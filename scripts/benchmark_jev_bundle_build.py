"""Measure empty and reused parser-cache builds on four existing pilot cases."""
import argparse
import gc
import json
import os
from pathlib import Path
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from pipeline.jev_bundles import SourceCache, build_bundle
from pipeline.jev_screening import fingerprint
from scripts.compare_jev_retrieval import load_replay
from scripts.jev_pilot_session import install_read_only_guard, sha, write

CASES = ('ROW-0a3fe5a6482a78b9', 'ROW-1a734ef6a228d65a',
         'ROW-1c2a72c58fbc2d87', 'ROW-0d749c119e46277b')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--run-root', type=Path, required=True)
    parser.add_argument('--replay', required=True)
    parser.add_argument('--label', required=True)
    args = parser.parse_args()
    repo, run = args.repo.resolve(), args.run_root.resolve()
    if repo == ROOT or not run.is_relative_to(repo / 'data/pilot/jev_screening'):
        raise ValueError('Isolated pilot required')
    if not args.label.isdigit():
        raise ValueError('Numeric label required')
    install_read_only_guard(repo, run)
    summary, packets = load_replay(run, args.replay)
    builder_hash = sha(ROOT / 'pipeline/jev_bundles.py')
    if summary['builder_sha256'] != builder_hash:
        raise ValueError('Benchmark must use current frozen builder')
    destination = run / ('bundle_build_timing_' + args.label + '.json')
    if destination.exists():
        raise ValueError('Timing label exists')
    records = []
    for row_id in CASES:
        selected = [p for (_, rid), p in packets.items() if rid == row_id]
        if len(selected) != 1:
            raise ValueError('Expected one existing case')
        parent = selected[0]
        cache = SourceCache(html_cache_dir=repo / 'data/raw/filings/bdc_html')
        timings, digests = [], []
        for state in ('empty_parser_cache', 'reused_parser_cache'):
            print('Bundle timing:', row_id, state, flush=True)
            gc.collect()
            wall_start, cpu_start = time.perf_counter(), time.process_time()
            packet = build_bundle(parent['flag'], [parent['output_position']], parent['provenance'], cache=cache)
            wall, cpu = time.perf_counter() - wall_start, time.process_time() - cpu_start
            if packet['filing'].get('sha256') != parent['filing']['sha256']:
                raise ValueError('Cached source changed')
            digests.append(fingerprint(packet))
            timings.append({'cache_state': state, 'wall_seconds': round(wall, 6),
                            'process_cpu_seconds': round(cpu, 6), 'status': packet['evidence_status']['status']})
        if len(set(digests)) != 1 or fingerprint(parent) != digests[0]:
            raise ValueError('Timed builds do not reproduce frozen packet')
        records.append({'row_id': row_id, 'cik': parent['flag']['cik'],
                        'source_sha256': parent['filing']['sha256'], 'bundle_fingerprint': digests[0],
                        'candidate_count': len(packet['source_candidates']), 'timings': timings})
        del cache, packet
    if sha(ROOT / 'pipeline/jev_bundles.py') != builder_hash:
        raise ValueError('Builder changed during timing')
    report = {'builder_sha256': builder_hash, 'replay': args.replay, 'records': records,
              'exact_reproduction': True, 'api_calls': 0, 'production_clearance_enabled': False,
              'limitations': ['One pair per existing case, not a population latency estimate.',
                  'Empty parser cache does not mean cold operating-system file cache.',
                  'Includes source read/hash/parse/retrieval; excludes input selection, CSV join, request preparation, model latency, B1 review and maintenance.',
                  'Timing uses this local process and machine; no concurrency throughput claim.']}
    write(destination, report)
    print(json.dumps(report), flush=True)


if __name__ == '__main__':
    timer = threading.Timer(180, lambda: os._exit(124))
    timer.daemon = True
    timer.start()
    try:
        main()
    finally:
        timer.cancel()
