"""Freeze two later-period C104 cases in one existing fund; no model calls."""
import argparse
from collections import Counter
import json
import os
from pathlib import Path
import sys
import threading
import duckdb

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from pipeline.jev_bundles import SourceCache, build_bundle, parser_runtime
from pipeline.jev_screening import fingerprint
from scripts.compare_jev_retrieval import load_replay
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
    parent_label = 'dependency_bound_v4_55'
    _, parent_packets = load_replay(run, parent_label)
    availability_path = run / 'later_period_availability_101f3a442774baad.json'
    availability = read(availability_path)
    expected_group = {'cik': '0001918712', 'report_date': '2026-03-31', 'rule_id': 'C104', 'flag_count': 35}
    if availability['later_period_groups'] != [expected_group]:
        raise ValueError('Unexpected later-period scope')
    flags_path = repo / 'data/output/row_validation_issues.csv'
    holdings_path = repo / 'data/output/private_markets_holdings.csv'
    flags_hash, holdings_hash = sha(flags_path), sha(holdings_path)
    if flags_hash != availability['issues_sha256']:
        raise ValueError('Flag snapshot changed')
    if {p['provenance']['holdings_sha256'] for p in parent_packets.values()} != {holdings_hash}:
        raise ValueError('Holdings differ from original experiment')
    runtime = parser_runtime()
    target = run / 'later_period_c104_57'
    target.mkdir()
    freeze = {'arm': 'within_filer_later_period_offline_transfer', 'group': expected_group,
              'max_flags': 2, 'new_funds': 0, 'api_calls_allowed': 0,
              'parser_runtime': runtime, 'selection_script_sha256': sha(Path(__file__)),
              'availability_sha256': sha(availability_path), 'parent_replay': parent_label,
              'flags_sha256': flags_hash, 'holdings_sha256': holdings_hash,
              'selection': 'Two lowest md5(jev-c104-transfer-v1|row_id), tie-break row_id; no replacement for blocked evidence.',
              'independent_holdout': False, 'source_inspected_before_freeze': False,
              'limitation': 'Later than metadata boundaries within a familiar filer; not a new-filer or independently adjudicated holdout.'}
    write(target / 'frozen_builder.json', freeze)
    print('Freeze written before source inspection; selecting two of 35 C104 flags', flush=True)
    with duckdb.connect(config={'threads': 2, 'memory_limit': '1GB'}) as con:
        def rows(sql, parameters):
            result = con.execute(sql, parameters)
            names = [c[0] for c in result.description]
            return [dict(zip(names, row)) for row in result.fetchall()]
        group = rows('''SELECT * FROM read_csv(?, all_varchar=true)
            WHERE source='bdc' AND cik='0001918712' AND report_date='2026-03-31' AND rule_id='C104'
            ORDER BY md5('jev-c104-transfer-v1|' || row_id),row_id LIMIT 36''', [str(flags_path)])
        if len(group) != 35 or len({r['row_id'] for r in group}) != 35 or any(not r['row_id'] for r in group):
            raise ValueError('Group membership differs')
        selected = group[:2]
        positions = rows('''SELECT * FROM read_csv(?, all_varchar=true)
            WHERE row_id IN (?,?) LIMIT 5''', [str(holdings_path), *[f['row_id'] for f in selected]])
    if len(positions) != 2 or {r['row_id'] for r in positions} != {f['row_id'] for f in selected}:
        raise ValueError('Output join not unique')
    prior_rows = {p['flag']['row_id'] for p in parent_packets.values()}
    prior_sources = {(p['output_position']['cik'], p['output_position']['accession_number']) for p in parent_packets.values()}
    new_sources = {(p['cik'], p['accession_number']) for p in positions}
    if any(p['row_id'] in prior_rows for p in positions) or len(new_sources) != 1 or new_sources & prior_sources:
        raise ValueError('Expected two new flags from one later filing')
    write(target / 'selection.json', {'freeze_sha256': sha(target / 'frozen_builder.json'),
          'flags': selected, 'holdings_rows': positions, 'group_member_row_ids': sorted(r['row_id'] for r in group),
          'sampled_members': 2, 'group_members': 35, 'unsampled_members': 33,
          'reference_labels': {f['row_id']: None for f in selected}})
    cache = SourceCache(html_cache_dir=repo / 'data/raw/filings/bdc_html')
    cases = []
    for flag in selected:
        provenance = {'flags_sha256': flags_hash, 'holdings_sha256': holdings_hash,
                      'builder_sha256': runtime['builder_sha256'], 'arm': freeze['arm'],
                      'selection_sha256': sha(target / 'selection.json')}
        packet = build_bundle(flag, [p for p in positions if p['row_id'] == flag['row_id']], provenance, cache=cache)
        write(target / ('C104_' + flag['row_id'] + '.json'), packet)
        cases.append({'rule': 'C104', 'row_id': flag['row_id'], 'packet_fingerprint': fingerprint(packet),
                      **packet['evidence_status']})
        print(flag['row_id'], packet['evidence_status']['status'], flush=True)
    if parser_runtime() != runtime or sha(flags_path) != flags_hash or sha(holdings_path) != holdings_hash:
        raise ValueError('Inputs changed during transfer probe')
    summary = {'arm': freeze['arm'], 'builder_sha256': runtime['builder_sha256'],
               'parser_runtime': runtime, 'parser_runtime_sha256': cache.runtime_hash,
               'holdings_sha256': holdings_hash, 'cases': cases,
               'status_counts': dict(Counter(c['status'] for c in cases)),
               'frozen_core_cases': 67, 'additional_offline_cases': 2, 'additional_source_files': 1,
               'api_calls': 0, 'independent_audits': 0, 'production_clearance_enabled': False}
    write(target / 'summary.json', summary)
    print(json.dumps(summary['status_counts']), flush=True)


if __name__ == '__main__':
    timer = threading.Timer(180, lambda: os._exit(124))
    timer.daemon = True
    timer.start()
    try:
        main()
    finally:
        timer.cancel()
