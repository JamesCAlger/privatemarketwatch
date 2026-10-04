"""Review preparation must not leak answers or manufacture signed-off checks."""
from scripts.prepare_jev_blind_review import review_input


def packet():
    return {'rule': {'id': 'C107', 'fields': ['cost'], 'expected': 'SECRET'},
            'output_position': {'cik': '0000000001', 'row_id': 'ROW-A', 'cost': '-1000',
                                'cost_source': 'reported', 'issuer_name': 'Example',
                                'model_decision': 'SECRET'},
            'provenance': {'holdings_sha256': 'snapshot'},
            'source_candidates': [{'source_values': {'cost': 'SECRET'}}],
            'evidence_status': {'status': 'SECRET'}, 'model': {'answer': 'SECRET'},
            'reference': {'expected': 'SECRET'}}


def test_answers_and_builder_candidates_are_withheld():
    import json
    result = review_input(packet(), '/cached/source.html', 'source-hash')
    assert 'SECRET' not in json.dumps(result)
    assert result['position']['cost'] == '-1000'
    assert 'source_candidates' not in result


def test_unreviewed_packet_has_no_completed_checks_or_clearance():
    result = review_input(packet(), '/cached/source.html', 'source-hash')
    assert all(value is None for value in result['review_form']['checks'].values())
    assert result['review_form']['disposition'] is None
    assert result['review_form']['reviewer'] is None
    assert result['production_clearance_enabled'] is False


def test_binding_changes_when_withheld_bundle_changes():
    before = packet()
    after = packet()
    after['source_candidates'].append({'new_sibling': True})
    assert review_input(before, 'source', 'hash')['review_id'] != review_input(after, 'source', 'hash')['review_id']


def test_raw_identity_is_retained_as_untrusted_pipeline_claim():
    original = packet()
    original['output_position']['bdc_dimensions_raw'] = ['original-axis-value']
    result = review_input(original, 'source', 'hash')
    result['position']['bdc_dimensions_raw'].append('review-note')
    assert original['output_position']['bdc_dimensions_raw'] == ['original-axis-value']
