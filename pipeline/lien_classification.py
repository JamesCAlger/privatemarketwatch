"""Lien position classification for unified holdings.

Classifies DIRECT_LENDING positions into First Lien / Second Lien / Unsecured
based on keyword matching against issuer_name + instrument_description text.

Architecture mirrors the GICS classification system:
  1. Deterministic keyword extraction via DuckDB SQL CASE WHEN
  2. Persistent cache (lien_cache.csv) for agent-reviewed positions
  3. Agent batch workflow scripts for positions lacking keywords

Keyword priority (first match wins):
  Second Lien > Unsecured > First Lien

This ordering ensures that "Second Lien Senior Secured" is correctly
classified as Second Lien, not First Lien.

Public API
----------
_sql_classify_lien() -> str
    Returns DuckDB CASE WHEN SQL fragment for the classified CTE.
classify_lien(issuer_name, instrument_desc) -> str | None
    Pure-Python classification for unit tests.
_load_lien_cache() -> dict
_save_lien_cache(cache) -> None
_apply_lien_cache(combined) -> pd.DataFrame
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Optional

import duckdb
import pandas as pd

from pipeline.classification import _sql_keyword_check

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Keyword lists (checked in priority order)
# ---------------------------------------------------------------------------

_SECOND_LIEN_KEYWORDS: list[str] = [
    "second lien",
    "second-lien",
    "2nd lien",
    "2nd-lien",
    "junior lien",
    "junior secured",
]

_UNSECURED_KEYWORDS: list[str] = [
    "unsecured",
    "subordinat",      # matches subordinated, subordinate
    "mezzanine",
]

_FIRST_LIEN_KEYWORDS: list[str] = [
    "first lien",
    "first-lien",
    "1st lien",
    "1st-lien",
    "senior secured",
    "unitranche",
    "one stop",        # Golub "One Stop" = unitranche/first-lien product
    "one-stop",
    "super senior",
    "last out",
    "first out",
    "senior lien",
]


# ---------------------------------------------------------------------------
# SQL classification
# ---------------------------------------------------------------------------

def _sql_classify_lien() -> str:
    """Generate DuckDB CASE WHEN for lien position classification.

    Searches both ``_combined_fund_text`` (issuer_name + instrument_description)
    and ``bdc_investment_identifier`` (the full XBRL typed-member string which
    often embeds lien tier in the hierarchy, e.g.
    "... 1st Lien/Senior Secured Debt - 125.7% Acme Corp ...").

    Returns NULL when no lien keyword is found.
    """
    _bid = "LOWER(COALESCE(CAST(bdc_investment_identifier AS VARCHAR), ''))"

    second_cft = _sql_keyword_check("_combined_fund_text", _SECOND_LIEN_KEYWORDS)
    second_bid = _sql_keyword_check(_bid, _SECOND_LIEN_KEYWORDS)
    unsecured_cft = _sql_keyword_check("_combined_fund_text", _UNSECURED_KEYWORDS)
    unsecured_bid = _sql_keyword_check(_bid, _UNSECURED_KEYWORDS)
    first_cft = _sql_keyword_check("_combined_fund_text", _FIRST_LIEN_KEYWORDS)
    first_bid = _sql_keyword_check(_bid, _FIRST_LIEN_KEYWORDS)

    return f"""CASE
  WHEN ({second_cft} OR {second_bid}) THEN 'Second Lien'
  WHEN ({unsecured_cft} OR {unsecured_bid}) THEN 'Unsecured'
  WHEN ({first_cft} OR {first_bid}) THEN 'First Lien'
  ELSE NULL
END"""


# ---------------------------------------------------------------------------
# Pure-Python classification (for unit tests)
# ---------------------------------------------------------------------------

def classify_lien(
    issuer_name: Optional[str],
    instrument_desc: Optional[str],
    index_classification: str = "DIRECT_LENDING",
    bdc_investment_identifier: Optional[str] = None,
) -> Optional[str]:
    """Classify lien position from text fields.

    Returns 'First Lien', 'Second Lien', 'Unsecured', or None.
    Only classifies DIRECT_LENDING positions; returns None for all others.

    Searches both issuer_name + instrument_desc (combined text) and the
    full ``bdc_investment_identifier`` which may embed lien tier from the
    XBRL dimension hierarchy.
    """
    if index_classification != "DIRECT_LENDING":
        return None

    combined = (
        (issuer_name or "").lower() + " " + (instrument_desc or "").lower()
    )
    bid = (bdc_investment_identifier or "").lower()

    # Priority order: second lien > unsecured > first lien
    for kw in _SECOND_LIEN_KEYWORDS:
        if kw in combined or kw in bid:
            return "Second Lien"
    for kw in _UNSECURED_KEYWORDS:
        if kw in combined or kw in bid:
            return "Unsecured"
    for kw in _FIRST_LIEN_KEYWORDS:
        if kw in combined or kw in bid:
            return "First Lien"
    return None


# ---------------------------------------------------------------------------
# Instrument pattern normalization (cache key)
# ---------------------------------------------------------------------------

# Strip rates like "SOFR + 5.50%", "L+450", "12.5%", etc.
_RATE_RE = re.compile(
    r"(?:SOFR|LIBOR|prime|L)\s*\+\s*[\d.]+%?"
    r"|[\d.]+\s*%"
    r"|\b\d+\s*bps?\b",
    re.IGNORECASE,
)

# Strip dates like "12/15/2027", "2027-06-30", "due 2028", etc.
_DATE_RE = re.compile(
    r"\b\d{1,2}/\d{1,2}/\d{2,4}\b"
    r"|\b\d{4}-\d{2}-\d{2}\b"
    r"|\bdue\s+\d{4}\b",
    re.IGNORECASE,
)

# Strip par/principal amounts like "$1,500,000", "$5.0M"
_AMOUNT_RE = re.compile(
    r"\$[\d,]+(?:\.\d+)?[MBK]?"
    r"|\b[\d,]+\s*(?:par|principal)\b",
    re.IGNORECASE,
)

# Collapse multiple spaces
_MULTI_SPACE_RE = re.compile(r"\s+")


def _normalize_instrument_pattern(text: str) -> str:
    """Normalize instrument text to a cache key.

    Strips company-specific identifiers (rates, dates, amounts) while
    preserving the structural descriptor (e.g., "senior secured first lien
    term loan").
    """
    if not text:
        return ""
    t = text.lower().strip()
    t = _RATE_RE.sub("", t)
    t = _DATE_RE.sub("", t)
    t = _AMOUNT_RE.sub("", t)
    t = _MULTI_SPACE_RE.sub(" ", t).strip()
    return t


# ---------------------------------------------------------------------------
# Cache I/O
# ---------------------------------------------------------------------------

_CACHE_COLUMNS = [
    "pattern_norm", "lien_position", "confidence", "source", "timestamp",
]


def _load_lien_cache() -> dict[str, tuple[str, str, str]]:
    """Load lien position cache.

    Returns dict: pattern_norm -> (lien_position, confidence, source).
    """
    from pipeline.config import LIEN_CACHE_FILE

    if not LIEN_CACHE_FILE.exists():
        return {}

    df = pd.read_csv(LIEN_CACHE_FILE, dtype=str)
    cache: dict[str, tuple[str, str, str]] = {}
    for _, row in df.iterrows():
        pattern = str(row.get("pattern_norm", ""))
        lien = str(row.get("lien_position", ""))
        confidence = str(row.get("confidence", "low"))
        source = str(row.get("source", "unknown"))
        if pattern and lien in ("First Lien", "Second Lien", "Unsecured"):
            cache[pattern] = (lien, confidence, source)
    return cache


def _save_lien_cache(cache: dict[str, tuple[str, str, str]]) -> None:
    """Save lien position cache to disk."""
    from pipeline.config import LIEN_CACHE_FILE

    records = [
        {
            "pattern_norm": pattern,
            "lien_position": lien,
            "confidence": confidence,
            "source": source,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        for pattern, (lien, confidence, source) in sorted(cache.items())
    ]
    df = pd.DataFrame(records, columns=_CACHE_COLUMNS)
    df.to_csv(LIEN_CACHE_FILE, index=False)


def _apply_lien_cache(combined: pd.DataFrame) -> pd.DataFrame:
    """Apply cached lien classifications to fill NULLs in lien_position.

    Mirrors the pattern of ``_apply_gics_cache`` in unified_holdings.py:
    loads the on-disk cache and JOINs against the holdings DataFrame using
    DuckDB.  Only DIRECT_LENDING positions with NULL lien_position are
    updated.
    """
    from pipeline.config import LIEN_CACHE_FILE

    if not LIEN_CACHE_FILE.exists():
        return combined

    cache = _load_lien_cache()
    if not cache:
        return combined

    # Build lookup DataFrame
    lookup_records = [
        {"pattern_norm": pattern, "lien_position_cached": lien}
        for pattern, (lien, _, _) in cache.items()
    ]
    lookup_df = pd.DataFrame(lookup_records)

    # Pre-compute normalized combined text patterns for each unique
    # (issuer_name, instrument_description) pair.  The cache key is the
    # normalized *combined* text -- same as the worklist script generates --
    # so a cache entry like "acme corp first lien term loan" matches the
    # position "Acme Corp" + "First Lien Term Loan".
    combined = combined.copy()
    combined["_row_idx"] = range(len(combined))

    # Build per-row combined text and normalize
    issuer_col = combined["issuer_name"].fillna("").astype(str)
    inst_col = (
        combined["instrument_description"].fillna("").astype(str)
        if "instrument_description" in combined.columns
        else pd.Series([""] * len(combined), dtype=str)
    )
    combined_text = issuer_col + " " + inst_col
    combined["_inst_norm"] = combined_text.map(_normalize_instrument_pattern)

    con = duckdb.connect()
    con.register("holdings", combined)
    con.register("lien_lookup", lookup_df)

    result = con.execute("""
        SELECT h.* EXCLUDE (lien_position, _inst_norm, _row_idx),
               CASE
                   WHEN (CAST(h.lien_position AS VARCHAR) IS NOT NULL
                         AND CAST(h.lien_position AS VARCHAR) != '')
                        THEN CAST(h.lien_position AS VARCHAR)
                   WHEN CAST(h.index_classification AS VARCHAR) = 'DIRECT_LENDING'
                        AND lk.lien_position_cached IS NOT NULL
                        THEN lk.lien_position_cached
                   ELSE CAST(h.lien_position AS VARCHAR)
               END AS lien_position
        FROM holdings h
        LEFT JOIN lien_lookup lk
          ON h._inst_norm = lk.pattern_norm
        ORDER BY h._row_idx
    """).fetchdf()
    con.close()

    before = (combined["lien_position"].notna()
              & (combined["lien_position"].astype(str) != "")).sum()
    after = (result["lien_position"].notna()
             & (result["lien_position"].astype(str) != "")).sum()
    filled = after - before

    logger.info("Lien cache: %d entries, filled %d positions (total classified: %d)",
                len(cache), filled, after)

    return result
