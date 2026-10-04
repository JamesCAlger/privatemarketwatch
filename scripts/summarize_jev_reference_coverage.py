"""Separate later source-review coverage from frozen model scoring labels."""
import argparse
from collections import Counter
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from pipeline.jev_screening import fingerprint
from scripts.analyze_jev_screening import summarize
from scripts.compare_jev_bundle_versions import NATURAL_RUNS
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
    observations = {}
    for label in NATURAL_RUNS:
        for row in summarize(run / label, run / 'api_attempts')['observations']:
            key = (row['flag']['rule_id'], row['flag']['row_id'])
            if key in observations and observations[key]['status'] == 'success':
                raise ValueError('Duplicate successful observation')
            observations[key] = row
    path = run / 'additional_C107_references_01.json'
    supplemental = read(path)
    if len(supplemental) != 10 or any(('C107', row_id) not in observations for row_id in supplemental):
        raise ValueError('Supplemental selection differs from pilot')
    rows = []
    for (rule, row_id), row in observations.items():
        extra = supplemental.get(row_id) if rule == 'C107' else None
        if extra and row['expected'] is not None and row['expected'] != extra['expected']:
            raise ValueError('Do not overwrite an existing frozen reference')
        rows.append({'rule': rule, 'row_id': row_id, 'model_status': row['status'],
                     'frozen_scoring_reference': row['expected'],
                     'latest_review_disposition': extra['expected'] if extra else row['expected'],
                     'supplemental_review': bool(extra)})
    report = {'flags': len(rows), 'supplemental_reference_sha256': sha(path),
              'review_dispositions': dict(Counter(r['latest_review_disposition'] or 'unreviewed' for r in rows)),
              'by_rule': {rule: dict(Counter(r['latest_review_disposition'] or 'unreviewed'
                           for r in rows if r['rule'] == rule)) for rule in sorted({r['rule'] for r in rows})},
              'observations': rows, 'audited_clearances': 0, 'frozen_model_scores_changed': False,
              'limitation': 'Source-review disposition is not complete independent bundle audit. Unscorable includes unsupported proxy-cost contracts.'}
    destination = run / ('reference_coverage_' + fingerprint(report)[:16] + '.json')
    if not destination.exists():
        write(destination, report)
    print(json.dumps({k: v for k, v in report.items() if k != 'observations'}), flush=True)


if __name__ == '__main__':
    main()
