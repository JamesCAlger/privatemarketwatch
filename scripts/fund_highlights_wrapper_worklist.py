"""Priority worklist for fund highlights wrapper authoring.

Reads the residual profiler output, filters to wrapper-actionable CIKs,
excludes those with existing wrapper JSON, and presents the queue.

Usage:
    python scripts/fund_highlights_wrapper_worklist.py --list
    python scripts/fund_highlights_wrapper_worklist.py --next
    python scripts/fund_highlights_wrapper_worklist.py --stats
    python scripts/fund_highlights_wrapper_worklist.py --done 0001280784
"""

import argparse
import logging
import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pipeline.config import (
    FUND_HIGHLIGHTS_RESIDUAL_PROFILE_FILE,
    FUND_HIGHLIGHTS_WRAPPER_DIR,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("highlights_worklist")


def _normalize_cik(cik: str) -> str:
    return str(cik).strip().zfill(10)


def _existing_wrappers() -> set[str]:
    """Return set of CIKs (10-digit) that already have a wrapper JSON."""
    if not FUND_HIGHLIGHTS_WRAPPER_DIR.exists():
        return set()
    wrappers = set()
    for path in FUND_HIGHLIGHTS_WRAPPER_DIR.glob("*.json"):
        stem = path.stem
        if stem.isdigit():
            wrappers.add(stem.zfill(10))
    return wrappers


def load_worklist() -> pd.DataFrame:
    """Load and filter the residual profiler output to wrapper-actionable CIKs."""
    if not FUND_HIGHLIGHTS_RESIDUAL_PROFILE_FILE.exists():
        logger.error(
            "Residual profile not found: %s\n"
            "Run: python scripts/rebuild_outputs.py --highlights-residual",
            FUND_HIGHLIGHTS_RESIDUAL_PROFILE_FILE,
        )
        return pd.DataFrame()

    df = pd.read_csv(FUND_HIGHLIGHTS_RESIDUAL_PROFILE_FILE, dtype=str)

    # Filter to wrapper-actionable
    if "wrapper_actionable" not in df.columns:
        logger.error("residual profile missing 'wrapper_actionable' column")
        return pd.DataFrame()

    df["wrapper_actionable"] = df["wrapper_actionable"].apply(
        lambda x: str(x).strip().lower() in ("true", "1", "yes")
    )
    df = df[df["wrapper_actionable"]].copy()

    # Normalize CIK
    df["cik"] = df["cik"].apply(_normalize_cik)

    # Exclude CIKs with existing wrappers
    existing = _existing_wrappers()
    df = df[~df["cik"].isin(existing)].copy()

    # Convert numeric columns for sorting
    for col in ["quarters_with_data", "fail_rate", "total_rows"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)

    # Sort: concept_mapping_gap first (by quarters desc), then multi_class_asymmetry
    category_priority = {
        "concept_mapping_gap": 0,
        "scale_mismatch": 1,
        "multi_class_asymmetry": 2,
    }
    if "dominant_category" in df.columns:
        df["_cat_rank"] = df["dominant_category"].map(category_priority).fillna(9)
    else:
        df["_cat_rank"] = 9

    df = df.sort_values(
        ["_cat_rank", "quarters_with_data"],
        ascending=[True, False],
    ).drop(columns=["_cat_rank"])

    return df


def cmd_list(limit: int = 50) -> None:
    """Print the worklist."""
    df = load_worklist()
    if df.empty:
        print("Worklist is empty (all wrapper-actionable CIKs have wrappers or profiler not run)")
        return

    display_cols = [
        c for c in ["cik", "entity_name", "dominant_category", "quarters_with_data",
                     "fail_rate", "total_rows"]
        if c in df.columns
    ]
    print(f"\nFund highlights wrapper worklist ({len(df)} remaining):\n")
    print(df[display_cols].head(limit).to_string(index=False))


def cmd_next() -> None:
    """Print the next CIK to work on."""
    df = load_worklist()
    if df.empty:
        print("No remaining wrapper-actionable CIKs")
        return

    row = df.iloc[0]
    cik = row["cik"]
    name = row.get("entity_name", "")
    cat = row.get("dominant_category", "")
    quarters = row.get("quarters_with_data", "")
    print(f"\nNext CIK: {cik}  {name}")
    print(f"  Category: {cat}")
    print(f"  Quarters with data: {quarters}")
    print(f"\nTo profile:")
    print(f"  /highlights-wrapper {cik} profile")


def cmd_stats() -> None:
    """Print worklist statistics."""
    df = load_worklist()
    existing = _existing_wrappers()

    if not FUND_HIGHLIGHTS_RESIDUAL_PROFILE_FILE.exists():
        print("Residual profiler not run yet")
        return

    full_df = pd.read_csv(FUND_HIGHLIGHTS_RESIDUAL_PROFILE_FILE, dtype=str)
    full_df["wrapper_actionable"] = full_df["wrapper_actionable"].apply(
        lambda x: str(x).strip().lower() in ("true", "1", "yes")
    )
    total_actionable = full_df["wrapper_actionable"].sum()

    print(f"\nFund highlights wrapper stats:")
    print(f"  Total wrapper-actionable CIKs: {total_actionable}")
    print(f"  Existing wrappers: {len(existing)}")
    print(f"  Remaining: {len(df)}")

    if "dominant_category" in df.columns and not df.empty:
        print(f"\n  Remaining by category:")
        for cat, count in df["dominant_category"].value_counts().items():
            print(f"    {cat}: {count}")


def cmd_done(cik: str) -> None:
    """Verify a CIK has a wrapper file."""
    cik = _normalize_cik(cik)
    wrapper_path = FUND_HIGHLIGHTS_WRAPPER_DIR / f"{cik}.json"
    if wrapper_path.exists():
        print(f"Wrapper exists for {cik}: {wrapper_path}")
    else:
        print(f"No wrapper found at {wrapper_path}")


def main():
    parser = argparse.ArgumentParser(description="Fund highlights wrapper worklist")
    parser.add_argument("--list", action="store_true", help="Show the full worklist")
    parser.add_argument("--next", action="store_true", help="Show the next CIK to work on")
    parser.add_argument("--stats", action="store_true", help="Show worklist statistics")
    parser.add_argument("--done", type=str, help="Verify wrapper exists for a CIK")
    parser.add_argument("--limit", type=int, default=50, help="Limit for --list output")
    args = parser.parse_args()

    if args.done:
        cmd_done(args.done)
    elif args.next:
        cmd_next()
    elif args.stats:
        cmd_stats()
    elif args.list:
        cmd_list(args.limit)
    else:
        cmd_stats()


if __name__ == "__main__":
    main()
