"""Inventory observed candidate layouts; signatures never certify supported scope."""
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


def layout_shape(candidate):
    """Header and grid geometry only; intentionally excludes position values."""
    return {
        'headers': {field: {key: header.get(key) for key in ('column', 'span', 'text')}
                    for field, header in sorted(candidate['headers'].items())},
        'row_geometry': [{'column': c['column'], 'span': c['span']} for c in candidate['raw_cells']],
    }


def numeric_evidence_paths(candidate):
    paths = []
    for field, value in candidate['source_values'].items():
        for cell in value.get('cells', []):
            for fact in cell.get('inline_facts', []):
                paths.append({'field': field, 'concept': fact.get('name'),
                              'format': fact.get('format'), 'format_namespace': fact.get('format_namespace'),
                              'scale': fact.get('scale'), 'currency': fact.get('currency')})
    unique = {fingerprint(p): p for p in paths}
    return [unique[key] for key in sorted(unique)]


def profile(packets):
    layouts, periods = {}, defaultdict(list)
    for packet in packets.values():
        row = {'rule': packet['rule']['id'], 'row_id': packet['flag']['row_id'],
               'cik': packet['output_position']['cik'], 'period': packet['output_position']['report_date'],
               'accession': packet['output_position']['accession_number'],
               'status': packet['evidence_status']['status'],
               'blocking_reasons': packet['evidence_status']['blocking_reasons'],
               'candidates': []}
        for candidate in packet['source_candidates']:
            shape = layout_shape(candidate)
            layout_id = fingerprint(shape)[:20]
            if layout_id in layouts and layouts[layout_id] != shape:
                raise ValueError('Layout hash collision')
            layouts[layout_id] = shape
            row['candidates'].append({
                'evidence_id': candidate['evidence_id'], 'layout_id': layout_id,
                'numeric_paths': numeric_evidence_paths(candidate),
                'period_basis': candidate.get('period_evidence', {}).get('basis'),
                'note_markers': sorted(n['marker'] for n in candidate['notes']),
                'note_table_count': sum(bool(n.get('continuation_table')) for n in candidate['notes']),
                'missing_note_markers': candidate['missing_note_markers'],
                'blocking_reasons': candidate['blocking_reasons'],
            })
        periods[(row['cik'], row['period'], row['accession'])].append(row)
    cohorts = []
    for (cik, period, accession), rows in sorted(periods.items()):
        candidates = [c for row in rows for c in row['candidates']]
        cohorts.append({'cik': cik, 'period': period, 'accession': accession,
                        'flags': len(rows), 'status_counts': dict(Counter(r['status'] for r in rows)),
                        'layout_ids': sorted({c['layout_id'] for c in candidates}),
                        'flags_without_candidates': sum(not r['candidates'] for r in rows),
                        'candidate_blockers': dict(Counter(reason for c in candidates for reason in set(c['blocking_reasons']))),
                        'flag_rows': rows})
    changes = []
    for cik in sorted({c['cik'] for c in cohorts}):
        ordered = [c for c in cohorts if c['cik'] == cik and c['layout_ids']]
        for previous, current in zip(ordered, ordered[1:]):
            if set(previous['layout_ids']) != set(current['layout_ids']):
                changes.append({'cik': cik, 'before_period': previous['period'], 'after_period': current['period'],
                                'before_accession': previous['accession'], 'after_accession': current['accession'],
                                'added_layouts': sorted(set(current['layout_ids']) - set(previous['layout_ids'])),
                                'absent_in_later_sample': sorted(set(previous['layout_ids']) - set(current['layout_ids']))})
    return {'flags': sum(c['flags'] for c in cohorts), 'funds': len({c['cik'] for c in cohorts}),
            'filing_periods': len(cohorts), 'observed_layout_shapes': len(layouts),
            'flags_without_candidates': sum(c['flags_without_candidates'] for c in cohorts),
            'observed_shape_set_changes': len(changes), 'shape_set_changes': changes,
            'layout_definitions': layouts, 'filing_periods_detail': cohorts,
            'filer_types': ['BDC cached inline-XBRL HTML'], 'production_clearance_enabled': False,
            'limitations': ['Sampled candidate layouts only, not a census of complete filings.',
                            'A shape-set difference may reflect different sampled positions, not a filer template change.',
                            'Identical headers/grid geometry do not validate note scope, ownership, units or candidate recall.',
                            'No validation of interval/tender funds, N-PORT or HTML-only filings.']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--run-root', type=Path, required=True)
    parser.add_argument('--replay', required=True)
    args = parser.parse_args()
    repo, root = args.repo.resolve(), args.run_root.resolve()
    if repo == ROOT or not root.is_relative_to(repo / 'data/pilot/jev_screening'):
        raise ValueError('Isolated pilot required')
    install_read_only_guard(repo, root)
    summary, packets = load_replay(root, args.replay)
    report = {**profile(packets), 'replay': args.replay, 'builder_sha256': summary['builder_sha256']}
    destination = root / ('layout_profile_' + fingerprint(report)[:16] + '.json')
    if not destination.exists():
        write(destination, report)
    print(json.dumps({k: report[k] for k in ('flags', 'funds', 'filing_periods', 'observed_layout_shapes',
                                           'flags_without_candidates', 'observed_shape_set_changes')}), flush=True)


if __name__ == '__main__':
    main()
