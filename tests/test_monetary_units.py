import json
from pathlib import Path

import duckdb
from lxml import etree
import pandas as pd
import pytest

from pipeline.monetary_units import XBRLI, ISO4217, document_units, resolve_bdc_units, unit_definition
from pipeline.financial_conventions import prepare


def source(tmp_path, *, currency='USD', cik='123', extra=''):
    folder=tmp_path/'123';folder.mkdir(exist_ok=True)
    path=folder/'000000012326000001.xml'
    path.write_text(f'<xbrl xmlns="{XBRLI}" xmlns:iso="{ISO4217}">'
        f'<context id="c1"><entity><identifier scheme="sec">{cik}</identifier></entity></context>'
        f'<unit id="U001"><measure>iso:{currency}</measure></unit>'
        '<unit id="U_USD"><measure>iso:EUR</measure></unit>' + extra + '</xbrl>')
    return path


def raw_rows(*changes):
    base=dict(cik='0000000123',accession_number='0000000123-26-000001',src_facts='{}',
        fair_value_unit='U001',cost_unit='U001',fair_value='100',cost='0',
        row_id='r1',position_id='p1',report_date='2026-03-31',source='bdc',
        fair_value_source='xbrl_field',src_context_id='c1')
    return pd.DataFrame([dict(base,**r) for r in (changes or ({},))])


def resolve(frame, tmp_path):
    with duckdb.connect() as con:
        con.register('input',frame)
        con.execute('CREATE TABLE bdc_raw AS SELECT * FROM input')
        resolve_bdc_units(con,tmp_path)
        return con.execute('SELECT * FROM bdc_raw ORDER BY row_id').fetchdf()


def test_unit_identifier_spelling_never_defines_its_currency(tmp_path):
    path=source(tmp_path)
    units,hash_value,status=document_units(path,'0000000123')
    assert status=='source_units_read' and len(hash_value)==64
    assert units['U001']['currency']=='USD'
    assert units['U_USD']['currency']=='EUR'
    frame=resolve(raw_rows({},dict(row_id='r2',cost_unit='U_USD')),tmp_path)
    assert list(frame._resolved_cost_currency)==['USD','EUR']
    assert list(frame._resolved_fv_currency)==['USD','USD']
    facts=json.loads(frame.iloc[0].src_facts)['_financial_units']
    assert facts['source_sha256']==hash_value and facts['cost']['unit_ref']=='U001'
    assert facts['cost']['status']=='resolved'
    frame=frame.rename(columns={'_resolved_cost_currency':'cost_currency','_resolved_fv_currency':'fair_value_currency'})
    output,states=prepare(frame)
    assert output.iloc[0].cost_reported==0 and output.iloc[0].cost==0
    assert pd.isna(output.iloc[1].cost_reported) and states.iloc[1].cost_state=='unresolved_currency'


def test_missing_unknown_and_case_mismatched_refs_are_not_guessed(tmp_path):
    source(tmp_path)
    result=resolve(raw_rows(dict(cost_unit='missing'),dict(row_id='r2',cost_unit='u001'),
        dict(row_id='r3',cost_unit=''),dict(row_id='r4',accession_number='0000000123-26-000099')) ,tmp_path)
    assert list(result._resolved_cost_currency)==['UNRESOLVED','UNRESOLVED','','UNRESOLVED']
    assert json.loads(result.iloc[2].src_facts)['_financial_units']['cost']['status']=='assumed_usd'
    assert json.loads(result.iloc[3].src_facts)['_financial_units']['cost']['status']=='source_unavailable'


def test_wrong_entity_and_duplicate_unit_ids_do_not_supply_currency(tmp_path):
    path=source(tmp_path,cik='456')
    assert document_units(path,'123')[2]=='source_entity_unresolved'
    path=source(tmp_path,extra='<unit id="U001"><measure>iso:GBP</measure></unit>')
    units,_,_=document_units(path,'123')
    assert units['U001']['currency'] is None
    result=resolve(raw_rows(),tmp_path)
    assert len(result)==1 and result.iloc[0]._resolved_cost_currency=='UNRESOLVED'


@pytest.mark.parametrize('body',[
    '<measure>iso:USD</measure><measure>iso:EUR</measure>',
    '<divide><unitNumerator><measure>iso:USD</measure></unitNumerator></divide>',
    '<measure>wrong:USD</measure>',
])
def test_composite_and_unbound_unit_definitions_are_unresolved(body):
    unit=etree.fromstring(f'<unit xmlns="{XBRLI}" xmlns:iso="{ISO4217}">{body}</unit>')
    assert unit_definition(unit)==dict(unit_kind='unresolved',currency=None)


def test_source_absence_does_not_infer_currency_from_usd_like_id(tmp_path):
    result=resolve(raw_rows(dict(cost_unit='U_USD')),tmp_path)
    assert result.iloc[0]._resolved_cost_currency=='UNRESOLVED'
    assert json.loads(result.iloc[0].src_facts)['_financial_units']['cost']['status']=='source_unavailable'


def resolve_with(frame, tmp_path, encodings):
    with duckdb.connect() as con:
        con.register('input',frame)
        con.execute('CREATE TABLE bdc_raw AS SELECT * FROM input')
        resolve_bdc_units(con,tmp_path,encodings=encodings)
        return con.execute('SELECT * FROM bdc_raw ORDER BY row_id').fetchdf()


def test_principal_unit_takes_the_currency_its_document_defines(tmp_path):
    # Apollo Debt Solutions names its units U_USD, U_EUR, U_GBP: the spelling is not a currency code.
    source(tmp_path)
    frame=resolve(raw_rows(dict(principal_amount_unit='U001'),dict(row_id='r2',principal_amount_unit='U_USD'),
        dict(row_id='r3',principal_amount_unit='missing'),dict(row_id='r4',principal_amount_unit='')),tmp_path)
    assert list(frame.principal_amount_unit)==['USD','EUR','missing','']
    facts=json.loads(frame.iloc[1].src_facts)['_financial_units']['principal_amount']
    assert facts=={'unit_ref':'U_USD','currency':'EUR'}


def test_rows_without_a_principal_unit_column_still_resolve(tmp_path):
    source(tmp_path)
    frame=resolve(raw_rows(),tmp_path)
    assert 'principal_amount_unit' not in frame and list(frame._resolved_fv_currency)==['USD']


def test_filer_reporting_dollar_values_under_foreign_unit_tags_is_not_converted(tmp_path):
    # Apollo 2025-06-30, Amey term loan: fair value fact 169.1M tagged GBP beside principal GBP 125.4M;
    # the untouched values sum to the filed total, so the tag is not the value's currency.
    source(tmp_path,currency='GBP')
    opted={'0000000123':{'foreign_unit_values':['reported_in_usd']}}
    frame=resolve_with(raw_rows(dict(fair_value='169100000',cost='168000000')),tmp_path,opted)
    assert list(frame._resolved_fv_currency)==['USD'] and list(frame._resolved_cost_currency)==['USD']
    units=json.loads(frame.iloc[0].src_facts)['_financial_units']
    assert units['fair_value']=={'unit_ref':'U001','currency':'GBP','status':'reported_in_usd'}
    assert units['cost']['status']=='reported_in_usd'
    from pipeline.monetary_fx import resolved_unit_decisions
    assert resolved_unit_decisions(frame)==[]


def test_foreign_unit_tag_still_converts_for_a_filer_without_the_setting(tmp_path):
    source(tmp_path,currency='GBP')
    frame=resolve_with(raw_rows(dict(fair_value='169100000')),tmp_path,{'0000000999':{'foreign_unit_values':['reported_in_usd']}})
    assert list(frame._resolved_fv_currency)==['GBP']
    assert json.loads(frame.iloc[0].src_facts)['_financial_units']['fair_value']['status']=='resolved'
    from pipeline.monetary_fx import resolved_unit_decisions
    assert [d['currency'] for d in resolved_unit_decisions(frame)]==['GBP']


def test_unresolved_unit_is_not_settled_by_the_setting(tmp_path):
    source(tmp_path)
    opted={'0000000123':{'foreign_unit_values':['reported_in_usd']}}
    frame=resolve_with(raw_rows(dict(fair_value_unit='missing')),tmp_path,opted)
    assert list(frame._resolved_fv_currency)==['UNRESOLVED']
