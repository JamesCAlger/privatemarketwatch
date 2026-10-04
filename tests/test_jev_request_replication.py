"""Exact-payload repeats preserve receipts, budget limits and unknown submissions."""
import copy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import requests

from pipeline.jev_screening import fingerprint
from scripts import repeat_jev_requests as repeat
from scripts.jev_pilot_session import read, write


@pytest.fixture
def parents(tmp_path, monkeypatch):
    monkeypatch.setenv('TYPESAFE_API_KEY', 'test-only')
    (tmp_path / 'api_attempts').mkdir()
    response = {'model': 'jev-1.13.0', 'answers': {
        'decision': {'type': 'choice', 'choice': 'false_alarm', 'confidence': .7,
                     'probabilities': {'false_alarm': .8, 'real_error': .1, 'ambiguous': .1}},
        'source_match': {'type': 'choice', 'choice': 't0r1', 'confidence': .8,
                         'probabilities': {'t0r1': .9, 'insufficient_evidence': .1}}},
        'usage': {'input_tokens': 1200}}
    for label in repeat.PARENTS:
        parent = tmp_path / label
        (parent / 'requests').mkdir(parents=True)
        (parent / 'packets').mkdir()
        records = []
        for index in range(4):
            packet = {'fixture': index, 'presentation': label}
            request = {'model': 'jev-1.13.0', 'state': packet, 'questions': {
                'decision': {'criteria': {'false_alarm': '', 'real_error': '', 'ambiguous': ''}},
                'source_match': {'criteria': {'t0r1': '', 'insufficient_evidence': ''}}}}
            request_id, packet_id = fingerprint(request), fingerprint(packet)
            write(parent / 'requests' / (request_id + '.json'), request)
            write(parent / 'packets' / (packet_id + '.json'), packet)
            write(tmp_path / 'api_attempts' / (request_id + '.result.json'), {
                'status': 'success', 'request_id': request_id,
                'bundle_fingerprint': packet_id, 'response': response})
            records.append({'request_id': request_id, 'packet_id': packet_id,
                            'flag': {'row_id': 'ROW-' + str(index)}})
        write(parent / 'manifest.json', {'records': records})
    return tmp_path, response


def test_replication_sends_exact_payload_and_preserves_original(parents, monkeypatch):
    root, body = parents
    repeat.prepare(root)
    sent = []
    def post(url, **kwargs):
        sent.append(kwargs)
        return SimpleNamespace(status_code=200, json=lambda: copy.deepcopy(body))
    monkeypatch.setattr(requests, 'post', post)
    repeat.submit(root, root, 1)
    record = read(root / repeat.LABEL / 'manifest.json')['records'][0]
    original = read(root / record['parent_run'] / 'requests' / (record['request_id'] + '.json'))
    assert sent[0]['json'] == original
    assert sent[0]['timeout'] == (5, 20) and sent[0]['allow_redirects'] is False
    assert read(root / 'api_attempts' / (record['attempt_id'] + '.result.json'))['request_id'] == record['request_id']
    assert repeat.sha(root / 'api_attempts' / (record['request_id'] + '.result.json')) == record['parent_receipt_sha256']
    assert not (root / 'api_session.lock').exists()


def test_unknown_submission_is_not_retried(parents, monkeypatch):
    root, _ = parents
    repeat.prepare(root)
    sent = []
    def fail(url, **kwargs):
        sent.append(fingerprint(kwargs['json']))
        raise requests.Timeout()
    monkeypatch.setattr(requests, 'post', fail)
    repeat.submit(root, root, 8)
    repeat.submit(root, root, 8)
    assert len(sent) == len(set(sent)) == 2
    receipts = [read(p) for p in (root / 'api_attempts').glob('repeat_*.result.json')]
    assert all(r['status'] == 'transport_error_unknown_submission' for r in receipts)


@pytest.mark.parametrize('tamper', ['payload', 'parent_receipt', 'attempt_id'])
def test_changed_repeat_is_rejected_before_network(parents, monkeypatch, tamper):
    root, _ = parents
    repeat.prepare(root)
    manifest_path = root / repeat.LABEL / 'manifest.json'
    manifest = read(manifest_path)
    record = manifest['records'][0]
    if tamper == 'payload':
        path = root / repeat.LABEL / 'requests' / (record['request_id'] + '.json')
        value = read(path)
        value['state'] = 'different evidence'
    elif tamper == 'parent_receipt':
        path = root / 'api_attempts' / (record['request_id'] + '.result.json')
        value = {'status': 'changed'}
    else:
        path, value = manifest_path, manifest
        value['records'][0]['attempt_id'] = 'arbitrary'
    path.write_text(json.dumps(value), encoding='utf-8')
    monkeypatch.setattr(requests, 'post', lambda *a, **kw: pytest.fail('Unexpected network call'))
    with pytest.raises(ValueError):
        repeat.submit(root, root, 1)
    assert not list((root / 'api_attempts').glob('repeat_*.started.json'))
    assert not (root / 'api_session.lock').exists()


def test_existing_session_lock_is_preserved(parents, monkeypatch):
    root, _ = parents
    repeat.prepare(root)
    lock = root / 'api_session.lock'
    lock.write_text('another process', encoding='utf-8')
    monkeypatch.setattr(requests, 'post', lambda *a, **kw: pytest.fail('Unexpected network call'))
    with pytest.raises(FileExistsError):
        repeat.submit(root, root, 1)
    assert lock.read_text() == 'another process'


def test_session_budget_is_checked_again_at_submission(parents, monkeypatch):
    root, _ = parents
    repeat.prepare(root)
    for index in range(100):
        write(root / 'api_attempts' / (str(index) + '.started.json'), {})
    monkeypatch.setattr(requests, 'post', lambda *a, **kw: pytest.fail('Unexpected network call'))
    repeat.submit(root, root, 8)
    assert not list((root / 'api_attempts').glob('repeat_*.started.json'))


def test_replication_cannot_be_prepared_over_session_cap(parents):
    root, _ = parents
    for index in range(93):
        write(root / 'api_attempts' / (str(index) + '.started.json'), {})
    with pytest.raises(ValueError, match='budget'):
        repeat.prepare(root)
    assert not (root / repeat.LABEL).exists()
