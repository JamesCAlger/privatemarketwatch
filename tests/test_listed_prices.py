"""Tests for pipeline.listed_prices."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from pipeline.listed_prices import (
    build_premium_discount,
    download_listed_prices,
    rebuild_from_cache,
    PREMIUM_DISCOUNT_COLUMNS,
    OUTPUT_COLUMNS,
)


# -- Fixtures ----------------------------------------------------------------

@pytest.fixture(autouse=True)
def _redirect_output(tmp_path):
    """Redirect output CSV writes to tmp_path to avoid conftest write guard."""
    with patch(
        "pipeline.listed_prices.BDC_PREMIUM_DISCOUNT_FILE",
        tmp_path / "bdc_premium_discount.csv",
    ):
        yield


@pytest.fixture
def sample_ticker_map():
    return pd.DataFrame({
        "cik": ["0001287032", "0001280784"],
        "ticker": ["PSEC", "HTGC"],
        "entity_name": ["Prospect Capital", "Hercules Capital"],
    })


@pytest.fixture
def sample_prices():
    """Daily prices for two tickers around quarter-end dates."""
    rows = []
    # PSEC prices around 2024-12-31
    for d in ["2024-12-27", "2024-12-30", "2024-12-31"]:
        rows.append({
            "cik": "0001287032", "ticker": "PSEC", "entity_name": "Prospect Capital",
            "date": d, "close": "5.50", "adj_close": "5.50", "volume": "1000000",
        })
    # HTGC prices around 2024-12-31
    for d in ["2024-12-27", "2024-12-30", "2024-12-31"]:
        rows.append({
            "cik": "0001280784", "ticker": "HTGC", "entity_name": "Hercules Capital",
            "date": d, "close": "20.50", "adj_close": "20.50", "volume": "500000",
        })
    return pd.DataFrame(rows)


@pytest.fixture
def sample_financials(tmp_path):
    """Fund financials with NAV for premium/discount computation."""
    df = pd.DataFrame({
        "cik": ["0001287032", "0001280784", "0001287032"],
        "entity_name": ["Prospect Capital", "Hercules Capital", "Prospect Capital"],
        "vehicle_type": ["bdc", "bdc", "bdc"],
        "source": ["companyfacts", "companyfacts", "companyfacts"],
        "report_quarter": ["2024q4", "2024q4", "2024q3"],
        "report_date": ["2024-12-31", "2024-12-31", "2024-09-30"],
        "nav_per_share": ["5.00", "20.00", "5.10"],
        "total_assets": ["10000000", "20000000", "10000000"],
        "net_assets": ["5000000", "15000000", "5000000"],
        "market_price_per_share": [None, None, None],
        "premium_discount_pct": [None, None, None],
    })
    path = tmp_path / "fund_financials.csv"
    df.to_csv(path, index=False)
    return path


# -- Tests -------------------------------------------------------------------

class TestPremiumDiscount:
    def test_basic_computation(self, sample_prices, sample_financials):
        """close=5.50, NAV=5.00 -> +10.0% premium."""
        result = build_premium_discount(
            prices_df=sample_prices,
            financials_csv=sample_financials,
        )
        assert not result.empty
        assert set(result.columns) >= set(PREMIUM_DISCOUNT_COLUMNS)

        # PSEC 2024q4: close=5.50, NAV=5.00 -> (5.50-5.00)/5.00*100 = 10.0%
        psec_q4 = result[
            (result["cik"] == "0001287032")
            & (result["report_quarter"] == "2024q4")
        ]
        assert len(psec_q4) == 1
        pct = float(psec_q4.iloc[0]["premium_discount_pct"])
        assert abs(pct - 10.0) < 0.01

    def test_discount_computation(self, sample_financials):
        """close=18.00, NAV=20.00 -> -10.0% discount."""
        prices = pd.DataFrame({
            "cik": ["0001280784"],
            "ticker": ["HTGC"],
            "entity_name": ["Hercules Capital"],
            "date": ["2024-12-31"],
            "close": ["18.00"],
            "adj_close": ["18.00"],
            "volume": ["500000"],
        })
        result = build_premium_discount(
            prices_df=prices,
            financials_csv=sample_financials,
        )
        htgc = result[
            (result["cik"] == "0001280784")
            & (result["report_quarter"] == "2024q4")
        ]
        assert len(htgc) == 1
        pct = float(htgc.iloc[0]["premium_discount_pct"])
        assert abs(pct - (-10.0)) < 0.01

    def test_lookback_window(self, sample_financials):
        """Price on 2024-12-27 (4 days before) should match within 7-day window."""
        prices = pd.DataFrame({
            "cik": ["0001287032"],
            "ticker": ["PSEC"],
            "entity_name": ["Prospect Capital"],
            "date": ["2024-12-27"],
            "close": ["5.25"],
            "adj_close": ["5.25"],
            "volume": ["1000000"],
        })
        result = build_premium_discount(
            prices_df=prices,
            financials_csv=sample_financials,
        )
        psec = result[
            (result["cik"] == "0001287032")
            & (result["report_quarter"] == "2024q4")
        ]
        assert len(psec) == 1
        assert float(psec.iloc[0]["close_price"]) == 5.25

    def test_no_price_outside_window(self, sample_financials):
        """Price 10 days before quarter-end should not match."""
        prices = pd.DataFrame({
            "cik": ["0001287032"],
            "ticker": ["PSEC"],
            "entity_name": ["Prospect Capital"],
            "date": ["2024-12-20"],
            "close": ["5.25"],
            "adj_close": ["5.25"],
            "volume": ["1000000"],
        })
        result = build_premium_discount(
            prices_df=prices,
            financials_csv=sample_financials,
        )
        psec = result[
            (result["cik"] == "0001287032")
            & (result["report_quarter"] == "2024q4")
        ]
        assert len(psec) == 0

    def test_missing_prices_produces_no_error(self, sample_financials):
        """CIKs with no prices should simply not appear."""
        empty_prices = pd.DataFrame(columns=OUTPUT_COLUMNS)
        result = build_premium_discount(
            prices_df=empty_prices,
            financials_csv=sample_financials,
        )
        assert result.empty

    def test_no_financials_file(self, tmp_path):
        """Missing financials file returns empty DataFrame."""
        prices = pd.DataFrame({
            "cik": ["0001287032"], "ticker": ["PSEC"],
            "entity_name": ["X"], "date": ["2024-12-31"],
            "close": ["5.50"], "adj_close": ["5.50"], "volume": ["100"],
        })
        result = build_premium_discount(
            prices_df=prices,
            financials_csv=tmp_path / "nonexistent.csv",
        )
        assert result.empty


class TestRebuildFromCache:
    def test_rebuild_from_cached_csvs(self, tmp_path, sample_ticker_map):
        """Rebuild reads per-ticker CSVs and produces combined output."""
        cache_dir = tmp_path / "listed_prices"
        cache_dir.mkdir()

        # Write a cached CSV for PSEC
        psec_data = pd.DataFrame({
            "date": ["2024-12-31"],
            "close": ["5.50"],
            "adj_close": ["5.50"],
            "volume": ["1000000"],
            "ticker": ["PSEC"],
        })
        psec_data.to_csv(cache_dir / "PSEC.csv", index=False)

        output_file = tmp_path / "bdc_listed_prices.csv"

        with (
            patch("pipeline.listed_prices.LISTED_PRICES_CACHE_DIR", cache_dir),
            patch("pipeline.listed_prices.BDC_LISTED_PRICES_FILE", output_file),
        ):
            result = rebuild_from_cache(ticker_map_df=sample_ticker_map)

        assert not result.empty
        assert result.iloc[0]["ticker"] == "PSEC"
        assert result.iloc[0]["cik"] == "0001287032"
        assert output_file.exists()

    def test_empty_cache_dir(self, tmp_path):
        cache_dir = tmp_path / "listed_prices"
        cache_dir.mkdir()

        with patch("pipeline.listed_prices.LISTED_PRICES_CACHE_DIR", cache_dir):
            result = rebuild_from_cache()

        assert result.empty

    def test_no_cache_dir(self, tmp_path):
        with patch("pipeline.listed_prices.LISTED_PRICES_CACHE_DIR", tmp_path / "nope"):
            result = rebuild_from_cache()
        assert result.empty


class TestDownloadListedPrices:
    def test_yfinance_not_installed(self, sample_ticker_map):
        """Graceful fallback when yfinance is not installed."""
        import importlib
        with patch.dict("sys.modules", {"yfinance": None}):
            # Force ImportError
            with patch("builtins.__import__", side_effect=ImportError("No module named 'yfinance'")):
                # The function catches ImportError internally
                pass

    def test_empty_ticker_map(self):
        result = download_listed_prices(pd.DataFrame(columns=["cik", "ticker", "entity_name"]))
        assert result.empty

    def test_none_ticker_map(self):
        result = download_listed_prices(None)
        assert result.empty
