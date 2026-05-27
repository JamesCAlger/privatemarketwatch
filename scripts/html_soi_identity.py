"""Review-only HTML Schedule of Investments row identity artifacts.

This script reads cached BDC and N-CSR/N-CSRS HTML filings, classifies SOI
rows, and assigns review-layer company and position group identifiers. It does
not edit production CSVs, frontend JSON, schemas, templates, or pipeline code.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pipeline import config
from pipeline.entity_resolution import extract_company_name, normalise_entity_name
from pipeline.html_extract import _extract_tables, _get_cell, load_template
from pipeline.html_soi_evidence import (
    _auto_detect_candidates,
    detect_periods_from_html_text,
    _period_for_table,
    _row_text,
    _template_selection,
    normalize_cik,
    normalize_text,
    score_table_soi,
)

OUTPUT_DIR = Path(".codex_tmp_next/html_soi_identity")

ROW_TAGS = [
    "POSITION_ROW",
    "UNRESOLVED_POSITION_ROW",
    "AGGREGATE_HEADER",
    "SUBTOTAL_ROW",
    "COLUMN_HEADER",
    "CONTINUATION_ROW",
    "COMPARATIVE_PERIOD_ROW",
    "BLANK_ROW",
    "UNCLASSIFIABLE",
]
POSITION_LIKE_ROW_TAGS = {"POSITION_ROW", "UNRESOLVED_POSITION_ROW"}
NON_POSITION_ROW_TAGS = {
    "AGGREGATE_HEADER",
    "SUBTOTAL_ROW",
    "COLUMN_HEADER",
    "CONTINUATION_ROW",
    "COMPARATIVE_PERIOD_ROW",
    "BLANK_ROW",
    "UNCLASSIFIABLE",
}

SUBTOTAL_RE = re.compile(
    r"(?i)^(total\b|sub[\s-]?total\b|subtotal\b|net\s+assets?\b|cash\s+equivalents?\b"
    r"|liabilities\b|members\W?\s*capital\b|partners\W?\s*capital\b"
    r"|stockholders\W?\s*equity\b|shareholders\W?\s*equity\b|net\s+asset\s+value\b)"
    r"|\b(?:sub[\s-]?)?total\s*$"
)
AGGREGATE_RE = re.compile(
    r"(?i)\b(non[-\s]?controlled|non[-\s]?affiliated|controlled|affiliate|first lien|second lien"
    r"|senior secured|subordinated debt|preferred equity|common equity|debt investments"
    r"|equity securities|industry|asset type|investments -)\b"
)
COLUMN_HEADER_RE = re.compile(
    r"(?i)\b(investments?|portfolio company|issuer|borrower|principal|par amount|shares|cost"
    r"|fair value|maturity|interest rate|coupon|spread|percentage of net assets|value)\b"
)
VALUE_RE = re.compile(r"[$(]?\d[\d,]*(?:\.\d+)?%?\)?")
DATE_RE = re.compile(r"\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b")
RATE_RE = re.compile(r"(?i)\b(?:SOFR|LIBOR|S|L|PRIME|BASE|EURIBOR)[A-Z()\s]*\+?\s*\d+(?:\.\d+)?\s*%?")
NUMERIC_LIKE_RE = re.compile(r"^\$?\(?-?\d[\d,]*(?:\.\d+)?%?\)?$")
PCT_CATEGORY_RE = re.compile(r"(?i)^[A-Za-z][A-Za-z0-9 &,/.'()]+(?:-|--|\u2013|\u2014)\s*\d+(?:\.\d+)?\s*%$")
SECURITY_WORD_RE = re.compile(
    r"(?i)\b(term loan|delayed draw|revolver|revolving credit|note|bond|warrant|preferred"
    r"|common stock|class [a-z]|shares?|units?|lp interest|membership interest|equity"
    r"|first lien|second lien|subordinated|senior secured|fund)\b"
)
TRANCHE_SPLIT_RE = re.compile(r"\s+-\s+")
TRAILING_FOOTNOTE_RE = re.compile(r"(?:\s*\(\d+\))+\s*$")
WHITESPACE_RE = re.compile(r"\s+")
SOURCE_CUT_RE = re.compile(r"(?i)\b(?:Reference Rate|Interest Rate|Maturity Date|Variable Index|Rate Cash)\b")
SOURCE_PREFIX_RE = re.compile(
    r"(?i)\b(?:Investments?|non[-\s]?controlled|non[-\s]?affiliated|controlled|affiliated"
    r"|First Lien Debt|Second Lien Debt|Subordinated Debt|Preferred Equity|Common Equity)\b"
)
TOKEN_RE = re.compile(r"[a-z0-9]+")


@dataclass(frozen=True)
class FilingCase:
    source_adapter: str
    cik: str
    entity_name: str
    accession_number: str
    form_type: str
    filing_date: str
    report_date: str
    vehicle_type: str
    html_path: Path


def _norm_key(value: Any) -> str:
    text = normalize_text(value).lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return WHITESPACE_RE.sub(" ", text).strip()


def _hash_id(prefix: str, key: str, length: int = 12) -> str:
    return f"{prefix}-{hashlib.sha1(key.encode('utf-8')).hexdigest()[:length]}"


def _display_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(config.PROJECT_ROOT.resolve())).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/")


def _read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path, dtype=str).fillna("")


def _load_entity_lookup() -> tuple[dict[tuple[str, str], dict[str, str]], dict[str, list[dict[str, str]]]]:
    lookup = _read_csv(config.ENTITY_LOOKUP_FILE)
    exact: dict[tuple[str, str], dict[str, str]] = {}
    norm: dict[str, list[dict[str, str]]] = defaultdict(list)
    if lookup.empty:
        return exact, norm

    for row in lookup.to_dict("records"):
        variant = normalize_text(row.get("issuer_name_variant"))
        source = normalize_text(row.get("source")).lower()
        entity_id = normalize_text(row.get("entity_id"))
        canonical_name = normalize_text(row.get("canonical_name"))
        normalized_name = normalize_text(row.get("normalized_name"))
        if variant and source and entity_id:
            rec = {
                "entity_id": entity_id,
                "canonical_name": canonical_name,
                "issuer_name_variant": variant,
                "source": source,
                "normalized_name": normalized_name,
            }
            exact[(source, variant)] = rec
            if normalized_name:
                norm[normalized_name].append(rec)
    return exact, norm


def _resolve_company(
    issuer: str,
    source_adapter: str,
    exact_lookup: dict[tuple[str, str], dict[str, str]],
    norm_lookup: dict[str, list[dict[str, str]]],
) -> dict[str, str]:
    issuer = normalize_text(issuer)
    if not issuer:
        return {"company_id": "", "canonical_name": "", "company_match_status": "NO_ISSUER", "company_key": ""}

    preferred_sources = ["bdc"] if source_adapter == "bdc" else ["nport", "bdc"]
    for source in preferred_sources:
        rec = exact_lookup.get((source, issuer))
        if rec:
            return {
                "company_id": rec["entity_id"],
                "canonical_name": rec["canonical_name"],
                "company_match_status": f"EXACT_{source.upper()}",
                "company_key": rec["entity_id"],
            }

    extracted = extract_company_name(issuer, "bdc" if source_adapter == "bdc" else "nport")
    normalized = normalise_entity_name(extracted or issuer)
    candidates = norm_lookup.get(normalized, [])
    entity_ids = sorted({c["entity_id"] for c in candidates if c.get("entity_id")})
    if len(entity_ids) == 1:
        rec = next(c for c in candidates if c.get("entity_id") == entity_ids[0])
        return {
            "company_id": rec["entity_id"],
            "canonical_name": rec["canonical_name"],
            "company_match_status": "NORMALIZED_UNIQUE",
            "company_key": rec["entity_id"],
        }
    if len(entity_ids) > 1:
        return {
            "company_id": "",
            "canonical_name": "",
            "company_match_status": "AMBIGUOUS_NORMALIZED",
            "company_key": normalized,
        }
    return {
        "company_id": "",
        "canonical_name": "",
        "company_match_status": "UNRESOLVED",
        "company_key": normalized,
    }


def _parse_number(value: str) -> float | None:
    text = normalize_text(value)
    if not text or text in {"-", "--", "\u2014"}:
        return None
    neg = text.startswith("(") and text.endswith(")")
    text = text.strip("()").replace("$", "").replace(",", "").replace("%", "").strip()
    try:
        val = float(text)
    except ValueError:
        return None
    return -val if neg else val


def _format_source_number(value: Any) -> set[str]:
    parsed = _parse_number(str(value))
    if parsed is None:
        return set()
    candidates: set[str] = set()
    for scaled in [parsed, parsed / 1000.0, parsed / 1_000_000.0]:
        if abs(scaled) < 0.00001:
            continue
        rounded = round(scaled)
        candidates.add(str(int(rounded)))
        candidates.add(f"{int(rounded):,}")
        if abs(scaled - rounded) > 0.001:
            candidates.add(f"{scaled:.2f}".rstrip("0").rstrip("."))
    return {c for c in candidates if len(c.replace(",", "").replace("-", "")) >= 2}


def _source_name_terms(identifier: str) -> list[str]:
    text = normalize_text(identifier)
    if not text:
        return []
    text = SOURCE_CUT_RE.split(text, maxsplit=1)[0]
    text = SOURCE_PREFIX_RE.sub(" ", text)
    text = re.sub(r"(?i)\b[A-Z][A-Za-z &:/]+ Industries\b", " ", text)
    text = WHITESPACE_RE.sub(" ", text).strip(" ,-")
    terms = [text] if len(text) >= 5 else []
    extracted = extract_company_name(text, "bdc")
    if extracted and extracted not in terms:
        terms.append(extracted)
    # Tail fragments often hold the investee after classification prefixes.
    words = text.split()
    for n in [6, 5, 4, 3, 2]:
        if len(words) >= n:
            tail = " ".join(words[-n:])
            if len(tail) >= 5 and tail not in terms:
                terms.append(tail)
    return terms[:6]


def _source_row_key(row: dict[str, Any], idx: int) -> str:
    base = "|".join(
        [
            normalize_cik(row.get("cik")),
            normalize_text(row.get("accession_number")),
            normalize_text(row.get("report_date")),
            normalize_text(row.get("investment_identifier")),
            normalize_text(row.get("fair_value")),
            str(idx),
        ]
    )
    return _hash_id("XBRLROW", base, 16)


def _load_bdc_source_rows(case_keys: set[tuple[str, str, str]] | None = None) -> dict[tuple[str, str, str], list[dict[str, Any]]]:
    df = _read_csv(config.BDC_HOLDINGS_FILE)
    if df.empty:
        return {}
    if case_keys:
        df["cik_norm"] = df["cik"].map(normalize_cik)
        df["_case_key"] = list(zip(df["cik_norm"], df["accession_number"].map(normalize_text), df["report_date"].map(normalize_text)))
        df = df[df["_case_key"].isin(case_keys)].copy()
    out: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for idx, row in enumerate(df.to_dict("records")):
        cik = normalize_cik(row.get("cik"))
        acc = normalize_text(row.get("accession_number"))
        report_date = normalize_text(row.get("report_date"))
        if not cik or not acc or not report_date:
            continue
        rec = dict(row)
        rec["xbrl_source_row_id"] = _source_row_key(rec, idx)
        rec["source_name_terms"] = _source_name_terms(rec.get("investment_identifier", ""))
        rec["source_name_terms_norm"] = [_norm_key(term) for term in rec["source_name_terms"] if _norm_key(term)]
        nums: set[str] = set()
        for field in ["fair_value", "cost", "principal_amount", "pct_of_net_assets"]:
            nums.update(_format_source_number(rec.get(field, "")))
        rec["source_number_terms"] = sorted(nums)
        out[(cik, acc, report_date)].append(rec)
    return out


def _nonblank_indices(row: list[str]) -> list[int]:
    return [i for i, cell in enumerate(row) if normalize_text(cell)]


def _is_column_header(row_text: str, row: list[str]) -> bool:
    text = row_text.lower()
    if not row_text:
        return False
    header_hits = len(COLUMN_HEADER_RE.findall(row_text))
    value_hits = len(VALUE_RE.findall(row_text))
    if header_hits >= 2 and value_hits <= 2:
        return True
    first = normalize_text(row[0] if row else "").lower()
    return first in {"investment", "investments", "portfolio company", "issuer", "borrower"}


def _classify_identity_row(row: list[str], previous_named: bool, period: str, report_date: str) -> tuple[str, str]:
    text = _row_text(row)
    nonempty = [cell for cell in row if normalize_text(cell)]
    if not text:
        return "BLANK_ROW", "blank row"
    if period and report_date and period != report_date:
        return "COMPARATIVE_PERIOD_ROW", "non-current SOI period"
    if _is_column_header(text, row):
        return "COLUMN_HEADER", "column header text"
    if SUBTOTAL_RE.search(text):
        return "SUBTOTAL_ROW", "subtotal or total keyword"
    if len(nonempty) <= 2 and PCT_CATEGORY_RE.search(text):
        return "AGGREGATE_HEADER", "category row with percent-only summary"
    if len(nonempty) <= 2 and AGGREGATE_RE.search(text) and not VALUE_RE.search(text):
        return "AGGREGATE_HEADER", "section header without numeric position values"
    if previous_named and not normalize_text(row[0] if row else "") and VALUE_RE.search(text):
        return "CONTINUATION_ROW", "blank leading identifier with numeric detail"
    if VALUE_RE.search(text) and any(c for c in nonempty if not NUMERIC_LIKE_RE.match(c)):
        return "POSITION_ROW", "numeric row with non-numeric identifier text"
    return "UNCLASSIFIABLE", "row lacks enough position evidence"


def _template_columns(template: dict[str, Any] | None) -> dict[str, int]:
    cols: dict[str, int] = {}
    if not template:
        return cols
    for field, spec in (template.get("columns") or {}).items():
        if isinstance(spec, dict) and "col" in spec:
            try:
                cols[field] = int(spec["col"])
            except (TypeError, ValueError):
                pass
    return cols


def _read_template_field(row: list[str], cols: dict[str, int], field: str) -> str:
    if field not in cols:
        return ""
    return normalize_text(_get_cell(row, cols[field]))


def _split_issuer_and_variant(identifier: str, investment_type: str, source_adapter: str) -> tuple[str, str]:
    ident = normalize_text(identifier)
    investment_type = normalize_text(investment_type)
    if not ident:
        return "", investment_type

    parts = TRANCHE_SPLIT_RE.split(ident, maxsplit=1)
    if len(parts) == 2 and SECURITY_WORD_RE.search(parts[1]):
        issuer = parts[0].strip()
        variant = parts[1].strip()
    else:
        issuer = ident
        variant = investment_type

    issuer = TRAILING_FOOTNOTE_RE.sub("", issuer).strip()
    if not variant:
        if source_adapter == "bdc":
            variant = "BASE_UNLABELED_LOAN"
        else:
            variant = "UNLABELED_SECURITY"
    return issuer, variant


def _infer_generic_fields(row: list[str]) -> dict[str, str]:
    cells = [normalize_text(c) for c in row]
    nonblank = [(i, c) for i, c in enumerate(cells) if c]
    identifier = nonblank[0][1] if nonblank else ""
    row_text = " ".join(c for _, c in nonblank)
    maturity = ""
    reference_spread = ""
    coupon = ""
    for _, cell in nonblank:
        if not maturity and DATE_RE.search(cell):
            maturity = DATE_RE.search(cell).group(0)  # type: ignore[union-attr]
        if not reference_spread and RATE_RE.search(cell):
            reference_spread = RATE_RE.search(cell).group(0)  # type: ignore[union-attr]
        if not coupon and "%" in cell and _parse_number(cell) is not None:
            coupon = cell

    numeric_tail = [c for _, c in nonblank if _parse_number(c) is not None or c in {"-", "\u2014"}]
    fair_value = numeric_tail[-1] if numeric_tail else ""
    cost = numeric_tail[-2] if len(numeric_tail) >= 2 else ""
    principal = numeric_tail[-3] if len(numeric_tail) >= 3 else ""
    investment_type = ""
    for _, cell in nonblank[1:4]:
        if SECURITY_WORD_RE.search(cell) and not VALUE_RE.search(cell):
            investment_type = cell
            break
    return {
        "investment_identifier": identifier,
        "investment_type": investment_type,
        "reference_spread": reference_spread,
        "floor": "",
        "coupon": coupon,
        "maturity": maturity,
        "principal": principal,
        "cost": cost,
        "fair_value": fair_value,
        "pct": "",
        "row_text": row_text,
    }


def _extract_fields(row: list[str], cols: dict[str, int], source_adapter: str) -> dict[str, str]:
    generic = _infer_generic_fields(row)
    if not cols:
        return generic

    investment_identifier = _read_template_field(row, cols, "investment_identifier") or generic["investment_identifier"]
    investment_type = _read_template_field(row, cols, "investment_type") or generic["investment_type"]
    reference_rate = _read_template_field(row, cols, "reference_rate_type")
    basis_spread = _read_template_field(row, cols, "basis_spread")
    reference_spread = " ".join(v for v in [reference_rate, basis_spread] if v).strip() or generic["reference_spread"]
    return {
        "investment_identifier": investment_identifier,
        "investment_type": investment_type,
        "reference_spread": reference_spread,
        "floor": _read_template_field(row, cols, "interest_rate_floor") or generic["floor"],
        "coupon": _read_template_field(row, cols, "interest_rate") or generic["coupon"],
        "maturity": _read_template_field(row, cols, "maturity_date") or generic["maturity"],
        "principal": _read_template_field(row, cols, "principal_amount") or generic["principal"],
        "cost": _read_template_field(row, cols, "cost") or generic["cost"],
        "fair_value": _read_template_field(row, cols, "fair_value") or generic["fair_value"],
        "pct": _read_template_field(row, cols, "pct_of_net_assets") or generic["pct"],
        "row_text": generic["row_text"],
    }


def _match_html_row_to_source(row_text: str, source_rows: list[dict[str, Any]]) -> tuple[list[str], str, str]:
    if not source_rows or not row_text:
        return [], "NO_SOURCE_ROWS", ""
    norm_row = _norm_key(row_text)
    scored: list[tuple[int, str, str]] = []
    for src in source_rows:
        raw_terms = src.get("source_name_terms", [])
        norm_terms = src.get("source_name_terms_norm", [])
        name_hits = [
            raw_terms[i]
            for i, term in enumerate(norm_terms)
            if term and term in norm_row and i < len(raw_terms)
        ]
        number_hits = [term for term in src.get("source_number_terms", []) if term and term in row_text]
        if not name_hits:
            continue
        score = len(name_hits) * 10 + min(len(number_hits), 3) * 2
        if score > 0:
            reason_parts = []
            if name_hits:
                reason_parts.append("name=" + ";".join(name_hits[:2]))
            if number_hits:
                reason_parts.append("number=" + ";".join(number_hits[:3]))
            scored.append((score, str(src["xbrl_source_row_id"]), " ".join(reason_parts)))
    if not scored:
        return [], "NO_MATCH", ""
    scored.sort(key=lambda x: (-x[0], x[1]))
    best_score = scored[0][0]
    best = [item for item in scored if item[0] == best_score]
    status = "MATCHED_XBRL_ROW" if len(best) == 1 else "AMBIGUOUS_XBRL_MATCH"
    return [item[1] for item in best], status, best[0][2]


def _group_key(
    source_adapter: str,
    cik: str,
    company_key: str,
    issuer: str,
    variant: str,
    reference_spread: str,
    floor: str,
    maturity: str,
) -> str:
    company_part = company_key or normalise_entity_name(issuer)
    return "|".join(
        [
            source_adapter,
            normalize_cik(cik),
            _norm_key(company_part),
            _norm_key(variant),
            _norm_key(reference_spread),
            _norm_key(floor),
            _norm_key(maturity),
        ]
    )


def _strict_key(base_key: str, coupon: str, investment_identifier: str) -> str:
    return "|".join([base_key, _norm_key(coupon), _norm_key(investment_identifier)])


def _source_row_hits_in_text(text: str, source_rows: list[dict[str, Any]], *, allow_numeric_only: bool = False) -> set[str]:
    norm_text = _norm_key(text)
    hits: set[str] = set()
    for src in source_rows:
        name_hit = any(term and term in norm_text for term in src.get("source_name_terms_norm", []))
        number_hit = any(term and term in text for term in src.get("source_number_terms", []))
        if name_hit or (allow_numeric_only and number_hit):
            hits.add(str(src["xbrl_source_row_id"]))
    return hits


def _expand_tables_with_bdc_source_rows(
    selected_tables: list[int],
    tables: list[list[list[str]]],
    source_rows: list[dict[str, Any]],
) -> tuple[list[int], str, dict[int, int]]:
    if not source_rows:
        return selected_tables, "no_xbrl_source_rows", {}

    selected = {int(t) for t in selected_tables if 0 <= int(t) < len(tables)}
    table_hits: dict[int, set[str]] = {}
    table_scores: dict[int, int] = {}
    reject_tables: set[int] = set()
    for tidx, table in enumerate(tables):
        table_text = "\n".join(_row_text(row) for row in table)
        hits = _source_row_hits_in_text(table_text, source_rows, allow_numeric_only=False)
        soi_score, _ = score_table_soi(table)
        value_density = sum(1 for row in table for cell in row if VALUE_RE.search(normalize_text(cell)))
        is_financial_statement = bool(
            re.search(r"(?i)(balance sheet|statement of operations|cash flow|cash flows|fair value hierarchy)", table_text[:2000])
        )
        penalty = 30 if is_financial_statement else 0
        if is_financial_statement and len(hits) == 0:
            reject_tables.add(tidx)
        score = soi_score * 3 + len(hits) * 8 + min(value_density, 30) - penalty
        table_hits[tidx] = hits
        table_scores[tidx] = score

    if source_rows:
        selected = {
            tidx for tidx in selected
            if tidx not in reject_tables and (table_hits.get(tidx) or table_scores.get(tidx, 0) >= 12)
        }
    covered = set().union(*(table_hits.get(t, set()) for t in selected)) if selected else set()
    total_source = len({str(r["xbrl_source_row_id"]) for r in source_rows})
    min_gain = 1
    while len(covered) < total_source:
        best_tidx = None
        best_gain = 0
        best_score = -10**9
        for tidx, hits in table_hits.items():
            if tidx in selected:
                continue
            gain = len(hits - covered)
            score = table_scores[tidx]
            if gain > best_gain or (gain == best_gain and score > best_score):
                best_tidx = tidx
                best_gain = gain
                best_score = score
        if best_tidx is None or best_gain < min_gain or best_score < 12:
            break
        selected.add(best_tidx)
        covered.update(table_hits[best_tidx])

    method = f"xbrl_guided_expansion source_rows={total_source} covered_by_selected_tables={len(covered)}"
    return sorted(selected), method, {t: len(h) for t, h in table_hits.items() if h}


def _select_tables(
    case: FilingCase,
    tables: list[list[list[str]]],
    raw_html: str,
    source_rows: list[dict[str, Any]] | None = None,
) -> tuple[list[int], dict[str, list[int]], str, dict[str, Any] | None, dict[int, int]]:
    template = None
    selection_source = "auto_detect"
    xbrl_table_hits: dict[int, int] = {}
    if case.source_adapter == "bdc":
        template = load_template(normalize_cik(case.cik).lstrip("0"))
        template_selection, _ = _template_selection(template, case.accession_number)
        selected_tables = list(template_selection.get("tables") or [])
        table_periods = template_selection.get("table_periods") or {}
        if selected_tables:
            expanded, expansion_method, xbrl_table_hits = _expand_tables_with_bdc_source_rows(selected_tables, tables, source_rows or [])
            if not table_periods:
                table_periods = detect_periods_from_html_text(raw_html, expanded) or {}
            return (
                expanded,
                table_periods,
                f"{template_selection.get('selection_source') or 'template'}+{expansion_method}",
                template,
                xbrl_table_hits,
            )

    auto = _auto_detect_candidates(tables, raw_html, case.report_date, case.form_type)
    selected_tables = list(auto.get("selected_tables") or [])
    table_periods = auto.get("table_periods") or {}
    if case.source_adapter == "bdc":
        selected_tables, expansion_method, xbrl_table_hits = _expand_tables_with_bdc_source_rows(selected_tables, tables, source_rows or [])
        if not table_periods:
            table_periods = detect_periods_from_html_text(raw_html, selected_tables) or {}
        selection_source = f"{selection_source}+{expansion_method}"
    return selected_tables, table_periods, selection_source, template, xbrl_table_hits


def _load_bdc_cases(limit_ciks: int | None, max_filings_per_cik: int | None, only_ciks: set[str]) -> list[FilingCase]:
    df = _read_csv(config.BDC_FILINGS_INDEX_FILE)
    if df.empty:
        return []
    rows: list[FilingCase] = []
    df["cik_norm"] = df["cik"].map(normalize_cik)
    if only_ciks:
        df = df[df["cik_norm"].isin(only_ciks)]
    ciks = sorted(df["cik_norm"].unique())
    if limit_ciks:
        ciks = ciks[:limit_ciks]
    for cik in ciks:
        sub = df[df["cik_norm"] == cik].sort_values(["report_date", "filing_date", "accession_number"])
        sub = sub[
            sub["accession_number"].map(
                lambda acc: (
                    config.BDC_HTML_CACHE_DIR
                    / cik.lstrip("0")
                    / f"{normalize_text(acc).replace('-', '')}.html"
                ).exists()
            )
        ]
        if max_filings_per_cik:
            sub = sub.tail(max_filings_per_cik)
        for row in sub.to_dict("records"):
            acc = normalize_text(row.get("accession_number"))
            html_path = config.BDC_HTML_CACHE_DIR / cik.lstrip("0") / f"{acc.replace('-', '')}.html"
            if not acc or not html_path.exists():
                continue
            rows.append(
                FilingCase(
                    source_adapter="bdc",
                    cik=cik,
                    entity_name=normalize_text(row.get("entity_name")),
                    accession_number=acc,
                    form_type=normalize_text(row.get("form_type")),
                    filing_date=normalize_text(row.get("filing_date")),
                    report_date=normalize_text(row.get("report_date")),
                    vehicle_type="bdc",
                    html_path=html_path,
                )
            )
    return rows


def _load_ncsr_cases(limit_ciks: int | None, max_filings_per_cik: int | None, only_ciks: set[str]) -> list[FilingCase]:
    idx = _read_csv(config.NCSR_FILINGS_INDEX_FILE)
    universe = _read_csv(config.COMBINED_UNIVERSE_FILE)
    if idx.empty or universe.empty:
        return []
    universe["cik_norm"] = universe["cik"].map(normalize_cik)
    vehicles = universe[universe["vehicle_type"].isin(["interval_fund", "tender_offer_fund"])]
    vehicle_map = dict(zip(vehicles["cik_norm"], vehicles["vehicle_type"]))
    idx["cik_norm"] = idx["cik"].map(normalize_cik)
    idx = idx[idx["cik_norm"].isin(vehicle_map)]
    if only_ciks:
        idx = idx[idx["cik_norm"].isin(only_ciks)]
    rows: list[FilingCase] = []
    ciks = sorted(idx["cik_norm"].unique())
    if limit_ciks:
        ciks = ciks[:limit_ciks]
    for cik in ciks:
        sub = idx[idx["cik_norm"] == cik].sort_values(["report_date", "filing_date", "accession_number"])
        sub = sub[
            sub.apply(
                lambda row: (
                    Path(normalize_text(row.get("html_local_path")))
                    if normalize_text(row.get("html_local_path"))
                    else (
                        config.NCSR_HTML_CACHE_DIR
                        / cik.lstrip("0")
                        / f"{normalize_text(row.get('accession_number')).replace('-', '')}.html"
                    )
                ).exists(),
                axis=1,
            )
        ]
        if max_filings_per_cik:
            sub = sub.tail(max_filings_per_cik)
        for row in sub.to_dict("records"):
            html_raw = normalize_text(row.get("html_local_path"))
            html_path = Path(html_raw) if html_raw else (
                config.NCSR_HTML_CACHE_DIR / cik.lstrip("0") / f"{normalize_text(row.get('accession_number')).replace('-', '')}.html"
            )
            if not html_path.exists():
                continue
            rows.append(
                FilingCase(
                    source_adapter="ncsr",
                    cik=cik,
                    entity_name=normalize_text(row.get("entity_name")),
                    accession_number=normalize_text(row.get("accession_number")),
                    form_type=normalize_text(row.get("form_type")),
                    filing_date=normalize_text(row.get("filing_date")),
                    report_date=normalize_text(row.get("report_date")),
                    vehicle_type=vehicle_map.get(cik, ""),
                    html_path=html_path,
                )
            )
    return rows


def _process_cases(
    cases: list[FilingCase],
    exact_lookup: dict[tuple[str, str], dict[str, str]],
    norm_lookup: dict[str, list[dict[str, str]]],
    bdc_source_rows: dict[tuple[str, str, str], list[dict[str, Any]]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    row_tags: list[dict[str, Any]] = []
    exceptions: list[dict[str, Any]] = []
    source_matches: list[dict[str, Any]] = []
    group_seen_periods: dict[str, set[str]] = defaultdict(set)
    period_member_counts: Counter[tuple[str, str]] = Counter()

    for case in cases:
        case_source_rows = bdc_source_rows.get((case.cik, case.accession_number, case.report_date), [])
        source_to_coords: dict[str, list[str]] = defaultdict(list)
        try:
            raw_html = case.html_path.read_text(encoding="utf-8", errors="replace")
            tables = _extract_tables(raw_html)
        except Exception as exc:
            exceptions.append(_exception_bundle(case, "HTML_READ_FAILED", str(exc), []))
            continue

        selected_tables, table_periods, selection_source, template, xbrl_table_hits = _select_tables(
            case,
            tables,
            raw_html,
            case_source_rows,
        )
        cols = _template_columns(template)
        if not selected_tables:
            exceptions.append(_exception_bundle(case, "NO_SOI_TABLE_SELECTED", "No SOI-like table selected.", []))
            continue

        case_candidates: list[dict[str, Any]] = []
        for tidx in selected_tables:
            if tidx < 0 or tidx >= len(tables):
                continue
            period = _period_for_table(tidx, case.report_date, table_periods)
            previous_named = False
            for ridx, row in enumerate(tables[tidx]):
                row_text = _row_text(row)
                row_tag, reason = _classify_identity_row(row, previous_named, period, case.report_date)
                if normalize_text(row[0] if row else ""):
                    previous_named = True
                fields = _extract_fields(row, cols, case.source_adapter)
                issuer, variant = _split_issuer_and_variant(
                    fields.get("investment_identifier", ""),
                    fields.get("investment_type", ""),
                    case.source_adapter,
                )
                company = _resolve_company(issuer, case.source_adapter, exact_lookup, norm_lookup)
                xbrl_ids, xbrl_match_status, xbrl_match_reason = _match_html_row_to_source(row_text, case_source_rows)
                if row_tag in {
                    "AGGREGATE_HEADER",
                    "SUBTOTAL_ROW",
                    "COLUMN_HEADER",
                    "BLANK_ROW",
                    "UNCLASSIFIABLE",
                    "COMPARATIVE_PERIOD_ROW",
                }:
                    xbrl_ids, xbrl_match_status, xbrl_match_reason = [], "NOT_POSITION_ROW", ""
                for xid in xbrl_ids:
                    source_to_coords[xid].append(f"{tidx}:{ridx}")

                position_group_id = ""
                group_key = ""
                strict_key = ""
                position_event = ""
                group_member_index = ""
                if row_tag == "POSITION_ROW" and company["company_match_status"] in {
                    "EXACT_BDC",
                    "EXACT_NPORT",
                    "NORMALIZED_UNIQUE",
                }:
                    group_key = _group_key(
                        case.source_adapter,
                        case.cik,
                        company["company_key"],
                        issuer,
                        variant,
                        fields.get("reference_spread", ""),
                        fields.get("floor", ""),
                        fields.get("maturity", ""),
                    )
                    strict_key = _strict_key(group_key, fields.get("coupon", ""), fields.get("investment_identifier", ""))
                    position_group_id = _hash_id("HTMLPOS", group_key)
                    period_key = (position_group_id, case.report_date)
                    period_member_counts[period_key] += 1
                    group_member_index = str(period_member_counts[period_key])
                    if period_member_counts[period_key] > 1:
                        position_event = "SAME_PERIOD_GROUP_MEMBER"
                    elif group_seen_periods[position_group_id]:
                        position_event = "MATCHED_PRIOR_GROUP"
                    else:
                        position_event = "FIRST_OBSERVED_GROUP"
                    group_seen_periods[position_group_id].add(case.report_date)
                elif row_tag == "POSITION_ROW":
                    row_tag = "UNRESOLVED_POSITION_ROW"

                rec = {
                    "source_adapter": case.source_adapter,
                    "vehicle_type": case.vehicle_type,
                    "cik": case.cik,
                    "entity_name": case.entity_name,
                    "accession_number": case.accession_number,
                    "form_type": case.form_type,
                    "filing_date": case.filing_date,
                    "report_date": case.report_date,
                    "period": period,
                    "html_path": _display_path(case.html_path),
                    "table_selection_source": selection_source,
                    "table_index": tidx,
                    "row_index": ridx,
                    "row_tag": row_tag,
                    "row_reason": reason,
                    "nonblank_cell_indices": "|".join(map(str, _nonblank_indices(row))),
                    "row_text": row_text,
                    "investment_identifier": fields.get("investment_identifier", ""),
                    "issuer": issuer,
                    "instrument_or_variant": variant,
                    "reference_spread": fields.get("reference_spread", ""),
                    "floor": fields.get("floor", ""),
                    "coupon": fields.get("coupon", ""),
                    "maturity": fields.get("maturity", ""),
                    "principal": fields.get("principal", ""),
                    "cost": fields.get("cost", ""),
                    "fair_value": fields.get("fair_value", ""),
                    "pct": fields.get("pct", ""),
                    "company_id": company["company_id"],
                    "canonical_name": company["canonical_name"],
                    "company_match_status": company["company_match_status"],
                    "position_group_id": position_group_id,
                    "position_group_key": group_key,
                    "strict_economic_row_key": strict_key,
                    "position_event": position_event,
                    "group_member_index": group_member_index,
                    "matched_xbrl_row_ids": "|".join(xbrl_ids),
                    "xbrl_match_status": xbrl_match_status,
                    "xbrl_match_reason": xbrl_match_reason,
                    "xbrl_table_hit_count": str(xbrl_table_hits.get(tidx, "")),
                }
                row_tags.append(rec)

                if row_tag in {"UNRESOLVED_POSITION_ROW", "CONTINUATION_ROW", "UNCLASSIFIABLE"}:
                    case_candidates.append(
                        {
                            "table_index": tidx,
                            "row_index": ridx,
                            "cell_indices": _nonblank_indices(row),
                            "row_tag": row_tag,
                            "row_text": row_text[:700],
                            "reason": reason,
                        }
                    )
        if case_candidates:
            exceptions.append(
                _exception_bundle(
                    case,
                    "ROW_REVIEW_REQUIRED",
                    "Rows need company, continuation, or classification review.",
                    case_candidates[:50],
                )
            )
        if case.source_adapter == "bdc":
            missing_rows: list[dict[str, Any]] = []
            for src in case_source_rows:
                xid = str(src["xbrl_source_row_id"])
                coords = source_to_coords.get(xid, [])
                source_matches.append(
                    {
                        "source_adapter": case.source_adapter,
                        "cik": case.cik,
                        "entity_name": case.entity_name,
                        "accession_number": case.accession_number,
                        "report_date": case.report_date,
                        "xbrl_source_row_id": xid,
                        "investment_identifier": normalize_text(src.get("investment_identifier")),
                        "fair_value": normalize_text(src.get("fair_value")),
                        "cost": normalize_text(src.get("cost")),
                        "principal_amount": normalize_text(src.get("principal_amount")),
                        "match_status": "MATCHED_HTML_COORDINATE" if coords else "MISSING_FROM_SELECTED_HTML",
                        "html_coordinates": "|".join(coords[:20]),
                        "source_name_terms": "|".join(src.get("source_name_terms", [])),
                    }
                )
                if not coords:
                    missing_rows.append(
                        {
                            "xbrl_source_row_id": xid,
                            "investment_identifier": normalize_text(src.get("investment_identifier"))[:700],
                            "fair_value": normalize_text(src.get("fair_value")),
                            "source_name_terms": src.get("source_name_terms", [])[:6],
                        }
                    )
            if missing_rows:
                exceptions.append(
                    _exception_bundle(
                        case,
                        "XBRL_ROWS_NOT_FOUND_IN_HTML",
                        "XBRL/source rows did not match selected HTML coordinates after guided expansion.",
                        missing_rows[:50],
                    )
                )

    groups = _build_position_groups(row_tags)
    return row_tags, groups, exceptions, source_matches


def _exception_bundle(case: FilingCase, reason_code: str, reason: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    review_id = _hash_id(
        "HTMLSOI",
        "|".join([case.source_adapter, case.cik, case.accession_number, case.report_date, reason_code]),
        16,
    )
    return {
        "schema_version": "html-soi-identity-review-bundle.v1",
        "review_id": review_id,
        "reason_code": reason_code,
        "reason": reason,
        "source_adapter": case.source_adapter,
        "vehicle_type": case.vehicle_type,
        "cik": case.cik,
        "entity_name": case.entity_name,
        "accession_number": case.accession_number,
        "form_type": case.form_type,
        "filing_date": case.filing_date,
        "report_date": case.report_date,
        "html_path": _display_path(case.html_path),
        "coordinate_rows": rows,
    }


def _build_position_groups(row_tags: list[dict[str, Any]]) -> list[dict[str, Any]]:
    position_rows = [r for r in row_tags if normalize_text(r.get("position_group_id"))]
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in position_rows:
        groups[row["position_group_id"]].append(row)

    out: list[dict[str, Any]] = []
    for gid, rows in sorted(groups.items()):
        periods = sorted({r["report_date"] for r in rows if r.get("report_date")})
        same_period_dupes = sum(
            max(0, n - 1)
            for n in Counter((r["report_date"] for r in rows)).values()
        )
        first = rows[0]
        out.append(
            {
                "position_group_id": gid,
                "source_adapter": first.get("source_adapter", ""),
                "vehicle_type": first.get("vehicle_type", ""),
                "cik": first.get("cik", ""),
                "entity_name": first.get("entity_name", ""),
                "company_id": first.get("company_id", ""),
                "canonical_name": first.get("canonical_name", ""),
                "issuer": first.get("issuer", ""),
                "instrument_or_variant": first.get("instrument_or_variant", ""),
                "reference_spread": first.get("reference_spread", ""),
                "floor": first.get("floor", ""),
                "maturity": first.get("maturity", ""),
                "periods": "|".join(periods),
                "row_count": len(rows),
                "same_period_duplicate_rows": same_period_dupes,
                "sample_coordinates": "|".join(
                    f"{r['accession_number']}:{r['table_index']}:{r['row_index']}" for r in rows[:8]
                ),
            }
        )
    return out


def _build_company_resolution(row_tags: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in row_tags:
        issuer = normalize_text(row.get("issuer"))
        if not issuer:
            continue
        key = (
            normalize_text(row.get("source_adapter")),
            normalize_text(row.get("issuer")),
            normalize_text(row.get("company_id")),
            normalize_text(row.get("company_match_status")),
        )
        grouped[key].append(row)
    out = []
    for (source_adapter, issuer, company_id, status), rows in sorted(grouped.items()):
        out.append(
            {
                "source_adapter": source_adapter,
                "issuer": issuer,
                "company_id": company_id,
                "company_match_status": status,
                "canonical_name": normalize_text(rows[0].get("canonical_name")),
                "row_count": len(rows),
                "sample_ciks": "|".join(sorted({r["cik"] for r in rows})[:5]),
                "sample_coordinates": "|".join(
                    f"{r['accession_number']}:{r['table_index']}:{r['row_index']}" for r in rows[:8]
                ),
            }
        )
    return out


def _load_unified_rows_for_agent_cases(row_tags: list[dict[str, Any]]) -> dict[tuple[str, str], list[dict[str, Any]]]:
    if not config.UNIFIED_HOLDINGS_FILE.exists() or not row_tags:
        return {}

    case_sources: dict[tuple[str, str], set[str]] = defaultdict(set)
    for row in row_tags:
        cik = normalize_cik(row.get("cik"))
        report_date = normalize_text(row.get("report_date"))
        source_adapter = normalize_text(row.get("source_adapter"))
        if not cik or not report_date:
            continue
        if source_adapter == "bdc":
            case_sources[(cik, report_date)].add("bdc")
        elif source_adapter == "ncsr":
            case_sources[(cik, report_date)].update({"nport", "html"})
        else:
            case_sources[(cik, report_date)].add(source_adapter)

    if not case_sources:
        return {}

    ciks = {key[0] for key in case_sources}
    dates = {key[1] for key in case_sources}
    chunks: list[pd.DataFrame] = []
    for chunk in pd.read_csv(config.UNIFIED_HOLDINGS_FILE, dtype=str, chunksize=100_000):
        chunk = chunk.fillna("")
        cik_norm = chunk["cik"].map(normalize_cik)
        report_dates = chunk["report_date"].map(normalize_text)
        mask = cik_norm.isin(ciks) & report_dates.isin(dates)
        if mask.any():
            sub = chunk.loc[mask].copy()
            sub["_cik_norm"] = cik_norm.loc[mask].values
            sub["_report_date_norm"] = report_dates.loc[mask].values
            chunks.append(sub)

    out: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    if not chunks:
        return out
    df = pd.concat(chunks, ignore_index=True)
    for idx, row in enumerate(df.to_dict("records")):
        key = (normalize_cik(row.get("_cik_norm")), normalize_text(row.get("_report_date_norm")))
        allowed_sources = case_sources.get(key, set())
        source = normalize_text(row.get("source")).lower()
        if source not in allowed_sources:
            continue
        rec = dict(row)
        rec["unified_row_id"] = _hash_id(
            "UNIFIEDROW",
            "|".join(
                [
                    normalize_text(rec.get("source")),
                    normalize_cik(rec.get("cik")),
                    normalize_text(rec.get("accession_number")),
                    normalize_text(rec.get("report_date")),
                    normalize_text(rec.get("issuer_name")),
                    normalize_text(rec.get("instrument_description")),
                    normalize_text(rec.get("bdc_investment_identifier")),
                    normalize_text(rec.get("fair_value")),
                    str(idx),
                ]
            ),
            16,
        )
        out[key].append(rec)
    return out


def _token_set(*values: Any) -> set[str]:
    text = _norm_key(" ".join(normalize_text(v) for v in values if normalize_text(v)))
    return {tok for tok in TOKEN_RE.findall(text) if len(tok) >= 3}


def _numeric_close(left: Any, right: Any) -> bool:
    a = _parse_number(normalize_text(left))
    b = _parse_number(normalize_text(right))
    if a is None or b is None:
        return False
    candidates = [b, b * 1000.0, b / 1000.0, b * 1_000_000.0, b / 1_000_000.0]
    tolerance = max(1.0, abs(a) * 0.002)
    return any(abs(a - cand) <= tolerance for cand in candidates)


def _score_unified_html_match(unified: dict[str, Any], html_row: dict[str, Any]) -> tuple[int, str]:
    score = 0
    reasons: list[str] = []

    entity_id = normalize_text(unified.get("entity_id"))
    company_id = normalize_text(html_row.get("company_id"))
    if entity_id and company_id and entity_id == company_id:
        score += 40
        reasons.append("entity_id=company_id")

    unified_name_terms = _token_set(
        unified.get("issuer_name"),
        unified.get("canonical_name"),
        unified.get("bdc_investment_identifier"),
    )
    html_name_terms = _token_set(
        html_row.get("issuer"),
        html_row.get("canonical_name"),
        html_row.get("investment_identifier"),
    )
    name_overlap = unified_name_terms & html_name_terms
    if name_overlap:
        score += min(len(name_overlap), 5) * 5
        reasons.append("name_terms=" + ";".join(sorted(name_overlap)[:5]))

    unified_instr_terms = _token_set(
        unified.get("instrument_description"),
        unified.get("bdc_investment_identifier"),
        unified.get("asset_category"),
        unified.get("lien_position"),
    )
    html_instr_terms = _token_set(
        html_row.get("instrument_or_variant"),
        html_row.get("investment_identifier"),
        html_row.get("row_text"),
    )
    instr_overlap = unified_instr_terms & html_instr_terms
    if instr_overlap:
        score += min(len(instr_overlap), 4) * 4
        reasons.append("instrument_terms=" + ";".join(sorted(instr_overlap)[:4]))

    maturity = normalize_text(unified.get("maturity_date"))
    html_maturity = normalize_text(html_row.get("maturity"))
    if maturity and html_maturity and maturity in html_maturity:
        score += 12
        reasons.append("maturity")

    for unified_field, html_field, label in [
        ("interest_rate", "coupon", "coupon"),
        ("basis_spread", "reference_spread", "spread"),
        ("reference_rate_type", "reference_spread", "reference_rate"),
    ]:
        left = _norm_key(unified.get(unified_field))
        right = _norm_key(html_row.get(html_field))
        if left and right and (left in right or right in left):
            score += 8
            reasons.append(label)

    for unified_field, html_field, label in [
        ("fair_value", "fair_value", "fair_value"),
        ("cost", "cost", "cost"),
        ("principal_amount", "principal", "principal"),
        ("pct_of_net_assets", "pct", "pct"),
    ]:
        if _numeric_close(unified.get(unified_field), html_row.get(html_field)):
            score += 6
            reasons.append(label)

    if not reasons:
        return 0, ""
    return score, " ".join(reasons)


def _build_unified_html_comparison(
    row_tags: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    unified_by_case = _load_unified_rows_for_agent_cases(row_tags)
    html_by_case: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    cases: dict[tuple[str, str], dict[str, str]] = {}
    for row in row_tags:
        cik = normalize_cik(row.get("cik"))
        report_date = normalize_text(row.get("report_date"))
        if not cik or not report_date:
            continue
        key = (cik, report_date)
        cases.setdefault(
            key,
            {
                "source_adapter": normalize_text(row.get("source_adapter")),
                "vehicle_type": normalize_text(row.get("vehicle_type")),
                "cik": cik,
                "entity_name": normalize_text(row.get("entity_name")),
                "report_date": report_date,
                "accession_number": normalize_text(row.get("accession_number")),
            },
        )
        if normalize_text(row.get("row_tag")) in POSITION_LIKE_ROW_TAGS:
            html_by_case[key].append(row)

    match_rows: list[dict[str, Any]] = []
    summary_rows: list[dict[str, Any]] = []
    for key in sorted(cases):
        case = cases[key]
        unified_rows = unified_by_case.get(key, [])
        html_rows = html_by_case.get(key, [])
        matched_html_units: set[str] = set()
        matched_unified = 0
        ambiguous_unified = 0
        missing_unified = 0

        if not unified_rows:
            status = "UNSUPPORTED_SOURCE_OR_DATE"
            for html in html_rows:
                match_rows.append(_comparison_record(case, None, html, status, 0, "no exact unified rows for CIK/report_date/source"))
            summary_rows.append(
                {
                    **case,
                    "unified_row_count": 0,
                    "html_position_like_row_count": len(html_rows),
                    "matched_unified_count": 0,
                    "ambiguous_unified_count": 0,
                    "missing_unified_count": 0,
                    "html_extra_position_like_count": len(html_rows),
                    "unsupported_case": "1",
                }
            )
            continue

        for unified in unified_rows:
            scored: list[tuple[int, str, dict[str, Any]]] = []
            for html in html_rows:
                html_unit = _html_match_unit(html)
                if html_unit in matched_html_units:
                    continue
                score, reason = _score_unified_html_match(unified, html)
                if score >= 35:
                    scored.append((score, reason, html))
            scored.sort(
                key=lambda item: (
                    -item[0],
                    normalize_text(item[2].get("table_index")),
                    normalize_text(item[2].get("row_index")),
                )
            )
            if not scored:
                missing_unified += 1
                match_rows.append(_comparison_record(case, unified, None, "MISSING_HTML_COORDINATE", 0, "no HTML position-like row met match threshold"))
                continue
            best_score = scored[0][0]
            best = [item for item in scored if item[0] == best_score]
            if len(best) > 1:
                ambiguous_unified += 1
                for score, reason, html in best[:10]:
                    match_rows.append(_comparison_record(case, unified, html, "AMBIGUOUS_MULTIPLE_HTML", score, reason))
                continue

            score, reason, html = best[0]
            gid = normalize_text(html.get("position_group_id"))
            status = "MATCHED_HTML_GROUP" if gid else "MATCHED_HTML_ROW"
            matched_unified += 1
            matched_html_units.add(_html_match_unit(html))
            match_rows.append(_comparison_record(case, unified, html, status, score, reason))

        html_extra = 0
        for html in html_rows:
            if _html_match_unit(html) in matched_html_units:
                continue
            html_extra += 1
            match_rows.append(_comparison_record(case, None, html, "HTML_EXTRA_POSITION_ROW", 0, "HTML position-like row not selected by any unified row"))

        summary_rows.append(
            {
                **case,
                "unified_row_count": len(unified_rows),
                "html_position_like_row_count": len(html_rows),
                "matched_unified_count": matched_unified,
                "ambiguous_unified_count": ambiguous_unified,
                "missing_unified_count": missing_unified,
                "html_extra_position_like_count": html_extra,
                "unsupported_case": "0",
            }
        )
    return match_rows, summary_rows


def _html_match_unit(html: dict[str, Any]) -> str:
    gid = normalize_text(html.get("position_group_id"))
    if gid:
        return "group|" + gid
    return "|".join(
        [
            "row",
            normalize_text(html.get("accession_number")),
            normalize_text(html.get("table_index")),
            normalize_text(html.get("row_index")),
        ]
    )


def _comparison_record(
    case: dict[str, str],
    unified: dict[str, Any] | None,
    html: dict[str, Any] | None,
    status: str,
    score: int,
    reason: str,
) -> dict[str, Any]:
    unified = unified or {}
    html = html or {}
    return {
        "comparison_status": status,
        "score": score,
        "reason": reason,
        "source_adapter": case.get("source_adapter", ""),
        "vehicle_type": case.get("vehicle_type", ""),
        "cik": case.get("cik", ""),
        "entity_name": case.get("entity_name", ""),
        "report_date": case.get("report_date", ""),
        "unified_row_id": unified.get("unified_row_id", ""),
        "unified_source": unified.get("source", ""),
        "unified_accession_number": unified.get("accession_number", ""),
        "unified_position_id": unified.get("position_id", ""),
        "unified_entity_id": unified.get("entity_id", ""),
        "unified_issuer_name": unified.get("issuer_name", ""),
        "unified_instrument_description": unified.get("instrument_description", ""),
        "unified_bdc_investment_identifier": unified.get("bdc_investment_identifier", ""),
        "unified_maturity_date": unified.get("maturity_date", ""),
        "unified_interest_rate": unified.get("interest_rate", ""),
        "unified_basis_spread": unified.get("basis_spread", ""),
        "unified_reference_rate_type": unified.get("reference_rate_type", ""),
        "unified_principal_amount": unified.get("principal_amount", ""),
        "unified_cost": unified.get("cost", ""),
        "unified_fair_value": unified.get("fair_value", ""),
        "unified_pct_of_net_assets": unified.get("pct_of_net_assets", ""),
        "html_accession_number": html.get("accession_number", ""),
        "html_path": html.get("html_path", ""),
        "html_table_index": html.get("table_index", ""),
        "html_row_index": html.get("row_index", ""),
        "html_cell_indices": html.get("nonblank_cell_indices", ""),
        "html_row_tag": html.get("row_tag", ""),
        "html_company_id": html.get("company_id", ""),
        "html_position_group_id": html.get("position_group_id", ""),
        "html_issuer": html.get("issuer", ""),
        "html_instrument_or_variant": html.get("instrument_or_variant", ""),
        "html_investment_identifier": html.get("investment_identifier", ""),
        "html_maturity": html.get("maturity", ""),
        "html_coupon": html.get("coupon", ""),
        "html_reference_spread": html.get("reference_spread", ""),
        "html_principal": html.get("principal", ""),
        "html_cost": html.get("cost", ""),
        "html_fair_value": html.get("fair_value", ""),
        "html_pct": html.get("pct", ""),
        "html_row_text": html.get("row_text", ""),
    }


def _write_unified_comparison_outputs(
    output_dir: Path,
    row_tags: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    output_dir.mkdir(parents=True, exist_ok=True)
    match_rows, summary_rows = _build_unified_html_comparison(row_tags)
    pd.DataFrame(match_rows).to_csv(output_dir / "html_soi_unified_matches.csv", index=False)
    pd.DataFrame(summary_rows).to_csv(output_dir / "html_soi_unified_summary.csv", index=False)

    lines = [
        "# HTML SOI vs Unified Holdings Comparison",
        "",
        "Review-only comparison of agent-tagged HTML SOI rows against private_markets_holdings.csv.",
        "",
        "## Cases",
    ]
    for row in summary_rows:
        lines.append(
            "- {cik} {report_date}: unified={unified_row_count} html_position_like={html_position_like_row_count} "
            "matched={matched_unified_count} ambiguous={ambiguous_unified_count} missing={missing_unified_count} "
            "html_extra={html_extra_position_like_count} unsupported={unsupported_case}".format(**row)
        )
    lines.extend(
        [
            "",
            "## Outputs",
            "- `html_soi_unified_matches.csv`",
            "- `html_soi_unified_summary.csv`",
        ]
    )
    (output_dir / "html_soi_unified_residuals.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return match_rows, summary_rows


def _write_outputs(
    output_dir: Path,
    row_tags: list[dict[str, Any]],
    groups: list[dict[str, Any]],
    exceptions: list[dict[str, Any]],
    cases: list[FilingCase],
    source_matches: list[dict[str, Any]],
    unified_match_rows: list[dict[str, Any]] | None = None,
    unified_summary_rows: list[dict[str, Any]] | None = None,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    bundles_dir = output_dir / "html_soi_review_bundles"
    for name in [
        "html_soi_row_tags.csv",
        "html_soi_position_groups.csv",
        "html_soi_company_resolution.csv",
        "html_soi_source_matches.csv",
        "html_soi_unified_matches.csv",
        "html_soi_unified_summary.csv",
        "html_soi_unified_residuals.md",
        "summary.json",
        "summary.md",
    ]:
        path = output_dir / name
        if path.exists():
            path.unlink()
    if bundles_dir.exists():
        for path in bundles_dir.glob("*.json"):
            path.unlink()
    bundles_dir.mkdir(parents=True, exist_ok=True)

    pd.DataFrame(row_tags).to_csv(output_dir / "html_soi_row_tags.csv", index=False)
    pd.DataFrame(groups).to_csv(output_dir / "html_soi_position_groups.csv", index=False)
    pd.DataFrame(_build_company_resolution(row_tags)).to_csv(output_dir / "html_soi_company_resolution.csv", index=False)
    pd.DataFrame(source_matches).to_csv(output_dir / "html_soi_source_matches.csv", index=False)
    if unified_match_rows is None or unified_summary_rows is None:
        unified_match_rows, unified_summary_rows = _write_unified_comparison_outputs(output_dir, row_tags)
    else:
        pd.DataFrame(unified_match_rows).to_csv(output_dir / "html_soi_unified_matches.csv", index=False)
        pd.DataFrame(unified_summary_rows).to_csv(output_dir / "html_soi_unified_summary.csv", index=False)

    for bundle in exceptions:
        (bundles_dir / f"{bundle['review_id']}.json").write_text(
            json.dumps(bundle, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    counts = Counter((r.get("source_adapter", ""), r.get("row_tag", "")) for r in row_tags)
    source_match_counts = Counter(r.get("match_status", "") for r in source_matches)
    summary = {
        "artifact": "html-soi-identity.v1",
        "case_count": len(cases),
        "row_count": len(row_tags),
        "position_group_count": len(groups),
        "review_bundle_count": len(exceptions),
        "counts_by_source_and_tag": {f"{k[0]}|{k[1]}": v for k, v in sorted(counts.items())},
        "bdc_source_row_count": len(source_matches),
        "bdc_source_match_counts": dict(sorted(source_match_counts.items())),
        "outputs": {
            "row_tags": str(output_dir / "html_soi_row_tags.csv"),
            "position_groups": str(output_dir / "html_soi_position_groups.csv"),
            "company_resolution": str(output_dir / "html_soi_company_resolution.csv"),
            "source_matches": str(output_dir / "html_soi_source_matches.csv"),
            "unified_matches": str(output_dir / "html_soi_unified_matches.csv"),
            "unified_summary": str(output_dir / "html_soi_unified_summary.csv"),
            "review_bundles": str(bundles_dir),
        },
    }
    (output_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

    lines = [
        "# HTML SOI Identity Review Artifacts",
        "",
        "Review-only artifacts. No production CSV, frontend JSON, schema, template, or pipeline output is changed.",
        "",
        f"- Filings processed: {len(cases)}",
        f"- HTML rows tagged: {len(row_tags)}",
        f"- Position groups: {len(groups)}",
        f"- Review bundles: {len(exceptions)}",
        f"- BDC source rows checked: {len(source_matches)}",
        "",
        "## Row Counts",
    ]
    for key, value in sorted(counts.items()):
        lines.append(f"- {key[0]} {key[1]}: {value}")
    lines.append("")
    lines.append("## BDC Source Match Counts")
    for key, value in sorted(source_match_counts.items()):
        lines.append(f"- {key}: {value}")
    lines.extend(
        [
            "",
            "## Outputs",
            "- `html_soi_row_tags.csv`",
            "- `html_soi_position_groups.csv`",
            "- `html_soi_company_resolution.csv`",
            "- `html_soi_source_matches.csv`",
            "- `html_soi_unified_matches.csv`",
            "- `html_soi_unified_summary.csv`",
            "- `html_soi_review_bundles/*.json`",
        ]
    )
    (output_dir / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _validate_outputs(row_tags: list[dict[str, Any]], groups: list[dict[str, Any]]) -> list[str]:
    errors: list[str] = []
    for i, row in enumerate(row_tags):
        for col in ["source_adapter", "cik", "accession_number", "table_index", "row_index", "row_tag"]:
            if normalize_text(row.get(col)) == "":
                errors.append(f"row {i} missing {col}")
        if row.get("row_tag") not in ROW_TAGS:
            errors.append(f"row {i} has invalid row_tag {row.get('row_tag')}")
        if row.get("row_tag") in {"AGGREGATE_HEADER", "SUBTOTAL_ROW", "COLUMN_HEADER"} and row.get("position_group_id"):
            errors.append(f"row {i} non-position row has position_group_id")
    group_ciks: dict[str, set[str]] = defaultdict(set)
    for row in row_tags:
        gid = normalize_text(row.get("position_group_id"))
        if gid:
            group_ciks[gid].add(normalize_text(row.get("cik")))
    for gid, ciks in group_ciks.items():
        if len(ciks) > 1:
            errors.append(f"{gid} spans multiple CIKs: {sorted(ciks)}")
    group_ids = {g["position_group_id"] for g in groups}
    for gid in group_ciks:
        if gid not in group_ids:
            errors.append(f"{gid} missing from position group output")
    return errors


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    parser.add_argument("--source", choices=["all", "bdc", "ncsr"], default="all")
    parser.add_argument("--cik", action="append", default=[], help="Limit to one or more CIKs.")
    parser.add_argument("--limit-ciks", type=int, default=None)
    parser.add_argument("--max-filings-per-cik", type=int, default=2)
    parser.add_argument(
        "--compare-unified-only",
        action="store_true",
        help="Read existing html_soi_row_tags.csv and write only unified-vs-HTML comparison artifacts.",
    )
    parser.add_argument("--skip-unified-comparison", action="store_true")
    parser.add_argument("--no-validate", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.compare_unified_only:
        row_tags_path = args.output_dir / "html_soi_row_tags.csv"
        row_tags_df = _read_csv(row_tags_path)
        if row_tags_df.empty:
            print(f"No row tags found at {row_tags_path}")
            return 1
        match_rows, summary_rows = _write_unified_comparison_outputs(args.output_dir, row_tags_df.to_dict("records"))
        print(f"Wrote unified comparison artifacts to {args.output_dir}")
        print(f"Comparison rows: {len(match_rows)}")
        print(f"Comparison cases: {len(summary_rows)}")
        return 0

    only_ciks = {normalize_cik(cik) for cik in args.cik if normalize_cik(cik)}
    exact_lookup, norm_lookup = _load_entity_lookup()

    cases: list[FilingCase] = []
    if args.source in {"all", "bdc"}:
        cases.extend(_load_bdc_cases(args.limit_ciks, args.max_filings_per_cik, only_ciks))
    if args.source in {"all", "ncsr"}:
        cases.extend(_load_ncsr_cases(args.limit_ciks, args.max_filings_per_cik, only_ciks))
    cases = sorted(cases, key=lambda c: (c.source_adapter, c.cik, c.report_date, c.accession_number))
    bdc_case_keys = {
        (case.cik, case.accession_number, case.report_date)
        for case in cases
        if case.source_adapter == "bdc"
    }
    bdc_source_rows = _load_bdc_source_rows(bdc_case_keys)

    row_tags, groups, exceptions, source_matches = _process_cases(cases, exact_lookup, norm_lookup, bdc_source_rows)
    errors = [] if args.no_validate else _validate_outputs(row_tags, groups)
    if errors:
        for err in errors[:50]:
            print(f"VALIDATION_ERROR: {err}")
        print(f"Validation failed with {len(errors)} errors.")
        return 1

    unified_match_rows = None
    unified_summary_rows = None
    if args.skip_unified_comparison:
        unified_match_rows = []
        unified_summary_rows = []
    _write_outputs(
        args.output_dir,
        row_tags,
        groups,
        exceptions,
        cases,
        source_matches,
        unified_match_rows,
        unified_summary_rows,
    )
    print(f"Wrote HTML SOI identity artifacts to {args.output_dir}")
    print(f"Filings processed: {len(cases)}")
    print(f"Rows tagged: {len(row_tags)}")
    print(f"Position groups: {len(groups)}")
    print(f"Review bundles: {len(exceptions)}")
    print(f"BDC source rows checked: {len(source_matches)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
