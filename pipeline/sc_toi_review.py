"""Review-only harness for SC TO-I tender-offer parser residuals.

This module builds deterministic worklists and evidence bundles for filings
that the SC TO-I extractor did not fully capture. It does not write production
SC TO-I result files and does not download SEC data.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import jsonschema

from pipeline import config

REVIEW_DIR = config.OUTPUT_DIR / "sc_toi_review"
SCHEMA_FILE = config.PROJECT_ROOT / "schemas" / "sc_toi_review" / "verdict.schema.json"
PROMPT_TEMPLATE = config.PROJECT_ROOT / "prompts" / "sc_toi_review_prompt.md"

KEY_FIELDS = [
    "shares_tendered",
    "shares_accepted",
    "repurchase_price_per_share",
    "offer_expiration_date",
]

TRIAGE_DETAIL_COLUMNS = [
    "accession_number",
    "cik",
    "entity_name",
    "form_type",
    "filing_date",
    "primary_document",
    "source_status",
    "category",
    "offer_role_hint",
    "offer_role_basis",
    "third_party_rule_14d1_state",
    "issuer_rule_13e4_state",
    "subject_company_hint",
    "offeror_hint",
    "role_snippet",
    "checkbox_state",
    "has_final_heading",
    "has_result_terms",
    "missing_fields",
    "template_signature",
    "html_local_path",
    "snippet",
]

WORKLIST_COLUMNS = [
    "review_id",
    "cik",
    "entity_name",
    "category",
    "template_signature",
    "offer_role_hint",
    "form_type_family",
    "packet_index",
    "packet_count",
    "group_total_issue_count",
    "issue_count",
    "progress_statuses",
    "form_types",
    "filing_date_min",
    "filing_date_max",
    "sample_accessions",
    "sample_primary_documents",
    "missing_fields",
    "checkbox_states",
    "has_final_heading_count",
    "has_result_terms_count",
    "recommended_action",
    "confidence",
]

BUNDLE_MANIFEST_COLUMNS = ["review_id", "bundle_path", "bundle_sha256"]
FILING_ROLE_TAG_COLUMNS = [
    "review_id",
    "accession_number",
    "cik",
    "category",
    "offer_role_tag",
    "confidence",
    "evidence_refs",
    "subject_company",
    "offeror",
    "notes",
]

PROTECTED_GENERATED_PATH_PREFIXES = [
    "frontend/public/data/",
]
PROTECTED_GENERATED_PATHS = {
    "data/output/sc_toi_repurchase_results.csv",
    "data/output/sc_toi_parse_progress.csv",
    "data/output/sc_toi_filings_index.csv",
}

INCLUDED_REVIEW_CATEGORIES = {
    "likely_final_results_missed",
    "checkbox_present_unclassified_state",
    "final_heading_but_no_result_terms",
    "no_final_checkbox_language",
    "partial_parse",
    "result_missing_fields",
    "missing_html",
}

RESULT_TERM_RE = re.compile(
    r"validly tendered|were tendered and not withdrawn|was tendered and not withdrawn|"
    r"purchased all|repurchased all|accepted for purchase|accepted for repurchase|"
    r"aggregate purchase price",
    re.I,
)

FINAL_CHECKBOX_RE = re.compile(
    r"final\s+amendment\s+reporting\s+the\s+results\s+of\s+the\s+tender\s+offer"
    r".{0,800}",
    re.I | re.S,
)

CHECKED_RE = re.compile(
    r"&#9746;|&#120;|&#254;|&thorn;|☒|\[x\]|"
    r"wingdings[^\r\n]{0,160}(?:x|þ)|>x<|>þ<",
    re.I,
)

UNCHECKED_RE = re.compile(
    r"&#9744;|&#9633;|&#168;|&uml;|☐|\[__\]",
    re.I,
)


RULE_14D1_RE = re.compile(r"third-party\s+tender\s+offer\s+subject\s+to\s+rule\s+14d-1", re.I)
RULE_13E4_RE = re.compile(r"issuer\s+tender\s+offer\s+subject\s+to\s+rule\s+13e-4", re.I)
CHECKBOX_TOKEN_RE = re.compile(
    r"(?P<checked>&#9746;|&#120;|&#254;|&thorn;|â˜’|\[x\]|>x<|>Ã¾<)|"
    r"(?P<unchecked>&#9744;|&#9633;|&#168;|&uml;|â˜|\[__\])",
    re.I,
)


class ScToiReviewError(RuntimeError):
    """Raised when SC TO-I review inputs or outputs fail closed."""


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def normalize_text(value: Any) -> str:
    if value is None:
        return ""
    text = str(value)
    return "" if text.lower() == "nan" else text.strip()


def normalize_cik(value: Any) -> str:
    digits = re.sub(r"\D", "", normalize_text(value))
    return digits.zfill(10) if digits else ""


def short_hash(value: str, length: int = 10) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:length]


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def display_path(path: Path) -> str:
    try:
        return str(path.relative_to(config.PROJECT_ROOT)).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/")


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        raise ScToiReviewError(f"Missing required CSV: {path}")
    with path.open(newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def write_csv_rows(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    ensure_dir(path.parent)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fieldnames})


def _stable_join(values: Iterable[Any], limit: int = 12) -> str:
    out: list[str] = []
    for value in values:
        text = normalize_text(value)
        if text and text not in out:
            out.append(text)
        if len(out) >= limit:
            break
    return " | ".join(out)


def _compact_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _html_to_text(html: str) -> str:
    try:
        from bs4 import BeautifulSoup

        return BeautifulSoup(html, "html.parser").get_text(" ", strip=True)
    except Exception:
        return re.sub(r"<[^>]+>", " ", html)


def _read_html(path: str) -> str:
    if not path:
        return ""
    p = Path(path)
    if not p.exists():
        return ""
    return p.read_text(encoding="utf-8", errors="replace")


def checkbox_state(html: str) -> str:
    """Return checked, unchecked, unknown, or absent for the final-amendment box."""
    match = FINAL_CHECKBOX_RE.search(html)
    if not match:
        return "absent"
    snippet = match.group(0)
    if CHECKED_RE.search(snippet):
        return "checked"
    if UNCHECKED_RE.search(snippet):
        return "unchecked"
    return "unknown"


def _checkbox_option_state(html: str, option_re: re.Pattern[str]) -> str:
    """Return the nearest checkbox state for a Schedule TO option line."""
    option = option_re.search(html)
    if not option:
        return "absent"
    window_start = max(0, option.start() - 260)
    window_end = min(len(html), option.end() + 80)
    window = html[window_start:window_end]
    option_offset = option.start() - window_start
    tokens: list[tuple[int, str]] = []
    for token in CHECKBOX_TOKEN_RE.finditer(window):
        state = "checked" if token.group("checked") else "unchecked"
        tokens.append((abs(token.start() - option_offset), state))
    if not tokens:
        return "unknown"
    tokens.sort(key=lambda item: item[0])
    return tokens[0][1]


def form_type_family(form_type: str) -> str:
    form = normalize_text(form_type).upper()
    if "TO-T" in form:
        return "SC_TO_T"
    if "TO-I" in form:
        return "SC_TO_I"
    return "UNKNOWN_FORM"


def _extract_offeror_hint(text: str) -> str:
    patterns = [
        r"offer\s+by\s*:?\s+(.{2,120}?)(?:\s+\(|\s+to\s+purchase|\s+has\s+received)",
        r"offer\s+by\s+(.{2,120}?)(?:,?\s+the\s+\"?(?:company|purchasers?)\"?)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.I)
        if match:
            return _compact_text(match.group(1))[:160]
    return ""


def _extract_subject_company_hint(text: str) -> str:
    patterns = [
        r"(?:shares|units)[^.]{0,160}?\s+(?:of|in)\s+(.{2,140}?)(?:,\s+the\s+subject\s+company|\s+\(the\s+\"?(?:corporation|partnership|company|issuer))",
        r"(.{2,140}?)\s+\(Name\s+of\s+Subject\s+Company",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.I)
        if match:
            return _compact_text(match.group(1))[:160]
    return ""


def _role_snippet(html: str, text: str) -> str:
    for pattern in [RULE_14D1_RE, RULE_13E4_RE, re.compile(r"offer\s+by", re.I)]:
        match = pattern.search(html) or pattern.search(text)
        if match:
            source = html if pattern.search(html) else text
            start = max(0, match.start() - 220)
            end = min(len(source), match.end() + 420)
            return _compact_text(_html_to_text(source[start:end]))[:700]
    return ""


def classify_offer_role(html: str, form_type: str = "") -> dict[str, str]:
    if not html:
        return {
            "offer_role_hint": "missing_html",
            "offer_role_basis": "missing_html",
            "third_party_rule_14d1_state": "absent",
            "issuer_rule_13e4_state": "absent",
            "subject_company_hint": "",
            "offeror_hint": "",
            "role_snippet": "",
        }
    text = _html_to_text(html)
    third_state = _checkbox_option_state(html, RULE_14D1_RE)
    issuer_state = _checkbox_option_state(html, RULE_13E4_RE)
    form_family = form_type_family(form_type)
    role = "unknown_role"
    basis = "ambiguous_or_missing_role_evidence"
    if third_state == "checked" and issuer_state != "checked":
        role = "third_party_tender"
        basis = "checked_rule_14d1"
    elif issuer_state == "checked" and third_state != "checked":
        role = "issuer_self_tender"
        basis = "checked_rule_13e4"
    elif third_state == "checked" and issuer_state == "checked":
        role = "unknown_role"
        basis = "conflicting_checked_rules"
    elif form_family == "SC_TO_T":
        role = "third_party_tender"
        basis = "form_type_fallback"
    elif form_family == "SC_TO_I":
        role = "issuer_self_tender"
        basis = "form_type_fallback"
    return {
        "offer_role_hint": role,
        "offer_role_basis": basis,
        "third_party_rule_14d1_state": third_state,
        "issuer_rule_13e4_state": issuer_state,
        "subject_company_hint": _extract_subject_company_hint(text),
        "offeror_hint": _extract_offeror_hint(text),
        "role_snippet": _role_snippet(html, text),
    }


def filing_snippet(html: str, text: str) -> str:
    checkbox = FINAL_CHECKBOX_RE.search(html)
    if checkbox:
        return _compact_text(_html_to_text(checkbox.group(0)))[:700]
    result = RESULT_TERM_RE.search(text)
    if result:
        start = max(0, result.start() - 260)
        end = min(len(text), result.end() + 440)
        return _compact_text(text[start:end])[:700]
    final = re.search(r"final amendment to tender offer statement", text, re.I)
    if final:
        start = max(0, final.start() - 200)
        end = min(len(text), final.end() + 500)
        return _compact_text(text[start:end])[:700]
    return _compact_text(text[:700])


def template_signature(category: str, snippet: str, primary_document: str = "") -> str:
    """Build a stable, rough template signature for grouping repeated misses."""
    seed = _compact_text(snippet.lower())
    seed = re.sub(r"\$?\d[\d,]*(?:\.\d+)?", "#", seed)
    seed = re.sub(
        r"\b(?:january|february|march|april|may|june|july|august|september|"
        r"october|november|december)\b",
        "month",
        seed,
    )
    doc_hint = re.sub(r"[^a-z0-9]+", "_", normalize_text(primary_document).lower()).strip("_")[:24]
    return short_hash("|".join([category, doc_hint, seed[:500]]), 12)


def classify_no_data_filing(html: str) -> dict[str, Any]:
    text = _html_to_text(html)
    lower = text.lower()
    state = checkbox_state(html)
    has_final_heading = "final amendment to tender offer statement" in lower
    has_result_terms = RESULT_TERM_RE.search(text) is not None
    if not html:
        category = "missing_html"
    elif state == "checked" or (has_final_heading and has_result_terms):
        category = "likely_final_results_missed"
    elif has_final_heading:
        category = "final_heading_but_no_result_terms"
    elif state == "unchecked":
        category = "unchecked_original_or_intermediate"
    elif state == "unknown":
        category = "checkbox_present_unclassified_state"
    else:
        category = "no_final_checkbox_language"
    return {
        "category": category,
        "checkbox_state": state,
        "has_final_heading": has_final_heading,
        "has_result_terms": has_result_terms,
        "snippet": filing_snippet(html, text),
    }


def make_review_id(cik: str, category: str, signature: str) -> str:
    cat_slug = re.sub(r"[^A-Za-z0-9]+", "_", category).strip("_").upper()[:36]
    digest = short_hash("|".join([normalize_cik(cik), category, signature]), 10)
    return f"SCTOI_{normalize_cik(cik)}_{cat_slug}_{digest}"


def review_group_signature(row: dict[str, Any]) -> str:
    """Return the grouping signature used for bounded review packets."""
    category = normalize_text(row.get("category"))
    if category == "result_missing_fields":
        missing = normalize_text(row.get("missing_fields"))
        return re.sub(r"[^A-Za-z0-9|_]+", "_", missing).strip("_")[:80] or category
    return category


def _packet_signature(row: dict[str, Any]) -> str:
    parts = [
        review_group_signature(row),
        normalize_text(row.get("offer_role_hint")) or "unknown_role",
        form_type_family(normalize_text(row.get("form_type"))),
    ]
    return "|".join(parts)


def _chunk_rows(rows: list[dict[str, Any]], size: int) -> list[list[dict[str, Any]]]:
    if size <= 0:
        return [rows]
    return [rows[i : i + size] for i in range(0, len(rows), size)]


def _index_by_accession(rows: list[dict[str, str]]) -> dict[str, dict[str, str]]:
    return {normalize_text(row.get("accession_number")): row for row in rows if normalize_text(row.get("accession_number"))}


def _missing_fields(row: dict[str, str]) -> list[str]:
    return [field for field in KEY_FIELDS if not normalize_text(row.get(field))]


def build_triage_rows(
    *,
    filings_index_path: Path = config.SC_TOI_FILINGS_INDEX_FILE,
    progress_path: Path = config.SC_TOI_PARSE_PROGRESS_FILE,
    results_path: Path = config.SC_TOI_RESULTS_FILE,
) -> list[dict[str, Any]]:
    index_rows = read_csv_rows(filings_index_path)
    progress_rows = read_csv_rows(progress_path)
    result_rows = read_csv_rows(results_path) if results_path.exists() else []
    index_by_acc = _index_by_accession(index_rows)

    triage: list[dict[str, Any]] = []
    for progress in progress_rows:
        status = normalize_text(progress.get("status"))
        if status not in {"no_data", "partial", "no_html"}:
            continue
        accession = normalize_text(progress.get("accession_number"))
        index = index_by_acc.get(accession, {})
        html_path = normalize_text(index.get("html_local_path"))
        html = _read_html(html_path)
        role = classify_offer_role(html, normalize_text(index.get("form_type")))
        if status == "no_data":
            info = classify_no_data_filing(html)
        elif status == "partial":
            text = _html_to_text(html)
            info = {
                "category": "partial_parse",
                "checkbox_state": checkbox_state(html),
                "has_final_heading": "final amendment to tender offer statement" in text.lower(),
                "has_result_terms": RESULT_TERM_RE.search(text) is not None,
                "snippet": filing_snippet(html, text),
            }
        else:
            info = {
                "category": "missing_html",
                "checkbox_state": "absent",
                "has_final_heading": False,
                "has_result_terms": False,
                "snippet": "",
            }
        signature = template_signature(
            str(info["category"]),
            str(info["snippet"]),
            normalize_text(index.get("primary_document")),
        )
        triage.append(
            {
                "accession_number": accession,
                "cik": normalize_cik(index.get("cik")),
                "entity_name": normalize_text(index.get("entity_name")),
                "form_type": normalize_text(index.get("form_type")),
                "filing_date": normalize_text(index.get("filing_date")),
                "primary_document": normalize_text(index.get("primary_document")),
                "source_status": status,
                "category": info["category"],
                "offer_role_hint": role["offer_role_hint"],
                "offer_role_basis": role["offer_role_basis"],
                "third_party_rule_14d1_state": role["third_party_rule_14d1_state"],
                "issuer_rule_13e4_state": role["issuer_rule_13e4_state"],
                "subject_company_hint": role["subject_company_hint"],
                "offeror_hint": role["offeror_hint"],
                "role_snippet": role["role_snippet"],
                "checkbox_state": info["checkbox_state"],
                "has_final_heading": str(bool(info["has_final_heading"])),
                "has_result_terms": str(bool(info["has_result_terms"])),
                "missing_fields": "",
                "template_signature": signature,
                "html_local_path": html_path,
                "snippet": info["snippet"],
            }
        )

    for result in result_rows:
        missing = _missing_fields(result)
        if not missing:
            continue
        accession = normalize_text(result.get("accession_number"))
        index = index_by_acc.get(accession, {})
        html_path = normalize_text(index.get("html_local_path"))
        html = _read_html(html_path)
        role = classify_offer_role(html, normalize_text(result.get("form_type") or index.get("form_type")))
        text = _html_to_text(html)
        snippet = filing_snippet(html, text)
        signature = template_signature("result_missing_fields", snippet, normalize_text(index.get("primary_document")))
        triage.append(
            {
                "accession_number": accession,
                "cik": normalize_cik(result.get("cik") or index.get("cik")),
                "entity_name": normalize_text(result.get("entity_name") or index.get("entity_name")),
                "form_type": normalize_text(result.get("form_type") or index.get("form_type")),
                "filing_date": normalize_text(result.get("filing_date") or index.get("filing_date")),
                "primary_document": normalize_text(index.get("primary_document")),
                "source_status": "result_missing_fields",
                "category": "result_missing_fields",
                "offer_role_hint": role["offer_role_hint"],
                "offer_role_basis": role["offer_role_basis"],
                "third_party_rule_14d1_state": role["third_party_rule_14d1_state"],
                "issuer_rule_13e4_state": role["issuer_rule_13e4_state"],
                "subject_company_hint": role["subject_company_hint"],
                "offeror_hint": role["offeror_hint"],
                "role_snippet": role["role_snippet"],
                "checkbox_state": checkbox_state(html),
                "has_final_heading": str("final amendment to tender offer statement" in text.lower()),
                "has_result_terms": str(RESULT_TERM_RE.search(text) is not None),
                "missing_fields": " | ".join(missing),
                "template_signature": signature,
                "html_local_path": html_path,
                "snippet": snippet,
            }
        )

    return triage


def _recommended_action(category: str) -> tuple[str, str]:
    if category == "likely_final_results_missed":
        return ("Review result language and propose a generalized parser pattern.", "HIGH")
    if category == "checkbox_present_unclassified_state":
        return ("Decode checkbox state or classify the filing structure.", "MEDIUM")
    if category == "result_missing_fields":
        return ("Identify missing field language and propose a generalized parser pattern.", "HIGH")
    if category == "partial_parse":
        return ("Determine why parser emitted partial results and identify missing fields.", "HIGH")
    if category == "missing_html":
        return ("Resolve missing cached HTML or document as unavailable.", "LOW")
    return ("Review as legacy or unusual structure before parser changes.", "MEDIUM")


def build_worklist(
    *,
    filings_index_path: Path = config.SC_TOI_FILINGS_INDEX_FILE,
    progress_path: Path = config.SC_TOI_PARSE_PROGRESS_FILE,
    results_path: Path = config.SC_TOI_RESULTS_FILE,
    output_dir: Path = REVIEW_DIR,
    top_n: int = 0,
    max_records_per_packet: int = 12,
) -> dict[str, Any]:
    triage = build_triage_rows(
        filings_index_path=filings_index_path,
        progress_path=progress_path,
        results_path=results_path,
    )
    ensure_dir(output_dir)
    write_csv_rows(output_dir / "triage_detail.csv", triage, TRIAGE_DETAIL_COLUMNS)

    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in triage:
        if row["category"] not in INCLUDED_REVIEW_CATEGORIES:
            continue
        grouped[(row["cik"], row["category"], _packet_signature(row))].append(row)

    worklist: list[dict[str, Any]] = []
    for (cik, category, signature), rows in grouped.items():
        rows = sorted(rows, key=lambda r: (normalize_text(r.get("filing_date")), normalize_text(r.get("accession_number"))))
        recommended, confidence = _recommended_action(category)
        chunks = _chunk_rows(rows, max_records_per_packet)
        for packet_index, chunk in enumerate(chunks, 1):
            chunk_signature = f"{signature}|packet_{packet_index}_of_{len(chunks)}"
            review_id = make_review_id(cik, category, chunk_signature)
            worklist.append(
                {
                    "review_id": review_id,
                    "cik": cik,
                    "entity_name": chunk[0].get("entity_name", ""),
                    "category": category,
                    "template_signature": chunk_signature,
                    "offer_role_hint": _stable_join(row.get("offer_role_hint") for row in chunk),
                    "form_type_family": _stable_join(form_type_family(row.get("form_type", "")) for row in chunk),
                    "packet_index": packet_index,
                    "packet_count": len(chunks),
                    "group_total_issue_count": len(rows),
                    "issue_count": len(chunk),
                    "progress_statuses": _stable_join(row.get("source_status") for row in chunk),
                    "form_types": _stable_join(row.get("form_type") for row in chunk),
                    "filing_date_min": chunk[0].get("filing_date", ""),
                    "filing_date_max": chunk[-1].get("filing_date", ""),
                    "sample_accessions": _stable_join((row.get("accession_number") for row in chunk), limit=12),
                    "sample_primary_documents": _stable_join((row.get("primary_document") for row in chunk), limit=12),
                    "missing_fields": _stable_join((row.get("missing_fields") for row in chunk), limit=8),
                    "checkbox_states": _stable_join((row.get("checkbox_state") for row in chunk), limit=8),
                    "has_final_heading_count": sum(str(row.get("has_final_heading")) == "True" for row in chunk),
                    "has_result_terms_count": sum(str(row.get("has_result_terms")) == "True" for row in chunk),
                    "recommended_action": recommended,
                    "confidence": confidence,
                }
            )
    worklist.sort(key=lambda r: (-int(r["issue_count"]), r["cik"], r["category"]))
    if top_n and top_n > 0:
        worklist = worklist[:top_n]
    write_csv_rows(output_dir / "worklist.csv", worklist, WORKLIST_COLUMNS)
    ensure_dir(output_dir / "bundles")
    ensure_dir(output_dir / "verdicts")
    return {
        "triage_count": len(triage),
        "worklist_count": len(worklist),
        "triage_counts": dict(Counter(row["category"] for row in triage)),
        "worklist_issue_count": sum(int(row["issue_count"]) for row in worklist),
    }


def _artifact(path: Path) -> dict[str, str]:
    return {
        "path": display_path(path),
        "sha256": sha256_file(path) if path.exists() else "",
        "exists": str(path.exists()),
    }


def build_bundles(
    *,
    output_dir: Path = REVIEW_DIR,
    review_ids: set[str] | None = None,
    overwrite: bool = False,
    max_records_per_bundle: int = 12,
) -> list[dict[str, str]]:
    worklist = read_csv_rows(output_dir / "worklist.csv")
    triage = read_csv_rows(output_dir / "triage_detail.csv")
    rows_by_accession = {row["accession_number"]: row for row in triage}

    ensure_dir(output_dir / "bundles")
    manifest: list[dict[str, str]] = []
    for work in worklist:
        review_id = work["review_id"]
        if review_ids is not None and review_id not in review_ids:
            continue
        bundle_path = output_dir / "bundles" / f"{review_id}.json"
        if bundle_path.exists() and not overwrite:
            manifest.append({"review_id": review_id, "bundle_path": display_path(bundle_path), "bundle_sha256": sha256_file(bundle_path)})
            continue
        packet_accessions = [part.strip() for part in work.get("sample_accessions", "").split("|") if part.strip()]
        group_rows = [rows_by_accession[accession] for accession in packet_accessions if accession in rows_by_accession]
        samples = sorted(group_rows, key=lambda r: (r.get("filing_date", ""), r.get("accession_number", "")))[:max_records_per_bundle]
        evidence_items = [
            {"evidence_id": "worklist_row", "kind": "worklist_row", "data": work},
        ]
        for idx, sample in enumerate(samples, 1):
            evidence_items.append(
                {
                    "evidence_id": f"filing_{idx}",
                    "kind": "filing_snippet",
                    "data": {
                        key: sample.get(key, "")
                        for key in TRIAGE_DETAIL_COLUMNS
                        if key != "html_local_path"
                    }
                    | {"html_path": sample.get("html_local_path", "")},
                }
            )
        bundle = {
            "schema_version": "sc-toi-review-bundle.v1",
            "generated_at": now_iso(),
            "review_id": review_id,
            "cik": work["cik"],
            "entity_name": work["entity_name"],
            "category": work["category"],
            "template_signature": work["template_signature"],
            "offer_role_hint": work.get("offer_role_hint", ""),
            "form_type_family": work.get("form_type_family", ""),
            "packet_index": int(work.get("packet_index") or 1),
            "packet_count": int(work.get("packet_count") or 1),
            "group_total_issue_count": int(work.get("group_total_issue_count") or work["issue_count"]),
            "issue_count": int(work["issue_count"]),
            "instructions": [
                "Tag each filing as issuer_self_tender, third_party_tender, not_final_or_no_results, unknown_role, or missing_html.",
                "Classify whether this bundle represents a benign no-result filing, a parser gap, an unsupported structure, insufficient evidence, third-party-only packet, or escalation.",
                "Do not edit production output files.",
                "If proposing a parser pattern, cite filing evidence and describe false-positive risk.",
            ],
            "source_artifacts": {
                "filings_index": _artifact(config.SC_TOI_FILINGS_INDEX_FILE),
                "parse_progress": _artifact(config.SC_TOI_PARSE_PROGRESS_FILE),
                "repurchase_results": _artifact(config.SC_TOI_RESULTS_FILE),
            },
            "all_accessions": [row.get("accession_number", "") for row in group_rows],
            "packet_accessions": [row.get("accession_number", "") for row in group_rows],
            "evidence_items": evidence_items,
        }
        bundle_path.write_text(json.dumps(bundle, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        manifest.append({"review_id": review_id, "bundle_path": display_path(bundle_path), "bundle_sha256": sha256_file(bundle_path)})
    write_csv_rows(output_dir / "bundle_manifest.csv", manifest, BUNDLE_MANIFEST_COLUMNS)
    return manifest


def _bundle_evidence_ids(bundle: dict[str, Any]) -> set[str]:
    return {normalize_text(item.get("evidence_id")) for item in bundle.get("evidence_items", []) if normalize_text(item.get("evidence_id"))}


def _bundle_accession_evidence(bundle: dict[str, Any]) -> dict[str, str]:
    out: dict[str, str] = {}
    for item in bundle.get("evidence_items", []):
        evidence_id = normalize_text(item.get("evidence_id"))
        data = item.get("data", {})
        accession = normalize_text(data.get("accession_number")) if isinstance(data, dict) else ""
        if evidence_id and accession:
            out[accession] = evidence_id
    return out


def _protected_edit(path_text: str) -> bool:
    norm = path_text.replace("\\", "/").lstrip("./")
    return norm in PROTECTED_GENERATED_PATHS or any(norm.startswith(prefix) for prefix in PROTECTED_GENERATED_PATH_PREFIXES)


def validate_verdict_file(
    verdict_path: Path,
    output_dir: Path = REVIEW_DIR,
    schema_file: Path = SCHEMA_FILE,
) -> list[str]:
    errors: list[str] = []
    try:
        verdict = json.loads(verdict_path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        return [f"invalid JSON: {exc}"]
    schema = json.loads(schema_file.read_text(encoding="utf-8"))
    try:
        jsonschema.Draft202012Validator(schema).validate(verdict)
    except jsonschema.ValidationError as exc:
        errors.append(f"schema: {exc.message}")

    review_id = normalize_text(verdict.get("review_id"))
    bundle_path = output_dir / "bundles" / f"{review_id}.json"
    if not bundle_path.exists():
        errors.append(f"Missing bundle for review_id: {review_id}")
        return errors
    bundle = json.loads(bundle_path.read_text(encoding="utf-8-sig"))
    if normalize_cik(verdict.get("cik")) != normalize_cik(bundle.get("cik")):
        errors.append("cik does not match bundle")
    if normalize_text(verdict.get("category")) != normalize_text(bundle.get("category")):
        errors.append("category does not match bundle")
    evidence_ids = _bundle_evidence_ids(bundle)
    accession_evidence = _bundle_accession_evidence(bundle)
    bundle_accessions = set(accession_evidence)
    for ref in verdict.get("evidence_refs", []):
        if ref not in evidence_ids:
            errors.append(f"unknown evidence_ref: {ref}")
    filing_tags = verdict.get("filing_tags", [])
    tagged_accessions: set[str] = set()
    for idx, tag in enumerate(filing_tags, 1):
        accession = normalize_text(tag.get("accession_number"))
        if accession in tagged_accessions:
            errors.append(f"duplicate filing_tags accession: {accession}")
        if accession:
            tagged_accessions.add(accession)
        if bundle_accessions and accession not in bundle_accessions:
            errors.append(f"filing_tags[{idx}] accession is not in bundle: {accession}")
        tag_refs = tag.get("evidence_refs", [])
        if not tag_refs:
            errors.append(f"filing_tags[{idx}] requires evidence_refs")
        for ref in tag_refs:
            if ref not in evidence_ids:
                errors.append(f"filing_tags[{idx}] unknown evidence_ref: {ref}")
        expected_ref = accession_evidence.get(accession)
        if expected_ref and expected_ref not in tag_refs:
            errors.append(f"filing_tags[{idx}] must cite its filing evidence: {expected_ref}")
    if bundle_accessions and tagged_accessions != bundle_accessions:
        missing = " | ".join(sorted(bundle_accessions - tagged_accessions))
        extra = " | ".join(sorted(tagged_accessions - bundle_accessions))
        if missing:
            errors.append(f"missing filing_tags for accessions: {missing}")
        if extra:
            errors.append(f"extra filing_tags accessions: {extra}")
    for changed in verdict.get("changed_files", []):
        if _protected_edit(str(changed)):
            errors.append(f"protected generated-output edit is not allowed: {changed}")
    if verdict.get("verdict") == "PARSER_PATTERN_PROPOSED":
        if not verdict.get("evidence_refs"):
            errors.append("PARSER_PATTERN_PROPOSED requires evidence_refs")
        for key in ["affected_fields", "parser_gap_mechanism", "proposed_pattern", "tests_validation_plan", "false_positive_risk"]:
            if not verdict.get(key):
                errors.append(f"PARSER_PATTERN_PROPOSED requires {key}")
        if not any(tag.get("offer_role_tag") == "issuer_self_tender" for tag in filing_tags):
            errors.append("PARSER_PATTERN_PROPOSED requires at least one issuer_self_tender filing tag")
    if verdict.get("verdict") == "OUT_OF_SCOPE_THIRD_PARTY":
        if not filing_tags:
            errors.append("OUT_OF_SCOPE_THIRD_PARTY requires filing_tags")
        if any(tag.get("offer_role_tag") != "third_party_tender" for tag in filing_tags):
            errors.append("OUT_OF_SCOPE_THIRD_PARTY requires all filing_tags to be third_party_tender")
    if verdict.get("verdict") in {"INSUFFICIENT_EVIDENCE", "ESCALATE"} and len(normalize_text(verdict.get("missing_evidence"))) < 10:
        errors.append(f"{verdict.get('verdict')} requires explicit missing_evidence")
    return errors


def validate_all_verdicts(
    output_dir: Path = REVIEW_DIR,
    schema_file: Path = SCHEMA_FILE,
    require_complete: bool = True,
) -> list[dict[str, str]]:
    verdict_dir = output_dir / "verdicts"
    if not verdict_dir.exists():
        return [{"verdict_file": "", "error": f"Missing verdict directory: {verdict_dir}"}]
    expected = {row["review_id"] for row in read_csv_rows(output_dir / "worklist.csv")}
    seen: set[str] = set()
    errors: list[dict[str, str]] = []
    for path in sorted(verdict_dir.glob("*.json")):
        try:
            verdict = json.loads(path.read_text(encoding="utf-8-sig"))
            review_id = normalize_text(verdict.get("review_id"))
            if review_id in seen:
                errors.append({"verdict_file": display_path(path), "error": f"Duplicate verdict for review_id: {review_id}"})
            if review_id:
                seen.add(review_id)
            if review_id and review_id not in expected:
                errors.append({"verdict_file": display_path(path), "error": f"review_id is not in worklist: {review_id}"})
        except json.JSONDecodeError:
            pass
        for error in validate_verdict_file(path, output_dir, schema_file):
            errors.append({"verdict_file": display_path(path), "error": error})
    if require_complete:
        for missing_id in sorted(expected - seen):
            errors.append({"verdict_file": "", "error": f"Missing verdict for review_id: {missing_id}"})
    return errors


def summarize_verdicts(output_dir: Path = REVIEW_DIR, schema_file: Path = SCHEMA_FILE, require_complete: bool = True) -> dict[str, Any]:
    validation_errors = validate_all_verdicts(output_dir, schema_file, require_complete=require_complete)
    if validation_errors:
        write_csv_rows(output_dir / "verdict_validation_errors.csv", validation_errors, ["verdict_file", "error"])
        raise ScToiReviewError(f"Verdict validation failed with {len(validation_errors)} error(s)")
    rows: list[dict[str, Any]] = []
    tag_rows: list[dict[str, Any]] = []
    for path in sorted((output_dir / "verdicts").glob("*.json")):
        verdict = json.loads(path.read_text(encoding="utf-8-sig"))
        rows.append(
            {
                "review_id": verdict["review_id"],
                "cik": verdict["cik"],
                "category": verdict["category"],
                "verdict": verdict["verdict"],
                "confidence": verdict["confidence"],
                "affected_fields": " | ".join(verdict.get("affected_fields", [])),
                "proposed_pattern": verdict.get("proposed_pattern", ""),
                "missing_evidence": verdict.get("missing_evidence", ""),
                "residual_risk": verdict.get("residual_risk", ""),
            }
        )
        for tag in verdict.get("filing_tags", []):
            tag_rows.append(
                {
                    "review_id": verdict["review_id"],
                    "accession_number": tag.get("accession_number", ""),
                    "cik": verdict["cik"],
                    "category": verdict["category"],
                    "offer_role_tag": tag.get("offer_role_tag", ""),
                    "confidence": tag.get("confidence", ""),
                    "evidence_refs": " | ".join(tag.get("evidence_refs", [])),
                    "subject_company": tag.get("subject_company", ""),
                    "offeror": tag.get("offeror", ""),
                    "notes": tag.get("notes", ""),
                }
            )
    write_csv_rows(
        output_dir / "summary.csv",
        rows,
        ["review_id", "cik", "category", "verdict", "confidence", "affected_fields", "proposed_pattern", "missing_evidence", "residual_risk"],
    )
    write_csv_rows(output_dir / "filing_role_tags.csv", tag_rows, FILING_ROLE_TAG_COLUMNS)
    counts = Counter(row["verdict"] for row in rows)
    tag_counts = Counter(row["offer_role_tag"] for row in tag_rows)
    return {"verdict_count": len(rows), "counts": dict(counts), "filing_tag_count": len(tag_rows), "filing_tag_counts": dict(tag_counts)}


def build_prompt(batch_path: Path, output_dir: Path = REVIEW_DIR) -> Path:
    if not PROMPT_TEMPLATE.exists():
        raise ScToiReviewError(f"Missing prompt template: {PROMPT_TEMPLATE}")
    batch = read_csv_rows(batch_path)
    prompt = PROMPT_TEMPLATE.read_text(encoding="utf-8")
    prompt += "\n\n## Review Batch\n\n"
    for row in batch:
        prompt += f"- {row.get('review_id')}: {display_path(output_dir / 'bundles' / (row.get('review_id') + '.json'))}\n"
    out = output_dir / "prompts" / f"sc_toi_review_prompt_{short_hash(json.dumps(batch, sort_keys=True), 8)}.md"
    ensure_dir(out.parent)
    out.write_text(prompt, encoding="utf-8")
    return out


def cli(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="SC TO-I review harness.")
    sub = parser.add_subparsers(dest="command", required=True)

    p_work = sub.add_parser("build-worklist", help="Build SC TO-I review worklist.")
    p_work.add_argument("--output-dir", type=Path, default=REVIEW_DIR)
    p_work.add_argument("--top-n", type=int, default=0)
    p_work.add_argument("--max-records-per-packet", type=int, default=12)

    p_bundle = sub.add_parser("build-bundles", help="Build review bundles.")
    p_bundle.add_argument("--output-dir", type=Path, default=REVIEW_DIR)
    p_bundle.add_argument("--review-id", action="append", default=[])
    p_bundle.add_argument("--all", action="store_true")
    p_bundle.add_argument("--overwrite", action="store_true")
    p_bundle.add_argument("--max-records-per-bundle", type=int, default=12)

    p_validate = sub.add_parser("validate-verdicts", help="Validate review verdicts.")
    p_validate.add_argument("--output-dir", type=Path, default=REVIEW_DIR)
    p_validate.add_argument("--schema-file", type=Path, default=SCHEMA_FILE)
    p_validate.add_argument("--allow-missing", action="store_true", help="Validate only verdicts that exist.")

    p_summary = sub.add_parser("summarize-verdicts", help="Summarize review verdicts.")
    p_summary.add_argument("--output-dir", type=Path, default=REVIEW_DIR)
    p_summary.add_argument("--schema-file", type=Path, default=SCHEMA_FILE)
    p_summary.add_argument("--allow-missing", action="store_true", help="Summarize existing verdicts without requiring a complete batch.")

    args = parser.parse_args(argv)
    if args.command == "build-worklist":
        print(json.dumps(build_worklist(output_dir=args.output_dir, top_n=args.top_n, max_records_per_packet=args.max_records_per_packet), indent=2, sort_keys=True))
        return 0
    if args.command == "build-bundles":
        review_ids = None if args.all or not args.review_id else set(args.review_id)
        manifest = build_bundles(
            output_dir=args.output_dir,
            review_ids=review_ids,
            overwrite=args.overwrite,
            max_records_per_bundle=args.max_records_per_bundle,
        )
        print(json.dumps({"bundle_count": len(manifest)}, indent=2, sort_keys=True))
        return 0
    if args.command == "validate-verdicts":
        errors = validate_all_verdicts(args.output_dir, args.schema_file, require_complete=not args.allow_missing)
        if errors:
            write_csv_rows(args.output_dir / "verdict_validation_errors.csv", errors, ["verdict_file", "error"])
            for error in errors:
                print(f"{error['verdict_file']}: {error['error']}")
            return 1
        print("All verdicts passed validation.")
        return 0
    if args.command == "summarize-verdicts":
        print(json.dumps(summarize_verdicts(args.output_dir, args.schema_file, require_complete=not args.allow_missing), indent=2, sort_keys=True))
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(cli())
