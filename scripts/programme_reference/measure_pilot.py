"""Bounded saved-candidate pilot; source preparation must precede comparison.

Run from the repository root with --source-dir and --output-dir under scratch/.
Raw facts are tag-copy probes, not reviewed lot rosters or acceptance gold.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import threading
from pathlib import Path

import duckdb

from scripts.programme_reference.evaluate import match_roster
from scripts.gold.estimate_gold import load_labels, pos_error

ROOT = Path(__file__).resolve().parents[2]
REFERENCE = ROOT / 'docs/production_stack/programme_reference_evidence_2026-09-09'


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def read_csv(path):
    with Path(path).open(encoding='utf-8-sig', newline='') as stream:
        return list(csv.DictReader(stream))


def write_csv(path, rows):
    if not rows:
        raise ValueError('Expected nonempty measurement table: ' + str(path))
    with Path(path).open('w', encoding='utf-8', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def sql_string(value):
    return "'" + str(value).replace("'", "''") + "'"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-dir', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    out = args.output_dir.resolve()
    if not out.is_relative_to(ROOT / 'scratch'):
        raise ValueError('Measurement outputs must be under scratch/')
    out.mkdir(parents=True, exist_ok=True)
    timer = threading.Timer(240, lambda: os._exit(124))
    timer.daemon = True
    timer.start()
    candidate = ROOT / 'data/output/private_markets_holdings.csv'
    input_paths = [candidate, REFERENCE / 'reference_pilot.csv', REFERENCE / 'obligations.csv',
                   ROOT / 'data/gold/labels/position_labels.jsonl',
                   ROOT / 'scripts/gold/estimate_gold.py', Path(__file__),
                   ROOT / 'scripts/programme_reference/evaluate.py',
                   ROOT / 'scripts/programme_reference/source_reader.py']
    identities = [{'path': str(p.relative_to(ROOT)), 'sha256': sha(p),
                   'bytes': p.stat().st_size, 'mtime_ns': p.stat().st_mtime_ns} for p in input_paths]
    (out / 'input_manifest.json').write_text(json.dumps(identities, indent=2), encoding='utf-8')
    pilot = read_csv(REFERENCE / 'reference_pilot.csv')
    obligations = read_csv(REFERENCE / 'obligations.csv')
    for row in obligations:
        if row['cik'] == '0002012139' and row['report_date'] == '2025-03-31':
            row.update(eligibility_status='eligible_source_investments',
                       evidence_ids='PILOT-FORTRESS-2025Q1',
                       follow_up='Direct June 2025 management statement and March 2025 comparative Level 3 rollforward; full source roster unavailable.')
    write_csv(out / 'obligations_v2.csv', obligations)
    print('Candidate pinned; freezing source-only probes.', flush=True)
    facts = []
    source_rows = []
    sources = []
    packets = []
    anchors = []
    unit_map = {}
    for cluster in pilot:
        path = args.source_dir / (cluster['reference_id'] + '.json')
        document = json.loads(path.read_text(encoding='utf-8'))
        if document.get('path'):
            original = ROOT / document['path']
            assert sha(original) == document['sha256'], 'Source changed: ' + str(original)
            assert document['reader_sha256'] == sha(ROOT / 'scripts/programme_reference/source_reader.py')
            sources.append({k: document[k] for k in ('reference_id', 'path', 'sha256', 'bytes', 'mtime_ns')})
        for row in document.get('source_candidates', []):
            source_rows.append({'reference_id': cluster['reference_id'], 'observation_id': row['source_observation_id'],
                'context_id': row['context_id'], 'row_xpath': row['row_xpath'], 'table_xpath': row['table_xpath'],
                'cells_json': json.dumps(row['cells']), 'dimensions_json': json.dumps(row['context']['dimensions']),
                'total_word_flag': row['total_word_flag'], 'review_status': row['review_status']})
            for fact in row['facts']:
                facts.append({'reference_id': cluster['reference_id'], 'cik': cluster['cik'],
                    'report_date': cluster['report_date'], 'accession': cluster['accession'],
                    'context_id': row['context_id'], 'observation_id': row['source_observation_id'],
                    **{k: fact[k] for k in ('field', 'concept', 'fact_id', 'value', 'currency', 'rounding_bound', 'parse_status', 'unit_ref', 'raw_text')}})
                unit_map[(cluster['reference_id'], fact['unit_ref'])] = fact['currency']
        for anchor in document.get('anchor_candidates', []):
            anchors.append({'reference_id': cluster['reference_id'],
                **{k: anchor[k] for k in ('concept', 'value', 'currency', 'rounding_bound', 'context_id', 'row_xpath', 'table_xpath')},
                'cells_json': json.dumps(anchor['cells']), 'basis_verified': False,
                'status': 'unreviewed_anchor_candidate; includes components, percentages and repeats'})
        packets.append({'reference_id': cluster['reference_id'], 'cik': cluster['cik'],
            'report_date': cluster['report_date'], 'component': cluster['reason'],
            'source_status': document['status'], 'source_fact_rows': len(document.get('source_candidates', [])),
            'roster_status': 'reviewed_development_two_lots' if cluster['reference_id'] == 'REF-0001899017-2023-06-30' else 'not_adjudicated',
            'primary_anchor_status': 'not_basis_certified', 'acceptance_label_status': 'none; calibration only'})
    write_csv(out / 'source_documents.csv', sources)
    write_csv(out / 'source_rows.csv', source_rows)
    write_csv(out / 'source_facts.csv', facts)
    write_csv(out / 'source_anchor_candidates.csv', anchors)
    write_csv(out / 'pilot_status.csv', packets)
    write_csv(out / 'source_units.csv', [{'reference_id': k[0], 'unit_ref': k[1], 'currency': v} for k, v in unit_map.items()])
    del source_rows, facts, anchors
    db = duckdb.connect(config={'memory_limit': '2GB', 'threads': 2})
    db.execute('SET temp_directory=' + sql_string(out / 'duckdb_temp'))

    def load(name, path):
        db.execute(f'CREATE TEMP TABLE {name} AS SELECT * FROM read_csv(?, all_varchar=true)', [str(path)])

    def export(name, query):
        db.execute(f'COPY ({query}) TO {sql_string(out / name)} (HEADER, FORMAT CSV)')

    load('obligations', out / 'obligations_v2.csv')
    load('pilot', REFERENCE / 'reference_pilot.csv')
    db.execute('''CREATE TEMP TABLE candidate AS SELECT h.* FROM read_csv(?, all_varchar=true) h
        SEMI JOIN obligations o ON lpad(h.cik,10,'0')=o.cik AND h.report_date=o.report_date''', [str(candidate)])
    export('quarter_denominators.csv', '''SELECT report_date, count(*) all_obligations,
        count(*) FILTER(WHERE eligibility_status LIKE 'eligible%') eligible,
        count(*) FILTER(WHERE eligibility_status='not_yet_investment_operating') pre_operation,
        count(*) FILTER(WHERE eligibility_status LIKE 'unresolved%') unresolved,
        count(*) FILTER(WHERE eligibility_status LIKE 'eligible%' AND cast(holdings_rows AS BIGINT)>0) eligible_with_saved_rows,
        count(*) FILTER(WHERE eligibility_status LIKE 'eligible%' AND cast(holdings_rows AS BIGINT)=0) eligible_missing_rows
        FROM obligations GROUP BY report_date ORDER BY report_date''')
    export('pilot_candidate_totals.csv', '''SELECT p.reference_id,p.cik,p.report_date,p.reason,
        count(h.cik) candidate_rows,sum(try_cast(h.fair_value AS DOUBLE)) published_signed_fv,
        sum(abs(try_cast(h.fair_value AS DOUBLE))) published_abs_fv,
        count(*) FILTER(WHERE h.cik IS NOT NULL AND try_cast(h.fair_value AS DOUBLE) IS NULL) missing_fv_rows,
        sum(CASE WHEN lower(coalesce(h.is_subsidiary,'')) NOT IN ('true','1') THEN try_cast(h.fair_value AS DOUBLE) ELSE 0 END) excluding_subsidiary_diagnostic
        FROM pilot p LEFT JOIN candidate h ON lpad(h.cik,10,'0')=p.cik AND h.report_date=p.report_date
        GROUP BY ALL ORDER BY p.reference_id''')
    load('raw_facts', out / 'source_facts.csv')
    load('source_units', out / 'source_units.csv')
    db.execute('''CREATE TEMP TABLE reference_fields AS SELECT reference_id,cik,report_date,accession,context_id,field,
        count(*) evidence_occurrences,
        count(DISTINCT coalesce(value,'NULL')||'|'||coalesce(currency,'NULL')) variants,
        max(try_cast(value AS DECIMAL(38,10))) reference_value,
        min(try_cast(rounding_bound AS DECIMAL(38,10))) rounding_bound,
        max(currency) reference_currency
        FROM raw_facts WHERE field != 'reported_rate' GROUP BY ALL''')
    mapping = {'fair_value': 'fair_value', 'cost': 'cost', 'principal_amount': 'principal_amount',
               'shares_held': 'shares_held', 'cash_rate': 'interest_rate', 'pik_rate': 'pik_rate',
               'basis_spread': 'basis_spread', 'pct_of_net_assets': 'pct_of_net_assets'}
    money = {'fair_value', 'cost', 'principal_amount'}
    unions = []
    for field, column in mapping.items():
        currency_column = column + '_currency'
        unit_expr = 'h.' + currency_column if field in money else 'NULL::VARCHAR'
        unions.append(f'''SELECT p.reference_id,h.src_context_id context_id,h.accession_number accession,
            '{field}' field,try_cast(h.{column} AS DECIMAL(38,10)) actual_value,
            {unit_expr} actual_unit,h.row_id,h.bdc_investment_identifier
            FROM candidate h JOIN pilot p ON lpad(h.cik,10,'0')=p.cik AND h.report_date=p.report_date''')
    db.execute('CREATE TEMP TABLE actual_fields AS ' + ' UNION ALL '.join(unions))
    export('tag_copy_fields.csv', '''WITH joined AS (
        SELECT r.*,count(a.context_id) OVER(PARTITION BY r.reference_id,r.context_id,r.field) candidate_rows,
        a.actual_value,a.row_id,a.bdc_investment_identifier,a.actual_unit,
        CASE WHEN a.actual_unit IS NULL THEN NULL
             WHEN regexp_matches(a.actual_unit,'(^|:)[A-Z]{3}$') THEN regexp_extract(a.actual_unit,'([A-Z]{3})$',1)
             ELSE u.currency END actual_currency
        FROM reference_fields r LEFT JOIN actual_fields a
        ON r.reference_id=a.reference_id AND r.context_id=a.context_id AND r.accession=a.accession AND r.field=a.field
        LEFT JOIN source_units u ON a.reference_id=u.reference_id AND a.actual_unit=u.unit_ref)
        SELECT *,CASE
          WHEN candidate_rows=0 THEN 'no_exact_candidate_context'
          WHEN candidate_rows>1 THEN 'ambiguous_candidate_context'
          WHEN variants>1 THEN 'conflicting_source_facts'
          WHEN reference_value IS NULL THEN 'unassessable_reference_value'
          WHEN actual_value IS NULL THEN 'missing_candidate_value'
          WHEN field IN ('fair_value','cost','principal_amount') AND reference_currency IS NULL THEN 'unresolved_reference_currency'
          WHEN field IN ('fair_value','cost','principal_amount') AND actual_currency IS NULL THEN 'unresolved_candidate_currency'
          WHEN field IN ('fair_value','cost','principal_amount') AND reference_currency!=actual_currency THEN 'currency_mismatch'
          WHEN rounding_bound IS NULL AND reference_value!=actual_value THEN 'rounding_not_established'
          WHEN abs(reference_value-actual_value)<=coalesce(rounding_bound,0) THEN 'within_source_precision'
          ELSE 'value_mismatch' END comparison_status,
          abs(reference_value-actual_value) absolute_numeric_difference
        FROM joined ORDER BY reference_id,context_id,field,row_id''')
    load('field_results', out / 'tag_copy_fields.csv')
    export('tag_copy_summary.csv', '''SELECT report_date,field,comparison_status,count(*) observations
        FROM field_results GROUP BY ALL ORDER BY ALL''')
    print('Tag-copy probes complete; comparing existing selected labels.', flush=True)
    cohorts = {r['cik'] for r in obligations}
    labels = [r for r in load_labels(ROOT / 'data/gold/labels/position_labels.jsonl')
              if r['cik'] in cohorts and '2023-03-31' <= r['report_date'] <= '2026-03-31']
    gold = []
    for label in labels:
        found = db.execute('''SELECT fair_value,cost,index_classification,lien_position,row_id FROM candidate
            WHERE lpad(cik,10,'0')=? AND report_date=? AND accession_number=? AND bdc_investment_identifier=?''',
            [label['cik'], label['report_date'], label['accession'], label['source_identifier']]).fetchall()
        fields = ['fair_value', 'cost', 'index_classification', 'lien_position', 'row_id']
        actual = dict(zip(fields, found[0])) if len(found) == 1 else {}
        for name in ('fair_value', 'cost'):
            actual[name] = float(actual[name]) if actual.get(name) else None
        score = pos_error(label, {'pipeline': actual}) if len(found) == 1 else {'errs': {}, 'checked': {}}
        for field, target in [('fair_value', 'fair_value'), ('cost', 'cost'), ('classification', 'index_classification'), ('lien', 'lien_position')]:
            gold.append({'label_key': label['_key'], 'cik': label['cik'], 'report_date': label['report_date'],
                'stored_label_status': label['label_status'], 'field': field, 'reference': label.get('true_' + field),
                'candidate': actual.get(target), 'join_count': len(found),
                'legacy_checked': field in score['checked'], 'legacy_error': score['errs'].get(field),
                'exact_match': label.get('true_' + field) == actual.get(target) if field in score['checked'] else None,
                'row_id': actual.get('row_id'), 'status': 'selected_tail_legacy_1pct; not programme B2 or new holdout'})
    write_csv(out / 'legacy_label_comparison.csv', gold)
    load('gold_results', out / 'legacy_label_comparison.csv')
    export('legacy_label_summary.csv', '''SELECT field,join_count,legacy_checked,legacy_error,count(*) labels
        FROM gold_results GROUP BY ALL ORDER BY ALL''')
    bain_candidate = db.execute("SELECT src_context_id, fair_value FROM candidate WHERE lpad(cik,10,'0')='0001899017' AND report_date='2023-06-30'").fetchall()
    # Complete two-lot development roster already reviewed before this comparison.
    bain = match_roster([{'key': 'C_dc09c8b1-abd8-43ad-a596-2a8476dee264', 'fair_value': 71250},
                         {'key': 'C_5caaf08f-afab-4d3d-bbe2-2d33a4944164', 'fair_value': 575000}],
                        [{'key': context, 'fair_value': fv} for context, fv in bain_candidate])
    bain['scope'] = 'Bain 2023Q2 complete two-lot development schedule only; not held-out acceptance'
    (out / 'reviewed_roster_result.json').write_text(json.dumps(bain, indent=2), encoding='utf-8')
    export('esdec_candidate_rows.csv', '''SELECT cik,report_date,accession_number,bdc_investment_identifier,
        fair_value,cost,principal_amount,fair_value_currency,cost_currency,principal_amount_currency,
        basis_spread,maturity_date,interest_rate,entity_id,position_id,row_id,src_context_id
        FROM candidate WHERE lpad(cik,10,'0')='0001837532' AND report_date IN ('2023-09-30','2023-12-31','2024-03-31')
        AND bdc_investment_identifier ILIKE '%esdec%' ORDER BY report_date,bdc_investment_identifier''')
    db.close()
    for item in identities:
        path = ROOT / item['path']
        assert (path.stat().st_size, path.stat().st_mtime_ns) == (item['bytes'], item['mtime_ns'])
    assert sha(candidate) == identities[0]['sha256']
    (out / 'verification.json').write_text(json.dumps({'candidate_hash_unchanged': True,
        'pinned_input_stats_unchanged': True, 'source_documents_rehashed': len(sources),
        'pilot_clusters': len(pilot), 'legacy_labels': len(labels), 'programme_verdict': 'NOT_ASSESSABLE'}, indent=2), encoding='utf-8')
    timer.cancel()
    print('Pilot completed; isolated results at ' + str(out), flush=True)


if __name__ == '__main__':
    main()
