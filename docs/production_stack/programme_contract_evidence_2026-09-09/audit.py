"""Bounded, cache-only programme assessment. No pipeline imports or production writes.

Run from the repository root. Results are observations of saved artifacts, not a
rebuild, source correctness assessment, or release acceptance. Maximum 240 seconds,
two DuckDB threads, 1 GB memory, no disk spill. All outputs stay beside this file.
"""
import ast
import csv
import hashlib
import json
import os
from pathlib import Path
import subprocess
import threading
from datetime import datetime, timezone
from collections import Counter, defaultdict

import duckdb

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
os.chdir(ROOT)
timer = threading.Timer(240, lambda: os._exit(124))
timer.daemon = True
timer.start()
started = datetime.now(timezone.utc).isoformat()
db = duckdb.connect()
db.execute("SET threads=2")
db.execute("SET memory_limit='1GB'")
db.execute("SET temp_directory=''")
queries = []
result = {"started_utc": started, "basis": "saved CSV; no rebuild; cohort 70; 13 quarter ends; eligibility not inferred"}

def run(name, sql, limit=1000):
    print('Query: ' + name, flush=True)
    queries.append('-- ' + name + '\n' + sql + ';\n')
    cursor = db.execute(sql)
    rows = cursor.fetchmany(limit + 1)
    if len(rows) > limit:
        raise RuntimeError('Result bound exceeded: ' + name)
    fields = [c[0] for c in cursor.description]
    result[name] = [dict(zip(fields, r)) for r in rows]
    return result[name]

def setup(sql):
    queries.append(sql + ';\n')
    db.execute(sql)

def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(4 * 1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()

def write_csv(name, rows):
    if not rows:
        return
    with (OUT / name).open('w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)

paths = [Path(p) for p in [
    'data/output/private_markets_holdings.csv', 'data/output/bdc_holdings.csv',
    'data/output/bdc_filings_index.csv', 'data/output/entity_lookup.csv',
    'data/reference/fx_rates.csv',
    'data/overrides/wrapper_cohorts/v2_70_gate_verified_wrapper_manifest.json',
    'docs/reference/architecture_rule_assets.csv']]
paths += sorted(Path('pipeline').rglob('*.py'))
paths += [Path('scripts/rebuild_outputs.py'), Path('scripts/run_quarter_pass.py')]
paths += sorted(Path('data/overrides').rglob('*.json'))
paths += [Path('data/overrides/row_corrections.csv')]
paths = sorted(set(p for p in paths if p.exists()))
print('Pinning input hashes: ' + str(len(paths)), flush=True)
initial = {p.as_posix(): (p.stat().st_size, p.stat().st_mtime_ns) for p in paths}
manifest = [{"path": p.as_posix(), "bytes": p.stat().st_size,
             "mtime_ns": p.stat().st_mtime_ns, "sha256": digest(p)} for p in paths]
result['git_head'] = subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip()
result['git_status_before'] = subprocess.check_output(['git', 'status', '--short'], text=True)
result['duckdb_version'] = duckdb.__version__
write_csv('input_manifest.csv', manifest)

setup("CREATE TABLE cohort AS SELECT lpad(unnest(entries).cik,10,'0') cik FROM read_json_auto('data/overrides/wrapper_cohorts/v2_70_gate_verified_wrapper_manifest.json')")
setup("CREATE TABLE quarters AS SELECT CAST(last_day(d + INTERVAL 2 MONTH) AS VARCHAR) report_date FROM generate_series(DATE '2023-01-01', DATE '2026-01-01', INTERVAL 3 MONTH) t(d)")
print('Reading bounded holdings columns', flush=True)
setup("""CREATE TABLE h AS SELECT source, cik, report_date, accession_number,
    row_id, row_id_basis, src_context_id, entity_id, position_id, position_key,
    bdc_investment_identifier, try_cast(basis_spread AS DOUBLE) spread,
    cost_source, interest_rate_source, principal_fx_status, maturity_date,
    fair_value_currency, cost_currency, principal_amount_currency,
    gics_sub_industry, nonaccrual_footnote, nonaccrual_dimension, is_subsidiary,
    try_cast(fair_value AS DOUBLE) fv, try_cast(cost AS DOUBLE) cost_value,
    try_cast(interest_rate AS DOUBLE) rate, try_cast(pik_rate AS DOUBLE) pik,
    try_cast(principal_amount AS DOUBLE) principal,
    try_cast(principal_amount_usd AS DOUBLE) principal_usd,
    try_cast(pct_of_net_assets AS DOUBLE) pct
    FROM read_csv('data/output/private_markets_holdings.csv', all_varchar=true)
    WHERE cik IN (SELECT cik FROM cohort) AND report_date IN (SELECT report_date FROM quarters)""")
quarter_rows = run('quarter_profile', """SELECT report_date, count(*) row_count,
    count(DISTINCT cik) funds, sum(fv) signed_fv, sum(abs(fv)) absolute_fv,
    count(*) FILTER (WHERE fv IS NULL) missing_fv,
    count(*) FILTER (WHERE fv < 0) negative_fv,
    count(*) FILTER (WHERE cost_source='derived_proxy') cost_proxy_rows,
    sum(abs(fv)) FILTER (WHERE cost_source='derived_proxy') cost_proxy_absolute_fv,
    count(*) FILTER (WHERE cost_value=0) zero_cost_rows,
    count(*) FILTER (WHERE rate IS NULL) missing_rate,
    count(*) FILTER (WHERE pik>0 AND rate=0) positive_pik_zero_rate,
    count(*) FILTER (WHERE abs(pct)>150) pct_outside_schema,
    count(*) FILTER (WHERE coalesce(entity_id,'')='') missing_entity_id,
    count(*) FILTER (WHERE coalesce(position_id,'')='') missing_position_id,
    count(*) FILTER (WHERE coalesce(position_key,'')='') missing_position_key,
    count(*) FILTER (WHERE coalesce(gics_sub_industry,'')<>'') gics_populated,
    sum(abs(fv)) FILTER (WHERE coalesce(gics_sub_industry,'')<>'') gics_populated_absolute_fv,
    count(*) FILTER (WHERE try_cast(is_subsidiary AS INTEGER)=1) subsidiary_rows
    FROM h GROUP BY 1 ORDER BY 1""")
write_csv('quarter_profile.csv', quarter_rows)
run('currency_profile', """SELECT report_date, field, coalesce(currency,'<blank>') currency,
    count(*) row_count, count(amount_value) populated_amounts, sum(abs(amount_value)) absolute_native_amount
    FROM (SELECT report_date,'fair_value' field,fair_value_currency currency,fv amount_value FROM h
    UNION ALL SELECT report_date,'cost',cost_currency,cost_value FROM h
    UNION ALL SELECT report_date,'principal',principal_amount_currency,principal FROM h)
    GROUP BY 1,2,3 ORDER BY 1,2,3""")
run('principal_fx_profile', """SELECT report_date, coalesce(principal_fx_status,'<blank>') status,
    count(*) row_count, count(principal) populated_principal, count(principal_usd) populated_usd
    FROM h GROUP BY 1,2 ORDER BY 1,2""")
run('key_collisions', """SELECT 'row_id' key_kind, count(*) duplicate_groups,
    coalesce(sum(n-1),0) excess_rows FROM (SELECT row_id,count(*) n FROM h
    WHERE coalesce(row_id,'')<>'' GROUP BY 1 HAVING count(*)>1)
    UNION ALL SELECT 'source_context',count(*),coalesce(sum(n-1),0) FROM (
    SELECT cik,report_date,accession_number,src_context_id,count(*) n FROM h
    WHERE coalesce(src_context_id,'')<>'' GROUP BY 1,2,3,4 HAVING count(*)>1)
    UNION ALL SELECT 'within_quarter_position_key',count(*),coalesce(sum(n-1),0) FROM (
    SELECT cik,report_date,position_key,count(*) n FROM h WHERE coalesce(position_key,'')<>''
    GROUP BY 1,2,3 HAVING count(*)>1)""")
run('row_id_basis', "SELECT row_id_basis,count(*) row_count FROM h GROUP BY 1 ORDER BY 1")
run('subsidiary_flag_values', "SELECT is_subsidiary,count(*) row_count FROM h GROUP BY 1 ORDER BY 1")
run('entity_lookup_multiplicity', """SELECT count(*) duplicate_join_keys,
    coalesce(sum(n-1),0) excess_lookup_rows, count(*) FILTER (WHERE ids>1) conflicting_ids
    FROM (SELECT issuer_name_variant,source,count(*) n,count(DISTINCT entity_id) ids
    FROM read_csv('data/output/entity_lookup.csv',all_varchar=true)
    GROUP BY 1,2 HAVING count(*)>1)""")
run('spread_override_saved_matches', """WITH corrections AS (
    SELECT unnest(corrections) c FROM read_json_auto('data/overrides/identifier_spread_corrections.json'))
    SELECT c.cik,c.report_date,c.identifier,c.new_value_decimal,
    c.new_value_decimal * 100 expected_percentage_points,h.row_id,h.spread saved_spread,
    h.fv FROM corrections LEFT JOIN h ON c.cik=h.cik AND c.report_date=h.report_date
    AND c.identifier=h.bdc_investment_identifier ORDER BY 1,2,3""")
run('raw_monetary_units', """SELECT field,coalesce(unit,'<blank>') unit,
    count(*) row_count FROM (SELECT fair_value_unit,cost_unit,principal_amount_unit
    FROM read_csv('data/output/bdc_holdings.csv',all_varchar=true)
    WHERE lpad(cik,10,'0') IN (SELECT cik FROM cohort)
    AND period IN (SELECT report_date FROM quarters))
    UNPIVOT INCLUDE NULLS (unit FOR field IN (fair_value_unit,cost_unit,principal_amount_unit))
    GROUP BY 1,2 ORDER BY 1,2""")
obligations = run('obligations', """WITH saved AS (SELECT cik,report_date,count(*) n
    FROM h GROUP BY 1,2), filings AS (SELECT lpad(cik,10,'0') cik,report_date,
    count(*) n,count(*) FILTER (WHERE coalesce(xbrl_local_path,'')<>'') paths_recorded
    FROM read_csv('data/output/bdc_filings_index.csv',all_varchar=true) GROUP BY 1,2)
    SELECT c.cik,q.report_date,coalesce(s.n,0) holdings_rows,
    coalesce(f.n,0) indexed_filings,coalesce(f.paths_recorded,0) indexed_local_paths,
    'eligibility_not_yet_adjudicated' eligibility_status
    FROM cohort c CROSS JOIN quarters q LEFT JOIN saved s USING(cik,report_date)
    LEFT JOIN filings f USING(cik,report_date) ORDER BY 1,2""")
write_csv('obligation_frame.csv', obligations)
result['obligation_summary'] = {"total":len(obligations),
    "with_holdings":sum(r['holdings_rows']>0 for r in obligations),
    "without_holdings":sum(r['holdings_rows']==0 for r in obligations),
    "without_holdings_with_indexed_filing":sum(r['holdings_rows']==0 and r['indexed_filings']>0 for r in obligations)}
del result['obligations']

print('Inspecting saved correction instances', flush=True)
stages = {'dedup':1,'subtotal_filter':1,'comparative_period_filter':1,
    'missing_position_add':1,'spv_lookthrough':1,'layer_exclusion':1,
    'rate_rescale':2,'all_pik_normalization':2,'column_remap':2,'unit_rescale':2,
    'classification_fix':2,'source_anchored_value':2,'rule_scope':3,'anchor_fix':3,
    'identifier_rate_grammar':3,'unknown':0}
records=[]
by_cik=defaultdict(list)
for family in ['agent_b2_corrections','agent_investigate_rules','agent_anchor','bdc_xbrl_html_section_bridges']:
    base=Path('data/overrides')/family
    for p in sorted(base.rglob('*.json')):
        x=json.loads(p.read_text(encoding='utf-8-sig'))
        rel=p.relative_to(base)
        eligible=len(rel.parts)==(1 if family=='bdc_xbrl_html_section_bridges' else 2)
        if family=='agent_investigate_rules' and p.parent.name.startswith('_'):
            eligible=False
        fc=x.get('fix_class',x.get('rule_type',''))
        cik=str(x.get('cik',p.parent.name)).zfill(10)
        scope=x.get('scope',{})
        if family=='agent_anchor':
            disposition='retain comparable published/investments-ex-cash anchor; validate basis and source independently'
        elif family=='bdc_xbrl_html_section_bridges':
            disposition='retain keyed source recovery; require explicit accepted-manifest membership rather than filename'
        elif fc=='all_pik_normalization':
            disposition='replace cash-leg interest_rate write atomically with all-in storage and income consumer'
        elif fc in ['rate_rescale','unit_rescale','column_remap','source_anchored_value','value_expression','field_rescale']:
            disposition='adapt to typed target units/meaning; reverify source mechanism and downstream interaction'
        elif fc in ['dedup','row_exclusion','row_dedup','comparative_period_filter','layer_exclusion','spv_lookthrough']:
            disposition='retain only source-proven duplicate/nonposition exclusion; preserve legitimate observations and accounting membership'
        elif fc in ['row_add','missing_position_add']:
            disposition='retain source-anchored recovery with source-lot identity; reject synthetic or duplicate positions'
        else:
            disposition='retain scoped mechanism only after target meaning and field authority are reverified'
        record={"family":family,"path":p.as_posix(),"sha256":digest(p),
            "cik":cik,"rule_id":x.get('rule_id',p.stem),"kind":fc,
            "loader_path_eligible":eligible,"scope":json.dumps(scope,sort_keys=True),
            "selector_or_predicate":json.dumps(x.get('predicate_sql',(x.get('template') or {}).get('row_selector',{})),sort_keys=True),
            "payload":json.dumps(x.get('template', {k:v for k,v in x.items() if k in ['field','factor','expression','values','positions','grand_total','basis','bridges']}),sort_keys=True),
            "stage":stages.get(fc,''),
            "target_disposition":disposition}
        records.append(record)
        if family=='agent_b2_corrections' and eligible and fc in stages and stages[fc] in [1,2] and fc not in ['comparative_period_filter','subtotal_filter']:
            by_cik[cik].append(x)
result['rule_loader_counts']=[{'family':f,'path_eligible':sum(r['loader_path_eligible'] for r in records if r['family']==f),'outside_loader_path':sum(not r['loader_path_eligible'] for r in records if r['family']==f)} for f in sorted({r['family'] for r in records})]
result['b2_order_inversions']=[]
result['all_pik_cash_writes']=[]
for cik, leaves in sorted(by_cik.items()):
    prod=sorted(leaves,key=lambda c:c['fix_class'])
    for i,a in enumerate(prod):
        if a['fix_class']=='all_pik_normalization' and a.get('template',{}).get('set_interest_to_cash'):
            result['all_pik_cash_writes'].append({'cik':cik,'scope':a.get('scope'), 'template':a.get('template')})
        for b in prod[i+1:]:
            if stages[a['fix_class']] <= stages[b['fix_class']]:
                continue
            aq=set(a.get('scope',{}).get('quarters',[])); bq=set(b.get('scope',{}).get('quarters',[]))
            overlap=bool(aq & bq) or not aq or not bq or 'all' in aq or 'all' in bq
            result['b2_order_inversions'].append({'cik':cik,'production_before':a['fix_class'],
                'production_after':b['fix_class'],'quarter_scope_overlap':overlap,
                'before_scope':sorted(aq),'after_scope':sorted(bq),
                'effect':'not replayed; selectors may be disjoint'})
result['html_bridge'] = []
for r in records:
    if r['family']=='bdc_xbrl_html_section_bridges' and r['loader_path_eligible']:
        x=json.loads(Path(r['path']).read_text(encoding='utf-8-sig'))
        valid=[b for b in x.get('bridges',[]) if b.get('accession_number') and b.get('report_date') and (b.get('raw_id_lower') or b.get('raw_investment_identifier')) and b.get('family')]
        result['html_bridge'].append({'path':r['path'],'schema':x.get('schema_version'),
            'records':len(x.get('bridges',[])),'records_with_required_key_fields':len(valid),
            'source_correctness':'not checked; proposed suffix does not disable loader'})
write_csv('correction_instances.csv', records)
result['all_pik_cash_write_count']=len(result['all_pik_cash_writes'])
result['artifacts_presence']={p:Path(p).exists() for p in [
    'data/output/lien_cache.csv','data/output/fund_strategy_correction_candidates.pinned.csv',
    'data/output/bdc_ixbrl_field_status.csv','data/output/unclassified_review_cache.csv']}
result['input_changes_during_audit']=[p for p,(size,mtime) in initial.items() if not Path(p).exists() or (Path(p).stat().st_size,Path(p).stat().st_mtime_ns)!=(size,mtime)]
result['finished_utc']=datetime.now(timezone.utc).isoformat()
if result['input_changes_during_audit']:
    raise RuntimeError('Inputs changed during audit')
(OUT/'queries.sql').write_text('\n'.join(queries),encoding='utf-8')
(OUT/'results.json').write_text(json.dumps(result,indent=2,default=str),encoding='utf-8')
db.close()
timer.cancel()
print(json.dumps({k:result[k] for k in ['obligation_summary','rule_loader_counts','b2_order_inversions','all_pik_cash_write_count','html_bridge','artifacts_presence']},indent=2),flush=True)
print('Complete; input stat guards unchanged; results in ' + OUT.name,flush=True)
