"""Per-CIK conservation-scope overrides (Layer 2, audited JSON).

The conservation sum excludes asset_category CASH globally, but some filers'
printed Total Investments INCLUDE cash-like instruments (1905824 FHLB discount
notes). The eligible set must mirror what the filer's anchor includes; that is
scope config, not a classification change. Consumed by BOTH sum
implementations (agent_rule.value_sum_by_quarter and the shadow conservation
engine) so trial and production frames cannot diverge.
"""
from __future__ import annotations

import json
import logging

from pipeline import config

logger = logging.getLogger(__name__)
SCOPE_DIR = config.CONSERVATION_SCOPE_DIR


def _norm(cik) -> str:
    return str(cik).lstrip("0")


def included_categories_for(cik) -> frozenset[str]:
    """asset_category values this CIK's anchor scope INCLUDES despite the
    global conservation exclusion. Empty set when no valid override exists."""
    if not SCOPE_DIR.exists():
        return frozenset()
    target = _norm(cik)
    for p in sorted(SCOPE_DIR.glob("*.json")):
        if _norm(p.stem) != target:
            continue
        try:
            obj = json.loads(p.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("conservation_scope override unreadable, ignored: %s (%s)", p, exc)
            return frozenset()
        cats = obj.get("include_asset_categories")
        if not (isinstance(cats, list) and cats and obj.get("evidence")):
            logger.warning("conservation_scope override invalid, ignored: %s", p)
            return frozenset()
        return frozenset(str(c).upper() for c in cats)
    return frozenset()
