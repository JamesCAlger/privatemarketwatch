"""Pure shadow routing; never writes queues or confers audited-holdings status.

Independent review records are separate inputs, not assertions supplied by Jev
or inferred from a builder's ready status. Production clearance is unsupported.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from decimal import Decimal
import hashlib
import json
import math
from typing import Any

from pipeline.jev_bundles import RULES, number, rule_fires

SCHEMA = 'jev-shadow-receipt.v1'
REQUIRED_CHECKS = ('identity', 'period', 'scope', 'units', 'notes', 'candidate_recall')


def fingerprint(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                     ensure_ascii=True, allow_nan=False).encode()).hexdigest()


@dataclass(frozen=True)
class Policy:
    version: str = 'shadow-pilot.v1'
    decision_cutoff: float = 0.75
    source_cutoff: float = 0.75
    model: str = 'jev-1.13.0'
    eligible_rules: tuple[str, ...] = ('C107', 'X08')
    high_error_rules: tuple[str, ...] = ()

    def __post_init__(self):
        for value in (self.decision_cutoff, self.source_cutoff):
            if not valid_confidence(value):
                raise ValueError('Confidence cutoffs must be finite numbers in [0, 1]')
        if not self.version or not self.model:
            raise ValueError('Policy and model versions are required')


def valid_confidence(value):
    return (not isinstance(value, bool) and isinstance(value, (int, float))
            and 0 <= value <= 1)


def _json_observation(value):
    """Retain malformed non-finite provider values without losing the receipt."""
    if isinstance(value, float) and not math.isfinite(value):
        return {'invalid_non_finite_number': str(value)}
    if isinstance(value, dict):
        return {key: _json_observation(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_observation(item) for item in value]
    return value


def evidence_failures(bundle, source_id, audit):
    failures = []
    candidates = [c for c in bundle.get('source_candidates', []) if c.get('evidence_id') == source_id]
    if len(candidates) != 1:
        return ['source_choice_not_unique']
    candidate = candidates[0]
    if candidate.get('blocking_reasons'):
        failures.append('candidate_evidence_blocked')
    identity = candidate.get('identity_evidence', {})
    if identity.get('blocking_reasons') or identity.get('output_class_compatible') is False:
        failures.append('candidate_identity_conflict')
    if candidate.get('period_evidence', {}).get('conflict'):
        failures.append('candidate_period_conflict')
    if candidate.get('report_date') != bundle['output_position'].get('report_date'):
        failures.append('candidate_period_mismatch')
    # A model's false-alarm answer cannot contradict its own selected row.
    # This is a veto only: agreement still requires independent source review.
    for field in bundle['rule']['fields']:
        prepared = candidate.get('source_values', {}).get(field, {})
        source = number(prepared.get('amount'))
        published = number(bundle['output_position'].get(field))
        unit = number(prepared.get('display_unit'))
        if (source is None or published is None or unit is None or unit <= 0
                or prepared.get('currency') != 'USD'):
            failures.append('selected_source_value_unresolved:' + field)
        elif abs(published - source) > unit / Decimal(2):
            failures.append('selected_source_value_mismatch:' + field)
    if not audit:
        return failures + ['independent_review_missing']
    if audit.get('method') != 'independent_source_review' or not audit.get('reviewer'):
        failures.append('independent_review_unidentified')
    if audit.get('bundle_fingerprint') != fingerprint(bundle):
        failures.append('independent_review_stale_bundle')
    if not bundle.get('filing', {}).get('sha256') or audit.get('source_sha256') != bundle['filing']['sha256']:
        failures.append('independent_review_source_mismatch')
    if audit.get('evidence_id') != source_id:
        failures.append('independent_review_different_position')
    if any(audit.get('checks', {}).get(key) is not True for key in REQUIRED_CHECKS):
        failures.append('independent_evidence_checks_incomplete')
    if not audit.get('citations'):
        failures.append('independent_source_citations_missing')
    for field in bundle['rule']['fields']:
        reviewed = audit.get('source_values', {}).get(field, {})
        source, published = number(reviewed.get('amount')), number(bundle['output_position'].get(field))
        unit = number(reviewed.get('display_unit'))
        if source is None or published is None or unit is None or unit <= 0 or reviewed.get('currency') != 'USD':
            failures.append('independent_value_unresolved:' + field)
            continue
        prepared = candidate.get('source_values', {}).get(field, {})
        if number(prepared.get('amount')) != source or number(prepared.get('display_unit')) != unit:
            failures.append('builder_review_value_conflict:' + field)
        # Recompute; never trust the model or the bundle's comparison boolean.
        if abs(published - source) > unit / Decimal(2):
            failures.append('source_value_mismatch:' + field)
    return failures


def route_flag(bundle: dict, result: dict | None, audit: dict | None, *,
               policy: Policy | None = None, expected_provenance: dict | None = None,
               parent_review_id: str | None = None) -> dict:
    policy = policy or Policy()
    rule_id = bundle.get('rule', {}).get('id')
    flag = bundle.get('flag', {})
    reasons = []
    if rule_id in policy.high_error_rules or flag.get('evidence_strength') == 'STRONG' or flag.get('severity') in {'FAIL', 'BLOCKER', 'ERROR'}:
        reasons.append('strong_or_high_error_rule')
    if flag.get('rule_id') != rule_id:
        reasons.append('flag_rule_mismatch')
    if rule_id not in policy.eligible_rules or rule_id not in RULES:
        reasons.append('unsupported_rule')
    if bundle.get('evidence_status', {}).get('status') != 'ready_for_model' or bundle.get('evidence_status', {}).get('blocking_reasons'):
        reasons.append('bundle_not_eligible')
    provenance = bundle.get('provenance', {})
    for key in ('holdings_sha256', 'flags_sha256', 'builder_sha256'):
        if not provenance.get(key):
            reasons.append('missing_provenance:' + key)
        if expected_provenance is None or expected_provenance.get(key) != provenance.get(key):
            reasons.append('stale_or_unverified_provenance:' + key)
    if rule_id in RULES:
        if bundle['rule'].get('fields') != RULES[rule_id]['fields'] or bundle['rule'].get('predicate') != RULES[rule_id]['predicate']:
            reasons.append('rule_contract_mismatch')
        if not rule_fires(rule_id, bundle.get('output_position', {})):
            reasons.append('flag_predicate_not_current')
    if not reasons:
        if result is None:
            reasons.append('not_submitted')
        elif not isinstance(result, dict) or result.get('status') != 'success':
            reasons.append('provider_or_schema_failure')
        elif result.get('model') != policy.model or result.get('bundle_fingerprint') != fingerprint(bundle):
            reasons.append('model_or_request_version_mismatch')
        elif result.get('decision') not in {'real_error', 'false_alarm', 'ambiguous'}:
            reasons.append('unknown_decision')
        elif result['decision'] != 'false_alarm':
            reasons.append('jev_' + result['decision'])
        elif not valid_confidence(result.get('decision_confidence')) or not valid_confidence(result.get('source_confidence')):
            reasons.append('invalid_or_missing_confidence')
        elif result['decision_confidence'] < policy.decision_cutoff or result['source_confidence'] < policy.source_cutoff:
            reasons.append('low_confidence')
        else:
            reasons.extend(evidence_failures(bundle, result.get('source_id'), audit))
    route = 'candidate_clearance' if not reasons else ('pending' if reasons == ['not_submitted'] else 'b1')
    identity = {key: flag.get(key) for key in ('row_id', 'cik', 'report_date', 'rule_id')}
    receipt = {'schema_version': SCHEMA, 'flag': identity, 'parent_review_id': parent_review_id,
               'bundle_fingerprint': fingerprint(bundle), 'policy': asdict(policy),
               'route': route, 'reasons': reasons or ['source_supported_false_alarm'],
               'model_result': _json_observation(result), 'independent_review_fingerprint': fingerprint(audit) if audit else None,
               'production_clearance_allowed': False, 'b1_work_suppressed': False,
               'audit_required': route == 'candidate_clearance'}
    receipt['receipt_id'] = fingerprint(receipt)
    return receipt


def project_groups(receipts: list[dict], expected_members: dict[str, list[str]]) -> list[dict]:
    """Only a fully accounted group can be a candidate; shadow never suppresses it."""
    by_id = {r['receipt_id']: r for r in receipts}
    if len(by_id) != len(receipts):
        raise ValueError('Duplicate receipts')
    keys = [tuple(r['flag'].get(k) for k in ('cik', 'report_date', 'row_id', 'rule_id')) for r in receipts]
    if len(set(keys)) != len(keys):
        raise ValueError('Duplicate current flag evaluations')
    declared = [member for members in expected_members.values() for member in members]
    if len(set(declared)) != len(declared):
        raise ValueError('Receipt assigned to multiple groups')
    if set(by_id) - set(declared):
        raise ValueError('Unassigned receipts would be omitted from group accounting')
    projected = []
    for group, members in expected_members.items():
        if len(set(members)) != len(members) or not members:
            raise ValueError('Each group requires distinct expected receipt IDs')
        known = [by_id[m] for m in members if m in by_id]
        if any(r.get('parent_review_id') != group for r in known):
            raise ValueError('Receipt belongs to a different parent group')
        complete = len(known) == len(members)
        candidate = complete and all(r['route'] == 'candidate_clearance' for r in known)
        projected.append({'parent_review_id': group, 'expected_members': len(members),
                          'accounted_members': len(known), 'all_members_candidate': candidate,
                          'keep_in_b1_worklist': True,
                          'missing_receipts': [m for m in members if m not in by_id]})
    return projected
