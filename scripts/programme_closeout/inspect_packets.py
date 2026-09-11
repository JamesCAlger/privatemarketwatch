"""Print bounded source review excerpts; never mutate reference labels."""
import argparse,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
BASE=ROOT/'docs/production_stack/programme_closeout_evidence_2026-09-09'
def main():
    p=argparse.ArgumentParser();p.add_argument('mode',choices=['currency','packets','anchors','labels','primary']);p.add_argument('--start',type=int,default=0);p.add_argument('--count',type=int,default=6);p.add_argument('--match',default='');a=p.parse_args()
    assert 0<a.count<=10
    if a.mode=='currency':
        docs=json.loads((BASE/'currency_cases/cases.json').read_text())
        for d in docs:
            if a.match and a.match not in d['accession']:continue
            print(d['path'],d['sha256'])
            for r in d.get('source_rows',[])[:20]:
                print(json.dumps(dict(xpath=r['row_xpath'],cells=r['cells'],facts=r['facts']),ensure_ascii=True))
        return
    if a.mode=='labels':
        packets=json.loads((BASE/'labels/packets.json').read_text())
        for d in packets[a.start:a.start+a.count]:
            print(d['key'])
            if a.match=='passages':
                for t in d.get('passages',[]):print(json.dumps(t,ensure_ascii=True))
                continue
            for m in d['matches']:
                if a.match and a.match not in m['xpath'] and a.match.lower() not in ' '.join(m['cells']).lower():continue
                print(json.dumps(dict(xpath=m['xpath'],row=' | '.join(m['cells'])[:1000],opening=m['opening'][:2]),ensure_ascii=True))
        return
    index=json.loads((BASE/'packets/index.json').read_text())
    for item in index[a.start:a.start+a.count]:
        d=json.loads((BASE/'packets'/f"{item['reference_id']}.json").read_text())
        if a.mode=='primary':
            source=json.loads((BASE/'primary'/f"{item['reference_id']}.json").read_text())
            print(source['ref'])
            for r in source.get('rows',[])[:18]:
                print(json.dumps(dict(xpath=r['xpath'],row=' | '.join(c for c in r['cells'] if c)[:500],
                    opening=r['opening'][:250]),ensure_ascii=True))
            continue
        if a.mode=='anchors':
            seen=set();unique=[]
            for x in item['primary_candidates']:
                if x['currency']=='USD' and x['value'] not in seen:
                    seen.add(x['value']);unique.append(dict(value=x['value'],row=x['row'][:180],xpath=x['xpath']))
            print(json.dumps(dict(ref=d['reference_id'],rows=d['source_rows'],anchors=unique,status=d['source_status']),ensure_ascii=True))
            continue
        print(json.dumps(item,ensure_ascii=True))
        for t in d['tables']:
            print(json.dumps(dict(table=t.get('table_xpath'),n=t['rows'],opening=' | '.join(t.get('opening_rows',[]))[:160],
                 preceding=' | '.join(t.get('preceding',[])[:4])[:210],first=' | '.join(t['first'][:1])[:100],last=' | '.join(t['last'][-1:])[:180]),ensure_ascii=True))
if __name__=='__main__':main()
