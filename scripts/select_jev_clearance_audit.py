"""Freeze every confidence-only natural candidate for independent source review."""
import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.analyze_jev_screening import summarize
from scripts.jev_pilot_session import install_read_only_guard, read, write


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--run-root', type=Path, required=True)
    args = parser.parse_args()
    repo, run = args.repo.resolve(), args.run_root.resolve()
    if repo == ROOT or not run.is_relative_to(repo / 'data/pilot/jev_screening'):
        raise ValueError('Isolated pilot required')
    install_read_only_guard(repo, run)
    target = run / 'clearance_audit_packets_01'
    target.mkdir()
    selected = []
    for label in ['development_model_01', 'consumed_holdout_model_01', 'weak_probe_model_01', 'newly_ready_model_01']:
        report = summarize(run / label, run / 'api_attempts')
        records = {r['request_id']: r for r in read(run / label / 'manifest.json')['records'] if r['request_id']}
        for observation in report['observations']:
            if not observation.get('confidence_eligible'):
                continue
            record = records[observation['request_id']]
            packet = read(run / label / 'packets' / (record['packet_id'] + '.json'))
            filename = packet['rule']['id'] + '_' + packet['flag']['row_id'] + '.json'
            write(target / filename, packet)
            selected.append({'run': label, 'packet_filename': filename, 'packet_fingerprint': record['packet_id'],
                             'request_id': record['request_id'], 'model_source': observation['source'],
                             'decision_confidence': observation['decision_confidence'],
                             'source_confidence': observation['source_confidence']})
    assert len(selected) == 14
    write(run / 'clearance_audit_selection_01.json', {'selection': 'All 14 confidence-only natural candidates; none certified cleared',
          'cases': selected, 'audit_reference_labels_are_development': True, 'production_clearance_enabled': False})
    print('Selected 14 frozen candidates for source review')


if __name__ == '__main__':
    main()
