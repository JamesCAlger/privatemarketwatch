"""Inspect three existing headerless source anchors without inheriting headers."""
import argparse
import json
import os
from pathlib import Path
import sys
import threading

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from pipeline.jev_bundles import SourceCache, parser_runtime
from pipeline.jev_header_continuation import inspect_header_continuation
from pipeline.jev_screening import fingerprint
from scripts.compare_jev_retrieval import load_replay
from scripts.inspect_jev_header_gaps import TARGETS
from scripts.jev_pilot_session import install_read_only_guard, sha, write


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--run-root', type=Path, required=True)
    parser.add_argument('--replay', required=True)
    args = parser.parse_args()
    repo, run = args.repo.resolve(), args.run_root.resolve()
    if repo == ROOT or not run.is_relative_to(repo / 'data/pilot/jev_screening'):
        raise ValueError('Isolated pilot required')
    install_read_only_guard(repo, run)
    summary, packets = load_replay(run, args.replay)
    runtime = parser_runtime()
    if summary.get('parser_runtime') != runtime:
        raise ValueError('Current parser runtime required')
    selected = [p for p in packets.values() if p['flag']['row_id'] in TARGETS]
    if len(selected) != 3:
        raise ValueError('Expected three already investigated flags')
    cache = SourceCache(html_cache_dir=repo / 'data/raw/filings/bdc_html')
    records = []
    for packet in selected:
        print('Header continuation probe:', packet['flag']['row_id'], flush=True)
        parsed, metadata = cache.load(packet['output_position'])
        if parsed is None or metadata['sha256'] != packet['filing']['sha256']:
            raise ValueError('Source unavailable or changed')
        indices = sorted({a['table_index'] for a in packet['retrieval']['unretrieved_source_context_anchors']})
        if len(indices) != 1:
            raise ValueError('Expected one headerless anchor table per case')
        ti = indices[0]
        before = fingerprint(parsed['tables'][ti])
        result = inspect_header_continuation(parsed, ti, cik=packet['flag']['cik'], period=packet['flag']['report_date'])
        if fingerprint(parsed['tables'][ti]) != before or sha(Path(metadata['path'])) != metadata['sha256']:
            raise ValueError('Source or parsed evidence changed')
        records.append({'rule': packet['rule']['id'], 'row_id': packet['flag']['row_id'],
                        'bundle_fingerprint': fingerprint(packet), 'source_sha256': metadata['sha256'],
                        'diagnostic': result, 'builder_status_unchanged': packet['evidence_status']['status']})
    if parser_runtime() != runtime:
        raise ValueError('Parser runtime changed')
    report = {'replay': args.replay, 'parser_runtime': runtime,
              'helper_sha256': sha(ROOT / 'pipeline/jev_header_continuation.py'),
              'records': records, 'api_calls': 0, 'production_changes': 0,
              'limitation': 'Unintegrated continuation geometry diagnostic on three consumed cases. No header inheritance, readiness promotion or independent source certification.'}
    path = run / ('header_continuation_probe_' + fingerprint(report)[:16] + '.json')
    if not path.exists():
        write(path, report)
    print(json.dumps({'artifact': path.name, 'cases': [{
        'row_id': r['row_id'], 'status': r['diagnostic']['status'],
        'blockers': r['diagnostic']['blockers'], 'fact_counts': r['diagnostic']['monetary_fact_counts']}
        for r in records]}), flush=True)


if __name__ == '__main__':
    timer = threading.Timer(150, lambda: os._exit(124))
    timer.daemon = True
    timer.start()
    try:
        main()
    finally:
        timer.cancel()
