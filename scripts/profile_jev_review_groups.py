"""Read-only membership accounting for review groups touched by the frozen pilot."""
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
from pipeline.jev_parent_inventory import parent_inventory
from scripts.compare_jev_retrieval import load_replay
from scripts.jev_pilot_session import install_read_only_guard, sha, write


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
    if len(packets) > 100:
        raise ValueError('Frozen packet limit exceeded')
    groups = defaultdict(list)
    for packet in packets.values():
        f = packet['flag']
        groups[(int(f['cik']), f['report_date'], f['rule_id'])].append(packet)
    if len({k[0] for k in groups}) > 16:
        raise ValueError('Reserved fund limit exceeded')
    sources = {'queue': repo / 'data/output/review_queue/review_queue.csv',
               'issues': repo / 'data/output/row_validation_issues.csv'}
    before = {name: sha(path) for name, path in sources.items()}
    records = []
    print(f'Inspecting membership for {len(groups)} existing fund/period/rule groups', flush=True)
    with duckdb.connect(config={'memory_limit': '1GB', 'threads': 2}) as db:
        db.execute('CREATE TEMP TABLE selected(cik BIGINT, report_date VARCHAR, rule_id VARCHAR)')
        db.executemany('INSERT INTO selected VALUES (?, ?, ?)', sorted(groups))
        def query(sql, params, limit):
            result = db.execute(sql, params)
            names = [c[0] for c in result.description]
            rows = result.fetchmany(limit + 1)
            if len(rows) > limit:
                raise ValueError('Bounded group result limit exceeded')
            return [dict(zip(names, row)) for row in rows]
        queue = query('''SELECT q.* FROM read_csv_auto(?, all_varchar=true) q
            JOIN selected s ON TRY_CAST(q.cik AS BIGINT)=s.cik AND q.report_date=s.report_date
                 AND q.rule_name=s.rule_id WHERE q.engine='row_validation' ''', [str(sources['queue'])], 100)
        diagnostic_queue = query('''SELECT q.* FROM read_csv_auto(?, all_varchar=true) q
            JOIN selected s ON TRY_CAST(q.unit_label AS BIGINT)=s.cik
                 AND CAST(TRY_CAST(q.period AS DATE) AS VARCHAR)=s.report_date
                 AND q.rule_name=s.rule_id WHERE q.engine='row_validation' ''', [str(sources['queue'])], 100)
        issues = query('''SELECT TRY_CAST(i.cik AS BIGINT) cik, i.report_date, i.rule_id,
            i.dataset, i.source, i.row_id, i.severity, i.action, i.evidence_strength
            FROM read_csv_auto(?, all_varchar=true) i JOIN selected s
            ON TRY_CAST(i.cik AS BIGINT)=s.cik AND i.report_date=s.report_date AND i.rule_id=s.rule_id''',
            [str(sources['issues'])], 10000)
    for key, members in sorted(groups.items()):
        existing = [r for r in issues if (r['cik'], r['report_date'], r['rule_id']) == key]
        parents = [r for r in queue if (int(r['cik']), r['report_date'], r['rule_name']) == key]
        diagnostic_parents = [r for r in diagnostic_queue if
            (int(r['unit_label']), r['period'][:10], r['rule_name']) == key]
        frozen_ids = {p['flag']['row_id'] for p in members}
        current_ids = {r['row_id'] for r in existing if r['dataset']=='private_markets_holdings'
                       and r['source']=='bdc' and r['row_id']}
        missing_ids = sorted(frozen_ids - current_ids)
        out_of_scope = [r for r in existing if r['dataset']!='private_markets_holdings'
                        or r['source']!='bdc' or not r['row_id']]
        all_selected = bool(existing) and not missing_ids and not out_of_scope and current_ids <= frozen_ids
        count_consistent = len(parents)==1 and int(parents[0]['n_units'])==len(existing)
        records.append({'cik': key[0], 'report_date': key[1], 'rule_id': key[2],
            'frozen_members': len(members), 'current_issue_rows': len(existing),
            'current_identified_bdc_members': len(current_ids), 'unselected_members': len(current_ids-frozen_ids),
            'frozen_ids_missing_from_current_issues': missing_ids,
            'unidentified_or_other_dataset_rows': len(out_of_scope),
            'all_current_members_selected': all_selected, 'queue_count_consistent': count_consistent,
            'all_selected_evidence_ready': all(p['evidence_status']['status']=='ready_for_model' for p in members),
            'parent_queue_items': parents, 'diagnostic_date_normalized_queue_items': diagnostic_parents,
            'diagnostic_queue_count_consistent': len(diagnostic_parents)==1 and
                int(diagnostic_parents[0]['n_units'])==len(existing), 'b1_work_suppressed': False})
    if {name: sha(path) for name, path in sources.items()} != before:
        raise ValueError('Read-only inputs changed')
    counts = {'groups': len(records), 'frozen_flags': len(packets),
        'fully_selected_groups': sum(r['all_current_members_selected'] for r in records),
        'fully_selected_evidence_ready_before_queue_binding': sum(r['all_current_members_selected'] and
            r['all_selected_evidence_ready'] for r in records),
        'fully_selected_and_evidence_ready': sum(r['all_current_members_selected'] and
            r['all_selected_evidence_ready'] and r['queue_count_consistent'] for r in records),
        'queue_count_mismatches_or_absent': sum(not r['queue_count_consistent'] for r in records),
        'diagnostic_date_normalized_matches': len(diagnostic_queue),
        'diagnostic_count_consistent': sum(r['diagnostic_queue_count_consistent'] for r in records)}
    review_ids = defaultdict(list)
    for r in diagnostic_queue:
        review_ids[r['review_id']].append({'unit_label': r['unit_label'], 'period': r['period'], 'rule': r['rule_name']})
    try:
        parent_inventory(diagnostic_queue, issues, queue_sha256=before['queue'], issues_sha256=before['issues'])
        inventory_preflight = {'status': 'accepted'}
    except ValueError as exc:
        inventory_preflight = {'status': 'rejected', 'reason': str(exc)}
    report = {'replay': args.replay, 'input_sha256': before, 'counts': counts, 'groups': records,
        'diagnostic_repeated_review_ids': {k: v for k, v in review_ids.items() if len(v)>1},
        'unmodified_queue_inventory_preflight': inventory_preflight,
        'inventory_helper_sha256': sha(ROOT / 'pipeline/jev_parent_inventory.py'),
        'api_calls': 0, 'production_changes': 0,
        'limitation': 'Date normalization is diagnostic only, not a certified parent join. No model/audit certification, B1 job savings or queue filtering.'}
    destination = run / ('review_group_profile_' + fingerprint(report)[:16] + '.json')
    if not destination.exists():
        write(destination, report)
    print(json.dumps({'artifact': destination.name, **counts}), flush=True)


if __name__ == '__main__':
    timer = threading.Timer(150, lambda: os._exit(124))
    timer.daemon = True
    timer.start()
    try:
        main()
    finally:
        timer.cancel()
