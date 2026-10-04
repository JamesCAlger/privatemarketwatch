"""Inspect three known partial B1 references within the existing fund reservation."""
import argparse
from collections import Counter
import json
import os
from pathlib import Path
import re
import sys
import threading

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from pipeline.jev_screening import fingerprint
from scripts.inventory_jev_rule_workload import CIKS
from scripts.jev_pilot_session import install_read_only_guard, sha, write

TARGETS = {'RVQ_REV_ccd366f14e46', 'RVQ_REV_6d7c7704ecee', 'RVQ_REV_0a39a3b68c74'}


def objects(text):
    decoder = json.JSONDecoder()
    for match in re.finditer(r'(?m)^\s*\{', text):
        try:
            value, _ = decoder.raw_decode(text[match.start():].lstrip())
            if isinstance(value, dict):
                yield value
        except ValueError:
            pass


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
    raw = inventory_path.read_bytes()
    inventory = json.loads(raw)
    selected = [r for r in inventory if int(r['cik']) in CIKS and r['rule'] in {'C107', 'C104', 'X08'}]
    if len(selected) > 100:
        raise ValueError('Historical selection cap')
    partial = [r for r in selected if r['review_id'] in TARGETS]
    if {r['review_id'] for r in partial} != TARGETS:
        raise ValueError('Expected three known partial references')
    records = []
    for item in partial:
        print('Inspecting historical reference:', item['review_id'], flush=True)
        trace, verdict_path = (repo / item['trace']).resolve(), (repo / item['verdict_path']).resolve()
        if (not trace.is_relative_to(repo / 'data/output/agent_b/batch') or
                not verdict_path.is_relative_to(repo / 'data/output/review_queue/verdicts') or
                trace.stat().st_size > 12 * 1024 * 1024 or verdict_path.stat().st_size > 256 * 1024):
            raise ValueError('Historical source bounds')
        if sha(trace) != item['trace_sha256'] or sha(verdict_path) != item['verdict_sha256']:
            raise ValueError('Historical reference changed since inventory')
        data = trace.read_bytes()
        text = data.decode('utf-16' if data.startswith((b'\xff\xfe', b'\xfe\xff')) else 'utf-8-sig')
        events = [json.loads(line) for line in text.splitlines() if line.strip()]
        completed = [e.get('item', {}) for e in events if e.get('type')=='item.completed']
        bundles = []
        for event in completed:
            if event.get('type')=='command_execution' and event.get('exit_code')==0:
                bundles.extend(o for o in objects(event.get('aggregated_output', ''))
                    if o.get('schema_version')=='review-bundle.v1' and o.get('review_id')==item['review_id'])
        if len(bundles)!=1:
            raise ValueError('Original bundle not uniquely identified')
        evidence = {e['evidence_id']: e.get('data') for e in bundles[0]['evidence_items']}
        flags = evidence['flag']
        artifact_rows = evidence['source_artifact_rows']
        if int(flags['n_units']) != int(item['n_units']) or len(artifact_rows)!=item['artifact_rows']:
            raise ValueError('Original coverage does not match frozen inventory')
        messages = [e.get('text', '') for e in completed if e.get('type')=='agent_message']
        verdict = json.loads(verdict_path.read_bytes())
        if not messages or verdict.get('verdict') != item['expected']:
            raise ValueError('Historical disposition changed')
        final = messages[-1]
        if len(final)>12000:
            raise ValueError('Final-message cap')
        records.append({'metadata': item, 'original_flag': flags,
            'original_artifact_rows': len(artifact_rows),
            'original_final': final, 'verdict_rationale': verdict.get('rationale'),
            'unrepresented_issue_rows_in_initial_bundle': int(flags['n_units'])-len(artifact_rows),
            'whole_group_gold_certified': False})
        if sha(trace) != item['trace_sha256'] or sha(verdict_path) != item['verdict_sha256']:
            raise ValueError('Historical source changed during inspection')
    counts = {rule: {'review_items': sum(r['rule']==rule for r in selected),
                    'known_partial': sum(r['rule']==rule and r['known_partial_coverage'] for r in selected),
                    'excerpt_smaller_than_group': sum(r['rule']==rule and int(r['artifact_rows'])<int(r['n_units']) for r in selected)}
              for rule in sorted({r['rule'] for r in selected})}
    report = {'inventory_sha256': sha(inventory_path), 'reserved_funds': len(CIKS),
        'historical_review_items': len(selected), 'by_rule': counts, 'inspected_partial_references': records,
        'api_calls': 0, 'production_changes': 0,
        'limitations': ['Historical review items are grouped references, not additional natural classifier test flags.',
            'An initial excerpt count alone does not measure all source rows investigated later.',
            'Partial-coverage wording is a known limitation; its absence is not proof of complete review.',
            'These references are not independently audited gold and do not bind current rebuilt holdings.']}
    destination = run / ('historical_coverage_' + fingerprint(report)[:16] + '.json')
    if not destination.exists():
        write(destination, report)
    print(json.dumps({'artifact': destination.name, 'historical_review_items': len(selected), 'by_rule': counts}), flush=True)


if __name__ == '__main__':
    timer = threading.Timer(90, lambda: os._exit(124))
    timer.daemon = True
    timer.start()
    try:
        main()
    finally:
        timer.cancel()
