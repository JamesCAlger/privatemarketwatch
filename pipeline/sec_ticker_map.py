"""CIK-to-ticker mapping from SEC company_tickers.json.

Downloads and caches the SEC's master CIK/ticker mapping, then
cross-references against the BDC universe to identify publicly-listed BDCs.

Public API
----------
download_sec_tickers(client) -> dict
    Download + cache company_tickers.json via EdgarClient.
load_sec_tickers() -> dict
    Read from cache only (no network).
build_bdc_ticker_map(client=None) -> pd.DataFrame
    Returns [cik, ticker, entity_name] for listed BDCs.
"""

import json
import logging
from typing import Any

import pandas as pd

from pipeline.config import (
    BDC_UNIVERSE_FILE,
    SEC_COMPANY_TICKERS_FILE,
)

logger = logging.getLogger(__name__)

SEC_COMPANY_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"


def download_sec_tickers(client: Any) -> dict:
    """Download SEC company_tickers.json and cache to disk.

    Parameters
    ----------
    client : EdgarClient
        Rate-limited HTTP client for SEC EDGAR.

    Returns
    -------
    dict
        Raw parsed JSON: {"0": {"cik_str": 789019, "ticker": "MSFT", ...}, ...}
    """
    logger.info("Downloading SEC company_tickers.json")
    data = client.get_json(SEC_COMPANY_TICKERS_URL)

    SEC_COMPANY_TICKERS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(SEC_COMPANY_TICKERS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f)
    logger.info(
        "Cached SEC company_tickers.json: %d entries", len(data),
    )
    return data


def load_sec_tickers() -> dict:
    """Load cached company_tickers.json from disk.

    Returns
    -------
    dict
        Raw parsed JSON, or empty dict if cache does not exist.
    """
    if not SEC_COMPANY_TICKERS_FILE.exists():
        logger.warning(
            "No cached company_tickers.json at %s", SEC_COMPANY_TICKERS_FILE,
        )
        return {}
    with open(SEC_COMPANY_TICKERS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def parse_sec_tickers(raw: dict) -> pd.DataFrame:
    """Parse SEC company_tickers.json into a DataFrame.

    Parameters
    ----------
    raw : dict
        Raw JSON from SEC (keyed by sequential index).

    Returns
    -------
    DataFrame with columns [cik, ticker, entity_name].
        cik is zero-padded to 10 digits.
    """
    if not raw:
        return pd.DataFrame(columns=["cik", "ticker", "entity_name"])

    rows = []
    for entry in raw.values():
        cik_str = str(entry.get("cik_str", "")).zfill(10)
        ticker = str(entry.get("ticker", "")).strip().upper()
        title = str(entry.get("title", "")).strip()
        if ticker:
            rows.append({
                "cik": cik_str,
                "ticker": ticker,
                "entity_name": title,
            })

    return pd.DataFrame(rows, columns=["cik", "ticker", "entity_name"])


def build_bdc_ticker_map(client: Any = None) -> pd.DataFrame:
    """Build a ticker map for publicly-listed BDCs.

    Cross-references SEC company_tickers.json against the BDC universe
    to find BDC CIKs that have exchange-listed tickers.

    Parameters
    ----------
    client : EdgarClient, optional
        If provided, downloads fresh company_tickers.json.
        If None, reads from cache only (no network).

    Returns
    -------
    DataFrame with columns [cik, ticker, entity_name] for listed BDCs.
    """
    # Get SEC ticker data
    if client is not None:
        raw = download_sec_tickers(client)
    else:
        raw = load_sec_tickers()

    if not raw:
        logger.warning("No SEC ticker data available")
        return pd.DataFrame(columns=["cik", "ticker", "entity_name"])

    all_tickers = parse_sec_tickers(raw)
    logger.info("SEC ticker map: %d total entries", len(all_tickers))

    # Load BDC universe
    if not BDC_UNIVERSE_FILE.exists():
        logger.warning("No BDC universe file at %s", BDC_UNIVERSE_FILE)
        return pd.DataFrame(columns=["cik", "ticker", "entity_name"])

    bdc_universe = pd.read_csv(BDC_UNIVERSE_FILE, dtype=str)
    bdc_ciks = set(bdc_universe["cik"].str.zfill(10).unique())
    logger.info("BDC universe: %d CIKs", len(bdc_ciks))

    # Cross-reference
    bdc_tickers = all_tickers[all_tickers["cik"].isin(bdc_ciks)].copy()
    bdc_tickers = bdc_tickers.drop_duplicates(subset=["cik"], keep="first")
    bdc_tickers = bdc_tickers.reset_index(drop=True)

    logger.info(
        "Listed BDCs: %d tickers matched from %d BDC CIKs",
        len(bdc_tickers), len(bdc_ciks),
    )

    return bdc_tickers
