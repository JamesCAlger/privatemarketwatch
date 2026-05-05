"""Extract per-industry aggregate data from cached BDC XBRL filings.

BDC 10-K/10-Q XBRL files contain sector-level aggregates (total FV, cost,
% of net assets per industry) via the ``EquitySecuritiesByIndustryAxis``
dimension.  This module extracts those aggregates into a flat CSV for
sector concentration analytics on fund pages and at the index level.

The industry axis is reported by ~174/229 BDCs with XBRL data.  It carries
aggregate totals (one row per industry per filing), NOT per-position data.

Public API
----------
extract_bdc_sector_breakdown(filings_index=None) -> pd.DataFrame
"""

import logging
import re
import time
from typing import Any, Optional

import pandas as pd
from lxml import etree

from pipeline.config import (
    BDC_FILINGS_INDEX_FILE,
    BDC_SECTOR_BREAKDOWN_FILE,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Target concepts
# ---------------------------------------------------------------------------
SECTOR_CONCEPT_MAP = [
    ("investmentownedatfairvalue", "fair_value"),
    ("investmentownedatcost", "cost"),
    ("investmentownedpercentofnetassets", "pct_of_net_assets"),
    ("concentrationriskpercentage1", "pct_of_net_assets"),
]

# Dimension local-name for the industry axis
INDUSTRY_AXIS = "equitysecuritiesbyindustryaxis"

# Axes whose members we want to capture alongside industry
INVESTMENT_TYPE_AXIS = "investmenttypeaxis"
AFFILIATION_AXIS = "investmentissueraffiliationaxis"

# Axes that mark position-level contexts (skip these)
POSITION_AXES = {"investmentidentifieraxis"}

# Output columns
SECTOR_COLUMNS = [
    "cik", "entity_name", "report_date", "industry_sector",
    "investment_type", "fair_value", "cost", "pct_of_net_assets",
    "gics_sub_industry",
]

# Regex: insert space before each uppercase letter that follows a lowercase
_CAMEL_RE = re.compile(r"(?<=[a-z])(?=[A-Z])")


# ---------------------------------------------------------------------------
# Helpers
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


def _strip_member_suffix(name: str) -> str:
    """Remove [Member] / Member suffix from an XBRL member name."""
    if name.endswith("Member"):
        name = name[:-6]
    if name.endswith("Sector"):
        name = name[:-6]
    return name


def _camel_to_words(name: str) -> str:
    """Convert CamelCase to space-separated lowercase words.

    Example: ``HealthcareEducationAndChildcare`` -> ``healthcare education and childcare``
    """
    return _CAMEL_RE.sub(" ", name).lower()


def normalize_member_name(raw: str) -> str:
    """Normalize an XBRL member name to a readable industry label.

    Strips namespace prefix, removes Member/Sector suffix, converts
    CamelCase to space-separated words.
    """
    # Strip namespace prefix (e.g., "glad:" or "us-gaap:")
    if ":" in raw:
        raw = raw.split(":", 1)[1]
    raw = _strip_member_suffix(raw)
    return _camel_to_words(raw)


def _match_sector_concept(local_lower: str) -> Optional[str]:
    """Match a lowercase local name to a sector output column."""
    for pattern, col in SECTOR_CONCEPT_MAP:
        if pattern in local_lower:
            return col
    return None


# ---------------------------------------------------------------------------
# Context parser for industry-dimensioned instant contexts
# ---------------------------------------------------------------------------

def _parse_sector_contexts(tree: etree._ElementTree) -> dict:
    """Parse ``<xbrli:context>`` elements and find industry-dimensioned contexts.

    Returns dict keyed by context ID with:
        instant_date, industry_member, investment_type_member
    Skips contexts that also carry InvestmentIdentifierAxis (position-level).
    Skips duration contexts (industry FV is point-in-time).
    """
    root = tree.getroot()
    contexts: dict[str, dict] = {}

    for ctx in root.iter():
        if _local_name(ctx.tag) != "context":
            continue

        ctx_id = ctx.get("id", "")
        if not ctx_id:
            continue

        instant_date = ""
        is_instant = False

        for child in ctx:
            ln = _local_name(child.tag)
            if ln == "period":
                for pc in child:
                    pln = _local_name(pc.tag)
                    if pln == "instant":
                        is_instant = True
                        instant_date = (pc.text or "").strip()

        # Industry FV is a balance-sheet concept (point-in-time)
        if not is_instant or not instant_date:
            # Also allow duration contexts for concentration risk percentages
            start_date = ""
            end_date = ""
            for child in ctx:
                ln = _local_name(child.tag)
                if ln == "period":
                    for pc in child:
                        pln = _local_name(pc.tag)
                        if pln == "startDate":
                            start_date = (pc.text or "").strip()
                        elif pln == "endDate":
                            end_date = (pc.text or "").strip()
            if not end_date:
                continue
            # Use end_date as the reporting date for duration contexts
            instant_date = end_date

        # Scan for dimensions
        industry_member = ""
        investment_type_member = ""
        has_position_axis = False

        for seg in ctx.iter():
            seg_ln = _local_name(seg.tag)
            if seg_ln == "explicitMember":
                dim_attr = seg.get("dimension", "")
                dim_local = _local_name(dim_attr).lower()
                member_val = (seg.text or "").strip()

                if dim_local == INDUSTRY_AXIS:
                    industry_member = member_val
                elif dim_local == INVESTMENT_TYPE_AXIS:
                    investment_type_member = member_val
                elif dim_local in POSITION_AXES:
                    has_position_axis = True
                    break
            elif seg_ln == "typedMember":
                dim_attr = seg.get("dimension", "")
                dim_local = _local_name(dim_attr).lower()
                if dim_local in POSITION_AXES:
                    has_position_axis = True
                    break

        if has_position_axis or not industry_member:
            continue

        contexts[ctx_id] = {
            "instant_date": instant_date,
            "industry_member": industry_member,
            "investment_type_member": investment_type_member,
        }

    return contexts


# ---------------------------------------------------------------------------
# Fact extractor
# ---------------------------------------------------------------------------

def _extract_sector_facts(
    tree: etree._ElementTree,
    contexts: dict,
) -> list[dict[str, Any]]:
    """Extract industry-level facts from the parsed contexts.

    Returns one dict per unique (instant_date, industry_member, investment_type_member).
    """
    if not contexts:
        return []

    ctx_ids = set(contexts.keys())

    # Accumulate by (date, industry, type)
    facts_by_key: dict[tuple, dict[str, Any]] = {}

    root = tree.getroot()
    for elem in root.iter():
        ctx_ref = elem.get("contextRef")
        if ctx_ref is None or ctx_ref not in ctx_ids:
            continue

        # Skip nil
        nil = elem.get("{http://www.w3.org/2001/XMLSchema-instance}nil")
        if nil and nil.lower() == "true":
            continue

        local = _local_name(elem.tag).lower()
        raw_text = (elem.text or "").strip()
        if not raw_text:
            continue

        col = _match_sector_concept(local)
        if col is None:
            continue

        # Parse numeric value
        try:
            value = float(raw_text.replace(",", ""))
        except (ValueError, TypeError):
            continue

        ctx_info = contexts[ctx_ref]
        key = (
            ctx_info["instant_date"],
            ctx_info["industry_member"],
            ctx_info["investment_type_member"],
        )

        if key not in facts_by_key:
            facts_by_key[key] = {
                "report_date": ctx_info["instant_date"],
                "industry_member_raw": ctx_info["industry_member"],
                "investment_type_raw": ctx_info["investment_type_member"],
            }

        # Keep first non-None value per column
        if col not in facts_by_key[key]:
            facts_by_key[key][col] = value

    return list(facts_by_key.values())


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def extract_bdc_sector_breakdown(
    filings_index: Optional[pd.DataFrame] = None,
) -> pd.DataFrame:
    """Extract per-industry aggregates from cached BDC XBRL files.

    Parameters
    ----------
    filings_index : DataFrame, optional
        Filings index with xbrl_download_status and xbrl_local_path.
        Loaded from disk if None.

    Returns
    -------
    DataFrame with per-CIK, per-quarter, per-industry sector breakdown.
    """
    t0 = time.time()

    if filings_index is None:
        if not BDC_FILINGS_INDEX_FILE.exists():
            logger.warning("No filings index found at %s",
                           BDC_FILINGS_INDEX_FILE)
            return pd.DataFrame(columns=SECTOR_COLUMNS)
        filings_index = pd.read_csv(BDC_FILINGS_INDEX_FILE, dtype=str)
        logger.info("Loaded filings index: %d rows", len(filings_index))

    # Filter to cached XBRL files
    cached = filings_index[
        filings_index["xbrl_download_status"].isin(["cached", "downloaded"])
        & filings_index["xbrl_local_path"].notna()
        & (filings_index["xbrl_local_path"] != "")
    ].copy()
    logger.info("Processing %d cached XBRL files for sector breakdown",
                len(cached))

    if cached.empty:
        return pd.DataFrame(columns=SECTOR_COLUMNS)

    all_records: list[dict] = []
    parsed = 0
    errors = 0
    ciks_with_data: set[str] = set()

    for _, row in cached.iterrows():
        xml_path = row["xbrl_local_path"]
        cik = str(row.get("cik", ""))
        entity_name = str(row.get("entity_name", ""))

        try:
            tree = etree.parse(xml_path)
            contexts = _parse_sector_contexts(tree)
            raw_facts = _extract_sector_facts(tree, contexts)

            for fact in raw_facts:
                record = {
                    "cik": cik,
                    "entity_name": entity_name,
                    "report_date": fact["report_date"],
                    "industry_sector": normalize_member_name(
                        fact["industry_member_raw"]
                    ),
                    "investment_type": (
                        normalize_member_name(fact["investment_type_raw"])
                        if fact.get("investment_type_raw")
                        else ""
                    ),
                    "fair_value": fact.get("fair_value"),
                    "cost": fact.get("cost"),
                    "pct_of_net_assets": fact.get("pct_of_net_assets"),
                }
                all_records.append(record)

            if raw_facts:
                ciks_with_data.add(cik)
            parsed += 1
        except Exception as exc:
            errors += 1
            if errors <= 5:
                logger.debug("Error parsing %s: %s", xml_path, exc)

    logger.info(
        "Parsed %d filings (%d errors), produced %d sector rows from %d CIKs",
        parsed, errors, len(all_records), len(ciks_with_data),
    )

    if not all_records:
        return pd.DataFrame(columns=SECTOR_COLUMNS)

    df = pd.DataFrame(all_records)

    # Ensure all columns exist
    for col in SECTOR_COLUMNS:
        if col not in df.columns:
            df[col] = None

    # Dedup: same (cik, report_date, industry_sector, investment_type) from
    # multiple contexts — keep the row with the most populated fields.
    dedup_cols = ["cik", "report_date", "industry_sector", "investment_type"]
    df["_populated"] = (
        df["fair_value"].notna().astype(int)
        + df["cost"].notna().astype(int)
        + df["pct_of_net_assets"].notna().astype(int)
    )
    df = df.sort_values(
        dedup_cols + ["_populated"],
        ascending=[True, True, True, True, False],
    )
    df = df.drop_duplicates(subset=dedup_cols, keep="first")
    df = df.drop(columns=["_populated"])

    # Map industry labels to GICS sub-industry names
    from pipeline.gics_mapping import map_to_gics

    unique_labels = df["industry_sector"].dropna().unique().tolist()
    label_map = map_to_gics(unique_labels)
    df["gics_sub_industry"] = (
        df["industry_sector"].map(label_map).fillna("Other")
    )

    # Save
    df = df[SECTOR_COLUMNS]
    df.to_csv(BDC_SECTOR_BREAKDOWN_FILE, index=False)

    n_ciks = df["cik"].nunique()
    n_dates = df["report_date"].nunique()
    n_sectors = df["industry_sector"].nunique()
    logger.info(
        "Sector breakdown: %d rows, %d CIKs, %d report dates, %d sectors",
        len(df), n_ciks, n_dates, n_sectors,
    )

    if not df["fair_value"].isna().all():
        total_fv = pd.to_numeric(df["fair_value"], errors="coerce").sum()
        logger.info("  Total FV across all sectors: $%.0f", total_fv)

    elapsed = time.time() - t0
    logger.info("Sector breakdown extraction complete in %.1f s", elapsed)

    return df
