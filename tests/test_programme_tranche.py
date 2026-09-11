"""Integration comparisons distinguish ID renumbering from changed membership."""
import duckdb
import pytest

from pipeline.programme.core import ContractError
from scripts.programme_tranche.measure_candidate import partition_difference
from scripts.programme_tranche.check_preservation import equivalent


def fixtures(connection, before, after):
    for name, rows in (('old_identity', before), ('h', after)):
        connection.execute('CREATE TABLE ' + name + '(row_id VARCHAR,position_id VARCHAR,entity_id VARCHAR)')
        connection.executemany('INSERT INTO ' + name + ' VALUES (?,?,?)',
                               [(row, position, position) for row, position in rows])


@pytest.mark.parametrize('field', ['position_id', 'entity_id'])
def test_generated_identifier_renumbering_is_not_a_merge(field):
    with duckdb.connect() as connection:
        fixtures(connection, [('source-a','P1'),('source-b','P1'),('source-c','P2')],
                             [('source-c','P999'),('source-b','P88'),('source-a','P88')])
        assert partition_difference(connection,field) == 0


@pytest.mark.parametrize('before,after', [
    ([('loan','P1'),('equity','P2')], [('loan','P3'),('equity','P3')]),
    ([('q1','P1'),('q2','P1')], [('q1','P2'),('q2','P3')]),
    ([('row','P1'),('row','P1')], [('row','P2')]),
    ([('a','P1'),('b',None)], [('a',None),('b','P2')]),
])
def test_real_merge_split_multiplicity_or_assignment_change_is_detected(before,after):
    with duckdb.connect() as connection:
        fixtures(connection,before,after)
        assert partition_difference(connection,'position_id') > 0


def test_missing_observation_key_cannot_certify_identity_stability():
    with duckdb.connect() as connection:
        fixtures(connection,[(None,'P1')],[(None,'P2')])
        with pytest.raises(ContractError):
            partition_difference(connection,'position_id')


def test_derived_delta_roundoff_is_recorded_at_the_source_scale():
    before = dict(fv_current=350_000_000_000.0, fv_baseline=349_999_999_900.0, fv_delta=100.0)
    after = dict(before, fv_current=before['fv_current'] + .02)
    after['fv_delta'] = after['fv_current'] - after['fv_baseline']
    disposition = []
    assert equivalent(before, after, roundoff=disposition) == []
    assert len(disposition) == 1
    assert disposition[0]['source_totals_within_existing_noise_rule'] is True


@pytest.mark.parametrize('invalid_subtraction', [False, True])
def test_material_source_change_or_invented_delta_never_passes_as_roundoff(invalid_subtraction):
    before = dict(fv_current=350_000_000_000.0, fv_baseline=349_999_999_900.0, fv_delta=100.0)
    after = dict(before, fv_current=before['fv_current'] + 1.0)
    after['fv_delta'] = after['fv_current'] - after['fv_baseline']
    if invalid_subtraction:
        after = dict(before, fv_delta=100.00001)
    assert equivalent(before, after)
