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
    BDC_INSTRUMENT_TYPE_BREAKDOWN_FILE,
    BDC_LIEN_BREAKDOWN_FILE,
    BDC_SECTOR_BREAKDOWN_FILE,
)
from pipeline.bdc_lien_hierarchy import _instrument_type, _lien_tier

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

# Dimension local-names for the industry axis (standard + custom filer axes)
INDUSTRY_AXES = {
    "equitysecuritiesbyindustryaxis",                       # us-gaap (188 CIKs)
    "investmentsclassificationbyindustryaxis",              # NexPoint/Blue Owl (CIK 1588272)
    "typeofindustryaxis",                                   # SLR Private Credit II (CIK 1932591)
    "classificationofindustrybasedonnatureofbusinessaxis",  # PIMCO Capital Solutions (CIK 1905824)
}

# Axes whose members we want to capture alongside industry
INVESTMENT_TYPE_AXIS = "investmenttypeaxis"
AFFILIATION_AXIS = "investmentissueraffiliationaxis"

# Axes that mark position-level contexts (skip these)
POSITION_AXES = {
    "investmentidentifieraxis",
    "investmentissuernameaxis",
    "investmentsecondarycategorizationaxis",
    "portfoliocompaniesaxis",
    "legalentityaxis",
    "ownershipaxis",
    "relatedpartytransactionsbyrelatedpartyaxis",
    "scheduleofequitymethodinvestmentequitymethodinvesteenameaxis",
}

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

                if dim_local in INDUSTRY_AXES:
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


# ---------------------------------------------------------------------------
# Lien breakdown (same hierarchical subtotal facts, lien dimension)
# ---------------------------------------------------------------------------
#
# Hierarchical-tagging filers (Blackstone, HPS, ...) tag lien tier on the
# same subtotal contexts that carry the sector member.  This reads those
# lien-bearing subtotals DIRECTLY (the filer's own totals) -- the aggregate
# analogue of the sector breakdown.  It does NOT map lien to individual
# positions (see pipeline.bdc_lien_hierarchy for that).

LIEN_BREAKDOWN_COLUMNS = [
    "cik", "entity_name", "report_date", "lien_tier",
    "fair_value", "cost", "grain",
]


def _parse_lien_contexts(tree: etree._ElementTree) -> dict:
    """Find lien-dimensioned (non-position) contexts.

    Returns dict ctx_id -> {instant_date, lien_tier, has_industry, is_pure_tier}.
    ``lien_tier`` is detected from the member name (filer-prefixed axis), so it
    is axis-name agnostic.  ``is_pure_tier`` means the only non-period
    dimension is the lien axis (a tier total); ``has_industry`` means it is a
    lien x sector subtotal.
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
            if _local_name(child.tag) == "period":
                for pc in child:
                    if _local_name(pc.tag) == "instant":
                        is_instant = True
                        instant_date = (pc.text or "").strip()
        if not is_instant or not instant_date:
            continue  # lien FV is point-in-time

        lien_tier = None
        has_industry = False
        n_other_axes = 0
        skip = False
        for seg in ctx.iter():
            seg_ln = _local_name(seg.tag)
            if seg_ln == "explicitMember":
                dim_local = _local_name(seg.get("dimension", "")).lower()
                member_local = (seg.text or "").strip().rsplit(":", 1)[-1]
                tier = _lien_tier(member_local)
                if tier:
                    lien_tier = tier
                elif dim_local in POSITION_AXES:
                    skip = True
                    break
                else:
                    if dim_local in INDUSTRY_AXES:
                        has_industry = True
                    n_other_axes += 1
            elif seg_ln == "typedMember":
                if _local_name(seg.get("dimension", "")).lower() in POSITION_AXES:
                    skip = True
                    break
                n_other_axes += 1

        if skip or not lien_tier:
            continue
        contexts[ctx_id] = {
            "instant_date": instant_date,
            "lien_tier": lien_tier,
            "has_industry": has_industry,
            "is_pure_tier": n_other_axes == 0,
        }
    return contexts


def _extract_lien_facts(tree: etree._ElementTree, contexts: dict) -> list[dict]:
    """One record per lien context with its FV/cost (first non-nil fact)."""
    if not contexts:
        return []
    ctx_ids = set(contexts.keys())
    per_ctx: dict[str, dict] = {}
    root = tree.getroot()
    for elem in root.iter():
        ctx_ref = elem.get("contextRef")
        if ctx_ref is None or ctx_ref not in ctx_ids:
            continue
        nil = elem.get("{http://www.w3.org/2001/XMLSchema-instance}nil")
        if nil and nil.lower() == "true":
            continue
        raw_text = (elem.text or "").strip()
        if not raw_text:
            continue
        col = _match_sector_concept(_local_name(elem.tag).lower())
        if col not in ("fair_value", "cost"):
            continue
        try:
            value = float(raw_text.replace(",", ""))
        except (ValueError, TypeError):
            continue
        rec = per_ctx.setdefault(ctx_ref, {**contexts[ctx_ref]})
        if col not in rec:
            rec[col] = value
    return [r for r in per_ctx.values() if "fair_value" in r]


def _aggregate_lien_tiers(records: list[dict]) -> list[dict]:
    """Per (date, lien_tier): prefer summing lien x sector subtotals; fall back
    to the pure lien-tier total.  Avoids double counting alternate partitions."""
    by_date_tier: dict[tuple, dict] = {}
    for r in records:
        by_date_tier.setdefault((r["instant_date"], r["lien_tier"]), []).append(r)
    out = []
    for (date, tier), recs in by_date_tier.items():
        sector_recs = [r for r in recs if r["has_industry"]]
        if sector_recs:
            fv = sum(r.get("fair_value", 0.0) for r in sector_recs)
            cost = sum(r.get("cost", 0.0) for r in sector_recs if r.get("cost") is not None)
            grain = "lien_sector_sum"
        else:
            pure = [r for r in recs if r["is_pure_tier"]]
            if not pure:
                continue  # only alternate partitions (e.g., lien x affiliation) -> ambiguous, skip
            fv = sum(r.get("fair_value", 0.0) for r in pure)
            cost = sum(r.get("cost", 0.0) for r in pure if r.get("cost") is not None)
            grain = "lien_only"
        out.append({"report_date": date, "lien_tier": tier,
                    "fair_value": fv, "cost": cost or None, "grain": grain})
    return out


# ---------------------------------------------------------------------------
# Instrument-type breakdown (revolver / delayed draw / term loan / unitranche)
# ---------------------------------------------------------------------------
# The aggregate analogue of the lien breakdown, on the instrument-type axis.
# Filers tag instrument type on the SAME subtotal contexts as lien -- often the
# SAME combined member (e.g. FirstLienSeniorSecuredTermLoanMember carries both),
# or a dedicated investmenttypeaxis member.  Detected name-based via
# ``_instrument_type`` (axis-agnostic), validated by the SAME grain/reconciliation
# logic as lien (prefer the type x sector subtotal sum; fall back to the pure
# type total; skip position-axis contexts and ambiguous alternate partitions).

INSTRUMENT_TYPE_BREAKDOWN_COLUMNS = [
    "cik", "entity_name", "report_date", "instrument_type",
    "fair_value", "cost", "grain",
]


def _parse_instrument_contexts(tree: etree._ElementTree) -> dict:
    """Find instrument-type-dimensioned (non-position) contexts.

    Mirror of :func:`_parse_lien_contexts` on the instrument-type axis. Returns
    ctx_id -> {instant_date, instrument_type, has_industry, is_pure_tier}.
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
            if _local_name(child.tag) == "period":
                for pc in child:
                    if _local_name(pc.tag) == "instant":
                        is_instant = True
                        instant_date = (pc.text or "").strip()
        if not is_instant or not instant_date:
            continue  # FV is point-in-time

        instrument_type = None
        has_industry = False
        n_other_axes = 0
        skip = False
        for seg in ctx.iter():
            seg_ln = _local_name(seg.tag)
            if seg_ln == "explicitMember":
                dim_local = _local_name(seg.get("dimension", "")).lower()
                member_local = (seg.text or "").strip().rsplit(":", 1)[-1]
                itype = _instrument_type(member_local)
                if itype:
                    instrument_type = itype
                    # a combined lien+type member also carries lien -- not an
                    # "other axis" for our grain accounting.
                elif dim_local in POSITION_AXES:
                    skip = True
                    break
                elif _lien_tier(member_local):
                    # lien-only member alongside the type axis -> not an extra
                    # partition for double-count purposes (type x lien is fine).
                    pass
                else:
                    if dim_local in INDUSTRY_AXES:
                        has_industry = True
                    n_other_axes += 1
            elif seg_ln == "typedMember":
                if _local_name(seg.get("dimension", "")).lower() in POSITION_AXES:
                    skip = True
                    break
                n_other_axes += 1

        if skip or not instrument_type:
            continue
        contexts[ctx_id] = {
            "instant_date": instant_date,
            "instrument_type": instrument_type,
            "has_industry": has_industry,
            "is_pure_tier": n_other_axes == 0,
        }
    return contexts


def _aggregate_instrument_types(records: list[dict]) -> list[dict]:
    """Per (date, instrument_type): prefer summing type x sector subtotals; fall
    back to the pure type total. Mirror of :func:`_aggregate_lien_tiers`."""
    by_date_type: dict[tuple, dict] = {}
    for r in records:
        by_date_type.setdefault((r["instant_date"], r["instrument_type"]), []).append(r)
    out = []
    for (date, itype), recs in by_date_type.items():
        sector_recs = [r for r in recs if r["has_industry"]]
        if sector_recs:
            fv = sum(r.get("fair_value", 0.0) for r in sector_recs)
            cost = sum(r.get("cost", 0.0) for r in sector_recs if r.get("cost") is not None)
            grain = "type_sector_sum"
        else:
            pure = [r for r in recs if r["is_pure_tier"]]
            if not pure:
                continue  # only alternate partitions -> ambiguous, skip
            fv = sum(r.get("fair_value", 0.0) for r in pure)
            cost = sum(r.get("cost", 0.0) for r in pure if r.get("cost") is not None)
            grain = "type_only"
        out.append({"report_date": date, "instrument_type": itype,
                    "fair_value": fv, "cost": cost or None, "grain": grain})
    return out


def extract_bdc_instrument_type_breakdown(
    filings_index: Optional[pd.DataFrame] = None,
) -> pd.DataFrame:
    """Extract per-CIK, per-quarter instrument-type FV totals from cached BDC XBRL.

    The instrument-type analogue of :func:`extract_bdc_lien_breakdown`, using the
    same parse/aggregate/dedup machinery. Cache-only, no network.
    """
    t0 = time.time()
    if filings_index is None:
        if not BDC_FILINGS_INDEX_FILE.exists():
            logger.warning("No filings index at %s", BDC_FILINGS_INDEX_FILE)
            return pd.DataFrame(columns=INSTRUMENT_TYPE_BREAKDOWN_COLUMNS)
        filings_index = pd.read_csv(BDC_FILINGS_INDEX_FILE, dtype=str)

    cached = filings_index[
        filings_index["xbrl_download_status"].isin(["cached", "downloaded"])
        & filings_index["xbrl_local_path"].notna()
        & (filings_index["xbrl_local_path"] != "")
    ].copy()
    if cached.empty:
        return pd.DataFrame(columns=INSTRUMENT_TYPE_BREAKDOWN_COLUMNS)

    all_records: list[dict] = []
    parsed = errors = 0
    ciks_with_data: set[str] = set()
    for _, row in cached.iterrows():
        try:
            tree = etree.parse(row["xbrl_local_path"])
            contexts = _parse_instrument_contexts(tree)
            facts = _extract_lien_facts(tree, contexts)  # generic: FV/cost per context
            for rec in _aggregate_instrument_types(facts):
                rec.update({"cik": str(row.get("cik", "")),
                            "entity_name": str(row.get("entity_name", ""))})
                all_records.append(rec)
            if facts:
                ciks_with_data.add(str(row.get("cik", "")))
            parsed += 1
        except Exception as exc:
            errors += 1
            if errors <= 5:
                logger.debug("Error parsing %s for instrument-type breakdown: %s",
                             row.get("xbrl_local_path"), exc)

    if not all_records:
        logger.info("Instrument-type breakdown: 0 rows (%d filings, %d errors)", parsed, errors)
        return pd.DataFrame(columns=INSTRUMENT_TYPE_BREAKDOWN_COLUMNS)

    df = pd.DataFrame(all_records)
    for col in INSTRUMENT_TYPE_BREAKDOWN_COLUMNS:
        if col not in df.columns:
            df[col] = None
    # one row per (cik, report_date, instrument_type); prefer sector-sum grain
    df["_g"] = (df["grain"] == "type_sector_sum").astype(int)
    df = (df.sort_values(["cik", "report_date", "instrument_type", "_g"],
                         ascending=[True, True, True, False])
            .drop_duplicates(["cik", "report_date", "instrument_type"], keep="first")
            .drop(columns="_g"))
    df = df[INSTRUMENT_TYPE_BREAKDOWN_COLUMNS]
    BDC_INSTRUMENT_TYPE_BREAKDOWN_FILE.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(BDC_INSTRUMENT_TYPE_BREAKDOWN_FILE, index=False)
    logger.info(
        "Instrument-type breakdown: %d rows, %d CIKs, %d filings (%d errors) in %.1f s",
        len(df), len(ciks_with_data), parsed, errors, time.time() - t0,
    )
    return df


def extract_bdc_lien_breakdown(
    filings_index: Optional[pd.DataFrame] = None,
) -> pd.DataFrame:
    """Extract per-CIK, per-quarter lien-tier FV totals from cached BDC XBRL.

    Reads the filer's own lien subtotals (aggregate), the lien analogue of
    :func:`extract_bdc_sector_breakdown`.  Cache-only, no network.
    """
    t0 = time.time()
    if filings_index is None:
        if not BDC_FILINGS_INDEX_FILE.exists():
            logger.warning("No filings index at %s", BDC_FILINGS_INDEX_FILE)
            return pd.DataFrame(columns=LIEN_BREAKDOWN_COLUMNS)
        filings_index = pd.read_csv(BDC_FILINGS_INDEX_FILE, dtype=str)

    cached = filings_index[
        filings_index["xbrl_download_status"].isin(["cached", "downloaded"])
        & filings_index["xbrl_local_path"].notna()
        & (filings_index["xbrl_local_path"] != "")
    ].copy()
    if cached.empty:
        return pd.DataFrame(columns=LIEN_BREAKDOWN_COLUMNS)

    all_records: list[dict] = []
    parsed = errors = 0
    ciks_with_data: set[str] = set()
    for _, row in cached.iterrows():
        try:
            tree = etree.parse(row["xbrl_local_path"])
            contexts = _parse_lien_contexts(tree)
            facts = _extract_lien_facts(tree, contexts)
            for tier in _aggregate_lien_tiers(facts):
                tier.update({"cik": str(row.get("cik", "")),
                             "entity_name": str(row.get("entity_name", ""))})
                all_records.append(tier)
            if facts:
                ciks_with_data.add(str(row.get("cik", "")))
            parsed += 1
        except Exception as exc:
            errors += 1
            if errors <= 5:
                logger.debug("Error parsing %s for lien breakdown: %s",
                             row.get("xbrl_local_path"), exc)

    if not all_records:
        logger.info("Lien breakdown: 0 rows (%d filings, %d errors)", parsed, errors)
        return pd.DataFrame(columns=LIEN_BREAKDOWN_COLUMNS)

    df = pd.DataFrame(all_records)
    for col in LIEN_BREAKDOWN_COLUMNS:
        if col not in df.columns:
            df[col] = None
    # one row per (cik, report_date, lien_tier); prefer sector-sum grain
    df["_g"] = (df["grain"] == "lien_sector_sum").astype(int)
    df = (df.sort_values(["cik", "report_date", "lien_tier", "_g"],
                         ascending=[True, True, True, False])
            .drop_duplicates(["cik", "report_date", "lien_tier"], keep="first")
            .drop(columns="_g"))
    df = df[LIEN_BREAKDOWN_COLUMNS]
    BDC_LIEN_BREAKDOWN_FILE.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(BDC_LIEN_BREAKDOWN_FILE, index=False)
    logger.info(
        "Lien breakdown: %d rows, %d CIKs, %d filings (%d errors) in %.1f s",
        len(df), len(ciks_with_data), parsed, errors, time.time() - t0,
    )
    return df
