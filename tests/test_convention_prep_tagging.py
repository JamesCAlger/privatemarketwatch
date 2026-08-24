"""Tests for the prep-phase tagging-facts section of the convention driver.

The prompt must carry filer-authored tagging FACTS (concept usage, declared
labels, first-seen dates) but stay blind to conclusions (no sum-test results,
no S0 votes, no classifier stats).
"""

import csv

from scripts.agent_convention.run_convention import (
    _tagging_facts, _tagging_section)
from pipeline import config


def _write(p, rows, cols):
    with open(p, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)


def test_tagging_facts_and_section(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "LINKBASE_ANALYSIS_DIR", tmp_path)
    _write(tmp_path / "dataset_rate_semantics.csv", [
        {"cik": "1551901", "adsh": "a1", "period": "2024-09-30",
         "n_bare": "0", "n_cash": "209", "n_pik": "10"},
        {"cik": "1551901", "adsh": "a2", "period": "2024-12-31",
         "n_bare": "7", "n_cash": "308", "n_pik": "41"},
        {"cik": "9999999", "adsh": "zz", "period": "2024-12-31",
         "n_bare": "5", "n_cash": "0", "n_pik": "0"},
    ], ["cik", "adsh", "period", "n_bare", "n_cash", "n_pik"])
    _write(tmp_path / "dataset_pre_rate_labels.csv", [
        {"adsh": "a1", "tag": "InvestmentInterestRatePaidInCash",
         "plabel": "Interest rate, cash"},
        {"adsh": "a2", "tag": "InvestmentInterestRatePaidInKind",
         "plabel": "Interest rate, PIK"},
        {"adsh": "zz", "tag": "InvestmentInterestRate",
         "plabel": "SHOULD NOT APPEAR"},
    ], ["adsh", "tag", "plabel"])

    facts = _tagging_facts("1551901", "2024-12-31")
    assert facts["target_usage"] == {"bare": 7, "cash": 308, "pik": 41}
    assert facts["concept_first_seen"]["cash"] == "2024-09-30"
    assert facts["concept_first_seen"]["bare"] == "2024-12-31"
    assert facts["declared_labels"] == {
        "InvestmentInterestRatePaidInCash": ["Interest rate, cash"],
        "InvestmentInterestRatePaidInKind": ["Interest rate, PIK"],
    }

    section = _tagging_section(facts)
    assert "PaidInCash on 308" in section
    assert "first appears 2024-09-30" in section
    assert '"Interest rate, cash"' in section
    assert "not conclusions" in section
    # blindness: nothing verdict-like leaks into the section
    for banned in ("all_in", "cash_leg", "sum", "S0", "violation"):
        assert banned not in section


def test_tagging_facts_absent_artifacts_is_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "LINKBASE_ANALYSIS_DIR", tmp_path / "missing")
    assert _tagging_facts("1551901", "2024-12-31") == {}
    assert _tagging_section({}) == ""


def test_tagging_facts_uncovered_cik_is_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "LINKBASE_ANALYSIS_DIR", tmp_path)
    _write(tmp_path / "dataset_rate_semantics.csv", [
        {"cik": "1234", "adsh": "a1", "period": "2024-09-30",
         "n_bare": "1", "n_cash": "0", "n_pik": "0"},
    ], ["cik", "adsh", "period", "n_bare", "n_cash", "n_pik"])
    assert _tagging_facts("1551901", "2024-12-31") == {}


def test_tagging_facts_real_artifacts_stellus():
    """Live check against the real linkbase_analysis artifacts (if present)."""
    if not (config.LINKBASE_ANALYSIS_DIR / "dataset_rate_semantics.csv").exists():
        import pytest
        pytest.skip("linkbase_analysis artifacts not built")
    facts = _tagging_facts("1551901", "2025-12-31")
    assert facts, "Stellus should be covered by the dataset artifacts"
    assert facts["target_usage"]["cash"] > 0
    assert facts["concept_first_seen"]["cash"] <= "2022-12-31"
