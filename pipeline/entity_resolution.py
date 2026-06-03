"""Entity resolution for private markets holdings.

Maps each issuer_name variant to a canonical entity_id and canonical_name,
enabling cross-filer and cross-source entity counting.

Pipeline:
  1. Build variant table (DuckDB GROUP BY on 1.3M holdings)
  2. Extract company names (Python regex on 273K variant rows)
  3. Normalise names (Python on 273K rows)
  4. Exact dedup (group by normalised name -> ~55-65K entities)
  5. Fuzzy clustering (rapidfuzz within-source, threshold 85)
  6. Cross-source linking (fuzzy match BDC vs N-PORT, threshold 80)
  7. Write entity_lookup.csv and enrich private_markets_holdings.csv
"""

import json
import logging
import re
import time
from collections import defaultdict
from pathlib import Path
from typing import Optional

import duckdb
import pandas as pd
from rapidfuzz import fuzz

from pipeline.config import (
    ENTITY_LOOKUP_FILE,
    ENTITY_OVERRIDES_FILE,
    ENTITY_STATS_FILE,
    IDENTIFIER_EXTRACTION_LOOKUP_FILE,
    UNIFIED_HOLDINGS_FILE,
)
from pipeline.utils import UnionFind

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Step 1: Name extraction
# ---------------------------------------------------------------------------

# Tier 1: Legal suffixes (preferred cutoff point)
_LEGAL_SUFFIX_RE = re.compile(
    r"(?i)(?:"
    r"\b(?:incorporated|corporation)\b"
    r"|,?\s*inc\.?,?"
    r"|,?\s*(?:l\.?l\.?c\.?)\b"
    r"|,?\s*corp\.?,?"
    r"|,?\s*ltd\.?,?"
    r"|,?\s*l\.p\.?,?"
    r"|,?\s*\blp\b"
    r"|,?\s*co\.\s?"
    r"|\b(?:plc|s\.a\.|n\.v\.|gmbh|ag|b\.v\.|s\.r\.l\.|s\.a\.r\.l\.|pty|s\.a\.s)\b"
    r")"
)

# Tier 2: Generic markers (fallback if no legal suffix)
_GENERIC_MARKER_RE = re.compile(r"(?i)\b(?:holdings|group)\b")

# N-PORT facility suffixes to strip
_NPORT_FACILITY_RE = re.compile(
    r"\s+(?:T/?L|DL|REVOLVER|REV|RC|RCF|DD"
    r"|TERM\s+LOAN|DELAYED\s+DRAW|CREDIT\s+FACIL(?:ITY)?)\b.*$",
    re.IGNORECASE,
)
_NPORT_TRAILING_SLASH = re.compile(r"\s*/\s*$")

# Metadata blob keywords
_METADATA_KEYWORDS = ["investment type", "interest rate", "maturity date"]

# Leading "Investment," prefix pattern
_INVESTMENT_PREFIX_RE = re.compile(
    r"^Investment,\s*(?:Non-Affiliated Issuer|Affiliated Issuer|Control Investment)"
    r"(?:,\s*(?:First Lien Debt|Second Lien Debt|Subordinated Debt|Unsecured Debt"
    r"|Equity|Preferred Equity|Common Equity|Warrant|Fund Investment"
    r"|[^,]+?Debt|[^,]+?Equity|[^,]+?Loan|[^,]+?Note))?[,;]\s*",
    re.IGNORECASE,
)

# Debt prefix: "Debt Investments, First Lien Senior Secured, <company>"
_DEBT_PREFIX_RE = re.compile(
    r"^(?:D?Debt(?:\s+Debt)?\s+)?(?:Debt\s+)?Investments?\s*,\s*"
    r"(?:First Lien|Second Lien|Senior Secured|Subordinated|Unsecured)[^,]*,\s*",
    re.IGNORECASE,
)

# Controlled/Non-Affiliated prefix
_CONTROLLED_PREFIX_RE = re.compile(
    r"^(?:Non-?)?Control(?:led)?(?:/Non-?Affiliated)?\s+Investments?\s*,"
    r"\s*Senior[^,]*,\s*(?:Industry\s+[^,]*,\s*)?(?:Company\s+)?",
    re.IGNORECASE,
)

# Related Party prefix: strip only "Related Party" leaving the company name
_RELATED_PARTY_PREFIX_RE = re.compile(
    r"^Related\s+Party\s+",
    re.IGNORECASE,
)

# Trailing instrument keywords (only applied when no legal suffix found)
_TRAILING_INSTRUMENT_RE = re.compile(
    r"\s+(?:First|Second|Third)\s+Lien\b.*$"
    r"|\s+Senior\s+Secured\b.*$"
    r"|\s+(?:Term\s+Loan|Revolver|Delayed\s+Draw|Credit\s+Facility"
    r"|Secured\s+Debt|Unsecured\s+Debt|Unitranche)\b.*$",
    re.IGNORECASE,
)

# Opaque numeric IDs (e.g. "1824445.SQ.RVR" from marketplace lending CIKs)
_OPAQUE_NUMERIC_ID_RE = re.compile(r"^\d{5,}\.\w{1,4}\.\w{2,4}$")

# Trailing number/parenthetical: " 1", " 2", " (1)", " (2)"
_TRAILING_NUMBER_RE = re.compile(r"\s+(?:\d+|\(\d+\))\s*$")

# Garbage entity names: subtotal/category headers that leak into variant table
_GARBAGE_ENTITY_NAMES_RE = re.compile(
    r"^(?:investments?|debt investments?|equity investments?"
    r"|first lien (?:debt|senior secured)|second lien (?:debt|senior secured)"
    r"|subordinated debt|unsecured debt|senior secured"
    r"|structured (?:products?|finance)|fund investments?"
    r"|total|subtotal|net assets?|other investments?"
    r"|portfolio investments?)$",
    re.IGNORECASE,
)

# Minimum entity name length (names shorter than this are garbage)
_MIN_ENTITY_NAME_LENGTH = 3

# Numeric-suffix guard: when two names are identical after stripping digits
# but differ in their digits, they are likely different series/vintages
# (e.g., "CIFC 2019-1" vs "CIFC 2020-3", "Carlyle Partners VII" vs
# "Carlyle Partners VIII").  Require a much higher score to merge.
_DIGIT_STRIP_RE = re.compile(r"\d+")
# Roman numerals as standalone tokens (i, ii, ..., xxxix, xl, etc.)
_ROMAN_TOKEN_RE = re.compile(
    r"\b(?:xl|xxx?(?:ix|iv|v?i{0,3})|xx?(?:ix|iv|v?i{0,3})|x?(?:ix|iv|v?i{0,3})|vi{0,3}|iv|i{1,3})\b",
    re.IGNORECASE,
)
# Set to 100 to block merges entirely: if two names differ only by
# numbers/Roman numerals, they are distinct series/vintages and should
# never be fuzzy-merged regardless of score.
_NUMERIC_SUFFIX_THRESHOLD = 100


def _strip_numeric_tokens(name: str) -> str:
    """Strip digits and Roman numeral tokens from a normalized name."""
    s = _DIGIT_STRIP_RE.sub("", name)
    s = _ROMAN_TOKEN_RE.sub("", s)
    return re.sub(r"\s+", " ", s).strip()


def _numeric_suffix_guard(name_a: str, name_b: str, threshold: int) -> int:
    """Return the effective threshold for merging two names.

    If the names are identical after stripping all digits and Roman
    numerals but differ in their numeric/ordinal components, return
    _NUMERIC_SUFFIX_THRESHOLD (95) to prevent merging different
    series/vintages.  Otherwise return the caller's threshold unchanged.
    """
    stripped_a = _strip_numeric_tokens(name_a)
    stripped_b = _strip_numeric_tokens(name_b)
    if not stripped_a or not stripped_b:
        return threshold
    # If the non-numeric skeletons match but the original names are
    # different, the difference is purely numeric/ordinal.
    if stripped_a == stripped_b and name_a != name_b:
        return max(threshold, _NUMERIC_SUFFIX_THRESHOLD)
    return threshold


def extract_company_name(issuer_name: str, source: str = "bdc") -> str:
    """Extract the real company name from a polluted issuer_name string.

    For BDC names: cuts after the first legal suffix (Inc., LLC, etc.)
    or generic marker (Holdings, Group). Handles metadata blobs and
    "Investment," prefixes.

    For N-PORT names: strips facility suffixes (TL, REVOLVER, etc.)
    and trailing slashes.
    """
    if not issuer_name or not isinstance(issuer_name, str):
        return ""

    name = issuer_name.strip()
    if not name:
        return ""

    if source == "nport":
        return _extract_nport_name(name)
    return _extract_bdc_name(name)


def _extract_nport_name(name: str) -> str:
    """Extract company name from N-PORT issuer_name."""
    # Strip facility suffixes: "FINASTRA USA INC TL 1L VISTA /" -> "FINASTRA USA INC"
    # First try legal suffix cutoff (many N-PORT names have Inc/LLC)
    m = _LEGAL_SUFFIX_RE.search(name)
    if m:
        extracted = name[: m.end()].strip().rstrip(",")
        if len(extracted) >= 2:
            return extracted

    # Strip facility suffixes
    cleaned = _NPORT_FACILITY_RE.sub("", name)
    # Strip trailing slash
    cleaned = _NPORT_TRAILING_SLASH.sub("", cleaned)
    # Strip trailing whitespace and common delimiters
    cleaned = cleaned.strip().rstrip("-/|,")
    return cleaned.strip() if cleaned.strip() else name


def _extract_bdc_name(name: str) -> str:
    """Extract company name from BDC issuer_name."""
    original_name = name

    # Phase 0: Split on pipe delimiter
    pipe_idx = name.find("|")
    if pipe_idx > 0:
        name = name[:pipe_idx].strip().rstrip(",")
        if not name:
            return _strip_trailing_number(original_name)

    # Phase 1: Handle "Investment," prefix
    inv_match = _INVESTMENT_PREFIX_RE.match(name)
    if inv_match:
        name = name[inv_match.end():].strip()
        if not name:
            return issuer_name_fallback(name)

    # Phase 1b: Handle "Debt Investments, First Lien ..., <company>" prefix
    debt_match = _DEBT_PREFIX_RE.match(name)
    if debt_match:
        name = name[debt_match.end():].strip()
        if not name:
            return issuer_name_fallback(original_name)

    # Phase 1c: Handle "Controlled/Non-Affiliated Investments, Senior ..., Company <name>" prefix
    ctrl_match = _CONTROLLED_PREFIX_RE.match(name)
    if ctrl_match:
        name = name[ctrl_match.end():].strip()
        if not name:
            return issuer_name_fallback(original_name)

    # Phase 1d: Handle "Related Party PSLF ..." prefix
    rp_match = _RELATED_PARTY_PREFIX_RE.match(name)
    if rp_match:
        name = name[rp_match.end():].strip()
        if not name:
            return issuer_name_fallback(original_name)

    # Phase 2: Check for metadata blob
    name_lower = name.lower()
    is_blob = any(kw in name_lower for kw in _METADATA_KEYWORDS)

    if is_blob:
        # Find legal suffix in blob and extract name ending there
        m = _LEGAL_SUFFIX_RE.search(name)
        if m:
            extracted = name[: m.end()].strip().rstrip(",")
            # Walk backward from the suffix to find name start
            # (skip past any leading metadata like "Software Zendesk")
            # Heuristic: if there's a repeated word before the suffix,
            # start from the second occurrence
            if len(extracted) >= 2:
                return _strip_trailing_number(extracted)
        # No legal suffix in blob -- return as-is (rare)
        return _strip_trailing_number(name)

    # Phase 3: Tier 1 -- legal suffix cutoff
    m = _LEGAL_SUFFIX_RE.search(name)
    if m:
        extracted = name[: m.end()].strip().rstrip(",")
        if len(extracted) >= 2:
            return _strip_trailing_number(extracted)

    # Phase 4: Tier 2 -- generic marker cutoff (Holdings, Group)
    m = _GENERIC_MARKER_RE.search(name)
    if m:
        extracted = name[: m.end()].strip().rstrip(",")
        if len(extracted) >= 2:
            return _strip_trailing_number(extracted)

    # Phase 5: No marker found -- try trailing instrument stripping
    cleaned = _TRAILING_INSTRUMENT_RE.sub("", name).strip()
    if cleaned and cleaned != name:
        return _strip_trailing_number(cleaned)

    # Phase 6: Return as-is (stripped of trailing numbers)
    return _strip_trailing_number(name)


def _strip_trailing_number(name: str) -> str:
    """Strip trailing ` 1`, ` 2`, ` (1)` etc. from extracted names."""
    return _TRAILING_NUMBER_RE.sub("", name).strip()


def issuer_name_fallback(name: str) -> str:
    """Fallback for empty extraction result."""
    return name.strip() if name else ""


# ---------------------------------------------------------------------------
# Step 2: Normalisation
# ---------------------------------------------------------------------------

_LEGAL_SUFFIXES_NORM = [
    " incorporated", " corporation", " limited",
    " inc", " llc", " l.l.c.", " corp", " ltd",
    " l.p.", " lp", " co.",
    " plc", " s.a.", " n.v.", " gmbh", " ag",
    " b.v.", " s.r.l.", " s.a.r.l.", " pty", " s.a.s",
    " holdings", " group",
]

_PARENTHETICAL_RE = re.compile(r"\([^)]*\)")
_PUNCTUATION_RE = re.compile(r"[^a-z0-9\s]")
_WHITESPACE_RE = re.compile(r"\s+")
_LEADING_THE_RE = re.compile(r"^the\s+")


def normalise_entity_name(name: str) -> str:
    """Normalise a company name for exact dedup matching.

    Steps:
      1. Lowercase
      2. Remove parenthetical content
      3. Strip legal suffixes
      4. Remove all punctuation
      5. Collapse whitespace
      6. Strip leading "the "
    """
    if not name or not isinstance(name, str):
        return ""

    n = name.lower().strip()
    # Remove parenthetical content
    n = _PARENTHETICAL_RE.sub("", n)
    # Strip legal suffixes (iterate in order, longest first handled by list)
    for suffix in _LEGAL_SUFFIXES_NORM:
        n = n.replace(suffix, "")
    # Remove punctuation
    n = _PUNCTUATION_RE.sub("", n)
    # Collapse whitespace
    n = _WHITESPACE_RE.sub(" ", n).strip()
    # Strip leading "the "
    n = _LEADING_THE_RE.sub("", n)
    return n


# ---------------------------------------------------------------------------
# Step 3: Exact dedup
# ---------------------------------------------------------------------------

def _build_variant_table(holdings_path: Path) -> pd.DataFrame:
    """Build variant table from unified holdings using DuckDB.

    Groups by (issuer_name, source) and aggregates occurrence count,
    first non-null CUSIP, LEI, and bdc_investment_identifier.

    Filters out opaque numeric IDs (e.g. "1824445.SQ.RVR").

    Returns a DataFrame with columns:
      issuer_name, source, occurrence_count, cusip, lei, bdc_investment_identifier
    """
    con = duckdb.connect()
    try:
        df = con.execute("""
            SELECT
                issuer_name,
                source,
                COUNT(*) as occurrence_count,
                FIRST(cusip) FILTER (
                    WHERE cusip IS NOT NULL AND cusip <> ''
                ) as cusip,
                FIRST(lei) FILTER (
                    WHERE lei IS NOT NULL AND lei <> ''
                ) as lei,
                FIRST(bdc_investment_identifier) FILTER (
                    WHERE bdc_investment_identifier IS NOT NULL
                    AND bdc_investment_identifier <> ''
                ) as bdc_investment_identifier
            FROM read_csv_auto(?, header=true, all_varchar=true)
            WHERE issuer_name IS NOT NULL AND issuer_name <> ''
              AND NOT regexp_matches(issuer_name, '^\\d{5,}\\.\\w{1,4}\\.\\w{2,4}$')
            GROUP BY issuer_name, source
            ORDER BY occurrence_count DESC
        """, [str(holdings_path)]).fetchdf()
    finally:
        con.close()

    df["occurrence_count"] = df["occurrence_count"].astype(int)

    # Filter out garbage entity names (subtotal/category headers)
    pre_count = len(df)
    garbage_mask = df["issuer_name"].apply(
        lambda n: bool(_GARBAGE_ENTITY_NAMES_RE.match(n.strip())) if isinstance(n, str) else False
    )
    short_mask = df["issuer_name"].apply(
        lambda n: len(n.strip()) < _MIN_ENTITY_NAME_LENGTH if isinstance(n, str) else True
    )
    df = df[~garbage_mask & ~short_mask].reset_index(drop=True)
    removed = pre_count - len(df)
    if removed > 0:
        logger.info("  Filtered %d garbage/short entity names", removed)

    return df


def _exact_dedup(variants: pd.DataFrame) -> pd.DataFrame:
    """Group variants by normalised name and assign entity IDs.

    For BDC variants, prefers LLM-extracted company names from the
    identifier_extraction_lookup.csv cache over regex extraction.

    Adds columns: extracted_name, normalized_name, entity_num, canonical_name
    """
    # Apply extraction and normalisation (Python on ~273K rows)
    variants = variants.copy()

    # Load LLM extraction cache if available
    llm_lookup = {}
    if IDENTIFIER_EXTRACTION_LOOKUP_FILE.exists():
        try:
            llm_df = pd.read_csv(
                IDENTIFIER_EXTRACTION_LOOKUP_FILE,
                usecols=["bdc_investment_identifier", "extracted_company_name"],
                dtype=str,
            )
            llm_df = llm_df.dropna(subset=["bdc_investment_identifier", "extracted_company_name"])
            llm_df = llm_df[llm_df["extracted_company_name"].str.strip() != ""]
            llm_lookup = dict(zip(
                llm_df["bdc_investment_identifier"],
                llm_df["extracted_company_name"],
            ))
            logger.info("  Loaded %d LLM-extracted names from cache", len(llm_lookup))
        except Exception:
            logger.warning("  Could not load LLM extraction cache; falling back to regex")

    extracted_names = []
    for _, row in variants.iterrows():
        issuer = row["issuer_name"]
        source = row["source"]
        bdc_id = row.get("bdc_investment_identifier", "")

        # For BDC variants, prefer LLM-extracted name
        if source == "bdc" and bdc_id and pd.notna(bdc_id) and bdc_id in llm_lookup:
            extracted_names.append(llm_lookup[bdc_id])
        else:
            extracted_names.append(extract_company_name(issuer, source))

    variants["extracted_name"] = extracted_names
    variants["normalized_name"] = variants["extracted_name"].apply(
        normalise_entity_name
    )

    # Group by normalized_name: assign entity_num and pick canonical
    # Canonical = extracted_name with highest occurrence_count, preferring
    # names with a legal suffix
    grouped = (
        variants.groupby("normalized_name", sort=True)
        .apply(_pick_canonical, include_groups=False)
        .reset_index()
        .rename(columns={0: "canonical_name"})
    )
    grouped["entity_num"] = range(1, len(grouped) + 1)

    # Merge back
    variants = variants.merge(
        grouped[["normalized_name", "entity_num", "canonical_name"]],
        on="normalized_name",
        how="left",
    )

    return variants


def _pick_canonical(group: pd.DataFrame) -> str:
    """Pick the best canonical name from a group of variants."""
    # Prefer names with legal suffixes
    has_suffix = group["extracted_name"].apply(
        lambda n: bool(_LEGAL_SUFFIX_RE.search(n)) if isinstance(n, str) else False
    )
    candidates = group[has_suffix] if has_suffix.any() else group
    # Among candidates, pick highest occurrence_count
    best_idx = candidates["occurrence_count"].idxmax()
    return candidates.at[best_idx, "extracted_name"]


# ---------------------------------------------------------------------------
# Step 4: Fuzzy clustering
# ---------------------------------------------------------------------------

def _fuzzy_cluster(
    variants: pd.DataFrame,
    threshold: int = 85,
    max_block_size: int = 500,
) -> pd.DataFrame:
    """Merge entities with similar normalised names using fuzzy matching.

    Two passes:
      Pass 1: 4-char blocking key, threshold (default 85).
      Pass 2: 3-char blocking key, higher threshold (threshold + 5, min 90),
              smaller max_block_size (200), only unmerged entities.
    Matching: rapidfuzz.fuzz.token_sort_ratio >= threshold.
    Clustering: Union-Find (connected components).
    """
    if len(variants) <= 1:
        return variants

    # Build entity-level table: one row per (normalized_name, entity_num)
    entity_df = (
        variants.groupby("entity_num")
        .agg(
            normalized_name=("normalized_name", "first"),
            canonical_name=("canonical_name", "first"),
            total_count=("occurrence_count", "sum"),
            source=("source", "first"),
        )
        .reset_index()
    )

    if len(entity_df) <= 1:
        return variants

    uf = UnionFind()
    total_comparisons = 0
    total_merges = 0
    numeric_blocked = 0

    # --- Pass 1: 4-char blocking ---
    entity_df["block_key"] = entity_df["normalized_name"].str[:4]
    blocks = entity_df.groupby("block_key")["entity_num"].apply(list).to_dict()

    for block_key, members in blocks.items():
        if len(members) <= 1:
            continue
        if len(members) > max_block_size:
            continue

        block_data = entity_df[entity_df["entity_num"].isin(members)]
        names = dict(zip(block_data["entity_num"], block_data["normalized_name"]))

        member_list = list(names.keys())
        for i in range(len(member_list)):
            for j in range(i + 1, len(member_list)):
                a, b = member_list[i], member_list[j]
                total_comparisons += 1
                score = fuzz.token_sort_ratio(names[a], names[b])
                effective = _numeric_suffix_guard(names[a], names[b], threshold)
                if score >= effective:
                    uf.union(a, b)
                    total_merges += 1
                elif effective > threshold:
                    numeric_blocked += 1

    pass1_merges = total_merges

    # --- Pass 2: 3-char blocking (catches near-miss first-4-char differences) ---
    # Higher threshold compensates for wider blocking; smaller block cap prevents explosion
    pass2_threshold = max(threshold + 5, 90)
    # Cap at 200 for wider 3-char blocks, but honor caller's smaller limit
    pass2_max_block = min(200, max_block_size)

    # Identify entities already merged in pass 1
    merged_in_pass1 = set()
    for comp_members in uf.components().values():
        if len(comp_members) > 1:
            merged_in_pass1.update(comp_members)

    # Only consider entities not yet merged
    unmerged_mask = ~entity_df["entity_num"].isin(merged_in_pass1)
    unmerged_df = entity_df[unmerged_mask]

    if len(unmerged_df) > 1:
        unmerged_df = unmerged_df.copy()
        unmerged_df["block_key_3"] = unmerged_df["normalized_name"].str[:3]
        blocks_3 = unmerged_df.groupby("block_key_3")["entity_num"].apply(list).to_dict()

        for block_key, members in blocks_3.items():
            if len(members) <= 1:
                continue
            if len(members) > pass2_max_block:
                continue

            block_data = unmerged_df[unmerged_df["entity_num"].isin(members)]
            names = dict(zip(block_data["entity_num"], block_data["normalized_name"]))

            member_list = list(names.keys())
            for i in range(len(member_list)):
                for j in range(i + 1, len(member_list)):
                    a, b = member_list[i], member_list[j]
                    total_comparisons += 1
                    score = fuzz.token_sort_ratio(names[a], names[b])
                    effective = _numeric_suffix_guard(names[a], names[b], pass2_threshold)
                    if score >= effective:
                        uf.union(a, b)
                        total_merges += 1
                    elif effective > pass2_threshold:
                        numeric_blocked += 1

    if total_merges == 0:
        return variants

    pass2_merges = total_merges - pass1_merges
    logger.info(
        "  Fuzzy clustering: %d comparisons, %d merges (pass1=%d, pass2=%d), %d numeric-suffix blocked",
        total_comparisons, total_merges, pass1_merges, pass2_merges, numeric_blocked,
    )

    # Remap entity_nums: all members of a component get the same entity_num
    components = uf.components()
    remap = {}
    for root, members in components.items():
        if len(members) <= 1:
            continue
        # Pick canonical: member with highest total_count, prefer legal suffix
        member_data = entity_df[entity_df["entity_num"].isin(members)]
        has_suffix = member_data["canonical_name"].apply(
            lambda n: bool(_LEGAL_SUFFIX_RE.search(n)) if isinstance(n, str) else False
        )
        candidates = member_data[has_suffix] if has_suffix.any() else member_data
        best_idx = candidates["total_count"].idxmax()
        best_num = candidates.at[best_idx, "entity_num"]
        best_name = candidates.at[best_idx, "canonical_name"]

        for m in members:
            if m != best_num:
                remap[m] = (best_num, best_name)

    # Apply remap to variants
    variants = variants.copy()
    for old_num, (new_num, new_name) in remap.items():
        mask = variants["entity_num"] == old_num
        variants.loc[mask, "entity_num"] = new_num
        variants.loc[mask, "canonical_name"] = new_name
        variants.loc[mask, "cluster_method"] = "fuzzy"

    return variants


# ---------------------------------------------------------------------------
# Step 5: Cross-source linking
# ---------------------------------------------------------------------------

def _cross_source_link(
    variants: pd.DataFrame,
    threshold: int = 80,
    max_block_size: int = 500,
) -> pd.DataFrame:
    """Link entities across BDC and N-PORT sources.

    1. Structured ID matching (CUSIP, LEI)
    2. Fuzzy name matching (block by first 4 chars, lower threshold)
    """
    # Entity-level aggregation with source info
    entity_df = (
        variants.groupby("entity_num")
        .agg(
            normalized_name=("normalized_name", "first"),
            canonical_name=("canonical_name", "first"),
            total_count=("occurrence_count", "sum"),
            sources=("source", lambda x: set(x)),
            cusip=("cusip", lambda x: next((v for v in x if pd.notna(v) and v != ""), None)),
            lei=("lei", lambda x: next((v for v in x if pd.notna(v) and v != ""), None)),
        )
        .reset_index()
    )

    # Separate BDC-only and NPORT-only entities
    bdc_only = entity_df[entity_df["sources"].apply(lambda s: s == {"bdc"})].copy()
    nport_only = entity_df[entity_df["sources"].apply(lambda s: s == {"nport"})].copy()

    if bdc_only.empty or nport_only.empty:
        return variants

    uf = UnionFind()
    merges = 0

    # Phase 1: Structured ID matching (CUSIP, LEI)
    # Build lookup from NPORT structured IDs
    cusip_to_nport = {}
    lei_to_nport = {}
    for _, row in nport_only.iterrows():
        if row["cusip"] and pd.notna(row["cusip"]):
            cusip_to_nport[row["cusip"]] = row["entity_num"]
        if row["lei"] and pd.notna(row["lei"]):
            lei_to_nport[row["lei"]] = row["entity_num"]

    for _, row in bdc_only.iterrows():
        if row["cusip"] and pd.notna(row["cusip"]) and row["cusip"] in cusip_to_nport:
            uf.union(row["entity_num"], cusip_to_nport[row["cusip"]])
            merges += 1
        if row["lei"] and pd.notna(row["lei"]) and row["lei"] in lei_to_nport:
            uf.union(row["entity_num"], lei_to_nport[row["lei"]])
            merges += 1

    # Phase 2: Fuzzy name matching (blocked by first 4 chars)
    bdc_only["block_key"] = bdc_only["normalized_name"].str[:4]
    nport_only["block_key"] = nport_only["normalized_name"].str[:4]

    # Build block index for NPORT
    nport_blocks = defaultdict(list)
    for _, row in nport_only.iterrows():
        nport_blocks[row["block_key"]].append(
            (row["entity_num"], row["normalized_name"])
        )

    comparisons = 0
    for _, bdc_row in bdc_only.iterrows():
        bk = bdc_row["block_key"]
        if bk not in nport_blocks:
            continue
        nport_in_block = nport_blocks[bk]
        if len(nport_in_block) > max_block_size:
            continue

        for nport_num, nport_name in nport_in_block:
            comparisons += 1
            score = fuzz.token_sort_ratio(
                bdc_row["normalized_name"], nport_name
            )
            if score >= threshold:
                uf.union(bdc_row["entity_num"], nport_num)
                merges += 1

    if merges == 0:
        return variants

    logger.info(
        "  Cross-source linking: %d comparisons, %d merges",
        comparisons, merges,
    )

    # Apply remap
    components = uf.components()
    remap = {}
    for root, members in components.items():
        if len(members) <= 1:
            continue
        # Pick canonical from higher-count member
        member_data = entity_df[entity_df["entity_num"].isin(members)]
        has_suffix = member_data["canonical_name"].apply(
            lambda n: bool(_LEGAL_SUFFIX_RE.search(n)) if isinstance(n, str) else False
        )
        candidates = member_data[has_suffix] if has_suffix.any() else member_data
        best_idx = candidates["total_count"].idxmax()
        best_num = candidates.at[best_idx, "entity_num"]
        best_name = candidates.at[best_idx, "canonical_name"]

        for m in members:
            if m != best_num:
                remap[m] = (best_num, best_name)

    variants = variants.copy()
    for old_num, (new_num, new_name) in remap.items():
        mask = variants["entity_num"] == old_num
        variants.loc[mask, "entity_num"] = new_num
        variants.loc[mask, "canonical_name"] = new_name
        variants.loc[mask, "cluster_method"] = "cross_source"

    return variants


# ---------------------------------------------------------------------------
# Step 5b: Manual entity overrides
# ---------------------------------------------------------------------------

def _apply_entity_overrides(
    variants: pd.DataFrame,
    overrides_path: Optional[Path] = None,
) -> pd.DataFrame:
    """Apply JSON-based entity merge and canonical name overrides.

    For merges: union-find all listed variants together, set canonical name.
    For canonical overrides: update canonical_name for matching (issuer_name, source) pairs.
    Skips gracefully if file doesn't exist or is malformed.
    """
    path = overrides_path or ENTITY_OVERRIDES_FILE
    if not path.exists():
        return variants

    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Could not load entity overrides from %s: %s", path, exc)
        return variants

    if data.get("schema_version") != "entity-overrides.v1":
        logger.warning("Unknown entity overrides schema: %s", data.get("schema_version"))
        return variants

    variants = variants.copy()
    uf = UnionFind()
    merge_count = 0

    # Apply merge overrides
    for merge in data.get("merges", []):
        canonical_name = merge.get("canonical_name", "")
        variant_specs = merge.get("variants", [])
        if not variant_specs or not canonical_name:
            continue

        # Find entity_nums for each variant
        entity_nums = []
        for spec in variant_specs:
            issuer = spec.get("issuer_name", "")
            source = spec.get("source", "")
            mask = (variants["issuer_name"] == issuer) & (variants["source"] == source)
            matched = variants.loc[mask, "entity_num"]
            if not matched.empty:
                entity_nums.append(int(matched.iloc[0]))

        if len(entity_nums) < 2:
            continue

        # Union all matched entity_nums
        for i in range(1, len(entity_nums)):
            uf.union(entity_nums[0], entity_nums[i])
            merge_count += 1

    # Apply UF merges
    if merge_count > 0:
        components = uf.components()
        for root, members in components.items():
            if len(members) <= 1:
                continue
            # Find the canonical name from the merge spec (first matching)
            # by looking at which merge spec covers these entity_nums
            best_num = min(members)  # deterministic pick
            # Try to find a merge spec that covers these members
            override_canonical = None
            for merge in data.get("merges", []):
                merge_nums = set()
                for spec in merge.get("variants", []):
                    issuer = spec.get("issuer_name", "")
                    source = spec.get("source", "")
                    mask = (variants["issuer_name"] == issuer) & (variants["source"] == source)
                    matched = variants.loc[mask, "entity_num"]
                    if not matched.empty:
                        merge_nums.add(int(matched.iloc[0]))
                if merge_nums & set(members):
                    override_canonical = merge.get("canonical_name")
                    break

            for m in members:
                if override_canonical:
                    variants.loc[variants["entity_num"] == m, "canonical_name"] = override_canonical
                variants.loc[variants["entity_num"] == m, "entity_num"] = best_num
                variants.loc[variants["entity_num"] == m, "cluster_method"] = "override"

    # Apply canonical name overrides
    canonical_count = 0
    for override in data.get("canonical_overrides", []):
        issuer = override.get("issuer_name", "")
        source = override.get("source", "")
        new_canonical = override.get("canonical_name", "")
        if not issuer or not new_canonical:
            continue
        mask = (variants["issuer_name"] == issuer) & (variants["source"] == source)
        if mask.any():
            # Update canonical_name for all variants sharing the same entity_num
            entity_nums = variants.loc[mask, "entity_num"].unique()
            for en in entity_nums:
                variants.loc[variants["entity_num"] == en, "canonical_name"] = new_canonical
            canonical_count += 1

    if merge_count > 0 or canonical_count > 0:
        logger.info(
            "  Entity overrides: %d merge operations, %d canonical overrides",
            merge_count, canonical_count,
        )

    return variants


# ---------------------------------------------------------------------------
# Step 6: Output
# ---------------------------------------------------------------------------

def _format_entity_id(num: int) -> str:
    """Format entity number as ENT-00000001."""
    return f"ENT-{num:08d}"


def _write_entity_lookup(variants: pd.DataFrame, output_path: Path) -> None:
    """Write entity_lookup.csv from the variant table."""
    out = pd.DataFrame({
        "entity_id": variants["entity_num"].apply(_format_entity_id),
        "canonical_name": variants["canonical_name"],
        "normalized_name": variants["normalized_name"],
        "issuer_name_variant": variants["issuer_name"],
        "source": variants["source"],
        "occurrence_count": variants["occurrence_count"],
        "cluster_method": variants.get("cluster_method", "exact"),
        "cusip": variants["cusip"].fillna(""),
        "lei": variants["lei"].fillna(""),
    })
    out.to_csv(output_path, index=False)
    logger.info("Wrote entity lookup: %s (%d rows)", output_path.name, len(out))


def _write_stats(variants: pd.DataFrame, output_path: Path) -> None:
    """Write entity_resolution_stats.csv."""
    total_variants = len(variants)
    total_entities = variants["entity_num"].nunique()
    bdc_variants = (variants["source"] == "bdc").sum()
    nport_variants = (variants["source"] == "nport").sum()

    bdc_entities = variants[variants["source"] == "bdc"]["entity_num"].nunique()
    nport_entities = variants[variants["source"] == "nport"]["entity_num"].nunique()

    # Count cross-source entities (entity_num appears in both sources)
    source_per_entity = variants.groupby("entity_num")["source"].apply(set)
    cross_source_count = (source_per_entity.apply(len) > 1).sum()

    fuzzy_merges = (variants.get("cluster_method", pd.Series(dtype=str)) == "fuzzy").sum()
    cross_source_merges = (variants.get("cluster_method", pd.Series(dtype=str)) == "cross_source").sum()

    stats = pd.DataFrame([{
        "total_variants": total_variants,
        "total_entities": total_entities,
        "bdc_variants": bdc_variants,
        "nport_variants": nport_variants,
        "bdc_entities": bdc_entities,
        "nport_entities": nport_entities,
        "cross_source_entities": cross_source_count,
        "fuzzy_merges": fuzzy_merges,
        "cross_source_merges": cross_source_merges,
    }])
    stats.to_csv(output_path, index=False)
    logger.info("Wrote stats: %s", output_path.name)


def _enrich_holdings(
    holdings_path: Path,
    lookup_path: Path,
    output_path: Optional[Path] = None,
) -> None:
    """Join entity_id and canonical_name onto the holdings CSV using DuckDB."""
    if output_path is None:
        output_path = holdings_path

    con = duckdb.connect()
    try:
        # Read both CSVs
        holdings_str = str(holdings_path).replace("\\", "/")
        lookup_str = str(lookup_path).replace("\\", "/")
        output_str = str(output_path).replace("\\", "/")

        # Check if holdings already has entity_id/canonical_name columns
        cols = con.execute(
            f"SELECT column_name FROM (DESCRIBE SELECT * FROM read_csv_auto('{holdings_str}', header=true, all_varchar=true))"
        ).fetchall()
        col_names = {c[0] for c in cols}
        exclude_cols = [c for c in ("entity_id", "canonical_name") if c in col_names]
        exclude_clause = f" EXCLUDE ({', '.join(exclude_cols)})" if exclude_cols else ""

        con.execute(f"""
            COPY (
                SELECT h.*{exclude_clause},
                       COALESCE(e.entity_id, '') as entity_id,
                       COALESCE(e.canonical_name, '') as canonical_name
                FROM read_csv_auto('{holdings_str}', header=true, all_varchar=true) h
                LEFT JOIN read_csv_auto('{lookup_str}', header=true, all_varchar=true) e
                  ON h.issuer_name = e.issuer_name_variant
                  AND h.source = e.source
            ) TO '{output_str}' (HEADER, DELIMITER ',')
        """)
    finally:
        con.close()

    logger.info("Enriched holdings written to %s", output_path.name)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def build_entity_lookup(
    holdings_path: Optional[Path] = None,
    fuzzy_threshold: int = 85,
    cross_source_threshold: int = 80,
    enrich: bool = True,
) -> pd.DataFrame:
    """Build the entity lookup table from unified holdings.

    Args:
        holdings_path: Path to private_markets_holdings.csv.
            Defaults to UNIFIED_HOLDINGS_FILE.
        fuzzy_threshold: Similarity threshold for within-source fuzzy matching.
        cross_source_threshold: Similarity threshold for cross-source linking.
        enrich: If True, join entity_id/canonical_name onto holdings CSV.

    Returns:
        The entity lookup DataFrame.
    """
    t0 = time.time()
    if holdings_path is None:
        holdings_path = UNIFIED_HOLDINGS_FILE

    logger.info("=" * 60)
    logger.info("ENTITY RESOLUTION")
    logger.info("=" * 60)
    logger.info("Input: %s", holdings_path.name)

    # Step 1: Build variant table
    logger.info("")
    logger.info("Step 1: Building variant table...")
    t1 = time.time()
    variants = _build_variant_table(holdings_path)
    logger.info(
        "  %d unique (issuer_name, source) pairs in %.1f s",
        len(variants), time.time() - t1,
    )

    # Step 2-3: Exact dedup (includes name extraction + normalisation)
    logger.info("")
    logger.info("Step 2-3: Name extraction + exact dedup...")
    t2 = time.time()
    variants = _exact_dedup(variants)
    # Initialize cluster_method
    if "cluster_method" not in variants.columns:
        variants["cluster_method"] = "exact"
    else:
        variants["cluster_method"] = variants["cluster_method"].fillna("exact")
    entity_count_exact = variants["entity_num"].nunique()
    logger.info(
        "  %d provisional entities (exact dedup) in %.1f s",
        entity_count_exact, time.time() - t2,
    )

    # Step 4: Fuzzy clustering
    logger.info("")
    logger.info("Step 4: Fuzzy clustering (threshold=%d)...", fuzzy_threshold)
    t3 = time.time()
    variants = _fuzzy_cluster(variants, threshold=fuzzy_threshold)
    entity_count_fuzzy = variants["entity_num"].nunique()
    logger.info(
        "  %d entities after fuzzy merge (%d merged) in %.1f s",
        entity_count_fuzzy,
        entity_count_exact - entity_count_fuzzy,
        time.time() - t3,
    )

    # Step 5: Cross-source linking
    logger.info("")
    logger.info("Step 5: Cross-source linking (threshold=%d)...", cross_source_threshold)
    t4 = time.time()
    variants = _cross_source_link(variants, threshold=cross_source_threshold)
    entity_count_xsource = variants["entity_num"].nunique()
    logger.info(
        "  %d entities after cross-source linking (%d merged) in %.1f s",
        entity_count_xsource,
        entity_count_fuzzy - entity_count_xsource,
        time.time() - t4,
    )

    # Step 5b: Manual entity overrides
    logger.info("")
    logger.info("Step 5b: Applying entity overrides...")
    t4b = time.time()
    variants = _apply_entity_overrides(variants)
    entity_count_final = variants["entity_num"].nunique()
    logger.info(
        "  %d entities after overrides (%d merged) in %.1f s",
        entity_count_final,
        entity_count_xsource - entity_count_final,
        time.time() - t4b,
    )

    # Renumber entity_nums to be consecutive
    unique_nums = sorted(variants["entity_num"].unique())
    num_remap = {old: new for new, old in enumerate(unique_nums, 1)}
    variants["entity_num"] = variants["entity_num"].map(num_remap)

    # Step 6: Write outputs
    logger.info("")
    logger.info("Step 6: Writing outputs...")
    _write_entity_lookup(variants, ENTITY_LOOKUP_FILE)
    _write_stats(variants, ENTITY_STATS_FILE)

    # Enrich holdings
    if enrich:
        logger.info("")
        logger.info("Step 7: Enriching holdings...")
        t5 = time.time()
        # Write to temp file then replace (avoid reading and writing same file)
        import tempfile
        tmp_path = holdings_path.parent / f".{holdings_path.name}.tmp"
        _enrich_holdings(holdings_path, ENTITY_LOOKUP_FILE, tmp_path)
        tmp_path.replace(holdings_path)
        logger.info("  Enriched in %.1f s", time.time() - t5)

    elapsed = time.time() - t0
    logger.info("")
    logger.info("Entity resolution complete in %.1f s", elapsed)
    logger.info("  Total variants: %d", len(variants))
    logger.info("  Total entities: %d", entity_count_final)

    return variants
