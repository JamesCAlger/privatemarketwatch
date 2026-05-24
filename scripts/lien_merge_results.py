"""Post-session validation and merge for CC skill lien position results.

Validates lien position values (only 3 valid values), deduplicates across
batches, reconciles with existing cache, and reports coverage stats.

Usage:
    python scripts/lien_merge_results.py --validate       # Validate only
    python scripts/lien_merge_results.py --validate --apply  # Validate + rebuild
    python scripts/lien_merge_results.py --stats           # Show coverage stats
"""

import argparse
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
    LIEN_CACHE_FILE,
    LIEN_SKILL_BATCHES_DIR,
    UNIFIED_HOLDINGS_FILE,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("lien_merge")

VALID_LIEN_VALUES = {"First Lien", "Second Lien", "Unsecured"}


def validate_lien_cache() -> tuple[int, int]:
    """Validate lien cache entries.

    Returns (valid_count, invalid_count).
    """
    if not LIEN_CACHE_FILE.exists():
        logger.warning("Lien cache not found: %s", LIEN_CACHE_FILE)
        return 0, 0

    cache = pd.read_csv(LIEN_CACHE_FILE, dtype=str)
    invalid = []
    valid_count = 0

    for _, row in cache.iterrows():
        lien = str(row.get("lien_position", ""))
        if lien in VALID_LIEN_VALUES:
            valid_count += 1
        else:
            invalid.append({
                "pattern_norm": row.get("pattern_norm", ""),
                "lien_position": lien,
                "source": row.get("source", ""),
            })

    if invalid:
        logger.error("Found %d invalid lien_position values:", len(invalid))
        for entry in invalid[:20]:
            logger.error("  '%s' -> '%s' (source=%s)",
                        entry["pattern_norm"],
                        entry["lien_position"],
                        entry["source"])
        if len(invalid) > 20:
            logger.error("  ... and %d more", len(invalid) - 20)
    else:
        logger.info("All %d lien cache entries have valid lien_position values", valid_count)

    return valid_count, len(invalid)


def dedup_cache() -> int:
    """Deduplicate lien cache (highest confidence wins).

    Returns number of duplicates removed.
    """
    if not LIEN_CACHE_FILE.exists():
        return 0

    cache = pd.read_csv(LIEN_CACHE_FILE, dtype=str)
    before = len(cache)

    confidence_rank = {"high": 3, "medium": 2, "low": 1}
    cache["_conf_rank"] = cache["confidence"].map(confidence_rank).fillna(0)
    cache = cache.sort_values(
        ["pattern_norm", "_conf_rank"],
        ascending=[True, False],
    )
    cache = cache.drop_duplicates(subset=["pattern_norm"], keep="first")
    cache = cache.drop(columns=["_conf_rank"])

    removed = before - len(cache)
    if removed > 0:
        cache.to_csv(LIEN_CACHE_FILE, index=False)
        logger.info("Removed %d duplicate cache entries", removed)

    return removed


def show_stats() -> None:
    """Show lien position coverage statistics."""
    if not UNIFIED_HOLDINGS_FILE.exists():
        logger.error("Unified holdings not found")
        return

    holdings = pd.read_csv(UNIFIED_HOLDINGS_FILE, dtype=str)

    con = duckdb.connect()
    con.register("h", holdings)

    # Overall lien coverage for DIRECT_LENDING
    stats = con.execute("""
        SELECT
            COUNT(*) AS total_rows,
            SUM(CASE WHEN CAST(lien_position AS VARCHAR) != ''
                     AND lien_position IS NOT NULL THEN 1 ELSE 0 END) AS lien_rows,
            SUM(TRY_CAST(fair_value AS DOUBLE)) AS total_fv,
            SUM(CASE WHEN CAST(lien_position AS VARCHAR) != ''
                     AND lien_position IS NOT NULL
                     THEN TRY_CAST(fair_value AS DOUBLE) ELSE 0 END) AS lien_fv
        FROM h
        WHERE CAST(index_classification AS VARCHAR) = 'DIRECT_LENDING'
    """).fetchdf().iloc[0]

    total = int(stats["total_rows"])
    classified = int(stats["lien_rows"])
    total_fv = float(stats["total_fv"]) if stats["total_fv"] else 0
    lien_fv = float(stats["lien_fv"]) if stats["lien_fv"] else 0

    logger.info("Lien coverage (DIRECT_LENDING rows):")
    logger.info("  Rows: %d / %d (%.1f%%)", classified, total,
                100 * classified / total if total else 0)
    logger.info("  FV: $%.1fB / $%.1fB (%.1f%%)",
                lien_fv / 1e9, total_fv / 1e9,
                100 * lien_fv / total_fv if total_fv else 0)

    # Breakdown by lien position
    breakdown = con.execute("""
        SELECT
            COALESCE(CAST(lien_position AS VARCHAR), 'NULL') AS lien,
            COUNT(*) AS n_rows,
            SUM(TRY_CAST(fair_value AS DOUBLE)) AS total_fv
        FROM h
        WHERE CAST(index_classification AS VARCHAR) = 'DIRECT_LENDING'
        GROUP BY 1
        ORDER BY total_fv DESC
    """).fetchdf()

    logger.info("Breakdown:")
    for _, row in breakdown.iterrows():
        fv = float(row["total_fv"]) if row["total_fv"] else 0
        logger.info("  %-12s  %6d rows  $%.1fB",
                    row["lien"], int(row["n_rows"]), fv / 1e9)

    # Cache stats
    if LIEN_CACHE_FILE.exists():
        cache = pd.read_csv(LIEN_CACHE_FILE, dtype=str)
        source_counts = cache["source"].value_counts()
        logger.info("Cache source breakdown (%d total):", len(cache))
        for src, count in source_counts.items():
            logger.info("  %s: %d entries", src, count)

    con.close()


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
        for line in result.stdout.strip().split("\n")[-5:]:
            logger.info("  %s", line)
    else:
        logger.error("Rebuild failed (exit code %d)", result.returncode)
        for line in result.stderr.strip().split("\n")[-10:]:
            logger.error("  %s", line)


def main():
    parser = argparse.ArgumentParser(
        description="Validate and merge CC skill lien position results"
    )
    parser.add_argument("--validate", action="store_true",
                        help="Validate cache entries")
    parser.add_argument("--apply", action="store_true",
                        help="Rebuild unified holdings after validation")
    parser.add_argument("--stats", action="store_true",
                        help="Show lien coverage statistics")
    args = parser.parse_args()

    if not any([args.validate, args.apply, args.stats]):
        parser.print_help()
        return

    if args.stats:
        show_stats()
        return

    if args.validate:
        t0 = time.time()
        logger.info("=== Validating Lien Position Results ===")

        dedup_cache()
        valid, invalid = validate_lien_cache()

        has_errors = invalid > 0
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
