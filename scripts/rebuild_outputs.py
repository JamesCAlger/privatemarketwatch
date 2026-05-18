"""Rebuild all pipeline output files from cached/downloaded data.

This script regenerates all output CSVs that get overwritten by the test
suite. It does NOT download any new data from SEC EDGAR -- it only
rebuilds from existing cached files on disk.

Usage:
    python scripts/rebuild_outputs.py              # Rebuild everything
    python scripts/rebuild_outputs.py --unified     # Only unified holdings
    python scripts/rebuild_outputs.py --returns     # Only matching + returns
    python scripts/rebuild_outputs.py --income      # Only fund income + fee uplift
    python scripts/rebuild_outputs.py --html        # Only HTML template extraction ($0)
"""

import argparse
import logging
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

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


def rebuild_ncsr():
    """Rebuild N-CSR financials from cached HTML files."""
    from pipeline.ncsr_financials import extract_ncsr_financials

    logger.info("=== Rebuilding N-CSR financials ===")
    t0 = time.time()
    df = extract_ncsr_financials()
    logger.info("N-CSR financials: %d rows in %.1f s", len(df), time.time() - t0)
    return df


def rebuild_financials(
    refresh_ncsr: bool = False,
    include_sector_breakdown: bool = False,
):
    """Rebuild fund financials from cached companyfacts + N-PORT fund info."""
    from pipeline.fund_financials import build_fund_financials
    from pipeline.config import NCSR_FINANCIALS_FILE

    # Full N-CSR HTML parsing is intentionally opt-in; it is serial over
    # thousands of cached filings and can take over an hour on Windows.
    if refresh_ncsr or not NCSR_FINANCIALS_FILE.exists():
        rebuild_ncsr()
    else:
        logger.info(
            "=== Reusing cached N-CSR financials (%s); pass --refresh-ncsr to reparse HTML ===",
            NCSR_FINANCIALS_FILE,
        )

    logger.info("=== Rebuilding fund financials ===")
    t0 = time.time()
    df = build_fund_financials()  # No client = cache-only, no downloads
    logger.info("Fund financials: %d rows in %.1f s", len(df), time.time() - t0)

    if include_sector_breakdown:
        from pipeline.bdc_sector_breakdown import extract_bdc_sector_breakdown

        logger.info("=== Rebuilding BDC sector breakdown ===")
        t1 = time.time()
        sector_df = extract_bdc_sector_breakdown()
        logger.info("Sector breakdown: %d rows in %.1f s",
                    len(sector_df), time.time() - t1)
    else:
        logger.info(
            "=== Skipping BDC sector breakdown; pass --sector-breakdown to rebuild it ==="
        )

    return df


def rebuild_html():
    """Re-run HTML template extraction (Phase 2 only, $0)."""
    from pipeline.html_extract import extract_all_html

    logger.info("=== Rebuilding HTML template extractions ===")
    t0 = time.time()
    df = extract_all_html()
    rows = len(df) if not df.empty else 0
    logger.info("HTML extractions: %d rows in %.1f s", rows, time.time() - t0)
    return df


def rebuild_gics():
    """Run GICS industry classification on unified holdings."""
    from pipeline.gics_classification import classify_gics

    logger.info("=== Running GICS classification ===")
    t0 = time.time()
    df = classify_gics()
    classified = (df["gics_sub_industry"] != "").sum()
    logger.info("GICS classification: %d/%d rows classified in %.1f s",
                classified, len(df), time.time() - t0)
    return df


def rebuild_frontend():
    """Regenerate frontend JSON data from output CSVs."""
    from pipeline.export_frontend import export_all

    logger.info("=== Rebuilding frontend data ===")
    t0 = time.time()
    export_all()
    logger.info("Frontend export complete in %.1f s", time.time() - t0)


def run_validation_rules(categories: list[str] | None = None):
    """Run report-only V1 validation rules against cached output CSVs."""
    from pipeline.validation_rules import run_all

    logger.info("=== Running validation rules ===")
    t0 = time.time()
    aggregate_df, detail_df = run_all(categories=categories)
    logger.info(
        "Validation rules: %d aggregate rows, %d detail rows in %.1f s",
        len(aggregate_df),
        len(detail_df),
        time.time() - t0,
    )
    return aggregate_df, detail_df


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
    parser.add_argument("--html", action="store_true",
                        help="Rebuild HTML template extractions only ($0)")
    parser.add_argument("--financials", action="store_true",
                        help="Rebuild fund financials only (cache-only)")
    parser.add_argument("--refresh-ncsr", action="store_true",
                        help="With --financials/all, reparse cached N-CSR HTML before rebuilding fund financials")
    parser.add_argument("--sector-breakdown", action="store_true",
                        help="With --financials/all, rebuild BDC sector breakdown")
    parser.add_argument("--gics", action="store_true",
                        help="Run GICS industry classification only")
    parser.add_argument("--frontend", action="store_true",
                        help="Rebuild frontend JSON data only")
    parser.add_argument("--validate-rules", action="store_true",
                        help="Run report-only V1 validation rules against cached outputs")
    parser.add_argument("--rules-category", nargs="+", choices=["PC", "IDX"],
                        help="Limit --validate-rules to one or more rule categories")
    args = parser.parse_args()

    # If no flags, rebuild everything
    rebuild_all = not (
        args.unified or args.income or args.returns
        or args.html or args.frontend or args.financials or args.gics
        or args.validate_rules
    )

    t_start = time.time()

    if rebuild_all or args.unified:
        rebuild_unified()

    if rebuild_all or args.income:
        rebuild_income()

    if rebuild_all or args.financials:
        rebuild_financials(
            refresh_ncsr=args.refresh_ncsr,
            include_sector_breakdown=args.sector_breakdown,
        )

    if rebuild_all or args.returns:
        rebuild_returns()

    if args.html:
        rebuild_html()

    if args.gics:
        rebuild_gics()

    if rebuild_all or args.frontend:
        rebuild_frontend()

    if args.validate_rules:
        run_validation_rules(categories=args.rules_category)

    total = time.time() - t_start
    logger.info("=== All rebuilds complete in %.1f s ===", total)


if __name__ == "__main__":
    main()
