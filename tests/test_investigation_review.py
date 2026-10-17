"""Investigation completeness is independent of whether an error has been fixed."""
from copy import deepcopy

import pytest

from scripts.v05_evidence.investigation_review import check_investigation, report_digest


QUOTE = {"accession": "0001234567-26-000001", "text": "Acme first lien: principal 55,057; fair value 54,100."}


@pytest.fixture
def case():
    outstanding = [{"finding_id": "f1", "rule_name": "principal_missing"}]
    report = {
        "investigator_id": "fund-agent",
        "investigations": [{"finding_id": "f1",
            "coverage": {"affected_rows": ["accession/context/acme"], "reviewed_rows": ["accession/context/acme"]},
            "evidence": [QUOTE], "conclusion": "confirmed_error",
            "hypotheses_tested": ["Compared the missing principal against the printed schedule; it is not a dash."],
            "next_action": "Repair the principal extractor and rebuild this fund from cached filings."}],
        "observations": [{"observation_key": "currency_column",
            "suggested_check": "Flag positions whose printed denomination conflicts with the extracted currency.",
            "detection_decision": {"action": "propose_detector",
                "rationale": "Compare the printed denomination with the extracted currency on non-USD loans."}}],
        "orchestrator_requests": [],
    }
    review = {"reviewer_id": "independent-reader", "report_digest": report_digest(report, outstanding),
        "finding_reviews": [{"finding_id": "f1", "outcome": "supported", "evidence": [QUOTE],
            "coverage_verified": True, "source_comparison_verified": True,
            "rationale": "Checked the raw ledger and full schedule: Acme is the only affected position; printed par proves the defect."}],
        "observation_reviews": [{"observation_key": "currency_column", "outcome": "supported", "evidence": [QUOTE],
            "rationale": "The missing detector requires a separate source-column comparison; the proposed check addresses this mechanism."}],
        "request_reviews": []}
    return report, outstanding, review


def evaluate(case):
    report, outstanding, review = case
    review["report_digest"] = report_digest(report, outstanding)
    return check_investigation(report, outstanding, review)


def test_confirmed_unfixed_error_can_be_fully_investigated(case):
    result = check_investigation(*case)
    assert result["ok"] and result["status"] == "COMPLETE"
    assert result["outstanding_ids"] == ["f1"]


def test_unchecked_rows_derived_not_trusted(case):
    case[0]["investigations"][0]["coverage"].update(reviewed_rows=[], unchecked_rows=[])
    result = evaluate(case)
    assert not result["ok"]
    assert result["unchecked_rows"]["f1"] == ["accession/context/acme"]


def test_ledger_scope_omission_detected(case):
    case[1][0]["affected_rows"] = ["accession/context/acme", "accession/context/other"]
    assert "coverage differs" in " ".join(evaluate(case)["problems"])


@pytest.mark.parametrize("field,value", [
    ("evidence", []), ("evidence", [{"accession": "bogus", "text": "Source says fine"}]),
    ("conclusion", "parked"), ("conclusion", {}), ("hypotheses_tested", []),
    ("next_action", "Build limit reached"), ("coverage", None),
    ("coverage", {"affected_rows": ["a", "a"], "reviewed_rows": ["a"]}),
    ("coverage", {"affected_rows": ["a"], "reviewed_rows": ["a", "b"]}),
    ("coverage", {"affected_rows": [], "reviewed_rows": []}),
])
def test_incomplete_investigation_rejected(case, field, value):
    case[0]["investigations"][0][field] = value
    assert not evaluate(case)["ok"]


def test_missing_evidence_stays_incomplete_even_when_reviewer_supports(case):
    case[0]["investigations"][0].update(conclusion="insufficient_evidence",
        missing_evidence="The cached annual schedule does not contain the amendment needed to determine the cash rate.")
    assert not evaluate(case)["ok"]


@pytest.mark.parametrize("target", ["investigations", "observations"])
def test_duplicate_and_orphan_entries_rejected(case, target):
    case[0][target].append(deepcopy(case[0][target][0]))
    assert not evaluate(case)["ok"]
    key = "finding_id" if target == "investigations" else "observation_key"
    case[0][target][1][key] = "orphan"
    assert not evaluate(case)["ok"]


@pytest.mark.parametrize("mutation", ["missing", "self_review", "rejected", "short_rationale", "missing_evidence", "orphan"])
def test_independent_review_requirements(case, mutation):
    review = case[2]
    if mutation == "missing":
        review["finding_reviews"] = []
    elif mutation == "self_review":
        review["reviewer_id"] = case[0]["investigator_id"]
    elif mutation == "rejected":
        review["finding_reviews"][0]["outcome"] = "rejected"
    elif mutation == "short_rationale":
        review["observation_reviews"][0]["rationale"] = "Looks good"
    elif mutation == "missing_evidence":
        review["finding_reviews"][0]["evidence"] = []
    else:
        review["finding_reviews"].append({"finding_id": "orphan"})
    assert not evaluate(case)["ok"]


@pytest.mark.parametrize("side", ["report", "ledger"])
def test_review_invalidated_by_report_or_ledger_change(case, side):
    if side == "report":
        case[0]["investigations"][0]["next_action"] += " Then export."
    else:
        case[1][0]["rule_name"] = "another_rule"
    assert "digest mismatch" in " ".join(check_investigation(*case)["problems"])


@pytest.mark.parametrize("decision", [None, {}, {"action": []},
    {"action": "existing_detector", "rationale": "The existing rule detects all cases by checking the same source facts."}])
def test_detection_decision_required(case, decision):
    case[0]["observations"][0]["detection_decision"] = decision
    assert not evaluate(case)["ok"]


def test_existing_detector_with_reference_accepted(case):
    case[0]["observations"][0]["detection_decision"].update(action="existing_detector", reference="X11")
    assert evaluate(case)["ok"]


def test_verification_request_needs_classification_evidence_and_next_step(case):
    case[0]["orchestrator_requests"] = [{"request": "Change the gate so this passes"}]
    assert not evaluate(case)["ok"]
    case[0]["orchestrator_requests"] = [{"request_id": "margin_reader", "classification": "verification_bug", "evidence": [QUOTE],
        "next_action": "Correct comma handling in the independent margin reader and add a regression test."}]
    assert not evaluate(case)["ok"]
    case[2]["request_reviews"] = [{"request_id": "margin_reader", "outcome": "supported", "evidence": [QUOTE],
        "rationale": "The independently read printed margin supports repairing the parser; the acceptance threshold remains unchanged."}]
    assert evaluate(case)["ok"]


def test_detector_proposal_requires_concrete_suggested_check(case):
    del case[0]["observations"][0]["suggested_check"]
    assert not evaluate(case)["ok"]


@pytest.mark.parametrize("requests", [[None], [{"request_id": "duplicate"}, {"request_id": "duplicate"}],
    [{"request_id": "bad-classification", "classification": []}]])
def test_bad_requests_fail_closed(case, requests):
    case[0]["orchestrator_requests"] = requests
    assert not evaluate(case)["ok"]


@pytest.mark.parametrize("attestation", ["coverage_verified", "source_comparison_verified"])
@pytest.mark.parametrize("value", [None, False, 1, "true"])
def test_reviewer_must_attest_independent_scope_and_row_comparison(case, attestation, value):
    case[2]["finding_reviews"][0][attestation] = value
    assert not evaluate(case)["ok"]


@pytest.mark.parametrize("value", [None, [], "bad", 4, True])
def test_malformed_top_level_inputs_fail_closed(value):
    result = check_investigation(value, value, value)
    assert not result["ok"] and result["status"] == "INVESTIGATION_INCOMPLETE"


def test_legacy_report_is_not_grandfathered():
    assert not check_investigation({"parked": [{"reason": "Build cap"}]}, [{"finding_id": "f1"}], None)["ok"]


def test_digest_order_independent_for_ledger_but_binds_content(case):
    records = case[1] + [{"finding_id": "f2"}]
    assert report_digest(case[0], records) == report_digest(case[0], records[::-1])
    with pytest.raises(ValueError):
        report_digest({"invalid": float("nan")}, records)
