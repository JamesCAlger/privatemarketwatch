"""Bounded Jev shadow runner; artifacts only in the isolated pilot run directory."""
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

from pipeline.jev_bundles import make_request
from pipeline.jev_screening import Policy, fingerprint, route_flag, valid_confidence
from scripts.jev_pilot_session import install_read_only_guard, read, sha, write

ENDPOINT = 'https://api.typesafe.ai/v1/systemone'


def validate_arm(arm, bundle_directory, run_root):
    """A consumed holdout may be replayed, but never relabelled as blind evidence."""
    frozen = run_root / 'holdout_frozen_01'
    if arm == 'holdout':
        if bundle_directory.resolve() != frozen.resolve():
            raise ValueError('Holdout requires the original frozen bundle directory')
        if (run_root / 'holdout_development_02').exists():
            raise ValueError('Holdout was consumed; use consumed_holdout development arm')
    if arm == 'consumed_holdout' and not (run_root / 'holdout_development_02').exists():
        raise ValueError('Consumed holdout development evidence is missing')
    if arm == 'temporal_holdout':
        if bundle_directory.resolve() != (run_root / 'temporal_frozen_01').resolve():
            raise ValueError('Temporal holdout requires the original frozen packets')
        frozen = read(bundle_directory / 'frozen_builder.json')
        if frozen.get('arm') != 'within_filer_unseen_accession':
            raise ValueError('Temporal holdout identity is missing')
        if sha(ROOT / 'pipeline/jev_bundles.py') != frozen['builder_sha256']:
            raise ValueError('Builder changed after temporal freeze; evidence is development now')


def validate_response(body, request):
    if not isinstance(body, dict) or body.get('model') != request['model']:
        raise ValueError('Model version mismatch')
    if not isinstance(body.get('answers'), dict) or set(body['answers']) != set(request['questions']):
        raise ValueError('Missing or unexpected answers')
    for name, question in request['questions'].items():
        answer = body['answers'][name]
        if not isinstance(answer, dict) or answer.get('type') != 'choice' or answer.get('choice') not in question['criteria']:
            raise ValueError('Malformed choice')
        probabilities = answer.get('probabilities', {})
        if not isinstance(probabilities, dict) or set(probabilities) != set(question['criteria']) or not all(valid_confidence(p) for p in probabilities.values()):
            raise ValueError('Malformed probabilities')
        if abs(sum(probabilities.values()) - 1) > 0.010000001 or not valid_confidence(answer.get('confidence')):
            raise ValueError('Malformed confidence or probability sum')
        count = len(probabilities)
        if count < 2:
            raise ValueError('Choice requires at least two outcomes')
        expected = (max(probabilities.values()) - 1 / count) / (1 - 1 / count)
        # Provider returns rounded observations. Allow a bounded 0.02 rounding
        # margin, not contradictory confidence or a non-winning selected option.
        if abs(expected - answer['confidence']) > 0.020000001:
            raise ValueError('Confidence contradicts the Choice distribution')
        if probabilities[answer['choice']] + 0.010000001 < max(probabilities.values()):
            raise ValueError('Selected choice is not a distribution maximum')
    if not isinstance(body.get('usage'), dict):
        raise ValueError('Missing token usage')
    tokens = body['usage'].get('input_tokens')
    if isinstance(tokens, bool) or not isinstance(tokens, int) or tokens < 0:
        raise ValueError('Missing token usage')


def decode_observation(observed, record, request):
    """Do not transfer a successful answer to a different packet during replay."""
    if (observed.get('request_id') != record['request_id']
            or observed.get('bundle_fingerprint') != record['packet_id']
            or fingerprint(request) != record['request_id']):
        return {'status': 'receipt_request_mismatch'}
    result = {'status': observed['status'], 'bundle_fingerprint': record['packet_id']}
    if observed['status'] == 'success':
        body = observed.get('response')
        try:
            validate_response(body, request)
        except (ValueError, TypeError, KeyError, AttributeError):
            return {'status': 'invalid_persisted_response'}
        result.update(model=body['model'], decision=body['answers']['decision']['choice'],
                      decision_confidence=body['answers']['decision']['confidence'],
                      source_id=body['answers']['source_match']['choice'],
                      source_confidence=body['answers']['source_match']['confidence'])
    return result


def prepare(args):
    import tiktoken
    validate_arm(args.arm, args.bundles, args.run_root)
    run = args.run_root / args.label
    if run.exists():
        raise ValueError('Run label exists; frozen inputs cannot be replaced')
    packets = []
    for path in sorted(args.bundles.glob('*.json')):
        packet = read(path)
        if isinstance(packet, dict) and packet.get('schema_version', '').startswith('jev-value-bundle.'):
            packets.append((path, packet))
    if not 1 <= len(packets) <= 50:
        raise ValueError('Expected 1..50 explicit packets')
    session = read(args.run_root / 'session.json')
    reservation = read(args.run_root / 'holdout_reservation_v2.json')
    allowed = (set(reservation['all_previously_exercised_ciks']) if args.arm == 'development'
               else {r['cik'] for r in reservation['holdout_funds']})
    if args.arm in {'controlled', 'weak_probe'}:
        allowed |= set(reservation['all_previously_exercised_ciks'])
    if args.arm == 'weak_probe' and (len(packets) > 6 or any(p['rule']['id'] != 'C104' for _, p in packets)):
        raise ValueError('Weak probe is limited to six C104 development flags')
    if args.arm == 'temporal_holdout' and len(packets) > 4:
        raise ValueError('Temporal holdout is limited to four flags')
    if args.arm == 'controlled':
        if any(not p.get('provenance', {}).get('controlled_mutation') for _, p in packets):
            raise ValueError('Controlled arm requires explicit mutation provenance')
    if not {p['flag']['cik'] for _, p in packets} <= allowed:
        raise ValueError('Packets exceed the frozen arm fund manifest')
    if args.arm != 'development' and len(packets) > session['limits']['holdout_flags']:
        raise ValueError('Holdout flag budget exceeded')
    references = read(args.references) if args.references else {}
    if args.arm != 'development' and any(p['flag']['row_id'] not in references for _, p in packets):
        raise ValueError('Freeze a source-reviewed reference, ambiguity or unscorable outcome for every holdout flag')
    policy = Policy(eligible_rules=('C104',), version='shadow-c104-probe.v1') if args.arm == 'weak_probe' else Policy()
    tokenizer = tiktoken.get_encoding('cl100k_base')
    run.mkdir()
    (run / 'packets').mkdir()
    (run / 'requests').mkdir()
    records = []
    for path, packet in packets:
        packet_id = fingerprint(packet)
        write(run / 'packets' / (packet_id + '.json'), packet)
        record = {'packet_id': packet_id, 'original_packet_path': str(path), 'original_sha256': sha(path),
                  'flag': packet['flag'], 'request_id': None, 'proxy_tokens': None,
                  'audit': references.get(packet['flag']['row_id'], {}).get('audit')}
        preflight = route_flag(packet, None, record['audit'], policy=policy,
                               expected_provenance=packet['provenance'])
        if preflight['route'] == 'pending':
            request = make_request(packet, model=policy.model)
            count = len(tokenizer.encode(json.dumps(request, ensure_ascii=True), disallowed_special=()))
            record['proxy_tokens'] = count
            if count <= 26000:
                request_id = fingerprint(request)
                write(run / 'requests' / (request_id + '.json'), request)
                record['request_id'] = request_id
            else:
                record['not_submitted_reason'] = 'request_proxy_token_limit'
        else:
            record['not_submitted_reason'] = ','.join(preflight['reasons'])
        records.append(record)
    write(run / 'references.json', references)
    from dataclasses import asdict
    manifest = {'arm': args.arm, 'created_utc': datetime.now(timezone.utc).isoformat(),
                'records': records, 'policy': asdict(policy), 'references_sha256': sha(run / 'references.json'),
                'runner_sha256': sha(Path(__file__)), 'routing_sha256': sha(ROOT / 'pipeline/jev_screening.py'),
                'untouched_holdout': args.arm == 'holdout',
                'within_filer_temporal_holdout': args.arm == 'temporal_holdout',
                'production_clearance_enabled': False}
    write(run / 'manifest.json', manifest)
    print(json.dumps({'packets': len(records), 'requests': sum(bool(r['request_id']) for r in records)}), flush=True)


def run_requests(args):
    import requests
    from dotenv import dotenv_values
    run = args.run_root / args.label
    manifest = read(run / 'manifest.json')
    if sha(Path(__file__)) != manifest['runner_sha256'] or sha(ROOT / 'pipeline/jev_screening.py') != manifest['routing_sha256']:
        raise ValueError('Runner or routing changed after freeze')
    if sha(run / 'references.json') != manifest['references_sha256']:
        raise ValueError('References changed after freeze')
    key = os.environ.get('TYPESAFE_API_KEY') or dotenv_values(args.repo / '.env').get('TYPESAFE_API_KEY')
    if not key or not key.strip():
        raise ValueError('TYPESAFE_API_KEY is not configured')
    attempts = args.run_root / 'api_attempts'
    attempts.mkdir(exist_ok=True)
    lock_path = args.run_root / 'api_session.lock'
    with lock_path.open('x', encoding='utf-8') as lock:
        lock.write(str(os.getpid()))
    started, calls = time.monotonic(), 0
    try:
        for record in manifest['records']:
            if calls >= args.limit or time.monotonic() - started > 45:
                break
            request_id = record['request_id']
            if not request_id or (attempts / (request_id + '.started.json')).exists():
                continue
            if len(list(attempts.glob('*.started.json'))) >= 100:
                print('Session request limit reached', flush=True)
                break
            request = read(run / 'requests' / (request_id + '.json'))
            if fingerprint(request) != request_id:
                raise ValueError('Request changed after freeze')
            write(attempts / (request_id + '.started.json'),
                  {'request_id': request_id, 'run': args.label, 'started_utc': datetime.now(timezone.utc).isoformat()})
            calls += 1
            then = time.monotonic()
            receipt = {'request_id': request_id, 'status': 'unknown', 'bundle_fingerprint': record['packet_id']}
            try:
                response = requests.post(ENDPOINT, json=request, headers={'Authorization': 'Bearer ' + key},
                                         timeout=(5, 20), allow_redirects=False)
                receipt['http_status'] = response.status_code
                if response.status_code != 200:
                    receipt['status'] = 'http_error'
                else:
                    body = response.json()
                    validate_response(body, request)
                    receipt.update(status='success', response=body)
            except requests.RequestException:
                receipt['status'] = 'transport_error_unknown_submission'
            except (ValueError, TypeError, KeyError):
                receipt['status'] = 'invalid_response_schema'
            receipt['elapsed_seconds'] = time.monotonic() - then
            write(attempts / (request_id + '.result.json'), receipt)
            print(json.dumps({'request_id': request_id[:12], 'status': receipt['status']}), flush=True)
            if receipt['status'] != 'success':
                break
    finally:
        lock_path.unlink()


def summarize(args):
    run = args.run_root / args.label
    manifest = read(run / 'manifest.json')
    policy = Policy(**manifest['policy'])
    receipts = []
    for record in manifest['records']:
        packet = read(run / 'packets' / (record['packet_id'] + '.json'))
        if fingerprint(packet) != record['packet_id']:
            raise ValueError('Frozen packet changed')
        result = None
        path = args.run_root / 'api_attempts' / (str(record['request_id']) + '.result.json')
        if path.exists():
            observed = read(path)
            request = read(run / 'requests' / (record['request_id'] + '.json'))
            result = decode_observation(observed, record, request)
        elif record['request_id'] and (args.run_root / 'api_attempts' / (record['request_id'] + '.started.json')).exists():
            result = {'status': 'unknown_submission'}
        elif record.get('not_submitted_reason') == 'request_proxy_token_limit':
            result = {'status': 'request_proxy_token_limit'}
        receipts.append(route_flag(packet, result, record['audit'], policy=policy,
                                   expected_provenance=packet['provenance']))
    from collections import Counter
    report = {'receipts': receipts, 'routes': dict(Counter(r['route'] for r in receipts)),
              'production_clearance_enabled': False, 'all_b1_work_retained': True}
    destination = run / ('routing_' + fingerprint(report)[:16] + '.json')
    if not destination.exists():
        write(destination, report)
    print(json.dumps({'routes': report['routes'], 'report': str(destination)}), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['prepare', 'run', 'summarize'])
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--run-root', type=Path, required=True)
    parser.add_argument('--label', required=True)
    parser.add_argument('--bundles', type=Path)
    parser.add_argument('--references', type=Path)
    parser.add_argument('--arm', choices=['development', 'holdout', 'consumed_holdout', 'controlled', 'weak_probe', 'temporal_holdout'], default='development')
    parser.add_argument('--limit', type=int, default=10)
    args = parser.parse_args()
    args.repo, args.run_root = args.repo.resolve(), args.run_root.resolve()
    if args.repo == ROOT or not args.run_root.is_relative_to(args.repo / 'data/pilot/jev_screening'):
        raise ValueError('Require isolated worktree and pilot artifact root')
    if not args.label.replace('_', '').isalnum() or not 1 <= args.limit <= 10:
        raise ValueError('Invalid run label or limit (1..10)')
    if args.action == 'prepare' and args.bundles is None:
        parser.error('--bundles is required for prepare')
    install_read_only_guard(args.repo, args.run_root)
    {'prepare': prepare, 'run': run_requests, 'summarize': summarize}[args.action](args)


if __name__ == '__main__':
    main()
