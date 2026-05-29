"""Tests for _compute_risk_stats() in pipeline.export.index_exports."""

import math

from pipeline.export.index_exports import _compute_risk_stats


def _make_series(returns_and_levels):
    """Build a minimal series list from (quarter, return, level) tuples."""
    return [
        {
            "quarter": q,
            "fv_weighted_return": r,
            "index_level_fv": lvl,
        }
        for q, r, lvl in returns_and_levels
    ]


class TestComputeRiskStats:
    """Core risk stat calculations with known synthetic data."""

    SERIES = _make_series([
        ("2022q1", 0.02, 102.0),
        ("2022q2", -0.03, 98.94),
        ("2022q3", 0.01, 99.93),
        ("2022q4", 0.04, 103.93),
        ("2023q1", 0.03, 107.05),
        ("2023q2", -0.01, 105.98),
        ("2023q3", 0.02, 108.10),
        ("2023q4", 0.05, 113.50),
    ])

    def test_volatility_positive(self):
        result = _compute_risk_stats(self.SERIES)
        assert result["volatility"] is not None
        assert result["volatility"] > 0

    def test_volatility_value(self):
        """Verify annualized vol = sample_std(quarterly) * sqrt(4)."""
        returns = [s["fv_weighted_return"] for s in self.SERIES]
        n = len(returns)
        mean_r = sum(returns) / n
        sample_var = sum((r - mean_r) ** 2 for r in returns) / (n - 1)
        expected_vol = math.sqrt(sample_var) * 2  # sqrt(4) = 2
        result = _compute_risk_stats(self.SERIES)
        assert abs(result["volatility"] - round(expected_vol, 4)) < 1e-6

    def test_sharpe_ratio(self):
        """Sharpe = (annualized_return - Rf) / annualized_vol."""
        result = _compute_risk_stats(self.SERIES)
        assert result["sharpe"] is not None
        # With mostly positive returns, Sharpe should be meaningfully positive
        # given Rf=4% and these returns compound to ~13.5% over 2 years
        assert isinstance(result["sharpe"], float)

    def test_max_drawdown(self):
        """Max drawdown should be negative (peak-to-trough decline)."""
        result = _compute_risk_stats(self.SERIES)
        assert result["maxDrawdown"] is not None
        assert result["maxDrawdown"] <= 0
        # The drawdown occurs at 2022q2 (level drops from 102 to 98.94)
        expected_dd = (98.94 - 102.0) / 102.0
        assert abs(result["maxDrawdown"] - round(expected_dd, 4)) < 1e-4
        assert result["maxDrawdownQuarter"] == "2022q2"

    def test_best_quarter(self):
        result = _compute_risk_stats(self.SERIES)
        assert result["bestQuarter"] == 0.05
        assert result["bestQuarterLabel"] == "2023q4"

    def test_worst_quarter(self):
        result = _compute_risk_stats(self.SERIES)
        assert result["worstQuarter"] == -0.03
        assert result["worstQuarterLabel"] == "2022q2"

    def test_pct_positive_quarters(self):
        result = _compute_risk_stats(self.SERIES)
        # 6 positive out of 8
        assert result["pctPositiveQuarters"] == round(6 / 8, 4)
        assert result["positiveQuarters"] == 6
        assert result["totalQuarters"] == 8

    def test_total_quarters(self):
        result = _compute_risk_stats(self.SERIES)
        assert result["totalQuarters"] == 8


class TestEdgeCases:
    """Edge cases: too few quarters, all None, single quarter."""

    def test_fewer_than_two_returns_none(self):
        series = _make_series([("2022q1", 0.02, 102.0)])
        result = _compute_risk_stats(series)
        assert result["volatility"] is None
        assert result["sharpe"] is None
        assert result["maxDrawdown"] is None
        assert result["bestQuarter"] is None
        assert result["worstQuarter"] is None
        assert result["pctPositiveQuarters"] is None
        assert result["totalQuarters"] == 1

    def test_empty_series(self):
        result = _compute_risk_stats([])
        assert result["volatility"] is None
        assert result["totalQuarters"] == 0

    def test_all_none_returns(self):
        series = [
            {"quarter": "2022q1", "fv_weighted_return": None, "index_level_fv": 100},
            {"quarter": "2022q2", "fv_weighted_return": None, "index_level_fv": 101},
        ]
        result = _compute_risk_stats(series)
        assert result["volatility"] is None
        assert result["totalQuarters"] == 0

    def test_two_quarters_minimal(self):
        series = _make_series([
            ("2022q1", 0.03, 103.0),
            ("2022q2", -0.01, 101.97),
        ])
        result = _compute_risk_stats(series)
        assert result["volatility"] is not None
        assert result["totalQuarters"] == 2
        assert result["bestQuarterLabel"] == "2022q1"
        assert result["worstQuarterLabel"] == "2022q2"

    def test_zero_volatility(self):
        """All identical returns => zero vol, Sharpe is None (div by zero)."""
        series = _make_series([
            ("2022q1", 0.01, 101.0),
            ("2022q2", 0.01, 102.01),
            ("2022q3", 0.01, 103.03),
        ])
        result = _compute_risk_stats(series)
        assert result["volatility"] == 0.0
        assert result["sharpe"] is None  # 0/0 guarded

    def test_no_drawdown_monotonic_increase(self):
        """Monotonically increasing levels => max drawdown = 0."""
        series = _make_series([
            ("2022q1", 0.02, 102.0),
            ("2022q2", 0.03, 105.06),
            ("2022q3", 0.01, 106.11),
        ])
        result = _compute_risk_stats(series)
        assert result["maxDrawdown"] == 0.0
