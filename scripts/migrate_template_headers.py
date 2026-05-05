"""One-time migration: add 'header' keys to all v3.0 templates.

For each template, loads a sample filing's grids, matches header text
against FIELD_HEADERS patterns, and adds "header" to column specs
where the header text confirms the field mapping.

Usage:
    python scripts/migrate_template_headers.py          # Migrate all templates
    python scripts/migrate_template_headers.py --dry-run # Preview changes
    python scripts/migrate_template_headers.py --cik 1287750  # Single CIK
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline.config import BDC_HTML_CACHE_DIR, HTML_TEMPLATE_DIR

# Canonical header patterns per field (pipe-separated OR)
FIELD_HEADERS = {
    "investment_identifier": "portfolio company|issuer|borrower|investment name|investments",
    "investment_type": "type of investment|investment type",
    "industry": "industry|sector",
    "interest_rate": "interest rate|coupon rate|rate",
    "reference_rate_type": "reference rate",
    "basis_spread": "spread",
    "maturity_date": "maturity",
    "principal_amount": "principal|par amount|par value",
    "cost": "cost|amortized cost",
    "fair_value": "fair value",
    "shares_held": "shares|units",
    "pik_rate": "pik",
    "pct_of_net_assets": "net assets|% of net",
}


def _accession_from_filename(filename: str) -> str:
    """Convert grids filename to accession format.

    '000114420413006615.grids.json' -> '0001144204-13-006615'
    """
    stem = filename.replace(".grids.json", "")
    if len(stem) == 18:
        return f"{stem[:10]}-{stem[10:12]}-{stem[12:]}"
    return stem


def _get_tables_for_filing(template: dict, accession: str) -> tuple[list[int], int]:
    """Get the correct table indices and header_row for a specific filing.

    Checks filing-specific overrides first, falls back to default.
    Includes table_periods tables (comparative period SOI tables).
    Returns (table_indices, header_row_idx).
    """
    default_tables = template.get("default", {}).get("tables", [])
    default_hr = template.get("default", {}).get("header_row", 0)

    filing_override = template.get("filings", {}).get(accession, {})
    if not filing_override:
        return default_tables, default_hr

    tables = list(filing_override.get("tables", default_tables))
    hr = filing_override.get("header_row", default_hr)

    # Include table_periods tables (comparative period SOI)
    for period_tables in filing_override.get("table_periods", {}).values():
        for ti in period_tables:
            if ti not in tables:
                tables.append(ti)

    return tables, hr


_SOI_INDICATORS = ["fair value", "cost", "maturity", "interest rate",
                   "principal", "par amount"]


def _is_soi_header(row: list[str]) -> bool:
    """Check if a header row looks like a Schedule of Investments.

    Requires at least 2 distinct SOI indicator phrases to avoid
    false positives from summary tables.
    """
    row_text = " ".join(c.strip().lower() for c in row)
    return sum(1 for kw in _SOI_INDICATORS if kw in row_text) >= 2


def _load_grids_with_soi(cik: str, template: dict) -> tuple[list | None, list[int], int]:
    """Load grids from a filing where SOI tables can be found.

    Tries each grids file, using the correct table indices (filing
    override or default). Validates that at least one table has
    a genuine SOI header (>= 2 indicator fields).  Returns
    (grids, table_indices, header_row_idx) or (None, [], 0).
    """
    cache_dir = BDC_HTML_CACHE_DIR / cik
    if not cache_dir.exists():
        return None, [], 0
    grids_files = sorted(cache_dir.glob("*.grids.json"))
    if not grids_files:
        return None, [], 0

    fallback = None  # first file with overlapping tables (even if no SOI)

    for gf in grids_files:
        accession = _accession_from_filename(gf.name)
        tables, hr = _get_tables_for_filing(template, accession)
        if not tables:
            continue
        try:
            with open(gf) as f:
                grids = json.load(f)
        except (json.JSONDecodeError, OSError):
            continue
        # Skip malformed grids (some files are list-of-lists)
        if not grids or not isinstance(grids[0], dict):
            continue
        idx_set = set(tables)
        has_overlap = False
        has_soi = False
        for t in grids:
            if t["index"] not in idx_set:
                continue
            has_overlap = True
            g = t.get("grid", [])
            if hr < len(g) and _is_soi_header(g[hr]):
                has_soi = True
                break
        if has_soi:
            return grids, tables, hr
        if has_overlap and fallback is None:
            fallback = (grids, tables, hr)

    if fallback:
        return fallback
    return None, [], 0


def _get_header_row(grids: list, table_indices: list[int],
                    header_row_idx: int) -> list[str] | None:
    """Get header row from the first SOI table in grids.

    Prefers tables with a genuine SOI header (>= 2 indicator fields)
    to avoid picking summary tables or financial statements.
    """
    idx_set = set(table_indices)
    fallback = None
    for t in grids:
        if t["index"] not in idx_set:
            continue
        grid = t.get("grid", [])
        if header_row_idx >= len(grid):
            continue
        row = grid[header_row_idx]
        if _is_soi_header(row):
            return row
        if fallback is None:
            fallback = row
    return fallback


def _match_header_cell(cell: str, pattern: str) -> str | None:
    """Check if cell text matches any of the pipe-separated patterns.

    Returns the specific matched alternative, or None.
    """
    cell_lower = cell.strip().lower()
    if not cell_lower:
        return None
    for p in pattern.split("|"):
        p = p.strip()
        if p and p in cell_lower:
            return p
    return None


def migrate_template(cik: str, dry_run: bool = False) -> dict:
    """Add 'header' keys to a single template. Returns change summary."""
    template_path = HTML_TEMPLATE_DIR / f"{cik}.json"
    if not template_path.exists():
        return {"cik": cik, "status": "not_found"}

    with open(template_path) as f:
        template = json.load(f)

    if template.get("version") != "3.0":
        return {"cik": cik, "status": "wrong_version"}

    columns = template.get("columns", {})
    if not columns:
        return {"cik": cik, "status": "no_columns"}

    # Load grids using correct filing-specific table overrides
    grids, soi_tables, header_row_idx = _load_grids_with_soi(cik, template)

    header_row = None
    if grids and soi_tables:
        header_row = _get_header_row(grids, soi_tables, header_row_idx)

    changes = []

    # Process base columns
    for field, spec in list(columns.items()):
        if not isinstance(spec, dict):
            continue
        if spec.get("header"):
            continue  # already has header

        pattern = FIELD_HEADERS.get(field)
        if not pattern:
            continue

        # Check if header row confirms this field
        if header_row:
            col_idx = spec.get("col", -1)
            # Search all header cells for the best (longest) match
            best_match = None
            for cell in header_row:
                m = _match_header_cell(cell, pattern)
                if m and (best_match is None or len(m) > len(best_match)):
                    best_match = m
            if best_match:
                spec["header"] = best_match
                changes.append(f"columns.{field}")
        else:
            # No grids available: add full pattern as fallback
            spec["header"] = pattern
            changes.append(f"columns.{field} (no grids)")

    # Process columns_by_width entries
    cbw = template.get("columns_by_width", {})
    for width_key, width_cols in cbw.items():
        # Try to find a table at this width for header verification
        width_header = None
        if grids:
            target_w = int(width_key) if width_key.isdigit() else 0
            # First try SOI tables at this width, then any table
            soi_set = set(soi_tables) if soi_tables else set()
            for t in grids:
                g = t.get("grid", [])
                if g and len(g[0]) == target_w and t["index"] in soi_set:
                    if header_row_idx < len(g):
                        width_header = g[header_row_idx]
                        break
            if not width_header:
                # Fallback: any table at this width (for widths from
                # other filings not in this grids file)
                for t in grids:
                    g = t.get("grid", [])
                    if g and len(g[0]) == target_w:
                        if header_row_idx < len(g):
                            width_header = g[header_row_idx]
                            break

        for field, spec in list(width_cols.items()):
            if not isinstance(spec, dict):
                continue
            if spec.get("header"):
                continue

            pattern = FIELD_HEADERS.get(field)
            if not pattern:
                continue

            check_row = width_header or header_row
            if check_row:
                best_match = None
                for cell in check_row:
                    m = _match_header_cell(cell, pattern)
                    if m and (best_match is None or len(m) > len(best_match)):
                        best_match = m
                if best_match:
                    spec["header"] = best_match
                    changes.append(f"columns_by_width.{width_key}.{field}")
            else:
                spec["header"] = pattern
                changes.append(
                    f"columns_by_width.{width_key}.{field} (no grids)"
                )

    # Check if investment_identifier is missing from base columns
    if "investment_identifier" not in columns:
        pattern = FIELD_HEADERS["investment_identifier"]
        if header_row:
            for col_idx, cell in enumerate(header_row):
                m = _match_header_cell(cell, pattern)
                if m:
                    columns["investment_identifier"] = {
                        "col": col_idx,
                        "header": m,
                    }
                    changes.append("columns.investment_identifier (added)")
                    break
            else:
                # No header match but col 0 likely has company names
                # Check if col 0 has non-empty text data
                if grids and soi_tables:
                    for t in grids:
                        if t["index"] in soi_tables:
                            g = t.get("grid", [])
                            for ri in range(header_row_idx + 1,
                                            min(len(g), header_row_idx + 5)):
                                if g[ri] and g[ri][0].strip():
                                    columns["investment_identifier"] = {
                                        "col": 0,
                                    }
                                    changes.append(
                                        "columns.investment_identifier "
                                        "(positional col 0)"
                                    )
                                    break
                            break

    if not changes:
        return {"cik": cik, "status": "no_changes", "changes": []}

    if not dry_run:
        with open(template_path, "w") as f:
            json.dump(template, f, indent=2)

    return {"cik": cik, "status": "migrated", "changes": changes}


def main():
    parser = argparse.ArgumentParser(
        description="Add 'header' keys to v3.0 templates",
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="Preview changes without writing")
    parser.add_argument("--cik", type=str,
                        help="Migrate single CIK")
    args = parser.parse_args()

    if args.cik:
        cik = args.cik.lstrip("0")
        result = migrate_template(cik, dry_run=args.dry_run)
        print(f"CIK {cik}: {result['status']}")
        if result.get("changes"):
            for c in result["changes"]:
                print(f"  + {c}")
        return

    # Migrate all templates
    template_files = sorted(HTML_TEMPLATE_DIR.glob("*.json"))
    total = 0
    migrated = 0
    no_changes = 0
    skipped = 0

    for tf in template_files:
        if not tf.stem.isdigit():
            continue
        total += 1
        cik = tf.stem
        result = migrate_template(cik, dry_run=args.dry_run)

        if result["status"] == "migrated":
            migrated += 1
            n = len(result.get("changes", []))
            print(f"  {cik}: +{n} headers")
        elif result["status"] == "no_changes":
            no_changes += 1
        else:
            skipped += 1
            print(f"  {cik}: {result['status']}")

    action = "would migrate" if args.dry_run else "migrated"
    print(f"\nDone: {total} templates, {action} {migrated}, "
          f"no changes {no_changes}, skipped {skipped}")


if __name__ == "__main__":
    main()
