"""Lineage consistency must not hide wrong donors or ambiguous earliest rows."""
import pytest

from scripts.build_jev_cost_lineage import verify_lineage


@pytest.fixture
def lineage():
    return {
        'output': {'cost_source': 'first_observed_fv_proxy', 'cost_reported': None,
                   'cost': '-39000', 'cik': '0000000001', 'position_id': 'snapshot-position'},
        'donor': {'row_id': 'ROW-DONOR', 'report_date': '2025-12-31', 'fair_value': '-39000',
                  'cik': '0000000001', 'position_id': 'snapshot-position'},
        'audit': {'method': 'first_observed_fv_proxy', 'donor_row_id': 'ROW-DONOR',
                  'donor_date': '2025-12-31', 'donor_release': 'release', 'proxy_value': '-39000'},
        'state': {'cost_state': 'absent'}, 'donor_state': {'donor_valid': 'True'},
        'earliest': {'candidate_count': 1, 'donor_row_id': 'ROW-DONOR', 'donor_date': '2025-12-31'},
        'release_id': 'release',
    }


def test_valid_negative_proxy_has_internal_lineage_only(lineage):
    assert all(verify_lineage(**lineage).values())


@pytest.mark.parametrize('part,field,value,check', [
    ('earliest', 'candidate_count', 2, 'unique_earliest_valid_donor'),
    ('earliest', 'donor_row_id', 'OTHER', 'unique_earliest_valid_donor'),
    ('donor', 'position_id', 'different', 'same_snapshot_position'),
    ('donor', 'cik', '0000000002', 'same_fund'),
    ('donor', 'fair_value', '-27000', 'proxy_value_matches'),
    ('audit', 'donor_release', 'old-release', 'same_release'),
    ('audit', 'donor_date', '2025-09-30', 'donor_date_link'),
    ('donor_state', 'donor_valid', 'False', 'donor_marked_valid'),
    ('output', 'cost_reported', '-39000', 'reported_cost_absent'),
    ('output', 'cost', 'NaN', 'proxy_value_matches'),
])
def test_inconsistent_lineage_is_explicit(lineage, part, field, value, check):
    lineage[part][field] = value
    assert verify_lineage(**lineage)[check] is False
