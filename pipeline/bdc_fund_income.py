"""Extract fund-level income facts from cached BDC XBRL filings.

BDC 10-K/10-Q XBRL files contain income statement facts alongside the
schedule of investments. This module extracts total investment income,
interest income, fee income, and net investment income for each filing
period. These are used to compute per-filer "fee uplift" -- the residual
yield not explained by coupons and PIK (i.e. origination fees, amendment
fees, prepayment penalties, OID accretion).

Public API
----------
extract_bdc_fund_income(filings_index=None) -> pd.DataFrame
"""

import logging
import time
from datetime import date
from typing import Any, Optional

import pandas as pd
from lxml import etree

from pipeline.config import (
    BDC_FILINGS_INDEX_FILE,
    BDC_FUND_INCOME_FILE,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Fund-level income concept map
# Substring-match-first-wins (same pattern as bdc_filings.CONCEPT_MAP).
# Longer substrings MUST appear before shorter ones.
# ---------------------------------------------------------------------------
FUND_INCOME_CONCEPT_MAP = [
    ("grossinvestmentincomeoperating", "total_investment_income"),
    ("investmentincomenonoperating", "nonoperating_income"),
    ("investmentincomedividend", "dividend_income"),
    ("investmentincomeinterest", "interest_income"),
    ("feeincome", "fee_income"),
    ("otherincome", "other_income"),
    ("netinvestmentincome", "net_investment_income"),
    ("investmentincomenet", "net_investment_income"),
    ("managementfeeexpense", "management_fee"),
    ("performancebasedincentivefee", "incentive_fee"),
    ("interestexpenseborrowings", "interest_expense"),
    ("interestexpense", "interest_expense"),
    ("investmentincomeinvestmentexpense", "total_expenses"),
    ("totalinvestmentincome", "total_investment_income"),
]

# Output columns for the fund income DataFrame
INCOME_COLUMNS = [
    "cik", "entity_name", "report_quarter", "report_date",
    "form_type", "accession_number", "start_date", "end_date",
    "duration_months",
    "total_investment_income", "interest_income", "dividend_income",
    "fee_income", "other_income", "net_investment_income",
    "management_fee", "incentive_fee", "interest_expense",
    "total_expenses",
]


# ---------------------------------------------------------------------------
# Helpers (reuse patterns from bdc_filings.py)
# ---------------------------------------------------------------------------

def _local_name(tag: str) -> str:
    """Strip namespace URI from an lxml tag."""
    if not isinstance(tag, str):
        return ""
    if tag.startswith("{"):
        return tag.split("}", 1)[1]
    if ":" in tag:
        return tag.split(":", 1)[1]
    return tag


def _match_income_concept(local_lower: str) -> Optional[str]:
    """Match a lowercase local name to an income column."""
    for pattern, col in FUND_INCOME_CONCEPT_MAP:
        if pattern in local_lower:
            return col
    return None


# ---------------------------------------------------------------------------
# Context parser for duration contexts
# ---------------------------------------------------------------------------

def _parse_income_contexts(tree: etree._ElementTree) -> dict:
    """Parse <xbrli:context> elements and identify entity-level duration contexts.

    Returns dict keyed by context ID with:
        start_date, end_date, duration_months, has_dimensions
    """
    root = tree.getroot()
    contexts: dict[str, dict] = {}

    for ctx in root.iter():
        if _local_name(ctx.tag) != "context":
            continue

        ctx_id = ctx.get("id", "")
        if not ctx_id:
            continue

        start_date = ""
        end_date = ""
        is_instant = False

        for child in ctx:
            ln = _local_name(child.tag)
            if ln == "period":
                for pc in child:
                    pln = _local_name(pc.tag)
                    if pln == "startDate":
                        start_date = (pc.text or "").strip()
                    elif pln == "endDate":
                        end_date = (pc.text or "").strip()
                    elif pln == "instant":
                        is_instant = True

        # Skip instant contexts -- income is a flow (duration) concept
        if is_instant or not start_date or not end_date:
            continue

        # Check for dimensions (typed or explicit members)
        has_dimensions = False
        for seg in ctx.iter():
            seg_ln = _local_name(seg.tag)
            if seg_ln in ("typedMember", "explicitMember"):
                has_dimensions = True
                break

        # Compute duration in months
        # Financial periods end at month-end: Jan 1 - Mar 31 = 3 months.
        # Raw (ed.month - sd.month) gives 2; add 1 for end-of-month dates.
        try:
            sd = date.fromisoformat(start_date)
            ed = date.fromisoformat(end_date)
            duration_months = (ed.year - sd.year) * 12 + (ed.month - sd.month)
            if ed.day >= 28:
                duration_months += 1
        except (ValueError, TypeError):
            duration_months = 0

        contexts[ctx_id] = {
            "start_date": start_date,
            "end_date": end_date,
            "duration_months": duration_months,
            "has_dimensions": has_dimensions,
        }

    return contexts


# ---------------------------------------------------------------------------
# Fact extractor
# ---------------------------------------------------------------------------

def _extract_fund_income_facts(
    tree: etree._ElementTree,
    contexts: dict,
) -> list[dict[str, Any]]:
    """Extract fund-level income facts from entity-level duration contexts.

    Returns one dict per unique (start_date, end_date) period.
    """
    # Only entity-level contexts (no dimensions)
    entity_ctx_ids = {
        cid for cid, info in contexts.items()
        if not info["has_dimensions"]
    }
    if not entity_ctx_ids:
        return []

    # Accumulate facts by (start_date, end_date)
    facts_by_period: dict[tuple, dict[str, Any]] = {}

    root = tree.getroot()
    for elem in root.iter():
        ctx_ref = elem.get("contextRef")
        if ctx_ref is None or ctx_ref not in entity_ctx_ids:
            continue

        # Skip nil
        nil = elem.get("{http://www.w3.org/2001/XMLSchema-instance}nil")
        if nil and nil.lower() == "true":
            continue

        local = _local_name(elem.tag).lower()
        raw_text = (elem.text or "").strip()
        if not raw_text:
            continue

        col = _match_income_concept(local)
        if col is None:
            continue

        # Parse numeric value
        try:
            value = float(raw_text.replace(",", ""))
        except (ValueError, TypeError):
            continue

        ctx_info = contexts[ctx_ref]
        period_key = (ctx_info["start_date"], ctx_info["end_date"])

        if period_key not in facts_by_period:
            facts_by_period[period_key] = {
                "start_date": ctx_info["start_date"],
                "end_date": ctx_info["end_date"],
                "duration_months": ctx_info["duration_months"],
            }

        # Keep first non-None value per column
        if col not in facts_by_period[period_key]:
            facts_by_period[period_key][col] = value

    return list(facts_by_period.values())


# ---------------------------------------------------------------------------
# Quarterly derivation
# ---------------------------------------------------------------------------

def _derive_quarterly_income(
    raw_facts: list[dict[str, Any]],
    filing_meta: dict[str, str],
) -> list[dict[str, Any]]:
    """Convert raw income periods to quarterly records.

    Logic:
    - Direct quarterly (2-4 months): use as-is
    - Annual (11-13 months): divide by 4
    - Other durations: divide by (duration_months / 3)
    """
    if not raw_facts:
        return []

    # Income columns to scale
    scalable_cols = [
        "total_investment_income", "interest_income", "dividend_income",
        "fee_income", "other_income", "net_investment_income",
        "management_fee", "incentive_fee", "interest_expense",
        "total_expenses",
    ]

    records = []
    for fact in raw_facts:
        dm = fact.get("duration_months", 0)
        if dm <= 0:
            continue

        # Determine scaling factor
        if 2 <= dm <= 4:
            scale = 1.0  # Already quarterly
        elif 11 <= dm <= 13:
            scale = 1.0 / 4.0  # Annual -> quarterly
        else:
            scale = 3.0 / dm  # General case

        # Build quarterly record
        record = {
            "cik": filing_meta.get("cik", ""),
            "entity_name": filing_meta.get("entity_name", ""),
            "form_type": filing_meta.get("form_type", ""),
            "accession_number": filing_meta.get("accession_number", ""),
            "start_date": fact["start_date"],
            "end_date": fact["end_date"],
            "duration_months": dm,
        }

        # Derive quarter label from end_date
        try:
            ed = date.fromisoformat(fact["end_date"])
            q = (ed.month - 1) // 3 + 1
            record["report_quarter"] = f"{ed.year}q{q}"
            record["report_date"] = fact["end_date"]
        except (ValueError, TypeError):
            record["report_quarter"] = ""
            record["report_date"] = fact["end_date"]

        # Scale income values
        for col in scalable_cols:
            val = fact.get(col)
            if val is not None:
                record[col] = val * scale
            else:
                record[col] = None

        records.append(record)

    return records


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def extract_bdc_fund_income(
    filings_index: Optional[pd.DataFrame] = None,
) -> pd.DataFrame:
    """Extract fund-level income from cached BDC XBRL files.

    Parameters
    ----------
    filings_index : DataFrame, optional
        Filings index with xbrl_download_status and xbrl_local_path.
        Loaded from disk if None.

    Returns
    -------
    DataFrame with quarterly fund-level income per CIK.
    """
    t0 = time.time()

    if filings_index is None:
        if not BDC_FILINGS_INDEX_FILE.exists():
            logger.warning("No filings index found at %s", BDC_FILINGS_INDEX_FILE)
            return pd.DataFrame(columns=INCOME_COLUMNS)
        filings_index = pd.read_csv(BDC_FILINGS_INDEX_FILE, dtype=str)
        logger.info("Loaded filings index: %d rows", len(filings_index))

    # Filter to cached XBRL files
    cached = filings_index[
        filings_index["xbrl_download_status"].isin(["cached", "downloaded"])
        & filings_index["xbrl_local_path"].notna()
        & (filings_index["xbrl_local_path"] != "")
    ].copy()
    logger.info("Processing %d cached XBRL files for fund-level income", len(cached))

    if cached.empty:
        return pd.DataFrame(columns=INCOME_COLUMNS)

    all_records: list[dict] = []
    parsed = 0
    errors = 0

    for _, row in cached.iterrows():
        xml_path = row["xbrl_local_path"]
        filing_meta = {
            "cik": str(row.get("cik", "")),
            "entity_name": str(row.get("entity_name", "")),
            "form_type": str(row.get("form_type", "")),
            "accession_number": str(row.get("accession_number", "")),
        }

        try:
            tree = etree.parse(xml_path)
            contexts = _parse_income_contexts(tree)
            raw_facts = _extract_fund_income_facts(tree, contexts)
            quarterly = _derive_quarterly_income(raw_facts, filing_meta)
            all_records.extend(quarterly)
            parsed += 1
        except Exception as exc:
            errors += 1
            if errors <= 5:
                logger.debug("Error parsing %s: %s", xml_path, exc)

    logger.info("Parsed %d filings (%d errors), produced %d quarterly records",
                parsed, errors, len(all_records))

    if not all_records:
        return pd.DataFrame(columns=INCOME_COLUMNS)

    df = pd.DataFrame(all_records)

    # Ensure all columns exist
    for col in INCOME_COLUMNS:
        if col not in df.columns:
            df[col] = None

    # Dedup: same CIK + quarter from multiple filings
    # Prefer actual quarterly (dm=3-4) over annual (dm=11-13) over stubs (dm=1-2)
    df["_dm_int"] = pd.to_numeric(df["duration_months"], errors="coerce").fillna(0).astype(int)
    df["_dm_pref"] = df["_dm_int"].apply(
        lambda x: 0 if 3 <= x <= 4 else (1 if 11 <= x <= 13 else 2)
    )
    df["_form_rank"] = df["form_type"].apply(
        lambda x: 0 if "10-K" in str(x) else 1
    )
    df = df.sort_values(
        ["cik", "report_quarter", "_dm_pref", "_dm_int", "_form_rank"],
        ascending=[True, True, True, True, True],
    )
    df = df.drop_duplicates(subset=["cik", "report_quarter"], keep="first")
    df = df.drop(columns=["_form_rank", "_dm_pref", "_dm_int"])

    # Save
    df = df[INCOME_COLUMNS]
    df.to_csv(BDC_FUND_INCOME_FILE, index=False)

    n_ciks = df["cik"].nunique()
    n_quarters = df["report_quarter"].nunique()
    logger.info("Fund income: %d rows, %d CIKs, %d quarters",
                len(df), n_ciks, n_quarters)

    if not df["total_investment_income"].isna().all():
        median_tii = pd.to_numeric(df["total_investment_income"], errors="coerce").median()
        logger.info("  Median total_investment_income: $%.0f", median_tii)

    elapsed = time.time() - t0
    logger.info("Fund income extraction complete in %.1f s", elapsed)

    return df
