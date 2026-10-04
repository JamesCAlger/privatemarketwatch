"""Descriptive confidence sensitivity by experiment arm; never fit a cutoff."""
import argparse
from collections import Counter
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from pipeline.jev_screening import fingerprint
from scripts.jev_pilot_session import install_read_only_guard, read, sha, write
from scripts.run_jev_screening import decode_observation


def sweep(rows, decision_cutoff, source_cutoff):
    selected = [r for r in rows if r['decision'] == 'false_alarm'
                and r['source'] != 'insufficient_evidence'
                and r['decision_confidence'] >= decision_cutoff
                and r['source_confidence'] >= source_cutoff]
    return {'decision_cutoff': decision_cutoff, 'source_cutoff': source_cutoff,
        'calls': len(rows), 'confidence_candidates': len(selected),
        'candidate_reference_classes': dict(Counter(r['expected'] for r in selected)),
        'candidate_wrong_source': sum(r['source'] != r['expected_source'] for r in selected),
        'candidate_attempt_ids': [r['attempt_id'] for r in selected]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--run-root', type=Path, required=True)
    parser.add_argument('--ledger', required=True)
    args = parser.parse_args()
    repo, run = args.repo.resolve(), args.run_root.resolve()
    if repo == ROOT or not run.is_relative_to(repo / 'data/pilot/jev_screening'):
        raise ValueError('Isolated pilot required')
    install_read_only_guard(repo, run)
    ledger_path = run / args.ledger
    if ledger_path.parent != run:
        raise ValueError('Ledger must be in run root')
    ledger = read(ledger_path)
    if ledger_path.name != 'observation_ledger_' + fingerprint(ledger)[:16] + '.json':
        raise ValueError('Ledger fingerprint mismatch')
    if not ledger['all_attempts_accounted_for'] or len(ledger['observations']) > 100:
        raise ValueError('Incomplete or excessive observations')
    rows = []
    for item in ledger['observations']:
        directory = run / item['run']
        manifest = read(directory / 'manifest.json')
        records = [r for r in manifest['records']
                   if r.get('attempt_id', r['request_id']) == item['attempt_id']]
        if len(records) != 1:
            raise ValueError('Attempt not uniquely bound to manifest')
        record = records[0]
        packet = read(directory / 'packets' / (record['packet_id'] + '.json'))
        if fingerprint(packet) != record['packet_id']:
            raise ValueError('Packet changed')
        request = read(directory / 'requests' / (record['request_id'] + '.json'))
        receipt_path = run / 'api_attempts' / (item['attempt_id'] + '.result.json')
        receipt = read(receipt_path)
        if decode_observation(receipt, record, request)['status'] != 'success':
            raise ValueError('Unsuccessful or invalid observation')
        ref_directory = run / record['parent_run'] if item['category'] == 'exact_request_repeat' else directory
        ref_manifest = read(ref_directory / 'manifest.json')
        ref_path = ref_directory / 'references.json'
        if sha(ref_path) != ref_manifest['references_sha256']:
            raise ValueError('Reference changed')
        ref = read(ref_path)[record['flag']['row_id']]
        answers = receipt['response']['answers']
        rows.append({**item, 'receipt_sha256': sha(receipt_path),
            'expected': ref.get('expected'), 'expected_source': ref.get('expected_source'),
            'decision': answers['decision']['choice'], 'source': answers['source_match']['choice'],
            'decision_confidence': answers['decision']['confidence'],
            'source_confidence': answers['source_match']['confidence']})
    thresholds = (0, .5, .65, .7, .75, .8, .85, .9, .95)
    categories = sorted({r['category'] for r in rows})
    arms = []
    for category in categories:
        selected = [r for r in rows if r['category'] == category]
        arms.append({'category': category, 'calls': len(selected),
            'reference_classes': dict(Counter(r['expected'] for r in selected)),
            'equal_cutoff_sweep': [sweep(selected, t, t) for t in thresholds],
            'source_cutoff_sweep_decision_075': [sweep(selected, .75, t) for t in thresholds]})
    report = {'ledger_sha256': sha(ledger_path), 'script_sha256': sha(Path(__file__)),
        'arms': arms, 'observations': rows, 'threshold_changed': False,
        'production_clearance_enabled': False,
        'limitations': ['Descriptive development sensitivity, not cutoff calibration.',
            'Arms contain repeated parents and cannot be pooled as independent cases.',
            'Historical packet observations do not revalidate the current builder.',
            'Confidence candidates remain subject to independent evidence and routing vetoes.',
            'No natural error-bearing cleared sample exists; missed-error risk is unestimated.']}
    destination = run / ('threshold_sensitivity_' + fingerprint(report)[:16] + '.json')
    if not destination.exists():
        write(destination, report)
    print(json.dumps({'artifact': destination.name, 'calls': len(rows), 'arms': len(arms)}), flush=True)


if __name__ == '__main__':
    main()
