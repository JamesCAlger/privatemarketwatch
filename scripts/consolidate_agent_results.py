"""Consolidate unclassified agent review results into pipeline cache files.

Reads all ``data/output/unclassified_agent_results_*.csv`` files and merges
results into:

- ``aggregate_header_flags.csv`` -- AGGREGATE_HEADER verdicts (160 rows)
- ``unclassified_review_cache.csv`` -- CLASSIFIED + JV_SUBSIDIARY verdicts

Populates missing columns (issuer_name_raw, total_fv, etc.) from
``unclassified_needs_review.csv`` via name_norm join.

Usage:
    python scripts/consolidate_agent_results.py          # Merge all results
    python scripts/consolidate_agent_results.py --stats  # Show available files
    python scripts/consolidate_agent_results.py --dry-run  # Preview without writing
"""

import argparse
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd

from pipeline.config import (
    AGGREGATE_HEADER_FLAGS_FILE,
    UNCLASSIFIED_NEEDS_REVIEW_FILE,
    UNCLASSIFIED_REVIEW_CACHE_FILE,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("consolidate_agent")

OUTPUT_DIR = PROJECT_ROOT / "data" / "output"
RESULT_PATTERN = "unclassified_agent_results_*.csv"


def _load_needs_review_context() -> dict[str, dict]:
    """Load unclassified_needs_review.csv as a name_norm -> context dict."""
    if not UNCLASSIFIED_NEEDS_REVIEW_FILE.exists():
        logger.warning("Needs-review file not found: %s", UNCLASSIFIED_NEEDS_REVIEW_FILE)
        return {}
    df = pd.read_csv(UNCLASSIFIED_NEEDS_REVIEW_FILE, dtype=str).fillna("")
    ctx: dict[str, dict] = {}
    for _, row in df.iterrows():
        nn = row.get("name_norm", "").strip()
        if nn:
            ctx[nn] = {
                "issuer_name_raw": row.get("issuer_name_raw", ""),
                "total_fv": row.get("total_fv", ""),
                "n_positions": row.get("n_positions", ""),
            }
    return ctx


def find_result_files() -> list[Path]:
    """Find all unclassified agent result CSV files."""
    return sorted(OUTPUT_DIR.glob(RESULT_PATTERN))


def consolidate(*, dry_run: bool = False) -> None:
    """Merge unclassified agent results into cache files."""
    files = find_result_files()
    if not files:
        logger.info("No result files found matching %s", RESULT_PATTERN)
        return

    logger.info("Found %d agent result files", len(files))

    # Load context from needs-review file
    context = _load_needs_review_context()
    logger.info("Loaded %d entries from needs-review context file", len(context))

    # Load existing caches
    review_cols = [
        "name_norm", "issuer_name_raw", "verdict", "new_index_classification",
        "asset_class", "confidence", "evidence", "reviewed_by", "reviewed_at",
        "batch_id",
    ]
    if UNCLASSIFIED_REVIEW_CACHE_FILE.exists():
        review_cache = pd.read_csv(UNCLASSIFIED_REVIEW_CACHE_FILE, dtype=str)
    else:
        review_cache = pd.DataFrame(columns=review_cols)

    flags_cols = [
        "name_norm", "issuer_name_raw", "verdict", "confidence", "evidence",
        "total_fv", "n_positions", "reviewed_by", "reviewed_at", "batch_id",
        "identifier_raw",
    ]
    if AGGREGATE_HEADER_FLAGS_FILE.exists():
        flags = pd.read_csv(AGGREGATE_HEADER_FLAGS_FILE, dtype=str)
    else:
        flags = pd.DataFrame(columns=flags_cols)

    review_names = set(review_cache["name_norm"].dropna().values)
    flags_names = set(flags["name_norm"].dropna().values)
    now = datetime.now(timezone.utc).isoformat()

    # Read all agent result files
    all_dfs = []
    for f in files:
        try:
            df = pd.read_csv(f, dtype=str).fillna("")
            all_dfs.append(df)
        except Exception as e:
            logger.error("Failed to read %s: %s", f.name, e)
    if not all_dfs:
        logger.info("No valid result data found")
        return

    all_results = pd.concat(all_dfs, ignore_index=True)
    # Deduplicate: keep first occurrence per name_norm
    all_results = all_results.drop_duplicates(subset=["name_norm"], keep="first")
    logger.info("Total unique agent results: %d", len(all_results))

    new_review_rows: list[dict] = []
    new_flag_rows: list[dict] = []
    stats = {
        "classified": 0,
        "aggregate_header": 0,
        "jv_subsidiary": 0,
        "unresolvable": 0,
        "skipped_existing": 0,
        "skipped_low_confidence": 0,
    }

    for _, row in all_results.iterrows():
        name_norm = str(row.get("name_norm", "")).strip()
        verdict = str(row.get("verdict", "")).strip()

        if not name_norm:
            continue

        # Get context from needs-review file
        ctx = context.get(name_norm, {})
        issuer_name_raw = ctx.get("issuer_name_raw", name_norm)
        total_fv = ctx.get("total_fv", "")
        n_positions = ctx.get("n_positions", "")

        new_idx = str(row.get("new_index_classification", "")).strip()
        asset_cls = str(row.get("asset_class", "")).strip()
        confidence = str(row.get("confidence", "")).strip().lower()
        evidence = str(row.get("evidence", "")).strip()

        if verdict == "AGGREGATE_HEADER":
            if name_norm in flags_names:
                stats["skipped_existing"] += 1
                continue
            new_flag_rows.append({
                "name_norm": name_norm,
                "issuer_name_raw": issuer_name_raw,
                "verdict": "AGGREGATE_HEADER",
                "confidence": confidence or "high",
                "evidence": evidence,
                "total_fv": total_fv,
                "n_positions": n_positions,
                "reviewed_by": "agent_review",
                "reviewed_at": now,
                "batch_id": "agent",
                "identifier_raw": "",
            })
            flags_names.add(name_norm)
            stats["aggregate_header"] += 1

        elif verdict in ("CLASSIFIED", "AUTO_CLASSIFIED"):
            if name_norm in review_names:
                stats["skipped_existing"] += 1
                continue
            if confidence == "low":
                stats["skipped_low_confidence"] += 1
                continue
            new_review_rows.append({
                "name_norm": name_norm,
                "issuer_name_raw": issuer_name_raw,
                "verdict": "CLASSIFIED",
                "new_index_classification": new_idx,
                "asset_class": asset_cls,
                "confidence": confidence or "medium",
                "evidence": evidence,
                "reviewed_by": "agent_review",
                "reviewed_at": now,
                "batch_id": "agent",
            })
            review_names.add(name_norm)
            stats["classified"] += 1

        elif verdict == "JV_SUBSIDIARY":
            if name_norm in review_names:
                stats["skipped_existing"] += 1
                continue
            new_review_rows.append({
                "name_norm": name_norm,
                "issuer_name_raw": issuer_name_raw,
                "verdict": "JV_SUBSIDIARY",
                "new_index_classification": "",
                "asset_class": "",
                "confidence": confidence or "high",
                "evidence": evidence,
                "reviewed_by": "agent_review",
                "reviewed_at": now,
                "batch_id": "agent",
            })
            review_names.add(name_norm)
            stats["jv_subsidiary"] += 1

        elif verdict == "UNRESOLVABLE":
            stats["unresolvable"] += 1

    logger.info(
        "Results: %d CLASSIFIED, %d AGGREGATE_HEADER, %d JV_SUBSIDIARY, "
        "%d UNRESOLVABLE, %d skipped (existing), %d skipped (low confidence)",
        stats["classified"], stats["aggregate_header"], stats["jv_subsidiary"],
        stats["unresolvable"], stats["skipped_existing"],
        stats["skipped_low_confidence"],
    )

    if dry_run:
        logger.info("[DRY RUN] Would add %d review cache rows, %d flag rows",
                    len(new_review_rows), len(new_flag_rows))
        return

    # Append and save
    if new_review_rows:
        review_cache = pd.concat(
            [review_cache, pd.DataFrame(new_review_rows)], ignore_index=True,
        )
        review_cache.to_csv(UNCLASSIFIED_REVIEW_CACHE_FILE, index=False)
        logger.info(
            "Review cache: added %d rows (total: %d) -> %s",
            len(new_review_rows), len(review_cache),
            UNCLASSIFIED_REVIEW_CACHE_FILE.name,
        )

    if new_flag_rows:
        flags = pd.concat(
            [flags, pd.DataFrame(new_flag_rows)], ignore_index=True,
        )
        flags.to_csv(AGGREGATE_HEADER_FLAGS_FILE, index=False)
        logger.info(
            "Aggregate flags: added %d rows (total: %d) -> %s",
            len(new_flag_rows), len(flags),
            AGGREGATE_HEADER_FLAGS_FILE.name,
        )


def show_stats() -> None:
    """Show available result files and verdict distribution."""
    files = find_result_files()
    if not files:
        logger.info("No result files found")
        return

    all_dfs = []
    for f in files:
        try:
            df = pd.read_csv(f, dtype=str)
            all_dfs.append(df)
        except Exception as e:
            logger.error("  %s: ERROR - %s", f.name, e)

    if all_dfs:
        combined = pd.concat(all_dfs, ignore_index=True)
        logger.info("Files: %d, Total rows: %d", len(files), len(combined))
        logger.info("Verdict distribution:")
        for verdict, count in combined["verdict"].value_counts().items():
            logger.info("  %s: %d", verdict, count)
        logger.info("Unique name_norm: %d", combined["name_norm"].nunique())

        # Check for confidence distribution on CLASSIFIED
        classified = combined[combined["verdict"] == "CLASSIFIED"]
        if not classified.empty:
            logger.info("CLASSIFIED confidence:")
            for conf, count in classified["confidence"].value_counts().items():
                logger.info("  %s: %d", conf, count)


def main():
    parser = argparse.ArgumentParser(
        description="Consolidate unclassified agent results into pipeline cache files",
    )
    parser.add_argument("--stats", action="store_true", help="Show available files")
    parser.add_argument("--dry-run", action="store_true",
                        help="Preview changes without writing")
    args = parser.parse_args()

    if args.stats:
        show_stats()
    else:
        consolidate(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
