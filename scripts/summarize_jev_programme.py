"""Account for every natural flag once, retaining run/version and reference limits."""
import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.analyze_jev_screening import summarize
from scripts.compare_jev_bundle_versions import NATURAL_RUNS
from pipeline.jev_screening import fingerprint
from scripts.jev_pilot_session import install_read_only_guard, read, write


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--run-root', type=Path, required=True)
    args = parser.parse_args()
    repo, run = args.repo.resolve(), args.run_root.resolve()
    if repo == ROOT or not run.is_relative_to(repo / 'data/pilot/jev_screening'):
        raise ValueError('Isolated pilot required')
    install_read_only_guard(repo, run)
    runs = NATURAL_RUNS
    flags, versions = {}, defaultdict(list)
    for label in runs:
        report = summarize(run / label, run / 'api_attempts')
        for row in report['observations']:
            key = (row['flag']['rule_id'], row['flag']['row_id'])
            versions[key].append(label)
            if key in flags and flags[key]['status'] == 'success':
                raise ValueError('Do not silently replace a prior successful natural observation')
            flags[key] = {**row, 'run': label}
    by_rule = defaultdict(list)
    for row in flags.values():
        by_rule[row['flag']['rule_id']].append(row)
    rule_summary = {}
    for rule, rows in by_rule.items():
        successful = [r for r in rows if r['status'] == 'success']
        rule_summary[rule] = {'flags': len(rows), 'successful_calls': len(successful),
                              'reference_labels': dict(Counter(r['expected'] or 'unreviewed' for r in rows)),
                              'confidence_only_candidates': sum(r['confidence_eligible'] for r in successful),
                              'audited_clearances': 0}
    sensitivity = []
    for cutoff in [0.5, 0.6, 0.7, 0.75, 0.8, 0.9]:
        accepted = [r for r in flags.values() if r['status'] == 'success'
                    and r['decision'] == 'false_alarm' and r['source'] != 'insufficient_evidence'
                    and r['decision_confidence'] >= cutoff and r['source_confidence'] >= cutoff]
        sensitivity.append({'both_cutoffs': cutoff, 'confidence_only_candidates': len(accepted),
                            'by_rule': dict(Counter(r['flag']['rule_id'] for r in accepted))})
    attempts = list((run / 'api_attempts').glob('*.started.json'))
    results = [read(p) for p in (run / 'api_attempts').glob('*.result.json')]
    report = {'natural_unique_flags': len(flags),
              'natural_distinct_funds': len({r['flag']['cik'] for r in flags.values()}),
              'natural_successful_calls': sum(r['status'] == 'success' for r in flags.values()),
              'rule_summary': rule_summary, 'threshold_sensitivity': sensitivity,
              'all_session_attempts': len(attempts),
              'all_session_input_tokens': sum(r.get('response', {}).get('usage', {}).get('input_tokens', 0) for r in results),
              'observations': list(flags.values()),
              'version_history': {rule + ':' + row: labels for (rule, row), labels in versions.items()},
              'limitations': ['Different frozen builder versions; this is observation accounting, not one final-builder validation run.',
                             'All model-scored natural references are false alarms; no confidence calibration or population recall estimate.',
                             'Four reviewed natural errors remain blocked before model submission.',
                             'No complete independent clearance audits and no B1 suppression.',
                             'X08/C104 are currently track-only weak rules; screening them adds review coverage, not removal of existing B1 jobs.',
                             'Threshold sensitivity is descriptive development analysis, not threshold selection or approval.']}
    destination = run / ('programme_summary_' + fingerprint(report)[:16] + '.json')
    if not destination.exists():
        write(destination, report)
    print(json.dumps({k: v for k, v in report.items() if k not in {'observations', 'version_history', 'limitations'}}))


if __name__ == '__main__':
    main()
