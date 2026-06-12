"""Assess bipartite (Hungarian) matching vs greedy for C/D/E tiers.

Compares greedy and bipartite matching against the gold set of reviewed pairs
from calibration v2.

Usage:
    python scripts/assess_bipartite.py
"""

import json
import logging
import sys
import time
from collections import defaultdict
from pathlib import Path

import duckdb
import pandas as pd

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline.config import BDC_HOLDINGS_FILE, UNIFIED_HOLDINGS_FILE
from pipeline.position_matching import match_positions

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(message)s",
)
logger = logging.getLogger(__name__)

CALIB_DIR = Path("data/output/position_match_calibration")
SAMPLE_FILE = CALIB_DIR / "sample.csv"
V1_VERDICTS_DIR = CALIB_DIR / "verdicts_v1_backup"


def _normalize_cik(cik: str) -> str:
    """Strip leading zeros from CIK for cross-dataset join."""
    return str(int(cik)) if cik and cik.strip().isdigit() else cik


def _join_gold_to_matches(
    gold_df: pd.DataFrame,
    matches_df: pd.DataFrame,
    label: str,
) -> pd.DataFrame:
    """Join gold set rows to match output by begin-side identity.

    Uses DuckDB for robust string matching with CIK normalization.
    Returns gold rows augmented with match output end-side info.
    """
    con = duckdb.connect()
    con.register("gold", gold_df)
    con.register("matches", matches_df)

    sql = f"""
    SELECT
        g.sample_row_key,
        g.match_method AS gold_method,
        g.cik AS gold_cik,
        g.begin_report_date AS gold_begin_date,
        g.begin_issuer_name AS gold_begin_name,
        g.begin_fair_value AS gold_begin_fv,
        g.end_issuer_name AS gold_end_name,
        g.end_fair_value AS gold_end_fv,
        g.review_label,
        g.review_confidence,
        m.end_issuer_name AS {label}_end_name,
        m.end_fair_value AS {label}_end_fv,
        m.match_method AS {label}_method,
        m.begin_issuer_name AS {label}_begin_name,
        ROW_NUMBER() OVER (
            PARTITION BY g.sample_row_key
            ORDER BY
                ABS(COALESCE(TRY_CAST(g.begin_fair_value AS DOUBLE), 0)
                    - COALESCE(TRY_CAST(m.begin_fair_value AS DOUBLE), 0)) ASC
        ) AS _rn
    FROM gold g
    LEFT JOIN matches m
      ON CAST(CAST(TRY_CAST(g.cik AS BIGINT) AS VARCHAR) AS VARCHAR)
         = CAST(CAST(TRY_CAST(m.cik AS BIGINT) AS VARCHAR) AS VARCHAR)
     AND CAST(g.begin_report_date AS VARCHAR) = CAST(m.begin_report_date AS VARCHAR)
     AND lower(trim(CAST(g.begin_issuer_name AS VARCHAR)))
         = lower(trim(CAST(m.begin_issuer_name AS VARCHAR)))
     AND CAST(m.match_method AS VARCHAR) LIKE
         CAST(LEFT(g.match_method, 1) || '%' AS VARCHAR)
    """
    result = con.execute(sql).fetchdf()
    con.close()

    # Keep best match per gold row
    result = result[result["_rn"] == 1].drop(columns=["_rn"])
    return result


def main():
    t0 = time.time()

    # Load gold set
    if not SAMPLE_FILE.exists():
        logger.error("sample.csv not found at %s", SAMPLE_FILE)
        return
    v2_gold = pd.read_csv(SAMPLE_FILE, dtype=str)
    logger.info("V2 gold set: %d rows from sample.csv", len(v2_gold))

    # Filter to C/D/E tiers with non-ambiguous verdicts
    cde_mask = v2_gold["match_method"].str.match(r"^[CDE]_", na=False)
    non_ambiguous = v2_gold["review_label"].isin([
        "correct_match", "wrong_tranche", "wrong_entity", "wrong_instrument",
    ])
    gold_cde = v2_gold[cde_mask & non_ambiguous].copy()
    logger.info("Gold set C/D/E non-ambiguous: %d rows", len(gold_cde))

    if gold_cde.empty:
        logger.warning("No C/D/E gold-set rows to assess")
        return

    # Load data
    logger.info("Loading unified holdings...")
    unified_df = pd.read_csv(UNIFIED_HOLDINGS_FILE, dtype=str)
    logger.info("  %d rows", len(unified_df))

    logger.info("Loading raw BDC holdings...")
    bdc_raw_df = pd.read_csv(BDC_HOLDINGS_FILE, dtype=str)
    logger.info("  %d rows", len(bdc_raw_df))

    # Run greedy matching (to tmp file, not production)
    tmp_dir = Path(".tmp")
    tmp_dir.mkdir(exist_ok=True)

    logger.info("Running GREEDY matching (use_bipartite=False)...")
    greedy_df = match_positions(
        unified_df=unified_df.copy(),
        bdc_raw_df=bdc_raw_df.copy(),
        use_bipartite=False,
        output_file=tmp_dir / "greedy_matches.csv",
    )

    # Run bipartite matching
    logger.info("Running BIPARTITE matching (use_bipartite=True)...")
    bipartite_df = match_positions(
        unified_df=unified_df.copy(),
        bdc_raw_df=bdc_raw_df.copy(),
        use_bipartite=True,
        output_file=tmp_dir / "bipartite_matches.csv",
    )

    # Join gold set to both outputs
    logger.info("Joining gold set to greedy output...")
    greedy_joined = _join_gold_to_matches(gold_cde, greedy_df, "greedy")
    logger.info("Joining gold set to bipartite output...")
    bipartite_joined = _join_gold_to_matches(gold_cde, bipartite_df, "bipartite")

    # Merge the two joined results
    merged = greedy_joined.merge(
        bipartite_joined[["sample_row_key", "bipartite_end_name", "bipartite_end_fv",
                          "bipartite_method", "bipartite_begin_name"]],
        on="sample_row_key",
        how="outer",
    )

    # Count matches found
    greedy_found = merged["greedy_end_name"].notna().sum()
    bipartite_found = merged["bipartite_end_name"].notna().sum()
    logger.info("Gold rows matched: greedy=%d, bipartite=%d of %d",
                greedy_found, bipartite_found, len(gold_cde))

    # Compare
    errors_fixed = 0
    regressions = 0
    unchanged_correct = 0
    unchanged_error = 0
    not_in_greedy = 0
    not_in_bipartite = 0
    changed_details = []

    for _, row in merged.iterrows():
        label = str(row.get("review_label", ""))
        is_error = label in ("wrong_tranche", "wrong_entity", "wrong_instrument")

        g_end = row.get("greedy_end_name")
        b_end = row.get("bipartite_end_name")

        if pd.isna(g_end) or g_end is None:
            not_in_greedy += 1
            continue
        if pd.isna(b_end) or b_end is None:
            not_in_bipartite += 1
            continue

        g_end = str(g_end).strip().lower()
        b_end = str(b_end).strip().lower()

        if g_end == b_end:
            if is_error:
                unchanged_error += 1
            else:
                unchanged_correct += 1
        else:
            if is_error:
                errors_fixed += 1
            else:
                regressions += 1

            changed_details.append({
                "cik": row.get("gold_cik", ""),
                "begin_report_date": row.get("gold_begin_date", ""),
                "begin_issuer_name": str(row.get("gold_begin_name", ""))[:60],
                "gold_label": label,
                "match_method": row.get("gold_method", ""),
                "greedy_end": str(row.get("greedy_end_name", ""))[:60],
                "bipartite_end": str(row.get("bipartite_end_name", ""))[:60],
                "gold_end": str(row.get("gold_end_name", ""))[:60],
            })

    # Report
    assessed = len(merged) - not_in_greedy - not_in_bipartite
    print("\n" + "=" * 70)
    print("BIPARTITE MATCHING ASSESSMENT")
    print("=" * 70)
    print(f"\nGold set C/D/E rows: {len(gold_cde)}")
    print(f"Rows with both greedy + bipartite match: {assessed}")
    print(f"\n{'Metric':<42} {'Count':>8}")
    print("-" * 52)
    print(f"{'Errors fixed (wrong -> different pair)':<42} {errors_fixed:>8}")
    print(f"{'Regressions (correct -> different pair)':<42} {regressions:>8}")
    print(f"{'Unchanged correct':<42} {unchanged_correct:>8}")
    print(f"{'Unchanged error':<42} {unchanged_error:>8}")
    print(f"{'Not found in greedy output':<42} {not_in_greedy:>8}")
    print(f"{'Not found in bipartite output':<42} {not_in_bipartite:>8}")

    net_improvement = errors_fixed - regressions
    print(f"\n{'Net improvement':<42} {net_improvement:>+8}")

    # Tier breakdown
    tier_counts = defaultdict(lambda: {"fixed": 0, "regressed": 0, "same": 0})
    for _, row in merged.iterrows():
        method = str(row.get("gold_method", ""))
        tier = method.split("_")[0] if "_" in method else method
        label = str(row.get("review_label", ""))
        is_error = label in ("wrong_tranche", "wrong_entity", "wrong_instrument")
        g_end = row.get("greedy_end_name")
        b_end = row.get("bipartite_end_name")
        if pd.isna(g_end) or pd.isna(b_end):
            continue
        if str(g_end).strip().lower() == str(b_end).strip().lower():
            tier_counts[tier]["same"] += 1
        elif is_error:
            tier_counts[tier]["fixed"] += 1
        else:
            tier_counts[tier]["regressed"] += 1

    print(f"\n{'Tier':<10} {'Fixed':>8} {'Regressed':>10} {'Unchanged':>10}")
    print("-" * 40)
    for tier in sorted(tier_counts.keys()):
        c = tier_counts[tier]
        print(f"{tier:<10} {c['fixed']:>8} {c['regressed']:>10} {c['same']:>10}")

    # Changed pair details
    if changed_details:
        print(f"\n{'CHANGED PAIRS':=^70}")
        for d in changed_details:
            print(f"\n  CIK: {d['cik']}  Method: {d['match_method']}  "
                  f"Label: {d['gold_label']}")
            print(f"  Begin: {d['begin_issuer_name']}")
            print(f"  Greedy end:    {d['greedy_end']}")
            print(f"  Bipartite end: {d['bipartite_end']}")
            print(f"  Gold end:      {d['gold_end']}")

    # Match count comparison
    greedy_cde = greedy_df[
        greedy_df["match_method"].str.match(r"^[CDE]_", na=False)
    ]
    bipartite_cde = bipartite_df[
        bipartite_df["match_method"].str.match(r"^[CDE]_", na=False)
    ]
    print(f"\n{'MATCH COUNT COMPARISON':=^70}")
    for tier_prefix in ["C_", "D_", "E_"]:
        g_count = len(greedy_cde[greedy_cde["match_method"].str.startswith(tier_prefix)])
        b_count = len(bipartite_cde[bipartite_cde["match_method"].str.startswith(tier_prefix)])
        delta = b_count - g_count
        print(f"  {tier_prefix}*: greedy={g_count}, bipartite={b_count}, delta={delta:+d}")

    total_g = len(greedy_df)
    total_b = len(bipartite_df)
    print(f"  Total: greedy={total_g}, bipartite={total_b}, delta={total_b - total_g:+d}")

    elapsed = time.time() - t0
    print(f"\nElapsed: {elapsed:.1f}s")
    print("=" * 70)


if __name__ == "__main__":
    main()
