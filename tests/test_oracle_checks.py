"""Tests for pipeline.oracle_checks -- comprehensive oracle check functions."""

import pandas as pd
import pytest

from pipeline.oracle_checks import (
    ALL_CHECK_IDS,
    CHECK_REGISTRY,
    CheckResult,
    check_A01_subtotal_arithmetic,
    check_J01_position_key_stability,
    check_J03_fuzzy_fallback_rate,
    check_A04_gav_reconciliation,
    check_A07_pct_of_net_assets_sum,
    check_B01_leaf_completeness,
    check_B02_unique_position_keys,
    check_B07_single_accession_per_quarter,
    check_B08_comparative_period_exclusion,
    check_C01_debt_has_rate,
    check_C04_equity_has_shares,
    check_C05_no_rate_on_common_equity,
    check_C08_fv_required,
    check_D01_position_count_band,
    check_D02_fv_stability,
    check_D03_count_fv_divergence,
    check_D06_position_continuity,
    check_D07_rate_distribution_stability,
    check_E02_holdings_fv_vs_total_assets,
    check_E04_nav_per_share_sanity,
    check_E07_position_count_vs_filing,
    check_F01_interest_rate_range,
    check_F03_fair_value_sign,
    check_F07_null_fair_value,
    check_F08_duplicate_detection,
    check_F09_text_corruption,
    check_F11_shares_sign,
    check_F12_rate_scale_detection,
    check_G01_keyword_aggregate_detection,
    check_G02_arithmetic_subtotal_detection,
    check_G03_header_row_detection,
    check_H01_source_fact_coverage,
    check_H05_bdc_source_vs_unified_gap,
    check_I02_leaf_marker_accuracy,
    check_I06_non_private_market_exclusion,
    check_J04_unique_position_id_per_report_date,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _source_detail(rows):
    """Build a source reconciliation detail DataFrame from row dicts."""
    defaults = {
        "status": "matched",
        "match_tier": "",
        "issue_severity": "",
        "residual_class": "reconciled",
        "blocking_issue": "false",
        "calibrated_status": "reconciled",
        "calibration_reason": "",
        "cik": "0001786108",
        "entity_name": "Trinity Capital Inc.",
        "report_date": "2024-12-31",
        "period": "2024-12-31",
        "accession_number": "0001786108-25-000001",
        "form_type": "10-K",
        "filing_date": "2025-03-01",
        "context_id": "ctx",
        "source_row_id": "1",
        "output_row_id": "1",
        "raw_investment_identifier": "Acme Corp Term Loan",
        "normalized_investment_identifier": "acme corp term loan",
        "dimensions_raw": "",
        "concept_names": "InvestmentOwnedAtFairValue",
        "source_wrapper_disposition": "debt_position_leaf",
        "source_wrapper_rule_id": "TRINITY_DEBT_LEAF_V1",
        "source_wrapper_family": "debt",
        "source_wrapper_parent_key": "acme corp",
        "source_wrapper_position_key": "acme corp term loan",
        "source_wrapper_structured_leaf_key": "",
        "source_wrapper_investment_date_key": "",
        "source_wrapper_maturity_date_key": "",
        "source_wrapper_rate_key": "",
        "source_wrapper_signature_status": "pass",
        "source_wrapper_unparsed_remainder": "",
        "output_wrapper_disposition": "",
        "output_wrapper_rule_id": "",
        "output_wrapper_family": "",
        "output_wrapper_parent_key": "",
        "output_wrapper_position_key": "",
        "output_wrapper_structured_leaf_key": "",
        "output_wrapper_investment_date_key": "",
        "output_wrapper_maturity_date_key": "",
        "output_wrapper_rate_key": "",
        "output_wrapper_signature_status": "",
        "output_wrapper_unparsed_remainder": "",
        "source_fair_value": "5000000",
        "output_fair_value": "5000000",
        "source_cost": "",
        "output_cost": "",
        "source_principal_amount": "",
        "output_principal_amount": "",
        "source_shares_held": "",
        "output_shares_held": "",
        "source_interest_rate": "",
        "output_interest_rate": "",
        "source_basis_spread": "",
        "output_basis_spread": "",
        "source_pik_rate": "",
        "output_pik_rate": "",
        "mismatched_fields": "",
        "issuer_name": "",
        "instrument_description": "",
        "index_classification": "",
        "asset_category": "",
        "issuer_category": "",
        "evidence": "",
    }
    merged = [{**defaults, **row} for row in rows]
    return pd.DataFrame(merged)


def _holdings(rows):
    """Build a unified holdings DataFrame from row dicts."""
    defaults = {
        "cik": "0001786108",
        "entity_name": "Trinity Capital Inc.",
        "report_date": "2024-12-31",
        "source": "bdc",
        "issuer_name": "Acme Corp",
        "instrument_description": "Senior Secured First Lien Term Loan",
        "fair_value": "5000000",
        "cost": "5000000",
        "interest_rate": "0.10",
        "basis_spread": "0.05",
        "shares_held": "",
        "principal_amount": "5000000",
        "pct_of_net_assets": "1.5",
        "index_classification": "senior_secured_debt",
        "asset_category": "debt",
        "issuer_category": "",
        "bdc_investment_identifier": "Acme Corp, Term Loan",
    }
    merged = [{**defaults, **row} for row in rows]
    return pd.DataFrame(merged)


def _fund_financials(rows):
    """Build a fund financials DataFrame from row dicts."""
    defaults = {
        "cik": "0001786108",
        "report_date": "2024-12-31",
        "investments_at_fair_value": "100000000",
        "total_assets": "120000000",
        "net_assets": "80000000",
        "nav_per_share": "15.0",
        "shares_outstanding": "5333333",
    }
    merged = [{**defaults, **row} for row in rows]
    return pd.DataFrame(merged)


# ===================================================================
# CATEGORY A TESTS
# ===================================================================

class TestA01SubtotalArithmetic:
    def test_pass_when_rollup_matches_children(self):
        detail = _source_detail([
            {
                "source_wrapper_disposition": "debt_issuer_rollup",
                "source_wrapper_parent_key": "acme corp",
                "source_wrapper_family": "debt",
                "source_fair_value": "10000000",
                "source_row_id": "parent",
                "output_row_id": "",
            },
            {
                "source_wrapper_disposition": "debt_position_leaf",
                "source_wrapper_parent_key": "acme corp term loan",
                "source_wrapper_family": "debt",
                "source_fair_value": "6000000",
                "source_row_id": "child1",
            },
            {
                "source_wrapper_disposition": "debt_position_leaf",
                "source_wrapper_parent_key": "acme corp revolver",
                "source_wrapper_family": "debt",
                "source_fair_value": "4000000",
                "source_row_id": "child2",
            },
        ])
        results = check_A01_subtotal_arithmetic(detail)
        assert any(r.status == "pass" for r in results)

    def test_fail_when_rollup_mismatches_children(self):
        detail = _source_detail([
            {
                "source_wrapper_disposition": "debt_issuer_rollup",
                "source_wrapper_parent_key": "acme corp",
                "source_wrapper_family": "debt",
                "source_fair_value": "20000000",
                "source_row_id": "parent",
                "output_row_id": "",
            },
            {
                "source_wrapper_disposition": "debt_position_leaf",
                "source_wrapper_parent_key": "acme corp term loan",
                "source_wrapper_family": "debt",
                "source_fair_value": "6000000",
                "source_row_id": "child1",
            },
        ])
        results = check_A01_subtotal_arithmetic(detail)
        assert any(r.status == "fail" for r in results)

    def test_skip_on_empty(self):
        results = check_A01_subtotal_arithmetic(pd.DataFrame())
        assert results[0].status == "skip"


class TestA04GavReconciliation:
    def test_pass_within_tolerance(self):
        holdings = _holdings([{"fair_value": "95000000"}])
        ff = _fund_financials([{"investments_at_fair_value": "100000000"}])
        results = check_A04_gav_reconciliation(holdings, ff)
        assert any(r.status == "pass" for r in results)

    def test_fail_outside_tolerance(self):
        holdings = _holdings([{"fair_value": "50000000"}])
        ff = _fund_financials([{"investments_at_fair_value": "100000000"}])
        results = check_A04_gav_reconciliation(holdings, ff)
        assert any(r.status == "fail" for r in results)

    def test_skip_no_financials(self):
        holdings = _holdings([{}])
        results = check_A04_gav_reconciliation(holdings, None)
        assert results[0].status == "skip"


class TestA07PctSum:
    def test_pass_normal_sum(self):
        rows = [{"pct_of_net_assets": str(i)} for i in range(1, 11)]
        holdings = _holdings(rows)
        results = check_A07_pct_of_net_assets_sum(holdings)
        assert any(r.status == "pass" for r in results)

    def test_fail_extreme_sum(self):
        rows = [{"pct_of_net_assets": "100"} for _ in range(5)]
        holdings = _holdings(rows)
        results = check_A07_pct_of_net_assets_sum(holdings)
        assert any(r.status == "fail" for r in results)


# ===================================================================
# CATEGORY B TESTS
# ===================================================================

class TestB01LeafCompleteness:
    def test_pass_all_leaves_have_fv(self):
        detail = _source_detail([
            {"source_fair_value": "5000000"},
            {"source_fair_value": "3000000"},
        ])
        results = check_B01_leaf_completeness(detail)
        assert any(r.status == "pass" for r in results)

    def test_skip_on_empty(self):
        results = check_B01_leaf_completeness(pd.DataFrame())
        assert results[0].status == "skip"


class TestB02UniquePositionKeys:
    def test_pass_no_dupes(self):
        holdings = _holdings([
            {"bdc_investment_identifier": "Acme Corp, Term Loan"},
            {"bdc_investment_identifier": "Beta Inc, Term Loan"},
        ])
        results = check_B02_unique_position_keys(holdings)
        assert any(r.status == "pass" for r in results)

    def test_fail_duplicates(self):
        holdings = _holdings([
            {"bdc_investment_identifier": "Acme Corp, Term Loan"},
            {"bdc_investment_identifier": "Acme Corp, Term Loan"},
        ])
        results = check_B02_unique_position_keys(holdings)
        assert any(r.status == "fail" for r in results)

    def test_prefers_unified_position_key_when_present(self):
        holdings = _holdings([
            {"bdc_investment_identifier": "same raw id", "position_key": "acme corp term loan"},
            {"bdc_investment_identifier": "same raw id", "position_key": "beta inc term loan"},
        ])
        results = check_B02_unique_position_keys(holdings)
        assert any(r.status == "pass" for r in results)


class TestB07SingleAccession:
    def test_pass_single_accession(self):
        detail = _source_detail([
            {"accession_number": "0001786108-25-000001", "form_type": "10-K"},
        ])
        results = check_B07_single_accession_per_quarter(detail)
        assert any(r.status == "pass" for r in results)

    def test_warn_multiple_accessions(self):
        detail = _source_detail([
            {"accession_number": "0001786108-25-000001", "form_type": "10-K"},
            {"accession_number": "0001786108-25-000002", "form_type": "10-K"},
        ])
        results = check_B07_single_accession_per_quarter(detail)
        assert any(r.status == "warn" for r in results)


class TestB08ComparativePeriod:
    def test_pass_no_comparative(self):
        detail = _source_detail([{"period": "2024-12-31", "report_date": "2024-12-31"}])
        results = check_B08_comparative_period_exclusion(detail)
        assert results[0].status == "pass"

    def test_fail_blocking_comparative(self):
        detail = _source_detail([{
            "period": "2023-12-31",
            "report_date": "2024-12-31",
            "blocking_issue": "true",
        }])
        results = check_B08_comparative_period_exclusion(detail)
        assert results[0].status == "fail"


# ===================================================================
# CATEGORY C TESTS
# ===================================================================

class TestC01DebtHasRate:
    def test_pass_debt_with_rates(self):
        holdings = _holdings([
            {"index_classification": "senior_secured_debt", "interest_rate": "0.10"},
            {"index_classification": "senior_secured_debt", "basis_spread": "0.05"},
        ])
        results = check_C01_debt_has_rate(holdings)
        assert any(r.status == "pass" for r in results)

    def test_fail_debt_without_rates(self):
        rows = [
            {"index_classification": "senior_secured_debt", "interest_rate": "", "basis_spread": ""}
            for _ in range(10)
        ]
        holdings = _holdings(rows)
        results = check_C01_debt_has_rate(holdings)
        assert any(r.status == "fail" for r in results)


class TestC04EquityHasShares:
    def test_pass_equity_with_shares(self):
        holdings = _holdings([
            {"index_classification": "equity", "shares_held": "1000",
             "asset_category": "equity", "instrument_description": "Common Stock"},
        ])
        results = check_C04_equity_has_shares(holdings)
        assert any(r.status == "pass" for r in results)


class TestC05NoRateOnCommonEquity:
    def test_pass_no_rate_on_common(self):
        holdings = _holdings([
            {"instrument_description": "Common Stock", "interest_rate": "0",
             "index_classification": "equity"},
        ])
        results = check_C05_no_rate_on_common_equity(holdings)
        assert results[0].status == "pass"

    def test_fail_rate_on_common(self):
        rows = [
            {"instrument_description": "Common Stock", "interest_rate": "0.08"}
            for _ in range(20)
        ]
        holdings = _holdings(rows)
        results = check_C05_no_rate_on_common_equity(holdings)
        assert results[0].status == "fail"


class TestC08FvRequired:
    def test_pass_all_have_fv(self):
        holdings = _holdings([{"fair_value": "5000000", "index_classification": "debt"}])
        results = check_C08_fv_required(holdings)
        assert results[0].status == "pass"


# ===================================================================
# CATEGORY D TESTS
# ===================================================================

class TestD01PositionCountBand:
    def test_pass_stable_counts(self):
        holdings = _holdings(
            [{"report_date": "2024-09-30"} for _ in range(10)]
            + [{"report_date": "2024-12-31"} for _ in range(12)]
        )
        results = check_D01_position_count_band(holdings)
        assert any(r.status == "pass" for r in results)

    def test_fail_spike(self):
        holdings = _holdings(
            [{"report_date": "2024-09-30"} for _ in range(10)]
            + [{"report_date": "2024-12-31"} for _ in range(100)]
        )
        results = check_D01_position_count_band(holdings)
        assert any(r.status == "fail" for r in results)


class TestD02FvStability:
    def test_pass_stable_fv(self):
        holdings = _holdings([
            {"report_date": "2024-09-30", "fair_value": "5000000"},
            {"report_date": "2024-12-31", "fair_value": "5500000"},
        ])
        results = check_D02_fv_stability(holdings)
        assert any(r.status == "pass" for r in results)


class TestD03CountFvDivergence:
    def test_pass_no_divergence(self):
        holdings = _holdings([
            {"report_date": "2024-09-30", "fair_value": "5000000"},
            {"report_date": "2024-12-31", "fair_value": "5000000"},
        ])
        results = check_D03_count_fv_divergence(holdings)
        # Should pass since count ratio is 1:1
        assert all(r.status in ("pass", "skip") for r in results)


class TestD06PositionContinuity:
    def test_pass_high_continuity(self):
        holdings = _holdings([
            {"report_date": "2024-09-30", "issuer_name": "Acme Corp"},
            {"report_date": "2024-09-30", "issuer_name": "Beta Inc"},
            {"report_date": "2024-12-31", "issuer_name": "Acme Corp"},
            {"report_date": "2024-12-31", "issuer_name": "Beta Inc"},
        ])
        results = check_D06_position_continuity(holdings)
        assert any(r.status == "pass" for r in results)

    def test_fail_low_continuity(self):
        holdings = _holdings([
            {"report_date": "2024-09-30", "issuer_name": "Acme Corp"},
            {"report_date": "2024-09-30", "issuer_name": "Beta Inc"},
            {"report_date": "2024-12-31", "issuer_name": "Gamma LLC"},
            {"report_date": "2024-12-31", "issuer_name": "Delta Holdings"},
        ])
        results = check_D06_position_continuity(holdings)
        assert any(r.status == "fail" for r in results)


class TestD07RateStability:
    def test_skip_no_rate_data(self):
        holdings = _holdings([{"interest_rate": ""}])
        results = check_D07_rate_distribution_stability(holdings)
        assert results[0].status == "skip"


# ===================================================================
# CATEGORY E TESTS
# ===================================================================

class TestE02HoldingsFvVsTotalAssets:
    def test_pass_holdings_below_total_assets(self):
        holdings = _holdings([{"fair_value": "100000000"}])
        ff = _fund_financials([{"total_assets": "120000000"}])
        results = check_E02_holdings_fv_vs_total_assets(holdings, ff)
        assert any(r.status == "pass" for r in results)

    def test_fail_holdings_above_total_assets(self):
        holdings = _holdings([{"fair_value": "200000000"}])
        ff = _fund_financials([{"total_assets": "120000000"}])
        results = check_E02_holdings_fv_vs_total_assets(holdings, ff)
        assert any(r.status == "fail" for r in results)


class TestE04NavPerShareSanity:
    def test_pass_consistent(self):
        ff = _fund_financials([{
            "nav_per_share": "15.0",
            "shares_outstanding": "5333333",
            "net_assets": "80000000",
        }])
        results = check_E04_nav_per_share_sanity(ff)
        assert any(r.status == "pass" for r in results)

    def test_fail_inconsistent(self):
        ff = _fund_financials([{
            "nav_per_share": "15.0",
            "shares_outstanding": "5333333",
            "net_assets": "200000000",
        }])
        results = check_E04_nav_per_share_sanity(ff)
        assert any(r.status == "fail" for r in results)


class TestE07PositionCountVsFiling:
    def test_pass_close_counts(self):
        detail = _source_detail([
            {"source_wrapper_disposition": "debt_position_leaf", "source_row_id": str(i)}
            for i in range(10)
        ])
        holdings = _holdings([{} for _ in range(10)])
        results = check_E07_position_count_vs_filing(detail, holdings)
        assert any(r.status == "pass" for r in results)


# ===================================================================
# CATEGORY F TESTS
# ===================================================================

class TestF01InterestRateRange:
    def test_pass_normal_rates(self):
        holdings = _holdings([
            {"interest_rate": "0.08"},
            {"interest_rate": "0.12"},
        ])
        results = check_F01_interest_rate_range(holdings)
        assert results[0].status == "pass"

    def test_warn_high_rates(self):
        holdings = _holdings([
            {"interest_rate": "500"},  # Way out of range
        ])
        results = check_F01_interest_rate_range(holdings)
        assert results[0].status in ("warn", "fail")


class TestF03FairValueSign:
    def test_pass_all_positive(self):
        holdings = _holdings([
            {"fair_value": "5000000"},
            {"fair_value": "3000000"},
        ])
        results = check_F03_fair_value_sign(holdings)
        assert results[0].status == "pass"

    def test_fail_many_negative(self):
        rows = [{"fair_value": "-1000000"} for _ in range(10)]
        holdings = _holdings(rows)
        results = check_F03_fair_value_sign(holdings)
        assert results[0].status == "fail"


class TestF07NullFairValue:
    def test_pass_no_nulls(self):
        holdings = _holdings([{"fair_value": "5000000"}])
        results = check_F07_null_fair_value(holdings)
        assert results[0].status == "pass"


class TestF08DuplicateDetection:
    def test_pass_no_dupes(self):
        holdings = _holdings([
            {"issuer_name": "Acme Corp", "fair_value": "5000000"},
            {"issuer_name": "Beta Inc", "fair_value": "3000000"},
        ])
        results = check_F08_duplicate_detection(holdings)
        assert results[0].status == "pass"

    def test_warn_dupes(self):
        holdings = _holdings([
            {"issuer_name": "Acme Corp", "instrument_description": "Term Loan",
             "fair_value": "5000000"},
            {"issuer_name": "Acme Corp", "instrument_description": "Term Loan",
             "fair_value": "5000000"},
        ])
        results = check_F08_duplicate_detection(holdings)
        assert results[0].status == "warn"


class TestF09TextCorruption:
    def test_pass_clean_text(self):
        holdings = _holdings([{"issuer_name": "Acme Corp"}])
        results = check_F09_text_corruption(holdings)
        assert results[0].status == "pass"


class TestF11SharesSign:
    def test_pass_positive_shares(self):
        holdings = _holdings([{"shares_held": "1000"}])
        results = check_F11_shares_sign(holdings)
        assert results[0].status == "pass"

    def test_warn_negative_shares(self):
        holdings = _holdings([{"shares_held": "-1000"}])
        results = check_F11_shares_sign(holdings)
        assert results[0].status == "warn"


class TestF12RateScale:
    def test_pass_normal_scale(self):
        holdings = _holdings([{"interest_rate": "8.5"}])
        results = check_F12_rate_scale_detection(holdings)
        assert results[0].status == "pass"


# ===================================================================
# CATEGORY G TESTS
# ===================================================================

class TestG01KeywordAggregate:
    def test_pass_no_aggregates(self):
        holdings = _holdings([
            {"issuer_name": "Acme Corp", "instrument_description": "Term Loan"},
        ])
        results = check_G01_keyword_aggregate_detection(holdings)
        assert results[0].status == "pass"

    def test_warn_aggregate_leaked(self):
        holdings = _holdings([
            {"issuer_name": "Total investments at fair value"},
        ])
        results = check_G01_keyword_aggregate_detection(holdings)
        assert results[0].status == "warn"


class TestG02ArithmeticSubtotal:
    def test_pass_no_subtotals(self):
        holdings = _holdings([
            {"fair_value": "5000000"},
            {"fair_value": "3000000"},
            {"fair_value": "7000000"},
        ])
        results = check_G02_arithmetic_subtotal_detection(holdings)
        assert results[0].status == "pass"

    def test_warn_subtotal_detected(self):
        # Row 0 FV = sum of rows 1+2
        holdings = _holdings([
            {"fair_value": "8000000"},
            {"fair_value": "5000000"},
            {"fair_value": "3000000"},
        ])
        results = check_G02_arithmetic_subtotal_detection(holdings)
        assert results[0].status == "warn"


class TestG03HeaderRow:
    def test_pass_no_headers(self):
        holdings = _holdings([{"fair_value": "5000000"}])
        results = check_G03_header_row_detection(holdings)
        assert results[0].status == "pass"


# ===================================================================
# CATEGORY H TESTS
# ===================================================================

class TestH01SourceFactCoverage:
    def test_pass_high_coverage(self):
        detail = _source_detail([
            {"source_wrapper_disposition": "debt_position_leaf",
             "source_fair_value": "5000000",
             "output_row_id": "1"},
            {"source_wrapper_disposition": "debt_position_leaf",
             "source_fair_value": "3000000",
             "status": "matched"},
        ])
        holdings = _holdings([{}])
        results = check_H01_source_fact_coverage(detail, holdings)
        assert results[0].status == "pass"


class TestH05BdcSourceVsUnifiedGap:
    def test_pass_no_source_only(self):
        detail = _source_detail([{"status": "matched"}])
        results = check_H05_bdc_source_vs_unified_gap(detail)
        assert results[0].status == "pass"

    def test_fail_blocking_source_only(self):
        detail = _source_detail([{
            "status": "missing_from_pipeline",
            "blocking_issue": "true",
        }])
        results = check_H05_bdc_source_vs_unified_gap(detail)
        assert results[0].status in ("fail", "warn")


# ===================================================================
# CATEGORY I TESTS
# ===================================================================

class TestI02LeafMarkerAccuracy:
    def test_pass_leaves_have_fv(self):
        detail = _source_detail([
            {"source_wrapper_disposition": "debt_position_leaf", "source_fair_value": "5000000"},
        ])
        results = check_I02_leaf_marker_accuracy(detail)
        assert results[0].status == "pass"


class TestI06NonPrivateMarketExclusion:
    def test_pass_npm_matches_pattern(self):
        detail = _source_detail([{
            "source_wrapper_disposition": "non_private_market",
            "raw_investment_identifier": "Cash and money market funds",
        }])
        results = check_I06_non_private_market_exclusion(detail)
        assert results[0].status == "pass"


# ===================================================================
# REGISTRY TESTS
# ===================================================================

class TestCheckRegistry:
    def test_all_checks_registered(self):
        assert len(CHECK_REGISTRY) >= 35

    def test_all_check_ids_sorted(self):
        assert ALL_CHECK_IDS == sorted(ALL_CHECK_IDS)

    def test_all_checks_return_list(self):
        """Each check function should return a list when given empty DataFrames."""
        for check_id, (func, _) in CHECK_REGISTRY.items():
            import inspect
            sig = inspect.signature(func)
            params = list(sig.parameters.keys())
            kwargs = {}
            for p in params:
                if "df" in p:
                    kwargs[p] = pd.DataFrame()
            try:
                result = func(**kwargs)
                assert isinstance(result, list), f"{check_id} did not return list"
                for r in result:
                    assert isinstance(r, CheckResult), f"{check_id} did not return CheckResult"
            except TypeError:
                pass  # Some checks need non-None args


class TestCheckResult:
    def test_to_dict(self):
        result = CheckResult(
            check_id="A01",
            scope="global",
            status="pass",
            metric_value=1.0,
            threshold=0.95,
            residual_rows=0,
            residual_fv=0,
            message="All good",
        )
        d = result.to_dict()
        assert d["check_id"] == "A01"
        assert d["status"] == "pass"
        assert d["detail_rows"] == 0


# ---------------------------------------------------------------------------
# Matches fixture
# ---------------------------------------------------------------------------

def _matches(rows):
    """Build a position_matches DataFrame from row dicts."""
    defaults = {
        "cik": "0001287750",
        "entity_name": "ARES CAPITAL CORP",
        "source": "bdc",
        "match_method": "B1b_position_key",
        "match_key": "acme corp term loan",
        "match_score": "1.0",
    }
    merged = [{**defaults, **row} for row in rows]
    return pd.DataFrame(merged)


# ===================================================================
# CATEGORY J TESTS: Position Matching Quality
# ===================================================================

class TestJ04UniquePositionIdPerReportDate:
    """Tests for J04: no duplicate position_id within one CIK/source/date."""

    def test_pass_unique_position_ids(self):
        holdings = _holdings([
            {"position_id": "POS-00000001", "issuer_name": "Acme Corp"},
            {"position_id": "POS-00000002", "issuer_name": "Beta Inc"},
        ])
        results = check_J04_unique_position_id_per_report_date(holdings)
        assert results[0].status == "pass"

    def test_fail_duplicate_position_id_same_date(self):
        holdings = _holdings([
            {"position_id": "POS-00000001", "issuer_name": "Acme Corp"},
            {"position_id": "POS-00000001", "issuer_name": "Beta Inc"},
        ])
        results = check_J04_unique_position_id_per_report_date(holdings)
        assert results[0].status == "fail"
        assert results[0].metric_value == 1


class TestJ01PositionKeyStability:
    """Tests for J01: B1b rate for wrapped CIKs."""

    def test_skip_when_no_matches(self):
        results = check_J01_position_key_stability(None)
        assert len(results) == 1
        assert results[0].status == "skip"

    def test_skip_when_empty(self):
        results = check_J01_position_key_stability(pd.DataFrame())
        assert len(results) == 1
        assert results[0].status == "skip"

    def test_pass_high_b1b_rate(self, monkeypatch):
        """Wrapped CIK with >70% B1b among non-A/B1 matches -> pass."""
        monkeypatch.setattr(
            "pipeline.oracle_checks._get_wrapped_ciks",
            lambda: {"0001287750"},
        )
        df = _matches([
            # 8 B1b matches
            *[{"match_method": "B1b_position_key"}] * 8,
            # 2 B2 matches (below threshold)
            *[{"match_method": "B2_exact_name"}] * 2,
            # 5 A matches (excluded from denominator)
            *[{"match_method": "A_within_filing"}] * 5,
        ])
        results = check_J01_position_key_stability(df)
        passed = [r for r in results if r.cik == "0001287750"]
        assert len(passed) == 1
        assert passed[0].status == "pass"
        assert passed[0].metric_value == pytest.approx(0.8)  # 8/10

    def test_fail_low_b1b_rate(self, monkeypatch):
        """Wrapped CIK with <70% B1b among non-A/B1 matches -> fail."""
        monkeypatch.setattr(
            "pipeline.oracle_checks._get_wrapped_ciks",
            lambda: {"0001572694"},
        )
        df = _matches([
            # 1 B1b, 9 D_fuzzy
            {"cik": "0001572694", "match_method": "B1b_position_key"},
            *[{"cik": "0001572694", "match_method": "D_fuzzy"}] * 9,
        ])
        results = check_J01_position_key_stability(df)
        failed = [r for r in results if r.cik == "0001572694"]
        assert len(failed) == 1
        assert failed[0].status == "fail"
        assert failed[0].metric_value == pytest.approx(0.1)  # 1/10
        assert not failed[0].detail.empty  # tier breakdown provided

    def test_skip_all_tier_a(self, monkeypatch):
        """Wrapped CIK with only A matches -> skip (key not tested)."""
        monkeypatch.setattr(
            "pipeline.oracle_checks._get_wrapped_ciks",
            lambda: {"0001287750"},
        )
        df = _matches([
            *[{"match_method": "A_within_filing"}] * 10,
        ])
        results = check_J01_position_key_stability(df)
        assert len(results) == 1
        assert results[0].status == "skip"

    def test_non_wrapped_cik_excluded(self, monkeypatch):
        """Non-wrapped CIKs should not be evaluated."""
        monkeypatch.setattr(
            "pipeline.oracle_checks._get_wrapped_ciks",
            lambda: {"0001287750"},  # only Ares
        )
        df = _matches([
            # Non-wrapped CIK with bad B1b rate
            *[{"cik": "0009999999", "match_method": "D_fuzzy"}] * 10,
        ])
        results = check_J01_position_key_stability(df)
        # Should skip -- no matches for the wrapped CIK
        assert all(r.status == "skip" for r in results)


class TestJ03FuzzyFallbackRate:
    """Tests for J03: fuzzy match rate for wrapped CIKs."""

    def test_skip_when_no_matches(self):
        results = check_J03_fuzzy_fallback_rate(None)
        assert len(results) == 1
        assert results[0].status == "skip"

    def test_pass_low_fuzzy(self, monkeypatch):
        """Wrapped CIK with <10% fuzzy -> pass."""
        monkeypatch.setattr(
            "pipeline.oracle_checks._get_wrapped_ciks",
            lambda: {"0001287750"},
        )
        df = _matches([
            *[{"match_method": "A_within_filing"}] * 50,
            *[{"match_method": "B1b_position_key"}] * 40,
            *[{"match_method": "B2_exact_name"}] * 5,
            *[{"match_method": "D_fuzzy"}] * 5,  # 5% fuzzy
        ])
        results = check_J03_fuzzy_fallback_rate(df)
        passed = [r for r in results if r.cik == "0001287750"]
        assert len(passed) == 1
        assert passed[0].status == "pass"
        assert passed[0].metric_value == pytest.approx(0.05)

    def test_fail_high_fuzzy(self, monkeypatch):
        """Wrapped CIK with >10% fuzzy -> fail."""
        monkeypatch.setattr(
            "pipeline.oracle_checks._get_wrapped_ciks",
            lambda: {"0001572694"},
        )
        df = _matches([
            *[{"cik": "0001572694", "match_method": "B1b_position_key"}] * 2,
            *[{"cik": "0001572694", "match_method": "D_fuzzy"}] * 18,  # 90%
        ])
        results = check_J03_fuzzy_fallback_rate(df)
        failed = [r for r in results if r.cik == "0001572694"]
        assert len(failed) == 1
        assert failed[0].status == "fail"
        assert failed[0].metric_value == pytest.approx(0.9)
        assert not failed[0].detail.empty

    def test_pass_zero_fuzzy(self, monkeypatch):
        """Wrapped CIK with no fuzzy at all -> pass."""
        monkeypatch.setattr(
            "pipeline.oracle_checks._get_wrapped_ciks",
            lambda: {"0001287750"},
        )
        df = _matches([
            *[{"match_method": "A_within_filing"}] * 10,
            *[{"match_method": "B1b_position_key"}] * 10,
        ])
        results = check_J03_fuzzy_fallback_rate(df)
        passed = [r for r in results if r.cik == "0001287750"]
        assert len(passed) == 1
        assert passed[0].status == "pass"
        assert passed[0].metric_value == 0.0

    def test_boundary_exactly_10_pct(self, monkeypatch):
        """Exactly 10% fuzzy is at the threshold -> pass (<=)."""
        monkeypatch.setattr(
            "pipeline.oracle_checks._get_wrapped_ciks",
            lambda: {"0001287750"},
        )
        df = _matches([
            *[{"match_method": "B1b_position_key"}] * 9,
            *[{"match_method": "D_fuzzy"}] * 1,  # exactly 10%
        ])
        results = check_J03_fuzzy_fallback_rate(df)
        passed = [r for r in results if r.cik == "0001287750"]
        assert len(passed) == 1
        assert passed[0].status == "pass"

    def test_detail_includes_match_keys(self, monkeypatch):
        """Failed check should include fuzzy match keys for debugging."""
        monkeypatch.setattr(
            "pipeline.oracle_checks._get_wrapped_ciks",
            lambda: {"0001572694"},
        )
        df = _matches([
            {"cik": "0001572694", "match_method": "D_fuzzy",
             "match_key": "lithium technologies inc"},
            *[{"cik": "0001572694", "match_method": "D_fuzzy",
               "match_key": "atx networks corp"}] * 4,
        ])
        results = check_J03_fuzzy_fallback_rate(df)
        failed = [r for r in results if r.cik == "0001572694"]
        assert len(failed) == 1
        assert "match_key" in failed[0].detail.columns


# ===================================================================
# DIAGNOSTIC: diagnose_fuzzy_fallbacks
# ===================================================================

class TestDiagnoseFuzzyFallbacks:
    """Tests for diagnose_fuzzy_fallbacks()."""

    def test_basic_diagnostic(self):
        """D_fuzzy match joined to unified shows position keys + diff."""
        from pipeline.oracle_checks import diagnose_fuzzy_fallbacks

        matches = pd.DataFrame([{
            "cik": "0001287750",
            "match_method": "D_fuzzy",
            "begin_report_date": "2024-03-31",
            "end_report_date": "2024-06-30",
            "begin_issuer_name": "Acme Corp",
            "end_issuer_name": "Acme Corp",
            "begin_fair_value": "1000000",
            "end_fair_value": "1050000",
            "match_score": "0.92",
        }])
        unified = pd.DataFrame([
            {"cik": "1287750", "report_date": "2024-03-31",
             "issuer_name": "Acme Corp", "fair_value": "1000000",
             "position_key": "acme corp first lien 7.5"},
            {"cik": "1287750", "report_date": "2024-06-30",
             "issuer_name": "Acme Corp", "fair_value": "1050000",
             "position_key": "acme corp first lien 8.0"},
        ])

        result = diagnose_fuzzy_fallbacks(matches, unified)
        assert len(result) == 1
        row = result.iloc[0]
        assert row["begin_position_key"] == "acme corp first lien 7.5"
        assert row["end_position_key"] == "acme corp first lien 8.0"
        assert "tokens differ" in row["key_diff_summary"]
        assert "7.5" in row["key_diff_summary"]
        assert "8.0" in row["key_diff_summary"]

    def test_empty_matches(self):
        """Empty matches_df returns empty DataFrame."""
        from pipeline.oracle_checks import diagnose_fuzzy_fallbacks

        result = diagnose_fuzzy_fallbacks(pd.DataFrame(), pd.DataFrame())
        assert result.empty

    def test_no_fuzzy_matches(self):
        """Non-D_fuzzy rows produce empty result."""
        from pipeline.oracle_checks import diagnose_fuzzy_fallbacks

        matches = pd.DataFrame([{
            "cik": "0001287750",
            "match_method": "B1b_position_key",
            "begin_report_date": "2024-03-31",
            "end_report_date": "2024-06-30",
            "begin_issuer_name": "Acme Corp",
            "end_issuer_name": "Acme Corp",
            "begin_fair_value": "1000000",
            "end_fair_value": "1050000",
        }])
        unified = pd.DataFrame([
            {"cik": "1287750", "report_date": "2024-03-31",
             "issuer_name": "Acme Corp", "fair_value": "1000000",
             "position_key": "acme corp first lien"},
        ])

        result = diagnose_fuzzy_fallbacks(matches, unified)
        assert result.empty

    def test_missing_position_key_column(self):
        """Unified without position_key returns empty + warning."""
        from pipeline.oracle_checks import diagnose_fuzzy_fallbacks

        matches = pd.DataFrame([{
            "cik": "0001287750",
            "match_method": "D_fuzzy",
            "begin_report_date": "2024-03-31",
            "end_report_date": "2024-06-30",
            "begin_issuer_name": "Acme Corp",
            "end_issuer_name": "Acme Corp",
            "begin_fair_value": "1000000",
            "end_fair_value": "1050000",
        }])
        unified = pd.DataFrame([
            {"cik": "1287750", "report_date": "2024-03-31",
             "issuer_name": "Acme Corp", "fair_value": "1000000"},
        ])

        result = diagnose_fuzzy_fallbacks(matches, unified)
        assert result.empty

    def test_identical_position_keys(self):
        """Same key on both sides produces 'identical keys' summary."""
        from pipeline.oracle_checks import diagnose_fuzzy_fallbacks

        matches = pd.DataFrame([{
            "cik": "0001287750",
            "match_method": "D_fuzzy",
            "begin_report_date": "2024-03-31",
            "end_report_date": "2024-06-30",
            "begin_issuer_name": "Acme Corp",
            "end_issuer_name": "Acme Corp",
            "begin_fair_value": "1000000",
            "end_fair_value": "1050000",
            "match_score": "0.90",
        }])
        unified = pd.DataFrame([
            {"cik": "1287750", "report_date": "2024-03-31",
             "issuer_name": "Acme Corp", "fair_value": "1000000",
             "position_key": "acme corp first lien"},
            {"cik": "1287750", "report_date": "2024-06-30",
             "issuer_name": "Acme Corp", "fair_value": "1050000",
             "position_key": "acme corp first lien"},
        ])

        result = diagnose_fuzzy_fallbacks(matches, unified)
        assert len(result) == 1
        assert result.iloc[0]["key_diff_summary"] == "identical keys"
