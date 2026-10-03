"""Freeze at most four unseen-accession cases within two already consumed funds."""
import argparse
from collections import Counter
import json
import os
from pathlib import Path
import sys
import threading

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from pipeline.jev_bundles import SourceCache, build_bundle
from scripts.jev_pilot_session import install_read_only_guard, read, sha, write


def main():
    import duckdb
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--run-root', type=Path, required=True)
    args = parser.parse_args()
    repo, run = args.repo.resolve(), args.run_root.resolve()
    if repo == ROOT or not run.is_relative_to(repo / 'data/pilot/jev_screening'):
        raise ValueError('Isolated pilot required')
    install_read_only_guard(repo, run)
    target = run / 'temporal_frozen_01'
    target.mkdir()
    reservation = read(run / 'holdout_reservation_v2.json')
    ciks = ['0001954360', '0001920145']
    assert set(ciks) == {r['cik'] for r in reservation['holdout_funds']}
    assert len(set(ciks) | set(reservation['all_previously_exercised_ciks'])) <= 16
    frozen = {'arm': 'within_filer_unseen_accession', 'quarter': '2025-09-30',
              'builder_sha256': sha(ROOT / 'pipeline/jev_bundles.py'),
              'runner_sha256': sha(ROOT / 'scripts/run_jev_screening.py'),
              'routing_sha256': sha(ROOT / 'pipeline/jev_screening.py'),
              'selection': 'One salted flag per C107/X08 per fund; missing strata stay empty; no replacement by readiness.',
              'max_flags': 4, 'new_funds': 0, 'untouched_filer_holdout': False}
    write(target / 'frozen_builder.json', frozen)
    seen = set()
    for directory in ['original_packets', 'holdout_development_02', 'weak_probe_04_packets']:
        paths = list((run / directory).glob('*_ROW-*.json'))
        if len(paths) > 50:
            raise ValueError('Prior corpus bound exceeded')
        for path in paths:
            row = read(path).get('output_position', {})
            seen.add((row.get('cik'), row.get('accession_number')))
    flag_path, holdings_path = repo / 'data/output/row_validation_issues.csv', repo / 'data/output/private_markets_holdings.csv'
    stamps = {p: (p.stat().st_size, p.stat().st_mtime_ns) for p in [flag_path, holdings_path]}
    provenance = {'flags_sha256': sha(flag_path), 'holdings_sha256': sha(holdings_path),
                  'builder_sha256': frozen['builder_sha256']}
    print('Selecting at most four temporal cases; source not inspected yet', flush=True)
    con = duckdb.connect()
    con.execute("SET memory_limit='1GB'")
    con.execute('SET threads=2')
    try:
        result = con.execute("""WITH ranked AS (
            SELECT *, row_number() OVER(PARTITION BY cik,rule_id
              ORDER BY md5('jev-temporal-v1|' || row_id),row_id) sample_rank
            FROM read_csv(?,all_varchar=true)
            WHERE source='bdc' AND cik IN (?,?) AND report_date='2025-09-30'
              AND rule_id IN ('C107','X08')
        ) SELECT * EXCLUDE(sample_rank) FROM ranked WHERE sample_rank=1
          ORDER BY cik,rule_id LIMIT 4""", [str(flag_path), *ciks])
        columns = [c[0] for c in result.description]
        flags = [dict(zip(columns, row)) for row in result.fetchall()]
        ids = [f['row_id'] for f in flags]
        rows = []
        if ids:
            result = con.execute('SELECT * FROM read_csv(?,all_varchar=true) WHERE row_id IN (' +
                                 ','.join('?' for _ in ids) + ') LIMIT 9', [str(holdings_path), *ids])
            columns = [c[0] for c in result.description]
            rows = [dict(zip(columns, row)) for row in result.fetchall()]
        if len(rows) > 8:
            raise ValueError('Join bound exceeded')
    finally:
        con.close()
    if any((p.stat().st_size, p.stat().st_mtime_ns) != stamp for p, stamp in stamps.items()):
        raise ValueError('Input snapshot changed')
    if any((r['cik'], r['accession_number']) in seen for r in rows):
        raise ValueError('Selected accession was already in the pilot; no replacement allowed')
    write(run / 'temporal_selection_01.json', {
        'flags': flags, 'holdings_rows': rows, 'provenance': provenance, 'freeze': frozen,
        'prior_accessions': sorted([list(pair) for pair in seen if all(pair)]),
        'missing_strata': [{'cik': cik, 'rule_id': rule} for cik in ciks for rule in ['C107', 'X08']
                           if not any(f['cik'] == cik and f['rule_id'] == rule for f in flags)]})
    cache = SourceCache(html_cache_dir=repo / 'data/raw/filings/bdc_html')
    cases = []
    for flag in flags:
        packet = build_bundle(flag, [r for r in rows if r['row_id'] == flag['row_id']], provenance, cache=cache)
        write(target / (flag['rule_id'] + '_' + flag['row_id'] + '.json'), packet)
        cases.append({'row_id': flag['row_id'], **packet['evidence_status']})
        print(flag['row_id'], packet['evidence_status']['status'], flush=True)
    if sha(ROOT / 'pipeline/jev_bundles.py') != frozen['builder_sha256']:
        raise ValueError('Builder changed during temporal holdout')
    report = {'cases': cases, 'status_counts': dict(Counter(r['status'] for r in cases)),
              'arm': frozen['arm'], 'production_clearance_enabled': False}
    write(target / 'summary.json', report)
    print(json.dumps(report['status_counts']), flush=True)


if __name__ == '__main__':
    timer = threading.Timer(240, lambda: os._exit(124))
    timer.daemon = True
    timer.start()
    try:
        main()
    finally:
        timer.cancel()
