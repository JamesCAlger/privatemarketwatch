"""Tests for pipeline.sec_ticker_map."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from pipeline.sec_ticker_map import (
    build_bdc_ticker_map,
    download_sec_tickers,
    load_sec_tickers,
    parse_sec_tickers,
)


# -- Fixtures ----------------------------------------------------------------

SAMPLE_SEC_JSON = {
    "0": {"cik_str": 1287032, "ticker": "PSEC", "title": "PROSPECT CAPITAL CORP"},
    "1": {"cik_str": 1418076, "ticker": "SLRC", "title": "SLR INVESTMENT CORP"},
    "2": {"cik_str": 789019, "ticker": "MSFT", "title": "MICROSOFT CORP"},
    "3": {"cik_str": 1280784, "ticker": "HTGC", "title": "HERCULES CAPITAL INC"},
}


# -- Tests -------------------------------------------------------------------

class TestParseSecTickers:
    def test_parses_entries(self):
        df = parse_sec_tickers(SAMPLE_SEC_JSON)
        assert len(df) == 4
        assert list(df.columns) == ["cik", "ticker", "entity_name"]

    def test_cik_zero_padding(self):
        df = parse_sec_tickers(SAMPLE_SEC_JSON)
        # CIK 789019 should become 0000789019
        msft = df[df["ticker"] == "MSFT"]
        assert len(msft) == 1
        assert msft.iloc[0]["cik"] == "0000789019"

    def test_10_digit_padding(self):
        df = parse_sec_tickers(SAMPLE_SEC_JSON)
        for _, row in df.iterrows():
            assert len(row["cik"]) == 10
            assert row["cik"].isdigit()

    def test_ticker_uppercased(self):
        raw = {"0": {"cik_str": 123, "ticker": "abc", "title": "Test"}}
        df = parse_sec_tickers(raw)
        assert df.iloc[0]["ticker"] == "ABC"

    def test_empty_input(self):
        df = parse_sec_tickers({})
        assert df.empty
        assert list(df.columns) == ["cik", "ticker", "entity_name"]

    def test_missing_ticker_skipped(self):
        raw = {"0": {"cik_str": 123, "ticker": "", "title": "No Ticker"}}
        df = parse_sec_tickers(raw)
        assert df.empty


class TestDownloadSecTickers:
    def test_download_and_cache(self, tmp_path):
        mock_client = MagicMock()
        mock_client.get_json.return_value = SAMPLE_SEC_JSON
        cache_file = tmp_path / "company_tickers.json"

        with patch("pipeline.sec_ticker_map.SEC_COMPANY_TICKERS_FILE", cache_file):
            result = download_sec_tickers(mock_client)

        assert result == SAMPLE_SEC_JSON
        assert cache_file.exists()
        with open(cache_file) as f:
            cached = json.load(f)
        assert cached == SAMPLE_SEC_JSON
        mock_client.get_json.assert_called_once()


class TestLoadSecTickers:
    def test_load_from_cache(self, tmp_path):
        cache_file = tmp_path / "company_tickers.json"
        with open(cache_file, "w") as f:
            json.dump(SAMPLE_SEC_JSON, f)

        with patch("pipeline.sec_ticker_map.SEC_COMPANY_TICKERS_FILE", cache_file):
            result = load_sec_tickers()

        assert result == SAMPLE_SEC_JSON

    def test_missing_cache_returns_empty(self, tmp_path):
        cache_file = tmp_path / "nonexistent.json"
        with patch("pipeline.sec_ticker_map.SEC_COMPANY_TICKERS_FILE", cache_file):
            result = load_sec_tickers()
        assert result == {}


class TestBuildBdcTickerMap:
    def test_cross_references_universe(self, tmp_path):
        """Only BDC CIKs from the universe should appear in the result."""
        # Create a fake BDC universe with 2 of the 4 SEC entries
        bdc_universe = pd.DataFrame({
            "cik": ["0001287032", "0001280784"],
            "entity_name": ["Prospect Capital", "Hercules Capital"],
        })
        universe_file = tmp_path / "bdc_universe.csv"
        bdc_universe.to_csv(universe_file, index=False)

        cache_file = tmp_path / "company_tickers.json"
        with open(cache_file, "w") as f:
            json.dump(SAMPLE_SEC_JSON, f)

        with (
            patch("pipeline.sec_ticker_map.BDC_UNIVERSE_FILE", universe_file),
            patch("pipeline.sec_ticker_map.SEC_COMPANY_TICKERS_FILE", cache_file),
        ):
            result = build_bdc_ticker_map()

        assert len(result) == 2
        tickers = set(result["ticker"])
        assert "PSEC" in tickers
        assert "HTGC" in tickers
        assert "MSFT" not in tickers  # Not a BDC

    def test_no_universe_returns_empty(self, tmp_path):
        cache_file = tmp_path / "company_tickers.json"
        with open(cache_file, "w") as f:
            json.dump(SAMPLE_SEC_JSON, f)

        with (
            patch("pipeline.sec_ticker_map.BDC_UNIVERSE_FILE", tmp_path / "nope.csv"),
            patch("pipeline.sec_ticker_map.SEC_COMPANY_TICKERS_FILE", cache_file),
        ):
            result = build_bdc_ticker_map()

        assert result.empty

    def test_no_cache_returns_empty(self, tmp_path):
        universe_file = tmp_path / "bdc_universe.csv"
        pd.DataFrame({"cik": ["0001287032"]}).to_csv(universe_file, index=False)

        with (
            patch("pipeline.sec_ticker_map.BDC_UNIVERSE_FILE", universe_file),
            patch("pipeline.sec_ticker_map.SEC_COMPANY_TICKERS_FILE", tmp_path / "nope.json"),
        ):
            result = build_bdc_ticker_map()

        assert result.empty
