"""Read frozen pilot original filings only; bounded, checkpointed source pass."""
import csv,hashlib,json,os,sys,threading,time
from pathlib import Path
ROOT=next(p for p in Path(__file__).resolve().parents if (p/'AGENTS.md').exists());os.chdir(ROOT);sys.path.insert(0,str(ROOT))
from scripts.programme_reference.source_reader import read_document
OUT=Path(__file__).parent;REF=ROOT/'docs/production_stack/programme_reference_evidence_2026-09-09'
t=threading.Timer(240,lambda:os._exit(124));t.daemon=True;t.start()
with (REF/'reference_pilot.csv').open(newline='',encoding='utf-8') as f:pilot=list(csv.DictReader(f))
assert len(pilot)==61
(OUT/'sources').mkdir(exist_ok=True)
results=[]
reader_sha=hashlib.sha256((ROOT/'scripts/programme_reference/source_reader.py').read_bytes()).hexdigest()
for i,p in enumerate(pilot):
    dest=OUT/'sources'/(p['reference_id']+'.json');start=time.monotonic()
    path=Path(p['html_path']) if p['html_path'] else None
    cached=json.loads(dest.read_text()) if dest.exists() else None
    if cached and cached.get('reader_sha256')==reader_sha:
        result=cached;st=Path(result['path']).stat() if result.get('path') else None
        assert st is None or (st.st_size,st.st_mtime_ns)==(result['bytes'],result['mtime_ns'])
    elif path is None or not path.is_file():
        result={'reference_id':p['reference_id'],'status':'no_primary_html_candidate','path':'','reader_sha256':reader_sha}
        dest.write_text(json.dumps(result,indent=2),encoding='utf-8')
    else:
        result={**read_document(path,p['report_date']),'reference_id':p['reference_id'],'accession':p['accession'],'cik':p['cik'],'reader_sha256':reader_sha}
        dest.write_text(json.dumps(result,ensure_ascii=True,indent=2),encoding='utf-8')
    results.append({'reference_id':p['reference_id'],'cik':p['cik'],'report_date':p['report_date'],'source_rows':len(result.get('source_candidates',[])),
      'anchor_candidates':len(result.get('anchor_candidates',[])),'status':result['status']})
    print(str(i+1)+'/61 '+p['reference_id']+' rows '+str(results[-1]['source_rows'])+' seconds '+str(round(time.monotonic()-start,1)),flush=True)
with (OUT/'source_inventory.csv').open('w',newline='',encoding='utf-8') as f:
    w=csv.DictWriter(f,fieldnames=list(results[0]));w.writeheader();w.writerows(results)
t.cancel()
