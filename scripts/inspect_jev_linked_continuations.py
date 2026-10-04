"""Inspect explicit continued notes on three currently ready development cases."""
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
from pipeline.jev_bundles import clean, parser_runtime, _hidden_cell_content
from pipeline.jev_explicit_notes import _kind, _numbered_container, ARC
from pipeline.jev_screening import fingerprint
from scripts.compare_jev_retrieval import load_replay
from scripts.jev_pilot_session import install_read_only_guard, sha, write

TARGETS = {'ROW-96f4cdf3e1312b04', 'ROW-1c2a72c58fbc2d87', 'ROW-10740886584fa8b9'}


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
    summary, packets = load_replay(run, 'dependency_bound_v4_55')
    if summary['parser_runtime'] != runtime:
        raise ValueError('Frozen parser runtime required')
    selected = [p for p in packets.values() if p['flag']['row_id'] in TARGETS]
    if len(selected) != 3:
        raise ValueError('Incomplete fixed selection')
    records = []
    for packet in selected:
        print('Inspecting linked continuations:', packet['flag']['row_id'], flush=True)
        source = Path(packet['filing']['path']).resolve()
        if (not source.is_relative_to(repo / 'data/raw/filings/bdc_html')
                or source.stat().st_size > 40 * 1024 * 1024 or sha(source) != packet['filing']['sha256']):
            raise ValueError('Frozen bounded source required')
        soup = BeautifulSoup(source.read_bytes(), 'lxml')
        by_id = defaultdict(list)
        for node in soup.find_all(True):
            if node.get('id'):
                by_id[node['id']].append(node)
        facts = soup.find_all('ix:nonfraction', attrs={'contextref': packet['output_position']['src_context_id']})
        ids = {f.get('id') for f in facts if str(f.get('name', '')).split(':')[-1].lower()
               in {'investmentownedatcost', 'investmentownedatfairvalue'}}
        targets = set()
        for relation in soup.find_all('ix:relationship', attrs={'arcrole': ARC}):
            if ids.intersection(str(relation.get('fromrefs', '')).split()):
                targets.update(str(relation.get('torefs', '')).split())
        notes = []
        for target in sorted(targets):
            if len(by_id[target]) != 1:
                raise ValueError('Ambiguous linked note ID')
            note = by_id[target][0]
            if not note.has_attr('continuedat'):
                continue
            _, marker, numbered = _numbered_container(note)
            chain, visited, current = [], set(), note
            while current is not None:
                ident = current.get('id')
                if not ident or ident in visited or len(visited) >= 10:
                    raise ValueError('Malformed or excessive continuation chain')
                visited.add(ident)
                text = clean(current.get_text(' ', strip=True))
                if len(text) > 20000:
                    raise ValueError('Continuation text cap exceeded')
                chain.append({'id': ident, 'kind': current.name, 'text': text,
                              'continued_at': current.get('continuedat'),
                              'hidden': _hidden_cell_content(current),
                              'table_count': len(current.find_all('table')),
                              'exclusions': len(current.find_all('ix:exclude'))})
                following = current.get('continuedat')
                if following:
                    matches = by_id[following]
                    if len(matches) != 1 or not _kind(matches[0], 'continuation'):
                        raise ValueError('Missing or ambiguous continuation target')
                    current = matches[0]
                else:
                    current = None
            bundle_notes = {fingerprint(n): n for c in packet['source_candidates'] for n in c['notes']
                            if marker is not None and n['marker'] == marker}
            notes.append({'note_id': target, 'marker': marker, 'numbered_container': numbered,
                          'chain': chain, 'existing_bundle_notes': list(bundle_notes.values())})
        records.append({'row_id': packet['flag']['row_id'], 'source_sha256': packet['filing']['sha256'],
                        'bundle_fingerprint': fingerprint(packet), 'notes': notes,
                        'current_evidence_status': packet['evidence_status']})
        soup.decompose()
        if sha(source) != packet['filing']['sha256']:
            raise ValueError('Source changed during inspection')
    if parser_runtime() != runtime:
        raise ValueError('Runtime changed')
    report = {'records': records, 'parser_runtime': runtime,
              'script_sha256': sha(Path(__file__)), 'helper_sha256': sha(ROOT / 'pipeline/jev_explicit_notes.py'),
              'notes_applied': False, 'production_changes': 0, 'api_calls': 0}
    path = run / ('linked_continuation_inspection_' + fingerprint(report)[:16] + '.json')
    if not path.exists():
        write(path, report)
    print(json.dumps({'artifact': path.name, 'records': [{'row_id': r['row_id'],
          'notes': [{'id': n['note_id'], 'marker': n['marker'], 'segments': len(n['chain'])}
                    for n in r['notes']]} for r in records]}), flush=True)


if __name__ == '__main__':
    timer = threading.Timer(120, lambda: os._exit(124))
    timer.daemon = True
    timer.start()
    try:
        main()
    finally:
        timer.cancel()
