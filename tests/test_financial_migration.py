import json

import pandas as pd
import pytest

from pipeline import holdings_finalizer,index_returns
from pipeline.financial_finalization import prepare_artifact
from pipeline.programme.core import sha
from tests.test_holdings_finalizer import holdings
from tests.test_position_matching import _make_bdc_raw
from tests.test_index_returns import _make_matches,_compute


def test_final_writer_rate_income_donors_and_registry_replay_are_one_contract(tmp_path,monkeypatch):
    frame=holdings([
        dict(row_id='R1',report_date='2025-12-31',cost='0',fair_value='100',principal_amount='100'),
        dict(row_id='R2',report_date='2026-03-31',cost='',fair_value='110',principal_amount='100')])
    frame['interest_rate']='10';frame['interest_rate_kind']='cash';frame['pik_rate']='2'
    frame['src_context_id']=['C1','C2'];frame['entity_id']='E1'
    frame['fair_value_source']='xbrl_field'
    frame,_=prepare_artifact(frame,tmp_path,source_frame=True)
    hp=tmp_path/'private_markets_holdings.csv';frame.to_csv(hp,index=False)
    result,matches=holdings_finalizer.finalize_existing_holdings(holdings_file=hp,bdc_raw_df=_make_bdc_raw([]))
    assert result.position_id.nunique()==1 and result.interest_rate.eq(12).all()
    assert result.set_index('row_id').loc['R1','cost']==0
    assert result.set_index('row_id').loc['R2','cost']==100
    assert matches.begin_interest_rate.eq(12).all()
    monkeypatch.setattr(index_returns,'POSITION_RETURNS_FILE',tmp_path/'position_returns.csv')
    monkeypatch.setattr(index_returns,'INDEX_RETURNS_FILE',tmp_path/'index_returns.csv')
    returns,_=index_returns.compute_returns(matches,fee_uplift_df=pd.DataFrame(columns=['cik','quarter','effective_uplift']),
        unified_pik_df=result[['cik','source','report_date','position_id','pik_rate']])
    assert len(returns)==1 and returns.iloc[0].income_return==pytest.approx(.03)
    registry_hash=sha(tmp_path/'identity_registry.duckdb')
    replay,_=holdings_finalizer.finalize_existing_holdings(holdings_file=hp,bdc_raw_df=_make_bdc_raw([]))
    assert result.set_index('row_id').position_id.to_dict()==replay.set_index('row_id').position_id.to_dict()
    assert (tmp_path/'identity_registry_history'/(registry_hash+'.duckdb')).is_file()
    release=json.loads((tmp_path/'holdings_release.json').read_text())
    assert release['holdings_sha256']==sha(hp)
    assert pd.read_csv(tmp_path/'cost_donor_audit.csv').dropna(subset=['donor_release']).donor_release.eq(release['release_id']).all()


def test_unavailable_coupon_stays_null_and_zero_coupon_is_observed(tmp_path,monkeypatch):
    monkeypatch.setattr(index_returns,'POSITION_RETURNS_FILE',tmp_path/'position_returns.csv')
    monkeypatch.setattr(index_returns,'INDEX_RETURNS_FILE',tmp_path/'index_returns.csv')
    base=dict(cik='123',source='bdc',index_classification='DIRECT_LENDING',begin_quarter='2025q4',end_quarter='2026q1',
        begin_report_date='2025-12-31',end_report_date='2026-03-31',begin_fair_value='1000',end_fair_value='1000',
        begin_principal_amount='1000',span_months='3',begin_basis_spread='5')
    pairs=_make_matches([dict(base,begin_issuer_name='Same borrower',position_id=p,begin_interest_rate=r)
        for p,r in [('unknown',None),('zero','0'),('observed','12')]])
    pik=pd.DataFrame([dict(cik='123',source='bdc',report_date='2025-12-31',position_id=p,pik_rate=2)
        for p in ('unknown','zero','observed')])
    result,_=_compute(pairs,unified_pik_df=pik)
    values=result.set_index('position_id')
    assert len(result)==3
    assert pd.isna(values.loc['unknown','income_rate']) and pd.isna(values.loc['unknown','income_return'])
    assert pd.isna(values.loc['unknown','total_return'])
    assert values.loc['zero','income_return']==0
    assert values.loc['observed','income_return']==pytest.approx(.03)
