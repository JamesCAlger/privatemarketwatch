"""Third-party list fetching and parsing for cross-validation.

Sources:
  1. Interval Fund Tracker (intervalfundtracker.com)
  2. Tender Offer Funds (tenderofferfunds.com)
  3. Sure Dividend BDC list (suredividend.com/bdc-list/)
  4. CEFA interval funds (cefa.com)

Each function attempts automated download first, then falls back to
looking for manually-placed files in data/raw/third_party/.
"""

import logging
import re
from pathlib import Path

import pandas as pd

from pipeline.config import (
    CEFA_INTERVAL_URL,
    INTERVAL_FUND_TRACKER_URL,
    SURE_DIVIDEND_BDC_URL,
    TENDER_OFFER_FUNDS_URL,
    THIRD_PARTY_DIR,
)
from pipeline.edgar_client import EdgarClient

logger = logging.getLogger(__name__)


def _try_read_html_tables(html: str, source: str) -> list[pd.DataFrame]:
    """Extract tables from HTML using pandas read_html."""
    try:
        from io import StringIO
        tables = pd.read_html(StringIO(html))
        logger.info("%s: found %d HTML tables", source, len(tables))
        return tables
    except Exception as exc:
        logger.warning("%s: could not parse HTML tables: %s", source, exc)
        return []


def _load_manual_file(name_pattern: str) -> pd.DataFrame | None:
    """Look for a manually-placed file matching *name_pattern* in THIRD_PARTY_DIR."""
    for path in THIRD_PARTY_DIR.iterdir():
        if re.search(name_pattern, path.name, re.IGNORECASE):
            logger.info("Found manual file: %s", path)
            try:
                if path.suffix.lower() in (".xlsx", ".xls"):
                    return pd.read_excel(path, dtype=str)
                elif path.suffix.lower() == ".csv":
                    return pd.read_csv(path, dtype=str)
                else:
                    return pd.read_csv(path, dtype=str, sep="\t")
            except Exception as exc:
                logger.warning("Could not parse %s: %s", path, exc)
    return None


# ──────────────────────────────────────────────────────────────────────
# 1. Interval Fund Tracker
# ──────────────────────────────────────────────────────────────────────

def fetch_interval_fund_tracker(client: EdgarClient) -> pd.DataFrame:
    """Fetch interval fund list from intervalfundtracker.com."""
    logger.info("Fetching Interval Fund Tracker ...")

    # Check for manual file first
    manual = _load_manual_file(r"interval.?fund.?tracker")
    if manual is not None:
        manual.columns = [c.strip().lower().replace(" ", "_") for c in manual.columns]
        manual["source"] = "interval_fund_tracker"
        return manual

    try:
        html = client.get_text(INTERVAL_FUND_TRACKER_URL)
        tables = _try_read_html_tables(html, "IntervalFundTracker")
        if tables:
            # Use the largest table (likely the fund list)
            df = max(tables, key=len)
            df.columns = [str(c).strip().lower().replace(" ", "_") for c in df.columns]
            df["source"] = "interval_fund_tracker"
            logger.info("Interval Fund Tracker: %d funds", len(df))
            return df
    except Exception as exc:
        logger.warning("Could not fetch Interval Fund Tracker: %s", exc)

    logger.info(
        "To use this source, manually download the fund list from %s "
        "and save it as data/raw/third_party/interval_fund_tracker.xlsx",
        INTERVAL_FUND_TRACKER_URL,
    )
    return pd.DataFrame(columns=["fund_name", "ticker", "source"])


# ──────────────────────────────────────────────────────────────────────
# 2. Tender Offer Funds
# ──────────────────────────────────────────────────────────────────────

def fetch_tender_offer_funds(client: EdgarClient) -> pd.DataFrame:
    """Fetch tender offer fund list from tenderofferfunds.com."""
    logger.info("Fetching Tender Offer Funds ...")

    manual = _load_manual_file(r"tender.?offer")
    if manual is not None:
        manual.columns = [c.strip().lower().replace(" ", "_") for c in manual.columns]
        manual["source"] = "tender_offer_funds"
        return manual

    try:
        html = client.get_text(TENDER_OFFER_FUNDS_URL)
        tables = _try_read_html_tables(html, "TenderOfferFunds")
        if tables:
            df = max(tables, key=len)
            df.columns = [str(c).strip().lower().replace(" ", "_") for c in df.columns]
            df["source"] = "tender_offer_funds"
            logger.info("Tender Offer Funds: %d funds", len(df))
            return df
    except Exception as exc:
        logger.warning("Could not fetch Tender Offer Funds: %s", exc)

    logger.info(
        "To use this source, manually download the fund list from %s "
        "and save it as data/raw/third_party/tender_offer_funds.xlsx",
        TENDER_OFFER_FUNDS_URL,
    )
    return pd.DataFrame(columns=["fund_name", "ticker", "source"])


# ──────────────────────────────────────────────────────────────────────
# 3. Sure Dividend BDC List
# ──────────────────────────────────────────────────────────────────────

def fetch_sure_dividend_bdcs(client: EdgarClient) -> pd.DataFrame:
    """Fetch BDC list from suredividend.com."""
    logger.info("Fetching Sure Dividend BDC list ...")

    manual = _load_manual_file(r"sure.?dividend|bdc.?list")
    if manual is not None:
        manual.columns = [c.strip().lower().replace(" ", "_") for c in manual.columns]
        manual["source"] = "sure_dividend"
        return manual

    try:
        html = client.get_text(SURE_DIVIDEND_BDC_URL)
        tables = _try_read_html_tables(html, "SureDividend")
        if tables:
            df = max(tables, key=len)
            df.columns = [str(c).strip().lower().replace(" ", "_") for c in df.columns]
            df["source"] = "sure_dividend"
            logger.info("Sure Dividend BDCs: %d entities", len(df))
            return df
    except Exception as exc:
        logger.warning("Could not fetch Sure Dividend BDC list: %s", exc)

    logger.info(
        "To use this source, manually download the BDC list from %s "
        "and save it as data/raw/third_party/sure_dividend_bdcs.xlsx",
        SURE_DIVIDEND_BDC_URL,
    )
    return pd.DataFrame(columns=["company_name", "ticker", "source"])


# ──────────────────────────────────────────────────────────────────────
# 4. CEFA Interval Funds
# ──────────────────────────────────────────────────────────────────────

def fetch_cefa_interval_funds(client: EdgarClient) -> pd.DataFrame:
    """Fetch interval fund list from CEFA."""
    logger.info("Fetching CEFA interval fund list ...")

    manual = _load_manual_file(r"cefa")
    if manual is not None:
        manual.columns = [c.strip().lower().replace(" ", "_") for c in manual.columns]
        manual["source"] = "cefa"
        return manual

    try:
        html = client.get_text(CEFA_INTERVAL_URL)
        tables = _try_read_html_tables(html, "CEFA")
        if tables:
            df = max(tables, key=len)
            df.columns = [str(c).strip().lower().replace(" ", "_") for c in df.columns]
            df["source"] = "cefa"
            logger.info("CEFA interval funds: %d entities", len(df))
            return df
    except Exception as exc:
        logger.warning("Could not fetch CEFA interval funds: %s", exc)

    logger.info(
        "To use this source, manually download the fund list from %s "
        "and save it as data/raw/third_party/cefa_interval_funds.xlsx",
        CEFA_INTERVAL_URL,
    )
    return pd.DataFrame(columns=["fund_name", "ticker", "source"])


# ──────────────────────────────────────────────────────────────────────
# Public entry point
# ──────────────────────────────────────────────────────────────────────

def fetch_all_third_party_lists(
    client: EdgarClient,
) -> dict[str, pd.DataFrame]:
    """Fetch all third-party lists. Returns a dict keyed by source name."""
    logger.info("=" * 60)
    logger.info("FETCHING THIRD-PARTY LISTS")
    logger.info("=" * 60)

    results: dict[str, pd.DataFrame] = {}

    for name, fetcher in [
        ("interval_fund_tracker", fetch_interval_fund_tracker),
        ("tender_offer_funds", fetch_tender_offer_funds),
        ("sure_dividend", fetch_sure_dividend_bdcs),
        ("cefa", fetch_cefa_interval_funds),
    ]:
        try:
            df = fetcher(client)
            if not df.empty:
                results[name] = df
                logger.info("%s: %d entries", name, len(df))
            else:
                logger.warning("%s: no data retrieved", name)
        except Exception as exc:
            logger.error("%s: failed — %s", name, exc)

    logger.info("Third-party lists retrieved: %d / 4", len(results))
    return results
