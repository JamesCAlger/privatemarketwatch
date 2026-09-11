from decimal import Decimal

import pytest

from scripts.programme_reference.source_reader import numeric_fact, rounding_bound, currency, read_document
from scripts.programme_reference.evaluate import compare_field, match_roster, primary_error_ratio


def test_inline_units_scale_sign_and_display_precision():
    assert numeric_fact('50,510',{'scale':'3','decimals':'-3','sign':'-'})==(Decimal('-50510000'),'parsed')
    assert rounding_bound({'decimals':'-3'})==500
    assert numeric_fact('600',{'scale':'-4'})[0]==Decimal('.06')
    assert currency(['iso4217:EUR'])=='EUR'
    assert currency(['xbrli:pure']) is None
    assert currency(['iso4217:USD','xbrli:shares']) is None


def test_nil_dash_explicit_zero_and_unsupported_transform():
    assert numeric_fact('0',{})[0]==0
    assert numeric_fact('-',{})==(None,'unqualified_dash')
    assert numeric_fact('-',{'format':'ixt:zerodash'})[0]==0
    assert numeric_fact('0',{'xsi:nil':'true'})==(None,'nil')
    assert numeric_fact('1,234',{'format':'custom:mystery'})[0] is None
    assert numeric_fact('1.234,50',{'format':'ixt:num-comma-decimal'})[0]==Decimal('1234.50')


def test_source_zero_missing_candidate_and_currency_are_distinct():
    assert compare_field(0,None,rounding=0)['status']=='missing_candidate_value'
    assert compare_field(0,1,rounding=0)['status']=='value_mismatch'
    assert compare_field(0,0,rounding=0)['status']=='within_source_precision'
    assert compare_field(10,10,rounding=0,reference_currency='EUR',actual_currency='USD')['status']=='currency_mismatch'
    assert compare_field(10,10,rounding=0,reference_currency='EUR')['status']=='unresolved_candidate_currency'
    assert compare_field(10,11)['status']=='rounding_not_established'


def test_source_precision_is_not_one_percent_error_tolerance():
    assert compare_field(50_510_000,50_510_400,rounding=500)['status']=='within_source_precision'
    assert compare_field(50_510_000,50_900_000,rounding=500)['status']=='value_mismatch'


def test_roster_preserves_same_borrower_distinct_facilities_and_duplicate_penalty():
    ref=[{'key':'A:loan','fair_value':100},{'key':'A:equity','fair_value':20}]
    out=[{'key':'A:loan','fair_value':90},{'key':'A:loan','fair_value':90}]
    result=match_roster(ref,out)
    assert result['matched_rows']==1
    assert result['source_only_rows']==1
    assert result['output_only_or_duplicate_rows']==1
    assert result['fv_recall']==100/120  # source-side FV; amount error is B2
    assert result['fv_precision']==.5
    out[1]['fair_value']=80
    assert match_roster(ref,out)['fv_precision'] is None
    assert match_roster(ref,list(reversed(out)))['fv_precision'] is None


def test_roster_zero_negative_and_missing_fv_remain_in_population():
    ref=[{'key':'zero','fair_value':0},{'key':'negative','fair_value':-2},{'key':'unknown','fair_value':None}]
    result=match_roster(ref,ref)
    assert result['row_recall']==1
    assert result['source_abs_fv_known']=='2'
    assert result['fv_recall'] is None
    assert result['source_missing_fv_rows']==1
    assert match_roster([],[])['row_recall'] is None
    assert match_roster([{'key':'x'},{'key':'x'}],[])['status']=='blocked_ambiguous_reference_key'


def test_primary_anchor_errors_do_not_net_or_include_unbridged_subsidiaries():
    rows=[{'cik':'1','report_date':'Q','primary':True,'basis_verified':True,'reference':100,'actual':110},
          {'cik':'2','report_date':'Q','primary':True,'basis_verified':True,'reference':100,'actual':90},
          {'cik':'1','report_date':'Q','primary':False,'basis_verified':True,'reference':1000,'actual':0},
          {'cik':'3','report_date':'Q','primary':True,'basis_verified':False,'reference':1000,'actual':0}]
    assert primary_error_ratio(rows)['ratio']==.1
    incomplete=rows+[{'cik':'4','report_date':'Q','primary':True,'basis_verified':True,'reference':100,'actual':None}]
    assert primary_error_ratio(incomplete)['ratio'] is None
    with pytest.raises(ValueError):primary_error_ratio(rows+[rows[0]])


def test_source_reader_keeps_comparative_total_and_two_tranches_separate(tmp_path):
    p=tmp_path/'source.html'
    p.write_text('''<html><body><xbrli:context id="now"><xbrli:entity><xbrli:identifier>1</xbrli:identifier><xbrldi:typedMember dimension="InvestmentIdentifierAxis">Acme first lien</xbrldi:typedMember></xbrli:entity><xbrli:period><xbrli:instant>2026-03-31</xbrli:instant></xbrli:period></xbrli:context>
    <xbrli:context id="prior"><xbrli:entity><xbrli:identifier>1</xbrli:identifier></xbrli:entity><xbrli:period><xbrli:instant>2025-12-31</xbrli:instant></xbrli:period></xbrli:context>
    <xbrli:unit id="opaque"><xbrli:measure>iso4217:EUR</xbrli:measure></xbrli:unit>
    <!-- A comment must not crash the table-heading reader. -->
    <table><tr><td>Acme first lien</td><td><ix:nonFraction id="a" name="us-gaap:InvestmentOwnedAtFairValue" contextRef="now" unitRef="opaque" scale="3" decimals="-3">10</ix:nonFraction></td></tr>
    <tr><td>Total Safety LLC</td><td><ix:nonFraction id="b" name="us-gaap:InvestmentOwnedAtFairValue" contextRef="now" unitRef="opaque" scale="3">11</ix:nonFraction></td></tr>
    <tr><td>Prior total</td><td><ix:nonFraction id="c" name="us-gaap:InvestmentOwnedAtFairValue" contextRef="prior" unitRef="opaque">12</ix:nonFraction></td></tr></table></body></html>''',encoding='utf-8')
    result=read_document(p,'2026-03-31')
    assert len(result['source_candidates'])==2
    assert result['source_candidates'][1]['total_word_flag'] is True  # flag never auto-excludes a real company
    assert result['source_candidates'][0]['facts'][0]['currency']=='EUR'
    assert result['source_candidates'][0]['facts'][0]['value']=='10000'
    assert result['source_candidates'][0]['row_xpath']!=result['source_candidates'][1]['row_xpath']
