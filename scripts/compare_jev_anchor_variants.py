"""Compare exact and raw-preserving anchor baselines on frozen model inputs."""
import argparse
from collections import Counter
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from pipeline.jev_anchor_baseline import compare_context_anchor
from pipeline.jev_screening import fingerprint
from scripts.analyze_jev_screening import summarize
from scripts.compare_jev_bundle_versions import NATURAL_RUNS
from scripts.compare_jev_retrieval import load_replay
from scripts.jev_pilot_session import install_read_only_guard, read, sha, write


def current_replay(root, label):
    summary, packets = load_replay(root, label)
    if len(packets)>100 or summary['builder_sha256'] != sha(ROOT / 'pipeline/jev_bundles.py'):
        raise ValueError('Bounded current replay required')
    rows = []
    for (rule, row_id), packet in sorted(packets.items()):
        rows.append({'rule': rule, 'row_id': row_id, 'cik': packet['flag']['cik'],
            'bundle_fingerprint': fingerprint(packet), 'evidence_status': packet['evidence_status']['status'],
            'exact': compare_context_anchor(packet),
            'raw': compare_context_anchor(packet, allow_raw_identifier=True)})
    report = {'replay': label, 'builder_sha256': summary['builder_sha256'],
        'selected_flags': len(rows), 'ready_flags': sum(r['evidence_status']=='ready_for_model' for r in rows),
        'exact_statuses': dict(Counter(r['exact']['status'] for r in rows)),
        'raw_statuses': dict(Counter(r['raw']['status'] for r in rows)),
        'ready_raw_statuses': dict(Counter(r['raw']['status'] for r in rows if r['evidence_status']=='ready_for_model')),
        'ready_unresolved': [r for r in rows if r['evidence_status']=='ready_for_model' and r['raw']['status']=='unresolved'],
        'observations': rows, 'audited_clearances': 0, 'api_calls': 0, 'production_clearance_enabled': False,
        'limitation': 'Current structured evidence only: no reference-label or model-score transfer, independent source certification or accuracy estimate.'}
    destination = root / ('current_anchor_profile_' + fingerprint(report)[:16] + '.json')
    if not destination.exists():
        write(destination, report)
    print(json.dumps({'artifact': destination.name, **{k: v for k, v in report.items() if k not in {'observations', 'ready_unresolved'}}}), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--run-root', type=Path, required=True)
    parser.add_argument('--replay', help='Profile a current replay without transferring historical labels')
    args = parser.parse_args()
    repo, root = args.repo.resolve(), args.run_root.resolve()
    if repo == ROOT or not root.is_relative_to(repo / 'data/pilot/jev_screening'):
        raise ValueError('Isolated pilot required')
    install_read_only_guard(repo, root)
    if args.replay:
        current_replay(root, args.replay)
        return
    rows, seen = [], set()
    for label in NATURAL_RUNS:
        run = root / label
        report = summarize(run, root / 'api_attempts')
        manifest, references = read(run / 'manifest.json'), read(run / 'references.json')
        records = {r['request_id']: r for r in manifest['records'] if r['request_id']}
        for observed in report['observations']:
            if observed['status'] != 'success':
                continue
            row_id = observed['flag']['row_id']
            key = (observed['flag']['rule_id'], row_id)
            if key in seen:
                raise ValueError('Repeated natural observation')
            seen.add(key)
            record = records[observed['request_id']]
            packet = read(run / 'packets' / (record['packet_id'] + '.json'))
            if fingerprint(packet) != record['packet_id']:
                raise ValueError('Frozen packet changed')
            exact = compare_context_anchor(packet)
            raw = compare_context_anchor(packet, allow_raw_identifier=True)
            reference = references[row_id]
            expected = {'anchor_consistent': 'false_alarm', 'anchor_mismatch': 'real_error'}.get(raw['status'])
            rows.append({'run': label, 'row_id': row_id, 'rule': key[0],
                         'packet_id': record['packet_id'], 'exact': exact, 'raw': raw,
                         'expected': reference['expected'], 'expected_source': reference['expected_source'],
                         'raw_source_agreement': raw['source_id'] == reference['expected_source'] and raw['status'] != 'unresolved',
                         'raw_label_agreement': expected == reference['expected'],
                         'jev_label_agreement': observed['label_agreement'],
                         'jev_source_agreement': observed['source_agreement']})
    report = {
        'natural_model_called_flags': len(rows),
        'exact_resolved': sum(r['exact']['status'] != 'unresolved' for r in rows),
        'raw_resolved': sum(r['raw']['status'] != 'unresolved' for r in rows),
        'raw_label_agreement': sum(r['raw_label_agreement'] for r in rows),
        'raw_source_agreement': sum(r['raw_source_agreement'] for r in rows),
        'jev_label_agreement': sum(r['jev_label_agreement'] for r in rows),
        'jev_source_agreement': sum(r['jev_source_agreement'] for r in rows),
        'new_resolutions': [r['row_id'] for r in rows if r['exact']['status'] == 'unresolved' and r['raw']['status'] != 'unresolved'],
        'observations': rows, 'audited_clearances': 0, 'api_calls': 0,
        'limitations': ['Development comparator uses a narrow observed affiliation-prefix normalization and exact retained raw dimension.',
                        'All model-called natural references are false alarms; no natural true-error sensitivity estimate.',
                        'Historical frozen builder inputs; later evidence guards invalidated some readiness claims.',
                        'Shared builder and pipeline provenance, not independent source/chain certification. No production routing.']}
    destination = root / ('anchor_variant_comparison_' + fingerprint(report)[:16] + '.json')
    if not destination.exists():
        write(destination, report)
    print(json.dumps({k: v for k, v in report.items() if k not in {'observations', 'limitations'}}), flush=True)


if __name__ == '__main__':
    main()
