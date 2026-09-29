"""Task 8 observation layer: what one census says about a field, an identifier dialect or a partition.

Split out of contracts.py along its seam (observation vs learn/freeze/evaluate). Pure
functions over one census document: current positions, per-field fill / concepts /
declared scale / magnitudes, the inherited identifier grammar applied per row, partition
predicates learned from Q1 detector outcomes, and row routing through
envelope.resolve_for_row (predicate evaluation is never re-implemented here).

Scale: the declared unit class (pure / percent / bps) plus a deterministic conversion to
percent. Namespace never identifies scale; magnitudes are reported so the caller can
ABSTAIN on mixed or changed magnitude regimes, never to assign a scale.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
import hashlib
import json

from scripts.profile_pilot import envelope
from scripts.profile_pilot.census_detect import LABEL_RE, _grammar_rows

WHOLE_FILING = "whole_filing"
FILLED = ("reported", "consistent_duplicate")
UNOBSERVABLE = ("unobservable", "not_collected")
IDENTIFIER_FIELD = "investment_identifier"
RATIO_CLASSES = ("pure", "percent", "bps")
UNIT_NOT_OBSERVABLE = "unit_not_observable"
PERCENT_MEASURES = frozenset({"percent", "pct", "percentage"})
BPS_MEASURES = frozenset({"bps", "bp", "basispoint", "basispoints"})
NO_SIGNATURE_FINDINGS = ("too_few_identifiers",)
SCALE_CONVENTIONS = {
    "pure": dict(canonical_unit="percent", factor="100",
                 declared_by="unit measure xbrli:pure: a ratio entered as a decimal fraction (0.095 = 9.5%)"),
    "percent": dict(canonical_unit="percent", factor="1", declared_by="unit measure named percent/pct"),
    "bps": dict(canonical_unit="percent", factor="0.01", declared_by="unit measure named bps/basis points")}


def _sha12(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode("ascii")).hexdigest()[:12]


# ---------------------------------------------------------------- census observations

def current_positions(doc: dict) -> list:
    dped = set(doc["document_metadata"]["document_period_end_dates"])
    return [p for p in doc["positions"] if p["period"].get("instant") in dped]


def _decimal(value):
    try:
        out = Decimal(str(value).strip())
    except (InvalidOperation, ValueError, TypeError):
        return None
    return out if out.is_finite() else None


def scale_class(fact: dict | None, units: dict) -> str:
    """Declared unit class of the fact behind a filled field.

    A filled field with no fact index cannot show its unit: that is UNIT_NOT_OBSERVABLE
    (inability to observe -> insufficient_evidence downstream), never `unresolved_unit`
    (a unit that WAS observed but is not a recognised ratio/monetary/shares unit)."""
    if not fact:
        return UNIT_NOT_OBSERVABLE
    if fact.get("value_kind") != "numeric":
        return "text"
    if fact.get("unit_kind") in ("monetary", "shares"):
        return fact["unit_kind"]
    unit = units.get(fact.get("unit_ref")) or {}
    measures = [str(m).rsplit(":", 1)[-1].lower() for m in unit.get("measures") or []]
    if measures == ["pure"]:
        return "pure"
    if len(measures) == 1 and measures[0] in PERCENT_MEASURES:
        return "percent"
    if len(measures) == 1 and measures[0] in BPS_MEASURES:
        return "bps"
    return "unresolved_unit"


def _regime(values: list):
    nonzero = [abs(v) for _, v, _ in values if v != 0]
    if not values:
        return None
    if not nonzero:
        return "zero_only"
    below = sum(v < 1 for v in nonzero)
    return "lt1" if below == len(nonzero) else ("ge1" if below == 0 else "mixed")


def channel_gaps(doc: dict, channels) -> list:
    gaps = [] if doc.get("collection", {}).get("state") != "failed" else ["collection:failed"]
    for name in channels:
        state = doc["channels"].get(name, {}).get("state")
        if state != "complete":
            gaps.append(name + ":" + str(state))
    return gaps


def observe_field(doc: dict, positions: list, field: str, facts_by_i: dict) -> dict:
    obs = dict(rows=len(positions), row_keys=[p["context_id"] for p in positions], filled_keys=[], absent_keys=[],
               nil_keys=[], unobservable_keys=[], conflicts=[], concept_keys={}, class_keys={}, values=[],
               decimals={})
    for p in positions:
        value = p["fields"].get(field) or {"status": "absent"}
        status, ctx = value.get("status"), p["context_id"]
        if status in FILLED:
            obs["filled_keys"].append(ctx)
            for concept in value.get("concepts") or []:
                obs["concept_keys"].setdefault(concept, []).append(ctx)
            indices = value.get("fact_indices") or []
            cls = scale_class(facts_by_i.get(indices[0]) if indices else None, doc.get("units") or {})
            obs["class_keys"].setdefault(cls, []).append(ctx)
            number = _decimal(value.get("value")) if cls in RATIO_CLASSES else None
            if cls in RATIO_CLASSES and number is not None:
                obs["values"].append((ctx, number, cls))
            obs["decimals"][str(value.get("decimals"))] = obs["decimals"].get(str(value.get("decimals")), 0) + 1
        elif status in UNOBSERVABLE:
            obs["unobservable_keys"].append(ctx)
        elif status == "conflict":
            obs["conflicts"].append(dict(context_id=ctx, reason=value.get("reason")))
        elif status == "nil":
            obs["nil_keys"].append(ctx)
        else:
            obs["absent_keys"].append(ctx)
    obs["filled"] = len(obs["filled_keys"])
    obs["fill_share"] = round(obs["filled"] / obs["rows"], 6) if obs["rows"] else None
    obs["concepts"] = sorted(obs["concept_keys"])
    obs["classes"] = {k: len(v) for k, v in sorted(obs["class_keys"].items())}
    obs["regime"] = _regime(obs["values"])
    obs["zero_values"] = sum(v == 0 for _, v, _ in obs["values"])
    return obs


def canonical(values: list, cls: str, conventions: dict) -> list:
    """Canonical percent values under the given (FROZEN) conventions; SCALE_CONVENTIONS here only
    seeds the tolerance file."""
    factor = Decimal(str(conventions[cls]["factor"]))
    return [(ctx, float(v * factor)) for ctx, v, c in values if c == cls]


def quantile(sorted_values: list, q: float) -> float:
    """Linear interpolation between closest ranks (numpy's default method)."""
    position = (len(sorted_values) - 1) * q
    lo = int(position)
    hi = min(lo + 1, len(sorted_values) - 1)
    return sorted_values[lo] + (sorted_values[hi] - sorted_values[lo]) * (position - lo)


def widened(lo: float, hi: float, w: float) -> list:
    if hi > lo:
        span = hi - lo
        return [round(lo - w * span, 10), round(hi + w * span, 10)]
    return [round(lo - w * abs(lo), 10), round(hi + w * abs(hi), 10)]


# ---------------------------------------------------------------- grammar (inherited)

def grammar_info(body: dict, *, path: str, sha256: str, anchors) -> dict:
    applies = body.get("applies_to") or {}
    dialect = str(applies.get("signature") or body.get("dominant_signature") or "grammar")
    signatures = list(applies.get("signatures") or [dialect])
    return dict(body=body, path=path, sha256=sha256, anchors=anchors, dialect=dialect, signatures=signatures,
                required_fields=list(body.get("required_fields") or []))


def grammar_observation(rows: list, grammar: dict) -> dict:
    """The authored grammar applied per row inside its declared keyword-signature scope."""
    from pipeline.identifier_rate import apply_grammar, evaluate_invariants
    from pipeline.identifier_signature import keyword_signature
    body, required = grammar["body"], grammar["required_fields"]
    idents = [r for r in rows if r.get("investment_identifier") and not LABEL_RE.match(r["investment_identifier"])]
    scope, violating, invariants = [], [], {}
    for row in idents:
        text = row["investment_identifier"]
        if keyword_signature(text, grammar["anchors"]) not in grammar["signatures"]:
            continue
        scope.append(row["context_id"])
        parsed = apply_grammar(text, body)
        missing = [f for f in required if parsed.get(f) is None]
        ok = not missing if required else any(v is not None for v in parsed.values())
        if not ok:
            violating.append(dict(context_id=row["context_id"], identifier=text[:200],
                                  missing_fields=missing or ["any"]))
        for name, verdict in evaluate_invariants(parsed, row.get("twins") or {}, body).items():
            key = name + ":" + verdict
            invariants[key] = invariants.get(key, 0) + 1
    parsed_rows = len(scope) - len(violating)
    return dict(field=IDENTIFIER_FIELD, dialect=grammar["dialect"], signatures=grammar["signatures"],
                required_fields=required, identifier_rows=len(idents), scope_rows=len(scope),
                scope_share=round(len(scope) / len(idents), 6) if idents else None, parsed_rows=parsed_rows,
                parse_share=round(parsed_rows / len(scope), 6) if scope else None, violating=violating,
                invariant_counts=dict(sorted(invariants.items())), provenance="inherited",
                inherited_from=grammar["path"] + " via pipeline/identifier_rate.py:apply_grammar",
                grammar_sha256=grammar["sha256"],
                note="delimiter/segment structure alone proves identifier structure only; this is the grammar")


# ---------------------------------------------------------------- partitions and routing

def _twins(position: dict) -> dict:
    def number(name):
        value = _decimal((position["fields"].get(name) or {}).get("value"))
        return float(value) if value is not None else None
    maturity = (position["fields"].get("maturity_date") or {}).get("value")
    return dict(interest_rate=number("interest_rate"), basis_spread=number("basis_spread"),
                pik_rate=number("pik_rate"), maturity_date=maturity if isinstance(maturity, str) else None)


def as_grammars(grammar) -> list:
    """None, one grammar_info, or a list of them (one per authored dialect)."""
    if not grammar:
        return []
    return list(grammar) if isinstance(grammar, (list, tuple)) else [grammar]


def grammar_for(applies_to: dict | None, grammars: list) -> tuple[dict | None, str | None]:
    """The dialect grammar a partition's format contract uses, or the cause it has none."""
    if not grammars:
        return None, "no_authored_grammar"
    if applies_to and applies_to.get("kind") == "grammar_dialect":
        hits = [g for g in grammars if g["dialect"] == applies_to["dialect"]]
        return (hits[0], None) if len(hits) == 1 else (None, "no_single_grammar_for_dialect")
    if len(grammars) == 1:
        return grammars[0], None
    return None, "several_dialects_without_dialect_partition"


def routing_rows(doc: dict, positions: list, grammar) -> list:
    fv_concepts: dict = {}
    for p in positions:
        concepts = (p["fields"].get("fair_value") or {}).get("concepts") or []
        fv_concepts[p["context_id"]] = concepts[0] if len(concepts) == 1 else None
    rows = [dict(context_id=p["context_id"], investment_identifier=p["identity"].get("typed_identifier"),
                 dimensions=[list(d) for d in p["identity"].get("dimensions") or []],
                 fair_value_concept=fv_concepts[p["context_id"]], twins=_twins(p)) for p in positions]
    grammars = as_grammars(grammar)
    labelled = [r for r in rows if r["investment_identifier"]]
    if len(grammars) == 1:
        g = grammars[0]
        _grammar_rows(labelled, dict(path=g["path"], sha256=g["sha256"], body=g["body"]))
    elif grammars:
        # One label per row: the unique authored dialect that parses it (census_detect rule per
        # grammar); none -> "unparsed", several -> "ambiguous:" + names (matches no dialect).
        parses: dict = {}
        for g in grammars:
            probe = [dict(investment_identifier=r["investment_identifier"]) for r in labelled]
            _grammar_rows(probe, dict(path=g["path"], sha256=g["sha256"], body=g["body"]))
            for r, p in zip(labelled, probe):
                if p.get("grammar_dialect") == g["dialect"]:
                    parses.setdefault(r["context_id"], []).append(g["dialect"])
        for r in labelled:
            names = sorted(parses.get(r["context_id"], []))
            r["grammar_dialect"] = names[0] if len(names) == 1 else (
                "ambiguous:" + "+".join(names) if names else "unparsed")
    return rows


def learn_partitions(q1_doc: dict, profile_entries: list) -> dict:
    """Partitions from Q1 evidence only: evidenced_partition predicates + non-null profile applies_to."""
    outcomes = q1_doc["detectors"]["partition"]["outcomes"]
    predicates, sources = [], []
    for item in outcomes:
        if item["outcome"] == "resolved" and item["finding"] == "evidenced_partition":
            for predicate in item["evidence"].get("predicates") or []:
                predicates.append(predicate)
                sources.append("census partition detector (" + str(item.get("provenance")) + ")")
    for entry in profile_entries:
        if entry.get("applies_to") is not None:
            predicates.append(entry["applies_to"])
            sources.append("q1 profile entry " + entry["entry_id"])
    partitions, seen = [], set()
    for predicate, source in zip(predicates, sources):
        envelope.check_predicate(predicate)
        tag = _sha12(predicate)
        if tag in seen:
            continue
        seen.add(tag)
        partitions.append(dict(partition_id="p" + tag, applies_to=predicate, source=source))
    partitions.append(dict(partition_id=WHOLE_FILING, applies_to=None,
                           source="null partition: rows no evidenced predicate selects"))
    mixed = [dict(outcome=o["outcome"], finding=o["finding"], signature=(o.get("subject") or {}).get("signature"))
             for o in outcomes if o["outcome"] != "resolved" and o["finding"] not in NO_SIGNATURE_FINDINGS
             and ((o.get("subject") or {}).get("signature") or {}).get("kind") not in (None, "none")]
    return dict(partitions=partitions, evidenced=len(partitions) > 1,
                identifier_format=dict(status="unresolved_mixed" if mixed else "no_unresolved_mixture",
                                       unresolved=mixed,
                                       outcomes=[dict(outcome=o["outcome"], finding=o["finding"]) for o in outcomes]))


def route(partitions: list, rows: list, report_date: str, form_type, recorded_at: str) -> dict:
    """Route rows to frozen partitions via envelope.resolve_for_row; ambiguity is never picked."""
    entries = [dict(entry_id=p["partition_id"], key="contract_partition", applies_to=p["applies_to"],
                    form_type=None, valid_from=None, valid_to=None, recorded_at=recorded_at, recorded_until=None)
               for p in partitions]
    routed = {p["partition_id"]: [] for p in partitions}
    ambiguous, unroutable = [], []
    for row in rows:
        try:
            hit = envelope.resolve_for_row(entries, row, "contract_partition", report_date, form_type, None)
        except envelope.AmbiguousResolutionError:
            matched = [p["partition_id"] for p in partitions
                       if p["applies_to"] is not None and envelope.predicate_matches(p["applies_to"], row)]
            ambiguous.append(dict(context_id=row["context_id"], partitions=matched))
            continue
        except envelope.PredicateEvaluationError as exc:
            unroutable.append(dict(context_id=row["context_id"], error=str(exc)[:200]))
            continue
        routed[hit.entry["entry_id"]].append(row["context_id"])
    return dict(routed=routed, ambiguous=ambiguous, unroutable=unroutable)
