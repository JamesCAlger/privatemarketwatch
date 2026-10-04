"""Compare frozen candidate sets without reusing model scores or clearing flags."""
from __future__ import annotations
import argparse
from collections import Counter
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from pipeline.jev_screening import fingerprint
from scripts.jev_pilot_session import install_read_only_guard, read, sha, write


def load_replay(run, label):
    if not label.replace('_', '').isalnum():
        raise ValueError('Invalid replay label')
    directory = run / label
    summary = read(directory / 'summary.json')
    runtime = summary.get('parser_runtime')
    runtime_hash = summary.get('parser_runtime_sha256')
    if runtime is not None or runtime_hash is not None:
        if (not isinstance(runtime, dict) or fingerprint(runtime) != runtime_hash
                or runtime.get('builder_sha256') != summary['builder_sha256']):
            raise ValueError('Invalid replay parser runtime binding')
    paths = list(directory.glob('*_ROW-*.json'))
    if not 1 <= len(paths) <= 100 or len(paths) != len(summary['cases']):
        raise ValueError('Incomplete or unbounded replay')
    declared = {}
    for case in summary['cases']:
        if 'rule' in case and 'row_id' in case:
            key = (case['rule'], case['row_id'])
        elif isinstance(case.get('case_id'), str) and '_ROW-' in case['case_id']:
            rule, row = case['case_id'].split('_ROW-', 1)
            key = (rule, 'ROW-' + row)
        else:
            raise ValueError('Summary lacks flag identity')
        if key in declared:
            raise ValueError('Duplicate declared flag')
        declared[key] = case
    packets = {}
    for path in paths:
        packet = read(path)
        filing = packet.get('filing') or {}
        # Input refusals may happen before a source path can be constructed.
        input_refusal = (set(filing) == {'status'} and filing.get('status') in {
            'missing_or_invalid_accession', 'missing_or_invalid_cik'})
        source_attempted = bool(filing) and not input_refusal
        if runtime is not None and source_attempted:
            if (filing.get('parser_runtime') != runtime
                    or filing.get('parser_runtime_sha256') != runtime_hash):
                raise ValueError('Packet parser runtime differs from summary')
        key = (packet['rule']['id'], packet['flag']['row_id'])
        if key in packets or packet['provenance']['builder_sha256'] != summary['builder_sha256']:
            raise ValueError('Duplicate flag or mixed builder versions')
        if (key not in declared or packet['flag'].get('rule_id') != key[0]
                or path.stem != key[0] + '_' + key[1]):
            raise ValueError('Packet flag differs from declared identity')
        case = declared[key]
        status = case.get('status', case.get('after'))
        reasons = case.get('blocking_reasons', case.get('reasons'))
        if (status != packet['evidence_status']['status']
                or reasons != packet['evidence_status']['blocking_reasons']):
            raise ValueError('Packet evidence status differs from summary')
        if (summary.get('holdings_sha256')
                and packet['provenance'].get('holdings_sha256') != summary['holdings_sha256']):
            raise ValueError('Packet holdings snapshot differs from summary')
        if 'packet_fingerprint' in case and fingerprint(packet) != case['packet_fingerprint']:
            raise ValueError('Packet content fingerprint differs from summary')
        packets[key] = packet
    if set(packets) != set(declared):
        raise ValueError('Replay membership differs from summary')
    actual_counts = dict(Counter(p['evidence_status']['status'] for p in packets.values()))
    if 'status_counts' in summary and summary['status_counts'] != actual_counts:
        raise ValueError('Replay status counts differ from summary')
    return summary, packets


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
    old_summary, before = load_replay(run, args.before)
    new_summary, after = load_replay(run, args.after)
    if set(before) != set(after):
        raise ValueError('Different flag selections')
    rows = []
    for key, new in sorted(after.items()):
        old = before[key]
        if old['output_position'] != new['output_position']:
            raise ValueError('Output snapshot differs')
        if old['filing'].get('sha256') != new['filing'].get('sha256'):
            raise ValueError('Source snapshot differs')
        old_ids = {c['evidence_id'] for c in old['source_candidates']}
        new_ids = {c['evidence_id'] for c in new['source_candidates']}
        rows.append({
            'rule': key[0], 'row_id': key[1], 'cik': new['output_position']['cik'],
            'issuer_name': new['output_position']['issuer_name'],
            'before_status': old['evidence_status']['status'],
            'after_status': new['evidence_status']['status'],
            'added_candidates': sorted(new_ids - old_ids),
            'removed_candidates': sorted(old_ids - new_ids),
            'before_candidate_count': len(old_ids), 'after_candidate_count': len(new_ids),
            'blocking_reasons': new['evidence_status']['blocking_reasons'],
            'candidate_blockers': {c['evidence_id']: c['blocking_reasons']
                                   for c in new['source_candidates'] if c['blocking_reasons']},
        })
    changes = [r for r in rows if r['added_candidates'] or r['removed_candidates']
               or r['before_status'] != r['after_status']]
    report = {
        'before': args.before, 'after': args.after,
        'before_builder_sha256': old_summary['builder_sha256'],
        'after_builder_sha256': new_summary['builder_sha256'],
        'flags': len(rows), 'funds': len({r['cik'] for r in rows}),
        'after_readiness': dict(Counter(r['after_status'] for r in rows)),
        'by_rule': {rule: dict(Counter(r['after_status'] for r in rows if r['rule'] == rule))
                    for rule in sorted({r['rule'] for r in rows})},
        'changed_flags': len(changes), 'changes': changes,
        'added_candidates': sum(len(r['added_candidates']) for r in rows),
        'removed_candidates': sum(len(r['removed_candidates']) for r in rows),
        'observations': rows,
        'limitation': 'Candidate-set changes are not independently measured recall. No model score transfer or clearance.',
    }
    destination = run / ('retrieval_comparison_' + fingerprint(report)[:16] + '.json')
    if not destination.exists():
        write(destination, report)
    print(json.dumps({k: v for k, v in report.items() if k not in {'observations', 'changes'}}), flush=True)


if __name__ == '__main__':
    main()
