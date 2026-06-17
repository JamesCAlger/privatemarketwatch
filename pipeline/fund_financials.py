"""Extract fund-level financials from companyfacts + N-PORT fund info.

Merges BDC balance-sheet data (companyfacts API, back to ~2012) with
N-PORT fundInfo (balance sheet, monthly returns, flows since 2019q4) into
a single ``fund_financials.csv`` -- one row per CIK per quarter.

Public API
----------
build_fund_financials(income_df, nport_fund_info_df, universe_df, client)
    -> pd.DataFrame
"""

import logging
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Optional

import duckdb
import pandas as pd

from pipeline import extract_companyfacts, extract_ncen
from pipeline.config import (
    BDC_FUND_INCOME_FILE,
    BDC_PREMIUM_DISCOUNT_FILE,
    BDC_XBRL_CACHE_DIR,
    COMBINED_UNIVERSE_FILE,
    COMPANYFACTS_CACHE_DIR,
    FUND_FINANCIALS_FILE,
    FUND_FINANCIALS_SCALE_OVERRIDES,
    FUND_IDENTITY_FILE,
    NCEN_QUARTERS,
    NCSR_FINANCIALS_FILE,
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
    "total_assets", "net_assets", "total_liabilities", "investments_at_fair_value",
    "investments_at_cost",
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
    # Distributions (BDC from companyfacts, interval/tender from N-CSR)
    "distribution_per_share",
    "dividends_declared_per_share",
    "distribution_ordinary_income",
    "distribution_return_of_capital",
    "distribution_from_nii",
    "distribution_from_gains",
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

NCSR_MAX_STALENESS_DAYS = 370


_EXTENDED_FIELDS = extract_companyfacts._EXTENDED_FIELDS


_TOTAL_RETURN_CLASS_PRIORITY = {
    "CommonClassIMember": 0,
    "": 1,
    "CommonClassDMember": 2,
    "CommonClassSMember": 3,
}


# NAV-based total-return elements we accept, in priority order (lower = preferred).
# The plain element is the standard net NAV total return; some filers instead tag
# only an after-incentive-fee or a custom NAV element (same NAV basis), with the
# before-fee (gross) variant as a last resort. Market-value total-return elements
# (InvestmentCompanyTotalReturnMarketValue, *BasedOnMarketValue) are deliberately
# NOT listed -- those are a different (price) basis and must not be mixed in.
_TR_ELEMENT_PRIORITY = {
    "InvestmentCompanyTotalReturn": 0,
    "InvestmentCompanyTotalReturnAfterIncentiveFees": 1,
    "TotalReturnBasedOnNetAssetValue": 2,
    "InvestmentCompanyTotalReturnBeforeIncentiveFees": 3,
}


def _xml_local_name(tag: str) -> str:
    """Return the local XML tag name without namespace."""
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def _xml_text_by_local_name(parent: ET.Element, name: str) -> str | None:
    for child in parent.iter():
        if _xml_local_name(child.tag) == name:
            return child.text
    return None


def _class_member_rank(member: str | None) -> tuple[int, str]:
    clean = (member or "").split(":")[-1]
    return (_TOTAL_RETURN_CLASS_PRIORITY.get(clean, 4), clean)


def _quarter_from_date(date_value: str) -> str:
    year = int(date_value[:4])
    month = int(date_value[5:7])
    return f"{year}q{((month - 1) // 3) + 1}"


def _duration_months(start_date: str, end_date: str) -> int:
    return extract_companyfacts._months_between(start_date, end_date)


def _normalize_total_return_fact_value(value: float) -> float:
    """Normalize XBRL total-return facts to decimal return units.

    Most filers use decimal returns (0.019 = 1.9%), but some cached XBRL
    facts use percentage points (1.9 = 1.9%). Keep impossible/extreme values
    visible after normalization; range validation decides whether they are
    chart-grade.
    """
    if abs(value) > 1.0:
        return value / 100.0
    return value


def _extract_bdc_total_return_facts_from_xml(path: Path) -> list[dict]:
    """Extract raw InvestmentCompanyTotalReturn facts from one cached XBRL file."""
    try:
        root = ET.parse(path).getroot()
    except (ET.ParseError, OSError) as exc:
        logger.debug("BDC total return: skipped unparsable XML %s: %s", path, exc)
        return []

    contexts: dict[str, dict] = {}
    for ctx in root.iter():
        if _xml_local_name(ctx.tag) != "context":
            continue
        context_id = ctx.attrib.get("id")
        if not context_id:
            continue

        start_date = _xml_text_by_local_name(ctx, "startDate")
        end_date = _xml_text_by_local_name(ctx, "endDate")
        if not start_date or not end_date:
            continue

        cik = _xml_text_by_local_name(ctx, "identifier")
        class_member = ""
        for member_el in ctx.iter():
            if _xml_local_name(member_el.tag) != "explicitMember":
                continue
            dimension = member_el.attrib.get("dimension", "")
            if dimension.split(":")[-1] == "StatementClassOfStockAxis":
                class_member = (member_el.text or "").split(":")[-1]
                break

        contexts[context_id] = {
            "cik": str(cik or path.parent.name).zfill(10),
            "start_date": start_date,
            "end_date": end_date,
            "class_member": class_member,
        }

    rows: list[dict] = []
    accession = path.stem
    for fact in root.iter():
        element = _xml_local_name(fact.tag)
        element_rank = _TR_ELEMENT_PRIORITY.get(element)
        if element_rank is None:
            continue
        context = contexts.get(fact.attrib.get("contextRef", ""))
        if not context:
            continue
        try:
            raw_value = float((fact.text or "").strip())
        except (TypeError, ValueError):
            continue
        rows.append({
            **context,
            "raw_value": raw_value,
            "value": _normalize_total_return_fact_value(raw_value),
            "element": element,
            "element_rank": element_rank,
            "accession": accession,
            "path": str(path),
        })

    if rows:
        filing_end_date = max(str(r["end_date"]) for r in rows)
        for row in rows:
            row["is_current_filing_period"] = row["end_date"] == filing_end_date

    return rows


def extract_bdc_total_return_quarterly(
    bdc_ciks: list[str] | None = None,
    xbrl_cache_dir: Path | None = None,
) -> pd.DataFrame:
    """Extract BDC shareholder total-return facts and convert YTD to quarters.

    Values are returned as percentage points, matching ``quarterly_return`` in
    ``fund_financials.csv`` and N-PORT monthly return compounding.
    """
    columns = ["cik", "report_quarter", "quarterly_return"]
    if xbrl_cache_dir is None:
        xbrl_cache_dir = BDC_XBRL_CACHE_DIR
    if not xbrl_cache_dir.exists():
        return pd.DataFrame(columns=columns)

    cik_filter = {str(c).zfill(10) for c in bdc_ciks or []}
    raw_rows: list[dict] = []
    cik_dirs = [p for p in xbrl_cache_dir.iterdir() if p.is_dir()]
    for cik_dir in cik_dirs:
        cik = cik_dir.name.zfill(10)
        if cik_filter and cik not in cik_filter:
            continue
        for xml_path in sorted(cik_dir.glob("*.xml")):
            raw_rows.extend(_extract_bdc_total_return_facts_from_xml(xml_path))

    if not raw_rows:
        return pd.DataFrame(columns=columns)

    raw = pd.DataFrame(raw_rows)
    class_ranks = raw["class_member"].map(_class_member_rank)
    raw["class_rank"] = class_ranks.map(lambda item: item[0])
    raw["class_sort"] = class_ranks.map(lambda item: item[1])
    raw["duration_months"] = [
        _duration_months(str(start), str(end))
        for start, end in zip(raw["start_date"], raw["end_date"])
    ]
    raw["is_ytd"] = (
        raw["start_date"].astype(str).str[5:10].eq("01-01")
        & raw["start_date"].astype(str).str[:4].eq(
            raw["end_date"].astype(str).str[:4]
        )
    )

    # For each CIK/end date choose the best class, prefer YTD/FY duration
    # facts, then the latest cached accession.
    raw = raw.sort_values(
        [
            "cik", "end_date", "class_rank", "class_sort", "element_rank",
            "is_ytd", "duration_months", "is_current_filing_period",
            "accession",
        ],
        ascending=[True, True, True, True, True, False, False, False, False],
        kind="mergesort",
    )
    selected = raw.drop_duplicates(["cik", "end_date"], keep="first").copy()

    non_priority = selected[
        ~selected["class_member"].fillna("").isin(_TOTAL_RETURN_CLASS_PRIORITY)
        & selected["class_member"].notna()
        & (selected["class_member"] != "")
    ]
    if not non_priority.empty:
        examples = (
            non_priority[["cik", "class_member"]]
            .drop_duplicates()
            .head(10)
            .to_dict("records")
        )
        logger.info(
            "BDC total return: selected non-priority class members: %s",
            examples,
        )

    out_rows: list[dict] = []
    for cik, grp in selected.sort_values(["cik", "end_date"]).groupby("cik"):
        ytd_by_year_quarter: dict[tuple[int, int], float] = {}
        for _, row in grp.iterrows():
            end_date = str(row["end_date"])
            year = int(end_date[:4])
            quarter = int(_quarter_from_date(end_date).split("q")[1])
            value = float(row["value"])
            duration = int(row["duration_months"] or 0)
            is_ytd = bool(row["is_ytd"])

            quarterly_value: float | None = None
            if is_ytd and quarter == 1:
                quarterly_value = value
            elif is_ytd and quarter in (2, 3, 4):
                prior = ytd_by_year_quarter.get((year, quarter - 1))
                if prior is not None:
                    quarterly_value = ((1 + value) / (1 + prior) - 1)
            elif duration <= 4:
                quarterly_value = value

            if is_ytd:
                ytd_by_year_quarter[(year, quarter)] = value

            out_rows.append({
                "cik": cik,
                "report_quarter": _quarter_from_date(end_date),
                "quarterly_return": (
                    quarterly_value * 100.0
                    if quarterly_value is not None
                    else None
                ),
            })

    result = pd.DataFrame(out_rows, columns=columns)
    if result.empty:
        return result
    return (
        result.sort_values(["cik", "report_quarter"], kind="mergesort")
        .drop_duplicates(["cik", "report_quarter"], keep="last")
        .reset_index(drop=True)
    )


# ---------------------------------------------------------------------------
# B. N-PORT fund info aggregation
# ---------------------------------------------------------------------------

def _prepare_nport(
    nport_fund_info_df: pd.DataFrame,
    ncen_df: pd.DataFrame | None = None,
    ncsr_df: pd.DataFrame | None = None,
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
    ncsr_df : DataFrame, optional
        N-CSR Financial Highlights from ``extract_ncsr_financials()``.
        When provided, enriches N-PORT rows with per-share NII,
        distribution decomposition, total return, expense ratio,
        income yield via temporal LEFT JOIN.
    """
    if nport_fund_info_df is None or nport_fund_info_df.empty:
        return pd.DataFrame(columns=OUTPUT_COLUMNS)

    nport_fund_info_df = nport_fund_info_df.copy()
    for col in [
        "accession_number", "series_name", "series_id", "class_id",
        "filing_date", "report_date", "quarter", "cik", "registrant_name",
    ]:
        if col not in nport_fund_info_df.columns:
            nport_fund_info_df[col] = None

    con = duckdb.connect()
    con.register("nport_raw", nport_fund_info_df)

    has_ncen = ncen_df is not None and not ncen_df.empty
    if has_ncen:
        ncen_df = ncen_df.copy()
        if "accession_number" not in ncen_df.columns:
            ncen_df["accession_number"] = ""
        con.register("ncen", ncen_df)

    has_ncsr = ncsr_df is not None and not ncsr_df.empty
    if has_ncsr:
        ncsr_df = ncsr_df.copy()
        for col in [
            "cik", "report_date", "filing_date", "accession_number",
            "share_class", "nav_end_per_share", "distribution_per_share",
            "distribution_from_nii", "distribution_from_gains",
            "distribution_return_of_capital", "total_return_pct",
            "gain_loss_per_share", "nii_per_share", "income_yield_pct",
            "expense_ratio_pct", "portfolio_turnover",
        ]:
            if col not in ncsr_df.columns:
                ncsr_df[col] = None
        con.register("ncsr", ncsr_df)

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

    # Base CTE: aggregate N-PORT to CIK economic reporting period.
    # The SEC bulk dataset quarter is provenance only; report_date defines
    # the fund financial period.
    base_cte = f"""
    WITH raw_norm AS (
        SELECT
            *,
            LPAD(CAST(cik AS VARCHAR), 10, '0') AS cik_norm,
            TRY_CAST(report_date AS DATE) AS report_date_dt,
            COALESCE(CAST(series_id AS VARCHAR), '')
                || '|'
                || COALESCE(CAST(series_name AS VARCHAR), '') AS series_key
        FROM nport_raw
        WHERE TRY_CAST(report_date AS DATE) IS NOT NULL
    ),
    class_dedup AS (
        -- Dedup class-level rows: same accession and fund series.
        SELECT DISTINCT ON (accession_number, series_key) *
        FROM raw_norm
        ORDER BY accession_number, series_key, class_id
    ),
    amendment_ranked AS (
        SELECT *,
            ROW_NUMBER() OVER (
                PARTITION BY cik_norm, report_date_dt, series_key
                ORDER BY
                    TRY_CAST(filing_date AS DATE) DESC NULLS LAST,
                    COALESCE(CAST(accession_number AS VARCHAR), '') DESC
            ) AS amendment_rn
        FROM class_dedup
    ),
    series_dedup AS (
        SELECT * FROM amendment_ranked
        WHERE amendment_rn = 1
    ),
    cik_quarter AS (
        SELECT
            cik_norm AS cik,
            MAX(registrant_name) AS entity_name,
            CAST(YEAR(report_date_dt) AS VARCHAR)
                || 'q'
                || CAST(QUARTER(report_date_dt) AS VARCHAR)
                AS report_quarter,
            CAST(report_date_dt AS VARCHAR) AS report_date,
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
        GROUP BY cik_norm, report_date_dt
    )"""

    # Fields that are explicitly emitted in the SELECT (not via ext_nulls)
    _NCSR_EXPLICIT_FIELDS = {
        "distribution_per_share", "dividends_declared_per_share",
        "distribution_ordinary_income", "distribution_return_of_capital",
        "distribution_from_nii", "distribution_from_gains",
        "total_return_pct", "gain_loss_per_share", "nav_change_per_share",
        "income_per_share", "income_yield_pct", "gross_investment_income",
        "portfolio_turnover",
    }

    # NULL columns for BDC-only companyfacts fields in N-PORT rows
    # (excludes fields that are explicitly emitted in the SELECT)
    _nport_ext_nulls = "\n        ".join(
        f"CAST(NULL AS DOUBLE) AS {f},"
        for f in _EXTENDED_FIELDS
        if f not in _NCSR_EXPLICIT_FIELDS
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
            nav_ref="COALESCE(TRY_CAST(nr.ncen_nav AS DOUBLE), CAST(NULL AS DOUBLE))",
        )

        # DV + CS column references for SELECT (from cik_quarter)
        _dv_select = ",\n        ".join(f"cq.{c}" for c in _DV_COLS)
        _cs_select = ",\n        ".join(f"cq.{c}" for c in _CS_COLS)

        # Build optional N-CSR CTE
        _ncsr_cte = ""
        _ncsr_join = ""
        _ncsr_nav = "COALESCE(TRY_CAST(nr.ncen_nav AS DOUBLE), CAST(NULL AS DOUBLE))"
        _ncsr_dist_per_share = "CAST(NULL AS DOUBLE) AS distribution_per_share,"
        _ncsr_dist_from_nii = "CAST(NULL AS DOUBLE) AS distribution_from_nii,"
        _ncsr_dist_from_gains = "CAST(NULL AS DOUBLE) AS distribution_from_gains,"
        _ncsr_dist_roc = "CAST(NULL AS DOUBLE) AS distribution_return_of_capital,"
        _ncsr_total_return = "CAST(NULL AS DOUBLE) AS total_return_pct,"
        _ncsr_gain_loss = "CAST(NULL AS DOUBLE) AS gain_loss_per_share,"
        _ncsr_nav_change = "CAST(NULL AS DOUBLE) AS nav_change_per_share,"
        _ncsr_income_ps = "CAST(NULL AS DOUBLE) AS income_per_share,"
        _ncsr_income_yield = "CAST(NULL AS DOUBLE) AS income_yield_pct,"
        _ncsr_portfolio_turnover = "CAST(NULL AS DOUBLE) AS portfolio_turnover,"
        _ncsr_expense_ratio = "nr.expense_ratio_pct,"

        if has_ncsr:
            _ncsr_cte = f""",
    ncsr_ranked AS (
        SELECT
            LPAD(CAST(ns.cik AS VARCHAR), 10, '0') AS cik,
            cq.report_quarter AS nport_quarter,
            cq.report_date AS nport_report_date,
            TRY_CAST(ns.nav_end_per_share AS DOUBLE) AS ncsr_nav,
            TRY_CAST(ns.distribution_per_share AS DOUBLE) AS ncsr_dist_per_share,
            TRY_CAST(ns.distribution_from_nii AS DOUBLE) AS ncsr_dist_from_nii,
            TRY_CAST(ns.distribution_from_gains AS DOUBLE) AS ncsr_dist_from_gains,
            TRY_CAST(ns.distribution_return_of_capital AS DOUBLE) AS ncsr_dist_roc,
            TRY_CAST(ns.total_return_pct AS DOUBLE) AS ncsr_total_return,
            TRY_CAST(ns.gain_loss_per_share AS DOUBLE) AS ncsr_gain_loss,
            TRY_CAST(ns.nii_per_share AS DOUBLE) AS ncsr_income_ps,
            TRY_CAST(ns.income_yield_pct AS DOUBLE) AS ncsr_income_yield,
            TRY_CAST(ns.expense_ratio_pct AS DOUBLE) AS ncsr_expense_ratio,
            TRY_CAST(ns.portfolio_turnover AS DOUBLE) AS ncsr_portfolio_turnover,
            ROW_NUMBER() OVER (
                PARTITION BY LPAD(CAST(ns.cik AS VARCHAR), 10, '0'),
                    cq.report_date
                ORDER BY
                    TRY_CAST(ns.report_date AS DATE) DESC NULLS LAST,
                    TRY_CAST(ns.filing_date AS DATE) DESC NULLS LAST,
                    COALESCE(CAST(ns.accession_number AS VARCHAR), '') DESC,
                    COALESCE(CAST(ns.share_class AS VARCHAR), '') ASC,
                    TRY_CAST(ns.nav_end_per_share AS DOUBLE) DESC NULLS LAST,
                    TRY_CAST(ns.total_return_pct AS DOUBLE) DESC NULLS LAST,
                    TRY_CAST(ns.expense_ratio_pct AS DOUBLE) DESC NULLS LAST,
                    TRY_CAST(ns.nii_per_share AS DOUBLE) DESC NULLS LAST,
                    TRY_CAST(ns.gain_loss_per_share AS DOUBLE) DESC NULLS LAST,
                    TRY_CAST(ns.distribution_per_share AS DOUBLE) DESC NULLS LAST,
                    TRY_CAST(ns.distribution_from_nii AS DOUBLE) DESC NULLS LAST,
                    TRY_CAST(ns.distribution_from_gains AS DOUBLE) DESC NULLS LAST,
                    TRY_CAST(ns.distribution_return_of_capital AS DOUBLE) DESC NULLS LAST
            ) AS rn
        FROM cik_quarter cq
        JOIN ncsr ns
            ON LPAD(CAST(ns.cik AS VARCHAR), 10, '0') = cq.cik
            AND CAST(ns.report_date AS DATE) <= CAST(cq.report_date AS DATE)
            AND date_diff('day', CAST(ns.report_date AS DATE),
                          CAST(cq.report_date AS DATE)) <= {NCSR_MAX_STALENESS_DAYS}
    )"""
            _ncsr_join = """
    LEFT JOIN ncsr_ranked nsr
        ON cq.cik = nsr.cik
        AND cq.report_date = nsr.nport_report_date
        AND nsr.rn = 1"""
            _ncsr_nav = "COALESCE(nsr.ncsr_nav, TRY_CAST(nr.ncen_nav AS DOUBLE), CAST(NULL AS DOUBLE))"
            _ncsr_dist_per_share = "nsr.ncsr_dist_per_share AS distribution_per_share,"
            _ncsr_dist_from_nii = "nsr.ncsr_dist_from_nii AS distribution_from_nii,"
            _ncsr_dist_from_gains = "nsr.ncsr_dist_from_gains AS distribution_from_gains,"
            _ncsr_dist_roc = "nsr.ncsr_dist_roc AS distribution_return_of_capital,"
            _ncsr_total_return = "nsr.ncsr_total_return AS total_return_pct,"
            _ncsr_gain_loss = "nsr.ncsr_gain_loss AS gain_loss_per_share,"
            _ncsr_nav_change = """CASE
            WHEN nsr.ncsr_income_ps IS NOT NULL
                OR nsr.ncsr_gain_loss IS NOT NULL
            THEN COALESCE(nsr.ncsr_income_ps, 0)
                 + COALESCE(nsr.ncsr_gain_loss, 0)
            ELSE NULL
        END AS nav_change_per_share,"""
            _ncsr_income_ps = "nsr.ncsr_income_ps AS income_per_share,"
            _ncsr_income_yield = "COALESCE(nsr.ncsr_income_yield, CAST(NULL AS DOUBLE)) AS income_yield_pct,"
            _ncsr_portfolio_turnover = "COALESCE(nsr.ncsr_portfolio_turnover, CAST(NULL AS DOUBLE)) AS portfolio_turnover,"
            _ncsr_expense_ratio = "COALESCE(nsr.ncsr_expense_ratio, TRY_CAST(nr.expense_ratio_pct AS DOUBLE)) AS expense_ratio_pct,"

        sql = f"""{base_cte},
    ncen_ranked AS (
        SELECT
            nc.cik,
            cq.report_quarter AS nport_quarter,
            cq.report_date AS nport_report_date,
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
                PARTITION BY nc.cik, cq.report_date
                ORDER BY
                    nc.report_date DESC,
                    COALESCE(CAST(nc.accession_number AS VARCHAR), '') DESC,
                    COALESCE(CAST(nc.nav_per_share AS VARCHAR), '') DESC,
                    COALESCE(CAST(nc.expense_ratio_pct AS VARCHAR), '') DESC,
                    COALESCE(CAST(nc.management_fee_pct AS VARCHAR), '') DESC
            ) AS rn
        FROM cik_quarter cq
        JOIN ncen nc
            ON cq.cik = nc.cik
            AND CAST(nc.report_date AS DATE) <= CAST(cq.report_date AS DATE)
    ){_ncsr_cte}
    SELECT
        cq.cik, cq.entity_name, cq.report_quarter, cq.report_date,
        cq.total_assets, cq.net_assets, cq.total_liabilities,
        {_ncsr_nav} AS nav_per_share,
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
        {_ncsr_expense_ratio}
        nr.market_price_per_share,
        nr.monthly_avg_net_assets,
        -- Extended companyfacts (NULL for N-PORT)
        {_nport_ext_nulls}
        -- Distributions (from N-CSR if available)
        {_ncsr_dist_per_share}
        CAST(NULL AS DOUBLE) AS dividends_declared_per_share,
        CAST(NULL AS DOUBLE) AS distribution_ordinary_income,
        {_ncsr_dist_roc}
        {_ncsr_dist_from_nii}
        {_ncsr_dist_from_gains}
        -- Performance (from N-CSR if available)
        {_ncsr_total_return}
        {_ncsr_gain_loss}
        {_ncsr_nav_change}
        {_ncsr_income_ps}
        {_ncsr_income_yield}
        CAST(NULL AS DOUBLE) AS gross_investment_income,
        {_ncsr_portfolio_turnover}
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
        AND cq.report_date = nr.nport_report_date
        AND nr.rn = 1{_ncsr_join}
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
        -- Distributions (NULL without N-CSR)
        CAST(NULL AS DOUBLE) AS distribution_per_share,
        CAST(NULL AS DOUBLE) AS dividends_declared_per_share,
        CAST(NULL AS DOUBLE) AS distribution_ordinary_income,
        CAST(NULL AS DOUBLE) AS distribution_return_of_capital,
        CAST(NULL AS DOUBLE) AS distribution_from_nii,
        CAST(NULL AS DOUBLE) AS distribution_from_gains,
        -- Performance (NULL without N-CSR)
        CAST(NULL AS DOUBLE) AS total_return_pct,
        CAST(NULL AS DOUBLE) AS gain_loss_per_share,
        CAST(NULL AS DOUBLE) AS nav_change_per_share,
        CAST(NULL AS DOUBLE) AS income_per_share,
        CAST(NULL AS DOUBLE) AS income_yield_pct,
        CAST(NULL AS DOUBLE) AS gross_investment_income,
        CAST(NULL AS DOUBLE) AS portfolio_turnover,
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
    # Ensure balance-sheet fields that may be missing in tests
    if "investments_at_fair_value" not in cf_balance_df.columns:
        cf_balance_df["investments_at_fair_value"] = None

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
        investments_at_fair_value,
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
            cf.investments_at_fair_value,
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
            investments_at_fair_value,
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
        "investments_at_fair_value",
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

    # ----- Manual scale overrides -----
    # For CIKs with too few rows for MEDIAN-based detection, apply a
    # multiplier when the row's TA (and NA) are >100x smaller than the
    # CIK's maximum, indicating a unit-scale error.
    _override_cik_sql = ", ".join(
        f"'{c}'" for c in FUND_FINANCIALS_SCALE_OVERRIDES
    ) if FUND_FINANCIALS_SCALE_OVERRIDES else "'__none__'"
    _override_mult_sql = " ".join(
        f"WHEN b.cik = '{c}' THEN {m}"
        for c, m in FUND_FINANCIALS_SCALE_OVERRIDES.items()
    )

    # ----- Data cleaning CTEs -----
    clean_sql = f"""
    WITH
    -- CTE 0: Manual scale overrides for CIKs where automatic detection fails
    _max_ta AS (
        SELECT cik, MAX(total_assets) AS max_ta, MAX(net_assets) AS max_na
        FROM bdc_joined
        WHERE cik IN ({_override_cik_sql})
        GROUP BY cik
    ),
    manual_scaled AS (
        SELECT b.* EXCLUDE (total_assets, total_liabilities, net_assets),
            CASE WHEN m.cik IS NOT NULL
                 AND b.total_assets IS NOT NULL AND b.total_assets > 0
                 AND m.max_ta > 0
                 AND b.total_assets < m.max_ta / 100
                 THEN b.total_assets * (CASE {_override_mult_sql} ELSE 1 END)
                 ELSE b.total_assets END AS total_assets,
            CASE WHEN m.cik IS NOT NULL
                 AND b.total_liabilities IS NOT NULL AND b.total_liabilities > 0
                 AND m.max_ta > 0
                 AND b.total_assets IS NOT NULL AND b.total_assets > 0
                 AND b.total_assets < m.max_ta / 100
                 THEN b.total_liabilities * (CASE {_override_mult_sql} ELSE 1 END)
                 ELSE b.total_liabilities END AS total_liabilities,
            CASE WHEN m.cik IS NOT NULL
                 AND b.net_assets IS NOT NULL AND b.net_assets > 0
                 AND m.max_na > 0
                 AND b.net_assets < m.max_na / 100
                 THEN b.net_assets * (CASE {_override_mult_sql} ELSE 1 END)
                 ELSE b.net_assets END AS net_assets
        FROM bdc_joined b
        LEFT JOIN _max_ta m ON b.cik = m.cik
    ),
    -- CTE 1: Power-of-10 scale fix using TA/NA ratio as anchor.
    -- If a quarter's TA/NA ratio deviates >30x from the CIK's median,
    -- correct total_assets (and total_liabilities) by the ratio.
    with_scale_fix AS (
        SELECT *,
            MEDIAN(ABS(total_assets / NULLIF(net_assets, 0)))
                OVER (PARTITION BY cik) AS _med_ratio,
            ABS(total_assets / NULLIF(net_assets, 0)) AS _this_ratio
        FROM manual_scaled
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
                -- TA equal to NA with material liabilities means an equity/net-assets
                -- concept leaked into total_assets. Leave TA unresolved.
                WHEN net_assets IS NOT NULL
                    AND net_assets > 0
                    AND total_liabilities IS NOT NULL
                    AND ABS(total_liabilities) > ABS(net_assets) * 0.01
                    AND ABS(total_assets - net_assets) <= ABS(net_assets) * 0.01
                THEN NULL
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
    ),
    -- CTE 4: Derive NAV from net_assets/shares_outstanding where direct is NULL
    -- Guards: (a) CIK median derived/direct ratio must be 0.7-1.4x,
    -- (b) derived value within 2x of direct median, (c) range $2-$200 if no history
    with_derived_nav AS (
        SELECT *,
            CASE
                WHEN net_assets IS NOT NULL AND net_assets > 0
                    AND shares_outstanding IS NOT NULL
                    AND shares_outstanding > 1000
                THEN net_assets / shares_outstanding
                ELSE NULL
            END AS _raw_derived_nav,
            MEDIAN(nav_per_share) OVER (PARTITION BY cik) AS _median_direct_nav,
            COUNT(nav_per_share) OVER (PARTITION BY cik) AS _direct_nav_count,
            -- Median derived NAV across all derivable rows for this CIK
            MEDIAN(CASE
                WHEN net_assets IS NOT NULL AND net_assets > 0
                    AND shares_outstanding IS NOT NULL AND shares_outstanding > 1000
                THEN net_assets / shares_outstanding
                ELSE NULL
            END) OVER (PARTITION BY cik) AS _median_derived_nav
        FROM cleaned
    ),
    nav_filled AS (
        SELECT * EXCLUDE (_raw_derived_nav, _median_direct_nav, _direct_nav_count,
                          _median_derived_nav, nav_per_share),
            COALESCE(
                nav_per_share,
                CASE
                    -- CIK has direct NAV history: derived must be within 2x
                    -- AND CIK's median derived/direct ratio must be ~1x
                    WHEN _direct_nav_count >= 2
                        AND _raw_derived_nav IS NOT NULL
                        AND _raw_derived_nav >= _median_direct_nav * 0.5
                        AND _raw_derived_nav <= _median_direct_nav * 2.0
                        AND _median_derived_nav IS NOT NULL
                        AND _median_direct_nav IS NOT NULL
                        AND _median_direct_nav > 0
                        AND (_median_derived_nav / _median_direct_nav) >= 0.7
                        AND (_median_derived_nav / _median_direct_nav) <= 1.4
                    THEN _raw_derived_nav
                    -- No direct NAV history: use range guard $2-$200
                    WHEN _direct_nav_count < 2
                        AND _raw_derived_nav IS NOT NULL
                        AND _raw_derived_nav >= 2.0
                        AND _raw_derived_nav <= 200.0
                    THEN _raw_derived_nav
                    ELSE NULL
                END
            ) AS nav_per_share
        FROM with_derived_nav
    )
    -- Final output with cleaned leverage_ratio + extended + computed
    SELECT
        cik, report_date, report_quarter,
        total_assets, net_assets, total_liabilities,
        investments_at_fair_value,
        nav_per_share,
        shares_outstanding, borrowings,
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
        -- N-CSR distribution decomposition (NULL for BDC)
        CAST(NULL AS DOUBLE) AS distribution_from_nii,
        CAST(NULL AS DOUBLE) AS distribution_from_gains,
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
    FROM nav_filled
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
# D-pre2. Backfill market price and premium/discount from listed prices
# ---------------------------------------------------------------------------


def _backfill_listed_price_data(df: pd.DataFrame) -> pd.DataFrame:
    """Fill market_price_per_share and premium_discount_pct from bdc_premium_discount.csv.

    Non-invasive: if the file does not exist, returns df unchanged.
    Only fills NULL values on BDC (companyfacts) rows.
    """
    if df.empty:
        return df
    if not BDC_PREMIUM_DISCOUNT_FILE.exists():
        return df

    try:
        pd_df = pd.read_csv(BDC_PREMIUM_DISCOUNT_FILE, dtype=str)
    except Exception:
        return df

    if pd_df.empty:
        return df

    con = duckdb.connect()
    con.register("ff", df)
    con.register("pd_data", pd_df)

    result = con.execute("""
        SELECT
            ff.* EXCLUDE (market_price_per_share, premium_discount_pct),
            COALESCE(
                ff.market_price_per_share,
                TRY_CAST(pd_data.close_price AS DOUBLE)
            ) AS market_price_per_share,
            COALESCE(
                ff.premium_discount_pct,
                TRY_CAST(pd_data.premium_discount_pct AS DOUBLE)
            ) AS premium_discount_pct
        FROM ff
        LEFT JOIN pd_data
            ON LPAD(CAST(ff.cik AS VARCHAR), 10, '0')
                = LPAD(CAST(pd_data.cik AS VARCHAR), 10, '0')
            AND ff.report_quarter = pd_data.report_quarter
            AND ff.source = 'companyfacts'
    """).fetchdf()

    con.close()

    filled_mkt = (
        result["market_price_per_share"].notna().sum()
        - df["market_price_per_share"].notna().sum()
    )
    filled_pd = (
        result["premium_discount_pct"].notna().sum()
        - df["premium_discount_pct"].notna().sum()
    )
    if filled_mkt > 0 or filled_pd > 0:
        logger.info(
            "Listed price backfill: +%d market_price, +%d premium_discount",
            filled_mkt, filled_pd,
        )

    return result


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
    if not universe_df.empty and "withdrawal_date" not in universe_df.columns:
        universe_df = universe_df.copy()
        universe_df["withdrawal_date"] = ""

    # 2. BDC CIKs from universe
    bdc_ciks: list[str] = []
    if not universe_df.empty and "vehicle_type" in universe_df.columns:
        bdc_rows = universe_df[universe_df["vehicle_type"] == "bdc"]
        bdc_ciks = bdc_rows["cik"].dropna().unique().tolist()
    logger.info("BDC CIKs for companyfacts: %d", len(bdc_ciks))

    # 3. Extract companyfacts balance sheet
    cf_balance_df = extract_companyfacts._extract_all_companyfacts(
        bdc_ciks,
        client=client,
        companyfacts_cache_dir=COMPANYFACTS_CACHE_DIR,
    )
    logger.info("Companyfacts balance sheet: %d rows", len(cf_balance_df))

    # 4. Prepare BDC side
    bdc_df = _prepare_bdc(cf_balance_df, income_df)
    bdc_total_return_df = extract_bdc_total_return_quarterly(bdc_ciks)
    if not bdc_df.empty and not bdc_total_return_df.empty:
        con = duckdb.connect()
        con.register("bdc", bdc_df)
        con.register("tr", bdc_total_return_df)
        bdc_df = con.execute("""
            SELECT
                b.* EXCLUDE (quarterly_return),
                tr.quarterly_return AS quarterly_return
            FROM bdc b
            LEFT JOIN tr
                ON LPAD(CAST(b.cik AS VARCHAR), 10, '0') = tr.cik
                AND b.report_quarter = tr.report_quarter
        """).fetchdf()
        con.close()
        logger.info(
            "BDC XBRL total returns: populated quarterly_return for %d rows",
            bdc_df["quarterly_return"].notna().sum(),
        )
    logger.info("BDC financials: %d rows", len(bdc_df))

    # 5. Extract N-CEN financials
    universe_ciks: set[str] = set()
    if not universe_df.empty and "cik" in universe_df.columns:
        universe_ciks = set(
            universe_df["cik"].dropna().astype(str).str.zfill(10).unique()
        )
    ncen_raw_df = extract_ncen._parse_ncen_financials(
        universe_ciks,
        sec_datasets_dir=SEC_DATASETS_DIR,
        ncen_quarters=NCEN_QUARTERS,
    )
    logger.info(
        "N-CEN financials: %d rows, %d CIKs",
        len(ncen_raw_df),
        ncen_raw_df["cik"].nunique() if not ncen_raw_df.empty else 0,
    )

    # 5b. Extract N-CEN identity (adviser, ticker)
    extract_ncen._parse_ncen_identity(
        universe_ciks,
        sec_datasets_dir=SEC_DATASETS_DIR,
        ncen_quarters=NCEN_QUARTERS,
        fund_identity_file=FUND_IDENTITY_FILE,
    )

    # 5c. Load N-CSR financials (from disk, no network)
    ncsr_raw_df = pd.DataFrame()
    if NCSR_FINANCIALS_FILE.exists():
        ncsr_raw_df = pd.read_csv(NCSR_FINANCIALS_FILE, dtype=str)
        logger.info(
            "N-CSR financials: %d rows, %d CIKs",
            len(ncsr_raw_df),
            ncsr_raw_df["cik"].nunique() if not ncsr_raw_df.empty else 0,
        )

    # 6. Prepare N-PORT side (enriched with N-CEN + N-CSR)
    nport_df = _prepare_nport(
        nport_fund_info_df,
        ncen_df=ncen_raw_df if not ncen_raw_df.empty else None,
        ncsr_df=ncsr_raw_df if not ncsr_raw_df.empty else None,
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
    _str_cols = {"cik", "entity_name", "report_quarter", "report_date", "source"}
    _bool_cols = {
        "is_formation_stage",
        "is_debt_default", "is_dividend_arrears",
        "is_fund_of_fund", "is_non_diversified",
    }
    union_cols = [c for c in OUTPUT_COLUMNS if c != "vehicle_type"]

    # Collect column sets for each registered table
    _table_cols = {}
    if has_bdc:
        _table_cols["bdc_fin"] = set(bdc_df.columns)
    if has_nport:
        _table_cols["nport_fin"] = set(nport_df.columns)
    if has_ncen:
        _table_cols["ncen_fin"] = set(ncen_only_df.columns)

    def _select_cols(table: str) -> str:
        """Build SELECT with NULLs for missing columns."""
        available = _table_cols.get(table, set())
        parts = []
        for col in union_cols:
            if col not in available and col != "cik":
                # Column missing from source -> NULL
                if col in _str_cols:
                    parts.append(f"CAST(NULL AS VARCHAR) AS {col}")
                elif col in _bool_cols:
                    parts.append(f"CAST(NULL AS BOOLEAN) AS {col}")
                else:
                    parts.append(f"CAST(NULL AS DOUBLE) AS {col}")
            elif col == "cik":
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
                cik,
                univ_entity_name,
                vehicle_type,
                withdrawal_date
            FROM (
                SELECT
                    LPAD(CAST(cik AS VARCHAR), 10, '0') AS cik,
                    entity_name AS univ_entity_name,
                    vehicle_type,
                    TRY_CAST(withdrawal_date AS DATE) AS withdrawal_date,
                    ROW_NUMBER() OVER (
                        PARTITION BY LPAD(CAST(cik AS VARCHAR), 10, '0')
                        ORDER BY LENGTH(entity_name) DESC, entity_name ASC
                    ) AS _rn
                FROM universe
            ) WHERE _rn = 1
        ),
        enriched AS (
            SELECT
                c.*,
                u.univ_entity_name,
                u.vehicle_type,
                u.withdrawal_date
            FROM combined c
            LEFT JOIN univ u ON c.cik = u.cik
            WHERE NOT (
                c.source = 'companyfacts'
                AND LOWER(COALESCE(u.vehicle_type, '')) = 'bdc'
                AND u.withdrawal_date IS NOT NULL
                AND TRY_CAST(c.report_date AS DATE) > u.withdrawal_date
            )
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
                        report_date DESC NULLS LAST,
                        entity_name ASC,
                        total_assets DESC NULLS LAST,
                        net_assets DESC NULLS LAST
                ) AS rn
            FROM enriched
        )
        SELECT
            cik,
            COALESCE(NULLIF(entity_name, ''), univ_entity_name, '') AS entity_name,
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
                        report_date DESC NULLS LAST,
                        entity_name ASC,
                        total_assets DESC NULLS LAST,
                        net_assets DESC NULLS LAST
                ) AS rn
            FROM combined
        )
        SELECT
            cik,
            COALESCE(entity_name, '') AS entity_name,
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
    result = result.sort_values(
        ["cik", "report_quarter", "report_date", "source", "entity_name"],
        kind="mergesort",
        na_position="last",
    ).reset_index(drop=True)

    # ----- Backfill market_price + premium/discount from listed prices -----
    result = _backfill_listed_price_data(result)

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
