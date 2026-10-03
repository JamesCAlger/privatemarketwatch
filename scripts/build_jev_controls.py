"""Bounded synthetic controls on existing reviewed positions; never natural flags."""
from __future__ import annotations
import argparse
from copy import deepcopy
from pathlib import Path
import sys
import threading
import os

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from pipeline.jev_bundles import SourceCache, build_bundle
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
    target = run / 'controlled_packets_01'
    target.mkdir()
    references = read(run / 'consumed_holdout_references.json')
    selected = ['00530c111921d6cb', '15366053e5d70910', '4d96302bd899ae00', '4ee79f2a3750963b']
    cache = SourceCache(html_cache_dir=repo / 'data/raw/filings/bdc_html')
    builder_hash = sha(ROOT / 'pipeline/jev_bundles.py')
    controls = {}
    for short_id in selected:
        original = read(run / 'holdout_development_02' / ('C107_ROW-' + short_id + '.json'))
        for kind, delta in [('beyond_rounding', -2000), ('within_rounding', -250)]:
            flag, output = deepcopy(original['flag']), deepcopy(original['output_position'])
            original_id = flag['row_id']
            # No truth-bearing suffix reaches the model's identity fields.
            new_id = 'ROW-' + fingerprint([original_id, kind])[:16]
            output.update(row_id=new_id, cost=str(float(output['cost']) + delta))
            flag.update(row_id=new_id, value=output['cost'])
            provenance = {'holdings_sha256': fingerprint(output), 'flags_sha256': fingerprint(flag),
                          'builder_sha256': builder_hash,
                          'controlled_mutation': {'parent_packet': fingerprint(original),
                                                  'field': 'cost', 'delta': delta, 'kind': kind}}
            packet = build_bundle(flag, [output], provenance, cache=cache)
            assert packet['filing']['sha256'] == original['filing']['sha256']
            assert packet['evidence_status']['status'] == 'ready_for_model'
            write(target / ('C107_' + new_id + '.json'), packet)
            controls[new_id] = {'expected': 'real_error' if kind == 'beyond_rounding' else 'false_alarm',
                               'expected_source': references[original_id]['expected_source'],
                               'parent_row_id': original_id, 'mutation': kind, 'delta': delta,
                               'reference_basis': 'Synthetic cost perturbation of source-reviewed development position; not an observed pipeline error.',
                               'audit': None}
            print('Built control:', new_id, kind, flush=True)
    assert sha(ROOT / 'pipeline/jev_bundles.py') == builder_hash
    write(run / 'controlled_references_01.json', controls)


if __name__ == '__main__':
    timer = threading.Timer(180, lambda: os._exit(124))
    timer.daemon = True
    timer.start()
    try:
        main()
    finally:
        timer.cancel()
