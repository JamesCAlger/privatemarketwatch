"""One-CIK trial rebuild for fund highlights wrapper development.

Extracts fund highlights for a single CIK, runs the oracle, and compares
identity pass rates before and after the wrapper takes effect.

Usage:
    python scripts/rebuild_highlights_cik_trial.py --cik 0001280784
    python scripts/rebuild_highlights_cik_trial.py --cik 0001280784 --no-wrapper
"""

import argparse
import logging
import sys
import time
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("highlights_trial")

TRIAL_OUTPUT_DIR = PROJECT_ROOT / "data" / "output" / "fund_highlights_wrapper_trial"


def _normalize_cik(cik: str) -> str:
    return cik.strip().zfill(10)


def run_trial(cik: str, no_wrapper: bool = False) -> None:
    """Run a single-CIK highlights trial."""
    from pipeline.config import BDC_FILINGS_INDEX_FILE
    from pipeline.bdc_fund_highlights import extract_bdc_fund_highlights
    from pipeline.bdc_fund_highlights_oracle import run_highlights_oracle
    from pipeline.fund_highlights_wrapper import invalidate_cache

    cik = _normalize_cik(cik)
    logger.info("=== Fund highlights trial for CIK %s ===", cik)

    # Optionally disable wrapper for before/after comparison
    if no_wrapper:
        logger.info("Wrapper disabled for this trial (--no-wrapper)")
        invalidate_cache()
        # Temporarily override the loader to return None
        import pipeline.fund_highlights_wrapper as fhw
        orig_load = fhw.load_highlights_wrapper
        fhw.load_highlights_wrapper = lambda *a, **kw: None
    else:
        invalidate_cache()

    t0 = time.time()

    # Load filings index and filter to target CIK
    if not BDC_FILINGS_INDEX_FILE.exists():
        logger.error("Filings index not found: %s", BDC_FILINGS_INDEX_FILE)
        sys.exit(1)

    filings = pd.read_csv(BDC_FILINGS_INDEX_FILE, dtype=str)
    cik_filings = filings[filings["cik"].apply(_normalize_cik) == cik].copy()
    logger.info("Found %d filings for CIK %s", len(cik_filings), cik)

    if cik_filings.empty:
        logger.error("No filings for CIK %s", cik)
        if no_wrapper:
            import pipeline.fund_highlights_wrapper as fhw
            fhw.load_highlights_wrapper = orig_load
        sys.exit(1)

    # Extract highlights for this CIK only
    highlights = extract_bdc_fund_highlights(filings_index=cik_filings)
    n_highlights = len(highlights)
    logger.info("Extracted %d highlights rows", n_highlights)

    if highlights.empty:
        logger.warning("No highlights extracted for CIK %s", cik)
        if no_wrapper:
            import pipeline.fund_highlights_wrapper as fhw
            fhw.load_highlights_wrapper = orig_load
        return

    # Run oracle on the trial output
    oracle = run_highlights_oracle(highlights_df=highlights)
    n_oracle = len(oracle)

    # Restore wrapper loader if disabled
    if no_wrapper:
        import pipeline.fund_highlights_wrapper as fhw
        fhw.load_highlights_wrapper = orig_load

    # Save trial outputs
    trial_dir = TRIAL_OUTPUT_DIR / cik
    trial_dir.mkdir(parents=True, exist_ok=True)

    suffix = "_no_wrapper" if no_wrapper else ""
    highlights.to_csv(trial_dir / f"highlights{suffix}.csv", index=False)
    oracle.to_csv(trial_dir / f"oracle{suffix}.csv", index=False)

    # Print summary
    n_pass = (oracle["oracle_status"] == "pass").sum()
    n_fail = (oracle["oracle_status"] == "fail").sum()
    n_review = (oracle["oracle_status"] == "review_required").sum()

    # Identity check pass rates
    nav_id = pd.to_numeric(oracle["nav_identity_pct_diff"], errors="coerce")
    nav_testable = nav_id.notna().sum()
    nav_pass = (nav_id <= 0.02).sum() if nav_testable else 0

    inc_id = pd.to_numeric(oracle["income_identity_pct_diff"], errors="coerce")
    inc_testable = inc_id.notna().sum()
    inc_pass = (inc_id <= 0.05).sum() if inc_testable else 0

    wrapper_label = "WITHOUT wrapper" if no_wrapper else "WITH wrapper"
    logger.info("--- Trial results (%s) ---", wrapper_label)
    logger.info("  Rows: %d highlights, %d oracle", n_highlights, n_oracle)
    logger.info("  Verdicts: %d pass, %d review, %d fail", n_pass, n_review, n_fail)
    logger.info(
        "  NAV identity: %d/%d pass (%.0f%%)",
        nav_pass, nav_testable,
        100 * nav_pass / nav_testable if nav_testable else 0,
    )
    logger.info(
        "  Income identity: %d/%d pass (%.0f%%)",
        inc_pass, inc_testable,
        100 * inc_pass / inc_testable if inc_testable else 0,
    )
    logger.info("  Output: %s", trial_dir)

    elapsed = time.time() - t0
    logger.info("Trial complete in %.1f s", elapsed)


def main():
    parser = argparse.ArgumentParser(description="Single-CIK fund highlights trial rebuild")
    parser.add_argument("--cik", required=True, help="CIK to trial (zero-padded or bare)")
    parser.add_argument("--no-wrapper", action="store_true",
                        help="Run without wrapper (baseline comparison)")
    args = parser.parse_args()
    run_trial(args.cik, no_wrapper=args.no_wrapper)


if __name__ == "__main__":
    main()
