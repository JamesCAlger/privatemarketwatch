"""Inspect existing validation/reconciliation records for four frozen overlap cases."""
import argparse
import json
import os
from pathlib import Path
import sys
import threading

import duckdb

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from pipeline.jev_bundles import number
from pipeline.jev_screening import fingerprint
from scripts.compare_jev_retrieval import load_replay
from scripts.jev_pilot_session import install_read_only_guard, sha, write

TARGETS = {'ROW-54bec5b9be81ee4d', 'ROW-96818d4e9b1777d0', 'ROW-1e319095e85a0c34', 'ROW-24cf5e7b72e10c93'}


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
    selected = {p['flag']['row_id']: p for p in packets.values() if p['flag']['row_id'] in TARGETS}
    if set(selected) != TARGETS:
        raise ValueError('Expected four frozen flags')
    files = {name: repo / 'data/output' / (name + '.csv')
             for name in ('row_validation_issues', 'source_reconciliation_detail')}
    before = {name: sha(path) for name, path in files.items()}
    print('Inspecting four frozen rows in existing validation and reconciliation files', flush=True)
    with duckdb.connect(config={'memory_limit': '1GB', 'threads': 2}) as db:
        def records(sql, params):
            result = db.execute(sql, params)
            names = [c[0] for c in result.description]
            return [dict(zip(names, row)) for row in result.fetchall()]
        flags = records('''SELECT row_id, rule_id, severity, evidence_strength, action, "column", value, message
            FROM read_csv_auto(?, all_varchar=true)
            WHERE row_id IN (SELECT UNNEST(?)) AND dataset='private_markets_holdings' AND source='bdc'
            ORDER BY row_id, rule_id LIMIT 101''', [str(files['row_validation_issues']), sorted(TARGETS)])
        source = records('''SELECT output_row_id, status, match_tier, residual_class, blocking_issue,
            calibrated_status, calibration_reason, mismatched_fields, context_id,
            source_fair_value, output_fair_value, source_cost, output_cost,
            source_principal_amount, output_principal_amount, asset_category, issuer_category,
            source_wrapper_disposition, output_wrapper_disposition
            FROM read_csv_auto(?, all_varchar=true)
            WHERE output_row_id IN (SELECT UNNEST(?)) ORDER BY output_row_id LIMIT 5''',
            [str(files['source_reconciliation_detail']), sorted(TARGETS)])
        if len(flags) > 100 or len(source) != 4 or {r['output_row_id'] for r in source} != TARGETS:
            raise ValueError('Unexpected validation/reconciliation cardinality')
        for row in source:
            output = selected[row['output_row_id']]['output_position']
            if any(number(row['output_' + f]) != number(output[f]) for f in ('cost', 'fair_value')):
                raise ValueError('Reconciliation output differs from frozen case')
        # Preserve the operator arrangement seen in the production SQL builder.
        # These booleans stand in for its three mismatch predicates, not a replay
        # of the full source-reconciliation job.
        precedence_probe = records('''SELECT cost_diff, principal_diff, shares_diff,
            CASE WHEN cost_diff OR principal_diff OR shares_diff AND asset='equity' AND fields LIKE '%principal_amount%'
                 THEN 'equity_principal_reason' ELSE 'secondary_field_reason' END original_reason_branch,
            CASE WHEN (cost_diff OR principal_diff OR shares_diff) AND asset='equity' AND fields LIKE '%principal_amount%'
                 THEN 'equity_principal_reason' ELSE 'secondary_field_reason' END parenthesized_reason_branch
            FROM (VALUES (true,false,false,'loan','cost'),
                         (false,true,false,'loan','principal_amount'),
                         (false,true,false,'equity','principal_amount'),
                         (false,false,true,'loan','shares_held'))
                 probe(cost_diff, principal_diff, shares_diff, asset, fields)''', [])
    if {name: sha(path) for name, path in files.items()} != before:
        raise ValueError('Read-only inputs changed')
    module = repo / 'pipeline/source_reconciliation.py'
    module_text = module.read_text(encoding='utf-8')
    if ('diagnostic_mismatch_expr = " OR ".join(' not in module_text or
            "WHEN {diagnostic_mismatch_expr}\n                         AND lower(COALESCE(o.asset_category, '')) LIKE 'equity%'" not in module_text):
        raise ValueError('Expected SQL mechanism changed; do not publish probe against it')
    report = {'replay': args.replay, 'row_ids': sorted(TARGETS), 'input_sha256': before,
        'source_reconciliation_module_sha256': sha(module), 'existing_flags': flags,
        'existing_reconciliation': source, 'sql_reason_precedence_probe': precedence_probe,
        'production_changes': 0, 'api_calls': 0,
        'limitations': ['Exact-source matching does not establish unique economic exposure across source schedules.',
            'Possible presentation overlap remains unresolved; no deduplication or target sum is certified.',
            'The SQL probe reproduces reason-branch precedence only, not a complete historical reconciliation build.']}
    destination = run / ('overlap_routing_' + fingerprint(report)[:16] + '.json')
    if not destination.exists():
        write(destination, report)
    print(json.dumps({'artifact': destination.name, 'existing_flags': flags,
        'existing_reconciliation': source, 'sql_reason_precedence_probe': precedence_probe}), flush=True)


if __name__ == '__main__':
    timer = threading.Timer(150, lambda: os._exit(124))
    timer.daemon = True
    timer.start()
    try:
        main()
    finally:
        timer.cancel()
