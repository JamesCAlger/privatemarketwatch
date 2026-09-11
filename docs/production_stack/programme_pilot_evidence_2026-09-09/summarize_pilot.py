"""Freeze reviewed development dispositions and compact, reproducible summaries."""
import csv
import json
import os
from pathlib import Path
import sys
import threading
from decimal import Decimal
import duckdb

ROOT=next(p for p in Path(__file__).resolve().parents if (p/'AGENTS.md').exists())
sys.path.insert(0,str(ROOT));os.chdir(ROOT)
from scripts.programme_reference.evaluate import match_roster, primary_error_ratio
from scripts.programme_reference.measure_pilot import read_csv, write_csv, sql_string
OUT=Path(__file__).parent;RESULTS=OUT/'results'
timer=threading.Timer(90,lambda:os._exit(124));timer.daemon=True;timer.start()
db=duckdb.connect(config={'memory_limit':'1GB','threads':2})
db.execute('CREATE TABLE fields AS SELECT * FROM read_csv(?,all_varchar=true)',[str(RESULTS/'tag_copy_fields.csv')])
db.execute('CREATE TABLE facts AS SELECT * FROM read_csv(?,all_varchar=true)',[str(RESULTS/'source_facts.csv')])
db.execute('CREATE TABLE packets AS SELECT * FROM read_csv(?,all_varchar=true)',[str(RESULTS/'pilot_status.csv')])
db.execute("UPDATE packets SET roster_status='reviewed_development_33_lots; six FV dashes unresolved' WHERE reference_id='REF-0002008748-2024-09-30'")
db.execute("UPDATE packets SET primary_anchor_status='agent-reviewed development basis; not held-out acceptance' WHERE reference_id IN ('REF-0002008748-2024-09-30','REF-0001899017-2023-06-30')")
db.execute('CREATE TABLE quarters AS SELECT * FROM read_csv(?,all_varchar=true)',[str(RESULTS/'quarter_denominators.csv')])
def export(name,query):
    db.execute('COPY ('+query+') TO '+sql_string(RESULTS/name)+' (HEADER,FORMAT CSV)')
export('pilot_status.csv','SELECT * FROM packets ORDER BY reference_id')
export('tag_copy_totals.csv','SELECT field,comparison_status,count(*) observations FROM fields GROUP BY ALL ORDER BY ALL')
export('tag_copy_discrepancies.csv',"SELECT * FROM fields WHERE comparison_status NOT IN ('within_source_precision','no_exact_candidate_context') ORDER BY reference_id,context_id,field")
export('explicit_zero_cost_candidates.csv',"""SELECT f.* FROM facts f JOIN fields r USING(reference_id,context_id,field)
    WHERE f.field='cost' AND try_cast(f.value AS DOUBLE)=0 AND f.raw_text='0'
    AND r.candidate_rows='1' AND r.variants='1' ORDER BY f.reference_id,f.context_id LIMIT 6""")
export('quarter_pilot_status.csv',"""SELECT q.*,p.clusters,p.source_available,
    t.within_source_precision,t.value_mismatch,t.no_exact_candidate_context,
    'reference-limited; no population accuracy estimate' AS accuracy_status,
    'blocked: incompatible saved identity generations' AS identity_status,
    'unmeasured: independent sector labels required' AS sector_status
    FROM quarters q LEFT JOIN (SELECT report_date,count(*) clusters,
       count(*) FILTER(WHERE source_status NOT LIKE 'no_primary%') source_available FROM packets GROUP BY report_date) p USING(report_date)
    LEFT JOIN (SELECT report_date,
       count(*) FILTER(WHERE comparison_status='within_source_precision') within_source_precision,
       count(*) FILTER(WHERE comparison_status='value_mismatch') value_mismatch,
       count(*) FILTER(WHERE comparison_status='no_exact_candidate_context') no_exact_candidate_context
       FROM fields GROUP BY report_date) t USING(report_date) ORDER BY report_date""")
lord=json.loads((OUT/'sources/REF-0002008748-2024-09-30.json').read_text())
full=json.loads((OUT/'lord_full_schedule.json').read_text())
# Explicit row-by-row source review. This is not a reusable global extraction rule.
lots={13:[5,6,9,10,11,12,13,14,17,18,19,22,23,24,27,28,29,30,33,34,35,38,39,40,41,44,45],14:[5,6,9,10,11,12]}
lotpaths={f'/html/body/table[{table}]/tr[{row}]' for table,rows in lots.items() for row in rows}
byxpath={r['row_xpath']:r for r in lord['source_candidates']}
roster=[]
for row in full['rows']:
    if row['xpath'] not in lotpaths:continue
    facts=[f for f in byxpath.get(row['xpath'],{}).get('facts',[]) if f['field']=='fair_value']
    assert len(facts)<=1
    roster.append({'key':row['xpath'],'issuer_instrument':row['cells'][0],
        'context_id':byxpath.get(row['xpath'],{}).get('context_id'),
        'fair_value':facts[0]['value'] if facts else None,
        'fair_value_status':'reported_inline' if facts else 'displayed_dash; numeric interpretation not adjudicated',
        'rounding_bound':facts[0]['rounding_bound'] if facts else None})
assert len(roster)==33
lord_totals=next(r for r in read_csv(RESULTS/'pilot_candidate_totals.csv') if r['reference_id']==lord['reference_id'])
assert lord_totals['candidate_rows']=='0'
lord_score=match_roster(roster,[])
lord_score.update(reference_id=lord['reference_id'],reference_label_status='agent-reviewed development; candidate absence already known',
    source_signed_fv_known=str(sum(Decimal(r['fair_value']) for r in roster if r['fair_value'] is not None)),
    primary_source_total='313562000',primary_source_total_xpath='/html/body/table[14]/tr[15]',
    monetary_scope='USD parent investment schedule; all disclosed loans and facilities; no subtotal or look-through additions')
(RESULTS/'lord_reviewed_roster.json').write_text(json.dumps({'source_path':lord['path'],'source_sha256':lord['sha256'],
    'roster':roster,'result':lord_score},indent=2),encoding='utf-8')
bain=json.loads((RESULTS/'reviewed_roster_result.json').read_text())
# Full small source schedule is the explicit basis; source total is a quoted cell, not a sum of candidate rows.
reviewed_anchors=[{'cik':'0001899017','report_date':'2023-06-30','primary':True,'basis_verified':True,
    'reference':646250,'actual':646250,'row_xpath':'/html/body/table[11]/tr[9]',
    'status':'agent-reviewed development schedule only; not cohort acceptance'},
    {'cik':'0002008748','report_date':'2024-09-30','primary':True,'basis_verified':True,
    'reference':313562000,'actual':0,'row_xpath':'/html/body/table[14]/tr[15]',
    'status':'empty saved candidate has sum zero; known positive source portfolio entirely absent'}]
write_csv(RESULTS/'reviewed_primary_anchors.csv',reviewed_anchors)
anchor_scores=[{'cik':a['cik'],'report_date':a['report_date'],**primary_error_ratio([a])} for a in reviewed_anchors]
(RESULTS/'reviewed_anchor_results.json').write_text(json.dumps(anchor_scores,indent=2),encoding='utf-8')
counts=dict(db.execute('SELECT comparison_status,count(*) FROM fields GROUP BY comparison_status').fetchall())
assert sum(counts.values())==47230
assert counts['value_mismatch']==30
assert sum(int(r['eligible']) for r in read_csv(RESULTS/'quarter_denominators.csv'))==812
assert sum(int(r['pre_operation']) for r in read_csv(RESULTS/'quarter_denominators.csv'))==98
summary={'source_documents':53,'pilot_clusters':61,'source_candidate_rows':sum(int(r['source_fact_rows']) for r in read_csv(RESULTS/'pilot_status.csv')),
    'source_field_groups':sum(counts.values()),'tag_copy_status_counts':counts,
    'eligible_obligations':812,'eligible_with_rows':779,'eligible_without_rows':33,'presence_ratio':779/812,
    'reviewed_development_rosters':2,'held_out_acceptance_rosters':0,'primary_anchor_scores':anchor_scores,
    'legacy_labels_in_scope':127,'legacy_unique_candidate_joins':122,'legacy_missing_joins':4,'legacy_ambiguous_joins':1,
    'legacy_numeric_flag_review':'Aurelia currency mismatch and Sentinel JV/parent scope and tranche mismatch in stored references; do not count as confirmed pipeline amount errors',
    'population_accuracy_estimate':None,'programme_verdict':'NOT_ASSESSABLE'}
(RESULTS/'pilot_summary.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
db.close();timer.cancel()
print(json.dumps(summary,ensure_ascii=True),flush=True)
