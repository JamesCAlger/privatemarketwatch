"""Map raw BDC XBRL industry labels to GICS sub-industry names.

BDC filers report industry-level aggregates using filer-specific XBRL member
names (e.g., "healthcare education and childcare", "software and services").
This module standardises those 1,500+ labels to the ~163 GICS sub-industry
names defined by MSCI/S&P.

Three-phase mapping:
  1. Programmatic cleanup + alias table (hardcoded common mappings)
  2. Fuzzy match against GICS reference list (difflib, threshold 0.80)
  3. LLM batch mapping via OpenAI (auto if OPENAI_API_KEY is set)

Results are cached to ``gics_label_cache.csv`` so the LLM is called at most
once per unique raw label.

Public API
----------
map_to_gics(labels) -> dict[str, str]
"""

import json
import logging
import os
import re
import time
from difflib import SequenceMatcher
from typing import Optional

import pandas as pd

try:
    from pydantic import BaseModel
except ImportError:
    BaseModel = None  # type: ignore[assignment,misc]

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

try:
    from openai import OpenAI
except ImportError:
    OpenAI = None  # type: ignore[assignment,misc]

from pipeline.config import GICS_LABEL_CACHE_FILE, GICS_REFERENCE_FILE

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# GICS reference list (loaded once)
# ---------------------------------------------------------------------------

_gics_names: list[str] | None = None


def _load_gics_names() -> list[str]:
    """Load the GICS sub-industry reference list from JSON."""
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

    class GicsMapping(BaseModel):
        label: str
        gics_sub_industry: str
        confidence: Literal["high", "medium", "low"]

    class GicsMappingResponse(BaseModel):
        mappings: list[GicsMapping]
else:
    GicsMapping = None  # type: ignore[assignment,misc]
    GicsMappingResponse = None  # type: ignore[assignment,misc]

# ---------------------------------------------------------------------------
# Phase 1: Programmatic cleanup and alias table
# ---------------------------------------------------------------------------

# Subtotal/aggregate prefixes to strip
_STRIP_PREFIXES = [
    "total investments - ",
    "total investments -",
    "total investments ",
    "total industry sectors",
    "total private credit debt investments",
    "total ",
]

# Labels that are aggregates, not real industries -- map to "Other"
_AGGREGATE_LABELS = {
    "all industries",
    "all other industries",
    "all other industry sectors",
    "all other sectors",
    "total investments",
    "total industry sectors",
    "total private credit debt investments",
    "aggregate sectors",
    "assets in excess of other liabilities",
    "affiliated investments",
    "non controlled affiliated investments",
    "controlled affiliated investments",
    "joint ventures",
    "investments in joint ventures",
    "investments in first lien debt",
    "investments in second lien debt",
    "first lien senior secured",
    "secured debt",
    "investment holdings and cash equivalents",
    "sub total",
}

# Prefix patterns that indicate aggregate/subtotal labels
_AGGREGATE_PREFIXES = [
    "total ",
    "sub total",
    "sub-total",
    "subtotal",
    "investments in ",
]

# Hardcoded alias map: raw label (lowercase) -> GICS sub-industry name.
# These cover the highest-FV labels and common BDC naming patterns.
_ALIAS_MAP: dict[str, str] = {
    # Software
    "software": "Application Software",
    "software and services": "Application Software",
    "software services": "Application Software",
    "software and computer": "Application Software",
    "internet software and services": "Application Software",
    "application software": "Application Software",
    "systems software": "Systems Software",
    "business applications software": "Application Software",
    "business productivity software": "Application Software",
    "automation workflow software": "Application Software",
    # IT / Technology
    "itservices": "IT Consulting & Other Services",
    "it services": "IT Consulting & Other Services",
    "technology": "Application Software",
    "high tech industries": "Application Software",
    "information technology": "Application Software",
    "information technology services": "IT Consulting & Other Services",
    # Insurance
    "insurance": "Property & Casualty Insurance",
    "insurance industry": "Property & Casualty Insurance",
    # Professional services
    "professional services": "Research & Consulting Services",
    "consulting": "Research & Consulting Services",
    "consulting services": "Research & Consulting Services",
    "research and consulting services": "Research & Consulting Services",
    # Healthcare
    "healthcare": "Health Care Services",
    "healthcare and pharmaceuticals": "Health Care Services",
    "healthcare pharmaceuticals": "Health Care Services",
    "health care providers services": "Health Care Services",
    "health care providers and services": "Health Care Services",
    "healthcare providers and services": "Health Care Services",
    "health care services": "Health Care Services",
    "healthcare services": "Health Care Services",
    "health care technology": "Health Care Technology",
    "healthcare technology": "Health Care Technology",
    "health care equipment services": "Health Care Equipment",
    "health care equipment and services": "Health Care Equipment",
    "healthcare equipment and services": "Health Care Equipment",
    "health care equipment supplies": "Health Care Equipment",
    "health care equipment and supplies": "Health Care Equipment",
    "healthcare equipment": "Health Care Equipment",
    "medical equipment and services": "Health Care Equipment",
    "health care": "Health Care Services",
    "healthcare education and childcare": "Health Care Services",
    "drug discovery and development": "Pharmaceuticals",
    # Financial services
    "financial services": "Diversified Financial Services",
    "diversified financial services": "Diversified Financial Services",
    "diversified financials": "Diversified Financial Services",
    "banking": "Diversified Banks",
    "banking finance insurance and real estate": "Diversified Financial Services",
    "banking finance insurance and realestate": "Diversified Financial Services",
    "banking finance insurance real estate": "Diversified Financial Services",
    "banks": "Diversified Banks",
    "bank": "Diversified Banks",
    "consumer finance": "Consumer Finance",
    "asset management and custody banks": "Asset Management & Custody Banks",
    "asset management custody banks": "Asset Management & Custody Banks",
    "capital markets": "Diversified Capital Markets",
    "brokerage": "Investment Banking & Brokerage",
    "specialized finance": "Specialized Finance",
    "investment funds and vehicles": "Asset Management & Custody Banks",
    # Commercial services
    "commercial services supplies": "Diversified Support Services",
    "commercial services and supplies": "Diversified Support Services",
    "commercial and professional services": "Diversified Support Services",
    "business services": "Diversified Support Services",
    "services business": "Diversified Support Services",
    # Consumer
    "consumer": "Specialized Consumer Services",
    "consumer services": "Specialized Consumer Services",
    "diversified consumer services": "Specialized Consumer Services",
    "consumer discretionary": "Specialized Consumer Services",
    "consumer staples": "Packaged Foods & Meats",
    # Aerospace
    "aerospace and defense": "Aerospace & Defense",
    "aerospace and defence": "Aerospace & Defense",
    "aerospace defense": "Aerospace & Defense",
    "aerospace": "Aerospace & Defense",
    "aerospace and defense manufacturing": "Aerospace & Defense",
    # Food & Beverage
    "food and beverage": "Packaged Foods & Meats",
    "food beverage": "Packaged Foods & Meats",
    "food products": "Packaged Foods & Meats",
    "food beverage and tobacco": "Packaged Foods & Meats",
    "beverage food and tobacco": "Packaged Foods & Meats",
    "beverage food tobacco": "Packaged Foods & Meats",
    "beverages": "Soft Drinks & Non-alcoholic Beverages",
    "beverage": "Soft Drinks & Non-alcoholic Beverages",
    "beverage and food": "Packaged Foods & Meats",
    # Media
    "media": "Movies & Entertainment",
    "media and entertainment": "Movies & Entertainment",
    "media entertainment": "Movies & Entertainment",
    "entertainment": "Movies & Entertainment",
    "broadcasting": "Broadcasting",
    "broadcasting and subscription media": "Broadcasting",
    "publishing": "Publishing",
    "advertising": "Advertising",
    "advertising and marketing services": "Advertising",
    # Real estate
    "real estate": "Real Estate Services",
    "real estate management development": "Real Estate Development",
    "buildings and real estate": "Real Estate Services",
    "buildings real estate": "Real Estate Services",
    "building and real estate": "Real Estate Services",
    "equity real estate investment trusts reits": "Diversified REITs",
    # Building products / Construction
    "building products": "Building Products",
    "building materials": "Construction Materials",
    "construction and engineering": "Construction & Engineering",
    "construction engineering": "Construction & Engineering",
    "construction": "Construction & Engineering",
    # Chemicals
    "chemicals": "Specialty Chemicals",
    "chemicals plastics and rubber": "Specialty Chemicals",
    "specialty chemicals": "Specialty Chemicals",
    "commodity chemicals": "Commodity Chemicals",
    # Transportation
    "transportation": "Cargo Ground Transportation",
    "transportation infrastructure": "Highways & Railtracks",
    "air freight logistics": "Air Freight & Logistics",
    "air freight and logistics": "Air Freight & Logistics",
    # Retail
    "specialty retail": "Specialty Stores",
    "retail": "Broadline Retail",
    "broadline retail": "Broadline Retail",
    "apparel retail": "Apparel Retail",
    "automotive retail": "Automotive Retail",
    # Automotive
    "automotive": "Automobile Parts & Equipment",
    "automobiles": "Automobile Manufacturers",
    "automobiles and components": "Automobile Parts & Equipment",
    "automobile components": "Automobile Parts & Equipment",
    "auto components": "Automobile Parts & Equipment",
    "auto parts and equipment": "Automobile Parts & Equipment",
    "auto parts equipment": "Automobile Parts & Equipment",
    "automobile manufacturers": "Automobile Manufacturers",
    # Capital goods / Machinery
    "capital goods": "Industrial Machinery & Supplies & Components",
    "machinery": "Industrial Machinery & Supplies & Components",
    "industrial": "Industrial Conglomerates",
    "industrials": "Industrial Conglomerates",
    "capital equipment": "Industrial Machinery & Supplies & Components",
    # Containers / Packaging
    "container and packaging": "Metal, Glass & Plastic Containers",
    "containers packaging and glass": "Metal, Glass & Plastic Containers",
    "containers and packaging": "Metal, Glass & Plastic Containers",
    "packaging": "Paper & Plastic Packaging Products & Materials",
    # Distributors
    "distributors": "Distributors",
    "distribution": "Distributors",
    # Electrical equipment
    "electrical equipment": "Electrical Components & Equipment",
    "electronic equipment instruments and components": "Electronic Equipment & Instruments",
    # Hotels / Leisure
    "hotels restaurants leisure": "Hotels, Resorts & Cruise Lines",
    "hotels restaurants and leisure": "Hotels, Resorts & Cruise Lines",
    "hotels and restaurants": "Hotels, Resorts & Cruise Lines",
    "leisure": "Leisure Products",
    "leisure products": "Leisure Products",
    # Life sciences
    "life sciences tools services": "Life Sciences Tools & Services",
    "life sciences tools and services": "Life Sciences Tools & Services",
    # Pharma / Biotech
    "pharmaceuticals": "Pharmaceuticals",
    "pharmaceuticals biotechnology and life sciences": "Pharmaceuticals",
    "biotechnology": "Biotechnology",
    # Energy
    "energy": "Oil & Gas Exploration & Production",
    "energy equipment and services": "Oil & Gas Equipment & Services",
    "oil gas and consumable fuels": "Oil & Gas Exploration & Production",
    "oil and gas": "Oil & Gas Exploration & Production",
    # Materials
    "materials": "Diversified Metals & Mining",
    "metals and mining": "Diversified Metals & Mining",
    # Telecom
    "telecommunications": "Integrated Telecommunication Services",
    "telecommunication services": "Integrated Telecommunication Services",
    "telecom": "Integrated Telecommunication Services",
    "wireless telecom services": "Wireless Telecommunication Services",
    "wireless telecommunication services": "Wireless Telecommunication Services",
    # Utilities
    "utilities": "Electric Utilities",
    "electric utilities": "Electric Utilities",
    # Education
    "education": "Education Services",
    "education services": "Education Services",
    # Semiconductors
    "semiconductors": "Semiconductors",
    "semiconductors and semiconductor equipment": "Semiconductors",
    "semiconductor materials and equipment": "Semiconductor Materials & Equipment",
    # Communications equipment
    "communications equipment": "Communications Equipment",
    # Manufacturing (generic)
    "manufacturing": "Industrial Machinery & Supplies & Components",
    # Trading companies
    "trading companies and distributors": "Trading Companies & Distributors",
    # Household
    "household products": "Household Products",
    "household and personal products": "Household Products",
    "personal care products": "Personal Care Products",
    # Environmental
    "environmental services": "Environmental & Facilities Services",
    "environmental and facilities services": "Environmental & Facilities Services",
    # Human resources
    "human resource and employment services": "Human Resource & Employment Services",
    "human resources": "Human Resource & Employment Services",
    # Security
    "security services": "Security & Alarm Services",
    # Data processing
    "data processing outsourced services": "Data Processing & Outsourced Services",
    "data processing and outsourced services": "Data Processing & Outsourced Services",
    # Apparel
    "apparel": "Apparel, Accessories & Luxury Goods",
    "textiles apparel and luxury goods": "Apparel, Accessories & Luxury Goods",
    "textiles apparel luxury goods": "Apparel, Accessories & Luxury Goods",
    # Paper / Forest
    "paper and forest products": "Paper & Plastic Packaging Products & Materials",
    # Gaming
    "casinos and gaming": "Casinos & Gaming",
    "gaming": "Casinos & Gaming",
    # Restaurants
    "restaurants": "Restaurants",
    # Homebuilding
    "homebuilding": "Homebuilding",
    # Interactive media
    "interactive media and services": "Interactive Media & Services",
    "interactive media services": "Interactive Media & Services",
    # REITs
    "reits": "Diversified REITs",
    # Misc
    "commercial and industrial": "Industrial Conglomerates",
    "multi sector holdings": "Multi-Sector Holdings",
    "multi-sector holdings": "Multi-Sector Holdings",
    "conglomerates": "Industrial Conglomerates",
    "industrial conglomerates": "Industrial Conglomerates",
    # Asset-based finance (BDC-specific, map to Specialized Finance)
    "asset based finance": "Specialized Finance",
    "asset based financing": "Specialized Finance",
    "asset based lending and finance": "Specialized Finance",
    "asset based lending and fund finance": "Specialized Finance",
    # Consumer sub-types
    "services consumer": "Specialized Consumer Services",
    "consumer discretionary distribution retail": "Broadline Retail",
    # Industrial sub-types
    "industrial support services": "Diversified Support Services",
    "industrial engineering": "Construction & Engineering",
    "diversified conglomerate services": "Industrial Conglomerates",
    # Communications
    "communications": "Integrated Telecommunication Services",
    # Fire / finance
    "fire finance": "Specialized Finance",
}

# Regex to strip trailing digits and numbering suffixes like "one", "two", "1"
_TRAILING_NUMBER_RE = re.compile(
    r"\s*(?:one|two|three|four|five|six|seven|eight|nine|ten|\d+)\s*$"
)
# Regex to strip sector/industry suffixes
_TRAILING_NOISE_RE = re.compile(
    r"\s*(?:sector|industry)\s*\.?\s*$"
)
# Filer-specific prefixes like "abf" or "arcc" or "glad"
_FILER_PREFIX_RE = re.compile(r"^[a-z]{2,5}(?=[A-Z]|(?:commercial|specialty|leasing))")


def _normalize_label(raw: str) -> str:
    """Clean up a raw industry label for matching."""
    label = raw.strip().lower()

    # Strip aggregate prefixes
    for prefix in _STRIP_PREFIXES:
        if label.startswith(prefix):
            label = label[len(prefix):].strip()
            break

    # Strip trailing numbering ("one", "two", "1", "2")
    label = _TRAILING_NUMBER_RE.sub("", label)

    # Strip trailing "sector", "industry"
    label = _TRAILING_NOISE_RE.sub("", label)

    # Strip trailing punctuation
    label = label.rstrip(".,;:")

    # Collapse whitespace
    label = re.sub(r"\s+", " ", label).strip()

    return label


def _gics_lookup_key(name: str) -> str:
    """Normalise a GICS name for case-insensitive lookup."""
    return name.strip().lower().replace("&", "and")


# ---------------------------------------------------------------------------
# Phase 2: Fuzzy matching
# ---------------------------------------------------------------------------

_FUZZY_THRESHOLD = 0.80


def _fuzzy_match(label: str, gics_names: list[str]) -> tuple[str, float] | None:
    """Find the best fuzzy match for *label* against the GICS list.

    Returns (gics_name, score) if score >= threshold, else None.
    """
    best_name = ""
    best_score = 0.0

    # Normalise label for comparison
    label_norm = label.lower().replace("&", "and")

    for gics_name in gics_names:
        gics_norm = gics_name.lower().replace("&", "and")
        score = SequenceMatcher(None, label_norm, gics_norm).ratio()
        if score > best_score:
            best_score = score
            best_name = gics_name

    if best_score >= _FUZZY_THRESHOLD:
        return best_name, best_score
    return None


# ---------------------------------------------------------------------------
# Phase 3: LLM batch mapping
# ---------------------------------------------------------------------------

_LLM_BATCH_SIZE = 50
_LLM_DELAY = 0.5

_LLM_SYSTEM_PROMPT = """\
You are a financial data classification specialist. You will map raw industry \
labels from SEC BDC (Business Development Company) XBRL filings to the \
closest GICS (Global Industry Classification Standard) sub-industry name.

Rules:
- Each label must map to EXACTLY one name from the provided GICS list, or "Other" \
if no reasonable match exists.
- Prefer the most specific sub-industry that fits. For example, "aerospace" -> \
"Aerospace & Defense", not "Industrial Conglomerates".
- Labels like "software" should map to "Application Software" (the most common \
sub-industry for BDC software investments).
- Labels that are clearly aggregates, subtotals, or non-industry text should \
map to "Other".
- If a label combines multiple industries (e.g., "banking finance insurance \
and real estate"), pick the dominant one or use "Diversified Financial Services".
"""


def _call_llm_batch(
    labels: list[str],
    gics_names: list[str],
) -> dict[str, str]:
    """Call OpenAI to map a batch of labels to GICS names.

    Returns dict: raw_label -> gics_sub_industry.
    """
    if OpenAI is None:
        logger.warning("openai SDK not installed -- cannot run LLM mapping")
        return {}

    client = OpenAI()
    gics_list_str = "\n".join(f"- {n}" for n in gics_names)

    numbered = "\n".join(f"{i+1}. {label}" for i, label in enumerate(labels))
    user_prompt = (
        f"Map each of the following industry labels to the closest GICS "
        f"sub-industry name from this list:\n\n{gics_list_str}\n\n"
        f"Labels to map:\n{numbered}"
    )

    use_structured = (
        GicsMappingResponse is not None
        and hasattr(getattr(client, "beta", None), "chat")
    )

    try:
        if use_structured:
            response = client.beta.chat.completions.parse(
                model="gpt-4o-mini",
                max_tokens=8192,
                messages=[
                    {"role": "system", "content": _LLM_SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                response_format=GicsMappingResponse,
            )
            parsed = response.choices[0].message.parsed
            if parsed is not None:
                result: dict[str, str] = {}
                gics_set = set(gics_names) | {"Other"}
                for m in parsed.mappings:
                    # Validate the response is a real GICS name
                    if m.gics_sub_industry in gics_set:
                        result[m.label] = m.gics_sub_industry
                    else:
                        result[m.label] = "Other"
                return result
        else:
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                max_tokens=8192,
                messages=[
                    {"role": "system", "content": _LLM_SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
            )
            text = response.choices[0].message.content or ""
            return _parse_llm_text_response(text, labels, gics_names)
    except Exception as exc:
        logger.error("LLM batch mapping failed: %s", exc)
        return {}

    return {}


def _parse_llm_text_response(
    text: str,
    labels: list[str],
    gics_names: list[str],
) -> dict[str, str]:
    """Parse unstructured LLM response into label->GICS mapping."""
    text = text.strip()
    if not text:
        return {}

    # Try JSON parse first
    if "```json" in text:
        text = text.split("```json")[1].split("```")[0].strip()
    elif "```" in text:
        text = text.split("```")[1].split("```")[0].strip()

    gics_set = set(gics_names) | {"Other"}
    result: dict[str, str] = {}

    try:
        items = json.loads(text)
        if isinstance(items, dict) and "mappings" in items:
            items = items["mappings"]
        if not isinstance(items, list):
            items = [items]

        for item in items:
            label = item.get("label", "")
            gics = item.get("gics_sub_industry", "Other")
            if label and gics in gics_set:
                result[label] = gics
            elif label:
                result[label] = "Other"
    except (json.JSONDecodeError, KeyError, TypeError):
        logger.warning("Could not parse LLM response as JSON")

    return result


def _run_llm_mapping(
    unmapped: list[str],
    gics_names: list[str],
) -> dict[str, str]:
    """Run LLM mapping on all unmapped labels in batches."""
    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        logger.warning(
            "OPENAI_API_KEY not set -- %d labels will be mapped to 'Other'",
            len(unmapped),
        )
        return {label: "Other" for label in unmapped}

    result: dict[str, str] = {}
    total_batches = (len(unmapped) + _LLM_BATCH_SIZE - 1) // _LLM_BATCH_SIZE

    for i in range(0, len(unmapped), _LLM_BATCH_SIZE):
        batch = unmapped[i:i + _LLM_BATCH_SIZE]
        batch_num = i // _LLM_BATCH_SIZE + 1
        logger.info(
            "  LLM batch %d/%d (%d labels)...",
            batch_num, total_batches, len(batch),
        )

        batch_result = _call_llm_batch(batch, gics_names)
        result.update(batch_result)

        # Map any labels the LLM didn't return to "Other"
        for label in batch:
            if label not in result:
                result[label] = "Other"

        if i + _LLM_BATCH_SIZE < len(unmapped):
            time.sleep(_LLM_DELAY)

    return result


# ---------------------------------------------------------------------------
# Cache management
# ---------------------------------------------------------------------------

def _load_cache() -> dict[str, tuple[str, str]]:
    """Load cached label mappings.

    Returns dict: raw_label -> (gics_sub_industry, source).
    """
    if not GICS_LABEL_CACHE_FILE.exists():
        return {}

    df = pd.read_csv(GICS_LABEL_CACHE_FILE, dtype=str)
    cache: dict[str, tuple[str, str]] = {}
    for _, row in df.iterrows():
        label = str(row.get("raw_label", ""))
        gics = str(row.get("gics_sub_industry", "Other"))
        source = str(row.get("source", "unknown"))
        if label:
            cache[label] = (gics, source)
    return cache


def _save_cache(cache: dict[str, tuple[str, str]]) -> None:
    """Save label cache to disk."""
    records = [
        {"raw_label": label, "gics_sub_industry": gics, "source": source}
        for label, (gics, source) in sorted(cache.items())
    ]
    df = pd.DataFrame(records)
    df.to_csv(GICS_LABEL_CACHE_FILE, index=False)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def map_to_gics(labels: list[str]) -> dict[str, str]:
    """Map raw industry labels to GICS sub-industry names.

    Parameters
    ----------
    labels : list[str]
        Raw industry sector labels from bdc_sector_breakdown.

    Returns
    -------
    dict[str, str]
        Mapping from raw_label -> GICS sub-industry name (or "Other").
        Uses cached results where available; only processes new labels.
    """
    if not labels:
        return {}

    gics_names = _load_gics_names()

    # Build case-insensitive lookup: normalised GICS name -> canonical name
    gics_exact: dict[str, str] = {}
    for name in gics_names:
        gics_exact[_gics_lookup_key(name)] = name

    # Load cache
    cache = _load_cache()

    # Result map
    result: dict[str, str] = {}
    unmapped: list[str] = []

    unique_labels = list(dict.fromkeys(labels))  # preserve order, dedup
    cache_updated = False

    for raw_label in unique_labels:
        # Check cache first
        if raw_label in cache:
            result[raw_label] = cache[raw_label][0]
            continue

        # Phase 1a: Check if it's an aggregate label
        cleaned = _normalize_label(raw_label)
        raw_lower = raw_label.lower().strip()
        is_aggregate = (
            raw_lower in _AGGREGATE_LABELS
            or cleaned in _AGGREGATE_LABELS
            or any(raw_lower.startswith(p) for p in _AGGREGATE_PREFIXES)
        )
        if is_aggregate:
            result[raw_label] = "Other"
            cache[raw_label] = ("Other", "aggregate")
            cache_updated = True
            continue

        # Phase 1b: Check alias map (on cleaned label)
        alias_result = _ALIAS_MAP.get(cleaned)
        if alias_result is None:
            # Also try the raw label directly
            alias_result = _ALIAS_MAP.get(raw_label.lower().strip())
        if alias_result is not None:
            result[raw_label] = alias_result
            cache[raw_label] = (alias_result, "alias")
            cache_updated = True
            continue

        # Phase 1c: Exact match against GICS names
        exact_key = _gics_lookup_key(cleaned)
        if exact_key in gics_exact:
            matched = gics_exact[exact_key]
            result[raw_label] = matched
            cache[raw_label] = (matched, "exact")
            cache_updated = True
            continue

        # Phase 2: Fuzzy match
        fuzzy_result = _fuzzy_match(cleaned, gics_names)
        if fuzzy_result is not None:
            matched, score = fuzzy_result
            result[raw_label] = matched
            cache[raw_label] = (matched, "fuzzy")
            cache_updated = True
            continue

        # Defer to LLM
        unmapped.append(raw_label)

    # Phase 3: LLM batch mapping for remaining
    if unmapped:
        logger.info("GICS mapping: %d labels need LLM mapping", len(unmapped))
        llm_results = _run_llm_mapping(unmapped, gics_names)

        for label in unmapped:
            gics = llm_results.get(label, "Other")
            result[label] = gics
            cache[label] = (gics, "llm")
            cache_updated = True

    # Save updated cache
    if cache_updated:
        _save_cache(cache)
        # Log source breakdown
        sources: dict[str, int] = {}
        for _, (_, src) in cache.items():
            sources[src] = sources.get(src, 0) + 1
        logger.info(
            "GICS label cache: %d entries (%s)",
            len(cache),
            ", ".join(f"{k}={v}" for k, v in sorted(sources.items())),
        )

    return result
