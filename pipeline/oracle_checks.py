"""Comprehensive BDC XBRL Oracle -- independent check functions.

Each check function takes standardized inputs and returns a list of CheckResult
objects.  Checks are grouped into 9 categories:

  A: Arithmetic Invariants   (derived truth -- highest confidence)
  B: Structural Invariants   (hierarchy integrity)
  C: Content Invariants      (archetype-driven field expectations)
  D: Cross-Quarter Stability (QoQ drift detection)
  E: Cross-Reference Checks  (fund financials triangulation)
  F: Data Quality            (field-level sanity)
  G: Aggregate Leak Detection
  H: Source Completeness
  I: Wrapper-Specific Checks

This module is a diagnostic layer: it does not mutate holdings data.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# CheckResult dataclass
# ---------------------------------------------------------------------------

@dataclass
class CheckResult:
    """Result of a single oracle check for one scope (CIK-quarter, CIK, or global)."""
    check_id: str           # e.g. "A01_subtotal_arithmetic"
    scope: str              # "cik_quarter" | "cik" | "global"
    status: str             # "pass" | "fail" | "warn" | "skip"
    metric_value: float     # the measured quantity
    threshold: float        # the pass/fail threshold
    residual_rows: int      # rows involved in the failure
    residual_fv: float      # FV involved in the failure
    detail: pd.DataFrame = field(default_factory=pd.DataFrame)  # row-level detail
    message: str = ""       # human-readable summary
    cik: str = ""
    report_date: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "check_id": self.check_id,
            "scope": self.scope,
            "status": self.status,
            "metric_value": self.metric_value,
            "threshold": self.threshold,
            "residual_rows": self.residual_rows,
            "residual_fv": self.residual_fv,
            "message": self.message,
            "cik": self.cik,
            "report_date": self.report_date,
            "detail_rows": len(self.detail),
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _safe_float(val: Any) -> float:
    """Coerce to float, returning 0.0 on failure."""
    try:
        v = float(val)
        if pd.isna(v):
            return 0.0
        return v
    except (ValueError, TypeError):
        return 0.0


def _pct_diff(actual: float, expected: float) -> float:
    """Absolute percentage difference."""
    if expected == 0:
        return 0.0 if actual == 0 else float("inf")
    return abs(actual - expected) / abs(expected)


def _col_float(df: pd.DataFrame, col: str) -> pd.Series:
    """Get a column as float, filling NaN with 0."""
    if col not in df.columns:
        return pd.Series(0.0, index=df.index)
    return pd.to_numeric(df[col], errors="coerce").fillna(0.0)


def _col_str(df: pd.DataFrame, col: str) -> pd.Series:
    """Get a column as str, filling empty."""
    if col not in df.columns:
        return pd.Series("", index=df.index)
    return df[col].fillna("").astype(str)


def _is_present(val: Any) -> bool:
    """Return True if value is non-null, non-empty, non-NaN."""
    if val is None:
        return False
    if isinstance(val, float) and pd.isna(val):
        return False
    s = str(val).strip()
    return s != "" and s.lower() not in ("nan", "none", "nat")


def _make_result(
    check_id: str,
    scope: str,
    status: str,
    metric_value: float,
    threshold: float,
    message: str,
    detail: pd.DataFrame | None = None,
    cik: str = "",
    report_date: str = "",
) -> CheckResult:
    residual = detail if detail is not None else pd.DataFrame()
    residual_fv = 0.0
    if not residual.empty:
        for col in ("fair_value", "source_fair_value", "output_fair_value"):
            if col in residual.columns:
                residual_fv = _col_float(residual, col).sum()
                break
    return CheckResult(
        check_id=check_id,
        scope=scope,
        status=status,
        metric_value=metric_value,
        threshold=threshold,
        residual_rows=len(residual),
        residual_fv=residual_fv,
        detail=residual,
        message=message,
        cik=cik,
        report_date=report_date,
    )


# ===================================================================
# CATEGORY A: ARITHMETIC INVARIANTS
# ===================================================================

def check_A01_subtotal_arithmetic(
    source_detail_df: pd.DataFrame,
    *,
    tolerance_pct: float = 0.005,
    tolerance_abs: float = 1000,
) -> list[CheckResult]:
    """A01: For each rollup row, verify rollup_fv == sum(child_leaf_fv)."""
    results = []
    if source_detail_df.empty:
        return [_make_result("A01", "global", "skip", 0, tolerance_pct,
                             "No source detail data available")]

    df = source_detail_df.copy()
    # Identify rollup rows (source disposition ends with _rollup)
    rollup_mask = _col_str(df, "source_wrapper_disposition").str.endswith("_rollup")
    leaf_mask = _col_str(df, "source_wrapper_disposition").str.endswith("_position_leaf")

    if not rollup_mask.any():
        return [_make_result("A01", "global", "skip", 0, tolerance_pct,
                             "No rollup rows found in source detail")]

    rollups = df[rollup_mask].copy()
    leaves = df[leaf_mask].copy()

    for group_key, group in rollups.groupby(
        ["cik", "report_date", "accession_number"], dropna=False
    ):
        cik, rd, acc = str(group_key[0]), str(group_key[1]), str(group_key[2])
        group_leaves = leaves[
            (_col_str(leaves, "cik") == cik)
            & (_col_str(leaves, "report_date") == rd)
            & (_col_str(leaves, "accession_number") == acc)
        ]

        failures = []
        for _, rollup_row in group.iterrows():
            rollup_fv = _safe_float(rollup_row.get("source_fair_value", 0))
            parent_key = str(rollup_row.get("source_wrapper_parent_key", "") or "")
            family = str(rollup_row.get("source_wrapper_family", "") or "")

            if not parent_key:
                continue

            # Find child leaves whose parent_key contains this rollup's parent_key
            child_mask = (
                _col_str(group_leaves, "source_wrapper_parent_key").str.contains(
                    re.escape(parent_key), na=False, regex=True
                )
            )
            if family:
                child_mask = child_mask & (_col_str(group_leaves, "source_wrapper_family") == family)

            children = group_leaves[child_mask]
            if children.empty:
                continue

            child_sum = _col_float(children, "source_fair_value").sum()
            diff = abs(rollup_fv - child_sum)
            if rollup_fv != 0 and diff > tolerance_abs and _pct_diff(child_sum, rollup_fv) > tolerance_pct:
                failures.append({
                    "cik": cik,
                    "report_date": rd,
                    "parent_key": parent_key,
                    "rollup_fv": rollup_fv,
                    "child_sum_fv": child_sum,
                    "diff": diff,
                    "pct_diff": _pct_diff(child_sum, rollup_fv),
                    "child_count": len(children),
                })

        fail_df = pd.DataFrame(failures) if failures else pd.DataFrame()
        n_rollups = len(group)
        n_pass = n_rollups - len(failures)
        status = "pass" if not failures else "fail"
        metric = n_pass / max(n_rollups, 1)
        results.append(_make_result(
            "A01", "cik_quarter", status, metric, 1.0 - tolerance_pct,
            f"{cik}/{rd}: {n_pass}/{n_rollups} rollups pass arithmetic check"
            + (f"; {len(failures)} failures" if failures else ""),
            detail=fail_df, cik=cik, report_date=rd,
        ))

    return results


def check_A04_gav_reconciliation(
    holdings_df: pd.DataFrame,
    fund_financials_df: pd.DataFrame | None = None,
    *,
    bdc_tolerance: float = 0.05,
    nport_tolerance: float = 0.10,
) -> list[CheckResult]:
    """A04: GAV reconciliation -- sum(leaf_fv) vs investments_at_fair_value."""
    results = []
    if holdings_df.empty:
        return [_make_result("A04", "global", "skip", 0, bdc_tolerance,
                             "No holdings data available")]
    if fund_financials_df is None or fund_financials_df.empty:
        return [_make_result("A04", "global", "skip", 0, bdc_tolerance,
                             "No fund financials available")]

    for (cik, rd), group in holdings_df.groupby(["cik", "report_date"], dropna=False):
        cik_s, rd_s = str(cik), str(rd)
        holdings_fv = _col_float(group, "fair_value").sum()

        ff_match = fund_financials_df[
            (_col_str(fund_financials_df, "cik").str.zfill(10) == cik_s.zfill(10))
            & (_col_str(fund_financials_df, "report_date") == rd_s)
        ]
        if ff_match.empty:
            results.append(_make_result(
                "A04", "cik_quarter", "skip", 0, bdc_tolerance,
                f"{cik_s}/{rd_s}: No fund financials for comparison",
                cik=cik_s, report_date=rd_s,
            ))
            continue

        inv_fv = _safe_float(ff_match.iloc[0].get("investments_at_fair_value", 0))
        total_assets = _safe_float(ff_match.iloc[0].get("total_assets", 0))
        comparison = inv_fv if inv_fv > 0 else total_assets
        if comparison == 0:
            results.append(_make_result(
                "A04", "cik_quarter", "skip", 0, bdc_tolerance,
                f"{cik_s}/{rd_s}: No nonzero comparison value in fund financials",
                cik=cik_s, report_date=rd_s,
            ))
            continue

        source_str = _col_str(group, "source")
        is_bdc = source_str.str.lower().eq("bdc").any()
        tol = bdc_tolerance if is_bdc else nport_tolerance
        diff_pct = _pct_diff(holdings_fv, comparison)
        status = "pass" if diff_pct <= tol else "fail"

        results.append(_make_result(
            "A04", "cik_quarter", status, diff_pct, tol,
            f"{cik_s}/{rd_s}: holdings_fv={holdings_fv:,.0f} vs "
            f"comparison={comparison:,.0f} ({diff_pct:.1%} diff, tol={tol:.0%})",
            cik=cik_s, report_date=rd_s,
        ))

    return results


def check_A07_pct_of_net_assets_sum(
    holdings_df: pd.DataFrame,
    *,
    min_sum: float = 50,
    max_sum: float = 250,
    outlier_threshold: float = 25,
) -> list[CheckResult]:
    """A07: sum(pct_of_net_assets) should be between 50% and 250% for BDC."""
    results = []
    if holdings_df.empty or "pct_of_net_assets" not in holdings_df.columns:
        return [_make_result("A07", "global", "skip", 0, max_sum,
                             "No pct_of_net_assets data")]

    for (cik, rd), group in holdings_df.groupby(["cik", "report_date"], dropna=False):
        cik_s, rd_s = str(cik), str(rd)
        pcts = _col_float(group, "pct_of_net_assets")
        pct_sum = pcts.sum()
        outliers = pcts[pcts.abs() > outlier_threshold]

        status = "pass" if min_sum <= pct_sum <= max_sum else "fail"
        if not outliers.empty:
            status = "warn" if status == "pass" else status

        results.append(_make_result(
            "A07", "cik_quarter", status, pct_sum, max_sum,
            f"{cik_s}/{rd_s}: pct_sum={pct_sum:.1f}%"
            + (f"; {len(outliers)} outliers > {outlier_threshold}%" if not outliers.empty else ""),
            cik=cik_s, report_date=rd_s,
        ))

    return results


# ===================================================================
# CATEGORY B: STRUCTURAL INVARIANTS
# ===================================================================

def check_B01_leaf_completeness(
    source_detail_df: pd.DataFrame,
) -> list[CheckResult]:
    """B01: Every XBRL leaf context should have fair_value populated."""
    results = []
    if source_detail_df.empty:
        return [_make_result("B01", "global", "skip", 0, 0,
                             "No source detail data")]

    df = source_detail_df.copy()
    leaf_mask = _col_str(df, "source_wrapper_disposition").str.endswith("_position_leaf")
    leaves = df[leaf_mask]

    if leaves.empty:
        return [_make_result("B01", "global", "skip", 0, 0, "No leaf rows found")]

    for (cik, rd), group in leaves.groupby(["cik", "report_date"], dropna=False):
        cik_s, rd_s = str(cik), str(rd)
        fv = _col_float(group, "source_fair_value")
        missing = group[fv.eq(0) & ~_col_str(group, "source_fair_value").str.strip().ne("")]
        # More precisely: rows where source_fair_value is genuinely absent
        no_fv = group[
            group.get("source_fair_value", pd.Series(dtype=str)).isin(["", None])
            | group.get("source_fair_value", pd.Series(dtype=str)).isna()
        ] if "source_fair_value" in group.columns else pd.DataFrame()

        total = len(group)
        with_fv = total - len(no_fv)
        rate = with_fv / max(total, 1)
        status = "pass" if rate >= 0.95 else "fail"

        results.append(_make_result(
            "B01", "cik_quarter", status, rate, 0.95,
            f"{cik_s}/{rd_s}: {with_fv}/{total} leaves have fair_value ({rate:.1%})",
            detail=no_fv, cik=cik_s, report_date=rd_s,
        ))

    return results


def check_B02_unique_position_keys(
    holdings_df: pd.DataFrame,
) -> list[CheckResult]:
    """B02: No two leaf rows share (CIK, report_date, wrapper_position_key)."""
    results = []
    if holdings_df.empty:
        return [_make_result("B02", "global", "skip", 0, 0, "No holdings data")]

    # Prefer the actual unified matching key.  Wrapper/source columns are
    # fallbacks for source-detail checks that do not carry unified position_key.
    key_col = None
    for candidate in ("position_key", "wrapper_position_key", "bdc_investment_identifier"):
        if candidate in holdings_df.columns:
            key_col = candidate
            break

    if key_col is None:
        return [_make_result("B02", "global", "skip", 0, 0,
                             "No position key column available")]

    for (cik, rd), group in holdings_df.groupby(["cik", "report_date"], dropna=False):
        cik_s, rd_s = str(cik), str(rd)
        keys = _col_str(group, key_col)
        non_empty = keys[keys.str.strip().ne("")]
        dupes = non_empty[non_empty.duplicated(keep=False)]
        status = "pass" if dupes.empty else "fail"

        results.append(_make_result(
            "B02", "cik_quarter", status, len(dupes), 0,
            f"{cik_s}/{rd_s}: {len(dupes)} duplicate position keys"
            + (f" (e.g. {dupes.iloc[0][:60]})" if not dupes.empty else ""),
            cik=cik_s, report_date=rd_s,
        ))

    return results


def check_B07_single_accession_per_quarter(
    source_detail_df: pd.DataFrame,
) -> list[CheckResult]:
    """B07: After amendment resolution, exactly one accession per (CIK, report_date, base_form)."""
    results = []
    if source_detail_df.empty:
        return [_make_result("B07", "global", "skip", 0, 0, "No source detail data")]

    df = source_detail_df.copy()
    df["_base_form"] = _col_str(df, "form_type").str.replace(r"/A$", "", regex=True)

    for (cik, rd), group in df.groupby(["cik", "report_date"], dropna=False):
        cik_s, rd_s = str(cik), str(rd)
        for base_form, form_group in group.groupby("_base_form", dropna=False):
            accessions = _col_str(form_group, "accession_number").unique()
            accessions = [a for a in accessions if a.strip()]
            n = len(accessions)
            status = "pass" if n <= 1 else "warn"
            results.append(_make_result(
                "B07", "cik_quarter", status, n, 1,
                f"{cik_s}/{rd_s}/{base_form}: {n} accession(s)",
                cik=cik_s, report_date=rd_s,
            ))

    return results


def check_B08_comparative_period_exclusion(
    source_detail_df: pd.DataFrame,
) -> list[CheckResult]:
    """B08: Rows where period != report_date should be excluded (not double-counted)."""
    results = []
    if source_detail_df.empty:
        return [_make_result("B08", "global", "skip", 0, 0, "No source detail data")]

    df = source_detail_df.copy()
    period = _col_str(df, "period")
    report_date = _col_str(df, "report_date")
    comparative = df[
        (period.str.strip() != "")
        & (report_date.str.strip() != "")
        & (period != report_date)
    ]

    # Check that comparative rows are marked as excluded
    if comparative.empty:
        return [_make_result("B08", "global", "pass", 0, 0,
                             "No comparative period rows found")]

    blocking = comparative[_col_str(comparative, "blocking_issue").str.lower().isin(["true", "1"])]
    status = "pass" if blocking.empty else "fail"

    return [_make_result(
        "B08", "global", status, len(blocking), 0,
        f"{len(comparative)} comparative rows; {len(blocking)} still blocking",
        detail=blocking,
    )]


# ===================================================================
# CATEGORY C: CONTENT INVARIANTS
# ===================================================================

def check_C01_debt_has_rate(
    holdings_df: pd.DataFrame,
    *,
    min_rate: float = 0.80,
) -> list[CheckResult]:
    """C01: >=80% of debt-classified rows should have interest_rate or basis_spread."""
    results = []
    if holdings_df.empty:
        return [_make_result("C01", "global", "skip", 0, min_rate, "No holdings data")]

    debt_mask = _col_str(holdings_df, "index_classification").str.lower().isin([
        "senior_secured_debt", "subordinated_debt", "debt",
        "senior secured debt", "subordinated debt",
    ]) | _col_str(holdings_df, "asset_category").str.lower().str.contains("debt|loan", regex=True, na=False)

    debt = holdings_df[debt_mask]
    if debt.empty:
        return [_make_result("C01", "global", "skip", 0, min_rate, "No debt rows found")]

    for (cik, rd), group in debt.groupby(["cik", "report_date"], dropna=False):
        cik_s, rd_s = str(cik), str(rd)
        has_rate = (
            _col_float(group, "interest_rate").ne(0)
            | _col_float(group, "basis_spread").ne(0)
        )
        rate = has_rate.sum() / max(len(group), 1)
        status = "pass" if rate >= min_rate else "fail"
        no_rate = group[~has_rate]
        results.append(_make_result(
            "C01", "cik_quarter", status, rate, min_rate,
            f"{cik_s}/{rd_s}: {rate:.1%} of {len(group)} debt rows have rate",
            detail=no_rate, cik=cik_s, report_date=rd_s,
        ))

    return results


def check_C04_equity_has_shares(
    holdings_df: pd.DataFrame,
    *,
    min_rate: float = 0.70,
) -> list[CheckResult]:
    """C04: >=70% of equity rows should have shares_held."""
    results = []
    if holdings_df.empty:
        return [_make_result("C04", "global", "skip", 0, min_rate, "No holdings data")]

    eq_mask = _col_str(holdings_df, "index_classification").str.lower().isin([
        "equity", "equity_other",
    ]) | _col_str(holdings_df, "asset_category").str.lower().str.contains("equity|stock", regex=True, na=False)

    equity = holdings_df[eq_mask]
    if equity.empty:
        return [_make_result("C04", "global", "skip", 0, min_rate, "No equity rows")]

    for (cik, rd), group in equity.groupby(["cik", "report_date"], dropna=False):
        cik_s, rd_s = str(cik), str(rd)
        has_shares = _col_float(group, "shares_held").ne(0)
        rate = has_shares.sum() / max(len(group), 1)
        status = "pass" if rate >= min_rate else "fail"
        results.append(_make_result(
            "C04", "cik_quarter", status, rate, min_rate,
            f"{cik_s}/{rd_s}: {rate:.1%} of {len(group)} equity rows have shares",
            cik=cik_s, report_date=rd_s,
        ))

    return results


def check_C05_no_rate_on_common_equity(
    holdings_df: pd.DataFrame,
    *,
    max_rate: float = 0.10,
) -> list[CheckResult]:
    """C05: <10% of common equity rows should have interest_rate (preferred may)."""
    results = []
    if holdings_df.empty:
        return [_make_result("C05", "global", "skip", 0, max_rate, "No holdings data")]

    common_mask = _col_str(holdings_df, "instrument_description").str.lower().str.contains(
        "common stock|common equity|common unit", regex=True, na=False
    )
    common = holdings_df[common_mask]
    if common.empty:
        return [_make_result("C05", "global", "skip", 0, max_rate, "No common equity rows")]

    has_rate = _col_float(common, "interest_rate").ne(0)
    rate = has_rate.sum() / max(len(common), 1)
    status = "pass" if rate <= max_rate else "fail"
    return [_make_result(
        "C05", "global", status, rate, max_rate,
        f"{rate:.1%} of {len(common)} common equity rows have interest_rate",
        detail=common[has_rate] if has_rate.any() else pd.DataFrame(),
    )]


def check_C08_fv_required(
    holdings_df: pd.DataFrame,
    *,
    min_rate: float = 0.95,
) -> list[CheckResult]:
    """C08: >=95% of classified rows should have non-null fair_value."""
    results = []
    if holdings_df.empty:
        return [_make_result("C08", "global", "skip", 0, min_rate, "No holdings data")]

    classified = holdings_df[
        _col_str(holdings_df, "index_classification").str.strip().ne("")
    ]
    if classified.empty:
        return [_make_result("C08", "global", "skip", 0, min_rate, "No classified rows")]

    has_fv = _col_float(classified, "fair_value").ne(0)
    # Also accept rows where fair_value string is present but equals 0
    fv_present = (
        has_fv | _col_str(classified, "fair_value").str.strip().ne("")
    )
    rate = fv_present.sum() / max(len(classified), 1)
    status = "pass" if rate >= min_rate else "fail"
    return [_make_result(
        "C08", "global", status, rate, min_rate,
        f"{rate:.1%} of {len(classified)} classified rows have fair_value",
    )]


# ===================================================================
# CATEGORY D: CROSS-QUARTER STABILITY
# ===================================================================

def check_D01_position_count_band(
    holdings_df: pd.DataFrame,
    *,
    min_ratio: float = 0.4,
    max_ratio: float = 2.5,
) -> list[CheckResult]:
    """D01: QoQ position count ratio within [0.4, 2.5]."""
    results = []
    if holdings_df.empty:
        return [_make_result("D01", "global", "skip", 0, max_ratio, "No holdings data")]

    counts = (
        holdings_df.groupby(["cik", "report_date"], dropna=False)
        .size()
        .reset_index(name="count")
        .sort_values(["cik", "report_date"])
    )

    for cik, group in counts.groupby("cik", dropna=False):
        cik_s = str(cik)
        group = group.sort_values("report_date").reset_index(drop=True)
        if len(group) < 2:
            continue

        for i in range(1, len(group)):
            prev_count = group.iloc[i - 1]["count"]
            curr_count = group.iloc[i]["count"]
            rd = str(group.iloc[i]["report_date"])

            if prev_count == 0:
                continue

            ratio = curr_count / prev_count
            status = "pass" if min_ratio <= ratio <= max_ratio else "fail"
            results.append(_make_result(
                "D01", "cik_quarter", status, ratio, max_ratio,
                f"{cik_s}/{rd}: count ratio {ratio:.2f} "
                f"({prev_count} -> {curr_count})",
                cik=cik_s, report_date=rd,
            ))

    if not results:
        results.append(_make_result("D01", "global", "skip", 0, max_ratio,
                                    "Insufficient multi-quarter data"))
    return results


def check_D02_fv_stability(
    holdings_df: pd.DataFrame,
    *,
    min_ratio: float = 0.3,
    max_ratio: float = 3.0,
) -> list[CheckResult]:
    """D02: QoQ total FV ratio within [0.3, 3.0]."""
    results = []
    if holdings_df.empty:
        return [_make_result("D02", "global", "skip", 0, max_ratio, "No holdings data")]

    fv_sums = (
        holdings_df.assign(fv=_col_float(holdings_df, "fair_value"))
        .groupby(["cik", "report_date"], dropna=False)["fv"]
        .sum()
        .reset_index(name="total_fv")
        .sort_values(["cik", "report_date"])
    )

    for cik, group in fv_sums.groupby("cik", dropna=False):
        cik_s = str(cik)
        group = group.sort_values("report_date").reset_index(drop=True)
        if len(group) < 2:
            continue

        for i in range(1, len(group)):
            prev_fv = group.iloc[i - 1]["total_fv"]
            curr_fv = group.iloc[i]["total_fv"]
            rd = str(group.iloc[i]["report_date"])

            if prev_fv == 0:
                continue

            ratio = curr_fv / prev_fv
            status = "pass" if min_ratio <= ratio <= max_ratio else "fail"
            results.append(_make_result(
                "D02", "cik_quarter", status, ratio, max_ratio,
                f"{cik_s}/{rd}: FV ratio {ratio:.2f} "
                f"({prev_fv:,.0f} -> {curr_fv:,.0f})",
                cik=cik_s, report_date=rd,
            ))

    if not results:
        results.append(_make_result("D02", "global", "skip", 0, max_ratio,
                                    "Insufficient multi-quarter data"))
    return results


def check_D03_count_fv_divergence(
    holdings_df: pd.DataFrame,
    *,
    count_spike_ratio: float = 2.0,
    fv_stable_range: tuple[float, float] = (0.7, 1.3),
) -> list[CheckResult]:
    """D03: Flag quarters where count doubles but FV is stable (subtotal leak signal)."""
    results = []
    if holdings_df.empty:
        return [_make_result("D03", "global", "skip", 0, 0, "No holdings data")]

    stats = (
        holdings_df.assign(fv=_col_float(holdings_df, "fair_value"))
        .groupby(["cik", "report_date"], dropna=False)
        .agg(count=("fv", "size"), total_fv=("fv", "sum"))
        .reset_index()
        .sort_values(["cik", "report_date"])
    )

    for cik, group in stats.groupby("cik", dropna=False):
        cik_s = str(cik)
        group = group.sort_values("report_date").reset_index(drop=True)
        if len(group) < 2:
            continue

        for i in range(1, len(group)):
            prev = group.iloc[i - 1]
            curr = group.iloc[i]
            rd = str(curr["report_date"])

            if prev["count"] == 0 or prev["total_fv"] == 0:
                continue

            count_ratio = curr["count"] / prev["count"]
            fv_ratio = curr["total_fv"] / prev["total_fv"]

            if count_ratio > count_spike_ratio and fv_stable_range[0] <= fv_ratio <= fv_stable_range[1]:
                results.append(_make_result(
                    "D03", "cik_quarter", "fail", count_ratio, count_spike_ratio,
                    f"{cik_s}/{rd}: count_ratio={count_ratio:.2f} but "
                    f"fv_ratio={fv_ratio:.2f} -- possible subtotal leak",
                    cik=cik_s, report_date=rd,
                ))

    if not results:
        results.append(_make_result("D03", "global", "pass", 0, 0,
                                    "No count-FV divergence detected"))
    return results


def check_D06_position_continuity(
    holdings_df: pd.DataFrame,
    *,
    min_continuity: float = 0.50,
) -> list[CheckResult]:
    """D06: >=50% of positions in Q-1 still present in Q (by issuer_name)."""
    results = []
    if holdings_df.empty or "issuer_name" not in holdings_df.columns:
        return [_make_result("D06", "global", "skip", 0, min_continuity, "No holdings data")]

    for cik, cik_group in holdings_df.groupby("cik", dropna=False):
        cik_s = str(cik)
        quarters = sorted(cik_group["report_date"].dropna().unique())
        if len(quarters) < 2:
            continue

        for i in range(1, len(quarters)):
            prev_q = quarters[i - 1]
            curr_q = quarters[i]
            prev_names = set(
                _col_str(cik_group[cik_group["report_date"] == prev_q], "issuer_name")
                .str.lower().str.strip()
            ) - {""}
            curr_names = set(
                _col_str(cik_group[cik_group["report_date"] == curr_q], "issuer_name")
                .str.lower().str.strip()
            ) - {""}

            if not prev_names:
                continue

            overlap = prev_names & curr_names
            continuity = len(overlap) / len(prev_names)
            status = "pass" if continuity >= min_continuity else "fail"
            results.append(_make_result(
                "D06", "cik_quarter", status, continuity, min_continuity,
                f"{cik_s}/{curr_q}: {continuity:.1%} continuity "
                f"({len(overlap)}/{len(prev_names)} issuers persist)",
                cik=cik_s, report_date=str(curr_q),
            ))

    if not results:
        results.append(_make_result("D06", "global", "skip", 0, min_continuity,
                                    "Insufficient multi-quarter data"))
    return results


def check_D07_rate_distribution_stability(
    holdings_df: pd.DataFrame,
    *,
    max_shift_bps: float = 300,
) -> list[CheckResult]:
    """D07: Median interest_rate doesn't shift >300bps between quarters."""
    results = []
    if holdings_df.empty or "interest_rate" not in holdings_df.columns:
        return [_make_result("D07", "global", "skip", 0, max_shift_bps, "No holdings data")]

    for cik, cik_group in holdings_df.groupby("cik", dropna=False):
        cik_s = str(cik)
        quarters = sorted(cik_group["report_date"].dropna().unique())
        if len(quarters) < 2:
            continue

        prev_median = None
        for q in quarters:
            rates = _col_float(cik_group[cik_group["report_date"] == q], "interest_rate")
            rates = rates[rates.ne(0)]
            if rates.empty:
                prev_median = None
                continue

            median = rates.median()
            # Normalize: if median > 1, assume it's in percentage form, convert to decimal
            if median > 1:
                median = median / 100

            if prev_median is not None:
                shift_bps = abs(median - prev_median) * 10000
                status = "pass" if shift_bps <= max_shift_bps else "fail"
                results.append(_make_result(
                    "D07", "cik_quarter", status, shift_bps, max_shift_bps,
                    f"{cik_s}/{q}: median rate shift {shift_bps:.0f} bps",
                    cik=cik_s, report_date=str(q),
                ))
            prev_median = median

    if not results:
        results.append(_make_result("D07", "global", "skip", 0, max_shift_bps,
                                    "Insufficient rate data"))
    return results


# ===================================================================
# CATEGORY E: CROSS-REFERENCE CHECKS
# ===================================================================

def check_E01_holdings_fv_vs_investments(
    holdings_df: pd.DataFrame,
    fund_financials_df: pd.DataFrame | None = None,
    *,
    tolerance: float = 0.05,
) -> list[CheckResult]:
    """E01: Primary GAV recon -- holdings FV vs investments_at_fair_value within 5%."""
    a04_results = check_A04_gav_reconciliation(
        holdings_df, fund_financials_df,
        bdc_tolerance=tolerance, nport_tolerance=tolerance * 2,
    )
    # Re-tag with E01 check_id
    for r in a04_results:
        r.check_id = "E01"
    return a04_results


def check_E02_holdings_fv_vs_total_assets(
    holdings_df: pd.DataFrame,
    fund_financials_df: pd.DataFrame | None = None,
) -> list[CheckResult]:
    """E02: BDC fallback -- holdings FV should be < total_assets."""
    results = []
    if holdings_df.empty:
        return [_make_result("E02", "global", "skip", 0, 0, "No holdings data")]
    if fund_financials_df is None or fund_financials_df.empty:
        return [_make_result("E02", "global", "skip", 0, 0, "No fund financials")]

    for (cik, rd), group in holdings_df.groupby(["cik", "report_date"], dropna=False):
        cik_s, rd_s = str(cik), str(rd)
        holdings_fv = _col_float(group, "fair_value").sum()

        ff_match = fund_financials_df[
            (_col_str(fund_financials_df, "cik").str.zfill(10) == cik_s.zfill(10))
            & (_col_str(fund_financials_df, "report_date") == rd_s)
        ]
        if ff_match.empty:
            continue

        total_assets = _safe_float(ff_match.iloc[0].get("total_assets", 0))
        if total_assets <= 0:
            continue

        status = "pass" if holdings_fv <= total_assets * 1.05 else "fail"
        ratio = holdings_fv / total_assets if total_assets > 0 else 0
        results.append(_make_result(
            "E02", "cik_quarter", status, ratio, 1.05,
            f"{cik_s}/{rd_s}: holdings_fv/total_assets = {ratio:.2f}",
            cik=cik_s, report_date=rd_s,
        ))

    if not results:
        results.append(_make_result("E02", "global", "skip", 0, 0,
                                    "No comparable data"))
    return results


def check_E04_nav_per_share_sanity(
    fund_financials_df: pd.DataFrame | None = None,
    *,
    tolerance: float = 0.05,
) -> list[CheckResult]:
    """E04: nav_per_share * shares_outstanding ~ net_assets within 5%."""
    results = []
    if fund_financials_df is None or fund_financials_df.empty:
        return [_make_result("E04", "global", "skip", 0, tolerance, "No fund financials")]

    ff = fund_financials_df.copy()
    for col in ("nav_per_share", "shares_outstanding", "net_assets"):
        if col not in ff.columns:
            return [_make_result("E04", "global", "skip", 0, tolerance,
                                 f"Missing column: {col}")]

    for _, row in ff.iterrows():
        nav_ps = _safe_float(row.get("nav_per_share", 0))
        shares = _safe_float(row.get("shares_outstanding", 0))
        net_assets = _safe_float(row.get("net_assets", 0))
        cik_s = str(row.get("cik", "")).zfill(10)
        rd_s = str(row.get("report_date", ""))

        if nav_ps == 0 or shares == 0 or net_assets == 0:
            continue

        computed = nav_ps * shares
        diff = _pct_diff(computed, net_assets)
        status = "pass" if diff <= tolerance else "fail"
        results.append(_make_result(
            "E04", "cik_quarter", status, diff, tolerance,
            f"{cik_s}/{rd_s}: nav*shares={computed:,.0f} vs net_assets={net_assets:,.0f} ({diff:.1%})",
            cik=cik_s, report_date=rd_s,
        ))

    if not results:
        results.append(_make_result("E04", "global", "skip", 0, tolerance,
                                    "No NAV/share data"))
    return results


def check_E07_position_count_vs_filing(
    source_detail_df: pd.DataFrame,
    holdings_df: pd.DataFrame,
    *,
    tolerance: float = 0.10,
) -> list[CheckResult]:
    """E07: Source leaf count vs output leaf count discrepancy < 10%."""
    results = []
    if source_detail_df.empty or holdings_df.empty:
        return [_make_result("E07", "global", "skip", 0, tolerance, "Missing data")]

    source_leaves = source_detail_df[
        _col_str(source_detail_df, "source_wrapper_disposition").str.endswith("_position_leaf")
    ]
    if source_leaves.empty:
        return [_make_result("E07", "global", "skip", 0, tolerance, "No source leaves")]

    source_counts = source_leaves.groupby(
        ["cik", "report_date"], dropna=False
    ).size().reset_index(name="source_count")

    output_counts = holdings_df.groupby(
        ["cik", "report_date"], dropna=False
    ).size().reset_index(name="output_count")

    merged = source_counts.merge(output_counts, on=["cik", "report_date"], how="outer").fillna(0)

    for _, row in merged.iterrows():
        cik_s = str(row["cik"])
        rd_s = str(row["report_date"])
        src = int(row["source_count"])
        out = int(row["output_count"])

        if src == 0:
            continue

        diff = abs(src - out) / src
        status = "pass" if diff <= tolerance else "fail"
        results.append(_make_result(
            "E07", "cik_quarter", status, diff, tolerance,
            f"{cik_s}/{rd_s}: source={src} vs output={out} ({diff:.1%} diff)",
            cik=cik_s, report_date=rd_s,
        ))

    if not results:
        results.append(_make_result("E07", "global", "skip", 0, tolerance,
                                    "No comparable data"))
    return results


# ===================================================================
# CATEGORY F: DATA QUALITY
# ===================================================================

def check_F01_interest_rate_range(
    holdings_df: pd.DataFrame,
    *,
    max_rate: float = 0.30,
    flag_rate: float = 0.25,
) -> list[CheckResult]:
    """F01: All interest rates in [0, 30%]. Flag >25% as possible scale error."""
    results = []
    if holdings_df.empty or "interest_rate" not in holdings_df.columns:
        return [_make_result("F01", "global", "skip", 0, max_rate, "No rate data")]

    rates = _col_float(holdings_df, "interest_rate")
    nonzero = rates[rates.ne(0)]

    if nonzero.empty:
        return [_make_result("F01", "global", "skip", 0, max_rate, "No nonzero rates")]

    # Normalize: if median > 1, assume percentage form (e.g. 8.5 = 8.5%)
    median_rate = nonzero.median()
    if median_rate > 1:
        nonzero = nonzero / 100
        max_rate_check = max_rate
        flag_rate_check = flag_rate
    else:
        max_rate_check = max_rate
        flag_rate_check = flag_rate

    out_of_range = nonzero[(nonzero < 0) | (nonzero > max_rate_check)]
    flagged = nonzero[nonzero > flag_rate_check]

    status = "pass" if out_of_range.empty else "fail"
    if status == "pass" and not flagged.empty:
        status = "warn"

    return [_make_result(
        "F01", "global", status, len(out_of_range), 0,
        f"{len(out_of_range)} rates out of [0, {max_rate:.0%}]; "
        f"{len(flagged)} flagged > {flag_rate:.0%}",
    )]


def check_F03_fair_value_sign(
    holdings_df: pd.DataFrame,
    *,
    min_positive_rate: float = 0.99,
) -> list[CheckResult]:
    """F03: >=99% of FV values should be positive."""
    results = []
    if holdings_df.empty:
        return [_make_result("F03", "global", "skip", 0, min_positive_rate, "No holdings data")]

    fv = _col_float(holdings_df, "fair_value")
    nonzero = fv[fv.ne(0)]
    if nonzero.empty:
        return [_make_result("F03", "global", "skip", 0, min_positive_rate, "No nonzero FV")]

    positive_rate = (nonzero > 0).sum() / len(nonzero)
    negative = holdings_df[fv < 0]
    status = "pass" if positive_rate >= min_positive_rate else "fail"
    return [_make_result(
        "F03", "global", status, positive_rate, min_positive_rate,
        f"{positive_rate:.1%} positive FV ({len(negative)} negative rows)",
        detail=negative,
    )]


def check_F04_pct_of_net_assets_range(
    holdings_df: pd.DataFrame,
    *,
    min_pct: float = 0.001,
    max_pct: float = 25.0,
) -> list[CheckResult]:
    """F04: Individual pct_of_net_assets in [0.001%, 25%]. Outliers flagged."""
    results = []
    if holdings_df.empty or "pct_of_net_assets" not in holdings_df.columns:
        return [_make_result("F04", "global", "skip", 0, max_pct, "No pct data")]

    pcts = _col_float(holdings_df, "pct_of_net_assets")
    nonzero = pcts[pcts.ne(0)]
    if nonzero.empty:
        return [_make_result("F04", "global", "skip", 0, max_pct, "No nonzero pct values")]

    outliers = nonzero[(nonzero.abs() < min_pct) | (nonzero.abs() > max_pct)]
    status = "pass" if outliers.empty else "warn"
    return [_make_result(
        "F04", "global", status, len(outliers), 0,
        f"{len(outliers)} pct_of_net_assets outliers outside [{min_pct}%, {max_pct}%]",
    )]


def check_F07_null_fair_value(
    holdings_df: pd.DataFrame,
    *,
    max_null_rate: float = 0.02,
) -> list[CheckResult]:
    """F07: <2% of rows have null fair_value."""
    results = []
    if holdings_df.empty:
        return [_make_result("F07", "global", "skip", 0, max_null_rate, "No holdings data")]

    fv_str = _col_str(holdings_df, "fair_value")
    null_mask = fv_str.str.strip().eq("") | holdings_df["fair_value"].isna() if "fair_value" in holdings_df.columns else pd.Series(True, index=holdings_df.index)
    null_rate = null_mask.sum() / max(len(holdings_df), 1)
    status = "pass" if null_rate <= max_null_rate else "fail"
    return [_make_result(
        "F07", "global", status, null_rate, max_null_rate,
        f"{null_rate:.2%} null fair_value ({null_mask.sum()}/{len(holdings_df)})",
    )]


def check_F08_duplicate_detection(
    holdings_df: pd.DataFrame,
) -> list[CheckResult]:
    """F08: No two rows with same (CIK, report_date, issuer_name, instrument_description, fair_value)."""
    results = []
    if holdings_df.empty:
        return [_make_result("F08", "global", "skip", 0, 0, "No holdings data")]

    key_cols = ["cik", "report_date", "issuer_name", "instrument_description", "fair_value"]
    available = [c for c in key_cols if c in holdings_df.columns]
    if len(available) < 3:
        return [_make_result("F08", "global", "skip", 0, 0,
                             "Insufficient columns for dupe detection")]

    dupes = holdings_df[holdings_df.duplicated(subset=available, keep=False)]
    status = "pass" if dupes.empty else "warn"
    return [_make_result(
        "F08", "global", status, len(dupes), 0,
        f"{len(dupes)} potential duplicate rows",
        detail=dupes.head(100),
    )]


def check_F09_text_corruption(
    holdings_df: pd.DataFrame,
) -> list[CheckResult]:
    """F09: Flag identifiers with repeated words, control chars, or garbled text."""
    results = []
    if holdings_df.empty:
        return [_make_result("F09", "global", "skip", 0, 0, "No holdings data")]

    # Check issuer_name and instrument_description for corruption
    corrupt_rows = []
    for col in ("issuer_name", "instrument_description", "bdc_investment_identifier"):
        if col not in holdings_df.columns:
            continue
        vals = _col_str(holdings_df, col)
        # Repeated consecutive word pattern (e.g., "Investment Debt InveInvestment")
        _repeat_re = re.compile(r"(\b\w{4,})\1")
        repeated = vals.apply(lambda x: bool(_repeat_re.search(x)) if x else False)
        # Control characters
        control = vals.str.contains(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", regex=True, na=False)
        corrupt = holdings_df[repeated | control]
        if not corrupt.empty:
            corrupt_rows.append(corrupt)

    if not corrupt_rows:
        return [_make_result("F09", "global", "pass", 0, 0,
                             "No text corruption detected")]

    combined = pd.concat(corrupt_rows).drop_duplicates()
    return [_make_result(
        "F09", "global", "warn", len(combined), 0,
        f"{len(combined)} rows with potential text corruption",
        detail=combined.head(50),
    )]


def check_F11_shares_sign(
    holdings_df: pd.DataFrame,
) -> list[CheckResult]:
    """F11: shares_held should be positive where present."""
    results = []
    if holdings_df.empty or "shares_held" not in holdings_df.columns:
        return [_make_result("F11", "global", "skip", 0, 0, "No shares data")]

    shares = _col_float(holdings_df, "shares_held")
    nonzero = shares[shares.ne(0)]
    negative = nonzero[nonzero < 0]
    status = "pass" if negative.empty else "warn"
    return [_make_result(
        "F11", "global", status, len(negative), 0,
        f"{len(negative)} negative shares_held values",
        detail=holdings_df.loc[negative.index].head(50) if not negative.empty else pd.DataFrame(),
    )]


def check_F12_rate_scale_detection(
    holdings_df: pd.DataFrame,
    *,
    whole_number_threshold: float = 1.0,
) -> list[CheckResult]:
    """F12: Detect rates reported as whole numbers (e.g., 850 vs 8.5%)."""
    results = []
    if holdings_df.empty or "interest_rate" not in holdings_df.columns:
        return [_make_result("F12", "global", "skip", 0, 0, "No rate data")]

    rates = _col_float(holdings_df, "interest_rate")
    nonzero = rates[rates.ne(0)]
    if nonzero.empty:
        return [_make_result("F12", "global", "skip", 0, 0, "No nonzero rates")]

    # If median is > 1, rates are likely in percentage form (normal for this pipeline)
    # If median is > 100, rates are likely in bps form or garbled
    median = nonzero.median()
    extreme = nonzero[nonzero.abs() > 100]  # >10000% or bps

    if not extreme.empty:
        return [_make_result(
            "F12", "global", "warn", len(extreme), 0,
            f"{len(extreme)} rates > 100 (possible bps scale: median={median:.1f})",
            detail=holdings_df.loc[extreme.index].head(50),
        )]

    return [_make_result("F12", "global", "pass", 0, 0,
                         f"Rate scale appears consistent (median={median:.2f})")]


# ===================================================================
# CATEGORY G: AGGREGATE LEAK DETECTION
# ===================================================================

_AGGREGATE_KEYWORDS = [
    "non-control", "affiliate investments", "control investments",
    "total investments", "net assets", "subtotal", "sub-total",
    "total cash", "cash and cash equivalents", "total fair value",
    "total cost", "unfunded commitments", "total unfunded",
    "weighted average", "liabilities in excess",
    "investment debt investments", "investment equity securities",
    "investment unsecured", "placeholder",
    "grand total", "total senior", "total junior",
    "total subordinated", "total first lien", "total second lien",
    "total equity", "total mezzanine", "total portfolio",
    "industry total", "sector total", "geography total",
    "portfolio investments", "investment in securities",
    "control and affiliate investments", "non-affiliated",
    "non-controlled", "affiliated investments",
    "senior secured loans total", "subordinated debt total",
    "equity investments total", "total fair value of investments",
    "grand total investments", "total investments at fair value",
    "total investments at cost", "total portfolio investments",
    "aggregate", "total warrant", "warrant investments total",
    "total fund investments", "total structured finance",
    "total collateralized", "total net assets",
    "portfolio total", "total interest bearing",
    "total floating rate", "total fixed rate",
    "total variable rate", "total income producing",
    "total non-income producing", "total non-accrual",
    "total restructured", "total workout",
    "summary of investments", "investment summary",
    "total by industry", "total by geography",
    "total by sector", "total by asset class",
    "total by investment type", "total by strategy",
    "domestic total", "international total",
    "north america total", "europe total", "asia total",
    "total healthcare", "total technology", "total consumer",
    "total energy", "total financial", "total industrial",
    "total materials", "total communications",
    "total real estate", "total utilities",
    "total education", "total media",
    "total transportation", "total services",
    "total manufacturing", "total government",
]


def check_G01_keyword_aggregate_detection(
    holdings_df: pd.DataFrame,
) -> list[CheckResult]:
    """G01: Extended keyword scan -- zero leaked aggregates in final output."""
    results = []
    if holdings_df.empty:
        return [_make_result("G01", "global", "skip", 0, 0, "No holdings data")]

    # Build combined text for scanning
    text_cols = []
    for col in ("issuer_name", "bdc_investment_identifier", "instrument_description"):
        if col in holdings_df.columns:
            text_cols.append(col)

    if not text_cols:
        return [_make_result("G01", "global", "skip", 0, 0, "No text columns")]

    combined_lower = pd.Series("", index=holdings_df.index)
    for col in text_cols:
        combined_lower = combined_lower + " " + _col_str(holdings_df, col).str.lower()

    matches = pd.Series(False, index=holdings_df.index)
    matched_keywords = pd.Series("", index=holdings_df.index)
    for kw in _AGGREGATE_KEYWORDS:
        kw_match = combined_lower.str.contains(kw, na=False, regex=False)
        new_matches = kw_match & ~matches
        matched_keywords = matched_keywords.where(~new_matches, kw)
        matches = matches | kw_match

    leaked = holdings_df[matches]
    status = "pass" if leaked.empty else "warn"
    return [_make_result(
        "G01", "global", status, len(leaked), 0,
        f"{len(leaked)} rows match aggregate keywords",
        detail=leaked.head(100),
    )]


def check_G02_arithmetic_subtotal_detection(
    holdings_df: pd.DataFrame,
    *,
    max_window: int = 20,
    tolerance_pct: float = 0.001,
) -> list[CheckResult]:
    """G02: No row whose FV equals sum of next N rows within 0.1%."""
    results = []
    if holdings_df.empty:
        return [_make_result("G02", "global", "skip", 0, 0, "No holdings data")]

    subtotal_rows = []
    for (cik, rd), group in holdings_df.groupby(["cik", "report_date"], dropna=False):
        fvs = _col_float(group, "fair_value").values
        if len(fvs) < 3:
            continue

        for i in range(len(fvs)):
            if fvs[i] == 0:
                continue
            running_sum = 0.0
            for n in range(1, min(max_window + 1, len(fvs) - i)):
                running_sum += fvs[i + n]
                if running_sum == 0:
                    continue
                if _pct_diff(running_sum, fvs[i]) <= tolerance_pct:
                    subtotal_rows.append({
                        "cik": str(cik),
                        "report_date": str(rd),
                        "row_index": i,
                        "fv": fvs[i],
                        "sum_next_n": running_sum,
                        "n": n,
                    })
                    break

    detail = pd.DataFrame(subtotal_rows)
    status = "pass" if detail.empty else "warn"
    return [_make_result(
        "G02", "global", status, len(detail), 0,
        f"{len(detail)} suspected arithmetic subtotals",
        detail=detail,
    )]


def check_G03_header_row_detection(
    holdings_df: pd.DataFrame,
) -> list[CheckResult]:
    """G03: Rows with identifier but no fair_value, no cost -- pure headers."""
    results = []
    if holdings_df.empty:
        return [_make_result("G03", "global", "skip", 0, 0, "No holdings data")]

    has_name = _col_str(holdings_df, "issuer_name").str.strip().ne("")
    no_fv = _col_float(holdings_df, "fair_value").eq(0) & (
        _col_str(holdings_df, "fair_value").str.strip().eq("")
        | holdings_df.get("fair_value", pd.Series(dtype=str)).isna()
    ) if "fair_value" in holdings_df.columns else pd.Series(True, index=holdings_df.index)
    no_cost = _col_float(holdings_df, "cost").eq(0) if "cost" in holdings_df.columns else pd.Series(True, index=holdings_df.index)

    headers = holdings_df[has_name & no_fv & no_cost]
    status = "pass" if headers.empty else "warn"
    return [_make_result(
        "G03", "global", status, len(headers), 0,
        f"{len(headers)} suspected header rows (name but no FV/cost)",
        detail=headers.head(50),
    )]


# ===================================================================
# CATEGORY H: SOURCE COMPLETENESS
# ===================================================================

def check_H01_source_fact_coverage(
    source_detail_df: pd.DataFrame,
    holdings_df: pd.DataFrame,
    *,
    min_coverage: float = 0.90,
) -> list[CheckResult]:
    """H01: >=90% of XBRL contexts with FV appear in holdings."""
    results = []
    if source_detail_df.empty or holdings_df.empty:
        return [_make_result("H01", "global", "skip", 0, min_coverage, "Missing data")]

    source_with_fv = source_detail_df[
        _col_float(source_detail_df, "source_fair_value").ne(0)
        & _col_str(source_detail_df, "source_wrapper_disposition").str.endswith("_position_leaf")
    ]

    if source_with_fv.empty:
        return [_make_result("H01", "global", "skip", 0, min_coverage,
                             "No source leaf rows with FV")]

    matched = source_with_fv[
        _col_str(source_with_fv, "output_row_id").str.strip().ne("")
        | _col_str(source_with_fv, "status").isin(["matched", "value_mismatch"])
    ]

    coverage = len(matched) / max(len(source_with_fv), 1)
    status = "pass" if coverage >= min_coverage else "fail"
    return [_make_result(
        "H01", "global", status, coverage, min_coverage,
        f"{coverage:.1%} source leaf coverage ({len(matched)}/{len(source_with_fv)})",
    )]


def check_H03_amendment_supersession(
    source_detail_df: pd.DataFrame,
) -> list[CheckResult]:
    """H03: /A filings supersede originals; no accession duplication."""
    results = []
    if source_detail_df.empty:
        return [_make_result("H03", "global", "skip", 0, 0, "No source detail data")]

    df = source_detail_df.copy()
    form_type = _col_str(df, "form_type")
    amendments = df[form_type.str.endswith("/A")]

    if amendments.empty:
        return [_make_result("H03", "global", "pass", 0, 0,
                             "No amendments found")]

    # Check that amendment rows don't co-exist with original rows in blocking state
    original_accessions = set()
    amendment_accessions = set()
    for _, row in amendments.iterrows():
        amendment_accessions.add(str(row.get("accession_number", "")))

    non_amendments = df[~form_type.str.endswith("/A")]
    for _, row in non_amendments.iterrows():
        original_accessions.add(str(row.get("accession_number", "")))

    # Find CIK-quarters with both amendment and original blocking rows
    blocking = df[_col_str(df, "blocking_issue").str.lower().isin(["true", "1"])]
    if blocking.empty:
        return [_make_result("H03", "global", "pass", 0, 0,
                             "No blocking rows from amendments")]

    both_types = blocking.groupby(["cik", "report_date"], dropna=False).apply(
        lambda g: g["form_type"].str.endswith("/A").any() and (~g["form_type"].str.endswith("/A")).any()
    )
    problematic = both_types[both_types].index.tolist() if not both_types.empty else []

    status = "pass" if not problematic else "warn"
    return [_make_result(
        "H03", "global", status, len(problematic), 0,
        f"{len(problematic)} CIK-quarters with mixed amendment/original blocking rows",
    )]


def check_H05_bdc_source_vs_unified_gap(
    source_detail_df: pd.DataFrame,
) -> list[CheckResult]:
    """H05: Rows in source but missing from unified are accounted for."""
    results = []
    if source_detail_df.empty:
        return [_make_result("H05", "global", "skip", 0, 0, "No source detail data")]

    source_only = source_detail_df[
        _col_str(source_detail_df, "status").eq("missing_from_pipeline")
    ]
    if source_only.empty:
        return [_make_result("H05", "global", "pass", 0, 0,
                             "No source-only rows")]

    blocking = source_only[
        _col_str(source_only, "blocking_issue").str.lower().isin(["true", "1"])
    ]
    documented = source_only[
        ~_col_str(source_only, "blocking_issue").str.lower().isin(["true", "1"])
    ]

    total = len(source_only)
    accounted = len(documented)
    rate = accounted / max(total, 1)

    status = "pass" if blocking.empty else ("warn" if len(blocking) < total * 0.1 else "fail")
    return [_make_result(
        "H05", "global", status, rate, 0.90,
        f"{accounted}/{total} source-only rows documented; {len(blocking)} still blocking",
        detail=blocking.head(50),
    )]


# ===================================================================
# CATEGORY I: WRAPPER-SPECIFIC CHECKS
# ===================================================================

def check_I02_leaf_marker_accuracy(
    source_detail_df: pd.DataFrame,
) -> list[CheckResult]:
    """I02: Rows marked position_leaf should have FV and look like positions."""
    results = []
    if source_detail_df.empty:
        return [_make_result("I02", "global", "skip", 0, 0, "No source detail data")]

    leaves = source_detail_df[
        _col_str(source_detail_df, "source_wrapper_disposition").str.endswith("_position_leaf")
    ]
    if leaves.empty:
        return [_make_result("I02", "global", "skip", 0, 0, "No leaf rows")]

    has_fv = _col_float(leaves, "source_fair_value").ne(0)
    accuracy = has_fv.sum() / max(len(leaves), 1)
    status = "pass" if accuracy >= 0.95 else "fail"
    return [_make_result(
        "I02", "global", status, accuracy, 0.95,
        f"{accuracy:.1%} of leaf-marked rows have FV ({has_fv.sum()}/{len(leaves)})",
        detail=leaves[~has_fv].head(50),
    )]


def check_I05_wrapper_content_signature_agreement(
    source_detail_df: pd.DataFrame,
    *,
    min_agreement: float = 0.85,
) -> list[CheckResult]:
    """I05: Wrapper disposition family agrees with content signature archetype in >=85% of rows."""
    results = []
    if source_detail_df.empty:
        return [_make_result("I05", "global", "skip", 0, min_agreement, "No source detail data")]

    leaves = source_detail_df[
        _col_str(source_detail_df, "source_wrapper_disposition").str.endswith("_position_leaf")
    ]
    if leaves.empty:
        return [_make_result("I05", "global", "skip", 0, min_agreement, "No leaf rows")]

    family = _col_str(leaves, "source_wrapper_family")
    sig_status = _col_str(leaves, "source_wrapper_signature_status")

    if (family.str.strip() == "").all():
        return [_make_result("I05", "global", "skip", 0, min_agreement,
                             "No family data")]

    pass_rate = (sig_status == "pass").sum() / max(len(leaves), 1)
    status = "pass" if pass_rate >= min_agreement else "fail"
    return [_make_result(
        "I05", "global", status, pass_rate, min_agreement,
        f"{pass_rate:.1%} wrapper-content signature agreement",
    )]


def check_I06_non_private_market_exclusion(
    source_detail_df: pd.DataFrame,
) -> list[CheckResult]:
    """I06: Rows classified as non_private_market match expected patterns."""
    results = []
    if source_detail_df.empty:
        return [_make_result("I06", "global", "skip", 0, 0, "No source detail data")]

    npm = source_detail_df[
        _col_str(source_detail_df, "source_wrapper_disposition").eq("non_private_market")
    ]
    if npm.empty:
        return [_make_result("I06", "global", "pass", 0, 0,
                             "No non_private_market rows")]

    # Check that these rows actually match non-private patterns
    _NPM_KEYWORDS = ["cash", "money market", "treasury", "government",
                      "repurchase agreement", "reverse repo"]
    identifiers = _col_str(npm, "raw_investment_identifier").str.lower()
    matched = identifiers.apply(
        lambda x: any(kw in x for kw in _NPM_KEYWORDS)
    )
    accuracy = matched.sum() / max(len(npm), 1)
    status = "pass" if accuracy >= 0.80 else "warn"
    return [_make_result(
        "I06", "global", status, accuracy, 0.80,
        f"{accuracy:.1%} of non_private_market rows match expected patterns "
        f"({matched.sum()}/{len(npm)})",
    )]


# ===================================================================
# CATEGORY J: Position Matching Quality
# ===================================================================


def check_J04_unique_position_id_per_report_date(
    holdings_df: pd.DataFrame,
) -> list[CheckResult]:
    """J04: A position_id must appear at most once per CIK/source/report date."""
    if holdings_df is None or holdings_df.empty:
        return [_make_result("J04", "global", "skip", 0, 0,
                             "No holdings data available")]

    required = {"cik", "report_date", "position_id"}
    if not required.issubset(holdings_df.columns):
        return [_make_result("J04", "global", "skip", 0, 0,
                             "Missing cik/report_date/position_id columns")]

    df = holdings_df.copy()
    if "source" not in df.columns:
        df["source"] = ""

    pid = _col_str(df, "position_id")
    df = df[pid.str.strip().ne("")]
    if df.empty:
        return [_make_result("J04", "global", "skip", 0, 0,
                             "No populated position_id values")]

    dupes = (
        df.groupby(["cik", "source", "report_date", "position_id"], dropna=False)
        .size()
        .reset_index(name="row_count")
    )
    dupes = dupes[dupes["row_count"] > 1]
    status = "pass" if dupes.empty else "fail"
    detail = dupes.sort_values(
        ["row_count", "cik", "source", "report_date", "position_id"],
        ascending=[False, True, True, True, True],
    ).head(100) if status == "fail" else pd.DataFrame()

    return [_make_result(
        "J04", "global", status, len(dupes), 0,
        f"{len(dupes)} duplicate (cik, source, report_date, position_id) groups",
        detail=detail,
    )]


def _get_wrapped_ciks() -> set[str]:
    """Return set of 10-digit CIK strings that have wrapper JSON definitions."""
    from pipeline.bdc_xbrl_wrapper import _WRAPPER_DEFINITIONS_DIR, normalize_cik
    wrapped = set()
    if not _WRAPPER_DEFINITIONS_DIR.exists():
        return wrapped
    for path in _WRAPPER_DEFINITIONS_DIR.glob("*.json"):
        cik = path.stem
        wrapped.add(normalize_cik(cik))
    return wrapped


def check_J01_position_key_stability(
    matches_df: pd.DataFrame,
    *,
    min_b1b_rate: float = 0.70,
) -> list[CheckResult]:
    """J01: For wrapped CIKs, >=70% of issuers in consecutive quarters match via B1b.

    Measures whether the wrapper's position keys are stable across quarters.
    Only evaluates CIKs that have wrapper JSON definitions.  For each wrapped
    CIK, counts how many match pairs used B1b_position_key vs lower tiers
    (B2/C/D/E).  If most matches bypass B1b, the position keys are unstable.
    """
    results: list[CheckResult] = []
    if matches_df is None or matches_df.empty:
        return [_make_result("J01", "global", "skip", 0, min_b1b_rate,
                             "No position match data available")]

    wrapped_ciks = _get_wrapped_ciks()
    if not wrapped_ciks:
        return [_make_result("J01", "global", "skip", 0, min_b1b_rate,
                             "No wrapped CIKs found")]

    method_col = "match_method"
    cik_col = "cik"
    if method_col not in matches_df.columns or cik_col not in matches_df.columns:
        return [_make_result("J01", "global", "skip", 0, min_b1b_rate,
                             "Missing match_method or cik column")]

    matches_df = matches_df.copy()
    matches_df[cik_col] = matches_df[cik_col].astype(str).str.zfill(10)
    wrapped_matches = matches_df[matches_df[cik_col].isin(wrapped_ciks)]

    if wrapped_matches.empty:
        return [_make_result("J01", "global", "skip", 0, min_b1b_rate,
                             "No matches found for wrapped CIKs")]

    for cik, cik_group in wrapped_matches.groupby(cik_col, dropna=False):
        cik_s = str(cik)
        total = len(cik_group)
        # Count high-confidence tiers (A is within-filing, B1 is CUSIP -- both
        # independent of wrapper position keys, so exclude from the denominator)
        non_a_b1 = cik_group[~cik_group[method_col].isin([
            "A_within_filing", "B1_cusip",
        ])]
        if non_a_b1.empty:
            # All matches are A or B1 -- position keys not exercised
            results.append(_make_result(
                "J01", "cik", "skip", 1.0, min_b1b_rate,
                f"{cik_s}: all {total} matches are A/B1 (position key not tested)",
                cik=cik_s,
            ))
            continue

        b1b_count = (non_a_b1[method_col] == "B1b_position_key").sum()
        b1b_rate = b1b_count / len(non_a_b1)
        status = "pass" if b1b_rate >= min_b1b_rate else "fail"

        # Build detail for failures: show tier distribution
        tier_dist = non_a_b1[method_col].value_counts().to_frame("count")
        tier_dist["pct"] = (tier_dist["count"] / len(non_a_b1) * 100).round(1)
        tier_dist = tier_dist.reset_index()
        tier_dist.columns = ["match_method", "count", "pct"]
        tier_dist.insert(0, "cik", cik_s)

        detail = tier_dist if status != "pass" else pd.DataFrame()
        results.append(_make_result(
            "J01", "cik", status, b1b_rate, min_b1b_rate,
            f"{cik_s}: B1b rate {b1b_rate:.1%} "
            f"({b1b_count}/{len(non_a_b1)} non-A/B1 matches)",
            detail=detail, cik=cik_s,
        ))

    if not results:
        results.append(_make_result("J01", "global", "skip", 0, min_b1b_rate,
                                    "No evaluable wrapped CIK matches"))
    return results


def check_J03_fuzzy_fallback_rate(
    matches_df: pd.DataFrame,
    *,
    max_fuzzy_rate: float = 0.10,
) -> list[CheckResult]:
    """J03: For wrapped CIKs, <10% of total matches should fall to Tier D fuzzy.

    A wrapped CIK should have stable position keys that prevent fallback to
    fuzzy matching.  High fuzzy rates indicate the wrapper's position keys
    contain volatile components or are otherwise unstable across quarters.
    """
    results: list[CheckResult] = []
    if matches_df is None or matches_df.empty:
        return [_make_result("J03", "global", "skip", 0, max_fuzzy_rate,
                             "No position match data available")]

    wrapped_ciks = _get_wrapped_ciks()
    if not wrapped_ciks:
        return [_make_result("J03", "global", "skip", 0, max_fuzzy_rate,
                             "No wrapped CIKs found")]

    method_col = "match_method"
    cik_col = "cik"
    if method_col not in matches_df.columns or cik_col not in matches_df.columns:
        return [_make_result("J03", "global", "skip", 0, max_fuzzy_rate,
                             "Missing match_method or cik column")]

    matches_df = matches_df.copy()
    matches_df[cik_col] = matches_df[cik_col].astype(str).str.zfill(10)
    wrapped_matches = matches_df[matches_df[cik_col].isin(wrapped_ciks)]

    if wrapped_matches.empty:
        return [_make_result("J03", "global", "skip", 0, max_fuzzy_rate,
                             "No matches found for wrapped CIKs")]

    for cik, cik_group in wrapped_matches.groupby(cik_col, dropna=False):
        cik_s = str(cik)
        total = len(cik_group)
        fuzzy_count = (cik_group[method_col] == "D_fuzzy").sum()
        fuzzy_rate = fuzzy_count / total if total > 0 else 0.0
        status = "pass" if fuzzy_rate <= max_fuzzy_rate else "fail"

        # Detail: show the fuzzy match keys for debugging
        detail = pd.DataFrame()
        if status != "pass" and "match_key" in cik_group.columns:
            fuzzy_rows = cik_group[cik_group[method_col] == "D_fuzzy"]
            detail = fuzzy_rows[["cik", method_col, "match_key"]].head(200).copy()
            if "match_score" in fuzzy_rows.columns:
                detail["match_score"] = fuzzy_rows["match_score"].head(200).values

        results.append(_make_result(
            "J03", "cik", status, fuzzy_rate, max_fuzzy_rate,
            f"{cik_s}: fuzzy rate {fuzzy_rate:.1%} "
            f"({fuzzy_count}/{total} matches)",
            detail=detail, cik=cik_s,
        ))

    if not results:
        results.append(_make_result("J03", "global", "skip", 0, max_fuzzy_rate,
                                    "No evaluable wrapped CIK matches"))
    return results


# ---------------------------------------------------------------------------
# Fuzzy fallback diagnostic
# ---------------------------------------------------------------------------

def diagnose_fuzzy_fallbacks(
    matches_df: pd.DataFrame,
    unified_df: pd.DataFrame,
) -> pd.DataFrame:
    """Diagnose D_fuzzy matches by showing which position key tokens differ.

    Joins the begin/end sides of each D_fuzzy match back to unified holdings
    to retrieve the position_key for each side, then tokenizes and diffs them.

    Returns a DataFrame with columns:
        cik, begin_report_date, end_report_date, begin_issuer_name,
        end_issuer_name, begin_position_key, end_position_key,
        match_score, key_diff_summary
    """
    if matches_df is None or matches_df.empty:
        return pd.DataFrame()

    if "match_method" not in matches_df.columns:
        return pd.DataFrame()

    fuzzy = matches_df[matches_df["match_method"] == "D_fuzzy"].copy()
    if fuzzy.empty:
        return pd.DataFrame()

    if unified_df is None or unified_df.empty:
        logger.warning("diagnose_fuzzy_fallbacks: empty unified_df, cannot join")
        return pd.DataFrame()

    if "position_key" not in unified_df.columns:
        logger.warning("diagnose_fuzzy_fallbacks: unified_df missing position_key column")
        return pd.DataFrame()

    # Prepare unified lookup keyed on (cik, report_date, issuer_name, fair_value_rounded)
    u = unified_df[["cik", "report_date", "issuer_name", "fair_value", "position_key"]].copy()
    u["cik"] = u["cik"].astype(str).str.zfill(10)
    u["report_date"] = u["report_date"].astype(str)
    u["issuer_name"] = u["issuer_name"].astype(str)
    u["fv_round"] = pd.to_numeric(u["fair_value"], errors="coerce").round(0)
    u = u.drop_duplicates(
        subset=["cik", "report_date", "issuer_name", "fv_round"],
        keep="first",
    )

    fuzzy["cik"] = fuzzy["cik"].astype(str).str.zfill(10)

    # Join begin side
    fuzzy["begin_report_date"] = fuzzy["begin_report_date"].astype(str)
    fuzzy["begin_issuer_name"] = fuzzy["begin_issuer_name"].astype(str)
    fuzzy["begin_fv_round"] = pd.to_numeric(
        fuzzy["begin_fair_value"], errors="coerce"
    ).round(0)

    begin_join = fuzzy.merge(
        u.rename(columns={"position_key": "begin_position_key"}),
        left_on=["cik", "begin_report_date", "begin_issuer_name", "begin_fv_round"],
        right_on=["cik", "report_date", "issuer_name", "fv_round"],
        how="left",
    )

    # Join end side
    fuzzy["end_report_date"] = fuzzy["end_report_date"].astype(str)
    fuzzy["end_issuer_name"] = fuzzy["end_issuer_name"].astype(str)
    fuzzy["end_fv_round"] = pd.to_numeric(
        fuzzy["end_fair_value"], errors="coerce"
    ).round(0)

    end_join = fuzzy.merge(
        u.rename(columns={"position_key": "end_position_key"}),
        left_on=["cik", "end_report_date", "end_issuer_name", "end_fv_round"],
        right_on=["cik", "report_date", "issuer_name", "fv_round"],
        how="left",
    )

    # Combine position keys from both joins
    out = fuzzy[["cik", "begin_report_date", "end_report_date",
                 "begin_issuer_name", "end_issuer_name"]].copy()
    out["begin_position_key"] = begin_join["begin_position_key"].values
    out["end_position_key"] = end_join["end_position_key"].values
    if "match_score" in fuzzy.columns:
        out["match_score"] = fuzzy["match_score"].values
    else:
        out["match_score"] = None

    # Compute key diff summary
    def _diff_tokens(row):
        bk = str(row.get("begin_position_key", "") or "")
        ek = str(row.get("end_position_key", "") or "")
        if not bk and not ek:
            return "both keys missing"
        if not bk:
            return "begin key missing"
        if not ek:
            return "end key missing"
        if bk == ek:
            return "identical keys"
        b_tokens = bk.split()
        e_tokens = ek.split()
        diffs_b = []
        diffs_e = []
        max_len = max(len(b_tokens), len(e_tokens))
        for i in range(max_len):
            bt = b_tokens[i] if i < len(b_tokens) else "<missing>"
            et = e_tokens[i] if i < len(e_tokens) else "<missing>"
            if bt != et:
                diffs_b.append(bt)
                diffs_e.append(et)
        return f"tokens differ: {diffs_b} vs {diffs_e}"

    out["key_diff_summary"] = out.apply(_diff_tokens, axis=1)

    return out.reset_index(drop=True)


# ===================================================================
# CHECK REGISTRY
# ===================================================================

# Maps check_id to (function, required_inputs_description)
CHECK_REGISTRY: dict[str, tuple[Any, str]] = {
    "A01": (check_A01_subtotal_arithmetic, "source_detail_df"),
    "A04": (check_A04_gav_reconciliation, "holdings_df, fund_financials_df"),
    "A07": (check_A07_pct_of_net_assets_sum, "holdings_df"),
    "B01": (check_B01_leaf_completeness, "source_detail_df"),
    "B02": (check_B02_unique_position_keys, "holdings_df"),
    "B07": (check_B07_single_accession_per_quarter, "source_detail_df"),
    "B08": (check_B08_comparative_period_exclusion, "source_detail_df"),
    "C01": (check_C01_debt_has_rate, "holdings_df"),
    "C04": (check_C04_equity_has_shares, "holdings_df"),
    "C05": (check_C05_no_rate_on_common_equity, "holdings_df"),
    "C08": (check_C08_fv_required, "holdings_df"),
    "D01": (check_D01_position_count_band, "holdings_df"),
    "D02": (check_D02_fv_stability, "holdings_df"),
    "D03": (check_D03_count_fv_divergence, "holdings_df"),
    "D06": (check_D06_position_continuity, "holdings_df"),
    "D07": (check_D07_rate_distribution_stability, "holdings_df"),
    "E01": (check_E01_holdings_fv_vs_investments, "holdings_df, fund_financials_df"),
    "E02": (check_E02_holdings_fv_vs_total_assets, "holdings_df, fund_financials_df"),
    "E04": (check_E04_nav_per_share_sanity, "fund_financials_df"),
    "E07": (check_E07_position_count_vs_filing, "source_detail_df, holdings_df"),
    "F01": (check_F01_interest_rate_range, "holdings_df"),
    "F03": (check_F03_fair_value_sign, "holdings_df"),
    "F04": (check_F04_pct_of_net_assets_range, "holdings_df"),
    "F07": (check_F07_null_fair_value, "holdings_df"),
    "F08": (check_F08_duplicate_detection, "holdings_df"),
    "F09": (check_F09_text_corruption, "holdings_df"),
    "F11": (check_F11_shares_sign, "holdings_df"),
    "F12": (check_F12_rate_scale_detection, "holdings_df"),
    "G01": (check_G01_keyword_aggregate_detection, "holdings_df"),
    "G02": (check_G02_arithmetic_subtotal_detection, "holdings_df"),
    "G03": (check_G03_header_row_detection, "holdings_df"),
    "H01": (check_H01_source_fact_coverage, "source_detail_df, holdings_df"),
    "H03": (check_H03_amendment_supersession, "source_detail_df"),
    "H05": (check_H05_bdc_source_vs_unified_gap, "source_detail_df"),
    "I02": (check_I02_leaf_marker_accuracy, "source_detail_df"),
    "I05": (check_I05_wrapper_content_signature_agreement, "source_detail_df"),
    "I06": (check_I06_non_private_market_exclusion, "source_detail_df"),
    "J01": (check_J01_position_key_stability, "matches_df"),
    "J03": (check_J03_fuzzy_fallback_rate, "matches_df"),
    "J04": (check_J04_unique_position_id_per_report_date, "holdings_df"),
}

ALL_CHECK_IDS = sorted(CHECK_REGISTRY.keys())

CATEGORIES = {
    "A": "Arithmetic Invariants",
    "B": "Structural Invariants",
    "C": "Content Invariants",
    "D": "Cross-Quarter Stability",
    "E": "Cross-Reference Checks",
    "F": "Data Quality",
    "G": "Aggregate Leak Detection",
    "H": "Source Completeness",
    "I": "Wrapper-Specific Checks",
    "J": "Position Matching Quality",
}
