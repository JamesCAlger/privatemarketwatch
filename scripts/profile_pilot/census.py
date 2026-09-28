"""Task 4: bounded, cache-only census of one XBRL instance per fund-quarter.

Seams: census_collect.py parses the instance once under explicit bounds; this
module maps facts to canonical fields with recorded dependencies, assembles
position observations, conflicts, periods and fund-level facts, runs the detectors
(census_detect.py) and validates the document against
schemas/census_v0.schema.json; census_run.py is the cached stage runner and CLI.

Inherited (imported read-only, recorded as dependencies): the position concept map
(pipeline.bdc_filings.CONCEPT_MAP), the context role classifier and fund basis
concepts (pipeline.context_inventory), the per-CIK explicit identity rules it calls
(pipeline.explicit_contexts) and unit definitions (pipeline.monetary_units). Everything
else (comparative periods, rate/spread/PIK, text/date/boolean, footnote channel,
fund income, conflicts, completeness) is new pilot code, provenance `derived`.
"""
from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path
import re

from scripts.profile_pilot.census_collect import (  # noqa: F401  (Bounds re-exported)
    Bounds, _ascii, _local, _sha256_file, collect_instance, collection_state)

SCHEMA_PATH = Path(__file__).resolve().parent / "schemas" / "census_v0.schema.json"
ROLE_SOURCE = "pipeline/context_inventory.py:classify_context"
CENSUS_VERSION = "census.v0.2"
_STANDARD_NS = re.compile(r"https?://(?:fasb\.org/(?:us-gaap|srt|us-gaap-sup)|xbrl\.sec\.gov/dei)/")


class CensusIncomplete(RuntimeError):
    """A census whose collection is not complete: never cached as a complete result."""

    def __init__(self, doc: dict):
        super().__init__("census collection " + doc["collection"]["state"] + ": "
                         + "; ".join(doc["collection"]["errors"])[:500])
        self.doc = doc


# ---------------------------------------------------------------- field vocabulary

POSITION_VALUE = ("fair_value", "cost", "principal_amount", "face_amount", "shares_held",
                  "pct_of_net_assets", "unrealized_gain_loss", "realized_gain_loss")
POSITION_RATE = ("interest_rate", "pik_rate", "interest_rate_floor", "basis_spread")
DATE_FIELDS = ("maturity_date", "acquisition_date")
TEXT_FIELDS = ("reference_rate_type", "variable_rate_type", "industry", "affiliation",
               "issuer_name", "investment_type", "non_income_producing", "restricted")
# Fields reported for every recognised position observation (absent is explicit).
POSITION_FIELDS = POSITION_VALUE + POSITION_RATE + DATE_FIELDS + TEXT_FIELDS + ("non_accrual",)
GROUPS = {**{f: "position_value" for f in POSITION_VALUE},
          **{f: "position_rate" for f in POSITION_RATE},
          **{f: "position_date" for f in DATE_FIELDS},
          "reference_rate_type": "position_rate", "variable_rate_type": "position_rate",
          "industry": "position_attribute", "affiliation": "position_attribute",
          "issuer_name": "position_attribute", "investment_type": "position_attribute",
          "non_income_producing": "position_status", "restricted": "position_status",
          "non_accrual": "position_status"}
# Derived (new) exact local-name mappings, lower-cased.
DERIVED_EXACT = {
    "investmentindustrysectorextensibleenumeration": ("industry", "position_attribute"),
    "investmentissueraffiliationextensibleenumeration": ("affiliation", "position_attribute"),
    "investmentissuernameextensibleenumeration": ("issuer_name", "position_attribute"),
    "investmenttypeextensibleenumeration": ("investment_type", "position_attribute"),
    "investmentvariableinterestratetypeextensibleenumeration": ("variable_rate_type", "position_rate"),
    "investmentnonincomeproducing": ("non_income_producing", "position_status"),
    "investmentrestricted": ("restricted", "position_status"),
    "investmentincomeinterest": ("income_interest", "fund_income"),
    "interestincomeoperating": ("income_interest", "fund_income"),
    "investmentincomeinterestanddividend": ("income_interest_and_dividend", "fund_income"),
    "investmentincomedividend": ("income_dividend", "fund_income"),
    "dividendincomeoperating": ("income_dividend", "fund_income"),
    "grossinvestmentincomeoperating": ("income_total", "fund_income"),
    "revenues": ("income_revenues", "fund_income"),
    "feeincome": ("income_fee", "fund_income"),
    "netinvestmentincome": ("net_investment_income", "fund_income"),
    "investmentincomeoperatingafterexpenseandtax": ("net_investment_income", "fund_income"),
    "investmentincomenet": ("net_investment_income", "fund_income"),
    "documentperiodenddate": ("document_period_end_date", "document_metadata"),
    "documenttype": ("document_type", "document_metadata"),
    "entitycentralindexkey": ("entity_cik", "document_metadata"),
    "amendmentflag": ("amendment_flag", "document_metadata"),
    "documentfiscalperiodfocus": ("fiscal_period_focus", "document_metadata"),
}
DERIVED_SUBSTRING = (("nonaccrual", "non_accrual", "position_status"),
                     ("paidinkind", "income_pik", "fund_income"))
DIMENSION_FIELDS = {"investmentindustryaxis": "industry", "equitysecuritiesbyindustryaxis": "industry",
                    "industrysectoraxis": "industry",
                    "investmentissueraffiliationaxis": "affiliation",
                    "investmentissuernameaxis": "issuer_name", "investmenttypeaxis": "investment_type"}


def field_channel(field: str | None) -> str:
    if field in POSITION_VALUE or field in POSITION_RATE:
        return "numeric_facts"
    return "text_facts"


# ---------------------------------------------------------------- mapping with dependencies

def _module_record(name: str, module, used_for: str) -> dict:
    path = Path(module.__file__).resolve()
    parts = path.parts
    relative = "/".join(parts[parts.index("pipeline"):]) if "pipeline" in parts else path.name
    return dict(name=name, path=relative, sha256=_sha256_file(path), provenance="inherited",
                used_for=used_for)


def dependency_records(aggregate_markers: dict | None = None, grammar: dict | None = None) -> list[dict]:
    from pipeline import bdc_filings, context_inventory, explicit_contexts, monetary_units
    records = [
        _module_record("concept_map", bdc_filings, "CONCEPT_MAP position field mapping"),
        _module_record("context_role_classifier", context_inventory,
                       "classify_context role/role_reason and FUND_BASIS_CONCEPTS"),
        _module_record("explicit_identity_rules", explicit_contexts,
                       "per-CIK explicit-member identity (called by classify_context)"),
        _module_record("unit_definition", monetary_units, "unit kind and ISO 4217 currency"),
    ]
    if aggregate_markers:
        records.append(dict(name="wrapper_aggregate_markers", path=str(aggregate_markers.get("path")),
                            sha256=aggregate_markers.get("sha256"), provenance="inherited",
                            used_for="subtotal detector corroboration only; never a census value"))
    if grammar:
        from pipeline import identifier_rate
        records.append(_module_record("identifier_grammar_parser", identifier_rate,
                                      "apply_grammar for the partition grammar_dialect discriminator"))
        records.append(dict(name="identifier_rate_grammar", path=str(grammar.get("path")),
                            sha256=grammar.get("sha256"), provenance="inherited",
                            used_for="partition grammar_dialect discriminator only"))
    return records


def _concept_mapping(qname: str, concept_map, fund_basis) -> dict:
    local = _local(qname).lower()
    if local in DERIVED_EXACT and DERIVED_EXACT[local][1] == "document_metadata":
        field, group = DERIVED_EXACT[local]
        return dict(field=field, group=group, provenance="derived", inherited_from=None, rule="exact")
    for pattern, field in concept_map:
        if pattern in local:
            return dict(field=field, group=GROUPS.get(field, "position_value"),
                        provenance="inherited",
                        inherited_from="pipeline/bdc_filings.py:CONCEPT_MAP", rule=pattern)
    if local in DERIVED_EXACT:
        field, group = DERIVED_EXACT[local]
        return dict(field=field, group=group, provenance="derived", inherited_from=None, rule="exact")
    for pattern, field, group in DERIVED_SUBSTRING:
        if pattern in local:
            return dict(field=field, group=group, provenance="derived", inherited_from=None,
                        rule="substring:" + pattern)
    if local in fund_basis:
        return dict(field={"assets": "assets", "assetsnet": "net_assets",
                           "liabilities": "liabilities",
                           "stockholdersequity": "stockholders_equity"}[local],
                    group="fund_balance", provenance="inherited",
                    inherited_from="pipeline/context_inventory.py:FUND_BASIS_CONCEPTS", rule="exact")
    return dict(field=None, group="unknown", provenance="derived", inherited_from=None, rule=None)


def classify_with_dependencies(collected: dict, cik: str) -> dict:
    """Map every fact to a canonical field and every context to an inherited role.

    Mapping provenance is recorded per concept; the role classifier is the
    production `context_inventory.classify_context` over this parse (inherited).
    Unknown facts keep field=None; contexts without investment facts keep
    role=no_investment_facts. Nothing is removed.
    """
    from pipeline.bdc_filings import CONCEPT_MAP
    from pipeline import context_inventory as ci
    mappings = {}
    for fact in collected["facts"]:
        mapping = mappings.get(fact["qname"])
        if mapping is None:
            mapping = mappings[fact["qname"]] = _concept_mapping(fact["qname"], CONCEPT_MAP,
                                                                 ci.FUND_BASIS_CONCEPTS)
        fact["field"], fact["group"] = mapping["field"], mapping["group"]
        fact["provenance"], fact["inherited_from"] = mapping["provenance"], mapping["inherited_from"]
        if fact["field"] in DATE_FIELDS and fact["status"] == "reported" and fact["value_kind"] != "date":
            fact["status"], fact["value"] = "invalid", None
    by_context: dict[str, list] = {}
    for fact in collected["facts"]:
        by_context.setdefault(fact["context_id"], []).append(fact)
    cik10 = str(cik).zfill(10)
    for context in collected["contexts"]:
        role_facts, unknown, basis = [], [], set()
        for fact in by_context.get(context["id"], []):
            local = _local(fact["qname"])
            if _STANDARD_NS.match(fact["namespace"] or ""):
                basis.add(local.lower())
            field = ci._field(local)
            suspicious = ("investment" in local.lower() and fact["unit_ref"] and
                          any(x in local.lower() for x in ("fairvalue", "cost", "principal")))
            if field or suspicious:
                role_facts.append(dict(field=field, concept="{" + fact["namespace"] + "}" + local))
                if not field:
                    unknown.append(local)
        period = context["period"]
        if not role_facts:
            context.update(role="no_investment_facts", role_reason="no mapped investment value facts",
                           provenance="derived", inherited_from=None)
            continue
        shaped = dict(dimensions=collected["_internal"].get(context["id"], []),
                      period_kind=period["kind"] if period["kind"] in ("instant", "duration") else "unresolved",
                      period=period.get("instant") or period.get("end"),
                      entity_cik=context["entity"]["identifier"].zfill(10),
                      facts=role_facts, unknown_concepts=unknown)
        role, reason = ci.classify_context(shaped, cik10, basis_concepts=basis)
        context.update(role=role, role_reason=reason, provenance="inherited",
                       inherited_from=ROLE_SOURCE)
    return mappings


# ---------------------------------------------------------------- field values and positions

def _unit_key(fact: dict) -> tuple:
    return (fact.get("value_kind"), fact.get("unit_kind"), fact.get("currency"))


def _provenance_of(facts: list) -> dict:
    """Inherited only when every contributing fact's mapping is inherited."""
    sources = sorted({f.get("inherited_from") for f in facts})
    if all(f.get("provenance") == "inherited" for f in facts) and None not in sources:
        return dict(provenance="inherited", inherited_from="; ".join(sources))
    return dict(provenance="derived", inherited_from=None)


def field_value(facts: list) -> dict:
    """One field in one context. Conflicts are kept, never resolved by order or size."""
    entry = dict(fact_indices=[f["i"] for f in facts], concepts=sorted({f["qname"] for f in facts}),
                 raw=[f.get("raw", "") for f in facts], unit_kind=facts[0].get("unit_kind"),
                 currency=facts[0].get("currency"), decimals=facts[0].get("decimals"),
                 **_provenance_of(facts))
    statuses = {f["status"] for f in facts}
    if len(facts) == 1:
        return dict(entry, status=facts[0]["status"], value=facts[0]["value"], reason=None)
    same = {(f["status"], json.dumps(f["value"]), _unit_key(f), f.get("decimals")) for f in facts}
    if len(same) == 1:
        status = facts[0]["status"]
        return dict(entry, status="consistent_duplicate" if status == "reported" else status,
                    value=facts[0]["value"], reason=None)
    if len(statuses) > 1:
        reason = "status_differs"
    elif len({_unit_key(f) for f in facts}) > 1:
        reason = "unit_differs"
    elif len({f.get("decimals") for f in facts}) > 1:
        reason = "decimals_differ"
    else:
        reason = "value_differs"
    return dict(entry, status="conflict", value=None, reason=reason, unit_kind=None, currency=None,
                decimals=None)


def build_positions(contexts: list, facts: list, channels: dict) -> tuple[list, list]:
    by_context: dict[str, dict[str, list]] = {}
    for fact in facts:
        if fact["field"] and fact["context_resolved"]:
            by_context.setdefault(fact["context_id"], {}).setdefault(fact["field"], []).append(fact)
    positions, conflicts = [], []
    for context in contexts:
        grouped = by_context.get(context["id"], {})
        for field, items in grouped.items():
            if len(items) > 1:
                value = field_value(items)
                if value["status"] == "conflict":
                    conflicts.append(dict(context_id=context["id"], field=field, reason=value["reason"],
                                          fact_indices=value["fact_indices"], provenance="derived",
                                          inherited_from=None))
        if context.get("role") != "confirmed_position":
            continue
        fields = {}
        for field in POSITION_FIELDS:
            if field in grouped:
                fields[field] = field_value(grouped[field])
            elif channels[field_channel(field)]["state"] == "complete":
                fields[field] = dict(status="absent", provenance="derived", inherited_from=None)
            else:
                fields[field] = dict(status="unobservable", provenance="derived", inherited_from=None,
                                     reason=field_channel(field) + " " + channels[field_channel(field)]["state"])
        dimension_fields = {}
        for axis, member in context["dimensions"]:
            name = DIMENSION_FIELDS.get(_local(axis).lower())
            if name:
                dimension_fields.setdefault(name, []).append(member)
        idents = [d["value"] for d in context["typed_dimensions"]
                  if "investmentidentifier" in _local(d["axis"]).lower()]
        positions.append(dict(observation_id="obs:" + context["id"], context_id=context["id"],
                              period=context["period"],
                              identity=dict(typed_identifier=idents[0] if len(idents) == 1 else None,
                                            dimensions=context["dimensions"],
                                            typed_dimensions=context["typed_dimensions"]),
                              dimension_fields=dimension_fields, fields=fields,
                              # membership of the recognised-position subset is the inherited role
                              provenance="inherited", inherited_from=ROLE_SOURCE))
    return positions, conflicts


def _periods(contexts: list, facts: list, dped: list) -> list:
    counts: dict[tuple, list] = {}
    fact_counts: dict[str, int] = {}
    for fact in facts:
        fact_counts[fact["context_id"]] = fact_counts.get(fact["context_id"], 0) + 1
    for context in contexts:
        period = context["period"]
        key = (period["kind"], period.get("instant"), period.get("start"), period.get("end"))
        slot = counts.setdefault(key, [0, 0])
        slot[0] += 1
        slot[1] += fact_counts.get(context["id"], 0)
    out = []
    for (kind, instant, start, end), (n_contexts, n_facts) in sorted(counts.items(), key=lambda kv: str(kv[0])):
        anchor = instant or end
        if kind in ("forever", "unresolved"):
            relation = kind
        elif not dped:
            relation = "no_document_period_end"
        else:
            relation = "document_period_end" if anchor in dped else "comparative"
        entry = dict(kind=kind, contexts=n_contexts, facts=n_facts, relation=relation,
                     provenance="derived", inherited_from=None)
        if instant:
            entry["instant"] = instant
        if start:
            entry.update(start=start, end=end)
        out.append(entry)
    return out


# ---------------------------------------------------------------- the census document

def _metric(name: str, value, depends: list, channels: dict) -> dict:
    complete = all(channels[c]["state"] == "complete" for c in depends)
    return dict(name=name, value=value, depends_on_channels=depends,
                completeness="complete" if complete else "incomplete")


def build_census(path, meta: dict, *, bounds: Bounds = Bounds(), aggregate_markers: dict | None = None,
                 learned_predicates: list | None = None, grammar: dict | None = None) -> dict:
    """Collect, classify, assemble and run the detectors for one instance.

    `meta` holds cik, report_date, accession_number, form_type, role. The wrapper
    `aggregate_markers` (optional) reach only the subtotal detector as inherited
    corroboration. `grammar` ({path, sha256, body}: the authored identifier_rate_grammars
    file, optional) reaches only the partition detector's grammar_dialect discriminator.
    """
    from scripts.profile_pilot import census_detect
    collected = collect_instance(path, bounds=bounds)
    channels = collected["channels"]
    mappings = classify_with_dependencies(collected, meta["cik"])
    facts, contexts = collected["facts"], collected["contexts"]
    positions, conflicts = build_positions(contexts, facts, channels)
    dped = sorted({f["value"] for f in facts if f["field"] == "document_period_end_date"
                   and isinstance(f["value"], str)})
    dimensioned = {c["id"]: bool(c["dimensions"] or c["typed_dimensions"]) for c in contexts}
    period_of = {c["id"]: c["period"] for c in contexts}
    fund_income, fund_balance = [], []
    for fact in facts:
        if fact["group"] in ("fund_income", "fund_balance"):
            (fund_income if fact["group"] == "fund_income" else fund_balance).append(dict(
                fact_index=fact["i"], field=fact["field"], qname=fact["qname"],
                context_id=fact["context_id"], period=period_of.get(fact["context_id"]),
                scope="dimensioned" if dimensioned.get(fact["context_id"], True) else "fund",
                status=fact["status"], value=fact["value"], currency=fact.get("currency"),
                decimals=fact.get("decimals"), provenance=fact["provenance"],
                inherited_from=fact["inherited_from"]))
    errors = collected["errors"]
    doc = dict(
        census_version=CENSUS_VERSION, schema="census_v0",
        document=dict(cik=str(meta["cik"]).zfill(10), report_date=meta["report_date"],
                      accession_number=meta.get("accession_number"), form_type=meta.get("form_type"),
                      role=meta.get("role"), path=collected["source"]["path"],
                      sha256_before=collected["source"]["sha256_before"],
                      sha256_after=collected["source"]["sha256_after"],
                      bytes=collected["source"]["bytes"]),
        bounds=asdict(bounds),
        collection=dict(state=collection_state(channels, errors), errors=errors,
                        elapsed_seconds=collected["elapsed_seconds"]),
        channels=channels,
        document_metadata=dict(
            document_period_end_dates=dped,
            document_types=sorted({str(f["value"]) for f in facts if f["field"] == "document_type"}),
            entity_identifiers=sorted({c["entity"]["identifier"] for c in contexts}),
            note="DocumentPeriodEndDate is filing metadata; comparative periods come from contexts"),
        periods=_periods(contexts, facts, dped),
        units=collected["units"], contexts=contexts, facts=facts,
        footnotes=collected["footnotes"], concept_mappings=mappings,
        dependencies=dependency_records(aggregate_markers, grammar),
        positions=positions, conflicts=conflicts, fund_income=fund_income, fund_balance=fund_balance,
        notes=["observation_id is a source observation id, not a cross-quarter position id",
               "raw BDC rates are decimals as reported; no scale conversion is applied here",
               "values are never read from a wrapper"])
    doc["detectors"] = census_detect.detect_structure(doc, collected["_texts"],
                                                      aggregate_markers=aggregate_markers,
                                                      learned_predicates=learned_predicates,
                                                      grammar=grammar)
    doc["metrics"] = [
        _metric("contexts", len(contexts), ["contexts"], channels),
        _metric("facts", len(facts), ["numeric_facts", "text_facts"], channels),
        _metric("position_observations", len(positions), ["contexts", "numeric_facts"], channels),
        _metric("conflicts", len(conflicts), ["numeric_facts", "text_facts"], channels),
        _metric("fund_income_facts", len(fund_income), ["numeric_facts"], channels),
        _metric("unknown_facts", sum(f["field"] is None for f in facts), ["numeric_facts", "text_facts"],
                channels),
        _metric("footnote_resources", len(doc["footnotes"]["resources"]), ["footnotes"], channels),
    ]
    roles: dict[str, int] = {}
    for context in contexts:
        roles[context.get("role", "unclassified")] = roles.get(context.get("role", "unclassified"), 0) + 1
    doc["summary"] = dict(
        contexts=len(contexts), facts=len(facts), position_observations=len(positions),
        position_observations_current=sum((p["period"].get("instant") in dped) for p in positions),
        conflicts=len(conflicts), unknown_facts=sum(f["field"] is None for f in facts),
        unresolved_context_facts=sum(not f["context_resolved"] for f in facts),
        roles=roles, periods=len(doc["periods"]),
        comparative_periods=sum(p["relation"] == "comparative" for p in doc["periods"]),
        detector_counts={name: det["counts"] for name, det in doc["detectors"].items()},
        detector_findings={name: _finding_counts(det["outcomes"]) for name, det in doc["detectors"].items()})
    return doc


def _finding_counts(outcomes: list) -> dict:
    counts: dict[str, int] = {}
    for item in outcomes:
        key = item["outcome"] + ":" + item["finding"]
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def dumps_census(doc: dict) -> str:
    return json.dumps(doc, indent=2, sort_keys=True, ensure_ascii=True, allow_nan=False) + "\n"


# ---------------------------------------------------------------- validation

def _schema_validator():
    import jsonschema
    schema = json.loads(SCHEMA_PATH.read_text(encoding="ascii"))
    return jsonschema.Draft202012Validator(schema)


def validate_census(doc: dict) -> dict:
    """JSON Schema plus semantic checks the schema cannot express."""
    from scripts.profile_pilot import envelope
    errors = [_ascii("schema: " + "/".join(map(str, e.absolute_path)) + ": " + e.message)[:300]
              for e in list(_schema_validator().iter_errors(doc))[:50]]
    if errors:
        return dict(ok=False, errors=errors)
    channels = doc["channels"]
    state = collection_state(channels, doc["collection"]["errors"])
    if state != doc["collection"]["state"]:
        errors.append("collection state " + doc["collection"]["state"] + " disagrees with channels (" + state + ")")
    for name, detector in doc["detectors"].items():
        counts = {k: 0 for k in ("candidate", "resolved", "insufficient_evidence")}
        for outcome in detector["outcomes"]:
            counts[outcome["outcome"]] += 1
            incomplete = [c for c in outcome["depends_on_channels"] if channels[c]["state"] != "complete"]
            if outcome["finding"] == "not_observed_in_complete_instance" and incomplete:
                errors.append("absence claim on incomplete channel(s) " + ",".join(incomplete)
                              + " in " + name)
            if outcome["outcome"] == "resolved" and incomplete and outcome["finding"] != "observed":
                errors.append("resolved " + name + " outcome depends on incomplete channel(s) "
                              + ",".join(incomplete))
            for predicate in outcome["evidence"].get("predicates", []) if isinstance(
                    outcome["evidence"], dict) else []:
                try:
                    envelope.check_predicate(predicate)
                except envelope.PredicateError as exc:
                    errors.append("partition predicate rejected: " + str(exc))
        if counts != detector["counts"]:
            errors.append("detector " + name + " counts disagree with outcomes")
    return dict(ok=not errors, errors=errors)
