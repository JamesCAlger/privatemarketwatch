"""Fail-closed parent/member accounting for a future shadow screening sidecar."""
from datetime import date
import re

from pipeline.jev_screening import fingerprint


def _period(value):
    if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
        raise ValueError('Canonical report date required; no implicit timestamp repair')
    return date.fromisoformat(value).isoformat()


def _cik(value):
    text = str(value)
    if not re.fullmatch(r'\d{1,10}', text) or int(text) <= 0:
        raise ValueError('Explicit numeric CIK required')
    return str(int(text)).zfill(10)


def parent_inventory(parents, issues, *, queue_sha256, issues_sha256):
    """Validate supplied complete groups; hashes must be verified by the caller.

    This does not load a queue, certify source truth, grant clearance, or claim
    uniqueness outside the supplied snapshot slice. The caller must check full
    queue ID uniqueness before selecting parents.
    """
    if not 0 < len(parents) <= 100 or len(issues) > 10000:
        raise ValueError('Bounded nonempty parent selection required')
    if any(not isinstance(v, str) or not re.fullmatch(r'[0-9a-f]{64}', v)
           for v in (queue_sha256, issues_sha256)):
        raise ValueError('Snapshot hashes required')
    ids, groups = set(), {}
    for parent in parents:
        review_id = parent.get('review_id')
        if not isinstance(review_id, str) or not review_id.strip() or review_id in ids:
            raise ValueError('Missing or duplicate parent review ID')
        ids.add(review_id)
        if parent.get('engine') != 'row_validation' or parent.get('period_kind') != 'report_date':
            raise ValueError('Unsupported parent engine or period kind')
        cik, period = _cik(parent.get('cik')), _period(parent.get('report_date'))
        if _period(parent.get('period')) != period or _cik(parent.get('unit_label')) != cik:
            raise ValueError('Contradictory parent localization')
        rule = parent.get('rule_name')
        if not isinstance(rule, str) or not rule.strip():
            raise ValueError('Parent rule required')
        key = (cik, period, rule)
        if key in groups:
            raise ValueError('Multiple parents for one fund/period/rule')
        n_units = parent.get('n_units')
        if not re.fullmatch(r'[1-9]\d*', str(n_units)):
            raise ValueError('Positive integer parent member count required')
        groups[key] = {'parent': parent, 'expected_count': int(n_units), 'members': []}
    member_keys = set()
    for issue in issues:
        key = (_cik(issue.get('cik')), _period(issue.get('report_date')), issue.get('rule_id'))
        if key not in groups:
            raise ValueError('Issue belongs to an unselected parent')
        if issue.get('dataset') != 'private_markets_holdings' or issue.get('source') != 'bdc':
            raise ValueError('Unsupported dataset/source requires B1')
        row_id = issue.get('row_id')
        if not isinstance(row_id, str) or not row_id.strip():
            raise ValueError('Unidentified member requires B1')
        member_key = (*key, row_id)
        if member_key in member_keys:
            raise ValueError('Duplicate member identity requires explicit resolution')
        member_keys.add(member_key)
        groups[key]['members'].append({'cik': key[0], 'report_date': key[1], 'rule_id': key[2],
                                       'row_id': row_id, 'issue_fingerprint': fingerprint(issue)})
    result = []
    for key, group in sorted(groups.items()):
        if len(group['members']) != group['expected_count']:
            raise ValueError('Incomplete or excessive parent membership')
        result.append({'parent_review_id': group['parent']['review_id'],
                       'parent_fingerprint': fingerprint(group['parent']),
                       'members': sorted(group['members'], key=lambda m: m['row_id'])})
    inventory = {'schema_version': 'jev-parent-inventory.v1', 'queue_sha256': queue_sha256,
        'issues_sha256': issues_sha256, 'parents': result,
        'full_queue_uniqueness_verified': False, 'snapshot_hashes_verified': False,
        'source_truth_verified': False, 'production_clearance_allowed': False,
        'b1_work_suppressed': False}
    inventory['inventory_fingerprint'] = fingerprint(inventory)
    return inventory
