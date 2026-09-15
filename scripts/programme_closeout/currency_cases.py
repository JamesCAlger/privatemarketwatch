"""Bounded printed-row evidence for source currency exceptions; cache only."""
import argparse
import json
import os
from pathlib import Path
import threading
import time
import duckdb
from lxml import etree
from scripts.programme_reference.source_reader import local,clean
from scripts.programme_closeout.candidate import sha,atomic_json

ROOT=Path(__file__).resolve().parents[2]


def literal_rows(path,wanted):
    if path.stat().st_size>120_000_000:
        return [],'source_over_120MB_bound'
    tree=etree.parse(str(path),etree.HTMLParser(no_network=True,recover=True,huge_tree=True))
    selected={}
    for fact in tree.iter():
        if not isinstance(fact.tag,str):continue
        context=fact.get('contextref') or fact.get('contextRef')
        if context not in wanted:continue
        row=next((n for n in fact.iterancestors() if local(n.tag)=='tr'),None)
        if row is None:continue
        xpath=tree.getpath(row)
        if xpath not in selected:
            table=next((n for n in row.iterancestors() if local(n.tag)=='table'),None)
            preceding=[] if table is None else [clean(n) for n in table.itersiblings(preceding=True)][:5]
            selected[xpath]=dict(row_xpath=xpath,context_ids=[],cells=[clean(n) for n in row if local(n.tag) in ('td','th')],
                table_xpath=tree.getpath(table) if table is not None else '',preceding=preceding,
                facts=[])
        record=selected[xpath]
        if context not in record['context_ids']:record['context_ids'].append(context)
        record['facts'].append(dict(concept=fact.get('name'),context_id=context,
            unit_ref=fact.get('unitref') or fact.get('unitRef'),scale=fact.get('scale'),text=clean(fact)))
    return list(selected.values()),'literal_source_rows'


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--resolution',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();out=a.output.resolve()
    if not out.is_relative_to(ROOT/'docs/production_stack/programme_closeout_evidence_2026-09-09') and not out.is_relative_to(ROOT/'scratch'):
        raise ValueError('Invalid output')
    out.mkdir(parents=True,exist_ok=True)
    if (out/'complete.json').exists():raise ValueError('Immutable completed evidence')
    start=time.monotonic()
    con=duckdb.connect(config={'memory_limit':'-1','threads':2})
    con.execute('CREATE TABLE r AS SELECT * FROM read_csv(?,all_varchar=true)',[str(a.resolution/'resolved_exceptions.csv')])
    con.execute("""CREATE TABLE selected AS SELECT * FROM r WHERE resolved_currency IS NOT NULL AND resolved_currency<>'USD'
        QUALIFY row_number() OVER(PARTITION BY resolved_currency,field ORDER BY report_date,cik,row_id)<=2""")
    # Retain every rare currency occurrence, not just an arbitrary illustrative row.
    con.execute("""INSERT INTO selected SELECT r.* FROM r ANTI JOIN selected s ON r.row_id=s.row_id AND r.field=s.field
        WHERE r.resolved_currency IN ('AFN','KPW','RSD','EGP')""")
    if con.execute('SELECT count(*) FROM selected').fetchone()[0]>150:raise ValueError('Case row bound')
    con.execute("""CREATE TABLE cases AS SELECT s.*,h.src_context_id,h.bdc_dimensions_raw FROM selected s
        LEFT JOIN read_csv(?,all_varchar=true) h ON s.row_id=h.row_id""",[str(ROOT/'data/output/private_markets_holdings.csv')])
    names=[c[0] for c in con.execute('DESCRIBE cases').fetchall()]
    cases=[dict(zip(names,r)) for r in con.execute('SELECT * FROM cases ORDER BY cik,accession,field,row_id').fetchall()]
    grouped={}
    for c in cases:grouped.setdefault((c['cik'],c['accession'],c['report_date']),[]).append(c)
    results=[]
    for i,((cik,acc,quarter),items) in enumerate(grouped.items()):
        path=ROOT/'data/raw/filings/bdc_html'/cik.lstrip('0')/(acc.replace('-','')+'.html')
        result=dict(cik=cik,accession=acc,report_date=quarter,path=path.relative_to(ROOT).as_posix(),
                    status='missing_html',cases=items)
        if path.exists():
            wanted={c['src_context_id'] for c in items}
            rows,status=literal_rows(path,wanted)
            result.update(status=status,sha256=sha(path))
            # Full literal row cells and contexts are preserved; no automatic
            # override is derived merely from a currency's implausible name.
            result['source_rows']=rows
        results.append(result)
        atomic_json(out/'cases.json',results)
        print(f'Currency source documents {i+1}/{len(grouped)}; {result["status"]}',flush=True)
    atomic_json(out/'complete.json',dict(status='complete',documents=len(grouped),cases=len(cases),
        seconds=time.monotonic()-start,interpretation='Printed/tagged evidence requiring explicit source decisions'))
    con.close()


if __name__=='__main__':main()
