"""Freeze source document candidates and a deterministic calibration pilot.

Does not label a complete schedule or claim candidate documents support every fact.
No missing-source replacement, production writes, downloads or gold changes.
"""
import csv,hashlib,json,os,threading
from pathlib import Path
from collections import Counter
import duckdb
ROOT=next(p for p in Path(__file__).resolve().parents if (p/'AGENTS.md').exists());os.chdir(ROOT);OUT=Path(__file__).parent
t=threading.Timer(90,lambda:os._exit(124));t.daemon=True;t.start()
def read(p):
    with Path(p).open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))
def write(p,rows):
    with (OUT/p).open('w',newline='',encoding='utf-8') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
db=duckdb.connect();db.execute("SET threads=2");db.execute("SET memory_limit='512MB'");db.execute("SET temp_directory=''")
c=db.execute("SELECT cik,report_date,accession_number,filing_date,form_type,xbrl_local_path FROM read_csv('data/output/bdc_filings_index.csv',all_varchar=true) WHERE report_date BETWEEN '2023-03-31' AND '2026-03-31' AND form_type IN ('10-K','10-Q','10-K/A','10-Q/A') ORDER BY cik,report_date,filing_date DESC,accession_number DESC")
filings=[dict(zip([d[0] for d in c.description],r)) for r in c.fetchmany(6000)];assert len(filings)<6000
primary={};accs={}
for f in filings:
    primary.setdefault((f['cik'],f['report_date']),f);accs[(f['cik'],f['accession_number'])]=f
ob=read(OUT/'obligations.csv');rows=[]
for o in ob:
    key=(o['cik'],o['report_date']);f=primary.get(key);basis='indexed_primary_period_candidate'
    if not f and o['positive_source_accession']:
        f=accs.get((o['cik'],o['positive_source_accession']),{'accession_number':o['positive_source_accession'],'xbrl_local_path':'','report_date':'','filing_date':'','form_type':''})
        basis='companyfacts_accession_candidate_context_needs_review'
    if not f:f={};basis='no_candidate_in_bounded_inventory'
    a=f.get('accession_number','');h=Path('data/raw/filings/bdc_html')/str(int(o['cik']))/(a.replace('-','')+'.html') if a else None
    x=Path(f['xbrl_local_path']) if f.get('xbrl_local_path') else None
    hexists=bool(h and h.is_file());xexists=bool(x and x.is_file())
    rows.append({'cik':o['cik'],'report_date':o['report_date'],'eligibility_status':o['eligibility_status'],
      'candidate_basis':basis,'accession':a,'document_report_date':f.get('report_date',''),
      'filing_date':f.get('filing_date',''),'form':f.get('form_type',''),
      'html_path':h.as_posix() if h else '', 'html_exists':hexists,'html_bytes':h.stat().st_size if hexists else '',
      'xml_path':x.as_posix() if x else '', 'xml_exists':xexists,'xml_bytes':x.stat().st_size if xexists else '',
      'target_period_roster_verified':False,'selection_status':'candidate_only; context/units/consolidation and amendment precedence not adjudicated'})
write('source_document_frame.csv',rows)
docmap={(r['cik'],r['report_date']):r for r in rows}
seed='programme-reference-calibration-v1-2026-09-09';selected={}
for q in sorted({r['report_date'] for r in ob}):
    population=[r for r in ob if r['report_date']==q and r['eligibility_status'].startswith('eligible')]
    rank=sorted(population,key=lambda r:hashlib.sha256((seed+'|'+r['cik']+'|'+q).encode()).hexdigest())
    for o in rank[:2]:
        selected[(o['cik'],q)]={'reason':'quarter_probability_pilot','stratum_n':len(population),'sample_n':2,'selection_probability':2/len(population)}
for o in ob:
    if o['eligibility_status'].startswith('eligible') and int(o['holdings_rows'])==0:
        selected.setdefault((o['cik'],o['report_date']),{'reason':'missing_output_census','stratum_n':32,'sample_n':32,'selection_probability':1})
        if selected[(o['cik'],o['report_date'])]['reason']=='quarter_probability_pilot':selected[(o['cik'],o['report_date'])]['reason']+=';also_missing_output_census'
    if o['eligibility_status'].startswith('unresolved'):
        selected[(o['cik'],o['report_date'])]={'reason':'eligibility_unresolved','stratum_n':1,'sample_n':1,'selection_probability':1}
for q in ['2023-03-31','2023-06-30','2023-09-30']:
    selected.setdefault(('0001899017',q),{'reason':'lifecycle_source_counterexample','stratum_n':'','sample_n':'','selection_probability':''})
packets=[];hashes=[];seen=set()
for (cik,q),s in sorted(selected.items()):
    d=docmap[(cik,q)];ref='REF-'+cik+'-'+q
    for field in ['html_path','xml_path']:
        p=Path(d[field]) if d[field] else None
        if not p or not p.is_file() or p.as_posix() in seen:continue
        st=p.stat()
        with p.open('rb') as f:sha=hashlib.file_digest(f,'sha256').hexdigest()
        assert (st.st_size,st.st_mtime_ns)==(p.stat().st_size,p.stat().st_mtime_ns)
        hashes.append({'path':p.as_posix(),'bytes':st.st_size,'mtime_ns':st.st_mtime_ns,'sha256':sha});seen.add(p.as_posix())
    packets.append({'reference_id':ref,**d,**s,'split':'calibration_development; no held-out claim',
      'label_status':'unlabeled','review_action':'Enumerate complete source lots, totals, exclusions, units and independent primary anchor; preserve unassessable status.',
      'allowed_use':'pilot calibration and regression; final acceptance requires separately governed review/split',
      'seed':seed})
write('reference_pilot.csv',packets);write('pilot_input_manifest.csv',hashes)
summary={'obligations':len(rows),'html_candidates':sum(r['html_exists'] for r in rows),'xml_candidates':sum(r['xml_exists'] for r in rows),
 'eligible_no_cached_candidate':sum(r['eligibility_status'].startswith('eligible') and not(r['html_exists'] or r['xml_exists']) for r in rows),
 'pilot_clusters':len(packets),'pilot_probability_clusters':sum('quarter_probability' in p['reason'] for p in packets),
 'pilot_reasons':dict(Counter(p['reason'] for p in packets)),
 'pilot_no_cached_candidate':sum(not(p['html_exists'] or p['xml_exists']) for p in packets),'pinned_source_files':len(hashes),
 'sampling_caveat':'Two source clusters per quarter are a pilot, not enough to certify 99%+ accuracy. Do not pool targeted census/counterexamples with probability estimates. Full schedule rosters and final hold-out split remain to be reviewed.'}
(OUT/'reference_summary.json').write_text(json.dumps(summary,indent=2),encoding='utf-8');db.close();t.cancel();print(json.dumps(summary,indent=2))
