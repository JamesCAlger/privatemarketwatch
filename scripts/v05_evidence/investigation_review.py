"""Fail-closed investigation and independent-review contract (no filesystem writes).

Report: investigator_id; investigations[{finding_id, coverage:{affected_rows:[str],
reviewed_rows:[str]}, evidence:[{accession,text}], conclusion, hypotheses_tested:[str],
next_action}]; observations[{observation_key, suggested_check?, detection_decision:
{action,rationale,reference?}}]; orchestrator_requests[{request_id,classification,
evidence,next_action}].
Review: report_digest, reviewer_id, finding_reviews[{finding_id,outcome,rationale,
evidence,coverage_verified:true,source_comparison_verified:true}],
observation_reviews[{observation_key,outcome,rationale,evidence}],
request_reviews[{request_id,outcome,rationale,evidence}].

Evidence is a nonempty list of cached-filing quotes, {accession,text}. A reviewer
must independently check the declared coverage against the raw ledger and source:
shape validation cannot prove that the investigator listed every affected row or
that a quotation supports a conclusion. Existing quote validation remains required.
Fund-level findings use explicit stable aggregate identifiers in coverage, not [].
An unresolved confirmed error can be fully investigated; missing evidence cannot.
The external review digest binds the entire report and outstanding ledger records.
"""
from __future__ import annotations

import hashlib
import json
import re


CONCLUSIONS = {"confirmed_error", "source_ambiguity", "false_alarm", "insufficient_evidence"}
DETECTION_ACTIONS = {"propose_detector", "existing_detector", "not_feasible"}


def report_digest(report: dict, outstanding: list[dict]) -> str:
    """Hash exact JSON content; ledger order is immaterial, list order in report is not.

    Raise ValueError for non-JSON input; check_investigation converts it to a failure.
    """
    try:
        records = sorted(outstanding, key=lambda row: json.dumps(row, sort_keys=True, allow_nan=False))
        payload = json.dumps({"report": report, "outstanding": records}, sort_keys=True,
                             separators=(",", ":"), ensure_ascii=False, allow_nan=False)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()
    except (TypeError, ValueError) as exc:
        raise ValueError("Report and ledger must contain JSON values only") from exc


def check_investigation(report: dict, outstanding: list[dict], review: dict | None) -> dict:
    """Validate required investigation and independent review, never accept legacy gaps."""
    problems = []
    unchecked = {}

    def fail(message):
        problems.append(message)

    def text(value, minimum=1):
        return isinstance(value, str) and len(value.strip()) >= minimum

    def collection(owner, key, where):
        value = owner.get(key)
        if not isinstance(value, list):
            fail(f"{where}.{key}: required list")
            return []
        return value

    def indexed(rows, key, where):
        result = {}
        for number, row in enumerate(rows):
            if not isinstance(row, dict) or not text(row.get(key)):
                fail(f"{where}[{number}]: required {key}")
                continue
            identifier = row[key]
            if identifier in result:
                fail(f"{where}: duplicate {key} {identifier}")
            result[identifier] = row
        return result

    def evidence(owner, where):
        quotes = collection(owner, "evidence", where)
        if not quotes:
            fail(f"{where}: evidence required")
        for quote in quotes:
            if (not isinstance(quote, dict)
                    or not isinstance(quote.get("accession"), str)
                    or not re.fullmatch(r"\d{10}-\d{2}-\d{6}", quote["accession"])
                    or not text(quote.get("text"), 10)):
                fail(f"{where}: evidence requires accession and substantive printed text")

    def row_ids(owner, key, where):
        values = collection(owner, key, where)
        valid = [value for value in values if text(value)]
        if len(valid) != len(values) or len(set(valid)) != len(valid):
            fail(f"{where}.{key}: unique nonempty string row identifiers required")
        return set(valid)

    if not isinstance(report, dict):
        fail("report: required object")
        report = {}
    if not isinstance(outstanding, list):
        fail("outstanding: required list")
        outstanding = []
    expected = indexed(outstanding, "finding_id", "outstanding")
    investigator = report.get("investigator_id")
    if not text(investigator):
        fail("report.investigator_id: required")
    investigations = indexed(collection(report, "investigations", "report"),
                             "finding_id", "investigations")
    for identifier in sorted(set(expected) - set(investigations)):
        fail(f"{identifier}: investigation missing")
    for identifier in sorted(set(investigations) - set(expected)):
        fail(f"{identifier}: orphan investigation")
    for identifier, item in investigations.items():
        coverage = item.get("coverage")
        if not isinstance(coverage, dict):
            fail(f"{identifier}: coverage object required")
            coverage = {}
        affected = row_ids(coverage, "affected_rows", identifier)
        checked = row_ids(coverage, "reviewed_rows", identifier)
        if not affected:
            fail(f"{identifier}: affected rows or explicit fund-level aggregate required")
        unchecked[identifier] = sorted(affected - checked)
        if affected - checked:
            fail(f"{identifier}: unchecked affected rows remain")
        if checked - affected:
            fail(f"{identifier}: reviewed rows outside declared scope")
        # Optional independently supplied coverage makes omissions machine-detectable.
        if "affected_rows" in expected.get(identifier, {}):
            ledger_rows = row_ids(expected[identifier], "affected_rows", f"ledger.{identifier}")
            if ledger_rows != affected:
                fail(f"{identifier}: coverage differs from ledger affected rows")
        evidence(item, identifier)
        conclusion = item.get("conclusion")
        if not isinstance(conclusion, str) or conclusion not in CONCLUSIONS:
            fail(f"{identifier}: invalid conclusion")
        if conclusion == "insufficient_evidence":
            fail(f"{identifier}: missing evidence leaves investigation incomplete")
            if not text(item.get("missing_evidence"), 20):
                fail(f"{identifier}: specify missing_evidence")
        hypotheses = collection(item, "hypotheses_tested", identifier)
        if not hypotheses or not all(text(value, 12) for value in hypotheses):
            fail(f"{identifier}: substantive hypotheses_tested required")
        if not text(item.get("next_action"), 20):
            fail(f"{identifier}: specific next_action required")

    observations = indexed(collection(report, "observations", "report"),
                           "observation_key", "observations")
    for identifier, observation in observations.items():
        decision = observation.get("detection_decision")
        if not isinstance(decision, dict):
            fail(f"{identifier}: detection_decision required")
            continue
        action = decision.get("action")
        if not isinstance(action, str) or action not in DETECTION_ACTIONS:
            fail(f"{identifier}: invalid detection action")
        if not text(decision.get("rationale"), 40):
            fail(f"{identifier}: substantive detection rationale required")
        if action == "existing_detector" and not text(decision.get("reference")):
            fail(f"{identifier}: existing detector reference required")
        if action == "propose_detector" and not text(observation.get("suggested_check"), 20):
            fail(f"{identifier}: concrete suggested_check required for proposed detector")

    requests = indexed(collection(report, "orchestrator_requests", "report"),
                       "request_id", "orchestrator_requests")
    for identifier, request in requests.items():
        where = f"orchestrator_requests.{identifier}"
        classification = request.get("classification")
        if not isinstance(classification, str) or classification not in {"verification_bug", "acceptance_change"}:
            fail(f"{where}: classify verification_bug or acceptance_change")
        evidence(request, where)
        if not text(request.get("next_action"), 20):
            fail(f"{where}: specific next_action required")

    try:
        digest = report_digest(report, outstanding)
    except ValueError:
        digest = None
        fail("report/ledger: not valid JSON data")
    if not isinstance(review, dict):
        fail("independent review: required object")
        review = {}
    reviewer = review.get("reviewer_id")
    if not text(reviewer) or reviewer == investigator:
        fail("independent review: distinct reviewer_id required")
    if digest is None or review.get("report_digest") != digest:
        fail("independent review: report/ledger digest mismatch")
    for key, id_key, targets in (("finding_reviews", "finding_id", expected),
                                 ("observation_reviews", "observation_key", observations),
                                 ("request_reviews", "request_id", requests)):
        entries = indexed(collection(review, key, "review"), id_key, key)
        if set(entries) != set(targets):
            fail(f"{key}: must review every target exactly, without orphan entries")
        for identifier, entry in entries.items():
            if entry.get("outcome") != "supported":
                fail(f"{key}.{identifier}: review not supported")
            if not text(entry.get("rationale"), 40):
                fail(f"{key}.{identifier}: substantive independent rationale required")
            evidence(entry, f"{key}.{identifier}")
            if key == "finding_reviews":
                for attestation in ("coverage_verified", "source_comparison_verified"):
                    if entry.get(attestation) is not True:
                        fail(f"{key}.{identifier}: {attestation} must be true")
    return {"ok": not problems,
            "status": "INVESTIGATION_INCOMPLETE" if problems else "COMPLETE",
            "problems": problems, "outstanding_ids": sorted(expected),
            "unchecked_rows": unchecked, "report_digest": digest}
