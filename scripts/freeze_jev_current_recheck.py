"""Freeze 12 reviewed current-builder rechecks plus four blocked natural errors."""
from collections import Counter
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.analyze_jev_screening import summarize
from scripts.compare_jev_bundle_versions import NATURAL_RUNS
from scripts.compare_jev_retrieval import load_replay
from scripts.jev_pilot_session import install_read_only_guard, read, sha, write

DEVELOPMENT = (
    'ROW-0d91b6b555659904', 'ROW-1a734ef6a228d65a', 'ROW-0a3fe5a6482a78b9',
    'ROW-0d749c119e46277b', 'ROW-3d415c265ff85a7b', 'ROW-1c2a72c58fbc2d87',
    'ROW-10740886584fa8b9', 'ROW-b63946977ed6c92e',
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--run-root', type=Path, required=True)
    args = parser.parse_args()
    repo, root = args.repo.resolve(), args.run_root.resolve()
    if repo == ROOT or not root.is_relative_to(repo / 'data/pilot/jev_screening'):
        raise ValueError('Isolated pilot required')
    install_read_only_guard(repo, root)
    summary, packets = load_replay(root, 'sibling_recall_v4_18')
    if summary['builder_sha256'] != sha(ROOT / 'pipeline/jev_bundles.py'):
        raise ValueError('Use one current frozen builder')
    by_id = {p['flag']['row_id']: p for p in packets.values()}
    if len(by_id) != len(packets):
        raise ValueError('Unexpected multiple rules per selected row')
    history, references = {}, {}
    for label in NATURAL_RUNS:
        report = summarize(root / label, root / 'api_attempts')
        source_refs = read(root / label / 'references.json')
        for row in report['observations']:
            row_id = row['flag']['row_id']
            if row['status'] == 'success':
                if row_id in history:
                    raise ValueError('Duplicate natural model history')
                history[row_id] = {'run': label, 'request_id': row['request_id']}
            if row_id in source_refs:
                reference = source_refs[row_id]
                if row_id in references and references[row_id]['expected'] != reference['expected']:
                    raise ValueError('Conflicting references')
                references[row_id] = reference
    error_ids = sorted(row_id for row_id, packet in by_id.items()
                       if packet['flag']['cik'] == '0001825265' and references.get(row_id, {}).get('expected') == 'real_error')
    if len(error_ids) != 4 or any(by_id[r]['evidence_status']['status'] != 'blocked' for r in error_ids):
        raise ValueError('Expected four blocked TCW controls')
    consumed = []
    for period in ('2025-12-31', '2026-03-31'):
        candidates = sorted(row_id for row_id, p in by_id.items()
                            if p['flag']['cik'] == '0001920145' and p['flag']['report_date'] == period
                            and p['rule']['id'] == 'C107' and p['evidence_status']['status'] == 'ready_for_model'
                            and row_id in history)
        if len(candidates) < 2:
            raise ValueError('Insufficient reviewed current-ready consumed cases')
        consumed.extend(candidates[:2])
    ready_ids = [*DEVELOPMENT, *consumed]
    if len(set(ready_ids)) != 12 or any(r not in history for r in ready_ids):
        raise ValueError('Rechecks must use 12 previously called natural flags')
    if any(by_id[r]['evidence_status']['status'] != 'ready_for_model' for r in ready_ids):
        raise ValueError('Selected recheck is no longer ready')
    if len(list((root / 'api_attempts').glob('*.started.json'))) + 12 > 100:
        raise ValueError('Insufficient reserved API budget')
    for label, ids in [('current_development_packets_20', [*DEVELOPMENT, *error_ids]),
                       ('current_consumed_packets_20', consumed)]:
        target = root / label
        target.mkdir()
        frozen_refs = {}
        for row_id in ids:
            packet, reference = by_id[row_id], references[row_id]
            if reference.get('source_sha256') and reference['source_sha256'] != packet['filing']['sha256']:
                raise ValueError('Reference source changed')
            write(target / (packet['rule']['id'] + '_' + row_id + '.json'), packet)
            frozen_refs[row_id] = {**reference, 'audit': None}
        write(root / (label + '_references.json'), frozen_refs)
    manifest = {'builder_sha256': summary['builder_sha256'], 'ready_rechecks': ready_ids,
                'blocked_controls': error_ids, 'prior_calls': {r: history[r] for r in ready_ids},
                'selection': 'Eight named source/identity cases plus two sorted Goldman cases per consumed period; four known TCW errors.',
                'natural_flags_added': 0, 'blind_holdout': False, 'production_clearance_enabled': False,
                'planned_calls': 12, 'remaining_calls_after_success': 6,
                'acceptance': 'Report every blocked/called outcome, source/label agreement and deterministic comparator. No calibration or threshold changes.'}
    write(root / 'current_recheck_manifest_20.json', manifest)
    print(json.dumps({'ready_rechecks': len(ready_ids), 'blocked_controls': len(error_ids),
                      'rules': dict(Counter(by_id[r]['rule']['id'] for r in ready_ids))}), flush=True)


if __name__ == '__main__':
    main()
