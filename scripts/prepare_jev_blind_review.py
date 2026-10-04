"""Prepare source-first B1 review inputs without model or builder answers."""
import argparse
from collections import Counter
from copy import deepcopy
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from pipeline.jev_screening import fingerprint, REQUIRED_CHECKS
from scripts.compare_jev_retrieval import load_replay
from scripts.jev_pilot_session import install_read_only_guard, sha, write
from scripts.review_jev_sources import review_source_path


def review_input(packet, source_path, source_sha):
    """Allowlist source-first inputs: never carry candidates, scores or labels."""
    position = packet['output_position']
    identity_fields = ('cik', 'report_date', 'accession_number', 'row_id', 'issuer_name',
                       'instrument_description', 'bdc_investment_identifier', 'maturity_date',
                       'acquisition_date', 'shares_held', 'principal_amount', 'accounting_scope_id',
                       'accounting_record_class', 'src_context_id', 'bdc_dimensions_raw',
                       'cost_source', 'cost_reported', 'cost_currency', 'fair_value_currency')
    fields = tuple(dict.fromkeys((*identity_fields, *packet['rule']['fields'])))
    return {
        'schema_version': 'jev-blind-source-review.v1',
        'review_id': fingerprint({'bundle': fingerprint(packet), 'purpose': 'source_first'})[:24],
        'rule': {'id': packet['rule']['id'], 'fields': list(packet['rule']['fields'])},
        'position': {k: deepcopy(position[k]) for k in fields if k in position},
        'source': {'path': str(source_path), 'sha256': source_sha},
        'snapshot': {'holdings_sha256': packet['provenance']['holdings_sha256'],
                     'bundle_fingerprint': fingerprint(packet)},
        'instructions': [
            'Review cached original filing first. Pipeline identity and values are claims to verify, not source truth.',
            'Find every plausible sibling independently; record table/row coordinates and why each is included or excluded.',
            'Establish reporting period, owner/accounting scope, instrument/share class, unit scale and required notes.',
            'Record independent amounts and display precision before comparing them with published amounts.',
            'For derived/proxy values, inspect donor lineage and policy; do not compare current source cost as if reported.',
            'Freeze source findings before consulting the withheld builder candidates or model outcomes.',
            'Leave unresolved checks null; do not infer passing checks from matching values.',
            'No edits to production holdings, queues or acceptance gates are authorized by this packet.',
        ],
        'review_form': {'reviewer': None, 'started_at': None, 'completed_at': None,
                       'active_seconds': None, 'source_coordinates': None,
                       'candidate_inventory': [], 'source_values': {}, 'citations': [],
                       'checks': {k: None for k in REQUIRED_CHECKS},
                       'disposition': None, 'reason': None, 'unresolved_questions': []},
        'production_clearance_enabled': False,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', required=True, type=Path)
    parser.add_argument('--run-root', required=True, type=Path)
    parser.add_argument('--replay', required=True)
    parser.add_argument('--label', required=True)
    args = parser.parse_args()
    repo, run = args.repo.resolve(), args.run_root.resolve()
    if repo == ROOT or not run.is_relative_to(repo / 'data/pilot/jev_screening'):
        raise ValueError('Isolated pilot required')
    install_read_only_guard(repo, run)
    if not args.label.replace('_', '').isalnum():
        raise ValueError('Invalid output label')
    summary, packets = load_replay(run, args.replay)
    if len(packets) != 67 or len({p['output_position']['cik'] for p in packets.values()}) != 11:
        raise ValueError('Unexpected frozen scope')
    holdings_hash = sha(repo / 'data/output/private_markets_holdings.csv')
    if any(p['provenance']['holdings_sha256'] != holdings_hash for p in packets.values()):
        raise ValueError('Holdings changed since replay')
    target = run / args.label
    target.mkdir()
    hashes, inventory = {}, []
    for key, packet in sorted(packets.items()):
        source = review_source_path(repo, packet)
        if source not in hashes:
            if source.stat().st_size > 40 * 1024 * 1024:
                raise ValueError('Source exceeds cap')
            hashes[source] = sha(source)
        if packet['filing'].get('sha256') and hashes[source] != packet['filing']['sha256']:
            raise ValueError('Source changed')
        item = review_input(packet, source, hashes[source])
        filename = key[0] + '_' + key[1] + '.json'
        write(target / filename, item)
        inventory.append({'review_id': item['review_id'], 'file': filename,
                          'sha256': sha(target / filename), 'rule': key[0]})
    report = {'packets': len(inventory), 'funds': 11, 'source_files': len(hashes),
              'rules': dict(Counter(i['rule'] for i in inventory)), 'inventory': inventory,
              'builder_sha256': summary['builder_sha256'], 'replay': args.replay,
              'preparation_script_sha256': sha(Path(__file__)),
              'holdings_sha256': holdings_hash, 'reviews_completed': 0,
              'api_calls': 0, 'production_clearance_enabled': False,
              'limitation': 'Prepared inputs only; existing cases are development data. Independent reviewer identity and completed source review are still required.'}
    write(target / 'manifest.json', report)
    print(json.dumps({k: v for k, v in report.items() if k != 'inventory'}), flush=True)


if __name__ == '__main__':
    main()
