"""Mandatory typed CSV/Parquet pairs, including empty legacy auxiliary outputs."""
from __future__ import annotations

import csv
from pathlib import Path
from pipeline.output_schemas import OUTPUT_SCHEMAS
from pipeline.programme.core import ContractError, digest


def columns(text, overrides=None):
    return {name: (overrides or {}).get(name, 'VARCHAR') for name in text.split(',')}


EXTRA_SCHEMAS = {
    'sector_enrichment_audit.csv': columns('row_id,decision_id,value,status,derivation'),
    'input_admission_audit.csv': columns('path,admission_status,loaded,reason,sha256',{'loaded':'BOOLEAN'}),
    'spread_unit_audit.csv': columns('row_id,cik,report_date,identifier,expected_pct,actual_pct',
        {'report_date':'DATE','expected_pct':'DOUBLE','actual_pct':'DOUBLE'}),
    'financial_state_audit.csv': columns('row_id,cost_state,donor_valid,source_cost_value,source_rate_value,rate_kind,coupon_state,maturity_precision',
        {'donor_valid':'BOOLEAN','source_cost_value':'DOUBLE','source_rate_value':'DOUBLE'}),
    'financial_nav_audit.csv': columns('cik,report_date,net_assets,source_sha256,status',{'report_date':'DATE','net_assets':'DOUBLE'}),
    'cost_donor_audit.csv': columns('row_id,method,donor_row_id,donor_date,donor_release,proxy_value',{'donor_date':'DATE','proxy_value':'DOUBLE'}),
    'identity_aliases.csv': columns('kind,scope,legacy_id,identity_id'),
    'agent_fix_application_audit.csv': columns(
        'layer,cik,rule_id,rule_type,status,rows_changed,fv_affected,authoring_rows,authoring_fv,drift,message',
        {'rows_changed': 'BIGINT', 'fv_affected': 'DOUBLE', 'authoring_rows': 'BIGINT', 'authoring_fv': 'DOUBLE'}),
    'entity_lookup.csv': columns('entity_id,canonical_name,normalized_name,issuer_name_variant,source,occurrence_count,cluster_method,cusip,lei',
                                {'occurrence_count': 'BIGINT'}),
    'entity_resolution_stats.csv': {name: 'BIGINT' for name in
        'total_variants,total_entities,bdc_variants,nport_variants,bdc_entities,nport_entities,cross_source_entities,fuzzy_merges,cross_source_merges'.split(',')},
    'pik_transitions.csv': columns('transition_type,source,cik,entity_name,position_id,prior_report_date,current_report_date,prior_status,current_status,prior_evidence,current_evidence,prior_fair_value,current_fair_value',
        {'prior_report_date': 'DATE', 'current_report_date': 'DATE', 'prior_fair_value': 'DOUBLE', 'current_fair_value': 'DOUBLE'}),
    'pik_schedule_proxy_summary.csv': columns('scope,source,index_classification,report_date,report_quarter,total_rows,pik_terms_rows,pik_terms_row_pct,total_fair_value,pik_terms_fair_value,pik_terms_fair_value_pct,unique_positions,pik_terms_unique_positions,first_seen_with_pik_terms_rows,first_seen_with_pik_terms_positions',
        {'report_date': 'DATE', **{n: 'BIGINT' for n in 'total_rows,pik_terms_rows,unique_positions,pik_terms_unique_positions,first_seen_with_pik_terms_rows,first_seen_with_pik_terms_positions'.split(',')},
         **{n: 'DOUBLE' for n in 'pik_terms_row_pct,total_fair_value,pik_terms_fair_value,pik_terms_fair_value_pct'.split(',')}}),
    'pik_schedule_proxy_transitions.csv': columns('transition_type,source,cik,entity_name,position_id,prior_report_date,current_report_date,issuer_name,index_classification,prior_pik_terms_flag,current_pik_terms_flag,prior_pik_terms_rate,current_pik_terms_rate,prior_fair_value,current_fair_value',
        {'prior_report_date': 'DATE', 'current_report_date': 'DATE', 'prior_pik_terms_flag': 'BOOLEAN', 'current_pik_terms_flag': 'BOOLEAN',
         **{n: 'DOUBLE' for n in 'prior_pik_terms_rate,current_pik_terms_rate,prior_fair_value,current_fair_value'.split(',')}}),
}
SCHEMAS = {**OUTPUT_SCHEMAS, **EXTRA_SCHEMAS}
STAGE_CSVS = {
    'unified': ('private_markets_holdings.csv', 'bdc_holdings.csv','agent_fix_application_audit.csv',
                'financial_state_audit.csv','financial_nav_audit.csv','input_admission_audit.csv','spread_unit_audit.csv'),
    'identity': ('private_markets_holdings.csv', 'position_matches.csv', 'position_id_edges.csv',
                 'entity_lookup.csv', 'entity_resolution_stats.csv','financial_state_audit.csv',
                 'financial_nav_audit.csv','cost_donor_audit.csv','identity_aliases.csv','sector_enrichment_audit.csv'),
    'evidence': ('position_pik_status.csv', 'pik_transitions.csv', 'pik_schedule_proxy_summary.csv',
                 'pik_schedule_proxy_transitions.csv'),
    'returns': ('private_markets_holdings.csv','position_returns.csv'),
    'frontend': (),
}
STAGE_FILES={
    'unified':('financial_contract.json','fund_financials.csv','source_refresh.json'),
    'identity':('financial_contract.json','identity_contract.json','identity_registry.duckdb','holdings_release.json','fund_financials.csv'),
    'evidence':(),
    'returns':('holdings_release.json','index_returns.csv','fund_financials.csv'),
    'frontend':('frontend_data.zip','frontend_export.json'),
}
# Export consumes the identity-bound provenance alongside the return series.
STAGE_FILES['returns'] += tuple(name for name in STAGE_FILES['identity']
    if name not in STAGE_FILES['returns']) + ('cost_donor_audit.csv','sector_enrichment_audit.csv')


def contract_identity(stage):
    return digest(dict(csv={name:list(SCHEMAS[name].items()) for name in STAGE_CSVS[stage]},files=STAGE_FILES[stage]))


def required(stage):
    return ['summary.json', 'read_ledger.json'] + list(STAGE_FILES[stage]) + [name for csv_name in STAGE_CSVS[stage]
            for name in (csv_name, str(Path(csv_name).with_suffix('.parquet')))]


def literal(value):
    return "'" + str(value).replace("'", "''") + "'"


def typed_query(path, schema):
    from pipeline.utils import _contract_cast_expr
    with Path(path).open(newline='', encoding='utf-8-sig') as stream:
        header = next(csv.reader(stream), None)
    if header != list(schema):
        raise ContractError('Wrong ordered CSV columns: ' + str(path))
    return ('SELECT ' + ', '.join(_contract_cast_expr(name, kind) for name, kind in schema.items()) +
            ' FROM read_csv(' + literal(Path(path).as_posix()) + ', header=true, all_varchar=true)')


def finalize_pair(path, connection):
    path = Path(path)
    if path.name not in SCHEMAS:
        raise ContractError('No governed artifact contract: ' + path.name)
    schema = SCHEMAS[path.name]
    query = typed_query(path, schema)
    companion = path.with_suffix('.parquet')
    connection.execute('COPY (' + query + ') TO ' + literal(companion.as_posix()) + ' (FORMAT PARQUET)')
    return verify_pair(path, connection)


def verify_pair(path, connection):
    path = Path(path)
    schema = SCHEMAS[path.name]
    query = typed_query(path, schema)
    companion_query = 'SELECT * FROM read_parquet(' + literal(path.with_suffix('.parquet').as_posix()) + ')'
    description = connection.execute('DESCRIBE ' + companion_query).fetchall()
    if [(row[0], row[1]) for row in description] != list(schema.items()):
        raise ContractError('Wrong typed companion schema: ' + path.name)
    # EXCEPT ALL preserves duplicate multiplicity. Typed dates remove only representational differences.
    difference = connection.execute('SELECT count(*) FROM ((' + query + ' EXCEPT ALL ' + companion_query +
                                    ') UNION ALL (' + companion_query + ' EXCEPT ALL ' + query + '))').fetchone()[0]
    if difference:
        raise ContractError('CSV/Parquet values differ: ' + path.name)
    return {'rows': connection.execute('SELECT count(*) FROM (' + companion_query + ')').fetchone()[0],
            'columns': len(schema), 'typed_multiset_difference': 0}


def verify_audit(path, connection):
    query = typed_query(path, SCHEMAS['agent_fix_application_audit.csv'])
    failures = connection.execute("SELECT layer,rule_id,status FROM (" + query +
                                  ") WHERE status IS NULL OR status NOT IN ('ok','no_rows')").fetchall()
    if failures:
        raise ContractError('Admitted correction execution failure: ' + repr(failures[:20]))
