"""Verify a frozen replay changes only note continuations and their blockers."""
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
        raise ValueError('Selections differ')
    changes = []
    for key, packet in sorted(new.items()):
        parent = old[key]
        if (parent['flag'] != packet['flag'] or parent['output_position'] != packet['output_position']
                or parent['filing'].get('sha256') != packet['filing'].get('sha256')):
            raise ValueError('Source, flag or output changed')
        old_reasons = set(parent['evidence_status']['blocking_reasons'])
        new_reasons = set(packet['evidence_status']['blocking_reasons'])
        if new_reasons - old_reasons or old_reasons - new_reasons - {'incomplete_candidate_evidence'}:
            raise ValueError('Unrelated flag blocker changed')
        for item in (parent, packet):
            if (item['evidence_status']['status'] == 'ready_for_model') != (not item['evidence_status']['blocking_reasons']):
                raise ValueError('Readiness contradicts blocker list')
        before = {c['evidence_id']: c for c in parent['source_candidates']}
        after = {c['evidence_id']: c for c in packet['source_candidates']}
        if set(before) != set(after):
            raise ValueError('Candidate inventory changed')
        additions = []
        for evidence_id, candidate in after.items():
            previous = before[evidence_id]
            if ({k: v for k, v in previous.items() if k not in {'notes', 'blocking_reasons'}}
                    != {k: v for k, v in candidate.items() if k not in {'notes', 'blocking_reasons'}}):
                raise ValueError('Non-note candidate evidence changed')
            if (set(candidate['blocking_reasons']) - set(previous['blocking_reasons'])
                    or set(previous['blocking_reasons']) - set(candidate['blocking_reasons'])
                    - {'referenced_note_continuation_unresolved'}):
                raise ValueError('Unrelated candidate blocker changed')
            if len(previous['notes']) != len(candidate['notes']):
                raise ValueError('Note inventory changed')
            for old_note, note in zip(previous['notes'], candidate['notes']):
                if old_note == note:
                    continue
                if ('continuation_table' in old_note or 'continuation_table' not in note
                        or old_note != {k: v for k, v in note.items() if k != 'continuation_table'}):
                    raise ValueError('Existing note changed beyond added continuation')
                table = note['continuation_table']
                if table['association'] != 'following_reference_rate_table' or not table['intervening_notes']:
                    raise ValueError('Unexpected continuation mechanism')
                additions.append({'evidence_id': evidence_id, 'marker': note['marker'],
                                  'period': note['report_date'], 'table_index': table['table_index'],
                                  'rows': len(table['rows']), 'intervening_notes': table['intervening_notes']})
        if additions:
            changes.append({'rule': key[0], 'row_id': key[1], 'cik': packet['flag']['cik'],
                'period': packet['flag']['report_date'], 'source_sha256': packet['filing']['sha256'],
                'before_status': parent['evidence_status']['status'],
                'after_status': packet['evidence_status']['status'], 'additions': additions})
    report = {'before': args.before, 'after': args.after, 'flags': len(new),
        'before_builder_sha256': old_summary['builder_sha256'],
        'after_builder_sha256': new_summary['builder_sha256'],
        'flags_with_note_additions': len(changes),
        'newly_ready': sum(r['before_status'] == 'blocked' and r['after_status'] == 'ready_for_model' for r in changes),
        'funds_with_note_additions': len({r['cik'] for r in changes}),
        'source_files_with_note_additions': len({r['source_sha256'] for r in changes}),
        'changes': changes, 'source_identity_amounts_and_candidate_sets_unchanged': True,
        'production_clearance_enabled': False,
        'limitation': 'Structured delta verification and source inspection, not an independent completeness audit or score transfer.'}
    destination = run / ('note_delta_' + fingerprint(report)[:16] + '.json')
    if not destination.exists():
        write(destination, report)
    print(json.dumps({k: v for k, v in report.items() if k != 'changes'}), flush=True)


if __name__ == '__main__':
    main()
