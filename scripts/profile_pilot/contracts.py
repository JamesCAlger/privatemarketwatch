"""Task 8: partitioned contracts learned from Q1, frozen, then evaluated on Q2 (spec 6.3, 9: M2).

Order (spec 6.3 / s8): (1) the tolerance table is frozen (`freeze_tolerances`, write-once,
Task 1 mechanism) before anything is learned; (2) `learn_contracts` reads ONLY the Q1
census, the Q1 profile, the authored grammar and the Q1 yield evidence, and learns every
contract inside the partitions evidenced in Q1; (3) `freeze_contracts` writes the full
fixed denominator (one contract per cik x field x partition x kind, with its learned
expectation and its band) before any Q2 census is parsed; (4) `evaluate_contracts` takes
the FROZEN inventory block and the FROZEN tolerance content (never SPEC_BANDS, which is
used only to write the tolerance file) and the Q2 observations; a missing frozen field
raises ContractError (fail closed); (5) `summarise_m2`.

Minimal suite, exactly: source_concept_set, fill_rate, scale, format_grammar, value_range,
fund_income_yield. Deferred and unchecked: non-accrual count, footnote-location,
position-identity. Every contract ends in exactly one of holds, holds_with_form_type,
breach, insufficient_evidence. holds_with_form_type is unreachable by construction here
(ruling R29): a form qualifier cannot be evidenced from one learning quarter, and a
10-Q/10-K change grants no tolerance relief; results are split by Q2 form type instead.

Partitions: predicates come from Q1 `evidenced_partition` detector outcomes (and any Q1
profile entry with a non-null applies_to); rows are routed with envelope.resolve_for_row
(partition-specific before the null partition; equally specific matches are ambiguous and
never picked). With no evidenced partition every contract is whole-filing (applies_to
null). An unresolved mixed identifier format (partition candidate / insufficient with a
real signature) blocks the identifier format contract: it is insufficient_evidence, not a
default whole-filing grammar contract.

Scale is the declared unit plus a deterministic conversion to percent (pure x100,
percent x1, bps /100). Namespace never identifies scale; magnitude is used ONLY to abstain
(mixed magnitudes under one declared unit, or a changed magnitude regime), never to assign
a scale. Stage B note (R28): Q2 "interpreted rows" are the Q2 census positions; Stage C
re-measures on interpreted rows. A `holds` records agreement with Q1; it proves nothing
about correctness.
"""
from __future__ import annotations

import copy

from scripts.profile_pilot import envelope
from scripts.profile_pilot.census import POSITION_FIELDS, POSITION_RATE, field_channel
from scripts.profile_pilot.contracts_observe import (  # noqa: F401  (current_positions, grammar_info re-exported)
    IDENTIFIER_FIELD, RATIO_CLASSES, SCALE_CONVENTIONS, WHOLE_FILING, canonical, channel_gaps, current_positions,
    grammar_info, grammar_observation, learn_partitions, observe_field, quantile, route, routing_rows, widened)

CONTRACTS_VERSION = "contracts.v0.1"
TOLERANCES_VERSION = "contract-tolerances.v1"
KINDS = ("source_concept_set", "fill_rate", "scale", "value_range", "format_grammar", "fund_income_yield")
STATUSES = ("holds", "holds_with_form_type", "breach", "insufficient_evidence")
CONCEPT_FIELDS = POSITION_FIELDS
SCALE_FIELDS = POSITION_RATE + ("pct_of_net_assets",)
RANGE_FIELDS = POSITION_RATE
YIELD_FIELD = "interest_rate"
LOW_HISTORY_BELOW = 50
SPEC_TABLE = [
    dict(expectation="source concept set", standard="identical set", low_history="identical set"),
    dict(expectation="fill rate", standard="+/- 10 percentage points", low_history="+/- 25 percentage points"),
    dict(expectation="scale", standard="identical", low_history="identical"),
    dict(expectation="value range (rates, spreads)", standard="Q2 p5-p95 inside Q1 min-max widened by 25%",
         low_history="same, widened by 50%"),
    dict(expectation="format grammar", standard="every Q2 identifier parses", low_history=">= 90% parse")]
SPEC_BANDS = {
    "standard": dict(source_concept_set="identical", fill_rate_pp=10, scale="identical", value_range_widen=0.25,
                     value_range_quantiles=[0.05, 0.95], format_grammar_min_parse_share=1.0),
    "low_history": dict(source_concept_set="identical", fill_rate_pp=25, scale="identical", value_range_widen=0.5,
                        value_range_quantiles=[0.05, 0.95], format_grammar_min_parse_share=0.9)}
KIND_BAND_KEYS = {"source_concept_set": ("source_concept_set",), "fill_rate": ("fill_rate_pp",),
                  "scale": ("scale",), "value_range": ("value_range_widen", "value_range_quantiles"),
                  "format_grammar": ("format_grammar_min_parse_share",), "fund_income_yield": ()}
DEFERRED = [dict(kind="non_accrual_count", status="unchecked", reason="deferred by the minimal-suite ruling"),
            dict(kind="footnote_location", status="unchecked", reason="deferred; footnote channel unsupported"),
            dict(kind="position_identity", status="unchecked", reason="deferred by the minimal-suite ruling")]
STAGE_B_NOTE = ("Stage B (ruling R28): Q2 interpreted rows are the Q2 census positions (canonical field values, "
                "raw values, units, decimals) plus identifier strings; the yield contract uses the pinned "
                "production slices through S2 (inherited evidence). Stage C re-measures on interpreted rows.")
HOLDS_WITH_FORM_TYPE_REASON = ("unreachable by construction (ruling R29): one learning quarter cannot evidence a "
                               "form-type qualifier; a 10-Q/10-K change grants no tolerance relief. Results are "
                               "split by Q2 form type instead.")
CLAIM = "A holds records agreement with the frozen Q1 expectation; it is not a correctness claim."


class ContractError(RuntimeError):
    """A frozen artifact is missing a field or disagrees with itself: fail closed."""


def _req(mapping, key, where: str):
    if not isinstance(mapping, dict) or key not in mapping:
        raise ContractError("frozen " + where + " is missing " + repr(key))
    return mapping[key]


# ---------------------------------------------------------------- tolerances (frozen first)

def tolerance_content() -> dict:
    from scripts.profile_pilot.contracts_income import S2_FUNCTION, s2_constants
    return dict(
        version=TOLERANCES_VERSION, source="docs/superpowers/specs/2026-09-28-filer-profile-pilot-design.md s6.3",
        spec_table_verbatim=copy.deepcopy(SPEC_TABLE), bands=copy.deepcopy(SPEC_BANDS),
        low_history_below_positions=LOW_HISTORY_BELOW,
        operationalisation=dict(
            position_count="current-period (document_period_end) recognised positions in the Q1 census",
            fill_rate="filled (reported or consistent_duplicate) / positions; nil, absent and conflict are not "
                      "filled; a reported zero is filled; |Q2 - Q1| * 100 <= fill_rate_pp holds",
            source_concept_set="set of concepts carrying the filled values; identical set holds",
            scale="declared unit class (pure/percent/bps) + conversion; a changed class is a breach; mixed or "
                  "changed magnitude regime under one declared unit is insufficient_evidence",
            value_range="canonical percent values; widened = [min - w*(max-min), max + w*(max-min)] "
                        "(w*|value| each side when max == min); Q2 p5 and p95 (linear interpolation) inside "
                        "the widened Q1 range holds",
            format_grammar="authored grammar (inherited), rows whose keyword signature is in the grammar's "
                           "declared signatures; parse = every required field extracted; parse share >= band; "
                           "learned only if Q1 itself meets the band inside a non-empty scope; an unresolved mixed "
                           "identifier format in Q1 leaves it insufficient_evidence; an empty Q2 scope is a breach",
            label_rows="identifier rows matching ^(sub)?total are set aside for the format contract"),
        scale_conventions=copy.deepcopy(SCALE_CONVENTIONS),
        fund_income_yield=dict(s2_function=S2_FUNCTION, constants=s2_constants(),
                               expectation="the Q1 S2 vote (cash_leg or all_in) persists in Q2",
                               vote_rule="S2's own per-quarter votes (tagged / estimated thresholds)"),
        form_type_qualifiers=dict(evidenced=[], rule=HOLDS_WITH_FORM_TYPE_REASON),
        reporting="reporting bands, not pass/fail bars; the pilot records")


def band_for(tolerances: dict, tier: str, kind: str) -> dict:
    if kind == "fund_income_yield":
        section = _req(tolerances, "fund_income_yield", "tolerances")
        return dict(s2_constants=_req(section, "constants", "tolerances.fund_income_yield"))
    bands = _req(_req(tolerances, "bands", "tolerances"), tier, "tolerances.bands")
    return {key: _req(bands, key, "tolerances.bands." + tier) for key in KIND_BAND_KEYS[kind]}


def tier_for(tolerances: dict, positions: int) -> str:
    return "low_history" if positions < _req(tolerances, "low_history_below_positions", "tolerances") else "standard"


def freeze_tolerances(paths) -> dict:
    from scripts.profile_pilot import manifest
    return manifest.freeze_inventory(paths, "contract_tolerances", tolerance_content())


# ---------------------------------------------------------------- learning (Q1 only)

def _profile_entry(entries: list, rows: list, field: str, report_date: str, form_type) -> dict | None:
    key = "column_contract." + field
    if not rows:
        return None
    hits = set()
    found = None
    sample = rows if any(e["key"] == key and e["applies_to"] is not None for e in entries) else rows[:1]
    for row in sample:
        res = envelope.resolve_for_row(entries, row, key, report_date, form_type, None)
        hits.add(res.entry["entry_id"] if res.found else None)
        found = res.entry if res.found else found
    return dict(split=True) if len(hits) > 1 else found


def _profile_disagrees(entry, obs: dict, partitioned: bool) -> str | None:
    if partitioned:
        return None
    if obs["filled"] == 0:
        return "profile has a column_contract entry for a field with no filled Q1 value" if entry else None
    if not entry or entry.get("split"):
        return "no single profile column_contract entry for a filled Q1 field"
    support = entry.get("support") or {}
    if (entry["value"] or {}).get("concepts") != obs["concepts"] or support.get("numerator") != obs["filled"] \
            or support.get("denominator") != obs["rows"]:
        return "profile concepts/support differ from the census"
    return None


def _contract(cik, kind, field, partition, tier, band, *, expectation=None, cause=None, evidence=None) -> dict:
    return dict(contract_id=":".join((cik, kind, field, partition["partition_id"])), cik=cik, kind=kind,
                field=field, partition_id=partition["partition_id"], applies_to=partition["applies_to"], tier=tier,
                band=band, learn_status="learned" if cause is None else "insufficient_evidence",
                learn_cause=cause, expectation=expectation, evidence=evidence or {})


def _learn_scale(obs: dict, gaps: list) -> tuple[dict | None, str | None]:
    if gaps or obs["unobservable_keys"]:
        return None, "q1_channel_incomplete"
    if not obs["filled"]:
        return None, "no_q1_observations"
    if any(c["reason"] == "unit_differs" for c in obs["conflicts"]):
        return None, "conflicting_units_on_one_field"
    classes = list(obs["classes"])
    if len(classes) > 1:
        return None, "mixed_declared_units_unresolved"
    if classes[0] not in RATIO_CLASSES:
        return None, "no_declared_ratio_unit"
    if len(obs["values"]) != obs["filled"]:
        return None, "unparseable_numeric_values"
    if obs["regime"] == "mixed":
        return None, "magnitude_mixed_under_one_declared_unit"
    if classes[0] == "pure" and obs["regime"] == "ge1":
        return None, "pure_values_inconsistent_with_decimal_convention"
    return dict(scale_class=classes[0], conversion=SCALE_CONVENTIONS[classes[0]],
                magnitude_regime=obs["regime"]), None


def _scale_evidence(obs: dict) -> dict:
    return dict(classes=obs["classes"], magnitude_regime=obs["regime"], decimals=obs["decimals"],
                filled=obs["filled"], unit_conflicts=[c for c in obs["conflicts"] if c["reason"] == "unit_differs"],
                rule="declared unit class + conversion; magnitude only ever triggers abstention")


def learn_contracts(*, cik: str, q1_doc: dict, q1_profile: dict | None, grammar: dict | None, yield_q1: dict,
                    tolerances: dict, q2_listing: dict, recorded_at: str) -> dict:
    """Every contract for one CIK from Q1 evidence only (no Q2 input exists in this signature)."""
    positions = current_positions(q1_doc)
    tier = tier_for(tolerances, len(positions))
    q1_date, q1_form = q1_doc["document"]["report_date"], q1_doc["document"].get("form_type")
    entries = list((q1_profile or {}).get("entries") or [])
    learned = learn_partitions(q1_doc, entries)
    partitions = learned["partitions"]
    rows = routing_rows(q1_doc, positions, grammar)
    routing = route(partitions, rows, q1_date, q1_form, recorded_at)
    by_ctx = {p["context_id"]: p for p in positions}
    rows_by_ctx = {r["context_id"]: r for r in rows}
    blocked = {pid for a in routing["ambiguous"] for pid in a["partitions"]}
    if routing["unroutable"]:
        blocked |= {p["partition_id"] for p in partitions}
    facts_by_i = {f["i"]: f for f in q1_doc["facts"]}
    contracts, partition_records = [], []
    for partition in partitions:
        pid = partition["partition_id"]
        keys = routing["routed"][pid]
        partition_records.append(dict(partition, q1_rows=len(keys)))
        if not keys and pid not in blocked:
            continue
        members = [by_ctx[k] for k in keys]
        member_rows = [rows_by_ctx[k] for k in keys]
        block_cause = "ambiguous_partition_overlap" if pid in blocked else None
        for field in CONCEPT_FIELDS:
            gaps = channel_gaps(q1_doc, ("contexts", field_channel(field)))
            obs = observe_field(q1_doc, members, field, facts_by_i)
            base = block_cause or ("q1_channel_incomplete" if gaps or obs["unobservable_keys"] else None)
            entry = _profile_entry(entries, member_rows, field, q1_date, q1_form)
            disagree = _profile_disagrees(entry, obs, learned["evidenced"])
            cause = base or ("q1_profile_disagrees_with_census" if disagree else None)
            profile_ref = dict(entry_id=(entry or {}).get("entry_id"), disagreement=disagree,
                               note="whole-filing profile entry" if not learned["evidenced"]
                               else "profile entries are whole-filing; not compared per partition")
            contracts.append(_contract(
                cik, "source_concept_set", field, partition, tier, band_for(tolerances, tier, "source_concept_set"),
                expectation=None if cause else dict(concepts=obs["concepts"]), cause=cause,
                evidence=dict(profile=profile_ref, filled=obs["filled"], rows=obs["rows"], channel_gaps=gaps)))
            contracts.append(_contract(
                cik, "fill_rate", field, partition, tier, band_for(tolerances, tier, "fill_rate"),
                expectation=None if cause else dict(fill_share=obs["fill_share"], filled=obs["filled"],
                                                    rows=obs["rows"]),
                cause=cause, evidence=dict(profile=profile_ref, absent=len(obs["absent_keys"]),
                                           nil=len(obs["nil_keys"]), conflicts=len(obs["conflicts"]),
                                           zero_values=obs["zero_values"], channel_gaps=gaps)))
            if field in SCALE_FIELDS:
                expectation, scale_cause = _learn_scale(obs, gaps)
                scale_cause = block_cause or scale_cause
                contracts.append(_contract(cik, "scale", field, partition, tier, band_for(tolerances, tier, "scale"),
                                           expectation=None if scale_cause else expectation, cause=scale_cause,
                                           evidence=_scale_evidence(obs)))
                if field in RANGE_FIELDS:
                    band = band_for(tolerances, tier, "value_range")
                    range_exp, range_cause = None, block_cause or (
                        ("scale_not_established_in_q1" if scale_cause else None))
                    if not range_cause:
                        values = sorted(v for _, v in canonical(obs["values"], expectation["scale_class"]))
                        range_exp = dict(canonical_unit="percent", scale_class=expectation["scale_class"],
                                         min=values[0], max=values[-1], n_values=len(values),
                                         widened=widened(values[0], values[-1], band["value_range_widen"]))
                    contracts.append(_contract(cik, "value_range", field, partition, tier, band,
                                               expectation=range_exp, cause=range_cause,
                                               evidence=dict(scale_learn_cause=scale_cause)))
        contracts.append(_learn_format(cik, partition, tier, tolerances, q1_doc, member_rows, grammar,
                                       learned["identifier_format"], block_cause))
    whole = next(p for p in partitions if p["partition_id"] == WHOLE_FILING)
    vote_ok = yield_q1.get("status") == "vote" and yield_q1.get("vote") in ("cash_leg", "all_in")
    contracts.append(_contract(
        cik, "fund_income_yield", YIELD_FIELD, whole, tier, band_for(tolerances, tier, "fund_income_yield"),
        expectation=dict(vote=yield_q1["vote"], r=(yield_q1.get("s2") or {}).get("r"),
                         src=(yield_q1.get("s2") or {}).get("src"), quarter=q1_date) if vote_ok else None,
        cause=None if vote_ok else str(yield_q1.get("cause") or "q1_yield_without_vote"),
        evidence=dict(q1_yield=yield_q1)))
    return dict(cik=cik, version=CONTRACTS_VERSION, tier=tier,
                q1=dict(report_date=q1_date, form_type=q1_form, positions=len(positions),
                        accession_number=q1_doc["document"].get("accession_number")),
                q2_listing=q2_listing, partitions=partition_records, partitions_evidenced=learned["evidenced"],
                identifier_format=learned["identifier_format"],
                routing=dict(ambiguous=routing["ambiguous"], unroutable=routing["unroutable"]),
                partition_statement=partition_statement(learned["evidenced"]),
                grammar=None if not grammar else dict(path=grammar["path"], sha256=grammar["sha256"],
                                                      dialect=grammar["dialect"], signatures=grammar["signatures"]),
                contracts=contracts, recorded_at=recorded_at, stage_b_note=STAGE_B_NOTE)


def partition_statement(evidenced: bool) -> str:
    if evidenced:
        return "partitions evidenced in Q1; contracts are per partition (applies_to = frozen Q1 predicate)"
    return ("no evidenced partition in Q1: every contract is whole-filing (applies_to null); unresolved mixed "
            "identifier formats leave the format contract insufficient_evidence")


def _learn_format(cik, partition, tier, tolerances, q1_doc, rows, grammar, identifier_format, block_cause) -> dict:
    band = band_for(tolerances, tier, "format_grammar")
    gaps = channel_gaps(q1_doc, ("contexts", "identifiers"))
    obs = grammar_observation(rows, grammar) if grammar and not gaps else None
    if block_cause:
        cause = block_cause
    elif not grammar:
        cause = "no_authored_grammar"
    elif gaps:
        cause = "q1_channel_incomplete"
    elif identifier_format["status"] == "unresolved_mixed":
        cause = "unresolved_mixed_identifier_format"
    elif not obs["scope_rows"]:
        cause = "grammar_scope_empty_in_q1"
    elif obs["parse_share"] < band["format_grammar_min_parse_share"]:
        cause = "grammar_does_not_hold_on_q1"
    else:
        cause = None
    expectation = None if cause else dict(
        field=IDENTIFIER_FIELD, dialect=obs["dialect"], signatures=obs["signatures"],
        required_fields=obs["required_fields"], grammar_sha256=obs["grammar_sha256"],
        q1_scope_rows=obs["scope_rows"], q1_parse_share=obs["parse_share"])
    evidence = dict(obs or {}, identifier_format=identifier_format, channel_gaps=gaps)
    if not grammar:
        evidence["note"] = "delimiter structure (profile identifier_format) is not a rate grammar"
    return _contract(cik, "format_grammar", IDENTIFIER_FIELD, partition, tier, band, expectation=expectation,
                     cause=cause, evidence=evidence)


def freeze_contracts(paths, blocks: dict, *, tolerances_state: dict) -> dict:
    """Write-once contract_inventory: the full fixed M2 denominator with expectations and bands."""
    from scripts.profile_pilot import manifest
    by_cik, by_kind = {}, {}
    for cik, block in blocks.items():
        for c in block["contracts"]:
            by_cik[cik] = by_cik.get(cik, 0) + 1
            by_kind[c["kind"]] = by_kind.get(c["kind"], 0) + 1
    content = dict(version=CONTRACTS_VERSION, tolerances=dict(content_sha256=tolerances_state["content_sha256"],
                                                             path=tolerances_state["path"]),
                   learning="Q1 census + Q1 profile + authored grammar (inherited) + Q1 S2 evidence; no Q2 read",
                   ciks=blocks, denominator=dict(total=sum(by_cik.values()), by_cik=by_cik, by_kind=by_kind),
                   kinds=list(KINDS), deferred_unchecked=DEFERRED, stage_b_note=STAGE_B_NOTE, claim=CLAIM)
    return manifest.freeze_inventory(paths, "contract_inventory", content)


# ---------------------------------------------------------------- evaluation (frozen inputs only)

def _result(c: dict, status: str, q2: dict, *, cause=None, expected=None, observed=None, keys=()) -> dict:
    return dict(contract_id=c["contract_id"], cik=c["cik"], kind=c["kind"], field=c["field"],
                partition_id=c["partition_id"], applies_to=c["applies_to"], tier=c["tier"], status=status,
                cause=cause, expected=expected, observed=observed, violating_keys=sorted(keys), q2=q2,
                band=c["band"])


def _check_frozen(c: dict, tolerances: dict) -> None:
    for key in ("contract_id", "cik", "kind", "field", "partition_id", "applies_to", "tier", "band",
                "learn_status", "learn_cause", "expectation"):
        _req(c, key, "contract " + str(c.get("contract_id")))
    if c["band"] != band_for(tolerances, c["tier"], c["kind"]):
        raise ContractError("frozen contract band disagrees with the frozen tolerance file: " + c["contract_id"])
    if c["learn_status"] == "learned" and c["expectation"] is None:
        raise ContractError("learned contract without an expectation: " + c["contract_id"])


def _check_s2_constants(tolerances: dict) -> None:
    from scripts.profile_pilot.contracts_income import s2_constants
    frozen = _req(_req(tolerances, "fund_income_yield", "tolerances"), "constants", "tolerances.fund_income_yield")
    if frozen != s2_constants():
        raise ContractError("pipeline.rate_convention constants changed after the freeze")


def evaluate_contracts(block: dict, tolerances: dict, *, q2_doc: dict | None, q2_listing: dict,
                       grammar: dict | None, yield_q2: dict | None) -> list:
    """Evaluate the frozen contracts of one CIK on Q2; every contract yields exactly one result."""
    contracts = _req(block, "contracts", "inventory block")
    for c in contracts:
        _check_frozen(c, tolerances)
    _check_s2_constants(tolerances)
    if q2_doc is None:
        q2 = dict(report_date=q2_listing.get("report_date"), form_type=None, status=q2_listing.get("status"),
                  detail=q2_listing.get("detail"))
        return [_result(c, "insufficient_evidence", q2, cause="q2_census_unavailable",
                        observed=dict(detail=q2_listing.get("detail"))) for c in contracts]
    q2 = dict(report_date=q2_doc["document"]["report_date"], form_type=q2_doc["document"].get("form_type"),
              status="available", census_relative=q2_listing.get("census_relative"))
    positions = current_positions(q2_doc)
    partitions = [dict(partition_id=p["partition_id"], applies_to=p["applies_to"])
                  for p in _req(block, "partitions", "inventory block")]
    rows = routing_rows(q2_doc, positions, grammar)
    routing = route(partitions, rows, q2["report_date"], q2["form_type"], _req(block, "recorded_at", "block"))
    by_ctx = {p["context_id"]: p for p in positions}
    rows_by_ctx = {r["context_id"]: r for r in rows}
    facts_by_i = {f["i"]: f for f in q2_doc["facts"]}
    ambiguous = {}
    for item in routing["ambiguous"]:
        for pid in item["partitions"]:
            ambiguous.setdefault(pid, []).append(item["context_id"])
    unroutable = [u["context_id"] for u in routing["unroutable"]]
    cache, scale_status, results = {}, {}, []
    for c in sorted(contracts, key=lambda c: KINDS.index(c["kind"])):
        pid = c["partition_id"]
        if c["learn_status"] != "learned":
            results.append(_result(c, "insufficient_evidence", q2, cause="not_learned_in_q1: " + str(c["learn_cause"])))
            continue
        if c["kind"] == "fund_income_yield":
            results.append(_evaluate_yield(c, q2, yield_q2))
            continue
        if pid in ambiguous or unroutable:
            keys = ambiguous.get(pid, []) + unroutable
            results.append(_result(c, "insufficient_evidence", q2, keys=keys, cause="ambiguous_partition_overlap"
                                   if pid in ambiguous else "rows_not_routable"))
            continue
        members = [by_ctx[k] for k in routing["routed"].get(pid, [])]
        if c["kind"] == "format_grammar":
            results.append(_evaluate_format(c, q2, q2_doc, [rows_by_ctx[k] for k in routing["routed"].get(pid, [])],
                                            grammar))
            continue
        gaps = channel_gaps(q2_doc, ("contexts", field_channel(c["field"])))
        if (pid, c["field"]) not in cache:
            cache[(pid, c["field"])] = observe_field(q2_doc, members, c["field"], facts_by_i)
        obs = cache[(pid, c["field"])]
        if gaps or obs["unobservable_keys"]:
            results.append(_result(c, "insufficient_evidence", q2, cause="q2_channel_incomplete",
                                   observed=dict(channel_gaps=gaps, unobservable=len(obs["unobservable_keys"])),
                                   keys=obs["unobservable_keys"]))
            continue
        if not obs["rows"]:
            results.append(_result(c, "insufficient_evidence", q2, cause="no_q2_positions_in_partition"))
            continue
        verdict = {"source_concept_set": _evaluate_concepts, "fill_rate": _evaluate_fill, "scale": _evaluate_scale,
                   "value_range": _evaluate_range}[c["kind"]](c, q2, obs, scale_status)
        if c["kind"] == "scale":
            scale_status[(pid, c["field"])] = verdict["status"]
        results.append(verdict)
    order = {c["contract_id"]: i for i, c in enumerate(contracts)}
    return sorted(results, key=lambda r: order[r["contract_id"]])


def _evaluate_concepts(c, q2, obs, _scale) -> dict:
    expected = _req(c["expectation"], "concepts", c["contract_id"])
    got = obs["concepts"]
    if got == expected:
        return _result(c, "holds", q2, expected=expected, observed=dict(concepts=got))
    added = sorted(set(got) - set(expected))
    removed = sorted(set(expected) - set(got))
    keys = {k for concept in added for k in obs["concept_keys"][concept]}
    return _result(c, "breach", q2, expected=expected, observed=dict(concepts=got, added=added, removed=removed),
                   keys=keys, cause="concept_set_changed")


def _evaluate_fill(c, q2, obs, _scale) -> dict:
    exp = _req(c["expectation"], "fill_share", c["contract_id"])
    pp = _req(c["band"], "fill_rate_pp", c["contract_id"])
    observed = dict(fill_share=obs["fill_share"], filled=obs["filled"], rows=obs["rows"],
                    absent=len(obs["absent_keys"]), nil=len(obs["nil_keys"]), conflicts=len(obs["conflicts"]),
                    zero_values=obs["zero_values"], delta_pp=round((obs["fill_share"] - exp) * 100, 4))
    if abs(obs["fill_share"] - exp) * 100 <= pp + 1e-9:
        return _result(c, "holds", q2, expected=dict(fill_share=exp, band_pp=pp), observed=observed)
    keys = obs["filled_keys"] if obs["fill_share"] > exp else (obs["absent_keys"] + obs["nil_keys"]
                                                                + [x["context_id"] for x in obs["conflicts"]])
    return _result(c, "breach", q2, expected=dict(fill_share=exp, band_pp=pp), observed=observed, keys=keys,
                   cause="fill_rate_outside_band")


def _evaluate_scale(c, q2, obs, _scale) -> dict:
    exp = c["expectation"]
    expected_class = _req(exp, "scale_class", c["contract_id"])
    regime = _req(exp, "magnitude_regime", c["contract_id"])
    observed = _scale_evidence(obs)
    if not obs["filled"]:
        return _result(c, "insufficient_evidence", q2, cause="no_q2_values_to_assess", expected=exp,
                       observed=observed)
    other = {k: v for k, v in obs["class_keys"].items() if k != expected_class}
    unit_conflicts = [x["context_id"] for x in obs["conflicts"] if x["reason"] == "unit_differs"]
    if other:
        return _result(c, "breach", q2, cause="declared_unit_class_changed", expected=exp, observed=observed,
                       keys={k for v in other.values() for k in v})
    if unit_conflicts:
        return _result(c, "insufficient_evidence", q2, cause="conflicting_units_on_one_field", expected=exp,
                       observed=observed, keys=unit_conflicts)
    if obs["regime"] == "mixed":
        return _result(c, "insufficient_evidence", q2, cause="magnitude_mixed_under_one_declared_unit",
                       expected=exp, observed=observed, keys=[k for k, _, _ in obs["values"]])
    if obs["regime"] != regime and "zero_only" not in (obs["regime"], regime):
        return _result(c, "insufficient_evidence", q2, cause="magnitude_regime_changed_under_same_declared_unit",
                       expected=exp, observed=observed, keys=[k for k, _, _ in obs["values"]])
    return _result(c, "holds", q2, expected=exp, observed=observed)


def _evaluate_range(c, q2, obs, scale_status) -> dict:
    exp = c["expectation"]
    lo, hi = _req(exp, "widened", c["contract_id"])
    q_lo, q_hi = _req(c["band"], "value_range_quantiles", c["contract_id"])
    status = scale_status.get((c["partition_id"], c["field"]))
    if status != "holds":
        return _result(c, "insufficient_evidence", q2, cause="scale_contract_not_holds",
                       observed=dict(scale_status=status), expected=exp)
    values = canonical(obs["values"], _req(exp, "scale_class", c["contract_id"]))
    if not values:
        return _result(c, "insufficient_evidence", q2, cause="no_q2_values_to_assess", expected=exp)
    ordered = sorted(v for _, v in values)
    p_lo, p_hi = round(quantile(ordered, q_lo), 10), round(quantile(ordered, q_hi), 10)
    observed = dict(p5=p_lo, p95=p_hi, min=ordered[0], max=ordered[-1], n_values=len(ordered))
    outside = [k for k, v in values if v < lo or v > hi]
    if lo <= p_lo and p_hi <= hi:
        return _result(c, "holds", q2, expected=exp, observed=dict(observed, rows_outside=len(outside)))
    return _result(c, "breach", q2, cause="quantiles_outside_widened_q1_range", expected=exp, observed=observed,
                   keys=outside)


def _evaluate_format(c, q2, q2_doc, rows, grammar) -> dict:
    exp = c["expectation"]
    minimum = _req(c["band"], "format_grammar_min_parse_share", c["contract_id"])
    if not grammar or grammar["sha256"] != _req(exp, "grammar_sha256", c["contract_id"]):
        raise ContractError("format contract evaluated without its pinned grammar: " + c["contract_id"])
    gaps = channel_gaps(q2_doc, ("contexts", "identifiers"))
    if gaps:
        return _result(c, "insufficient_evidence", q2, cause="q2_channel_incomplete", expected=exp,
                       observed=dict(channel_gaps=gaps))
    obs = grammar_observation(rows, grammar)
    if not obs["scope_rows"]:
        keys = [r["context_id"] for r in rows if r.get("investment_identifier")]
        return _result(c, "breach", q2, cause="dialect_scope_empty_in_q2", expected=exp, observed=obs, keys=keys)
    if obs["parse_share"] >= minimum:
        return _result(c, "holds", q2, expected=exp, observed=obs)
    return _result(c, "breach", q2, cause="identifiers_do_not_parse_under_dialect", expected=exp, observed=obs,
                   keys=[v["context_id"] for v in obs["violating"]])


def _evaluate_yield(c, q2, yield_q2) -> dict:
    exp = c["expectation"]
    expected = _req(exp, "vote", c["contract_id"])
    ev = yield_q2 or dict(status="insufficient_evidence", cause="q2_yield_evidence_missing")
    observed = dict(q2_yield=ev)
    if ev.get("status") != "vote":
        return _result(c, "insufficient_evidence", q2, cause=str(ev.get("cause")), expected=exp, observed=observed)
    if ev.get("vote") == expected:
        return _result(c, "holds", q2, expected=exp, observed=observed)
    keys = ["income:" + str(ev.get("cik")) + ":" + str(ev.get("report_date"))]
    return _result(c, "breach", q2, cause="s2_convention_vote_changed", expected=exp, observed=observed, keys=keys)


# ---------------------------------------------------------------- M2

def _counts(results) -> dict:
    out = {s: 0 for s in STATUSES}
    for r in results:
        out[r["status"]] += 1
    return out


def summarise_m2(results: list, *, denominator: int) -> dict:
    if len(results) != denominator:
        raise ContractError("M2 results (%d) differ from the frozen denominator (%d)" % (len(results), denominator))
    by = lambda key: {k: _counts([r for r in results if key(r) == k]) for k in sorted({key(r) for r in results})}
    causes: dict = {}
    for r in results:
        if r["status"] == "insufficient_evidence":
            causes[r["cause"]] = causes.get(r["cause"], 0) + 1
    counts = _counts(results)
    return dict(denominator=denominator, counts=counts,
                holds_share=round(counts["holds"] / denominator, 6) if denominator else None,
                by_cik=by(lambda r: r["cik"]), by_kind=by(lambda r: r["kind"]),
                by_q2_form_type=by(lambda r: r["q2"]["form_type"] or "unavailable"),
                by_cik_and_kind=by(lambda r: r["cik"] + ":" + r["kind"]),
                by_q2_form_type_and_kind=by(lambda r: (r["q2"]["form_type"] or "unavailable") + ":" + r["kind"]),
                insufficient_causes=dict(sorted(causes.items())),
                breaches=[dict(contract_id=r["contract_id"], cause=r["cause"], expected=r["expected"],
                               observed=_brief(r["observed"]), violating_keys=r["violating_keys"],
                               q2_form_type=r["q2"]["form_type"]) for r in results if r["status"] == "breach"],
                holds_with_form_type_reason=HOLDS_WITH_FORM_TYPE_REASON, deferred_unchecked=DEFERRED,
                stage_b_note=STAGE_B_NOTE, claim=CLAIM)


def _brief(observed):
    if not isinstance(observed, dict):
        return observed
    return {k: v for k, v in observed.items() if k not in ("violating", "q2_yield")}
