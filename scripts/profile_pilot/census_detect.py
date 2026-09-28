"""Task 4 detectors over one census: subtotal, alternate view, non-disclosure, partition.

Every detector emits exactly one of `candidate`, `resolved`, `insufficient_evidence`
per subject, with the evidence that produced it and the collector channels it
depends on. A `resolved` outcome that depends on an incomplete channel is
downgraded to `insufficient_evidence` (only a positive `observed` survives), and a
failed collection yields one instance-level `insufficient_evidence` per detector.

Rules (spec 6.1): equal values under different axes do not establish duplicates;
sum equality alone does not establish a subtotal (structural parent/child on the
same entity/date/currency/scope basis plus heading evidence is required; no subset
search); a missing concept is `not_observed_in_complete_instance` only when the
concept, identifier, text and footnote channels are all complete; partitions are
structural predicates in the envelope vocabulary, never row positions.

Subtotal: a "Total ..." label that matches no sum is never resolved as not-a-subtotal;
only position-level tranche facts (maturity, rate, spread) on the context rule it out.
Partition: the candidate signature is two delimiters each above 20% prevalence, or a
multi-modal segment count on one delimiter; the discriminator search then runs
(punctuation inside one segment, axis member, carrying concept, segment count, shared
prefix vocabulary, and the inherited authored grammar dialect). Every outcome carries
provenance/inherited_from; an outcome resting only on inherited input is `inherited`.
"""
from __future__ import annotations

from decimal import Decimal
import re

DETECTOR_VERSION = "census-detect.v0.2"
OUTCOMES = ("candidate", "resolved", "insufficient_evidence")
SCOPE_AXES = frozenset({"consolidatedentitiesaxis", "consolidationitemsaxis"})
LABEL_RE = re.compile(r"^\s*(sub-?\s*)?totals?\b", re.IGNORECASE)
SINGLE = ("reported", "consistent_duplicate")
NON_BALANCE = ("maturity_date", "interest_rate", "basis_spread", "pik_rate", "interest_rate_floor",
               "acquisition_date")
BALANCE = ("fair_value", "cost", "principal_amount", "shares_held")
MAX_GROUP = 20
MIN_PARTITION_ROWS = 10
DIALECT_SHARE = 0.20
NEAR_SHARE = 0.90
DELIMITERS = ("|", ";", ",", " - ", " / ")
MAX_PREFIX_VOCABULARY = 3
NON_DISCLOSURE_TERMS = {
    "fair_value": ("fair value",),
    "cost": ("amortized cost", "cost basis"),
    "principal_amount": ("principal", " par "),
    "shares_held": ("shares", " units"),
    "interest_rate": ("interest rate", "%"),
    "basis_spread": ("sofr", "libor", "spread", "prime", "euribor", "sonia"),
    "pik_rate": ("pik", "paid-in-kind", "paid in kind"),
    "interest_rate_floor": ("floor",),
    "maturity_date": ("maturity", "matures", "due "),
    "non_accrual": ("non-accrual", "nonaccrual", "non accrual"),
    "industry": ("industry", "sector"),
    "affiliation": ("affiliate", "controlled"),
}
DEPENDS = {
    "subtotal": ["contexts", "units", "numeric_facts"],
    "alternate_view": ["contexts", "units", "numeric_facts", "text_facts"],
    "non_disclosure": ["contexts", "identifiers", "numeric_facts", "text_facts", "footnotes"],
    "partition": ["contexts", "identifiers", "numeric_facts"],
}


def _local(tag: str) -> str:
    return str(tag).rsplit("}", 1)[-1].rsplit(":", 1)[-1]


def _outcome(detector, subject, outcome, finding, evidence, *, provenance="derived",
             inherited_from=None) -> dict:
    """One detector outcome. `inherited` only when the outcome rests solely on inherited input."""
    assert outcome in OUTCOMES
    assert (provenance == "inherited") == bool(inherited_from), "inherited outcomes name their source"
    return dict(detector=detector, subject=subject, outcome=outcome, finding=finding,
                evidence=evidence, provenance=provenance, inherited_from=inherited_from,
                depends_on_channels=list(DEPENDS[detector]))


def _finish(name: str, outcomes: list, channels: dict, extra: dict | None = None) -> dict:
    incomplete = [c for c in DEPENDS[name] if channels[c]["state"] != "complete"]
    for item in outcomes:
        if item["outcome"] == "resolved" and item["finding"] != "observed" and incomplete:
            item["evidence"] = dict(item["evidence"], downgraded_from=item["finding"],
                                    incomplete_channels=incomplete)
            item["outcome"], item["finding"] = "insufficient_evidence", "collection_incomplete"
    counts = {k: sum(o["outcome"] == k for o in outcomes) for k in OUTCOMES}
    return dict(version=DETECTOR_VERSION, depends_on_channels=list(DEPENDS[name]),
                channel_states={c: channels[c]["state"] for c in DEPENDS[name]},
                outcomes=outcomes, counts=counts, **(extra or {}))


# ---------------------------------------------------------------- shared views

def _field_entries(doc: dict, field: str) -> dict:
    from scripts.profile_pilot.census import field_value
    grouped: dict[str, list] = {}
    for fact in doc["facts"]:
        if fact["field"] == field and fact["context_resolved"]:
            grouped.setdefault(fact["context_id"], []).append(fact)
    return {cid: field_value(items) for cid, items in grouped.items()}


def _dims(context: dict) -> frozenset:
    return frozenset([("e", a, m) for a, m in context["dimensions"]]
                     + [("t", d["axis"], d["value"]) for d in context["typed_dimensions"]])


def _period_key(context: dict) -> tuple:
    p = context["period"]
    return (p["kind"], p.get("instant"), p.get("start"), p.get("end"))


def _identifier(context: dict) -> str | None:
    idents = [d["value"] for d in context["typed_dimensions"]
              if "investmentidentifier" in _local(d["axis"]).lower()]
    return idents[0] if len(idents) == 1 else None


def _comparable(parent: dict, children: list) -> bool:
    return (parent["status"] in SINGLE and all(
        c["status"] in SINGLE and c["currency"] == parent["currency"] and parent["currency"]
        and c["decimals"] == parent["decimals"] and c["unit_kind"] == parent["unit_kind"]
        for c in children))


# ---------------------------------------------------------------- subtotal

def detect_subtotals(doc: dict, aggregate_markers: dict | None) -> list:
    fv = _field_entries(doc, "fair_value")
    contexts = {c["id"]: c for c in doc["contexts"] if c["id"] in fv}
    groups: dict[tuple, list] = {}
    for context in contexts.values():
        groups.setdefault((context["entity"]["identifier"], _period_key(context)), []).append(context)
    markers = (aggregate_markers or {}).get("markers") or []
    reported: dict[str, set] = {}
    for fact in doc["facts"]:
        if fact["field"] in NON_BALANCE and fact["status"] == "reported":
            reported.setdefault(fact["context_id"], set()).add(fact["field"])
    out = []
    for members in groups.values():
        dims = {c["id"]: _dims(c) for c in members}
        for parent in sorted(members, key=lambda c: c["id"]):
            pid, pdims = parent["id"], dims[parent["id"]]
            label = _identifier(parent)
            labelled = bool(label and LABEL_RE.match(label))
            sets = []
            if not parent["typed_dimensions"]:
                axes = {a for kind, a, _ in pdims}
                by_axis: dict[str, list] = {}
                leaf = []
                for other in members:
                    extra = dims[other["id"]] - pdims
                    if other["id"] == pid or not pdims < dims[other["id"]]:
                        continue
                    if any(_local(a).lower() in SCOPE_AXES for _, a, _ in extra):
                        continue
                    if len(extra) == 1 and next(iter(extra))[0] == "e" and next(iter(extra))[1] not in axes:
                        by_axis.setdefault(next(iter(extra))[1], []).append(other["id"])
                    if _identifier(other):
                        leaf.append(other["id"])
                sets += [("axis:" + axis, sorted(ids)) for axis, ids in sorted(by_axis.items())]
                if leaf:
                    sets.append(("leaf_positions", sorted(leaf)))
            if labelled:
                peers = [c["id"] for c in members if c["id"] != pid and _identifier(c)
                         and not LABEL_RE.match(_identifier(c))
                         and sorted(c["dimensions"]) == sorted(parent["dimensions"])]
                if peers:
                    sets.append(("labelled_peer_group", sorted(peers)))
            if not sets and not labelled:
                continue
            subject = dict(context_id=pid, label=label, period=parent["period"])
            entry = fv[pid]
            marker = next((m for m in markers if label and m in label.lower()), None)
            marker_evidence = None if marker is None else dict(
                marker=marker, provenance="inherited", inherited_from=aggregate_markers.get("path"),
                sha256=aggregate_markers.get("sha256"), note="corroboration only; no value read")
            heading = ("undimensioned_fund_context" if not pdims else
                       "category_only_dimensions" if (not parent["typed_dimensions"]
                                                      and parent.get("role") != "confirmed_position")
                       else ("total_label" if labelled else None))
            if entry["status"] not in SINGLE:
                out.append(_outcome("subtotal", subject, "insufficient_evidence", "parent_value_not_single",
                                    dict(parent_status=entry["status"], reason=entry.get("reason"))))
                continue
            matches, incomparable = [], []
            for kind, ids in sets:
                children = [fv[i] for i in ids]
                if not _comparable(entry, children):
                    incomparable.append(dict(set=kind, children=ids))
                    continue
                total = sum((Decimal(c["value"]) for c in children), Decimal(0))
                if total == Decimal(entry["value"]):
                    matches.append(dict(set=kind, children=ids, sum=str(total)))
            evidence = dict(parent_value=entry["value"], currency=entry["currency"],
                            decimals=entry["decimals"], heading=heading, matched_sets=matches,
                            incomparable_sets=incomparable,
                            evaluated_sets=[dict(set=k, size=len(i)) for k, i in sets],
                            wrapper_marker=marker_evidence)
            structural = [m for m in matches if m["set"] != "labelled_peer_group"]
            tranche = sorted(reported.get(pid, ()))
            evidence["position_tranche_fields"] = tranche
            if labelled and tranche and not structural:
                # A "Total ..." label on a context that carries position-level tranche facts
                # (maturity, rate, spread) is a position (e.g. Total Safety), even if a peer
                # sum happens to match.
                out.append(_outcome("subtotal", subject, "resolved", "not_subtotal",
                                    dict(evidence, reason="label carries position-level tranche facts")))
            elif structural:
                evidence["children"] = structural[0]["children"]
                if heading in ("undimensioned_fund_context", "category_only_dimensions"):
                    out.append(_outcome("subtotal", subject, "resolved", "structural_subtotal", evidence))
                else:
                    out.append(_outcome("subtotal", subject, "candidate", "structural_sum_without_heading",
                                        evidence))
            elif matches:
                evidence["children"] = matches[0]["children"]
                out.append(_outcome("subtotal", subject, "candidate", "labelled_peer_sum", evidence))
            elif incomparable:
                out.append(_outcome("subtotal", subject, "insufficient_evidence", "children_not_comparable",
                                    evidence))
            elif heading in ("undimensioned_fund_context", "category_only_dimensions"):
                out.append(_outcome("subtotal", subject, "candidate", "heading_without_sum_match", evidence))
            elif marker_evidence:
                out.append(_outcome("subtotal", subject, "candidate", "wrapper_marker_only", evidence,
                                    provenance="inherited", inherited_from=marker_evidence["inherited_from"]))
            elif labelled:
                # Missing one fixed peer sum is not evidence against a subtotal.
                out.append(_outcome("subtotal", subject, "insufficient_evidence",
                                    "total_label_without_sum_match", evidence))
            else:
                out.append(_outcome("subtotal", subject, "resolved", "not_subtotal",
                                    dict(evidence, reason="inherited role is confirmed_position and no "
                                         "structural child set sums to it")))
    return out


# ---------------------------------------------------------------- alternate view

def _same(a: dict, b: dict) -> bool | None:
    """True/False when comparable (same unit kind, currency, decimals), else None."""
    if a["status"] not in SINGLE or b["status"] not in SINGLE:
        return None
    if (a.get("unit_kind"), a.get("currency"), a.get("decimals")) != (
            b.get("unit_kind"), b.get("currency"), b.get("decimals")):
        return None
    return a["value"] == b["value"]


def detect_alternate_views(doc: dict) -> tuple[list, int]:
    contexts = {c["id"]: c for c in doc["contexts"]}
    groups: dict[tuple, list] = {}
    not_evaluated = 0
    for pos in doc["positions"]:
        context = contexts[pos["context_id"]]
        ident = pos["identity"]["typed_identifier"]
        if not ident:
            not_evaluated += 1
            continue
        key = (context["entity"]["identifier"], _period_key(context), " ".join(ident.lower().split()))
        groups.setdefault(key, []).append(pos)
    out = []
    for (_, _, ident_key), members in sorted(groups.items(), key=lambda kv: str(kv[0])):
        if len(members) < 2:
            continue
        members = sorted(members, key=lambda p: p["context_id"])
        if len(members) > MAX_GROUP:
            out.append(_outcome("alternate_view", dict(context_ids=[p["context_id"] for p in members],
                                                       identity_key=ident_key),
                                "insufficient_evidence", "group_too_large", dict(size=len(members))))
            continue
        for i, a in enumerate(members):
            for b in members[i + 1:]:
                out.append(_pair(a, b, contexts, ident_key))
    return out, not_evaluated


def _pair(a: dict, b: dict, contexts: dict, ident_key: str) -> dict:
    da = {("e", x, y) for x, y in contexts[a["context_id"]]["dimensions"]}
    db = {("e", x, y) for x, y in contexts[b["context_id"]]["dimensions"]}
    differing = sorted({axis for _, axis, _ in da ^ db})
    subject = dict(context_ids=[a["context_id"], b["context_id"]], identity_key=ident_key)
    equal, differ, incomparable = [], [], []
    for field in NON_BALANCE + BALANCE:
        fa, fb = a["fields"].get(field, {}), b["fields"].get(field, {})
        if fa.get("status") in (None, "absent", "unobservable") or fb.get("status") in (
                None, "absent", "unobservable"):
            continue
        same = _same(fa, fb)
        (incomparable if same is None else equal if same else differ).append(field)
    evidence = dict(differing_axes=differing, equal_fields=equal, differing_fields=differ,
                    incomparable_fields=incomparable, period=contexts[a["context_id"]]["period"],
                    note="no canonical view is selected")
    if any(_local(axis).lower() in SCOPE_AXES for axis in differing):
        return _outcome("alternate_view", subject, "resolved", "distinct_accounting_scope", evidence)
    if any(f in NON_BALANCE for f in differ):
        return _outcome("alternate_view", subject, "resolved", "distinct_tranches", evidence)
    if differ:
        return _outcome("alternate_view", subject, "resolved", "distinct_balances", evidence)
    if not differing:
        return _outcome("alternate_view", subject, "insufficient_evidence", "no_differing_axis", evidence)
    if incomparable:
        return _outcome("alternate_view", subject, "insufficient_evidence", "incomparable_fields", evidence)
    if any(f in NON_BALANCE for f in equal):
        return _outcome("alternate_view", subject, "candidate", "alternate_view", evidence)
    if equal:
        return _outcome("alternate_view", subject, "insufficient_evidence", "balances_only", evidence)
    return _outcome("alternate_view", subject, "insufficient_evidence", "no_comparable_fields", evidence)


# ---------------------------------------------------------------- non-disclosure

def detect_non_disclosure(doc: dict, texts: dict) -> list:
    channels = doc["channels"]
    observed: dict[str, dict] = {}
    for fact in doc["facts"]:
        if fact["field"] and fact["status"] != "not_collected":
            slot = observed.setdefault(fact["field"], {})
            slot[fact["status"]] = slot.get(fact["status"], 0) + 1
    identifiers = [d["value"].lower() for c in doc["contexts"] for d in c["typed_dimensions"]]
    identifiers += [_local(m).lower() for c in doc["contexts"] for _, m in c["dimensions"]]
    fact_texts = [(k, v.lower()) for k, v in texts.items() if not str(k).startswith("footnote:")]
    notes = [(k, v.lower()) for k, v in texts.items() if str(k).startswith("footnote:")]
    unsupported = [c for c in DEPENDS["non_disclosure"] if channels[c]["state"] == "unsupported"]
    incomplete = [c for c in DEPENDS["non_disclosure"]
                  if channels[c]["state"] not in ("complete", "unsupported")]
    out = []
    for field, terms in NON_DISCLOSURE_TERMS.items():
        subject = dict(field=field)
        if field in observed:
            out.append(_outcome("non_disclosure", subject, "resolved", "observed",
                                dict(fact_status_counts=observed[field])))
            continue
        hits = {}
        for channel, items in (("identifiers", [(None, t) for t in identifiers]),
                               ("text_facts", fact_texts), ("footnotes", notes)):
            found = [key for key, text in items if any(term in text for term in terms)]
            if found:
                hits[channel] = dict(count=len(found), examples=[str(k) for k in found[:5]
                                                                 if k is not None])
        evidence = dict(terms=list(terms), hits=hits, unsupported_channels=unsupported,
                        incomplete_channels=incomplete,
                        note="XBRL absence is never full-filing non-disclosure")
        if hits:
            out.append(_outcome("non_disclosure", subject, "candidate", "disclosed_outside_tagged_concept",
                                evidence))
        elif unsupported or incomplete:
            out.append(_outcome("non_disclosure", subject, "insufficient_evidence",
                                "channels_not_all_supported", evidence))
        else:
            out.append(_outcome("non_disclosure", subject, "resolved", "not_observed_in_complete_instance",
                                evidence))
    return out



# ---------------------------------------------------------------- partition

def _profile(rows: list) -> dict:
    n = len(rows)
    profile = {}
    for delim in DELIMITERS:
        having = [r for r in rows if delim in r["investment_identifier"]]
        counts: dict[int, int] = {}
        for r in having:
            k = len(r["investment_identifier"].split(delim))
            counts[k] = counts.get(k, 0) + 1
        profile[delim] = dict(rows=len(having), prevalence=round(len(having) / n, 4) if n else 0,
                              segment_counts={str(k): v for k, v in sorted(counts.items())})
    return profile


def _matches(predicate: dict, row: dict) -> bool | None:
    from scripts.profile_pilot import envelope
    try:
        return envelope.predicate_matches(predicate, row)
    except envelope.PredicateEvaluationError:
        return None


def _candidates_for(group: list, defining: tuple) -> list:
    preds = []
    pairs = sorted({tuple(p) for r in group for p in r["dimensions"]})
    preds += [dict(kind="axis_member", axis=a, member=m) for a, m in pairs]
    concepts = sorted({r["fair_value_concept"] for r in group if r["fair_value_concept"]})
    preds += [dict(kind="carrying_concept", field="fair_value", concept=c) for c in concepts]
    # Segment counts on the delimiters that DEFINE the signature only restate it
    # (e.g. count 1 = "delimiter absent"); they are not independent discriminators.
    for delim in DELIMITERS:
        if delim in defining:
            continue
        counts = sorted({len(r["investment_identifier"].split(delim)) for r in group})
        preds += [dict(kind="segment_count", delimiter=delim, count=k) for k in counts if k > 1]
    # A prefix vocabulary must be SHARED (each entry on >= 2 rows): unique borrower
    # names are not a vocabulary.
    tokens: dict[str, int] = {}
    for r in group:
        token = (r["investment_identifier"].split() or [""])[0]
        tokens[token] = tokens.get(token, 0) + 1
    if tokens and "" not in tokens and len(tokens) <= MAX_PREFIX_VOCABULARY and min(tokens.values()) >= 2:
        preds.append(dict(kind="prefix", vocabulary=sorted(tokens)))
    dialects = sorted({r["grammar_dialect"] for r in group if r.get("grammar_dialect")})
    preds += [dict(kind="grammar_dialect", dialect=d) for d in dialects]
    return preds


def _grammar_rows(rows: list, grammar: dict | None) -> dict:
    """Label each row with the inherited grammar dialect that parses it (or `unparsed:`)."""
    if not grammar:
        return dict(status="insufficient_evidence", cause="no_authored_grammar",
                    note="no identifier_rate_grammars file for this CIK; grammar_dialect not searchable")
    from pipeline.identifier_rate import apply_grammar
    body = grammar["body"]
    applies = body.get("applies_to") or {}
    name = str(applies.get("signature") or body.get("dominant_signature") or "grammar")
    required = list(body.get("required_fields") or [])
    counts: dict[str, int] = {}
    for row in rows:
        try:
            parsed = apply_grammar(row["investment_identifier"], body)
        except Exception as exc:  # a malformed inherited grammar is evidence, not a crash
            return dict(status="insufficient_evidence", cause="grammar_not_applicable",
                        error=type(exc).__name__, provenance="inherited",
                        inherited_from=grammar["path"], sha256=grammar["sha256"])
        ok = (all(parsed.get(f) is not None for f in required) if required
              else any(v is not None for v in parsed.values()))
        row["grammar_dialect"] = name if ok else "unparsed:" + name
        counts[row["grammar_dialect"]] = counts.get(row["grammar_dialect"], 0) + 1
    return dict(status="evaluated", dialect=name, required_fields=required, rows_by_dialect=counts,
                provenance="inherited", inherited_from=grammar["path"], sha256=grammar["sha256"],
                parser="pipeline/identifier_rate.py:apply_grammar")


def _signatures(rows: list, profile: dict) -> list:
    n = len(rows)
    prevalent = sorted((d for d in DELIMITERS if profile[d]["prevalence"] > DIALECT_SHARE),
                       key=lambda d: (-profile[d]["prevalence"], DELIMITERS.index(d)))
    out = [dict(kind="delimiters", delimiters=[d1, d2])
           for i, d1 in enumerate(prevalent) for d2 in prevalent[i + 1:]]
    for delim in DELIMITERS:
        modes = sorted(((int(k), v) for k, v in profile[delim]["segment_counts"].items()
                        if v / n > DIALECT_SHARE), key=lambda kv: (-kv[1], kv[0]))
        if len(modes) >= 2:
            out.append(dict(kind="segment_counts", delimiter=delim, counts=sorted([modes[0][0], modes[1][0]])))
    return out


def _inside_segment(rows: list, outer: str, inner: str) -> dict | None:
    """`inner` occurs only inside one fixed segment of the `outer` split (e.g. a comma in
    the borrower name before ' - '): punctuation, not a second dialect."""
    having = [r["investment_identifier"] for r in rows if inner in r["investment_identifier"]]
    if not having or any(outer not in text for text in having):
        return None
    positions = set()
    for text in having:
        positions |= {i for i, seg in enumerate(text.split(outer)) if inner in seg}
        if len(positions) > 1:
            return None
    return dict(outer=outer, inner=inner, segment_index=positions.pop(), rows=len(having))


def _search(g1: list, g2: list, others: list, defining: tuple) -> tuple[list, list]:
    exact, near = [], []
    for mine, theirs in ((g1, g2), (g2, g1)):
        for predicate in _candidates_for(mine, defining):
            hit_mine = [_matches(predicate, r) for r in mine]
            hit_theirs = [_matches(predicate, r) for r in theirs]
            if None in hit_mine or None in hit_theirs:
                continue
            share_mine = sum(hit_mine) / len(mine)
            share_theirs = sum(hit_theirs) / len(theirs)
            record = dict(predicate=predicate, selects_share=round(share_mine, 4),
                          other_share=round(share_theirs, 4),
                          other_group_rows_matched=sum(bool(_matches(predicate, r)) for r in others))
            if share_mine == 1 and share_theirs == 0:
                exact.append(record)
            elif share_mine >= NEAR_SHARE and share_theirs <= 1 - NEAR_SHARE:
                near.append(dict(record, exceptions=[r["context_id"] for r, h in zip(mine, hit_mine) if not h]
                                 + [r["context_id"] for r, h in zip(theirs, hit_theirs) if h]))
    return exact, near


def _evaluate_signature(signature: dict, rows: list, base_subject: dict, base_evidence: dict,
                        grammar_record: dict) -> dict:
    subject = dict(base_subject, signature=signature)
    evidence = dict(base_evidence, grammar_dialect=grammar_record,
                    searched_kinds=["axis_member", "carrying_concept", "segment_count", "prefix",
                                    "grammar_dialect"])
    if signature["kind"] == "delimiters":
        d1, d2 = signature["delimiters"]
        defining = (d1, d2)
        for outer, inner in ((d1, d2), (d2, d1)):
            inside = _inside_segment(rows, outer, inner)
            if inside:
                evidence.update(inside_segment=inside)
                return _outcome("partition", subject, "resolved", "secondary_delimiter_inside_segment",
                                evidence)
        only1 = [r for r in rows if d1 in r["investment_identifier"] and d2 not in r["investment_identifier"]]
        with2 = [r for r in rows if d2 in r["investment_identifier"]]
        both = sum(d1 in r["investment_identifier"] for r in with2)
        g1, g2 = only1, with2
        labels = [dict(group=repr(d1) + " without " + repr(d2), rows=len(g1)),
                  dict(group="with " + repr(d2), rows=len(g2), of_which_also_contain=both)]
        evidence.update(disjoint=both == 0)
    else:
        delim, (k1, k2) = signature["delimiter"], signature["counts"]
        defining = (delim,)
        g1 = [r for r in rows if delim in r["investment_identifier"]
              and len(r["investment_identifier"].split(delim)) == k1]
        g2 = [r for r in rows if delim in r["investment_identifier"]
              and len(r["investment_identifier"].split(delim)) == k2]
        labels = [dict(group="%d segments on %r" % (k1, delim), rows=len(g1)),
                  dict(group="%d segments on %r" % (k2, delim), rows=len(g2))]
    evidence.update(groups=labels,
                    excluded_as_tautological="segment_count on the signature delimiter(s) " + repr(list(defining)))
    if not g1 or not g2:
        evidence["packet_stub"] = dict(question="Overlapping signature " + repr(signature)
                                       + " leaves one side empty and is not punctuation inside one segment.",
                                       groups=labels)
        return _outcome("partition", subject, "insufficient_evidence", "overlapping_signature_unexplained",
                        evidence)
    ids = {r["context_id"] for r in g1} | {r["context_id"] for r in g2}
    others = [r for r in rows if r["context_id"] not in ids]
    exact, near = _search(g1, g2, others, defining)
    if exact:
        evidence.update(predicates=[e["predicate"] for e in exact], discriminators=exact, disjoint_partition=True)
        if all(e["predicate"]["kind"] == "grammar_dialect" for e in exact):
            return _outcome("partition", subject, "resolved", "evidenced_partition", evidence,
                            provenance="inherited", inherited_from=grammar_record["inherited_from"])
        return _outcome("partition", subject, "resolved", "evidenced_partition", evidence)
    if near:
        evidence.update(near_discriminators=near)
        return _outcome("partition", subject, "candidate", "near_discriminator", evidence)
    evidence["packet_stub"] = dict(
        question="Signature " + repr(signature) + " has no structural discriminator: one grammar with "
                 "optional segments or two filer dialects?",
        groups=[dict(label, examples=[dict(context_id=r["context_id"], identifier=r["investment_identifier"])
                                     for r in g[:5]])
                for label, g in zip(labels, (g1, g2))])
    return _outcome("partition", subject, "insufficient_evidence", "no_structural_discriminator", evidence)


def detect_partitions(doc: dict, learned_predicates: list | None, grammar: dict | None = None) -> list:
    dped = set(doc["document_metadata"]["document_period_end_dates"])
    fv_concepts: dict[str, set] = {}
    for fact in doc["facts"]:
        if fact["field"] == "fair_value":
            fv_concepts.setdefault(fact["context_id"], set()).add(fact["qname"])
    positions = [p for p in doc["positions"] if p["identity"]["typed_identifier"]]
    current = [p for p in positions if p["period"].get("instant") in dped]
    basis = "document_period_end" if current else "all_periods"
    rows = [dict(context_id=p["context_id"], investment_identifier=p["identity"]["typed_identifier"],
                 dimensions=[list(x) for x in p["identity"]["dimensions"]],
                 fair_value_concept=(next(iter(fv_concepts[p["context_id"]]))
                                     if len(fv_concepts.get(p["context_id"], ())) == 1 else None))
            for p in (current or positions)]
    subject = dict(field="investment_identifier", rows=len(rows), basis=basis)
    profile = _profile(rows)
    evidence = dict(delimiter_profile=profile)
    grammar_record = _grammar_rows(rows, grammar)
    if learned_predicates:
        evidence["learned_checks"] = [dict(predicate=p, matched=sum(bool(_matches(p, r)) for r in rows),
                                           unevaluable=sum(_matches(p, r) is None for r in rows))
                                      for p in learned_predicates]
    if len(rows) < MIN_PARTITION_ROWS:
        return [_outcome("partition", dict(subject, signature=dict(kind="none")), "insufficient_evidence",
                         "too_few_identifiers", dict(evidence, grammar_dialect=grammar_record))]
    signatures = _signatures(rows, profile)
    if not signatures:
        return [_outcome("partition", dict(subject, signature=dict(kind="none")), "resolved", "single_dialect",
                         dict(evidence, grammar_dialect=grammar_record,
                              note="no two delimiters above " + str(DIALECT_SHARE)
                              + " prevalence and no multi-modal segment count"))]
    return [_evaluate_signature(sig, rows, subject, evidence, grammar_record) for sig in signatures]


# ---------------------------------------------------------------- entry point

def detect_structure(doc: dict, texts: dict, *, aggregate_markers: dict | None = None,
                     learned_predicates: list | None = None, grammar: dict | None = None) -> dict:
    channels = doc["channels"]
    if doc["collection"]["state"] == "failed":
        return {name: _finish(name, [_outcome(name, dict(scope="instance"), "insufficient_evidence",
                                              "collection_incomplete",
                                              dict(collection_state="failed",
                                                   errors=doc["collection"]["errors"]))], channels)
                for name in DEPENDS}
    views, not_evaluated = detect_alternate_views(doc)
    return dict(
        subtotal=_finish("subtotal", detect_subtotals(doc, aggregate_markers), channels,
                         dict(wrapper_markers="inherited corroboration only" if aggregate_markers
                              else "not supplied")),
        alternate_view=_finish("alternate_view", views, channels,
                               dict(not_evaluated_without_typed_identifier=not_evaluated)),
        non_disclosure=_finish("non_disclosure", detect_non_disclosure(doc, texts), channels),
        partition=_finish("partition", detect_partitions(doc, learned_predicates, grammar), channels,
                          dict(grammar="supplied (inherited)" if grammar else "no authored grammar")))
