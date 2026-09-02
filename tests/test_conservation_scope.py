"""Tests for pipeline.conservation_scope -- per-CIK override reads."""
import json
from pipeline import conservation_scope


def test_included_categories_reads_override(tmp_path, monkeypatch):
    d = tmp_path / "conservation_scope"
    d.mkdir()
    d.joinpath("1905824.json").write_text(json.dumps(
        {"cik": "1905824", "include_asset_categories": ["CASH"],
         "scope_quarters": ["all"], "evidence": [{"source": "filing", "quote": "x"}],
         "rationale": "r", "confidence": 0.99}), encoding="utf-8")
    monkeypatch.setattr(conservation_scope, "SCOPE_DIR", d)
    assert conservation_scope.included_categories_for("1905824") == frozenset({"CASH"})
    assert conservation_scope.included_categories_for("0001905824") == frozenset({"CASH"})
    assert conservation_scope.included_categories_for("999") == frozenset()


def test_malformed_override_is_ignored(tmp_path, monkeypatch):
    d = tmp_path / "conservation_scope"
    d.mkdir()
    d.joinpath("111.json").write_text("{not json", encoding="utf-8")
    monkeypatch.setattr(conservation_scope, "SCOPE_DIR", d)
    assert conservation_scope.included_categories_for("111") == frozenset()


def test_quarter_scoped_override_is_ignored_fail_closed(tmp_path, monkeypatch):
    """scope_quarters != ["all"] is not yet implemented -- must return frozenset() (fail-closed)."""
    d = tmp_path / "conservation_scope"
    d.mkdir()
    d.joinpath("200.json").write_text(json.dumps({
        "cik": "200", "include_asset_categories": ["CASH"],
        "scope_quarters": ["2026-03-31"],
        "evidence": [{"source": "filing", "quote": "x"}],
        "rationale": "r", "confidence": 0.9,
    }), encoding="utf-8")
    monkeypatch.setattr(conservation_scope, "SCOPE_DIR", d)
    assert conservation_scope.included_categories_for("200") == frozenset()


def test_missing_scope_quarters_is_ignored_fail_closed(tmp_path, monkeypatch):
    """scope_quarters missing entirely -- must return frozenset() (fail-closed)."""
    d = tmp_path / "conservation_scope"
    d.mkdir()
    d.joinpath("300.json").write_text(json.dumps({
        "cik": "300", "include_asset_categories": ["CASH"],
        "evidence": [{"source": "filing", "quote": "x"}],
        "rationale": "r", "confidence": 0.9,
    }), encoding="utf-8")
    monkeypatch.setattr(conservation_scope, "SCOPE_DIR", d)
    assert conservation_scope.included_categories_for("300") == frozenset()
