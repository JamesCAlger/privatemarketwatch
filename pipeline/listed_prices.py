"""Daily listed price download and premium/discount computation for BDCs.

Downloads daily OHLCV via yfinance for exchange-listed BDCs, caches
per-ticker CSVs, and computes quarter-end premium/discount by joining
close prices against NAV from fund_financials.csv.

Public API
----------
download_listed_prices(ticker_map_df, force_refresh=False) -> pd.DataFrame
    Download via yfinance, cache per-ticker, return combined.
rebuild_from_cache(ticker_map_df=None) -> pd.DataFrame
    Rebuild from cached per-ticker CSVs only (no network).
build_premium_discount(prices_df=None, financials_csv=None) -> pd.DataFrame
    DuckDB join of quarter-end close against NAV.
"""

import logging
import time
from pathlib import Path

import duckdb
import pandas as pd

from pipeline.config import (
    BDC_LISTED_PRICES_FILE,
    BDC_PREMIUM_DISCOUNT_FILE,
    FUND_FINANCIALS_FILE,
    LISTED_PRICES_CACHE_DIR,
)

logger = logging.getLogger(__name__)

OUTPUT_COLUMNS = [
    "cik", "ticker", "entity_name", "date", "close", "adj_close", "volume",
]

PREMIUM_DISCOUNT_COLUMNS = [
    "cik", "ticker", "report_quarter", "report_date",
    "close_price", "nav_per_share", "premium_discount_pct",
]


def download_listed_prices(
    ticker_map_df: pd.DataFrame,
    force_refresh: bool = False,
) -> pd.DataFrame:
    """Download daily prices via yfinance for each BDC ticker.

    Parameters
    ----------
    ticker_map_df : DataFrame
        Output of build_bdc_ticker_map(): [cik, ticker, entity_name].
    force_refresh : bool
        If True, re-download even if cached CSV exists.

    Returns
    -------
    DataFrame with columns [cik, ticker, entity_name, date, close, adj_close, volume].
    """
    try:
        import yfinance as yf
    except ImportError:
        logger.error(
            "yfinance is not installed. "
            "Install with: pip install yfinance"
        )
        return pd.DataFrame(columns=OUTPUT_COLUMNS)

    if ticker_map_df is None or ticker_map_df.empty:
        logger.warning("No ticker map provided; skipping price download")
        return pd.DataFrame(columns=OUTPUT_COLUMNS)

    LISTED_PRICES_CACHE_DIR.mkdir(parents=True, exist_ok=True)

    # Build ticker -> (cik, entity_name) lookup
    ticker_lookup: dict[str, tuple[str, str]] = {}
    for _, row in ticker_map_df.iterrows():
        ticker_lookup[row["ticker"]] = (
            row["cik"], row.get("entity_name", ""),
        )

    all_frames = []
    n_downloaded = 0
    n_cached = 0
    n_failed = 0

    # Collect cached tickers first
    tickers_to_download = []
    for ticker, (cik, entity_name) in ticker_lookup.items():
        cache_path = LISTED_PRICES_CACHE_DIR / f"{ticker}.csv"
        if cache_path.exists() and not force_refresh:
            try:
                df = pd.read_csv(cache_path, dtype=str)
                df["cik"] = cik
                df["entity_name"] = entity_name
                all_frames.append(df)
                n_cached += 1
                continue
            except Exception:
                pass  # Re-download on corrupt cache
        tickers_to_download.append(ticker)

    # Batch download uncached tickers via yf.download()
    if tickers_to_download:
        logger.info(
            "Downloading prices for %d tickers via yf.download()",
            len(tickers_to_download),
        )
        try:
            batch = yf.download(
                tickers_to_download,
                period="max",
                group_by="ticker",
                auto_adjust=False,
                threads=False,
            )
            if batch.empty:
                logger.warning("yf.download() returned empty DataFrame")
                n_failed += len(tickers_to_download)
            else:
                # yf.download with multiple tickers returns MultiIndex columns:
                #   (TICKER, "Close"), (TICKER, "Volume"), etc.
                # With a single ticker it returns flat columns.
                is_multi = isinstance(batch.columns, pd.MultiIndex)

                for ticker in tickers_to_download:
                    cik, entity_name = ticker_lookup[ticker]
                    cache_path = LISTED_PRICES_CACHE_DIR / f"{ticker}.csv"

                    try:
                        if is_multi:
                            if ticker not in batch.columns.get_level_values(0):
                                logger.warning("No data for %s in batch", ticker)
                                n_failed += 1
                                continue
                            hist = batch[ticker].copy()
                        else:
                            # Single ticker: flat columns
                            hist = batch.copy()

                        hist = hist.reset_index()
                        # Normalize column names
                        col_map = {c: c.lower().replace(" ", "_") for c in hist.columns}
                        hist = hist.rename(columns=col_map)

                        # Drop rows where close is NaN
                        if "close" in hist.columns:
                            hist = hist.dropna(subset=["close"])

                        if hist.empty:
                            logger.warning("No price data for %s", ticker)
                            n_failed += 1
                            continue

                        # Ensure adj_close exists
                        if "adj_close" not in hist.columns:
                            hist["adj_close"] = hist.get("close")

                        # Ensure date column
                        if "date" not in hist.columns:
                            logger.warning("No 'date' column for %s", ticker)
                            n_failed += 1
                            continue

                        # Keep only needed columns
                        keep = ["date", "close", "adj_close", "volume"]
                        for col in keep:
                            if col not in hist.columns:
                                hist[col] = None
                        hist = hist[keep].copy()

                        hist["date"] = pd.to_datetime(
                            hist["date"]
                        ).dt.strftime("%Y-%m-%d")
                        hist["ticker"] = ticker

                        # Cache per-ticker
                        hist.to_csv(cache_path, index=False)

                        hist["cik"] = cik
                        hist["entity_name"] = entity_name
                        all_frames.append(hist)
                        n_downloaded += 1

                    except Exception as exc:
                        logger.warning(
                            "Failed to process %s: %s", ticker, exc,
                        )
                        n_failed += 1

        except Exception as exc:
            logger.error("yf.download() failed: %s", exc)
            n_failed += len(tickers_to_download)

    logger.info(
        "Listed prices: %d downloaded, %d from cache, %d failed",
        n_downloaded, n_cached, n_failed,
    )

    if not all_frames:
        return pd.DataFrame(columns=OUTPUT_COLUMNS)

    combined = pd.concat(all_frames, ignore_index=True)

    # Ensure consistent column ordering
    for col in OUTPUT_COLUMNS:
        if col not in combined.columns:
            combined[col] = None
    combined = combined[OUTPUT_COLUMNS]

    # Save combined output
    combined.to_csv(BDC_LISTED_PRICES_FILE, index=False)
    logger.info(
        "Saved bdc_listed_prices.csv: %d rows, %d tickers",
        len(combined), combined["ticker"].nunique(),
    )

    return combined


def rebuild_from_cache(ticker_map_df: pd.DataFrame | None = None) -> pd.DataFrame:
    """Rebuild combined listed prices from cached per-ticker CSVs.

    Parameters
    ----------
    ticker_map_df : DataFrame, optional
        If provided, uses it to map CIK/entity_name to tickers.
        If None, reads from cached per-ticker CSVs and uses whatever
        metadata is in them.

    Returns
    -------
    DataFrame with columns [cik, ticker, entity_name, date, close, adj_close, volume].
    """
    if not LISTED_PRICES_CACHE_DIR.exists():
        logger.warning("No listed prices cache dir")
        return pd.DataFrame(columns=OUTPUT_COLUMNS)

    csv_files = sorted(LISTED_PRICES_CACHE_DIR.glob("*.csv"))
    if not csv_files:
        logger.warning("No cached price CSVs found")
        return pd.DataFrame(columns=OUTPUT_COLUMNS)

    # Build ticker -> (cik, entity_name) lookup from ticker_map_df
    ticker_lookup: dict[str, tuple[str, str]] = {}
    if ticker_map_df is not None and not ticker_map_df.empty:
        for _, row in ticker_map_df.iterrows():
            ticker_lookup[row["ticker"]] = (
                row["cik"], row.get("entity_name", ""),
            )

    all_frames = []
    for csv_path in csv_files:
        ticker = csv_path.stem
        try:
            df = pd.read_csv(csv_path, dtype=str)
        except Exception as exc:
            logger.warning("Failed to read %s: %s", csv_path, exc)
            continue

        if "ticker" not in df.columns:
            df["ticker"] = ticker

        if ticker in ticker_lookup:
            cik, entity_name = ticker_lookup[ticker]
            df["cik"] = cik
            df["entity_name"] = entity_name
        elif "cik" not in df.columns:
            df["cik"] = ""
            df["entity_name"] = ""

        all_frames.append(df)

    if not all_frames:
        return pd.DataFrame(columns=OUTPUT_COLUMNS)

    combined = pd.concat(all_frames, ignore_index=True)
    for col in OUTPUT_COLUMNS:
        if col not in combined.columns:
            combined[col] = None
    combined = combined[OUTPUT_COLUMNS]

    combined.to_csv(BDC_LISTED_PRICES_FILE, index=False)
    logger.info(
        "Rebuilt bdc_listed_prices.csv from cache: %d rows, %d tickers",
        len(combined), combined["ticker"].nunique(),
    )

    return combined


def build_premium_discount(
    prices_df: pd.DataFrame | None = None,
    financials_csv: Path | None = None,
) -> pd.DataFrame:
    """Compute quarter-end premium/discount by joining prices against NAV.

    For each BDC CIK-quarter in fund_financials.csv, finds the closest
    trading-day close price within a 7-day lookback window from the
    quarter-end report_date, then computes:

        premium_discount_pct = (close - nav) / nav * 100

    Parameters
    ----------
    prices_df : DataFrame, optional
        Combined listed prices. Loaded from disk if None.
    financials_csv : Path, optional
        Path to fund_financials.csv. Uses default if None.

    Returns
    -------
    DataFrame with columns:
        [cik, ticker, report_quarter, report_date,
         close_price, nav_per_share, premium_discount_pct]
    """
    if financials_csv is None:
        financials_csv = FUND_FINANCIALS_FILE

    if prices_df is None:
        if BDC_LISTED_PRICES_FILE.exists():
            prices_df = pd.read_csv(BDC_LISTED_PRICES_FILE, dtype=str)
        else:
            logger.warning("No bdc_listed_prices.csv found")
            return pd.DataFrame(columns=PREMIUM_DISCOUNT_COLUMNS)

    if prices_df.empty:
        return pd.DataFrame(columns=PREMIUM_DISCOUNT_COLUMNS)

    if not financials_csv.exists():
        logger.warning("No fund_financials.csv at %s", financials_csv)
        return pd.DataFrame(columns=PREMIUM_DISCOUNT_COLUMNS)

    financials_df = pd.read_csv(financials_csv, dtype=str)

    con = duckdb.connect()
    con.register("prices", prices_df)
    con.register("financials", financials_df)

    sql = """
    WITH
    -- BDC quarters with NAV
    bdc_quarters AS (
        SELECT
            LPAD(CAST(cik AS VARCHAR), 10, '0') AS cik,
            report_quarter,
            CAST(report_date AS DATE) AS report_date,
            TRY_CAST(nav_per_share AS DOUBLE) AS nav_per_share
        FROM financials
        WHERE source = 'companyfacts'
          AND TRY_CAST(nav_per_share AS DOUBLE) IS NOT NULL
          AND TRY_CAST(nav_per_share AS DOUBLE) > 0
          AND TRY_CAST(report_date AS DATE) IS NOT NULL
    ),
    -- Prices with parsed dates
    price_dates AS (
        SELECT
            LPAD(CAST(cik AS VARCHAR), 10, '0') AS cik,
            ticker,
            CAST(date AS DATE) AS trade_date,
            TRY_CAST(close AS DOUBLE) AS close_price
        FROM prices
        WHERE TRY_CAST(close AS DOUBLE) IS NOT NULL
          AND TRY_CAST(close AS DOUBLE) > 0
    ),
    -- Join: find closest trading day within 7-day lookback
    joined AS (
        SELECT
            bq.cik,
            pd.ticker,
            bq.report_quarter,
            bq.report_date,
            pd.trade_date,
            pd.close_price,
            bq.nav_per_share,
            ROW_NUMBER() OVER (
                PARTITION BY bq.cik, bq.report_quarter
                ORDER BY ABS(date_diff('day', pd.trade_date, bq.report_date))
            ) AS rn
        FROM bdc_quarters bq
        JOIN price_dates pd
            ON bq.cik = pd.cik
            AND pd.trade_date <= bq.report_date
            AND pd.trade_date >= bq.report_date - INTERVAL '7 days'
    )
    SELECT
        cik,
        ticker,
        report_quarter,
        CAST(report_date AS VARCHAR) AS report_date,
        close_price,
        nav_per_share,
        (close_price - nav_per_share) / nav_per_share * 100.0
            AS premium_discount_pct
    FROM joined
    WHERE rn = 1
    ORDER BY cik, report_quarter
    """

    result = con.execute(sql).fetchdf()
    con.close()

    result.to_csv(BDC_PREMIUM_DISCOUNT_FILE, index=False)
    logger.info(
        "Premium/discount: %d rows, %d CIKs",
        len(result),
        result["cik"].nunique() if not result.empty else 0,
    )

    return result
