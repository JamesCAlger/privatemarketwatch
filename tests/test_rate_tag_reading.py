"""Coupon, cash margin and PIK margin tagged apart (source_encodings.rate_tag_reading)."""
from lxml import etree

from pipeline import rate_tag_reading as rtr
from pipeline.bdc_filings import _extract_investment_facts

XML = """<xbrl xmlns:us-gaap="http://fasb.org/us-gaap/2025">
  <us-gaap:InvestmentOwnedAtFairValue contextRef="pik_loan" decimals="-3">37500000</us-gaap:InvestmentOwnedAtFairValue>
  <us-gaap:InvestmentInterestRatePaidInCash contextRef="pik_loan" decimals="4">0.0263</us-gaap:InvestmentInterestRatePaidInCash>
  <us-gaap:InvestmentInterestRatePaidInKind contextRef="pik_loan" decimals="4">0.0313</us-gaap:InvestmentInterestRatePaidInKind>
  <us-gaap:InvestmentInterestRate contextRef="pik_loan" decimals="4">0.0945</us-gaap:InvestmentInterestRate>
  <us-gaap:InvestmentOwnedAtFairValue contextRef="cash_only" decimals="-3">1000000</us-gaap:InvestmentOwnedAtFairValue>
  <us-gaap:InvestmentInterestRatePaidInCash contextRef="cash_only" decimals="4">0.0700</us-gaap:InvestmentInterestRatePaidInCash>
  <us-gaap:InvestmentOwnedAtFairValue contextRef="with_spread" decimals="-3">2000000</us-gaap:InvestmentOwnedAtFairValue>
  <us-gaap:InvestmentInterestRatePaidInCash contextRef="with_spread" decimals="4">0.0250</us-gaap:InvestmentInterestRatePaidInCash>
  <us-gaap:InvestmentInterestRate contextRef="with_spread" decimals="4">0.0900</us-gaap:InvestmentInterestRate>
  <us-gaap:InvestmentBasisSpreadVariableRate contextRef="with_spread" decimals="4">0.0500</us-gaap:InvestmentBasisSpreadVariableRate>
</xbrl>"""
CONTEXTS = {name: {"is_investment": True, "period": "2025-06-30", "investment_identifier": name, "industry": "",
                   "investment_type": "", "affiliation": "", "dimensions_raw": ""}
            for name in ("pik_loan", "cash_only", "with_spread")}


def _rows(margin_rate_tags):
    tree = etree.ElementTree(etree.fromstring(XML))
    return {r["_context_id"]: r for r in _extract_investment_facts(tree, CONTEXTS, margin_rate_tags=margin_rate_tags)}


def test_the_plain_tag_is_the_coupon_and_the_paid_in_cash_tag_the_cash_margin():
    row = _rows(True)["pik_loan"]
    assert row["interest_rate"] == 0.0945 and row["basis_spread"] == 0.0263 and row["pik_rate"] == 0.0313
    assert row["interest_rate_concept"] == "bare"
    assert '"basis_spread":{"c":"investmentinterestratepaidincash","r":0.0263}' in row["src_facts"]


def test_a_context_with_no_plain_tag_reads_as_before():
    row = _rows(True)["cash_only"]
    assert row["interest_rate"] == 0.07 and row["interest_rate_concept"] == "paid_in_cash" and row["basis_spread"] is None


def test_a_tagged_spread_is_not_replaced():
    row = _rows(True)["with_spread"]
    assert row["interest_rate"] == 0.09 and row["basis_spread"] == 0.05


def test_a_filer_without_the_setting_keeps_the_first_rate_fact():
    row = _rows(False)["pik_loan"]
    assert row["interest_rate"] == 0.0263 and row["interest_rate_concept"] == "paid_in_cash" and row["basis_spread"] is None


def test_settle_without_provenance():
    facts = {"a": {"interest_rate": 0.09, "_cash_margin": 0.02}}
    assert rtr.settle(facts) == 1 and facts["a"] == {"interest_rate": 0.09, "basis_spread": 0.02}


def test_cash_rate_with_plain_spread_reads_the_plain_tag_as_the_spread():
    # Stepstone 10-K 2024-12-31, Creek Parent: plain 0.0525 (the spread), paid-in-cash 0.1275 (the cash rate)
    from pipeline import rate_tag_reading as rtr
    facts = {"both": {"interest_rate": 0.0525}, "cash_only": {}, "tagged_spread": {"basis_spread": 0.05}, "untouched": {"interest_rate": 0.09}}
    rtr.hold_cash_margin(facts["both"], 0.1275)
    rtr.hold_cash_margin(facts["cash_only"], 0.087)
    rtr.hold_cash_margin(facts["tagged_spread"], 0.087)
    marks = {}
    assert rtr.settle(facts, marks, mode="cash_rate_with_plain_spread") == 1
    assert facts["both"]["interest_rate"] == 0.1275 and facts["both"]["basis_spread"] == 0.0525
    assert facts["both"]["interest_rate_concept"] == "paid_in_cash"
    assert marks["both"]["interest_rate"] == {"c": rtr.PAID_IN_CASH, "r": 0.1275}
    assert marks["both"]["basis_spread"]["c"] == "investmentinterestrate"
    assert facts["cash_only"]["interest_rate"] == 0.087 and "basis_spread" not in facts["cash_only"]
    assert facts["tagged_spread"] == {"basis_spread": 0.05, "interest_rate": 0.087, "interest_rate_concept": "paid_in_cash"}
    assert facts["untouched"] == {"interest_rate": 0.09}
