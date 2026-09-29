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
import re

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



# ---------------------------------------------------------------- Task B2-3: rate text (generic patterns)
#
# Re-derived from the owner-session semantic census (2026-09-29) and hardened with negatives:
# a base token followed by "+ d.dd%" (percent spread) or "+ ddd/dddd" (bps spread); a bare
# "d.dd%" only when the text after it is a rate word or a delimiter (never an issuer name such
# as "1.5% Club Holdings"); a percentage marked PIK ("12.00% PIK", "PIK 12.00%") is a PIK
# rate and is never read as the cash rate.

BASE_TOKENS = ("TERM SOFR", "SOFR", "SONIA", "EURIBOR", "LIBOR", "PRIME", "BSBY", "CDOR", "S", "L", "E", "P")
_BASE = r"(?:TERM\s*SOFR|SOFR|SONIA|EURIBOR|LIBOR|PRIME|BSBY|CDOR|S|L|E|P)"
_LEAD = r"(?<![A-Za-z0-9&+.])"
_TENOR = r"(?:\s*\([^)]{0,20}\))?"
RE_BASE_PLUS_PCT = re.compile(_LEAD + _BASE + _TENOR + r"\s*\+\s*(\d{1,2}(?:\.\d{1,4})?)\s*%", re.I)
# 100..1999 bps: a four-digit 2xxx is a year ("Series S+ 2023 Notes"), never a spread
RE_BASE_PLUS_BPS = re.compile(_LEAD + _BASE + _TENOR + r"\s*\+\s*(1\d{3}|\d{3})(?![\d.,/%-])(?!\s*%)", re.I)
RE_PCT = re.compile(r"(?<![\d.+])(\d{1,2}(?:\.\d{1,4})?)\s*%")
RE_UNDRAWN = re.compile(r"\b(?:undrawn|unfunded|unused|delayed[\s-]*draw|delayed\s+tl|ddtl|revolv\w*)\b", re.I)
RE_PIK_AFTER = re.compile(r"\s*\(?\s*PIK\b", re.I)
RE_PIK_BEFORE = re.compile(r"\bPIK\s*[:\-]?\s*\(?\s*$", re.I)
RATE_WORDS = frozenset({"cash", "fixed", "interest", "rate", "coupon", "senior", "sr", "notes", "note", "due", "all",
                        "total", "current", "per", "pik", "payable", "and", "or", "plus", "floor", "spread",
                        "toggle", "paid", "pa", "p", "min", "max", "cap", "default"})
TEXT_MATCH_TOL_PCT = 0.011
GENERIC_PARSER = dict(kind="generic", patterns=["RE_BASE_PLUS_PCT", "RE_BASE_PLUS_BPS", "RE_PCT"],
                      provenance="derived")


def _rate_pct(text: str, match) -> str | None:
    """'cash' / 'pik' for a bare percentage that reads as a rate; None when it is part of a name."""
    before, after = text[:match.start()], text[match.end():]
    if RE_PIK_AFTER.match(after) or RE_PIK_BEFORE.search(before):
        return "pik"
    word = re.match(r"\s*\(?\s*([A-Za-z][A-Za-z\-]*)", after)
    if word is None:
        return "cash"
    token = word.group(1).lower().split("-")[0]
    return "cash" if token in RATE_WORDS else None


def parse_rate_text(text: str) -> dict:
    """Generic base-plus-spread / bare-percent reading of one identifier (spread and pcts in percent)."""
    text = text or ""
    out = dict(parser="generic", category="no_rate_text", spread=None, cash_pcts=[], pik_pcts=[],
               undrawn_marker=bool(RE_UNDRAWN.search(text)))
    m_pct, m_bps = RE_BASE_PLUS_PCT.search(text), RE_BASE_PLUS_BPS.search(text)
    spans = []
    if m_pct and (not m_bps or m_pct.start() <= m_bps.start()):
        out["spread"], spans = round(float(m_pct.group(1)), 4), [m_pct.span()]
    elif m_bps:
        out["spread"], spans = round(float(m_bps.group(1)) / 100.0, 4), [m_bps.span()]
    for m in RE_PCT.finditer(text):
        if any(a <= m.start() < b for a, b in spans):
            continue
        kind = _rate_pct(text, m)
        if kind:
            out[kind + "_pcts"].append(round(float(m.group(1)), 4))
    if out["spread"] is not None:
        out["category"] = "base_plus_spread"
    elif out["cash_pcts"]:
        out["category"] = "bare_pct"
    elif out["pik_pcts"]:
        out["category"] = "pik_pct_only"
    return out


def grammar_rate_text(text: str, grammar: dict) -> dict:
    """The authored grammar's reading of one identifier (inherited: pipeline.identifier_rate.apply_grammar)."""
    from pipeline.identifier_rate import apply_grammar
    parsed = apply_grammar(text or "", grammar["body"])
    spread = parsed.get("basis_spread")
    rate = next((parsed.get(k) for k in ("interest_rate", "interest_rate_cash_leg", "interest_rate_all_in")
                 if isinstance(parsed.get(k), (int, float))), None)
    pik = parsed.get("pik_rate") if isinstance(parsed.get("pik_rate"), (int, float)) else None
    out = dict(parser="grammar", category="no_rate_text", spread=None, cash_pcts=[], pik_pcts=[],
               undrawn_marker=bool(RE_UNDRAWN.search(text or "")))
    if isinstance(spread, (int, float)):
        out.update(category="base_plus_spread", spread=round(float(spread), 4))
        if rate is not None:
            out["cash_pcts"] = [round(float(rate), 4)]
    elif rate is not None:
        out.update(category="bare_pct", cash_pcts=[round(float(rate), 4)])
    elif pik is not None:
        out["category"] = "pik_pct_only"
    if pik is not None:
        out["pik_pcts"] = [round(float(pik), 4)]
    return out


# ---------------------------------------------------------------- Task B2-3: row-level rate values

def _magnitude(value: Decimal) -> str:
    return "zero" if value == 0 else ("lt1" if abs(value) < 1 else "ge1")


def row_value(position: dict, field: str, facts_by_i: dict, units: dict):
    """(status, number, declared class) of one field on one row; number None when not numeric."""
    value = position["fields"].get(field) or {"status": "absent"}
    status = value.get("status")
    if status in UNOBSERVABLE:
        return "unobservable", None, None
    if status not in FILLED:
        return "unfilled", None, None
    indices = value.get("fact_indices") or []
    cls = scale_class(facts_by_i.get(indices[0]) if indices else None, units)
    return "filled", _decimal(value.get("value")), cls


def canonical_one(number: Decimal, cls: str, conventions: dict) -> float:
    return float(number * Decimal(str(conventions[cls]["factor"])))


def observe_composition(doc: dict, positions: list, facts_by_i: dict, conventions: dict) -> dict:
    """Implied base (rate - spread) per row carrying both fields, with magnitude resolved PER ROW.

    Same magnitude class on the row (or a zero): computed (canonical percent when both declared
    units are ratio classes; raw when both carry the same non-ratio unit class). Different
    magnitudes: computed only when the two declared ratio classes differ (the declared units
    explain it); otherwise the row is `unresolved_pair` (never guessed). A 0 rate is an
    undrawn/unfunded placeholder, not a composition: counted apart."""
    units = doc.get("units") or {}
    out = dict(pair_rows=0, resolved=[], basis={}, unresolved_keys=[], unobservable_keys=[], zero_rate_keys=[])
    for p in positions:
        ctx = p["context_id"]
        rs, rv, rc = row_value(p, "interest_rate", facts_by_i, units)
        ss, sv, sc = row_value(p, "basis_spread", facts_by_i, units)
        if "unobservable" in (rs, ss):
            out["unobservable_keys"].append(ctx)
            continue
        if rv is None or sv is None:
            continue
        if rv == 0:
            out["zero_rate_keys"].append(ctx)
            continue
        out["pair_rows"] += 1
        same = _magnitude(rv) == _magnitude(sv) or "zero" in (_magnitude(rv), _magnitude(sv))
        declared = rc in RATIO_CLASSES and sc in RATIO_CLASSES
        if declared and (same or rc != sc):
            base, basis = canonical_one(rv, rc, conventions) - canonical_one(sv, sc, conventions), "canonical_percent"
        elif same and rc == sc and rc not in RATIO_CLASSES:
            base, basis = float(rv - sv), "raw_" + str(rc)
        else:
            out["unresolved_keys"].append(ctx)
            continue
        out["resolved"].append((ctx, round(base, 10)))
        out["basis"][basis] = out["basis"].get(basis, 0) + 1
    out["n"] = len(out["resolved"])
    out["unresolved_share"] = round(len(out["unresolved_keys"]) / out["pair_rows"], 6) if out["pair_rows"] else 0.0
    ordered = sorted(v for _, v in out["resolved"])
    out["share_rate_le_spread"] = round(sum(v <= 0 for v in ordered) / len(ordered), 6) if ordered else None
    for name, q in (("p25", 0.25), ("p50", 0.5), ("p75", 0.75)):
        out[name] = round(quantile(ordered, q), 10) if ordered else None
    out["iqr"] = round(out["p75"] - out["p25"], 10) if ordered else None
    return out


TEXT_SHARES = ("spread_text_matches_numeric", "rate_equals_text_spread", "rate_equals_text_pct")


def observe_text(doc: dict, positions: list, facts_by_i: dict, conventions: dict, grammar: dict | None, *,
                 tol_pct: float = TEXT_MATCH_TOL_PCT) -> dict:
    """Identifier rate text against the numeric interest_rate / basis_spread, per row category.

    Numeric values are canonical percent under the DECLARED unit (a non-ratio unit is not
    compared: counted as numeric_unit_unresolved). Rows carrying a filled numeric rate or
    spread and a non-label identifier are the parse-share denominator. A 0 rate against a
    text spread on an undrawn/unfunded row (marker in the text, or a 0.00 text spread) is
    excluded from rate_equals_text_spread and counted as undrawn_zero_rate."""
    from pipeline.identifier_rate import normalize_rate_pct
    units = doc.get("units") or {}
    shares = {name: dict(n=0, hits=0, hit_keys=[], miss_keys=[]) for name in TEXT_SHARES}
    evidence_rate_spread = dict(n=0, hits=0)
    out = dict(identifier_rows=0, debt_rows=0, parsed_rows=0, categories={}, undrawn_zero_rate_keys=[],
               numeric_unit_unresolved=0, unobservable_keys=[],
               parser=GENERIC_PARSER if grammar is None else dict(
                   kind="grammar", grammar_sha256=grammar["sha256"], dialect=grammar["dialect"], path=grammar["path"],
                   provenance="inherited"))
    for p in positions:
        text = p["identity"].get("typed_identifier")
        if not text or LABEL_RE.match(text):
            continue
        out["identifier_rows"] += 1
        ctx = p["context_id"]
        rs, rv, rc = row_value(p, "interest_rate", facts_by_i, units)
        ss, sv, sc = row_value(p, "basis_spread", facts_by_i, units)
        if "unobservable" in (rs, ss):
            out["unobservable_keys"].append(ctx)
        if rv is None and sv is None:
            continue
        out["debt_rows"] += 1
        parsed = grammar_rate_text(text, grammar) if grammar is not None else parse_rate_text(text)
        out["categories"][parsed["category"]] = out["categories"].get(parsed["category"], 0) + 1
        if parsed["category"] == "no_rate_text":
            continue
        out["parsed_rows"] += 1
        rate = canonical_one(rv, rc, conventions) if rv is not None and rc in RATIO_CLASSES else None
        spread = canonical_one(sv, sc, conventions) if sv is not None and sc in RATIO_CLASSES else None
        out["numeric_unit_unresolved"] += (rv is not None and rate is None) or (sv is not None and spread is None)

        def mark(name, hit, ctx=ctx):
            slot = shares[name]
            slot["n"] += 1
            slot["hits"] += bool(hit)
            slot["hit_keys" if hit else "miss_keys"].append(ctx)
        if parsed["category"] == "base_plus_spread":
            t = parsed["spread"]
            if spread is not None:
                mark("spread_text_matches_numeric", abs(spread - t) <= tol_pct)
            if rate is not None:
                if rate == 0 and (parsed["undrawn_marker"] or t == 0):
                    out["undrawn_zero_rate_keys"].append(ctx)
                else:
                    mark("rate_equals_text_spread", abs(rate - t) <= tol_pct)
            if rv is not None and rv != 0:
                evidence_rate_spread["n"] += 1
                evidence_rate_spread["hits"] += abs(normalize_rate_pct(str(rv)) - t) <= tol_pct
        elif parsed["category"] == "bare_pct" and rate is not None:
            mark("rate_equals_text_pct", any(abs(rate - x) <= tol_pct for x in parsed["cash_pcts"]))
    for slot in shares.values():
        slot["share"] = round(slot["hits"] / slot["n"], 6) if slot["n"] else None
    out["shares"] = shares
    out["parse_share"] = round(out["parsed_rows"] / out["debt_rows"], 6) if out["debt_rows"] else None
    ev = evidence_rate_spread
    out["rate_equals_text_spread_magnitude_normalised"] = dict(
        n=ev["n"], share=round(ev["hits"] / ev["n"], 6) if ev["n"] else None,
        rule="evidence only: raw rate normalised by magnitude (pipeline.identifier_rate.normalize_rate_pct, the "
             "grammar twin rule), so a filer whose rate is mixed-magnitude under one unit stays visible")
    return out
