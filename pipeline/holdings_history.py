"""Complete cohort observation history for a pinned static frontend release."""
from __future__ import annotations
import json
from pathlib import Path

from pipeline.output_schemas import OUTPUT_SCHEMAS
from pipeline.programme.artifacts import literal,typed_query
from pipeline.programme.core import sha


def export_history(con,holdings_file,output_dir,*,cohort,start="2023-03-31",end="2026-03-31",release_id=None,source_cache=None,
                   sector_bundle=None,sector_audit=None,taxonomy=None,cost_donors=None,
                   cash_status_reference=None,xbrl_cache=None):
    holdings_file=Path(holdings_file)
    output=Path(output_dir);output.mkdir(parents=True,exist_ok=True)
    source_hash=sha(holdings_file)
    release_file=holdings_file.parent/'holdings_release.json'
    if release_file.is_file():
        pinned=json.loads(release_file.read_text(encoding='utf-8'))
        if pinned['holdings_sha256']!=source_hash:
            raise ValueError('History holdings do not match the finalized release')
        if release_id and release_id!=pinned['release_id']:
            raise ValueError('Requested history release differs from finalized holdings')
        release_id=pinned['release_id']
    interpretation_inputs={str(Path(p).resolve()):sha(p) for p in (sector_bundle,sector_audit,taxonomy,cost_donors)
        if p and Path(p).is_file()}
    release=release_id or "holdings-"+source_hash
    schema=OUTPUT_SCHEMAS["private_markets_holdings.csv"]
    con.execute("""CREATE OR REPLACE TEMP TABLE history AS SELECT * FROM ("""+
        typed_query(holdings_file,schema)+") WHERE cik IN (SELECT unnest(?)) AND report_date BETWEEN ?::DATE AND ?::DATE",
        [sorted(cohort),start,end])
    invalid=con.execute("""SELECT count(*) FROM history WHERE coalesce(row_id,'')='' OR coalesce(position_id,'')=''""").fetchone()[0]
    if invalid: raise ValueError("Accessible history requires final observation and position identity")
    if con.execute("SELECT count(*)-count(DISTINCT row_id) FROM history").fetchone()[0]:
        raise ValueError("Accessible history repeats observation identity")
    from pipeline.history_evidence import build_inline_evidence
    evidence=dict(documents=0,direct_fields=0)
    if source_cache is not None:
        evidence=build_inline_evidence(con,cache_dir=source_cache,output_dir=output,release_id=release)
    else:
        con.execute("CREATE OR REPLACE TEMP TABLE history_evidence(row_id VARCHAR,field VARCHAR,payload JSON)")
    from pipeline.history_evidence import add_interpretation_evidence
    add_interpretation_evidence(con,release_id=release,sector_bundle=sector_bundle,sector_audit=sector_audit,
        taxonomy=taxonomy,cost_donors=cost_donors)
    if con.execute("SELECT count(*) FROM (SELECT row_id,field FROM history_evidence GROUP BY ALL HAVING count(*)>1)").fetchone()[0]:
        raise ValueError("Ambiguous observation field evidence")
    from pipeline.history_evidence import FIELDS
    invalid_evidence=con.execute("""SELECT count(*) FROM history_evidence e LEFT JOIN history h USING(row_id)
        WHERE h.row_id IS NULL OR e.field NOT IN (SELECT unnest(?))
        OR json_extract_string(e.payload,'$.status') NOT IN ('direct','inferred','calculated','unavailable')
        OR json_extract_string(e.payload,'$.release_id') IS DISTINCT FROM ?
        OR json_extract_string(e.payload,'$.row_id') IS DISTINCT FROM e.row_id""",[list(FIELDS),release]).fetchone()[0]
    if invalid_evidence: raise ValueError("Evidence belongs to an undeclared field or another release/observation")
    con.execute("""CREATE OR REPLACE TEMP TABLE row_evidence AS SELECT row_id,to_json(map(list(field),list(payload))) AS evidence
        FROM history_evidence GROUP BY row_id""")
    groups=con.execute("SELECT cik,report_date,count(*) FROM history GROUP BY ALL ORDER BY cik,report_date").fetchall()
    indexes={c:dict(release_id=release,cik=c,quarters=[]) for c in sorted(cohort)}
    # At most cohort x quarter groups; DuckDB serializes all observation rows.
    packed="struct_pack("+",".join('"'+c+'" := h."'+c+'"' for c in schema)+",evidence := e.evidence)"
    exported=0
    for cik,date,count in groups:
        directory=output/cik;directory.mkdir(exist_ok=True)
        payload=con.execute("SELECT to_json(struct_pack(release_id := ?,cik := ?,quarter := ?,rows := list("+
            packed+" ORDER BY h.row_id))) FROM history h LEFT JOIN row_evidence e USING(row_id) WHERE cik=? AND report_date=?",[release,cik,str(date),cik,date]).fetchone()[0]
        target=directory/(str(date)+".json")
        target.write_text(payload+"\n",encoding="utf-8")
        indexes[cik]["quarters"].append(dict(quarter=str(date),rows=count,path=cik+"/"+str(date)+".json",sha256=sha(target)))
        exported+=count
    source_statuses=[]
    if cash_status_reference is not None:
        if xbrl_cache is None:
            raise ValueError('Source-status wording requires the pinned XBRL cache')
        from pipeline.public_cash_status import collect_cash_only_statuses
        source_statuses=collect_cash_only_statuses(con,reference=cash_status_reference,
            cache=xbrl_cache,cohort=cohort,start=start,end=end)
        for status in source_statuses:
            cik,quarter=status['cik'],status['quarter']
            directory=output/cik;directory.mkdir(exist_ok=True)
            target=directory/(quarter+'.json')
            payload=dict(release_id=release,cik=cik,quarter=quarter,rows=[],source_status=status)
            target.write_text(json.dumps(payload,indent=2)+'\n',encoding='utf-8')
            # Empty-quarter identity is checked explicitly; row multiset readback
            # below continues to verify every actual observation unchanged.
            if json.loads(target.read_text(encoding='utf-8'))!=payload:
                raise ValueError('Empty-quarter source-status payload changed during export')
            indexes[cik]['quarters'].append(dict(quarter=quarter,rows=0,path=cik+'/'+quarter+'.json',sha256=sha(target)))
    for cik,index in indexes.items():
        index['quarters'].sort(key=lambda item:item['quarter'])
        directory=output/cik;directory.mkdir(exist_ok=True)
        (directory/"index.json").write_text(json.dumps(index,indent=2)+"\n",encoding="utf-8")
    expected=con.execute("SELECT count(*) FROM history").fetchone()[0]
    # Read actual payloads and compare the full typed observation multiset.
    written=[str(output/cik/(str(date)+".json")) for cik,date,_ in groups]
    difference=0
    if written:
        # Sparse text fields can be inferred as JSON when sampled files contain
        # only nulls. Casting JSON strings to VARCHAR then retains JSON quotes.
        # Parse the declared field types directly before the exact comparison.
        row_type='STRUCT('+','.join('"'+c+'" '+kind for c,kind in schema.items())+')[]'
        object_size=max(Path(p).stat().st_size for p in written)+1
        con.execute("CREATE OR REPLACE TEMP TABLE history_readback AS SELECT r.*"
            " FROM read_json(?,columns={rows: "+literal(row_type)+"},maximum_object_size="+
            str(object_size)+"),unnest(rows) AS u(r)",[written])
        difference=con.execute("SELECT count(*) FROM ((SELECT * FROM history EXCEPT ALL SELECT * FROM history_readback) UNION ALL "
            "(SELECT * FROM history_readback EXCEPT ALL SELECT * FROM history))").fetchone()[0]
    if exported!=expected or difference or sha(holdings_file)!=source_hash:
        raise ValueError("Accessible history drifted during export: expected="+str(expected)+
            ", exported="+str(exported)+", typed_difference="+str(difference))
    if any(sha(p)!=value for p,value in interpretation_inputs.items()):
        raise ValueError("Interpretation inputs changed during history export")
    linked=con.execute("SELECT count(*) FROM history_evidence").fetchone()[0]
    field_population=expected*len(FIELDS)
    evidence_statuses=dict(con.execute("SELECT json_extract_string(payload,'$.status'),count(*) FROM history_evidence GROUP BY 1").fetchall())
    evidence_statuses['default_unavailable']=field_population-linked
    manifest=dict(release_id=release,holdings_sha256=source_hash,funds=sorted(cohort),start=start,end=end,
        rows=expected,exported_rows=exported,accessible_holdings_difference=difference,evidence=evidence,
        source_statuses=source_statuses,
        evidence_default=dict(status="unavailable",reason="No verified field locator in this release"),
        evidence_path_or_unavailable=sum(evidence_statuses.values())/field_population if field_population else None,
        evidence_field_population=field_population,evidence_statuses=evidence_statuses,
        interpretation_inputs=[dict(name=Path(p).name,sha256=value) for p,value in interpretation_inputs.items()])
    (output/"manifest.json").write_text(json.dumps(manifest,indent=2)+"\n",encoding="utf-8")
    return manifest
