"""Summarize frozen pilot observations without conflating agreement and safety."""
from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from pipeline.jev_screening import fingerprint
from pipeline.jev_bundles import number
from pipeline.jev_anchor_baseline import compare_context_anchor
from scripts.jev_pilot_session import install_read_only_guard, read, sha, write
from scripts.run_jev_screening import decode_observation


def summarize(run, attempts):
    manifest = read(run / 'manifest.json')
    if sha(run / 'references.json') != manifest['references_sha256']:
        raise ValueError('Frozen references changed')
    references = read(run / 'references.json')
    observations = []
    for record in manifest['records']:
        reference = references.get(record['flag']['row_id'], {})
        row = {'flag': record['flag'], 'expected': reference.get('expected'),
               'request_id': record['request_id'], 'status': 'not_submitted'}
        packet = read(run / 'packets' / (record['packet_id'] + '.json'))
        if fingerprint(packet) != record['packet_id']:
            raise ValueError('Frozen packet changed')
        row['context_anchor_baseline'] = compare_context_anchor(packet)
        # Deliberately conditional on a reviewer-supplied source identity. This
        # quantifies arithmetic value only, not automatic source-investigation savings.
        candidates = [c for c in packet['source_candidates'] if c['evidence_id'] == reference.get('expected_source')]
        baseline = None
        if len(candidates) == 1 and not candidates[0]['blocking_reasons']:
            agreement = []
            for field in packet['rule']['fields']:
                value = candidates[0]['source_values'][field]
                source, output, unit = number(value['amount']), number(packet['output_position'][field]), number(value['display_unit'])
                if None in (source, output, unit) or unit <= 0:
                    break
                agreement.append(abs(source - output) <= unit / 2)
            if len(agreement) == len(packet['rule']['fields']):
                baseline = 'false_alarm' if all(agreement) else 'real_error'
        row['conditional_numeric_baseline'] = baseline
        receipt_path = attempts / (str(record['request_id']) + '.result.json')
        if receipt_path.exists():
            receipt = read(receipt_path)
            request = read(run / 'requests' / (record['request_id'] + '.json'))
            decoded = decode_observation(receipt, record, request)
            row['status'] = decoded['status']
            if decoded['status'] == 'success':
                response = receipt['response']
                decision, source = response['answers']['decision'], response['answers']['source_match']
                row.update(decision=decision['choice'], decision_confidence=decision['confidence'],
                           source=source['choice'], source_confidence=source['confidence'],
                           input_tokens=response['usage']['input_tokens'],
                           label_agreement=decision['choice'] == reference.get('expected'),
                           source_agreement=source['choice'] == reference.get('expected_source'),
                           confidence_eligible=(decision['choice'] == 'false_alarm'
                               and decision['confidence'] >= manifest['policy']['decision_cutoff']
                               and source['confidence'] >= manifest['policy']['source_cutoff']
                               and source['choice'] != 'insufficient_evidence'))
        observations.append(row)
    successes = [r for r in observations if r['status'] == 'success']
    scored = [r for r in successes if r['expected'] in {'false_alarm', 'real_error', 'ambiguous'}]
    counts = {'flags': len(observations), 'successful_calls': len(successes),
              'reference_scored': len(scored),
              'label_agreement': sum(r['label_agreement'] for r in scored),
              'source_agreement': sum(r['source_agreement'] for r in scored),
              'confidence_eligible': sum(r['confidence_eligible'] for r in successes),
              'input_tokens': sum(r['input_tokens'] for r in successes)}
    conditional = [r for r in scored if r['conditional_numeric_baseline'] is not None]
    counts['conditional_numeric_baseline_scored'] = len(conditional)
    counts['conditional_numeric_baseline_agreement'] = sum(r['conditional_numeric_baseline'] == r['expected'] for r in conditional)
    anchors = [r for r in observations if r['context_anchor_baseline']['status'] != 'unresolved']
    counts['context_anchor_resolved'] = len(anchors)
    counts['context_anchor_source_agreement'] = sum(r['context_anchor_baseline']['source_id'] == references.get(r['flag']['row_id'], {}).get('expected_source') for r in anchors)
    return {'arm': manifest['arm'], 'counts': counts,
            'reference_classes': dict(Counter(r['expected'] for r in scored)),
            'observations': observations, 'production_clearance_enabled': False,
            'baseline_limitation': 'Numeric baseline receives manually reviewed expected_source and builder values. It is not an independent automatic source resolver and does not establish savings.',
            'limitation': 'Confidence eligibility is not safe clearance. Development agreement does not estimate unseen-fund accuracy or true-error recall. Manual review cost and B1 work remain.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--run-root', type=Path, required=True)
    parser.add_argument('--label', required=True)
    args = parser.parse_args()
    repo, out = args.repo.resolve(), args.run_root.resolve()
    if repo == ROOT or not out.is_relative_to(repo / 'data/pilot/jev_screening'):
        raise ValueError('Isolated pilot required')
    if not args.label.replace('_', '').isalnum():
        raise ValueError('Invalid label')
    install_read_only_guard(repo, out)
    report = summarize(out / args.label, out / 'api_attempts')
    target = out / args.label / ('analysis_' + fingerprint(report)[:16] + '.json')
    if not target.exists():
        write(target, report)
    import json
    print(json.dumps(report['counts']))


if __name__ == '__main__':
    main()
