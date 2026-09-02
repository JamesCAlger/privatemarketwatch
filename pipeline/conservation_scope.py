"""Per-CIK conservation-scope overrides (Layer 2, audited JSON).

The conservation sum excludes asset_category CASH globally, but some filers'
printed Total Investments INCLUDE cash-like instruments (1905824 FHLB discount
notes). The eligible set must mirror what the filer's anchor includes; that is
scope config, not a classification change. Consumed by BOTH sum
implementations (agent_rule.value_sum_by_quarter and the shadow conservation
engine) so trial and production frames cannot diverge.

Quarter scoping (2026-09-02): anchor bases differ by quarter -- e.g. the
2026-03-31 anchors for 1950976/1899996/1772704/1916608 are agent-promoted
schedule totals that INCLUDE the MMF sweep, while their 2025-12-31 anchors are
companyfacts concepts that EXCLUDE it (an "all"-quarters carve-out regressed
the attested Q4). scope_quarters is therefore either ["all"] or an explicit
list of ISO report dates; anything else is ignored fail-closed.
"""
from __future__ import annotations

import json
import logging
import re

from pipeline import config

logger = logging.getLogger(__name__)
SCOPE_DIR = config.CONSERVATION_SCOPE_DIR

_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _norm(cik) -> str:
    return str(cik).lstrip("0")


def scope_override_for(cik) -> tuple[frozenset[str], frozenset[str] | None]:
    """(included_categories, scoped_quarters) for this CIK's override.

    - No/invalid override: (frozenset(), None).
    - scope_quarters == ["all"]: (categories, None) -- applies to every quarter.
    - scope_quarters == list of ISO dates: (categories, frozenset(dates)).

    Fail-closed: missing/empty scope_quarters, or any entry that is neither
    "all" nor an ISO date, invalidates the whole override with a warning.
    """
    if not SCOPE_DIR.exists():
        return frozenset(), None
    target = _norm(cik)
    for p in sorted(SCOPE_DIR.glob("*.json")):
        if _norm(p.stem) != target:
            continue
        try:
            obj = json.loads(p.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("conservation_scope override unreadable, ignored: %s (%s)", p, exc)
            return frozenset(), None
        cats = obj.get("include_asset_categories")
        if not (isinstance(cats, list) and cats and obj.get("evidence")):
            logger.warning("conservation_scope override invalid, ignored: %s", p)
            return frozenset(), None
        sq = obj.get("scope_quarters")
        if not (isinstance(sq, list) and sq):
            logger.warning(
                "conservation_scope override %s has missing/empty scope_quarters"
                " -- ignored (fail-closed)", p.stem)
            return frozenset(), None
        categories = frozenset(str(c).upper() for c in cats)
        if sq == ["all"]:
            return categories, None
        quarters = [str(q).strip() for q in sq]
        if all(_ISO_DATE_RE.match(q) for q in quarters):
            return categories, frozenset(quarters)
        logger.warning(
            "conservation_scope override %s has unrecognized scope_quarters"
            " entries -- ignored (fail-closed)", p.stem)
        return frozenset(), None
    return frozenset(), None


def included_categories_for(cik, quarter: str | None = None) -> frozenset[str]:
    """asset_category values this CIK's anchor scope INCLUDES despite the
    global conservation exclusion, for the given quarter.

    quarter=None returns categories only for "all"-quarters overrides
    (fail-closed for quarter-unaware callers when the override is scoped).
    """
    categories, quarters = scope_override_for(cik)
    if not categories:
        return frozenset()
    if quarters is None:
        return categories
    if quarter is not None and str(quarter) in quarters:
        return categories
    return frozenset()
