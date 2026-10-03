"""Freeze paired sibling-value lures using four existing reviewed C107 cases."""
import argparse
from copy import deepcopy
from decimal import Decimal
import os
from pathlib import Path
import sys
import threading

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from pipeline.jev_bundles import SourceCache, build_bundle
from pipeline.jev_screening import fingerprint
from scripts.jev_pilot_session import install_read_only_guard, read, sha, write

CASES = [
    ('explicit_notes_06', 'ROW-07cc1bd2c9b66a04', 't12r27', 't12r26'),
    ('explicit_notes_06', 'ROW-54bec5b9be81ee4d', 't12r6', 't12r7'),
    ('holdout_development_06', 'ROW-15366053e5d70910', 't55r29', 't55r36'),
    ('holdout_development_06', 'ROW-4d96302bd899ae00', 't18r31', 't18r34'),
]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--run-root', type=Path, required=True)
    args = parser.parse_args()
    repo, run = args.repo.resolve(), args.run_root.resolve()
    if repo == ROOT or not run.is_relative_to(repo / 'data/pilot/jev_screening'):
        raise ValueError('Isolated pilot required')
    install_read_only_guard(repo, run)
    target = run / 'sibling_control_packets_01'
    target.mkdir()
    cache = SourceCache(html_cache_dir=repo / 'data/raw/filings/bdc_html')
    builder_hash = sha(ROOT / 'pipeline/jev_bundles.py')
    references = {}
    for directory, row_id, source_id, lure_id in CASES:
        original = read(run / directory / ('C107_' + row_id + '.json'))
        candidates = {c['evidence_id']: c for c in original['source_candidates']}
        source_cost = Decimal(candidates[source_id]['comparisons']['cost']['source_amount'])
        lure_cost = Decimal(candidates[lure_id]['comparisons']['cost']['source_amount'])
        assert source_cost < 0 and lure_cost < 0 and abs(source_cost - lure_cost) > 1000
        for kind, amount in [('unchanged_pair', original['output_position']['cost']),
                             ('sibling_value_lure', str(lure_cost))]:
            flag, output = deepcopy(original['flag']), deepcopy(original['output_position'])
            new_id = 'ROW-' + fingerprint([row_id, 'sibling_01', kind])[:16]
            output.update(row_id=new_id, cost=amount)
            flag.update(row_id=new_id, value=amount)
            provenance = {'holdings_sha256': fingerprint(output), 'flags_sha256': fingerprint(flag),
                          'builder_sha256': builder_hash,
                          'controlled_mutation': {'parent_packet': fingerprint(original),
                                                  'field': 'cost', 'kind': kind,
                                                  'lure_source_id': lure_id}}
            packet = build_bundle(flag, [output], provenance, cache=cache)
            assert packet['filing']['sha256'] == original['filing']['sha256']
            assert packet['evidence_status']['status'] == 'ready_for_model'
            rebuilt = {c['evidence_id']: c for c in packet['source_candidates']}
            assert source_id in rebuilt and lure_id in rebuilt
            assert Decimal(rebuilt[source_id]['comparisons']['cost']['source_amount']) == source_cost
            write(target / ('C107_' + new_id + '.json'), packet)
            references[new_id] = {
                'expected': 'real_error' if kind == 'sibling_value_lure' else 'false_alarm',
                'expected_source': source_id, 'parent_row_id': row_id,
                'mutation': kind, 'lure_source_id': lure_id,
                'reference_basis': 'Synthetic paired control; cost borrowed from another source row while position identity is unchanged. Not a natural pipeline error.',
                'audit': None}
            print('Built sibling control:', new_id, kind, flush=True)
    assert sha(ROOT / 'pipeline/jev_bundles.py') == builder_hash
    write(run / 'sibling_control_references_01.json', references)


if __name__ == '__main__':
    timer = threading.Timer(180, lambda: os._exit(124))
    timer.daemon = True
    timer.start()
    try:
        main()
    finally:
        timer.cancel()
