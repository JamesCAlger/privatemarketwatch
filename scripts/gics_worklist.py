"""Generate ranked batch CSVs of unclassified entities for CC skill processing.

Queries private_markets_holdings.csv for the latest quarter, groups by
issuer_name, ranks by total FV descending, and splits into batch CSVs
for parallel CC skill processing.

Usage:
    python scripts/gics_worklist.py                  # Generate batches (default 100/batch)
    python scripts/gics_worklist.py --batch-size 50  # Custom batch size
    python scripts/gics_worklist.py --max-batches 5  # Limit number of batches
    python scripts/gics_worklist.py --stats           # Show current worklist stats
    python scripts/gics_worklist.py --claim 3         # Mark batch 3 as claimed
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
    AGGREGATE_HEADER_FLAGS_FILE,
    COMPANY_GICS_CACHE_FILE,
    GICS_SKILL_BATCHES_DIR,
    GICS_SKILL_CLAIMS_FILE,
    UNIFIED_HOLDINGS_FILE,
)
from pipeline.gics_classification import (
    _extract_search_name,
    _normalize_company_name,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("gics_worklist")

BATCH_COLUMNS = [
    "entity_id",
    "issuer_name_raw",
    "name_norm",
    "search_name",
    "total_fv",
    "n_positions",
    "n_funds",
    "typical_class",
    "sample_fund",
    "sample_identifier",
]


def _load_already_resolved() -> set[str]:
    """Load normalized names already resolved (non-Other GICS or flagged)."""
    resolved: set[str] = set()

    # GICS cache: non-Other entries
    if COMPANY_GICS_CACHE_FILE.exists():
        df = pd.read_csv(COMPANY_GICS_CACHE_FILE, dtype=str)
        for _, row in df.iterrows():
            gics = str(row.get("gics_sub_industry", "Other"))
            if gics != "Other":
                name = str(row.get("company_name_norm", ""))
                if name:
                    resolved.add(name)

    # Aggregate header flags
    if AGGREGATE_HEADER_FLAGS_FILE.exists():
        df = pd.read_csv(AGGREGATE_HEADER_FLAGS_FILE, dtype=str)
        for _, row in df.iterrows():
            name = str(row.get("name_norm", ""))
            if name:
                resolved.add(name)

    return resolved


def _load_claims() -> dict:
    """Load batch claim tracking."""
    if GICS_SKILL_CLAIMS_FILE.exists():
        with open(GICS_SKILL_CLAIMS_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {}


def _save_claims(claims: dict) -> None:
    """Save batch claim tracking."""
    GICS_SKILL_CLAIMS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(GICS_SKILL_CLAIMS_FILE, "w", encoding="utf-8") as f:
        json.dump(claims, f, indent=2)


def generate_batches(batch_size: int = 100, max_batches: int | None = None) -> int:
    """Generate batch CSVs from unclassified entities.

    Returns the number of batches generated.
    """
    t0 = time.time()

    if not UNIFIED_HOLDINGS_FILE.exists():
        logger.error("Unified holdings not found: %s", UNIFIED_HOLDINGS_FILE)
        return 0

    logger.info("Loading unified holdings...")
    holdings = pd.read_csv(UNIFIED_HOLDINGS_FILE, dtype=str)
    already_resolved = _load_already_resolved()
    logger.info("Already resolved: %d names", len(already_resolved))

    con = duckdb.connect()
    con.register("holdings", holdings)

    # Get latest quarter for freshest data
    latest_q = con.execute("""
        SELECT MAX(CAST(report_date AS VARCHAR)) AS max_rd
        FROM holdings
        WHERE report_date IS NOT NULL AND CAST(report_date AS VARCHAR) != ''
    """).fetchone()[0]
    logger.info("Latest report_date: %s", latest_q)

    # Get unclassified CORPORATE entities ranked by FV
    candidates = con.execute("""
        SELECT
            CAST(issuer_name AS VARCHAR) AS issuer_name_raw,
            SUM(TRY_CAST(fair_value AS DOUBLE)) AS total_fv,
            COUNT(*) AS n_positions,
            COUNT(DISTINCT LPAD(CAST(cik AS VARCHAR), 10, '0')) AS n_funds,
            MODE(CAST(index_classification AS VARCHAR)) AS typical_class,
            FIRST(CAST(entity_name AS VARCHAR)) AS sample_fund,
            FIRST(CAST(bdc_investment_identifier AS VARCHAR)) AS sample_identifier
        FROM holdings
        WHERE CAST(issuer_category AS VARCHAR) = 'CORPORATE'
          AND (CAST(gics_sub_industry AS VARCHAR) = ''
               OR gics_sub_industry IS NULL)
          AND issuer_name IS NOT NULL
          AND CAST(issuer_name AS VARCHAR) != ''
        GROUP BY CAST(issuer_name AS VARCHAR)
        HAVING SUM(TRY_CAST(fair_value AS DOUBLE)) IS NOT NULL
        ORDER BY total_fv DESC
    """).fetchdf()
    con.close()

    logger.info("Raw candidates from DuckDB: %d", len(candidates))

    # Normalize and deduplicate, excluding already resolved
    records: list[dict] = []
    seen: set[str] = set()
    entity_id = 0

    for _, row in candidates.iterrows():
        raw_name = str(row["issuer_name_raw"])
        name_norm = _normalize_company_name(raw_name)
        if not name_norm or len(name_norm) <= 2:
            continue
        if name_norm in seen or name_norm in already_resolved:
            continue
        seen.add(name_norm)
        entity_id += 1

        search_name = _extract_search_name(raw_name)
        records.append({
            "entity_id": entity_id,
            "issuer_name_raw": raw_name,
            "name_norm": name_norm,
            "search_name": search_name if search_name else raw_name,
            "total_fv": float(row["total_fv"]) if row["total_fv"] else 0,
            "n_positions": int(row["n_positions"]),
            "n_funds": int(row["n_funds"]),
            "typical_class": str(row["typical_class"]) if row["typical_class"] else "",
            "sample_fund": str(row["sample_fund"]) if row["sample_fund"] else "",
            "sample_identifier": str(row["sample_identifier"]) if row["sample_identifier"] else "",
        })

    logger.info("After dedup/exclusion: %d entities", len(records))

    if not records:
        logger.info("No unresolved entities remaining")
        return 0

    # Split into batches
    GICS_SKILL_BATCHES_DIR.mkdir(parents=True, exist_ok=True)
    n_batches = (len(records) + batch_size - 1) // batch_size
    if max_batches is not None:
        n_batches = min(n_batches, max_batches)

    for i in range(n_batches):
        start = i * batch_size
        end = min(start + batch_size, len(records))
        batch_records = records[start:end]
        batch_df = pd.DataFrame(batch_records, columns=BATCH_COLUMNS)
        batch_path = GICS_SKILL_BATCHES_DIR / f"batch_{i + 1:03d}.csv"
        batch_df.to_csv(batch_path, index=False)

    total_fv = sum(r["total_fv"] for r in records[:n_batches * batch_size])
    logger.info("Generated %d batches (%d entities, $%.1fB FV) in %.1fs",
                n_batches, min(len(records), n_batches * batch_size),
                total_fv / 1e9, time.time() - t0)
    logger.info("Batches saved to %s", GICS_SKILL_BATCHES_DIR)

    return n_batches


def show_stats() -> None:
    """Show current worklist statistics."""
    if not GICS_SKILL_BATCHES_DIR.exists():
        logger.info("No batches directory found. Run without --stats first.")
        return

    batch_files = sorted(GICS_SKILL_BATCHES_DIR.glob("batch_*.csv"))
    if not batch_files:
        logger.info("No batch files found.")
        return

    claims = _load_claims()
    total_entities = 0
    total_fv = 0.0

    for bf in batch_files:
        df = pd.read_csv(bf, dtype=str)
        batch_num = bf.stem.replace("batch_", "")
        n = len(df)
        fv = df["total_fv"].astype(float).sum()
        status = claims.get(batch_num, {}).get("status", "unclaimed")
        total_entities += n
        total_fv += fv
        logger.info("  %s: %3d entities, $%.1fB FV [%s]",
                     bf.name, n, fv / 1e9, status)

    logger.info("Total: %d entities across %d batches, $%.1fB FV",
                total_entities, len(batch_files), total_fv / 1e9)


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
        description="Generate GICS skill worklist batches"
    )
    parser.add_argument("--batch-size", type=int, default=100,
                        help="Entities per batch (default: 100)")
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
