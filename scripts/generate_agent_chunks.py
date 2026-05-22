"""Generate agent chunk files from needs_search CSV for batch GICS classification.

Usage:
    python scripts/generate_agent_chunks.py                    # Generate all chunks
    python scripts/generate_agent_chunks.py --range 0 51       # Generate chunks 0-51
    python scripts/generate_agent_chunks.py --chunk-size 50    # Custom chunk size
    python scripts/generate_agent_chunks.py --stats            # Show chunk status
"""

import argparse
import logging
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("gen_chunks")

OUTPUT_DIR = PROJECT_ROOT / "data" / "output"


def generate_chunks(chunk_size: int = 50, start: int = 0, end: int = 9999) -> int:
    """Generate agent chunk text files."""
    ns_path = OUTPUT_DIR / "gics_needs_search_sorted.csv"
    if not ns_path.exists():
        logger.error("Sorted needs_search file not found: %s", ns_path)
        return 0

    ns = pd.read_csv(ns_path, dtype=str)
    n_chunks = (len(ns) + chunk_size - 1) // chunk_size

    generated = 0
    for chunk in range(start, min(end + 1, n_chunks)):
        s = chunk * chunk_size
        e = min(s + chunk_size, len(ns))
        subset = ns.iloc[s:e]
        lines = []
        for _, row in subset.iterrows():
            nn = str(row['name_norm'])
            sn = str(row['search_name'])
            si = str(row.get('sample_identifier', ''))[:150]
            fv = float(row.get('total_fv', 0))
            lines.append(f'{nn}||{sn}||{fv:.0f}||{si}')

        chunk_path = OUTPUT_DIR / f"gics_agent_chunk_{chunk:03d}.txt"
        chunk_path.write_text('\n'.join(lines), encoding='utf-8')
        generated += 1

    logger.info("Generated %d chunk files (chunks %d-%d, %d entities each)",
                generated, start, min(end, n_chunks - 1), chunk_size)
    return generated


def show_stats() -> None:
    """Show which chunks have been processed."""
    chunk_files = sorted(OUTPUT_DIR.glob("gics_agent_chunk_*.txt"))
    result_files = sorted(OUTPUT_DIR.glob("gics_agent_results_*.csv"))

    result_nums = set()
    for f in result_files:
        try:
            num = int(f.stem.replace("gics_agent_results_", ""))
            result_nums.add(num)
        except ValueError:
            continue

    chunk_nums = set()
    for f in chunk_files:
        try:
            num = int(f.stem.replace("gics_agent_chunk_", ""))
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


def main():
    parser = argparse.ArgumentParser(description="Generate agent chunk files")
    parser.add_argument("--chunk-size", type=int, default=50)
    parser.add_argument("--range", nargs=2, type=int, default=None)
    parser.add_argument("--stats", action="store_true")
    args = parser.parse_args()

    if args.stats:
        show_stats()
    elif args.range:
        generate_chunks(chunk_size=args.chunk_size, start=args.range[0], end=args.range[1])
    else:
        generate_chunks(chunk_size=args.chunk_size)


if __name__ == "__main__":
    main()
