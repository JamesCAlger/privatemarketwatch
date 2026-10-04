"""Layout diagnostics must separate geometry from values and not imply support."""
import copy

from scripts.profile_jev_layouts import layout_shape, numeric_evidence_paths, profile, section_evidence


def candidate():
    return {'headers': {'cost': {'column': 2, 'span': 2, 'text': 'Cost (3)'}},
            'raw_cells': [{'column': 2, 'span': 2, 'text': '100'}],
            'source_values': {'cost': {'cells': [{'inline_facts': [{'name': 'us-gaap:InvestmentOwnedAtCost',
                'scale': '3', 'currency': 'USD', 'text': '100'}]}]}}}


def test_value_changes_do_not_masquerade_as_layout_changes():
    first, second = candidate(), candidate()
    second['raw_cells'][0]['text'] = '200'
    second['source_values']['cost']['cells'][0]['inline_facts'][0]['text'] = '200'
    assert layout_shape(first) == layout_shape(second)
    assert numeric_evidence_paths(first) == numeric_evidence_paths(second)


def test_header_note_and_span_changes_are_visible():
    original = candidate()
    changed = copy.deepcopy(original)
    changed['headers']['cost']['text'] = 'Cost (3,5)'
    assert layout_shape(original) != layout_shape(changed)
    changed = copy.deepcopy(original)
    changed['raw_cells'][0]['span'] = 3
    assert layout_shape(original) != layout_shape(changed)


def test_transform_path_changes_are_separate_from_layout_geometry():
    original, changed = candidate(), candidate()
    changed['source_values']['cost']['cells'][0]['inline_facts'][0]['format'] = 'ixt:fixed-zero'
    assert layout_shape(original) == layout_shape(changed)
    assert numeric_evidence_paths(original) != numeric_evidence_paths(changed)


def test_missing_candidates_stay_explicit_in_coverage():
    packet = {'rule': {'id': 'C107'}, 'flag': {'row_id': 'ROW-1'},
              'output_position': {'cik': '1', 'report_date': '2025-12-31', 'accession_number': 'accession'},
              'evidence_status': {'status': 'blocked', 'blocking_reasons': ['missing_source']},
              'source_candidates': []}
    result = profile({'case': packet})
    assert result['flags'] == result['flags_without_candidates'] == 1
    assert result['observed_layout_shapes'] == 0
    assert result['production_clearance_enabled'] is False


def test_local_and_inherited_scope_evidence_are_not_conflated():
    item = {'table_index': 3, 'section_context': [
        {'table_index': 3, 'row_index': 1, 'text': 'Investments (1)'},
        {'table_index': 2, 'row_index': 1, 'text': 'Investments (2)',
         'scope_unresolved': True, 'scope_reason': 'unconfirmed_schedule_continuation'}]}
    result = section_evidence(item)
    assert [s['location'] for s in result] == ['local', 'other_table']
    assert [s['scope_unresolved'] for s in result] == [False, True]
    assert result[1]['scope_reason'] == 'unconfirmed_schedule_continuation'


def test_unknown_section_coordinates_do_not_imply_local_evidence():
    assert section_evidence({'section_context': [{'text': 'Unlocated section'}]})[0]['location'] == 'unknown'
