"""Position-level GICS industry classification for unified holdings.

Classifies each position's company (issuer_name) into one of ~163 GICS
sub-industry names. Three-phase cascade:

  1. Map extracted_industry via gics_mapping alias/fuzzy ($0)
     + keyword rules on company name ($0)
     + structural skip for non-corporate rows ($0)
  2. LLM batch classification of unique company names (~$1-3 via GPT-4o-mini)
     + optional web search re-classification for low-confidence results
  3. Apply via DuckDB LEFT JOIN on normalized issuer_name

Cache: company_gics_cache.csv persists across runs so LLM is called at most
once per unique normalized company name.

Public API
----------
classify_gics(unified_df) -> pd.DataFrame
"""

import json
import logging
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Optional

import duckdb
import pandas as pd

try:
    from pydantic import BaseModel
except ImportError:
    BaseModel = None  # type: ignore[assignment,misc]

try:
    from openai import OpenAI
except ImportError:
    OpenAI = None  # type: ignore[assignment,misc]

from pipeline.config import (
    COMPANY_GICS_CACHE_FILE,
    GICS_REFERENCE_FILE,
    UNIFIED_HOLDINGS_FILE,
)
from pipeline.gics_mapping import map_to_gics as _map_label_to_gics

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_LLM_BATCH_SIZE = 50
_LLM_DELAY = 0.5
_MAX_WORKERS = 10
_CACHE_SAVE_INTERVAL = 50  # save every N batches

# Regex for opaque numeric IDs (consumer/marketplace loans)
_OPAQUE_NUMERIC_ID_RE = re.compile(r"^\d{5,}[.\-]")

# Legal suffixes to strip for company name normalization
_LEGAL_SUFFIXES = re.compile(
    r",?\s*\b("
    r"LLC|L\.L\.C\.|Inc\.?|Incorporated|Corp\.?|Corporation|"
    r"Ltd\.?|Limited|L\.P\.?|LP|Co\.?|Company|"
    r"Holdings|Holding|Group|Enterprises?|"
    r"PLC|P\.L\.C\.|N\.V\.|S\.A\.|AG|GmbH|"
    r"International|Intl\.?"
    r")\b\.?\s*$",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# GICS reference
# ---------------------------------------------------------------------------

_gics_names: list[str] | None = None


def _load_gics_names() -> list[str]:
    """Load GICS sub-industry reference list."""
    global _gics_names
    if _gics_names is not None:
        return _gics_names
    with open(GICS_REFERENCE_FILE, encoding="utf-8") as f:
        _gics_names = json.load(f)
    return _gics_names


# ---------------------------------------------------------------------------
# Pydantic schema for LLM structured output
# ---------------------------------------------------------------------------

if BaseModel is not None:
    from typing import Literal

    class CompanyClassification(BaseModel):
        id: int
        gics_sub_industry: str
        confidence: Literal["high", "medium", "low"]

    class CompanyClassificationResponse(BaseModel):
        classifications: list[CompanyClassification]
else:
    CompanyClassification = None  # type: ignore[assignment,misc]
    CompanyClassificationResponse = None  # type: ignore[assignment,misc]

# ---------------------------------------------------------------------------
# Company name normalization
# ---------------------------------------------------------------------------


def _normalize_company_name(name: str) -> str:
    """Normalize company name for dedup: lowercase, strip legal suffixes,
    collapse whitespace, strip trailing punctuation.
    """
    if not name:
        return ""
    n = name.strip().lower()
    # Strip legal suffixes (iterative, handles "Holdings, LLC")
    for _ in range(3):
        prev = n
        n = _LEGAL_SUFFIXES.sub("", n).strip()
        if n == prev:
            break
    # Collapse whitespace
    n = re.sub(r"\s+", " ", n).strip()
    # Strip trailing punctuation
    n = n.rstrip(".,;:-")
    return n


# ---------------------------------------------------------------------------
# Phase 1b: Keyword rules (high-precision, low-recall)
# ---------------------------------------------------------------------------

_KEYWORD_RULES: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\bdental\b", re.I), "Health Care Services"),
    (re.compile(r"\bhospital\b", re.I), "Health Care Facilities"),
    (re.compile(r"\bpharma(?:ceut)?\b", re.I), "Pharmaceuticals"),
    (re.compile(r"\brestaurant\b", re.I), "Restaurants"),
    (re.compile(r"\bveterinar", re.I), "Health Care Services"),
    (re.compile(r"\binsurance\b", re.I), "Property & Casualty Insurance"),
    (re.compile(r"\bsoftware\b", re.I), "Application Software"),
    (re.compile(r"\bautomotive\b", re.I), "Automobile Parts & Equipment"),
    (re.compile(r"\bairline", re.I), "Passenger Airlines"),
    (re.compile(r"\bhotel\b", re.I), "Hotels, Resorts & Cruise Lines"),
    (re.compile(r"\bgrocery\b|\bsupermarket\b", re.I), "Food Distributors"),
    (re.compile(r"\bgymnasi|\bfitness\b", re.I), "Leisure Facilities"),
    (re.compile(r"\bcabin[eo]t\b|\bfurniture\b", re.I), "Home Furnishings"),
    (re.compile(r"\bcasino\b|\bgaming\b", re.I), "Casinos & Gaming"),
    (re.compile(r"\bbrewery\b|\bbrewing\b|\bdistiller", re.I), "Distillers & Vintners"),
    (re.compile(r"\bpipeline\b", re.I), "Oil & Gas Storage & Transportation"),
    (re.compile(r"\bsemiconductor\b", re.I), "Semiconductors"),
    (re.compile(r"\bphysician\b|\bmedical\b.*\bgroup\b", re.I), "Health Care Services"),
    (re.compile(r"\bstaffing\b|\brecruitment\b", re.I), "Human Resource & Employment Services"),
    (re.compile(r"\bcybersecur", re.I), "Systems Software"),
    (re.compile(r"\bdata\s*cent[er]", re.I), "Data Processing & Outsourced Services"),
    (re.compile(r"\bwaste\s*management\b|\bwaste\s*serv", re.I), "Environmental & Facilities Services"),
    (re.compile(r"\btelecom", re.I), "Integrated Telecommunication Services"),
    (re.compile(r"\bpet\s*care\b|\bpet\s*food\b|\bpet\s*supply\b", re.I), "Packaged Foods & Meats"),
]


def _classify_by_keyword(name_norm: str) -> str | None:
    """Apply keyword rules. Return GICS sub-industry or None."""
    for pattern, gics in _KEYWORD_RULES:
        if pattern.search(name_norm):
            return gics
    return None


# ---------------------------------------------------------------------------
# Phase 1a: Map extracted_industry labels to GICS
# ---------------------------------------------------------------------------


def _classify_from_extracted_industry(
    unified_df: pd.DataFrame,
) -> dict[str, str]:
    """Map extracted_industry labels to GICS via gics_mapping module.

    Returns dict: normalized_company_name -> gics_sub_industry.
    Only includes entries where a non-'Other' mapping was found.
    """
    con = duckdb.connect()
    con.register("unified", unified_df)

    # Get (issuer_name, extracted_industry) counts for CORPORATE rows
    pairs = con.execute("""
        SELECT
            CAST(issuer_name AS VARCHAR) AS issuer_name,
            CAST(extracted_industry AS VARCHAR) AS extracted_industry,
            COUNT(*) AS vote_count
        FROM unified
        WHERE CAST(extracted_industry AS VARCHAR) != ''
          AND CAST(issuer_category AS VARCHAR) = 'CORPORATE'
        GROUP BY 1, 2
    """).fetchdf()
    con.close()

    if pairs.empty:
        return {}

    # Get unique industry labels and map them
    unique_labels = pairs["extracted_industry"].unique().tolist()
    label_to_gics = _map_label_to_gics(unique_labels)

    # Build name -> gics (majority vote when multiple labels per company)
    name_votes: dict[str, dict[str, int]] = {}
    for _, row in pairs.iterrows():
        name_norm = _normalize_company_name(str(row["issuer_name"]))
        if not name_norm:
            continue
        gics = label_to_gics.get(str(row["extracted_industry"]), "Other")
        if gics == "Other":
            continue
        if name_norm not in name_votes:
            name_votes[name_norm] = {}
        count = int(row["vote_count"])
        name_votes[name_norm][gics] = name_votes[name_norm].get(gics, 0) + count

    # Pick majority for each name
    result: dict[str, str] = {}
    for name_norm, votes in name_votes.items():
        best = max(votes, key=votes.get)  # type: ignore[arg-type]
        result[name_norm] = best

    return result


# ---------------------------------------------------------------------------
# Phase 1c: Structural inference (skip non-corporate)
# ---------------------------------------------------------------------------


def _get_skip_names(unified_df: pd.DataFrame) -> set[str]:
    """Return normalized names that should be skipped (FUND, GOVERNMENT, opaque IDs)."""
    con = duckdb.connect()
    con.register("unified", unified_df)

    skip_rows = con.execute("""
        SELECT DISTINCT CAST(issuer_name AS VARCHAR) AS issuer_name
        FROM unified
        WHERE CAST(issuer_category AS VARCHAR) IN ('FUND', 'GOVERNMENT')
           OR CAST(nport_asset_cat AS VARCHAR) = 'STIV'
    """).fetchdf()
    con.close()

    skip_names: set[str] = set()
    for name in skip_rows["issuer_name"]:
        norm = _normalize_company_name(str(name))
        if norm:
            skip_names.add(norm)

    return skip_names


# ---------------------------------------------------------------------------
# Phase 2: LLM batch classification
# ---------------------------------------------------------------------------

_LLM_SYSTEM_PROMPT = """\
You classify private company names from SEC filings into GICS sub-industries. \
These are middle-market companies receiving debt or equity investments from \
BDCs (Business Development Companies) and interval funds. Classify by company \
name only. If you cannot determine the industry from the name alone, use "Other".\
"""


def _build_batch_prompt(companies: list[str], gics_names: list[str]) -> str:
    """Build the user prompt for a batch of company names."""
    gics_list = "\n".join(f"- {n}" for n in gics_names)
    numbered = "\n".join(f"{i+1}. {c}" for i, c in enumerate(companies))
    return (
        f"GICS sub-industries (use EXACTLY one of these names, or \"Other\"):\n"
        f"{gics_list}\n\n"
        f"Classify each company:\n{numbered}"
    )


def _call_openai_batch(
    companies: list[str],
    gics_names: list[str],
    client: object,
) -> list[dict]:
    """Call GPT-4o-mini for a batch of companies.

    Returns list of dicts with keys: id, gics_sub_industry, confidence.
    """
    prompt = _build_batch_prompt(companies, gics_names)
    gics_set = set(gics_names) | {"Other"}

    use_structured = (
        CompanyClassificationResponse is not None
        and hasattr(getattr(client, "beta", None), "chat")
    )

    try:
        if use_structured:
            response = client.beta.chat.completions.parse(  # type: ignore[union-attr]
                model="gpt-4o-mini",
                max_tokens=8192,
                messages=[
                    {"role": "system", "content": _LLM_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                response_format=CompanyClassificationResponse,
            )
            parsed = response.choices[0].message.parsed
            if parsed is not None:
                results = []
                for c in parsed.classifications:
                    gics = c.gics_sub_industry if c.gics_sub_industry in gics_set else "Other"
                    results.append({
                        "id": c.id,
                        "gics_sub_industry": gics,
                        "confidence": c.confidence,
                    })
                return results
        else:
            # Fallback to JSON mode
            response = client.chat.completions.create(  # type: ignore[union-attr]
                model="gpt-4o-mini",
                max_tokens=8192,
                messages=[
                    {"role": "system", "content": _LLM_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                response_format={"type": "json_object"},
            )
            text = response.choices[0].message.content or ""
            return _parse_json_response(text, len(companies), gics_set)
    except Exception as exc:
        logger.error("  LLM batch failed: %s", exc)
        return []

    return []


def _parse_json_response(
    text: str,
    expected_count: int,
    gics_set: set[str],
) -> list[dict]:
    """Parse JSON response from LLM into structured results."""
    if not text.strip():
        return []
    try:
        data = json.loads(text)
        items = data.get("classifications", data) if isinstance(data, dict) else data
        if not isinstance(items, list):
            return []
        results = []
        for item in items:
            gics = item.get("gics_sub_industry", "Other")
            if gics not in gics_set:
                gics = "Other"
            results.append({
                "id": item.get("id", 0),
                "gics_sub_industry": gics,
                "confidence": item.get("confidence", "low"),
            })
        return results
    except (json.JSONDecodeError, KeyError, TypeError):
        logger.warning("  Could not parse LLM JSON response")
        return []


def _parse_batch_results(
    companies: list[str],
    raw_results: list[dict],
) -> dict[str, tuple[str, str]]:
    """Match LLM results back to company names.

    Returns dict: company_name -> (gics_sub_industry, confidence).
    """
    result: dict[str, tuple[str, str]] = {}

    # Build id -> result mapping
    by_id = {r["id"]: r for r in raw_results}

    for i, company in enumerate(companies):
        entry = by_id.get(i + 1)
        if entry:
            result[company] = (entry["gics_sub_industry"], entry["confidence"])
        else:
            result[company] = ("Other", "low")

    return result


def _run_llm_classification(
    candidates: list[str],
    gics_names: list[str],
) -> dict[str, tuple[str, str]]:
    """Run LLM classification on all candidate company names.

    Returns dict: normalized_name -> (gics_sub_industry, confidence).
    """
    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        logger.warning(
            "OPENAI_API_KEY not set -- %d names will be mapped to 'Other'",
            len(candidates),
        )
        return {name: ("Other", "low") for name in candidates}

    if OpenAI is None:
        logger.warning("openai SDK not installed -- cannot run LLM classification")
        return {name: ("Other", "low") for name in candidates}

    client = OpenAI()
    result: dict[str, tuple[str, str]] = {}

    # Build batch specs
    batches = []
    for i in range(0, len(candidates), _LLM_BATCH_SIZE):
        batches.append(candidates[i:i + _LLM_BATCH_SIZE])

    total_batches = len(batches)
    logger.info("  LLM classification: %d names in %d batches (%d workers)",
                len(candidates), total_batches, _MAX_WORKERS)

    completed = 0

    def _process_batch(batch: list[str]) -> dict[str, tuple[str, str]]:
        raw = _call_openai_batch(batch, gics_names, client)
        return _parse_batch_results(batch, raw)

    with ThreadPoolExecutor(max_workers=_MAX_WORKERS) as executor:
        futures = {
            executor.submit(_process_batch, batch): idx
            for idx, batch in enumerate(batches)
        }
        for future in as_completed(futures):
            batch_idx = futures[future]
            try:
                batch_result = future.result()
                result.update(batch_result)
            except Exception as exc:
                logger.error("  Batch %d failed: %s", batch_idx + 1, exc)
                # Fill with Other for failed batch
                for name in batches[batch_idx]:
                    result[name] = ("Other", "low")

            completed += 1
            if completed % _CACHE_SAVE_INTERVAL == 0:
                logger.info("  Progress: %d/%d batches", completed, total_batches)

    # Fill any missing
    for name in candidates:
        if name not in result:
            result[name] = ("Other", "low")

    return result


# ---------------------------------------------------------------------------
# Phase 2b: Optional web search for low-confidence results
# ---------------------------------------------------------------------------


def _search_and_reclassify(
    low_confidence: list[str],
    gics_names: list[str],
) -> dict[str, tuple[str, str]]:
    """Search for low-confidence companies and reclassify with context.

    Requires SERPER_API_KEY env var. If not set, returns empty dict.
    """
    serper_key = os.environ.get("SERPER_API_KEY", "")
    if not serper_key:
        return {}

    if OpenAI is None:
        return {}

    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        return {}

    import requests

    client = OpenAI()
    gics_set = set(gics_names) | {"Other"}
    result: dict[str, tuple[str, str]] = {}

    logger.info("  Web search reclassification: %d companies", len(low_confidence))

    for i, name in enumerate(low_confidence):
        try:
            # Search
            resp = requests.post(
                "https://google.serper.dev/search",
                json={"q": f"{name} company"},
                headers={"X-API-KEY": serper_key},
                timeout=10,
            )
            resp.raise_for_status()
            search_data = resp.json()
            organic = search_data.get("organic", [])[:3]
            context = "\n".join(
                f"- {r.get('title', '')}: {r.get('snippet', '')}"
                for r in organic
            )

            # Reclassify with context
            reclassify_prompt = (
                f"Company: {name}\n\n"
                f"Search results:\n{context}\n\n"
                f"Based on this context, classify into one GICS sub-industry "
                f"from this list (or 'Other'):\n"
                + "\n".join(f"- {g}" for g in gics_names)
            )
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                max_tokens=200,
                messages=[
                    {"role": "system", "content": _LLM_SYSTEM_PROMPT},
                    {"role": "user", "content": reclassify_prompt},
                ],
            )
            answer = (response.choices[0].message.content or "").strip()
            # Find the GICS name in the response
            for gics_name in gics_names:
                if gics_name.lower() in answer.lower():
                    result[name] = (gics_name, "medium")
                    break
            else:
                result[name] = ("Other", "low")

        except Exception as exc:
            logger.debug("  Search failed for '%s': %s", name, exc)
            continue

        if (i + 1) % 50 == 0:
            logger.info("  Search progress: %d/%d", i + 1, len(low_confidence))
        time.sleep(0.2)  # Rate limit

    return result


# ---------------------------------------------------------------------------
# Cache management
# ---------------------------------------------------------------------------


def _load_cache() -> dict[str, tuple[str, str, str]]:
    """Load company GICS cache.

    Returns dict: company_name_norm -> (gics_sub_industry, confidence, source).
    """
    if not COMPANY_GICS_CACHE_FILE.exists():
        return {}

    df = pd.read_csv(COMPANY_GICS_CACHE_FILE, dtype=str)
    cache: dict[str, tuple[str, str, str]] = {}
    for _, row in df.iterrows():
        name = str(row.get("company_name_norm", ""))
        gics = str(row.get("gics_sub_industry", "Other"))
        confidence = str(row.get("confidence", "low"))
        source = str(row.get("source", "unknown"))
        if name:
            cache[name] = (gics, confidence, source)
    return cache


def _save_cache(cache: dict[str, tuple[str, str, str]]) -> None:
    """Save company GICS cache to disk."""
    records = [
        {
            "company_name_norm": name,
            "gics_sub_industry": gics,
            "confidence": confidence,
            "source": source,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        for name, (gics, confidence, source) in sorted(cache.items())
    ]
    df = pd.DataFrame(records)
    df.to_csv(COMPANY_GICS_CACHE_FILE, index=False)


# ---------------------------------------------------------------------------
# Candidate selection
# ---------------------------------------------------------------------------


def _get_candidates(
    unified_df: pd.DataFrame,
    already_classified: set[str],
    skip_names: set[str],
) -> list[str]:
    """Return unique normalized company names needing LLM classification.

    Filters:
    - issuer_category = 'CORPORATE' only
    - Not already classified
    - Not in skip set
    - Not opaque numeric IDs
    - Name length > 2 characters
    """
    con = duckdb.connect()
    con.register("unified", unified_df)

    names_df = con.execute("""
        SELECT DISTINCT CAST(issuer_name AS VARCHAR) AS issuer_name
        FROM unified
        WHERE CAST(issuer_category AS VARCHAR) = 'CORPORATE'
    """).fetchdf()
    con.close()

    candidates: list[str] = []
    seen: set[str] = set()

    for raw_name in names_df["issuer_name"]:
        name_str = str(raw_name)
        norm = _normalize_company_name(name_str)
        if not norm or len(norm) <= 2:
            continue
        if norm in seen or norm in already_classified or norm in skip_names:
            continue
        if _OPAQUE_NUMERIC_ID_RE.match(name_str):
            continue
        seen.add(norm)
        candidates.append(norm)

    return candidates


# ---------------------------------------------------------------------------
# Phase 3: Apply enrichment via DuckDB
# ---------------------------------------------------------------------------


_LOAN_DESCRIPTORS = re.compile(
    r",\s*("
    r"first lien|second lien|third lien|"
    r"senior secured|senior unsecured|senior subordinated|"
    r"subordinated|unitranche|mezzanine|"
    r"term loan|revolver|delayed draw|"
    r"one stop|common equity|preferred (stock|equity|shares)|"
    r"member interest|affiliated issuer|"
    r"series [a-z]|class [a-z]"
    r")\b",
    re.IGNORECASE,
)


def _extract_short_name(name: str) -> str:
    """Extract company name portion from a BDC identifier that may include loan descriptors.

    Example: "KnowBe4, Inc., First Lien Term Loan" -> normalize("KnowBe4, Inc.") -> "knowbe4"
    """
    # Try splitting at first loan descriptor
    m = _LOAN_DESCRIPTORS.search(name.lower())
    if m:
        company_part = name[: m.start()].strip().rstrip(",").strip()
        if company_part:
            return _normalize_company_name(company_part)
    return ""


def _apply_gics_to_holdings(
    unified_df: pd.DataFrame,
    cache: dict[str, tuple[str, str, str]],
) -> pd.DataFrame:
    """Apply GICS classification to unified holdings via DuckDB JOIN.

    Uses two-pass matching:
    1. Exact match on full normalized issuer_name
    2. Fallback: extract company name portion (strip loan descriptors) and match
    """
    # Build lookup DataFrame
    lookup_records = [
        {"company_name_norm": name, "gics_sub_industry": gics}
        for name, (gics, _, _) in cache.items()
        if gics != "Other"
    ]

    if not lookup_records:
        logger.info("No GICS classifications to apply")
        return unified_df

    lookup_df = pd.DataFrame(lookup_records)

    # Pre-compute name normalization mapping (avoids DuckDB UDF overhead)
    # Includes both full-name normalization and short-name extraction
    unique_names = unified_df["issuer_name"].dropna().unique()
    name_map_records = []
    for name in unique_names:
        norm = _normalize_company_name(str(name))
        short = _extract_short_name(str(name))
        if norm:
            name_map_records.append({
                "issuer_name": str(name),
                "_name_norm": norm,
                "_name_short": short if short else norm,
            })

    if not name_map_records:
        return unified_df

    name_map_df = pd.DataFrame(name_map_records)

    # Add row index to preserve order through JOIN
    unified_df = unified_df.copy()
    unified_df["_row_idx"] = range(len(unified_df))

    con = duckdb.connect()
    con.register("holdings", unified_df)
    con.register("gics_lookup", lookup_df)
    con.register("name_map", name_map_df)

    result = con.execute("""
        SELECT h.* EXCLUDE (gics_sub_industry, _row_idx),
               COALESCE(g1.gics_sub_industry, g2.gics_sub_industry, '') AS gics_sub_industry,
               h._row_idx
        FROM holdings h
        LEFT JOIN name_map nm
          ON CAST(h.issuer_name AS VARCHAR) = nm.issuer_name
        LEFT JOIN gics_lookup g1
          ON nm._name_norm = g1.company_name_norm
        LEFT JOIN gics_lookup g2
          ON nm._name_short = g2.company_name_norm
          AND g1.gics_sub_industry IS NULL
        ORDER BY h._row_idx
    """).fetchdf()
    con.close()

    # Drop the temp index column
    result = result.drop(columns=["_row_idx"])

    # Ensure column order matches UNIFIED_COLUMNS
    from pipeline.unified_holdings import UNIFIED_COLUMNS
    for col in UNIFIED_COLUMNS:
        if col not in result.columns:
            result[col] = ""
    result = result[[c for c in UNIFIED_COLUMNS if c in result.columns]]

    return result


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def classify_gics(
    unified_df: Optional[pd.DataFrame] = None,
    cache_only: bool = False,
) -> pd.DataFrame:
    """Add gics_sub_industry column to unified holdings.

    Three-phase cascade:
    1. Map extracted_industry via gics_mapping + keyword rules ($0)
    2. LLM batch classification of unique company names (~$1-3)
    3. Apply via DuckDB LEFT JOIN on issuer_name

    Parameters
    ----------
    unified_df : pd.DataFrame, optional
        Unified holdings DataFrame. If None, loads from disk.

    Returns
    -------
    pd.DataFrame
        Unified holdings with gics_sub_industry populated.
    """
    t0 = time.time()
    logger.info("=== GICS Industry Classification ===")

    # Load unified holdings if needed
    if unified_df is None:
        logger.info("Loading unified holdings from %s", UNIFIED_HOLDINGS_FILE.name)
        unified_df = pd.read_csv(UNIFIED_HOLDINGS_FILE, dtype=str)

    # Ensure column exists
    if "gics_sub_industry" not in unified_df.columns:
        unified_df["gics_sub_industry"] = ""

    cache_only = cache_only or os.environ.get("GICS_CACHE_ONLY", "").lower() in {
        "1", "true", "yes"
    }
    gics_names = _load_gics_names()
    cache = _load_cache()
    initial_cache_size = len(cache)

    logger.info("  Loaded cache: %d entries", initial_cache_size)
    if cache_only:
        logger.info("  Cache-only mode: applying existing company_gics_cache.csv only")

    # ── Phase 1a: Map extracted_industry to GICS ──
    logger.info("Phase 1a: Mapping extracted_industry labels...")
    industry_map = {} if cache_only else _classify_from_extracted_industry(unified_df)
    new_from_industry = 0
    for name_norm, gics in industry_map.items():
        if name_norm not in cache:
            cache[name_norm] = (gics, "high", "extracted_industry")
            new_from_industry += 1
    logger.info("  Phase 1a: %d new classifications from extracted_industry",
                new_from_industry)

    # ── Phase 1b: Keyword rules ──
    logger.info("Phase 1b: Applying keyword rules...")
    # Get all unique CORPORATE issuer names not yet in cache
    con = duckdb.connect()
    con.register("unified", unified_df)
    corp_names = con.execute("""
        SELECT DISTINCT CAST(issuer_name AS VARCHAR) AS issuer_name
        FROM unified
        WHERE CAST(issuer_category AS VARCHAR) = 'CORPORATE'
    """).fetchdf()
    con.close()

    new_from_keywords = 0
    if not cache_only:
        for raw_name in corp_names["issuer_name"]:
            norm = _normalize_company_name(str(raw_name))
            if not norm or norm in cache:
                continue
            gics = _classify_by_keyword(norm)
            if gics:
                cache[norm] = (gics, "medium", "keyword")
                new_from_keywords += 1
    logger.info("  Phase 1b: %d new classifications from keywords",
                new_from_keywords)

    # ── Phase 1c: Structural skip ──
    logger.info("Phase 1c: Identifying skip names (FUND/GOVERNMENT/opaque)...")
    skip_names = _get_skip_names(unified_df)
    logger.info("  Phase 1c: %d names to skip", len(skip_names))

    # ── Phase 2: LLM batch classification ──
    already_classified = set(cache.keys())
    candidates = [] if cache_only else _get_candidates(
        unified_df, already_classified, skip_names
    )

    if candidates:
        logger.info("Phase 2: LLM classification for %d unique company names...",
                    len(candidates))
        llm_results = _run_llm_classification(candidates, gics_names)

        for name_norm, (gics, confidence) in llm_results.items():
            cache[name_norm] = (gics, confidence, "llm")

        # ── Phase 2b: Optional search reclassification ──
        low_conf = [
            name for name, (gics, conf, _) in cache.items()
            if conf == "low" and gics == "Other" and name in set(candidates)
        ]
        if low_conf and os.environ.get("SERPER_API_KEY"):
            logger.info("Phase 2b: Web search for %d low-confidence names...",
                        len(low_conf))
            search_results = _search_and_reclassify(low_conf, gics_names)
            for name_norm, (gics, confidence) in search_results.items():
                cache[name_norm] = (gics, confidence, "search")
            logger.info("  Phase 2b: %d reclassified via search",
                        len(search_results))
    else:
        logger.info("Phase 2: All names already classified (cache hit)")

    # Save cache
    if len(cache) > initial_cache_size:
        _save_cache(cache)
        # Log source breakdown
        sources: dict[str, int] = {}
        for _, (_, _, src) in cache.items():
            sources[src] = sources.get(src, 0) + 1
        logger.info("  Cache saved: %d entries (%s)",
                    len(cache),
                    ", ".join(f"{k}={v}" for k, v in sorted(sources.items())))

    # ── Phase 3: Apply to holdings ──
    logger.info("Phase 3: Applying GICS to holdings via DuckDB JOIN...")
    result = _apply_gics_to_holdings(unified_df, cache)

    # Stats
    classified = (result["gics_sub_industry"] != "").sum()
    total = len(result)
    logger.info("  Result: %d/%d rows (%.1f%%) with gics_sub_industry",
                classified, total, 100 * classified / total if total else 0)

    # Save
    result.to_csv(UNIFIED_HOLDINGS_FILE, index=False)
    logger.info("  Saved to %s", UNIFIED_HOLDINGS_FILE.name)

    elapsed = time.time() - t0
    logger.info("GICS classification completed in %.1f s", elapsed)

    return result


# ---------------------------------------------------------------------------
# Phase 2c: OpenAI Web Search reclassification (top N by FV)
# ---------------------------------------------------------------------------

_WEB_SEARCH_SYSTEM_PROMPT = """\
You classify private companies into GICS sub-industries using web search. \
For EACH company in the list, you MUST search the web to find what it does, \
then classify it.

These are middle-market private companies receiving debt/equity investments \
from BDCs and private credit funds. Many are PE-backed.

CRITICAL RULES:
- You MUST search for and classify EVERY company in the list. Do not skip any.
- Search using the company name (if a "dba" name is shown, search that instead)
- Use the EXACT GICS sub-industry name from the list (spelling must match exactly)
- If you truly cannot find ANY information after searching, use "Other"
- For holding companies / acquisition vehicles / "bidcos", classify by the \
  operating subsidiary's industry (search for the operating company name)
- For multi-industry conglomerates, use the dominant revenue segment
- JVs and structured vehicles with no identifiable business: use "Other"

You MUST return a JSON array with EXACTLY one entry per company:
[{"id": 1, "company": "original name", "gics_sub_industry": "...", "confidence": "high|medium|low", "evidence": "what the company does"}]
"""

_WEB_SEARCH_BATCH_SIZE = 5  # Small batches: each company gets a search
_WEB_SEARCH_MAX_WORKERS = 3  # Moderate concurrency to avoid rate limits

# Regex to extract DBA/operating company name from position descriptions
_DBA_RE = re.compile(r"\((?:dba|d/b/a|fka|aka)\s+([^)]+)\)", re.IGNORECASE)
# Regex to detect obviously non-classifiable names
_SKIP_WEB_SEARCH_RE = re.compile(
    r"^(?:investments?|debt investments?|equity investments?|"
    r".*\b(?:jv|joint venture)\b.*|"
    r".*\bnote issuer\b.*|"
    r".*\bsubordinated certificates\b.*|"
    r"investments? in (?:non-controlled|controlled).*|"
    r".*\bco-invest(?:ment)?\b.*|"
    r"total\s+.*)",
    re.IGNORECASE,
)


def _extract_search_name(raw_name: str) -> str:
    """Extract the best search term from a position name.

    Handles DBA names, bidcos, and position descriptions.
    """
    # Check for DBA/AKA name first
    dba_match = _DBA_RE.search(raw_name)
    if dba_match:
        return dba_match.group(1).strip()

    # Strip common position description suffixes
    name = raw_name
    # Remove ", first lien senior secured loan" etc.
    for suffix in [
        ", first lien senior secured loan",
        ", second lien term loan",
        ", senior secured term loan",
        ", first lien term loan",
        ", delayed draw term loan",
        ", revolver",
        ", revolving credit facility",
        ", class a units",
        ", series a preferred stock",
        ", subordinated notes",
        ", llc interest",
        ", common equity",
        ", common stock",
        ", preferred equity",
    ]:
        if name.lower().endswith(suffix):
            name = name[: -len(suffix)]
            break

    # Remove trailing " 1", " 2" etc. (duplicate position markers)
    name = re.sub(r"\s+\d+$", "", name)

    return name.strip()


def _build_web_search_prompt(
    companies: list[tuple[int, str, str]],
    gics_names: list[str],
) -> str:
    """Build prompt for web-search-based classification.

    Parameters
    ----------
    companies : list of (id, search_name, extra_context)
        Extra context includes position type, fund name, etc.
    gics_names : list of valid GICS sub-industry names
    """
    gics_list = "\n".join(f"- {n}" for n in gics_names)
    company_lines = []
    for idx, name, context in companies:
        line = f"{idx}. {name}"
        if context:
            line += f" [context: {context}]"
        company_lines.append(line)
    numbered = "\n".join(company_lines)
    return (
        f"GICS sub-industries (use EXACTLY one of these, or \"Other\"):\n"
        f"{gics_list}\n\n"
        f"Search for EACH company below and classify. "
        f"Return results for ALL {len(companies)} companies:\n{numbered}\n\n"
        f"Return a JSON array with EXACTLY {len(companies)} entries, "
        f"one per company above."
    )


def _call_openai_web_search(
    companies: list[tuple[int, str, str]],
    gics_names: list[str],
    client: object,
) -> list[dict]:
    """Call OpenAI Responses API with web_search tool for a batch.

    Returns list of dicts with keys: id, gics_sub_industry, confidence,
    evidence, sources (semicolon-separated URLs from web search).
    """
    prompt = _build_web_search_prompt(companies, gics_names)
    gics_set = set(gics_names) | {"Other"}

    try:
        response = client.responses.create(  # type: ignore[union-attr]
            model="gpt-4.1-mini",
            tools=[{"type": "web_search"}],
            instructions=_WEB_SEARCH_SYSTEM_PROMPT,
            input=prompt,
        )

        # Extract text and source URLs from response
        text = ""
        source_urls: list[str] = []
        for item in response.output:
            if hasattr(item, "content"):
                for content_block in item.content:
                    if hasattr(content_block, "text"):
                        text += content_block.text
                    # Capture citation URLs from annotations
                    if hasattr(content_block, "annotations"):
                        for ann in content_block.annotations:
                            url = getattr(ann, "url", None)
                            if url:
                                # Strip utm_source tracking
                                clean_url = re.sub(
                                    r"[?&]utm_source=openai", "", url
                                )
                                if clean_url not in source_urls:
                                    source_urls.append(clean_url)

        if not text.strip():
            return []

        # Store raw response text for review (before JSON parsing)
        raw_response_text = text.strip()

        # Extract JSON from response (may be wrapped in ```json ... ```)
        json_text = text.strip()
        if "```" in json_text:
            # Extract from code block
            parts = json_text.split("```")
            for part in parts[1::2]:  # Odd indices are code blocks
                part = part.strip()
                if part.startswith("json"):
                    part = part[4:].strip()
                if part.startswith("["):
                    json_text = part
                    break

        data = json.loads(json_text)
        if not isinstance(data, list):
            data = data.get("classifications", []) if isinstance(data, dict) else []

        results = []
        for item in data:
            gics = item.get("gics_sub_industry", "Other")
            if gics not in gics_set:
                # Fuzzy match: check if close (case-insensitive)
                gics_lower = gics.lower()
                matched = False
                for valid in gics_names:
                    if valid.lower() == gics_lower:
                        gics = valid
                        matched = True
                        break
                if not matched:
                    gics = "Other"
            evidence = item.get("evidence", "")
            # Only attribute sources to companies where info was found
            # (avoid batch-level URL cross-contamination)
            has_info = evidence and not any(
                neg in evidence.lower()
                for neg in [
                    "unable to find", "no information found",
                    "insufficient information", "could not find",
                    "no specific information",
                ]
            )
            results.append({
                "id": item.get("id", 0),
                "gics_sub_industry": gics,
                "confidence": item.get("confidence", "medium"),
                "evidence": evidence,
                "sources": "; ".join(source_urls) if has_info else "",
            })
        return results

    except json.JSONDecodeError as exc:
        logger.warning("  Web search batch JSON parse error: %s", exc)
        logger.debug("  Raw text: %s", text[:500] if text else "(empty)")
        return []
    except Exception as exc:
        logger.error("  Web search batch failed: %s", exc)
        return []


def _get_top_unclassified_by_fv(
    n: int = 5000,
    unified_df: Optional[pd.DataFrame] = None,
    skip_already_searched: bool = True,
) -> pd.DataFrame:
    """Get top N unclassified company names ranked by total FV.

    Returns DataFrame with columns: company_name_norm, total_fv, n_positions, context.
    """
    if unified_df is None:
        unified_df = pd.read_csv(UNIFIED_HOLDINGS_FILE, dtype=str)

    cache = _load_cache()

    con = duckdb.connect()
    con.register("holdings", unified_df)

    # Get top companies by FV that are currently "Other" in cache
    top_df = con.execute("""
        SELECT
            CAST(issuer_name AS VARCHAR) AS issuer_name,
            SUM(TRY_CAST(fair_value AS DOUBLE)) AS total_fv,
            COUNT(*) AS n_positions,
            -- Context: most common index_classification + a sample fund name
            MODE(CAST(index_classification AS VARCHAR)) AS typical_class,
            FIRST(CAST(entity_name AS VARCHAR)) AS sample_fund
        FROM holdings
        WHERE CAST(issuer_category AS VARCHAR) = 'CORPORATE'
          AND (CAST(gics_sub_industry AS VARCHAR) = ''
               OR gics_sub_industry IS NULL)
          AND issuer_name IS NOT NULL
          AND CAST(issuer_name AS VARCHAR) != ''
        GROUP BY CAST(issuer_name AS VARCHAR)
        HAVING SUM(TRY_CAST(fair_value AS DOUBLE)) IS NOT NULL
        ORDER BY total_fv DESC
        LIMIT ?
    """, [n * 3]).fetchdf()  # Fetch extra to filter after normalization
    con.close()

    # Filter to only "Other" in cache, extract search names
    records = []
    seen: set[str] = set()
    for _, row in top_df.iterrows():
        raw_name = str(row["issuer_name"])
        norm = _normalize_company_name(raw_name)
        if not norm or norm in seen:
            continue
        if len(norm) <= 2:
            continue
        if _OPAQUE_NUMERIC_ID_RE.match(raw_name):
            continue
        # Skip obviously non-classifiable names
        if _SKIP_WEB_SEARCH_RE.match(raw_name):
            continue
        # Only include if currently "Other" or not in cache
        cached = cache.get(norm)
        if cached and cached[0] != "Other":
            continue
        # Skip if already tried with web search (avoid re-spending)
        if skip_already_searched and cached and cached[2] == "web_search":
            continue
        seen.add(norm)

        # Extract the best search term
        search_name = _extract_search_name(raw_name)

        context_parts = []
        if row.get("typical_class"):
            context_parts.append(str(row["typical_class"]))
        if row.get("sample_fund"):
            context_parts.append(f"held by {str(row['sample_fund'])}")
        records.append({
            "company_name_norm": norm,
            "issuer_name_raw": raw_name,
            "search_name": search_name,
            "total_fv": float(row["total_fv"]) if row["total_fv"] else 0,
            "n_positions": int(row["n_positions"]),
            "context": "; ".join(context_parts),
        })
        if len(records) >= n:
            break

    return pd.DataFrame(records)


def reclassify_with_web_search(
    n: int = 5000,
    unified_df: Optional[pd.DataFrame] = None,
    dry_run: bool = False,
) -> pd.DataFrame:
    """Reclassify top N unclassified companies using OpenAI web search.

    Uses the Responses API with web_search tool to find information about
    each company, then classifies into GICS sub-industries.

    Parameters
    ----------
    n : int
        Number of top companies (by FV) to reclassify.
    unified_df : pd.DataFrame, optional
        Unified holdings. If None, loads from disk.
    dry_run : bool
        If True, only returns candidates without calling API.

    Returns
    -------
    pd.DataFrame
        Results with columns: company_name_norm, gics_sub_industry,
        confidence, evidence, total_fv.
    """
    t0 = time.time()
    logger.info("=== GICS Web Search Reclassification (top %d by FV) ===", n)

    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key and not dry_run:
        logger.error("OPENAI_API_KEY not set")
        return pd.DataFrame()

    # Get candidates
    candidates_df = _get_top_unclassified_by_fv(n, unified_df)
    logger.info("  Candidates: %d companies, $%.1fB total FV",
                len(candidates_df),
                candidates_df["total_fv"].sum() / 1e9)

    if dry_run:
        return candidates_df

    if candidates_df.empty:
        logger.info("  No candidates to reclassify")
        return pd.DataFrame()

    if OpenAI is None:
        logger.error("openai SDK not installed")
        return pd.DataFrame()

    client = OpenAI()
    gics_names = _load_gics_names()
    cache = _load_cache()

    # Build batches (use search_name for better web search results)
    batch_items: list[tuple[int, str, str]] = []
    # Map from batch position to norm name (for cache updates)
    batch_norm_names: list[str] = []
    for idx, row in candidates_df.iterrows():
        search_name = row.get("search_name", row["company_name_norm"])
        batch_items.append((
            len(batch_items) + 1,
            search_name,
            row.get("context", ""),
        ))
        batch_norm_names.append(row["company_name_norm"])

    # Split into batches, re-numbering 1..N within each batch for clarity
    batches: list[list[tuple[int, str, str]]] = []
    batch_norm_slices: list[list[str]] = []  # Parallel: norm names per batch
    for i in range(0, len(batch_items), _WEB_SEARCH_BATCH_SIZE):
        chunk = batch_items[i:i + _WEB_SEARCH_BATCH_SIZE]
        # Re-number within batch: 1..len(chunk)
        renumbered = [(j + 1, name, ctx) for j, (_, name, ctx) in enumerate(chunk)]
        batches.append(renumbered)
        batch_norm_slices.append(batch_norm_names[i:i + _WEB_SEARCH_BATCH_SIZE])

    total_batches = len(batches)
    logger.info("  Processing %d batches (%d companies/batch, %d workers)",
                total_batches, _WEB_SEARCH_BATCH_SIZE, _WEB_SEARCH_MAX_WORKERS)

    results: list[dict] = []
    completed = 0
    reclassified = 0

    def _process_ws_batch(
        batch: list[tuple[int, str, str]],
        norm_names: list[str],
    ) -> list[dict]:
        raw = _call_openai_web_search(batch, gics_names, client)
        batch_results = []
        for i, (batch_id, search_name, ctx) in enumerate(batch):
            norm_name = norm_names[i]
            entry = next((r for r in raw if r.get("id") == batch_id), None)
            batch_results.append({
                "company_name_norm": norm_name,
                "search_name": search_name,
                "gics_sub_industry": entry["gics_sub_industry"] if entry else "Other",
                "confidence": entry.get("confidence", "low") if entry else "low",
                "evidence": entry.get("evidence", "") if entry else "",
                "sources": entry.get("sources", "") if entry else "",
                "context": ctx,
            })
        return batch_results

    with ThreadPoolExecutor(max_workers=_WEB_SEARCH_MAX_WORKERS) as executor:
        futures = {
            executor.submit(_process_ws_batch, batch, batch_norm_slices[idx]): idx
            for idx, batch in enumerate(batches)
        }
        for future in as_completed(futures):
            batch_idx = futures[future]
            try:
                batch_results = future.result()
                results.extend(batch_results)
                for r in batch_results:
                    if r["gics_sub_industry"] != "Other":
                        reclassified += 1
            except Exception as exc:
                logger.error("  Batch %d failed: %s", batch_idx + 1, exc)

            completed += 1
            if completed % 5 == 0 or completed == total_batches:
                logger.info("  Progress: %d/%d batches, %d reclassified",
                            completed, total_batches, reclassified)

    # Update cache
    updated = 0
    for r in results:
        name = r["company_name_norm"]
        gics = r["gics_sub_industry"]
        conf = r["confidence"]
        if gics != "Other":
            cache[name] = (gics, conf, "web_search")
            updated += 1
        elif name not in cache or cache[name][0] == "Other":
            # Keep "Other" with web_search source (we tried and couldn't find it)
            cache[name] = ("Other", "low", "web_search")

    if updated > 0:
        _save_cache(cache)
        logger.info("  Cache updated: %d reclassified, %d total entries",
                    updated, len(cache))

    # Build results DataFrame
    results_df = pd.DataFrame(results)
    if not results_df.empty:
        # Merge FV data
        results_df = results_df.merge(
            candidates_df[["company_name_norm", "total_fv", "n_positions"]],
            on="company_name_norm",
            how="left",
        )

    elapsed = time.time() - t0
    non_other = (results_df["gics_sub_industry"] != "Other").sum() if not results_df.empty else 0
    logger.info("  Done: %d/%d reclassified (%.1f%%) in %.1f s",
                non_other, len(results_df),
                100 * non_other / len(results_df) if len(results_df) else 0,
                elapsed)

    # Save review queue: "Other" results with evidence for CC review
    if not results_df.empty:
        from pipeline.config import OUTPUT_DIR
        review_df = results_df[results_df["gics_sub_industry"] == "Other"].copy()
        if not review_df.empty:
            review_df = review_df.sort_values("total_fv", ascending=False)
            review_path = OUTPUT_DIR / "gics_review_queue.csv"
            review_df.to_csv(review_path, index=False)
            logger.info("  Review queue: %d companies saved to %s",
                        len(review_df), review_path.name)

    return results_df
