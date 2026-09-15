"""Historical programme evaluation only; quarter_acceptance owns the live gate."""
from __future__ import annotations

import math
from pathlib import Path

import jsonschema

from pipeline.programme.catalog import (CRITERIA, EXACT, NUMERIC, REFERENCE_REQUIRED,
    MAXIMUM_NUMERIC, METRIC_UNITS, BOUNDED_FRACTIONS, EXACT_MINIMUM)
from pipeline.programme.core import ContractError, digest, now, read_json, sha, verify_records

CONTRACTS = Path(__file__).with_name('contracts')


def validate_reference(reference, root):
    jsonschema.validate(reference, read_json(CONTRACTS / 'reference-v1.schema.json'))
    verify_records(root, [reference['payload'], *reference['sources']])
    if reference['review_attestation']:
        verify_records(root, [reference['review_attestation']])
    if reference['review_status'] == 'reviewed' and (
        not reference['reviewer'] or reference['reviewer'] == reference['author'] or
        not reference['review_attestation'] or reference['disagreements'] or not reference['sources']):
        raise ContractError('Reviewed reference lacks independent, complete adjudication')
    if reference['review_status'] == 'reviewed':
        attestation = read_json(Path(root) / reference['review_attestation']['path'])
        required = dict(schema_version=1, reference_id=reference['reference_id'],
            reference_version=reference['version'], reviewer=reference['reviewer'],
            payload_sha256=reference['payload']['sha256'],
            source_sha256=[source['sha256'] for source in reference['sources']], decision='approved')
        if any(attestation.get(key) != value for key, value in required.items()):
            raise ContractError('Independent attestation does not approve this exact reference version')


def validate_contract(contract):
    jsonschema.validate(contract, read_json(CONTRACTS / 'threshold-v1.schema.json'))
    if contract.get('schema_version') != 1 or contract.get('status') not in ('working_targets', 'approved'):
        raise ContractError('Unknown programme metric contract')
    if set(contract.get('targets', {})) != NUMERIC or not contract.get('version'):
        raise ContractError('Incomplete or changed metric inventory')
    for metric, target in contract['targets'].items():
        if set(target) != {'operator', 'value'} or target['operator'] not in ('min', 'max'):
            raise ContractError('Invalid comparison: ' + metric)
        if isinstance(target['value'], bool) or not isinstance(target['value'], (int, float)) or not math.isfinite(target['value']):
            raise ContractError('Invalid threshold value: ' + metric)
        if target['operator'] != ('max' if metric in MAXIMUM_NUMERIC else 'min'):
            raise ContractError('Comparison direction is part of the metric definition: ' + metric)
        if target['value'] < 0 or (metric in BOUNDED_FRACTIONS and target['value'] > 1):
            raise ContractError('Threshold outside metric domain: ' + metric)
    if contract['targets']['evidence_path_or_unavailable'] != {'operator': 'min', 'value': 1.0} or contract['targets']['misleading_links'] != {'operator': 'max', 'value': 0}:
        raise ContractError('Exact evidence requirements cannot be numerically relaxed')


def evaluate_metric(metric, observation, contract, candidate, root, references):
    target = contract['targets'].get(metric, EXACT.get(metric))
    if target is None:
        raise ContractError('Unknown metric: ' + metric)
    base = dict(metric_id=metric, metric_version=1, candidate_fingerprint=candidate,
                threshold_version=contract['version'], threshold_status=contract['status'], **target)

    def result(status, reason, **extra):
        return dict(base, status=status, reason=reason, **extra)

    if observation is None:
        return result('UNMEASURED', 'No observation supplied for this required metric')
    jsonschema.validate(observation, read_json(CONTRACTS / 'observation-v1.schema.json'))
    if observation['metric_id'] != metric or observation['candidate_fingerprint'] != candidate:
        raise ContractError('Observation belongs to a different metric or candidate')
    if observation['assessed'] > observation['eligible']:
        raise ContractError('Assessed count exceeds eligible population')
    if observation['unit'] != METRIC_UNITS[metric]:
        raise ContractError('Observation uses the wrong metric unit')
    for key in ('value', 'lower_95_bound', 'upper_95_bound', 'numerator', 'denominator', 'missing_weight'):
        value = observation.get(key)
        if value is not None and (not math.isfinite(value) or value < 0):
            raise ContractError('Invalid nonnegative finite measurement: ' + key)
    if metric in BOUNDED_FRACTIONS | EXACT_MINIMUM:
        if any(observation.get(key) is not None and observation[key] > 1
               for key in ('value', 'lower_95_bound', 'upper_95_bound')):
            raise ContractError('Fraction exceeds one')
    if observation.get('independent_units', 0) and observation['independent_units'] > observation['assessed']:
        raise ContractError('Independent units exceed assessed units')
    point, lower, upper = (observation.get(key) for key in ('value', 'lower_95_bound', 'upper_95_bound'))
    if point is not None and ((lower is not None and lower > point) or (upper is not None and upper < point)):
        raise ContractError('Uncertainty bound excludes the declared point estimate')
    numerator, denominator = observation.get('numerator'), observation.get('denominator')
    if METRIC_UNITS[metric] == 'fraction' and denominator is not None:
        if denominator == 0:
            return result('UNASSESSABLE', 'Zero denominator is not a passing measurement')
        if numerator is not None and point is not None and not math.isclose(numerator / denominator, point, rel_tol=1e-10, abs_tol=1e-12):
            raise ContractError('Recorded numerator/denominator disagrees with the observation')
    if observation['design'] == 'unmeasured':
        return result('UNMEASURED', observation['reason'] or 'Measurement not executed',
                      observation_sha256=digest(observation))
    if observation['scope'] != contract.get('required_population_scope') or observation['quarter'] is not None:
        return result('UNASSESSABLE', 'Observation covers a subset, not the declared full programme scope',
                      subset_value=observation['value'], scope=observation['scope'], quarter=observation['quarter'])
    if not observation['evidence']:
        return result('UNASSESSABLE', 'No retained measurement evidence')
    verify_records(root, observation['evidence'])
    if not observation['denominator_known'] or observation['missing_weight'] > 0:
        return result('UNASSESSABLE', 'Unknown denominator or unresolved FV weights')
    if observation['eligible'] == 0:
        return result('UNASSESSABLE', 'Empty population needs an evidenced applicability decision')
    if metric in REFERENCE_REQUIRED:
        authority = contract.get('reference_review_authority')
        if not authority or not observation['references']:
            return result('UNASSESSABLE', 'Independent reference review authority/evidence is unavailable')
        for key in observation['references']:
            reference = references.get(key)
            if reference is None:
                return result('UNASSESSABLE', 'Missing reference version: ' + key)
            validate_reference(reference, root)
            if reference['review_status'] != 'reviewed' or reference['reviewer'] != authority:
                return result('UNASSESSABLE', 'Reference is development, unreviewed or disputed')
            if observation['design'] == 'sample' and reference['exposure'] != 'held_out':
                return result('UNASSESSABLE', 'Exposed development examples cannot certify sampled population accuracy')
    if observation['design'] in ('census', 'scenario'):
        if observation['assessed'] != observation['eligible']:
            return result('UNASSESSABLE', 'Incomplete census or required scenario set')
        value, basis = observation['value'], observation['design']
    elif observation['design'] == 'sample':
        if not all(observation.get(key) for key in ('design_id', 'interval_method', 'independent_units')):
            return result('UNASSESSABLE', 'Missing sampling design, independent units or interval method')
        value = observation.get('lower_95_bound' if target['operator'] == 'min' else 'upper_95_bound')
        basis = 'one_sided_95_bound'
    else:
        return result('UNMEASURED', observation['reason'] or 'Measurement not executed')
    if value is None or isinstance(value, bool) or not math.isfinite(value):
        return result('UNASSESSABLE', 'Missing or non-finite comparison value')
    if target['operator'] == 'min':
        passed = value >= target['value']
    else:
        passed = value <= target['value']
    return result('PASS' if passed else 'FAIL', 'Compared against versioned programme contract',
                  comparison_value=value, basis=basis, observation_sha256=digest(observation),
                  scope=observation['scope'], quarter=observation['quarter'])


def evaluate(contract, observations, candidate, root, references=None, *, historical_replay=False):
    if not historical_replay:
        raise ContractError('Programme evaluator retired; use pipeline.quarter_acceptance with candidate evidence')
    validate_contract(contract)
    expected = {metric for _, metrics in CRITERIA.values() for metric in metrics}
    if set(observations) - expected:
        raise ContractError('Unknown metrics in observation inventory')
    criteria = []
    for criterion, (title, metrics) in CRITERIA.items():
        results = [evaluate_metric(metric, observations.get(metric), contract, candidate, root, references or {}) for metric in metrics]
        states = {r['status'] for r in results}
        status = 'FAIL' if 'FAIL' in states else 'PASS' if states == {'PASS'} else 'UNASSESSABLE'
        criteria.append(dict(criterion_id=criterion, title=title, status=status, results=results))
    states = {c['status'] for c in criteria}
    verdict = ('FAIL_WITH_UNASSESSED_ITEMS' if 'FAIL' in states and 'UNASSESSABLE' in states else
               'FAIL' if 'FAIL' in states else 'UNASSESSABLE' if 'UNASSESSABLE' in states else 'MEETS_WORKING_CONTRACT')
    result = dict(schema_version=1, candidate_fingerprint=candidate, contract_sha256=digest(contract),
                contract_version=contract['version'], evaluated_utc=now(), criteria=criteria, verdict=verdict,
                evaluator_identity={name: sha(Path(__file__).with_name(name))
                                    for name in ('measurement.py', 'catalog.py', 'core.py')},
                release_approval='not_granted', criterion_inventory_sha256=digest(CRITERIA))
    jsonschema.validate(result, read_json(CONTRACTS / 'result-v1.schema.json'))
    return result


def compare_amendment(old, new, observations, candidate, root, references=None):
    validate_contract(old); validate_contract(new)
    amendment = new.get('amendment') or {}
    if old['version'] == new['version'] or amendment.get('previous_contract_sha256') != digest(old):
        raise ContractError('Amendment must retain an explicit previous contract identity')
    if not amendment.get('rationale') or not amendment.get('evidence'):
        raise ContractError('Evidence-backed amendment rationale is required')
    if old['history'] != new['history'] or old['required_population_scope'] != new['required_population_scope']:
        raise ContractError('A changed population requires new scoped observations, not a same-observation comparison')
    verify_records(root, amendment['evidence'])
    before = evaluate(old, observations, candidate, root, references,historical_replay=True)
    after = evaluate(new, observations, candidate, root, references,historical_replay=True)
    changed = [{'metric_id': metric, 'old': old['targets'][metric], 'new': new['targets'][metric]}
               for metric in sorted(NUMERIC) if old['targets'][metric] != new['targets'][metric]]
    return dict(candidate_fingerprint=candidate, same_candidate=True, changed_targets=changed,
                before=before, after=after, amendment=amendment,
                note='Comparison records impact; it does not grant approval for material risk changes.')
