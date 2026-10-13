"""A loan whose cost is tagged twice, once in dollars and once in a foreign unit.

A filer can tag the par of a foreign loan with the cost concept and the foreign unit, beside the
dollar cost (Apollo Debt Solutions, 10-K for 2025-12-31, JOA Joker Holdco 3: printed
'EUR 126,725 132,847 147,810' as par, cost, fair value; tagged InvestmentOwnedAtCost 126,725,000
in EUR and 132,847,000 in USD, and no principal fact). The extractor keeps the first fact of a
column, so the euro par was published as the dollar cost and the row had no principal.

A filer whose wrapper sets ``source_encodings.cost_in_two_units: ["foreign_is_par"]`` has such a
context read as the page prints it: the dollar fact is the cost, and the foreign fact is the
principal in that currency where the context carries no principal fact. A context is read this
way only when it has exactly two cost facts, one in a unit the filing defines as USD and one in a
unit it defines as another currency. Anything else is left alone.
"""
from __future__ import annotations

import logging
import re
from functools import lru_cache
from typing import Any

logger = logging.getLogger(__name__)

COST_CONCEPT = "investmentownedatcost"
COST_EVENT = "cost:of_two_units:"
PAR_EVENT = "principal_amount:from_foreign_cost_tag:"
_AMOUNT_RE = re.compile(r"-?\d+(?:\.\d+)?")


@lru_cache(maxsize=1)
def _reading_ciks() -> frozenset[str]:
    from pipeline.source_encodings import load_encodings
    return frozenset(cik for cik, encoding in load_encodings().items()
                     if encoding.get("cost_in_two_units") == ["foreign_is_par"])


def reads_cost_in_two_units(cik: Any) -> bool:
    return re.sub(r"\D", "", str(cik or "")).zfill(10) in _reading_ciks()


def two_unit_costs(tree: Any, wanted: Any = None) -> dict[str, tuple[tuple[str, float], tuple[str, float]]]:
    """Contexts with one dollar and one foreign cost fact: context -> ((usd unit, value), (foreign unit, value))."""
    from pipeline.bdc_filings import _local_name
    from pipeline.monetary_units import XBRLI, unit_definition
    root = tree.getroot()
    currency: dict[str, str] = {}
    repeated: set[str] = set()
    for unit in root.findall(f"{{{XBRLI}}}unit"):
        name = unit.get("id") or ""
        if name in currency:
            repeated.add(name)
        definition = unit_definition(unit)
        currency[name] = definition["currency"] if definition["unit_kind"] == "monetary" else ""
    seen: dict[str, list[tuple[str, float]]] = {}
    for elem in root.iter():
        if not isinstance(elem.tag, str) or _local_name(elem.tag).lower() != COST_CONCEPT:
            continue
        context = elem.get("contextRef") or ""
        text = (elem.text or "").strip()
        if not context or (wanted is not None and context not in wanted) or not _AMOUNT_RE.fullmatch(text):
            continue
        fact = (elem.get("unitRef") or "", float(text))
        if fact not in seen.setdefault(context, []):
            seen[context].append(fact)
    result = {}
    for context, facts in seen.items():
        if len(facts) != 2 or any(unit in repeated or not currency.get(unit) for unit, _ in facts):
            continue
        dollars = [fact for fact in facts if currency[fact[0]] == "USD"]
        foreign = [fact for fact in facts if currency[fact[0]] != "USD"]
        if len(dollars) == 1 and len(foreign) == 1:
            result[context] = (dollars[0], foreign[0])
    return result


def settle_cost_in_two_units(tree: Any, facts_by_context: dict[str, dict[str, Any]], filing_meta: dict[str, str],
                             record_events: bool = True) -> int:
    """Read the dollar fact as cost and the foreign fact as par, in place. Returns the contexts changed."""
    if not reads_cost_in_two_units(filing_meta.get("cik", "")):
        return 0
    from pipeline.bdc_filings import _record_value_xform
    changed = 0
    for context, ((usd_unit, usd_value), (foreign_unit, foreign_value)) in two_unit_costs(tree, facts_by_context).items():
        values = facts_by_context[context]
        kept = values.get("cost")
        if not isinstance(kept, (int, float)) or kept not in (usd_value, foreign_value):
            logger.warning("cost in two units %s %s %s: stored cost matches neither fact; left alone",
                           filing_meta.get("cik", ""), filing_meta.get("accession_number", ""), context)
            continue
        if kept != usd_value:
            values["cost"] = usd_value
            values["cost_unit"] = usd_unit
            if record_events:
                # the declared raw value is the fact that was read (the dollar one), which the re-verifier re-reads
                _record_value_xform(values, "cost", usd_value, COST_EVENT + usd_unit)
        if values.get("principal_amount") is None:
            values["principal_amount"] = foreign_value
            values["principal_amount_unit"] = foreign_unit
            if record_events:
                _record_value_xform(values, "principal_amount", foreign_value, PAR_EVENT + foreign_unit)
        changed += 1
    return changed


def declared_unit(field: str, x_events: list) -> str | None:
    """The unit of the cost fact a published cost or principal was read from, else None."""
    prefix = {"cost": COST_EVENT, "principal_amount": PAR_EVENT}.get(field)
    if prefix:
        for event in x_events:
            if str(event).startswith(prefix):
                return str(event)[len(prefix):]
    return None
