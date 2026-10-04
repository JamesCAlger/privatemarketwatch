"""Resolve explicit note links for three consumed flags in two Ares filings."""
import argparse
import json
import os
from pathlib import Path
import sys
import threading

from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from pipeline.jev_bundles import clean, parser_runtime
from pipeline.jev_explicit_notes import resolve_explicit_notes
from pipeline.jev_screening import fingerprint
from scripts.compare_jev_retrieval import load_replay
from scripts.jev_pilot_session import install_read_only_guard, sha, write

TARGETS = {'dependency_bound_v4_55': {'ROW-f22f54d69382e56e'},
           'later_period_c104_57': {'ROW-a5dcb49c5296d21a', 'ROW-0f8a9c553173fb19'}}
CONCEPTS = {'investmentownedatcost', 'investmentownedatfairvalue'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--run-root', type=Path, required=True)
    args = parser.parse_args()
    repo, run = args.repo.resolve(), args.run_root.resolve()
    if repo == ROOT or not run.is_relative_to(repo / 'data/pilot/jev_screening'):
        raise ValueError('Isolated pilot required')
    install_read_only_guard(repo, run)
    runtime, records = parser_runtime(), []
    for replay, targets in TARGETS.items():
        summary, packets = load_replay(run, replay)
        if summary['parser_runtime'] != runtime:
            raise ValueError('Frozen parser runtime required')
        selected = [p for p in packets.values() if p['flag']['row_id'] in targets]
        if len(selected) != len(targets):
            raise ValueError('Selection incomplete')
        for packet in selected:
            print('Resolving explicit notes:', packet['flag']['row_id'], flush=True)
            source = Path(packet['filing']['path']).resolve()
            if (not source.is_relative_to(repo / 'data/raw/filings/bdc_html')
                    or source.stat().st_size > 40 * 1024 * 1024
                    or sha(source) != packet['filing']['sha256']):
                raise ValueError('Bounded frozen source required')
            soup = BeautifulSoup(source.read_bytes(), 'lxml')
            tables = [t for t in soup.find_all('table') if any(r.find(['td', 'th']) for r in t.find_all('tr'))]
            candidate_facts, fact_ids = [], []
            for candidate in packet['source_candidates']:
                rows = [r for r in tables[candidate['table_index']].find_all('tr') if r.find(['td', 'th'])]
                row = rows[candidate['row_index']]
                actual = row.find_all('ix:nonfraction')
                expected = [f for c in candidate['raw_cells'] for f in c.get('inline_facts', [])]
                if [(n.get('name'), n.get('contextref'), clean(n.text)) for n in actual] != [
                        (f['name'], f['context_id'], f['text']) for f in expected]:
                    raise ValueError('Raw source coordinates disagree with frozen candidate facts')
                monetary = [n for n in actual if str(n.get('name', '')).split(':')[-1].lower() in CONCEPTS]
                if not monetary or any(not n.get('id') for n in monetary):
                    raise ValueError('Explicit monetary fact IDs required')
                ids = [n['id'] for n in monetary]
                fact_ids.extend(ids)
                candidate_facts.append({'evidence_id': candidate['evidence_id'], 'fact_ids': ids,
                                        'missing_markers': candidate['missing_note_markers']})
            diagnostic = resolve_explicit_notes(soup, list(dict.fromkeys(fact_ids)))
            by_id = {r['fact_id']: r for r in diagnostic['records']}
            for candidate in candidate_facts:
                candidate['per_fact_missing_marker_links'] = [
                    {'fact_id': f, 'status': by_id[f]['status'], 'blockers': by_id[f]['blockers'],
                     'linked_missing_markers': sorted({n['marker'] for n in by_id[f]['notes']}
                                                     & set(candidate['missing_markers']))}
                    for f in candidate['fact_ids']]
            records.append({'row_id': packet['flag']['row_id'], 'replay': replay,
                            'bundle_fingerprint': fingerprint(packet), 'source_sha256': packet['filing']['sha256'],
                            'candidate_facts': candidate_facts, 'diagnostic': diagnostic,
                            'builder_status_unchanged': packet['evidence_status']['status']})
            soup.decompose()
            if sha(source) != packet['filing']['sha256']:
                raise ValueError('Source changed')
    if parser_runtime() != runtime:
        raise ValueError('Runtime changed')
    report = {'records': records, 'parser_runtime': runtime,
              'helper_sha256': sha(ROOT / 'pipeline/jev_explicit_notes.py'),
              'script_sha256': sha(Path(__file__)), 'api_calls': 0, 'production_changes': 0,
              'limitation': 'Explicit-link diagnostic only; no note attachment, completeness certification, period reassignment or readiness promotion.'}
    path = run / ('explicit_note_probe_' + fingerprint(report)[:16] + '.json')
    if not path.exists():
        write(path, report)
    print(json.dumps({'artifact': path.name, 'records': [
        {'row_id': r['row_id'], 'candidates': len(r['candidate_facts']),
         'facts': len(r['diagnostic']['records']),
         'unresolved': sum(f['status'] == 'unresolved' for f in r['diagnostic']['records'])}
        for r in records]}), flush=True)


if __name__ == '__main__':
    timer = threading.Timer(150, lambda: os._exit(124))
    timer.daemon = True
    timer.start()
    try:
        main()
    finally:
        timer.cancel()
