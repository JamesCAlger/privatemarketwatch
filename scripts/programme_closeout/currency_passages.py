"""Read short source passages needed to adjudicate rare currency-tag conflicts."""
import json
from pathlib import Path
import re
from lxml import etree
from scripts.programme_closeout.candidate import sha,atomic_json
ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'docs/production_stack/programme_closeout_evidence_2026-09-09/currency_cases'


def main():
    docs=json.loads((OUT/'cases.json').read_text())
    results=[]
    for doc in docs:
        if not any(c['resolved_currency'] in ('AFN','KPW','RSD','EGP','CNY','NOK') for c in doc['cases']):
            continue
        path=ROOT/doc['path']
        if not path.is_file():continue
        tree=etree.parse(str(path),etree.HTMLParser(no_network=True,recover=True,huge_tree=True))
        body=re.sub(r'\s+',' ',' '.join(tree.getroot().itertext()))
        hits=[]
        for pattern in ('South Korean','Korean Won','Swedish','Swiss Franc','denominated in','U.S. dollars','U.S. Dollars','Norwegian','Chinese'):
            matches=list(re.finditer(re.escape(pattern),body,re.I))
            for m in matches[:8]:
                hits.append(dict(pattern=pattern,text=body[max(0,m.start()-120):m.end()+240]))
        results.append(dict(path=doc['path'],sha256=sha(path),passages=hits))
        print(path.name+' passages '+str(len(hits)),flush=True)
    atomic_json(OUT/'passages.json',results)


if __name__=='__main__':main()
