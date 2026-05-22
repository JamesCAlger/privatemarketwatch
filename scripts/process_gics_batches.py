"""Process GICS skill batches: triage by name patterns, then classify.

This script handles the name-pattern triage for all batches, classifying
entities as AGGREGATE_HEADER, JV_SUBSIDIARY, or marking them as needing
web search for GICS classification.

Usage:
    python scripts/process_gics_batches.py                    # Process all batches
    python scripts/process_gics_batches.py --start 1 --end 10 # Process batches 1-10
    python scripts/process_gics_batches.py --stats             # Show progress stats
"""

import argparse
import csv
import json
import logging
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd

from pipeline.config import (
    AGGREGATE_HEADER_FLAGS_FILE,
    COMPANY_GICS_CACHE_FILE,
    GICS_SKILL_BATCHES_DIR,
    GICS_SKILL_CLAIMS_FILE,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("process_gics")

# ── AGGREGATE_HEADER patterns ──────────────────────────────────────
# These are category labels, subtotals, section headers that leaked through

# Exact match patterns (lowercase)
AGG_EXACT = {
    "investments", "investments investments", "debt investments",
    "secured debt", "secured debt total", "unsecured debt",
    "unsecured debt total", "portfolio investments", "equity investments",
    "debt securities", "equity securities", "nvestments",
    "total investments", "total debt investments", "total equity investments",
    "total portfolio investments", "total secured debt", "total unsecured debt",
    "net assets", "total net assets", "total assets",
    "cash", "cash equivalents", "cash and cash equivalents",
    "cash equivalents and restricted cash equivalents",
    "other investments", "other assets", "other",
    "short-term investments", "short term investments",
    "money market funds", "warrants", "equity",
    "common stock", "preferred stock", "common equity",
    "senior secured loans", "senior secured term loans",
    "senior secured notes", "subordinated notes",
    "first lien", "second lien", "first lien debt", "second lien debt",
    "first lien senior secured", "second lien senior secured",
    "first lien term loans", "second lien term loans",
    "1st lien/secured loans", "2nd lien/secured loans",
    "1st lien/secured loans united states of america",
    "first lien senior secured debt", "second lien senior secured debt",
    "senior secured first lien term loans",
    "senior secured second lien term loans",
    "senior unsecured debt", "mezzanine debt",
    "unitranche debt", "unitranche", "subordinated debt",
    "bank debt/senior secured loans", "bank loans",
    "collateralized loan obligations", "structured products",
    "structured finance", "structured finance investments",
    "bonds", "corporate bonds", "notes",
    "non-controlled non-affiliated investments",
    "non-controlled/non-affiliated investments",
    "non-controlled, non-affiliated investments",
    "controlled affiliated investments",
    "controlled affiliate investments",
    "controlled, affiliated investments",
    "non-controlled affiliated investments",
    "non-controlled, affiliated investments",
    "non-controlled/affiliated investments",
    "affiliate investments", "non-affiliate investments",
    "investments debt investments",
    "investments equity investments",
    "portfolio company investments",
    "total first lien", "total second lien",
    "total first lien debt", "total second lien debt",
    "diversified consumer service", "diversified consumer services",
    "u.s. treasury", "u.s. treasury bill", "federated treasury obligations",
    "portfolio company warrant investments- united states",
    "portfolio company equity investments- united states",
    "portfolio company debt investments- united states",
}

# ── GICS sub-industries used as aggregate header labels ──────────
# These GICS sub-industry names appear verbatim as issuer names
GICS_AS_AGG_LABELS = {
    "aerospace & defense", "building products", "construction & engineering",
    "electrical components & equipment", "industrial conglomerates",
    "trading companies & distributors", "environmental & facilities services",
    "human resource & employment services", "research & consulting services",
    "data processing & outsourced services", "air freight & logistics",
    "passenger airlines", "automobile parts & equipment",
    "automobile manufacturers", "consumer electronics", "home furnishings",
    "homebuilding", "household appliances", "leisure products",
    "casinos & gaming", "hotels, resorts & cruise lines", "leisure facilities",
    "restaurants", "education services", "specialized consumer services",
    "broadline retail", "specialty stores", "apparel retail",
    "food distributors", "food retail", "packaged foods & meats",
    "household products", "personal care products",
    "health care equipment", "health care supplies", "health care services",
    "health care facilities", "managed health care", "health care technology",
    "biotechnology", "pharmaceuticals", "life sciences tools & services",
    "diversified banks", "regional banks", "diversified financial services",
    "specialized finance", "consumer finance",
    "asset management & custody banks", "insurance brokers",
    "property & casualty insurance", "life & health insurance",
    "application software", "systems software",
    "communications equipment", "semiconductors",
    "integrated telecommunication services",
    "electric utilities", "gas utilities", "multi-utilities",
    "independent power producers & energy traders",
    "renewable electricity", "independent power & renewable electricity producers",
    "oil & gas exploration & production", "oil & gas equipment & services",
    "specialty chemicals", "diversified chemicals",
    "diversified metals & mining", "steel", "copper", "gold",
    "commercial printing", "security & alarm services",
    "it consulting & other services", "internet services & infrastructure",
    "interactive media & services", "movies & entertainment",
    "broadcasting", "advertising", "publishing",
}

# Regex patterns for aggregate headers
AGG_PATTERNS = [
    # Bare instrument category labels with optional percentages
    re.compile(r'^[\d.]+%[,\s]*(first lien|second lien|senior secured|unsecured|mezzanine|unitranche)', re.I),
    re.compile(r'^[\d.]+%\s+of\s+(shareholder|net|total)', re.I),
    re.compile(r'^first lien senior secured (debt|loans?)\s*[-|]', re.I),
    re.compile(r'^second lien senior secured (debt|loans?)\s*[-|]', re.I),
    re.compile(r'^senior secured (term )?loans?\s+[\d.]+%', re.I),
    # "[Instrument] [GICS industry]" patterns -- subtotal rows
    re.compile(r'^(secured debt|senior secured term loans?|warrants?|preferred stock|common stock|senior secured loans?|unsecured debt|mezzanine debt|first lien|second lien|first lien debt|second lien debt)\s+[A-Z][A-Za-z\s&,]+$', re.I),
    re.compile(r'^(total|subtotal)\s+', re.I),
    # Bare industry labels (matching known GICS sectors/industries)
    re.compile(r'^(aerospace|automotive|aviation|banking|beverages|biotechnology|building|capital goods|chemicals|commercial|communications|construction|consumer|diversified|education|electric|electronics|energy|entertainment|environmental|financial|food|gas|healthcare|health care|hotels|hotel|household|industrial|information|insurance|internet|leisure|machinery|manufacturing|media|metals|mining|oil|packaging|paper|pharmaceuticals|professional|real estate|retail|semiconductors|software|specialty|technology|telecommunications|textiles|transportation|utilities|wholesale)([\s,&]+\w+){0,4}$', re.I),
    # Affiliation headers
    re.compile(r'^(controlled|non-controlled|affiliated|non-affiliated)\s+(affiliate|non-affiliate|controlled|non-controlled)?\s*(investments?)?', re.I),
    # "- First Lien Senior Secured Loan" pattern (dash prefix)
    re.compile(r'^-\s*(first|second|senior|junior)', re.I),
    # "Investments [Type] [Category]" headers from structured XBRL
    re.compile(r'^investments\s+(debt|equity|portfolio|non-controlled|controlled)', re.I),
    # "[Type] Investments [Category]" from XBRL structured names
    re.compile(r'^(controlled|non-controlled)\s+(affiliate|affiliated)\s+investments\s+', re.I),
    # "Debt Securities [Industry]" patterns
    re.compile(r'^debt securities\s+[A-Z]', re.I),
    re.compile(r'^debt securities,\s+[A-Z]', re.I),
    # "Investment" category labels
    re.compile(r'^(investment|investments)\s+(in\s+)?(non-controlled|controlled|affiliate)', re.I),
    # "nvestments" (truncated) patterns
    re.compile(r'^nvestments\s+', re.I),
    # "[Company Type] Total [Category]" - subtotal with embedded company type
    re.compile(r'(debt investments total|equity investments total|investments total)', re.I),
    # "Senior Secured Loans NNN.N%" or "Senior Secured Loans - NNN.N%" patterns
    re.compile(r'^senior secured loans\s+[-]?\s*[\d.]+%', re.I),
    # Treasury / cash patterns
    re.compile(r'\b(treasury bill|treasury note|t-bill)\b', re.I),
    re.compile(r'^(short-term|short term)\s+investments?\b', re.I),
    re.compile(r'^united states treasury\b', re.I),
    re.compile(r'^federated\s+treasury\b', re.I),
    # "Portfolio Company [Type]- [Country] [Industry]" WITHOUT company name
    re.compile(r'^portfolio company\s+(warrant|equity|debt)\s+(investments?|securities)\s*-\s*(united states|europe|asia|united kingdom|canada|australia)\s*$', re.I),
    re.compile(r'^portfolio company\s+(warrant|equity|debt)\s+(investments?|securities)\s*-\s*(united states|europe|asia|united kingdom|canada|australia)\s+[A-Z][a-z]+(\s+[A-Z&][a-z]*)*$', re.I),
    # "[Industry], [Industry]" bare comma-separated industry combos
    re.compile(r'^(hotel|gaming|leisure|restaurant|banking|finance|real estate|manufacturing|capital equipment|chemicals|plastics|rubber|diversified investment vehicles)[,\s]+(gaming|leisure|restaurant|capital equipment|plastics|rubber|banking|finance|real estate|manufacturing)\b', re.I),
]

# ── JV_SUBSIDIARY patterns ──────────────────────────────────────────

JV_PATTERNS = [
    re.compile(r'\bjv\b', re.I),
    re.compile(r'\bjoint\s+venture\b', re.I),
    re.compile(r'\bco-invest(ment)?\b', re.I),
    re.compile(r'\bco invest(ment)?\b', re.I),
    re.compile(r'\bfunding (vehicle|entity)\b', re.I),
    re.compile(r'\bsenior loan (fund|program)\b', re.I),
    re.compile(r'\bwarehouse\b', re.I),
    re.compile(r'\bcredit (facility|opportunities)\b.*\b(llc|lp|fund)\b', re.I),
    re.compile(r'\b(note issuer|structured note issuer)\b', re.I),
    re.compile(r'\bholding vehicle\b', re.I),
    re.compile(r'\bsfr dev jv\b', re.I),
    re.compile(r'\bemerald jv\b', re.I),
    re.compile(r'\bverdelite jv\b', re.I),
    re.compile(r'\bscf investor\b', re.I),
]

# Additional JV patterns - PE fund vehicles (Partners Group style)
PE_FUND_PATTERNS = [
    # "TRIDENT VII, L.P." - PE fund name + roman numeral + LP
    re.compile(r'^[A-Z][\w\s]+(I{1,3}V?|V|VI{0,3}|IX|X{0,3})\s*[\(,]?\s*(L\.?P\.?|S\.?C\.?A\.?|SCSp|FCPI|GmbH)', re.I),
    # "KKR [Name] Co-Invest" pattern
    re.compile(r'\b(kkr|blackstone|apollo|carlyle|tpg|bain|ares|cerberus|warburg|advent|permira|eqt|hg|capvis|kohlberg|green equity|astorg|ohcp|stonepeak|vepf|slp)\b.*\b(co-invest|l\.?p\.?|fund)\b', re.I),
    # SPV patterns
    re.compile(r'\bspv\b', re.I),
    # Blocker/purchaser vehicles
    re.compile(r'\bblocker\b.*\b(l\.?p\.?|llc)\b', re.I),
    # Feeder vehicles
    re.compile(r'\bfeeder\b.*\b(l\.?p\.?|llc)\b', re.I),
    # Program LLC patterns
    re.compile(r'\b(lending|loan|credit)\s+program\b', re.I),
    # "[Name] Holdings LLC" without clear operating company signals
    re.compile(r'^(bcred|blue owl|owl rock)\b.*\b(holdings|opportunities)\b', re.I),
]

# ── GICS from embedded industry hints ──────────────────────────────

# Goldman Sachs hierarchy: "Software Acme Corp" -> industry prefix
GS_INDUSTRY_MAP = {
    "software": "Application Software",
    "internet": "Interactive Media & Services",
    "technology": "IT Consulting & Other Services",
    "healthcare": "Health Care Services",
    "health care": "Health Care Services",
    "biotechnology": "Biotechnology",
    "pharmaceuticals": "Pharmaceuticals",
    "financial services": "Diversified Financial Services",
    "insurance": "Insurance Brokers",
    "aerospace & defense": "Aerospace & Defense",
    "media": "Movies & Entertainment",
    "entertainment": "Movies & Entertainment",
    "chemicals": "Specialty Chemicals",
    "consumer services": "Specialized Consumer Services",
    "education": "Education Services",
    "food & beverage": "Packaged Foods & Meats",
    "construction & engineering": "Construction & Engineering",
    "building products": "Building Products",
    "environmental services": "Environmental & Facilities Services",
    "real estate": "Real Estate Services",
    "transportation": "Cargo Ground Transportation",
    "energy": "Oil & Gas Exploration & Production",
    "telecommunications": "Integrated Telecommunication Services",
    "automotive": "Automobile Parts & Equipment",
    "packaging": "Paper & Plastic Packaging Products & Materials",
    "metals & mining": "Diversified Metals & Mining",
    "utilities": "Electric Utilities",
    "restaurants": "Restaurants",
    "retail": "Broadline Retail",
    "electronics": "Electronic Equipment & Instruments",
    "semiconductors": "Semiconductors",
    "industrial": "Industrial Conglomerates",
    "machinery": "Industrial Machinery & Supplies & Components",
    "wholesale": "Distributors",
    "leisure": "Leisure Products",
    "textiles": "Textiles",
    "hotels": "Hotels, Resorts & Cruise Lines",
    "gaming": "Casinos & Gaming",
    "advertising": "Advertising",
    "publishing": "Publishing",
    "broadcasting": "Broadcasting",
    # Additional GS prefixes found in the data
    "it services": "IT Consulting & Other Services",
    "specialty retail": "Specialty Stores",
    "diversified consumer service": "Specialized Consumer Services",
    "diversified consumer services": "Specialized Consumer Services",
    "health care technology": "Health Care Technology",
    "health care equipment": "Health Care Equipment",
    "capital goods": "Industrial Machinery & Supplies & Components",
    "commercial services": "Diversified Support Services",
    "commercial & professional services": "Research & Consulting Services",
    "professional services": "Research & Consulting Services",
    "consumer durables & apparel": "Apparel, Accessories & Luxury Goods",
    "food & staples retailing": "Food Retail",
    "household & personal products": "Household Products",
    "materials": "Specialty Chemicals",
    "diversified financials": "Diversified Financial Services",
    "retailing": "Specialty Stores",
}

# ── Crescent Capital / TCW / similar identifier industry extraction ──
# Pattern: "Investments [Country] Debt Investments [GICS Industry] [Company]"
IDENTIFIER_INDUSTRY_MAP = {
    "Health Care Equipment & Services": "Health Care Equipment",
    "Healthcare Technology": "Health Care Technology",
    "Software & Services": "Application Software",
    "Commercial & Professional Services": "Research & Consulting Services",
    "Consumer Services": "Specialized Consumer Services",
    "Consumer Durables & Apparel": "Apparel, Accessories & Luxury Goods",
    "Diversified Financials": "Diversified Financial Services",
    "Capital Goods": "Industrial Machinery & Supplies & Components",
    "Insurance": "Insurance Brokers",
    "Energy": "Oil & Gas Equipment & Services",
    "Pharmaceuticals, Biotechnology & Life Sciences": "Pharmaceuticals",
    "Internet & Direct Marketing Retail": "Broadline Retail",
    "Transportation": "Cargo Ground Transportation",
    "Materials": "Specialty Chemicals",
    "Food, Beverage & Tobacco": "Packaged Foods & Meats",
    "Media & Entertainment": "Movies & Entertainment",
    "Automobiles & Components": "Automobile Parts & Equipment",
    "Retailing": "Specialty Stores",
    "Telecommunication Services": "Integrated Telecommunication Services",
    "Utilities": "Electric Utilities",
    "Real Estate": "Real Estate Services",
    "Semiconductors & Semiconductor Equipment": "Semiconductors",
    "Technology Hardware & Equipment": "Technology Hardware, Storage & Peripherals",
    "Application Software": "Application Software",
    "Household Durables": "Housewares & Specialties",
}

# Trinity Capital / Horizon identifier patterns
# "Portfolio Company Debt Securities- United States [Industry] [Company]"
TRINITY_INDUSTRY_MAP = {
    "Finance and Insurance": "Diversified Financial Services",
    "Green Technology": "Renewable Electricity",
    "Space Technology": "Aerospace & Defense",
    "Real Estate Technology": "Real Estate Services",
    "Transportation Technology": "Cargo Ground Transportation",
    "Food and Agriculture Technologies": "Agricultural Products & Services",
    "Marketing, Media, and Entertainment": "Advertising",
    "SaaS": "Application Software",
    "Healthcare": "Health Care Services",
    "Healthcare Technology": "Health Care Technology",
    "Medical Devices": "Health Care Equipment",
    "Biotechnology": "Biotechnology",
    "Connectivity": "Integrated Telecommunication Services",
    "Industrials": "Industrial Machinery & Supplies & Components",
    "Consumer Products & Services": "Specialized Consumer Services",
    "Supply Chain Technology": "Application Software",
    "Automation & Internet of Things": "Electronic Equipment & Instruments",
    "Enterprise Cloud": "Systems Software",
}


def _is_aggregate_header(name_norm: str, raw: str) -> tuple[bool, str]:
    """Check if entity is an aggregate header. Returns (is_agg, evidence)."""
    # Exact match
    if name_norm in AGG_EXACT:
        return True, "Exact match: known aggregate header label"

    # GICS sub-industry used as label
    if name_norm in GICS_AS_AGG_LABELS:
        return True, "Bare GICS sub-industry label used as aggregate header"

    # Pattern match
    for pat in AGG_PATTERNS:
        if pat.search(raw):
            return True, f"Pattern match: {pat.pattern[:60]}"

    # Very short generic terms
    if len(name_norm) <= 4 and name_norm in {"cash", "debt", "loan", "bond", "note", "fund"}:
        return True, "Very short generic term"

    return False, ""


def _is_jv_subsidiary(name_norm: str, raw: str) -> tuple[bool, str]:
    """Check if entity is a JV/subsidiary vehicle. Returns (is_jv, evidence)."""
    for pat in JV_PATTERNS:
        if pat.search(raw):
            return True, f"JV pattern: {pat.pattern[:60]}"

    for pat in PE_FUND_PATTERNS:
        if pat.search(raw):
            return True, f"PE fund/SPV pattern: {pat.pattern[:60]}"

    return False, ""


def _extract_gs_industry(raw: str) -> str | None:
    """Extract Goldman Sachs hierarchy industry prefix."""
    lower = raw.lower().strip()
    # Sort by length descending to match longer prefixes first
    for prefix in sorted(GS_INDUSTRY_MAP.keys(), key=len, reverse=True):
        if lower.startswith(prefix + " "):
            # Make sure there's actually a company name after the prefix
            remainder = raw[len(prefix):].strip()
            if len(remainder) > 3 and not remainder.lower().startswith("total"):
                return GS_INDUSTRY_MAP[prefix]
    return None


def _extract_identifier_industry(sample_identifier: str) -> str | None:
    """Extract GICS from embedded industry in sample_identifier."""
    if not sample_identifier:
        return None

    # Crescent Capital pattern: "Investments [Country] Debt Investments [Industry] [Company]"
    m = re.search(
        r'(?:Debt|Equity) Investments\s+([A-Z][A-Za-z\s&,]+?)(?:\s+(?:Investment\s+Type|[A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,2}\s+(?:Investment|Unitranche|Senior|First|Second|Term|Revolver|Common|Preferred)))',
        sample_identifier
    )
    if m:
        industry = m.group(1).strip()
        # Remove trailing company name fragments
        for key in sorted(IDENTIFIER_INDUSTRY_MAP.keys(), key=len, reverse=True):
            if industry == key or industry.startswith(key):
                return IDENTIFIER_INDUSTRY_MAP[key]

    # Trinity Capital pattern: "Portfolio Company Debt Securities- United States [Industry] [Company]"
    m = re.search(
        r'Portfolio Company (?:Debt|Equity|Warrant) (?:Securities|Investments)-\s*(?:United States|United Sates|Europe|Asia|United Kingdom|Canada|Australia)\s+([A-Za-z\s&,]+?)(?:\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\s*(?:,|\s+Inc|\s+LLC|\s+Corp|\s+Ltd|$))',
        sample_identifier
    )
    if m:
        industry = m.group(1).strip()
        if industry in TRINITY_INDUSTRY_MAP:
            return TRINITY_INDUSTRY_MAP[industry]

    # Goldman Sachs pattern in identifier:
    # "Investment 1st Lien/Senior Secured Debt - NNN% [Company] Industry [Industry]"
    m = re.search(r'Industry\s+([A-Z][A-Za-z\s&]+?)(?:\s+Interest|\s+Reference|\s+Maturity|\s*$)',
                  sample_identifier)
    if m:
        industry_label = m.group(1).strip().lower()
        for prefix in sorted(GS_INDUSTRY_MAP.keys(), key=len, reverse=True):
            if industry_label == prefix or industry_label.startswith(prefix):
                return GS_INDUSTRY_MAP[prefix]

    return None


def _triage_entity(row: dict) -> dict:
    """Triage a single entity. Returns verdict dict."""
    raw = str(row.get("issuer_name_raw", ""))
    name_norm = str(row.get("name_norm", ""))
    sample_identifier = str(row.get("sample_identifier", ""))

    # 1. Check aggregate header
    is_agg, evidence = _is_aggregate_header(name_norm, raw)
    if is_agg:
        return {
            "verdict": "AGGREGATE_HEADER",
            "confidence": "high",
            "evidence": evidence,
            "gics": None,
        }

    # 2. Check JV/subsidiary
    is_jv, evidence = _is_jv_subsidiary(name_norm, raw)
    if is_jv:
        return {
            "verdict": "JV_SUBSIDIARY",
            "confidence": "high",
            "evidence": evidence,
            "gics": None,
        }

    # 3. Check for GS industry prefix -> can classify directly
    gs_gics = _extract_gs_industry(raw)
    if gs_gics:
        return {
            "verdict": "GICS",
            "confidence": "medium",
            "evidence": f"Goldman Sachs hierarchy prefix -> {gs_gics}",
            "gics": gs_gics,
        }

    # 4. Check for embedded industry in sample_identifier
    id_gics = _extract_identifier_industry(sample_identifier)
    if id_gics:
        return {
            "verdict": "GICS",
            "confidence": "medium",
            "evidence": f"Embedded industry in identifier -> {id_gics}",
            "gics": id_gics,
        }

    # 5. Needs web search
    return {
        "verdict": "NEEDS_SEARCH",
        "confidence": None,
        "evidence": None,
        "gics": None,
    }


def _load_gics_cache() -> pd.DataFrame:
    """Load existing GICS cache."""
    if COMPANY_GICS_CACHE_FILE.exists():
        return pd.read_csv(COMPANY_GICS_CACHE_FILE, dtype=str)
    return pd.DataFrame(columns=[
        "company_name_norm", "gics_sub_industry", "confidence", "source", "timestamp"
    ])


def _load_flags() -> pd.DataFrame:
    """Load existing aggregate header flags."""
    columns = ["name_norm", "issuer_name_raw", "verdict", "confidence", "evidence",
               "total_fv", "n_positions", "reviewed_by", "reviewed_at", "batch_id"]
    if AGGREGATE_HEADER_FLAGS_FILE.exists():
        return pd.read_csv(AGGREGATE_HEADER_FLAGS_FILE, dtype=str)
    return pd.DataFrame(columns=columns)


def _save_gics_cache(cache: pd.DataFrame) -> None:
    """Save GICS cache."""
    cache.to_csv(COMPANY_GICS_CACHE_FILE, index=False)


def _save_flags(flags: pd.DataFrame) -> None:
    """Save aggregate header flags."""
    flags.to_csv(AGGREGATE_HEADER_FLAGS_FILE, index=False)


def _save_claims(claims: dict) -> None:
    """Save claims file."""
    GICS_SKILL_CLAIMS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(GICS_SKILL_CLAIMS_FILE, "w", encoding="utf-8") as f:
        json.dump(claims, f, indent=2)


def _load_claims() -> dict:
    """Load claims file."""
    if GICS_SKILL_CLAIMS_FILE.exists():
        with open(GICS_SKILL_CLAIMS_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {}


def process_batch(batch_num: int, cache: pd.DataFrame, flags: pd.DataFrame,
                  needs_search_file) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """Process a single batch. Returns updated (cache, flags, stats)."""
    batch_id = f"{batch_num:03d}"
    batch_path = GICS_SKILL_BATCHES_DIR / f"batch_{batch_id}.csv"

    if not batch_path.exists():
        logger.warning("Batch %s not found", batch_id)
        return cache, flags, {"status": "missing"}

    batch = pd.read_csv(batch_path, dtype=str)
    now = datetime.now(timezone.utc).isoformat()

    # Already resolved names
    cache_names = set(cache["company_name_norm"].dropna().values) if len(cache) > 0 else set()
    flags_names = set(flags["name_norm"].dropna().values) if len(flags) > 0 else set()

    new_gics = []
    new_flags = []
    stats = {"n_gics": 0, "n_aggregate": 0, "n_jv": 0, "n_unresolvable": 0, "n_needs_search": 0}

    for _, row in batch.iterrows():
        name_norm = str(row.get("name_norm", ""))
        if not name_norm or name_norm in cache_names or name_norm in flags_names:
            continue

        result = _triage_entity(row)

        if result["verdict"] == "GICS":
            new_gics.append({
                "company_name_norm": name_norm,
                "gics_sub_industry": result["gics"],
                "confidence": result["confidence"],
                "source": "cc_skill",
                "timestamp": now,
            })
            cache_names.add(name_norm)
            stats["n_gics"] += 1

        elif result["verdict"] == "AGGREGATE_HEADER":
            new_flags.append({
                "name_norm": name_norm,
                "issuer_name_raw": str(row.get("issuer_name_raw", "")),
                "verdict": "AGGREGATE_HEADER",
                "confidence": result["confidence"],
                "evidence": result["evidence"],
                "total_fv": str(row.get("total_fv", "")),
                "n_positions": str(row.get("n_positions", "")),
                "reviewed_by": "cc_skill",
                "reviewed_at": now,
                "batch_id": batch_id,
            })
            flags_names.add(name_norm)
            stats["n_aggregate"] += 1

        elif result["verdict"] == "JV_SUBSIDIARY":
            new_flags.append({
                "name_norm": name_norm,
                "issuer_name_raw": str(row.get("issuer_name_raw", "")),
                "verdict": "JV_SUBSIDIARY",
                "confidence": result["confidence"],
                "evidence": result["evidence"],
                "total_fv": str(row.get("total_fv", "")),
                "n_positions": str(row.get("n_positions", "")),
                "reviewed_by": "cc_skill",
                "reviewed_at": now,
                "batch_id": batch_id,
            })
            flags_names.add(name_norm)
            stats["n_jv"] += 1

        elif result["verdict"] == "NEEDS_SEARCH":
            # Write to needs_search file for web search pass
            needs_search_file.writerow({
                "batch_id": batch_id,
                "entity_id": str(row.get("entity_id", "")),
                "issuer_name_raw": str(row.get("issuer_name_raw", "")),
                "name_norm": name_norm,
                "search_name": str(row.get("search_name", "")),
                "total_fv": str(row.get("total_fv", "")),
                "n_positions": str(row.get("n_positions", "")),
                "n_funds": str(row.get("n_funds", "")),
                "typical_class": str(row.get("typical_class", "")),
                "sample_fund": str(row.get("sample_fund", "")),
                "sample_identifier": str(row.get("sample_identifier", "")),
            })
            stats["n_needs_search"] += 1

    # Merge new results into cache and flags
    if new_gics:
        new_gics_df = pd.DataFrame(new_gics)
        cache = pd.concat([cache, new_gics_df], ignore_index=True)

    if new_flags:
        new_flags_df = pd.DataFrame(new_flags)
        flags = pd.concat([flags, new_flags_df], ignore_index=True)

    stats["status"] = "done"
    stats["completed_at"] = now
    return cache, flags, stats


def run(start: int = 1, end: int = 780) -> None:
    """Process batches from start to end."""
    t0 = time.time()
    logger.info("Processing batches %03d through %03d", start, end)

    cache = _load_gics_cache()
    flags = _load_flags()
    claims = _load_claims()

    needs_search_path = PROJECT_ROOT / "data" / "output" / "gics_needs_search.csv"
    needs_search_cols = [
        "batch_id", "entity_id", "issuer_name_raw", "name_norm", "search_name",
        "total_fv", "n_positions", "n_funds", "typical_class", "sample_fund",
        "sample_identifier",
    ]

    with open(needs_search_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=needs_search_cols)
        writer.writeheader()

        total_stats = {"n_gics": 0, "n_aggregate": 0, "n_jv": 0,
                       "n_unresolvable": 0, "n_needs_search": 0}

        for batch_num in range(start, end + 1):
            cache, flags, stats = process_batch(batch_num, cache, flags, writer)

            if stats.get("status") == "done":
                for k in total_stats:
                    total_stats[k] += stats.get(k, 0)
                claims[f"{batch_num:03d}"] = {
                    "status": "triage_done",
                    "completed_at": stats["completed_at"],
                    "n_gics": stats["n_gics"],
                    "n_aggregate": stats["n_aggregate"],
                    "n_jv": stats["n_jv"],
                    "n_needs_search": stats["n_needs_search"],
                }

            # Save periodically (every 50 batches)
            if batch_num % 50 == 0 or batch_num == end:
                _save_gics_cache(cache)
                _save_flags(flags)
                _save_claims(claims)
                elapsed = time.time() - t0
                logger.info(
                    "Batch %03d done (%.0fs). Running totals: "
                    "%d GICS, %d AGG, %d JV, %d need_search",
                    batch_num, elapsed,
                    total_stats["n_gics"], total_stats["n_aggregate"],
                    total_stats["n_jv"], total_stats["n_needs_search"],
                )

    # Final save
    _save_gics_cache(cache)
    _save_flags(flags)
    _save_claims(claims)

    elapsed = time.time() - t0
    logger.info(
        "Triage complete in %.1fs. GICS=%d, AGGREGATE=%d, JV=%d, NEEDS_SEARCH=%d",
        elapsed,
        total_stats["n_gics"], total_stats["n_aggregate"],
        total_stats["n_jv"], total_stats["n_needs_search"],
    )
    logger.info("Entities needing web search saved to %s", needs_search_path)


def show_stats() -> None:
    """Show current processing progress."""
    claims = _load_claims()
    if not claims:
        logger.info("No batches processed yet")
        return

    done = sum(1 for v in claims.values() if v.get("status") in ("done", "triage_done"))
    total_gics = sum(v.get("n_gics", 0) for v in claims.values())
    total_agg = sum(v.get("n_aggregate", 0) for v in claims.values())
    total_jv = sum(v.get("n_jv", 0) for v in claims.values())
    total_search = sum(v.get("n_needs_search", 0) for v in claims.values())

    logger.info("Batches processed: %d / 780", done)
    logger.info("  GICS classified: %d", total_gics)
    logger.info("  AGGREGATE_HEADER: %d", total_agg)
    logger.info("  JV_SUBSIDIARY: %d", total_jv)
    logger.info("  Needs web search: %d", total_search)

    # Check needs_search file
    ns_path = PROJECT_ROOT / "data" / "output" / "gics_needs_search.csv"
    if ns_path.exists():
        df = pd.read_csv(ns_path, dtype=str)
        total_fv = df["total_fv"].astype(float).sum()
        logger.info("  Needs search file: %d entities, $%.1fB FV", len(df), total_fv / 1e9)


def main():
    parser = argparse.ArgumentParser(description="Process GICS skill batches (triage pass)")
    parser.add_argument("--start", type=int, default=1, help="Start batch number")
    parser.add_argument("--end", type=int, default=780, help="End batch number")
    parser.add_argument("--stats", action="store_true", help="Show progress stats")
    args = parser.parse_args()

    if args.stats:
        show_stats()
    else:
        run(start=args.start, end=args.end)


if __name__ == "__main__":
    main()
