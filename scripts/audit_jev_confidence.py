"""Check frozen responses against the documented Choice confidence contract."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from pipeline.jev_screening import fingerprint
from scripts.jev_pilot_session import install_read_only_guard, read, write
from scripts.run_jev_screening import validate_response


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--run-root', type=Path, required=True)
    args = parser.parse_args()
    repo, run = args.repo.resolve(), args.run_root.resolve()
    if repo == ROOT or not run.is_relative_to(repo / 'data/pilot/jev_screening'):
        raise ValueError('Isolated pilot required')
    install_read_only_guard(repo, run)
    records, seen = [], set()
    for label in ['development_model_01', 'consumed_holdout_model_01',
                  'controlled_model_01', 'weak_probe_model_01', 'newly_ready_model_01',
                  'sibling_model_01', 'scale_model_01', 'legend_model_01', 'temporal_model_01',
                  'order_normal_model_01', 'order_reverse_model_01', 'grouped_header_model_01',
                  'order_repeat_model_01', 'current_development_model_01', 'current_consumed_model_01',
                  'note_stress_model_01', 'zero_control_model_01']:
        manifest = read(run / label / 'manifest.json')
        if len(manifest['records']) > 50:
            raise ValueError('Bounded manifest required')
        for item in manifest['records']:
            request_id = item['request_id']
            attempt_id = item.get('attempt_id', request_id)
            receipt_path = run / 'api_attempts' / (str(attempt_id) + '.result.json')
            if not request_id or attempt_id in seen or not receipt_path.exists():
                continue
            seen.add(attempt_id)
            request = read(run / label / 'requests' / (request_id + '.json'))
            if fingerprint(request) != request_id:
                raise ValueError('Frozen request changed')
            receipt = read(receipt_path)
            if receipt['request_id'] != request_id or receipt['bundle_fingerprint'] != item['packet_id']:
                raise ValueError('Receipt identity differs from frozen record')
            record = {'run': label, 'request_id': request_id, 'attempt_id': attempt_id, 'status': receipt['status']}
            if receipt['status'] == 'success':
                try:
                    validate_response(receipt['response'], request)
                    record['contract_valid'] = True
                except (ValueError, TypeError, KeyError, AttributeError) as exc:
                    record.update(contract_valid=False, reason=str(exc))
                record['questions'] = {}
                for name, answer in receipt['response']['answers'].items():
                    n = len(answer['probabilities'])
                    expected = (max(answer['probabilities'].values()) - 1/n) / (1 - 1/n)
                    record['questions'][name] = {
                        'options': n, 'confidence': answer['confidence'],
                        'top_probability': max(answer['probabilities'].values()),
                        'formula_difference': abs(expected - answer['confidence']),
                        'probability_at_confidence_075': .75 * (1 - 1/n) + 1/n}
            records.append(record)
    report = {'source': 'https://docs.typesafe.ai/confidence',
              'records': records, 'responses': len(records),
              'valid': sum(r.get('contract_valid', False) for r in records),
              'invalid': sum(r.get('contract_valid') is False for r in records),
              'threshold_changed': False, 'production_clearance_enabled': False}
    destination = run / ('confidence_audit_' + fingerprint(report)[:16] + '.json')
    if not destination.exists():
        write(destination, report)
    print(json.dumps({k: v for k, v in report.items() if k != 'records'}), flush=True)


if __name__ == '__main__':
    main()
