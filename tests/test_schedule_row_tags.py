"""Note contexts that reuse a schedule member are not positions (source_encodings.schedule_row_tags)."""
import pytest
from lxml import etree

from pipeline import schedule_row_tags as srt

XML = """<xbrl xmlns:us-gaap="http://fasb.org/us-gaap/2025">
  <us-gaap:InvestmentOwnedAtFairValue contextRef="row" decimals="-3">102939000</us-gaap:InvestmentOwnedAtFairValue>
  <us-gaap:InvestmentOwnedAtCost contextRef="row" decimals="-3">65683000</us-gaap:InvestmentOwnedAtCost>
  <us-gaap:InvestmentOwnedAtFairValue contextRef="rollforward" decimals="-3">102939000</us-gaap:InvestmentOwnedAtFairValue>
  <us-gaap:InvestmentOwnedAtFairValue contextRef="pct_only" decimals="-3">26000</us-gaap:InvestmentOwnedAtFairValue>
  <us-gaap:InvestmentOwnedPercentOfNetAssets contextRef="pct_only" decimals="3">0.001</us-gaap:InvestmentOwnedPercentOfNetAssets>
  <us-gaap:InvestmentOwnedAtFairValue contextRef="rounded" decimals="-3">2395000</us-gaap:InvestmentOwnedAtFairValue>
  <us-gaap:InvestmentOwnedAtCost contextRef="rounded" decimals="-5">2900000</us-gaap:InvestmentOwnedAtCost>
  <us-gaap:InvestmentInterestRate contextRef="rate_only" decimals="3">0.111</us-gaap:InvestmentInterestRate>
  <us-gaap:InvestmentOwnedAtFairValue contextRef="not_investment" decimals="-5">9000000</us-gaap:InvestmentOwnedAtFairValue>
</xbrl>"""
CONTEXTS = {name: {"is_investment": name != "not_investment"}
            for name in ("row", "rollforward", "pct_only", "rounded", "rate_only", "not_investment")}
META = {"cik": "0001859919", "accession_number": "0001859919-23-000040"}


def _tree():
    return etree.ElementTree(etree.fromstring(XML))


def test_a_context_with_no_cost_and_no_percent_or_a_rounded_value_is_not_a_row(monkeypatch):
    monkeypatch.setattr(srt, "_tagged_ciks", lambda: {"0001859919": frozenset({"cost_or_percent_unrounded"})})
    assert srt.non_schedule_contexts(_tree(), CONTEXTS, META) == {"rollforward", "rounded"}


def test_schedule_rows_and_rate_only_contexts_are_kept(monkeypatch):
    monkeypatch.setattr(srt, "_tagged_ciks", lambda: {"0001859919": frozenset({"cost_or_percent_unrounded"})})
    facts = {name: {"fair_value": 1.0} for name in CONTEXTS}
    assert srt.drop_non_schedule_contexts(_tree(), CONTEXTS, facts, META) == 2
    assert set(facts) == {"row", "pct_only", "rate_only", "not_investment"}


def test_a_filer_without_the_setting_keeps_every_context(monkeypatch):
    monkeypatch.setattr(srt, "_tagged_ciks", lambda: {})
    assert srt.non_schedule_contexts(_tree(), CONTEXTS, META) == set()


def test_the_setting_admits_one_value(tmp_path):
    import json
    from pipeline.source_encodings import load_encodings
    wrapper = {"schema_version": "bdc-xbrl-wrapper.v3", "cik": "0001859919",
               "source_encodings": {"schedule_row_tags": ["cost"]}}
    (tmp_path / "0001859919.json").write_text(json.dumps(wrapper), encoding="utf-8")
    with pytest.raises(ValueError, match="schedule row test is"):
        load_encodings(tmp_path)


def test_a_note_aggregate_with_cost_and_no_quantity_is_not_a_row(monkeypatch):
    monkeypatch.setattr(srt, "_tagged_ciks", lambda: {"0001859919": frozenset({"quantity_or_percent"})})
    # 'row' has cost and fair value only (the New Mountain non-accrual aggregate); 'pct_only' has a percent
    assert srt.non_schedule_contexts(_tree(), CONTEXTS, META) == {"row", "rollforward", "rounded"}


def test_a_commitment_table_context_is_not_a_row(monkeypatch):
    monkeypatch.setattr(srt, "_tagged_ciks", lambda: {"0001859919": frozenset({"not_commitment_only"})})
    xml = XML.replace("</xbrl>", '<us-gaap:InvestmentCompanyFinancialCommitmentToInvesteeFutureAmount contextRef="rollforward" '
                      'decimals="-3">5000</us-gaap:InvestmentCompanyFinancialCommitmentToInvesteeFutureAmount>'
                      '<us-gaap:InvestmentCompanyFinancialCommitmentToInvesteeFutureAmount contextRef="row" decimals="-3">7000'
                      '</us-gaap:InvestmentCompanyFinancialCommitmentToInvesteeFutureAmount></xbrl>')
    tree = etree.ElementTree(etree.fromstring(xml))
    # 'row' carries a cost, so it stays a schedule row even with a commitment amount
    assert srt.non_schedule_contexts(tree, CONTEXTS, META) == {"rollforward"}


def test_a_schedule_row_repeated_in_rounded_form_on_its_own_context_is_kept(monkeypatch):
    # Barings 2023-06-30, c-838: exact cost and fair value, plus the joint-venture note's rounded copies.
    xml = """<xbrl xmlns:us-gaap="http://fasb.org/us-gaap/2025">
      <us-gaap:InvestmentOwnedAtCost contextRef="both" decimals="-3">4622000</us-gaap:InvestmentOwnedAtCost>
      <us-gaap:InvestmentOwnedAtFairValue contextRef="both" decimals="-3">4534000</us-gaap:InvestmentOwnedAtFairValue>
      <us-gaap:InvestmentOwnedAtCost contextRef="both" decimals="-5">4600000</us-gaap:InvestmentOwnedAtCost>
      <us-gaap:InvestmentOwnedAtFairValue contextRef="both" decimals="-5">4500000</us-gaap:InvestmentOwnedAtFairValue>
      <us-gaap:InvestmentOwnedAtFairValue contextRef="note" decimals="-3">2395000</us-gaap:InvestmentOwnedAtFairValue>
      <us-gaap:InvestmentOwnedAtFairValue contextRef="note" decimals="-5">2400000</us-gaap:InvestmentOwnedAtFairValue>
      <us-gaap:InvestmentOwnedAtCost contextRef="note" decimals="-5">2900000</us-gaap:InvestmentOwnedAtCost>
    </xbrl>"""
    monkeypatch.setattr(srt, "_tagged_ciks", lambda: {"0001859919": frozenset({"cost_or_percent_unrounded"})})
    contexts = {"both": {"is_investment": True}, "note": {"is_investment": True}}
    assert srt.non_schedule_contexts(etree.ElementTree(etree.fromstring(xml)), contexts, META) == {"note"}


def test_cost_or_percent_keeps_a_row_whose_fair_value_is_tagged_at_decimals_minus_4(monkeypatch):
    # T Series 10-K for 2024-12-31, c-277: 'Fetch Insurance Services, LLC ... 1,707 1,677 1,690 0.16',
    # fair value 1,690,000 at decimals -4 beside an exact cost and a percent: a schedule row.
    xml = """<xbrl xmlns:us-gaap="http://fasb.org/us-gaap/2025">
      <us-gaap:InvestmentOwnedAtFairValue contextRef="fetch" decimals="-4">1690000</us-gaap:InvestmentOwnedAtFairValue>
      <us-gaap:InvestmentOwnedAtCost contextRef="fetch" decimals="-3">1677000</us-gaap:InvestmentOwnedAtCost>
      <us-gaap:InvestmentOwnedPercentOfNetAssets contextRef="fetch" decimals="4">0.0016</us-gaap:InvestmentOwnedPercentOfNetAssets>
      <us-gaap:InvestmentOwnedAtFairValue contextRef="rollforward" decimals="-3">14252000</us-gaap:InvestmentOwnedAtFairValue>
    </xbrl>"""
    contexts = {"fetch": {"is_investment": True}, "rollforward": {"is_investment": True}}
    tree = etree.ElementTree(etree.fromstring(xml))
    monkeypatch.setattr(srt, "_tagged_ciks", lambda: {"0001859919": frozenset({"cost_or_percent"})})
    assert srt.non_schedule_contexts(tree, contexts, META) == {"rollforward"}
    # the rounded variant drops the schedule row: the reason the plain test exists
    monkeypatch.setattr(srt, "_tagged_ciks", lambda: {"0001859919": frozenset({"cost_or_percent_unrounded"})})
    assert srt.non_schedule_contexts(tree, contexts, META) == {"fetch", "rollforward"}


def test_cost_or_percent_still_drops_note_rows_without_cost_or_percent(monkeypatch):
    # false positive guard: a fair-value-only note context and a rate-only context
    monkeypatch.setattr(srt, "_tagged_ciks", lambda: {"0001859919": frozenset({"cost_or_percent"})})
    assert srt.non_schedule_contexts(_tree(), CONTEXTS, META) == {"rollforward"}
