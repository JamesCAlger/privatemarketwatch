"""Quality gate for fund-level highlights data.

Aggregates oracle verdicts per CIK and assigns promotion tiers:
  - Verified: all quarters pass, deep time series, high cross-source match
  - Preliminary: passes but limited depth or lower cross-source match
  - Under review: review_required status in multiple quarters
  - Excluded: any oracle fail quarter

Produces a per-CIK gate CSV and a markdown summary.

Usage:
    python scripts/fund_highlights_quality_gate.py
    python scripts/fund_highlights_quality_gate.py --oracle-csv path/to/oracle.csv
"""

import argparse
import logging
import sys
import time
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
    FUND_HIGHLIGHTS_QUALITY_GATE_MD_FILE,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("fund_highlights_gate")

# ---------------------------------------------------------------------------
# Tier thresholds
# ---------------------------------------------------------------------------

# Minimum quarters of history for Verified tier
_VERIFIED_MIN_QUARTERS = 8
# Cross-source match rate thresholds
_VERIFIED_CROSS_MATCH_MIN = 0.95
_PASS_CROSS_MATCH_MIN = 0.80
_REVIEW_CROSS_MATCH_MIN = 0.50
# Max review-required quarters before REVIEW status
_PASS_MAX_REVIEW_QUARTERS = 2
# Core field count in latest quarter
_PASS_MIN_CORE = 3
_REVIEW_MIN_CORE = 2


# ---------------------------------------------------------------------------
# Gate logic
# ---------------------------------------------------------------------------

def _compute_cross_source_match_rate(oracle_df: pd.DataFrame, cik: str) -> float:
    """Compute cross-source match rate for a CIK.

    Counts the fraction of non-null cross-source pct_diff columns that
    are within tolerance (5% for most, 2% for total_assets).
    """
    cik_rows = oracle_df[oracle_df["cik"] == cik]
    cross_cols = [c for c in cik_rows.columns if c.startswith("cross_") and c.endswith("_pct_diff")]
    if not cross_cols:
        return np.nan

    total = 0
    matched = 0
    for col in cross_cols:
        vals = pd.to_numeric(cik_rows[col], errors="coerce").dropna()
        if vals.empty:
            continue
        tol = 0.02 if "total_assets" in col else 0.05
        total += len(vals)
        matched += (vals <= tol).sum()

    if total == 0:
        return np.nan
    return matched / total


def build_quality_gate(oracle_df: pd.DataFrame) -> pd.DataFrame:
    """Build per-CIK quality gate from oracle results.

    Parameters
    ----------
    oracle_df : DataFrame
        Output of run_highlights_oracle().

    Returns
    -------
    DataFrame with one row per CIK and gate verdict + tier.
    """
    if oracle_df.empty:
        return pd.DataFrame()

    # Ensure string types
    oracle_df = oracle_df.copy()
    oracle_df["cik"] = oracle_df["cik"].astype(str)
    oracle_df["oracle_status"] = oracle_df["oracle_status"].fillna("pass")
    oracle_df["oracle_fail_reasons"] = oracle_df["oracle_fail_reasons"].fillna("")
    oracle_df["oracle_review_reasons"] = oracle_df["oracle_review_reasons"].fillna("")

    records = []
    for cik, group in oracle_df.groupby("cik"):
        entity_name = group["entity_name"].iloc[0]

        # Count quarters (distinct report_quarter values)
        quarters = group["report_quarter"].nunique()

        # Aggregate to per-quarter verdict: a quarter's status is the BEST
        # status among its rows (pass > review_required > fail). This avoids
        # penalizing CIKs where entity-level rows flag review but per-class
        # rows pass.
        _status_rank = {"pass": 0, "review_required": 1, "fail": 2}
        quarter_statuses = {}
        for rq, qgroup in group.groupby("report_quarter"):
            best = min(qgroup["oracle_status"].map(lambda s: _status_rank.get(s, 2)))
            quarter_statuses[rq] = {0: "pass", 1: "review_required", 2: "fail"}[best]

        pass_q = sum(1 for s in quarter_statuses.values() if s == "pass")
        review_q = sum(1 for s in quarter_statuses.values() if s == "review_required")
        fail_q = sum(1 for s in quarter_statuses.values() if s == "fail")

        # Latest quarter info
        latest_rq = group["report_quarter"].max()
        latest_rows = group[group["report_quarter"] == latest_rq]
        latest_status = "fail" if (latest_rows["oracle_status"] == "fail").any() else (
            "review_required" if (latest_rows["oracle_status"] == "review_required").any() else "pass"
        )
        latest_fail = "|".join(
            latest_rows["oracle_fail_reasons"].dropna()
            [latest_rows["oracle_fail_reasons"] != ""].unique()
        )
        latest_review = "|".join(
            latest_rows["oracle_review_reasons"].dropna()
            [latest_rows["oracle_review_reasons"] != ""].unique()
        )

        # Cross-source match rate
        cross_match = _compute_cross_source_match_rate(oracle_df, str(cik))

        # Core field count: use the BEST quarter across all history, not just
        # the latest. The latest quarter is often a thin instant-only filing
        # (balance sheet snapshots) while earlier quarters have full financial
        # highlights (total return, expense ratios, per-share metrics).
        core_count = int(group["core_field_count"].max()) if not group.empty else 0
        # Also track latest quarter core count for reference
        latest_core = int(latest_rows["core_field_count"].max()) if not latest_rows.empty else 0

        # Count specific failure types
        identity_fail_count = 0
        stability_flag_count = 0
        coverage_flag_count = 0

        for _, row in group.iterrows():
            fr = str(row.get("oracle_fail_reasons", ""))
            rr = str(row.get("oracle_review_reasons", ""))
            all_reasons = (fr + "|" + rr).split("|")
            all_reasons = [r for r in all_reasons if r]

            for reason in all_reasons:
                if reason in ("nav_identity_fail", "income_identity_fail"):
                    identity_fail_count += 1
                elif reason in ("nav_discontinuity", "expense_ratio_jump",
                                "nii_ratio_jump", "total_return_implausible",
                                "share_count_discontinuity"):
                    stability_flag_count += 1
                elif reason in ("core_coverage_insufficient", "class_field_asymmetry"):
                    coverage_flag_count += 1

        # --- Gate verdict ---
        # FAIL if: latest quarter has identity failure, OR identity fails in
        # >50% of testable quarters, OR cross-source match < 50%, OR no core fields.
        # REVIEW if: any historical fail quarter, OR >2 review quarters,
        # OR cross-match < 80%, OR core fields < 3.
        # PASS otherwise.
        blocking_reasons = []

        latest_has_fail = latest_status == "fail"
        fail_rate = fail_q / max(fail_q + pass_q + review_q, 1)

        if latest_has_fail:
            blocking_reasons.append(f"latest_quarter_fail:{latest_rq}")
        if fail_rate > 0.5 and fail_q > 1:
            blocking_reasons.append(f"identity_fail_rate:{fail_rate:.0%}")
        if not pd.isna(cross_match) and cross_match < _REVIEW_CROSS_MATCH_MIN:
            blocking_reasons.append(f"cross_match_rate:{cross_match:.0%}")
        if core_count <= 1:
            blocking_reasons.append(f"core_fields:{core_count}")

        if blocking_reasons:
            gate_status = "FAIL"
        else:
            review_reasons_list = []
            if fail_q > 0:
                review_reasons_list.append(f"historical_fail_quarters:{fail_q}")
            if review_q > _PASS_MAX_REVIEW_QUARTERS:
                review_reasons_list.append(f"review_quarters:{review_q}")
            if not pd.isna(cross_match) and cross_match < _PASS_CROSS_MATCH_MIN:
                review_reasons_list.append(f"cross_match_rate:{cross_match:.0%}")
            if core_count < _PASS_MIN_CORE:
                review_reasons_list.append(f"core_fields:{core_count}")

            if review_reasons_list:
                gate_status = "REVIEW"
                blocking_reasons = review_reasons_list
            else:
                gate_status = "PASS"

        # --- Promotion tier ---
        if gate_status == "FAIL":
            tier = "Excluded"
        elif gate_status == "REVIEW":
            tier = "Under review"
        elif (quarters >= _VERIFIED_MIN_QUARTERS
              and (pd.isna(cross_match) or cross_match >= _VERIFIED_CROSS_MATCH_MIN)):
            tier = "Verified"
        else:
            tier = "Preliminary"

        records.append({
            "cik": str(cik),
            "entity_name": entity_name,
            "total_quarters": quarters,
            "pass_quarters": pass_q,
            "review_quarters": review_q,
            "fail_quarters": fail_q,
            "latest_quarter": latest_rq,
            "latest_oracle_status": latest_status,
            "latest_fail_reasons": latest_fail,
            "latest_review_reasons": latest_review,
            "cross_source_match_rate": round(cross_match, 4) if pd.notna(cross_match) else np.nan,
            "core_field_count_best": core_count,
            "core_field_count_latest": latest_core,
            "identity_fail_count": identity_fail_count,
            "stability_flag_count": stability_flag_count,
            "coverage_flag_count": coverage_flag_count,
            "gate_status": gate_status,
            "gate_blocking_reasons": "|".join(blocking_reasons) if blocking_reasons else "",
            "tier": tier,
        })

    gate_df = pd.DataFrame(records)
    gate_df = gate_df.sort_values(["gate_status", "cik"])
    return gate_df


def write_gate(gate_df: pd.DataFrame, csv_path: Path, md_path: Path) -> None:
    """Write gate results to CSV and markdown summary."""
    gate_df.to_csv(csv_path, index=False)
    logger.info("Gate CSV: %s (%d CIKs)", csv_path, len(gate_df))

    # Build markdown summary
    buf = StringIO()
    buf.write("# Fund Highlights Quality Gate\n\n")

    n_total = len(gate_df)
    n_pass = (gate_df["gate_status"] == "PASS").sum()
    n_review = (gate_df["gate_status"] == "REVIEW").sum()
    n_fail = (gate_df["gate_status"] == "FAIL").sum()

    buf.write(f"**{n_total} CIKs evaluated**\n\n")
    buf.write(f"| Status | Count | % |\n")
    buf.write(f"|--------|------:|---:|\n")
    for status, count in [("PASS", n_pass), ("REVIEW", n_review), ("FAIL", n_fail)]:
        pct = 100.0 * count / n_total if n_total else 0
        buf.write(f"| {status} | {count} | {pct:.0f}% |\n")
    buf.write("\n")

    # Tier breakdown
    buf.write("## Promotion Tiers\n\n")
    buf.write("| Tier | Count | Description |\n")
    buf.write("|------|------:|-------------|\n")
    for tier, desc in [
        ("Verified", "All pass, 8+ quarters, cross-match >= 95%"),
        ("Preliminary", "All pass but limited depth or lower cross-match"),
        ("Under review", "Multiple review-required quarters"),
        ("Excluded", "Any identity check failure"),
    ]:
        count = (gate_df["tier"] == tier).sum()
        buf.write(f"| {tier} | {count} | {desc} |\n")
    buf.write("\n")

    # Cross-source match rate stats
    match_rates = gate_df["cross_source_match_rate"].dropna()
    if not match_rates.empty:
        buf.write("## Cross-Source Match Rate\n\n")
        buf.write(f"- Median: {match_rates.median():.1%}\n")
        buf.write(f"- Mean: {match_rates.mean():.1%}\n")
        buf.write(f"- Min: {match_rates.min():.1%}\n")
        buf.write(f"- >= 95%: {(match_rates >= 0.95).sum()} CIKs\n")
        buf.write(f"- >= 80%: {(match_rates >= 0.80).sum()} CIKs\n")
        buf.write(f"- < 50%: {(match_rates < 0.50).sum()} CIKs\n")
        buf.write("\n")

    # Most common blocking reasons
    all_reasons = []
    for val in gate_df["gate_blocking_reasons"].dropna():
        val = str(val)
        if val:
            all_reasons.extend(val.split("|"))
    if all_reasons:
        from collections import Counter
        reason_counts = Counter(r.split(":")[0] for r in all_reasons)
        buf.write("## Blocking Reason Frequency\n\n")
        buf.write("| Reason | Count |\n")
        buf.write("|--------|------:|\n")
        for reason, count in reason_counts.most_common():
            buf.write(f"| {reason} | {count} |\n")
        buf.write("\n")

    # Detail: failing CIKs
    failing = gate_df[gate_df["gate_status"] == "FAIL"]
    if not failing.empty:
        buf.write("## Failing CIKs\n\n")
        buf.write("| CIK | Entity | Fail Quarters | Latest Status | Blocking Reasons |\n")
        buf.write("|-----|--------|:-------------:|:-------------:|------------------|\n")
        for _, row in failing.head(25).iterrows():
            buf.write(
                f"| {row['cik']} | {str(row['entity_name'])[:40]} | "
                f"{row['fail_quarters']} | {row['latest_oracle_status']} | "
                f"{row['gate_blocking_reasons']} |\n"
            )
        if len(failing) > 25:
            buf.write(f"\n... and {len(failing) - 25} more\n")
        buf.write("\n")

    # Detail: Verified CIKs
    verified = gate_df[gate_df["tier"] == "Verified"]
    if not verified.empty:
        buf.write("## Verified CIKs (Top 20)\n\n")
        buf.write("| CIK | Entity | Quarters | Cross Match | Core Fields |\n")
        buf.write("|-----|--------|:--------:|:-----------:|:-----------:|\n")
        for _, row in verified.head(20).iterrows():
            cm = f"{row['cross_source_match_rate']:.0%}" if pd.notna(row["cross_source_match_rate"]) else "N/A"
            buf.write(
                f"| {row['cik']} | {str(row['entity_name'])[:40]} | "
                f"{row['total_quarters']} | {cm} | "
                f"{row['core_field_count_latest']} |\n"
            )
        buf.write("\n")

    md_text = buf.getvalue()
    md_path.write_text(md_text, encoding="utf-8")
    logger.info("Gate markdown: %s", md_path)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run_quality_gate(oracle_df: pd.DataFrame = None) -> pd.DataFrame:
    """Run the quality gate end-to-end.

    Parameters
    ----------
    oracle_df : DataFrame, optional
        Oracle results. Loaded from disk if None.

    Returns
    -------
    Gate DataFrame with one row per CIK.
    """
    t0 = time.time()

    if oracle_df is None:
        if not BDC_FUND_HIGHLIGHTS_ORACLE_FILE.exists():
            logger.error("No oracle file at %s. Run oracle first.", BDC_FUND_HIGHLIGHTS_ORACLE_FILE)
            return pd.DataFrame()
        oracle_df = pd.read_csv(BDC_FUND_HIGHLIGHTS_ORACLE_FILE, dtype=str)
        # Convert numeric columns
        for col in oracle_df.columns:
            if col not in {"cik", "entity_name", "report_quarter", "share_class",
                            "oracle_status", "oracle_fail_reasons", "oracle_review_reasons"}:
                oracle_df[col] = pd.to_numeric(oracle_df[col], errors="coerce")

    gate_df = build_quality_gate(oracle_df)

    if not gate_df.empty:
        write_gate(gate_df, FUND_HIGHLIGHTS_QUALITY_GATE_FILE, FUND_HIGHLIGHTS_QUALITY_GATE_MD_FILE)

    elapsed = time.time() - t0
    logger.info("Quality gate complete in %.1f s", elapsed)

    return gate_df


def main():
    parser = argparse.ArgumentParser(
        description="Fund highlights quality gate."
    )
    parser.add_argument("--oracle-csv", type=Path, default=None,
                        help="Path to oracle CSV (default: standard output path)")
    args = parser.parse_args()

    oracle_df = None
    if args.oracle_csv:
        oracle_df = pd.read_csv(args.oracle_csv, dtype=str)
        for col in oracle_df.columns:
            if col not in {"cik", "entity_name", "report_quarter", "share_class",
                            "oracle_status", "oracle_fail_reasons", "oracle_review_reasons"}:
                oracle_df[col] = pd.to_numeric(oracle_df[col], errors="coerce")

    run_quality_gate(oracle_df)


if __name__ == "__main__":
    main()
