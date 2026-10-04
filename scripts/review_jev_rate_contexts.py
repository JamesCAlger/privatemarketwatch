"""Inspect raw fact inventories for three existing blocked positions; no rate inference."""
import argparse
from collections import defaultdict
import json
import os
from pathlib import Path
import sys
import threading
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from pipeline.jev_screening import fingerprint
from scripts.jev_pilot_session import install_read_only_guard, read, sha, write
from scripts.review_jev_sources import exact_context_facts, text


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--run-root', type=Path, required=True)
    args = parser.parse_args()
    repo, run = args.repo.resolve(), args.run_root.resolve()
    if repo == ROOT or not run.is_relative_to(repo / 'data/pilot/jev_screening'):
        raise ValueError('Isolated pilot required')
    install_read_only_guard(repo, run)
    parent_path = run / 'missing_identity_source_review_45.json'
    parent = read(parent_path)
    if len(parent) != 3 or {r['output_position']['cik'] for r in parent} != {'0001954360'}:
        raise ValueError('Only the three existing source-reviewed cases are allowed')
    groups = defaultdict(list)
    for item in parent:
        groups[item['source_path']].append(item)
    records = []
    for filename, cases in groups.items():
        source = Path(filename).resolve()
        if not source.is_relative_to(repo / 'data/raw') or source.stat().st_size > 40 * 1024 * 1024:
            raise ValueError('Source outside bounded cache')
        source_hash = sha(source)
        if any(c['source_sha256'] != source_hash for c in cases):
            raise ValueError('Source changed')
        print('Inspecting exact-context raw facts:', cases[0]['output_position']['report_date'], flush=True)
        soup = BeautifulSoup(source.read_bytes(), 'lxml')
        for case in cases:
            context_id = case['output_position']['src_context_id']
            context, facts = exact_context_facts(soup, context_id)
            if context is None or len(facts) > 100:
                raise ValueError('Missing context or excessive facts')
            inventory = [{'concept': f.get('name'), 'text': text(f), 'format': f.get('format'),
                'scale': f.get('scale'), 'sign': f.get('sign'), 'unit_ref': f.get('unitref'),
                'unit_xml': str(soup.find(id=f.get('unitref')))[:2000] if f.get('unitref') else None,
                'in_table': f.find_parent('table') is not None,
                'in_hidden': f.find_parent('ix:hidden') is not None} for f in facts]
            records.append({'row_id': case['row_id'], 'period': case['output_position']['report_date'],
                'context_id': context_id, 'source_sha256': source_hash, 'facts': inventory,
                'position': case['source_positions'][0], 'published_position': case['output_position'],
                'rate_absence_certified': False, 'whole_position_unfunded_certified': False})
        soup.decompose()
    report = {'records': records, 'parent_review_sha256': sha(parent_path), 'api_calls': 0,
        'production_changes': 0,
        'limitations': ['Exact-context inventory only, not a full search of rate or commitment disclosures.',
            'Missing tags and displayed dashes are not automatically numeric zero or complete evidence of absence.',
            'An unfunded-portion note does not establish that the entire position is undrawn.',
            'No X02 labels or independent source audits are assigned.']}
    destination = run / ('rate_context_inventory_' + fingerprint(report)[:16] + '.json')
    write(destination, report)
    print(json.dumps({'artifact': destination.name, 'records': len(records),
                      'facts_per_record': [len(r['facts']) for r in records]}), flush=True)


if __name__ == '__main__':
    timer = threading.Timer(120, lambda: os._exit(124))
    timer.daemon = True
    timer.start()
    try:
        main()
    finally:
        timer.cancel()
