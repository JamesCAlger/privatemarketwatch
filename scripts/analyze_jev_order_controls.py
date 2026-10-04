"""Report paired presentation results without treating confidence as calibration."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from pipeline.jev_screening import fingerprint
from scripts.analyze_jev_screening import summarize
from scripts.jev_pilot_session import install_read_only_guard, write


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--run-root', type=Path, required=True)
    args = parser.parse_args()
    repo, run = args.repo.resolve(), args.run_root.resolve()
    if repo == ROOT or not run.is_relative_to(repo / 'data/pilot/jev_screening'):
        raise ValueError('Isolated pilot required')
    install_read_only_guard(repo, run)
    reports = [summarize(run / label, run / 'api_attempts') for label in
               ('order_normal_model_01', 'order_reverse_model_01')]
    arms = [{r['flag']['row_id']: r for r in report['observations']} for report in reports]
    if set(arms[0]) != set(arms[1]) or len(arms[0]) != 4:
        raise ValueError('Expected four complete pairs')
    pairs = []
    for row_id in sorted(arms[0]):
        normal, reverse = arms[0][row_id], arms[1][row_id]
        if normal['status'] != 'success' or reverse['status'] != 'success':
            raise ValueError('Pair incomplete')
        pairs.append({'row_id': row_id,
                      'decision_unchanged': normal['decision'] == reverse['decision'],
                      'source_unchanged': normal['source'] == reverse['source'],
                      'both_labels_correct': normal['label_agreement'] and reverse['label_agreement'],
                      'both_sources_correct': normal['source_agreement'] and reverse['source_agreement'],
                      'eligibility_changed': normal['confidence_eligible'] != reverse['confidence_eligible'],
                      'passes_both_presentations': normal['confidence_eligible'] and reverse['confidence_eligible'],
                      'decision_confidences': [normal['decision_confidence'], reverse['decision_confidence']],
                      'source_confidences': [normal['source_confidence'], reverse['source_confidence']]})
    report = {'pairs': pairs, 'pair_count': len(pairs),
              'label_changes': sum(not p['decision_unchanged'] for p in pairs),
              'source_changes': sum(not p['source_unchanged'] for p in pairs),
              'confidence_eligibility_changes': sum(p['eligibility_changed'] for p in pairs),
              'passes_both_presentations': sum(p['passes_both_presentations'] for p in pairs),
              'input_tokens': sum(r['counts']['input_tokens'] for r in reports),
              'natural_flags_added': 0, 'audited_clearances': 0,
              'limitations': ['One call per presentation; ordering effects are not separated from provider variability.',
                              'Four development false alarms; no unsafe-clearance rate or confidence calibration.',
                              'Do not choose the presentation with higher confidence or change routing cutoffs from this result.']}
    destination = run / ('order_comparison_' + fingerprint(report)[:16] + '.json')
    if not destination.exists():
        write(destination, report)
    print(json.dumps({k: v for k, v in report.items() if k != 'pairs'}), flush=True)


if __name__ == '__main__':
    main()
