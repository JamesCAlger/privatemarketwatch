"""Read original inline facts and source rows without production extraction rules.

The result is a review candidate, never an independently adjudicated roster.
No per-filer corrections, dimension deduplication or candidate-output inputs.
"""
from __future__ import annotations

import hashlib
import re
from decimal import Decimal, InvalidOperation
from pathlib import Path

from lxml import etree

FIELDS = {
    'investmentownedatfairvalue': 'fair_value',
    'investmentownedfairvalue': 'fair_value',
    'moneymarketfundsatfairvalue': 'fair_value',
    'investmentownedatcost': 'cost',
    'investmentownedcost': 'cost',
    'moneymarketfundsatcarryingvalue': 'cost',
    'investmentownedbalanceprincipalamount': 'principal_amount',
    'investmentownedbalanceshares': 'shares_held',
    'investmentinterestratepaidincash': 'cash_rate',
    'investmentinterestrate': 'reported_rate',
    'investmentinterestratepaidinkind': 'pik_rate',
    'investmentpikrate': 'pik_rate',
    'investmentbasisspreadvariablerate': 'basis_spread',
    'investmentbasisspreadofvariablerate': 'basis_spread',
    'investmentownedpercentofnetassets': 'pct_of_net_assets',
    'investmentownedpercentageofnetassets': 'pct_of_net_assets',
}
RATES = {'cash_rate','reported_rate','pik_rate','basis_spread','pct_of_net_assets'}


def local(tag: str) -> str:
    return str(tag).split('}')[-1].split(':')[-1].lower()


def clean(node) -> str:
    if not isinstance(node.tag,str):return ''
    return ' '.join(' '.join(node.itertext()).split())


def numeric_fact(text: str, attrs: dict) -> tuple[Decimal | None, str]:
    """Respect inline scale/sign/format; nil, dash and unsupported format stay explicit."""
    if any(local(k)=='nil' and str(v).lower() in ('true','1') for k,v in attrs.items()):
        return None, 'nil'
    fmt=local(attrs.get('format',''))
    if fmt not in ('','num-dot-decimal','numdotdecimal','num-comma-decimal','numcommadecimal','zerodash','zero-dash','numdash'):
        return None, 'unsupported_format:'+fmt
    value=text.strip().replace('\u00a0','').replace(' ','')
    if value in ('-','\u2014','\u2013',''):
        return (Decimal(0),'reported_zero') if fmt in ('zerodash','zero-dash','numdash') else (None,'unqualified_dash')
    if fmt in ('num-comma-decimal','numcommadecimal'):
        value=value.replace('.','').replace(',','.')
    else:value=value.replace(',','')
    try:
        scale=int(attrs.get('scale','0'))
        if abs(scale)>12:return None,'unsupported_scale'
        amount=Decimal(value)*(Decimal(10)**scale)
        if not amount.is_finite():return None,'nonfinite'
        if attrs.get('sign')=='-':amount=-amount
        return amount,'parsed'
    except (InvalidOperation,ValueError):return None,'unparsed'


def rounding_bound(attrs: dict) -> Decimal | None:
    value=attrs.get('decimals','')
    if value.upper()=='INF':return Decimal(0)
    try:
        d=int(value)
        return Decimal('0.5')*(Decimal(10)**(-d)) if abs(d)<=12 else None
    except ValueError:return None


def currency(measures: list[str]) -> str | None:
    """Resolve actual measure definitions, not the spelling of a unit ID."""
    if len(measures)==1 and re.fullmatch(r'(?:[^:]+:)?[A-Z]{3}',measures[0]):
        return measures[0].split(':')[-1]
    return None


def read_document(path: Path, report_date: str, max_bytes: int=55_000_000) -> dict:
    path=Path(path);st=path.stat()
    if st.st_size>max_bytes:raise ValueError('source_size_cap')
    with path.open('rb') as f:sha=hashlib.file_digest(f,'sha256').hexdigest()
    tree=etree.parse(str(path),etree.HTMLParser(no_network=True,recover=True))
    # XPath's prefix-free suffix test also handles HTMLParser's literal ix: tags.
    contexts={};units={}
    for ctx in tree.xpath('//*[substring(name(), string-length(name()) - 6) = "context"]'):
        instants=[(n.text or '').strip() for n in ctx.iter() if local(n.tag)=='instant']
        if instants!=[report_date]:continue
        ident=[clean(n) for n in ctx.iter() if local(n.tag)=='identifier']
        dims=[{'axis':n.get('dimension',''),'value':clean(n),'kind':local(n.tag)} for n in ctx.iter() if local(n.tag) in ('typedmember','explicitmember')]
        contexts[ctx.get('id','')]={'cik':ident[0].zfill(10) if ident else '', 'report_date':report_date,'dimensions':dims}
    for unit in tree.xpath('//*[substring(name(), string-length(name()) - 3) = "unit"]'):
        units[unit.get('id','')]=[clean(n) for n in unit.iter() if local(n.tag)=='measure']
    facts=tree.xpath('//*[@contextref and @name]');assert len(facts)<150000,'fact cap'
    rows={};anchors=[];table_cache={};concepts={};rejected=[]
    for f in facts:
        ctx=f.get('contextref','')
        if ctx not in contexts or local(f.tag)!='nonfraction':continue
        name=f.get('name','');tag=local(name);field=FIELDS.get(tag)
        context=contexts[ctx]
        anchor_candidate=(not context['dimensions'] and ('investment' in tag and 'income' not in tag and ('fairvalue' in tag or 'carrying' in tag)))
        if not field and not anchor_candidate:continue
        amount,status=numeric_fact(clean(f),dict(f.attrib));bound=rounding_bound(dict(f.attrib))
        if field in RATES and amount is not None:
            amount*=100
            if bound is not None:bound*=100
        trs=f.xpath('ancestor::tr[1]');tables=f.xpath('ancestor::table[1]')
        if not trs or not tables:
            rejected.append({'context_id':ctx,'concept':name,'reason':'not_in_visible_table_row'});continue
        tr=trs[0];table=tables[0];xpath=tree.getpath(tr);tablepath=tree.getpath(table)
        if tablepath not in table_cache:
            preceding=[];sib=table.getprevious()
            for _ in range(8):
                if sib is None:break
                preceding.append(clean(sib)[-700:]);sib=sib.getprevious()
            table_cache[tablepath]={'table_xpath':tablepath,'preceding':preceding,'opening_rows':[clean(n)[:1600] for n in table.xpath('./tr[position()<=4]|./tbody/tr[position()<=4]')]}
        cells=[clean(c) for c in tr.xpath('./td|./th')]
        item={'concept':name,'field':field or 'anchor_candidate','fact_id':f.get('id',''),'context_id':ctx,
              'value':str(amount) if amount is not None else None,'rounding_bound':str(bound) if bound is not None else None,
              'unit_ref':f.get('unitref',''),'unit_measures':units.get(f.get('unitref',''),[]),
              'currency':currency(units.get(f.get('unitref',''),[])), 'parse_status':status,
              'raw_text':clean(f),'attributes':dict(f.attrib)}
        if anchor_candidate:
            anchors.append({**item,'row_xpath':xpath,'cells':cells,'table_xpath':tablepath})
        if field:
            key=(xpath,ctx)
            row=rows.setdefault(key,{'source_observation_id':'SRC-'+hashlib.sha256((sha+'|'+xpath+'|'+ctx).encode()).hexdigest()[:20],
              'row_xpath':xpath,'table_xpath':tablepath,'context_id':ctx,'context':context,'cells':cells,'facts':[]})
            row['facts'].append(item);concepts[name]=concepts.get(name,0)+1
    candidates=[r for r in rows.values() if any(f['field']=='fair_value' for f in r['facts'])]
    # Keep all candidates, including apparent aggregates, repeated presentations and conflicts.
    for r in candidates:
        r['review_status']='unreviewed_source_candidate'
        first=next((c for c in r['cells'] if c),'')
        r['total_word_flag']=bool(re.match(r'^(?:total|subtotal)\b',first,re.I))
        r['numeric_conflicts']=[field for field in FIELDS.values() if len({(f['value'],f['currency']) for f in r['facts'] if f['field']==field})>1]
    assert (st.st_size,st.st_mtime_ns)==(path.stat().st_size,path.stat().st_mtime_ns),'source changed'
    return {'path':path.as_posix(),'sha256':sha,'bytes':st.st_size,'mtime_ns':st.st_mtime_ns,
      'report_date':report_date,'source_contexts':len(contexts),'source_candidates':candidates,
      'anchor_candidates':anchors,'tables':list(table_cache.values()),'concept_counts':concepts,
      'rejected_facts':rejected,'status':'source_candidates_require_review; not acceptance labels'}
