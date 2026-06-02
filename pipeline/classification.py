"""Classification helpers for unified private markets holdings."""

from __future__ import annotations

import re
from typing import Optional

import pandas as pd


_INDUSTRY_LABELS = {
    # Single-word labels
    "insurance", "chemicals", "media", "software", "pharmaceuticals",
    "machinery", "entertainment", "biotechnology", "automotive", "wholesale",
    "retail", "telecommunications", "distributors", "education", "banks",
    "healthcare", "technology", "energy", "transportation",
    "aerospace", "construction", "agriculture", "mining", "utilities",
    "textiles", "packaging", "plastics", "electronics", "cannabis",
    "restaurants", "gaming", "containers", "beverage", "building",
    "commodities",
    # Multi-word GICS sector/industry labels
    "aerospace & defense", "air freight & logistics", "auto components",
    "building products", "capital markets", "commercial services & supplies",
    "communications equipment", "commodity chemicals",
    "construction & engineering", "construction materials",
    "consumer finance", "consumer goods", "consumer services",
    "containers & packaging", "diversified consumer services",
    "diversified financial services", "diversified telecommunication services",
    "electric utilities", "electrical equipment",
    "electronic equipment, instruments & components",
    "energy equipment & services", "food & staples retailing", "food products",
    "gas utilities", "health care equipment & supplies",
    "health care providers & services", "health care technology",
    "hotels, restaurants & leisure", "household durables", "household products",
    "independent power and renewable electricity producers",
    "industrial conglomerates", "interactive media & services",
    "internet & direct marketing retail", "internet software & services",
    "it services", "leisure products", "life sciences tools & services",
    "media: advertising, printing & publishing",
    "media: broadcasting & subscription", "media: diversified & production",
    "metals & mining", "multi-utilities", "oil, gas & consumable fuels",
    "paper & forest products", "personal products",
    "professional services", "real estate",
    "real estate management & development", "road & rail",
    "semiconductors & semiconductor equipment",
    "specialty retail", "technology hardware, storage & peripherals",
    "textiles, apparel & luxury goods", "thrifts & mortgage finance",
    "trading companies & distributors", "transportation infrastructure",
    "water utilities", "wireless telecommunication services",
    # BDC-specific industry labels
    "consumer goods: durable", "consumer goods: non-durable",
    "energy: oil & gas", "energy: electricity",
    "services: business", "services: consumer",
    "transportation: cargo", "transportation: consumer",
    "utilities: electric", "utilities: oil & gas", "utilities: water",
    "banking, finance, insurance & real estate",
    "business services", "distribution",
    "environmental services", "food & beverage", "high tech industries",
    "hotel, gaming & leisure",
    # Geography labels
    "canada", "europe", "australia", "asia",
    "united states", "united kingdom",
}

# Post-extraction bad issuer name filter (catches extraction artifacts where
# dimension-path positions produce bare category labels as issuer_name).
_BAD_ISSUER_NAMES_EXACT = {
    "investments", "debt investments", "equity investments",
    "equity securities", "debt securities", "short-term investments",
    "cash equivalents", "cash", "investment",
    "non-controlled", "non-affiliated",
    "controlled investments", "affiliated investments",
    "non-controlled/non-affiliated investments",
    "non-control/non-affiliate investments",
    "non-control investments",
    "non-affiliate investments",
    "control investments",
    "affiliate investments",
    "first lien debt", "second lien debt",
    "subordinated debt", "mezzanine debt",
    "senior secured loans", "senior secured notes",
    # Goldman Sachs 4-level hierarchy category headers (safety net)
    "investment debt investments",
    "investment 1st lien/senior secured debt",
    "investment 2nd lien/senior secured debt",
    "investment equity securities",
    "investment unsecured debt",
}

_BAD_ISSUER_PREFIXES = [
    "non-controlled/", "non-controlled-",
    "non-controlled, non-affiliated",
    "non-affiliated/",
    "investments non-controlled",
    "investments non-controlled/",
    "investments, investments",
]

# Affiliation prefixes/suffixes in dash-delimited identifiers (PhenixFIN-style)
# e.g. "Non-Controlled/Non-Affiliated Investments - Acme Corp - Term Loan"
# Also handles inverted format used by PennantPark et al.:
# "Investments in Non-Controlled, Non-Affiliated Portfolio Companies - Acme Corp"
# DuckDB regexp_replace patterns (case-insensitive via (?i))

_BAD_ISSUER_ENTITY_SIGNALS = [
    "inc.", "inc,", "llc", "corp.", "corp,", "holdings", "holding",
    "ltd.", "ltd,", "l.p.", "gmbh", "co.", "plc", "company",
]

# N-PORT asset_cat -> unified asset_category
_NPORT_ASSET_MAP = {
    "LON": "LOAN",
    "DBT": "DEBT",
    "EC": "EQUITY_COMMON",
    "EP": "EQUITY_PREFERRED",
    "RE": "EQUITY_COMMON",      # Real estate equity (direct property holdings)
    "ABS-CBDO": "DEBT",         # CLO debt tranches (structured credit)
}

# N-PORT issuer_type -> unified issuer_category
_NPORT_ISSUER_MAP = {
    "CORP": "CORPORATE",
    "COR": "CORPORATE",
    "PF": "FUND",
    "RF": "FUND",
    "MUN": "GOVERNMENT",
    "UST": "GOVERNMENT",
    "USGA": "GOVERNMENT",
    "NUSS": "OTHER",  # name-gated: only GOVERNMENT if name has govt keyword (see CTE 4)
}

# BDC keyword -> asset_category (priority order matters)
# NOTE: "fund" is handled separately via _FUND_WORD_RE to avoid matching "funded"
_BDC_FUND_KEYWORDS = [
    "lp interest", "limited partner",
    "co-invest", "co-investment", "limited partnership interest",
]

_BDC_LOAN_KEYWORDS = [
    "first lien", "second lien", "term loan", "term note",
    "promissory note", "secured note", "mezzanine", "unitranche",
    "subordinated", "revolving", "revolver", "credit facility", "delayed draw",
    "term debt", "note at",
    "senior secured", "secured debt", "unsecured note", "bridge loan",
    "line of credit", "senior note", "junior note", "convertible note",
    "credit agreement", "loan agreement", "note purchase", "one stop",
    "asset-based", "equipment financing",
]

_BDC_EQUITY_KEYWORDS = [
    "shares", "common stock", "warrant",
    "membership interest", "units", "common",
    "equity interest", "class a units", "class b units", "ordinary shares",
]

# Regex for series A-F matching
_SERIES_RE = re.compile(r"\bseries\s+[a-f]\b", re.IGNORECASE)

# Regex for "fund" as a standalone word (must not match "funded"/"unfunded")
_FUND_WORD_RE = re.compile(r"\bfunds?\b", re.IGNORECASE)

# Money market fund patterns (not private markets -- filtered out)
_MONEY_MARKET_KEYWORDS = [
    "money market", "government obligations fund", "treasury obligations fund",
    "liquidity fund", "financial square",
]

# Index classification fund-name signals
_CREDIT_FUND_SIGNALS = [
    "credit", "lending", "loan", "debt", "income", "clo",
    "senior", "direct lending", "floating rate", "yield",
    "distressed", "mezzanine", "high yield", "fixed income",
    "leveraged", "structured credit", "private credit",
    "asset management",
]
_PE_FUND_SIGNALS = [
    "equity", "buyout", "growth", "venture", "private equity",
    "capital partners", "co-invest", "coinvest", "aggregator",
    "secondaries", "infrastructure", "real assets", "opportunistic",
    "lp interest", "lp interests", "partnership interest",
]

# N-PORT fund-like issuer name detection: CORP+OTHER holdings with these
# patterns are likely PE/VC fund interests, not operating companies.
_NPORT_FUND_NAME_KEYWORDS = [
    "capital partners", "buyout", "ventures", "growth equity",
    "secondaries",
]

# N-PORT credit fund name detection: EC+CORPORATE holdings with these
# keywords in issuer_name are likely BDC/credit fund interests, not operating cos.
_NPORT_CREDIT_FUND_NAME_KEYWORDS = [
    "bdc", "private credit", "senior loan", "lending fund",
    "credit fund", "credit corp", "direct lend", "debt fund",
]

# NUSS name-gated government detection: only map NUSS to GOVERNMENT when the
# issuer name contains an explicit government keyword.  Most NUSS-tagged
# positions are corporate (filer mis-tagged).
_NPORT_GOVT_NAME_RE = r"\bGOVT\b|\bGOVERNMENT\b|REPUBLIC OF|KINGDOM OF|SOVEREIGN"

# L.P. suffix fund co-keywords: an L.P. entity is only reclassified as FUND
# when the name also contains one of these fund-signaling keywords.
_NPORT_LP_FUND_CO_KEYWORDS = [
    "fund", "partners", "capital", "venture", "buyout",
    "growth equity", "credit", "investment",
]

# BDC fund vehicle / manager detection: equity-type positions in entities
# whose names match these signals should have issuer_category = FUND.
# "asset management" uses a position guard (must appear within first 30 chars)
# to avoid false positives from compound multi-entity names.
_BDC_FUND_VEHICLE_KEYWORDS = [
    "asset management",
    "senior loan program",
]
# Max character position for "asset management" match (guards against compound
# names like "Microstar Logistics LLC, Microstar Global Asset Management LLC")
_BDC_FUND_VEHICLE_POS_GUARD = 30

# Named co-invest / LP interest reclassification
# Operating company markers -- if the issuer name contains one of these,
# it's likely a direct position in an operating company, not a fund allocation.
_COMPANY_MARKERS = [
    "inc.", "inc,", "llc", "corp.", "corp,", "holdings",
    "group", "l.p.", " and ", " & ", "ltd.", "ltd,",
    "plc", "s.a.", "n.v.", "gmbh", "co.",
]
_COINVEST_KEYWORDS = ["co-invest", "co-investment", "coinvest"]
# Bare LP/partnership interest signals.  These indicate a single-asset
# co-invest SPV wrapping a direct operating-company position, BUT only when
# the issuer name also has a strict company marker AND does NOT contain "fund"
# (which would indicate a genuine fund vehicle like "Senior Loan Fund LLC").
_LP_INTEREST_KEYWORDS = [
    "lp interest", "lp interests",
    "limited partnership interest", "limited partnership interests",
    "general partnership interest", "general partnership interests",
    "membership interest",
]
# Strict subset of _COMPANY_MARKERS for LP interest reclassification.
# Excludes "l.p.", "group", " and ", " & " which commonly appear in fund names.
_STRICT_COMPANY_MARKERS = [
    "inc.", "inc,", "llc", "corp.", "corp,", "holdings",
    "ltd.", "ltd,", "plc", "s.a.", "n.v.", "gmbh", "co.",
]
_NAMED_LP_PATTERNS = [
    "lp interest | non-affiliated", "lp interest | affiliated",
    "lp interest |non-affiliated", "lp interest |affiliated",
    "llc interest | non-affiliated", "llc interest | affiliated",
]

# ---------------------------------------------------------------------------
# 2-axis classification keyword lists
# ---------------------------------------------------------------------------

# Real estate keywords (trigger for any issuer)
_REAL_ESTATE_KEYWORDS = [
    "real estate", "reit", "multifamily", "timberland",
    "prisa", "clarion", "cbre", "brookfield premier",
    "sentinel real", "morgan stanley prime", "core mob",
]

# Real estate keywords that only trigger when issuer_category='FUND'
# (avoids "National Property Solutions LLC" which is a corporate borrower)
_REAL_ESTATE_FUND_KEYWORDS = [
    "property", "prologis", "logistics fund", "logistics partner",
    "industrial trust", "industrial fund", "housing",
    "national property",
]

# Structured credit keywords
_STRUCTURED_CREDIT_KEYWORDS = [
    "clo ", " clo,", "clo/", "loan note issuer",
    "structured note", "subordinate note", "subordinated note", "sub note",
]

_BDC_VEHICLE_RE = re.compile(r"\bbdc\b", re.IGNORECASE)
_BDC_MANAGER_RE = re.compile(r"\b(advisory|management|manager)\b", re.IGNORECASE)

# Cash/liquid keywords (safe for any issuer)
_CASH_KEYWORDS = [
    "t-bill", "money market", "financial square", "gvmxx",
    "treasury fund", "treasury bill", "treasury note", "treasury bond",
    "u.s. treasury", "us treasury",
]
# Cash keywords that only trigger when issuer_category != CORPORATE
# (avoids "Apex Group Treasury LLC" false positives)
_CASH_CORPORATE_GUARD_KEYWORDS = [
    "treasury",
]

# Hedge fund keywords (negative signal -- NOT credit or PE)
_HEDGE_FUND_KEYWORDS = [
    "hedge", "macro", "long/short", "long short", "market neutral",
    "arbitrage", "event driven", "multi-strategy", "multi strategy",
    "absolute return",
]

# Roman numeral vintage fund pattern -- "Fund IV", "Fund XII", etc.
# Overwhelmingly PE vintage year fund series.
_VINTAGE_FUND_RE = re.compile(
    r'\bfund\s+(i{1,3}|iv|vi{0,3}|viii|ix|xi{0,3}|xiv|xv|x)\b',
    re.IGNORECASE,
)

# Pipe-format direction detection: if the last pipe-segment matches one of
# these tags, the format is "Company | Instrument | Affiliation" (Blue Owl,
# Golub, TriplePoint) rather than "Type | Industry | Company" (SLR).

_PIPE_INSTRUMENT_KEYWORDS = [
    "term loan", "revolving", "credit facility", "delayed draw",
    "first lien", "second lien", "senior secured", "unsecured debt",
    "subordinated", "mezzanine",
    "common stock", "preferred stock", "preferred class",
    "common units", "preferred units",
    "membership interest", "llc interest", "lp interest",
    "limited liability co", "limited partnership",
    "class a ", "class b ", "class c ",
    "warrant",
]

# Regex for legal entity suffixes at end of string (optionally followed by
# parenthetical, trailing digits, or a trailing number suffix like "LLC 1").
# Used to detect company names in pipe-delimited segments.
_LEGAL_SUFFIX_RE_SQL = (
    r"\b(inc\.?|llc\.?|corp\.?|ltd\.?|l\.?p\.?|gmbh|company|corporation"
    r"|incorporated)\s*(\(.*\))?\s*\d*\s*$"
)

# Regex to strip leading quantity/dollar amounts from instrument descriptions

def _sql_keyword_check(col: str, keywords: list[str]) -> str:
    """Generate SQL OR chain: contains(col, 'kw1') OR contains(col, 'kw2') ..."""
    clauses = [f"contains({col}, '{kw.replace(chr(39), chr(39)+chr(39))}')"
               for kw in keywords]
    return "(" + " OR ".join(clauses) + ")"


def _sql_is_bdc_vehicle_fund() -> str:
    """BDC-named fund vehicle, excluding adviser/manager economics."""
    return (
        "(issuer_category = 'FUND' "
        "AND regexp_matches(_combined_fund_text, '\\bbdc\\b') "
        "AND NOT regexp_matches(_combined_fund_text, '\\b(advisory|management|manager)\\b'))"
    )


def _is_bdc_vehicle_fund(issuer_category: str, combined_text: str) -> bool:
    """Return True for BDC vehicle rows that should be private credit funds."""
    return (
        issuer_category == "FUND"
        and bool(_BDC_VEHICLE_RE.search(combined_text))
        and not _BDC_MANAGER_RE.search(combined_text)
    )


def _sql_exact_match(col: str, values: set[str]) -> str:
    """Generate SQL IN clause: col IN ('v1', 'v2', ...)"""
    escaped = [v.replace("'", "''") for v in sorted(values)]
    return f"{col} IN ({', '.join(repr(v) for v in escaped)})"


def _sql_starts_with_any(col: str, prefixes: list[str]) -> str:
    """Generate SQL OR chain: starts_with(col, 'p1') OR starts_with(col, 'p2') ..."""
    clauses = [f"starts_with({col}, '{p.replace(chr(39), chr(39)+chr(39))}')"
               for p in prefixes]
    return "(" + " OR ".join(clauses) + ")"


def _sql_ends_with_any(col: str, suffixes: list[str]) -> str:
    """Generate SQL OR chain: suffix_of(col, 's1') OR suffix_of(col, 's2') ..."""
    clauses = [f"ends_with({col}, '{s.replace(chr(39), chr(39)+chr(39))}')"
               for s in suffixes]
    return "(" + " OR ".join(clauses) + ")"


def _sql_is_bad_issuer_name() -> str:
    """Generate SQL boolean expression for post-extraction bad issuer name filter.

    Catches extraction artifacts where dimension-path identifiers produce bare
    category labels (e.g., "Investments", "First Lien Debt") as issuer_name.

    Three rules:
    1. Exact match against _BAD_ISSUER_NAMES_EXACT
    2. No alphabetic characters (date-only "01/15/2025", percentage-only "1.00%")
    3. Starts with _BAD_ISSUER_PREFIXES AND lacks entity signals
    """
    # Strip trailing commas/semicolons (pipe-parser may leave them)
    col = "lower(TRIM(TRAILING ',' FROM TRIM(TRAILING ';' FROM trim(CAST(issuer_name AS VARCHAR)))))"
    parts = []
    # Rule 1: exact match
    parts.append(_sql_exact_match(col, _BAD_ISSUER_NAMES_EXACT))
    # Rule 2: no alphabetic characters (catches dates, percentages, numbers)
    parts.append(
        f"(LENGTH(trim(CAST(issuer_name AS VARCHAR))) >= 1"
        f" AND NOT regexp_matches(trim(CAST(issuer_name AS VARCHAR)), '[a-zA-Z]'))"
    )
    # Rule 3: bad prefix + no entity signals
    prefix_check = _sql_starts_with_any(col, _BAD_ISSUER_PREFIXES)
    entity_guards = " AND ".join(
        f"NOT contains({col}, '{s}')" for s in _BAD_ISSUER_ENTITY_SIGNALS
    )
    parts.append(f"({prefix_check} AND {entity_guards})")
    return " OR ".join(f"({p})" for p in parts)



def _sql_classify_bdc_asset() -> str:
    """Generate CASE WHEN for BDC asset classification.

    Mirrors the priority logic in _classify_bdc_asset():
    1. XBRL investment_type axis
    2. Keyword matching on instrument_description
    3. Keyword matching on full_identifier
    4. Financial field heuristic
    5. Fallback -> OTHER
    """
    lines = ["CASE"]

    # --- Priority 0: XBRL axis override ---
    # Fund keywords on axis
    axis_fund_kw = _sql_keyword_check("_lower_type", _BDC_FUND_KEYWORDS)
    axis_fund_re = "regexp_matches(_lower_type, '\\bfunds?\\b')"
    lines.append(f"  WHEN _lower_type != '' AND ({axis_fund_kw} OR {axis_fund_re}) THEN 'FUND'")
    # Loan keywords on axis
    axis_loan_kw = _sql_keyword_check("_lower_type", _BDC_LOAN_KEYWORDS)
    lines.append(f"  WHEN _lower_type != '' AND {axis_loan_kw} THEN 'LOAN'")
    # Equity keywords on axis
    lines.append("  WHEN _lower_type != '' AND (contains(_lower_type, 'equity') OR contains(_lower_type, 'stock') OR contains(_lower_type, 'shares') OR contains(_lower_type, 'warrant')) THEN 'EQUITY_COMMON'")

    # --- Priority 1-3 on instrument_description then full_identifier ---
    for col in ["_lower_instr", "_lower_full"]:
        # Loan (before fund to avoid "funded" false positives)
        loan_kw = _sql_keyword_check(col, _BDC_LOAN_KEYWORDS)
        lines.append(f"  WHEN {col} != '' AND {loan_kw} THEN 'LOAN'")
        # Fund keywords
        fund_kw = _sql_keyword_check(col, _BDC_FUND_KEYWORDS)
        fund_re = f"regexp_matches({col}, '\\bfunds?\\b')"
        lines.append(f"  WHEN {col} != '' AND ({fund_kw} OR {fund_re}) THEN 'FUND'")
        # Preferred (before common equity to avoid short-circuit)
        lines.append(f"  WHEN {col} != '' AND contains({col}, 'preferred') THEN 'EQUITY_PREFERRED'")
        # Equity keywords
        eq_kw = _sql_keyword_check(col, _BDC_EQUITY_KEYWORDS)
        series_re = f"regexp_matches({col}, '\\bseries\\s+[a-f]\\b')"
        lines.append(f"  WHEN {col} != '' AND ({eq_kw} OR {series_re}) THEN 'EQUITY_COMMON'")

    # --- Priority 4: Financial field heuristic ---
    lines.append("  WHEN _has_interest_rate THEN 'LOAN'")
    lines.append("  WHEN _has_basis_spread THEN 'LOAN'")
    lines.append("  WHEN _has_principal_amount THEN 'LOAN'")
    lines.append("  WHEN _has_shares THEN 'EQUITY_COMMON'")

    lines.append("  ELSE 'OTHER'")
    lines.append("END")
    return "\n".join(lines)


def _sql_classify_index() -> str:
    """Generate CASE WHEN for index classification.

    Mirrors _classify_index() logic including fund signal counting.
    Priority order:
    1. STRUCTURED_CREDIT (CLO keywords)
    2. CASH (GOVERNMENT or cash keywords -- before asset_category rules
       so that Treasury Bills / money market funds with populated
       principal_amount or shares_held are not misrouted to
       DIRECT_LENDING / COMMON_EQUITY by the financial-field heuristic)
    3. DIRECT_LENDING (LOAN/DEBT + CORPORATE)
    4. DIRECT_REAL_ESTATE (CORPORATE + nport_asset_cat=RE or RE keywords)
    5. PREFERRED_EQUITY (EQUITY_PREFERRED + CORPORATE)
    6. COMMON_EQUITY (EQUITY_COMMON + CORPORATE)
    7. REAL_ESTATE_FUND (FUND + RE keywords or nport_asset_cat=RE)
    8. PRIVATE_CREDIT_FUND (FUND + credit signals)
    9. PRIVATE_EQUITY_FUND (FUND + PE signals)
    10. Fund tiebreaker (credit vs PE count)
    11. HEDGE_FUND (FUND + explicit hedge keywords)
    12. PRIVATE_EQUITY_FUND (FUND + roman numeral vintage series)
    13. UNCLASSIFIED (FUND + no signal)
    14. UNCLASSIFIED (fallback)
    """
    # Build credit/PE signal checks on _combined_fund_text
    credit_checks = [f"contains(_combined_fund_text, '{s}')" for s in _CREDIT_FUND_SIGNALS]
    pe_checks = [f"contains(_combined_fund_text, '{s}')" for s in _PE_FUND_SIGNALS]
    has_credit = "(" + " OR ".join(credit_checks) + ")"
    has_pe = "(" + " OR ".join(pe_checks) + ")"

    # Count expressions for tiebreaker
    credit_count_parts = [f"CASE WHEN contains(_combined_fund_text, '{s}') THEN 1 ELSE 0 END"
                          for s in _CREDIT_FUND_SIGNALS]
    pe_count_parts = [f"CASE WHEN contains(_combined_fund_text, '{s}') THEN 1 ELSE 0 END"
                      for s in _PE_FUND_SIGNALS]
    credit_count = "(" + " + ".join(credit_count_parts) + ")"
    pe_count = "(" + " + ".join(pe_count_parts) + ")"

    # Real estate keyword checks
    re_kw = _sql_keyword_check("_combined_fund_text", _REAL_ESTATE_KEYWORDS)
    re_fund_kw = _sql_keyword_check("_combined_fund_text", _REAL_ESTATE_FUND_KEYWORDS)
    # Structured credit keyword checks
    sc_kw = _sql_keyword_check("_combined_fund_text", _STRUCTURED_CREDIT_KEYWORDS)
    bdc_vehicle_fund = _sql_is_bdc_vehicle_fund()
    # Cash keyword checks
    cash_kw = _sql_keyword_check("_combined_fund_text", _CASH_KEYWORDS)
    cash_guard_kw = _sql_keyword_check("_combined_fund_text", _CASH_CORPORATE_GUARD_KEYWORDS)
    # Hedge fund keyword checks
    hedge_kw = _sql_keyword_check("_combined_fund_text", _HEDGE_FUND_KEYWORDS)

    # nport_asset_cat structural signal for funds without keyword signal
    nac_re = "UPPER(TRIM(CAST(nport_asset_cat AS VARCHAR))) = 'RE'"
    nac_dbt = "UPPER(TRIM(CAST(nport_asset_cat AS VARCHAR))) IN ('DBT', 'LON')"
    nac_eq = "UPPER(TRIM(CAST(nport_asset_cat AS VARCHAR))) IN ('EC', 'EP')"

    return f"""CASE
  WHEN {sc_kw} THEN 'STRUCTURED_CREDIT'
  WHEN issuer_category = 'GOVERNMENT' OR {cash_kw} THEN 'CASH'
  WHEN issuer_category != 'CORPORATE' AND {cash_guard_kw} THEN 'CASH'
  WHEN asset_category IN ('LOAN', 'DEBT') AND issuer_category = 'CORPORATE' THEN 'DIRECT_LENDING'
  WHEN issuer_category = 'CORPORATE' AND ({nac_re} OR {re_kw} OR {re_fund_kw}) THEN 'DIRECT_REAL_ESTATE'
  WHEN asset_category = 'EQUITY_PREFERRED' AND issuer_category = 'CORPORATE' THEN 'PREFERRED_EQUITY'
  WHEN asset_category = 'EQUITY_COMMON' AND issuer_category = 'CORPORATE' THEN 'COMMON_EQUITY'
  WHEN issuer_category = 'FUND' AND ({re_kw} OR {re_fund_kw}) THEN 'REAL_ESTATE_FUND'
  WHEN issuer_category = 'FUND' AND {nac_re} THEN 'REAL_ESTATE_FUND'
  WHEN {bdc_vehicle_fund} THEN 'PRIVATE_CREDIT_FUND'
  WHEN issuer_category = 'FUND' AND {has_credit} AND NOT {has_pe} THEN 'PRIVATE_CREDIT_FUND'
  WHEN issuer_category = 'FUND' AND {has_pe} AND NOT {has_credit} THEN 'PRIVATE_EQUITY_FUND'
  WHEN issuer_category = 'FUND' AND {has_credit} AND {has_pe} AND {credit_count} >= {pe_count} THEN 'PRIVATE_CREDIT_FUND'
  WHEN issuer_category = 'FUND' AND {has_credit} AND {has_pe} AND {credit_count} < {pe_count} THEN 'PRIVATE_EQUITY_FUND'
  WHEN issuer_category = 'FUND' AND {hedge_kw} THEN 'HEDGE_FUND'
  WHEN issuer_category = 'FUND' AND {nac_dbt} THEN 'PRIVATE_CREDIT_FUND'
  WHEN issuer_category = 'FUND' AND {nac_eq} THEN 'PRIVATE_EQUITY_FUND'
  WHEN issuer_category = 'FUND' AND NOT {has_credit} AND NOT {has_pe} AND regexp_matches(_combined_fund_text, '\\bfund\\s+(i{{1,3}}|iv|vi{{0,3}}|viii|ix|xi{{0,3}}|xiv|xv|x)\\b') THEN 'PRIVATE_EQUITY_FUND'
  WHEN issuer_category = 'FUND' AND NOT {has_credit} AND NOT {has_pe} THEN 'UNCLASSIFIED'
  ELSE 'UNCLASSIFIED'
END"""


def _sql_is_named_coinvest() -> str:
    """Generate SQL boolean expression for named co-invest detection.

    Two paths:
    1. Co-invest path: any company marker + co-invest keyword or pipe LP pattern.
    2. Bare LP interest path: strict company marker + LP interest keyword
       + no "fund" word in issuer name.
    """
    marker_check = _sql_keyword_check("_lower_issuer", _COMPANY_MARKERS)
    coinvest_check = _sql_keyword_check("_combined_coinvest", _COINVEST_KEYWORDS)

    # Named LP patterns checked against full identifier
    lp_clauses = [f"contains(_lower_bdc_id, '{p}')" for p in _NAMED_LP_PATTERNS]
    lp_check = "(" + " OR ".join(lp_clauses) + ")"

    # Path 1: co-invest keywords (original logic)
    path1 = f"({marker_check} AND ({coinvest_check} OR {lp_check}))"

    # Path 2: bare LP interest with strict markers and no "fund" word
    strict_marker_check = _sql_keyword_check("_lower_issuer", _STRICT_COMPANY_MARKERS)
    lp_interest_check = _sql_keyword_check("_combined_coinvest", _LP_INTEREST_KEYWORDS)
    no_fund = "NOT regexp_matches(_lower_issuer, '\\bfunds?\\b')"
    path2 = f"({strict_marker_check} AND {no_fund} AND {lp_interest_check})"

    return f"(asset_category = 'FUND' AND ({path1} OR {path2}))"


def _sql_classify_exposure_type() -> str:
    """Generate CASE WHEN for exposure_type classification.

    Three values:
    - LIQUID: Government issuers or cash-like instruments
    - FUND: Fund vehicles (issuer_category='FUND' or nport PF/RF)
    - DIRECT: Everything else (direct positions in operating companies)
    """
    cash_kw = _sql_keyword_check("_combined_fund_text", _CASH_KEYWORDS)
    cash_guard_kw = _sql_keyword_check("_combined_fund_text", _CASH_CORPORATE_GUARD_KEYWORDS)
    return f"""CASE
  WHEN issuer_category = 'GOVERNMENT' THEN 'LIQUID'
  WHEN {cash_kw} THEN 'LIQUID'
  WHEN issuer_category != 'CORPORATE' AND {cash_guard_kw} THEN 'LIQUID'
  WHEN issuer_category = 'FUND' THEN 'FUND'
  ELSE 'DIRECT'
END"""


def _sql_classify_asset_class() -> str:
    """Generate CASE WHEN for asset_class classification.

    Priority order:
    1. CASH -- government + cash keywords
    2. REAL_ESTATE -- RE keywords (generic any issuer)
       + nport_asset_cat=RE (any issuer, including CORPORATE)
    3. STRUCTURED_CREDIT -- CLO keywords
    4. PRIVATE_CREDIT -- LOAN/DEBT+CORPORATE or credit fund signals
       + nport_asset_cat=DBT for funds without keyword signal
    5. PRIVATE_EQUITY -- EQUITY+CORPORATE or PE fund signals
       + nport_asset_cat=EC/EP for funds without keyword signal
    6. HEDGE_FUND -- fund with explicit hedge fund keywords
    7. OTHER -- fund with no signals, or general fallback
    """
    cash_kw = _sql_keyword_check("_combined_fund_text", _CASH_KEYWORDS)
    cash_guard_kw = _sql_keyword_check("_combined_fund_text", _CASH_CORPORATE_GUARD_KEYWORDS)
    re_kw = _sql_keyword_check("_combined_fund_text", _REAL_ESTATE_KEYWORDS)
    re_fund_kw = _sql_keyword_check("_combined_fund_text", _REAL_ESTATE_FUND_KEYWORDS)
    sc_kw = _sql_keyword_check("_combined_fund_text", _STRUCTURED_CREDIT_KEYWORDS)
    bdc_vehicle_fund = _sql_is_bdc_vehicle_fund()
    hedge_kw = _sql_keyword_check("_combined_fund_text", _HEDGE_FUND_KEYWORDS)

    # Credit/PE signal checks (reuse existing lists)
    credit_checks = [f"contains(_combined_fund_text, '{s}')" for s in _CREDIT_FUND_SIGNALS]
    pe_checks = [f"contains(_combined_fund_text, '{s}')" for s in _PE_FUND_SIGNALS]
    has_credit = "(" + " OR ".join(credit_checks) + ")"
    has_pe = "(" + " OR ".join(pe_checks) + ")"

    # nport_asset_cat structural signal for funds without keyword signal
    nac_re = "UPPER(TRIM(CAST(nport_asset_cat AS VARCHAR))) = 'RE'"
    nac_dbt = "UPPER(TRIM(CAST(nport_asset_cat AS VARCHAR))) IN ('DBT', 'LON')"
    nac_eq = "UPPER(TRIM(CAST(nport_asset_cat AS VARCHAR))) IN ('EC', 'EP')"

    return f"""CASE
  WHEN issuer_category = 'GOVERNMENT' OR {cash_kw} THEN 'CASH'
  WHEN issuer_category != 'CORPORATE' AND {cash_guard_kw} THEN 'CASH'
  WHEN {re_kw} THEN 'REAL_ESTATE'
  WHEN issuer_category = 'FUND' AND {re_fund_kw} THEN 'REAL_ESTATE'
  WHEN {nac_re} THEN 'REAL_ESTATE'
  WHEN {sc_kw} THEN 'STRUCTURED_CREDIT'
  WHEN asset_category IN ('LOAN', 'DEBT') AND issuer_category = 'CORPORATE' THEN 'PRIVATE_CREDIT'
  WHEN {bdc_vehicle_fund} THEN 'PRIVATE_CREDIT'
  WHEN issuer_category = 'FUND' AND {has_credit} THEN 'PRIVATE_CREDIT'
  WHEN issuer_category = 'FUND' AND {nac_dbt} THEN 'PRIVATE_CREDIT'
  WHEN asset_category IN ('EQUITY_COMMON', 'EQUITY_PREFERRED') AND issuer_category = 'CORPORATE' THEN 'PRIVATE_EQUITY'
  WHEN issuer_category = 'FUND' AND {has_pe} THEN 'PRIVATE_EQUITY'
  WHEN {hedge_kw} THEN 'HEDGE_FUND'
  WHEN issuer_category = 'FUND' AND {nac_eq} THEN 'PRIVATE_EQUITY'
  WHEN issuer_category = 'FUND' AND NOT {has_credit} AND NOT {has_pe} AND regexp_matches(_combined_fund_text, '\\bfund\\s+(i{{1,3}}|iv|vi{{0,3}}|viii|ix|xi{{0,3}}|xiv|xv|x)\\b') THEN 'PRIVATE_EQUITY'
  WHEN issuer_category = 'FUND' AND NOT {has_credit} AND NOT {has_pe} THEN 'OTHER'
  ELSE 'OTHER'
END"""


def _sql_normalize_name(col: str) -> str:
    """Generate SQL expression to normalize an issuer name column.

    Rules:
    1. Collapse repeated periods (.. or ...) to single .
    2. Collapse multiple whitespace to single space
    3. Strip trailing commas, semicolons, and whitespace (but NOT single trailing
       periods, which are abbreviations like Inc., Corp., Ltd.)
    4. Trim leading/trailing whitespace
    """
    return (
        f"TRIM(REGEXP_REPLACE("
        f"REGEXP_REPLACE("
        f"REGEXP_REPLACE({col}, '\\.{{2,}}', '.', 'g'), "
        f"'\\s+', ' ', 'g'), "
        f"'[,;\\s]+$', ''))"
    )


def _sql_money_market_check() -> str:
    """Generate SQL boolean for money market fund detection."""
    return _sql_keyword_check("_lower_bdc_id", _MONEY_MARKET_KEYWORDS)


def _sql_industry_label_in() -> str:
    """Generate SQL IN clause for all _INDUSTRY_LABELS (for industry-prefix detection)."""
    return _sql_exact_match("_issuer_lower", _INDUSTRY_LABELS)


# ---------------------------------------------------------------------------
# BDC identifier parsing
# ---------------------------------------------------------------------------

def _classify_bdc_asset(instrument_description: str,
                        investment_type: str = "",
                        full_identifier: str = "",
                        has_interest_rate: bool = False,
                        has_shares: bool = False,
                        has_basis_spread: bool = False,
                        has_principal_amount: bool = False) -> str:
    """Classify a BDC holding's asset category.

    Classification priority:
    1. XBRL investment_type axis (if populated)
    2. Keyword matching on instrument_description
    3. Keyword matching on full_identifier (for bare-name identifiers)
    4. Financial field heuristic (interest_rate/spread/principal -> LOAN, shares -> EQUITY)
    5. Fallback -> OTHER
    """
    # XBRL axis override
    if investment_type and isinstance(investment_type, str) and investment_type.strip():
        it_lower = investment_type.strip().lower()
        if any(kw in it_lower for kw in _BDC_FUND_KEYWORDS) or _FUND_WORD_RE.search(it_lower):
            return "FUND"
        if any(kw in it_lower for kw in _BDC_LOAN_KEYWORDS):
            return "LOAN"
        if any(kw in it_lower for kw in ["equity", "stock", "shares", "warrant"]):
            return "EQUITY_COMMON"
        # Fall through to keyword matching if axis doesn't match known patterns

    # Try keyword matching on instrument_description first, then full_identifier
    for text in [instrument_description, full_identifier]:
        if not text or not isinstance(text, str):
            continue

        lower = text.lower()

        # Priority 1: Loan/Debt (checked before Fund to avoid "Funded" false positives)
        for kw in _BDC_LOAN_KEYWORDS:
            if kw in lower:
                return "LOAN"

        # Priority 2: Fund (word-boundary regex for "fund" to not match "funded")
        for kw in _BDC_FUND_KEYWORDS:
            if kw in lower:
                return "FUND"
        if _FUND_WORD_RE.search(lower):
            return "FUND"

        # Priority 3: Equity (preferred before common to avoid short-circuit)
        if "preferred" in lower:
            return "EQUITY_PREFERRED"
        for kw in _BDC_EQUITY_KEYWORDS:
            if kw in lower:
                return "EQUITY_COMMON"
        if _SERIES_RE.search(lower):
            return "EQUITY_COMMON"

    # Financial field heuristic fallback
    if has_interest_rate:
        return "LOAN"
    if has_basis_spread:
        return "LOAN"
    if has_principal_amount:
        return "LOAN"
    if has_shares:
        return "EQUITY_COMMON"

    return "OTHER"


def _classify_nport_asset(asset_cat: str) -> str:
    """Map N-PORT asset_cat code to unified asset_category."""
    if not asset_cat or not isinstance(asset_cat, str):
        return "OTHER"
    code = asset_cat.strip().upper()
    return _NPORT_ASSET_MAP.get(code, "OTHER")


# ---------------------------------------------------------------------------
# Issuer classification
# ---------------------------------------------------------------------------

def _classify_bdc_issuer(asset_category: str, issuer_name: str = "") -> str:
    """Infer BDC issuer category from asset category and issuer name.

    BDC investees are overwhelmingly private operating companies.
    FUND assets map to FUND issuer category.  Additionally, equity-type
    positions in fund managers / lending vehicles (detected by name keywords)
    are reclassified as FUND.
    """
    if asset_category == "FUND":
        return "FUND"
    # Equity stakes in fund managers/vehicles
    if asset_category in ("EQUITY_COMMON", "EQUITY_PREFERRED", "OTHER"):
        if issuer_name and isinstance(issuer_name, str):
            name_lower = issuer_name.lower()
            for kw in _BDC_FUND_VEHICLE_KEYWORDS:
                pos = name_lower.find(kw)
                if pos < 0:
                    continue
                # "asset management" requires position guard
                if kw == "asset management" and pos >= _BDC_FUND_VEHICLE_POS_GUARD:
                    continue
                return "FUND"
    return "CORPORATE"


def _classify_nport_issuer(issuer_type: str) -> str:
    """Map N-PORT issuer_type code to unified issuer_category."""
    if not issuer_type or not isinstance(issuer_type, str):
        return "OTHER"
    code = issuer_type.strip().upper()
    return _NPORT_ISSUER_MAP.get(code, "OTHER")


# ---------------------------------------------------------------------------
# Index classification
# ---------------------------------------------------------------------------

def _classify_index(asset_category: str, issuer_category: str,
                    issuer_name: str, instrument_description: str,
                    nport_asset_cat: str = "") -> str:
    """Assign index classification.

    Priority order:
      1. STRUCTURED_CREDIT:   CLO keywords (before DIRECT_LENDING to catch CLO tranches)
      2. CASH:                GOVERNMENT or cash keywords (before asset_category rules
                              so Treasury Bills / money market funds with populated
                              principal_amount or shares_held are not misrouted)
      3. DIRECT_LENDING:      LOAN/DEBT + CORPORATE
      4. DIRECT_REAL_ESTATE:  CORPORATE + nport_asset_cat=RE or RE keywords
      5. PREFERRED_EQUITY:    EQUITY_PREFERRED + CORPORATE
      6. COMMON_EQUITY:       EQUITY_COMMON + CORPORATE
      7. REAL_ESTATE_FUND:    FUND + RE keywords or nport_asset_cat=RE
      8. PRIVATE_CREDIT_FUND: FUND + credit signals
      9. PRIVATE_EQUITY_FUND: FUND + PE signals
      10. HEDGE_FUND:          FUND + explicit hedge keywords (before nac fallback)
      11. PRIVATE_CREDIT_FUND: FUND + nport_asset_cat=DBT/LON
      12. PRIVATE_EQUITY_FUND: FUND + nport_asset_cat=EC/EP
      13. PRIVATE_EQUITY_FUND: FUND + roman numeral vintage series (Fund IV, etc.)
      14. UNCLASSIFIED:       FUND + no signal at all
      15. UNCLASSIFIED:       everything else
    """
    # Combine issuer name + instrument description for signal matching
    combined = ""
    if issuer_name and isinstance(issuer_name, str):
        combined += issuer_name.lower()
    if instrument_description and isinstance(instrument_description, str):
        combined += " " + instrument_description.lower()

    nac = (nport_asset_cat or "").strip().upper()

    # Structured credit (check first -- CLO tranches should not fall into DIRECT_LENDING)
    has_sc = any(kw in combined for kw in _STRUCTURED_CREDIT_KEYWORDS)
    if has_sc:
        return "STRUCTURED_CREDIT"

    # Cash (before asset_category rules so Treasury Bills / money market funds
    # with populated principal_amount or shares_held are not misrouted)
    has_cash = any(kw in combined for kw in _CASH_KEYWORDS)
    has_cash_guard = any(kw in combined for kw in _CASH_CORPORATE_GUARD_KEYWORDS)
    if issuer_category == "GOVERNMENT" or has_cash:
        return "CASH"
    if issuer_category != "CORPORATE" and has_cash_guard:
        return "CASH"

    if asset_category in ("LOAN", "DEBT") and issuer_category == "CORPORATE":
        return "DIRECT_LENDING"

    # Direct real estate (CORPORATE + nport_asset_cat=RE or RE keywords)
    has_re = any(kw in combined for kw in _REAL_ESTATE_KEYWORDS)
    has_re_fund = any(kw in combined for kw in _REAL_ESTATE_FUND_KEYWORDS)
    if issuer_category == "CORPORATE" and (nac == "RE" or has_re or has_re_fund):
        return "DIRECT_REAL_ESTATE"

    if asset_category == "EQUITY_PREFERRED" and issuer_category == "CORPORATE":
        return "PREFERRED_EQUITY"

    if asset_category == "EQUITY_COMMON" and issuer_category == "CORPORATE":
        return "COMMON_EQUITY"
    if issuer_category == "FUND" and (has_re or has_re_fund):
        return "REAL_ESTATE_FUND"
    if issuer_category == "FUND" and nac == "RE":
        return "REAL_ESTATE_FUND"

    if _is_bdc_vehicle_fund(issuer_category, combined):
        return "PRIVATE_CREDIT_FUND"

    if issuer_category == "FUND":
        has_credit = any(sig in combined for sig in _CREDIT_FUND_SIGNALS)
        has_pe = any(sig in combined for sig in _PE_FUND_SIGNALS)

        if has_credit and not has_pe:
            return "PRIVATE_CREDIT_FUND"
        if has_pe and not has_credit:
            return "PRIVATE_EQUITY_FUND"
        if has_credit and has_pe:
            credit_count = sum(1 for s in _CREDIT_FUND_SIGNALS if s in combined)
            pe_count = sum(1 for s in _PE_FUND_SIGNALS if s in combined)
            if credit_count >= pe_count:
                return "PRIVATE_CREDIT_FUND"
            return "PRIVATE_EQUITY_FUND"
        # Explicit hedge fund keywords (check before nac fallback)
        has_hedge = any(kw in combined for kw in _HEDGE_FUND_KEYWORDS)
        if has_hedge:
            return "HEDGE_FUND"
        # nport_asset_cat fallback
        if nac in ("DBT", "LON"):
            return "PRIVATE_CREDIT_FUND"
        if nac in ("EC", "EP"):
            return "PRIVATE_EQUITY_FUND"
        # Roman numeral vintage fund series (Fund IV, Fund XII, etc.) -> PE
        if _VINTAGE_FUND_RE.search(combined):
            return "PRIVATE_EQUITY_FUND"
        # No signal at all -> UNCLASSIFIED (not HEDGE_FUND)
        if not has_credit and not has_pe:
            return "UNCLASSIFIED"

    return "UNCLASSIFIED"


# ---------------------------------------------------------------------------
# Coupon type inference for BDC
# ---------------------------------------------------------------------------

def _infer_coupon_type(basis_spread, interest_rate) -> str:
    """Infer coupon type for BDC holdings.

    - basis_spread populated -> Floating
    - interest_rate populated but no spread -> Fixed
    - Neither -> blank
    """
    has_spread = pd.notna(basis_spread) and basis_spread != 0
    has_rate = pd.notna(interest_rate) and interest_rate != 0

    if has_spread:
        return "Floating"
    if has_rate:
        return "Fixed"
    return ""


def _normalize_rate(raw: Optional[float]) -> Optional[float]:
    """Normalize a raw BDC rate to percentage scale.

    BDC XBRL rates arrive in three bands:
      <= 0.50   -> decimal (multiply by 100)
      > 0.50 and < 50 -> already percentage (leave as-is)
      >= 50     -> basis points (divide by 100)
    """
    if raw is None:
        return None
    if raw <= 0.50:
        return raw * 100
    if raw >= 50:
        return raw / 100
    return raw  # already percentage


# ---------------------------------------------------------------------------
# Named co-invest / LP interest reclassification
# ---------------------------------------------------------------------------

def _is_named_coinvest(issuer_name: str, instrument_description: str,
                       full_identifier: str) -> bool:
    """Return True if this FUND holding is actually a named operating company.

    Two paths:
    1. **Co-invest path**: combined text has a co-invest keyword AND the
       issuer name has any company marker.  OR the full identifier matches
       a named LP pipe pattern AND the issuer name has any company marker.
    2. **Bare LP interest path**: combined text has an LP interest keyword
       AND the issuer name has a *strict* company marker (Inc., LLC, Corp.,
       Holdings -- excluding L.P., Group, & which appear in fund names)
       AND the issuer name does NOT contain the word "fund".

    Returns False for generic unnamed vehicles (e.g., "Co-investment" with
    no company name, or opaque LP funds like "Senior Loan Fund LLC").
    """
    if not issuer_name or not isinstance(issuer_name, str):
        return False

    issuer_lower = issuer_name.lower()
    has_company_marker = any(m in issuer_lower for m in _COMPANY_MARKERS)

    # Build combined text from all fields
    combined = issuer_lower
    if instrument_description and isinstance(instrument_description, str):
        combined += " " + instrument_description.lower()
    if full_identifier and isinstance(full_identifier, str):
        combined += " " + full_identifier.lower()

    # Path 1: Co-invest keywords (original logic, any company marker)
    if has_company_marker:
        if any(kw in combined for kw in _COINVEST_KEYWORDS):
            return True

        # Check named LP pipe patterns (these appear in the full identifier)
        ident_lower = full_identifier.lower() if full_identifier and isinstance(full_identifier, str) else ""
        if any(pat in ident_lower for pat in _NAMED_LP_PATTERNS):
            return True

    # Path 2: Bare LP interest -- stricter requirements
    has_strict_marker = any(m in issuer_lower for m in _STRICT_COMPANY_MARKERS)
    has_fund_word = bool(_FUND_WORD_RE.search(issuer_lower))
    if has_strict_marker and not has_fund_word:
        if any(kw in combined for kw in _LP_INTEREST_KEYWORDS):
            return True

    return False
