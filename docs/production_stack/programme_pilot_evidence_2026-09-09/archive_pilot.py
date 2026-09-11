"""Archive isolated evidence; large row tables use deterministic gzip compression."""
import csv
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading

ROOT=next(p for p in Path(__file__).resolve().parents if (p/'AGENTS.md').exists())
sys.path.insert(0,str(ROOT));os.chdir(ROOT)
from scripts.programme_reference.measure_pilot import read_csv,write_csv,sha
OUT=Path(__file__).parent
DEST=ROOT/'docs/production_stack/programme_pilot_evidence_2026-09-09'
DEST.mkdir(exist_ok=True)
timer=threading.Timer(120,lambda:os._exit(124));timer.daemon=True;timer.start()
for path in sorted((OUT/'results').glob('*')):
    if not path.is_file():continue
    if path.stat().st_size>1_000_000:
        with path.open('rb') as src,(DEST/(path.name+'.gz')).open('wb') as dst:
            with gzip.GzipFile(fileobj=dst,mode='wb',mtime=0,filename='') as stream:shutil.copyfileobj(src,stream)
    else:shutil.copyfile(path,DEST/path.name)
for name in ('source_inventory.csv','source_tables.csv','source_anchors.csv','gap_xml_documents.csv','gap_xml_facts.csv',
    'review_case_sources.json','lord_full_schedule.json','semantic_diff_report.json','semantic_backstop_result.json','semantic_only.log',
    'collect_sources.py','gap_sources.py','source_profiles.py','review_cases.py','complete_lord_roster.py','summarize_pilot.py','semantic_backstop.py','archive_pilot.py','verify_delivery.py'):
    shutil.copyfile(OUT/name,DEST/name)
sources={r['path'] for r in read_csv(OUT/'gap_xml_documents.csv')}
sources.update(r['path'] for r in json.loads((OUT/'review_case_sources.json').read_text()) if r.get('sha256'))
supplement=[]
for path in sorted(sources):
    p=ROOT/path;st=p.stat()
    supplement.append({'path':path,'sha256':sha(p),'bytes':st.st_size,'mtime_ns':st.st_mtime_ns})
write_csv(DEST/'supplemental_input_manifest.csv',supplement)
prior=read_csv(ROOT/'docs/production_stack/programme_reference_evidence_2026-09-09/all_input_manifest.csv')
drift=[]
for entry in prior:
    path=ROOT/entry['path'];st=path.stat()
    if (st.st_size,st.st_mtime_ns)!=(int(entry['bytes']),int(entry['mtime_ns'])):drift.append(entry['path'])
assert not drift,drift
current=json.loads((OUT/'results/input_manifest.json').read_text())
for entry in current:
    assert sha(ROOT/entry['path'])==entry['sha256'],entry['path']
verification=json.loads((OUT/'results/verification.json').read_text())
verification.update(prior_pinned_input_stats_checked=len(prior),prior_pinned_input_drift=drift,
    current_candidate_and_evaluator_hashes_rechecked=len(current),supplemental_source_inputs_hashed=len(supplement),
    targeted_tests={'command':'python -m pytest tests/test_programme_reference.py -q','passed':8,'seconds':51.31},
    semantic_backstop={'full_manifest_scan':'stopped at 240-second bound; no result; 64537 manifest entries',
        'five_artifact_semantic_comparison':'completed; 11 holdings, 7 matches, 7 position-return, 6 index-return delta rows; fund financials unchanged',
        'assessment':'Existing baseline divergence, not a clean baseline result. Pytest protected-output guard passed; saved inputs unchanged.'})
(DEST/'verification.json').write_text(json.dumps(verification,indent=2),encoding='utf-8')
status=subprocess.run(['git','status','--short'],cwd=ROOT,capture_output=True,text=True,check=True).stdout
(DEST/'worktree_status.txt').write_text(status,encoding='utf-8')
head=subprocess.run(['git','rev-parse','HEAD'],cwd=ROOT,capture_output=True,text=True,check=True).stdout.strip()
(DEST/'run_identity.json').write_text(json.dumps({'head':head,'candidate_sha256':current[0]['sha256'],
    'scope':'Saved holdings only; no synchronized release claim','date':'2026-09-09','programme_verdict':'NOT_ASSESSABLE'},indent=2),encoding='utf-8')
timer.cancel()
print('Archived pilot; preserved '+str(len(prior))+' pinned inputs; supplemental hashes '+str(len(supplement)),flush=True)
