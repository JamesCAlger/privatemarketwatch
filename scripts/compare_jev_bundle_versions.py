"""Compare historical observations with a complete, explicitly chosen replay set."""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from pipeline.jev_bundles import make_request
from pipeline.jev_screening import fingerprint
from scripts.analyze_jev_screening import summarize
from scripts.compare_jev_retrieval import load_replay
from scripts.jev_pilot_session import install_read_only_guard, read, sha, write

NATURAL_RUNS = ('development_model_01', 'consumed_holdout_model_01', 'weak_probe_model_01',
                'newly_ready_model_01', 'legend_model_01', 'temporal_model_01',
                'grouped_header_model_01')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--run-root', type=Path, required=True)
    parser.add_argument('--replays', nargs='+', required=True)
    args = parser.parse_args()
    repo, run = args.repo.resolve(), args.run_root.resolve()
    if repo == ROOT or not run.is_relative_to(repo / 'data/pilot/jev_screening'):
        raise ValueError('Isolated pilot required')
    install_read_only_guard(repo, run)
    current, hashes = {}, set()
    for label in args.replays:
        summary, packets = load_replay(run, label)
        hashes.add(summary['builder_sha256'])
        for key, packet in packets.items():
            if key in current:
                raise ValueError('Overlapping replay selections')
            current[key] = (packet, label)
    if len(hashes) != 1 or next(iter(hashes)) != sha(ROOT / 'pipeline/jev_bundles.py'):
        raise ValueError('Replays must use one current frozen builder')
    if len(current) > 100:
        raise ValueError('Comparison exceeds bounded pilot')
    historical = {}
    for label in NATURAL_RUNS:
        report = summarize(run / label, run / 'api_attempts')
        manifest = read(run / label / 'manifest.json')
        records = {(r['flag']['rule_id'], r['flag']['row_id']): r for r in manifest['records']}
        for row in report['observations']:
            key = (row['flag']['rule_id'], row['flag']['row_id'])
            if key in historical and historical[key]['status'] == 'success':
                raise ValueError('Duplicate successful natural observation')
            record = records[key]
            old = read(run / label / 'packets' / (record['packet_id'] + '.json'))
            latest, replay = current[key]
            ready = latest['evidence_status']['status'] == 'ready_for_model'
            same_request = False
            if row['status'] == 'success' and ready:
                original_request = read(run / label / 'requests' / (record['request_id'] + '.json'))
                same_request = fingerprint(make_request(latest)) == fingerprint(original_request)
            historical[key] = {
                'rule': key[0], 'row_id': key[1], 'historical_run': label,
                'status': row['status'], 'historical_confidence_candidate': row.get('confidence_eligible', False),
                'current_replay': replay, 'current_ready': ready,
                'exact_request_unchanged': same_request,
                'old_notes': sum(len(c['notes']) for c in old['source_candidates']),
                'current_notes': sum(len(c['notes']) for c in latest['source_candidates']),
                'current_blocking_reasons': latest['evidence_status']['blocking_reasons'],
            }
    if set(current) != set(historical):
        raise ValueError('Historical and replay flag sets differ')
    rows = list(historical.values())
    candidates = [r for r in rows if r['historical_confidence_candidate']]
    report = {
        'builder_sha256': next(iter(hashes)), 'flags': len(rows),
        'current_readiness': dict(Counter('ready' if r['current_ready'] else 'blocked' for r in rows)),
        'historical_confidence_candidates': len(candidates),
        'historical_candidates_currently_ready': sum(r['current_ready'] for r in candidates),
        'historical_candidates_exact_request_unchanged': sum(r['exact_request_unchanged'] for r in candidates),
        'audited_clearances': 0, 'observations': rows,
        'limitation': 'Readiness is not audited completeness. Historical confidence is not transferred to changed requests. No API calls or production routing.',
    }
    recheck_bindings = []
    for label in ('current_development_model_01', 'current_consumed_model_01'):
        manifest_path = run / label / 'manifest.json'
        if not manifest_path.exists():
            continue
        records = read(manifest_path)['records']
        if len(records) > 50:
            raise ValueError('Unbounded recheck manifest')
        for record in records:
            if not record['request_id']:
                continue
            key = (record['flag']['rule_id'], record['flag']['row_id'])
            packet, _ = current[key]
            original = read(run / label / 'requests' / (record['request_id'] + '.json'))
            if fingerprint(original) != record['request_id']:
                raise ValueError('Recheck request changed')
            ready = packet['evidence_status']['status'] == 'ready_for_model'
            current_request = make_request(packet) if ready else None
            exact = ready and fingerprint(current_request) == record['request_id']
            # Diagnostic only: the model did see this ID, so never treat this
            # comparison as permission to reuse a response for a changed request.
            without_id = json.loads(json.dumps(current_request)) if ready else None
            original_without_id = json.loads(json.dumps(original))
            if without_id is not None:
                without_id['state'].pop('bundle_id', None)
            original_without_id['state'].pop('bundle_id', None)
            recheck_bindings.append({'run': label, 'row_id': key[1], 'current_ready': ready,
                                    'exact_request_unchanged': exact,
                                    'only_bundle_id_changed': ready and not exact and fingerprint(without_id) == fingerprint(original_without_id)})
    report['current_recheck_request_bindings'] = recheck_bindings
    report['current_recheck_requests_unchanged'] = sum(r['exact_request_unchanged'] for r in recheck_bindings)
    report['current_recheck_only_bundle_id_changed'] = sum(r['only_bundle_id_changed'] for r in recheck_bindings)
    destination = run / ('bundle_version_comparison_' + fingerprint(report)[:16] + '.json')
    if not destination.exists():
        write(destination, report)
    print(json.dumps({k: v for k, v in report.items() if k not in {'observations', 'current_recheck_request_bindings'}}), flush=True)


if __name__ == '__main__':
    main()
