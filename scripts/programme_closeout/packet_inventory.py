"""Bounded review index from retained literal source packets, never gold labels."""
import csv,json,hashlib,time,threading,os
from pathlib import Path
from collections import Counter
from scripts.programme_closeout.candidate import atomic_json

ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'docs/production_stack/programme_closeout_evidence_2026-09-09/packets'

def main():
    timer=threading.Timer(300,lambda:os._exit(124));timer.daemon=True;timer.start()
    OUT.mkdir(parents=True,exist_ok=True)
    frame=list(csv.DictReader((ROOT/'docs/production_stack/programme_reference_evidence_2026-09-09/reference_pilot.csv').open()))
    assert len(frame)==61
    packets=[]
    for row in frame:
        ref=row['reference_id'];p=ROOT/'scratch/2026-09-09_measurement_pilot/sources'/f'{ref}.json'
        source=json.loads(p.read_text()) if p.exists() else {}
        candidates=source.get('source_candidates',[])
        groups={}
        for r in candidates:
            table=groups.setdefault(r['table_xpath'],dict(rows=0,contexts=set(),first=[],last=[]))
            table['rows']+=1;table['contexts'].add(r['context_id'])
            text=' | '.join(c for c in r['cells'] if c)
            if len(table['first'])<2:table['first'].append(text[:700])
            table['last']=(table['last']+[text[:700]])[-2:]
        for tab in source.get('tables',[]):
            if tab['table_xpath'] in groups:groups[tab['table_xpath']].update(tab)
        for tab in groups.values():tab['contexts']=len(tab['contexts'])
        packet=dict(reference_id=ref,cik=row['cik'],report_date=row['report_date'],component=row['reason'],
                    path=row['html_path'],source_sha256=source.get('sha256'),source_status=source.get('status','missing_saved_packet'),
                    source_rows=len(candidates),tables=list(groups.values()),anchors=source.get('anchor_candidates',[]))
        atomic_json(OUT/f'{ref}.json',packet)
        packets.append(dict(reference_id=ref,source_rows=len(candidates),tables=len(groups),
                            primary_candidates=[dict(value=a['value'],currency=a['currency'],concept=a['concept'],
                            row=' | '.join(c for c in a['cells'] if c)[:250],xpath=a['row_xpath'])
                            for a in packet['anchors']],source_status=packet['source_status']))
    atomic_json(OUT/'index.json',packets)
    print(json.dumps(dict(packets=len(packets),rows=sum(x['source_rows'] for x in packets)),indent=2),flush=True)
    timer.cancel()

if __name__=='__main__':main()
