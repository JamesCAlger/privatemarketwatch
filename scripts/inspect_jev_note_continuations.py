"""Inspect unresolved note-table associations in two existing AB Centers flags."""
import argparse
import json
import os
from pathlib import Path
import sys
import threading

from bs4 import BeautifulSoup, NavigableString

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from pipeline.jev_bundles import clean, parse_source, _requires_note_continuation
from pipeline.jev_screening import fingerprint
from scripts.compare_jev_retrieval import load_replay
from scripts.jev_pilot_session import install_read_only_guard, sha, write

TARGETS = {'ROW-54bec5b9be81ee4d', 'ROW-96818d4e9b1777d0'}


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
    selected = [p for p in packets.values() if p['flag']['row_id'] in TARGETS]
    if len(selected) != 2 or len({p['filing']['sha256'] for p in selected}) != 1:
        raise ValueError('Expected two existing flags in one filing')
    if summary['builder_sha256'] != sha(ROOT / 'pipeline/jev_bundles.py'):
        raise ValueError('Current parser must match replay')
    source = Path(selected[0]['filing']['path']).resolve()
    if not source.is_relative_to(repo / 'data/raw/filings/bdc_html') or source.stat().st_size > 40 * 1024 * 1024:
        raise ValueError('Source outside bounded cache')
    if sha(source) != selected[0]['filing']['sha256']:
        raise ValueError('Source changed')
    print('Inspecting two note-continuation flags in one cached filing', flush=True)
    raw = source.read_bytes()
    parsed = parse_source(raw)
    soup = BeautifulSoup(raw, 'lxml')
    tables = [t for t in soup.find_all('table') if any(r.find(['td', 'th']) for r in t.find_all('tr'))]
    table_ids = {id(t): i for i, t in enumerate(tables)}
    wanted = {n['text'] for p in selected for c in p['source_candidates'] for n in c['notes']
              if _requires_note_continuation(n['text']) and not n.get('continuation_table')}
    records = []
    for element in soup.find_all(['p', 'div', 'tr']):
        value = clean(element.get_text(' ', strip=True))
        if value not in wanted:
            continue
        siblings = []
        for sibling in element.next_siblings:
            description = clean(str(sibling)) if isinstance(sibling, NavigableString) else clean(sibling.get_text(' ', strip=True))
            if not description:
                continue
            siblings.append({'element': getattr(sibling, 'name', None), 'text_excerpt': description[:1800],
                             'characters': len(description), 'excerpt_truncated': len(description) > 1800})
            if len(siblings) == 12:
                break
        following = []
        for table in element.find_all_next('table', limit=5):
            index = table_ids.get(id(table))
            if index is None:
                continue
            info = parsed['tables'][index]
            following.append({'table_index': index, 'rows': len(info['rows']),
                'text_characters': len(clean(table.get_text(' ', strip=True))),
                'unsupported_layout': info['unsupported_layout'], 'period': info['report_date'],
                'first_rows': [' '.join(c['text'] for c in r)[:1000] for r in info['rows'][:3]]})
        records.append({'note': value, 'element': element.name, 'parent_element': element.parent.name,
                        'next_siblings': siblings, 'following_tables': following})
        if len(records) > 10:
            raise ValueError('Diagnostic match limit exceeded')
    if not records:
        raise ValueError('No matching source note')
    report = {'replay': args.replay, 'row_ids': sorted(TARGETS), 'source_sha256': sha(source),
        'builder_sha256': summary['builder_sha256'], 'records': records,
        'production_clearance_enabled': False,
        'limitation': 'Bounded navigation excerpts, not a complete evidence packet or certified table association.'}
    destination = run / ('note_continuation_inspection_' + fingerprint(report)[:16] + '.json')
    if not destination.exists():
        write(destination, report)
    print(json.dumps({'artifact': destination.name, 'matching_elements': len(records)}), flush=True)


if __name__ == '__main__':
    timer = threading.Timer(180, lambda: os._exit(124))
    timer.daemon = True
    timer.start()
    try:
        main()
    finally:
        timer.cancel()
