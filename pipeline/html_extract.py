"""v3.0 HTML extraction engine for pre-XBRL BDC filings.

Reads per-CIK JSON templates that specify exact table indices and column
positions.  All intelligence lives in the template (created once by an LLM);
the engine is a simple table reader.

Usage::

    python -m pipeline.main --extract-html        # Extract all pre-XBRL filings
"""

import json
import logging
import re
import time
from pathlib import Path
from typing import Any, Optional

import pandas as pd

from pipeline.config import (
    BDC_FILINGS_INDEX_FILE,
    BDC_HTML_CACHE_DIR,
    HTML_EXTRACTION_FILE,
    HTML_TEMPLATE_DIR,
)

logger = logging.getLogger(__name__)

try:
    from bs4 import BeautifulSoup
except ImportError:
    BeautifulSoup = None  # type: ignore[assignment,misc]

TEMPLATE_VERSION = "3.0"
PROGRESS_SAVE_INTERVAL = 10

# ---------------------------------------------------------------------------
# A. Regexes & parsing utilities (carried from v2.0 engine)
# ---------------------------------------------------------------------------

# Footnote patterns
_FOOTNOTE_RE = re.compile(r"\s*(\(\d+\))+\s*$")
_TRAILING_FOOTNOTE_RE = re.compile(r"\s*\*+\s*$")

# Foreign currency parenthetical: "(CAD 76,091)", "(EUR 4,055)"
_FOREIGN_CURRENCY_PAREN_RE = re.compile(
    r"\s*\(\s*[A-Z]{3}\s+[\d.,\s]+\)"
)

# First contiguous digit group for multi-number cells
_FIRST_NUMERIC_RE = re.compile(r"^[-\s]*([\d.,]+)")

# Date formats
_DATE_FORMATS = [
    (re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{4})$"), r"\3-\1-\2"),   # M/D/YYYY
    (re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{2})$"), None),           # M/D/YY
    (re.compile(r"^(\d{1,2})-(\d{1,2})-(\d{4})$"), r"\3-\1-\2"),    # M-D-YYYY
]
_MONTH_NAMES = {
    "january": 1, "february": 2, "march": 3, "april": 4,
    "may": 5, "june": 6, "july": 7, "august": 8,
    "september": 9, "october": 10, "november": 11, "december": 12,
    "jan": 1, "feb": 2, "mar": 3, "apr": 4,
    "jun": 6, "jul": 7, "aug": 8, "sep": 9, "sept": 9,
    "oct": 10, "nov": 11, "dec": 12,
}
_MONTH_NAME_DATE_RE = re.compile(r"^([A-Za-z]+)\s+(\d{4})$")
_MONTH_DAY_YEAR_RE = re.compile(r"^([A-Za-z]+)\s+(\d{1,2})\s+(\d{4})$")

# Subtotal detection -- matches names that START with "Total/Subtotal/Net assets"
# OR names that END with "Total" (e.g., "First Lien Debt Total").
_SUBTOTAL_START_RE = re.compile(
    r"(?i)^(total\b|sub[\s-]?total\b|subtotal\b"
    r"|net\s+assets?\b|cash\s+equivalents?\b|liabilities\b"
    r"|members\W?\s*capital\b|partners\W?\s*capital\b"
    r"|stockholders\W?\s*equity\b|shareholders\W?\s*equity\b"
    r"|net\s+asset\s+value\b)"
)
_SUBTOTAL_END_RE = re.compile(r"(?i)\b(?:sub[\s-]?)?total\s*$")
# "Net <category>" section summaries (e.g., "Net Senior Secured Loans")
_NET_SECTION_RE = re.compile(
    r"(?i)^net\s+(?:senior|secured|first|second|structured|subordinated"
    r"|common|preferred|unsecured|debt|loans?|equity|notes?"
    r"|stock|warrants?|bank|investments?|mezzanine|collateralized"
    r"|bridge|junior|revolv)"
)


def _strip_footnotes(value: str) -> str:
    """Remove trailing footnote references."""
    value = _FOOTNOTE_RE.sub("", value)
    value = _TRAILING_FOOTNOTE_RE.sub("", value)
    return value.strip()


def _parse_dollar(value: Any) -> Optional[float]:
    """Parse a dollar value, handling parenthesized negatives."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip()
    if not s or s == "-" or s.lower() in ("null", "none"):
        return None
    s = _FOREIGN_CURRENCY_PAREN_RE.sub("", s).strip()
    if not s:
        return None
    negative = False
    if s.startswith("(") and s.endswith(")"):
        s = s[1:-1]
        negative = True
    s = s.replace(",", "").replace("$", "").strip()
    s = _strip_footnotes(s)
    try:
        val = float(s)
        return -val if negative else val
    except ValueError:
        m = _FIRST_NUMERIC_RE.match(s)
        if m:
            first_num = m.group(1).replace(",", "")
            try:
                val = float(first_num)
                return -val if negative else val
            except ValueError:
                pass
        return None


def _parse_rate(value: Any) -> Optional[float]:
    """Parse a rate value, extracting the first number."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        v = float(value)
        if 0 < v < 0.5:
            return v * 100
        return v
    s = str(value).strip()
    has_pct = "%" in s
    s = s.replace("%", "").strip()
    if not s or s == "-" or s.lower() == "null":
        return None
    try:
        v = float(s)
        if not has_pct and 0 < v < 0.5:
            return v * 100
        return v
    except ValueError:
        m = re.search(r"[\d.]+", s)
        if m:
            try:
                v = float(m.group())
                if not has_pct and 0 < v < 0.5:
                    return v * 100
                return v
            except ValueError:
                pass
        return None


def _convert_date(date_str: str) -> Optional[str]:
    """Convert a date string to YYYY-MM-DD format."""
    date_str = _strip_footnotes(date_str).strip()
    date_str = date_str.replace(",", " ")
    date_str = re.sub(r"\s+", " ", date_str).strip()
    if not date_str or date_str == "-":
        return None

    if re.match(r"^\d{4}-\d{2}-\d{2}$", date_str):
        return date_str

    for pat, repl in _DATE_FORMATS:
        m = pat.match(date_str)
        if m:
            if repl is not None:
                raw = pat.sub(repl, date_str)
                parts = raw.split("-")
                if len(parts) == 3:
                    return f"{parts[0]}-{parts[1].zfill(2)}-{parts[2].zfill(2)}"
                return raw
            else:
                month, day, year2 = m.groups()
                year = int(year2)
                year = year + 2000 if year < 50 else year + 1900
                return f"{year}-{int(month):02d}-{int(day):02d}"

    # MM/YYYY partial dates
    m = re.match(r"^(\d{1,2})/(\d{4})$", date_str)
    if m:
        month, year = m.groups()
        return f"{year}-{int(month):02d}-01"

    # Month name dates
    m = _MONTH_NAME_DATE_RE.match(date_str)
    if m:
        month_name, year = m.groups()
        month_num = _MONTH_NAMES.get(month_name.lower())
        if month_num is not None:
            return f"{year}-{month_num:02d}-01"

    m = _MONTH_DAY_YEAR_RE.match(date_str)
    if m:
        month_name, day, year = m.groups()
        month_num = _MONTH_NAMES.get(month_name.lower())
        if month_num is not None:
            return f"{year}-{month_num:02d}-{int(day):02d}"

    return None


# ---------------------------------------------------------------------------
# B. HTML table parsing
# ---------------------------------------------------------------------------

def _extract_tables(html: str) -> list[list[list[str]]]:
    """Parse all <table> elements from HTML.

    Returns list of tables, each table = list of rows, each row = list of
    cell strings.  Handles colspan, ZWSP, whitespace collapse.
    """
    if BeautifulSoup is None:
        raise ImportError(
            "beautifulsoup4 required. Install: pip install beautifulsoup4 lxml"
        )

    soup = BeautifulSoup(html, "lxml")
    tables: list[list[list[str]]] = []

    for table_elem in soup.find_all("table"):
        rows: list[list[str]] = []
        for tr in table_elem.find_all("tr"):
            cells: list[str] = []
            for td in tr.find_all(["td", "th"]):
                text = td.get_text(separator=" ", strip=True)
                text = re.sub(r"\s+", " ", text).strip()
                text = text.replace("\u200b", "")
                colspan = 1
                try:
                    colspan = int(td.get("colspan", 1))
                except (ValueError, TypeError):
                    pass
                cells.append(text)
                for _ in range(colspan - 1):
                    cells.append("")
            if cells:
                rows.append(cells)
        if rows:
            tables.append(rows)

    return tables


# ---------------------------------------------------------------------------
# C. Template I/O
# ---------------------------------------------------------------------------

def load_template(cik: str) -> Optional[dict]:
    """Load a v3.0 template for a CIK.

    Returns None if not found, wrong version, or invalid JSON.
    """
    cik_stripped = str(cik).lstrip("0") or "0"
    path = HTML_TEMPLATE_DIR / f"{cik_stripped}.json"
    if not path.exists():
        return None
    try:
        with open(path) as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return None
    if data.get("version") != TEMPLATE_VERSION:
        return None
    return data


# ---------------------------------------------------------------------------
# D. Cell reading + rate parsing
# ---------------------------------------------------------------------------

def _get_cell(row: list[str], col: int) -> str:
    """Read cell at grid position.

    Handles:
    - $ split (SEC HTML splits "$" and number into adjacent cells)
    - Empty-cell lookahead for colspan offset
    - Split reference+spread cells ("SF +" in one, "5.50 %" in next)
    - Split parenthetical negatives ("(12,987" + ")")
    - Split PIK notation ("(PIK 1.00" + "%)")
    - ZWSP stripping
    """
    if col < 0 or col >= len(row):
        return ""
    val = row[col].strip().strip("\u200b").strip()

    # "$" split
    if val == "$" and col + 1 < len(row):
        val = row[col + 1].strip().strip("\u200b").strip()
    # Colspan offset: empty cell, value at col+1
    elif not val and col + 1 < len(row):
        val = row[col + 1].strip().strip("\u200b").strip()

    # Split reference+spread cells: "SF +" in one cell, "5.50 %" in next
    if val and re.match(
        r"^(?:[A-Za-z][A-Za-z0-9 ]*?|\d+M\s+USD\s+[A-Z]+)\s*\+\s*$",
        val,
    ):
        for nidx in range(col + 1, min(col + 6, len(row))):
            nval = row[nidx].strip().strip("\u200b").strip()
            if nval and re.search(r"\d", nval):
                val = val + " " + nval
                break

    # Split parenthetical negative: "(12,987" + ")"
    if val and re.match(r"^\([\d,.]+$", val):
        for nidx in range(col + 1, min(col + 3, len(row))):
            nval = row[nidx].strip().strip("\u200b").strip()
            if nval == ")":
                val = val + ")"
                break
            elif nval:
                break

    # Split PIK notation: "(PIK 1.00" + "%)"
    if val and re.match(r".*\(PIK\s+[\d.]+$", val, re.IGNORECASE):
        for nidx in range(col + 1, min(col + 3, len(row))):
            nval = row[nidx].strip().strip("\u200b").strip()
            if nval and re.match(r"^%?\s*\)?$", nval):
                val = val + " " + nval
                break
            elif nval:
                break

    # Strip leading "$" (non-split dollar sign)
    if val and val.startswith("$") and len(val) > 1:
        val = val[1:].strip()

    return val


def _resolve_headers(
    header_row: list[str],
    active_columns: dict,
) -> dict[str, int]:
    """Match column header text to field names.

    For each field in *active_columns* that has a ``"header"`` key,
    scan *header_row* cells for a case-insensitive substring match.
    The ``"header"`` value supports ``"|"`` as OR (e.g. ``"shares|units"``).

    Returns dict mapping field_name -> resolved column index.
    Only fields with a positive match are included.
    """
    resolved: dict[str, int] = {}
    for field, spec in active_columns.items():
        if not isinstance(spec, dict):
            continue
        header_pattern = spec.get("header")
        if not header_pattern:
            continue
        patterns = [p.strip().lower() for p in header_pattern.split("|")
                    if p.strip()]
        if not patterns:
            continue
        for col_idx, cell in enumerate(header_row):
            cell_lower = cell.strip().lower()
            if not cell_lower:
                continue
            if any(p in cell_lower for p in patterns):
                resolved[field] = col_idx
                break
    return resolved


# ---------------------------------------------------------------------------
# E. Core extraction
# ---------------------------------------------------------------------------

def extract_filing(
    html: str,
    filing_meta: dict,
    template: dict,
) -> tuple[list[dict], dict]:
    """Extract holdings from one HTML filing using a v3.0 template.

    Args:
        html: Raw HTML string.
        filing_meta: Dict with cik, accession_number, form_type, etc.
        template: Loaded v3.0 template dict.

    Returns:
        (holdings_rows, stats) where holdings_rows is in bdc_holdings schema.
    """
    stats: dict[str, Any] = {
        "tables_found": 0,
        "rows_extracted": 0,
        "elapsed_seconds": 0,
    }
    t0 = time.time()

    # Parse all tables from HTML
    all_tables = _extract_tables(html)
    stats["tables_found"] = len(all_tables)

    if not all_tables:
        stats["elapsed_seconds"] = time.time() - t0
        return [], stats

    # Resolve filing-specific overrides
    accession = filing_meta.get("accession_number", "")
    filing_spec = template.get("filings", {}).get(accession, {})

    # Table indices: filing override > default
    table_indices = filing_spec.get("tables", template.get("default", {}).get("tables", []))
    header_row = filing_spec.get("header_row", template.get("default", {}).get("header_row", 0))

    # Merge columns: base + filing-specific overrides
    columns = dict(template.get("columns", {}))
    columns.update(filing_spec.get("columns", {}))

    # Width-based column overrides (optional)
    columns_by_width: dict[str, dict] = {}
    base_cbw = template.get("columns_by_width", {})
    filing_cbw = filing_spec.get("columns_by_width", {})
    if base_cbw or filing_cbw:
        columns_by_width = {**base_cbw, **filing_cbw}

    # Table-to-period mapping (optional)
    table_periods: dict[int, str] = {}
    tp_spec = filing_spec.get("table_periods", template.get("default", {}).get("table_periods", {}))
    for period_date, tidx_list in tp_spec.items():
        for t in tidx_list:
            table_periods[t] = period_date

    # Dollar unit: filing override > template default
    dollar_unit = filing_spec.get("dollar_unit", template.get("dollar_unit", 1))

    # Top-level continuation column shift (filing override > template default)
    top_ccs = filing_spec.get(
        "continuation_column_shift",
        template.get("continuation_column_shift"),
    )

    report_date = filing_meta.get("report_date", "")
    cik = filing_meta.get("cik", "")
    entity_name = filing_meta.get("entity_name", "")

    # Extract from each specified table
    all_rows: list[dict] = []
    source_row_idx = 0
    last_header_resolved: dict[str, int] = {}  # carry across continuation tables

    for tidx in table_indices:
        if tidx < 0 or tidx >= len(all_tables):
            continue
        table = all_tables[tidx]

        # Select column mapping for this table based on width
        active_columns = columns
        active_ccs = top_ccs  # default to template/filing-level shift
        if columns_by_width and table:
            tw = len(table[header_row]) if header_row < len(table) else 0
            wk = str(tw)
            if wk in columns_by_width:
                width_override = columns_by_width[wk]
                active_columns = dict(columns)
                # Extract continuation_column_shift before merging (it's not
                # a column spec)
                if "continuation_column_shift" in width_override:
                    active_ccs = width_override["continuation_column_shift"]
                active_columns.update(
                    {k: v for k, v in width_override.items()
                     if k != "continuation_column_shift"}
                )

        # Semantic header resolution: match "header" patterns to actual cells
        if header_row < len(table):
            new_resolved = _resolve_headers(table[header_row], active_columns)
            if new_resolved:
                last_header_resolved = new_resolved

        # Build effective columns: apply header resolution overrides
        effective_columns: dict = {}
        for field, spec in active_columns.items():
            col_spec = dict(spec) if isinstance(spec, dict) else {"col": spec}
            has_header = isinstance(spec, dict) and spec.get("header")
            if has_header:
                if field in last_header_resolved:
                    col_spec = dict(col_spec)
                    col_spec["col"] = last_header_resolved[field]
                    effective_columns[field] = col_spec
                # else: field has header but no match -> skip (don't extract)
            else:
                effective_columns[field] = col_spec

        # Period for this table: table_periods override > report_date
        table_period = table_periods.get(tidx, report_date)

        for ri, row in enumerate(table):
            if ri <= header_row:
                continue  # skip header rows

            # Read each mapped field
            record: dict[str, Any] = {
                "cik": cik,
                "entity_name": entity_name,
                "accession_number": accession,
                "form_type": filing_meta.get("form_type", ""),
                "filing_date": filing_meta.get("filing_date", ""),
                "report_date": report_date,
                "period": table_period,
                "investment_identifier": "",
                "fair_value": "",
                "cost": "",
                "principal_amount": "",
                "interest_rate": "",
                "basis_spread": "",
                "reference_rate_type": "",
                "maturity_date": "",
                "shares_held": "",
                "pct_of_net_assets": "",
                "unrealized_gain_loss": "",
                "pik_rate": "",
                "industry": "",
                "investment_type": "",
                "affiliation": "",
                "dimensions_raw": "",
                "dollar_unit": dollar_unit,
                "is_subtotal": False,
                "source_row_idx": source_row_idx,
            }
            source_row_idx += 1

            # -- Determine continuation column shift for this row --
            apply_shift = 0
            if active_ccs:
                shift_val = active_ccs["shift"]
                det_col = active_ccs["detect_col"]
                # Read identifier first at its normal position
                id_spec = effective_columns.get("investment_identifier")
                if id_spec is not None:
                    id_col = id_spec["col"] if isinstance(id_spec, dict) else id_spec
                    id_val = _get_cell(row, id_col) if id_col is not None else ""
                else:
                    id_val = ""
                # Check detect column: raw cell text (no _get_cell lookahead)
                det_val = row[det_col].strip() if det_col < len(row) else ""
                if id_val and (not det_val or not re.search(r"[a-zA-Z]", det_val)):
                    apply_shift = shift_val

            # -- Capture raw cell text for all mapped fields --
            _ALL_FIELDS = (
                "investment_identifier", "investment_type", "industry",
                "fair_value", "cost", "principal_amount",
                "interest_rate", "reference_rate_type", "basis_spread",
                "pik_rate", "maturity_date", "shares_held",
                "pct_of_net_assets",
            )
            for field in _ALL_FIELDS:
                col_spec = effective_columns.get(field)
                if col_spec is not None:
                    col_idx = col_spec["col"] if isinstance(col_spec, dict) else col_spec
                    if field != "investment_identifier" and apply_shift:
                        col_idx += apply_shift
                    cell = _get_cell(row, col_idx)
                    if cell:
                        record[field] = cell

            # Strip trailing footnote markers from identifier (e.g. "(12)(13)")
            raw_id = record.get("investment_identifier", "")
            if raw_id:
                record["investment_identifier"] = _strip_footnotes(raw_id)

            # -- Subtotal detection --
            name = record.get("investment_identifier", "")
            if name and (
                _SUBTOTAL_START_RE.match(name)
                or _SUBTOTAL_END_RE.search(name)
                or _NET_SECTION_RE.match(name)
            ):
                record["is_subtotal"] = True

            # Skip empty rows (no name and no FV)
            if not name and not record.get("fair_value"):
                source_row_idx -= 1  # don't count blank rows
                continue

            all_rows.append(record)

    # Name propagation for continuation rows (empty name = continuation)
    # Also detect per-company subtotals: originally empty name + has FV but
    # lacks detail fields (rate, maturity, type).  These are company-level
    # sums, not individual positions.
    last_name = ""
    last_industry = ""
    for row in all_rows:
        if row.get("investment_identifier"):
            last_name = row["investment_identifier"]
            if row.get("industry"):
                last_industry = row["industry"]
        elif last_name:
            has_fv = bool(row.get("fair_value"))
            # Don't count subtotal-like text in detail fields as "detail".
            # Industry subtotal rows (e.g. "Total Aerospace") may land in
            # rate/maturity/industry columns.
            rate_val = row.get("interest_rate", "")
            mat_val = row.get("maturity_date", "")
            type_val = row.get("investment_type", "")
            ind_val = row.get("industry", "")
            for fld in ("interest_rate", "maturity_date",
                         "investment_type", "industry"):
                val = row.get(fld, "")
                if val and (
                    _SUBTOTAL_START_RE.match(val)
                    or _SUBTOTAL_END_RE.search(val)
                    or _NET_SECTION_RE.match(val)
                ):
                    row[fld] = ""  # clear garbage subtotal text
            has_detail = bool(
                row.get("interest_rate")
                or row.get("maturity_date")
                or row.get("investment_type")
            )
            if has_fv and not has_detail:
                # Per-company subtotal row — mark as subtotal, don't propagate
                row["is_subtotal"] = True
            else:
                row["investment_identifier"] = last_name
                if not row.get("industry") and last_industry:
                    row["industry"] = last_industry

    stats["rows_extracted"] = len(all_rows)
    stats["elapsed_seconds"] = time.time() - t0
    return all_rows, stats


# ---------------------------------------------------------------------------
# F. Batch extraction
# ---------------------------------------------------------------------------

def extract_all_html(
    client: Any = None,
    filings_index: Optional[pd.DataFrame] = None,
    cik_filter: Optional[list[str]] = None,
) -> pd.DataFrame:
    """Extract all CIKs with v3.0 templates.

    Args:
        client: EdgarClient for downloading HTML (optional if cached).
        filings_index: Filing index DataFrame. Loads from disk if None.
        cik_filter: Optional list of CIKs to limit processing.

    Returns:
        DataFrame in bdc_holdings schema.
    """
    if filings_index is None:
        if not BDC_FILINGS_INDEX_FILE.exists():
            logger.error("Filings index not found: %s", BDC_FILINGS_INDEX_FILE)
            return pd.DataFrame()
        filings_index = pd.read_csv(BDC_FILINGS_INDEX_FILE, dtype=str)

    # Filter to pre-XBRL filings
    if "xbrl_download_status" in filings_index.columns:
        to_process = filings_index[
            filings_index["xbrl_download_status"] == "not_found"
        ].copy()
    else:
        to_process = filings_index.copy()

    # Must have primary_document
    if "primary_document" in to_process.columns:
        to_process = to_process[to_process["primary_document"].notna()].copy()
        to_process = to_process[to_process["primary_document"] != ""].copy()

    # CIK filter
    if cik_filter:
        filter_set = {str(c).lstrip("0") for c in cik_filter}
        to_process = to_process[
            to_process["cik"].astype(str).str.lstrip("0").isin(filter_set)
        ]

    logger.info("HTML extraction: %d filings to process", len(to_process))

    if to_process.empty:
        if HTML_EXTRACTION_FILE.exists():
            return pd.read_csv(HTML_EXTRACTION_FILE, dtype=str)
        return pd.DataFrame()

    # Load progress for resumability
    progress_file = HTML_EXTRACTION_FILE.parent / "html_extract_progress.csv"
    parsed_accessions: set[str] = set()
    if progress_file.exists():
        prog = pd.read_csv(progress_file, dtype=str)
        parsed_accessions = set(
            prog.loc[prog["status"].isin(["parsed", "error"]), "accession_number"]
        )
        logger.info("  Resuming: %d already processed", len(parsed_accessions))

    to_process = to_process[~to_process["accession_number"].isin(parsed_accessions)]
    logger.info("  %d filings remaining", len(to_process))

    if to_process.empty:
        if HTML_EXTRACTION_FILE.exists():
            return pd.read_csv(HTML_EXTRACTION_FILE, dtype=str)
        return pd.DataFrame()

    all_holdings: list[dict] = []
    progress_records: list[dict] = []
    t0 = time.time()

    # Cache loaded templates
    template_cache: dict[str, Optional[dict]] = {}

    for i, (_, row) in enumerate(to_process.iterrows(), 1):
        acc = str(row["accession_number"])
        cik = str(row["cik"]).lstrip("0") or "0"

        # Load template (cached)
        if cik not in template_cache:
            template_cache[cik] = load_template(cik)
        tmpl = template_cache[cik]

        if tmpl is None:
            progress_records.append({
                "accession_number": acc, "status": "no_template", "count": "0",
            })
            continue

        # Load HTML
        acc_nodashes = acc.replace("-", "")
        html_path = BDC_HTML_CACHE_DIR / cik / f"{acc_nodashes}.html"

        if not html_path.exists() or html_path.stat().st_size <= 1024:
            if client is not None:
                from pipeline.bdc_filings import download_html_filing
                primary_doc = str(row.get("primary_document", ""))
                result = download_html_filing(client, cik, acc, primary_doc)
                if result is None:
                    progress_records.append({
                        "accession_number": acc, "status": "download_failed",
                        "count": "0",
                    })
                    continue
                html_path = result
            else:
                progress_records.append({
                    "accession_number": acc, "status": "no_html", "count": "0",
                })
                continue

        try:
            html_content = html_path.read_text(encoding="utf-8", errors="replace")
        except Exception as exc:
            logger.debug("Failed to read %s: %s", html_path, exc)
            progress_records.append({
                "accession_number": acc, "status": "read_error", "count": "0",
            })
            continue

        filing_meta = {
            "cik": cik,
            "entity_name": str(row.get("entity_name", "")),
            "accession_number": acc,
            "form_type": str(row.get("form_type", "")),
            "filing_date": str(row.get("filing_date", "")),
            "report_date": str(row.get("report_date", "")),
        }

        try:
            holdings, stats = extract_filing(html_content, filing_meta, tmpl)
            all_holdings.extend(holdings)
            progress_records.append({
                "accession_number": acc, "status": "parsed",
                "count": str(len(holdings)),
            })
            if i <= 5 or i % 100 == 0:
                logger.info(
                    "  [%d/%d] CIK %s: %d rows (%.2fs)",
                    i, len(to_process), cik, len(holdings),
                    stats["elapsed_seconds"],
                )
        except Exception as exc:
            logger.error(
                "  [%d/%d] CIK %s %s: error: %s",
                i, len(to_process), cik, acc, exc,
            )
            progress_records.append({
                "accession_number": acc, "status": "error", "count": "0",
            })

        # Periodic progress save
        if i % PROGRESS_SAVE_INTERVAL == 0 or i == len(to_process):
            _save_progress(progress_records, parsed_accessions, progress_file)
            if all_holdings:
                _save_holdings(all_holdings)

    # Final save
    _save_progress(progress_records, parsed_accessions, progress_file)
    if all_holdings:
        _save_holdings(all_holdings)

    if HTML_EXTRACTION_FILE.exists():
        return pd.read_csv(HTML_EXTRACTION_FILE, dtype=str)
    return pd.DataFrame(all_holdings) if all_holdings else pd.DataFrame()


def _save_progress(
    records: list[dict],
    existing: set[str],
    progress_file: Path,
) -> None:
    """Save extraction progress, merging with existing."""
    if not records:
        return
    new_df = pd.DataFrame(records)
    if progress_file.exists():
        old_df = pd.read_csv(progress_file, dtype=str)
        combined = pd.concat([old_df, new_df], ignore_index=True)
        combined.drop_duplicates(
            subset=["accession_number"], keep="last", inplace=True
        )
    else:
        combined = new_df
    combined.to_csv(progress_file, index=False)


def _save_holdings(holdings: list[dict]) -> None:
    """Save extracted holdings, merging with existing."""
    new_df = pd.DataFrame(holdings)
    if HTML_EXTRACTION_FILE.exists():
        existing = pd.read_csv(HTML_EXTRACTION_FILE, dtype=str)
        combined = pd.concat([existing, new_df], ignore_index=True)
        combined.drop_duplicates(
            subset=["accession_number", "investment_identifier", "period"],
            inplace=True,
        )
    else:
        combined = new_df
    combined.to_csv(HTML_EXTRACTION_FILE, index=False)
