"""Bounded, read-only intake and replay for the isolated Jev screening pilot."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
import threading

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def sha(path):
    result = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            result.update(block)
    return result.hexdigest()


def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def write(path, value):
    with path.open('x', encoding='utf-8') as stream:
        json.dump(value, stream, indent=2, ensure_ascii=True)
        stream.write('\n')


def protected_inventory(repo):
    inventory = {}
    for folder in ('data/output', 'frontend/public/data', 'pipeline', 'scripts', 'tests'):
        for base, dirs, files in os.walk(repo / folder):
            dirs[:] = [d for d in dirs if d != '__pycache__']
            # Fleet archives contain >200000 files. This is a bounded backstop,
            # not a full output-tree attestation; runtime writes are guarded too.
            if folder == 'data/output':
                dirs[:] = []
            for name in files:
                path = Path(base) / name
                stat = path.stat()
                inventory[path.relative_to(repo).as_posix()] = [stat.st_size, stat.st_mtime_ns]
                if len(inventory) > 200000:
                    raise ValueError('Protected inventory exceeds 200000 files')
    return inventory


def install_read_only_guard(repo, out):
    def check(value):
        if isinstance(value, (str, bytes, os.PathLike)):
            path = Path(os.fsdecode(value)).resolve()
            if path.is_relative_to(repo) and not any(path.is_relative_to(p) for p in (ROOT, out)):
                raise PermissionError('Pilot write outside isolated worktree/run directory: ' + str(path))

    def audit(event, args):
        if event == 'open':
            path, mode, flags = args
            if (mode and any(c in mode for c in 'wax+')) or flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND):
                check(path)
        elif event in {'os.remove', 'os.rmdir', 'os.mkdir', 'os.chmod', 'os.utime', 'os.truncate'}:
            check(args[0])
        elif event in {'os.rename', 'os.link', 'os.symlink'}:
            check(args[0])
            check(args[1])
    sys.addaudithook(audit)


def initialize(repo, out):
    if out.exists() and any(out.iterdir()):
        raise ValueError('Use a new run directory')
    out.mkdir(parents=True, exist_ok=True)
    print('Recording production file metadata; no production writes', flush=True)
    write(out / 'protected_before.json', protected_inventory(repo))
    origins = [repo / 'scratch/2026-10-03_jev_builder/final/manifest.json',
               repo / 'scratch/2026-10-03_jev_real_cases/bundles/manifest.json']
    cases = []
    packet_dir = out / 'original_packets'
    packet_dir.mkdir()
    for manifest_path in origins:
        manifest = read(manifest_path)
        for case in manifest['cases']:
            packet_path = manifest_path.parent / case['bundle_path']
            packet = read(packet_path)
            if case.get('bundle_sha256') and sha(packet_path) != case['bundle_sha256']:
                raise ValueError('Original packet hash mismatch')
            key = packet['rule']['id'] + '_' + packet['flag']['row_id']
            write(packet_dir / (key + '.json'), packet)
            cases.append({'case_id': key, 'cik': packet['flag']['cik'],
                          'period': packet['flag']['report_date'],
                          'original_status': packet['evidence_status']['status'],
                          'original_path': str(packet_path), 'sha256': sha(packet_path)})
    if len(cases) > 50:
        raise ValueError('Development intake exceeds 50 flags')
    old = read(repo / 'scratch/2026-10-03_jev_b1_benchmark/manifest.json')
    current_ciks = sorted({c['cik'] for c in cases})
    all_seen = sorted(set(current_ciks) | {c['cik'] for c in old['cases']})
    manifest = {'started_utc': datetime.now(timezone.utc).isoformat(),
                'read_only_repository': str(repo), 'implementation_worktree': str(ROOT),
                'development_cases': cases, 'current_case_ciks': current_ciks,
                'all_previously_exercised_ciks': all_seen,
                'limits': {'programme_funds': 16, 'holdout_funds': 4,
                           'holdout_flags': 40, 'session_jev_attempts': 100},
                'production_clearance_enabled': False,
                'protection_inventory_scope': 'Top-level canonical output files, frontend data, source code and tests; excludes output archive subdirectories',
                'starting_builder_sha256': sha(ROOT / 'pipeline/jev_bundles.py')}
    write(out / 'session.json', manifest)
    print(json.dumps({'development_flags': len(cases), 'current_funds': current_ciks,
                      'all_previously_exercised_funds': all_seen}), flush=True)


def replay(repo, out, label):
    from pipeline.jev_bundles import SourceCache, build_bundle
    run = out / label
    if run.exists():
        raise ValueError('Replay label already exists')
    run.mkdir()
    session = read(out / 'session.json')
    cache = SourceCache(html_cache_dir=repo / 'data/raw/filings/bdc_html')
    builder_hash = sha(ROOT / 'pipeline/jev_bundles.py')
    results = []
    for i, case in enumerate(session['development_cases'], 1):
        original = read(out / 'original_packets' / (case['case_id'] + '.json'))
        print(f"Replay {i}/{len(session['development_cases'])}: {case['case_id']}", flush=True)
        provenance = {**original['provenance'],
                      'builder_sha256': builder_hash,
                      'replay_of_packet_sha256': case['sha256']}
        packet = build_bundle(original['flag'], [original['output_position']], provenance, cache=cache)
        old_source = original['filing'].get('sha256')
        if old_source and packet['filing'].get('sha256') != old_source:
            raise ValueError('Source bytes changed since reference experiment')
        write(run / (case['case_id'] + '.json'), packet)
        results.append({'case_id': case['case_id'], 'cik': case['cik'],
                        'before': case['original_status'],
                        'after': packet['evidence_status']['status'],
                        'reasons': packet['evidence_status']['blocking_reasons'],
                        'candidate_reasons': dict(Counter(r for c in packet['source_candidates']
                                                         for r in c['blocking_reasons']))})
    if sha(ROOT / 'pipeline/jev_bundles.py') != builder_hash:
        raise ValueError('Builder changed during replay; partial run is invalid')
    summary = {'cases': results, 'status_counts': dict(Counter(r['after'] for r in results)),
               'builder_sha256': builder_hash}
    write(run / 'summary.json', summary)
    print(json.dumps(summary['status_counts']), flush=True)


def holdout_build(repo, out, label, *, development_replay=False):
    from pipeline.jev_bundles import SourceCache, build_bundle
    selected = read(out / 'holdout_selection.json')
    run = out / label
    if run.exists():
        raise ValueError('Holdout run label exists')
    prior_builds = list(out.glob('*/frozen_builder.json'))
    if prior_builds and not development_replay:
        raise ValueError('Holdout has been consumed; subsequent builds must be labelled development replays')
    run.mkdir()
    builder_hash = sha(ROOT / 'pipeline/jev_bundles.py')
    write(run / 'frozen_builder.json', {'builder_sha256': builder_hash,
                                      'selection_sha256': sha(out / 'holdout_selection.json'),
                                      'frozen_before_source_inspection': not development_replay,
                                      'arm': 'development_from_consumed_holdout' if development_replay else 'untouched_holdout'})
    provenance = {**selected['provenance'], 'builder_sha256': builder_hash}
    cache = SourceCache(html_cache_dir=repo / 'data/raw/filings/bdc_html')
    records = []
    for i, flag in enumerate(selected['flags'], 1):
        print(f"Holdout build {i}/{len(selected['flags'])}: {flag['row_id']}", flush=True)
        matched = [r for r in selected['holdings_rows'] if r['row_id'] == flag['row_id']]
        packet = build_bundle(flag, matched, provenance, cache=cache)
        case_id = flag['rule_id'] + '_' + flag['row_id']
        write(run / (case_id + '.json'), packet)
        records.append({'case_id': case_id, 'status': packet['evidence_status']['status'],
                        'reasons': packet['evidence_status']['blocking_reasons']})
    if sha(ROOT / 'pipeline/jev_bundles.py') != builder_hash:
        raise ValueError('Builder changed during holdout')
    write(run / 'summary.json', {'cases': records, 'builder_sha256': builder_hash,
                                'status_counts': dict(Counter(r['status'] for r in records))})
    print(json.dumps(dict(Counter(r['status'] for r in records))), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['init', 'replay', 'holdout', 'holdout-replay', 'audit'])
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--label', default='replay_01')
    args = parser.parse_args()
    repo, out = args.repo.resolve(), args.out.resolve()
    if not out.is_relative_to(repo / 'data/pilot/jev_screening'):
        raise ValueError('Run artifacts must be under data/pilot/jev_screening')
    if repo == ROOT:
        raise ValueError('Pilot implementation must be in a separate worktree')
    if not args.label.replace('_', '').isalnum():
        raise ValueError('Label must contain letters, digits or underscores')
    install_read_only_guard(repo, out)
    timer = threading.Timer(240, lambda: os._exit(124))
    timer.daemon = True
    timer.start()
    try:
        if args.action == 'init':
            initialize(repo, out)
        elif args.action == 'replay':
            replay(repo, out, args.label)
        elif args.action in {'holdout', 'holdout-replay'}:
            holdout_build(repo, out, args.label, development_replay=args.action == 'holdout-replay')
        else:
            before = read(out / 'protected_before.json')
            after = protected_inventory(repo)
            changed = sorted(k for k in set(before) | set(after) if before.get(k) != after.get(k))
            write(out / (args.label + '_protection_audit.json'),
                  {'changed_paths': changed, 'before_count': len(before), 'after_count': len(after)})
            print(json.dumps({'changed_count': len(changed), 'changed_paths': changed[:20]}))
    finally:
        timer.cancel()


if __name__ == '__main__':
    main()
