"""Bounded exact-request replication for the frozen presentation experiment.

Separate attempt IDs preserve identical provider payloads without overwriting or
reusing prior responses. Unknown submissions are never automatically retried.
This arm does not produce screening clearances or new natural observations.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from pipeline.jev_screening import fingerprint
from scripts.jev_pilot_session import install_read_only_guard, read, sha, write
from scripts.run_jev_screening import ENDPOINT, validate_response

PARENTS = ('order_normal_model_01', 'order_reverse_model_01')
LABEL = 'order_repeat_model_01'


def validate_frozen_record(run, record):
    request_id = record['request_id']
    request = read(run / 'requests' / (request_id + '.json'))
    if fingerprint(request) != request_id:
        raise ValueError('Frozen repeated request changed')
    parent = run.parent / record['parent_run']
    if record['parent_run'] not in PARENTS:
        raise ValueError('Unsupported parent')
    if request != read(parent / 'requests' / (request_id + '.json')):
        raise ValueError('Repeated payload differs from parent')
    if record['attempt_id'] != 'repeat_' + fingerprint({'replication': LABEL, 'request_id': request_id}):
        raise ValueError('Repeat attempt identity changed')
    packet = read(run / 'packets' / (record['packet_id'] + '.json'))
    if fingerprint(packet) != record['packet_id']:
        raise ValueError('Frozen repeated packet changed')
    return request


def prepare(root):
    records, packets, requests = [], {}, {}
    parents = []
    for label in PARENTS:
        parent = root / label
        manifest = read(parent / 'manifest.json')
        if len(manifest['records']) != 4:
            raise ValueError('Expected four frozen presentation cases')
        parents.append({'run': label, 'manifest_sha256': sha(parent / 'manifest.json')})
        for item in manifest['records']:
            request_id, packet_id = item['request_id'], item['packet_id']
            request = read(parent / 'requests' / (request_id + '.json'))
            packet = read(parent / 'packets' / (packet_id + '.json'))
            receipt = read(root / 'api_attempts' / (request_id + '.result.json'))
            if fingerprint(request) != request_id or fingerprint(packet) != packet_id:
                raise ValueError('Parent packet or request changed')
            if (receipt['status'] != 'success' or receipt['request_id'] != request_id
                    or receipt['bundle_fingerprint'] != packet_id):
                raise ValueError('Parent response unavailable or mismatched')
            validate_response(receipt['response'], request)
            records.append({**item, 'parent_run': label,
                            'attempt_id': 'repeat_' + fingerprint({'replication': LABEL, 'request_id': request_id}),
                            'parent_receipt_sha256': sha(root / 'api_attempts' / (request_id + '.result.json'))})
            packets[packet_id], requests[request_id] = packet, request
    if len(records) != 8 or len(requests) != 8:
        raise ValueError('Expected eight distinct original requests')
    if len(list((root / 'api_attempts').glob('*.started.json'))) + 8 > 100:
        raise ValueError('Insufficient session budget')
    run = root / LABEL
    run.mkdir()
    (run / 'packets').mkdir()
    (run / 'requests').mkdir()
    for key, packet in packets.items():
        write(run / 'packets' / (key + '.json'), packet)
    for key, request in requests.items():
        write(run / 'requests' / (key + '.json'), request)
    # Alternate normal/reversed presentation for each case in the repeat arm.
    records.sort(key=lambda r: (r['flag']['row_id'], r['parent_run']))
    manifest = {'arm': 'exact_request_replication', 'records': records, 'parents': parents,
                'runner_sha256': sha(Path(__file__)),
                'response_validator_sha256': sha(ROOT / 'scripts/run_jev_screening.py'),
                'created_utc': datetime.now(timezone.utc).isoformat(),
                'production_clearance_enabled': False, 'natural_flags_added': 0}
    write(run / 'manifest.json', manifest)
    print(json.dumps({'replication_requests': len(records), 'new_payloads': 0}), flush=True)


def submit(root, repo, limit):
    import requests
    from dotenv import dotenv_values
    run, attempts = root / LABEL, root / 'api_attempts'
    manifest = read(run / 'manifest.json')
    if (manifest['runner_sha256'] != sha(Path(__file__)) or
            manifest['response_validator_sha256'] != sha(ROOT / 'scripts/run_jev_screening.py')):
        raise ValueError('Replication code changed after freeze')
    if len(manifest['records']) != 8:
        raise ValueError('Replication manifest exceeds fixed selection')
    for parent in manifest['parents']:
        if sha(root / parent['run'] / 'manifest.json') != parent['manifest_sha256']:
            raise ValueError('Parent manifest changed')
    key = os.environ.get('TYPESAFE_API_KEY') or dotenv_values(repo / '.env').get('TYPESAFE_API_KEY')
    if not key or not key.strip():
        raise ValueError('TYPESAFE_API_KEY is not configured')
    lock_path = root / 'api_session.lock'
    with lock_path.open('x', encoding='utf-8') as lock:
        lock.write(str(os.getpid()))
    started, calls = time.monotonic(), 0
    try:
        for record in manifest['records']:
            if calls >= limit or time.monotonic() - started > 45:
                break
            request_id, attempt_id = record['request_id'], record['attempt_id']
            if (attempts / (attempt_id + '.started.json')).exists():
                continue
            if len(list(attempts.glob('*.started.json'))) >= 100:
                break
            request = validate_frozen_record(run, record)
            if sha(attempts / (request_id + '.result.json')) != record['parent_receipt_sha256']:
                raise ValueError('Parent receipt changed')
            write(attempts / (attempt_id + '.started.json'), {
                'request_id': request_id, 'attempt_id': attempt_id, 'run': LABEL,
                'started_utc': datetime.now(timezone.utc).isoformat()})
            calls += 1
            then = time.monotonic()
            receipt = {'request_id': request_id, 'attempt_id': attempt_id, 'status': 'unknown',
                       'bundle_fingerprint': record['packet_id']}
            try:
                response = requests.post(ENDPOINT, json=request,
                                         headers={'Authorization': 'Bearer ' + key},
                                         timeout=(5, 20), allow_redirects=False)
                receipt['http_status'] = response.status_code
                if response.status_code == 200:
                    body = response.json()
                    validate_response(body, request)
                    receipt.update(status='success', response=body)
                else:
                    receipt['status'] = 'http_error'
            except requests.RequestException:
                receipt['status'] = 'transport_error_unknown_submission'
            except (ValueError, TypeError, KeyError, AttributeError):
                receipt['status'] = 'invalid_response_schema'
            receipt['elapsed_seconds'] = time.monotonic() - then
            write(attempts / (attempt_id + '.result.json'), receipt)
            print(json.dumps({'attempt_id': attempt_id[:19], 'status': receipt['status']}), flush=True)
            if receipt['status'] != 'success':
                break
    finally:
        lock_path.unlink()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['prepare', 'run'])
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--run-root', type=Path, required=True)
    parser.add_argument('--limit', type=int, default=4, choices=range(1, 9))
    args = parser.parse_args()
    repo, root = args.repo.resolve(), args.run_root.resolve()
    if repo == ROOT or not root.is_relative_to(repo / 'data/pilot/jev_screening'):
        raise ValueError('Isolated pilot required')
    install_read_only_guard(repo, root)
    if args.action == 'prepare':
        prepare(root)
    else:
        submit(root, repo, args.limit)


if __name__ == '__main__':
    main()
