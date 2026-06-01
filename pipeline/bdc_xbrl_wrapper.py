"""Per-CIK XBRL identifier wrappers used by BDC source reconciliation.

Wrappers classify raw filing identifiers into deterministic signatures without
mutating published holdings rows.  They are diagnostics and reconciliation
helpers; global parser/staging defects should still be fixed globally.

Wrapper specs are loaded from v3 JSON definitions in
data/overrides/bdc_xbrl_wrappers/.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import logging
import re
import unicodedata
from pathlib import Path
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)

WRAPPER_COLUMNS = [
    "wrapper_version",
    "wrapper_rule_id",
    "wrapper_family",
    "wrapper_disposition",
    "wrapper_position_key",
    "wrapper_parent_key",
    "wrapper_structured_leaf_key",
    "wrapper_investment_date_key",
    "wrapper_maturity_date_key",
    "wrapper_rate_key",
    "wrapper_signature_status",
    "wrapper_unparsed_remainder",
]

DEFAULT_LEAF_MARKERS_BY_FAMILY = {
    "debt": (
        "type of investment",
        "investment type",
        "investment date",
        "initial acquisition date",
        "maturity date",
        "maturity",
        "interest rate",
        "reference rate",
        "reference rate and spread",
        "current coupon",
        "sofr",
        "libor",
        "euribor",
        "first lien",
        "1st lien",
        "second lien",
        "term loan",
        "revolving credit facility",
        "delayed draw",
        "senior secured",
        "floor rate",
        "pik interest",
    ),
    "equity": (
        "type of investment",
        "investment type",
        "investment date",
        "initial acquisition date",
        "common stock",
        "common equity",
        "preferred stock",
        "preferred equity",
        "preferred units",
        "partnership interest",
    ),
    "warrant": (
        "type of investment",
        "investment type",
        "investment date",
        "expiration date",
        "expirationdate",
        "warrant",
    ),
    "mixed": (
        "type of investment",
        "investment type",
        "investment date",
        "initial acquisition date",
        "maturity date",
        "maturity",
        "interest rate",
        "reference rate",
        "current coupon",
        "first lien",
        "1st lien",
        "second lien",
        "term loan",
        "revolving credit facility",
        "delayed draw",
        "senior secured",
        "floor rate",
        "pik interest",
        "common stock",
        "common units",
        "common equity",
        "preferred stock",
        "preferred units",
        "limited partner interests",
        "partnership interest",
        "term loan",
        "warrant",
    ),
}

DEFAULT_ENTITY_SIGNALS_RE = re.compile(
    r"\b(?:inc|incorporated|llc|l\.l\.c|corp|corporation|co|company|ltd|limited|"
    r"holdings|holding|holding\s+company|partners|group|lp|l\.p|plc|sa|s\.a|"
    r"s\.r\.l|ag|bv|b\.v|gmbh|pty|pbc|bidco|midco|topco|investco)\b",
    re.IGNORECASE,
)

_LEAF_MARKER_RE = re.compile(
    r"(type\s+of\s+investment|investment\s+type|initial\s+acquisition\s+date|"
    r"investment\s+date|maturity\s*date|expiration\s*date|maturity\b|"
    r"variable\s+interest\s+rate|fixed\s+interest\s+rate|pik\s+interest\s+rate|"
    r"reference\s+rate(?:\s+and\s+spread)?|current\s+coupon|interest\s*rate|"
    r"\bsofr\b|\blibor\b|\beuribor\b)",
    re.IGNORECASE,
)
_DATE_VALUE_PATTERNS = {
    "investment": re.compile(
        r"(?:investment\s+date|initial\s+acquisition\s+date)\s+(.*?)(?=type\s+of\s+investment|"
        r"investment\s+type|maturity\s*date|expiration\s*date|maturity\b|"
        r"variable\s+interest\s+rate|fixed\s+interest\s+rate|pik\s+interest\s+rate|"
        r"reference\s+rate(?:\s+and\s+spread)?|current\s+coupon|interest\s*rate|$)",
        re.IGNORECASE | re.DOTALL,
    ),
    "maturity": re.compile(
        r"(?:maturity\s*date|expiration\s*date|maturity)\s+(.*?)(?=type\s+of\s+investment|"
        r"investment\s+type|investment\s+date|initial\s+acquisition\s+date|"
        r"variable\s+interest\s+rate|fixed\s+interest\s+rate|pik\s+interest\s+rate|"
        r"reference\s+rate(?:\s+and\s+spread)?|current\s+coupon|interest\s*rate|$)",
        re.IGNORECASE | re.DOTALL,
    ),
}
_RATE_VALUE_RE = re.compile(
    r"(?:variable\s+interest\s+rate|fixed\s+interest\s+rate|pik\s+interest\s+rate|"
    r"reference\s+rate(?:\s+and\s+spread)?|current\s+coupon|interest\s*rate|"
    r"\bsofr\b|\blibor\b|\beuribor\b)\s+(.*)$",
    re.IGNORECASE | re.DOTALL,
)
_DASH_TRANSLATION = str.maketrans({
    "\u2010": "-",
    "\u2011": "-",
    "\u2012": "-",
    "\u2013": "-",
    "\u2014": "-",
    "\u2212": "-",
})


def normalize_wrapper_identifier(value: Any) -> str:
    """Normalize filing identifier text for wrapper diagnostics only."""
    text = "" if value is None else str(value).strip()
    text = unicodedata.normalize("NFKC", text)
    text = text.replace("\u00a0", " ")
    text = text.replace("\u00c2", "")
    text = text.replace("\u00e2\u0080\u0093", "-").replace("\u00e2\u0080\u0094", "-")
    text = text.replace("\u00ef\u00bb\u00bf", "")
    text = re.sub(r"[\u200b-\u200d\ufeff]", "", text)
    text = text.translate(_DASH_TRANSLATION)
    text = re.sub(r"\s+-\s+", " - ", text)
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(
        r"^Investment Debt InveInvestment Debt Investments",
        "Investment Debt Investments",
        text,
        flags=re.IGNORECASE,
    )
    return text


@dataclass(frozen=True)
class WrapperSpec:
    cik: str
    rule_prefix: str
    version: str
    prefix_rules: dict[str, str]
    leaf_markers_by_family: dict[str, tuple[str, ...]]
    entity_signals_re: re.Pattern[str] = DEFAULT_ENTITY_SIGNALS_RE
    aggregate_markers: tuple[str, ...] = (
        "sub-total",
        "subtotal",
        "total investments",
        "total debt investments",
        "total equity investments",
        "portfolio investments",
    )
    non_private_markers: tuple[str, ...] = (
        "cash",
        "money market",
        "financial square",
        "government institutional",
        "u.s. treasury",
        "us treasury",
    )
    category_marker_re: re.Pattern[str] | None = field(default=None)
    fallback_family_patterns: tuple[tuple[re.Pattern[str], str], ...] = ()
    canonical_strip_re: re.Pattern[str] | None = None
    no_prefix_is_aggregate: bool = False

    def normalized_cik(self) -> str:
        return normalize_cik(self.cik)


def normalize_cik(value: Any) -> str:
    digits = re.sub(r"\D+", "", "" if value is None else str(value))
    return digits.zfill(10) if digits else ""


def normalize_key(value: Any) -> str:
    text = normalize_wrapper_identifier(value)
    text = unicodedata.normalize("NFKD", text)
    text = re.sub(r"[^A-Za-z0-9]+", " ", text).lower()
    return re.sub(r"\s+", " ", text).strip()


def is_non_private_market_identifier(identifier: Any, markers: tuple[str, ...] | None = None) -> bool:
    """Return True for cash, money-market, Treasury, and mutual-fund rows.

    The cash check is intentionally bounded. Valid BDC loan rows commonly
    disclose coupon mix as "Cash + PIK"; those are position-level facts, not
    cash equivalents.
    """
    raw = normalize_wrapper_identifier(identifier)
    lowered = raw.lower()
    marker_values = markers or (
        "money market",
        "financial square",
        "government institutional",
        "u.s. treasury",
        "us treasury",
        "mutual fund",
        "floating rate central fund",
        "high income central fund",
    )
    for marker in marker_values:
        if marker == "cash":
            continue
        if marker in lowered:
            return True
    if "cash +" in lowered or "total coupon" in lowered or "coupon" in lowered:
        return False
    return bool(re.search(
        r"(?:^|[^a-z])(?:total\s+)?cash(?:\s+and\s+cash\s+equivalents|\s+equivalents|\s+accounts)?(?:[^a-z]|$)",
        lowered,
    ))


def _parent_text(identifier: str) -> str:
    marker = _LEAF_MARKER_RE.search(identifier)
    if marker:
        return identifier[: marker.start()]
    return identifier


def _family_for_identifier(spec: WrapperSpec, identifier: str) -> tuple[str, str]:
    for prefix, family in spec.prefix_rules.items():
        if identifier.startswith(prefix):
            return prefix, family
    # Try fallback patterns (replaces Saratoga-specific hardcoded checks)
    for pattern, family in spec.fallback_family_patterns:
        if pattern.match(identifier):
            return "", family
    return "", ""


def _has_leaf_marker(spec: WrapperSpec, identifier: str, family: str) -> bool:
    compact = re.sub(r"[^a-z0-9]+", "", identifier.lower())
    lower = identifier.lower()
    markers = spec.leaf_markers_by_family.get(family, ())
    return any(marker in lower or marker.replace(" ", "") in compact for marker in markers)


def _rule_id(spec: WrapperSpec, family: str, suffix: str) -> str:
    return f"{spec.rule_prefix}_{family.upper()}_{suffix}_V{spec.version}"


def _rollup_disposition(
    spec: WrapperSpec,
    identifier: str,
    parent_key: str,
    family: str,
    prefix_text: str,
) -> tuple[str, str]:
    normalized = normalize_key(identifier)
    suffix = normalized
    prefix_key = normalize_key(prefix_text)
    if prefix_key and suffix.startswith(prefix_key):
        suffix = suffix[len(prefix_key):].strip()
    suffix_text = identifier[len(prefix_text):] if prefix_text and identifier.startswith(prefix_text) else identifier
    lowered = identifier.lower()
    if is_non_private_market_identifier(identifier, spec.non_private_markers):
        return "non_private_market", _rule_id(spec, family, "NON_PRIVATE_MARKET")
    if re.search(r"(?:^| )sub total(?: |$)", normalized) or re.search(r"(?:^| )subtotal(?: |$)", normalized):
        return f"{family}_total_rollup", _rule_id(spec, family, "TOTAL_ROLLUP")
    if re.search(r"(?:^| )total(?: |$)", suffix):
        return f"{family}_total_rollup", _rule_id(spec, family, "TOTAL_ROLLUP")
    if any(marker in lowered for marker in spec.aggregate_markers):
        return "aggregate", _rule_id(spec, family, "AGGREGATE")
    if spec.no_prefix_is_aggregate and not prefix_text:
        return "aggregate", _rule_id(spec, family, "AGGREGATE")
    if spec.entity_signals_re.search(suffix_text):
        return f"{family}_issuer_rollup", _rule_id(spec, family, "ISSUER_ROLLUP")
    if spec.category_marker_re and spec.category_marker_re.search(suffix_text):
        return "aggregate", _rule_id(spec, family, "AGGREGATE")
    if parent_key:
        return f"{family}_category_rollup", _rule_id(spec, family, "CATEGORY_ROLLUP")
    return f"{family}_unclassified", _rule_id(spec, family, "UNCLASSIFIED")


def _extract_value_key(identifier: str, value_name: str) -> str:
    pattern = _DATE_VALUE_PATTERNS.get(value_name)
    if pattern is None:
        return ""
    match = pattern.search(identifier)
    return normalize_key(match.group(1)) if match else ""


def _extract_rate_key(identifier: str, family: str) -> str:
    if family not in {"debt", "mixed"}:
        return ""
    match = _RATE_VALUE_RE.search(identifier)
    return normalize_key(match.group(1)) if match else ""


def _canonical_identifier_for_keys(spec: WrapperSpec, identifier: str) -> str:
    if spec.canonical_strip_re is not None:
        return spec.canonical_strip_re.sub("", identifier).strip()
    return identifier


# ---------------------------------------------------------------------------
# JSON-based spec loader (replaces hardcoded _make_specs)
# ---------------------------------------------------------------------------

_WRAPPER_DEFINITIONS_DIR = Path(__file__).resolve().parent.parent / "data" / "overrides" / "bdc_xbrl_wrappers"


def _load_specs_from_json() -> dict[str, WrapperSpec]:
    """Load WrapperSpec objects from v3 JSON definitions with dispatch sections."""
    specs: dict[str, WrapperSpec] = {}
    if not _WRAPPER_DEFINITIONS_DIR.exists():
        return specs
    for path in sorted(_WRAPPER_DEFINITIONS_DIR.glob("*.json")):
        try:
            with open(path, encoding="utf-8") as fh:
                raw = json.load(fh)
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Failed to load wrapper JSON %s: %s", path.name, exc)
            continue
        schema_version = raw.get("schema_version", "")
        if schema_version != "bdc-xbrl-wrapper.v3":
            continue
        dispatch = raw.get("dispatch")
        if dispatch is None:
            continue
        cik = raw["cik"]
        cik_norm = normalize_cik(cik)

        # Build prefix_rules
        prefix_rules = dict(dispatch.get("prefix_rules") or {})

        # Build leaf_markers_by_family
        raw_markers = dispatch.get("leaf_markers_by_family")
        if raw_markers:
            leaf_markers = {k: tuple(v) for k, v in raw_markers.items()}
        else:
            leaf_markers = dict(DEFAULT_LEAF_MARKERS_BY_FAMILY)

        # Build aggregate_markers
        agg = dispatch.get("aggregate_markers")
        aggregate_markers = tuple(agg) if agg else (
            "sub-total", "subtotal", "total investments",
            "total debt investments", "total equity investments",
            "portfolio investments",
        )

        # Build non_private_markers
        npm = dispatch.get("non_private_markers")
        non_private_markers = tuple(npm) if npm else (
            "cash", "money market", "financial square",
            "government institutional", "u.s. treasury", "us treasury",
        )

        # Build entity_signals_re
        entity_re_str = dispatch.get("entity_signals_re")
        entity_signals_re = re.compile(entity_re_str, re.IGNORECASE) if entity_re_str else DEFAULT_ENTITY_SIGNALS_RE

        # Build category_marker_re
        cat_re_str = dispatch.get("category_marker_re")
        category_marker_re = re.compile(cat_re_str, re.IGNORECASE) if cat_re_str else None

        # Build fallback_family_patterns
        fallback_patterns: list[tuple[re.Pattern[str], str]] = []
        for entry in dispatch.get("fallback_family_patterns") or []:
            try:
                pat = re.compile(entry["regex"], re.IGNORECASE)
                fallback_patterns.append((pat, entry["family"]))
            except re.error as exc:
                logger.warning("Bad fallback regex in %s: %s", path.name, exc)

        # Build canonical_strip_re
        canon_str = dispatch.get("canonical_strip_re")
        canonical_strip_re = re.compile(canon_str) if canon_str else None

        # no_prefix_is_aggregate flag
        no_prefix_is_aggregate = bool(dispatch.get("no_prefix_is_aggregate", False))

        spec = WrapperSpec(
            cik=cik,
            rule_prefix=dispatch["rule_prefix"],
            version=str(raw.get("version", 1)),
            prefix_rules=prefix_rules,
            leaf_markers_by_family=leaf_markers,
            entity_signals_re=entity_signals_re,
            aggregate_markers=aggregate_markers,
            non_private_markers=non_private_markers,
            category_marker_re=category_marker_re,
            fallback_family_patterns=tuple(fallback_patterns),
            canonical_strip_re=canonical_strip_re,
            no_prefix_is_aggregate=no_prefix_is_aggregate,
        )
        specs[cik_norm] = spec
    return specs


WRAPPER_SPECS = _load_specs_from_json()


def get_wrapper_spec(cik: Any) -> WrapperSpec | None:
    return WRAPPER_SPECS.get(normalize_cik(cik))


def supported_wrapper_ciks() -> tuple[str, ...]:
    return tuple(sorted(WRAPPER_SPECS))


def supported_prefixes_for_cik(cik: Any) -> tuple[str, ...]:
    spec = get_wrapper_spec(cik)
    return tuple(spec.prefix_rules) if spec else ()


def classify_identifier(cik: Any, identifier: Any) -> dict[str, str]:
    raw = normalize_wrapper_identifier(identifier)
    result = {col: "" for col in WRAPPER_COLUMNS}
    spec = get_wrapper_spec(cik)
    if spec is None:
        return result
    prefix, family = _family_for_identifier(spec, raw)
    if not family:
        return result

    has_leaf_marker = _has_leaf_marker(spec, raw, family)
    key_identifier = _canonical_identifier_for_keys(spec, raw)
    parent_key = normalize_key(_parent_text(key_identifier))
    result["wrapper_version"] = spec.version
    result["wrapper_family"] = family
    if not parent_key:
        result.update({
            "wrapper_rule_id": _rule_id(spec, family, "UNCLASSIFIED"),
            "wrapper_disposition": f"{family}_unclassified",
            "wrapper_signature_status": "fail",
        })
        return result

    result["wrapper_parent_key"] = parent_key
    result["wrapper_signature_status"] = "pass"
    if has_leaf_marker:
        investment_date_key = _extract_value_key(key_identifier, "investment")
        maturity_date_key = _extract_value_key(key_identifier, "maturity")
        rate_key = _extract_rate_key(key_identifier, family)
        structured_parts = [family, parent_key, investment_date_key, maturity_date_key, rate_key]
        result.update({
            "wrapper_rule_id": _rule_id(spec, family, "LEAF"),
            "wrapper_disposition": f"{family}_position_leaf",
            "wrapper_position_key": normalize_key(key_identifier),
            "wrapper_investment_date_key": investment_date_key,
            "wrapper_maturity_date_key": maturity_date_key,
            "wrapper_rate_key": rate_key,
            "wrapper_structured_leaf_key": "|".join(structured_parts)
            if parent_key and (investment_date_key or maturity_date_key or rate_key)
            else "",
        })
    else:
        disposition, rule_id = _rollup_disposition(spec, raw, parent_key, family, prefix)
        result.update({
            "wrapper_rule_id": rule_id,
            "wrapper_disposition": disposition,
            "wrapper_signature_status": "pass" if not disposition.endswith("_unclassified") else "fail",
        })
    return result


def add_bdc_xbrl_wrapper_columns(
    df: pd.DataFrame,
    *,
    identifier_col: str,
    cik_col: str = "cik",
) -> pd.DataFrame:
    """Return ``df`` with deterministic wrapper columns added."""
    result = df.copy()
    for col in WRAPPER_COLUMNS:
        if col not in result.columns:
            result[col] = ""
        else:
            result[col] = result[col].fillna("").astype(str)

    if result.empty or identifier_col not in result.columns or cik_col not in result.columns:
        return result

    cik_norm = result[cik_col].map(normalize_cik)
    identifiers = result[identifier_col].fillna("").map(normalize_wrapper_identifier)
    mask = pd.Series(False, index=result.index)
    for cik_value, spec in WRAPPER_SPECS.items():
        prefix_mask = pd.Series(False, index=result.index)
        for prefix in spec.prefix_rules:
            prefix_mask = prefix_mask | identifiers.str.startswith(prefix, na=False)
        # Apply fallback patterns from config (replaces hardcoded Saratoga checks)
        for pattern, _family in spec.fallback_family_patterns:
            prefix_mask = prefix_mask | identifiers.str.match(pattern, na=False)
        mask = mask | (cik_norm.eq(cik_value) & prefix_mask)
    if not mask.any():
        return result

    classified = pd.DataFrame(
        [classify_identifier(cik, identifier) for cik, identifier in zip(result.loc[mask, cik_col], identifiers.loc[mask])],
        index=result.index[mask],
    )
    for col in WRAPPER_COLUMNS:
        result.loc[mask, col] = classified[col]
    return result
