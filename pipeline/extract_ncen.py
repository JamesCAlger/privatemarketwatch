"""Cached N-CEN dataset parsing for fund financials."""

import logging
import zipfile

import pandas as pd

from pipeline.config import FUND_IDENTITY_FILE, NCEN_QUARTERS, SEC_DATASETS_DIR

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# B2. N-CEN financial data extraction
# ---------------------------------------------------------------------------

_NCEN_DATE_MONTHS = {
    "JAN": "01", "FEB": "02", "MAR": "03", "APR": "04",
    "MAY": "05", "JUN": "06", "JUL": "07", "AUG": "08",
    "SEP": "09", "OCT": "10", "NOV": "11", "DEC": "12",
}


def _parse_ncen_date(raw: str) -> str | None:
    """Convert N-CEN date '31-JUL-2025' to ISO '2025-07-31'."""
    if not raw or not isinstance(raw, str):
        return None
    parts = raw.strip().split("-")
    if len(parts) != 3:
        return None
    day, mon, year = parts
    month_num = _NCEN_DATE_MONTHS.get(mon.upper())
    if not month_num:
        return None
    return f"{year}-{month_num}-{day.zfill(2)}"


def _parse_ncen_financials(
    universe_ciks: set[str],
    sec_datasets_dir=SEC_DATASETS_DIR,
    ncen_quarters=NCEN_QUARTERS,
) -> pd.DataFrame:
    """Extract financial fields from cached N-CEN ZIPs for universe CIKs.

    N-CEN is filed annually by investment companies. FUND_REPORTED_INFO
    contains management fee (%), expense ratio (%), NAV per share, etc.
    Only N-2 registrants (closed-end funds) are extracted.

    Parameters
    ----------
    universe_ciks : set of str
        CIKs (10-digit padded) to include.

    Returns
    -------
    DataFrame with columns: cik, entity_name, report_date, report_quarter,
        management_fee_pct, expense_ratio_pct, nav_per_share,
        market_price_per_share, monthly_avg_net_assets.
    """
    empty_cols = [
        "cik", "entity_name", "report_date", "report_quarter",
        "management_fee_pct", "expense_ratio_pct", "nav_per_share",
        "market_price_per_share", "monthly_avg_net_assets",
        "is_debt_default", "is_dividend_arrears",
        "is_fund_of_fund", "is_non_diversified",
    ]
    if not universe_ciks:
        return pd.DataFrame(columns=empty_cols)

    all_rows: list[dict] = []

    for quarter in ncen_quarters:
        year, q = quarter[:4], quarter[5:]
        zip_path = sec_datasets_dir / f"{year}q{q}_ncen.zip"
        if not zip_path.exists():
            continue

        try:
            with zipfile.ZipFile(zip_path) as zf:
                names = zf.namelist()
                if ("FUND_REPORTED_INFO.tsv" not in names
                        or "SUBMISSION.tsv" not in names):
                    continue

                def _read_tsv(filename: str) -> pd.DataFrame:
                    with zf.open(filename) as fh:
                        return pd.read_csv(
                            fh, sep="\t", dtype=str, on_bad_lines="skip",
                        )

                fri = _read_tsv("FUND_REPORTED_INFO.tsv")
                sub = _read_tsv("SUBMISSION.tsv")

                reg = None
                if "REGISTRANT.tsv" in names:
                    reg = _read_tsv("REGISTRANT.tsv")

                # Join FRI -> SUBMISSION for CIK + report date
                if "ACCESSION_NUMBER" not in fri.columns:
                    continue
                merged = fri.merge(
                    sub[["ACCESSION_NUMBER", "CIK", "REPORT_ENDING_PERIOD"]],
                    on="ACCESSION_NUMBER", how="left",
                )

                # Join -> REGISTRANT for name + company type filter
                if (reg is not None
                        and "INVESTMENT_COMPANY_TYPE" in reg.columns):
                    reg_cols = ["ACCESSION_NUMBER", "REGISTRANT_NAME",
                                "INVESTMENT_COMPANY_TYPE"]
                    reg_cols = [c for c in reg_cols if c in reg.columns]
                    merged = merged.merge(
                        reg[reg_cols], on="ACCESSION_NUMBER", how="left",
                    )
                else:
                    continue  # Can't filter to N-2 without company type

                # Filter to N-2 registrants
                if "INVESTMENT_COMPANY_TYPE" not in merged.columns:
                    continue
                merged = merged[
                    merged["INVESTMENT_COMPANY_TYPE"] == "N-2"
                ]

                if merged.empty:
                    continue

                # Filter to universe CIKs
                merged["cik_padded"] = (
                    merged["CIK"].str.strip().str.zfill(10)
                )
                merged = merged[merged["cik_padded"].isin(universe_ciks)]

                if merged.empty:
                    continue

                for _, row in merged.iterrows():
                    report_date = _parse_ncen_date(
                        row.get("REPORT_ENDING_PERIOD", ""),
                    )
                    if not report_date:
                        continue

                    cik = row["cik_padded"]
                    entity_name = str(
                        row.get("REGISTRANT_NAME", "")
                    ).strip()

                    # Parse date to derive quarter
                    try:
                        month = int(report_date.split("-")[1])
                        year_str = report_date.split("-")[0]
                        q_num = (month - 1) // 3 + 1
                        report_quarter = f"{year_str}q{q_num}"
                    except (ValueError, IndexError):
                        continue

                    def _to_float(val):
                        if val is None or str(val).strip() in ("", "nan"):
                            return None
                        try:
                            return float(val)
                        except (ValueError, TypeError):
                            return None

                    all_rows.append({
                        "cik": cik,
                        "entity_name": entity_name,
                        "report_date": report_date,
                        "report_quarter": report_quarter,
                        "management_fee_pct": _to_float(
                            row.get("MANAGEMENT_FEE"),
                        ),
                        "expense_ratio_pct": _to_float(
                            row.get("NET_OPERATING_EXPENSES"),
                        ),
                        "nav_per_share": _to_float(
                            row.get("NAV_PER_SHARE"),
                        ),
                        "market_price_per_share": _to_float(
                            row.get("MARKET_PRICE_PER_SHARE"),
                        ),
                        "monthly_avg_net_assets": _to_float(
                            row.get("MONTHLY_AVG_NET_ASSETS"),
                        ),
                        "is_debt_default": (
                            str(row.get("IS_LONG_TERM_DEBT_DEFAULT", ""))
                            .strip().upper() == "Y"
                        ),
                        "is_dividend_arrears": (
                            str(row.get(
                                "IS_ACCUM_DIVIDEND_IN_ARREARS", ""))
                            .strip().upper() == "Y"
                        ),
                        "is_fund_of_fund": (
                            str(row.get("IS_FUND_OF_FUND", ""))
                            .strip().upper() == "Y"
                        ),
                        "is_non_diversified": (
                            str(row.get("IS_NON_DIVERSIFIED", ""))
                            .strip().upper() == "Y"
                        ),
                    })
        except (zipfile.BadZipFile, OSError) as exc:
            logger.warning("Failed to read %s: %s", zip_path.name, exc)
            continue

    if not all_rows:
        return pd.DataFrame(columns=empty_cols)

    df = pd.DataFrame(all_rows)

    # Dedup by (cik, report_date), keep first occurrence
    df = df.drop_duplicates(subset=["cik", "report_date"], keep="first")

    # ----- Guard rails for N-CEN data quality -----
    # 1. Negative management_fee_pct -> 0 (fee waivers)
    neg_fee = (df["management_fee_pct"] < 0).sum()
    if neg_fee:
        logger.info("N-CEN: clamped %d negative management_fee_pct to 0", neg_fee)
        df.loc[df["management_fee_pct"] < 0, "management_fee_pct"] = 0.0

    # 2. Expense ratio > 20% -> NULL (dollar value filed as pct, or stub)
    high_exp = (df["expense_ratio_pct"] > 20).sum()
    if high_exp:
        logger.info("N-CEN: nulled %d expense_ratio_pct > 20%%", high_exp)
        df.loc[df["expense_ratio_pct"] > 20, "expense_ratio_pct"] = None

    # 3. Zero NAV per share -> NULL (not yet launched or error)
    zero_nav = (df["nav_per_share"] == 0).sum()
    if zero_nav:
        logger.info("N-CEN: nulled %d zero nav_per_share", zero_nav)
        df.loc[df["nav_per_share"] == 0, "nav_per_share"] = None

    # 4. Zero market_price_per_share -> NULL (non-listed funds)
    zero_mkt = (df["market_price_per_share"] == 0).sum()
    if zero_mkt:
        logger.info(
            "N-CEN: nulled %d zero market_price_per_share", zero_mkt,
        )
        df.loc[df["market_price_per_share"] == 0,
               "market_price_per_share"] = None

    return df


# ---------------------------------------------------------------------------
# B2b. N-CEN identity extraction (adviser, ticker)
# ---------------------------------------------------------------------------

_IDENTITY_COLUMNS = [
    "cik", "entity_name", "adviser_name", "adviser_crd_number",
    "ticker", "class_name",
]


def _parse_ncen_identity(
    universe_ciks: set[str],
    sec_datasets_dir=SEC_DATASETS_DIR,
    ncen_quarters=NCEN_QUARTERS,
    fund_identity_file=FUND_IDENTITY_FILE,
) -> pd.DataFrame:
    """Extract fund identity from N-CEN ADVISER and SHARES_OUTSTANDING tables.

    Returns one row per CIK with the latest available identity fields.
    Saved to ``fund_identity.csv``.

    Parameters
    ----------
    universe_ciks : set of str
        CIKs (10-digit padded) to include.

    Returns
    -------
    DataFrame with columns: cik, entity_name, adviser_name,
        adviser_crd_number, ticker, class_name.
    """
    if not universe_ciks:
        return pd.DataFrame(columns=_IDENTITY_COLUMNS)

    all_rows: list[dict] = []

    for quarter in ncen_quarters:
        year, q = quarter[:4], quarter[5:]
        zip_path = sec_datasets_dir / f"{year}q{q}_ncen.zip"
        if not zip_path.exists():
            continue

        try:
            with zipfile.ZipFile(zip_path) as zf:
                names = zf.namelist()
                if "SUBMISSION.tsv" not in names:
                    continue

                def _read_tsv(filename: str) -> pd.DataFrame:
                    with zf.open(filename) as fh:
                        return pd.read_csv(
                            fh, sep="\t", dtype=str, on_bad_lines="skip",
                        )

                sub = _read_tsv("SUBMISSION.tsv")

                reg = None
                if "REGISTRANT.tsv" in names:
                    reg = _read_tsv("REGISTRANT.tsv")

                if reg is None or "INVESTMENT_COMPANY_TYPE" not in reg.columns:
                    continue

                # Filter to N-2 registrants in universe
                merged_sub = sub[["ACCESSION_NUMBER", "CIK"]].copy()
                merged_sub["cik_padded"] = (
                    merged_sub["CIK"].str.strip().str.zfill(10)
                )
                merged_sub = merged_sub[
                    merged_sub["cik_padded"].isin(universe_ciks)
                ]
                if merged_sub.empty:
                    continue

                acc_set = set(merged_sub["ACCESSION_NUMBER"].unique())

                # N-2 filter
                reg_n2 = reg[reg["INVESTMENT_COMPANY_TYPE"] == "N-2"]
                n2_accs = set(reg_n2["ACCESSION_NUMBER"].unique())
                acc_set = acc_set & n2_accs
                if not acc_set:
                    continue

                # ADVISER table (joins via FUND_ID which embeds
                # accession number as first component)
                adviser_name = {}
                adviser_crd = {}
                if "ADVISER.tsv" in names:
                    adv = _read_tsv("ADVISER.tsv")
                    if not adv.empty and "FUND_ID" in adv.columns:
                        # Extract accession from FUND_ID
                        adv["_acc"] = (
                            adv["FUND_ID"]
                            .str.split("_")
                            .str[0]
                        )
                        adv = adv[adv["_acc"].isin(acc_set)]
                        for _, row in adv.iterrows():
                            acc = row.get("_acc", "")
                            name = str(
                                row.get("ADVISER_NAME", ""),
                            ).strip()
                            crd = str(
                                row.get("CRD_NUM", ""),
                            ).strip()
                            if acc and name and name != "nan":
                                adviser_name[acc] = name
                            if acc and crd and crd != "nan":
                                adviser_crd[acc] = crd

                # SHARES_OUTSTANDING table (has TICKER,
                # joins via FUND_ID)
                ticker_map = {}
                class_map = {}
                if "SHARES_OUTSTANDING.tsv" in names:
                    so = _read_tsv("SHARES_OUTSTANDING.tsv")
                    if not so.empty and "FUND_ID" in so.columns:
                        so["_acc"] = (
                            so["FUND_ID"]
                            .str.split("_")
                            .str[0]
                        )
                        so = so[so["_acc"].isin(acc_set)]
                        for _, row in so.iterrows():
                            acc = row.get("_acc", "")
                            tkr = str(row.get("TICKER", "")).strip()
                            cls = str(
                                row.get("CLASS_NAME", ""),
                            ).strip()
                            if acc and tkr and tkr != "nan":
                                ticker_map[acc] = tkr
                            if acc and cls and cls != "nan":
                                class_map[acc] = cls

                # Registrant name
                reg_name_map = {}
                if "REGISTRANT_NAME" in reg.columns:
                    for _, row in reg_n2.iterrows():
                        acc = row.get("ACCESSION_NUMBER", "")
                        if acc in acc_set:
                            rname = str(
                                row.get("REGISTRANT_NAME", ""),
                            ).strip()
                            if rname:
                                reg_name_map[acc] = rname

                # Build identity rows by CIK
                for _, srow in merged_sub.iterrows():
                    acc = srow["ACCESSION_NUMBER"]
                    if acc not in acc_set:
                        continue
                    cik = srow["cik_padded"]
                    all_rows.append({
                        "cik": cik,
                        "entity_name": reg_name_map.get(acc, ""),
                        "adviser_name": adviser_name.get(acc, ""),
                        "adviser_crd_number": adviser_crd.get(acc, ""),
                        "ticker": ticker_map.get(acc, ""),
                        "class_name": class_map.get(acc, ""),
                    })

        except (zipfile.BadZipFile, OSError) as exc:
            logger.warning("N-CEN identity: failed %s: %s",
                           zip_path.name, exc)
            continue

    if not all_rows:
        return pd.DataFrame(columns=_IDENTITY_COLUMNS)

    df = pd.DataFrame(all_rows)

    # Keep latest per CIK (later quarters override earlier)
    df = df.drop_duplicates(subset=["cik"], keep="last")

    # Save to disk
    df.to_csv(fund_identity_file, index=False)
    logger.info("Fund identity: %d CIKs saved to %s",
                len(df), fund_identity_file.name)

    return df


