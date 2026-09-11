"""Document-scoped monetary units for the required cohort; cache-only, 15-minute cap."""
from __future__ import annotations
import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
import threading
import time
import duckdb
from lxml import etree

ROOT = Path(__file__).resolve().parents[2]
XBRLI = 'http://www.xbrl.org/2003/instance'


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def document_units(path):
    """Read unit definitions only; no production parser, network or entity expansion."""
    result = []
    for event, elem in etree.iterparse(str(path), events=('end',), load_dtd=False,
                                       no_network=True, resolve_entities=False, huge_tree=True):
        if elem.tag == '{'+XBRLI+'}unit':
            numerator = elem.findall('./{'+XBRLI+'}measure')
            measures = [str(n.text or '').strip() for n in numerator]
            simple = len(measures) == 1 and elem.find('{'+XBRLI+'}divide') is None
            value = measures[0].split(':')[-1].upper() if simple else ''
            ns = numerator[0].nsmap.get(measures[0].split(':')[0], '') if simple and ':' in measures[0] else ''
            currency = value if ns == 'http://www.xbrl.org/2003/iso4217' and len(value) == 3 else ''
            result.append(dict(unit_ref=elem.get('id',''), measures=json.dumps(measures),
                               currency=currency, kind='monetary' if currency else 'non_monetary_or_composite'))
        # Retain children until the owning unit has been read; all other completed
        # root-level facts/contexts can be freed, keeping large filings bounded.
        if elem.getparent() is not None and elem.getparent().getparent() is None:
            elem.clear()
            while elem.getprevious() is not None:
                del elem.getparent()[0]
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    out=a.output.resolve()
    if not out.is_relative_to(ROOT/'scratch') and not out.is_relative_to(ROOT/'docs/production_stack/programme_closeout_evidence_2026-09-09'):
        raise ValueError('Output must be named closeout evidence or scratch')
    out.mkdir(parents=True,exist_ok=True)
    if (out/'complete.json').exists():
        raise ValueError('Completed evidence is immutable')
    timer=threading.Timer(900,lambda:os._exit(124));timer.daemon=True;timer.start()
    started=time.monotonic()
    candidate=ROOT/'data/output/private_markets_holdings.csv'
    candidate_sha=sha(candidate)
    cohort=ROOT/'data/overrides/wrapper_cohorts/v2_70_gate_verified_wrapper_manifest.json'
    ids=[e['cik'] for e in json.loads(cohort.read_text())['entries']]
    con=duckdb.connect(config={'memory_limit':'2GB','threads':2})
    con.execute('SET temp_directory=?',[str(out/'temp')])
    con.execute("CREATE TABLE scope(cik VARCHAR)")
    con.executemany("INSERT INTO scope VALUES (?)",[(c,) for c in ids])
    print('Read cohort monetary fields',flush=True)
    con.execute("""CREATE TABLE h AS SELECT h.* FROM read_csv(?,all_varchar=true) h
        SEMI JOIN scope s ON lpad(h.cik,10,'0')=s.cik
        WHERE h.report_date BETWEEN '2023-03-31' AND '2026-03-31'""",[str(candidate)])
    docs=con.execute("""SELECT DISTINCT lpad(cik,10,'0'),coalesce(accession_number,'') FROM h
        WHERE lower(source)='bdc' ORDER BY 1,2""").fetchall()
    rows=[];inputs=[];statuses=[]
    checkpoint=out/'documents';checkpoint.mkdir(exist_ok=True)
    for i,(cik,acc) in enumerate(docs):
        path=ROOT/'data/raw/filings/bdc_xbrl'/cik.lstrip('0')/(acc.replace('-','')+'.xml')
        saved=checkpoint/(cik+'_'+acc.replace('-','')+'.json')
        stat=path.stat() if path.exists() else None
        old=json.loads(saved.read_text()) if saved.exists() else {}
        identity=(stat.st_size,stat.st_mtime_ns) if stat else None
        if old.get('identity') == list(identity or []) and old.get('reader_sha256')==sha(Path(__file__)):
            item=old
        else:
            item=dict(cik=cik,accession=acc,path=path.relative_to(ROOT).as_posix(),
                      identity=list(identity or []),reader_sha256=sha(Path(__file__)),units=[],
                      status='missing_xml',sha256='')
            if stat:
                item['sha256']=sha(path)
                try:
                    item['units']=document_units(path)
                    item['status']='units_read'
                except (etree.XMLSyntaxError,OSError) as exc:
                    item['status']='source_parse_error'
                    item['error']=str(exc)[:500]
            saved.write_text(json.dumps(item,sort_keys=True,indent=2),encoding='utf-8')
        inputs.append({k:item[k] for k in ('path','sha256','identity')})
        statuses.append(dict(cik=cik,accession=acc,status=item['status'],units=len(item['units'])))
        rows.extend(dict(cik=cik,accession=acc,**unit) for unit in item['units'])
        if i%25==0 or i==len(docs)-1:
            print(f'Unit documents {i+1}/{len(docs)}; elapsed {time.monotonic()-started:.1f}s',flush=True)
    def csvout(name, records):
        with (out/name).open('w',newline='',encoding='utf-8') as f:
            w=csv.DictWriter(f,fieldnames=list(records[0]));w.writeheader();w.writerows(records)
    csvout('document_units.csv',rows);csvout('document_status.csv',statuses)
    con.execute('CREATE TABLE units AS SELECT * FROM read_csv(?,all_varchar=true)',[str(out/'document_units.csv')])
    con.execute('CREATE TABLE doc_status AS SELECT * FROM read_csv(?,all_varchar=true)',[str(out/'document_status.csv')])
    projections=[]
    for field in ('fair_value','cost','principal_amount'):
        projections.append(f"""SELECT lpad(cik,10,'0') cik,report_date,coalesce(accession_number,'') accession,row_id,
            issuer_name,bdc_investment_identifier,'{field}' field,
            try_cast({field} AS DECIMAL(38,8)) amount,
            coalesce({field}_currency,'') raw_unit,try_cast(fair_value AS DECIMAL(38,8)) published_fv
            FROM h WHERE lower(source)='bdc'""")
    con.execute('CREATE TABLE fields AS '+' UNION ALL '.join(projections))
    con.execute("""CREATE TABLE classified AS SELECT f.*,u.currency source_currency,u.kind unit_kind,d.status document_status,
        CASE WHEN f.amount IS NULL THEN 'missing_value'
             WHEN u.currency<>'' THEN CASE WHEN u.currency='USD' THEN 'reported_unit_USD' ELSE 'reported_unit_foreign' END
             WHEN f.raw_unit='' THEN 'absent_unit_requires_default_or_source_decision'
             WHEN u.unit_ref IS NOT NULL THEN 'non_monetary_or_composite_unit'
             WHEN d.status='missing_xml' THEN 'source_xml_unavailable'
             ELSE 'unresolved_unit_token' END unit_status
        FROM fields f LEFT JOIN units u ON f.cik=u.cik AND f.accession=u.accession AND f.raw_unit=u.unit_ref
        LEFT JOIN doc_status d ON f.cik=d.cik AND f.accession=d.accession""")
    queries={
        'unit_population.csv':"""SELECT report_date,field,unit_status,coalesce(source_currency,'') currency,
            count(*) field_observations,count(DISTINCT cik) funds,sum(amount) signed_original_amount,
            sum(abs(published_fv)) published_abs_fv_exposure FROM classified GROUP BY ALL ORDER BY 1,2,3,4""",
        'conversion_requirements.csv':"""SELECT report_date,field,source_currency currency,count(*) field_observations,
            count(DISTINCT cik) funds,sum(amount) signed_original_amount,sum(abs(published_fv)) published_abs_fv_exposure
            FROM classified WHERE unit_status='reported_unit_foreign' GROUP BY ALL ORDER BY 1,2,3""",
        'unit_exceptions.csv':"""SELECT * FROM classified WHERE unit_status NOT IN ('missing_value','reported_unit_USD')
            ORDER BY report_date,cik,field,row_id""",
    }
    for name,sql in queries.items():
        sqlpath=(out/name).as_posix().replace("'","''")
        con.execute(f"COPY ({sql}) TO '{sqlpath}' (FORMAT CSV, HEADER)")
    before=sha(candidate)
    if before != candidate_sha:
        raise RuntimeError('Candidate input changed during unit inventory')
    summary=dict(status='complete',elapsed_seconds=round(time.monotonic()-started,2),holdings_rows=con.execute('SELECT count(*) FROM h').fetchone()[0],
                 documents=len(docs),document_states=dict(con.execute('SELECT status,count(*) FROM doc_status GROUP BY 1').fetchall()),
                 field_states=dict(con.execute('SELECT unit_status,count(*) FROM classified GROUP BY 1').fetchall()),
                 candidate_sha256=before,cohort_sha256=sha(cohort),
                 script_sha256=sha(Path(__file__)),interpretation='Actual XBRL unit definitions; printed/tagged conflicts still require source adjudication')
    (out/'input_manifest.json').write_text(json.dumps(inputs,indent=2),encoding='utf-8')
    (out/'complete.json').write_text(json.dumps(summary,indent=2,sort_keys=True),encoding='utf-8')
    con.close();timer.cancel();print(json.dumps(summary,sort_keys=True),flush=True)


if __name__=='__main__':main()
