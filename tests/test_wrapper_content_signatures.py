"""Tests for the wrapper content signature engine (v2 wrapper system)."""

import json

import pandas as pd
import pytest

from pipeline.wrapper_content_signatures import (
    Archetype,
    EdgeCase,
    FieldSignature,
    FVReconciliation,
    PositionCountQoQ,
    RateSanity,
    WrapperDefinition,
    _DEFAULT_ARCHETYPE_SIGNATURES,
    _parse_definition,
    classify_archetype,
    classify_content_signature_rows,
    load_wrapper_definition,
    validate_content_signatures,
    validate_fv_reconciliation,
    run_qoq_drift,
    _detect_edge_cases,
    _field_is_present,
    _load_holdings_for_cik,
)


# ---------------------------------------------------------------------------
# Fixture: minimal wrapper definition for testing
# ---------------------------------------------------------------------------


def _make_wrapper(
    archetypes=None,
    fv_recon=None,
    pos_qoq=None,
    rate_sanity=None,
    edge_cases=(),
) -> WrapperDefinition:
    """Build a test WrapperDefinition."""
    if archetypes is None:
        archetypes = (
            Archetype(
                name="senior_secured_debt",
                description="Debt",
                keywords=("First lien", "Senior secured loan", "Term loan"),
                keyword_mode="any",
                field_signatures=(
                    FieldSignature("interest_rate", "numeric_range", "required", min_val=0.01, max_val=0.25),
                    FieldSignature("basis_spread", "numeric_range", "optional", min_val=0.01, max_val=0.15),
                    FieldSignature("shares_held", "presence", "forbidden"),
                    FieldSignature("fair_value", "numeric_range", "required", min_val=-1e8, max_val=1e11),
                ),
            ),
            Archetype(
                name="equity",
                description="Equity",
                keywords=("Common stock", "Preferred shares", "LLC interest"),
                keyword_mode="any",
                field_signatures=(
                    FieldSignature("shares_held", "presence", "required"),
                    FieldSignature("interest_rate", "presence", "forbidden"),
                    FieldSignature("basis_spread", "presence", "forbidden"),
                    FieldSignature("fair_value", "numeric_range", "required", min_val=-1e8, max_val=1e11),
                ),
            ),
            Archetype(
                name="clo",
                description="CLO",
                keywords=("Collateralized loan obligation", "CLO"),
                keyword_mode="any",
                field_signatures=(
                    FieldSignature("interest_rate", "numeric_range", "required", min_val=0.01, max_val=0.25),
                    FieldSignature("basis_spread", "numeric_range", "required", min_val=0.01, max_val=0.15),
                ),
            ),
            Archetype(
                name="warrant",
                description="Warrant",
                keywords=("Warrant",),
                keyword_mode="any",
                field_signatures=(
                    FieldSignature("interest_rate", "presence", "forbidden"),
                    FieldSignature("basis_spread", "presence", "forbidden"),
                ),
            ),
        )
    return WrapperDefinition(
        cik="0001918712",
        entity_name="Ares Strategic Income Fund",
        version=1,
        archetypes=archetypes,
        fv_reconciliation=fv_recon,
        position_count_qoq=pos_qoq,
        rate_sanity=rate_sanity,
        edge_cases=edge_cases,
    )


# ---------------------------------------------------------------------------
# Schema loading tests
# ---------------------------------------------------------------------------


def test_load_wrapper_definition_for_ares():
    """Loading Ares CIK returns a valid WrapperDefinition."""
    wrapper = load_wrapper_definition("0001918712")
    assert wrapper is not None
    assert wrapper.cik == "0001918712"
    assert wrapper.entity_name == "Ares Strategic Income Fund"
    assert len(wrapper.archetypes) == 4
    archetype_names = {a.name for a in wrapper.archetypes}
    assert "senior_secured_debt" in archetype_names
    assert "equity" in archetype_names
    assert "clo" in archetype_names
    assert "warrant" in archetype_names


def test_load_wrapper_definition_missing_cik_returns_none():
    """Missing CIK returns None, not an error."""
    wrapper = load_wrapper_definition("0000000000")
    assert wrapper is None


def test_load_wrapper_definition_normalizes_cik():
    """Bare numeric CIK is zero-padded before lookup."""
    wrapper = load_wrapper_definition("1918712")
    assert wrapper is not None
    assert wrapper.cik == "0001918712"


def test_load_wrapper_definition_has_invariants():
    """Ares wrapper includes FV reconciliation and position count invariants."""
    wrapper = load_wrapper_definition("0001918712")
    assert wrapper is not None
    assert wrapper.fv_reconciliation is not None
    assert wrapper.fv_reconciliation.source_field == "investments_at_fair_value"
    assert wrapper.fv_reconciliation.tolerance_pct == 0.05
    assert wrapper.position_count_qoq is not None
    assert wrapper.rate_sanity is not None


def test_load_wrapper_definition_has_edge_cases():
    """Ares wrapper includes known edge cases."""
    wrapper = load_wrapper_definition("0001918712")
    assert wrapper is not None
    assert len(wrapper.edge_cases) > 0
    ids = {ec.id for ec in wrapper.edge_cases}
    assert "pipe_delimited_rows" in ids
    assert "bare_fund_vehicle" in ids


def test_blue_owl_tech_content_signatures_cover_explicit_instruments():
    """Blue Owl Technology archetypes cover explicit instrument text without bare-name promotion."""
    wrapper = load_wrapper_definition("0001869453")
    assert wrapper is not None

    assert classify_archetype(
        wrapper,
        "Armstrong Bidco Limited | First lien senior secured GBP delayed draw term loan",
    ) == "debt"
    assert classify_archetype(
        wrapper,
        "Anaplan, Inc., Firs lien senior secured revolving loan",
    ) == "debt"
    assert classify_archetype(
        wrapper,
        "KWOL Acquisition Inc. (dba Worldwide Clinical Trials), Common stock",
    ) == "equity"
    assert classify_archetype(wrapper, "LSI Financing 1 DAC") is None
    assert classify_archetype(wrapper, "BOCSO") is None


# ---------------------------------------------------------------------------
# Archetype classification tests
# ---------------------------------------------------------------------------


def test_classify_debt_archetype():
    wrapper = _make_wrapper()
    assert classify_archetype(wrapper, "First lien senior secured loan") == "senior_secured_debt"
    assert classify_archetype(wrapper, "ABC Corp, Senior secured loan, SOFR+5%") == "senior_secured_debt"
    assert classify_archetype(wrapper, "Acme LLC, Term loan B") == "senior_secured_debt"


def test_classify_equity_archetype():
    wrapper = _make_wrapper()
    assert classify_archetype(wrapper, "Acme Holdings, Common stock") == "equity"
    assert classify_archetype(wrapper, "XYZ Corp, Preferred shares") == "equity"
    assert classify_archetype(wrapper, "Vehicle LLC, LLC interest") == "equity"


def test_classify_clo_archetype():
    wrapper = _make_wrapper()
    assert classify_archetype(wrapper, "Some CLO Fund, Collateralized loan obligation") == "clo"
    assert classify_archetype(wrapper, "CLO tranche A notes") == "clo"


def test_classify_warrant_archetype():
    wrapper = _make_wrapper()
    assert classify_archetype(wrapper, "Acme Corp, Warrant") == "warrant"


def test_classify_no_match_returns_none():
    wrapper = _make_wrapper()
    assert classify_archetype(wrapper, "Some random text") is None
    assert classify_archetype(wrapper, "") is None


def test_classify_archetype_case_insensitive():
    wrapper = _make_wrapper()
    assert classify_archetype(wrapper, "FIRST LIEN SENIOR SECURED LOAN") == "senior_secured_debt"
    assert classify_archetype(wrapper, "common STOCK holding") == "equity"


def test_classify_pipe_separated_debt():
    """Pipe-separated format should still match keywords."""
    wrapper = _make_wrapper()
    result = classify_archetype(wrapper, "Acme Corp | First lien senior secured loan | SOFR+5%")
    assert result == "senior_secured_debt"


# ---------------------------------------------------------------------------
# Content signature pass/fail tests
# ---------------------------------------------------------------------------


def test_signature_pass_debt_rate_in_range():
    """Debt row with rate in range passes all signatures."""
    wrapper = _make_wrapper()
    df = pd.DataFrame([{
        "report_date": "2024-12-31",
        "instrument_description": "Acme Corp, First lien senior secured loan",
        "interest_rate": 0.08,
        "basis_spread": 0.05,
        "fair_value": 5000000,
        "shares_held": None,
    }])
    summary, violations = validate_content_signatures(wrapper, df)
    assert len(violations) == 0
    assert summary.iloc[0]["pass_rate"] == 1.0


def test_signature_fail_rate_above_max():
    """Debt row with rate above max fails numeric_range check."""
    wrapper = _make_wrapper()
    df = pd.DataFrame([{
        "report_date": "2024-12-31",
        "instrument_description": "Acme Corp, First lien senior secured loan",
        "interest_rate": 0.30,  # Above 0.25 max
        "basis_spread": 0.05,
        "fair_value": 5000000,
        "shares_held": None,
    }])
    summary, violations = validate_content_signatures(wrapper, df)
    assert len(violations) >= 1
    rate_violations = [v for v in violations if v.field_name == "interest_rate"]
    assert len(rate_violations) == 1
    assert "above max" in rate_violations[0].reason
    assert summary.iloc[0]["fail_rows"] == 1


def test_signature_fail_rate_below_min():
    """Debt row with rate below min fails."""
    wrapper = _make_wrapper()
    df = pd.DataFrame([{
        "report_date": "2024-12-31",
        "instrument_description": "Acme Corp, First lien senior secured loan",
        "interest_rate": 0.001,  # Below 0.01 min
        "fair_value": 5000000,
        "shares_held": None,
    }])
    summary, violations = validate_content_signatures(wrapper, df)
    rate_violations = [v for v in violations if v.field_name == "interest_rate"]
    assert len(rate_violations) == 1
    assert "below min" in rate_violations[0].reason


def test_signature_fail_forbidden_field_present():
    """Debt row with shares_held present (forbidden) fails."""
    wrapper = _make_wrapper()
    df = pd.DataFrame([{
        "report_date": "2024-12-31",
        "instrument_description": "Acme Corp, First lien senior secured loan",
        "interest_rate": 0.08,
        "fair_value": 5000000,
        "shares_held": 1000,  # Forbidden for debt
    }])
    summary, violations = validate_content_signatures(wrapper, df)
    shares_violations = [v for v in violations if v.field_name == "shares_held"]
    assert len(shares_violations) == 1
    assert "forbidden" in shares_violations[0].reason


def test_signature_fail_required_field_missing():
    """Equity row with shares_held missing (required) fails."""
    wrapper = _make_wrapper()
    df = pd.DataFrame([{
        "report_date": "2024-12-31",
        "instrument_description": "Acme Corp, Common stock",
        "interest_rate": None,
        "basis_spread": None,
        "fair_value": 5000000,
        "shares_held": None,  # Required for equity but missing
    }])
    summary, violations = validate_content_signatures(wrapper, df)
    shares_violations = [v for v in violations if v.field_name == "shares_held"]
    assert len(shares_violations) == 1
    assert "required but missing" in shares_violations[0].reason


def test_equity_null_rate_not_a_violation():
    """Equity row with null interest_rate is not a violation (forbidden + absent = pass)."""
    wrapper = _make_wrapper()
    df = pd.DataFrame([{
        "report_date": "2024-12-31",
        "instrument_description": "Acme Corp, Common stock",
        "interest_rate": None,
        "basis_spread": None,
        "fair_value": 5000000,
        "shares_held": 1000,
    }])
    summary, violations = validate_content_signatures(wrapper, df)
    assert len(violations) == 0
    assert summary.iloc[0]["pass_rate"] == 1.0


def test_unclassified_rows_are_not_signature_failures():
    """Rows that don't match any archetype should not be counted as failures."""
    wrapper = _make_wrapper()
    df = pd.DataFrame([{
        "report_date": "2024-12-31",
        "instrument_description": "Some random holding XYZ",
        "interest_rate": 999,  # Would fail any range check
        "fair_value": 5000000,
        "shares_held": None,
    }])
    summary, violations = validate_content_signatures(wrapper, df)
    assert len(violations) == 0
    assert summary.iloc[0]["unclassified_rows"] == 1
    assert summary.iloc[0]["pass_rate"] == 1.0


def test_classify_content_signature_rows_uses_wrapper_leaf_family_fallback():
    """Row classification should expose the same wrapper-family fallback as validation."""
    wrapper = WrapperDefinition(
        cik="0000000099",
        entity_name="Test BDC",
        version=1,
        archetypes=(
            Archetype(
                name="debt",
                description="Debt",
                keywords=("term loan",),
                keyword_mode="any",
                field_signatures=(),
            ),
        ),
    )
    df = pd.DataFrame([{
        "report_date": "2025-03-31",
        "instrument_description": "",
        "bdc_investment_identifier": "Apex Service Partners LLC 3",
        "wrapper_family": "debt",
        "wrapper_disposition": "debt_position_leaf",
        "fair_value": "56000000",
    }])

    rows = classify_content_signature_rows(wrapper, df)

    assert list(rows.columns) == [
        "row_index",
        "report_date",
        "classification_text",
        "archetype",
        "fair_value",
    ]
    assert rows.iloc[0]["classification_text"] == "Apex Service Partners LLC 3"
    assert rows.iloc[0]["archetype"] == "debt"
    assert rows.iloc[0]["fair_value"] == 56000000.0


def test_classify_content_signature_rows_leaves_unknown_rows_unclassified():
    wrapper = _make_wrapper()
    df = pd.DataFrame([{
        "report_date": "2024-12-31",
        "instrument_description": "Unmapped co-investment program",
        "fair_value": "-250000",
    }])

    rows = classify_content_signature_rows(wrapper, df)

    assert rows.iloc[0]["archetype"] == ""
    assert rows.iloc[0]["fair_value"] == 250000.0


def test_load_holdings_for_cik_filters_raw_to_current_fv_position_leaves(monkeypatch, tmp_path):
    raw_path = tmp_path / "bdc_holdings.csv"
    pd.DataFrame([
        {
            "cik": "0001377936",
            "report_date": "2024-11-30",
            "period": "2024-11-30",
            "investment_identifier": (
                "GoReact - Education Software - First Lien Term Loan "
                "(3M USD TERM SOFR+7.50%), 12.17% Cash/1.00% PIK, 1/17/2025"
            ),
            "fair_value": "8142981",
            "cost": "8139422",
        },
        {
            "cik": "0001377936",
            "report_date": "2024-11-30",
            "period": "2024-02-29",
            "investment_identifier": (
                "GoReact - Education Software - First Lien Term Loan "
                "(3M USD TERM SOFR+7.50%), 13.03% Cash/1.00% PIK, 1/17/2025"
            ),
            "fair_value": "8087775",
            "cost": "8060498",
        },
        {
            "cik": "0001377936",
            "report_date": "2024-11-30",
            "period": "2024-11-30",
            "investment_identifier": "TOTAL INVESTMENTS - 256.5%",
            "fair_value": "960093232",
            "cost": "940000000",
        },
        {
            "cik": "0001377936",
            "report_date": "2024-11-30",
            "period": "2024-11-30",
            "investment_identifier": (
                "GoReact - Education Software - Delayed Draw Term Loan "
                "(3M USD TERM SOFR+7.50%), 12.17% Cash/1.00% PIK, 1/17/2025"
            ),
            "fair_value": "",
            "cost": "",
        },
    ]).to_csv(raw_path, index=False)
    monkeypatch.setattr("pipeline.wrapper_content_signatures.BDC_HOLDINGS_FILE", raw_path)

    result = _load_holdings_for_cik("1377936")

    assert len(result) == 1
    assert "GoReact" in result.iloc[0]["investment_identifier"]
    assert result.iloc[0]["fair_value"] == 8142981


# ---------------------------------------------------------------------------
# FV reconciliation tests
# ---------------------------------------------------------------------------


def test_fv_reconciliation_within_tolerance_passes():
    """Position FV sum within tolerance of fund-level anchor passes."""
    wrapper = _make_wrapper(
        fv_recon=FVReconciliation("investments_at_fair_value", 0.05, 5000000),
    )
    holdings = pd.DataFrame([
        {"report_date": "2024-12-31", "fair_value": 100000000, "cik": "0001918712"},
        {"report_date": "2024-12-31", "fair_value": 50000000, "cik": "0001918712"},
    ])
    financials = pd.DataFrame([
        {"report_date": "2024-12-31", "investments_at_fair_value": 155000000, "cik": "0001918712"},
    ])
    result = validate_fv_reconciliation(wrapper, holdings, financials)
    assert len(result) == 1
    assert result.iloc[0]["status"] == "pass"


def test_fv_reconciliation_outside_tolerance_fails():
    """Position FV sum far from fund-level anchor fails."""
    wrapper = _make_wrapper(
        fv_recon=FVReconciliation("investments_at_fair_value", 0.05, 5000000),
    )
    holdings = pd.DataFrame([
        {"report_date": "2024-12-31", "fair_value": 100000000, "cik": "0001918712"},
    ])
    financials = pd.DataFrame([
        {"report_date": "2024-12-31", "investments_at_fair_value": 200000000, "cik": "0001918712"},
    ])
    result = validate_fv_reconciliation(wrapper, holdings, financials)
    assert len(result) == 1
    assert result.iloc[0]["status"] == "fail"


def test_fv_reconciliation_no_invariant_returns_empty():
    """No fv_reconciliation invariant returns empty DataFrame."""
    wrapper = _make_wrapper(fv_recon=None)
    holdings = pd.DataFrame([
        {"report_date": "2024-12-31", "fair_value": 100000000, "cik": "0001918712"},
    ])
    financials = pd.DataFrame([
        {"report_date": "2024-12-31", "investments_at_fair_value": 100000000, "cik": "0001918712"},
    ])
    result = validate_fv_reconciliation(wrapper, holdings, financials)
    assert result.empty


def test_fv_reconciliation_abs_tolerance_prevents_false_positive():
    """Small absolute difference within abs tolerance passes even if pct is above threshold."""
    wrapper = _make_wrapper(
        fv_recon=FVReconciliation("investments_at_fair_value", 0.01, 10000000),
    )
    holdings = pd.DataFrame([
        {"report_date": "2024-12-31", "fair_value": 5000000, "cik": "0001918712"},
    ])
    financials = pd.DataFrame([
        # 100% pct diff, but only $5M absolute diff which is under $10M abs tolerance
        {"report_date": "2024-12-31", "investments_at_fair_value": 10000000, "cik": "0001918712"},
    ])
    result = validate_fv_reconciliation(wrapper, holdings, financials)
    assert len(result) == 1
    # pct_diff is 0.5 (>0.01 tolerance_pct), but abs_diff is $5M (<$10M tolerance_abs)
    # The logic requires BOTH pct and abs to exceed tolerance to fail
    assert result.iloc[0]["status"] == "pass"


# ---------------------------------------------------------------------------
# QoQ drift detection tests
# ---------------------------------------------------------------------------


def test_qoq_drift_position_count_spike_flagged():
    """A >200% QoQ position count increase is flagged."""
    wrapper = _make_wrapper(
        pos_qoq=PositionCountQoQ(max_increase_pct=2.0, max_decrease_pct=0.5),
        archetypes=(),  # No archetypes so all rows are unclassified (pass)
    )
    # Q1: 10 rows, Q2: 25 rows (250% = spike)
    rows = []
    for i in range(10):
        rows.append({"report_date": "2024-03-31", "instrument_description": f"Row {i}"})
    for i in range(25):
        rows.append({"report_date": "2024-06-30", "instrument_description": f"Row {i}"})
    df = pd.DataFrame(rows)

    drift_summary, _, _, _ = run_qoq_drift(wrapper, df)

    assert "qoq_drift_flag" in drift_summary.columns
    q2_row = drift_summary[drift_summary["report_date"] == "2024-06-30"]
    assert len(q2_row) == 1
    assert "position_count_spike" in q2_row.iloc[0]["qoq_drift_flag"]


def test_qoq_drift_stable_quarters_pass():
    """Stable position counts do not trigger drift flags."""
    wrapper = _make_wrapper(
        pos_qoq=PositionCountQoQ(max_increase_pct=2.0, max_decrease_pct=0.5),
        archetypes=(),
    )
    rows = []
    for i in range(10):
        rows.append({"report_date": "2024-03-31", "instrument_description": f"Row {i}"})
    for i in range(12):  # 120% = within 200% threshold
        rows.append({"report_date": "2024-06-30", "instrument_description": f"Row {i}"})
    df = pd.DataFrame(rows)

    drift_summary, _, _, _ = run_qoq_drift(wrapper, df)

    assert "qoq_drift_flag" in drift_summary.columns
    # Neither quarter should have drift flags (first quarter has no previous)
    assert all(drift_summary["qoq_drift_flag"].fillna("").eq(""))


def test_qoq_drift_position_count_drop_flagged():
    """A >50% QoQ position count decrease is flagged."""
    wrapper = _make_wrapper(
        pos_qoq=PositionCountQoQ(max_increase_pct=2.0, max_decrease_pct=0.5),
        archetypes=(),
    )
    rows = []
    for i in range(20):
        rows.append({"report_date": "2024-03-31", "instrument_description": f"Row {i}"})
    for i in range(5):  # 25% = below 50% threshold
        rows.append({"report_date": "2024-06-30", "instrument_description": f"Row {i}"})
    df = pd.DataFrame(rows)

    drift_summary, _, _, _ = run_qoq_drift(wrapper, df)

    q2_row = drift_summary[drift_summary["report_date"] == "2024-06-30"]
    assert "position_count_drop" in q2_row.iloc[0]["qoq_drift_flag"]


def test_new_delimiter_edge_case_flagged():
    """Edge case detection finds pipe-delimited rows."""
    wrapper = _make_wrapper(
        edge_cases=(
            EdgeCase(
                id="pipe_delimited",
                description="Pipe-delimited rows",
                first_seen_quarter="2025-12-31",
                detection_pattern=r"\|",
                disposition="warn",
            ),
        ),
        archetypes=(),
    )
    df = pd.DataFrame([
        {"report_date": "2024-12-31", "instrument_description": "Acme Corp, First lien loan, 8%"},
        {"report_date": "2025-12-31", "instrument_description": "Beta Corp | First lien loan | 7%"},
        {"report_date": "2025-12-31", "instrument_description": "Gamma Corp, First lien loan, 9%"},
    ])

    edge_cases = _detect_edge_cases(wrapper, df)

    assert len(edge_cases) == 1
    assert edge_cases.iloc[0]["edge_case_id"] == "pipe_delimited"
    assert edge_cases.iloc[0]["report_date"] == "2025-12-31"
    assert edge_cases.iloc[0]["match_count"] == 1


# ---------------------------------------------------------------------------
# False positive guard tests
# ---------------------------------------------------------------------------


def test_normal_organic_growth_not_flagged():
    """Normal 50% quarter-over-quarter growth is within bounds."""
    wrapper = _make_wrapper(
        pos_qoq=PositionCountQoQ(max_increase_pct=2.0, max_decrease_pct=0.5),
        archetypes=(),
    )
    rows = []
    for i in range(100):
        rows.append({"report_date": "2024-03-31", "instrument_description": f"Row {i}"})
    for i in range(150):  # 150% of previous
        rows.append({"report_date": "2024-06-30", "instrument_description": f"Row {i}"})
    df = pd.DataFrame(rows)

    drift_summary, _, _, _ = run_qoq_drift(wrapper, df)

    # No flags for normal growth
    assert all(drift_summary["qoq_drift_flag"].fillna("").eq(""))


def test_null_rate_on_equity_not_violation():
    """Null interest_rate on equity is expected (forbidden + absent = pass)."""
    wrapper = _make_wrapper()
    df = pd.DataFrame([{
        "report_date": "2024-12-31",
        "instrument_description": "Acme Corp, Common stock",
        "interest_rate": None,
        "basis_spread": None,
        "fair_value": 1000000,
        "shares_held": 500,
    }])
    summary, violations = validate_content_signatures(wrapper, df)
    assert len(violations) == 0


def test_field_is_present_helper():
    """_field_is_present correctly identifies present/absent values."""
    assert _field_is_present(0.05) is True
    assert _field_is_present(0) is True
    assert _field_is_present("hello") is True
    assert _field_is_present(None) is False
    assert _field_is_present("") is False
    assert _field_is_present(float("nan")) is False
    assert _field_is_present("nan") is False
    assert _field_is_present("None") is False


# ---------------------------------------------------------------------------
# Integration: full QoQ drift run
# ---------------------------------------------------------------------------


def test_run_qoq_drift_returns_four_dataframes():
    """run_qoq_drift returns (summary, violations, fv_recon, edge_cases)."""
    wrapper = _make_wrapper(
        fv_recon=FVReconciliation("investments_at_fair_value", 0.05, 5000000),
        pos_qoq=PositionCountQoQ(max_increase_pct=2.0, max_decrease_pct=0.5),
        edge_cases=(
            EdgeCase("test_ec", "Test edge case", "2024-12-31", "test_pattern", "warn"),
        ),
    )
    df = pd.DataFrame([
        {
            "report_date": "2024-12-31",
            "instrument_description": "Acme Corp, First lien senior secured loan",
            "interest_rate": 0.08,
            "fair_value": 5000000,
            "shares_held": None,
            "cik": "0001918712",
        },
    ])
    fund_fin = pd.DataFrame([
        {"report_date": "2024-12-31", "investments_at_fair_value": 5200000, "cik": "0001918712"},
    ])

    drift_summary, violations_df, fv_recon, edge_cases = run_qoq_drift(
        wrapper, df, fund_fin,
    )

    assert isinstance(drift_summary, pd.DataFrame)
    assert isinstance(violations_df, pd.DataFrame)
    assert isinstance(fv_recon, pd.DataFrame)
    assert isinstance(edge_cases, pd.DataFrame)
    assert len(drift_summary) == 1
    assert drift_summary.iloc[0]["pass_rate"] == 1.0
    assert len(fv_recon) == 1
    assert fv_recon.iloc[0]["status"] == "pass"


def test_multiple_quarters_signature_summary():
    """Summary has one row per quarter with correct counts."""
    wrapper = _make_wrapper()
    df = pd.DataFrame([
        {
            "report_date": "2024-09-30",
            "instrument_description": "Acme, First lien senior secured loan",
            "interest_rate": 0.08,
            "fair_value": 5000000,
            "shares_held": None,
        },
        {
            "report_date": "2024-09-30",
            "instrument_description": "Beta, Common stock",
            "interest_rate": None,
            "fair_value": 1000000,
            "shares_held": 100,
            "basis_spread": None,
        },
        {
            "report_date": "2024-12-31",
            "instrument_description": "Gamma, First lien senior secured loan",
            "interest_rate": 0.50,  # Will fail
            "fair_value": 3000000,
            "shares_held": None,
        },
    ])

    summary, violations = validate_content_signatures(wrapper, df)

    assert len(summary) == 2
    q3 = summary[summary["report_date"] == "2024-09-30"].iloc[0]
    q4 = summary[summary["report_date"] == "2024-12-31"].iloc[0]
    assert q3["total_rows"] == 2
    assert q3["fail_rows"] == 0
    assert q4["total_rows"] == 1
    assert q4["fail_rows"] == 1


# ---------------------------------------------------------------------------
# Default archetype field signature tests
# ---------------------------------------------------------------------------


def test_default_signatures_applied_to_equity_archetype():
    """Equity archetype with only FV signature gets basis_spread:forbidden from defaults."""
    raw = {
        "cik": "0000000099",
        "entity_name": "Test Fund",
        "version": 1,
        "archetypes": {
            "equity": {
                "description": "Equity instruments",
                "detection_rules": {"keywords": ["Common stock"], "keyword_mode": "any"},
                "field_signatures": {
                    "fair_value": {
                        "type": "numeric_range",
                        "constraint": "required",
                        "min": -1e9,
                        "max": 1e12,
                    },
                },
            },
        },
    }
    defn = _parse_definition(raw)
    equity_arch = [a for a in defn.archetypes if a.name == "equity"][0]
    sig_map = {s.field_name: s for s in equity_arch.field_signatures}
    assert "basis_spread" in sig_map
    assert sig_map["basis_spread"].constraint == "forbidden"
    # Explicit FV should still be there
    assert "fair_value" in sig_map
    assert sig_map["fair_value"].constraint == "required"


def test_explicit_signature_overrides_default():
    """Wrapper with explicit basis_spread:optional on equity keeps explicit, not default."""
    raw = {
        "cik": "0000000099",
        "entity_name": "Test Fund",
        "version": 1,
        "archetypes": {
            "equity": {
                "description": "Equity instruments",
                "detection_rules": {"keywords": ["Common stock"], "keyword_mode": "any"},
                "field_signatures": {
                    "basis_spread": {
                        "type": "presence",
                        "constraint": "optional",
                    },
                },
            },
        },
    }
    defn = _parse_definition(raw)
    equity_arch = [a for a in defn.archetypes if a.name == "equity"][0]
    sig_map = {s.field_name: s for s in equity_arch.field_signatures}
    assert sig_map["basis_spread"].constraint == "optional"  # explicit wins
    # FV default should still be applied since not explicit
    assert "fair_value" in sig_map
    assert sig_map["fair_value"].constraint == "required"


def test_unknown_archetype_gets_no_defaults():
    """Archetype with unrecognized name gets no default signatures."""
    raw = {
        "cik": "0000000099",
        "entity_name": "Test Fund",
        "version": 1,
        "archetypes": {
            "structured_credit": {
                "description": "Structured credit instruments",
                "detection_rules": {"keywords": ["CLO tranche"], "keyword_mode": "any"},
                "field_signatures": {},
            },
        },
    }
    defn = _parse_definition(raw)
    arch = defn.archetypes[0]
    assert arch.name == "structured_credit"
    assert len(arch.field_signatures) == 0


def test_warrant_defaults_include_rate_and_spread_forbidden():
    """Warrant archetype gets interest_rate:forbidden and basis_spread:forbidden."""
    raw = {
        "cik": "0000000099",
        "entity_name": "Test Fund",
        "version": 1,
        "archetypes": {
            "warrant": {
                "description": "Warrants",
                "detection_rules": {"keywords": ["Warrant"], "keyword_mode": "any"},
                "field_signatures": {},
            },
        },
    }
    defn = _parse_definition(raw)
    warrant_arch = defn.archetypes[0]
    sig_map = {s.field_name: s for s in warrant_arch.field_signatures}
    assert sig_map["interest_rate"].constraint == "forbidden"
    assert sig_map["basis_spread"].constraint == "forbidden"
    assert sig_map["fair_value"].constraint == "required"


def test_default_equity_signature_catches_spread_on_equity():
    """Equity row with basis_spread present triggers a violation via default signature."""
    raw = {
        "cik": "0000000099",
        "entity_name": "Test Fund",
        "version": 1,
        "archetypes": {
            "equity": {
                "description": "Equity instruments",
                "detection_rules": {"keywords": ["Common stock"], "keyword_mode": "any"},
                "field_signatures": {
                    "fair_value": {
                        "type": "numeric_range",
                        "constraint": "required",
                        "min": -1e9,
                        "max": 1e12,
                    },
                },
            },
        },
    }
    defn = _parse_definition(raw)
    wrapper = WrapperDefinition(
        cik=defn.cik,
        entity_name=defn.entity_name,
        version=defn.version,
        archetypes=defn.archetypes,
    )
    df = pd.DataFrame([{
        "report_date": "2024-12-31",
        "instrument_description": "Acme Corp, Common stock",
        "interest_rate": None,
        "basis_spread": 0.05,  # Should be forbidden for equity
        "fair_value": 1000000,
        "shares_held": None,
    }])
    summary, violations = validate_content_signatures(wrapper, df)
    spread_violations = [v for v in violations if v.field_name == "basis_spread"]
    assert len(spread_violations) == 1
    assert "forbidden" in spread_violations[0].reason
