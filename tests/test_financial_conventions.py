import json

import duckdb
import pandas as pd
import pytest

from pipeline.financial_conventions import prepare,cost_proxies,maturity_interval_sql


def rows(*changes):
    base=dict(row_id="R1",cik="0000000123",report_date="2026-03-31",source="bdc",
        interest_rate="10",interest_rate_kind="cash",pik_rate="2",cost="100",fair_value="110",
        position_id="P1",src_context_id="C1",fair_value_source="xbrl_field",cost_currency="USD",fair_value_currency="USD",
        maturity_date="2030-06-15",maturity_date_source="xbrl_field",gics_sub_industry="Software",
        pct_of_net_assets="0.2")
    return pd.DataFrame([dict(base,**change) for change in (changes or ({},))])


def test_cash_plus_supported_pik_allin_and_effective_yield():
    result,_=prepare(rows({},dict(row_id="R2",interest_rate_kind="all_in",interest_rate="12"),
        dict(row_id="R3",interest_rate_kind="effective_yield"),dict(row_id="R4",pik_rate=""),
        dict(row_id="R5",pik_rate="0")))
    by_id=result.set_index("row_id")
    assert by_id.loc["R1","interest_rate"]==12
    assert by_id.loc["R2","interest_rate_cash"]==10
    assert pd.isna(by_id.loc["R3","interest_rate"])
    assert pd.isna(by_id.loc["R4","interest_rate"])
    assert by_id.loc["R4","interest_rate_cash"]==10
    assert by_id.loc["R5","interest_rate"]==10


def test_generic_rate_concept_does_not_establish_cash_convention():
    frame=rows(dict(interest_rate_kind="",src_facts=json.dumps({"interest_rate":{"c":"investmentinterestrate"}})),
        dict(row_id="R2",interest_rate_kind="",src_facts=json.dumps({"interest_rate":{"c":"investmentinterestratepaidincash"}})))
    result,_=prepare(frame)
    assert result.iloc[0].interest_rate_kind=="unresolved"
    assert pd.isna(result.iloc[0].interest_rate)
    assert result.iloc[1].interest_rate==12


def test_reported_zero_and_zero_donor_preserved_invalid_or_foreign_not_absent():
    prepared,states=prepare(rows(dict(row_id="zero",report_date="2025-12-31",cost="0",fair_value="0"),
        dict(row_id="absent",cost=""),dict(row_id="invalid",cost="invalid"),
        dict(row_id="foreign",cost="80",cost_currency="EUR")))
    result,audit=cost_proxies(prepared,states,release_id="release1")
    values=result.set_index("row_id")
    evidence=audit.set_index("row_id")
    assert values.loc["zero","cost"]==0 and values.loc["zero","cost_reported"]==0
    assert values.loc["absent","cost"]==0
    assert evidence.loc["absent","donor_row_id"]=="zero"
    assert evidence.loc["absent","donor_release"]=="release1"
    assert pd.isna(values.loc["invalid","cost"]) and evidence.loc["invalid","method"]=="invalid"
    assert pd.isna(values.loc["foreign","cost"]) and evidence.loc["foreign","method"]=="unresolved_currency"
    again,newstates=prepare(result,prior_states=states)
    replayed,again_audit=cost_proxies(again,newstates,release_id="release1")
    assert again_audit.set_index("row_id").loc["invalid","method"]=="invalid"
    assert replayed.set_index("row_id").loc["absent","cost"]==0
    assert replayed.set_index("row_id").loc["absent","interest_rate"]==12


def test_cost_never_crosses_position_or_ambiguous_earliest_donor():
    prepared,states=prepare(rows(dict(row_id="A",cost="",fair_value="",position_id="P2"),
        dict(row_id="B",cost="",report_date="2025-12-31",fair_value="10"),
        dict(row_id="C",cost="",report_date="2025-12-31",fair_value="20"),
        dict(row_id="D",cost="")))
    result,audit=cost_proxies(prepared,states,release_id="release")
    evidence=audit.set_index("row_id")
    assert evidence.loc["A","method"]=="no_source_valid_donor"
    assert evidence.loc["D","method"]=="ambiguous_earliest_donor"
    assert result.cost.isna().all()


@pytest.mark.parametrize('change', [
    {'fair_value_source':''}, {'src_context_id':''},
    {'corrected_fields':'fair_value'}, {'src_field_overrides':'fair_value=bridge:reviewed'},
    {'src_transforms':'fair_value:decimals_rescale'}, {'src_conflict_fields':'fair_value'},
    {'src_filled_fields':'fair_value'},
    {'src_facts':json.dumps({'fair_value':{'x':['decimals_rescale:10^-3']}})},
    {'src_facts':json.dumps({'fair_value':{'r':999}})},
    {'src_facts':json.dumps({'fair_value':{'disputed':True}})},
])
def test_unverified_fv_cannot_donate_despite_retained_source_anchor(change):
    prepared,states=prepare(rows(dict(cost='',**change)))
    result,audit=cost_proxies(prepared,states,release_id='release')
    assert not states.iloc[0].donor_valid
    assert pd.isna(result.iloc[0].cost)
    assert audit.iloc[0].method=='no_source_valid_donor'


def test_unrelated_field_correction_does_not_disqualify_observed_zero_fv():
    prepared,states=prepare(rows(dict(cost='',fair_value='0',corrected_fields='cost;interest_rate',
        src_transforms='interest_rate:rate_x100',
        src_facts=json.dumps({'fair_value':{'r':0},'interest_rate':{'x':['rate_x100']}}))))
    result,audit=cost_proxies(prepared,states,release_id='release')
    assert states.iloc[0].donor_valid and result.iloc[0].cost==0
    assert audit.iloc[0].method=='first_observed_fv_proxy'


def test_reported_nav_percent_separate_missing_accrual_and_month_precision():
    nav=pd.DataFrame([dict(cik="123",report_date="2026-03-31",net_assets=1000)])
    taxonomy=pd.DataFrame([dict(sub_industry="Software",sector="Information Technology")])
    result,_=prepare(rows(dict(maturity_date="2030-06-01",src_facts=json.dumps({"maturity_date":{"r":"2030-06"}}))),nav=nav,hierarchy=taxonomy)
    row=result.iloc[0]
    assert row.pct_of_net_assets=="0.2"
    assert row.pct_of_net_assets_calculated==11
    assert row.nonaccrual_status=="unknown"
    assert row.maturity_date=="2030-06-30" and row.maturity_precision=="month"
    assert row.maturity_status=="partial" and row.gics_sector=="Information Technology"
    low,high=maturity_interval_sql("'2030-06-30'","'month'")
    with duckdb.connect() as con:
        bounds=con.execute("SELECT "+low+","+high).fetchone()
    assert str(bounds[0]).startswith("2030-06-01") and str(bounds[1]).startswith("2030-06-30")


def test_missing_prior_states_blocks_reinterpreting_invalid_as_absent():
    result,_=prepare(rows(dict(cost="bad")))
    with pytest.raises(ValueError,match="retained field states"): prepare(result)


def test_invalid_cost_state_survives_numeric_staging_and_stale_audit_blocks():
    from pipeline.financial_conventions import raw_cost_state_sql
    with duckdb.connect() as con:
        facts=con.execute('SELECT '+raw_cost_state_sql("'invalid literal'","'{}'")).fetchone()[0]
    result,states=prepare(rows(dict(cost='',src_facts=facts)))
    assert states.iloc[0].cost_state=='invalid'
    final,audit=cost_proxies(result,states,release_id='release')
    assert pd.isna(final.iloc[0].cost) and audit.iloc[0].method=='invalid'
    final.loc[0,'interest_rate_reported']=99
    with pytest.raises(ValueError,match='disagree with reported values'):
        prepare(final,prior_states=states)


def test_raw_comparative_rates_are_replaced_by_final_position_values_not_borrower():
    from pipeline.financial_conventions import synchronize_matches
    final,_=prepare(rows(dict(row_id='A1',position_id='P1',report_date='2025-12-31'),
        dict(row_id='A2',position_id='P1',report_date='2026-03-31'),
        dict(row_id='B1',position_id='P2',report_date='2025-12-31',interest_rate='20',pik_rate='1'),
        dict(row_id='B2',position_id='P2',report_date='2026-03-31',interest_rate='20',pik_rate='1')))
    matched=pd.DataFrame([dict(cik='123',source='bdc',position_id=p,begin_report_date='2025-12-31',end_report_date='2026-03-31',
        begin_interest_rate='10',end_interest_rate='10',begin_cost='100',end_cost='100') for p in ('P1','P2','missing')])
    result=synchronize_matches(matched,final).set_index('position_id')
    assert result.loc['P1','begin_interest_rate']==12
    assert result.loc['P2','begin_interest_rate']==21
    assert pd.isna(result.loc['missing','begin_interest_rate'])
    assert len(result)==3


@pytest.mark.parametrize('currency,state',[('GBP','FX_unavailable'),('AUD','FX_unavailable'),('UNRESOLVED','unit_unresolved')])
@pytest.mark.parametrize('amount',['176106000','0','-12.25'])
def test_incompatible_fv_is_retained_as_source_but_never_usd_or_nav(currency,state,amount):
    nav=pd.DataFrame([dict(cik='123',report_date='2026-03-31',net_assets=1000)])
    result,states=prepare(rows(dict(fair_value=amount,fair_value_currency=currency,cost='')),nav=nav)
    row=result.iloc[0]
    assert pd.isna(row.fair_value) and pd.isna(row.pct_of_net_assets_calculated)
    assert row.fair_value_currency==currency
    assert json.loads(row.src_facts)['_financial_fair_value']==dict(raw=amount,currency=currency,state=state)
    assert not states.iloc[0].donor_valid
    replay,replayed_states=prepare(result,prior_states=states,nav=nav)
    assert json.loads(replay.iloc[0].src_facts)==json.loads(row.src_facts)
    assert pd.isna(replay.iloc[0].fair_value)
    final,donors=cost_proxies(replay,replayed_states,release_id='release')
    assert pd.isna(final.iloc[0].cost)


@pytest.mark.parametrize('fv_currency',['USD',''])
def test_foreign_principal_does_not_null_compatible_fv(fv_currency):
    result,_=prepare(rows(dict(fair_value='0',fair_value_currency=fv_currency,
        principal_currency='GBP',principal_amount='120',cost_currency='EUR')))
    assert result.iloc[0].fair_value==0
    assert result.iloc[0].principal_amount=='120'
    assert pd.isna(result.iloc[0].cost)


def test_raw_comparative_foreign_fv_cannot_reenter_returns_after_finalization():
    from pipeline.financial_conventions import synchronize_matches
    final,_=prepare(rows(dict(report_date='2025-12-31',fair_value='10',fair_value_currency='USD'),
        dict(row_id='R2',fair_value='20',fair_value_currency='GBP')))
    matched=pd.DataFrame([dict(cik='123',source='bdc',position_id='P1',begin_report_date='2025-12-31',
        end_report_date='2026-03-31',begin_fair_value='10',end_fair_value='20')])
    actual=synchronize_matches(matched,final)
    assert actual.iloc[0].begin_fair_value==10 and pd.isna(actual.iloc[0].end_fair_value)


def fx_fixture(amount='80',currency='GBP',report_date='2026-03-31'):
    facts={'_financial_units':{'source_sha256':'a'*64},'fair_value':{'r':amount}}
    frame=rows(dict(fair_value=amount,fair_value_currency=currency,report_date=report_date,
        cost='',src_facts=json.dumps(facts)))
    decision=dict(decision_id='synthetic-review',row_id='R1',field='fair_value',source_value=amount,
        currency=currency,document_sha256='a'*64)
    quote=dict(provider='ECB',date='2026-03-30',per_EUR={'GBP':'0.8','USD':'1.2'},
        quote_id='synthetic-quote',source_sha256='b'*64)
    return frame,decision,quote


@pytest.mark.parametrize('amount,expected',[('80',120),('-80',-120),('0',0),('0.125',0.1875)])
def test_adjudicated_foreign_fv_uses_pinned_decimal_fx_then_donates_and_replays(amount,expected):
    frame,decision,quote=fx_fixture(amount)
    result,states=prepare(frame,fx_quotes=[quote],unit_adjudications=[decision])
    row=result.iloc[0]
    assert row.fair_value==expected and row.fair_value_currency=='USD'
    event=json.loads(row.src_facts)['_financial_fx']['fair_value']
    assert event['source_value']==amount and event['tagged_currency']=='GBP'
    assert event['conversion']['quote_id']=='synthetic-quote'
    assert states.iloc[0].donor_valid
    final,donors=cost_proxies(result,states,release_id='release')
    assert final.iloc[0].cost==expected and donors.iloc[0].donor_row_id=='R1'
    again,_=prepare(final,prior_states=states,fx_quotes=[quote],unit_adjudications=[decision])
    assert again.iloc[0].fair_value==expected
    assert json.loads(again.iloc[0].src_facts)['_financial_fx']['fair_value']==event


@pytest.mark.parametrize('change',['rate','source_hash','date','withdrawn_quote'])
def test_changed_fx_reference_requires_source_rebuild_instead_of_stale_replay(change):
    frame,decision,quote=fx_fixture()
    result,states=prepare(frame,fx_quotes=[quote],unit_adjudications=[decision])
    changed=dict(quote)
    if change=='rate': changed['per_EUR']={'GBP':'0.8','USD':'2.0'}
    if change=='source_hash': changed['source_sha256']='c'*64
    if change=='date': changed['date']='2026-03-29'
    quotes=[] if change=='withdrawn_quote' else [changed]
    with pytest.raises(ValueError,match='Retained FX reference changed; rebuild from cached source'):
        prepare(result,prior_states=states,fx_quotes=quotes,unit_adjudications=[decision])
    if change=='rate':
        rebuilt,_=prepare(frame,fx_quotes=quotes,unit_adjudications=[decision])
        assert rebuilt.iloc[0].fair_value==200


@pytest.mark.parametrize('partial',[False,True])
def test_withdrawn_unit_decision_cannot_leave_converted_values_admitted(partial):
    frame,decision,quote=fx_fixture()
    result,states=prepare(frame,fx_quotes=[quote],unit_adjudications=[decision])
    decisions=[dict(decision,row_id='unrelated-row')] if partial else []
    with pytest.raises(ValueError,match='no admitted decision; rebuild from cached source'):
        prepare(result,prior_states=states,fx_quotes=[quote],unit_adjudications=decisions)


def test_newly_available_quote_requires_rebuild_of_unavailable_conversion():
    frame,decision,quote=fx_fixture()
    result,states=prepare(frame,unit_adjudications=[decision])
    with pytest.raises(ValueError,match='Retained FX reference changed'):
        prepare(result,prior_states=states,fx_quotes=[quote],unit_adjudications=[decision])
    rebuilt,_=prepare(frame,fx_quotes=[quote],unit_adjudications=[decision])
    assert rebuilt.iloc[0].fair_value==120


def test_unselected_future_quote_does_not_invalidate_unchanged_replay():
    frame,decision,quote=fx_fixture()
    result,states=prepare(frame,fx_quotes=[quote],unit_adjudications=[decision])
    future=dict(quote,date='2026-04-01',quote_id='future',source_sha256='c'*64)
    again,_=prepare(result,prior_states=states,fx_quotes=[quote,future],unit_adjudications=[decision])
    assert again.iloc[0].fair_value==120
    assert json.loads(again.iloc[0].src_facts)['_financial_fx']==json.loads(result.iloc[0].src_facts)['_financial_fx']


@pytest.mark.parametrize('change',['rate','source_hash'])
def test_retained_conversion_metadata_cannot_keep_an_unchanged_signature(change):
    frame,decision,quote=fx_fixture()
    result,states=prepare(frame,fx_quotes=[quote],unit_adjudications=[decision])
    facts=json.loads(result.iloc[0].src_facts)
    conversion=facts['_financial_fx']['fair_value']['conversion']
    if change=='rate': conversion['rate_USD_per_source']='9'
    else: conversion['quote_inputs']['source_sha256']='d'*64
    result.loc[0,'src_facts']=json.dumps(facts)
    with pytest.raises(ValueError,match='Retained FX reference changed'):
        prepare(result,prior_states=states,fx_quotes=[quote],unit_adjudications=[decision])


@pytest.mark.parametrize('case,expected',[('future','FX_unavailable'),('stale','FX_stale'),('missing','FX_unavailable')])
def test_adjudicated_currency_without_current_quote_stays_unavailable(case,expected):
    frame,decision,quote=fx_fixture()
    if case=='future': quote['date']='2026-04-01'
    if case=='stale': quote['date']='2026-03-23'
    result,_=prepare(frame,fx_quotes=[] if case=='missing' else [quote],unit_adjudications=[decision])
    assert pd.isna(result.iloc[0].fair_value) and result.iloc[0].fair_value_currency=='GBP'
    facts=json.loads(result.iloc[0].src_facts)
    assert facts['_financial_fx']['fair_value']['conversion']['method']==expected
    assert facts['_financial_fair_value']['state']==expected
    assert facts['_financial_fair_value']['raw']=='80'


def test_quotes_alone_cannot_convert_unadjudicated_foreign_unit():
    frame,_,quote=fx_fixture()
    result,_=prepare(frame,fx_quotes=[quote])
    assert pd.isna(result.iloc[0].fair_value)
    assert '_financial_fx' not in json.loads(result.iloc[0].src_facts)


def test_seven_day_quote_boundary_and_same_observation_legs():
    frame,decision,quote=fx_fixture()
    quote['date']='2026-03-24'
    future=dict(quote,date='2026-04-01',quote_id='future',per_EUR={'GBP':'1','USD':'9'})
    result,_=prepare(frame,fx_quotes=[quote,future],unit_adjudications=[decision])
    assert result.iloc[0].fair_value==120
    event=json.loads(result.iloc[0].src_facts)['_financial_fx']['fair_value']['conversion']
    assert event['age_days']==7 and event['quote_inputs']['USD_per_EUR']=='1.2'
    assert event['quote_inputs']['source_sha256']=='b'*64


@pytest.mark.parametrize('change',[{'field':'cost'},{'field':'principal_amount'}])
def test_other_monetary_field_adjudication_cannot_be_applied_to_fv(change):
    frame,decision,quote=fx_fixture()
    with pytest.raises(ValueError,match='lacks observation/value/document'):
        prepare(frame,fx_quotes=[quote],unit_adjudications=[dict(decision,**change)])


def test_adjudicated_usd_correction_does_not_use_principal_or_fx():
    frame,decision,_=fx_fixture(currency='EGP')
    frame['principal_currency']='GBP'
    decision['currency']='USD'
    result,_=prepare(frame,unit_adjudications=[decision])
    assert result.iloc[0].fair_value==80 and result.iloc[0].fair_value_currency=='USD'
    assert json.loads(result.iloc[0].src_facts)['_financial_fx']['fair_value']['tagged_currency']=='EGP'


def test_reviewed_foreign_unit_remains_resolved_when_its_fx_is_missing():
    frame,decision,_=fx_fixture(currency='EGP')
    decision['currency']='GBP'
    result,states=prepare(frame,unit_adjudications=[decision])
    assert pd.isna(result.iloc[0].fair_value) and result.iloc[0].fair_value_currency=='GBP'
    facts=json.loads(result.iloc[0].src_facts)
    assert facts['_financial_fx']['fair_value']['tagged_currency']=='EGP'
    assert facts['_financial_fair_value']['currency']=='GBP'
    result['fair_value_currency']='USD'
    with pytest.raises(ValueError,match='does not match retained'):
        prepare(result,prior_states=states,unit_adjudications=[decision])


@pytest.mark.parametrize('change',[dict(source_value='81'),dict(document_sha256='c'*64)])
def test_wrong_value_or_document_cannot_unlock_currency_conversion(change):
    frame,decision,quote=fx_fixture()
    with pytest.raises(ValueError,match='does not match retained'):
        prepare(frame,fx_quotes=[quote],unit_adjudications=[dict(decision,**change)])


def test_conflicting_quote_dates_and_repeated_adjudications_block():
    frame,decision,quote=fx_fixture()
    with pytest.raises(ValueError,match='Ambiguous FX observations'):
        prepare(frame,fx_quotes=[quote,dict(quote,quote_id='other')],unit_adjudications=[decision])
    with pytest.raises(ValueError,match='Ambiguous FV unit'):
        prepare(frame,unit_adjudications=[decision,decision])


def test_fx_input_loader_requires_admission_and_retained_quote_source(tmp_path):
    from pipeline.monetary_fx import load_inputs
    from pipeline.programme.core import sha
    _,decision,quote=fx_fixture()
    source=tmp_path/'provider.txt';source.write_text('synthetic quote source')
    quote['source']={'path':source.name,'sha256':sha(source)}
    files={'quotes.json':dict(format_version=1,quotes=[quote]),
        'unit_adjudications.json':dict(format_version=1,decisions=[decision])}
    for name,data in files.items(): (tmp_path/name).write_text(json.dumps(data))
    absent=load_inputs(tmp_path)
    assert absent['quotes']==[] and absent['decisions']==[]
    manifest=dict(format_version=1,entries={name:dict(admission_status='promoted',sha256=sha(tmp_path/name),
        evidence={'fixture':'independent passed review'}) for name in files})
    (tmp_path/'admission_manifest.json').write_text(json.dumps(manifest))
    loaded=load_inputs(tmp_path)
    assert len(loaded['quotes'])==len(loaded['decisions'])==1
    source.write_text('tampered quote source')
    with pytest.raises(ValueError,match='source hash mismatch'): load_inputs(tmp_path)


def test_actual_financial_artifact_path_consumes_admitted_fx_package(tmp_path,monkeypatch):
    from pipeline import config
    from pipeline.financial_finalization import prepare_artifact
    from pipeline.programme.core import sha
    frame,decision,quote=fx_fixture()
    reference=tmp_path/'reference';base=reference/'monetary_conversion';base.mkdir(parents=True)
    source=base/'provider.txt';source.write_text('synthetic provider observation')
    quote['source']=dict(path=source.name,sha256=sha(source))
    for name,data in (('quotes.json',dict(format_version=1,quotes=[quote])),
                      ('unit_adjudications.json',dict(format_version=1,decisions=[decision]))):
        (base/name).write_text(json.dumps(data))
    (base/'admission_manifest.json').write_text(json.dumps(dict(format_version=1,entries={name:
        dict(admission_status='promoted',sha256=sha(base/name),evidence={'fixture':'reviewed'})
        for name in ('quotes.json','unit_adjudications.json')})))
    monkeypatch.setattr(config,'REFERENCE_DIR',reference)
    monkeypatch.setattr(config,'FUND_FINANCIALS_FILE',tmp_path/'absent.csv')
    monkeypatch.setattr(config,'GICS_HIERARCHY_FILE',tmp_path/'absent.json')
    output=tmp_path/'staged'
    result,_=prepare_artifact(frame,output,source_frame=True)
    assert result.iloc[0].fair_value==120
    receipt=json.loads((output/'financial_contract.json').read_text(encoding='utf-8'))
    assert 'monetary_conversion/quotes.json' in receipt['monetary_inputs']


@pytest.mark.parametrize('change',[{'field':'cost'},{'currency':'U_GBP'},{'source_value':'NaN'}])
def test_admitted_but_malformed_unit_decision_is_rejected_at_load(tmp_path,change):
    from pipeline.monetary_fx import load_inputs
    from pipeline.programme.core import sha
    _,decision,_=fx_fixture()
    path=tmp_path/'unit_adjudications.json'
    path.write_text(json.dumps(dict(format_version=1,decisions=[dict(decision,**change)])))
    (tmp_path/'admission_manifest.json').write_text(json.dumps(dict(format_version=1,entries={path.name:
        dict(admission_status='promoted',sha256=sha(path),evidence={'fixture':'reviewed'})})))
    with pytest.raises(ValueError,match='Malformed field-specific'): load_inputs(tmp_path)
