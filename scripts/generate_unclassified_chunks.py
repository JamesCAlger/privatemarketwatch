"""Generate agent chunk files from unclassified_needs_review.csv.

Splits the needs-review entities into pipe-delimited text chunks for
parallel CC agent processing. Each chunk contains entity context
(financial signals, instrument type, identifier) that agents need to
determine asset-class classification.

Usage:
    python scripts/generate_unclassified_chunks.py                    # Generate all
    python scripts/generate_unclassified_chunks.py --chunk-size 50    # Custom size
    python scripts/generate_unclassified_chunks.py --range 0 10       # Range
    python scripts/generate_unclassified_chunks.py --stats            # Status
"""

import argparse
import logging
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd

from pipeline.config import UNCLASSIFIED_NEEDS_REVIEW_FILE

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("gen_unclassified_chunks")

OUTPUT_DIR = PROJECT_ROOT / "data" / "output"


def generate_chunks(chunk_size: int = 50, start: int = 0, end: int = 9999) -> int:
    """Generate agent chunk text files.

    Returns the number of chunks generated.
    """
    if not UNCLASSIFIED_NEEDS_REVIEW_FILE.exists():
        logger.error("Needs review file not found: %s", UNCLASSIFIED_NEEDS_REVIEW_FILE)
        return 0

    nr = pd.read_csv(UNCLASSIFIED_NEEDS_REVIEW_FILE, dtype=str)
    logger.info("Loaded %d entities from needs_review", len(nr))

    n_chunks = (len(nr) + chunk_size - 1) // chunk_size

    generated = 0
    for chunk in range(start, min(end + 1, n_chunks)):
        s = chunk * chunk_size
        e = min(s + chunk_size, len(nr))
        subset = nr.iloc[s:e]
        lines = []
        for _, row in subset.iterrows():
            name_norm = str(row.get("name_norm", ""))
            issuer_raw = str(row.get("issuer_name_raw", ""))
            source = str(row.get("source", ""))
            issuer_cat = str(row.get("issuer_category", ""))
            total_fv = str(row.get("total_fv", "0"))
            rate = str(row.get("sample_interest_rate", ""))
            shares = str(row.get("sample_shares_held", ""))
            instrument = str(row.get("sample_instrument", ""))[:150]
            identifier = str(row.get("sample_identifier", ""))[:150]
            lines.append(
                f"{name_norm}||{issuer_raw}||{source}||{issuer_cat}"
                f"||{total_fv}||{rate}||{shares}||{instrument}||{identifier}"
            )

        chunk_path = OUTPUT_DIR / f"unclassified_agent_chunk_{chunk:03d}.txt"
        chunk_path.write_text("\n".join(lines), encoding="utf-8")
        generated += 1

    logger.info("Generated %d chunk files (chunks %d-%d, %d entities each)",
                generated, start, min(end, n_chunks - 1), chunk_size)
    return generated


def show_stats() -> None:
    """Show which chunks have been processed."""
    chunk_files = sorted(OUTPUT_DIR.glob("unclassified_agent_chunk_*.txt"))
    result_files = sorted(OUTPUT_DIR.glob("unclassified_agent_results_*.csv"))

    result_nums = set()
    for f in result_files:
        try:
            num = int(f.stem.replace("unclassified_agent_results_", ""))
            result_nums.add(num)
        except ValueError:
            continue

    chunk_nums = set()
    for f in chunk_files:
        try:
            num = int(f.stem.replace("unclassified_agent_chunk_", ""))
            chunk_nums.add(num)
        except ValueError:
            continue

    logger.info("Chunk files: %d", len(chunk_nums))
    logger.info("Result files: %d", len(result_nums))
    done = chunk_nums & result_nums
    pending = chunk_nums - result_nums
    logger.info("Done: %d, Pending: %d", len(done), len(pending))
    if pending:
        pending_sorted = sorted(pending)
        logger.info("Next pending chunks: %s", pending_sorted[:20])

    # Count total entities in needs_review
    if UNCLASSIFIED_NEEDS_REVIEW_FILE.exists():
        nr = pd.read_csv(UNCLASSIFIED_NEEDS_REVIEW_FILE, dtype=str)
        total_fv = nr["total_fv"].astype(float).sum()
        logger.info("Total entities needing review: %d ($%.1fB FV)",
                     len(nr), total_fv / 1e9)


def main():
    parser = argparse.ArgumentParser(
        description="Generate agent chunk files for UNCLASSIFIED review"
    )
    parser.add_argument("--chunk-size", type=int, default=50)
    parser.add_argument("--range", nargs=2, type=int, default=None)
    parser.add_argument("--stats", action="store_true")
    args = parser.parse_args()

    if args.stats:
        show_stats()
    elif args.range:
        generate_chunks(chunk_size=args.chunk_size,
                        start=args.range[0], end=args.range[1])
    else:
        generate_chunks(chunk_size=args.chunk_size)


if __name__ == "__main__":
    main()
