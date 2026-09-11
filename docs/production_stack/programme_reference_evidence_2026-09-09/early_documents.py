"""Read two early cached filings per selected lifecycle ambiguity; bounded 16 files."""
import csv,hashlib,json,os,threading
from pathlib import Path
import duckdb
from lxml import etree
ROOT=next(p for p in Path(__file__).resolve().parents if (p/'AGENTS.md').exists());os.chdir(ROOT);OUT=Path(__file__).parent
t=threading.Timer(90,lambda:os._exit(124));t.daemon=True;t.start()
ids=['0001899017','0001899996','0001919369','0001954360','0001959568','0001959604','0002012139','0001965934']
con=duckdb.connect();con.execute("SET threads=2");con.execute("SET memory_limit='512MB'")
c=con.execute("""SELECT cik,accession_number,report_date,filing_date,form_type FROM read_csv('data/output/bdc_filings_index.csv',all_varchar=true)
 WHERE cik IN (SELECT unnest(?)) AND report_date>='2023-03-31' AND report_date<='2026-03-31'
 AND form_type IN ('10-K','10-Q','10-K/A','10-Q/A')
 QUALIFY row_number() OVER(PARTITION BY cik ORDER BY report_date,filing_date,accession_number)<=2 ORDER BY cik,report_date""",[ids])
docs=[dict(zip([x[0] for x in c.description],r)) for r in c.fetchall()];assert len(docs)<=16
records=[]
for d in docs:
    p=Path('data/raw/filings/bdc_html')/str(int(d['cik']))/(d['accession_number'].replace('-','')+'.html')
    if not p.exists() or p.stat().st_size>35_000_000:
        records.append({**d,'source_path':p.as_posix(),'available':False,'sha256':'','text_key':'','text_sha256':''});continue
    tree=etree.parse(str(p),etree.HTMLParser(no_network=True,recover=True))
    for e in tree.xpath('//script|//style'):e.getparent().remove(e)
    body=' '.join(' '.join(tree.getroot().itertext()).split())
    key=d['cik']+'_'+d['report_date']
    (OUT/'source_text'/(key+'.txt')).write_text(body,encoding='utf-8')
    records.append({**d,'source_path':p.as_posix(),'available':True,'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),
         'text_key':key,'text_sha256':hashlib.sha256(body.encode()).hexdigest()})
    print(key+' chars '+str(len(body)),flush=True)
with (OUT/'early_source_documents.csv').open('w',encoding='utf-8',newline='') as f:
    w=csv.DictWriter(f,fieldnames=list(records[0]));w.writeheader();w.writerows(records)
t.cancel()
