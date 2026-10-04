"""Read reported B1 token usage from bounded, hash-verified historical traces."""
import argparse
from collections import Counter
import json
import os
from pathlib import Path
import statistics
import sys
import threading

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from pipeline.jev_screening import fingerprint
from scripts.inventory_jev_rule_workload import CIKS
from scripts.jev_pilot_session import install_read_only_guard, read, sha, write

FIELDS = ('input_tokens', 'cached_input_tokens', 'output_tokens', 'reasoning_output_tokens')


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
    if inventory_path.stat().st_size > 2 * 1024 * 1024:
        raise ValueError('Inventory size limit')
    inventory_hash = sha(inventory_path)
    selected = [r for r in read(inventory_path) if int(r['cik']) in CIKS and r['rule'] in {'C107', 'C104', 'X08'}]
    if len(selected) != 40 or len({r['review_id'] for r in selected}) != len(selected):
        raise ValueError('Expected 40 unique previously inventoried historical groups')
    records = []
    for index, item in enumerate(selected, 1):
        path = (repo / item['trace']).resolve()
        if not path.is_relative_to(repo / 'data/output/agent_b/batch') or path.stat().st_size > 12 * 1024 * 1024:
            raise ValueError('Trace outside bounded historical cache')
        if sha(path) != item['trace_sha256']:
            raise ValueError('Historical trace changed')
        raw = path.read_bytes()
        content = raw.decode('utf-16' if raw.startswith((b'\xff\xfe', b'\xfe\xff')) else 'utf-8-sig')
        events = [json.loads(line) for line in content.splitlines() if line.strip()]
        turns = [e for e in events if e.get('type') == 'turn.completed']
        if len(turns) != 1:
            raise ValueError('Usage requires exactly one completed turn per historical trace')
        usage = turns[0].get('usage', {})
        if any(type(usage.get(k)) is not int or usage[k] < 0 for k in FIELDS):
            raise ValueError('Incomplete or invalid reported usage')
        commands = [e['item'] for e in events if e.get('type') == 'item.completed'
                    and e.get('item', {}).get('type') == 'command_execution']
        records.append({'review_id': item['review_id'], 'cik': item['cik'], 'quarter': item['quarter'],
                        'rule': item['rule'], 'historical_group_issue_count': int(item['n_units']),
                        'initial_excerpt_rows': item['artifact_rows'],
                        'known_partial_coverage': item['known_partial_coverage'],
                        'historical_reference_verdict': item['expected'],
                        'trace_sha256': item['trace_sha256'], 'reported_usage': {k: usage[k] for k in FIELDS},
                        'completed_commands': len(commands),
                        'failed_commands': sum(c.get('exit_code') != 0 for c in commands),
                        'active_seconds': None, 'avoided_work_measured': False})
        if sha(path) != item['trace_sha256']:
            raise ValueError('Trace changed during reading')
        if index % 10 == 0:
            print(f'Historical usage: {index}/40 traces', flush=True)
    if sha(inventory_path) != inventory_hash:
        raise ValueError('Historical inventory changed')
    def stats(rows):
        return {'review_groups': len(rows), 'known_partial_groups': sum(r['known_partial_coverage'] for r in rows),
                'reported_token_totals': {k: sum(r['reported_usage'][k] for r in rows) for k in FIELDS},
                'reported_input_tokens': {'minimum': min(r['reported_usage']['input_tokens'] for r in rows),
                    'median': statistics.median(r['reported_usage']['input_tokens'] for r in rows),
                    'maximum': max(r['reported_usage']['input_tokens'] for r in rows)},
                'completed_commands': sum(r['completed_commands'] for r in rows),
                'failed_commands': sum(r['failed_commands'] for r in rows)}
    report = {'inventory_sha256': inventory_hash, 'selection_rules': ['C104', 'C107', 'X08'],
              'reserved_funds': len(CIKS), 'represented_funds': len({r['cik'] for r in records}),
              'totals': stats(records), 'by_rule': {rule: stats([r for r in records if r['rule'] == rule])
                  for rule in sorted({r['rule'] for r in records})}, 'records': records,
              'api_calls': 0, 'production_changes': 0,
              'limitations': ['Raw usage fields are reported separately; do not sum overlapping token fields or infer an invoice.',
                  'Historical grouped reviews are not the same workload as current per-flag Jev requests.',
                  'No active reviewer time, billed spend or avoided B1 work is measured.',
                  'A reported completed turn or command count is not proof that every group member was reviewed.',
                  'Old reference dispositions are not current independently audited truth.']}
    path = run / ('historical_usage_' + fingerprint(report)[:16] + '.json')
    if not path.exists():
        write(path, report)
    print(json.dumps({'artifact': path.name, 'represented_funds': report['represented_funds'],
                      'totals': report['totals'], 'by_rule': report['by_rule']}), flush=True)


if __name__ == '__main__':
    timer = threading.Timer(90, lambda: os._exit(124))
    timer.daemon = True
    timer.start()
    try:
        main()
    finally:
        timer.cancel()
