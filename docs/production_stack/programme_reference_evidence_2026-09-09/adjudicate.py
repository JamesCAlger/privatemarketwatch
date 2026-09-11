"""Materialize reviewed lifecycle bounds and a source-first 910-slot frame.

Bounded cache-only preparation, not a production eligibility policy or gold labeler.
The manually selected bounds below must be reviewed with their saved passages.
"""
import csv, hashlib, json, os, re, threading
from collections import Counter
from pathlib import Path
import duckdb
ROOT=next(p for p in Path(__file__).resolve().parents if (p/'AGENTS.md').exists())
os.chdir(ROOT); OUT=Path(__file__).parent
timer=threading.Timer(90,lambda:os._exit(124));timer.daemon=True;timer.start()
def read(name):
    with (OUT/name).open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))
def write(name,rows):
    assert rows
    with (OUT/name).open('w',encoding='utf-8',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)

# CIK, text key suffix, lower/upper bound on FIRST investment operations, source phrase.
# A blank lower bound means operating-by evidence, not a known inception date.
decisions=[
('1588272','','2014-09-02','2014-09-02',r'commenced operations on September 2, 2014'),
('1634452','','2017-11-15','2017-11-15',r'commenced investment operations on November 15, 2017'),
('1646614','','2015-07-01','2015-07-01',r'commenced investment operations on July 1, 2015'),
('1743415','','2019-03-12','2019-03-12',r'March 12, 2019.{0,500}commenced'),
('1792509','','2020-05-27','2020-05-27',r'May 27, 2020.{0,400}commencement'),
('1860424','','2021-10-01','2021-10-01',r'commenced.{0,80}October 1, 2021'),
('1899017','_2023-06-30','2023-04-01','2023-06-30',r'Bain Capital Private Credit Schedule of Investments As of June 30, 2023'),
('1899996','_2023-06-30','','2022-12-31',r'Consolidated Statements of Ass ets and Liabilities June 30, 2023 December 31, 2022'),
('1901164','','2022-11-14','2022-11-14',r'commenced operations on November 14, 2022'),
('1905824','','2022-06-30','2022-06-30',r'commenced investment operations on June 30, 2022'),
('1916099','','2023-12-20','2023-12-20',r'commenced operations on December 20, 2023'),
('1919369','_2023-12-31','2023-10-01','2023-12-31',r'did not commence investing activities until the fourth calendar quarter of 2023'),
('1920145','','2023-04-06','2023-04-06',r'April 6, 2023.{0,300}commenced'),
('1925309','','2022-08-31','2022-08-31',r'commenced its loan origination and investment activities on August 31, 2022'),
('1930087','','2023-06-30','2023-06-30',r'commenced.{0,100}June 30, 2023'),
('1950803','','2023-04-03','2023-04-03',r'April 3, 2023.{0,100}commence'),
('1950976','','2023-10-11','2023-10-11',r'commenced.{0,100}October 11, 2023'),
('1954360','_2023-09-30','2023-05-05','2023-05-05',r'May 5, 2023.{0,60}Commencement of Operations'),
('1959568','_2023-09-30','2023-10-01','2023-12-31',r'As of September 30, 2023, we had not commenced operations and have not made any investments'),
('1959604','_2023-09-30','2023-10-01','2023-12-31',r'As of September 30, 2023, we had not commenced operations and have not made any investments'),
('1965934','_2024-03-31','2024-04-01','2024-06-30',r'As of March 31, 2024.{0,120}had not commenced operations'),
('1976336','','2024-11-05','2024-11-05',r'commenced investment operations on November 5, 2024'),
('1989817','','2024-04-08','2024-04-08',r'commenced.{0,100}April 8, 2024'),
('1993402','','2024-01-19','2024-01-19',r'commenced investment operations on January 19, 2024'),
('2006758','','2023-12-15','2023-12-15',r'commencement of operations on December 15, 2023'),
('2008748','','2024-02-23','2024-02-23',r'commenced.{0,100}February 23, 2024'),
('2011498','','2024-10-21','2024-10-21',r'October 21, 2024.{0,180}Commencement of Operations'),
('2012139','_2025-06-30','2025-01-01','2025-06-30',r'As of December 31, 2024, the Company had not yet commenced investment operations'),
('2031750','','2024-08-28','2024-08-28',r'commenced.{0,100}August 28, 2024'),
('2049733','','2025-05-01','2025-05-01',r'May 1, 2025.{0,65}commencement of operations'),
('2052152','','2025-01-24','2025-01-24',r'Amounts have been derived based on the activity and the weighted average number of shares outstanding started on January 24, 2025'),
('2083477','','2026-01-02','2026-01-02',r'January 2, 2026.{0,35}commencement of operations'),
]
docs={r['cik']:{**r,'source_path':r['html_path'],'text_method':'HTML itertext excluding script/style; whitespace collapsed'} for r in read('fund_source_documents.csv') if r['available']=='True'}
docs.update({r['cik']:r for r in read('xml_fallback_documents.csv')})
docs.update({r['text_key']:{**r,'text_method':'HTML itertext excluding script/style; whitespace collapsed'} for r in read('early_source_documents.csv')})
funds={r['cik']:r for r in read('fund_metadata.csv')}
passages=[];lifecycle=[];missing=[]
for cik,suffix,lo,hi,pattern in decisions:
    cik=cik.zfill(10);key=cik+suffix;d=docs[key]
    body=(OUT/'source_text'/(key+'.txt')).read_text(encoding='utf-8')
    m=re.search(pattern,body,re.I)
    if not m:missing.append((key,pattern));continue
    a=max(0,m.start()-160);b=min(len(body),m.end()+320)
    eid='LIFE-'+cik
    passages.append({'evidence_id':eid,'cik':cik,'source_path':d['source_path'],'document_sha256':d['sha256'],
      'accession':d['accession_number'],'document_report_date':d['report_date'],'text_key':key,
      'text_sha256':d['text_sha256'],'text_method':d['text_method'],'start':a,'end':b,'excerpt':body[a:b],
      'review_status':'agent_source_reviewed; not owner-adjudicated or held-out gold'})
    reason='Source states commencement date.'
    if cik=='0001899996':reason='Operating by 2022-12-31: comparative investment assets. Note 1 preserves LP-to-LLC continuity; BDC election is not inception.'
    if cik=='0002052152':reason='Start inferred from financial highlights: first activity/share period starts 2025-01-24; return footnote uses commencement NAV. Acquired portfolio history is not automatically this fund history.'
    if lo!=hi and lo:reason='Bounded start interval; lower bound from explicit prior inactivity; upper bound from positive source investment facts or stated first investment quarter. Exact start date not asserted.'
    if cik=='0001899017':reason='Q1 filing explicitly not operating; Q2 schedule contains equity/credit investments. Later November 2023 commencement language cannot exclude these earlier disclosed investments. First qualifying investment interval, not asserted formal launch date.'
    lifecycle.append({'cik':cik,'entity_name':funds[cik]['entity_name'],'first_operation_lower':lo,'first_operation_upper':hi,
      'evidence_id':eid,'basis':reason})
if missing:raise RuntimeError(json.dumps(missing))
# Additional authority for predecessor continuity, positive endpoint and cash counterexamples.
extras=[
('LORD-2026Q1-TOTAL','0002008748',r'Total investments at fair value.{0,130}1,413,006'),
('LORD-2026Q1-SCHEDULE','0002008748',r'Total Investments \(8\).{0,80}1,413,006'),
('BAIN-Q1-NOT-OPERATING','0001899017_2023-03-31',r'had not commenced operations as of March 31, 2023'),
('BAIN-LATER-COMMENCEMENT','0001899017',r'commenced.{0,120}November 28, 2023'),
('FIDELITY-CONTINUITY','0001899996_2023-06-30',r'Effective January 31, 2023, the General Partner and the Limited Partners became unit holders'),
('SENIOR-FIRST-PORTFOLIO','0001959568_2023-12-31',r'On December 4, 2023, the Company completed the acquisition of the Warehouse Portfolio'),
('JEFFERIES-FIRST-PORTFOLIO','0001959604_2023-12-31',r'On December 4, 2023, the Company completed the acquisition of the Warehouse Portfolio'),
]
for eid,key,pattern in extras:
    d=docs[key];body=(OUT/'source_text'/(key+'.txt')).read_text(encoding='utf-8');m=re.search(pattern,body,re.I);assert m,(eid,pattern)
    a=max(0,m.start()-150);b=min(len(body),m.end()+400)
    passages.append({'evidence_id':eid,'cik':key[:10],'source_path':d['source_path'],'document_sha256':d['sha256'],
      'accession':d['accession_number'],'document_report_date':d['report_date'],'text_key':key,
      'text_sha256':d['text_sha256'],'text_method':d['text_method'],'start':a,'end':b,'excerpt':body[a:b],
      'review_status':'agent_source_reviewed; not owner-adjudicated or held-out gold'})
write('lifecycle_decisions.csv',lifecycle)
(OUT/'source_passages.json').write_text(json.dumps(passages,indent=2,ensure_ascii=True),encoding='utf-8')
life={r['cik']:r for r in lifecycle}
cf={(r['cik'],r['report_date']):r for r in read('positive_investment_evidence.csv')}
with Path('docs/production_stack/programme_contract_evidence_2026-09-09/obligation_frame.csv').open(newline='',encoding='utf-8') as f:frame=list(csv.DictReader(f))
rows=[]
for r in frame:
    cik=r['cik'];q=r['report_date'];l=life.get(cik);c=cf.get((cik,q));n=int(r['holdings_rows']);eids=[]
    if l:eids.append(l['evidence_id'])
    if c:eids.append('CF-'+cik+'-'+q)
    if l and l['first_operation_lower'] and q<l['first_operation_lower']:
        assert not c,('source contradiction',cik,q)
        status='not_yet_investment_operating'
    elif c:status='eligible_source_investments'
    elif l and q>=l['first_operation_upper']:status='eligible_operating_interval'
    else:status='unresolved_start_interval'
    # Observed holdings never determine lifecycle eligibility.
    follow=''
    if status.startswith('eligible') and not n:
        follow='missing_output_positive_source_investments' if c else 'missing_output_roster_or_cash_status_unreviewed'
    if status=='not_yet_investment_operating' and n:follow='retain_disclosures_review_cash_population'
    if status=='unresolved_start_interval':follow='resolve_exact_quarter_before_final_denominator'
    rows.append({'cik':cik,'entity_name':funds[cik]['entity_name'],'report_date':q,'eligibility_status':status,
      'evidence_ids':';'.join(eids),'holdings_rows':n,'indexed_filings':r['indexed_filings'],
      'positive_investment_concept':c['concept'] if c else '',
      'positive_investment_amount':c['amount'] if c else '', 'source_currency':c['currency'] if c else '',
      'positive_source_accession':c['accession'] if c else '',
      'full_source_roster_reviewed':False,'follow_up':follow})
assert len(rows)==910 and len({(r['cik'],r['report_date']) for r in rows})==910
write('obligations.csv',rows)
write('missing_output_obligations.csv',[r for r in rows if not r['holdings_rows']])
qs=[]
for q in sorted({r['report_date'] for r in rows}):
    rr=[r for r in rows if r['report_date']==q];eligible=[r for r in rr if r['eligibility_status'].startswith('eligible')]
    qs.append({'report_date':q,'all_obligations':len(rr),'eligible':len(eligible),
      'pre_operation':sum(r['eligibility_status']=='not_yet_investment_operating' for r in rr),
      'unresolved':sum(r['eligibility_status'].startswith('unresolved') for r in rr),
      'eligible_with_saved_rows':sum(r['holdings_rows']>0 for r in eligible),
      'eligible_missing_rows':sum(not r['holdings_rows'] for r in eligible),
      'missing_positive_source':sum(r['follow_up']=='missing_output_positive_source_investments' for r in rr),
      'pre_operation_with_saved_rows':sum(r['eligibility_status']=='not_yet_investment_operating' and r['holdings_rows']>0 for r in rr)})
write('eligibility_quarters.csv',qs)
summary={'status_counts':dict(Counter(r['eligibility_status'] for r in rows)),
 'follow_up_counts':dict(Counter(r['follow_up'] for r in rows if r['follow_up'])),
 'quarters':qs,'lifecycle_decisions':len(lifecycle),'source_passages':len(passages),
 'interpretation':'Operating-history assessment, not complete statutory filing eligibility or independent source-roster accuracy. Pre-operation disclosed records retained. One unresolved quarter must not be silently removed.'}
(OUT/'eligibility_summary.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
timer.cancel();print(json.dumps(summary,indent=2))
