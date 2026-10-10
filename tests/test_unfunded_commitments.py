"""Undrawn commitment rows netted by the commitment the filer tags (source_encodings.unfunded_rows)."""
import json

import pytest
from lxml import etree

from pipeline import unfunded_commitments as uc

XML = """<xbrl xmlns:us-gaap="http://fasb.org/us-gaap/2025">
  <us-gaap:InvestmentCompanyFinancialCommitmentToInvesteeFutureAmount contextRef="n1">1679000</us-gaap:InvestmentCompanyFinancialCommitmentToInvesteeFutureAmount>
  <us-gaap:InvestmentCompanyFinancialCommitmentToInvesteeFutureAmount contextRef="n2">31849000</us-gaap:InvestmentCompanyFinancialCommitmentToInvesteeFutureAmount>
  <us-gaap:InvestmentCompanyFinancialCommitmentToInvesteeFutureAmount contextRef="n3">500000</us-gaap:InvestmentCompanyFinancialCommitmentToInvesteeFutureAmount>
</xbrl>"""

CONTEXTS = {
    "n1": {"period": "2026-03-31", "investment_identifier": "AGS Health LLC 1"},
    "n2": {"period": "2026-03-31", "investment_identifier": "Sotheby's, Revolver"},
    "n3": {"period": "2026-03-31", "investment_identifier": "No Such Company LLC"},
    "c30": {"period": "2026-03-31", "investment_identifier": "AGS Health LLC | Software & Services 1"},
    "c32": {"period": "2026-03-31", "investment_identifier": "AGS Health LLC | Software & Services 3"},
    "c640": {"period": "2026-03-31", "investment_identifier": "Sotheby's, Revolver | Consumer Services"},
    "p640": {"period": "2025-12-31", "investment_identifier": "Sotheby's, Revolver | Consumer Services"},
}
META = {"cik": "0001930679", "accession_number": "0001628280-26-034545"}


def _facts():
    return {
        # funded tranche: same principal as the commitment, cost below it
        "c30": {"fair_value": 1628000.0, "cost": 1675000.0, "principal_amount": 1679000.0},
        "c32": {"fair_value": 1628000.0, "cost": 1679000.0, "principal_amount": 1679000.0},
        "c640": {"fair_value": 31849000.0, "cost": 31849000.0, "principal_amount": 31849000.0},
        "p640": {"fair_value": 31849000.0, "cost": 31849000.0, "principal_amount": 31849000.0},
    }


@pytest.fixture
def netting(monkeypatch):
    monkeypatch.setattr(uc, "_netting_ciks", lambda: frozenset({"0001930679"}))


def test_a_commitment_row_is_published_net_and_keeps_its_committed_principal(netting):
    facts = _facts()
    assert uc.net_unfunded_rows(etree.ElementTree(etree.fromstring(XML)), CONTEXTS, facts, META) == 2
    assert facts["c32"]["fair_value"] == -51000.0 and facts["c32"]["cost"] == 0.0
    assert facts["c32"]["principal_amount"] == 1679000.0
    assert facts["c640"]["fair_value"] == 0.0 and facts["c640"]["cost"] == 0.0
    recorded = json.loads(facts["c32"]["src_facts"])
    assert recorded["fair_value"] == {"r": 1628000.0, "x": ["net_of_commitment:1679000.0"]}
    assert uc.net_offset(recorded["cost"]["x"]) == 1679000.0


def test_a_funded_row_and_a_row_of_another_date_are_left_alone(netting):
    facts = _facts()
    uc.net_unfunded_rows(etree.ElementTree(etree.fromstring(XML)), CONTEXTS, facts, META)
    assert facts["c30"] == {"fair_value": 1628000.0, "cost": 1675000.0, "principal_amount": 1679000.0}
    assert facts["p640"]["fair_value"] == 31849000.0


def test_a_filer_without_the_setting_is_untouched(monkeypatch):
    monkeypatch.setattr(uc, "_netting_ciks", lambda: frozenset())
    facts = _facts()
    assert uc.net_unfunded_rows(etree.ElementTree(etree.fromstring(XML)), CONTEXTS, facts, META) == 0
    assert facts == _facts()


def test_reconciliation_nets_without_recording_events(netting):
    facts = _facts()
    uc.net_unfunded_rows(etree.ElementTree(etree.fromstring(XML)), CONTEXTS, facts, META, record_events=False)
    assert facts["c640"]["fair_value"] == 0.0 and "src_facts" not in facts["c640"]


def test_the_row_whose_principal_equals_the_commitment_is_preferred():
    rows = [{"investment_identifier": "A-Lign Assurance LLC | Software 1", "cost": 3287.0, "principal_amount": 3303.0},
            {"investment_identifier": "A-Lign Assurance LLC | Software 2", "cost": 3287.0, "principal_amount": 3287.0},
            {"investment_identifier": "A-Lign Assurance LLC Holdings | Software", "cost": 9.0, "principal_amount": 9.0}]
    matched, unmatched = uc.match_commitments([("A-Lign Assurance LLC 1", 3287.0), ("A-Lign Assurance LLC 2", 3287.0),
                                               ("A-Lign Assurance LLC 3", 77.0)], rows)
    assert [row["investment_identifier"][-1] for row, _ in matched] == ["2", "1"]
    assert unmatched == [("A-Lign Assurance LLC 3", 77.0)]


def test_net_offset_ignores_other_events():
    assert uc.net_offset(["decimals_rescale:10^-3"]) == 0.0
    assert uc.net_offset(None) == 0.0


def test_the_setting_admits_one_value(tmp_path):
    from pipeline.source_encodings import load_encodings
    wrapper = {"schema_version": "bdc-xbrl-wrapper.v3", "cik": "0001930679",
               "source_encodings": {"unfunded_rows": ["net_of_tagged_commitment"]}}
    (tmp_path / "0001930679.json").write_text(json.dumps(wrapper), encoding="utf-8")
    assert load_encodings(tmp_path)["0001930679"]["unfunded_rows"] == ["net_of_tagged_commitment"]
    wrapper["source_encodings"]["unfunded_rows"] = ["drop"]
    (tmp_path / "0001930679.json").write_text(json.dumps(wrapper), encoding="utf-8")
    with pytest.raises(ValueError, match="unfunded row handling"):
        load_encodings(tmp_path)
