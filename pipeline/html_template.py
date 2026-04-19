"""Template-based programmatic extraction for pre-XBRL BDC filings.

Applies per-CIK JSON templates (created by Claude Code instances) to
extract holdings from HTML schedule-of-investments tables. Zero LLM cost.

Usage::

    python -m pipeline.main --extract-html        # Extract all pre-XBRL filings
"""

import json
import logging
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import pandas as pd

from pipeline.config import (
    BDC_FILINGS_INDEX_FILE,
    BDC_HTML_CACHE_DIR,
    HTML_EXTRACTION_FILE,
    HTML_TEMPLATE_DIR,
)
from pipeline.html_holdings import (
    ScheduleTable,
    RowClassification,
    _build_column_map,
    _looks_numeric,
    _parse_dollar,
    _parse_rate,
    _strip_footnotes,
    _to_bdc_holdings_schema,
    classify_rows,
    download_html_filing,
    find_schedule_tables,
    post_process,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TEMPLATE_SCHEMA_VERSION = "2.0"
PROGRESS_SAVE_INTERVAL = 10

# Date format conversion patterns
_DATE_FORMATS = [
    (re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{4})$"), r"\3-\1-\2"),   # M/D/YYYY
    (re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{2})$"), None),           # M/D/YY
    (re.compile(r"^(\d{1,2})-(\d{1,2})-(\d{4})$"), r"\3-\1-\2"),    # M-D-YYYY
]

# Amendment #1: month-name date parsing (e.g., "January 2017" -> 2017-01-01).
# Hercules Capital and other BDCs use this format for maturity columns.
_MONTH_NAMES = {
    "january": 1, "february": 2, "march": 3, "april": 4,
    "may": 5, "june": 6, "july": 7, "august": 8,
    "september": 9, "october": 10, "november": 11, "december": 12,
    "jan": 1, "feb": 2, "mar": 3, "apr": 4,
    "jun": 6, "jul": 7, "aug": 8, "sep": 9, "sept": 9,
    "oct": 10, "nov": 11, "dec": 12,
}
_MONTH_NAME_DATE_RE = re.compile(
    r"^([A-Za-z]+)\s+(\d{4})$"
)
# "June 30 2024", "December 31, 2024" (comma stripped upstream).
_MONTH_DAY_YEAR_RE = re.compile(
    r"^([A-Za-z]+)\s+(\d{1,2})\s+(\d{4})$"
)

# Rate extraction patterns for embedded rate+spread in a single cell
_RATE_CELL_PATTERNS = [
    # "S+5.25% / 10.50%" or "L+4.00%/9.25%"
    # Amendment #32: re.IGNORECASE on all patterns.
    re.compile(
        r"([SLPE]|SF)\s*\+\s*([\d.]+)%?\s*/\s*([\d.]+)%?",
        re.IGNORECASE,
    ),
    # "12.00% (L+10.00%, Floor 2.00%)" — total rate before parenthesized ref+spread
    # Also supports "Base" for PRIME/base rate (Amendment #12).
    re.compile(
        r"([\d.]+)\s*%\s*\(\s*([SLPE]|SF|Base)\s*\+\s*([\d.]+)",
        re.IGNORECASE,
    ),
    # "12.00% (SOFR+10.00%, Floor 2.00%)" — total rate before full-name ref+spread
    re.compile(
        r"([\d.]+)\s*%\s*\(\s*(SOFR|LIBOR|PRIME|SOF|SF|EURIBOR)\s*\+?\s*([\d.]+)",
        re.IGNORECASE,
    ),
    # "10.00% (3ML+ 7.00%)" — total rate before NML/NMS reference+spread
    # NML = N-month LIBOR (1ML, 3ML, 6ML), NMS = N-month SOFR
    # Also handles space: "9.35% (1M L+725)" where "1M L" = 1-month LIBOR
    re.compile(
        r"([\d.]+)\s*%\s*\(\s*(\d+M\s*[LS])\s*\+\s*([\d.]+)",
        re.IGNORECASE,
    ),
    # "SOFR+5.25%" or "SOFR + 5.25" or "SF + 5.50"
    re.compile(
        r"(SOFR|LIBOR|PRIME|SOF|SF|EURIBOR)\s*\+\s*([\d.]+)%?",
        re.IGNORECASE,
    ),
    # "S+5.25%" or "E+3.00%" or "Base+ 2.50%" (Amendment #12)
    re.compile(
        r"([SLPE]|Base)\s*\+\s*([\d.]+)%?",
        re.IGNORECASE,
    ),
]

_REFERENCE_MAP = {
    "S": "SOFR", "SOF": "SOFR", "SOFR": "SOFR", "SF": "SOFR",
    "L": "LIBOR", "LIBOR": "LIBOR",
    "P": "PRIME", "PRIME": "PRIME",
    "E": "EURIBOR", "EURIBOR": "EURIBOR",
    # "Base" rate -> PRIME (Amendment #12). Used by BlackRock Capital etc.
    "Base": "PRIME", "BASE": "PRIME",
    # N-month LIBOR/SOFR (e.g. "3ML" = 3-month LIBOR)
    "1ML": "LIBOR", "3ML": "LIBOR", "6ML": "LIBOR", "12ML": "LIBOR",
    "1MS": "SOFR", "3MS": "SOFR", "6MS": "SOFR",
}

# Pattern for spread cells that embed the reference rate code:
# "S + 500", "P + 232", "S+500", "SOFR + 5.25", "SF + 5.50", "E + 3.00",
# "Base + 400" (Amendment #12).
# Amendment #32: case-insensitive spread cell matching.
_SPREAD_CELL_PATTERN = re.compile(
    r"([SLPE]|SF|SOFR|LIBOR|PRIME|EURIBOR|Base)\s*\+\s*(\d+(?:\.\d+)?)",
    re.IGNORECASE,
)

# Amendment #7: strip parenthetical footnote markers like "(r)", "(4)",
# "(13)" from header text before word-level comparison. SEC filings
# commonly append footnote refs to header words without a separating
# space, e.g. "Cost(r)" which would otherwise never match "cost".
_FOOTNOTE_PAREN_RE = re.compile(r"\([^)]*\)")

# PIK detection -- two formats:
#   "PIK 5.00%" (number after PIK)
#   "14.00 % PIK" (number before PIK, pure PIK)
#   "9.42 % ( 3.00 % PIK)" (partial PIK in parenthetical)
_PIK_AFTER_RE = re.compile(r"PIK\s*([\d.]+\s*%?)", re.IGNORECASE)
_PIK_BEFORE_RE = re.compile(r"([\d.]+\s*%?)\s*PIK", re.IGNORECASE)
_PIK_PARTIAL_RE = re.compile(
    r"\(\s*(?:incl\.?\s*)?([\d.]+\s*%?)\s*PIK\s*\)", re.IGNORECASE,
)
# Strip PIK notation so _parse_rate sees a clean number.
# Three alternatives (order matters -- most specific first):
#   1. Parenthetical PIK: "(3.00% PIK)" or "(incl. 1.50% PIK)"
#   2. "plus" PIK: "plus 10.00% PIK" (must strip the "plus X%" too)
#   3. Bare PIK suffix: " PIK"
_PIK_STRIP_RE = re.compile(
    r"\s*\(\s*(?:incl\.?\s*)?[\d.]+\s*%?\s*PIK\s*\)"
    r"|\s*plus\s+[\d.]+\s*%?\s*PIK\b"
    r"|\s*PIK\b",
    re.IGNORECASE,
)


# =====================================================================
# Programmatic Extraction
# =====================================================================

def _get_logical_columns(header: list[str]) -> list[int]:
    """Return grid-level indices of non-empty header cells.

    These define the logical column positions.  Logical index 0 maps to
    ``grid_positions[0]``, logical index 1 maps to ``grid_positions[1]``, etc.
    """
    return [i for i, cell in enumerate(header) if cell.strip()]


def _dense_row(row: list[str], grid_positions: list[int]) -> list[str]:
    """Collapse a grid-level row to only the logical column positions.

    For dollar-value cells that split ``$`` and the number into adjacent
    cells, the ``$`` is prepended to the next cell's content so the value
    reads naturally (e.g. ``$ 13.2``).
    """
    out: list[str] = []
    for gi in grid_positions:
        if gi >= len(row):
            out.append("")
            continue
        val = row[gi].strip()
        # If this cell is just "$", the real value is in the next cell
        if val == "$" and gi + 1 < len(row):
            next_val = row[gi + 1].strip()
            out.append(f"$ {next_val}" if next_val else "$")
        else:
            out.append(val)
    return out


def _html_to_schedule_markdown(html: str) -> str:
    """Extract schedule-of-investments tables from HTML, convert to markdown.

    Produces a **dense** markdown table with only the non-empty header columns
    so column indices are small integers (0, 1, 2, ...) that an LLM can
    reliably identify.  Dollar-value cells that SEC HTML splits into
    ``$`` + number + empty across three ``<td>`` elements are recombined
    into single cells (e.g. ``$ 13.2``).

    Also includes surrounding page text for dollar-unit context.
    Only the first 40 data rows are included per table to stay within
    reasonable token budgets for template learning.
    """
    try:
        from bs4 import BeautifulSoup as BS
    except ImportError:
        raise ImportError(
            "beautifulsoup4 required. Install: pip install beautifulsoup4 lxml"
        )

    soup = BS(html, "lxml")

    # Remove script/style tags
    for tag in soup.find_all(["script", "style"]):
        tag.decompose()

    # Grab dollar-unit context from nearby text
    context_snippets: list[str] = []
    for elem in soup.find_all(["p", "div", "span"], limit=80):
        t = elem.get_text(strip=True)
        if t and len(t) < 500:
            context_snippets.append(t)
    page_context = "\n".join(context_snippets[:30])

    # Find schedule tables
    tables = find_schedule_tables(html)
    if not tables:
        return ""

    parts: list[str] = []

    # Include dollar-unit context
    for line in page_context.split("\n"):
        lower = line.lower()
        if any(kw in lower for kw in [
            "thousand", "million", "(000", "schedule of investment",
            "consolidated schedule",
        ]):
            parts.append(f"> {line}")
    if parts:
        parts.append("")

    MAX_DATA_ROWS = 40  # enough to see all column patterns, save tokens

    for ti, table in enumerate(tables):
        header = table.rows[table.header_row_idx]
        grid_positions = _get_logical_columns(header)

        if not grid_positions:
            continue

        parts.append(
            f"### Table {ti + 1} (score={table.score:.1f}, "
            f"dollar_unit={table.dollar_unit}, "
            f"grid_columns={len(header)}, "
            f"logical_columns={len(grid_positions)})"
        )
        parts.append("")

        # Dense header row
        dense_header = _dense_row(header, grid_positions)
        escaped = [c.replace("|", "\\|") for c in dense_header]
        parts.append("| " + " | ".join(escaped) + " |")
        parts.append("| " + " | ".join(["---"] * len(dense_header)) + " |")

        # Dense data rows (limited)
        data_count = 0
        for ri in range(table.header_row_idx + 1, len(table.rows)):
            row = table.rows[ri]
            dense = _dense_row(row, grid_positions)
            escaped = [c.replace("|", "\\|") for c in dense]
            parts.append("| " + " | ".join(escaped) + " |")
            data_count += 1
            if data_count >= MAX_DATA_ROWS:
                parts.append(
                    f"| ... ({len(table.rows) - table.header_row_idx - 1 - MAX_DATA_ROWS}"
                    f" more data rows) ... |"
                )
                break

        parts.append("")

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Amendment #25: Filing-date-aware variant selection (tiebreaker only)
# ---------------------------------------------------------------------------
# Variants in a per-CIK template often correspond to distinct format eras
# (e.g., a 2013 legacy schedule vs. a 2020 modern schedule).  Header-based
# scoring alone cannot reliably distinguish them when header vocabularies
# overlap, which has caused post-2019 filings to be routed to legacy
# variants (CION, Oaktree, Main Street, etc.).
#
# This module adds an out-of-band signal: the filing date is used to
# narrow the candidate variants to those whose [effective_from,
# effective_until) window contains the filing date.  When the template
# does not declare these fields explicitly, they are auto-derived from
# the ``source_filing`` accession of each variant, looked up in
# ``bdc_filings_index.csv``.

_ACCESSION_DATE_CACHE: Optional[dict[str, str]] = None


def _load_accession_dates() -> dict[str, str]:
    """Lazy-load {accession_number: filing_date} from bdc_filings_index.csv.

    Returns empty dict if the index file is missing.  Caches across calls.
    """
    global _ACCESSION_DATE_CACHE
    if _ACCESSION_DATE_CACHE is not None:
        return _ACCESSION_DATE_CACHE
    if not BDC_FILINGS_INDEX_FILE.exists():
        _ACCESSION_DATE_CACHE = {}
        return _ACCESSION_DATE_CACHE
    try:
        df = pd.read_csv(
            BDC_FILINGS_INDEX_FILE,
            dtype=str,
            usecols=["accession_number", "filing_date"],
        )
        df = df.dropna(subset=["accession_number", "filing_date"])
        _ACCESSION_DATE_CACHE = dict(
            zip(df["accession_number"], df["filing_date"])
        )
    except Exception as exc:
        logger.warning("Failed to load accession date map: %s", exc)
        _ACCESSION_DATE_CACHE = {}
    return _ACCESSION_DATE_CACHE


def _reset_accession_date_cache() -> None:
    """Test hook: clear the cached accession->date map."""
    global _ACCESSION_DATE_CACHE
    _ACCESSION_DATE_CACHE = None


def _variant_date_ranges(
    template: dict,
) -> dict[str, tuple[Optional[str], Optional[str]]]:
    """Derive per-variant (effective_from, effective_until) date windows.

    When a variant declares ``effective_from`` / ``effective_until``
    explicitly in the template, those values are used verbatim.

    Otherwise, windows are auto-derived from ``source_filing`` dates:
      * Variants are sorted by their source filing date.
      * Variant i covers filings from its own source date up to (but not
        including) variant (i+1)'s source date.
      * The earliest variant's window is open-ended on the left
        (``effective_from = None``) so it claims any filing predating
        every template source.
      * The latest variant's window is open-ended on the right
        (``effective_until = None``).

    Returns ``{format_id: (from_date_or_None, until_date_or_None)}``.
    A missing format_id in the returned map means the variant has no
    discoverable date range and will be treated as unrestricted.
    """
    variants = template.get("variants") or []
    if not variants:
        return {}

    date_map = _load_accession_dates()

    dated: list[tuple[str, Optional[str]]] = []
    for v in variants:
        fid = v.get("format_id") or v.get("variant_id") or "primary"
        src = v.get("source_filing") or ""
        # Accession numbers appear in two forms: "0001414932-20-000004"
        # (with dashes, as used in templates) and stripped.  The filings
        # index stores the dashed form.
        src_date = date_map.get(src)
        if src_date is None and src:
            # Fall back to stripped lookup just in case
            src_stripped = src.replace("-", "")
            for acc, dt in date_map.items():
                if acc.replace("-", "") == src_stripped:
                    src_date = dt
                    break
        dated.append((fid, src_date))

    # Sort by source date (missing dates sort last).  ISO dates sort
    # lexicographically.
    dated_sorted = sorted(
        dated, key=lambda x: (x[1] is None, x[1] or "")
    )

    ranges: dict[str, tuple[Optional[str], Optional[str]]] = {}
    n = len(dated_sorted)
    for i, (fid, src_date) in enumerate(dated_sorted):
        if src_date is None:
            # Variant with no resolvable source date: treat as
            # unrestricted (covers any filing).  Do not record a range.
            continue
        # Earliest variant: open on the left so pre-source filings map
        # to it.
        eff_from = None if i == 0 else src_date

        # End bound = next variant's source date (exclusive).  If the
        # next variant has no source date, walk forward until we find
        # one; if none exists, this variant is open on the right.
        eff_until = None
        for j in range(i + 1, n):
            if dated_sorted[j][1] is not None:
                eff_until = dated_sorted[j][1]
                break
        ranges[fid] = (eff_from, eff_until)

    # Explicit template overrides take precedence.
    for v in variants:
        fid = v.get("format_id") or v.get("variant_id") or "primary"
        if "effective_from" in v or "effective_until" in v:
            cur = ranges.get(fid, (None, None))
            ranges[fid] = (
                v.get("effective_from", cur[0]),
                v.get("effective_until", cur[1]),
            )

    return ranges


def _in_range(
    filing_date: str,
    eff_from: Optional[str],
    eff_until: Optional[str],
) -> bool:
    """Half-open interval check: ``eff_from <= filing_date < eff_until``.

    ``None`` on either side means unbounded on that side.  ISO date
    strings (YYYY-MM-DD) compare lexicographically.
    """
    if not filing_date:
        return True  # No filing date -> do not exclude
    if eff_from is not None and filing_date < eff_from:
        return False
    if eff_until is not None and filing_date >= eff_until:
        return False
    return True


def _filter_variants_by_date(
    variants: list[dict],
    template: dict,
    filing_date: Optional[str],
) -> list[dict]:
    """Return variants whose date window contains ``filing_date``.

    If ``filing_date`` is missing or no variant has a discoverable date
    range, returns the input list unchanged.  If filtering produces an
    empty result (filing date outside all ranges), returns the input
    list unchanged so the scorer can still make a decision.
    """
    if not filing_date:
        return variants
    ranges = _variant_date_ranges(template)
    if not ranges:
        return variants

    filtered: list[dict] = []
    for v in variants:
        fid = v.get("format_id") or v.get("variant_id") or "primary"
        window = ranges.get(fid)
        if window is None:
            # Variant has no resolvable date range -> include as
            # candidate.  Header-based scoring will handle it.
            filtered.append(v)
            continue
        if _in_range(filing_date, window[0], window[1]):
            filtered.append(v)

    # If no variant claims this filing date, fall back to all variants.
    if not filtered:
        return variants
    return filtered


def _normalize_template(template: dict) -> dict:
    """Ensure template has a ``variants`` array.

    v1.0 templates store column_mapping / value_formats / etc. at the top
    level.  This function wraps them into a single-element ``variants``
    list so downstream code can always iterate over ``template["variants"]``.

    v2.0 templates (already have ``variants``) are returned as-is.
    """
    if "variants" in template:
        return template

    # Wrap v1.0 fields into a single variant
    variant: dict[str, Any] = {
        "format_id": "default",
    }
    for key in (
        "column_mapping", "value_formats", "row_conventions",
        "filer_quirks", "programmatic_analysis",
    ):
        if key in template:
            variant[key] = template[key]

    out = dict(template)
    out["variants"] = [variant]
    return out


def _select_best_variant(
    table: ScheduleTable,
    template: dict,
    filing_date: Optional[str] = None,
) -> dict:
    """Pick the variant whose structure best matches *table*.

    For each variant, calls ``_detect_template_drift`` and counts real
    mismatches.  The variant with the fewest mismatches wins; ties are
    broken by column count closeness (smaller delta = better fit), then
    by grid position overlap (more overlap = better fit), then by
    variant order (first = preferred / modern).

    Amendment #25 (date-aware tiebreaker): When two or more variants
    score identically on header matching (same real/shift/skip/col_delta
    /gp_overlap), ``filing_date`` is used as the FINAL tiebreaker.  The
    variant whose [effective_from, effective_until) window contains the
    filing date wins the tie.  This does NOT override header evidence:
    if one variant scores strictly better than another on headers, it
    wins regardless of date.

    This matters for filers like CION (CIK 1534254) whose 2014 and 2017
    variants produce identical header scores because their column sets
    overlap; pure header scoring picks the legacy variant and extracts
    0 rows.  Date tiebreaking steers post-2017 filings to the 2017
    variant.  For filers like PhenixFIN (CIK 1490349) whose 10-K and
    10-Q filings alternate between two variants concurrently, header
    scoring differentiates them and the date tiebreaker never activates.

    Returns the winning variant dict (contains column_mapping,
    value_formats, etc.).
    """
    variants = template.get("variants", [])
    if not variants:
        return {}
    if len(variants) == 1:
        return variants[0]

    header = table.rows[table.header_row_idx]
    actual_gp = set(_get_logical_columns(header))
    actual_col_count = len(actual_gp)

    # Precompute date-range match for each variant (amendment #23 tiebreaker).
    date_ranges = _variant_date_ranges(template) if filing_date else {}

    def _date_match(variant: dict) -> bool:
        """True if variant's date window contains filing_date."""
        if not filing_date or not date_ranges:
            return False
        fid = variant.get("format_id") or variant.get("variant_id") or "primary"
        window = date_ranges.get(fid)
        if window is None:
            return False
        return _in_range(filing_date, window[0], window[1])

    best_variant = variants[0]
    best_key: tuple | None = None

    for variant in variants:
        # Wrap variant to look like a top-level template for drift detection
        pseudo = dict(variant)
        # _detect_template_drift reads column_mapping + programmatic_analysis
        # which are already in the variant dict.
        _, reasons = _detect_template_drift(table, pseudo)

        real, shift, skip = _count_real_mismatches(reasons, header)

        # Column count closeness: smaller delta = better structural match.
        variant_cc = variant.get("programmatic_analysis", {}).get(
            "column_count", actual_col_count
        )
        col_delta = abs(actual_col_count - variant_cc)

        # Grid position overlap: how many template grid positions land on
        # actual header positions.  Higher = better structural match.
        variant_gp = variant.get("programmatic_analysis", {}).get(
            "grid_positions", []
        )
        gp_overlap = len(set(variant_gp) & actual_gp)

        # Date-match bit as final tiebreaker (amendment #25).  0 = match
        # (preferred), 1 = no match.  Only activates when every upstream
        # tiebreaker is equal, so it never overrides header evidence.
        date_rank = 0 if _date_match(variant) else 1

        # Amendments #2 + #8 + #25: tiebreaker chain is
        #   real -> shift -> skip -> col_delta -> gp_overlap (desc) -> date_rank.
        # Lower real/shift/skip/col_delta/date_rank is better; higher
        # gp_overlap is better, so negate it for lexicographic min.
        key = (real, shift, skip, col_delta, -gp_overlap, date_rank)
        if best_key is None or key < best_key:
            best_key = key
            best_variant = variant

    return best_variant


def load_template(cik: str) -> Optional[dict]:
    """Load a saved template for a CIK.

    Returns None if no template file exists or JSON is invalid.
    """
    cik_stripped = str(cik).lstrip("0") or "0"
    path = HTML_TEMPLATE_DIR / f"{cik_stripped}.json"
    if not path.exists():
        return None
    try:
        with open(path) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def _apply_template_column_map(
    row_cells: list[str],
    template: dict,
    detected_dollar_unit: int = 1,
) -> dict:
    """Extract fields from a row using the template's column mapping.

    Template column indices are **logical** (dense, 0-based among non-empty
    header cells).  They are converted to grid-level indices using the
    ``grid_positions`` mapping stored in ``programmatic_analysis``.

    Handles:
    - Logical-to-grid index conversion
    - "$" + number split in SEC HTML
    - Embedded rate+spread extraction from rate cells
    - Date format conversion

    Amendment #9: when ``value_formats.dollar_unit_auto`` is true, the
    ``detected_dollar_unit`` argument (usually ``table.dollar_unit``) is
    used instead of the template's static ``dollar_unit``.  Useful for
    filers whose unit changed mid-era.
    """
    cm = template.get("column_mapping", {})
    vf = template.get("value_formats", {})
    quirks = template.get("filer_quirks", {})
    if vf.get("dollar_unit_auto"):
        dollar_unit = detected_dollar_unit
    else:
        dollar_unit = vf.get("dollar_unit", 1)

    # Logical-to-grid mapping (if present).
    # Some filers have variant row widths within the same filing (e.g.,
    # comparative-period rows include an extra Acquisition Date column that
    # shifts dollar fields by +2).  Detect the width delta and apply it
    # to grid positions that would otherwise map to empty cells.
    pa = template.get("programmatic_analysis", {})
    grid_positions = pa.get("grid_positions")
    # Width delta: positive when row is wider, negative when narrower.
    # Only apply when abs(delta) >= 2 to avoid false positives from minor
    # padding variations (e.g., 15 vs 16 cells from trailing empty columns).
    _row_width_delta = 0
    # When expected_row_width is explicitly set, use it for precise delta
    # calculation. This enables proactive grid shifting for filers with
    # narrower continuation rows (e.g., Prospect Capital where continuation
    # rows drop company+industry columns, shifting all data left by 6).
    _proactive_shift = False
    _explicit_expected = pa.get("expected_row_width")
    if _explicit_expected:
        actual_width = len(row_cells)
        delta = actual_width - _explicit_expected
        if abs(delta) >= 2:
            _row_width_delta = delta
            _proactive_shift = True
    elif grid_positions:
        expected_width = max(grid_positions) + 3  # +3 for trailing padding
        actual_width = len(row_cells)
        delta = actual_width - expected_width
        if abs(delta) >= 2:
            _row_width_delta = delta

    result: dict[str, Any] = {
        "issuer_name": None,
        "instrument_description": None,
        "industry": None,
        "interest_rate": None,
        "reference_rate": None,
        "basis_spread": None,
        "maturity_date": None,
        "principal_amount": None,
        "cost": None,
        "fair_value": None,
        "shares_held": None,
        "pct_of_net_assets": None,
        "pik_rate": None,
        "cash_rate_raw": None,
        # Raw cell text (always preserved, even when parsing fails)
        "raw_interest_rate": None,
        "raw_basis_spread": None,
        "raw_maturity_date": None,
        "raw_fair_value": None,
        "raw_cost": None,
        "raw_principal_amount": None,
        "raw_shares_held": None,
        "raw_pct_of_net_assets": None,
    }

    # Fields where an empty cell should trigger a look-ahead to the next
    # grid cell (handles colspan offset: header at grid idx N, data at N+1).
    # Includes text fields like instrument_description/reference_rate/industry
    # because some filers (e.g. Golub 2013) have data consistently offset
    # +1 from header positions.  Excludes company to avoid false reads on
    # continuation rows (company empty = name propagation).
    _NUMERIC_FIELDS = {
        "fair_value", "cost", "principal_amount", "interest_rate",
        "shares_held", "pct_of_net_assets", "basis_spread",
        "instrument_description", "maturity_date", "reference_rate",
        "industry",
    }
    # Fields eligible for width-delta retry (numeric + date fields).
    _SHIFTABLE_FIELDS = _NUMERIC_FIELDS | {"maturity_date"}

    def _get_cell(field_name: str) -> Optional[str]:
        entry = cm.get(field_name, {})
        if not isinstance(entry, dict):
            return None

        # Direct grid index (for columns without headers, e.g. company
        # columns that have no header text in the HTML table).
        direct_grid = entry.get("grid_index")
        if direct_grid is not None:
            idx = direct_grid
        else:
            logical_idx = entry.get("index")
            if logical_idx is None or logical_idx < 0:
                return None

            # Convert logical index to grid index
            if grid_positions and logical_idx < len(grid_positions):
                idx = grid_positions[logical_idx]
            else:
                idx = logical_idx  # fallback: treat as grid index

        # Proactive grid shift: when expected_row_width is set and the
        # row is narrower/wider, shift ALL grid positions by the delta.
        # This handles filers where continuation rows drop leading columns
        # (e.g., company+industry), shifting all remaining data left.
        if _proactive_shift and _row_width_delta != 0:
            idx = idx + _row_width_delta
            if idx < 0 or idx >= len(row_cells):
                return None

        if idx >= len(row_cells):
            return None
        # Strip whitespace and zero-width spaces (U+200B) common in modern
        # SEC HTML where every cell is padded with \u200b.
        val = row_cells[idx].strip().strip("\u200b").strip()
        # Handle "$" + number split: when a cell is just "$", the actual
        # value is in the next cell (common in SEC HTML with colspan).
        if val == "$" and idx + 1 < len(row_cells):
            val = row_cells[idx + 1].strip().strip("\u200b").strip()
        # Colspan offset: header uses colspan=2 but data cells are
        # colspan=1, so the value lands at grid idx+1 instead of idx.
        # Try the next cell for eligible fields when current cell is empty.
        elif not val and field_name in _NUMERIC_FIELDS and idx + 1 < len(row_cells):
            next_val = row_cells[idx + 1].strip().strip("\u200b").strip()
            # For text-category fields (industry), reject numeric look-ahead
            # to avoid grabbing a dollar/rate value from the adjacent column.
            if next_val and field_name == "industry":
                cleaned = next_val.replace(",", "").replace("$", "").strip()
                try:
                    float(cleaned)
                    next_val = ""  # numeric -- don't use
                except ValueError:
                    pass  # non-numeric -- keep it
            val = next_val
        # Width-delta retry: when the row width differs from expected (e.g.,
        # comparative period with extra/fewer columns), try the same logical
        # position shifted by the width delta.  Skip when proactive shift
        # is active (already applied above, avoid double-shifting).
        if (not _proactive_shift and not val and _row_width_delta != 0
                and field_name in _SHIFTABLE_FIELDS):
            shifted_idx = idx + _row_width_delta
            if shifted_idx < len(row_cells):
                sval = row_cells[shifted_idx].strip().strip("\u200b").strip()
                if sval == "$" and shifted_idx + 1 < len(row_cells):
                    sval = row_cells[shifted_idx + 1].strip().strip("\u200b").strip()
                elif not sval and shifted_idx + 1 < len(row_cells):
                    sval = row_cells[shifted_idx + 1].strip().strip("\u200b").strip()
                if sval and sval.startswith("$") and len(sval) > 1:
                    sval = sval[1:].strip()
                if sval:
                    val = sval
        # Handle split reference+spread cells (e.g., "SF +" in one cell,
        # "5.50 %" in the next non-empty cell).  Concatenate so the
        # _SPREAD_CELL_PATTERN can match the full "SF + 5.50" text.
        # Amendment #17: also handles multi-word reference codes like
        # "1M USD SOFR+", "3M USD LIBOR +", "Base +", etc.  Anything
        # whose stripped text ends with "+" after a word character qualifies.
        if val and re.match(
            r"^(?:[A-Za-z][A-Za-z0-9 ]*?|\d+M\s+USD\s+[A-Z]+)\s*\+\s*$",
            val,
        ):
            for nidx in range(idx + 1, min(idx + 6, len(row_cells))):
                nval = row_cells[nidx].strip().strip("\u200b").strip()
                if nval and re.search(r"\d", nval):
                    val = val + " " + nval
                    break
        # Amendment #25b: split parenthetical negative concatenation.
        # SEC HTML sometimes splits "(12,987)" across cells: "(12,987" in
        # one cell, ")" in the next.  Concatenate so _parse_dollar sees
        # the full "(12,987)" and handles it as negative.
        if val and re.match(r"^\([\d,.]+$", val):
            for nidx in range(idx + 1, min(idx + 3, len(row_cells))):
                nval = row_cells[nidx].strip().strip("\u200b").strip()
                if nval == ")":
                    val = val + ")"
                    break
                elif nval:
                    break  # non-closing-paren content, stop
        # Amendment #26: split PIK notation concatenation.
        # SEC HTML can split "(PIK 1.00" across cells: "(PIK 1.00" in one,
        # "%)" or "%" in the next.  Concatenate so PIK regex sees full text.
        if val and re.match(r".*\(PIK\s+[\d.]+$", val, re.IGNORECASE):
            for nidx in range(idx + 1, min(idx + 3, len(row_cells))):
                nval = row_cells[nidx].strip().strip("\u200b").strip()
                if nval and re.match(r"^%?\s*\)?$", nval):
                    val = val + " " + nval
                    break
                elif nval:
                    break
        # Also handle "$X" (dollar sign prefix without split)
        if val and val.startswith("$") and len(val) > 1:
            val = val[1:].strip()
        return val if val else None

    # Company / issuer name
    company_cell = _get_cell("company")
    if company_cell:
        # If instrument is in company cell (multi-line), take first line
        if quirks.get("instrument_in_company_cell"):
            lines = company_cell.split("\n")
            if not lines:
                lines = [company_cell]
            # Amendment #24: when no newline split found, try dash separators.
            if len(lines) == 1:
                for sep in ["\u2013", "\u2014", " -- "]:
                    parts = lines[0].split(sep, 1)
                    if len(parts) == 2:
                        lines = [parts[0].strip(), parts[1].strip()]
                        break
            result["issuer_name"] = lines[0].strip()
            if len(lines) > 1:
                result["instrument_description"] = lines[1].strip()
        else:
            result["issuer_name"] = company_cell

    # Instrument description from its own column (e.g., Ares "Investment")
    if not result.get("instrument_description"):
        inst_cell = _get_cell("instrument_description")
        if inst_cell:
            result["instrument_description"] = _strip_footnotes(inst_cell)

    # Industry from its own column (e.g., SLR "Industry")
    ind_entry = cm.get("industry", {})
    if isinstance(ind_entry, dict) and ind_entry.get("source") == "column":
        ind_cell = _get_cell("industry")
        if ind_cell:
            result["industry"] = _strip_footnotes(ind_cell)

    # Dollar fields
    for field in ["fair_value", "cost", "principal_amount"]:
        raw = _get_cell(field)
        result[f"raw_{field}"] = raw  # Preserve raw cell text always
        val = _parse_dollar(raw)
        if val is not None:
            result[field] = val * dollar_unit
        else:
            result[field] = None

    # Dollar-sign rescue: when any dollar field is missing, scan the row
    # for "$" markers and map them to principal_amount, cost, fair_value
    # (left-to-right order).  Handles column-shifted rows (variant widths
    # from comparative periods with extra columns).
    missing_dollar = [
        f for f in ["principal_amount", "cost", "fair_value"]
        if result[f] is None
    ]
    if missing_dollar:
        dollar_positions = [
            i for i in range(len(row_cells))
            if row_cells[i].strip() == "$"
        ]
        # Last 3 "$" markers = principal_amount, cost, fair_value
        _DOLLAR_FIELDS_LTR = [
            "principal_amount", "cost", "fair_value",
        ]
        if len(dollar_positions) >= 3:
            tail = dollar_positions[-3:]
            for field, dp in zip(_DOLLAR_FIELDS_LTR, tail):
                if result[field] is None and dp + 1 < len(row_cells):
                    val = _parse_dollar(
                        row_cells[dp + 1].strip()
                    )
                    if val is not None:
                        result[field] = val * dollar_unit

    # Interest rate cell -- may contain embedded reference rate + spread
    rate_cell = _get_cell("interest_rate")
    if rate_cell:
        result["raw_interest_rate"] = rate_cell  # Preserve raw cell text
        rate_cell_clean = _strip_footnotes(rate_cell)

        # Check for PIK notation
        # Partial PIK first: "9.42 % ( 3.00 % PIK)"
        pik_partial = _PIK_PARTIAL_RE.search(rate_cell_clean)
        if pik_partial:
            result["pik_rate"] = _parse_rate(pik_partial.group(1))
        else:
            # "PIK 5.00%" (number after)
            pik_after = _PIK_AFTER_RE.search(rate_cell_clean)
            if pik_after:
                result["pik_rate"] = _parse_rate(pik_after.group(1))
            else:
                # "14.00 % PIK" (number before, pure PIK)
                pik_before = _PIK_BEFORE_RE.search(rate_cell_clean)
                if pik_before:
                    result["pik_rate"] = _parse_rate(pik_before.group(1))

        # Multi-cell PIK: some filers (e.g. Golub 2025+) put "PIK" in a
        # separate cell after the interest rate cell.  Scan cells between
        # the rate column and the next mapped column for PIK indicators.
        if result["pik_rate"] is None:
            ir_entry = cm.get("interest_rate", {})
            ir_grid = None
            if isinstance(ir_entry, dict):
                ir_grid = ir_entry.get("grid_index")
                if ir_grid is None:
                    ir_logical = ir_entry.get("index")
                    if (ir_logical is not None and grid_positions
                            and ir_logical < len(grid_positions)):
                        ir_grid = grid_positions[ir_logical]
            if ir_grid is not None:
                # Find next mapped grid position after interest_rate
                next_gp = len(row_cells)
                for gp in sorted(grid_positions or []):
                    if gp > ir_grid:
                        next_gp = gp
                        break
                # Collect non-empty cell text between rate and next column
                trail_parts: list[str] = []
                for ci in range(ir_grid + 1, min(next_gp, len(row_cells))):
                    cv = row_cells[ci].strip().strip("\u200b").strip()
                    if cv:
                        trail_parts.append(cv)
                trail_text = " ".join(trail_parts)
                if re.search(r"\bPIK\b", trail_text, re.IGNORECASE):
                    # Partial PIK: "cash/ 2.25 % PIK"
                    partial_m = re.search(
                        r"cash\s*/?\s*([\d.]+\s*%?)\s*PIK",
                        trail_text, re.IGNORECASE,
                    )
                    if partial_m:
                        result["pik_rate"] = _parse_rate(
                            partial_m.group(1)
                        )
                    else:
                        # Pure PIK: entire interest rate is PIK
                        result["pik_rate"] = result.get("interest_rate")

        # Strip PIK notation so _parse_rate sees clean number
        rate_cell_clean = _PIK_STRIP_RE.sub("", rate_cell_clean).strip()

        if quirks.get("rate_cell_includes_reference"):
            # Try to extract reference + spread + total rate
            for pat in _RATE_CELL_PATTERNS:
                m = pat.search(rate_cell_clean)
                if m:
                    groups = m.groups()
                    # Detect group order: if groups[0] is numeric, the
                    # pattern captured (total, ref, spread); otherwise
                    # it is the standard (ref, spread[, total]) order.
                    try:
                        float(groups[0])
                        is_total_first = True
                    except (ValueError, TypeError):
                        is_total_first = False

                    if is_total_first and len(groups) >= 3:
                        # (total, ref, spread)
                        result["interest_rate"] = _parse_rate(groups[0])
                        # Amendment #32: normalize to uppercase for map lookup.
                        ref_code = groups[1].replace(" ", "").upper()
                        result["reference_rate"] = _REFERENCE_MAP.get(
                            ref_code, ref_code
                        )
                        spread_raw = _parse_rate(groups[2])
                        # Amendment #30: basis-point conversion -- check if
                        # the spread group text itself has "%".  A cell may
                        # have "%" in the total-rate portion but not the
                        # spread portion (e.g., "14.00% (Base+ 850)").
                        spread_text = groups[2]
                        if spread_raw and spread_raw >= 100 and "%" not in spread_text:
                            spread_raw /= 100
                        result["basis_spread"] = spread_raw
                    else:
                        # (ref, spread[, total])
                        ref_code = groups[0].replace(" ", "").upper()
                        result["reference_rate"] = _REFERENCE_MAP.get(
                            ref_code, ref_code
                        )
                        spread_raw = _parse_rate(groups[1])
                        spread_text = groups[1]
                        if spread_raw and spread_raw >= 100 and "%" not in spread_text:
                            spread_raw /= 100
                        result["basis_spread"] = spread_raw
                        if len(groups) >= 3:
                            result["interest_rate"] = _parse_rate(
                                groups[2]
                            )
                        else:
                            result["interest_rate"] = result[
                                "basis_spread"
                            ]
                    break
            else:
                # No pattern matched. Amendment #13: strip any residual
                # parenthetical content (e.g., "(2.50% Cash / 13.50%)"
                # left over after PIK stripping) and retry.
                stripped = re.sub(r"\(.*\)", "", rate_cell_clean).strip()
                result["interest_rate"] = _parse_rate(stripped)
        else:
            # Amendment #13: same residual-parenthetical fallback for cells
            # without rate_cell_includes_reference (e.g., "16.00% (...Cash)").
            parsed = _parse_rate(rate_cell_clean)
            if parsed is None and "(" in rate_cell_clean:
                stripped = re.sub(r"\(.*\)", "", rate_cell_clean).strip()
                parsed = _parse_rate(stripped)
            result["interest_rate"] = parsed

    # Reference rate and basis spread from separate columns (when not
    # already extracted from the rate cell above).
    if not result.get("reference_rate"):
        ref_cell = _get_cell("reference_rate")
        if ref_cell:
            ref_clean = _strip_footnotes(ref_cell).strip()
            # Map short codes: "SOFR (Q)" -> "SOFR"
            for code, full in _REFERENCE_MAP.items():
                if ref_clean.upper().startswith(code):
                    result["reference_rate"] = full
                    break
            else:
                result["reference_rate"] = ref_clean

    if result.get("basis_spread") is None:
        spread_cell = _get_cell("basis_spread")
        if spread_cell:
            result["raw_basis_spread"] = spread_cell  # Preserve raw cell text
            spread_clean = _strip_footnotes(spread_cell)
            # Try "S + 500" / "P + 232" format (reference + spread in one cell)
            spread_match = _SPREAD_CELL_PATTERN.search(spread_clean)
            if spread_match:
                # Amendment #32: normalize to uppercase for map lookup.
                ref_code = spread_match.group(1).upper()
                if not result.get("reference_rate"):
                    result["reference_rate"] = _REFERENCE_MAP.get(
                        ref_code, ref_code
                    )
                spread_val = float(spread_match.group(2))
                # Values > 20 are basis points (500 -> 5.00%)
                if spread_val > 20:
                    spread_val /= 100
                result["basis_spread"] = spread_val
            else:
                result["basis_spread"] = _parse_rate(spread_clean)

    # PIK rate from a dedicated column (overrides regex extraction from rate
    # cell).  Some filers (e.g., Main Street 2025 format) have a separate
    # "PIK Rate" column.
    pik_entry = cm.get("pik_rate", {})
    if isinstance(pik_entry, dict) and pik_entry.get("index") is not None:
        pik_cell = _get_cell("pik_rate")
        if pik_cell:
            pik_val = _parse_rate(_strip_footnotes(pik_cell))
            if pik_val is not None:
                result["pik_rate"] = pik_val

    # Maturity date
    mat_cell = _get_cell("maturity_date")
    if mat_cell:
        result["raw_maturity_date"] = mat_cell  # Preserve raw cell text
        result["maturity_date"] = _convert_date(
            mat_cell.strip(), vf.get("date_format", "")
        )

    # Shares
    shares_cell = _get_cell("shares_held")
    if shares_cell:
        result["raw_shares_held"] = shares_cell  # Preserve raw cell text
        result["shares_held"] = _parse_dollar(shares_cell)

    # Pct of net assets
    pct_cell = _get_cell("pct_of_net_assets")
    if pct_cell:
        result["raw_pct_of_net_assets"] = pct_cell  # Preserve raw cell text
        result["pct_of_net_assets"] = _parse_rate(pct_cell)

    # Amendment #37b: preserve raw Cash/PIK rate text for downstream
    # LLM enrichment.  Filers like FIDUS use "12.96%/0.00%" format
    # in a dedicated Cash/PIK column that _parse_rate() cannot handle.
    cash_cell = _get_cell("cash_rate")
    if cash_cell:
        result["cash_rate_raw"] = _strip_footnotes(cash_cell).strip()

    return result


def _convert_date(date_str: str, expected_format: str = "") -> Optional[str]:
    """Convert a date string to YYYY-MM-DD format.

    Handles MM/DD/YYYY, M/D/YY, M-D-YYYY, and YYYY-MM-DD.
    Returns None if unparseable.
    """
    date_str = _strip_footnotes(date_str).strip()
    # Amendment #31: strip commas so "April, 2022" -> "April 2022" before
    # month-name matching.  Commas never appear in numeric date formats.
    date_str = date_str.replace(",", " ")
    date_str = re.sub(r"\s+", " ", date_str).strip()
    if not date_str or date_str == "-":
        return None

    # Already in YYYY-MM-DD?
    if re.match(r"^\d{4}-\d{2}-\d{2}$", date_str):
        return date_str

    for pat, repl in _DATE_FORMATS:
        m = pat.match(date_str)
        if m:
            if repl is not None:
                # Direct regex substitution
                raw = pat.sub(repl, date_str)
                # Zero-pad month and day
                parts = raw.split("-")
                if len(parts) == 3:
                    return f"{parts[0]}-{parts[1].zfill(2)}-{parts[2].zfill(2)}"
                return raw
            else:
                # M/D/YY format -- need to expand year
                month, day, year2 = m.groups()
                year = int(year2)
                year = year + 2000 if year < 50 else year + 1900
                return f"{year}-{int(month):02d}-{int(day):02d}"

    # Handle MM/YYYY partial dates (e.g., "10/2029", "1/2030")
    m = re.match(r"^(\d{1,2})/(\d{4})$", date_str)
    if m:
        month, year = m.groups()
        return f"{year}-{int(month):02d}-01"

    # Amendment #1: month-name dates ("January 2017", "June 2016").
    m = _MONTH_NAME_DATE_RE.match(date_str)
    if m:
        month_name, year = m.groups()
        month_num = _MONTH_NAMES.get(month_name.lower())
        if month_num is not None:
            return f"{year}-{month_num:02d}-01"

    # "June 30 2024", "December 31 2024" (comma stripped above).
    m = _MONTH_DAY_YEAR_RE.match(date_str)
    if m:
        month_name, day, year = m.groups()
        month_num = _MONTH_NAMES.get(month_name.lower())
        if month_num is not None:
            return f"{year}-{month_num:02d}-{int(day):02d}"

    return None


def _detect_template_drift(
    table: ScheduleTable,
    template: dict,
) -> tuple[bool, list[str]]:
    """Check if the table structure has drifted from the template.

    Returns (has_drift, list_of_reasons).
    """
    reasons: list[str] = []

    cm = template.get("column_mapping", {})
    pa = template.get("programmatic_analysis", {})

    header = table.rows[table.header_row_idx]
    grid_positions = pa.get("grid_positions", [])
    expected_logical_cols = pa.get("column_count", 0)

    # Compare logical column counts (non-empty header cells)
    actual_logical_cols = sum(1 for c in header if c.strip())
    if expected_logical_cols > 0 and abs(actual_logical_cols - expected_logical_cols) > 2:
        reasons.append(
            f"Column count: expected ~{expected_logical_cols}, "
            f"got {actual_logical_cols}"
        )

    # Check that key mapped columns still have matching header keywords
    for field_name, entry in cm.items():
        if not isinstance(entry, dict):
            continue
        # Skip fields using direct grid_index (no header to check)
        if entry.get("grid_index") is not None:
            continue
        logical_idx = entry.get("index")
        header_text = entry.get("header_text", "").lower().strip()
        if logical_idx is None or not header_text:
            continue
        # Convert logical to grid
        if grid_positions and logical_idx < len(grid_positions):
            idx = grid_positions[logical_idx]
        else:
            idx = logical_idx
        if idx >= len(header):
            reasons.append(
                f"Field {field_name}: expected '{header_text}' at column "
                f"{logical_idx} out of range "
                f"(table has {actual_logical_cols} logical columns)"
            )
            continue
        actual = header[idx].lower().strip()
        # Amendment #8: empty actual cell contributes a weak mismatch signal
        # (helps tiebreak variants that point grid_positions at empty cells).
        if not actual:
            reasons.append(
                f"Field {field_name}: empty cell at col {idx} "
                f"(expected '{header_text}')"
            )
            continue
        # Amendment #7: strip parenthetical footnote markers like "(r)", "(4)"
        # from both sides before word-level comparison. SEC filings append
        # footnote refs to header words without a separating space, e.g.
        # "Cost(r)" which would otherwise never match "cost".
        expected_clean = _FOOTNOTE_PAREN_RE.sub("", header_text)
        actual_clean = _FOOTNOTE_PAREN_RE.sub("", actual)
        expected_words = set(expected_clean.split())
        actual_words = set(actual_clean.split())
        if expected_words and actual_words:
            overlap = len(expected_words & actual_words)
            if overlap == 0 and actual_clean != expected_clean:
                reasons.append(
                    f"Field {field_name}: header mismatch at col {idx}: "
                    f"expected '{header_text}', got '{actual}'"
                )

    # Dollar unit change -- logged as info but NOT a drift trigger.
    # The template is the authoritative source for dollar unit; auto-detection
    # can be wrong (e.g., missing "in thousands" text).
    template_unit = template.get("value_formats", {}).get("dollar_unit", 1)
    if table.dollar_unit != template_unit:
        reasons.append(
            f"Dollar unit: template={template_unit}, detected={table.dollar_unit}"
        )

    real_mismatches, _, _ = _count_real_mismatches(reasons, header)
    return real_mismatches > 0, reasons


def _count_real_mismatches(
    reasons: list[str], header: list[str]
) -> tuple[int, int, int]:
    """Count (real, shift, skip) drift signals from drift reasons.

    A "real" mismatch means the expected header text is absent from all
    header cells.  A "shift" occurs when the expected header text still
    exists in the actual header (just at a different position).  A
    "skip" is recorded when the template mapped a field to a cell that
    is empty in the actual header -- weaker than a real mismatch but
    used as a tiebreaker when comparing variants (Amendment #8).

    Used as a multi-level tiebreaker in ``_select_best_variant``:
    real -> shift -> skip -> col_delta -> gp_overlap.
    """
    # Strip parenthetical footnote markers from the actual header before
    # substring matching so "cost(r)" still satisfies expected "cost".
    all_actual = " ".join(
        _FOOTNOTE_PAREN_RE.sub("", c.lower()) for c in header if c.strip()
    )
    real = 0
    shift = 0
    skip = 0
    for r in reasons:
        if r.startswith("Dollar unit:"):
            continue  # template is authoritative for dollar unit
        if r.startswith("Column count:"):
            real += 1
            continue
        # Amendment #8: fields pointing at empty cells count as skips.
        if ": empty cell at col" in r:
            skip += 1
            continue
        if "expected '" in r:
            exp_start = r.index("expected '") + len("expected '")
            exp_end = r.index("'", exp_start)
            expected_text = _FOOTNOTE_PAREN_RE.sub(
                "", r[exp_start:exp_end]
            ).strip()
            if expected_text and expected_text in all_actual:
                shift += 1  # Column shift, not real drift
                continue
            real += 1
        else:
            real += 1
    return real, shift, skip


_DATE_MARKER_RE = re.compile(
    r"\b(?:"
    r"as\s+of"
    r"|for\s+the\s+(?:period|year|quarter)\s+ended?"
    r"|schedule\s+of\s+investments"
    r")\s+"
    r"([A-Za-z]+\s+\d{1,2},?\s+\d{4})",
    re.IGNORECASE,
)

_STANDALONE_DATE_RE = re.compile(
    r"^((?:January|February|March|April|May|June|July|August|September"
    r"|October|November|December)\s+\d{1,2},?\s+\d{4})$",
    re.IGNORECASE,
)


def _segment_table_by_period(
    table: ScheduleTable, report_date: str,
) -> ScheduleTable:
    """Amendment #19: segment a multi-period table.

    Scans data rows for bold date markers like "As of June 30, 2018".
    Returns a copy of the table containing only the rows from the
    segment matching *report_date* (or the largest segment if no match).
    If no period markers are found, returns the table unchanged.
    """
    header_idx = table.header_row_idx
    segments: list[tuple[str, int, int]] = []
    current_date = ""
    segment_start = header_idx + 1

    for i, row in enumerate(table.rows[header_idx + 1:], start=header_idx + 1):
        joined = " ".join(c for c in row if c.strip()).strip()
        m = _DATE_MARKER_RE.search(joined)
        if not m:
            stripped = joined.strip()
            m = _STANDALONE_DATE_RE.match(stripped)
        if m:
            if current_date and segment_start < i:
                segments.append((current_date, segment_start, i))
            current_date = m.group(1).strip()
            segment_start = i + 1

    # Close last segment
    if current_date and segment_start < len(table.rows):
        segments.append((current_date, segment_start, len(table.rows)))

    if len(segments) < 2:
        return table  # no segmentation needed

    # Try to match report_date to a segment
    best_seg = max(segments, key=lambda s: s[2] - s[1])  # default: largest
    if report_date:
        rd_clean = report_date.replace("-", "")
        for seg_date, seg_start, seg_end in segments:
            conv = _convert_date(seg_date)
            if conv and conv.replace("-", "") == rd_clean:
                best_seg = (seg_date, seg_start, seg_end)
                break

    _, start, end = best_seg
    new_rows = table.rows[:header_idx + 1] + table.rows[start:end]
    return ScheduleTable(
        rows=new_rows,
        header_row_idx=header_idx,
        score=table.score,
        dollar_unit=table.dollar_unit,
        column_map=table.column_map,
    )


def _resolve_grid(
    table: "ScheduleTable",
    effective_template: dict,
) -> dict:
    """Resolve grid positions for *table* against *effective_template*.

    When the actual header grid positions differ from the template's
    (dense vs sparse layout, extra columns), remap the column_mapping
    indices by matching header text keywords.

    Returns a (possibly new) template dict with resolved column_mapping
    and programmatic_analysis.grid_positions.  If no remapping is needed
    the original *effective_template* is returned unchanged.
    """
    pa = effective_template.get("programmatic_analysis", {})
    tpl_gp = pa.get("grid_positions", [])
    header = table.rows[table.header_row_idx]
    actual_gp = _get_logical_columns(header)

    if not tpl_gp or actual_gp == tpl_gp:
        return effective_template

    cm = effective_template.get("column_mapping", {})

    # Build actual header text at each logical index
    actual_headers = {
        li: header[gi].strip().lower()
        for li, gi in enumerate(actual_gp)
    }

    # For each mapped field, find the best matching actual column
    field_to_actual_logical: dict[str, int] = {}
    for field_name, entry in cm.items():
        if not isinstance(entry, dict):
            continue
        if entry.get("grid_index") is not None:
            continue
        logical_idx = entry.get("index")
        hdr_text = entry.get("header_text", "").lower().strip()
        if logical_idx is None or not hdr_text:
            continue
        hdr_words = set(hdr_text.split())
        best_overlap = 0
        best_li = logical_idx
        for ali, atext in actual_headers.items():
            awords = set(atext.split())
            overlap = len(hdr_words & awords)
            if overlap > best_overlap:
                best_overlap = overlap
                best_li = ali
        field_to_actual_logical[field_name] = best_li

    # Re-index column_mapping to use actual logical indices
    resolved_cm = {}
    for field_name, entry in cm.items():
        if not isinstance(entry, dict):
            resolved_cm[field_name] = entry
            continue
        new_entry = dict(entry)
        if field_name in field_to_actual_logical:
            new_entry["index"] = field_to_actual_logical[field_name]
        resolved_cm[field_name] = new_entry

    resolved = dict(effective_template)
    resolved["column_mapping"] = resolved_cm
    resolved_pa = dict(pa)
    resolved_pa["grid_positions"] = list(actual_gp)
    resolved["programmatic_analysis"] = resolved_pa
    return resolved


def extract_filing_with_template(
    html_content: str,
    filing_meta: dict,
    template: dict,
) -> tuple[list[dict], dict]:
    """Extract holdings from one HTML filing using a learned template.

    Zero LLM calls -- purely programmatic extraction.

    Args:
        html_content: Raw HTML string.
        filing_meta: Dict with cik, accession_number, form_type, etc.
        template: Loaded template dict for this CIK.

    Returns:
        (holdings_rows, stats) where holdings_rows is in bdc_holdings schema.
    """
    stats: dict[str, Any] = {
        "tables_found": 0,
        "data_rows_found": 0,
        "rows_extracted": 0,
        "drift_detected": False,
        "drift_reasons": [],
        "template_version": template.get("schema_version", ""),
        "variant_id": None,
        "elapsed_seconds": 0,
    }

    t0 = time.time()

    # Find tables
    tables = find_schedule_tables(html_content)
    stats["tables_found"] = len(tables)
    if not tables:
        stats["elapsed_seconds"] = time.time() - t0
        return [], stats

    # --- Table + variant selection ---
    # Try all tables returned by find_schedule_tables and pick the
    # (table, variant) pair with the fewest real header mismatches.
    # This handles filers where the schedule is not the first table
    # (e.g., income statement precedes schedule of investments).
    norm = _normalize_template(template)
    # Preserve original template for top-level keys (row_type_column_overrides,
    # filer_quirks.segment_by_period, merge_sibling_tables) that are NOT part
    # of the variant-level structure and would be lost when template is
    # reassigned to the effective (variant-only) dict at line 1448.
    _orig_template = template

    # Amendment #25: pass filing_date so variant selection can narrow
    # candidates to the correct format era before header scoring.
    filing_date = filing_meta.get("filing_date") or None

    best_table = tables[0]
    best_variant = _select_best_variant(tables[0], norm, filing_date)
    best_real = None

    for t in tables:
        # Skip tables with no valid headers (malformed tables)
        col_count = sum(1 for c in t.rows[t.header_row_idx] if c.strip())
        if col_count == 0:
            continue

        variant = _select_best_variant(t, norm, filing_date)
        _, reasons = _detect_template_drift(t, variant)
        real, _, _ = _count_real_mismatches(reasons, t.rows[t.header_row_idx])

        if real == 0:
            data_row_count = len(t.rows) - t.header_row_idx - 1
            if data_row_count < 15:
                continue

        if best_real is None or real < best_real:
            best_real = real
            best_table = t
            best_variant = variant
            if real == 0:
                break  # Perfect match with sufficient data

    table = best_table
    stats["variant_id"] = best_variant.get("format_id")

    # Amendment #19: multi-period segmentation.
    # Always attempt when report_date is available; the function returns the
    # table unchanged if fewer than 2 date-marker segments are found.
    report_date = filing_meta.get("report_date", "")
    if report_date:
        table = _segment_table_by_period(table, report_date)

    # The selected variant becomes the effective template for extraction.
    # Merge variant fields with shared top-level metadata so downstream
    # code sees a flat template dict.
    effective: dict[str, Any] = {}
    for key in ("column_mapping", "value_formats", "row_conventions",
                "filer_quirks", "programmatic_analysis"):
        if key in best_variant:
            effective[key] = best_variant[key]
        elif key in template:
            effective[key] = template[key]

    # Check for template drift against the selected variant
    has_drift, drift_reasons = _detect_template_drift(table, effective)
    stats["drift_detected"] = has_drift
    stats["drift_reasons"] = drift_reasons

    if has_drift:
        logger.info(
            "Template drift detected for CIK %s (variant=%s): %s",
            filing_meta.get("cik", ""),
            stats["variant_id"],
            drift_reasons,
        )

    # Use effective template for the rest of extraction
    template = effective

    # Classify rows
    classified = classify_rows(table)
    data_classified = [r for r in classified if r.kind == "data"]
    stats["data_rows_found"] = len(data_classified)

    if not data_classified:
        stats["elapsed_seconds"] = time.time() - t0
        return [], stats

    # Resolve grid positions: if the actual header's grid positions differ
    # from the template's (e.g., dense vs sparse layout, or extra columns),
    # rebuild the field-to-grid mapping by matching template header texts
    # against actual header cells.
    template_pa = template.get("programmatic_analysis", {})
    expected_col_count = template_pa.get("column_count", 0)
    header = table.rows[table.header_row_idx]

    resolved_template = _resolve_grid(table, template)

    if resolved_template is not template:
        # Amendment #14: re-check drift after grid remapping.  If only
        # shifts remain (real == 0), the remapping resolved the drift;
        # proceed with template extraction instead of fallback.
        if has_drift:
            _, re_reasons = _detect_template_drift(table, resolved_template)
            re_real, _, _ = _count_real_mismatches(re_reasons, header)
            if re_real == 0:
                has_drift = False
                stats["drift_detected"] = False
                stats["drift_reasons"] = re_reasons

    # Extract using template
    all_extracted: list[dict] = []
    current_section = ""

    # Amendment #29: capture header width for mid-table row-width filtering.
    _header_width = len(table.rows[table.header_row_idx])

    # Alternating company/investment row merging: single-text rows classified
    # as section_header may actually be company-name rows.  We stash them
    # and apply the name to the next data row.
    _conv_rc = template.get("row_conventions", {})
    _company_no_fin = (
        _conv_rc.get("continuation_detection") == "company_row_no_financials"
    )
    _pending_company_name: str | None = None
    _pending_company_industry: str | None = None

    _data_row_idx = 0  # 0-based index of data rows for source_row_idx
    for rc in classified:
        if rc.kind == "section_header":
            section_text = rc.section_context or " ".join(
                c for c in rc.cells if c.strip()
            )
            if _company_no_fin:
                # In this mode, single-text rows are company names, not
                # true section headers.  Stash the name for the next data
                # row.  Also capture industry from the row if present.
                _pending_company_name = section_text
                # Try to extract industry from the row cells
                ind_entry = resolved_template.get(
                    "column_mapping", {}
                ).get("industry", {})
                if isinstance(ind_entry, dict) and ind_entry.get("source") == "column":
                    gidx = ind_entry.get("grid_index")
                    if gidx is not None and gidx < len(rc.cells):
                        ind_val = rc.cells[gidx].strip().strip("\u200b")
                        # Look-ahead for colspan offset
                        if not ind_val and gidx + 1 < len(rc.cells):
                            ind_val = rc.cells[gidx + 1].strip().strip("\u200b")
                        if ind_val:
                            _pending_company_industry = ind_val
                        else:
                            _pending_company_industry = None
                    else:
                        _pending_company_industry = None
                else:
                    _pending_company_industry = None
            else:
                current_section = section_text
            continue

        if rc.kind != "data":
            continue

        # Amendment #29: skip rows whose width differs significantly from
        # the header width (likely comparative-period or summary rows
        # injected mid-table).  Use threshold of 3 to avoid filtering
        # narrow continuations already handled by expected_row_width.
        # Skip this filter when expected_row_width is set (template
        # explicitly handles width variation via proactive grid shift).
        _exp_rw = template_pa.get("expected_row_width")
        if not _exp_rw and abs(len(rc.cells) - _header_width) >= 3:
            continue

        # Amendment #27: check for continuation row BEFORE extraction so
        # row_type_column_overrides can use different column positions.
        _row_type_overrides = _orig_template.get("row_type_column_overrides")
        _use_override = False
        if _row_type_overrides and not has_drift:
            _co_entry = resolved_template.get("column_mapping", {}).get("company", {})
            _co_cidx = None
            if isinstance(_co_entry, dict):
                _co_cidx = _co_entry.get("grid_index")
                if _co_cidx is None:
                    _li = _co_entry.get("index")
                    _gp = resolved_template.get("programmatic_analysis", {}).get(
                        "grid_positions"
                    )
                    if _li is not None and _gp and _li < len(_gp):
                        _co_cidx = _gp[_li]
                    elif _li is not None:
                        _co_cidx = _li
            if _co_cidx is not None and _co_cidx < len(rc.cells):
                if not rc.cells[_co_cidx].strip().strip("\u200b"):
                    _use_override = True

        # Apply template column mapping
        if has_drift:
            # Drift detected -- fall back to keyword-based mapping
            fallback_map = _build_column_map(
                table.rows[table.header_row_idx]
            )
            row_data = _apply_fallback_extraction(
                rc.cells, fallback_map, table.dollar_unit,
            )
        elif _use_override:
            # Build override template with different column_mapping
            override_template = dict(resolved_template)
            override_cm = dict(resolved_template.get("column_mapping", {}))
            override_cm.update(_row_type_overrides.get("continuation", {}))
            override_template["column_mapping"] = override_cm
            row_data = _apply_template_column_map(
                rc.cells, override_template,
                detected_dollar_unit=table.dollar_unit,
            )
        else:
            row_data = _apply_template_column_map(
                rc.cells, resolved_template,
                detected_dollar_unit=table.dollar_unit,
            )

        # Row-level grounding: attach source row index
        row_data["source_row_idx"] = _data_row_idx
        _data_row_idx += 1

        # Determine if this is a continuation row
        is_continuation = False
        company_entry = resolved_template.get("column_mapping", {}).get("company", {})
        if isinstance(company_entry, dict):
            # Direct grid_index takes priority over logical index
            direct_cidx = company_entry.get("grid_index")
            if direct_cidx is not None:
                cidx = direct_cidx
            else:
                logical_cidx = company_entry.get("index")
                grid_pos = resolved_template.get("programmatic_analysis", {}).get(
                    "grid_positions"
                )
                # Convert logical to grid index
                if logical_cidx is not None:
                    if grid_pos and logical_cidx < len(grid_pos):
                        cidx = grid_pos[logical_cidx]
                    else:
                        cidx = logical_cidx
                else:
                    cidx = None
            if cidx is not None:
                conv = template.get("row_conventions", {})
                if conv.get("continuation_detection") == "empty_first_cell":
                    if cidx < len(rc.cells):
                        is_continuation = not rc.cells[cidx].strip().strip("\u200b")

        # Amendment #6: missing_key_column continuation.  A row is a
        # continuation when its designated key column (e.g., the date
        # column) is empty.  New positions always have a date; continuation
        # rows never do.  Configured via
        # ``row_conventions.continuation_detection: "missing_key_column"``
        # plus ``row_conventions.continuation_key_column: N`` (logical idx).
        if not is_continuation:
            conv = template.get("row_conventions", {})
            if conv.get("continuation_detection") == "missing_key_column":
                key_logical = conv.get("continuation_key_column")
                if key_logical is not None:
                    grid_pos = resolved_template.get(
                        "programmatic_analysis", {}
                    ).get("grid_positions")
                    if grid_pos and key_logical < len(grid_pos):
                        key_idx = grid_pos[key_logical]
                    else:
                        key_idx = key_logical
                    if key_idx is not None and key_idx < len(rc.cells):
                        is_continuation = (
                            not rc.cells[key_idx].strip().strip("\u200b")
                        )

        # Narrow-row continuation: rows narrower than expected_row_width
        # are continuation rows that dropped leading columns (e.g.,
        # Prospect Capital where continuation rows omit company+industry,
        # shifting all data left).
        if not is_continuation:
            conv = template.get("row_conventions", {})
            if conv.get("narrow_row_continuation"):
                erw = template.get("programmatic_analysis", {}).get(
                    "expected_row_width"
                )
                if erw and len(rc.cells) < erw - 2:
                    is_continuation = True

        row_data["is_continuation"] = is_continuation
        row_data["_section"] = current_section
        if not row_data.get("industry") and current_section:
            ind_src = template.get("row_conventions", {}).get("industry_source")
            if ind_src == "section_header":
                row_data["industry"] = current_section

        # Apply pending company name from company_row_no_financials mode
        if _company_no_fin and _pending_company_name:
            row_data["issuer_name"] = _pending_company_name
            if _pending_company_industry and not row_data.get("industry"):
                row_data["industry"] = _pending_company_industry
            _pending_company_name = None
            _pending_company_industry = None

        all_extracted.append(row_data)

    # Second pass for company_row_no_financials: data rows that have a
    # company name but NO financial data are company-header rows that weren't
    # caught as section headers (e.g., they had 2+ non-empty cells).
    # Merge them with the next data row that has financials.
    if _company_no_fin:
        _financial_keys = (
            "fair_value", "cost", "principal_amount", "interest_rate",
            "maturity_date", "shares_held",
        )
        merged: list[dict] = []
        pending_company: dict | None = None
        for row in all_extracted:
            has_financials = any(row.get(k) is not None for k in _financial_keys)
            has_name = bool(row.get("issuer_name"))
            if has_name and not has_financials:
                # New company header row replaces any pending company.
                pending_company = row
            elif pending_company is not None and has_financials:
                row["issuer_name"] = pending_company.get("issuer_name")
                if pending_company.get("industry") and not row.get("industry"):
                    row["industry"] = pending_company["industry"]
                merged.append(row)
                # Amendment #38: do NOT reset pending_company.
                # Same company may have additional instrument rows
                # (e.g., first lien + second lien + equity).
            else:
                merged.append(row)
        if pending_company is not None:
            merged.append(pending_company)
        all_extracted = merged

    # Amendment #28: merge sibling tables (debt/equity/warrant schedules).
    # When the template declares merge_sibling_tables, extract positions from
    # remaining tables and append (deduped by name+FV).
    if template.get("filer_quirks", {}).get("merge_sibling_tables"):
        _primary_keys = {
            (r.get("issuer_name", "").strip().lower(), r.get("fair_value"))
            for r in all_extracted
            if r.get("issuer_name")
        }
        for sibling_t in tables[1:]:
            if sibling_t is table:
                continue
            sib_variant = _select_best_variant(sibling_t, norm, filing_date)

            # Build sibling-specific effective template (same merge logic
            # as the primary table at lines 1458-1464).
            sib_effective: dict[str, Any] = {}
            for key in ("column_mapping", "value_formats", "row_conventions",
                        "filer_quirks", "programmatic_analysis"):
                if key in sib_variant:
                    sib_effective[key] = sib_variant[key]
                elif key in _orig_template:
                    sib_effective[key] = _orig_template[key]

            _, sib_reasons = _detect_template_drift(sibling_t, sib_effective)
            sib_real, _, _ = _count_real_mismatches(
                sib_reasons, sibling_t.rows[sibling_t.header_row_idx]
            )
            sib_data = len(sibling_t.rows) - sibling_t.header_row_idx - 1
            if sib_real > 0 or sib_data < 5:
                continue

            # Resolve grid for sibling table
            sib_resolved = _resolve_grid(sibling_t, sib_effective)

            sib_classified = classify_rows(sibling_t)
            for sib_rc in sib_classified:
                if sib_rc.kind != "data":
                    continue
                sib_row = _apply_template_column_map(
                    sib_rc.cells, sib_resolved,
                    detected_dollar_unit=sibling_t.dollar_unit,
                )
                sib_key = (
                    (sib_row.get("issuer_name") or "").strip().lower(),
                    sib_row.get("fair_value"),
                )
                if sib_key not in _primary_keys:
                    all_extracted.append(sib_row)
                    _primary_keys.add(sib_key)

    # Post-process (name propagation, final normalization)
    # Dollar unit already applied in _apply_template_column_map, so pass 1
    processed = post_process(all_extracted, dollar_unit=1)

    # Filter out empty rows.  Mark subtotal rows with is_subtotal flag
    # instead of filtering them.  Subtotals have only cost+FV (name
    # propagated from previous row by post_process) but no
    # instrument_description, rate, principal, maturity, or shares.
    # Amendment #16: section-header filter.  When
    # ``instrument_in_company_cell`` or similar quirks cause section-header
    # rows to survive row classification (non-empty company cell), filter
    # them out post-extraction using substring matches from
    # ``row_conventions.section_header_examples``.
    _section_examples: list[str] = template.get("row_conventions", {}).get(
        "section_header_examples", []
    )
    _section_keywords_lc = [
        ex.strip().lower() for ex in _section_examples
        if isinstance(ex, str) and ex.strip()
    ]
    valid_rows = []
    for r in processed:
        if not r.get("issuer_name"):
            continue
        if _section_keywords_lc:
            name_lc = r["issuer_name"].strip().lower()
            if any(kw in name_lc for kw in _section_keywords_lc):
                continue  # section-header row misclassified as data
        # Mark subtotal rows (cost+FV but no detail fields) instead of
        # filtering them.  Downstream consumers use is_subtotal flag.
        if any(
            r.get(k) is not None
            for k in ("fair_value", "cost", "principal_amount")
        ):
            has_detail = (
                r.get("instrument_description")
                or r.get("interest_rate") is not None
                or r.get("maturity_date")
                or r.get("shares_held") is not None
            )
            r["is_subtotal"] = not has_detail
        else:
            r["is_subtotal"] = False
        valid_rows.append(r)

    stats["rows_extracted"] = len(valid_rows)

    # Convert to bdc_holdings schema
    holdings = _to_bdc_holdings_schema(valid_rows, filing_meta)

    stats["elapsed_seconds"] = time.time() - t0
    return holdings, stats


def _apply_fallback_extraction(
    cells: list[str],
    col_map: dict[str, int],
    dollar_unit: int,
) -> dict:
    """Extract fields using keyword-based column map (drift fallback).

    Uses the same extraction logic as the original html_holdings.py.
    """
    result: dict[str, Any] = {
        "issuer_name": None,
        "instrument_description": None,
        "industry": None,
        "interest_rate": None,
        "reference_rate": None,
        "basis_spread": None,
        "maturity_date": None,
        "principal_amount": None,
        "cost": None,
        "fair_value": None,
        "shares_held": None,
        "pct_of_net_assets": None,
        # Raw cell text (always preserved, even when parsing fails)
        "raw_interest_rate": None,
        "raw_basis_spread": None,
        "raw_maturity_date": None,
        "raw_fair_value": None,
        "raw_cost": None,
        "raw_principal_amount": None,
        "raw_shares_held": None,
        "raw_pct_of_net_assets": None,
    }

    _NUMERIC_FALLBACK_FIELDS = {
        "fair_value", "cost", "principal_amount", "interest_rate",
        "shares_held", "pct_of_net_assets",
    }

    def _get(field: str) -> Optional[str]:
        idx = col_map.get(field)
        if idx is None or idx >= len(cells):
            return None
        val = cells[idx].strip()
        # Handle "$" + number split (same as _apply_template_column_map)
        if val == "$" and idx + 1 < len(cells):
            val = cells[idx + 1].strip()
        # Colspan offset: header colspan=2 but data colspan=1, so value is
        # at idx+1.  Try next cell for numeric fields when current is empty.
        elif not val and field in _NUMERIC_FALLBACK_FIELDS and idx + 1 < len(cells):
            val = cells[idx + 1].strip()
        if val and val.startswith("$") and len(val) > 1:
            val = val[1:].strip()
        return val if val else None

    company = _get("company")
    if company:
        result["issuer_name"] = company

    instr = _get("instrument_description")
    if instr:
        result["instrument_description"] = instr

    for field in ["fair_value", "cost", "principal_amount"]:
        raw = _get(field)
        result[f"raw_{field}"] = raw  # Preserve raw cell text always
        val = _parse_dollar(raw)
        if val is not None:
            result[field] = val * dollar_unit
        else:
            result[field] = None

    rate_raw = _get("interest_rate")
    if rate_raw:
        result["raw_interest_rate"] = rate_raw  # Preserve raw cell text
        result["interest_rate"] = _parse_rate(rate_raw)

    mat_raw = _get("maturity_date")
    if mat_raw:
        result["raw_maturity_date"] = mat_raw  # Preserve raw cell text
        result["maturity_date"] = _convert_date(mat_raw)

    shares_raw = _get("shares_held")
    if shares_raw:
        result["raw_shares_held"] = shares_raw  # Preserve raw cell text
        result["shares_held"] = _parse_dollar(shares_raw)

    pct_raw = _get("pct_of_net_assets")
    if pct_raw:
        result["raw_pct_of_net_assets"] = pct_raw  # Preserve raw cell text
        result["pct_of_net_assets"] = _parse_rate(pct_raw)

    return result


def extract_all_html(
    client: Any = None,
    filings_index: Optional[pd.DataFrame] = None,
    cik_filter: Optional[list[str]] = None,
) -> pd.DataFrame:
    """Extract all pre-XBRL filings using learned templates.

    Purely programmatic -- no LLM calls. The client param is only used
    for downloading HTML files if not cached (pass EdgarClient, not OpenAI).

    Args:
        client: EdgarClient for HTML downloads (optional if all cached).
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

    logger.info("HTML template extraction: %d filings to process", len(to_process))

    if to_process.empty:
        if HTML_EXTRACTION_FILE.exists():
            return pd.read_csv(HTML_EXTRACTION_FILE, dtype=str)
        return pd.DataFrame()

    # Load progress for resumability
    progress_file = HTML_EXTRACTION_FILE.parent / "html_template_extract_progress.csv"
    parsed_accessions: set[str] = set()
    if progress_file.exists():
        prog = pd.read_csv(progress_file, dtype=str)
        parsed_accessions = set(
            prog.loc[
                prog["status"].isin(["parsed", "error"]), "accession_number"
            ]
        )
        logger.info(
            "  Resuming: %d accessions already processed",
            len(parsed_accessions),
        )

    to_process = to_process[
        ~to_process["accession_number"].isin(parsed_accessions)
    ]
    logger.info(
        "  %d filings remaining after resume filter", len(to_process),
    )

    if to_process.empty:
        if HTML_EXTRACTION_FILE.exists():
            return pd.read_csv(HTML_EXTRACTION_FILE, dtype=str)
        return pd.DataFrame()

    all_holdings: list[dict] = []
    progress_records: list[dict] = []
    t0 = time.time()

    # Cache loaded templates to avoid re-reading JSON per filing
    template_cache: dict[str, Optional[dict]] = {}

    for i, (_, row) in enumerate(to_process.iterrows(), 1):
        acc = str(row["accession_number"])
        cik = str(row["cik"]).lstrip("0") or "0"

        # Load template (cached)
        if cik not in template_cache:
            template_cache[cik] = load_template(cik)
        template = template_cache[cik]

        if template is None:
            progress_records.append({
                "accession_number": acc,
                "status": "no_template",
                "count": "0",
            })
            continue

        # Load HTML
        acc_nodashes = acc.replace("-", "")
        html_path = BDC_HTML_CACHE_DIR / cik / f"{acc_nodashes}.html"

        if not html_path.exists() or html_path.stat().st_size <= 1024:
            # Try downloading if client provided
            if client is not None:
                primary_doc = str(row.get("primary_document", ""))
                result = download_html_filing(client, cik, acc, primary_doc)
                if result is None:
                    progress_records.append({
                        "accession_number": acc,
                        "status": "download_failed",
                        "count": "0",
                    })
                    continue
                html_path = result
            else:
                progress_records.append({
                    "accession_number": acc,
                    "status": "no_html",
                    "count": "0",
                })
                continue

        try:
            html_content = html_path.read_text(
                encoding="utf-8", errors="replace"
            )
        except Exception as exc:
            logger.debug("Failed to read %s: %s", html_path, exc)
            progress_records.append({
                "accession_number": acc,
                "status": "read_error",
                "count": "0",
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
            holdings, stats = extract_filing_with_template(
                html_content, filing_meta, template,
            )
            all_holdings.extend(holdings)
            progress_records.append({
                "accession_number": acc,
                "status": "parsed",
                "count": str(len(holdings)),
            })
            if i <= 5 or i % 100 == 0:
                logger.info(
                    "  [%d/%d] CIK %s: %d rows (%.2fs, drift=%s)",
                    i, len(to_process), cik, len(holdings),
                    stats["elapsed_seconds"], stats["drift_detected"],
                )
        except Exception as exc:
            logger.error(
                "  [%d/%d] CIK %s %s: extraction error: %s",
                i, len(to_process), cik, acc, exc,
            )
            progress_records.append({
                "accession_number": acc,
                "status": "error",
                "count": "0",
            })

        # Periodic progress save
        if i % PROGRESS_SAVE_INTERVAL == 0 or i == len(to_process):
            _save_extract_progress(
                progress_records, parsed_accessions, progress_file,
            )
            if all_holdings:
                _save_extract_holdings(all_holdings)
            elapsed = time.time() - t0
            rate = i / elapsed if elapsed > 0 else 0
            logger.info(
                "  Progress: %d/%d filings, %d holdings (%.1f/s)",
                i, len(to_process), len(all_holdings), rate,
            )

    # Final save
    _save_extract_progress(progress_records, parsed_accessions, progress_file)
    if all_holdings:
        _save_extract_holdings(all_holdings)

    if HTML_EXTRACTION_FILE.exists():
        return pd.read_csv(HTML_EXTRACTION_FILE, dtype=str)
    return pd.DataFrame(all_holdings) if all_holdings else pd.DataFrame()


def _save_extract_progress(
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


def _save_extract_holdings(holdings: list[dict]) -> None:
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

