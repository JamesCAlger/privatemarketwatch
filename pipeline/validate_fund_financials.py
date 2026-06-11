"""Fund-level financial validation.

Produces deterministic fund-period validation artifacts for ``fund_financials.csv``.
This is the fund-level counterpart to the unified holdings validation stack: it
reports check results, severities, evidence strength, and derived quality tiers
without mutating source data.
"""

from __future__ import annotations

import logging
import math
from datetime import date
from typing import Optional

import duckdb
import pandas as pd

from pipeline.config import (
    COMBINED_UNIVERSE_FILE,
    FUND_FINANCIALS_CROSS_LEVEL_FILE,
    FUND_FINANCIALS_FILE,
    FUND_FINANCIALS_QUALITY_METRICS_FILE,
    FUND_FINANCIALS_VALIDATION_CURRENT_FILE,
    UNIFIED_HOLDINGS_FILE,
)
from pipeline.column_validation import (
    EVIDENCE_MODERATE,
    EVIDENCE_STRONG,
    EVIDENCE_WEAK,
    SEVERITY_FAIL,
    SEVERITY_INFO,
    SEVERITY_WARN,
)

logger = logging.getLogger(__name__)

DATASET = "fund_financials"

STATUS_PASS = "PASS"
STATUS_FAIL = "FAIL"
STATUS_SKIP = "SKIP"

RESULT_COLUMNS = [
    "dataset", "cik", "report_quarter", "report_date", "check_code",
    "status", "severity", "evidence_strength", "value", "expected",
    "mechanism", "source_artifacts", "note",
]

QUALITY_COLUMNS = [
    "dataset", "cik", "report_quarter", "report_date", "validation_tier",
    "fail_count", "warn_count", "info_count", "strong_issue_count",
    "moderate_issue_count", "weak_issue_count",
]

NUMERIC_EXPORT_COLUMNS = [
    "total_assets", "net_assets", "total_liabilities",
    "nav_per_share", "shares_outstanding", "borrowings",
    "total_investment_income", "net_investment_income",
    "leverage_ratio", "quarterly_return",
    "management_fee_pct", "expense_ratio_pct",
    "distribution_per_share", "distribution_rate",
    "total_return_pct", "income_per_share", "income_yield_pct",
    "portfolio_turnover", "asset_coverage_ratio",
    "unfunded_commitments", "premium_discount_pct",
    "distribution_rate_proxy", "redemption_pressure",
    "annualized_return",
    "monthly_return_1", "monthly_return_2", "monthly_return_3",
]

REQUIRED_FUND_COLUMNS = [
    "cik", "entity_name", "vehicle_type", "source", "report_quarter",
    "report_date", "investments_at_fair_value", *NUMERIC_EXPORT_COLUMNS,
]


def _empty_results() -> pd.DataFrame:
    return pd.DataFrame(columns=RESULT_COLUMNS)


def _empty_quality() -> pd.DataFrame:
    return pd.DataFrame(columns=QUALITY_COLUMNS)


def _prepare_fund_df(df: pd.DataFrame) -> pd.DataFrame:
    prepared = df.copy()
    for col in REQUIRED_FUND_COLUMNS:
        if col not in prepared.columns:
            prepared[col] = ""
    prepared["cik"] = prepared["cik"].astype(str).str.zfill(10)
    prepared["report_quarter"] = prepared["report_quarter"].fillna("").astype(str)
    prepared["report_date"] = prepared["report_date"].fillna("").astype(str)
    return prepared


def _num(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce")


def _is_present_finite_number(raw: object) -> bool:
    """Return True for blank/null or a parseable finite numeric value."""
    if raw is None:
        return True
    if pd.isna(raw):
        return True
    text = str(raw).strip()
    if text == "":
        return True
    try:
        return math.isfinite(float(text))
    except (TypeError, ValueError):
        return False


def _quarter_from_date_sql(date_expr: str) -> str:
    return f"""
        CASE WHEN TRY_CAST({date_expr} AS DATE) IS NOT NULL THEN
            CAST(YEAR(TRY_CAST({date_expr} AS DATE)) AS VARCHAR)
            || 'q'
            || CAST(QUARTER(TRY_CAST({date_expr} AS DATE)) AS VARCHAR)
        ELSE ''
        END
    """


def _result(
    row: pd.Series | dict,
    check_code: str,
    status: str,
    value: object = "",
    expected: str = "",
    severity: str = "",
    evidence_strength: str = "",
    note: str = "",
    mechanism: str = "",
    source_artifacts: str = "fund_financials.csv",
) -> dict:
    return {
        "dataset": DATASET,
        "cik": str(row.get("cik", "") or "").zfill(10),
        "report_quarter": str(row.get("report_quarter", "") or ""),
        "report_date": str(row.get("report_date", "") or ""),
        "check_code": check_code,
        "status": status,
        "severity": severity if status == STATUS_FAIL else "",
        "evidence_strength": evidence_strength if status == STATUS_FAIL else "",
        "value": "" if pd.isna(value) else str(value),
        "expected": expected,
        "mechanism": mechanism,
        "source_artifacts": source_artifacts,
        "note": note,
    }


def _append_threshold_results(
    rows: list[dict],
    df: pd.DataFrame,
    check_code: str,
    value: pd.Series,
    fail_mask: pd.Series,
    missing_mask: pd.Series,
    expected: str,
    severity: str,
    evidence_strength: str,
    note: str,
) -> None:
    for idx, row in df.iterrows():
        if bool(missing_mask.loc[idx]):
            rows.append(_result(row, check_code, STATUS_SKIP, expected=expected,
                                note="required field missing"))
        elif bool(fail_mask.loc[idx]):
            rows.append(_result(row, check_code, STATUS_FAIL,
                                value=value.loc[idx], expected=expected,
                                severity=severity,
                                evidence_strength=evidence_strength,
                                note=note))
        else:
            rows.append(_result(row, check_code, STATUS_PASS,
                                value=value.loc[idx], expected=expected))


def validate_fund_source(df: pd.DataFrame) -> pd.DataFrame:
    """Validate fund_financials.csv internal consistency and ranges."""
    if df.empty:
        return _empty_results()
    fund = _prepare_fund_df(df)
    rows: list[dict] = []

    # F1: exported numeric values must be finite when present.
    for idx, row in fund.iterrows():
        bad_cols = []
        for col in NUMERIC_EXPORT_COLUMNS:
            raw = row.get(col, "")
            if not _is_present_finite_number(raw):
                bad_cols.append(col)
        if bad_cols:
            rows.append(_result(
                row, "F1", STATUS_FAIL, value=",".join(bad_cols),
                expected="numeric export values finite or null",
                severity=SEVERITY_FAIL,
                evidence_strength=EVIDENCE_STRONG,
                note="non-finite numeric export value",
            ))
        else:
            rows.append(_result(row, "F1", STATUS_PASS,
                                expected="numeric export values finite or null"))

    # F2: report dates cannot be in the future.
    report_dates = pd.to_datetime(fund["report_date"], errors="coerce")
    today = pd.Timestamp(date.today())
    _append_threshold_results(
        rows, fund, "F2", report_dates.dt.strftime("%Y-%m-%d"),
        report_dates > today,
        report_dates.isna(),
        "report_date <= today",
        SEVERITY_FAIL,
        EVIDENCE_STRONG,
        "future report_date",
    )

    expected_quarter = report_dates.apply(
        lambda d: f"{d.year}q{d.quarter}" if pd.notna(d) else "",
    )
    f3_missing = report_dates.isna() | (fund["report_quarter"].str.strip() == "")
    f3_fail = fund["report_quarter"].str.strip() != expected_quarter
    _append_threshold_results(
        rows, fund, "F3", fund["report_quarter"],
        f3_fail, f3_missing,
        "report_quarter equals calendar quarter of report_date",
        SEVERITY_FAIL,
        EVIDENCE_STRONG,
        "report_quarter inconsistent with report_date",
    )

    total_assets = _num(fund["total_assets"])
    net_assets = _num(fund["net_assets"])
    liabilities = _num(fund["total_liabilities"])
    nav = _num(fund["nav_per_share"])
    shares = _num(fund["shares_outstanding"])
    borrowings = _num(fund["borrowings"])
    leverage = _num(fund["leverage_ratio"])
    management_fee_pct = _num(fund["management_fee_pct"])
    expense_ratio_pct = _num(fund["expense_ratio_pct"])
    quarterly_return = _num(fund["quarterly_return"])
    m1 = _num(fund["monthly_return_1"])
    m2 = _num(fund["monthly_return_2"])
    m3 = _num(fund["monthly_return_3"])
    distribution_rate = _num(fund["distribution_rate"])
    income_yield_pct = _num(fund["income_yield_pct"])
    asset_coverage = _num(fund["asset_coverage_ratio"])

    # F10: total assets - total liabilities = net assets within 1% of assets.
    f10_value = total_assets - liabilities - net_assets
    f10_missing = total_assets.isna() | liabilities.isna() | net_assets.isna() | (total_assets <= 0)
    f10_fail = f10_value.abs() > total_assets.abs() * 0.01
    _append_threshold_results(
        rows, fund, "F10", f10_value, f10_fail, f10_missing,
        "abs(total_assets - total_liabilities - net_assets) <= 1% total_assets",
        SEVERITY_FAIL, EVIDENCE_STRONG,
        "balance sheet identity does not reconcile",
    )

    # F11: NAV identity within 2% of net assets.
    f11_value = nav * shares - net_assets
    f11_missing = nav.isna() | shares.isna() | net_assets.isna() | (net_assets <= 0)
    f11_fail = f11_value.abs() > net_assets.abs() * 0.02
    _append_threshold_results(
        rows, fund, "F11", f11_value, f11_fail, f11_missing,
        "abs(nav_per_share * shares_outstanding - net_assets) <= 2% net_assets",
        SEVERITY_WARN, EVIDENCE_MODERATE,
        "NAV/share identity does not reconcile",
    )

    # F12: leverage consistency. Exported leverage may be capped at 2.0.
    raw_leverage = borrowings / total_assets
    comparable_leverage = raw_leverage.clip(upper=2.0)
    f12_value = comparable_leverage - leverage
    f12_missing = borrowings.isna() | total_assets.isna() | leverage.isna() | (total_assets <= 0)
    f12_fail = f12_value.abs() > 0.05
    _append_threshold_results(
        rows, fund, "F12", f12_value, f12_fail, f12_missing,
        "abs(min(borrowings / total_assets, 2.0) - leverage_ratio) <= 5pp",
        SEVERITY_WARN, EVIDENCE_MODERATE,
        "leverage ratio inconsistent with borrowings and total assets",
    )

    # F13: management fee percentage should not exceed expense ratio percentage.
    f13_value = management_fee_pct - expense_ratio_pct
    f13_missing = management_fee_pct.isna() | expense_ratio_pct.isna()
    f13_fail = f13_value > 0
    _append_threshold_results(
        rows, fund, "F13", f13_value, f13_fail, f13_missing,
        "management_fee_pct <= expense_ratio_pct",
        SEVERITY_WARN, EVIDENCE_MODERATE,
        "management fee percentage exceeds expense ratio",
    )

    # F17: quarterly return equals product of monthly returns.
    computed_qr = ((1 + m1 / 100) * (1 + m2 / 100) * (1 + m3 / 100) - 1) * 100
    f17_value = quarterly_return - computed_qr
    f17_missing = quarterly_return.isna() | m1.isna() | m2.isna() | m3.isna()
    f17_fail = f17_value.abs() > 0.1
    _append_threshold_results(
        rows, fund, "F17", f17_value, f17_fail, f17_missing,
        "quarterly_return equals compounded monthly returns within 0.1pp",
        SEVERITY_FAIL, EVIDENCE_STRONG,
        "quarterly return inconsistent with monthly returns",
    )

    # Tier 3 range/anomaly checks.
    range_specs = [
        ("F30", nav, nav.isna(), (nav <= 0.01) | (nav >= 1000),
         "0.01 < nav_per_share < 1000", "NAV per share outside expected range"),
        ("F31", quarterly_return, quarterly_return.isna(),
         (quarterly_return <= -50) | (quarterly_return >= 50),
         "-50% < quarterly_return < 50%", "quarterly return outside expected range"),
        ("F32", expense_ratio_pct, expense_ratio_pct.isna(),
         (expense_ratio_pct <= 0) | (expense_ratio_pct >= 20),
         "0 < expense_ratio_pct < 20%", "expense ratio outside expected range"),
        ("F33", distribution_rate, distribution_rate.isna(),
         (distribution_rate <= 0) | (distribution_rate >= 30),
         "0 < distribution_rate < 30%", "distribution rate outside expected range"),
        ("F34", leverage, leverage.isna(),
         (leverage < 0) | (leverage > 2.0),
         "0 <= leverage_ratio <= 2.0", "leverage ratio outside expected range"),
    ]
    for code, value, missing, fail, expected, note in range_specs:
        _append_threshold_results(
            rows, fund, code, value, fail, missing, expected,
            SEVERITY_WARN, EVIDENCE_WEAK, note,
        )

    f16_value = distribution_rate - income_yield_pct * 1.5
    f16_missing = distribution_rate.isna() | income_yield_pct.isna()
    f16_fail = f16_value > 0
    _append_threshold_results(
        rows, fund, "F16", f16_value, f16_fail, f16_missing,
        "distribution_rate <= income_yield_pct * 1.5",
        SEVERITY_INFO, EVIDENCE_WEAK,
        "distribution rate exceeds income yield heuristic",
    )

    f18_missing = fund["vehicle_type"].str.lower().ne("bdc") | asset_coverage.isna()
    f18_fail = asset_coverage < 1.5
    _append_threshold_results(
        rows, fund, "F18", asset_coverage, f18_fail, f18_missing,
        "BDC asset_coverage_ratio >= 1.5",
        SEVERITY_WARN, EVIDENCE_MODERATE,
        "BDC asset coverage ratio below regulatory threshold",
    )

    return pd.DataFrame(rows, columns=RESULT_COLUMNS)


def validate_cross_level(
    fund_df: pd.DataFrame,
    holdings_df: Optional[pd.DataFrame] = None,
) -> pd.DataFrame:
    """Validate fund-level values against unified holdings aggregates."""
    if fund_df.empty:
        return _empty_results()
    if holdings_df is None:
        if not UNIFIED_HOLDINGS_FILE.exists():
            return _empty_results()
        holdings_df = pd.read_csv(UNIFIED_HOLDINGS_FILE, dtype=str)
    if holdings_df.empty:
        return _empty_results()

    fund = _prepare_fund_df(fund_df)
    con = duckdb.connect()
    con.register("ff", fund)
    con.register("h", holdings_df)
    cross = con.execute(f"""
        WITH fund AS (
            SELECT
                LPAD(CAST(cik AS VARCHAR), 10, '0') AS cik,
                CAST(report_quarter AS VARCHAR) AS report_quarter,
                CAST(report_date AS VARCHAR) AS report_date,
                TRY_CAST(total_assets AS DOUBLE) AS total_assets,
                TRY_CAST(net_assets AS DOUBLE) AS net_assets,
                TRY_CAST(investments_at_fair_value AS DOUBLE) AS inv_fv,
                TRY_CAST(borrowings AS DOUBLE) AS borrowings,
                TRY_CAST(income_yield_pct AS DOUBLE) AS income_yield_pct
            FROM ff
        ),
        hold AS (
            SELECT
                LPAD(CAST(cik AS VARCHAR), 10, '0') AS cik,
                {_quarter_from_date_sql('report_date')} AS report_quarter,
                MAX(CAST(report_date AS VARCHAR)) AS holdings_report_date,
                SUM(TRY_CAST(fair_value AS DOUBLE)) AS holdings_fv,
                SUM(TRY_CAST(pct_of_net_assets AS DOUBLE)) AS pct_sum,
                COUNT(*) AS position_count,
                SUM(
                    CASE WHEN TRY_CAST(interest_rate AS DOUBLE) > 0
                           AND TRY_CAST(fair_value AS DOUBLE) > 0
                         THEN TRY_CAST(interest_rate AS DOUBLE)
                              * TRY_CAST(fair_value AS DOUBLE)
                    END
                ) / NULLIF(SUM(
                    CASE WHEN TRY_CAST(interest_rate AS DOUBLE) > 0
                           AND TRY_CAST(fair_value AS DOUBLE) > 0
                         THEN TRY_CAST(fair_value AS DOUBLE)
                    END
                ), 0) AS wac
            FROM h
            WHERE TRY_CAST(fair_value AS DOUBLE) IS NOT NULL
            GROUP BY cik, report_quarter
        ),
        joined AS (
            SELECT
                COALESCE(fund.cik, hold.cik) AS cik,
                COALESCE(fund.report_quarter, hold.report_quarter) AS report_quarter,
                fund.report_date,
                hold.holdings_report_date,
                fund.total_assets,
                fund.net_assets,
                fund.inv_fv,
                fund.borrowings,
                fund.income_yield_pct,
                hold.holdings_fv,
                hold.pct_sum,
                hold.position_count,
                hold.wac,
                fund.cik IS NOT NULL AS has_fund,
                hold.cik IS NOT NULL AS has_holdings
            FROM fund
            FULL OUTER JOIN hold
              ON fund.cik = hold.cik
             AND fund.report_quarter = hold.report_quarter
        ),
        with_lag AS (
            SELECT *,
                LAG(position_count) OVER (PARTITION BY cik ORDER BY report_quarter) AS prev_position_count,
                LAG(holdings_fv) OVER (PARTITION BY cik ORDER BY report_quarter) AS prev_holdings_fv,
                LAG(total_assets) OVER (PARTITION BY cik ORDER BY report_quarter) AS prev_total_assets
            FROM joined
        )
        SELECT * FROM with_lag
        ORDER BY cik, report_quarter
    """).fetchdf()
    con.close()

    try:
        from pipeline.gav_reconciliation import build_gav_reconciliation

        gav_holdings = holdings_df.copy()
        for col, default in {
            "entity_name": "",
            "source": "bdc",
            "is_subsidiary": "0",
        }.items():
            if col not in gav_holdings.columns:
                gav_holdings[col] = default
        gav = build_gav_reconciliation(
            unified_df=gav_holdings,
            fund_financials_df=fund_df,
            nport_fund_info_df=pd.DataFrame(),
            bdc_source_df=pd.DataFrame(),
        )
    except Exception as exc:
        logger.warning("F20 canonical GAV reconciliation unavailable: %s", exc)
        gav = pd.DataFrame()
    gav_by_pair: dict[tuple[str, str], pd.Series] = {}
    if not gav.empty:
        for _, gav_row in gav.iterrows():
            gav_by_pair[(
                str(gav_row.get("cik", "")).zfill(10),
                str(gav_row.get("report_date", "")),
            )] = gav_row

    rows: list[dict] = []
    for _, row in cross.iterrows():
        base = {
            "cik": row.get("cik", ""),
            "report_quarter": row.get("report_quarter", ""),
            "report_date": row.get("report_date", "") or row.get("holdings_report_date", ""),
        }

        def add(code: str, status: str, value: object = "", expected: str = "",
                severity: str = SEVERITY_WARN, evidence: str = EVIDENCE_MODERATE,
                note: str = "") -> None:
            rows.append(_result(
                base, code, status, value=value, expected=expected,
                severity=severity, evidence_strength=evidence, note=note,
                source_artifacts="fund_financials.csv;private_markets_holdings.csv",
            ))

        holdings_fv = row.get("holdings_fv")
        inv_fv = row.get("inv_fv")
        net_assets = row.get("net_assets")
        total_assets = row.get("total_assets")
        pct_sum = row.get("pct_sum")
        position_count = row.get("position_count")

        gav_key = (str(base["cik"]).zfill(10), str(base["report_date"]))
        gav_row = gav_by_pair.get(gav_key)
        if gav_row is None:
            add("F20", STATUS_SKIP, expected="canonical GAV reconciliation row exists")
        else:
            gav_status = str(gav_row.get("reconciliation_status", "") or "").upper()
            status = STATUS_PASS if gav_status == "PASS" else (
                STATUS_SKIP if gav_status == "SKIP" else STATUS_FAIL
            )
            severity = SEVERITY_FAIL if gav_status == "FAIL" else SEVERITY_WARN
            evidence = EVIDENCE_STRONG if gav_status == "FAIL" else EVIDENCE_MODERATE
            add(
                "F20",
                status,
                value=gav_row.get("gav_ratio_adjusted") or gav_row.get("gav_ratio") or "",
                expected="canonical GAV reconciliation_status is PASS",
                severity=severity,
                evidence=evidence,
                note=(
                    "canonical GAV reconciliation status="
                    f"{gav_status}; source={gav_row.get('comparison_source', '')}; "
                    f"scope={gav_row.get('failure_scope', '')}"
                ),
            )

        if pd.isna(holdings_fv) or pd.isna(net_assets) or net_assets <= 0:
            add("F21", STATUS_SKIP, expected="0.5 <= holdings_fv / net_assets <= 2.5")
        else:
            ratio = holdings_fv / net_assets
            add("F21", STATUS_FAIL if ratio < 0.5 or ratio > 2.5 else STATUS_PASS,
                value=round(ratio, 4),
                expected="0.5 <= holdings_fv / net_assets <= 2.5",
                note="holdings FV to net assets ratio outside expected range")

        if pd.isna(pct_sum):
            add("F22", STATUS_SKIP, expected="50 <= sum(pct_of_net_assets) <= 400")
        else:
            add("F22", STATUS_FAIL if pct_sum < 50 or pct_sum > 400 else STATUS_PASS,
                value=round(pct_sum, 4),
                expected="50 <= sum(pct_of_net_assets) <= 400",
                note="pct_of_net_assets sum indicates incomplete extraction or duplication")

        if pd.isna(holdings_fv) or pd.isna(net_assets) or net_assets <= 0 or pd.isna(pct_sum):
            add("F23", STATUS_SKIP, expected="computed pct and reported pct differ by <= 10% relative")
        else:
            computed_pct = holdings_fv / net_assets * 100
            rel_diff = abs(computed_pct - pct_sum) / max(abs(computed_pct), 1)
            add("F23", STATUS_FAIL if rel_diff > 0.10 else STATUS_PASS,
                value=round(rel_diff, 4),
                expected="computed pct and reported pct differ by <= 10% relative",
                note="reported pct_of_net_assets inconsistent with FV/net assets")

        prev_count = row.get("prev_position_count")
        if pd.isna(position_count) or pd.isna(prev_count) or prev_count <= 0:
            add("F24", STATUS_SKIP, expected="0.5 <= position_count_q / position_count_prior_q <= 2.0")
        else:
            ratio = position_count / prev_count
            add("F24", STATUS_FAIL if ratio < 0.5 or ratio > 2.0 else STATUS_PASS,
                value=round(ratio, 4),
                expected="0.5 <= position_count_q / position_count_prior_q <= 2.0",
                note="position count changed sharply quarter-over-quarter")

        prev_hfv = row.get("prev_holdings_fv")
        prev_assets = row.get("prev_total_assets")
        if (pd.isna(holdings_fv) or pd.isna(prev_hfv) or prev_hfv <= 0
                or pd.isna(total_assets) or pd.isna(prev_assets) or prev_assets <= 0):
            add("F25", STATUS_SKIP, expected="holdings FV growth and total assets growth differ by <= 30pp")
        else:
            h_growth = holdings_fv / prev_hfv - 1
            a_growth = total_assets / prev_assets - 1
            diff = abs(h_growth - a_growth)
            add("F25", STATUS_FAIL if diff > 0.30 else STATUS_PASS,
                value=round(diff, 4),
                expected="holdings FV growth and total assets growth differ by <= 30pp",
                note="holdings FV growth diverges from total assets growth")

        borrowings = row.get("borrowings")
        if (pd.isna(borrowings) or pd.isna(total_assets) or total_assets <= 0
                or pd.isna(holdings_fv) or holdings_fv <= 0
                or pd.isna(net_assets)):
            add("F26", STATUS_SKIP, expected="two leverage views differ by <= 20pp")
        else:
            fund_lev = borrowings / total_assets
            holdings_lev = (holdings_fv - net_assets) / holdings_fv
            diff = abs(fund_lev - holdings_lev)
            add("F26", STATUS_FAIL if diff > 0.20 else STATUS_PASS,
                value=round(diff, 4),
                expected="two leverage views differ by <= 20pp",
                evidence=EVIDENCE_WEAK,
                note="fund and holdings leverage proxies diverge")

        wac = row.get("wac")
        income_yield = row.get("income_yield_pct")
        if pd.isna(wac) or pd.isna(income_yield):
            add("F27", STATUS_SKIP, expected="income_yield_pct <= WAC + 200bps")
        else:
            diff = income_yield - wac
            add("F27", STATUS_FAIL if diff > 2.0 else STATUS_PASS,
                value=round(diff, 4),
                expected="income_yield_pct <= WAC + 200bps",
                evidence=EVIDENCE_WEAK,
                note="income yield exceeds holdings WAC heuristic")

        has_fund = bool(row.get("has_fund"))
        has_holdings = bool(row.get("has_holdings"))
        add("F28", STATUS_FAIL if has_fund != has_holdings else STATUS_PASS,
            value=f"fund={has_fund};holdings={has_holdings}",
            expected="fund_financials and holdings both present or both absent",
            note="fund_financials/holdings coverage mismatch")

    return pd.DataFrame(rows, columns=RESULT_COLUMNS)


def build_quality_metrics(results: pd.DataFrame) -> pd.DataFrame:
    """Build per-CIK-quarter quality tier summary from fund validation results."""
    if results.empty:
        return _empty_quality()
    issues = results[results["status"] == STATUS_FAIL].copy()
    base = results[["dataset", "cik", "report_quarter", "report_date"]].drop_duplicates()
    if issues.empty:
        base["validation_tier"] = "VERIFIED"
        for col in QUALITY_COLUMNS[5:]:
            base[col] = 0
        return base[QUALITY_COLUMNS]

    grouped = issues.groupby(["dataset", "cik", "report_quarter"], dropna=False).agg(
        report_date=("report_date", "max"),
        fail_count=("severity", lambda s: int((s == SEVERITY_FAIL).sum())),
        warn_count=("severity", lambda s: int((s == SEVERITY_WARN).sum())),
        info_count=("severity", lambda s: int((s == SEVERITY_INFO).sum())),
        strong_issue_count=("evidence_strength", lambda s: int((s == EVIDENCE_STRONG).sum())),
        moderate_issue_count=("evidence_strength", lambda s: int((s == EVIDENCE_MODERATE).sum())),
        weak_issue_count=("evidence_strength", lambda s: int((s == EVIDENCE_WEAK).sum())),
    ).reset_index()
    summary = base.drop(columns=["report_date"]).merge(
        grouped, on=["dataset", "cik", "report_quarter"], how="left"
    )
    summary["report_date"] = summary["report_date"].fillna("")
    for col in QUALITY_COLUMNS[5:]:
        summary[col] = summary[col].fillna(0).astype(int)
    summary["validation_tier"] = "VERIFIED"
    summary.loc[summary["warn_count"] > 0, "validation_tier"] = "VALIDATED_WITH_WARNINGS"
    summary.loc[summary["fail_count"] > 0, "validation_tier"] = "UNDER_REVIEW"
    return summary[QUALITY_COLUMNS]


def _fund_period_cross_level_rows(
    cross_results: pd.DataFrame,
    fund_df: pd.DataFrame,
) -> pd.DataFrame:
    """Keep persisted cross-level diagnostics referential to fund_financials."""
    if cross_results.empty or fund_df.empty:
        return cross_results.iloc[0:0].copy()

    fund = _prepare_fund_df(fund_df)
    valid_pairs = set(zip(fund["cik"], fund["report_quarter"]))
    out = cross_results.copy()
    pairs = zip(
        out["cik"].fillna("").astype(str).str.zfill(10),
        out["report_quarter"].fillna("").astype(str),
    )
    mask = [pair in valid_pairs for pair in pairs]
    return out.loc[mask].copy()


def validate_fund_financials(
    fund_df: Optional[pd.DataFrame] = None,
    holdings_df: Optional[pd.DataFrame] = None,
    universe_df: Optional[pd.DataFrame] = None,
    write: bool = True,
) -> dict[str, pd.DataFrame]:
    """Run fund-level validation and optionally write output artifacts."""
    del universe_df  # Reserved for F39/F40 implementation.
    if fund_df is None:
        if not FUND_FINANCIALS_FILE.exists():
            logger.error("Fund financials file not found: %s", FUND_FINANCIALS_FILE)
            return {
                "fund_validation": _empty_results(),
                "fund_quality": _empty_quality(),
                "fund_cross_level": _empty_results(),
            }
        fund_df = pd.read_csv(FUND_FINANCIALS_FILE, dtype=str)

    source_results = validate_fund_source(fund_df)
    cross_results = validate_cross_level(fund_df, holdings_df=holdings_df)
    all_results = pd.concat(
        [df for df in [source_results, cross_results] if not df.empty],
        ignore_index=True,
    ) if not source_results.empty or not cross_results.empty else _empty_results()
    quality = build_quality_metrics(all_results)

    if write:
        persisted_cross = _fund_period_cross_level_rows(cross_results, fund_df)
        all_results.to_csv(FUND_FINANCIALS_VALIDATION_CURRENT_FILE, index=False)
        quality.to_csv(FUND_FINANCIALS_QUALITY_METRICS_FILE, index=False)
        persisted_cross.to_csv(FUND_FINANCIALS_CROSS_LEVEL_FILE, index=False)
        logger.info("  Saved %s", FUND_FINANCIALS_VALIDATION_CURRENT_FILE.name)
        logger.info("  Saved %s", FUND_FINANCIALS_QUALITY_METRICS_FILE.name)
        logger.info("  Saved %s", FUND_FINANCIALS_CROSS_LEVEL_FILE.name)

    logger.info(
        "Fund financials validation: %d check rows, %d quality rows",
        len(all_results), len(quality),
    )
    return {
        "fund_validation": all_results[RESULT_COLUMNS],
        "fund_quality": quality[QUALITY_COLUMNS],
        "fund_cross_level": cross_results[RESULT_COLUMNS],
    }
