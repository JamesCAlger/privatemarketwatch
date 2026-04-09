"""Rebuild all pipeline output files from cached/downloaded data.

This script regenerates all output CSVs that get overwritten by the test
suite. It does NOT download any new data from SEC EDGAR -- it only
rebuilds from existing cached files on disk.

Usage:
    python scripts/rebuild_outputs.py              # Rebuild everything
    python scripts/rebuild_outputs.py --unified     # Only unified holdings
    python scripts/rebuild_outputs.py --returns     # Only matching + returns
    python scripts/rebuild_outputs.py --income      # Only fund income + fee uplift
"""

import argparse
import logging
import sys
import time

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("rebuild")


def rebuild_unified():
    """Rebuild unified holdings from cached BDC + N-PORT data."""
    from pipeline.unified_holdings import build_unified_holdings

    logger.info("=== Rebuilding unified holdings ===")
    t0 = time.time()
    df = build_unified_holdings()
    logger.info("Unified holdings: %d rows in %.1f s", len(df), time.time() - t0)
    return df


def rebuild_income():
    """Rebuild fund income + fee uplift from cached XBRL."""
    from pipeline.bdc_fund_income import extract_bdc_fund_income
    from pipeline.fee_uplift import compute_fee_uplift

    logger.info("=== Rebuilding fund income ===")
    t0 = time.time()
    fund_income_df = extract_bdc_fund_income()
    logger.info("Fund income: %d rows in %.1f s", len(fund_income_df), time.time() - t0)

    logger.info("=== Rebuilding fee uplift ===")
    t1 = time.time()
    fee_uplift_df = compute_fee_uplift(fund_income_df=fund_income_df)
    logger.info("Fee uplift: %d rows in %.1f s", len(fee_uplift_df), time.time() - t1)

    return fund_income_df, fee_uplift_df


def rebuild_returns():
    """Rebuild position matches, position IDs, and index returns."""
    import pandas as pd

    from pipeline.index_returns import compute_returns
    from pipeline.position_matching import assign_position_ids, match_positions

    logger.info("=== Rebuilding position matches ===")
    t0 = time.time()
    matches_df = match_positions()
    logger.info("Matches: %d pairs in %.1f s", len(matches_df), time.time() - t0)

    logger.info("=== Assigning position IDs ===")
    t1 = time.time()
    unified_df = pd.read_csv("data/output/private_markets_holdings.csv", dtype=str)
    unified_df, matches_df = assign_position_ids(unified_df, matches_df)
    # Save unified holdings with position_ids populated
    unified_df.to_csv("data/output/private_markets_holdings.csv", index=False)
    # Save matches with position_ids populated
    matches_df.to_csv("data/output/position_matches.csv", index=False)
    logger.info("Position IDs assigned in %.1f s", time.time() - t1)

    logger.info("=== Rebuilding index returns ===")
    t2 = time.time()
    pos_df, idx_df = compute_returns()
    logger.info("Returns: %d position rows, %d index rows in %.1f s",
                len(pos_df), len(idx_df), time.time() - t2)

    return pos_df, idx_df


def rebuild_frontend():
    """Regenerate frontend JSON data from output CSVs."""
    from pipeline.export_frontend import export_all

    logger.info("=== Rebuilding frontend data ===")
    t0 = time.time()
    export_all()
    logger.info("Frontend export complete in %.1f s", time.time() - t0)


def main():
    parser = argparse.ArgumentParser(
        description="Rebuild pipeline outputs from cached data (no downloads)."
    )
    parser.add_argument("--unified", action="store_true",
                        help="Rebuild unified holdings only")
    parser.add_argument("--income", action="store_true",
                        help="Rebuild fund income + fee uplift only")
    parser.add_argument("--returns", action="store_true",
                        help="Rebuild position matches + index returns only")
    parser.add_argument("--frontend", action="store_true",
                        help="Rebuild frontend JSON data only")
    args = parser.parse_args()

    # If no flags, rebuild everything
    rebuild_all = not (args.unified or args.income or args.returns or args.frontend)

    t_start = time.time()

    if rebuild_all or args.unified:
        rebuild_unified()

    if rebuild_all or args.income:
        rebuild_income()

    if rebuild_all or args.returns:
        rebuild_returns()

    if rebuild_all or args.frontend:
        rebuild_frontend()

    total = time.time() - t_start
    logger.info("=== All rebuilds complete in %.1f s ===", total)


if __name__ == "__main__":
    main()
