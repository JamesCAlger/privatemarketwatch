"""Extract fund-level financials from companyfacts + N-PORT fund info.

Merges BDC balance-sheet data (companyfacts API, back to ~2012) with
N-PORT fundInfo (balance sheet, monthly returns, flows since 2019q4) into
a single ``fund_financials.csv`` -- one row per CIK per quarter.

Public API
----------
build_fund_financials(income_df, nport_fund_info_df, universe_df, client)
    -> pd.DataFrame
"""

import json
import logging
import time
import zipfile
from typing import Optional

import duckdb
import pandas as pd

from pipeline.config import (
    BDC_FUND_INCOME_FILE,
    COMBINED_UNIVERSE_FILE,
    COMPANYFACTS_CACHE_DIR,
    FUND_FINANCIALS_FILE,
    FUND_IDENTITY_FILE,
    NCEN_QUARTERS,
    NPORT_FUND_INFO_FILE,
    SEC_DATASETS_DIR,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Output schema
# ---------------------------------------------------------------------------
OUTPUT_COLUMNS = [
    "cik", "entity_name", "vehicle_type", "source",
    "report_quarter", "report_date",
    "total_assets", "net_assets", "total_liabilities",
    "nav_per_share", "shares_outstanding", "borrowings",
    "total_investment_income", "net_investment_income",
    "management_fee", "incentive_fee", "interest_expense", "total_expenses",
    "monthly_return_1", "monthly_return_2", "monthly_return_3",
    "monthly_flow_sales_1", "monthly_flow_sales_2", "monthly_flow_sales_3",
    "monthly_flow_redemptions_1", "monthly_flow_redemptions_2",
    "monthly_flow_redemptions_3",
    "leverage_ratio", "quarterly_return",
    "management_fee_pct", "expense_ratio_pct",
    "market_price_per_share", "monthly_avg_net_assets",
    # Distributions (BDC from companyfacts)
    "distribution_per_share",
    "dividends_declared_per_share",
    "distribution_ordinary_income",
    "distribution_return_of_capital",
    # Performance
    "total_return_pct",
    "gain_loss_per_share",
    "nav_change_per_share",
    "income_per_share",
    "income_yield_pct",
    "gross_investment_income",
    # Portfolio & risk
    "portfolio_turnover",
    "asset_coverage_ratio",
    "unfunded_commitments",
    "unrealized_appreciation",
    "unrealized_depreciation",
    "debt_weighted_avg_rate",
    # N-PORT risk
    "total_borrowings_detail",
    "dv01_3mon", "dv01_1yr", "dv01_5yr", "dv01_10yr", "dv01_30yr",
    "dv100_3mon", "dv100_1yr", "dv100_5yr", "dv100_10yr", "dv100_30yr",
    # N-PORT credit spread risk
    "credit_spread_3mon_invest", "credit_spread_1yr_invest",
    "credit_spread_5yr_invest", "credit_spread_10yr_invest",
    "credit_spread_30yr_invest",
    "credit_spread_3mon_noninvest", "credit_spread_1yr_noninvest",
    "credit_spread_5yr_noninvest", "credit_spread_10yr_noninvest",
    "credit_spread_30yr_noninvest",
    # N-CEN flags
    "is_debt_default", "is_dividend_arrears",
    "is_fund_of_fund", "is_non_diversified",
    # Computed
    "distribution_rate",
    "distribution_rate_proxy",
    "redemption_pressure",
    "annualized_return",
    "premium_discount_pct",
    "is_formation_stage",
]


# ---------------------------------------------------------------------------
# A. Companyfacts helpers
# ---------------------------------------------------------------------------

def _load_companyfacts_cached(cik: str) -> dict:
    """Read companyfacts JSON from disk cache. No network calls."""
    cik_padded = str(cik).zfill(10)
    cache_path = COMPANYFACTS_CACHE_DIR / f"{cik_padded}.json"
    if not cache_path.exists():
        return {}
    try:
        with open(cache_path) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def _months_between(start: str, end: str) -> int:
    """Return the number of months between two ISO date strings."""
    try:
        sy, sm = int(start[:4]), int(start[5:7])
        ey, em = int(end[:4]), int(end[5:7])
        return (ey - sy) * 12 + (em - sm)
    except (ValueError, IndexError):
        return 0


def _prior_quarter_end(end_date: str) -> str:
    """Subtract 3 months from an ISO end_date, snap to month-end.

    Financial period end dates are always month-end, so we return
    the last day of the target month. E.g. 2024-06-30 -> 2024-03-31.
    """
    import calendar
    try:
        y, m = int(end_date[:4]), int(end_date[5:7])
        m -= 3
        if m <= 0:
            m += 12
            y -= 1
        d = calendar.monthrange(y, m)[1]
        return f"{y:04d}-{m:02d}-{d:02d}"
    except (ValueError, IndexError):
        return ""


def _extract_duration_series(
    facts: dict,
    concept_names: list[str],
    unit_key: str = "USD",
) -> dict[str, float]:
    """Extract quarterly values from duration concepts.

    XBRL duration facts are often YTD cumulative. This function:
    1. Collects all (start, end, value) triples
    2. For each end_date, prefers the shortest period (single-quarter)
    3. When only YTD exists, deltas against prior quarter's YTD
    4. Fallback: divides by period length in quarters
    """
    if not facts:
        return {}

    all_facts = facts.get("facts", {})
    names_lower = {n.lower() for n in concept_names}

    # Collect all (start, end, value) triples across matching concepts
    # entries_by_end: {end_date: [(start_date, value), ...]}
    entries_by_end: dict[str, list[tuple[str, float]]] = {}
    best_count = 0

    for _taxonomy, concepts in all_facts.items():
        if not isinstance(concepts, dict):
            continue
        for concept_name, concept_data in concepts.items():
            if concept_name.lower() not in names_lower:
                continue
            units = concept_data.get("units", {})
            entries = units.get(unit_key, [])
            if not entries:
                continue

            # Check if this concept has enough data to be the best
            concept_entries: dict[str, list[tuple[str, float]]] = {}
            for entry in entries:
                end_date = entry.get("end")
                start_date = entry.get("start")
                val = entry.get("val")
                if not end_date or not start_date or val is None:
                    continue
                try:
                    fval = float(val)
                except (ValueError, TypeError):
                    continue
                concept_entries.setdefault(end_date, []).append(
                    (start_date, fval),
                )

            if not concept_entries:
                continue
            # Pick concept with most end_dates
            if len(concept_entries) > best_count:
                best_count = len(concept_entries)
                entries_by_end = concept_entries

    if not entries_by_end:
        return {}

    # Phase 2+3: For each end_date (chronological), convert to quarterly
    result: dict[str, float] = {}
    ytd_at: dict[tuple[str, str], float] = {}  # YTD values keyed by (start_date, end_date)

    for end_date in sorted(entries_by_end):
        candidates = entries_by_end[end_date]
        # Sort by period length ascending (shortest first)
        best_start, best_value = min(
            candidates, key=lambda x: _months_between(x[0], end_date),
        )
        span = _months_between(best_start, end_date)

        if span <= 4:
            # Already single-quarter (3-month or stub) -- use directly
            result[end_date] = best_value
        else:
            # YTD cumulative -- find longest-period entry with same start
            # for the current end_date (this IS the YTD value)
            ytd_at[(best_start, end_date)] = best_value

            # Try to find a longer (or same-start) entry that represents
            # the YTD at the same fiscal year for the prior quarter
            prior_end = _prior_quarter_end(end_date)

            # Look for prior quarter's YTD with the same start_date
            if (best_start, prior_end) in ytd_at:
                result[end_date] = best_value - ytd_at[(best_start, prior_end)]
            elif prior_end in entries_by_end:
                # Prior end exists but wasn't YTD -- check if any entry
                # shares same start_date (same fiscal year)
                prior_candidates = entries_by_end[prior_end]
                same_fy = [
                    (s, v) for s, v in prior_candidates if s == best_start
                ]
                if same_fy:
                    _, prior_ytd = max(
                        same_fy,
                        key=lambda x: _months_between(x[0], prior_end),
                    )
                    ytd_at[(best_start, prior_end)] = prior_ytd
                    result[end_date] = best_value - prior_ytd
                else:
                    # No same-FY prior YTD; divide by quarters
                    n_quarters = max(1, round(span / 3))
                    result[end_date] = best_value / n_quarters
            else:
                # No prior quarter data at all (Q1 or annual-only filer)
                n_quarters = max(1, round(span / 3))
                result[end_date] = best_value / n_quarters

    return result


def _extract_concept_series(
    facts: dict,
    concept_names: list[str],
    unit_key: str = "USD",
    instant_only: bool = True,
) -> dict[str, float]:
    """Extract time-series for the best-matching concept from companyfacts.

    Searches all taxonomies for exact concept name matches (case-insensitive).
    Filters by unit_key and instant/duration.  Returns the concept variant
    with the most data points as ``{end_date: value}``.
    When tied on data points, prefers the shorter concept name.
    """
    if not facts:
        return {}

    all_facts = facts.get("facts", {})
    best_series: dict[str, float] = {}
    best_concept_name: str = ""

    names_lower = {n.lower() for n in concept_names}

    for _taxonomy, concepts in all_facts.items():
        if not isinstance(concepts, dict):
            continue
        for concept_name, concept_data in concepts.items():
            if concept_name.lower() not in names_lower:
                continue

            units = concept_data.get("units", {})
            entries = units.get(unit_key, [])
            if not entries:
                continue

            series: dict[str, float] = {}
            for entry in entries:
                end_date = entry.get("end")
                start_date = entry.get("start")
                val = entry.get("val")
                if not end_date or val is None:
                    continue
                if instant_only and start_date:
                    continue
                if not instant_only and not start_date:
                    continue
                try:
                    series[end_date] = float(val)
                except (ValueError, TypeError):
                    continue

            if not series:
                continue
            # Pick by most data points; tiebreak by shorter concept name
            if (len(series) > len(best_series)
                    or (len(series) == len(best_series)
                        and len(concept_name) < len(best_concept_name))):
                best_series = series
                best_concept_name = concept_name

    return best_series


# Concept definitions for BDC balance sheet
_BALANCE_SHEET_CONCEPTS = {
    "total_assets": {
        "exact": ["Assets"],
        "fallback": ["TotalAssets", "AssetsNet"],
        "unit": "USD", "instant": True,
    },
    "total_liabilities": {
        "exact": ["Liabilities"],
        "fallback": ["TotalLiabilities"],
        "unit": "USD", "instant": True,
    },
    "net_assets": {
        "exact": ["StockholdersEquity", "NetAssetsOrNetAssets",
                  "MembersCapital", "PartnersCapital"],
        "fallback": [],
        "unit": "USD", "instant": True,
    },
    "nav_per_share": {
        "exact": ["NetAssetValuePerShare"],
        "fallback": [],
        "unit": "USD/shares", "instant": True,
    },
    "shares_outstanding": {
        "exact": ["CommonStockSharesOutstanding",
                  "EntityCommonStockSharesOutstanding"],
        "fallback": [],
        "unit": "shares", "instant": True,
    },
    "borrowings": {
        "exact": ["LongTermDebt", "LineOfCredit",
                  "DebtInstrumentCarryingAmount"],
        "fallback": [],
        "unit": "USD", "instant": True,
    },
}


# Distribution & dividend concepts (instant = per-share snapshots)
_DISTRIBUTION_CONCEPTS = {
    "distribution_per_share": {
        "exact": ["InvestmentCompanyDistributionToShareholdersPerShare"],
        "fallback": [],
        "unit": "USD/shares", "instant": False,
    },
    "dividends_declared_per_share": {
        "exact": ["CommonStockDividendsPerShareDeclared"],
        "fallback": [],
        "unit": "USD/shares", "instant": False,
    },
    "distribution_ordinary_income": {
        "exact": ["InvestmentCompanyDistributionOrdinaryIncome"],
        "fallback": [],
        "unit": "USD", "instant": False,
    },
    "distribution_return_of_capital": {
        "exact": ["InvestmentCompanyTaxReturnOfCapitalDistribution"],
        "fallback": [],
        "unit": "USD", "instant": False,
    },
}

# Performance concepts (duration = period totals)
_PERFORMANCE_CONCEPTS = {
    "total_return_pct": {
        "exact": ["InvestmentCompanyTotalReturn"],
        "fallback": [],
        "unit": "pure", "instant": False,
    },
    "gain_loss_per_share": {
        "exact": ["InvestmentCompanyGainLossOnInvestmentPerShare"],
        "fallback": [],
        "unit": "USD/shares", "instant": False,
    },
    "nav_change_per_share": {
        "exact": [
            "InvestmentCompanyNetAssetValuePerSharePeriodIncreaseDecrease",
        ],
        "fallback": [],
        "unit": "USD/shares", "instant": False,
    },
}

# Income & yield concepts (duration)
_INCOME_CONCEPTS = {
    "income_per_share": {
        "exact": ["InvestmentCompanyInvestmentIncomeLossPerShare"],
        "fallback": [],
        "unit": "USD/shares", "instant": False,
    },
    "income_yield_pct": {
        "exact": ["InvestmentCompanyInvestmentIncomeLossRatio"],
        "fallback": [],
        "unit": "pure", "instant": False,
    },
    "gross_investment_income": {
        "exact": ["GrossInvestmentIncomeOperating"],
        "fallback": [],
        "unit": "USD", "instant": False,
    },
}

# Portfolio & risk concepts (mixed instant/duration)
_PORTFOLIO_CONCEPTS = {
    "portfolio_turnover": {
        "exact": ["InvestmentCompanyPortfolioTurnover"],
        "fallback": [],
        "unit": "pure", "instant": False,
    },
    "asset_coverage_ratio": {
        "exact": [
            "InvestmentCompanySeniorSecurityIndebtednessAssetCoverageRatio",
        ],
        "fallback": [],
        "unit": "pure", "instant": True,
    },
    "unfunded_commitments": {
        "exact": ["InvestmentCompanyFinancialCommitmentToInvesteeFutureAmount"],
        "fallback": [],
        "unit": "USD", "instant": True,
    },
    "unrealized_appreciation": {
        "exact": ["TaxBasisOfInvestmentsGrossUnrealizedAppreciation"],
        "fallback": [],
        "unit": "USD", "instant": True,
    },
    "unrealized_depreciation": {
        "exact": ["TaxBasisOfInvestmentsGrossUnrealizedDepreciation"],
        "fallback": [],
        "unit": "USD", "instant": True,
    },
    "debt_weighted_avg_rate": {
        "exact": ["DebtWeightedAverageInterestRate"],
        "fallback": [],
        "unit": "pure", "instant": True,
    },
}

# All extended concept groups (beyond balance sheet)
_EXTENDED_CONCEPT_GROUPS = [
    _DISTRIBUTION_CONCEPTS,
    _PERFORMANCE_CONCEPTS,
    _INCOME_CONCEPTS,
    _PORTFOLIO_CONCEPTS,
]

# Fields that are in extended concept groups (used in extraction)
_EXTENDED_FIELDS = sorted({
    field
    for group in _EXTENDED_CONCEPT_GROUPS
    for field in group
})


def _extract_bdc_balance_sheet(cik: str, facts: dict) -> list[dict]:
    """Extract balance-sheet + extended time series from one CIK's companyfacts."""
    if not facts:
        return []

    # Extract each concept series (exact match first, then fallback)
    concept_series: dict[str, dict[str, float]] = {}

    # Balance sheet (instant)
    for field, spec in _BALANCE_SHEET_CONCEPTS.items():
        series = _extract_concept_series(
            facts, spec["exact"], spec["unit"], spec["instant"],
        )
        if not series and spec.get("fallback"):
            series = _extract_concept_series(
                facts, spec["fallback"], spec["unit"], spec["instant"],
            )
        concept_series[field] = series

    # Extended concepts (distributions, performance, income, portfolio)
    for group in _EXTENDED_CONCEPT_GROUPS:
        for field, spec in group.items():
            if spec["instant"]:
                series = _extract_concept_series(
                    facts, spec["exact"], spec["unit"], True,
                )
                if not series and spec.get("fallback"):
                    series = _extract_concept_series(
                        facts, spec["fallback"], spec["unit"], True,
                    )
            else:
                # Duration concepts: use YTD -> quarterly conversion
                series = _extract_duration_series(
                    facts, spec["exact"], spec["unit"],
                )
                if not series and spec.get("fallback"):
                    series = _extract_duration_series(
                        facts, spec["fallback"], spec["unit"],
                    )
            concept_series[field] = series

    # Collect all end_dates
    all_dates: set[str] = set()
    for series in concept_series.values():
        all_dates.update(series.keys())

    if not all_dates:
        return []

    # Build rows
    rows = []
    cik_padded = str(cik).zfill(10)
    for end_date in sorted(all_dates):
        row: dict = {"cik": cik_padded, "report_date": end_date}
        has_value = False
        for field, series in concept_series.items():
            val = series.get(end_date)
            row[field] = val
            if val is not None:
                has_value = True
        if has_value:
            rows.append(row)

    return rows


def _extract_all_companyfacts(
    bdc_ciks: list[str],
    client: object | None = None,
) -> pd.DataFrame:
    """Extract balance-sheet data for all BDC CIKs from companyfacts.

    Reads from disk cache first.  For CIKs with no cache file, fetches
    from the SEC companyfacts API and caches the result (rate-limited,
    ~0.11 s per request).
    """
    from pipeline.validate_html_template import _fetch_companyfacts

    all_rows: list[dict] = []

    # Identify CIKs needing fetch
    uncached = []
    for cik in bdc_ciks:
        cik_padded = str(cik).zfill(10)
        cache_path = COMPANYFACTS_CACHE_DIR / f"{cik_padded}.json"
        if not cache_path.exists():
            uncached.append(cik)

    if uncached:
        logger.info(
            "Companyfacts: %d/%d BDC CIKs uncached, fetching from SEC...",
            len(uncached), len(bdc_ciks),
        )
        # Use provided client, or create one shared client for all fetches
        fetch_client = client
        if fetch_client is None:
            from pipeline.edgar_client import EdgarClient
            fetch_client = EdgarClient()

        for i, cik in enumerate(uncached, 1):
            _fetch_companyfacts(cik, fetch_client)
            if i % 50 == 0:
                logger.info("  Fetched %d/%d...", i, len(uncached))
        logger.info("Companyfacts: fetched %d new CIKs from SEC", len(uncached))

    # Now read everything from cache
    for cik in bdc_ciks:
        facts = _load_companyfacts_cached(cik)
        if not facts:
            continue
        rows = _extract_bdc_balance_sheet(cik, facts)
        all_rows.extend(rows)

    if not all_rows:
        return pd.DataFrame(columns=[
            "cik", "report_date", "total_assets", "total_liabilities",
            "net_assets", "nav_per_share", "shares_outstanding", "borrowings",
        ] + _EXTENDED_FIELDS)

    return pd.DataFrame(all_rows)


# ---------------------------------------------------------------------------
# B. N-PORT fund info aggregation
# ---------------------------------------------------------------------------

def _prepare_nport(
    nport_fund_info_df: pd.DataFrame,
    ncen_df: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Aggregate N-PORT fund info from series-level to CIK-quarter level.

    Parameters
    ----------
    nport_fund_info_df : DataFrame
        Raw N-PORT fund info rows.
    ncen_df : DataFrame, optional
        N-CEN financial data from ``_parse_ncen_financials()``.
        When provided, enriches N-PORT rows with management_fee_pct,
        expense_ratio_pct, nav_per_share, market_price_per_share,
        monthly_avg_net_assets via temporal LEFT JOIN.
    """
    if nport_fund_info_df is None or nport_fund_info_df.empty:
        return pd.DataFrame(columns=OUTPUT_COLUMNS)

    con = duckdb.connect()
    con.register("nport_raw", nport_fund_info_df)

    has_ncen = ncen_df is not None and not ncen_df.empty
    if has_ncen:
        con.register("ncen", ncen_df)

    # Borrowing detail + DV01 from N-PORT fund_info (if columns exist)
    _has_borrow = (
        "total_borrowings_detail" in nport_fund_info_df.columns
        if nport_fund_info_df is not None and not nport_fund_info_df.empty
        else False
    )
    _borrow_agg = (
        "SUM(TRY_CAST(total_borrowings_detail AS DOUBLE))"
        " AS total_borrowings_detail"
        if _has_borrow
        else "CAST(NULL AS DOUBLE) AS total_borrowings_detail"
    )
    # DV01/DV100 columns (10 total)
    _DV_COLS = [
        "dv01_3mon", "dv01_1yr", "dv01_5yr", "dv01_10yr", "dv01_30yr",
        "dv100_3mon", "dv100_1yr", "dv100_5yr", "dv100_10yr", "dv100_30yr",
    ]
    _has_dv01 = (
        "dv01_1yr" in nport_fund_info_df.columns
        if nport_fund_info_df is not None and not nport_fund_info_df.empty
        else False
    )
    _dv_parts = []
    for dvc in _DV_COLS:
        if _has_dv01 and dvc in nport_fund_info_df.columns:
            _dv_parts.append(
                f"SUM(TRY_CAST({dvc} AS DOUBLE)) AS {dvc}")
        else:
            _dv_parts.append(f"CAST(NULL AS DOUBLE) AS {dvc}")
    _dv01_cols = ",\n            ".join(_dv_parts)

    # Credit spread columns (10 total)
    _CS_COLS = [
        "credit_spread_3mon_invest", "credit_spread_1yr_invest",
        "credit_spread_5yr_invest", "credit_spread_10yr_invest",
        "credit_spread_30yr_invest",
        "credit_spread_3mon_noninvest", "credit_spread_1yr_noninvest",
        "credit_spread_5yr_noninvest", "credit_spread_10yr_noninvest",
        "credit_spread_30yr_noninvest",
    ]
    _has_cs = (
        "credit_spread_3mon_invest" in nport_fund_info_df.columns
        if nport_fund_info_df is not None and not nport_fund_info_df.empty
        else False
    )
    _cs_parts = []
    for csc in _CS_COLS:
        if _has_cs and csc in nport_fund_info_df.columns:
            _cs_parts.append(
                f"SUM(TRY_CAST({csc} AS DOUBLE)) AS {csc}")
        else:
            _cs_parts.append(f"CAST(NULL AS DOUBLE) AS {csc}")
    _cs_cols = ",\n            ".join(_cs_parts)

    # Base CTE: aggregate N-PORT to CIK-quarter
    base_cte = f"""
    WITH series_dedup AS (
        -- Dedup class-level rows: same (accession_number, series_name)
        SELECT DISTINCT ON (accession_number, series_name) *
        FROM nport_raw
        ORDER BY accession_number, series_name, class_id
    ),
    cik_quarter AS (
        SELECT
            LPAD(CAST(cik AS VARCHAR), 10, '0') AS cik,
            MAX(registrant_name) AS entity_name,
            quarter AS report_quarter,
            MAX(report_date) AS report_date,
            SUM(TRY_CAST(total_assets AS DOUBLE)) AS total_assets,
            SUM(TRY_CAST(net_assets AS DOUBLE)) AS net_assets,
            SUM(TRY_CAST(total_liabilities AS DOUBLE)) AS total_liabilities,
            SUM(
                COALESCE(TRY_CAST(borrowing_pay_within_1yr AS DOUBLE), 0)
                + COALESCE(TRY_CAST(borrowing_pay_after_1yr AS DOUBLE), 0)
            ) AS borrowings,
            -- Weighted-avg monthly returns by net_assets
            SUM(TRY_CAST(monthly_total_return1 AS DOUBLE)
                * TRY_CAST(net_assets AS DOUBLE))
                / NULLIF(SUM(TRY_CAST(net_assets AS DOUBLE)), 0)
                AS monthly_return_1,
            SUM(TRY_CAST(monthly_total_return2 AS DOUBLE)
                * TRY_CAST(net_assets AS DOUBLE))
                / NULLIF(SUM(TRY_CAST(net_assets AS DOUBLE)), 0)
                AS monthly_return_2,
            SUM(TRY_CAST(monthly_total_return3 AS DOUBLE)
                * TRY_CAST(net_assets AS DOUBLE))
                / NULLIF(SUM(TRY_CAST(net_assets AS DOUBLE)), 0)
                AS monthly_return_3,
            -- Sum flows
            SUM(TRY_CAST(sales_flow_mon1 AS DOUBLE)) AS monthly_flow_sales_1,
            SUM(TRY_CAST(sales_flow_mon2 AS DOUBLE)) AS monthly_flow_sales_2,
            SUM(TRY_CAST(sales_flow_mon3 AS DOUBLE)) AS monthly_flow_sales_3,
            SUM(TRY_CAST(redemption_flow_mon1 AS DOUBLE))
                AS monthly_flow_redemptions_1,
            SUM(TRY_CAST(redemption_flow_mon2 AS DOUBLE))
                AS monthly_flow_redemptions_2,
            SUM(TRY_CAST(redemption_flow_mon3 AS DOUBLE))
                AS monthly_flow_redemptions_3,
            -- N-PORT Part B additional tables
            {_borrow_agg},
            {_dv01_cols},
            {_cs_cols}
        FROM series_dedup
        GROUP BY cik, quarter
    )"""

    # NULL columns for BDC-only companyfacts fields in N-PORT rows
    _nport_ext_nulls = "\n        ".join(
        f"CAST(NULL AS DOUBLE) AS {f},"
        for f in _EXTENDED_FIELDS
    )

    # Common computed metrics for N-PORT
    _nport_computed = """
        -- Computed: distribution_rate (NULL for N-PORT; use proxy)
        CAST(NULL AS DOUBLE) AS distribution_rate,
        -- distribution_rate_proxy = (reinvestment_flow * 4) / net_assets * 100
        CASE
            WHEN ({sales_total} - {redeem_total}) > 0
                AND {net_assets_ref} IS NOT NULL AND {net_assets_ref} > 0
            THEN (({sales_total} - {redeem_total}) * 4.0)
                 / {net_assets_ref} * 100.0
            ELSE NULL
        END AS distribution_rate_proxy,
        -- redemption_pressure = total_redemptions / net_assets * 100
        CASE
            WHEN {net_assets_ref} IS NOT NULL AND {net_assets_ref} > 0
            THEN ({redeem_total}) / {net_assets_ref} * 100.0
            ELSE NULL
        END AS redemption_pressure,
        -- annualized_return = ((1 + quarterly/100)^4 - 1) * 100
        CASE
            WHEN {qr_ref} IS NOT NULL
            THEN (POWER(1 + {qr_ref} / 100.0, 4) - 1) * 100.0
            ELSE NULL
        END AS annualized_return,
        -- premium/discount (N-PORT: from N-CEN market_price)
        CASE
            WHEN {mkt_ref} IS NOT NULL
                AND {nav_ref} IS NOT NULL AND {nav_ref} > 0
            THEN ({mkt_ref} - {nav_ref}) / {nav_ref} * 100.0
            ELSE NULL
        END AS premium_discount_pct,
        -- Formation-stage flag (always FALSE for N-PORT)
        CAST(FALSE AS BOOLEAN) AS is_formation_stage
    """

    if has_ncen:
        qr_sql = """CASE
            WHEN cq.monthly_return_1 IS NOT NULL
                AND cq.monthly_return_2 IS NOT NULL
                AND cq.monthly_return_3 IS NOT NULL
            THEN (
                (1 + cq.monthly_return_1 / 100.0)
                * (1 + cq.monthly_return_2 / 100.0)
                * (1 + cq.monthly_return_3 / 100.0)
                - 1
            ) * 100.0
            ELSE NULL
        END"""

        computed = _nport_computed.format(
            sales_total=(
                "COALESCE(cq.monthly_flow_sales_1, 0)"
                " + COALESCE(cq.monthly_flow_sales_2, 0)"
                " + COALESCE(cq.monthly_flow_sales_3, 0)"
            ),
            redeem_total=(
                "COALESCE(cq.monthly_flow_redemptions_1, 0)"
                " + COALESCE(cq.monthly_flow_redemptions_2, 0)"
                " + COALESCE(cq.monthly_flow_redemptions_3, 0)"
            ),
            net_assets_ref="cq.net_assets",
            qr_ref=qr_sql,
            mkt_ref="nr.market_price_per_share",
            nav_ref="COALESCE(nr.ncen_nav, CAST(NULL AS DOUBLE))",
        )

        # DV + CS column references for SELECT (from cik_quarter)
        _dv_select = ",\n        ".join(f"cq.{c}" for c in _DV_COLS)
        _cs_select = ",\n        ".join(f"cq.{c}" for c in _CS_COLS)

        sql = f"""{base_cte},
    ncen_ranked AS (
        SELECT
            nc.cik,
            cq.report_quarter AS nport_quarter,
            nc.management_fee_pct,
            nc.expense_ratio_pct,
            nc.nav_per_share AS ncen_nav,
            nc.market_price_per_share,
            nc.monthly_avg_net_assets,
            nc.is_debt_default,
            nc.is_dividend_arrears,
            nc.is_fund_of_fund,
            nc.is_non_diversified,
            ROW_NUMBER() OVER (
                PARTITION BY nc.cik, cq.report_quarter
                ORDER BY nc.report_date DESC
            ) AS rn
        FROM cik_quarter cq
        JOIN ncen nc
            ON cq.cik = nc.cik
            AND CAST(nc.report_date AS DATE) <= CAST(cq.report_date AS DATE)
    )
    SELECT
        cq.cik, cq.entity_name, cq.report_quarter, cq.report_date,
        cq.total_assets, cq.net_assets, cq.total_liabilities,
        COALESCE(nr.ncen_nav, CAST(NULL AS DOUBLE)) AS nav_per_share,
        CAST(NULL AS DOUBLE) AS shares_outstanding,
        cq.borrowings,
        CAST(NULL AS DOUBLE) AS total_investment_income,
        CAST(NULL AS DOUBLE) AS net_investment_income,
        CAST(NULL AS DOUBLE) AS management_fee,
        CAST(NULL AS DOUBLE) AS incentive_fee,
        CAST(NULL AS DOUBLE) AS interest_expense,
        CAST(NULL AS DOUBLE) AS total_expenses,
        cq.monthly_return_1, cq.monthly_return_2, cq.monthly_return_3,
        cq.monthly_flow_sales_1, cq.monthly_flow_sales_2,
        cq.monthly_flow_sales_3,
        cq.monthly_flow_redemptions_1, cq.monthly_flow_redemptions_2,
        cq.monthly_flow_redemptions_3,
        CASE WHEN cq.total_assets IS NOT NULL AND cq.total_assets > 0
            THEN LEAST(cq.borrowings / cq.total_assets, 2.0)
            ELSE NULL
        END AS leverage_ratio,
        {qr_sql} AS quarterly_return,
        'nport' AS source,
        nr.management_fee_pct,
        nr.expense_ratio_pct,
        nr.market_price_per_share,
        nr.monthly_avg_net_assets,
        -- Extended companyfacts (NULL for N-PORT)
        {_nport_ext_nulls}
        -- N-PORT risk
        cq.total_borrowings_detail,
        {_dv_select},
        {_cs_select},
        -- N-CEN flags
        nr.is_debt_default,
        nr.is_dividend_arrears,
        nr.is_fund_of_fund,
        nr.is_non_diversified,
        {computed}
    FROM cik_quarter cq
    LEFT JOIN ncen_ranked nr
        ON cq.cik = nr.cik
        AND cq.report_quarter = nr.nport_quarter
        AND nr.rn = 1
    """
    else:
        qr_sql = """CASE
            WHEN monthly_return_1 IS NOT NULL
                AND monthly_return_2 IS NOT NULL
                AND monthly_return_3 IS NOT NULL
            THEN (
                (1 + monthly_return_1 / 100.0)
                * (1 + monthly_return_2 / 100.0)
                * (1 + monthly_return_3 / 100.0)
                - 1
            ) * 100.0
            ELSE NULL
        END"""

        computed = _nport_computed.format(
            sales_total=(
                "COALESCE(monthly_flow_sales_1, 0)"
                " + COALESCE(monthly_flow_sales_2, 0)"
                " + COALESCE(monthly_flow_sales_3, 0)"
            ),
            redeem_total=(
                "COALESCE(monthly_flow_redemptions_1, 0)"
                " + COALESCE(monthly_flow_redemptions_2, 0)"
                " + COALESCE(monthly_flow_redemptions_3, 0)"
            ),
            net_assets_ref="net_assets",
            qr_ref=qr_sql,
            mkt_ref="CAST(NULL AS DOUBLE)",
            nav_ref="CAST(NULL AS DOUBLE)",
        )

        # DV + CS column references for no-ncen SELECT
        # (from cik_quarter, no table alias needed)
        _dv_select_noalias = ",\n        ".join(_DV_COLS)
        _cs_select_noalias = ",\n        ".join(_CS_COLS)

        sql = f"""{base_cte}
    SELECT
        cik, entity_name, report_quarter, report_date,
        total_assets, net_assets, total_liabilities,
        CAST(NULL AS DOUBLE) AS nav_per_share,
        CAST(NULL AS DOUBLE) AS shares_outstanding,
        borrowings,
        CAST(NULL AS DOUBLE) AS total_investment_income,
        CAST(NULL AS DOUBLE) AS net_investment_income,
        CAST(NULL AS DOUBLE) AS management_fee,
        CAST(NULL AS DOUBLE) AS incentive_fee,
        CAST(NULL AS DOUBLE) AS interest_expense,
        CAST(NULL AS DOUBLE) AS total_expenses,
        monthly_return_1, monthly_return_2, monthly_return_3,
        monthly_flow_sales_1, monthly_flow_sales_2, monthly_flow_sales_3,
        monthly_flow_redemptions_1, monthly_flow_redemptions_2,
        monthly_flow_redemptions_3,
        CASE WHEN total_assets IS NOT NULL AND total_assets > 0
            THEN LEAST(borrowings / total_assets, 2.0)
            ELSE NULL
        END AS leverage_ratio,
        {qr_sql} AS quarterly_return,
        'nport' AS source,
        CAST(NULL AS DOUBLE) AS management_fee_pct,
        CAST(NULL AS DOUBLE) AS expense_ratio_pct,
        CAST(NULL AS DOUBLE) AS market_price_per_share,
        CAST(NULL AS DOUBLE) AS monthly_avg_net_assets,
        -- Extended companyfacts (NULL for N-PORT)
        {_nport_ext_nulls}
        -- N-PORT risk
        total_borrowings_detail,
        {_dv_select_noalias},
        {_cs_select_noalias},
        -- N-CEN flags (NULL when no N-CEN data)
        CAST(NULL AS BOOLEAN) AS is_debt_default,
        CAST(NULL AS BOOLEAN) AS is_dividend_arrears,
        CAST(NULL AS BOOLEAN) AS is_fund_of_fund,
        CAST(NULL AS BOOLEAN) AS is_non_diversified,
        {computed}
    FROM cik_quarter
    """

    result = con.execute(sql).fetchdf()
    con.close()
    return result


# ---------------------------------------------------------------------------
# B2. N-CEN financial data extraction
# ---------------------------------------------------------------------------

_NCEN_DATE_MONTHS = {
    "JAN": "01", "FEB": "02", "MAR": "03", "APR": "04",
    "MAY": "05", "JUN": "06", "JUL": "07", "AUG": "08",
    "SEP": "09", "OCT": "10", "NOV": "11", "DEC": "12",
}


def _parse_ncen_date(raw: str) -> str | None:
    """Convert N-CEN date '31-JUL-2025' to ISO '2025-07-31'."""
    if not raw or not isinstance(raw, str):
        return None
    parts = raw.strip().split("-")
    if len(parts) != 3:
        return None
    day, mon, year = parts
    month_num = _NCEN_DATE_MONTHS.get(mon.upper())
    if not month_num:
        return None
    return f"{year}-{month_num}-{day.zfill(2)}"


def _parse_ncen_financials(universe_ciks: set[str]) -> pd.DataFrame:
    """Extract financial fields from cached N-CEN ZIPs for universe CIKs.

    N-CEN is filed annually by investment companies. FUND_REPORTED_INFO
    contains management fee (%), expense ratio (%), NAV per share, etc.
    Only N-2 registrants (closed-end funds) are extracted.

    Parameters
    ----------
    universe_ciks : set of str
        CIKs (10-digit padded) to include.

    Returns
    -------
    DataFrame with columns: cik, entity_name, report_date, report_quarter,
        management_fee_pct, expense_ratio_pct, nav_per_share,
        market_price_per_share, monthly_avg_net_assets.
    """
    empty_cols = [
        "cik", "entity_name", "report_date", "report_quarter",
        "management_fee_pct", "expense_ratio_pct", "nav_per_share",
        "market_price_per_share", "monthly_avg_net_assets",
        "is_debt_default", "is_dividend_arrears",
        "is_fund_of_fund", "is_non_diversified",
    ]
    if not universe_ciks:
        return pd.DataFrame(columns=empty_cols)

    all_rows: list[dict] = []

    for quarter in NCEN_QUARTERS:
        year, q = quarter[:4], quarter[5:]
        zip_path = SEC_DATASETS_DIR / f"{year}q{q}_ncen.zip"
        if not zip_path.exists():
            continue

        try:
            with zipfile.ZipFile(zip_path) as zf:
                names = zf.namelist()
                if ("FUND_REPORTED_INFO.tsv" not in names
                        or "SUBMISSION.tsv" not in names):
                    continue

                def _read_tsv(filename: str) -> pd.DataFrame:
                    with zf.open(filename) as fh:
                        return pd.read_csv(
                            fh, sep="\t", dtype=str, on_bad_lines="skip",
                        )

                fri = _read_tsv("FUND_REPORTED_INFO.tsv")
                sub = _read_tsv("SUBMISSION.tsv")

                reg = None
                if "REGISTRANT.tsv" in names:
                    reg = _read_tsv("REGISTRANT.tsv")

                # Join FRI -> SUBMISSION for CIK + report date
                if "ACCESSION_NUMBER" not in fri.columns:
                    continue
                merged = fri.merge(
                    sub[["ACCESSION_NUMBER", "CIK", "REPORT_ENDING_PERIOD"]],
                    on="ACCESSION_NUMBER", how="left",
                )

                # Join -> REGISTRANT for name + company type filter
                if (reg is not None
                        and "INVESTMENT_COMPANY_TYPE" in reg.columns):
                    reg_cols = ["ACCESSION_NUMBER", "REGISTRANT_NAME",
                                "INVESTMENT_COMPANY_TYPE"]
                    reg_cols = [c for c in reg_cols if c in reg.columns]
                    merged = merged.merge(
                        reg[reg_cols], on="ACCESSION_NUMBER", how="left",
                    )
                else:
                    continue  # Can't filter to N-2 without company type

                # Filter to N-2 registrants
                if "INVESTMENT_COMPANY_TYPE" not in merged.columns:
                    continue
                merged = merged[
                    merged["INVESTMENT_COMPANY_TYPE"] == "N-2"
                ]

                if merged.empty:
                    continue

                # Filter to universe CIKs
                merged["cik_padded"] = (
                    merged["CIK"].str.strip().str.zfill(10)
                )
                merged = merged[merged["cik_padded"].isin(universe_ciks)]

                if merged.empty:
                    continue

                for _, row in merged.iterrows():
                    report_date = _parse_ncen_date(
                        row.get("REPORT_ENDING_PERIOD", ""),
                    )
                    if not report_date:
                        continue

                    cik = row["cik_padded"]
                    entity_name = str(
                        row.get("REGISTRANT_NAME", "")
                    ).strip()

                    # Parse date to derive quarter
                    try:
                        month = int(report_date.split("-")[1])
                        year_str = report_date.split("-")[0]
                        q_num = (month - 1) // 3 + 1
                        report_quarter = f"{year_str}q{q_num}"
                    except (ValueError, IndexError):
                        continue

                    def _to_float(val):
                        if val is None or str(val).strip() in ("", "nan"):
                            return None
                        try:
                            return float(val)
                        except (ValueError, TypeError):
                            return None

                    all_rows.append({
                        "cik": cik,
                        "entity_name": entity_name,
                        "report_date": report_date,
                        "report_quarter": report_quarter,
                        "management_fee_pct": _to_float(
                            row.get("MANAGEMENT_FEE"),
                        ),
                        "expense_ratio_pct": _to_float(
                            row.get("NET_OPERATING_EXPENSES"),
                        ),
                        "nav_per_share": _to_float(
                            row.get("NAV_PER_SHARE"),
                        ),
                        "market_price_per_share": _to_float(
                            row.get("MARKET_PRICE_PER_SHARE"),
                        ),
                        "monthly_avg_net_assets": _to_float(
                            row.get("MONTHLY_AVG_NET_ASSETS"),
                        ),
                        "is_debt_default": (
                            str(row.get("IS_LONG_TERM_DEBT_DEFAULT", ""))
                            .strip().upper() == "Y"
                        ),
                        "is_dividend_arrears": (
                            str(row.get(
                                "IS_ACCUM_DIVIDEND_IN_ARREARS", ""))
                            .strip().upper() == "Y"
                        ),
                        "is_fund_of_fund": (
                            str(row.get("IS_FUND_OF_FUND", ""))
                            .strip().upper() == "Y"
                        ),
                        "is_non_diversified": (
                            str(row.get("IS_NON_DIVERSIFIED", ""))
                            .strip().upper() == "Y"
                        ),
                    })
        except (zipfile.BadZipFile, OSError) as exc:
            logger.warning("Failed to read %s: %s", zip_path.name, exc)
            continue

    if not all_rows:
        return pd.DataFrame(columns=empty_cols)

    df = pd.DataFrame(all_rows)

    # Dedup by (cik, report_date), keep first occurrence
    df = df.drop_duplicates(subset=["cik", "report_date"], keep="first")

    # ----- Guard rails for N-CEN data quality -----
    # 1. Negative management_fee_pct -> 0 (fee waivers)
    neg_fee = (df["management_fee_pct"] < 0).sum()
    if neg_fee:
        logger.info("N-CEN: clamped %d negative management_fee_pct to 0", neg_fee)
        df.loc[df["management_fee_pct"] < 0, "management_fee_pct"] = 0.0

    # 2. Expense ratio > 20% -> NULL (dollar value filed as pct, or stub)
    high_exp = (df["expense_ratio_pct"] > 20).sum()
    if high_exp:
        logger.info("N-CEN: nulled %d expense_ratio_pct > 20%%", high_exp)
        df.loc[df["expense_ratio_pct"] > 20, "expense_ratio_pct"] = None

    # 3. Zero NAV per share -> NULL (not yet launched or error)
    zero_nav = (df["nav_per_share"] == 0).sum()
    if zero_nav:
        logger.info("N-CEN: nulled %d zero nav_per_share", zero_nav)
        df.loc[df["nav_per_share"] == 0, "nav_per_share"] = None

    # 4. Zero market_price_per_share -> NULL (non-listed funds)
    zero_mkt = (df["market_price_per_share"] == 0).sum()
    if zero_mkt:
        logger.info(
            "N-CEN: nulled %d zero market_price_per_share", zero_mkt,
        )
        df.loc[df["market_price_per_share"] == 0,
               "market_price_per_share"] = None

    return df


# ---------------------------------------------------------------------------
# B2b. N-CEN identity extraction (adviser, ticker)
# ---------------------------------------------------------------------------

_IDENTITY_COLUMNS = [
    "cik", "entity_name", "adviser_name", "adviser_crd_number",
    "ticker", "class_name",
]


def _parse_ncen_identity(universe_ciks: set[str]) -> pd.DataFrame:
    """Extract fund identity from N-CEN ADVISER and SHARES_OUTSTANDING tables.

    Returns one row per CIK with the latest available identity fields.
    Saved to ``fund_identity.csv``.

    Parameters
    ----------
    universe_ciks : set of str
        CIKs (10-digit padded) to include.

    Returns
    -------
    DataFrame with columns: cik, entity_name, adviser_name,
        adviser_crd_number, ticker, class_name.
    """
    if not universe_ciks:
        return pd.DataFrame(columns=_IDENTITY_COLUMNS)

    all_rows: list[dict] = []

    for quarter in NCEN_QUARTERS:
        year, q = quarter[:4], quarter[5:]
        zip_path = SEC_DATASETS_DIR / f"{year}q{q}_ncen.zip"
        if not zip_path.exists():
            continue

        try:
            with zipfile.ZipFile(zip_path) as zf:
                names = zf.namelist()
                if "SUBMISSION.tsv" not in names:
                    continue

                def _read_tsv(filename: str) -> pd.DataFrame:
                    with zf.open(filename) as fh:
                        return pd.read_csv(
                            fh, sep="\t", dtype=str, on_bad_lines="skip",
                        )

                sub = _read_tsv("SUBMISSION.tsv")

                reg = None
                if "REGISTRANT.tsv" in names:
                    reg = _read_tsv("REGISTRANT.tsv")

                if reg is None or "INVESTMENT_COMPANY_TYPE" not in reg.columns:
                    continue

                # Filter to N-2 registrants in universe
                merged_sub = sub[["ACCESSION_NUMBER", "CIK"]].copy()
                merged_sub["cik_padded"] = (
                    merged_sub["CIK"].str.strip().str.zfill(10)
                )
                merged_sub = merged_sub[
                    merged_sub["cik_padded"].isin(universe_ciks)
                ]
                if merged_sub.empty:
                    continue

                acc_set = set(merged_sub["ACCESSION_NUMBER"].unique())

                # N-2 filter
                reg_n2 = reg[reg["INVESTMENT_COMPANY_TYPE"] == "N-2"]
                n2_accs = set(reg_n2["ACCESSION_NUMBER"].unique())
                acc_set = acc_set & n2_accs
                if not acc_set:
                    continue

                # ADVISER table (joins via FUND_ID which embeds
                # accession number as first component)
                adviser_name = {}
                adviser_crd = {}
                if "ADVISER.tsv" in names:
                    adv = _read_tsv("ADVISER.tsv")
                    if not adv.empty and "FUND_ID" in adv.columns:
                        # Extract accession from FUND_ID
                        adv["_acc"] = (
                            adv["FUND_ID"]
                            .str.split("_")
                            .str[0]
                        )
                        adv = adv[adv["_acc"].isin(acc_set)]
                        for _, row in adv.iterrows():
                            acc = row.get("_acc", "")
                            name = str(
                                row.get("ADVISER_NAME", ""),
                            ).strip()
                            crd = str(
                                row.get("CRD_NUM", ""),
                            ).strip()
                            if acc and name and name != "nan":
                                adviser_name[acc] = name
                            if acc and crd and crd != "nan":
                                adviser_crd[acc] = crd

                # SHARES_OUTSTANDING table (has TICKER,
                # joins via FUND_ID)
                ticker_map = {}
                class_map = {}
                if "SHARES_OUTSTANDING.tsv" in names:
                    so = _read_tsv("SHARES_OUTSTANDING.tsv")
                    if not so.empty and "FUND_ID" in so.columns:
                        so["_acc"] = (
                            so["FUND_ID"]
                            .str.split("_")
                            .str[0]
                        )
                        so = so[so["_acc"].isin(acc_set)]
                        for _, row in so.iterrows():
                            acc = row.get("_acc", "")
                            tkr = str(row.get("TICKER", "")).strip()
                            cls = str(
                                row.get("CLASS_NAME", ""),
                            ).strip()
                            if acc and tkr and tkr != "nan":
                                ticker_map[acc] = tkr
                            if acc and cls and cls != "nan":
                                class_map[acc] = cls

                # Registrant name
                reg_name_map = {}
                if "REGISTRANT_NAME" in reg.columns:
                    for _, row in reg_n2.iterrows():
                        acc = row.get("ACCESSION_NUMBER", "")
                        if acc in acc_set:
                            rname = str(
                                row.get("REGISTRANT_NAME", ""),
                            ).strip()
                            if rname:
                                reg_name_map[acc] = rname

                # Build identity rows by CIK
                for _, srow in merged_sub.iterrows():
                    acc = srow["ACCESSION_NUMBER"]
                    if acc not in acc_set:
                        continue
                    cik = srow["cik_padded"]
                    all_rows.append({
                        "cik": cik,
                        "entity_name": reg_name_map.get(acc, ""),
                        "adviser_name": adviser_name.get(acc, ""),
                        "adviser_crd_number": adviser_crd.get(acc, ""),
                        "ticker": ticker_map.get(acc, ""),
                        "class_name": class_map.get(acc, ""),
                    })

        except (zipfile.BadZipFile, OSError) as exc:
            logger.warning("N-CEN identity: failed %s: %s",
                           zip_path.name, exc)
            continue

    if not all_rows:
        return pd.DataFrame(columns=_IDENTITY_COLUMNS)

    df = pd.DataFrame(all_rows)

    # Keep latest per CIK (later quarters override earlier)
    df = df.drop_duplicates(subset=["cik"], keep="last")

    # Save to disk
    df.to_csv(FUND_IDENTITY_FILE, index=False)
    logger.info("Fund identity: %d CIKs saved to %s",
                len(df), FUND_IDENTITY_FILE.name)

    return df


# ---------------------------------------------------------------------------
# B3. Standalone N-CEN rows (CIKs not in N-PORT or BDC)
# ---------------------------------------------------------------------------

def _prepare_ncen(
    ncen_df: pd.DataFrame,
    existing_ciks: set[str],
) -> pd.DataFrame:
    """Produce standalone rows for CIKs in N-CEN but not in N-PORT or BDC.

    Parameters
    ----------
    ncen_df : DataFrame
        Output of ``_parse_ncen_financials()``.
    existing_ciks : set of str
        CIKs already present in BDC or N-PORT output (10-digit padded).

    Returns
    -------
    DataFrame aligned to OUTPUT_COLUMNS with source='ncen'.
    """
    if ncen_df is None or ncen_df.empty:
        return pd.DataFrame(columns=OUTPUT_COLUMNS)

    # Filter to CIKs NOT already covered
    ncen_only = ncen_df[~ncen_df["cik"].isin(existing_ciks)]
    if ncen_only.empty:
        return pd.DataFrame(columns=OUTPUT_COLUMNS)

    # Build output rows with NULLs for fields not available from N-CEN
    rows: list[dict] = []
    for _, r in ncen_only.iterrows():
        row: dict = {col: None for col in OUTPUT_COLUMNS}
        row["cik"] = r["cik"]
        row["entity_name"] = r.get("entity_name", "")
        row["source"] = "ncen"
        row["report_quarter"] = r.get("report_quarter")
        row["report_date"] = r.get("report_date")
        row["nav_per_share"] = r.get("nav_per_share")
        row["management_fee_pct"] = r.get("management_fee_pct")
        row["expense_ratio_pct"] = r.get("expense_ratio_pct")
        row["market_price_per_share"] = r.get("market_price_per_share")
        row["monthly_avg_net_assets"] = r.get("monthly_avg_net_assets")
        row["is_debt_default"] = r.get("is_debt_default")
        row["is_dividend_arrears"] = r.get("is_dividend_arrears")
        row["is_fund_of_fund"] = r.get("is_fund_of_fund")
        row["is_non_diversified"] = r.get("is_non_diversified")
        row["is_formation_stage"] = False
        rows.append(row)

    return pd.DataFrame(rows, columns=OUTPUT_COLUMNS)


# ---------------------------------------------------------------------------
# C. BDC balance sheet + income join
# ---------------------------------------------------------------------------

def _prepare_bdc(
    cf_balance_df: pd.DataFrame,
    income_df: pd.DataFrame,
) -> pd.DataFrame:
    """Join companyfacts balance sheet with bdc_fund_income."""
    if cf_balance_df.empty and (income_df is None or income_df.empty):
        return pd.DataFrame(columns=OUTPUT_COLUMNS)

    con = duckdb.connect()

    # Ensure extended fields exist in cf_balance_df (may be absent in tests
    # or when companyfacts lack these concepts)
    for f in _EXTENDED_FIELDS:
        if f not in cf_balance_df.columns:
            cf_balance_df[f] = None

    con.register("cf_balance", cf_balance_df)

    # Extended fields comma-separated for SQL SELECT
    _ext_select = ", ".join(_EXTENDED_FIELDS)

    # Derive report_quarter from report_date for companyfacts
    # Format: YYYYqN where N = ceil(month/3)
    cf_sql = f"""
    SELECT
        LPAD(CAST(cik AS VARCHAR), 10, '0') AS cik,
        report_date,
        CAST(YEAR(TRY_CAST(report_date AS DATE)) AS VARCHAR)
            || 'q'
            || CAST(CEIL(MONTH(TRY_CAST(report_date AS DATE)) / 3.0) AS INTEGER)
            AS report_quarter,
        total_assets, total_liabilities, net_assets,
        nav_per_share, shares_outstanding, borrowings,
        {_ext_select}
    FROM cf_balance
    WHERE TRY_CAST(report_date AS DATE) IS NOT NULL
    """

    # Dedup: prefer quarterly over annual for same (cik, report_quarter)
    cf_dedup_sql = f"""
    WITH cf_raw AS ({cf_sql}),
    cf_ranked AS (
        SELECT *,
            ROW_NUMBER() OVER (
                PARTITION BY cik, report_quarter
                ORDER BY report_date DESC
            ) AS rn
        FROM cf_raw
    )
    SELECT * EXCLUDE (rn) FROM cf_ranked WHERE rn = 1
    """

    cf_df = con.execute(cf_dedup_sql).fetchdf()
    con.register("cf", cf_df)

    # Handle income_df
    if income_df is not None and not income_df.empty:
        con.register("income", income_df)
        has_income = True
    else:
        has_income = False

    # Build extended field list for SQL
    ext_cf_fields = ", ".join(f"cf.{f}" for f in _EXTENDED_FIELDS)
    ext_null_fields = ", ".join(
        f"CAST(NULL AS DOUBLE) AS {f}" for f in _EXTENDED_FIELDS
    )

    if has_income:
        join_sql = f"""
        WITH inc AS (
            SELECT
                LPAD(CAST(cik AS VARCHAR), 10, '0') AS cik,
                report_quarter,
                TRY_CAST(total_investment_income AS DOUBLE)
                    AS total_investment_income,
                TRY_CAST(net_investment_income AS DOUBLE)
                    AS net_investment_income,
                TRY_CAST(management_fee AS DOUBLE) AS management_fee,
                TRY_CAST(incentive_fee AS DOUBLE) AS incentive_fee,
                TRY_CAST(interest_expense AS DOUBLE) AS interest_expense,
                TRY_CAST(total_expenses AS DOUBLE) AS total_expenses
            FROM income
        )
        SELECT
            COALESCE(cf.cik, inc.cik) AS cik,
            cf.report_date,
            COALESCE(cf.report_quarter, inc.report_quarter)
                AS report_quarter,
            cf.total_assets, cf.net_assets, cf.total_liabilities,
            cf.nav_per_share, cf.shares_outstanding, cf.borrowings,
            inc.total_investment_income, inc.net_investment_income,
            inc.management_fee, inc.incentive_fee,
            inc.interest_expense, inc.total_expenses,
            {ext_cf_fields}
        FROM cf
        FULL OUTER JOIN inc
            ON cf.cik = inc.cik AND cf.report_quarter = inc.report_quarter
        """
    else:
        join_sql = f"""
        SELECT
            cik, report_date, report_quarter,
            total_assets, net_assets, total_liabilities,
            nav_per_share, shares_outstanding, borrowings,
            CAST(NULL AS DOUBLE) AS total_investment_income,
            CAST(NULL AS DOUBLE) AS net_investment_income,
            CAST(NULL AS DOUBLE) AS management_fee,
            CAST(NULL AS DOUBLE) AS incentive_fee,
            CAST(NULL AS DOUBLE) AS interest_expense,
            CAST(NULL AS DOUBLE) AS total_expenses,
            {", ".join(f for f in _EXTENDED_FIELDS)}
        FROM cf
        """

    joined_df = con.execute(join_sql).fetchdf()
    con.register("bdc_joined", joined_df)

    # Build extended field passthrough for cleaning CTEs
    ext_field_list = ", ".join(_EXTENDED_FIELDS)

    # ----- Build seed-filter field list -----
    # All financial fields that should be NULLed for seed capital rows
    _seed_null_fields = [
        "total_assets", "net_assets", "total_liabilities",
        "nav_per_share", "shares_outstanding", "borrowings",
        "total_investment_income", "net_investment_income",
        "management_fee", "incentive_fee", "interest_expense", "total_expenses",
    ] + list(_EXTENDED_FIELDS)
    _seed_exclude = ", ".join(_seed_null_fields + ["_is_seed"])
    _seed_cases = "\n        ".join(
        f"CASE WHEN _is_seed THEN NULL ELSE {f} END AS {f},"
        for f in _seed_null_fields
    )

    # ----- Decimal -> percentage fields (Fix 2) -----
    _pct_fields = [
        "total_return_pct", "income_yield_pct",
        "portfolio_turnover", "debt_weighted_avg_rate",
    ]
    _pct_cases = "\n        ".join(
        f"""CASE
            WHEN {f} IS NULL THEN NULL
            WHEN ABS({f}) <= 1.0 THEN {f} * 100.0
            WHEN ABS({f}) > 100.0 THEN NULL
            ELSE {f}
        END AS {f},"""
        for f in _pct_fields
    )

    # Extended fields EXCLUDING the ones handled by pct conversion
    _ext_passthrough = [f for f in _EXTENDED_FIELDS if f not in _pct_fields]
    _ext_passthrough_list = ", ".join(_ext_passthrough)

    # ----- Data cleaning CTEs -----
    clean_sql = f"""
    WITH
    -- CTE 1: Power-of-10 scale fix using TA/NA ratio as anchor.
    -- If a quarter's TA/NA ratio deviates >30x from the CIK's median,
    -- correct total_assets (and total_liabilities) by the ratio.
    with_scale_fix AS (
        SELECT *,
            MEDIAN(ABS(total_assets / NULLIF(net_assets, 0)))
                OVER (PARTITION BY cik) AS _med_ratio,
            ABS(total_assets / NULLIF(net_assets, 0)) AS _this_ratio
        FROM bdc_joined
    ),
    scaled AS (
        SELECT * EXCLUDE (total_assets, total_liabilities,
                          _med_ratio, _this_ratio),
            CASE
                WHEN _med_ratio IS NOT NULL
                    AND _this_ratio IS NOT NULL
                    AND _med_ratio > 0
                    AND _this_ratio > 0
                    AND ABS(LOG10(NULLIF(_this_ratio / _med_ratio, 0))) > 1.5
                THEN total_assets * (_med_ratio / _this_ratio)
                ELSE total_assets
            END AS total_assets,
            CASE
                WHEN _med_ratio IS NOT NULL
                    AND _this_ratio IS NOT NULL
                    AND _med_ratio > 0
                    AND _this_ratio > 0
                    AND ABS(LOG10(NULLIF(_this_ratio / _med_ratio, 0))) > 1.5
                THEN total_liabilities * (_med_ratio / _this_ratio)
                ELSE total_liabilities
            END AS total_liabilities
        FROM with_scale_fix
    ),
    -- CTE 2: Value guards (Fix 3: <= 0 instead of < 0)
    guarded AS (
        SELECT * EXCLUDE (total_assets),
            CASE
                -- Non-positive total_assets -> NULL
                WHEN total_assets <= 0 THEN NULL
                -- TA < 0.8 * NA (structural impossibility) -> NULL
                WHEN net_assets IS NOT NULL
                    AND net_assets > 0
                    AND total_assets < net_assets * 0.8
                THEN NULL
                ELSE total_assets
            END AS total_assets
        FROM scaled
    ),
    -- CTE 3: Seed capital filter (Fix 3) -- NULL all financial fields
    -- when total_assets < $100K
    no_seed AS (
        SELECT *,
            (total_assets IS NOT NULL AND total_assets > 0
             AND total_assets < 100000) AS _is_seed
        FROM guarded
    ),
    cleaned AS (
        SELECT * EXCLUDE ({_seed_exclude}),
        {_seed_cases}
        -- _is_seed flag not carried forward
        FROM no_seed
    )
    -- Final output with cleaned leverage_ratio + extended + computed
    SELECT
        cik, report_date, report_quarter,
        total_assets, net_assets, total_liabilities,
        nav_per_share, shares_outstanding, borrowings,
        total_investment_income, net_investment_income,
        management_fee, incentive_fee, interest_expense, total_expenses,
        CAST(NULL AS DOUBLE) AS monthly_return_1,
        CAST(NULL AS DOUBLE) AS monthly_return_2,
        CAST(NULL AS DOUBLE) AS monthly_return_3,
        CAST(NULL AS DOUBLE) AS monthly_flow_sales_1,
        CAST(NULL AS DOUBLE) AS monthly_flow_sales_2,
        CAST(NULL AS DOUBLE) AS monthly_flow_sales_3,
        CAST(NULL AS DOUBLE) AS monthly_flow_redemptions_1,
        CAST(NULL AS DOUBLE) AS monthly_flow_redemptions_2,
        CAST(NULL AS DOUBLE) AS monthly_flow_redemptions_3,
        CASE
            WHEN borrowings IS NOT NULL AND total_assets IS NOT NULL
                AND total_assets > 0
            THEN LEAST(borrowings / total_assets, 2.0)
            ELSE NULL
        END AS leverage_ratio,
        CAST(NULL AS DOUBLE) AS quarterly_return,
        'companyfacts' AS source,
        CAST(NULL AS DOUBLE) AS management_fee_pct,
        CAST(NULL AS DOUBLE) AS expense_ratio_pct,
        CAST(NULL AS DOUBLE) AS market_price_per_share,
        CAST(NULL AS DOUBLE) AS monthly_avg_net_assets,
        -- Extended companyfacts fields (non-pct passthrough)
        {_ext_passthrough_list},
        -- Decimal -> percentage conversion (Fix 2)
        {_pct_cases}
        -- N-PORT risk fields (NULL for BDC)
        CAST(NULL AS DOUBLE) AS total_borrowings_detail,
        CAST(NULL AS DOUBLE) AS dv01_3mon,
        CAST(NULL AS DOUBLE) AS dv01_1yr,
        CAST(NULL AS DOUBLE) AS dv01_5yr,
        CAST(NULL AS DOUBLE) AS dv01_10yr,
        CAST(NULL AS DOUBLE) AS dv01_30yr,
        CAST(NULL AS DOUBLE) AS dv100_3mon,
        CAST(NULL AS DOUBLE) AS dv100_1yr,
        CAST(NULL AS DOUBLE) AS dv100_5yr,
        CAST(NULL AS DOUBLE) AS dv100_10yr,
        CAST(NULL AS DOUBLE) AS dv100_30yr,
        -- N-PORT credit spread (NULL for BDC)
        CAST(NULL AS DOUBLE) AS credit_spread_3mon_invest,
        CAST(NULL AS DOUBLE) AS credit_spread_1yr_invest,
        CAST(NULL AS DOUBLE) AS credit_spread_5yr_invest,
        CAST(NULL AS DOUBLE) AS credit_spread_10yr_invest,
        CAST(NULL AS DOUBLE) AS credit_spread_30yr_invest,
        CAST(NULL AS DOUBLE) AS credit_spread_3mon_noninvest,
        CAST(NULL AS DOUBLE) AS credit_spread_1yr_noninvest,
        CAST(NULL AS DOUBLE) AS credit_spread_5yr_noninvest,
        CAST(NULL AS DOUBLE) AS credit_spread_10yr_noninvest,
        CAST(NULL AS DOUBLE) AS credit_spread_30yr_noninvest,
        -- N-CEN flags (NULL for BDC)
        CAST(NULL AS BOOLEAN) AS is_debt_default,
        CAST(NULL AS BOOLEAN) AS is_dividend_arrears,
        CAST(NULL AS BOOLEAN) AS is_fund_of_fund,
        CAST(NULL AS BOOLEAN) AS is_non_diversified,
        -- Computed: distribution_rate = (dist_per_share * 4) / nav * 100
        CASE
            WHEN distribution_per_share IS NOT NULL
                AND nav_per_share IS NOT NULL AND nav_per_share > 0
            THEN GREATEST(LEAST((distribution_per_share * 4.0) / nav_per_share * 100.0, 50.0), 0.0)
            ELSE NULL
        END AS distribution_rate,
        CAST(NULL AS DOUBLE) AS distribution_rate_proxy,
        CAST(NULL AS DOUBLE) AS redemption_pressure,
        CAST(NULL AS DOUBLE) AS annualized_return,
        -- premium/discount: NULL for BDC (no market_price from companyfacts)
        CAST(NULL AS DOUBLE) AS premium_discount_pct,
        -- Formation-stage flag (Fix 4)
        CASE
            WHEN shares_outstanding IS NOT NULL AND shares_outstanding < 1000
                AND (nav_per_share < 0 OR nav_per_share > 10000)
            THEN TRUE
            ELSE FALSE
        END AS is_formation_stage
    FROM cleaned
    """

    result = con.execute(clean_sql).fetchdf()
    con.close()
    return result


# ---------------------------------------------------------------------------
# D0. Schema enforcement
# ---------------------------------------------------------------------------

def _enforce_schema(df: pd.DataFrame) -> list[tuple[str, int]]:
    """Run schema checks on fund_financials output. Non-fatal."""
    if df.empty:
        return []
    con = duckdb.connect()
    con.register("ff", df)

    checks = [
        # Layer 1: Type/format
        ("cik_format",
         "SELECT COUNT(*) FROM ff"
         " WHERE LENGTH(CAST(cik AS VARCHAR)) != 10"
         "    OR regexp_matches(CAST(cik AS VARCHAR), '[^0-9]')"),
        ("source_enum",
         "SELECT COUNT(*) FROM ff"
         " WHERE CAST(source AS VARCHAR) NOT IN"
         " ('companyfacts','nport','ncen')"),
        ("vehicle_type_enum",
         "SELECT COUNT(*) FROM ff"
         " WHERE CAST(vehicle_type AS VARCHAR) NOT IN"
         " ('bdc','interval_fund','tender_offer_fund','')"
         "   AND vehicle_type IS NOT NULL"),
        ("report_date_parseable",
         "SELECT COUNT(*) FROM ff"
         " WHERE report_date IS NOT NULL"
         "   AND CAST(report_date AS VARCHAR) != ''"
         "   AND TRY_CAST(report_date AS DATE) IS NULL"),
        # Layer 2: Domain range
        ("total_assets_positive",
         "SELECT COUNT(*) FROM ff"
         " WHERE TRY_CAST(total_assets AS DOUBLE) IS NOT NULL"
         "   AND TRY_CAST(total_assets AS DOUBLE) <= 0"),
        ("nav_per_share_range",
         "SELECT COUNT(*) FROM ff"
         " WHERE TRY_CAST(nav_per_share AS DOUBLE) IS NOT NULL"
         "   AND (TRY_CAST(nav_per_share AS DOUBLE) < -100"
         "        OR TRY_CAST(nav_per_share AS DOUBLE) > 100000)"),
        ("leverage_ratio_range",
         "SELECT COUNT(*) FROM ff"
         " WHERE TRY_CAST(leverage_ratio AS DOUBLE) IS NOT NULL"
         "   AND (TRY_CAST(leverage_ratio AS DOUBLE) < 0"
         "        OR TRY_CAST(leverage_ratio AS DOUBLE) > 2.0)"),
        ("expense_ratio_range",
         "SELECT COUNT(*) FROM ff"
         " WHERE TRY_CAST(expense_ratio_pct AS DOUBLE) IS NOT NULL"
         "   AND (TRY_CAST(expense_ratio_pct AS DOUBLE) < 0"
         "        OR TRY_CAST(expense_ratio_pct AS DOUBLE) > 20)"),
        ("distribution_rate_range",
         "SELECT COUNT(*) FROM ff"
         " WHERE TRY_CAST(distribution_rate AS DOUBLE) IS NOT NULL"
         "   AND (TRY_CAST(distribution_rate AS DOUBLE) < 0"
         "        OR TRY_CAST(distribution_rate AS DOUBLE) > 50)"),
        ("quarterly_return_range",
         "SELECT COUNT(*) FROM ff"
         " WHERE TRY_CAST(quarterly_return AS DOUBLE) IS NOT NULL"
         "   AND (TRY_CAST(quarterly_return AS DOUBLE) < -50"
         "        OR TRY_CAST(quarterly_return AS DOUBLE) > 100)"),
        # Layer 3: Relational
        ("ta_ge_na",
         "SELECT COUNT(*) FROM ff"
         " WHERE TRY_CAST(total_assets AS DOUBLE) IS NOT NULL"
         "   AND TRY_CAST(net_assets AS DOUBLE) IS NOT NULL"
         "   AND TRY_CAST(net_assets AS DOUBLE) > 0"
         "   AND TRY_CAST(total_assets AS DOUBLE)"
         "       < TRY_CAST(net_assets AS DOUBLE) * 0.8"),
        ("bdc_has_balance_sheet",
         "SELECT COUNT(*) FROM ff"
         " WHERE source = 'companyfacts'"
         "   AND TRY_CAST(total_assets AS DOUBLE) IS NULL"
         "   AND TRY_CAST(net_assets AS DOUBLE) IS NULL"),
    ]

    violations: list[tuple[str, int]] = []
    for name, sql in checks:
        try:
            count = con.execute(sql).fetchone()[0]
            if count > 0:
                violations.append((name, count))
        except Exception:
            pass  # Skip check on SQL error (column missing, etc.)

    con.close()
    return violations


# ---------------------------------------------------------------------------
# D-pre. Computed return waterfall
# ---------------------------------------------------------------------------


def _fill_computed_returns(df: pd.DataFrame) -> pd.DataFrame:
    """Fill NULL total_return_pct using a 2-tier waterfall.

    Only applies to companyfacts rows (BDCs) where total_return_pct is NULL
    but NAV data exists.

    Tier 1: NAV adjusted by shares_outstanding ratio (neutralises splits)
    Tier 2: raw NAV + distributions with >50% jump guard

    Computed returns outside -50% to +50% are discarded (capital raise
    artifacts). net_assets change is NOT used because it conflates
    performance with fund inflows/outflows.
    """
    if df.empty or "total_return_pct" not in df.columns:
        return df

    con = duckdb.connect()
    con.register("ff", df)

    filled = con.execute("""
        WITH
        -- Add lagged values for all three tiers
        with_lags AS (
            SELECT *,
                LAG(nav_per_share) OVER w AS _prev_nav,
                LAG(shares_outstanding) OVER w AS _prev_shares
            FROM ff
            WINDOW w AS (PARTITION BY cik ORDER BY report_quarter)
        ),
        -- Compute candidate returns per tier
        with_candidates AS (
            SELECT *,
                -- Tier 1: NAV adjusted by share count ratio (neutralises splits)
                CASE WHEN _prev_nav IS NOT NULL AND _prev_nav > 0
                          AND nav_per_share IS NOT NULL
                          AND _prev_shares IS NOT NULL AND _prev_shares > 0
                          AND shares_outstanding IS NOT NULL AND shares_outstanding > 0
                     THEN (
                         nav_per_share * shares_outstanding
                         - _prev_nav * _prev_shares
                         + COALESCE(distribution_per_share, 0) * shares_outstanding
                     ) / (_prev_nav * _prev_shares) * 100.0
                     ELSE NULL
                END AS _ret_tier1,
                -- Tier 2: raw NAV + distributions with jump guard
                CASE WHEN _prev_nav IS NOT NULL AND _prev_nav > 0
                          AND nav_per_share IS NOT NULL
                          AND nav_per_share / _prev_nav <= 1.5
                          AND nav_per_share / _prev_nav >= 0.67
                     THEN (nav_per_share - _prev_nav
                           + COALESCE(distribution_per_share, 0))
                           / _prev_nav * 100.0
                     ELSE NULL
                END AS _ret_tier2
            FROM with_lags
        )
        SELECT * EXCLUDE (
            total_return_pct,
            _prev_nav, _prev_shares,
            _ret_tier1, _ret_tier2
        ),
            CASE
                WHEN total_return_pct IS NOT NULL THEN total_return_pct
                WHEN source != 'companyfacts' THEN NULL
                ELSE CASE
                    WHEN COALESCE(_ret_tier1, _ret_tier2)
                         BETWEEN -50.0 AND 50.0
                    THEN COALESCE(_ret_tier1, _ret_tier2)
                    ELSE NULL
                END
            END AS total_return_pct
        FROM with_candidates
    """).fetchdf()

    con.close()

    # Log fill stats
    orig_count = df["total_return_pct"].notna().sum()
    new_count = filled["total_return_pct"].notna().sum()
    added = new_count - orig_count
    if added > 0:
        logger.info(
            "Computed return waterfall: +%d rows filled "
            "(total_return_pct %d -> %d)",
            added, orig_count, new_count,
        )

    return filled


# ---------------------------------------------------------------------------
# D. Orchestrator
# ---------------------------------------------------------------------------

def build_fund_financials(
    income_df: Optional[pd.DataFrame] = None,
    nport_fund_info_df: Optional[pd.DataFrame] = None,
    universe_df: Optional[pd.DataFrame] = None,
    client: object | None = None,
) -> pd.DataFrame:
    """Build unified fund financials from companyfacts + N-PORT fund info.

    Parameters
    ----------
    income_df : DataFrame, optional
        BDC fund income from ``extract_bdc_fund_income()``.
        Loaded from disk if None.
    nport_fund_info_df : DataFrame, optional
        N-PORT fund info. Loaded from disk if None.
    universe_df : DataFrame, optional
        Combined universe. Loaded from disk if None.
    client : EdgarClient, optional
        If provided, refreshes companyfacts cache via network.
        If None, reads from cache only (no downloads).

    Returns
    -------
    DataFrame saved to ``fund_financials.csv``.
    """
    t0 = time.time()

    # 1. Lazy-load inputs
    if income_df is None:
        if BDC_FUND_INCOME_FILE.exists():
            income_df = pd.read_csv(BDC_FUND_INCOME_FILE, dtype=str)
            logger.info("Loaded bdc_fund_income: %d rows", len(income_df))
        else:
            logger.info("No bdc_fund_income.csv found; skipping income data")
            income_df = pd.DataFrame()

    if nport_fund_info_df is None:
        if NPORT_FUND_INFO_FILE.exists():
            nport_fund_info_df = pd.read_csv(NPORT_FUND_INFO_FILE, dtype=str)
            logger.info("Loaded nport_fund_info: %d rows",
                        len(nport_fund_info_df))
        else:
            logger.info("No nport_fund_info.csv found; skipping N-PORT data")
            nport_fund_info_df = pd.DataFrame()

    if universe_df is None:
        if COMBINED_UNIVERSE_FILE.exists():
            universe_df = pd.read_csv(COMBINED_UNIVERSE_FILE, dtype=str)
            logger.info("Loaded universe: %d entities", len(universe_df))
        else:
            logger.warning("No combined_universe.csv; vehicle_type unavailable")
            universe_df = pd.DataFrame()

    # 2. BDC CIKs from universe
    bdc_ciks: list[str] = []
    if not universe_df.empty and "vehicle_type" in universe_df.columns:
        bdc_rows = universe_df[universe_df["vehicle_type"] == "bdc"]
        bdc_ciks = bdc_rows["cik"].dropna().unique().tolist()
    logger.info("BDC CIKs for companyfacts: %d", len(bdc_ciks))

    # 3. Extract companyfacts balance sheet
    cf_balance_df = _extract_all_companyfacts(bdc_ciks, client)
    logger.info("Companyfacts balance sheet: %d rows", len(cf_balance_df))

    # 4. Prepare BDC side
    bdc_df = _prepare_bdc(cf_balance_df, income_df)
    logger.info("BDC financials: %d rows", len(bdc_df))

    # 5. Extract N-CEN financials
    universe_ciks: set[str] = set()
    if not universe_df.empty and "cik" in universe_df.columns:
        universe_ciks = set(
            universe_df["cik"].dropna().astype(str).str.zfill(10).unique()
        )
    ncen_raw_df = _parse_ncen_financials(universe_ciks)
    logger.info(
        "N-CEN financials: %d rows, %d CIKs",
        len(ncen_raw_df),
        ncen_raw_df["cik"].nunique() if not ncen_raw_df.empty else 0,
    )

    # 5b. Extract N-CEN identity (adviser, ticker)
    _parse_ncen_identity(universe_ciks)

    # 6. Prepare N-PORT side (enriched with N-CEN)
    nport_df = _prepare_nport(
        nport_fund_info_df,
        ncen_df=ncen_raw_df if not ncen_raw_df.empty else None,
    )
    logger.info("N-PORT financials: %d rows", len(nport_df))

    # 7. Standalone N-CEN rows (CIKs not in BDC or N-PORT)
    existing_ciks: set[str] = set()
    if not bdc_df.empty:
        existing_ciks |= set(bdc_df["cik"].unique())
    if not nport_df.empty:
        existing_ciks |= set(nport_df["cik"].unique())
    ncen_only_df = _prepare_ncen(ncen_raw_df, existing_ciks)
    logger.info(
        "N-CEN standalone: %d rows, %d CIKs",
        len(ncen_only_df),
        ncen_only_df["cik"].nunique() if not ncen_only_df.empty else 0,
    )

    # 8. UNION ALL + vehicle_type enrichment + dedup
    if bdc_df.empty and nport_df.empty and ncen_only_df.empty:
        logger.warning("No financials data produced")
        result = pd.DataFrame(columns=OUTPUT_COLUMNS)
        result.to_csv(FUND_FINANCIALS_FILE, index=False)
        return result

    con = duckdb.connect()

    has_bdc = not bdc_df.empty
    has_nport = not nport_df.empty
    has_ncen = not ncen_only_df.empty

    if has_bdc:
        con.register("bdc_fin", bdc_df)
    if has_nport:
        con.register("nport_fin", nport_df)
    if has_ncen:
        con.register("ncen_fin", ncen_only_df)

    # Build explicit column list for UNION ALL alignment
    _str_cols = {"cik", "report_quarter", "report_date", "source"}
    _bool_cols = {
        "is_formation_stage",
        "is_debt_default", "is_dividend_arrears",
        "is_fund_of_fund", "is_non_diversified",
    }
    union_cols = [c for c in OUTPUT_COLUMNS
                  if c not in ("entity_name", "vehicle_type")]

    def _select_cols(table: str) -> str:
        """Build SELECT with NULLs for missing columns."""
        parts = []
        for col in union_cols:
            if col == "cik":
                parts.append(
                    f"LPAD(CAST({table}.cik AS VARCHAR), 10, '0') AS cik")
            elif col in _str_cols:
                parts.append(f"CAST({table}.{col} AS VARCHAR) AS {col}")
            elif col in _bool_cols:
                parts.append(
                    f"CAST({table}.{col} AS BOOLEAN) AS {col}")
            else:
                parts.append(
                    f"TRY_CAST({table}.{col} AS DOUBLE) AS {col}")
        return ", ".join(parts)

    # Build UNION ALL from available sources
    union_parts = []
    if has_bdc:
        union_parts.append(
            f"SELECT {_select_cols('bdc_fin')} FROM bdc_fin")
    if has_nport:
        union_parts.append(
            f"SELECT {_select_cols('nport_fin')} FROM nport_fin")
    if has_ncen:
        union_parts.append(
            f"SELECT {_select_cols('ncen_fin')} FROM ncen_fin")
    union_sql = "\nUNION ALL\n".join(union_parts)

    # Build the list of all non-identity columns for the final SELECT
    _final_select_cols = [
        c for c in OUTPUT_COLUMNS
        if c not in ("cik", "entity_name", "vehicle_type", "source",
                     "report_quarter", "report_date")
    ]
    _final_cols_sql = ",\n            ".join(_final_select_cols)
    if not universe_df.empty:
        con.register("universe", universe_df)
        final_sql = f"""
        WITH combined AS ({union_sql}),
        univ AS (
            SELECT
                LPAD(CAST(cik AS VARCHAR), 10, '0') AS cik,
                entity_name AS univ_entity_name,
                vehicle_type
            FROM universe
        ),
        enriched AS (
            SELECT
                c.*,
                u.univ_entity_name,
                u.vehicle_type
            FROM combined c
            LEFT JOIN univ u ON c.cik = u.cik
        ),
        deduped AS (
            SELECT *,
                ROW_NUMBER() OVER (
                    PARTITION BY cik, report_quarter
                    ORDER BY
                        CASE source
                            WHEN 'companyfacts' THEN 1
                            WHEN 'nport' THEN 2
                            WHEN 'ncen' THEN 3
                            ELSE 4
                        END,
                        report_date DESC NULLS LAST
                ) AS rn
            FROM enriched
        )
        SELECT
            cik,
            COALESCE(univ_entity_name, '') AS entity_name,
            COALESCE(vehicle_type, '') AS vehicle_type,
            source, report_quarter, report_date,
            {_final_cols_sql}
        FROM deduped
        WHERE rn = 1
          AND univ_entity_name IS NOT NULL
        ORDER BY cik, report_quarter
        """
    else:
        final_sql = f"""
        WITH combined AS ({union_sql}),
        deduped AS (
            SELECT *,
                ROW_NUMBER() OVER (
                    PARTITION BY cik, report_quarter
                    ORDER BY
                        CASE source
                            WHEN 'companyfacts' THEN 1
                            WHEN 'nport' THEN 2
                            WHEN 'ncen' THEN 3
                            ELSE 4
                        END,
                        report_date DESC NULLS LAST
                ) AS rn
            FROM combined
        )
        SELECT
            cik,
            '' AS entity_name,
            '' AS vehicle_type,
            source, report_quarter, report_date,
            {_final_cols_sql}
        FROM deduped
        WHERE rn = 1
        ORDER BY cik, report_quarter
        """

    result = con.execute(final_sql).fetchdf()
    con.close()

    # ----- Computed return waterfall (fill total_return_pct gaps) -----
    result = _fill_computed_returns(result)

    # Schema enforcement (non-fatal warnings)
    violations = _enforce_schema(result)
    if violations:
        logger.warning("Schema enforcement: %d check(s) flagged",
                        len(violations))
        for name, count in violations:
            logger.warning("  %s: %d rows", name, count)

    # Save
    result.to_csv(FUND_FINANCIALS_FILE, index=False)

    elapsed = time.time() - t0
    n_ciks = result["cik"].nunique() if not result.empty else 0
    logger.info(
        "Fund financials: %d rows, %d CIKs in %.1f s",
        len(result), n_ciks, elapsed,
    )
    if not result.empty and "vehicle_type" in result.columns:
        for vt in ["bdc", "interval_fund", "tender_offer_fund"]:
            count = (result["vehicle_type"] == vt).sum()
            if count:
                logger.info("  %s: %d rows", vt, count)
    if not result.empty:
        qmin = result["report_quarter"].min()
        qmax = result["report_quarter"].max()
        logger.info("  Date range: %s to %s", qmin, qmax)

    return result
