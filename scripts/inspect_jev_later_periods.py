"""Check later-period flag availability within the same 11 funds, without source inspection."""
import argparse
from collections import defaultdict
import json
import os
from pathlib import Path
import sys
import threading
import duckdb

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from pipeline.jev_screening import fingerprint
from scripts.compare_jev_retrieval import load_replay
from scripts.jev_pilot_session import install_read_only_guard, read, sha, write


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
    _, packets = load_replay(run, args.replay)
    ciks = sorted({p['flag']['cik'] for p in packets.values()})
    if len(packets) != 67 or len(ciks) != 11:
        raise ValueError('Expected fixed 67-case, 11-fund scope')
    known = defaultdict(set)
    for packet in packets.values():
        known[packet['flag']['cik']].add(packet['flag']['report_date'])
    historical_path = repo / 'scratch/2026-10-03_jev_b1_benchmark/inventory_ens2_rest_r3.json'
    historical_hash = sha(historical_path)
    for item in read(historical_path):
        if item['cik'] in ciks:
            known[item['cik']].add(item['quarter'])
    exploratory_path = run / 'exploratory_context_089f24a29d1a0ec6.json'
    exploratory = read(exploratory_path)['published_position']
    known[exploratory['cik']].add(exploratory['report_date'])
    boundaries = {cik: max(known[cik]) for cik in ciks}
    issues = repo / 'data/output/row_validation_issues.csv'
    issues_hash = sha(issues)
    print('Checking later-period metadata for 11 existing funds; no source files opened', flush=True)
    with duckdb.connect(config={'threads': 2, 'memory_limit': '1GB'}) as con:
        con.execute('CREATE TEMP TABLE boundaries(cik VARCHAR, last_known_period DATE)')
        con.executemany('INSERT INTO boundaries VALUES (?, ?)', sorted(boundaries.items()))
        result = con.execute('''SELECT i.cik, i.report_date, i.rule_id, count(*) flag_count
            FROM read_csv(?, all_varchar=true) i JOIN boundaries b USING(cik)
            WHERE i.source='bdc' AND i.rule_id IN ('C107','X08','C104')
              AND TRY_CAST(i.report_date AS DATE)>b.last_known_period
            GROUP BY i.cik,i.report_date,i.rule_id ORDER BY i.cik,i.report_date,i.rule_id LIMIT 101''', [str(issues)])
        columns = [c[0] for c in result.description]
        later = [dict(zip(columns, row)) for row in result.fetchall()]
        if len(later) > 100:
            raise ValueError('Metadata output exceeds scope cap')
    if sha(issues) != issues_hash or sha(historical_path) != historical_hash:
        raise ValueError('Input metadata changed')
    report = {'replay': args.replay, 'issues_sha256': issues_hash, 'historical_inventory_sha256': historical_hash,
              'exploratory_artifact_sha256': sha(exploratory_path),
              'funds': len(ciks), 'last_known_period_by_fund': boundaries,
              'later_period_groups': later, 'new_flags_selected': 0, 'source_files_opened': 0,
              'api_calls': 0, 'production_changes': 0,
              'limitation': 'Availability only. Historical inventory metadata extends the exclusion boundary, but does not establish independent review or fresh holdout eligibility. No scope expansion or sample selection.'}
    path = run / ('later_period_availability_' + fingerprint(report)[:16] + '.json')
    if not path.exists():
        write(path, report)
    print(json.dumps({'artifact': path.name, 'funds': len(ciks), 'later_period_groups': later,
                      'last_known_period_by_fund': boundaries}), flush=True)


if __name__ == '__main__':
    timer = threading.Timer(90, lambda: os._exit(124))
    timer.daemon = True
    timer.start()
    try:
        main()
    finally:
        timer.cancel()
