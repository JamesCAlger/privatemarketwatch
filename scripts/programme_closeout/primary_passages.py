"""Literal primary-total and schedule-boundary review, including untagged rows."""
import csv,json,os,re,threading,time
from pathlib import Path
from lxml import etree
from scripts.programme_closeout.candidate import sha,atomic_json
from scripts.programme_reference.source_reader import clean,local
ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'docs/production_stack/programme_closeout_evidence_2026-09-09/primary'
def main():
    OUT.mkdir(parents=True,exist_ok=True)
    
    frame=list(csv.DictReader((ROOT/'docs/production_stack/programme_reference_evidence_2026-09-09/reference_pilot.csv').open()))
    assert len(frame)==61
    for i,p in enumerate(frame):
        dest=OUT/(p['reference_id']+'.json')
        source=ROOT/p['html_path'] if p['html_path'] else None
        if source is None or not source.is_file():
            atomic_json(dest,dict(ref=p['reference_id'],status='primary_HTML_unavailable',path=p['html_path']));continue
        digest=sha(source)
        if dest.exists() and json.loads(dest.read_text()).get('sha256')==digest:continue
        tree=etree.parse(str(source),etree.HTMLParser(no_network=True,recover=True,huge_tree=True))
        matches=[];boundaries=[]
        for table in tree.xpath('//table'):
            rows=table.xpath('./tr|./tbody/tr')
            if not rows:continue
            opening=' | '.join(clean(r) for r in rows[:5])
            texts=[clean(r) for r in rows]
            selected=[(r,t) for r,t in zip(rows,texts) if re.search(r'(?i)^(total (?:portfolio )?investments?|total investment portfolio|investments?[, ]+(?:at fair value|[-:]? ?non)|non.controlled.{0,35}investments?.*cost)',t)]
            if not selected:continue
            preceding=[];node=table
            for _ in range(3):
                preceding.extend(clean(s)[-450:] for s in list(node.itersiblings(preceding=True))[:5])
                node=node.getparent()
                if node is None:break
            for row,txt in selected:
                matches.append(dict(xpath=tree.getpath(row),cells=[clean(c) for c in row.xpath('./td|./th')],
                    opening=opening[:1600],preceding=preceding[:15],
                    facts=[dict(concept=f.get('name'),context=f.get('contextref'),unit=f.get('unitref'),scale=f.get('scale'),text=clean(f)) for f in row.xpath('.//*[@contextref and @name]')]))
            if len(matches)>300:raise ValueError('Primary candidate cap')
        atomic_json(dest,dict(ref=p['reference_id'],path=p['html_path'],sha256=digest,status='literal_primary_review_candidates',rows=matches))
        print(f'Primary source packet {i+1}/61: {len(matches)} candidate rows',flush=True)
    
if __name__=='__main__':main()
