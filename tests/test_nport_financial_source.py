import json

import pandas as pd

from pipeline.financial_conventions import prepare,cost_proxies
from pipeline.staging_nport import _prepare_nport
from tests.test_unified_holdings import TestPrepareNport as _NportFixture


def test_nport_usd_value_is_independent_of_foreign_principal_and_can_supply_donor():
    raw=_NportFixture()._make_nport_df([dict(cik='123',holding_id='H1',
        issuer_name='Alpha Ltd',issuer_title='Senior Loan',asset_cat='DBT',issuer_type='CORP',
        currency_value=1100,balance=1000,unit='PA',currency_code='EUR',exchange_rate=.9,
        report_date='2026-03-31',accession_number='0000000123-26-000001')])
    staged=_prepare_nport(raw)
    assert len(staged)==1
    assert staged.iloc[0].fair_value==1100 and staged.iloc[0].fair_value_currency=='USD'
    assert staged.iloc[0].principal_amount_currency=='EUR'
    assert staged.iloc[0].fair_value_source=='nport'
    assert json.loads(staged.iloc[0].src_facts)['fair_value']['source_item']=='N-PORT C.2.c'
    staged['row_id']='R1';staged['position_id']='P1'
    prepared,states=prepare(staged)
    assert bool(states.iloc[0].donor_valid)
    final,audit=cost_proxies(prepared,states,release_id='test-release')
    assert final.iloc[0].cost==1100 and pd.isna(final.iloc[0].cost_reported)
    assert audit.iloc[0].donor_row_id=='R1' and audit.iloc[0].method=='first_observed_fv_proxy'
    # An independently flagged correction still disqualifies the value.
    staged['corrected_fields']='fair_value'
    _,states=prepare(staged)
    assert not bool(states.iloc[0].donor_valid)


def test_nport_value_without_source_holding_identifier_is_not_a_donor():
    raw=_NportFixture()._make_nport_df([dict(cik='123',holding_id='',issuer_name='Alpha Ltd',
        asset_cat='DBT',issuer_type='CORP',currency_value=1100,report_date='2026-03-31')])
    staged=_prepare_nport(raw)
    staged['row_id']='R1';staged['position_id']='P1'
    _,states=prepare(staged)
    assert len(states)==1 and not bool(states.iloc[0].donor_valid)
