"""Count distinct blocked flags per evidence failure; preserve overlapping causes."""
import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from pipeline.jev_screening import fingerprint
from scripts.compare_jev_retrieval import load_replay
from scripts.jev_pilot_session import install_read_only_guard, write


def profile(packets):
    records = []
    for (rule, row_id), packet in sorted(packets.items()):
        if packet['evidence_status']['status'] != 'blocked':
            continue
        reasons = set(packet['evidence_status']['blocking_reasons'])
        leaf_reasons = {reason for candidate in packet['source_candidates']
                        for reason in candidate['blocking_reasons']}
        specific = (reasons - {'incomplete_candidate_evidence'}) | leaf_reasons
        if not specific:
            specific = {'unexplained_blocker'}
        records.append({'rule': rule, 'row_id': row_id, 'cik': packet['flag']['cik'],
            'period': packet['flag']['report_date'], 'issuer_name': packet['output_position'].get('issuer_name'),
            'flag_reasons': sorted(reasons), 'candidate_reasons': sorted(leaf_reasons),
            'specific_reasons': sorted(specific), 'candidate_count': len(packet['source_candidates']),
            'complete_candidates': sum(not c['blocking_reasons'] for c in packet['source_candidates']),
            'candidate_recall_certified': False})
    by_reason = defaultdict(list)
    for record in records:
        for reason in record['specific_reasons']:
            by_reason[reason].append(record)
    issues = [{'reason': reason, 'distinct_flags': len(rows),
               'distinct_funds': len({r['cik'] for r in rows}),
               'by_rule': dict(Counter(r['rule'] for r in rows)),
               'sole_specific_reason_flags': sum(len(r['specific_reasons']) == 1 for r in rows),
               'flag_keys': [r['rule'] + ':' + r['row_id'] for r in rows]}
              for reason, rows in by_reason.items()]
    issues.sort(key=lambda item: (-item['distinct_flags'], item['reason']))
    return {'selected_flags': len(packets), 'blocked_flags': len(records),
            'blocked_by_rule': dict(Counter(r['rule'] for r in records)),
            'blocked_without_candidates': sum(r['candidate_count'] == 0 for r in records),
            'blocked_with_some_complete_candidates': sum(r['complete_candidates'] > 0 for r in records),
            'issues': issues, 'records': records,
            'production_clearance_enabled': False,
            'limitations': ['Cause counts overlap and must not be summed as distinct flags.',
                'A complete-looking candidate does not certify identity, recall or bundle validity.',
                'Sole specific reason does not imply a safe repair or clearance opportunity.',
                'Counts cover the selected development sample, not production prevalence.']}


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
    summary, packets = load_replay(run, args.replay)
    report = {**profile(packets), 'replay': args.replay, 'builder_sha256': summary['builder_sha256']}
    destination = run / ('blocker_profile_' + fingerprint(report)[:16] + '.json')
    if not destination.exists():
        write(destination, report)
    print(json.dumps({k: v for k, v in report.items() if k not in {'records', 'limitations', 'issues'}}), flush=True)
    print(json.dumps([{k: v for k, v in issue.items() if k != 'flag_keys'} for issue in report['issues']]), flush=True)


if __name__ == '__main__':
    main()
