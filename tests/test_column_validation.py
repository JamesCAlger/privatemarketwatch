"""Tests for pipeline.column_validation."""

import pandas as pd

from pipeline.column_validation import (
    SEVERITY_FAIL,
    SEVERITY_INFO,
    SEVERITY_WARN,
    adapt_validation_reports,
    build_quality_summary,
    build_residual_summary,
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
            "principal_amount_usd": "100000000",
        }])
        issues, _ = validate_column_contracts(df)
        result = _issues_by_rule(issues, "X06")
        assert len(result) == 1
        assert result.iloc[0]["severity"] == SEVERITY_FAIL

    def test_principal_scale_error_exempt_for_unfunded_revolver(self):
        """Unfunded/revolver/delayed-draw positions exempt from X06."""
        for keyword in [
            "Revolver", "Unfunded", "Undrawn", "Commitment",
            "Delayed Draw", "Credit Facility",
        ]:
            df = _make_unified_df([{
                "fair_value": "1000",
                "principal_amount": "100000000",
                "issuer_name": f"Acme Corp - {keyword} Term Loan",
            }])
            issues, _ = validate_column_contracts(df)
            result = _issues_by_rule(issues, "X06")
            assert len(result) == 0, f"X06 should not fire for '{keyword}'"

    def test_rate_percentage_scale_passes_and_high_rate_warns(self):
        ok_df = _make_unified_df([{"interest_rate": "9.8"}])
        ok_issues, _ = validate_column_contracts(ok_df)
        assert len(_issues_by_rule(ok_issues, "C113")) == 0

        warn_df = _make_unified_df([{"interest_rate": "30"}])
        warn_issues, _ = validate_column_contracts(warn_df)
        result = _issues_by_rule(warn_issues, "C113")
        assert len(result) == 1
        assert result.iloc[0]["severity"] == SEVERITY_WARN

    def test_c113_exempts_structured_credit_effective_yield(self):
        """B-trial refinement: CLO/structured effective yields >25% are legitimate."""
        # STRUCTURED_CREDIT effective yield 36% -> exempt (no C113)
        sc = _make_unified_df([{"interest_rate": "36", "asset_class": "STRUCTURED_CREDIT"}])
        assert len(_issues_by_rule(validate_column_contracts(sc)[0], "C113")) == 0

        # "effective interest" descriptor 30% (PRIVATE_CREDIT) -> exempt (no C113)
        eff = _make_unified_df([{
            "interest_rate": "30",
            "bdc_investment_identifier": "Catamaran CLO 2014-1 Subordinated, effective interest 30%",
        }])
        assert len(_issues_by_rule(validate_column_contracts(eff)[0], "C113")) == 0

    def test_c206_flags_issuer_name_dimension_leak(self):
        """B-trial/TorcSill: raw XBRL dimension/term text leaked into issuer_name."""
        # the TorcSill-style contaminated copy fires
        bad = _make_unified_df([{
            "issuer_name": "Debt Securities, Energy Equipment & Services WDE TorcSill "
                           "Holdings LLC, Acquisition Date 08/13/24 , Protective Advance Term Loan",
        }])
        assert len(_issues_by_rule(validate_column_contracts(bad)[0], "C206")) == 1

        for leak in ["X Corp, Acquisition Date 1/1/24", "Y LLC Maturity Date 5/1/28",
                     "Z Inc, % of Net Assets 0.6%"]:
            df = _make_unified_df([{"issuer_name": leak}])
            assert len(_issues_by_rule(validate_column_contracts(df)[0], "C206")) == 1, leak

    def test_c206_clean_issuer_names_pass(self):
        """False-positive guard: clean entity names must NOT fire C206."""
        for ok in ["WDE TorcSill Holdings LLC", "Acme Corp",
                   "JHCC Holdings LLC, One stop 7", "Integro Parent, Inc."]:
            df = _make_unified_df([{"issuer_name": ok}])
            assert len(_issues_by_rule(validate_column_contracts(df)[0], "C206")) == 0, ok

    def test_c113_keeps_private_credit_and_gross_scale(self):
        """False-positive guard: real mis-parses must still fire."""
        # PRIVATE_CREDIT 50% (EOT-balloon-style mis-parse) -> still fires
        pc = _make_unified_df([{"interest_rate": "50"}])
        assert len(_issues_by_rule(validate_column_contracts(pc)[0], "C113")) == 1

        # >75% gross scale error fires even for exempt structured class
        gross = _make_unified_df([{"interest_rate": "80", "asset_class": "STRUCTURED_CREDIT"}])
        assert len(_issues_by_rule(validate_column_contracts(gross)[0], "C113")) == 1

        # negative rate fires for all classes
        neg = _make_unified_df([{"interest_rate": "-3", "asset_class": "STRUCTURED_CREDIT"}])
        assert len(_issues_by_rule(validate_column_contracts(neg)[0], "C113")) == 1

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

    # --- X01 preferred-equity tightening -------------------------------------
    def test_x01_preferred_equity_rate_is_not_flagged(self):
        # False alarm: preferred equity legitimately carries a stated dividend
        # rate. It must NOT fire X01 after the tightening.
        df = _make_unified_df([{
            "asset_class": "PRIVATE_EQUITY",
            "index_classification": "PREFERRED_EQUITY",
            "interest_rate": "16.0",
        }])
        issues, _ = validate_column_contracts(df)
        assert len(_issues_by_rule(issues, "X01")) == 0

    def test_x01_common_equity_rate_still_flagged(self):
        # True positive retained: common equity with a rate is still suspicious.
        df = _make_unified_df([{
            "asset_class": "PRIVATE_EQUITY",
            "index_classification": "COMMON_EQUITY",
            "interest_rate": "16.0",
        }])
        issues, _ = validate_column_contracts(df)
        assert len(_issues_by_rule(issues, "X01")) == 1

    # --- X07 equity-appreciation tightening ----------------------------------
    def test_x07_equity_10x_appreciation_is_not_flagged(self):
        # False alarm: equity/warrants legitimately appreciate >10x cost.
        df = _make_unified_df([{
            "asset_class": "PRIVATE_EQUITY",
            "index_classification": "COMMON_EQUITY",
            "cost": "100000",
            "fair_value": "5000000",  # 50x
        }])
        issues, _ = validate_column_contracts(df)
        assert len(_issues_by_rule(issues, "X07")) == 0

    def test_x07_debt_10x_still_flagged(self):
        # True positive retained: a loan at 50x cost is a real outlier.
        df = _make_unified_df([{
            "asset_class": "PRIVATE_CREDIT",
            "cost": "100000",
            "fair_value": "5000000",  # 50x
        }])
        issues, _ = validate_column_contracts(df)
        assert len(_issues_by_rule(issues, "X07")) == 1

    # --- FX02 / FX03 USD-unit canonicalization -------------------------------
    def test_fx02_noncanonical_usd_token_is_not_flagged(self):
        # False alarm: non-canonical USD unit tokens are still dollars.
        for tok in ("U_USD", "UNIT_USD", "UNIT_STANDARD_USD_K5CWMI1_BU-1-I27"):
            df = _make_unified_df([{"source": "bdc", "fair_value_currency": tok}])
            issues, _ = validate_column_contracts(df)
            assert len(_issues_by_rule(issues, "FX02")) == 0, tok

    def test_fx02_genuine_non_usd_still_flagged(self):
        # True positive retained: a real non-USD unit must still fire.
        df = _make_unified_df([{"source": "bdc", "fair_value_currency": "EUR"}])
        issues, _ = validate_column_contracts(df)
        assert len(_issues_by_rule(issues, "FX02")) == 1

    def test_fx03_noncanonical_usd_token_is_not_flagged(self):
        for tok in ("U_USD", "UNIT_USD", "UNIT_STANDARD_USD_TJGR_KXHI0CIJ"):
            df = _make_unified_df([{"source": "bdc", "cost_currency": tok}])
            issues, _ = validate_column_contracts(df)
            assert len(_issues_by_rule(issues, "FX03")) == 0, tok

    def test_fx03_genuine_non_usd_still_flagged(self):
        df = _make_unified_df([{"source": "bdc", "cost_currency": "GBP"}])
        issues, _ = validate_column_contracts(df)
        assert len(_issues_by_rule(issues, "FX03")) == 1

    # --- C103 negative-FV calibration -----------------------------------------
    def test_c103_unexplained_negative_fv_still_flagged(self):
        # True positive retained: negative FV with positive cost and no
        # unfunded-commitment text is exactly the mis-parse class C103 exists for.
        df = _make_unified_df([{"fair_value": "-125000", "cost": "1000000"}])
        issues, _ = validate_column_contracts(df)
        result = _issues_by_rule(issues, "C103")
        assert len(result) == 1
        assert result.iloc[0]["severity"] == SEVERITY_WARN

    def test_c103_sign_consistent_negative_mark_not_flagged(self):
        # False alarm: cost and FV both negative is a filer's own
        # parenthetical unfunded-commitment mark.
        df = _make_unified_df([{"fair_value": "-125000", "cost": "-68000"}])
        issues, _ = validate_column_contracts(df)
        assert len(_issues_by_rule(issues, "C103")) == 0

    def test_c103_unfunded_keyword_not_flagged(self):
        # False alarm: revolver / delayed-draw text marks a commitment position.
        for kw in ("Revolving Loan", "Delayed Draw Term Loan", "Unfunded",
                   "Letter of Credit"):
            df = _make_unified_df([{
                "fair_value": "-56000",
                "cost": "1000000",
                "bdc_investment_identifier": f"Acme Corp - First Lien {kw}",
            }])
            issues, _ = validate_column_contracts(df)
            assert len(_issues_by_rule(issues, "C103")) == 0, kw

    # --- C104 / C404 demotion --------------------------------------------------
    def test_c104_zero_fv_is_info_track_only(self):
        df = _make_unified_df([{"fair_value": "0"}])
        issues, _ = validate_column_contracts(df)
        result = _issues_by_rule(issues, "C104")
        assert len(result) == 1
        assert result.iloc[0]["severity"] == SEVERITY_INFO
        assert result.iloc[0]["action"] == "TRACK_ONLY"

    def test_c404_negative_pct_is_info_track_only(self):
        df = _make_unified_df([{"pct_of_net_assets": "-0.2"}])
        issues, _ = validate_column_contracts(df)
        result = _issues_by_rule(issues, "C404")
        assert len(result) == 1
        assert result.iloc[0]["severity"] == SEVERITY_INFO
        assert result.iloc[0]["action"] == "TRACK_ONLY"

    def test_c107_negative_cost_still_warns(self):
        # Regression pin: C107 was deliberately NOT scope-cut (retro-test
        # showed sign/keyword exclusions lose reals faster than false alarms).
        df = _make_unified_df([{"cost": "-534000"}])
        issues, _ = validate_column_contracts(df)
        result = _issues_by_rule(issues, "C107")
        assert len(result) == 1
        assert result.iloc[0]["severity"] == SEVERITY_WARN
        assert result.iloc[0]["action"] == "REVIEW"


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
            {
                "cik": "0000000104",
                "report_date": "2024-03-31",
                "gav_ratio": "",
                "gav_ratio_adjusted": "",
                "holdings_source": "bdc",
                "comparison_source": "",
                "reconciliation_status": "SKIP",
                "blocks_verified": True,
                "failure_scope": "no_comparison",
                "gav_rule_id": "GAV_BDC01",
            },
        ])
        issues = adapt_validation_reports({"gav_reconciliation": gav})
        assert _issues_by_rule(issues, "GAV_BDC01").iloc[0]["severity"] == SEVERITY_FAIL
        assert _issues_by_rule(issues, "GAV_BDC02").iloc[0]["severity"] == SEVERITY_WARN
        assert (_issues_by_rule(issues, "GAV_BDC02")["action"] == "BLOCK_VERIFIED").any()
        assert _issues_by_rule(issues, "GAV_NPORT01").iloc[0]["severity"] == SEVERITY_WARN
        assert len(issues) == 4

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

    def test_source_reconciliation_adapter_blocks_verified(self):
        detail = pd.DataFrame([
            {
                "status": "missing_from_pipeline",
                "cik": "0000000100",
                "report_date": "2024-03-31",
                "raw_investment_identifier": "Acme Corp - Term Loan",
                "evidence": "eligible current-period source row has no pipeline output row",
            },
            {
                "status": "collapsed_duplicate_dimension_path",
                "cik": "0000000100",
                "report_date": "2024-03-31",
                "raw_investment_identifier": "Acme Corp - Term Loan",
                "evidence": "same economic facts reported on multiple dimension paths",
            },
            {
                "status": "value_mismatch",
                "blocking_issue": False,
                "calibrated_status": "diagnostic_field_mismatch",
                "cik": "0000000100",
                "report_date": "2024-03-31",
                "raw_investment_identifier": "Diagnostic Co - Equity",
                "mismatched_fields": "principal_amount",
                "calibration_reason": "principal_amount differs on equity position; tracked as diagnostic",
            },
        ])
        issues = adapt_validation_reports({"source_reconciliation_detail": detail})
        result = _issues_by_rule(issues, "SRC_BDC01")
        assert len(result) == 1
        assert result.iloc[0]["severity"] == SEVERITY_FAIL
        assert result.iloc[0]["action"] == "BLOCK_VERIFIED"
        assert len(_issues_by_rule(issues, "collapsed_duplicate_dimension_path")) == 0
        assert len(_issues_by_rule(issues, "SRC_BDC03")) == 0

    def test_position_purity_adapter_warns_without_blocking_verified(self):
        diagnostics = pd.DataFrame([
            {
                "issue_family": "subtotal_candidate",
                "source": "bdc",
                "cik": "0000000100",
                "report_date": "2024-03-31",
                "row_key": "0",
                "bdc_investment_identifier": "Total Senior Secured Loans",
                "issuer_name": "Total Senior Secured Loans",
                "evidence": "identifier matched diagnostic subtotal logic",
            },
            {
                "issue_family": "duplicate_dimension_candidate",
                "source": "bdc",
                "cik": "0000000100",
                "report_date": "2024-03-31",
                "row_key": "1",
                "bdc_investment_identifier": "Acme Corp - First Lien Loan",
                "issuer_name": "Acme Corp",
                "evidence": "same normalized position identity",
            },
            {
                "issue_family": "comparative_period",
                "source": "bdc",
                "cik": "0000000100",
                "report_date": "2024-03-31",
                "row_key": "2",
                "bdc_investment_identifier": "Prior Co - Loan",
                "issuer_name": "Prior Co",
                "evidence": "period before report_date",
            },
        ])
        issues = adapt_validation_reports({
            "position_purity_diagnostics": diagnostics,
        })
        assert set(issues["rule_id"]) == {"PP01", "PP02", "PP03"}
        assert set(issues["severity"]) == {SEVERITY_WARN}
        assert set(issues[issues["rule_id"].isin(["PP01", "PP02"])]["action"]) == {"REVIEW"}

        summary = build_quality_summary(_make_unified_df([{}]), issues)
        assert summary.iloc[0]["validation_tier"] == "VERIFIED"
        assert summary.iloc[0]["warn_count"] == 0


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


class TestResidualSummary:
    def test_x06_residual_summary_groups_without_suppressing_fail(self):
        df = _make_unified_df([
            {
                "issuer_name": "Scale Problem LLC",
                "fair_value": "1000000",
                "principal_amount": "250000000",
                "principal_amount_usd": "250000000",
            },
            {
                "issuer_name": "Normal Loan LLC",
                "fair_value": "1000000",
                "principal_amount": "1000000",
                "principal_amount_usd": "1000000",
            },
        ])
        reports = run_column_quality_validation(df)
        issues = reports["row_validation_issues"]
        x06 = _issues_by_rule(issues, "X06")
        residual = reports["validate_all_residual_summary"]

        assert len(x06) == 1
        assert x06.iloc[0]["severity"] == SEVERITY_FAIL
        assert set(residual["rule_id"]) == {"X06"}
        assert residual.iloc[0]["ratio_band"] == "100x-1000x"
        assert residual.iloc[0]["issue_count"] == 1
        assert "Scale Problem LLC" in residual.iloc[0]["top_issuer_samples"]

    def test_agg01_residual_summary_groups_adapter_warnings(self):
        df = _make_unified_df([{}])
        agg = pd.DataFrame([{
            "cik": "0000000100",
            "report_date": "2024-03-31",
            "issuer_name": "Total Investments at Fair Value",
            "reason": "keyword: total investments",
        }])
        issues = adapt_validation_reports({"aggregate_leaks": agg})
        residual = build_residual_summary(df, issues)

        assert residual.iloc[0]["rule_id"] == "AGG01"
        assert residual.iloc[0]["ratio_band"] == "not_applicable"
        assert residual.iloc[0]["warn_count"] == 1
        assert "Total Investments" in residual.iloc[0]["top_issuer_samples"]
