"""Post-session validation and merge for CC skill GICS + aggregate header results.

Validates all GICS sub-industry names against the reference list, deduplicates
across batches, reconciles with existing caches, and reports coverage stats.

Usage:
    python scripts/gics_merge_results.py --validate       # Validate only
    python scripts/gics_merge_results.py --validate --apply  # Validate + rebuild
    python scripts/gics_merge_results.py --stats           # Show coverage stats
    python scripts/gics_merge_results.py --propose-rules   # Propose _BAD_ISSUER_NAMES_EXACT additions
"""

import argparse
import json
import logging
import subprocess
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import duckdb
import pandas as pd

from pipeline.config import (
    AGGREGATE_HEADER_FLAGS_FILE,
    COMPANY_GICS_CACHE_FILE,
    GICS_REFERENCE_FILE,
    GICS_SKILL_BATCHES_DIR,
    GICS_SKILL_CLAIMS_FILE,
    UNIFIED_HOLDINGS_FILE,
)
from pipeline.gics_classification import _normalize_company_name

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("gics_merge")


def _load_gics_reference() -> set[str]:
    """Load valid GICS sub-industry names."""
    with open(GICS_REFERENCE_FILE, encoding="utf-8") as f:
        names = json.load(f)
    return set(names)


def validate_gics_cache() -> tuple[int, int]:
    """Validate GICS cache entries against reference.

    Returns (valid_count, invalid_count).
    """
    if not COMPANY_GICS_CACHE_FILE.exists():
        logger.warning("GICS cache not found: %s", COMPANY_GICS_CACHE_FILE)
        return 0, 0

    valid_names = _load_gics_reference()
    valid_names.add("Other")  # "Other" is always valid

    cache = pd.read_csv(COMPANY_GICS_CACHE_FILE, dtype=str)
    invalid = []
    valid_count = 0

    for _, row in cache.iterrows():
        gics = str(row.get("gics_sub_industry", ""))
        if gics in valid_names:
            valid_count += 1
        else:
            invalid.append({
                "company_name_norm": row.get("company_name_norm", ""),
                "gics_sub_industry": gics,
                "source": row.get("source", ""),
            })

    if invalid:
        logger.error("Found %d invalid GICS sub-industry names:", len(invalid))
        for entry in invalid[:20]:
            logger.error("  '%s' -> '%s' (source=%s)",
                        entry["company_name_norm"],
                        entry["gics_sub_industry"],
                        entry["source"])
        if len(invalid) > 20:
            logger.error("  ... and %d more", len(invalid) - 20)
    else:
        logger.info("All %d GICS cache entries have valid sub-industry names", valid_count)

    return valid_count, len(invalid)


def validate_aggregate_flags() -> tuple[int, int]:
    """Validate aggregate header flags file.

    Returns (valid_count, issue_count).
    """
    if not AGGREGATE_HEADER_FLAGS_FILE.exists():
        logger.info("No aggregate header flags file found (OK for first run)")
        return 0, 0

    flags = pd.read_csv(AGGREGATE_HEADER_FLAGS_FILE, dtype=str)
    valid_verdicts = {"AGGREGATE_HEADER", "JV_SUBSIDIARY", "UNRESOLVABLE"}
    valid_confidence = {"high", "medium", "low"}

    issues = 0
    for _, row in flags.iterrows():
        verdict = str(row.get("verdict", ""))
        confidence = str(row.get("confidence", ""))
        name = str(row.get("name_norm", ""))

        if verdict not in valid_verdicts:
            logger.error("  Invalid verdict '%s' for '%s'", verdict, name)
            issues += 1
        if confidence not in valid_confidence:
            logger.error("  Invalid confidence '%s' for '%s'", confidence, name)
            issues += 1
        if not name.strip():
            logger.error("  Empty name_norm in flags file")
            issues += 1

    valid = len(flags) - issues
    if issues == 0:
        logger.info("All %d aggregate header flags are valid", len(flags))
    else:
        logger.error("%d issues in aggregate header flags", issues)

    # Verdict breakdown
    for verdict in valid_verdicts:
        count = (flags["verdict"] == verdict).sum()
        if count > 0:
            logger.info("  %s: %d entries", verdict, count)

    return valid, issues


def dedup_cache() -> int:
    """Deduplicate GICS cache (highest confidence wins).

    Returns number of duplicates removed.
    """
    if not COMPANY_GICS_CACHE_FILE.exists():
        return 0

    cache = pd.read_csv(COMPANY_GICS_CACHE_FILE, dtype=str)
    before = len(cache)

    # Confidence ranking: high > medium > low
    confidence_rank = {"high": 3, "medium": 2, "low": 1}
    cache["_conf_rank"] = cache["confidence"].map(confidence_rank).fillna(0)

    # For duplicates, prefer non-Other GICS, then higher confidence
    cache["_is_other"] = (cache["gics_sub_industry"] == "Other").astype(int)
    cache = cache.sort_values(
        ["company_name_norm", "_is_other", "_conf_rank"],
        ascending=[True, True, False],
    )
    cache = cache.drop_duplicates(subset=["company_name_norm"], keep="first")
    cache = cache.drop(columns=["_conf_rank", "_is_other"])

    removed = before - len(cache)
    if removed > 0:
        cache.to_csv(COMPANY_GICS_CACHE_FILE, index=False)
        logger.info("Removed %d duplicate cache entries", removed)

    return removed


def dedup_flags() -> int:
    """Deduplicate aggregate header flags (highest confidence wins).

    Returns number of duplicates removed.
    """
    if not AGGREGATE_HEADER_FLAGS_FILE.exists():
        return 0

    flags = pd.read_csv(AGGREGATE_HEADER_FLAGS_FILE, dtype=str)
    before = len(flags)

    confidence_rank = {"high": 3, "medium": 2, "low": 1}
    flags["_conf_rank"] = flags["confidence"].map(confidence_rank).fillna(0)
    flags = flags.sort_values(
        ["name_norm", "_conf_rank"],
        ascending=[True, False],
    )
    flags = flags.drop_duplicates(subset=["name_norm"], keep="first")
    flags = flags.drop(columns=["_conf_rank"])

    removed = before - len(flags)
    if removed > 0:
        flags.to_csv(AGGREGATE_HEADER_FLAGS_FILE, index=False)
        logger.info("Removed %d duplicate flag entries", removed)

    return removed


def show_stats() -> None:
    """Show coverage statistics."""
    if not UNIFIED_HOLDINGS_FILE.exists():
        logger.error("Unified holdings not found")
        return

    holdings = pd.read_csv(UNIFIED_HOLDINGS_FILE, dtype=str)

    con = duckdb.connect()
    con.register("h", holdings)

    # Overall GICS coverage
    stats = con.execute("""
        SELECT
            COUNT(*) AS total_rows,
            SUM(CASE WHEN CAST(gics_sub_industry AS VARCHAR) != ''
                     AND gics_sub_industry IS NOT NULL THEN 1 ELSE 0 END) AS gics_rows,
            SUM(TRY_CAST(fair_value AS DOUBLE)) AS total_fv,
            SUM(CASE WHEN CAST(gics_sub_industry AS VARCHAR) != ''
                     AND gics_sub_industry IS NOT NULL
                     THEN TRY_CAST(fair_value AS DOUBLE) ELSE 0 END) AS gics_fv
        FROM h
        WHERE CAST(issuer_category AS VARCHAR) = 'CORPORATE'
    """).fetchdf().iloc[0]

    total = int(stats["total_rows"])
    classified = int(stats["gics_rows"])
    total_fv = float(stats["total_fv"]) if stats["total_fv"] else 0
    gics_fv = float(stats["gics_fv"]) if stats["gics_fv"] else 0

    logger.info("GICS coverage (CORPORATE rows):")
    logger.info("  Rows: %d / %d (%.1f%%)", classified, total,
                100 * classified / total if total else 0)
    logger.info("  FV: $%.1fB / $%.1fB (%.1f%%)",
                gics_fv / 1e9, total_fv / 1e9,
                100 * gics_fv / total_fv if total_fv else 0)

    # Unclassified breakdown
    unclassified = con.execute("""
        SELECT
            CAST(issuer_name AS VARCHAR) AS issuer_name,
            SUM(TRY_CAST(fair_value AS DOUBLE)) AS total_fv,
            COUNT(*) AS n_rows,
            COUNT(DISTINCT LPAD(CAST(cik AS VARCHAR), 10, '0')) AS n_funds
        FROM h
        WHERE CAST(issuer_category AS VARCHAR) = 'CORPORATE'
          AND (CAST(gics_sub_industry AS VARCHAR) = ''
               OR gics_sub_industry IS NULL)
        GROUP BY CAST(issuer_name AS VARCHAR)
        ORDER BY total_fv DESC
        LIMIT 20
    """).fetchdf()

    if not unclassified.empty:
        remaining_fv = total_fv - gics_fv
        logger.info("Top 20 unclassified entities ($%.1fB remaining):", remaining_fv / 1e9)
        for _, row in unclassified.iterrows():
            fv = float(row["total_fv"]) if row["total_fv"] else 0
            logger.info("  $%.0fM  %d funds  %s",
                        fv / 1e6, int(row["n_funds"]), row["issuer_name"])

    # Cache source breakdown
    if COMPANY_GICS_CACHE_FILE.exists():
        cache = pd.read_csv(COMPANY_GICS_CACHE_FILE, dtype=str)
        source_counts = cache["source"].value_counts()
        logger.info("Cache source breakdown (%d total):", len(cache))
        for src, count in source_counts.items():
            non_other = ((cache["source"] == src) & (cache["gics_sub_industry"] != "Other")).sum()
            logger.info("  %s: %d entries (%d classified)", src, count, non_other)

    # Aggregate flags breakdown
    if AGGREGATE_HEADER_FLAGS_FILE.exists():
        flags = pd.read_csv(AGGREGATE_HEADER_FLAGS_FILE, dtype=str)
        logger.info("Aggregate header flags: %d entries", len(flags))
        for verdict in ["AGGREGATE_HEADER", "JV_SUBSIDIARY", "UNRESOLVABLE"]:
            count = (flags["verdict"] == verdict).sum()
            if count > 0:
                logger.info("  %s: %d", verdict, count)

    con.close()


def propose_rules() -> None:
    """Propose additions to _BAD_ISSUER_NAMES_EXACT from AGGREGATE_HEADER flags."""
    if not AGGREGATE_HEADER_FLAGS_FILE.exists():
        logger.info("No aggregate header flags to propose rules from")
        return

    flags = pd.read_csv(AGGREGATE_HEADER_FLAGS_FILE, dtype=str)
    agg = flags[
        (flags["verdict"] == "AGGREGATE_HEADER")
        & (flags["confidence"].isin(["high", "medium"]))
    ]

    if agg.empty:
        logger.info("No high/medium confidence AGGREGATE_HEADER flags")
        return

    logger.info("Proposed additions to _BAD_ISSUER_NAMES_EXACT (%d entries):", len(agg))
    logger.info("Review these before adding to pipeline/bdc_identifier.py:\n")
    for _, row in agg.iterrows():
        name = str(row["name_norm"])
        raw = str(row.get("issuer_name_raw", ""))
        evidence = str(row.get("evidence", ""))
        print(f'    "{name}",  # {evidence[:60]}')


def apply_results() -> None:
    """Rebuild unified holdings with updated caches."""
    logger.info("Rebuilding unified holdings with updated caches...")
    result = subprocess.run(
        [sys.executable, "scripts/rebuild_outputs.py", "--unified"],
        capture_output=True,
        text=True,
        cwd=str(PROJECT_ROOT),
    )
    if result.returncode == 0:
        logger.info("Rebuild completed successfully")
        # Show last few lines of output
        for line in result.stdout.strip().split("\n")[-5:]:
            logger.info("  %s", line)
    else:
        logger.error("Rebuild failed (exit code %d)", result.returncode)
        for line in result.stderr.strip().split("\n")[-10:]:
            logger.error("  %s", line)


def main():
    parser = argparse.ArgumentParser(
        description="Validate and merge CC skill GICS + aggregate header results"
    )
    parser.add_argument("--validate", action="store_true",
                        help="Validate cache entries and flags")
    parser.add_argument("--apply", action="store_true",
                        help="Rebuild unified holdings after validation")
    parser.add_argument("--stats", action="store_true",
                        help="Show GICS coverage statistics")
    parser.add_argument("--propose-rules", action="store_true",
                        help="Propose _BAD_ISSUER_NAMES_EXACT additions")
    args = parser.parse_args()

    if not any([args.validate, args.apply, args.stats, args.propose_rules]):
        parser.print_help()
        return

    if args.stats:
        show_stats()
        return

    if args.propose_rules:
        propose_rules()
        return

    if args.validate:
        t0 = time.time()
        logger.info("=== Validating GICS + Aggregate Header Results ===")

        # Deduplicate first
        dedup_cache()
        dedup_flags()

        # Validate
        gics_valid, gics_invalid = validate_gics_cache()
        flags_valid, flags_issues = validate_aggregate_flags()

        has_errors = gics_invalid > 0 or flags_issues > 0
        elapsed = time.time() - t0
        logger.info("Validation completed in %.1fs (%s)",
                    elapsed, "ERRORS FOUND" if has_errors else "PASS")

        if has_errors and args.apply:
            logger.error("Cannot apply: fix validation errors first")
            sys.exit(1)

    if args.apply:
        apply_results()


if __name__ == "__main__":
    main()
