"""Tests for scripts/gics_quality_gate.py."""

import pandas as pd

from scripts.gics_quality_gate import (
    clean_cache,
    clean_flags,
    validate_agent_result_file,
    validate_cache,
    validate_flags,
)


def test_clean_cache_aliases_and_quarantines_invalid_labels(tmp_path, monkeypatch):
    cache_path = tmp_path / "company_gics_cache.csv"
    quarantine_path = tmp_path / "gics_cache_quarantine.csv"
    monkeypatch.setattr("scripts.gics_quality_gate.QUARANTINE_FILE", quarantine_path)

    pd.DataFrame(
        [
            {
                "company_name_norm": "acme software",
                "gics_sub_industry": "Application Software",
                "confidence": "HIGH",
                "source": "cc_skill",
                "timestamp": "2026-01-01T00:00:00+00:00",
            },
            {
                "company_name_norm": "paper co",
                "gics_sub_industry": "Paper Packaging",
                "confidence": "medium",
                "source": "cc_skill",
                "timestamp": "2026-01-01T00:00:00+00:00",
            },
            {
                "company_name_norm": "numeric code co",
                "gics_sub_industry": "45103010",
                "confidence": "high",
                "source": "cc_skill",
                "timestamp": "2026-01-01T00:00:00+00:00",
            },
            {
                "company_name_norm": "broad label co",
                "gics_sub_industry": "Capital Markets",
                "confidence": "high",
                "source": "cc_review",
                "timestamp": "2026-01-01T00:00:00+00:00",
            },
        ]
    ).to_csv(cache_path, index=False)

    summary = clean_cache(path=cache_path, apply=True)

    cleaned = pd.read_csv(cache_path, dtype=str).fillna("")
    assert summary["aliased_rows"] == 1
    assert summary["quarantined_rows"] == 2
    assert set(cleaned["company_name_norm"]) == {"acme software", "paper co"}
    assert cleaned.loc[
        cleaned["company_name_norm"] == "paper co", "gics_sub_industry"
    ].iloc[0] == "Paper & Plastic Packaging Products & Materials"
    assert cleaned.loc[
        cleaned["company_name_norm"] == "acme software", "confidence"
    ].iloc[0] == "high"

    quarantine = pd.read_csv(quarantine_path, dtype=str).fillna("")
    assert set(quarantine["company_name_norm"]) == {"numeric code co", "broad label co"}
    assert validate_cache(path=cache_path).ok


def test_clean_flags_normalizes_confidence(tmp_path):
    flags_path = tmp_path / "aggregate_header_flags.csv"
    pd.DataFrame(
        [
            {
                "name_norm": "aggregate label",
                "issuer_name_raw": "Aggregate Label",
                "verdict": "AGGREGATE_HEADER",
                "confidence": "HIGH",
                "evidence": "category label",
            },
            {
                "name_norm": "vehicle",
                "issuer_name_raw": "Vehicle",
                "verdict": "JV_SUBSIDIARY",
                "confidence": "",
                "evidence": "vehicle label",
            },
        ]
    ).to_csv(flags_path, index=False)

    summary = clean_flags(path=flags_path, apply=True)

    cleaned = pd.read_csv(flags_path, dtype=str).fillna("")
    assert summary["confidence_fixed_rows"] == 2
    assert cleaned["confidence"].tolist() == ["high", "medium"]
    assert validate_flags(path=flags_path).ok


def test_validate_agent_result_file_requires_exact_chunk_order_and_labels(tmp_path):
    result_path = tmp_path / "gics_agent_results_001.csv"
    chunk_path = tmp_path / "gics_agent_chunk_001.txt"
    chunk_path.write_text(
        "acme||Acme||1||Acme\n"
        "header||Header||2||Header\n",
        encoding="utf-8",
    )
    pd.DataFrame(
        [
            {
                "name_norm": "acme",
                "verdict": "GICS",
                "gics_sub_industry": "Application Software",
                "confidence": "high",
                "evidence": "software business",
            },
            {
                "name_norm": "header",
                "verdict": "AGGREGATE_HEADER",
                "gics_sub_industry": "",
                "confidence": "high",
                "evidence": "category label",
            },
        ]
    ).to_csv(result_path, index=False)

    assert validate_agent_result_file(result_path, chunk_path).ok


def test_validate_agent_result_file_rejects_numeric_gics(tmp_path):
    result_path = tmp_path / "gics_agent_results_001.csv"
    chunk_path = tmp_path / "gics_agent_chunk_001.txt"
    chunk_path.write_text("acme||Acme||1||Acme\n", encoding="utf-8")
    pd.DataFrame(
        [
            {
                "name_norm": "acme",
                "verdict": "GICS",
                "gics_sub_industry": "45103010",
                "confidence": "high",
                "evidence": "numeric code should not publish",
            },
        ]
    ).to_csv(result_path, index=False)

    result = validate_agent_result_file(result_path, chunk_path)
    assert not result.ok
    assert any("numeric GICS code" in detail for detail in result.details)
