"""Bounded B2 full-population accounting and scoped order sensitivity proof."""
import argparse,json,os,sys,threading,time
sys.dont_write_bytecode=True
from pathlib import Path
from collections import Counter
import duckdb
import pandas as pd
from scripts.programme_closeout.candidate import atomic_json,sha
ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'docs/production_stack/programme_closeout_evidence_2026-09-09/rule_replay'
NUMERIC=('fair_value','cost','principal_amount','principal_amount_usd','interest_rate','pik_rate','spread','shares_held','pct_of_net_assets')
TEXT=('cik','source','report_date','accession_number','src_context_id','bdc_investment_identifier','issuer_name','instrument_description','index_classification','asset_class','maturity_date','is_subsidiary')

def digest_rows(df):
    frame=pd.DataFrame(index=df.index)
    for c in TEXT:
        if c in df:frame[c]=df[c].fillna('').astype(str)
    for c in NUMERIC:
        if c in df:frame[c]=pd.to_numeric(df[c],errors='coerce').astype(float)
    return Counter(pd.util.hash_pandas_object(frame,index=False).tolist())

def anchors(df):
    cols=[c for c in ('source','cik','report_date','accession_number','src_context_id','bdc_investment_identifier') if c in df]
    return pd.util.hash_pandas_object(df[cols].fillna('').astype(str),index=False)

def main():
    p=argparse.ArgumentParser();p.add_argument('--candidate',type=Path,required=True);a=p.parse_args()
    attempt=a.candidate.resolve()/'attempts/unified-01';bundle=attempt/'bundle';workspace=attempt/'workspace'
    assert attempt.is_relative_to(ROOT/'data/programme/candidates')
    start=time.monotonic();OUT.mkdir(exist_ok=True)
    sys.path.insert(0,str(workspace))
    from pipeline.agent_b2_appliers import apply_scoped
    from pipeline.unified_holdings import _assign_row_ids
    assert Path(sys.modules['pipeline'].__file__).resolve().is_relative_to(workspace)
    events=json.loads((bundle/'rule_events.json').read_text());ciks=sorted({e['cik'] for e in events})
    con=duckdb.connect();con.execute("SET threads=2");con.execute("SET memory_limit='-1'")
    for name in ('before','after'):
        path=bundle/(name+'_b2.csv')
        literal="'"+str(path).replace("'","''")+"'"
        con.execute(f"CREATE VIEW {name}_data AS SELECT * FROM read_csv({literal},header=true,all_varchar=true)")
    # COPY destinations are exclusively the owned evidence directory.
    summary=con.execute('''WITH b AS (SELECT lpad(cik,10,'0') cik,report_date,count(*) n,sum(try_cast(fair_value AS DOUBLE)) fv,sum(abs(try_cast(fair_value AS DOUBLE))) abs_fv FROM before_data GROUP BY ALL),
      a AS (SELECT lpad(cik,10,'0') cik,report_date,count(*) n,sum(try_cast(fair_value AS DOUBLE)) fv,sum(abs(try_cast(fair_value AS DOUBLE))) abs_fv FROM after_data GROUP BY ALL)
      SELECT coalesce(b.cik,a.cik) cik,coalesce(b.report_date,a.report_date) report_date,b.n before_rows,a.n after_rows,b.fv before_fv,a.fv after_fv,b.abs_fv before_abs_fv,a.abs_fv after_abs_fv,
      coalesce(a.n,0)-coalesce(b.n,0) row_delta,coalesce(a.fv,0)-coalesce(b.fv,0) signed_fv_delta FROM b FULL JOIN a USING(cik,report_date)''').df()
    summary.to_csv(OUT/'b2_population_by_fund_quarter.csv',index=False)
    source=con.execute("SELECT * FROM before_data WHERE source='bdc' AND lpad(cik,10,'0') IN (SELECT unnest(?))",[ciks]).df()
    source['cik']=source.cik.str.zfill(10)
    for c in NUMERIC:
        if c in source:source[c]=pd.to_numeric(source[c],errors='coerce')
    results=[];touches={};states=[]
    for cik in ciks:
        original=source.loc[source.cik==cik].copy();leaves=[e for e in events if e['cik']==cik]
        if 'row_id' not in original:original=_assign_row_ids(original)
        elif original.row_id.isna().all() or original.row_id.fillna('').eq('').all():original=_assign_row_ids(original)
        current=original.copy()
        for event in leaves:
            correction={k:event[k] for k in ('cik','fix_class','scope','template')}
            before=current.copy();current,audit=apply_scoped(current,correction)
            before_hash=pd.util.hash_pandas_object(before[[c for c in TEXT+NUMERIC if c in before]].fillna('').astype(str),index=False)
            after_hash=pd.util.hash_pandas_object(current[[c for c in TEXT+NUMERIC if c in current]].fillna('').astype(str),index=False)
            # Index identity only used if retained uniquely by the existing applier.
            index_safe=before.index.is_unique and current.index.is_unique
            if index_safe:
                changed=before_hash.ne(after_hash.reindex(before.index))
                touched=set(anchors(before.loc[changed]).astype(str))
            else:touched=set()
            touches[event['rule_id']]=touched
            results.append(dict(rule_id=event['rule_id'],cik=cik,fix_class=event['fix_class'],original_audit=event['audit'],
                replay_audit=audit,changed_or_removed_rows=int(changed.sum()) if index_safe else None,
                touched_source_anchor_hashes=sorted(touched),index_identity_safe=index_safe,
                input_rows=len(before),output_rows=len(current),
                affected_input_abs_fv=float(pd.to_numeric(before.loc[changed,'fair_value'],errors='coerce').abs().sum()) if index_safe else None))
        reverse=original.copy()
        for event in reversed(leaves):reverse,_=apply_scoped(reverse,{k:event[k] for k in ('cik','fix_class','scope','template')})
        normal_hash=digest_rows(current);reverse_hash=digest_rows(reverse)
        states.append(dict(cik=cik,rules=len(leaves),normal_rows=len(current),reverse_rows=len(reverse),
            different_row_versions=sum((normal_hash-reverse_hash).values())+sum((reverse_hash-normal_hash).values()),
            comparison='tracked value multiset after forward versus reversed B2 order; not all pipeline layers'))
        print('B2 replay '+cik+' rules '+str(len(leaves)),flush=True)
    overlaps=[]
    for i,left in enumerate(events):
        for right in events[i+1:]:
            shared=touches[left['rule_id']] & touches[right['rule_id']]
            if shared:overlaps.append(dict(first=left['rule_id'],second=right['rule_id'],touched_anchors=len(shared)))
    atomic_json(OUT/'rule_footprints.json',results);atomic_json(OUT/'order_results.json',states);atomic_json(OUT/'observed_overlaps.json',overlaps)
    changed=summary.loc[(summary.row_delta!=0)|(summary.signed_fv_delta.abs()>0.01)]
    atomic_json(OUT/'summary.json',dict(recorded_applications=len(events),replay_applications=len(results),
      execution_errors=sum(r['replay_audit'].get('status') not in ('ok','no_rows') for r in results),
      affected_fund_quarters=len(changed),net_row_delta=int(summary.row_delta.sum()),signed_fv_delta=float(summary.signed_fv_delta.sum()),
      sum_abs_fund_quarter_fv_delta=float(summary.signed_fv_delta.abs().sum()),
      observed_overlapping_rule_pairs=len(overlaps),order_sensitive_ciks=sum(r['different_row_versions']>0 for r in states),
      source_files=[dict(path=str((bundle/f).relative_to(ROOT)),sha256=sha(bundle/f)) for f in ('before_b2.csv','after_b2.csv','rule_events.json')],
      elapsed_seconds=time.monotonic()-start,scope='B2 admitted post-staging leaves only; frozen full population. Global, wrapper, cache and Layer C cross-layer order is not certified.',
      correctness='Measured impact is not proof a rule is financially correct; source reconciliation remains required.'))
    print('B2 accounting complete',flush=True);con.close();
if __name__=='__main__':main()
