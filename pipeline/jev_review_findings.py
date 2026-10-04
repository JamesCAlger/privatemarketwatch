"""Validate source-first findings as records, never as clearance certificates."""
from copy import deepcopy
from datetime import datetime
from decimal import Decimal, InvalidOperation
import math

from pipeline.jev_screening import REQUIRED_CHECKS, fingerprint


def _text(value):
    return isinstance(value, str) and bool(value.strip())


def _coordinates(value):
    # Normalize presentation only; do not guess that different free-text
    # coordinate schemes refer to the same source location.
    return ' '.join(value.casefold().split())


def _timestamp(value):
    if not _text(value):
        raise ValueError('Review timestamps are required')
    try:
        result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError as exc:
        raise ValueError('Invalid review timestamp') from exc
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError('Review timestamps require a timezone')
    return result


def _number(value):
    if isinstance(value, bool):
        raise ValueError('Boolean is not a source amount')
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError('Invalid source amount or display unit') from exc
    if not result.is_finite():
        raise ValueError('Nonfinite source amount or display unit')
    return result


def freeze_findings(prepared, completed):
    """Structural validation cannot prove reviewer independence or source truth."""
    if prepared.get('schema_version') != 'jev-blind-source-review.v1':
        raise ValueError('Unsupported review input')
    if prepared.get('production_clearance_enabled') is not False:
        raise ValueError('Shadow input required')
    envelope = lambda value: {k: v for k, v in value.items() if k != 'review_form'}
    if envelope(prepared) != envelope(completed):
        raise ValueError('Prepared evidence envelope changed')
    form = completed.get('review_form')
    if not isinstance(form, dict) or not _text(form.get('reviewer')):
        raise ValueError('Named reviewer required')
    if form.get('source_first_attestation') is not True:
        raise ValueError('Explicit source-first attestation required')
    start, end = _timestamp(form.get('started_at')), _timestamp(form.get('completed_at'))
    seconds = form.get('active_seconds')
    if (end < start or isinstance(seconds, bool) or not isinstance(seconds, (int, float))
            or not math.isfinite(seconds) or seconds <= 0 or seconds > (end - start).total_seconds()):
        raise ValueError('Invalid active review timing')
    checks = form.get('checks')
    if not isinstance(checks, dict) or set(checks) != set(REQUIRED_CHECKS):
        raise ValueError('Exact source-check inventory required')
    if any(value is not None and type(value) is not bool for value in checks.values()):
        raise ValueError('Checks must be true, false or null')
    disposition = form.get('disposition')
    if disposition not in {'false_alarm', 'real_error', 'unresolved'} or not _text(form.get('reason')):
        raise ValueError('Disposition and reason required')
    questions = form.get('unresolved_questions')
    if not isinstance(questions, list) or any(not _text(q) for q in questions):
        raise ValueError('Unresolved questions must be text')
    if disposition == 'unresolved' and not questions:
        raise ValueError('Unresolved finding requires an explicit question')
    if disposition == 'false_alarm' and (not all(v is True for v in checks.values()) or questions):
        raise ValueError('False-alarm finding requires complete source checks')
    citations = form.get('citations')
    inventory = form.get('candidate_inventory')
    values = form.get('source_values')
    if not isinstance(citations, list) or not isinstance(inventory, list) or not isinstance(values, dict):
        raise ValueError('Structured source evidence required')
    if disposition != 'unresolved' and (not citations or not inventory or not _text(form.get('source_coordinates'))):
        raise ValueError('Resolved finding requires source coordinates, citations and candidate inventory')
    for citation in citations:
        if (not isinstance(citation, dict) or citation.get('source_sha256') != prepared['source']['sha256']
                or not _text(citation.get('coordinates')) or not _text(citation.get('supports'))):
            raise ValueError('Citation must bind original source and describe its support')
    for candidate in inventory:
        if (not isinstance(candidate, dict) or not _text(candidate.get('coordinates'))
                or candidate.get('treatment') not in {'selected', 'excluded', 'unresolved'}
                or not _text(candidate.get('reason'))):
            raise ValueError('Each candidate requires coordinates, treatment and reason')
    coordinates = [_coordinates(c['coordinates']) for c in inventory]
    if len(set(coordinates)) != len(coordinates):
        raise ValueError('Duplicate candidate coordinates require a single explicit treatment')
    if disposition == 'false_alarm' and sum(c['treatment'] == 'selected' for c in inventory) != 1:
        raise ValueError('False-alarm finding requires one selected source position')
    if disposition == 'false_alarm' and any(c['treatment'] == 'unresolved' for c in inventory):
        raise ValueError('Unresolved candidate prevents a false-alarm finding')
    if disposition == 'false_alarm':
        selected = next(c for c in inventory if c['treatment'] == 'selected')
        coordinate = _coordinates(selected['coordinates'])
        if _coordinates(form['source_coordinates']) != coordinate:
            raise ValueError('Source coordinates differ from the selected candidate')
        if not any(_coordinates(c['coordinates']) == coordinate for c in citations):
            raise ValueError('A citation must identify the selected source coordinates')
    if disposition == 'false_alarm' and any(field not in values for field in prepared['rule']['fields']):
        raise ValueError('All disputed source amounts required')
    for field, value in values.items():
        if field not in prepared['rule']['fields'] or not isinstance(value, dict):
            raise ValueError('Unexpected source value')
        amount = _number(value.get('amount'))
        unit = _number(value.get('display_unit'))
        if unit <= 0 or value.get('currency') != 'USD':
            raise ValueError('Supported source currency and positive precision required')
        if disposition == 'false_alarm':
            position = prepared['position']
            if position.get(field + '_currency') != 'USD':
                raise ValueError('Output currency is not established')
            if abs(_number(position.get(field)) - amount) > unit / 2:
                raise ValueError('False-alarm finding contradicts independently recorded amount')
    result = {'schema_version': 'jev-source-findings.v1',
        'prepared_input_fingerprint': fingerprint(prepared),
        'completed_input_fingerprint': fingerprint(completed),
        'review_id': prepared['review_id'], 'snapshot': deepcopy(prepared['snapshot']),
        'source': deepcopy(prepared['source']), 'findings': deepcopy(form),
        'stage': 'source_first_findings_only', 'independence_verified': False,
        'bundle_audit_completed': False, 'production_clearance_enabled': False,
        'limitation': 'Valid record structure and reviewer attestation do not establish independent source truth.'}
    result['findings_id'] = fingerprint(result)
    return result
