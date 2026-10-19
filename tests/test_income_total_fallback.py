"""Highlights wrapper income_concept_fallback for total_investment_income (AGL Private Credit Income).

10-Q 2025-03-31 (0000950170-25-067853) prints 'Interest income $ 13,533 Total investment income 13,533 Expenses:
Interest and other financing expenses 6,699 ... Offering costs 235' and 'Net investment income (loss) 5,373'. Tags:
InvestmentIncomeInterest 13,533,000, InvestmentIncomeNet 13,533,000 (the total), InterestAndDebtExpense 6,699,000,
NoninterestExpenseOfferingCost 235,000, NetInvestmentIncome 5,373,000. The shared map reads InvestmentIncomeNet as
net investment income (first fact wins) and the offering cost as interest expense.
"""
import io
import json

from lxml import etree

from pipeline.bdc_fund_income import _extract_fund_income_facts, _parse_income_contexts
from pipeline import fund_highlights_wrapper as fhw


def _tree(facts):
    xml = ('<?xml version="1.0" encoding="utf-8"?><xbrli:xbrl xmlns:xbrli="http://www.xbrl.org/2003/instance" '
           'xmlns:us-gaap="http://fasb.org/us-gaap/2024"><xbrli:context id="d1"><xbrli:entity>'
           '<xbrli:identifier scheme="http://www.sec.gov/CIK">0002011498</xbrli:identifier></xbrli:entity>'
           '<xbrli:period><xbrli:startDate>2025-01-01</xbrli:startDate><xbrli:endDate>2025-03-31</xbrli:endDate>'
           '</xbrli:period></xbrli:context>'
           + "".join('<us-gaap:%s contextRef="d1">%s</us-gaap:%s>' % (c, v, c) for c, v in facts)
           + '</xbrli:xbrl>')
    return etree.parse(io.BytesIO(xml.encode("utf-8")))


FACTS = [("InvestmentIncomeInterest", "13533000"), ("InvestmentIncomeNet", "13533000"),
         ("InterestAndDebtExpense", "6699000"), ("NoninterestExpenseOfferingCost", "235000"),
         ("NetInvestmentIncome", "5373000")]
SUPPRESS = ("noninterestexpenseofferingcost",)
FALLBACK = (("total_investment_income", "investmentincomenet"), ("interest_expense", "interestanddebtexpense"))


def _facts(facts, **kw):
    tree = _tree(facts)
    return _extract_fund_income_facts(tree, _parse_income_contexts(tree), **kw)[0]


def test_wrapper_reads_total_income_and_the_printed_net_investment_income():
    row = _facts(FACTS, suppress=SUPPRESS, fallback=FALLBACK)
    assert row["total_investment_income"] == 13533000.0
    assert row["net_investment_income"] == 5373000.0
    assert row["interest_expense"] == 6699000.0


def test_after_tax_fallback_fills_nii_once_total_income_is_known():
    # 10-Q 2026-06-30: no NetInvestmentIncome tag, only InvestmentIncomeOperatingAfterExpenseAndTax
    facts = [f for f in FACTS if f[0] != "NetInvestmentIncome"] + [("InvestmentIncomeOperatingAfterExpenseAndTax", "14808000")]
    row = _facts(facts, suppress=SUPPRESS, fallback=FALLBACK)
    assert row["total_investment_income"] == 13533000.0
    assert row["net_investment_income"] == 14808000.0


def test_without_the_wrapper_the_total_is_read_as_net_investment_income_as_before():
    # false-positive guard: a fund whose wrapper lists nothing is read exactly as before
    row = _facts(FACTS)
    assert row["net_investment_income"] == 13533000.0
    assert "total_investment_income" not in row
    assert row["interest_expense"] == 235000.0


def test_fallback_never_replaces_a_filed_total():
    row = _facts(FACTS + [("GrossInvestmentIncomeOperating", "14000000")], suppress=SUPPRESS, fallback=FALLBACK)
    assert row["total_investment_income"] == 14000000.0


def test_a_period_with_only_the_fallback_fact_is_dropped():
    tree = _tree([("InvestmentIncomeNet", "13533000")])
    assert _extract_fund_income_facts(tree, _parse_income_contexts(tree), fallback=FALLBACK) == []


def test_wrapper_loader_admits_total_investment_income_fallback(tmp_path):
    wrapper = {"schema_version": "fund-highlights-wrapper.v1", "cik": "0002011498", "entity_name": "x", "version": 1,
               "income_concept_fallback": {"total_investment_income": ["investmentincomenet"]}}
    path = tmp_path / "0002011498.json"
    path.write_text(json.dumps(wrapper), encoding="utf-8")
    spec = fhw._load_wrapper_from_path(path)
    assert spec.income_concept_fallback == (("total_investment_income", "investmentincomenet"),)
