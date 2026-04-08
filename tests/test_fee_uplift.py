"""Tests for pipeline.fee_uplift module.

Covers:
- Basic uplift computation (income yield - coupon yield)
- Guard rails (cap, floor, outlier exclusion)
- Cross-sectional fallback
- Empty inputs
- Output schema
"""

import pandas as pd
import pytest

from pipeline.fee_uplift import (
    MAX_UPLIFT_PCT,
    MIN_UPLIFT_PCT,
    compute_fee_uplift,
)


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _make_fund_income(rows: list[dict]) -> pd.DataFrame:
    """Create a minimal fund income DataFrame."""
    cols = [
        "cik", "entity_name", "report_quarter", "report_date",
        "form_type", "accession_number", "start_date", "end_date",
        "duration_months", "total_investment_income", "interest_income",
        "dividend_income", "fee_income", "other_income",
        "net_investment_income", "management_fee", "incentive_fee",
        "interest_expense", "total_expenses",
    ]
    df = pd.DataFrame(rows)
    for c in cols:
        if c not in df.columns:
            df[c] = None
    return df


def _make_unified(rows: list[dict]) -> pd.DataFrame:
    """Create a minimal unified holdings DataFrame."""
    cols = [
        "cik", "report_date", "issuer_name", "fair_value",
        "interest_rate", "pik_rate", "index_classification",
        "source", "asset_category",
    ]
    df = pd.DataFrame(rows)
    for c in cols:
        if c not in df.columns:
            df[c] = None
    return df


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestFeeUplift:
    def test_basic_uplift(self):
        """Fee uplift = income yield - coupon yield."""
        # Fund earns $10M on $100M portfolio = 10% annualized yield
        # Median coupon = 8%
        # Uplift = 2%
        fund_income = _make_fund_income([{
            "cik": "100",
            "report_quarter": "2024q1",
            "duration_months": "3",
            "total_investment_income": "2500000",  # $2.5M quarterly
        }])
        unified = _make_unified([
            {
                "cik": "100", "report_date": "2024-03-31",
                "issuer_name": "Loan A", "fair_value": "50000000",
                "interest_rate": "8", "pik_rate": None,
                "index_classification": "DIRECT_LENDING",
            },
            {
                "cik": "100", "report_date": "2024-03-31",
                "issuer_name": "Loan B", "fair_value": "50000000",
                "interest_rate": "8", "pik_rate": None,
                "index_classification": "DIRECT_LENDING",
            },
        ])

        result = compute_fee_uplift(fund_income_df=fund_income,
                                     unified_df=unified)
        assert len(result) == 1
        row = result.iloc[0]
        # Income yield: 2.5M * 4 / 100M * 100 = 10%
        assert abs(row["total_income_yield"] - 10.0) < 0.5
        # Coupon median = 8%
        assert abs(row["median_all_in_coupon"] - 8.0) < 0.5
        # Uplift ~ 2%
        assert abs(row["effective_uplift"] - 2.0) < 0.5

    def test_zero_uplift(self):
        """When income yield equals coupon yield, uplift is 0."""
        fund_income = _make_fund_income([{
            "cik": "100",
            "report_quarter": "2024q1",
            "duration_months": "3",
            "total_investment_income": "2000000",
        }])
        unified = _make_unified([{
            "cik": "100", "report_date": "2024-03-31",
            "issuer_name": "Loan A", "fair_value": "100000000",
            "interest_rate": "8", "pik_rate": None,
            "index_classification": "DIRECT_LENDING",
        }])

        result = compute_fee_uplift(fund_income_df=fund_income,
                                     unified_df=unified)
        assert len(result) == 1
        # Income yield: 2M * 4 / 100M * 100 = 8%
        # Coupon = 8%, uplift = 0
        assert abs(result.iloc[0]["effective_uplift"]) < 0.5

    def test_cap_at_max_uplift(self):
        """Uplift exceeding MAX_UPLIFT_PCT uses cross-sectional median."""
        # One CIK with huge uplift, one with normal
        fund_income = _make_fund_income([
            {
                "cik": "100", "report_quarter": "2024q1",
                "duration_months": "3",
                "total_investment_income": "10000000",  # $10M on $10M = crazy
            },
            {
                "cik": "200", "report_quarter": "2024q1",
                "duration_months": "3",
                "total_investment_income": "2500000",  # $2.5M on $100M = normal
            },
        ])
        unified = _make_unified([
            {
                "cik": "100", "report_date": "2024-03-31",
                "issuer_name": "Loan X", "fair_value": "10000000",
                "interest_rate": "10", "pik_rate": None,
                "index_classification": "DIRECT_LENDING",
            },
            {
                "cik": "200", "report_date": "2024-03-31",
                "issuer_name": "Loan Y", "fair_value": "100000000",
                "interest_rate": "8", "pik_rate": None,
                "index_classification": "DIRECT_LENDING",
            },
        ])

        result = compute_fee_uplift(fund_income_df=fund_income,
                                     unified_df=unified)
        cik100 = result[result["cik"] == "100"]
        assert len(cik100) == 1
        # CIK 100: income yield = 10M*4/10M*100 = 400%, uplift = 390%
        # Exceeds MAX_UPLIFT_PCT -> falls back to cross-sectional median
        assert cik100.iloc[0]["effective_uplift"] <= MAX_UPLIFT_PCT

    def test_negative_uplift_uses_cross_sectional(self):
        """Negative uplift (income < coupon) uses cross-sectional median."""
        fund_income = _make_fund_income([
            {
                "cik": "100", "report_quarter": "2024q1",
                "duration_months": "3",
                "total_investment_income": "500000",  # Very low income
            },
            {
                "cik": "200", "report_quarter": "2024q1",
                "duration_months": "3",
                "total_investment_income": "3000000",
            },
        ])
        unified = _make_unified([
            {
                "cik": "100", "report_date": "2024-03-31",
                "issuer_name": "Loan A", "fair_value": "100000000",
                "interest_rate": "10", "pik_rate": None,
                "index_classification": "DIRECT_LENDING",
            },
            {
                "cik": "200", "report_date": "2024-03-31",
                "issuer_name": "Loan B", "fair_value": "100000000",
                "interest_rate": "8", "pik_rate": None,
                "index_classification": "DIRECT_LENDING",
            },
        ])

        result = compute_fee_uplift(fund_income_df=fund_income,
                                     unified_df=unified)
        cik100 = result[result["cik"] == "100"]
        assert len(cik100) == 1
        # CIK 100: income yield = 0.5M*4/100M*100 = 2%, coupon = 10%
        # Uplift = -8% -> negative -> uses cross-sectional
        assert cik100.iloc[0]["effective_uplift"] >= 0

    def test_empty_fund_income(self):
        """Empty fund income -> empty result."""
        result = compute_fee_uplift(
            fund_income_df=pd.DataFrame(),
            unified_df=pd.DataFrame(),
        )
        assert len(result) == 0
        assert "effective_uplift" in result.columns

    def test_output_schema(self):
        """Output contains all expected columns."""
        fund_income = _make_fund_income([{
            "cik": "100", "report_quarter": "2024q1",
            "duration_months": "3",
            "total_investment_income": "2500000",
        }])
        unified = _make_unified([{
            "cik": "100", "report_date": "2024-03-31",
            "issuer_name": "Loan A", "fair_value": "100000000",
            "interest_rate": "8", "pik_rate": None,
            "index_classification": "DIRECT_LENDING",
        }])

        result = compute_fee_uplift(fund_income_df=fund_income,
                                     unified_df=unified)
        expected_cols = {
            "cik", "quarter", "total_income_yield",
            "median_all_in_coupon", "fee_uplift_pct",
            "cross_sectional_median_uplift", "effective_uplift",
        }
        assert expected_cols.issubset(set(result.columns))

    def test_pik_included_in_coupon_median(self):
        """PIK rate is added to coupon when computing median_all_in_coupon."""
        fund_income = _make_fund_income([{
            "cik": "100", "report_quarter": "2024q1",
            "duration_months": "3",
            "total_investment_income": "3000000",
        }])
        unified = _make_unified([{
            "cik": "100", "report_date": "2024-03-31",
            "issuer_name": "Loan A", "fair_value": "100000000",
            "interest_rate": "8", "pik_rate": "2",
            "index_classification": "DIRECT_LENDING",
        }])

        result = compute_fee_uplift(fund_income_df=fund_income,
                                     unified_df=unified)
        assert len(result) == 1
        # Coupon median should be 8+2=10, not just 8
        assert abs(result.iloc[0]["median_all_in_coupon"] - 10.0) < 0.5

    def test_multiple_quarters(self):
        """Uplift computed independently per quarter."""
        fund_income = _make_fund_income([
            {"cik": "100", "report_quarter": "2024q1",
             "duration_months": "3", "total_investment_income": "2500000"},
            {"cik": "100", "report_quarter": "2024q2",
             "duration_months": "3", "total_investment_income": "2700000"},
        ])
        unified = _make_unified([
            {"cik": "100", "report_date": "2024-03-31",
             "issuer_name": "Loan A", "fair_value": "100000000",
             "interest_rate": "8", "index_classification": "DIRECT_LENDING"},
            {"cik": "100", "report_date": "2024-06-30",
             "issuer_name": "Loan A", "fair_value": "100000000",
             "interest_rate": "8", "index_classification": "DIRECT_LENDING"},
        ])

        result = compute_fee_uplift(fund_income_df=fund_income,
                                     unified_df=unified)
        assert len(result) == 2
        quarters = sorted(result["quarter"].tolist())
        assert quarters == ["2024q1", "2024q2"]

    def test_total_fv_includes_all_positions(self):
        """Total FV denominator includes all positions; coupon median is DL-only."""
        fund_income = _make_fund_income([{
            "cik": "100", "report_quarter": "2024q1",
            "duration_months": "3",
            "total_investment_income": "2500000",
        }])
        unified = _make_unified([
            {
                "cik": "100", "report_date": "2024-03-31",
                "issuer_name": "Loan A", "fair_value": "100000000",
                "interest_rate": "8",
                "index_classification": "DIRECT_LENDING",
            },
            {
                "cik": "100", "report_date": "2024-03-31",
                "issuer_name": "Equity B", "fair_value": "50000000",
                "interest_rate": None,
                "index_classification": "DIRECT_EQUITY",
            },
        ])

        result = compute_fee_uplift(fund_income_df=fund_income,
                                     unified_df=unified)
        assert len(result) == 1
        # Total FV = $150M (DL $100M + Equity $50M), NOT just DL
        # Income yield = 2.5M*4/150M*100 = 6.67%
        assert abs(result.iloc[0]["total_income_yield"] - 6.67) < 0.5
        # Coupon median is DL-only = 8%
        assert abs(result.iloc[0]["median_all_in_coupon"] - 8.0) < 0.5
