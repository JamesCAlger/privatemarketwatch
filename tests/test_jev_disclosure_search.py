from copy import deepcopy

import pytest

from pipeline.jev_disclosure_search import anchor_issuer_seeds, disclosure_search


def cell(value, **extra):
    return {'column': 0, 'span': 1, 'text': value, **extra}


def source():
    return {'tables': [
        {'table_index': 0, 'report_date': '2026-03-31', 'rows': [[cell('AB Centers DDTL')]]},
        {'table_index': 1, 'report_date': '2025-12-31', 'rows': [[cell('AB Centers Revolver')]]},
        {'table_index': 2, 'unsupported_layout': True, 'rows': [[cell('AB Centers Common Stock')]]},
        {'table_index': 3, 'rows': [[cell('Petvet Centers Loan')]]},
    ], 'contexts': {}}


def test_retains_all_roles_periods_instruments_and_unknown_geometry_without_identity_claim():
    parsed = source()
    before = deepcopy(parsed)
    result = disclosure_search(parsed, issuer_phrases=['AB Centers'])
    assert [r['table_index'] for r in result['matches']] == [0, 1, 2]
    assert result['tables_scanned'] == 4
    assert result['table_role_counts'] == {'unknown': 4}
    assert result['matches'][1]['parsed_report_date'] == '2025-12-31'
    assert result['matches'][2]['unsupported_layout']
    assert result['inclusion_decision'] is None and not result['position_identity_verified']
    assert not result['recall_verified'] and not result['ownership_scope_verified']
    result['matches'][0]['source_cells'][0]['text'] = 'changed copy'
    assert parsed == before


def test_short_distinctive_name_is_not_dropped_to_generic_centers():
    result = disclosure_search(source(), issuer_phrases=['AB Centers'])
    assert all('Petvet' not in r['source_cells'][0]['text'] for r in result['matches'])


@pytest.mark.parametrize('value,matched', [
    ('ab\u00a0CENTERS, Inc.', True), ('AB-Centers', True),
    ('ABC Centers', False), ('AB CentersPlus', False), ('Centers AB', False),
])
def test_contiguous_word_sequence_not_substrings_or_reordered_terms(value, matched):
    parsed = {'tables': [{'table_index': 0, 'rows': [[cell(value)]]}]}
    assert bool(disclosure_search(parsed, issuer_phrases=['AB Centers'])['matches']) == matched


def test_context_anchor_finds_unnamed_continuation_but_not_similar_context():
    parsed = {'tables': [{'table_index': 0, 'rows': [
        [cell('Revolver', inline_facts=[{'context_id': 'ctx'}])],
        [cell('Other loan', inline_facts=[{'context_id': 'ctx2'}])]]}],
        'contexts': {'ctx': {'instant': '2026-03-31'}}}
    result = disclosure_search(parsed, issuer_phrases=['AB Centers'], context_ids=['ctx', 'absent'])
    assert len(result['matches']) == 1
    assert result['matches'][0]['matched_phrases'] == []
    assert result['matches'][0]['context_definitions']['ctx']['instant'] == '2026-03-31'
    assert result['missing_context_anchors'] == ['absent']


def test_hidden_row_is_preserved_as_evidence_not_silently_omitted():
    parsed = source()
    parsed['tables'][0]['rows'][0][0]['hidden_source_content'] = True
    row = disclosure_search(parsed, issuer_phrases=['AB Centers'])['matches'][0]
    assert row['source_cells'][0]['hidden_source_content'] is True


@pytest.mark.parametrize('phrases', [[], ['Centers'], [' '], ['12 34'], ['AB Centers', 'ab-centers'], [None]])
def test_empty_generic_numeric_and_duplicate_searches_are_rejected(phrases):
    with pytest.raises(ValueError):
        disclosure_search(source(), issuer_phrases=phrases)


def test_match_cap_refuses_instead_of_publishing_truncated_inventory():
    with pytest.raises(ValueError, match='incomplete'):
        disclosure_search(source(), issuer_phrases=['AB Centers'], max_matches=2)


def test_repeated_coordinates_are_rejected():
    parsed = source()
    parsed['tables'][1]['table_index'] = 0
    with pytest.raises(ValueError, match='coordinate'):
        disclosure_search(parsed, issuer_phrases=['AB Centers'])


def test_missing_issuer_allows_exact_anchor_navigation_without_recall_claim():
    parsed = {'tables': [{'table_index': 0, 'rows': [[cell('Loan', inline_facts=[{'context_id': 'ctx'}])]]}]}
    result = disclosure_search(parsed, issuer_phrases=[], context_ids=['ctx'])
    assert len(result['matches']) == 1
    assert result['issuer_phrases'] == [] and not result['recall_verified']


def test_missing_issuer_and_absent_anchor_is_an_explicit_empty_result():
    result = disclosure_search(source(), issuer_phrases=[], context_ids=['absent'])
    assert result['matches'] == [] and result['missing_context_anchors'] == ['absent']


def issuer_table():
    labels = ['Portfolio Company', 'Investment Type', 'Cost', 'Fair Value']
    headers = [dict(cell(value), column=i) for i, value in enumerate(labels)]
    values = [dict(cell(value), column=i) for i, value in enumerate(['AB Centers', 'Term Loan', '10', '9'])]
    values[3]['inline_facts'] = [{'context_id': 'ctx'}]
    return {'tables': [{'table_index': 0, 'rows': [headers, values]}]}


def test_exact_anchor_source_issuer_column_supplies_query_with_coordinates():
    initial = disclosure_search(issuer_table(), issuer_phrases=[], context_ids=['ctx'])
    result = anchor_issuer_seeds(initial)
    assert [s['phrase'] for s in result['seeds']] == ['AB Centers']
    assert result['seeds'][0]['origins'][0]['row_index'] == 1
    assert not result['identity_verified'] and not result['refusals']


@pytest.mark.parametrize('mutation', ['hidden', 'hidden_header', 'unknown', 'combined', 'missing', 'single_word', 'not_anchor'])
def test_unsupported_source_identity_is_not_repaired_by_guessing(mutation):
    initial = disclosure_search(issuer_table(), issuer_phrases=[], context_ids=['ctx'])
    row = initial['matches'][0]
    if mutation == 'hidden':
        row['source_cells'][0]['hidden_source_content'] = True
    elif mutation == 'hidden_header':
        row['role_header_rows'][0]['cells'][0]['hidden_source_content'] = True
    elif mutation in {'unknown', 'combined'}:
        row['header_role']['role'] = 'investment_rollforward' if mutation == 'combined' else 'unknown'
    elif mutation == 'missing':
        row['source_cells'][0]['text'] = ''
    elif mutation == 'single_word':
        row['source_cells'][0]['text'] = 'Skillsoft'
    else:
        row['matched_context_anchors'] = []
    assert anchor_issuer_seeds(initial)['seeds'] == []
