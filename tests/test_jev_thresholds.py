from scripts.analyze_jev_thresholds import sweep


def observation(**changes):
    return {'decision': 'false_alarm', 'source': 't1r1', 'decision_confidence': .75,
            'source_confidence': .75, 'expected': 'false_alarm', 'expected_source': 't1r1',
            'attempt_id': 'a', **changes}


def test_both_cutoffs_are_required_and_boundary_is_inclusive():
    rows = [observation(), observation(decision_confidence=.74), observation(source_confidence=.74)]
    assert sweep(rows, .75, .75)['confidence_candidates'] == 1


def test_abstention_and_suspected_error_never_become_confidence_candidates():
    rows = [observation(source='insufficient_evidence'), observation(decision='real_error'),
            observation(decision='ambiguous')]
    assert sweep(rows, 0, 0)['confidence_candidates'] == 0


def test_wrong_source_and_false_negative_remain_counted():
    result = sweep([observation(expected='real_error', expected_source='t2r1')], .75, .75)
    assert result['candidate_reference_classes'] == {'real_error': 1}
    assert result['candidate_wrong_source'] == 1


def test_calls_are_not_reported_as_unique_cases():
    result = sweep([observation(), observation(attempt_id='b')], .75, .75)
    assert result['calls'] == 2
    assert result['candidate_attempt_ids'] == ['a', 'b']
