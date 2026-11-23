import pandas as pd
import pytest

from pipeline import reviewed_position_identity as identity
from tests.test_reviewed_position_identity import frame, match, configure


def test_wrong_tranches_removed_and_source_backed_adjacent_payload_emitted(monkeypatch):
    configure(monkeypatch, {'c-1': '750', 'c-2': '750', 'c-3': '265'})
    rows = frame([dict(report_date='2025-06-30', src_context_id='c-1'),
                  dict(report_date='2025-09-30', src_context_id='c-2'),
                  dict(report_date='2025-09-30', src_context_id='c-3')])
    rows['fair_value'] = [50000, 51000, 52000]
    rows['principal_amount'] = [52400, 53800, 52200]
    pairs = match('2025-06-30', '2025-09-30', 50000, 52000)
    output = identity.reconcile_financial_matches(pairs, rows, emit_missing=True)
    assert len(output) == 1
    pair = output.iloc[0]
    assert pair.match_method == 'REVIEWED_context_identity'
    assert pair.begin_principal_amount == 52400
    assert pair.end_principal_amount == 53800
    assert pair.end_fair_value == 51000


def test_unproven_refinance_gap_not_emitted(monkeypatch):
    configure(monkeypatch, {'c-1': 'dec-2025', 'c-2': 'new-2026'})
    rows = frame([dict(report_date='2025-12-31', src_context_id='c-1'),
                  dict(report_date='2026-03-31', src_context_id='c-2')])
    assert identity.reconcile_financial_matches(match('2025-12-31', '2026-03-31'), rows, emit_missing=True).empty


def test_mapped_to_unmapped_forbidden_default_unchanged(monkeypatch):
    configure(monkeypatch, {'c-1': 'term'})
    rows = frame([dict(report_date='2025-03-31', src_context_id='c-1'),
                  dict(report_date='2025-06-30', src_context_id='c-2')])
    pairs = match('2025-03-31', '2025-06-30')
    assert identity.reconcile_financial_matches(pairs, rows).empty
    monkeypatch.setattr(identity, 'load_encodings', lambda: {})
    pd.testing.assert_frame_equal(identity.reconcile_financial_matches(pairs, rows), pairs)


def test_raw_a_alias_resolves_actual_begin_instead_of_end_cleaned_name(monkeypatch):
    configure(monkeypatch, {'c-1': 'term', 'c-2': 'term'})
    rows = frame([dict(report_date='2025-03-31', src_context_id='c-1'),
                  dict(report_date='2025-06-30', src_context_id='c-2')])
    rows['issuer_name'] = ['Old Borrower', 'New Borrower']
    rows['bdc_investment_identifier'] = ['Malformed Member', 'Malformed Member']
    rows['principal_amount'] = [120, 130]
    pairs = match('2025-03-31', '2025-06-30', method='A_within_filing')
    pairs['_identity_begin_name'] = 'Malformed Member'
    pairs['_identity_end_name'] = 'Malformed Member'
    output = identity.reconcile_financial_matches(pairs, rows, emit_missing=True)
    assert len(output) == 1
    assert output.iloc[0].begin_issuer_name == 'Old Borrower'
    assert output.iloc[0].begin_principal_amount == 120
    assert output.iloc[0].end_principal_amount == 130


def test_same_value_reviewed_endpoint_ambiguity_fails_closed(monkeypatch):
    configure(monkeypatch, {'c-1': 'first', 'c-2': 'second', 'c-3': 'first'})
    rows = frame([dict(report_date='2025-03-31', src_context_id='c-1'),
                  dict(report_date='2025-03-31', src_context_id='c-2'),
                  dict(report_date='2025-06-30', src_context_id='c-3')])
    with pytest.raises(ValueError, match='endpoint is ambiguous'):
        identity.reconcile_financial_matches(match('2025-03-31', '2025-06-30'), rows)
    trigger = match('2025-03-31', '2025-06-30')
    pd.testing.assert_frame_equal(identity.reconcile_financial_matches(trigger, rows, preserve_indices={0}), trigger)


def test_duplicate_canonical_reviewed_pair_deduplicates_provenance(monkeypatch):
    configure(monkeypatch, {'c-1': 'term', 'c-2': 'term'})
    rows = frame([dict(report_date='2025-03-31', src_context_id='c-1'),
                  dict(report_date='2025-06-30', src_context_id='c-2')])
    pairs = pd.concat([match('2025-03-31', '2025-06-30')]*2, ignore_index=True)
    pairs.loc[1,'match_method'] = 'B1b_position_key_override'
    output = identity.reconcile_financial_matches(pairs, rows, emit_missing=True)
    assert len(output) == 1
    assert output.iloc[0].match_method == 'B1b_position_key_override'


def test_force_trigger_preserved_until_rebound_and_not_duplicated(monkeypatch):
    configure(monkeypatch, {'c-1': 'term', 'c-2': 'wrong', 'c-3': 'term'})
    rows = frame([dict(report_date='2025-03-31', src_context_id='c-1'),
                  dict(report_date='2025-06-30', src_context_id='c-2'),
                  dict(report_date='2025-06-30', src_context_id='c-3')])
    rows['fair_value'] = [100, 101, 102]
    pairs = match('2025-03-31', '2025-06-30', 100, 101)
    assert len(identity.reconcile_financial_matches(pairs, rows, preserve_indices={0})) == 1
    pairs['end_fair_value'] = 102
    pairs['match_method'] = 'A_within_filing_override'
    pairs['_identity_end_name'] = 'stale trigger'
    output = identity.reconcile_financial_matches(pairs, rows, emit_missing=True)
    assert len(output) == 1
    assert output.iloc[0].match_method == 'A_within_filing_override'


def test_actual_match_export_obeys_reviewed_contract(monkeypatch, tmp_path):
    from pipeline.position_matching import match_positions
    from pipeline import position_match_overrides
    configure(monkeypatch, {'c-1': 'dec', 'c-2': 'new'})
    monkeypatch.setattr(position_match_overrides, 'load_position_match_overrides', lambda: pd.DataFrame())
    rows = frame([dict(report_date='2025-12-31', src_context_id='c-1'),
                  dict(report_date='2026-03-31', src_context_id='c-2')])
    rows['position_key'] = 'same misleading member'
    path = tmp_path / 'financial.csv'
    from tests.test_position_matching import _make_bdc_raw
    result = match_positions(rows, bdc_raw_df=_make_bdc_raw([]), output_file=path)
    assert result.empty
    assert pd.read_csv(path).empty


def test_tied_value_uses_source_terms_not_first_candidate(monkeypatch):
    configure(monkeypatch, {'c-1': 'first', 'c-2': 'second', 'c-3': 'first'})
    rows = frame([dict(report_date='2025-03-31', src_context_id='c-1'),
                  dict(report_date='2025-03-31', src_context_id='c-2'),
                  dict(report_date='2025-06-30', src_context_id='c-3')])
    rows['principal_amount'] = [120, 130, 125]
    pairs = match('2025-03-31', '2025-06-30')
    pairs['begin_principal_amount'] = 120
    output = identity.reconcile_financial_matches(pairs, rows)
    assert len(output) == 1
    assert output.iloc[0].begin_principal_amount == 120


def test_missing_source_begin_cannot_license_reviewed_comparative(monkeypatch):
    configure(monkeypatch, {'c-2': 'term'})
    rows = frame([dict(report_date='2025-06-30', src_context_id='c-2')])
    assert identity.reconcile_financial_matches(match('2024-12-31', '2025-06-30'), rows).empty


def test_amount_agreements_cannot_outvote_conflicting_source_spread(monkeypatch):
    configure(monkeypatch, {'c-1': '750', 'c-2': '265', 'c-3': '750'})
    rows = frame([dict(report_date='2025-03-31', src_context_id='c-1'),
                  dict(report_date='2025-03-31', src_context_id='c-2'),
                  dict(report_date='2025-06-30', src_context_id='c-3')])
    rows['principal_amount'] = [120, 130, 125]
    rows['cost'] = [95, 96, 97]
    rows['basis_spread'] = [7.5, 2.65, 7.5]
    pairs = match('2025-03-31', '2025-06-30')
    pairs['begin_principal_amount'] = 130
    pairs['begin_cost'] = 96
    pairs['begin_basis_spread'] = 7.5
    with pytest.raises(ValueError, match='endpoint is ambiguous'):
        identity.reconcile_financial_matches(pairs, rows)


def test_explicit_index_gap_cannot_hide_ordinary_destination_collision():
    from pipeline.position_match_overrides import _rebind_forced_endpoints
    from tests.test_position_match_overrides import _whole_endpoint_case
    result, directives, holdings = _whole_endpoint_case()
    ordinary = result.copy()
    ordinary['end_issuer_name'] = holdings.iloc[1].issuer_name
    ordinary['end_fair_value'] = holdings.iloc[1].fair_value
    pairs = pd.concat([result, ordinary], ignore_index=True)
    pairs.index = [1, 2]
    directives['_match_idx'] = 1
    directives['_override_idx'] = 0
    with pytest.raises(ValueError, match='already has an ordinary matched pair'):
        _rebind_forced_endpoints(pairs, directives, holdings, set())


@pytest.mark.parametrize('problem', ['maturity', 'instrument', 'scope'])
def test_reviewed_key_cannot_override_existing_real_error_guards(monkeypatch, problem):
    configure(monkeypatch, {'c-1': 'term', 'c-2': 'term'})
    rows = frame([dict(report_date='2025-03-31', src_context_id='c-1'),
                  dict(report_date='2025-06-30', src_context_id='c-2')])
    if problem == 'maturity':
        rows['maturity_date'] = ['2027-01-31', '2032-01-31']
        rows['principal_amount'] = [100, 500]
        rows['basis_spread'] = [3, 7]
    elif problem == 'instrument':
        rows['instrument_description'] = ['Term loan', 'Warrant']
    else:
        rows['is_subsidiary'] = ['0', '1']
    assert identity.reconcile_financial_matches(match('2025-03-31', '2025-06-30'), rows, emit_missing=True).empty


def test_month_precision_overlap_remains_compatible(monkeypatch):
    configure(monkeypatch, {'c-1': 'term', 'c-2': 'term'})
    rows = frame([dict(report_date='2025-03-31', src_context_id='c-1'),
                  dict(report_date='2025-06-30', src_context_id='c-2')])
    rows['maturity_date'] = ['2030-06-30', '2030-06-01']
    rows['maturity_precision'] = ['month', 'month']
    rows['principal_amount'] = [100, 500]
    rows['basis_spread'] = [3, 7]
    assert len(identity.reconcile_financial_matches(match('2025-03-31', '2025-06-30'), rows, emit_missing=True)) == 1


def test_source_endpoint_uids_survive_sort_and_other_funds(monkeypatch, tmp_path):
    from pipeline.position_matching import assign_position_ids
    configure(monkeypatch, {'c-1': 'term', 'c-2': 'term'})
    active = frame([dict(report_date='2025-03-31', src_context_id='c-1'),
                    dict(report_date='2025-06-30', src_context_id='c-2')])
    active['bdc_investment_identifier'] = 'Malformed member'
    other = active.copy()
    other['cik'] = '0000000001'
    other['src_context_id'] = ['other1','other2']
    rows = pd.concat([active.iloc[[1]],other.iloc[[0]],active.iloc[[0]],other.iloc[[1]]])
    rows.index = [51,11,93,27]
    pairs = match('2025-03-31', '2025-06-30', method='A_within_filing')
    mapping = {}
    identity.reconcile_financial_matches(pairs, rows, endpoint_uids=mapping)
    assert mapping == {(0,'begin'):2,(0,'end'):0}
    output, financial = assign_position_ids(rows, pairs, edges_file=tmp_path/'edges.csv')
    assert len(financial) == 1
    ids = output.loc[output.cik.eq('0001918712'),'position_id']
    assert ids.nunique() == 1
    assert financial.iloc[0].position_id == ids.iloc[0]
    assert not output.loc[output.cik.eq('0000000001'),'position_id'].isin(ids).any()
