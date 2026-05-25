"""Deterministic triage pass over UNCLASSIFIED worklist batches.

No LLM. Classifies entities via patterns and financial signals into:
- AGGREGATE_HEADER / JV_SUBSIDIARY -> appends to aggregate_header_flags.csv
- AUTO_CLASSIFIED -> writes to unclassified_review_cache.csv
- NEEDS_REVIEW -> writes to unclassified_needs_review.csv

Triage cascade (first match wins):
1. Aggregate header detection (reused from process_gics_batches)
2. JV / structured vehicle detection (reused from process_gics_batches)
3. Fund subtype classification (issuer_category=FUND, keyword matching)
4. Financial signal heuristic (CORPORATE issuers with interest_rate/principal/shares)
5. Fallback -> NEEDS_REVIEW

Usage:
    python scripts/triage_unclassified.py                        # Process all batches
    python scripts/triage_unclassified.py --start 1 --end 10     # Process batch range
    python scripts/triage_unclassified.py --stats                # Show progress stats
"""

import argparse
import csv
import json
import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd

from pipeline.classification import (
    _CREDIT_FUND_SIGNALS,
    _HEDGE_FUND_KEYWORDS,
    _PE_FUND_SIGNALS,
    _REAL_ESTATE_KEYWORDS,
)
from pipeline.config import (
    AGGREGATE_HEADER_FLAGS_FILE,
    UNCLASSIFIED_NEEDS_REVIEW_FILE,
    UNCLASSIFIED_REVIEW_CACHE_FILE,
    UNCLASSIFIED_SKILL_BATCHES_DIR,
    UNCLASSIFIED_SKILL_CLAIMS_FILE,
)
from scripts.process_gics_batches import (
    _is_aggregate_header,
    _is_jv_subsidiary,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("triage_unclassified")

# ---------------------------------------------------------------------------
# Fund subtype keyword sets (derived from classification.py lists)
# Priority order: HEDGE > RE > CREDIT > PE (avoids "equity" false-positive)
# ---------------------------------------------------------------------------

HEDGE_FUND_KW = set(_HEDGE_FUND_KEYWORDS)
CREDIT_FUND_KW = set(_CREDIT_FUND_SIGNALS)
PE_FUND_KW = set(_PE_FUND_SIGNALS)
RE_FUND_KW = set(_REAL_ESTATE_KEYWORDS)


# ---------------------------------------------------------------------------
# Triage logic
# ---------------------------------------------------------------------------

def _classify_fund_subtype(text: str) -> tuple[str | None, str | None, str]:
    """Classify a FUND entity by keyword matching on combined text.

    Returns (new_index_classification, asset_class, evidence) or (None, None, "")
    if no match.
    """
    lower = text.lower()

    # Check in priority order
    if any(kw in lower for kw in HEDGE_FUND_KW):
        matched = [kw for kw in HEDGE_FUND_KW if kw in lower]
        return "HEDGE_FUND", "FUND", f"Hedge fund keyword: {matched[0]}"

    if any(kw in lower for kw in RE_FUND_KW):
        matched = [kw for kw in RE_FUND_KW if kw in lower]
        return "REAL_ESTATE_FUND", "FUND", f"Real estate keyword: {matched[0]}"

    if any(kw in lower for kw in CREDIT_FUND_KW):
        matched = [kw for kw in CREDIT_FUND_KW if kw in lower]
        return "PRIVATE_CREDIT_FUND", "FUND", f"Credit fund keyword: {matched[0]}"

    if any(kw in lower for kw in PE_FUND_KW):
        matched = [kw for kw in PE_FUND_KW if kw in lower]
        return "PRIVATE_EQUITY_FUND", "FUND", f"PE fund keyword: {matched[0]}"

    return None, None, ""


def _classify_by_financial_signal(row: dict) -> tuple[str | None, str | None, str, str]:
    """Classify CORPORATE entity by financial signals.

    Returns (new_index_classification, asset_class, confidence, evidence)
    or (None, None, "", "") if no signal.
    """
    interest_rate = _safe_float(row.get("sample_interest_rate", ""))
    basis_spread = _safe_float(row.get("sample_basis_spread", ""))
    principal = _safe_float(row.get("sample_principal_amount", ""))
    shares = _safe_float(row.get("sample_shares_held", ""))
    maturity = str(row.get("sample_maturity_date", "")).strip()

    has_rate = interest_rate is not None and interest_rate > 0
    has_spread = basis_spread is not None and basis_spread > 0
    has_principal = principal is not None and principal > 0
    has_shares = shares is not None and shares > 0
    has_maturity = bool(maturity) and maturity != "nan"

    # Strong signal: rate + principal -> DIRECT_LENDING
    if (has_rate or has_spread) and has_principal:
        return "DIRECT_LENDING", "LOAN", "high", \
            f"Interest rate + principal amount present"

    # Medium signal: rate + maturity -> DIRECT_LENDING
    if (has_rate or has_spread) and has_maturity:
        return "DIRECT_LENDING", "LOAN", "medium", \
            f"Interest rate + maturity date present"

    # Medium signal: shares only, no rate -> COMMON_EQUITY
    if has_shares and not has_rate and not has_spread:
        return "COMMON_EQUITY", "EQUITY_COMMON", "medium", \
            f"Shares held present, no interest rate"

    return None, None, "", ""


def _safe_float(val) -> float | None:
    """Safely convert to float, returning None on failure."""
    if val is None:
        return None
    try:
        v = float(val)
        return v if v == v else None  # NaN check
    except (ValueError, TypeError):
        return None


def _triage_entity(row: dict) -> dict:
    """Triage a single entity through the 5-rule cascade.

    Returns a dict with verdict, new_index_classification, asset_class,
    confidence, and evidence.
    """
    raw = str(row.get("issuer_name_raw", ""))
    name_norm = str(row.get("name_norm", ""))
    issuer_category = str(row.get("issuer_category", ""))
    sample_instrument = str(row.get("sample_instrument", ""))
    sample_identifier = str(row.get("sample_identifier", ""))

    # Rule 1: Aggregate header
    is_agg, evidence = _is_aggregate_header(name_norm, raw)
    if is_agg:
        return {
            "verdict": "AGGREGATE_HEADER",
            "new_index_classification": "",
            "asset_class": "",
            "confidence": "high",
            "evidence": evidence,
        }

    # Rule 2: JV / structured vehicle
    is_jv, evidence = _is_jv_subsidiary(name_norm, raw)
    if is_jv:
        return {
            "verdict": "JV_SUBSIDIARY",
            "new_index_classification": "",
            "asset_class": "",
            "confidence": "high",
            "evidence": evidence,
        }

    # Rule 3: Fund subtype classification
    if issuer_category == "FUND":
        combined_text = f"{raw} {sample_instrument} {sample_identifier}"
        idx_class, asset_class, evidence = _classify_fund_subtype(combined_text)
        if idx_class:
            return {
                "verdict": "AUTO_CLASSIFIED",
                "new_index_classification": idx_class,
                "asset_class": asset_class,
                "confidence": "medium",
                "evidence": evidence,
            }

    # Rule 4: Financial signal heuristic (CORPORATE)
    if issuer_category == "CORPORATE":
        idx_class, asset_class, confidence, evidence = \
            _classify_by_financial_signal(row)
        if idx_class:
            return {
                "verdict": "AUTO_CLASSIFIED",
                "new_index_classification": idx_class,
                "asset_class": asset_class,
                "confidence": confidence,
                "evidence": evidence,
            }

    # Rule 5: Fallback
    return {
        "verdict": "NEEDS_REVIEW",
        "new_index_classification": "",
        "asset_class": "",
        "confidence": "",
        "evidence": "",
    }


# ---------------------------------------------------------------------------
# File I/O
# ---------------------------------------------------------------------------

_FLAGS_COLUMNS = [
    "name_norm", "issuer_name_raw", "verdict", "confidence", "evidence",
    "total_fv", "n_positions", "reviewed_by", "reviewed_at", "batch_id",
]

_CACHE_COLUMNS = [
    "name_norm", "issuer_name_raw", "verdict", "new_index_classification",
    "asset_class", "confidence", "evidence", "reviewed_by", "reviewed_at",
    "batch_id",
]

_NEEDS_REVIEW_COLUMNS = [
    "batch_id", "entity_id", "issuer_name_raw", "name_norm", "search_name",
    "total_fv", "n_positions", "n_funds",
    "source", "asset_category", "exposure_type", "issuer_category",
    "sample_interest_rate", "sample_basis_spread",
    "sample_shares_held", "sample_principal_amount",
    "sample_maturity_date", "sample_instrument", "sample_identifier",
    "sample_fund",
]


def _load_flags() -> pd.DataFrame:
    """Load existing aggregate header flags."""
    if AGGREGATE_HEADER_FLAGS_FILE.exists():
        return pd.read_csv(AGGREGATE_HEADER_FLAGS_FILE, dtype=str)
    return pd.DataFrame(columns=_FLAGS_COLUMNS)


def _save_flags(flags: pd.DataFrame) -> None:
    """Save aggregate header flags."""
    flags.to_csv(AGGREGATE_HEADER_FLAGS_FILE, index=False)


def _load_cache() -> pd.DataFrame:
    """Load existing unclassified review cache."""
    if UNCLASSIFIED_REVIEW_CACHE_FILE.exists():
        return pd.read_csv(UNCLASSIFIED_REVIEW_CACHE_FILE, dtype=str)
    return pd.DataFrame(columns=_CACHE_COLUMNS)


def _save_cache(cache: pd.DataFrame) -> None:
    """Save unclassified review cache."""
    cache.to_csv(UNCLASSIFIED_REVIEW_CACHE_FILE, index=False)


def _load_claims() -> dict:
    """Load claims file."""
    if UNCLASSIFIED_SKILL_CLAIMS_FILE.exists():
        with open(UNCLASSIFIED_SKILL_CLAIMS_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {}


def _save_claims(claims: dict) -> None:
    """Save claims file."""
    UNCLASSIFIED_SKILL_CLAIMS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(UNCLASSIFIED_SKILL_CLAIMS_FILE, "w", encoding="utf-8") as f:
        json.dump(claims, f, indent=2)


# ---------------------------------------------------------------------------
# Batch processing
# ---------------------------------------------------------------------------

def process_batch(batch_num: int, cache: pd.DataFrame, flags: pd.DataFrame,
                  needs_review_writer) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """Process a single batch. Returns updated (cache, flags, stats)."""
    batch_id = f"{batch_num:03d}"
    batch_path = UNCLASSIFIED_SKILL_BATCHES_DIR / f"batch_{batch_id}.csv"

    if not batch_path.exists():
        return cache, flags, {"status": "missing"}

    batch = pd.read_csv(batch_path, dtype=str)
    now = datetime.now(timezone.utc).isoformat()

    # Already resolved names
    cache_names = set(cache["name_norm"].dropna().values) if len(cache) > 0 else set()
    flags_names = set(flags["name_norm"].dropna().values) if len(flags) > 0 else set()

    new_cache_rows = []
    new_flags_rows = []
    stats = {"n_auto": 0, "n_aggregate": 0, "n_jv": 0, "n_needs_review": 0}

    for _, row in batch.iterrows():
        name_norm = str(row.get("name_norm", ""))
        if not name_norm or name_norm in cache_names or name_norm in flags_names:
            continue

        result = _triage_entity(row)
        verdict = result["verdict"]

        if verdict == "AGGREGATE_HEADER":
            new_flags_rows.append({
                "name_norm": name_norm,
                "issuer_name_raw": str(row.get("issuer_name_raw", "")),
                "verdict": "AGGREGATE_HEADER",
                "confidence": result["confidence"],
                "evidence": result["evidence"],
                "total_fv": str(row.get("total_fv", "")),
                "n_positions": str(row.get("n_positions", "")),
                "reviewed_by": "triage_rule",
                "reviewed_at": now,
                "batch_id": batch_id,
            })
            flags_names.add(name_norm)
            stats["n_aggregate"] += 1

        elif verdict == "JV_SUBSIDIARY":
            new_flags_rows.append({
                "name_norm": name_norm,
                "issuer_name_raw": str(row.get("issuer_name_raw", "")),
                "verdict": "JV_SUBSIDIARY",
                "confidence": result["confidence"],
                "evidence": result["evidence"],
                "total_fv": str(row.get("total_fv", "")),
                "n_positions": str(row.get("n_positions", "")),
                "reviewed_by": "triage_rule",
                "reviewed_at": now,
                "batch_id": batch_id,
            })
            flags_names.add(name_norm)
            stats["n_jv"] += 1

        elif verdict == "AUTO_CLASSIFIED":
            new_cache_rows.append({
                "name_norm": name_norm,
                "issuer_name_raw": str(row.get("issuer_name_raw", "")),
                "verdict": "AUTO_CLASSIFIED",
                "new_index_classification": result["new_index_classification"],
                "asset_class": result["asset_class"],
                "confidence": result["confidence"],
                "evidence": result["evidence"],
                "reviewed_by": "triage_rule",
                "reviewed_at": now,
                "batch_id": batch_id,
            })
            cache_names.add(name_norm)
            stats["n_auto"] += 1

        elif verdict == "NEEDS_REVIEW":
            needs_review_writer.writerow({
                "batch_id": batch_id,
                "entity_id": str(row.get("entity_id", "")),
                "issuer_name_raw": str(row.get("issuer_name_raw", "")),
                "name_norm": name_norm,
                "search_name": str(row.get("search_name", "")),
                "total_fv": str(row.get("total_fv", "")),
                "n_positions": str(row.get("n_positions", "")),
                "n_funds": str(row.get("n_funds", "")),
                "source": str(row.get("source", "")),
                "asset_category": str(row.get("asset_category", "")),
                "exposure_type": str(row.get("exposure_type", "")),
                "issuer_category": str(row.get("issuer_category", "")),
                "sample_interest_rate": str(row.get("sample_interest_rate", "")),
                "sample_basis_spread": str(row.get("sample_basis_spread", "")),
                "sample_shares_held": str(row.get("sample_shares_held", "")),
                "sample_principal_amount": str(row.get("sample_principal_amount", "")),
                "sample_maturity_date": str(row.get("sample_maturity_date", "")),
                "sample_instrument": str(row.get("sample_instrument", "")),
                "sample_identifier": str(row.get("sample_identifier", "")),
                "sample_fund": str(row.get("sample_fund", "")),
            })
            stats["n_needs_review"] += 1

    # Merge new results
    if new_cache_rows:
        cache = pd.concat([cache, pd.DataFrame(new_cache_rows)], ignore_index=True)

    if new_flags_rows:
        flags = pd.concat([flags, pd.DataFrame(new_flags_rows)], ignore_index=True)

    stats["status"] = "done"
    stats["completed_at"] = now
    return cache, flags, stats


def run(start: int = 1, end: int = 999) -> None:
    """Process batches from start to end."""
    t0 = time.time()

    # Determine actual batch range
    if not UNCLASSIFIED_SKILL_BATCHES_DIR.exists():
        logger.error("Batches directory not found: %s", UNCLASSIFIED_SKILL_BATCHES_DIR)
        return
    batch_files = sorted(UNCLASSIFIED_SKILL_BATCHES_DIR.glob("batch_*.csv"))
    if not batch_files:
        logger.error("No batch files found")
        return
    max_batch = max(int(f.stem.replace("batch_", "")) for f in batch_files)
    end = min(end, max_batch)

    logger.info("Processing batches %03d through %03d", start, end)

    cache = _load_cache()
    flags = _load_flags()
    claims = _load_claims()

    with open(UNCLASSIFIED_NEEDS_REVIEW_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=_NEEDS_REVIEW_COLUMNS)
        writer.writeheader()

        total_stats = {"n_auto": 0, "n_aggregate": 0, "n_jv": 0, "n_needs_review": 0}

        for batch_num in range(start, end + 1):
            cache, flags, stats = process_batch(batch_num, cache, flags, writer)

            if stats.get("status") == "done":
                for k in total_stats:
                    total_stats[k] += stats.get(k, 0)
                claims[f"{batch_num:03d}"] = {
                    "status": "triage_done",
                    "completed_at": stats["completed_at"],
                    "n_auto": stats["n_auto"],
                    "n_aggregate": stats["n_aggregate"],
                    "n_jv": stats["n_jv"],
                    "n_needs_review": stats["n_needs_review"],
                }

            # Save periodically (every 50 batches)
            if batch_num % 50 == 0 or batch_num == end:
                _save_cache(cache)
                _save_flags(flags)
                _save_claims(claims)
                elapsed = time.time() - t0
                logger.info(
                    "Batch %03d done (%.0fs). Running totals: "
                    "%d AUTO, %d AGG, %d JV, %d NEEDS_REVIEW",
                    batch_num, elapsed,
                    total_stats["n_auto"], total_stats["n_aggregate"],
                    total_stats["n_jv"], total_stats["n_needs_review"],
                )

    # Final save
    _save_cache(cache)
    _save_flags(flags)
    _save_claims(claims)

    elapsed = time.time() - t0
    total_resolved = total_stats["n_auto"] + total_stats["n_aggregate"] + total_stats["n_jv"]
    total_all = total_resolved + total_stats["n_needs_review"]
    pct = (total_resolved / total_all * 100) if total_all else 0
    logger.info(
        "Triage complete in %.1fs. AUTO=%d, AGGREGATE=%d, JV=%d, "
        "NEEDS_REVIEW=%d (%.0f%% resolved)",
        elapsed,
        total_stats["n_auto"], total_stats["n_aggregate"],
        total_stats["n_jv"], total_stats["n_needs_review"],
        pct,
    )
    logger.info("Review cache: %s", UNCLASSIFIED_REVIEW_CACHE_FILE)
    logger.info("Needs review: %s", UNCLASSIFIED_NEEDS_REVIEW_FILE)


def show_stats() -> None:
    """Show current processing progress."""
    claims = _load_claims()
    if not claims:
        logger.info("No batches processed yet")
        return

    done = sum(1 for v in claims.values() if v.get("status") == "triage_done")
    total_auto = sum(v.get("n_auto", 0) for v in claims.values())
    total_agg = sum(v.get("n_aggregate", 0) for v in claims.values())
    total_jv = sum(v.get("n_jv", 0) for v in claims.values())
    total_review = sum(v.get("n_needs_review", 0) for v in claims.values())

    logger.info("Batches processed: %d", done)
    logger.info("  AUTO_CLASSIFIED: %d", total_auto)
    logger.info("  AGGREGATE_HEADER: %d", total_agg)
    logger.info("  JV_SUBSIDIARY: %d", total_jv)
    logger.info("  NEEDS_REVIEW: %d", total_review)

    if UNCLASSIFIED_NEEDS_REVIEW_FILE.exists():
        df = pd.read_csv(UNCLASSIFIED_NEEDS_REVIEW_FILE, dtype=str)
        total_fv = df["total_fv"].astype(float).sum()
        logger.info("  Needs review file: %d entities, $%.1fB FV",
                     len(df), total_fv / 1e9)

    if UNCLASSIFIED_REVIEW_CACHE_FILE.exists():
        df = pd.read_csv(UNCLASSIFIED_REVIEW_CACHE_FILE, dtype=str)
        logger.info("  Review cache: %d entries", len(df))
        if "new_index_classification" in df.columns:
            for cls, cnt in df["new_index_classification"].value_counts().items():
                logger.info("    %s: %d", cls, cnt)


def main():
    parser = argparse.ArgumentParser(
        description="Triage UNCLASSIFIED worklist batches (deterministic pass)"
    )
    parser.add_argument("--start", type=int, default=1, help="Start batch number")
    parser.add_argument("--end", type=int, default=999, help="End batch number")
    parser.add_argument("--stats", action="store_true", help="Show progress stats")
    args = parser.parse_args()

    if args.stats:
        show_stats()
    else:
        run(start=args.start, end=args.end)


if __name__ == "__main__":
    main()
