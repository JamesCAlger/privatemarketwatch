"""Interval fund and tender offer fund universe discovery.

Six methods (exhaustive mode):
  A. N-CEN classification — multi-quarter census (2022q1–2025q4)
  B. Exhaustive N-2 quarterly index scan (2015–now) with cover page parsing
  C. EFTS full-text search across ALL form types (interval/tender terms)
  D. XBRL company facts — IntervalFundFlag concept
  E. Third-party list seeding (interval_fund_tracker + tender_offer_funds)
  F. Activity confirmation (N-PORT/N-CEN/N-CSR filing recency)

Plus original safety-net N-PORT data set scan (retained as final catch-all).
"""

import io
import logging
import re
import time
import zipfile
from datetime import datetime, timedelta
from typing import Any

import pandas as pd

from pipeline.config import (
    ACTIVITY_LOOKBACK_MONTHS,
    EFTS_INTERVAL_QUERIES,
    EFTS_TENDER_QUERIES,
    EXHAUSTIVE_FUND_UNIVERSE_FILE,
    FUND_UNIVERSE_FILE,
    INDEX_SCAN_START_YEAR,
    N2_HEADERS_CACHE_DIR,
    NCEN_DATASET_URL,
    NCEN_QUARTERS,
    NPORT_DATASET_URL,
    SEC_DATASETS_DIR,
    THIRD_PARTY_DIR,
)
from pipeline.edgar_client import EdgarClient

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────
# Helpers — N-2 checkbox parsing (shared between old Method B and new)
# ──────────────────────────────────────────────────────────────────────

def _parse_n2_checkboxes(html: str) -> dict[str, bool]:
    """Parse N-2 cover page checkboxes from HTML content.

    N-2 cover pages contain Unicode checkbox characters:
      ☒ (U+2612, &#9746;) = checked
      ☑ (U+2611, &#9745;) = checked
      ☐ (U+2610, &#9744;) = unchecked

    The modern N-2 form has these cover page checkboxes:
      - Registered Closed-End Fund
      - Business Development Company
      - Interval Fund (Rule 23c-3)

    Note: There is NO "Tender Offer" checkbox on the N-2 form.
    Tender offer funds are identified via text analysis (see _has_tender_offer_structure).

    Returns dict with boolean values for: closed_end, bdc, interval
    """
    text = html[:80_000]

    for entity, char in [
        ("&#9746;", "\u2612"), ("&#9745;", "\u2611"), ("&#9744;", "\u2610"),
        ("&#x2612;", "\u2612"), ("&#x2611;", "\u2611"), ("&#x2610;", "\u2610"),
    ]:
        text = text.replace(entity, char)

    clean = re.sub(r"<[^>]+>", " ", text)
    clean = re.sub(r"&[a-zA-Z]+;", " ", clean)
    clean = re.sub(r"\s+", " ", clean)

    result = {"closed_end": False, "bdc": False, "interval": False}

    checkbox_re = re.compile(r"([\u2612\u2611\u2610]|\[[Xx ]\])")
    matches = list(checkbox_re.finditer(clean))

    for i, m in enumerate(matches):
        char = m.group(1)
        is_checked = char in ("\u2612", "\u2611", "[X]", "[x]")
        if not is_checked:
            continue

        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else start + 300
        label = clean[start:end]

        if re.search(r"interval\s+fund", label, re.IGNORECASE):
            result["interval"] = True
        elif re.search(r"registered\s+closed.end", label, re.IGNORECASE):
            result["closed_end"] = True
        elif re.search(r"business\s+development", label, re.IGNORECASE):
            result["bdc"] = True

    return result


def _has_tender_offer_structure(html: str) -> bool:
    """Check if an N-2 filing indicates a tender offer fund structure."""
    text = html[:200_000]
    clean = re.sub(r"<[^>]+>", " ", text)
    clean = re.sub(r"&[a-zA-Z]+;", " ", clean)
    clean = re.sub(r"\s+", " ", clean)

    patterns = [
        r"tender\s+offer\s+fund",
        r"periodic\s+tender\s+offer",
        r"quarterly\s+tender\s+offer",
        r"semi.annual\s+tender\s+offer",
        r"annual\s+tender\s+offer",
        r"(?:intends?|will|shall|may)\s+(?:to\s+)?(?:make|conduct|commence)"
        r".{0,50}tender\s+offer",
        r"repurchase.{0,30}tender\s+offer",
    ]

    for pat in patterns:
        if re.search(pat, clean, re.IGNORECASE):
            return True
    return False


def _find_col(df: pd.DataFrame, candidates: list[str]) -> str | None:
    """Return the first matching column name from candidates."""
    cols_lower = {c.lower(): c for c in df.columns}
    for candidate in candidates:
        if candidate.lower() in cols_lower:
            return cols_lower[candidate.lower()]
        for col_lower, col_orig in cols_lower.items():
            if candidate.lower() in col_lower:
                return col_orig
    return None


def _extract_cik_from_hit(hit: dict) -> str:
    """Extract CIK string from an EFTS search hit."""
    src = hit.get("_source", hit)
    ciks = src.get("ciks", [])
    if isinstance(ciks, list) and ciks:
        return str(ciks[0])
    return str(src.get("cik", ""))


def _extract_name_from_hit(hit: dict) -> str:
    """Extract entity name from an EFTS search hit."""
    src = hit.get("_source", hit)
    names = src.get("display_names", [])
    if isinstance(names, list) and names:
        return str(names[0])
    return str(src.get("entity_name", ""))


# ──────────────────────────────────────────────────────────────────────
# N-2 header caching helpers
# ──────────────────────────────────────────────────────────────────────

def _get_cached_n2(cik: str, accession: str) -> str | None:
    """Return cached N-2 HTML header text, or None if not cached."""
    safe_acc = accession.replace("/", "_").replace("\\", "_")
    path = N2_HEADERS_CACHE_DIR / f"{cik}_{safe_acc}.html"
    if path.exists():
        try:
            return path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            return None
    return None


def _cache_n2(cik: str, accession: str, html: str) -> None:
    """Write N-2 HTML header text to cache."""
    safe_acc = accession.replace("/", "_").replace("\\", "_")
    path = N2_HEADERS_CACHE_DIR / f"{cik}_{safe_acc}.html"
    try:
        path.write_text(html, encoding="utf-8")
    except Exception as exc:
        logger.debug("Could not cache N-2 for CIK %s: %s", cik, exc)


# ──────────────────────────────────────────────────────────────────────
# Method A — Multi-quarter N-CEN classification (PRIMARY)
# ──────────────────────────────────────────────────────────────────────

def _load_ncen_multi_quarter(client: EdgarClient) -> pd.DataFrame:
    """Download and parse N-CEN data across multiple quarters.

    Loops through NCEN_QUARTERS (16 quarters from 2022q1 to 2025q4),
    extracts IS_INTERVAL=Y funds, and unions results. Keeps the most
    recent quarter's data per (cik, series_id).
    """
    logger.info("Method A: Multi-quarter N-CEN scan (%d quarters) ...",
                len(NCEN_QUARTERS))

    all_records: list[dict] = []

    for quarter in NCEN_QUARTERS:
        url = (
            f"https://www.sec.gov/files/dera/data/"
            f"form-n-cen-data-sets/{quarter}_ncen.zip"
        )
        dest = SEC_DATASETS_DIR / f"{quarter}_ncen.zip"

        # Download (skip silently if 404)
        if not dest.exists():
            try:
                client.download_file(url, dest)
            except Exception:
                logger.debug("N-CEN quarter %s not available, skipping", quarter)
                continue

        # Parse the ZIP
        try:
            records = _parse_ncen_zip(dest, quarter)
            all_records.extend(records)
            logger.info("  %s: %d interval funds", quarter, len(records))
        except Exception as exc:
            logger.warning("  %s: parse error — %s", quarter, exc)

    if not all_records:
        logger.warning("No interval funds found across any N-CEN quarter")
        return _ncen_via_efts(client)

    df = pd.DataFrame(all_records)

    # Deduplicate by (cik, series_id), keeping the most recent quarter
    df = df.sort_values("quarter", ascending=False)
    dedup_cols = ["cik"]
    if "series_id" in df.columns:
        dedup_cols.append("series_id")
    df = df.drop_duplicates(subset=dedup_cols, keep="first")
    df = df.drop(columns=["quarter"], errors="ignore")

    logger.info("Method A (N-CEN multi-quarter): %d unique interval/tender funds",
                len(df))
    return df


def _parse_ncen_zip(zip_path: Any, quarter: str) -> list[dict]:
    """Parse a single N-CEN quarterly ZIP for IS_INTERVAL=Y funds."""
    with zipfile.ZipFile(zip_path) as zf:
        names = zf.namelist()

        def _read_tsv(filename: str) -> pd.DataFrame:
            with zf.open(filename) as fh:
                return pd.read_csv(fh, sep="\t", dtype=str, on_bad_lines="skip")

        if "FUND_REPORTED_INFO.tsv" not in names:
            return []
        if "SUBMISSION.tsv" not in names:
            return []

        fri = _read_tsv("FUND_REPORTED_INFO.tsv")
        sub = _read_tsv("SUBMISSION.tsv")

        # REGISTRANT is optional (for name)
        reg = None
        if "REGISTRANT.tsv" in names:
            reg = _read_tsv("REGISTRANT.tsv")

        # Adviser is optional
        adv = None
        if "ADVISER.tsv" in names:
            adv = _read_tsv("ADVISER.tsv")

        if "IS_INTERVAL" not in fri.columns:
            return []

        interval_mask = fri["IS_INTERVAL"].str.upper().eq("Y")
        interval_funds = fri[interval_mask].copy()

        if interval_funds.empty:
            return []

        # Join with SUBMISSION for CIK
        merged = interval_funds.merge(
            sub[["ACCESSION_NUMBER", "CIK"]],
            on="ACCESSION_NUMBER", how="left",
        )

        # Join with REGISTRANT for name
        if reg is not None and "REGISTRANT_NAME" in reg.columns:
            reg_cols = ["ACCESSION_NUMBER", "REGISTRANT_NAME"]
            if "INVESTMENT_COMPANY_TYPE" in reg.columns:
                reg_cols.append("INVESTMENT_COMPANY_TYPE")
            merged = merged.merge(reg[reg_cols], on="ACCESSION_NUMBER", how="left")

        # Join with ADVISER
        if (adv is not None and "ADVISER_NAME" in adv.columns
                and "FUND_ID" in adv.columns and "FUND_ID" in merged.columns):
            adv_valid = adv[adv["FUND_ID"].notna() & (adv["FUND_ID"].str.strip() != "")]
            first_adv = adv_valid.drop_duplicates(subset=["FUND_ID"], keep="first")
            merged = merged.merge(
                first_adv[["FUND_ID", "ADVISER_NAME"]],
                on="FUND_ID", how="left",
            )

        records: list[dict] = []
        for _, row in merged.iterrows():
            cik = str(row.get("CIK", "")).strip()
            if not cik or cik == "nan":
                continue
            records.append({
                "cik": cik,
                "entity_name": str(row.get("REGISTRANT_NAME", "")).strip()
                    if "REGISTRANT_NAME" in merged.columns else "",
                "series_id": str(row.get("SERIES_ID", "")).strip()
                    if "SERIES_ID" in merged.columns else "",
                "fund_name": str(row.get("FUND_NAME", "")).strip()
                    if "FUND_NAME" in merged.columns else "",
                "adviser_name": str(row.get("ADVISER_NAME", "")).strip()
                    if "ADVISER_NAME" in merged.columns else None,
                "vehicle_type": "interval_fund",
                "discovery_method": "ncen_classification",
                "quarter": quarter,
            })

        return records


def _ncen_via_efts(client: EdgarClient) -> pd.DataFrame:
    """Fallback: search for N-CEN filings via EFTS and extract fund type info."""
    logger.info("Falling back to EFTS search for N-CEN filers ...")
    hits = client.search_filings(form_type="N-CEN", max_results=500)
    records: list[dict] = []
    seen_ciks: set[str] = set()
    for hit in hits:
        cik = _extract_cik_from_hit(hit)
        if cik in seen_ciks:
            continue
        seen_ciks.add(cik)
        records.append({
            "cik": cik,
            "entity_name": _extract_name_from_hit(hit),
            "series_id": None,
            "fund_name": None,
            "adviser_name": None,
            "vehicle_type": "unknown_fund",
            "discovery_method": "ncen_efts_search",
        })
    logger.info("EFTS fallback: %d N-CEN filers found", len(records))
    return pd.DataFrame(records)


# ──────────────────────────────────────────────────────────────────────
# Method B — Exhaustive N-2 quarterly index scan
# ──────────────────────────────────────────────────────────────────────

def _exhaustive_n2_scan(client: EdgarClient) -> pd.DataFrame:
    """Scan all quarterly indices for N-2 filings, then parse cover pages.

    1. client.scan_quarterly_indices() → all N-2 filings since 2015
    2. Group by CIK, keep latest filing per CIK
    3. For each CIK: resolve URL, download partial, parse checkboxes
    4. Classify as interval / tender / skip
    """
    logger.info("Method B: Exhaustive N-2 index scan (since %d) ...",
                INDEX_SCAN_START_YEAR)

    # Step 1: Scan quarterly indices
    all_filings = client.scan_quarterly_indices(since_year=INDEX_SCAN_START_YEAR)
    logger.info("  Total N-2 filings found: %d", len(all_filings))

    if not all_filings:
        logger.warning("  No N-2 filings found in quarterly indices")
        return pd.DataFrame()

    # Step 2: Group by CIK, keep latest filing per CIK
    filings_df = pd.DataFrame(all_filings)
    filings_df = filings_df.sort_values("filing_date", ascending=False)
    latest_per_cik = filings_df.drop_duplicates(subset=["cik"], keep="first")
    logger.info("  Unique N-2 filers: %d", len(latest_per_cik))

    # Step 3 & 4: Resolve, download, parse
    records: list[dict] = []
    parsed_count = 0
    interval_count = 0
    tender_count = 0
    bdc_count = 0
    cef_count = 0
    no_checkbox_count = 0
    skipped = 0

    for idx, row in latest_per_cik.iterrows():
        cik = str(row["cik"])
        name = str(row["company_name"])
        accession = str(row["accession_number"])
        filing_date = str(row["filing_date"])

        # Progress logging
        total_done = parsed_count + skipped + bdc_count + cef_count + no_checkbox_count
        if total_done > 0 and total_done % 50 == 0:
            logger.info("  Progress: %d / %d CIKs processed (%d interval, %d tender)",
                        total_done, len(latest_per_cik), interval_count, tender_count)

        # Check cache first
        html = _get_cached_n2(cik, accession)

        if html is None:
            # Resolve filing document URL
            doc_url = client.resolve_filing_document_url(cik, accession)
            if not doc_url:
                skipped += 1
                continue
            if doc_url.lower().endswith(".pdf"):
                skipped += 1
                continue

            # Download partial (first 150KB)
            html = client.download_partial(doc_url)
            if html is None:
                skipped += 1
                continue

            # Cache it
            _cache_n2(cik, accession, html)

        # Parse checkboxes
        try:
            checkboxes = _parse_n2_checkboxes(html)
            parsed_count += 1

            has_any_checkbox = any(checkboxes.values())

            if has_any_checkbox:
                if checkboxes["bdc"] and not checkboxes["interval"]:
                    bdc_count += 1
                    continue
                if checkboxes["interval"]:
                    vehicle_type = "interval_fund"
                    interval_count += 1
                elif checkboxes["closed_end"]:
                    if _has_tender_offer_structure(html):
                        vehicle_type = "tender_offer_fund"
                        tender_count += 1
                    else:
                        cef_count += 1
                        continue
                else:
                    no_checkbox_count += 1
                    continue
            else:
                # No modern checkboxes — text-based fallback
                clean_lower = re.sub(r"<[^>]+>", " ", html[:200_000])
                clean_lower = re.sub(r"\s+", " ", clean_lower).lower()

                if "business development company" in clean_lower:
                    bdc_count += 1
                    continue
                if re.search(r"interval\s+fund", clean_lower):
                    vehicle_type = "interval_fund"
                    interval_count += 1
                elif _has_tender_offer_structure(html):
                    vehicle_type = "tender_offer_fund"
                    tender_count += 1
                else:
                    no_checkbox_count += 1
                    continue

            records.append({
                "cik": cik,
                "entity_name": name,
                "series_id": None,
                "fund_name": None,
                "vehicle_type": vehicle_type,
                "discovery_method": "n2_index_scan",
                "n2_filing_date": filing_date,
                "n2_accession_number": accession,
            })

        except Exception as exc:
            logger.debug("Could not parse N-2 for CIK %s: %s", cik, exc)
            skipped += 1

    logger.info(
        "  N-2 index scan results: %d parsed | %d interval | %d tender offer | "
        "%d BDC (skipped) | %d regular CEF (skipped) | %d no checkboxes | %d skipped",
        parsed_count, interval_count, tender_count,
        bdc_count, cef_count, no_checkbox_count, skipped,
    )

    result = pd.DataFrame(records)
    if not result.empty:
        result = result.drop_duplicates(subset=["cik"], keep="first")

    logger.info("Method B: %d interval/tender funds from N-2 index scan", len(result))
    return result


# ──────────────────────────────────────────────────────────────────────
# Method C — EFTS full-text search across all form types
# ──────────────────────────────────────────────────────────────────────

def _efts_text_search(client: EdgarClient) -> pd.DataFrame:
    """Search EFTS for interval/tender fund terms across ALL form types.

    Catches funds that self-describe as interval/tender in N-CSR, prospectus
    supplements, shareholder reports — even if their N-2 checkbox is wrong.
    """
    logger.info("Method C: EFTS full-text search ...")

    records: list[dict] = []
    seen_ciks: set[str] = set()

    # Interval fund queries
    for query in EFTS_INTERVAL_QUERIES:
        try:
            hits = client.search_filings(query=query, max_results=500)
            new_count = 0
            for hit in hits:
                cik = _extract_cik_from_hit(hit)
                if not cik or cik in seen_ciks:
                    continue
                seen_ciks.add(cik)
                records.append({
                    "cik": cik,
                    "entity_name": _extract_name_from_hit(hit),
                    "series_id": None,
                    "fund_name": None,
                    "vehicle_type": "interval_fund",
                    "discovery_method": "efts_text_search",
                })
                new_count += 1
            logger.info("  Query %s: %d hits, %d new CIKs", query, len(hits), new_count)
        except Exception as exc:
            logger.warning("  EFTS query %s failed: %s", query, exc)

    # Tender offer queries
    for query in EFTS_TENDER_QUERIES:
        try:
            hits = client.search_filings(query=query, max_results=500)
            new_count = 0
            for hit in hits:
                cik = _extract_cik_from_hit(hit)
                if not cik or cik in seen_ciks:
                    continue
                seen_ciks.add(cik)
                records.append({
                    "cik": cik,
                    "entity_name": _extract_name_from_hit(hit),
                    "series_id": None,
                    "fund_name": None,
                    "vehicle_type": "tender_offer_fund",
                    "discovery_method": "efts_text_search",
                })
                new_count += 1
            logger.info("  Query %s: %d hits, %d new CIKs", query, len(hits), new_count)
        except Exception as exc:
            logger.warning("  EFTS query %s failed: %s", query, exc)

    result = pd.DataFrame(records)
    if not result.empty:
        result = result.drop_duplicates(subset=["cik"], keep="first")

    logger.info("Method C: %d funds from EFTS text search", len(result))
    return result


# ──────────────────────────────────────────────────────────────────────
# Method D — XBRL company facts (IntervalFundFlag)
# ──────────────────────────────────────────────────────────────────────

def _xbrl_interval_fund_flags(client: EdgarClient) -> pd.DataFrame:
    """Scan XBRL frames API for IntervalFundFlag = true across all years."""
    logger.info("Method D: XBRL IntervalFundFlag scan ...")

    entries = client.scan_xbrl_interval_fund_flags()

    if not entries:
        logger.info("Method D: No XBRL interval fund flags found")
        return pd.DataFrame()

    records = [{
        "cik": str(e["cik"]),
        "entity_name": str(e.get("entity_name", "")),
        "series_id": None,
        "fund_name": None,
        "vehicle_type": "interval_fund",
        "discovery_method": "xbrl_company_facts",
    } for e in entries]

    result = pd.DataFrame(records)
    if not result.empty:
        result = result.drop_duplicates(subset=["cik"], keep="first")

    logger.info("Method D: %d funds from XBRL IntervalFundFlag", len(result))
    return result


# ──────────────────────────────────────────────────────────────────────
# Method E — Third-party list seeding
# ──────────────────────────────────────────────────────────────────────

def _seed_from_third_party(client: EdgarClient, known_ciks: set[str]) -> pd.DataFrame:
    """Read third-party CSVs and resolve unknown fund names to CIKs via EFTS.

    Only returns genuinely NEW CIKs not already in known_ciks.
    """
    logger.info("Method E: Third-party list seeding ...")

    records: list[dict] = []

    tp_sources = [
        (THIRD_PARTY_DIR / "interval_fund_tracker.csv", "interval_fund"),
        (THIRD_PARTY_DIR / "tender_offer_funds.csv", "tender_offer_fund"),
    ]

    for csv_path, vehicle_type in tp_sources:
        if not csv_path.exists():
            logger.info("  %s not found, skipping", csv_path.name)
            continue

        try:
            tp_df = pd.read_csv(csv_path, dtype=str)
        except Exception as exc:
            logger.warning("  Could not read %s: %s", csv_path.name, exc)
            continue

        # Find the fund name column
        name_col = None
        for c in tp_df.columns:
            if "name" in c.lower():
                name_col = c
                break

        if name_col is None:
            logger.warning("  No name column in %s", csv_path.name)
            continue

        logger.info("  Searching %d funds from %s ...",
                    len(tp_df), csv_path.name)

        new_count = 0
        for _, row in tp_df.iterrows():
            fund_name = str(row.get(name_col, "")).strip()
            if not fund_name or fund_name == "nan":
                continue

            # Search EFTS for this fund name
            try:
                hits = client.search_filings(query=f'"{fund_name}"', max_results=5)
            except Exception:
                continue

            for hit in hits:
                cik = _extract_cik_from_hit(hit)
                if not cik or cik in known_ciks:
                    continue

                known_ciks.add(cik)  # prevent duplicates within this method
                records.append({
                    "cik": cik,
                    "entity_name": _extract_name_from_hit(hit),
                    "series_id": None,
                    "fund_name": fund_name,
                    "vehicle_type": vehicle_type,
                    "discovery_method": "third_party_seed",
                })
                new_count += 1
                break  # one CIK per fund name

        logger.info("  %s: %d new CIKs discovered", csv_path.name, new_count)

    result = pd.DataFrame(records)
    if not result.empty:
        result = result.drop_duplicates(subset=["cik"], keep="first")

    logger.info("Method E: %d new funds from third-party seeding", len(result))
    return result


# ──────────────────────────────────────────────────────────────────────
# Method F — Activity confirmation
# ──────────────────────────────────────────────────────────────────────

# Periodic form types that indicate an active fund
_PERIODIC_FORMS = {
    "N-PORT", "N-PORT/A", "NPORT-P", "NPORT-P/A", "NPORT-EX", "NPORT-EX/A",
    "N-CEN", "N-CEN/A",
    "N-CSR", "N-CSR/A", "N-CSRS", "N-CSRS/A",
}


def _confirm_activity(client: EdgarClient, ciks: list[str]) -> pd.DataFrame:
    """For each CIK, check for recent periodic filings to classify activity.

    Returns DataFrame with columns: cik, activity_status,
    latest_periodic_filing_date, latest_periodic_filing_type.
    """
    logger.info("Method F: Activity confirmation for %d funds ...", len(ciks))

    cutoff_active = datetime.now() - timedelta(days=365)
    cutoff_inactive = datetime.now() - timedelta(
        days=ACTIVITY_LOOKBACK_MONTHS * 30
    )

    records: list[dict] = []
    active_count = 0
    possibly_count = 0
    inactive_count = 0

    for i, cik in enumerate(ciks):
        if i > 0 and i % 50 == 0:
            logger.info("  Activity check: %d / %d (%d active, %d possibly, %d inactive)",
                        i, len(ciks), active_count, possibly_count, inactive_count)

        latest_date = None
        latest_type = None

        try:
            data = client.get_company_submissions(cik)
            recent = data.get("filings", {}).get("recent", {})
            forms = recent.get("form", [])
            dates = recent.get("filingDate", [])

            for form, date_str in zip(forms, dates):
                if form and form.upper() in _PERIODIC_FORMS:
                    if latest_date is None or date_str > latest_date:
                        latest_date = date_str
                        latest_type = form
        except Exception as exc:
            logger.debug("Could not check activity for CIK %s: %s", cik, exc)

        if latest_date:
            try:
                dt = datetime.strptime(latest_date, "%Y-%m-%d")
            except ValueError:
                dt = datetime.min

            if dt >= cutoff_active:
                status = "active"
                active_count += 1
            elif dt >= cutoff_inactive:
                status = "possibly_inactive"
                possibly_count += 1
            else:
                status = "inactive"
                inactive_count += 1
        else:
            status = "inactive"
            inactive_count += 1

        records.append({
            "cik": cik,
            "activity_status": status,
            "latest_periodic_filing_date": latest_date,
            "latest_periodic_filing_type": latest_type,
        })

    logger.info("Method F: %d active, %d possibly inactive, %d inactive",
                active_count, possibly_count, inactive_count)
    return pd.DataFrame(records)


# ──────────────────────────────────────────────────────────────────────
# Safety-net N-PORT data set scan (original Method D, now final catch)
# ──────────────────────────────────────────────────────────────────────

def _scan_nport_dataset(client: EdgarClient, known_ciks: set[str]) -> pd.DataFrame:
    """Lightweight scan of N-PORT data set for filers with private-market holdings
    not already in our universe."""
    dest = SEC_DATASETS_DIR / "nport_data.zip"
    try:
        client.download_file(NPORT_DATASET_URL, dest)
    except Exception as exc:
        logger.warning("Could not download N-PORT data set: %s", exc)
        try:
            alt = "https://www.sec.gov/files/dera/data/form-n-port-data-sets/2025q3_nport.zip"
            client.download_file(alt, dest)
        except Exception:
            logger.error("N-PORT data set unavailable — skipping N-PORT safety net")
            return pd.DataFrame()

    try:
        with zipfile.ZipFile(dest) as zf:
            names = zf.namelist()
            logger.info("N-PORT ZIP contents: %s", [n for n in names[:20]])

            def _read_tsv(filename: str, **kwargs: Any) -> pd.DataFrame:
                with zf.open(filename) as fh:
                    return pd.read_csv(fh, sep="\t", dtype=str,
                                       on_bad_lines="skip", **kwargs)

            if "FUND_REPORTED_HOLDING.tsv" not in names:
                logger.warning("FUND_REPORTED_HOLDING.tsv not in N-PORT ZIP")
                return pd.DataFrame()
            if "REGISTRANT.tsv" not in names:
                logger.warning("REGISTRANT.tsv not in N-PORT ZIP")
                return pd.DataFrame()

            logger.info("Parsing N-PORT holdings (up to 500k rows) ...")
            holdings = _read_tsv("FUND_REPORTED_HOLDING.tsv", nrows=500_000)
            registrant = _read_tsv("REGISTRANT.tsv")

            mask = pd.Series(False, index=holdings.index)
            if "ISSUER_TYPE" in holdings.columns:
                mask |= holdings["ISSUER_TYPE"].str.contains(
                    "private|pvt|fund", case=False, na=False
                )
            if "ASSET_CAT" in holdings.columns:
                mask |= holdings["ASSET_CAT"].str.contains(
                    "LOAN|loan", case=False, na=False
                )

            if mask.sum() == 0:
                logger.info("No private-market holdings found in N-PORT scan")
                return pd.DataFrame()

            private_accessions = holdings.loc[mask, "ACCESSION_NUMBER"].unique()
            private_reg = registrant[
                registrant["ACCESSION_NUMBER"].isin(private_accessions)
            ]
            private_ciks = private_reg["CIK"].astype(str).str.strip().unique()

            new_filers = [c for c in private_ciks if c not in known_ciks]
            logger.info(
                "N-PORT safety net: %d filers with private holdings, %d new",
                len(private_ciks), len(new_filers),
            )

            if not new_filers:
                return pd.DataFrame()

            name_map = dict(zip(
                private_reg["CIK"].astype(str).str.strip(),
                private_reg["REGISTRANT_NAME"],
            ))
            records = [{
                "cik": cik,
                "entity_name": name_map.get(cik, ""),
                "series_id": None,
                "fund_name": None,
                "vehicle_type": "unknown_fund",
                "discovery_method": "nport_safety_net",
            } for cik in new_filers]

            return pd.DataFrame(records)

    except Exception as exc:
        logger.error("Error scanning N-PORT data set: %s", exc, exc_info=True)
        return pd.DataFrame()


# ──────────────────────────────────────────────────────────────────────
# Merge helper — combine discoveries from all methods
# ──────────────────────────────────────────────────────────────────────

def _merge_all_discoveries(*dfs: pd.DataFrame) -> pd.DataFrame:
    """Merge DataFrames from methods A-D, preferring N-CEN classification."""
    frames = [df for df in dfs if df is not None and not df.empty]
    if not frames:
        return pd.DataFrame()

    combined = pd.concat(frames, ignore_index=True)

    # Priority: ncen > n2_index_scan > efts_text_search > xbrl > others
    priority_map = {
        "ncen_classification": 0,
        "n2_index_scan": 1,
        "n2_checkbox": 1,
        "efts_text_search": 2,
        "xbrl_company_facts": 3,
        "ncen_efts_search": 4,
    }

    combined = combined.sort_values(
        "discovery_method",
        key=lambda s: s.map(priority_map).fillna(5),
    )

    dedup_cols = ["cik"]
    if "series_id" in combined.columns:
        dedup_cols.append("series_id")
    combined = combined.drop_duplicates(subset=dedup_cols, keep="first")

    return combined


# ──────────────────────────────────────────────────────────────────────
# Public entry point
# ──────────────────────────────────────────────────────────────────────

def build_fund_universe(client: EdgarClient, exhaustive: bool = False) -> pd.DataFrame:
    """Run all interval/tender fund discovery methods and merge.

    Parameters
    ----------
    client : EdgarClient
        Rate-limited HTTP client for SEC EDGAR.
    exhaustive : bool
        If True, run all 6 discovery methods (slower, ~45-60 min first run).
        If False, run the fast subset (Methods A + original B + N-PORT safety net).

    Returns a DataFrame matching the combined_universe schema.
    """
    logger.info("=" * 60)
    logger.info("BUILDING FUND UNIVERSE (Interval / Tender Offer)")
    logger.info("  Mode: %s", "EXHAUSTIVE (6 methods)" if exhaustive else "FAST (legacy)")
    logger.info("=" * 60)

    t_total = time.time()

    if not exhaustive:
        return _build_fund_universe_fast(client)

    # ── Method A: Multi-quarter N-CEN ──
    t0 = time.time()
    df_a = _load_ncen_multi_quarter(client)
    logger.info("Method A completed in %.1f s", time.time() - t0)

    # ── Method B: Exhaustive N-2 index scan ──
    t0 = time.time()
    df_b = _exhaustive_n2_scan(client)
    logger.info("Method B completed in %.1f s", time.time() - t0)

    # ── Method C: EFTS full-text search ──
    t0 = time.time()
    df_c = _efts_text_search(client)
    logger.info("Method C completed in %.1f s", time.time() - t0)

    # ── Method D: XBRL company facts ──
    t0 = time.time()
    df_d = _xbrl_interval_fund_flags(client)
    logger.info("Method D completed in %.1f s", time.time() - t0)

    # ── Merge A+B+C+D ──
    universe = _merge_all_discoveries(df_a, df_b, df_c, df_d)

    if universe.empty:
        logger.warning("No interval/tender funds found in Methods A-D")
        return pd.DataFrame()

    logger.info("After merging A+B+C+D: %d unique funds", len(universe))

    # ── Method E: Third-party list seeding ──
    t0 = time.time()
    known_ciks = set(universe["cik"].tolist())
    df_e = _seed_from_third_party(client, known_ciks)
    if not df_e.empty:
        universe = pd.concat([universe, df_e], ignore_index=True)
    logger.info("Method E completed in %.1f s", time.time() - t0)

    # ── Method F: Activity confirmation ──
    t0 = time.time()
    all_ciks = universe["cik"].unique().tolist()
    activity_df = _confirm_activity(client, all_ciks)
    universe = universe.merge(activity_df, on="cik", how="left")
    logger.info("Method F completed in %.1f s", time.time() - t0)

    # ── N-PORT safety net scan (final catch-all) ──
    t0 = time.time()
    known_ciks = set(universe["cik"].tolist())
    df_nport = _scan_nport_dataset(client, known_ciks)
    if not df_nport.empty:
        universe = pd.concat([universe, df_nport], ignore_index=True)
    logger.info("N-PORT safety net completed in %.1f s", time.time() - t0)

    # ── Build discovery_methods column (aggregate all methods per CIK) ──
    method_sets: dict[str, set[str]] = {}
    for df_label, df_data in [
        ("ncen_classification", df_a),
        ("n2_index_scan", df_b),
        ("efts_text_search", df_c),
        ("xbrl_company_facts", df_d),
        ("third_party_seed", df_e),
        ("nport_safety_net", df_nport),
    ]:
        if df_data is not None and not df_data.empty:
            for cik in df_data["cik"].unique():
                method_sets.setdefault(cik, set()).add(df_label)

    universe["discovery_methods"] = universe["cik"].apply(
        lambda c: ",".join(sorted(method_sets.get(c, {"unknown"})))
    )

    # Data sources
    universe["data_sources"] = universe.apply(
        lambda row: ",".join(filter(None, [
            "ncen" if "ncen" in str(row.get("discovery_methods", "")) else None,
            "n2" if "n2" in str(row.get("discovery_methods", "")) else None,
            "efts" if "efts" in str(row.get("discovery_methods", "")) else None,
            "xbrl" if "xbrl" in str(row.get("discovery_methods", "")) else None,
        ])) or "sec",
        axis=1,
    )

    # Standardise columns
    for col in ["file_number", "election_date", "withdrawal_date", "total_net_assets"]:
        if col not in universe.columns:
            universe[col] = None
    if "in_third_party_lists" not in universe.columns:
        universe["in_third_party_lists"] = ""

    # Set status from activity_status
    if "activity_status" in universe.columns:
        universe["status"] = universe["activity_status"]
    elif "status" not in universe.columns:
        universe["status"] = "active"

    # Filing dates
    if "latest_periodic_filing_date" in universe.columns:
        universe["last_filing_date"] = universe["latest_periodic_filing_date"]
    else:
        universe["last_filing_date"] = None
    if "first_filing_date" not in universe.columns:
        universe["first_filing_date"] = None

    universe = universe.reset_index(drop=True)

    # ── Save outputs ──
    # Active-only output (backward compatible)
    out_cols = [
        "cik", "entity_name", "series_id", "fund_name", "vehicle_type",
        "status", "discovery_methods", "data_sources", "adviser_name",
        "first_filing_date", "last_filing_date", "in_third_party_lists",
    ]
    save_cols = [c for c in out_cols if c in universe.columns]

    active_mask = universe["status"].isin(["active", "possibly_inactive"])
    active_df = universe.loc[active_mask, save_cols]
    active_df.to_csv(FUND_UNIVERSE_FILE, index=False)
    logger.info("Saved active fund universe to %s (%d funds)",
                FUND_UNIVERSE_FILE, len(active_df))

    # Exhaustive output (all funds with activity info)
    exhaustive_cols = save_cols + [
        c for c in [
            "activity_status", "latest_periodic_filing_date",
            "latest_periodic_filing_type", "n2_filing_date", "n2_accession_number",
        ] if c in universe.columns and c not in save_cols
    ]
    universe[exhaustive_cols].to_csv(EXHAUSTIVE_FUND_UNIVERSE_FILE, index=False)
    logger.info("Saved exhaustive fund universe to %s (%d funds)",
                EXHAUSTIVE_FUND_UNIVERSE_FILE, len(universe))

    logger.info("Fund universe build completed in %.1f s", time.time() - t_total)
    logger.info("  Total unique entities: %d", len(universe))
    logger.info("  Active: %d", active_mask.sum())
    logger.info("  Interval funds: %d",
                (universe["vehicle_type"] == "interval_fund").sum())
    logger.info("  Tender offer funds: %d",
                (universe["vehicle_type"] == "tender_offer_fund").sum())

    return universe


def _build_fund_universe_fast(client: EdgarClient) -> pd.DataFrame:
    """Fast (legacy) universe build — Methods A + original B + N-PORT safety net.

    Used when --exhaustive is not specified.
    """
    # Method A: N-CEN (4 quarters — one per quarter-of-year to catch all
    # annual filers regardless of which quarter they file in)
    dataset_year = NCEN_DATASET_URL.rsplit("/", 1)[-1][:4]  # e.g. "2025"
    all_ncen_records: list[dict] = []
    for qnum in (1, 2, 3, 4):
        # Find latest cached file for this quarter-of-year
        candidates = sorted(
            SEC_DATASETS_DIR.glob(f"*q{qnum}_ncen.zip"),
            reverse=True,
        )
        chosen = candidates[0] if candidates else None
        if chosen is None:
            # Try downloading latest year
            url = (
                "https://www.sec.gov/files/dera/data/"
                f"form-n-cen-data-sets/{dataset_year}q{qnum}_ncen.zip"
            )
            dest = SEC_DATASETS_DIR / f"{dataset_year}q{qnum}_ncen.zip"
            try:
                client.download_file(url, dest)
                chosen = dest
            except Exception:
                logger.debug("N-CEN Q%d not available, skipping", qnum)
                continue
        try:
            recs = _parse_ncen_zip(chosen, chosen.stem.replace("_ncen", ""))
            all_ncen_records.extend(recs)
            logger.info("  N-CEN %s: %d interval funds", chosen.stem, len(recs))
        except Exception as exc:
            logger.warning("  N-CEN %s: parse error - %s", chosen.stem, exc)

    if all_ncen_records:
        df_a = pd.DataFrame(all_ncen_records)
        df_a = df_a.sort_values("quarter", ascending=False)
        dedup_cols = ["cik"] + (["series_id"] if "series_id" in df_a.columns else [])
        df_a = df_a.drop_duplicates(subset=dedup_cols, keep="first")
        df_a = df_a.drop(columns=["quarter"], errors="ignore")
        logger.info("Method A (fast-4q): %d interval funds from N-CEN", len(df_a))
    else:
        df_a = _ncen_via_efts(client)

    # Method B: EFTS-based N-2 search (fast, original approach)
    df_b = _search_n2_via_efts(client)

    # Combine
    frames = [f for f in [df_a, df_b] if not f.empty]
    if frames:
        universe = pd.concat(frames, ignore_index=True)
        universe = universe.sort_values(
            "discovery_method",
            key=lambda s: s.map({
                "ncen_classification": 0,
                "n2_checkbox": 1,
                "ncen_efts_search": 2,
            }).fillna(3),
        )
        dedup_cols = ["cik"]
        if "series_id" in universe.columns:
            dedup_cols.append("series_id")
        universe = universe.drop_duplicates(subset=dedup_cols, keep="first")
    else:
        universe = pd.DataFrame()

    if universe.empty:
        logger.warning("No interval/tender funds found")
        return pd.DataFrame()

    # N-PORT safety net
    known_ciks = set(universe["cik"].tolist())
    df_nport = _scan_nport_dataset(client, known_ciks)
    if not df_nport.empty:
        universe = pd.concat([universe, df_nport], ignore_index=True)
        universe = universe.drop_duplicates(
            subset=["cik"] + (["series_id"] if "series_id" in universe.columns else []),
            keep="first",
        )

    # Build discovery_methods
    method_a_ciks = set(df_a["cik"].tolist()) if not df_a.empty else set()
    method_b_ciks = set(df_b["cik"].tolist()) if not df_b.empty else set()
    method_nport_ciks = set(df_nport["cik"].tolist()) if not df_nport.empty else set()

    def _get_methods(cik: str) -> str:
        methods = []
        if cik in method_a_ciks:
            methods.append("ncen_classification")
        if cik in method_b_ciks:
            methods.append("n2_checkbox")
        if cik in method_nport_ciks:
            methods.append("nport_safety_net")
        return ",".join(methods) if methods else "unknown"

    universe["discovery_methods"] = universe["cik"].apply(_get_methods)
    universe["data_sources"] = "ncen"

    # Standardise columns
    for col in ["file_number", "election_date", "withdrawal_date", "total_net_assets"]:
        if col not in universe.columns:
            universe[col] = None
    if "in_third_party_lists" not in universe.columns:
        universe["in_third_party_lists"] = ""
    if "status" not in universe.columns:
        universe["status"] = "active"
    if "first_filing_date" not in universe.columns:
        universe["first_filing_date"] = None
    if "last_filing_date" not in universe.columns:
        universe["last_filing_date"] = None

    universe = universe.reset_index(drop=True)
    logger.info("Fund universe (fast): %d entities total", len(universe))

    out_cols = [
        "cik", "entity_name", "series_id", "fund_name", "vehicle_type",
        "status", "discovery_methods", "data_sources", "adviser_name",
        "first_filing_date", "last_filing_date", "in_third_party_lists",
    ]
    save_cols = [c for c in out_cols if c in universe.columns]
    universe[save_cols].to_csv(FUND_UNIVERSE_FILE, index=False)
    logger.info("Saved fund universe to %s", FUND_UNIVERSE_FILE)

    return universe


def _search_n2_via_efts(client: EdgarClient) -> pd.DataFrame:
    """Fast Method B: find N-2 filers via EFTS + N-CEN registrants, parse checkboxes."""
    logger.info("Method B (fast): N-2 checkbox parsing via EFTS ...")

    # Get N-CEN registrants of type N-2
    n2_ciks: dict[str, str] = {}
    # Use the latest cached N-CEN ZIP (prefer properly-named quarterly files)
    ncen_candidates = sorted(SEC_DATASETS_DIR.glob("*_ncen.zip"), reverse=True)
    ncen_zip = ncen_candidates[0] if ncen_candidates else SEC_DATASETS_DIR / "ncen_data.zip"
    if ncen_zip.exists():
        try:
            with zipfile.ZipFile(ncen_zip) as zf:
                if "REGISTRANT.tsv" in zf.namelist():
                    with zf.open("REGISTRANT.tsv") as fh:
                        reg = pd.read_csv(fh, sep="\t", dtype=str, on_bad_lines="skip")
                    if "INVESTMENT_COMPANY_TYPE" in reg.columns:
                        n2_mask = reg["INVESTMENT_COMPANY_TYPE"].str.strip().str.upper().eq("N-2")
                        for _, row in reg[n2_mask].iterrows():
                            cik = str(row.get("CIK", "")).strip()
                            name = str(row.get("REGISTRANT_NAME", "")).strip()
                            if cik and cik != "nan":
                                n2_ciks[cik] = name
        except Exception as exc:
            logger.warning("Could not read REGISTRANT.tsv: %s", exc)

    logger.info("  N-CEN REGISTRANT.tsv: %d N-2 registrants", len(n2_ciks))

    # Supplement with EFTS
    try:
        efts_hits = client.search_filings(form_type="N-2", max_results=500)
        efts_new = 0
        for hit in efts_hits:
            cik = _extract_cik_from_hit(hit)
            if cik and cik not in n2_ciks:
                n2_ciks[cik] = _extract_name_from_hit(hit)
                efts_new += 1
        logger.info("  EFTS N-2 search added %d new registrants", efts_new)
    except Exception as exc:
        logger.warning("  EFTS N-2 search failed: %s", exc)

    logger.info("  Total unique N-2 registrants to parse: %d", len(n2_ciks))

    # Fetch and parse each N-2
    records: list[dict] = []
    parsed_count = 0
    interval_count = 0
    tender_count = 0
    bdc_count = 0
    cef_count = 0
    no_checkbox_count = 0
    skipped = 0

    for cik, name in n2_ciks.items():
        doc_url = _get_latest_n2_via_submissions(client, cik)
        if not doc_url:
            skipped += 1
            continue
        if doc_url.lower().endswith(".pdf"):
            skipped += 1
            continue

        try:
            html = client.get_text(doc_url)
            checkboxes = _parse_n2_checkboxes(html)
            parsed_count += 1

            has_any_checkbox = any(checkboxes.values())

            if has_any_checkbox:
                if checkboxes["bdc"] and not checkboxes["interval"]:
                    bdc_count += 1
                    continue
                if checkboxes["interval"]:
                    vehicle_type = "interval_fund"
                    interval_count += 1
                elif checkboxes["closed_end"]:
                    if _has_tender_offer_structure(html):
                        vehicle_type = "tender_offer_fund"
                        tender_count += 1
                    else:
                        cef_count += 1
                        continue
                else:
                    no_checkbox_count += 1
                    continue
            else:
                clean_lower = re.sub(r"<[^>]+>", " ", html[:200_000])
                clean_lower = re.sub(r"\s+", " ", clean_lower).lower()
                if "business development company" in clean_lower:
                    bdc_count += 1
                    continue
                if re.search(r"interval\s+fund", clean_lower):
                    vehicle_type = "interval_fund"
                    interval_count += 1
                elif _has_tender_offer_structure(html):
                    vehicle_type = "tender_offer_fund"
                    tender_count += 1
                else:
                    no_checkbox_count += 1
                    continue

            records.append({
                "cik": cik,
                "entity_name": name,
                "series_id": None,
                "fund_name": None,
                "vehicle_type": vehicle_type,
                "discovery_method": "n2_checkbox",
            })

        except Exception as exc:
            logger.debug("Could not parse N-2 for CIK %s: %s", cik, exc)
            skipped += 1

    logger.info(
        "  N-2 results: %d parsed | %d interval | %d tender | "
        "%d BDC | %d CEF | %d no checkboxes | %d skipped",
        parsed_count, interval_count, tender_count,
        bdc_count, cef_count, no_checkbox_count, skipped,
    )

    result = pd.DataFrame(records)
    if not result.empty:
        result = result.drop_duplicates(subset=["cik"], keep="first")

    logger.info("Method B (fast): %d interval/tender funds", len(result))
    return result


def _get_latest_n2_via_submissions(client: EdgarClient, cik: str) -> str | None:
    """Return the URL of the most recent N-2 or N-2/A primary document for a CIK."""
    try:
        data = client.get_company_submissions(cik)
        recent = data.get("filings", {}).get("recent", {})
        forms = recent.get("form", [])
        accessions = recent.get("accessionNumber", [])
        docs = recent.get("primaryDocument", [])

        for form, accession, doc in zip(forms, accessions, docs):
            if form and form.upper() in ("N-2", "N-2/A"):
                acc_nodashes = accession.replace("-", "")
                return (
                    f"https://www.sec.gov/Archives/edgar/data/"
                    f"{cik}/{acc_nodashes}/{doc}"
                )
        return None
    except Exception as exc:
        logger.debug("Could not get submissions for CIK %s: %s", cik, exc)
        return None
