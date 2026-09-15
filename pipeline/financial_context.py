"""Read-only, independently supported USD NAV inputs for calculated percentages."""
from __future__ import annotations
import json
from pathlib import Path

import duckdb
import pandas as pd

from pipeline.programme.artifacts import literal
from pipeline.programme.core import sha

NAV_CONCEPTS={'stockholdersequity','netassetsornetassets','memberscapital','partnerscapital'}


def compatible_nav(holdings,financials_file,companyfacts_dir):
    """Accept a fund denominator only when cached USD instant facts agree.

    Later filings may revise prior quarters under latest-best history. Distinct
    values in the latest filing, or disagreement between NAV concept families,
    leave a denominator unavailable. No companyfacts download is possible here.
    """
    columns=['cik','report_date','net_assets']
    if holdings.empty or not Path(financials_file).is_file():
        return pd.DataFrame(columns=columns),pd.DataFrame(columns=['cik','report_date','net_assets','source_sha256','status'])
    financials_hash=sha(financials_file)
    records=[]
    unavailable_sources=[]
    with duckdb.connect(config={'threads':2,'memory_limit':'-1'}) as con:
        con.register('holdings',holdings)
        ciks=[r[0] for r in con.execute("SELECT DISTINCT lpad(cast(cik AS VARCHAR),10,'0') FROM holdings WHERE source='bdc' ORDER BY 1").fetchall()]
        for cik in ciks:
            if not cik.isdigit(): raise ValueError('Invalid NAV source CIK')
            path=Path(companyfacts_dir)/(cik+'.json')
            if not path.is_file(): continue
            before=sha(path)
            data=json.loads(path.read_text(encoding='utf-8'))
            declared_cik=data.get('cik')
            if declared_cik is None or str(declared_cik).strip()=='':
                # Legacy synthesized caches may omit the document identity.
                # Their filename/name is not independent support for a NAV:
                # retain the source hash and an explicit unavailable reason.
                if sha(path)!=before: raise ValueError('NAV source changed while reading')
                unavailable_sources.append(dict(cik=cik,source_sha256=before,status='source_cik_missing'))
                continue
            if str(declared_cik).zfill(10)!=cik:
                raise ValueError('NAV source CIK does not match its filename: '+str(path)
                                 +' (expected '+cik+', declared '+str(declared_cik)+')')
            # These are structured source facts, not row-wise holdings transforms.
            for namespace,concepts in data.get('facts',{}).items():
                for concept,payload in concepts.items():
                    if concept.lower() not in NAV_CONCEPTS: continue
                    for fact in payload.get('units',{}).get('USD',[]):
                        if not fact.get('start') and fact.get('end') and fact.get('filed'):
                            records.append(dict(cik=cik,report_date=fact['end'],concept=namespace+':'+concept,
                                filed=fact['filed'],accession=fact.get('accn'),value=fact.get('val'),source_sha256=before))
            if sha(path)!=before: raise ValueError('NAV source changed while reading')
        facts=pd.DataFrame(records,columns=['cik','report_date','concept','filed','accession','value','source_sha256'])
        for column in ('cik','report_date','concept','filed','accession','source_sha256'):
            facts[column]=facts[column].astype('string')
        con.register('nav_facts',facts)
        unavailable=pd.DataFrame(unavailable_sources,columns=['cik','source_sha256','status']).astype('string')
        con.register('unavailable_nav_sources',unavailable)
        con.execute("""CREATE TEMP TABLE nav_source AS WITH latest AS (
            SELECT *,max(TRY_CAST(filed AS DATE)) OVER(PARTITION BY cik,report_date,concept) AS last_filed
            FROM nav_facts WHERE TRY_CAST(report_date AS DATE) IS NOT NULL
                AND isfinite(TRY_CAST(value AS DOUBLE)))
            SELECT cik,report_date,count(DISTINCT TRY_CAST(value AS DECIMAL(38,12))) AS values_count,
                min(TRY_CAST(value AS DECIMAL(38,12))) AS nav,min(source_sha256) AS source_sha256
            FROM latest WHERE TRY_CAST(filed AS DATE)=last_filed GROUP BY cik,report_date""")
        con.execute("""CREATE TEMP TABLE denominator_audit AS WITH wanted AS (
            SELECT DISTINCT lpad(cast(cik AS VARCHAR),10,'0') AS cik,CAST(report_date AS VARCHAR) AS report_date
            FROM holdings WHERE source='bdc'), ff AS (
            SELECT lpad(cast(cik AS VARCHAR),10,'0') AS cik,CAST(report_date AS VARCHAR) AS report_date,
                count(DISTINCT TRY_CAST(net_assets AS DECIMAL(38,12))) AS variants,
                min(TRY_CAST(net_assets AS DECIMAL(38,12))) AS net_assets
            FROM read_csv_auto("""+literal(financials_file)+""",all_varchar=true) WHERE source='companyfacts' GROUP BY ALL)
            SELECT w.*,f.net_assets,coalesce(s.source_sha256,u.source_sha256) AS source_sha256,
                CASE WHEN u.status IS NOT NULL THEN u.status
                     WHEN s.cik IS NULL THEN 'no_cached_usd_nav'
                     WHEN s.values_count<>1 THEN 'ambiguous_latest_source_nav'
                     WHEN f.variants<>1 OR f.net_assets IS NULL THEN 'missing_or_ambiguous_fund_nav'
                     WHEN f.net_assets<>s.nav THEN 'fund_nav_disagrees_with_source'
                     WHEN f.net_assets=0 THEN 'zero_denominator' ELSE 'compatible' END AS status
            FROM wanted w LEFT JOIN ff f USING(cik,report_date) LEFT JOIN nav_source s USING(cik,report_date)
            LEFT JOIN unavailable_nav_sources u USING(cik)""")
        nav=con.execute("SELECT cik,report_date,CAST(net_assets AS DOUBLE) AS net_assets FROM denominator_audit WHERE status='compatible'").fetchdf()
        audit=con.execute('SELECT * FROM denominator_audit ORDER BY cik,report_date').fetchdf()
    if sha(financials_file)!=financials_hash: raise ValueError('Fund NAV inputs changed while reading')
    return nav,audit
