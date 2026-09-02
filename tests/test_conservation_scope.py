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


def test_quarter_scoped_override_applies_only_to_scoped_quarter(tmp_path, monkeypatch):
    """scope_quarters with ISO dates applies to exactly those quarters.

    Implemented 2026-09-02: an "all"-quarters carve-out on Q1-only evidence
    regressed the attested 2025-12-31 (Q4 anchors exclude cash, Q1 anchors
    include it). quarter=None stays fail-closed for scoped overrides.
    """
    d = tmp_path / "conservation_scope"
    d.mkdir()
    d.joinpath("200.json").write_text(json.dumps({
        "cik": "200", "include_asset_categories": ["CASH"],
        "scope_quarters": ["2026-03-31"],
        "evidence": [{"source": "filing", "quote": "x"}],
        "rationale": "r", "confidence": 0.9,
    }), encoding="utf-8")
    monkeypatch.setattr(conservation_scope, "SCOPE_DIR", d)
    assert conservation_scope.included_categories_for("200", quarter="2026-03-31") == frozenset({"CASH"})
    assert conservation_scope.included_categories_for("200", quarter="2025-12-31") == frozenset()
    assert conservation_scope.included_categories_for("200") == frozenset()
    assert conservation_scope.scope_override_for("200") == (
        frozenset({"CASH"}), frozenset({"2026-03-31"}))


def test_non_iso_scope_quarters_ignored_fail_closed(tmp_path, monkeypatch):
    """Entries that are neither "all" nor ISO dates invalidate the override."""
    d = tmp_path / "conservation_scope"
    d.mkdir()
    d.joinpath("201.json").write_text(json.dumps({
        "cik": "201", "include_asset_categories": ["CASH"],
        "scope_quarters": ["2026-Q1"],
        "evidence": [{"source": "filing", "quote": "x"}],
        "rationale": "r", "confidence": 0.9,
    }), encoding="utf-8")
    monkeypatch.setattr(conservation_scope, "SCOPE_DIR", d)
    assert conservation_scope.included_categories_for("201", quarter="2026-03-31") == frozenset()
    assert conservation_scope.scope_override_for("201") == (frozenset(), None)


def test_build_cash_filter_emits_quarter_clause(tmp_path, monkeypatch):
    """The shadow engine's SQL carve for a quarter-scoped override must be
    conditioned on report_date; an "all" override must not be."""
    import scripts.shadow_conservation_engine as eng
    d = tmp_path / "conservation_scope"
    d.mkdir()
    d.joinpath("200.json").write_text(json.dumps({
        "cik": "200", "include_asset_categories": ["CASH"],
        "scope_quarters": ["2026-03-31"],
        "evidence": [{"source": "filing", "quote": "x"}],
        "rationale": "r", "confidence": 0.9,
    }), encoding="utf-8")
    d.joinpath("300.json").write_text(json.dumps({
        "cik": "300", "include_asset_categories": ["CASH"],
        "scope_quarters": ["all"],
        "evidence": [{"source": "filing", "quote": "x"}],
        "rationale": "r", "confidence": 0.9,
    }), encoding="utf-8")
    monkeypatch.setattr(conservation_scope, "SCOPE_DIR", d)
    sql = eng.build_cash_filter()
    scoped = next(c for c in sql.split(" OR ") if "'0000000200'" in c)
    unscoped = next(c for c in sql.split(" OR ") if "'0000000300'" in c)
    assert "report_date" in scoped and "'2026-03-31'" in scoped
    assert "report_date" not in unscoped


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


def test_invalid_structure_empty_categories_or_missing_evidence(tmp_path, monkeypatch):
    """Empty include_asset_categories or missing evidence -> frozenset() and no crash (fold-in minor)."""
    d = tmp_path / "conservation_scope"
    d.mkdir()
    monkeypatch.setattr(conservation_scope, "SCOPE_DIR", d)

    # Empty include_asset_categories list -> invalid -> frozenset()
    d.joinpath("401.json").write_text(json.dumps({
        "cik": "401", "include_asset_categories": [],
        "scope_quarters": ["all"], "evidence": [{"source": "filing", "quote": "x"}],
        "rationale": "r", "confidence": 0.9,
    }), encoding="utf-8")
    assert conservation_scope.included_categories_for("401") == frozenset()

    # Missing evidence key entirely -> invalid -> frozenset()
    d.joinpath("402.json").write_text(json.dumps({
        "cik": "402", "include_asset_categories": ["CASH"],
        "scope_quarters": ["all"], "rationale": "r", "confidence": 0.9,
    }), encoding="utf-8")
    assert conservation_scope.included_categories_for("402") == frozenset()
