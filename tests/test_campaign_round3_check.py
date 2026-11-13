"""Round-3 retirement-campaign checks (scripts/v05_evidence/campaign_round3_check.py): the cited row must be
one the verdict names, and each claim fails on its realistic plant."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "v05_evidence"))

import campaign_retirement_check as base  # noqa: E402
import campaign_round3_check as c3  # noqa: E402


def test_names_in_verdict_requires_the_issuer_in_the_verdict_text():
    v = "the raw source row for Experigreen Intermediate Holdings, Inc. shows a revolver"
    assert c3.names_in_verdict("Experigreen Intermediate Holdings, Inc.", v)
    assert not c3.names_in_verdict("Acme Widgets LLC", v)
    assert not c3.names_in_verdict("ATS", "ATS appears as the portfolio company")   # too short to be sure


def test_src_bdc01_spec_reads_quoted_positions():
    v = {"culprit_citations": [{"quoted_text": "Thrasio, LLC | Common Stock | 1,234"},
                               {"quoted_text": "Total Investments | 5"}]}
    spec = c3.make_spec("SRC_BDC01", {"printed_context": ""}, v)
    assert spec["quoted_positions"] == ["Thrasio, LLC"]


@pytest.fixture
def row(monkeypatch):
    monkeypatch.setattr(base, "row_period", lambda r: (True, "ok"))
    monkeypatch.setattr(base, "row_line", lambda r: "Dreyfus Treasury Obligations Cash Management 65,057")
    return {"row_id": "R1", "cik": "0000000003", "accession_number": "A", "src_context_id": "c1",
            "issuer_name": "Dreyfus Treasury Obligations", "asset_class": "CASH", "index_classification": "CASH",
            "exposure_type": "LIQUID", "fair_value": 65_057_000.0}


@pytest.mark.parametrize("rule, field", [("C301", "index_classification"), ("C303", "exposure_type"), ("C304", "asset_class")])
def test_class_rules_pass_on_cash_class_and_fail_on_plants(row, rule, field, monkeypatch):
    monkeypatch.setattr(c3, "filing", lambda cik, acc: None)
    spec = {"anchor": "Short-Term Investments / Dreyfus Treasury Obligations Cash Management Money Market Fund"}
    assert all(ok for _, ok, _ in c3.t_cited(rule, row, spec))
    for bad in ("", "PRIVATE_EQUITY"):
        assert not all(ok for _, ok, _ in c3.t_cited(rule, dict(row, **{field: bad}), spec)), bad


def test_class_rule_with_a_named_class():
    spec = {"anchor": "COMMON_EQUITY"}
    want = c3.re.findall(r"\b[A-Z][A-Z_]{3,}\b", spec["anchor"])
    assert want == ["COMMON_EQUITY"]
