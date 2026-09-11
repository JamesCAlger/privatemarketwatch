"""Bounded source-only extraction of manually reviewed development examples.

Selection was informed by investigation/existing gold. These are NOT held-out labels.
No shared pipeline parser is used. XPath/row text and document hash are retained.
"""
import csv,hashlib,json,os,re,threading
from pathlib import Path
from lxml import etree
ROOT=next(p for p in Path(__file__).resolve().parents if (p/'AGENTS.md').exists());os.chdir(ROOT);OUT=Path(__file__).parent
t=threading.Timer(60,lambda:os._exit(124));t.daemon=True;t.start()
requests=[
 ('BAIN-2023Q2','1899017','0000950170-23-041723','Legacy Corporate Lending HoldCo'),
 ('ESDEC-2023Q3','1837532','0000950170-23-061985','Esdec Solar Group B.V.'),
 ('ESDEC-2023Q4','1837532','0000950170-24-031479','Esdec Solar Group B.V.'),
 ('ESDEC-2024Q1','1837532','0000950170-24-058684','Esdec Solar Group B.V.'),
]
rows=[];manifest=[]
for eid,cik,acc,needle in requests:
    p=Path('data/raw/filings/bdc_html')/cik/(acc.replace('-','')+'.html');st=p.stat();assert st.st_size<55_000_000
    with p.open('rb') as f:sha=hashlib.file_digest(f,'sha256').hexdigest()
    tree=etree.parse(str(p),etree.HTMLParser(no_network=True,recover=True))
    body=' '.join(' '.join(tree.getroot().itertext()).split())
    unit_hits=[]
    for m in re.finditer(r'.{0,80}(?:in thousands|dollars in thousands).{0,100}',body,re.I):
        unit_hits.append(m.group())
        if len(unit_hits)==3:break
    matches=tree.xpath('//tr[contains(string(.), $needle) and not(.//tr)]',needle=needle);assert len(matches)<=25,len(matches)
    found=[]
    for node in matches:
        cells=[' '.join(' '.join(c.itertext()).split()) for c in node.xpath('./td|./th')]
        table=node.xpath('ancestor::table[1]')[0]
        headers=table.xpath('./tr[position()<=5]|./tbody/tr[position()<=5]')
        headertext=[' '.join(' '.join(h.itertext()).split())[:2500] for h in headers]
        preceding=[];sibling=table.getprevious()
        for _ in range(8):
            if sibling is None:break
            preceding.append(' '.join(' '.join(sibling.itertext()).split())[-600:]);sibling=sibling.getprevious()
        facts=[{'attributes':dict(el.attrib),'text':' '.join(' '.join(el.itertext()).split())} for el in node.iter() if str(el.tag).lower().endswith('nonfraction')]
        refs=sorted({f['attributes'][k] for f in facts for k in ('unitref','contextref') if k in f['attributes']})
        ref_text={}
        for ref in refs:
            targets=tree.xpath('//*[@id=$ref]',ref=ref);assert len(targets)==1,(eid,ref,len(targets))
            ref_text[ref]=' '.join(' '.join(targets[0].itertext()).split())
        found.append({'xpath':tree.getpath(node),'table_xpath':tree.getpath(table),'cells':cells,'table_opening_rows':headertext,
          'preceding_siblings_nearest_first':preceding,'inline_numeric_facts':facts,'source_units_and_contexts':ref_text})
    assert found,eid
    rows.append({'example_group':eid,'cik':cik.zfill(10),'accession':acc,'source_path':p.as_posix(),
      'document_sha256':sha,'review_status':'agent-source-reviewed development; selected using prior investigation/gold; not acceptance gold',
      'unit_passage_candidates':unit_hits,'candidate_source_rows':found})
    manifest.append({'path':p.as_posix(),'bytes':st.st_size,'mtime_ns':st.st_mtime_ns,'sha256':sha})
    assert (st.st_size,st.st_mtime_ns)==(p.stat().st_size,p.stat().st_mtime_ns)
    print(eid+' candidate rows '+str(len(found)),flush=True)
(OUT/'development_source_rows.json').write_text(json.dumps(rows,indent=2,ensure_ascii=True),encoding='utf-8')
with (OUT/'development_input_manifest.csv').open('w',newline='',encoding='utf-8') as f:
    w=csv.DictWriter(f,fieldnames=list(manifest[0]));w.writeheader();w.writerows(manifest)
t.cancel()
