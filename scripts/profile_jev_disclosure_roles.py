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
from scripts.jev_pilot_session import install_read_only_guard, read, sha, write


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--run-root', type=Path, required=True)
    parser.add_argument('--replay', required=True)
    parser.add_argument('--all-source-tables', action='store_true',
                        help='Inventory all tables in the same frozen filings, independently of candidate retrieval')
    parser.add_argument('--review-label', help='Include sources bound by prepared source-first inputs, including early builder refusals')
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
        if args.all_source_tables and packet.get('filing', {}).get('path'):
            filing = packet['filing']
            sources[(filing['path'], filing['sha256'])]
        for candidate in packet.get('source_candidates', []):
            filing = packet['filing']
            key = (filing['path'], filing['sha256'])
            sources[key].setdefault(candidate['table_index'], []).append(packet['flag']['row_id'])
    review_manifest_hash = None
    if args.review_label:
        if not args.all_source_tables or not args.review_label.replace('_', '').isalnum():
            raise ValueError('Review label requires all-source mode and a simple directory name')
        directory = run / args.review_label
        manifest = read(directory / 'manifest.json')
        if manifest['replay'] != args.replay or len(manifest['inventory']) != len(packets):
            raise ValueError('Prepared review inventory differs from replay')
        expected = {fingerprint(p) for p in packets.values()}
        seen = set()
        for item in manifest['inventory']:
            path = (directory / item['file']).resolve()
            if path.parent != directory or sha(path) != item['sha256']:
                raise ValueError('Prepared input changed or escaped directory')
            prepared = read(path)
            binding = prepared['snapshot']['bundle_fingerprint']
            if binding not in expected or binding in seen:
                raise ValueError('Prepared packet binding differs or repeats')
            seen.add(binding)
            source = prepared['source']
            sources[(source['path'], source['sha256'])]
        if seen != expected:
            raise ValueError('Prepared packet coverage incomplete')
        review_manifest_hash = sha(directory / 'manifest.json')
    if len(sources) > 26:
        raise ValueError('Existing source limit exceeded')
    records = []
    source_inventory = []
    all_counts = Counter()
    for index, ((path, digest), tables) in enumerate(sorted(sources.items()), 1):
        source = Path(path).resolve()
        if not source.is_relative_to(repo / 'data/raw/filings/bdc_html') or source.stat().st_size > 40 * 1024 * 1024:
            raise ValueError('Source outside bounded cache')
        if sha(source) != digest:
            raise ValueError('Source changed')
        print(f'Header role profile: source {index}/{len(sources)}, {len(tables)} candidate tables', flush=True)
        parsed = parse_source(source.read_bytes())
        selected_tables = (range(len(parsed['tables'])) if args.all_source_tables else sorted(tables))
        local_counts = Counter()
        for table_index in selected_tables:
            row_ids = tables.get(table_index, [])
            table = parsed['tables'][table_index]
            finding = table_disclosure_role(table)
            local_counts[finding['role']] += 1
            if args.all_source_tables and finding['role'] == 'unknown':
                continue
            records.append({'source_sha256': digest, 'source_relative_path': str(source.relative_to(repo)),
                'table_index': table_index, 'row_ids': sorted(set(row_ids)),
                'in_candidate_retrieval': table_index in tables,
                'parsed_report_date': table.get('report_date'),
                'parsed_period_evidence': table.get('period_evidence'),
                'finding': finding,
                'first_eight_rows': table['rows'][:8]})
        all_counts.update(local_counts)
        source_inventory.append({'source_sha256': digest,
            'source_relative_path': str(source.relative_to(repo)),
            'role_counts': dict(local_counts), 'candidate_table_count': len(tables)})
        if sha(source) != digest:
            raise ValueError('Source changed during profile')
    counts = dict(all_counts)
    report = {'replay': args.replay, 'builder_sha256': summary['builder_sha256'],
        'role_helper_sha256': sha(ROOT / 'pipeline/jev_disclosure_role.py'),
        'source_count': len(sources), 'table_count': sum(all_counts.values()),
        'review_manifest_sha256': review_manifest_hash,
        'mode': 'all_source_tables' if args.all_source_tables else 'candidate_tables',
        'source_inventory': source_inventory, 'role_counts': counts, 'tables': records,
        'api_calls': 0, 'production_changes': 0,
        'limitation': ('All-table explicit-header inventory; unknown table details omitted, counts retained. '
                      'Recognized tables can concern other periods or owners; no relevance, recall or inclusion certification.'
                      if args.all_source_tables else
                      'Retrieval-conditioned header coverage, not role accuracy, candidate recall or inclusion certification.')}
    destination = run / ('disclosure_role_profile_' + fingerprint(report)[:16] + '.json')
    if not destination.exists():
        write(destination, report)
    print(json.dumps({'artifact': destination.name, 'sources': len(sources),
                      'tables_inspected': sum(all_counts.values()), 'tables_retained': len(records), 'roles': counts}), flush=True)


if __name__ == '__main__':
    timer = threading.Timer(240, lambda: os._exit(124))
    timer.daemon = True
    timer.start()
    try:
        main()
    finally:
        timer.cancel()
