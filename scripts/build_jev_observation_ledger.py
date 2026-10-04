"""Account for flags, model calls, repeats and synthetic controls separately."""
import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from pipeline.jev_screening import fingerprint
from scripts.compare_jev_bundle_versions import NATURAL_RUNS
from scripts.compare_jev_retrieval import load_replay
from scripts.jev_pilot_session import install_read_only_guard, read, sha, write
from scripts.run_jev_screening import validate_response

RUNS = {**{label: 'natural_first_call' for label in NATURAL_RUNS},
        'controlled_model_01': 'synthetic_numeric_control',
        'sibling_model_01': 'synthetic_numeric_control',
        'scale_model_01': 'synthetic_numeric_control',
        'order_normal_model_01': 'presentation_variant',
        'order_reverse_model_01': 'presentation_variant',
        'order_repeat_model_01': 'exact_request_repeat',
        'current_development_model_01': 'current_builder_recheck',
        'current_consumed_model_01': 'current_builder_recheck',
        'note_stress_model_01': 'synthetic_note_stress',
        'zero_control_model_01': 'synthetic_zero_control'}


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
    replay, natural = load_replay(run, args.replay)
    if len(natural) != 67:
        raise ValueError('Expected frozen 67-flag scope')
    rows, seen, by_flag = [], set(), defaultdict(list)
    for label, category in RUNS.items():
        directory = run / label
        manifest = read(directory / 'manifest.json')
        refs_path = directory / 'references.json'
        if len(manifest['records']) > 50:
            raise ValueError('References changed or manifest exceeds limit')
        refs = {}
        if category == 'exact_request_repeat':
            for parent in manifest['parents']:
                if RUNS.get(parent['run']) != 'presentation_variant':
                    raise ValueError('Unexpected repeat parent')
                parent_dir = run / parent['run']
                if sha(parent_dir / 'manifest.json') != parent['manifest_sha256']:
                    raise ValueError('Repeat parent manifest changed')
                parent_manifest = read(parent_dir / 'manifest.json')
                if sha(parent_dir / 'references.json') != parent_manifest['references_sha256']:
                    raise ValueError('Repeat parent references changed')
        else:
            if sha(refs_path) != manifest['references_sha256']:
                raise ValueError('References changed')
            refs = read(refs_path)
        for record in manifest['records']:
            request_id = record['request_id']
            attempt_id = record.get('attempt_id', request_id)
            receipt_path = run / 'api_attempts' / (str(attempt_id) + '.result.json')
            if not request_id or not receipt_path.exists():
                continue
            if category == 'exact_request_repeat' and sha(run / 'api_attempts' / (request_id + '.result.json')) != record['parent_receipt_sha256']:
                raise ValueError('Repeat parent receipt changed')
            if attempt_id in seen:
                raise ValueError('An attempt is assigned to multiple experiment arms')
            seen.add(attempt_id)
            packet = read(directory / 'packets' / (record['packet_id'] + '.json'))
            request = read(directory / 'requests' / (request_id + '.json'))
            receipt = read(receipt_path)
            if fingerprint(packet) != record['packet_id'] or fingerprint(request) != request_id:
                raise ValueError('Frozen request or packet changed')
            if receipt['request_id'] != request_id or receipt['bundle_fingerprint'] != record['packet_id']:
                raise ValueError('Receipt does not belong to frozen request')
            row_id, rule = record['flag']['row_id'], record['flag']['rule_id']
            synthetic = category.startswith('synthetic_')
            parent_id = refs[row_id].get('parent_row_id') if synthetic else row_id
            key = (rule, parent_id)
            if key not in natural:
                raise ValueError('Observation parent is outside frozen natural selection')
            if receipt['status'] == 'success':
                validate_response(receipt['response'], request)
            tokens = receipt.get('response', {}).get('usage', {}).get('input_tokens', 0)
            item = {'run': label, 'category': category, 'attempt_id': attempt_id,
                    'request_id': request_id, 'row_id': row_id, 'rule': rule,
                    'parent_natural_row_id': parent_id, 'synthetic': synthetic,
                    'status': receipt['status'], 'input_tokens': tokens}
            rows.append(item)
            by_flag[key].append(item)
    started = {p.name.removesuffix('.started.json') for p in (run / 'api_attempts').glob('*.started.json')}
    results = {p.name.removesuffix('.result.json') for p in (run / 'api_attempts').glob('*.result.json')}
    if not started == results == seen or len(seen) > 100:
        raise ValueError('Unassigned, unfinished or over-budget attempt; do not publish complete accounting')
    flags = []
    for key, packet in sorted(natural.items()):
        observations = by_flag[key]
        calls = [r for r in observations if not r['synthetic']]
        flags.append({'rule': key[0], 'row_id': key[1], 'cik': packet['flag']['cik'],
                      'period': packet['flag']['report_date'], 'action': packet['flag']['action'],
                      'current_readiness': packet['evidence_status']['status'],
                      'natural_or_presentation_calls': len(calls),
                      'synthetic_child_calls': len(observations) - len(calls),
                      'attempt_ids': [r['attempt_id'] for r in observations]})
    report = {'selected_natural_flags': len(flags), 'represented_funds': len({f['cik'] for f in flags}),
              'unique_natural_flags_called': sum(f['natural_or_presentation_calls'] > 0 for f in flags),
              'natural_flags_never_called': sum(f['natural_or_presentation_calls'] == 0 for f in flags),
              'all_calls': len(rows), 'calls_by_category': dict(Counter(r['category'] for r in rows)),
              'input_tokens': sum(r['input_tokens'] for r in rows),
              'all_attempts_accounted_for': True, 'current_replay': args.replay,
              'builder_sha256': replay['builder_sha256'], 'flags': flags, 'observations': rows,
              'audited_clearances': 0, 'production_clearance_enabled': False,
              'limitations': ['Repeat, presentation and revised-bundle calls are not new natural flags.',
                  'Synthetic child calls do not count as naturally observed errors or additional flags.',
                  'Current readiness is separate from the version under which historical calls were scored.']}
    destination = run / ('observation_ledger_' + fingerprint(report)[:16] + '.json')
    if not destination.exists():
        write(destination, report)
    print(json.dumps({k: v for k, v in report.items() if k not in {'flags', 'observations', 'limitations'}}), flush=True)


if __name__ == '__main__':
    main()
