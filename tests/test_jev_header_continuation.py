from copy import deepcopy

import pytest

from pipeline.jev_header_continuation import inspect_header_continuation


def source():
    headers = {f: {'row': 0, 'column': i, 'span': 1, 'text': f}
               for i, f in enumerate(('issuer', 'instrument', 'cost', 'fair_value'))}
    row = [{'column': i, 'span': 1, 'text': 'value', 'inline_facts': [
        {'name': 'us-gaap:InvestmentOwnedAt' + suffix, 'context_id': 'ctx'}]}
        for i, suffix in ((2, 'Cost'), (3, 'FairValue'))]
    return {'tables': [
        {'table_index': 0, 'report_date': '2026-03-31', 'headers': deepcopy(headers), 'rows': []},
        {'table_index': 1, 'report_date': '2026-03-31', 'headers': {}, 'rows': [row]},
        {'table_index': 2, 'report_date': '2026-03-31', 'headers': deepcopy(headers), 'rows': []}],
        'contexts': {'ctx': {'instant': '2026-03-31', 'entity_identifier': '0000000001'}}}


def inspect(parsed):
    return inspect_header_continuation(parsed, 1, cik='1', period='2026-03-31')


def test_consistent_geometry_does_not_inherit_headers_or_certify_scope():
    parsed = source()
    before = deepcopy(parsed)
    result = inspect(parsed)
    assert result['status'] == 'candidate_geometry_consistent'
    assert result['monetary_fact_counts'] == {'cost': 1, 'fair_value': 1}
    assert not any(result[k] for k in ('headers_applied', 'ownership_scope_verified', 'notes_complete', 'position_identity_verified'))
    assert parsed == before


@pytest.mark.parametrize('mutation,reason', [
    ('next_columns', 'adjacent_header_disagreement'),
    ('next_label', 'adjacent_header_disagreement'),
    ('missing_header', 'missing_adjacent_header_fields'),
    ('shifted_fact', 'monetary_fact_outside_proposed_column'),
    ('merged_cell', 'monetary_fact_outside_proposed_column'),
    ('other_period', 'unresolved_or_conflicting_table_period'),
    ('fact_period', 'unresolved_or_conflicting_fact_context'),
    ('fact_entity', 'unresolved_or_conflicting_fact_context'),
    ('hidden_header', 'hidden_header_content'),
    ('hidden_fact', 'hidden_or_unsupported_fact'),
    ('custom_only', 'missing_standard_monetary_field_facts'),
])
def test_structure_and_context_changes_remain_unresolved(mutation, reason):
    parsed = source()
    target = parsed['tables'][1]
    if mutation == 'next_columns':
        parsed['tables'][2]['headers']['cost']['column'] = 4
    elif mutation == 'next_label':
        parsed['tables'][2]['headers']['cost']['text'] = 'Other Cost'
    elif mutation == 'missing_header':
        del parsed['tables'][0]['headers']['issuer']
    elif mutation == 'shifted_fact':
        target['rows'][0][0]['column'] = 1
    elif mutation == 'merged_cell':
        target['rows'][0][0]['span'] = 2
    elif mutation == 'other_period':
        target['report_date'] = '2025-12-31'
    elif mutation == 'fact_period':
        parsed['contexts']['ctx']['instant'] = '2025-12-31'
    elif mutation == 'fact_entity':
        parsed['contexts']['ctx']['entity_identifier'] = '2'
    elif mutation == 'hidden_header':
        parsed['tables'][0]['headers']['cost']['hidden_source_content'] = True
    elif mutation == 'hidden_fact':
        target['rows'][0][0]['hidden_source_content'] = True
    else:
        target['rows'][0][0]['inline_facts'][0]['name'] = 'custom:NetCost'
    result = inspect(parsed)
    assert result['status'] == 'unresolved' and reason in result['blockers']


def test_every_row_is_checked_not_only_selected_position():
    parsed = source()
    wrong = deepcopy(parsed['tables'][1]['rows'][0])
    wrong[0]['column'] = 1
    parsed['tables'][1]['rows'].append(wrong)
    assert 'monetary_fact_outside_proposed_column' in inspect(parsed)['blockers']


@pytest.mark.parametrize('cik,period', [('0', '2026-03-31'), ('1', '2026-02-30'), ('1', None), ('../1', '2026-03-31')])
def test_invalid_source_identity_cannot_validate_a_continuation(cik, period):
    with pytest.raises(ValueError):
        inspect_header_continuation(source(), 1, cik=cik, period=period)
