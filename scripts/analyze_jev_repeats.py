"""Compare exact-request replications with their frozen original responses."""
import argparse
from collections import defaultdict
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from pipeline.jev_screening import fingerprint
from scripts.jev_pilot_session import install_read_only_guard, read, sha, write
from scripts.repeat_jev_requests import LABEL, validate_frozen_record
from scripts.run_jev_screening import decode_observation


def confidence_eligible(answers):
    decision, source = answers['decision'], answers['source_match']
    return (decision['choice'] == 'false_alarm' and decision['confidence'] >= .75
            and source['choice'] != 'insufficient_evidence' and source['confidence'] >= .75)


def summarize(root):
    run, attempts = root / LABEL, root / 'api_attempts'
    manifest = read(run / 'manifest.json')
    if len(manifest['records']) != 8:
        raise ValueError('Expected eight frozen repeats')
    rows, by_flag = [], defaultdict(list)
    for record in manifest['records']:
        request = validate_frozen_record(run, record)
        parent = root / record['parent_run']
        parent_manifest = read(parent / 'manifest.json')
        if sha(parent / 'references.json') != parent_manifest['references_sha256']:
            raise ValueError('Parent references changed')
        reference = read(parent / 'references.json')[record['flag']['row_id']]
        original_path = attempts / (record['request_id'] + '.result.json')
        if sha(original_path) != record['parent_receipt_sha256']:
            raise ValueError('Original receipt changed')
        original = read(original_path)
        repeated = read(attempts / (record['attempt_id'] + '.result.json'))
        if repeated.get('attempt_id') != record['attempt_id']:
            raise ValueError('Repeat receipt identity differs')
        for receipt in (original, repeated):
            if decode_observation(receipt, record, request)['status'] != 'success':
                raise ValueError('Incomplete or invalid repeat pair')
        first, second = original['response']['answers'], repeated['response']['answers']
        row = {'row_id': record['flag']['row_id'], 'presentation': record['parent_run'],
               'request_id': record['request_id'], 'attempt_id': record['attempt_id'],
               'answers_identical': first == second,
               'label_changed': first['decision']['choice'] != second['decision']['choice'],
               'source_changed': first['source_match']['choice'] != second['source_match']['choice'],
               'decision_confidences': [first['decision']['confidence'], second['decision']['confidence']],
               'source_confidences': [first['source_match']['confidence'], second['source_match']['confidence']],
               'confidence_eligibility': [confidence_eligible(first), confidence_eligible(second)],
               'repeated_label_agreement': second['decision']['choice'] == reference['expected'],
               'repeated_source_agreement': second['source_match']['choice'] == reference['expected_source'],
               'repeat_input_tokens': repeated['response']['usage']['input_tokens']}
        rows.append(row)
        by_flag[row['row_id']].append(row)
    if len(by_flag) != 4 or any(len(v) != 2 for v in by_flag.values()):
        raise ValueError('Expected four paired presentations')
    return {
        'repeated_calls': len(rows), 'exact_answer_repeats': sum(r['answers_identical'] for r in rows),
        'label_changes': sum(r['label_changed'] for r in rows),
        'source_changes': sum(r['source_changed'] for r in rows),
        'within_request_eligibility_changes': sum(r['confidence_eligibility'][0] != r['confidence_eligibility'][1] for r in rows),
        'repeat_between_presentation_eligibility_changes': sum(v[0]['confidence_eligibility'][1] != v[1]['confidence_eligibility'][1] for v in by_flag.values()),
        'repeated_label_agreement': sum(r['repeated_label_agreement'] for r in rows),
        'repeated_source_agreement': sum(r['repeated_source_agreement'] for r in rows),
        'repeat_input_tokens': sum(r['repeat_input_tokens'] for r in rows),
        'observations': rows, 'audited_clearances': 0, 'natural_flags_added': 0,
        'limitations': ['Two observations per exact request on four development false alarms.',
                        'Identical responses cannot distinguish deterministic inference from provider caching.',
                        'No confidence calibration, production routing or selection of a more favourable presentation.']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--run-root', type=Path, required=True)
    args = parser.parse_args()
    repo, root = args.repo.resolve(), args.run_root.resolve()
    if repo == ROOT or not root.is_relative_to(repo / 'data/pilot/jev_screening'):
        raise ValueError('Isolated pilot required')
    install_read_only_guard(repo, root)
    report = summarize(root)
    destination = root / ('repeat_comparison_' + fingerprint(report)[:16] + '.json')
    if not destination.exists():
        write(destination, report)
    print(json.dumps({k: v for k, v in report.items() if k not in {'observations', 'limitations'}}), flush=True)


if __name__ == '__main__':
    main()
