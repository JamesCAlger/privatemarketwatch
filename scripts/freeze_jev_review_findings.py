"""Seal completed source-first findings in the pilot directory, without clearance."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from pipeline.jev_review_findings import freeze_findings
from scripts.jev_pilot_session import install_read_only_guard, read, sha, write


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--run-root', type=Path, required=True)
    parser.add_argument('--prepared-label', required=True)
    parser.add_argument('--review-id', required=True)
    parser.add_argument('--completed', type=Path, required=True,
                        help='Completed JSON copy inside the pilot run directory')
    args = parser.parse_args()
    repo, run = args.repo.resolve(), args.run_root.resolve()
    if repo == ROOT or not run.is_relative_to(repo / 'data/pilot/jev_screening'):
        raise ValueError('Isolated pilot required')
    install_read_only_guard(repo, run)
    if not args.prepared_label.replace('_', '').isalnum():
        raise ValueError('Invalid prepared input label')
    directory = run / args.prepared_label
    manifest_path = directory / 'manifest.json'
    manifest = read(manifest_path)
    if len(manifest['inventory']) > 100 or manifest.get('production_clearance_enabled') is not False:
        raise ValueError('Bounded shadow handoff required')
    records = [r for r in manifest['inventory'] if r['review_id'] == args.review_id]
    if len(records) != 1:
        raise ValueError('Review ID must occur exactly once')
    prepared_path = (directory / records[0]['file']).resolve()
    if prepared_path.parent != directory or sha(prepared_path) != records[0]['sha256']:
        raise ValueError('Prepared input changed or escaped directory')
    completed_path = args.completed.resolve()
    if (not completed_path.is_relative_to(run) or completed_path == prepared_path
            or completed_path.stat().st_size > 1024 * 1024):
        raise ValueError('Use a separate bounded completed copy inside the run directory')
    prepared, completed = read(prepared_path), read(completed_path)
    source = Path(prepared['source']['path']).resolve()
    if (not source.is_relative_to(repo / 'data/raw') or source.stat().st_size > 40 * 1024 * 1024
            or sha(source) != prepared['source']['sha256']):
        raise ValueError('Original source changed or outside cache')
    if sha(repo / 'data/output/private_markets_holdings.csv') != prepared['snapshot']['holdings_sha256']:
        raise ValueError('Holdings snapshot changed; prepare a new handoff')
    findings = freeze_findings(prepared, completed)
    record = {'prepared_manifest_sha256': sha(manifest_path),
              'completed_file_sha256': sha(completed_path),
              'validator_sha256': sha(ROOT / 'pipeline/jev_review_findings.py'),
              'findings': findings}
    target = run / 'source_first_findings'
    target.mkdir(exist_ok=True)
    destination = target / (findings['findings_id'] + '.json')
    write(destination, record)
    print(json.dumps({'artifact': str(destination.relative_to(run)),
        'disposition': findings['findings']['disposition'],
        'bundle_audit_completed': False, 'production_clearance_enabled': False}), flush=True)


if __name__ == '__main__':
    main()
