from scripts.profile_jev_blockers import profile


def packet(flag_reasons, candidate_reasons, status='blocked'):
    return {'flag': {'cik': '1', 'report_date': '2026-03-31'},
            'output_position': {'issuer_name': 'Example'},
            'evidence_status': {'status': status, 'blocking_reasons': flag_reasons},
            'source_candidates': [{'blocking_reasons': reasons} for reasons in candidate_reasons]}


def test_repeated_candidate_failure_counts_one_flag_and_preserves_overlap():
    item = packet(['incomplete_candidate_evidence'], [['missing_notes'], ['missing_notes', 'currency_conflict']])
    result = profile({('X08', 'ROW-1'): item})
    assert result['blocked_flags'] == 1
    assert {r['reason']: r['distinct_flags'] for r in result['issues']} == {'missing_notes': 1, 'currency_conflict': 1}
    assert all(r['sole_specific_reason_flags'] == 0 for r in result['issues'])


def test_pre_retrieval_blockers_and_partial_candidates_stay_distinct():
    result = profile({('C107', 'ROW-1'): packet(['proxy_cost_requires_lineage'], []),
                      ('X08', 'ROW-2'): packet(['incomplete_candidate_evidence'], [[], ['missing_notes']]),
                      ('X08', 'ROW-3'): packet([], [[]], 'ready_for_model')})
    assert result['selected_flags'] == 3
    assert result['blocked_flags'] == 2
    assert result['blocked_without_candidates'] == 1
    assert result['blocked_with_some_complete_candidates'] == 1
    assert result['blocked_by_rule'] == {'C107': 1, 'X08': 1}
    assert all(not r['candidate_recall_certified'] for r in result['records'])


def test_unexplained_blocker_is_not_silently_dropped():
    result = profile({('X08', 'ROW-1'): packet(['incomplete_candidate_evidence'], [])})
    assert result['issues'][0]['reason'] == 'unexplained_blocker'
