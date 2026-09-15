"""Visible zero transforms and exact large-value citation matching."""
import json

import duckdb
import pytest
from lxml import etree

from pipeline.history_evidence import inline_date,inline_records
from pipeline.holdings_history import export_history
from pipeline.holdings_finalizer import project_artifact
from tests.test_holdings_finalizer import holdings


def inline_document(text, fmt='', scale='0', extra=''):
    return '''<html><head><meta charset="utf-8"></head><body>
      <xbrli:context id="c1"><xbrli:period><xbrli:instant>2026-03-31</xbrli:instant>
      </xbrli:period></xbrli:context><table><tr><td>
      <ix:nonfraction name="us-gaap:InvestmentOwnedAtFairValue" contextRef="c1"
      unitRef="USD" format="'''+fmt+'" scale="'+scale+'" '+extra+'>'+text+'''</ix:nonfraction>
      </td></tr></table></body></html>'''


@pytest.mark.parametrize('fmt,text,eligible', [
    ('ixt:fixed-zero','\u2014',True),
    ('ixt:fixed-zero','not applicable',True),
    ('ixt:fixed-zero','',False),
    ('ixt:zerodash','-',True),
    ('ixt:zerodash','\u2013',True),
    ('ixt:zerodash','\ufe63',True),
    ('ixt:zerodash','7',False),
    ('ixt:zerodash','--',False),
    ('','\u2014',False),
    ('ixt:num-dot-decimal','\u2014',False),
    ('unknown:unsupported','0',False),
])
def test_zero_needs_declared_valid_transform_and_visible_text(fmt,text,eligible):
    tree=etree.fromstring(inline_document(text,fmt,scale='6').encode('utf-8'),etree.HTMLParser())
    record=inline_records(tree,'source')[0]
    assert record['eligible'] is eligible
    if eligible:
        assert record['number']=='0'
        assert record['text']==text


@pytest.mark.parametrize('extra', ['xsi:nil="true"','sign="-"'])
def test_zero_transform_preserves_nil_and_negative_zero_contract(extra):
    tree=etree.fromstring(inline_document('-', 'ixt:zerodash', extra=extra).encode(),etree.HTMLParser())
    record=inline_records(tree,'source')[0]
    assert record['eligible'] is ('nil' not in extra)
    assert float(record['number'])==0


@pytest.mark.parametrize('value,text,fmt,scale,expected', [
    (2031871000.0,'2,031,871','ixt:num-dot-decimal','3',True),
    (2002500000.0,'2,002,500','ixt:num-dot-decimal','3',True),
    (-2031871000.0,'(2,031,871)','ixt:num-dot-decimal','3',True),
    (2031871000.01,'2,031,871','ixt:num-dot-decimal','3',False),
    (0.0,'\u2014','ixt:fixed-zero','6',True),
    (0.0,'\u2014','ixt:zerodash','6',True),
    (1.0,'\u2014','ixt:fixed-zero','6',False),
    (0.0,'\u2014','','6',False),
])
def test_complete_export_links_exact_large_amounts_and_declared_zeros(tmp_path,value,text,fmt,scale,expected):
    cache=tmp_path/'cache/123';cache.mkdir(parents=True)
    (cache/'001.html').write_text(inline_document(text,fmt,scale),encoding='utf-8')
    frame=holdings([dict(row_id='R',position_id='P',cik='0000000123',accession_number='001',
        report_date='2026-03-31',fair_value=value,src_context_id='c1')])
    hp=tmp_path/'private_markets_holdings.csv'
    project_artifact(frame,'private_markets_holdings.csv').to_csv(hp,index=False)
    with duckdb.connect() as con:
        result=export_history(con,hp,tmp_path/'history',cohort={'0000000123'},
            source_cache=cache.parent,release_id='release')
    payload=json.loads((tmp_path/'history/0000000123/2026-03-31.json').read_text(encoding='utf-8'))
    evidence=(payload['rows'][0]['evidence'] or {}).get('fair_value')
    assert bool(evidence) is expected
    assert payload['rows'][0]['fair_value']==value
    assert result['accessible_holdings_difference']==0
    if expected:
        assert evidence['status']=='direct' and evidence['source_text']==text


@pytest.mark.parametrize('text,fmt,expected', [
    ('2/29/2032','date-month-day-year','2032-02-29'),
    ('10/29/32','date-month-day-year','2032-10-29'),
    ('1.2.99','datemonthdayyear','2099-01-02'),
    ('1/2/9','date-month-day-year','2009-01-02'),
    ('4/2/2032','date-month-day-year','2032-04-02'),
    ('11/12/2031','date-month-day-year','2031-11-12'),
    ('7/7/2028','date-month-day-year','2028-07-07'),
    ('2032-02-29','','2032-02-29'),
    ('2032/02/29','date-year-month-day','2032-02-29'),
    ('2/29/2031','date-month-day-year',None),
    ('29/10/2032','date-month-day-year',None),
    ('10/29/32','',None),
    ('10/2032','date-month-year',None),
    ('2032','',None),
    ('2032-02-29','unsupported-date',None),
    ('1/2/032','date-month-day-year',None),
    ('','date-month-day-year',None),
])
def test_declared_date_order_and_precision(text,fmt,expected):
    assert inline_date(text,fmt)==expected


@pytest.mark.parametrize('text,fmt,retained,expected', [
    ('2/29/2032','ixt:date-month-day-year','2032-02-29',True),
    ('10/29/32','ixt:date-month-day-year','2032-10-29',True),
    ('10/29/32','ixt:date-month-day-year','2032-10-28',False),
    ('10/29/32','','2032-10-29',False),
    ('10/2032','ixt:date-month-year','2032-10-31',False),
    ('2/29/2031','ixt:date-month-day-year','2031-02-28',False),
    ('2032-02-29','','2032-02-29',True),
    ('10/29/32','ixt:date-month-day-year',None,False),
])
def test_export_date_citation_matches_the_retained_complete_date(tmp_path,text,fmt,retained,expected):
    html=inline_document(text,fmt).replace('InvestmentOwnedAtFairValue','InvestmentMaturityDate')
    html=html.replace('nonfraction','nonnumeric').replace('unitRef="USD"','').replace('scale="0"','')
    cache=tmp_path/'cache/123';cache.mkdir(parents=True)
    (cache/'001.html').write_text(html,encoding='utf-8')
    frame=holdings([dict(row_id='R',position_id='P',cik='0000000123',accession_number='001',
        report_date='2026-03-31',maturity_date=retained,src_context_id='c1')])
    hp=tmp_path/'private_markets_holdings.csv'
    project_artifact(frame,'private_markets_holdings.csv').to_csv(hp,index=False)
    with duckdb.connect() as con:
        result=export_history(con,hp,tmp_path/'history',cohort={'0000000123'},
            source_cache=cache.parent,release_id='release')
    payload=json.loads((tmp_path/'history/0000000123/2026-03-31.json').read_text(encoding='utf-8'))
    evidence=(payload['rows'][0]['evidence'] or {}).get('maturity_date')
    assert bool(evidence) is expected
    assert payload['rows'][0]['maturity_date']==retained
    assert result['accessible_holdings_difference']==0
    if expected:
        assert evidence['status']=='direct' and evidence['source_text']==text


@pytest.mark.parametrize('head', [
    '<head></head>',
    '<head><meta charset="windows-1252"></head>',
    '<head><meta http-equiv="Content-Type" content="text/html; charset=iso-8859-1"></head>',
    '',
])
def test_rendition_declares_its_actual_encoding_and_preserves_visible_glyphs(head):
    from scripts.programme_closeout.citation_viewer import sanitize
    source=('<html>'+head+'<body><span id="target">&#8212; caf&#233;</span></body></html>').encode('ascii')
    tree=etree.ElementTree(etree.fromstring(source,etree.HTMLParser()))
    expected=tree.find('.//span').text
    sanitize(tree)
    rendered=etree.tostring(tree,encoding='utf-8',method='html')
    reread=etree.fromstring(rendered,etree.HTMLParser())
    assert reread.find('.//span').text==expected
    declarations=reread.xpath('//meta[@charset]')
    assert len(declarations)==1 and declarations[0].get('charset')=='utf-8'
    assert b'charset="utf-8"' in rendered[:1024]
