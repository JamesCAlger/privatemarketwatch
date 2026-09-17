"""Footprint gate: cohort-wide counts between two sealed identity bundles."""
from pathlib import Path
import duckdb
import pandas as pd
import pytest

from scripts.candidate_footprint import compute_footprint, compare_footprints

ENC = {'0001803498': {'reporting_entity_suffixes': ['Emerald JV LP'],
                      'reporting_entity_identifier_suffixes': ['Emerald JV LP']}}


def _bundle(tmp_path, name, e_pairs, labelled_parent=0):
    b = tmp_path / name / 'bundle'
    b.mkdir(parents=True)
    with duckdb.connect() as con:
        holdings = pd.DataFrame([
            dict(row_id=f'R{i}', cik='0001803498', issuer_name='Acme LLC', fair_value=100.0,
                 accounting_record_class='parent_schedule', position_id=f'P{i}', entity_id='E1')
            for i in range(10)] + [
            dict(row_id=f'L{i}', cik='0001803498', issuer_name='Beta Co., Emerald JV LP', fair_value=5.0,
                 accounting_record_class='parent_schedule', position_id=f'L{i}', entity_id='E2')
            for i in range(labelled_parent)])
        matches = pd.DataFrame([dict(match_method='E_entity_fingerprint', begin_fair_value=100.0, end_fair_value=100.0)] * e_pairs
                               + [dict(match_method='B1b_position_key', begin_fair_value=100.0, end_fair_value=100.0)] * 100)
        edges = pd.DataFrame([dict(edge_type='match_pair')] * 500)
        lookup = pd.DataFrame([dict(entity_id='E1', normalized_name='acme'), dict(entity_id='E2', normalized_name='joint:beta co and gamma')])
        for frame, fname in ((holdings, 'private_markets_holdings'), (matches, 'position_matches'),
                             (edges, 'position_id_edges'), (lookup, 'entity_lookup')):
            con.register('f', frame)
            con.execute(f"COPY f TO '{(b / (fname + '.parquet')).as_posix()}' (FORMAT PARQUET)")
            con.unregister('f')
    return b


def test_equal_bundles_raise_no_flags(tmp_path):
    a = compute_footprint(_bundle(tmp_path, 'a', 10), ENC)
    b = compute_footprint(_bundle(tmp_path, 'b', 10), ENC)
    assert compare_footprints(b, a) == []


def test_tenfold_tier_growth_is_flagged(tmp_path):
    prior = compute_footprint(_bundle(tmp_path, 'prior', 100), ENC)
    current = compute_footprint(_bundle(tmp_path, 'current', 1000), ENC)
    flags = compare_footprints(current, prior)
    assert [f['metric'] for f in flags] == ['match_method.E_entity_fingerprint']
    assert flags[0]['ratio'] == pytest.approx(10.0)


def test_small_populations_are_not_flagged_on_ratio(tmp_path):
    prior = compute_footprint(_bundle(tmp_path, 'prior', 3), ENC)
    current = compute_footprint(_bundle(tmp_path, 'current', 30), ENC)
    assert compare_footprints(current, prior) == []


def test_labelled_row_in_parent_scope_is_always_flagged(tmp_path):
    prior = compute_footprint(_bundle(tmp_path, 'prior', 10), ENC)
    current = compute_footprint(_bundle(tmp_path, 'current', 10, labelled_parent=2), ENC)
    flags = compare_footprints(current, prior)
    assert flags == [dict(metric='labelled_parent_rows.0001803498', prior=0, current=2, ratio=None,
                          reason='reporting-entity label in parent scope')]


def test_footprint_reports_joint_entities_and_singletons(tmp_path):
    fp = compute_footprint(_bundle(tmp_path, 'a', 10), ENC)
    assert fp['joint_entities'] == 1
    assert fp['positions'] == 10 and fp['singletons'] == 10
    assert fp['scope_rows']['parent_schedule'] == 10
