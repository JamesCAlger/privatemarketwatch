"""Per-CIK fund highlights wrappers for concept mapping and share class aliases.

Wrappers are deterministic JSON configs loaded at extraction time -- no LLM in
the hot path.  They fix per-CIK concept-to-field mapping gaps and share class
member recognition failures identified by the fund highlights oracle.

Wrapper specs are loaded from v1 JSON definitions in
data/overrides/fund_highlights_wrappers/{CIK}.json.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pipeline.config import FUND_HIGHLIGHTS_WRAPPER_DIR

logger = logging.getLogger(__name__)

_SCHEMA_VERSION = "fund-highlights-wrapper.v1"

# Module-level cache: CIK (10-digit padded) -> HighlightsWrapperSpec
_WRAPPER_CACHE: dict[str, "HighlightsWrapperSpec"] = {}
_CACHE_LOADED = False


def _normalize_cik(value: Any) -> str:
    """Normalize CIK to 10-digit zero-padded string."""
    digits = re.sub(r"\D+", "", "" if value is None else str(value))
    return digits.zfill(10) if digits else ""


@dataclass(frozen=True)
class HighlightsWrapperSpec:
    """Frozen spec for a single CIK's fund highlights wrapper."""
    cik: str
    entity_name: str
    version: int
    # Ordered (substring, target_field, action) tuples
    concept_overrides: tuple[tuple[str, str, str], ...] = ()
    share_class_aliases: dict[str, str] = field(default_factory=dict)
    oracle_tolerances: dict[str, float] = field(default_factory=dict)
    source_preferences: dict[str, str] = field(default_factory=dict)
    # (report_date, field, value) the filer's page states and its undimensioned facts get wrong
    figure_corrections: tuple[tuple[str, str, float], ...] = ()
    # Lower-case concept-name substrings the fund-income extractor must not read as an income
    # figure for this filer (a filer's own per-share concept whose name contains an income name)
    income_concept_suppress: tuple[str, ...] = ()
    # (income column, lower-case concept name): the concept fills the column in the fund-income
    # extractor only for a period that has an income statement and no fact for that column
    income_concept_fallback: tuple[tuple[str, str], ...] = ()
    # Year-end dates of the year in which the fund began operating: the quarters before its first
    # income statement are nil, so that year-end quarter is the year less the quarters filed
    first_income_year_ends: tuple[str, ...] = ()
    notes: str = ""


def _load_wrapper_from_path(path: Path) -> HighlightsWrapperSpec | None:
    """Load and validate a single wrapper JSON file."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Failed to load highlights wrapper %s: %s", path.name, exc)
        return None

    sv = data.get("schema_version", "")
    if sv != _SCHEMA_VERSION:
        logger.warning(
            "Highlights wrapper %s: expected schema %s, got %s",
            path.name, _SCHEMA_VERSION, sv,
        )
        return None

    cik = _normalize_cik(data.get("cik", ""))
    if not cik:
        logger.warning("Highlights wrapper %s: missing or invalid cik", path.name)
        return None

    # Parse concept_overrides
    raw_overrides = data.get("concept_overrides", [])
    overrides = []
    for entry in raw_overrides:
        sub = entry.get("xbrl_concept_substring", "").lower()
        target = entry.get("target_field", "")
        action = entry.get("action", "map")
        if sub and action in ("map", "suppress", "prefer"):
            overrides.append((sub, target, action))

    # Parse share_class_aliases
    raw_aliases = data.get("share_class_aliases", {})
    aliases = {str(k): str(v) for k, v in raw_aliases.items()} if raw_aliases else {}

    # Parse oracle_tolerances (cap at 0.20)
    raw_tol = data.get("oracle_tolerances", {})
    tolerances = {}
    for key in ("nav_identity_tol", "income_identity_tol"):
        val = raw_tol.get(key)
        if val is not None:
            tolerances[key] = min(float(val), 0.20)

    # Parse source_preferences
    raw_prefs = data.get("source_preferences", {})
    prefs = {str(k): str(v) for k, v in raw_prefs.items()} if raw_prefs else {}

    # Parse figure_corrections: each needs a date, a known field, a number and its evidence.
    corrections = []
    for entry in data.get("figure_corrections", []) or []:
        day, name, value = str(entry.get("report_date", "")), str(entry.get("field", "")), entry.get("value")
        if (not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day) or name not in FIGURE_FIELDS
                or not isinstance(value, (int, float)) or not str(entry.get("evidence", "")).strip()):
            logger.warning("Highlights wrapper %s: figure correction ignored: %r", path.name, entry)
            continue
        corrections.append((day, name, float(value)))

    return HighlightsWrapperSpec(
        cik=cik,
        entity_name=data.get("entity_name", ""),
        version=int(data.get("version", 1)),
        concept_overrides=tuple(overrides),
        share_class_aliases=aliases,
        oracle_tolerances=tolerances,
        source_preferences=prefs,
        figure_corrections=tuple(corrections),
        income_concept_suppress=tuple(str(s).strip().lower() for s in (data.get("income_concept_suppress") or [])
                                      if str(s).strip()),
        income_concept_fallback=tuple(
            (str(column), str(concept).strip().lower())
            for column, concepts in (data.get("income_concept_fallback") or {}).items()
            if str(column) in INCOME_FALLBACK_COLUMNS
            for concept in (concepts or []) if str(concept).strip()),
        first_income_year_ends=tuple(str(day) for day in (data.get("first_income_year_ends") or [])
                                     if re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(day))),
        notes=data.get("notes", ""),
    )


def _ensure_cache_loaded() -> None:
    """Load all wrapper JSON files into the module cache."""
    global _CACHE_LOADED
    if _CACHE_LOADED:
        return
    _WRAPPER_CACHE.clear()
    if not FUND_HIGHLIGHTS_WRAPPER_DIR.exists():
        _CACHE_LOADED = True
        return
    for path in sorted(FUND_HIGHLIGHTS_WRAPPER_DIR.glob("*.json")):
        spec = _load_wrapper_from_path(path)
        if spec:
            _WRAPPER_CACHE[spec.cik] = spec
    if _WRAPPER_CACHE:
        logger.info(
            "Loaded %d fund highlights wrappers", len(_WRAPPER_CACHE),
        )
    _CACHE_LOADED = True


def load_highlights_wrapper(cik: Any) -> HighlightsWrapperSpec | None:
    """Load a single CIK's highlights wrapper, or None if not found."""
    _ensure_cache_loaded()
    return _WRAPPER_CACHE.get(_normalize_cik(cik))


CLASS_NAV_PREFERENCE = "share_class_consensus"

# Income columns a wrapper may name a fallback concept for (income_concept_fallback).
INCOME_FALLBACK_COLUMNS = frozenset({"total_expenses"})

# Fund-level figures a wrapper may correct from the filing page.
FIGURE_FIELDS = frozenset({"total_assets", "total_liabilities", "net_assets", "investments_at_fair_value",
                           "nav_per_share", "shares_outstanding",
                           # Quarter figures of the same frame that a filer's duration facts can get wrong (North
                           # Haven: the year's distribution per unit filed again on a three-month context; an
                           # annualised income ratio that the year-to-date split reads as a running total; net
                           # expenses printed for a quarter and not tagged).
                           "distribution_per_share", "income_yield_pct", "net_expenses"})


def apply_figure_corrections(balance_df):
    """Set the fund-level figures a wrapper corrects, on the company-facts balance frame.

    Company facts hold one undimensioned value per concept and date, the last one filed. That
    value can be wrong for a date (Golub 2023-06-30: a later 10-K files 50,000 where the 10-Q's
    balance sheet says 650,323,000), filed at the wrong scale (Oaktree 2022-03-31: 4,000 shares
    and 25,040 a share, in thousands), or not filed at all (Sixth Street 2023-06-30: the printed
    'Total Investments' has no undimensioned fact). A wrapper lists the figure with the page as
    evidence; it is applied before scale detection, so the detection sees the right numbers.
    A correction for a date the fund's rows do not hold adds the row. A fund with no rows in the
    frame is left alone: a correction never brings a fund into a build that did not load it.
    Returns the frame.
    """
    _ensure_cache_loaded()
    if balance_df is None or balance_df.empty or "cik" not in balance_df.columns or "report_date" not in balance_df.columns:
        return balance_df
    frame = balance_df.copy()
    added = []
    for cik, spec in _WRAPPER_CACHE.items():
        mine = frame["cik"].astype(str).str.zfill(10) == cik
        if not spec.figure_corrections or not mine.any():
            continue
        for day, name, value in spec.figure_corrections:
            if name not in frame.columns:
                frame[name] = None
            hit = mine & (frame["report_date"].astype(str).str[:10] == day)
            if hit.any():
                frame.loc[hit, name] = value
            else:
                added.append({"cik": cik, "report_date": day, name: value})
            logger.info("fund figure corrected from the page: %s %s %s = %s", cik, day, name, value)
    if added:
        import pandas as pd
        extra = pd.DataFrame(added).groupby(["cik", "report_date"], as_index=False).first()
        frame = pd.concat([frame, extra], ignore_index=True)
    return frame


def first_income_year_ends() -> frozenset[tuple[str, str]]:
    """(cik, year-end date) pairs whose wrapper declares the year the fund began operating.

    Opt-in: ``first_income_year_ends``. Read by ``fund_financials.quarter_income_sql``, which for
    these pairs alone takes the year-end quarter as the annual figure less the one or two
    quarters filed, the quarters before the first income statement being nil.
    """
    _ensure_cache_loaded()
    return frozenset((cik, day) for cik, spec in _WRAPPER_CACHE.items() for day in spec.first_income_year_ends)


def class_nav_ciks() -> frozenset[str]:
    """CIKs whose wrapper takes NAV per share from the per-class filing facts.

    Opt-in: source_preferences.nav_per_share = "share_class_consensus". For these
    funds the quarter-end per-class facts are kept in the highlights extract and,
    when every class agrees, used in place of a missing or inconsistent
    entity-level NAV per share.
    """
    _ensure_cache_loaded()
    return frozenset(cik for cik, spec in _WRAPPER_CACHE.items()
                     if spec.source_preferences.get("nav_per_share") == CLASS_NAV_PREFERENCE)


def get_all_highlights_wrappers() -> dict[str, HighlightsWrapperSpec]:
    """Return the full wrapper cache: {cik_10digit: spec}."""
    _ensure_cache_loaded()
    return dict(_WRAPPER_CACHE)


def invalidate_cache() -> None:
    """Force reload on next access (useful for tests)."""
    global _CACHE_LOADED
    _WRAPPER_CACHE.clear()
    _CACHE_LOADED = False
