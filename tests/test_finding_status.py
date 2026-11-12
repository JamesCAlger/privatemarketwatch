"""pipeline.finding_status: one status per finding, mapped in one place."""
import inspect
import re

import pytest

from pipeline import finding_dispositions, finding_status as fs
from pipeline.finding_status import Facts, status_of
from pipeline.quarter_acceptance import RESOLVED_FINDING_STATES
from scripts import findings_ledger


def test_resolved_states_equal_the_gates_definition():
    assert fs.RESOLVED_STATES == RESOLVED_FINDING_STATES


def test_every_state_the_ledger_can_emit_is_known():
    source = inspect.getsource(findings_ledger.classify_finding)
    emitted = set(re.findall(r'return "([a-z0-9_]+)"', source))
    emitted |= set(re.findall(r'"([a-z0-9_]+)" if ', source)) | set(re.findall(r' else "([a-z0-9_]+)"', source))
    emitted |= {findings_ledger.SILENT_REAL_ERROR_STATE, findings_ledger.RETIRED_STATE}
    emitted |= set(finding_dispositions.STATE_BY_CLASS.values())
    emitted |= set(findings_ledger.CLOSURE_ACTIONABLE_STATES) | set(findings_ledger.ACTIONABLE_STATES)
    assert "open" in emitted and "needs_human" in emitted
    assert emitted <= fs.KNOWN_STATES, sorted(emitted - fs.KNOWN_STATES)


def test_every_known_state_maps_to_a_status():
    for state in fs.KNOWN_STATES:
        assert status_of(state) in fs.STATUSES


def test_unknown_state_raises():
    with pytest.raises(ValueError):
        status_of("some_new_state")
    with pytest.raises(ValueError):
        status_of("")


@pytest.mark.parametrize("state", sorted(RESOLVED_FINDING_STATES))
def test_resolved_is_closed_whatever_the_facts(state):
    facts = Facts(fix_queued=True, check_repair=True, proposal_class="as_filed",
                  conclusion="confirmed_error", conclusion_supported=True)
    assert status_of(state, facts) == fs.CLOSED
    assert not fs.is_outstanding(status_of(state, facts))


def test_outstanding_is_exactly_not_closed():
    for state in fs.KNOWN_STATES:
        assert fs.is_outstanding(status_of(state)) == (state not in RESOLVED_FINDING_STATES)


def test_queued_fix_waits_for_the_build():
    assert status_of("real_error_unremediated", Facts(fix_queued=True)) == fs.FIX_AWAITING_BUILD
    assert status_of("open", Facts(fix_queued=True, check_repair=True)) == fs.FIX_AWAITING_BUILD


def test_check_repair_request_and_misfire_proposals():
    assert status_of("open", Facts(check_repair=True)) == fs.NEEDS_CHECK_REPAIR
    assert status_of("open", Facts(proposal_class="rule_problem")) == fs.NEEDS_CHECK_REPAIR
    assert status_of("open", Facts(proposal_class="false_alarm")) == fs.NEEDS_CHECK_REPAIR
    # a misfire beats a human-basket state and a real-error verdict: the next step is the check
    assert status_of("needs_human", Facts(check_repair=True)) == fs.NEEDS_CHECK_REPAIR
    assert status_of("real_error_check_silent", Facts(check_repair=True)) == fs.NEEDS_CHECK_REPAIR


@pytest.mark.parametrize("state", ["needs_human", "evidence_backlog"])
def test_human_basket_needs_the_owner(state):
    assert status_of(state) == fs.NEEDS_OWNER_RULING


@pytest.mark.parametrize("klass", ["as_filed", "not_applicable", "informational"])
def test_store_class_proposal_needs_the_owner(klass):
    assert status_of("open", Facts(proposal_class=klass)) == fs.NEEDS_OWNER_RULING
    assert status_of("remediation_pulled", Facts(proposal_class=klass)) == fs.NEEDS_OWNER_RULING


@pytest.mark.parametrize("state", sorted(fs.REAL_ERROR_STATES))
def test_real_error_family_needs_a_fix(state):
    assert status_of(state) == fs.NEEDS_DATA_FIX


def test_supported_conclusions_on_an_open_finding():
    assert status_of("open", Facts(conclusion="confirmed_error", conclusion_supported=True)) == fs.NEEDS_DATA_FIX
    assert status_of("open", Facts(conclusion="false_alarm", conclusion_supported=True)) == fs.NEEDS_CHECK_REPAIR
    assert status_of("open", Facts(conclusion="source_ambiguity", conclusion_supported=True)) == fs.NEEDS_OWNER_RULING


@pytest.mark.parametrize("conclusion", ["confirmed_error", "false_alarm", "source_ambiguity", "insufficient_evidence", ""])
def test_unsupported_or_incomplete_conclusion_goes_back_to_review(conclusion):
    assert status_of("open", Facts(conclusion=conclusion, conclusion_supported=False)) == fs.NEEDS_AGENT_REVIEW
    assert status_of("open", Facts(conclusion="insufficient_evidence", conclusion_supported=True)) == fs.NEEDS_AGENT_REVIEW


@pytest.mark.parametrize("state", sorted(fs.UNREVIEWED_STATES))
def test_unreviewed_states_need_agent_review(state):
    assert status_of(state) == fs.NEEDS_AGENT_REVIEW
