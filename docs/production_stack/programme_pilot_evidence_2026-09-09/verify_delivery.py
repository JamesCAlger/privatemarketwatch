"""Bounded final integrity and documentation checks for the pilot delivery."""
import ast
import csv
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sys
import threading
import duckdb

ROOT=next(p for p in Path(__file__).resolve().parents if (p/'AGENTS.md').exists())
os.chdir(ROOT);sys.path.insert(0,str(ROOT))
from scripts.programme_reference.measure_pilot import read_csv,sha
DEST=ROOT/'docs/production_stack/programme_pilot_evidence_2026-09-09'
timer=threading.Timer(90,lambda:os._exit(124));timer.daemon=True;timer.start()
docs=[ROOT/'docs/production_stack'/name for name in ('programme_measurement_pilot_2026-09-09.md',
    'programme_measurement_register.md','programme_reference_and_eligibility.md','programme_target_contract.md','consolidation_readiness_plan.md')]+[DEST/'README.md']
broken=[]
for doc in docs:
    for target in re.findall(r'\]\(([^)]+)\)',doc.read_text(encoding='utf-8')):
        if target.startswith(('https://','http://','#')):continue
        path=target.split('#')[0]
        if path and not (doc.parent/path).exists():broken.append((doc.name,target))
assert not broken,broken
code=list((ROOT/'scripts/programme_reference').glob('*.py'))+list(DEST.glob('*.py'))+[ROOT/'tests/test_programme_reference.py']
for path in code:ast.parse(path.read_text(encoding='utf-8'),filename=str(path))
previous=read_csv(ROOT/'docs/production_stack/programme_reference_evidence_2026-09-09/all_input_manifest.csv')
for entry in previous:
    path=ROOT/entry['path'];st=path.stat()
    assert (st.st_size,st.st_mtime_ns)==(int(entry['bytes']),int(entry['mtime_ns'])),entry['path']
for entry in json.loads((DEST/'input_manifest.json').read_text()):assert sha(ROOT/entry['path'])==entry['sha256'],entry['path']
db=duckdb.connect(config={'memory_limit':'1GB','threads':2})
counts={}
for name in ('source_rows.csv.gz','source_facts.csv.gz','tag_copy_fields.csv.gz'):
    counts[name]=db.execute('SELECT count(*) FROM read_csv(?,all_varchar=true)',[str(DEST/name)]).fetchone()[0]
assert counts['source_rows.csv.gz']==15128
assert counts['tag_copy_fields.csv.gz']==47230
packets=read_csv(DEST/'pilot_status.csv')
assert len(packets)==61 and len({r['reference_id'] for r in packets})==61
assert sum(r['roster_status'].startswith('reviewed_development') for r in packets)==2
obligations=read_csv(DEST/'obligations_v2.csv')
assert len(obligations)==910 and len({(r['cik'],r['report_date']) for r in obligations})==910
assert sum(r['eligibility_status'].startswith('eligible') for r in obligations)==812
assert len({r['report_date'] for r in obligations})==13
for target,expected in ((.995,598),(.99,299),(.95,59)):
    assert math.ceil(math.log(.05)/math.log(target))==expected
db.close()
verification=json.loads((DEST/'verification.json').read_text())
verification.update(delivery_document_links_checked=len(docs),delivery_python_syntax_files=len(code),
    compressed_table_row_counts=counts,all_61_packet_ids_unique=True,all_910_obligation_keys_unique=True,
    final_prior_pinned_input_stats_unchanged=True,final_candidate_evaluator_hashes_unchanged=True)
(DEST/'verification.json').write_text(json.dumps(verification,indent=2),encoding='utf-8')
files=[{'path':p.name,'bytes':p.stat().st_size,'sha256':sha(p)} for p in sorted(DEST.iterdir()) if p.is_file() and p.name!='artifact_manifest.json']
(DEST/'artifact_manifest.json').write_text(json.dumps({'date':'2026-09-09','artifacts':files},indent=2),encoding='utf-8')
timer.cancel()
print(json.dumps({'links':'valid','python_syntax_files':len(code),'artifacts':len(files),
    'compressed_rows':counts,'prior_inputs_unchanged':len(previous),'artifact_bytes':sum(r['bytes'] for r in files)}),flush=True)
