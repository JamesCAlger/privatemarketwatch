"""Select and build six C104 development flags from already consumed funds."""
from __future__ import annotations
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
    parser.add_argument('--label', default='weak_probe_02')
    args = parser.parse_args()
    repo, run = args.repo.resolve(), args.run_root.resolve()
    if repo == ROOT or not run.is_relative_to(repo / 'data/pilot/jev_screening'):
        raise ValueError('Isolated pilot required')
    install_read_only_guard(repo, run)
    if not args.label.replace('_', '').isalnum():
        raise ValueError('Invalid label')
    ciks = ['0001954360', '0001920145', '0001784700']
    reservation = read(run / 'holdout_reservation_v2.json')
    consumed = set(reservation['all_previously_exercised_ciks']) | {r['cik'] for r in reservation['holdout_funds']}
    assert set(ciks) <= consumed and len(consumed) <= 16
    flags_path = repo / 'data/output/row_validation_issues.csv'
    holdings_path = repo / 'data/output/private_markets_holdings.csv'
    print('Selecting six bounded weak-rule flags from three consumed funds', flush=True)
    stamps = {p: (p.stat().st_size, p.stat().st_mtime_ns) for p in [flags_path, holdings_path]}
    provenance = {'flags_sha256': sha(flags_path), 'holdings_sha256': sha(holdings_path),
                  'builder_sha256': sha(ROOT / 'pipeline/jev_bundles.py')}
    con = duckdb.connect()
    con.execute("SET memory_limit='1GB'")
    con.execute('SET threads=2')
    try:
        result = con.execute("""WITH eligible AS (
            SELECT *, dense_rank() OVER(PARTITION BY cik ORDER BY report_date DESC) period_rank
            FROM read_csv(?,all_varchar=true)
            WHERE source='bdc' AND rule_id='C104' AND cik IN (?,?,?)
              AND report_date IN ('2025-12-31','2026-03-31')
        ), ranked AS (
            SELECT *, row_number() OVER(PARTITION BY cik,report_date
            ORDER BY md5('c104-probe-v1|' || row_id),row_id) sample_rank
            FROM eligible WHERE period_rank<=2
        ) SELECT * EXCLUDE(period_rank,sample_rank) FROM ranked WHERE sample_rank=1
          ORDER BY cik,report_date LIMIT 6""", [str(flags_path), *ciks])
        columns = [c[0] for c in result.description]
        flags = [dict(zip(columns, r)) for r in result.fetchall()]
        if not flags:
            raise ValueError('No eligible flags')
        ids = [f['row_id'] for f in flags]
        result = con.execute('SELECT * FROM read_csv(?,all_varchar=true) WHERE row_id IN (' +
                             ','.join('?' for _ in ids) + ') LIMIT 13', [str(holdings_path), *ids])
        columns = [c[0] for c in result.description]
        rows = [dict(zip(columns, r)) for r in result.fetchall()]
        assert len(rows) <= 12
    finally:
        con.close()
    assert all((p.stat().st_size, p.stat().st_mtime_ns) == stamp for p, stamp in stamps.items())
    write(run / (args.label + '_selection.json'), {'flags': flags, 'holdings_rows': rows, 'provenance': provenance,
          'arm': 'development', 'selection': 'One salted sample per 2025-12-31/2026-03-31 period, three already consumed funds'})
    target = run / (args.label + '_packets')
    target.mkdir()
    cache = SourceCache(html_cache_dir=repo / 'data/raw/filings/bdc_html')
    summaries = []
    for flag in flags:
        packet = build_bundle(flag, [r for r in rows if r['row_id'] == flag['row_id']], provenance, cache=cache)
        write(target / ('C104_' + flag['row_id'] + '.json'), packet)
        summaries.append({'row_id': flag['row_id'], **packet['evidence_status']})
        print(flag['row_id'], packet['evidence_status']['status'], flush=True)
    assert sha(ROOT / 'pipeline/jev_bundles.py') == provenance['builder_sha256']
    write(target / 'summary.json', {'cases': summaries, 'status_counts': dict(Counter(r['status'] for r in summaries))})


if __name__ == '__main__':
    timer = threading.Timer(240, lambda: os._exit(124))
    timer.daemon = True
    timer.start()
    try:
        main()
    finally:
        timer.cancel()
