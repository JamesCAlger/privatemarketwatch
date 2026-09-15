import json

import duckdb
import pandas as pd
import pytest

from pipeline.primary_anchor_evidence import collect_overrides
from pipeline.programme.core import ContractError,sha


def fixture(tmp_path, *, total=100, basis='investments_ex_cash', rows=None):
    folder=tmp_path/'anchors/123';folder.mkdir(parents=True)
    leaf=folder/'2026-03-31.json'
    leaf.write_text(json.dumps(dict(cik='123',target_quarter='2026-03-31',grand_total=total,basis=basis,
        method='total_row',evidence=[dict(quote='A dollar sign alone is insufficient')],components=[])))
    financials=tmp_path/'financials.csv'
    pd.DataFrame(rows or [dict(cik='123',report_date='2026-03-31',source='companyfacts',
                             investments_at_fair_value=100,cash_equivalents_at_fair_value=5)]).to_csv(financials,index=False)
    return folder.parent,leaf,financials


@pytest.mark.parametrize('basis,total',[('investments_ex_cash',100),('published_rows',105)])
def test_override_currency_requires_same_basis_independent_source(tmp_path,basis,total):
    folder,leaf,financials=fixture(tmp_path,basis=basis,total=total)
    with duckdb.connect() as con:
        row=collect_overrides(con,folder,financials)[0]
    assert row['currency']=='USD' and row['override_agrees']
    assert sha(leaf) in row['source_evidence'] and sha(financials) in row['source_evidence']
    assert row['evidence_status']=='independent_total_agrees'


def test_schedule_label_and_nearby_value_do_not_certify_override(tmp_path):
    folder,leaf,financials=fixture(tmp_path,total=101)
    with duckdb.connect() as con:
        row=collect_overrides(con,folder,financials)[0]
    assert not row['override_agrees']
    assert row['evidence_status']=='override_disagrees_with_independent_total'


@pytest.mark.parametrize('source,quarter',[('schedule','2026-03-31'),('companyfacts','2025-12-31')])
def test_wrong_producer_or_period_cannot_supply_currency(tmp_path,source,quarter):
    folder,leaf,financials=fixture(tmp_path,rows=[dict(cik='123',report_date=quarter,source=source,
        investments_at_fair_value=100,cash_equivalents_at_fair_value=5)])
    with duckdb.connect() as con:
        row=collect_overrides(con,folder,financials)[0]
    assert row['currency']=='' and row['override_agrees'] is None


def test_conflicting_totals_are_not_selected_by_maximum(tmp_path):
    rows=[dict(cik='123',report_date='2026-03-31',source='companyfacts',investments_at_fair_value=v)
          for v in (99,100)]
    folder,leaf,financials=fixture(tmp_path,rows=rows)
    with duckdb.connect() as con:
        row=collect_overrides(con,folder,financials)[0]
    assert row['evidence_status']=='conflicting_independent_totals' and row['currency']==''


def test_published_basis_cannot_assume_missing_cash_is_zero(tmp_path):
    folder,leaf,financials=fixture(tmp_path,basis='published_rows',rows=[
        dict(cik='123',report_date='2026-03-31',source='companyfacts',investments_at_fair_value=100)])
    with duckdb.connect() as con:
        row=collect_overrides(con,folder,financials)[0]
    assert row['override_agrees'] is None and row['currency']==''


@pytest.mark.parametrize('claim,kind,currency',[(100,'verified_override','USD'),(101,'unverified_override','')])
def test_acceptance_adapter_writes_bound_evidence_and_membership(tmp_path,monkeypatch,claim,kind,currency):
    from scripts.run_production_acceptance import primary_evidence
    from scripts import shadow_conservation_engine as engine
    frozen=tmp_path/'frozen';output=tmp_path/'evaluation';output.mkdir()
    folder=frozen/'data/overrides/agent_anchor/123';folder.mkdir(parents=True)
    (folder/'2026-03-31.json').write_text(json.dumps(dict(cik='123',target_quarter='2026-03-31',
        grand_total=claim,basis='investments_ex_cash')))
    raw=frozen/'data/output/bdc_holdings.csv';raw.parent.mkdir(parents=True);raw.write_text('cik\n123\n')
    financials=frozen/'data/output/fund_financials.csv'
    pd.DataFrame([dict(cik='123',report_date='2026-03-31',source='companyfacts',
        investments_at_fair_value=100,cash_equivalents_at_fair_value=0)]).to_csv(financials,index=False)
    holdings=tmp_path/'holdings.csv'
    pd.DataFrame([dict(row_id='R1',cik='123',report_date='2026-03-31',accounting_scope_id='123|parent',
        accounting_record_class='parent_schedule',fair_value=100,fair_value_currency='USD',
        index_classification='DIRECT_LENDING')]).to_csv(holdings,index=False)
    def result(con,rule):
        con.execute('CREATE TABLE _cash_rows(cik VARCHAR,report_date VARCHAR)')
        con.execute("""CREATE TABLE result_fv_conservation AS SELECT '0000000123' AS cik,
          '2026-03-31' AS report_date,? AS anchor_value,100 AS value_sum,
          'verified_override_investments_ex_cash' AS anchor_used,'investments_ex_cash' AS anchor_basis,
          0.0 AS residual_pct,'reconciles' AS status""",[claim])
    monkeypatch.setattr(engine,'run_rule',result)
    primary_evidence(holdings,frozen,output,{'0000000123'})
    anchors=pd.read_csv(output/'primary_anchors.csv').fillna('')
    assert anchors.iloc[0].anchor_kind==kind and anchors.iloc[0].currency==currency
    membership=pd.read_parquet(output/'accounting_membership.parquet')
    assert len(membership)==1
    assert membership.iloc[0].membership==('included' if claim==100 else 'unknown')
