import json

import duckdb

from pipeline.holdings_history import export_history
from pipeline.holdings_finalizer import project_artifact
from tests.test_holdings_finalizer import holdings
from tests.test_citation_resolver import fixture


def test_history_distinguishes_foreign_disclosure_from_absent_usd_value(tmp_path):
    from pipeline.financial_conventions import prepare
    frame=holdings([dict(row_id='foreign',position_id='P1',fair_value='176106000',fair_value_currency='GBP',
        cik='0000000123',cost='')])
    prepared,_=prepare(frame,source_frame=True)
    hp=tmp_path/'private_markets_holdings.csv'
    project_artifact(prepared,'private_markets_holdings.csv').to_csv(hp,index=False)
    with duckdb.connect() as con:
        result=export_history(con,hp,tmp_path/'history',cohort={'0000000123'},release_id='release')
    payload=json.loads((tmp_path/'history/0000000123/2026-03-31.json').read_text(encoding='utf-8'))
    row=payload['rows'][0]
    assert row['fair_value'] is None and row['fair_value_currency']=='GBP'
    assert row['evidence']['fair_value']==dict(status='unavailable',release_id='release',row_id='foreign',
        field='fair_value',reason='FX_unavailable',source_amount='176106000',source_currency='GBP')
    assert result['rows']==1 and result['accessible_holdings_difference']==0


def test_history_labels_converted_fv_as_calculation_and_retains_quote_inputs(tmp_path):
    from pipeline.financial_conventions import prepare
    from tests.test_financial_conventions import fx_fixture
    sample,decision,quote=fx_fixture()
    frame=holdings([sample.iloc[0].to_dict()])
    prepared,_=prepare(frame,source_frame=True,fx_quotes=[quote],unit_adjudications=[decision])
    hp=tmp_path/'private_markets_holdings.csv'
    project_artifact(prepared,'private_markets_holdings.csv').to_csv(hp,index=False)
    with duckdb.connect() as con:
        result=export_history(con,hp,tmp_path/'history',cohort={'0000000123'},release_id='release')
    payload=json.loads((tmp_path/'history/0000000123/2026-03-31.json').read_text(encoding='utf-8'))
    row=payload['rows'][0]
    assert row['fair_value']==120 and row['fair_value_currency']=='USD'
    evidence=row['evidence']['fair_value']
    assert evidence['status']=='calculated' and evidence['input']['status']=='unavailable'
    assert evidence['calculation']['source_value']=='80'
    assert evidence['calculation']['conversion']['quote_id']=='synthetic-quote'
    assert result['accessible_holdings_difference']==0


def test_zero_fx_result_cannot_masquerade_as_direct_usd_source_fact(tmp_path):
    from pipeline.financial_conventions import prepare
    from tests.test_financial_conventions import fx_fixture
    from tests.test_history_numeric_citations import inline_document
    sample,decision,quote=fx_fixture(amount='0',currency='USD')
    decision['currency']='GBP'
    sample['src_context_id']='c1';sample['accession_number']='001'
    prepared,_=prepare(holdings([sample.iloc[0].to_dict()]),source_frame=True,
        fx_quotes=[quote],unit_adjudications=[decision])
    hp=tmp_path/'private_markets_holdings.csv'
    project_artifact(prepared,'private_markets_holdings.csv').to_csv(hp,index=False)
    cache=tmp_path/'cache/123';cache.mkdir(parents=True)
    (cache/'001.html').write_text(inline_document('0'),encoding='utf-8')
    with duckdb.connect() as con:
        result=export_history(con,hp,tmp_path/'history',cohort={'0000000123'},release_id='release',source_cache=cache.parent)
    row=json.loads((tmp_path/'history/0000000123/2026-03-31.json').read_text(encoding='utf-8'))['rows'][0]
    assert row['fair_value']==0
    assert row['evidence']['fair_value']['status']=='calculated'
    assert result['evidence']['direct_fields']==0


def test_inline_history_links_only_exact_selected_source_period_and_value(tmp_path):
    _,_,source=fixture(tmp_path)
    cache=tmp_path/"cache"/"123";cache.mkdir(parents=True)
    (cache/"001.html").write_bytes(source.read_bytes())
    frame=holdings([
        dict(row_id="correct",position_id="P1",fair_value="100",report_date="2026-03-31",src_context_id="c1"),
        dict(row_id="prior",position_id="P1",fair_value="100",report_date="2025-12-31",src_context_id="prior"),
        dict(row_id="wrong_period",position_id="P2",fair_value="100",report_date="2026-03-31",src_context_id="prior"),
        dict(row_id="changed_value",position_id="P3",fair_value="105",report_date="2026-03-31",src_context_id="c1"),
        dict(row_id="amended",position_id="P4",fair_value="100",report_date="2026-03-31",src_context_id="c1",accession_number="002"),
    ])
    frame["cik"]="0000000123"
    frame.loc[frame.row_id!="amended","accession_number"]="001"
    hp=tmp_path/"private_markets_holdings.csv";project_artifact(frame,"private_markets_holdings.csv").to_csv(hp,index=False)
    with duckdb.connect() as con:
        result=export_history(con,hp,tmp_path/"history",cohort={"0000000123"},source_cache=cache.parent,release_id="release")
    assert result["accessible_holdings_difference"]==0
    assert result["evidence"]["direct_fields"]==2
    payload=json.loads((tmp_path/"history/0000000123/2026-03-31.json").read_text())
    rows={r["row_id"]:r for r in payload["rows"]}
    assert rows["correct"]["evidence"]["fair_value"]["status"]=="direct"
    assert rows["correct"]["evidence"]["fair_value"]["release_id"]=="release"
    assert all(not rows[name]["evidence"] for name in ("wrong_period","changed_value","amended"))


def test_duplicate_facts_and_hidden_inline_facts_never_create_links(tmp_path):
    _,_,source=fixture(tmp_path)
    html=source.read_text().replace("<table>","""<ix:hidden><ix:nonfraction name="us:InvestmentOwnedAtCost"
        contextRef="c1" unitRef="USD">50</ix:nonfraction></ix:hidden><table>
        <ix:nonfraction name="us:InvestmentOwnedAtFairValue" contextRef="c1" unitRef="USD">100</ix:nonfraction>""")
    cache=tmp_path/"cache/123";cache.mkdir(parents=True);(cache/"001.html").write_text(html)
    frame=holdings([dict(row_id="R",position_id="P",cik="0000000123",accession_number="001",
        report_date="2026-03-31",fair_value="100",cost="50",src_context_id="c1")])
    hp=tmp_path/"private_markets_holdings.csv";project_artifact(frame,"private_markets_holdings.csv").to_csv(hp,index=False)
    with duckdb.connect() as con:
        result=export_history(con,hp,tmp_path/"history",cohort={"0000000123"},source_cache=cache.parent)
    assert result["evidence"]["direct_fields"]==0
    assert not list((tmp_path/"history/0000000123/sources").glob("*.html"))


def test_bulk_inference_and_cost_donor_are_bound_to_observation_and_release(tmp_path):
    from tests.test_sector_enrichment import bundle
    path,taxonomy,_=bundle(tmp_path)
    audit=tmp_path/'sector_audit.csv'
    audit.write_text('row_id,decision_id,status\nR1,D1,applied\nR2,D1,applied\nR3,D1,applied\n')
    donors=tmp_path/'cost_donors.csv'
    donors.write_text('row_id,method,donor_row_id,donor_date,donor_release\n'
        'R2,first_observed_fv_proxy,R1,2025-12-31,release\n'
        'R3,first_observed_fv_proxy,R1,2025-12-31,other-release\n'
        'R4,first_observed_fv_proxy,R1,2025-12-31,release\n')
    frame=holdings([
        dict(row_id='R1',position_id='P1',report_date='2025-12-31',fair_value='0',cost='0'),
        dict(row_id='R2',position_id='P1',report_date='2026-03-31',fair_value='10',cost='0',cost_source='first_observed_fv_proxy'),
        dict(row_id='R3',position_id='P2',report_date='2026-03-31',fair_value='10',cost='0',cost_source='first_observed_fv_proxy'),
        dict(row_id='R4',position_id='P3',report_date='2026-03-31',fair_value='10',cost='0',cost_source='first_observed_fv_proxy'),
    ])
    frame['cik']='0000000123';frame['canonical_name']='Acme';frame['issuer_name']='Acme'
    frame['gics_sub_industry']='Application Software'
    frame.loc[frame.row_id=='R3','canonical_name']='Changed borrower'
    hp=tmp_path/'private_markets_holdings.csv';project_artifact(frame,'private_markets_holdings.csv').to_csv(hp,index=False)
    with duckdb.connect() as con:
        result=export_history(con,hp,tmp_path/'history',cohort={'0000000123'},release_id='release',
            sector_bundle=path,sector_audit=audit,taxonomy=taxonomy,cost_donors=donors)
    payload=json.loads((tmp_path/'history/0000000123/2026-03-31.json').read_text())
    rows={r['row_id']:r for r in payload['rows']}
    assert rows['R2']['evidence']['cost']['status']=='calculated'
    assert rows['R2']['evidence']['cost']['donor_row_id']=='R1'
    assert rows['R2']['evidence']['cost']['input']['status']=='unavailable'
    assert rows['R2']['evidence']['gics_sub_industry']['status']=='inferred'
    assert not rows['R3']['evidence'] and not rows['R4']['evidence']
    assert result['evidence_path_or_unavailable']==1
    assert sum(result['evidence_statuses'].values())==result['evidence_field_population']
