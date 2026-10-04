"""Count observed evidence mechanisms by distinct flag and filer, not certification."""
import argparse
from collections import defaultdict
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
    parser.add_argument('--replay', required=True)
    args = parser.parse_args()
    repo, run = args.repo.resolve(), args.run_root.resolve()
    if repo == ROOT or not run.is_relative_to(repo / 'data/pilot/jev_screening'):
        raise ValueError('Isolated pilot required')
    install_read_only_guard(repo, run)
    summary, packets = load_replay(run, args.replay)
    observed = defaultdict(dict)
    for key, packet in packets.items():
        features = set()
        for candidate in packet['source_candidates']:
            features.add('period_basis:' + str(candidate.get('period_evidence', {}).get('basis')))
            if len(candidate.get('notes', [])):
                features.add('referenced_notes_present')
            for section in candidate.get('section_context', []):
                if section.get('table_index') != candidate.get('table_index'):
                    features.add('section_evidence_from_other_table')
                if section.get('scope_unresolved'):
                    features.add('unresolved_section_scope')
            for note in candidate.get('notes', []):
                if note.get('continuation_table'):
                    features.add('note_table:' + note['continuation_table']['association'])
            for field, value in candidate['source_values'].items():
                if field in candidate['headers'] and candidate['headers'][field].get('span', 1) > 1:
                    features.add('monetary_header_spans_multiple_columns')
                for cell in value.get('cells', []):
                    if cell.get('superscript_note_markers'):
                        features.add('monetary_cell_superscript_notes')
                    for fact in cell.get('inline_facts', []):
                        features.add('transform_namespace:' + str(fact.get('format_namespace')))
                        if (fact.get('format') or '').split(':')[-1] in {'fixed-zero', 'zerodash'}:
                            features.add('explicit_zero_transform')
                        if fact.get('sign') == '-':
                            features.add('inline_negative_sign')
        for feature in features:
            observed[feature][key] = {'cik': packet['flag']['cik'],
                'filing': packet['output_position'].get('accession_number'),
                'ready': packet['evidence_status']['status'] == 'ready_for_model'}
    records = []
    for feature, flags in sorted(observed.items()):
        values = list(flags.values())
        records.append({'feature': feature, 'flags': len(flags),
            'ready_flags': sum(r['ready'] for r in values),
            'blocked_flags': sum(not r['ready'] for r in values),
            'funds': len({r['cik'] for r in values}),
            'filings': len({(r['cik'], r['filing']) for r in values}),
            'ciks': sorted({r['cik'] for r in values})})
    report = {'replay': args.replay, 'builder_sha256': summary['builder_sha256'],
        'selected_flags': len(packets), 'flags_with_candidates': sum(bool(p['source_candidates']) for p in packets.values()),
        'records': records, 'production_clearance_enabled': False,
        'limitations': ['Features overlap; flag counts cannot be summed.',
            'Readiness is for the whole packet, not independent validation of the listed feature.',
            'Candidate samples do not establish full-filing or future-filer support.',
            'Absence of an observed feature does not mean a source filing lacks it.',
            'Single-filer observations require transfer validation before generality claims.']}
    destination = run / ('mechanism_profile_' + fingerprint(report)[:16] + '.json')
    if not destination.exists():
        write(destination, report)
    print(json.dumps({'artifact': destination.name, 'records': records}), flush=True)


if __name__ == '__main__':
    main()
