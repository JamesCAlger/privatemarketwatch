"""Build an offline citation proof from pinned original HTML, never product JSON."""
from __future__ import annotations
import hashlib,html,json,os,re,threading,time
from pathlib import Path
from lxml import etree
from scripts.programme_closeout.candidate import sha,atomic_json
from scripts.programme_reference.source_reader import clean,local
ROOT=Path(__file__).resolve().parents[2]
BASE=ROOT/'docs/production_stack/programme_closeout_evidence_2026-09-09'
OUT=BASE/'viewer'
CASES=[
 ('forterro-fv','0001193125-26-215667','/html/body/div[153]/table/tr[25]','fairvalue','5,388','Forterro CHF facility: USD fair value','Reported amount / conflicting currency tag','The printed fair value is 5,388 thousand. Its AFN tag conflicts with the USD reporting presentation; principal is explicitly CHF. The original tag is preserved for review.'),
 ('forterro-sek','0001193125-26-215667','/html/body/div[153]/table/tr[26]','principal','35,658','Forterro SEK facility: principal','Reported foreign-currency amount','SEK 35,658 thousand is original principal. It is not a USD amount and is a different facility from the CHF loan.'),
 ('forterro-sek-fv','0001193125-26-215667','/html/body/div[153]/table/tr[26]','fairvalue','3,663','Forterro SEK facility: USD fair value','Reported amount / conflicting currency tag','Printed fair value is 3,663 thousand in the USD presentation; its RSD inline tag remains a conflict.'),
 ('bigtime','0001193125-25-280627','/html/body/div[100]/table/tr[4]','principal','200','BigTime Software: principal','Corrected source conflict / proposal','The printed principal is $200 thousand; the inline fact says EGP. This development proposal uses the printed USD evidence. It does not change production.'),
 ('riser','0001193125-26-221684','/html/body/div[96]/table/tr[35]','principal','981','Riser Interco: principal','Reported GBP / conflicting EGP tag','The same EGP tag family is used on an explicitly GBP-denominated principal. This case prevents a blanket EGP-to-USD correction.'),
 ('korean','0000950170-24-094137','/html/body/table[26]/tr[15]','principal','195,000,000','Delivery Hero: principal','Unresolved currency interpretation','The contemporaneous filing prints Korean won; the tag says KPW. Later South Korean wording is corroboration, not certification of this older observation. No USD conversion is asserted.'),
]

def resolve_cell(tree,xpath,field,expected):
    rows=tree.xpath(xpath)
    if len(rows)!=1:raise ValueError('Citation row ambiguous or missing')
    facts=[f for f in rows[0].iter() if field in (f.get('name') or '').lower() and clean(f)==expected]
    if len(facts)!=1:raise ValueError('Citation field ambiguous or changed')
    cells=facts[0].xpath('ancestor::td[1]|ancestor::th[1]')
    if len(cells)!=1:raise ValueError('Citation cell ambiguous')
    return facts[0],cells[0]

def sanitize(tree):
    """Passive local rendition. Keep visible filing text and tables; strip active IO."""
    for node in list(tree.iter()):
        if not isinstance(node.tag,str):continue
        tag=local(node.tag)
        if tag in ('script','iframe','object','embed','form','input','button','link','base','img','svg','video','audio','source','header','hidden'):
            parent=node.getparent()
            if parent is not None:parent.remove(node)
            continue
        if tag=='meta' and (node.get('http-equiv') or '').lower()=='refresh':
            node.getparent().remove(node);continue
        if tag=='style' and node.text:
            node.text=re.sub(r'(?is)@import[^;]+;|url\([^)]*\)','',node.text)
        for attr in list(node.attrib):
            if attr.lower().startswith('on') or attr.lower() in ('src','srcset','action','formaction','background','xlink:href'):
                del node.attrib[attr]
            elif attr.lower()=='href' and not node.attrib[attr].startswith('#'):
                del node.attrib[attr]
            elif attr.lower()=='style':
                node.attrib[attr]=re.sub(r'(?is)url\([^)]*\)|expression\([^)]*\)','',node.attrib[attr])
    head=tree.find('head')
    if head is None:head=etree.SubElement(tree.getroot(),'head')
    csp=etree.Element('meta',{'http-equiv':'Content-Security-Policy','content':"default-src 'none'; style-src 'unsafe-inline'; img-src 'none'; script-src 'none'; base-uri 'none'; form-action 'none'"})
    head.insert(0,csp)
    style=etree.SubElement(head,'style');style.text=':target{background:#ffdf70!important;outline:4px solid #a45500!important;scroll-margin-top:70px} .citation-banner{position:sticky;top:0;background:#162c41;color:white;padding:12px;font:14px sans-serif;z-index:9999} body{margin:18px} '

def main():
    timer=threading.Timer(600,lambda:os._exit(124));timer.daemon=True;timer.start();started=time.monotonic()
    OUT.mkdir(parents=True,exist_ok=True)
    docs=json.loads((BASE/'currency_cases/cases.json').read_text())
    byacc={d['accession']:d for d in docs};built={};records=[]
    for acc in dict.fromkeys(c[1] for c in CASES):
        d=byacc[acc];path=ROOT/d['path'];source_hash=sha(path)
        if source_hash!=d['sha256']:raise ValueError('Source hash drift')
        tree=etree.parse(str(path),etree.HTMLParser(no_network=True,huge_tree=True,recover=True))
        for cid,_,xpath,field,expected,title,category,note in [c for c in CASES if c[1]==acc]:
            fact,cell=resolve_cell(tree,xpath,field,expected)
            cell_text=clean(cell);cell_xpath=tree.getpath(cell)
            cell.set('id','cite-'+cid);cell.set('data-citation',cid)
            records.append(dict(id=cid,title=title,category=category,note=note,value=expected,
                source_path=d['path'],source_sha256=source_hash,accession=acc,cik=d['cik'],report_date=d['report_date'],
                row_xpath=xpath,cell_xpath=cell_xpath,cell_text=cell_text,cell_sha256=hashlib.sha256(cell_text.encode()).hexdigest(),
                context_id=fact.get('contextref'),concept=fact.get('name'),raw_unit=fact.get('unitref'),scale=fact.get('scale'),
                rendition=acc+'.html',fragment='cite-'+cid,exposure='development; not hold-out'))
        sanitize(tree)
        body=tree.find('body');banner=etree.Element('div',{'class':'citation-banner'})
        banner.text='Cached filing rendition | '+d['report_date']+' | '+acc+' | Active content removed; source text retained. Source SHA-256: '+source_hash
        body.insert(0,banner)
        target=OUT/(acc+'.html');target.write_bytes(etree.tostring(tree,encoding='utf-8',method='html'))
        built[acc]=dict(rendition=target.name,sha256=sha(target),bytes=target.stat().st_size,source_sha256=source_hash)
    for r in records:r['rendition_sha256']=built[r['accession']]['sha256']
    synthetic=[dict(id='derived',title='Two Forterro facilities: combined fair value',category='Calculated / development aggregation',value='$9,051,000',
        inputs=['forterro-fv','forterro-sek-fv'],formula='(5388 + 3663) * 1000',
        note='Sum of two retained facilities, using their proposed USD presentation amounts. This is a selected pair, not total Forterro exposure. Both input currency conflicts remain visible and the result inherits provisional status.'),
        dict(id='inferred',title='Forterro: proposed GICS sector',category='Inferred / research assignment',value='Information Technology (45)',inputs=['forterro-fv'],
        decision_id='DEV-GICS-FORTERRO-20260909',method='business-description mapping; analyst judgment',confidence='provisional',
        scope='Forterro business group; legal borrower mapping unresolved',business_source='https://www.forterro.com/en/company/about',
        source_capture='Official search excerpt describes industrial business software; direct page returned 403. No full-page hash or historical revenue verification.',
        taxonomy_path='data/reference/gics_hierarchy.json',taxonomy_sha256=sha(ROOT/'data/reference/gics_hierarchy.json'),
        note='Research proposal from the software business description, mapped to the local taxonomy. This is not vendor-confirmed GICS, a filing disclosure, or an independently validated historical borrower assignment. Source capture, effective date and legal-entity mapping remain incomplete; keep it out of accuracy gold.'),
        dict(id='unavailable',title='Missing primary source',category='Unavailable',value='Unavailable',
        note='The required primary HTML is absent from the local pilot cache. A comparative XML fact is not a complete source roster. No unrelated filing opens as a substitute.'),
        dict(id='stale',title='Rejected stale locator',category='Unavailable / invalid evidence identity',value='Rejected',
        note='A stale source hash, missing cell, ambiguous locator or changed expected text invalidates a citation. Re-resolve it in a new candidate; do not fall back to the nearest number.')]
    all_cases=records+synthetic
    data=json.dumps(all_cases,ensure_ascii=True).replace('<','\\u003c')
    page='''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Programme evidence viewer</title>
<style>*{box-sizing:border-box}body{margin:0;color:#173046;background:#f4f6f8;font:16px/1.5 system-ui}header{padding:22px 28px;background:#173046;color:white}h1{margin:0;font-size:25px}header p{margin:5px 0}main{display:grid;grid-template-columns:320px 1fr;min-height:85vh}nav{padding:16px;display:flex;flex-direction:column;gap:8px}button{font:inherit;text-align:left;border:1px solid #bac7cf;background:white;border-radius:7px;padding:10px;cursor:pointer}button[aria-pressed=true]{border:2px solid #215e97;background:#e7f2fc}button:focus-visible,a:focus-visible{outline:3px solid #af5200}button span{display:block;font-weight:700}article{padding:20px;min-width:0}.badge{display:inline-block;background:#e7dbba;padding:3px 10px;border-radius:20px}#meta{font:12px/1.5 monospace;overflow-wrap:anywhere}iframe{width:100%;height:65vh;border:1px solid #9faeba;background:white}.empty{padding:30px;background:white;border:1px dashed #9faeba}#links a{margin-right:20px}@media(max-width:700px){main{display:block}nav{display:grid;grid-template-columns:1fr 1fr}article{padding:12px}iframe{height:65vh}header{padding:15px}}</style>
<header><h1>From a number to its evidence</h1><p>Offline programme prototype · Real filing examples and clearly marked illustrative paths</p></header><main><nav aria-label="Evidence examples" id="cases"></nav><article><h2 id="title">Choose a number</h2><span class="badge" id="category">Evidence type</span><p id="note"></p><p id="links"></p><p id="meta"></p><div id="display"></div></article></main><script>
const cases=CASE_DATA; window.citationCases=cases; window.navigationResults=[];
function select(c){const started=performance.now();document.querySelectorAll('button').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.id===c.id)));document.getElementById('title').textContent=c.title;document.getElementById('category').textContent=c.category;document.getElementById('note').textContent=c.note;document.getElementById('links').replaceChildren();document.getElementById('meta').textContent='';const area=document.getElementById('display');area.replaceChildren();
if(c.rendition){const url=c.rendition+'#'+c.fragment;const a=document.createElement('a');a.href=url;a.target='_blank';a.rel='noopener';a.textContent='Open filing with highlight';document.getElementById('links').append(a);document.getElementById('meta').textContent=c.report_date+' | '+c.accession+' | '+c.concept+' | tag '+c.raw_unit+' | source SHA-256 '+c.source_sha256;const frame=document.createElement('iframe');frame.title=c.title+' source filing';frame.setAttribute('sandbox','allow-same-origin');frame.src=url;frame.onload=()=>window.navigationResults.push({id:c.id,ms:performance.now()-started});area.append(frame);}else{const p=document.createElement('p');p.className='empty';p.textContent='No direct source highlight applies to this path. '+c.note;area.append(p);window.navigationResults.push({id:c.id,ms:performance.now()-started});}}
const originalSelect=select;select=function(c){originalSelect(c);if(c.inputs){const detail=document.createElement('pre');detail.style.whiteSpace='pre-wrap';detail.textContent=JSON.stringify(Object.fromEntries(Object.entries(c).filter(([k])=>!['title','note','value','category','inputs'].includes(k))),null,2);document.getElementById('display').append(detail);for(const id of c.inputs){const input=cases.find(x=>x.id===id);const a=document.createElement('a');a.href='#'+id;a.textContent='Evidence: '+input.title;a.dataset.input=id;a.onclick=e=>{e.preventDefault();select(input)};document.getElementById('links').append(a);}}};
for(const c of cases){const b=document.createElement('button');b.dataset.id=c.id;b.setAttribute('aria-pressed','false');b.textContent=c.title;const value=document.createElement('span');value.textContent=c.value;b.append(value);b.onclick=()=>select(c);document.getElementById('cases').append(b);}select(cases[0]);
</script></html>'''.replace('CASE_DATA',data)
    (OUT/'index.html').write_text(page,encoding='utf-8')
    atomic_json(OUT/'citations.json',all_cases)
    atomic_json(OUT/'build.json',dict(source_documents=built,cases=len(all_cases),real_highlights=len(records),seconds=time.monotonic()-started,
                status='built; browser validation separate',builder_sha256=sha(Path(__file__))))
    print(json.dumps(dict(documents=len(built),highlights=len(records),seconds=time.monotonic()-started)),flush=True);timer.cancel()

if __name__=='__main__':main()
