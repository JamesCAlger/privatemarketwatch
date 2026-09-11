"""Bounded search of original cached XML for target missing-quarter facts."""
import csv,hashlib,json,os,threading
from pathlib import Path
from lxml import etree
ROOT=next(p for p in Path(__file__).resolve().parents if (p/'AGENTS.md').exists());os.chdir(ROOT);OUT=Path(__file__).parent
t=threading.Timer(100,lambda:os._exit(124));t.daemon=True;t.start()
targets={'1646614':['2023-03-31'],'1899996':['2023-03-31'],'1901164':['2023-03-31'],'1916099':['2023-12-31'],
 '1954360':['2023-06-30'],'2006758':['2024-03-31'],'2008748':['2024-03-31'],'2012139':['2025-03-31']}
rows=[];docs=[]
for cik,quarters in targets.items():
    files=sorted((Path('data/raw/filings/bdc_xbrl')/cik).glob('*.xml'));assert len(files)<=30
    for p in files:
        st=p.stat()
        if st.st_size>55_000_000:
            docs.append({'path':p.as_posix(),'status':'over_cap','target_contexts':0});continue
        tree=etree.parse(str(p),etree.XMLParser(no_network=True,resolve_entities=False,huge_tree=True))
        contexts=tree.xpath('//*[local-name()="context"][.//*[local-name()="instant" and (text()=$q)]]',q=quarters[0])
        ctx={c.get('id'):[{'axis':m.get('dimension'),'text':' '.join(' '.join(m.itertext()).split())} for m in c.xpath('.//*[local-name()="typedMember" or local-name()="explicitMember"]')] for c in contexts}
        for context,dims in ctx.items():
            facts=tree.xpath('//*[@contextRef=$c]',c=context)
            for f in facts:
                name=etree.QName(f).localname
                if not any(s in name.lower() for s in ('investment','cash','assets')) or len(f.text or '')>60:continue
                rows.append({'cik':cik.zfill(10),'report_date':quarters[0],'path':p.as_posix(),'context_id':context,'dimensions':json.dumps(dims),
                  'concept':name,'value':f.text,'unit':f.get('unitRef'),'decimals':f.get('decimals')})
        docs.append({'path':p.as_posix(),'status':'read','target_contexts':len(contexts)})
    print(cik+' documents '+str(len(files))+' facts '+str(sum(r['cik']==cik.zfill(10) for r in rows)),flush=True)
for name,rr in [('gap_xml_facts.csv',rows),('gap_xml_documents.csv',docs)]:
    if rr:
        with (OUT/name).open('w',newline='',encoding='utf-8') as f:
            w=csv.DictWriter(f,fieldnames=list(rr[0]));w.writeheader();w.writerows(rr)
t.cancel()
