"""Inspect headerless declared source anchors for three frozen pilot cases."""
import argparse
import json
import os
from pathlib import Path
import sys
import threading

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from pipeline.jev_bundles import SourceCache
from pipeline.jev_screening import fingerprint
from scripts.compare_jev_retrieval import load_replay
from scripts.jev_pilot_session import install_read_only_guard, sha, write

TARGETS = {'ROW-1b664508f7920acb', 'ROW-2ea18714a921a74f', 'ROW-d8774de8eaa174f2'}


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
    if summary['builder_sha256'] != sha(ROOT / 'pipeline/jev_bundles.py'):
        raise ValueError('Current parser must match replay')
    cache = SourceCache(html_cache_dir=repo / 'data/raw/filings/bdc_html')
    records = []
    for packet in packets.values():
        if packet['flag']['row_id'] not in TARGETS:
            continue
        print('Inspecting header gap:', packet['flag']['row_id'], flush=True)
        parsed, metadata = cache.load(packet['output_position'])
        if parsed is None or metadata['sha256'] != packet['filing']['sha256']:
            raise ValueError('Source changed or unavailable')
        anchors = packet['retrieval']['unretrieved_source_context_anchors']
        if not anchors or len(anchors) > 4:
            raise ValueError('Unexpected anchor count')
        tables = []
        indices = sorted({i for a in anchors for i in range(max(0, a['table_index']-2), a['table_index']+2)
                          if i < len(parsed['tables'])})
        for index in indices:
            table = parsed['tables'][index]
            anchor_indices = [a['row_index'] for a in anchors if a['table_index'] == index]
            tables.append({'table_index': index, 'report_date': table['report_date'],
                'period_evidence': table['period_evidence'], 'title_context': table['title_context'],
                'headers': table['headers'], 'unsupported_layout': table['unsupported_layout'],
                'row_count': len(table['rows']), 'first_rows': table['rows'][:3],
                'last_rows': table['rows'][-2:],
                'anchor_rows': [{'row_index': ri, 'cells': table['rows'][ri]} for ri in anchor_indices]})
        records.append({'flag': packet['flag'], 'source_sha256': metadata['sha256'],
            'declared_context': packet['output_position']['src_context_id'],
            'context_definition': parsed['contexts'].get(packet['output_position']['src_context_id']),
            'tables': tables})
    if len(records) != 3:
        raise ValueError('Expected three existing flags')
    report = {'replay': args.replay, 'builder_sha256': summary['builder_sha256'], 'records': records,
              'labels_assigned': False, 'production_clearance_enabled': False}
    destination = run / ('header_gap_inspection_' + fingerprint(report)[:16] + '.json')
    if not destination.exists():
        write(destination, report)
    print(json.dumps({'artifact': destination.name, 'records': len(records)}), flush=True)


if __name__ == '__main__':
    timer = threading.Timer(180, lambda: os._exit(124))
    timer.daemon = True
    timer.start()
    try:
        main()
    finally:
        timer.cancel()
