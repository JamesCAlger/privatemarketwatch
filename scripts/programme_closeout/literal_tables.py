"""Extract at most 1,000 literal rows for an explicit cached source-table review."""
import argparse,csv,json,os,threading
from pathlib import Path
from lxml import etree
from scripts.programme_reference.source_reader import clean,local
from scripts.programme_closeout.candidate import sha,atomic_json
ROOT=Path(__file__).resolve().parents[2]
BASE=ROOT/'docs/production_stack/programme_closeout_evidence_2026-09-09'
def main():
    p=argparse.ArgumentParser();p.add_argument('--reference',required=True);p.add_argument('--xpath',action='append',required=True);p.add_argument('--name',required=True);p.add_argument('--print-limit',type=int,default=30);a=p.parse_args()
    assert 0<=a.print_limit<=60
    
    frame=list(csv.DictReader((ROOT/'docs/production_stack/programme_reference_evidence_2026-09-09/reference_pilot.csv').open()))
    selected=next(r for r in frame if r['reference_id']==a.reference);path=ROOT/selected['html_path'];assert path.stat().st_size<120_000_000
    tree=etree.parse(str(path),etree.HTMLParser(no_network=True,recover=True,huge_tree=True));result=[];headers=[]
    for expression in a.xpath:
        for table in tree.xpath(expression):
            previous=[];node=table
            for _ in range(3):
                previous.extend(clean(n)[-500:] for n in list(node.itersiblings(preceding=True))[:6])
                node=node.getparent()
                if node is None:break
            headers.append(dict(xpath=tree.getpath(table),preceding=previous))
            for row in table.xpath('./tr|./tbody/tr'):
                result.append(dict(xpath=tree.getpath(row),cells=[clean(c) for c in row.xpath('./td|./th')],
                    facts=[dict(attributes=dict(f.attrib),text=clean(f)) for f in row.xpath('.//*[@contextref and @name]')]))
    assert len(result)<=1000
    output=BASE/'literal'/a.name
    if output.name!=a.name or output.suffix!='.json':raise ValueError('Use one JSON filename')
    atomic_json(output,dict(reference_id=a.reference,source_path=selected['html_path'],source_sha256=sha(path),tables=headers,rows=result))
    for row in result[:a.print_limit]:print(json.dumps(dict(xpath=row['xpath'],cells=row['cells']),ensure_ascii=True))
    print('Literal rows: '+str(len(result)),flush=True);
if __name__=='__main__':main()
