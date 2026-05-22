"""Backfill investment_identifier onto aggregate_header_flags.csv.

The agent chunks wrote AGGREGATE_HEADER verdicts keyed by name_norm
(the _normalize_company_name() output), but the staging join needs to
match against the raw investment_identifier from bdc_holdings.csv.

This script:
1. Loads aggregate_header_flags.csv
2. Builds a reverse lookup: normalize(lower(investment_identifier)) -> [identifiers]
3. For each AGGREGATE_HEADER flag, finds matching raw identifiers
4. Writes the raw identifier back as a new column (identifier_raw)
5. Reports stats on matched vs unmatched flags

The updated flags file can then be joined on identifier_raw in staging_bdc.py
for exact matching against _lower_id, avoiding the lossy normalization mismatch.

Usage:
    python scripts/backfill_aggregate_flag_identifiers.py
    python scripts/backfill_aggregate_flag_identifiers.py --dry-run
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from pipeline.config import AGGREGATE_HEADER_FLAGS_FILE, OUTPUT_DIR
from pipeline.gics_classification import _normalize_company_name

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

BDC_HOLDINGS_FILE = OUTPUT_DIR / "bdc_holdings.csv"


def backfill(dry_run: bool = False) -> None:
    """Backfill identifier_raw onto aggregate header flags."""
    if not AGGREGATE_HEADER_FLAGS_FILE.exists():
        logger.info("No aggregate_header_flags.csv found -- nothing to do.")
        return

    if not BDC_HOLDINGS_FILE.exists():
        logger.error("bdc_holdings.csv not found at %s", BDC_HOLDINGS_FILE)
        return

    # Load flags
    flags = pd.read_csv(AGGREGATE_HEADER_FLAGS_FILE, dtype=str)
    agg_mask = flags["verdict"] == "AGGREGATE_HEADER"
    n_agg = agg_mask.sum()
    logger.info("Loaded %d flags (%d AGGREGATE_HEADER)", len(flags), n_agg)

    # Build reverse lookup from bdc_holdings:
    # normalize(lower(investment_identifier)) -> set of lower(investment_identifier)
    logger.info("Building reverse lookup from bdc_holdings.csv ...")
    bdc = pd.read_csv(
        BDC_HOLDINGS_FILE,
        dtype=str,
        usecols=["investment_identifier"],
    )
    raw_ids = bdc["investment_identifier"].dropna().unique()
    logger.info("  %d unique investment_identifiers", len(raw_ids))

    norm_to_raw: dict[str, set[str]] = {}
    for rid in raw_ids:
        lower = rid.lower().strip()
        norm = _normalize_company_name(lower)
        if norm:
            if norm not in norm_to_raw:
                norm_to_raw[norm] = set()
            norm_to_raw[norm].add(lower)

    logger.info("  %d unique normalized keys in reverse lookup", len(norm_to_raw))

    # Match each AGGREGATE_HEADER flag to raw identifiers
    matched = 0
    unmatched = 0
    multi_match = 0
    identifier_raws = []

    for idx, row in flags.iterrows():
        if row["verdict"] != "AGGREGATE_HEADER":
            identifier_raws.append("")
            continue

        name_norm = str(row["name_norm"]).strip()
        raw_set = norm_to_raw.get(name_norm, set())

        if not raw_set:
            identifier_raws.append("")
            unmatched += 1
        elif len(raw_set) == 1:
            identifier_raws.append(next(iter(raw_set)))
            matched += 1
        else:
            # Multiple raw identifiers normalize to this key.
            # Store all of them pipe-delimited for inspection.
            identifier_raws.append("|||".join(sorted(raw_set)))
            matched += 1
            multi_match += 1

    flags["identifier_raw"] = identifier_raws

    logger.info("Results:")
    logger.info("  Matched:     %d / %d", matched, n_agg)
    logger.info("  Unmatched:   %d / %d", unmatched, n_agg)
    logger.info("  Multi-match: %d (multiple raw identifiers per key)", multi_match)

    if dry_run:
        logger.info("Dry run -- not writing changes.")
        # Show some examples
        agg_flags = flags[agg_mask]
        has_raw = agg_flags[agg_flags["identifier_raw"] != ""]
        logger.info("Sample matched entries:")
        for _, r in has_raw.head(10).iterrows():
            raw = str(r["identifier_raw"])
            if len(raw) > 100:
                raw = raw[:100] + "..."
            logger.info("  name_norm: %s", str(r["name_norm"])[:60])
            logger.info("  raw:       %s", raw)
            logger.info("")
        return

    # Write updated flags
    flags.to_csv(AGGREGATE_HEADER_FLAGS_FILE, index=False)
    logger.info("Wrote updated flags to %s", AGGREGATE_HEADER_FLAGS_FILE)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Backfill identifier_raw onto aggregate header flags"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would change without writing",
    )
    args = parser.parse_args()
    backfill(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
