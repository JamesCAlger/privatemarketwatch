"""Oracle harness for fund-level highlights validation.

Runs per-(cik, report_quarter, share_class) diagnostic checks against
bdc_fund_highlights.csv, cross-referencing bdc_fund_income.csv and
fund_financials.csv for consistency.

Validation groups
-----------------
1. Algebraic identity checks -- NAV and income identities (FAIL if broken)
2. Cross-source consistency (highlights vs fund_income and fund_financials)
3. Cross-quarter stability (QoQ continuity, drift detection)
4. Monotonicity and sign checks (ordering, floor constraints)
5. Coverage completeness (core field count, per-class symmetry)

Notes on calibration:
- Balance sheet identity (TA - TL = SE) is Group 2 (REVIEW), not Group 1,
  because the "assets" concept in XBRL often matches narrower elements and
  TA/TL/SE frequently come from different contexts within the same filing.
- Senior security coverage ratio is reported as a ratio (2.03x = 203%),
  not in percentage form, so floor check uses >= 1.0.
- Stability checks use instant-only data where available (NAV, shares) to
  avoid false jumps from instant/duration row alternation.

Public API
----------
run_highlights_oracle(highlights_df=None, fund_income_df=None,
                      fund_financials_df=None) -> pd.DataFrame
"""

import logging
import time

import numpy as np
import pandas as pd

from pipeline.config import (
    BDC_FUND_HIGHLIGHTS_FILE,
    BDC_FUND_HIGHLIGHTS_ORACLE_FILE,
    BDC_FUND_INCOME_FILE,
    FUND_FINANCIALS_FILE,
)
from pipeline.fund_highlights_wrapper import load_highlights_wrapper

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Tolerance for algebraic identity checks (as fraction, e.g. 0.02 = 2%)
_IDENTITY_TOL = 0.02
_INCOME_IDENTITY_TOL = 0.05

# Tolerance for cross-source checks
_CROSS_SOURCE_TOL = 0.05
_CROSS_SOURCE_TA_TOL = 0.02

# Cross-quarter stability thresholds
_NAV_QOQ_MAX = 0.50           # 50% change
_EXPENSE_RATIO_QOQ_MAX = 10.0  # 10 percentage points
_NII_RATIO_QOQ_MAX = 15.0      # 15 percentage points
_TOTAL_RETURN_MAX = 50.0        # 50% quarterly return
_SHARES_QOQ_MAX = 1.0          # 100% change (doubles/halves)

# Core fields for coverage check
_CORE_FIELDS = [
    "nav_per_share", "total_return", "nii_per_share",
    "expense_ratio_incl_incentive", "distribution_per_share",
]

# Class field asymmetry threshold
_CLASS_ASYMMETRY_MAX = 0.30  # 30% field asymmetry across classes

# Mapping from highlights columns to bdc_fund_income columns
_CROSS_INCOME_MAP = {
    "net_investment_income": "net_investment_income",
    "management_fee_expense": "management_fee",
    "total_expenses": "total_expenses",
    "total_investment_income": "total_investment_income",
    "incentive_fee_expense": "incentive_fee",
    "interest_expense": "interest_expense",
}

# Mapping from highlights columns to fund_financials columns
_CROSS_FF_MAP = {
    "total_assets": "total_assets",
    "nav_per_share": "nav_per_share",
    "shares_outstanding": "shares_outstanding",
}

# Output columns
_ORACLE_COLUMNS = [
    "cik", "entity_name", "report_quarter", "share_class",
    # Group 1: identity
    "nav_identity_pct_diff", "income_identity_pct_diff",
    "balance_sheet_identity_pct_diff", "net_assets_equity_pct_diff",
    # Group 2: cross-source
    "cross_nii_pct_diff", "cross_mgmt_fee_pct_diff",
    "cross_expenses_pct_diff", "cross_total_income_pct_diff",
    "cross_incentive_fee_pct_diff", "cross_interest_expense_pct_diff",
    "cross_total_assets_pct_diff", "cross_nav_pct_diff",
    "cross_shares_pct_diff",
    # Group 3: stability
    "nav_qoq_change", "expense_ratio_qoq_change", "nii_ratio_qoq_change",
    "total_return_value", "shares_qoq_change",
    # Group 4: monotonicity/sign
    "expense_ratio_ordering_ok", "asset_coverage_ok",
    "total_return_above_floor", "coverage_ratio_ok",
    "facility_capacity_ordering_ok",
    # Group 5: coverage
    "core_field_count",
    "class_field_asymmetry",
    # Wrapper
    "highlights_wrapper_version",
    # Verdict
    "oracle_status",
    "oracle_fail_reasons",
    "oracle_review_reasons",
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _pct_diff(a: float, b: float) -> float:
    """Symmetric percentage difference: |a-b| / max(|a|, |b|).

    Returns NaN if both are zero or NaN.
    """
    if pd.isna(a) or pd.isna(b):
        return np.nan
    denom = max(abs(a), abs(b))
    if denom == 0:
        return 0.0
    return abs(a - b) / denom


def _load_highlights(highlights_df):
    """Load highlights, converting numeric columns."""
    if highlights_df is None:
        if not BDC_FUND_HIGHLIGHTS_FILE.exists():
            logger.warning("No highlights file at %s", BDC_FUND_HIGHLIGHTS_FILE)
            return pd.DataFrame()
        highlights_df = pd.read_csv(BDC_FUND_HIGHLIGHTS_FILE, dtype=str)
    df = highlights_df.copy()
    # Convert numeric columns
    skip = {"cik", "entity_name", "accession_number", "form_type", "filing_date",
            "period_end", "period_start", "period_type", "share_class",
            "report_quarter"}
    for col in df.columns:
        if col not in skip:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    # Normalize share_class: fillna with empty string
    df["share_class"] = df["share_class"].fillna("")
    return df


def _load_fund_income(fund_income_df):
    """Load fund income reference."""
    if fund_income_df is None:
        if not BDC_FUND_INCOME_FILE.exists():
            return pd.DataFrame()
        fund_income_df = pd.read_csv(BDC_FUND_INCOME_FILE, dtype=str)
    df = fund_income_df.copy()
    for col in df.columns:
        if col not in {"cik", "entity_name", "report_quarter", "report_date",
                        "form_type", "accession_number", "start_date", "end_date"}:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def _load_fund_financials(fund_financials_df):
    """Load fund financials reference."""
    if fund_financials_df is None:
        if not FUND_FINANCIALS_FILE.exists():
            return pd.DataFrame()
        fund_financials_df = pd.read_csv(FUND_FINANCIALS_FILE, dtype=str)
    df = fund_financials_df.copy()
    for col in df.columns:
        if col not in {"cik", "entity_name", "vehicle_type", "source",
                        "report_quarter", "report_date"}:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


# ---------------------------------------------------------------------------
# Group 1: Algebraic identity checks
# ---------------------------------------------------------------------------

def _check_identities(row: dict) -> dict:
    """Check algebraic relationships that must hold if data is correct.

    Returns dict of pct_diff values (NaN if not testable).
    """
    result = {}

    # NAV identity: assets_net ~ nav_per_share * shares_outstanding
    nav = row.get("nav_per_share")
    shares = row.get("shares_outstanding")
    assets_net = row.get("assets_net")
    if pd.notna(nav) and pd.notna(shares) and pd.notna(assets_net) and assets_net != 0:
        computed = nav * shares
        result["nav_identity_pct_diff"] = _pct_diff(assets_net, computed)
    else:
        result["nav_identity_pct_diff"] = np.nan

    # Income identity: TII - total_expenses ~ NII
    tii = row.get("total_investment_income")
    te = row.get("total_expenses")
    nii = row.get("net_investment_income")
    if pd.notna(tii) and pd.notna(te) and pd.notna(nii) and tii != 0:
        computed_nii = tii - te
        result["income_identity_pct_diff"] = _pct_diff(nii, computed_nii)
    else:
        result["income_identity_pct_diff"] = np.nan

    # Balance sheet identity: total_assets - total_liabilities ~ stockholders_equity
    ta = row.get("total_assets")
    tl = row.get("total_liabilities")
    se = row.get("stockholders_equity")
    if pd.notna(ta) and pd.notna(tl) and pd.notna(se) and ta != 0:
        computed_se = ta - tl
        result["balance_sheet_identity_pct_diff"] = _pct_diff(se, computed_se)
    else:
        result["balance_sheet_identity_pct_diff"] = np.nan

    # Net assets ~ equity
    if pd.notna(assets_net) and pd.notna(se) and max(abs(assets_net), abs(se)) > 0:
        result["net_assets_equity_pct_diff"] = _pct_diff(assets_net, se)
    else:
        result["net_assets_equity_pct_diff"] = np.nan

    return result


# ---------------------------------------------------------------------------
# Group 2: Cross-source consistency
# ---------------------------------------------------------------------------

def _build_income_lookup(fund_income_df: pd.DataFrame) -> dict:
    """Build (cik, report_quarter) -> row dict for fund income."""
    if fund_income_df.empty:
        return {}
    lookup = {}
    for _, row in fund_income_df.iterrows():
        key = (str(row.get("cik", "")), str(row.get("report_quarter", "")))
        if key not in lookup:
            lookup[key] = row.to_dict()
    return lookup


def _build_ff_lookup(fund_financials_df: pd.DataFrame) -> dict:
    """Build (cik, report_quarter) -> row dict for fund financials.

    For BDC source, prefer the BDC row; otherwise take first.
    """
    if fund_financials_df.empty:
        return {}
    lookup = {}
    # Sort so BDC source comes first
    df = fund_financials_df.copy()
    df["_source_rank"] = df.get("source", pd.Series("", index=df.index)).apply(
        lambda x: 0 if str(x).lower().startswith("bdc") else 1
    )
    df = df.sort_values("_source_rank")
    for _, row in df.iterrows():
        key = (str(row.get("cik", "")), str(row.get("report_quarter", "")))
        if key not in lookup:
            lookup[key] = row.to_dict()
    return lookup


def _check_cross_source(
    row: dict,
    income_lookup: dict,
    ff_lookup: dict,
) -> dict:
    """Check highlights values against fund_income and fund_financials."""
    result = {}
    cik = str(row.get("cik", ""))
    rq = str(row.get("report_quarter", ""))
    share_class = str(row.get("share_class", ""))

    # Cross-income checks only for entity-level rows (share_class == "")
    if share_class == "":
        income_row = income_lookup.get((cik, rq))
        if income_row:
            for hl_col, inc_col in _CROSS_INCOME_MAP.items():
                hl_val = row.get(hl_col)
                inc_val = income_row.get(inc_col)
                col_name = f"cross_{inc_col}_pct_diff"
                # Normalize column name for output
                out_col = {
                    "cross_net_investment_income_pct_diff": "cross_nii_pct_diff",
                    "cross_management_fee_pct_diff": "cross_mgmt_fee_pct_diff",
                    "cross_total_expenses_pct_diff": "cross_expenses_pct_diff",
                    "cross_total_investment_income_pct_diff": "cross_total_income_pct_diff",
                    "cross_incentive_fee_pct_diff": "cross_incentive_fee_pct_diff",
                    "cross_interest_expense_pct_diff": "cross_interest_expense_pct_diff",
                }.get(col_name, col_name)
                if pd.notna(hl_val) and pd.notna(inc_val):
                    result[out_col] = _pct_diff(float(hl_val), float(inc_val))
                else:
                    result[out_col] = np.nan
        else:
            for inc_col in _CROSS_INCOME_MAP.values():
                col_name = f"cross_{inc_col}_pct_diff"
                out_col = {
                    "cross_net_investment_income_pct_diff": "cross_nii_pct_diff",
                    "cross_management_fee_pct_diff": "cross_mgmt_fee_pct_diff",
                    "cross_total_expenses_pct_diff": "cross_expenses_pct_diff",
                    "cross_total_investment_income_pct_diff": "cross_total_income_pct_diff",
                    "cross_incentive_fee_pct_diff": "cross_incentive_fee_pct_diff",
                    "cross_interest_expense_pct_diff": "cross_interest_expense_pct_diff",
                }.get(col_name, col_name)
                result[out_col] = np.nan
    else:
        # Per-class rows: no cross-income check (income is entity-level)
        for out_col in ["cross_nii_pct_diff", "cross_mgmt_fee_pct_diff",
                        "cross_expenses_pct_diff", "cross_total_income_pct_diff",
                        "cross_incentive_fee_pct_diff", "cross_interest_expense_pct_diff"]:
            result[out_col] = np.nan

    # Cross-fund-financials checks (entity-level only for TA, but NAV/shares
    # can apply to entity-level rows)
    if share_class == "":
        ff_row = ff_lookup.get((cik, rq))
        if ff_row:
            for hl_col, ff_col in _CROSS_FF_MAP.items():
                hl_val = row.get(hl_col)
                ff_val = ff_row.get(ff_col)
                out_col = {
                    "total_assets": "cross_total_assets_pct_diff",
                    "nav_per_share": "cross_nav_pct_diff",
                    "shares_outstanding": "cross_shares_pct_diff",
                }[ff_col]
                if pd.notna(hl_val) and pd.notna(ff_val):
                    result[out_col] = _pct_diff(float(hl_val), float(ff_val))
                else:
                    result[out_col] = np.nan
        else:
            for out_col in ["cross_total_assets_pct_diff", "cross_nav_pct_diff",
                            "cross_shares_pct_diff"]:
                result[out_col] = np.nan
    else:
        for out_col in ["cross_total_assets_pct_diff", "cross_nav_pct_diff",
                        "cross_shares_pct_diff"]:
            result[out_col] = np.nan

    return result


# ---------------------------------------------------------------------------
# Group 3: Cross-quarter stability
# ---------------------------------------------------------------------------

def _check_stability(
    highlights_df: pd.DataFrame,
    oracle_df: pd.DataFrame,
) -> pd.DataFrame:
    """Compute QoQ stability metrics and merge into oracle_df.

    Uses highlights_df (with period_type) to select the right row type
    for each metric:
    - NAV and shares: prefer instant rows (balance-sheet snapshots)
    - Expense ratio, NII ratio, total return: prefer duration rows

    Only fires from Q2+ of each (cik, share_class) group.
    """
    oracle_df = oracle_df.copy()
    oracle_df["nav_qoq_change"] = np.nan
    oracle_df["expense_ratio_qoq_change"] = np.nan
    oracle_df["nii_ratio_qoq_change"] = np.nan
    oracle_df["total_return_value"] = np.nan
    oracle_df["shares_qoq_change"] = np.nan

    # Build lookup: (cik, report_quarter, share_class, period_type) -> row
    hl = highlights_df.copy()
    hl["share_class"] = hl["share_class"].fillna("")
    for c in ["nav_per_share", "shares_outstanding", "expense_ratio_incl_incentive",
              "nii_ratio", "total_return"]:
        if c in hl.columns:
            hl[c] = pd.to_numeric(hl[c], errors="coerce")

    # For each (cik, share_class) group, compute QoQ from the preferred
    # period_type time series.
    group_cols = ["cik", "share_class"]

    # Deduplicate highlights to one row per (cik, rq, share_class, period_type)
    # Already done by the extractor, but be safe.

    def _qoq_series(group_df, col, period_type_pref):
        """Get QoQ values for a column using preferred period type."""
        pref = group_df[group_df["period_type"] == period_type_pref]
        if pref.empty:
            # Fall back to whatever is available
            pref = group_df
        # Deduplicate to one per report_quarter
        pref = pref.sort_values("report_quarter").drop_duplicates(
            subset=["report_quarter"], keep="first"
        )
        if len(pref) < 2 or col not in pref.columns:
            return {}
        result = {}
        vals = pref[col].values
        quarters = pref["report_quarter"].values
        for i in range(1, len(vals)):
            prev_v, curr_v = vals[i - 1], vals[i]
            if pd.notna(prev_v) and pd.notna(curr_v):
                result[quarters[i]] = (prev_v, curr_v)
        return result

    for (cik, sc), group in hl.groupby(group_cols):
        # NAV QoQ (pct change, prefer instant)
        nav_series = _qoq_series(group, "nav_per_share", "instant")
        for rq, (prev, curr) in nav_series.items():
            if prev != 0:
                mask = ((oracle_df["cik"] == cik)
                        & (oracle_df["report_quarter"] == rq)
                        & (oracle_df["share_class"] == sc))
                oracle_df.loc[mask, "nav_qoq_change"] = (curr - prev) / abs(prev)

        # Shares QoQ (pct change, prefer instant)
        shares_series = _qoq_series(group, "shares_outstanding", "instant")
        for rq, (prev, curr) in shares_series.items():
            if prev != 0:
                mask = ((oracle_df["cik"] == cik)
                        & (oracle_df["report_quarter"] == rq)
                        & (oracle_df["share_class"] == sc))
                oracle_df.loc[mask, "shares_qoq_change"] = (curr - prev) / abs(prev)

        # Expense ratio QoQ (absolute pp change, prefer duration)
        er_series = _qoq_series(group, "expense_ratio_incl_incentive", "duration")
        for rq, (prev, curr) in er_series.items():
            mask = ((oracle_df["cik"] == cik)
                    & (oracle_df["report_quarter"] == rq)
                    & (oracle_df["share_class"] == sc))
            oracle_df.loc[mask, "expense_ratio_qoq_change"] = curr - prev

        # NII ratio QoQ (absolute pp change, prefer duration)
        nii_series = _qoq_series(group, "nii_ratio", "duration")
        for rq, (prev, curr) in nii_series.items():
            mask = ((oracle_df["cik"] == cik)
                    & (oracle_df["report_quarter"] == rq)
                    & (oracle_df["share_class"] == sc))
            oracle_df.loc[mask, "nii_ratio_qoq_change"] = curr - prev

        # Total return (absolute value for plausibility, prefer duration)
        dur_rows = group[group["period_type"] == "duration"]
        if dur_rows.empty:
            dur_rows = group
        for _, r in dur_rows.iterrows():
            tr = r.get("total_return")
            if pd.notna(tr):
                mask = ((oracle_df["cik"] == cik)
                        & (oracle_df["report_quarter"] == r["report_quarter"])
                        & (oracle_df["share_class"] == sc))
                oracle_df.loc[mask, "total_return_value"] = tr

    return oracle_df


# ---------------------------------------------------------------------------
# Group 4: Monotonicity and sign checks
# ---------------------------------------------------------------------------

def _check_monotonicity(row: dict) -> dict:
    """Check ordering and sign constraints."""
    result = {}

    # Expense ratio ordering: incl_incentive >= ex_mgmt_incentive
    er_incl = row.get("expense_ratio_incl_incentive")
    er_ex = row.get("expense_ratio_ex_mgmt_incentive")
    if pd.notna(er_incl) and pd.notna(er_ex):
        result["expense_ratio_ordering_ok"] = 1 if er_incl >= er_ex - 0.5 else 0
    else:
        result["expense_ratio_ordering_ok"] = np.nan

    # Asset coverage > 0
    ac = row.get("asset_coverage_per_unit")
    if pd.notna(ac):
        result["asset_coverage_ok"] = 1 if ac > 0 else 0
    else:
        result["asset_coverage_ok"] = np.nan

    # Total return > -100%
    tr = row.get("total_return")
    if pd.notna(tr):
        result["total_return_above_floor"] = 1 if tr > -100.0 else 0
    else:
        result["total_return_above_floor"] = np.nan

    # Senior security coverage ratio >= 1.0 (ratio form, not percentage;
    # 2.03 means 203% coverage, BDC regulatory minimum is 1.5 = 150%)
    scr = row.get("senior_security_coverage_ratio")
    if pd.notna(scr):
        result["coverage_ratio_ok"] = 1 if scr >= 1.0 else 0
    else:
        result["coverage_ratio_ok"] = np.nan

    # Facility capacity ordering: max >= remaining
    fmax = row.get("facility_max_capacity")
    frem = row.get("facility_remaining_capacity")
    if pd.notna(fmax) and pd.notna(frem):
        result["facility_capacity_ordering_ok"] = 1 if fmax >= frem - 1.0 else 0
    else:
        result["facility_capacity_ordering_ok"] = np.nan

    return result


# ---------------------------------------------------------------------------
# Group 5: Coverage completeness
# ---------------------------------------------------------------------------

def _check_coverage(row: dict) -> dict:
    """Check core field coverage count (per-row, overridden by aggregate later)."""
    count = sum(1 for f in _CORE_FIELDS if pd.notna(row.get(f)))
    return {"core_field_count": count}


def _compute_aggregate_core_count(highlights_df: pd.DataFrame) -> dict:
    """Compute core field count aggregated across instant + duration rows.

    Core fields span both period types (nav_per_share is instant,
    total_return/nii_per_share are duration), so aggregating across rows
    for the same (cik, report_quarter, share_class) gives the true count.

    Returns dict of (cik, report_quarter, share_class) -> int.
    """
    result = {}
    hl = highlights_df.copy()
    hl["share_class"] = hl["share_class"].fillna("")
    for col in _CORE_FIELDS:
        if col in hl.columns:
            hl[col] = pd.to_numeric(hl[col], errors="coerce")

    for (cik, rq, sc), group in hl.groupby(["cik", "report_quarter", "share_class"]):
        count = 0
        for f in _CORE_FIELDS:
            if f in group.columns and group[f].notna().any():
                count += 1
        result[(str(cik), str(rq), str(sc))] = count

    return result


def _compute_class_asymmetry(highlights_df: pd.DataFrame) -> dict:
    """Compute per-class field asymmetry for CIKs with multiple share classes.

    Returns dict of (cik, report_quarter, share_class) -> asymmetry_ratio.
    """
    result = {}
    per_class = highlights_df[highlights_df["share_class"] != ""].copy()
    if per_class.empty:
        return result

    data_cols = [c for c in _CORE_FIELDS if c in per_class.columns]
    if not data_cols:
        return result

    for (cik, rq), group in per_class.groupby(["cik", "report_quarter"]):
        if len(group) < 2:
            # Single class: no asymmetry
            for _, row in group.iterrows():
                result[(cik, rq, row["share_class"])] = 0.0
            continue

        # Compute non-null field sets per class
        field_sets = {}
        for _, row in group.iterrows():
            sc = row["share_class"]
            fields = frozenset(c for c in data_cols if pd.notna(row[c]))
            field_sets[sc] = fields

        # Union of all fields across classes
        all_fields = frozenset().union(*field_sets.values())
        if not all_fields:
            for sc in field_sets:
                result[(cik, rq, sc)] = 0.0
            continue

        # Per-class asymmetry: fields missing from this class / total fields
        for sc, fields in field_sets.items():
            missing = len(all_fields - fields)
            asymmetry = missing / len(all_fields)
            result[(cik, rq, sc)] = asymmetry

    return result


# ---------------------------------------------------------------------------
# Verdict logic
# ---------------------------------------------------------------------------

def _compute_verdict(
    row: dict,
    nav_identity_tol: float = _IDENTITY_TOL,
    income_identity_tol: float = _INCOME_IDENTITY_TOL,
) -> tuple:
    """Compute oracle_status, fail_reasons, review_reasons from check results.

    Parameters
    ----------
    row : dict
        Oracle check results for a single row.
    nav_identity_tol : float
        NAV identity tolerance (default: global _IDENTITY_TOL).
        Per-CIK wrappers may relax this up to 20%.
    income_identity_tol : float
        Income identity tolerance (default: global _INCOME_IDENTITY_TOL).
        Per-CIK wrappers may relax this up to 20%.

    Returns (status, fail_reasons_str, review_reasons_str).
    """
    fail_reasons = []
    review_reasons = []

    # --- Group 1: identity failures -> FAIL (NAV and income only) ---
    nav_id = row.get("nav_identity_pct_diff")
    if pd.notna(nav_id) and nav_id > nav_identity_tol:
        fail_reasons.append("nav_identity_fail")

    inc_id = row.get("income_identity_pct_diff")
    if pd.notna(inc_id) and inc_id > income_identity_tol:
        fail_reasons.append("income_identity_fail")

    # Balance sheet identity and net_assets/equity are DIAGNOSTIC only (not
    # verdict triggers). The XBRL "assets" concept is too ambiguous -- 90%+
    # of testable rows have TA/TL/SE from different contexts, producing
    # structural mismatches that don't indicate extraction errors.

    # --- Group 2: cross-source -> REVIEW ---
    cross_checks = [
        ("cross_nii_pct_diff", "cross_source_nii_mismatch", _CROSS_SOURCE_TOL),
        ("cross_mgmt_fee_pct_diff", "cross_source_mgmt_fee_mismatch", _CROSS_SOURCE_TOL),
        ("cross_expenses_pct_diff", "cross_source_expenses_mismatch", _CROSS_SOURCE_TOL),
        ("cross_total_income_pct_diff", "cross_source_total_income_mismatch", _CROSS_SOURCE_TOL),
        ("cross_incentive_fee_pct_diff", "cross_source_incentive_fee_mismatch", _CROSS_SOURCE_TOL),
        ("cross_interest_expense_pct_diff", "cross_source_interest_expense_mismatch", _CROSS_SOURCE_TOL),
        ("cross_total_assets_pct_diff", "cross_source_total_assets_mismatch", _CROSS_SOURCE_TA_TOL),
        ("cross_nav_pct_diff", "cross_source_nav_mismatch", _CROSS_SOURCE_TOL),
        ("cross_shares_pct_diff", "cross_source_shares_mismatch", _CROSS_SOURCE_TOL),
    ]
    for col, reason, tol in cross_checks:
        val = row.get(col)
        if pd.notna(val) and val > tol:
            review_reasons.append(reason)

    # --- Group 3: stability -> REVIEW ---
    nav_qoq = row.get("nav_qoq_change")
    if pd.notna(nav_qoq) and abs(nav_qoq) > _NAV_QOQ_MAX:
        review_reasons.append("nav_discontinuity")

    er_qoq = row.get("expense_ratio_qoq_change")
    if pd.notna(er_qoq) and abs(er_qoq) > _EXPENSE_RATIO_QOQ_MAX:
        review_reasons.append("expense_ratio_jump")

    nii_qoq = row.get("nii_ratio_qoq_change")
    if pd.notna(nii_qoq) and abs(nii_qoq) > _NII_RATIO_QOQ_MAX:
        review_reasons.append("nii_ratio_jump")

    tr = row.get("total_return_value")
    if pd.notna(tr) and abs(tr) > _TOTAL_RETURN_MAX:
        review_reasons.append("total_return_implausible")

    shares_qoq = row.get("shares_qoq_change")
    if pd.notna(shares_qoq) and abs(shares_qoq) > _SHARES_QOQ_MAX:
        review_reasons.append("share_count_discontinuity")

    # --- Group 4: monotonicity -> REVIEW ---
    if row.get("expense_ratio_ordering_ok") == 0:
        review_reasons.append("expense_ratio_ordering_violated")

    if row.get("asset_coverage_ok") == 0:
        review_reasons.append("negative_asset_coverage")

    if row.get("total_return_above_floor") == 0:
        review_reasons.append("total_return_below_floor")

    if row.get("coverage_ratio_ok") == 0:
        review_reasons.append("coverage_ratio_below_floor")

    if row.get("facility_capacity_ordering_ok") == 0:
        review_reasons.append("facility_capacity_ordering")

    # --- Group 5: coverage -> REVIEW ---
    # core_coverage_insufficient is NOT a per-row verdict trigger. It is a
    # CIK-level gate concern (checked in the quality gate against the best
    # quarter's aggregate core count). Per-row, it would fire on every
    # entity-level row that only has balance sheet data.

    asymmetry = row.get("class_field_asymmetry")
    if pd.notna(asymmetry) and asymmetry > _CLASS_ASYMMETRY_MAX:
        review_reasons.append("class_field_asymmetry")

    # --- Verdict ---
    if fail_reasons:
        status = "fail"
    elif review_reasons:
        status = "review_required"
    else:
        status = "pass"

    return (
        status,
        "|".join(fail_reasons) if fail_reasons else "",
        "|".join(review_reasons) if review_reasons else "",
    )


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def run_highlights_oracle(
    highlights_df=None,
    fund_income_df=None,
    fund_financials_df=None,
) -> pd.DataFrame:
    """Run oracle validation on fund-level highlights data.

    Parameters
    ----------
    highlights_df : DataFrame, optional
        Fund highlights data. Loaded from disk if None.
    fund_income_df : DataFrame, optional
        Fund income reference. Loaded from disk if None.
    fund_financials_df : DataFrame, optional
        Fund financials reference. Loaded from disk if None.

    Returns
    -------
    DataFrame with one row per (cik, report_quarter, share_class) and
    diagnostic columns + verdict.
    """
    t0 = time.time()

    hl = _load_highlights(highlights_df)
    if hl.empty:
        logger.warning("No highlights data to validate")
        return pd.DataFrame(columns=_ORACLE_COLUMNS)

    fi = _load_fund_income(fund_income_df)
    ff = _load_fund_financials(fund_financials_df)

    # Build cross-source lookups
    income_lookup = _build_income_lookup(fi)
    ff_lookup = _build_ff_lookup(ff)

    logger.info(
        "Oracle inputs: %d highlights rows, %d income rows, %d financials rows",
        len(hl), len(fi), len(ff),
    )

    # Compute class asymmetry upfront
    class_asymmetry = _compute_class_asymmetry(hl)

    # Process each row
    records = []
    for _, row in hl.iterrows():
        row_dict = row.to_dict()
        record = {
            "cik": row_dict.get("cik", ""),
            "entity_name": row_dict.get("entity_name", ""),
            "report_quarter": row_dict.get("report_quarter", ""),
            "share_class": row_dict.get("share_class", ""),
        }

        # Group 1: identities
        record.update(_check_identities(row_dict))

        # Group 2: cross-source
        record.update(_check_cross_source(row_dict, income_lookup, ff_lookup))

        # Group 4: monotonicity
        record.update(_check_monotonicity(row_dict))

        # Group 5: coverage
        record.update(_check_coverage(row_dict))

        # Class asymmetry
        key = (
            str(record["cik"]),
            str(record["report_quarter"]),
            str(record["share_class"]),
        )
        record["class_field_asymmetry"] = class_asymmetry.get(key, np.nan)

        records.append(record)

    oracle_df = pd.DataFrame(records)

    # Override per-row core_field_count with aggregate across period types.
    # Core fields span instant (nav_per_share) and duration (total_return,
    # nii_per_share, etc.), so a single row can't have all of them. The
    # aggregate count reflects what the CIK actually reports per quarter.
    agg_core = _compute_aggregate_core_count(hl)
    for i, row in oracle_df.iterrows():
        key = (str(row["cik"]), str(row["report_quarter"]), str(row["share_class"]))
        oracle_df.at[i, "core_field_count"] = agg_core.get(key, 0)

    # Group 3: stability -- uses highlights_df with period_type to select
    # instant rows for NAV/shares, duration rows for ratios/returns.
    oracle_df = _check_stability(hl, oracle_df)

    # Build per-CIK wrapper tolerance lookup
    wrapper_tols: dict[str, dict[str, float]] = {}
    wrapper_versions: dict[str, int] = {}
    for cik_val in oracle_df["cik"].unique():
        wrapper = load_highlights_wrapper(cik_val)
        if wrapper:
            wrapper_tols[str(cik_val)] = wrapper.oracle_tolerances
            wrapper_versions[str(cik_val)] = wrapper.version
        else:
            wrapper_versions[str(cik_val)] = 0

    # Compute verdicts with per-CIK tolerances
    statuses = []
    fail_reasons = []
    review_reasons = []
    wv_col = []
    for _, row in oracle_df.iterrows():
        cik_str = str(row.get("cik", ""))
        tols = wrapper_tols.get(cik_str, {})
        nav_tol = tols.get("nav_identity_tol", _IDENTITY_TOL)
        inc_tol = tols.get("income_identity_tol", _INCOME_IDENTITY_TOL)
        status, fr, rr = _compute_verdict(
            row.to_dict(),
            nav_identity_tol=nav_tol,
            income_identity_tol=inc_tol,
        )
        statuses.append(status)
        fail_reasons.append(fr)
        review_reasons.append(rr)
        wv_col.append(wrapper_versions.get(cik_str, 0))

    oracle_df["highlights_wrapper_version"] = wv_col
    oracle_df["oracle_status"] = statuses
    oracle_df["oracle_fail_reasons"] = fail_reasons
    oracle_df["oracle_review_reasons"] = review_reasons

    # Ensure column order
    for col in _ORACLE_COLUMNS:
        if col not in oracle_df.columns:
            oracle_df[col] = np.nan
    oracle_df = oracle_df[_ORACLE_COLUMNS]

    # Save
    oracle_df.to_csv(BDC_FUND_HIGHLIGHTS_ORACLE_FILE, index=False)

    # Log summary
    n_total = len(oracle_df)
    n_pass = (oracle_df["oracle_status"] == "pass").sum()
    n_review = (oracle_df["oracle_status"] == "review_required").sum()
    n_fail = (oracle_df["oracle_status"] == "fail").sum()
    n_ciks = oracle_df["cik"].nunique()

    logger.info(
        "Oracle results: %d rows (%d CIKs) -- %d pass, %d review, %d fail",
        n_total, n_ciks, n_pass, n_review, n_fail,
    )

    # Log most common fail/review reasons
    _log_reason_summary(oracle_df, "oracle_fail_reasons", "Fail")
    _log_reason_summary(oracle_df, "oracle_review_reasons", "Review")

    elapsed = time.time() - t0
    logger.info("Oracle complete in %.1f s", elapsed)

    return oracle_df


def _log_reason_summary(df: pd.DataFrame, col: str, label: str) -> None:
    """Log frequency of each reason code."""
    reasons = df[col].dropna()
    reasons = reasons[reasons != ""]
    if reasons.empty:
        return

    # Split pipe-separated reasons and count
    all_reasons = []
    for val in reasons:
        all_reasons.extend(str(val).split("|"))

    from collections import Counter
    counts = Counter(all_reasons)
    logger.info("  %s reason breakdown:", label)
    for reason, count in counts.most_common(15):
        logger.info("    %-45s %5d", reason, count)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    run_highlights_oracle()
