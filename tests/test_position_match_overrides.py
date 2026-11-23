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
    result = pd.DataFrame(rows)
    if "source" not in result:
        result["source"] = "bdc"
    return result


def _forced_holdings(result, overrides):
    """Explicit original and destination observations for force-pair tests."""
    original = result.iloc[0]
    replacement = overrides.iloc[0]
    base = dict(cik=original.cik, source=original.source,
                report_date=original.end_report_date,
                issuer_name=original.end_issuer_name, fair_value=original.end_fair_value,
                cost=9400000., principal_amount=9600000., interest_rate=8., basis_spread=3.,
                shares_held=10., index_classification="DIRECT_LENDING", asset_category="LOAN",
                issuer_category="CORPORATE", maturity_date="2030-06-30", coupon_type="FLOATING")
    destination = dict(base, issuer_name=replacement.replace_end_issuer_name,
                       fair_value=replacement.replace_end_fair_value,
                       cost=8900000., principal_amount=9100000., interest_rate=9., basis_spread=4.,
                       shares_held=20., maturity_date="2031-02-28", coupon_type="FIXED")
    return pd.DataFrame([base, destination])


def _whole_endpoint_case():
    directive = _make_force_pair_override(cik="0001572694")
    result = _make_result_df([{key: directive[key] for key in (
        "cik", "begin_report_date", "end_report_date", "begin_issuer_name",
        "end_issuer_name", "begin_fair_value", "end_fair_value", "match_method")}])
    overrides = pd.DataFrame([directive])
    holdings = _forced_holdings(result, overrides)
    for field in ("cost", "principal_amount", "interest_rate", "basis_spread", "shares_held"):
        result["end_" + field] = holdings.iloc[0][field]
    for field in ("index_classification", "asset_category", "issuer_category", "maturity_date", "coupon_type"):
        result[field] = holdings.iloc[0][field]
    result["begin_principal_amount"] = "10000000"
    result["match_key"] = "original-trigger-key"
    result["span_months"] = "3"
    result["match_score"] = "1"
    result["unknown_end_annotation"] = "retain custom provenance"
    return result, overrides, holdings


def test_force_pair_rebinds_complete_endpoint_and_preserves_begin_and_provenance():
    result, overrides, holdings = _whole_endpoint_case()
    holdings.loc[1, ["index_classification", "asset_category", "issuer_category"]] = ["COMMON_EQUITY", "EQUITY", "FUND"]
    original = result.copy(deep=True)
    output, rejected, forced = apply_match_overrides(result, overrides, unified_df=holdings)
    assert (rejected, forced) == (0, 1)
    for field in ("issuer_name", "fair_value", "cost", "principal_amount", "interest_rate", "basis_spread", "shares_held"):
        assert output.iloc[0]["end_" + field] == holdings.iloc[1][field]
    for field in ("index_classification", "asset_category", "issuer_category", "maturity_date", "coupon_type"):
        assert output.iloc[0][field] == holdings.iloc[1][field]
    assert output.iloc[0].begin_principal_amount == original.iloc[0].begin_principal_amount
    assert output.iloc[0].match_key == "original-trigger-key"
    assert output.iloc[0].unknown_end_annotation == "retain custom provenance"
    assert list(output.columns) == list(original.columns)
    pd.testing.assert_frame_equal(result, original)


def test_force_pair_copies_unknown_financial_value_instead_of_old_endpoint():
    result, overrides, holdings = _whole_endpoint_case()
    holdings.loc[1, "principal_amount"] = None
    output, _, _ = apply_match_overrides(result, overrides, unified_df=holdings)
    assert pd.isna(output.iloc[0].end_principal_amount)


@pytest.mark.parametrize("problem", ["missing", "duplicate", "wrong_source", "wrong_date", "wrong_cik", "near_value"])
def test_force_pair_destination_resolution_fails_closed(problem):
    result, overrides, holdings = _whole_endpoint_case()
    if problem == "missing":
        holdings = holdings.iloc[:1]
    elif problem == "duplicate":
        holdings = pd.concat([holdings, holdings.iloc[[1]]], ignore_index=True)
    elif problem == "near_value":
        holdings.loc[1, "fair_value"] = "9000001"
    else:
        field, value = {"wrong_source": ("source", "nport"), "wrong_date": ("report_date", "2025-03-31"),
                        "wrong_cik": ("cik", "0000000123")}[problem]
        holdings.loc[1, field] = value
    with pytest.raises(ValueError, match="exactly one destination"):
        apply_match_overrides(result, overrides, unified_df=holdings)


def test_force_pair_cannot_cross_accounting_scope():
    result, overrides, holdings = _whole_endpoint_case()
    holdings["is_subsidiary"] = ["0", "1"]
    with pytest.raises(ValueError, match="accounting scope"):
        apply_match_overrides(result, overrides, unified_df=holdings)


def test_force_pair_requires_destination_holdings():
    result, overrides, _ = _whole_endpoint_case()
    with pytest.raises(ValueError, match="requires unified holdings"):
        apply_match_overrides(result, overrides)


def test_one_force_directive_cannot_tolerance_match_two_pairs():
    result, overrides, holdings = _whole_endpoint_case()
    duplicate = result.copy()
    duplicate["begin_fair_value"] = "10000500"
    pairs = pd.concat([result, duplicate], ignore_index=True)
    with pytest.raises(ValueError, match="selects multiple matched pairs"):
        apply_match_overrides(pairs, overrides, unified_df=holdings)


@pytest.mark.parametrize("same_period", [True, False])
def test_forced_destination_collision_between_directives_is_period_scoped(same_period):
    result, overrides, holdings = _whole_endpoint_case()
    second = result.copy()
    second_override = overrides.copy()
    second["begin_issuer_name"] = "Another beginning"
    second_override["begin_issuer_name"] = "Another beginning"
    if not same_period:
        second["begin_report_date"] = "2024-06-30"
        second_override["begin_report_date"] = "2024-06-30"
    pairs = pd.concat([result, second], ignore_index=True)
    directives = pd.concat([overrides, second_override], ignore_index=True)
    if same_period:
        with pytest.raises(ValueError, match="share a destination"):
            apply_match_overrides(pairs, directives, unified_df=holdings)
    else:
        output, _, forced = apply_match_overrides(pairs, directives, unified_df=holdings)
        assert forced == 2
        assert output.end_principal_amount.tolist() == [9100000., 9100000.]


@pytest.mark.parametrize("same_period", [True, False])
def test_forced_destination_collision_with_ordinary_pair_is_period_scoped(same_period):
    result, overrides, holdings = _whole_endpoint_case()
    ordinary = result.copy()
    ordinary["begin_issuer_name"] = "Another beginning"
    ordinary["end_issuer_name"] = holdings.iloc[1].issuer_name
    ordinary["end_fair_value"] = holdings.iloc[1].fair_value
    if not same_period:
        ordinary["begin_report_date"] = "2024-06-30"
    pairs = pd.concat([result, ordinary], ignore_index=True)
    if same_period:
        with pytest.raises(ValueError, match="already has an ordinary matched pair"):
            apply_match_overrides(pairs, overrides, unified_df=holdings)
    else:
        output, _, forced = apply_match_overrides(pairs, overrides, unified_df=holdings)
        assert forced == 1
        pd.testing.assert_series_equal(output.iloc[1], ordinary.iloc[0], check_dtype=False, check_names=False)


def test_unmatched_force_pair_keeps_ordinary_record_unchanged():
    result, overrides, _ = _whole_endpoint_case()
    overrides["begin_issuer_name"] = "Unrelated company"
    output, rejected, forced = apply_match_overrides(result, overrides)
    assert (rejected, forced) == (0, 0)
    pd.testing.assert_frame_equal(result, output)


def test_rejected_destination_pair_does_not_block_forced_replacement():
    result, overrides, holdings = _whole_endpoint_case()
    rejected_pair = result.copy()
    rejected_pair["begin_issuer_name"] = "Another beginning"
    rejected_pair["end_issuer_name"] = holdings.iloc[1].issuer_name
    rejected_pair["end_fair_value"] = holdings.iloc[1].fair_value
    rejection = overrides.copy()
    rejection["action"] = "reject"
    rejection["begin_issuer_name"] = "Another beginning"
    rejection["end_issuer_name"] = holdings.iloc[1].issuer_name
    rejection["end_fair_value"] = holdings.iloc[1].fair_value
    output, rejected, forced = apply_match_overrides(
        pd.concat([result, rejected_pair], ignore_index=True),
        pd.concat([overrides, rejection], ignore_index=True), unified_df=holdings)
    assert (len(output), rejected, forced) == (1, 1, 1)
    assert output.iloc[0].end_principal_amount == 9100000.


@pytest.mark.parametrize("method", ["A_within_filing", "B1b_position_key"])
def test_forced_destination_identity_ignores_trigger_key_and_preserves_begin_lookup(tmp_path, method):
    from pipeline.position_matching import assign_position_ids
    from tests.test_position_matching import _make_unified

    result, overrides, holdings = _whole_endpoint_case()
    result["match_method"] = method
    overrides["match_method"] = method
    holdings["bdc_investment_identifier"] = ["raw wrong endpoint", "raw destination"]
    if method.startswith("A"):
        result["begin_issuer_name"] = "raw beginning"
        result["end_issuer_name"] = "raw wrong endpoint"
        overrides["begin_issuer_name"] = "raw beginning"
        overrides["end_issuer_name"] = "raw wrong endpoint"
    begin = dict(holdings.iloc[1], report_date="2024-09-30", fair_value="10000000",
                 bdc_investment_identifier="raw beginning")
    unified = _make_unified([begin] + holdings.to_dict("records"))
    for field in holdings.columns:
        if field not in unified:
            unified[field] = [begin[field]] + holdings[field].tolist()
    forced, _, _ = apply_match_overrides(result, overrides, unified_df=unified)
    assert forced.iloc[0].match_key == "original-trigger-key"
    assigned, pairs = assign_position_ids(unified, forced, edges_file=tmp_path / "edges.csv")
    destination = assigned.loc[(assigned.report_date == "2024-12-31") &
                               (assigned.issuer_name == overrides.iloc[0].replace_end_issuer_name)].iloc[0]
    beginning = assigned.loc[assigned.report_date == "2024-09-30"].iloc[0]
    rejected = assigned.loc[(assigned.report_date == "2024-12-31") &
                            (assigned.issuer_name != destination.issuer_name)].iloc[0]
    assert len(pairs) == 1
    assert beginning.position_id == destination.position_id == pairs.iloc[0].position_id
    assert rejected.position_id != destination.position_id


def test_forced_principal_reaches_per_unit_return_calculation(monkeypatch, tmp_path):
    from pipeline import index_returns
    from pipeline.index_returns import compute_returns
    from pipeline.position_matching import MATCH_COLUMNS

    monkeypatch.setattr(index_returns, "POSITION_RETURNS_FILE", tmp_path / "position_returns.csv")
    monkeypatch.setattr(index_returns, "INDEX_RETURNS_FILE", tmp_path / "index_returns.csv")

    result, overrides, holdings = _whole_endpoint_case()
    for column in MATCH_COLUMNS:
        if column not in result:
            result[column] = ""
    result["begin_interest_rate"] = "8"
    result["span_months"] = "3"
    result["match_score"] = "1"
    result["position_id"] = "test-position"
    forced, _, _ = apply_match_overrides(result, overrides, unified_df=holdings)
    positions, _ = compute_returns(forced,
        fee_uplift_df=pd.DataFrame(columns=["cik", "quarter", "effective_uplift"]),
        unified_pik_df=pd.DataFrame(columns=["cik", "source", "report_date", "position_id", "pik_rate"]))
    expected = (9000000 / 9100000 - 10000000 / 10000000) / (10000000 / 10000000)
    assert positions.iloc[0].capital_return == pytest.approx(expected)


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
    new_result, n_rejected, n_forced = apply_match_overrides(result_df, overrides_df,
                                                          unified_df=_forced_holdings(result_df, overrides_df))
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
    new_result, _, n_forced = apply_match_overrides(result_df, overrides_df,
                                                  unified_df=_forced_holdings(result_df, overrides_df))
    assert n_forced == 1
    assert new_result.iloc[0]["match_method"] == "D_fuzzy_override"
