"""Source-table role cannot silently become a row inclusion decision."""
from copy import deepcopy

import pytest

from pipeline.jev_disclosure_role import table_disclosure_role


def table(labels):
    return {'table_index': 15, 'rows': [[{'column': n, 'span': 1, 'text': text}
                                      for n, text in enumerate(labels)]], 'unsupported_layout': False}


@pytest.mark.parametrize('labels,role', [
    (['Portfolio Company', 'Investment Type', 'Cost', 'Fair Value (3)'], 'position_values'),
    (['Portfolio Company', 'Investment Type', 'Commitment Expiration Date', 'Unfunded Commitment', 'Fair Value (3)'], 'unfunded_commitments'),
    (['Company', 'Type of Investment', 'Amortized Cost', 'Market Value'], 'position_values'),
    (['Portfolio Company', 'Investment Type', 'Cost', 'Unfunded Commitment', 'Commitment Expiration Date', 'Fair Value'], 'ambiguous'),
    (['Portfolio Company', 'Investment Type', 'Unfunded Commitment', 'Fair Value'], 'unknown'),
    (['Portfolio Company', 'Investment Type', 'Cost', 'Cost', 'Fair Value'], 'ambiguous'),
    (['Total Investments', 'Cost', 'Fair Value'], 'unknown'),
    (['Acme LLC', 'Loan with unfunded commitment', '100', '99'], 'unknown'),
])
def test_explicit_single_band_headers(labels, role):
    source = table(labels)
    before = deepcopy(source)
    result = table_disclosure_role(source)
    assert result['role'] == role
    assert result['inclusion_decision'] is None
    assert result['economic_identity_verified'] is False
    assert result['ownership_scope_verified'] is False
    assert source == before


def test_unfunded_note_does_not_change_position_table_role():
    source = table(['Portfolio Company', 'Investment Type', 'Cost', 'Fair Value'])
    source['rows'].append([{'column': 0, 'span': 4, 'text': '(9) This position is an unfunded commitment.'}])
    assert table_disclosure_role(source)['role'] == 'position_values'


def test_different_header_bands_do_not_supply_missing_fields():
    source = table(['Portfolio Company', 'Investment Type', 'Cost'])
    source['rows'].extend(table(['Fair Value', 'Commitment Expiration Date', 'Unfunded Commitment'])['rows'])
    assert table_disclosure_role(source)['role'] == 'unknown'


def test_conflicting_complete_bands_are_ambiguous():
    source = table(['Portfolio Company', 'Investment Type', 'Cost', 'Fair Value'])
    source['rows'].extend(table(['Portfolio Company', 'Investment Type', 'Commitment Expiration Date',
                                'Unfunded Commitment', 'Fair Value'])['rows'])
    assert table_disclosure_role(source)['role'] == 'ambiguous'


def test_unsupported_geometry_does_not_certify_role():
    source = table(['Portfolio Company', 'Investment Type', 'Cost', 'Fair Value'])
    source['unsupported_layout'] = True
    result = table_disclosure_role(source)
    assert result['role'] == 'unknown'
    assert result['evidence'][0]['table_index'] == 15


def test_source_header_coordinates_and_note_reference_are_preserved():
    source = table(['Portfolio Company', 'Investment Type', 'Cost', 'Fair Value (3)'])
    source['rows'].insert(0, [])
    evidence = table_disclosure_role(source)['evidence'][0]
    assert evidence['row_index'] == 1
    assert evidence['matching_cells']['fair_value'] == [{'column': 3, 'span': 1, 'text': 'Fair Value (3)'}]


ROLLFORWARD = ['Name of Investment', 'Fair Value at December 31, 2024',
               'Gross Addition (a)', 'Gross Reduction (b)', 'Realized Gains (Losses)',
               'Net Change in Unrealized Appreciation/ (Depreciation)',
               'Fair Value at September 30, 2025', 'Interest/Dividend/ Other income']


def test_explicit_rollforward_preserves_dates_without_assigning_owner():
    source = table(ROLLFORWARD)
    result = table_disclosure_role(source)
    assert result['role'] == 'investment_rollforward'
    assert result['ownership_scope_verified'] is False
    assert result['economic_identity_verified'] is False
    assert result['inclusion_decision'] is None
    matches = result['evidence'][0]['matching_cells']
    assert matches['beginning_fair_value'][0]['header_date'] == '2024-12-31'
    assert matches['ending_fair_value'][0]['header_date'] == '2025-09-30'
    assert matches['gross_addition'][0]['text'] == 'Gross Addition (a)'


@pytest.mark.parametrize('index,replacement', [
    (2, 'Principal Amount'), (3, 'Amortized Cost'),
    (1, 'Fair Value at December 31, 2025'),
    (1, 'Fair Value at September 30, 2025'),
    (6, 'Fair Value at September 31, 2025'),
    (0, 'Total Investments'),
])
def test_incomplete_or_conflicting_rollforward_headers_stay_unknown(index, replacement):
    labels = list(ROLLFORWARD)
    labels[index] = replacement
    assert table_disclosure_role(table(labels))['role'] == 'unknown'


def test_comparative_values_without_movements_are_not_a_rollforward():
    assert table_disclosure_role(table([ROLLFORWARD[0], ROLLFORWARD[1], ROLLFORWARD[6]]))['role'] == 'unknown'


def test_duplicate_rollforward_movement_header_is_ambiguous():
    assert table_disclosure_role(table(ROLLFORWARD + ['Gross Addition']))['role'] == 'ambiguous'


def test_unsupported_rollforward_layout_stays_unknown():
    source = table(ROLLFORWARD)
    source['unsupported_layout'] = True
    assert table_disclosure_role(source)['role'] == 'unknown'
