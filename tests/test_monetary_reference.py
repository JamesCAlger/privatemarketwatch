from decimal import Decimal

import duckdb
import pytest

from pipeline.field_assessment import comparison_sql
from pipeline.monetary_reference import normalize
from tests.test_financial_conventions import fx_fixture


def compare_source(*,field='fair_value',published='120',currency='GBP',published_currency='USD',
                   decisions=None,quotes=None,document_hash='a'*64,source_value='80',precision='.5'):
    source=dict(cik='123',quarter='2026-03-31',accession='A',context_id='C',field=field,
        source_complete=True,fact_count=1,variants=1,reason='ready',source_role='confirmed_position',
        correspondence_status='ready',reference_value=Decimal(source_value),precision_bound=Decimal(precision),currency=currency)
    candidate=dict(cik='123',quarter='2026-03-31',accession='A',context_id='C',field=field,
        candidate_rows=1,published=Decimal(published) if published is not None else None,published_currency=published_currency)
    with duckdb.connect() as con:
        for table,values in (('source_fields',source),('published',candidate)):
            con.execute('CREATE TABLE '+table+' AS SELECT '+','.join('? AS '+k for k in values),list(values.values()))
        con.execute("CREATE TABLE links AS SELECT '123' AS cik,'2026-03-31' AS quarter,'A' AS accession,'C' AS context_id,'R1' AS row_id")
        con.execute("CREATE TABLE document_status AS SELECT '123' AS cik,'A' AS accession,? AS source_sha256",[document_hash])
        normalize(con,quotes=quotes or [],decisions=decisions or [])
        outcome=con.execute(comparison_sql()).fetchone()[-2:]
        audit=con.execute('SELECT method,reference_value,precision_bound,quote_source_sha256 FROM monetary_reference_audit').fetchall()
        assert con.execute('SELECT count(*) FROM source_fields').fetchone()[0]==1
        return outcome,audit


@pytest.mark.parametrize('field',['fair_value','cost'])
@pytest.mark.parametrize('candidate_value',[None,'80','120'])
def test_no_adjudicated_usd_reference_means_unassessable_not_missing_or_correct(field,candidate_value):
    result,audit=compare_source(field=field,published=candidate_value)
    assert result==('disclosed_unassessable','unresolved_USD_monetary_reference')
    assert audit==[]


def test_principal_stays_comparable_in_original_unit():
    result,_=compare_source(field='principal_amount',published='80',published_currency='GBP')
    assert result==('correct','source_precision_comparison')


@pytest.mark.parametrize('value,status',[('120','correct'),('120.7','correct'),('120.8','incorrect'),(None,'missing_output')])
def test_reference_uses_source_values_and_independent_quote_leg_arithmetic(value,status):
    _,decision,quote=fx_fixture()
    result,audit=compare_source(published=value,quotes=[quote],decisions=[decision])
    assert result[0]==status
    assert len(audit)==1
    method,reference_value,precision_bound,quote_hash=audit[0]
    assert method=='report_date_reference_conversion'
    assert Decimal(reference_value)==Decimal('120')
    assert Decimal(precision_bound)==Decimal('0.75')
    assert quote_hash=='b'*64


@pytest.mark.parametrize('case,reason',[('missing','FX_unavailable'),('stale','FX_stale')])
def test_missing_and_stale_rates_are_assessment_shortfalls(case,reason):
    _,decision,quote=fx_fixture()
    quote['date']='2026-03-23'
    result,_=compare_source(published=None,decisions=[decision],quotes=[] if case=='missing' else [quote])
    assert result==('disclosed_unassessable',reason)


@pytest.mark.parametrize('change',[{'document_sha256':'c'*64},{'source_value':'81'}])
def test_unit_decision_cannot_change_a_different_source_fact(change):
    _,decision,quote=fx_fixture()
    result,audit=compare_source(decisions=[dict(decision,**change)],quotes=[quote])
    assert result==('disclosed_unassessable','unresolved_source_unit_adjudication')
    assert audit==[]


def test_adjudicated_usd_unit_corrects_reference_without_converting_principal():
    _,decision,_=fx_fixture()
    decision['currency']='USD'
    result,audit=compare_source(currency='EGP',published='80',decisions=[decision])
    assert result[0]=='correct' and audit[0][0]=='already_USD'


def test_known_usd_missing_output_still_fails_accuracy_instead_of_becoming_fx_gap():
    result,_=compare_source(currency='USD',published=None)
    assert result==('missing_output','missing_value_or_row')


def test_wrong_published_currency_still_fails_against_normalized_reference():
    _,decision,quote=fx_fixture()
    result,_=compare_source(published='120',published_currency='GBP',decisions=[decision],quotes=[quote])
    assert result==('incorrect','wrong_currency')
