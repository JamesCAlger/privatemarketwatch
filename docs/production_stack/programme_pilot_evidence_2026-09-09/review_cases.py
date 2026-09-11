"""Bounded raw-source case review, with original rows retained for adjudication."""
import csv
import hashlib
import json
import os
from pathlib import Path
import sys
import threading
from lxml import etree

ROOT=next(p for p in Path(__file__).resolve().parents if (p/'AGENTS.md').exists())
sys.path.insert(0,str(ROOT));os.chdir(ROOT)
from scripts.programme_reference.source_reader import clean, local
OUT=Path(__file__).parent
timer=threading.Timer(120,lambda:os._exit(124));timer.daemon=True;timer.start()
with (OUT/'results/tag_copy_fields.csv').open(newline='',encoding='utf-8') as f:
    selected=[r for r in csv.DictReader(f) if r['comparison_status']=='value_mismatch']
cases=[]
for rid,context in [(r['reference_id'],r['context_id']) for r in selected]:
    d=json.loads((OUT/'sources'/(rid+'.json')).read_text())
    cases.append({'case':'tag_copy_discrepancy','reference_id':rid,'context_id':context,'path':d['path'],
        'sha256':d['sha256'],'rows':[r for r in d['source_candidates'] if r['context_id']==context]})
labels={}
for line in (ROOT/'data/gold/labels/position_labels.jsonl').read_text().splitlines():
    r=json.loads(line);labels[r['_key']]=r
jobs=[('fortress_eligibility','data/raw/filings/bdc_html/2012139/000119312525203968.html','single investment as of March 31, 2025'),
      ('fortress_level3','data/raw/filings/bdc_html/2012139/000119312526224353.html','1,092'),
      ('diameter_early','data/raw/filings/bdc_html/1916099/000095017024058570.html','December 31, 2023')]
for r in labels.values():
    if (r['cik']=='0001838126' and r['source_identifier']=='Sentinel Buyer Corp. 2') or (r['cik']=='0001925309' and 'Aurelia' in r['source_identifier']):
        jobs.append(('legacy_label_'+r['cik'],r['source_ref']['doc'].replace('\\','/'),'Sentinel Buyer' if r['cik']=='0001838126' else 'Aurelia Netherlands'))
for name,relative,needle in jobs:
    path=ROOT/relative
    if not path.exists():
        cases.append({'case':name,'status':'requested_source_path_missing','path':relative});continue
    assert path.stat().st_size<55_000_000
    with path.open('rb') as f:digest=hashlib.file_digest(f,'sha256').hexdigest()
    tree=etree.parse(str(path),etree.HTMLParser(no_network=True,recover=True))
    contexts={n.get('id'):clean(n) for n in tree.xpath('//*[substring(name(), string-length(name()) - 6) = "context"]')}
    units={n.get('id'):clean(n) for n in tree.xpath('//*[substring(name(), string-length(name()) - 3) = "unit"]')}
    text=clean(tree.getroot());offset=text.find(needle)
    matching=[]
    for row in tree.xpath('//tr[not(.//tr)]'):
        if needle.lower() in clean(row).lower():
            preceding=[];ancestor=row.xpath('ancestor::table[1]')[0]
            for level in range(4):
                sib=ancestor.getprevious()
                for _ in range(5):
                    if sib is None:break
                    preceding.append(clean(sib)[-500:]);sib=sib.getprevious()
                ancestor=ancestor.getparent()
                if ancestor is None:break
            matching.append({'xpath':tree.getpath(row),'cells':[clean(c) for c in row.xpath('./td|./th')],
               'preceding_candidates':preceding,
               'table_opening':[clean(r) for r in row.xpath('ancestor::table[1]/tr[position()<=5]')],
               'facts':[{'attributes':dict(f.attrib),'text':clean(f),'context':contexts.get(f.get('contextref')),'unit':units.get(f.get('unitref'))} for f in row.xpath('.//*[@contextref and @name]')]})
    cases.append({'case':name,'path':relative,'sha256':digest,'text_match':offset,
        'excerpt':text[max(0,offset-250):offset+650] if offset>=0 else None,
        'matching_rows_count':len(matching),'matching_rows':matching[:15]})
    print(name+' matching rows '+str(len(matching)),flush=True)
(OUT/'review_case_sources.json').write_text(json.dumps(cases,ensure_ascii=True,indent=2),encoding='utf-8')
timer.cancel()
