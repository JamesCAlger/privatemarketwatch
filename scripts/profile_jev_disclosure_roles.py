"""Measure explicit header-role coverage on existing frozen candidate tables."""
import argparse
from collections import Counter, defaultdict
import json
import os
from pathlib import Path
import sys
import threading

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from pipeline.jev_bundles import parse_source
from pipeline.jev_disclosure_role import table_disclosure_role
from pipeline.jev_screening import fingerprint
from scripts.compare_jev_retrieval import load_replay
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
    if len(packets) > 100 or summary['builder_sha256'] != sha(ROOT / 'pipeline/jev_bundles.py'):
        raise ValueError('Bounded current replay required')
    sources = defaultdict(dict)
    for packet in packets.values():
        for candidate in packet.get('source_candidates', []):
            filing = packet['filing']
            key = (filing['path'], filing['sha256'])
            sources[key].setdefault(candidate['table_index'], []).append(packet['flag']['row_id'])
    if len(sources) > 26:
        raise ValueError('Existing source limit exceeded')
    records = []
    for index, ((path, digest), tables) in enumerate(sorted(sources.items()), 1):
        source = Path(path).resolve()
        if not source.is_relative_to(repo / 'data/raw/filings/bdc_html') or source.stat().st_size > 40 * 1024 * 1024:
            raise ValueError('Source outside bounded cache')
        if sha(source) != digest:
            raise ValueError('Source changed')
        print(f'Header role profile: source {index}/{len(sources)}, {len(tables)} candidate tables', flush=True)
        parsed = parse_source(source.read_bytes())
        for table_index, row_ids in sorted(tables.items()):
            table = parsed['tables'][table_index]
            records.append({'source_sha256': digest, 'source_relative_path': str(source.relative_to(repo)),
                'table_index': table_index, 'row_ids': sorted(set(row_ids)),
                'finding': table_disclosure_role(table),
                'first_eight_rows': table['rows'][:8]})
        if sha(source) != digest:
            raise ValueError('Source changed during profile')
    counts = dict(Counter(r['finding']['role'] for r in records))
    report = {'replay': args.replay, 'builder_sha256': summary['builder_sha256'],
        'role_helper_sha256': sha(ROOT / 'pipeline/jev_disclosure_role.py'),
        'source_count': len(sources), 'table_count': len(records), 'role_counts': counts, 'tables': records,
        'api_calls': 0, 'production_changes': 0,
        'limitation': 'Retrieval-conditioned header coverage, not role accuracy, candidate recall or inclusion certification.'}
    destination = run / ('disclosure_role_profile_' + fingerprint(report)[:16] + '.json')
    if not destination.exists():
        write(destination, report)
    print(json.dumps({'artifact': destination.name, 'sources': len(sources), 'tables': len(records), 'roles': counts}), flush=True)


if __name__ == '__main__':
    timer = threading.Timer(240, lambda: os._exit(124))
    timer.daemon = True
    timer.start()
    try:
        main()
    finally:
        timer.cancel()
