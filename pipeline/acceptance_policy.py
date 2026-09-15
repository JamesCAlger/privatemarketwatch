"""Read versioned owner adoptions without creating or inferring approvals.

An absent or explicitly pending section stays pending. Adopted sections must
identify the decision and the exact evidence population they govern. Merely
providing a numeric floor or a truthy status is not an adoption.
"""
from __future__ import annotations

from pathlib import Path

from pipeline.programme.core import ContractError, read_json, sha


def load(path, *, evidence_files):
    pending = dict(denominator_adoption=None, field_assessability_floors={},
        field_floor_adoption=None, source_roster_certified=False, source_roster_currency=None)
    if path is None:
        return pending, {}
    path = Path(path).resolve()
    data = read_json(path)
    if data.get('format_version') != 1:
        raise ContractError('Unsupported acceptance policy format')
    records = {str(path): sha(path)}

    def decision(section):
        record = section.get('decision', {})
        if not isinstance(record, dict) or not record.get('path') or not record.get('sha256'):
            raise ContractError('An adopted policy requires its recorded decision')
        target = (path.parent/record['path']).resolve()
        if not target.is_file() or sha(target) != record['sha256']:
            raise ContractError('Acceptance policy decision changed or is unavailable')
        records[str(target)] = record['sha256']
        return dict(path=str(target), sha256=record['sha256'])

    def binding(section, names):
        expected = section.get('evidence_sha256', {})
        for name in names:
            record = evidence_files.get(name)
            if not record or expected.get(name) != record['sha256']:
                raise ContractError('Acceptance policy belongs to different '+name+' evidence')

    allowed = {'field_floors': 'adopted', 'denominator': 'adopted', 'source_roster': 'certified'}
    for name, accepted in allowed.items():
        section = data.get(name, {})
        if not isinstance(section, dict):
            raise ContractError('Invalid acceptance policy section: '+name)
        status = section.get('status', 'pending')
        if status == 'pending':
            continue
        if status != accepted:
            raise ContractError('Unrecognized acceptance policy status: '+name)
        authority = decision(section)
        if name == 'field_floors':
            from pipeline.field_assessment import FIELDS
            from pipeline.categorical_field_assessment import FIELDS as OTHER_FIELDS
            floors = section.get('floors')
            if not isinstance(floors, dict) or not floors or set(floors)-set(FIELDS+OTHER_FIELDS):
                raise ContractError('Invalid or unsupported field assessability floors')
            if any(isinstance(v, bool) or not isinstance(v, (float,int)) or not 0 <= v <= 1
                   for v in floors.values()):
                raise ContractError('Field floors must be finite proportions between zero and one')
            # The measurement supporting adoption is immutable. It can be a
            # prior experiment; the adopted floors need not be reapproved for
            # every new candidate. A missing field still blocks that field.
            measurement = section.get('measurement', {})
            if not isinstance(measurement, dict):
                raise ContractError('Missing assessability measurement')
            measured = decision(dict(decision=measurement))
            pending.update(field_assessability_floors=floors,
                field_floor_adoption=dict(decision=authority, measurement=measured))
        elif name == 'denominator':
            binding(section, ('obligations','exclusions'))
            pending['denominator_adoption'] = authority
        else:
            binding(section, ('contexts','reconciliation'))
            currency = section.get('currency')
            if not isinstance(currency,str) or len(currency)!=3 or not currency.isupper() or not currency.isalpha():
                raise ContractError('Certified source roster requires an explicit currency')
            pending.update(source_roster_certified=True,source_roster_currency=currency,
                           source_roster_certification=authority)
    return pending, records


def verify(records):
    for name, expected in records.items():
        if not Path(name).is_file() or sha(name) != expected:
            raise ContractError('Acceptance policy input changed during evaluation: '+name)
