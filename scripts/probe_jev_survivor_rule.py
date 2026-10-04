"""Reproduce one existing dedup survivor choice on six frozen rows in memory."""
import argparse
import json
import os
from pathlib import Path
import sys
import threading
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from pipeline.agent_rule import _apply_dedup
from pipeline.jev_screening import fingerprint
from scripts.jev_pilot_session import install_read_only_guard, read, sha, write


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--run-root', type=Path, required=True)
    args = parser.parse_args()
    repo, run = args.repo.resolve(), args.run_root.resolve()
    if repo == ROOT or not run.is_relative_to(repo / 'data/pilot/jev_screening'):
        raise ValueError('Isolated pilot required')
    install_read_only_guard(repo, run)
    modules = ['pipeline/agent_rule.py', 'pipeline/unified_holdings.py']
    for module in modules:
        if (repo / module).read_text(encoding='utf-8-sig') != (ROOT / module).read_text(encoding='utf-8-sig'):
            raise ValueError('Worktree and main mechanism code differ')
    parent_path = run / 'exploratory_context_089f24a29d1a0ec6.json'
    parent = read(parent_path)
    rule_path = repo / 'data/overrides/agent_investigate_rules/1825265/superior-affiliation-axis-dedup-2025q3.json'
    rule = read(rule_path)
    before_hashes = {str(p.relative_to(repo)): sha(p) for p in
                     [rule_path, repo / 'data/output/agent_fix_application_audit.csv', *[repo / m for m in modules]]}
    raw = [r for r in parent['bdc_rows_for_named_issuer_in_accession'] if r['period'] == '2025-09-30']
    if len(raw) != 6 or rule['match_fields'] != ['report_date', 'fair_value'] or rule['keep'] != 'first':
        raise ValueError('Unexpected rule or six-row source set')
    rows = [{'source': 'bdc', 'cik': r['cik'], 'report_date': r['period'],
             'accession_number': r['accession_number'], 'src_context_id': r['src_context_id'],
             'bdc_dimensions_raw': r['dimensions_raw'], 'identifier': r['investment_identifier'],
             'fair_value': float(r['fair_value']), 'cost': float(r['cost']) if r['cost'] else None,
             '_rid': index} for index, r in enumerate(raw)]
    results = []
    for order, records in [('original', rows), ('reversed', list(reversed(rows)))]:
        print('Reproducing dedup survivor order:', order, flush=True)
        surviving, audit = _apply_dedup(pd.DataFrame(records), rule)
        kept = surviving['src_context_id'].tolist()
        results.append({'order': order, 'surviving_contexts': sorted(kept), 'audit': audit})
    if results[0]['surviving_contexts'] != results[1]['surviving_contexts']:
        raise ValueError('Order invariance did not reproduce')
    published_context = parent['published_position']['src_context_id']
    main_context = 'C_f1dd68ce-9df4-4ad8-9279-784ba8aaf308'
    if published_context not in results[0]['surviving_contexts'] or main_context in results[0]['surviving_contexts']:
        raise ValueError('Observed survivor mechanism did not reproduce')
    alternative, alternative_audit = _apply_dedup(pd.DataFrame(rows), {**rule, 'keep': 'last'})
    alternative_rows = alternative.where(pd.notna(alternative), None).to_dict('records')
    alternative_contexts = sorted(alternative['src_context_id'].tolist())
    detailed_contexts = {r['src_context_id'] for r in rows
                         if r['identifier'].startswith(('Debt Investments,', 'Equity Investments,'))}
    if len(detailed_contexts) != 3:
        raise ValueError('Expected three detailed-source candidates')
    main_row = next(r for r in rows if r['src_context_id'] == main_context)
    published_cost = float(parent['published_position']['cost'])
    audit_frame = pd.read_csv(repo / 'data/output/agent_fix_application_audit.csv', dtype=str)
    application = audit_frame[audit_frame['rule_id'].eq(rule['rule_id'])].fillna('').to_dict('records')
    if len(application) != 1:
        raise ValueError('Expected one current application audit')
    if any(sha(repo / path) != value for path, value in before_hashes.items()):
        raise ValueError('Mechanism input changed during probe')
    report = {'parent_sha256': sha(parent_path), 'input_sha256': before_hashes,
              'worktree_module_sha256': {m: sha(ROOT / m) for m in modules},
              'module_text_equal_after_newline_normalization': True,
              'rule': rule, 'reconstructed_candidates': rows, 'results': results,
              'keep_last_counterfactual': {'surviving_contexts': alternative_contexts,
                  'audit': alternative_audit,
                  'detailed_contexts_lost': sorted(detailed_contexts - set(alternative_contexts)),
                  'source_costs_retained': {r['src_context_id']: (None if pd.isna(r['cost']) else r['cost'])
                                           for r in alternative_rows}},
              'keep_first_detailed_contexts_lost': sorted(detailed_contexts - set(results[0]['surviving_contexts'])),
              'current_application_audit': application,
              'main_schedule_cost': main_row['cost'], 'published_proxy_cost': published_cost,
              'cost_difference': main_row['cost'] - published_cost,
              'equal_fair_value': main_row['fair_value'], 'production_changes': 0, 'api_calls': 0,
              'limitation': 'Six-row in-memory applier reproduction, not a full pipeline replay. Candidate mapping uses raw source fields; row_id is absent as at the production correction stage. No rule migration or replacement authorized.'}
    destination = run / ('survivor_rule_probe_' + fingerprint(report)[:16] + '.json')
    if not destination.exists():
        write(destination, report)
    print(json.dumps({'artifact': destination.name, 'cost_difference': report['cost_difference'],
                      'same_survivors_when_reversed': True, 'current_application_audit': application}), flush=True)


if __name__ == '__main__':
    timer = threading.Timer(90, lambda: os._exit(124))
    timer.daemon = True
    timer.start()
    try:
        main()
    finally:
        timer.cancel()
