"""Shared non-accrual evidence extraction from cached BDC XBRL filings."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from lxml import etree

from pipeline.bdc_filings import _local_name, _parse_xbrl_contexts

XBRL_PARSER = etree.XMLParser(huge_tree=True, recover=True)
MAX_AUDIT_FOOTNOTE_CHARS = 1000


_MONTHS = {
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

_AS_OF_DATE_RE = re.compile(
    r"\bas\s+of\s+("
    r"january|february|march|april|may|june|july|august|september|october|"
    r"november|december"
    r")\s+([0-9]{1,2}),\s+([0-9]{4})",
    re.IGNORECASE,
)

_NONACCRUAL_RE = re.compile(r"\bnon[\s-]?accrual\b", re.IGNORECASE)
_NEGATED_RE = re.compile(
    r"\b(no|none|not|without)\b[^.]{0,120}\bnon[\s-]?accrual\b",
    re.IGNORECASE,
)
_EXCLUSION_RE = re.compile(
    r"\b(excludes?|excluding|excluded)\b[^.]{0,120}\bnon[\s-]?accrual\b",
    re.IGNORECASE,
)
_POSITIVE_RE = re.compile(
    r"\b("
    r"(?:is|are|was|were|remain(?:s|ed)?|classified|placed)\s+"
    r"(?:\w+\s+){0,8}?"
    r"(?:on|in|as)\s+non[\s-]?accrual"
    r"|non[\s-]?accrual\s+status"
    r"|placed\s+on\s+non[\s-]?accrual"
    r")\b",
    re.IGNORECASE,
)

# Layer 1: Schedule-level aggregate count statements.  The footnote
# describes the fund's total non-accrual exposure rather than flagging a
# specific position.  These are attached to every fact in the schedule by
# XBRL footnote arcs, causing massive fan-out.
_SCHEDULE_LEVEL_COUNT_RE = re.compile(
    r"\b(?:the\s+(?:Company|Fund|Trust|Registrant)\s+had\s+"
    r"(?:one|two|three|four|five|six|seven|eight|nine|ten|\d+)\s+"
    r"(?:portfolio\s+)?(?:company\s+)?investment)"
    r"|"
    r"(?:loans\s+with\s+a\s+cost\s+basis\s+of\s+\$[\d.,]+\s+"
    r"(?:million|billion|thousand)?\s*"
    r"(?:and\s+a\s+fair\s+value\s+of\s+\$[\d.,]+\s*"
    r"(?:million|billion|thousand)?\s*)?"
    r"were\s+classified\s+as\s+non[\s-]?accrual)",
    re.IGNORECASE,
)

# Layer 2: Footnotes whose primary subject is NOT non-accrual.  Non-accrual
# is mentioned incidentally in a long footnote about SPV structure, unfunded
# commitments, affiliated holdings, or other topics.
_NON_PRIMARY_SUBJECT_RE = re.compile(
    r"^(?:"
    # SPV / structural footnotes
    r"denotes\s+that\s+all\s+or\s+a\s+portion"
    r"|"
    # Unfunded commitment footnotes mentioning NA incidentally
    r"position\s+or\s+portion\s+thereof\s+is\s+an\s+unfunded"
    r"|"
    # Multi-entity holding descriptions
    r"the\s+company\s+holds\s+investments?\s+in\s+[A-Z]"
    r"|"
    # Unfunded commitment with no-interest language
    r"security\s+has\s+an\s+unfunded\s+commitment"
    r")",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class FootnoteDecision:
    accepted: bool
    reason: str


def _parse_report_date(report_date: str | None) -> date | None:
    if not report_date:
        return None
    try:
        y, m, d = (int(part) for part in str(report_date)[:10].split("-"))
        return date(y, m, d)
    except (TypeError, ValueError):
        return None


def _as_of_dates(text: str) -> set[date]:
    dates: set[date] = set()
    for match in _AS_OF_DATE_RE.finditer(text):
        month = _MONTHS[match.group(1).lower()]
        day = int(match.group(2))
        year = int(match.group(3))
        try:
            dates.add(date(year, month, day))
        except ValueError:
            continue
    return dates


def classify_footnote(text: str, report_date: str | None = None) -> FootnoteDecision:
    """Return whether a linked footnote is positive current-period evidence."""
    note = " ".join(str(text or "").split())
    if not _NONACCRUAL_RE.search(note):
        return FootnoteDecision(False, "no_nonaccrual_language")
    if _EXCLUSION_RE.search(note):
        return FootnoteDecision(False, "exclusion_language")
    if _NEGATED_RE.search(note):
        return FootnoteDecision(False, "negated_language")

    # Layer 2: reject footnotes whose primary subject is not non-accrual.
    if _NON_PRIMARY_SUBJECT_RE.search(note):
        return FootnoteDecision(False, "non_primary_subject")

    # Layer 1: reject schedule-level aggregate count statements.
    if _SCHEDULE_LEVEL_COUNT_RE.search(note):
        return FootnoteDecision(False, "schedule_level_count")

    stated_dates = _as_of_dates(note)
    parsed_report_date = _parse_report_date(report_date)
    if stated_dates and parsed_report_date and parsed_report_date not in stated_dates:
        return FootnoteDecision(False, "stale_or_comparative_date")

    if _POSITIVE_RE.search(note):
        return FootnoteDecision(True, "positive_linked_footnote")
    return FootnoteDecision(False, "ambiguous_nonaccrual_language")


def _audit_text(text: str) -> str:
    note = " ".join(str(text or "").split())
    if len(note) <= MAX_AUDIT_FOOTNOTE_CHARS:
        return note
    return note[:MAX_AUDIT_FOOTNOTE_CHARS] + "...[truncated]"


def has_nonaccrual_dimension(context: dict[str, Any]) -> bool:
    """Return true for investment contexts carrying explicit non-accrual members."""
    if not context.get("is_investment") or not context.get("investment_identifier"):
        return False
    text = " ".join(
        str(context.get(k, "") or "")
        for k in ("investment_type", "affiliation", "dimensions_raw")
    )
    compact = re.sub(r"[^a-z0-9]", "", text.lower())
    return "nonaccrual" in compact


def linked_fact_footnotes(root: etree._Element) -> dict[str, list[str]]:
    """Map XBRL fact ids to linked footnote text mentioning non-accrual."""
    label_to_id: dict[str, str] = {}
    label_to_note: dict[str, str] = {}
    arcs: list[tuple[str, str]] = []

    for elem in root.iter():
        ln = _local_name(elem.tag).lower()
        if ln == "loc":
            label = elem.get("{http://www.w3.org/1999/xlink}label") or elem.get("label")
            href = elem.get("{http://www.w3.org/1999/xlink}href") or elem.get("href")
            if label and href and "#" in href:
                label_to_id[label] = href.rsplit("#", 1)[-1]
        elif ln == "footnote":
            label = elem.get("{http://www.w3.org/1999/xlink}label") or elem.get("label")
            note = " ".join("".join(elem.itertext()).split())
            if label and _NONACCRUAL_RE.search(note):
                label_to_note[label] = note
        elif ln.endswith("arc"):
            from_label = elem.get("{http://www.w3.org/1999/xlink}from") or elem.get("from")
            to_label = elem.get("{http://www.w3.org/1999/xlink}to") or elem.get("to")
            if from_label and to_label:
                arcs.append((from_label, to_label))

    out: dict[str, list[str]] = {}
    for from_label, to_label in arcs:
        fact_id = label_to_id.get(from_label)
        note = label_to_note.get(to_label)
        if fact_id and note:
            out.setdefault(fact_id, []).append(note)
    return out


def extract_nonaccrual_candidates(
    xml_path: str | Path,
    *,
    cik: str,
    report_date: str,
    accession_number: str = "",
) -> list[dict[str, Any]]:
    """Extract accepted and rejected position-level non-accrual candidates."""
    tree = etree.parse(str(xml_path), parser=XBRL_PARSER)
    root = tree.getroot()
    contexts = _parse_xbrl_contexts(tree)
    rows: list[dict[str, Any]] = []

    for ctx_id, context in contexts.items():
        ident = str(context.get("investment_identifier", "") or "").strip()
        if not ident:
            continue
        if has_nonaccrual_dimension(context):
            rows.append({
                "cik": cik,
                "report_date": report_date,
                "accession_number": accession_number,
                "investment_identifier": ident,
                "nonaccrual_source": "dimension",
                "accepted": True,
                "rejection_reason": "",
                "context_id": ctx_id,
                "fact_id": "",
                "footnote_text": "",
            })

    footnotes_by_fact_id = linked_fact_footnotes(root)
    for elem in root.iter():
        fact_id = elem.get("id")
        ctx_ref = elem.get("contextRef")
        if not fact_id or fact_id not in footnotes_by_fact_id or not ctx_ref:
            continue
        context = contexts.get(ctx_ref, {})
        ident = str(context.get("investment_identifier", "") or "").strip()
        if not context.get("is_investment") or not ident:
            continue

        for note in footnotes_by_fact_id[fact_id]:
            decision = classify_footnote(note, report_date)
            rows.append({
                "cik": cik,
                "report_date": report_date,
                "accession_number": accession_number,
                "investment_identifier": ident,
                "nonaccrual_source": "footnote",
                "accepted": decision.accepted,
                "rejection_reason": "" if decision.accepted else decision.reason,
                "context_id": ctx_ref,
                "fact_id": fact_id,
                "footnote_text": _audit_text(note),
            })

    return rows
