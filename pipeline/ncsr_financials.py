"""Extract fund-level Financial Highlights from N-CSR / N-CSRS filings.

Interval and tender offer funds (~160 CIKs) file annual N-CSR and
semi-annual N-CSRS reports with a mandated Financial Highlights table
(SEC Reg S-X).  This module discovers those filings, downloads the HTML,
and parses per-share NII, distribution decomposition, NAV, expense
ratios, and total return.

Public API
----------
build_ncsr_filings_index(client, universe_ciks)  -> pd.DataFrame
download_ncsr_filings(client, filings_index)      -> pd.DataFrame
extract_ncsr_financials(filings_index=None)        -> pd.DataFrame
"""

import html
import logging
import re
import time
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
from bs4 import BeautifulSoup, Tag

from pipeline.config import (
    COMBINED_UNIVERSE_FILE,
    NCSR_FINANCIALS_FILE,
    NCSR_FILINGS_INDEX_FILE,
    NCSR_HTML_CACHE_DIR,
)
from pipeline.edgar_client import EdgarClient

logger = logging.getLogger(__name__)

# N-CSR form types to discover
_NCSR_FORM_TYPES = {"N-CSR", "N-CSRS", "N-CSR/A", "N-CSRS/A"}

# ---------------------------------------------------------------------------
# A. Filing discovery
# ---------------------------------------------------------------------------

def build_ncsr_filings_index(
    client: EdgarClient,
    universe_ciks: list[str],
) -> pd.DataFrame:
    """Fetch N-CSR / N-CSRS filing metadata for interval/tender fund CIKs.

    Returns a DataFrame with one row per filing.  Cached to disk for 24 h.
    """
    if NCSR_FILINGS_INDEX_FILE.exists():
        age = datetime.now() - datetime.fromtimestamp(
            NCSR_FILINGS_INDEX_FILE.stat().st_mtime,
        )
        if age < timedelta(hours=24):
            cached = pd.read_csv(NCSR_FILINGS_INDEX_FILE, dtype=str)
            cached_ciks = set(cached["cik"].unique()) if "cik" in cached.columns else set()
            requested_ciks = set(str(c) for c in universe_ciks)
            new_ciks = requested_ciks - cached_ciks
            if not new_ciks:
                logger.info(
                    "Loading cached N-CSR filings index (%d min old, %d CIKs)",
                    int(age.total_seconds() / 60), len(cached_ciks),
                )
                return cached
            logger.info(
                "Cached index has %d CIKs but %d new CIKs requested, rebuilding",
                len(cached_ciks), len(new_ciks),
            )

    logger.info(
        "Building N-CSR filings index for %d CIKs ...", len(universe_ciks),
    )

    records: list[dict[str, str]] = []
    for i, cik in enumerate(universe_ciks, 1):
        if i % 50 == 0 or i == len(universe_ciks):
            logger.info("  N-CSR submissions progress: %d / %d", i, len(universe_ciks))

        try:
            data = client.get_company_submissions(cik)
        except Exception as exc:
            logger.warning("  CIK %s submissions failed: %s", cik, exc)
            continue

        entity_name = data.get("name", "")
        filings_obj = data.get("filings", {})

        recent = filings_obj.get("recent", {})
        _collect_ncsr_filings(records, cik, entity_name, recent)

        for page_ref in filings_obj.get("files", []):
            page_name = page_ref.get("name", "")
            if not page_name:
                continue
            page_url = f"https://data.sec.gov/submissions/{page_name}"
            try:
                page_data = client.get_json(page_url)
            except Exception as exc:
                logger.debug("  CIK %s page %s failed: %s", cik, page_name, exc)
                continue
            _collect_ncsr_filings(records, cik, entity_name, page_data)

    df = pd.DataFrame(records)
    if df.empty:
        logger.warning("No N-CSR filings found")
        df = pd.DataFrame(columns=[
            "cik", "entity_name", "accession_number", "form_type",
            "filing_date", "report_date", "primary_document",
        ])
    else:
        df.drop_duplicates(subset=["accession_number"], inplace=True)
        df.sort_values(["cik", "filing_date"], inplace=True)

    df.to_csv(NCSR_FILINGS_INDEX_FILE, index=False)
    logger.info(
        "N-CSR filings index: %d filings across %d CIKs",
        len(df), df["cik"].nunique() if not df.empty else 0,
    )
    return df


def _collect_ncsr_filings(
    records: list[dict[str, str]],
    cik: str,
    entity_name: str,
    recent: dict[str, list],
) -> None:
    """Extract N-CSR filings from a submissions-API recent/page dict."""
    forms = recent.get("form", [])
    dates = recent.get("filingDate", [])
    accessions = recent.get("accessionNumber", [])
    primary_docs = recent.get("primaryDocument", [])
    report_dates = recent.get("reportDate", [])

    for j in range(len(forms)):
        form = forms[j] if j < len(forms) else ""
        if form not in _NCSR_FORM_TYPES:
            continue

        records.append({
            "cik": cik,
            "entity_name": entity_name,
            "accession_number": accessions[j] if j < len(accessions) else "",
            "form_type": form,
            "filing_date": dates[j] if j < len(dates) else "",
            "report_date": report_dates[j] if j < len(report_dates) else "",
            "primary_document": primary_docs[j] if j < len(primary_docs) else "",
        })


# ---------------------------------------------------------------------------
# B. Filing download
# ---------------------------------------------------------------------------

def download_ncsr_filings(
    client: EdgarClient,
    filings_index: pd.DataFrame,
) -> pd.DataFrame:
    """Download N-CSR HTML for each filing.  Caches to disk.

    Adds ``html_local_path`` and ``download_status`` columns.
    """
    if filings_index.empty:
        filings_index["html_local_path"] = pd.Series(dtype=str)
        filings_index["download_status"] = pd.Series(dtype=str)
        return filings_index

    statuses: list[str] = []
    local_paths: list[str] = []
    total = len(filings_index)
    t0 = time.time()

    for idx, row in filings_index.iterrows():
        i = len(statuses) + 1
        if i % 100 == 0 or i == total:
            elapsed = time.time() - t0
            rate = i / elapsed if elapsed > 0 else 0
            logger.info(
                "  N-CSR download: %d / %d  (%.1f/s)",
                i, total, rate,
            )

        prev_status = row.get("download_status")
        if pd.notna(prev_status) and prev_status in ("cached", "downloaded"):
            statuses.append(str(prev_status))
            local_paths.append(str(row.get("html_local_path", "") or ""))
            continue

        cik = str(row["cik"]).lstrip("0") or "0"
        acc = str(row["accession_number"]).replace("-", "")
        primary_doc = str(row.get("primary_document", ""))

        cache_dir = NCSR_HTML_CACHE_DIR / cik
        cache_file = cache_dir / f"{acc}.html"

        if cache_file.exists() and cache_file.stat().st_size > 1024:
            statuses.append("cached")
            local_paths.append(str(cache_file))
            continue

        if not primary_doc:
            statuses.append("no_primary_doc")
            local_paths.append("")
            continue

        url = (
            f"https://www.sec.gov/Archives/edgar/data/{cik}/"
            f"{acc}/{primary_doc}"
        )
        try:
            cache_dir.mkdir(parents=True, exist_ok=True)
            client.download_file(url, cache_file)
            statuses.append("downloaded")
            local_paths.append(str(cache_file))
        except Exception as exc:
            logger.warning("  Download failed: %s -- %s", url, exc)
            statuses.append("failed")
            local_paths.append("")

    filings_index = filings_index.copy()
    filings_index["download_status"] = statuses
    filings_index["html_local_path"] = local_paths

    filings_index.to_csv(NCSR_FILINGS_INDEX_FILE, index=False)
    ok_count = sum(1 for s in statuses if s in ("cached", "downloaded"))
    logger.info("N-CSR downloads: %d / %d successful", ok_count, total)
    return filings_index


# ---------------------------------------------------------------------------
# C. Financial Highlights extraction
# ---------------------------------------------------------------------------

# Row label patterns -> output field name
# ORDER MATTERS: specific patterns must precede generic ones.
_ROW_LABEL_PATTERNS: list[tuple[re.Pattern, str]] = [
    # NAV
    (re.compile(r"net\s+asset\s+value.*?begin", re.I), "nav_begin_per_share"),
    (re.compile(r"net\s+asset\s+value.*?end", re.I), "nav_end_per_share"),
    # Distributions -- MUST come before NII pattern to avoid false match
    # "Distributions from ..." / "Dividends from ..." / "From ..." (under header)
    # Requires either "distribution/dividend" prefix OR "from" prefix (not bare "net investment income")
    (re.compile(r"(?:(?:distribution|dividend)s?\s+(?:from\s+)?|from\s+)net\s+investment\s+income", re.I), "distribution_from_nii"),
    (re.compile(r"(?:(?:distribution|dividend)s?\s+(?:from\s+)?|from\s+)(?:net\s+)?(?:realized\s+)?(?:capital\s+)?gain", re.I), "distribution_from_gains"),
    (re.compile(r"return\s+of\s+capital", re.I), "distribution_return_of_capital"),
    (re.compile(r"total\s+(?:distribution|dividend)", re.I), "distribution_per_share"),
    # Ratios -- income yield MUST come before generic NII
    (re.compile(r"(?:ratio\s+of\s+)?net\s+investment\s+(?:income|loss).*?(?:average|ratio|net\s+asset)", re.I), "income_yield_pct"),
    # NII per share (generic, after distribution and ratio patterns)
    (re.compile(r"net\s+investment\s+(?:income|loss)", re.I), "nii_per_share"),
    # Gain/loss
    (re.compile(r"(?:net\s+)?(?:realized\s*(?:and|[/])\s*unrealized|change\s+in\s+unrealized)", re.I), "gain_loss_per_share"),
    # Total return
    (re.compile(r"total\s+return", re.I), "total_return_pct"),
    # Ratios
    (re.compile(r"(?:total\s+)?expense.*?(?:average|net\s+asset)", re.I), "expense_ratio_pct"),
    (re.compile(r"portfolio\s+turnover", re.I), "portfolio_turnover"),
    (re.compile(r"net\s+assets.*?end", re.I), "net_assets_end"),
]

# Period heading patterns
_PERIOD_YEAR_RE = re.compile(
    r"(?:year|twelve\s+months?|annual\s+period)\s+ended\s+"
    r"(\w+\.?\s+\d{1,2},?\s+\d{4})",
    re.I,
)
_PERIOD_SEMI_RE = re.compile(
    r"(?:six\s+months?|semi[\s-]?annual\s+period|period)\s+ended\s+"
    r"(\w+\.?\s+\d{1,2},?\s+\d{4})",
    re.I,
)

# Date parsing for period headings
_MONTH_MAP = {
    "january": 1, "jan": 1, "february": 2, "feb": 2,
    "march": 3, "mar": 3, "april": 4, "apr": 4,
    "may": 5, "june": 6, "jun": 6,
    "july": 7, "jul": 7, "august": 8, "aug": 8,
    "september": 9, "sep": 9, "sept": 9,
    "october": 10, "oct": 10, "november": 11, "nov": 11,
    "december": 12, "dec": 12,
}

# Financial Highlights heading pattern
_FH_HEADING_RE = re.compile(
    r"(?:Consolidated\s+)?Financial\s+Highlights",
    re.I,
)

# Footnote pattern to strip from values
_FOOTNOTE_RE = re.compile(r"\([a-z0-9,]+\)\s*$")

# Negative value in parentheses
_PAREN_NEG_RE = re.compile(r"^\((.+)\)$")


def extract_ncsr_financials(
    filings_index: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Parse Financial Highlights from cached N-CSR HTML files.

    Parameters
    ----------
    filings_index : DataFrame, optional
        N-CSR filings index with ``html_local_path``.
        Loaded from disk if None.

    Returns
    -------
    DataFrame saved to ``ncsr_financials.csv``.
    """
    t0 = time.time()

    if filings_index is None:
        if NCSR_FILINGS_INDEX_FILE.exists():
            filings_index = pd.read_csv(NCSR_FILINGS_INDEX_FILE, dtype=str)
        else:
            logger.warning("No N-CSR filings index found")
            empty = pd.DataFrame(columns=_OUTPUT_COLS)
            empty.to_csv(NCSR_FINANCIALS_FILE, index=False)
            return empty

    if filings_index.empty:
        empty = pd.DataFrame(columns=_OUTPUT_COLS)
        empty.to_csv(NCSR_FINANCIALS_FILE, index=False)
        return empty

    all_rows: list[dict] = []
    ok_count = 0
    fail_count = 0
    skip_count = 0
    total = len(filings_index)
    max_file_bytes = 50 * 1024 * 1024  # 50 MB

    for i, (_, row) in enumerate(filings_index.iterrows(), 1):
        html_path = str(row.get("html_local_path", "") or "")
        if not html_path or not Path(html_path).exists():
            continue

        # Skip very large files (BeautifulSoup too slow on 100MB+ HTML)
        file_size = Path(html_path).stat().st_size
        if file_size > max_file_bytes:
            skip_count += 1
            continue

        cik = str(row.get("cik", "")).strip()
        entity_name = str(row.get("entity_name", "")).strip()
        accession = str(row.get("accession_number", "")).strip()
        form_type = str(row.get("form_type", "")).strip()
        filing_date = str(row.get("filing_date", "")).strip()
        report_date = str(row.get("report_date", "")).strip()

        try:
            records = _parse_financial_highlights(html_path)
            for rec in records:
                rec["cik"] = cik
                rec["entity_name"] = entity_name
                rec["accession_number"] = accession
                rec["form_type"] = form_type
                rec["filing_date"] = filing_date
                rec["report_date"] = report_date
                all_rows.append(rec)
            if records:
                ok_count += 1
            else:
                fail_count += 1
        except Exception as exc:
            logger.debug(
                "Failed to parse %s (CIK %s): %s", accession, cik, exc,
            )
            fail_count += 1

        if i % 200 == 0 or i == total:
            logger.info(
                "  N-CSR extraction progress: %d / %d (ok=%d, fail=%d, skip=%d)",
                i, total, ok_count, fail_count, skip_count,
            )

    logger.info(
        "N-CSR extraction: %d filings parsed, %d failed, %d skipped (>50MB), %d total records",
        ok_count, fail_count, skip_count, len(all_rows),
    )

    if not all_rows:
        result = pd.DataFrame(columns=_OUTPUT_COLS)
    else:
        result = pd.DataFrame(all_rows)
        result = _apply_guards(result)
        result = _derive_report_quarter(result)
        result = _dedup_filings(result)

        # Ensure all output columns
        for col in _OUTPUT_COLS:
            if col not in result.columns:
                result[col] = None
        result = result[_OUTPUT_COLS]

    result.to_csv(NCSR_FINANCIALS_FILE, index=False)

    elapsed = time.time() - t0
    logger.info(
        "N-CSR financials: %d rows, %d CIKs in %.1f s",
        len(result),
        result["cik"].nunique() if not result.empty else 0,
        elapsed,
    )
    return result


_OUTPUT_COLS = [
    "cik", "entity_name", "accession_number", "form_type",
    "filing_date", "report_date", "report_quarter", "period_type",
    "share_class",
    "nav_begin_per_share", "nav_end_per_share",
    "nii_per_share", "gain_loss_per_share",
    "distribution_from_nii", "distribution_from_gains",
    "distribution_return_of_capital", "distribution_per_share",
    "total_return_pct", "expense_ratio_pct", "income_yield_pct",
    "portfolio_turnover", "net_assets_end",
]


# ---------------------------------------------------------------------------
# C1. HTML parsing internals
# ---------------------------------------------------------------------------

def _parse_financial_highlights(html_path: str) -> list[dict]:
    """Parse all Financial Highlights tables from an N-CSR filing.

    Returns a list of records (one per share class per period), with
    the largest net_assets_end class kept per period.
    """
    text = Path(html_path).read_text(encoding="utf-8", errors="replace")
    soup = BeautifulSoup(text, "html.parser")

    tables = _find_fh_tables(soup)
    if not tables:
        return []

    # Detect dollar unit from document
    dollar_unit = _detect_dollar_unit(text)

    all_records: list[dict] = []
    for table in tables:
        records = _extract_table(table, dollar_unit)
        # If table yields nothing (stub/footnote table), try the next
        # sibling table — the real data is often in the table immediately
        # after a heading stub.
        if not records:
            next_sib = table.find_next_sibling("table")
            if next_sib is not None:
                records = _extract_table(next_sib, dollar_unit)
        all_records.extend(records)

    if not all_records:
        return []

    # Pick largest share class per period
    return _pick_largest_class(all_records)


def _find_fh_tables(soup: BeautifulSoup) -> list[Tag]:
    """Find Financial Highlights table(s) in the document.

    Skips TOC links, auditor opinions, regulatory wrapper text,
    and long narrative paragraphs that mention Financial Highlights.
    """
    tables: list[Tag] = []
    seen_tables: set[int] = set()

    # Walk all text nodes to find FH headings
    for elem in soup.find_all(string=_FH_HEADING_RE):
        parent = elem.parent
        if parent is None:
            continue

        # Skip TOC entries (links), auditor opinions, regulatory wrappers
        parent_text = parent.get_text(" ", strip=True) if parent else ""
        if parent.name == "a" and parent.get("href"):
            continue
        if "opinion on" in parent_text.lower():
            continue
        if "item 7" in parent_text.lower():
            continue
        # Skip if inside a <td> that looks like a TOC row
        td_parent = parent.find_parent("td")
        if td_parent and td_parent.find("a", href=True):
            continue
        # Skip long narrative paragraphs (>200 chars) that mention FH
        if len(parent_text) > 200:
            continue

        # Check if the heading is inside a <caption> element of a <table>
        # (old SGML-style filings put FH heading in <caption>).
        # Only match <caption>, not <td> — a heading in <td> would select
        # a wrapper table instead of the actual FH data table.
        caption_parent = parent.find_parent("caption")
        if caption_parent is not None:
            enclosing_table = caption_parent.find_parent("table")
            if enclosing_table is not None and id(enclosing_table) not in seen_tables:
                tables.append(enclosing_table)
                seen_tables.add(id(enclosing_table))
                continue

        # Find the next <table> after this heading
        table = _find_next_table(parent)
        if table is not None and id(table) not in seen_tables:
            tables.append(table)
            seen_tables.add(id(table))

    return tables


def _find_next_table(element: Tag) -> Tag | None:
    """Find the first <table> element after the given element."""
    # Walk forward through siblings, then up to parent and repeat
    current = element
    while current is not None:
        for sibling in current.next_siblings:
            if isinstance(sibling, Tag):
                if sibling.name == "table":
                    return sibling
                # Check if a table is nested inside this sibling
                inner = sibling.find("table")
                if inner is not None:
                    return inner
        current = current.parent
        if current is None or current.name == "[document]":
            break
    return None


def _detect_dollar_unit(text: str) -> float:
    """Detect dollar multiplier from document text (thousands, millions)."""
    lower = text[:50000].lower()
    if "in thousands" in lower or "(in thousands)" in lower:
        return 1_000.0
    if "in millions" in lower or "(in millions)" in lower:
        return 1_000_000.0
    return 1.0


def _extract_table(table: Tag, dollar_unit: float) -> list[dict]:
    """Extract records from a Financial Highlights table.

    Supports vertical layout (labels in column 1, periods across top)
    and horizontal layout (periods as rows).
    """
    rows = _get_table_rows(table)
    if len(rows) < 3:
        return []

    # Detect layout: vertical if first column has known field labels
    is_vertical = _detect_vertical_layout(rows)

    if is_vertical:
        return _extract_vertical(rows, dollar_unit)
    else:
        return _extract_horizontal(rows, dollar_unit)


def _get_table_rows(table: Tag) -> list[list[str]]:
    """Extract table as a list of rows, each a list of cell text strings.

    Respects colspan.
    """
    rows: list[list[str]] = []
    for tr in table.find_all("tr"):
        cells: list[str] = []
        for td in tr.find_all(["td", "th"]):
            cell_text = td.get_text(" ", strip=True)
            # Unescape HTML entities
            cell_text = html.unescape(cell_text)
            colspan = 1
            try:
                colspan = int(td.get("colspan", 1))
            except (ValueError, TypeError):
                pass
            cells.append(cell_text)
            for _ in range(colspan - 1):
                cells.append("")
        if cells:
            rows.append(cells)
    return rows


def _detect_vertical_layout(rows: list[list[str]]) -> bool:
    """Return True if this looks like a vertical Financial Highlights table.

    Vertical = row labels in column 0/1, period dates as column headers.
    """
    # Check first few non-empty rows for known label patterns in col 0
    label_hits = 0
    for row in rows[:20]:
        if not row:
            continue
        label = row[0].strip()
        if not label:
            continue
        for pat, _ in _ROW_LABEL_PATTERNS:
            if pat.search(label):
                label_hits += 1
                break
    return label_hits >= 2


def _extract_vertical(
    rows: list[list[str]],
    dollar_unit: float,
) -> list[dict]:
    """Extract from vertical layout: row labels in col 0, periods across top.

    Handles SEC HTML quirks: "$" in its own cell (value at col+1),
    split parentheses for negatives, and multi-row period headers.
    """
    if not rows:
        return []

    # Find period column headers (dates in first few rows)
    period_cols: list[tuple[int, str]] = []
    for ri, row in enumerate(rows[:8]):
        cols = _find_period_columns(row)
        if len(cols) >= 1:
            period_cols = cols
            break

    if not period_cols:
        # Fall back: treat each non-label column as a period (unnamed)
        if len(rows) > 0 and len(rows[0]) > 1:
            period_cols = [(ci, "") for ci in range(1, len(rows[0]))]
        if not period_cols:
            return []

    # Detect value column offset: SEC HTML often puts "$" in the header
    # column and the actual number in the next column.
    value_offsets = _detect_value_offsets(rows, period_cols)

    # Build per-period records
    records: list[dict] = []
    for pi, (col_idx, period_label) in enumerate(period_cols):
        rec: dict = {"period_label": period_label}
        period_info = _parse_period_label(period_label)
        rec["period_type"] = period_info.get("period_type", "")
        rec["period_end_date"] = period_info.get("end_date", "")

        offset = value_offsets[pi] if pi < len(value_offsets) else 0
        val_col = col_idx + offset

        for row in rows:
            if not row:
                continue
            label = row[0].strip()
            field = _match_row_label(label)
            if field is None:
                continue

            val_text = _read_cell_value(row, val_col)
            val = _parse_value(val_text, field, dollar_unit)
            if val is not None and field not in rec:
                rec[field] = val

        records.append(rec)

    return records


def _detect_value_offsets(
    rows: list[list[str]],
    period_cols: list[tuple[int, str]],
) -> list[int]:
    """Detect whether values are offset from period header columns.

    SEC HTML often puts "$" in the header column position, with the
    actual numeric value in the next column (offset=1).
    """
    offsets = []
    for col_idx, _ in period_cols:
        # Check first 20 data rows for this column
        offset_1_hits = 0
        offset_0_hits = 0
        for row in rows[:25]:
            if not row or len(row) <= col_idx:
                continue
            label = row[0].strip().lower() if row else ""
            if not label or not any(p.search(label) for p, _ in _ROW_LABEL_PATTERNS):
                continue
            cell_at_col = row[col_idx].strip() if col_idx < len(row) else ""
            cell_at_next = row[col_idx + 1].strip() if col_idx + 1 < len(row) else ""
            if cell_at_col == "$" or (not cell_at_col and _looks_numeric(cell_at_next)):
                offset_1_hits += 1
            elif _looks_numeric(cell_at_col):
                offset_0_hits += 1
        offsets.append(1 if offset_1_hits > offset_0_hits else 0)
    return offsets


def _looks_numeric(text: str) -> bool:
    """Return True if text looks like a numeric value (possibly negative)."""
    if not text:
        return False
    cleaned = text.replace(",", "").replace("$", "").replace("%", "").strip()
    cleaned = cleaned.strip("()")
    cleaned = cleaned.replace("-", "", 1).replace(".", "", 1)
    return bool(cleaned) and cleaned.replace(" ", "").isdigit()


def _read_cell_value(row: list[str], col_idx: int) -> str:
    """Read a cell value, handling SEC HTML split patterns.

    Scans forward past empty and "$" cells to find the actual value.
    Concatenates split parentheses: "(0.56" + ")" -> "(0.56)".
    """
    # Scan forward up to 3 positions to find actual content
    for offset in range(3):
        idx = col_idx + offset
        if idx >= len(row):
            return ""
        val = row[idx].strip()
        if val and val != "$":
            # Found actual content -- handle split negative parens
            if val.startswith("(") and not val.endswith(")"):
                next_idx = idx + 1
                if next_idx < len(row):
                    next_cell = row[next_idx].strip()
                    if next_cell in (")", "%)", "%)"):
                        val = val + next_cell
            return val
    return ""


def _extract_horizontal(
    rows: list[list[str]],
    dollar_unit: float,
) -> list[dict]:
    """Extract from horizontal layout: field names as headers, periods as rows.

    Handles multi-row headers by merging text from the first few rows
    that contain known field label keywords.
    """
    if len(rows) < 2:
        return []

    # Find the header row(s) -- merge text across multiple rows for
    # multi-row headers (common in PIMCO-style tables)
    header_row_idx, merged_headers = _find_merged_headers(rows)

    field_map: dict[int, str] = {}
    for ci, header in enumerate(merged_headers):
        field = _match_row_label(header.strip())
        if field is not None:
            field_map[ci] = field

    if not field_map:
        return []

    # Data rows start after headers; detect by looking for date-range
    # patterns (MM/DD/YYYY - MM/DD/YYYY) or known share class labels
    data_start = header_row_idx + 1

    records: list[dict] = []
    _date_range_re = re.compile(
        r"\d{1,2}/\d{1,2}/\d{4}\s*-\s*\d{1,2}/\d{1,2}/\d{4}", re.I,
    )
    for row in rows[data_start:]:
        if not row:
            continue
        # Skip share class label rows and empty rows
        row_text = " ".join(c.strip() for c in row)
        if not row_text.strip():
            continue

        rec: dict = {}
        has_value = False
        for ci, field in field_map.items():
            val_text = _read_cell_value(row, ci)
            val = _parse_value(val_text, field, dollar_unit)
            if val is not None:
                rec[field] = val
                has_value = True
        if has_value:
            # Try to get period from first column
            if 0 not in field_map and len(row) > 0:
                period_text = row[0].strip()
                rec["period_label"] = period_text
                period_info = _parse_period_label(period_text)
                if not period_info.get("end_date"):
                    # Try MM/DD/YYYY - MM/DD/YYYY format
                    m = _date_range_re.search(period_text)
                    if m:
                        end_part = m.group(0).split("-")[-1].strip()
                        try:
                            dt = datetime.strptime(end_part, "%m/%d/%Y")
                            period_info["end_date"] = dt.strftime("%Y-%m-%d")
                        except ValueError:
                            pass
                rec["period_type"] = period_info.get("period_type", "")
                rec["period_end_date"] = period_info.get("end_date", "")
            records.append(rec)

    return records


def _find_merged_headers(rows: list[list[str]]) -> tuple[int, list[str]]:
    """Find and merge multi-row column headers.

    Only merges rows that look like headers (text labels), not data rows
    (containing dates, dollar signs, or numeric values).
    Returns (last_header_row_index, merged_header_strings).
    """
    if not rows:
        return 0, []

    max_cols = max(len(r) for r in rows) if rows else 0
    merged = [""] * max_cols

    _date_range_re = re.compile(r"\d{1,2}/\d{1,2}/\d{4}")
    _data_row_re = re.compile(r"^\s*\$?\s*[\d,.]+\s*%?\s*$")

    # Scan first 8 rows to find header content
    last_header_idx = 0
    for ri, row in enumerate(rows[:8]):
        # Check if this is a data row by looking for date patterns or
        # rows where most non-empty cells are numeric
        row_text = row[0].strip() if row else ""
        if _date_range_re.search(row_text):
            break

        # Count numeric vs text cells to determine if header or data
        num_cells = 0
        text_cells = 0
        for cell in row[1:]:
            c = cell.strip()
            if not c or c == "$":
                continue
            if _data_row_re.match(c) or c in (")", "%)", "("):
                num_cells += 1
            else:
                text_cells += 1

        # If mostly numeric, this is a data row -- stop merging headers
        if num_cells > text_cells and num_cells > 2:
            break

        # Merge this row's text into headers
        for ci, cell in enumerate(row):
            text = cell.strip()
            if not text or text == "$":
                continue
            if ci < max_cols:
                if merged[ci]:
                    merged[ci] += " " + text
                else:
                    merged[ci] = text

        # Track if this row has a known label
        for ci, cell in enumerate(row):
            if _match_row_label(cell.strip()) is not None:
                last_header_idx = ri
                break

    return last_header_idx, merged


def _find_period_columns(row: list[str]) -> list[tuple[int, str]]:
    """Find columns that contain period date headings.

    Returns list of (column_index, date_text) tuples.
    """
    date_re = re.compile(
        r"(?:(?:year|six\s+months?|period|twelve\s+months?|semi[\s-]?annual"
        r"|for\s+the\s+(?:year|six\s+months?|period))"
        r"\s+ended\s+)?"
        r"(\w+\.?\s+\d{1,2},?\s+\d{4})",
        re.I,
    )
    cols = []
    for ci, cell in enumerate(row):
        if ci == 0:
            continue
        cell = cell.strip()
        if not cell:
            continue
        if date_re.search(cell):
            cols.append((ci, cell))
    return cols


def _parse_period_label(label: str) -> dict[str, str]:
    """Parse a period heading like 'Year Ended December 31, 2024'."""
    result: dict[str, str] = {}

    # Determine period type
    lower = label.lower()
    if "six month" in lower or "semi" in lower:
        result["period_type"] = "semi-annual"
    elif "year" in lower or "twelve month" in lower or "annual" in lower:
        result["period_type"] = "annual"
    else:
        result["period_type"] = ""

    # Parse end date
    date_match = re.search(
        r"(\w+)\.?\s+(\d{1,2}),?\s+(\d{4})", label,
    )
    if date_match:
        month_str = date_match.group(1).lower().rstrip(".")
        day = int(date_match.group(2))
        year = int(date_match.group(3))
        month = _MONTH_MAP.get(month_str)
        if month:
            result["end_date"] = f"{year}-{month:02d}-{day:02d}"

    return result


def _match_row_label(label: str) -> str | None:
    """Match a row label against known Financial Highlights fields."""
    if not label:
        return None
    for pat, field in _ROW_LABEL_PATTERNS:
        if pat.search(label):
            return field
    return None


def _parse_value(
    text: str,
    field: str,
    dollar_unit: float,
) -> float | None:
    """Parse a cell value into a float.

    Handles: parentheses (negative), dashes (NULL), $, %, footnotes,
    bare digit footnote markers, and unclosed parentheses.
    """
    if not text or not isinstance(text, str):
        return None

    text = text.strip()

    # Dashes or em-dashes = NULL
    if text in ("-", "--", "---", "N/A", "n/a", ""):
        return None
    if all(c in "-\u2014\u2013 " for c in text):
        return None

    # Strip footnote markers like (a), (1), (a,b)
    text = _FOOTNOTE_RE.sub("", text).strip()

    # Strip dollar signs and percent signs
    is_pct = "%" in text
    text = text.replace("$", "").replace("%", "").replace(",", "").strip()

    if not text:
        return None

    # Parentheses = negative (both closed and unclosed)
    m = _PAREN_NEG_RE.match(text)
    if m:
        text = m.group(1).strip()
        sign = -1.0
    elif text.startswith("(") and not text.endswith(")"):
        # Unclosed paren from split cells: "(0.56" without ")"
        text = text[1:].strip()
        sign = -1.0
    else:
        sign = 1.0

    # Strip trailing bare footnote markers (e.g., "6.74 5" -> "6.74")
    # Must come after paren handling but before numeric extraction
    text = re.sub(r"\s+\d{1,2}\s*$", "", text)

    # Strip any remaining non-numeric chars except . and -
    text = re.sub(r"[^\d.\-]", "", text)
    if not text:
        return None

    try:
        val = float(text) * sign
    except ValueError:
        return None

    # Apply dollar unit for net_assets_end (not percentages)
    if field == "net_assets_end" and not is_pct:
        val *= dollar_unit

    return val


def _pick_largest_class(records: list[dict]) -> list[dict]:
    """For multi-class funds, keep the class with largest net_assets_end per period."""
    if not records:
        return []

    # Group by period_end_date (or period_label if no date)
    from collections import defaultdict
    by_period: dict[str, list[dict]] = defaultdict(list)
    for rec in records:
        key = rec.get("period_end_date") or rec.get("period_label", "")
        by_period[key].append(rec)

    result: list[dict] = []
    for key, group in by_period.items():
        if len(group) == 1:
            result.append(group[0])
        else:
            # Pick the one with largest net_assets_end
            best = max(
                group,
                key=lambda r: float(r.get("net_assets_end") or 0),
            )
            result.append(best)

    return result


# ---------------------------------------------------------------------------
# C2. Post-processing
# ---------------------------------------------------------------------------

def _apply_guards(df: pd.DataFrame) -> pd.DataFrame:
    """Apply data quality guard rails -- clamp or null extreme values."""
    if df.empty:
        return df

    df = df.copy()

    # NAV range: $0.50 - $5000
    for col in ("nav_begin_per_share", "nav_end_per_share"):
        if col in df.columns:
            vals = pd.to_numeric(df[col], errors="coerce")
            mask = (vals < 0.50) | (vals > 5000)
            df.loc[mask, col] = None

    # Total return: -60% to +100%
    if "total_return_pct" in df.columns:
        vals = pd.to_numeric(df["total_return_pct"], errors="coerce")
        mask = (vals < -60) | (vals > 100)
        df.loc[mask, "total_return_pct"] = None

    # Expense ratio: 0-20%
    if "expense_ratio_pct" in df.columns:
        vals = pd.to_numeric(df["expense_ratio_pct"], errors="coerce")
        mask = (vals < 0) | (vals > 20)
        df.loc[mask, "expense_ratio_pct"] = None

    # Portfolio turnover: 0-500%
    if "portfolio_turnover" in df.columns:
        vals = pd.to_numeric(df["portfolio_turnover"], errors="coerce")
        mask = (vals < 0) | (vals > 500)
        df.loc[mask, "portfolio_turnover"] = None

    return df


def _dedup_filings(df: pd.DataFrame) -> pd.DataFrame:
    """Prefer N-CSR over N-CSRS for same (CIK, report_quarter).

    Also ranks by data completeness so periods with more extracted fields
    are preferred over empty/partial records.
    """
    if df.empty or "form_type" not in df.columns:
        return df

    df = df.copy()

    # Sort preference: N-CSR > N-CSR/A > N-CSRS > N-CSRS/A
    form_priority = {"N-CSR": 1, "N-CSR/A": 2, "N-CSRS": 3, "N-CSRS/A": 4}
    df["_form_priority"] = df["form_type"].map(form_priority).fillna(5)

    # Count non-null financial fields for completeness ranking
    _value_fields = [
        "nav_begin_per_share", "nav_end_per_share", "nii_per_share",
        "total_return_pct", "expense_ratio_pct", "net_assets_end",
    ]
    df["_completeness"] = df[
        [c for c in _value_fields if c in df.columns]
    ].notna().sum(axis=1)

    # Dedup on report_quarter (derived before this call)
    dedup_col = "report_quarter"
    df.sort_values(
        ["cik", dedup_col, "_completeness", "_form_priority"],
        ascending=[True, True, False, True],
        inplace=True,
    )
    df.drop_duplicates(subset=["cik", dedup_col], keep="first", inplace=True)
    df.drop(columns=["_form_priority", "_completeness"], inplace=True)

    return df


def _derive_report_quarter(df: pd.DataFrame) -> pd.DataFrame:
    """Derive report_quarter from period_end_date or report_date."""
    if df.empty:
        return df

    df = df.copy()

    def _to_quarter(date_str: str) -> str:
        if not date_str or not isinstance(date_str, str):
            return ""
        try:
            parts = date_str.split("-")
            if len(parts) < 2:
                return ""
            year = parts[0]
            month = int(parts[1])
            q = (month - 1) // 3 + 1
            return f"{year}q{q}"
        except (ValueError, IndexError):
            return ""

    # Prefer period_end_date, fall back to report_date
    if "period_end_date" in df.columns:
        df["report_quarter"] = df["period_end_date"].apply(_to_quarter)
        # Fill gaps from report_date
        mask = df["report_quarter"] == ""
        df.loc[mask, "report_quarter"] = (
            df.loc[mask, "report_date"].apply(_to_quarter)
        )
    else:
        df["report_quarter"] = df["report_date"].apply(_to_quarter)

    # Also set report_date from period_end_date if available
    if "period_end_date" in df.columns:
        mask = df["report_date"].isna() | (df["report_date"] == "")
        df.loc[mask, "report_date"] = df.loc[mask, "period_end_date"]
        # Drop internal columns
        df.drop(columns=["period_end_date", "period_label"], errors="ignore",
                inplace=True)

    return df
