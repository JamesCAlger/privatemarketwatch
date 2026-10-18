"""Highlights wrapper income_concept_fallback for interest_expense (TCW Direct Lending VIII).

10-Q 2024-09-30 (0000950170-24-125154) prints 'Interest and credit facility expenses 9,831 7,049 27,186
14,011' (us-gaap:InterestAndDebtExpense) and 'Directors fees 64' (us-gaap:NoninterestExpenseDirectorsFees).
The income concept map reads any concept containing 'interestexpense', so the directors' fee was
published as interest expense and InterestAndDebtExpense was never read.
"""
import io
import json

from lxml import etree

from pipeline.bdc_fund_income import _extract_fund_income_facts, _parse_income_contexts
from pipeline import fund_highlights_wrapper as fhw


def _tree(facts):
    xml = ('<?xml version="1.0" encoding="utf-8"?><xbrli:xbrl xmlns:xbrli="http://www.xbrl.org/2003/instance" '
           'xmlns:us-gaap="http://fasb.org/us-gaap/2024"><xbrli:context id="d1"><xbrli:entity>'
           '<xbrli:identifier scheme="http://www.sec.gov/CIK">0001825265</xbrli:identifier></xbrli:entity>'
           '<xbrli:period><xbrli:startDate>2024-07-01</xbrli:startDate><xbrli:endDate>2024-09-30</xbrli:endDate>'
           '</xbrli:period></xbrli:context>'
           + "".join('<us-gaap:%s contextRef="d1">%s</us-gaap:%s>' % (c, v, c) for c, v in facts)
           + '</xbrli:xbrl>')
    return etree.parse(io.BytesIO(xml.encode("utf-8")))


FACTS = [("GrossInvestmentIncomeOperating", "30000000"), ("NoninterestExpenseDirectorsFees", "64000"),
         ("InterestAndDebtExpense", "9831000")]
SUPPRESS = ("noninterestexpense", "repurchaseagreementsinterestexpense")
FALLBACK = (("interest_expense", "interestanddebtexpense"),)


def test_wrapper_reads_the_printed_interest_line():
    tree = _tree(FACTS)
    facts = _extract_fund_income_facts(tree, _parse_income_contexts(tree), suppress=SUPPRESS, fallback=FALLBACK)
    assert facts[0]["interest_expense"] == 9831000.0


def test_without_the_wrapper_the_directors_fee_is_read_as_before():
    # false-positive guard: a fund whose wrapper lists nothing is read exactly as before
    tree = _tree(FACTS)
    assert _extract_fund_income_facts(tree, _parse_income_contexts(tree))[0]["interest_expense"] == 64000.0


def test_fallback_never_replaces_a_filed_interest_expense():
    tree = _tree(FACTS + [("InterestExpenseBorrowings", "5000000")])
    facts = _extract_fund_income_facts(tree, _parse_income_contexts(tree), suppress=SUPPRESS, fallback=FALLBACK)
    assert facts[0]["interest_expense"] == 5000000.0


def test_wrapper_loader_admits_interest_expense_fallback(tmp_path, monkeypatch):
    wrapper = {"schema_version": "fund-highlights-wrapper.v1", "cik": "0001825265", "entity_name": "x", "version": 1,
               "income_concept_suppress": list(SUPPRESS),
               "income_concept_fallback": {"interest_expense": ["interestanddebtexpense"], "net_investment_income": ["x12345678"]}}
    path = tmp_path / "0001825265.json"
    path.write_text(json.dumps(wrapper), encoding="utf-8")
    spec = fhw._load_wrapper_from_path(path)
    assert spec.income_concept_fallback == (("interest_expense", "interestanddebtexpense"),)
