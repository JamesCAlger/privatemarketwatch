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


def test_validate_fund_source_f1_allows_empty_numeric_exports():
    result = validate_fund_source(_fund_df([{
        "total_investment_income": "",
        "net_investment_income": None,
        "distribution_per_share": pd.NA,
    }]))

    f1 = result[result["check_code"] == "F1"].iloc[0]
    assert f1["status"] == STATUS_PASS


def test_validate_fund_source_f1_rejects_invalid_and_nonfinite_values():
    result = validate_fund_source(_fund_df([{
        "total_assets": "nan",
        "net_assets": "inf",
        "borrowings": "-inf",
        "quarterly_return": "not-a-number",
    }]))

    f1 = result[result["check_code"] == "F1"].iloc[0]
    assert f1["status"] == STATUS_FAIL
    assert set(f1["value"].split(",")) == {
        "total_assets",
        "net_assets",
        "borrowings",
        "quarterly_return",
    }


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


def test_validate_fund_source_flags_cash_equivalents_exceeding_investments():
    """CASH_EQUIV_EXCEEDS_INVESTMENTS guards the companyfacts_fv_plus_cash gate anchor."""
    result = validate_fund_source(_fund_df([
        # Flagged: companyfacts row where cash is larger than investments at fair value.
        {"cik": "0000001001", "investments_at_fair_value": "100000",
         "cash_equivalents_at_fair_value": "667000"},
        # Clean: cash well below investments.
        {"cik": "0000001002", "investments_at_fair_value": "900000",
         "cash_equivalents_at_fair_value": "50000"},
        # Null cash: nothing to compare, so the check skips rather than flags.
        {"cik": "0000001003", "investments_at_fair_value": "900000",
         "cash_equivalents_at_fair_value": ""},
        # Boundary: equality does NOT flag (the guard is a strict >).
        {"cik": "0000001004", "investments_at_fair_value": "900000",
         "cash_equivalents_at_fair_value": "900000"},
        # Non-positive on either side is uncomparable, so it skips rather than flags.
        {"cik": "0000001005", "investments_at_fair_value": "900000",
         "cash_equivalents_at_fair_value": "0"},
        {"cik": "0000001006", "investments_at_fair_value": "0",
         "cash_equivalents_at_fair_value": "50000"},
    ]))

    checks = result[result["check_code"] == "CASH_EQUIV_EXCEEDS_INVESTMENTS"]
    by_cik = {row["cik"]: row for _, row in checks.iterrows()}
    assert len(by_cik) == 6
    assert by_cik["0000001001"]["status"] == STATUS_FAIL
    assert by_cik["0000001001"]["severity"] == "WARN"
    assert by_cik["0000001001"]["evidence_strength"] == "WEAK"
    assert by_cik["0000001002"]["status"] == STATUS_PASS
    assert by_cik["0000001003"]["status"] == STATUS_SKIP
    assert by_cik["0000001004"]["status"] == STATUS_PASS
    assert by_cik["0000001005"]["status"] == STATUS_SKIP
    assert by_cik["0000001006"]["status"] == STATUS_SKIP


def test_validate_fund_source_cash_equivalents_check_is_companyfacts_only():
    """Non-companyfacts rows and absent columns must not produce a cash flag."""
    result = validate_fund_source(_fund_df([{
        "source": "nport",
        "investments_at_fair_value": "100000",
        "cash_equivalents_at_fair_value": "667000",
    }]))
    assert _status(result, "CASH_EQUIV_EXCEEDS_INVESTMENTS") == STATUS_SKIP

    # Older fund_financials.csv without the Task 6 column: the check still runs, as SKIP.
    without_column = _fund_df([{}])
    assert "cash_equivalents_at_fair_value" not in without_column.columns
    result = validate_fund_source(without_column)
    assert _status(result, "CASH_EQUIV_EXCEEDS_INVESTMENTS") == STATUS_SKIP


def test_validate_cross_level_includes_fund_holdings_reconciliation():
    fund = _fund_df([{}])
    holdings = _holdings_df([{}, {}])

    result = validate_cross_level(fund, holdings)

    assert _status(result, "F20") == STATUS_PASS
    assert _status(result, "F21") == STATUS_PASS
    assert _status(result, "F22") == STATUS_PASS
    assert _status(result, "F23") == STATUS_PASS
    assert _status(result, "F28") == STATUS_PASS


def test_validate_cross_level_f20_uses_canonical_gav_status():
    fund = _fund_df([{}])
    holdings = _holdings_df([{"fair_value": "100000"}])

    result = validate_cross_level(fund, holdings)

    f20 = result[result["check_code"] == "F20"].iloc[0]
    assert f20["status"] == STATUS_FAIL
    assert "canonical GAV reconciliation status=FAIL" in f20["note"]


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


def test_validate_fund_financials_persists_only_fund_period_cross_level(tmp_path, monkeypatch):
    fund = _fund_df([{}])
    holdings = _holdings_df([
        {},
        {
            "cik": "0000002000",
            "report_date": "2024-03-31",
        },
    ])
    validation_path = tmp_path / "fund_financials_validation_current.csv"
    quality_path = tmp_path / "fund_financials_quality_metrics.csv"
    cross_path = tmp_path / "fund_financials_cross_level.csv"
    monkeypatch.setattr(
        "pipeline.validate_fund_financials.FUND_FINANCIALS_VALIDATION_CURRENT_FILE",
        validation_path,
    )
    monkeypatch.setattr(
        "pipeline.validate_fund_financials.FUND_FINANCIALS_QUALITY_METRICS_FILE",
        quality_path,
    )
    monkeypatch.setattr(
        "pipeline.validate_fund_financials.FUND_FINANCIALS_CROSS_LEVEL_FILE",
        cross_path,
    )

    reports = validate_fund_financials(
        fund_df=fund,
        holdings_df=holdings,
        write=True,
    )

    returned_mismatches = reports["fund_cross_level"][
        reports["fund_cross_level"]["check_code"] == "F28"
    ]
    persisted = pd.read_csv(cross_path, dtype=str)
    assert len(returned_mismatches) == 2
    assert set(persisted["cik"]) == {"0000001000"}
    assert "0000002000" not in set(persisted["cik"])


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
