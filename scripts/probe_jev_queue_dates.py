"""Read-only reproduction of queue localization for two existing Ares groups."""
import argparse
import json
import os
from pathlib import Path
import sys
import threading

import duckdb

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from pipeline.review_queue import _queue_item
from pipeline.jev_screening import fingerprint
from scripts.jev_pilot_session import install_read_only_guard, sha, write


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--run-root', type=Path, required=True)
    args = parser.parse_args()
    repo, run = args.repo.resolve(), args.run_root.resolve()
    if repo == ROOT or not run.is_relative_to(repo / 'data/pilot/jev_screening'):
        raise ValueError('Isolated pilot required')
    install_read_only_guard(repo, run)
    modules = {name: sha(repo / name) for name in ('pipeline/review_queue.py', 'scripts/shadow_adapter.py')}
    if any(sha(ROOT / name)!=value for name, value in modules.items()):
        raise ValueError('Isolated modules do not match observed production mechanism')
    paths = {'issues': repo / 'data/output/row_validation_issues.csv',
             'ledger': repo / 'data/output/shadow/validation_results_ledger.csv',
             'queue': repo / 'data/output/review_queue/review_queue.csv'}
    before = {k: sha(p) for k, p in paths.items()}
    periods = ['2023-09-30', '2023-12-31']
    print('Probing two existing Ares C107 groups and CSV date inference', flush=True)
    with duckdb.connect(config={'memory_limit': '1GB', 'threads': 2}) as db:
        def query(sql, params):
            result = db.execute(sql, params)
            columns = [c[0] for c in result.description]
            values = result.fetchmany(11)
            if len(values)>10:
                raise ValueError('Bounded date-probe output exceeded')
            return [dict(zip(columns, row)) for row in values]
        raw_dates = query('''SELECT report_date, row_id FROM read_csv_auto(?, all_varchar=true)
            WHERE TRY_CAST(cik AS BIGINT)=1702510 AND dataset='private_markets_holdings'
              AND source='bdc' AND rule_id='C107' AND report_date IN (SELECT UNNEST(?)) ORDER BY report_date''',
            [str(paths['issues']), periods])
        inferred_dates = query('''SELECT CAST(report_date AS VARCHAR) inferred_period,
            typeof(report_date) inferred_type, row_id FROM read_csv_auto(?, sample_size=-1)
            WHERE TRY_CAST(cik AS BIGINT)=1702510 AND dataset='private_markets_holdings'
              AND source='bdc' AND rule_id='C107'
              AND CAST(report_date AS DATE) IN (SELECT CAST(UNNEST(?) AS DATE)) ORDER BY report_date''',
            [str(paths['issues']), periods])
        ledger = query('''SELECT * FROM read_csv_auto(?, all_varchar=true)
            WHERE engine='row_validation' AND rule_name='C107' AND TRY_CAST(cik AS BIGINT)=1702510
              AND CAST(TRY_CAST(period AS DATE) AS VARCHAR) IN (SELECT UNNEST(?)) ORDER BY period''',
            [str(paths['ledger']), periods])
        queue = query('''SELECT review_id, cik, report_date, period, unit_label FROM read_csv_auto(?, all_varchar=true)
            WHERE engine='row_validation' AND rule_name='C107' AND TRY_CAST(unit_label AS BIGINT)=1702510
              AND CAST(TRY_CAST(period AS DATE) AS VARCHAR) IN (SELECT UNNEST(?)) ORDER BY period''',
            [str(paths['queue']), periods])
    if any(len(rows)!=2 for rows in (raw_dates, inferred_dates, ledger, queue)):
        raise ValueError('Expected two existing records in each source')
    records = []
    for raw, inferred, entry, queued in zip(raw_dates, inferred_dates, ledger, queue):
        if (raw['row_id'] != inferred['row_id'] or entry['period'] != inferred['inferred_period']
                or queued['period'] != entry['period']):
            raise ValueError('Observed date chain does not match')
        original = _queue_item(entry)
        normalized = _queue_item({**entry, 'period': raw['report_date']})
        if original['review_id'] != queued['review_id']:
            raise ValueError('Observed queue ID does not reproduce')
        records.append({'raw_issue': raw, 'inferred_issue': inferred, 'existing_queue': queued,
            'original_localization': {k: original[k] for k in ('review_id', 'cik', 'report_date')},
            'date_only_counterfactual': {k: normalized[k] for k in ('review_id', 'cik', 'report_date')}})
    if {k: sha(p) for k, p in paths.items()} != before:
        raise ValueError('Inputs changed during probe')
    report = {'input_sha256': before, 'module_sha256': modules, 'records': records,
        'original_unique_ids': len({r['original_localization']['review_id'] for r in records}),
        'counterfactual_unique_ids': len({r['date_only_counterfactual']['review_id'] for r in records}),
        'production_changes': 0, 'api_calls': 0,
        'limitation': 'Two-row mechanism reproduction only. Counterfactual IDs are not migrated, registered or authorized for dispatch.'}
    destination = run / ('queue_date_probe_' + fingerprint(report)[:16] + '.json')
    if not destination.exists():
        write(destination, report)
    print(json.dumps({'artifact': destination.name, **report}), flush=True)


if __name__ == '__main__':
    timer = threading.Timer(120, lambda: os._exit(124))
    timer.daemon = True
    timer.start()
    try:
        main()
    finally:
        timer.cancel()
