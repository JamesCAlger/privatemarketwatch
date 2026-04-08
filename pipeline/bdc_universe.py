"""BDC (Business Development Company) universe discovery.

Three complementary methods:
  A. N-54A / N-54C election filings (EFTS search)
  B. 814- file-number verification + XBRL concept scan
  C. SEC BDC bulk data set
"""

import csv
import io
import logging
from datetime import datetime

import pandas as pd

from pipeline.config import BDC_DATASET_URL, BDC_UNIVERSE_FILE, SEC_DATASETS_DIR
from pipeline.edgar_client import EdgarClient

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────
# Method A — N-54A / N-54C election filings
# ──────────────────────────────────────────────────────────────────────

def _search_election_filings(client: EdgarClient) -> pd.DataFrame:
    """Find BDC elections (N-54A) and withdrawals (N-54C) via EFTS."""

    # --- N-54A (election to be regulated as a BDC) ---
    logger.info("Searching for N-54A filings ...")
    n54a_hits = client.search_filings(form_type="N-54A", max_results=2000)
    elections: list[dict] = []
    for hit in n54a_hits:
        src = hit.get("_source", hit)
        elections.append({
            "cik": str(src.get("ciks", [src.get("cik", "")])[0] if isinstance(src.get("ciks"), list) else src.get("cik", "")),
            "entity_name": src.get("display_names", [src.get("entity_name", "")])[0] if isinstance(src.get("display_names"), list) else src.get("entity_name", ""),
            "file_date": src.get("file_date", src.get("filed", "")),
            "form_type": "N-54A",
            "file_num": src.get("file_num", ""),
        })
    logger.info("Found %d N-54A filings", len(elections))

    # --- N-54C (withdrawal of BDC election) ---
    logger.info("Searching for N-54C filings ...")
    n54c_hits = client.search_filings(form_type="N-54C", max_results=2000)
    withdrawals: list[dict] = []
    for hit in n54c_hits:
        src = hit.get("_source", hit)
        withdrawals.append({
            "cik": str(src.get("ciks", [src.get("cik", "")])[0] if isinstance(src.get("ciks"), list) else src.get("cik", "")),
            "entity_name": src.get("display_names", [src.get("entity_name", "")])[0] if isinstance(src.get("display_names"), list) else src.get("entity_name", ""),
            "file_date": src.get("file_date", src.get("filed", "")),
            "form_type": "N-54C",
        })
    logger.info("Found %d N-54C filings", len(withdrawals))

    df_elect = pd.DataFrame(elections)
    df_withdraw = pd.DataFrame(withdrawals)

    if df_elect.empty:
        logger.warning("No N-54A filings found — EFTS may be down or format changed")
        return pd.DataFrame(columns=["cik", "entity_name", "election_date",
                                      "withdrawal_date", "status"])

    # Determine active vs withdrawn
    # For each CIK, get the latest election and latest withdrawal
    df_elect["file_date"] = pd.to_datetime(df_elect["file_date"], errors="coerce")
    latest_election = (
        df_elect.sort_values("file_date")
        .groupby("cik", as_index=False)
        .last()
        .rename(columns={"file_date": "election_date", "file_num": "file_number"})
    )

    if not df_withdraw.empty:
        df_withdraw["file_date"] = pd.to_datetime(df_withdraw["file_date"], errors="coerce")
        latest_withdrawal = (
            df_withdraw.sort_values("file_date")
            .groupby("cik", as_index=False)
            .last()
            .rename(columns={"file_date": "withdrawal_date"})
            [["cik", "withdrawal_date"]]
        )
        merged = latest_election.merge(latest_withdrawal, on="cik", how="left")
    else:
        merged = latest_election.copy()
        merged["withdrawal_date"] = pd.NaT

    merged["status"] = merged.apply(
        lambda r: "withdrawn"
        if pd.notna(r["withdrawal_date"])
        and (pd.isna(r["election_date"]) or r["withdrawal_date"] > r["election_date"])
        else "active",
        axis=1,
    )
    merged["discovery_method"] = "n54a_filing"
    result = merged[["cik", "entity_name", "election_date", "withdrawal_date",
                      "status", "file_number", "discovery_method"]].copy()
    logger.info("Method A: %d BDCs (%d active, %d withdrawn)",
                len(result),
                (result["status"] == "active").sum(),
                (result["status"] == "withdrawn").sum())
    return result


# ──────────────────────────────────────────────────────────────────────
# Method B — 814- file number verification
# ──────────────────────────────────────────────────────────────────────

def _verify_file_numbers(client: EdgarClient, ciks: list[str]) -> pd.DataFrame:
    """For each CIK, fetch submissions and verify 814- file number."""
    records: list[dict] = []
    for cik in ciks:
        try:
            data = client.get_company_submissions(cik)
            entity_name = data.get("name", "")
            file_numbers = []
            # filings are in data["filings"]["recent"]
            recent = data.get("filings", {}).get("recent", {})
            file_nums_list = recent.get("fileNumber", [])
            file_numbers = list(set(file_nums_list))

            is_814 = any(fn.startswith("814-") for fn in file_numbers)
            bdc_file_num = next((fn for fn in file_numbers if fn.startswith("814-")), None)
            records.append({
                "cik": cik,
                "entity_name": entity_name,
                "file_number": bdc_file_num,
                "has_814_file_number": is_814,
            })
        except Exception as exc:
            logger.warning("Could not fetch submissions for CIK %s: %s", cik, exc)
            records.append({
                "cik": cik,
                "entity_name": "",
                "file_number": None,
                "has_814_file_number": False,
            })

    df = pd.DataFrame(records)
    confirmed = df[df["has_814_file_number"]].copy()
    confirmed["discovery_method"] = "814_file_number"
    logger.info("Method B: %d / %d CIKs confirmed with 814- file number",
                len(confirmed), len(ciks))
    return confirmed


# ──────────────────────────────────────────────────────────────────────
# Method C — SEC BDC Bulk Data Set
# ──────────────────────────────────────────────────────────────────────

def _load_bdc_dataset(client: EdgarClient) -> pd.DataFrame:
    """Download and parse the SEC BDC data set ZIP."""
    dest = SEC_DATASETS_DIR / "bdc_data.zip"
    try:
        client.download_file(BDC_DATASET_URL, dest)
    except Exception as exc:
        logger.warning("Could not download BDC data set: %s", exc)
        # Try alternate months (same /structureddata/ path)
        alt_urls = [
            "https://www.sec.gov/files/structureddata/data/business-development-company-bdc-data-sets/2026_01_bdc.zip",
            "https://www.sec.gov/files/structureddata/data/business-development-company-bdc-data-sets/2025_12_bdc.zip",
        ]
        downloaded = False
        for alt in alt_urls:
            try:
                client.download_file(alt, dest)
                downloaded = True
                break
            except Exception:
                continue
        if not downloaded:
            logger.error("BDC data set unavailable — skipping Method C")
            return pd.DataFrame(columns=["cik", "entity_name", "discovery_method"])

    try:
        import zipfile
        with zipfile.ZipFile(dest) as zf:
            # Look for a SUB-like table (submissions) inside the ZIP
            names = zf.namelist()
            logger.info("BDC data set ZIP contents: %s", names)

            # Try to find the main data file
            target = None
            for name in names:
                lower = name.lower()
                if "sub" in lower and lower.endswith((".csv", ".tsv", ".txt")):
                    target = name
                    break
            if target is None:
                # Fall back to first CSV/TSV
                for name in names:
                    if name.lower().endswith((".csv", ".tsv", ".txt")):
                        target = name
                        break

            if target is None:
                logger.warning("No parseable file found in BDC data set ZIP")
                return pd.DataFrame(columns=["cik", "entity_name", "discovery_method"])

            with zf.open(target) as fh:
                # Try tab-separated first (SEC datasets often are TSV)
                content = fh.read().decode("utf-8", errors="replace")
                if "\t" in content[:2000]:
                    df = pd.read_csv(io.StringIO(content), sep="\t",
                                     dtype=str, on_bad_lines="skip")
                else:
                    df = pd.read_csv(io.StringIO(content), dtype=str,
                                     on_bad_lines="skip")

            # Normalise column names
            df.columns = [c.strip().lower().replace(" ", "_") for c in df.columns]

            # Extract CIK column
            cik_col = None
            for candidate in ["cik", "cik_number", "cik_num", "registrant_cik"]:
                if candidate in df.columns:
                    cik_col = candidate
                    break
            if cik_col is None:
                logger.warning("Could not identify CIK column in BDC data set. Columns: %s",
                               list(df.columns))
                return pd.DataFrame(columns=["cik", "entity_name", "discovery_method"])

            name_col = None
            for candidate in ["name", "entity_name", "company_name", "registrant_name",
                               "company", "registrant"]:
                if candidate in df.columns:
                    name_col = candidate
                    break

            result = pd.DataFrame({
                "cik": df[cik_col].astype(str).str.strip(),
                "entity_name": df[name_col].astype(str).str.strip() if name_col else "",
            })
            result = result.drop_duplicates(subset=["cik"])
            result["discovery_method"] = "bdc_dataset"
            logger.info("Method C: %d BDCs from SEC data set", len(result))
            return result

    except Exception as exc:
        logger.error("Error parsing BDC data set: %s", exc)
        return pd.DataFrame(columns=["cik", "entity_name", "discovery_method"])


# ──────────────────────────────────────────────────────────────────────
# Public entry point
# ──────────────────────────────────────────────────────────────────────

def build_bdc_universe(client: EdgarClient) -> pd.DataFrame:
    """Run all BDC discovery methods and merge into a single DataFrame.

    Returns a DataFrame with columns matching the combined_universe schema
    (vehicle_type = 'bdc').
    """
    logger.info("=" * 60)
    logger.info("BUILDING BDC UNIVERSE")
    logger.info("=" * 60)

    # Method A: N-54A / N-54C filings
    df_a = _search_election_filings(client)

    # Method B: Verify 814- file numbers for Method-A CIKs
    if not df_a.empty:
        df_b = _verify_file_numbers(client, df_a["cik"].unique().tolist())
    else:
        df_b = pd.DataFrame(columns=["cik", "entity_name", "file_number",
                                      "has_814_file_number", "discovery_method"])

    # Method C: BDC data set
    df_c = _load_bdc_dataset(client)

    # ── Merge all methods ──
    # Start with Method A as the base (has the most metadata)
    universe = df_a.copy() if not df_a.empty else pd.DataFrame()

    # Add CIKs from Method C not already in the universe
    if not df_c.empty:
        if universe.empty:
            universe = df_c.copy()
        else:
            new_from_c = df_c[~df_c["cik"].isin(universe["cik"])]
            if not new_from_c.empty:
                logger.info("%d new BDCs found only in SEC data set", len(new_from_c))
                universe = pd.concat([universe, new_from_c], ignore_index=True)

    if universe.empty:
        logger.warning("No BDCs found across any method!")
        return pd.DataFrame()

    # Build discovery_methods column
    method_a_ciks = set(df_a["cik"].tolist()) if not df_a.empty else set()
    method_b_ciks = set(df_b["cik"].tolist()) if not df_b.empty else set()
    method_c_ciks = set(df_c["cik"].tolist()) if not df_c.empty else set()

    def _get_methods(cik: str) -> str:
        methods = []
        if cik in method_a_ciks:
            methods.append("n54a_filing")
        if cik in method_b_ciks:
            methods.append("814_file_number")
        if cik in method_c_ciks:
            methods.append("bdc_dataset")
        return ",".join(methods) if methods else "unknown"

    universe["discovery_methods"] = universe["cik"].apply(_get_methods)

    # Update file_number from Method B where available
    if not df_b.empty:
        file_num_map = df_b.set_index("cik")["file_number"].to_dict()
        universe["file_number"] = universe.apply(
            lambda r: file_num_map.get(r["cik"], r.get("file_number")), axis=1
        )

    # Standardise columns for the combined schema
    universe["vehicle_type"] = "bdc"
    universe["series_id"] = None
    universe["fund_name"] = None
    universe["data_sources"] = "xbrl_10k,xbrl_10q"
    universe["adviser_name"] = None
    universe["total_net_assets"] = None
    universe["in_third_party_lists"] = ""

    # Ensure required columns exist with defaults
    for col in ["election_date", "withdrawal_date", "status", "file_number"]:
        if col not in universe.columns:
            universe[col] = None

    # Deduplicate by CIK
    universe = universe.drop_duplicates(subset=["cik"]).reset_index(drop=True)

    # Compute first/last filing dates (placeholder — will be enriched later)
    universe["first_filing_date"] = universe.get("election_date")
    universe["last_filing_date"] = None

    logger.info("BDC universe: %d entities total", len(universe))

    # Save intermediate output
    universe.to_csv(BDC_UNIVERSE_FILE, index=False)
    logger.info("Saved BDC universe to %s", BDC_UNIVERSE_FILE)

    return universe
