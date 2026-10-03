"""Rebuild a bounded frozen development selection without rescanning holdings."""
from __future__ import annotations
import argparse
from collections import Counter
import json
import os
from pathlib import Path
import sys
import threading

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from pipeline.jev_bundles import SourceCache, build_bundle
from scripts.jev_pilot_session import install_read_only_guard, read, sha, write


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--run-root', type=Path, required=True)
    parser.add_argument('--selection', type=Path, required=True)
    parser.add_argument('--prior-bundles', type=Path, required=True)
    parser.add_argument('--label', required=True)
    args = parser.parse_args()
    repo, run = args.repo.resolve(), args.run_root.resolve()
    if repo == ROOT or not run.is_relative_to(repo / 'data/pilot/jev_screening'):
        raise ValueError('Isolated pilot required')
    if not args.label.replace('_', '').isalnum():
        raise ValueError('Invalid label')
    install_read_only_guard(repo, run)
    selection = read(args.selection)
    if not 1 <= len(selection['flags']) <= 40 or len(selection['holdings_rows']) > 80:
        raise ValueError('Selection exceeds replay bounds')
    reservation = read(run / 'holdout_reservation_v2.json')
    allowed = set(reservation['all_previously_exercised_ciks']) | {r['cik'] for r in reservation['holdout_funds']}
    if not {r['cik'] for r in selection['flags']} <= allowed:
        raise ValueError('New fund outside session cap')
    filenames = [flag['rule_id'] + '_' + flag['row_id'] + '.json' for flag in selection['flags']]
    if len(set(filenames)) != len(filenames):
        raise ValueError('Duplicate selected flag')
    missing = [name for name in filenames if not (args.prior_bundles / name).is_file()]
    if missing:
        raise ValueError('Selection has no prior packet: ' + ', '.join(missing))
    target = run / args.label
    target.mkdir()
    builder_hash = sha(ROOT / 'pipeline/jev_bundles.py')
    provenance = {**selection['provenance'], 'builder_sha256': builder_hash}
    cache = SourceCache(html_cache_dir=repo / 'data/raw/filings/bdc_html')
    cases = []
    for flag in selection['flags']:
        filename = flag['rule_id'] + '_' + flag['row_id'] + '.json'
        old = read(args.prior_bundles / filename)
        packet = build_bundle(flag, [r for r in selection['holdings_rows'] if r['row_id'] == flag['row_id']], provenance, cache=cache)
        if old.get('filing', {}).get('sha256') and old['filing']['sha256'] != packet['filing'].get('sha256'):
            raise ValueError('Source changed')
        write(target / filename, packet)
        cases.append({'row_id': flag['row_id'], **packet['evidence_status']})
        print(flag['row_id'], packet['evidence_status']['status'], flush=True)
    if sha(ROOT / 'pipeline/jev_bundles.py') != builder_hash:
        raise ValueError('Builder changed during replay')
    report = {'arm': 'development_replay', 'selection_sha256': sha(args.selection),
              'builder_sha256': builder_hash, 'cases': cases,
              'status_counts': dict(Counter(r['status'] for r in cases))}
    write(target / 'summary.json', report)
    print(json.dumps(report['status_counts']), flush=True)


if __name__ == '__main__':
    timer = threading.Timer(240, lambda: os._exit(124))
    timer.daemon = True
    timer.start()
    try:
        main()
    finally:
        timer.cancel()
