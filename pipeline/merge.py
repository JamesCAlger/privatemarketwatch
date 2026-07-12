"""Merge BDC and fund universes, validate against third-party lists.

Produces:
  - combined_universe.csv / .json
  - validation_report.csv
"""

import logging
import re
import uuid
from difflib import SequenceMatcher

import pandas as pd

from pipeline.config import (
    COMBINED_UNIVERSE_FILE,
    COMBINED_UNIVERSE_JSON,
    ENTITY_CURRENT_NAMES_FILE,
    VALIDATION_REPORT_FILE,
)

logger = logging.getLogger(__name__)

# Columns for the final combined universe
SCHEMA_COLUMNS = [
    "entity_id",
    "cik",
    "entity_name",
    "series_id",
    "fund_name",
    "file_number",
    "vehicle_type",
    "status",
    "activity_status",
    "election_date",
    "withdrawal_date",
    "first_filing_date",
    "last_filing_date",
    "latest_periodic_filing_date",
    "latest_periodic_filing_type",
    "discovery_methods",
    "data_sources",
    "in_third_party_lists",
    "adviser_name",
    "total_net_assets",
]


def _normalise_name(name: str) -> str:
    """Normalise an entity name for fuzzy matching."""
    if not isinstance(name, str):
        return ""
    name = name.lower().strip()
    # Remove parenthetical content (e.g. ticker, CIK annotations)
    name = re.sub(r"\(.*?\)", "", name)
    # Remove common legal suffixes
    for suffix in [
        " corporation", " incorporated", " limited",
        ", inc.", " inc.", " inc", ", llc", " llc",
        ", l.p.", " l.p.", ", lp", " lp",
        " corp.", " corp", " co.", " co",
        " fund", " trust", " capital",
        ", ltd.", " ltd.", " ltd",
    ]:
        name = name.replace(suffix, "")
    # Remove punctuation
    name = re.sub(r"[^a-z0-9\s]", "", name)
    name = re.sub(r"\s+", " ", name).strip()
    return name


def _fuzzy_match_score(a: str, b: str) -> float:
    """Return similarity ratio between two normalised names."""
    na = _normalise_name(a)
    nb = _normalise_name(b)
    if not na or not nb:
        return 0.0
    # Use both full ratio and partial containment
    full = SequenceMatcher(None, na, nb).ratio()
    # Boost score if one name fully contains the other
    if na in nb or nb in na:
        full = max(full, 0.85)
    return full


def _apply_entity_name_overlay(
    df: pd.DataFrame,
    overlay_file=ENTITY_CURRENT_NAMES_FILE,
) -> pd.DataFrame:
    """Overwrite ``entity_name`` with current SEC registrant names.

    Universe entity names come from EFTS ``display_names`` captured at
    discovery time, which are frozen at the filing-date name -- funds that
    rename after their election filing (e.g. Owl Rock -> Blue Owl) keep the
    stale name. ``scripts/refresh_entity_names.py`` snapshots current names
    from the SEC submissions API into ``overlay_file``; this applies them so
    refreshed names survive universe rebuilds.
    """
    if not overlay_file.exists():
        return df
    try:
        overlay = pd.read_csv(overlay_file, dtype=str)
    except Exception as exc:
        logger.warning("Could not read entity name overlay %s: %s",
                       overlay_file, exc)
        return df
    if overlay.empty or not {"cik", "entity_name"} <= set(overlay.columns):
        logger.warning("Entity name overlay %s missing cik/entity_name "
                       "columns -- skipping", overlay_file)
        return df
    overlay = overlay.dropna(subset=["cik", "entity_name"])
    overlay["cik"] = overlay["cik"].astype(str).str.strip().str.zfill(10)
    name_by_cik = dict(zip(overlay["cik"], overlay["entity_name"]))
    mapped = df["cik"].map(name_by_cik)
    changed = mapped.notna() & (mapped != df["entity_name"])
    if changed.any():
        df = df.copy()
        df.loc[changed, "entity_name"] = mapped[changed]
        logger.info("Entity name overlay: updated %d universe rows from %s",
                    int(changed.sum()), overlay_file.name)
    return df


def merge_universes(
    bdc_df: pd.DataFrame,
    fund_df: pd.DataFrame,
    third_party: dict[str, pd.DataFrame],
) -> pd.DataFrame:
    """Merge BDC + fund universes and validate against third-party lists.

    Returns the combined universe DataFrame.
    """
    logger.info("=" * 60)
    logger.info("MERGING UNIVERSES")
    logger.info("=" * 60)

    # ── 1. Combine BDC + Fund ──
    frames = [f for f in [bdc_df, fund_df] if f is not None and not f.empty]
    if not frames:
        logger.error("No data from either BDC or fund universe — nothing to merge")
        return pd.DataFrame(columns=SCHEMA_COLUMNS)

    combined = pd.concat(frames, ignore_index=True)

    # Deduplicate by CIK (+series_id if present)
    dedup_cols = ["cik"]
    if "series_id" in combined.columns:
        # Only dedup on series_id if it's non-null
        combined["_dedup_series"] = combined["series_id"].fillna("")
        combined = combined.sort_values("vehicle_type")  # prefer bdc, interval, tender
        combined = combined.drop_duplicates(
            subset=["cik", "_dedup_series"], keep="first"
        )
        combined = combined.drop(columns=["_dedup_series"])
    else:
        combined = combined.drop_duplicates(subset=["cik"], keep="first")

    # Ensure all schema columns exist
    for col in SCHEMA_COLUMNS:
        if col not in combined.columns:
            combined[col] = None

    # Generate entity IDs
    combined["entity_id"] = [
        f"EV-{str(uuid.uuid4())[:8].upper()}" for _ in range(len(combined))
    ]

    # Pad CIK to 10 digits
    combined["cik"] = combined["cik"].astype(str).str.strip().str.zfill(10)

    # Apply current-name overlay before third-party matching so fuzzy name
    # matching runs against up-to-date registrant names.
    combined = _apply_entity_name_overlay(combined)

    logger.info("Combined universe: %d entities before validation", len(combined))
    logger.info("  BDCs: %d", (combined["vehicle_type"] == "bdc").sum())
    logger.info("  Interval funds: %d",
                (combined["vehicle_type"] == "interval_fund").sum())
    logger.info("  Tender offer funds: %d",
                (combined["vehicle_type"] == "tender_offer_fund").sum())
    logger.info("  Unknown/other: %d",
                (~combined["vehicle_type"].isin(
                    ["bdc", "interval_fund", "tender_offer_fund"]
                )).sum())

    # ── 2. Third-party validation ──
    validation_rows: list[dict] = []

    for source_name, tp_df in third_party.items():
        if tp_df.empty:
            continue

        logger.info("Validating against %s (%d entries) ...", source_name, len(tp_df))

        # Find name and ticker columns in third-party data
        tp_cols = [c.lower() for c in tp_df.columns]
        name_col = None
        ticker_col = None
        cik_col = None

        for c in tp_df.columns:
            cl = c.lower()
            if "name" in cl and name_col is None:
                name_col = c
            if "ticker" in cl or "symbol" in cl:
                ticker_col = c
            if "cik" in cl:
                cik_col = c

        if name_col is None and ticker_col is None and cik_col is None:
            logger.warning("  No usable columns in %s, skipping", source_name)
            continue

        # Match third-party entries to our universe
        matched_tp_indices: set[int] = set()
        matched_universe_indices: set[int] = set()

        for tp_idx, tp_row in tp_df.iterrows():
            tp_name = str(tp_row.get(name_col, "")) if name_col else ""
            tp_ticker = str(tp_row.get(ticker_col, "")).strip().upper() if ticker_col else ""
            tp_cik = str(tp_row.get(cik_col, "")).strip() if cik_col else ""

            best_match_idx = None
            best_score = 0.0

            # Try exact CIK match first
            if tp_cik:
                tp_cik_padded = tp_cik.zfill(10)
                cik_matches = combined[combined["cik"] == tp_cik_padded]
                if not cik_matches.empty:
                    best_match_idx = cik_matches.index[0]
                    best_score = 1.0

            # Try name fuzzy match
            if best_match_idx is None and tp_name:
                for u_idx, u_row in combined.iterrows():
                    u_name = str(u_row.get("entity_name", ""))
                    score = _fuzzy_match_score(tp_name, u_name)
                    # Also try fund_name
                    if u_row.get("fund_name"):
                        score = max(score, _fuzzy_match_score(
                            tp_name, str(u_row["fund_name"])
                        ))
                    if score > best_score:
                        best_score = score
                        best_match_idx = u_idx

            if best_match_idx is not None and best_score >= 0.5:
                matched_tp_indices.add(tp_idx)
                matched_universe_indices.add(best_match_idx)
                # Update in_third_party_lists
                current = str(combined.at[best_match_idx, "in_third_party_lists"] or "")
                if source_name not in current:
                    combined.at[best_match_idx, "in_third_party_lists"] = (
                        f"{current},{source_name}" if current else source_name
                    )

        # Record unmatched third-party entries (in TP but not in our universe)
        for tp_idx, tp_row in tp_df.iterrows():
            if tp_idx not in matched_tp_indices:
                tp_name = str(tp_row.get(name_col, "")) if name_col else ""
                tp_ticker = str(tp_row.get(ticker_col, "")) if ticker_col else ""
                validation_rows.append({
                    "issue": "in_third_party_not_in_universe",
                    "source": source_name,
                    "entity_name": tp_name,
                    "ticker": tp_ticker,
                    "cik": str(tp_row.get(cik_col, "")) if cik_col else "",
                    "notes": f"Found in {source_name} but not matched in our universe",
                })

        # Record universe entities not matched in this TP list
        # (only for the relevant vehicle type)
        relevant_types = set()
        if "bdc" in source_name.lower() or "dividend" in source_name.lower():
            relevant_types = {"bdc"}
        elif "interval" in source_name.lower() or "cefa" in source_name.lower():
            relevant_types = {"interval_fund"}
        elif "tender" in source_name.lower():
            relevant_types = {"tender_offer_fund"}

        if relevant_types:
            for u_idx, u_row in combined.iterrows():
                if (
                    u_row["vehicle_type"] in relevant_types
                    and u_idx not in matched_universe_indices
                ):
                    validation_rows.append({
                        "issue": "in_universe_not_in_third_party",
                        "source": source_name,
                        "entity_name": str(u_row.get("entity_name", "")),
                        "ticker": "",
                        "cik": str(u_row.get("cik", "")),
                        "notes": (
                            f"In our universe as {u_row['vehicle_type']} "
                            f"but not found in {source_name}"
                        ),
                    })

        logger.info("  %s: %d/%d matched, %d unmatched TP entries",
                     source_name, len(matched_tp_indices), len(tp_df),
                     len(tp_df) - len(matched_tp_indices))

    # ── 3. Save outputs ──

    # Select and order columns
    output = combined[SCHEMA_COLUMNS].copy()
    output.to_csv(COMBINED_UNIVERSE_FILE, index=False)
    logger.info("Saved combined universe to %s (%d entities)",
                COMBINED_UNIVERSE_FILE, len(output))

    # JSON output
    output.to_json(COMBINED_UNIVERSE_JSON, orient="records", indent=2,
                   date_format="iso")
    logger.info("Saved combined universe JSON to %s", COMBINED_UNIVERSE_JSON)

    # Validation report
    if validation_rows:
        val_df = pd.DataFrame(validation_rows)
        val_df.to_csv(VALIDATION_REPORT_FILE, index=False)
        logger.info("Saved validation report to %s (%d discrepancies)",
                     VALIDATION_REPORT_FILE, len(val_df))
    else:
        logger.info("No validation discrepancies (or no third-party data to compare)")

    return output
