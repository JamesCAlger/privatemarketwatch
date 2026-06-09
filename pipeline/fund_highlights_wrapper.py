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

    return HighlightsWrapperSpec(
        cik=cik,
        entity_name=data.get("entity_name", ""),
        version=int(data.get("version", 1)),
        concept_overrides=tuple(overrides),
        share_class_aliases=aliases,
        oracle_tolerances=tolerances,
        source_preferences=prefs,
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


def get_all_highlights_wrappers() -> dict[str, HighlightsWrapperSpec]:
    """Return the full wrapper cache: {cik_10digit: spec}."""
    _ensure_cache_loaded()
    return dict(_WRAPPER_CACHE)


def invalidate_cache() -> None:
    """Force reload on next access (useful for tests)."""
    global _CACHE_LOADED
    _WRAPPER_CACHE.clear()
    _CACHE_LOADED = False
