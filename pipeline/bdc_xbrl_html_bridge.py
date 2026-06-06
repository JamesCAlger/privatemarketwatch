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
    "permit_overwrite",
]

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


def _section_for_row(row: list[str]) -> tuple[str, str] | None:
    cells = [_norm_text(cell) for cell in row if _norm_text(cell)]
    if len(cells) != 1:
        return None
    text = cells[0]
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
