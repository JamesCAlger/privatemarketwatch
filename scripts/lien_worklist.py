"""Generate ranked batch CSVs of unclassified lien positions for CC skill processing.

Queries private_markets_holdings.csv for DIRECT_LENDING positions with NULL
lien_position, groups by normalized instrument pattern, ranks by total FV
descending, and splits into batch CSVs for parallel CC skill processing.

Usage:
    python scripts/lien_worklist.py                  # Generate batches (default 100/batch)
    python scripts/lien_worklist.py --batch-size 50  # Custom batch size
    python scripts/lien_worklist.py --max-batches 5  # Limit number of batches
    python scripts/lien_worklist.py --stats          # Show current worklist stats
    python scripts/lien_worklist.py --claim 3        # Mark batch 3 as claimed
"""

import argparse
import json
import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import duckdb
import pandas as pd

from pipeline.config import (
    LIEN_CACHE_FILE,
    LIEN_SKILL_BATCHES_DIR,
    LIEN_SKILL_CLAIMS_FILE,
    UNIFIED_HOLDINGS_FILE,
)
from pipeline.lien_classification import _normalize_instrument_pattern

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("lien_worklist")

BATCH_COLUMNS = [
    "pattern_norm",
    "sample_issuer_name",
    "sample_instrument_description",
    "sample_bdc_investment_identifier",
    "total_fv",
    "n_positions",
    "n_funds",
]


def _load_already_resolved() -> set[str]:
    """Load normalized patterns already resolved in lien cache."""
    resolved: set[str] = set()
    if LIEN_CACHE_FILE.exists():
        df = pd.read_csv(LIEN_CACHE_FILE, dtype=str)
        for _, row in df.iterrows():
            pattern = str(row.get("pattern_norm", ""))
            if pattern:
                resolved.add(pattern)
    return resolved


def _load_claims() -> dict:
    """Load batch claim tracking."""
    if LIEN_SKILL_CLAIMS_FILE.exists():
        with open(LIEN_SKILL_CLAIMS_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {}


def _save_claims(claims: dict) -> None:
    """Save batch claim tracking."""
    LIEN_SKILL_CLAIMS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(LIEN_SKILL_CLAIMS_FILE, "w", encoding="utf-8") as f:
        json.dump(claims, f, indent=2)


def generate_batches(batch_size: int = 100, max_batches: int | None = None) -> int:
    """Generate batch CSVs from unclassified lien positions.

    Returns the number of batches generated.
    """
    t0 = time.time()

    if not UNIFIED_HOLDINGS_FILE.exists():
        logger.error("Unified holdings not found: %s", UNIFIED_HOLDINGS_FILE)
        return 0

    logger.info("Loading unified holdings...")
    holdings = pd.read_csv(UNIFIED_HOLDINGS_FILE, dtype=str)
    already_resolved = _load_already_resolved()
    logger.info("Already resolved: %d patterns", len(already_resolved))

    con = duckdb.connect()
    con.register("holdings", holdings)

    # Get DIRECT_LENDING positions with NULL lien_position
    candidates = con.execute("""
        SELECT
            CAST(issuer_name AS VARCHAR) AS issuer_name,
            CAST(instrument_description AS VARCHAR) AS instrument_description,
            FIRST(CAST(bdc_investment_identifier AS VARCHAR)) AS sample_bdc_id,
            SUM(TRY_CAST(fair_value AS DOUBLE)) AS total_fv,
            COUNT(*) AS n_positions,
            COUNT(DISTINCT LPAD(CAST(cik AS VARCHAR), 10, '0')) AS n_funds
        FROM holdings
        WHERE CAST(index_classification AS VARCHAR) = 'DIRECT_LENDING'
          AND (lien_position IS NULL OR CAST(lien_position AS VARCHAR) = '')
          AND issuer_name IS NOT NULL
          AND CAST(issuer_name AS VARCHAR) != ''
        GROUP BY CAST(issuer_name AS VARCHAR),
                 CAST(instrument_description AS VARCHAR)
        HAVING SUM(TRY_CAST(fair_value AS DOUBLE)) IS NOT NULL
        ORDER BY total_fv DESC
    """).fetchdf()
    con.close()

    logger.info("Raw candidates from DuckDB: %d", len(candidates))

    # Normalize and deduplicate by instrument pattern, excluding already resolved
    records: list[dict] = []
    seen: set[str] = set()

    for _, row in candidates.iterrows():
        issuer = str(row["issuer_name"]) if row["issuer_name"] else ""
        inst = str(row["instrument_description"]) if row["instrument_description"] else ""
        combined = issuer + " " + inst
        pattern = _normalize_instrument_pattern(combined)
        if not pattern or len(pattern) <= 2:
            continue
        if pattern in seen or pattern in already_resolved:
            continue
        seen.add(pattern)

        records.append({
            "pattern_norm": pattern,
            "sample_issuer_name": issuer,
            "sample_instrument_description": inst,
            "sample_bdc_investment_identifier": str(row["sample_bdc_id"]) if row["sample_bdc_id"] else "",
            "total_fv": float(row["total_fv"]) if row["total_fv"] else 0,
            "n_positions": int(row["n_positions"]),
            "n_funds": int(row["n_funds"]),
        })

    logger.info("After dedup/exclusion: %d patterns", len(records))

    if not records:
        logger.info("No unresolved lien positions remaining")
        return 0

    # Split into batches
    LIEN_SKILL_BATCHES_DIR.mkdir(parents=True, exist_ok=True)
    n_batches = (len(records) + batch_size - 1) // batch_size
    if max_batches is not None:
        n_batches = min(n_batches, max_batches)

    for i in range(n_batches):
        start = i * batch_size
        end = min(start + batch_size, len(records))
        batch_records = records[start:end]
        batch_df = pd.DataFrame(batch_records, columns=BATCH_COLUMNS)
        batch_path = LIEN_SKILL_BATCHES_DIR / f"batch_{i + 1:03d}.csv"
        batch_df.to_csv(batch_path, index=False)

    total_fv = sum(r["total_fv"] for r in records[:n_batches * batch_size])
    logger.info("Generated %d batches (%d patterns, $%.1fB FV) in %.1fs",
                n_batches, min(len(records), n_batches * batch_size),
                total_fv / 1e9, time.time() - t0)
    logger.info("Batches saved to %s", LIEN_SKILL_BATCHES_DIR)

    return n_batches


def show_stats() -> None:
    """Show current worklist statistics."""
    if not LIEN_SKILL_BATCHES_DIR.exists():
        logger.info("No batches directory found. Run without --stats first.")
        return

    batch_files = sorted(LIEN_SKILL_BATCHES_DIR.glob("batch_*.csv"))
    if not batch_files:
        logger.info("No batch files found.")
        return

    claims = _load_claims()
    total_patterns = 0
    total_fv = 0.0

    for bf in batch_files:
        df = pd.read_csv(bf, dtype=str)
        batch_num = bf.stem.replace("batch_", "")
        n = len(df)
        fv = df["total_fv"].astype(float).sum()
        status = claims.get(batch_num, {}).get("status", "unclaimed")
        total_patterns += n
        total_fv += fv
        logger.info("  %s: %3d patterns, $%.1fB FV [%s]",
                     bf.name, n, fv / 1e9, status)

    logger.info("Total: %d patterns across %d batches, $%.1fB FV",
                total_patterns, len(batch_files), total_fv / 1e9)


def claim_batch(batch_num: int) -> None:
    """Mark a batch as claimed (advisory, not locked)."""
    claims = _load_claims()
    key = f"{batch_num:03d}"
    claims[key] = {
        "status": "claimed",
        "claimed_at": datetime.now(timezone.utc).isoformat(),
    }
    _save_claims(claims)
    logger.info("Batch %03d marked as claimed", batch_num)


def main():
    parser = argparse.ArgumentParser(
        description="Generate lien position skill worklist batches"
    )
    parser.add_argument("--batch-size", type=int, default=100,
                        help="Patterns per batch (default: 100)")
    parser.add_argument("--max-batches", type=int, default=None,
                        help="Maximum number of batches to generate")
    parser.add_argument("--stats", action="store_true",
                        help="Show current worklist statistics")
    parser.add_argument("--claim", type=int, default=None,
                        help="Mark batch N as claimed")
    args = parser.parse_args()

    if args.stats:
        show_stats()
    elif args.claim is not None:
        claim_batch(args.claim)
    else:
        generate_batches(batch_size=args.batch_size, max_batches=args.max_batches)


if __name__ == "__main__":
    main()
