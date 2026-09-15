"""Programme metrics cannot pass on partial populations or unreviewed labels."""
from copy import deepcopy
from pathlib import Path

import pytest

from pipeline.programme.core import ContractError, atomic_json, digest, read_json, record
from pipeline.programme.measurement import CONTRACTS, compare_amendment, evaluate, evaluate_metric, validate_reference, validate_contract


@pytest.fixture
def contract():
    return read_json(CONTRACTS / 'working-v1.json')


@pytest.fixture
def observation(tmp_path):
    (tmp_path / 'proof.json').write_text('{"count": 100}')
    return dict(schema_version=1, metric_id='sector_fv_coverage', metric_version=1,
                candidate_fingerprint='a' * 64, scope='cohort_70_required_history', quarter=None,
                design='census', denominator_known=True, eligible=100, assessed=100,
                missing_weight=0, value=.98, unit='fraction', formula='known sector FV / eligible absolute FV',
                evidence=[record(tmp_path, 'proof.json')], references=[], reason='')


def test_empty_observations_emit_all_28_criteria_without_pass(contract, tmp_path):
    result = evaluate(contract, {}, 'a' * 64, tmp_path,historical_replay=True)
    assert len(result['criteria']) == 28
    assert len({c['criterion_id'] for c in result['criteria']}) == 28
    assert {c['status'] for c in result['criteria']} == {'UNASSESSABLE'}
    assert all(r['status'] == 'UNMEASURED' for c in result['criteria'] for r in c['results'])


def test_retired_evaluator_cannot_be_used_as_the_live_gate(contract,tmp_path):
    with pytest.raises(ContractError,match='retired'):
        evaluate(contract,{},'a'*64,tmp_path)


@pytest.mark.parametrize('change', [dict(denominator_known=False), dict(missing_weight=1),
    dict(assessed=99), dict(value=None), dict(evidence=[]), dict(eligible=0, assessed=0),
    dict(quarter='2026-03-31'), dict(scope='selected_four_schedules')])
def test_incomplete_measurement_is_not_a_pass(contract, observation, tmp_path, change):
    observation.update(change)
    result = evaluate_metric(observation['metric_id'], observation, contract, 'a' * 64, tmp_path, {})
    assert result['status'] == 'UNASSESSABLE'


def test_complete_census_can_pass_and_fail_working_target(contract, observation, tmp_path):
    assert evaluate_metric('sector_fv_coverage', observation, contract, 'a' * 64, tmp_path, {})['status'] == 'PASS'
    observation['value'] = .72
    assert evaluate_metric('sector_fv_coverage', observation, contract, 'a' * 64, tmp_path, {})['status'] == 'FAIL'


def test_candidate_or_evidence_mismatch_is_rejected(contract, observation, tmp_path):
    with pytest.raises(ContractError):
        evaluate_metric('sector_fv_coverage', observation, contract, 'b' * 64, tmp_path, {})
    (tmp_path / 'proof.json').write_text('changed')
    with pytest.raises(ContractError):
        evaluate_metric('sector_fv_coverage', observation, contract, 'a' * 64, tmp_path, {})


def test_entity_accuracy_cannot_self_certify_reference(contract, observation, tmp_path):
    observation['metric_id'] = 'entity_precision'
    observation['value'] = 1
    observation['references'] = ['development']
    assert evaluate_metric('entity_precision', observation, contract, 'a' * 64, tmp_path, {})['status'] == 'UNASSESSABLE'


def test_sample_requires_uncertainty_instead_of_point_estimate(contract, observation, tmp_path):
    observation.update(design='sample', value=1, assessed=10)
    assert evaluate_metric('sector_fv_coverage', observation, contract, 'a' * 64, tmp_path, {})['status'] == 'UNASSESSABLE'
    observation.update(design_id='predeclared-sample', interval_method='one-sided-cluster-bootstrap',
                       independent_units=10, lower_95_bound=.90)
    assert evaluate_metric('sector_fv_coverage', observation, contract, 'a' * 64, tmp_path, {})['status'] == 'FAIL'


def test_amendment_preserves_old_and_new_on_same_candidate(contract, observation, tmp_path):
    new = deepcopy(contract)
    new['version'] = 'working-v2-test-only'
    new['targets']['sector_fv_coverage']['value'] = .99
    new['amendment'] = dict(previous_contract_sha256=digest(contract), rationale='Test stricter target', evidence=observation['evidence'])
    result = compare_amendment(contract, new, {'sector_fv_coverage': observation}, 'a' * 64, tmp_path)
    assert result['same_candidate']
    old_d3 = next(c for c in result['before']['criteria'] if c['criterion_id'] == 'D3')
    new_d3 = next(c for c in result['after']['criteria'] if c['criterion_id'] == 'D3')
    assert old_d3['results'][1]['status'] == 'PASS'
    assert new_d3['results'][1]['status'] == 'FAIL'
    assert contract['targets']['sector_fv_coverage']['value'] == .95


def test_exact_evidence_requirements_cannot_be_relaxed(contract, observation, tmp_path):
    new = deepcopy(contract)
    new['targets']['misleading_links']['value'] = 1
    with pytest.raises(ContractError):
        compare_amendment(contract, new, {}, 'a' * 64, tmp_path)


def test_self_review_cannot_create_independent_reference(tmp_path):
    (tmp_path / 'payload.json').write_text('{}')
    (tmp_path / 'source.html').write_text('<p>source</p>')
    (tmp_path / 'review.json').write_text('{}')
    reference = dict(schema_version=1, reference_id='test', version='1', author='agent', reviewer='agent',
                     review_status='reviewed', exposure='development_outputs_seen',
                     scope=dict(unit='schedule', population='four schedules', quarter=None),
                     sources=[record(tmp_path, 'source.html')], payload=record(tmp_path, 'payload.json'),
                     disagreements=[], review_attestation=record(tmp_path, 'review.json'))
    with pytest.raises(ContractError):
        validate_reference(reference, tmp_path)


@pytest.mark.parametrize('change', [dict(value=1.1), dict(value=-.1), dict(unit='percent'),
    dict(value=float('nan')), dict(numerator=90, denominator=100),
    dict(design='sample', assessed=10, independent_units=11), dict(lower_95_bound=.99)])
def test_invalid_measurement_cannot_become_a_pass(contract, observation, tmp_path, change):
    observation.update(change)
    with pytest.raises(ContractError):
        evaluate_metric('sector_fv_coverage', observation, contract, 'a' * 64, tmp_path, {})


def test_zero_recorded_denominator_is_unassessable(contract, observation, tmp_path):
    observation.update(numerator=0, denominator=0)
    assert evaluate_metric('sector_fv_coverage', observation, contract, 'a' * 64, tmp_path, {})['status'] == 'UNASSESSABLE'


def test_not_executed_observation_retains_its_missing_dependency(contract, observation, tmp_path):
    observation.update(design='unmeasured', eligible=0, assessed=0, denominator_known=False,
                       value=None, evidence=[], reason='Independent source review is pending')
    result = evaluate_metric('sector_fv_coverage', observation, contract, 'a' * 64, tmp_path, {})
    assert result['status'] == 'UNMEASURED'
    assert result['reason'] == 'Independent source review is pending'


def test_numeric_amendment_cannot_reverse_the_metric(contract):
    contract['targets']['sector_accuracy']['operator'] = 'max'
    with pytest.raises(ContractError):
        validate_contract(contract)


def test_reference_attestation_must_bind_the_reviewed_payload(tmp_path):
    (tmp_path / 'payload.json').write_text('{}')
    (tmp_path / 'source.html').write_text('<p>Source row</p>')
    (tmp_path / 'review.json').write_text('{}')
    reference = dict(schema_version=1, reference_id='test', version='1', author='preparer', reviewer='reviewer',
        review_status='reviewed', exposure='held_out', scope=dict(unit='schedule', population='fixture', quarter=None),
        sources=[record(tmp_path, 'source.html')], payload=record(tmp_path, 'payload.json'), disagreements=[],
        review_attestation=record(tmp_path, 'review.json'))
    with pytest.raises(ContractError):
        validate_reference(reference, tmp_path)
    atomic_json(tmp_path / 'review.json', dict(schema_version=1, reference_id='test', reference_version='1',
        reviewer='reviewer', payload_sha256=reference['payload']['sha256'],
        source_sha256=[reference['sources'][0]['sha256']], decision='approved'))
    reference['review_attestation'] = record(tmp_path, 'review.json')
    validate_reference(reference, tmp_path)
    reference['version'] = '2'
    with pytest.raises(ContractError):
        validate_reference(reference, tmp_path)
