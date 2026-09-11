"""Freeze every physical row of a small source schedule, including untagged zeros."""
import json
import os
from pathlib import Path
import sys
import threading
from lxml import etree
ROOT=next(p for p in Path(__file__).resolve().parents if (p/'AGENTS.md').exists())
sys.path.insert(0,str(ROOT));os.chdir(ROOT)
from scripts.programme_reference.source_reader import clean
OUT=Path(__file__).parent
timer=threading.Timer(45,lambda:os._exit(124));timer.daemon=True;timer.start()
doc=json.loads((OUT/'sources/REF-0002008748-2024-09-30.json').read_text())
tree=etree.parse(doc['path'],etree.HTMLParser(no_network=True,recover=True))
rows=[]
for ti in (13,14):
    table=tree.xpath('/html/body/table')[ti-1]
    for row in table.xpath('./tr'):
        rows.append({'xpath':tree.getpath(row),'cells':[clean(c) for c in row.xpath('./td|./th')],
           'facts':[{'attributes':dict(f.attrib),'text':clean(f)} for f in row.xpath('.//*[@contextref and @name]')]})
(OUT/'lord_full_schedule.json').write_text(json.dumps({'path':doc['path'],'sha256':doc['sha256'],'rows':rows},indent=2),encoding='utf-8')
for row in rows:print((row['xpath']+' '+' | '.join(c for c in row['cells'] if c)).encode('ascii','backslashreplace').decode(),flush=True)
timer.cancel()
