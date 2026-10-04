"""Freeze paired C104 controls using a copied filing; never modify cached originals."""
import argparse
from copy import deepcopy
import json
import os
from pathlib import Path
import sys
import threading
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from pipeline.jev_bundles import SourceCache, build_bundle
from pipeline.jev_screening import fingerprint
from scripts.jev_pilot_session import install_read_only_guard, read, sha, write
from scripts.review_jev_sources import review_source_path

PARENT = 'ROW-51aff32e293b8795'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--run-root', type=Path, required=True)
    args = parser.parse_args()
    repo, run = args.repo.resolve(), args.run_root.resolve()
    if repo == ROOT or not run.is_relative_to(repo / 'data/pilot/jev_screening'):
        raise ValueError('Isolated pilot required')
    install_read_only_guard(repo, run)
    if len(list((run / 'api_attempts').glob('*.started.json'))) != 98:
        raise ValueError('Expected exactly two remaining calls under the 100-call cap')
    builder_hash = sha(ROOT / 'pipeline/jev_bundles.py')
    parent = read(run / 'rate_note_scope_v4_42' / ('C104_' + PARENT + '.json'))
    if parent['provenance']['builder_sha256'] != builder_hash or len(parent['source_candidates']) != 1:
        raise ValueError('Current single-candidate parent required')
    candidate = parent['source_candidates'][0]
    source = review_source_path(repo, parent)
    if source.stat().st_size > 40 * 1024 * 1024 or sha(source) != parent['filing']['sha256']:
        raise ValueError('Original source changed or exceeds cap')
    money = candidate['source_values']['fair_value']
    if money['amount'] != '0' or money['display_unit'] != '1000' or money['currency'] != 'USD':
        raise ValueError('Expected disclosed USD zero in thousands')
    facts = [f for c in money['cells'] for f in c.get('inline_facts', [])]
    if len(facts) != 1 or facts[0]['format'] != 'ixt:fixed-zero':
        raise ValueError('Expected single explicitly tagged zero')
    target = run / 'zero_control_packets_44'
    target.mkdir()
    source_root = run / 'zero_control_sources_44'
    changed_dir = source_root / str(int(parent['output_position']['cik']))
    changed_dir.mkdir(parents=True)
    print('Copying one source and altering one explicit fair-value fact', flush=True)
    soup = BeautifulSoup(source.read_bytes(), 'lxml')
    matches = [tag for tag in soup.find_all('ix:nonfraction')
               if tag.get('name') == facts[0]['name'] and tag.get('contextref') == facts[0]['context_id']]
    if len(matches) != 1:
        raise ValueError('Target source fact is not unique')
    tag = matches[0]
    if tag.get('format') != 'ixt:fixed-zero' or tag.get('scale') != '3':
        raise ValueError('Source transform changed')
    tag['format'] = 'ixt:num-dot-decimal'
    tag.clear()
    tag.append('1')
    changed_path = changed_dir / source.name
    with changed_path.open('x', encoding='utf-8') as stream:
        stream.write(str(soup))
    del soup
    caches = {'disclosed_zero': SourceCache(html_cache_dir=repo / 'data/raw/filings/bdc_html'),
              'missed_positive_fv': SourceCache(html_cache_dir=source_root)}
    refs, records = {}, []
    for kind, cache in caches.items():
        flag, output = deepcopy(parent['flag']), deepcopy(parent['output_position'])
        row_id = 'ROW-' + fingerprint([PARENT, 'zero_control_44', kind])[:16]
        flag['row_id'] = output['row_id'] = row_id
        provenance = {'holdings_sha256': fingerprint(output), 'flags_sha256': fingerprint(flag),
            'builder_sha256': builder_hash, 'controlled_mutation': {
                'kind': kind, 'parent_packet': fingerprint(parent),
                'parent_row_id': PARENT, 'original_source_sha256': parent['filing']['sha256'],
                'output_fair_value': '0', 'source_fair_value': '0' if kind == 'disclosed_zero' else '1000'}}
        packet = build_bundle(flag, [output], provenance, cache=cache)
        if packet['evidence_status']['status'] != 'ready_for_model' or len(packet['source_candidates']) != 1:
            raise ValueError('Control failed readiness or changed candidate count')
        actual = packet['source_candidates'][0]
        for field in ('evidence_id', 'headers', 'identity_evidence', 'period_evidence', 'notes', 'section_context'):
            if actual.get(field) != candidate.get(field):
                raise ValueError('Unrelated source evidence changed: ' + field)
        expected_amount = provenance['controlled_mutation']['source_fair_value']
        if actual['source_values']['fair_value']['amount'] != expected_amount:
            raise ValueError('Unexpected source amount')
        if actual['comparisons']['fair_value']['agrees_at_display_precision'] != (kind == 'disclosed_zero'):
            raise ValueError('Control comparison does not represent the intended error')
        write(target / ('C104_' + row_id + '.json'), packet)
        refs[row_id] = {'expected': 'false_alarm' if kind == 'disclosed_zero' else 'real_error',
            'expected_source': candidate['evidence_id'], 'parent_row_id': PARENT,
            'reviewed_source_fair_value': expected_amount, 'audit': None,
            'reference_basis': 'Frozen synthetic C104 control; original identity and unrelated evidence retained.'}
        records.append({'row_id': row_id, 'kind': kind, 'packet_fingerprint': fingerprint(packet),
            'source_sha256': packet['filing']['sha256'], 'expected_source': candidate['evidence_id'],
            'source_fair_value': expected_amount, 'output_fair_value': '0'})
    if sha(source) != parent['filing']['sha256'] or sha(ROOT / 'pipeline/jev_bundles.py') != builder_hash:
        raise ValueError('Original source or builder changed')
    write(run / 'zero_control_references_44.json', refs)
    write(run / 'zero_control_design_44.json', {'cases': records, 'builder_sha256': builder_hash,
        'parent_row_id': PARENT, 'original_source_unchanged': True, 'api_calls': 0,
        'limitation': 'Synthetic paired control on one existing position, not new natural error evidence.'})
    print(json.dumps({'prepared_controls': len(records), 'expected': ['false_alarm', 'real_error']}), flush=True)


if __name__ == '__main__':
    timer = threading.Timer(180, lambda: os._exit(124))
    timer.daemon = True
    timer.start()
    try:
        main()
    finally:
        timer.cancel()
