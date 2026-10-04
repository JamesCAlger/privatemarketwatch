"""Freeze four paired candidate-order controls without changing source evidence."""
import argparse
from copy import deepcopy
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from pipeline.jev_bundles import make_request
from pipeline.jev_screening import fingerprint
from scripts.build_jev_scale_controls import CASES
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
    parent_dir = run / 'source_identity_probe_15'
    summary = read(parent_dir / 'summary.json')
    if summary['builder_sha256'] != sha(ROOT / 'pipeline/jev_bundles.py'):
        raise ValueError('Replay must use current builder')
    if len(list((run / 'api_attempts').glob('*.started.json'))) + 8 > 100:
        raise ValueError('Insufficient session call budget')
    normal, reverse = run / 'order_normal_packets_01', run / 'order_reverse_packets_01'
    if normal.exists() or reverse.exists():
        raise ValueError('Order controls already frozen')
    references, records, packets = {}, [], []
    for row_id, source_id in CASES:
        parent = read(parent_dir / ('X08_' + row_id + '.json'))
        if parent['evidence_status']['status'] != 'ready_for_model' or len(parent['source_candidates']) < 2:
            raise ValueError('Order control requires ready evidence and multiple candidates')
        candidates = {c['evidence_id']: c for c in parent['source_candidates']}
        if source_id not in candidates or not all(candidates[source_id]['comparisons'][f]['agrees_at_display_precision']
                                                  for f in parent['rule']['fields']):
            raise ValueError('Reviewed reference no longer matches source')
        baseline = deepcopy(parent)
        baseline['provenance']['controlled_mutation'] = {
            'parent_packet': fingerprint(parent), 'kind': 'candidate_order_pair', 'source_evidence_changed': False}
        # Both arms share the same opaque ID and every other model-visible field.
        baseline['bundle_id'] = fingerprint([parent['bundle_id'], 'candidate_order_pair_01'])[:20]
        reversed_packet = deepcopy(baseline)
        reversed_packet['source_candidates'].reverse()
        assert reversed_packet['source_candidates'][::-1] == baseline['source_candidates']
        first, second = make_request(baseline), make_request(reversed_packet)
        assert fingerprint(first) != fingerprint(second)
        for state in (first['state'], second['state']):
            for field in ('source_candidates', 'source_tables', 'source_notes'):
                state[field] = sorted(state[field], key=fingerprint)
        assert first == second
        packets.append((row_id, baseline, reversed_packet))
        references[row_id] = {'expected': 'false_alarm', 'expected_source': source_id,
                              'reference_basis': 'Existing source-reviewed X08 identity and numeric values; presentation-order control, not a new natural observation.',
                              'audit': None}
        records.append({'row_id': row_id, 'source_id': source_id,
                        'candidates': len(parent['source_candidates']),
                        'parent_packet': fingerprint(parent)})
    normal.mkdir()
    reverse.mkdir()
    for row_id, baseline, reversed_packet in packets:
        write(normal / ('X08_' + row_id + '.json'), baseline)
        write(reverse / ('X08_' + row_id + '.json'), reversed_packet)
    write(run / 'order_references_01.json', references)
    write(run / 'order_design_01.json', {'pairs': records, 'maximum_calls': 8,
          'builder_sha256': summary['builder_sha256'], 'natural_flags_added': 0,
          'limitation': 'Small development presentation test. Revised packets have no independent clearance audit.'})
    print(json.dumps({'pairs': len(records), 'maximum_calls': 8}), flush=True)


if __name__ == '__main__':
    main()
