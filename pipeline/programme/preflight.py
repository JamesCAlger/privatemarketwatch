"""Small actual cache-only workloads; never eligible as complete candidate stages."""
from pathlib import Path

from pipeline.programme.core import ContractError, atomic_json, now, read_json


def sample_raw_inputs(config, connection):
    """Bound materialized rows; DuckDB scans cached files, never pandas full loads."""
    bdc = connection.execute("""
        SELECT * EXCLUDE (sample_rank) FROM (
            SELECT *, row_number() OVER (PARTITION BY cik, report_date
                ORDER BY investment_identifier, accession_number) AS sample_rank
            FROM read_csv(?, header=true, all_varchar=true)
            WHERE lpad(cik,10,'0') IN ('0001950976','0001930087','0001287750')
              AND report_date >= '2023-03-31' AND report_date <= '2026-03-31'
        ) WHERE sample_rank <= 8 ORDER BY cik, report_date, investment_identifier LIMIT 400
    """, [str(config.BDC_HOLDINGS_FILE)]).df().fillna('')
    nport = connection.execute("""
        SELECT * EXCLUDE (sample_rank) FROM (
            SELECT *, row_number() OVER (PARTITION BY cik, report_date
                ORDER BY issuer_name, holding_id) AS sample_rank
            FROM read_csv(?, header=true, all_varchar=true)
            WHERE fair_value_level='3' AND report_date >= '2023-03-31'
              AND report_date <= '2026-03-31'
        ) WHERE sample_rank <= 3 ORDER BY cik, report_date, issuer_name LIMIT 80
    """, [str(config.NPORT_HOLDINGS_FILE)]).df().fillna('')
    if bdc.empty or nport.empty:
        raise ContractError('Representative raw source sample is empty')
    return bdc, nport, dict(bdc_rows=len(bdc), nport_rows=len(nport),
        bdc_ciks=sorted(bdc.cik.unique()), bdc_dates=sorted(bdc.report_date.unique()),
        nport_ciks=sorted(nport.cik.unique()), nport_dates=sorted(nport.report_date.unique()),
        selection='8 BDC rows per fund-quarter across three named funds; 3 NPORT L3 rows per fund-quarter, capped 80',
        limitation='Promoted rule stores are empty for this sample; full admitted corrections execute in the real unified stage')


def execute_preflight(attempt, reads):
    from pipeline.programme.stages import execute
    attempt = Path(attempt)
    results = {}
    from pipeline.programme.runner import STAGES
    for stage in STAGES:
        print('Representative workload: ' + stage, flush=True)
        execute(attempt, reads, preflight_stage=stage)
        results[stage] = read_json(attempt / 'bundle' / stage / 'summary.json')
    if results['identity']['times']['matches'] < 1:
        raise ContractError('Preflight did not exercise a cross-quarter position match')
    atomic_json(attempt / 'bundle/preflight_summary.json', dict(completed_utc=now(),
        stages=results, role='dependency preflight only; never a production or complete candidate stage',
        financial_validation='not assessed',
        limitations=['Bounded samples do not cover every financial rule branch',
                     'Windows native OS reads remain an explicit trusted boundary']))
