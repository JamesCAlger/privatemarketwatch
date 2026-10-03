"""Measure incomplete-alternative cases without relaxing the screening policy."""
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
    parser.add_argument('--bundles', type=Path, required=True)
    parser.add_argument('--references', type=Path, required=True)
    args = parser.parse_args()
    repo, run = args.repo.resolve(), args.run_root.resolve()
    if repo == ROOT or not run.is_relative_to(repo / 'data/pilot/jev_screening'):
        raise ValueError('Isolated pilot required')
    install_read_only_guard(repo, run)
    references = read(args.references)
    if not 1 <= len(references) <= 20:
        raise ValueError('Bounded source-reviewed selection required')
    rows = []
    for row_id, reference in references.items():
        paths = list(args.bundles.glob('*_' + row_id + '.json'))
        if len(paths) != 1:
            raise ValueError('Expected one frozen packet per reviewed flag')
        packet = read(paths[0])
        if packet['filing']['sha256'] != reference['source_sha256']:
            raise ValueError('Reference source changed')
        selected = [c for c in packet['source_candidates'] if c['evidence_id'] == reference['expected_source']]
        complete = len(selected) == 1 and not selected[0]['blocking_reasons']
        rows.append({'row_id': row_id, 'packet_sha256': sha(paths[0]),
                     'expected_source': reference['expected_source'],
                     'strict_status': packet['evidence_status']['status'],
                     'reviewed_candidate_complete': complete,
                     'candidate_reasons': {c['evidence_id']: c['blocking_reasons'] for c in packet['source_candidates']},
                     'counterfactual_only': True, 'production_clearance_allowed': False})
    report = {'records': rows, 'reviewed_flags': len(rows),
              'blocked_with_complete_reviewed_candidate': sum(
                  r['strict_status'] == 'blocked' and r['reviewed_candidate_complete'] for r in rows),
              'references_sha256': sha(args.references),
              'limitation': 'Uses manually reviewed source identities. This is not an automatic resolver, policy change, accuracy estimate or clearance.'}
    destination = run / ('candidate_gap_analysis_' + fingerprint(report)[:16] + '.json')
    if not destination.exists():
        write(destination, report)
    print(json.dumps({k: v for k, v in report.items() if k != 'records'}), flush=True)


if __name__ == '__main__':
    main()
