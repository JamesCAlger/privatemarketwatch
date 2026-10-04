"""Report the common-builder development recheck separately from natural intake."""
import argparse
from collections import Counter
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from pipeline.jev_anchor_baseline import compare_context_anchor
from pipeline.jev_screening import fingerprint, Policy, route_flag
from scripts.analyze_jev_screening import summarize
from scripts.jev_pilot_session import install_read_only_guard, read, write
from scripts.run_jev_screening import decode_observation


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--run-root', type=Path, required=True)
    args = parser.parse_args()
    repo, root = args.repo.resolve(), args.run_root.resolve()
    if repo == ROOT or not root.is_relative_to(repo / 'data/pilot/jev_screening'):
        raise ValueError('Isolated pilot required')
    install_read_only_guard(repo, root)
    selection = read(root / 'current_recheck_manifest_20.json')
    rows, routes = [], []
    historical = {}
    for label in {r['run'] for r in selection['prior_calls'].values()}:
        historical.update({r['flag']['row_id']: r for r in summarize(root / label, root / 'api_attempts')['observations']
                           if r['status'] == 'success'})
    for label in ('current_development_model_01', 'current_consumed_model_01'):
        run = root / label
        report, manifest = summarize(run, root / 'api_attempts'), read(run / 'manifest.json')
        records = {r['flag']['row_id']: r for r in manifest['records']}
        references = read(run / 'references.json')
        for row in report['observations']:
            row_id = row['flag']['row_id']
            record = records[row_id]
            packet = read(run / 'packets' / (record['packet_id'] + '.json'))
            if packet['provenance']['builder_sha256'] != selection['builder_sha256']:
                raise ValueError('Mixed builder versions in common-builder evaluation')
            raw = compare_context_anchor(packet, allow_raw_identifier=True)
            reference = references[row_id]
            decoded = None
            if row['status'] == 'success':
                request = read(run / 'requests' / (record['request_id'] + '.json'))
                receipt = read(root / 'api_attempts' / (record['request_id'] + '.result.json'))
                decoded = decode_observation(receipt, record, request)
            route = route_flag(packet, decoded, None, policy=Policy(**manifest['policy']),
                               expected_provenance=packet['provenance'])
            routes.append(route)
            previous = historical.get(row_id)
            rows.append({**row, 'current_run': label, 'raw_baseline': raw,
                         'raw_source_agreement': raw['status'] != 'unresolved' and raw['source_id'] == reference['expected_source'],
                         'raw_label_agreement': {'anchor_consistent': 'false_alarm', 'anchor_mismatch': 'real_error'}.get(raw['status']) == reference['expected'],
                         'prior_confidence_eligible': previous.get('confidence_eligible') if previous else None,
                         'route': route['route']})
    expected_ids = set(selection['ready_rechecks']) | set(selection['blocked_controls'])
    if len(rows) != 16 or {r['flag']['row_id'] for r in rows} != expected_ids:
        raise ValueError('Recheck accounting differs from frozen selection')
    successful = [r for r in rows if r['status'] == 'success']
    blocked = [r for r in rows if r['flag']['row_id'] in selection['blocked_controls']]
    report = {
        'builder_sha256': selection['builder_sha256'], 'flags': len(rows),
        'successful_rechecks': len(successful),
        'label_agreement': sum(r['label_agreement'] for r in successful),
        'source_agreement': sum(r['source_agreement'] for r in successful),
        'confidence_only_candidates': sum(r['confidence_eligible'] for r in successful),
        'confidence_eligibility_changed_from_older_bundle': sum(r['confidence_eligible'] != r['prior_confidence_eligible'] for r in successful),
        'raw_anchor_resolved': sum(r['raw_baseline']['status'] != 'unresolved' for r in successful),
        'raw_anchor_label_agreement': sum(r['raw_label_agreement'] for r in successful),
        'raw_anchor_source_agreement': sum(r['raw_source_agreement'] for r in successful),
        'known_errors_not_submitted': sum(r['status'] == 'not_submitted' for r in blocked),
        'routes': dict(Counter(r['route'] for r in rows)),
        'input_tokens': sum(r['input_tokens'] for r in successful),
        'observations': rows, 'routing_receipts': routes,
        'natural_flags_added': 0, 'audited_clearances': 0,
        'limitations': ['Purposive development recheck, not independent holdout or calibration.',
                        'All 12 called references are false alarms; four natural errors are pre-model fallbacks.',
                        'Changed confidence can reflect changed evidence and provider variability; not a causal repair effect.',
                        'Deterministic comparator shares source inputs and has no independent clearance authority.']}
    destination = root / ('current_recheck_' + fingerprint(report)[:16] + '.json')
    if not destination.exists():
        write(destination, report)
    print(json.dumps({k: v for k, v in report.items() if k not in {'observations', 'routing_receipts', 'limitations'}}), flush=True)


if __name__ == '__main__':
    main()
