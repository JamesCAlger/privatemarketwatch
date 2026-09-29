"""Task 6: M1 derivation-rate scoring against the hand-authored wrapper (spec 6.2, 9).

This is the ONLY pilot module that loads a comparison wrapper (`load_wrapper`). The
derivation module (profile.py) never imports it.

Comparison semantics are data: `FAMILIES` and the rules below are frozen, with the
per-CIK assignment of every wrapper key of the fixed denominator
(`inventories/wrapper_key_inventory.json`), into
`inventories/m1_comparison_semantics.json` BEFORE any profile is derived
(`freeze_semantics`). Scoring reads that frozen file (`load_semantics`), never the
in-code declaration.

Classes (exactly one per denominator key): exact, partial, inherited, unresolved
(reason: candidate | insufficient_evidence | no_observation | not_implemented), miss
(a contradictory census proposal only), not_derivable. The scorer reads classes, reasons,
families, equivalence and legal-form tokens from the frozen file and fails closed if any is
missing.
`partial` is never added to `exact`. Scalars are exact or miss; `partial` is reserved
for collections and near-equal strings (subset, overlap, same prefixes with different
families, same delimiter token with different padding, same name up to case and legal
form). Missing AND extra values are compared. Order is significant only where the
consumer's behaviour uses it (prefix_rules, fallback patterns, field_order).

M1 measures how much of a hand-authored wrapper an independent census derivation
reproduces. It is not evidence that either the wrapper or the profile is correct.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
import hashlib
import json
from pathlib import Path
import re

from scripts.profile_pilot.census_detect import DELIMITERS
from scripts.profile_pilot.manifest import StageInvalidated, digest
from scripts.profile_pilot.paths import PilotPaths, confined, write_once_json

SEMANTICS_VERSION = "m1-semantics.v2"
SEMANTICS_RELATIVE = "inventories/m1_comparison_semantics.json"
CLASSES = ("exact", "partial", "inherited", "unresolved", "miss", "not_derivable")
# Unresolved reasons in precedence order (first present wins, for stubs and rollups).
REASONS = ("candidate", "insufficient_evidence", "no_observation", "not_implemented")
# Every field the scorer reads from the frozen file; a missing one fails closed.
REQUIRED_FIELDS = ("classes", "reasons", "families", "equivalence", "legal_form_tokens", "assignments")
DISCLAIMER = ("M1 is a derivation-rate measurement against hand-authored wrappers. It is not "
              "evidence that the wrapper, the census or the profile is correct.")
HEADER_KEYS = ("schema_version", "cik", "entity_name", "version", "source")
LEGAL_FORM_TOKENS = ("inc", "incorporated", "corp", "corporation", "llc", "lp", "ltd", "limited", "co",
                     "company", "plc")
# Imported concept -> field vocabulary (pipeline/extract_companyfacts.py, investments_at_fair_value
# exact + fallback concepts). An equality reached only through this table rests on inherited code:
# it is scored `inherited`, never `exact`; the file hash is frozen with the table.
EQUIVALENCE = {"invariants.fv_reconciliation.source_field": {
    "mapping": {"investments_at_fair_value": ["InvestmentOwnedAtFairValue", "InvestmentsAtFairValueAggregate",
                                              "InvestmentsFairValueDisclosure"]},
    "source": "pipeline/extract_companyfacts.py"}}
CODE_ROOT = Path(__file__).resolve().parents[2]

# Ordered: the first family whose match specs accept a key owns it.
FAMILIES = [
    dict(id="header_metadata", match=[dict(exact=["schema_version", "version", "source"])],
         comparison="not_derivable", derivation="not_derivable",
         note="wrapper artefact bookkeeping; no filer structure behind it"),
    dict(id="cik", match=[dict(exact=["cik"])], comparison="exact_cik", derivation="implemented",
         profile_key="fund_level_concepts.entity_cik", canonical="10-digit zero-padded string"),
    dict(id="entity_name", match=[dict(exact=["entity_name"])], comparison="name", derivation="implemented",
         profile_key="fund_level_concepts.entity_registrant_name",
         canonical="whitespace collapsed; partial = equal after casefold, punctuation and legal-form removal"),
    dict(id="identifier_delimiter", match=[dict(exact=["identifier_format.delimiter"])], comparison="delimiter",
         derivation="implemented", profile_key="identifier_format.delimiter", vocabulary=list(DELIMITERS),
         canonical="exact string incl. padding; partial = same token, different padding; a wrapper value "
                   "whose token is outside the census delimiter vocabulary is unresolved/not_implemented"),
    dict(id="identifier_alternates", match=[dict(exact=["identifier_format.alternate_delimiters"])],
         comparison="string_set", casefold=False, derivation="not_implemented",
         profile_key="identifier_format.alternate_delimiters", canonical="set of exact strings (no consumer "
                                                                          "uses the order)"),
    dict(id="identifier_field_order", match=[dict(exact=["identifier_format.field_order"])],
         comparison="ordered_list", derivation="not_implemented", profile_key="identifier_format.field_order",
         canonical="ordered list of field names"),
    dict(id="aggregate_markers", match=[dict(exact=["dispatch.aggregate_markers"])],
         comparison="substring_markers", derivation="implemented",
         profile_key="subtotals_and_headings.aggregate_labels",
         canonical="wrapper = lower-cased substring markers matched with any(); derived = full lower-cased "
                   "labels of observed structural subtotals. Observed labels cannot reproduce a marker set, "
                   "so exact is unreachable: every derived label covered by some marker (and at least one) -> "
                   "partial; some labels uncovered -> partial if any is covered, else miss. `extra` = labels "
                   "no marker covers (contradiction), `missing` = markers matching no observed label "
                   "(unobserved, not contradiction)"),
    dict(id="non_private_markers", match=[dict(exact=["dispatch.non_private_markers"])], comparison="string_set",
         casefold=True, derivation="not_implemented", profile_key="subtotals_and_headings.non_private_markers",
         canonical="set of lower-cased substrings"),
    dict(id="prefix_rules_mapping", match=[dict(exact=["dispatch.prefix_rules"])], whole_value=True,
         comparison="ordered_pairs", derivation="not_implemented", profile_key="subtotals_and_headings.prefix_rules",
         canonical="ordered [prefix, family] pairs (first startswith match wins); prefix presence without "
                   "its family is not a mapping"),
    dict(id="prefix_rules_leaf", match=[dict(prefix=["dispatch.prefix_rules."])], comparison="prefix_family",
         derivation="not_implemented", profile_key="subtotals_and_headings.prefix_rules",
         canonical="the family mapped to this exact prefix"),
    dict(id="rule_prefix", match=[dict(exact=["dispatch.rule_prefix"])], comparison="not_derivable",
         derivation="not_derivable", note="authoring label for rule ids"),
    dict(id="leaf_markers", match=[dict(prefix=["dispatch.leaf_markers_by_family"])],
         comparison="not_implemented", derivation="not_implemented"),
    dict(id="fallback_patterns", match=[dict(prefix=["dispatch.fallback_family_patterns"])],
         comparison="not_implemented", derivation="not_implemented"),
    dict(id="dispatch_regex", match=[dict(exact=["dispatch.canonical_strip_re", "dispatch.category_marker_re",
                                                 "dispatch.category_marker_before_total"])],
         comparison="not_implemented", derivation="not_implemented"),
    dict(id="staging", match=[dict(exact=["staging"]), dict(prefix=["staging."])],
         comparison="not_implemented", derivation="not_implemented"),
    dict(id="source_encodings", match=[dict(exact=["source_encodings"]), dict(prefix=["source_encodings."])],
         comparison="not_implemented", derivation="not_implemented"),
    dict(id="segment_assertions", match=[dict(exact=["segment_assertions"]), dict(prefix=["segment_assertions[]"])],
         comparison="not_implemented", derivation="not_implemented"),
    dict(id="fv_source_field", match=[dict(exact=["invariants.fv_reconciliation.source_field"])],
         comparison="anchor_field", derivation="implemented",
         profile_key="fund_level_concepts.investments_at_fair_value_concept",
         canonical="concept of the fund-level investments total mapped through the imported `equivalence` "
                   "table; equality through that table is inherited (never exact); the field alone, never "
                   "its basis or tolerance"),
    dict(id="invariant_thresholds", match=[dict(exact=["invariants"]), dict(prefix=["invariants."])],
         comparison="decimal", derivation="not_implemented", profile_key_prefix="fund_level_concepts.",
         canonical="decimal equality; a visible fund total does not derive a tolerance or threshold"),
    dict(id="archetype_prose", match=[dict(prefix=["archetypes."], suffix=[".description"])],
         comparison="not_derivable", derivation="not_derivable", note="authored prose"),
    dict(id="archetypes", match=[dict(exact=["archetypes"]), dict(prefix=["archetypes."])],
         comparison="not_implemented", derivation="not_implemented"),
    dict(id="edge_case_annotations", match=[dict(exact=["known_edge_cases"]),
                                            dict(prefix=["known_edge_cases[]"],
                                                 suffix=[".description", ".id", ".disposition"])],
         comparison="not_derivable", derivation="not_derivable", note="authored annotation / policy label"),
    dict(id="edge_case_other", match=[dict(prefix=["known_edge_cases[]"])], comparison="not_implemented",
         derivation="not_implemented"),
]
ROLLUP = [
    "container keys (keys with descendants in the CIK inventory, unless the family is whole_value) are "
    "classified from their descendant LEAF keys:",
    "1 all exact -> exact", "2 all exact or inherited, at least one inherited -> inherited",
    "3 any exact or partial -> partial (an inherited leaf is not a derived subset)",
    "4 any unresolved -> unresolved (reason: first of `reasons` present among the leaves)",
    "5 any miss -> miss", "6 any inherited -> inherited", "7 otherwise -> not_derivable",
]
NO_ENTRY_RULE = [
    "implemented derivation, no live entry for the profile key at the report date:",
    "stub bearing on the key: the first of `reasons` among the stub causes -> unresolved/<reason>; a "
    "stub with cause no_value (resolved evidence that yields no value, contradicting the wrapper's "
    "value) -> miss; no stub at all (nothing observed) -> unresolved/no_observation",
    "miss is reserved for a contradictory census proposal (a different value, or resolved evidence of "
    "no value)",
    "entries carrying a non-null applies_to cannot be compared with a flat wrapper key -> "
    "unresolved/not_implemented",
    "an exact comparison on an entry with provenance inherited, or reached through an inherited "
    "equivalence table, -> inherited (inherited_from recorded on the key record)",
    "a denominator key absent from this wrapper version is compared as an absent value",
]


class SemanticsError(ValueError):
    """A denominator key is not owned by any frozen comparison family."""


# ---------------------------------------------------------------- freezing

def _accepts(spec: dict, key: str) -> bool:
    if key in spec.get("exact", ()):
        return True
    prefixes = spec.get("prefix")
    if not prefixes or not any(key.startswith(p) for p in prefixes):
        return False
    suffixes = spec.get("suffix")
    return not suffixes or any(key.endswith(s) for s in suffixes)


def _family_of(key: str, families: list) -> dict | None:
    return next((f for f in families if any(_accepts(spec, key) for spec in f["match"])), None)


def _has_descendants(key: str, keys) -> bool:
    return any(k.startswith(key + ".") or k.startswith(key + "[]") for k in keys)


def build_semantics(inventory: dict) -> dict:
    assignments = {}
    for cik, entry in sorted(inventory["ciks"].items()):
        keys = entry.get("keys") or []
        owned = {}
        for key in keys:
            family = _family_of(key, FAMILIES)
            if family is not None and family.get("whole_value"):
                owned[key] = family["id"]
            elif _has_descendants(key, keys):
                owned[key] = "container"
            elif family is not None:
                owned[key] = family["id"]
            else:
                raise SemanticsError("wrapper key " + repr(key) + " of " + cik + " has no frozen comparison family")
        assignments[cik] = owned
    equivalence = {}
    for key, table in EQUIVALENCE.items():
        source = CODE_ROOT / table["source"]
        equivalence[key] = dict(table, sha256=hashlib.sha256(source.read_bytes()).hexdigest())
    return dict(version=SEMANTICS_VERSION, classes=list(CLASSES), reasons=list(REASONS), families=FAMILIES,
                rollup=ROLLUP, no_entry_rule=NO_ENTRY_RULE, equivalence=equivalence,
                legal_form_tokens=list(LEGAL_FORM_TOKENS), inventory_content_sha256=digest(inventory),
                assignments=assignments, disclaimer=DISCLAIMER)


def freeze_semantics(paths: PilotPaths, inventory: dict) -> dict:
    content = build_semantics(inventory)
    body = dict(inventory="m1_comparison_semantics", run_id=paths.run_id, content=content,
                content_sha256=digest(content))
    target = write_once_json(paths, SEMANTICS_RELATIVE, body)
    return dict(state="frozen", path=str(target), sha256=hashlib.sha256(target.read_bytes()).hexdigest(),
                content_sha256=body["content_sha256"])


def load_semantics(paths: PilotPaths) -> dict:
    body = json.loads(confined(paths, SEMANTICS_RELATIVE).read_text(encoding="ascii"))
    if body.get("inventory") != "m1_comparison_semantics" or digest(body["content"]) != body.get("content_sha256"):
        raise StageInvalidated("frozen M1 comparison semantics do not match their digest")
    _require(body["content"])
    return body["content"]


def _require(semantics: dict) -> None:
    missing = [f for f in REQUIRED_FIELDS if f not in semantics]
    if missing:
        raise SemanticsError("frozen M1 semantics lack required field(s): " + ", ".join(missing))


# ---------------------------------------------------------------- wrapper access (this module only)

def load_wrapper(path, *, expected_sha256: str) -> dict:
    raw = Path(path).read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise StageInvalidated("comparison wrapper bytes differ from their pin: " + str(path))
    return json.loads(raw.decode("utf-8"))


def wrapper_values(wrapper: dict) -> dict:
    """key path -> list of occurrences (one for plain keys, one per element under `[]`)."""
    out: dict = {}

    def walk(value, prefix: str) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                path = prefix + "." + key if prefix else key
                out.setdefault(path, []).append(child)
                walk(child, path)
        elif isinstance(value, list):
            for child in value:
                walk(child, prefix + "[]")

    walk(wrapper, "")
    return out


# ---------------------------------------------------------------- canonical values and modes

def _ws(text) -> str:
    return " ".join(str(text).split())


def _loose_name(text, legal_form_tokens) -> str:
    tokens = re.sub(r"[^a-z0-9 ]+", " ", str(text).casefold()).split()
    return " ".join(t for t in tokens if t not in set(legal_form_tokens))


def _local(qname) -> str:
    return str(qname).rsplit("}", 1)[-1].rsplit(":", 1)[-1]


def canonical_value(family: dict, value, semantics: dict):
    mode = family["comparison"]
    if value is None:
        return None
    if mode == "exact_cik":
        return str(value).strip().zfill(10)
    if mode == "name":
        return _ws(value)
    if mode == "string_set":
        items = value if isinstance(value, list) else [value]
        return sorted({_ws(v).lower() if family.get("casefold") else str(v) for v in items})
    if mode == "substring_markers":
        items = value if isinstance(value, list) else [value]
        return sorted({_ws(v).lower() for v in items})
    if mode == "ordered_list":
        return list(value) if isinstance(value, list) else [value]
    if mode in ("ordered_pairs", "prefix_family"):
        if isinstance(value, dict):
            return [[k, v] for k, v in value.items()]
        return [[p[0], p[1] if len(p) > 1 else None] if isinstance(p, list) else [p, None] for p in value]
    if mode == "decimal":
        try:
            return str(Decimal(str(value)).normalize())
        except InvalidOperation:
            return None
    if mode == "anchor_field":
        table = semantics["equivalence"][family["match"][0]["exact"][0]]
        for field, concepts in table["mapping"].items():
            if _local(value) in concepts:
                return field
        return str(value)
    return value


def _compare(family: dict, derived, wrapper, key: str, semantics: dict) -> tuple[str, dict]:
    mode = family["comparison"]
    d, w = canonical_value(family, derived, semantics), canonical_value(family, wrapper, semantics)
    detail = dict(derived=d, wrapper=w)
    if mode == "prefix_family":
        prefix = key[len("dispatch.prefix_rules."):]
        mapping = {p: f for p, f in (d or [])}
        detail = dict(derived=mapping.get(prefix), wrapper=wrapper)
        if prefix not in mapping:
            return "miss", dict(detail, note="prefix not derived")
        if mapping[prefix] is None:
            return "miss", dict(detail, note="prefix present without a family: presence is not a mapping")
        return ("exact" if mapping[prefix] == wrapper else "miss"), detail
    if d is None and w is None:
        return "exact", dict(detail, note="absent in both")
    if d is None or w is None:
        return "miss", detail
    if mode == "anchor_field":
        table = semantics["equivalence"][family["match"][0]["exact"][0]]
        if d == w:
            detail.update(inherited_via=table["source"] + "@" + table["sha256"],
                          note="equal only through the imported concept->field table")
            return "exact", detail
        return "miss", detail
    if mode in ("exact_cik", "decimal"):
        return ("exact" if d == w else "miss"), detail
    if mode == "name":
        if d == w:
            return "exact", detail
        tokens = semantics["legal_form_tokens"]
        return ("partial" if _loose_name(d, tokens) == _loose_name(w, tokens) else "miss"), detail
    if mode == "delimiter":
        if d == w:
            return "exact", detail
        return ("partial" if str(d).strip() == str(w).strip() else "miss"), detail
    if mode == "string_set":
        missing, extra = sorted(set(w) - set(d)), sorted(set(d) - set(w))
        detail.update(missing=missing, extra=extra)
        if not missing and not extra:
            return "exact", detail
        return ("partial" if set(d) & set(w) else "miss"), detail
    if mode == "substring_markers":
        extra = [label for label in d if not any(m in label for m in w)]
        missing = [m for m in w if not any(m in label for label in d)]
        detail.update(missing=missing, extra=extra,
                      note="observed labels vs substring markers: exact is not reachable")
        if not d:
            return "miss", detail
        return ("partial" if len(extra) < len(d) else "miss"), detail
    if mode == "ordered_list":
        detail.update(missing=[x for x in w if x not in d], extra=[x for x in d if x not in w])
        if d == w:
            return "exact", detail
        return ("partial" if set(map(str, d)) & set(map(str, w)) else "miss"), detail
    if mode == "ordered_pairs":
        wp, dp = [p for p, _ in w], [p for p, _ in d]
        detail.update(missing=[p for p in wp if p not in dp], extra=[p for p in dp if p not in wp])
        if d == w:
            return "exact", detail
        pairs = {tuple(p) for p in d if p[1] is not None} & {tuple(p) for p in w}
        detail["matching_pairs"] = sorted(list(p) for p in pairs)
        return ("partial" if pairs else "miss"), detail
    raise SemanticsError("unknown comparison mode " + repr(mode))


# ---------------------------------------------------------------- profile projection

def _live_entries(profile: dict, key: str) -> list:
    date, form = profile["report_date"], profile.get("form_type")
    out = []
    for entry in profile["entries"]:
        if entry["key"] != key or entry["recorded_until"] is not None:
            continue
        if not ((entry["valid_from"] is None or entry["valid_from"] <= date)
                and (entry["valid_to"] is None or date < entry["valid_to"])):
            continue
        if entry["form_type"] is not None and entry["form_type"] != form:
            continue
        out.append(entry)
    return out


def _profile_key(family: dict, key: str) -> str | None:
    if family.get("profile_key"):
        return family["profile_key"]
    if family.get("profile_key_prefix"):
        return family["profile_key_prefix"] + key
    return None


def _no_entry(profile: dict, profile_key: str | None, reasons) -> tuple[str, str | None, list]:
    stubs = [s for s in profile.get("packet_stubs") or [] if profile_key and profile_key in s.get("bears_on", [])]
    causes = {s["cause"] for s in stubs}
    ids = [s["stub_id"] for s in stubs]
    for reason in reasons:
        if reason in causes:
            return "unresolved", reason, ids
    if "no_value" in causes:
        return "miss", None, ids  # resolved evidence of no value contradicts the wrapper's value
    return "unresolved", "no_observation", ids


def _leaf(profile: dict, family: dict, key: str, values: dict, semantics: dict) -> dict:
    present = key in values
    occurrences = values.get(key, [])
    wrapper = (occurrences if "[]" in key else occurrences[0]) if present else None
    record = dict(family=family["id"], wrapper_present=present, reason=None, entry_ids=[], stub_ids=[],
                  provenance=None)
    if family["comparison"] == "not_derivable":
        return dict(record, **{"class": "not_derivable"}, wrapper=wrapper, note=family.get("note"))
    if family["comparison"] == "not_implemented":
        return dict(record, **{"class": "unresolved"}, reason="not_implemented", wrapper=wrapper,
                    note="comparison not implemented by this pilot")
    if family["comparison"] == "delimiter" and present:
        vocabulary = {v.strip() for v in family.get("vocabulary", [])}
        if str(wrapper).strip() not in vocabulary:
            return dict(record, **{"class": "unresolved"}, reason="not_implemented", wrapper=wrapper,
                        note="wrapper delimiter token outside the census delimiter vocabulary")
    profile_key = _profile_key(family, key)
    entries = _live_entries(profile, profile_key) if profile_key else []
    if any(e["applies_to"] is not None for e in entries):
        return dict(record, **{"class": "unresolved"}, reason="not_implemented", wrapper=wrapper,
                    entry_ids=[e["entry_id"] for e in entries],
                    note="partition-specific entries cannot be compared with a flat wrapper key")
    if not entries:
        if family["derivation"] != "implemented":
            return dict(record, **{"class": "unresolved"}, reason="not_implemented", wrapper=wrapper,
                        note="derivation not implemented by this pilot")
        if present:
            klass, reason, stub_ids = _no_entry(profile, profile_key, semantics["reasons"])
            return dict(record, **{"class": klass}, reason=reason, stub_ids=stub_ids, wrapper=wrapper,
                        derived=None, note="no derived entry")
        return dict(record, **{"class": "exact"}, wrapper=None, derived=None, note="absent in both")
    entry = entries[0]
    klass, detail = _compare(family, entry["value"], wrapper, key, semantics)
    provenance, inherited_from = entry["provenance"], entry.get("inherited_from")
    via = detail.pop("inherited_via", None)
    if via:
        provenance = "inherited"
        inherited_from = "; ".join(x for x in (via, inherited_from) if x)
    if klass == "exact" and provenance == "inherited":
        klass = "inherited"
    return dict(record, **detail, **{"class": klass}, entry_ids=[entry["entry_id"]],
                provenance=provenance, inherited_from=inherited_from)


def _rollup(leaves: list, reasons) -> tuple[str, str | None]:
    classes = [r["class"] for r in leaves]
    if not classes:
        return "not_derivable", None
    if all(c == "exact" for c in classes):
        return "exact", None
    if all(c in ("exact", "inherited") for c in classes):
        return "inherited", None
    if any(c in ("exact", "partial") for c in classes):
        return "partial", None
    if "unresolved" in classes:
        present = {r["reason"] for r in leaves if r["class"] == "unresolved"}
        return "unresolved", next(r for r in reasons if r in present)
    if "miss" in classes:
        return "miss", None
    if "inherited" in classes:
        return "inherited", None
    return "not_derivable", None


def section_of(key: str) -> str:
    if key in HEADER_KEYS:
        return "header"
    return key.split(".", 1)[0].split("[", 1)[0]


def summarise(records: list, classes=CLASSES, reasons=REASONS) -> dict:
    def counts(rows):
        out = {c: 0 for c in classes}
        for r in rows:
            out[r["class"]] += 1
        return out

    by_reason = {r: 0 for r in reasons}
    for r in records:
        if r["class"] == "unresolved":
            by_reason[r["reason"]] += 1
    sections: dict = {}
    for r in records:
        sections.setdefault(r["section"], []).append(r)
    leaves = [r for r in records if not r["container"]]
    return dict(denominator=len(records), counts=counts(records), unresolved_by_reason=by_reason,
                by_section={s: dict(denominator=len(rows), counts=counts(rows)) for s, rows in sorted(sections.items())},
                leaf_only=dict(denominator=len(leaves), counts=counts(leaves)))


def compare_to_wrapper(profile: dict, wrapper: dict, *, cik: str, inventory_keys, semantics: dict) -> dict:
    """Classify every denominator key of `cik` (the fixed inventory) against `wrapper`."""
    _require(semantics)
    assignment = semantics["assignments"].get(cik)
    if assignment is None:
        raise SemanticsError("no frozen assignment for " + cik)
    families = {f["id"]: f for f in semantics["families"]}
    keys = list(inventory_keys)
    unknown = [k for k in keys if k not in assignment]
    if unknown:
        raise SemanticsError("denominator keys without a frozen family: " + repr(unknown[:5]))
    values = wrapper_values(wrapper)
    records = {}
    for key in keys:
        if assignment[key] != "container":
            records[key] = dict(_leaf(profile, families[assignment[key]], key, values, semantics), key=key,
                                section=section_of(key), container=False)
    for key in keys:
        if assignment[key] == "container":
            leaves = [records[k] for k in keys if k in records and not records[k]["container"]
                      and (k.startswith(key + ".") or k.startswith(key + "[]"))]
            klass, reason = _rollup(leaves, semantics["reasons"])
            records[key] = dict(key=key, section=section_of(key), container=True, family="container",
                                reason=reason, wrapper_present=key in values, leaf_keys=len(leaves),
                                **{"class": klass})
    ordered = [records[k] for k in keys]
    return dict(cik=cik, keys=ordered, **summarise(ordered, semantics["classes"], semantics["reasons"]))
