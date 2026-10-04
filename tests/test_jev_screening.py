"""Shadow clearance requires independently reviewed evidence, not confidence alone."""
import copy

import pytest

from pipeline.jev_bundles import RULES
from pipeline.jev_screening import Policy, REQUIRED_CHECKS, fingerprint, project_groups, route_flag


@pytest.fixture
def case():
    packet = {
        'rule': {'id': 'X08', **RULES['X08']},
        'flag': {'row_id': 'ROW-1', 'cik': '0000000001', 'report_date': '2025-06-30', 'rule_id': 'X08'},
        'output_position': {'cost': '2000000', 'cost_reported': '2000000', 'fair_value': '1000', 'report_date': '2025-06-30'},
        'provenance': {'holdings_sha256': 'holdings', 'flags_sha256': 'flags', 'builder_sha256': 'builder'},
        'filing': {'sha256': 'source'},
        'evidence_status': {'status': 'ready_for_model', 'blocking_reasons': []},
        'source_candidates': [{'evidence_id': 't0r1', 'report_date': '2025-06-30', 'blocking_reasons': [],
                               'source_values': {'cost': {'amount': '2000000', 'display_unit': '1000', 'currency': 'USD'},
                                                 'fair_value': {'amount': '1000', 'display_unit': '1000', 'currency': 'USD'}}}],
    }
    result = {'status': 'success', 'model': 'jev-1.13.0', 'bundle_fingerprint': fingerprint(packet),
              'decision': 'false_alarm', 'source_id': 't0r1', 'decision_confidence': 0.9, 'source_confidence': 0.9}
    audit = {'method': 'independent_source_review', 'reviewer': 'test reviewer',
             'bundle_fingerprint': fingerprint(packet), 'source_sha256': 'source', 'evidence_id': 't0r1',
             'checks': dict.fromkeys(REQUIRED_CHECKS, True), 'citations': ['source:table0:row1'],
             'source_values': {'cost': {'amount': '2000000', 'display_unit': '1000', 'currency': 'USD'},
                               'fair_value': {'amount': '1000', 'display_unit': '1000', 'currency': 'USD'}}}
    return packet, result, audit


def route(case, **kwargs):
    packet, result, audit = case
    return route_flag(packet, result, audit, expected_provenance=packet['provenance'], **kwargs)


def refreeze(case):
    packet, result, audit = case
    result['bundle_fingerprint'] = audit['bundle_fingerprint'] = fingerprint(packet)


def test_supported_clearance_is_only_a_shadow_candidate(case):
    receipt = route(case)
    assert receipt['route'] == 'candidate_clearance'
    assert receipt['production_clearance_allowed'] is False
    assert receipt['b1_work_suppressed'] is False
    assert receipt['audit_required'] is True
    assert receipt == route(case)


@pytest.mark.parametrize('decision', ['real_error', 'ambiguous'])
def test_suspected_errors_and_ambiguity_always_go_to_b1(case, decision):
    case[1].update(decision=decision, decision_confidence=1, source_confidence=1)
    assert route(case)['route'] == 'b1'


@pytest.mark.parametrize('field', ['decision_confidence', 'source_confidence'])
@pytest.mark.parametrize('value', [None, True, '0.99', -0.1, 1.1, float('nan'), float('inf'), 0.749999])
def test_invalid_or_low_confidence_cannot_clear(case, field, value):
    case[1][field] = value
    assert route(case)['route'] == 'b1'


def test_cutoff_boundary_is_inclusive(case):
    case[1].update(decision_confidence=0.75, source_confidence=0.75)
    assert route(case)['route'] == 'candidate_clearance'


def test_independent_audit_cannot_be_replaced_by_model_confidence(case):
    packet, result, _ = case
    receipt = route_flag(packet, result, None, expected_provenance=packet['provenance'])
    assert 'independent_review_missing' in receipt['reasons']


def test_proxy_cost_cannot_bypass_builder_with_a_ready_marker(case):
    case[0]['output_position']['cost_source'] = 'first_observed_fv_proxy'
    refreeze(case)
    receipt = route(case)
    assert receipt['route'] == 'b1'
    assert 'proxy_cost_requires_lineage' in receipt['reasons']


def test_matching_amounts_and_high_confidence_cannot_clear_wrong_tranche(case):
    case[0]['source_candidates'][0]['identity_evidence'] = {'output_instrument_compatible': False}
    refreeze(case)
    receipt = route(case)
    assert receipt['route'] == 'b1'
    assert 'candidate_identity_conflict' in receipt['reasons']


def test_selected_row_mismatch_is_recorded_without_an_audit(case):
    packet, result, _ = case
    packet['output_position']['fair_value'] = '10'
    result['bundle_fingerprint'] = fingerprint(packet)
    receipt = route_flag(packet, result, None, expected_provenance=packet['provenance'])
    assert 'selected_source_value_mismatch:fair_value' in receipt['reasons']
    assert 'independent_review_missing' in receipt['reasons']


def test_selected_row_rounding_is_not_a_false_mismatch(case):
    packet, result, _ = case
    packet['output_position']['fair_value'] = '500'
    result['bundle_fingerprint'] = fingerprint(packet)
    receipt = route_flag(packet, result, None, expected_provenance=packet['provenance'])
    assert receipt['reasons'] == ['independent_review_missing']


@pytest.mark.parametrize('currency', [None, 'AUD'])
def test_selected_row_currency_must_be_resolved_even_without_audit(case, currency):
    packet, result, _ = case
    packet['source_candidates'][0]['source_values']['fair_value']['currency'] = currency
    result['bundle_fingerprint'] = fingerprint(packet)
    receipt = route_flag(packet, result, None, expected_provenance=packet['provenance'])
    assert 'selected_source_value_unresolved:fair_value' in receipt['reasons']


@pytest.mark.parametrize('check', REQUIRED_CHECKS)
def test_each_independent_check_is_required(case, check):
    case[2]['checks'][check] = False
    assert route(case)['route'] == 'b1'


def test_value_comparison_is_recomputed_even_if_model_and_builder_claim_agreement(case):
    packet, _, _ = case
    packet['output_position']['fair_value'] = '10'
    packet['source_candidates'][0]['comparisons'] = {'fair_value': {'agrees_at_display_precision': True}}
    refreeze(case)
    assert 'source_value_mismatch:fair_value' in route(case)['reasons']


def test_identity_conflict_overrides_matching_money_and_perfect_confidence(case):
    case[0]['source_candidates'][0]['identity_evidence'] = {'output_class_compatible': False}
    case[1].update(decision_confidence=1, source_confidence=1)
    refreeze(case)
    assert 'candidate_identity_conflict' in route(case)['reasons']


def test_review_is_invalidated_by_any_bundle_change(case):
    case[0]['new_source_note'] = 'New evidence'
    case[1]['bundle_fingerprint'] = fingerprint(case[0])
    assert 'independent_review_stale_bundle' in route(case)['reasons']


def test_changed_holdings_snapshot_routes_to_b1(case):
    packet, result, audit = case
    expected = {**packet['provenance'], 'holdings_sha256': 'new snapshot'}
    assert 'stale_or_unverified_provenance:holdings_sha256' in route_flag(
        packet, result, audit, expected_provenance=expected)['reasons']


def test_high_error_rule_bypasses_model(case):
    assert route(case, policy=Policy(high_error_rules=('X08',)))['reasons'][0] == 'strong_or_high_error_rule'


@pytest.mark.parametrize('severity', ['FAIL', 'BLOCKER', 'ERROR'])
def test_hard_failure_severity_never_enters_screening(case, severity):
    case[0]['flag']['severity'] = severity
    refreeze(case)
    assert route(case)['reasons'][0] == 'strong_or_high_error_rule'


def test_flag_rule_cannot_disagree_with_bundle_rule(case):
    case[0]['flag']['rule_id'] = 'C104'
    refreeze(case)
    assert 'flag_rule_mismatch' in route(case)['reasons']


def test_unsubmitted_eligible_item_remains_pending(case):
    packet, _, audit = case
    receipt = route_flag(packet, None, audit, expected_provenance=packet['provenance'])
    assert receipt['route'] == 'pending'


def test_group_requires_every_member_and_never_suppresses_b1_in_shadow(case):
    receipt = route(case, parent_review_id='G1')
    group = project_groups([receipt], {'G1': [receipt['receipt_id'], 'missing']})[0]
    assert group['all_members_candidate'] is False
    assert group['keep_in_b1_worklist'] is True
    assert group['missing_receipts'] == ['missing']
    complete = project_groups([receipt], {'G1': [receipt['receipt_id']]})[0]
    assert complete['all_members_candidate'] is True
    assert complete['keep_in_b1_worklist'] is True


def test_duplicate_receipts_and_wrong_parent_are_rejected(case):
    receipt = route(case, parent_review_id='G1')
    with pytest.raises(ValueError, match='Duplicate'):
        project_groups([receipt, copy.deepcopy(receipt)], {'G1': [receipt['receipt_id']]})
    with pytest.raises(ValueError, match='different parent'):
        project_groups([receipt], {'G2': [receipt['receipt_id']]})


def test_second_evaluation_cannot_double_count_a_current_flag(case):
    first = route(case, parent_review_id='G1')
    case[1]['decision_confidence'] = 0.8
    second = route(case, parent_review_id='G1')
    with pytest.raises(ValueError, match='Duplicate current flag'):
        project_groups([first, second], {'G1': [first['receipt_id'], second['receipt_id']]})


def test_group_cannot_silently_omit_an_available_receipt(case):
    receipt = route(case, parent_review_id='G1')
    with pytest.raises(ValueError, match='Unassigned'):
        project_groups([receipt], {'G1': ['missing']})


def test_member_cannot_be_reused_across_groups(case):
    receipt = route(case, parent_review_id='G1')
    with pytest.raises(ValueError, match='multiple groups'):
        project_groups([receipt], {'G1': [receipt['receipt_id']], 'G2': [receipt['receipt_id']]})
