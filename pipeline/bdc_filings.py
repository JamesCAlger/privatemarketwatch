"""BDC XBRL filing download and investee-level holdings extraction.

Downloads 10-K / 10-Q XBRL instance documents for every BDC in the universe
and parses Schedule of Investments data into a flat CSV.

Public API
----------
extract_bdc_holdings(client, bdc_universe=None) -> pd.DataFrame
"""

import json
import logging
import re
import time
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd
from lxml import etree

from pipeline.config import (
    BDC_DEDUPE_AXIS_SPLITS_FILE,
    BDC_FILING_FORM_TYPES,
    BDC_FILINGS_INDEX_FILE,
    BDC_HOLDINGS_FILE,
    BDC_PARSE_PROGRESS_FILE,
    BDC_UNIVERSE_FILE,
    BDC_XBRL_CACHE_DIR,
    BDC_XBRL_START_YEAR,
)
from pipeline.edgar_client import EdgarClient

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# XBRL concept -> output column mapping
# ---------------------------------------------------------------------------
# Keys are lowercase substrings matched against the local name of each XBRL
# element.  Order matters -- first match wins.
# WARNING: Longer/more-specific patterns MUST appear before shorter ones.
# e.g. "investmentinterestratepaidinkind" before "investmentinterestrate",
# otherwise PIK rate silently maps to interest_rate.
CONCEPT_MAP: list[tuple[str, str]] = [
    # Fair value
    ("investmentownedatfairvalue", "fair_value"),
    ("investmentownedfairvalue", "fair_value"),
    # Cost basis
    ("investmentownedatcost", "cost"),
    ("investmentownedcost", "cost"),
    # Principal / par / face
    ("investmentownedbalanceprincipalamount", "principal_amount"),
    ("investmentownedbalancesharesornumberofcontractsorprincipalamount", "principal_amount"),
    ("investmentobtainedfaceamount", "face_amount"),
    ("investmentownedfaceamount", "face_amount"),
    # Shares
    ("investmentownedbalanceshares", "shares_held"),
    ("investmentownednumberofsharesornumberofcontracts", "shares_held"),
    # Interest rate -- IMPORTANT: longer/more-specific patterns MUST come
    # before the generic "investmentinterestrate" to avoid false matches.
    # NOTE: InvestmentInterestRatePaidInCash maps to the SAME interest_rate
    # column (34 filers use it; the value IS their reported cash-leg rate).
    # Which concept won is recorded in interest_rate_concept so the rate-
    # convention S0 signal and the all-in migration can act per row.
    ("investmentinterestratepaidinkind", "pik_rate"),
    ("investmentinterestratepaidincash", "interest_rate"),
    ("investmentinterestratefloor", "interest_rate_floor"),
    ("investmentinterestrate", "interest_rate"),
    # PIK rate (alternate naming)
    ("investmentpikrate", "pik_rate"),
    # Spread / variable rate
    ("investmentbasisspreadvariablerate", "basis_spread"),
    ("investmentbasisspreadofvariablerate", "basis_spread"),
    # Reference rate type (SOFR / PRIME / etc.)
    ("investmentreferencerateandspread", "reference_rate_type"),
    # Maturity date
    ("investmentmaturitydate", "maturity_date"),
    # % of net assets
    ("investmentownedpercentofnetassets", "pct_of_net_assets"),
    ("investmentownedpercentageofnetassets", "pct_of_net_assets"),
    # Unrealized gain/loss
    ("investmentownedunrealizedappreciationdepreciation", "unrealized_gain_loss"),
    # Realized gain/loss
    ("realizedgainlossoninvestments", "realized_gain_loss"),
    ("realizedgainlossoninvestment", "realized_gain_loss"),
    # Acquisition date
    ("investmentacquisitiondate", "acquisition_date"),
]

# All possible output value columns (used to initialise empty records)
_VALUE_COLUMNS = sorted({col for _, col in CONCEPT_MAP})
_UNIT_COLUMNS = [f"{col}_unit" for col in ("fair_value", "cost", "principal_amount")]

# Monetary columns (USD-denominated) subject to decimals normalization.
# When a filing mixes decimals attributes (e.g. most facts at decimals="-3"
# but a few at decimals="-6"), the outlier facts are likely 1000x inflated.
_MONETARY_COLUMNS = frozenset({
    "fair_value", "cost", "principal_amount", "face_amount",
    "unrealized_gain_loss", "realized_gain_loss",
})

# Fields whose raw as-extracted value is ALWAYS recorded in src_facts: staging
# applies threshold-heuristic rescales to these, so the cheap re-verification
# tier needs the pre-pipeline value (scoping doc 2.3/2.4).
_RATE_PROV_COLUMNS = frozenset({
    "interest_rate", "basis_spread", "pik_rate", "pct_of_net_assets",
})

# col -> its canonical CONCEPT_MAP pattern.  For most columns this is the
# first (most specific) pattern in CONCEPT_MAP for that column.  src_facts
# records the winning concept only when it is non-canonical -- the full
# re-verify tier re-locates canonical facts by replaying _match_concept.
#
# Special case: interest_rate.  CONCEPT_MAP intentionally places
# "investmentinterestratepaidincash" before "investmentinterestrate" so
# that paidincash facts are not mis-classified as bare rates.  But the bare
# "investmentinterestrate" concept is the canonical/primary form.  We set
# the canonical explicitly so the non-canonical paidincash variant is
# recorded in src_facts while bare rates are not.
CANONICAL_CONCEPT: dict[str, str] = {}
for _pat, _col in CONCEPT_MAP:
    CANONICAL_CONCEPT.setdefault(_col, _pat)
# Override: bare InvestmentInterestRate is the canonical interest_rate concept.
CANONICAL_CONCEPT["interest_rate"] = "investmentinterestrate"


def _record_value_xform(
    record: dict[str, Any], col: str, old_value: Any, code: str,
) -> None:
    """Record an extractor-side value transform into the record's src_facts.

    Sets ``r`` to the pre-transform value (first writer wins -- chained
    transforms keep the original instance value) and appends ``code`` to the
    ordered ``x`` event list.
    """
    try:
        prov = json.loads(record.get("src_facts") or "{}")
    except json.JSONDecodeError:
        prov = {}
    entry = prov.setdefault(col, {})
    entry.setdefault("r", old_value)
    entry.setdefault("x", []).append(code)
    record["src_facts"] = json.dumps(prov, sort_keys=True, separators=(",", ":"))


# Dimension local-name substrings used to identify the investment axis
_INVESTMENT_ID_DIMS = ("investmentidentifier", "investmentcompany")
# Cash-equivalents axis: filers tag MMF/T-bill schedule rows here (printed
# after "Total Portfolio Investments"). Only filer-extension members name a
# specific instrument; us-gaap: members are category aggregates.
_CASH_EQUIV_DIMS = ("cashandcashequivalent",)
_COMPANY_ID_DIMS = ("portfoliocompan", "portfolioinvestment", "issuer")
_INDUSTRY_DIMS = ("industr",)
_TYPE_DIMS = ("investmenttype", "investmentinstrument")
_AFFILIATION_DIMS = ("issueraffiliation", "affiliationstatus")

_DATE_LIKE_IDENTIFIER_RE = re.compile(
    r"^(\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{4}[/-]\d{1,2}[/-]\d{1,2}|"
    r"(19|20)\d{2}q[1-4]|q[1-4]\s+(19|20)\d{2})$",
    re.IGNORECASE,
)
_PLACEHOLDER_IDENTIFIER_RE = re.compile(
    r"^(n/?a|none|null|unknown|various|multiple|misc\.?|miscellaneous|other|"
    r"placeholder|not applicable|tbd)$",
    re.IGNORECASE,
)
_CATEGORY_IDENTIFIER_RE = re.compile(
    r"^(software|health\s*care|healthcare|financials?|industrials?|energy|"
    r"consumer|business services|technology|media|telecommunications|"
    r"first lien|first lien debt|second lien|second lien debt|subordinated debt|"
    r"senior secured loans?|secured loans?|unsecured loans?|equity securities|"
    r"preferred equity|common equity|warrants?)$",
    re.IGNORECASE,
)

_STEPSTONE_2025Q4_CIK = "0001950803"
_STEPSTONE_2025Q4_ACCESSION = "0001193125-26-128890"
_STEPSTONE_2025Q4_REPORT_DATE = "2025-12-31"
_STEPSTONE_2025Q4_NET_ASSETS = 1864467000.0
_STEPSTONE_2025Q4_SCALE_FACTOR = 1000.0
_STEPSTONE_2025Q4_SCALE_MAX_ABS = 500000.0
_STEPSTONE_2025Q4_MIN_SCALE_RATIO = 250.0
_STEPSTONE_2025Q4_MAX_SCALE_RATIO = 2000.0
_STEPSTONE_2025Q4_SCALE_COLUMNS = ("fair_value", "cost", "principal_amount")


# ===========================================================================
# Step 1 -- Build filings index from SEC submissions API
# ===========================================================================

def _build_filings_index(
    client: EdgarClient,
    bdc_universe: pd.DataFrame,
) -> pd.DataFrame:
    """Fetch 10-K/10-Q filing metadata for every BDC via the submissions API.

    Returns a DataFrame with one row per filing.  Cached to disk for 24 h.
    """
    # Check cache freshness
    if BDC_FILINGS_INDEX_FILE.exists():
        age = datetime.now() - datetime.fromtimestamp(
            BDC_FILINGS_INDEX_FILE.stat().st_mtime,
        )
        if age < timedelta(hours=24):
            logger.info(
                "Loading cached filings index (%d min old)",
                int(age.total_seconds() / 60),
            )
            return pd.read_csv(BDC_FILINGS_INDEX_FILE, dtype=str)

    ciks = (
        bdc_universe["cik"]
        .astype(str)
        .str.strip()
        .unique()
        .tolist()
    )
    logger.info("Building filings index for %d unique CIKs ...", len(ciks))

    cutoff_date = f"{BDC_XBRL_START_YEAR}-01-01"
    records: list[dict[str, str]] = []

    for i, cik in enumerate(ciks, 1):
        if i % 50 == 0 or i == len(ciks):
            logger.info("  Submissions progress: %d / %d CIKs", i, len(ciks))

        try:
            data = client.get_company_submissions(cik)
        except Exception as exc:
            logger.warning("  CIK %s submissions failed: %s", cik, exc)
            continue

        entity_name = data.get("name", "")
        filings_obj = data.get("filings", {})

        # Recent filings are inline
        recent = filings_obj.get("recent", {})
        _collect_filings(records, cik, entity_name, recent, cutoff_date)

        # Older filings are paginated into separate JSON files
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
            _collect_filings(records, cik, entity_name, page_data, cutoff_date)

    df = pd.DataFrame(records)
    if df.empty:
        logger.warning("No filings found -- check BDC universe and network access")
        return df

    df.drop_duplicates(subset=["accession_number"], inplace=True)
    df.sort_values(["cik", "filing_date"], inplace=True)

    # Merge with existing index to preserve data for CIKs not in this run
    # (e.g. when called via --ciks with a subset of the universe).
    if BDC_FILINGS_INDEX_FILE.exists():
        existing = pd.read_csv(BDC_FILINGS_INDEX_FILE, dtype=str)
        new_cik_set = set(df["cik"].astype(str).str.strip())
        keep = existing[~existing["cik"].astype(str).str.strip().isin(new_cik_set)]
        if len(keep) > 0:
            df = pd.concat([keep, df], ignore_index=True)
            df.sort_values(["cik", "filing_date"], inplace=True)
            logger.info(
                "Merged with existing index: preserved %d rows for %d other CIKs",
                len(keep),
                keep["cik"].nunique(),
            )

    df.to_csv(BDC_FILINGS_INDEX_FILE, index=False)
    logger.info(
        "Filings index built: %d filings across %d CIKs -> %s",
        len(df),
        df["cik"].nunique(),
        BDC_FILINGS_INDEX_FILE.name,
    )
    return df


def _collect_filings(
    records: list[dict[str, str]],
    cik: str,
    entity_name: str,
    recent: dict[str, list],
    cutoff_date: str,
) -> None:
    """Extract matching filings from a submissions-API recent/page dict."""
    forms = recent.get("form", [])
    dates = recent.get("filingDate", [])
    accessions = recent.get("accessionNumber", [])
    primary_docs = recent.get("primaryDocument", [])
    report_dates = recent.get("reportDate", [])

    for j in range(len(forms)):
        form = forms[j] if j < len(forms) else ""
        if form not in BDC_FILING_FORM_TYPES:
            continue
        filing_date = dates[j] if j < len(dates) else ""
        if filing_date < cutoff_date:
            continue

        records.append({
            "cik": cik,
            "entity_name": entity_name,
            "accession_number": accessions[j] if j < len(accessions) else "",
            "form_type": form,
            "filing_date": filing_date,
            "report_date": report_dates[j] if j < len(report_dates) else "",
            "primary_document": primary_docs[j] if j < len(primary_docs) else "",
        })


# ===========================================================================
# Step 2 -- Download XBRL instance documents
# ===========================================================================

def _download_xbrl_instances(
    client: EdgarClient,
    filings_index: pd.DataFrame,
) -> pd.DataFrame:
    """Download XBRL XML for each filing.  Updates *filings_index* in place.

    Adds columns: ``xbrl_local_path``, ``xbrl_download_status``.
    """
    statuses: list[str] = []
    local_paths: list[str] = []
    total = len(filings_index)
    t0 = time.time()

    for idx, row in filings_index.iterrows():
        i = len(statuses) + 1
        if i % 100 == 0 or i == total:
            elapsed = time.time() - t0
            rate = i / elapsed if elapsed > 0 else 0
            eta = (total - i) / rate if rate > 0 else 0
            logger.info(
                "  XBRL download progress: %d / %d  (%.1f/s, ETA %.0f s)",
                i, total, rate, eta,
            )

        # Skip rows preserved from a previous run (via merge in _build_filings_index)
        prev_status = row.get("xbrl_download_status")
        if pd.notna(prev_status) and prev_status in (
            "cached", "downloaded", "not_found",
        ):
            statuses.append(prev_status)
            local_paths.append(row.get("xbrl_local_path", "") or "")
            continue

        cik_stripped = str(row["cik"]).lstrip("0") or "0"
        acc_no_dashes = str(row["accession_number"]).replace("-", "")
        primary_doc = str(row.get("primary_document", ""))

        cache_dir = BDC_XBRL_CACHE_DIR / cik_stripped
        cache_file = cache_dir / f"{acc_no_dashes}.xml"

        # Already cached?
        if cache_file.exists() and cache_file.stat().st_size > 1024:
            statuses.append("cached")
            local_paths.append(str(cache_file))
            continue

        base_url = (
            f"https://www.sec.gov/Archives/edgar/data/"
            f"{cik_stripped}/{acc_no_dashes}"
        )

        downloaded = False

        # Attempt 1: iXBRL companion (_htm.xml)
        if primary_doc and primary_doc.lower().endswith((".htm", ".html")):
            stem = primary_doc.rsplit(".", 1)[0]
            xml_name = f"{stem}_htm.xml"
            url = f"{base_url}/{xml_name}"
            if _try_download(client, url, cache_file):
                downloaded = True

        # Attempt 2: .xml extension directly
        if not downloaded and primary_doc:
            stem = primary_doc.rsplit(".", 1)[0]
            xml_name = f"{stem}.xml"
            url = f"{base_url}/{xml_name}"
            if _try_download(client, url, cache_file):
                downloaded = True

        # Attempt 3: Fetch filing index page and find XBRL instance
        if not downloaded:
            xbrl_url = _find_xbrl_in_filing_index(
                client, cik_stripped, acc_no_dashes,
                str(row["accession_number"]),
            )
            if xbrl_url and _try_download(client, xbrl_url, cache_file):
                downloaded = True

        if downloaded:
            statuses.append("downloaded")
            local_paths.append(str(cache_file))
        else:
            statuses.append("not_found")
            local_paths.append("")

    filings_index["xbrl_download_status"] = statuses
    filings_index["xbrl_local_path"] = local_paths

    # Save updated index
    filings_index.to_csv(BDC_FILINGS_INDEX_FILE, index=False)

    found = sum(1 for s in statuses if s in ("downloaded", "cached"))
    logger.info(
        "XBRL download complete: %d downloaded/cached, %d not found out of %d",
        found, total - found, total,
    )
    return filings_index


def _try_download(
    client: EdgarClient,
    url: str,
    dest: Path,
) -> bool:
    """Try to download *url* to *dest*.  Return True on success."""
    resp = client.get_safe(url)
    if resp is None:
        return False
    content = resp.content
    if len(content) < 1024:
        return False
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(content)
    return True


def _find_xbrl_in_filing_index(
    client: EdgarClient,
    cik_stripped: str,
    acc_no_dashes: str,
    accession_number: str,
) -> str | None:
    """Parse the filing index page to locate the XBRL instance document URL."""
    index_url = (
        f"https://www.sec.gov/Archives/edgar/data/"
        f"{cik_stripped}/{acc_no_dashes}/{accession_number}-index.htm"
    )
    resp = client.get_safe(index_url)
    if resp is None:
        return None

    html = resp.text.lower()

    # Look for links to .xml files that look like XBRL instances
    # Typical patterns: *_htm.xml, *.xml (but not R*.xml which are renders)
    href_pattern = re.compile(r'href="([^"]+\.xml)"', re.IGNORECASE)
    candidates: list[str] = []
    for m in href_pattern.finditer(resp.text):
        href = m.group(1)
        fname = href.rsplit("/", 1)[-1].lower()
        # Skip rendering/taxonomy/calculation files
        if fname.startswith(("r", "financial", "defn")) or "_cal." in fname:
            continue
        if "_lab." in fname or "_def." in fname or "_pre." in fname:
            continue
        candidates.append(href)

    if not candidates:
        return None

    # Prefer _htm.xml variants
    for c in candidates:
        if "_htm.xml" in c.lower():
            href = c
            break
    else:
        href = candidates[0]

    if href.startswith("/"):
        return f"https://www.sec.gov{href}"
    if not href.startswith("http"):
        return (
            f"https://www.sec.gov/Archives/edgar/data/"
            f"{cik_stripped}/{acc_no_dashes}/{href}"
        )
    return href


# ===========================================================================
# Step 3 -- XBRL parsing helpers
# ===========================================================================

def _local_name(tag: str) -> str:
    """Strip namespace URI from an lxml tag string like ``{uri}localname``.

    Returns empty string for non-string tags (e.g. lxml Comment/PI nodes
    whose ``.tag`` is a callable, not a string -- ``root.iter()`` yields these).
    """
    if not isinstance(tag, str):
        return ""
    if tag.startswith("{"):
        return tag.split("}", 1)[1]
    if ":" in tag:
        return tag.split(":", 1)[1]
    return tag


_CAMEL_BOUNDARY_RE = re.compile(
    r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])|"
    r"(?<=[A-Za-z])(?=[0-9])|(?<=[0-9])(?=[A-Za-z])"
)


def _humanize_member_local_name(name: str) -> str:
    """Turn an XBRL member local-name into a readable identifier.

    ``DreyfusTreasuryObligationsCashManagementMoneyMarketFundMember`` ->
    ``Dreyfus Treasury Obligations Cash Management Money Market Fund``.
    """
    text = str(name or "").strip()
    if text.endswith("Member"):
        text = text[: -len("Member")]
    return _CAMEL_BOUNDARY_RE.sub(" ", text).strip()


def _parse_xbrl_contexts(tree: etree._ElementTree) -> dict[str, dict]:
    """Parse ``<xbrli:context>`` elements and identify investment contexts.

    Returns a dict keyed by context ID.  Each value is a dict with keys:
    ``period``, ``investment_identifier``, ``industry``, ``investment_type``,
    ``affiliation``, ``dimensions_raw``, ``is_investment``.
    """
    root = tree.getroot()
    contexts: dict[str, dict] = {}

    for ctx in root.iter():
        if _local_name(ctx.tag) != "context":
            continue

        ctx_id = ctx.get("id", "")
        if not ctx_id:
            continue

        # -- Period --
        period_str = ""
        for child in ctx:
            ln = _local_name(child.tag)
            if ln == "period":
                for pc in child:
                    pln = _local_name(pc.tag)
                    if pln == "instant":
                        period_str = (pc.text or "").strip()
                    elif pln == "endDate":
                        period_str = (pc.text or "").strip()

        # -- Dimensions --
        investment_id = ""
        company_id = ""
        cash_equiv_id = ""
        industry = ""
        investment_type = ""
        affiliation = ""
        dimension_parts: list[str] = []
        is_investment = False

        for seg in ctx.iter():
            seg_ln = _local_name(seg.tag)

            if seg_ln == "typedMember":
                dim_attr = seg.get("dimension", "")
                dim_ln = _local_name(dim_attr).lower() if dim_attr else ""
                # Extract child text as the investee identifier
                children = list(seg)
                if children:
                    val = (children[0].text or "").strip()
                else:
                    val = (seg.text or "").strip()

                dimension_parts.append(f"{dim_ln}={val}")

                if any(kw in dim_ln for kw in _INVESTMENT_ID_DIMS):
                    investment_id = val
                    is_investment = True
                elif any(kw in dim_ln for kw in _COMPANY_ID_DIMS):
                    company_id = val
                elif any(kw in dim_ln for kw in _CASH_EQUIV_DIMS):
                    cash_equiv_id = val

            elif seg_ln == "explicitMember":
                dim_attr = seg.get("dimension", "")
                dim_ln = _local_name(dim_attr).lower() if dim_attr else ""
                member_val = (seg.text or "").strip()
                member_ln = _local_name(member_val) if member_val else ""

                dimension_parts.append(f"{dim_ln}={member_ln}")

                if any(kw in dim_ln for kw in _INDUSTRY_DIMS):
                    industry = member_ln
                elif any(kw in dim_ln for kw in _TYPE_DIMS):
                    investment_type = member_ln
                elif any(kw in dim_ln for kw in _AFFILIATION_DIMS):
                    affiliation = member_ln

                if any(kw in dim_ln for kw in _COMPANY_ID_DIMS) and not company_id:
                    company_id = member_ln

                if (
                    any(kw in dim_ln for kw in _CASH_EQUIV_DIMS)
                    and member_val
                    and not member_val.lower().startswith("us-gaap:")
                ):
                    cash_equiv_id = _humanize_member_local_name(member_ln)

        if company_id and _is_non_position_identifier(investment_id):
            investment_id = company_id

        # Cash-equivalents-axis rescue: filer-extension members on the cash
        # axis name a specific schedule position (Dreyfus/State Street MMF
        # class, 2026-09-02 escalation deep-dive). Generic us-gaap members and
        # fully undimensioned contexts (the printed totals) never reach here.
        if (
            not is_investment
            and cash_equiv_id
            and not _is_non_position_identifier(cash_equiv_id)
        ):
            investment_id = cash_equiv_id
            is_investment = True

        contexts[ctx_id] = {
            "period": period_str,
            "investment_identifier": investment_id,
            "industry": industry,
            "investment_type": investment_type,
            "affiliation": affiliation,
            "dimensions_raw": "|".join(dimension_parts),
            "is_investment": is_investment,
        }

    return contexts


def _is_non_position_identifier(value: str) -> bool:
    """Return true when an XBRL investment identifier is not position identity."""
    text = str(value or "").strip()
    lower = text.lower()
    if not text:
        return True
    if _DATE_LIKE_IDENTIFIER_RE.match(lower):
        return True
    if _PLACEHOLDER_IDENTIFIER_RE.match(lower):
        return True
    if _CATEGORY_IDENTIFIER_RE.match(lower):
        return True
    if len(text) > 140 and ("axis" in lower or "=" in lower):
        return True
    return False


def _normalize_mixed_decimals_monetary_facts(
    facts_by_ctx: dict[str, dict[str, Any]],
    monetary_facts_stored: list[tuple[str, str, int, str]],
    prov_by_ctx: dict[str, dict[str, dict]] | None = None,
) -> None:
    """Normalize rare mixed-decimals monetary outliers in-place.

    Some filings tag most monetary investment facts at one decimals scale and
    a small number at a coarser scale.  When the outlier value is wildly larger
    than the dominant scale, align it with the dominant decimals.
    """
    if len(monetary_facts_stored) < 5:
        return

    decimals_tracker = [dec for _, _, dec, _loc in monetary_facts_stored]
    dec_counts = Counter(decimals_tracker)
    dominant_dec, dominant_count = dec_counts.most_common(1)[0]
    if dominant_count / len(decimals_tracker) < 0.75:
        return

    dominant_abs_vals = []
    for ctx_ref, col, fact_dec, _loc in monetary_facts_stored:
        if fact_dec != dominant_dec:
            continue
        val = facts_by_ctx[ctx_ref].get(col)
        if isinstance(val, (int, float)) and val != 0:
            dominant_abs_vals.append(abs(val))
    dominant_abs_vals.sort()
    median_dominant = (
        dominant_abs_vals[len(dominant_abs_vals) // 2]
        if dominant_abs_vals
        else 0
    )
    if median_dominant <= 0:
        return

    for ctx_ref, col, fact_dec, local in monetary_facts_stored:
        diff = fact_dec - dominant_dec
        if abs(diff) < 3:
            continue
        val = facts_by_ctx[ctx_ref].get(col)
        if val is None or not isinstance(val, (int, float)):
            continue
        if abs(val) / median_dominant > 100:
            corrected = val * (10 ** diff)
            facts_by_ctx[ctx_ref][col] = corrected
            logger.debug(
                "Decimals normalization: ctx=%s col=%s decimals=%d "
                "(dominant=%d) %s -> %s",
                ctx_ref, col, fact_dec, dominant_dec, val, corrected,
            )
            if prov_by_ctx is not None:
                entry = prov_by_ctx.setdefault(ctx_ref, {}).setdefault(col, {})
                entry.setdefault("r", val)
                entry.setdefault("x", []).append(f"decimals_rescale:10^{diff}")
                # Retain the exact winning concept so the full re-verify tier
                # can exact-match the transformed fact.
                entry.setdefault("c", local)


def _normalize_cik_digits(value: Any) -> str:
    digits = re.sub(r"\D+", "", "" if value is None else str(value))
    return digits.zfill(10) if digits else ""


def _stepstone_2025q4_scale_fix_applies(row: dict[str, Any]) -> bool:
    if _normalize_cik_digits(row.get("cik")) != _STEPSTONE_2025Q4_CIK:
        return False
    if str(row.get("accession_number", "") or "").strip() != _STEPSTONE_2025Q4_ACCESSION:
        return False
    report_date = str(row.get("report_date", "") or "").strip()
    period = str(row.get("period", "") or "").strip()
    if report_date != _STEPSTONE_2025Q4_REPORT_DATE or period != _STEPSTONE_2025Q4_REPORT_DATE:
        return False

    identifier = str(row.get("investment_identifier", "") or "")
    lower_identifier = identifier.lower()
    if "first lien senior secured" not in lower_identifier:
        return False

    try:
        from pipeline.bdc_xbrl_wrapper import classify_identifier
    except Exception:
        logger.debug("Stepstone scale fix skipped because wrapper classifier was unavailable")
        return False

    wrapper = classify_identifier(_STEPSTONE_2025Q4_CIK, identifier)
    if wrapper.get("wrapper_disposition") != "debt_position_leaf":
        return False

    try:
        fair_value = abs(float(row.get("fair_value")))
        pct_of_net_assets = abs(float(row.get("pct_of_net_assets")))
    except (TypeError, ValueError):
        return False
    if pd.isna(fair_value) or pd.isna(pct_of_net_assets):
        return False
    if fair_value == 0 or pct_of_net_assets == 0:
        return False
    if fair_value >= _STEPSTONE_2025Q4_SCALE_MAX_ABS:
        return False
    implied_scale = (pct_of_net_assets * _STEPSTONE_2025Q4_NET_ASSETS) / fair_value
    return (
        _STEPSTONE_2025Q4_MIN_SCALE_RATIO
        <= implied_scale
        <= _STEPSTONE_2025Q4_MAX_SCALE_RATIO
    )


def _scale_stepstone_2025q4_value(value: Any) -> Any:
    if value is None:
        return value
    if isinstance(value, str) and value.strip() == "":
        return value
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return value
    if pd.isna(numeric) or numeric == 0:
        return value
    if abs(numeric) >= _STEPSTONE_2025Q4_SCALE_MAX_ABS:
        return value
    return numeric * _STEPSTONE_2025Q4_SCALE_FACTOR


def _apply_stepstone_2025q4_monetary_scale_correction(
    records: list[dict[str, Any]],
) -> None:
    """Correct Stepstone 2025-12-31 first-lien position values reported 1000x low.

    The affected filing has wrapper-recognized first-lien position rows whose
    monetary facts are in thousands while category totals and percentages imply
    dollar-scale values.  Keep this repair CIK/accession/date scoped so it does
    not become a generic small-position heuristic.
    """
    corrected = 0
    for row in records:
        if not _stepstone_2025q4_scale_fix_applies(row):
            continue
        row_corrected = False
        for col in _STEPSTONE_2025Q4_SCALE_COLUMNS:
            before = row.get(col)
            after = _scale_stepstone_2025q4_value(before)
            if (
                after != before
                and not (
                    isinstance(after, (int, float))
                    and isinstance(before, (int, float))
                    and pd.isna(after)
                    and pd.isna(before)
                )
            ):
                _record_value_xform(row, col, before, "cik_scale_fix:x1000")
                row[col] = after
                row_corrected = True
        if row_corrected:
            corrected += 1
    if corrected:
        logger.info(
            "Stepstone 2025-12-31 monetary scale correction applied to %d first-lien rows",
            corrected,
        )


def _extract_investment_facts(
    tree: etree._ElementTree,
    contexts: dict[str, dict],
) -> list[dict[str, Any]]:
    """Extract investment-level XBRL facts and group by context.

    Returns one dict per investment position (context) with all mapped values.
    """
    # Gather only investment-context IDs
    inv_ctx_ids = {cid for cid, info in contexts.items() if info["is_investment"]}
    if not inv_ctx_ids:
        return []

    # Accumulate facts by context ID
    facts_by_ctx: dict[str, dict[str, Any]] = {}

    # Sparse provenance entries: col -> {r, c, x} built during fact ingestion.
    prov_by_ctx: dict[str, dict[str, dict]] = {}

    # Track decimals attribute for monetary facts (for cross-fact normalization)
    # Tuple extended to (ctx_ref, col, dec, local) so normalization can record
    # the exact winning concept in src_facts.
    monetary_facts_stored: list[tuple[str, str, int, str]] = []  # (ctx_ref, col, dec, local)

    root = tree.getroot()
    for elem in root.iter():
        ctx_ref = elem.get("contextRef")
        if ctx_ref is None or ctx_ref not in inv_ctx_ids:
            continue

        # Skip nil elements
        nil = elem.get("{http://www.w3.org/2001/XMLSchema-instance}nil")
        if nil and nil.lower() == "true":
            continue

        local = _local_name(elem.tag).lower()
        raw_text = (elem.text or "").strip()
        if not raw_text:
            continue

        # Match concept
        col = _match_concept(local)
        if col is None:
            continue

        # Parse value
        value = _parse_fact_value(col, raw_text)

        # Read decimals attribute for monetary columns
        dec_val: int | None = None
        if col in _MONETARY_COLUMNS and isinstance(value, (int, float)):
            dec_attr = elem.get("decimals")
            if dec_attr is not None:
                try:
                    dec_val = int(dec_attr)
                except ValueError:
                    pass

        if ctx_ref not in facts_by_ctx:
            facts_by_ctx[ctx_ref] = {}
        # Keep first non-None value per column (some filings duplicate facts)
        if col not in facts_by_ctx[ctx_ref] or facts_by_ctx[ctx_ref][col] is None:
            facts_by_ctx[ctx_ref][col] = value
            if col == "interest_rate":
                # Provenance: which taxonomy concept won this column. A
                # PaidInCash win means the stored value is the filer-declared
                # CASH leg (rate-convention S0 / all-in migration input).
                facts_by_ctx[ctx_ref]["interest_rate_concept"] = (
                    "paid_in_cash" if "paidincash" in local else "bare")
            if col in ("fair_value", "cost", "principal_amount"):
                facts_by_ctx[ctx_ref][f"{col}_unit"] = elem.get("unitRef", "") or ""
            if dec_val is not None:
                monetary_facts_stored.append((ctx_ref, col, dec_val, local))
            # --- src_facts provenance entry ---
            entry: dict[str, Any] = {}
            # Exact inequality: over-recording c (any non-canonical local) is
            # harmless; under-recording breaks the re-verifier's concept-
            # disambiguation contract.  The old substring test ("not in") was
            # wrong: "investmentinterestrate" IS a substring of
            # "investmentinterestratepaidincash", so paidincash never got a c.
            if local != CANONICAL_CONCEPT.get(col, ""):
                entry["c"] = local
            if col in _RATE_PROV_COLUMNS and isinstance(value, (int, float)):
                entry["r"] = value
            if entry:
                prov_by_ctx.setdefault(ctx_ref, {})[col] = entry

    # --- Normalize mixed-decimals monetary facts ---
    # Some filers tag a handful of facts with decimals="-6" while the majority
    # use decimals="-3".  The outlier values are 1000x too large.  Correct by
    # scaling outlier facts to match the dominant decimals.
    # Guard rails:
    #   1. >= 5 monetary facts total
    #   2. Dominant decimals represents >= 75% of facts
    #   3. Decimals diff >= 3 (1000x+ scale difference)
    #   4. Outlier value must be > 100x the median of dominant-decimals values
    #      (prevents false corrections when decimals differ only in precision)
    _normalize_mixed_decimals_monetary_facts(facts_by_ctx, monetary_facts_stored, prov_by_ctx)

    # Build output records
    records: list[dict[str, Any]] = []
    for ctx_id, fact_vals in facts_by_ctx.items():
        ctx_info = contexts[ctx_id]
        record: dict[str, Any] = {
            "_context_id": ctx_id,
            "period": ctx_info["period"],
            "investment_identifier": ctx_info["investment_identifier"],
            "industry": ctx_info["industry"],
            "investment_type": ctx_info["investment_type"],
            "affiliation": ctx_info["affiliation"],
            "dimensions_raw": ctx_info["dimensions_raw"],
        }
        # Initialise all value columns to None then overlay parsed facts
        for vc in _VALUE_COLUMNS:
            record[vc] = fact_vals.get(vc)
        for uc in _UNIT_COLUMNS:
            record[uc] = fact_vals.get(uc, "")
        record["interest_rate_concept"] = fact_vals.get("interest_rate_concept", "")
        prov = prov_by_ctx.get(ctx_id) or {}
        record["src_facts"] = (
            json.dumps(prov, sort_keys=True, separators=(",", ":")) if prov else "")
        records.append(record)

    return records


def _match_concept(local_lower: str) -> str | None:
    """Match a lowercase local name to an output column via CONCEPT_MAP."""
    for pattern, col in CONCEPT_MAP:
        if pattern in local_lower:
            return col
    return None


def _parse_fact_value(col: str, raw: str) -> Any:
    """Parse raw text into the appropriate Python type for *col*."""
    # Date columns -> keep as string
    if col.endswith("_date"):
        return raw

    # String columns
    if col in ("reference_rate_type",):
        return raw

    # Numeric columns
    try:
        return float(raw.replace(",", ""))
    except (ValueError, TypeError):
        return raw  # keep original string if not numeric


def _parse_single_filing(
    xml_path: str,
    filing_meta: dict[str, str],
) -> list[dict[str, Any]]:
    """Parse one XBRL instance file and return investee-level records."""
    try:
        tree = etree.parse(xml_path)
    except Exception as exc:
        logger.debug("XML parse error for %s: %s", xml_path, exc)
        return []

    contexts = _parse_xbrl_contexts(tree)
    facts = _extract_investment_facts(tree, contexts)

    # --- Non-accrual evidence: footnotes + dimensions ---
    from pipeline.nonaccrual_evidence import (
        classify_footnote,
        has_nonaccrual_dimension,
        linked_fact_footnotes,
    )

    root = tree.getroot()
    report_date = filing_meta.get("report_date", "")

    # 1. Dimension-based: check each context for explicit non-accrual members
    na_dim_ctxs: set[str] = set()
    for ctx_id, ctx_info in contexts.items():
        if has_nonaccrual_dimension(ctx_info):
            na_dim_ctxs.add(ctx_id)

    # 2. Footnote-based: build fact_id -> linked footnotes, resolve to contexts
    fn_map = linked_fact_footnotes(root)
    # Build fact_id -> context_id mapping for investment facts
    fact_id_to_ctx: dict[str, str] = {}
    inv_ctx_ids = {cid for cid, info in contexts.items() if info["is_investment"]}
    for elem in root.iter():
        fid = elem.get("id")
        cref = elem.get("contextRef")
        if fid and cref and cref in inv_ctx_ids:
            fact_id_to_ctx[fid] = cref

    na_fn_ctxs: set[str] = set()
    for fact_id, notes in fn_map.items():
        ctx_id = fact_id_to_ctx.get(fact_id)
        if not ctx_id:
            continue
        for note in notes:
            decision = classify_footnote(note, report_date)
            if decision.accepted:
                na_fn_ctxs.add(ctx_id)
                break  # one accepted footnote is enough for this context

    # 3. Stamp each record
    for rec in facts:
        ctx_id = rec.get("_context_id", "")
        rec["nonaccrual_footnote"] = ctx_id in na_fn_ctxs
        rec["nonaccrual_dimension"] = ctx_id in na_dim_ctxs

    # Annotate each record with filing metadata
    for rec in facts:
        rec["cik"] = filing_meta.get("cik", "")
        rec["entity_name"] = filing_meta.get("entity_name", "")
        rec["accession_number"] = filing_meta.get("accession_number", "")
        rec["form_type"] = filing_meta.get("form_type", "")
        rec["filing_date"] = filing_meta.get("filing_date", "")
        rec["report_date"] = filing_meta.get("report_date", "")

    _apply_stepstone_2025q4_monetary_scale_correction(facts)

    return facts


_DEDUP_KEY_COLUMNS = [
    "accession_number", "investment_identifier", "period", "dimensions_raw",
]
_DEDUP_CONFLICT_COLUMNS = [
    "fair_value",
    "cost",
    "principal_amount",
    "shares_held",
]


def _deduplicate_bdc_holdings(df: pd.DataFrame) -> pd.DataFrame:
    """Collapse duplicate XBRL contexts without keeping sparse rows first.

    Some filers report the same investment identifier in multiple contexts: one
    sparse context may carry text/rate fields while another carries FV/cost/
    principal.  A plain ``drop_duplicates(keep='first')`` can therefore discard
    the economic facts.  This helper keeps the most complete row, fills missing
    non-conflicting values from sibling contexts, and marks economic conflicts
    for downstream QA instead of hiding them.
    """
    if df.empty:
        return df

    missing = [col for col in _DEDUP_KEY_COLUMNS if col not in df.columns]
    if missing:
        logger.warning("BDC dedupe filling missing key columns: %s", missing)
        df = df.copy()
        for col in missing:
            df[col] = ""

    result = df.copy()
    for col in _DEDUP_KEY_COLUMNS:
        result[col] = result[col].fillna("").astype(str)
    value_cols = [col for col in _VALUE_COLUMNS if col in result.columns]
    score_cols = [col for col in value_cols if col not in {"unrealized_gain_loss"}]

    result["_dedupe_row_order"] = range(len(result))
    result["_dedupe_score"] = 0
    for col in score_cols:
        as_text = result[col].astype("string").str.strip()
        result["_dedupe_score"] += as_text.notna() & (as_text != "")
    if "_context_id" not in result.columns:
        result["_context_id"] = ""

    group_sizes = result.groupby(_DEDUP_KEY_COLUMNS, dropna=False)[
        "_dedupe_row_order"
    ].transform("size")
    result["dedupe_context_count"] = group_sizes

    # ------------------------------------------------------------------
    # FV-conflict split: when a dedup group has distinct fair values,
    # the rows represent genuinely different positions reported under the
    # same XBRL axis.  Sub-group by rounded FV so each position survives.
    # ------------------------------------------------------------------
    fv_numeric = pd.to_numeric(result.get("fair_value"), errors="coerce")
    fv_rounded = fv_numeric.round(0)
    fv_nunique = fv_rounded.groupby(
        [result[k] for k in _DEDUP_KEY_COLUMNS], dropna=False,
    ).transform("nunique")
    has_fv_conflict = fv_nunique > 1

    result["_fv_split_key"] = ""
    # Rows with a non-null FV in a conflict group get their rounded FV as key
    fv_mask = has_fv_conflict & fv_rounded.notna()
    result.loc[fv_mask, "_fv_split_key"] = (
        fv_rounded[fv_mask].astype(int).astype(str)
    )
    # Null-FV rows in conflict groups: assign to the sub-group of the
    # highest-scoring non-null-FV row in their original group
    null_fv_conflict = has_fv_conflict & fv_rounded.isna()
    if null_fv_conflict.any():
        best_key = (
            result[has_fv_conflict & fv_rounded.notna()]
            .sort_values(
                by=["_dedupe_score", "_context_id", "_dedupe_row_order"],
                ascending=[False, True, True],
                kind="mergesort",
            )
            .groupby(_DEDUP_KEY_COLUMNS, dropna=False)["_fv_split_key"]
            .first()
        )
        for idx in result.index[null_fv_conflict]:
            key_vals = tuple(result.loc[idx, _DEDUP_KEY_COLUMNS])
            if key_vals in best_key.index:
                result.at[idx, "_fv_split_key"] = best_key[key_vals]

    _EFFECTIVE_KEY = _DEDUP_KEY_COLUMNS + ["_fv_split_key"]

    # ------------------------------------------------------------------
    # Detect conflicts within effective (post-split) sub-groups
    # ------------------------------------------------------------------
    conflict_fields_by_col: dict[str, pd.Series] = {}
    for col in [c for c in _DEDUP_CONFLICT_COLUMNS if c in result.columns]:
        numeric = pd.to_numeric(result[col], errors="coerce").round(6)
        normalized = numeric.astype("string").where(
            numeric.notna(),
            result[col].astype("string").str.strip(),
        )
        normalized = normalized.mask(normalized.isna() | (normalized == ""), pd.NA)
        nunique = normalized.groupby(
            [result[k] for k in _EFFECTIVE_KEY],
            dropna=False,
        ).transform("nunique")
        conflict_fields_by_col[col] = nunique > 1

    result["dedupe_conflict_fields"] = ""
    for col, mask in conflict_fields_by_col.items():
        result.loc[mask, "dedupe_conflict_fields"] = (
            result.loc[mask, "dedupe_conflict_fields"]
            .astype("string")
            .fillna("")
            .map(lambda val, field=col: field if val == "" else f"{val},{field}")
        )

    # ------------------------------------------------------------------
    # Fill missing values and pick best row per effective sub-group
    # ------------------------------------------------------------------
    fill_source = result.copy()
    fill_source[value_cols] = fill_source[value_cols].replace("", pd.NA)
    fill_values = (
        fill_source
        .sort_values(
            by=["_dedupe_score", "_context_id", "_dedupe_row_order"],
            ascending=[False, True, True],
            kind="mergesort",
        )
        .groupby(_EFFECTIVE_KEY, dropna=False)[value_cols]
        .first()
        .reset_index()
    )

    picked = (
        result.sort_values(
            by=["_dedupe_score", "_context_id", "_dedupe_row_order"],
            ascending=[False, True, True],
            kind="mergesort",
        )
        .drop_duplicates(subset=_EFFECTIVE_KEY, keep="first")
        .merge(
            fill_values,
            on=_EFFECTIVE_KEY,
            how="left",
            suffixes=("", "_dedupe_fill"),
        )
    )
    picked["dedupe_filled_fields"] = ""

    for col in value_cols:
        fill_col = f"{col}_dedupe_fill"
        if fill_col not in picked.columns:
            continue
        has_conflict = picked["dedupe_conflict_fields"].astype("string").str.contains(
            rf"(?:^|,){re.escape(col)}(?:,|$)",
            regex=True,
            na=False,
        )
        missing_value = (
            picked[col].isna()
            | (picked[col].astype("string").str.strip() == "")
        )
        actually_filled = (
            missing_value & ~has_conflict
            & picked[fill_col].notna()
            & (picked[fill_col].astype("string").str.strip() != "")
        )
        picked.loc[missing_value & ~has_conflict, col] = picked.loc[
            missing_value & ~has_conflict, fill_col
        ]
        picked.loc[actually_filled, "dedupe_filled_fields"] = (
            picked.loc[actually_filled, "dedupe_filled_fields"]
            .map(lambda val, field=col: field if val == "" else f"{val},{field}")
        )
        picked.drop(columns=[fill_col], inplace=True)

    # Non-accrual OR-merge: if any row in a dedup group has True, the
    # surviving row must have True (signals should not be lost by dedup).
    for na_col in ("nonaccrual_footnote", "nonaccrual_dimension"):
        if na_col in result.columns:
            bool_col = pd.to_numeric(result[na_col], errors="coerce").fillna(0)
            na_group_max = (
                bool_col.groupby(
                    [result[k] for k in _EFFECTIVE_KEY], dropna=False,
                ).transform("max")
            )
            result["_na_max"] = na_group_max
            # Get one value per effective group to merge into picked
            na_agg = (
                result.drop_duplicates(subset=_EFFECTIVE_KEY)
                [_EFFECTIVE_KEY + ["_na_max"]]
            )
            picked = picked.merge(na_agg, on=_EFFECTIVE_KEY, how="left")
            picked[na_col] = picked["_na_max"].fillna(0).astype(bool)
            picked.drop(columns=["_na_max"], inplace=True)
            result.drop(columns=["_na_max"], inplace=True)

    # Tag rows that resulted from an FV-based axis split
    picked["dedupe_axis_split"] = picked["_fv_split_key"].ne("")

    # Emit audit artifact for split rows
    split_rows = picked[picked["dedupe_axis_split"]]
    if not split_rows.empty:
        audit_cols = [
            c for c in [
                "cik", "entity_name", "accession_number", "report_date",
                "investment_identifier", "period", "dimensions_raw",
                "fair_value", "cost", "dedupe_context_count",
                "dedupe_conflict_fields",
            ] if c in split_rows.columns
        ]
        try:
            split_rows[audit_cols].to_csv(
                BDC_DEDUPE_AXIS_SPLITS_FILE, index=False
            )
            logger.info(
                "BDC dedupe axis splits: %d rows written to %s",
                len(split_rows), BDC_DEDUPE_AXIS_SPLITS_FILE,
            )
        except Exception:
            logger.warning(
                "Failed to write BDC dedupe axis splits audit file",
                exc_info=True,
            )

    conflicts = picked["dedupe_conflict_fields"].astype("string").str.len().fillna(0) > 0
    if conflicts.any():
        logger.warning(
            "BDC dedupe found %d investment groups with conflicting economic facts",
            int(conflicts.sum()),
        )

    # Publish the winning row's XBRL contextRef as the row's source anchor.
    # accession_number + src_context_id locates the ix:nonFraction facts in
    # the cached filing (primary-of-N when dedupe_context_count > 1).
    if "_context_id" in picked.columns:
        picked["src_context_id"] = picked["_context_id"].fillna("").astype(str)
    else:
        picked["src_context_id"] = ""

    drop_cols = ["_dedupe_row_order", "_dedupe_score", "_fv_split_key"]
    if "_context_id" in picked.columns:
        drop_cols.append("_context_id")
    return picked.drop(columns=drop_cols)


# ===========================================================================
# Step 4 -- Batch parsing with resumability
# ===========================================================================

def _parse_all_filings(filings_index: pd.DataFrame) -> pd.DataFrame:
    """Parse all downloaded XBRL files and produce a holdings DataFrame.

    Uses a progress file for crash recovery -- already-parsed accessions are
    skipped on restart.
    """
    # Load progress (set of already-parsed accession numbers)
    parsed_accessions: set[str] = set()
    if BDC_PARSE_PROGRESS_FILE.exists():
        prog = pd.read_csv(BDC_PARSE_PROGRESS_FILE, dtype=str)
        parsed_accessions = set(
            prog.loc[
                prog["status"].isin(["parsed", "error"]), "accession_number"
            ]
        )
        logger.info(
            "Resuming parsing -- %d accessions already processed",
            len(parsed_accessions),
        )

    # Filter to downloadable filings not yet parsed
    mask = (
        filings_index["xbrl_download_status"].isin(["downloaded", "cached"])
        & ~filings_index["accession_number"].isin(parsed_accessions)
    )
    to_parse = filings_index.loc[mask]
    logger.info("Filings to parse: %d (skipping %d already done)", len(to_parse), len(parsed_accessions))

    all_holdings: list[dict[str, Any]] = []
    progress_records: list[dict[str, str]] = []
    t0 = time.time()

    for i, (_, row) in enumerate(to_parse.iterrows(), 1):
        acc = str(row["accession_number"])
        xml_path = str(row["xbrl_local_path"])
        filing_meta = row.to_dict()

        try:
            holdings = _parse_single_filing(xml_path, filing_meta)
            all_holdings.extend(holdings)
            progress_records.append({"accession_number": acc, "status": "parsed", "count": str(len(holdings))})
        except Exception as exc:
            logger.debug("Parse error for %s: %s", acc, exc)
            progress_records.append({"accession_number": acc, "status": "error", "count": "0"})

        # Periodic progress save
        if i % 50 == 0 or i == len(to_parse):
            _save_parse_progress(progress_records, parsed_accessions)
            elapsed = time.time() - t0
            rate = i / elapsed if elapsed > 0 else 0
            eta = (len(to_parse) - i) / rate if rate > 0 else 0
            logger.info(
                "  Parse progress: %d / %d  (%d holdings so far, ETA %.0f s)",
                i, len(to_parse), len(all_holdings), eta,
            )

    # Final progress save
    _save_parse_progress(progress_records, parsed_accessions)

    # Build combined DataFrame
    if not all_holdings:
        # Also load any previously-saved holdings
        if BDC_HOLDINGS_FILE.exists():
            logger.info("No new holdings; loading existing %s", BDC_HOLDINGS_FILE.name)
            return pd.read_csv(BDC_HOLDINGS_FILE, dtype=str)
        logger.warning("No holdings extracted from any filing")
        return pd.DataFrame()

    new_df = pd.DataFrame(all_holdings)

    # Merge with any previously-saved holdings (from prior partial runs)
    if BDC_HOLDINGS_FILE.exists() and len(parsed_accessions) > 0:
        existing = pd.read_csv(BDC_HOLDINGS_FILE, dtype=str)
        combined = pd.concat([existing, new_df], ignore_index=True)
    else:
        combined = new_df

    # Always deduplicate (same investment can appear in multiple contexts).
    # Use completeness-aware selection so sparse context rows do not discard FV.
    combined = _deduplicate_bdc_holdings(combined)
    combined.to_csv(BDC_HOLDINGS_FILE, index=False)
    from pipeline.utils import write_parquet_companion
    write_parquet_companion(BDC_HOLDINGS_FILE)
    logger.info(
        "Holdings saved: %d total rows -> %s",
        len(combined), BDC_HOLDINGS_FILE.name,
    )
    return combined


def rebuild_cached_bdc_holdings(
    filings_index: pd.DataFrame | None = None,
    ciks: list[str] | None = None,
) -> pd.DataFrame:
    """Rebuild ``bdc_holdings.csv`` from already-cached XBRL files only.

    This intentionally does not call EDGAR or use the parse progress file.  It
    is for parser/dedupe changes where every cached instance should be
    reinterpreted with current code.

    Parameters
    ----------
    filings_index : pd.DataFrame, optional
        Pre-loaded filings index.  If *None*, loaded from ``BDC_FILINGS_INDEX_FILE``.
    ciks : list[str], optional
        When given, only those CIKs' cached filings are re-parsed and the
        result is merged over the existing ``bdc_holdings.csv`` (other CIKs'
        rows are preserved byte-identically).  When *None*, a full rebuild is
        performed (existing behaviour).
    """
    if filings_index is None:
        if not BDC_FILINGS_INDEX_FILE.exists():
            raise FileNotFoundError(
                f"BDC filings index file not found: {BDC_FILINGS_INDEX_FILE}"
            )
        filings_index = pd.read_csv(BDC_FILINGS_INDEX_FILE, dtype=str)

    if filings_index.empty or "xbrl_local_path" not in filings_index.columns:
        logger.warning("No cached BDC filings available for holdings rebuild")
        return pd.DataFrame()

    # Cohort-scoped rebuild: restrict index to requested CIKs only
    wanted: set[str] = set()
    if ciks:
        wanted = {_normalize_cik_digits(c) for c in ciks}
        cik_norm = filings_index["cik"].map(_normalize_cik_digits)
        filings_index = filings_index.loc[cik_norm.isin(wanted)]
        logger.info(
            "Cohort-scoped rebuild: %d CIKs, %d index rows",
            len(wanted), len(filings_index),
        )

    records: list[dict[str, Any]] = []
    total = len(filings_index)
    parsed = 0
    for i, (_, row) in enumerate(filings_index.iterrows(), 1):
        status = str(row.get("xbrl_download_status", "") or "")
        if status not in ("downloaded", "cached"):
            continue
        xml_path = str(row.get("xbrl_local_path", "") or "").strip()
        if not xml_path or not Path(xml_path).exists():
            continue
        parsed += 1
        records.extend(_parse_single_filing(xml_path, row.to_dict()))
        if i % 100 == 0 or i == total:
            logger.info(
                "  Cached BDC parse progress: %d / %d filings (%d holdings)",
                i, total, len(records),
            )

    if not records:
        logger.warning("No BDC holdings rebuilt from cached XBRL files")
        return pd.DataFrame()

    holdings = _deduplicate_bdc_holdings(pd.DataFrame(records))

    # Merge back over existing artifact when scoped to specific CIKs
    if ciks and BDC_HOLDINGS_FILE.exists():
        existing = pd.read_csv(BDC_HOLDINGS_FILE, dtype=str)
        keep = ~existing["cik"].map(_normalize_cik_digits).isin(wanted)
        existing = existing.loc[keep]
        for col in holdings.columns:
            if col not in existing.columns:
                existing[col] = ""
        for col in existing.columns:
            if col not in holdings.columns:
                holdings[col] = ""
        holdings = pd.concat([existing, holdings], ignore_index=True)
        logger.info(
            "Merged over existing artifact: %d kept + %d re-extracted",
            int(keep.sum()), len(holdings) - int(keep.sum()),
        )

    holdings.to_csv(BDC_HOLDINGS_FILE, index=False)
    from pipeline.utils import write_parquet_companion
    write_parquet_companion(BDC_HOLDINGS_FILE)
    logger.info(
        "Cached BDC holdings rebuilt: %d rows from %d filings -> %s",
        len(holdings), parsed, BDC_HOLDINGS_FILE.name,
    )
    return holdings


def _save_parse_progress(
    new_records: list[dict[str, str]],
    existing_accessions: set[str],
) -> None:
    """Append new progress records to the progress file."""
    if not new_records:
        return
    new_df = pd.DataFrame(new_records)
    if BDC_PARSE_PROGRESS_FILE.exists():
        existing = pd.read_csv(BDC_PARSE_PROGRESS_FILE, dtype=str)
        combined = pd.concat([existing, new_df], ignore_index=True)
        combined.drop_duplicates(subset=["accession_number"], keep="last", inplace=True)
    else:
        combined = new_df
    combined.to_csv(BDC_PARSE_PROGRESS_FILE, index=False)


# ===========================================================================
# Public entry point
# ===========================================================================

def extract_bdc_holdings(
    client: EdgarClient,
    bdc_universe: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """End-to-end BDC holdings extraction pipeline.

    1. Build filings index (SEC submissions API)
    2. Download XBRL instance documents
    3. Parse XBRL and extract investee-level holdings

    Parameters
    ----------
    client : EdgarClient
        Rate-limited HTTP client.
    bdc_universe : pd.DataFrame, optional
        BDC universe with a ``cik`` column.  If *None*, loaded from disk.

    Returns
    -------
    pd.DataFrame
        One row per investment position per filing period.
    """
    logger.info("=" * 60)
    logger.info("BDC HOLDINGS EXTRACTION -- STARTING")
    logger.info("=" * 60)
    t0 = time.time()

    # Load universe if not provided
    if bdc_universe is None:
        if not BDC_UNIVERSE_FILE.exists():
            raise FileNotFoundError(
                f"BDC universe file not found: {BDC_UNIVERSE_FILE}"
            )
        bdc_universe = pd.read_csv(BDC_UNIVERSE_FILE, dtype=str)

    n_ciks = bdc_universe["cik"].astype(str).str.strip().nunique()
    logger.info("BDC universe: %d rows, %d unique CIKs", len(bdc_universe), n_ciks)

    # Step 1: Build filings index
    logger.info("")
    logger.info("-- Step 1: Building filings index --")
    t1 = time.time()
    filings_index = _build_filings_index(client, bdc_universe)
    logger.info("  Filings index: %d filings (%.1f s)", len(filings_index), time.time() - t1)

    if filings_index.empty:
        logger.warning("No filings found -- aborting holdings extraction")
        return pd.DataFrame()

    # Step 2: Download XBRL instances
    logger.info("")
    logger.info("-- Step 2: Downloading XBRL instance documents --")
    t2 = time.time()
    filings_index = _download_xbrl_instances(client, filings_index)
    logger.info("  XBRL download complete (%.1f s)", time.time() - t2)

    # Step 3: Parse all filings
    logger.info("")
    logger.info("-- Step 3: Parsing XBRL holdings --")
    t3 = time.time()
    holdings = _parse_all_filings(filings_index)
    logger.info("  Parsing complete (%.1f s)", time.time() - t3)

    # Summary
    total_time = time.time() - t0
    logger.info("")
    logger.info("=" * 60)
    logger.info("BDC HOLDINGS EXTRACTION -- COMPLETE (%.1f s)", total_time)
    logger.info("=" * 60)
    if not holdings.empty:
        logger.info("  Total holding records: %d", len(holdings))
        logger.info("  Unique CIKs with holdings: %d",
                     holdings["cik"].nunique() if "cik" in holdings.columns else 0)
        logger.info("  Unique investees: %d",
                     holdings["investment_identifier"].nunique()
                     if "investment_identifier" in holdings.columns else 0)
        logger.info("  Filings with holdings: %d",
                     holdings["accession_number"].nunique()
                     if "accession_number" in holdings.columns else 0)
    else:
        logger.warning("  No holdings extracted")

    return holdings


# ===========================================================================
# HTML download (pre-XBRL filings)
# ===========================================================================

def download_html_filing(
    client: EdgarClient,
    cik: str,
    accession: str,
    primary_doc: str,
    *,
    agent: str = "",
    reason: str = "bdc_html_filing",
) -> Path | None:
    """Download a BDC HTML primary document through the audited guard.

    Caches to BDC_HTML_CACHE_DIR / cik / {accession_nodashes}.html.
    Returns cached file path or None on failure.
    """
    from pipeline.sec_download_guard import download_bdc_html

    record = download_bdc_html(
        client=client,
        cik=cik,
        accession=accession,
        primary_doc=primary_doc,
        agent=agent,
        reason=reason,
    )
    if record.get("status") in {"cached", "downloaded"}:
        path = Path(str(record.get("cache_path", "")))
        if not path.is_absolute():
            path = Path(__file__).resolve().parent.parent / path
        return path
    logger.debug(
        "HTML download failed for CIK %s accession %s: %s",
        cik,
        accession,
        record.get("error") or record.get("stage"),
    )
    return None
