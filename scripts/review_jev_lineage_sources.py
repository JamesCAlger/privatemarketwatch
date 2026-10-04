"""Preserve raw donor FV facts for six B1-only cost-lineage source reviews."""
import argparse
import json
import os
from pathlib import Path
import re
import sys
import threading

from bs4 import BeautifulSoup, NavigableString

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.jev_pilot_session import install_read_only_guard, read, sha, write
from scripts.review_jev_sources import exact_context_facts, review_source_path, text


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--run-root', type=Path, required=True)
    parser.add_argument('--lineage', required=True)
    parser.add_argument('--label', required=True)
    args = parser.parse_args()
    repo, run = args.repo.resolve(), args.run_root.resolve()
    if repo == ROOT or not run.is_relative_to(repo / 'data/pilot/jev_screening'):
        raise ValueError('Isolated pilot required')
    if any(not v.replace('_', '').isalnum() for v in (args.lineage, args.label)):
        raise ValueError('Invalid label')
    install_read_only_guard(repo, run)
    lineage_path = run / (args.lineage + '.json')
    lineage = read(lineage_path)
    if not 1 <= len(lineage['records']) <= 6:
        raise ValueError('At most six donors')
    reports = []
    for record in lineage['records']:
        donor = record['donor']
        path = review_source_path(repo, {'output_position': donor})
        if not path.is_file() or path.stat().st_size > 40 * 1024 * 1024:
            raise ValueError('Cached source unavailable or too large')
        print('Reading donor source:', donor['row_id'], donor['report_date'], flush=True)
        soup = BeautifulSoup(path.read_bytes(), 'lxml')
        tables = [t for t in soup.find_all('table') if any(tr.find(['td', 'th']) for tr in t.find_all('tr'))]
        if len(tables) > 500:
            raise ValueError('Source table limit')
        table_ids = {id(table): i for i, table in enumerate(tables)}
        context, facts = exact_context_facts(soup, donor['src_context_id'])
        fv_facts = [f for f in facts if (f.get('name') or '').split(':')[-1] == 'InvestmentOwnedAtFairValue']
        if len(fv_facts) > 10:
            raise ValueError('Ambiguous context exceeds review bound')
        positions = []
        for fact in fv_facts:
            table, row = fact.find_parent('table'), fact.find_parent('tr')
            if table is None or row is None:
                continue
            rows = [r for r in table.find_all('tr') if r.find(['td', 'th'])]
            ri = next(i for i, r in enumerate(rows) if r is row)
            prefix, size = [], 0
            for node in table.previous_elements:
                if isinstance(node, NavigableString) and str(node).strip():
                    value = ' '.join(str(node).split())
                    prefix.append(value)
                    size += len(value)
                    if size > 2200:
                        break
            positions.append({'table_index': table_ids[id(table)], 'row_index': ri,
                              'header_rows': [text(r) for r in rows[:3]],
                              'preceding_text': ' '.join(reversed(prefix)),
                              'visible_row': text(row),
                              'neighbour_rows': [text(r) for r in rows[max(0, ri-1):ri+2]],
                              'fact': {'concept': fact.get('name'), 'text': text(fact),
                                       'scale': fact.get('scale', '0'), 'sign': fact.get('sign'),
                                       'format': fact.get('format'),
                                       'unit': text(soup.find(id=fact.get('unitref')))}})
        reports.append({'row_id': record['row_id'], 'donor_row_id': donor['row_id'],
                        'source_path': str(path), 'source_sha256': sha(path),
                        'context_xml': str(context) if context else None,
                        'source_positions': positions, 'source_truth_verified': False,
                        'position_chain_verified': False, 'route': 'B1'})
        soup.decompose()
    write(run / (args.label + '.json'), {'lineage_sha256': sha(lineage_path), 'records': reports,
           'limitation': 'Raw tagged donor facts only. Context equality and pipeline lineage are not independent tranche/chain proof.'})
    print(json.dumps({'donor_reviews': len(reports), 'sources_with_fv_rows': sum(bool(r['source_positions']) for r in reports)}), flush=True)


if __name__ == '__main__':
    timer = threading.Timer(90, lambda: os._exit(124))
    timer.daemon = True
    timer.start()
    try:
        main()
    finally:
        timer.cancel()
