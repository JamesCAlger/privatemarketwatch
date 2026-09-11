"""Read metadata/coverage of existing gold; never edit labels or rescore them."""
import csv,hashlib,json,os,threading
from collections import Counter,defaultdict
from pathlib import Path
ROOT=next(p for p in Path(__file__).resolve().parents if (p/'AGENTS.md').exists());os.chdir(ROOT);OUT=Path(__file__).parent
t=threading.Timer(60,lambda:os._exit(124));t.daemon=True;t.start()
cohort={x['cik'] for x in json.loads(Path('data/overrides/wrapper_cohorts/v2_70_gate_verified_wrapper_manifest.json').read_text())['entries']}
manifest=[];out={}
def pin(p):
    p=Path(p);st=p.stat();manifest.append({'path':p.as_posix(),'bytes':st.st_size,'mtime_ns':st.st_mtime_ns,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()})
def readcsv(p):
    pin(p)
    with Path(p).open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))
def validq(q):return '2023-03-31'<=str(q)<='2026-03-31'
p=Path('data/gold/labels/position_labels.jsonl');pin(p)
labels=[json.loads(s) for s in p.read_text().splitlines() if s.strip()]
latest={x['_key']:x for x in labels};v=list(latest.values())
refs=[]
for x in v:
    source=(x.get('source_ref') or {}).get('doc','');path=Path(source)
    refs.append({'key':x['_key'],'cik':x.get('cik'),'report_date':x.get('report_date'),
       'accession':x.get('accession'),'label_status':x.get('label_status'),
       'adjudicator':x.get('adjudicator'),'stratum':x.get('stratum'),
       'source_path':source,'source_exists':path.exists(),
       'has_context':bool((x.get('source_ref') or {}).get('context_id')),
       'in_programme':str(x.get('cik')).zfill(10) in cohort and validq(x.get('report_date')),
       'reuse':'source-label reuse candidate; check provenance/exposure and new semantic compatibility before acceptance'})
out['position_labels']={'records':len(labels),'unique_keys':len(v),'funds':len({x.get('cik') for x in v}),
 'label_status':dict(Counter(x.get('label_status') for x in v)),'strata':dict(Counter(x.get('stratum') for x in v)),
 'in_programme':sum(x['in_programme'] for x in refs),'source_files_present':sum(x['source_exists'] for x in refs),'context_locators':sum(x['has_context'] for x in refs)}
framep=Path('data/gold/samples/sample_frame_batch1.jsonl');pin(framep)
frame=[json.loads(s) for s in framep.read_text().splitlines() if s.strip()]
out['position_frame']={'records':len(frame),'units':dict(Counter(x.get('unit_type') for x in frame)),'strata':dict(Counter(x.get('stratum') for x in frame))}
out['match_batches']=[];packetrefs=[]
for batch in ['mg1','mg3','mg4_contested','mg5_recall']:
    base=Path('data/output/match_quality/gold')/batch
    work=readcsv(base/'worklist.csv');gold=readcsv(base/'gold_set.csv')
    strata=Counter();citation_packets=0;blank_evidence=0;packetperiods=set();missing_packets=0
    for w in work:
        pid=w['packet_id'];p=base/'packets'/(pid+'.json');vpath=base/'verdicts'/(pid+'.json')
        if not p.exists() or not vpath.exists():missing_packets+=1;continue
        pin(p);pin(vpath);packet=json.loads(p.read_text(encoding='utf-8-sig'));verdict=json.loads(vpath.read_text(encoding='utf-8-sig'))
        rows=packet.get('rows',[])+packet.get('candidate_rows',[])
        quarters=sorted({r.get('report_date') for r in rows if r.get('report_date')})
        packetperiods.update(quarters)
        evidence=verdict.get('evidence',[])+[e for edge in verdict.get('edge_verdicts',[])+verdict.get('proposed_links',[]) for e in edge.get('evidence',[])]
        citation_packets+=bool(evidence);blank_evidence+=not bool(evidence)
        strata[(w['packet_type'],w['stratum'])]+=1
        packetrefs.append({'batch':batch,'packet_id':pid,'packet_type':w['packet_type'],'stratum':w['stratum'],
             'cik':w['cik'],'quarters':';'.join(quarters),'has_evidence_entries':bool(evidence),
             'has_required_period':any(validq(d) for d in quarters),
             'reuse':'regression/development; prior evaluation exposure; no new held-out claim'})
    auditpath=base/'audit_slice.csv';audit=readcsv(auditpath) if auditpath.exists() else []
    out['match_batches'].append({'batch':batch,'packets':len(work),'gold_records':len(gold),
      'units':dict(Counter(x['unit'] for x in gold)),
      'strata':{k[0]+'/'+k[1]:v for k,v in strata.items()},'missing_packet_or_verdict':missing_packets,
      'packets_with_evidence_entries':citation_packets,'packets_without_evidence_entries':blank_evidence,
      'periods':sorted(packetperiods),'owner_audit_rows':len(audit),
      'owner_verdicts_recorded':sum(bool(x.get('owner_verdict')) for x in audit)})
old=readcsv('data/output/shadow/trial_2026-06-18/gold/gold_labels.csv')
out['shadow_flag_gold']={'rows':len(old),'labeled':sum(bool(x.get('true_verdict')) for x in old),'funds':len({x['cik'] for x in old}),'scope':'flag-selected judgments; not full source roster'}
for name,rows in [('existing_position_reference_index.csv',refs),('existing_match_reference_index.csv',packetrefs),('benchmark_input_manifest.csv',manifest)]:
    with (OUT/name).open('w',encoding='utf-8',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
changes=[x['path'] for x in manifest if (Path(x['path']).stat().st_size,Path(x['path']).stat().st_mtime_ns)!=(x['bytes'],x['mtime_ns'])]
assert not changes,changes
out['input_changes']=changes
(OUT/'benchmark_inventory.json').write_text(json.dumps(out,indent=2),encoding='utf-8');t.cancel();print(json.dumps(out,indent=2),flush=True)
