"""Transport/schema failures must never become successful screening answers."""
import copy
import json
from types import SimpleNamespace

import pytest

from scripts.run_jev_screening import validate_response, validate_arm, decode_observation
from pipeline.jev_screening import fingerprint
from scripts import run_jev_screening as runner


def test_consumed_holdout_cannot_be_reported_as_blind(tmp_path):
    frozen = tmp_path / 'holdout_frozen_01'
    frozen.mkdir()
    validate_arm('holdout', frozen, tmp_path)
    development = tmp_path / 'holdout_development_02'
    development.mkdir()
    with pytest.raises(ValueError, match='consumed'):
        validate_arm('holdout', frozen, tmp_path)
    validate_arm('consumed_holdout', development, tmp_path)


def test_holdout_requires_original_packets(tmp_path):
    with pytest.raises(ValueError, match='original frozen'):
        validate_arm('holdout', tmp_path / 'repaired', tmp_path)


def test_temporal_holdout_cannot_use_repaired_builder_or_another_folder(tmp_path):
    folder = tmp_path / 'temporal_frozen_01'
    folder.mkdir()
    frozen = {'arm': 'within_filer_unseen_accession',
              'builder_sha256': runner.sha(runner.ROOT / 'pipeline/jev_bundles.py')}
    path = folder / 'frozen_builder.json'
    path.write_text(json.dumps(frozen))
    validate_arm('temporal_holdout', folder, tmp_path)
    with pytest.raises(ValueError, match='original frozen'):
        validate_arm('temporal_holdout', tmp_path / 'repaired', tmp_path)
    frozen['builder_sha256'] = 'changed'
    path.write_text(json.dumps(frozen))
    with pytest.raises(ValueError, match='development now'):
        validate_arm('temporal_holdout', folder, tmp_path)


@pytest.fixture
def pair():
    request = {'model': 'jev-1.13.0', 'questions': {
        'decision': {'criteria': {'false_alarm': '', 'real_error': '', 'ambiguous': ''}},
        'source_match': {'criteria': {'t0r1': '', 'insufficient_evidence': ''}}}}
    body = {'model': 'jev-1.13.0', 'answers': {
        'decision': {'type': 'choice', 'choice': 'false_alarm', 'confidence': 0.7,
                     'probabilities': {'false_alarm': 0.8, 'real_error': 0.1, 'ambiguous': 0.1}},
        'source_match': {'type': 'choice', 'choice': 't0r1', 'confidence': 0.8,
                         'probabilities': {'t0r1': 0.9, 'insufficient_evidence': 0.1}}},
        'usage': {'input_tokens': 1200}}
    return body, request


def test_valid_provider_schema(pair):
    validate_response(*pair)


@pytest.mark.parametrize('estimated_tokens,submitted', [(21000, True), (23000, False)])
def test_preparation_keeps_oversized_evidence_out_of_request_queue(tmp_path, monkeypatch, estimated_tokens, submitted):
    import tiktoken
    packets = tmp_path / 'input'
    packets.mkdir()
    (packets / 'packet.json').write_text(json.dumps({
        'schema_version': 'jev-value-bundle.v4', 'flag': {'cik': '1', 'row_id': 'ROW-1'}, 'provenance': {}}))
    (tmp_path / 'session.json').write_text(json.dumps({'limits': {'holdout_flags': 40}}))
    (tmp_path / 'holdout_reservation_v2.json').write_text(json.dumps({
        'all_previously_exercised_ciks': ['1'], 'holdout_funds': []}))
    monkeypatch.setattr(runner, 'route_flag', lambda *a, **k: {'route': 'pending'})
    monkeypatch.setattr(runner, 'make_request', lambda *a, **k: {'state': 'sized separately'})
    monkeypatch.setattr(tiktoken, 'get_encoding', lambda *a: SimpleNamespace(encode=lambda *a, **k: range(estimated_tokens)))
    args = SimpleNamespace(arm='development', bundles=packets, run_root=tmp_path, label='sized', references=None)
    runner.prepare(args)
    manifest = json.loads((tmp_path / 'sized/manifest.json').read_text())
    record = manifest['records'][0]
    assert bool(record['request_id']) is submitted
    assert len(list((tmp_path / 'sized/requests').glob('*.json'))) == int(submitted)
    assert manifest['token_budget']['provider_token_guarantee'] is False
    if not submitted:
        assert record['not_submitted_reason'] == 'request_proxy_token_limit'
        assert len(list((tmp_path / 'sized/packets').glob('*.json'))) == 1


@pytest.mark.parametrize('tamper', ['none', 'receipt', 'references'])
def test_analysis_does_not_score_misbound_receipts_or_changed_references(tmp_path, pair, tamper):
    from scripts.analyze_jev_screening import summarize
    body, request = pair
    run, attempts = tmp_path / 'run', tmp_path / 'attempts'
    for path in (run / 'packets', run / 'requests', attempts):
        path.mkdir(parents=True)
    packet = {'evidence_status': {'status': 'blocked'}, 'source_candidates': [],
              'rule': {'fields': ['cost']}, 'output_position': {}}
    packet_id, request_id = fingerprint(packet), fingerprint(request)
    (run / 'packets' / (packet_id + '.json')).write_text(json.dumps(packet))
    (run / 'requests' / (request_id + '.json')).write_text(json.dumps(request))
    (run / 'references.json').write_text(json.dumps({'ROW-1': {'expected': 'false_alarm', 'expected_source': 't0r1'}}))
    manifest = {'arm': 'development', 'records': [{'flag': {'row_id': 'ROW-1'},
                 'packet_id': packet_id, 'request_id': request_id}],
                'references_sha256': runner.sha(run / 'references.json'),
                'policy': {'decision_cutoff': .75, 'source_cutoff': .75}}
    (run / 'manifest.json').write_text(json.dumps(manifest))
    receipt = {'status': 'success', 'request_id': request_id,
               'bundle_fingerprint': packet_id, 'response': body}
    if tamper == 'receipt':
        receipt['bundle_fingerprint'] = 'other-packet'
    (attempts / (request_id + '.result.json')).write_text(json.dumps(receipt))
    if tamper == 'references':
        (run / 'references.json').write_text('{}')
        with pytest.raises(ValueError, match='references changed'):
            summarize(run, attempts)
    else:
        report = summarize(run, attempts)
        assert report['counts']['successful_calls'] == (tamper == 'none')


@pytest.mark.parametrize('change', ['answers_list', 'probabilities_list', 'usage_none', 'nonmax_choice', 'contradictory_confidence'])
def test_nested_shape_and_documented_choice_contract(pair, change):
    body, request = copy.deepcopy(pair)
    if change == 'answers_list':
        body['answers'] = list(body['answers'])
    elif change == 'probabilities_list':
        body['answers']['decision']['probabilities'] = list(body['answers']['decision']['probabilities'])
    elif change == 'usage_none':
        body['usage'] = None
    elif change == 'nonmax_choice':
        body['answers']['decision']['choice'] = 'real_error'
    else:
        body['answers']['decision']['confidence'] = 0.99
    with pytest.raises(ValueError):
        validate_response(body, request)


@pytest.mark.parametrize('change', ['packet', 'request', 'body', 'valid'])
def test_persisted_answer_must_belong_to_frozen_request(pair, change):
    body, request = copy.deepcopy(pair)
    record = {'request_id': fingerprint(request), 'packet_id': 'packet-a'}
    receipt = {'status': 'success', 'request_id': record['request_id'],
               'bundle_fingerprint': 'packet-a', 'response': body}
    if change == 'packet':
        receipt['bundle_fingerprint'] = 'packet-b'
    elif change == 'request':
        receipt['request_id'] = 'another-request'
    elif change == 'body':
        body['answers']['decision']['confidence'] = float('nan')
    decoded = decode_observation(receipt, record, request)
    assert (decoded['status'] == 'success') is (change == 'valid')


@pytest.mark.parametrize('change', ['model', 'source', 'probability', 'sum', 'confidence', 'tokens', 'answers'])
def test_invalid_response_cannot_be_successful(pair, change):
    body, request = copy.deepcopy(pair)
    if change == 'model':
        body['model'] = 'unpinned'
    elif change == 'source':
        body['answers']['source_match']['choice'] = 'unknown_source'
    elif change == 'probability':
        body['answers']['decision']['probabilities']['false_alarm'] = True
    elif change == 'sum':
        body['answers']['decision']['probabilities']['false_alarm'] = 0.1
    elif change == 'confidence':
        body['answers']['decision']['confidence'] = float('nan')
    elif change == 'tokens':
        body['usage']['input_tokens'] = -1
    else:
        del body['answers']['source_match']
    with pytest.raises(ValueError):
        validate_response(body, request)


@pytest.fixture
def transport_run(tmp_path, monkeypatch, pair):
    monkeypatch.setenv('TYPESAFE_API_KEY', 'test-only-placeholder')
    run = tmp_path / 'trial'
    run.mkdir()
    (run / 'requests').mkdir()
    (tmp_path / 'api_attempts').mkdir()
    (run / 'references.json').write_text('{}')
    records = []
    for index in range(2):
        request = copy.deepcopy(pair[1])
        request['state'] = {'index': index}
        request_id = fingerprint(request)
        (run / 'requests' / (request_id + '.json')).write_text(json.dumps(request))
        records.append({'request_id': request_id, 'packet_id': 'packet-' + str(index)})
    manifest = {'records': records, 'runner_sha256': runner.sha(runner.ROOT / 'scripts/run_jev_screening.py'),
                'routing_sha256': runner.sha(runner.ROOT / 'pipeline/jev_screening.py'),
                'references_sha256': runner.sha(run / 'references.json')}
    (run / 'manifest.json').write_text(json.dumps(manifest))
    return SimpleNamespace(run_root=tmp_path, label='trial', repo=tmp_path, limit=10), records


def test_prior_unknown_submission_is_never_automatically_retried(transport_run, monkeypatch):
    import requests
    args, records = transport_run
    for record in records:
        (args.run_root / 'api_attempts' / (record['request_id'] + '.started.json')).write_text('{}')
    monkeypatch.setattr(requests, 'post', lambda *a, **k: pytest.fail('Unexpected retry'))
    runner.run_requests(args)
    assert not (args.run_root / 'api_session.lock').exists()


def test_session_attempt_budget_prevents_network(transport_run, monkeypatch):
    import requests
    args, _ = transport_run
    for index in range(100):
        (args.run_root / 'api_attempts' / (str(index) + '.started.json')).write_text('{}')
    monkeypatch.setattr(requests, 'post', lambda *a, **k: pytest.fail('Budget exceeded'))
    runner.run_requests(args)


def test_existing_session_lock_is_not_removed(transport_run, monkeypatch):
    import requests
    args, _ = transport_run
    lock = args.run_root / 'api_session.lock'
    lock.write_text('another-owner')
    monkeypatch.setattr(requests, 'post', lambda *a, **k: pytest.fail('Lock bypassed'))
    with pytest.raises(FileExistsError):
        runner.run_requests(args)
    assert lock.read_text() == 'another-owner'


@pytest.mark.parametrize('mode', ['timeout', 'http_error', 'invalid_json'])
def test_transport_failure_stops_batch_and_retains_attempt(transport_run, monkeypatch, mode):
    import requests
    args, records = transport_run
    calls = []
    def post(*a, **kwargs):
        calls.append(1)
        assert kwargs['allow_redirects'] is False
        if mode == 'timeout':
            raise requests.Timeout('simulated')
        def invalid_json():
            raise ValueError('simulated')
        return SimpleNamespace(status_code=503 if mode == 'http_error' else 200, json=invalid_json)
    monkeypatch.setattr(requests, 'post', post)
    runner.run_requests(args)
    assert len(calls) == 1
    attempts = args.run_root / 'api_attempts'
    assert (attempts / (records[0]['request_id'] + '.started.json')).exists()
    receipt = json.loads((attempts / (records[0]['request_id'] + '.result.json')).read_text())
    assert receipt['status'] != 'success'
    assert not (attempts / (records[1]['request_id'] + '.started.json')).exists()
    assert not (args.run_root / 'api_session.lock').exists()
