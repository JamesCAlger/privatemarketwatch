"""Check frozen replay changes are confined to note retrieval and its blockers."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from pipeline.jev_screening import fingerprint
from scripts.compare_jev_retrieval import load_replay
from scripts.jev_pilot_session import install_read_only_guard, write


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--run-root', type=Path, required=True)
    parser.add_argument('--before', required=True)
    parser.add_argument('--after', required=True)
    args = parser.parse_args()
    repo, run = args.repo.resolve(), args.run_root.resolve()
    if repo == ROOT or not run.is_relative_to(repo / 'data/pilot/jev_screening'):
        raise ValueError('Isolated pilot required')
    install_read_only_guard(repo, run)
    old_summary, old = load_replay(run, args.before)
    new_summary, new = load_replay(run, args.after)
    if set(old) != set(new):
        raise ValueError('Selection changed')
    changes = []
    allowed = {'notes', 'missing_note_markers', 'blocking_reasons'}
    allowed_reasons = {'missing_referenced_notes', 'referenced_note_continuation_unresolved',
                       'conflicting_referenced_notes'}
    for key, packet in sorted(new.items()):
        parent = old[key]
        for field in ('flag', 'output_position', 'retrieval'):
            if parent.get(field) != packet.get(field):
                raise ValueError('Non-note packet field changed: ' + field)
        if parent['filing'].get('sha256') != packet['filing'].get('sha256'):
            raise ValueError('Source changed')
        if (set(parent['evidence_status']['blocking_reasons']) ^ set(packet['evidence_status']['blocking_reasons'])) - {'incomplete_candidate_evidence'}:
            raise ValueError('Non-note packet blocker changed')
        before = {c['evidence_id']: c for c in parent['source_candidates']}
        after = {c['evidence_id']: c for c in packet['source_candidates']}
        if set(before) != set(after):
            raise ValueError('Candidate inventory changed')
        edits = []
        for evidence_id, candidate in after.items():
            previous = before[evidence_id]
            if {k: v for k, v in previous.items() if k not in allowed} != {k: v for k, v in candidate.items() if k not in allowed}:
                raise ValueError('Non-note candidate evidence changed')
            if (set(previous['blocking_reasons']) ^ set(candidate['blocking_reasons'])) - allowed_reasons:
                raise ValueError('Non-note candidate blocker changed')
            if previous != candidate:
                edits.append({'evidence_id': evidence_id,
                    'before': {k: previous[k] for k in allowed},
                    'after': {k: candidate[k] for k in allowed}})
        if edits:
            changes.append({'rule': key[0], 'row_id': key[1], 'cik': packet['flag']['cik'],
                'before_status': parent['evidence_status']['status'],
                'after_status': packet['evidence_status']['status'], 'candidate_changes': edits})
    report = {'before': args.before, 'after': args.after,
        'before_builder_sha256': old_summary['builder_sha256'], 'after_builder_sha256': new_summary['builder_sha256'],
        'flags': len(new), 'changed_flags': len(changes),
        'newly_ready': sum(c['before_status'] == 'blocked' and c['after_status'] == 'ready_for_model' for c in changes),
        'newly_blocked': sum(c['before_status'] == 'ready_for_model' and c['after_status'] == 'blocked' for c in changes),
        'source_identity_amounts_and_candidate_sets_unchanged': True,
        'changes': changes, 'production_clearance_enabled': False,
        'limitation': 'Checks the structured delta, not independent note completeness or model score transfer.'}
    destination = run / ('note_retrieval_delta_' + fingerprint(report)[:16] + '.json')
    if not destination.exists():
        write(destination, report)
    print(json.dumps({'artifact': destination.name, **{k: v for k, v in report.items() if k != 'changes'}}), flush=True)


if __name__ == '__main__':
    main()
