"""Paired X08 scale-error controls on four already source-reviewed positions."""
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

CASES = [('ROW-0d749c119e46277b', 't34r16'), ('ROW-3d415c265ff85a7b', 't38r6'),
         ('ROW-1c2a72c58fbc2d87', 't13r24'), ('ROW-f9392efe09fe5877', 't33r22')]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--run-root', type=Path, required=True)
    args = parser.parse_args()
    repo, run = args.repo.resolve(), args.run_root.resolve()
    if repo == ROOT or not run.is_relative_to(repo / 'data/pilot/jev_screening'):
        raise ValueError('Isolated pilot required')
    install_read_only_guard(repo, run)
    target = run / 'scale_control_packets_01'
    target.mkdir()
    cache = SourceCache(html_cache_dir=repo / 'data/raw/filings/bdc_html')
    builder_hash = sha(ROOT / 'pipeline/jev_bundles.py')
    references = {}
    for row_id, source_id in CASES:
        original = read(run / 'clearance_audit_packets_01' / ('X08_' + row_id + '.json'))
        for kind, divisor in [('unchanged_pair', 1), ('fv_scale_error', 1000)]:
            flag, output = deepcopy(original['flag']), deepcopy(original['output_position'])
            new_id = 'ROW-' + fingerprint([row_id, 'scale_01', kind])[:16]
            output.update(row_id=new_id, fair_value=str(Decimal(output['fair_value']) / divisor))
            # X08's flagged column is cost, which is unchanged.
            flag.update(row_id=new_id)
            provenance = {'holdings_sha256': fingerprint(output), 'flags_sha256': fingerprint(flag),
                          'builder_sha256': builder_hash,
                          'controlled_mutation': {'parent_packet': fingerprint(original),
                                                  'field': 'fair_value', 'kind': kind, 'divisor': divisor}}
            packet = build_bundle(flag, [output], provenance, cache=cache)
            assert packet['filing']['sha256'] == original['filing']['sha256']
            assert packet['evidence_status']['status'] == 'ready_for_model'
            candidates = {c['evidence_id']: c for c in packet['source_candidates']}
            comparison = candidates[source_id]['comparisons']['fair_value']
            assert comparison['agrees_at_display_precision'] is (divisor == 1)
            write(target / ('X08_' + new_id + '.json'), packet)
            references[new_id] = {
                'expected': 'real_error' if divisor != 1 else 'false_alarm',
                'expected_source': source_id, 'parent_row_id': row_id, 'mutation': kind,
                'reference_basis': 'Synthetic 1000x output FV scale error with intact source evidence; not a natural pipeline error.',
                'audit': None}
            print('Built scale control:', new_id, kind, flush=True)
    assert sha(ROOT / 'pipeline/jev_bundles.py') == builder_hash
    write(run / 'scale_control_references_01.json', references)


if __name__ == '__main__':
    timer = threading.Timer(180, lambda: os._exit(124))
    timer.daemon = True
    timer.start()
    try:
        main()
    finally:
        timer.cancel()
