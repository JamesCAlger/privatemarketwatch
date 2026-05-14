"""Companyfacts/XBRL extraction for fund financials."""

import json
import logging

import pandas as pd

from pipeline.config import COMPANYFACTS_CACHE_DIR

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# A. Companyfacts helpers
# ---------------------------------------------------------------------------

def _load_companyfacts_cached(cik: str, companyfacts_cache_dir=COMPANYFACTS_CACHE_DIR) -> dict:
    """Read companyfacts JSON from disk cache. No network calls."""
    cik_padded = str(cik).zfill(10)
    cache_path = companyfacts_cache_dir / f"{cik_padded}.json"
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
    "investments_at_fair_value": {
        "exact": ["InvestmentOwnedAtFairValue"],
        "fallback": ["InvestmentsAtFairValueAggregate",
                      "InvestmentsFairValueDisclosure"],
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
    companyfacts_cache_dir=COMPANYFACTS_CACHE_DIR,
) -> pd.DataFrame:
    """Extract balance-sheet data for all BDC CIKs from companyfacts.

    Reads from disk cache first. If a client is provided, missing CIKs are
    fetched from the SEC companyfacts API and cached. If client is None this is
    strictly cache-only and missing CIKs are skipped.
    """
    all_rows: list[dict] = []

    # Identify CIKs needing fetch
    uncached = []
    for cik in bdc_ciks:
        cik_padded = str(cik).zfill(10)
        cache_path = companyfacts_cache_dir / f"{cik_padded}.json"
        if not cache_path.exists():
            uncached.append(cik)

    if uncached:
        if client is None:
            logger.info(
                "Companyfacts: %d/%d BDC CIKs uncached; skipping because client=None cache-only mode",
                len(uncached), len(bdc_ciks),
            )
        else:
            from pipeline.validate_html_template import _fetch_companyfacts

            logger.info(
                "Companyfacts: %d/%d BDC CIKs uncached, fetching from SEC...",
                len(uncached), len(bdc_ciks),
            )
            for i, cik in enumerate(uncached, 1):
                _fetch_companyfacts(cik, client)
                if i % 50 == 0:
                    logger.info("  Fetched %d/%d...", i, len(uncached))
            logger.info("Companyfacts: fetched %d new CIKs from SEC", len(uncached))

    # Now read everything from cache
    for cik in bdc_ciks:
        facts = _load_companyfacts_cached(cik, companyfacts_cache_dir)
        if not facts:
            continue
        rows = _extract_bdc_balance_sheet(cik, facts)
        all_rows.extend(rows)

    if not all_rows:
        return pd.DataFrame(columns=[
            "cik", "report_date", "total_assets", "total_liabilities",
            "net_assets", "nav_per_share", "shares_outstanding", "borrowings",
            "investments_at_fair_value",
        ] + _EXTENDED_FIELDS)

    return pd.DataFrame(all_rows)


