"""Tests for pipeline.column_validation."""

import pandas as pd

from pipeline.column_validation import (
    SEVERITY_FAIL,
    SEVERITY_INFO,
    SEVERITY_WARN,
    adapt_validation_reports,
    build_quality_summary,
    run_column_quality_validation,
    validate_column_contracts,
)
from pipeline.unified_holdings import UNIFIED_COLUMNS


def _make_unified_df(rows):
    data = []
    for row in rows:
        full = {c: "" for c in UNIFIED_COLUMNS}
        full.update({
            "source": "bdc",
            "cik": "0000000100",
            "entity_name": "Test BDC",
            "accession_number": "0000000100-24-000001",
            "filing_date": "2024-05-01",
            "report_date": "2024-03-31",
            "issuer_name": "Acme Corp",
            "fair_value": "1000000",
            "cost": "1000000",
            "index_classification": "DIRECT_LENDING",
            "asset_category": "LOAN",
            "issuer_category": "CORPORATE",
            "exposure_type": "DIRECT",
            "asset_class": "PRIVATE_CREDIT",
            "coupon_type": "Floating",
            "basis_spread": "5.5",
            "interest_rate": "9.8",
            "bdc_investment_identifier": "Acme Corp - First Lien Loan",
        })
        full.update(row)
        data.append(full)
    return pd.DataFrame(data)


def _issues_by_rule(issues, rule_id):
    return issues[issues["rule_id"] == rule_id]


class TestColumnContracts:
    def test_valid_row_has_no_failures(self):
        df = _make_unified_df([{}])
        issues, metrics = validate_column_contracts(df)
        assert len(issues[issues["severity"] == SEVERITY_FAIL]) == 0
        assert not metrics.empty

    def test_invalid_enum_produces_fail(self):
        df = _make_unified_df([{"source": "bad"}])
        issues, _ = validate_column_contracts(df)
        result = _issues_by_rule(issues, "C001")
        assert len(result) == 1
        assert result.iloc[0]["severity"] == SEVERITY_FAIL

    def test_null_fair_value_indexable_row_fails(self):
        df = _make_unified_df([{"fair_value": ""}])
        issues, _ = validate_column_contracts(df)
        result = _issues_by_rule(issues, "C101")
        assert len(result) == 1
        assert result.iloc[0]["severity"] == SEVERITY_FAIL

    def test_null_fair_value_non_indexable_row_not_fail(self):
        df = _make_unified_df([{
            "fair_value": "",
            "index_classification": "UNCLASSIFIED",
        }])
        issues, _ = validate_column_contracts(df)
        assert len(_issues_by_rule(issues, "C101")) == 0

    def test_principal_amount_scale_error_fails(self):
        df = _make_unified_df([{
            "fair_value": "1000000",
            "principal_amount": "100000000",
        }])
        issues, _ = validate_column_contracts(df)
        result = _issues_by_rule(issues, "X06")
        assert len(result) == 1
        assert result.iloc[0]["severity"] == SEVERITY_FAIL

    def test_rate_percentage_scale_passes_and_high_rate_warns(self):
        ok_df = _make_unified_df([{"interest_rate": "9.8"}])
        ok_issues, _ = validate_column_contracts(ok_df)
        assert len(_issues_by_rule(ok_issues, "C113")) == 0

        warn_df = _make_unified_df([{"interest_rate": "30"}])
        warn_issues, _ = validate_column_contracts(warn_df)
        result = _issues_by_rule(warn_issues, "C113")
        assert len(result) == 1
        assert result.iloc[0]["severity"] == SEVERITY_WARN

    def test_maturity_sentinel_info_and_bad_year_fail(self):
        sentinel = _make_unified_df([{"maturity_date": "9999-12-31"}])
        sentinel_issues, _ = validate_column_contracts(sentinel)
        info = _issues_by_rule(sentinel_issues, "C403")
        assert len(info) == 1
        assert info.iloc[0]["severity"] == SEVERITY_INFO

        bad = _make_unified_df([{"maturity_date": "0225-06-28"}])
        bad_issues, _ = validate_column_contracts(bad)
        fail = _issues_by_rule(bad_issues, "C402")
        assert len(fail) == 1
        assert fail.iloc[0]["severity"] == SEVERITY_FAIL

        equity_placeholder = _make_unified_df([{
            "maturity_date": "1899-12-31",
            "asset_category": "EQUITY_COMMON",
            "asset_class": "PRIVATE_EQUITY",
        }])
        equity_issues, _ = validate_column_contracts(equity_placeholder)
        assert len(_issues_by_rule(equity_issues, "C402")) == 0

    def test_negative_shares_warns(self):
        df = _make_unified_df([{"shares_held": "-100"}])
        issues, _ = validate_column_contracts(df)
        result = _issues_by_rule(issues, "C119")
        assert len(result) == 1
        assert result.iloc[0]["severity"] == SEVERITY_WARN

    def test_fixed_spread_fail_and_floating_missing_spread_warn(self):
        fixed = _make_unified_df([{
            "coupon_type": "Fixed",
            "basis_spread": "3.0",
        }])
        fixed_issues, _ = validate_column_contracts(fixed)
        assert _issues_by_rule(fixed_issues, "X04").iloc[0]["severity"] == SEVERITY_FAIL

        floating = _make_unified_df([{
            "coupon_type": "Floating",
            "basis_spread": "",
        }])
        floating_issues, _ = validate_column_contracts(floating)
        assert _issues_by_rule(floating_issues, "X05").iloc[0]["severity"] == SEVERITY_WARN

    def test_private_equity_with_rate_warns(self):
        df = _make_unified_df([{
            "asset_class": "PRIVATE_EQUITY",
            "index_classification": "COMMON_EQUITY",
            "interest_rate": "8.5",
        }])
        issues, _ = validate_column_contracts(df)
        result = _issues_by_rule(issues, "X01")
        assert len(result) == 1
        assert result.iloc[0]["severity"] == SEVERITY_WARN


class TestReportAdapters:
    def test_gav_adapter_severity(self):
        gav = pd.DataFrame([
            {
                "cik": "0000000100",
                "report_date": "2024-03-31",
                "gav_ratio": "0.2",
                "gav_ratio_adjusted": "",
                "comparison_source": "investments_at_fair_value",
                "holdings_source": "bdc",
                "holdings_scope": "bdc_schedule",
                "denominator_scope": "investment_fair_value",
                "gav_rule_id": "GAV_BDC01",
            },
            {
                "cik": "0000000101",
                "report_date": "2024-03-31",
                "gav_ratio": "0.75",
                "gav_ratio_adjusted": "",
                "comparison_source": "investments_at_fair_value",
                "holdings_source": "bdc",
                "holdings_scope": "bdc_schedule",
                "denominator_scope": "investment_fair_value",
                "gav_rule_id": "GAV_BDC01",
            },
            {
                "cik": "0000000102",
                "report_date": "2024-03-31",
                "gav_ratio": "1.0",
                "gav_ratio_adjusted": "",
                "comparison_source": "investments_at_fair_value",
                "holdings_source": "bdc",
                "holdings_scope": "bdc_schedule",
                "denominator_scope": "investment_fair_value",
                "gav_rule_id": "GAV_BDC01",
            },
            {
                "cik": "0000000103",
                "report_date": "2024-03-31",
                "gav_ratio": "0.2",
                "gav_ratio_adjusted": "",
                "comparison_source": "total_assets_nport",
                "holdings_source": "nport",
                "holdings_scope": "nport_private_markets_filter",
                "denominator_scope": "full_fund_assets",
                "gav_rule_id": "GAV_NPORT01",
            },
        ])
        issues = adapt_validation_reports({"gav_reconciliation": gav})
        assert _issues_by_rule(issues, "GAV_BDC01").iloc[0]["severity"] == SEVERITY_FAIL
        assert _issues_by_rule(issues, "GAV_BDC02").iloc[0]["severity"] == SEVERITY_WARN
        assert _issues_by_rule(issues, "GAV_NPORT01").iloc[0]["severity"] == SEVERITY_WARN
        assert len(issues) == 3

    def test_aggregate_adapter_suspects_are_warns(self):
        agg = pd.DataFrame([
            {
                "cik": "0000000100",
                "report_date": "2024-03-31",
                "issuer_name": "Total Senior Secured",
                "reason": "keyword: total senior",
            },
            {
                "cik": "0000000101",
                "report_date": "2024-03-31",
                "issuer_name": "Maybe Header",
                "reason": "outlier",
            },
        ])
        issues = adapt_validation_reports({"aggregate_leaks": agg})
        assert len(_issues_by_rule(issues, "AGG02")) == 0
        assert set(_issues_by_rule(issues, "AGG01")["severity"]) == {SEVERITY_WARN}

    def test_classification_adapter_global_rules_are_warns(self):
        classification = pd.DataFrame([
            {
                "rule": "I2: DL -> PRIVATE_CREDIT",
                "disagreement_count": 12,
                "sample_names": "['Acme Corp']",
            }
        ])
        issues = adapt_validation_reports({"classification_validation": classification})
        result = _issues_by_rule(issues, "CLS_I2")
        assert len(result) == 1
        assert result.iloc[0]["severity"] == SEVERITY_WARN


class TestQualitySummary:
    def test_quality_summary_tiers(self):
        df = _make_unified_df([
            {"cik": "0000000100"},
            {"cik": "0000000101", "fair_value": ""},
        ])
        reports = run_column_quality_validation(df)
        summary = reports["data_quality_metrics"]
        by_cik = dict(zip(summary["cik"], summary["validation_tier"]))
        assert by_cik["0000000101"] == "UNDER_REVIEW"
        assert "row_validation_issues" in reports
        assert "column_quality_metrics" in reports

    def test_build_quality_summary_no_issues_verified(self):
        df = _make_unified_df([{}])
        summary = build_quality_summary(
            df,
            pd.DataFrame(columns=[
                "dataset", "source", "cik", "report_date", "row_key",
                "column", "rule_id", "severity", "evidence_strength",
                "status", "action", "value", "message", "evidence",
            ]),
        )
        assert summary.iloc[0]["validation_tier"] == "VERIFIED"
