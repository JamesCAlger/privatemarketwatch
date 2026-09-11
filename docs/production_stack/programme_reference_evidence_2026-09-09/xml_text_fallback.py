"""Read at most five cached XML files where latest HTML exceeds the read cap."""
import csv,hashlib,json,os,threading
import duckdb
from pathlib import Path
from lxml import etree
ROOT=next(p for p in Path(__file__).resolve().parents if (p/'AGENTS.md').exists());os.chdir(ROOT);OUT=Path(__file__).parent
t=threading.Timer(75,lambda:os._exit(124));t.daemon=True;t.start()
with (OUT/'fund_source_documents.csv').open(newline='',encoding='utf-8') as f:docs=[r for r in csv.DictReader(f) if r['available']!='True']
assert len(docs)<=5
records=[]
for d in docs:
    if d['cik']=='0001950803':
        con=duckdb.connect()
        cur=con.execute("SELECT * FROM read_csv('data/output/bdc_filings_index.csv',all_varchar=true) WHERE cik='0001950803' AND accession_number='0001193125-23-210954'")
        rows=cur.fetchall();assert len(rows)==1
        d={**d,**dict(zip([c[0] for c in cur.description],rows[0]))};con.close()
    p=Path(d['xbrl_local_path']);assert p.exists() and p.stat().st_size<50_000_000
    tree=etree.parse(str(p),etree.XMLParser(resolve_entities=False,no_network=True,huge_tree=True))
    blocks=tree.xpath('//*[contains(local-name(),"TextBlock")]');assert len(blocks)<1000
    pieces=[]
    for block in blocks:
        text=block.text or ''
        if len(text)>2_000_000:continue
        node=etree.fromstring(('<html><body>'+text+'</body></html>').encode(),etree.HTMLParser(encoding='utf-8',no_network=True,recover=True))
        clean=' '.join(' '.join(node.itertext()).split())
        pieces.append(etree.QName(block).localname+': '+clean)
    body='\n'.join(pieces)
    (OUT/'source_text'/(d['cik']+'.txt')).write_text(body,encoding='utf-8')
    records.append({**d,'source_path':p.relative_to(ROOT).as_posix(),'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),
       'text_sha256':hashlib.sha256(body.encode()).hexdigest(),'text_chars':len(body),'text_method':'concatenated named XBRL text blocks; HTML-normalized per block'})
    print(d['cik']+' text blocks '+str(len(blocks))+' chars '+str(len(body)),flush=True)
with (OUT/'xml_fallback_documents.csv').open('w',newline='',encoding='utf-8') as f:
    w=csv.DictWriter(f,fieldnames=sorted({k for r in records for k in r}));w.writeheader();w.writerows(records)
t.cancel()
