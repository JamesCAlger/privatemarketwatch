"""Cache-only inline citations joined by filing, context, field and value.

Index a source document once, then join its facts to observations in DuckDB.
Unresolved transformations, currencies and ambiguous source facts produce no
link. The history exporter supplies an explicit unavailable state for them.
"""
from __future__ import annotations

from collections import Counter
from datetime import date
from decimal import Decimal, InvalidOperation
import hashlib
import json
from pathlib import Path
import re

from lxml import etree
import pandas as pd

from pipeline.citation_resolver import local
from pipeline.programme.core import sha
from pipeline.programme.artifacts import literal

FIELDS=("fair_value","cost","interest_rate","maturity_date","gics_sub_industry","gics_sector")
FACT_COLUMNS=["context_id","concept","field","period","unit","number","text","fragment","eligible","date_value"]
# XBRL Transformation Registry 2 zerodashType; a bare dash has no numeric
# meaning without its declared transformation. Registry 4 fixed-zero accepts
# any string, but an empty fact cannot provide a visible citation target.
ZERO_DASHES=frozenset('-\u058a\u05be\u2010\u2011\u2012\u2013\u2014\u2015\ufe58\ufe63\uff0d')


def inline_date(text,fmt):
    """Decode complete, declared numeric dates without guessing date order.

    XBRL Registry 4 date-month-day-year defines short years as 2000-2099.
    Partial dates and unsupported transformations do not create exact dates.
    """
    parts=None
    if not fmt and re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}',text):
        year,month,day=map(int,text.split('-'))
        parts=(year,month,day)
    elif fmt in ('date-month-day-year','datemonthdayyear','dateslashus'):
        pattern=r'([0-9]{1,2})[^0-9]+([0-9]{1,2})[^0-9]+([0-9]{1,2}|[0-9]{4})'
        match=re.fullmatch(pattern,text)
        if match:
            month,day,year=map(int,match.groups())
            if len(match[3])<=2: year+=2000
            parts=(year,month,day)
    elif fmt in ('date-year-month-day','dateyearmonthday'):
        match=re.fullmatch(r'([0-9]{1,2}|[0-9]{4})[^0-9]+([0-9]{1,2})[^0-9]+([0-9]{1,2})',text)
        if match:
            year,month,day=map(int,match.groups())
            if len(match[1])<=2: year+=2000
            parts=(year,month,day)
    try:
        return date(*parts).isoformat() if parts else None
    except ValueError:
        return None


def add_interpretation_evidence(con,*,release_id,sector_bundle=None,sector_audit=None,taxonomy=None,cost_donors=None):
    """Attach admitted inference and calculation records, never filing labels."""
    # Missing USD value is not missing disclosure. Retain the original foreign
    # amount and unit as unavailable evidence without presenting it as USD.
    con.execute("""INSERT INTO history_evidence SELECT h.row_id,'fair_value',to_json(struct_pack(
        status := 'unavailable',release_id := ?,row_id := h.row_id,field := 'fair_value',
        reason := json_extract_string(TRY_CAST(h.src_facts AS JSON),'$._financial_fair_value.state'),
        source_amount := json_extract_string(TRY_CAST(h.src_facts AS JSON),'$._financial_fair_value.raw'),
        source_currency := json_extract_string(TRY_CAST(h.src_facts AS JSON),'$._financial_fair_value.currency')))
        FROM history h WHERE h.fair_value IS NULL
        AND json_extract_string(TRY_CAST(h.src_facts AS JSON),'$._financial_fair_value.state')
            IN ('FX_unavailable','FX_stale','unit_unresolved')
        AND NOT EXISTS(SELECT 1 FROM history_evidence e WHERE e.row_id=h.row_id AND e.field='fair_value')""",[release_id])
    con.execute("""INSERT INTO history_evidence SELECT h.row_id,'fair_value',to_json(struct_pack(
        status := 'calculated',release_id := ?,row_id := h.row_id,field := 'fair_value',
        method := json_extract_string(TRY_CAST(h.src_facts AS JSON),'$._financial_fx.fair_value.conversion.method'),
        calculation := json_extract(TRY_CAST(h.src_facts AS JSON),'$._financial_fx.fair_value'),
        input := CAST('{"status":"unavailable","reason":"Original monetary fact requires its own verified source locator"}' AS JSON)))
        FROM history h WHERE h.fair_value IS NOT NULL
        AND json_extract_string(TRY_CAST(h.src_facts AS JSON),'$._financial_fx.fair_value.conversion.method')
            IN ('report_date_reference_conversion','already_USD')
        AND NOT EXISTS(SELECT 1 FROM history_evidence e WHERE e.row_id=h.row_id AND e.field='fair_value')""",[release_id])
    if sector_bundle and sector_audit and Path(sector_bundle).is_file() and Path(sector_audit).is_file():
        from pipeline.sector_enrichment import load_decisions,SUBJECT_SQL
        bundle,membership=load_decisions(sector_bundle,taxonomy)
        decisions=pd.DataFrame(bundle['decisions'],columns=['decision_id','subject','status','value','input_text','model'])
        con.register('sector_decisions',decisions)
        con.execute('CREATE OR REPLACE TEMP TABLE sector_audit AS SELECT * FROM read_csv_auto('+literal(sector_audit)+',all_varchar=true)')
        con.execute('CREATE OR REPLACE TEMP TABLE sector_members AS SELECT * FROM read_csv_auto('+literal(membership)+',all_varchar=true)')
        if con.execute('SELECT count(*) FROM (SELECT row_id FROM sector_audit GROUP BY ALL HAVING count(*)>1)').fetchone()[0]:
            raise ValueError('Repeated sector application evidence')
        if con.execute('SELECT count(*) FROM (SELECT row_id FROM sector_members GROUP BY ALL HAVING count(*)>1)').fetchone()[0]:
            raise ValueError('Repeated sector observation membership')
        for field in ('gics_sub_industry','gics_sector'):
            if field not in {r[0] for r in con.execute('DESCRIBE history').fetchall()}: continue
            con.execute("""INSERT INTO history_evidence SELECT h.row_id,?,to_json(struct_pack(
                status := 'inferred',release_id := ?,row_id := h.row_id,field := ?,decision_id := d.decision_id,
                model := d.model,input_text := d.input_text,taxonomy_sha256 := ?,
                reason := 'Model inference from company wording; not a disclosed filing classification'))
                FROM history h JOIN sector_audit a USING(row_id) JOIN sector_members m USING(row_id)
                JOIN sector_decisions d ON d.decision_id=a.decision_id AND d.subject=m.subject
                WHERE a.status='applied' AND d.status='inferred' AND h.gics_sub_industry=d.value
                AND """+SUBJECT_SQL+"=m.subject AND coalesce(CAST(h.\""+field+"\" AS VARCHAR),'')<>''",
                [field,release_id,field,bundle['taxonomy_sha256']])
        con.unregister('sector_decisions')
    if cost_donors and Path(cost_donors).is_file():
        con.execute('CREATE OR REPLACE TEMP TABLE cost_donors AS SELECT * FROM read_csv_auto('+literal(cost_donors)+',all_varchar=true)')
        if con.execute('SELECT count(*) FROM (SELECT row_id FROM cost_donors GROUP BY ALL HAVING count(*)>1)').fetchone()[0]:
            raise ValueError('Repeated cost donor evidence')
        con.execute("""INSERT INTO history_evidence SELECT h.row_id,'cost',to_json(struct_pack(
            status := 'calculated',release_id := ?,row_id := h.row_id,field := 'cost',method := a.method,
            donor_row_id := d.row_id,donor_date := d.report_date,donor_release := a.donor_release,
            input := coalesce(e.payload,CAST('{"status":"unavailable","reason":"No verified donor field locator in this release"}' AS JSON))))
            FROM history h JOIN cost_donors a USING(row_id) JOIN history d ON d.row_id=a.donor_row_id
                AND d.cik=h.cik AND d.position_id=h.position_id AND d.source=h.source
                AND d.report_date=TRY_CAST(a.donor_date AS DATE)
                AND TRY_CAST(CAST(d.fair_value AS VARCHAR) AS DECIMAL(38,12))=TRY_CAST(CAST(h.cost AS VARCHAR) AS DECIMAL(38,12))
            LEFT JOIN history_evidence e ON e.row_id=d.row_id AND e.field='fair_value'
            WHERE a.method='first_observed_fv_proxy' AND h.cost_source=a.method AND a.donor_release=?""",
            [release_id,release_id])


def inline_records(tree,source_hash):
    """Walk XML nodes, not holdings rows; retain duplicate facts as ambiguity."""
    from pipeline.bdc_filings import _match_concept
    nodes=list(tree.iter())
    contexts={};units={}
    ids=Counter(node.get("id") for node in nodes if node.get("id"))
    for node in nodes:
        kind=local(node.tag)
        if kind=="context":
            dates=[(child.text or "").strip() for child in node.iter() if local(child.tag) in ("instant","enddate")]
            contexts[node.get("id")]=dates[0] if len(dates)==1 and ids[node.get("id")]==1 else None
        elif kind=="unit":
            measures=[local((child.text or "").strip()) for child in node.iter() if local(child.tag)=="measure"]
            units[node.get("id")]=measures[0] if len(measures)==1 and ids[node.get("id")]==1 else "unresolved"
    records=[]
    for node in nodes:
        if local(node.tag) not in ("nonfraction","nonnumeric"): continue
        name=node.get("name") or ""
        field=_match_concept(local(name))
        if field not in FIELDS: continue
        context=node.get("contextref") or node.get("contextRef")
        text=" ".join("".join(node.itertext()).split())
        unitref=node.get("unitref") or node.get("unitRef") or ""
        unit=units.get(unitref,unitref.lower() if unitref.lower() in ("usd","pure") else "unresolved")
        eligible=bool(contexts.get(context)) and all(local(parent.tag) not in ("hidden","header") for parent in node.iterancestors())
        eligible=eligible and not any(local(k)=="nil" and v.lower()=="true" for k,v in node.attrib.items())
        eligible=eligible and (not node.get("id") or ids[node.get("id")]==1)
        # Only uncomplicated numeric lexemes are resolved. Unsupported inline
        # transformations remain unavailable instead of guessing punctuation.
        number=None
        date_value=None
        if field in ("fair_value","cost","interest_rate"):
            fmt=local(node.get("format") or "")
            try:
                lexical=text.replace(",","").strip()
                if lexical.startswith("(") and lexical.endswith(")"): lexical="-"+lexical[1:-1]
                if fmt=="fixed-zero" or (fmt=="zerodash" and text in ZERO_DASHES): lexical="0"
                if fmt=="zerodash" and text not in ZERO_DASHES: lexical="invalid"
                number=Decimal(lexical)*(Decimal(10)**int(node.get("scale") or "0"))
                if node.get("sign")=="-": number=-abs(number)
                if not number.is_finite(): number=None
            except (InvalidOperation,ValueError,OverflowError): pass
            if fmt and fmt not in ("num-dot-decimal","numdotdecimal","numcommadot","num-dot-decimal-in","fixed-zero","zerodash"):
                number=None
            if number is None or not text: eligible=False
        elif field=='maturity_date':
            date_value=inline_date(text,local(node.get('format') or ''))
            if date_value is None: eligible=False
        fragment="evidence-"+hashlib.sha256((source_hash+str(context)+name).encode()).hexdigest()[:24]
        records.append(dict(context_id=context,concept=local(name),field=field,period=contexts.get(context),unit=unit,
            number=str(number) if number is not None else None,text=text,fragment=fragment,eligible=eligible,date_value=date_value))
        # Setting a unique context/concept anchor is safe only when the SQL
        # selector later proves that exactly one matching fact exists.
        node.set("data-evidence-anchor",fragment)
    return records


def build_inline_evidence(con,*,cache_dir,output_dir,release_id,history_table="history"):
    """Create history_evidence from the complete selected history population.

    The caller owns the release directory and history table. This function
    never downloads filings or changes the cache. Every actual rendered link
    pins the source hash and matches the observation's accession and period.
    """
    if history_table!="history": raise ValueError("Expected the exporter's history table")
    from pipeline.bdc_filings import CANONICAL_CONCEPT
    from scripts.programme_closeout.citation_viewer import sanitize
    cache=Path(cache_dir);output=Path(output_dir)
    from pipeline.bdc_xbrl_html_bridge import load_html_section_bridge_rows
    from pipeline.history_bridge_evidence import attach as attach_bridge
    bridges=load_html_section_bridge_rows()
    con.execute("CREATE OR REPLACE TEMP TABLE history_evidence(row_id VARCHAR,field VARCHAR,payload JSON)")
    documents=con.execute("""SELECT DISTINCT cik,accession_number FROM history
        WHERE (coalesce(src_context_id,'')<>'' OR coalesce(src_field_overrides,'') LIKE '%=bridge:%')
        AND coalesce(accession_number,'')<>'' ORDER BY ALL""").fetchall()
    records=[]
    for cik,accession in documents:
        if not str(cik).isdigit() or not all(c.isdigit() or c=="-" for c in accession):
            raise ValueError("Invalid source document identity")
        source=cache/str(int(cik))/(accession.replace("-","")+".html")
        if not source.is_file():
            records.append(dict(cik=cik,accession=accession,status="unavailable",reason="cached_html_missing"));continue
        source_hash=sha(source)
        tree=etree.parse(str(source),etree.HTMLParser(no_network=True,huge_tree=True,recover=True))
        facts=pd.DataFrame(inline_records(tree,source_hash),columns=FACT_COLUMNS)
        con.register("inline_facts",facts)
        # A duplicate with the same value is still an ambiguous source locator.
        con.execute("""CREATE OR REPLACE TEMP TABLE unique_inline AS SELECT * FROM inline_facts
            QUALIFY count(*) OVER(PARTITION BY context_id,concept)=1""")
        source_dir=output/cik/"sources";source_dir.mkdir(parents=True,exist_ok=True)
        filename=accession+"-"+source_hash[:16]+".html"
        href="/data/holdings_history/"+cik+"/sources/"+filename+"#"
        for field in ("fair_value","cost","interest_rate","maturity_date"):
            canonical=CANONICAL_CONCEPT[field]
            if field in ("fair_value","cost"):
                # DOUBLE -> high-scale DECIMAL can invent sub-cent noise even
                # for exactly representable integers. Compare the canonical
                # numeric text instead; retain exact equality, no tolerance.
                agreement="i.unit='usd' AND TRY_CAST(i.number AS DECIMAL(38,12))=TRY_CAST(CAST(h.\""+field+"\" AS VARCHAR) AS DECIMAL(38,12))"
                if field=="cost": agreement+=" AND coalesce(h.cost_source,'') NOT IN ('derived_proxy','first_observed_fv_proxy')"
                if field=="fair_value": agreement+=" AND json_extract(TRY_CAST(h.src_facts AS JSON),'$._financial_fx.fair_value') IS NULL"
            elif field=="interest_rate":
                # A cash leg cannot be cited as the displayed all-in coupon.
                columns={r[0] for r in con.execute("DESCRIBE history").fetchall()}
                agreement="false" if "interest_rate_kind" not in columns else """h.interest_rate_kind='all_in'
                    AND i.unit='pure' AND TRY_CAST(i.number AS DECIMAL(38,12))*100=TRY_CAST(CAST(h.interest_rate AS VARCHAR) AS DECIMAL(38,12))"""
            else:
                agreement="TRY_CAST(i.date_value AS DATE)=h.maturity_date"
            con.execute("""INSERT INTO history_evidence SELECT h.row_id,?,to_json(struct_pack(
                status := 'direct',release_id := ?,row_id := h.row_id,field := ?,href := ?||i.fragment,
                source_text := i.text,source_sha256 := ?,accession_number := h.accession_number,
                context_id := i.context_id,concept := i.concept,unit := i.unit))
                FROM history h JOIN unique_inline i ON i.context_id=h.src_context_id
                    AND i.period=cast(h.report_date AS VARCHAR) AND i.field=?
                    AND i.concept=lower(coalesce(nullif(json_extract_string(TRY_CAST(h.src_facts AS JSON),? ),''),?))
                WHERE h.cik=? AND h.accession_number=? AND i.eligible AND """+agreement+"""
                    AND coalesce(h.corrected_fields,'') NOT LIKE ?
                    AND json_extract(TRY_CAST(h.src_facts AS JSON),?) IS NULL""",
                [field,release_id,field,href,source_hash,field,"$."+field+".c",canonical,cik,accession,"%"+field+"%","$."+field+".x"])
        if not bridges.empty:
            attach_bridge(con,tree,bridges,cik=cik,accession=accession,source_hash=source_hash,release_id=release_id,href=href,
                raw_html=source.read_text(encoding='utf-8',errors='replace'))
        fragments={r[0] for r in con.execute("""SELECT split_part(json_extract_string(payload,'$.href'),'#',2)
            FROM history_evidence WHERE json_extract_string(payload,'$.source_sha256')=?""",[source_hash]).fetchall()}
        if fragments:
            for node in tree.iter():
                anchor=node.attrib.pop("data-evidence-anchor",None)
                if anchor in fragments: node.set("id",anchor)
            sanitize(tree)
            counts=Counter(node.get("id") for node in tree.iter())
            if any(counts[f]!=1 for f in fragments): raise ValueError("Rendered source locator lost or ambiguous")
            target=source_dir/filename
            target.write_bytes(etree.tostring(tree,encoding="utf-8",method="html"))
            rendition_hash=sha(target)
        else: rendition_hash=None
        if sha(source)!=source_hash: raise ValueError("Source changed while building history evidence")
        records.append(dict(cik=cik,accession=accession,source_sha256=source_hash,rendition_sha256=rendition_hash,
            status="rendered" if fragments else "unavailable",verified_fragments=len(fragments)))
        con.unregister("inline_facts")
    (output/"source_documents.json").write_text(json.dumps(records,indent=2)+"\n",encoding="utf-8")
    return dict(documents=len(records),direct_fields=con.execute("SELECT count(*) FROM history_evidence").fetchone()[0])
