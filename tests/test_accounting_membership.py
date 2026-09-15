import duckdb
import pandas as pd
import pytest

from pipeline.accounting_membership import build
from pipeline.programme.core import ContractError,sha


def fixture(tmp_path,basis='investments_ex_cash',kind='fund_financials'):
    holdings=tmp_path/'holdings.csv';anchors=tmp_path/'anchors.csv'
    rows=[dict(row_id=rid,cik='123',report_date='2026-03-31',accounting_scope_id=scope,
        accounting_record_class=record_class,fair_value=value,fair_value_currency=currency,index_classification=category)
        for rid,scope,record_class,value,currency,category in [
            ('p','123|parent','parent_schedule',100,'USD','DIRECT_LENDING'),
            ('j','123|jv','underlying_schedule',-20,'USD','DIRECT_LENDING'),
            ('cash','123|parent','parent_schedule',5,'USD','CASH'),
            ('zero','123|parent','parent_schedule',0,'USD','DIRECT_LENDING')]]
    pd.DataFrame(rows).to_csv(holdings,index=False)
    pd.DataFrame([dict(cik='123',quarter='2026-03-31',anchor_basis=basis,anchor_kind=kind,currency='USD',
                      source_evidence='source#sha256='+'a'*64)]).to_csv(anchors,index=False)
    return holdings,anchors


def test_parent_membership_preserves_signed_public_rows_separately(tmp_path):
    holdings,anchors=fixture(tmp_path)
    before=sha(holdings)
    with duckdb.connect() as con:
        build(con,release_id='R1',holdings=holdings,anchors=anchors)
        memberships=dict(con.execute('SELECT row_id,membership FROM accounting_membership').fetchall())
        totals=con.execute('SELECT retained_fair_value,included_fair_value,excluded_fair_value FROM accounting_anchor_summaries').fetchone()
    assert memberships==dict(p='included',j='excluded',cash='excluded',zero='included')
    assert totals==(85,100,-15) and sha(holdings)==before


def test_declared_published_anchor_includes_all_retained_scopes_and_signs(tmp_path):
    holdings,anchors=fixture(tmp_path,basis='published_rows')
    with duckdb.connect() as con:
        build(con,release_id='R1',holdings=holdings,anchors=anchors)
        assert con.execute("SELECT count(*) FROM accounting_membership WHERE membership='included'").fetchone()[0]==4


def test_missing_source_kind_cannot_create_comparable_membership(tmp_path):
    holdings,anchors=fixture(tmp_path,kind='schedule_total')
    with duckdb.connect() as con:
        build(con,release_id='R1',holdings=holdings,anchors=anchors)
        assert con.execute("SELECT count(*) FROM accounting_membership WHERE membership='unknown'").fetchone()[0]==4


def test_currency_unknown_does_not_become_included_or_zero(tmp_path):
    holdings,anchors=fixture(tmp_path)
    frame=pd.read_csv(holdings);frame.loc[frame.row_id=='p','fair_value_currency']='UNRESOLVED';frame.to_csv(holdings,index=False)
    with duckdb.connect() as con:
        build(con,release_id='R1',holdings=holdings,anchors=anchors)
        assert con.execute("SELECT membership,reason FROM accounting_membership WHERE row_id='p'").fetchone()==('unknown','currency_not_comparable')
        assert con.execute('SELECT unknown_absolute_fair_value FROM accounting_anchor_summaries').fetchone()[0]==100


def test_repeated_observation_cannot_duplicate_anchor_membership(tmp_path):
    holdings,anchors=fixture(tmp_path)
    frame=pd.read_csv(holdings);pd.concat([frame,frame.iloc[:1]]).to_csv(holdings,index=False)
    with duckdb.connect() as con,pytest.raises(ContractError,match='unique observation'):
        build(con,release_id='R1',holdings=holdings,anchors=anchors)
