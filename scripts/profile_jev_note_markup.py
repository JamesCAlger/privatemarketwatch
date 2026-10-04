"""Bounded inspection of superscript markup on frozen candidate rows; no labels."""
import argparse
from collections import defaultdict
import json
import os
from pathlib import Path
import re
import sys
import threading

from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from pipeline.jev_screening import fingerprint
from scripts.compare_jev_retrieval import load_replay
from scripts.jev_pilot_session import install_read_only_guard, read, sha, write
from scripts.review_jev_sources import review_source_path


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
    sources = defaultdict(list)
    for packet in packets.values():
        if packet['source_candidates']:
            sources[review_source_path(repo, packet)].append(packet)
    if len(sources) > 30:
        raise ValueError('Source limit exceeded')
    records, candidate_rows = [], set()
    for index, (path, source_packets) in enumerate(sources.items(), 1):
        print(f'Note markup source {index}/{len(sources)}', flush=True)
        digest = sha(path)
        if path.stat().st_size > 40 * 1024 * 1024 or any(p['filing']['sha256'] != digest for p in source_packets):
            raise ValueError('Source changed or exceeds limit')
        soup = BeautifulSoup(path.read_bytes().decode('utf-8'), 'lxml')
        tables = [t for t in soup.find_all('table') if any(tr.find(['td', 'th']) for tr in t.find_all('tr'))]
        for packet in source_packets:
            for candidate in packet['source_candidates']:
                key = (digest, candidate['table_index'], candidate['row_index'])
                if key in candidate_rows:
                    continue
                candidate_rows.add(key)
                rows = [tr for tr in tables[key[1]].find_all('tr') if tr.find(['td', 'th'])]
                row = rows[key[2]]
                for tag in row.find_all(['sup', 'span']):
                    if tag.name != 'sup' and not re.search(r'vertical-align\s*:\s*super', tag.get('style', ''), re.I):
                        continue
                    text = ' '.join(tag.get_text(' ', strip=True).split())
                    if not text:
                        continue
                    records.append({'source_sha256': digest, 'cik': packet['flag']['cik'],
                        'period': packet['flag']['report_date'], 'evidence_id': candidate['evidence_id'],
                        'tag': tag.name, 'text': text[:120],
                        'bare_marker_shape': bool(re.fullmatch(r'(?:\d{1,2}|[A-Za-z])(?:\s*,\s*(?:\d{1,2}|[A-Za-z]))*', text)),
                        'inside_numeric_fact': tag.find_parent('ix:nonfraction') is not None})
                    if len(records) > 2000:
                        raise ValueError('Markup record limit exceeded')
        del soup, tables
    report = {'replay': args.replay, 'builder_sha256': summary['builder_sha256'],
        'sources': len(sources), 'candidate_rows_inspected': len(candidate_rows),
        'superscript_records': len(records), 'bare_marker_shapes': sum(r['bare_marker_shape'] for r in records),
        'records': records, 'production_clearance_enabled': False,
        'limitation': 'Candidate rows only; excludes unretrieved rows, headers and section headings. Markup shapes do not establish note meaning.'}
    destination = run / ('note_markup_' + fingerprint(report)[:16] + '.json')
    if not destination.exists():
        write(destination, report)
    print(json.dumps({k: v for k, v in report.items() if k not in {'records', 'limitation'}}), flush=True)


if __name__ == '__main__':
    timer = threading.Timer(240, lambda: os._exit(124))
    timer.daemon = True
    timer.start()
    try:
        main()
    finally:
        timer.cancel()
