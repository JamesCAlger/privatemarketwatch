"""Classify a recorded cohort population outside builds with an explicit call budget."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import time
from types import SimpleNamespace

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

import duckdb
from pipeline import config
from pipeline.programme.artifacts import literal
from pipeline.programme.core import atomic_json,now,read_json,sha
from pipeline.programme.runner import candidate_path,heavy_lock
from pipeline.quarter_acceptance import load_cohort
from pipeline.sector_enrichment import SUBJECT_SQL


def prepare(holdings,output,cohort,taxonomy):
    """One explicit candidate population; model work is limited separately."""
    with duckdb.connect(config={"threads":2,"memory_limit":"-1"}) as con:
        con.execute("CREATE TABLE cohort(cik VARCHAR)")
        con.executemany("INSERT INTO cohort VALUES (?)",[(c,) for c in sorted(cohort)])
        con.execute("CREATE TABLE valid AS SELECT unnest(?::VARCHAR[]) AS value",[taxonomy])
        con.execute("""CREATE TABLE population AS SELECT *, """+SUBJECT_SQL+""" AS subject,
            coalesce(nullif(cast(canonical_name AS VARCHAR),''),cast(issuer_name AS VARCHAR),'') AS input_text,
            TRY_CAST(fair_value AS DOUBLE) AS fv,
            EXISTS(SELECT 1 FROM valid v WHERE v.value=h.gics_sub_industry) AS known
            FROM read_csv_auto("""+literal(holdings)+""",all_varchar=true) h
            SEMI JOIN cohort c ON lpad(h.cik,10,'0')=c.cik
            WHERE report_date BETWEEN '2023-03-31' AND '2026-03-31'""")
        con.execute("""CREATE TABLE subjects AS SELECT subject,min(input_text) AS input_text,
            count(*) AS observations,sum(abs(fv)) AS abs_fv_history,
            sum(abs(fv)) FILTER(WHERE report_date='2026-03-31') AS abs_fv_current,
            bool_or(issuer_category IN ('FUND','GOVERNMENT')) AS excluded_type,
            count(DISTINCT nullif(entity_id,'')) AS legacy_entity_count
            FROM population WHERE NOT known GROUP BY subject""")
        con.execute("COPY (SELECT * FROM subjects ORDER BY abs_fv_current DESC NULLS LAST,abs_fv_history DESC,subject) TO "+literal(output/"subjects.csv")+" (HEADER)")
        con.execute("COPY (SELECT row_id,subject FROM population WHERE NOT known ORDER BY row_id) TO "+literal(output/"membership.csv")+" (HEADER)")
        summary=con.execute("""SELECT count(*) AS rows,count(*) FILTER(WHERE known) AS known_rows,
            coalesce(sum(abs(fv)),0) AS abs_fv,coalesce(sum(abs(fv)) FILTER(WHERE known),0) AS known_abs_fv,
            count(*) FILTER(WHERE NOT known) AS unknown_rows FROM population""").fetchdf().to_dict("records")[0]
        atomic_json(output/"population.json",summary)
    return summary


class RecordedClient:
    """Record exact response model and usage; disable hidden SDK retries."""
    def __init__(self,client,output):
        self.client,self.output=client,output
        self.metadata=None
        self.beta=SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(parse=self.parse)))

    def parse(self,**kwargs):
        try:
            response=self.client.beta.chat.completions.parse(**kwargs)
        except Exception as error:
            # Retain the service failure without serializing exception text,
            # which can include credential fragments from authentication errors.
            failure=dict(type=type(error).__name__,status_code=getattr(error,'status_code',None),
                request_id=getattr(error,'request_id',None))
            self.metadata=dict(model=kwargs.get('model'),response_id=None,usage=None,error=failure)
            atomic_json(self.output,dict(error=failure))
            raise RuntimeError('Recorded classification service failure: '+type(error).__name__) from None
        atomic_json(self.output,response.model_dump(mode="json"))
        self.metadata={"model":response.model,"response_id":response.id,
            "usage":response.usage.model_dump() if response.usage else None}
        return response


def run(holdings,output,call_budget,*,call=None):
    from pipeline import gics_classification as classifier
    output.mkdir(parents=True,exist_ok=False)
    taxonomy_path=config.GICS_REFERENCE_FILE
    taxonomy=read_json(taxonomy_path)
    inputs={str(p):sha(p) for p in (holdings,taxonomy_path,config.WRAPPER_COHORT_MANIFEST_FILE,
        ROOT/"pipeline/gics_classification.py",ROOT/"pipeline/sector_enrichment.py",Path(__file__))}
    request=dict(holdings=str(holdings),input_sha256=inputs,call_budget=call_budget,batch_size=50,
        model="gpt-4o-mini",sdk_retries=0,started_at=now(),authority="Owner-authorized P5 task; isolated inference decisions")
    atomic_json(output/"request.json",request)
    prepare(holdings,output,load_cohort(),taxonomy)
    with duckdb.connect(config={"threads":2,"memory_limit":"-1"}) as con:
        selected=con.execute("""SELECT * FROM read_csv_auto("""+literal(output/"subjects.csv")+""",all_varchar=true)
            WHERE subject<>'' AND excluded_type='false' AND TRY_CAST(legacy_entity_count AS INT)<=1
            ORDER BY TRY_CAST(abs_fv_current AS DOUBLE) DESC NULLS LAST,
                TRY_CAST(abs_fv_history AS DOUBLE) DESC,subject LIMIT ?""",[call_budget*50]).fetchdf().to_dict("records")
    client=None
    if selected and call is None:
        from dotenv import load_dotenv
        load_dotenv(ROOT/".env")
        from openai import OpenAI
        if os.environ.get("OPENAI_API_KEY"):
            client=OpenAI(max_retries=0,timeout=None)
    decisions=[];calls=0
    for offset in range(0,len(selected),50):
        batch=selected[offset:offset+50]
        texts=[r["input_text"] for r in batch]
        prompt=classifier._build_batch_prompt(texts,taxonomy)
        prompt_hash=hashlib.sha256((classifier._LLM_SYSTEM_PROMPT+"\n"+prompt).encode()).hexdigest()
        batch_path=output/("batch-"+str(offset//50+1))
        atomic_json(batch_path.with_suffix(".request.json"),dict(input_text=texts,prompt=prompt,
            system_prompt=classifier._LLM_SYSTEM_PROMPT,prompt_sha256=prompt_hash,requested_model="gpt-4o-mini"))
        metadata={"model":"gpt-4o-mini","response_id":None,"usage":None}
        raw=[]
        if call or client:
            calls+=1
            print("P5 model call "+str(calls)+"/"+str(call_budget),flush=True)
            if call:
                raw=call(texts,taxonomy)
            else:
                recorder=RecordedClient(client,batch_path.with_suffix(".response.json"))
                raw=classifier._call_openai_batch(texts,taxonomy,recorder)
                if recorder.metadata: metadata=recorder.metadata
        counts={i:sum(r.get("id")==i for r in raw) for i in range(1,len(batch)+1)}
        by_id={r.get("id"):r for r in raw if counts.get(r.get("id"))==1}
        for i,subject in enumerate(batch,1):
            entry=by_id.get(i,{})
            value=entry.get("gics_sub_industry","Other")
            accepted=value in taxonomy and entry.get("confidence")=="high"
            reason=("high_confidence_name_inference" if accepted else
                    "api_key_unavailable" if not call and not client else
                    "service_error" if metadata.get('error') else
                    "missing_or_ambiguous_response" if i not in by_id else "insufficient_evidence")
            decision=dict(subject=subject["subject"],input_text=subject["input_text"],status="inferred" if accepted else "abstained",
                value=value if accepted else None,confidence=entry.get("confidence","low"),reason=reason,
                model=metadata["model"],response_id=metadata["response_id"],prompt_sha256=prompt_hash,recorded_at=now(),
                verification="not_checked",derivation="inferred",evidence="Company wording from pinned holdings; model inference, no external source verification")
            decision["decision_id"]="sector-"+hashlib.sha256(json.dumps(decision,sort_keys=True).encode()).hexdigest()
            decisions.append(decision)
        atomic_json(batch_path.with_suffix(".result.json"),dict(metadata=metadata,results=raw,calls_used=calls))
    for path,expected in inputs.items():
        if sha(Path(path))!=expected: raise ValueError("P5 input changed: "+path)
    bundle=dict(format_version=1,admission_status="promoted",taxonomy_sha256=sha(taxonomy_path),
        input_holdings_sha256=sha(holdings),membership=dict(path="membership.csv",sha256=sha(output/"membership.csv")),
        decisions=decisions,authority="P5 authorized classification; inferred labels retain provenance")
    atomic_json(output/"sector_decisions.json",bundle)
    with duckdb.connect(config={"threads":2,"memory_limit":"-1"}) as con:
        import pandas as pd
        con.register("decisions",pd.DataFrame(decisions,columns=["subject","status","reason","value"]))
        con.execute("""COPY (SELECT s.*,coalesce(d.reason,CASE WHEN s.subject='' THEN 'missing_entity_name'
            WHEN s.excluded_type='true' THEN 'fund_or_government_not_company'
            WHEN TRY_CAST(s.legacy_entity_count AS INT)>1 THEN 'ambiguous_entity_assignment'
            ELSE 'outside_call_budget' END) AS reason FROM read_csv_auto("""+literal(output/"subjects.csv")+""",all_varchar=true) s
            LEFT JOIN decisions d ON s.subject=d.subject WHERE coalesce(d.status,'')<>'inferred') TO """+literal(output/"residuals.csv")+" (HEADER)")
        con.execute("""COPY (SELECT subject AS company_name_norm,value AS gics_sub_industry,'high' AS confidence,
            'programme_inference' AS source,? AS timestamp FROM decisions WHERE status='inferred') TO """+literal(output/"cache_for_quality_gate.csv")+" (HEADER)",[now()])
    from scripts.gics_quality_gate import validate_cache
    gate=validate_cache(output/"cache_for_quality_gate.csv")
    atomic_json(output/"quality_gate.json",dict(ok=gate.ok,issue_count=gate.issue_count,details=gate.details))
    atomic_json(output/"summary.json",dict(calls_used=calls,call_budget=call_budget,decisions=len(decisions),
        inferred=sum(d["status"]=="inferred" for d in decisions),abstained=sum(d["status"]=="abstained" for d in decisions),
        residual_file="residuals.csv",quality_gate=gate.ok,cached_rebuild="pending"))
    atomic_json(output/"complete.json",{p.name:sha(p) for p in output.iterdir() if p.is_file()})
    if not gate.ok: raise ValueError("P5 taxonomy quality gate failed")


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--holdings",type=Path,required=True)
    parser.add_argument("--output-dir",type=Path,required=True)
    parser.add_argument("--call-budget",type=int,required=True)
    args=parser.parse_args()
    output=args.output_dir.resolve()
    if not output.is_relative_to(ROOT/"scratch") or not 1<=args.call_budget<=20:
        parser.error("Use scratch output and an explicit budget of 1-20 calls")
    with heavy_lock(candidate_path("t1-runtime-20260910-v5")):
        run(args.holdings.resolve(),output,args.call_budget)


if __name__=="__main__": main()
