"""Source-precision XBRL field observations for E4; never repairs holdings.

The concept vocabulary is shared with extraction; numeric values, units and
precision are read directly from cached instances. Context role/completeness
comes from the separate E0 collector. Replay is a separate diagnostic.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from pathlib import Path
import re

from lxml import etree

from pipeline.bdc_filings import CONCEPT_MAP
from pipeline.context_inventory import XBRLI, _namespace, _number, local
from pipeline.programme.core import sha
from pipeline.provenance_reverify import CHEAP_FIELDS
from pipeline.monetary_units import unit_definition

POLICY_VERSION = "field-assessment.v3"
FIELDS = tuple(CHEAP_FIELDS)
MONEY = frozenset({"fair_value", "cost", "principal_amount"})
RATES = frozenset({"interest_rate", "basis_spread", "pik_rate", "pct_of_net_assets"})


def field_for(concept):
    # Preserve longest-specific-first matching, including exclusions such as
    # rate floors. Filtering the vocabulary before matching would misread them.
    name = local(concept).lower()
    field = next((field for pattern, field in CONCEPT_MAP if pattern in name), None)
    return field if field in FIELDS else None


def precision_bound(decimals):
    if decimals == "INF":
        return "0"
    if decimals is None or not re.fullmatch(r"-?\d+", decimals):
        return None
    places = int(decimals)
    # This is the precision range of the comparison representation, not an
    # error tolerance. Unsupported precision is explicitly unassessable.
    if not -20 <= places <= 11:
        return None
    return str(Decimal(5).scaleb(-places - 1))


def source_meaning(field, concept, unit_kind, raw):
    """Return assessability reason and multiplier into the stored convention.

    v5 stores cash interest. Generic InvestmentInterestRate does not establish
    whether that fact means cash or all-in. Never choose meaning by closeness.
    """
    if field in MONEY:
        return ("ready" if unit_kind == "monetary" else "unresolved_monetary_unit"), 1
    if field == "shares_held":
        return ("ready" if unit_kind == "shares" else "unresolved_share_unit"), 1
    if unit_kind != "pure":
        return "unresolved_rate_unit", 100
    if raw is not None and abs(Decimal(raw)) > 1:
        return "ambiguous_rate_scale", 100
    name = local(concept).lower()
    if field == "interest_rate" and "investmentinterestratepaidincash" not in name:
        return "unresolved_cash_or_all_in_kind", 100
    return "ready", 100


def read_field_document(path: Path, cik: str, *, max_bytes=100_000_000,
                        max_contexts=25_000, max_facts=300_000):
    """One source parse; no network, correction, default timer or memory cap."""
    path = Path(path)
    result = dict(path=str(path), cik=cik, sha256=None, complete=False,
                  errors=[], facts=[], contexts=[], other_facts=[])
    try:
        before = path.stat()
        if before.st_size > max_bytes:
            raise ValueError("Source exceeds structural byte bound")
        result["sha256"] = sha(path)
        tree = etree.parse(str(path), etree.XMLParser(resolve_entities=False,
            no_network=True, load_dtd=False, huge_tree=True))
        if tree.docinfo.doctype:
            raise ValueError("DTD is not permitted in source instances")
        units = {u.get("id"): unit_definition(u) for u in tree.findall(f"{{{XBRLI}}}unit")}
        contexts = {}
        for node in tree.findall(f"{{{XBRLI}}}context"):
            instants = node.findall(f"{{{XBRLI}}}period/{{{XBRLI}}}instant")
            entity = node.findtext(f"{{{XBRLI}}}entity/{{{XBRLI}}}identifier", "")
            period = (instants[0].text or "").strip() if len(instants) == 1 else None
            contexts[node.get("id")] = dict(context_id=node.get("id"), quarter=period,
                valid_entity=entity.strip().lstrip("0") == cik.lstrip("0"))
        if len(contexts) > max_contexts:
            raise ValueError("Source exceeds structural context bound")
        result["contexts"] = list(contexts.values())
        from pipeline.categorical_field_assessment import read_facts
        result['other_facts'] = read_facts(tree, contexts)
        count = 0
        for node in tree.getroot():
            context_id = node.get("contextRef")
            if not context_id:
                continue
            count += 1
            if count > max_facts:
                raise ValueError("Source exceeds structural fact bound")
            field = field_for(node.tag)
            if not field:
                continue
            context = contexts.get(context_id)
            if context is None:
                result["errors"].append("Field fact references missing context: " + context_id)
                continue
            if not context["quarter"]:
                continue
            raw, value_status = _number(node)
            definition = units.get(node.get("unitRef"), dict(unit_kind="unresolved", currency=None))
            reason, multiplier = source_meaning(field, node.tag, definition["unit_kind"], raw)
            bound = precision_bound(node.get("decimals"))
            if not context["valid_entity"]:
                reason = "reporting_entity_mismatch"
            elif value_status != "reported":
                reason = "source_" + value_status
            elif bound is None:
                reason = "unresolved_source_precision"
            elif node.get("scale") or node.get("sign"):
                reason = "unexpected_inline_transform_in_instance"
            result["facts"].append(dict(context_id=context_id, quarter=context["quarter"],
                field=field, concept=node.tag, fact_id=node.get("id"), raw=raw,
                decimals=node.get("decimals"), rounding_bound=bound,
                unit_ref=node.get("unitRef"), **definition, reason=reason,
                multiplier=multiplier, nil=value_status == "nil"))
        after = path.stat()
        if (before.st_size, before.st_mtime_ns, result["sha256"]) != (
                after.st_size, after.st_mtime_ns, sha(path)):
            raise ValueError("Source changed during field inspection")
        result["complete"] = not result["errors"]
    except (OSError, ValueError, InvalidOperation, etree.XMLSyntaxError) as exc:
        result["errors"].append(type(exc).__name__ + ": " + str(exc))
    return result


def comparison_sql():
    """Compare one source-context/field with candidate rows in a typed join.

    Inputs: source_fields (one row per reference context/field) and published
    (candidate count/value/currency per same key). Unresolved join multiplicity
    is retained; it cannot silently select a favourable candidate or source.
    """
    return """SELECT s.*, p.candidate_rows, p.published, p.published_currency,
      CASE
        WHEN NOT s.source_complete THEN 'disclosed_unassessable'
        WHEN coalesce(s.fact_count,0)=0 THEN 'not_disclosed'
        WHEN s.reason <> 'ready' OR s.variants <> 1 OR s.source_role <> 'confirmed_position'
          OR s.correspondence_status <> 'ready'
          OR coalesce(p.candidate_rows,0)>1 THEN 'disclosed_unassessable'
        WHEN coalesce(p.candidate_rows,0)=0 OR p.published IS NULL THEN 'missing_output'
        WHEN s.field IN ('fair_value','cost','principal_amount')
          AND nullif(p.published_currency,'') IS NULL THEN 'disclosed_unassessable'
        WHEN s.field IN ('fair_value','cost','principal_amount')
          AND p.published_currency <> s.currency THEN 'incorrect'
        WHEN abs(p.published-s.reference_value) <= s.precision_bound THEN 'correct'
        ELSE 'incorrect'
      END AS category,
      CASE
        WHEN NOT s.source_complete THEN 'incomplete_source'
        WHEN coalesce(s.fact_count,0)=0 THEN 'no_numeric_tag_disclosed'
        WHEN s.variants <> 1 THEN 'conflicting_source_facts'
        WHEN s.reason <> 'ready' THEN s.reason
        WHEN s.source_role <> 'confirmed_position' THEN 'unresolved_position_role'
        WHEN s.correspondence_status <> 'ready' THEN s.correspondence_status
        WHEN coalesce(p.candidate_rows,0)>1 THEN 'ambiguous_candidate_context_join'
        WHEN coalesce(p.candidate_rows,0)=0 OR p.published IS NULL THEN 'missing_value_or_row'
        WHEN s.field IN ('fair_value','cost','principal_amount')
          AND nullif(p.published_currency,'') IS NULL THEN 'unresolved_candidate_currency'
        WHEN s.field IN ('fair_value','cost','principal_amount')
          AND p.published_currency <> s.currency THEN 'wrong_currency'
        ELSE 'source_precision_comparison'
      END AS assessment_reason
      FROM source_fields s LEFT JOIN published p
      USING(cik,quarter,accession,context_id,field)"""
