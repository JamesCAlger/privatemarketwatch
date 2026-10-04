"""Read-only aggregate of existing validation rows within the reserved 16 funds."""
import argparse
import json
import os
from pathlib import Path
import sys
import threading

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from pipeline.jev_screening import fingerprint
from scripts.jev_pilot_session import install_read_only_guard, sha, write

CIKS = (1702510, 1742313, 1784700, 1825265, 1860424, 1872371, 1899017,
        1916608, 1918712, 1919369, 1925309, 1959568, 2012139, 2031750,
        1954360, 1920145)


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
    source = repo / 'data/output/row_validation_issues.csv'
    source_hash = sha(source)
    print('Aggregating validation rows for 16 reserved funds', flush=True)
    db = duckdb.connect(config={'memory_limit': '1GB', 'threads': '2'})
    db.execute('''CREATE TEMP TABLE selected AS
        SELECT dataset, source, TRY_CAST(cik AS BIGINT) cik, report_date,
               row_id, rule_id, severity, evidence_strength, status, action
        FROM read_csv_auto(?, all_varchar=true)
        WHERE TRY_CAST(cik AS BIGINT) IN (SELECT UNNEST(?))''', [str(source), list(CIKS)])

    def records(query):
        result = db.execute(query)
        columns = [c[0] for c in result.description]
        rows = result.fetchmany(5001)
        if len(rows) > 5000:
            raise ValueError('Aggregate output exceeds cap')
        return [dict(zip(columns, row)) for row in rows]

    counts = '''COUNT(*) issue_rows, COUNT(DISTINCT cik) funds,
        COUNT(DISTINCT (cik, report_date)) fund_periods,
        COUNT(DISTINCT (dataset, source, cik, report_date, row_id))
            FILTER (WHERE row_id IS NOT NULL AND row_id<>'') identified_position_keys,
        COUNT(*) FILTER (WHERE row_id IS NULL OR row_id='') missing_row_ids'''
    overall = records('SELECT ' + counts + ', MIN(report_date) first_period, MAX(report_date) last_period FROM selected')
    groups = records('SELECT dataset, source, rule_id, severity, evidence_strength, status, action, '
                     + counts + ' FROM selected GROUP BY ALL ORDER BY issue_rows DESC, dataset, source, rule_id, severity, evidence_strength, status, action')
    quarters = records('SELECT report_date, evidence_strength, action, ' + counts
                       + ' FROM selected GROUP BY ALL ORDER BY report_date DESC, issue_rows DESC, evidence_strength, action')
    latest = records('''WITH periods AS (SELECT cik, MAX(report_date) report_date
                         FROM selected WHERE dataset='private_markets_holdings' AND source='bdc'
                         GROUP BY cik)
        SELECT s.rule_id, s.severity, s.evidence_strength, s.status, s.action,
               COUNT(*) issue_rows, COUNT(DISTINCT s.cik) funds,
               MIN(s.report_date) earliest_latest_period, MAX(s.report_date) latest_period
        FROM selected s JOIN periods p USING(cik, report_date)
        WHERE s.dataset='private_markets_holdings' AND s.source='bdc'
        GROUP BY ALL ORDER BY issue_rows DESC, rule_id, severity, evidence_strength, status, action''')
    missing_ids = records('SELECT dataset, source, rule_id, report_date, ' + counts
                         + " FROM selected WHERE row_id IS NULL OR row_id=''"
                         + ' GROUP BY ALL ORDER BY issue_rows DESC, dataset, source, rule_id, report_date')
    overlaps = records('''WITH positions AS (
        SELECT cik, report_date, row_id,
            BOOL_OR(rule_id='C107') c107,
            BOOL_OR(rule_id='C104') c104,
            BOOL_OR(rule_id='X08') x08,
            BOOL_OR(action='REVIEW') any_review,
            BOOL_OR(action='BLOCK_VERIFIED') any_block,
            BOOL_OR(action='REVIEW' AND rule_id<>'C107') review_other_than_c107,
            BOOL_OR(evidence_strength='STRONG') any_strong
        FROM selected
        WHERE dataset='private_markets_holdings' AND source='bdc'
            AND report_date='2026-03-31' AND row_id IS NOT NULL AND row_id<>''
        GROUP BY cik, report_date, row_id)
        SELECT c107, c104, x08, any_review, any_block, review_other_than_c107, any_strong,
               COUNT(*) position_keys, COUNT(DISTINCT cik) funds
        FROM positions WHERE c107 OR c104 OR x08 GROUP BY ALL
        ORDER BY c107, c104, x08, any_review, any_block, review_other_than_c107, any_strong''')
    db.close()
    if sha(source) != source_hash:
        raise ValueError('Source changed during aggregate')
    report = {'source': str(source.relative_to(repo)), 'source_sha256': source_hash,
        'inventory_script_sha256': sha(Path(__file__)),
        'inspected_rule_code_sha256': sha(repo / 'pipeline/column_validation.py'),
        'reserved_ciks': list(CIKS), 'overall': overall, 'groups': groups,
        'missing_identity_groups': missing_ids,
        'q1_2026_position_flag_overlap': overlaps,
        'quarters': quarters, 'latest_flagged_period_per_fund': latest,
        'production_clearance_enabled': False,
        'limitations': ['Issue rows are not unique investigations or measured B1 jobs.',
            'Historical periods repeat positions; position keys are snapshot-local.',
            'Latest means latest period with a recorded flag, not confirmed latest fund holdings.',
            'Position overlaps use exact row IDs in this artifact; fund-wide or missing-ID issues cannot be allocated.',
            'Flags do not establish true-error prevalence, bundle readiness or Jev savings.',
            'No new flags selected for source investigation or model calls.']}
    destination = run / ('rule_workload_' + fingerprint(report)[:16] + '.json')
    if not destination.exists():
        write(destination, report)
    print(json.dumps({'artifact': destination.name, 'overall': overall,
                      'latest_rule_groups': len(latest)}), flush=True)


if __name__ == '__main__':
    timer = threading.Timer(120, lambda: os._exit(124))
    timer.daemon = True
    timer.start()
    try:
        main()
    finally:
        timer.cancel()
