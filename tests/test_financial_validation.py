import pytest

from pipeline.financial_validation import violations
from tests.test_holdings_finalizer import ready_holdings


def test_reported_zero_and_unknown_coupon_are_consistent():
    assert violations(ready_holdings())==[]


@pytest.mark.parametrize('change,check',[
    ({'cost':100},'financial_reported_cost_preserved'),
    ({'cost_reported':None,'cost':100,'cost_source':''},'financial_unlabelled_cost_proxy'),
    ({'interest_rate_kind':'cash','interest_rate_reported':10,'pik_rate':2,'interest_rate':10},'financial_coupon_consistency'),
    ({'interest_rate_kind':'effective_yield','interest_rate':12},'financial_coupon_consistency'),
    ({'interest_rate_kind':''},'financial_interest_rate_kind_enum'),
    ({'maturity_status':'dated','maturity_precision':'month','maturity_date':'2027-12-31'},'financial_maturity_state'),
    ({'fair_value':100,'fair_value_currency':'GBP'},'financial_fair_value_currency'),
    ({'cost':0,'cost_currency':'AUD'},'financial_cost_currency'),
])
def test_final_state_rejects_silent_contract_changes(change,check):
    frame=ready_holdings()
    for field,value in change.items(): frame[field]=value
    assert check in dict(violations(frame))


def test_complete_cash_plus_pik_remains_usable():
    frame=ready_holdings([dict(interest_rate=10,interest_rate_kind='cash',pik_rate=2)])
    assert frame.iloc[0].interest_rate==12
    assert violations(frame)==[]


def test_a_coupon_taken_from_the_pik_tag_must_be_labelled_and_equal_it():
    # Decision D-018: for a fund reviewed as filing a PIK-only coupon in the PIK tag, the published rate is
    # the PIK rate, there is no filed plain rate, and the row says where the rate came from.
    labelled=dict(interest_rate_kind='all_in',interest_rate_reported=None,pik_rate=13.25,interest_rate=13.25,
        src_transforms='interest_rate:pik_only')
    frame=ready_holdings()
    for field,value in labelled.items(): frame[field]=value
    assert violations(frame)==[]
    for change in ({'src_transforms':''},{'interest_rate':12.0},{'interest_rate_kind':'unresolved'}):
        frame=ready_holdings()
        for field,value in {**labelled,**change}.items(): frame[field]=value
        assert 'financial_coupon_consistency' in dict(violations(frame)),change
