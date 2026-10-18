"""source_encodings.whole_dollar_scale_filings: a filing printed in whole dollars whose facts mix decimals 0 and -3.

TCW Direct Lending VIII, 10-Q 2023-03-31 (0000950170-23-020390): HOP Energy prints
'Term Loan ... 22,548,887 06/17/27 22,130,144 21,218,503'; principal and fair value are tagged
decimals 0, cost decimals -3 (instance value 22,130,144,000).
"""
import json

import pytest

from pipeline.bdc_filings import _normalize_mixed_decimals_monetary_facts
from pipeline.source_encodings import load_encodings, whole_dollar_scale_filing

CIK = "0001825265"
ACC = "0000950170-23-020390"


def _facts():
    facts = {
        "hop": {"principal_amount": 22548887.0, "cost": 22130144000.0, "fair_value": 21218503.0},
        "alorica": {"principal_amount": 34202616.0, "cost": 33717954000.0, "fair_value": 33586969000.0},
        # a small line: 100x the median test would leave it at 1,000 times its value
        "revolver": {"principal_amount": 558813.0, "cost": 558813000.0, "fair_value": 551548.0},
    }
    stored = [
        ("hop", "principal_amount", 0, "investmentownedbalanceprincipalamount"),
        ("hop", "cost", -3, "investmentownedatcost"),
        ("hop", "fair_value", 0, "investmentownedatfairvalue"),
        ("alorica", "principal_amount", 0, "investmentownedbalanceprincipalamount"),
        ("alorica", "cost", -3, "investmentownedatcost"),
        ("alorica", "fair_value", -3, "investmentownedatfairvalue"),
        ("revolver", "principal_amount", 0, "investmentownedbalanceprincipalamount"),
        ("revolver", "cost", -3, "investmentownedatcost"),
        ("revolver", "fair_value", 0, "investmentownedatfairvalue"),
    ]
    return facts, stored


def test_listed_filing_reads_every_coarse_fact_at_whole_dollars():
    facts, stored = _facts()
    prov = {}
    _normalize_mixed_decimals_monetary_facts(facts, stored, prov, whole_dollar=True)
    assert facts["hop"] == {"principal_amount": 22548887.0, "cost": 22130144.0, "fair_value": 21218503.0}
    assert facts["alorica"]["fair_value"] == pytest.approx(33586969.0)
    assert facts["revolver"]["cost"] == pytest.approx(558813.0)
    assert prov["hop"]["cost"]["x"] == ["decimals_rescale:10^-3"]
    assert prov["hop"]["cost"]["r"] == 22130144000.0
    assert "fair_value" not in prov["hop"]


def test_unlisted_filing_with_the_same_facts_is_left_alone():
    # false positive guard: 4 of 9 facts at -3 is below the 75 pct dominance the shared guard needs
    facts, stored = _facts()
    _normalize_mixed_decimals_monetary_facts(facts, stored, {}, whole_dollar=False)
    assert facts["hop"]["cost"] == 22130144000.0
    assert facts["revolver"]["cost"] == 558813000.0


def test_finer_fact_is_never_multiplied_up():
    facts = {"a": {"cost": 1234.567}}
    _normalize_mixed_decimals_monetary_facts(facts, [("a", "cost", 3, "investmentownedatcost")], {}, whole_dollar=True)
    assert facts["a"]["cost"] == 1234.567


def test_lookup_is_by_cik_and_accession(tmp_path):
    wrapper = {"schema_version": "bdc-xbrl-wrapper.v3", "cik": CIK, "source_encodings": {"whole_dollar_scale_filings": [ACC]}}
    (tmp_path / (CIK + ".json")).write_text(json.dumps(wrapper), encoding="utf-8")
    encodings = load_encodings(tmp_path)
    assert whole_dollar_scale_filing({"cik": "1825265", "accession_number": ACC}, encodings)
    assert not whole_dollar_scale_filing({"cik": CIK, "accession_number": "0000950170-23-040379"}, encodings)
    assert not whole_dollar_scale_filing({"cik": "0001715933", "accession_number": ACC}, encodings)


def test_loader_rejects_a_non_accession(tmp_path):
    wrapper = {"schema_version": "bdc-xbrl-wrapper.v3", "cik": CIK, "source_encodings": {"whole_dollar_scale_filings": ["2023-03-31"]}}
    (tmp_path / (CIK + ".json")).write_text(json.dumps(wrapper), encoding="utf-8")
    with pytest.raises(ValueError):
        load_encodings(tmp_path)
