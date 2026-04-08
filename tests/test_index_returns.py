"""Tests for pipeline.index_returns module.

Covers:
- Direct Lending: capital + income return
- Direct Equity: capital return only
- Fund vehicles: capital + distribution
- Span adjustment (multi-quarter -> quarterly equivalent)
- Outlier guards (>200%, <-99%)
- Index aggregation (FV-weighted, equal-weighted)
- Minimum constituent threshold
- Chain-linking across two quarters
- Empty and edge-case inputs
"""

import pandas as pd
import pytest

from pipeline.index_returns import (
    MAX_RETURN,
    MIN_BEGIN_FV,
    MIN_CONSTITUENTS,
    MIN_RETURN,
    compute_returns,
)
from pipeline.position_matching import MATCH_COLUMNS


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

# Empty DataFrames to prevent tests from loading real data from disk
_EMPTY_FEE_UPLIFT = pd.DataFrame(columns=["cik", "quarter", "effective_uplift"])
_EMPTY_PIK = pd.DataFrame(columns=["cik", "report_date", "issuer_name", "pik_rate"])


def _make_matches(rows: list[dict]) -> pd.DataFrame:
    """Create a minimal matched pairs DataFrame."""
    df = pd.DataFrame(rows)
    for c in MATCH_COLUMNS:
        if c not in df.columns:
            df[c] = None
    return df


def _compute(matches_df, **kwargs):
    """Wrapper around compute_returns that defaults to empty auxiliary data."""
    kwargs.setdefault("fee_uplift_df", _EMPTY_FEE_UPLIFT)
    kwargs.setdefault("unified_pik_df", _EMPTY_PIK)
    return compute_returns(matches_df=matches_df, **kwargs)


# ---------------------------------------------------------------------------
# Return calculation
# ---------------------------------------------------------------------------

class TestReturnCalculation:
    def test_direct_lending_capital_plus_income(self):
        """Direct Lending: total_return = capital + income."""
        matches = _make_matches([{
            "cik": "100", "entity_name": "BDC1", "source": "bdc",
            "index_classification": "DIRECT_LENDING",
            "begin_quarter": "2024q1", "end_quarter": "2024q2",
            "begin_report_date": "2024-03-31", "end_report_date": "2024-06-30",
            "begin_issuer_name": "Acme Corp", "end_issuer_name": "Acme Corp",
            "begin_fair_value": "1000000", "end_fair_value": "1010000",
            "begin_cost": "950000", "end_cost": "950000",
            "begin_principal_amount": "1000000",
            "begin_interest_rate": "10",  # 10% annual
            "begin_basis_spread": "5.0",
            "span_months": "3",
            "match_method": "A_within_filing",
            "asset_category": "LOAN_FIRST_LIEN",
        }])
        pos, idx = _compute(matches)
        assert len(pos) == 1
        row = pos.iloc[0]
        # Capital: (1,010,000 - 1,000,000) / 1,000,000 = 0.01
        assert abs(row["capital_return"] - 0.01) < 0.001
        # Income: (1,000,000 * 10 / 100 * 3/12) / 1,000,000 = 0.025
        assert abs(row["income_return"] - 0.025) < 0.001
        # Total: 0.01 + 0.025 = 0.035
        assert abs(row["total_return"] - 0.035) < 0.001

    def test_direct_equity_capital_only(self):
        """Direct Equity: no income component."""
        matches = _make_matches([{
            "cik": "100", "entity_name": "BDC1", "source": "bdc",
            "index_classification": "DIRECT_EQUITY",
            "begin_quarter": "2024q1", "end_quarter": "2024q2",
            "begin_report_date": "2024-03-31", "end_report_date": "2024-06-30",
            "begin_issuer_name": "Startup Inc", "end_issuer_name": "Startup Inc",
            "begin_fair_value": "500000", "end_fair_value": "550000",
            "begin_cost": "400000", "end_cost": "400000",
            "span_months": "3",
            "match_method": "B5_exact_identifier",
            "asset_category": "EQUITY_COMMON",
        }])
        pos, _ = _compute(matches)
        row = pos.iloc[0]
        # Capital: (550k - 500k) / 500k = 0.10
        assert abs(row["capital_return"] - 0.10) < 0.001
        # Income: 0
        assert row["income_return"] == 0
        assert abs(row["total_return"] - 0.10) < 0.001

    def test_fund_vehicle_distribution(self):
        """Fund vehicles: distribution = max(0, begin_cost - end_cost)."""
        matches = _make_matches([{
            "cik": "100", "entity_name": "BDC1", "source": "bdc",
            "index_classification": "PRIVATE_CREDIT_FUND",
            "begin_quarter": "2024q1", "end_quarter": "2024q2",
            "begin_report_date": "2024-03-31", "end_report_date": "2024-06-30",
            "begin_issuer_name": "Credit Fund LP", "end_issuer_name": "Credit Fund LP",
            "begin_fair_value": "1000000", "end_fair_value": "980000",
            "begin_cost": "900000", "end_cost": "850000",
            "span_months": "3",
            "match_method": "C1_normalized_name",
            "asset_category": "FUND",
        }])
        pos, _ = _compute(matches)
        row = pos.iloc[0]
        # Capital: (980k - 1M) / 1M = -0.02
        assert abs(row["capital_return"] - (-0.02)) < 0.001
        # Income/distribution: max(0, 900k - 850k) / 1M = 0.05
        assert abs(row["income_return"] - 0.05) < 0.001
        # Total: -0.02 + 0.05 = 0.03
        assert abs(row["total_return"] - 0.03) < 0.001

    def test_span_adjustment_12_to_quarterly(self):
        """12-month span should be converted to quarterly equivalent."""
        matches = _make_matches([{
            "cik": "100", "entity_name": "BDC1", "source": "bdc",
            "index_classification": "DIRECT_LENDING",
            "begin_quarter": "2023q4", "end_quarter": "2024q4",
            "begin_report_date": "2023-12-31", "end_report_date": "2024-12-31",
            "begin_issuer_name": "Acme", "end_issuer_name": "Acme",
            "begin_fair_value": "1000000", "end_fair_value": "1050000",
            "begin_cost": "1000000", "end_cost": "1000000",
            "begin_principal_amount": "1000000",
            "begin_interest_rate": "8",
            "span_months": "12",
            "match_method": "A_within_filing",
            "asset_category": "LOAN_FIRST_LIEN",
        }])
        pos, _ = _compute(matches)
        row = pos.iloc[0]
        assert row["span_adjusted"] == True
        # Total return over 12m = capital + income
        # Capital: (1.05M - 1M) / 1M = 0.05
        # Income: (1M * 8/100 * 12/12) / 1M = 0.08 (full year's coupon)
        # Total: 0.05 + 0.08 = 0.13
        # quarterly_return = (1 + 0.13)^(3/12) - 1 = (1.13)^0.25 - 1
        expected_quarterly = (1 + row["total_return"]) ** (3.0 / 12.0) - 1
        assert abs(row["quarterly_total_return"] - expected_quarterly) < 0.0001
        # Verify income is full year's coupon (not just one quarter)
        assert abs(row["income_return"] - 0.08) < 0.001
        assert abs(row["total_return"] - 0.13) < 0.001

    def test_income_scales_with_span_6m(self):
        """6-month span should accrue 2 quarters of income."""
        matches = _make_matches([{
            "cik": "100", "entity_name": "BDC1", "source": "bdc",
            "index_classification": "DIRECT_LENDING",
            "begin_quarter": "2024q1", "end_quarter": "2024q3",
            "begin_report_date": "2024-03-31", "end_report_date": "2024-09-30",
            "begin_issuer_name": "Acme", "end_issuer_name": "Acme",
            "begin_fair_value": "1000000", "end_fair_value": "1000000",
            "begin_cost": "1000000", "end_cost": "1000000",
            "begin_principal_amount": "1000000",
            "begin_interest_rate": "12",  # 12% annual
            "span_months": "6",
            "match_method": "A_within_filing",
            "asset_category": "LOAN_FIRST_LIEN",
        }])
        pos, _ = _compute(matches)
        row = pos.iloc[0]
        # Income: 1M * 12/100 * 6/12 / 1M = 0.06 (half year's coupon)
        assert abs(row["income_return"] - 0.06) < 0.001
        # Capital: 0 (FV unchanged)
        assert abs(row["capital_return"]) < 0.001
        # Total: 0.06, quarterly: (1.06)^(3/6) - 1
        expected_qtr = (1 + 0.06) ** 0.5 - 1
        assert abs(row["quarterly_total_return"] - expected_qtr) < 0.001

    def test_outlier_above_200pct(self):
        """Returns above 200% should be set to NULL."""
        matches = _make_matches([{
            "cik": "100", "entity_name": "BDC1", "source": "bdc",
            "index_classification": "DIRECT_EQUITY",
            "begin_quarter": "2024q1", "end_quarter": "2024q2",
            "begin_report_date": "2024-03-31", "end_report_date": "2024-06-30",
            "begin_issuer_name": "Moonshot", "end_issuer_name": "Moonshot",
            "begin_fair_value": "100000", "end_fair_value": "500000",
            "begin_cost": "100000", "end_cost": "100000",
            "span_months": "3",
            "match_method": "B5_exact_identifier",
            "asset_category": "EQUITY_COMMON",
        }])
        pos, _ = _compute(matches)
        row = pos.iloc[0]
        # Capital: 400% > 200%, so quarterly_total_return should be NULL
        assert row["total_return"] > MAX_RETURN
        assert pd.isna(row["quarterly_total_return"])

    def test_outlier_below_minus_99pct(self):
        """Returns below -99% should be capped."""
        matches = _make_matches([{
            "cik": "100", "entity_name": "BDC1", "source": "bdc",
            "index_classification": "DIRECT_EQUITY",
            "begin_quarter": "2024q1", "end_quarter": "2024q2",
            "begin_report_date": "2024-03-31", "end_report_date": "2024-06-30",
            "begin_issuer_name": "Bankrupt Co", "end_issuer_name": "Bankrupt Co",
            "begin_fair_value": "1000000", "end_fair_value": "1000",
            "begin_cost": "1000000", "end_cost": "1000000",
            "begin_shares_held": "10000", "end_shares_held": "10000",
            "span_months": "3",
            "match_method": "B5_exact_identifier",
            "asset_category": "EQUITY_COMMON",
        }])
        pos, _ = _compute(matches)
        row = pos.iloc[0]
        # Per-share: begin = 1M/10k = 100, end = 1000/10k = 0.1
        # price_return = (0.1 - 100) / 100 = -0.999, below -0.99
        assert row["quarterly_total_return"] == MIN_RETURN


# ---------------------------------------------------------------------------
# Index aggregation
# ---------------------------------------------------------------------------

class TestIndexAggregation:
    def _make_n_matches(self, n: int, index_class: str = "DIRECT_LENDING",
                        quarter: str = "2024q2") -> pd.DataFrame:
        """Create n matched pairs for aggregation tests."""
        rows = []
        for i in range(n):
            rows.append({
                "cik": str(100 + i), "entity_name": f"BDC{i}",
                "source": "bdc",
                "index_classification": index_class,
                "begin_quarter": "2024q1", "end_quarter": quarter,
                "begin_report_date": "2024-03-31",
                "end_report_date": "2024-06-30",
                "begin_issuer_name": f"Company{i}",
                "end_issuer_name": f"Company{i}",
                "begin_fair_value": str(1000000 + i * 10000),
                "end_fair_value": str(1010000 + i * 10000),
                "begin_cost": str(950000 + i * 10000),
                "end_cost": str(950000 + i * 10000),
                "begin_principal_amount": str(1000000 + i * 10000),
                "begin_interest_rate": "8",
                "span_months": "3",
                "match_method": "A_within_filing",
                "asset_category": "LOAN_FIRST_LIEN",
            })
        return _make_matches(rows)

    def test_fv_weighted_return(self):
        """FV-weighted return computed correctly."""
        matches = self._make_n_matches(15)
        pos, idx = _compute(matches)
        dl = idx[idx["index_classification"] == "DIRECT_LENDING"]
        assert len(dl) == 1
        # All positions have similar returns, so FV-weighted should be close to average
        assert dl.iloc[0]["fv_weighted_return"] > 0
        assert dl.iloc[0]["constituent_count"] == 15

    def test_minimum_constituent_threshold(self):
        """Index not produced with fewer than MIN_CONSTITUENTS."""
        matches = self._make_n_matches(5)  # Below threshold
        _, idx = _compute(matches)
        dl = idx[idx["index_classification"] == "DIRECT_LENDING"]
        assert len(dl) == 0  # Filtered out

    def test_chain_linking_two_quarters(self):
        """Chain-linked index level across two quarters."""
        rows = []
        for i in range(15):
            # Q1 -> Q2
            rows.append({
                "cik": str(100 + i), "entity_name": f"BDC{i}",
                "source": "bdc",
                "index_classification": "DIRECT_LENDING",
                "begin_quarter": "2024q1", "end_quarter": "2024q2",
                "begin_report_date": "2024-03-31",
                "end_report_date": "2024-06-30",
                "begin_issuer_name": f"Co{i}",
                "end_issuer_name": f"Co{i}",
                "begin_fair_value": "1000000",
                "end_fair_value": "1010000",
                "begin_cost": "1000000", "end_cost": "1000000",
                "begin_principal_amount": "1000000",
                "begin_interest_rate": "8",
                "span_months": "3",
                "match_method": "A_within_filing",
                "asset_category": "LOAN_FIRST_LIEN",
            })
            # Q2 -> Q3
            rows.append({
                "cik": str(100 + i), "entity_name": f"BDC{i}",
                "source": "bdc",
                "index_classification": "DIRECT_LENDING",
                "begin_quarter": "2024q2", "end_quarter": "2024q3",
                "begin_report_date": "2024-06-30",
                "end_report_date": "2024-09-30",
                "begin_issuer_name": f"Co{i}",
                "end_issuer_name": f"Co{i}",
                "begin_fair_value": "1010000",
                "end_fair_value": "1020000",
                "begin_cost": "1000000", "end_cost": "1000000",
                "begin_principal_amount": "1010000",
                "begin_interest_rate": "8",
                "span_months": "3",
                "match_method": "A_within_filing",
                "asset_category": "LOAN_FIRST_LIEN",
            })
        matches = _make_matches(rows)
        _, idx = _compute(matches)
        dl = idx[idx["index_classification"] == "DIRECT_LENDING"]
        assert len(dl) == 2  # Two quarters
        # Chain-linked: second index level should be > first
        levels = dl.sort_values("quarter")["index_level_fv"].tolist()
        assert levels[0] > 100  # First quarter above base
        assert levels[1] > levels[0]  # Growing


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_empty_matches(self):
        """Empty input -> empty output."""
        pos, idx = _compute(pd.DataFrame(columns=MATCH_COLUMNS))
        assert len(pos) == 0
        assert len(idx) == 0

    def test_match_score_passthrough(self):
        """match_score from position matching appears in position returns output."""
        matches = _make_matches([{
            "cik": "100", "entity_name": "BDC1", "source": "bdc",
            "index_classification": "DIRECT_LENDING",
            "begin_quarter": "2024q1", "end_quarter": "2024q2",
            "begin_report_date": "2024-03-31", "end_report_date": "2024-06-30",
            "begin_issuer_name": "Score Co", "end_issuer_name": "Score Co",
            "begin_fair_value": "1000000", "end_fair_value": "1010000",
            "begin_cost": "950000", "end_cost": "950000",
            "begin_principal_amount": "1000000",
            "begin_interest_rate": "10",
            "span_months": "3",
            "match_method": "D_fuzzy",
            "match_score": "0.92",
            "asset_category": "LOAN_FIRST_LIEN",
        }])
        pos, _ = _compute(matches)
        assert len(pos) == 1
        assert "match_score" in pos.columns
        assert abs(float(pos.iloc[0]["match_score"]) - 0.92) < 0.001

    def test_missing_interest_rate(self):
        """Position with NULL interest_rate -> income_return = 0 for lending."""
        matches = _make_matches([{
            "cik": "100", "entity_name": "BDC1", "source": "bdc",
            "index_classification": "DIRECT_LENDING",
            "begin_quarter": "2024q1", "end_quarter": "2024q2",
            "begin_report_date": "2024-03-31", "end_report_date": "2024-06-30",
            "begin_issuer_name": "NoRate Co", "end_issuer_name": "NoRate Co",
            "begin_fair_value": "1000000", "end_fair_value": "1010000",
            "begin_cost": "950000", "end_cost": "950000",
            "begin_principal_amount": "1000000",
            "begin_interest_rate": None,
            "span_months": "3",
            "match_method": "A_within_filing",
            "asset_category": "LOAN_FIRST_LIEN",
        }])
        pos, _ = _compute(matches)
        row = pos.iloc[0]
        assert row["income_return"] == 0  # COALESCE(NULL, 0)
        assert abs(row["total_return"] - 0.01) < 0.001  # Capital only


# ---------------------------------------------------------------------------
# Per-unit price return (DIRECT_LENDING)
# ---------------------------------------------------------------------------

class TestPerUnitPriceReturn:
    def test_amortizing_loan_at_par(self):
        """Loan amortizes from $10M to $8M at par: price return = 0."""
        matches = _make_matches([{
            "cik": "100", "entity_name": "BDC1", "source": "bdc",
            "index_classification": "DIRECT_LENDING",
            "begin_quarter": "2024q1", "end_quarter": "2024q2",
            "begin_report_date": "2024-03-31", "end_report_date": "2024-06-30",
            "begin_issuer_name": "Amort Co", "end_issuer_name": "Amort Co",
            "begin_fair_value": "10000000", "end_fair_value": "8000000",
            "begin_cost": "10000000", "end_cost": "8000000",
            "begin_principal_amount": "10000000",
            "end_principal_amount": "8000000",
            "begin_interest_rate": "10",
            "span_months": "3",
            "match_method": "A_within_filing",
            "asset_category": "LOAN_FIRST_LIEN",
        }])
        pos, _ = _compute(matches)
        row = pos.iloc[0]
        # begin_price = 10M/10M = 1.0, end_price = 8M/8M = 1.0
        # price_return = (1.0 - 1.0) / 1.0 = 0
        assert abs(row["capital_return"]) < 0.001
        # Income: 10M * 10/100 * 3/12 / 10M = 0.025
        assert abs(row["income_return"] - 0.025) < 0.001
        # Total = income only
        assert abs(row["total_return"] - 0.025) < 0.001

    def test_additional_draw_at_par(self):
        """Fund increases position from $5M to $8M at par: price return = 0."""
        matches = _make_matches([{
            "cik": "100", "entity_name": "BDC1", "source": "bdc",
            "index_classification": "DIRECT_LENDING",
            "begin_quarter": "2024q1", "end_quarter": "2024q2",
            "begin_report_date": "2024-03-31", "end_report_date": "2024-06-30",
            "begin_issuer_name": "DrawCo", "end_issuer_name": "DrawCo",
            "begin_fair_value": "5000000", "end_fair_value": "8000000",
            "begin_cost": "5000000", "end_cost": "8000000",
            "begin_principal_amount": "5000000",
            "end_principal_amount": "8000000",
            "begin_interest_rate": "8",
            "span_months": "3",
            "match_method": "A_within_filing",
            "asset_category": "LOAN_FIRST_LIEN",
        }])
        pos, _ = _compute(matches)
        row = pos.iloc[0]
        # begin_price = 5M/5M = 1.0, end_price = 8M/8M = 1.0
        assert abs(row["capital_return"]) < 0.001

    def test_price_decline_with_amortization(self):
        """Price drops from par to 0.95 while principal amortizes."""
        matches = _make_matches([{
            "cik": "100", "entity_name": "BDC1", "source": "bdc",
            "index_classification": "DIRECT_LENDING",
            "begin_quarter": "2024q1", "end_quarter": "2024q2",
            "begin_report_date": "2024-03-31", "end_report_date": "2024-06-30",
            "begin_issuer_name": "Stressed Co", "end_issuer_name": "Stressed Co",
            "begin_fair_value": "9800000", "end_fair_value": "7600000",
            "begin_cost": "10000000", "end_cost": "8000000",
            "begin_principal_amount": "10000000",
            "end_principal_amount": "8000000",
            "begin_interest_rate": "10",
            "span_months": "3",
            "match_method": "A_within_filing",
            "asset_category": "LOAN_FIRST_LIEN",
        }])
        pos, _ = _compute(matches)
        row = pos.iloc[0]
        # begin_price = 9.8M/10M = 0.98, end_price = 7.6M/8M = 0.95
        # price_return = (0.95 - 0.98) / 0.98 = -0.030612...
        expected_price_return = (0.95 - 0.98) / 0.98
        assert abs(row["capital_return"] - expected_price_return) < 0.001

    def test_fallback_missing_end_principal(self):
        """Missing end_principal_amount falls back to raw FV change."""
        matches = _make_matches([{
            "cik": "100", "entity_name": "BDC1", "source": "bdc",
            "index_classification": "DIRECT_LENDING",
            "begin_quarter": "2024q1", "end_quarter": "2024q2",
            "begin_report_date": "2024-03-31", "end_report_date": "2024-06-30",
            "begin_issuer_name": "NoPrincipal Co", "end_issuer_name": "NoPrincipal Co",
            "begin_fair_value": "1000000", "end_fair_value": "900000",
            "begin_cost": "1000000", "end_cost": "1000000",
            "begin_principal_amount": "1000000",
            "end_principal_amount": None,
            "begin_interest_rate": "10",
            "span_months": "3",
            "match_method": "B2_exact_name",
            "asset_category": "LOAN_FIRST_LIEN",
        }])
        pos, _ = _compute(matches)
        row = pos.iloc[0]
        # Fallback: (900k - 1M) / 1M = -0.10
        assert abs(row["capital_return"] - (-0.10)) < 0.001

    def test_equity_stable_cost_uses_raw_fv(self):
        """DE with stable cost (no shares): raw FV change is correct."""
        matches = _make_matches([{
            "cik": "100", "entity_name": "BDC1", "source": "bdc",
            "index_classification": "DIRECT_EQUITY",
            "begin_quarter": "2024q1", "end_quarter": "2024q2",
            "begin_report_date": "2024-03-31", "end_report_date": "2024-06-30",
            "begin_issuer_name": "Equity Co", "end_issuer_name": "Equity Co",
            "begin_fair_value": "1000000", "end_fair_value": "1100000",
            "begin_cost": "800000", "end_cost": "800000",
            "span_months": "3",
            "match_method": "B2_exact_name",
            "asset_category": "EQUITY_COMMON",
        }])
        pos, _ = _compute(matches)
        row = pos.iloc[0]
        # FV/cost: begin = 1M/800k = 1.25, end = 1.1M/800k = 1.375
        # price_return = (1.375 - 1.25) / 1.25 = 0.10
        # Same as raw FV change when cost is stable
        assert abs(row["capital_return"] - 0.10) < 0.001

    def test_equity_share_sale_per_share_price(self):
        """DE partial sale: shares drop 50%, FV drops 50%, price return = 0."""
        matches = _make_matches([{
            "cik": "100", "entity_name": "BDC1", "source": "bdc",
            "index_classification": "DIRECT_EQUITY",
            "begin_quarter": "2024q1", "end_quarter": "2024q2",
            "begin_report_date": "2024-03-31", "end_report_date": "2024-06-30",
            "begin_issuer_name": "SaleCo", "end_issuer_name": "SaleCo",
            "begin_fair_value": "2000000", "end_fair_value": "1000000",
            "begin_cost": "1600000", "end_cost": "800000",
            "begin_shares_held": "100000", "end_shares_held": "50000",
            "span_months": "3",
            "match_method": "B2_exact_name",
            "asset_category": "EQUITY_COMMON",
        }])
        pos, _ = _compute(matches)
        row = pos.iloc[0]
        # begin_price = 2M/100k = 20, end_price = 1M/50k = 20
        assert abs(row["capital_return"]) < 0.001

    def test_equity_share_purchase_with_appreciation(self):
        """DE additional purchase + price increase: isolates price change."""
        matches = _make_matches([{
            "cik": "100", "entity_name": "BDC1", "source": "bdc",
            "index_classification": "DIRECT_EQUITY",
            "begin_quarter": "2024q1", "end_quarter": "2024q2",
            "begin_report_date": "2024-03-31", "end_report_date": "2024-06-30",
            "begin_issuer_name": "GrowthCo", "end_issuer_name": "GrowthCo",
            "begin_fair_value": "1000000", "end_fair_value": "2200000",
            "begin_cost": "500000", "end_cost": "1000000",
            "begin_shares_held": "10000", "end_shares_held": "20000",
            "span_months": "3",
            "match_method": "A_within_filing",
            "asset_category": "EQUITY_COMMON",
        }])
        pos, _ = _compute(matches)
        row = pos.iloc[0]
        # begin_price = 1M/10k = 100, end_price = 2.2M/20k = 110
        # price_return = (110 - 100) / 100 = 0.10
        assert abs(row["capital_return"] - 0.10) < 0.001

    def test_equity_cost_ratio_no_shares(self):
        """DE with cost change but no shares: uses FV/cost as price proxy."""
        matches = _make_matches([{
            "cik": "100", "entity_name": "BDC1", "source": "bdc",
            "index_classification": "DIRECT_EQUITY",
            "begin_quarter": "2024q1", "end_quarter": "2024q2",
            "begin_report_date": "2024-03-31", "end_report_date": "2024-06-30",
            "begin_issuer_name": "CostCo", "end_issuer_name": "CostCo",
            "begin_fair_value": "1500000", "end_fair_value": "750000",
            "begin_cost": "1000000", "end_cost": "500000",
            "span_months": "3",
            "match_method": "B2_exact_name",
            "asset_category": "EQUITY_COMMON",
        }])
        pos, _ = _compute(matches)
        row = pos.iloc[0]
        # begin_price = 1.5M/1M = 1.5, end_price = 750k/500k = 1.5
        # price_return = 0 (proportional sale, no mark change)
        assert abs(row["capital_return"]) < 0.001

    def test_equity_cost_ratio_with_mark_change(self):
        """DE cost halves but FV drops less: positive price return."""
        matches = _make_matches([{
            "cik": "100", "entity_name": "BDC1", "source": "bdc",
            "index_classification": "DIRECT_EQUITY",
            "begin_quarter": "2024q1", "end_quarter": "2024q2",
            "begin_report_date": "2024-03-31", "end_report_date": "2024-06-30",
            "begin_issuer_name": "MarkUpCo", "end_issuer_name": "MarkUpCo",
            "begin_fair_value": "1000000", "end_fair_value": "600000",
            "begin_cost": "800000", "end_cost": "400000",
            "span_months": "3",
            "match_method": "B2_exact_name",
            "asset_category": "EQUITY_COMMON",
        }])
        pos, _ = _compute(matches)
        row = pos.iloc[0]
        # begin_price = 1M/800k = 1.25, end_price = 600k/400k = 1.5
        # price_return = (1.5 - 1.25) / 1.25 = 0.20
        assert abs(row["capital_return"] - 0.20) < 0.001

    def test_equity_no_data_falls_back_to_raw_fv(self):
        """DE with no shares and no cost: raw FV fallback."""
        matches = _make_matches([{
            "cik": "100", "entity_name": "BDC1", "source": "bdc",
            "index_classification": "DIRECT_EQUITY",
            "begin_quarter": "2024q1", "end_quarter": "2024q2",
            "begin_report_date": "2024-03-31", "end_report_date": "2024-06-30",
            "begin_issuer_name": "NoCostCo", "end_issuer_name": "NoCostCo",
            "begin_fair_value": "1000000", "end_fair_value": "900000",
            "span_months": "3",
            "match_method": "B2_exact_name",
            "asset_category": "EQUITY_COMMON",
        }])
        pos, _ = _compute(matches)
        row = pos.iloc[0]
        # Fallback: (900k - 1M) / 1M = -0.10
        assert abs(row["capital_return"] - (-0.10)) < 0.001

    def test_equity_shares_preferred_over_cost(self):
        """When both shares and cost available, shares path is used."""
        matches = _make_matches([{
            "cik": "100", "entity_name": "BDC1", "source": "bdc",
            "index_classification": "DIRECT_EQUITY",
            "begin_quarter": "2024q1", "end_quarter": "2024q2",
            "begin_report_date": "2024-03-31", "end_report_date": "2024-06-30",
            "begin_issuer_name": "BothCo", "end_issuer_name": "BothCo",
            "begin_fair_value": "1000000", "end_fair_value": "550000",
            "begin_cost": "800000", "end_cost": "400000",
            "begin_shares_held": "10000", "end_shares_held": "5000",
            "span_months": "3",
            "match_method": "A_within_filing",
            "asset_category": "EQUITY_COMMON",
        }])
        pos, _ = _compute(matches)
        row = pos.iloc[0]
        # Shares path: begin = 1M/10k = 100, end = 550k/5k = 110
        # price_return = (110 - 100) / 100 = 0.10
        # Cost path would give: begin = 1M/800k = 1.25, end = 550k/400k = 1.375
        # price_return = (1.375 - 1.25) / 1.25 = 0.10 (same here, but different by construction)
        assert abs(row["capital_return"] - 0.10) < 0.001

    def test_equity_shares_ratio_guard_jump_10x(self):
        """DE with 10x shares jump falls back to raw FV, not per-unit."""
        matches = _make_matches([{
            "cik": "100", "entity_name": "BDC1", "source": "bdc",
            "index_classification": "DIRECT_EQUITY",
            "begin_quarter": "2024q1", "end_quarter": "2024q2",
            "begin_report_date": "2024-03-31", "end_report_date": "2024-06-30",
            "begin_issuer_name": "UnitMismatch Co",
            "end_issuer_name": "UnitMismatch Co",
            "begin_fair_value": "1000000", "end_fair_value": "1050000",
            "begin_shares_held": "1000", "end_shares_held": "10000",
            "span_months": "3",
            "match_method": "B2_exact_name",
            "asset_category": "EQUITY_COMMON",
        }])
        pos, _ = _compute(matches)
        row = pos.iloc[0]
        # Per-unit would give: (1.05M/10k - 1M/1k) / (1M/1k) = (105 - 1000)/1000 = -89.5%
        # Raw FV fallback: (1.05M - 1M) / 1M = +5%
        assert abs(row["capital_return"] - 0.05) < 0.001

    def test_equity_shares_ratio_guard_drop_1000x(self):
        """DE with 1000x shares drop falls back to raw FV."""
        matches = _make_matches([{
            "cik": "100", "entity_name": "BDC1", "source": "bdc",
            "index_classification": "DIRECT_EQUITY",
            "begin_quarter": "2024q1", "end_quarter": "2024q2",
            "begin_report_date": "2024-03-31", "end_report_date": "2024-06-30",
            "begin_issuer_name": "InverseMismatch",
            "end_issuer_name": "InverseMismatch",
            "begin_fair_value": "500000", "end_fair_value": "480000",
            "begin_shares_held": "500000", "end_shares_held": "500",
            "span_months": "3",
            "match_method": "B2_exact_name",
            "asset_category": "EQUITY_COMMON",
        }])
        pos, _ = _compute(matches)
        row = pos.iloc[0]
        # Raw FV: (480k - 500k) / 500k = -0.04
        assert abs(row["capital_return"] - (-0.04)) < 0.001

    def test_equity_shares_ratio_guard_skips_cost_fallback(self):
        """DE with >5x shares jump skips cost-based fallback too."""
        matches = _make_matches([{
            "cik": "100", "entity_name": "BDC1", "source": "bdc",
            "index_classification": "DIRECT_EQUITY",
            "begin_quarter": "2024q1", "end_quarter": "2024q2",
            "begin_report_date": "2024-03-31", "end_report_date": "2024-06-30",
            "begin_issuer_name": "CostScaledCo",
            "end_issuer_name": "CostScaledCo",
            "begin_fair_value": "1000000", "end_fair_value": "1020000",
            "begin_cost": "900000", "end_cost": "9000000",
            "begin_shares_held": "1000", "end_shares_held": "10000",
            "span_months": "3",
            "match_method": "B2_exact_name",
            "asset_category": "EQUITY_COMMON",
        }])
        pos, _ = _compute(matches)
        row = pos.iloc[0]
        # Shares guard triggers (10x), cost guard also triggers (shares >5x)
        # Falls through to raw FV: (1.02M - 1M) / 1M = +2%
        assert abs(row["capital_return"] - 0.02) < 0.001

    def test_equity_shares_ratio_within_5x_uses_per_unit(self):
        """DE with shares change within 5x still uses per-unit return."""
        matches = _make_matches([{
            "cik": "100", "entity_name": "BDC1", "source": "bdc",
            "index_classification": "DIRECT_EQUITY",
            "begin_quarter": "2024q1", "end_quarter": "2024q2",
            "begin_report_date": "2024-03-31", "end_report_date": "2024-06-30",
            "begin_issuer_name": "DoubleCo", "end_issuer_name": "DoubleCo",
            "begin_fair_value": "1000000", "end_fair_value": "2200000",
            "begin_shares_held": "10000", "end_shares_held": "20000",
            "span_months": "3",
            "match_method": "B2_exact_name",
            "asset_category": "EQUITY_COMMON",
        }])
        pos, _ = _compute(matches)
        row = pos.iloc[0]
        # Per-unit: begin = 1M/10k = 100, end = 2.2M/20k = 110
        # price_return = (110 - 100) / 100 = 0.10
        assert abs(row["capital_return"] - 0.10) < 0.001

    def test_equity_cost_fallback_when_no_shares(self):
        """DE cost-based fallback still works when shares are absent."""
        matches = _make_matches([{
            "cik": "100", "entity_name": "BDC1", "source": "bdc",
            "index_classification": "DIRECT_EQUITY",
            "begin_quarter": "2024q1", "end_quarter": "2024q2",
            "begin_report_date": "2024-03-31", "end_report_date": "2024-06-30",
            "begin_issuer_name": "NoSharesCo",
            "end_issuer_name": "NoSharesCo",
            "begin_fair_value": "1000000", "end_fair_value": "600000",
            "begin_cost": "800000", "end_cost": "400000",
            "span_months": "3",
            "match_method": "B2_exact_name",
            "asset_category": "EQUITY_COMMON",
        }])
        pos, _ = _compute(matches)
        row = pos.iloc[0]
        # Cost path: begin = 1M/800k = 1.25, end = 600k/400k = 1.5
        # price_return = (1.5 - 1.25) / 1.25 = 0.20
        assert abs(row["capital_return"] - 0.20) < 0.001

    def test_sofr_imputation_from_peers(self):
        """Positions with spread-only get income via imputed SOFR from peers."""
        # Two positions in same quarter: one with rate+spread (donor),
        # one with spread-only (recipient)
        matches = _make_matches([
            {   # Donor: has both rate and spread -> implied SOFR = 10 - 5 = 5
                "cik": "100", "entity_name": "BDC1", "source": "bdc",
                "index_classification": "DIRECT_LENDING",
                "begin_quarter": "2024q1", "end_quarter": "2024q2",
                "begin_report_date": "2024-03-31", "end_report_date": "2024-06-30",
                "begin_issuer_name": "Donor Co", "end_issuer_name": "Donor Co",
                "begin_fair_value": "1000000", "end_fair_value": "1000000",
                "begin_cost": "1000000", "end_cost": "1000000",
                "begin_principal_amount": "1000000",
                "begin_interest_rate": "10",
                "begin_basis_spread": "5.0",
                "span_months": "3",
                "match_method": "A_within_filing",
                "asset_category": "LOAN_FIRST_LIEN",
            },
            {   # Recipient: spread only, no interest_rate
                "cik": "200", "entity_name": "BDC2", "source": "bdc",
                "index_classification": "DIRECT_LENDING",
                "begin_quarter": "2024q1", "end_quarter": "2024q2",
                "begin_report_date": "2024-03-31", "end_report_date": "2024-06-30",
                "begin_issuer_name": "NoRate Co", "end_issuer_name": "NoRate Co",
                "begin_fair_value": "1000000", "end_fair_value": "1000000",
                "begin_cost": "1000000", "end_cost": "1000000",
                "begin_principal_amount": "1000000",
                "begin_interest_rate": None,
                "begin_basis_spread": "6.0",
                "span_months": "3",
                "match_method": "B2_exact_name",
                "asset_category": "LOAN_FIRST_LIEN",
            },
        ])
        pos, _ = _compute(matches)
        donor = pos[pos["issuer_name"] == "Donor Co"].iloc[0]
        recip = pos[pos["issuer_name"] == "NoRate Co"].iloc[0]
        # Donor: effective_rate = 10 (from interest_rate directly)
        assert abs(donor["income_rate"] - 10.0) < 0.01
        # Recipient: effective_rate = 6.0 + 5.0 (SOFR) = 11.0
        assert abs(recip["income_rate"] - 11.0) < 0.01
        # Recipient income: 1M * 11/100 * 3/12 / 1M = 0.0275
        assert abs(recip["income_return"] - 0.0275) < 0.001

    def test_sofr_imputation_no_donors(self):
        """With no donors in the quarter, spread-only positions get no income."""
        matches = _make_matches([{
            "cik": "200", "entity_name": "BDC2", "source": "bdc",
            "index_classification": "DIRECT_LENDING",
            "begin_quarter": "2024q1", "end_quarter": "2024q2",
            "begin_report_date": "2024-03-31", "end_report_date": "2024-06-30",
            "begin_issuer_name": "Orphan Co", "end_issuer_name": "Orphan Co",
            "begin_fair_value": "1000000", "end_fair_value": "1000000",
            "begin_cost": "1000000", "end_cost": "1000000",
            "begin_principal_amount": "1000000",
            "begin_interest_rate": None,
            "begin_basis_spread": "6.0",
            "span_months": "3",
            "match_method": "B2_exact_name",
            "asset_category": "LOAN_FIRST_LIEN",
        }])
        pos, _ = _compute(matches)
        row = pos.iloc[0]
        # No donors -> SOFR is NULL -> effective_rate is NULL -> income = 0
        assert row["income_return"] == 0

    def test_sofr_imputation_output_columns(self):
        """income_rate column appears in output."""
        matches = _make_matches([{
            "cik": "100", "entity_name": "BDC1", "source": "bdc",
            "index_classification": "DIRECT_LENDING",
            "begin_quarter": "2024q1", "end_quarter": "2024q2",
            "begin_report_date": "2024-03-31", "end_report_date": "2024-06-30",
            "begin_issuer_name": "Col Co", "end_issuer_name": "Col Co",
            "begin_fair_value": "1000000", "end_fair_value": "1000000",
            "begin_cost": "1000000", "end_cost": "1000000",
            "begin_principal_amount": "1000000",
            "begin_interest_rate": "8",
            "span_months": "3",
            "match_method": "A_within_filing",
            "asset_category": "LOAN_FIRST_LIEN",
        }])
        pos, _ = _compute(matches)
        assert "income_rate" in pos.columns

    def test_filer_median_imputation_from_same_cik(self):
        """Positions with neither rate nor spread get income from same-filer median."""
        # Same CIK: two rated positions and one with no rate/spread
        matches = _make_matches([
            {   # Rated position 1: rate = 10
                "cik": "100", "entity_name": "BDC1", "source": "bdc",
                "index_classification": "DIRECT_LENDING",
                "begin_quarter": "2024q1", "end_quarter": "2024q2",
                "begin_report_date": "2024-03-31", "end_report_date": "2024-06-30",
                "begin_issuer_name": "Rated A", "end_issuer_name": "Rated A",
                "begin_fair_value": "1000000", "end_fair_value": "1000000",
                "begin_cost": "1000000", "end_cost": "1000000",
                "begin_principal_amount": "1000000",
                "begin_interest_rate": "10",
                "begin_basis_spread": "5.0",
                "span_months": "3",
                "match_method": "A_within_filing",
                "asset_category": "LOAN_FIRST_LIEN",
            },
            {   # Rated position 2: rate = 12
                "cik": "100", "entity_name": "BDC1", "source": "bdc",
                "index_classification": "DIRECT_LENDING",
                "begin_quarter": "2024q1", "end_quarter": "2024q2",
                "begin_report_date": "2024-03-31", "end_report_date": "2024-06-30",
                "begin_issuer_name": "Rated B", "end_issuer_name": "Rated B",
                "begin_fair_value": "1000000", "end_fair_value": "1000000",
                "begin_cost": "1000000", "end_cost": "1000000",
                "begin_principal_amount": "1000000",
                "begin_interest_rate": "12",
                "begin_basis_spread": "7.0",
                "span_months": "3",
                "match_method": "A_within_filing",
                "asset_category": "LOAN_FIRST_LIEN",
            },
            {   # No rate, no spread -- should get filer median = 11
                "cik": "100", "entity_name": "BDC1", "source": "bdc",
                "index_classification": "DIRECT_LENDING",
                "begin_quarter": "2024q1", "end_quarter": "2024q2",
                "begin_report_date": "2024-03-31", "end_report_date": "2024-06-30",
                "begin_issuer_name": "Blind Co", "end_issuer_name": "Blind Co",
                "begin_fair_value": "1000000", "end_fair_value": "1000000",
                "begin_cost": "1000000", "end_cost": "1000000",
                "begin_principal_amount": "1000000",
                "begin_interest_rate": None,
                "begin_basis_spread": None,
                "span_months": "3",
                "match_method": "A_within_filing",
                "asset_category": "LOAN_FIRST_LIEN",
            },
        ])
        pos, _ = _compute(matches)
        blind = pos[pos["issuer_name"] == "Blind Co"].iloc[0]
        # Filer median of 10 and 12 = 11
        assert abs(blind["income_rate"] - 11.0) < 0.01
        # Income: 1M * 11/100 * 3/12 / 1M = 0.0275
        assert abs(blind["income_return"] - 0.0275) < 0.001

    def test_filer_median_not_applied_cross_cik(self):
        """Filer median only applies within the same CIK, not across filers."""
        matches = _make_matches([
            {   # CIK 100: has rate
                "cik": "100", "entity_name": "BDC1", "source": "bdc",
                "index_classification": "DIRECT_LENDING",
                "begin_quarter": "2024q1", "end_quarter": "2024q2",
                "begin_report_date": "2024-03-31", "end_report_date": "2024-06-30",
                "begin_issuer_name": "Rated Co", "end_issuer_name": "Rated Co",
                "begin_fair_value": "1000000", "end_fair_value": "1000000",
                "begin_cost": "1000000", "end_cost": "1000000",
                "begin_principal_amount": "1000000",
                "begin_interest_rate": "10",
                "begin_basis_spread": "5.0",
                "span_months": "3",
                "match_method": "A_within_filing",
                "asset_category": "LOAN_FIRST_LIEN",
            },
            {   # CIK 200: no rate, no spread, different CIK -- no filer median
                "cik": "200", "entity_name": "BDC2", "source": "bdc",
                "index_classification": "DIRECT_LENDING",
                "begin_quarter": "2024q1", "end_quarter": "2024q2",
                "begin_report_date": "2024-03-31", "end_report_date": "2024-06-30",
                "begin_issuer_name": "Orphan Co", "end_issuer_name": "Orphan Co",
                "begin_fair_value": "1000000", "end_fair_value": "1000000",
                "begin_cost": "1000000", "end_cost": "1000000",
                "begin_principal_amount": "1000000",
                "begin_interest_rate": None,
                "begin_basis_spread": None,
                "span_months": "3",
                "match_method": "B2_exact_name",
                "asset_category": "LOAN_FIRST_LIEN",
            },
        ])
        pos, _ = _compute(matches)
        orphan = pos[pos["issuer_name"] == "Orphan Co"].iloc[0]
        # CIK 200 has no rated positions -> no filer median -> income = 0
        assert orphan["income_return"] == 0

    def test_filer_median_tier3_after_sofr_tier2(self):
        """SOFR imputation (tier 2) takes priority; filer median is tier 3."""
        matches = _make_matches([
            {   # Donor: rate=10, spread=5 -> SOFR=5
                "cik": "100", "entity_name": "BDC1", "source": "bdc",
                "index_classification": "DIRECT_LENDING",
                "begin_quarter": "2024q1", "end_quarter": "2024q2",
                "begin_report_date": "2024-03-31", "end_report_date": "2024-06-30",
                "begin_issuer_name": "Donor Co", "end_issuer_name": "Donor Co",
                "begin_fair_value": "1000000", "end_fair_value": "1000000",
                "begin_cost": "1000000", "end_cost": "1000000",
                "begin_principal_amount": "1000000",
                "begin_interest_rate": "10",
                "begin_basis_spread": "5.0",
                "span_months": "3",
                "match_method": "A_within_filing",
                "asset_category": "LOAN_FIRST_LIEN",
            },
            {   # Spread-only: should get SOFR tier (spread=6 + SOFR=5 = 11)
                "cik": "100", "entity_name": "BDC1", "source": "bdc",
                "index_classification": "DIRECT_LENDING",
                "begin_quarter": "2024q1", "end_quarter": "2024q2",
                "begin_report_date": "2024-03-31", "end_report_date": "2024-06-30",
                "begin_issuer_name": "Spread Co", "end_issuer_name": "Spread Co",
                "begin_fair_value": "1000000", "end_fair_value": "1000000",
                "begin_cost": "1000000", "end_cost": "1000000",
                "begin_principal_amount": "1000000",
                "begin_interest_rate": None,
                "begin_basis_spread": "6.0",
                "span_months": "3",
                "match_method": "A_within_filing",
                "asset_category": "LOAN_FIRST_LIEN",
            },
        ])
        pos, _ = _compute(matches)
        spread = pos[pos["issuer_name"] == "Spread Co"].iloc[0]
        # Should use SOFR tier (spread + SOFR = 6 + 5 = 11), NOT filer median (10)
        assert abs(spread["income_rate"] - 11.0) < 0.01

    def test_begin_basis_spread_in_output(self):
        """begin_basis_spread column appears in position returns output."""
        matches = _make_matches([{
            "cik": "100", "entity_name": "BDC1", "source": "bdc",
            "index_classification": "DIRECT_LENDING",
            "begin_quarter": "2024q1", "end_quarter": "2024q2",
            "begin_report_date": "2024-03-31", "end_report_date": "2024-06-30",
            "begin_issuer_name": "BBS Co", "end_issuer_name": "BBS Co",
            "begin_fair_value": "1000000", "end_fair_value": "1000000",
            "begin_cost": "1000000", "end_cost": "1000000",
            "begin_principal_amount": "1000000",
            "begin_interest_rate": "8",
            "begin_basis_spread": "3.0",
            "span_months": "3",
            "match_method": "A_within_filing",
            "asset_category": "LOAN_FIRST_LIEN",
        }])
        pos, _ = _compute(matches)
        assert "begin_basis_spread" in pos.columns
        assert abs(float(pos.iloc[0]["begin_basis_spread"]) - 3.0) < 0.01

    def test_end_principal_in_output(self):
        """end_principal_amount appears in position returns output."""
        matches = _make_matches([{
            "cik": "100", "entity_name": "BDC1", "source": "bdc",
            "index_classification": "DIRECT_LENDING",
            "begin_quarter": "2024q1", "end_quarter": "2024q2",
            "begin_report_date": "2024-03-31", "end_report_date": "2024-06-30",
            "begin_issuer_name": "Output Co", "end_issuer_name": "Output Co",
            "begin_fair_value": "1000000", "end_fair_value": "900000",
            "begin_cost": "1000000", "end_cost": "900000",
            "begin_principal_amount": "1000000",
            "end_principal_amount": "900000",
            "begin_interest_rate": "8",
            "span_months": "3",
            "match_method": "A_within_filing",
            "asset_category": "LOAN_FIRST_LIEN",
        }])
        pos, _ = _compute(matches)
        assert "end_principal_amount" in pos.columns
        assert abs(float(pos.iloc[0]["end_principal_amount"]) - 900000) < 1


# ---------------------------------------------------------------------------
# PIK rate integration
# ---------------------------------------------------------------------------

class TestPIKRate:
    def test_pik_rate_pct_in_output(self):
        """pik_rate_pct column appears in position returns output."""
        matches = _make_matches([{
            "cik": "100", "entity_name": "BDC1", "source": "bdc",
            "index_classification": "DIRECT_LENDING",
            "begin_quarter": "2024q1", "end_quarter": "2024q2",
            "begin_report_date": "2024-03-31", "end_report_date": "2024-06-30",
            "begin_issuer_name": "PIK Co", "end_issuer_name": "PIK Co",
            "begin_fair_value": "1000000", "end_fair_value": "1000000",
            "begin_cost": "1000000", "end_cost": "1000000",
            "begin_principal_amount": "1000000",
            "begin_interest_rate": "8",
            "span_months": "3",
            "match_method": "A_within_filing",
            "asset_category": "LOAN_FIRST_LIEN",
        }])
        pos, _ = _compute(matches)
        assert "pik_rate_pct" in pos.columns

    def test_pik_zero_when_not_present(self):
        """Without PIK data, pik_rate_pct defaults to 0."""
        matches = _make_matches([{
            "cik": "100", "entity_name": "BDC1", "source": "bdc",
            "index_classification": "DIRECT_LENDING",
            "begin_quarter": "2024q1", "end_quarter": "2024q2",
            "begin_report_date": "2024-03-31", "end_report_date": "2024-06-30",
            "begin_issuer_name": "NoPIK Co", "end_issuer_name": "NoPIK Co",
            "begin_fair_value": "1000000", "end_fair_value": "1000000",
            "begin_cost": "1000000", "end_cost": "1000000",
            "begin_principal_amount": "1000000",
            "begin_interest_rate": "10",
            "span_months": "3",
            "match_method": "A_within_filing",
            "asset_category": "LOAN_FIRST_LIEN",
        }])
        pos, _ = _compute(matches)
        assert pos.iloc[0]["pik_rate_pct"] == 0


# ---------------------------------------------------------------------------
# Fee uplift integration
# ---------------------------------------------------------------------------

class TestFeeUplift:
    def test_fee_uplift_pct_in_output(self):
        """fee_uplift_pct column appears in position returns output."""
        matches = _make_matches([{
            "cik": "100", "entity_name": "BDC1", "source": "bdc",
            "index_classification": "DIRECT_LENDING",
            "begin_quarter": "2024q1", "end_quarter": "2024q2",
            "begin_report_date": "2024-03-31", "end_report_date": "2024-06-30",
            "begin_issuer_name": "FeeTest Co", "end_issuer_name": "FeeTest Co",
            "begin_fair_value": "1000000", "end_fair_value": "1000000",
            "begin_cost": "1000000", "end_cost": "1000000",
            "begin_principal_amount": "1000000",
            "begin_interest_rate": "8",
            "span_months": "3",
            "match_method": "A_within_filing",
            "asset_category": "LOAN_FIRST_LIEN",
        }])
        pos, _ = _compute(matches)
        assert "fee_uplift_pct" in pos.columns

    def test_no_uplift_data_graceful(self):
        """Without fee uplift data, fee_uplift_pct defaults to 0."""
        matches = _make_matches([{
            "cik": "100", "entity_name": "BDC1", "source": "bdc",
            "index_classification": "DIRECT_LENDING",
            "begin_quarter": "2024q1", "end_quarter": "2024q2",
            "begin_report_date": "2024-03-31", "end_report_date": "2024-06-30",
            "begin_issuer_name": "NoUplift Co", "end_issuer_name": "NoUplift Co",
            "begin_fair_value": "1000000", "end_fair_value": "1000000",
            "begin_cost": "1000000", "end_cost": "1000000",
            "begin_principal_amount": "1000000",
            "begin_interest_rate": "10",
            "span_months": "3",
            "match_method": "A_within_filing",
            "asset_category": "LOAN_FIRST_LIEN",
        }])
        # Pass empty fee_uplift
        empty_uplift = pd.DataFrame(columns=["cik", "quarter", "effective_uplift"])
        pos, _ = _compute(matches, fee_uplift_df=empty_uplift)
        assert pos.iloc[0]["fee_uplift_pct"] == 0
        # Income should be same as without uplift
        assert abs(pos.iloc[0]["income_return"] - 0.025) < 0.001  # 10% * 3/12

    def test_dl_income_with_fee_uplift(self):
        """Fee uplift adds to DL income return."""
        matches = _make_matches([{
            "cik": "100", "entity_name": "BDC1", "source": "bdc",
            "index_classification": "DIRECT_LENDING",
            "begin_quarter": "2024q1", "end_quarter": "2024q2",
            "begin_report_date": "2024-03-31", "end_report_date": "2024-06-30",
            "begin_issuer_name": "Uplift Co", "end_issuer_name": "Uplift Co",
            "begin_fair_value": "1000000", "end_fair_value": "1000000",
            "begin_cost": "1000000", "end_cost": "1000000",
            "begin_principal_amount": "1000000",
            "begin_interest_rate": "10",
            "span_months": "3",
            "match_method": "A_within_filing",
            "asset_category": "LOAN_FIRST_LIEN",
        }])
        uplift = pd.DataFrame([{
            "cik": "100", "quarter": "2024q1", "effective_uplift": "2.0",
        }])
        pos, _ = _compute(matches, fee_uplift_df=uplift)
        row = pos.iloc[0]
        # Income: 1M * (10 + 0 + 2) / 100 * 3/12 / 1M = 0.03
        assert abs(row["income_return"] - 0.03) < 0.001

    def test_uplift_only_for_dl(self):
        """Fee uplift does not affect DIRECT_EQUITY income."""
        matches = _make_matches([{
            "cik": "100", "entity_name": "BDC1", "source": "bdc",
            "index_classification": "DIRECT_EQUITY",
            "begin_quarter": "2024q1", "end_quarter": "2024q2",
            "begin_report_date": "2024-03-31", "end_report_date": "2024-06-30",
            "begin_issuer_name": "Equity Co", "end_issuer_name": "Equity Co",
            "begin_fair_value": "1000000", "end_fair_value": "1100000",
            "begin_cost": "800000", "end_cost": "800000",
            "span_months": "3",
            "match_method": "B2_exact_name",
            "asset_category": "EQUITY_COMMON",
        }])
        uplift = pd.DataFrame([{
            "cik": "100", "quarter": "2024q1", "effective_uplift": "5.0",
        }])
        pos, _ = _compute(matches, fee_uplift_df=uplift)
        row = pos.iloc[0]
        # DE income should still be 0 regardless of uplift
        assert row["income_return"] == 0

    def test_fund_vehicles_unaffected(self):
        """Fee uplift does not affect PRIVATE_CREDIT_FUND income."""
        matches = _make_matches([{
            "cik": "100", "entity_name": "BDC1", "source": "bdc",
            "index_classification": "PRIVATE_CREDIT_FUND",
            "begin_quarter": "2024q1", "end_quarter": "2024q2",
            "begin_report_date": "2024-03-31", "end_report_date": "2024-06-30",
            "begin_issuer_name": "Credit Fund LP",
            "end_issuer_name": "Credit Fund LP",
            "begin_fair_value": "1000000", "end_fair_value": "980000",
            "begin_cost": "900000", "end_cost": "850000",
            "span_months": "3",
            "match_method": "C1_normalized_name",
            "asset_category": "FUND",
        }])
        uplift = pd.DataFrame([{
            "cik": "100", "quarter": "2024q1", "effective_uplift": "5.0",
        }])
        pos, _ = _compute(matches, fee_uplift_df=uplift)
        row = pos.iloc[0]
        # Fund vehicle income = cost distribution, not coupon
        assert abs(row["income_return"] - 0.05) < 0.001  # (900k-850k)/1M
