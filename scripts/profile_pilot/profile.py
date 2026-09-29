"""Task 6: derive a filer profile v0 from ONE census document (spec 6.2).

Isolation (ruling R16): this module never reads a comparison wrapper. It imports no
wrapper loader, no manifest and no M1 code, and `derive_profile` reads no file except
JSON Schemas (the envelope schema, through envelope.validate_profile): it is a function
of the census document, the census source record and the anchor block the caller copied. Wrapper aggregate-marker corroboration that the
census carries inside the subtotal detector is used only to mark an entry
`inherited`; the marker text is never copied into a value.

Entries are created only from `resolved` detector outcomes (or, for census
enumerations that are not detector outcomes, from channels whose collection state is
`complete`), through `envelope.make_assertion`, with measured support, the census
source and dependency ids as evidence, valid_from = the census report date,
valid_to = null, author census, status derived, regression_pin null. `candidate` and
`insufficient_evidence` outcomes become packet stubs recorded beside the entries,
never entries. A stub names the profile keys it bears on, so a comparison can report
`unresolved` with the detector's reason. An incomplete collection channel blocks every
entry of a section that depends on it.

form_type: every entry is derived from one census of one form; no form-type
difference is evidenced by a single instance, so entries carry form_type = null and
the source form sits in the `census_source` evidence item.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from functools import lru_cache
import json
from pathlib import Path

from scripts.profile_pilot import envelope
from scripts.profile_pilot.census import POSITION_FIELDS
from scripts.profile_pilot.census_detect import DELIMITERS, LABEL_RE

PROFILE_VERSION = "profile.v0.1"
SCHEMA_DIR = Path(__file__).resolve().parent / "schemas"
DOCUMENT_SCHEMA = "filer_profile_document_v0.schema.json"
ENVELOPE_SCHEMA = "filer_profile_v0.schema.json"
ERAS = ("q1", "same_era")
ERA_ROLES = {"q1": "q1", "same_era": "verified_era"}
DERIVED_SECTIONS = ("identifier_format", "subtotals_and_headings", "presentation_views",
                    "comparative_periods", "column_contract", "footnote_conventions",
                    "position_identity", "non_disclosure", "fund_level_concepts")
STUB_SECTIONS = ("accounting_scope", "lifecycle")
SECTIONS = DERIVED_SECTIONS + STUB_SECTIONS + ("anchors",)
# Channels each section's entries depend on (spec 6.1 collector completeness).
SECTION_CHANNELS = {
    "identifier_format": ("contexts", "identifiers", "numeric_facts"),
    "subtotals_and_headings": ("contexts", "units", "numeric_facts"),
    "presentation_views": ("contexts", "units", "numeric_facts", "text_facts"),
    "comparative_periods": ("contexts", "numeric_facts"),
    "column_contract": ("contexts", "numeric_facts", "text_facts"),
    "footnote_conventions": ("footnotes", "numeric_facts", "text_facts"),
    "position_identity": ("contexts", "identifiers"),
    "non_disclosure": ("contexts", "identifiers", "numeric_facts", "text_facts", "footnotes"),
    "fund_level_concepts": ("contexts", "numeric_facts", "text_facts"),
}
PRIMARY_SHARE = 0.90   # one delimiter must split >= 90% of identifiers to be THE delimiter
PADDING_SHARE = 0.90   # one whitespace padding must cover >= 90% of its occurrences
PADDABLE = ("|", ";", ",")
FOOTNOTE_FIELDS = ("non_accrual", "pik_rate")
STUB_FINDINGS_NOT_IMPLEMENTED = ("evidenced_partition",)
ROLE_SOURCE = "pipeline/context_inventory.py:classify_context"


class ProfileError(ValueError):
    """A profile document violates its schema or the derivation contract."""


# ---------------------------------------------------------------- small helpers

def _local(qname: str) -> str:
    return str(qname).rsplit("}", 1)[-1].rsplit(":", 1)[-1]


def _complete(doc: dict, channels) -> list:
    """The channels (of `channels`) that are NOT complete."""
    return [c for c in channels if doc["channels"].get(c, {}).get("state") != "complete"]


def _dped(doc: dict) -> set:
    return set(doc["document_metadata"]["document_period_end_dates"])


def _current_positions(doc: dict) -> list:
    dped = _dped(doc)
    return [p for p in doc["positions"] if p["period"].get("instant") in dped]


def _identifier_rows(doc: dict) -> list:
    """The partition detector's basis: current typed identifiers, Total/Subtotal labels set aside."""
    positions = [p for p in doc["positions"] if p["identity"]["typed_identifier"]]
    current = [p for p in positions if p["period"].get("instant") in _dped(doc)]
    return [p["identity"]["typed_identifier"] for p in (current or positions)
            if not LABEL_RE.match(p["identity"]["typed_identifier"])]


def _compact_subject(subject) -> dict:
    if not isinstance(subject, dict):
        return {}
    keep = ("context_id", "label", "field", "signature", "rows", "basis", "context_ids", "identity_key",
            "scope")
    return {k: subject[k] for k in keep if k in subject}


class _Builder:
    """Collects assertion specs and packet stubs for one profile."""

    def __init__(self, doc: dict, source: dict, recorded_at: str):
        self.doc, self.source, self.recorded_at = doc, source, recorded_at
        self.events: list = []
        self.stubs: list = []
        self.sections = {name: dict(status="derived", entry_ids=[], stub_ids=[],
                                    depends_on_channels=list(SECTION_CHANNELS.get(name, ())),
                                    notes=[]) for name in SECTIONS}
        self.cik = str(doc["document"]["cik"]).zfill(10)
        self.report_date = doc["document"]["report_date"]
        names = sorted({str(d.get("name")) for d in doc.get("dependencies") or []})
        self.census_dependencies = names

    def _base_evidence(self, section: str) -> list:
        src = self.source
        channels = SECTION_CHANNELS.get(section, ())
        return [dict(kind="census_source", census_relative=src["census_relative"],
                     census_sha256=src["census_sha256"], fingerprint=src["fingerprint"],
                     accession_number=src.get("accession_number"), form_type=src.get("form_type"),
                     report_date=src["report_date"], role=src.get("role")),
                dict(kind="dependencies", channels=list(channels),
                     channel_states={c: self.doc["channels"].get(c, {}).get("state") for c in channels},
                     census_dependencies=self.census_dependencies)]

    def entry(self, section: str, key: str, value, support: dict, evidence: list, *,
              provenance: str = "derived", inherited_from: str | None = None) -> None:
        before = {e["entry_id"] for e in envelope.materialize_entries(self.events)}
        self.events = envelope.make_assertion(
            self.events, cik=self.cik, key=key, value=value, valid_from=self.report_date,
            recorded_at=self.recorded_at, support=support,
            evidence=self._base_evidence(section) + list(evidence), provenance=provenance,
            inherited_from=inherited_from)
        new = [e["entry_id"] for e in envelope.materialize_entries(self.events)
               if e["entry_id"] not in before]
        self.sections[section]["entry_ids"] += new

    def stub(self, section: str, cause: str, bears_on, *, detector=None, finding=None, subject=None,
             question=None, evidence=None) -> None:
        stub_id = section + ":" + str(1 + sum(s["section"] == section for s in self.stubs))
        self.stubs.append(dict(stub_id=stub_id, section=section, cause=cause, bears_on=sorted(set(bears_on)),
                               detector=detector, finding=finding, subject=_compact_subject(subject),
                               question=question, evidence=evidence or {}))
        self.sections[section]["stub_ids"].append(stub_id)

    def blocked(self, section: str, bears_on) -> bool:
        """Block a whole section on an incomplete channel (spec 6.1)."""
        incomplete = _complete(self.doc, SECTION_CHANNELS[section])
        if not incomplete:
            return False
        states = {c: self.doc["channels"].get(c, {}).get("state") for c in incomplete}
        self.stub(section, "insufficient_evidence", bears_on, finding="collection_channel_incomplete",
                  question="Section depends on channel(s) that are not complete: " + json.dumps(states,
                                                                                                sort_keys=True),
                  evidence=dict(channel_states=states))
        self.sections[section]["status"] = "insufficient_evidence"
        return True

    def outcome_stub(self, section: str, item: dict, bears_on) -> None:
        packet = item.get("evidence", {}).get("packet_stub") if isinstance(item.get("evidence"), dict) else None
        self.stub(section, item["outcome"], bears_on, detector=item.get("detector"), finding=item.get("finding"),
                  subject=item.get("subject"),
                  question=(packet or {}).get("question") or ("Detector " + str(item.get("detector")) + " "
                                                               + item["outcome"] + ": " + str(item.get("finding"))),
                  evidence=dict(provenance=item.get("provenance"), inherited_from=item.get("inherited_from")))


def _outcome_ref(item: dict) -> dict:
    return dict(kind="detector_outcome", detector=item.get("detector"), outcome=item["outcome"],
                finding=item.get("finding"), subject=_compact_subject(item.get("subject")),
                provenance=item.get("provenance"), inherited_from=item.get("inherited_from"))


def _provenance(items: list) -> tuple[str, str | None]:
    """Inherited when any contributing outcome is inherited or rests on wrapper corroboration."""
    sources = set()
    for item in items:
        if item.get("provenance") == "inherited" and item.get("inherited_from"):
            sources.add(item["inherited_from"])
        marker = item.get("evidence", {}).get("wrapper_marker") if isinstance(item.get("evidence"), dict) else None
        if marker:
            sources.add(str(marker.get("inherited_from")))
    return ("inherited", "; ".join(sorted(sources))) if sources else ("derived", None)


# ---------------------------------------------------------------- sections

def _identifier_format(b: _Builder) -> None:
    section, key = "identifier_format", "identifier_format.delimiter"
    if b.blocked(section, [key]):
        return
    outcomes = b.doc["detectors"]["partition"]["outcomes"]
    open_items = [o for o in outcomes if o["outcome"] != "resolved"]
    for item in open_items:
        b.outcome_stub(section, item, [key])
    partitioned = [o for o in outcomes if o["outcome"] == "resolved" and o["finding"] in STUB_FINDINGS_NOT_IMPLEMENTED]
    for item in partitioned:
        b.stub(section, "not_implemented", [key], detector="partition", finding=item["finding"],
               subject=item.get("subject"),
               question="Evidenced partition: per-partition delimiter entries are not derived by this pilot")
    if open_items or partitioned or not outcomes:
        b.sections[section]["status"] = "unresolved"
        if not outcomes:
            b.sections[section]["notes"].append("partition detector produced no outcome")
        return
    rows = _identifier_rows(b.doc)
    outers = sorted({o["evidence"]["inside_segment"]["outer"] for o in outcomes
                     if o["finding"] == "secondary_delimiter_inside_segment"})
    if len(outers) > 1:
        b.stub(section, "insufficient_evidence", [key], detector="partition",
               finding="conflicting_outer_delimiters", question="Resolved outcomes name different outer delimiters: "
               + repr(outers))
        b.sections[section]["status"] = "unresolved"
        return
    shares = {d: sum(d in r for r in rows) for d in DELIMITERS}
    token = outers[0] if outers else (max(DELIMITERS, key=lambda d: (shares[d], -DELIMITERS.index(d)))
                                      if rows else None)
    if not rows or token is None or shares[token] < PRIMARY_SHARE * len(rows):
        b.stub(section, "no_value", [key], detector="partition", finding="no_dominant_delimiter",
               question="Partition resolved but no vocabulary delimiter splits >= %d%% of identifiers"
               % int(PRIMARY_SHARE * 100),
               evidence=dict(rows=len(rows), counts={d: n for d, n in shares.items() if n},
                             vocabulary=list(DELIMITERS)))
        b.sections[section]["notes"].append("resolved, but no dominant delimiter in the vocabulary")
        return
    value, padding = _padded(token, rows)
    provenance, inherited_from = _provenance(outcomes)
    b.entry(section, key, value, dict(kind="prevalence", numerator=shares[token], denominator=len(rows)),
            [*(_outcome_ref(o) for o in outcomes),
             dict(kind="delimiter_padding", token=token, forms=padding, rule="form covering >= %s of "
                  "occurrences, else the bare token" % PADDING_SHARE),
             dict(kind="identifier_examples", identifiers=[r for r in rows if token in r][:5])],
            provenance=provenance, inherited_from=inherited_from)


def _padded(token: str, rows: list) -> tuple[str, dict]:
    if token not in PADDABLE:
        return token, {}
    forms = {" " + token + " ": 0, token + " ": 0, " " + token: 0, token: 0}
    total = 0
    for text in rows:
        for i, ch in enumerate(text):
            if ch != token:
                continue
            left = i > 0 and text[i - 1] == " "
            right = i + 1 < len(text) and text[i + 1] == " "
            form = (" " if left else "") + token + (" " if right else "")
            forms[form] += 1
            total += 1
    best = max(forms, key=lambda f: forms[f])
    value = best if total and forms[best] >= PADDING_SHARE * total else token
    return value, dict(forms, occurrences=total)


def _subtotals(b: _Builder) -> None:
    section = "subtotals_and_headings"
    structural_key, labels_key = section + ".structural_subtotals", section + ".aggregate_labels"
    fund_key = "fund_level_concepts.investments_at_fair_value_concept"
    if b.blocked(section, [structural_key, labels_key, fund_key]):
        return
    outcomes = b.doc["detectors"]["subtotal"]["outcomes"]
    contexts = {c["id"]: c for c in b.doc["contexts"]}
    dped = _dped(b.doc)
    for item in outcomes:
        if item["outcome"] == "resolved":
            continue
        bears = [structural_key]
        subject = item.get("subject") or {}
        if subject.get("label") or (isinstance(item.get("evidence"), dict) and item["evidence"].get("wrapper_marker")):
            bears.append(labels_key)
        context = contexts.get(subject.get("context_id"))
        if context and not context["dimensions"] and not context["typed_dimensions"] \
                and context["period"].get("instant") in dped:
            bears.append(fund_key)
        b.outcome_stub(section, item, bears)
    structural = [o for o in outcomes if o["outcome"] == "resolved" and o["finding"] == "structural_subtotal"]
    if not outcomes:
        b.sections[section]["notes"].append("subtotal detector produced no outcome")
    if structural:
        kinds = sorted({m["set"] for o in structural for m in o["evidence"].get("matched_sets", [])
                        if m["set"] != "labelled_peer_group"})
        headings = sorted({str(o["evidence"].get("heading")) for o in structural})
        provenance, inherited_from = _provenance(structural)
        b.entry(section, structural_key, dict(heading_kinds=headings, child_set_kinds=kinds),
                dict(kind="prevalence", numerator=len(structural), denominator=len(outcomes)),
                [_outcome_ref(o) for o in structural[:20]]
                + [dict(kind="context_ids", ids=sorted(o["subject"].get("context_id") for o in structural))],
                provenance=provenance, inherited_from=inherited_from)
    labelled = [o for o in structural if (o.get("subject") or {}).get("label")]
    if labelled:
        values = sorted({" ".join(o["subject"]["label"].lower().split()) for o in labelled})
        provenance, inherited_from = _provenance(labelled)
        b.entry(section, labels_key, values,
                dict(kind="prevalence", numerator=len(labelled), denominator=len(structural)),
                [_outcome_ref(o) for o in labelled], provenance=provenance, inherited_from=inherited_from)
    if b.sections[section]["stub_ids"] and not b.sections[section]["entry_ids"]:
        b.sections[section]["status"] = "unresolved"


def _presentation_views(b: _Builder) -> None:
    section, key = "presentation_views", "presentation_views.same_identifier_contexts"
    if b.blocked(section, [key]):
        return
    outcomes = b.doc["detectors"]["alternate_view"]["outcomes"]
    for item in outcomes:
        if item["outcome"] != "resolved":
            b.outcome_stub(section, item, [key])
    resolved = [o for o in outcomes if o["outcome"] == "resolved"]
    if not outcomes:
        b.sections[section]["status"] = "no_observations"
        b.sections[section]["notes"].append("no identifier appears under more than one context")
        return
    if resolved:
        counts: dict = {}
        for o in resolved:
            counts[o["finding"]] = counts.get(o["finding"], 0) + 1
        provenance, inherited_from = _provenance(resolved)
        b.entry(section, key, dict(sorted(counts.items())),
                dict(kind="prevalence", numerator=len(resolved), denominator=len(outcomes)),
                [_outcome_ref(o) for o in resolved[:20]], provenance=provenance, inherited_from=inherited_from)
    else:
        b.sections[section]["status"] = "unresolved"


def _months(report_date: str, anchor: str) -> int:
    return (int(report_date[:4]) * 12 + int(report_date[5:7])) - (int(anchor[:4]) * 12 + int(anchor[5:7]))


def _comparative_periods(b: _Builder) -> None:
    section, key = "comparative_periods", "comparative_periods.position_schedule_offsets_months"
    if b.blocked(section, [key]):
        return
    positions = [p for p in b.doc["positions"] if p["period"].get("kind") == "instant"]
    if not positions:
        b.sections[section]["status"] = "no_observations"
        return
    dped = _dped(b.doc)
    comparative = [p for p in positions if p["period"].get("instant") not in dped]
    offsets = sorted({_months(b.report_date, p["period"]["instant"]) for p in comparative})
    b.entry(section, key, offsets, dict(kind="prevalence", numerator=len(comparative), denominator=len(positions)),
            [dict(kind="periods", periods=[{k: p[k] for k in ("kind", "instant", "start", "end", "relation",
                                                               "contexts") if k in p}
                                           for p in b.doc["periods"] if p.get("relation") == "comparative"][:40]),
             dict(kind="inherited_dependency", note="position membership is the inherited context role",
                  inherited_from=ROLE_SOURCE)])


def _column_contract(b: _Builder) -> None:
    section = "column_contract"
    if b.blocked(section, [section + "." + f for f in POSITION_FIELDS]):
        return
    current = _current_positions(b.doc)
    if not current:
        b.sections[section]["status"] = "no_observations"
        return
    for field in POSITION_FIELDS:
        filled = [p["fields"].get(field, {}) for p in current
                  if p["fields"].get(field, {}).get("status") in ("reported", "consistent_duplicate")]
        if not filled:
            continue
        concepts = sorted({c for f in filled for c in f.get("concepts", [])})
        sources = sorted({f.get("inherited_from") for f in filled})
        inherited = all(f.get("provenance") == "inherited" for f in filled) and None not in sources
        conflicts = sum(p["fields"].get(field, {}).get("status") == "conflict" for p in current)
        b.entry(section, section + "." + field, dict(concepts=concepts),
                dict(kind="prevalence", numerator=len(filled), denominator=len(current)),
                [dict(kind="field_status", conflicts=conflicts, basis="document_period_end positions")],
                provenance="inherited" if inherited else "derived",
                inherited_from="; ".join(sources) if inherited else None)


def _non_disclosure_outcomes(b: _Builder) -> dict:
    return {o["subject"].get("field"): o for o in b.doc["detectors"]["non_disclosure"]["outcomes"]
            if isinstance(o.get("subject"), dict)}


def _footnote_conventions(b: _Builder) -> None:
    section = "footnote_conventions"
    keys = [section + "." + f + "_location" for f in FOOTNOTE_FIELDS]
    if b.blocked(section, keys):
        return
    outcomes = _non_disclosure_outcomes(b)
    for field, key in zip(FOOTNOTE_FIELDS, keys):
        item = outcomes.get(field)
        if item is None:
            b.stub(section, "insufficient_evidence", [key], finding="no_detector_outcome")
        elif item["outcome"] != "resolved":
            b.outcome_stub(section, item, [key])
        else:
            value = "tagged_concept" if item["finding"] == "observed" else item["finding"]
            b.entry(section, key, value, dict(kind="context_count", count=int(sum(
                (item["evidence"].get("fact_status_counts") or {}).values()))), [_outcome_ref(item)])
    if not b.sections[section]["entry_ids"]:
        b.sections[section]["status"] = "unresolved"


def _position_identity(b: _Builder) -> None:
    section, key = "position_identity", "position_identity.typed_identifier_axis"
    if b.blocked(section, [key]):
        return
    current = _current_positions(b.doc)
    if not current:
        b.sections[section]["status"] = "no_observations"
        return
    axes: dict = {}
    for p in current:
        found = sorted({d["axis"] for d in p["identity"]["typed_dimensions"]
                        if "investmentidentifier" in _local(d["axis"]).lower()})
        label = found[0] if len(found) == 1 else ("none" if not found else "multiple")
        axes[label] = axes.get(label, 0) + 1
    typed = {a: n for a, n in axes.items() if a not in ("none", "multiple")}
    if len(typed) == 1 and set(axes) == set(typed):
        axis, n = next(iter(typed.items()))
        b.entry(section, key, axis, dict(kind="prevalence", numerator=n, denominator=len(current)),
                [dict(kind="axis_counts", counts=axes)], provenance="inherited",
                inherited_from=ROLE_SOURCE + " (position membership, explicit_contexts rules)")
    else:
        b.stub(section, "insufficient_evidence", [key], finding="mixed_identity_carriers",
               question="Current positions do not share one typed identifier axis",
               evidence=dict(axis_counts=axes))
        b.sections[section]["status"] = "unresolved"


def _non_disclosure(b: _Builder) -> None:
    section = "non_disclosure"
    for field, item in sorted(_non_disclosure_outcomes(b).items(), key=lambda kv: str(kv[0])):
        key = section + "." + (str(field) if field else "instance")
        if item["outcome"] == "resolved":
            b.entry(section, key, item["finding"], dict(kind="context_count", count=int(sum(
                (item["evidence"].get("fact_status_counts") or {}).values()))), [_outcome_ref(item)])
        else:
            b.outcome_stub(section, item, [key])
    if b.sections[section]["stub_ids"] and not b.sections[section]["entry_ids"]:
        b.sections[section]["status"] = "unresolved"


def _single_text(facts: list, local: str) -> tuple[list, list]:
    values = [f for f in facts if _local(f["qname"]) == local and f["status"] in ("reported",
                                                                                  "consistent_duplicate")]
    return sorted({" ".join(str(f["value"]).split()) for f in values}), values


def _fund_level(b: _Builder) -> None:
    section = "fund_level_concepts"
    keys = [section + "." + k for k in ("entity_cik", "entity_registrant_name",
                                         "investments_at_fair_value_concept", "fund_income_concepts",
                                         "fund_balance_concepts")]
    if b.blocked(section, keys):
        return
    facts = b.doc["facts"]
    for key, local, norm in ((keys[0], "EntityCentralIndexKey", lambda v: v.zfill(10)),
                             (keys[1], "EntityRegistrantName", lambda v: v)):
        values, used = _single_text(facts, local)
        if len(values) == 1:
            b.entry(section, key, norm(values[0]), dict(kind="context_count", count=len(used)),
                    [dict(kind="fact_indices", concept="dei:" + local, ids=[f["i"] for f in used][:10])])
        else:
            b.stub(section, "insufficient_evidence", [key], finding="dei_fact_not_single",
                   evidence=dict(values=values[:5]))
    _fund_total(b, keys[2])
    dped = _dped(b.doc)
    for key, rows in ((keys[3], b.doc["fund_income"]), (keys[4], b.doc["fund_balance"])):
        current = [r for r in rows if r.get("scope") == "fund" and r.get("status") == "reported"
                   and ((r.get("period") or {}).get("instant") in dped or (r.get("period") or {}).get("end") in dped)]
        if current:
            pairs = sorted({(r["field"], r["qname"]) for r in current})
            b.entry(section, key, [list(p) for p in pairs], dict(kind="context_count", count=len(current)),
                    [dict(kind="fact_indices", ids=[r["fact_index"] for r in current][:20])])


def _fund_total(b: _Builder, key: str) -> None:
    """The concept of the fund-level investments total, from a resolved structural subtotal."""
    dped = _dped(b.doc)
    contexts = {c["id"]: c for c in b.doc["contexts"]}
    chosen = []
    for item in b.doc["detectors"]["subtotal"]["outcomes"]:
        if item["outcome"] != "resolved" or item["finding"] != "structural_subtotal":
            continue
        context = contexts.get((item.get("subject") or {}).get("context_id"))
        if (item["evidence"].get("heading") == "undimensioned_fund_context" and context
                and context["period"].get("instant") in dped):
            chosen.append(item)
    if not chosen:
        return  # open outcomes bearing on this key were stubbed by the subtotal section
    concepts = sorted({f["qname"] for item in chosen for f in b.doc["facts"]
                       if f.get("field") == "fair_value" and f["context_id"] == item["subject"]["context_id"]
                       and f["status"] in ("reported", "consistent_duplicate")})
    if len(concepts) != 1:
        b.stub("fund_level_concepts", "insufficient_evidence", [key], finding="fund_total_concept_not_single",
               evidence=dict(concepts=concepts))
        return
    try:
        values = sorted({str(Decimal(str(item["evidence"]["parent_value"]))) for item in chosen})
    except (InvalidOperation, KeyError):
        values = []
    provenance, inherited_from = _provenance(chosen)
    b.entry("fund_level_concepts", key, concepts[0],
            dict(kind="context_count", count=len(chosen)),
            [_outcome_ref(o) for o in chosen] + [dict(kind="fund_total_values", values=values)],
            provenance=provenance, inherited_from=inherited_from)


def _stub_sections(b: _Builder, anchors: dict | None) -> dict:
    for name, question in (("accounting_scope", "Accounting scope cannot be settled from structure alone"),
                           ("lifecycle", "Lifecycle is outside the pilot census")):
        b.sections[name].update(status="stub")
        b.stub(name, "not_implemented", [name], question=question)
    if anchors and anchors.get("status") == "copied" and anchors.get("files"):
        b.sections["anchors"].update(status="copied")
        return anchors
    b.sections["anchors"].update(status="stub")
    b.stub("anchors", "not_implemented", ["anchors"], question="No agent_anchor file for this report date",
           evidence=dict(available=(anchors or {}).get("available", [])))
    return dict(status="stub", reason="no agent_anchor file for this report date",
                available=(anchors or {}).get("available", []))


# ---------------------------------------------------------------- entry points

def derive_profile(doc: dict, *, source: dict, era: str, recorded_at: str, anchors: dict | None = None) -> dict:
    """Profile v0 for one census document. Pure: no file access, no wrapper."""
    if era not in ERAS:
        raise ProfileError("unknown era " + repr(era))
    if str(doc["document"]["cik"]).zfill(10) != str(source["cik"]).zfill(10) \
            or doc["document"]["report_date"] != source["report_date"]:
        raise ProfileError("census document does not match its source record")
    b = _Builder(doc, source, recorded_at)
    _identifier_format(b)
    _subtotals(b)
    _presentation_views(b)
    _comparative_periods(b)
    _column_contract(b)
    _footnote_conventions(b)
    _position_identity(b)
    _non_disclosure(b)
    _fund_level(b)
    anchor_block = _stub_sections(b, anchors)
    for name in DERIVED_SECTIONS:
        section = b.sections[name]
        if section["status"] == "derived" and not section["entry_ids"]:
            section["status"] = "unresolved" if section["stub_ids"] else "no_observations"
    validation = envelope.validate_profile(b.events, sample_rows={})
    stub_counts: dict = {}
    for s in b.stubs:
        stub_counts[s["cause"]] = stub_counts.get(s["cause"], 0) + 1
    return dict(
        schema="filer_profile_document_v0", profile_version=PROFILE_VERSION, cik=b.cik, era=era,
        report_date=b.report_date, form_type=doc["document"].get("form_type"), recorded_at=recorded_at,
        source=dict(source), channel_states={k: v.get("state") for k, v in sorted(doc["channels"].items())},
        sections=b.sections, events=b.events, entries=envelope.materialize_entries(b.events),
        packet_stubs=b.stubs, anchors=anchor_block, validation=validation,
        counts=dict(entries=len(envelope.materialize_entries(b.events)), packet_stubs=len(b.stubs),
                    stubs_by_cause=dict(sorted(stub_counts.items()))),
        claims="Derived from one census without reading the comparison wrapper; no correctness claim.")


@lru_cache(maxsize=1)
def _document_validator():
    import jsonschema
    from referencing import Registry, Resource
    document = json.loads((SCHEMA_DIR / DOCUMENT_SCHEMA).read_text(encoding="ascii"))
    entry = json.loads((SCHEMA_DIR / ENVELOPE_SCHEMA).read_text(encoding="ascii"))
    registry = Registry().with_resources([(ENVELOPE_SCHEMA, Resource.from_contents(entry)),
                                          (DOCUMENT_SCHEMA, Resource.from_contents(document))])
    return jsonschema.Draft202012Validator(document, registry=registry)


def validate_document(document: dict) -> None:
    """Document layout (schemas/filer_profile_document_v0) + every entry against the envelope."""
    errors = sorted(_document_validator().iter_errors(document), key=lambda e: list(e.absolute_path))
    if errors:
        raise ProfileError("schema: " + "/".join(map(str, errors[0].absolute_path)) + ": "
                           + errors[0].message[:300])
    try:
        envelope.validate_profile(document["events"], sample_rows={})
    except envelope.EnvelopeError as exc:
        raise ProfileError(str(exc)) from exc
    materialized = envelope.materialize_entries(document["events"])
    if materialized != document["entries"]:
        raise ProfileError("entries are not the materialized view of the event log")
    ids = {e["entry_id"] for e in materialized}
    for name, section in document["sections"].items():
        if not set(section["entry_ids"]) <= ids:
            raise ProfileError("section " + name + " names unknown entries")
