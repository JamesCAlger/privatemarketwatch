"""One authoritative XBRL instance per filer and report date when several are indexed.

Owner ruling 2026-10-04: prioritise the amendment unless it only carries the amended
datapoints. The rule, applied to the indexed 10-K/10-Q candidates (and their /A
amendments) of ONE fund-quarter:

1. Every candidate is measured: target-quarter position facts (InvestmentOwnedAtFairValue
   on an instant context dated at the report date that carries an investment-identifier
   axis) and target-quarter non-dei numeric facts. Where no candidate has an identifier-axis
   fact, the non-dei numeric count is the measure.
2. A candidate is FULL when its count is at least FULL_CANDIDATE_MIN_PCT of the largest
   candidate's count.
3. The latest-filed full candidate is selected: a full amendment beats the original, a
   cover-only amendment never does.
4. An amendment with zero target-quarter non-dei numeric facts is cover-only, whatever dei
   facts or dei instant contexts it carries (dei:EntityPublicFloat is often dated at the
   period end).
5. Everything else is refused with a specific reason; nothing is settled by guessing.

"Amendment" always means the filings-index form type (10-K/A, 10-Q/A). dei:AmendmentFlag is
recorded as evidence and never read by the decision: it is false on real 10-K/As (Ares,
TCW). File size is recorded and never read either. The fund-level total is not required.

`measure_instance` parses an instance (heavy for large filers: the caller holds the shared
lease); `decide` is pure and reproducible from the recorded measurements.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
import re

RULE_VERSION = "amendment-rule.v1"

# 90% is a PROXY sitting in an empty gap, not a calibrated boundary. In the evidence base
# (74 parsed multi-instance fund-quarters, 78 amendments) every amendment has either 0% of
# the original's target-quarter position facts (44) or at least 98% (34); nothing lies in
# between, and no true partial amendment exists in the sample. Any value from just above 0%
# to 98% would have produced the same selections. A candidate that ever lands strictly
# between 0% and this threshold is refused for review, never selected or skipped.
FULL_CANDIDATE_MIN_PCT = 90

AMENDMENT_FORMS = frozenset({"10-K/A", "10-Q/A"})
MEASURE_IDENTIFIER = "identifier_axis_fair_value_facts"
MEASURE_NUMERIC = "non_dei_numeric_facts"
POSITION_CONCEPT = "investmentownedatfairvalue"
IDENTIFIER_AXIS_TOKEN = "investmentidentifier"
MAX_CANDIDATES = 20

XBRLI = "{http://www.xbrl.org/2003/instance}"
_DEI = re.compile(r"https?://xbrl\.sec\.gov/dei/")


def _local(value) -> str:
    return str(value).rsplit("}", 1)[-1].rsplit(":", 1)[-1]


def _digest(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def measure_instance(path, cik: str, quarter: str, *, max_bytes: int = 100_000_000,
                     max_contexts: int = 25_000, max_facts: int = 300_000) -> dict:
    """Count the facts the rule needs in one cached instance; never raises on a bad file.

    `source_complete` is False with `errors` filled when the file is missing, too large,
    not a standalone XBRL instance, or changed while it was read.
    """
    from lxml import etree
    path = Path(path)
    result = dict(rule_version=RULE_VERSION, path=str(path), cik=str(cik).zfill(10), quarter=quarter,
                  source_complete=False, errors=[], sha256=None, bytes=None,
                  document_period_ends=[], amendment_flag=[], dei_facts=0,
                  target_instant_contexts=0, position_facts=0, numeric_facts=0)
    try:
        size = path.stat().st_size
        if size > max_bytes:
            raise ValueError("Source exceeds amendment-rule byte limit")
        result["bytes"] = size
        result["sha256"] = _digest(path)
        parser = etree.XMLParser(no_network=True, resolve_entities=False, load_dtd=False,
                                 recover=False, huge_tree=True)
        tree = etree.parse(str(path), parser)
        root = tree.getroot()
        if tree.docinfo.doctype or root.tag != XBRLI + "xbrl":
            raise ValueError("Expected a standalone XBRL instance without a DTD")
        nodes = tree.findall(XBRLI + "context")
        if len(nodes) > max_contexts:
            raise ValueError("Source exceeds context count limit")
        contexts = {}
        for node in nodes:
            instants = node.findall(XBRLI + "period/" + XBRLI + "instant")
            ends = node.findall(XBRLI + "period/" + XBRLI + "endDate")
            both = instants + ends
            period = (both[0].text or "").strip() if len(both) == 1 else None
            identifier = any(IDENTIFIER_AXIS_TOKEN in _local(d.get("dimension", "")).lower()
                             for d in node.iter() if isinstance(d.tag, str) and d.get("dimension"))
            contexts[node.get("id")] = (period, bool(instants), identifier)
        result["target_instant_contexts"] = sum(
            1 for period, instant, _ in contexts.values() if period == quarter and instant)
        period_ends, flags, facts = set(), [], 0
        for node in root:
            if not isinstance(node.tag, str) or not node.get("contextRef"):
                continue
            facts += 1
            if facts > max_facts:
                raise ValueError("Source exceeds fact count limit")
            name = _local(node.tag)
            if _DEI.match(etree.QName(node).namespace or ""):
                result["dei_facts"] += 1
                if name == "DocumentPeriodEndDate":
                    period_ends.add((node.text or "").strip())
                elif name == "AmendmentFlag":
                    flags.append((node.text or "").strip())
                continue
            period, instant, identifier = contexts.get(node.get("contextRef"), (None, False, False))
            if period != quarter or not node.get("unitRef"):
                continue
            result["numeric_facts"] += 1
            if instant and identifier and name.lower() == POSITION_CONCEPT:
                result["position_facts"] += 1
        result["document_period_ends"] = sorted(period_ends)
        result["amendment_flag"] = sorted(set(flags))
        if (path.stat().st_size, _digest(path)) != (size, result["sha256"]):
            raise ValueError("Source changed during inspection")
        result["source_complete"] = True
    except (OSError, ValueError, etree.XMLSyntaxError) as exc:
        result["errors"].append(type(exc).__name__ + ": " + str(exc))
    return result


def _refuse(reason: str, rows: list, **extra) -> dict:
    return dict(status="unavailable", decision="refused", reason=reason, accession_number=None,
                rule_version=RULE_VERSION, full_candidate_min_pct=FULL_CANDIDATE_MIN_PCT,
                candidates=rows, **extra)


def decide(quarter: str, candidates: list[dict]) -> dict:
    """Apply the rule to measured candidates of one fund-quarter. Pure; no file access.

    Each candidate carries `accession_number`, `form_type`, `filing_date` (from the filings
    index) and the `measure_instance` fields. The result lists every candidate, latest filed
    first, with its counts, ratio and disposition, plus the decision and its reason.
    """
    if len(candidates) > MAX_CANDIDATES:
        raise ValueError("Same-quarter instance selection exceeds 20 candidates")
    ordered = sorted(candidates, key=lambda c: (c["filing_date"], c["accession_number"]), reverse=True)
    rows = []
    for c in ordered:
        rows.append(dict(
            accession=c["accession_number"], form_type=c["form_type"], filing_date=c["filing_date"],
            is_amendment=c["form_type"] in AMENDMENT_FORMS, path=c.get("path"),
            sha256=c.get("sha256"), bytes=c.get("bytes"),
            source_complete=bool(c.get("source_complete")), errors=list(c.get("errors") or []),
            document_period_ends=list(c.get("document_period_ends") or []),
            amendment_flag_recorded_not_used=list(c.get("amendment_flag") or []),
            dei_facts=c.get("dei_facts"), target_instant_contexts=c.get("target_instant_contexts"),
            position_facts=int(c.get("position_facts") or 0),
            numeric_facts=int(c.get("numeric_facts") or 0),
            count=None, ratio=None, full=None, disposition="not_assessed"))
    if any(not r["source_complete"] for r in rows):
        for r in rows:
            if not r["source_complete"]:
                r["disposition"] = "not_measurable"
        return _refuse("candidate_not_measurable", rows)
    if any(r["document_period_ends"] != [quarter] for r in rows):
        for r in rows:
            if r["document_period_ends"] != [quarter]:
                r["disposition"] = "period_end_mismatch"
        return _refuse("candidate_period_end_mismatch", rows)
    if len({r["form_type"].removesuffix("/A") for r in rows}) != 1:
        return _refuse("mixed_form_family", rows)
    originals = [r for r in rows if not r["is_amendment"]]
    if len(originals) > 1:
        for r in originals:
            r["disposition"] = "competing_original"
        return _refuse("two_originals_same_quarter", rows)
    identifier = any(r["position_facts"] > 0 for r in rows)
    measure = MEASURE_IDENTIFIER if identifier else MEASURE_NUMERIC
    for r in rows:
        r["count"] = r["position_facts"] if identifier else r["numeric_facts"]
    largest = max(r["count"] for r in rows)
    extra = dict(measure=measure, largest_count=largest)
    if largest == 0:
        return _refuse("no_candidate_with_position_facts", rows, **extra)
    partial = None
    for r in rows:
        r["ratio"] = round(r["count"] / largest, 6)
        # Integer comparison: exactly 90% is full, with no float rounding at the boundary.
        r["full"] = r["count"] * 100 >= largest * FULL_CANDIDATE_MIN_PCT
        if r["full"]:
            r["disposition"] = "full"
        elif r["is_amendment"] and r["numeric_facts"] == 0:
            r["disposition"] = "cover_only_amendment"
        elif r["count"] == 0 and not r["is_amendment"]:
            r["disposition"] = "original_without_target_facts"
        else:
            # Strictly between 0% and the threshold, or an amendment that carries financial
            # facts but no schedule: it restates part of the filing. Not chosen, not skipped.
            r["disposition"] = "partial"
            partial = partial or ("partial_amendment_needs_review" if r["is_amendment"]
                                  else "partial_original_needs_review")
    if partial:
        return _refuse(partial, rows, **extra)
    chosen = next(r for r in rows if r["full"])  # rows are latest filed first
    for r in rows:
        if r["full"] and r is not chosen:
            r["disposition"] = "full_superseded_by_later_filing"
    chosen["disposition"] = "selected"
    if chosen["is_amendment"]:
        reason = "latest_full_amendment"
    elif any(r["disposition"] == "cover_only_amendment" for r in rows):
        reason = "original_after_cover_only_amendment"
    else:
        reason = "latest_full_candidate"
    return dict(status="selected", decision="selected", reason=reason,
                accession_number=chosen["accession"], rule_version=RULE_VERSION,
                full_candidate_min_pct=FULL_CANDIDATE_MIN_PCT, candidates=rows, **extra)
