"""Cached HTML Schedule of Investments evidence for BDC review bundles.

This module is intentionally read-only. It parses cached filing HTML in memory
and reuses the low-level HTML table parser, but does not call the production
HTML extraction workflow or write learned grid/template files.
"""

from __future__ import annotations

import hashlib
import html as html_mod
import re
from bisect import bisect_right
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

from pipeline import config
from pipeline.html_extract import _extract_tables, load_template

HTML_EVIDENCE_IDS = {
    "html_artifact",
    "html_template_selection",
    "html_detected_soi_candidates",
    "html_table_grid_excerpt",
    "html_period_assignment",
    "html_row_classification_candidates",
    "html_source_row_coordinate_candidates",
    "xbrl_rows_same_accession",
}

ROW_CLASSIFICATIONS = {
    "POSITION_ROW",
    "AGGREGATE_HEADER",
    "SUBTOTAL_ROW",
    "CONTINUATION_ROW",
    "COMPARATIVE_PERIOD_ROW",
    "UNCLASSIFIABLE",
    "INSUFFICIENT_EVIDENCE",
}

HTML_RULE_TYPES = {
    "table_selection",
    "period_assignment",
    "row_classification",
    "continuation_row_merge",
    "aggregate_subtotal_exclusion",
}

_SOI_KEYWORDS_HIGH = {
    "fair value",
    "cost",
    "principal",
    "amortized cost",
    "schedule of investments",
}
_SOI_KEYWORDS_MED = {
    "maturity",
    "portfolio company",
    "issuer",
    "borrower",
    "company",
    "shares",
    "industry",
    "rate",
    "spread",
    "coupon",
    "par amount",
    "par value",
    "investment type",
    "investment",
}
_SOI_KEYWORDS_NEG = {
    "total return",
    "page",
    "item 1",
    "table of contents",
    "per share",
    "balance sheet",
    "statement of operations",
    "financial highlights",
    "selected financial",
    "roll forward",
    "fair value hierarchy",
}

_MONTH_NAMES = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}
_PERIOD_DATE_RE = re.compile(
    r"(?:" + "|".join(_MONTH_NAMES) + r")[\s\xa0]+(\d{1,2})\s*,?\s*(\d{4})",
    re.IGNORECASE,
)
_SOI_RE = re.compile(r"schedule\s+of\s+investments", re.IGNORECASE)
_TABLE_OPEN_RE = re.compile(r"<table[\s>]", re.IGNORECASE)
_HTML_TAG_RE = re.compile(r"<[^>]+>")
_SUBTOTAL_RE = re.compile(
    r"(?i)^(total\b|sub[\s-]?total\b|subtotal\b|net\s+assets?\b|cash\s+equivalents?\b|liabilities\b"
    r"|members\W?\s*capital\b|partners\W?\s*capital\b|stockholders\W?\s*equity\b"
    r"|shareholders\W?\s*equity\b|net\s+asset\s+value\b)|\b(?:sub[\s-]?)?total\s*$"
)
_AGGREGATE_HEADER_RE = re.compile(
    r"(?i)\b(non[-\s]?controlled|non[-\s]?affiliated|controlled|affiliate|first lien|second lien|senior secured|equity investments|debt investments|industry|asset type)\b"
)
_GENERIC_ISSUER_RE = re.compile(r"(?i)^(portfolio company|investment|issuer|borrower|company|total|subtotal)$")
_VALUE_RE = re.compile(r"[$(]?\d[\d,]*(?:\.\d+)?%?\)?")
_TOKEN_RE = re.compile(r"[a-z0-9]+")
_GENERIC_TERM_RE = re.compile(
    r"(?i)\b(?:investments?|debt|equity|instrument|ref|floor|spread|total|coupon|maturity|date|"
    r"first|second|lien|term|loan|delayed|draw|revolver|revolving|sofr|libor|cash|pik|"
    r"non[-\s]?controlled|non[-\s]?affiliated|controlled|affiliated|industry|fair|value|cost)\b"
)


def normalize_text(value: Any) -> str:
    if value is None:
        return ""
    text = str(value)
    return "" if text.lower() == "nan" else text.strip()


def normalize_cik(value: Any) -> str:
    digits = re.sub(r"\D", "", normalize_text(value))
    return digits.zfill(10) if digits else ""


def _display_path(path: Path) -> str:
    try:
        return str(path.relative_to(config.PROJECT_ROOT)).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/")


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _evidence_item(evidence_id: str, description: str, data: Any) -> dict[str, Any]:
    return {"evidence_id": evidence_id, "description": description, "data": data}


def score_table_soi(grid: list[list[str]], min_rows: int = 5) -> tuple[int, int]:
    """Score a table grid for Schedule of Investments likelihood."""
    if not grid or len(grid) < min_rows:
        return (0, 0)

    width = len(grid[0]) if grid else 0
    best_score = 0
    best_hr = 0
    for hr in range(min(3, len(grid))):
        hdr_text = " ".join(c.lower() for c in grid[hr] if c.strip())
        if not hdr_text:
            continue
        score = 0
        score += sum(4 for kw in _SOI_KEYWORDS_HIGH if kw in hdr_text)
        score += sum(2 for kw in _SOI_KEYWORDS_MED if kw in hdr_text)
        score -= sum(5 for kw in _SOI_KEYWORDS_NEG if kw in hdr_text)
        if len(grid) >= 15:
            score += 5
        if len(grid) >= 50:
            score += 5
        if width >= 8:
            score += 3
        if score > best_score:
            best_score = score
            best_hr = hr
    return (best_score, best_hr)


def group_continuation_tables(scored_tables: list[tuple[int, int, int, int]]) -> list[list[int]]:
    """Group scored tables into likely SOI continuation chains."""
    if not scored_tables:
        return []
    sorted_tables = sorted(scored_tables, key=lambda x: x[0])
    groups: list[list[int]] = []
    current_group = [sorted_tables[0][0]]
    current_width = sorted_tables[0][2]
    for i in range(1, len(sorted_tables)):
        tidx, _, width, _ = sorted_tables[i]
        prev_tidx = sorted_tables[i - 1][0]
        if abs(width - current_width) <= 6 and tidx - prev_tidx <= 5:
            current_group.append(tidx)
        else:
            groups.append(current_group)
            current_group = [tidx]
            current_width = width
    groups.append(current_group)
    return groups


def parse_period_date(text: str) -> str | None:
    m = _PERIOD_DATE_RE.search(text)
    if not m:
        return None
    month_name = m.group(0).split()[0].lower().rstrip(",")
    month = _MONTH_NAMES.get(month_name)
    if not month:
        return None
    day = int(m.group(1))
    year = int(m.group(2))
    if year < 2000 or year > 2030 or day < 1 or day > 31:
        return None
    return f"{year:04d}-{month:02d}-{day:02d}"


def find_soi_date_markers(raw_html: str) -> list[tuple[int, str]]:
    table_positions = [m.start() for m in _TABLE_OPEN_RE.finditer(raw_html)]
    if not table_positions:
        return []

    markers: list[tuple[int, str]] = []
    for soi_m in _SOI_RE.finditer(raw_html):
        window_raw = raw_html[soi_m.end() : soi_m.end() + 500]
        window_text = html_mod.unescape(_HTML_TAG_RE.sub(" ", window_raw))
        date = parse_period_date(window_text)
        if date:
            markers.append((bisect_right(table_positions, soi_m.start()), date))
    return markers


def detect_periods_from_html_text(raw_html: str, soi_table_indices: list[int]) -> dict[str, list[int]] | None:
    if not soi_table_indices or len(soi_table_indices) < 2:
        return None
    markers = find_soi_date_markers(raw_html)
    if not markers:
        return None

    seen_tidx: dict[int, str] = {}
    for tidx, date in markers:
        seen_tidx.setdefault(tidx, date)
    date_markers = sorted(seen_tidx.items())
    if len({date for _, date in date_markers}) < 2:
        return None

    periods: dict[str, list[int]] = {}
    for tidx in sorted(soi_table_indices):
        assigned_date = None
        for marker_tidx, marker_date in date_markers:
            if marker_tidx <= tidx:
                assigned_date = marker_date
            else:
                break
        assigned_date = assigned_date or date_markers[0][1]
        periods.setdefault(assigned_date, []).append(tidx)
    return periods if len(periods) >= 2 else None


def detect_10k_periods(table_groups: list[list[int]], report_date: str) -> dict[str, list[int]] | None:
    if len(table_groups) != 2 or not report_date or len(report_date) < 10:
        return None
    group1, group2 = table_groups
    if not group1 or not group2 or group2[0] - group1[-1] < 10:
        return None
    try:
        comp_date = f"{int(report_date[:4]) - 1}-{report_date[5:]}"
    except (ValueError, IndexError):
        return None
    return {report_date: group1, comp_date: group2}


def _html_source_config(source: str) -> tuple[Path, Path, tuple[str, ...], str] | None:
    source_norm = normalize_text(source).lower()
    if source_norm == "bdc":
        return (
            config.BDC_HTML_CACHE_DIR,
            config.BDC_FILINGS_INDEX_FILE,
            ("10-K", "10-K/A", "10-Q", "10-Q/A"),
            "BDC",
        )
    if source_norm in {"ncsr", "nport", "interval", "interval_source"}:
        return (
            config.NCSR_HTML_CACHE_DIR,
            config.NCSR_FILINGS_INDEX_FILE,
            ("N-CSR", "N-CSRS", "N-CSR/A", "N-CSRS/A"),
            "N-CSR",
        )
    return None


def _html_path(source: str, cik: str, accession: str) -> Path:
    source_config = _html_source_config(source)
    cache_dir = source_config[0] if source_config else config.BDC_HTML_CACHE_DIR
    return cache_dir / normalize_cik(cik).lstrip("0") / f"{accession.replace('-', '')}.html"


def _load_filing_meta(source: str, cik: str, accession: str, report_date: str) -> dict[str, str]:
    meta = {
        "cik": normalize_cik(cik),
        "accession_number": accession,
        "report_date": report_date,
        "form_type": "",
        "filing_date": "",
        "entity_name": "",
    }
    source_config = _html_source_config(source)
    path = source_config[1] if source_config else config.BDC_FILINGS_INDEX_FILE
    if not path.exists():
        return meta
    try:
        df = pd.read_csv(path, dtype=str).fillna("")
    except Exception:
        return meta
    mask = df.get("cik", pd.Series(dtype=str)).astype(str).map(normalize_cik).eq(normalize_cik(cik))
    if accession:
        mask &= df.get("accession_number", pd.Series(dtype=str)).astype(str).eq(accession)
    elif report_date and "report_date" in df.columns:
        mask &= df["report_date"].astype(str).eq(report_date)
    if not mask.any():
        return meta
    row = df[mask].iloc[0].to_dict()
    for key in meta:
        value = normalize_text(row.get(key))
        if value:
            meta[key] = normalize_cik(value) if key == "cik" else value
    return meta


def _template_selection(template: dict[str, Any] | None, accession: str) -> tuple[dict[str, Any], bool]:
    if not template:
        return ({"available": False, "selection_source": "none", "tables": [], "table_periods": {}}, False)
    filings = template.get("filings", {}) if isinstance(template.get("filings"), dict) else {}
    filing_spec = filings.get(accession, {}) or filings.get(accession.replace("-", ""), {})
    has_accession_selection = bool(filing_spec.get("tables") or filing_spec.get("table_periods"))
    default_spec = template.get("default", {}) if isinstance(template.get("default"), dict) else {}
    tables = filing_spec.get("tables", default_spec.get("tables", template.get("tables", [])))
    table_periods = filing_spec.get("table_periods", default_spec.get("table_periods", {}))
    return (
        {
            "available": bool(tables or table_periods),
            "selection_source": "accession_template" if has_accession_selection else "default_template",
            "tables": tables or [],
            "table_periods": table_periods or {},
        },
        has_accession_selection,
    )


def _auto_detect_candidates(tables: list[list[list[str]]], raw_html: str, report_date: str, form_type: str) -> dict[str, Any]:
    scored: list[tuple[int, int, int, int]] = []
    for tidx, grid in enumerate(tables):
        score, header_row = score_table_soi(grid)
        if score >= 8:
            scored.append((tidx, score, len(grid[0]) if grid else 0, header_row))
    high_scored = [item for item in scored if item[1] >= 10]
    groups = group_continuation_tables(high_scored)
    selected_groups: list[list[int]] = []
    if groups:
        group_info = sorted(
            groups,
            key=lambda g: (-len(g), g[0]),
        )
        if "10-K" in form_type and len(group_info) >= 2:
            selected_groups = sorted(group_info[:2], key=lambda g: g[0])
        else:
            selected_groups = [group_info[0]]
    selected_tables = [tidx for group in selected_groups for tidx in group]
    table_periods = detect_periods_from_html_text(raw_html, selected_tables)
    method = "html" if table_periods else ""
    if table_periods is None and "10-K" in form_type and len(selected_groups) == 2:
        table_periods = detect_10k_periods(selected_groups, report_date)
        method = "gap" if table_periods else ""
    return {
        "candidate_type": "auto_detect_fallback",
        "selected_tables": selected_tables,
        "groups": selected_groups,
        "table_periods": table_periods or {},
        "period_method": method,
        "scored_tables": [
            {"table_index": t, "score": s, "width": w, "header_row": h}
            for t, s, w, h in sorted(scored, key=lambda x: (-x[1], x[0]))[:20]
        ],
    }


def _period_for_table(table_index: int, report_date: str, table_periods: dict[str, list[int]]) -> str:
    for period, indices in table_periods.items():
        if table_index in {int(i) for i in indices}:
            return period
    return report_date


def _row_text(row: list[str]) -> str:
    return " ".join(cell for cell in row if normalize_text(cell))


def _norm_key(value: Any) -> str:
    text = normalize_text(value).lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _classify_row(row: list[str], previous_named: bool, period: str, report_date: str) -> tuple[list[str], str]:
    text = _row_text(row)
    nonempty = [cell for cell in row if normalize_text(cell)]
    labels: list[str] = []
    reason = ""
    if period and report_date and period != report_date:
        labels.append("COMPARATIVE_PERIOD_ROW")
    if not text:
        labels.append("UNCLASSIFIABLE")
        return labels, "blank row"
    if len(nonempty) <= 2 and _AGGREGATE_HEADER_RE.search(text) and not _VALUE_RE.search(text):
        labels.append("AGGREGATE_HEADER")
        reason = "section-like text without numeric position values"
    if _SUBTOTAL_RE.search(text):
        labels.append("SUBTOTAL_ROW")
        reason = "subtotal or total keyword"
    if previous_named and not normalize_text(row[0] if row else "") and _VALUE_RE.search(text):
        labels.append("CONTINUATION_ROW")
        reason = "blank leading identifier with numeric detail"
    if not labels and _VALUE_RE.search(text):
        labels.append("POSITION_ROW")
    if not labels:
        labels.append("UNCLASSIFIABLE")
    return labels, reason or "heuristic row classification"


def _source_row_search_terms(source_row: dict[str, Any]) -> list[str]:
    raw = normalize_text(
        source_row.get("raw_investment_identifier")
        or source_row.get("investment_identifier")
        or source_row.get("normalized_investment_identifier")
    )
    normalized = normalize_text(source_row.get("normalized_investment_identifier"))
    terms: list[str] = []

    entity_match = re.search(
        r"([A-Z][A-Za-z0-9&.,()' -]+?\b(?:Inc\.?|LLC|Ltd\.?|Corporation|Corp\.?|"
        r"Company|Co\.?|Holdings|Buyer|Partners|Technologies|Brands|SASU))\s+Instrument\b",
        raw,
    )
    if entity_match:
        entity_candidate = entity_match.group(1).strip()
        terms.append(entity_candidate)
        entity_words = entity_candidate.split()
        for n in [5, 4, 3, 2]:
            if len(entity_words) >= n:
                terms.append(" ".join(entity_words[-n:]))

    for text in [raw, normalized]:
        prefix_trimmed = re.split(r"(?i)\b(?:Reference Rate|Interest Rate|Maturity Date|Initial Acquisition Date)\b", text, maxsplit=1)[0]
        if prefix_trimmed and prefix_trimmed != text:
            terms.append(prefix_trimmed.strip(" ,-"))
            prefix_words = prefix_trimmed.split()
            for n in [6, 5, 4, 3, 2]:
                if len(prefix_words) >= n:
                    tail = " ".join(prefix_words[-n:])
                    tail = _GENERIC_TERM_RE.sub(" ", tail)
                    tail = re.sub(r"\s+", " ", tail).strip(" ,-")
                    if len(tail) >= 5:
                        terms.append(tail)
        cleaned = _GENERIC_TERM_RE.sub(" ", text)
        cleaned = re.sub(r"\s+", " ", cleaned).strip(" ,-")
        if len(cleaned) >= 5:
            terms.append(cleaned)

    # Many BDC typed members are "category industry issuer Instrument ...".
    instrument_split = re.split(r"(?i)\bInstrument\b", raw, maxsplit=1)[0]
    words = instrument_split.split()
    for n in [8, 7, 6, 5, 4, 3, 2]:
        if len(words) >= n:
            tail = " ".join(words[-n:])
            tail = _GENERIC_TERM_RE.sub(" ", tail)
            tail = re.sub(r"\s+", " ", tail).strip(" ,-")
            if len(tail) >= 5:
                terms.append(tail)

    deduped: list[str] = []
    for term in terms:
        key = _norm_key(term)
        alpha_tokens = [tok for tok in _TOKEN_RE.findall(key) if re.search(r"[a-z]", tok)]
        if key and len(alpha_tokens) >= 2 and key not in {_norm_key(t) for t in deduped}:
            deduped.append(term)
    return deduped[:8]


def _source_row_coordinate_candidates(
    tables: list[list[list[str]]],
    *,
    source_rows: Iterable[dict[str, Any]],
    selected_tables: list[int],
    table_periods: dict[str, list[int]],
    report_date: str,
    table_scores: dict[int, tuple[int, int]],
    max_rows: int,
) -> list[dict[str, Any]]:
    selected = {int(t) for t in selected_tables if str(t).strip().isdigit() or isinstance(t, int)}
    out: list[dict[str, Any]] = []
    for source_idx, source_row in enumerate(source_rows):
        if len(out) >= max_rows:
            break
        terms = _source_row_search_terms(source_row)
        if not terms:
            continue
        term_keys = [(term, _norm_key(term)) for term in terms if len(_norm_key(term)) >= 5]
        source_id = normalize_text(source_row.get("source_row_id") or source_row.get("classification_id") or source_idx)
        hits_for_source = 0
        for tidx, table in enumerate(tables):
            if len(out) >= max_rows or hits_for_source >= 8:
                break
            period = _period_for_table(tidx, report_date, table_periods)
            previous_named = False
            for ridx, row in enumerate(table):
                row_text = _row_text(row)
                row_key = _norm_key(row_text)
                matched_terms = [term for term, term_key in term_keys if term_key and term_key in row_key]
                if not matched_terms:
                    if normalize_text(row[0] if row else ""):
                        previous_named = True
                    continue
                labels, reason = _classify_row(row, previous_named, period, report_date)
                score, header_row = table_scores.get(tidx, (0, 0))
                out.append(
                    {
                        "source_row_id": source_id,
                        "raw_investment_identifier": normalize_text(source_row.get("raw_investment_identifier") or source_row.get("investment_identifier"))[:700],
                        "source_fair_value": normalize_text(source_row.get("source_fair_value")) or normalize_text(source_row.get("fair_value")),
                        "table_index": tidx,
                        "row_index": ridx,
                        "cell_indices": [i for i, cell in enumerate(row) if normalize_text(cell)],
                        "row_text": row_text[:900],
                        "matched_terms": matched_terms[:5],
                        "selected_by_template_or_detector": tidx in selected,
                        "table_soi_score": score,
                        "table_header_row": header_row,
                        "period": period,
                        "classification_candidates": labels,
                        "reason": reason,
                    }
                )
                hits_for_source += 1
                break
                # One row per table is enough for a source row coordinate candidate.
            # Preserve continuation state within the loop above.
    return out


def _compact_grid_rows(
    tables: list[list[list[str]]],
    selected_tables: list[int],
    table_periods: dict[str, list[int]],
    report_date: str,
    search_terms: Iterable[str],
    max_rows: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    terms = [normalize_text(term).lower() for term in search_terms if len(normalize_text(term)) >= 3]
    excerpts: list[dict[str, Any]] = []
    candidates: list[dict[str, Any]] = []
    for tidx in selected_tables:
        if tidx < 0 or tidx >= len(tables):
            continue
        table = tables[tidx]
        period = _period_for_table(tidx, report_date, table_periods)
        header_context = _row_text(table[0])[:500] if table else ""
        previous_named = False
        for ridx, row in enumerate(table):
            row_text = _row_text(row)
            labels, reason = _classify_row(row, previous_named, period, report_date)
            if normalize_text(row[0] if row else ""):
                previous_named = True
            matched_term = any(term in row_text.lower() for term in terms)
            matched_generic = bool(_GENERIC_ISSUER_RE.search(row_text))
            matched_value = bool(_VALUE_RE.search(row_text))
            classification_candidate = any(label != "POSITION_ROW" for label in labels)
            include = ridx <= 2 or matched_term or matched_generic or classification_candidate
            if include and len(excerpts) < max_rows:
                excerpts.extend(
                    {
                        "table_index": tidx,
                        "row_index": ridx,
                        "cell_index": cidx,
                        "text": normalize_text(cell)[:300],
                        "header_context": header_context,
                        "period": period,
                    }
                    for cidx, cell in enumerate(row)
                    if normalize_text(cell)
                )
            if (matched_term or matched_generic or matched_value or classification_candidate) and len(candidates) < max_rows:
                candidates.append(
                    {
                        "table_index": tidx,
                        "row_index": ridx,
                        "cell_indices": [i for i, cell in enumerate(row) if normalize_text(cell)],
                        "row_text": row_text[:700],
                        "period": period,
                        "classification_candidates": labels,
                        "reason": reason,
                    }
                )
    return excerpts[: max_rows * 12], candidates


def build_html_soi_evidence(
    *,
    source: str,
    cik: str,
    report_date: str,
    accession: str = "",
    form_type: str = "",
    residual_names: Iterable[str] = (),
    fair_values: Iterable[Any] = (),
    source_identifiers: Iterable[str] = (),
    source_rows: Iterable[dict[str, Any]] = (),
    xbrl_rows_same_accession: Iterable[dict[str, Any]] = (),
    allow_html_download: bool = False,
    max_rows: int = 40,
) -> list[dict[str, Any]]:
    """Build shared cached-HTML evidence items for a filing accession."""
    source_config = _html_source_config(source)
    if source_config is None:
        return []
    _, _, doc_types, source_label = source_config

    acc = normalize_text(accession)
    if not acc:
        return [
            _evidence_item(
                "html_artifact",
                f"Cached {source_label} HTML filing could not be selected because no accession number was available.",
                {
                    "status": "missing_accession",
                    "cik": normalize_cik(cik),
                    "report_date": report_date,
                    "accession_number": "",
                },
            )
        ]

    meta = _load_filing_meta(source, cik, acc, report_date)
    if form_type:
        meta["form_type"] = form_type
    html_path = _html_path(source, cik, acc)
    if not html_path.exists():
        if allow_html_download:
            try:
                from pipeline.edgar_client import EdgarClient

                client = EdgarClient()
                url = client.resolve_filing_document_url(
                    normalize_cik(cik),
                    acc,
                    doc_types=doc_types,
                )
                if url:
                    client.download_file(url, html_path)
            except Exception:
                pass
        if html_path.exists():
            # Continue into normal cached parsing path after opt-in download.
            pass
        else:
            status = "missing_cached_html_download_allowed" if allow_html_download else "missing_cached_html"
            return [
                _evidence_item(
                    "html_artifact",
                    f"Cached {source_label} HTML filing was not found; download was attempted only when explicitly allowed.",
                    {
                        "status": status,
                        "path": _display_path(html_path),
                        "sha256": "",
                        **meta,
                    },
                )
            ]

    raw_html = html_path.read_text(encoding="utf-8", errors="replace")
    tables = _extract_tables(raw_html)
    template = load_template(normalize_cik(cik).lstrip("0"))
    template_selection, has_accession_template = _template_selection(template, acc)
    auto_candidates = _auto_detect_candidates(tables, raw_html, report_date, meta.get("form_type", ""))

    selected_tables = list(template_selection.get("tables") or auto_candidates.get("selected_tables") or [])
    table_periods = template_selection.get("table_periods") or auto_candidates.get("table_periods") or {}
    table_scores = {tidx: score_table_soi(grid) for tidx, grid in enumerate(tables)}
    search_terms = list(residual_names) + [str(v) for v in fair_values] + list(source_identifiers)
    excerpts, row_candidates = _compact_grid_rows(tables, selected_tables, table_periods, report_date, search_terms, max_rows)
    source_coordinate_candidates = _source_row_coordinate_candidates(
        tables,
        source_rows=source_rows,
        selected_tables=selected_tables,
        table_periods=table_periods,
        report_date=report_date,
        table_scores=table_scores,
        max_rows=max_rows,
    )

    evidence = [
        _evidence_item(
            "html_artifact",
            f"Cached {source_label} HTML filing artifact used for coordinate-level review evidence.",
            {
                "status": "available",
                "path": _display_path(html_path),
                "sha256": _sha256_file(html_path),
                "table_count": len(tables),
                **meta,
            },
        ),
        _evidence_item(
            "html_template_selection",
            "Audited template-selected SOI tables and table_periods when available.",
            template_selection,
        ),
    ]
    if not has_accession_template:
        evidence.append(
            _evidence_item(
                "html_detected_soi_candidates",
                "Auto-detected SOI table candidates. This is fallback candidate evidence, not audited template evidence.",
                auto_candidates,
            )
        )
    evidence.extend(
        [
            _evidence_item(
                "html_table_grid_excerpt",
                "Compact table grid cells around headers, residual names, identifiers, values, and row-classification candidates.",
                excerpts,
            ),
            _evidence_item(
                "html_period_assignment",
                "Period labels assigned to selected HTML table indices.",
                {
                    "source": template_selection.get("selection_source") if table_periods == template_selection.get("table_periods") else auto_candidates.get("period_method", "fallback"),
                    "report_date": report_date,
                    "table_periods": table_periods,
                },
            ),
            _evidence_item(
                "html_row_classification_candidates",
                "Coordinate-level row classification candidates. Verdicts must cite table_index, row_index, and cell_indices.",
                row_candidates,
            ),
            _evidence_item(
                "html_source_row_coordinate_candidates",
                "Source-row-targeted HTML coordinate candidates searched across all filing tables. selected_by_template_or_detector=false means the row appears outside the current parsed SOI table set.",
                source_coordinate_candidates,
            ),
            _evidence_item(
                "xbrl_rows_same_accession",
                "XBRL/raw BDC rows from the same accession. XBRL remains numeric source of truth unless separately reconciled.",
                list(xbrl_rows_same_accession)[:max_rows],
            ),
        ]
    )
    return evidence


def resolve_accessions_from_rows(rows: Iterable[dict[str, Any]]) -> list[str]:
    accessions: list[str] = []
    for row in rows:
        for key in ("accession_number", "source_accession", "sample_accessions"):
            value = normalize_text(row.get(key))
            if not value:
                continue
            for part in re.split(r"[|,;\s]+", value):
                part = normalize_text(part)
                if part and part.lower() != "nan" and part not in accessions:
                    accessions.append(part)
    return accessions
