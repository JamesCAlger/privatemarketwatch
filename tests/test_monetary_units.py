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
