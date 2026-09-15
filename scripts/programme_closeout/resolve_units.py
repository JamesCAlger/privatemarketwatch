"""Resolve the pipeline's uppercased unit tokens against pinned source-unit definitions."""
import argparse
import json
import os
from pathlib import Path
import threading
import time
import duckdb
from scripts.programme_closeout.candidate import sha,atomic_json

ROOT=Path(__file__).resolve().parents[2]


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();out=a.output.resolve()
    if not out.is_relative_to(ROOT/'docs/production_stack/programme_closeout_evidence_2026-09-09') and not out.is_relative_to(ROOT/'scratch'):
        raise ValueError('Invalid output')
    if out.exists():raise ValueError('New output required')
    out.mkdir(parents=True)
    start=time.monotonic()
    con=duckdb.connect(config={'memory_limit':'-1','threads':2})
    paths=[a.source/'document_units.csv',a.source/'unit_exceptions.csv']
    con.execute('CREATE TABLE u AS SELECT * FROM read_csv(?,all_varchar=true)',[str(paths[0])])
    con.execute('CREATE TABLE f AS SELECT * FROM read_csv(?,all_varchar=true)',[str(paths[1])])
    con.execute("""CREATE TABLE alias AS SELECT cik,accession,upper(unit_ref) alias,
        count(DISTINCT coalesce(currency,'NOT_MONEY')) currencies,max(currency) currency
        FROM u GROUP BY ALL""")
    con.execute("""CREATE TABLE r AS SELECT f.*,CASE
        WHEN f.source_currency IS NOT NULL THEN f.source_currency
        WHEN a.currencies=1 THEN a.currency
        ELSE NULL END resolved_currency,
        CASE WHEN f.source_currency IS NOT NULL THEN 'exact_source_unit'
             WHEN a.currencies=1 AND a.currency IS NOT NULL THEN 'case_normalized_source_unit'
             WHEN a.currencies>1 THEN 'ambiguous_case_normalized_unit'
             WHEN coalesce(f.raw_unit,'')='' THEN 'absent_unit_default_requires_contrary_evidence_check'
             ELSE 'unresolved_source_unit' END resolution
        FROM f LEFT JOIN alias a ON f.cik=a.cik AND f.accession=a.accession AND upper(f.raw_unit)=a.alias""")
    def export(name,sql):
        dest=(out/name).as_posix().replace("'","''")
        con.execute(f"COPY ({sql}) TO '{dest}' (FORMAT CSV,HEADER)")
    export('resolved_exceptions.csv', 'SELECT * FROM r ORDER BY report_date,cik,field,row_id')
    export('conversion_requirements.csv',"""SELECT report_date,field,resolved_currency currency,count(*) field_observations,
        count(DISTINCT cik) funds,sum(try_cast(amount AS DECIMAL(38,8))) signed_original_amount,
        sum(abs(try_cast(published_fv AS DECIMAL(38,8)))) published_abs_fv_exposure
        FROM r WHERE resolved_currency<>'USD' GROUP BY ALL ORDER BY 1,2,3""")
    export('resolution_summary.csv',"""SELECT resolution,coalesce(resolved_currency,'') currency,field,count(*) field_observations,
        count(DISTINCT cik) funds FROM r GROUP BY ALL ORDER BY 1,2,3""")
    export('unresolved_tokens.csv',"""SELECT resolution,raw_unit,field,count(*) field_observations,count(DISTINCT cik) funds
        FROM r WHERE resolved_currency IS NULL GROUP BY ALL ORDER BY field_observations DESC""")
    export('source_examples.csv',"""SELECT * FROM r QUALIFY row_number() OVER(PARTITION BY resolution,
        resolved_currency,field ORDER BY report_date,cik,row_id)<=5""")
    summary=dict(status='complete',elapsed_seconds=time.monotonic()-start,
                 currencies=con.execute("SELECT DISTINCT resolved_currency FROM r WHERE resolved_currency IS NOT NULL ORDER BY 1").fetchall(),
                 foreign_field_observations=con.execute("SELECT count(*) FROM r WHERE resolved_currency<>'USD'").fetchone()[0],
                 remaining_unresolved=con.execute("SELECT count(*) FROM r WHERE resolved_currency IS NULL").fetchone()[0],
                 candidate_sha256=json.loads((a.source/'complete.json').read_text())['candidate_sha256'],
                 inputs=[dict(path=str(p),sha256=sha(p)) for p in paths],
                 scope='Refinement of non-USD/missing/unknown token exceptions; exact USD rows remain in original inventory')
    atomic_json(out/'complete.json',summary);con.close();
    print(json.dumps(summary,sort_keys=True),flush=True)


if __name__=='__main__':main()
