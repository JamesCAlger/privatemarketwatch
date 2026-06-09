"""Residual profiler for fund-level highlights quality gate.

Categorizes each non-PASS CIK by dominant failure mode to inform
wrapper schema design. Produces a per-CIK profile CSV and a markdown
summary with category breakdown and cross-source field analysis.

Usage:
    python scripts/fund_highlights_residual_profiler.py
    python scripts/fund_highlights_residual_profiler.py --oracle-csv path --gate-csv path
"""

import argparse
import logging
import sys
import time
from collections import Counter
from io import StringIO
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pipeline.config import (
    BDC_FUND_HIGHLIGHTS_ORACLE_FILE,
    FUND_HIGHLIGHTS_QUALITY_GATE_FILE,
    FUND_HIGHLIGHTS_RESIDUAL_PROFILE_FILE,
    FUND_HIGHLIGHTS_RESIDUAL_PROFILE_MD_FILE,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("residual_profiler")

# ---------------------------------------------------------------------------
# Category definitions (priority order -- first match wins)
# ---------------------------------------------------------------------------

CATEGORY_PRIORITY = [
    "non_bdc_entity",
    "scale_mismatch",
    "concept_mapping_gap",
    "multi_class_asymmetry",
    "source_divergence",
    "stability_outlier",
    "temporal_gap",
    "coverage_thin",
]

WRAPPER_ACTIONABLE = {
    "non_bdc_entity": False,
    "scale_mismatch": True,
    "concept_mapping_gap": True,
    "multi_class_asymmetry": True,
    "source_divergence": True,
    "stability_outlier": False,  # investigate
    "temporal_gap": False,
    "coverage_thin": False,
}

ACTION_RECOMMENDATIONS = {
    "non_bdc_entity": "Exclude from universe",
    "scale_mismatch": "Per-CIK scale override",
    "concept_mapping_gap": "Per-CIK concept alias",
    "multi_class_asymmetry": "Share class mapping",
    "source_divergence": "Source preference rule",
    "stability_outlier": "Case-by-case investigation",
    "temporal_gap": "Investigate filing gap",
    "coverage_thin": "Document limitation",
}

# Non-TA cross-source columns (excluding total_assets)
_NON_TA_CROSS_COLS = [
    "cross_nii_pct_diff",
    "cross_mgmt_fee_pct_diff",
    "cross_expenses_pct_diff",
    "cross_total_income_pct_diff",
    "cross_incentive_fee_pct_diff",
    "cross_interest_expense_pct_diff",
    "cross_nav_pct_diff",
    "cross_shares_pct_diff",
]


# ---------------------------------------------------------------------------
# Detector functions
# ---------------------------------------------------------------------------

def _detect_non_bdc_entity(gate_row: pd.Series, cik_oracle: pd.DataFrame) -> bool:
    """core_fields <= 1 across all history, no BDC-typical data."""
    core_best = int(gate_row.get("core_field_count_best", 0) or 0)
    if core_best > 1:
        return False
    # Also check: very few testable rows
    n_rows = len(cik_oracle)
    if n_rows <= 2 and core_best <= 1:
        return True
    # If core_best is 0 or 1, this is not a real BDC
    return core_best <= 1


def _detect_scale_mismatch(cik_oracle: pd.DataFrame) -> tuple[bool, float, str]:
    """Non-TA cross-source pct_diffs consistently in [0.98, 1.02] band.

    Returns (detected, pct_in_band, affected_fields_str).
    TA-only scale mismatch is systemic and NOT flagged here.
    """
    in_band_counts = 0
    total_counts = 0
    affected_fields = []

    for col in _NON_TA_CROSS_COLS:
        if col not in cik_oracle.columns:
            continue
        vals = pd.to_numeric(cik_oracle[col], errors="coerce").dropna()
        if len(vals) < 3:
            continue
        band_mask = (vals >= 0.98) & (vals <= 1.02)
        field_in_band = band_mask.sum()
        if field_in_band / len(vals) >= 0.70:
            affected_fields.append(col.replace("cross_", "").replace("_pct_diff", ""))
        in_band_counts += field_in_band
        total_counts += len(vals)

    if total_counts < 3:
        return False, 0.0, ""

    pct_in_band = in_band_counts / total_counts
    # Need >= 70% of non-TA observations in scale band AND at least one affected field
    detected = pct_in_band >= 0.70 and len(affected_fields) > 0
    return detected, pct_in_band, "|".join(affected_fields)


def _detect_concept_mapping_gap(
    gate_row: pd.Series, cik_oracle: pd.DataFrame,
) -> tuple[bool, float]:
    """Identity fail rate >= 30% of testable rows.

    Returns (detected, identity_fail_rate).
    """
    identity_fail_count = int(gate_row.get("identity_fail_count", 0) or 0)
    # Testable rows = rows with at least one identity check populated
    identity_cols = [
        "nav_identity_pct_diff",
        "income_identity_pct_diff",
        "balance_sheet_identity_pct_diff",
        "net_assets_equity_pct_diff",
    ]
    testable = 0
    for col in identity_cols:
        if col in cik_oracle.columns:
            testable += pd.to_numeric(cik_oracle[col], errors="coerce").notna().sum()
    if testable == 0:
        return False, 0.0
    rate = identity_fail_count / testable
    return rate >= 0.30, rate


def _detect_multi_class_asymmetry(cik_oracle: pd.DataFrame) -> tuple[bool, int]:
    """class_field_asymmetry > 0.3 in >= 10% of per-class rows.

    Returns (detected, share_class_count).
    """
    if "class_field_asymmetry" not in cik_oracle.columns:
        return False, 0
    if "share_class" not in cik_oracle.columns:
        return False, 0

    share_classes = cik_oracle["share_class"].nunique()
    if share_classes <= 1:
        return False, share_classes

    asymmetry_vals = pd.to_numeric(
        cik_oracle["class_field_asymmetry"], errors="coerce",
    ).dropna()
    if asymmetry_vals.empty:
        return False, share_classes

    high_asymmetry = (asymmetry_vals > 0.3).sum()
    rate = high_asymmetry / len(asymmetry_vals)
    return rate >= 0.10, share_classes


def _detect_source_divergence(cik_oracle: pd.DataFrame) -> tuple[bool, float, int, str]:
    """Non-TA median pct_diff in (0.05, 0.98) -- not tight match, not scale band.

    Returns (detected, median_diff, fields_tested, divergent_fields_str).
    """
    all_diffs = []
    divergent_fields = []

    for col in _NON_TA_CROSS_COLS:
        if col not in cik_oracle.columns:
            continue
        vals = pd.to_numeric(cik_oracle[col], errors="coerce").dropna()
        if vals.empty:
            continue
        med = vals.median()
        all_diffs.append(med)
        if 0.05 < med < 0.98:
            divergent_fields.append(col.replace("cross_", "").replace("_pct_diff", ""))

    if not all_diffs:
        return False, 0.0, 0, ""

    overall_median = float(np.median(all_diffs))
    detected = 0.05 < overall_median < 0.98
    return detected, overall_median, len(all_diffs), "|".join(divergent_fields)


def _detect_stability_outlier(
    gate_row: pd.Series, cik_oracle: pd.DataFrame,
) -> tuple[bool, float]:
    """Stability flags in >= 15% of rows, with 4+ quarters.

    Returns (detected, stability_flag_rate).
    """
    total_quarters = int(gate_row.get("total_quarters", 0) or 0)
    if total_quarters < 4:
        return False, 0.0

    stability_count = int(gate_row.get("stability_flag_count", 0) or 0)
    n_rows = len(cik_oracle)
    if n_rows == 0:
        return False, 0.0

    rate = stability_count / n_rows
    return rate >= 0.15, rate


def _detect_temporal_gap(
    gate_row: pd.Series, cik_oracle: pd.DataFrame,
) -> bool:
    """Latest quarter before 2024q3, but core_fields >= 2 historically."""
    latest = str(gate_row.get("latest_quarter", ""))
    if not latest:
        return False
    core_best = int(gate_row.get("core_field_count_best", 0) or 0)
    if core_best < 2:
        return False
    # Parse quarter: "2024q3" format
    return latest < "2024q3"


def _detect_coverage_thin(gate_row: pd.Series) -> bool:
    """core_field_count_best <= 2, no identity failures."""
    core_best = int(gate_row.get("core_field_count_best", 0) or 0)
    identity_fails = int(gate_row.get("identity_fail_count", 0) or 0)
    return core_best <= 2 and identity_fails == 0


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------

def classify_cik(
    cik: str,
    gate_row: pd.Series,
    cik_oracle: pd.DataFrame,
) -> dict:
    """Run all detectors and pick dominant failure mode by priority.

    Returns a dict with profile columns for this CIK.
    """
    detected_modes = []
    evidence = {}

    # 1. non_bdc_entity
    if _detect_non_bdc_entity(gate_row, cik_oracle):
        detected_modes.append("non_bdc_entity")

    # 2. scale_mismatch
    scale_hit, pct_in_band, scale_fields = _detect_scale_mismatch(cik_oracle)
    evidence["pct_cross_in_scale_band"] = round(pct_in_band, 4)
    evidence["scale_fields_affected"] = scale_fields
    if scale_hit:
        detected_modes.append("scale_mismatch")

    # 3. concept_mapping_gap
    concept_hit, identity_rate = _detect_concept_mapping_gap(gate_row, cik_oracle)
    evidence["identity_fail_rate"] = round(identity_rate, 4)
    if concept_hit:
        detected_modes.append("concept_mapping_gap")

    # 4. multi_class_asymmetry
    class_hit, share_classes = _detect_multi_class_asymmetry(cik_oracle)
    evidence["share_class_count"] = share_classes
    if class_hit:
        detected_modes.append("multi_class_asymmetry")

    # 5. source_divergence
    div_hit, median_diff, fields_tested, div_fields = _detect_source_divergence(
        cik_oracle,
    )
    evidence["cross_source_median_diff"] = round(median_diff, 4)
    evidence["cross_source_fields_tested"] = fields_tested
    evidence["divergent_fields"] = div_fields
    if div_hit:
        detected_modes.append("source_divergence")

    # 6. stability_outlier
    stab_hit, stab_rate = _detect_stability_outlier(gate_row, cik_oracle)
    evidence["stability_flag_rate"] = round(stab_rate, 4)
    if stab_hit:
        detected_modes.append("stability_outlier")

    # 7. temporal_gap
    if _detect_temporal_gap(gate_row, cik_oracle):
        detected_modes.append("temporal_gap")

    # 8. coverage_thin
    if _detect_coverage_thin(gate_row):
        detected_modes.append("coverage_thin")

    # Pick dominant by priority
    dominant = "coverage_thin"  # fallback
    for cat in CATEGORY_PRIORITY:
        if cat in detected_modes:
            dominant = cat
            break

    secondary = [m for m in detected_modes if m != dominant]

    return {
        "cik": cik,
        "entity_name": gate_row.get("entity_name", ""),
        "gate_status": gate_row.get("gate_status", ""),
        "tier": gate_row.get("tier", ""),
        "dominant_failure_mode": dominant,
        "secondary_failure_modes": "|".join(secondary) if secondary else "",
        "wrapper_actionable": WRAPPER_ACTIONABLE.get(dominant, False),
        "action_recommendation": ACTION_RECOMMENDATIONS.get(dominant, ""),
        "identity_fail_rate": evidence.get("identity_fail_rate", 0.0),
        "cross_source_median_diff": evidence.get("cross_source_median_diff", 0.0),
        "cross_source_fields_tested": evidence.get("cross_source_fields_tested", 0),
        "core_field_max": int(gate_row.get("core_field_count_best", 0) or 0),
        "quarters_with_data": int(gate_row.get("total_quarters", 0) or 0),
        "latest_quarter": gate_row.get("latest_quarter", ""),
        "share_class_count": evidence.get("share_class_count", 0),
        "stability_flag_rate": evidence.get("stability_flag_rate", 0.0),
        "pct_cross_in_scale_band": evidence.get("pct_cross_in_scale_band", 0.0),
        "scale_fields_affected": evidence.get("scale_fields_affected", ""),
        "divergent_fields": evidence.get("divergent_fields", ""),
    }


# ---------------------------------------------------------------------------
# Profile builder
# ---------------------------------------------------------------------------

def build_residual_profile(
    oracle_df: pd.DataFrame,
    gate_df: pd.DataFrame,
) -> pd.DataFrame:
    """Build residual profile for all non-PASS CIKs.

    Parameters
    ----------
    oracle_df : DataFrame
        Full oracle results (one row per CIK-quarter-class).
    gate_df : DataFrame
        Quality gate results (one row per CIK).

    Returns
    -------
    DataFrame with one row per non-PASS CIK.
    """
    non_pass = gate_df[gate_df["gate_status"] != "PASS"].copy()
    if non_pass.empty:
        logger.warning("No non-PASS CIKs found in gate data.")
        return pd.DataFrame()

    oracle_df = oracle_df.copy()
    oracle_df["cik"] = oracle_df["cik"].astype(str)

    records = []
    for _, gate_row in non_pass.iterrows():
        cik = str(gate_row["cik"])
        cik_oracle = oracle_df[oracle_df["cik"] == cik]
        record = classify_cik(cik, gate_row, cik_oracle)
        records.append(record)

    profile_df = pd.DataFrame(records)
    profile_df = profile_df.sort_values(
        ["dominant_failure_mode", "quarters_with_data"],
        ascending=[True, False],
    )
    return profile_df


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def write_profile(
    profile_df: pd.DataFrame,
    csv_path: Path,
    md_path: Path,
    oracle_df: pd.DataFrame | None = None,
) -> None:
    """Write profile CSV and markdown summary."""
    profile_df.to_csv(csv_path, index=False)
    logger.info("Profile CSV: %s (%d CIKs)", csv_path, len(profile_df))

    buf = StringIO()
    n_total = len(profile_df)

    buf.write("# Fund Highlights Residual Profile\n\n")
    buf.write(f"**{n_total} non-PASS CIKs profiled**\n\n")

    # --- Category breakdown ---
    buf.write("## Category Breakdown\n\n")
    buf.write("| Category | Count | % | Wrapper-Actionable |\n")
    buf.write("|----------|------:|---:|:------------------:|\n")
    cat_counts = profile_df["dominant_failure_mode"].value_counts()
    for cat in CATEGORY_PRIORITY:
        count = int(cat_counts.get(cat, 0))
        if count == 0:
            continue
        pct = 100.0 * count / n_total if n_total else 0
        actionable = "Yes" if WRAPPER_ACTIONABLE.get(cat, False) else "No"
        buf.write(f"| {cat} | {count} | {pct:.0f}% | {actionable} |\n")
    buf.write("\n")

    # --- Wrapper-actionable totals ---
    actionable_count = profile_df["wrapper_actionable"].sum()
    non_actionable_count = n_total - actionable_count
    buf.write("## Actionability Summary\n\n")
    buf.write(f"- **Wrapper-actionable**: {int(actionable_count)} CIKs "
              f"({100.0 * actionable_count / n_total:.0f}%)\n")
    buf.write(f"- **Non-actionable**: {int(non_actionable_count)} CIKs "
              f"({100.0 * non_actionable_count / n_total:.0f}%)\n\n")

    # --- Systemic TA note ---
    if oracle_df is not None and "cross_total_assets_pct_diff" in oracle_df.columns:
        ta_vals = pd.to_numeric(
            oracle_df["cross_total_assets_pct_diff"], errors="coerce",
        ).dropna()
        if not ta_vals.empty:
            ta_in_band = ((ta_vals >= 0.98) & (ta_vals <= 1.02)).sum()
            ta_pct = 100.0 * ta_in_band / len(ta_vals)
            buf.write("## Systemic Note: Total Assets Scale Mismatch\n\n")
            buf.write(
                f"cross_total_assets_pct_diff is in the [0.98, 1.02] scale band "
                f"for {ta_in_band}/{len(ta_vals)} observations ({ta_pct:.0f}%). "
                f"This is a systemic pattern (TA denominator difference) and is "
                f"NOT classified as per-CIK scale_mismatch. Only non-TA field "
                f"scale patterns trigger that category.\n\n"
            )

    # --- Per-category top CIKs ---
    buf.write("## Per-Category Detail\n\n")
    for cat in CATEGORY_PRIORITY:
        cat_rows = profile_df[profile_df["dominant_failure_mode"] == cat]
        if cat_rows.empty:
            continue
        action = ACTION_RECOMMENDATIONS.get(cat, "")
        buf.write(f"### {cat} ({len(cat_rows)} CIKs) -- {action}\n\n")

        # Pick display columns based on category
        if cat == "scale_mismatch":
            buf.write("| CIK | Entity | Quarters | Scale Band % | Fields Affected |\n")
            buf.write("|-----|--------|:--------:|:------------:|:---------------:|\n")
            for _, row in cat_rows.head(10).iterrows():
                buf.write(
                    f"| {row['cik']} | {str(row['entity_name'])[:35]} | "
                    f"{row['quarters_with_data']} | "
                    f"{row['pct_cross_in_scale_band']:.0%} | "
                    f"{row['scale_fields_affected']} |\n"
                )
        elif cat == "concept_mapping_gap":
            buf.write("| CIK | Entity | Quarters | Identity Fail Rate | Core Fields |\n")
            buf.write("|-----|--------|:--------:|:------------------:|:-----------:|\n")
            for _, row in cat_rows.head(10).iterrows():
                buf.write(
                    f"| {row['cik']} | {str(row['entity_name'])[:35]} | "
                    f"{row['quarters_with_data']} | "
                    f"{row['identity_fail_rate']:.0%} | "
                    f"{row['core_field_max']} |\n"
                )
        elif cat == "source_divergence":
            buf.write("| CIK | Entity | Quarters | Median Diff | Divergent Fields |\n")
            buf.write("|-----|--------|:--------:|:-----------:|:----------------:|\n")
            for _, row in cat_rows.head(10).iterrows():
                buf.write(
                    f"| {row['cik']} | {str(row['entity_name'])[:35]} | "
                    f"{row['quarters_with_data']} | "
                    f"{row['cross_source_median_diff']:.2%} | "
                    f"{row['divergent_fields']} |\n"
                )
        elif cat == "multi_class_asymmetry":
            buf.write("| CIK | Entity | Quarters | Classes | Core Fields |\n")
            buf.write("|-----|--------|:--------:|:-------:|:-----------:|\n")
            for _, row in cat_rows.head(10).iterrows():
                buf.write(
                    f"| {row['cik']} | {str(row['entity_name'])[:35]} | "
                    f"{row['quarters_with_data']} | "
                    f"{row['share_class_count']} | "
                    f"{row['core_field_max']} |\n"
                )
        elif cat == "stability_outlier":
            buf.write("| CIK | Entity | Quarters | Stability Rate | Core Fields |\n")
            buf.write("|-----|--------|:--------:|:--------------:|:-----------:|\n")
            for _, row in cat_rows.head(10).iterrows():
                buf.write(
                    f"| {row['cik']} | {str(row['entity_name'])[:35]} | "
                    f"{row['quarters_with_data']} | "
                    f"{row['stability_flag_rate']:.0%} | "
                    f"{row['core_field_max']} |\n"
                )
        else:
            # non_bdc_entity, temporal_gap, coverage_thin
            buf.write("| CIK | Entity | Quarters | Latest Quarter | Core Fields |\n")
            buf.write("|-----|--------|:--------:|:--------------:|:-----------:|\n")
            for _, row in cat_rows.head(10).iterrows():
                buf.write(
                    f"| {row['cik']} | {str(row['entity_name'])[:35]} | "
                    f"{row['quarters_with_data']} | "
                    f"{row['latest_quarter']} | "
                    f"{row['core_field_max']} |\n"
                )
        buf.write("\n")

    # --- Cross-source field divergence analysis ---
    if oracle_df is not None:
        all_cross_cols = [c for c in oracle_df.columns
                         if c.startswith("cross_") and c.endswith("_pct_diff")]
        if all_cross_cols:
            # Restrict to non-PASS CIKs
            non_pass_ciks = set(profile_df["cik"].astype(str))
            np_oracle = oracle_df[oracle_df["cik"].astype(str).isin(non_pass_ciks)]

            buf.write("## Cross-Source Field Divergence (Non-PASS CIKs)\n\n")
            buf.write("| Field | Observations | Median Diff | "
                      "Tight (<5%) | Divergent (5-98%) | Scale Band (98-102%) |\n")
            buf.write("|-------|:-----------:|:-----------:|"
                      ":-----------:|:-----------------:|:--------------------:|\n")

            for col in sorted(all_cross_cols):
                vals = pd.to_numeric(np_oracle[col], errors="coerce").dropna()
                if vals.empty:
                    continue
                n = len(vals)
                med = vals.median()
                tight = (vals <= 0.05).sum()
                divergent = ((vals > 0.05) & (vals < 0.98)).sum()
                scale_band = ((vals >= 0.98) & (vals <= 1.02)).sum()
                field_name = col.replace("cross_", "").replace("_pct_diff", "")
                buf.write(
                    f"| {field_name} | {n} | {med:.4f} | "
                    f"{tight} ({100*tight//n}%) | "
                    f"{divergent} ({100*divergent//n}%) | "
                    f"{scale_band} ({100*scale_band//n}%) |\n"
                )
            buf.write("\n")

    md_text = buf.getvalue()
    md_path.write_text(md_text, encoding="utf-8")
    logger.info("Profile markdown: %s", md_path)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def run_residual_profiler(
    oracle_df: pd.DataFrame | None = None,
    gate_df: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Run the residual profiler end-to-end.

    Parameters
    ----------
    oracle_df : DataFrame, optional
        Oracle results. Loaded from disk if None.
    gate_df : DataFrame, optional
        Gate results. Loaded from disk if None.

    Returns
    -------
    Profile DataFrame with one row per non-PASS CIK.
    """
    t0 = time.time()

    if oracle_df is None:
        if not BDC_FUND_HIGHLIGHTS_ORACLE_FILE.exists():
            logger.error(
                "No oracle file at %s. Run oracle first.",
                BDC_FUND_HIGHLIGHTS_ORACLE_FILE,
            )
            return pd.DataFrame()
        oracle_df = pd.read_csv(BDC_FUND_HIGHLIGHTS_ORACLE_FILE, dtype=str)
        for col in oracle_df.columns:
            if col not in {
                "cik", "entity_name", "report_quarter", "share_class",
                "oracle_status", "oracle_fail_reasons", "oracle_review_reasons",
            }:
                oracle_df[col] = pd.to_numeric(oracle_df[col], errors="coerce")

    if gate_df is None:
        if not FUND_HIGHLIGHTS_QUALITY_GATE_FILE.exists():
            logger.error(
                "No gate file at %s. Run quality gate first.",
                FUND_HIGHLIGHTS_QUALITY_GATE_FILE,
            )
            return pd.DataFrame()
        gate_df = pd.read_csv(FUND_HIGHLIGHTS_QUALITY_GATE_FILE, dtype=str)
        for col in gate_df.columns:
            if col not in {
                "cik", "entity_name", "gate_status", "tier",
                "latest_quarter", "latest_oracle_status",
                "latest_fail_reasons", "latest_review_reasons",
                "gate_blocking_reasons",
            }:
                gate_df[col] = pd.to_numeric(gate_df[col], errors="coerce")

    profile_df = build_residual_profile(oracle_df, gate_df)

    if not profile_df.empty:
        write_profile(
            profile_df,
            FUND_HIGHLIGHTS_RESIDUAL_PROFILE_FILE,
            FUND_HIGHLIGHTS_RESIDUAL_PROFILE_MD_FILE,
            oracle_df=oracle_df,
        )

    elapsed = time.time() - t0
    logger.info("Residual profiler complete in %.1f s", elapsed)

    return profile_df


def main():
    parser = argparse.ArgumentParser(
        description="Fund highlights residual profiler."
    )
    parser.add_argument(
        "--oracle-csv", type=Path, default=None,
        help="Path to oracle CSV (default: standard output path)",
    )
    parser.add_argument(
        "--gate-csv", type=Path, default=None,
        help="Path to gate CSV (default: standard output path)",
    )
    args = parser.parse_args()

    oracle_df = None
    gate_df = None

    if args.oracle_csv:
        oracle_df = pd.read_csv(args.oracle_csv, dtype=str)
        for col in oracle_df.columns:
            if col not in {
                "cik", "entity_name", "report_quarter", "share_class",
                "oracle_status", "oracle_fail_reasons", "oracle_review_reasons",
            }:
                oracle_df[col] = pd.to_numeric(oracle_df[col], errors="coerce")

    if args.gate_csv:
        gate_df = pd.read_csv(args.gate_csv, dtype=str)
        for col in gate_df.columns:
            if col not in {
                "cik", "entity_name", "gate_status", "tier",
                "latest_quarter", "latest_oracle_status",
                "latest_fail_reasons", "latest_review_reasons",
                "gate_blocking_reasons",
            }:
                gate_df[col] = pd.to_numeric(gate_df[col], errors="coerce")

    run_residual_profiler(oracle_df, gate_df)


if __name__ == "__main__":
    main()
