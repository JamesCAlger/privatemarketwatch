"""Reject ambiguous parent identity and partial group coverage before screening."""
from copy import deepcopy

import pytest

from pipeline.jev_parent_inventory import parent_inventory


def parent(**changes):
    return dict({'review_id': 'review-a', 'engine': 'row_validation', 'period_kind': 'report_date',
        'cik': '0001702510', 'unit_label': '0001702510', 'period': '2026-03-31',
        'report_date': '2026-03-31', 'rule_name': 'C107', 'n_units': '1'}, **changes)


def issue(**changes):
    return dict({'cik': '1702510', 'report_date': '2026-03-31', 'rule_id': 'C107',
        'row_id': 'ROW-a', 'dataset': 'private_markets_holdings', 'source': 'bdc'}, **changes)


def build(parents, issues):
    return parent_inventory(parents, issues, queue_sha256='a'*64, issues_sha256='b'*64)


def test_complete_group_retains_every_member_without_certifying_clearance():
    parents, issues = [parent(n_units='2')], [issue(row_id='ROW-b'), issue()]
    before = deepcopy((parents, issues))
    result = build(parents, issues)
    assert [m['row_id'] for m in result['parents'][0]['members']] == ['ROW-a', 'ROW-b']
    assert all(result[k] is False for k in ('production_clearance_allowed', 'b1_work_suppressed',
        'source_truth_verified', 'snapshot_hashes_verified', 'full_queue_uniqueness_verified'))
    assert (parents, issues) == before


@pytest.mark.parametrize('change', [
    {'report_date': ''}, {'cik': ''}, {'period': '2026-03-31 00:00:00'},
    {'report_date': '2026-02-30'}, {'period': '2025-12-31'}, {'unit_label': '0001860424'},
    {'engine': 'source_recon'}, {'period_kind': 'name'}, {'rule_name': ''},
    {'n_units': '1.0'}, {'n_units': '0'}, {'n_units': True},
])
def test_parent_contract_rejects_ambiguous_or_unsupported_localization(change):
    with pytest.raises(ValueError):
        build([parent(**change)], [issue()])


def test_cross_quarter_reused_review_id_is_rejected():
    with pytest.raises(ValueError, match='duplicate parent'):
        build([parent(), parent(period='2025-12-31', report_date='2025-12-31')],
              [issue(), issue(report_date='2025-12-31')])


def test_distinct_cross_quarter_ids_keep_snapshot_local_row_identity():
    result = build([parent(), parent(review_id='review-b', period='2025-12-31', report_date='2025-12-31')],
                   [issue(), issue(report_date='2025-12-31')])
    assert len(result['parents']) == 2


def test_same_group_cannot_have_two_different_parent_ids():
    with pytest.raises(ValueError, match='Multiple parents'):
        build([parent(), parent(review_id='review-b')], [issue()])


@pytest.mark.parametrize('members', [[], [issue(), issue(row_id='ROW-b')]])
def test_partial_or_excessive_membership_is_rejected(members):
    with pytest.raises(ValueError, match='membership'):
        build([parent()], members)


def test_duplicate_issue_is_not_hidden_by_a_set():
    with pytest.raises(ValueError, match='Duplicate member'):
        build([parent(n_units='2')], [issue(), issue()])


@pytest.mark.parametrize('change', [{'row_id': ''}, {'source': 'nport'},
    {'dataset': 'fund_financials'}, {'rule_id': 'X02'}, {'report_date': '2025-12-31'}])
def test_unknown_or_foreign_member_is_rejected(change):
    with pytest.raises(ValueError):
        build([parent()], [issue(**change)])


def test_no_unhashed_snapshot_contract():
    with pytest.raises(ValueError, match='hashes'):
        parent_inventory([parent()], [issue()], queue_sha256='', issues_sha256='b'*64)


def test_membership_fingerprint_changes_with_evidence():
    first = build([parent()], [issue(value='-1')])
    second = build([parent()], [issue(value='-2')])
    assert first['inventory_fingerprint'] != second['inventory_fingerprint']
