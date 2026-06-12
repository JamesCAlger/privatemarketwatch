"""Tests for pipeline.position_match_overrides module.

Covers:
- Loading override files (valid/invalid/empty)
- Applying reject and force_pair actions
- FV tolerance matching
- CIK scoping
- Method suffix for overrides
"""

import json

import pandas as pd
import pytest

from pipeline.position_match_overrides import (
    OVERRIDE_COLUMNS,
    apply_match_overrides,
    load_position_match_overrides,
)


def _make_override_file(path, cik, overrides, schema_version="position-match-override.v1"):
    """Write a minimal override JSON file."""
    payload = {
        "schema_version": schema_version,
        "cik": cik,
        "updated_at": "2026-06-12",
        "overrides": overrides,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _make_reject_override(**kwargs):
    """Return a minimal valid reject override record."""
    base = {
        "action": "reject",
        "begin_report_date": "2024-09-30",
        "end_report_date": "2024-12-31",
        "begin_issuer_name": "Acme Corp - Term Loan",
        "end_issuer_name": "Acme Corp - Revolver",
        "begin_fair_value": "10000000",
        "end_fair_value": "7000000",
        "match_method": "C_normalized_name",
        "mechanism": "subtype_mismatch: term_loan vs revolver",
        "evidence": "instrument_description fields differ",
        "confidence": 0.90,
        "residual_risk": "Position becomes unmatched",
        "created_by": "agent",
        "review_id": "test-reject-001",
    }
    base.update(kwargs)
    return base


def _make_force_pair_override(**kwargs):
    """Return a minimal valid force_pair override record."""
    base = {
        "action": "force_pair",
        "begin_report_date": "2024-09-30",
        "end_report_date": "2024-12-31",
        "begin_issuer_name": "Acme Corp - Term Loan A",
        "end_issuer_name": "Acme Corp - Term Loan B",
        "begin_fair_value": "10000000",
        "end_fair_value": "9500000",
        "match_method": "C_normalized_name",
        "mechanism": "fv_crossover: correct pair is A->A",
        "evidence": "maturity consistency",
        "confidence": 0.85,
        "residual_risk": "May mask refinancing",
        "created_by": "agent",
        "review_id": "test-force-001",
        "replace_end_issuer_name": "Acme Corp - Term Loan A",
        "replace_end_fair_value": "9000000",
    }
    base.update(kwargs)
    return base


def _make_result_df(rows=None):
    """Build a minimal matches result DataFrame."""
    if rows is None:
        rows = [
            {
                "cik": "0001572694",
                "begin_report_date": "2024-09-30",
                "end_report_date": "2024-12-31",
                "begin_issuer_name": "Acme Corp - Term Loan",
                "end_issuer_name": "Acme Corp - Revolver",
                "begin_fair_value": 10000000,
                "end_fair_value": 7000000,
                "match_method": "C_normalized_name",
            },
            {
                "cik": "0001572694",
                "begin_report_date": "2024-09-30",
                "end_report_date": "2024-12-31",
                "begin_issuer_name": "Beta Corp - First Lien",
                "end_issuer_name": "Beta Corp - First Lien",
                "begin_fair_value": 5000000,
                "end_fair_value": 4800000,
                "match_method": "B2_exact_name",
            },
        ]
    return pd.DataFrame(rows)


# --- Loading tests ---


def test_load_empty_dir(tmp_path):
    """Empty overrides directory returns empty DataFrame."""
    override_dir = tmp_path / "overrides"
    override_dir.mkdir()
    result = load_position_match_overrides(overrides_dir=override_dir)
    assert result.empty
    assert list(result.columns) == OVERRIDE_COLUMNS


def test_load_nonexistent_dir(tmp_path):
    """Non-existent directory returns empty DataFrame."""
    result = load_position_match_overrides(overrides_dir=tmp_path / "no_such_dir")
    assert result.empty


def test_load_valid_reject(tmp_path):
    """Single reject override loads correctly."""
    override_dir = tmp_path / "overrides"
    _make_override_file(
        override_dir / "0001572694.json",
        "0001572694",
        [_make_reject_override()],
    )
    result = load_position_match_overrides(overrides_dir=override_dir)
    assert len(result) == 1
    assert result.iloc[0]["action"] == "reject"
    assert result.iloc[0]["cik"] == "0001572694"
    assert result.iloc[0]["mechanism"] == "subtype_mismatch: term_loan vs revolver"


def test_load_valid_force_pair(tmp_path):
    """force_pair override with replace fields loads correctly."""
    override_dir = tmp_path / "overrides"
    _make_override_file(
        override_dir / "0001572694.json",
        "0001572694",
        [_make_force_pair_override()],
    )
    result = load_position_match_overrides(overrides_dir=override_dir)
    assert len(result) == 1
    assert result.iloc[0]["action"] == "force_pair"
    assert result.iloc[0]["replace_end_issuer_name"] == "Acme Corp - Term Loan A"
    assert result.iloc[0]["replace_end_fair_value"] == "9000000"


def test_load_missing_required_field(tmp_path):
    """Missing required field raises ValueError."""
    override_dir = tmp_path / "overrides"
    bad_record = _make_reject_override()
    del bad_record["mechanism"]
    _make_override_file(override_dir / "bad.json", "0001572694", [bad_record])
    with pytest.raises(ValueError, match="missing required fields.*mechanism"):
        load_position_match_overrides(overrides_dir=override_dir)


def test_load_invalid_action(tmp_path):
    """Invalid action value raises ValueError."""
    override_dir = tmp_path / "overrides"
    bad_record = _make_reject_override(action="delete")
    _make_override_file(override_dir / "bad.json", "0001572694", [bad_record])
    with pytest.raises(ValueError, match="invalid action"):
        load_position_match_overrides(overrides_dir=override_dir)


def test_load_force_pair_missing_replace_fields(tmp_path):
    """force_pair without replace_end_* raises ValueError."""
    override_dir = tmp_path / "overrides"
    bad_record = _make_force_pair_override()
    del bad_record["replace_end_issuer_name"]
    del bad_record["replace_end_fair_value"]
    _make_override_file(override_dir / "bad.json", "0001572694", [bad_record])
    with pytest.raises(ValueError, match="force_pair.*replace_end_issuer_name"):
        load_position_match_overrides(overrides_dir=override_dir)


def test_load_invalid_schema_version(tmp_path):
    """Wrong schema_version raises ValueError."""
    override_dir = tmp_path / "overrides"
    _make_override_file(
        override_dir / "bad.json",
        "0001572694",
        [_make_reject_override()],
        schema_version="position-match-override.v99",
    )
    with pytest.raises(ValueError, match="unsupported schema_version"):
        load_position_match_overrides(overrides_dir=override_dir)


# --- Application tests ---


def test_apply_reject_removes_pair():
    """reject override removes the matching pair from results."""
    result_df = _make_result_df()
    overrides_df = pd.DataFrame([{
        "cik": "0001572694",
        "action": "reject",
        "begin_report_date": "2024-09-30",
        "end_report_date": "2024-12-31",
        "begin_issuer_name": "Acme Corp - Term Loan",
        "end_issuer_name": "Acme Corp - Revolver",
        "begin_fair_value": "10000000",
        "end_fair_value": "7000000",
        "match_method": "C_normalized_name",
        "mechanism": "test",
        "evidence": "test",
        "confidence": 0.9,
        "residual_risk": "test",
        "created_by": "test",
        "review_id": "test",
        "replace_end_issuer_name": "",
        "replace_end_fair_value": "",
    }])
    new_result, n_rejected, n_forced = apply_match_overrides(result_df, overrides_df)
    assert n_rejected == 1
    assert n_forced == 0
    assert len(new_result) == 1
    assert new_result.iloc[0]["begin_issuer_name"] == "Beta Corp - First Lien"


def test_apply_force_pair_replaces_end():
    """force_pair override swaps end-side columns."""
    result_df = _make_result_df([{
        "cik": "0001572694",
        "begin_report_date": "2024-09-30",
        "end_report_date": "2024-12-31",
        "begin_issuer_name": "Acme Corp - Term Loan A",
        "end_issuer_name": "Acme Corp - Term Loan B",
        "begin_fair_value": 10000000,
        "end_fair_value": 9500000,
        "match_method": "C_normalized_name",
    }])
    overrides_df = pd.DataFrame([{
        "cik": "0001572694",
        "action": "force_pair",
        "begin_report_date": "2024-09-30",
        "end_report_date": "2024-12-31",
        "begin_issuer_name": "Acme Corp - Term Loan A",
        "end_issuer_name": "Acme Corp - Term Loan B",
        "begin_fair_value": "10000000",
        "end_fair_value": "9500000",
        "match_method": "C_normalized_name",
        "mechanism": "test",
        "evidence": "test",
        "confidence": 0.85,
        "residual_risk": "test",
        "created_by": "test",
        "review_id": "test",
        "replace_end_issuer_name": "Acme Corp - Term Loan A",
        "replace_end_fair_value": "9000000",
    }])
    new_result, n_rejected, n_forced = apply_match_overrides(result_df, overrides_df)
    assert n_rejected == 0
    assert n_forced == 1
    assert new_result.iloc[0]["end_issuer_name"] == "Acme Corp - Term Loan A"
    assert str(new_result.iloc[0]["end_fair_value"]) == "9000000"


def test_apply_fv_tolerance():
    """Override matches within 1% FV tolerance."""
    result_df = _make_result_df([{
        "cik": "0001572694",
        "begin_report_date": "2024-09-30",
        "end_report_date": "2024-12-31",
        "begin_issuer_name": "Acme Corp - Term Loan",
        "end_issuer_name": "Acme Corp - Revolver",
        "begin_fair_value": 10050000,  # 0.5% difference from override
        "end_fair_value": 7020000,     # 0.3% difference from override
        "match_method": "C_normalized_name",
    }])
    overrides_df = pd.DataFrame([{
        "cik": "0001572694",
        "action": "reject",
        "begin_report_date": "2024-09-30",
        "end_report_date": "2024-12-31",
        "begin_issuer_name": "Acme Corp - Term Loan",
        "end_issuer_name": "Acme Corp - Revolver",
        "begin_fair_value": "10000000",
        "end_fair_value": "7000000",
        "match_method": "C_normalized_name",
        "mechanism": "test",
        "evidence": "test",
        "confidence": 0.9,
        "residual_risk": "test",
        "created_by": "test",
        "review_id": "test",
        "replace_end_issuer_name": "",
        "replace_end_fair_value": "",
    }])
    new_result, n_rejected, _ = apply_match_overrides(result_df, overrides_df)
    assert n_rejected == 1
    assert len(new_result) == 0


def test_apply_no_match_logs_warning(caplog):
    """Override with no matching pair logs warning."""
    result_df = _make_result_df()
    overrides_df = pd.DataFrame([{
        "cik": "0009999999",  # Different CIK
        "action": "reject",
        "begin_report_date": "2024-09-30",
        "end_report_date": "2024-12-31",
        "begin_issuer_name": "No Such Corp",
        "end_issuer_name": "No Such Corp",
        "begin_fair_value": "999",
        "end_fair_value": "999",
        "match_method": "C_normalized_name",
        "mechanism": "test",
        "evidence": "test",
        "confidence": 0.9,
        "residual_risk": "test",
        "created_by": "test",
        "review_id": "test",
        "replace_end_issuer_name": "",
        "replace_end_fair_value": "",
    }])
    import logging
    with caplog.at_level(logging.WARNING):
        new_result, n_rejected, _ = apply_match_overrides(result_df, overrides_df)
    assert n_rejected == 0
    assert len(new_result) == 2
    assert "did not match" in caplog.text


def test_apply_cik_scoping():
    """Override for CIK A doesn't affect CIK B."""
    result_df = _make_result_df([
        {
            "cik": "0001572694",
            "begin_report_date": "2024-09-30",
            "end_report_date": "2024-12-31",
            "begin_issuer_name": "Acme Corp - Term Loan",
            "end_issuer_name": "Acme Corp - Revolver",
            "begin_fair_value": 10000000,
            "end_fair_value": 7000000,
            "match_method": "C_normalized_name",
        },
        {
            "cik": "0001111111",
            "begin_report_date": "2024-09-30",
            "end_report_date": "2024-12-31",
            "begin_issuer_name": "Acme Corp - Term Loan",
            "end_issuer_name": "Acme Corp - Revolver",
            "begin_fair_value": 10000000,
            "end_fair_value": 7000000,
            "match_method": "C_normalized_name",
        },
    ])
    overrides_df = pd.DataFrame([{
        "cik": "0001572694",  # Only CIK A
        "action": "reject",
        "begin_report_date": "2024-09-30",
        "end_report_date": "2024-12-31",
        "begin_issuer_name": "Acme Corp - Term Loan",
        "end_issuer_name": "Acme Corp - Revolver",
        "begin_fair_value": "10000000",
        "end_fair_value": "7000000",
        "match_method": "C_normalized_name",
        "mechanism": "test",
        "evidence": "test",
        "confidence": 0.9,
        "residual_risk": "test",
        "created_by": "test",
        "review_id": "test",
        "replace_end_issuer_name": "",
        "replace_end_fair_value": "",
    }])
    new_result, n_rejected, _ = apply_match_overrides(result_df, overrides_df)
    assert n_rejected == 1
    assert len(new_result) == 1
    assert new_result.iloc[0]["cik"] == "0001111111"


def test_override_method_suffix():
    """force_pair appends _override to match_method."""
    result_df = _make_result_df([{
        "cik": "0001572694",
        "begin_report_date": "2024-09-30",
        "end_report_date": "2024-12-31",
        "begin_issuer_name": "Acme Corp - Term Loan A",
        "end_issuer_name": "Acme Corp - Term Loan B",
        "begin_fair_value": 10000000,
        "end_fair_value": 9500000,
        "match_method": "D_fuzzy",
    }])
    overrides_df = pd.DataFrame([{
        "cik": "0001572694",
        "action": "force_pair",
        "begin_report_date": "2024-09-30",
        "end_report_date": "2024-12-31",
        "begin_issuer_name": "Acme Corp - Term Loan A",
        "end_issuer_name": "Acme Corp - Term Loan B",
        "begin_fair_value": "10000000",
        "end_fair_value": "9500000",
        "match_method": "D_fuzzy",
        "mechanism": "test",
        "evidence": "test",
        "confidence": 0.85,
        "residual_risk": "test",
        "created_by": "test",
        "review_id": "test",
        "replace_end_issuer_name": "Acme Corp - Term Loan A",
        "replace_end_fair_value": "9000000",
    }])
    new_result, _, n_forced = apply_match_overrides(result_df, overrides_df)
    assert n_forced == 1
    assert new_result.iloc[0]["match_method"] == "D_fuzzy_override"
