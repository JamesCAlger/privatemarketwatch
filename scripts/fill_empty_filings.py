"""Fill in empty-table filings in existing v3.0 templates.

For each template, finds filings with tables=[] and runs auto-detect scoring
to find SOI tables. Merges results into the existing template without touching
already-mapped filings.

Usage:
    python scripts/fill_empty_filings.py              # Process all CIKs
    python scripts/fill_empty_filings.py --cik 1280784  # Single CIK
    python scripts/fill_empty_filings.py --dry-run     # Show changes without writing
"""

import argparse
import json
import os
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.learn_template import (
    _score_table_soi,
    _group_continuation_tables,
    _detect_periods_from_html,
    _detect_10k_periods,
    _load_grids,
    _load_filings_index,
    _scan_tables,
    prepare_cik,
)
from pipeline.config import BDC_HTML_CACHE_DIR

import pandas as pd


def _acc_to_nodashes(acc: str) -> str:
    return acc.replace("-", "")


def _acc_to_dashed(acc_nodashes: str) -> str:
    return f"{acc_nodashes[:10]}-{acc_nodashes[10:12]}-{acc_nodashes[12:]}"


def fill_empty_filings_for_cik(
    cik: str,
    template: dict,
    idx: pd.DataFrame,
    dry_run: bool = False,
    include_amendments: bool = False,
) -> dict:
    """Find SOI tables for empty-table filings and update the template.

    Returns dict with stats: {filled, skipped_no_grids, skipped_no_soi, already_covered, total_empty}
    """
    cik_stripped = cik.lstrip("0")
    cache_dir = BDC_HTML_CACHE_DIR / cik_stripped

    default_tables = template.get("default", {}).get("tables", [])
    filings_ovr = template.setdefault("filings", {})

    # Get filing metadata
    cik_filings = idx[idx["cik"].str.lstrip("0") == cik_stripped].copy()

    # Find all HTML files
    html_dir = cache_dir
    if not html_dir.exists():
        return {"filled": 0, "skipped_no_grids": 0, "skipped_no_soi": 0,
                "already_covered": 0, "total_empty": 0}

    html_files = sorted(html_dir.glob("*.html"))

    stats = {"filled": 0, "skipped_no_grids": 0, "skipped_no_soi": 0,
             "already_covered": 0, "total_empty": 0}

    for hf in html_files:
        acc_nodashes = hf.stem
        acc_dashed = _acc_to_dashed(acc_nodashes)

        # Check if this filing already has tables
        override = filings_ovr.get(acc_dashed, {})
        tables = override.get("tables", default_tables)
        if tables:
            stats["already_covered"] += 1
            continue

        # Get filing metadata
        row = cik_filings[cik_filings["accession_number"] == acc_dashed]
        if row.empty:
            # Try matching without the CIK padding
            continue

        form_type = row.iloc[0].get("form_type", "")
        report_date = row.iloc[0].get("report_date", "")

        # Skip amendments unless requested
        if not include_amendments and form_type in ("10-K/A", "10-Q/A"):
            continue

        stats["total_empty"] += 1

        # Load grids -- generate if missing
        grids = _load_grids(cik_stripped, acc_nodashes)
        if not grids:
            html_path = cache_dir / f"{acc_nodashes}.html"
            if html_path.exists():
                _scan_tables(html_path, cik=cik_stripped)
                grids = _load_grids(cik_stripped, acc_nodashes)
        if not grids:
            stats["skipped_no_grids"] += 1
            continue

        # Score each table
        scored = []
        for t in grids:
            tidx = t["index"]
            grid = t["grid"]
            score, hr = _score_table_soi(grid)
            if score >= 8:
                scored.append((tidx, score, t["width"], hr))

        # Group continuation tables (score >= 10)
        high_scored = [(t, s, w, h) for t, s, w, h in scored if s >= 10]
        groups = _group_continuation_tables(high_scored)

        if not groups:
            stats["skipped_no_soi"] += 1
            continue

        # Select best group(s) - same logic as auto_detect_cik
        group_info = []
        for gi, group in enumerate(groups):
            total_rows = 0
            for tidx in group:
                for t in grids:
                    if t["index"] == tidx:
                        total_rows += t["rows"]
                        break
            group_info.append((gi, len(group), total_rows, group[0]))

        # For 10-K: take the two largest groups (current + comparative)
        if "10-K" in form_type and len(group_info) >= 2:
            by_size = sorted(group_info, key=lambda x: (-x[1], -x[2]))
            selected_groups = [
                groups[by_size[0][0]],
                groups[by_size[1][0]],
            ]
            selected_groups.sort(key=lambda g: g[0])
        elif group_info:
            first_gi = min(group_info, key=lambda x: x[3])
            if first_gi[1] >= 2:
                selected_groups = [groups[first_gi[0]]]
            else:
                best_gi = max(group_info, key=lambda x: (x[1], -x[3]))[0]
                selected_groups = [groups[best_gi]]
        else:
            selected_groups = []

        all_selected = [t for g in selected_groups for t in g]
        if not all_selected:
            stats["skipped_no_soi"] += 1
            continue

        # Detect comparative periods
        table_periods = None
        html_path = cache_dir / f"{acc_nodashes}.html"
        if html_path.exists() and len(all_selected) >= 2:
            table_periods = _detect_periods_from_html(
                html_path, all_selected, report_date,
            )
        if table_periods is None and "10-K" in form_type and len(selected_groups) == 2:
            table_periods = _detect_10k_periods(selected_groups, report_date)

        # Build override entry
        new_override = {"tables": all_selected}
        if table_periods:
            new_override["table_periods"] = table_periods

        # Merge into existing override (preserve any existing keys like columns)
        if acc_dashed in filings_ovr:
            filings_ovr[acc_dashed].update(new_override)
        else:
            filings_ovr[acc_dashed] = new_override

        stats["filled"] += 1

    return stats


def main():
    parser = argparse.ArgumentParser(description="Fill empty-table filings in templates")
    parser.add_argument("--cik", help="Process single CIK")
    parser.add_argument("--dry-run", action="store_true", help="Show changes without writing")
    parser.add_argument("--include-amendments", action="store_true",
                        help="Also process 10-K/A and 10-Q/A filings")
    args = parser.parse_args()

    template_dir = Path("data/raw/filing_templates")
    idx = _load_filings_index()

    if args.cik:
        cik = args.cik.lstrip("0")
        template_path = template_dir / f"{cik}.json"
        if not template_path.exists():
            print(f"No template found for CIK {cik}")
            return
        templates_to_process = [(cik, template_path)]
    else:
        templates_to_process = []
        for tp in sorted(template_dir.glob("*.json")):
            cik = tp.stem
            templates_to_process.append((cik, tp))

    total_filled = 0
    total_no_soi = 0
    total_no_grids = 0
    total_empty = 0
    modified_ciks = []

    for cik, tp in templates_to_process:
        with open(tp) as f:
            template = json.load(f)

        if template.get("version") != "3.0":
            continue

        result = fill_empty_filings_for_cik(
            cik, template, idx,
            dry_run=args.dry_run,
            include_amendments=args.include_amendments,
        )

        if result["filled"] > 0:
            modified_ciks.append(cik)
            if not args.dry_run:
                with open(tp, "w") as f:
                    json.dump(template, f, indent=2)
                    f.write("\n")

        total_filled += result["filled"]
        total_no_soi += result["skipped_no_soi"]
        total_no_grids += result["skipped_no_grids"]
        total_empty += result["total_empty"]

        if result["total_empty"] > 0:
            print(f"  CIK {cik:>10}: "
                  f"{result['filled']:>3} filled, "
                  f"{result['skipped_no_soi']:>3} no_soi, "
                  f"{result['skipped_no_grids']:>3} no_grids "
                  f"(of {result['total_empty']} empty)")

    print(f"\n{'DRY RUN - ' if args.dry_run else ''}Summary:")
    print(f"  Total empty filings processed: {total_empty}")
    print(f"  Filled with SOI tables: {total_filled}")
    print(f"  No SOI found: {total_no_soi}")
    print(f"  No grids available: {total_no_grids}")
    print(f"  Modified CIKs: {len(modified_ciks)}")

    if modified_ciks:
        print(f"\nModified CIKs: {', '.join(modified_ciks)}")


if __name__ == "__main__":
    main()
