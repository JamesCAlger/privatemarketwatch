"""Static HTML-section bridge support for BDC XBRL wrappers.

Bridge files are audited, cached-HTML-derived mappings from an XBRL typed
identifier to the source table section that supplied the missing instrument
context.  They are intentionally exact-keyed by CIK, accession, report date,
and raw identifier so they cannot become a broad HTML fallback.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import re
from datetime import date
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

from pipeline.config import BDC_HTML_CACHE_DIR, OVERRIDES_DIR
from pipeline.html_extract import _extract_tables

logger = logging.getLogger(__name__)

BRIDGE_SCHEMA_VERSION = "bdc-xbrl-html-section-bridge.v1"
BRIDGE_DEFINITIONS_DIR = OVERRIDES_DIR / "bdc_xbrl_html_section_bridges"

BRIDGE_TABLE_COLUMNS = [
    "cik",
    "accession_number",
    "report_date",
    "raw_id_lower",
    "issuer_name",
    "instrument_description",
    "family",
    "disposition",
    "rule_id",
    "html_sha256",
    "table_index",
    "section_row_index",
    "row_index",
    "cell_indices",
    "section_label",
    # HTML-sourced field values (descriptors XBRL leaves untagged per position)
    "maturity_date",
    "acquisition_date",
    "reference_rate_type",
    "permit_overwrite",
]

# Date column extraction.  Schedule rows carry an acquisition date and a
# maturity date (e.g. "7/25/2025  5/25/2029"); maturity is the later date.
_FULL_DATE_RE = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{2,4})\b")
_MONTH_DATE_RE = re.compile(r"\b(\d{1,2})/(\d{4})\b")
_REF_RATE_RE = re.compile(r"(?i)\b(SOFR|LIBOR|EURIBOR|PRIME|SONIA|CORRA)\b")


def _last_day(year: int, month: int) -> date:
    if month == 12:
        return date(year, 12, 31)
    return date.fromordinal(date(year, month + 1, 1).toordinal() - 1)


def _extract_row_dates(row: list[str]) -> list[date]:
    """All plausible dates in a row, sorted ascending (1950 <= year < 2099)."""
    out: list[date] = []
    for cell in row:
        text = _norm_text(cell)
        if not text:
            continue
        full = list(_FULL_DATE_RE.finditer(text))
        if full:
            for m in full:
                mm, dd, yy = int(m.group(1)), int(m.group(2)), int(m.group(3))
                if yy < 100:
                    yy += 2000
                try:
                    d = date(yy, mm, dd)
                except ValueError:
                    continue
                if 1950 <= d.year < 2099:
                    out.append(d)
        else:
            for m in _MONTH_DATE_RE.finditer(text):
                mm, yy = int(m.group(1)), int(m.group(2))
                if not (1 <= mm <= 12):
                    continue
                try:
                    d = _last_day(yy, mm)
                except ValueError:
                    continue
                if 1950 <= d.year < 2099:
                    out.append(d)
    return sorted(set(out))


def _extract_reference_rate(row: list[str]) -> str:
    joined = " ".join(_norm_text(cell) for cell in row)
    m = _REF_RATE_RE.search(joined)
    if m:
        return m.group(1).upper()
    if re.search(r"(?i)\bSF\s*\+", joined) or re.search(r"\bS\s*\+\s*\d", joined):
        return "SOFR"
    if re.search(r"\bL\s*\+\s*\d", joined):
        return "LIBOR"
    if re.search(r"\bE\s*\+\s*\d", joined):
        return "EURIBOR"
    if re.search(r"\bP\s*\+\s*\d", joined):
        return "PRIME"
    return ""


# Benchmark abbreviations as they appear ALONE in a dedicated "Index" / "Reference
# Rate" column (where the spread lives in a separate column, so there is no
# "+ x.xx%" for _extract_reference_rate to latch onto).  Only applied on the
# header-confirmed benchmark-column path -- a bare "S" in a free row scan is
# ambiguous, but in a confirmed Index column it is unambiguous.
_BENCHMARK_CODE = {
    "SF": "SOFR", "S": "SOFR", "SO": "SOFR", "SOFR": "SOFR", "TSF": "SOFR",
    "TSOFR": "SOFR", "TERMSOFR": "SOFR",
    "L": "LIBOR", "LIB": "LIBOR", "LIBOR": "LIBOR", "LIB1M": "LIBOR", "LIB3M": "LIBOR",
    "E": "EURIBOR", "EUR": "EURIBOR", "EURIBOR": "EURIBOR",
    "P": "PRIME", "PR": "PRIME", "PRIME": "PRIME",
    "SONIA": "SONIA", "CORRA": "CORRA",
}


def _benchmark_from_code(cell: str) -> str:
    """Map a bare benchmark code (letters only) from a confirmed Index column."""
    t = re.sub(r"[^A-Za-z]", "", _FOOTNOTE_STRIP_RE.sub("", cell or "")).upper()
    return _BENCHMARK_CODE.get(t, "")

_VALUE_RE = re.compile(r"[$(]?\d[\d,]*(?:\.\d+)?%?\)?")
_TOKEN_RE = re.compile(r"[a-z0-9]+")
_GENERIC_SOURCE_RE = re.compile(
    r"(?i)\b(?:investments?|non[-\s]?controlled|non[-\s]?affiliated|"
    r"controlled|affiliated|debt|equity|industry|investment|reference|rate|"
    r"spread|interest|maturity|date|shares?|cost|fair|value|percentage|"
    r"net|assets?)\b"
)
_SUBTOTAL_RE = re.compile(r"(?i)^(?:total|subtotal|sub-total|net\b)|\btotal\b")

_FOOTNOTE_STRIP_RE = re.compile(r"\s*(?:\(\d+\))+")
_INSTRUMENT_SUFFIX_RE = re.compile(
    r"\s*[-\u2013\u2014]\s+"
    r"("
    r"(?:A\d?\s+)?Ordinary\s+Shares?"
    r"|(?:Senior\s+)?Preferred\s+(?:Stock|Shares?|Equity)"
    r"|Common\s+(?:Stock|Shares?)"
    r"|Class\s+[A-Z](?:[-\s]?\d+)?\s+(?:Common\s+)?(?:Units?|Subordinated\s+Notes?)"
    r"|(?:Preferred|Common)\s+Units?"
    r"|Class\s+[A-Z](?:R\d?|1)?"
    r"|LLC\s+Interest"
    r"|L\.P\.\s+Interest"
    r"|LP\s+Interest"
    r"|Membership\s+Interests?"
    r"|Equity\s+Interest"
    r"|Subordinated\s+Notes?"
    r"|Warrants?"
    r")"
    r"(?:\s+\d+)?"
    r"\s*$",
    re.IGNORECASE,
)


def _parse_inline_instrument_type(cell_text: str) -> str | None:
    """Extract instrument type suffix from a company name cell.

    Handles patterns like ``"CG Parent (4)(22) - Preferred Stock"`` by
    stripping footnote markers and matching a dash-separated suffix.
    Returns the matched instrument type or ``None``.
    """
    text = _FOOTNOTE_STRIP_RE.sub("", cell_text).strip()
    m = _INSTRUMENT_SUFFIX_RE.search(text)
    if m:
        return m.group(1).strip()
    return None

_SECTION_PATTERNS: tuple[tuple[re.Pattern[str], str, str], ...] = (
    (re.compile(r"(?i)^first\s+lien\s+debt$"), "debt", "First Lien Debt"),
    (re.compile(r"(?i)^second\s+lien\s+debt$"), "debt", "Second Lien Debt"),
    (re.compile(r"(?i)^unsecured\s+debt$"), "debt", "Unsecured Debt"),
    (re.compile(r"(?i)^senior\s+secured\s+(?:loans?|debt)$"), "debt", "Senior Secured Debt"),
    (re.compile(r"(?i)^subordinated\s+(?:debt|notes?)$"), "debt", "Subordinated Debt"),
    (re.compile(r"(?i)^other\s+secured\s+debt$"), "debt", "Other Secured Debt"),
    (re.compile(r"(?i)^structured\s+finance(?:\s+investments?)?$"), "debt", "Structured Finance"),
    (re.compile(r"(?i)^common\s+equity$"), "equity", "Common Equity"),
    (re.compile(r"(?i)^preferred\s+equity$"), "equity", "Preferred Equity"),
    (re.compile(r"(?i)^equity\s+investments?$"), "equity", "Equity Investments"),
    (re.compile(r"(?i)^common\s+stock$"), "equity", "Common Stock"),
    (re.compile(r"(?i)^preferred\s+stock$"), "equity", "Preferred Stock"),
    (re.compile(r"(?i)^llc\s+interest$"), "equity", "LLC Interest"),
    (re.compile(r"(?i)^investments?\s+in\s+joint\s+ventures?$"), "equity", "Joint Ventures"),
    (re.compile(r"(?i)^warrants?$"), "warrant", "Warrant"),
)


def normalize_cik(value: Any) -> str:
    digits = re.sub(r"[^0-9]", "", str(value or ""))
    return digits.zfill(10) if digits else ""


def _norm_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").replace("\u00a0", " ")).strip()


def _norm_key(value: Any) -> str:
    text = _norm_text(value).lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _raw_id_lower(value: Any) -> str:
    return _norm_text(value).lower()


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _empty_bridge_df() -> pd.DataFrame:
    return pd.DataFrame(columns=BRIDGE_TABLE_COLUMNS)


def _record_to_row(cik: str, record: dict[str, Any]) -> dict[str, Any] | None:
    accession = _norm_text(record.get("accession_number"))
    report_date = _norm_text(record.get("report_date"))
    raw_lower = _raw_id_lower(record.get("raw_id_lower") or record.get("raw_investment_identifier"))
    family = _norm_text(record.get("family")).lower()
    if not (cik and accession and report_date and raw_lower and family):
        return None
    disposition = f"{family}_position_leaf"
    return {
        "cik": cik,
        "accession_number": accession,
        "report_date": report_date,
        "raw_id_lower": raw_lower,
        "issuer_name": _norm_text(record.get("issuer_name")),
        "instrument_description": _norm_text(record.get("instrument_description")),
        "family": family,
        "disposition": disposition,
        "rule_id": f"HTML_SECTION_BRIDGE_{family.upper()}_LEAF_V1",
        "html_sha256": _norm_text(record.get("html_sha256")),
        "table_index": int(record.get("table_index", -1)),
        "section_row_index": int(record.get("section_row_index", -1)),
        "row_index": int(record.get("row_index", -1)),
        "cell_indices": json.dumps(record.get("cell_indices", []), sort_keys=True),
        "section_label": _norm_text(record.get("section_label")),
        "maturity_date": _norm_text(record.get("maturity_date")),
        "acquisition_date": _norm_text(record.get("acquisition_date")),
        "reference_rate_type": _norm_text(record.get("reference_rate_type")),
        "permit_overwrite": bool(record.get("permit_overwrite", False)),
    }


def load_html_section_bridge_rows(
    bridge_dir: Path | None = None,
    *,
    ciks: Iterable[str] | None = None,
) -> pd.DataFrame:
    """Load accepted static HTML-section bridge rows as a DataFrame."""
    root = bridge_dir or BRIDGE_DEFINITIONS_DIR
    wanted = {normalize_cik(c) for c in ciks or [] if normalize_cik(c)}
    if not root.exists():
        return _empty_bridge_df()

    rows: list[dict[str, Any]] = []
    for path in sorted(root.glob("*.json")):
        try:
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Skipping invalid HTML bridge file %s: %s", path.name, exc)
            continue
        if data.get("schema_version") != BRIDGE_SCHEMA_VERSION:
            continue
        cik = normalize_cik(data.get("cik"))
        if not cik or (wanted and cik not in wanted):
            continue
        for record in data.get("bridges") or []:
            row = _record_to_row(cik, record)
            if row is not None:
                rows.append(row)

    if not rows:
        return _empty_bridge_df()
    return pd.DataFrame(rows, columns=BRIDGE_TABLE_COLUMNS).drop_duplicates(
        ["cik", "accession_number", "report_date", "raw_id_lower"],
        keep="last",
    )


def apply_html_section_bridge_wrapper_columns(
    df: pd.DataFrame,
    *,
    identifier_col: str,
    cik_col: str = "cik",
    bridge_dir: Path | None = None,
) -> pd.DataFrame:
    """Overlay wrapper classification columns for exact bridge matches."""
    if df.empty or identifier_col not in df.columns:
        return df
    bridges = load_html_section_bridge_rows(bridge_dir)
    if bridges.empty:
        return df

    result = df.copy()
    for col in ("accession_number", "report_date", cik_col):
        if col not in result.columns:
            return result
    key_df = pd.DataFrame(
        {
            "_idx": result.index,
            "cik": result[cik_col].map(normalize_cik),
            "accession_number": result["accession_number"].map(_norm_text),
            "report_date": result["report_date"].map(_norm_text),
            "raw_id_lower": result[identifier_col].map(_raw_id_lower),
        }
    )
    matched = key_df.merge(
        bridges,
        on=["cik", "accession_number", "report_date", "raw_id_lower"],
        how="left",
    )
    matched = matched[matched["family"].fillna("").astype(str).ne("")]
    if matched.empty:
        return result

    for _, row in matched.iterrows():
        idx = row["_idx"]
        family = str(row["family"])
        issuer = _norm_key(row["issuer_name"])
        instrument = _norm_key(row["instrument_description"])
        key = " ".join(part for part in [issuer, instrument] if part).strip()
        result.at[idx, "wrapper_version"] = "html-section-bridge.v1"
        result.at[idx, "wrapper_family"] = family
        result.at[idx, "wrapper_disposition"] = row["disposition"]
        result.at[idx, "wrapper_rule_id"] = row["rule_id"]
        result.at[idx, "wrapper_parent_key"] = issuer
        result.at[idx, "wrapper_position_key"] = key or _norm_key(result.at[idx, identifier_col])
        result.at[idx, "wrapper_signature_status"] = "pass"
        result.at[idx, "wrapper_unparsed_remainder"] = ""
    return result


_CONTINUED_RE = re.compile(r"(?i)\s*\(continued\)\s*$")


# ---------------------------------------------------------------------------
# Column-aware extraction + per-field status (shadow list)
# ---------------------------------------------------------------------------
# Default field -> column rules. header = regex the source column label must
# match for status=value; otherwise the value is heuristic -> validation_needed.
# Per-CIK overrides can extend this (Layer-2). "No rule" defaults conservative.
_FIELD_COLUMN_RULES: dict[str, dict[str, str]] = {
    # No \b after "maturity": many filers concatenate labels ("MaturityDate").
    "maturity_date": {"header": r"(?i)maturity"},
    "acquisition_date": {"header": r"(?i)acquisition|initial"},
    # reference_rate_type is the BENCHMARK name (SOFR/LIBOR/...).  It may live in a
    # dedicated "Index" / "Reference Rate" column (bare code, e.g. "SF"), OR in a
    # combined column ("Reference Rate and Spread", "SpreadAboveIndex" holding
    # "SF + 5.50%").  Match all of these; field_status() tries candidates in
    # priority order (dedicated benchmark column first) and returns the first that
    # parses to a benchmark -- so a pure numeric Spread column does not produce a
    # false value, and a combined column is still read.
    # "interest rate" is included as a LAST-priority candidate: some filers put
    # the benchmark there ("Prime plus", "SOFR + 5.50%"); a purely numeric all-in
    # rate just fails to parse and stays flagged, so it is safe.
    "reference_rate_type": {"header": r"(?i)reference\s*rate|\bindex\b|spread|basis|base\s*rate|interest\s*rate"},
}
_HEADER_LABEL_RE = re.compile(
    r"(?i)maturity|reference\s*rate|spread|acquisition|principal|par\s*amount|"
    r"\bcost\b|fair\s*value|interest\s*rate|coupon|industry|company|portfolio|investment"
)


def _row_grid(tr) -> list[str]:
    """Colspan-aware expansion of a <tr> into a flat grid of cell texts."""
    out: list[str] = []
    for td in tr.iter():
        if _ixbrl_local(td.tag) not in ("td", "th"):  # headers are often <th>
            continue
        out.append(_norm_text("".join(td.itertext())))
        try:
            span = int(td.get("colspan") or 1)
        except ValueError:
            span = 1
        out.extend([""] * (max(span, 1) - 1))
    return out


def _detect_header_map(grid: list[str]) -> dict[int, str] | None:
    """Return grid-index -> header label if the row looks like a column header
    (>=2 field labels, no data numbers); else None."""
    nonempty = [c for c in grid if c]
    if len(nonempty) < 3:
        return None
    # strip footnote markers so header labels aren't counted as numeric:
    # parenthesized "(2)(15)" AND bare trailing refs "Maturity 6" / "Company 1 2 3 4"
    def _nofn(s: str) -> str:
        s = re.sub(r"\(\d{1,3}\)", "", s)
        s = re.sub(r"(?:\s+\d{1,2}\b)+\s*$", "", s)  # trailing 1-2 digit footnote refs
        return _norm_text(s)
    labeled = sum(1 for c in grid if c and _HEADER_LABEL_RE.search(c))
    numeric = sum(1 for c in grid if c and re.search(r"\d", _nofn(c)))
    if labeled >= 2 and numeric == 0:
        return {i: _nofn(c) for i, c in enumerate(grid) if _nofn(c)}
    return None


_MMYY_RE = re.compile(r"^\s*(\d{1,2})/(\d{2})\s*$")


def _parse_field_value(field: str, cell: str) -> str:
    if field in ("maturity_date", "acquisition_date"):
        ds = _extract_row_dates([cell])
        if ds:
            return ds[-1].isoformat()
        # Header-confirmed date column: accept abbreviated MM/YY (e.g. Main Street
        # "04/28" -> Apr 2028). Only safe here because we know this is the date
        # column; NOT applied in the heuristic row scan where MM/DD is ambiguous.
        m = _MMYY_RE.match(cell or "")
        if m:
            mm, yy = int(m.group(1)), int(m.group(2))
            if 1 <= mm <= 12:
                try:
                    return _last_day(2000 + yy, mm).isoformat()
                except ValueError:
                    pass
        return ""
    if field == "reference_rate_type":
        return _extract_reference_rate([cell]) or _benchmark_from_code(cell)
    return _norm_text(cell)


def _heuristic_field_value(field: str, grid: list[str]) -> str:
    if field == "maturity_date":
        ds = _extract_row_dates(grid)
        return ds[-1].isoformat() if ds else ""
    if field == "acquisition_date":
        ds = _extract_row_dates(grid)
        return ds[0].isoformat() if len(ds) >= 2 else ""
    if field == "reference_rate_type":
        return _extract_reference_rate(grid)
    return ""


def field_status(field: str, grid: list[str], header_map: dict[int, str]) -> dict[str, str]:
    """Resolve one field from an anchored row -> {value, status, source_column}.

    status: ``value`` (header-confirmed cell), ``validation_needed`` (value found
    but column unconfirmed -- heuristic, or cell present but unparsable), or
    ``blank`` (column found but empty, or nothing found). ``not_found`` (the
    flat-XBRL position has no inline row) is assigned upstream at the join.
    """
    rule = _FIELD_COLUMN_RULES.get(field, {})
    hdr = rule.get("header")
    cols: list[int] = []
    if hdr and header_map:
        hr = re.compile(hdr)
        cols = [i for i in sorted(header_map) if hr.search(header_map[i]) and i < len(grid)]
    if cols:
        # When several columns match (benchmark "Index" + numeric "Spread"), try
        # the dedicated-benchmark column first, then combined, then pure-spread;
        # return the first that parses.  This avoids locking onto a numeric spread
        # column while still reading a combined "Reference Rate and Spread" cell.
        def _pri(i: int) -> tuple[int, int]:
            lab = header_map[i].lower()
            benchy = ("index" in lab or "reference" in lab or "base rate" in lab)
            spready = ("spread" in lab or "basis" in lab)
            rank = 0 if (benchy and not spready) else (1 if benchy else 2)
            return (rank, i)
        cols.sort(key=_pri)
        first_nonempty = None
        for i in cols:
            cell = grid[i]
            if not cell:
                continue
            if first_nonempty is None:
                first_nonempty = i
            pv = _parse_field_value(field, cell)
            if pv:
                return {"value": pv, "status": "value", "source_column": header_map[i]}
        if first_nonempty is not None:
            # matched column(s) had content but nothing parsed -> suspect
            return {"value": "", "status": "validation_needed", "source_column": header_map[first_nonempty]}
        return {"value": "", "status": "blank", "source_column": header_map[cols[0]]}
    hv = _heuristic_field_value(field, grid)
    if hv:
        return {"value": hv, "status": "validation_needed", "source_column": "(heuristic)"}
    return {"value": "", "status": "blank", "source_column": ""}


def apply_maturity_signature(rec: dict[str, str], report_date: str) -> dict[str, str]:
    """Content signature for maturity: a header-confirmed maturity must be
    future-dated relative to the report date.  A past-dated 'maturity' is almost
    always a misread acquisition/other date in a coincidentally-aligned cell ->
    downgrade value -> validation_needed (header-agnostic; catches the
    coincidental-parse case the column logic can't)."""
    if (rec.get("status") == "value" and rec.get("value") and report_date
            and rec["value"] < report_date):
        return {**rec, "status": "validation_needed"}
    return rec


def apply_html_section_bridge_field_overlays(
    df: pd.DataFrame,
    *,
    identifier_col: str,
    cik_col: str = "cik",
    bridge_dir: Path | None = None,
) -> pd.DataFrame:
    """Overlay HTML-sourced descriptor VALUES (maturity_date, reference_rate_type)
    onto exact bridge matches, only where the staged value is currently blank.

    Exact-keyed by (cik, accession_number, report_date, raw_id_lower) -- never a
    broad fallback.  Bridged maturity comes from an HTML row whose fair value
    already reconciled to the XBRL position, so it inherits that evidence.

    src_field_overrides: for each overlaid field, appends a coordinate ref of the
    form ``field=bridge:<sha8>:t<table_index>:r<row_index>`` (';'-joined across
    fields), enabling downstream consumers to trace each bridge-sourced value back
    to the exact HTML table cell that supplied it.
    """
    if df.empty or identifier_col not in df.columns:
        return df
    bridges = load_html_section_bridge_rows(bridge_dir)
    if bridges.empty:
        return df
    for col in ("accession_number", "report_date", cik_col):
        if col not in df.columns:
            return df

    result = df.copy()
    for col in ("maturity_date", "maturity_date_source",
                "reference_rate_type", "reference_rate_source",
                "src_field_overrides"):
        if col not in result.columns:
            result[col] = ""

    key_df = pd.DataFrame(
        {
            "_idx": result.index,
            "cik": result[cik_col].map(normalize_cik),
            "accession_number": result["accession_number"].map(_norm_text),
            "report_date": result["report_date"].map(_norm_text),
            "raw_id_lower": result[identifier_col].map(_raw_id_lower),
        }
    )
    matched = key_df.merge(
        bridges[[
            "cik", "accession_number", "report_date", "raw_id_lower",
            "maturity_date", "reference_rate_type",
            "html_sha256", "table_index", "row_index",
        ]],
        on=["cik", "accession_number", "report_date", "raw_id_lower"],
        how="inner",
    )
    if matched.empty:
        return result

    def _blank(v: Any) -> bool:
        return v is None or str(v).strip() in ("", "nan", "NaT")

    def _append_override(idx: Any, field: str, row: Any) -> None:
        sha8 = _norm_text(row.get("html_sha256"))[:8]
        ref = (f"{field}=bridge:{sha8}"
               f":t{int(row.get('table_index', -1))}"
               f":r{int(row.get('row_index', -1))}")
        prev = str(result.at[idx, "src_field_overrides"] or "").strip()
        result.at[idx, "src_field_overrides"] = f"{prev};{ref}" if prev else ref

    for _, row in matched.iterrows():
        idx = row["_idx"]
        mat = _norm_text(row.get("maturity_date"))
        if mat and _blank(result.at[idx, "maturity_date"]):
            result.at[idx, "maturity_date"] = mat
            result.at[idx, "maturity_date_source"] = "html_section_bridge"
            _append_override(idx, "maturity_date", row)
        rrt = _norm_text(row.get("reference_rate_type"))
        if rrt and _blank(result.at[idx, "reference_rate_type"]):
            result.at[idx, "reference_rate_type"] = rrt
            result.at[idx, "reference_rate_source"] = "html_section_bridge"
            _append_override(idx, "reference_rate_type", row)
    return result


def _section_for_row(row: list[str]) -> tuple[str, str] | None:
    cells = [_norm_text(cell) for cell in row if _norm_text(cell)]
    if len(cells) != 1:
        return None
    # "First Lien Debt (continued)" on continuation pages -> same section
    text = _CONTINUED_RE.sub("", cells[0])
    if _VALUE_RE.search(text):
        return None
    for pattern, family, instrument in _SECTION_PATTERNS:
        if pattern.match(text):
            return family, instrument
    return None


def _parse_numeric_tokens(row: list[str]) -> list[float]:
    values: list[float] = []
    for cell in row:
        text = _norm_text(cell)
        if not text:
            continue
        for match in re.finditer(r"\(?\$?\s*\d[\d,]*(?:\.\d+)?\)?", text):
            token = match.group(0).replace("$", "").replace(",", "").replace(" ", "")
            negative = token.startswith("(") and token.endswith(")")
            token = token.strip("()")
            try:
                value = float(token)
            except ValueError:
                continue
            values.append(-value if negative else value)
    return values


def _number_matches(row_values: list[float], value: Any) -> bool:
    try:
        target = float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return False
    for candidate in row_values:
        if abs(candidate - target) <= max(1.0, abs(target) * 0.0001):
            return True
        if abs(candidate * 1000 - target) <= max(1.0, abs(target) * 0.0001):
            return True
    return False


def _search_terms(source_row: dict[str, Any]) -> list[str]:
    raw = _norm_text(
        source_row.get("raw_investment_identifier")
        or source_row.get("investment_identifier")
        or source_row.get("normalized_investment_identifier")
    )
    # Pipe-delimited affiliation suffix (Blackstone et al.):
    # "123Dentist, Inc. 1 | Non-Affiliated Issuer" -> issuer = "123Dentist, Inc."
    # Keep the segment before the first pipe and drop the trailing tranche
    # number; FV reconciliation disambiguates tranches downstream.
    if "|" in raw:
        raw = raw.split("|", 1)[0].strip()
        raw = re.sub(r"\s+\d+$", "", raw).strip()
    cleaned = _GENERIC_SOURCE_RE.sub(" ", raw)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" ,-")
    terms = [cleaned] if len(_norm_key(cleaned)) >= 5 else []
    words = raw.split()
    for n in (8, 7, 6, 5, 4, 3, 2):
        if len(words) < n:
            continue
        tail = " ".join(words[-n:])
        tail = _GENERIC_SOURCE_RE.sub(" ", tail)
        tail = re.sub(r"\s+", " ", tail).strip(" ,-")
        if len(_norm_key(tail)) >= 5:
            terms.append(tail)
    out: list[str] = []
    seen: set[str] = set()
    for term in terms:
        key = _norm_key(term)
        if key and key not in seen and len(_TOKEN_RE.findall(key)) >= 2:
            out.append(term)
            seen.add(key)
    return out[:8]


def propose_html_section_bridges(
    *,
    cik: str,
    accession_number: str,
    report_date: str,
    source_rows: Iterable[dict[str, Any]],
    html_path: Path | None = None,
) -> dict[str, Any]:
    """Propose bridge records from cached HTML and source rows.

    The returned records are proposals. They should be reviewed before being
    saved under ``data/overrides/bdc_xbrl_html_section_bridges``.
    """
    cik_norm = normalize_cik(cik)
    acc = _norm_text(accession_number)
    acc_nodashes = acc.replace("-", "")
    path = html_path or (BDC_HTML_CACHE_DIR / cik_norm.lstrip("0") / f"{acc_nodashes}.html")
    if not path.exists():
        return {
            "schema_version": BRIDGE_SCHEMA_VERSION,
            "cik": cik_norm,
            "version": 1,
            "source": "bdc_xbrl",
            "bridges": [],
            "rejected": [{"reason": "missing_cached_html", "path": str(path)}],
        }

    raw_html = path.read_text(encoding="utf-8", errors="replace")
    tables = _extract_tables(raw_html)
    html_sha = _sha256_file(path)
    candidates: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []

    positioned_rows: list[dict[str, Any]] = []
    for table_index, table in enumerate(tables):
        active: tuple[int, str, str] | None = None
        for row_index, row in enumerate(table):
            section = _section_for_row(row)
            if section:
                active = (row_index, section[0], section[1])
                continue
            if active is None:
                continue
            row_text = " ".join(_norm_text(cell) for cell in row if _norm_text(cell))
            if not row_text or _SUBTOTAL_RE.search(row_text):
                continue
            values = _parse_numeric_tokens(row)
            if not values:
                continue
            first_cell = next((_norm_text(cell) for cell in row if _norm_text(cell)), "")
            inline_type = _parse_inline_instrument_type(first_cell)
            row_dates = _extract_row_dates(row)
            positioned_rows.append({
                "table_index": table_index,
                "section_row_index": active[0],
                "row_index": row_index,
                "row_key": _norm_key(row_text),
                "row_values": values,
                "issuer_name": first_cell,
                "family": active[1],
                "instrument_description": inline_type or active[2],
                "section_label": active[2],
                "inline_instrument_type": inline_type,
                "cell_indices": [idx for idx, cell in enumerate(row) if _norm_text(cell)],
                # HTML-sourced field values: maturity = latest date in the row,
                # acquisition = earliest (kept for reviewer cross-check).
                "maturity_date": row_dates[-1].isoformat() if row_dates else "",
                "acquisition_date": row_dates[0].isoformat() if len(row_dates) >= 2 else "",
                "reference_rate_type": _extract_reference_rate(row),
            })

    for source in source_rows:
        raw_id = _norm_text(
            source.get("raw_investment_identifier")
            or source.get("investment_identifier")
            or source.get("normalized_investment_identifier")
        )
        if not raw_id:
            continue
        terms = [_norm_key(term) for term in _search_terms(source)]
        terms = [term for term in terms if term]
        matches = [
            row for row in positioned_rows
            if any(term in row["row_key"] for term in terms)
        ]
        fv = source.get("source_fair_value", source.get("fair_value"))
        if fv not in (None, ""):
            matches = [row for row in matches if _number_matches(row["row_values"], fv)]
        if len(matches) != 1:
            rejected.append({
                "raw_investment_identifier": raw_id,
                "reason": "ambiguous_or_unmatched_html_row",
                "candidate_count": len(matches),
            })
            continue
        row = matches[0]
        candidates.append({
            "accession_number": acc,
            "report_date": report_date,
            "raw_id_lower": _raw_id_lower(raw_id),
            "issuer_name": row["issuer_name"],
            "instrument_description": row["instrument_description"],
            "family": row["family"],
            "html_sha256": html_sha,
            "table_index": row["table_index"],
            "section_row_index": row["section_row_index"],
            "row_index": row["row_index"],
            "cell_indices": row["cell_indices"],
            "section_label": row["section_label"],
            "inline_instrument_type": row.get("inline_instrument_type"),
            "maturity_date": row.get("maturity_date", ""),
            "acquisition_date": row.get("acquisition_date", ""),
            "reference_rate_type": row.get("reference_rate_type", ""),
            "match_evidence": {
                "matched_terms": terms[:5],
                "fair_value_matched": fv not in (None, ""),
            },
        })

    return {
        "schema_version": BRIDGE_SCHEMA_VERSION,
        "cik": cik_norm,
        "version": 1,
        "source": "bdc_xbrl",
        "bridges": candidates,
        "rejected": rejected,
    }


# Fields carried from the inline anchor, and where their status lives.
_STATUS_FIELDS = ("maturity_date", "reference_rate_type", "lien_position", "gics_sector")
_FIELD_STATUS_KEY = {
    "maturity_date": "maturity_status",
    "reference_rate_type": "reference_rate_status",
}


def join_flat_positions_to_inline_status(
    flat_rows: Iterable[dict[str, Any]],
    bridges: Iterable[dict[str, Any]],
    *,
    identifier_key: str = "investment_identifier",
) -> list[dict[str, Any]]:
    """Attach inline per-field statuses to every flat-XBRL position.

    A flat position that has no inline anchor (its row was not found in the
    inline document, though it exists in flat XBRL) gets status ``not_found``
    for all fields -> routed to review.  Otherwise each field carries the
    builder's status (``value`` / ``validation_needed`` / ``blank``); fields
    without an explicit status (lien/sector) derive ``value`` if populated else
    ``blank``.

    Period scoping: the inline document tags only the *current* period's
    positions, so an unanchored flat row that is a comparative-period fact
    (``period`` != ``report_date``) is benign -- it is anchored in its own
    current-period filing, not this one.  Such rows are labeled ``comparative``
    (not ``not_found``) so the review queue is scoped to genuine current-period
    misses.  Each record carries ``period`` and ``period_role``.
    """
    by_key: dict[str, dict[str, Any]] = {}
    for b in bridges:
        by_key[_raw_id_lower(b.get("raw_id_lower") or b.get(identifier_key) or "")] = b

    out: list[dict[str, Any]] = []
    for fr in flat_rows:
        ident = str(fr.get(identifier_key) or "")
        b = by_key.get(_raw_id_lower(ident))
        rdate = _norm_text(fr.get("report_date"))
        period = _norm_text(fr.get("period"))
        period_role = "comparative" if period and period != rdate else "current"
        unanchored_status = "not_found" if period_role == "current" else "comparative"
        rec: dict[str, Any] = {
            "cik": fr.get("cik", ""),
            "accession_number": fr.get("accession_number", ""),
            "report_date": fr.get("report_date", ""),
            "period": period,
            "period_role": period_role,
            "investment_identifier": ident,
            "anchored": b is not None,
        }
        for f in _STATUS_FIELDS:
            if b is None:
                rec[f] = ""
                rec[f"{f}_status"] = unanchored_status
                rec[f"{f}_source_column"] = ""
                continue
            rec[f] = b.get(f, "")
            st = b.get(_FIELD_STATUS_KEY.get(f, ""))
            if st is None:  # lien/sector: no explicit status -> derive
                st = "value" if b.get(f) else "blank"
            rec[f"{f}_status"] = st
            rec[f"{f}_source_column"] = b.get(f"{f}_source_column", "")
        out.append(rec)
    return out


_ZERO_FV = 1.0  # dollars: a current position with |FV| below this owns ~nothing


def _parse_fv(v: Any) -> float | None:
    if v is None:
        return None
    try:
        return float(str(v).replace(",", "").replace("$", "").strip())
    except (ValueError, AttributeError):
        return None


def build_field_status_rows(
    bridges: Iterable[dict[str, Any]],
    flat_rows: Iterable[dict[str, Any]],
    lien_subtotals: dict[str, float],
    *,
    identifier_key: str = "investment_identifier",
    commitment_ids: Iterable[str] | None = None,
) -> list[dict[str, Any]]:
    """Producer core for one filing: join flat positions -> inline status (Step 3,
    assigns not_found), apply the lien reconciliation gate (a), classify benign
    unanchored rows, and emit rows in the overlay's schema.

    Anchor classification of current-period unanchored rows -- so the review queue
    is not polluted by rows we already know are OK:
      - ``unfunded_commitment``: the filer tagged the position (it is in
        ``commitment_ids`` -- has rate/spread/contractual-obligation facts) but
        there is no InvestmentOwnedAtFairValue fact (delayed draw / revolver).
      - ``zero_fv``: flat fair value is confirmed ~0 (nothing owned).
      - ``not_found``: material (non-zero FV) and untagged -> a genuine miss.
    Benign classes set every field status to the class label, so a downstream
    review filter on status==``not_found`` skips them.

    If the filing's value-status lien doesn't roll up to ``lien_subtotals``
    (reconcile_to_subtotals fails), value-status lien is downgraded to
    validation_needed for the whole filing -> the overlay then won't apply it.
    """
    flat_rows = list(flat_rows)
    joined = join_flat_positions_to_inline_status(flat_rows, bridges, identifier_key=identifier_key)
    commit = {_raw_id_lower(c) for c in (commitment_ids or ())}
    # Current-period FV lookups. reconcile uses 0.0 for null (a still-held
    # position also appears as a comparative row with the same identifier, and
    # summing both double-counts its FV); the benign-classifier needs null
    # preserved so a null FV is not mislabeled zero_fv.
    cur_rows = [r for r in flat_rows
                if not _norm_text(r.get("period")) or _norm_text(r.get("period")) == _norm_text(r.get("report_date"))]
    fv_by_id = {_raw_id_lower(r.get(identifier_key, "")): float(r.get("fair_value") or 0.0) for r in cur_rows}
    fv_num_by_id = {_raw_id_lower(r.get(identifier_key, "")): _parse_fv(r.get("fair_value")) for r in cur_rows}

    # (a) lien reconciliation gate -- current-period value-lien rows only
    per_pos = [(j["lien_position"], fv_by_id.get(_raw_id_lower(j["investment_identifier"]), 0.0))
               for j in joined
               if j.get("lien_position_status") == "value" and j.get("lien_position")
               and j.get("period_role") == "current"]
    lien_ok = reconcile_to_subtotals(per_pos, lien_subtotals)["reconciled"] if lien_subtotals else True

    rows: list[dict[str, Any]] = []
    for j in joined:
        anchored = j.get("anchored")
        role = j.get("period_role", "current")
        rid = _raw_id_lower(j["investment_identifier"])
        # benign classification for current-period unanchored rows
        benign = None
        if not anchored and role == "current":
            fv = fv_num_by_id.get(rid)
            if rid in commit:
                benign = "unfunded_commitment"
            elif fv is not None and abs(fv) < _ZERO_FV:
                benign = "zero_fv"
        if anchored:
            anchor_class = "anchored"
        elif role == "comparative":
            anchor_class = "comparative"
        else:
            anchor_class = benign or "missing"

        lien_status = j.get("lien_position_status", "")
        if lien_status == "value" and not lien_ok:
            lien_status = "validation_needed"  # filer-quarter failed rollup
        if benign:  # OK row -> every field carries the benign label, not not_found
            lien_status = benign

        def _fs(field_status_value: str) -> str:
            return benign if benign else field_status_value

        rows.append({
            "cik": j["cik"], "accession_number": j["accession_number"],
            "report_date": j["report_date"], "period": j.get("period", ""),
            "period_role": role, "anchor_class": anchor_class,
            "raw_id_lower": rid,
            "maturity_date": j.get("maturity_date", ""),
            "maturity_status": _fs(j.get("maturity_date_status", "")),
            "reference_rate_type": j.get("reference_rate_type", ""),
            "reference_rate_status": _fs(j.get("reference_rate_type_status", "")),
            "lien_position": j.get("lien_position", ""),
            "lien_status": lien_status,
            "gics_sector": j.get("gics_sector", ""),
            "sector_status": _fs(j.get("gics_sector_status", "")),
            "lien_reconciled": lien_ok,
        })
    return rows


def reconcile_to_subtotals(
    per_position: Iterable[tuple[str, float]],
    subtotals: dict[str, float],
    *,
    tol_pct: float = 0.05,
    tol_abs: float = 5_000_000.0,
) -> dict[str, Any]:
    """(a) Roll per-position tier FV up to the filer's own subtotals.

    ``per_position``: (tier, fv) for each anchored position. ``subtotals``: the
    filer's tier -> FV (from bdc_lien_breakdown / bdc_sector_breakdown). A tier
    reconciles if its position-sum matches its subtotal within tolerance; the
    filer-quarter reconciles if every subtotal'd tier matches. Used to downgrade
    lien/sector status to validation_needed when the rollup fails (the
    arithmetic backstop the column rules can't provide).
    """
    pos_by_tier: dict[str, float] = {}
    for tier, fv in per_position:
        if tier:
            pos_by_tier[tier] = pos_by_tier.get(tier, 0.0) + float(fv or 0.0)
    tiers: dict[str, dict[str, Any]] = {}
    all_ok = bool(subtotals)
    for tier, sub_fv in subtotals.items():
        ps = pos_by_tier.get(tier, 0.0)
        ok = abs(ps - sub_fv) <= max(tol_abs, tol_pct * abs(sub_fv))
        tiers[tier] = {"pos_sum": ps, "subtotal": float(sub_fv), "ok": ok}
        all_ok = all_ok and ok
    return {"reconciled": all_ok, "tiers": tiers}


# Unified-column fields the overlay can write, with their status key.
_OVERLAY_FIELDS = {
    "maturity_date": "maturity_status",
    "reference_rate_type": "reference_rate_status",
    "lien_position": "lien_status",
}


def apply_ixbrl_field_status_overlay(
    df: "pd.DataFrame",
    status_rows: Iterable[dict[str, Any]],
    *,
    identifier_col: str = "bdc_investment_identifier",
    cik_col: str = "cik",
    dims_col: str = "bdc_dimensions_raw",
) -> "pd.DataFrame":
    """(b) Overlay only ``status='value'`` descriptors onto the staged rows.

    Exact-keyed by (cik, accession, report_date, <full inline-XBRL member>);
    blank-only (never clobbers an existing value); consumes ONLY ``value`` status
    (validation_needed / not_found / blank are left as-is -> Unknown). For
    lien/sector the status already reflects the reconciliation gate (downgraded
    upstream if the filer-quarter didn't reconcile), so this is a simple value
    consumer.

    Join key: the FULL ``InvestmentIdentifierAxis`` member. The artifact stores it
    in ``raw_id_lower``; production preserves it in ``bdc_dimensions_raw``
    (``...axis=<member>``). Keying on the STRIPPED ``bdc_investment_identifier``
    (the prior behavior) misses flattened filers whose member carries an affiliation
    suffix (e.g. ``"... | Non-Affiliated Issuer"``), stranding ~65% of their captured
    lien/maturity. Falls back to ``identifier_col`` when the dims member is absent.
    """
    if df.empty:
        return df
    for col in ("accession_number", "report_date", cik_col, identifier_col):
        if col not in df.columns:
            return df
    # Accept a DataFrame directly (avoids a CSV->dicts->DataFrame round-trip on the
    # ~1M-row artifact); copy so we never mutate the caller's frame.
    if isinstance(status_rows, pd.DataFrame):
        sdf = status_rows.copy()
    else:
        sdf = pd.DataFrame(list(status_rows))
    if sdf.empty:
        return df

    def _member_lower(frame: "pd.DataFrame") -> "pd.Series":
        """Full inline-XBRL InvestmentIdentifierAxis member, lowercased -- matches
        the artifact's raw_id_lower. From bdc_dimensions_raw ('...axis=<member>'),
        falling back to identifier_col when dims is absent/unparseable."""
        ident = frame[identifier_col].map(_norm_text)
        if dims_col in frame.columns:
            # astype("string") first: an all-null dims column is inferred as
            # nullable Int32, and Int32.fillna("") raises (the all-NULL->Int32
            # pitfall). Coerce to StringDtype so fillna("") is valid; null rows
            # become "" and fall through to the identifier fallback below.
            dims = frame[dims_col].astype("string").fillna("")
            mem = dims.str.replace(r"^[^=]*=", "", regex=True).map(_norm_text)
            mem = mem.where(dims.str.contains("=", regex=False) & (mem.str.strip() != ""), ident)
        else:
            mem = ident
        return mem.str.lower()

    result = df.copy()
    for fld in _OVERLAY_FIELDS:
        if fld not in result.columns:
            result[fld] = ""
    if "reference_rate_source" not in result.columns:
        result["reference_rate_source"] = ""

    result["_k"] = (result[cik_col].map(normalize_cik) + "|"
                    + result["accession_number"].map(_norm_text) + "|"
                    + result["report_date"].map(_norm_text) + "|"
                    + _member_lower(result))
    id_src = identifier_col if identifier_col in sdf.columns else None
    sdf["_k"] = (sdf[cik_col].map(normalize_cik) if cik_col in sdf.columns else sdf["cik"].map(normalize_cik)) + "|" \
        + sdf["accession_number"].map(_norm_text) + "|" + sdf["report_date"].map(_norm_text) + "|" \
        + (sdf["raw_id_lower"].map(_raw_id_lower) if "raw_id_lower" in sdf.columns else sdf[id_src].map(_raw_id_lower))

    keep = ["_k"] + [c for f in _OVERLAY_FIELDS for c in (f, _OVERLAY_FIELDS[f]) if c in sdf.columns]
    sdf = sdf[keep].drop_duplicates("_k", keep="last")
    merged = result.merge(sdf, on="_k", how="left", suffixes=("", "_ix"))

    blank = lambda col: col.isna() | col.astype(str).str.strip().isin(["", "nan", "NaT"])
    for fld, status_key in _OVERLAY_FIELDS.items():
        vcol, scol = f"{fld}_ix", f"{status_key}"
        if vcol not in merged.columns or scol not in merged.columns:
            continue
        mask = (merged[scol].astype(str) == "value") & merged[vcol].notna() \
            & (merged[vcol].astype(str).str.strip() != "") & blank(merged[fld])
        result.loc[mask.values, fld] = merged.loc[mask, vcol].values
        # mark provenance: a bridge-filled value is NOT a structured XBRL tag
        _src = {"reference_rate_type": "reference_rate_source",
                "maturity_date": "maturity_date_source"}.get(fld)
        if _src:
            if _src not in result.columns:
                result[_src] = ""
            result.loc[mask.values, _src] = "ixbrl_field_status"
    result.drop(columns=["_k"], inplace=True)
    return result


def _ixbrl_local(tag: Any) -> str:
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) and "}" in tag else (tag or "")


def propose_field_bridges_from_ixbrl(
    *,
    cik: str,
    accession_number: str,
    report_date: str,
    html_path: Path | None = None,
    fv_concept: str = "InvestmentOwnedAtFairValue",
) -> dict[str, Any]:
    """Build maturity / reference-rate bridge records by anchoring on the inline
    XBRL fair-value fact's ``contextRef`` (an exact per-position key) and reading
    the enclosing table row.

    This supersedes the fuzzy issuer-name + FV matcher for inline-XBRL filers:
    the FV fact is tagged with the position's context (whose
    ``InvestmentIdentifierAxis`` member == ``bdc_investment_identifier``), so the
    join is exact and per-tranche, not a name guess.  Maturity / reference rate
    are read from the untagged sibling cells of the same DOM row.
    """
    from lxml import etree

    cik_norm = normalize_cik(cik)
    acc = _norm_text(accession_number)
    acc_nodashes = acc.replace("-", "")
    path = html_path or (BDC_HTML_CACHE_DIR / cik_norm.lstrip("0") / f"{acc_nodashes}.html")
    if not path.exists():
        return {"schema_version": BRIDGE_SCHEMA_VERSION, "cik": cik_norm, "version": 1,
                "source": "bdc_xbrl_ixbrl", "bridges": [],
                "rejected": [{"reason": "missing_cached_html", "path": str(path)}]}

    tree = etree.parse(str(path))
    root = tree.getroot()
    html_sha = _sha256_file(path)

    # context id -> (identifier, instant)
    contexts: dict[str, tuple[str, str]] = {}
    for c in root.iter():
        if _ixbrl_local(c.tag) != "context":
            continue
        cid = c.get("id")
        ident = instant = ""
        for sub in c.iter():
            st = _ixbrl_local(sub.tag)
            if st == "typedMember" and "Investment" in (sub.get("dimension") or ""):
                kids = list(sub)
                ident = _norm_text((kids[0].text if kids else sub.text) or "")
            elif st == "instant":
                instant = _norm_text(sub.text)
        if cid:
            contexts[cid] = (ident, instant)

    # Walk table rows in document order so the active lien section and industry
    # sub-header are known for each position row (per-position lien/sector).
    bridges: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    seen: set[str] = set()
    cur_lien = ""
    cur_sector = ""
    cur_header: dict[int, str] = {}
    rd = _norm_text(report_date)

    # Commitment evidence: a current-instant identifier that the filer DID tag
    # (any fact) but for which there is NO InvestmentOwnedAtFairValue fact is an
    # unfunded commitment / zero-FV position (delayed draw, revolver) -- it has
    # nothing owned at fair value to anchor.  These are benign, not genuine
    # missing datapoints, so the producer must not route them to review.
    fv_idents: set[str] = set()
    any_idents: set[str] = set()
    for el in root.iter():
        if _ixbrl_local(el.tag) != "nonFraction":
            continue
        ci, inst = contexts.get(el.get("contextRef"), ("", ""))
        if not ci or inst != rd:
            continue
        rl = _raw_id_lower(ci)
        any_idents.add(rl)
        if (el.get("name") or "").rsplit(":", 1)[-1] == fv_concept:
            fv_idents.add(rl)
    commitment_ids = sorted(any_idents - fv_idents)
    for tr in root.iter():
        if _ixbrl_local(tr.tag) != "tr":
            continue
        grid = _row_grid(tr)
        cells = [c for c in grid]  # grid is the colspan-expanded cell list
        nonempty = [c for c in cells if c]
        # column header row -> remember the column map for following data rows
        hm = _detect_header_map(grid)
        if hm is not None:
            cur_header = hm
            continue
        sec = _section_for_row(cells)
        if sec:
            cur_lien = sec[1]
            continue
        # industry sub-header: a lone non-value, non-subtotal label row
        if len(nonempty) == 1 and not _VALUE_RE.search(nonempty[0]) and not _SUBTOTAL_RE.search(nonempty[0]):
            cur_sector = _CONTINUED_RE.sub("", nonempty[0])
            continue
        # position row? find a leaf FV fact tagged with a current-period context
        ident = cref = ""
        for el in tr.iter():
            if _ixbrl_local(el.tag) != "nonFraction":
                continue
            if (el.get("name") or "").rsplit(":", 1)[-1] != fv_concept:
                continue
            i, inst = contexts.get(el.get("contextRef"), ("", ""))
            if i and inst == rd:
                ident, cref = i, el.get("contextRef")
                break
        if not ident or ident in seen:
            continue
        seen.add(ident)
        # Column-aware field resolution: each field carries value + status
        # (value / validation_needed / blank) + the source column it came from.
        mat = apply_maturity_signature(field_status("maturity_date", grid, cur_header), rd)
        acq = field_status("acquisition_date", grid, cur_header)
        rrt = field_status("reference_rate_type", grid, cur_header)
        footnotes = re.findall(r"\((\d{1,3})\)", " ".join(cells))
        # lien tier: section header (Blackstone-style) OR, for filers that group
        # only by industry, parse it from the row's instrument text.
        from pipeline.lien_classification import classify_lien
        lien_tier = classify_lien("", cur_lien) or classify_lien("", " ".join(cells)) or ""
        bridges.append({
            "accession_number": acc,
            "report_date": rd,
            "raw_id_lower": _raw_id_lower(ident),
            "issuer_name": ident,
            "instrument_description": "",
            "family": "debt" if mat["value"] else "equity",
            "html_sha256": html_sha,
            "maturity_date": mat["value"],
            "maturity_status": mat["status"],
            "maturity_source_column": mat["source_column"],
            "acquisition_date": acq["value"],
            "acquisition_status": acq["status"],
            "reference_rate_type": rrt["value"],
            "reference_rate_status": rrt["status"],
            "reference_rate_source_column": rrt["source_column"],
            "lien_position": lien_tier,
            "lien_section": cur_lien,
            "gics_sector": cur_sector,
            "footnote_markers": footnotes,
            "match_evidence": {"method": "ixbrl_contextref_anchor",
                               "context_ref": cref, "anchor_concept": fv_concept},
        })

    return {"schema_version": BRIDGE_SCHEMA_VERSION, "cik": cik_norm, "version": 1,
            "source": "bdc_xbrl_ixbrl", "bridges": bridges, "rejected": rejected,
            "commitment_ids": commitment_ids}


def extract_bdc_ixbrl_field_status(
    *,
    bdc_holdings_file: Path | None = None,
    lien_breakdown_file: Path | None = None,
    out_file: Path | None = None,
    ciks: Iterable[str] | None = None,
    progress_every: int = 250,
) -> Path:
    """APPLY STEP (universe run; heavy -- parses cached inline HTML per filing).

    Produce the per-position iXBRL field-status artifact for every cached inline
    filing: anchor descriptors on the FV fact's contextRef, join flat positions
    -> inline status (assigning not_found to flat rows absent from the inline
    doc), apply the lien subtotal-reconciliation gate, and write
    value / validation_needed / blank / not_found rows that the staging overlay
    (apply_ixbrl_field_status_overlay) consumes blank-only, value-only.

    Not invoked automatically -- run explicitly; it overwrites the artifact.
    """
    import duckdb
    from pipeline.config import (
        BDC_HOLDINGS_FILE, BDC_LIEN_BREAKDOWN_FILE, BDC_IXBRL_FIELD_STATUS_FILE,
    )
    hold = bdc_holdings_file or BDC_HOLDINGS_FILE
    lien_f = lien_breakdown_file or BDC_LIEN_BREAKDOWN_FILE
    out = out_file or BDC_IXBRL_FIELD_STATUS_FILE
    wanted = {normalize_cik(c) for c in (ciks or []) if normalize_cik(c)}

    con = duckdb.connect()
    # report_date MUST stay a 'YYYY-MM-DD' string: the builder anchors FV facts
    # by matching the XBRL context instant to report_date textually.  Letting
    # read_csv_auto infer DATE yields '...-00:00:00' keys that never match.
    flat = con.execute(
        "SELECT LPAD(CAST(cik AS VARCHAR),10,'0') AS cik, accession_number, "
        "report_date, CAST(period AS VARCHAR) AS period, investment_identifier, "
        "CAST(fair_value AS DOUBLE) AS fair_value "
        f"FROM read_csv_auto('{hold.as_posix()}', "
        "types={'cik':'VARCHAR','report_date':'VARCHAR','period':'VARCHAR'}) "
        "WHERE investment_identifier IS NOT NULL"
    ).df()
    if wanted:
        flat = flat[flat["cik"].isin(wanted)]

    # lien subtotals per (cik, report_date): prefer the lien_only grain
    subtotals: dict[tuple[str, str], dict[str, float]] = {}
    if lien_f.exists():
        lien = con.execute(
            "SELECT LPAD(CAST(cik AS VARCHAR),10,'0') AS cik, report_date, lien_tier, "
            "grain, CAST(fair_value AS DOUBLE) AS fair_value "
            f"FROM read_csv_auto('{lien_f.as_posix()}', "
            "types={'cik':'VARCHAR','report_date':'VARCHAR'})"
        ).df()
        if not lien.empty:
            lo = lien[lien["grain"] == "lien_only"]
            use = lo if not lo.empty else lien
            for (c, rd), grp in use.groupby(["cik", "report_date"]):
                subtotals[(c, rd)] = grp.groupby("lien_tier")["fair_value"].sum().to_dict()

    rows: list[dict[str, Any]] = []
    groups = list(flat.groupby(["cik", "accession_number", "report_date"]))
    logger.info("iXBRL field-status: %d filings to process", len(groups))
    for i, ((c, acc, rd), grp) in enumerate(groups, 1):
        prop = propose_field_bridges_from_ixbrl(cik=c, accession_number=acc, report_date=rd)
        bridges = prop.get("bridges") or []
        flat_rows = grp.to_dict("records")
        for fr in flat_rows:
            fr["cik"], fr["accession_number"], fr["report_date"] = c, acc, rd
        rows.extend(build_field_status_rows(
            bridges, flat_rows, subtotals.get((c, rd), {}),
            commitment_ids=prop.get("commitment_ids") or [],
        ))
        if i % progress_every == 0:
            logger.info("  processed %d/%d filings (%d status rows)", i, len(groups), len(rows))

    out_df = pd.DataFrame(rows)

    # in_unified: does this (cik, report_date, identifier) survive into the
    # index-facing unified holdings?  Lets the review queue scope to production
    # rows (status=='not_found' AND in_unified) and ignore subtotal-aggregate /
    # identifier-mismatched flat rows that the unified subtotal filter already
    # drops.  Audit trail is preserved -- the flag, not a hard filter.
    from pipeline.config import UNIFIED_HOLDINGS_FILE
    out_df["in_unified"] = False
    if UNIFIED_HOLDINGS_FILE.exists() and not out_df.empty:
        udf = con.execute(
            "SELECT DISTINCT LPAD(CAST(cik AS VARCHAR),10,'0') AS cik, "
            "CAST(report_date AS VARCHAR) AS report_date, bdc_investment_identifier AS ident "
            f"FROM read_csv_auto('{UNIFIED_HOLDINGS_FILE.as_posix()}', "
            "types={'cik':'VARCHAR','report_date':'VARCHAR'}) "
            "WHERE bdc_investment_identifier IS NOT NULL"
        ).df()
        udf["raw_id_lower"] = udf["ident"].map(_raw_id_lower)
        udf = udf[["cik", "report_date", "raw_id_lower"]].drop_duplicates()
        udf["_u"] = True
        out_df = out_df.merge(udf, on=["cik", "report_date", "raw_id_lower"], how="left")
        out_df["in_unified"] = out_df.pop("_u").fillna(False)

    out_df.to_csv(out, index=False)
    logger.info("Wrote %d iXBRL field-status rows (%d in_unified) -> %s",
                len(out_df), int(out_df["in_unified"].sum()), out)
    return out


def _main() -> int:
    parser = argparse.ArgumentParser(description="Propose BDC XBRL HTML-section bridge records from cached HTML.")
    parser.add_argument("--cik", required=True)
    parser.add_argument("--accession", required=True)
    parser.add_argument("--report-date", required=True)
    parser.add_argument("--source-rows-csv", required=True)
    parser.add_argument("--output")
    args = parser.parse_args()

    source_rows = pd.read_csv(args.source_rows_csv, dtype=str).to_dict("records")
    proposal = propose_html_section_bridges(
        cik=args.cik,
        accession_number=args.accession,
        report_date=args.report_date,
        source_rows=source_rows,
    )
    text = json.dumps(proposal, indent=2)
    if args.output:
        Path(args.output).write_text(text + "\n", encoding="utf-8")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
