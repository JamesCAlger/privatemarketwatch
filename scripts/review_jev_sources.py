"""Extract raw cached evidence for source review, independently of bundle values.

Does not assign truth labels or stamp audit checks. A reviewer must inspect the
source rows, notes, contexts and units before creating reference records.
"""
from __future__ import annotations
import argparse
from collections import defaultdict
import json
import os
from pathlib import Path
import re
import sys
import threading

from bs4 import BeautifulSoup, NavigableString

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.jev_pilot_session import install_read_only_guard, read, sha, write


def text(element):
    return ' '.join(element.get_text(' ', strip=True).split()) if element else ''


def review_source_path(repo: Path, packet: dict) -> Path:
    root = (repo / 'data/raw/filings/bdc_html').resolve()
    declared = packet.get('filing', {}).get('path')
    if declared:
        path = Path(declared).resolve()
    else:
        output = packet['output_position']
        cik, accession = str(output.get('cik', '')), str(output.get('accession_number', ''))
        if not re.fullmatch(r'\d{1,10}', cik) or not re.fullmatch(r'\d{10}-\d{2}-\d{6}', accession):
            raise ValueError('Missing or invalid cached source identity')
        path = (root / str(int(cik)) / (accession.replace('-', '') + '.html')).resolve()
    if not path.is_relative_to(root):
        raise ValueError('Review source must remain in the cached BDC filings root')
    return path


def exact_context_facts(soup, context_id):
    if not isinstance(context_id, str) or not context_id.strip():
        return None, []
    return soup.find(id=context_id), soup.find_all('ix:nonfraction', attrs={'contextref': context_id})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--run-root', type=Path, required=True)
    parser.add_argument('--bundles', type=Path, required=True)
    parser.add_argument('--label', required=True)
    parser.add_argument('--rule', choices=['C107', 'C104', 'X08'], default='C107')
    parser.add_argument('--include-blocked', action='store_true')
    parser.add_argument('--row-id', action='append', default=[])
    args = parser.parse_args()
    repo, out = args.repo.resolve(), args.run_root.resolve()
    if repo == ROOT or not out.is_relative_to(repo / 'data/pilot/jev_screening'):
        raise ValueError('Isolated worktree and pilot run required')
    if not args.label.replace('_', '').isalnum():
        raise ValueError('Invalid label')
    install_read_only_guard(repo, out)
    if not args.bundles.resolve().is_relative_to(out):
        raise ValueError('Use frozen packets within the pilot run')
    groups = defaultdict(list)
    for path in sorted(args.bundles.glob(args.rule + '*.json')):
        packet = read(path)
        if args.row_id and packet['flag']['row_id'] not in args.row_id:
            continue
        if args.include_blocked or packet['evidence_status']['status'] == 'ready_for_model':
            groups[str(review_source_path(repo, packet))].append(packet)
    if sum(map(len, groups.values())) > 40:
        raise ValueError('Review limit exceeded')
    reports = []
    for filename, packets in groups.items():
        source = Path(filename)
        if source.stat().st_size > 40 * 1024 * 1024:
            raise ValueError('Source limit exceeded')
        source_sha = sha(source)
        if any(p.get('filing', {}).get('sha256') and p['filing']['sha256'] != source_sha for p in packets):
            raise ValueError('Source changed')
        print('Review evidence:', packets[0]['flag']['cik'], packets[0]['flag']['report_date'], flush=True)
        soup = BeautifulSoup(source.read_bytes(), 'lxml')
        document_text = text(soup)
        unit_declarations = [document_text[max(0,m.start()-180):m.end()+180]
                             for m in list(re.finditer(r'\b(?:thousands|millions)\b', document_text, re.I))[:60]]
        negative_cost_notes = [document_text[max(0,m.start()-100):m.end()+850]
                               for m in list(re.finditer(r'negative\s+cost', document_text, re.I))[:12]]
        tables = [t for t in soup.find_all('table') if any(tr.find(['td', 'th']) for tr in t.find_all('tr'))]
        table_ids = {id(t): i for i, t in enumerate(tables)}
        for packet in packets:
            context_id = packet['output_position'].get('src_context_id')
            context, facts = exact_context_facts(soup, context_id)
            concept = 'investmentownedatfairvalue' if args.rule == 'C104' else 'investmentownedatcost'
            cost_facts = [f for f in facts if (f.get('name') or '').split(':')[-1].lower() == concept]
            positions = []
            for fact in cost_facts:
                table, row = fact.find_parent('table'), fact.find_parent('tr')
                if table is None or row is None:
                    continue
                rows = [r for r in table.find_all('tr') if r.find(['td', 'th'])]
                row_index = next(i for i, r in enumerate(rows) if r is row)
                prefix, size = [], 0
                for element in table.previous_elements:
                    if isinstance(element, NavigableString) and element.strip():
                        value = ' '.join(str(element).split())
                        prefix.append(value)
                        size += len(value)
                        if size > 2500:
                            break
                positions.append({'table_index': table_ids[id(table)], 'row_index': row_index,
                                  'preceding_text': ' '.join(reversed(prefix)),
                                  'header_rows': [text(r) for r in rows[:3]],
                                  'visible_row': text(row),
                                  'neighbour_rows': [text(r) for r in rows[max(0,row_index-1):row_index+2]],
                                  'reviewed_concept': concept,
                                  'monetary_fact': {'text': text(fact), 'scale': fact.get('scale', '0'),
                                                'sign': fact.get('sign'), 'unit': text(soup.find(id=fact.get('unitref')))},
                                  'monetary_cell_html': str(fact.find_parent(['td', 'th']))[:1800]})
                positions[-1]['row_monetary_facts'] = [
                    {'concept': f.get('name'), 'text': text(f), 'scale': f.get('scale', '0'),
                     'sign': f.get('sign'), 'format': f.get('format'),
                     'unit': text(soup.find(id=f.get('unitref'))),
                     'cell_html': str(f.find_parent(['td', 'th']))[:1800]}
                    for f in row.find_all('ix:nonfraction', attrs={'contextref': context_id})
                    if (f.get('name') or '').split(':')[-1].lower() in {'investmentownedatcost', 'investmentownedatfairvalue'}]
            issuer = ' '.join(packet['output_position'].get('issuer_name', '').casefold().split())
            issuer_rows, token_rows = [], []
            tokens = list(dict.fromkeys(re.findall(r'[a-z]{3,}', issuer)))[:2]
            if issuer:
                for ti, table in enumerate(tables):
                    for ri, row in enumerate(r for r in table.find_all('tr') if r.find(['td', 'th'])):
                        visible = text(row)
                        if issuer in visible.casefold():
                            issuer_rows.append({'table_index': ti, 'row_index': ri, 'visible_row': visible[:1800]})
                        if tokens and all(token in set(re.findall(r'[a-z]{3,}', visible.casefold())) for token in tokens):
                            token_rows.append({'table_index': ti, 'row_index': ri, 'visible_row': visible[:1800]})
                        if len(issuer_rows) >= 80 or len(token_rows) >= 80:
                            break
                    if len(issuer_rows) >= 80 or len(token_rows) >= 80:
                        break
            reports.append({'row_id': packet['flag']['row_id'], 'source_path': str(source),
                            'source_path_basis': 'packet' if packet.get('filing', {}).get('path') else 'exact_cached_cik_accession',
                            'source_hash_previously_frozen': bool(packet.get('filing', {}).get('sha256')),
                            'source_sha256': source_sha, 'output_position': packet['output_position'],
                            'context_text': text(context), 'context_xml': str(context) if context else None,
                            'unit_declarations': unit_declarations,
                            'negative_cost_notes': negative_cost_notes,
                            'source_positions': positions,
                            'exact_issuer_search': {'query': issuer, 'matches': issuer_rows,
                                                   'truncated': len(issuer_rows) >= 80,
                                                   'limitation': 'Exact visible-name search can miss aliases; not automatic recall certification.'},
                            'token_issuer_search': {'tokens': tokens, 'matches': token_rows,
                                                   'truncated': len(token_rows) >= 80,
                                                   'limitation': 'Broad two-token visible-row search for manual review, not independent automatic recall certification.'},
                            'bundle_values_used_for_extraction': False,
                            'reference_label_assigned': False})
        soup.decompose()
    write(out / (args.label + '.json'), reports)
    print(json.dumps({'review_records': len(reports), 'source_files': len(groups)}), flush=True)


if __name__ == '__main__':
    timer = threading.Timer(180, lambda: os._exit(124))
    timer.daemon = True
    timer.start()
    try:
        main()
    finally:
        timer.cancel()
