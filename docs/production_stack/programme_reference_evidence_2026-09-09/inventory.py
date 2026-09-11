"""Bounded cache-only source/reference inventory; outputs beside this script.

No pipeline imports, production writes, downloads, gold-label edits or scoring.
Source snippets are review candidates, never automatic lifecycle decisions.
"""
import csv, hashlib, json, os, re, subprocess, threading
from pathlib import Path
from datetime import datetime, timezone
import duckdb
from lxml import etree

ROOT=next(p for p in Path(__file__).resolve().parents if (p/'AGENTS.md').exists()); os.chdir(ROOT)
OUT=Path(__file__).parent
timer=threading.Timer(180,lambda:os._exit(124));timer.daemon=True;timer.start()
db=duckdb.connect();db.execute("SET threads=2");db.execute("SET memory_limit='768MB'");db.execute("SET temp_directory=''")
manifest=[]; queries=[]
def pin(p):
    p=Path(p);st=p.stat()
    with p.open('rb') as f:
        h=hashlib.file_digest(f,'sha256').hexdigest()
    manifest.append({'path':p.as_posix(),'bytes':st.st_size,'mtime_ns':st.st_mtime_ns,'sha256':h})
    return h
def q(sql,args=None,cap=10000):
    queries.append(sql)
    c=db.execute(sql,args or []);rows=c.fetchmany(cap+1)
    if len(rows)>cap:raise RuntimeError('result cap')
    cols=[d[0] for d in c.description]
    return [dict(zip(cols,r)) for r in rows]
def write(name,rows):
    if not rows:return
    with (OUT/name).open('w',encoding='utf-8',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)

for p in ['data/output/bdc_filings_index.csv','data/output/combined_universe.csv',
          'docs/production_stack/programme_contract_evidence_2026-09-09/obligation_frame.csv',
          'data/overrides/wrapper_cohorts/v2_70_gate_verified_wrapper_manifest.json']:
    pin(p)
db.execute("CREATE TABLE o AS SELECT * FROM read_csv('docs/production_stack/programme_contract_evidence_2026-09-09/obligation_frame.csv',all_varchar=true)")
db.execute("CREATE TABLE f AS SELECT * FROM read_csv('data/output/bdc_filings_index.csv',all_varchar=true) WHERE cik IN (SELECT cik FROM o)")
db.execute("CREATE TABLE u AS SELECT * FROM read_csv('data/output/combined_universe.csv',all_varchar=true) WHERE cik IN (SELECT cik FROM o)")
funds=q("SELECT cik,max(entity_name) entity_name,min(election_date) election_date,max(withdrawal_date) withdrawal_date FROM u GROUP BY 1 ORDER BY 1")
assert len(funds)==70
docs=q("""SELECT cik,accession_number,report_date,filing_date,form_type,xbrl_local_path
 FROM f WHERE report_date<='2026-03-31' AND form_type IN ('10-K','10-Q','10-K/A','10-Q/A')
 QUALIFY row_number() OVER(PARTITION BY cik ORDER BY report_date DESC,filing_date DESC,accession_number DESC)=1 ORDER BY cik""")
write('latest_document_candidates.csv',docs)
db.execute('CREATE TABLE cf (cik VARCHAR,concept VARCHAR,currency VARCHAR,report_date VARCHAR,accession VARCHAR,form VARCHAR,filed VARCHAR,amount DOUBLE,source_path VARCHAR)')
concepts=[]
pattern=re.compile(r'InvestmentOwnedAtFairValue|InvestmentsAtFairValue|InvestmentsFairValue|InvestmentCompanyInvestmentsFairValue|InvestmentsAndOtherFinancialInstruments|^Assets$|InvestmentIncomeInterest|InvestmentCompanyInvestmentIncome|InvestmentCompanyNetInvestmentIncome|^NetAssets$')
print('Reading companyfacts for 70 funds',flush=True)
for n,fund in enumerate(funds):
    cik=fund['cik'];p=Path('data/raw/companyfacts_cache')/(cik+'.json')
    if not p.exists():continue
    if p.stat().st_size>30_000_000:raise RuntimeError('companyfacts file cap')
    pin(p);x=json.loads(p.read_text(encoding='utf-8-sig'))
    for namespace,tags in x.get('facts',{}).items():
        for tag,meta in tags.items():
            if not pattern.search(tag):continue
            for unit,events in meta.get('units',{}).items():
                concepts.append({'cik':cik,'namespace':namespace,'concept':tag,'unit':unit,'observations':len(events)})
                db.execute("""INSERT INTO cf SELECT ?,?,?,j.value->>'end',j.value->>'accn',
                  j.value->>'form',j.value->>'filed',try_cast(j.value->>'val' AS DOUBLE),?
                  FROM json_each(?) j WHERE (j.value->>'end') IN (SELECT DISTINCT report_date FROM o)
                  AND (j.value->>'form') IN ('10-K','10-Q','10-K/A','10-Q/A')""",
                  [cik,namespace+':'+tag,unit,p.as_posix(),json.dumps(events)])
    if (n+1)%10==0:print('Companyfacts funds: '+str(n+1),flush=True)
write('companyfacts_concepts.csv',concepts)
cf=q("""SELECT * FROM cf QUALIFY row_number() OVER(PARTITION BY cik,concept,currency,report_date ORDER BY filed DESC,accession DESC)=1 ORDER BY cik,report_date,concept,currency""")
write('companyfacts_evidence.csv',cf)
positive=q("""SELECT * FROM cf WHERE amount>0 AND lower(concept) LIKE '%investment%'
 AND lower(concept) NOT LIKE '%income%' QUALIFY row_number() OVER(PARTITION BY cik,report_date ORDER BY filed DESC,concept,accession DESC)=1 ORDER BY cik,report_date""")
write('positive_investment_evidence.csv',positive)

print('Reading one latest cached HTML per fund for lifecycle candidates',flush=True)
snippets=[];source_docs=[]
pat=re.compile(r'commenced (?:our |its |investment |substantial |substantive |commercial |business )?operations|commencement of (?:investment )?operations|began (?:our |its |investment )?operations|commenced (?:our |its )?investment activities|formed (?:as|on|in)|organized (?:as|on|in)|completed (?:the |a )?merger|ceased operations|has not commenced|had not commenced',re.I)
textdir=OUT/'source_text';textdir.mkdir(exist_ok=True)
for i,d in enumerate(docs):
    cik=d['cik'];acc=d['accession_number'];p=Path('data/raw/filings/bdc_html')/str(int(cik))/(acc.replace('-','')+'.html')
    if not p.exists():
        source_docs.append({**d,'html_path':p.as_posix(),'available':False,'sha256':'','text_sha256':'','text_chars':0});continue
    if p.stat().st_size>35_000_000:
        source_docs.append({**d,'html_path':p.as_posix(),'available':'over_size_cap','sha256':'','text_sha256':'','text_chars':0});continue
    sha=pin(p)
    tree=etree.parse(str(p),etree.HTMLParser(no_network=True,recover=True))
    # Exclude scripts/styles; hidden iXBRL facts remain in source text but are not lifecycle labels.
    for el in tree.xpath('//script|//style'):el.getparent().remove(el)
    body=' '.join(' '.join(tree.getroot().itertext()).split())
    textsha=hashlib.sha256(body.encode()).hexdigest()
    (textdir/(cik+'.txt')).write_text(body,encoding='utf-8')
    source_docs.append({**d,'html_path':p.as_posix(),'available':True,'sha256':sha,'text_sha256':textsha,'text_chars':len(body)})
    seen=set()
    for match in pat.finditer(body):
        start=max(0,match.start()-230);end=min(len(body),match.end()+470)
        excerpt=body[start:end]
        if excerpt in seen:continue
        seen.add(excerpt)
        snippets.append({'cik':cik,'accession':acc,'path':p.as_posix(),'document_sha256':sha,
                         'text_sha256':textsha,'start':start,'end':end,'excerpt':excerpt})
        if len(seen)>=35:break
    del body,tree
    if (i+1)%10==0:print('HTML funds: '+str(i+1),flush=True)
write('fund_source_documents.csv',source_docs)
(OUT/'lifecycle_candidates.json').write_text(json.dumps(snippets,indent=2,ensure_ascii=True),encoding='utf-8')
write('fund_metadata.csv',funds)
write('input_manifest.csv',manifest)
changed=[m['path'] for m in manifest if (Path(m['path']).stat().st_size,Path(m['path']).stat().st_mtime_ns)!=(m['bytes'],m['mtime_ns'])]
if changed:raise RuntimeError('Inputs changed: '+str(changed))
summary={'timestamp_utc':datetime.now(timezone.utc).isoformat(),'git_head':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),
         'funds':len(funds),'latest_documents':len(docs),'html_available':sum(d['available'] is True for d in source_docs),
         'companyfacts_field_quarters':len(cf),'positive_investment_quarters':len(positive),'lifecycle_candidates':len(snippets),'input_count':len(manifest),'input_changes':changed}
(OUT/'summary.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
db.close();timer.cancel();print(json.dumps(summary,indent=2),flush=True)
