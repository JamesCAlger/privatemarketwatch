"""Extract tender offer repurchase results from SC TO-I/A filings.

Tender offer funds and non-traded BDCs file SC TO-I (original) and
SC TO-I/A (amendment) forms for each periodic share repurchase offer.
The final amendment contains exact results: shares tendered, shares
accepted, proration %, and repurchase price per share.

Public API
----------
build_sc_toi_filings_index(client, universe_ciks)  -> pd.DataFrame
download_sc_toi_filings(client, filings_index)      -> pd.DataFrame
extract_sc_toi_results(filings_index=None)           -> pd.DataFrame
"""

import logging
import re
import time
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

from pipeline.config import (
    COMBINED_UNIVERSE_FILE,
    SC_TOI_FILINGS_INDEX_FILE,
    SC_TOI_HTML_CACHE_DIR,
    SC_TOI_PARSE_PROGRESS_FILE,
    SC_TOI_RESULTS_FILE,
)
from pipeline.edgar_client import EdgarClient

logger = logging.getLogger(__name__)

# SC TO-I form types to discover
_SC_TOI_FORM_TYPES = {"SC TO-I", "SC TO-I/A", "SC TO-T", "SC TO-T/A"}

# Output columns
_OUTPUT_COLS = [
    "cik", "entity_name", "accession_number", "form_type",
    "filing_date", "report_date", "offer_expiration_date",
    "shares_offered", "shares_tendered", "shares_accepted", "proration_pct",
    "repurchase_price_per_share", "oversubscription_rate",
    "tx_valuation", "parse_method",
]

_SHARE_NUM = r"\d[\d,]*(?:\.\d+)?"

# ---------------------------------------------------------------------------
# Regex patterns for narrative extraction
# ---------------------------------------------------------------------------

# Shares tendered: "X shares [of the Fund] were validly tendered"
# Keep this result-oriented so original offers like "Shares that are tendered"
# do not create false-positive result rows.
_SHARES_TENDERED_RE = re.compile(
    rf"({_SHARE_NUM})\s+[Ss]hares?\b(?:\s+of\s+the\s+Fund)?\s+"
    r"(?:(?:were|was)\s+)?(?:validly\s+)?tendered",
    re.I,
)

# Shares accepted: "accepted for purchase/repurchase/payment X shares"
# Also handles: "the Fund accepted X Shares" and "purchased X Shares"
_SHARES_ACCEPTED_RE = re.compile(
    r"(?:"
    r"accepted\s+(?:for\s+)?(?:purchase|repurchase|payment)\s+"
    rf"(?:(?:a\s+total\s+)?(?:of\s+)?)?({_SHARE_NUM})\s+[Ss]hares?"
    r"|"
    r"(?:purchased|repurchased|accepted)\s+"
    r"(?:(?:on\s+a\s+pro\s+rata\s+basis\s+)?(?:the\s+maximum\s+of\s+)?"
    r"|(?:all\s+such\s+)|(?:all\s+)|(?:(?:a\s+total\s+)?(?:of\s+)?))"
    rf"({_SHARE_NUM})\s+[Ss]hares?"
    r")",
    re.I,
)

# "accepted for purchase 100% of the Shares" — full acceptance, no share count
_ACCEPTED_ALL_RE = re.compile(
    r"accepted\s+(?:for\s+)?(?:purchase|repurchase|payment)\s+100\s*%\s+"
    r"(?:of\s+)?(?:the\s+)?[Ss]hares?",
)

# Implicit full acceptance: "tenders were accepted for purchase by the Fund"
# This appears in final amendments when all tenders were accepted (no proration).
# Does NOT appear in intermediate amendments or original filings.
_TENDERS_ACCEPTED_RE = re.compile(
    r"tenders?\s+(?:were|was)\s+accepted\s+(?:for\s+)?(?:purchase|repurchase|payment)",
    re.I,
)

# Proration percentage: "representing approximately X%"
_PRORATION_RE = re.compile(
    r"(?:representing|approximately|pro[\s-]?rat(?:a|ed)\s+(?:at\s+)?)"
    r"\s*(?:approximately\s+)?([\d.]+)\s*%",
    re.I,
)

# Repurchase price per share: "repurchase price per share of $X.XX"
_PRICE_RE = re.compile(
    r"(?:repurchase|purchase|tender)\s+price\s+"
    r"(?:per\s+[Ss]hare\s+)?(?:(?:of|was|is|equal\s+to)\s+)?"
    r"\$?([\d,.]+)",
    re.I,
)

# "repurchased at a price of $X.XX per Share"
_PRICE_AT_RE = re.compile(
    r"(?:repurchased|purchased)?\s*at\s+(?:a\s+)?price\s+"
    r"(?:of|equal\s+to)\s+"
    r"(?:the\s+net\s+offering\s+price\s+per\s+[Ss]hare\s+determined\s+"
    r"as\s+of\s+\w+\s+\d{1,2},?\s+\d{4}\s+of\s+)?"
    r"\$?([\d,.]+)(?:\s+per\s+[Ss]hare)?",
    re.I,
)

# Alternate price pattern in tables: "$XX.XX per Share"
_TABLE_PRICE_RE = re.compile(
    r"\$\s*([\d,.]+)\s+per\s+[Ss]hare",
    re.I,
)

# Offer expiration date: "expired at ... on [Month Day, Year]"
_OFFER_EXPIRED_RE = re.compile(
    r"[Oo]ffer\s+(?:expired|terminated)\s+"
    r"(?:at\s+\S+\s+\S+[,.]?\s+\S+\s+\S+[,.]?\s+)?on\s+"
    r"(\w+\s+\d{1,2},?\s+\d{4})",
    re.I,
)

# Shares offered: "purchase up to X ... shares"
_SHARES_OFFERED_RE = re.compile(
    rf"(?:purchase|repurchase)\s+up\s+to\s+({_SHARE_NUM})\s+(?:\S+\s+){{0,5}}?"
    r"(?:common\s+)?[Ss]hares?",
    re.I,
)

# Transaction Valuation from filing fee table (aggregate max purchase price)
_TX_VALTN_RE = re.compile(
    r"Transaction\s+Valuation.*?\$([\d,]+)",
    re.I,
)


# ---------------------------------------------------------------------------
# A. Filing discovery
# ---------------------------------------------------------------------------

def build_sc_toi_filings_index(
    client: EdgarClient,
    universe_ciks: list[str],
) -> pd.DataFrame:
    """Fetch SC TO-I / SC TO-I/A filing metadata for universe CIKs.

    Returns a DataFrame with one row per filing.  Cached to disk for 24 h.
    """
    if SC_TOI_FILINGS_INDEX_FILE.exists():
        age = datetime.now() - datetime.fromtimestamp(
            SC_TOI_FILINGS_INDEX_FILE.stat().st_mtime,
        )
        if age < timedelta(hours=24):
            cached = pd.read_csv(SC_TOI_FILINGS_INDEX_FILE, dtype=str)
            cached_ciks = set(cached["cik"].unique()) if "cik" in cached.columns else set()
            requested_ciks = set(str(c) for c in universe_ciks)
            new_ciks = requested_ciks - cached_ciks
            if not new_ciks:
                logger.info(
                    "Loading cached SC TO-I filings index (%d min old, %d CIKs)",
                    int(age.total_seconds() / 60), len(cached_ciks),
                )
                return cached
            logger.info(
                "Cached index has %d CIKs but %d new CIKs requested, rebuilding",
                len(cached_ciks), len(new_ciks),
            )

    logger.info(
        "Building SC TO-I filings index for %d CIKs ...", len(universe_ciks),
    )

    records: list[dict[str, str]] = []
    for i, cik in enumerate(universe_ciks, 1):
        if i % 50 == 0 or i == len(universe_ciks):
            logger.info("  SC TO-I submissions progress: %d / %d", i, len(universe_ciks))

        try:
            data = client.get_company_submissions(cik)
        except Exception as exc:
            logger.warning("  CIK %s submissions failed: %s", cik, exc)
            continue

        entity_name = data.get("name", "")
        filings_obj = data.get("filings", {})

        recent = filings_obj.get("recent", {})
        _collect_sc_toi_filings(records, cik, entity_name, recent)

        for page_ref in filings_obj.get("files", []):
            page_name = page_ref.get("name", "")
            if not page_name:
                continue
            page_url = f"https://data.sec.gov/submissions/{page_name}"
            try:
                page_data = client.get_json(page_url)
            except Exception as exc:
                logger.debug("  CIK %s page %s failed: %s", cik, page_name, exc)
                continue
            _collect_sc_toi_filings(records, cik, entity_name, page_data)

    df = pd.DataFrame(records)
    if df.empty:
        logger.warning("No SC TO-I filings found")
        df = pd.DataFrame(columns=[
            "cik", "entity_name", "accession_number", "form_type",
            "filing_date", "report_date", "primary_document",
        ])
    else:
        df.drop_duplicates(subset=["accession_number"], inplace=True)
        df.sort_values(["cik", "filing_date"], inplace=True)

    df.to_csv(SC_TOI_FILINGS_INDEX_FILE, index=False)
    logger.info(
        "SC TO-I filings index: %d filings across %d CIKs",
        len(df), df["cik"].nunique() if not df.empty else 0,
    )
    return df


def _collect_sc_toi_filings(
    records: list[dict[str, str]],
    cik: str,
    entity_name: str,
    recent: dict[str, list],
) -> None:
    """Extract SC TO-I filings from a submissions-API recent/page dict."""
    forms = recent.get("form", [])
    dates = recent.get("filingDate", [])
    accessions = recent.get("accessionNumber", [])
    primary_docs = recent.get("primaryDocument", [])
    report_dates = recent.get("reportDate", [])

    for j in range(len(forms)):
        form = forms[j] if j < len(forms) else ""
        if form not in _SC_TOI_FORM_TYPES:
            continue

        records.append({
            "cik": cik,
            "entity_name": entity_name,
            "accession_number": accessions[j] if j < len(accessions) else "",
            "form_type": form,
            "filing_date": dates[j] if j < len(dates) else "",
            "report_date": report_dates[j] if j < len(report_dates) else "",
            "primary_document": primary_docs[j] if j < len(primary_docs) else "",
        })


# ---------------------------------------------------------------------------
# B. Filing download
# ---------------------------------------------------------------------------

def download_sc_toi_filings(
    client: EdgarClient,
    filings_index: pd.DataFrame,
) -> pd.DataFrame:
    """Download SC TO-I HTML for each filing.  Caches to disk.

    Adds ``html_local_path`` and ``download_status`` columns.
    """
    if filings_index.empty:
        filings_index["html_local_path"] = pd.Series(dtype=str)
        filings_index["download_status"] = pd.Series(dtype=str)
        return filings_index

    statuses: list[str] = []
    local_paths: list[str] = []
    total = len(filings_index)
    t0 = time.time()

    for idx, row in filings_index.iterrows():
        i = len(statuses) + 1
        if i % 100 == 0 or i == total:
            elapsed = time.time() - t0
            rate = i / elapsed if elapsed > 0 else 0
            logger.info(
                "  SC TO-I download: %d / %d  (%.1f/s)",
                i, total, rate,
            )

        prev_status = row.get("download_status")
        if pd.notna(prev_status) and prev_status in ("cached", "downloaded"):
            statuses.append(str(prev_status))
            local_paths.append(str(row.get("html_local_path", "") or ""))
            continue

        cik = str(row["cik"]).lstrip("0") or "0"
        acc = str(row["accession_number"]).replace("-", "")
        primary_doc = str(row.get("primary_document", ""))

        cache_dir = SC_TOI_HTML_CACHE_DIR / cik
        cache_file = cache_dir / f"{acc}.html"

        if cache_file.exists() and cache_file.stat().st_size > 1024:
            statuses.append("cached")
            local_paths.append(str(cache_file))
            continue

        if not primary_doc:
            statuses.append("no_primary_doc")
            local_paths.append("")
            continue

        url = (
            f"https://www.sec.gov/Archives/edgar/data/{cik}/"
            f"{acc}/{primary_doc}"
        )
        try:
            cache_dir.mkdir(parents=True, exist_ok=True)
            client.download_file(url, cache_file)
            statuses.append("downloaded")
            local_paths.append(str(cache_file))
        except Exception as exc:
            logger.warning("  Download failed: %s -- %s", url, exc)
            statuses.append("failed")
            local_paths.append("")

    filings_index = filings_index.copy()
    filings_index["download_status"] = statuses
    filings_index["html_local_path"] = local_paths

    filings_index.to_csv(SC_TOI_FILINGS_INDEX_FILE, index=False)
    ok_count = sum(1 for s in statuses if s in ("cached", "downloaded"))
    logger.info("SC TO-I downloads: %d / %d successful", ok_count, total)
    return filings_index


# ---------------------------------------------------------------------------
# C. Repurchase results extraction
# ---------------------------------------------------------------------------

def extract_sc_toi_results(
    filings_index: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Parse repurchase results from cached SC TO-I/A HTML files.

    Resumable: tracks parsed accessions in ``sc_toi_parse_progress.csv``.

    Parameters
    ----------
    filings_index : DataFrame, optional
        SC TO-I filings index with ``html_local_path``.
        Loaded from disk if None.

    Returns
    -------
    DataFrame saved to ``sc_toi_repurchase_results.csv``.
    """
    t0 = time.time()

    if filings_index is None:
        if SC_TOI_FILINGS_INDEX_FILE.exists():
            filings_index = pd.read_csv(SC_TOI_FILINGS_INDEX_FILE, dtype=str)
        else:
            logger.warning("No SC TO-I filings index found")
            empty = pd.DataFrame(columns=_OUTPUT_COLS)
            empty.to_csv(SC_TOI_RESULTS_FILE, index=False)
            return empty

    if filings_index.empty:
        empty = pd.DataFrame(columns=_OUTPUT_COLS)
        empty.to_csv(SC_TOI_RESULTS_FILE, index=False)
        return empty

    # -- Load progress checkpoint --
    parsed_accessions: set[str] = set()
    if SC_TOI_PARSE_PROGRESS_FILE.exists():
        prog_df = pd.read_csv(SC_TOI_PARSE_PROGRESS_FILE, dtype=str)
        parsed_accessions = set(prog_df["accession_number"].dropna())

    # -- Filter to unprocessed filings --
    to_parse = filings_index[
        ~filings_index["accession_number"].isin(parsed_accessions)
    ]

    # Early exit: nothing new to parse
    if to_parse.empty:
        if SC_TOI_RESULTS_FILE.exists():
            logger.info(
                "SC TO-I extraction: all %d filings already processed, "
                "loading cached output",
                len(filings_index),
            )
            return pd.read_csv(SC_TOI_RESULTS_FILE, dtype=str)
        parsed_accessions = set()
        to_parse = filings_index

    logger.info(
        "SC TO-I extraction: %d filings to parse (%d already done)",
        len(to_parse), len(parsed_accessions),
    )

    # -- Parse loop --
    new_rows: list[dict] = []
    progress_records: list[dict[str, str]] = []
    ok_count = 0
    fail_count = 0
    total = len(to_parse)

    for i, (_, row) in enumerate(to_parse.iterrows(), 1):
        accession = str(row.get("accession_number", "")).strip()
        html_path = str(row.get("html_local_path", "") or "")

        if not html_path or not Path(html_path).exists():
            progress_records.append({
                "accession_number": accession,
                "status": "no_html",
                "count": "0",
            })
            continue

        cik = str(row.get("cik", "")).strip()
        entity_name = str(row.get("entity_name", "")).strip()
        form_type = str(row.get("form_type", "")).strip()
        filing_date = str(row.get("filing_date", "")).strip()
        report_date = str(row.get("report_date", "")).strip()

        try:
            results = _parse_repurchase_results(html_path)
            for rec in results:
                rec["cik"] = cik
                rec["entity_name"] = entity_name
                rec["accession_number"] = accession
                rec["form_type"] = form_type
                rec["filing_date"] = filing_date
                rec["report_date"] = report_date
                new_rows.append(rec)
            if results:
                # Distinguish full results from boilerplate-only matches
                has_tendered = any(
                    r.get("shares_tendered") is not None for r in results
                )
                status = "ok" if has_tendered else "partial"
                ok_count += 1
                progress_records.append({
                    "accession_number": accession,
                    "status": status,
                    "count": str(len(results)),
                })
            else:
                progress_records.append({
                    "accession_number": accession,
                    "status": "no_data",
                    "count": "0",
                })
        except Exception as exc:
            logger.debug(
                "Failed to parse %s (CIK %s): %s", accession, cik, exc,
            )
            fail_count += 1
            progress_records.append({
                "accession_number": accession,
                "status": "error",
                "count": "0",
            })

        if i % 200 == 0:
            _save_progress(progress_records, parsed_accessions)
            logger.info(
                "  SC TO-I extraction progress: %d / %d (ok=%d, fail=%d)",
                i, total, ok_count, fail_count,
            )

    # Final progress save
    _save_progress(progress_records, parsed_accessions)

    logger.info(
        "SC TO-I extraction: %d filings with results, %d failed, "
        "%d new records",
        ok_count, fail_count, len(new_rows),
    )

    # -- Merge with existing output --
    if new_rows:
        new_df = pd.DataFrame(new_rows)
        if SC_TOI_RESULTS_FILE.exists() and len(parsed_accessions) > 0:
            existing = pd.read_csv(SC_TOI_RESULTS_FILE, dtype=str)
            combined = pd.concat([existing, new_df], ignore_index=True)
        else:
            combined = new_df
    elif SC_TOI_RESULTS_FILE.exists():
        combined = pd.read_csv(SC_TOI_RESULTS_FILE, dtype=str)
    else:
        combined = pd.DataFrame(columns=_OUTPUT_COLS)

    if combined.empty:
        result = pd.DataFrame(columns=_OUTPUT_COLS)
    else:
        result = _apply_guards(combined)
        result = _dedup_amendments(result)

        for col in _OUTPUT_COLS:
            if col not in result.columns:
                result[col] = None
        result = result[_OUTPUT_COLS]

    result.to_csv(SC_TOI_RESULTS_FILE, index=False)

    # -- Validation summary --
    _log_extraction_quality(result, filings_index)

    elapsed = time.time() - t0
    logger.info(
        "SC TO-I results: %d rows, %d CIKs in %.1f s",
        len(result),
        result["cik"].nunique() if not result.empty else 0,
        elapsed,
    )
    return result


def _save_progress(
    new_records: list[dict[str, str]],
    existing_accessions: set[str],
) -> None:
    """Append new progress records to the SC TO-I progress file."""
    if not new_records:
        return
    new_df = pd.DataFrame(new_records)
    if SC_TOI_PARSE_PROGRESS_FILE.exists():
        existing = pd.read_csv(SC_TOI_PARSE_PROGRESS_FILE, dtype=str)
        combined = pd.concat([existing, new_df], ignore_index=True)
        combined.drop_duplicates(
            subset=["accession_number"], keep="last", inplace=True,
        )
    else:
        combined = new_df
    combined.to_csv(SC_TOI_PARSE_PROGRESS_FILE, index=False)


# ---------------------------------------------------------------------------
# C1. HTML parsing internals
# ---------------------------------------------------------------------------

def _parse_repurchase_results(html_path: str) -> list[dict]:
    """Parse repurchase results from an SC TO-I/A filing.

    Returns a list of dicts (one per offer/class found in filing).
    """
    from bs4 import BeautifulSoup

    text = Path(html_path).read_text(encoding="utf-8", errors="replace")
    soup = BeautifulSoup(text, "html.parser")

    # Get plain text for narrative regex search
    body_text = soup.get_text(" ", strip=True)

    rec: dict = {}

    # -- Extract shares tendered --
    m = _SHARES_TENDERED_RE.search(body_text)
    if m:
        rec["shares_tendered"] = _parse_share_count(m.group(1))

    # -- Extract shares accepted --
    m = _SHARES_ACCEPTED_RE.search(body_text)
    if m:
        val = m.group(1) or m.group(2)
        rec["shares_accepted"] = _parse_share_count(val)
    elif _ACCEPTED_ALL_RE.search(body_text):
        # "accepted for purchase 100% of the Shares" — accepted = tendered
        if "shares_tendered" in rec and rec["shares_tendered"] is not None:
            rec["shares_accepted"] = rec["shares_tendered"]
    elif _TENDERS_ACCEPTED_RE.search(body_text):
        # Implicit full acceptance: "tenders were accepted for purchase"
        # Only appears in final amendments; all tenders accepted (no count stated)
        if "shares_tendered" in rec and rec["shares_tendered"] is not None:
            rec["shares_accepted"] = rec["shares_tendered"]

    # -- Extract proration percentage --
    m = _PRORATION_RE.search(body_text)
    if m:
        rec["proration_pct"] = _parse_float(m.group(1))

    # -- Extract repurchase price per share --
    # Try "repurchased at a price of $X per Share" first (Blackstone pattern)
    m = _PRICE_AT_RE.search(body_text)
    if m:
        rec["repurchase_price_per_share"] = _parse_float(m.group(1))
    else:
        # Try standard narrative pattern
        m = _PRICE_RE.search(body_text)
        if m:
            rec["repurchase_price_per_share"] = _parse_float(m.group(1))
        else:
            m = _TABLE_PRICE_RE.search(body_text)
            if m:
                rec["repurchase_price_per_share"] = _parse_float(m.group(1))

    # Also scan tables for per-class pricing
    table_prices = _extract_table_prices(soup)
    if table_prices and "repurchase_price_per_share" not in rec:
        rec["repurchase_price_per_share"] = table_prices[0]

    # -- Extract offer expiration date --
    m = _OFFER_EXPIRED_RE.search(body_text)
    if m:
        rec["offer_expiration_date"] = _parse_date_text(m.group(1))

    # -- Extract shares offered (max purchase amount) --
    m = _SHARES_OFFERED_RE.search(body_text)
    if m:
        rec["shares_offered"] = _parse_share_count(m.group(1))

    # -- Extract Transaction Valuation (filing fee cross-check) --
    m = _TX_VALTN_RE.search(body_text)
    if m:
        val = _parse_int(m.group(1))
        # Filter out filing fee amounts (< $1M); real TxValtn is > $10M
        if val is not None and val >= 1_000_000:
            rec["tx_valuation"] = val

    # -- Compute oversubscription rate --
    tendered = rec.get("shares_tendered")
    accepted = rec.get("shares_accepted")
    if tendered is not None and accepted is not None and accepted > 0:
        rec["oversubscription_rate"] = round(tendered / accepted, 4)

    # Recompute after possible 100% acceptance inference above
    accepted = rec.get("shares_accepted")
    if tendered is not None and accepted is not None and accepted > 0:
        if "oversubscription_rate" not in rec:
            rec["oversubscription_rate"] = round(tendered / accepted, 4)

    # Determine parse method
    if rec:
        rec["parse_method"] = "narrative_regex"

    # Shares offered, proration boilerplate, or fee-table values can appear in
    # original offers before any result exists. Require direct result evidence.
    if rec.get("shares_tendered") is None and rec.get("shares_accepted") is None:
        return []

    if not rec:
        return []

    return [rec]


def _extract_table_prices(soup) -> list[float]:
    """Scan HTML tables for per-share repurchase price data."""
    prices: list[float] = []
    for table in soup.find_all("table"):
        table_text = table.get_text(" ", strip=True).lower()
        if "price" not in table_text and "per share" not in table_text:
            continue
        # Table mentions price -- scan all rows for dollar values
        for tr in table.find_all("tr"):
            cells = [td.get_text(" ", strip=True) for td in tr.find_all(["td", "th"])]
            for cell in cells:
                m = re.match(r"^\$?\s*([\d,.]+)$", cell.strip())
                if m:
                    val = _parse_float(m.group(1))
                    if val is not None and 0.01 < val < 10000:
                        prices.append(val)
    return prices


def _parse_int(text: str) -> int | None:
    """Parse a comma-separated integer string."""
    if not text:
        return None
    try:
        return int(text.replace(",", ""))
    except ValueError:
        return None


def _parse_share_count(text: str) -> int | float | None:
    """Parse a share count, preserving fractional shares when disclosed."""
    val = _parse_float(text)
    if val is None:
        return None
    if float(val).is_integer():
        return int(val)
    return val


def _parse_float(text: str) -> float | None:
    """Parse a float string, stripping commas."""
    if not text:
        return None
    try:
        return float(text.replace(",", ""))
    except ValueError:
        return None


def _parse_date_text(text: str) -> str | None:
    """Parse a date like 'November 30, 2021' to 'YYYY-MM-DD'."""
    if not text:
        return None
    text = text.strip().replace(",", "")
    for fmt in ("%B %d %Y", "%b %d %Y"):
        try:
            dt = datetime.strptime(text, fmt)
            return dt.strftime("%Y-%m-%d")
        except ValueError:
            continue
    return text  # Return raw text if parse fails


# ---------------------------------------------------------------------------
# C2. Post-processing
# ---------------------------------------------------------------------------

def _apply_guards(df: pd.DataFrame) -> pd.DataFrame:
    """Apply data quality guard rails."""
    if df.empty:
        return df

    df = df.copy()

    # Proration: must be 0-100%
    if "proration_pct" in df.columns:
        vals = pd.to_numeric(df["proration_pct"], errors="coerce")
        mask = (vals < 0) | (vals > 100)
        df.loc[mask, "proration_pct"] = None

    # Shares: must be non-negative
    for col in ("shares_tendered", "shares_accepted"):
        if col in df.columns:
            vals = pd.to_numeric(df[col], errors="coerce")
            mask = vals < 0
            df.loc[mask, col] = None

    if "shares_tendered" in df.columns and "shares_accepted" in df.columns:
        tendered = pd.to_numeric(df["shares_tendered"], errors="coerce")
        accepted = pd.to_numeric(df["shares_accepted"], errors="coerce")
        ratio = accepted / tendered
        decimal_comma_mask = ratio.between(999.5, 1000.5)
        df.loc[decimal_comma_mask, "shares_accepted"] = (
            accepted[decimal_comma_mask] / 1000
        )

    # Price: must be economically meaningful. Par values like $0.001 per share
    # appear in issuer descriptions and are not tender offer prices.
    if "repurchase_price_per_share" in df.columns:
        vals = pd.to_numeric(df["repurchase_price_per_share"], errors="coerce")
        mask = vals <= 0.01
        df.loc[mask, "repurchase_price_per_share"] = None

    # Oversubscription rate: must be >= 1.0 (or null)
    # Rate < 1 means more accepted than tendered, which is impossible
    if "oversubscription_rate" in df.columns:
        vals = pd.to_numeric(df["oversubscription_rate"], errors="coerce")
        mask = vals < 1.0
        df.loc[mask, "oversubscription_rate"] = None

    return df


def _dedup_amendments(df: pd.DataFrame) -> pd.DataFrame:
    """Prefer SC TO-I/A over SC TO-I for same offer.

    Amendment filings supersede original filings with final results.
    Dedup key is (cik, offer_expiration_date) when available, else
    (cik, report_date) when available, else no dedup (keep all).
    """
    if df.empty or "form_type" not in df.columns:
        return df

    df = df.copy()

    # Build a composite offer key for dedup
    # Prefer offer_expiration_date, fall back to report_date
    offer_exp = df.get("offer_expiration_date", pd.Series(dtype=str))
    report_dt = df.get("report_date", pd.Series(dtype=str))
    df["_offer_key"] = offer_exp.where(
        offer_exp.notna() & (offer_exp != ""), report_dt,
    )

    # Only dedup rows that have a usable offer key
    has_key = df["_offer_key"].notna() & (df["_offer_key"] != "")
    if not has_key.any():
        df.drop(columns=["_offer_key"], inplace=True)
        return df

    no_key = df[~has_key].copy()
    keyed = df[has_key].copy()

    # Sort preference: amendments first (have final results)
    form_priority = {
        "SC TO-I/A": 1, "SC TO-T/A": 2,
        "SC TO-I": 3, "SC TO-T": 4,
    }
    keyed["_form_priority"] = keyed["form_type"].map(form_priority).fillna(5)

    # Count non-null result fields for completeness ranking
    _value_fields = [
        "shares_tendered", "shares_accepted", "proration_pct",
        "repurchase_price_per_share",
    ]
    keyed["_completeness"] = keyed[
        [c for c in _value_fields if c in keyed.columns]
    ].notna().sum(axis=1)

    # Prefer latest filing_date, then best form type, then most complete
    keyed.sort_values(
        ["cik", "_offer_key", "filing_date", "_completeness", "_form_priority"],
        ascending=[True, True, False, False, True],
        inplace=True,
    )
    keyed.drop_duplicates(
        subset=["cik", "_offer_key"], keep="first", inplace=True,
    )
    keyed.drop(columns=["_form_priority", "_completeness"], inplace=True)

    result = pd.concat([keyed, no_key], ignore_index=True)
    result.drop(columns=["_offer_key"], inplace=True)
    result.sort_values(["cik", "filing_date"], inplace=True)
    return result


# ---------------------------------------------------------------------------
# D. Extraction quality validation
# ---------------------------------------------------------------------------

def _log_extraction_quality(
    results: pd.DataFrame,
    filings_index: pd.DataFrame,
) -> None:
    """Log extraction quality metrics for monitoring."""
    if results.empty:
        logger.info("  Extraction quality: no results to validate")
        return

    n_rows = len(results)
    _key_fields = [
        "shares_tendered", "shares_accepted",
        "repurchase_price_per_share", "offer_expiration_date",
    ]

    # Field fill rates
    logger.info("  Extraction quality:")
    for col in _key_fields:
        if col in results.columns:
            filled = results[col].notna() & (results[col].astype(str) != "nan")
            fill_pct = filled.sum() / n_rows * 100
            logger.info("    %-30s %d/%d (%.0f%%)", col, filled.sum(), n_rows, fill_pct)

    # Amendment coverage: how many SC TO-I/A filings had no results at all?
    if filings_index is not None and not filings_index.empty:
        amendments = filings_index[
            filings_index["form_type"].isin({"SC TO-I/A", "SC TO-T/A"})
        ]
        originals = filings_index[
            filings_index["form_type"].isin({"SC TO-I", "SC TO-T"})
        ]
        result_accessions = set(results["accession_number"].dropna())
        final_amendments_with_results = amendments[
            amendments["accession_number"].isin(result_accessions)
        ]
        logger.info(
            "    %-30s %d amendments -> %d with results, %d originals",
            "filing coverage:",
            len(amendments),
            len(final_amendments_with_results),
            len(originals),
        )

    # Consistency checks
    if "shares_tendered" in results.columns and "shares_accepted" in results.columns:
        tendered = pd.to_numeric(results["shares_tendered"], errors="coerce")
        accepted = pd.to_numeric(results["shares_accepted"], errors="coerce")
        both_present = tendered.notna() & accepted.notna()
        if both_present.any():
            bad = (accepted[both_present] > tendered[both_present]).sum()
            if bad > 0:
                logger.warning(
                    "    WARNING: %d rows have shares_accepted > shares_tendered",
                    bad,
                )

    if "shares_tendered" in results.columns and "shares_offered" in results.columns:
        tendered = pd.to_numeric(results["shares_tendered"], errors="coerce")
        offered = pd.to_numeric(results["shares_offered"], errors="coerce")
        both_present = tendered.notna() & offered.notna()
        if both_present.any():
            oversubscribed = (tendered[both_present] > offered[both_present]).sum()
            if oversubscribed > 0:
                logger.info(
                    "    %-30s %d/%d rows",
                    "oversubscribed offers:",
                    oversubscribed,
                    both_present.sum(),
                )

    # TxValtn cross-check: tx_valuation ~= shares_offered * repurchase_price
    _tx_cross_check(results)


def _tx_cross_check(results: pd.DataFrame) -> None:
    """Cross-check extracted shares_offered * price against TxValtn.

    TxValtn uses NAV at offer commencement; repurchase_price uses NAV at
    valuation date. Expect ratio within 0.8-1.2 for a pass.
    """
    needed = {"tx_valuation", "shares_offered", "repurchase_price_per_share"}
    if not needed.issubset(results.columns):
        return

    tx = pd.to_numeric(results["tx_valuation"], errors="coerce")
    offered = pd.to_numeric(results["shares_offered"], errors="coerce")
    price = pd.to_numeric(results["repurchase_price_per_share"], errors="coerce")
    computed = offered * price
    can_check = tx.notna() & computed.notna() & (computed > 0)

    if not can_check.any():
        return

    ratio = tx[can_check] / computed[can_check]
    ok = ((ratio >= 0.8) & (ratio <= 1.2)).sum()
    fail = can_check.sum() - ok

    logger.info(
        "    %-30s %d/%d pass (0.8-1.2x), %d fail",
        "TxValtn cross-check:",
        ok,
        can_check.sum(),
        fail,
    )
    if fail > 0:
        bad_mask = can_check.copy()
        bad_mask.loc[can_check] = (ratio < 0.8) | (ratio > 1.2)
        bad_rows = results[bad_mask]
        for _, row in bad_rows.head(5).iterrows():
            idx = row.name
            logger.warning(
                "      CIK %s %s: TxValtn=%s, computed=%s, ratio=%.2f",
                row.get("cik", "?"),
                row.get("offer_expiration_date", row.get("filing_date", "?")),
                row.get("tx_valuation", "?"),
                f"{computed.loc[idx]:,.0f}",
                tx.loc[idx] / computed.loc[idx],
            )
