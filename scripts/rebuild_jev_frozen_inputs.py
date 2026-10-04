"""Enrich frozen pilot rows from the identical holdings snapshot, then rebuild."""
from __future__ import annotations
import argparse
from collections import Counter
import json
import os
from pathlib import Path
import sys
import threading
import duckdb

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from pipeline.jev_bundles import SourceCache, build_bundle, clean
from pipeline.jev_screening import fingerprint
from scripts.jev_pilot_session import install_read_only_guard, read, sha, write


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--run-root', type=Path, required=True)
    parser.add_argument('--parents', nargs='+', required=True)
    parser.add_argument('--label', required=True)
    args = parser.parse_args()
    repo, run = args.repo.resolve(), args.run_root.resolve()
    if repo == ROOT or not run.is_relative_to(repo / 'data/pilot/jev_screening'):
        raise ValueError('Isolated pilot required')
    if any(not value.replace('_', '').isalnum() for value in [args.label, *args.parents]):
        raise ValueError('Invalid label')
    install_read_only_guard(repo, run)
    parents = {}
    for label in args.parents:
        directory = run / label
        summary = read(directory / 'summary.json')
        paths = list(directory.glob('*_ROW-*.json'))
        if len(paths) != len(summary['cases']):
            raise ValueError('Incomplete parent replay')
        for path in paths:
            packet = read(path)
            key = (packet['flag']['rule_id'], packet['flag']['row_id'])
            if key in parents:
                raise ValueError('Duplicate frozen flag')
            parents[key] = packet
    if not 1 <= len(parents) <= 100:
        raise ValueError('Bounded frozen selection required')
    reservation = read(run / 'holdout_reservation_v2.json')
    allowed = set(reservation['all_previously_exercised_ciks']) | {r['cik'] for r in reservation['holdout_funds']}
    if not {p['flag']['cik'] for p in parents.values()} <= allowed:
        raise ValueError('Fund outside pilot reservation')
    holdings = repo / 'data/output/private_markets_holdings.csv'
    holdings_hash = sha(holdings)
    if any(p['provenance']['holdings_sha256'] != holdings_hash for p in parents.values()):
        raise ValueError('Current holdings differ from frozen snapshot; do not enrich')
    row_ids = sorted({key[1] for key in parents})
    with duckdb.connect(config={'threads': 2, 'memory_limit': '1GB'}) as con:
        result = con.execute('''SELECT * FROM read_csv_auto(?,all_varchar=true)
            WHERE row_id IN (SELECT unnest(?)) LIMIT 101''', [str(holdings), row_ids])
        columns = [c[0] for c in result.description]
        rows = [dict(zip(columns, values)) for values in result.fetchall()]
    if len(rows) != len(row_ids) or len({r['row_id'] for r in rows}) != len(rows):
        raise ValueError('Snapshot row join is not unique and complete')
    matched = {r['row_id']: r for r in rows}
    for packet in parents.values():
        output = matched[packet['flag']['row_id']]
        for field, value in packet['output_position'].items():
            if clean(value) != clean(output.get(field)):
                raise ValueError('Frozen output differs from snapshot: ' + field)
    target = run / args.label
    target.mkdir()
    cache = SourceCache(html_cache_dir=repo / 'data/raw/filings/bdc_html')
    builder_hash = sha(ROOT / 'pipeline/jev_bundles.py')
    cases = []
    ordered = sorted(parents.items(), key=lambda item: (item[1]['flag']['cik'],
                     item[1]['output_position'].get('accession_number', ''), item[0]))
    for index, ((rule, row_id), parent) in enumerate(ordered, 1):
        provenance = {**parent['provenance'], 'builder_sha256': builder_hash,
                      'enriched_from_packet_sha256': fingerprint(parent),
                      'enrichment_basis': 'same_hash_full_holdings_row'}
        packet = build_bundle(parent['flag'], [matched[row_id]], provenance, cache=cache)
        if (packet['filing'].get('sha256') and parent['filing'].get('sha256')
                and packet['filing']['sha256'] != parent['filing']['sha256']):
            raise ValueError('Source changed since parent')
        write(target / (rule + '_' + row_id + '.json'), packet)
        cases.append({'rule': rule, 'row_id': row_id, **packet['evidence_status']})
        print(f"Rebuild {index}/{len(ordered)}: {row_id} {packet['evidence_status']['status']}", flush=True)
    if sha(ROOT / 'pipeline/jev_bundles.py') != builder_hash or sha(holdings) != holdings_hash:
        raise ValueError('Inputs changed during rebuild; incomplete replay')
    summary = {'arm': 'development_snapshot_enrichment', 'builder_sha256': builder_hash,
               'holdings_sha256': holdings_hash, 'cases': cases,
               'status_counts': dict(Counter(c['status'] for c in cases)), 'production_clearance_enabled': False}
    write(target / 'summary.json', summary)
    print(json.dumps(summary['status_counts']), flush=True)


if __name__ == '__main__':
    timer = threading.Timer(240, lambda: os._exit(124))
    timer.daemon = True
    timer.start()
    try:
        main()
    finally:
        timer.cancel()
