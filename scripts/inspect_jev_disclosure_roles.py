"""Record explicit source-table roles for four existing AB Centers flags."""
import argparse
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

TARGETS = {
    'ROW-54bec5b9be81ee4d': (12, 6),
    'ROW-96818d4e9b1777d0': (12, 7),
    'ROW-1e319095e85a0c34': (15, 2),
    'ROW-24cf5e7b72e10c93': (15, 3),
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--run-root', type=Path, required=True)
    parser.add_argument('--replay', required=True)
    parser.add_argument('--exploratory-tcw', action='store_true',
                        help='Inspect the separately documented TCW primary and rollforward tables')
    args = parser.parse_args()
    repo, run = args.repo.resolve(), args.run_root.resolve()
    if repo == ROOT or not run.is_relative_to(repo / 'data/pilot/jev_screening'):
        raise ValueError('Isolated pilot required')
    install_read_only_guard(repo, run)
    if args.exploratory_tcw:
        parent_path = run / 'exploratory_context_089f24a29d1a0ec6.json'
        parent = read(parent_path)
        source = (repo / parent['source_relative_path']).resolve()
        if (parent['published_position']['row_id'] != 'ROW-ecc8c78a0d433f52' or
                not source.is_relative_to(repo / 'data/raw/filings/bdc_html') or
                source.stat().st_size > 40 * 1024 * 1024 or sha(source) != parent['source_sha256']):
            raise ValueError('Unexpected exploratory source')
        print('Inspecting primary and rollforward headers in the exploratory TCW source', flush=True)
        parsed = parse_source(source.read_bytes())
        records = [{'table_index': ti, 'finding': table_disclosure_role(parsed['tables'][ti]),
                    'header_rows': parsed['tables'][ti]['rows'][:3]} for ti in (5, 10)]
        if sha(source) != parent['source_sha256']:
            raise ValueError('Exploratory source changed')
        report = {'parent_sha256': sha(parent_path), 'source_sha256': parent['source_sha256'],
                  'builder_sha256': sha(ROOT / 'pipeline/jev_bundles.py'),
                  'role_helper_sha256': sha(ROOT / 'pipeline/jev_disclosure_role.py'),
                  'tables': records, 'api_calls': 0, 'production_changes': 0,
                  'limitation': 'Explicit header roles only; separate exploratory case, no automatic identity, ownership, row inclusion or correction.'}
        destination = run / ('exploratory_table_roles_' + fingerprint(report)[:16] + '.json')
        if not destination.exists():
            write(destination, report)
        print(json.dumps({'artifact': destination.name,
                          'roles': {r['table_index']: r['finding']['role'] for r in records}}), flush=True)
        return
    summary, packets = load_replay(run, args.replay)
    selected = {p['flag']['row_id']: p for p in packets.values() if p['flag']['row_id'] in TARGETS}
    if set(selected) != set(TARGETS):
        raise ValueError('Expected four frozen flags')
    if summary['builder_sha256'] != sha(ROOT / 'pipeline/jev_bundles.py'):
        raise ValueError('Parser must match replay')
    filing = selected['ROW-54bec5b9be81ee4d']['filing']
    source = Path(filing['path']).resolve()
    if not source.is_relative_to(repo / 'data/raw/filings/bdc_html') or source.stat().st_size > 40 * 1024 * 1024:
        raise ValueError('Source outside bounded cache')
    before = sha(source)
    if before != filing['sha256']:
        raise ValueError('Source changed')
    print('Inspecting explicit headers for four existing flags in one cached filing', flush=True)
    parsed = parse_source(source.read_bytes())
    rows = []
    for row_id, (table_index, row_index) in TARGETS.items():
        table = parsed['tables'][table_index]
        cells = table['rows'][row_index]
        text = ' '.join(c['text'] for c in cells)
        if 'AB Centers' not in text:
            raise ValueError('Source coordinate no longer identifies expected issuer')
        context_ids = {f.get('context_id') for c in cells for f in c.get('inline_facts', [])}
        if selected[row_id]['output_position']['src_context_id'] not in context_ids:
            raise ValueError('Source row does not contain frozen output context')
        rows.append({'row_id': row_id, 'table_index': table_index, 'row_index': row_index,
                     'source_cells': cells, 'table_role': table_disclosure_role(table),
                     'output_position': selected[row_id]['output_position']})
    if sha(source) != before:
        raise ValueError('Source changed during inspection')
    report = {'replay': args.replay, 'source_sha256': before,
              'builder_sha256': summary['builder_sha256'],
              'role_helper_sha256': sha(ROOT / 'pipeline/jev_disclosure_role.py'), 'rows': rows,
              'production_changes': 0, 'api_calls': 0,
              'limitation': 'Header roles do not prove economic identity, ownership, duplicate exposure or an inclusion correction.'}
    destination = run / ('disclosure_roles_' + fingerprint(report)[:16] + '.json')
    if not destination.exists():
        write(destination, report)
    print(json.dumps({'artifact': destination.name,
                     'roles': {r['row_id']: r['table_role']['role'] for r in rows}}), flush=True)


if __name__ == '__main__':
    timer = threading.Timer(150, lambda: os._exit(124))
    timer.daemon = True
    timer.start()
    try:
        main()
    finally:
        timer.cancel()
