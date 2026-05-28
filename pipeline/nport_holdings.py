"""N-PORT holdings extraction for interval/tender offer funds.

Downloads SEC quarterly N-PORT TSV data sets, filters to the fund universe,
and produces investee-level holdings, fund-level info, and filing index CSVs.

Optionally supplements holdings with liquidity classification from raw
N-PORT XML filings (gated behind ``include_xml_supplement``).

Public API
----------
extract_nport_holdings(client, fund_universe=None, quarters=None,
                       include_xml_supplement=False) -> pd.DataFrame
"""

import io
import logging
import re
import time
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

import pandas as pd

from pipeline.config import (
    FUND_UNIVERSE_FILE,
    NPORT_DATASET_URL_TEMPLATE,
    NPORT_EXCLUDE_CIKS,
    NPORT_FILINGS_INDEX_FILE,
    NPORT_FUND_INFO_FILE,
    NPORT_HOLDINGS_FILE,
    NPORT_PARSE_PROGRESS_FILE,
    NPORT_QUARTERS,
    NPORT_TSV_CACHE_DIR,
    NPORT_XML_CACHE_DIR,
)
from pipeline.edgar_client import EdgarClient

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Date conversion helper
# ---------------------------------------------------------------------------
# SEC TSV dates are typically DD-MON-YYYY (e.g. "30-SEP-2024") or sometimes
# already YYYY-MM-DD.  Normalise everything to YYYY-MM-DD.
_MONTH_MAP = {
    "JAN": "01", "FEB": "02", "MAR": "03", "APR": "04",
    "MAY": "05", "JUN": "06", "JUL": "07", "AUG": "08",
    "SEP": "09", "OCT": "10", "NOV": "11", "DEC": "12",
}


def _normalise_date(val: str) -> str:
    """Convert DD-MON-YYYY to YYYY-MM-DD.  Pass through if already ISO."""
    if not val or not isinstance(val, str):
        return val
    val = val.strip()
    # Already ISO?
    if re.match(r"^\d{4}-\d{2}-\d{2}$", val):
        return val
    # DD-MON-YYYY
    m = re.match(r"^(\d{1,2})-([A-Z]{3})-(\d{4})$", val.upper())
    if m:
        day, mon, year = m.groups()
        month_num = _MONTH_MAP.get(mon, "00")
        return f"{year}-{month_num}-{day.zfill(2)}"
    return val


def _quarter_from_report_date(val: object) -> str:
    """Return calendar quarter label for a normalized report date."""
    norm = _normalise_date(val) if isinstance(val, str) else val
    dt = pd.to_datetime(norm, errors="coerce")
    if pd.isna(dt):
        return ""
    return f"{dt.year}q{((dt.month - 1) // 3) + 1}"


def _set_economic_quarter(df: pd.DataFrame, sec_dataset_quarter: str) -> pd.DataFrame:
    """Set public quarter from report_date and retain SEC bulk quarter."""
    if df.empty:
        return df
    df = df.copy()
    df["sec_dataset_quarter"] = sec_dataset_quarter
    if "report_date" in df.columns:
        derived = df["report_date"].apply(_quarter_from_report_date)
        df["quarter"] = derived.where(derived.astype(str) != "", sec_dataset_quarter)
    else:
        df["quarter"] = sec_dataset_quarter
    return df


# ===========================================================================
# TSV reading helper
# ===========================================================================

def _read_tsv_from_zip(
    zf: zipfile.ZipFile,
    filename: str,
    usecols: list[str] | None = None,
    chunksize: int | None = None,
    **kwargs: Any,
) -> pd.DataFrame | pd.io.parsers.TextFileReader:
    """Read a TSV file from an open ZipFile.

    All columns read as ``dtype=str``.  Bad lines are skipped.
    Returns a DataFrame or a TextFileReader if *chunksize* is set.
    """
    # Find the file inside the ZIP (may have a path prefix)
    matching = [n for n in zf.namelist() if n.endswith(filename)]
    if not matching:
        if chunksize:
            # Return an empty iterator
            return iter([])
        return pd.DataFrame()

    name_in_zip = matching[0]
    raw = zf.read(name_in_zip)

    return pd.read_csv(
        io.BytesIO(raw),
        sep="\t",
        dtype=str,
        on_bad_lines="skip",
        usecols=usecols,
        chunksize=chunksize,
        **kwargs,
    )


# ===========================================================================
# Step 1 -- Download quarterly ZIPs
# ===========================================================================

def _download_quarterly_zips(
    client: EdgarClient,
    quarters: list[str] | None = None,
) -> list[tuple[str, Path]]:
    """Download N-PORT quarterly ZIPs.  Skip if already cached (> 1 MB).

    Returns list of (quarter, zip_path) for successful downloads.
    """
    if quarters is None:
        quarters = list(NPORT_QUARTERS)

    results: list[tuple[str, Path]] = []

    for i, quarter in enumerate(quarters, 1):
        dest = NPORT_TSV_CACHE_DIR / f"{quarter}_nport.zip"

        # Skip if cached and reasonably sized
        if dest.exists() and dest.stat().st_size > 1_000_000:
            results.append((quarter, dest))
            if i % 5 == 0 or i == len(quarters):
                logger.info(
                    "  ZIP download progress: %d / %d (cached)", i, len(quarters),
                )
            continue

        url = NPORT_DATASET_URL_TEMPLATE.format(quarter=quarter)
        try:
            client.download_file(url, dest)
            results.append((quarter, dest))
        except Exception as exc:
            status_code = getattr(getattr(exc, "response", None), "status_code", None)
            if status_code == 404:
                logger.info("  Quarter %s not available (404)", quarter)
            else:
                logger.warning("  Failed to download %s: %s", quarter, exc)

        if i % 5 == 0 or i == len(quarters):
            logger.info(
                "  ZIP download progress: %d / %d (%d available)",
                i, len(quarters), len(results),
            )

    logger.info("Downloaded/cached %d of %d quarterly ZIPs", len(results), len(quarters))
    return results


# ===========================================================================
# Step 1b -- Amendment dedup helper
# ===========================================================================

def _dedup_amendments(df: pd.DataFrame, label: str) -> pd.DataFrame:
    """Keep only the latest accession per (CIK, SERIES_ID, REPORT_DATE) group.

    When a fund re-files as NPORT-P/A, the SEC bulk dataset includes both
    original and amendment rows.  We keep the amendment (later accession number).
    """
    if df.empty or "ACCESSION_NUMBER" not in df.columns:
        return df

    group_cols: list[str] = []
    if "CIK" in df.columns:
        group_cols.append("CIK")
    if "REPORT_DATE" in df.columns:
        group_cols.append("REPORT_DATE")

    has_series = "SERIES_ID" in df.columns
    if has_series:
        df = df.copy()
        df["_SERIES_KEY"] = df["SERIES_ID"].fillna("")
        group_cols.append("_SERIES_KEY")

    if not group_cols:
        return df

    latest_acc = df.groupby(group_cols)["ACCESSION_NUMBER"].transform("max")
    pre_count = len(df)
    df = df[df["ACCESSION_NUMBER"] == latest_acc]
    removed = pre_count - len(df)

    if has_series and "_SERIES_KEY" in df.columns:
        df = df.drop(columns=["_SERIES_KEY"])

    if removed > 0:
        logger.info("  Amendment dedup (%s): removed %d rows", label, removed)

    return df


# ===========================================================================
# Step 2 -- Process one quarterly ZIP
# ===========================================================================

def _process_quarter_tsv(
    zip_path: Path,
    quarter: str,
    target_ciks: set[str],
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Process a single quarterly N-PORT ZIP.

    Returns (holdings_df, fund_info_df, filings_index_df).
    All filtered to *target_ciks*.
    """
    with zipfile.ZipFile(zip_path, "r") as zf:
        # 1) REGISTRANT -- filter to target CIKs
        reg = _read_tsv_from_zip(zf, "REGISTRANT.tsv")
        if reg.empty:
            return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

        reg.columns = reg.columns.str.strip()
        # CIK column may have leading zeros or spaces
        reg["CIK"] = reg["CIK"].astype(str).str.strip().str.lstrip("0")
        reg = reg[reg["CIK"].isin(target_ciks)]
        if reg.empty:
            return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

        acc_set = set(reg["ACCESSION_NUMBER"].dropna().unique())

        # 2) SUBMISSION
        sub = _read_tsv_from_zip(zf, "SUBMISSION.tsv")
        if not sub.empty:
            sub.columns = sub.columns.str.strip()
            sub = sub[sub["ACCESSION_NUMBER"].isin(acc_set)]
        else:
            sub = pd.DataFrame(columns=["ACCESSION_NUMBER"])

        # 3) FUND_REPORTED_INFO
        fri = _read_tsv_from_zip(zf, "FUND_REPORTED_INFO.tsv")
        if not fri.empty:
            fri.columns = fri.columns.str.strip()
            fri = fri[fri["ACCESSION_NUMBER"].isin(acc_set)]
        else:
            fri = pd.DataFrame(columns=["ACCESSION_NUMBER"])

        # 4) MONTHLY_TOTAL_RETURN
        mtr = _read_tsv_from_zip(zf, "MONTHLY_TOTAL_RETURN.tsv")
        if not mtr.empty:
            mtr.columns = mtr.columns.str.strip()
            mtr = mtr[mtr["ACCESSION_NUMBER"].isin(acc_set)]
        else:
            mtr = pd.DataFrame(columns=["ACCESSION_NUMBER"])

        # 4b) BORROW_AGGREGATE -- total borrowings detail
        borrow_agg = _read_tsv_from_zip(zf, "BORROW_AGGREGATE.tsv")
        if not borrow_agg.empty:
            borrow_agg.columns = borrow_agg.columns.str.strip()
            if "ACCESSION_NUMBER" in borrow_agg.columns:
                borrow_agg = borrow_agg[
                    borrow_agg["ACCESSION_NUMBER"].isin(acc_set)
                ]
        else:
            borrow_agg = pd.DataFrame(columns=["ACCESSION_NUMBER"])

        # 4c) INTEREST_RATE_RISK -- DV01 at various tenors
        irr = _read_tsv_from_zip(zf, "INTEREST_RATE_RISK.tsv")
        if not irr.empty:
            irr.columns = irr.columns.str.strip()
            if "ACCESSION_NUMBER" in irr.columns:
                irr = irr[irr["ACCESSION_NUMBER"].isin(acc_set)]
        else:
            irr = pd.DataFrame(columns=["ACCESSION_NUMBER"])

        # 5) FUND_REPORTED_HOLDING -- read in chunks for memory efficiency
        holding_chunks: list[pd.DataFrame] = []
        reader = _read_tsv_from_zip(
            zf, "FUND_REPORTED_HOLDING.tsv", chunksize=500_000,
        )
        for chunk in reader:
            chunk.columns = chunk.columns.str.strip()
            filtered = chunk[chunk["ACCESSION_NUMBER"].isin(acc_set)]
            if not filtered.empty:
                holding_chunks.append(filtered)

        if holding_chunks:
            holdings = pd.concat(holding_chunks, ignore_index=True)
        else:
            holdings = pd.DataFrame()

        if holdings.empty:
            # Still build filings_index and fund_info even without holdings
            holdings = pd.DataFrame()

        # Get holding IDs for supplementary table joins
        holding_id_set: set[str] = set()
        if not holdings.empty and "HOLDING_ID" in holdings.columns:
            holding_id_set = set(holdings["HOLDING_ID"].dropna().unique())

        # 6) DEBT_SECURITY
        debt = _read_tsv_from_zip(zf, "DEBT_SECURITY.tsv")
        if not debt.empty:
            debt.columns = debt.columns.str.strip()
            if "HOLDING_ID" in debt.columns and holding_id_set:
                debt = debt[debt["HOLDING_ID"].isin(holding_id_set)]
            else:
                debt = pd.DataFrame()
        else:
            debt = pd.DataFrame()

        # 7) IDENTIFIERS -- deduplicate to one row per holding_id
        idents = _read_tsv_from_zip(zf, "IDENTIFIERS.tsv")
        if not idents.empty:
            idents.columns = idents.columns.str.strip()
            if "HOLDING_ID" in idents.columns and holding_id_set:
                idents = idents[idents["HOLDING_ID"].isin(holding_id_set)]
                idents = idents.drop_duplicates(subset=["HOLDING_ID"], keep="first")
            else:
                idents = pd.DataFrame()
        else:
            idents = pd.DataFrame()

    # -- Amendment dedup: keep only the latest accession per filing group --
    # Enrich fri with CIK + REPORT_DATE before amendment dedup so grouping
    # doesn't collapse all empty-SERIES_ID rows into one group.
    if not fri.empty:
        if not reg.empty and "CIK" in reg.columns:
            _reg_cik = reg[["ACCESSION_NUMBER", "CIK"]].drop_duplicates(
                subset=["ACCESSION_NUMBER"], keep="first",
            )
            fri = fri.merge(_reg_cik, on="ACCESSION_NUMBER", how="left")
        if not sub.empty and "REPORT_DATE" in sub.columns:
            _sub_rd = sub[["ACCESSION_NUMBER", "REPORT_DATE"]].drop_duplicates(
                subset=["ACCESSION_NUMBER"], keep="first",
            )
            fri = fri.merge(_sub_rd, on="ACCESSION_NUMBER", how="left")
    if not holdings.empty:
        if not reg.empty and "CIK" in reg.columns:
            _reg_cik_h = reg[["ACCESSION_NUMBER", "CIK"]].drop_duplicates(
                subset=["ACCESSION_NUMBER"], keep="first",
            )
            holdings = holdings.merge(
                _reg_cik_h, on="ACCESSION_NUMBER", how="left",
            )
        if not sub.empty and "REPORT_DATE" in sub.columns:
            _sub_rd_h = sub[["ACCESSION_NUMBER", "REPORT_DATE"]].drop_duplicates(
                subset=["ACCESSION_NUMBER"], keep="first",
            )
            holdings = holdings.merge(
                _sub_rd_h, on="ACCESSION_NUMBER", how="left",
            )
        # Enrich with SERIES_ID from FRI so dedup groups by
        # (CIK, REPORT_DATE, SERIES_ID) -- multi-series CIKs preserved.
        if not fri.empty and "SERIES_ID" in fri.columns:
            _fri_sid = fri[["ACCESSION_NUMBER", "SERIES_ID"]].drop_duplicates(
                subset=["ACCESSION_NUMBER"], keep="first",
            )
            holdings = holdings.merge(
                _fri_sid, on="ACCESSION_NUMBER", how="left",
            )
    if not holdings.empty:
        holdings = _dedup_amendments(holdings, "holdings")
        for _tmp_h in ("CIK", "REPORT_DATE", "SERIES_ID"):
            if _tmp_h in holdings.columns:
                holdings = holdings.drop(columns=[_tmp_h])
    if not fri.empty:
        fri = _dedup_amendments(fri, "fund_info")
        for _tmp in ("CIK", "REPORT_DATE"):
            if _tmp in fri.columns:
                fri = fri.drop(columns=[_tmp])

    # -- Build holdings output --
    if not holdings.empty:
        # Join debt security
        if not debt.empty and "HOLDING_ID" in debt.columns:
            debt_cols = [c for c in debt.columns if c != "ACCESSION_NUMBER" or c == "HOLDING_ID"]
            # Keep only meaningful debt columns + HOLDING_ID
            debt_keep = ["HOLDING_ID"]
            for c in ["MATURITY_DATE", "COUPON_TYPE", "ANNUALIZED_RATE", "IS_DEFAULT",
                       "ARE_ANY_INTEREST_PAYMENT", "IS_ANY_PORTION_INTEREST_PAID"]:
                if c in debt.columns:
                    debt_keep.append(c)
            debt_sub = debt[debt_keep].drop_duplicates(subset=["HOLDING_ID"], keep="first")
            holdings = holdings.merge(debt_sub, on="HOLDING_ID", how="left")

        # Join identifiers
        if not idents.empty and "HOLDING_ID" in idents.columns:
            id_keep = ["HOLDING_ID"]
            for c in ["IDENTIFIER_ISIN", "IDENTIFIER_TICKER", "OTHER_IDENTIFIER",
                       "IDENTIFIER_OTHER_DESC"]:
                if c in idents.columns:
                    id_keep.append(c)
            id_sub = idents[id_keep]
            holdings = holdings.merge(id_sub, on="HOLDING_ID", how="left")

        # Join registrant info (cik, entity_name)
        reg_keep = ["ACCESSION_NUMBER", "CIK"]
        if "ENTITY_NAME" in reg.columns:
            reg_keep.append("ENTITY_NAME")
        elif "REGISTRANT_NAME" in reg.columns:
            reg_keep.append("REGISTRANT_NAME")
        reg_sub = reg[reg_keep].drop_duplicates(subset=["ACCESSION_NUMBER"], keep="first")
        holdings = holdings.merge(reg_sub, on="ACCESSION_NUMBER", how="left")

        # Join submission info (filing_date, report_date, sub_type)
        if not sub.empty:
            sub_keep = ["ACCESSION_NUMBER"]
            for c in ["FILING_DATE", "REPORT_DATE", "SUB_TYPE"]:
                if c in sub.columns:
                    sub_keep.append(c)
            sub_sub = sub[sub_keep].drop_duplicates(subset=["ACCESSION_NUMBER"], keep="first")
            holdings = holdings.merge(sub_sub, on="ACCESSION_NUMBER", how="left")

        # Join fund_reported_info (series_name, series_id)
        if not fri.empty:
            fri_keep = ["ACCESSION_NUMBER"]
            for c in ["SERIES_NAME", "SERIES_ID"]:
                if c in fri.columns:
                    fri_keep.append(c)
            if len(fri_keep) > 1:
                fri_sub = fri[fri_keep].drop_duplicates(
                    subset=["ACCESSION_NUMBER"], keep="first",
                )
                holdings = holdings.merge(fri_sub, on="ACCESSION_NUMBER", how="left")

        holdings["QUARTER"] = quarter

    # -- Build fund_info output --
    fund_info = pd.DataFrame()
    if not fri.empty:
        fund_info = fri.copy()
        # Join registrant
        if not reg_sub.empty:
            fund_info = fund_info.merge(reg_sub, on="ACCESSION_NUMBER", how="left")
        # Join submission
        if not sub.empty and "ACCESSION_NUMBER" in sub.columns:
            sub_keep2 = ["ACCESSION_NUMBER"]
            for c in ["FILING_DATE", "REPORT_DATE"]:
                if c in sub.columns:
                    sub_keep2.append(c)
            sub_sub2 = sub[sub_keep2].drop_duplicates(
                subset=["ACCESSION_NUMBER"], keep="first",
            )
            fund_info = fund_info.merge(sub_sub2, on="ACCESSION_NUMBER", how="left")
        # Join monthly returns
        if not mtr.empty and "ACCESSION_NUMBER" in mtr.columns:
            fund_info = fund_info.merge(mtr, on="ACCESSION_NUMBER", how="left")

        # Join BORROW_AGGREGATE: sum AMOUNT per accession
        if (not borrow_agg.empty
                and "ACCESSION_NUMBER" in borrow_agg.columns
                and "AMOUNT" in borrow_agg.columns):
            ba = borrow_agg.copy()
            ba["AMOUNT"] = pd.to_numeric(ba["AMOUNT"], errors="coerce")
            ba_sum = (
                ba.groupby("ACCESSION_NUMBER")["AMOUNT"]
                .sum()
                .reset_index()
                .rename(columns={"AMOUNT": "TOTAL_BORROWINGS_DETAIL"})
            )
            fund_info = fund_info.merge(
                ba_sum, on="ACCESSION_NUMBER", how="left",
            )

        # Join INTEREST_RATE_RISK: DV01 and DV100 at all tenors (USD)
        if (not irr.empty
                and "ACCESSION_NUMBER" in irr.columns):
            irr_filt = irr.copy()
            # Filter to USD if CURRENCY_CODE column exists
            if "CURRENCY_CODE" in irr_filt.columns:
                irr_filt = irr_filt[irr_filt["CURRENCY_CODE"] == "USD"]

            _IRR_RENAME = {
                "INTRST_RATE_CHANGE_3MON_DV01": "DV01_3MON",
                "INTRST_RATE_CHANGE_1YR_DV01": "DV01_1YR",
                "INTRST_RATE_CHANGE_5YR_DV01": "DV01_5YR",
                "INTRST_RATE_CHANGE_10YR_DV01": "DV01_10YR",
                "INTRST_RATE_CHANGE_30YR_DV01": "DV01_30YR",
                "INTRST_RATE_CHANGE_3MON_DV100": "DV100_3MON",
                "INTRST_RATE_CHANGE_1YR_DV100": "DV100_1YR",
                "INTRST_RATE_CHANGE_5YR_DV100": "DV100_5YR",
                "INTRST_RATE_CHANGE_10YR_DV100": "DV100_10YR",
                "INTRST_RATE_CHANGE_30YR_DV100": "DV100_30YR",
            }
            rename_map = {
                src: dst for src, dst in _IRR_RENAME.items()
                if src in irr_filt.columns
            }
            if rename_map:
                irr_sub = irr_filt[
                    ["ACCESSION_NUMBER"] + list(rename_map.keys())
                ].copy()
                irr_sub = irr_sub.rename(columns=rename_map)
                for col in rename_map.values():
                    irr_sub[col] = pd.to_numeric(irr_sub[col], errors="coerce")
                irr_agg = (
                    irr_sub.groupby("ACCESSION_NUMBER")
                    .sum(numeric_only=True)
                    .reset_index()
                )
                fund_info = fund_info.merge(
                    irr_agg, on="ACCESSION_NUMBER", how="left",
                )

        fund_info["QUARTER"] = quarter

    # -- Build filings_index output --
    filings_index = pd.DataFrame()
    if not reg.empty:
        idx = reg[["ACCESSION_NUMBER", "CIK"]].copy()
        if "ENTITY_NAME" in reg.columns:
            idx["ENTITY_NAME"] = reg["ENTITY_NAME"]
        elif "REGISTRANT_NAME" in reg.columns:
            idx["ENTITY_NAME"] = reg["REGISTRANT_NAME"]

        if not sub.empty:
            sub_keep3 = ["ACCESSION_NUMBER"]
            for c in ["FILING_DATE", "REPORT_DATE", "SUB_TYPE"]:
                if c in sub.columns:
                    sub_keep3.append(c)
            sub_sub3 = sub[sub_keep3].drop_duplicates(
                subset=["ACCESSION_NUMBER"], keep="first",
            )
            idx = idx.merge(sub_sub3, on="ACCESSION_NUMBER", how="left")

        if not fri.empty:
            fri_keep2 = ["ACCESSION_NUMBER"]
            for c in ["SERIES_NAME", "SERIES_ID", "TOTAL_ASSETS", "NET_ASSETS"]:
                if c in fri.columns:
                    fri_keep2.append(c)
            if len(fri_keep2) > 1:
                fri_sub2 = fri[fri_keep2].drop_duplicates(
                    subset=["ACCESSION_NUMBER"], keep="first",
                )
                idx = idx.merge(fri_sub2, on="ACCESSION_NUMBER", how="left")

        # Holdings count per accession
        if not holdings.empty and "ACCESSION_NUMBER" in holdings.columns:
            hcount = (
                holdings.groupby("ACCESSION_NUMBER")
                .size()
                .reset_index(name="HOLDINGS_COUNT")
            )
            idx = idx.merge(hcount, on="ACCESSION_NUMBER", how="left")
            idx["HOLDINGS_COUNT"] = idx["HOLDINGS_COUNT"].fillna("0")
        else:
            idx["HOLDINGS_COUNT"] = "0"

        idx["QUARTER"] = quarter
        idx = idx.drop_duplicates(subset=["ACCESSION_NUMBER"], keep="first")
        filings_index = idx

    # Lowercase all column names in all outputs
    if not holdings.empty:
        holdings.columns = holdings.columns.str.lower()
        # Normalise date columns
        for dc in ["filing_date", "report_date", "maturity_date"]:
            if dc in holdings.columns:
                holdings[dc] = holdings[dc].apply(_normalise_date)
        holdings = _set_economic_quarter(holdings, quarter)

    if not fund_info.empty:
        fund_info.columns = fund_info.columns.str.lower()
        for dc in ["filing_date", "report_date"]:
            if dc in fund_info.columns:
                fund_info[dc] = fund_info[dc].apply(_normalise_date)
        fund_info = _set_economic_quarter(fund_info, quarter)

    if not filings_index.empty:
        filings_index.columns = filings_index.columns.str.lower()
        for dc in ["filing_date", "report_date"]:
            if dc in filings_index.columns:
                filings_index[dc] = filings_index[dc].apply(_normalise_date)
        filings_index = _set_economic_quarter(filings_index, quarter)

    return holdings, fund_info, filings_index


# ===========================================================================
# Step 2b -- Batch processing with resumability
# ===========================================================================

def _process_all_quarters(
    client: EdgarClient,
    target_ciks: set[str],
    quarters: list[str] | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Download and process all quarterly ZIPs with resumability.

    Returns (holdings_df, fund_info_df, filings_index_df).
    """
    # Load progress
    processed_quarters: set[str] = set()
    if NPORT_PARSE_PROGRESS_FILE.exists():
        prog = pd.read_csv(NPORT_PARSE_PROGRESS_FILE, dtype=str)
        processed_quarters = set(
            prog.loc[prog["status"] == "processed", "quarter"]
        )
        logger.info(
            "Resuming -- %d quarters already processed", len(processed_quarters),
        )

    # Download ZIPs
    zip_files = _download_quarterly_zips(client, quarters)

    # Filter to unprocessed
    to_process = [(q, p) for q, p in zip_files if q not in processed_quarters]
    logger.info(
        "Quarters to process: %d (skipping %d already done)",
        len(to_process), len(zip_files) - len(to_process),
    )

    all_holdings: list[pd.DataFrame] = []
    all_fund_info: list[pd.DataFrame] = []
    all_filings_index: list[pd.DataFrame] = []
    progress_records: list[dict[str, str]] = []
    total_holdings = 0
    t0 = time.time()

    for i, (quarter, zip_path) in enumerate(to_process, 1):
        try:
            h, fi, idx = _process_quarter_tsv(zip_path, quarter, target_ciks)
            n_holdings = len(h)
            total_holdings += n_holdings

            if not h.empty:
                all_holdings.append(h)
            if not fi.empty:
                all_fund_info.append(fi)
            if not idx.empty:
                all_filings_index.append(idx)

            progress_records.append({
                "quarter": quarter,
                "status": "processed",
                "holdings_count": str(n_holdings),
                "timestamp": datetime.now().isoformat(),
            })
        except Exception as exc:
            logger.warning("Error processing quarter %s: %s", quarter, exc)
            progress_records.append({
                "quarter": quarter,
                "status": "error",
                "holdings_count": "0",
                "timestamp": datetime.now().isoformat(),
            })

        # Periodic progress save and logging
        if i % 5 == 0 or i == len(to_process):
            _save_nport_progress(progress_records)
            elapsed = time.time() - t0
            rate = i / elapsed if elapsed > 0 else 0
            eta = (len(to_process) - i) / rate if rate > 0 else 0
            logger.info(
                "  Processed %d / %d quarters (%d holdings so far, ETA %.0f s)",
                i, len(to_process), total_holdings, eta,
            )

    # Final progress save
    _save_nport_progress(progress_records)

    # Concatenate new results
    new_holdings = pd.concat(all_holdings, ignore_index=True) if all_holdings else pd.DataFrame()
    new_fund_info = pd.concat(all_fund_info, ignore_index=True) if all_fund_info else pd.DataFrame()
    new_filings_index = pd.concat(all_filings_index, ignore_index=True) if all_filings_index else pd.DataFrame()

    # Merge with existing on-disk data (from prior partial runs)
    holdings = _merge_with_existing(new_holdings, NPORT_HOLDINGS_FILE, ["accession_number", "holding_id"])
    fund_info = _merge_with_existing(new_fund_info, NPORT_FUND_INFO_FILE, None)
    filings_index = _merge_with_existing(new_filings_index, NPORT_FILINGS_INDEX_FILE, ["accession_number"])

    # Save
    if not holdings.empty:
        holdings.to_csv(NPORT_HOLDINGS_FILE, index=False)
        logger.info("Holdings saved: %d rows -> %s", len(holdings), NPORT_HOLDINGS_FILE.name)
    if not fund_info.empty:
        fund_info.to_csv(NPORT_FUND_INFO_FILE, index=False)
        logger.info("Fund info saved: %d rows -> %s", len(fund_info), NPORT_FUND_INFO_FILE.name)
    if not filings_index.empty:
        filings_index.to_csv(NPORT_FILINGS_INDEX_FILE, index=False)
        logger.info("Filings index saved: %d rows -> %s", len(filings_index), NPORT_FILINGS_INDEX_FILE.name)

    return holdings, fund_info, filings_index


def _merge_with_existing(
    new_df: pd.DataFrame,
    existing_path: Path,
    dedup_cols: list[str] | None,
) -> pd.DataFrame:
    """Merge new data with existing CSV on disk, deduplicating if specified."""
    if new_df.empty and existing_path.exists():
        return pd.read_csv(existing_path, dtype=str)

    if new_df.empty:
        return pd.DataFrame()

    if existing_path.exists():
        existing = pd.read_csv(existing_path, dtype=str)
        combined = pd.concat([existing, new_df], ignore_index=True)
    else:
        combined = new_df

    if dedup_cols:
        # Only dedup on columns that exist
        valid_cols = [c for c in dedup_cols if c in combined.columns]
        if valid_cols:
            combined.drop_duplicates(subset=valid_cols, keep="last", inplace=True)

    return combined


def _save_nport_progress(new_records: list[dict[str, str]]) -> None:
    """Append progress records to the N-PORT progress file."""
    if not new_records:
        return
    new_df = pd.DataFrame(new_records)
    if NPORT_PARSE_PROGRESS_FILE.exists():
        existing = pd.read_csv(NPORT_PARSE_PROGRESS_FILE, dtype=str)
        combined = pd.concat([existing, new_df], ignore_index=True)
        combined.drop_duplicates(subset=["quarter"], keep="last", inplace=True)
    else:
        combined = new_df
    combined.to_csv(NPORT_PARSE_PROGRESS_FILE, index=False)


# ===========================================================================
# Step 3 -- XML supplement for liquidity classification (optional)
# ===========================================================================

def _parse_nport_xml_liquidity(xml_path: str | Path) -> dict[str, str]:
    """Parse one N-PORT XML file for per-holding liquidity classification.

    Returns dict keyed by CUSIP -> liquidity category string.
    Categories: 'Highly Liquid', 'Moderately Liquid', 'Less Liquid', 'Illiquid'
    """
    result: dict[str, str] = {}
    try:
        tree = ET.parse(str(xml_path))
    except Exception as exc:
        logger.debug("XML parse error for %s: %s", xml_path, exc)
        return result

    root = tree.getroot()
    # N-PORT XML uses the SEC namespace
    ns = ""
    # Try to detect namespace from root tag
    m = re.match(r"\{(.+?)\}", root.tag)
    if m:
        ns = m.group(1)

    def _find(elem: ET.Element, tag: str) -> ET.Element | None:
        """Find child element with or without namespace."""
        if ns:
            found = elem.find(f"{{{ns}}}{tag}")
            if found is not None:
                return found
        return elem.find(tag)

    def _findall(elem: ET.Element, tag: str) -> list[ET.Element]:
        """Find all child elements with or without namespace."""
        if ns:
            found = elem.findall(f"{{{ns}}}{tag}")
            if found:
                return found
        return elem.findall(tag)

    # Map liquidity category codes to human-readable names
    _LIQ_MAP = {
        "1": "Highly Liquid",
        "2": "Moderately Liquid",
        "3": "Less Liquid",
        "4": "Illiquid",
    }

    # Find all invstOrSec elements (individual holdings)
    for inv in root.iter():
        tag = inv.tag
        if isinstance(tag, str):
            local = tag.split("}")[-1] if "}" in tag else tag
        else:
            continue

        if local != "invstOrSec":
            continue

        # Extract CUSIP
        cusip_elem = _find(inv, "cusip")
        cusip = (cusip_elem.text or "").strip() if cusip_elem is not None else ""
        if not cusip:
            continue

        # Try single category (fundCat)
        liq_cat = ""
        fund_cat_elem = _find(inv, "fundCat")
        if fund_cat_elem is not None:
            cat_code = (fund_cat_elem.text or "").strip()
            liq_cat = _LIQ_MAP.get(cat_code, cat_code)

        # Try multi-bucket (fundCats -> fundCat elements)
        if not liq_cat:
            fund_cats_elem = _find(inv, "fundCats")
            if fund_cats_elem is not None:
                cats = _findall(fund_cats_elem, "fundCat")
                if cats:
                    # Take the category with highest percentage
                    best_pct = -1.0
                    best_cat = ""
                    for cat_elem in cats:
                        cat_code = cat_elem.get("category", "")
                        pct_str = cat_elem.get("pct", "0")
                        try:
                            pct = float(pct_str)
                        except (ValueError, TypeError):
                            pct = 0.0
                        if pct > best_pct:
                            best_pct = pct
                            best_cat = _LIQ_MAP.get(cat_code, cat_code)
                    liq_cat = best_cat

        if liq_cat:
            result[cusip] = liq_cat

    return result


def _supplement_from_xml(
    client: EdgarClient,
    holdings: pd.DataFrame,
    filings_index: pd.DataFrame,
) -> pd.DataFrame:
    """Download raw N-PORT XML filings and add liquidity classification.

    For each unique (cik, accession_number), download the XML, parse
    liquidity data, and left-join back onto holdings via (accession_number,
    issuer_cusip).
    """
    if holdings.empty:
        return holdings

    # Get unique (cik, accession_number) pairs
    if "cik" in filings_index.columns and "accession_number" in filings_index.columns:
        pairs = filings_index[["cik", "accession_number"]].drop_duplicates()
    elif "cik" in holdings.columns and "accession_number" in holdings.columns:
        pairs = holdings[["cik", "accession_number"]].drop_duplicates()
    else:
        logger.warning("Cannot determine cik/accession_number for XML supplement")
        return holdings

    total = len(pairs)
    logger.info("Downloading %d N-PORT XML filings for liquidity data ...", total)

    liq_records: list[dict[str, str]] = []
    t0 = time.time()

    for i, (_, row) in enumerate(pairs.iterrows(), 1):
        cik = str(row["cik"]).strip()
        acc = str(row["accession_number"]).strip()
        acc_no_dashes = acc.replace("-", "")

        cache_dir = NPORT_XML_CACHE_DIR / cik
        cache_file = cache_dir / f"{acc_no_dashes}.xml"

        # Check cache
        if cache_file.exists() and cache_file.stat().st_size > 1024:
            liq_map = _parse_nport_xml_liquidity(cache_file)
            for cusip, liq_cat in liq_map.items():
                liq_records.append({
                    "accession_number": acc,
                    "issuer_cusip": cusip,
                    "liquidity_classification": liq_cat,
                })
            if i % 100 == 0 or i == total:
                elapsed = time.time() - t0
                rate = i / elapsed if elapsed > 0 else 0
                eta = (total - i) / rate if rate > 0 else 0
                logger.info(
                    "  XML progress: %d / %d (ETA %.0f s)", i, total, eta,
                )
            continue

        # Fetch filing index page, find XML document
        cik_stripped = cik.lstrip("0") or "0"
        index_url = (
            f"https://www.sec.gov/Archives/edgar/data/"
            f"{cik_stripped}/{acc_no_dashes}/{acc}-index.htm"
        )
        resp = client.get_safe(index_url)
        if resp is None:
            continue

        # Find primary XML document (nport-p XML)
        xml_url = _find_nport_xml_url(resp.text, cik_stripped, acc_no_dashes)
        if xml_url is None:
            continue

        # Download
        try:
            cache_file.parent.mkdir(parents=True, exist_ok=True)
            client.download_file(xml_url, cache_file)
        except Exception as exc:
            logger.debug("Failed to download XML for %s: %s", acc, exc)
            continue

        liq_map = _parse_nport_xml_liquidity(cache_file)
        for cusip, liq_cat in liq_map.items():
            liq_records.append({
                "accession_number": acc,
                "issuer_cusip": cusip,
                "liquidity_classification": liq_cat,
            })

        if i % 100 == 0 or i == total:
            elapsed = time.time() - t0
            rate = i / elapsed if elapsed > 0 else 0
            eta = (total - i) / rate if rate > 0 else 0
            logger.info("  XML progress: %d / %d (ETA %.0f s)", i, total, eta)

    if not liq_records:
        logger.info("No liquidity data found in XML filings")
        holdings["liquidity_classification"] = ""
        return holdings

    liq_df = pd.DataFrame(liq_records)
    liq_df.drop_duplicates(
        subset=["accession_number", "issuer_cusip"], keep="first", inplace=True,
    )

    # Left join onto holdings
    if "issuer_cusip" in holdings.columns:
        holdings = holdings.merge(
            liq_df,
            on=["accession_number", "issuer_cusip"],
            how="left",
        )
    else:
        holdings["liquidity_classification"] = ""

    logger.info(
        "Liquidity classification added: %d of %d holdings have data",
        holdings["liquidity_classification"].notna().sum()
        if "liquidity_classification" in holdings.columns else 0,
        len(holdings),
    )

    return holdings


def _find_nport_xml_url(
    index_html: str,
    cik_stripped: str,
    acc_no_dashes: str,
) -> str | None:
    """Parse a filing index page to find the primary N-PORT XML document URL."""
    href_pattern = re.compile(r'href="([^"]+\.xml)"', re.IGNORECASE)

    for m in href_pattern.finditer(index_html):
        href = m.group(1)
        fname = href.rsplit("/", 1)[-1].lower()
        # Skip taxonomy/rendering/calculation files
        if any(skip in fname for skip in ("_cal.", "_lab.", "_def.", "_pre.", "r9999")):
            continue
        # Prefer primary nport document
        if "nport" in fname or "primary_doc" in fname:
            if href.startswith("/"):
                return f"https://www.sec.gov{href}"
            if not href.startswith("http"):
                return (
                    f"https://www.sec.gov/Archives/edgar/data/"
                    f"{cik_stripped}/{acc_no_dashes}/{href}"
                )
            return href

    # Fallback: any .xml that isn't taxonomy
    for m in href_pattern.finditer(index_html):
        href = m.group(1)
        fname = href.rsplit("/", 1)[-1].lower()
        if any(skip in fname for skip in ("_cal.", "_lab.", "_def.", "_pre.", "r9999")):
            continue
        if href.startswith("/"):
            return f"https://www.sec.gov{href}"
        if not href.startswith("http"):
            return (
                f"https://www.sec.gov/Archives/edgar/data/"
                f"{cik_stripped}/{acc_no_dashes}/{href}"
            )
        return href

    return None


# ===========================================================================
# Public entry point
# ===========================================================================

def extract_nport_holdings(
    client: EdgarClient,
    fund_universe: pd.DataFrame | None = None,
    quarters: list[str] | None = None,
    include_xml_supplement: bool = False,
) -> pd.DataFrame:
    """End-to-end N-PORT holdings extraction pipeline.

    1. Download quarterly N-PORT TSV ZIPs from SEC
    2. Filter and join TSVs to extract holdings for target CIKs
    3. Optionally supplement with liquidity classification from raw XML

    Parameters
    ----------
    client : EdgarClient
        Rate-limited HTTP client.
    fund_universe : pd.DataFrame, optional
        Fund universe with a ``cik`` column. If *None*, loaded from disk.
    quarters : list[str], optional
        Specific quarters to process. Defaults to all NPORT_QUARTERS.
    include_xml_supplement : bool
        If True, download raw N-PORT XML for liquidity classification.

    Returns
    -------
    pd.DataFrame
        One row per holding per filing.
    """
    logger.info("=" * 60)
    logger.info("N-PORT HOLDINGS EXTRACTION -- STARTING")
    logger.info("=" * 60)
    t0 = time.time()

    # Load universe if not provided
    if fund_universe is None:
        if not FUND_UNIVERSE_FILE.exists():
            raise FileNotFoundError(
                f"Fund universe file not found: {FUND_UNIVERSE_FILE}"
            )
        fund_universe = pd.read_csv(FUND_UNIVERSE_FILE, dtype=str)

    # Build target CIKs set (strip leading zeros for matching)
    target_ciks = set(
        fund_universe["cik"]
        .astype(str)
        .str.strip()
        .str.lstrip("0")
        .unique()
    )
    # Exclude consumer/marketplace lending CIKs at extraction time so they
    # never enter nport_holdings.csv (saves ~7M throwaway rows and ~2 GB).
    if NPORT_EXCLUDE_CIKS:
        excluded = target_ciks & NPORT_EXCLUDE_CIKS
        if excluded:
            target_ciks -= NPORT_EXCLUDE_CIKS
            logger.info(
                "Excluded %d consumer/marketplace CIKs from extraction: %s",
                len(excluded), ", ".join(sorted(excluded)),
            )
    logger.info(
        "Fund universe: %d rows, %d unique CIKs", len(fund_universe), len(target_ciks),
    )

    # Process all quarters
    holdings, fund_info, filings_index = _process_all_quarters(
        client, target_ciks, quarters,
    )

    # Optional XML supplement
    if include_xml_supplement and not holdings.empty:
        logger.info("")
        logger.info("-- XML supplement: liquidity classification --")
        t_xml = time.time()
        holdings = _supplement_from_xml(client, holdings, filings_index)
        # Re-save with liquidity data
        if not holdings.empty:
            holdings.to_csv(NPORT_HOLDINGS_FILE, index=False)
        logger.info("  XML supplement complete (%.1f s)", time.time() - t_xml)

    # Summary
    total_time = time.time() - t0
    logger.info("")
    logger.info("=" * 60)
    logger.info("N-PORT HOLDINGS EXTRACTION -- COMPLETE (%.1f s)", total_time)
    logger.info("=" * 60)
    if not holdings.empty:
        logger.info("  Total holding records: %d", len(holdings))
        if "cik" in holdings.columns:
            logger.info("  Unique CIKs with holdings: %d", holdings["cik"].nunique())
        if "issuer_name" in holdings.columns:
            logger.info("  Unique issuers: %d", holdings["issuer_name"].nunique())
        if "quarter" in holdings.columns:
            logger.info("  Quarters covered: %s", ", ".join(sorted(holdings["quarter"].unique())))
    else:
        logger.warning("  No holdings extracted")

    return holdings
