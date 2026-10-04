"""Offline context sizing on four frozen cases; no API calls or source downloads."""
import argparse
import json
import os
from pathlib import Path
import sys
import threading

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from pipeline.jev_bundles import make_request, parse_source
from scripts.jev_pilot_session import install_read_only_guard, read, sha, write
from scripts.review_jev_sources import review_source_path

CASES = ('ROW-0a3fe5a6482a78b9', 'ROW-1a734ef6a228d65a',
         'ROW-1c2a72c58fbc2d87', 'ROW-0d749c119e46277b')


def main():
    import duckdb
    import tiktoken
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', required=True, type=Path)
    parser.add_argument('--run-root', required=True, type=Path)
    args = parser.parse_args()
    repo, run = args.repo.resolve(), args.run_root.resolve()
    if repo == ROOT or not run.is_relative_to(repo / 'data/pilot/jev_screening'):
        raise ValueError('Isolated pilot required')
    install_read_only_guard(repo, run)
    codec = tiktoken.get_encoding('cl100k_base')
    def count(value):
        return len(codec.encode(json.dumps(value, ensure_ascii=True, separators=(',', ':')), disallowed_special=()))
    holdings = repo / 'data/output/private_markets_holdings.csv'
    holdings_hash = sha(holdings)
    db = duckdb.connect(config={'memory_limit': '1GB', 'threads': '2'})
    records = []
    for row_id in CASES:
        paths = list((run / 'current_development_packets_20').glob('*_' + row_id + '.json'))
        if len(paths) != 1:
            raise ValueError('Expected one frozen case')
        packet = read(paths[0])
        if packet['provenance']['holdings_sha256'] != holdings_hash:
            raise ValueError('Holdings changed')
        source = review_source_path(repo, packet)
        if source.stat().st_size > 40 * 1024 * 1024 or sha(source) != packet['filing']['sha256']:
            raise ValueError('Source changed or exceeds cap')
        print('Sizing case:', row_id, flush=True)
        raw = source.read_bytes()
        parsed = parse_source(raw)
        position = packet['output_position']
        period = position['report_date']
        tables = [t for t in parsed['tables'] if t['report_date'] == period
                  and 'cost' in t['headers'] and 'fair_value' in t['headers']]
        notes = [n for n in parsed['notes'] if n['report_date'] == period]
        context_ids = {f['context_id'] for t in tables for row in t['rows'] for cell in row
                       for f in cell.get('inline_facts', [])}
        contexts = {k: v for k, v in parsed['contexts'].items() if k in context_ids}
        visible = [{'table_index': t['table_index'], 'title_context': t['title_context'],
                    'rows': [[c['text'] for c in row] for row in t['rows']]} for t in tables]
        result = db.execute('''SELECT * FROM read_csv_auto(?, all_varchar=true)
            WHERE TRY_CAST(cik AS BIGINT)=? AND report_date=? ORDER BY row_id LIMIT 5001''',
            [str(holdings), int(position['cik']), period])
        columns = [c[0] for c in result.description]
        rows = result.fetchall()
        if len(rows) > 5000:
            raise ValueError('Fund-quarter row cap exceeded')
        published = {'columns': columns, 'rows': rows}
        core_fields = ('row_id', 'issuer_name', 'instrument_description', 'bdc_investment_identifier',
                       'src_context_id', 'cost', 'cost_reported', 'cost_source', 'cost_currency',
                       'fair_value', 'fair_value_currency', 'shares_held', 'principal_amount',
                       'maturity_date', 'accounting_scope_id', 'accounting_record_class')
        selected_columns = [c for c in core_fields if c in columns]
        indices = [columns.index(c) for c in selected_columns]
        published_core = {'columns': selected_columns, 'rows': [[r[i] for i in indices] for r in rows]}
        request = make_request(packet)
        longest = max(count(q) for q in request['questions'].values())
        variants = {
            'current_state': request['state'],
            'broad_visible_tables': {'tables': visible, 'notes': notes},
            'broad_structured_tables': {'tables': tables, 'notes': notes, 'contexts': contexts},
            'published_fund_quarter': published,
            'published_core_fields': published_core,
            'broad_visible_plus_core_fields': {'tables': visible, 'notes': notes, 'published': published_core},
            'broad_visible_plus_published': {'tables': visible, 'notes': notes, 'published': published},
            'broad_structured_plus_published': {'tables': tables, 'notes': notes, 'contexts': contexts, 'published': published},
        }
        sizes = {name: {'state_proxy_tokens': count(state),
                        'state_plus_longest_question_proxy_tokens': count(state) + longest}
                 for name, state in variants.items()}
        records.append({'row_id': row_id, 'cik': position['cik'], 'period': period,
                        'source_sha256': packet['filing']['sha256'], 'source_bytes': len(raw),
                        'whole_filing_html_proxy_tokens': count(raw.decode('utf-8')),
                        'selected_tables': len(tables), 'selected_rows': sum(len(t['rows']) for t in tables),
                        'selected_notes': len(notes), 'published_rows': len(rows), 'sizes': sizes})
        del parsed, raw, variants
    db.close()
    if sha(holdings) != holdings_hash:
        raise ValueError('Holdings changed during measurement')
    report = {'schema_version': 'jev-context-sizing.v1', 'records': records,
              'holdings_sha256': holdings_hash, 'script_sha256': sha(Path(__file__)),
              'api_calls': 0, 'production_clearance_enabled': False,
              'limitations': ['cl100k estimates are not the provider tokenizer or billing.',
                  'Broad tables are selected by parsed date and monetary headers: complete SOI recall is not certified.',
                  'Visible text loses geometry, units and XBRL identity; structured tables retain more evidence.',
                  'Broad variants measure payload size only and are not validated classification requests.',
                  'Whole filing HTML includes unrelated statements and hidden facts.',
                  'Published rows use columns plus row arrays; core-field variants omit nonselected pipeline columns.',
                  'Core-field projection is a sizing comparison, not a sufficient evidence contract for every rule.']}
    write(run / 'context_scope_measurement_22.json', report)
    print(json.dumps(records), flush=True)


if __name__ == '__main__':
    timer = threading.Timer(180, lambda: os._exit(124))
    timer.daemon = True
    timer.start()
    try:
        main()
    finally:
        timer.cancel()
