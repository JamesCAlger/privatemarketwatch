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


def _year_to_date_step(value: float, prior: float) -> float:
    """This quarter's part of a year-to-date amount, given the previous year-to-date amount."""
    return value - prior


def _grows_like_running_total(value: float, prior: float, span_months: int) -> bool:
    """True when a year-to-date ratio grew from the previous one as a running total does.

    A running total over n quarters is n/(n-1) times the (n-1)-quarter figure; an annualised
    ratio stays near 1. The cut is halfway: 1 + 0.5/(n-1).
    """
    quarters = max(2, round(span_months / 3))
    return prior != 0 and abs(value) >= abs(prior) * (1 + 0.5 / (quarters - 1))


_MIN_VOTING_RATIO = 0.015


def _running_ratio_periods(entries_by_end: dict[str, list[tuple[str, float]]]) -> tuple[dict[str, bool], bool]:
    """Which fiscal periods of a ratio the filer prints as a running total, not annualised.

    Each pair of year-to-date figures with the same start (three and six months, six and nine,
    nine and twelve) votes, as does a three-month figure filed beside a year-to-date one; a pair
    whose earlier figure is under 1.5 pct does not vote. A period with two or more votes is a
    running total when most of them say so; a period with one vote, or a tie, takes the fund's
    default: running only when most of all its votes say so and two or more periods are running
    totals. One jump in an annualised ratio, or one new fund's ramp-up year, therefore does not
    set the basis. Returns ({period start: running}, fund default).
    """
    by_period: dict[tuple[str, str], float] = {}
    for end_date, candidates in entries_by_end.items():
        for start, value in candidates:
            by_period.setdefault((start, end_date), value)
    votes: dict[str, list[bool]] = {}
    for (start, end_date), value in by_period.items():
        span = _months_between(start, end_date)
        prior = by_period.get((start, _prior_quarter_end(end_date)))
        # A prior under 1.5 pct (a new fund's first months) votes nothing: an annualised ratio
        # climbing from near zero grows like a running total.
        if span > 4 and prior is not None and abs(prior) >= _MIN_VOTING_RATIO:
            votes.setdefault(start, []).append(_grows_like_running_total(value, prior, span))
    # A three-month figure filed beside the year to date (2026-04-01 to 06-30 beside 01-01 to 06-30)
    # votes too: on a running total it is about the year to date less the previous one.
    for (start, end_date), value in by_period.items():
        span = _months_between(start, end_date)
        prior = by_period.get((start, _prior_quarter_end(end_date)))
        if span <= 4 or prior is None:
            continue
        for (q_start, q_end), quarter in by_period.items():
            if q_end == end_date and q_start > start and _months_between(q_start, q_end) <= 4:
                votes.setdefault(start, []).append(abs(quarter - (value - prior)) < abs(quarter - value))
    every = [v for vs in votes.values() for v in vs]
    # The fund's default needs running-total votes from two fiscal periods, not one ramp-up year.
    periods_running = sum(1 for vs in votes.values() if sum(vs) * 2 > len(vs))
    default = len(every) >= 2 and sum(every) * 2 > len(every) and periods_running >= 2
    running = {}
    for start, vs in votes.items():
        yes = sum(vs)
        running[start] = default if len(vs) < 2 or yes * 2 == len(vs) else yes * 2 > len(vs)
    return running, default


def _ratio_is_running(start: str, end_date: str, running: dict[str, bool], default: bool) -> bool:
    """Basis of one ratio figure: its own fiscal period's, else the period it falls in, else the fund's."""
    if start in running:
        return running[start]
    within = [s for s in running if s <= start and _months_between(s, end_date) <= 12]
    return running[max(within)] if within else default


def _split_without_year_to_date(value: float, end_date: str, span_months: int,
                                quarters: dict[str, float], quarter_only: bool = False) -> float | None:
    """This quarter's part of a figure covering several quarters when no earlier year-to-date figure is filed.

    Where every earlier quarter of the period already has a value (a fund that files each 10-Q
    quarter on its own and the year in the 10-K), the quarter is the figure less those quarters.
    Otherwise the figure is spread evenly: an average, not the quarter. (Ratios never come here.)
    ``quarter_only`` fields take no average: None is returned and the date gets no value.
    """
    count = max(1, round(span_months / 3))
    if count > 1:
        earlier, day = [], end_date
        for _ in range(count - 1):
            day = _prior_quarter_end(day)
            if day not in quarters:
                break
            earlier.append(quarters[day])
        else:
            return value - sum(earlier)
    if quarter_only and count > 1:
        return None
    return value / count


def _extract_duration_series(
    facts: dict,
    concept_names: list[str],
    unit_key: str = "USD",
    ratio: bool = False,
    quarter_only: bool = False,
    ratio_as_filed_from: str | None = None,
) -> dict[str, float]:
    """Extract quarterly values from duration concepts.

    XBRL duration facts are often YTD cumulative. This function:
    1. Collects all (start, end, value) triples
    2. For each end_date, prefers the shortest period (single-quarter)
    3. When only YTD exists, deltas against prior quarter's YTD
    4. Fallback: divides by period length in quarters

    ``ratio`` marks a rate such as the net investment income ratio. It is never split or
    averaged: the stored figure is the filed ratio for the shortest period ending on the date,
    on an annualised basis. Most filers annualise it for each year-to-date period and it is
    kept as filed. A filer that prints it for the period, not annualised (it grows like a
    running total, see ``_running_ratio_periods``), has it annualised: times four over the
    period's quarters, so the year's figure in a 10-K is unchanged.

    ``ratio_as_filed_from`` (a fund's highlights wrapper, ``income_ratio_as_filed``): figures
    whose period starts on or after this date are kept as filed whatever the votes say, for a
    filer whose annualised ratio climbs like a running total (a new fund's first year).

    ``quarter_only`` drops a date whose only figure covers several quarters and cannot be
    split (step 4): the field then has no value there instead of an average.
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

    if ratio:
        running, default = _running_ratio_periods(entries_by_end)

    for end_date in sorted(entries_by_end):
        candidates = entries_by_end[end_date]
        # Sort by period length ascending (shortest first)
        best_start, best_value = min(
            candidates, key=lambda x: _months_between(x[0], end_date),
        )
        span = _months_between(best_start, end_date)

        if ratio:
            # A rate, not an amount: annualise a running-total filer's figure, keep the rest as filed.
            forced = ratio_as_filed_from is not None and best_start >= ratio_as_filed_from
            if not forced and _ratio_is_running(best_start, end_date, running, default):
                # _months_between counts month ends (2 for a calendar quarter), so go by quarters
                result[end_date] = best_value * 4 / max(1, round(span / 3))
            else:
                result[end_date] = best_value
        elif span <= 4:
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
                result[end_date] = _year_to_date_step(best_value, ytd_at[(best_start, prior_end)])
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
                    result[end_date] = _year_to_date_step(best_value, prior_ytd)
                else:
                    # No same-FY prior YTD: less the filed quarters, else divide by quarters
                    result[end_date] = _split_without_year_to_date(best_value, end_date, span, result, quarter_only)
            else:
                # No prior quarter data at all (Q1 or annual-only filer)
                result[end_date] = _split_without_year_to_date(best_value, end_date, span, result, quarter_only)

    return {day: value for day, value in result.items() if value is not None}


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
        "fallback": ["TotalAssets"],
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
        # Fill missing dates only; preserve the existing concept choice where
        # reported. Filers can switch tags between quarters. AssetsNet precedes
        # MembersEquity because it can retain unrounded schedule-dollar values.
        "missing_date_concepts": ["AssetsNet", "MembersEquity"],
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
        # Fallbacks (only used when the standard element is absent) for funds that
        # tag their per-share distribution under other standard taxonomy elements:
        # declared common dividend, or per-unit distribution for LP-structured BDCs.
        # NOT DividendsPayableAmountPerShare (a balance, not a period flow) and NOT
        # company-specific component extensions (not present in companyfacts).
        "fallback": [
            "CommonStockDividendsPerShareDeclared",
            "DistributionMadeToLimitedPartnerDistributionsDeclaredPerUnit",
        ],
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
        "unit": "pure", "instant": False, "ratio": True,
    },
    "gross_investment_income": {
        "exact": ["GrossInvestmentIncomeOperating"],
        "fallback": [],
        "unit": "USD", "instant": False,
    },
    # Expenses after fee waivers and expense support, where the fund files that figure. total_expenses
    # stays the gross figure (owner ruling 2026-10-06, decision D-025).
    "net_expenses": {
        "exact": ["InvestmentCompanyExpenseAfterReductionOfFeeWaiverAndReimbursement"],
        "fallback": [],
        "unit": "USD", "instant": False,
        # Compared with the quarter's income and gross expenses, so an average over the year would
        # be on another basis. HPS and Blue Owl file this figure for 2024 in the 10-K only.
        "quarter_only": True,
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
    # Fund-level total cost of investments (sibling of investments_at_fair_value).
    # Independent anchor for cost reconciliation; 75/76 BDC-cohort coverage.
    "investments_at_cost": {
        "exact": ["InvestmentOwnedAtCost"],
        "fallback": [],
        "unit": "USD", "instant": True,
    },
    # Fund-level cash equivalents the filer tags separately from investments (money-market
    # sweeps, T-bills held for cash management). With investments_at_fair_value this forms the
    # deterministic PUBLISHED-ROWS anchor (spec 2026-09-07 s.2). No fallback on purpose:
    # CashAndCashEquivalentsAtCarryingValue includes bank cash and would overstate.
    "cash_equivalents_at_fair_value": {
        "exact": ["CashEquivalentsAtCarryingValue", "MoneyMarketFundsAtCarryingValue"],
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
    from pipeline.fund_highlights_wrapper import income_ratio_as_filed_from

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
        for concept in spec.get("missing_date_concepts", []):
            additional = _extract_concept_series(
                facts, [concept], spec["unit"], spec["instant"],
            )
            series.update({day: value for day, value in additional.items() if day not in series})
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
                as_filed_from = income_ratio_as_filed_from(cik) if spec.get("ratio") else None
                series = _extract_duration_series(
                    facts, spec["exact"], spec["unit"], ratio=bool(spec.get("ratio")),
                    quarter_only=bool(spec.get("quarter_only")), ratio_as_filed_from=as_filed_from,
                )
                if not series and spec.get("fallback"):
                    series = _extract_duration_series(
                        facts, spec["fallback"], spec["unit"], ratio=bool(spec.get("ratio")),
                        quarter_only=bool(spec.get("quarter_only")), ratio_as_filed_from=as_filed_from,
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
    from pipeline.fund_highlights_wrapper import drop_ignored_accessions
    for cik in bdc_ciks:
        facts = _load_companyfacts_cached(cik, companyfacts_cache_dir)
        if not facts:
            continue
        # A filing whose facts the filer dated to the wrong period (wrapper opt-in, one fund)
        facts = drop_ignored_accessions(cik, facts)
        rows = _extract_bdc_balance_sheet(cik, facts)
        all_rows.extend(rows)

    if not all_rows:
        return pd.DataFrame(columns=[
            "cik", "report_date", "total_assets", "total_liabilities",
            "net_assets", "nav_per_share", "shares_outstanding", "borrowings",
            "investments_at_fair_value",
        ] + _EXTENDED_FIELDS)

    return pd.DataFrame(all_rows)


