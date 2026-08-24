"""Merge agent GICS classification results into main cache files.

Usage:
    python scripts/merge_agent_results.py                    # Merge all available result files
    python scripts/merge_agent_results.py --range 0 3        # Merge results 000-003
    python scripts/merge_agent_results.py --stats             # Show what's available
    python scripts/merge_agent_results.py --rekey             # Re-key cache entries via bridge file
"""

import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd

from pipeline.config import (
    AGGREGATE_HEADER_FLAGS_FILE,
    COMPANY_GICS_CACHE_FILE,
    GICS_SKILL_CLAIMS_FILE,
)
from scripts.gics_quality_gate import validate_agent_result_file

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("merge_results")

OUTPUT_DIR = PROJECT_ROOT / "data" / "output"
# Campaign shards (chunks + per-batch results) live under campaign_results/,
# not the output root -- relocated 2026-08-20, see agent_changelog.
CAMPAIGN_DIR = OUTPUT_DIR / "campaign_results" / "gics"
RESULT_PATTERN = "gics_agent_results_*.csv"

# Expected columns in agent result CSVs
EXPECTED_COLS = ["name_norm", "verdict", "gics_sub_industry", "confidence", "evidence"]


def _read_agent_csv(path: Path) -> pd.DataFrame:
    """Read agent CSV with resilient parsing for variable schemas."""
    import csv as csv_mod

    # First try standard pandas read
    try:
        df = pd.read_csv(path, dtype=str, quotechar='"')
    except Exception:
        # Fallback: manual CSV read
        rows = []
        with open(path, encoding="utf-8") as fh:
            reader = csv_mod.reader(fh)
            header = next(reader)
            for parts in reader:
                if len(parts) >= len(header):
                    rows.append(dict(zip(header, parts[:len(header)])))
                elif len(parts) == len(EXPECTED_COLS):
                    rows.append(dict(zip(EXPECTED_COLS, parts)))
        df = pd.DataFrame(rows)

    if df.empty:
        return pd.DataFrame(columns=EXPECTED_COLS)

    # Normalize column names - agents use various schemas
    col_map = {}
    cols_lower = {c.lower().strip(): c for c in df.columns}

    # Map name_norm
    for candidate in ["name_norm", "entity_name", "company_name", "name"]:
        if candidate in cols_lower:
            col_map[cols_lower[candidate]] = "name_norm"
            break

    # Map verdict - could be "verdict" or the gics value itself in a column
    if "verdict" in cols_lower:
        col_map[cols_lower["verdict"]] = "verdict"

    # Map gics_sub_industry
    for candidate in ["gics_sub_industry", "gics", "sub_industry"]:
        if candidate in cols_lower:
            col_map[cols_lower[candidate]] = "gics_sub_industry"
            break

    # Map confidence
    if "confidence" in cols_lower:
        col_map[cols_lower["confidence"]] = "confidence"

    # Map evidence
    for candidate in ["evidence", "reasoning", "reason", "notes", "search_queries"]:
        if candidate in cols_lower:
            col_map[cols_lower[candidate]] = "evidence"
            break

    df = df.rename(columns=col_map)

    # If verdict column is missing but gics_sub_industry has values, infer verdict
    if "verdict" not in df.columns and "gics_sub_industry" in df.columns:
        df["verdict"] = df["gics_sub_industry"].apply(
            lambda x: "GICS" if x and str(x).strip() and str(x).strip() != "nan" else "UNRESOLVABLE"
        )

    # If gics_sub_industry is missing but verdict contains GICS names, use it
    if "gics_sub_industry" not in df.columns:
        # Check if verdict column actually contains GICS names
        valid_gics = _load_valid_gics()
        if "verdict" in df.columns:
            has_gics_in_verdict = df["verdict"].isin(valid_gics).any()
            if has_gics_in_verdict:
                df["gics_sub_industry"] = df["verdict"].apply(
                    lambda x: x if x in valid_gics else ""
                )
                df["verdict"] = df["verdict"].apply(
                    lambda x: "GICS" if x in valid_gics else x
                )

    # Ensure required columns exist
    for col in EXPECTED_COLS:
        if col not in df.columns:
            df[col] = ""

    # Fill missing confidence
    df["confidence"] = df["confidence"].fillna("medium").replace("", "medium")

    return df


def _load_valid_gics() -> set:
    """Load valid GICS sub-industry names."""
    gics_ref = PROJECT_ROOT / "data" / "reference" / "gics_sub_industries.json"
    if gics_ref.exists():
        import json as json_mod
        with open(gics_ref, encoding="utf-8") as f:
            return set(json_mod.load(f))
    # Fallback: hardcoded common GICS names
    return {
        "Application Software", "Systems Software", "Health Care Equipment",
        "Health Care Services", "Insurance Brokers", "Diversified Financial Services",
        "Specialized Consumer Services", "Research & Consulting Services",
        "IT Consulting & Other Services", "Data Processing & Outsourced Services",
        "Aerospace & Defense", "Building Products", "Construction & Engineering",
        "Industrial Machinery & Supplies & Components", "Restaurants",
        "Education Services", "Broadline Retail", "Specialty Stores",
        "Packaged Foods & Meats", "Pharmaceuticals", "Biotechnology",
        "Aluminum", "Steel", "Property & Casualty Insurance",
        "Trading Companies & Distributors", "Cargo Ground Transportation",
        "Environmental & Facilities Services", "Diversified Support Services",
        "Human Resource & Employment Services", "Security & Alarm Services",
        "Health Care Technology", "Health Care Facilities",
        "Paper & Plastic Packaging Products & Materials",
        "Electronic Equipment & Instruments", "Semiconductors",
        "Integrated Telecommunication Services", "Movies & Entertainment",
        "Advertising", "Publishing", "Broadcasting", "Interactive Media & Services",
        "Real Estate Services", "Wireless Telecommunication Services",
        "Electric Utilities", "Renewable Electricity", "Consumer Finance",
        "Specialized Finance", "Commercial & Residential Mortgage Finance",
        "Asset Management & Custody Banks", "Automobile Parts & Equipment",
        "Hotels Resorts & Cruise Lines", "Casinos & Gaming",
        "Oil & Gas Equipment & Services", "Oil & Gas Exploration & Production",
        "Specialty Chemicals", "Commodity Chemicals", "Industrial Gases",
        "Health Care Supplies", "Health Care Distributors", "Managed Health Care",
        "Life Sciences Tools & Services", "Household Products", "Personal Care Products",
        "Multi-Sector Holdings", "Regional Banks", "Diversified Banks",
        "Transaction & Payment Processing Services", "Internet Services & Infrastructure",
        "Communications Equipment", "Electronic Components",
    }


def find_result_files(start: int = 0, end: int = 9999) -> list[Path]:
    """Find agent result CSVs in range."""
    files = sorted(CAMPAIGN_DIR.glob(RESULT_PATTERN))
    filtered = []
    for f in files:
        try:
            num = int(f.stem.replace("gics_agent_results_", ""))
            if start <= num <= end:
                filtered.append(f)
        except ValueError:
            continue
    return filtered


def merge_results(start: int = 0, end: int = 9999) -> None:
    """Merge agent results into cache files."""
    files = find_result_files(start, end)
    if not files:
        logger.info("No result files found in range %d-%d", start, end)
        return

    logger.info("Found %d result files to merge", len(files))

    # Load existing caches
    if COMPANY_GICS_CACHE_FILE.exists():
        cache = pd.read_csv(COMPANY_GICS_CACHE_FILE, dtype=str)
    else:
        cache = pd.DataFrame(columns=[
            "company_name_norm", "gics_sub_industry", "confidence", "source", "timestamp"
        ])

    flags_cols = ["name_norm", "issuer_name_raw", "verdict", "confidence", "evidence",
                  "total_fv", "n_positions", "reviewed_by", "reviewed_at", "batch_id"]
    if AGGREGATE_HEADER_FLAGS_FILE.exists():
        flags = pd.read_csv(AGGREGATE_HEADER_FLAGS_FILE, dtype=str)
    else:
        flags = pd.DataFrame(columns=flags_cols)

    cache_names = set(cache["company_name_norm"].dropna().values)
    flags_names = set(flags["name_norm"].dropna().values)
    now = datetime.now(timezone.utc).isoformat()

    total_gics = 0
    total_agg = 0
    total_jv = 0
    total_unresolvable = 0
    total_skipped = 0

    new_gics_rows = []
    new_flag_rows = []

    for f in files:
        gate = validate_agent_result_file(f)
        if not gate.ok:
            logger.error(
                "Skipping %s: strict GICS result validation failed (%d issue groups)",
                f.name,
                gate.issue_count,
            )
            for detail in gate.details[:10]:
                logger.error("  %s", detail)
            if len(gate.details) > 10:
                logger.error("  ... and %d more", len(gate.details) - 10)
            continue

        try:
            df = _read_agent_csv(f)
        except Exception as e:
            logger.error("Failed to read %s: %s", f.name, e)
            continue

        for _, row in df.iterrows():
            name_norm = str(row.get("name_norm", "")).strip()
            verdict = str(row.get("verdict", "")).strip()
            gics = str(row.get("gics_sub_industry", "")).strip()
            confidence = str(row.get("confidence", "medium")).strip().lower()
            evidence = str(row.get("evidence", "")).strip()

            if not name_norm:
                continue

            # Skip already resolved
            if name_norm in cache_names or name_norm in flags_names:
                total_skipped += 1
                continue

            if verdict == "GICS" and gics:
                new_gics_rows.append({
                    "company_name_norm": name_norm,
                    "gics_sub_industry": gics,
                    "confidence": confidence,
                    "source": "cc_skill",
                    "timestamp": now,
                })
                cache_names.add(name_norm)
                total_gics += 1

            elif verdict == "AGGREGATE_HEADER":
                new_flag_rows.append({
                    "name_norm": name_norm,
                    "issuer_name_raw": name_norm,
                    "verdict": "AGGREGATE_HEADER",
                    "confidence": confidence,
                    "evidence": evidence,
                    "total_fv": "",
                    "n_positions": "",
                    "reviewed_by": "cc_skill_agent",
                    "reviewed_at": now,
                    "batch_id": f.stem.replace("gics_agent_results_", ""),
                })
                flags_names.add(name_norm)
                total_agg += 1

            elif verdict == "JV_SUBSIDIARY":
                new_flag_rows.append({
                    "name_norm": name_norm,
                    "issuer_name_raw": name_norm,
                    "verdict": "JV_SUBSIDIARY",
                    "confidence": confidence,
                    "evidence": evidence,
                    "total_fv": "",
                    "n_positions": "",
                    "reviewed_by": "cc_skill_agent",
                    "reviewed_at": now,
                    "batch_id": f.stem.replace("gics_agent_results_", ""),
                })
                flags_names.add(name_norm)
                total_jv += 1

            elif verdict == "UNRESOLVABLE":
                # Store as GICS Other
                new_gics_rows.append({
                    "company_name_norm": name_norm,
                    "gics_sub_industry": "Other",
                    "confidence": "low",
                    "source": "cc_skill",
                    "timestamp": now,
                })
                cache_names.add(name_norm)
                total_unresolvable += 1

    # Append new rows
    if new_gics_rows:
        cache = pd.concat([cache, pd.DataFrame(new_gics_rows)], ignore_index=True)
        cache.to_csv(COMPANY_GICS_CACHE_FILE, index=False)
        logger.info("Added %d GICS entries to cache (total: %d)", len(new_gics_rows), len(cache))

    if new_flag_rows:
        flags = pd.concat([flags, pd.DataFrame(new_flag_rows)], ignore_index=True)
        flags.to_csv(AGGREGATE_HEADER_FLAGS_FILE, index=False)
        logger.info("Added %d flag entries (total: %d)", len(new_flag_rows), len(flags))

    logger.info(
        "Merge complete: %d GICS, %d AGG, %d JV, %d UNRESOLVABLE, %d skipped (already resolved)",
        total_gics, total_agg, total_jv, total_unresolvable, total_skipped,
    )


def rekey_cache() -> None:
    """Re-key agent GICS cache entries using the bridge file.

    Agent results were keyed by the raw ``name_norm`` from
    ``gics_needs_search_sorted.csv`` (full BDC investment-identifier
    strings), but ``_apply_gics_to_holdings()`` joins on
    ``_normalize_company_name(issuer_name)`` (short company name) and
    ``_extract_short_name(issuer_name)``.

    This function:
    1. Loads the bridge file (``name_norm`` -> ``issuer_name_raw``).
    2. Scans ALL quality-gate-passing agent result files for GICS verdicts
       that are missing from the cache (handles both already-merged long-key
       entries and never-merged entries).
    3. Computes proper cache keys via ``_normalize_company_name`` and
       ``_extract_short_name`` on ``issuer_name_raw``.
    4. Adds new cache rows with ``source="cc_skill_rekeyed"`` -- purely
       additive, no existing entries are modified or removed.
    """
    from pipeline.gics_classification import (
        _extract_short_name,
        _normalize_company_name,
    )

    bridge_file = OUTPUT_DIR / "gics_needs_search_sorted.csv"
    if not bridge_file.exists():
        logger.error("Bridge file not found: %s", bridge_file)
        return

    # --- Load bridge: name_norm -> (issuer_name_raw, search_name) ----------
    bridge_df = pd.read_csv(bridge_file, dtype=str)
    bridge_map: dict[str, tuple[str, str]] = {}
    for _, row in bridge_df.iterrows():
        nn = str(row.get("name_norm", "")).strip()
        raw = str(row.get("issuer_name_raw", "")).strip()
        sn = str(row.get("search_name", "")).strip()
        if nn and raw:
            bridge_map[nn] = (raw, sn)

    logger.info("Bridge loaded: %d name_norm -> (issuer_name_raw, search_name) mappings", len(bridge_map))

    # --- Load existing cache -----------------------------------------------
    if COMPANY_GICS_CACHE_FILE.exists():
        cache = pd.read_csv(COMPANY_GICS_CACHE_FILE, dtype=str)
    else:
        cache = pd.DataFrame(columns=[
            "company_name_norm", "gics_sub_industry", "confidence",
            "source", "timestamp",
        ])

    cache_names = set(cache["company_name_norm"].dropna().values)
    now = datetime.now(timezone.utc).isoformat()

    # --- Collect GICS verdicts from ALL agent result files ------------------
    # Keyed by agent name_norm -> (gics_sub_industry, confidence)
    # This picks up both entries already in cache (with long key) AND
    # entries that were never merged.
    agent_verdicts: dict[str, tuple[str, str]] = {}
    files = find_result_files()
    files_passed = 0
    files_blocked = 0

    for f in files:
        gate = validate_agent_result_file(f)
        if not gate.ok:
            files_blocked += 1
            continue
        files_passed += 1

        try:
            df = _read_agent_csv(f)
        except Exception as e:
            logger.error("Failed to read %s: %s", f.name, e)
            continue

        for _, row in df.iterrows():
            name_norm = str(row.get("name_norm", "")).strip()
            verdict = str(row.get("verdict", "")).strip()
            gics = str(row.get("gics_sub_industry", "")).strip()
            confidence = str(row.get("confidence", "medium")).strip().lower()

            if verdict == "GICS" and gics and name_norm:
                # First occurrence wins (earlier files have priority)
                if name_norm not in agent_verdicts:
                    agent_verdicts[name_norm] = (gics, confidence)

    logger.info(
        "Agent results: %d files passed gate, %d blocked, %d unique GICS verdicts",
        files_passed, files_blocked, len(agent_verdicts),
    )

    # --- Compute proper keys via bridge ------------------------------------
    new_rows: list[dict] = []
    stats = {
        "bridged": 0,
        "no_bridge": 0,
        "new_short_key": 0,
        "new_search_key": 0,
        "already_cached": 0,
        "new_original_key": 0,
    }

    for agent_name, (gics, confidence) in agent_verdicts.items():
        bridge_entry = bridge_map.get(agent_name)
        if not bridge_entry:
            stats["no_bridge"] += 1
            continue
        raw, search_name = bridge_entry
        stats["bridged"] += 1

        # Candidate keys for cache insertion:
        # 1. short_key: _extract_short_name(issuer_name_raw) -- strips loan descriptors
        # 2. search_key: _normalize_company_name(search_name) -- the company name
        #    from the bridge's search_name column (often the cleaned-up entity name)
        # These match what _apply_gics_to_holdings() computes in its two-pass JOIN:
        #   Pass 1: _normalize_company_name(issuer_name) = cache key
        #   Pass 2: _extract_short_name(issuer_name) = cache key
        short_key = _extract_short_name(raw)
        search_key = _normalize_company_name(search_name) if search_name else ""

        for key, stat_name in [
            (short_key, "new_short_key"),
            (search_key, "new_search_key"),
        ]:
            if (
                key
                and key != agent_name
                and key not in cache_names
            ):
                new_rows.append({
                    "company_name_norm": key,
                    "gics_sub_industry": gics,
                    "confidence": confidence,
                    "source": "cc_skill_rekeyed",
                    "timestamp": now,
                })
                cache_names.add(key)
                stats[stat_name] += 1
            elif key and key in cache_names:
                stats["already_cached"] += 1

        # Also ensure the original agent key is in cache (handles never-merged entries)
        if agent_name not in cache_names:
            new_rows.append({
                "company_name_norm": agent_name,
                "gics_sub_industry": gics,
                "confidence": confidence,
                "source": "cc_skill",
                "timestamp": now,
            })
            cache_names.add(agent_name)
            stats["new_original_key"] += 1

    # --- Save ---------------------------------------------------------------
    if new_rows:
        cache = pd.concat([cache, pd.DataFrame(new_rows)], ignore_index=True)
        cache.to_csv(COMPANY_GICS_CACHE_FILE, index=False)

    logger.info(
        "Rekey complete: %d new entries added "
        "(short_key=%d, search_key=%d, original=%d), "
        "%d bridged, %d no bridge match, %d already in cache. "
        "Cache total: %d",
        len(new_rows),
        stats["new_short_key"],
        stats["new_search_key"],
        stats["new_original_key"],
        stats["bridged"],
        stats["no_bridge"],
        stats["already_cached"],
        len(cache),
    )


def show_stats() -> None:
    """Show available result files."""
    files = find_result_files()
    if not files:
        logger.info("No result files found")
        return

    total_rows = 0
    for f in files:
        try:
            df = pd.read_csv(f, dtype=str)
            n = len(df)
            total_rows += n
            verdicts = df["verdict"].value_counts().to_dict() if "verdict" in df.columns else {}
            logger.info("  %s: %d rows %s", f.name, n, verdicts)
        except Exception as e:
            logger.error("  %s: ERROR - %s", f.name, e)

    logger.info("Total: %d files, %d rows", len(files), total_rows)


def main():
    parser = argparse.ArgumentParser(description="Merge agent GICS results into caches")
    parser.add_argument("--range", nargs=2, type=int, default=None,
                        help="Range of result file numbers to merge (start end)")
    parser.add_argument("--stats", action="store_true", help="Show available result files")
    parser.add_argument("--rekey", action="store_true",
                        help="Re-key cache entries via bridge file for proper join matching")
    args = parser.parse_args()

    if args.stats:
        show_stats()
    elif args.rekey:
        rekey_cache()
    elif args.range:
        merge_results(start=args.range[0], end=args.range[1])
    else:
        merge_results()


if __name__ == "__main__":
    main()
