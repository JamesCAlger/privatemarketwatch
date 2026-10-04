from copy import deepcopy
import pytest
from pipeline.jev_review_findings import freeze_findings
from scripts.prepare_jev_blind_review import review_input


def inputs():
    packet = {'rule': {'id': 'C107', 'fields': ['cost']}, 'output_position': {'cost': '-1000', 'cost_currency': 'USD'},
              'provenance': {'holdings_sha256': 'holdings'}}
    prepared = review_input(packet, 'source.html', 'source-hash')
    completed = deepcopy(prepared)
    completed['review_form'].update(reviewer='synthetic test reviewer', source_first_attestation=True,
        started_at='2026-10-04T01:00:00Z', completed_at='2026-10-04T01:02:00Z', active_seconds=60,
        disposition='unresolved', reason='Cannot distinguish source siblings',
        unresolved_questions=['Which tranche matches?'])
    return prepared, completed


def resolved():
    prepared, completed = inputs()
    completed['review_form'].update(disposition='false_alarm', reason='Source reports same cost',
        unresolved_questions=[], checks={k: True for k in completed['review_form']['checks']},
        source_coordinates='table 1 row 2',
        citations=[{'source_sha256': 'source-hash', 'coordinates': 'table 1 row 2', 'supports': 'Disclosed cost'}],
        candidate_inventory=[{'coordinates': 'table 1 row 2', 'treatment': 'selected', 'reason': 'Exact class'}],
        source_values={'cost': {'amount': '-1000', 'display_unit': '1', 'currency': 'USD'}})
    return prepared, completed


def test_unresolved_findings_are_valid_without_inventing_evidence():
    record = freeze_findings(*inputs())
    assert record['findings']['disposition'] == 'unresolved'
    assert all(v is None for v in record['findings']['checks'].values())
    assert not record['bundle_audit_completed'] and not record['production_clearance_enabled']


def test_complete_findings_do_not_certify_independence_or_clearance():
    record = freeze_findings(*resolved())
    assert not record['independence_verified']
    assert not record['bundle_audit_completed']
    assert record['stage'] == 'source_first_findings_only'


def test_changed_envelope_is_rejected():
    prepared, completed = inputs()
    completed['position']['cost'] = '-2000'
    with pytest.raises(ValueError, match='envelope'):
        freeze_findings(prepared, completed)


@pytest.mark.parametrize('changes', [{'active_seconds': 121}, {'active_seconds': float('nan')},
    {'active_seconds': True}, {'completed_at': '2026-10-04T00:59:00Z'},
    {'started_at': '2026-10-04T01:00:00'}, {'source_first_attestation': False}])
def test_invalid_timing_or_unattested_review_is_rejected(changes):
    prepared, completed = inputs()
    completed['review_form'].update(changes)
    with pytest.raises(ValueError):
        freeze_findings(prepared, completed)


@pytest.mark.parametrize('field,value', [('notes', None), ('identity', 1), ('candidate_recall', False)])
def test_false_alarm_requires_boolean_complete_checks(field, value):
    prepared, completed = resolved()
    completed['review_form']['checks'][field] = value
    with pytest.raises(ValueError):
        freeze_findings(prepared, completed)


def test_wrong_source_citation_is_rejected():
    prepared, completed = resolved()
    completed['review_form']['citations'][0]['source_sha256'] = 'different-source'
    with pytest.raises(ValueError, match='Citation'):
        freeze_findings(prepared, completed)


@pytest.mark.parametrize('field,value', [('amount', 'NaN'), ('amount', True), ('display_unit', '0'), ('currency', 'CAD')])
def test_invalid_source_values_are_not_frozen(field, value):
    prepared, completed = resolved()
    completed['review_form']['source_values']['cost'][field] = value
    with pytest.raises(ValueError):
        freeze_findings(prepared, completed)


def test_unresolved_sibling_prevents_false_alarm_record():
    prepared, completed = resolved()
    completed['review_form']['candidate_inventory'].append(
        {'coordinates': 'table 1 row 3', 'treatment': 'unresolved', 'reason': 'Same name'})
    with pytest.raises(ValueError, match='Unresolved candidate'):
        freeze_findings(prepared, completed)


def test_independent_amount_contradiction_prevents_false_alarm():
    prepared, completed = resolved()
    completed['review_form']['source_values']['cost']['amount'] = '-2000'
    with pytest.raises(ValueError, match='contradicts'):
        freeze_findings(prepared, completed)


def test_real_error_can_record_contradictory_source_amount():
    prepared, completed = resolved()
    completed['review_form']['disposition'] = 'real_error'
    completed['review_form']['source_values']['cost']['amount'] = '-2000'
    assert freeze_findings(prepared, completed)['findings']['disposition'] == 'real_error'
