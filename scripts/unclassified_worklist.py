"""Generate ranked batch CSVs of UNCLASSIFIED entities for CC skill processing.

Queries private_markets_holdings.csv for entities where
index_classification = 'UNCLASSIFIED', groups by issuer_name, ranks by
total FV descending, and splits into batch CSVs for parallel processing.

Usage:
    python scripts/unclassified_worklist.py                  # Generate batches (default 100/batch)
    python scripts/unclassified_worklist.py --batch-size 50  # Custom batch size
    python scripts/unclassified_worklist.py --max-batches 5  # Limit number of batches
    python scripts/unclassified_worklist.py --stats           # Show current worklist stats
    python scripts/unclassified_worklist.py --claim 3         # Mark batch 3 as claimed
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
    UNCLASSIFIED_REVIEW_CACHE_FILE,
    UNCLASSIFIED_SKILL_BATCHES_DIR,
    UNCLASSIFIED_SKILL_CLAIMS_FILE,
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
logger = logging.getLogger("unclassified_worklist")

BATCH_COLUMNS = [
    "entity_id",
    "issuer_name_raw",
    "name_norm",
    "search_name",
    "total_fv",
    "n_positions",
    "n_funds",
    "source",
    "asset_category",
    "exposure_type",
    "issuer_category",
    "sample_interest_rate",
    "sample_basis_spread",
    "sample_shares_held",
    "sample_principal_amount",
    "sample_maturity_date",
    "sample_instrument",
    "sample_identifier",
    "sample_fund",
]


def _load_already_resolved() -> set[str]:
    """Load normalized names already resolved (review cache or flagged)."""
    resolved: set[str] = set()

    # Unclassified review cache
    if UNCLASSIFIED_REVIEW_CACHE_FILE.exists():
        df = pd.read_csv(UNCLASSIFIED_REVIEW_CACHE_FILE, dtype=str)
        for _, row in df.iterrows():
            name = str(row.get("name_norm", ""))
            if name:
                resolved.add(name)

    # Aggregate header flags (shared with GICS)
    if AGGREGATE_HEADER_FLAGS_FILE.exists():
        df = pd.read_csv(AGGREGATE_HEADER_FLAGS_FILE, dtype=str)
        for _, row in df.iterrows():
            name = str(row.get("name_norm", ""))
            if name:
                resolved.add(name)

    return resolved


def _load_claims() -> dict:
    """Load batch claim tracking."""
    if UNCLASSIFIED_SKILL_CLAIMS_FILE.exists():
        with open(UNCLASSIFIED_SKILL_CLAIMS_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {}


def _save_claims(claims: dict) -> None:
    """Save batch claim tracking."""
    UNCLASSIFIED_SKILL_CLAIMS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(UNCLASSIFIED_SKILL_CLAIMS_FILE, "w", encoding="utf-8") as f:
        json.dump(claims, f, indent=2)


def generate_batches(batch_size: int = 100, max_batches: int | None = None) -> int:
    """Generate batch CSVs from UNCLASSIFIED entities.

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

    # Get UNCLASSIFIED entities ranked by FV with financial signal columns
    candidates = con.execute("""
        SELECT
            CAST(issuer_name AS VARCHAR) AS issuer_name_raw,
            SUM(TRY_CAST(fair_value AS DOUBLE)) AS total_fv,
            COUNT(*) AS n_positions,
            COUNT(DISTINCT LPAD(CAST(cik AS VARCHAR), 10, '0')) AS n_funds,
            MAX(CAST(source AS VARCHAR)) AS source,
            MAX(CAST(asset_category AS VARCHAR)) AS asset_category,
            MAX(CAST(exposure_type AS VARCHAR)) AS exposure_type,
            MAX(CAST(issuer_category AS VARCHAR)) AS issuer_category,
            MAX(TRY_CAST(interest_rate AS DOUBLE)) AS sample_interest_rate,
            MAX(TRY_CAST(basis_spread AS DOUBLE)) AS sample_basis_spread,
            MAX(TRY_CAST(shares_held AS DOUBLE)) AS sample_shares_held,
            MAX(TRY_CAST(principal_amount AS DOUBLE)) AS sample_principal_amount,
            MAX(CAST(maturity_date AS VARCHAR)) AS sample_maturity_date,
            MAX(CAST(instrument_description AS VARCHAR)) AS sample_instrument,
            MAX(CAST(bdc_investment_identifier AS VARCHAR)) AS sample_identifier,
            FIRST(CAST(entity_name AS VARCHAR)) AS sample_fund
        FROM holdings
        WHERE CAST(index_classification AS VARCHAR) = 'UNCLASSIFIED'
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
            "source": str(row["source"]) if row["source"] else "",
            "asset_category": str(row["asset_category"]) if row["asset_category"] else "",
            "exposure_type": str(row["exposure_type"]) if row["exposure_type"] else "",
            "issuer_category": str(row["issuer_category"]) if row["issuer_category"] else "",
            "sample_interest_rate": float(row["sample_interest_rate"]) if pd.notna(row["sample_interest_rate"]) else "",
            "sample_basis_spread": float(row["sample_basis_spread"]) if pd.notna(row["sample_basis_spread"]) else "",
            "sample_shares_held": float(row["sample_shares_held"]) if pd.notna(row["sample_shares_held"]) else "",
            "sample_principal_amount": float(row["sample_principal_amount"]) if pd.notna(row["sample_principal_amount"]) else "",
            "sample_maturity_date": str(row["sample_maturity_date"]) if row["sample_maturity_date"] else "",
            "sample_instrument": str(row["sample_instrument"]) if row["sample_instrument"] else "",
            "sample_identifier": str(row["sample_identifier"]) if row["sample_identifier"] else "",
            "sample_fund": str(row["sample_fund"]) if row["sample_fund"] else "",
        })

    logger.info("After dedup/exclusion: %d entities", len(records))

    if not records:
        logger.info("No unresolved entities remaining")
        return 0

    # Split into batches
    UNCLASSIFIED_SKILL_BATCHES_DIR.mkdir(parents=True, exist_ok=True)
    n_batches = (len(records) + batch_size - 1) // batch_size
    if max_batches is not None:
        n_batches = min(n_batches, max_batches)

    for i in range(n_batches):
        start = i * batch_size
        end = min(start + batch_size, len(records))
        batch_records = records[start:end]
        batch_df = pd.DataFrame(batch_records, columns=BATCH_COLUMNS)
        batch_path = UNCLASSIFIED_SKILL_BATCHES_DIR / f"batch_{i + 1:03d}.csv"
        batch_df.to_csv(batch_path, index=False)

    total_fv = sum(r["total_fv"] for r in records[:n_batches * batch_size])
    logger.info("Generated %d batches (%d entities, $%.1fB FV) in %.1fs",
                n_batches, min(len(records), n_batches * batch_size),
                total_fv / 1e9, time.time() - t0)
    logger.info("Batches saved to %s", UNCLASSIFIED_SKILL_BATCHES_DIR)

    return n_batches


def show_stats() -> None:
    """Show current worklist statistics."""
    if not UNCLASSIFIED_SKILL_BATCHES_DIR.exists():
        logger.info("No batches directory found. Run without --stats first.")
        return

    batch_files = sorted(UNCLASSIFIED_SKILL_BATCHES_DIR.glob("batch_*.csv"))
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
        description="Generate UNCLASSIFIED skill worklist batches"
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
