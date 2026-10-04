"""Verify synthetic note controls preserve source identity and numeric evidence."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from pipeline.jev_screening import fingerprint
from scripts.jev_pilot_session import install_read_only_guard, read, sha, write


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--run-root', type=Path, required=True)
    args = parser.parse_args()
    repo, run = args.repo.resolve(), args.run_root.resolve()
    if repo == ROOT or not run.is_relative_to(repo / 'data/pilot/jev_screening'):
        raise ValueError('Isolated pilot required')
    install_read_only_guard(repo, run)
    design = read(run / 'note_stress_design_29.json')
    if len(design['cases']) != 4:
        raise ValueError('Expected four fixed controls')
    records = []
    for item in design['cases']:
        packet = read(run / 'note_stress_packets_29' / ('C107_' + item['row_id'] + '.json'))
        original = read(run / 'context_required_v4_27' / ('C107_' + item['parent_row_id'] + '.json'))
        fields = ('evidence_id', 'raw_cells', 'headers', 'source_values', 'identity_evidence', 'period_evidence')
        project = lambda p: [{key: candidate[key] for key in fields} for candidate in p['source_candidates']]
        if project(packet) != project(original):
            raise ValueError('Source identity or amounts changed beyond note stress')
        if sha(Path(packet['filing']['path'])) != packet['filing']['sha256']:
            raise ValueError('Source receipt changed')
        records.append({'row_id': item['row_id'], 'packet_fingerprint': fingerprint(packet),
                        'source_identity_and_values_preserved': True, 'kind': item['kind']})
    write(run / 'note_stress_verified_29.json', {'records': records, 'api_calls': 0,
          'limitation': 'Mutation integrity only; not independent clearance or robustness certification.'})
    print(json.dumps({'verified_controls': len(records)}), flush=True)


if __name__ == '__main__':
    main()
