"""Inspect note extraction boundaries for three existing blocked pilot flags."""
import argparse
import json
import os
from pathlib import Path
import sys
import threading

from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from pipeline.jev_bundles import parse_source, _NOTE_DEFINITION, clean
from pipeline.jev_screening import fingerprint
from scripts.compare_jev_retrieval import load_replay
from scripts.jev_pilot_session import install_read_only_guard, sha, write

TARGETS = {'ROW-502ef9ff97600955', 'ROW-53d913fbd15e343c', 'ROW-f22f54d69382e56e'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--run-root', type=Path, required=True)
    parser.add_argument('--replay', required=True)
    parser.add_argument('--row-id', action='append', default=[], help='At most four explicit IDs from the supplied frozen replay')
    args = parser.parse_args()
    repo, run = args.repo.resolve(), args.run_root.resolve()
    if repo == ROOT or not run.is_relative_to(repo / 'data/pilot/jev_screening'):
        raise ValueError('Isolated pilot required')
    install_read_only_guard(repo, run)
    summary, packets = load_replay(run, args.replay)
    if sha(ROOT / 'pipeline/jev_bundles.py') != summary['builder_sha256']:
        raise ValueError('Diagnostic parser must match the selected replay builder')
    targets = set(args.row_id) if args.row_id else TARGETS
    if not 1 <= len(targets) <= 4 or not targets <= {p['flag']['row_id'] for p in packets.values()}:
        raise ValueError('Expected bounded explicit flags from the supplied replay')
    reports = []
    for packet in packets.values():
        if packet['flag']['row_id'] not in targets:
            continue
        source = Path(packet['filing']['path']).resolve()
        if not source.is_relative_to(repo / 'data/raw/filings/bdc_html') or source.stat().st_size > 40 * 1024 * 1024:
            raise ValueError('Source outside bounded cache')
        if sha(source) != packet['filing']['sha256']:
            raise ValueError('Source changed')
        print('Inspecting note boundaries:', packet['flag']['row_id'], flush=True)
        raw = source.read_bytes()
        parsed = parse_source(raw)
        soup = BeautifulSoup(raw, 'lxml')
        tables = [t for t in soup.find_all('table') if any(r.find(['td', 'th']) for r in t.find_all('tr'))]
        table_ids = {id(t): i for i, t in enumerate(tables)}
        missing = sorted({m for c in packet['source_candidates'] for m in c['missing_note_markers']})
        note_elements = []
        preceding_table = None
        for element in soup.find_all(['table', 'p', 'tr', 'div']):
            if id(element) in table_ids:
                preceding_table = table_ids[id(element)]
            if element.name == 'table' or element.find('table'):
                continue
            value = clean(element.get_text(' ', strip=True))
            match = _NOTE_DEFINITION.match(value)
            if not match or len(value) > 8000:
                continue
            marker = (match[1] or match[2]).lower()
            if marker not in missing:
                continue
            note_elements.append({'marker': marker, 'preceding_table': preceding_table,
                'element': element.name, 'text': value,
                'table_period': parsed['tables'][preceding_table]['report_date'] if preceding_table is not None else None})
            if len(note_elements) > 150:
                raise ValueError('Note diagnostic limit exceeded')
        reports.append({'flag': packet['flag'], 'source_sha256': sha(source),
            'missing_markers': missing,
            'candidates': [{'id': c['evidence_id'], 'missing': c['missing_note_markers'],
                'notes': [{'marker': n['marker'], 'anchor': n['anchor_table_index']} for n in c['notes']]}
                for c in packet['source_candidates']],
            'parsed_notes': [{'marker': n['marker'], 'period': n['report_date'], 'anchor': n['anchor_table_index'],
                'text': n['text']} for n in parsed['notes'] if n['marker'] in missing],
            'raw_note_elements': note_elements,
            'all_same_period_notes': [n for n in parsed['notes'] if n['report_date'] == packet['flag']['report_date']],
            'symbol_elements': list(dict.fromkeys(clean(e.get_text(' ', strip=True))
                for e in soup.find_all(['p', 'div', 'tr', 'span'])
                if '*' in missing and clean(e.get_text(' ', strip=True)).startswith('*')
                and 10 < len(clean(e.get_text(' ', strip=True))) < 1800))[:30],
            'table_scopes': [{'index': t['table_index'], 'period': t['report_date'],
                'title': t['title_context'][:500],
                'first_rows': [' '.join(c['text'] for c in row)[:650] for row in t['rows'][:2]],
                'last_rows': [' '.join(c['text'] for c in row)[:650] for row in t['rows'][-2:]]}
                for t in parsed['tables']]})
        soup.decompose()
        if sha(source) != packet['filing']['sha256']:
            raise ValueError('Source changed during note inspection')
    if len(reports) != len(targets):
        raise ValueError('Requested flag coverage incomplete')
    report = {'replay': args.replay, 'builder_sha256': summary['builder_sha256'],
        'records': reports, 'production_clearance_enabled': False, 'labels_assigned': False}
    path = run / ('missing_note_inspection_' + fingerprint(report)[:16] + '.json')
    if not path.exists():
        write(path, report)
    print(json.dumps({'artifact': path.name, 'records': [{'row_id': r['flag']['row_id'],
        'missing': r['missing_markers'], 'raw_note_elements': len(r['raw_note_elements'])} for r in reports]}), flush=True)


if __name__ == '__main__':
    timer = threading.Timer(180, lambda: os._exit(124))
    timer.daemon = True
    timer.start()
    try:
        main()
    finally:
        timer.cancel()
