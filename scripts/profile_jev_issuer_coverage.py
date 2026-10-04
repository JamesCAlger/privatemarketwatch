"""Aggregate one reserved filer's issuer gaps over time; no new case selection."""
import argparse
import json
import os
from pathlib import Path
import sys
import threading

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from pipeline.jev_screening import fingerprint
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
    holdings = repo / 'data/output/private_markets_holdings.csv'
    holdings_hash = sha(holdings)
    parent = read(run / 'rate_note_scope_v4_42/summary.json')
    if holdings_hash != parent['holdings_sha256']:
        raise ValueError('Holdings differ from pilot snapshot')
    db = duckdb.connect(config={'threads': '2', 'memory_limit': '1GB'})
    print('Aggregating Crescent issuer coverage by period', flush=True)
    db.execute('''CREATE TEMP TABLE positions AS SELECT report_date, row_id, issuer_name,
        bdc_investment_identifier,
        (issuer_name IS NULL OR TRIM(issuer_name)='') missing_issuer,
        CASE
          WHEN regexp_matches(bdc_investment_identifier,
            '^Investments\\s+.+?\\s+(?:Debt|Equity)\\s+Investments\\s+Health Care Equipment and Services\\s+')
            THEN 'health_care_and_variant'
          WHEN regexp_matches(bdc_investment_identifier,
            '^Investments\\s+.+?\\s+(?:Debt|Equity)\\s+Investments\\s+Financial Service\\s+')
            THEN 'financial_service_singular'
          ELSE 'other_identifier'
        END label_group
        FROM read_csv_auto(?, all_varchar=true)
        WHERE TRY_CAST(cik AS BIGINT)=1954360 AND source='bdc' ''', [str(holdings)])
    result = db.execute('''SELECT report_date, label_group, COUNT(*) positions,
        COUNT(*) FILTER (WHERE missing_issuer) missing_issuers,
        COUNT(DISTINCT row_id) distinct_snapshot_row_ids
        FROM positions GROUP BY ALL ORDER BY report_date, label_group''')
    names = [c[0] for c in result.description]
    rows = result.fetchmany(101)
    if len(rows) > 100:
        raise ValueError('Aggregate output exceeds cap')
    records = [dict(zip(names, row)) for row in rows]
    db.close()
    if sha(holdings) != holdings_hash:
        raise ValueError('Holdings changed')
    report = {'cik': '0001954360', 'holdings_sha256': holdings_hash, 'records': records,
        'script_sha256': sha(Path(__file__)), 'production_changes': 0, 'api_calls': 0,
        'limitations': ['Aggregate identifier-label profile, not additional source-reviewed natural cases.',
            'Null-issuer association does not prove every row shares the reproduced three-case mechanism.',
            'Changing label frequencies do not by themselves date a filer-template change.',
            'Counts are within the current snapshot; no historical pipeline build was replayed.']}
    destination = run / ('issuer_coverage_' + fingerprint(report)[:16] + '.json')
    if not destination.exists():
        write(destination, report)
    print(json.dumps({'artifact': destination.name, 'records': records}), flush=True)


if __name__ == '__main__':
    timer = threading.Timer(90, lambda: os._exit(124))
    timer.daemon = True
    timer.start()
    try:
        main()
    finally:
        timer.cancel()
