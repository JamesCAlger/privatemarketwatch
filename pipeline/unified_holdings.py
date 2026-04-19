"""Unified private markets holdings -- combines BDC and N-PORT data.

Produces a single private_markets_holdings.csv with standardised schema,
asset/issuer/index classification, and parsed identifiers suitable for
index construction and dashboard analytics.
"""

import logging
import re
import time
from pathlib import Path
from typing import Optional, Union

import duckdb
import pandas as pd

from pipeline.config import (
    BDC_HOLDINGS_FILE,
    ENTITY_LOOKUP_FILE,
    IDENTIFIER_EXTRACTION_LOOKUP_FILE,
    NPORT_EXCLUDE_CIKS,
    NPORT_HOLDINGS_FILE,
    UNIFIED_HOLDINGS_FILE,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Unified output column order
UNIFIED_COLUMNS = [
    # Identity
    "source", "cik", "entity_name", "accession_number",
    "filing_date", "report_date",
    # Holding identification
    "issuer_name", "instrument_description",
    # Identifiers (N-PORT only)
    "cusip", "isin", "lei", "ticker",
    # Valuation
    "fair_value", "cost", "pct_of_net_assets",
    "shares_held", "principal_amount",
    # Classification
    "asset_category", "issuer_category", "index_classification",
    "fair_value_level",
    # Rate/spread
    "interest_rate", "basis_spread", "reference_rate_type",
    "coupon_type", "pik_rate",
    # Debt details
    "maturity_date",
    # Source-specific (BDC)
    "bdc_investment_identifier", "bdc_form_type", "bdc_dimensions_raw",
    "bdc_unrealized_gain_loss",
    # Source-specific (N-PORT)
    "nport_holding_id", "nport_series_name", "nport_series_id",
    "nport_asset_cat", "nport_issuer_type", "nport_payoff_profile",
    "nport_investment_country", "nport_is_restricted", "nport_quarter",
    "nport_is_default", "nport_are_interest_payments_in_arrears",
    "nport_is_paid_in_kind", "nport_currency_code",
    "nport_liquidity_classification",
    # Entity resolution (populated by --entities step)
    "entity_id", "canonical_name",
    # LLM-extracted fields (populated by --extract step)
    "extracted_industry",
    # Position tracking (populated by --returns step)
    "position_id",
]

# BDC aggregate row patterns (case-insensitive substring)
_BDC_AGGREGATE_PATTERNS = [
    "non-control",
    "affiliate investments",
    "control investments",
    "total investments",
    "net assets",
    "subtotal",
    # V3 additions -- confirmed leaked patterns from data exploration
    "total cash",
    "cash and cash equivalents",
    "total fair value",
    "total cost",
    "unfunded commitments",
    "total unfunded",
    "weighted average",
    "liabilities in excess",
    "investment debt investments",
    "investment equity securities",
    "investment unsecured",
    "placeholder",
    "controlled affiliated",
    "non-controlled",
    # Category-level subtotals from hierarchical XBRL filings
    "portfolio company debt securities",
    "portfolio company equity investments",
    "portfolio company equity securities",
    "equity and other investments",
    "debt securities-",
    "1st lien/senior secured",
    "2nd lien/senior secured",
    "1st lien/last-out",
    "subordinated/unsecured",
    "amounts related to investments transferred",
    # Aggregate-only XBRL filers (balance sheet lines, portfolio-level summaries)
    "assets in excess",
    "investment portfolio",
    "total mutual",
    "total u.s. treasury",
    "total debt & equity",
    "total real estate properties",
    "debt & equity securities",
    "largest portfolio company",
    # "Total X" subtotal patterns (specific enough to avoid false positives
    # like "Total Safety Holdings LLC" or "Total Access Elevator, Inc.")
    "total affiliates",
    "total senior secured",
    "total senior direct",
    "total first lien",
    "total second lien",
    "total subordinated",
    "total warrant",
    "total portfolio",
    "total structured",
    # Additional leaked subtotals found in position-return analysis (2026-04-03)
    "total debt investments",
    "total secured debt",
    "total bank debt",
    "total equipment financing",
    "total unsecured",
    # Audit A3 gaps (2026-04-06)
    "sub-total",
    "total senior unsecured",
    "total mezzanine",
    "total unitranche",
    # Equity category subtotals (e.g. SLR Investment Corp "Total Common Equity/...")
    "total common equity",
    "total preferred equity",
    "total equity/",
    "total equity investment",
    # Affiliation-level subtotals (2026-04-09 audit)
    "total controlled affiliates",
    "total affiliated investments",
    "total controlled investments",
    "total controlled/affiliated",
    "total non controlled non affiliated",
    # Fund-level aggregates (2026-04-09 audit)
    "investment fund after cash",
    "portfolio company investment in securities",
    "five largest loan exposures",
    "five largest portfolio",
    "investments in controlled, affiliated",
    "investments in controlled affiliated",
    "net asset value at fair value",
    "cash and investments",
    # XBRL dimension member labels (category-level tags, not investee-level)
    "[member]",
]

# Bare issuer names that are section headers or industry labels (exact match, lower)
_BDC_AGGREGATE_EXACT = {
    "investments", "debt investments", "equity securities",
    "equity investments", "cash equivalents", "cash",
    "controlled investments", "controlled affiliated investments",
    "debt securities", "short-term investments",
    "total portfolio company commitments",
    "total short-term investments",
    "total debt investments",
    "total equity investments",
    "total equity securities",
    "debt investment",  # singular (e.g., from aggregate-only XBRL)
    # Bare section headers leaked from hierarchical XBRL
    "largest portfolio company investment",
    "senior secured loans",
    "senior secured notes",
    "first lien",
    "second lien",
    "equity/other",
    "collateralized loan obligation",
    "clo subordinated notes",
    # Exact-match "total" subtotals (only match when the ENTIRE lowered
    # identifier equals the string -- "Total Equity Solutions Inc" won't match)
    "total equity",
    "total warrants",
    "total affiliates",
    # Compound section headers with " - " separator (MidCap, AB Private Credit)
    "first lien - secured debt",
    "second lien - secured debt",
    "unsecured debt",
    "u.s. 1st lien/junior secured debt",
    # Bare instrument-type headers (Kennedy Lewis, SLR HC BDC, Ares Core Infra)
    "first and second lien debt",
    "bank debt/senior secured loans",
    "senior subordinated loans",
    "senior secured loans - first lien",
    "first lien/senior",
    "portfolio investments and cash equivalents",
    "liabilities less other assets",
    # Standalone category headers that are subtotals (2026-04-09 audit)
    "first lien secured debt",
    "first lien/senior secured debt",
}

# Suffix patterns for industry-prefixed subtotals.
# Identifiers ENDING with these strings (no rate/maturity/company after)
# are category-level subtotals, e.g. "Oil, Gas & Consumable Fuels First and Second Lien Debt".
# Real positions always have SOFR/Spread/Interest Rate/Due after the instrument type.
# NOTE: Only include patterns that do NOT appear at the end of real position identifiers.
# "first lien senior secured term loan" is too broad (real positions end with it too).
_BDC_AGGREGATE_SUFFIXES = [
    "first and second lien debt",
    "equity investments",
]

# Issuer names that are industry/geography labels (not companies).
# Single-word entries are filtered only when the identifier IS a single word.
# Multi-word entries are exact-matched against the full identifier (for bare headers)
# AND used for industry-prefix detection in CTE 5 (for "Industry - Company - Instrument").
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
    "NUSS": "GOVERNMENT",
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
    "liquidity fund",
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
    "capital partners", "co-invest",
    "secondaries", "infrastructure", "real assets", "opportunistic",
    "lp interest", "lp interests", "partnership interest",
]

# N-PORT fund-like issuer name detection: CORP+OTHER holdings with these
# patterns are likely PE/VC fund interests, not operating companies.
_NPORT_FUND_NAME_KEYWORDS = [
    "capital partners", "buyout", "ventures", "growth equity",
]

# N-PORT credit fund name detection: EC+CORPORATE holdings with these
# keywords in issuer_name are likely BDC/credit fund interests, not operating cos.
_NPORT_CREDIT_FUND_NAME_KEYWORDS = [
    "bdc", "private credit", "senior loan", "lending fund",
    "credit fund", "credit corp", "direct lend",
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

# Pipe-format direction detection: if the last pipe-segment matches one of
# these tags, the format is "Company | Instrument | Affiliation" (Blue Owl,
# Golub, TriplePoint) rather than "Type | Industry | Company" (SLR).
_AFFILIATION_TAGS = {
    "non-affiliated issuer", "affiliated issuer",
    "non-affiliated", "affiliated", "controlled",
    "non-control/non-affiliate", "control", "affiliate",
}

# Instrument-type keywords for 3-pipe format detection.  When segment 3
# matches one of these, it is an instrument description, NOT a company name.
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
_QTY_PREFIX_RE = re.compile(r"^\$?[\d,.]+ ?")


# ---------------------------------------------------------------------------
# SQL generation helpers (generate SQL from Python constants)
# ---------------------------------------------------------------------------

def _sql_keyword_check(col: str, keywords: list[str]) -> str:
    """Generate SQL OR chain: contains(col, 'kw1') OR contains(col, 'kw2') ..."""
    clauses = [f"contains({col}, '{kw.replace(chr(39), chr(39)+chr(39))}')"
               for kw in keywords]
    return "(" + " OR ".join(clauses) + ")"


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


def _sql_is_bdc_aggregate() -> str:
    """Generate SQL boolean expression for aggregate row detection."""
    parts = []
    # NULL/empty identifiers are always aggregates (matches Python _is_bdc_aggregate_row)
    parts.append("_lower_id = ''")
    # Named aggregate patterns (substring)
    parts.append(_sql_keyword_check("_lower_id", _BDC_AGGREGATE_PATTERNS))
    # Exact match section headers
    parts.append(_sql_exact_match("_lower_id", _BDC_AGGREGATE_EXACT))
    # Category header prefixes (only when no ' - ' separator)
    _cat_prefixes = [
        "debt investments ", "debt investments,",
        "debt securities ",
        "equity securities ", "equity investments ",
        "investment 1st lien", "investment 2nd lien",
        "investment subordinated", "investment unsecured",
        "investments ", "investments-",
        "debt investment ",  # singular with industry/pct suffix
    ]
    cat_sql = _sql_starts_with_any("_lower_id", _cat_prefixes)
    parts.append(f"(NOT contains(_raw_id, ' - ') AND {cat_sql})")
    # Identifiers ending with a percentage are always subtotals/allocations
    parts.append("regexp_matches(_lower_id, '\\d+\\.?\\d*%\\s*$')")
    # "Total ..." industry subtotals: starts with "total " but does NOT contain
    # any company suffix (Inc., LLC, Corp., Ltd., LP, Holdings, Group, Solutions,
    # Fund, Partners, Term, Loan, Note, Stock, Warrant, Debt, Common, Preferred).
    # This catches "Total Software", "Total Healthcare & Pharmaceuticals" etc.
    # while preserving "Total Access Elevator, Inc.", "Total Safety U.S. Inc."
    _total_company_signals = [
        "inc.", "inc,", "llc", "corp.", "corp,", "ltd.", "ltd,",
        ", lp", " lp,", "holdings", "group", "solutions",
        "technologies",
        "term loan", "term debt", "revolver", "delayed draw",
    ]
    company_guards = " AND ".join(
        f"NOT contains(_lower_id, '{s}')" for s in _total_company_signals
    )
    parts.append(
        f"(starts_with(_lower_id, 'total ') AND {company_guards})"
    )
    # Also catch pipe-delimited subtotals where "Total X" is in the last
    # segment, e.g. "Corporate Bonds | Automotive | Total Automotive"
    last_seg = "trim(string_split(_lower_id, ' | ')[-1])"
    last_seg_guards = " AND ".join(
        f"NOT contains({last_seg}, '{s}')" for s in _total_company_signals
    )
    parts.append(
        f"(contains(_lower_id, ' | ') AND starts_with({last_seg}, 'total ') "
        f"AND {last_seg_guards})"
    )
    # Industry-prefixed subtotals: identifier ENDS with instrument type
    # (real positions always have rate/maturity after the instrument type)
    suffix_sql = _sql_ends_with_any("_lower_id", _BDC_AGGREGATE_SUFFIXES)
    parts.append(suffix_sql)
    # Single-word industry/geography labels
    single_word_labels = sorted(v for v in _INDUSTRY_LABELS if " " not in v)
    multi_word_labels = sorted(v for v in _INDUSTRY_LABELS if " " in v)
    if single_word_labels:
        parts.append(f"(NOT contains(_lower_id, ' ') AND {_sql_exact_match('_lower_id', set(single_word_labels))})")
    if multi_word_labels:
        parts.append(_sql_exact_match("_lower_id", set(multi_word_labels)))
    return " OR ".join(parts)


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

    return f"""CASE
  WHEN asset_category IN ('LOAN', 'DEBT') AND issuer_category = 'CORPORATE' THEN 'DIRECT_LENDING'
  WHEN asset_category = 'EQUITY_PREFERRED' AND issuer_category = 'CORPORATE' THEN 'PREFERRED_EQUITY'
  WHEN asset_category = 'EQUITY_COMMON' AND issuer_category = 'CORPORATE' THEN 'COMMON_EQUITY'
  WHEN issuer_category = 'FUND' AND {has_credit} AND NOT {has_pe} THEN 'PRIVATE_CREDIT_FUND'
  WHEN issuer_category = 'FUND' AND {has_pe} AND NOT {has_credit} THEN 'PRIVATE_EQUITY_FUND'
  WHEN issuer_category = 'FUND' AND {has_credit} AND {has_pe} AND {credit_count} >= {pe_count} THEN 'PRIVATE_CREDIT_FUND'
  WHEN issuer_category = 'FUND' AND {has_credit} AND {has_pe} AND {credit_count} < {pe_count} THEN 'PRIVATE_EQUITY_FUND'
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

def _parse_bdc_identifier(identifier: str) -> tuple[str, str]:
    """Split a BDC investment_identifier into (issuer_name, instrument_description).

    Handles five pipe sub-formats (3-pipe):
    1. affil_last:    "Company | Instrument | Affiliation"  -> issuer = seg1
    2. company_first: "Company | Industry | Instrument"     -> issuer = seg1
    3. company_seg2:  "Category | Company | Instrument"     -> issuer = seg2
    4. slr:           "Type | Industry | Company | ..."     -> issuer = seg3

    Plus dash-based:
    5. Industry-prefix: "Industry - Company - Instrument"   -> issuer = seg2
    6. Default: "Company - Instrument"                      -> issuer = seg1

    Returns ("", "") for empty/null input.
    """
    if not identifier or not isinstance(identifier, str):
        return ("", "")

    # Pipe-separator format
    if " | " in identifier:
        pipe_parts = identifier.split(" | ")
        if len(pipe_parts) >= 3:
            last_seg = pipe_parts[-1].strip().lower()
            if last_seg in _AFFILIATION_TAGS:
                # Affiliation format: "Company | Instrument | Affiliation"
                issuer = pipe_parts[0].strip()
                instrument = pipe_parts[1].strip()
                return (issuer, instrument)

            # 3-pipe sub-format detection
            if len(pipe_parts) == 3:
                seg1 = pipe_parts[0].strip()
                seg2 = pipe_parts[1].strip()
                seg3 = pipe_parts[2].strip()
                _suffix_re = re.compile(
                    _LEGAL_SUFFIX_RE_SQL, re.IGNORECASE
                )
                seg1_is_company = bool(_suffix_re.search(seg1))
                seg2_is_company = bool(_suffix_re.search(seg2))
                seg3_is_instrument = any(
                    kw in seg3.lower() for kw in _PIPE_INSTRUMENT_KEYWORDS
                )
                if seg1_is_company:
                    # company_first: "Company | Industry | Instrument"
                    return (seg1, seg3)
                if seg3_is_instrument and seg2_is_company:
                    # company_seg2: "Category | Company | Instrument"
                    return (seg2, seg3)
                if seg3_is_instrument and seg2.lower() in _INDUSTRY_LABELS:
                    # company_first without legal suffix: seg2 is known industry
                    return (seg1, seg3)

            # SLR format: "Type | Industry | Company | ..."
            issuer = pipe_parts[2].strip()
            other_parts = [pipe_parts[0].strip(), pipe_parts[1].strip()]
            if len(pipe_parts) >= 4:
                other_parts.extend(p.strip() for p in pipe_parts[3:])
            instrument = ", ".join(other_parts)
            return (issuer, instrument)
        elif len(pipe_parts) == 2:
            # 2-segment pipe: "Company | Instrument" or "Company | Affiliation"
            issuer = pipe_parts[0].strip()
            instrument = pipe_parts[1].strip()
            return (issuer, instrument)

    if " - " not in identifier:
        return (identifier.strip(), "")

    segments = identifier.split(" - ")
    first_seg = segments[0].strip()

    # Industry-prefix detection: if first segment is a known label and 3+ segments
    if first_seg.lower() in _INDUSTRY_LABELS and len(segments) >= 3:
        issuer = segments[1].strip()
        instrument = " - ".join(s.strip() for s in segments[2:])
        instrument = _QTY_PREFIX_RE.sub("", instrument).strip()
        return (issuer, instrument)

    # Default: first segment is issuer, rest is instrument
    instrument = " - ".join(s.strip() for s in segments[1:])
    instrument = _QTY_PREFIX_RE.sub("", instrument).strip()

    return (first_seg, instrument)


# ---------------------------------------------------------------------------
# BDC aggregate/subtotal detection
# ---------------------------------------------------------------------------

def _is_bdc_aggregate_row(identifier: str) -> bool:
    """Return True if this BDC identifier is an aggregate/subtotal row.

    Filters:
    1. Named aggregate substring patterns (e.g., "total investments")
    2. Exact-match section headers (e.g., "Investments", "Debt Investments")
    3. Single-word industry/geography labels (e.g., "Insurance", "Canada")
    4. "Debt Investments XXX" category headers (e.g., "Debt Investments Software")
    """
    if not identifier or not isinstance(identifier, str):
        return True

    lower = identifier.lower().strip()

    # Named aggregate patterns (substring)
    for pattern in _BDC_AGGREGATE_PATTERNS:
        if pattern in lower:
            return True

    # Exact match section headers
    if lower in _BDC_AGGREGATE_EXACT:
        return True

    # Category headers: "Debt Investments <Industry>", "Debt Securities <Industry>",
    # "Equity Securities <Industry>", "Investment <Type>" etc.
    # These have no ' - ' separator and are always subtotals.
    if " - " not in identifier:
        _cat_prefixes = (
            "debt investments ", "debt investments,",
            "debt securities ",
            "equity securities ", "equity investments ",
            "investment 1st lien", "investment 2nd lien",
            "investment subordinated", "investment unsecured",
            "investments ", "investments-",
            "debt investment ",  # singular with industry/pct suffix
        )
        for pfx in _cat_prefixes:
            if lower.startswith(pfx):
                return True

    # Identifiers ending with a percentage are always subtotals/allocations
    # e.g. "Debt Investment 96.8%", "United States - 1.60%"
    if re.search(r"\d+\.?\d*%\s*$", lower):
        return True

    # Industry-prefixed subtotals: identifier ends with instrument type
    # (real positions always have rate/maturity after)
    for suffix in _BDC_AGGREGATE_SUFFIXES:
        if lower.endswith(suffix):
            return True

    # "Total ..." industry subtotals: starts with "total " but does NOT contain
    # any company suffix (Inc., LLC, Corp., etc.)
    _total_co_signals = [
        "inc.", "inc,", "llc", "corp.", "corp,", "ltd.", "ltd,",
        ", lp", " lp,", "holdings", "group", "solutions",
        "technologies",
        "term loan", "term debt", "revolver", "delayed draw",
    ]
    if lower.startswith("total "):
        if not any(s in lower for s in _total_co_signals):
            return True
    # Also catch pipe-delimited subtotals where "Total X" is in the last
    # segment, e.g. "Corporate Bonds | Automotive | Total Automotive"
    if " | " in lower:
        last_seg = lower.rsplit(" | ", 1)[-1].strip()
        if last_seg.startswith("total "):
            if not any(s in last_seg for s in _total_co_signals):
                return True

    # Single-word industry/geography labels (bare identifiers only)
    if " " not in lower and lower in _INDUSTRY_LABELS:
        return True
    # Multi-word labels
    if lower in _INDUSTRY_LABELS:
        return True

    return False


# ---------------------------------------------------------------------------
# Asset classification
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
                    issuer_name: str, instrument_description: str) -> str:
    """Assign one of the five private market indices (or UNCLASSIFIED).

    Rules:
      DIRECT_LENDING:      LOAN/DEBT + CORPORATE
      PREFERRED_EQUITY:    EQUITY_PREFERRED + CORPORATE
      COMMON_EQUITY:       EQUITY_COMMON + CORPORATE
      PRIVATE_CREDIT_FUND: FUND issuer + credit signals in name
      PRIVATE_EQUITY_FUND: FUND issuer + PE signals in name
      UNCLASSIFIED:        everything else
    """
    if asset_category in ("LOAN", "DEBT") and issuer_category == "CORPORATE":
        return "DIRECT_LENDING"

    if asset_category == "EQUITY_PREFERRED" and issuer_category == "CORPORATE":
        return "PREFERRED_EQUITY"

    if asset_category == "EQUITY_COMMON" and issuer_category == "CORPORATE":
        return "COMMON_EQUITY"

    if issuer_category == "FUND":
        # Combine issuer name + instrument description for signal matching
        combined = ""
        if issuer_name and isinstance(issuer_name, str):
            combined += issuer_name.lower()
        if instrument_description and isinstance(instrument_description, str):
            combined += " " + instrument_description.lower()

        has_credit = any(sig in combined for sig in _CREDIT_FUND_SIGNALS)
        has_pe = any(sig in combined for sig in _PE_FUND_SIGNALS)

        if has_credit and not has_pe:
            return "PRIVATE_CREDIT_FUND"
        if has_pe and not has_credit:
            return "PRIVATE_EQUITY_FUND"
        # Ambiguous or no signals -- still classify by what's stronger
        if has_credit and has_pe:
            # Count matches -- more signals wins
            credit_count = sum(1 for s in _CREDIT_FUND_SIGNALS if s in combined)
            pe_count = sum(1 for s in _PE_FUND_SIGNALS if s in combined)
            if credit_count >= pe_count:
                return "PRIVATE_CREDIT_FUND"
            return "PRIVATE_EQUITY_FUND"
        # No signals at all
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
      > 0.50 and <= 50 -> already percentage (leave as-is)
      > 50      -> basis points (divide by 100)
    """
    if raw is None:
        return None
    if raw <= 0.50:
        return raw * 100
    if raw > 50:
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


def _reclassify_named_fund_positions(df: pd.DataFrame) -> pd.DataFrame:
    """Reclassify named co-invest and LP interest positions from FUND to EQUITY.

    For rows where asset_category == "FUND" and the holding identifies a
    specific operating company (via _is_named_coinvest), override:
      - asset_category -> EQUITY_PREFERRED if "preferred" in name, else EQUITY_COMMON
      - issuer_category -> CORPORATE

    This ensures _classify_index() returns PREFERRED_EQUITY or COMMON_EQUITY for these rows.
    """
    if "asset_category" not in df.columns or len(df) == 0:
        return df

    fund_mask = df["asset_category"] == "FUND"
    if not fund_mask.any():
        return df

    # Evaluate _is_named_coinvest for FUND rows only
    fund_idx = df.index[fund_mask]
    named_mask = df.loc[fund_idx].apply(
        lambda row: _is_named_coinvest(
            row.get("issuer_name", ""),
            row.get("instrument_description", ""),
            row.get("bdc_investment_identifier", row.get("investment_identifier", "")),
        ),
        axis=1,
    )
    named_idx = fund_idx[named_mask]

    if len(named_idx) == 0:
        return df

    # Determine preferred vs common
    for idx in named_idx:
        combined = ""
        for col in ["issuer_name", "instrument_description"]:
            val = df.at[idx, col] if col in df.columns else ""
            if val and isinstance(val, str):
                combined += " " + val.lower()
        if "preferred" in combined:
            df.at[idx, "asset_category"] = "EQUITY_PREFERRED"
        else:
            df.at[idx, "asset_category"] = "EQUITY_COMMON"
        df.at[idx, "issuer_category"] = "CORPORATE"

    logger.info("  Reclassified %d named co-invest/LP positions from FUND to EQUITY",
                len(named_idx))

    return df


# ---------------------------------------------------------------------------
# BDC preparation
# ---------------------------------------------------------------------------

def _prepare_bdc(bdc_df: pd.DataFrame) -> pd.DataFrame:
    """Filter, parse, classify, and map BDC holdings to unified schema.

    Uses a DuckDB CTE pipeline for all data manipulation. The pandas
    DataFrame is registered as a virtual table, transformed entirely in
    SQL, and the result is fetched back as a pandas DataFrame.
    """
    logger.info("Preparing BDC holdings: %d input rows", len(bdc_df))

    if bdc_df.empty:
        return pd.DataFrame(columns=UNIFIED_COLUMNS)

    con = duckdb.connect()
    con.register("bdc_raw", bdc_df)

    # Pre-generate SQL fragments from Python constants
    agg_filter = _sql_is_bdc_aggregate()
    asset_case = _sql_classify_bdc_asset()
    coinvest_expr = _sql_is_named_coinvest()
    mm_check = _sql_money_market_check()
    industry_in = _sql_industry_label_in()
    affil_in = _sql_exact_match(
        "lower(trim(string_split(_raw_id, ' | ')[-1]))", _AFFILIATION_TAGS
    )
    # 3-pipe format detection helpers
    seg1_has_suffix = (
        f"regexp_matches(lower(trim(string_split(_raw_id, ' | ')[1])), "
        f"'{_LEGAL_SUFFIX_RE_SQL}')"
    )
    seg2_has_suffix = (
        f"regexp_matches(lower(trim(string_split(_raw_id, ' | ')[2])), "
        f"'{_LEGAL_SUFFIX_RE_SQL}')"
    )
    seg3_is_instrument = _sql_keyword_check(
        "lower(trim(string_split(_raw_id, ' | ')[3]))", _PIPE_INSTRUMENT_KEYWORDS
    )
    seg2_is_industry = _sql_exact_match(
        "lower(trim(string_split(_raw_id, ' | ')[2]))", _INDUSTRY_LABELS
    )
    name_norm = _sql_normalize_name("issuer_name")

    # Fund vehicle/manager detection: equity-type positions with these name
    # signals get issuer_category = FUND (overrides the default CORPORATE).
    fund_vehicle_clauses = []
    for kw in _BDC_FUND_VEHICLE_KEYWORDS:
        kw_escaped = kw.replace("'", "''")
        if kw == "asset management":
            # Position guard: must appear within first N chars
            fund_vehicle_clauses.append(
                f"(strpos(lower(CAST(issuer_name AS VARCHAR)), '{kw_escaped}') > 0"
                f" AND strpos(lower(CAST(issuer_name AS VARCHAR)), '{kw_escaped}')"
                f" <= {_BDC_FUND_VEHICLE_POS_GUARD})"
            )
        else:
            fund_vehicle_clauses.append(
                f"contains(lower(CAST(issuer_name AS VARCHAR)), '{kw_escaped}')"
            )
    fund_vehicle_sql = " OR ".join(fund_vehicle_clauses)

    # Filter comparative-period rows if the 'period' column exists
    has_period = "period" in bdc_df.columns
    period_filter = (
        """WHERE TRY_CAST(period AS DATE) = TRY_CAST(report_date AS DATE)
           OR period IS NULL
           OR CAST(period AS VARCHAR) = ''"""
        if has_period else ""
    )

    sql = f"""
    WITH
    -- CTE 1: Normalise text columns, cast numerics, add row id
    -- Filter to current-period rows only (period = report_date).
    -- Comparative rows (period < report_date) are preserved in raw
    -- bdc_holdings.csv for position matching but excluded from the
    -- unified index to avoid double-counting.
    raw AS (
        SELECT
            *,
            ROW_NUMBER() OVER () AS _row_id,
            COALESCE(CAST(investment_identifier AS VARCHAR), '') AS _raw_id,
            COALESCE(lower(trim(CAST(investment_identifier AS VARCHAR))), '') AS _lower_id,
            TRY_CAST(fair_value AS DOUBLE) AS _fv,
            TRY_CAST(interest_rate AS DOUBLE) AS _ir,
            TRY_CAST(principal_amount AS DOUBLE) AS _pa,
            TRY_CAST(shares_held AS DOUBLE) AS _sh,
            TRY_CAST(basis_spread AS DOUBLE) AS _bs,
            TRY_CAST(cost AS DOUBLE) AS _cost,
            TRY_CAST(pct_of_net_assets AS DOUBLE) AS _pct,
            TRY_CAST(pik_rate AS DOUBLE) AS _pik,
            TRY_CAST(unrealized_gain_loss AS DOUBLE) AS _ugl
        FROM bdc_raw
        {period_filter}
    ),

    -- CTE 1b: Amendment dedup -- when a CIK has both a 10-K and 10-K/A
    -- (or 10-Q and 10-Q/A) for the same report_date, keep only the rows
    -- from the latest-filed accession.  If the amendment's XBRL had no
    -- investment data (common: 21/27 amendments in our dataset), the
    -- original is the only accession with rows and is kept automatically.
    no_amendments AS (
        SELECT r.* FROM raw r
        INNER JOIN (
            SELECT cik, report_date, accession_number,
                ROW_NUMBER() OVER (
                    PARTITION BY cik, CAST(report_date AS VARCHAR),
                        REGEXP_REPLACE(CAST(form_type AS VARCHAR), '/A$', '')
                    ORDER BY CAST(filing_date AS VARCHAR) DESC
                ) AS _amd_rank
            FROM raw
            GROUP BY cik, report_date, accession_number, form_type, filing_date
        ) ranked
          ON r.cik = ranked.cik
         AND r.report_date = ranked.report_date
         AND r.accession_number = ranked.accession_number
        WHERE ranked._amd_rank = 1
    ),

    -- CTE 2: Filter aggregate/subtotal rows
    no_aggregates AS (
        SELECT * FROM no_amendments
        WHERE NOT ({agg_filter})
    ),

    -- CTE 3: Filter XBRL artifacts (no financial data at all)
    no_artifacts AS (
        SELECT * FROM no_aggregates
        WHERE _fv IS NOT NULL
           OR _ir IS NOT NULL
           OR _pa IS NOT NULL
           OR _sh IS NOT NULL
    ),

    -- CTE 4: Filter hierarchical prefix subtotals via self-join
    no_subtotals AS (
        SELECT a.* FROM no_artifacts a
        WHERE NOT EXISTS (
            SELECT 1 FROM no_artifacts b
            WHERE a.cik = b.cik
              AND a.accession_number = b.accession_number
              AND b._raw_id LIKE a._raw_id || '%'
              AND LENGTH(b._raw_id) > LENGTH(a._raw_id) + 10
              AND a._raw_id IS NOT NULL
              AND LENGTH(a._raw_id) >= 3
        )
    ),

    -- CTE 5a: Initial split + helper columns for re-parsing
    initial_split AS (
        SELECT *,
            string_split(_raw_id, ' - ') AS _segments,
            CASE
                WHEN NOT contains(_raw_id, ' - ') THEN trim(_raw_id)
                ELSE trim(string_split(_raw_id, ' - ')[1])
            END AS _issuer_raw,
            CASE
                WHEN NOT contains(_raw_id, ' - ') THEN lower(trim(_raw_id))
                ELSE lower(trim(string_split(_raw_id, ' - ')[1]))
            END AS _issuer_lower,
            -- Pipe-separator detection: four 3-pipe sub-formats
            --   affil_last:    "Company | Instrument | Affiliation"  -> issuer = seg1
            --   company_first: "Company | Industry | Instrument"     -> issuer = seg1
            --   company_seg2:  "Category | Company | Instrument"     -> issuer = seg2
            --   slr:           "Type | Industry | Company | ..."     -> issuer = seg3
            CASE
                -- 3+ pipes: last segment is affiliation tag
                WHEN contains(_raw_id, ' | ') AND len(string_split(_raw_id, ' | ')) >= 3
                     AND {affil_in}
                THEN trim(string_split(_raw_id, ' | ')[1])
                -- 3 pipes: seg1 has legal suffix -> company-first
                WHEN contains(_raw_id, ' | ') AND len(string_split(_raw_id, ' | ')) = 3
                     AND {seg1_has_suffix}
                THEN trim(string_split(_raw_id, ' | ')[1])
                -- 3 pipes: seg3 is instrument AND seg2 has legal suffix -> company in seg2
                WHEN contains(_raw_id, ' | ') AND len(string_split(_raw_id, ' | ')) = 3
                     AND {seg3_is_instrument}
                     AND {seg2_has_suffix}
                THEN trim(string_split(_raw_id, ' | ')[2])
                -- 3 pipes: seg3 is instrument AND seg2 is known industry -> company in seg1
                WHEN contains(_raw_id, ' | ') AND len(string_split(_raw_id, ' | ')) = 3
                     AND {seg3_is_instrument}
                     AND {seg2_is_industry}
                THEN trim(string_split(_raw_id, ' | ')[1])
                -- 3+ pipes: default SLR -> issuer = seg3
                WHEN contains(_raw_id, ' | ') AND len(string_split(_raw_id, ' | ')) >= 3
                THEN trim(string_split(_raw_id, ' | ')[3])
                -- 2 pipes
                WHEN contains(_raw_id, ' | ') AND len(string_split(_raw_id, ' | ')) = 2
                THEN trim(string_split(_raw_id, ' | ')[1])
                ELSE NULL
            END AS _pipe_issuer,
            -- Track which pipe variant for instrument_description assembly
            CASE
                WHEN contains(_raw_id, ' | ') AND len(string_split(_raw_id, ' | ')) >= 3
                     AND {affil_in}
                THEN 'affil_last'
                WHEN contains(_raw_id, ' | ') AND len(string_split(_raw_id, ' | ')) = 3
                     AND {seg1_has_suffix}
                THEN 'company_first'
                WHEN contains(_raw_id, ' | ') AND len(string_split(_raw_id, ' | ')) = 3
                     AND {seg3_is_instrument}
                     AND {seg2_has_suffix}
                THEN 'company_seg2'
                WHEN contains(_raw_id, ' | ') AND len(string_split(_raw_id, ' | ')) = 3
                     AND {seg3_is_instrument}
                     AND {seg2_is_industry}
                THEN 'company_first'
                WHEN contains(_raw_id, ' | ') AND len(string_split(_raw_id, ' | ')) >= 3
                THEN 'slr'
                WHEN contains(_raw_id, ' | ') AND len(string_split(_raw_id, ' | ')) = 2
                THEN 'two_pipe'
                ELSE NULL
            END AS _pipe_format,
        FROM no_subtotals
    ),

    -- CTE 5b: Re-parse with industry-prefix detection and pipe-format override
    parsed AS (
        SELECT * EXCLUDE (_issuer_raw, _issuer_lower, _pipe_issuer, _pipe_format, _segments),
            CASE
                -- Pipe format takes priority
                WHEN _pipe_issuer IS NOT NULL THEN _pipe_issuer
                -- Industry prefix with 3+ segments: take segment 2 as issuer
                WHEN {industry_in}
                     AND len(_segments) >= 3
                THEN trim(_segments[2])
                -- Default: first segment
                ELSE _issuer_raw
            END AS issuer_name,
            CASE
                -- 2-pipe: instrument = segment 2
                WHEN _pipe_issuer IS NOT NULL AND _pipe_format = 'two_pipe'
                THEN trim(string_split(_raw_id, ' | ')[2])
                -- Affiliation-last (3+): instrument = segment 2
                WHEN _pipe_issuer IS NOT NULL AND _pipe_format = 'affil_last'
                THEN trim(string_split(_raw_id, ' | ')[2])
                -- Company-first (3): instrument = segment 3
                WHEN _pipe_issuer IS NOT NULL AND _pipe_format = 'company_first'
                THEN trim(string_split(_raw_id, ' | ')[3])
                -- Company in seg2 (3): instrument = segment 3
                WHEN _pipe_issuer IS NOT NULL AND _pipe_format = 'company_seg2'
                THEN trim(string_split(_raw_id, ' | ')[3])
                -- SLR (3+): combine segments 1, 2, and 4+ as instrument
                WHEN _pipe_issuer IS NOT NULL AND _pipe_format = 'slr'
                THEN trim(string_split(_raw_id, ' | ')[1]) || ', ' || trim(string_split(_raw_id, ' | ')[2])
                     || CASE
                         WHEN len(string_split(_raw_id, ' | ')) >= 4
                         THEN ', ' || trim(array_to_string(string_split(_raw_id, ' | ')[4:], ' | '))
                         ELSE ''
                     END
                -- Industry prefix with 3+ segments: segments 3+ as instrument
                WHEN {industry_in}
                     AND len(_segments) >= 3
                THEN regexp_replace(
                    trim(array_to_string(_segments[3:], ' - ')),
                    '^\\$?[\\d,.]+ ?', ''
                )
                -- No dash: empty instrument
                WHEN NOT contains(_raw_id, ' - ') THEN ''
                -- Default: segments 2+ as instrument
                ELSE regexp_replace(
                    trim(array_to_string(_segments[2:], ' - ')),
                    '^\\$?[\\d,.]+ ?', ''
                )
            END AS instrument_description
        FROM initial_split
    ),

    -- CTE 6: Classify asset category
    classified AS (
        SELECT *,
            -- Precompute lowercase fields for classification
            COALESCE(lower(trim(CAST(instrument_description AS VARCHAR))), '') AS _lower_instr,
            COALESCE(lower(trim(CAST(investment_type AS VARCHAR))), '') AS _lower_type,
            COALESCE(lower(trim(CAST(_raw_id AS VARCHAR))), '') AS _lower_full,
            (_ir IS NOT NULL AND _ir != 0) AS _has_interest_rate,
            (_sh IS NOT NULL AND _sh != 0) AS _has_shares,
            (_bs IS NOT NULL AND _bs != 0) AS _has_basis_spread,
            (_pa IS NOT NULL AND _pa != 0) AS _has_principal_amount
        FROM parsed
    ),

    with_asset AS (
        SELECT *,
            {asset_case} AS asset_category
        FROM classified
    ),

    -- CTE 7: Classify issuer
    with_issuer AS (
        SELECT *,
            CASE
                WHEN asset_category = 'FUND' THEN 'FUND'
                -- Equity stakes in fund managers / lending vehicles
                WHEN asset_category IN ('EQUITY_COMMON', 'EQUITY_PREFERRED', 'OTHER')
                     AND ({fund_vehicle_sql})
                THEN 'FUND'
                ELSE 'CORPORATE'
            END AS issuer_category
        FROM with_asset
    ),

    -- CTE 8: Named co-invest reclassification
    reclassified AS (
        SELECT *,
            -- Precompute fields for coinvest detection
            COALESCE(lower(trim(CAST(issuer_name AS VARCHAR))), '') AS _lower_issuer,
            COALESCE(lower(trim(CAST(issuer_name AS VARCHAR))), '') || ' ' ||
                COALESCE(lower(trim(CAST(instrument_description AS VARCHAR))), '') || ' ' ||
                COALESCE(lower(trim(CAST(_raw_id AS VARCHAR))), '') AS _combined_coinvest,
            COALESCE(lower(trim(CAST(_raw_id AS VARCHAR))), '') AS _lower_bdc_id
        FROM with_issuer
    ),

    with_reclass AS (
        SELECT *,
            CASE
                WHEN {coinvest_expr} AND contains(
                    COALESCE(lower(CAST(issuer_name AS VARCHAR)), '') || ' ' || COALESCE(lower(CAST(instrument_description AS VARCHAR)), ''),
                    'preferred'
                ) THEN 'EQUITY_PREFERRED'
                WHEN {coinvest_expr} THEN 'EQUITY_COMMON'
                ELSE asset_category
            END AS asset_category_final,
            CASE
                WHEN {coinvest_expr} THEN 'CORPORATE'
                ELSE issuer_category
            END AS issuer_category_final
        FROM reclassified
    ),

    -- CTE 9: Filter money market funds
    no_mm AS (
        SELECT * FROM with_reclass
        WHERE NOT ({mm_check})
    ),

    -- CTE 10: Infer coupon type
    with_coupon AS (
        SELECT *,
            CASE
                WHEN _bs IS NOT NULL AND _bs != 0 THEN 'Floating'
                WHEN _ir IS NOT NULL AND _ir != 0 THEN 'Fixed'
                ELSE ''
            END AS coupon_type
        FROM no_mm
    ),

    -- CTE 10b: Text enrichment from investment_identifier
    with_enrichment AS (
        SELECT *,
            -- Reference rate type: SOFR/LIBOR/PRIME from identifier text
            CASE
                WHEN regexp_matches(lower(_raw_id), '\\bsofr\\b') THEN 'SOFR'
                WHEN regexp_matches(lower(_raw_id), '\\blibor\\b') THEN 'LIBOR'
                WHEN regexp_matches(lower(_raw_id), '\\bprime\\b') THEN 'PRIME'
                ELSE NULL
            END AS _text_ref_rate,
            -- Maturity date: extract from "M/D/YYYY Maturity", "Due M/D/YY",
            -- "Maturity Date MM/DD/YYYY", "Maturity M/D/YYYY" patterns
            COALESCE(
                NULLIF(regexp_extract(_raw_id,
                    '(\\d{{1,2}}/\\d{{1,2}}/\\d{{2,4}})\\s+[Mm]aturity', 1), ''),
                NULLIF(regexp_extract(_raw_id,
                    '(?:[Mm]aturity|[Dd]ue)\\s+(?:[Dd]ate\\s+)?(\\d{{1,2}}/\\d{{1,2}}/\\d{{2,4}})', 1), '')
            ) AS _text_maturity_raw
        FROM with_coupon
    ),

    -- CTE 11: Map to unified schema
    unified AS (
        SELECT
            'bdc' AS source,
            LPAD(CAST(cik AS VARCHAR), 10, '0') AS cik,
            entity_name,
            accession_number,
            filing_date,
            report_date,
            {name_norm} AS issuer_name,
            instrument_description,
            '' AS cusip,
            '' AS isin,
            '' AS lei,
            '' AS ticker,
            _fv AS fair_value,
            _cost AS cost,
            CASE WHEN _pct IS NOT NULL AND _pct <= 0.50 THEN _pct * 100
                 WHEN _pct IS NOT NULL AND _pct > 50 THEN _pct / 100
                 ELSE _pct END AS pct_of_net_assets,
            asset_category_final AS asset_category,
            issuer_category_final AS issuer_category,
            '' AS index_classification,
            '' AS fair_value_level,
            CASE WHEN _ir IS NOT NULL AND _ir < 0 THEN NULL
                 WHEN _ir IS NOT NULL AND _ir <= 0.50 THEN _ir * 100
                 WHEN _ir IS NOT NULL AND _ir > 50 THEN _ir / 100
                 ELSE _ir END AS interest_rate,
            CASE WHEN _bs IS NOT NULL AND _bs < 0 THEN NULL
                 WHEN _bs IS NOT NULL AND _bs <= 0.50 THEN _bs * 100
                 WHEN _bs IS NOT NULL AND _bs > 50 THEN _bs / 100
                 ELSE _bs END AS basis_spread,
            COALESCE(NULLIF(CAST(reference_rate_type AS VARCHAR), ''), _text_ref_rate, '')
                AS reference_rate_type,
            coupon_type,
            CASE WHEN _pik IS NOT NULL AND _pik < 0 THEN NULL
                 WHEN _pik IS NOT NULL AND _pik <= 0.50 THEN _pik * 100
                 WHEN _pik IS NOT NULL AND _pik > 50 THEN _pik / 100
                 ELSE _pik END AS pik_rate,
            CASE
                WHEN maturity_date IS NOT NULL AND CAST(maturity_date AS VARCHAR) != ''
                    THEN CAST(maturity_date AS VARCHAR)
                WHEN _text_maturity_raw IS NOT NULL THEN
                    strftime(
                        CASE WHEN LENGTH(regexp_extract(
                                 _text_maturity_raw, '/(\\d+)$', 1)) <= 2
                             THEN TRY_STRPTIME(_text_maturity_raw, '%m/%d/%y')
                             ELSE TRY_STRPTIME(_text_maturity_raw, '%m/%d/%Y')
                        END,
                        '%Y-%m-%d')
                ELSE ''
            END AS maturity_date,
            _sh AS shares_held,
            _pa AS principal_amount,
            _raw_id AS bdc_investment_identifier,
            form_type AS bdc_form_type,
            dimensions_raw AS bdc_dimensions_raw,
            _ugl AS bdc_unrealized_gain_loss,
            '' AS nport_holding_id,
            '' AS nport_series_name,
            '' AS nport_series_id,
            '' AS nport_asset_cat,
            '' AS nport_issuer_type,
            '' AS nport_payoff_profile,
            '' AS nport_investment_country,
            '' AS nport_is_restricted,
            '' AS nport_quarter,
            '' AS nport_is_default,
            '' AS nport_are_interest_payments_in_arrears,
            '' AS nport_is_paid_in_kind,
            '' AS nport_currency_code,
            '' AS nport_liquidity_classification,
            '' AS entity_id,
            '' AS canonical_name,
            '' AS extracted_industry,
            '' AS position_id,
            _row_id
        FROM with_enrichment
    )

    SELECT * FROM unified ORDER BY _row_id
    """

    result = con.execute(sql).fetchdf()
    con.close()

    # Drop internal row id column
    result.drop(columns=["_row_id"], inplace=True)

    # Log filtering stats
    input_count = len(bdc_df)
    output_count = len(result)
    logger.info("  After all BDC filters: %d rows (%d removed)",
                output_count, input_count - output_count)

    logger.info("  BDC asset breakdown:")
    for cat, count in result["asset_category"].value_counts().items():
        logger.info("    %s: %d (%.1f%%)", cat, count, 100 * count / len(result))

    # Log text enrichment stats
    n = len(result)
    ref_filled = (result["reference_rate_type"] != "").sum()
    mat_filled = (result["maturity_date"] != "").sum()
    logger.info("  Text enrichment: reference_rate_type %d (%.1f%%), "
                "maturity_date %d (%.1f%%)",
                ref_filled, 100 * ref_filled / n if n else 0,
                mat_filled, 100 * mat_filled / n if n else 0)

    return result


# ---------------------------------------------------------------------------
# N-PORT preparation
# ---------------------------------------------------------------------------

def _prepare_nport(nport_input: Union[pd.DataFrame, Path, str]) -> pd.DataFrame:
    """Filter to Level 3, classify, and map N-PORT holdings to unified schema.

    Uses a DuckDB CTE pipeline for all data manipulation.

    Parameters
    ----------
    nport_input : pd.DataFrame | Path | str
        Either a pre-loaded DataFrame or a path to the N-PORT CSV file.
        When a path is provided, the CSV is loaded directly by DuckDB
        (avoids pandas memory overhead for large files).
    """
    con = duckdb.connect()
    _nport_loaded_from_file = False

    if isinstance(nport_input, (str, Path)):
        _nport_loaded_from_file = True
        nport_path = str(nport_input).replace("\\", "/")
        # Use CREATE TABLE (not VIEW) so DuckDB loads the CSV once into its
        # memory-efficient columnar format.  A VIEW would re-scan the 5 GB+
        # file for every downstream query.
        exclude_clause = ""
        if NPORT_EXCLUDE_CIKS:
            cik_list = ", ".join(f"'{c}'" for c in NPORT_EXCLUDE_CIKS)
            exclude_clause = f"WHERE LTRIM(CAST(cik AS VARCHAR), '0') NOT IN ({cik_list})"
        con.execute(f"""
            CREATE TABLE nport_raw AS
            SELECT * FROM read_csv_auto('{nport_path}',
                                        header=true, all_varchar=true)
            {exclude_clause}
        """)
        row_count = con.execute("SELECT COUNT(*) FROM nport_raw").fetchone()[0]
        logger.info("Preparing N-PORT holdings: %d input rows", row_count)
        if row_count == 0:
            con.close()
            return pd.DataFrame(columns=UNIFIED_COLUMNS)

        # Ensure expected columns exist (handles older nport_holdings.csv)
        existing_cols = {r[0] for r in con.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'nport_raw'"
        ).fetchall()}
        for col in ["are_any_interest_payment",
                     "is_any_portion_interest_paid",
                     "liquidity_classification",
                     "is_default", "currency_code"]:
            if col not in existing_cols:
                con.execute(f"ALTER TABLE nport_raw ADD COLUMN {col} VARCHAR DEFAULT ''")
    else:
        nport_df = nport_input
        # Filter excluded CIKs from DataFrame path too
        if NPORT_EXCLUDE_CIKS and "cik" in nport_df.columns:
            before = len(nport_df)
            nport_df = nport_df[
                ~nport_df["cik"].astype(str).str.lstrip("0").isin(NPORT_EXCLUDE_CIKS)
            ]
            if len(nport_df) < before:
                logger.info("  Excluded %d rows from %d CIKs",
                            before - len(nport_df), len(NPORT_EXCLUDE_CIKS))
        logger.info("Preparing N-PORT holdings: %d input rows", len(nport_df))
        if nport_df.empty:
            con.close()
            return pd.DataFrame(columns=UNIFIED_COLUMNS)

        # Ensure expected columns exist (handles older nport_holdings.csv)
        for col in ["are_any_interest_payment", "is_any_portion_interest_paid",
                     "liquidity_classification", "is_default", "currency_code"]:
            if col not in nport_df.columns:
                nport_df[col] = ""

        con.register("nport_raw", nport_df)

    # Build CASE WHEN for asset_cat mapping
    asset_cases = "\n".join(
        f"        WHEN upper(trim(asset_cat)) = '{code}' THEN '{cat}'"
        for code, cat in _NPORT_ASSET_MAP.items()
    )
    # Build CASE WHEN for issuer_type mapping
    issuer_cases = "\n".join(
        f"        WHEN upper(trim(issuer_type)) = '{code}' THEN '{cat}'"
        for code, cat in _NPORT_ISSUER_MAP.items()
    )

    # Build fund-name keyword SQL for N-PORT fund detection
    fund_kw_checks = " OR ".join(
        f"contains(lower(issuer_name), '{kw}')" for kw in _NPORT_FUND_NAME_KEYWORDS
    )
    # Build credit-fund-name keyword SQL for EC+CORPORATE -> FUND reclassification
    credit_fund_kw_checks = " OR ".join(
        f"contains(lower(issuer_name), '{kw}')" for kw in _NPORT_CREDIT_FUND_NAME_KEYWORDS
    )
    # Build hedge fund exclusion signal checks
    credit_signal_checks = " OR ".join(
        f"contains(lower(CAST(issuer_name AS VARCHAR)), '{s}')" for s in _CREDIT_FUND_SIGNALS
    )
    pe_signal_checks = " OR ".join(
        f"contains(lower(CAST(issuer_name AS VARCHAR)), '{s}')" for s in _PE_FUND_SIGNALS
    )
    # Fall back to issuer_title when issuer_name is NULL/empty (rescues ~9K rows)
    _name_coalesce = "COALESCE(NULLIF(TRIM(CAST(issuer_name AS VARCHAR)), ''), issuer_title)"
    name_norm = _sql_normalize_name(_name_coalesce)

    sql = f"""
    WITH
    -- CTE 1: Filter to Level 3 or NULL/empty fair_value_level
    level3 AS (
        SELECT *, ROW_NUMBER() OVER () AS _row_id
        FROM nport_raw
        WHERE TRY_CAST(fair_value_level AS INTEGER) = 3
           OR fair_value_level IS NULL
           OR TRIM(CAST(fair_value_level AS VARCHAR)) = ''
    ),

    -- CTE 2: Classify assets
    with_asset AS (
        SELECT *,
            CASE
{asset_cases}
                ELSE 'OTHER'
            END AS asset_category
        FROM level3
    ),

    -- CTE 3: Classify issuers
    with_issuer AS (
        SELECT *,
            CASE
{issuer_cases}
                ELSE 'OTHER'
            END AS issuer_category
        FROM with_asset
    ),

    -- CTE 4: RE + FUND -> OTHER; LON/DBT + OTHER -> CORPORATE
    adjusted AS (
        SELECT *,
            CASE
                WHEN asset_cat = 'RE' AND issuer_category = 'FUND' THEN 'OTHER'
                ELSE asset_category
            END AS asset_category_final,
            CASE
                WHEN asset_category IN ('LOAN', 'DEBT') AND issuer_category = 'OTHER'
                    THEN 'CORPORATE'
                ELSE issuer_category
            END AS issuer_category_final
        FROM with_issuer
    ),

    -- CTE 4b: Detect fund-like issuer names in CORP+OTHER holdings
    with_fund_detect AS (
        SELECT *,
            CASE
                WHEN asset_category_final = 'OTHER'
                     AND issuer_category_final = 'CORPORATE'
                     AND (
                         -- L.P. suffix is a strong fund signal (but exclude operating companies)
                         (contains(lower(issuer_name), 'l.p.')
                          AND NOT (contains(lower(issuer_name), 'inc.')
                                OR contains(lower(issuer_name), 'llc')
                                OR contains(lower(issuer_name), 'corp.')))
                         -- Explicit fund keywords
                         OR regexp_matches(lower(issuer_name), '\\bfunds?\\b')
                         OR {fund_kw_checks}
                     )
                THEN 'FUND'
                -- EC+CORPORATE with BDC/credit fund name -> FUND
                WHEN asset_category_final = 'EQUITY_COMMON'
                     AND issuer_category_final = 'CORPORATE'
                     AND ({credit_fund_kw_checks})
                THEN 'FUND'
                ELSE issuer_category_final
            END AS issuer_category_reclassed
        FROM adjusted
    ),

    -- CTE 4c: Exclude hedge fund LP interests
    -- PF+OTHER named holdings with no credit/PE signal are likely hedge funds
    no_hedge_funds AS (
        SELECT * FROM with_fund_detect
        WHERE NOT (
            upper(trim(CAST(issuer_type AS VARCHAR))) = 'PF'
            AND upper(trim(CAST(asset_cat AS VARCHAR))) = 'OTHER'
            AND issuer_name IS NOT NULL
            AND TRIM(CAST(issuer_name AS VARCHAR)) != ''
            AND NOT ({credit_signal_checks})
            AND NOT ({pe_signal_checks})
        )
    ),

    -- CTE 5: Map to unified schema
    unified AS (
        SELECT
            'nport' AS source,
            LPAD(CAST(cik AS VARCHAR), 10, '0') AS cik,
            registrant_name AS entity_name,
            accession_number,
            filing_date,
            report_date,
            {name_norm} AS issuer_name,
            CASE WHEN TRIM(CAST(issuer_name AS VARCHAR)) IS NOT NULL
                      AND TRIM(CAST(issuer_name AS VARCHAR)) != ''
                 THEN issuer_title
                 ELSE '' END AS instrument_description,
            issuer_cusip AS cusip,
            identifier_isin AS isin,
            issuer_lei AS lei,
            identifier_ticker AS ticker,
            TRY_CAST(currency_value AS DOUBLE) AS fair_value,
            NULL AS cost,
            TRY_CAST(percentage AS DOUBLE) AS pct_of_net_assets,
            asset_category_final AS asset_category,
            issuer_category_reclassed AS issuer_category,
            '' AS index_classification,
            CAST(TRY_CAST(fair_value_level AS INTEGER) AS VARCHAR) AS fair_value_level,
            CASE WHEN TRY_CAST(annualized_rate AS DOUBLE) > 50 THEN NULL
                 ELSE TRY_CAST(annualized_rate AS DOUBLE) END AS interest_rate,
            NULL AS basis_spread,
            '' AS reference_rate_type,
            coupon_type,
            NULL AS pik_rate,
            maturity_date,
            CASE WHEN upper(trim(unit)) = 'NS'
                 THEN TRY_CAST(balance AS DOUBLE) END AS shares_held,
            CASE WHEN upper(trim(unit)) = 'PA'
                 THEN TRY_CAST(balance AS DOUBLE) END AS principal_amount,
            '' AS bdc_investment_identifier,
            '' AS bdc_form_type,
            '' AS bdc_dimensions_raw,
            NULL AS bdc_unrealized_gain_loss,
            holding_id AS nport_holding_id,
            series_name AS nport_series_name,
            series_id AS nport_series_id,
            asset_cat AS nport_asset_cat,
            issuer_type AS nport_issuer_type,
            payoff_profile AS nport_payoff_profile,
            investment_country AS nport_investment_country,
            is_restricted_security AS nport_is_restricted,
            quarter AS nport_quarter,
            COALESCE(CAST(is_default AS VARCHAR), '') AS nport_is_default,
            COALESCE(CAST(are_any_interest_payment AS VARCHAR), '') AS nport_are_interest_payments_in_arrears,
            COALESCE(CAST(is_any_portion_interest_paid AS VARCHAR), '') AS nport_is_paid_in_kind,
            COALESCE(CAST(currency_code AS VARCHAR), '') AS nport_currency_code,
            COALESCE(CAST(liquidity_classification AS VARCHAR), '') AS nport_liquidity_classification,
            '' AS entity_id,
            '' AS canonical_name,
            '' AS extracted_industry,
            '' AS position_id,
            _row_id
        FROM no_hedge_funds
    )

    SELECT * FROM unified ORDER BY _row_id
    """

    result = con.execute(sql).fetchdf()

    # Log rate cap stats (count from input, since SQL already capped)
    if _nport_loaded_from_file:
        rate_capped = con.execute(
            "SELECT COUNT(*) FROM nport_raw "
            "WHERE TRY_CAST(annualized_rate AS DOUBLE) > 50"
        ).fetchone()[0]
    else:
        rate_capped = 0
        if "annualized_rate" in nport_df.columns:
            raw_rates = pd.to_numeric(nport_df["annualized_rate"], errors="coerce")
            rate_capped = int((raw_rates > 50).sum())

    con.close()

    # Drop internal row id column
    result.drop(columns=["_row_id"], inplace=True)

    logger.info("  After Level 3 + hedge fund filter: %d rows", len(result))

    if rate_capped > 0:
        logger.info("  N-PORT rates capped at 50%%: %d rows", rate_capped)

    if result.empty:
        return pd.DataFrame(columns=UNIFIED_COLUMNS)

    logger.info("  N-PORT asset breakdown:")
    for cat, count in result["asset_category"].value_counts().items():
        logger.info("    %s: %d (%.1f%%)", cat, count, 100 * count / len(result))

    return result


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def build_unified_holdings(
    bdc_df: Optional[pd.DataFrame] = None,
    nport_df: Optional[pd.DataFrame] = None,
) -> pd.DataFrame:
    """Build unified private markets holdings from BDC + N-PORT data.

    If DataFrames are not provided, reads from disk (BDC_HOLDINGS_FILE,
    NPORT_HOLDINGS_FILE).

    Returns the combined DataFrame and saves to UNIFIED_HOLDINGS_FILE.
    """
    t0 = time.time()

    # Load from disk if not provided
    if bdc_df is None:
        logger.info("Loading BDC holdings from %s", BDC_HOLDINGS_FILE.name)
        bdc_df = pd.read_csv(BDC_HOLDINGS_FILE, dtype=str)
        # Restore numeric columns
        for col in ["fair_value", "cost", "principal_amount", "interest_rate",
                     "basis_spread", "pik_rate", "pct_of_net_assets",
                     "shares_held", "unrealized_gain_loss"]:
            if col in bdc_df.columns:
                bdc_df[col] = pd.to_numeric(bdc_df[col], errors="coerce")
        logger.info("  Loaded %d BDC rows", len(bdc_df))

    # Determine N-PORT input: use file path (DuckDB) for disk loads to avoid
    # pandas OOM on very large CSVs; use DataFrame if already provided.
    nport_input: Union[pd.DataFrame, Path]
    if nport_df is None:
        logger.info("Loading N-PORT holdings from %s (via DuckDB)", NPORT_HOLDINGS_FILE.name)
        nport_input = NPORT_HOLDINGS_FILE
    else:
        nport_input = nport_df

    # Prepare each source
    bdc_unified = _prepare_bdc(bdc_df)
    nport_unified = _prepare_nport(nport_input)

    # Combine via DuckDB UNION ALL + index classification
    con = duckdb.connect()
    con.register("bdc_part", bdc_unified)
    con.register("nport_part", nport_unified)

    idx_case = _sql_classify_index()
    col_list = ", ".join(c for c in UNIFIED_COLUMNS if c != "index_classification")
    # Use explicit column list for UNION ALL to avoid positional mismatch
    union_cols = ", ".join(UNIFIED_COLUMNS)

    sql = f"""
    WITH combined AS (
        SELECT {union_cols} FROM bdc_part
        UNION ALL
        SELECT {union_cols} FROM nport_part
    ),
    -- Cross-source dedup: if the same holding appears in both BDC and N-PORT
    -- (same CIK + period + similar issuer name + similar fair_value),
    -- keep the BDC source row.
    deduped AS (
        SELECT *,
            ROW_NUMBER() OVER (
                PARTITION BY cik, report_date, issuer_name,
                             ROUND(TRY_CAST(fair_value AS DOUBLE), -2)
                ORDER BY
                    CASE WHEN source = 'bdc' THEN 0 ELSE 1 END
            ) AS _dedup_rank
        FROM combined
    ),
    no_dupes AS (
        SELECT * FROM deduped WHERE _dedup_rank = 1
    ),
    with_fund_text AS (
        SELECT *,
            COALESCE(lower(trim(issuer_name)), '') || ' ' ||
            COALESCE(lower(trim(instrument_description)), '') AS _combined_fund_text
        FROM no_dupes
    ),
    classified AS (
        SELECT *,
            {idx_case} AS _index_class
        FROM with_fund_text
    ),
    -- Cost proxy: fill NULL/zero cost with first observed fair_value
    -- for that position (cik + issuer_name), ordered by report_date.
    with_cost AS (
        SELECT * EXCLUDE (cost),
            COALESCE(
                NULLIF(TRY_CAST(cost AS DOUBLE), 0),
                FIRST_VALUE(
                    NULLIF(TRY_CAST(fair_value AS DOUBLE), 0)
                    IGNORE NULLS
                ) OVER (
                    PARTITION BY cik, issuer_name
                    ORDER BY report_date
                    ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING
                )
            ) AS cost
        FROM classified
    ),
    -- Shares normalization: detect power-of-10 unit mismatches within
    -- the same position (cik + issuer_name) by comparing each row's
    -- per-unit price (fair_value / shares_held) against the group median.
    -- Outliers are replaced with the nearest non-outlier shares value.
    with_shares_fix AS (
        SELECT * EXCLUDE (shares_held),
            CASE
                WHEN _is_outlier THEN COALESCE(
                    -- Nearest previous non-outlier shares
                    LAST_VALUE(CASE WHEN NOT _is_outlier THEN _sh_val END
                        IGNORE NULLS) OVER (
                        PARTITION BY cik, issuer_name ORDER BY report_date
                        ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING),
                    -- Nearest following non-outlier shares
                    FIRST_VALUE(CASE WHEN NOT _is_outlier THEN _sh_val END
                        IGNORE NULLS) OVER (
                        PARTITION BY cik, issuer_name ORDER BY report_date
                        ROWS BETWEEN 1 FOLLOWING AND UNBOUNDED FOLLOWING)
                )
                ELSE _sh_val
            END AS shares_held
        FROM (
            SELECT *,
                TRY_CAST(shares_held AS DOUBLE) AS _sh_val,
                TRY_CAST(fair_value AS DOUBLE) AS _fv_val,
                -- Median per-unit price across the group
                MEDIAN(
                    ABS(TRY_CAST(fair_value AS DOUBLE)
                        / NULLIF(TRY_CAST(shares_held AS DOUBLE), 0))
                ) OVER (PARTITION BY cik, issuer_name)
                    AS _med_upx,
                -- Group size (only rows with valid shares)
                COUNT(CASE WHEN TRY_CAST(shares_held AS DOUBLE) IS NOT NULL
                           AND TRY_CAST(shares_held AS DOUBLE) != 0
                           AND TRY_CAST(fair_value AS DOUBLE) IS NOT NULL
                           AND TRY_CAST(fair_value AS DOUBLE) != 0
                      THEN 1 END
                ) OVER (PARTITION BY cik, issuer_name)
                    AS _sh_group_size,
                -- Outlier flag
                (TRY_CAST(shares_held AS DOUBLE) IS NOT NULL
                 AND TRY_CAST(shares_held AS DOUBLE) != 0
                 AND TRY_CAST(fair_value AS DOUBLE) IS NOT NULL
                 AND TRY_CAST(fair_value AS DOUBLE) != 0
                 AND COUNT(CASE WHEN TRY_CAST(shares_held AS DOUBLE) IS NOT NULL
                                AND TRY_CAST(shares_held AS DOUBLE) != 0
                                AND TRY_CAST(fair_value AS DOUBLE) IS NOT NULL
                                AND TRY_CAST(fair_value AS DOUBLE) != 0
                           THEN 1 END
                     ) OVER (PARTITION BY cik, issuer_name) >= 2
                 AND ABS(LOG10(NULLIF(
                     ABS(TRY_CAST(fair_value AS DOUBLE)
                         / TRY_CAST(shares_held AS DOUBLE))
                     / NULLIF(MEDIAN(
                         ABS(TRY_CAST(fair_value AS DOUBLE)
                             / NULLIF(TRY_CAST(shares_held AS DOUBLE), 0))
                       ) OVER (PARTITION BY cik, issuer_name), 0)
                 , 0))) > 1.5
                ) AS _is_outlier
            FROM with_cost
        ) _sh_sub
    )
    SELECT
        {col_list},
        _index_class AS index_classification
    FROM with_shares_fix
    """

    combined = con.execute(sql).fetchdf()

    # Diagnostic: count shares corrections
    try:
        shares_diag = con.execute(f"""
        WITH combined AS (
            SELECT * FROM bdc_part
            UNION ALL
            SELECT * FROM nport_part
        ),
        deduped AS (
            SELECT *,
                ROW_NUMBER() OVER (
                    PARTITION BY cik, report_date, issuer_name,
                                 ROUND(TRY_CAST(fair_value AS DOUBLE), -2)
                    ORDER BY CASE WHEN source = 'bdc' THEN 0 ELSE 1 END
                ) AS _dedup_rank
            FROM combined
        ),
        no_dupes AS (SELECT * FROM deduped WHERE _dedup_rank = 1),
        _sh_check AS (
            SELECT
                TRY_CAST(shares_held AS DOUBLE) AS orig_sh,
                TRY_CAST(fair_value AS DOUBLE) AS fv,
                ABS(TRY_CAST(fair_value AS DOUBLE)
                    / NULLIF(TRY_CAST(shares_held AS DOUBLE), 0)) AS _upx,
                MEDIAN(ABS(TRY_CAST(fair_value AS DOUBLE)
                    / NULLIF(TRY_CAST(shares_held AS DOUBLE), 0)))
                    OVER (PARTITION BY cik, issuer_name) AS _med_upx,
                COUNT(CASE WHEN TRY_CAST(shares_held AS DOUBLE) IS NOT NULL
                           AND TRY_CAST(shares_held AS DOUBLE) != 0
                           AND TRY_CAST(fair_value AS DOUBLE) IS NOT NULL
                           AND TRY_CAST(fair_value AS DOUBLE) != 0
                      THEN 1 END) OVER (PARTITION BY cik, issuer_name) AS _grp
            FROM no_dupes
            WHERE TRY_CAST(shares_held AS DOUBLE) IS NOT NULL
              AND TRY_CAST(shares_held AS DOUBLE) != 0
              AND TRY_CAST(fair_value AS DOUBLE) IS NOT NULL
              AND TRY_CAST(fair_value AS DOUBLE) != 0
        )
        SELECT COUNT(*) AS n_corrected,
               COUNT(DISTINCT orig_sh) AS n_distinct
        FROM _sh_check
        WHERE _grp >= 2
          AND ABS(LOG10(_upx / NULLIF(_med_upx, 0))) > 1.5
        """).fetchone()
        if shares_diag and shares_diag[0] > 0:
            logger.info("  Shares normalization: corrected %d rows (%d distinct original values)",
                        shares_diag[0], shares_diag[1])
    except Exception:
        pass  # Diagnostic only, don't fail the pipeline

    con.close()

    # Ensure column order
    combined = combined[[c for c in UNIFIED_COLUMNS if c in combined.columns]]
    for col in UNIFIED_COLUMNS:
        if col not in combined.columns:
            combined[col] = ""
    combined = combined[UNIFIED_COLUMNS]

    pre_dedup = len(bdc_unified) + len(nport_unified)
    dedup_removed = pre_dedup - len(combined)
    logger.info("Combined: %d total rows (BDC %d + N-PORT %d, %d cross-source dupes removed)",
                len(combined), len(bdc_unified), len(nport_unified), dedup_removed)

    # Entity enrichment: join against existing entity_lookup if available
    if ENTITY_LOOKUP_FILE.exists():
        con2 = duckdb.connect()
        con2.register("holdings", combined)
        lookup_str = str(ENTITY_LOOKUP_FILE).replace("\\", "/")
        combined = con2.execute(f"""
            SELECT h.* EXCLUDE (entity_id, canonical_name),
                   COALESCE(e.entity_id, '') AS entity_id,
                   COALESCE(e.canonical_name, '') AS canonical_name
            FROM holdings h
            LEFT JOIN read_csv_auto('{lookup_str}',
                          header=true, all_varchar=true) e
              ON CAST(h.issuer_name AS VARCHAR) = e.issuer_name_variant
              AND CAST(h.source AS VARCHAR) = e.source
        """).fetchdf()
        con2.close()
        # Re-apply column order (EXCLUDE moves columns to end)
        combined = combined[UNIFIED_COLUMNS]
        eid_count = (combined["entity_id"] != "").sum()
        logger.info("Entity enrichment: %d/%d rows (%.1f%%) with entity_id",
                     eid_count, len(combined),
                     100 * eid_count / len(combined) if len(combined) else 0)

    # Industry enrichment: join against identifier_extraction_lookup if available
    if IDENTIFIER_EXTRACTION_LOOKUP_FILE.exists():
        con3 = duckdb.connect()
        con3.register("holdings", combined)
        ilookup_str = str(IDENTIFIER_EXTRACTION_LOOKUP_FILE).replace("\\", "/")
        combined = con3.execute(f"""
            SELECT h.* EXCLUDE (extracted_industry),
                   CASE
                       WHEN (h.extracted_industry IS NULL
                             OR CAST(h.extracted_industry AS VARCHAR) = '')
                            AND e.extracted_industry IS NOT NULL
                            AND e.extracted_industry != ''
                            AND e.extracted_industry != 'None'
                       THEN e.extracted_industry
                       ELSE COALESCE(h.extracted_industry, '')
                   END AS extracted_industry
            FROM holdings h
            LEFT JOIN read_csv_auto('{ilookup_str}',
                          header=true, all_varchar=true) e
              ON CAST(h.bdc_investment_identifier AS VARCHAR)
               = CAST(e.bdc_investment_identifier AS VARCHAR)
        """).fetchdf()
        con3.close()
        combined = combined[UNIFIED_COLUMNS]
        ind_count = (combined["extracted_industry"] != "").sum()
        logger.info("Industry enrichment: %d/%d rows (%.1f%%) with extracted_industry",
                     ind_count, len(combined),
                     100 * ind_count / len(combined) if len(combined) else 0)

    # Log cost proxy stats
    cost_filled = combined["cost"].notna() & (combined["cost"] != 0)
    logger.info("  Cost coverage: %d rows (%.1f%%)",
                cost_filled.sum(), 100 * cost_filled.sum() / len(combined) if len(combined) else 0)

    # Save
    combined.to_csv(UNIFIED_HOLDINGS_FILE, index=False)
    logger.info("Saved to %s (%.1f MB)",
                UNIFIED_HOLDINGS_FILE.name,
                UNIFIED_HOLDINGS_FILE.stat().st_size / (1024 * 1024))

    # Log summary statistics
    _log_summary(combined)

    elapsed = time.time() - t0
    logger.info("Unified holdings built in %.1f s", elapsed)

    return combined


def _log_summary(df: pd.DataFrame) -> None:
    """Log summary statistics about the unified dataset."""
    total = len(df)
    bdc_count = (df["source"] == "bdc").sum()
    nport_count = (df["source"] == "nport").sum()

    logger.info("")
    logger.info("Unified holdings: %d total", total)
    logger.info("  BDC:    %d (%.1f%%)", bdc_count, 100 * bdc_count / total if total else 0)
    logger.info("  N-PORT: %d (%.1f%%)", nport_count, 100 * nport_count / total if total else 0)

    logger.info("")
    logger.info("By index:")
    for idx_name, count in df["index_classification"].value_counts().items():
        logger.info("  %-25s %d (%.1f%%)", idx_name + ":", count, 100 * count / total)

    logger.info("")
    logger.info("Analytics coverage:")
    for col, label in [
        ("interest_rate", "interest_rate filled"),
        ("basis_spread", "basis_spread filled (BDC only)"),
        ("reference_rate_type", "reference_rate_type filled"),
        ("cost", "cost filled (BDC real + N-PORT proxy)"),
        ("maturity_date", "maturity_date filled"),
        ("principal_amount", "principal_amount filled"),
        ("shares_held", "shares_held filled"),
        ("pct_of_net_assets", "pct_of_net_assets"),
    ]:
        if col in df.columns:
            filled = df[col].notna() & (df[col] != "") & (df[col] != 0)
            pct = 100 * filled.sum() / total if total else 0
            logger.info("  %-30s %.1f%%", label + ":", pct)

    # Quarter range
    quarters = set()
    # From N-PORT quarter column
    nport_q = df.loc[df["nport_quarter"] != "", "nport_quarter"].dropna().unique()
    quarters.update(nport_q)
    # From BDC report_date -> approximate quarter
    bdc_dates = df.loc[df["source"] == "bdc", "report_date"].dropna()
    for d in bdc_dates.unique():
        try:
            dt = pd.to_datetime(d)
            q = f"{dt.year}q{(dt.month - 1) // 3 + 1}"
            quarters.add(q)
        except (ValueError, TypeError):
            pass

    if quarters:
        sorted_q = sorted(quarters)
        logger.info("  Quarters covered: %s - %s", sorted_q[0], sorted_q[-1])
