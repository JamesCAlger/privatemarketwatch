import duckdb
import pandas as pd
import pytest

from pipeline.accounting_scope import annotate, scope_expression


def scopes(records):
    with duckdb.connect() as con:
        con.execute('CREATE TABLE h(cik VARCHAR,bdc_dimensions_raw VARCHAR,is_subsidiary VARCHAR,row_id VARCHAR)')
        con.executemany('INSERT INTO h VALUES (?,?,?,?)',records)
        expression=scope_expression('cik','bdc_dimensions_raw','is_subsidiary','row_id')
        return con.execute('SELECT '+expression+' FROM h ORDER BY row_id').fetchall()


def test_parent_and_two_subsidiary_scopes_stay_distinct():
    actual=scopes([
        ('123','investmentidentifieraxis=Acme Loan','0','a'),
        ('123','nonconsolidatedsubsidiaryaxis=JV1','1','b'),
        ('123','nonconsolidatedsubsidiaryaxis=JV2','1','c')])
    assert len(set(actual))==3
    assert actual[0]==('0000000123|parent',)


def test_affiliation_paths_do_not_create_new_accounting_scopes():
    actual=scopes([
        ('123','nonconsolidatedsubsidiaryaxis=JV1|affiliationaxis=Controlled','1','a'),
        ('123','affiliationaxis=Affiliated|nonconsolidatedsubsidiaryaxis=JV1','1','b')])
    assert actual[0]==actual[1]==('0000000123|nonconsolidatedsubsidiaryaxis=jv1',)


@pytest.mark.parametrize('dimensions',[
    '', 'nonconsolidatedsubsidiaryaxis=', 'investmentidentifieraxis=Subsidiary Holdings LLC'
])
def test_unresolved_flagged_scope_is_isolated_by_observation(dimensions):
    actual=scopes([('123',dimensions,'1','a'),('123',dimensions,'1','b')])
    assert actual==[('0000000123|unresolved:a',),('0000000123|unresolved:b',)]


def test_borrower_name_and_ordinary_affiliation_are_not_subsidiary_scope():
    actual=scopes([
        ('123','investmentidentifieraxis=Subsidiary Holdings LLC','0','a'),
        ('123','investmentidentifieraxis=Joint Venture Credit LLC|affiliationaxis=Controlled','0','b')])
    assert actual==[('0000000123|parent',),('0000000123|parent',)]


def test_reporting_axis_order_does_not_change_scope_representation():
    first='nonconsolidatedsubsidiaryaxis=SPV|equitymethodinvestmentequitymethodinvesteenameaxis=JV'
    second='equitymethodinvestmentequitymethodinvesteenameaxis=JV|nonconsolidatedsubsidiaryaxis=SPV'
    actual=scopes([('123',first,'1','a'),('123',second,'1','b')])
    expected='0000000123|equitymethodinvestmentequitymethodinvesteenameaxis=jv|nonconsolidatedsubsidiaryaxis=spv'
    assert actual==[(expected,),(expected,)]


def test_output_scope_and_record_class_follow_source_signals():
    frame = pd.DataFrame([
        dict(cik='123', row_id='parent', is_subsidiary=0, bdc_dimensions_raw='', fair_value=-5),
        dict(cik='123', row_id='child', is_subsidiary=1,
             bdc_dimensions_raw='nonconsolidatedsubsidiaryaxis=JV1', fair_value=0),
        dict(cik='123', row_id='unknown', is_subsidiary=1, bdc_dimensions_raw='', fair_value=10),
    ])
    result = annotate(frame)
    assert result.row_id.tolist() == frame.row_id.tolist()
    assert result.fair_value.tolist() == [-5, 0, 10]
    assert result.accounting_record_class.tolist() == [
        'parent_schedule', 'underlying_schedule', 'unresolved_underlying_schedule']
    assert result.accounting_scope_id.tolist() == [
        '0000000123|parent', '0000000123|nonconsolidatedsubsidiaryaxis=jv1',
        '0000000123|unresolved:unknown']
    result['accounting_scope_id'] = 'stale'
    assert annotate(result).accounting_scope_id.tolist() == annotate(frame).accounting_scope_id.tolist()


def test_empty_scope_output_keeps_the_typed_columns():
    result = annotate(pd.DataFrame(columns=['cik', 'row_id']))
    assert result.empty
    assert list(result.columns) == ['cik', 'row_id', 'accounting_scope_id', 'accounting_record_class']
