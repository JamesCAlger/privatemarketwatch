"""Check the full candidate delta before submitting paired synthetic C104 controls."""
import argparse
from copy import deepcopy
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
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
    design = read(run / 'zero_control_design_44.json')
    packets = {}
    for item in design['cases']:
        packet = read(run / 'zero_control_packets_44' / ('C104_' + item['row_id'] + '.json'))
        if fingerprint(packet) != item['packet_fingerprint'] or sha(Path(packet['filing']['path'])) != item['source_sha256']:
            raise ValueError('Frozen packet or source changed')
        packets[item['kind']] = packet
    if set(packets) != {'disclosed_zero', 'missed_positive_fv'}:
        raise ValueError('Unexpected paired controls')
    parent = read(run / 'rate_note_scope_v4_42' / ('C104_' + design['parent_row_id'] + '.json'))
    baseline, error = packets['disclosed_zero'], packets['missed_positive_fv']
    if baseline['source_candidates'] != parent['source_candidates']:
        raise ValueError('Baseline source evidence differs from original')
    project = lambda p: {k: v for k, v in p['output_position'].items() if k != 'row_id'}
    if not project(parent) == project(baseline) == project(error):
        raise ValueError('Published position changed beyond synthetic ID')
    old, altered = baseline['source_candidates'][0], deepcopy(error['source_candidates'][0])
    context_targets = [r for r in altered['context_rows'] if r['row_index'] == altered['row_index']]
    if len(context_targets) != 1 or context_targets[0]['cells'] != altered['raw_cells']:
        raise ValueError('Target context copy must exactly match the altered raw row')
    context_targets[0]['cells'] = deepcopy(old['raw_cells'])
    value = altered['source_values']['fair_value']
    if (value['amount'], value['currency'], value['display_unit'], value['blocking_reasons']) != ('1000', 'USD', '1000', []):
        raise ValueError('Expected exactly USD 1000 at unchanged display precision')
    cells = [c for c in altered['raw_cells'] if c['column'] == 12]
    if len(cells) != 1 or cells[0]['text'] != '1' or len(cells[0]['inline_facts']) != 1:
        raise ValueError('Expected one altered numeric cell')
    cell = cells[0]
    if cell['inline_facts'][0]['text'] != '1' or cell['inline_facts'][0]['format'] != 'ixt:num-dot-decimal':
        raise ValueError('Unexpected transform or fact payload')
    cell['text'] = '\u2014'
    cell['inline_facts'][0]['text'] = '\u2014'
    cell['inline_facts'][0]['format'] = 'ixt:fixed-zero'
    altered['source_values']['fair_value'] = deepcopy(old['source_values']['fair_value'])
    altered['comparisons']['fair_value'] = deepcopy(old['comparisons']['fair_value'])
    if altered != old:
        raise ValueError('Candidate changed beyond the intended FV cell and comparison: '
                         + str([k for k in set(altered) | set(old) if altered.get(k) != old.get(k)]))
    report = {'controls': 2, 'full_candidate_delta_verified': True,
        'unrelated_source_evidence_unchanged': True, 'published_values_unchanged': True,
        'design_sha256': sha(run / 'zero_control_design_44.json'),
        'api_calls': 0, 'independent_audit': False, 'production_clearance_enabled': False}
    write(run / 'zero_control_verified_44.json', report)
    print(json.dumps(report), flush=True)


if __name__ == '__main__':
    main()
