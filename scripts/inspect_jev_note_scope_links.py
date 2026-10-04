"""Inspect explicit links and nearby headings for two consumed Ares note gaps."""
import argparse
import json
import os
from pathlib import Path
import sys
import threading

from bs4 import BeautifulSoup, NavigableString

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from pipeline.jev_bundles import clean, _NOTE_DEFINITION, parser_runtime
from pipeline.jev_screening import fingerprint
from scripts.compare_jev_retrieval import load_replay
from scripts.jev_pilot_session import install_read_only_guard, sha, write

TARGETS = [('dependency_bound_v4_55', 'ROW-f22f54d69382e56e', '12'),
           ('later_period_c104_57', 'ROW-a5dcb49c5296d21a', '13')]


def excerpt(element, direction, limit=1600):
    parts, size = [], 0
    for node in getattr(element, direction):
        if isinstance(node, NavigableString) and clean(node):
            value = clean(node)
            parts.append(value)
            size += len(value) + 1
            if size >= limit:
                break
    if direction == 'previous_elements':
        parts.reverse()
    return ' '.join(parts)[:limit + 500]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--run-root', type=Path, required=True)
    args = parser.parse_args()
    repo, run = args.repo.resolve(), args.run_root.resolve()
    if repo == ROOT or not run.is_relative_to(repo / 'data/pilot/jev_screening'):
        raise ValueError('Isolated pilot required')
    install_read_only_guard(repo, run)
    runtime = parser_runtime()
    records = []
    for replay, row_id, marker in TARGETS:
        summary, packets = load_replay(run, replay)
        if summary['parser_runtime'] != runtime:
            raise ValueError('Current parser runtime required')
        packet = next(p for p in packets.values() if p['flag']['row_id'] == row_id)
        source = Path(packet['filing']['path']).resolve()
        if (not source.is_relative_to(repo / 'data/raw/filings/bdc_html')
                or source.stat().st_size > 40 * 1024 * 1024
                or sha(source) != packet['filing']['sha256']):
            raise ValueError('Bounded frozen source required')
        print('Inspecting note links:', row_id, flush=True)
        soup = BeautifulSoup(source.read_bytes(), 'lxml')
        tables = [t for t in soup.find_all('table') if any(r.find(['td', 'th']) for r in t.find_all('tr'))]
        table_ids = {id(t): i for i, t in enumerate(tables)}
        notes, headings, preceding_table = [], [], None
        for element in soup.find_all(['table', 'div', 'p', 'tr', 'h1', 'h2', 'h3']):
            if id(element) in table_ids:
                preceding_table = table_ids[id(element)]
            if element.name == 'table' or element.find('table'):
                continue
            value = clean(element.get_text(' ', strip=True))
            if len(value) > 3000:
                continue
            if 'schedule of investments' in value.casefold() and len(value) < 250:
                headings.append({'preceding_table': preceding_table, 'text': value,
                                 'before': excerpt(element, 'previous_elements', 350),
                                 'after': excerpt(element, 'next_elements', 450)})
            match = _NOTE_DEFINITION.match(value)
            if not match or (match[1] or match[2]).lower() != marker:
                continue
            if any(_NOTE_DEFINITION.match(clean(c.get_text(' ', strip=True)))
                   for c in element.find_all(['div', 'p'])):
                continue
            descendants = [element, *element.find_all(True)]
            identifiers = sorted({str(n.get('id')) for n in descendants if n.get('id')})
            references = []
            for node in soup.find_all(True):
                for key in ('href', 'footnoterefs', 'torefs', 'fromrefs'):
                    attribute = str(node.get(key, ''))
                    if identifiers and any(token.lstrip('#') in identifiers for token in attribute.split()):
                        references.append({'tag': node.name, 'attribute': key, 'value': attribute,
                                           'attrs': dict(node.attrs), 'text': clean(node.get_text(' ', strip=True))[:300]})
                        if len(references) > 50:
                            raise ValueError('Reference cap exceeded')
            notes.append({'preceding_table': preceding_table, 'text': value,
                          'attrs': [dict(n.attrs) for n in descendants[:12]], 'identifiers': identifiers,
                          'references': references, 'before': excerpt(element, 'previous_elements'),
                          'after': excerpt(element, 'next_elements')})
            if len(notes) > 10:
                raise ValueError('Note cap exceeded')
        if len(headings) > 250:
            raise ValueError('Heading cap exceeded')
        records.append({'row_id': row_id, 'replay': replay, 'marker': marker,
                        'source_sha256': packet['filing']['sha256'], 'notes': notes,
                        'headings': headings, 'table_count': len(tables)})
        soup.decompose()
        if sha(source) != packet['filing']['sha256']:
            raise ValueError('Source changed during inspection')
    if parser_runtime() != runtime:
        raise ValueError('Runtime changed')
    report = {'parser_runtime': runtime, 'script_sha256': sha(Path(__file__)), 'records': records,
              'scope_applied': False, 'production_changes': 0, 'api_calls': 0}
    path = run / ('note_scope_links_' + fingerprint(report)[:16] + '.json')
    if not path.exists():
        write(path, report)
    print(json.dumps({'artifact': path.name, 'records': [
        {'row_id': r['row_id'], 'notes': len(r['notes']), 'headings': len(r['headings']),
         'reference_counts': [len(n['references']) for n in r['notes']]} for r in records]}), flush=True)


if __name__ == '__main__':
    timer = threading.Timer(150, lambda: os._exit(124))
    timer.daemon = True
    timer.start()
    try:
        main()
    finally:
        timer.cancel()
