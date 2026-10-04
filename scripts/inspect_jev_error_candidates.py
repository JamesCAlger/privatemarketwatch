"""Compare three historical error groups with current flags without transferring truth labels."""
import argparse
import json
import os
from pathlib import Path
import sys
import threading
import duckdb

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from pipeline.jev_screening import fingerprint
from scripts.build_jev_bundles import read_inputs
from scripts.inspect_jev_historical_coverage import objects
from scripts.jev_pilot_session import install_read_only_guard, read, sha, write

TARGETS = {'RVQ_REV_d01fc72414cb', 'RVQ_REV_2b5ab0f83dc7', 'RVQ_REV_cfa56935ad94'}
ISSUER_TERMS = {'RVQ_REV_d01fc72414cb': ['%HOP Energy%', '%Superior Industries%'],
                'RVQ_REV_2b5ab0f83dc7': ['%HydroSource%', '%HOP Energy%'],
                'RVQ_REV_cfa56935ad94': ['%Alcresta%']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--run-root', type=Path, required=True)
    args = parser.parse_args()
    repo, run = args.repo.resolve(), args.run_root.resolve()
    if repo == ROOT or not run.is_relative_to(repo / 'data/pilot/jev_screening'):
        raise ValueError('Isolated pilot required')
    install_read_only_guard(repo, run)
    inventory_path = repo / 'scratch/2026-10-03_jev_b1_benchmark/inventory_ens2_rest_r3.json'
    inventory = read(inventory_path)
    selected = [r for r in inventory if r['review_id'] in TARGETS]
    if len(selected) != 3 or {r['review_id'] for r in selected} != TARGETS:
        raise ValueError('Expected three historical groups')
    flags_path = repo / 'data/output/row_validation_issues.csv'
    holdings_path = repo / 'data/output/private_markets_holdings.csv'
    hashes = {str(p.relative_to(repo)): sha(p) for p in (inventory_path, flags_path, holdings_path)}
    records = []
    for item in selected:
        if item['cik'] not in {'0001825265', '0001918712'} or item['rule'] not in {'C104', 'X08'}:
            raise ValueError('Outside frozen diagnostic scope')
        print('Inspecting historical error candidate:', item['review_id'], flush=True)
        trace, verdict_path = (repo / item['trace']).resolve(), (repo / item['verdict_path']).resolve()
        if (not trace.is_relative_to(repo / 'data/output/agent_b/batch') or
                not verdict_path.is_relative_to(repo / 'data/output/review_queue/verdicts') or
                trace.stat().st_size > 12 * 1024 * 1024 or verdict_path.stat().st_size > 256 * 1024):
            raise ValueError('Reference bounds exceeded')
        if sha(trace) != item['trace_sha256'] or sha(verdict_path) != item['verdict_sha256']:
            raise ValueError('Reference differs from frozen inventory')
        raw = trace.read_bytes()
        text = raw.decode('utf-16' if raw.startswith((b'\xff\xfe', b'\xfe\xff')) else 'utf-8-sig')
        bundles = []
        for line in text.splitlines():
            if not line.strip():
                continue
            event = json.loads(line)
            command = event.get('item', {})
            if event.get('type') == 'item.completed' and command.get('type') == 'command_execution' and command.get('exit_code') == 0:
                bundles.extend(o for o in objects(command.get('aggregated_output', ''))
                               if o.get('schema_version') == 'review-bundle.v1' and o.get('review_id') == item['review_id'])
        if len(bundles) != 1:
            raise ValueError('Original bundle is not unique')
        evidence = {e['evidence_id']: e.get('data') for e in bundles[0]['evidence_items']}
        old_rows = evidence['source_artifact_rows']
        if len(old_rows) != item['artifact_rows'] or len(old_rows) > 25:
            raise ValueError('Historical excerpt differs')
        flags, matches = read_inputs(flags_path, holdings_path, rules=[item['rule']],
                                    ciks=[item['cik']], quarter=item['quarter'], row_ids=[], limit=50)
        if len(flags) >= 50:
            raise ValueError('Current group may exceed diagnostic limit')
        # Names locate candidates only; do not join unstable historical ordinals.
        with duckdb.connect() as con:
            con.execute("SET memory_limit='1GB'")
            con.execute('SET threads=2')
            terms = ISSUER_TERMS[item['review_id']]
            result = con.execute('SELECT * FROM read_csv(?, all_varchar=true) '
                                 'WHERE source=\'bdc\' AND cik=? AND report_date=? AND (' +
                                 ' OR '.join('issuer_name ILIKE ?' for _ in terms) + ') LIMIT 101',
                                 [str(holdings_path), item['cik'], item['quarter'], *terms])
            columns = [c[0] for c in result.description]
            named_positions = [dict(zip(columns, values)) for values in result.fetchall()]
            if len(named_positions) > 100:
                raise ValueError('Named-position candidate cap exceeded')
        records.append({'historical_metadata': item, 'historical_issue_excerpt': old_rows,
                        'historical_verdict': read(verdict_path), 'current_flags': flags,
                        'current_holdings_matches': dict(matches),
                        'named_current_positions': named_positions,
                        'historical_label_transferred': False})
        if sha(trace) != item['trace_sha256'] or sha(verdict_path) != item['verdict_sha256']:
            raise ValueError('Reference changed during read')
    if any(sha(repo / path) != digest for path, digest in hashes.items()):
        raise ValueError('Input changed during inspection')
    report = {'input_sha256': hashes, 'groups': records, 'api_calls': 0,
              'production_changes': 0, 'new_funds': 0, 'new_evaluation_cases': 0,
              'limitation': 'Candidate investigation only. Historical group verdicts are not current row truth; no source adjudication or new builder evaluation performed.'}
    destination = run / ('historical_error_candidates_' + fingerprint(report)[:16] + '.json')
    if not destination.exists():
        write(destination, report)
    print(json.dumps({'artifact': destination.name,
                      'current_group_counts': {r['historical_metadata']['review_id']: len(r['current_flags']) for r in records}}), flush=True)


if __name__ == '__main__':
    timer = threading.Timer(150, lambda: os._exit(124))
    timer.daemon = True
    timer.start()
    try:
        main()
    finally:
        timer.cancel()
