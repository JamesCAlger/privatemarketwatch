"""Render factual explanations for a bounded frozen experiment; no API calls."""
import argparse
from collections import Counter
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from pipeline.jev_explanation import explain_receipt
from pipeline.jev_screening import Policy, fingerprint, route_flag
from scripts.jev_pilot_session import install_read_only_guard, read, sha, write
from scripts.run_jev_screening import decode_observation


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--run-root', type=Path, required=True)
    parser.add_argument('--label', required=True)
    args = parser.parse_args()
    repo, root = args.repo.resolve(), args.run_root.resolve()
    if repo == ROOT or not root.is_relative_to(repo / 'data/pilot/jev_screening'):
        raise ValueError('Isolated pilot required')
    if not args.label.replace('_', '').isalnum():
        raise ValueError('Invalid experiment label')
    install_read_only_guard(repo, root)
    run = root / args.label
    manifest = read(run / 'manifest.json')
    if not 1 <= len(manifest['records']) <= 20:
        raise ValueError('Bounded explanation run required')
    policy = Policy(**manifest['policy'])
    explanations = []
    for record in manifest['records']:
        bundle = read(run / 'packets' / (record['packet_id'] + '.json'))
        if fingerprint(bundle) != record['packet_id']:
            raise ValueError('Frozen bundle changed')
        result, provider_receipt_hash = None, None
        attempt = record.get('attempt_id') or record['request_id']
        path = root / 'api_attempts' / (str(attempt) + '.result.json')
        if path.exists():
            request = read(run / 'requests' / (record['request_id'] + '.json'))
            result = decode_observation(read(path), record, request)
            provider_receipt_hash = sha(path)
        elif attempt and (root / 'api_attempts' / (str(attempt) + '.started.json')).exists():
            result = {'status': 'unknown_submission'}
        elif record.get('not_submitted_reason'):
            result = {'status': record['not_submitted_reason']}
        receipt = route_flag(bundle, result, record.get('audit'), policy=policy,
                             expected_provenance=bundle['provenance'])
        explanations.append({**explain_receipt(bundle, receipt),
                             'routing_receipt': receipt,
                             'provider_receipt_sha256': provider_receipt_hash})
    report = {'experiment': args.label, 'arm': manifest['arm'], 'records': explanations,
              'manifest_sha256': sha(run / 'manifest.json'),
              'explanation_sha256': sha(ROOT / 'pipeline/jev_explanation.py'),
              'router_sha256': sha(ROOT / 'pipeline/jev_screening.py'),
              'routes': dict(Counter(e['route'] for e in explanations)),
              'historical_observations_not_current_revalidation': True,
              'api_calls': 0, 'production_clearance_allowed': False,
              'limitation': 'Readable facts do not replace B1 causal investigation or an independent source audit.'}
    target = run / ('factual_explanations_' + fingerprint(report)[:16] + '.json')
    if not target.exists():
        write(target, report)
    print(json.dumps({'experiment': args.label, 'records': len(explanations), 'routes': report['routes'],
                      'examples': [r['summary'] for r in explanations[:2]]}), flush=True)


if __name__ == '__main__':
    main()
