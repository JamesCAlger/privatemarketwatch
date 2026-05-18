"""BDC identifier parsing and aggregate-row detection."""

from __future__ import annotations

import re

from pipeline.classification import (
    _BAD_ISSUER_ENTITY_SIGNALS,
    _BAD_ISSUER_NAMES_EXACT,
    _BAD_ISSUER_PREFIXES,
    _INDUSTRY_LABELS,
    _LEGAL_SUFFIX_RE_SQL,
    _PIPE_INSTRUMENT_KEYWORDS,
    _sql_ends_with_any,
    _sql_exact_match,
    _sql_keyword_check,
    _sql_starts_with_any,
)


_BDC_AGGREGATE_PATTERNS = [
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
    # NOTE: "investments investments" removed from patterns -- it appears in real
    # dimension-path identifiers (CIK 1849894, 1899996, 1920453, etc.) containing
    # company names. Handled by entity-signal-gated category prefix logic below.
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
    "sub total",
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
    # Affiliation-category subtotals (2026-05-06 audit)
    "investments in non-controlled",
    "investments in non-affiliated",
    "investments in affiliated",
    # Dimension-path subtotals (CIK 1959604/1959568)
    "total non-controlled",
    "total non-affiliated",
    # PennantPark/similar: percentage-prefix category headers without slash
    "common equity/partnership interests",
    "partnership interests/warrants",
]

# Bare issuer names that are section headers or industry labels (exact match, lower)
_BDC_AGGREGATE_EXACT = {
    "investments", "debt investments", "equity securities",
    "equity investments", "cash equivalents", "cash",
    "affiliate investments", "affiliated investments",
    "affiliate investments at fair value",
    "affiliated investments at fair value",
    "control investments", "controlled investments",
    "control investments at fair value",
    "controlled investments at fair value",
    "non-affiliate investments", "non-affiliated investments",
    "non-control/non-affiliate investments",
    "non-controlled/non-affiliated investments",
    "controlled affiliated investments",
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
    # Category-level subtotals from Carlyle/SL Investment (2026-05-06 audit)
    "senior secured debt",
    "first lien debt",
    "second lien debt",
    "subordinated debt",
    "mezzanine debt",
    "investments debt investments",
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

_AFFILIATION_PREFIX_RE = (
    r"(?i)^(?:"
    r"Non-Control(?:led)?(?:[/,] ?Non-Affiliat(?:e|ed))? Investments"
    r"|Control(?:led)? Investments"
    r"|Affiliat(?:e|ed) Investments"
    r"|Investments in (?:Non-)?Control(?:led)?(?:[,/] ?(?:Non-)?Affiliat(?:e|ed))?"
    r" Portfolio Companies"
    r")"
    "(?:\\s*-\\s*|\\s*\u2014\\s*|\\s+)"
)
_AFFILIATION_SUFFIX_RE = (
    r"(?i) - (?:Non-Control(?:led)?(?:[/,] ?Non-Affiliat(?:e|ed))?"
    r"|Control(?:led)?|Affiliat(?:e|ed))$"
)

# Entity signals that indicate a real company name (guards for prefix filter)

_AFFILIATION_TAGS = {
    "non-affiliated issuer", "affiliated issuer",
    "non-affiliated", "affiliated", "controlled",
    "non-control/non-affiliate", "control", "affiliate",
}

# Instrument-type keywords for 3-pipe format detection.  When segment 3
# matches one of these, it is an instrument description, NOT a company name.

_QTY_PREFIX_RE = re.compile(r"^\$?[\d,.]+ ?")

def _is_bad_issuer_name(issuer_name: str) -> bool:
    """Python mirror of _sql_is_bad_issuer_name for tests."""
    if not issuer_name or not isinstance(issuer_name, str):
        return False
    name = issuer_name.strip().rstrip(",").rstrip(";").strip()
    lower = name.lower()
    # Rule 1: exact match
    if lower in _BAD_ISSUER_NAMES_EXACT:
        return True
    # Rule 2: no alphabetic characters
    if len(name) >= 1 and not re.search(r"[a-zA-Z]", name):
        return True
    # Rule 3: bad prefix without entity signals
    for prefix in _BAD_ISSUER_PREFIXES:
        if lower.startswith(prefix):
            if not any(s in lower for s in _BAD_ISSUER_ENTITY_SIGNALS):
                return True
    return False


def _sql_is_bdc_aggregate() -> str:
    """Generate SQL boolean expression for aggregate row detection.

    Mirrors _is_bdc_aggregate_row() Python logic. Entity-signal guard prevents
    filtering real positions that embed aggregate-sounding category names in
    their dimension paths.
    """
    # ------------------------------------------------------------------
    # Entity signal: if the identifier contains a company name suffix
    # (LLC, Inc, Corp, etc.), most aggregate checks are skipped.
    # ------------------------------------------------------------------
    _entity_signals = [
        "inc.", "inc,", " inc ", " inc-",
        "llc", "l.l.c",
        "corp.", "corp,",
        "ltd.", "ltd,", " ltd ",
        ", lp", " lp,", "l.p.",
        "holdings", "group",
        "gmbh", " co.", " plc",
    ]
    has_entity_sql = " OR ".join(
        f"contains(_lower_id, '{s}')" for s in _entity_signals
    )
    has_entity = f"({has_entity_sql})"
    no_entity = f"NOT {has_entity}"

    parts = []
    # NULL/empty identifiers are always aggregates
    parts.append("_lower_id = ''")
    # Unconditional: [member] tag always means aggregate
    parts.append("contains(_lower_id, '[member]')")
    # Named aggregate patterns -- only when no entity signals
    parts.append(f"({no_entity} AND ({_sql_keyword_check('_lower_id', _BDC_AGGREGATE_PATTERNS)}))")
    # Qualified non-control check
    parts.append(
        f"(contains(_lower_id, 'non-control') AND LENGTH(_raw_id) < 150 AND {no_entity})"
    )
    # Exact match section headers (always apply -- short strings won't have entity signals)
    parts.append(_sql_exact_match("_lower_id", _BDC_AGGREGATE_EXACT))
    # Category header prefixes (only when no entity signals and no separators)
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
    parts.append(f"({no_entity} AND NOT contains(_raw_id, ' - ') AND NOT contains(_raw_id, ' -- ') AND {cat_sql})")
    # Identifiers ending with a percentage -- only when no entity signals
    parts.append(f"({no_entity} AND regexp_matches(_lower_id, '\\d+\\.?\\d*%\\s*$'))")
    # "Total ..." industry subtotals: starts with "total " but does NOT contain
    # any company suffix
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
    # Also catch pipe-delimited subtotals where "Total X" is in the last segment
    last_seg = "trim(string_split(_lower_id, ' | ')[-1])"
    last_seg_guards = " AND ".join(
        f"NOT contains({last_seg}, '{s}')" for s in _total_company_signals
    )
    parts.append(
        f"(contains(_lower_id, ' | ') AND starts_with({last_seg}, 'total ') "
        f"AND {last_seg_guards})"
    )
    # Percentage-prefix category subtotals: starts with "NNN.NN% " followed by
    # slash-separated category terms (no entity signals, no dash separators).
    # Example: "177.4% Common Equity/Partnership Interests/Warrants"
    pct_prefix = "regexp_matches(_lower_id, '^\\d[\\d.]*%\\s+')"
    has_slash = "contains(_lower_id, '/')"
    no_dash = "NOT contains(_raw_id, ' - ') AND NOT contains(_raw_id, ' -- ')"
    parts.append(f"({pct_prefix} AND {no_entity} AND {no_dash} AND {has_slash})")
    # Industry-prefixed subtotals -- only when no entity signals
    suffix_sql = _sql_ends_with_any("_lower_id", _BDC_AGGREGATE_SUFFIXES)
    parts.append(f"({no_entity} AND {suffix_sql})")
    # Single-word industry/geography labels
    single_word_labels = sorted(v for v in _INDUSTRY_LABELS if " " not in v)
    multi_word_labels = sorted(v for v in _INDUSTRY_LABELS if " " in v)
    if single_word_labels:
        parts.append(f"(NOT contains(_lower_id, ' ') AND {_sql_exact_match('_lower_id', set(single_word_labels))})")
    if multi_word_labels:
        parts.append(_sql_exact_match("_lower_id", set(multi_word_labels)))
    return " OR ".join(parts)



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

    # Normalise em-dash (U+2014) and en-dash (U+2013) before splitting
    identifier = identifier.replace("\u2014", " - ")
    identifier = identifier.replace("\u2013", "-")

    _GS_PCT_RE = re.compile(r"^-?\d[\d.]*%\s+\S")
    _GS_KEYWORD_RE = re.compile(
        r"^(.+?)\s+(?:Industry|Interest Rate|Reference Rate|Maturity|Floor|PIK)\b"
    )
    # Extended keyword boundary for pct-prefix extraction (adds Current Coupon, Basis Point)
    _PCT_KEYWORD_RE = re.compile(
        r"^(.+?)\s+(?:Industry|Interest Rate|Current Coupon|Maturity"
        r"|Reference Rate|Basis Point|Floor|PIK)(?:\s|$)"
    )
    _PCT_PREFIX_RE = re.compile(r"^\d[\d.]*%\s+")
    # Entity signals for pct-prefix guard (same list used in aggregate detection)
    _pct_entity_sigs = [
        "inc.", "inc,", " inc ", " inc-",
        "llc", "l.l.c", "corp.", "corp,",
        "ltd.", "ltd,", " ltd ", ", lp", " lp,", "l.p.",
        "holdings", "group", "gmbh", " co.", " plc",
    ]

    if " - " not in identifier:
        # Goldman Sachs 1-segment (no dash): "Investment <type> <pct>% <co> Industry ..."
        if identifier.lower().strip().startswith("investment ") and re.search(
            r"\d[\d.]*%\s+\S", identifier
        ):
            text = re.sub(r"^.*?\d[\d.]*%\s+", "", identifier.strip())
            m = _GS_KEYWORD_RE.match(text)
            issuer = m.group(1) if m else text
            # instrument: text between "Investment " and the percentage
            inst_text = re.sub(r"^investment\s+", "", identifier.strip(), flags=re.IGNORECASE)
            inst_m = re.match(r"^(.+?)\s+\d[\d.]*%", inst_text)
            instrument = inst_m.group(1) if inst_m else ""
            return (issuer, instrument)
        # No-dash "Issuer Name" label format (PennantPark variant):
        # "Common Equity/... Issuer Name SP L2 Holdings, LLC Industry ..."
        # Guard: must NOT start with "investment " (Goldman Sachs format)
        stripped = identifier.strip()
        if (not stripped.lower().startswith("investment ")
                and re.search(r"(?i)\bissuer name\s+", stripped)):
            # Extract company name after "Issuer Name" label
            after_label = re.split(r"(?i)\bIssuer Name\s+", stripped, maxsplit=1)
            if len(after_label) == 2:
                company_text = after_label[1]
                m = _PCT_KEYWORD_RE.match(company_text)
                issuer = m.group(1).strip() if m else company_text.strip()
                instrument = after_label[0].strip()
                # Strip pct prefix from instrument if present
                instrument = _PCT_PREFIX_RE.sub("", instrument).strip()
                return (issuer, instrument)
        return (identifier.strip(), "")

    segments = identifier.split(" - ")
    first_seg = segments[0].strip()

    # Industry-prefix detection: if first segment is a known label and 3+ segments
    if first_seg.lower() in _INDUSTRY_LABELS and len(segments) >= 3:
        issuer = segments[1].strip()
        instrument = " - ".join(s.strip() for s in segments[2:])
        instrument = _QTY_PREFIX_RE.sub("", instrument).strip()
        return (issuer, instrument)

    # Pct-prefix category skip (PennantPark / Blue Owl):
    # seg[1] = "NNN.N% Category Name", seg[2] = "NNN.N% Company ... Industry ..."
    # Condition: seg[1] starts with pct prefix, has NO entity signals, and
    # seg[2] also starts with pct prefix (confirming hierarchical pct format).
    # Entity signal in seg[1] means it's a real company name like "150% Acme LLC"
    # -- NOT a category prefix -- so we skip this branch.
    if (len(segments) >= 2
            and _PCT_PREFIX_RE.match(first_seg)
            and not any(s in first_seg.lower() for s in _pct_entity_sigs)):
        seg2 = segments[1].strip()
        # Blue Owl CIK 1817825: seg[2] = "Investments made in <Country>"
        if seg2.lower().startswith("investments made in") and len(segments) >= 4:
            # seg[3] might be industry or company; seg[4] might be company
            seg3 = segments[2].strip()
            if seg3.lower() in _INDUSTRY_LABELS and len(segments) >= 5:
                issuer = segments[3].strip()
                instrument = " - ".join(s.strip() for s in segments[4:])
            else:
                issuer = seg3
                instrument = " - ".join(s.strip() for s in segments[3:])
            # Category from seg[1] (minus pct prefix)
            category = _PCT_PREFIX_RE.sub("", first_seg).strip()
            if category:
                instrument = category + " - " + instrument if instrument else category
            return (issuer, instrument)
        # Standard PennantPark: seg[2] starts with pct prefix
        if _PCT_PREFIX_RE.match(seg2):
            # Strip pct prefix from seg[2] to get company text
            company_text = _PCT_PREFIX_RE.sub("", seg2).strip()
            # Strip "Issuer Name " label if present
            company_text = re.sub(
                r"^Issuer Name\s+", "", company_text, flags=re.IGNORECASE
            )
            # Extract company via keyword boundary
            m = _PCT_KEYWORD_RE.match(company_text)
            issuer = m.group(1).strip() if m else company_text
            # Instrument = category from seg[1] (minus pct) + remaining segments
            category = _PCT_PREFIX_RE.sub("", first_seg).strip()
            rest = " - ".join(s.strip() for s in segments[2:])
            instrument = category if category else rest
            return (issuer, instrument)

    # Goldman Sachs hierarchical format (2-4 segments):
    # seg[1] starts with "Investment ", last segment has "<pct>% <company> Industry ..."
    if (len(segments) >= 2
            and first_seg.lower().startswith("investment ")
            and _GS_PCT_RE.match(segments[-1].strip())):
        last_text = re.sub(r"^-?\d[\d.]*%\s+", "", segments[-1].strip())
        m = _GS_KEYWORD_RE.match(last_text)
        issuer = m.group(1) if m else last_text
        # instrument: seg[1] minus "Investment " prefix
        instrument = re.sub(r"^investment\s+", "", first_seg, flags=re.IGNORECASE)
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

    Many BDCs use hierarchical XBRL dimension paths that embed category names
    (e.g., "Investments Non-Controlled First Lien Debt") followed by the actual
    company name, rate, maturity, etc. Entity-name signals (LLC, Inc, Corp, etc.)
    are the strongest indicator that an identifier represents a real position.

    Filters:
    1. Named aggregate substring patterns (e.g., "total investments")
    2. Exact-match section headers (e.g., "Investments", "Debt Investments")
    3. Single-word industry/geography labels (e.g., "Insurance", "Canada")
    4. "Debt Investments XXX" category headers (e.g., "Debt Investments Software")
    """
    if not identifier or not isinstance(identifier, str):
        return True

    lower = identifier.lower().strip()

    # ------------------------------------------------------------------
    # Entity-signal guard: identifiers containing company name suffixes
    # are almost always real positions, even if they contain aggregate-
    # sounding substrings (e.g., "1st Lien/Senior Secured Debt" embedded
    # in "Investment 1st Lien/Senior Secured Debt Acme LLC Term Loan").
    # Only truly unambiguous aggregate markers ([member], "total investments",
    # percentage endings) can override this guard.
    # ------------------------------------------------------------------
    _entity_signals = [
        "inc.", "inc,", " inc ", " inc-",
        "llc", "l.l.c",
        "corp.", "corp,",
        "ltd.", "ltd,", " ltd ",
        ", lp", " lp,", "l.p.",
        "holdings", "group",
        "gmbh", " co.", " plc",
    ]
    has_entity = any(s in lower for s in _entity_signals)

    # Unconditional aggregate markers (override entity guard)
    if "[member]" in lower:
        return True

    # Named aggregate patterns — only apply to identifiers WITHOUT entity signals
    if not has_entity:
        for pattern in _BDC_AGGREGATE_PATTERNS:
            if pattern in lower:
                return True

    # Qualified non-control check: filter identifiers with "non-control" that are
    # short (<150 chars) and lack entity-name signals.
    if "non-control" in lower:
        if len(identifier.strip()) < 150 and not has_entity:
            return True

    # Exact match section headers
    if lower in _BDC_AGGREGATE_EXACT:
        return True

    # Category headers: "Debt Investments <Industry>", "Debt Securities <Industry>",
    # "Equity Securities <Industry>", "Investment <Type>" etc.
    # These have no ' - ' or ' -- ' separator and are always subtotals.
    # Only apply when no entity signals present.
    if not has_entity and " - " not in identifier and " -- " not in identifier:
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
    # Exception: entity-signal identifiers that happen to embed a pct-of-NAV
    # in the dimension path (e.g., "Investments 176% of Net Assets, Company LLC")
    if not has_entity and re.search(r"\d+\.?\d*%\s*$", lower):
        return True

    # Industry-prefixed subtotals: identifier ends with instrument type
    # (real positions always have rate/maturity after)
    if not has_entity:
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

    # Percentage-prefix category subtotals: starts with "NNN.NN% " followed by
    # slash-separated category terms (no entity signals, no dash separators).
    # Example: "177.4% Common Equity/Partnership Interests/Warrants"
    if (not has_entity
            and re.match(r"^\d[\d.]*%\s+", lower)
            and " - " not in identifier and " -- " not in identifier
            and "/" in lower):
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
