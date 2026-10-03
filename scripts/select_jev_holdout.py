"""Freeze up to 40 flags from the already reserved holdout CIKs; no source parsing."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import sys
import threading

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.jev_pilot_session import install_read_only_guard, read, sha, write


def main():
    import duckdb
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--run-root', type=Path, required=True)
    args = parser.parse_args()
    repo, out = args.repo.resolve(), args.run_root.resolve()
    if repo == ROOT or not out.is_relative_to(repo / 'data/pilot/jev_screening'):
        raise ValueError('Use isolated implementation and pilot artifacts')
    install_read_only_guard(repo, out)
    reservation = read(out / 'holdout_reservation_v2.json')
    ciks = [e['cik'] for e in reservation['holdout_funds']]
    assert len(set(ciks) | set(reservation['all_previously_exercised_ciks'])) <= 16
    assert 0 < len(ciks) <= 4
    flags_path = repo / 'data/output/row_validation_issues.csv'
    holdings_path = repo / 'data/output/private_markets_holdings.csv'
    print('Fingerprinting holdout inputs; cached artifacts only', flush=True)
    provenance = {'flags_path': str(flags_path), 'flags_sha256': sha(flags_path),
                  'holdings_path': str(holdings_path), 'holdings_sha256': sha(holdings_path)}
    stamps = {p: (p.stat().st_size, p.stat().st_mtime_ns) for p in (flags_path, holdings_path)}
    con = duckdb.connect()
    con.execute("SET memory_limit='1GB'")
    con.execute('SET threads=2')
    try:
        placeholders = ','.join('?' for _ in ciks)
        query = f"""WITH eligible AS (
          SELECT *, dense_rank() OVER(PARTITION BY cik ORDER BY report_date DESC) AS period_rank
          FROM read_csv(?, all_varchar=true)
          WHERE source='bdc' AND rule_id IN ('C107','X08') AND cik IN ({placeholders})
        ), sampled AS (
          SELECT *, row_number() OVER(PARTITION BY cik,report_date,rule_id
            ORDER BY md5('jev-shadow-holdout-v1|' || row_id),row_id) AS sample_rank
          FROM eligible WHERE period_rank<=2
        ) SELECT * EXCLUDE(period_rank,sample_rank) FROM sampled WHERE sample_rank<=5
          ORDER BY cik,report_date,rule_id,row_id LIMIT 40"""
        result = con.execute(query, [str(flags_path), *ciks])
        columns = [c[0] for c in result.description]
        flags = [dict(zip(columns, r)) for r in result.fetchall()]
        ids = sorted({f['row_id'] for f in flags})
        holdings = []
        if ids:
            result = con.execute('SELECT * FROM read_csv(?,all_varchar=true) WHERE row_id IN (' +
                                 ','.join('?' for _ in ids) + ') LIMIT 81', [str(holdings_path), *ids])
            columns = [c[0] for c in result.description]
            holdings = [dict(zip(columns, r)) for r in result.fetchall()]
            if len(holdings) > 80:
                raise ValueError('Row join exceeds bound')
        if any((p.stat().st_size, p.stat().st_mtime_ns) != stamps[p] for p in stamps):
            raise ValueError('Inputs changed during holdout selection')
        manifest = {'selection': 'Two latest available flag periods per reserved fund; up to five flags per rule/period, stable salted MD5 order',
                    'provenance': provenance, 'reserved_ciks': ciks,
                    'flags': flags, 'holdings_rows': holdings,
                    'reference_status': 'Not yet source-reviewed; no source read or model calls in selection',
                    'unrepresented_funds': sorted(set(ciks) - {f['cik'] for f in flags})}
        write(out / 'holdout_selection.json', manifest)
        print(json.dumps({'flags': len(flags), 'holdings_rows': len(holdings),
                          'funds': sorted({f['cik'] for f in flags}),
                          'unrepresented_funds': manifest['unrepresented_funds']}), flush=True)
    finally:
        con.close()


if __name__ == '__main__':
    timer = threading.Timer(180, lambda: os._exit(124))
    timer.daemon = True
    timer.start()
    try:
        main()
    finally:
        timer.cancel()
