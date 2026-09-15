import json

import pandas as pd
import pytest

from pipeline.financial_context import compatible_nav
from pipeline.programme.core import sha


def test_nav_requires_same_cik_date_usd_and_unambiguous_latest_source(tmp_path):
    cache=tmp_path/'cache';cache.mkdir()
    facts={'cik':123,'facts':{'us-gaap':{'StockholdersEquity':{'units':{'USD':[
        {'end':'2025-12-31','filed':'2026-02-01','val':95},
        {'end':'2025-12-31','filed':'2026-05-01','val':100},
        {'end':'2026-03-31','filed':'2026-05-01','val':200},
        {'end':'2026-03-31','filed':'2026-05-01','val':201}],
        'EUR':[{'end':'2026-06-30','filed':'2026-08-01','val':300}]}}}}}
    (cache/'0000000123.json').write_text(json.dumps(facts))
    frame=pd.DataFrame([dict(cik='0000000123',report_date=date,source='companyfacts',net_assets=value)
        for date,value in [('2025-12-31',100),('2026-03-31',200),('2026-06-30',300)]])
    ff=tmp_path/'fund_financials.csv';frame.to_csv(ff,index=False)
    nav,audit=compatible_nav(frame.assign(source='bdc'),ff,cache)
    assert len(nav)==1 and nav.iloc[0].net_assets==100
    assert audit.set_index('report_date').status.to_dict()=={'2025-12-31':'compatible',
        '2026-03-31':'ambiguous_latest_source_nav','2026-06-30':'no_cached_usd_nav'}


def test_no_source_facts_never_turn_fund_summary_into_evidence(tmp_path):
    frame=pd.DataFrame([dict(cik='0000000123',report_date='2026-03-31',source='companyfacts',net_assets=100)])
    ff=tmp_path/'fund_financials.csv';frame.to_csv(ff,index=False)
    nav,audit=compatible_nav(frame.assign(source='bdc'),ff,tmp_path/'missing_cache')
    assert nav.empty
    assert audit.iloc[0].status=='no_cached_usd_nav'


@pytest.mark.parametrize('declared_cik', [None, ''])
def test_missing_source_cik_is_unavailable_without_using_its_facts(tmp_path,declared_cik):
    cache=tmp_path/'cache';cache.mkdir()
    source={'entityName':'Matching fund name','facts':{'us-gaap':{'StockholdersEquity':{
        'units':{'USD':[{'end':'2026-03-31','filed':'2026-05-01','val':100}]}}}}}
    if declared_cik is not None:
        source['cik']=declared_cik
    path=cache/'0000000123.json';path.write_text(json.dumps(source))
    valid=cache/'0000000456.json'
    valid.write_text(json.dumps(dict(source,cik=456)))
    frame=pd.DataFrame([dict(cik=cik,report_date='2026-03-31',source='companyfacts',net_assets=100)
                        for cik in ['0000000123','0000000456']])
    ff=tmp_path/'fund_financials.csv';frame.to_csv(ff,index=False)
    nav,audit=compatible_nav(frame.assign(source='bdc'),ff,cache)
    assert nav.cik.tolist()==['0000000456']
    rejected=audit.set_index('cik').loc['0000000123']
    assert rejected.status=='source_cik_missing'
    assert rejected.source_sha256==sha(path)
    assert audit.set_index('cik').loc['0000000456'].status=='compatible'
    assert json.loads(path.read_text())==source


def test_explicitly_different_source_cik_still_blocks(tmp_path):
    cache=tmp_path/'cache';cache.mkdir()
    (cache/'0000000123.json').write_text(json.dumps({'cik':456,'facts':{}}))
    frame=pd.DataFrame([dict(cik='0000000123',report_date='2026-03-31',source='companyfacts',net_assets=100)])
    ff=tmp_path/'fund_financials.csv';frame.to_csv(ff,index=False)
    with pytest.raises(ValueError,match='expected 0000000123, declared 456'):
        compatible_nav(frame.assign(source='bdc'),ff,cache)
