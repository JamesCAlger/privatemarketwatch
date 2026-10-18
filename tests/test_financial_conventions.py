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
    quote=dict(provider='FRED',date='2026-03-30',usd_per_unit={'GBP':'1.5','EUR':'1.2'},
        series={'GBP':'DEXUSUK','EUR':'DEXUSEU'},quote_id='synthetic-quote',source_sha256='b'*64)
    return frame,decision,quote


def resolved_unit_fixture(amount='80',currency='GBP',status='resolved',report_date='2026-03-31'):
    # Staging recorded the document's own unit definition for this fact.
    facts={'_financial_units':{'source_sha256':'a'*64,
        'fair_value':{'unit_ref':'gbp','currency':currency if status=='resolved' else None,'status':status}},
        'fair_value':{'r':amount}}
    frame=rows(dict(fair_value=amount,fair_value_currency=currency if status=='resolved' else 'UNRESOLVED',
        report_date=report_date,cost='',src_facts=json.dumps(facts)))
    quote=dict(provider='FRED',date='2026-03-30',usd_per_unit={'GBP':'1.5'},series={'GBP':'DEXUSUK'},
        quote_id='synthetic-quote',source_sha256='b'*64)
    return frame,quote


def test_document_resolved_iso_unit_auto_adjudicates_and_replays():
    frame,quote=resolved_unit_fixture()
    result,states=prepare(frame,fx_quotes=[quote])
    row=result.iloc[0]
    assert row.fair_value==120 and row.fair_value_currency=='USD'
    event=json.loads(row.src_facts)['_financial_fx']['fair_value']
    assert event['decision_id']=='unit:R1' and event['document_sha256']=='a'*64
    assert event['source_value']=='80' and event['resolved_currency']=='GBP'
    assert event['conversion']['quote_inputs']['usd_per_unit']=='1.5'
    again,_=prepare(result,prior_states=states,fx_quotes=[quote])
    assert again.iloc[0].fair_value==120
    assert json.loads(again.iloc[0].src_facts)['_financial_fx']['fair_value']==event


def test_unresolved_document_unit_is_not_auto_adjudicated():
    frame,quote=resolved_unit_fixture(status='unit_unresolved')
    result,_=prepare(frame,fx_quotes=[quote])
    assert pd.isna(result.iloc[0].fair_value)
    assert '_financial_fx' not in json.loads(result.iloc[0].src_facts)


def test_manual_decision_overrides_automatic_unit_decision():
    frame,quote=resolved_unit_fixture()
    manual=dict(decision_id='reviewed-override',row_id='R1',field='fair_value',source_value='80',
        currency='GBP',document_sha256='a'*64)
    result,_=prepare(frame,fx_quotes=[quote],unit_adjudications=[manual])
    assert json.loads(result.iloc[0].src_facts)['_financial_fx']['fair_value']['decision_id']=='reviewed-override'


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
    if expected<0:
        # a negative first value converts like any other but is not a cost (owner ruling 2026-10-06, D-024)
        assert pd.isna(final.iloc[0].cost) and donors.iloc[0].method=='no_source_valid_donor'
    else:
        assert final.iloc[0].cost==expected and donors.iloc[0].donor_row_id=='R1'
    again,_=prepare(final,prior_states=states,fx_quotes=[quote],unit_adjudications=[decision])
    assert again.iloc[0].fair_value==expected
    assert json.loads(again.iloc[0].src_facts)['_financial_fx']['fair_value']==event


@pytest.mark.parametrize('change',['rate','source_hash','date','withdrawn_quote'])
def test_changed_fx_reference_requires_source_rebuild_instead_of_stale_replay(change):
    frame,decision,quote=fx_fixture()
    result,states=prepare(frame,fx_quotes=[quote],unit_adjudications=[decision])
    changed=dict(quote)
    if change=='rate': changed['usd_per_unit']={'GBP':'2.5','EUR':'1.2'}
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
    future=dict(quote,date='2026-04-01',quote_id='future',usd_per_unit={'GBP':'9'})
    result,_=prepare(frame,fx_quotes=[quote,future],unit_adjudications=[decision])
    assert result.iloc[0].fair_value==120
    event=json.loads(result.iloc[0].src_facts)['_financial_fx']['fair_value']['conversion']
    assert event['age_days']==7 and event['quote_inputs']['usd_per_unit']=='1.5'
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


BARE=json.dumps({"interest_rate":{"c":"bare","r":0.0943}})


def test_fund_reading_publishes_the_plain_rate_tag_as_all_in():
    # BCRED 2026-03-31, Inovalon Holdings, Inc. 1: filed 9.43, PIK 2.75 (part of the 9.43); IRI Group: filed 7.95, no PIK.
    frame=rows(dict(row_id="pik",cik="0001803498",interest_rate_kind="",interest_rate="9.43",pik_rate="2.75",src_facts=BARE),
        dict(row_id="plain",cik="0001803498",interest_rate_kind="",interest_rate="7.95",pik_rate="",src_facts=BARE),
        dict(row_id="other",cik="0000000999",interest_rate_kind="",interest_rate="9.43",pik_rate="2.75",src_facts=BARE))
    result,states=prepare(frame,rate_readings={"0001803498":"all_in"})
    by_id=result.set_index("row_id")
    assert by_id.loc["pik","interest_rate_kind"]=="all_in" and by_id.loc["pik","interest_rate"]==9.43
    assert by_id.loc["pik","interest_rate_cash"]==pytest.approx(6.68)
    assert by_id.loc["plain","interest_rate"]==7.95 and pd.isna(by_id.loc["plain","interest_rate_cash"])
    assert "coupon_unresolved" not in by_id.loc["pik","src_transforms"]
    # a fund with no reading: the same PIK row stays withheld
    assert by_id.loc["other","interest_rate_kind"]=="unresolved" and pd.isna(by_id.loc["other","interest_rate"])
    assert states.set_index("row_id").loc["pik","coupon_state"]=="supported"


def test_pik_above_the_filed_rate_contradicts_all_in_and_stays_unresolved():
    # Ares 2023-12-31, NMC Skincare first lien loan 1: filed 1.00, PIK 11.44. The filed rate cannot contain the PIK.
    frame=rows(dict(row_id="split",cik="0001287750",interest_rate_kind="",interest_rate="1.0",pik_rate="11.44",src_facts=BARE),
        dict(row_id="equal",cik="0001287750",interest_rate_kind="",interest_rate="15.0",pik_rate="15.0",src_facts=BARE))
    result,_=prepare(frame,rate_readings={"0001287750":"all_in"})
    by_id=result.set_index("row_id")
    assert by_id.loc["split","interest_rate_kind"]=="unresolved" and pd.isna(by_id.loc["split","interest_rate"])
    assert by_id.loc["split","interest_rate_reported"]==1.0
    assert "interest_rate:coupon_unresolved" in by_id.loc["split","src_transforms"]
    # fully PIK: the filed rate equals the PIK rate
    assert by_id.loc["equal","interest_rate"]==15.0 and by_id.loc["equal","interest_rate_cash"]==0.0


def test_reading_does_not_override_a_tag_that_names_its_own_kind_or_invent_a_rate():
    cash=json.dumps({"interest_rate":{"c":"investmentinterestratepaidincash"}})
    frame=rows(dict(row_id="cash",cik="0001803498",interest_rate_kind="",interest_rate="10",pik_rate="2",src_facts=cash),
        dict(row_id="none",cik="0001803498",interest_rate_kind="",interest_rate="",pik_rate="",src_facts="{}"),
        dict(row_id="rerun",cik="0001803498",interest_rate_kind="unresolved",interest_rate="8.42",pik_rate="",src_facts=BARE))
    result,_=prepare(frame,rate_readings={"0001803498":"all_in"},source_frame=True)
    by_id=result.set_index("row_id")
    assert by_id.loc["cash","interest_rate_kind"]=="cash" and by_id.loc["cash","interest_rate"]==12
    assert by_id.loc["none","interest_rate_kind"]=="unresolved" and pd.isna(by_id.loc["none","interest_rate"])
    # a row stored as unresolved by an earlier build takes the reading
    assert by_id.loc["rerun","interest_rate"]==8.42


def test_cash_leg_reading_keeps_the_existing_cash_rule():
    frame=rows(dict(row_id="pik",cik="0000000777",interest_rate_kind="",interest_rate="6.7",pik_rate="7.6",src_facts=BARE),
        dict(row_id="plain",cik="0000000777",interest_rate_kind="",interest_rate="6.7",pik_rate="",src_facts=BARE))
    result,_=prepare(frame,rate_readings={"0000000777":"cash_leg"})
    by_id=result.set_index("row_id")
    assert by_id.loc["pik","interest_rate"]==pytest.approx(14.3) and by_id.loc["pik","interest_rate_cash"]==6.7
    # with no PIK on the row the cash coupon is the all-in coupon
    assert by_id.loc["plain","interest_rate"]==6.7


def test_wrapper_setting_is_validated_and_set_for_the_four_funds_that_file_rates():
    from pipeline.source_encodings import load_encodings
    encodings=load_encodings()
    for cik in ("0001803498","0001287750","0001838126","0001837532"):
        assert encodings[cik]["filed_rate_reading"]==["all_in"]
    assert "filed_rate_reading" not in encodings.get("0001812554",{})


def test_plain_rate_with_no_pik_on_the_row_is_published_for_any_fund():
    # With no PIK the all-in coupon and the cash coupon are the same number, so no fund reading is needed.
    plain=json.dumps({"interest_rate":{"c":"investmentinterestrate"}})
    frame=rows(dict(row_id="none",cik="0000000999",interest_rate_kind="",interest_rate="7.95",pik_rate="",src_facts=plain),
        dict(row_id="zero",cik="0000000999",interest_rate_kind="",interest_rate="8.42",pik_rate="0",src_facts=BARE),
        dict(row_id="text",cik="0000000999",interest_rate_kind="",interest_rate="9.0",pik_rate="",src_facts="{}"))
    result,states=prepare(frame,rate_readings={})
    by_id=result.set_index("row_id")
    for row_id,rate in (("none",7.95),("zero",8.42),("text",9.0)):
        assert by_id.loc[row_id,"interest_rate_kind"]=="all_in" and by_id.loc[row_id,"interest_rate"]==rate
        assert "coupon_unresolved" not in by_id.loc[row_id,"src_transforms"]
    assert set(states.coupon_state)=={"supported"}


def test_plain_rate_stays_withheld_when_the_row_has_or_mentions_pik():
    frame=rows(dict(row_id="pik",cik="0000000999",interest_rate_kind="",interest_rate="9.43",pik_rate="2.75",src_facts=BARE),
        # PIK named in the row text but no PIK rate captured: the filed number may be the cash part
        dict(row_id="named",cik="0000000999",interest_rate_kind="",interest_rate="6.7",pik_rate="",src_facts=BARE,
             bdc_investment_identifier="Acme Corp, First lien loan (6.7% Cash, 7.6% PIK)"),
        dict(row_id="described",cik="0000000999",interest_rate_kind="",interest_rate="6.7",pik_rate="",src_facts=BARE,
             instrument_description="Term loan, 2.00% PIK"))
    result,_=prepare(frame,rate_readings={})
    by_id=result.set_index("row_id")
    for row_id in ("pik","named","described"):
        assert by_id.loc[row_id,"interest_rate_kind"]=="unresolved" and pd.isna(by_id.loc[row_id,"interest_rate"])
        assert "interest_rate:coupon_unresolved" in by_id.loc[row_id,"src_transforms"]


def test_no_pik_rule_does_not_reach_tags_that_are_not_the_coupon():
    def tag(name): return json.dumps({"interest_rate":{"c":name}})
    frame=rows(dict(row_id="cash",cik="0000000999",interest_rate_kind="",interest_rate="10",pik_rate="",
                    src_facts=tag("investmentinterestratepaidincash")),
        dict(row_id="eot",cik="0000000999",interest_rate_kind="",interest_rate="4",pik_rate="",src_facts=tag("investmentinterestrateendofterm")),
        dict(row_id="cap",cik="0000000999",interest_rate_kind="",interest_rate="12",pik_rate="",src_facts=tag("investmentinterestratecap")),
        dict(row_id="yield",cik="0000000999",interest_rate_kind="",interest_rate="11",pik_rate="",src_facts=tag("investmenteffectiveyield")))
    result,_=prepare(frame,rate_readings={})
    assert result.interest_rate.isna().all()
    assert result.set_index("row_id").loc["cash","interest_rate_cash"]==10


def test_a_row_that_files_no_rate_is_not_tagged_coupon_unresolved():
    # Blue Owl tags no rate at all (0 of 8,164 credit rows). "Unresolved" means a filed rate whose
    # meaning is unknown; a row with nothing filed has nothing to resolve (decision D-010).
    frame=rows(dict(row_id="none",cik="0001812554",interest_rate_kind="",interest_rate="",pik_rate="",src_facts="{}"),
        dict(row_id="pikonly",cik="0001812554",interest_rate_kind="",interest_rate="",pik_rate="2.75",src_facts="{}"),
        dict(row_id="split",cik="0001287750",interest_rate_kind="",interest_rate="1.0",pik_rate="11.44",src_facts=BARE))
    result,states=prepare(frame,rate_readings={"0001287750":"all_in"})
    by_id=result.set_index("row_id")
    assert "coupon_unresolved" not in by_id.loc["none","src_transforms"]
    assert "coupon_unresolved" not in by_id.loc["pikonly","src_transforms"]
    assert pd.isna(by_id.loc["none","interest_rate"]) and by_id.loc["none","interest_rate_kind"]=="unresolved"
    # a filed rate that cannot be read stays tagged
    assert "interest_rate:coupon_unresolved" in by_id.loc["split","src_transforms"]


def test_a_loan_filed_with_only_a_pik_rate_takes_it_as_the_coupon_where_the_fund_files_it_so():
    # Ares 2025-06-30: WebPT senior subordinated loan is printed "13.25 % PIK" in the coupon column and
    # tagged with a PIK rate and no plain rate; Amerivet subordinated loan "16.50 % PIK" likewise
    # (decision D-018). The coupon is the PIK rate.
    credit=dict(asset_category="LOAN")
    frame=rows(dict(credit,row_id="pikonly",cik="0001287750",interest_rate_kind="",interest_rate="",pik_rate="13.25",basis_spread="",src_facts="{}"),
        # Ares equity units printed with a PIK dividend keep no interest rate: the rule is for loan rows.
        dict(row_id="equity",cik="0001287750",asset_category="EQUITY_COMMON",interest_rate_kind="",interest_rate="",pik_rate="10.0",basis_spread="",src_facts="{}"),
        # Apollo 2024-12-31 Material Holdings: "S+610 (Includes 8.03% PIK)". A spread is filed, so the PIK is a part, not the coupon.
        dict(credit,row_id="spread",cik="0001287750",interest_rate_kind="",interest_rate="",pik_rate="8.03",basis_spread="6.1",src_facts="{}"),
        # HPS 2026-03-31 Daphne S.P.A.: printed "E + 6.75 %" with a coupon of 8.75 %; the PIK tag holds the margin.
        # HPS reads its plain tag as all-in but has no PIK-only setting, so nothing is published.
        dict(credit,row_id="margin",cik="0001838126",interest_rate_kind="",interest_rate="",pik_rate="6.75",basis_spread="",src_facts="{}"),
        dict(credit,row_id="nothing",cik="0001287750",interest_rate_kind="",interest_rate="",pik_rate="",basis_spread="",src_facts="{}"))
    result,states=prepare(frame,rate_readings={"0001287750":"all_in","0001838126":"all_in"},pik_only_coupon={"0001287750"})
    by_id=result.set_index("row_id")
    assert by_id.loc["pikonly","interest_rate"]==13.25 and by_id.loc["pikonly","interest_rate_kind"]=="all_in"
    assert pd.isna(by_id.loc["pikonly","interest_rate_reported"])
    assert "interest_rate:pik_only" in by_id.loc["pikonly","src_transforms"]
    assert states.set_index("row_id").loc["pikonly","coupon_state"]=="supported"
    for row_id in ("equity","spread","margin","nothing"):
        assert pd.isna(by_id.loc[row_id,"interest_rate"]) and by_id.loc[row_id,"interest_rate_kind"]=="unresolved"
        assert "pik_only" not in str(by_id.loc[row_id,"src_transforms"])


def test_pik_only_setting_is_validated_and_set_for_ares_and_apollo():
    from pipeline.financial_conventions import pik_only_coupon_funds
    from pipeline.source_encodings import load_encodings
    # Apollo: the row text itself reads 'Interest Rate 11.45% PIK' (Material Holdings, 2024-09-30)
    # Blue Owl files both kinds (below); it is in this set and in the margin set
    assert pik_only_coupon_funds()>={"0001287750","0001837532","0001812554"}
    assert load_encodings()["0001287750"]["pik_only_tag_reading"]==["coupon"]
    assert load_encodings()["0001812554"]["pik_only_tag_reading"]==["coupon","margin"]


def test_a_fund_that_files_both_kinds_reads_each_row_by_its_printed_reference_rate():
    # Blue Owl 10-K 2025-12-31: Associations Finance "N/A | 14.25%" (a fixed PIK coupon) and Inovalon second lien
    # "S+ | 8.50%" (a PIK margin over SOFR). Both rows are tagged with a PIK rate and nothing else.
    owl="0001812554"
    loan=dict(asset_category="LOAN",cik=owl,interest_rate_kind="",interest_rate="",src_facts="{}",basis_spread="")
    frame=rows(dict(loan,row_id="fixed",pik_rate="14.25",reference_rate_type="",coupon_type="Fixed"),
        dict(loan,row_id="margin",pik_rate="8.5",reference_rate_type="SOFR",coupon_type=""),
        # the printed cell was not read (an unknown code): a margin must not be published as a coupon
        dict(loan,row_id="unread",pik_rate="5.75",reference_rate_type="",coupon_type=""),
        # a reference rate outranks a Fixed label: never both readings on one row
        dict(loan,row_id="clash",pik_rate="6.0",reference_rate_type="SOFR",coupon_type="Fixed"),
        dict(loan,row_id="equity",asset_category="EQUITY_PREFERRED",pik_rate="11.0",reference_rate_type="",coupon_type="Fixed"),
        # a coupon-only fund needs no printed evidence (Ares), as before
        dict(loan,row_id="ares",cik="0001287750",pik_rate="13.25",reference_rate_type="",coupon_type=""))
    result,_=prepare(frame,rate_readings={},pik_only_coupon={owl,"0001287750"},pik_only_margin={owl})
    by_id=result.set_index("row_id")
    assert float(by_id.loc["fixed","interest_rate"])==14.25 and by_id.loc["fixed","interest_rate_kind"]=="all_in"
    assert "interest_rate:pik_only" in by_id.loc["fixed","src_transforms"] and str(by_id.loc["fixed","basis_spread"]) in ("","nan","None")
    for row_id in ("margin","clash"):
        assert float(by_id.loc[row_id,"basis_spread"])==float(by_id.loc[row_id,"pik_rate"])
        assert pd.isna(by_id.loc[row_id,"interest_rate"]) and "pik_only" not in by_id.loc[row_id,"src_transforms"]
    for row_id in ("unread","equity"):
        assert pd.isna(by_id.loc[row_id,"interest_rate"]) and str(by_id.loc[row_id,"basis_spread"]) in ("","nan","None")
        assert "pik_" not in str(by_id.loc[row_id,"src_transforms"]).replace("pik_rate","")
    assert float(by_id.loc["ares","interest_rate"])==13.25


def test_a_negative_first_observed_value_is_not_a_cost():
    # Blue Owl from 2024-12-31: undrawn lines come from the commitments table with a negative fair value and no
    # cost fact (Ministry Brands revolving loan, -4,083,000). A proxy would publish a negative cost the fund never
    # filed (owner ruling 2026-10-06, decision D-024). An observed zero still donates (test above).
    prepared,states=prepare(rows(dict(row_id="neg",cost="",fair_value="-4083000",position_id="P1"),
        dict(row_id="pos",cost="",fair_value="250000",position_id="P2")))
    result,audit=cost_proxies(prepared,states,release_id="release")
    by_id=result.set_index("row_id");evidence=audit.set_index("row_id")
    assert pd.isna(by_id.loc["neg","cost"]) and by_id.loc["neg","cost_source"]!="first_observed_fv_proxy"
    assert evidence.loc["neg","method"]=="no_source_valid_donor" and pd.isna(evidence.loc["neg","proxy_value"])
    assert by_id.loc["pos","cost"]==250000 and evidence.loc["pos","method"]=="first_observed_fv_proxy"


def test_a_pik_tag_that_is_a_margin_over_a_known_reference_rate_is_published_as_the_spread():
    # HPS 2024-12-31: Southern Graphics Inc. is printed "SF + 7.50 % PIK" and tagged with a PIK rate of 0.075 and
    # no spread; Daphne S.P.A. "E + 6.75 %" likewise (decision D-026). The margin belongs in basis_spread.
    loan=dict(asset_category="LOAN",cik="0001838126",interest_rate_kind="",interest_rate="",src_facts="{}")
    frame=rows(dict(loan,row_id="margin",pik_rate="7.5",basis_spread="",reference_rate_type="SOFR"),
        # Wildcat Car Wash is printed "15.00 % PIK" with no reference rate: not a margin, left alone.
        dict(loan,row_id="fixed",pik_rate="15.0",basis_spread="",reference_rate_type=""),
        # a spread is already filed: the PIK is a part of it (Severin Acquisition, spread 4.75, PIK 2.25)
        dict(loan,row_id="both",pik_rate="2.25",basis_spread="4.75",interest_rate="8.42",reference_rate_type="SOFR"),
        dict(loan,row_id="equity",asset_category="EQUITY_COMMON",pik_rate="8.0",basis_spread="",reference_rate_type="SOFR"),
        # a fund outside the setting: nothing moves
        dict(loan,row_id="other",cik="0001812554",pik_rate="5.75",basis_spread="",reference_rate_type="SOFR"))
    result,_=prepare(frame,rate_readings={"0001838126":"all_in"},pik_only_coupon=set(),pik_only_margin={"0001838126"})
    by_id=result.set_index("row_id")
    assert float(by_id.loc["margin","basis_spread"])==7.5 and "basis_spread:pik_margin" in by_id.loc["margin","src_transforms"]
    assert float(by_id.loc["margin","pik_rate"])==7.5 and pd.isna(by_id.loc["margin","interest_rate"])
    assert float(by_id.loc["both","basis_spread"])==4.75
    for row_id in ("fixed","equity","other"):
        assert str(by_id.loc[row_id,"basis_spread"]) in ("","nan","None") and "pik_margin" not in str(by_id.loc[row_id,"src_transforms"])


def test_pik_margin_setting_is_validated_and_set_for_hps_and_blue_owl():
    from pipeline.financial_conventions import pik_only_margin_funds
    # Blue Owl 10-K 2025-12-31: Inovalon second lien is printed 'S+ | (no cash) | 8.50%' under Ref. Rate, Cash, PIK;
    # 10-Q 2023-03-31: Hg Genesis 9 'E+ 7.00% PIK'. Its reference rate comes from the printed column, not a tag.
    assert pik_only_margin_funds()>={"0001838126","0001812554"}


def test_the_pik_margin_label_survives_a_second_pass_over_the_finalized_rows():
    # The build finalizes rows, then prepares them again with their retained states. On the second pass the spread
    # is already filled, so the label has to be kept, not re-derived (found in sandbox five16: 60 HPS rows lost it).
    loan=dict(asset_category="LOAN",cik="0001838126",interest_rate_kind="",interest_rate="",src_facts="{}",
        pik_rate="7.5",basis_spread="",reference_rate_type="SOFR",src_transforms="pik_rate:rate_x100")
    first,states=prepare(rows(loan),rate_readings={},pik_only_coupon=set(),pik_only_margin={"0001838126"})
    again,_=prepare(first,prior_states=states,rate_readings={},pik_only_coupon=set(),pik_only_margin={"0001838126"})
    assert float(again.iloc[0].basis_spread)==7.5
    assert again.iloc[0].src_transforms.count("basis_spread:pik_margin")==1


def test_with_the_proxy_switched_off_a_row_with_no_filed_cost_has_no_cost():
    # Owner ruling 2026-10-11: no cost is published where none is filed (config.COST_PROXY_ENABLED = False).
    prepared,states=prepare(rows(dict(row_id="none",cost="",fair_value="250000",position_id="P1"),
        dict(row_id="filed",cost="240000",fair_value="250000",position_id="P2")))
    result,audit=cost_proxies(prepared,states,release_id="release",enabled=False)
    by_id=result.set_index("row_id");evidence=audit.set_index("row_id")
    assert pd.isna(by_id.loc["none","cost"]) and by_id.loc["none","cost_source"]!="first_observed_fv_proxy"
    assert evidence.loc["none","method"]=="not_filed" and pd.isna(evidence.loc["none","proxy_value"])
    assert by_id.loc["filed","cost"]==240000 and evidence.loc["filed","method"]=="reported"


def test_a_cash_rate_with_no_pik_tag_is_the_coupon_only_for_a_fund_that_says_so():
    # Stepstone prints 'Cash Interest Rate / PIK Rate' and shows a PIK figure on every row that has one (decision D-112).
    cash={"interest_rate":{"r":0.087,"c":"investmentinterestratepaidincash"}}
    frame=rows(dict(row_id="plain",interest_rate="8.7",pik_rate="",src_facts=json.dumps(cash),
            instrument_description="Term Loan | Cash Interest Rate / PIK Rate | 8.70%"),
        dict(row_id="pik",interest_rate="8.92",pik_rate="2.88",src_facts=json.dumps(cash)))
    off,_=prepare(frame,no_untagged_pik=set())
    on,_=prepare(frame,no_untagged_pik={"0000000123"})
    off=off.set_index("row_id");on=on.set_index("row_id")
    assert pd.isna(off.loc["plain","interest_rate"])
    assert float(on.loc["plain","interest_rate"])==8.7 and "cash_plus_pik" not in str(on.loc["plain","src_transforms"])
    assert round(float(on.loc["pik","interest_rate"]),2)==11.8 and round(float(off.loc["pik","interest_rate"]),2)==11.8


@pytest.mark.parametrize("maturity,precision,status", [
    ("2027-08-10", "day", "dated"),       # declared from the printed line '08/10/27'
    ("2027-08", "unknown", None),          # false positive guard: no full date, no day precision
    ("", "unknown", None),
])
def test_printed_page_maturity_gets_day_precision_only_with_a_full_date(maturity, precision, status):
    result, _ = prepare(rows(dict(src_context_id="printed_page:d3dad0396499ac3b", fair_value_source="printed_page",
                                  maturity_date=maturity, maturity_date_source="printed_page")))
    row = result.iloc[0]
    assert row.maturity_precision == precision
    if status:
        assert row.maturity_status == status
    else:
        assert row.maturity_status != "dated"
