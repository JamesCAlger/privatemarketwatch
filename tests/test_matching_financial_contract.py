import pandas as pd
import pytest

from pipeline.position_matching import match_positions,assign_position_ids
from tests.test_position_matching import _make_bdc_raw,_make_unified


def pair():
    base=dict(source='bdc',cik='0000000123',entity_name='Fund',issuer_name='Acme Corp',
        index_classification='DIRECT_LENDING',asset_category='LOAN',cost='900',fair_value='1000',
        interest_rate='12',basis_spread='5',maturity_date='2030-06-30')
    frame=_make_unified([dict(base,report_date='2025-12-31',principal_amount='1000'),
        dict(base,report_date='2026-03-31',principal_amount='3000',basis_spread='9')])
    frame['row_id']=['R1','R2'];frame['row_id_basis']='src_anchor'
    return frame


@pytest.mark.parametrize('precision,date,expected',[
    ('month','2030-06-05',True),('year','2030-02-01',True),
    ('day','2030-06-05',False),('month','2030-07-01',False),('unknown','2033-01-01',True)])
def test_contested_maturity_uses_disclosure_intervals(tmp_path,precision,date,expected):
    frame=pair();frame['maturity_precision']=[precision,'day'];frame.loc[1,'maturity_date']=date
    result=match_positions(frame,_make_bdc_raw([]),contested_assignment=True,output_file=tmp_path/'matches.csv')
    # This is the contested B2 veto; C/D retain their separately governed
    # 365-day interval-gap allowance.
    assert ((result.match_method=='B2_exact_name').sum()==1)==expected


def test_matching_cost_is_reported_and_scope_never_crosses(tmp_path):
    frame=pair();frame['cost_reported']=['0','80'];frame['maturity_precision']='day'
    result=match_positions(frame,_make_bdc_raw([]),contested_assignment=True,output_file=tmp_path/'matches.csv')
    assert result.iloc[0].begin_cost==0 and result.iloc[0].end_cost==80
    frame['is_subsidiary']=['0','1'];frame['jv_subsidiary']='Y'
    rejected=match_positions(frame,_make_bdc_raw([]),contested_assignment=True,output_file=tmp_path/'scoped.csv')
    assert rejected.empty
    # Even a cached Tier-A pair from before scope enforcement cannot merge IDs.
    assigned,kept=assign_position_ids(frame,result,contested_assignment=True,edges_file=tmp_path/'edges.csv')
    assert assigned.position_id.nunique()==2 and kept.empty
