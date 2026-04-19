"""Programmatic HTML table detection and parsing for BDC schedule-of-investments.

Provides table detection (``find_schedule_tables``), row classification
(``classify_rows``), column mapping (``_build_column_map``), and parsing
utilities used by ``pipeline.html_template`` for template-based extraction.
"""

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from pipeline.config import (
    BDC_HTML_CACHE_DIR,
)
from pipeline.edgar_client import EdgarClient

logger = logging.getLogger(__name__)

try:
    from bs4 import BeautifulSoup
except ImportError:
    BeautifulSoup = None  # type: ignore[assignment,misc]

# Header keywords for schedule-of-investments table detection
_STRONG_KEYWORDS = [
    "fair value", "amortized cost", "principal amount", "principal",
    "interest rate", "rate", "maturity", "maturity date", "par amount",
    "cost", "spread",
]
_MEDIUM_KEYWORDS = [
    "company", "investment", "portfolio", "industry", "issuer",
    "description", "borrower",
]
_NEGATIVE_KEYWORDS = [
    "total assets", "balance sheet", "income statement",
    "cash flow", "stockholders", "shareholders",
    "earnings per share", "revenue", "investment income",
]

# Subtotal detection patterns (reuse from unified_holdings.py conventions)
_SUBTOTAL_PATTERNS = re.compile(
    r"(?i)^(total\b|sub-?total\b|subtotal\b)",
)

# Dollar-unit detection patterns
_DOLLAR_UNIT_PATTERNS = [
    (re.compile(r"(?i)in\s+millions|in\s+million|\(in\s+millions?\)"), 1_000_000),
    (re.compile(r"(?i)in\s+thousands|in\s+thousand|\(in\s+thousands?\)|\(000s?\)|\(000S?\)"), 1_000),
]

# Footnote reference patterns at end of numeric cells
_FOOTNOTE_RE = re.compile(r"\s*(\(\d+\))+\s*$")
_TRAILING_FOOTNOTE_RE = re.compile(r"\s*\*+\s*$")

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class ScheduleTable:
    """A detected schedule-of-investments table."""
    rows: list[list[str]]
    header_row_idx: int
    score: float
    dollar_unit: int = 1  # multiplier: 1, 1000, or 1_000_000
    column_map: dict[str, int] = field(default_factory=dict)


@dataclass
class RowClassification:
    """Classification of a single table row."""
    row_idx: int
    cells: list[str]
    kind: str  # "header", "section_header", "subtotal", "data", "blank"
    section_context: str = ""  # current industry/category from most recent section_header


# =====================================================================
# 2a. HTML Download & Cache
# =====================================================================

def download_html_filing(
    client: EdgarClient,
    cik: str,
    accession: str,
    primary_doc: str,
) -> Optional[Path]:
    """Download the HTML primary document for a filing.

    Caches to BDC_HTML_CACHE_DIR / cik / {accession_nodashes}.html.
    Returns cached file path or None on failure.
    """
    cik_stripped = cik.lstrip("0") or "0"
    acc_nodashes = accession.replace("-", "")
    cache_dir = BDC_HTML_CACHE_DIR / cik_stripped
    cache_file = cache_dir / f"{acc_nodashes}.html"

    if cache_file.exists() and cache_file.stat().st_size > 1024:
        return cache_file

    url = (
        f"https://www.sec.gov/Archives/edgar/data/"
        f"{cik_stripped}/{acc_nodashes}/{primary_doc}"
    )

    try:
        resp = client.get(url)
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_file.write_bytes(resp.content)
        logger.debug("Downloaded HTML: %s -> %s", url, cache_file)
        return cache_file
    except Exception as exc:
        logger.debug("HTML download failed for %s: %s", url, exc)
        return None


# =====================================================================
# 2b. Table Detection (BeautifulSoup)
# =====================================================================

def _extract_table_rows(table_elem) -> list[list[str]]:
    """Extract rows from a BeautifulSoup <table> as lists of cell text.

    Respects ``colspan`` attributes: when a cell has ``colspan=N``, the
    cell text is placed in the first grid column and N-1 empty strings
    are appended.  This ensures header and data rows have the same number
    of grid-level cells, which is critical for column-index alignment
    when headers use wide colspans (e.g. ``colspan=3``) and dollar-value
    data cells split into ``$`` + number + empty (each ``colspan=1``).
    """
    rows = []
    for tr in table_elem.find_all("tr"):
        cells: list[str] = []
        for td in tr.find_all(["td", "th"]):
            text = td.get_text(separator=" ", strip=True)
            text = re.sub(r"\s+", " ", text).strip()
            # Amendment #33: strip zero-width spaces that inflate column count.
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
    return rows


def _score_table(rows: list[list[str]]) -> tuple[float, int]:
    """Score a table for likelihood of being a schedule of investments.

    Returns (score, best_header_row_idx).
    """
    if len(rows) < 3:
        return -1.0, 0

    best_score = -1.0
    best_header_idx = 0

    # Check first 5 rows as potential headers
    for header_idx in range(min(5, len(rows))):
        header_text = " ".join(rows[header_idx]).lower()
        score = 0.0

        for kw in _STRONG_KEYWORDS:
            if kw in header_text:
                score += 3.0

        for kw in _MEDIUM_KEYWORDS:
            if kw in header_text:
                score += 1.5

        for kw in _NEGATIVE_KEYWORDS:
            if kw in header_text:
                score -= 5.0

        # Bonus for having many columns (schedules typically 5+)
        ncols = len(rows[header_idx])
        if ncols >= 5:
            score += 2.0
        elif ncols >= 3:
            score += 1.0

        # Bonus for having many data rows after the header
        data_rows = len(rows) - header_idx - 1
        if data_rows >= 20:
            score += 3.0
        elif data_rows >= 10:
            score += 2.0
        elif data_rows >= 5:
            score += 1.0

        if score > best_score:
            best_score = score
            best_header_idx = header_idx

    return best_score, best_header_idx


def _detect_dollar_unit(rows: list[list[str]], title_text: str = "") -> int:
    """Detect if values are reported in thousands or millions.

    Checks header rows and table title text for unit indicators.
    """
    # Check title text first
    search_text = title_text
    # Also check first 3 rows
    for row in rows[:3]:
        search_text += " " + " ".join(row)

    for pattern, multiplier in _DOLLAR_UNIT_PATTERNS:
        if pattern.search(search_text):
            return multiplier

    return 1


def _build_column_map(header_cells: list[str]) -> dict[str, int]:
    """Map header cell text to standardized field names.

    Returns dict mapping field name -> column index.
    """
    col_map: dict[str, int] = {}

    # Keywords to field name mapping (order matters -- first match wins)
    field_keywords: list[tuple[str, list[str]]] = [
        ("fair_value", ["fair value", "fair\nvalue"]),
        ("cost", ["amortized cost", "cost"]),
        ("principal_amount", ["principal amount", "principal", "par amount",
                              "par value", "par"]),
        # "interest rate" / "total rate" must match before bare "rate",
        # otherwise "Reference Rate and Spread" steals the slot.
        ("interest_rate", ["interest rate", "total rate", "coupon"]),
        ("maturity_date", ["maturity date", "maturity"]),
        ("pct_of_net_assets", ["% of net", "percent of net", "of net assets"]),
        ("shares_held", ["shares", "number of shares", "quantity"]),
        ("company", ["company", "portfolio company", "issuer", "borrower",
                     "investment", "description"]),
        ("instrument_description", ["type of investment", "investment type"]),
        ("industry", ["industry", "sector"]),
    ]

    # First pass: specific keywords only
    for i, cell in enumerate(header_cells):
        cell_lower = cell.lower().strip()
        if not cell_lower:
            continue
        for field_name, keywords in field_keywords:
            if field_name in col_map:
                continue  # already mapped
            for kw in keywords:
                if kw in cell_lower:
                    col_map[field_name] = i
                    break

    # Second pass: bare "rate" fallback for interest_rate, but only if the
    # cell does NOT contain "reference" or "spread" (those are spread columns).
    if "interest_rate" not in col_map:
        for i, cell in enumerate(header_cells):
            if i in col_map.values():
                continue  # column already claimed
            cell_lower = cell.lower().strip()
            if "rate" in cell_lower and "reference" not in cell_lower and "spread" not in cell_lower:
                col_map["interest_rate"] = i
                break

    return col_map


def _tables_are_continuation(
    table_a_rows: list[list[str]],
    table_b_rows: list[list[str]],
    header_idx_a: int,
    header_idx_b: int,
) -> bool:
    """Check if table B is a continuation of table A (same header pattern)."""
    if not table_a_rows or not table_b_rows:
        return False

    header_a = table_a_rows[header_idx_a] if header_idx_a < len(table_a_rows) else []
    header_b = table_b_rows[header_idx_b] if header_idx_b < len(table_b_rows) else []

    if not header_a or not header_b:
        return False

    # Compare column count and header text similarity
    if abs(len(header_a) - len(header_b)) > 2:
        return False

    # Check overlap in header keywords
    a_words = {w.lower() for w in " ".join(header_a).split() if len(w) > 2}
    b_words = {w.lower() for w in " ".join(header_b).split() if len(w) > 2}

    if not a_words or not b_words:
        return False

    overlap = len(a_words & b_words) / max(len(a_words), len(b_words))
    return overlap > 0.5


def find_schedule_tables(html: str) -> list[ScheduleTable]:
    """Find schedule-of-investments tables in HTML filing.

    Returns tables scoring above threshold, ordered by score.
    Merges continuation tables that have matching headers.
    """
    if BeautifulSoup is None:
        raise ImportError(
            "beautifulsoup4 is required for HTML extraction. "
            "Install with: pip install beautifulsoup4 lxml"
        )

    # Financial-highlights phrases used both in headerless-continuation
    # guard (below) and in Amendment #20 post-filter.
    _FIN_HIGHLIGHTS_PHRASES = {
        "net investment", "net realized", "net unrealized", "total return",
        "ratio to", "per share", "from operations", "nav per share",
        "end of period", "beginning of period", "distributions declared",
    }

    soup = BeautifulSoup(html, "lxml")

    # Collect title context: text around schedule-of-investments references.
    # We do a quick scan of the first 500 p/div/span elements, but also fall
    # back to a regex scan of the raw HTML for dollar-unit patterns since
    # 10-K filings can have thousands of preamble elements before the
    # schedule of investments.
    title_text = ""
    page_text_snippets: list[str] = []
    dollar_unit_context = ""
    for text_elem in soup.find_all(["p", "div", "span"], limit=500):
        t = text_elem.get_text(strip=True)
        page_text_snippets.append(t)
        if not title_text and ("schedule of investments" in t.lower()
                               or "consolidated schedule" in t.lower()):
            title_text = t
        if not dollar_unit_context:
            t_lower = t.lower()
            for pat, _ in _DOLLAR_UNIT_PATTERNS:
                if pat.search(t_lower):
                    dollar_unit_context = t
                    break

    # Fallback: search for dollar unit near "schedule of investments" headings
    # in the raw HTML.  A naive regex on the full HTML would match "millions"
    # in financial statement notes (every filing mentions "millions"), giving
    # false positives for filers who report schedules in actual dollars.
    # Instead, find "schedule of investments" and search only the +-2000 chars
    # around that heading for dollar-unit patterns.
    if not dollar_unit_context:
        html_lower = html.lower()
        for heading_kw in ["schedule of investments", "consolidated schedule"]:
            pos = html_lower.find(heading_kw)
            if pos >= 0:
                window_start = max(0, pos - 500)
                window_end = min(len(html), pos + 2000)
                window = html_lower[window_start:window_end]
                for pat, _ in _DOLLAR_UNIT_PATTERNS:
                    m = pat.search(window)
                    if m:
                        dollar_unit_context = html[
                            window_start + m.start():window_start + m.end()
                        ]
                        break
                if dollar_unit_context:
                    break

    # Collect text for dollar-unit detection (include dollar_unit_context)
    page_context = " ".join(page_text_snippets[:50])
    if dollar_unit_context:
        page_context = dollar_unit_context + " " + page_context

    candidates: list[tuple[float, int, list[list[str]]]] = []
    for table_elem in soup.find_all("table"):
        rows = _extract_table_rows(table_elem)
        if not rows:
            continue
        score, header_idx = _score_table(rows)
        if score > 3.0:
            candidates.append((score, header_idx, rows))

    if not candidates:
        return []

    # Sort by score descending
    candidates.sort(key=lambda x: -x[0])

    # Group tables by header similarity, then merge within each group.
    # This handles filings where one schedule spans many <table> elements,
    # each repeating the same header row (e.g. Ares Capital 10-K has 170+
    # continuation tables for the detailed schedule of investments).
    groups: list[list[int]] = []  # group[i] = list of candidate indices
    assigned: set[int] = set()

    for i in range(len(candidates)):
        if i in assigned:
            continue
        group = [i]
        assigned.add(i)
        _, hi, ri = candidates[i]
        for j in range(i + 1, len(candidates)):
            if j in assigned:
                continue
            _, hj, rj = candidates[j]
            if _tables_are_continuation(ri, rj, hi, hj):
                group.append(j)
                assigned.add(j)
        groups.append(group)

    # Amendment #37: merge headerless continuation tables into the best-
    # matching headed group.  Some filers (e.g. FIDUS 2021+) do not repeat
    # column headers on continuation pages.  These tables score > 3.0
    # (financial content) but fail _tables_are_continuation (no header
    # overlap).  Merge each into the headed group whose data row width
    # best matches.
    _all_keywords = set(_STRONG_KEYWORDS + _MEDIUM_KEYWORDS)
    headerless_members: set[int] = set()
    # Map candidate_idx -> group_idx that it should merge into.
    _headerless_target: dict[int, int] = {}
    if len(groups) > 1:
        # Precompute median data row width for each headed group.
        _group_widths: list[tuple[int, int]] = []  # (group_idx, median_w)
        for gi, group in enumerate(groups):
            leader_idx = group[0]
            _, _hidx, _rows = candidates[leader_idx]
            _header = _rows[_hidx] if _hidx < len(_rows) else []
            _header_text = " ".join(_header).lower()
            if not any(kw in _header_text for kw in _all_keywords):
                continue  # not a schedule table
            _dw = [
                len(r) for r in _rows[_hidx + 1:]
                if any(c.strip() for c in r)
            ]
            _med = sorted(_dw)[len(_dw) // 2] if _dw else 0
            _group_widths.append((gi, _med))

        if _group_widths:
            # Precompute header column count for each headed group
            # (used for non-empty cell density check).
            _group_hdr_cols: dict[int, int] = {}
            for gi, _ in _group_widths:
                li = groups[gi][0]
                _, _hi, _ri = candidates[li]
                _hdr = _ri[_hi] if _hi < len(_ri) else []
                _group_hdr_cols[gi] = sum(
                    1 for c in _hdr if c.strip()
                )

            # Find headerless singletons and merge into best group.
            singletons = [
                (gi, groups[gi][0])
                for gi in range(len(groups))
                if len(groups[gi]) == 1
            ]
            for s_gi, cidx in singletons:
                _, s_hidx, s_rows = candidates[cidx]
                s_header = s_rows[s_hidx] if s_hidx < len(s_rows) else []
                s_header_text = " ".join(s_header).lower()
                if any(kw in s_header_text for kw in _all_keywords):
                    continue  # has real schedule headers
                s_dw = [
                    len(r) for r in s_rows if any(c.strip() for c in r)
                ]
                if not s_dw:
                    continue
                s_med = sorted(s_dw)[len(s_dw) // 2]
                # Non-empty cell count per data row (density check).
                s_ne = [
                    sum(1 for c in r if c.strip())
                    for r in s_rows if any(c.strip() for c in r)
                ]
                s_med_ne = sorted(s_ne)[len(s_ne) // 2] if s_ne else 0
                # Find closest headed group by width.
                best_gi, best_diff = -1, 999
                for t_gi, t_med in _group_widths:
                    diff = abs(s_med - t_med)
                    if diff < best_diff:
                        best_diff = diff
                        best_gi = t_gi
                if best_gi >= 0 and best_diff <= 5:
                    # Density guard: headerless table must have at least
                    # half as many non-empty cells as the target group's
                    # header column count.  Rejects sparse tables (e.g.,
                    # 2-col "Fair Value/Cost" tables with 18-cell rows).
                    min_ne = max(4, _group_hdr_cols.get(best_gi, 8) // 2)
                    if s_med_ne < min_ne:
                        continue
                    # Financial highlights guard: reject tables whose
                    # first column contains per-share/NAV/return data.
                    _fin_kw = _FIN_HIGHLIGHTS_PHRASES | {
                        "shares outstanding", "weighted average",
                        "net assets at", "average net", "average debt",
                        "total assets", "net increase", "net decrease",
                    }
                    _fin_match = 0
                    _fin_total = 0
                    for _fr in s_rows:
                        _fc = _fr[0].strip().lower() if _fr else ""
                        if not _fc:
                            continue
                        _fin_total += 1
                        if any(p in _fc for p in _fin_kw):
                            _fin_match += 1
                    if _fin_total > 0 and _fin_match / _fin_total > 0.2:
                        continue
                    headerless_members.add(cidx)
                    _headerless_target[cidx] = best_gi
                    groups[best_gi].append(cidx)

            if headerless_members:
                groups = [
                    g for g in groups
                    if not (len(g) == 1 and g[0] in headerless_members)
                ]

    # Build merged ScheduleTable for each group
    result_tables: list[ScheduleTable] = []
    for group in groups:
        leader_idx = group[0]
        leader_score, leader_hidx, leader_rows = candidates[leader_idx]
        merged_rows = list(leader_rows)

        for member_idx in group[1:]:
            _, member_hidx, member_rows = candidates[member_idx]
            if member_idx in headerless_members:
                # Headerless continuation: append ALL rows (no header to skip)
                merged_rows.extend(member_rows)
            else:
                # Normal continuation: skip header row
                merged_rows.extend(member_rows[member_hidx + 1:])

        dollar_unit = _detect_dollar_unit(merged_rows, page_context)
        col_map = _build_column_map(merged_rows[leader_hidx])
        total_data = len(merged_rows) - leader_hidx - 1
        result_tables.append(ScheduleTable(
            rows=merged_rows,
            header_row_idx=leader_hidx,
            score=leader_score,
            dollar_unit=dollar_unit,
            column_map=col_map,
        ))

    # Amendment #20: reject financial-highlights tables.
    def _is_financial_highlights(tbl: ScheduleTable) -> bool:
        match_count = 0
        total = 0
        for row in tbl.rows[tbl.header_row_idx + 1:]:
            first_col = row[0].strip().lower() if row else ""
            if not first_col:
                continue
            total += 1
            if any(p in first_col for p in _FIN_HIGHLIGHTS_PHRASES):
                match_count += 1
        return total > 0 and match_count / total > 0.3

    # Amendment #22: reject tiny tables with no large dollar values.
    def _has_significant_content(tbl: ScheduleTable) -> bool:
        data_rows = len(tbl.rows) - tbl.header_row_idx - 1
        if data_rows >= 5:
            return True
        # Check for any dollar value > $100K
        for row in tbl.rows[tbl.header_row_idx + 1:]:
            for cell in row:
                val = _parse_dollar(cell)
                if val is not None and abs(val) > 100_000:
                    return True
        return False

    result_tables = [
        t for t in result_tables
        if not _is_financial_highlights(t) and _has_significant_content(t)
    ]

    # Sort by score first (prefer highest-scoring table group), then by data rows
    # as tiebreaker (prefer larger continuation table groups when scores are equal)
    result_tables.sort(
        key=lambda t: (t.score, len(t.rows) - t.header_row_idx - 1), reverse=True,
    )

    return result_tables


# =====================================================================
# 2c. Row Classification (Programmatic)
# =====================================================================

def classify_rows(table: ScheduleTable) -> list[RowClassification]:
    """Classify each row in the table as header/section_header/subtotal/data/blank."""
    results: list[RowClassification] = []
    header_cells = table.rows[table.header_row_idx]
    ncols = len(header_cells)
    current_section = ""

    for i, row in enumerate(table.rows):
        # Skip the header row itself
        if i <= table.header_row_idx:
            results.append(RowClassification(
                row_idx=i, cells=row, kind="header",
            ))
            continue

        # Check for blank/spacer rows
        non_empty = [c for c in row if c.strip()]
        if not non_empty:
            results.append(RowClassification(
                row_idx=i, cells=row, kind="blank",
            ))
            continue

        # Check for subtotal rows
        joined = " ".join(non_empty).strip()
        if _SUBTOTAL_PATTERNS.match(joined):
            results.append(RowClassification(
                row_idx=i, cells=row, kind="subtotal",
                section_context=current_section,
            ))
            continue

        # Check for section headers (single-text rows spanning most columns)
        # Section headers typically have 1-2 non-empty cells and no dollar amounts
        has_dollar = any(_looks_numeric(c) for c in non_empty)
        if len(non_empty) <= 2 and not has_dollar and len(row) < ncols:
            current_section = joined
            results.append(RowClassification(
                row_idx=i, cells=row, kind="section_header",
                section_context=current_section,
            ))
            continue

        # Also detect section headers that have many empty cells
        if (len(non_empty) == 1 and not has_dollar
                and len(joined) > 3 and len(joined) < 100):
            current_section = joined
            results.append(RowClassification(
                row_idx=i, cells=row, kind="section_header",
                section_context=current_section,
            ))
            continue

        # Default: data row
        results.append(RowClassification(
            row_idx=i, cells=row, kind="data",
            section_context=current_section,
        ))

    return results


def _looks_numeric(text: str) -> bool:
    """Check if text looks like a numeric/dollar value."""
    # Strip common formatting
    cleaned = text.replace(",", "").replace("$", "").replace("(", "").replace(")", "")
    cleaned = _FOOTNOTE_RE.sub("", cleaned)
    cleaned = _TRAILING_FOOTNOTE_RE.sub("", cleaned)
    cleaned = cleaned.strip()
    if not cleaned or cleaned == "-":
        return False
    try:
        float(cleaned)
        return True
    except ValueError:
        return False




# =====================================================================
# 2e. Post-Processing (Programmatic)
# =====================================================================

def _strip_footnotes(value: str) -> str:
    """Remove trailing footnote references from a string."""
    value = _FOOTNOTE_RE.sub("", value)
    value = _TRAILING_FOOTNOTE_RE.sub("", value)
    return value.strip()


# Amendment #18: foreign currency parenthetical: "(CAD 76,091)", "(EUR 4,055)".
# Matches exactly 3 uppercase letters, whitespace, then digits with optional
# commas/decimals/trailing space, inside parens.  Narrow enough to avoid
# stripping the negative convention `(1,234)` which has only digits.
_FOREIGN_CURRENCY_PAREN_RE = re.compile(
    r"\s*\(\s*[A-Z]{3}\s+[\d.,\s]+\)"
)

# Amendment #5: take only the first contiguous digit group from a cell.
# Cells like "1,791,278 150,000 1,791,278 150,000" (Rand Capital multi-
# instrument rows) have multiple space-separated numbers.  `float()` fails
# on the embedded space; we keep only the first number.
_FIRST_NUMERIC_RE = re.compile(r"^[-\s]*([\d.,]+)")


def _parse_dollar(value: Any) -> Optional[float]:
    """Parse a dollar value from LLM output, handling parenthesized negatives."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip()
    if not s or s == "-" or s.lower() == "null" or s.lower() == "none":
        return None
    # Amendment #18: strip foreign currency parenthetical BEFORE the
    # negative-parens check so we don't lose the real USD value.
    s = _FOREIGN_CURRENCY_PAREN_RE.sub("", s).strip()
    if not s:
        return None
    # Handle parenthesized negatives: (1,234) -> -1234
    negative = False
    if s.startswith("(") and s.endswith(")"):
        s = s[1:-1]
        negative = True
    s = s.replace(",", "").replace("$", "").strip()
    s = _strip_footnotes(s)
    # Amendment #5: if the cell has multiple space-separated numbers, take
    # only the first contiguous digit group.  "1791278 150000" -> "1791278".
    # Only triggers when a literal float() parse would fail (preserves the
    # fast-path for well-formed single numbers).
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


# Amendment #4: trailing Cash/PIK suffixes that must be stripped before float().
# BCP Investment Corp and others use cells like "6.5% Cash", "10.0% PIK".
_RATE_SUFFIX_STRIP_RE = re.compile(
    r"\s+(?:cash|pik)\s*$", re.IGNORECASE,
)


def _parse_rate(value: Any) -> Optional[float]:
    """Parse a rate value, ensuring it's in percentage form."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        v = float(value)
        # If LLM returns 0.0525, convert to 5.25
        if 0 < v < 0.5:
            return v * 100
        return v
    s = str(value).strip()
    # If the string contains "%", the value is already in percentage form
    # (e.g. "0.25 %") -- do NOT apply the decimal-to-percentage heuristic.
    has_pct = "%" in s
    s = s.rstrip("%").strip()
    # Amendment #4: strip trailing " Cash" / " PIK" suffixes (case-insensitive).
    # Repeated strip handles cells like "6.5 PIK" where "%" was already removed.
    prev = None
    while prev != s:
        prev = s
        s = _RATE_SUFFIX_STRIP_RE.sub("", s).strip()
        s = s.rstrip("%").strip()
    if not s or s == "-" or s.lower() == "null":
        return None
    try:
        v = float(s)
        if not has_pct and 0 < v < 0.5:
            return v * 100
        return v
    except ValueError:
        return None


def post_process(
    rows: list[dict],
    dollar_unit: int = 1,
) -> list[dict]:
    """Post-process LLM-extracted rows.

    - Name propagation for continuation rows
    - Dollar unit normalization
    - Rate normalization
    - Footnote stripping
    """
    dollar_fields = ["principal_amount", "cost", "fair_value"]
    rate_fields = ["interest_rate", "basis_spread", "pct_of_net_assets"]
    last_issuer = ""
    # Amendment #23: propagate industry alongside issuer_name.
    last_industry = ""

    processed: list[dict] = []
    for row in rows:
        out = dict(row)

        # Name propagation for continuation rows
        if out.get("is_continuation", False) and last_issuer:
            out["issuer_name"] = last_issuer
            # Amendment #23: industry propagation to continuation rows.
            if not out.get("industry") and last_industry:
                out["industry"] = last_industry
        elif out.get("issuer_name"):
            last_issuer = out["issuer_name"]
            if out.get("industry"):
                last_industry = out["industry"]

        # Dollar unit normalization
        for f in dollar_fields:
            val = _parse_dollar(out.get(f))
            if val is not None:
                out[f] = val * dollar_unit
            else:
                out[f] = None

        # Rate normalization
        for f in rate_fields:
            out[f] = _parse_rate(out.get(f))

        # Shares -- just parse as number
        sh = out.get("shares_held")
        if sh is not None:
            out["shares_held"] = _parse_dollar(sh)  # reuse same parser

        # Maturity date -- keep as string, validate format
        mat = out.get("maturity_date")
        if mat and isinstance(mat, str):
            mat = mat.strip()
            # Accept YYYY-MM-DD format
            if not re.match(r"\d{4}-\d{2}-\d{2}$", mat):
                out["maturity_date"] = None

        processed.append(out)

    return processed


def reconcile_subtotals(
    data_rows: list[dict],
    subtotal_rows: list[dict],
) -> list[dict]:
    """Compare sum of extracted fair values to subtotal row values.

    Returns list of dicts with reconciliation info per section.
    """
    results: list[dict] = []
    current_section = ""
    section_fv_sum = 0.0
    section_count = 0

    for row in data_rows:
        section = row.get("_section", "")
        if section != current_section and section:
            # New section -- emit previous if we have data
            if current_section and section_count > 0:
                results.append({
                    "section": current_section,
                    "sum_fair_value": section_fv_sum,
                    "row_count": section_count,
                })
            current_section = section
            section_fv_sum = 0.0
            section_count = 0

        fv = row.get("fair_value")
        if fv is not None and isinstance(fv, (int, float)):
            section_fv_sum += fv
            section_count += 1

    # Emit last section
    if current_section and section_count > 0:
        results.append({
            "section": current_section,
            "sum_fair_value": section_fv_sum,
            "row_count": section_count,
        })

    # Match against subtotals
    for recon in results:
        section = recon["section"]
        matching_sub = [
            s for s in subtotal_rows
            if s.get("_section", "") == section and s.get("fair_value") is not None
        ]
        if matching_sub:
            sub_fv = matching_sub[0]["fair_value"]
            recon["subtotal_fair_value"] = sub_fv
            if sub_fv and sub_fv != 0:
                recon["pct_diff"] = abs(recon["sum_fair_value"] - sub_fv) / abs(sub_fv)
            else:
                recon["pct_diff"] = None
        else:
            recon["subtotal_fair_value"] = None
            recon["pct_diff"] = None

    return results


# =====================================================================
# 2f. Convert to bdc_holdings.csv schema
# =====================================================================

def _to_bdc_holdings_schema(
    rows: list[dict],
    filing_meta: dict[str, str],
) -> list[dict]:
    """Convert extracted rows to bdc_holdings.csv schema."""
    output: list[dict] = []
    report_date = filing_meta.get("report_date", "")

    for row in rows:
        record = {
            "cik": filing_meta.get("cik", ""),
            "entity_name": filing_meta.get("entity_name", ""),
            "accession_number": filing_meta.get("accession_number", ""),
            "form_type": filing_meta.get("form_type", ""),
            "filing_date": filing_meta.get("filing_date", ""),
            "report_date": report_date,
            "period": report_date,  # HTML filings only have current period
            "investment_identifier": row.get("issuer_name", ""),
            "fair_value": row.get("fair_value"),
            "cost": row.get("cost"),
            "principal_amount": row.get("principal_amount"),
            "interest_rate": row.get("interest_rate"),
            "basis_spread": row.get("basis_spread"),
            "reference_rate_type": row.get("reference_rate"),
            "maturity_date": row.get("maturity_date"),
            "shares_held": row.get("shares_held"),
            "pct_of_net_assets": row.get("pct_of_net_assets"),
            "unrealized_gain_loss": None,
            "pik_rate": row.get("pik_rate"),
            "industry": row.get("industry", ""),
            "investment_type": row.get("instrument_description", ""),
            "affiliation": "",
            "dimensions_raw": row.get("cash_rate_raw") or "",
            # Raw cell text (preserved for downstream disambiguation)
            "raw_interest_rate": row.get("raw_interest_rate") or "",
            "raw_fair_value": row.get("raw_fair_value") or "",
            "raw_cost": row.get("raw_cost") or "",
            "raw_principal_amount": row.get("raw_principal_amount") or "",
            "raw_maturity_date": row.get("raw_maturity_date") or "",
            "raw_shares_held": row.get("raw_shares_held") or "",
            "raw_basis_spread": row.get("raw_basis_spread") or "",
            "raw_pct_of_net_assets": row.get("raw_pct_of_net_assets") or "",
            "is_subtotal": row.get("is_subtotal", False),
            "source_row_idx": row.get("source_row_idx"),
        }
        output.append(record)

    return output


