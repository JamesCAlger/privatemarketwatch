"""Measure the completed candidate, with explicit reuse of byte-identical pilot inputs."""
import argparse,csv,json,os,threading,time
from pathlib import Path
import duckdb,pandas as pd
from scripts.programme_closeout.candidate import atomic_json,sha,read_bundle
from scripts.programme_reference.evaluate import match_roster,primary_error_ratio
from scripts.programme_closeout.acceptance import PROPOSED,evaluate,programme_verdict
ROOT=Path(__file__).resolve().parents[2]
BASE=ROOT/'docs/production_stack/programme_closeout_evidence_2026-09-09'
PILOT=ROOT/'docs/production_stack/programme_pilot_evidence_2026-09-09'

def main():
    p=argparse.ArgumentParser();p.add_argument('--candidate',type=Path,required=True);a=p.parse_args()
    candidate=a.candidate.resolve();bundle=candidate/'attempts/unified-01/bundle';snap=json.loads((candidate/'snapshot.json').read_text())
    read_bundle(bundle,snap['input_fingerprint']);out=BASE/'baseline';out.mkdir(exist_ok=True)
    start=time.monotonic()
    path=bundle/'private_markets_holdings.csv';csvsha=sha(path)
    assert csvsha=='f175956d07649ed77dd3ec11c0ffd92f1af8074824d15ab881bc8495f4e81b68','Pilot reuse requires exact input bytes'
    con=duckdb.connect();con.execute('SET threads=2');con.execute("SET memory_limit='-1'")
    temp=ROOT/'scratch/2026-09-09_programme_closeout/baseline_temp';temp.mkdir(exist_ok=True)
    con.execute("SET temp_directory='"+temp.as_posix().replace("'","''")+"'")
    q=lambda p:"'"+str(p).replace("'","''")+"'"
    con.execute(f'CREATE VIEW h AS SELECT * FROM read_parquet({q(path.with_suffix(".parquet"))})')
    obligations=pd.read_csv(PILOT/'obligations_v2.csv',dtype=str);con.register('obligations',obligations)
    taxonomy_path=candidate/'frozen/data/reference/gics_hierarchy.json'
    taxonomy=json.loads(taxonomy_path.read_text())
    gics=pd.DataFrame([dict(subindustry=k,sector=v['sector']) for k,v in taxonomy.items()]);con.register('gics',gics)
    con.execute("CREATE VIEW selected AS SELECT h.*,g.sector gics_sector FROM h JOIN obligations o ON lpad(CAST(h.cik AS VARCHAR),10,'0')=o.cik AND CAST(h.report_date AS VARCHAR)=o.report_date LEFT JOIN gics g ON h.gics_sub_industry=g.subindustry")
    quarters=con.execute('''SELECT report_date,count(*) AS "rows",count(distinct cik) funds,sum(fair_value) signed_fv,sum(abs(fair_value)) absolute_fv,
       count(*) filter(where fair_value IS NULL) missing_fv,
       count(*) filter(where nullif(gics_sector,'') IS NOT NULL) gics_rows,
       sum(abs(fair_value)) filter(where nullif(gics_sector,'') IS NOT NULL) gics_abs_fv
       FROM selected GROUP BY report_date ORDER BY report_date''').df()
    quarters.to_csv(out/'quarter_baseline.csv',index=False)
    coverage=con.execute('''WITH counts AS (SELECT lpad(CAST(cik AS VARCHAR),10,'0') cik,CAST(report_date AS VARCHAR) report_date,count(*) n_rows FROM h GROUP BY ALL)
       SELECT o.*,coalesce(c.n_rows,0) candidate_rows FROM obligations o LEFT JOIN counts c USING(cik,report_date)''').df()
    coverage.to_csv(out/'obligation_baseline.csv',index=False)
    rosters=json.loads((BASE/'review/new_development_rosters.json').read_text());results=[]
    for r in rosters:
        cik=r['reference_id'].split('-')[1];date=r['reference_id'][-10:]
        rows=con.execute('SELECT count(*),coalesce(sum(fair_value),0) FROM selected WHERE lpad(CAST(cik AS VARCHAR),10,\'0\')=? AND CAST(report_date AS VARCHAR)=?',[cik,date]).fetchone()
        # Absence can be scored exactly; nonempty candidates require explicit source-lot joins.
        score=match_roster([dict(key=x['key'],fair_value=x['fair_value']) for x in r['rows']],[]) if rows[0]==0 else dict(status='candidate_present_requires_explicit_lot_join')
        anchor=primary_error_ratio([dict(cik=cik,report_date=date,primary=True,basis_verified=True,reference=r['total_fv'],actual=rows[1])]) if rows[0]==0 else None
        results.append(dict(reference_id=r['reference_id'],candidate_rows=rows[0],candidate_fv=rows[1],roster_result=score,primary_result=anchor,scope='development fund-quarter census, not cohort estimate'))
    atomic_json(out/'new_roster_results.json',results)
    # Narrow source-review joins, never change the gold key merely to create a match.
    labels=con.execute('''SELECT cik,report_date,issuer_name,instrument_description,bdc_investment_identifier,src_context_id,row_id,position_id,
      fair_value,cost,index_classification,is_subsidiary,bdc_dimensions_raw
      FROM h WHERE CAST(report_date AS VARCHAR)='2025-12-31' AND
      (regexp_matches(lower(issuer_name),'fifth season|lsi financing|cross.strategy opportunities|ocic slf|state street institutional.*government')) LIMIT 501''').df()
    assert len(labels)<=500;labels.to_csv(out/'legacy_join_candidates.csv',index=False)
    audit=pd.read_csv(bundle/'agent_fix_application_audit.csv',dtype=str).fillna('')
    audit.groupby(['layer','status','drift'],dropna=False).size().rename('rules').reset_index().to_csv(out/'application_audit_status.csv',index=False)
    # Type-aware CSV/Parquet parity: compare row order, every declared field, exact typed values.
    columns=con.execute('DESCRIBE h').fetchall()
    projection=','.join('try_cast("'+name+'" AS '+typ+') AS "'+name+'"' for name,typ,*_ in columns)
    con.execute(f'CREATE VIEW raw_csv AS SELECT * FROM read_csv({q(path)},header=true,all_varchar=true)')
    expressions=','.join('count(*) filter(where c."'+name+'" IS DISTINCT FROM p."'+name+'") AS "'+name+'"' for name,*_ in columns)
    parity=con.execute(f'''WITH c AS (SELECT row_number() over() ordinal,{projection} FROM raw_csv),
      p AS (SELECT row_number() over() ordinal,* FROM h)
      SELECT {expressions},count(*) rows_compared FROM c FULL JOIN p USING(ordinal)''').df()
    parity.to_csv(out/'csv_parquet_typed_parity.csv',index=False)
    metrics=[]
    for r in results:
        score=r['roster_result']
        if 'row_recall' in score:
            obs=dict(release_id=candidate.name,input_sha256=csvsha,eligible=score['reference_rows'],assessed=score['reference_rows'],
                design='census',denominator_known=True,value=score['row_recall'])
            metrics.append(dict(evaluate('roster_row_recall',obs),scope=r['reference_id']))
    q1=quarters.iloc[-1]
    metrics.append(dict(evaluate('sector_fv_coverage',dict(release_id=candidate.name,input_sha256=csvsha,eligible=int(q1['rows']),assessed=int(q1['rows']),
        design='census',denominator_known=True,missing_weight=int(q1.missing_fv),value=float(q1.gics_abs_fv/q1.absolute_fv))),scope=str(q1.report_date)))
    metrics.append(evaluate('sector_accuracy',dict(release_id=candidate.name,input_sha256=csvsha,eligible=1,assessed=0,design='census',denominator_known=False)))
    atomic_json(out/'proposed_metric_results.json',metrics)
    atomic_json(out/'threshold_proposal.json',dict(version='programme-proposal-20260909-v2',approved=False,units='ratios 0..1 except local_citation_p95_ms and zero violation counts',
       thresholds={k:dict(operator=v[0],value=v[1]) for k,v in PROPOSED.items()},
       invariants='Exact structural/identity/replay/evidence/public-total requirements remain 100% or zero violations; this file does not replace the 28-criterion register.'))
    prior=json.loads((PILOT/'pilot_summary.json').read_text())
    atomic_json(out/'summary.json',dict(candidate=candidate.name,holdings_sha256=csvsha,rows=int(parity.rows_compared.iloc[0]),
       required_history_rows=int(quarters['rows'].sum()),obligations=len(coverage),eligible_obligations=812,taxonomy_sha256=sha(taxonomy_path),
       byte_identical_to_pilot=True,reused_pilot_summary_sha256=sha(PILOT/'pilot_summary.json'),
       reuse_reason='Exact same canonical CSV bytes; pilot source/evaluator identities remain in its manifest. Identity outputs are not reused.',
       reused_pilot_summary=prior,new_development_rosters=results,typed_parity_different_cells=int(parity.drop(columns=['rows_compared']).sum(axis=1).iloc[0]),
       proposal_evaluation=programme_verdict(metrics),population_accuracy='UNASSESSABLE; no complete independent cohort reference',
       elapsed_seconds=time.monotonic()-start))
    print('Candidate baseline complete',flush=True);con.close();
if __name__=='__main__':main()
