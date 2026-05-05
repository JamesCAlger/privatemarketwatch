"""Fix newly-added 10-K filings that are missing table_periods.

For each template, finds 10-K filings that:
1. Were recently added by fill_empty_filings.py (have tables but no table_periods)
2. Have enough tables to likely include comparative periods

Attempts to split them using:
1. HTML-based "Schedule of Investments" date marker detection
2. Grid-based date text scanning in first rows of tables
3. Midpoint heuristic (split tables in half if roughly 2x expected count)

Usage:
    python scripts/fix_10k_periods.py              # Process all CIKs
    python scripts/fix_10k_periods.py --cik 1280784  # Single CIK
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.learn_template import (
    _detect_periods_from_html,
    _detect_10k_periods,
    _load_grids,
    _load_filings_index,
    _group_continuation_tables,
)
from pipeline.config import BDC_HTML_CACHE_DIR

import pandas as pd

_DATE_RE = re.compile(
    r'(?:january|february|march|april|may|june|july|august|september|'
    r'october|november|december)\s+\d{1,2}\s*,?\s*\d{4}',
    re.IGNORECASE,
)
_DATE_YMD_RE = re.compile(r'(\d{4})-(\d{2})-(\d{2})')
_MONTH_MAP = {
    'january': '01', 'february': '02', 'march': '03', 'april': '04',
    'may': '05', 'june': '06', 'july': '07', 'august': '08',
    'september': '09', 'october': '10', 'november': '11', 'december': '12',
}


def _parse_date_text(text: str) -> str | None:
    """Parse 'March 31, 2023' -> '2023-03-31'."""
    text = text.strip().lower()
    for month_name, month_num in _MONTH_MAP.items():
        if month_name in text:
            # Extract year and day
            parts = re.findall(r'\d+', text)
            if len(parts) >= 2:
                day = parts[0].zfill(2)
                year = parts[1] if len(parts[1]) == 4 else parts[-1]
                if len(year) == 4:
                    return f"{year}-{month_num}-{day}"
    return None


def _scan_grids_for_periods(
    cik: str,
    acc_nodashes: str,
    table_indices: list[int],
) -> dict[str, list[int]] | None:
    """Scan table grids for date text to split into periods.

    Looks at first 2 rows of each table in the SOI range for date text
    like "December 31, 2023" or "Schedule of Investments".
    """
    grids = _load_grids(cik, acc_nodashes)
    if not grids:
        return None

    grid_by_idx = {t["index"]: t["grid"] for t in grids}

    # Find all date markers in SOI tables
    markers: list[tuple[int, str]] = []  # (table_idx, date_str)
    for tidx in sorted(table_indices):
        grid = grid_by_idx.get(tidx)
        if not grid:
            continue
        # Check first 3 rows for date text
        for row_i in range(min(3, len(grid))):
            row_text = " ".join(c for c in grid[row_i] if c.strip())
            for m in _DATE_RE.finditer(row_text):
                date = _parse_date_text(m.group())
                if date:
                    markers.append((tidx, date))
                    break
            if markers and markers[-1][0] == tidx:
                break

    if not markers:
        return None

    # Need at least 2 distinct dates
    distinct_dates = set(d for _, d in markers)
    if len(distinct_dates) < 2:
        return None

    # Assign each table to the most recent preceding date marker
    periods: dict[str, list[int]] = {}
    for tidx in sorted(table_indices):
        assigned_date = None
        for marker_tidx, marker_date in markers:
            if marker_tidx <= tidx:
                assigned_date = marker_date
            else:
                break
        if assigned_date is None and markers:
            assigned_date = markers[0][1]
        if assigned_date:
            periods.setdefault(assigned_date, []).append(tidx)

    if len(periods) < 2:
        return None

    return periods


def _midpoint_split(
    table_indices: list[int],
    report_date: str,
) -> dict[str, list[int]] | None:
    """Split tables at midpoint for 10-K filings.

    Assumes first half = current period, second half = comparative.
    Only used as last resort when other methods fail.
    """
    if len(table_indices) < 4:
        return None

    if not report_date or len(report_date) < 10:
        return None

    # Find the largest gap between consecutive tables
    sorted_tables = sorted(table_indices)
    max_gap = 0
    split_point = len(sorted_tables) // 2

    for i in range(1, len(sorted_tables)):
        gap = sorted_tables[i] - sorted_tables[i - 1]
        if gap > max_gap:
            max_gap = gap
            split_point = i

    # If largest gap is < 3, fall back to midpoint
    if max_gap < 3:
        split_point = len(sorted_tables) // 2

    current = sorted_tables[:split_point]
    comparative = sorted_tables[split_point:]

    if not current or not comparative:
        return None

    # Derive comparative date
    try:
        year = int(report_date[:4])
        comp_date = f"{year - 1}-{report_date[5:]}"
    except (ValueError, IndexError):
        return None

    return {
        report_date: current,
        comp_date: comparative,
    }


def fix_10k_periods_for_cik(
    cik: str,
    template: dict,
    idx: pd.DataFrame,
) -> dict:
    """Fix 10-K filings missing table_periods in a template.

    Returns stats dict.
    """
    cik_stripped = cik.lstrip("0")
    cache_dir = BDC_HTML_CACHE_DIR / cik_stripped
    filings_ovr = template.get("filings", {})
    default_tables = template.get("default", {}).get("tables", [])
    cik_filings = idx[idx["cik"].str.lstrip("0") == cik_stripped].copy()

    stats = {"fixed_html": 0, "fixed_grid": 0, "fixed_midpoint": 0,
             "already_has_periods": 0, "not_10k": 0, "too_few_tables": 0}

    for acc_dashed, override in filings_ovr.items():
        tables = override.get("tables", default_tables)
        if not tables or len(tables) < 3:
            continue

        # Skip if already has table_periods
        if override.get("table_periods"):
            stats["already_has_periods"] += 1
            continue

        # Check form type
        row = cik_filings[cik_filings["accession_number"] == acc_dashed]
        if row.empty:
            continue
        form_type = row.iloc[0].get("form_type", "")
        report_date = row.iloc[0].get("report_date", "")

        if "10-K" not in form_type:
            stats["not_10k"] += 1
            continue

        acc_nodashes = acc_dashed.replace("-", "")

        # Method 1: HTML-based detection
        html_path = cache_dir / f"{acc_nodashes}.html"
        table_periods = None
        if html_path.exists():
            table_periods = _detect_periods_from_html(
                html_path, tables, report_date,
            )
            if table_periods:
                override["table_periods"] = table_periods
                stats["fixed_html"] += 1
                continue

        # Method 2: Grid-based date scanning
        table_periods = _scan_grids_for_periods(cik_stripped, acc_nodashes, tables)
        if table_periods:
            override["table_periods"] = table_periods
            stats["fixed_grid"] += 1
            continue

        # Method 3: Gap-based detection (relaxed)
        grids = _load_grids(cik_stripped, acc_nodashes)
        if grids:
            # Try grouping tables
            scored = [(tidx, 10, 20, 0) for tidx in tables]  # dummy scores
            groups = _group_continuation_tables(scored)
            if len(groups) >= 2:
                table_periods = _detect_10k_periods(groups, report_date)
                if table_periods:
                    override["table_periods"] = table_periods
                    stats["fixed_grid"] += 1
                    continue

        # Method 4: Midpoint split as last resort
        table_periods = _midpoint_split(tables, report_date)
        if table_periods:
            override["table_periods"] = table_periods
            stats["fixed_midpoint"] += 1
            continue

        stats["too_few_tables"] += 1

    return stats


def main():
    parser = argparse.ArgumentParser(description="Fix 10-K filings missing table_periods")
    parser.add_argument("--cik", help="Process single CIK")
    args = parser.parse_args()

    template_dir = Path("data/raw/filing_templates")
    idx = _load_filings_index()

    if args.cik:
        cik = args.cik.lstrip("0")
        templates_to_process = [(cik, template_dir / f"{cik}.json")]
    else:
        templates_to_process = [
            (tp.stem, tp) for tp in sorted(template_dir.glob("*.json"))
        ]

    total = {"fixed_html": 0, "fixed_grid": 0, "fixed_midpoint": 0,
             "already_has_periods": 0, "too_few_tables": 0}
    modified_ciks = []

    for cik, tp in templates_to_process:
        if not tp.exists():
            continue
        with open(tp) as f:
            template = json.load(f)
        if template.get("version") != "3.0":
            continue

        result = fix_10k_periods_for_cik(cik, template, idx)
        fixed = result["fixed_html"] + result["fixed_grid"] + result["fixed_midpoint"]

        if fixed > 0:
            modified_ciks.append(cik)
            with open(tp, "w") as f:
                json.dump(template, f, indent=2)
                f.write("\n")
            print(f"  CIK {cik:>10}: {fixed} fixed "
                  f"(html={result['fixed_html']}, grid={result['fixed_grid']}, "
                  f"midpoint={result['fixed_midpoint']})")

        for k in total:
            total[k] += result.get(k, 0)

    print(f"\nSummary:")
    print(f"  Fixed via HTML markers: {total['fixed_html']}")
    print(f"  Fixed via grid dates: {total['fixed_grid']}")
    print(f"  Fixed via midpoint split: {total['fixed_midpoint']}")
    print(f"  Already had periods: {total['already_has_periods']}")
    print(f"  Too few tables: {total['too_few_tables']}")
    print(f"  Modified CIKs: {len(modified_ciks)}")


if __name__ == "__main__":
    main()
