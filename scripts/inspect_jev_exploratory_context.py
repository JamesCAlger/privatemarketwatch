"""Inspect one suspicious current position found during historical-reference review."""
import argparse
import json
import os
from pathlib import Path
import sys
import threading
import duckdb
from bs4 import BeautifulSoup, NavigableString

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from pipeline.jev_screening import fingerprint
from scripts.jev_pilot_session import install_read_only_guard, read, sha, write
from scripts.review_jev_sources import context_fact_inventory, exact_context_facts, text


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--run-root', type=Path, required=True)
    args = parser.parse_args()
    repo, run = args.repo.resolve(), args.run_root.resolve()
    if repo == ROOT or not run.is_relative_to(repo / 'data/pilot/jev_screening'):
        raise ValueError('Isolated pilot required')
    install_read_only_guard(repo, run)
    parent_path = run / 'historical_error_candidates_00ddb8e888a19fd3.json'
    parent = read(parent_path)
    holdings_path = repo / 'data/output/private_markets_holdings.csv'
    if sha(holdings_path) != parent['input_sha256'][str(holdings_path.relative_to(repo))]:
        raise ValueError('Current holdings differ from parent diagnostic')
    positions = [p for g in parent['groups'] for p in g['named_current_positions']
                 if p['row_id'] == 'ROW-ecc8c78a0d433f52']
    if len(positions) != 1:
        raise ValueError('Expected one exploratory position')
    position = positions[0]
    if position['cik'] != '0001825265' or position['report_date'] != '2025-09-30':
        raise ValueError('Unexpected exploratory scope')
    source = repo / 'data/raw/filings/bdc_html/1825265/000119312525276913.html'
    if source.stat().st_size > 40 * 1024 * 1024:
        raise ValueError('Source byte limit')
    digest = sha(source)
    print('Inspecting one exploratory TCW position from cached source', flush=True)
    soup = BeautifulSoup(source.read_bytes(), 'lxml')
    tables = [t for t in soup.find_all('table') if any(r.find(['td', 'th']) for r in t.find_all('tr'))]
    if sum(len(t.find_all('tr')) for t in tables) > 10000:
        raise ValueError('Source row limit')
    table_ids = {id(table): index for index, table in enumerate(tables)}
    context, facts = exact_context_facts(soup, position['src_context_id'])
    if context is None:
        raise ValueError('Declared context not found')
    inventory = context_fact_inventory(facts, table_ids)
    coordinates = sorted({(f['table_index'], f['row_index']) for f in inventory
                          if f.get('table_index') is not None and f.get('row_index') is not None})
    excerpts = []
    for ti, ri in coordinates:
        table = tables[ti]
        rows = [r for r in table.find_all('tr') if r.find(['td', 'th'])]
        preceding, size = [], 0
        for element in table.previous_elements:
            if isinstance(element, NavigableString) and element.strip():
                value = ' '.join(str(element).split())
                preceding.append(value)
                size += len(value)
                if size > 2500:
                    break
        excerpts.append({'table_index': ti, 'row_index': ri,
                         'header_rows': [text(r) for r in rows[:3]],
                         'visible_cells': [text(c) for c in rows[ri].find_all(['td', 'th'])],
                         'neighbour_rows': [text(r) for r in rows[max(0, ri-2):ri+3]],
                         'preceding_text_excerpt': ' '.join(reversed(preceding))})
    issuer_rows = []
    for ti, table in enumerate(tables):
        rows = [r for r in table.find_all('tr') if r.find(['td', 'th'])]
        for ri, row in enumerate(rows):
            if 'superior industries' in text(row).casefold():
                if len(issuer_rows) >= 40 or len(text(row)) > 12000:
                    raise ValueError('Issuer row inventory cap exceeded')
                issuer_rows.append({'table_index': ti, 'row_index': ri,
                                    'header_rows': [text(r) for r in rows[:3]],
                                    'visible_row': text(row),
                                    'neighbour_rows': [text(r) for r in rows[max(0, ri-1):ri+2]],
                                    'row_facts': [{'attributes': dict(f.attrs), 'visible_text': text(f)}
                                                  for f in row.find_all('ix:nonfraction')]})
    if sha(source) != digest or sha(holdings_path) != parent['input_sha256'][str(holdings_path.relative_to(repo))]:
        raise ValueError('Source or holdings changed')
    bdc_path = repo / 'data/output/bdc_holdings.csv'
    flags_path = repo / 'data/output/row_validation_issues.csv'
    diagnostic_hashes = {str(p.relative_to(repo)): sha(p) for p in (bdc_path, holdings_path, flags_path)}
    with duckdb.connect() as con:
        con.execute("SET memory_limit='1GB'")
        con.execute('SET threads=2')
        def rows(sql, parameters):
            result = con.execute(sql, parameters)
            columns = [c[0] for c in result.description]
            found = [dict(zip(columns, values)) for values in result.fetchall()]
            if len(found) > 100:
                raise ValueError('Exploratory lineage exceeds row cap')
            return found
        raw_rows = rows("SELECT * FROM read_csv(?, all_varchar=true) WHERE cik=? AND accession_number=? "
                        "AND investment_identifier ILIKE '%Superior Industries%' LIMIT 101",
                        [str(bdc_path), position['cik'], position['accession_number']])
        published_rows = rows("SELECT * FROM read_csv(?, all_varchar=true) WHERE cik=? AND report_date=? "
                              "AND (src_context_id IN (?,?) OR TRY_CAST(fair_value AS DOUBLE)=12115467) LIMIT 101",
                              [str(holdings_path), position['cik'], position['report_date'],
                               position['src_context_id'], 'C_f1dd68ce-9df4-4ad8-9279-784ba8aaf308'])
        issues = rows('SELECT * FROM read_csv(?, all_varchar=true) WHERE cik=? AND report_date=? AND row_id=? LIMIT 101',
                      [str(flags_path), position['cik'], position['report_date'], position['row_id']])
    if any(sha(repo / path) != value for path, value in diagnostic_hashes.items()):
        raise ValueError('Lineage input changed during inspection')
    report = {'parent_sha256': sha(parent_path), 'published_position': position,
              'source_relative_path': str(source.relative_to(repo)), 'source_sha256': digest,
              'context_xml': str(context), 'exact_context_facts': inventory, 'row_excerpts': excerpts,
              'issuer_row_inventory': issuer_rows,
              'diagnostic_input_sha256': diagnostic_hashes,
              'bdc_rows_for_named_issuer_in_accession': raw_rows,
              'published_context_or_equal_fv_candidates': published_rows,
              'current_position_issues': issues,
              'exploratory_positions': 1, 'frozen_experiment_cases': 67, 'api_calls': 0,
              'production_changes': 0, 'source_truth_certified': False,
              'limitation': 'One additional source investigation, outside the frozen classifier experiment. No full sibling, note, ownership or donor-lineage audit.'}
    destination = run / ('exploratory_context_' + fingerprint(report)[:16] + '.json')
    if not destination.exists():
        write(destination, report)
    print(json.dumps({'artifact': destination.name, 'facts': len(inventory), 'rows': len(excerpts)}), flush=True)


if __name__ == '__main__':
    timer = threading.Timer(120, lambda: os._exit(124))
    timer.daemon = True
    timer.start()
    try:
        main()
    finally:
        timer.cancel()
