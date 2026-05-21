"""Tests for report-only fund strategy validation."""

import pandas as pd

from pipeline.fund_strategy_validation import (
    apply_fund_strategy_correction_candidates,
    build_fund_strategy_correction_candidates,
    build_fund_strategy_holdings_mix,
    build_fund_strategy_reference,
    build_fund_strategy_validation,
    run_fund_strategy_validation,
)


def _holdings(rows):
    defaults = {
        "source": "bdc",
        "cik": "100",
        "entity_name": "Test Fund",
        "report_date": "2024-03-31",
        "issuer_name": "Issuer",
        "instrument_description": "Investment",
        "fair_value": "100",
        "issuer_category": "CORPORATE",
        "asset_category": "LOAN",
        "asset_class": "PRIVATE_CREDIT",
        "nport_asset_cat": "",
        "nport_issuer_type": "",
        "accession_number": "000100-24-000001",
        "bdc_investment_identifier": "Issuer - Investment",
        "nport_holding_id": "",
        "index_classification": "DIRECT_LENDING",
    }
    return pd.DataFrame([{**defaults, **row} for row in rows])


def _universe(rows):
    defaults = {
        "cik": "100",
        "entity_name": "Test Fund",
        "fund_name": "",
        "vehicle_type": "",
    }
    return pd.DataFrame([{**defaults, **row} for row in rows])


def _approved_override(**overrides):
    row = {
        "cik": "100",
        "strategy": "REAL_ESTATE",
        "sub_strategy": "RE_CREDIT",
        "mechanism": "manual_source_review",
        "evidence_source": "filing",
        "evidence_accession_number": "000100-24-000001",
        "evidence_text": "Fund states real estate strategy.",
        "confidence": "HIGH",
        "effective_start_date": "2024-01-01",
        "effective_end_date": "",
        "review_status": "APPROVED",
        "residual_risk": "none",
    }
    row.update(overrides)
    return pd.DataFrame([row])


def test_bdc_defaults_to_private_credit():
    holdings = _holdings([{"cik": "100", "entity_name": "BDC 100"}])
    universe = _universe([{"cik": "100", "entity_name": "BDC 100", "vehicle_type": "bdc"}])

    ref = build_fund_strategy_reference(holdings, universe, pd.DataFrame())

    assert ref.iloc[0]["cik"] == "0000000100"
    assert ref.iloc[0]["strategy"] == "PRIVATE_CREDIT"
    assert ref.iloc[0]["strategy_source"] == "VEHICLE_TYPE_BDC"


def test_approved_override_takes_precedence_over_vehicle_and_name_inference():
    holdings = _holdings([{"cik": "100", "entity_name": "Credit BDC"}])
    universe = _universe([{
        "cik": "100",
        "entity_name": "Credit BDC",
        "fund_name": "Credit BDC",
        "vehicle_type": "bdc",
    }])
    overrides = _approved_override(strategy="REAL_ESTATE")

    ref = build_fund_strategy_reference(holdings, universe, overrides)

    assert ref.iloc[0]["strategy"] == "REAL_ESTATE"
    assert ref.iloc[0]["strategy_source"] == "APPROVED_OVERRIDE"
    assert ref.iloc[0]["sub_strategy"] == "RE_CREDIT"


def test_unknown_strategy_does_not_create_mismatch_warning():
    holdings = _holdings([{"cik": "200", "entity_name": "Mystery Fund"}])
    universe = _universe([{
        "cik": "200",
        "entity_name": "Mystery Fund",
        "fund_name": "Mystery Fund",
        "vehicle_type": "interval_fund",
    }])

    reports = run_fund_strategy_validation(holdings, universe, output=False)
    validation = reports["fund_strategy_validation"]

    assert validation.iloc[0]["strategy"] == "UNKNOWN"
    assert validation.iloc[0]["validation_status"] == "NO_REFERENCE"
    assert validation.iloc[0]["rule_ids"] == ""


def test_real_estate_strategy_with_low_re_holdings_triggers_fs01():
    holdings = _holdings([
        {"fair_value": "80", "index_classification": "DIRECT_LENDING"},
        {"fair_value": "20", "index_classification": "DIRECT_REAL_ESTATE"},
    ])
    reference = build_fund_strategy_reference(
        holdings,
        _universe([{"fund_name": "Real Estate Income Fund"}]),
        pd.DataFrame(),
    )
    mix = build_fund_strategy_holdings_mix(holdings)

    validation, queue = build_fund_strategy_validation(reference, mix)

    assert validation.iloc[0]["validation_status"] == "UNDER_REVIEW"
    assert validation.iloc[0]["rule_ids"] == "FS01"
    assert len(queue) == 1


def test_real_estate_strategy_with_high_re_holdings_passes():
    holdings = _holdings([
        {"fair_value": "60", "index_classification": "DIRECT_REAL_ESTATE"},
        {"fair_value": "40", "index_classification": "DIRECT_LENDING"},
    ])
    reference = build_fund_strategy_reference(
        holdings,
        _universe([{"fund_name": "Real Estate Income Fund"}]),
        pd.DataFrame(),
    )
    mix = build_fund_strategy_holdings_mix(holdings)

    validation, queue = build_fund_strategy_validation(reference, mix)

    assert validation.iloc[0]["validation_status"] == "PASS"
    assert validation.iloc[0]["rule_ids"] == ""
    assert queue.empty


def test_private_credit_strategy_with_low_credit_share_triggers_fs02():
    holdings = _holdings([
        {"fair_value": "30", "index_classification": "DIRECT_LENDING"},
        {"fair_value": "70", "index_classification": "COMMON_EQUITY"},
    ])
    reference = build_fund_strategy_reference(
        holdings,
        _universe([{"vehicle_type": "bdc"}]),
        pd.DataFrame(),
    )
    mix = build_fund_strategy_holdings_mix(holdings)

    validation, _ = build_fund_strategy_validation(reference, mix)

    assert validation.iloc[0]["validation_status"] == "UNDER_REVIEW"
    assert "FS02" in validation.iloc[0]["rule_ids"]


def test_review_queue_includes_only_under_review_rows_sorted_by_affected_fv():
    holdings = _holdings([
        {
            "cik": "100",
            "entity_name": "Small BDC",
            "report_date": "2024-03-31",
            "fair_value": "100",
            "index_classification": "COMMON_EQUITY",
        },
        {
            "cik": "200",
            "entity_name": "Large BDC",
            "report_date": "2024-03-31",
            "fair_value": "1000",
            "index_classification": "COMMON_EQUITY",
        },
        {
            "cik": "300",
            "entity_name": "Passing BDC",
            "report_date": "2024-03-31",
            "fair_value": "1000",
            "index_classification": "DIRECT_LENDING",
        },
    ])
    universe = _universe([
        {"cik": "100", "entity_name": "Small BDC", "vehicle_type": "bdc"},
        {"cik": "200", "entity_name": "Large BDC", "vehicle_type": "bdc"},
        {"cik": "300", "entity_name": "Passing BDC", "vehicle_type": "bdc"},
    ])

    reports = run_fund_strategy_validation(holdings, universe, output=False)
    queue = reports["fund_strategy_review_queue"]

    assert queue["validation_status"].tolist() == ["UNDER_REVIEW", "UNDER_REVIEW"]
    assert queue["cik"].tolist() == ["0000000200", "0000000100"]
    assert queue["affected_fair_value"].tolist() == [500.0, 50.0]


def test_real_estate_strategy_generates_apply_candidate_for_direct_re_row():
    holdings = _holdings([{
        "source": "nport",
        "issuer_name": "Northpoint Apartments LLC",
        "instrument_description": "Real estate equity",
        "asset_category": "EQUITY_COMMON",
        "issuer_category": "CORPORATE",
        "nport_asset_cat": "RE",
        "index_classification": "COMMON_EQUITY",
        "asset_class": "PRIVATE_EQUITY",
        "nport_holding_id": "nport-1",
    }])
    reference = build_fund_strategy_reference(
        holdings,
        _universe([{"fund_name": "Real Estate Income Fund"}]),
        pd.DataFrame(),
    )
    mix = build_fund_strategy_holdings_mix(holdings)
    _, queue = build_fund_strategy_validation(reference, mix)

    candidates = build_fund_strategy_correction_candidates(holdings, reference, queue)

    assert candidates.iloc[0]["correction_status"] == "APPLY"
    assert candidates.iloc[0]["proposed_index_classification"] == "DIRECT_REAL_ESTATE"
    assert candidates.iloc[0]["proposed_asset_class"] == "REAL_ESTATE"


def test_real_estate_strategy_debt_row_updates_asset_class_not_direct_re_bucket():
    holdings = _holdings([{
        "source": "nport",
        "issuer_name": "Northpoint Mortgage Trust",
        "instrument_description": "Real estate debt",
        "asset_category": "DEBT",
        "issuer_category": "CORPORATE",
        "nport_asset_cat": "RE",
        "index_classification": "DIRECT_LENDING",
        "asset_class": "PRIVATE_CREDIT",
        "nport_holding_id": "nport-1",
    }])
    reference = build_fund_strategy_reference(
        holdings,
        _universe([{"fund_name": "Real Estate Income Fund"}]),
        pd.DataFrame(),
    )
    mix = build_fund_strategy_holdings_mix(holdings)
    _, queue = build_fund_strategy_validation(reference, mix)

    candidates = build_fund_strategy_correction_candidates(holdings, reference, queue)

    assert candidates.iloc[0]["correction_status"] == "APPLY"
    assert candidates.iloc[0]["proposed_index_classification"] == "DIRECT_LENDING"
    assert candidates.iloc[0]["proposed_asset_class"] == "REAL_ESTATE"


def test_fund_holding_strategy_can_apply_fund_bucket_only_with_fund_evidence():
    holdings = _holdings([{
        "issuer_name": "Northpoint Property Fund LP",
        "asset_category": "FUND",
        "issuer_category": "FUND",
        "index_classification": "UNCLASSIFIED",
        "asset_class": "OTHER",
    }])
    reference = build_fund_strategy_reference(
        holdings,
        _universe([{"fund_name": "Real Estate Income Fund"}]),
        pd.DataFrame(),
    )
    mix = build_fund_strategy_holdings_mix(holdings)
    _, queue = build_fund_strategy_validation(reference, mix)

    candidates = build_fund_strategy_correction_candidates(holdings, reference, queue)

    assert candidates.iloc[0]["correction_status"] == "APPLY"
    assert candidates.iloc[0]["proposed_index_classification"] == "REAL_ESTATE_FUND"
    assert candidates.iloc[0]["proposed_asset_class"] == "REAL_ESTATE"


def test_cash_structured_and_generic_operating_company_rows_are_not_applied():
    holdings = _holdings([
        {
            "issuer_name": "U.S. Treasury Bill",
            "asset_category": "DEBT",
            "issuer_category": "GOVERNMENT",
            "index_classification": "CASH",
            "asset_class": "CASH",
            "fair_value": "10",
        },
        {
            "issuer_name": "Atlas CLO 2024-1",
            "instrument_description": "Subordinated note",
            "asset_category": "DEBT",
            "issuer_category": "CORPORATE",
            "index_classification": "STRUCTURED_CREDIT",
            "asset_class": "STRUCTURED_CREDIT",
            "fair_value": "10",
        },
        {
            "issuer_name": "Generic Software Holdings LLC",
            "instrument_description": "Common equity",
            "asset_category": "EQUITY_COMMON",
            "issuer_category": "CORPORATE",
            "index_classification": "COMMON_EQUITY",
            "asset_class": "PRIVATE_EQUITY",
            "fair_value": "80",
        },
    ])
    reference = build_fund_strategy_reference(
        holdings,
        _universe([{"fund_name": "Real Estate Income Fund"}]),
        pd.DataFrame(),
    )
    mix = build_fund_strategy_holdings_mix(holdings)
    _, queue = build_fund_strategy_validation(reference, mix)

    candidates = build_fund_strategy_correction_candidates(holdings, reference, queue)

    by_issuer = candidates.set_index("issuer_name")
    assert by_issuer.loc["U.S. Treasury Bill", "correction_status"] == "REJECT"
    assert by_issuer.loc["Atlas CLO 2024-1", "correction_status"] == "REJECT"
    assert by_issuer.loc["Generic Software Holdings LLC", "correction_status"] == "REVIEW"


def test_apply_helper_mutates_only_apply_candidates_and_supports_nport_keys():
    holdings = _holdings([
        {
            "source": "nport",
            "nport_holding_id": "nport-1",
            "issuer_name": "Northpoint Apartments LLC",
            "index_classification": "COMMON_EQUITY",
            "asset_class": "PRIVATE_EQUITY",
        },
        {
            "source": "nport",
            "nport_holding_id": "nport-2",
            "issuer_name": "Generic Software Holdings LLC",
            "index_classification": "COMMON_EQUITY",
            "asset_class": "PRIVATE_EQUITY",
        },
    ])
    candidates = pd.DataFrame([
        {
            "correction_status": "APPLY",
            "cik": "100",
            "report_date": "2024-03-31",
            "source": "nport",
            "accession_number": "000100-24-000001",
            "bdc_investment_identifier": "Issuer - Investment",
            "nport_holding_id": "nport-1",
            "proposed_index_classification": "DIRECT_REAL_ESTATE",
            "proposed_asset_class": "REAL_ESTATE",
        },
        {
            "correction_status": "REVIEW",
            "cik": "100",
            "report_date": "2024-03-31",
            "source": "nport",
            "accession_number": "000100-24-000001",
            "bdc_investment_identifier": "Issuer - Investment",
            "nport_holding_id": "nport-2",
            "proposed_index_classification": "DIRECT_REAL_ESTATE",
            "proposed_asset_class": "REAL_ESTATE",
        },
    ])

    result = apply_fund_strategy_correction_candidates(holdings, candidates)

    first = result[result["nport_holding_id"] == "nport-1"].iloc[0]
    second = result[result["nport_holding_id"] == "nport-2"].iloc[0]
    assert first["index_classification"] == "DIRECT_REAL_ESTATE"
    assert first["asset_class"] == "REAL_ESTATE"
    assert second["index_classification"] == "COMMON_EQUITY"
    assert second["asset_class"] == "PRIVATE_EQUITY"


def test_apply_excludes_re_fund_to_pc_fund_transition():
    """RE_FUND -> PC_FUND transitions are excluded (investees are genuine RE)."""
    holdings = _holdings([
        {
            "source": "nport",
            "nport_holding_id": "nport-1",
            "issuer_name": "EPIC Dallas",
            "index_classification": "REAL_ESTATE_FUND",
            "asset_class": "REAL_ESTATE",
        },
        {
            "source": "nport",
            "nport_holding_id": "nport-2",
            "issuer_name": "Apollo Co-investment",
            "index_classification": "PRIVATE_EQUITY_FUND",
            "asset_class": "PRIVATE_EQUITY",
        },
    ])
    candidates = pd.DataFrame([
        {
            "correction_status": "APPLY",
            "current_index_classification": "REAL_ESTATE_FUND",
            "cik": "100",
            "report_date": "2024-03-31",
            "source": "nport",
            "accession_number": "000100-24-000001",
            "bdc_investment_identifier": "Issuer - Investment",
            "nport_holding_id": "nport-1",
            "proposed_index_classification": "PRIVATE_CREDIT_FUND",
            "proposed_asset_class": "PRIVATE_CREDIT",
        },
        {
            "correction_status": "APPLY",
            "current_index_classification": "PRIVATE_EQUITY_FUND",
            "cik": "100",
            "report_date": "2024-03-31",
            "source": "nport",
            "accession_number": "000100-24-000001",
            "bdc_investment_identifier": "Issuer - Investment",
            "nport_holding_id": "nport-2",
            "proposed_index_classification": "PRIVATE_CREDIT_FUND",
            "proposed_asset_class": "PRIVATE_CREDIT",
        },
    ])

    result = apply_fund_strategy_correction_candidates(holdings, candidates)

    re_row = result[result["nport_holding_id"] == "nport-1"].iloc[0]
    pe_row = result[result["nport_holding_id"] == "nport-2"].iloc[0]
    # RE_FUND -> PC_FUND should be blocked
    assert re_row["index_classification"] == "REAL_ESTATE_FUND"
    assert re_row["asset_class"] == "REAL_ESTATE"
    # PE_FUND -> PC_FUND should be applied
    assert pe_row["index_classification"] == "PRIVATE_CREDIT_FUND"
    assert pe_row["asset_class"] == "PRIVATE_CREDIT"


def test_apply_handles_pc_fund_to_re_fund_transition():
    """PC_FUND -> RE_FUND transitions are applied (RE debt funds correctly reclassified)."""
    holdings = _holdings([
        {
            "source": "nport",
            "nport_holding_id": "nport-1",
            "issuer_name": "Heitman Core RE Debt Inc",
            "index_classification": "PRIVATE_CREDIT_FUND",
            "asset_class": "PRIVATE_CREDIT",
        },
    ])
    candidates = pd.DataFrame([
        {
            "correction_status": "APPLY",
            "current_index_classification": "PRIVATE_CREDIT_FUND",
            "cik": "100",
            "report_date": "2024-03-31",
            "source": "nport",
            "accession_number": "000100-24-000001",
            "bdc_investment_identifier": "Issuer - Investment",
            "nport_holding_id": "nport-1",
            "proposed_index_classification": "REAL_ESTATE_FUND",
            "proposed_asset_class": "REAL_ESTATE",
        },
    ])

    result = apply_fund_strategy_correction_candidates(holdings, candidates)

    row = result[result["nport_holding_id"] == "nport-1"].iloc[0]
    assert row["index_classification"] == "REAL_ESTATE_FUND"
    assert row["asset_class"] == "REAL_ESTATE"


def test_apply_returns_unchanged_when_all_excluded():
    """If all APPLY candidates are excluded transitions, return holdings unchanged."""
    holdings = _holdings([
        {
            "source": "nport",
            "nport_holding_id": "nport-1",
            "issuer_name": "Sora Multifamily Residential",
            "index_classification": "REAL_ESTATE_FUND",
            "asset_class": "REAL_ESTATE",
        },
    ])
    candidates = pd.DataFrame([
        {
            "correction_status": "APPLY",
            "current_index_classification": "REAL_ESTATE_FUND",
            "cik": "100",
            "report_date": "2024-03-31",
            "source": "nport",
            "accession_number": "000100-24-000001",
            "bdc_investment_identifier": "Issuer - Investment",
            "nport_holding_id": "nport-1",
            "proposed_index_classification": "PRIVATE_CREDIT_FUND",
            "proposed_asset_class": "PRIVATE_CREDIT",
        },
    ])

    result = apply_fund_strategy_correction_candidates(holdings, candidates)
    assert result.iloc[0]["index_classification"] == "REAL_ESTATE_FUND"
    assert result.iloc[0]["asset_class"] == "REAL_ESTATE"


def test_apply_preserves_unmatched_holdings():
    """Holdings rows not in the candidates table are left unchanged."""
    holdings = _holdings([
        {
            "source": "bdc",
            "bdc_investment_identifier": "Acme Corp - First Lien",
            "nport_holding_id": "",
            "issuer_name": "Acme Corp",
            "index_classification": "DIRECT_LENDING",
            "asset_class": "PRIVATE_CREDIT",
        },
        {
            "source": "bdc",
            "bdc_investment_identifier": "Beta Corp - Equity",
            "nport_holding_id": "",
            "issuer_name": "Beta Corp",
            "index_classification": "COMMON_EQUITY",
            "asset_class": "PRIVATE_EQUITY",
        },
    ])
    candidates = pd.DataFrame([
        {
            "correction_status": "APPLY",
            "current_index_classification": "COMMON_EQUITY",
            "cik": "100",
            "report_date": "2024-03-31",
            "source": "bdc",
            "accession_number": "000100-24-000001",
            "bdc_investment_identifier": "Beta Corp - Equity",
            "nport_holding_id": "",
            "proposed_index_classification": "PRIVATE_EQUITY_FUND",
            "proposed_asset_class": "PRIVATE_EQUITY",
        },
    ])

    result = apply_fund_strategy_correction_candidates(holdings, candidates)

    acme = result[result["issuer_name"] == "Acme Corp"].iloc[0]
    beta = result[result["issuer_name"] == "Beta Corp"].iloc[0]
    # Acme unchanged
    assert acme["index_classification"] == "DIRECT_LENDING"
    assert acme["asset_class"] == "PRIVATE_CREDIT"
    # Beta updated
    assert beta["index_classification"] == "PRIVATE_EQUITY_FUND"
    assert beta["asset_class"] == "PRIVATE_EQUITY"


def test_apply_excludes_bad_signal_ciks():
    """CIKs in _EXCLUDED_CIKS are blocked (false FUND_NAME_SIGNAL)."""
    holdings = _holdings([
        {
            "cik": "1793855",  # abrdn Global Infrastructure
            "source": "nport",
            "bdc_investment_identifier": "",
            "nport_holding_id": "nport-infra",
            "issuer_name": "Cresta Highline Co-Invest Fund I LP",
            "index_classification": "PRIVATE_EQUITY_FUND",
            "asset_class": "PRIVATE_EQUITY",
        },
        {
            "cik": "200",  # normal credit fund
            "source": "nport",
            "bdc_investment_identifier": "",
            "nport_holding_id": "nport-credit",
            "issuer_name": "Some Credit Fund LP",
            "index_classification": "PRIVATE_EQUITY_FUND",
            "asset_class": "PRIVATE_EQUITY",
        },
    ])
    candidates = pd.DataFrame([
        {
            "correction_status": "APPLY",
            "current_index_classification": "PRIVATE_EQUITY_FUND",
            "cik": "1793855",
            "report_date": "2024-03-31",
            "source": "nport",
            "accession_number": "000100-24-000001",
            "bdc_investment_identifier": "",
            "nport_holding_id": "nport-infra",
            "proposed_index_classification": "PRIVATE_CREDIT_FUND",
            "proposed_asset_class": "PRIVATE_CREDIT",
        },
        {
            "correction_status": "APPLY",
            "current_index_classification": "PRIVATE_EQUITY_FUND",
            "cik": "200",
            "report_date": "2024-03-31",
            "source": "nport",
            "accession_number": "000100-24-000001",
            "bdc_investment_identifier": "",
            "nport_holding_id": "nport-credit",
            "proposed_index_classification": "PRIVATE_CREDIT_FUND",
            "proposed_asset_class": "PRIVATE_CREDIT",
        },
    ])

    result = apply_fund_strategy_correction_candidates(holdings, candidates)

    infra = result[result["nport_holding_id"] == "nport-infra"].iloc[0]
    credit = result[result["nport_holding_id"] == "nport-credit"].iloc[0]
    # abrdn infrastructure CIK blocked
    assert infra["index_classification"] == "PRIVATE_EQUITY_FUND"
    assert infra["asset_class"] == "PRIVATE_EQUITY"
    # Normal CIK applied
    assert credit["index_classification"] == "PRIVATE_CREDIT_FUND"
    assert credit["asset_class"] == "PRIVATE_CREDIT"
