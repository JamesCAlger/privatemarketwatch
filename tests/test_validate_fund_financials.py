"""Tests for fund-level financial validation."""

import pandas as pd

from pipeline.validate_fund_financials import (
    STATUS_FAIL,
    STATUS_PASS,
    STATUS_SKIP,
    build_quality_metrics,
    validate_cross_level,
    validate_fund_financials,
    validate_fund_source,
)


def _fund_df(rows):
    base = {
        "cik": "0000001000",
        "entity_name": "Test Fund",
        "vehicle_type": "bdc",
        "source": "companyfacts",
        "report_quarter": "2024q1",
        "report_date": "2024-03-31",
        "total_assets": "1000000",
        "net_assets": "600000",
        "total_liabilities": "400000",
        "investments_at_fair_value": "900000",
        "nav_per_share": "10",
        "shares_outstanding": "60000",
        "borrowings": "250000",
        "leverage_ratio": "0.25",
        "management_fee_pct": "1.0",
        "expense_ratio_pct": "2.0",
        "quarterly_return": "3.0301",
        "monthly_return_1": "1.0",
        "monthly_return_2": "1.0",
        "monthly_return_3": "1.0",
        "distribution_rate": "8.0",
        "income_yield_pct": "7.0",
        "asset_coverage_ratio": "2.0",
    }
    out = []
    for row in rows:
        merged = base.copy()
        merged.update(row)
        out.append(merged)
    return pd.DataFrame(out)


def _holdings_df(rows):
    base = {
        "cik": "0000001000",
        "report_date": "2024-03-31",
        "fair_value": "450000",
        "pct_of_net_assets": "75",
        "interest_rate": "10",
    }
    out = []
    for row in rows:
        merged = base.copy()
        merged.update(row)
        out.append(merged)
    return pd.DataFrame(out)


def _status(result, code):
    subset = result[result["check_code"] == code]
    assert not subset.empty
    return subset.iloc[0]["status"]


def test_validate_fund_source_passes_core_identities():
    result = validate_fund_source(_fund_df([{}]))

    assert _status(result, "F1") == STATUS_PASS
    assert _status(result, "F10") == STATUS_PASS
    assert _status(result, "F11") == STATUS_PASS
    assert _status(result, "F12") == STATUS_PASS
    assert _status(result, "F17") == STATUS_PASS


def test_validate_fund_source_flags_balance_sheet_and_return_mismatch():
    result = validate_fund_source(_fund_df([{
        "net_assets": "500000",
        "quarterly_return": "9.0",
    }]))

    f10 = result[result["check_code"] == "F10"].iloc[0]
    f17 = result[result["check_code"] == "F17"].iloc[0]
    assert f10["status"] == STATUS_FAIL
    assert f10["severity"] == "FAIL"
    assert f17["status"] == STATUS_FAIL
    assert f17["evidence_strength"] == "STRONG"


def test_validate_fund_source_flags_report_quarter_date_mismatch():
    result = validate_fund_source(_fund_df([{
        "source": "nport",
        "report_quarter": "2026q1",
        "report_date": "2025-12-31",
    }]))

    f3 = result[result["check_code"] == "F3"].iloc[0]
    assert f3["status"] == STATUS_FAIL
    assert f3["evidence_strength"] == "STRONG"


def test_validate_cross_level_includes_fund_holdings_reconciliation():
    fund = _fund_df([{}])
    holdings = _holdings_df([{}, {}])

    result = validate_cross_level(fund, holdings)

    assert _status(result, "F20") == STATUS_PASS
    assert _status(result, "F21") == STATUS_PASS
    assert _status(result, "F22") == STATUS_PASS
    assert _status(result, "F23") == STATUS_PASS
    assert _status(result, "F28") == STATUS_PASS


def test_validate_cross_level_flags_coverage_mismatch():
    fund = _fund_df([{}])
    holdings = _holdings_df([{
        "cik": "0000002000",
        "report_date": "2024-03-31",
    }])

    result = validate_cross_level(fund, holdings)
    mismatches = result[(result["check_code"] == "F28")
                        & (result["status"] == STATUS_FAIL)]

    assert len(mismatches) == 2


def test_build_quality_metrics_derives_under_review():
    result = validate_fund_source(_fund_df([{"total_assets": "not-a-number"}]))
    quality = build_quality_metrics(result)

    assert quality.iloc[0]["validation_tier"] == "UNDER_REVIEW"
    assert quality.iloc[0]["fail_count"] >= 1


def test_validate_fund_financials_orchestrator_without_holdings_marks_cross_skips():
    reports = validate_fund_financials(
        fund_df=_fund_df([{}]),
        holdings_df=pd.DataFrame(),
        write=False,
    )

    assert "fund_validation" in reports
    assert "fund_quality" in reports
    assert reports["fund_quality"].iloc[0]["validation_tier"] == "VERIFIED"
    assert reports["fund_cross_level"].empty
