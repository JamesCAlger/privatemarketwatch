"""Runner script for per-CIK HTML template creation (v3.0).

Lists CIKs needing templates, downloads HTML filings, provides validation
utilities. Designed to be run by Claude Code instances following the prompt
in scripts/learn_template_prompt.md.

Usage:
    # Auto-detect SOI tables and write draft template (recommended first step)
    python scripts/learn_template.py --auto-detect 1287750

    # List CIKs needing templates
    python scripts/learn_template.py --list

    # Prepare data for a specific CIK (download HTML, list all tables)
    python scripts/learn_template.py --prepare 1287750

    # Claim next unclaimed CIK, download & prepare
    python scripts/learn_template.py --next

    # Inspect a table's grid layout + auto-suggest column mapping
    python scripts/learn_template.py --inspect 1287750 --filing 000114420419025263 --table 7

    # Inspect all distinct widths across all filings for a CIK
    python scripts/learn_template.py --inspect 1287750 --all-widths

    # Validate a template against extraction results
    python scripts/learn_template.py --validate 1287750

    # Quick validation only (aggregate + carry rate)
    python scripts/learn_template.py --validate-only 1287750

    # Accept a FAIL with justification (marks as done)
    python scripts/learn_template.py --accept 1476765 --justification "10-K full SOI vs 10-Q summary causes count instability. FV correct within each form type."

    # Re-validate ALL templates (batch), save summary CSV with triage report
    python scripts/learn_template.py --revalidate-all

    # Show progress summary
    python scripts/learn_template.py --progress
"""

import argparse
import json
import logging
import os
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

from pipeline.config import (
    BDC_FILINGS_INDEX_FILE,
    BDC_HTML_CACHE_DIR,
    COMPANYFACTS_CACHE_DIR,
    HTML_TEMPLATE_DIR,
    OUTPUT_DIR,
)
from pipeline.html_soi_evidence import (
    detect_10k_periods as _shared_detect_10k_periods,
    detect_periods_from_html_text as _shared_detect_periods_from_html_text,
    find_soi_date_markers as _shared_find_soi_date_markers,
    group_continuation_tables as _shared_group_continuation_tables,
    parse_period_date as _shared_parse_period_date,
    score_table_soi as _shared_score_table_soi,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

TEMPLATE_PROGRESS_FILE = OUTPUT_DIR / "template_progress.csv"
TEMPLATE_CLAIMS_FILE = OUTPUT_DIR / "template_claims.json"
VALIDATION_SUMMARY_FILE = OUTPUT_DIR / "html_template_validation_summary.csv"

# XBRL became universal for BDCs in 2023Q1 (100% coverage).  HTML templates
# only need to cover filings with report_date <= this cutoff.
HTML_TEMPLATE_CUTOFF_DATE = "2022-12-31"


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def _load_filings_index() -> pd.DataFrame:
    return pd.read_csv(BDC_FILINGS_INDEX_FILE, dtype=str)


def _load_bdc_holdings() -> pd.DataFrame:
    return pd.read_csv(
        OUTPUT_DIR / "bdc_holdings.csv",
        dtype={"cik": str},
        usecols=[
            "cik", "entity_name", "accession_number", "form_type",
            "report_date", "period", "investment_identifier",
            "fair_value", "cost", "principal_amount", "interest_rate",
            "basis_spread", "reference_rate_type", "maturity_date",
            "shares_held", "pik_rate",
        ],
    )


# ---------------------------------------------------------------------------
# Table grid I/O  (one .grids.json per HTML filing, exact copy of parsed grid)
# ---------------------------------------------------------------------------

def _grids_path_for_filing(cik: str, acc_nodashes: str) -> Path:
    """Path to saved grids JSON for a specific filing."""
    return BDC_HTML_CACHE_DIR / cik / f"{acc_nodashes}.grids.json"


def _save_grids(cik: str, acc_nodashes: str, tables: list) -> None:
    """Save all table grids for one filing as JSON."""
    out = []
    for i, t in enumerate(tables):
        out.append({
            "index": i,
            "width": len(t[0]) if t else 0,
            "rows": len(t),
            "grid": t,
        })
    path = _grids_path_for_filing(cik, acc_nodashes)
    with open(path, "w") as f:
        json.dump(out, f, separators=(",", ":"))


def _load_grids(cik: str, acc_nodashes: str) -> list | None:
    """Load saved grids for one filing. Returns list of table dicts or None."""
    path = _grids_path_for_filing(cik, acc_nodashes)
    if not path.exists():
        return None
    try:
        with open(path) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def _load_table_grid(cik: str, acc_nodashes: str, table_idx: int):
    """Load a single table's grid. Returns list-of-rows or None."""
    grids = _load_grids(cik, acc_nodashes)
    if not grids:
        return None
    for t in grids:
        if t["index"] == table_idx:
            return t["grid"]
    return None


# ---------------------------------------------------------------------------
# List CIKs needing templates
# ---------------------------------------------------------------------------

def list_ciks():
    """Print CIKs that need templates, sorted by filing count."""
    idx = _load_filings_index()
    html_filings = idx[idx["xbrl_download_status"] == "not_found"]

    # Check existing templates
    existing = {f.stem for f in HTML_TEMPLATE_DIR.glob("*.json")}

    # Group by CIK
    grouped = html_filings.groupby("cik").agg(
        entity_name=("entity_name", "first"),
        n_filings=("accession_number", "count"),
        min_date=("filing_date", "min"),
        max_date=("filing_date", "max"),
    ).reset_index()

    # Check which have XBRL ground truth
    try:
        bdc = pd.read_csv(
            OUTPUT_DIR / "bdc_holdings.csv",
            usecols=["cik"], dtype=str,
        )
        xbrl_ciks = set(bdc["cik"].str.lstrip("0"))
    except FileNotFoundError:
        xbrl_ciks = set()

    # Check which have cached HTML
    cached_ciks = set()
    if BDC_HTML_CACHE_DIR.exists():
        for d in BDC_HTML_CACHE_DIR.iterdir():
            if d.is_dir() and list(d.glob("*.html")):
                cached_ciks.add(d.name)

    grouped["cik_stripped"] = grouped["cik"].str.lstrip("0")
    grouped["has_template"] = grouped["cik_stripped"].isin(existing)
    grouped["has_xbrl"] = grouped["cik_stripped"].isin(xbrl_ciks)
    grouped["has_html_cached"] = grouped["cik_stripped"].isin(cached_ciks)

    # Split into done vs needed
    done = grouped[grouped["has_template"]]
    needed = grouped[~grouped["has_template"]].sort_values(
        "n_filings", ascending=False,
    )

    print(f"\n{'='*70}")
    print(f"Template Progress: {len(done)}/{len(grouped)} CIKs complete")
    print(f"{'='*70}")

    if not needed.empty:
        needed = needed.sort_values(
            ["has_xbrl", "n_filings"], ascending=[False, False],
        )
        print(f"\nCIKs needing templates ({len(needed)}):")
        print(f"{'CIK':>10}  {'Name':<40}  {'Filings':>7}  {'Dates':<23}  {'XBRL':>4}  {'HTML':>4}")
        print("-" * 100)
        for _, row in needed.iterrows():
            cik = row["cik_stripped"]
            name = (row["entity_name"] or "")[:40]
            xbrl = "Y" if row["has_xbrl"] else ""
            html = "Y" if row["has_html_cached"] else ""
            print(
                f"{cik:>10}  {name:<40}  {row['n_filings']:>7}  "
                f"{row['min_date']} - {row['max_date']}  {xbrl:>4}  {html:>4}"
            )

    if not done.empty:
        print(f"\nCompleted ({len(done)}):")
        for _, row in done.iterrows():
            print(f"  {row['cik_stripped']:>10}  {(row['entity_name'] or '')[:50]}")


# ---------------------------------------------------------------------------
# Prepare HTML data for a CIK
# ---------------------------------------------------------------------------

def _scan_tables(html_path: Path, cik: str = None) -> list[dict] | None:
    """Scan all tables in an HTML file.

    Returns list of table info dicts, or None on error.
    Saves full grids to disk as .grids.json alongside the HTML file.
    """
    try:
        from pipeline.html_extract import _extract_tables
    except ImportError:
        return None
    try:
        html = html_path.read_text(encoding="utf-8", errors="replace")
        tables = _extract_tables(html)

        # Save exact grid copy to disk
        if cik:
            acc_nodashes = html_path.stem
            _save_grids(cik, acc_nodashes, tables)

        results = []
        for i, table in enumerate(tables):
            header = table[0] if table else []
            header_text = [c for c in header if c.strip()]
            results.append({
                "index": i,
                "rows": len(table),
                "cols": len(header),
                "header_nonempty": len(header_text),
                "header_text": header_text[:8],
                "sample_row": table[1] if len(table) > 1 else [],
            })
        return results
    except Exception:
        return None


def prepare_cik(cik: str):
    """Download ALL pre-XBRL HTML filings for a CIK and list tables.

    Downloads every filing, scans all tables, saves grids to .grids.json,
    and shows table index, row count, and header text for each. This is the
    input the LLM instance uses to create the v3.0 template.
    """
    cik_stripped = cik.lstrip("0")
    idx = _load_filings_index()

    cik_filings = idx[
        (idx["cik"].str.lstrip("0") == cik_stripped)
        & (idx["xbrl_download_status"] == "not_found")
    ].sort_values("filing_date")

    if cik_filings.empty:
        print(f"No pre-XBRL filings found for CIK {cik_stripped}")
        return

    entity_name = cik_filings.iloc[0]["entity_name"]
    print(f"\nCIK {cik_stripped}: {entity_name}")
    print(f"  Pre-XBRL filings: {len(cik_filings)}")
    print(f"  Date range: {cik_filings['filing_date'].min()} "
          f"to {cik_filings['filing_date'].max()}")

    # ------------------------------------------------------------------
    # Phase 1: Download ALL filings
    # ------------------------------------------------------------------
    cache_dir = BDC_HTML_CACHE_DIR / cik_stripped
    to_download = []
    already_cached = 0
    for _, filing in cik_filings.iterrows():
        acc_nodashes = filing["accession_number"].replace("-", "")
        cache_file = cache_dir / f"{acc_nodashes}.html"
        if cache_file.exists() and cache_file.stat().st_size > 1024:
            already_cached += 1
        else:
            to_download.append(filing)

    print(f"\n  Cached: {already_cached}/{len(cik_filings)}, "
          f"to download: {len(to_download)}")

    if to_download:
        from pipeline.edgar_client import EdgarClient
        from pipeline.bdc_filings import download_html_filing
        client = EdgarClient()
        ok, fail = 0, 0
        for filing in to_download:
            primary_doc = filing.get("primary_document", "")
            result = download_html_filing(
                client, cik_stripped,
                filing["accession_number"], primary_doc,
                agent="learn_template",
                reason="learn_template_prepare",
            )
            if result:
                ok += 1
            else:
                fail += 1
        print(f"  Downloaded: {ok}, failed: {fail}")

    # ------------------------------------------------------------------
    # Phase 2: Scan ALL tables in ALL filings (saves .grids.json per filing)
    # ------------------------------------------------------------------
    print(f"\n  Table scan (all filings):")
    print(f"  {'='*70}")

    for _, filing in cik_filings.iterrows():
        acc = filing["accession_number"]
        acc_nodashes = acc.replace("-", "")
        cache_file = cache_dir / f"{acc_nodashes}.html"

        print(f"\n  {filing['filing_date']}  {filing['form_type']:<8}  {acc}")

        if not cache_file.exists():
            print(f"    (not cached)")
            continue

        table_info = _scan_tables(cache_file, cik=cik_stripped)
        if table_info is None:
            print(f"    (parse error)")
            continue

        if not table_info:
            print(f"    (no tables)")
            continue

        for t in table_info:
            header_preview = ", ".join(t["header_text"][:6])
            if len(t["header_text"]) > 6:
                header_preview += ", ..."
            header_preview = header_preview.encode("ascii", "replace").decode("ascii")
            print(f"    Table {t['index']:>2}: {t['rows']:>4} rows, "
                  f"{t['header_nonempty']:>2} cols  [{header_preview}]")

            # Show first data row as sample
            if t["sample_row"]:
                sample = [c for c in t["sample_row"] if c.strip()][:6]
                sample_str = " | ".join(sample)
                if len(sample_str) > 70:
                    sample_str = sample_str[:67] + "..."
                sample_str = sample_str.encode("ascii", "replace").decode("ascii")
                print(f"           sample: {sample_str}")

    # ------------------------------------------------------------------
    # Phase 3: XBRL ground truth
    # ------------------------------------------------------------------
    try:
        bdc = pd.read_csv(
            OUTPUT_DIR / "bdc_holdings.csv",
            dtype={"cik": str},
            usecols=["cik", "report_date", "fair_value"],
        )
        xbrl = bdc[bdc["cik"].str.lstrip("0") == cik_stripped]
        if not xbrl.empty:
            dates = sorted(xbrl["report_date"].unique())
            print(f"\n  XBRL ground truth available:")
            print(f"    Periods: {len(dates)} ({dates[0]} to {dates[-1]})")
            for dt in dates[-4:]:
                n = len(xbrl[xbrl["report_date"] == dt])
                fv_sum = pd.to_numeric(
                    xbrl[xbrl["report_date"] == dt]["fair_value"],
                    errors="coerce",
                ).sum()
                print(f"    {dt}: {n} holdings, FV=${fv_sum/1e6:,.0f}M")
        else:
            print(f"\n  No XBRL ground truth (pre-XBRL only CIK)")
    except FileNotFoundError:
        print(f"\n  bdc_holdings.csv not found")

    # Summary
    grids_dir = BDC_HTML_CACHE_DIR / cik_stripped
    n_grids = len(list(grids_dir.glob("*.grids.json")))
    print(f"\n  Saved {n_grids} .grids.json files alongside HTML.")
    print(f"  Use --inspect {cik_stripped} --all-widths to see column layouts.")


# ---------------------------------------------------------------------------
# Inspect table grids (column mapping helper)
# ---------------------------------------------------------------------------

# Header text -> field name mapping for auto-suggestion
_HEADER_FIELD_MAP = [
    (r"portfolio\s*company|issuer|borrower|\bcompany\b|investment\s*name", "investment_identifier"),
    (r"industry|sector", "industry"),
    (r"\bcoupon\b|\brate\b|\binterest\b", "interest_rate"),
    (r"\bfloor\b", None),  # recognized but no direct field
    (r"maturity", "maturity_date"),
    (r"principal\s*amount|par\s*amount|par\s*value|\bprincipal\b|\bpar\b", "principal_amount"),
    (r"amortized\s*cost|\bcost\b", "cost"),
    (r"fair\s*value", "fair_value"),
    (r"number\s*of\s*shares|\bshares\b|\bunits\b", "shares_held"),
    (r"reference\s*rate", "reference_rate_type"),
    (r"\bspread\b", "basis_spread"),
    (r"\bpik\b", "pik_rate"),
    (r"net\s*assets|%\s*of\s*net", "pct_of_net_assets"),
    (r"footnote", None),
]


def _match_header_to_field(header_text: str) -> str | None:
    """Map header text to a template field name. Returns None if no match."""
    text = header_text.lower().strip()
    if not text:
        return None
    for pattern, field in _HEADER_FIELD_MAP:
        if re.search(pattern, text):
            return field
    return None


_DOLLAR_FIELDS = {"principal_amount", "cost", "fair_value"}
_RATE_FIELDS = {"interest_rate", "basis_spread", "pik_rate"}
_TEXT_FIELDS = {"investment_identifier", "industry", "investment_type",
                "reference_rate_type", "maturity_date"}

# Canonical header patterns for semantic header matching in templates.
# Used by auto-detect to add "header" to column specs, and by the migration
# script (scripts/migrate_template_headers.py).
_FIELD_HEADERS = {
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


def _find_data_position(grid: list, header_pos: int, field: str,
                        data_rows: list) -> int | None:
    """Find where data actually appears for a field, given its header position.

    Scans data rows to find the first non-empty cell at or after header_pos.
    For dollar fields, looks for '$' sign first.
    Returns the grid position to use in the template col mapping.
    """
    if not data_rows:
        return header_pos

    for row in data_rows:
        if header_pos >= len(row):
            continue

        # For dollar fields: find the '$' position (engine reads $ -> lookahead -> number)
        if field in _DOLLAR_FIELDS:
            # Search from header_pos to header_pos+4
            for offset in range(0, 5):
                pos = header_pos + offset
                if pos >= len(row):
                    break
                val = row[pos].strip()
                if val == "$":
                    return pos  # engine will read $ then lookahead to number
                if val and val != "$" and re.match(r"^[\d,.()\-]+$", val):
                    return pos  # number directly at this position
                if val and val.startswith("$") and len(val) > 1:
                    return pos  # "$12,345" combined in one cell

        # For shares/number fields (no $ sign): find the first numeric cell
        if field == "shares_held":
            for offset in range(0, 5):
                pos = header_pos + offset
                if pos >= len(row):
                    break
                val = row[pos].strip().replace(",", "")
                if val and re.match(r"^[\d.]+$", val):
                    return pos

        # For text/rate/date fields: find first non-empty cell
        if field in _TEXT_FIELDS or field in _RATE_FIELDS:
            for offset in range(0, 3):
                pos = header_pos + offset
                if pos >= len(row):
                    break
                val = row[pos].strip()
                if val:
                    return pos

    # Fallback: header position itself
    return header_pos


def inspect_table(cik: str, acc_nodashes: str, table_idx: int,
                  header_row: int = 0):
    """Inspect a single table's grid and auto-suggest column mapping.

    Reads from saved .grids.json (no HTML re-parsing needed).
    """
    cik_stripped = cik.lstrip("0")
    grid = _load_table_grid(cik_stripped, acc_nodashes, table_idx)
    if grid is None:
        print(f"Table {table_idx} not found in grids for {acc_nodashes}.")
        print(f"Run --prepare {cik_stripped} first to generate .grids.json files.")
        return

    width = len(grid[0]) if grid else 0
    print(f"\n{'='*70}")
    print(f"Table {table_idx} in {acc_nodashes}  (width={width}, {len(grid)} rows)")
    print(f"{'='*70}")

    if header_row >= len(grid):
        print(f"  header_row={header_row} out of range (table has {len(grid)} rows)")
        return

    # --- Show header row with positions ---
    hdr = grid[header_row]
    print(f"\n  Header (row {header_row}):")
    headers_at = {}  # pos -> text
    for i, cell in enumerate(hdr):
        text = cell.strip()
        if text:
            headers_at[i] = text
            safe = text.encode("ascii", "replace").decode("ascii")[:40]
            print(f"    [{i:>2}] {safe}")

    # --- Show first 3 data rows with non-empty cells ---
    print(f"\n  Data rows:")
    data_rows = []
    shown = 0
    for ri in range(header_row + 1, min(len(grid), header_row + 20)):
        row = grid[ri]
        nonempty = [(i, row[i].strip()[:30]) for i in range(len(row))
                    if row[i].strip()]
        if not nonempty:
            continue
        data_rows.append(row)
        if shown < 3:
            safe_cells = [(i, v.encode("ascii", "replace").decode("ascii"))
                          for i, v in nonempty]
            print(f"    Row {ri}: {safe_cells}")
            shown += 1

    # --- Find $ positions across data rows ---
    dollar_positions = set()
    for row in data_rows[:5]:
        for i, cell in enumerate(row):
            if cell.strip() == "$":
                dollar_positions.add(i)
    if dollar_positions:
        print(f"\n  $ sign positions in data: {sorted(dollar_positions)}")

    # --- Auto-suggest column mapping ---
    print(f"\n  Suggested columns_by_width[\"{width}\"]:")
    suggestion = {}
    for hpos, htext in sorted(headers_at.items()):
        field = _match_header_to_field(htext)
        if field is None:
            continue
        data_pos = _find_data_position(grid, hpos, field, data_rows[:5])
        if data_pos is not None:
            suggestion[field] = data_pos
            offset_note = ""
            if data_pos != hpos:
                offset_note = f"  (header at {hpos}, data at {data_pos})"
            safe = htext.encode("ascii", "replace").decode("ascii")[:30]
            print(f'    "{field}": {{"col": {data_pos}}}  '
                  f'  # {safe}{offset_note}')

    # --- Print as JSON ---
    if suggestion:
        print(f"\n  JSON:")
        print(f'    "{width}": {{')
        items = list(suggestion.items())
        for i, (field, col) in enumerate(items):
            comma = "," if i < len(items) - 1 else ""
            print(f'      "{field}": {{"col": {col}}}{comma}')
        print(f"    }}")

    return suggestion


def inspect_all_widths(cik: str):
    """Inspect all distinct table widths across all filings for a CIK.

    Groups tables by header-row width, picks one representative per width,
    and runs the column-mapping suggestion for each.
    """
    cik_stripped = cik.lstrip("0")
    cache_dir = BDC_HTML_CACHE_DIR / cik_stripped

    grids_files = sorted(cache_dir.glob("*.grids.json"))
    if not grids_files:
        print(f"No .grids.json files found for CIK {cik_stripped}.")
        print(f"Run --prepare {cik_stripped} first.")
        return

    # Collect all tables grouped by width
    # width -> {"acc": ..., "table_idx": ..., "rows": ..., "header_row": ...}
    width_samples = {}
    soi_keywords = {"fair value", "cost", "principal", "amortized",
                    "maturity", "shares", "portfolio company", "issuer"}

    for gf in grids_files:
        acc = gf.stem.replace(".grids", "")
        grids = _load_grids(cik_stripped, acc)
        if not grids:
            continue

        for t in grids:
            idx = t["index"]
            w = t["width"]
            nrows = t["rows"]
            grid = t["grid"]
            if not grid or nrows < 5:
                continue

            # Check if this looks like a schedule-of-investments table
            # by matching header keywords
            for hr in range(min(3, len(grid))):
                hdr_text = " ".join(
                    c.lower() for c in grid[hr] if c.strip()
                )
                matches = sum(1 for kw in soi_keywords if kw in hdr_text)
                if matches >= 2:
                    key = (w, hr)
                    if key not in width_samples or nrows > width_samples[key]["rows"]:
                        width_samples[key] = {
                            "acc": acc, "table_idx": idx,
                            "rows": nrows, "header_row": hr,
                        }
                    break

    if not width_samples:
        print(f"No schedule-of-investments tables found in grids.")
        return

    print(f"\n{'='*70}")
    print(f"All distinct SOI table widths for CIK {cik_stripped}")
    print(f"{'='*70}")
    print(f"  Found {len(width_samples)} distinct (width, header_row) combinations.\n")

    for (w, hr), info in sorted(width_samples.items()):
        inspect_table(
            cik_stripped, info["acc"], info["table_idx"],
            header_row=hr,
        )
        print()


# ---------------------------------------------------------------------------
# Persist validation result
# ---------------------------------------------------------------------------

def _load_validation_summary() -> pd.DataFrame:
    """Load the validation summary CSV, or return empty DataFrame."""
    if VALIDATION_SUMMARY_FILE.exists():
        try:
            return pd.read_csv(VALIDATION_SUMMARY_FILE, dtype={"cik": str})
        except Exception:
            return pd.DataFrame()
    return pd.DataFrame()


def _save_validation_result(result: dict) -> None:
    """Upsert a single CIK's validation result into the summary CSV.

    Preserves existing ``fail_justification`` and ``accepted`` fields
    if present (they are set separately via ``--accept``).
    """
    s = result.get("summary", {})
    row = {
        "cik": result["cik"],
        "entity_name": result.get("entity_name", ""),
        "overall": result.get("overall", "NO_DATA"),
        "fail_reasons": "; ".join(result.get("fail_reasons", [])),
        "warn_reasons": "; ".join(result.get("warn_reasons", [])),
        "fail_justification": "",
        "accepted": False,
    }
    row.update(s)

    existing = _load_validation_summary()

    # Preserve fail_justification / accepted from previous row
    if not existing.empty and "cik" in existing.columns:
        prev = existing[existing["cik"] == str(result["cik"])]
        if not prev.empty:
            prev_row = prev.iloc[0]
            prev_just = prev_row.get("fail_justification", "")
            prev_acc = prev_row.get("accepted", False)
            if prev_just and str(prev_just).strip():
                row["fail_justification"] = str(prev_just)
            # Keep accepted=True only if justification is still present
            # and overall is still FAIL (re-validation may fix the issue)
            if result.get("overall") == "PASS":
                row["accepted"] = False
                row["fail_justification"] = ""
            elif prev_acc and str(prev_acc).strip().lower() in ("true", "1"):
                row["accepted"] = True
        existing = existing[existing["cik"] != str(result["cik"])]

    new_row = pd.DataFrame([row])
    updated = pd.concat([existing, new_row], ignore_index=True)
    updated.to_csv(VALIDATION_SUMMARY_FILE, index=False)


def accept_cik(cik: str, justification: str) -> None:
    """Mark a FAIL CIK as accepted with a justification.

    Updates the validation summary CSV and marks the CIK as done in claims.
    """
    cik_stripped = cik.lstrip("0")
    existing = _load_validation_summary()

    if existing.empty or "cik" not in existing.columns:
        print(f"No validation results found. Run --validate-only {cik} first.")
        return

    mask = existing["cik"] == cik_stripped
    if not mask.any():
        print(f"CIK {cik_stripped} not found in validation summary. "
              f"Run --validate-only {cik} first.")
        return

    row = existing.loc[mask].iloc[0]
    overall = row.get("overall", "")
    if overall == "PASS":
        print(f"CIK {cik_stripped} already PASS -- no justification needed.")
        return

    # Update the row
    existing.loc[mask, "fail_justification"] = justification
    existing.loc[mask, "accepted"] = True
    existing.to_csv(VALIDATION_SUMMARY_FILE, index=False)

    # Mark as done in claims
    with _ClaimsLock():
        claims = _load_claims()
        claims[cik_stripped] = "done"
        _save_claims(claims)

    entity = row.get("entity_name", "")
    fail_reasons = row.get("fail_reasons", "")
    print(f"\nCIK {cik_stripped} ({entity}) accepted with justification:")
    print(f"  Overall: {overall}")
    if fail_reasons:
        print(f"  Fail reasons: {fail_reasons}")
    print(f"  Justification: {justification}")
    print(f"  Marked as done in claims.")


# ---------------------------------------------------------------------------
# Validate a template
# ---------------------------------------------------------------------------

def validate_template(cik: str):
    """Validate a v3.0 template by extracting all filings and checking results."""
    from pipeline.html_extract import extract_filing, load_template

    cik_stripped = cik.lstrip("0")
    template = load_template(cik_stripped)

    if template is None:
        print(f"No v3.0 template found for CIK {cik_stripped}")
        return

    print(f"\nTemplate for CIK {cik_stripped}:")
    print(f"  Entity: {template.get('entity_name', 'N/A')}")
    print(f"  Version: {template.get('version', 'N/A')}")
    print(f"  Dollar unit: {template.get('dollar_unit', 1)}")
    print(f"  Columns: {list(template.get('columns', {}).keys())}")
    print(f"  Default tables: {template.get('default', {}).get('tables', [])}")
    n_overrides = len(template.get("filings", {}))
    if n_overrides:
        print(f"  Filing overrides: {n_overrides}")

    # Extract from all cached HTML
    cache_dir = BDC_HTML_CACHE_DIR / cik_stripped
    if not cache_dir.exists():
        print(f"\n  No cached HTML to test extraction")
        return

    html_files = sorted(cache_dir.glob("*.html"))
    if not html_files:
        print(f"\n  No cached HTML to test extraction")
        return

    idx = _load_filings_index()

    for html_file in html_files:
        print(f"\n  Testing: {html_file.name}")
        html = html_file.read_text(encoding="utf-8", errors="replace")

        acc_nodashes = html_file.stem
        filing_row = idx[
            idx["accession_number"].str.replace("-", "") == acc_nodashes
        ]
        if filing_row.empty:
            filing_meta = {
                "cik": cik_stripped,
                "entity_name": template.get("entity_name", ""),
                "accession_number": acc_nodashes,
                "form_type": "10-K",
                "filing_date": "2024-01-01",
                "report_date": "2023-12-31",
            }
        else:
            row = filing_row.iloc[0]
            filing_meta = {
                "cik": cik_stripped,
                "entity_name": row.get("entity_name", ""),
                "accession_number": row.get("accession_number", acc_nodashes),
                "form_type": row.get("form_type", "10-K"),
                "filing_date": row.get("filing_date", ""),
                "report_date": row.get("report_date", ""),
            }

        holdings, stats = extract_filing(html, filing_meta, template)

        print(f"    Holdings: {len(holdings)}")
        print(f"    Tables found: {stats['tables_found']}")

        if holdings:
            from pipeline.html_extract import _parse_dollar, _parse_rate
            dollar_unit = holdings[0].get("dollar_unit", 1) if holdings else 1
            fv_parsed = []
            for h in holdings:
                raw = h.get("fair_value")
                if raw:
                    v = _parse_dollar(raw)
                    if v is not None:
                        fv_parsed.append(v * dollar_unit)
            fv_vals = fv_parsed
            rate_vals = [_parse_rate(h["interest_rate"]) for h in holdings
                         if _parse_rate(h.get("interest_rate")) is not None]
            name_vals = [h["investment_identifier"] for h in holdings
                         if h.get("investment_identifier")]

            total_fv = sum(fv_vals) if fv_vals else 0
            print(f"    FV: {len(fv_vals)}/{len(holdings)} non-null, "
                  f"sum=${total_fv/1e6:,.0f}M")
            if holdings:
                print(f"    Rate: {len(rate_vals)}/{len(holdings)} "
                      f"({len(rate_vals)/len(holdings)*100:.0f}%)")
                print(f"    Names: {len(name_vals)}/{len(holdings)} "
                      f"({len(name_vals)/len(holdings)*100:.0f}%)")

            # Show first 3 holdings
            print(f"    Sample:")
            for h in holdings[:3]:
                inv = (h.get("investment_identifier") or "")[:45]
                inv = inv.encode("ascii", "replace").decode("ascii")
                fv_raw = h.get("fair_value")
                fv_num = _parse_dollar(fv_raw) if fv_raw else None
                if fv_num is not None:
                    fv_num *= dollar_unit
                fv_s = f"${fv_num:>12,.0f}" if fv_num is not None else "        None"
                rate_raw = h.get("interest_rate")
                rate_num = _parse_rate(rate_raw) if rate_raw else None
                rate_s = f"{rate_num:.1f}%" if rate_num is not None else "None"
                print(f"      {inv:<45} FV={fv_s}  Rate={rate_s}")

    # XBRL comparison
    try:
        bdc = _load_bdc_holdings()
        xbrl = bdc[bdc["cik"].str.lstrip("0") == cik_stripped]
        if not xbrl.empty:
            print(f"\n  XBRL comparison:")
            latest_period = xbrl[
                xbrl["period"] == xbrl["report_date"]
            ]["report_date"].max()
            if pd.notna(latest_period):
                xbrl_latest = xbrl[
                    (xbrl["report_date"] == latest_period)
                    & (xbrl["period"] == latest_period)
                ]
                xbrl_fv = pd.to_numeric(
                    xbrl_latest["fair_value"], errors="coerce"
                )
                print(f"    Latest XBRL period: {latest_period}")
                print(f"    XBRL holdings: {len(xbrl_latest)}")
                print(f"    XBRL FV sum: ${xbrl_fv.sum()/1e6:,.0f}M")
    except FileNotFoundError:
        pass

    # Aggregate validation
    from pipeline.validate_html_template import (
        validate_cik as _validate_cik,
        _print_cik_report,
    )
    print("\n" + "=" * 60)
    print("VALIDATION (self-referential + count stability)")
    print("=" * 60)
    result = _validate_cik(cik_stripped)
    _print_cik_report(result)
    _save_validation_result(result)

    s = result.get("summary", {})
    if s.get("median_self_ref_ratio") is not None:
        if s["median_self_ref_ratio"] < 0.85:
            print("\n  ACTION: self-ref ratio < 0.85 -- missing positions.")
            print("  Check: table indices, column mappings")
        elif s["median_self_ref_ratio"] > 1.15:
            print("\n  ACTION: self-ref ratio > 1.15 -- extracting too much.")
            print("  Check: wrong table, dollar_unit, comparative periods")

    if s.get("count_instability", 0) > 0:
        print("\n  ACTION: Position count instability detected.")
        print("  Check: per-filing overrides needed for format changes")

    # Auto-mark as done when validation passes
    if result.get("overall") == "PASS":
        with _ClaimsLock():
            claims = _load_claims()
            claims[cik_stripped] = "done"
            _save_claims(claims)
        print(f"\n  VALIDATED -- CIK {cik_stripped} marked as done.")


# ---------------------------------------------------------------------------
# Progress summary
# ---------------------------------------------------------------------------

def show_progress():
    """Show template validation progress."""
    # Templates with columns (real SOI, not shell companies)
    queue = _get_validation_queue()
    queue_ciks = {e["cik"] for e in queue}

    claims = _load_claims()
    done = {k for k, v in claims.items() if v == "done" and k in queue_ciks}
    claimed = {k for k, v in claims.items()
               if v == "claimed" and k in queue_ciks}
    remaining = queue_ciks - done - claimed

    # Count accepted-with-justification among done CIKs
    summary_df = _load_validation_summary()
    accepted_ciks: set[str] = set()
    if not summary_df.empty and "accepted" in summary_df.columns:
        acc_mask = summary_df["accepted"].astype(str).str.lower().isin(
            ("true", "1")
        )
        accepted_ciks = set(summary_df.loc[acc_mask, "cik"])
    accepted_done = done & accepted_ciks
    pass_done = done - accepted_done

    # Shell companies (templates with no columns)
    all_templates = {f.stem for f in HTML_TEMPLATE_DIR.glob("*.json")
                     if f.stem.isdigit()}
    shells = all_templates - queue_ciks

    print(f"\n{'='*70}")
    print(f"Template Validation Progress")
    print(f"{'='*70}")
    print(f"  Total templates: {len(all_templates)} "
          f"({len(queue_ciks)} with SOI, {len(shells)} shell/empty)")
    print(f"  Validated (PASS): {len(pass_done)}")
    if accepted_done:
        print(f"  Accepted (FAIL):  {len(accepted_done)}")
    print(f"  In progress:      {len(claimed)}")
    print(f"  Not started:      {len(remaining)}")
    if queue_ciks:
        print(f"  Progress: {len(done)}/{len(queue_ciks)} "
              f"({len(done)/len(queue_ciks)*100:.0f}%)")

    # Filing coverage
    idx = _load_filings_index()
    pre_cutoff = idx[idx["report_date"] <= HTML_TEMPLATE_CUTOFF_DATE]
    total_filings = len(pre_cutoff)
    done_filings = pre_cutoff[
        pre_cutoff["cik"].str.lstrip("0").isin(done)
    ]
    print(f"\n  Filing coverage (validated): "
          f"{len(done_filings)}/{total_filings} "
          f"({len(done_filings)/total_filings*100:.0f}%)"
          if total_filings else "")


# ---------------------------------------------------------------------------
# Batch re-validate all templates
# ---------------------------------------------------------------------------

def revalidate_all() -> None:
    """Re-validate every template CIK and save results to summary CSV.

    Preserves existing fail_justification/accepted fields.  Produces a
    triage report at the end: PASS, accepted-FAIL, and needs-attention.
    """
    from pipeline.validate_html_template import (
        validate_cik as _validate_cik,
    )

    template_files = sorted(HTML_TEMPLATE_DIR.glob("*.json"))
    all_ciks = [f.stem for f in template_files if f.stem.isdigit()]

    if not all_ciks:
        print("No templates found.")
        return

    print(f"Re-validating {len(all_ciks)} template CIKs...\n")

    pass_ciks: list[dict] = []
    accepted_ciks: list[dict] = []
    fail_ciks: list[dict] = []
    error_ciks: list[str] = []

    for i, cik in enumerate(all_ciks):
        result = _validate_cik(cik)
        if result.get("error"):
            error_ciks.append(cik)
            if (i + 1) % 25 == 0:
                print(f"  [{i+1}/{len(all_ciks)}] ...")
            continue

        _save_validation_result(result)

        overall = result.get("overall", "NO_DATA")
        entity = result.get("entity_name", "")
        fail_reasons = "; ".join(result.get("fail_reasons", []))

        entry = {"cik": cik, "entity_name": entity,
                 "overall": overall, "fail_reasons": fail_reasons}

        if overall == "PASS":
            pass_ciks.append(entry)
        else:
            # Check if previously accepted
            summary_df = _load_validation_summary()
            if not summary_df.empty and "accepted" in summary_df.columns:
                mask = summary_df["cik"] == cik
                if mask.any():
                    acc = summary_df.loc[mask, "accepted"].iloc[0]
                    if str(acc).strip().lower() in ("true", "1"):
                        accepted_ciks.append(entry)
                        continue
            fail_ciks.append(entry)

        if (i + 1) % 25 == 0:
            print(f"  [{i+1}/{len(all_ciks)}] "
                  f"PASS={len(pass_ciks)} "
                  f"ACCEPTED={len(accepted_ciks)} "
                  f"FAIL={len(fail_ciks)} "
                  f"ERROR={len(error_ciks)}")

    # Triage report
    print(f"\n{'='*70}")
    print("REVALIDATION SUMMARY")
    print(f"{'='*70}")
    print(f"  Total templates:  {len(all_ciks)}")
    print(f"  PASS:             {len(pass_ciks)}")
    print(f"  Accepted (FAIL):  {len(accepted_ciks)}")
    print(f"  FAIL (needs work):{len(fail_ciks)}")
    print(f"  Error/skipped:    {len(error_ciks)}")

    if accepted_ciks:
        print(f"\n--- Accepted FAILs (have justification) ---")
        for e in accepted_ciks:
            print(f"  {e['cik']} ({e['entity_name']}): {e['fail_reasons']}")

    if fail_ciks:
        print(f"\n--- FAILs needing attention ---")
        for e in fail_ciks:
            print(f"  {e['cik']} ({e['entity_name']}): {e['fail_reasons']}")

    print(f"\nResults saved to: {VALIDATION_SUMMARY_FILE}")
    print(f"Next steps:")
    print(f"  - Fix templates for FAIL CIKs, then --validate")
    print(f"  - Or accept structural failures: "
          f"--accept <CIK> --justification \"reason\"")


# ---------------------------------------------------------------------------
# Claim next CIK
# ---------------------------------------------------------------------------

_CLAIMS_LOCK = TEMPLATE_CLAIMS_FILE.with_suffix(".lock")


class _ClaimsLock:
    """File-based lock for atomic read-modify-write of claims JSON."""

    def __enter__(self):
        for i in range(100):
            try:
                fd = os.open(str(_CLAIMS_LOCK),
                             os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.close(fd)
                return self
            except FileExistsError:
                try:
                    age = time.time() - os.path.getmtime(str(_CLAIMS_LOCK))
                    if age > 60:
                        os.unlink(str(_CLAIMS_LOCK))
                        continue
                except OSError:
                    pass
                time.sleep(0.1)
        raise RuntimeError("Could not acquire claims lock after 10s")

    def __exit__(self, *exc):
        try:
            os.unlink(str(_CLAIMS_LOCK))
        except OSError:
            pass


def _load_claims() -> dict:
    if TEMPLATE_CLAIMS_FILE.exists():
        try:
            return json.load(open(TEMPLATE_CLAIMS_FILE))
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def _save_claims(claims: dict):
    tmp = TEMPLATE_CLAIMS_FILE.with_suffix(".tmp")
    with open(tmp, "w") as f:
        json.dump(claims, f, indent=2)
    tmp.replace(TEMPLATE_CLAIMS_FILE)


def _get_validation_queue() -> list[dict]:
    """Return CIKs that have draft templates but need validation, sorted by
    filing count descending (largest first)."""
    existing = {}
    for p in HTML_TEMPLATE_DIR.glob("*.json"):
        if not p.stem.isdigit():
            continue
        try:
            with open(p) as f:
                t = json.load(f)
            cols = t.get("columns", {})
            n_tables = len(t.get("default", {}).get("tables", []))
            existing[p.stem] = {
                "cik": p.stem,
                "name": t.get("entity_name", ""),
                "has_columns": bool(cols),
                "n_tables": n_tables,
            }
        except (json.JSONDecodeError, OSError):
            continue

    # Count filings per CIK from the index
    idx = _load_filings_index()
    pre_cutoff = idx[idx["report_date"] <= HTML_TEMPLATE_CUTOFF_DATE]
    filing_counts = pre_cutoff.groupby(
        pre_cutoff["cik"].str.lstrip("0")
    ).size().to_dict()

    queue = []
    for cik, info in existing.items():
        if not info["has_columns"]:
            continue  # shell companies with no SOI
        info["n_filings"] = filing_counts.get(cik, 0)
        queue.append(info)

    queue.sort(key=lambda x: -x["n_filings"])
    return queue


def claim_next_cik():
    """Claim the next CIK needing validation and print instructions."""
    queue = _get_validation_queue()
    if not queue:
        print("No CIKs with draft templates to validate!")
        return

    with _ClaimsLock():
        claims = _load_claims()

        claimed_cik = None
        for entry in queue:
            cik = entry["cik"]
            if cik not in claims:
                claimed_cik = entry
                break

        if claimed_cik is None:
            n_done = sum(1 for v in claims.values() if v == "done")
            n_claimed = sum(1 for v in claims.values() if v == "claimed")
            print("All CIKs are claimed or done.")
            print(f"  Done: {n_done}, In progress: {n_claimed}, "
                  f"Queue: {len(queue)}")
            return

        claims[claimed_cik["cik"]] = "claimed"
        _save_claims(claims)

    cik = claimed_cik["cik"]
    print(f"CLAIMED CIK: {cik}")
    print(f"  Name: {claimed_cik['name']}")
    print(f"  Filings: {claimed_cik['n_filings']}")
    print(f"  Context: data/raw/filing_templates/{cik}.auto_detect.txt")
    print(f"  Template: data/raw/filing_templates/{cik}.json")
    print(f"\nWorkflow:")
    print(f"  1. Read the context file (summary sections at the top)")
    print(f"  2. Fix template following scripts/learn_template_prompt.md")
    print(f"  3. python scripts/learn_template.py --validate {cik}")


def claim_fix_next():
    """Claim the next FAIL CIK from batch_validate_results.json and print instructions."""
    results_path = Path("data/output/batch_validate_results.json")
    fix_claims_path = Path("data/output/fix_claims.json")

    if not results_path.exists():
        print("No batch validation results found. Run scripts/batch_validate.py first.")
        return

    with open(results_path) as f:
        results = json.load(f)

    # Load existing fix claims
    if fix_claims_path.exists():
        with open(fix_claims_path) as f:
            fix_claims = json.load(f)
    else:
        fix_claims = {}

    # Find next unclaimed FAIL CIK, sorted by filing count (smallest first for faster fixes)
    fail_ciks = []
    for cik, r in results.items():
        if r.get("status") != "FAIL":
            continue
        if fix_claims.get(cik) in ("fixing", "fixed"):
            continue
        filing_count = int(r.get("filing_count", "0") or "0")
        fail_ciks.append((cik, filing_count, r))

    if not fail_ciks:
        n_fixed = sum(1 for v in fix_claims.values() if v == "fixed")
        n_fixing = sum(1 for v in fix_claims.values() if v == "fixing")
        n_fail = sum(1 for r in results.values() if r.get("status") == "FAIL")
        print(f"All FAIL CIKs claimed or fixed.")
        print(f"  Total FAIL: {n_fail}, Fixed: {n_fixed}, In progress: {n_fixing}")
        return

    # Sort by filing count (smallest first)
    fail_ciks.sort(key=lambda x: x[1])
    cik, filing_count, r = fail_ciks[0]

    # Claim it
    fix_claims[cik] = "fixing"
    with open(fix_claims_path, "w") as f:
        json.dump(fix_claims, f, indent=2)
        f.write("\n")

    # Load template to get entity name
    tp = Path(f"data/raw/filing_templates/{cik}.json")
    entity_name = "Unknown"
    if tp.exists():
        with open(tp) as f:
            t = json.load(f)
        entity_name = t.get("entity_name", "Unknown")

    print(f"CLAIMED CIK: {cik}")
    print(f"  Name: {entity_name}")
    print(f"  Filings: {filing_count}")
    print(f"  Fail reasons:")
    for fr in r.get("fail_reasons", []):
        print(f"    - {fr}")
    for wr in r.get("warn_reasons", []):
        print(f"    - WARN: {wr}")
    print(f"  Ratio: {r.get('ratio', '?')}, In-range: {r.get('in_range', '?')}")
    print(f"  FV fill: {r.get('median_fv_fill', '?')}, Carry: {r.get('median_carry', '?')}")
    print(f"  Count instability: {r.get('count_instability', '?')}")
    print(f"\n  Template: data/raw/filing_templates/{cik}.json")
    print(f"  Context: data/raw/filing_templates/{cik}.auto_detect.txt")
    print(f"  Prompt: prompts/html_extraction/fix_template_agent_prompt.md")
    print(f"\nWorkflow:")
    print(f"  1. python scripts/learn_template.py --validate {cik}")
    print(f"  2. Diagnose and fix template (see prompt)")
    print(f"  3. Re-validate until PASS")
    print(f"  4. python scripts/learn_template.py --fix-done {cik}")

    n_remaining = len(fail_ciks) - 1
    print(f"\n  Remaining FAIL CIKs: {n_remaining}")


def mark_fix_done(cik: str):
    """Mark a CIK as fixed after validation passes."""
    fix_claims_path = Path("data/output/fix_claims.json")
    if fix_claims_path.exists():
        with open(fix_claims_path) as f:
            fix_claims = json.load(f)
    else:
        fix_claims = {}

    cik_stripped = cik.lstrip("0")
    fix_claims[cik_stripped] = "fixed"
    with open(fix_claims_path, "w") as f:
        json.dump(fix_claims, f, indent=2)
        f.write("\n")

    # Also update template_claims to "done"
    claims = _load_claims()
    if cik_stripped in claims:
        claims[cik_stripped] = "done"
        _save_claims(claims)

    print(f"CIK {cik_stripped} marked as fixed.")


# ---------------------------------------------------------------------------
# Auto-detect SOI tables
# ---------------------------------------------------------------------------

# Keywords for SOI table scoring
_SOI_KEYWORDS_HIGH = {
    "fair value", "cost", "principal", "amortized cost",
    "schedule of investments",
}
_SOI_KEYWORDS_MED = {
    "maturity", "portfolio company", "issuer", "borrower", "company",
    "shares", "industry", "rate", "spread", "coupon",
    "par amount", "par value", "investment type", "investment",
}
_SOI_KEYWORDS_NEG = {
    "total return", "page", "item 1", "table of contents",
    "per share", "balance sheet", "statement of operations",
    "financial highlights", "selected financial", "roll forward",
    "fair value hierarchy",
}


def _score_table_soi(grid: list, min_rows: int = 5) -> tuple[int, int]:
    """Score a single table grid for schedule-of-investments likelihood.

    Returns (score, best_header_row).
    """
    return _shared_score_table_soi(grid, min_rows=min_rows)


def _group_continuation_tables(
    scored_tables: list[tuple[int, int, int, int]],
) -> list[list[int]]:
    """Group scored tables into continuation chains.

    Args:
        scored_tables: list of (table_idx, score, width, header_row) for one filing.
            Only tables with score >= threshold should be passed in.

    Returns:
        List of table groups, each group = list of table indices.
        Groups are formed by width similarity and index adjacency.

    Adjacent tables with similar width (within 6) and index gap <= 5
    are grouped. The gap of 5 handles SOI schedules where 1-2 non-SOI
    tables (FV totals, footnotes) interrupt the sequence.
    """
    return _shared_group_continuation_tables(scored_tables)


_MONTH_NAMES = {
    "january": 1, "february": 2, "march": 3, "april": 4,
    "may": 5, "june": 6, "july": 7, "august": 8,
    "september": 9, "october": 10, "november": 11, "december": 12,
}

_PERIOD_DATE_RE = re.compile(
    r"(?:" + "|".join(_MONTH_NAMES) + r")[\s\xa0]+(\d{1,2})\s*,?\s*(\d{4})",
    re.IGNORECASE,
)


def _parse_period_date(text: str) -> str | None:
    """Parse a date like 'March 31, 2023' from text. Returns 'YYYY-MM-DD' or None."""
    return _shared_parse_period_date(text)


_SOI_RE = re.compile(r"schedule\s+of\s+investments", re.IGNORECASE)
_TABLE_OPEN_RE = re.compile(r"<table[\s>]", re.IGNORECASE)
_HTML_TAG_RE = re.compile(r"<[^>]+>")


def _find_soi_date_markers(
    raw_html: str,
) -> list[tuple[int, str]]:
    """Find 'Schedule of Investments' headings with dates in raw HTML.

    Scans the HTML for SOI headings, extracts the date within 500 chars
    after each heading (stripping tags and decoding entities), and maps
    each to the table index it precedes.

    Table indices match ``soup.find_all("table")`` / ``_extract_tables()``
    order (every ``<table>`` tag in document order, including nested).

    Returns list of (table_index, date_str) tuples.
    """
    return _shared_find_soi_date_markers(raw_html)


def _detect_periods_from_html(
    html_path: Path,
    soi_table_indices: list[int],
    report_date: str,
) -> dict[str, list[int]] | None:
    """Detect current vs comparative periods from inter-table paragraph text.

    Scans raw HTML for 'Schedule of Investments' headings with dates,
    then assigns each SOI table to the nearest preceding date marker.
    Works for both 10-Q and 10-K filings.

    Returns {date_str: [table_indices...]} or None if detection fails.
    """
    if not soi_table_indices or len(soi_table_indices) < 2:
        return None

    try:
        raw_html = html_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    return _shared_detect_periods_from_html_text(raw_html, soi_table_indices)


def _detect_10k_periods(
    table_groups: list[list[int]],
    report_date: str,
) -> dict | None:
    """For 10-K filings with 2 SOI table groups, split into current/comparative.

    Returns table_periods dict or None if not applicable.
    """
    return _shared_detect_10k_periods(table_groups, report_date)


def _auto_detect_dollar_unit(
    cik: str,
    sample_filing_acc: str,
    grids: list,
    columns: dict,
    header_row: int,
    table_indices: list[int],
) -> tuple[int, str]:
    """Auto-detect dollar unit for a CIK.

    Tries companyfacts comparison first, then HTML text search.
    Returns (dollar_unit, rationale_string).
    """
    from pipeline.html_extract import _parse_dollar
    from pipeline.validate_html_template import (
        _fetch_companyfacts,
        _find_investment_fv_series,
        _auto_detect_unit,
    )

    # Try to get a FV sum from sample tables
    fv_col_spec = columns.get("fair_value")
    if fv_col_spec is None:
        return (1, "no fair_value column mapped")

    fv_col = fv_col_spec["col"] if isinstance(fv_col_spec, dict) else fv_col_spec

    # Sum FV from sample tables in the filing
    raw_fv_sum = 0.0
    count = 0
    for tidx in table_indices:
        # Find the table in grids
        table_grid = None
        for t in grids:
            if t["index"] == tidx:
                table_grid = t["grid"]
                break
        if not table_grid:
            continue
        for ri in range(header_row + 1, len(table_grid)):
            row = table_grid[ri]
            cell = _get_cell_from_grid(row, fv_col)
            val = _parse_dollar(cell)
            if val is not None and val > 0:
                raw_fv_sum += val
                count += 1

    if raw_fv_sum == 0:
        return (1, f"no FV values found in sample (0/{count} cells)")

    # Try companyfacts
    cik_padded = cik.zfill(10)
    cache_path = Path(str(COMPANYFACTS_CACHE_DIR)) / f"{cik_padded}.json"
    if cache_path.exists():
        try:
            with open(cache_path) as f:
                facts = json.load(f)
            fv_series = _find_investment_fv_series(facts)
            if fv_series:
                # Find the closest XBRL aggregate to compare
                xbrl_values = list(fv_series.values())
                # Use median as reference
                xbrl_ref = sorted(xbrl_values)[len(xbrl_values) // 2]
                adj_ratio, best_mult, raw_ratio = _auto_detect_unit(
                    raw_fv_sum, xbrl_ref,
                )
                # Convert multiplier to dollar_unit
                # _auto_detect_unit returns the multiplier to APPLY to html_sum
                # dollar_unit is the multiplier applied during extraction
                # So if best_mult = 1000, it means html values are 1000x too small
                # -> dollar_unit = 1000
                if best_mult == 1e-6:
                    unit = 1000000
                elif best_mult == 1e-3:
                    unit = 1000
                elif best_mult == 1:
                    unit = 1
                elif best_mult == 1e3:
                    # html values are 1000x too large -- unusual
                    unit = 1
                elif best_mult == 1e6:
                    # html values are 1M too large -- unusual
                    unit = 1
                else:
                    unit = 1
                rationale = (
                    f"companyfacts ratio: {adj_ratio:.2f}x "
                    f"(html_sum=${raw_fv_sum:,.0f}, xbrl_ref=${xbrl_ref:,.0f}, "
                    f"mult={best_mult})"
                )
                return (unit, rationale)
        except (json.JSONDecodeError, OSError):
            pass

    # Fallback: check HTML text for "in thousands" / "in millions"
    # Look at the sample filing HTML
    html_path = BDC_HTML_CACHE_DIR / cik / f"{sample_filing_acc}.html"
    if html_path.exists():
        try:
            text = html_path.read_text(encoding="utf-8", errors="replace")[:50000]
            text_lower = text.lower()
            if "in thousands" in text_lower or "(in 000s)" in text_lower:
                return (1000, "HTML text contains 'in thousands'")
            if "in millions" in text_lower:
                return (1000000, "HTML text contains 'in millions'")
        except OSError:
            pass

    return (1, f"default (html_fv_sum=${raw_fv_sum:,.0f}, no companyfacts)")


def _safe_ascii(text: str) -> str:
    """Convert text to safe ASCII for Windows cp1252 console output."""
    return text.encode("ascii", "replace").decode("ascii")


def _table_snippet(grid: list[list[str]], max_len: int = 80) -> str:
    """One-line summary of a table's content for context display."""
    # Gather first non-empty row's text
    for row in grid[:3]:
        cells = [c.strip() for c in row if c.strip()]
        if cells:
            text = " | ".join(cells)
            if len(text) > max_len:
                text = text[:max_len - 3] + "..."
            return _safe_ascii(text)
    return "(empty)"


def _get_cell_from_grid(row: list[str], col: int) -> str:
    """Read cell from a grid row, handling $ split. Simplified _get_cell for grids."""
    if col < 0 or col >= len(row):
        return ""
    val = row[col].strip()
    if val == "$" and col + 1 < len(row):
        val = row[col + 1].strip()
    elif not val and col + 1 < len(row):
        val = row[col + 1].strip()
    if val and val.startswith("$") and len(val) > 1:
        val = val[1:].strip()
    return val


def auto_detect_cik(cik: str, save_context: bool = True):
    """Auto-detect SOI tables for a CIK and write a draft template.

    Scores every table in every filing, identifies SOI tables, auto-maps
    columns, detects dollar_unit, and writes a complete draft template.

    If save_context=True, also writes the context output to
    data/raw/filing_templates/<CIK>.auto_detect.txt for later review
    by a Claude Code instance (no re-running needed).
    """
    import io
    import contextlib

    # Capture all output to both stdout and a file
    output_buf = io.StringIO() if save_context else None

    class _Tee:
        """Write to both stdout and buffer."""
        def __init__(self, buf):
            self._buf = buf
            self._stdout = sys.stdout
        def write(self, s):
            try:
                self._stdout.write(s)
            except UnicodeEncodeError:
                self._stdout.write(s.encode('ascii', 'replace').decode('ascii'))
            if self._buf:
                self._buf.write(s)
        def flush(self):
            self._stdout.flush()

    old_stdout = sys.stdout
    if save_context:
        sys.stdout = _Tee(output_buf)
    cik_stripped = cik.lstrip("0")
    cache_dir = BDC_HTML_CACHE_DIR / cik_stripped
    idx = _load_filings_index()

    # Get filing metadata -- ALL filings up to the XBRL universality cutoff
    # (includes filings that have XBRL -- we want HTML templates for the
    # entire period so both sources can be cross-validated)
    cik_filings = idx[
        (idx["cik"].str.lstrip("0") == cik_stripped)
        & (idx["report_date"] <= HTML_TEMPLATE_CUTOFF_DATE)
    ].sort_values("filing_date")

    if cik_filings.empty:
        print(f"No filings found for CIK {cik_stripped} "
              f"before {HTML_TEMPLATE_CUTOFF_DATE}")
        return

    entity_name = cik_filings.iloc[0]["entity_name"]
    print(f"\nAUTO-DETECT: CIK {cik_stripped} - {entity_name}")
    print(f"  {len(cik_filings)} filings through {HTML_TEMPLATE_CUTOFF_DATE}")

    # Step 1: Ensure grids exist
    grids_files = list(cache_dir.glob("*.grids.json")) if cache_dir.exists() else []
    if len(grids_files) < len(cik_filings) * 0.5:
        print(f"  Grids incomplete ({len(grids_files)}/{len(cik_filings)}), "
              f"running prepare...")
        prepare_cik(cik_stripped)
        grids_files = list(cache_dir.glob("*.grids.json"))

    print(f"  {len(grids_files)} grids loaded\n")

    # Step 2: Score every table in every filing
    filing_results: list[dict] = []  # per-filing scoring results
    all_soi_widths: dict[int, list] = {}  # width -> [(acc, tidx, score, hr, grid)]

    for _, filing in cik_filings.iterrows():
        acc = filing["accession_number"]
        acc_nodashes = acc.replace("-", "")
        form_type = filing.get("form_type", "")
        report_date = filing.get("report_date", "")

        grids = _load_grids(cik_stripped, acc_nodashes)
        if not grids:
            filing_results.append({
                "acc": acc, "acc_nodashes": acc_nodashes,
                "form_type": form_type, "report_date": report_date,
                "filing_date": filing.get("filing_date", ""),
                "tables": [], "scored": [], "groups": [],
                "status": "no_grids",
            })
            continue

        # Score each table
        scored: list[tuple[int, int, int, int]] = []  # (tidx, score, width, hr)
        for t in grids:
            tidx = t["index"]
            grid = t["grid"]
            score, hr = _score_table_soi(grid)
            if score >= 8:  # Loose threshold for candidates
                width = t["width"]
                scored.append((tidx, score, width, hr))
                # Track for width-based column mapping
                if width not in all_soi_widths:
                    all_soi_widths[width] = []
                all_soi_widths[width].append((acc_nodashes, tidx, score, hr, grid))

        # Group into continuation chains (only tables scoring >= 10)
        high_scored = [(t, s, w, h) for t, s, w, h in scored if s >= 10]
        groups = _group_continuation_tables(high_scored)

        # Select the best SOI group(s) -- not ALL high-scoring groups.
        # The SOI schedule is the LARGEST continuation chain (most tables).
        # For 10-K: pick the two largest groups (current + comparative).
        # For 10-Q: pick the largest group by table count (the SOI always
        # has the most continuation pages). If tied, prefer the first by index.
        group_info: list[tuple[int, int, int, int]] = []  # (group_idx, n_tables, total_rows, first_tidx)
        for gi, group in enumerate(groups):
            total_rows = 0
            for tidx in group:
                for t in (grids or []):
                    if t["index"] == tidx:
                        total_rows += t["rows"]
                        break
            group_info.append((gi, len(group), total_rows, group[0]))

        # For 10-K: take the two largest groups (current + comparative)
        if "10-K" in form_type and len(group_info) >= 2:
            # Sort by table count descending, then total rows
            by_size = sorted(group_info, key=lambda x: (-x[1], -x[2]))
            selected_groups = [
                groups[by_size[0][0]],
                groups[by_size[1][0]],
            ]
            # Sort by table index (lower = current, higher = comparative)
            selected_groups.sort(key=lambda g: g[0])
        elif group_info:
            # For 10-Q: prefer the FIRST group by index (current period
            # always comes before comparative in SEC filings). But if the
            # first group is a single table (likely a title/summary, not
            # the actual SOI), fall through to the LARGEST group.
            first_gi = min(group_info, key=lambda x: x[3])
            if first_gi[1] >= 2:
                # First group has 2+ tables -- trust it as the SOI
                selected_groups = [groups[first_gi[0]]]
            else:
                # First group is a single table -- use largest instead.
                # Tiebreak: prefer lowest first_tidx (current period comes
                # before comparative in SEC filings).
                best_gi = max(group_info, key=lambda x: (x[1], -x[3]))[0]
                selected_groups = [groups[best_gi]]
        else:
            selected_groups = []

        # Detect comparative period tables via inter-table paragraph text
        table_periods = None
        period_method = None
        html_path = cache_dir / f"{acc_nodashes}.html"
        all_selected = [t for g in selected_groups for t in g]
        if html_path.exists() and len(all_selected) >= 2:
            table_periods = _detect_periods_from_html(
                html_path, all_selected, report_date,
            )
            if table_periods:
                period_method = "html"
        # Fallback: gap-based detection for 10-K
        if table_periods is None and "10-K" in form_type and len(selected_groups) == 2:
            table_periods = _detect_10k_periods(selected_groups, report_date)
            if table_periods:
                period_method = "gap"

        # Final table list: use current period tables only when periods detected
        if table_periods and report_date in table_periods:
            final_tables = table_periods[report_date]
        else:
            final_tables = [t for g in selected_groups for t in g]

        filing_results.append({
            "acc": acc, "acc_nodashes": acc_nodashes,
            "form_type": form_type, "report_date": report_date,
            "filing_date": filing.get("filing_date", ""),
            "tables": final_tables,
            "scored": scored,
            "groups": groups,
            "table_periods": table_periods,
            "period_method": period_method,
            "status": "ok" if final_tables else "no_soi",
        })

    # Step 3: Build per-filing context into a buffer (printed AFTER summary)
    # Group filings by table pattern to reduce noise -- show full context
    # for the first occurrence of each pattern and for outliers only.
    _detail_lines: list[str] = []  # buffered per-filing detail
    low_confidence = []
    shown_patterns: dict[str, int] = {}  # pattern -> count of filings shown
    pattern_filings: dict[str, list] = {}  # pattern -> list of filing_results

    for fr in filing_results:
        _d = _detail_lines.append  # shorthand
        status_tag = ""
        if fr["status"] == "no_grids":
            status_tag = " [NO GRIDS]"
        elif fr["status"] == "no_soi":
            status_tag = " [NO SOI TABLES]"
            low_confidence.append(fr)

        if not fr["tables"]:
            if fr["status"] != "no_grids":
                _d(f"\n  {fr['filing_date']}  {fr['form_type']:<8}  "
                   f"{fr['acc']}{status_tag}")
            if fr["scored"] and max(s for _, s, _, _ in fr["scored"]) < 10:
                low_confidence.append(fr)
            continue

        # Determine if this pattern has been shown with full context.
        # The key includes table indices + widths + header text so that any
        # structural change (different table widths, shifted columns, changed
        # headers) gets its own full context block.
        _struct_parts = [str(fr["tables"])]
        for tidx, _sc, w, hr in fr["scored"]:
            if tidx in fr["tables"]:
                _struct_parts.append(f"{tidx}:w{w}")
        # Add header text from first selected table
        _hdr_key = ""
        grids_for_key = _load_grids(cik_stripped, fr["acc_nodashes"])
        if grids_for_key and fr["tables"]:
            first_t = next(
                (t for t in grids_for_key if t["index"] == min(fr["tables"])),
                None,
            )
            if first_t:
                hr_for_key = 0
                for tidx, _, _, h in fr["scored"]:
                    if tidx == min(fr["tables"]):
                        hr_for_key = h
                        break
                if hr_for_key < len(first_t["grid"]):
                    _hdr_key = "|".join(
                        c.strip()[:15] for c in first_t["grid"][hr_for_key]
                        if c.strip()
                    )
                _struct_parts.append(_hdr_key)
        pattern_key = ";;".join(_struct_parts)
        show_full = pattern_key not in shown_patterns

        # Always show the line
        _d(f"\n  {fr['filing_date']}  {fr['form_type']:<8}  "
           f"{fr['acc']}")
        _d(f"    -> tables: {fr['tables']}")
        if fr.get("table_periods"):
            tp = fr["table_periods"]
            method = fr.get("period_method", "")
            method_tag = f" [{method}]" if method else ""
            _d(f"    -> table_periods{method_tag}: {tp}")

        shown_patterns[pattern_key] = shown_patterns.get(pattern_key, 0) + 1
        pattern_filings.setdefault(pattern_key, []).append(fr)

        if not show_full:
            # Skip context for repeated patterns
            if fr["scored"] and max(s for _, s, _, _ in fr["scored"]) < 10:
                low_confidence.append(fr)
            continue

        # Show context: tables immediately before/after the selection
        grids = _load_grids(cik_stripped, fr["acc_nodashes"])
        if not grids:
            continue

        first_sel = min(fr["tables"])
        last_sel = max(fr["tables"])

        # Context BEFORE: 2 tables preceding the selection
        before_tables = [
            t for t in grids
            if t["index"] < first_sel and t["index"] >= first_sel - 3
        ]
        if before_tables:
            _d("    BEFORE:")
            for t in sorted(before_tables, key=lambda x: x["index"]):
                snippet = _table_snippet(t["grid"])
                _d(f"      Table {t['index']:>3} (w={t['width']:>2}, "
                   f"{t['rows']:>3}r): {snippet}")

        # First selected table: header + first 2 data rows
        sel_table = next(
            (t for t in grids if t["index"] == first_sel), None
        )
        if sel_table:
            g = sel_table["grid"]
            # Find header row from scored
            hr = 0
            for tidx, _, _, h in fr["scored"]:
                if tidx == first_sel:
                    hr = h
                    break
            # Show header
            if hr < len(g):
                hdr_cells = [c.strip() for c in g[hr] if c.strip()][:8]
                hdr_text = _safe_ascii(" | ".join(hdr_cells))
                _d(f"    HEADER (Table {first_sel}, row {hr}): {hdr_text}")
            # Show 2 data rows
            shown = 0
            for ri in range(hr + 1, min(hr + 15, len(g))):
                row = g[ri]
                nonempty = [c.strip() for c in row if c.strip()]
                if len(nonempty) < 2:
                    continue
                cells = [c.strip()[:20] for c in row if c.strip()][:6]
                line = _safe_ascii(" | ".join(cells))
                _d(f"    DATA row {ri}: {line}")
                shown += 1
                if shown >= 2:
                    break

        # Context AFTER: 2 tables following the selection
        after_tables = [
            t for t in grids
            if t["index"] > last_sel and t["index"] <= last_sel + 3
        ]
        if after_tables:
            _d("    AFTER:")
            for t in sorted(after_tables, key=lambda x: x["index"])[:2]:
                snippet = _table_snippet(t["grid"])
                _d(f"      Table {t['index']:>3} (w={t['width']:>2}, "
                   f"{t['rows']:>3}r): {snippet}")

        # Show high-scoring tables NOT in selection with their own context
        excluded_high = [
            (tidx, score, w, hr)
            for tidx, score, w, hr in fr["scored"]
            if tidx not in fr["tables"] and score >= 10
        ]
        if excluded_high:
            # Group excluded tables into contiguous runs
            excluded_runs: list[list[tuple]] = []
            for item in sorted(excluded_high, key=lambda x: x[0]):
                if (excluded_runs and
                        item[0] - excluded_runs[-1][-1][0] <= 5 and
                        abs(item[2] - excluded_runs[-1][0][2]) <= 6):
                    excluded_runs[-1].append(item)
                else:
                    excluded_runs.append([item])

            for run in excluded_runs[:3]:  # Show up to 3 excluded groups
                run_indices = [t[0] for t in run]
                run_first = run_indices[0]
                run_last = run_indices[-1]
                # Before context for this excluded group
                exc_before = [
                    t for t in grids
                    if t["index"] < run_first and t["index"] >= run_first - 2
                ]
                # After context
                exc_after = [
                    t for t in grids
                    if t["index"] > run_last and t["index"] <= run_last + 2
                ]
                # First table header/data
                exc_table = next(
                    (t for t in grids if t["index"] == run_first), None
                )

                _d(f"    ALSO SCORED HIGH: {run_indices} "
                   f"(score={run[0][1]}, w={run[0][2]})")
                if exc_before:
                    b = sorted(exc_before, key=lambda x: x["index"])[-1]
                    _d(f"      before: Table {b['index']:>3} "
                       f"({b['rows']}r): "
                       f"{_table_snippet(b['grid'], 60)}")
                if exc_table:
                    g = exc_table["grid"]
                    hr = run[0][3]
                    if hr < len(g):
                        hdr_cells = [c.strip() for c in g[hr] if c.strip()][:6]
                        _d(f"      header: "
                           f"{_safe_ascii(' | '.join(hdr_cells))}")
                    # First data row
                    for ri in range(hr + 1, min(hr + 10, len(g))):
                        row = g[ri]
                        nonempty = [c.strip() for c in row if c.strip()]
                        if len(nonempty) >= 2:
                            cells = [c.strip()[:18] for c in row
                                     if c.strip()][:5]
                            _d(f"      data:   "
                               f"{_safe_ascii(' | '.join(cells))}")
                            break
                if exc_after:
                    a = sorted(exc_after, key=lambda x: x["index"])[0]
                    _d(f"      after:  Table {a['index']:>3} "
                       f"({a['rows']}r): "
                       f"{_table_snippet(a['grid'], 60)}")

    # Step 4: Determine default tables
    # Find the most common table pattern among 10-Q filings
    tenq_patterns: dict[str, int] = {}
    for fr in filing_results:
        if "10-Q" in fr["form_type"] and fr["tables"]:
            key = str(fr["tables"])
            tenq_patterns[key] = tenq_patterns.get(key, 0) + 1

    if tenq_patterns:
        # Most common pattern
        default_tables_str = max(tenq_patterns, key=tenq_patterns.get)
        default_tables = json.loads(default_tables_str)
    else:
        # Fall back to first filing with tables
        default_tables = []
        for fr in filing_results:
            if fr["tables"]:
                default_tables = fr["tables"]
                break

    # Step 5: Determine default header_row
    # Most common header row across all SOI tables
    hr_counts: dict[int, int] = {}
    for fr in filing_results:
        for _, _, _, hr in fr["scored"]:
            hr_counts[hr] = hr_counts.get(hr, 0) + 1
    default_header_row = max(hr_counts, key=hr_counts.get) if hr_counts else 0

    # Step 6: Auto-map columns using the best representative table per width
    # Pick the most common width among SOI tables
    width_counts: dict[int, int] = {}
    for fr in filing_results:
        for tidx in fr["tables"]:
            for t, s, w, h in fr["scored"]:
                if t == tidx:
                    width_counts[w] = width_counts.get(w, 0) + 1

    columns = {}
    columns_by_width = {}

    if all_soi_widths:
        # Primary width: most common
        primary_width = max(width_counts, key=width_counts.get) if width_counts else None

        # Only process widths that appear in at least 3 filing tables
        # (filters out note tables, FV hierarchy tables, etc.)
        significant_widths = {
            w for w, cnt in width_counts.items() if cnt >= 3
        }
        # Always include primary width
        if primary_width:
            significant_widths.add(primary_width)

        for w, samples in sorted(all_soi_widths.items()):
            if w not in significant_widths:
                continue

            # Pick the table with highest score for this width
            best = max(samples, key=lambda x: x[2])
            acc_nd, tidx, score, hr, grid = best

            # Get data rows for column mapping
            data_rows = grid[hr + 1: min(hr + 20, len(grid))]

            # Map columns using header text
            hdr = grid[hr] if hr < len(grid) else []
            width_columns = {}
            for hpos, cell in enumerate(hdr):
                text = cell.strip()
                if not text:
                    continue
                field = _match_header_to_field(text)
                if field is None:
                    continue
                data_pos = _find_data_position(grid, hpos, field, data_rows)
                if data_pos is not None:
                    spec = {"col": data_pos}
                    # Store the actual header text (lowercased) for this
                    # filer, not the universal canonical pattern
                    spec["header"] = text.lower()
                    width_columns[field] = spec

            if w == primary_width or not columns:
                columns = width_columns
            elif width_columns != columns:
                # Only store as width override if different from base
                diff = {}
                for field, spec in width_columns.items():
                    if field not in columns or columns[field] != spec:
                        diff[field] = spec
                if diff:
                    columns_by_width[str(w)] = diff

    # Step 7: Auto-detect dollar_unit
    # Find a good sample filing
    sample_acc = ""
    sample_tables = []
    sample_grids = None
    for fr in filing_results:
        if fr["tables"] and fr["status"] == "ok":
            sample_acc = fr["acc_nodashes"]
            sample_tables = fr["tables"]
            sample_grids = _load_grids(cik_stripped, sample_acc)
            break

    dollar_unit = 1
    unit_rationale = "default"
    if sample_grids and columns:
        dollar_unit, unit_rationale = _auto_detect_dollar_unit(
            cik_stripped, sample_acc, sample_grids, columns,
            default_header_row, sample_tables,
        )

    # Step 8: Build per-filing overrides
    filings_overrides = {}
    for fr in filing_results:
        if fr["status"] == "no_grids":
            continue

        tables = fr["tables"]
        override: dict = {}

        # Tables override if different from default
        if tables != default_tables:
            override["tables"] = tables

        # table_periods
        if fr.get("table_periods"):
            override["table_periods"] = fr["table_periods"]

        if override:
            filings_overrides[fr["acc"]] = override

    # Step 9: Write draft template
    template = {
        "version": "3.0",
        "cik": cik_stripped,
        "entity_name": entity_name,
        "dollar_unit": dollar_unit,
        "columns": columns,
    }
    if columns_by_width:
        template["columns_by_width"] = columns_by_width

    template["default"] = {
        "tables": default_tables,
        "header_row": default_header_row,
    }

    if filings_overrides:
        template["filings"] = filings_overrides

    # Write to disk
    template_path = HTML_TEMPLATE_DIR / f"{cik_stripped}.json"
    with open(template_path, "w") as f:
        json.dump(template, f, indent=2)

    # Step 10: Print summary (summary sections first, per-filing detail last)

    # 10a: PATTERN SUMMARY
    n_with_soi = sum(1 for fr in filing_results if fr["tables"])
    print(f"\n{'='*70}")
    print(f"PATTERN SUMMARY: {len(pattern_filings)} unique patterns "
          f"across {n_with_soi} filings with SOI tables")
    for pk, members in sorted(pattern_filings.items(),
                               key=lambda x: -len(x[1])):
        is_default = (members[0]["tables"] == default_tables)
        tag = " ** DEFAULT" if is_default else ""
        dates = [m["filing_date"] for m in members]
        forms = [m["form_type"] for m in members]
        form_summary = ", ".join(
            f"{forms.count(f)} {f}" for f in sorted(set(forms))
        )
        if len(members) <= 3:
            # Show individual filings
            print(f"\n  {pk}: {len(members)} filing(s){tag}")
            for m in members:
                print(f"    {m['filing_date']}  {m['form_type']}  {m['acc']}")
        else:
            print(f"\n  {pk}: {len(members)} filing(s){tag}")
            print(f"    {dates[0]} to {dates[-1]}  ({form_summary})")
    # Flag suspicious patterns (very narrow width = likely wrong table)
    for pk, members in pattern_filings.items():
        for m in members:
            for tidx, _, w, _ in m["scored"]:
                if tidx in m["tables"] and w <= 4:
                    print(f"  ** SUSPICIOUS: {m['acc']} table {tidx} "
                          f"width={w} (too narrow for SOI)")
                    break

    # 10b: COLUMN MAPPING
    print(f"\n{'='*70}")
    print(f"COLUMN MAPPING (primary width={primary_width if width_counts else '?'}, "
          f"header_row={default_header_row}):")
    for field, spec in sorted(columns.items()):
        col = spec["col"] if isinstance(spec, dict) else spec
        print(f"  {field:<25} col {col}")

    if columns_by_width:
        print(f"\nWIDTH OVERRIDES:")
        for w, cols in sorted(columns_by_width.items()):
            print(f"  width={w}: {cols}")

    # Per-field column verification: show what each mapped column reads
    # from actual data rows so the instance can verify correctness.
    if sample_grids and sample_tables and columns:
        from pipeline.html_extract import (
            _parse_dollar as _pd, _parse_rate as _pr, _convert_date as _cd,
        )
        # Collect all active column sets (base + each width override)
        col_sets: list[tuple[str, dict]] = [("base", columns)]
        for wk, diff in columns_by_width.items():
            merged = dict(columns)
            merged.update(diff)
            col_sets.append((f"w={wk}", merged))

        for label, col_map in col_sets:
            # Find a sample table matching this width
            target_w = None
            if label.startswith("w="):
                target_w = int(label[2:])

            sample_grid = None
            sample_tidx = None
            for t in sample_grids:
                if t["index"] in sample_tables:
                    g = t["grid"]
                    w = len(g[0]) if g else 0
                    if target_w is None or w == target_w:
                        sample_grid = g
                        sample_tidx = t["index"]
                        break

            if not sample_grid:
                # Try any grids file for this width
                if target_w:
                    for fr in filing_results:
                        if fr["status"] != "ok":
                            continue
                        fg = _load_grids(cik_stripped, fr["acc_nodashes"])
                        if not fg:
                            continue
                        for t in fg:
                            if t["index"] in fr["tables"]:
                                g = t["grid"]
                                w = len(g[0]) if g else 0
                                if w == target_w:
                                    sample_grid = g
                                    sample_tidx = t["index"]
                                    break
                        if sample_grid:
                            break
            if not sample_grid:
                continue

            print(f"\nCOLUMN VERIFICATION ({label}, Table {sample_tidx}):")

            # Show 3 data rows with per-field breakdown
            shown = 0
            for ri in range(default_header_row + 1, len(sample_grid)):
                row = sample_grid[ri]
                # Skip empty rows
                nonempty = sum(1 for c in row if c.strip())
                if nonempty < 2:
                    continue

                print(f"  Row {ri}:")
                for field in sorted(col_map.keys()):
                    spec = col_map[field]
                    col_idx = spec["col"] if isinstance(spec, dict) else spec
                    raw = _get_cell_from_grid(row, col_idx)
                    raw_safe = raw.encode("ascii", "replace").decode("ascii")[:40]

                    # Show parsed value
                    parsed = ""
                    if field in _DOLLAR_FIELDS:
                        v = _pd(raw)
                        if v is not None:
                            parsed = f" -> ${v * dollar_unit:,.0f}"
                    elif field in _RATE_FIELDS:
                        v = _pr(raw)
                        if v is not None:
                            parsed = f" -> {v}"
                    elif field == "maturity_date":
                        v = _cd(raw) if raw else None
                        if v:
                            parsed = f" -> {v}"

                    print(f"    {field:<25} col {col_idx:>2}  "
                          f"\"{raw_safe}\"{parsed}")

                shown += 1
                if shown >= 3:
                    break

    print(f"\nDOLLAR UNIT: {dollar_unit} ({unit_rationale})")

    # Low confidence warnings
    if low_confidence:
        print(f"\nLOW CONFIDENCE ({len(low_confidence)} filings, review these):")
        for fr in low_confidence[:10]:
            max_score = max((s for _, s, _, _ in fr["scored"]), default=0)
            print(f"  {fr['filing_date']}  {fr['form_type']:<8}  "
                  f"{fr['acc']}  max_score={max_score}")

    # Statistics
    n_with_tables = sum(1 for fr in filing_results if fr["tables"])
    n_no_soi = sum(1 for fr in filing_results if fr["status"] == "no_soi")
    n_overrides = len(filings_overrides)

    print(f"\nDRAFT TEMPLATE SAVED: {template_path}")
    print(f"  Default tables: {default_tables}")
    print(f"  Per-filing overrides: {n_overrides}")
    print(f"  Filings with SOI tables: {n_with_tables}/{len(filing_results)}")
    print(f"  Filings with no SOI tables: {n_no_soi}")

    print(f"\nNext: Review low-confidence filings, then run:")
    print(f"  python scripts/learn_template.py --validate {cik_stripped}")

    # 10f: PER-FILING DETAIL (reference section at the end)
    if _detail_lines:
        print(f"\n{'='*70}")
        print(f"PER-FILING DETAIL (reference -- {len(filing_results)} filings):")
        print(f"{'='*70}")
        for line in _detail_lines:
            print(line)

    # Save context output to file for offline review
    if save_context and output_buf:
        sys.stdout = old_stdout
        context_path = HTML_TEMPLATE_DIR / f"{cik_stripped}.auto_detect.txt"
        with open(context_path, "w", encoding="utf-8") as f:
            f.write(output_buf.getvalue())
        print(f"  Context saved: {context_path}")


def _batch_auto_detect():
    """Run auto-detect on all CIKs that have pre-XBRL filings but no template."""
    idx = _load_filings_index()

    # Find CIKs with filings up to the XBRL universality cutoff
    # (all filings, not just pre-XBRL -- we want full coverage through Q4 2022)
    pre_cutoff = idx[idx["report_date"] <= HTML_TEMPLATE_CUTOFF_DATE]
    ciks_needing = pre_cutoff.groupby(
        pre_cutoff["cik"].str.lstrip("0")
    ).size().reset_index(name="n_filings")

    # Exclude CIKs that already have a validated template
    existing = set()
    for p in HTML_TEMPLATE_DIR.glob("*.json"):
        if p.stem.isdigit():
            existing.add(p.stem)

    todo = [
        (row["cik"], row["n_filings"])
        for _, row in ciks_needing.iterrows()
        if row["cik"] not in existing
    ]
    todo.sort(key=lambda x: -x[1])  # Most filings first

    print(f"BATCH AUTO-DETECT: {len(todo)} CIKs to process "
          f"({len(existing)} already have templates)")
    print(f"  Sorted by filing count (most first)\n")

    for i, (cik, n) in enumerate(todo):
        print(f"\n{'#'*70}")
        print(f"# [{i+1}/{len(todo)}] CIK {cik} ({n} filings)")
        print(f"{'#'*70}")
        try:
            auto_detect_cik(cik, save_context=True)
        except Exception as e:
            print(f"  ERROR: {e}")
            continue

    print(f"\n\nBATCH COMPLETE: {len(todo)} CIKs processed")
    print(f"  Draft templates: data/raw/filing_templates/<CIK>.json")
    print(f"  Context files:   data/raw/filing_templates/<CIK>.auto_detect.txt")


# ---------------------------------------------------------------------------
# Add periods (non-destructive)
# ---------------------------------------------------------------------------

def _add_periods_to_template(cik: str) -> dict:
    """Add table_periods to an existing template without overwriting anything.

    Reads the template JSON, runs period detection on each filing's HTML,
    and adds table_periods to per-filing overrides where detected.
    Returns stats dict {total, added, skipped_existing, skipped_no_html,
    skipped_no_periods, skipped_single_table}.
    """
    cik_stripped = cik.lstrip("0")
    template_path = HTML_TEMPLATE_DIR / f"{cik_stripped}.json"
    if not template_path.exists():
        return {"error": f"No template for CIK {cik_stripped}"}

    with open(template_path) as f:
        template = json.load(f)

    if template.get("version") != "3.0":
        return {"error": f"Not v3.0 template for CIK {cik_stripped}"}

    cache_dir = BDC_HTML_CACHE_DIR / cik_stripped
    idx = _load_filings_index()
    cik_filings = idx[
        (idx["cik"].str.lstrip("0") == cik_stripped)
        & (idx["report_date"] <= HTML_TEMPLATE_CUTOFF_DATE)
    ].sort_values("filing_date")

    default_tables = template.get("default", {}).get("tables", [])
    filings_dict = template.setdefault("filings", {})

    stats = {
        "total": len(cik_filings),
        "added": 0,
        "skipped_existing": 0,
        "skipped_no_html": 0,
        "skipped_no_periods": 0,
        "skipped_single_table": 0,
    }

    for _, filing in cik_filings.iterrows():
        acc = filing["accession_number"]
        report_date = filing["report_date"]
        acc_nodashes = acc.replace("-", "")

        # Get effective tables for this filing
        override = filings_dict.get(acc, {})
        tables = override.get("tables", default_tables)

        if not tables or len(tables) < 2:
            stats["skipped_single_table"] += 1
            continue

        # Skip if table_periods already set
        if override.get("table_periods"):
            stats["skipped_existing"] += 1
            continue

        html_path = cache_dir / f"{acc_nodashes}.html"
        if not html_path.exists():
            stats["skipped_no_html"] += 1
            continue

        # Run period detection
        table_periods = _detect_periods_from_html(
            html_path, tables, report_date,
        )

        # Fallback: gap-based for 10-K
        if table_periods is None:
            form_type = filing.get("form_type", "")
            if "10-K" in form_type:
                # Build groups from tables list for gap detection
                # Simple approach: treat all tables as one group if contiguous,
                # or split into groups if there's a gap >= 10
                groups = _tables_to_groups(tables)
                if len(groups) == 2:
                    table_periods = _detect_10k_periods(groups, report_date)

        if not table_periods:
            stats["skipped_no_periods"] += 1
            continue

        # Add table_periods to filing override (create if needed)
        if acc not in filings_dict:
            filings_dict[acc] = {}
        filings_dict[acc]["table_periods"] = table_periods
        stats["added"] += 1

    # Save only if we added something
    if stats["added"] > 0:
        with open(template_path, "w") as f:
            json.dump(template, f, indent=2)

    return stats


def _tables_to_groups(tables: list[int]) -> list[list[int]]:
    """Split a flat list of table indices into groups based on gaps >= 10."""
    if not tables:
        return []
    sorted_t = sorted(tables)
    groups: list[list[int]] = [[sorted_t[0]]]
    for t in sorted_t[1:]:
        if t - groups[-1][-1] >= 10:
            groups.append([t])
        else:
            groups[-1].append(t)
    return groups


def add_periods_all():
    """Add table_periods to all existing templates."""
    templates = sorted(HTML_TEMPLATE_DIR.glob("*.json"))
    ciks = [p.stem for p in templates if p.stem.isdigit()]

    print(f"ADD-PERIODS: Processing {len(ciks)} templates\n")

    total_added = 0
    total_filings = 0
    ciks_modified = 0

    for i, cik in enumerate(ciks):
        stats = _add_periods_to_template(cik)
        if "error" in stats:
            print(f"  [{i+1}/{len(ciks)}] CIK {cik}: {stats['error']}")
            continue

        total_filings += stats["total"]
        total_added += stats["added"]
        if stats["added"] > 0:
            ciks_modified += 1

        # Only print CIKs where we added periods
        if stats["added"] > 0:
            print(f"  [{i+1}/{len(ciks)}] CIK {cik}: +{stats['added']} "
                  f"periods added (of {stats['total']} filings)")
        elif (i + 1) % 50 == 0:
            print(f"  [{i+1}/{len(ciks)}] ... (no changes)")

    print(f"\nADD-PERIODS COMPLETE:")
    print(f"  Templates processed: {len(ciks)}")
    print(f"  Templates modified:  {ciks_modified}")
    print(f"  Filing periods added: {total_added}")
    print(f"  Total filings checked: {total_filings}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Manage per-CIK HTML extraction templates (v3.0)",
    )
    parser.add_argument("--list", action="store_true",
                        help="List CIKs needing templates")
    parser.add_argument("--next", action="store_true",
                        help="Claim and prepare the next available CIK")
    parser.add_argument("--prepare", type=str, metavar="CIK",
                        help="Prepare data for a specific CIK")
    parser.add_argument("--inspect", type=str, metavar="CIK",
                        help="Inspect table grid layout for a CIK")
    parser.add_argument("--filing", type=str, metavar="ACC",
                        help="Filing accession (with --inspect)")
    parser.add_argument("--table", type=int, metavar="IDX",
                        help="Table index (with --inspect --filing)")
    parser.add_argument("--header-row", type=int, default=0,
                        help="Header row index (with --inspect, default 0)")
    parser.add_argument("--all-widths", action="store_true",
                        help="Inspect all distinct SOI widths (with --inspect)")
    parser.add_argument("--validate", type=str, metavar="CIK",
                        help="Validate a template with extraction + XBRL")
    parser.add_argument("--validate-only", type=str, metavar="CIK",
                        help="Run aggregate + carry validation only")
    parser.add_argument("--accept", type=str, metavar="CIK",
                        help="Accept a FAIL CIK with justification")
    parser.add_argument("--justification", type=str, metavar="TEXT",
                        help="Justification text (with --accept)")
    parser.add_argument("--auto-detect", type=str, metavar="CIK",
                        help="Auto-detect SOI tables and write draft template")
    parser.add_argument("--auto-detect-all", action="store_true",
                        help="Batch auto-detect for all CIKs needing templates")
    parser.add_argument("--add-periods", type=str, nargs="?", const="ALL",
                        metavar="CIK",
                        help="Add table_periods to templates (CIK or all)")
    parser.add_argument("--revalidate-all", action="store_true",
                        help="Re-validate all template CIKs, save summary CSV")
    parser.add_argument("--fix-next", action="store_true",
                        help="Claim next FAIL CIK for fixing")
    parser.add_argument("--fix-done", type=str, metavar="CIK",
                        help="Mark a CIK as fixed after validation passes")
    parser.add_argument("--progress", action="store_true",
                        help="Show overall progress")

    args = parser.parse_args()

    if args.auto_detect:
        auto_detect_cik(args.auto_detect)
    elif args.auto_detect_all:
        _batch_auto_detect()
    elif args.add_periods:
        if args.add_periods == "ALL":
            add_periods_all()
        else:
            stats = _add_periods_to_template(args.add_periods)
            if "error" in stats:
                print(stats["error"])
            else:
                print(f"CIK {args.add_periods.lstrip('0')}: "
                      f"+{stats['added']} periods added, "
                      f"{stats['skipped_existing']} already had periods, "
                      f"{stats['skipped_no_periods']} no periods detected, "
                      f"{stats['skipped_no_html']} no HTML, "
                      f"{stats['skipped_single_table']} single-table")
    elif args.list:
        list_ciks()
    elif args.next:
        claim_next_cik()
    elif args.prepare:
        prepare_cik(args.prepare)
    elif args.inspect:
        if args.all_widths:
            inspect_all_widths(args.inspect)
        elif args.filing and args.table is not None:
            inspect_table(
                args.inspect, args.filing, args.table,
                header_row=args.header_row,
            )
        elif args.filing:
            # List all tables in this filing from saved grids
            cik = args.inspect.lstrip("0")
            grids = _load_grids(cik, args.filing)
            if not grids:
                print(f"No grids for {args.filing}. Run --prepare {cik} first.")
            else:
                print(f"\nTables in {args.filing}:")
                for t in grids:
                    grid = t["grid"]
                    hdr = grid[0] if grid else []
                    hdr_text = [c for c in hdr if c.strip()][:6]
                    preview = ", ".join(hdr_text)
                    if len(preview) > 60:
                        preview = preview[:57] + "..."
                    preview = preview.encode("ascii", "replace").decode("ascii")
                    print(f"  Table {t['index']:>2}: w={t['width']:>2}, "
                          f"{t['rows']:>3} rows  [{preview}]")
        else:
            print("Usage: --inspect CIK --all-widths")
            print("       --inspect CIK --filing ACC")
            print("       --inspect CIK --filing ACC --table IDX [--header-row N]")
    elif args.validate:
        validate_template(args.validate)
    elif args.validate_only:
        from pipeline.validate_html_template import (
            validate_cik as _validate_cik,
            _print_cik_report,
        )
        result = _validate_cik(args.validate_only.lstrip("0"))
        _print_cik_report(result)
        _save_validation_result(result)
    elif args.accept:
        if not args.justification:
            print("Error: --accept requires --justification TEXT")
            sys.exit(1)
        accept_cik(args.accept, args.justification)
    elif args.revalidate_all:
        revalidate_all()
    elif args.fix_next:
        claim_fix_next()
    elif args.fix_done:
        mark_fix_done(args.fix_done)
    elif args.progress:
        show_progress()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
