"""Build six bounded B1-only proxy-cost lineage packets from frozen audit files.

Verifies internal policy application, not source truth or position-chain quality.
No Jev requests, screening eligibility, production writes or pipeline rebuilds.
"""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import sys
import threading

import duckdb

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from pipeline.jev_bundles import clean, number
from scripts.compare_jev_retrieval import load_replay
from scripts.jev_pilot_session import install_read_only_guard, read, sha, write


def records(result):
    columns = [c[0] for c in result.description]
    return [dict(zip(columns, values)) for values in result.fetchall()]


def verify_lineage(output, donor, audit, state, donor_state, earliest, release_id):
    checks = {
        'proxy_method': output.get('cost_source') == audit.get('method') == 'first_observed_fv_proxy',
        'reported_cost_absent': number(output.get('cost_reported')) is None and state.get('cost_state') == 'absent',
        'donor_row_link': audit.get('donor_row_id') == donor.get('row_id'),
        'same_snapshot_position': bool(output.get('position_id')) and output.get('position_id') == donor.get('position_id'),
        'same_fund': clean(output.get('cik')) == clean(donor.get('cik')),
        'donor_date_link': audit.get('donor_date') == donor.get('report_date'),
        'same_release': audit.get('donor_release') == release_id,
        'donor_marked_valid': str(donor_state.get('donor_valid')).lower() == 'true',
        'proxy_value_matches': number(output.get('cost')) is not None and
             number(output.get('cost')) == number(audit.get('proxy_value')) == number(donor.get('fair_value')),
        'unique_earliest_valid_donor': earliest.get('candidate_count') == 1 and
             earliest.get('donor_row_id') == donor.get('row_id') and earliest.get('donor_date') == donor.get('report_date'),
    }
    return checks


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--run-root', type=Path, required=True)
    parser.add_argument('--replay', required=True)
    parser.add_argument('--label', required=True)
    args = parser.parse_args()
    repo, run = args.repo.resolve(), args.run_root.resolve()
    if repo == ROOT or not run.is_relative_to(repo / 'data/pilot/jev_screening'):
        raise ValueError('Isolated pilot required')
    if not args.label.replace('_', '').isalnum():
        raise ValueError('Invalid label')
    install_read_only_guard(repo, run)
    _, packets = load_replay(run, args.replay)
    selected = {p['flag']['row_id']: p for p in packets.values()
                if p['output_position'].get('cost_source') == 'first_observed_fv_proxy'}
    if not 1 <= len(selected) <= 6:
        raise ValueError('Expected at most six existing proxy-cost flags')
    paths = {name: repo / 'data/output' / name for name in (
        'private_markets_holdings.csv', 'cost_donor_audit.csv', 'financial_state_audit.csv',
        'identity_contract.json', 'holdings_release.json')}
    hashes = {name: sha(path) for name, path in paths.items()}
    contract, release = read(paths['identity_contract.json']), read(paths['holdings_release.json'])
    for name, key in [('private_markets_holdings.csv', 'holdings_sha256'),
                      ('cost_donor_audit.csv', 'cost_donors_sha256'),
                      ('financial_state_audit.csv', 'field_states_sha256')]:
        if hashes[name] != contract.get(key):
            raise ValueError('Identity contract hash differs: ' + name)
    if (release.get('holdings_sha256') != hashes['private_markets_holdings.csv'] or
            release.get('release_id') != contract.get('release_id')):
        raise ValueError('Release identity mismatch')
    if any(p['provenance']['holdings_sha256'] != hashes['private_markets_holdings.csv'] for p in selected.values()):
        raise ValueError('Holdings changed since pilot freeze')
    print('Reading six or fewer target/donor lineages from cached audit files', flush=True)
    with duckdb.connect(config={'threads': 2, 'memory_limit': '1GB'}) as con:
        audits = records(con.execute('SELECT * FROM read_csv_auto(?,all_varchar=true) WHERE row_id IN (SELECT unnest(?)) LIMIT 7',
                                     [str(paths['cost_donor_audit.csv']), sorted(selected)]))
        if len(audits) != len(selected) or len({a['row_id'] for a in audits}) != len(selected):
            raise ValueError('Missing or duplicate donor audit')
        ids = sorted(set(selected) | {a['donor_row_id'] for a in audits if a.get('donor_row_id')})
        observations = records(con.execute('SELECT * FROM read_csv_auto(?,all_varchar=true) WHERE row_id IN (SELECT unnest(?)) LIMIT 13',
                                           [str(paths['private_markets_holdings.csv']), ids]))
        states = records(con.execute('SELECT * FROM read_csv_auto(?,all_varchar=true) WHERE row_id IN (SELECT unnest(?)) LIMIT 13',
                                     [str(paths['financial_state_audit.csv']), ids]))
        if (len(observations) != len(ids) or len({r['row_id'] for r in observations}) != len(ids)
                or len(states) != len(ids) or len({r['row_id'] for r in states}) != len(ids)):
            raise ValueError('Target/donor rows are not unique and complete')
        by_id, state_by_id = {r['row_id']: r for r in observations}, {r['row_id']: r for r in states}
        positions = sorted({by_id[row_id]['position_id'] for row_id in selected})
        earliest_rows = records(con.execute('''WITH valid AS (
            SELECT h.cik,h.position_id,h.row_id,h.report_date,
                min(TRY_CAST(h.report_date AS DATE)) OVER(PARTITION BY h.cik,h.position_id) AS first_date
            FROM read_csv_auto(?,all_varchar=true) h
            JOIN read_csv_auto(?,all_varchar=true) s USING(row_id)
            WHERE h.position_id IN (SELECT unnest(?)) AND TRY_CAST(s.donor_valid AS BOOLEAN)), earliest AS (
            SELECT * FROM valid WHERE TRY_CAST(report_date AS DATE)=first_date)
            SELECT cik,position_id,count(*) AS candidate_count,min(row_id) AS donor_row_id,
                min(report_date) AS donor_date FROM earliest GROUP BY cik,position_id LIMIT 7''',
            [str(paths['private_markets_holdings.csv']), str(paths['financial_state_audit.csv']), positions]))
    earliest = {(r['cik'], r['position_id']): r for r in earliest_rows}
    results = []
    for audit in audits:
        output, donor = by_id[audit['row_id']], by_id[audit['donor_row_id']]
        for key, value in selected[audit['row_id']]['output_position'].items():
            if clean(value) != clean(output.get(key)):
                raise ValueError('Target differs from frozen bundle: ' + key)
        checks = verify_lineage(output, donor, audit, state_by_id[output['row_id']], state_by_id[donor['row_id']],
                                earliest.get((output['cik'], output['position_id']), {}), contract['release_id'])
        fields = ('row_id', 'cik', 'position_id', 'report_date', 'accession_number', 'issuer_name',
                  'instrument_description', 'bdc_investment_identifier', 'src_context_id',
                  'cost', 'cost_reported', 'cost_source', 'cost_currency', 'fair_value', 'fair_value_currency',
                  'accounting_scope_id', 'accounting_record_class', 'maturity_date')
        results.append({'row_id': output['row_id'], 'output': {k: output.get(k) for k in fields},
                        'donor': {k: donor.get(k) for k in fields}, 'donor_audit': audit,
                        'output_state': state_by_id[output['row_id']], 'donor_state': state_by_id[donor['row_id']],
                        'internal_policy_checks': checks, 'internal_policy_consistent': all(checks.values()),
                        'source_truth_verified': False, 'position_chain_verified': False,
                        'proxy_equals_reported_cost': False, 'route': 'B1', 'jev_eligible': False})
    if any(sha(path) != hashes[name] for name, path in paths.items()):
        raise ValueError('Input changed during lineage build')
    report = {'schema_version': 'jev-b1-cost-lineage.v1', 'source_replay': args.replay,
              'release_id': contract['release_id'], 'input_sha256': hashes,
              'lineage_builder_sha256': sha(Path(__file__)), 'records': results,
              'flags': len(results), 'internally_consistent': sum(r['internal_policy_consistent'] for r in results),
              'production_clearance_enabled': False,
              'limitation': 'Same-snapshot position IDs only. Pipeline audit agreement is not independent source/chain verification or validation of using FV as a cost proxy.'}
    write(run / (args.label + '.json'), report)
    print(json.dumps({k: report[k] for k in ('flags', 'internally_consistent', 'production_clearance_enabled')}), flush=True)


if __name__ == '__main__':
    timer = threading.Timer(90, lambda: os._exit(124))
    timer.daemon = True
    timer.start()
    try:
        main()
    finally:
        timer.cancel()
