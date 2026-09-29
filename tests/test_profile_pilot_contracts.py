"""Task 8: partitioned Q1 contracts, frozen tolerances, Q2 evaluation (M2) and the S2 yield adapter.

Census documents here are minimal hand-built dicts holding only what the contract code
reads (document, channels, positions, facts, units, partition outcomes, fund income).
The S2 tests call the REAL pipeline.rate_convention._aggregate_signals on synthetic
frames with cwd = tmp_path. The one `needs_cache` test reads a real Q1/Q2 census pair of
the authoritative Stage B census root through PROFILE_PILOT_DATA_ROOT (read-only).
"""
from __future__ import annotations

from contextlib import contextmanager
import copy
import json
import os
from pathlib import Path
import re

import pandas as pd
import pytest

from scripts.profile_pilot import contracts, contracts_income, envelope, manifest
from scripts.profile_pilot.census import POSITION_FIELDS
from tests.test_profile_pilot_paths import fake_paths

CIK = "0001860424"
Q1, Q2 = "2023-06-30", "2023-09-30"
RECORDED = "2026-09-29T00:00:00Z"
CONCEPT = {
    "fair_value": "us-gaap:InvestmentOwnedAtFairValue", "cost": "us-gaap:InvestmentOwnedAtCost",
    "principal_amount": "us-gaap:InvestmentOwnedBalancePrincipalAmount",
    "interest_rate": "us-gaap:InvestmentInterestRate", "pik_rate": "us-gaap:InvestmentInterestRatePaidInKind",
    "basis_spread": "us-gaap:InvestmentBasisSpreadVariableRate",
    "interest_rate_floor": "us-gaap:InvestmentInterestRateFloor",
    "pct_of_net_assets": "us-gaap:InvestmentOwnedPercentOfNetAssets",
    "maturity_date": "us-gaap:InvestmentMaturityDate",
    "industry": "us-gaap-supplement:InvestmentIndustrySectorExtensibleEnumeration",
}
UNITS = {
    "usd": dict(measures=["iso4217:USD"], unit_kind="monetary", currency="USD"),
    "pure": dict(measures=["pure"], unit_kind="pure", currency=None),
    "pct": dict(measures=["abc:Percent"], unit_kind="unresolved", currency=None),
    "bps": dict(measures=["abc:bps"], unit_kind="unresolved", currency=None),
}
SINGLE = dict(detector="partition", outcome="resolved", finding="single_dialect",
              subject=dict(field="investment_identifier", signature=dict(kind="none")), evidence={},
              provenance="derived", inherited_from=None, depends_on_channels=["contexts"])
MIXED = dict(detector="partition", outcome="insufficient_evidence", finding="no_structural_discriminator",
             subject=dict(field="investment_identifier", signature=dict(kind="delimiters", delimiters=["|", ","])),
             evidence={}, provenance="derived", inherited_from=None, depends_on_channels=["contexts"])
DEBT = dict(kind="axis_member", axis="abc:TypeAxis", member="abc:DebtMember")
EQUITY = dict(kind="axis_member", axis="abc:TypeAxis", member="abc:EquityMember")


def evidenced(*predicates):
    return dict(SINGLE, finding="evidenced_partition", evidence=dict(predicates=list(predicates)),
                subject=dict(field="investment_identifier", signature=dict(kind="delimiters", delimiters=["|", ";"])))


def val(value, unit="pure", concept=None, decimals="4", kind="numeric"):
    return dict(value=value, unit=unit, concept=concept, decimals=decimals, kind=kind)


def mk_doc(rows, *, date=Q1, form="10-Q", partition=(SINGLE,), channels=None, fund_income=()):
    facts, positions = [], []
    for spec in rows:
        fields = {}
        for field in POSITION_FIELDS:
            item = spec["fields"].get(field)
            if item is None:
                fields[field] = dict(status="absent", provenance="derived", inherited_from=None)
            elif item == "UNOBS":
                fields[field] = dict(status="unobservable", reason="numeric_facts truncated",
                                     provenance="derived", inherited_from=None)
            elif item == "NIL":
                fields[field] = dict(status="nil", value=None, provenance="derived", inherited_from=None)
            else:
                unit = UNITS.get(item["unit"]) if item["unit"] else None
                concept = item["concept"] or CONCEPT.get(field, "abc:" + field)
                i = len(facts)
                facts.append(dict(i=i, qname=concept, value_kind=item["kind"], unit_ref=item["unit"],
                                  decimals=item["decimals"], value=item["value"], raw=item["value"], field=field,
                                  unit_kind=unit["unit_kind"] if unit else None,
                                  currency=unit["currency"] if unit else None, status="reported"))
                fields[field] = dict(status="reported", value=item["value"], raw=[item["value"]], concepts=[concept],
                                     fact_indices=[i], unit_kind=unit["unit_kind"] if unit else None,
                                     currency=unit["currency"] if unit else None, decimals=item["decimals"],
                                     reason=None, provenance="derived", inherited_from=None)
        positions.append(dict(observation_id="obs:" + spec["ctx"], context_id=spec["ctx"],
                              period=dict(kind="instant", instant=date),
                              identity=dict(typed_identifier=spec.get("ident"), typed_dimensions=[],
                                            dimensions=[list(d) for d in spec.get("dims", ())]),
                              dimension_fields={}, fields=fields, provenance="derived", inherited_from=None))
    states = {c: dict(state="complete", reason=None, count=1)
              for c in ("contexts", "units", "numeric_facts", "text_facts", "footnotes", "identifiers")}
    for name, state in (channels or {}).items():
        states[name] = dict(state=state, reason="test", count=0)
    return dict(document=dict(cik=CIK, report_date=date, form_type=form, accession_number="A-" + date),
                document_metadata=dict(document_period_end_dates=[date], document_types=[form]),
                collection=dict(state="complete", errors=[]), channels=states, units=copy.deepcopy(UNITS),
                facts=facts, positions=positions, detectors=dict(partition=dict(outcomes=list(partition))),
                fund_income=list(fund_income))


def debt(i, *, rate="0.10", unit="pure", concept=None, pik=None, dims=(), ident=None, extra=None):
    fields = dict(fair_value=val("1000000", "usd", decimals="0"),
                  principal_amount=val("1000000", "usd", decimals="0"),
                  interest_rate=val(rate, unit, concept))
    if pik is not None:
        fields["pik_rate"] = val(pik)
    fields.update(extra or {})
    return dict(ctx="c%d" % i, ident=ident or ("Acme %d | First Lien | 10.00%% | 1/1/2029" % i),
                dims=dims, fields=fields)


def equity(i, dims=()):
    return dict(ctx="e%d" % i, ident="Holdco %d Common Units" % i, dims=dims,
                fields=dict(fair_value=val("500", "usd", decimals="0")))


def mk_profile(doc, entries_for=None):
    events = []
    positions = contracts.current_positions(doc)
    for field in entries_for or POSITION_FIELDS:
        filled = [p for p in positions if p["fields"][field]["status"] in ("reported", "consistent_duplicate")]
        if not filled:
            continue
        concepts = sorted({c for p in filled for c in p["fields"][field]["concepts"]})
        events = envelope.make_assertion(
            events, cik=CIK, key="column_contract." + field, value=dict(concepts=concepts),
            valid_from=doc["document"]["report_date"], recorded_at=RECORDED,
            support=dict(kind="prevalence", numerator=len(filled), denominator=len(positions)),
            evidence=[dict(kind="field_status", conflicts=0)])
    return dict(entries=envelope.materialize_entries(events), sections=dict(column_contract=dict(status="derived")))


GRAMMAR_BODY = dict(applies_to=dict(signature="RATE"), required_fields=["interest_rate"],
                    extractors=[dict(field="interest_rate", regex=r"\|\s*(\d+(?:\.\d+)?)%\s*\|", group=1,
                                     type="pct")], invariants=[])


def grammar():
    return contracts.grammar_info(GRAMMAR_BODY, path="test/grammar.json", sha256="0" * 64,
                                  anchors=[("RATE", re.compile(r"\d+(?:\.\d+)?%"))])


VOTE_CASH = dict(status="vote", vote="cash_leg", cause=None, report_date=Q1)
Q2_LISTING = dict(status="available", report_date=Q2, census_relative="census/x/" + Q2 + ".json")


def tolerances():
    return contracts.tolerance_content()


def learn(q1_doc, *, profile=None, gram=None, yield_q1=VOTE_CASH, tol=None):
    return contracts.learn_contracts(cik=CIK, q1_doc=q1_doc, q1_profile=profile or mk_profile(q1_doc),
                                     grammar=gram, yield_q1=yield_q1, tolerances=tol or tolerances(),
                                     q2_listing=Q2_LISTING, recorded_at=RECORDED)


def evaluate(block, q2_doc, *, gram=None, yield_q2=None, tol=None, listing=Q2_LISTING):
    return contracts.evaluate_contracts(block, tol or tolerances(), q2_doc=q2_doc, q2_listing=listing,
                                        grammar=gram, yield_q2=yield_q2 or dict(VOTE_CASH, report_date=Q2))


def pick(results, kind, field, partition="whole_filing"):
    [hit] = [r for r in results if r["kind"] == kind and r["field"] == field and r["partition_id"] == partition]
    return hit


def book(n=60, **kw):
    return [debt(i, **kw) for i in range(n)]


# ---------------------------------------------------------------- frozen tolerance table (spec 6.3)

def test_tolerance_file_carries_the_spec_table_verbatim_and_operational_bands():
    tol = tolerances()
    assert tol["spec_table_verbatim"] == [
        dict(expectation="source concept set", standard="identical set", low_history="identical set"),
        dict(expectation="fill rate", standard="+/- 10 percentage points", low_history="+/- 25 percentage points"),
        dict(expectation="scale", standard="identical", low_history="identical"),
        dict(expectation="value range (rates, spreads)", standard="Q2 p5-p95 inside Q1 min-max widened by 25%",
             low_history="same, widened by 50%"),
        dict(expectation="format grammar", standard="every Q2 identifier parses", low_history=">= 90% parse")]
    assert tol["bands"]["standard"]["fill_rate_pp"] == 10 and tol["bands"]["low_history"]["fill_rate_pp"] == 25
    assert tol["bands"]["standard"]["value_range_widen"] == 0.25
    assert tol["bands"]["low_history"]["value_range_widen"] == 0.5
    assert tol["bands"]["standard"]["format_grammar_min_parse_share"] == 1.0
    assert tol["bands"]["low_history"]["format_grammar_min_parse_share"] == 0.9
    assert tol["low_history_below_positions"] == 50
    assert tol["form_type_qualifiers"]["evidenced"] == []
    assert set(tol["fund_income_yield"]["constants"]) >= {"INCOME_COVERAGE_BAND", "METHOD_VERSION",
                                                          "INCOME_R_ALL_IN", "INCOME_R_CASH", "INCOME_MIN_QUARTERS"}
    json.dumps(tol).encode("ascii")


def test_tolerance_version_2_records_the_evidence_limit_correction_and_interpretation():
    tol = contracts.tolerance_content_v2()
    assert tol["version"] == "contract-tolerances.v2"
    assert tol["supersedes"]["version"] == "contract-tolerances.v1"
    assert tol["supersedes"]["run_id"] == "stageb-contracts-20260929t032414z"
    assert "INCOME_MIN_QUARTERS" in tol["fund_income_yield"]["vote_rule"]
    assert "not a relaxation" in tol["supersedes"]["reason"]
    assert "strict" in tol["identifier_format_interpretation"]
    assert set(tol["scale_conventions"]) == {"pure", "percent", "bps"}


# ---------------------------------------------------------------- denominator and statuses

def test_every_expected_contract_is_in_the_fixed_denominator_with_exactly_one_status():
    q1 = mk_doc(book())
    block = learn(q1, gram=grammar())
    kinds = {}
    for c in block["contracts"]:
        kinds[c["kind"]] = kinds.get(c["kind"], 0) + 1
    assert kinds == dict(source_concept_set=len(POSITION_FIELDS), fill_rate=len(POSITION_FIELDS),
                         scale=len(contracts.SCALE_FIELDS), value_range=len(contracts.RANGE_FIELDS),
                         format_grammar=1, fund_income_yield=1, rate_composition=1, text_agreement=1)
    results = evaluate(block, mk_doc(book(), date=Q2), gram=grammar())
    assert [r["contract_id"] for r in results] == [c["contract_id"] for c in block["contracts"]]
    assert all(r["status"] in contracts.STATUSES for r in results)
    assert all(r["applies_to"] is None and r["partition_id"] == "whole_filing" for r in results)
    assert pick(results, "fill_rate", "interest_rate")["status"] == "holds"
    assert pick(results, "format_grammar", "investment_identifier")["status"] == "holds"
    m2 = contracts.summarise_m2(results, denominator=len(block["contracts"]))
    assert m2["denominator"] == len(results) and sum(m2["counts"].values()) == len(results)
    assert m2["counts"]["holds_with_form_type"] == 0 and m2["holds_with_form_type_reason"]


def test_ares_style_missing_q2_census_keeps_every_contract_as_insufficient():
    block = learn(mk_doc(book()))
    listing = dict(status="unavailable", report_date="2022-12-31", detail="selection_requires_amendment_scan")
    results = evaluate(block, None, listing=listing)
    assert len(results) == len(block["contracts"])
    assert {r["status"] for r in results} == {"insufficient_evidence"}
    assert {r["cause"] for r in results} == {"q2_census_unavailable"}
    assert all(r["q2"]["form_type"] is None for r in results)


# ---------------------------------------------------------------- scale

def test_true_decimal_percent_and_bps_changes_within_one_namespace():
    block = learn(mk_doc(book(rate="0.10")))
    scale = pick(block["contracts"], "scale", "interest_rate")
    assert scale["expectation"]["scale_class"] == "pure" and scale["expectation"]["magnitude_regime"] == "lt1"
    percent = pick(evaluate(block, mk_doc(book(rate="10.0", unit="pct"), date=Q2)), "scale", "interest_rate")
    assert percent["status"] == "breach" and percent["observed"]["classes"] == {"percent": 60}
    assert len(percent["violating_keys"]) == 60
    bps = pick(evaluate(block, mk_doc(book(rate="1000", unit="bps"), date=Q2)), "scale", "interest_rate")
    assert bps["status"] == "breach" and bps["observed"]["classes"] == {"bps": 60}
    # Same declared unit, magnitudes now percent-like: magnitude is not scale evidence -> abstain, never holds.
    silent = pick(evaluate(block, mk_doc(book(rate="10.0"), date=Q2)), "scale", "interest_rate")
    assert silent["status"] == "insufficient_evidence"
    assert silent["cause"] == "magnitude_regime_changed_under_same_declared_unit"
    same = pick(evaluate(block, mk_doc(book(rate="0.11"), date=Q2)), "scale", "interest_rate")
    assert same["status"] == "holds"


def _drop_fact_indices(doc, field="interest_rate", ctxs=None):
    for p in doc["positions"]:
        if ctxs is None or p["context_id"] in ctxs:
            p["fields"][field]["fact_indices"] = []
    return doc


def test_a_filled_field_without_a_fact_index_is_unobservable_scale_not_a_breach():
    # Minor A: inability to observe the unit is insufficient_evidence with a named cause.
    block = learn(mk_doc(book(rate="0.10")))
    q2 = _drop_fact_indices(mk_doc(book(rate="0.10"), date=Q2))
    scale = pick(evaluate(block, q2), "scale", "interest_rate")
    assert (scale["status"], scale["cause"]) == ("insufficient_evidence", "unit_not_observable_no_fact_index")
    assert scale["observed"]["classes"] == {"unit_not_observable": 60} and len(scale["violating_keys"]) == 60
    # An observed unit change on other rows is still a breach, whatever the unobservable rows say.
    mixed = mk_doc(book(30, rate="0.10") + [debt(i, rate="10.0", unit="pct") for i in range(30, 60)], date=Q2)
    mixed = _drop_fact_indices(mixed, ctxs={"c%d" % i for i in range(10)})
    scale = pick(evaluate(block, mixed), "scale", "interest_rate")
    assert (scale["status"], scale["cause"]) == ("breach", "declared_unit_class_changed")
    assert scale["violating_keys"] == sorted("c%d" % i for i in range(30, 60))
    # Learning: a Q1 field without fact indices names the same cause (never "mixed" or "no ratio unit").
    unlearned = learn(_drop_fact_indices(mk_doc(book(rate="0.10"))))
    assert pick(unlearned["contracts"], "scale", "interest_rate")["learn_cause"] == "unit_not_observable_no_fact_index"


def test_namespace_change_with_unchanged_scale_breaks_concept_not_scale():
    block = learn(mk_doc(book()))
    results = evaluate(block, mk_doc(book(concept="abc:CustomInterestRate"), date=Q2))
    assert pick(results, "scale", "interest_rate")["status"] == "holds"
    concept = pick(results, "source_concept_set", "interest_rate")
    assert concept["status"] == "breach"
    assert concept["observed"]["added"] == ["abc:CustomInterestRate"]
    assert concept["observed"]["removed"] == ["us-gaap:InvestmentInterestRate"]
    assert len(concept["violating_keys"]) == 60


def test_removed_concept_breach_lists_the_q2_rows_no_longer_carrying_it():
    block = learn(mk_doc(book(pik="0.01")))
    result = pick(evaluate(block, mk_doc(book(), date=Q2)), "source_concept_set", "pik_rate")
    assert result["status"] == "breach" and result["observed"]["removed"] == ["us-gaap:InvestmentInterestRatePaidInKind"]
    assert len(result["violating_keys"]) == 60
    partial = book(pik="0.01")[:40] + book()[40:]
    moved = [debt(i, pik="0.01") for i in range(40)] + \
            [debt(i, extra=dict(pik_rate=val("0.01", concept="abc:Pik"))) for i in range(40, 60)]
    result = pick(evaluate(learn(mk_doc(partial)), mk_doc(moved, date=Q2)), "source_concept_set", "pik_rate")
    assert result["observed"]["added"] == ["abc:Pik"] and result["observed"]["removed"] == []
    assert len(result["violating_keys"]) == 20


def test_namespace_move_keys_only_rows_carrying_the_added_concept():
    block = learn(mk_doc(book(pik="0.01")))
    moved = [debt(i, extra=dict(pik_rate=val("0.01", concept="abc:Pik"))) for i in range(40)] + book()[40:]
    result = pick(evaluate(block, mk_doc(moved, date=Q2)), "source_concept_set", "pik_rate")
    assert result["observed"]["added"] == ["abc:Pik"]
    assert result["observed"]["removed"] == ["us-gaap:InvestmentInterestRatePaidInKind"]
    assert result["violating_keys"] == sorted("c%d" % i for i in range(40))
    assert result["observed"]["rows_not_carrying_removed"] == 60


def test_pure_removal_never_keys_rows_filled_under_a_still_expected_concept():
    q1 = [debt(i, pik="0.01") for i in range(30)] + \
         [debt(i, extra=dict(pik_rate=val("0.01", concept="abc:Pik"))) for i in range(30, 60)]
    q2 = [debt(i, extra=dict(pik_rate=val("0.01", concept="abc:Pik"))) for i in range(30)] + \
         [debt(i, extra=dict(pik_rate="NIL")) for i in range(30, 45)] + book()[45:]
    result = pick(evaluate(learn(mk_doc(q1)), mk_doc(q2, date=Q2)), "source_concept_set", "pik_rate")
    assert result["observed"]["removed"] == ["us-gaap:InvestmentInterestRatePaidInKind"]
    assert result["observed"]["added"] == []
    assert result["violating_keys"] == sorted("c%d" % i for i in range(30, 60))


def test_mixed_magnitudes_and_text_rates_abstain_on_scale_and_range():
    nexpoint = book(30, rate="0.10") + [debt(100 + i, rate="3.75") for i in range(30)]
    block = learn(mk_doc(nexpoint))
    scale = pick(block["contracts"], "scale", "interest_rate")
    assert scale["learn_status"] == "insufficient_evidence"
    assert scale["learn_cause"] == "magnitude_mixed_under_one_declared_unit"
    assert pick(block["contracts"], "value_range", "interest_rate")["learn_cause"] == "scale_not_established_in_q1"
    onex = [debt(i, extra=dict(interest_rate=val("SOFR + 6.50%", None, kind="text", decimals=None)))
            for i in range(60)]
    block = learn(mk_doc(onex))
    assert pick(block["contracts"], "scale", "interest_rate")["learn_cause"] == "no_declared_ratio_unit"
    results = evaluate(block, mk_doc(onex, date=Q2))
    assert pick(results, "scale", "interest_rate")["status"] == "insufficient_evidence"
    assert pick(results, "scale", "interest_rate")["cause"].startswith("not_learned_in_q1")


# ---------------------------------------------------------------- partitions

def test_two_valid_dialect_partitions_are_learned_and_routed_by_frozen_predicates():
    q1_rows = [debt(i, dims=[("abc:TypeAxis", "abc:DebtMember")]) for i in range(60)] + \
              [equity(i, dims=[("abc:TypeAxis", "abc:EquityMember")]) for i in range(60)]
    q2_rows = [debt(i, dims=[("abc:TypeAxis", "abc:DebtMember")]) for i in range(30)] + \
              [equity(i, dims=[("abc:TypeAxis", "abc:EquityMember")]) for i in range(90)]
    block = learn(mk_doc(q1_rows, partition=(evidenced(DEBT, EQUITY),)))
    ids = sorted(p["partition_id"] for p in block["partitions"] if p["q1_rows"])
    assert len(ids) == 2 and "whole_filing" not in ids
    debt_id = next(p["partition_id"] for p in block["partitions"] if p["applies_to"] == DEBT)
    results = evaluate(block, mk_doc(q2_rows, date=Q2, partition=(SINGLE,)))
    fill = pick(results, "fill_rate", "interest_rate", debt_id)
    assert fill["status"] == "holds" and fill["applies_to"] == DEBT
    # The same filing without the partition reads as a whole-filing fill breach (50% -> 25%).
    flat = learn(mk_doc(q1_rows))
    assert pick(evaluate(flat, mk_doc(q2_rows, date=Q2)), "fill_rate", "interest_rate")["status"] == "breach"


def test_ambiguous_partition_overlap_is_insufficient_never_a_pick():
    both = [("abc:TypeAxis", "abc:DebtMember"), ("abc:TypeAxis", "abc:EquityMember")]
    q1_rows = [debt(i, dims=[("abc:TypeAxis", "abc:DebtMember")]) for i in range(60)] + \
              [equity(i, dims=[("abc:TypeAxis", "abc:EquityMember")]) for i in range(60)]
    block = learn(mk_doc(q1_rows, partition=(evidenced(DEBT, EQUITY),)))
    q2_rows = q1_rows[:-1] + [equity(999, dims=both)]
    results = evaluate(block, mk_doc(q2_rows, date=Q2))
    partitioned = [r for r in results if r["partition_id"] != "whole_filing" and r["kind"] != "fund_income_yield"]
    assert partitioned and {r["status"] for r in partitioned} == {"insufficient_evidence"}
    learned = [r for r in partitioned if not r["cause"].startswith("not_learned_in_q1")]
    assert learned and {r["cause"] for r in learned} == {"ambiguous_partition_overlap"}
    assert all("e999" in r["violating_keys"] for r in learned)
    assert len(results) == len(block["contracts"])


def test_unresolved_mixed_identifier_format_blocks_the_format_contract_only():
    block = learn(mk_doc(book(), partition=(MIXED,)), gram=grammar())
    fmt = pick(block["contracts"], "format_grammar", "investment_identifier")
    assert fmt["learn_status"] == "insufficient_evidence"
    assert fmt["learn_cause"] == "unresolved_mixed_identifier_format"
    assert pick(block["contracts"], "fill_rate", "interest_rate")["learn_status"] == "learned"
    assert "whole-filing" in block["partition_statement"]


def test_m2_is_reported_as_evaluated_and_under_the_strict_6_3_reading():
    mixed = learn(mk_doc(book(), partition=(MIXED,)))
    clean = learn(mk_doc(book()))
    results = evaluate(mixed, mk_doc(book(), date=Q2)) + evaluate(clean, mk_doc(book(), date=Q2))
    flagged = [r for r in results if r["identifier_format_unresolved"]]
    assert len(flagged) == len(mixed["contracts"])
    assert not any(r["identifier_format_unresolved"] for r in results[len(mixed["contracts"]):])
    m2 = contracts.summarise_m2(results, denominator=len(results))
    strict = m2["strict_6_3"]
    assert strict["denominator"] == m2["denominator"]
    moved = sum(1 for r in flagged if r["kind"] != "fund_income_yield" and r["status"] != "insufficient_evidence")
    assert strict["counts"]["insufficient_evidence"] == m2["counts"]["insufficient_evidence"] + moved
    assert strict["insufficient_causes"]["identifier_format_unresolved"] == moved
    assert strict["counts"]["holds"] < m2["counts"]["holds"]
    assert set(strict["by_q2_form_type"]) == set(m2["by_q2_form_type"])
    assert "strict" in strict["interpretation"]


# ---------------------------------------------------------------- two dialect partitions (format)

PIPE_BODY = dict(applies_to=dict(signature="PIPE"), required_fields=["interest_rate"],
                 extractors=[dict(field="interest_rate", regex=r"\|\s*(\d+(?:\.\d+)?)%\s*\|", group=1, type="pct")])
COMMA_BODY = dict(applies_to=dict(signature="COMMA"), required_fields=["interest_rate"],
                  extractors=[dict(field="interest_rate", regex=r",\s*(\d+(?:\.\d+)?)%\s*,", group=1, type="pct")])


def dialects():
    return [contracts.grammar_info(PIPE_BODY, path="g/pipe.json", sha256="1" * 64,
                                   anchors=[("PIPE", re.compile(r"\|\s*\d+(?:\.\d+)?%"))]),
            contracts.grammar_info(COMMA_BODY, path="g/comma.json", sha256="2" * 64,
                                   anchors=[("COMMA", re.compile(r",\s*\d+(?:\.\d+)?%"))])]


def comma(i):
    return debt(1000 + i, ident="Beta %d, First Lien, 10.00%%, 1/1/2029" % i)


def test_two_dialect_partitions_hold_their_own_format_contracts_where_whole_filing_breaches():
    pipe_pred = dict(kind="grammar_dialect", dialect="PIPE")
    comma_pred = dict(kind="grammar_dialect", dialect="COMMA")
    rows = book(30) + [comma(i) for i in range(30)]
    routed = contracts.routing_rows(mk_doc(rows), contracts.current_positions(mk_doc(rows)), dialects())
    assert envelope.predicate_matches(pipe_pred, routed[0]) and not envelope.predicate_matches(comma_pred, routed[0])
    assert envelope.predicate_matches(comma_pred, routed[-1])
    block = learn(mk_doc(rows, partition=(evidenced(pipe_pred, comma_pred),)), gram=dialects())
    q2 = mk_doc(book(25) + [comma(i) for i in range(35)], date=Q2)
    results = evaluate(block, q2, gram=dialects())
    formats = [r for r in results if r["kind"] == "format_grammar"]
    assert sorted(r["expected"]["dialect"] for r in formats) == ["COMMA", "PIPE"]
    assert {r["status"] for r in formats} == {"holds"}
    assert {tuple(sorted(r["applies_to"].items())) for r in formats} == {
        tuple(sorted(pipe_pred.items())), tuple(sorted(comma_pred.items()))}
    # Whole filing under one dialect: the same regular filing reads as a 50% grammar failure...
    both = [contracts.grammar_info(PIPE_BODY, path="g/pipe.json", sha256="1" * 64,
                                   anchors=[("PIPE", re.compile(r"\d+(?:\.\d+)?%"))])]
    flat = learn(mk_doc(rows), gram=both)
    fmt = pick(flat["contracts"], "format_grammar", "investment_identifier")
    assert fmt["learn_cause"] == "grammar_does_not_hold_on_q1" and fmt["evidence"]["parse_share"] == 0.5
    # ...and a whole-filing contract frozen on a one-dialect Q1 breaches on the two-dialect Q2.
    single = learn(mk_doc(book(60)), gram=both)
    breach = pick(evaluate(single, q2, gram=both), "format_grammar", "investment_identifier")
    assert breach["status"] == "breach" and len(breach["violating_keys"]) == 35


# ---------------------------------------------------------------- format grammar

def test_format_grammar_names_field_and_dialect_and_keeps_violating_keys():
    block = learn(mk_doc(book()), gram=grammar())
    fmt = pick(block["contracts"], "format_grammar", "investment_identifier")
    assert fmt["expectation"]["dialect"] == "RATE" and fmt["expectation"]["field"] == "investment_identifier"
    assert fmt["evidence"]["provenance"] == "inherited"
    q2 = book() + [debt(200, ident="Beta 200 | First Lien | 9.5% cash|1/1/2030")]
    result = pick(evaluate(block, mk_doc(q2, date=Q2), gram=grammar()), "format_grammar", "investment_identifier")
    assert result["status"] == "breach"
    assert result["violating_keys"] == ["c200"]
    assert result["observed"]["violating"][0]["missing_fields"] == ["interest_rate"]
    none = learn(mk_doc(book()), gram=None)
    assert pick(none["contracts"], "format_grammar", "investment_identifier")["learn_cause"] == "no_authored_grammar"


# ---------------------------------------------------------------- low history

def test_low_history_bands_apply_below_fifty_q1_positions():
    q1 = book(26) + [equity(i) for i in range(14)]          # 40 positions, 65% rated
    block = learn(mk_doc(q1), gram=grammar())
    assert block["tier"] == "low_history"
    fill = pick(block["contracts"], "fill_rate", "interest_rate")
    assert fill["band"] == dict(fill_rate_pp=25)
    q2 = book(18) + [equity(i) for i in range(22)]          # 45% rated: -20 pp
    results = evaluate(block, mk_doc(q2, date=Q2), gram=grammar())
    assert pick(results, "fill_rate", "interest_rate")["status"] == "holds"
    standard = learn(mk_doc(book(52) + [equity(i) for i in range(28)]))
    q2s = book(36) + [equity(i) for i in range(44)]         # 65% -> 45%
    assert pick(evaluate(standard, mk_doc(q2s, date=Q2)), "fill_rate", "interest_rate")["status"] == "breach"
    # Range widened 50%: Q1 rates 0.08..0.12 (8..12%), band [6, 14]; Q2 at 13.5% holds low_history.
    rates = [debt(i, rate=r) for i, r in enumerate(["0.08", "0.12"] * 13)]
    block = learn(mk_doc(rates))
    rng = pick(block["contracts"], "value_range", "interest_rate")
    assert rng["expectation"]["widened"] == [6.0, 14.0]
    q2r = [debt(i, rate="0.135") for i in range(26)]
    assert pick(evaluate(block, mk_doc(q2r, date=Q2)), "value_range", "interest_rate")["status"] == "holds"


def test_value_range_breach_lists_rows_outside_the_widened_band():
    rates = [debt(i, rate=r) for i, r in enumerate(["0.08", "0.12"] * 30)]
    block = learn(mk_doc(rates))
    assert pick(block["contracts"], "value_range", "interest_rate")["expectation"]["widened"] == [7.0, 13.0]
    q2 = [debt(i, rate="0.20") for i in range(60)]
    result = pick(evaluate(block, mk_doc(q2, date=Q2)), "value_range", "interest_rate")
    assert result["status"] == "breach" and len(result["violating_keys"]) == 60
    assert result["observed"]["p95"] == 20.0


# ---------------------------------------------------------------- form type (R29)

def test_form_change_grants_no_relief_and_results_split_by_q2_form():
    block = learn(mk_doc(book(), form="10-Q"))
    q2 = book(20) + [equity(i) for i in range(40)]
    as_10q = evaluate(block, mk_doc(q2, date=Q2, form="10-Q"))
    as_10k = evaluate(block, mk_doc(q2, date=Q2, form="10-K"))
    assert [r["status"] for r in as_10q] == [r["status"] for r in as_10k]
    assert pick(as_10k, "fill_rate", "interest_rate")["status"] == "breach"
    assert all(r["status"] != "holds_with_form_type" for r in as_10k)
    m2 = contracts.summarise_m2(as_10k, denominator=len(block["contracts"]))
    assert set(m2["by_q2_form_type"]) == {"10-K"}
    assert m2["by_q2_form_type"]["10-K"]["breach"] == m2["counts"]["breach"]


# ---------------------------------------------------------------- completeness, absent vs zero

def test_source_incompleteness_is_insufficient_not_a_breach():
    block = learn(mk_doc(book()))
    q2 = mk_doc(book(), date=Q2, channels=dict(numeric_facts="truncated"))
    results = evaluate(block, q2)
    for kind in ("fill_rate", "source_concept_set", "scale", "value_range"):
        result = pick(results, kind, "interest_rate")
        assert result["status"] == "insufficient_evidence" and result["cause"] == "q2_channel_incomplete"
    assert pick(results, "fill_rate", "industry")["status"] == "holds"
    unobs = [debt(i, extra=dict(interest_rate="UNOBS")) for i in range(60)]
    assert pick(evaluate(block, mk_doc(unobs, date=Q2)), "fill_rate", "interest_rate")["cause"] == \
        "q2_channel_incomplete"


def test_absent_versus_zero_fields():
    zeros = learn(mk_doc(book(pik="0")))
    pik_fill = pick(zeros["contracts"], "fill_rate", "pik_rate")
    assert pik_fill["expectation"]["fill_share"] == 1.0          # a reported zero is filled
    absent_q2 = pick(evaluate(zeros, mk_doc(book(), date=Q2)), "fill_rate", "pik_rate")
    assert absent_q2["status"] == "breach"                        # observed missing in a complete source
    assert absent_q2["observed"]["absent"] == 60 and len(absent_q2["violating_keys"]) == 60
    none = learn(mk_doc(book()))
    assert pick(none["contracts"], "source_concept_set", "pik_rate")["expectation"]["concepts"] == []
    results = evaluate(none, mk_doc(book(), date=Q2))
    assert pick(results, "fill_rate", "pik_rate")["status"] == "holds"
    assert pick(results, "source_concept_set", "pik_rate")["status"] == "holds"
    appeared = pick(evaluate(none, mk_doc(book(pik="0"), date=Q2)), "fill_rate", "pik_rate")
    assert appeared["status"] == "breach"


# ---------------------------------------------------------------- frozen-file authority

def test_evaluation_reads_only_the_frozen_files_and_fails_closed(tmp_path, monkeypatch):
    paths = fake_paths(tmp_path, run_id="stageb-contracts-test")
    state = contracts.freeze_tolerances(paths)
    frozen_tol = manifest.load_inventory(paths, "contract_tolerances")
    assert state["state"] == "frozen" and frozen_tol == tolerances()
    block = learn(mk_doc(book()), tol=frozen_tol)
    contracts.freeze_contracts(paths, {CIK: block}, tolerances_state=state)
    inventory = manifest.load_inventory(paths, "contract_inventory")
    assert inventory["denominator"]["total"] == len(block["contracts"])
    q2 = mk_doc(book(20) + [equity(i) for i in range(40)], date=Q2)
    before = evaluate(inventory["ciks"][CIK], q2, tol=frozen_tol)
    monkeypatch.setitem(contracts.SPEC_BANDS["standard"], "fill_rate_pp", 90)
    monkeypatch.setattr(contracts, "LOW_HISTORY_BELOW", 1000)
    monkeypatch.setattr(contracts, "learn_contracts", lambda **kw: pytest.fail("evaluation re-learned"))
    after = evaluate(inventory["ciks"][CIK], q2, tol=frozen_tol)
    assert after == before and pick(after, "fill_rate", "interest_rate")["status"] == "breach"
    broken = copy.deepcopy(frozen_tol)
    del broken["bands"]["standard"]["fill_rate_pp"]
    with pytest.raises(contracts.ContractError):
        evaluate(inventory["ciks"][CIK], q2, tol=broken)
    # The conversion used for Q2 ranges is the frozen one, not the code's dict.
    from scripts.profile_pilot import contracts_observe
    ranged = evaluate(inventory["ciks"][CIK], q2, tol=frozen_tol)
    assert pick(ranged, "value_range", "interest_rate")["status"] == "holds"
    monkeypatch.setitem(contracts_observe.SCALE_CONVENTIONS, "pure", dict(canonical_unit="percent", factor="1"))
    assert evaluate(inventory["ciks"][CIK], q2, tol=frozen_tol) == ranged
    no_conventions = copy.deepcopy(frozen_tol)
    del no_conventions["scale_conventions"]
    with pytest.raises(contracts.ContractError):
        evaluate(inventory["ciks"][CIK], q2, tol=no_conventions)
    no_factor = copy.deepcopy(frozen_tol)
    del no_factor["scale_conventions"]["pure"]["factor"]
    with pytest.raises(contracts.ContractError):
        evaluate(inventory["ciks"][CIK], q2, tol=no_factor)
    no_expectation = copy.deepcopy(inventory["ciks"][CIK])
    del no_expectation["contracts"][0]["expectation"]
    with pytest.raises(contracts.ContractError):
        evaluate(no_expectation, q2, tol=frozen_tol)
    with pytest.raises(Exception):
        contracts.freeze_tolerances(paths)                        # write-once


def test_changed_s2_constants_after_freeze_fail_closed(monkeypatch):
    block = learn(mk_doc(book()))
    frozen = tolerances()
    from pipeline import rate_convention
    monkeypatch.setattr(rate_convention, "INCOME_COVERAGE_BAND", (0.1, 9.0))
    with pytest.raises(contracts.ContractError):
        evaluate(block, mk_doc(book(), date=Q2), tol=frozen)


# ---------------------------------------------------------------- fund-income yield (S2 adapter)

@contextmanager
def chdir(path: Path):
    previous = os.getcwd()
    os.chdir(path)
    try:
        yield path
    finally:
        os.chdir(previous)


def holdings(rows, *, q=Q1, acc="A1"):
    out = []
    for i, (ir, pik, prin) in enumerate(rows):
        out.append(dict(source="bdc", cik=CIK, report_date=q, interest_rate=ir, pik_rate=pik,
                        principal_amount=prin, basis_spread="", bdc_investment_identifier="Acme %d Term Loan" % i,
                        src_transforms="interest_rate:rate_x100;pik_rate:rate_x100", src_context_id="c%d" % i,
                        accession_number=acc, fair_value=prin))
    return pd.DataFrame(out)


def income(ii, *, q=Q1, months="3", tii="", acc="A1"):
    return pd.DataFrame([dict(cik=CIK, report_date=q, form_type="10-Q", accession_number=acc, start_date="2023-04-01",
                              end_date=q, duration_months=months, total_investment_income=tii,
                              interest_income=ii)])


def census_for(n, *, q=Q1, concept="us-gaap:InvestmentInterestRatePaidInCash"):
    rows = [debt(i, concept=concept) for i in range(n)]
    fund = [dict(fact_index=0, field="income_interest", qname="us-gaap:InterestIncomeOperating", context_id="d",
                 period=dict(kind="duration", start="2023-04-01", end=q), scope="fund", status="reported",
                 value="1", currency="USD", decimals="0", provenance="derived", inherited_from=None)]
    return mk_doc(rows, date=q, fund_income=fund)


def yield_evidence(h, inc, doc, tmp_path, **kw):
    with chdir(tmp_path):
        return contracts_income.income_evidence(h, inc, cik=CIK, report_date=Q1, census_doc=doc,
                                                cwd=lambda: chdir(tmp_path), **kw)


Q0 = "2023-03-31"


def two_quarters(rows, ii, *, concept="us-gaap:InvestmentInterestRatePaidInCash"):
    h = pd.concat([holdings(rows, q=Q0, acc="A0"), holdings(rows, q=Q1, acc="A1")], ignore_index=True)
    inc = pd.concat([income(ii, q=Q0, acc="A0"), income(ii, q=Q1, acc="A1")], ignore_index=True)
    docs = {Q0: census_for(len(rows), q=Q0, concept=concept), Q1: census_for(len(rows), q=Q1, concept=concept)}
    return h, inc, docs


def test_one_quarter_cannot_vote_two_can_and_pik_is_never_added_twice(tmp_path):
    cash_rows = [("10.0", "2.0", "1000000")] * 5 + [("10.0", "", "1000000")] * 5
    cash = holdings(cash_rows)
    ev = yield_evidence(cash, income("275000.0"), census_for(10), tmp_path)
    assert ev["status"] == "insufficient_evidence" and ev["vote"] is None
    assert ev["cause"] == "s2_evidence_limit_below_min_quarters"
    assert ev["s2"]["src"] == "tagged" and abs(ev["s2"]["r"] - 1.0) < 1e-9 and ev["s2"]["votes_cash"] == 1
    assert ev["s2"]["min_quarters"] == 2
    assert ev["preconditions"]["rate_units"]["ok"] and ev["preconditions"]["duration"]["ok"]
    h, inc, docs = two_quarters(cash_rows, "275000.0")
    with chdir(tmp_path):
        ev = contracts_income.income_evidence(h, inc, cik=CIK, report_date=Q1, census_doc=docs[Q1],
                                              window=[Q0, Q1], window_docs=docs, cwd=lambda: chdir(tmp_path))
    assert ev["status"] == "vote" and ev["vote"] == "cash_leg" and ev["s2"]["votes_cash"] == 2
    assert sorted(ev["window_preconditions"]) == [Q0, Q1]
    allin_rows = [("12.0", "2.0", "1000000")] * 5 + [("10.0", "", "1000000")] * 5
    h, inc, docs = two_quarters(allin_rows, "275000.0", concept="us-gaap:InvestmentInterestRate")
    with chdir(tmp_path):
        ev = contracts_income.income_evidence(h, inc, cik=CIK, report_date=Q1, census_doc=docs[Q1],
                                              window=[Q0, Q1], window_docs=docs, cwd=lambda: chdir(tmp_path))
    assert ev["status"] == "vote" and ev["vote"] == "all_in" and abs(ev["s2"]["r"]) < 1e-9
    # The frozen minimum governs: a frozen value of 3 blocks the two-quarter vote.
    with chdir(tmp_path):
        ev = contracts_income.income_evidence(h, inc, cik=CIK, report_date=Q1, census_doc=docs[Q1],
                                              window=[Q0, Q1], window_docs=docs, min_quarters=3,
                                              cwd=lambda: chdir(tmp_path))
    assert ev["cause"] == "s2_evidence_limit_below_min_quarters"
    seen = []
    from pipeline.rate_convention import _aggregate_signals

    def spy(h, inc):
        seen.append(h.copy())
        return _aggregate_signals(h, inc)

    yield_evidence(cash, income("275000.0"), census_for(10), tmp_path, aggregate=spy)
    assert list(seen[0]["interest_rate"]) == list(cash["interest_rate"])      # PIK never pre-added
    assert list(seen[0].columns) == list(contracts_income.S2_COLUMNS)


def test_duration_mismatch_is_insufficient(tmp_path):
    cash = holdings([("10.0", "2.0", "1000000")] * 5 + [("10.0", "", "1000000")] * 5)
    ev = yield_evidence(cash, income("1100000.0", months="12"), census_for(10), tmp_path)
    assert ev["status"] == "insufficient_evidence"
    assert ev["cause"] == "duration_mismatch_no_quarterly_income"
    assert ev["preconditions"]["duration"]["durations_months"] == ["12"]


def test_insufficient_rated_book_coverage_is_insufficient(tmp_path):
    sparse = holdings([("10.0", "2.0", "1000000")] + [("", "", "1000000")] * 9)
    ev = yield_evidence(sparse, income("275000.0"), census_for(10), tmp_path)
    assert ev["status"] == "insufficient_evidence"
    assert ev["cause"] == "coverage_outside_income_coverage_band"
    assert ev["s2"]["coverage_ratio"] < 0.4


def test_unknown_convention_units_and_scope_are_insufficient(tmp_path):
    middle = holdings([("10.0", "2.0", "1000000")] * 5 + [("10.0", "", "1000000")] * 5)
    ev = yield_evidence(middle, income("262500.0"), census_for(10), tmp_path)      # r = 0.5
    assert ev["cause"] == "unknown_convention_r_between_thresholds" and ev["vote"] is None
    unproven = middle.copy()
    unproven.loc[0, "src_transforms"] = ""
    assert yield_evidence(unproven, income("275000.0"), census_for(10), tmp_path)["cause"] == \
        "rate_units_not_proven"
    other = yield_evidence(middle, income("275000.0", acc="B9"), census_for(10), tmp_path)
    assert other["cause"] == "scope_accession_mismatch"
    estimated = yield_evidence(middle, income("", tii="300000.0"), census_for(10), tmp_path)
    assert estimated["s2"]["src"] == "est"


def test_bdc_holdings_shaped_frame_is_not_s2_input(tmp_path):
    raw = pd.DataFrame([dict(cik=CIK, report_date=Q1, interest_rate="0.10", pik_rate="0.02",
                             principal_amount="1000000", investment_identifier="Acme")])
    ev = yield_evidence(raw, income("275000.0"), census_for(1), tmp_path)
    assert ev["status"] == "insufficient_evidence" and ev["cause"] == "holdings_frame_not_s2_shaped"


def test_yield_contract_votes_become_holds_breach_or_insufficient():
    block = learn(mk_doc(book()))
    yc = pick(block["contracts"], "fund_income_yield", "interest_rate")
    assert yc["expectation"]["vote"] == "cash_leg"
    q2 = mk_doc(book(), date=Q2)
    assert pick(evaluate(block, q2), "fund_income_yield", "interest_rate")["status"] == "holds"
    flipped = dict(VOTE_CASH, vote="all_in", report_date=Q2)
    assert pick(evaluate(block, q2, yield_q2=flipped), "fund_income_yield", "interest_rate")["status"] == "breach"
    none = dict(status="insufficient_evidence", vote=None, cause="duration_mismatch_no_quarterly_income",
                report_date=Q2)
    result = pick(evaluate(block, q2, yield_q2=none), "fund_income_yield", "interest_rate")
    assert result["status"] == "insufficient_evidence" and result["cause"] == "duration_mismatch_no_quarterly_income"
    unlearned = learn(mk_doc(book()), yield_q1=dict(none, report_date=Q1))
    result = pick(evaluate(unlearned, q2), "fund_income_yield", "interest_rate")
    assert result["cause"] == "not_learned_in_q1: duration_mismatch_no_quarterly_income"


def test_runner_helpers_are_light_and_name_the_missing_q2():
    from scripts.profile_pilot import contracts_run
    census = dict(selected={}, unavailable={(CIK, "q2"): dict(report_date="2022-12-31", reason="unavailable",
                                                             detail="selection_requires_amendment_scan")})
    listing = contracts_run._q2_listing(census, CIK)
    assert listing["status"] == "unavailable" and listing["detail"] == "selection_requires_amendment_scan"
    assert manifest.classify_workload(contracts_run._workload("0001803498", 55_000_000)) is False
    assert contracts_run.default_run_id().startswith("stageb-contracts-")
    brief = contracts_run._yield_brief(dict(report_date=Q1, status="insufficient_evidence", vote=None,
                                            cause="no_fund_income_row", preconditions=dict(rows=dict(ok=True))))
    assert brief["preconditions"] == {"rows": True} and brief["r"] is None
    assert "scripts/profile_pilot/contracts_observe.py" in contracts_run.CODE_FILES
    clock = dict(tolerances_frozen_utc="T1", manifest_written_utc="T2", learning_done_utc="T3",
                 inventory_frozen_utc="T4")
    assert contracts_run.order_proof(clock, cached_q2_stamps=[]) == "unknown"
    assert contracts_run.order_proof(clock, cached_q2_stamps=["T5", "T6"]) is True
    assert contracts_run.order_proof(dict(clock, first_q2_parse_utc="T3"), cached_q2_stamps=[]) is False
    assert contracts_run.order_proof(dict(clock, first_q2_parse_utc="T4"), cached_q2_stamps=[]) is True


# ---------------------------------------------------------------- producer lineage (I1)

def _profile_chain(tmp_path):
    """A fake census root and a profile root derived from it (real Task 6 stage)."""
    from scripts.profile_pilot import profile_run
    from tests.test_profile_pilot_profile import CIK as PCIK, NOW as PNOW, build_census_root, sibling
    census_paths = build_census_root(tmp_path)
    prof_paths = sibling(census_paths, run_id="stageb-profile-test")
    profile_run.run_stage(prof_paths, census_run_id=census_paths.run_id, ciks=[PCIK], recorded_at=PNOW)
    return census_paths, prof_paths, PCIK


def _copy_census_root(census_paths, run_id):
    import shutil
    shutil.copytree(census_paths.run_root, census_paths.run_root.parent / run_id)
    return run_id


def test_contracts_pins_a_profile_root_only_when_it_was_derived_from_the_pinned_census(tmp_path):
    from scripts.profile_pilot import contracts_run
    from scripts.profile_pilot.manifest import StageInvalidated
    from tests.test_profile_pilot_profile import sibling
    census_paths, prof_paths, cik = _profile_chain(tmp_path)
    paths = sibling(census_paths, run_id="stageb-contracts-test")
    census = contracts_run.pin_census(paths, census_paths.run_id, [cik])
    pinned = contracts_run.pin_profiles(paths, prof_paths.run_id, [cik], census=census)
    assert pinned["lineage"]["ok"] is True and pinned["lineage"]["census_run_id"] == census_paths.run_id
    assert [c["profile"] for c in pinned["lineage"]["checked"]] == [cik + "/q1"]
    assert pinned["census_sha256"][cik] == census["selected"][(cik, "q1")]["census_sha256"]
    # Same bytes, other census root: the profile root names a different producer.
    other = contracts_run.pin_census(paths, _copy_census_root(census_paths, "stageb-fake-census-copy"), [cik])
    with pytest.raises(StageInvalidated, match="derived from census root"):
        contracts_run.pin_profiles(paths, prof_paths.run_id, [cik], census=other)
    # Same census root id, but its authoritative Q1 census is now different bytes.
    target = census_paths.run_root / "census" / cik / "2023-03-31.json"
    target.write_text(target.read_text(encoding="ascii") + " ", encoding="ascii")
    listing = census_paths.run_root / "results" / "authoritative.json"
    body = json.loads(listing.read_text(encoding="ascii"))
    for row in body["fund_quarters"]:
        if row["census_relative"] == "census/" + cik + "/2023-03-31.json":
            row["census_sha256"] = manifest.sha256_file(target)
    listing.write_text(json.dumps(body), encoding="ascii")
    changed = contracts_run.pin_census(paths, census_paths.run_id, [cik])
    with pytest.raises(StageInvalidated, match="was derived from census"):
        contracts_run.pin_profiles(paths, prof_paths.run_id, [cik], census=changed)
    code = contracts_run.main(["run", "--main-root", str(paths.main_repo_root), "--data-root", str(paths.data_root),
                               "--run-id", "stageb-contracts-test2", "--census-run-id", census_paths.run_id,
                               "--profile-run-id", prof_paths.run_id, "--cik", cik])
    assert code == contracts_run.EXIT_INVALIDATED


def test_profile_document_source_must_name_the_lineage_census(tmp_path):
    from scripts.profile_pilot import contracts_run
    from scripts.profile_pilot.manifest import StageInvalidated
    census_paths, prof_paths, cik = _profile_chain(tmp_path)
    record = manifest.file_record(prof_paths.run_root / "profiles" / cik / "q1.json", "p")
    doc = contracts_run.load_profile(record)
    assert contracts_run.load_profile(record, census_sha256=doc["source"]["census_sha256"]) == doc
    with pytest.raises(StageInvalidated, match="profile document source"):
        contracts_run.load_profile(record, census_sha256="0" * 64)


# ---------------------------------------------------------------- real census pair (cache)

@pytest.mark.needs_cache
def test_real_stellus_census_pair_learns_and_evaluates_every_contract():
    data_root = os.environ.get("PROFILE_PILOT_DATA_ROOT")
    if not data_root:
        pytest.skip("PROFILE_PILOT_DATA_ROOT not set (run through the pilot launcher)")
    root = Path(data_root) / "pilot" / "filer_profile" / "stageb-20260929t004819z" / "census" / "0001901037"
    q1 = json.loads((root / "2022-09-30.json").read_text(encoding="ascii"))["result"]
    q2 = json.loads((root / "2022-12-31.json").read_text(encoding="ascii"))["result"]
    profile_path = (Path(data_root) / "pilot" / "filer_profile" / "stageb-profile-20260929t015742z" / "profiles"
                    / "0001901037" / "q1.json")
    profile = json.loads(profile_path.read_text(encoding="ascii"))["result"]
    tol = tolerances()
    block = contracts.learn_contracts(cik="0001901037", q1_doc=q1, q1_profile=profile, grammar=None,
                                      yield_q1=dict(status="insufficient_evidence", vote=None, cause="test",
                                                    report_date="2022-09-30"),
                                      tolerances=tol, q2_listing=dict(Q2_LISTING, report_date="2022-12-31"),
                                      recorded_at=RECORDED)
    assert block["tier"] == "standard" and block["q1"]["positions"] == 62
    assert not any(c["learn_cause"] == "q1_profile_disagrees_with_census" for c in block["contracts"])
    results = contracts.evaluate_contracts(block, tol, q2_doc=q2, q2_listing=dict(Q2_LISTING, report_date="2022-12-31"),
                                           grammar=None, yield_q2=dict(status="insufficient_evidence", vote=None,
                                                                       cause="test", report_date="2022-12-31"))
    assert len(results) == len(block["contracts"])
    assert {r["q2"]["form_type"] for r in results} == {"10-K"}
    assert all(r["status"] in contracts.STATUSES for r in results)
    assert pick(results, "format_grammar", "investment_identifier")["cause"] == "not_learned_in_q1: no_authored_grammar"


CENSUS_RUN = "stageb-20260929t004819z"
PROFILE_RUN = "stageb-profile-20260929t015742z"


@pytest.mark.needs_cache
def test_real_census_pairs_for_all_eight_ciks_learn_and_evaluate():
    """Smoke over every authoritative Q1/Q2 pair (grammar inherited, yield stubbed): no crash,
    fixed denominator, exactly one status per contract, no profile/census disagreement."""
    data_root = os.environ.get("PROFILE_PILOT_DATA_ROOT")
    if not data_root:
        pytest.skip("PROFILE_PILOT_DATA_ROOT not set (run through the pilot launcher)")
    from pipeline.identifier_rate import load_grammar
    from pipeline.identifier_signature import load_anchors
    from scripts.profile_pilot import cohort
    base = Path(data_root) / "pilot" / "filer_profile"
    listing = json.loads((base / CENSUS_RUN / "results" / "authoritative.json").read_text(encoding="ascii"))
    rows = {(r["cik"], r["role"]): r for r in listing["fund_quarters"]}
    tol = tolerances()
    stub = dict(status="insufficient_evidence", vote=None, cause="test")
    for cik in cohort.PILOT_CIKS:
        q1_row = rows[(cik, "q1")]
        q1 = json.loads((base / CENSUS_RUN / q1_row["census_relative"]).read_text(encoding="ascii"))["result"]
        profile = json.loads((base / PROFILE_RUN / "profiles" / cik / "q1.json").read_text(encoding="ascii"))["result"]
        gram = None
        path = Path(contracts.__file__).resolve().parents[2] / "data" / "overrides" / "identifier_rate_grammars" / (
            cik + ".json")
        if path.is_file():
            gram = contracts.grammar_info(load_grammar(cik), path=str(path), sha256="0" * 64,
                                          anchors=load_anchors(cik, anchor_dir=path.parents[1] / "identifier_anchors"))
        q2_row = rows.get((cik, "q2"))
        listing_q2 = dict(status="available" if q2_row else "unavailable",
                          report_date=q2_row["report_date"] if q2_row else None, detail="test")
        block = contracts.learn_contracts(cik=cik, q1_doc=q1, q1_profile=profile, grammar=gram,
                                          yield_q1=dict(stub, report_date=q1_row["report_date"]), tolerances=tol,
                                          q2_listing=listing_q2, recorded_at=RECORDED)
        assert not [c["contract_id"] for c in block["contracts"]
                    if c["learn_cause"] == "q1_profile_disagrees_with_census"], cik
        assert not block["partitions_evidenced"]
        q2 = None
        if q2_row:
            q2 = json.loads((base / CENSUS_RUN / q2_row["census_relative"]).read_text(encoding="ascii"))["result"]
        results = contracts.evaluate_contracts(block, tol, q2_doc=q2, q2_listing=listing_q2, grammar=gram,
                                               yield_q2=dict(stub, report_date=listing_q2["report_date"]))
        expected = 2 * len(POSITION_FIELDS) + len(contracts.SCALE_FIELDS) + len(contracts.RANGE_FIELDS) + 2 + 2
        assert len(results) == len(block["contracts"]) == expected == 59, cik
        assert len([c for c in block["contracts"] if c["kind"] in contracts.KINDS]) == 57, cik
        assert all(r["status"] in contracts.STATUSES and r["status"] != "holds_with_form_type" for r in results)
        json.dumps(results, allow_nan=False).encode("ascii")
        del q1, q2, profile


@pytest.mark.needs_cache
def test_real_s2_evidence_for_onex_and_stellus(tmp_path):
    """The adapter over the real (read-only) unified + income CSVs for two fund-quarters."""
    data_root = os.environ.get("PROFILE_PILOT_DATA_ROOT")
    if not data_root:
        pytest.skip("PROFILE_PILOT_DATA_ROOT not set (run through the pilot launcher)")
    import duckdb
    out = Path(data_root) / "output"
    con = duckdb.connect(config=dict(threads=2, memory_limit="2GB", temp_directory=str(tmp_path)))
    try:
        h = con.execute("SELECT * FROM read_csv(?, all_varchar=true, header=true) WHERE lpad(cik,10,'0') IN "
                        "('0001860424', '0001901037')", [str(out / "private_markets_holdings.csv")]).df()
        inc = con.execute("SELECT * FROM read_csv(?, all_varchar=true, header=true)",
                          [str(out / "bdc_fund_income.csv")]).df()
    finally:
        con.close()
    base = Path(data_root) / "pilot" / "filer_profile" / CENSUS_RUN / "census"
    for cik, q in (("0001860424", "2023-06-30"), ("0001860424", "2023-09-30"), ("0001901037", "2022-09-30")):
        doc = json.loads((base / cik / (q + ".json")).read_text(encoding="ascii"))["result"]
        frame = h[(h["cik"] == cik) & (h["report_date"] == q)]
        ev = contracts_income.income_evidence(frame, inc[inc["report_date"] <= q], cik=cik, report_date=q,
                                              census_doc=doc, cwd=lambda: chdir(tmp_path))
        assert ev["status"] in ("vote", "insufficient_evidence") and (ev["status"] == "vote") == (ev["cause"] is None)
        json.dumps(ev, allow_nan=False).encode("ascii")



# ================================================================ Task B2-3: tolerances v3, semantic kinds

V2_RUN = "stageb-contracts-20260929t053506z"
V2_SHA = "bf15c296caf581617436b50c932d59c87164767eb77e79902c2a34584bb934ec"
SEMANTIC = ("rate_composition", "text_agreement")


def floater(i, *, rate=None, spread="0.05", unit="pure", spread_unit=None, ident=None, extra=None):
    """A floating-rate row: base = rate - spread varies a little across rows (IQR > 0)."""
    rate = rate if rate is not None else "%.4f" % (0.09 + (i % 10) * 0.001)
    fields = dict(fair_value=val("1000000", "usd", decimals="0"), principal_amount=val("1000000", "usd", decimals="0"),
                  interest_rate=val(rate, unit), basis_spread=val(spread, spread_unit or unit))
    fields.update(extra or {})
    pct = "%.2f" % (float(spread) * (100 if (spread_unit or unit) == "pure" else 1))
    return dict(ctx="f%d" % i, ident=ident or ("Acme %d | First Lien | S + %s%% | 1/1/2029" % (i, pct)), dims=(),
                fields=fields)


def floaters(n=60, **kw):
    return [floater(i, **kw) for i in range(n)]


def v2_tol():
    return contracts.tolerance_content_v2()


def strip_flag(results):
    return [{k: v for k, v in r.items() if k != "newly_abstained"} for r in results]


def test_v2_tolerance_content_reproduces_the_frozen_v2_digest():
    assert manifest.digest(contracts.tolerance_content_v2()) == V2_SHA
    assert contracts.tolerance_content_v2()["version"] == "contract-tolerances.v2"


def test_v3_tolerance_content_carries_v2_verbatim_and_the_new_bands():
    v2, v3 = contracts.tolerance_content_v2(), contracts.tolerance_content()
    assert v3["version"] == contracts.TOLERANCES_VERSION == "contract-tolerances.v3"
    assert v3["v2_verbatim"] == v2 and v3["v2_content_sha256"] == V2_SHA
    for tier in ("standard", "low_history"):
        assert {k: v3["bands"][tier][k] for k in v2["bands"][tier]} == v2["bands"][tier]
        assert set(v3["bands"][tier]) - set(v2["bands"][tier]) == {"share_pp", "iqr_widen", "text_share_pp",
                                                                   "min_rows", "min_parse_share"}
    assert v3["supersedes"]["version"] == "contract-tolerances.v2" and v3["supersedes"]["run_id"] == V2_RUN
    assert "adds rate_composition and text_agreement" in v3["supersedes"]["reason"]
    assert "in-sample" in v3["supersedes"]["reason"]
    assert "in-sample (bands chosen after Q2 and the history were read)" in json.dumps(v3["calibration"])
    assert "not a fifth status" in v3["operationalisation"]["newly_abstained"]
    for key in ("rate_composition", "text_agreement"):
        assert v3["operationalisation"][key]
    for name in ("spec_table_verbatim", "scale_conventions", "fund_income_yield", "low_history_below_positions",
                 "form_type_qualifiers", "identifier_format_interpretation"):
        assert v3[name] == v2[name]
    json.dumps(v3).encode("ascii")


def test_v3_adds_exactly_two_contracts_per_learned_partition_and_keeps_the_v2_subset_identical():
    q1, q2 = mk_doc(book() + floaters()), mk_doc(book() + floaters(), date=Q2)
    b2, b3 = learn(q1, gram=grammar(), tol=v2_tol()), learn(q1, gram=grammar())
    assert len(b3["contracts"]) == len(b2["contracts"]) + 2
    assert [c for c in b3["contracts"] if c["kind"] not in SEMANTIC] == b2["contracts"]
    assert [c["kind"] for c in b3["contracts"][-2:]] == list(SEMANTIC)
    r2 = evaluate(b2, q2, gram=grammar(), tol=v2_tol())
    r3 = evaluate(b3, q2, gram=grammar())
    assert strip_flag([r for r in r3 if r["kind"] not in SEMANTIC]) == strip_flag(r2)
    assert b2["version"] == "contracts.v0.2" and b3["version"] == "contracts.v0.3"
    parts = learn(mk_doc(book(dims=[("abc:TypeAxis", "abc:DebtMember")]) + floaters(),
                         partition=(evidenced(DEBT),)))
    per = {}
    for c in parts["contracts"]:
        if c["kind"] in SEMANTIC:
            per.setdefault(c["partition_id"], []).append(c["kind"])
    assert len(per) == 2 and all(sorted(v) == sorted(SEMANTIC) for v in per.values())


# ---------------------------------------------------------------- rate_composition

def test_composition_spread_for_coupon_breaches_with_every_row_as_violating_key():
    block = learn(mk_doc(floaters()))
    comp = pick(block["contracts"], "rate_composition", contracts.COMPOSITION_FIELD)
    assert comp["learn_status"] == "learned"
    assert comp["expectation"]["share_rate_le_spread"] == 0.0 and comp["expectation"]["n"] == 60
    swapped = mk_doc([floater(i, rate="0.05") for i in range(60)], date=Q2)
    res = pick(evaluate(block, swapped), "rate_composition", contracts.COMPOSITION_FIELD)
    assert res["status"] == "breach" and res["observed"]["share_rate_le_spread"] == 1.0
    assert res["observed"]["criteria"]["share"] == "breach"
    assert res["violating_keys"] == sorted("f%d" % i for i in range(60))


def test_composition_pure_level_shift_with_unchanged_dispersion_holds():
    block = learn(mk_doc(floaters()))
    shifted = mk_doc([floater(i, rate="%.4f" % (0.10 + (i % 10) * 0.001)) for i in range(60)], date=Q2)
    res = pick(evaluate(block, shifted), "rate_composition", contracts.COMPOSITION_FIELD)
    assert res["status"] == "holds"
    assert abs(res["observed"]["p50_shift"] - 1.0) < 1e-6        # evidence only, never a criterion


def test_composition_dispersion_widening_breaches_on_the_iqr_criterion():
    block = learn(mk_doc(floaters()))
    mixed = mk_doc([floater(i, rate="0.05" if i % 3 == 0 else None) for i in range(60)], date=Q2)
    wide = contracts.semantic_tolerances(v2_tol(), share_pp=90, iqr_widen=2.0, text_share_pp=10)
    res = pick(contracts.evaluate_contracts(contracts.rebanded_block(block, wide), wide, q2_doc=mixed,
                                            q2_listing=Q2_LISTING, grammar=None,
                                            yield_q2=dict(VOTE_CASH, report_date=Q2)),
               "rate_composition", contracts.COMPOSITION_FIELD)
    assert res["observed"]["criteria"] == dict(share="holds", iqr="breach") and res["status"] == "breach"
    assert set(res["violating_keys"]) >= {"f0", "f3"}


def test_composition_low_n_abstains_on_either_side():
    few = learn(mk_doc(book() + floaters(5)))
    comp = pick(few["contracts"], "rate_composition", contracts.COMPOSITION_FIELD)
    assert comp["learn_status"] == "insufficient_evidence"
    assert comp["learn_cause"] == "fewer_than_min_rows_with_both_fields"
    block = learn(mk_doc(floaters()))
    res = pick(evaluate(block, mk_doc(book() + floaters(5), date=Q2)), "rate_composition",
               contracts.COMPOSITION_FIELD)
    assert res["status"] == "insufficient_evidence"
    assert res["cause"] == "fewer_than_min_rows_with_both_fields_in_q2" and res["newly_abstained"] is True


def test_composition_is_not_gated_on_scale_and_resolves_magnitude_per_row():
    block = learn(mk_doc(floaters()))
    # declared units differ (rate percent, spread pure): the declared conversion resolves the row
    declared = mk_doc([floater(i, rate="%.2f" % (9 + (i % 10) * 0.1), unit="pct", spread_unit="pure")
                       for i in range(60)], date=Q2)
    results = evaluate(block, declared)
    assert pick(results, "scale", "interest_rate")["status"] == "breach"
    comp = pick(results, "rate_composition", contracts.COMPOSITION_FIELD)
    assert comp["status"] == "holds" and comp["observed"]["unresolved_share"] == 0.0
    # same declared unit, magnitudes differ (spread 5.0 under pure) on 20% of rows: excluded, reported
    some = mk_doc([floater(i, spread="5.0" if i < 12 else "0.05") for i in range(60)], date=Q2)
    comp = pick(evaluate(block, some), "rate_composition", contracts.COMPOSITION_FIELD)
    assert comp["status"] == "holds" and comp["observed"]["unresolved_share"] == 0.2
    most = mk_doc([floater(i, spread="5.0" if i < 36 else "0.05") for i in range(60)], date=Q2)
    comp = pick(evaluate(block, most), "rate_composition", contracts.COMPOSITION_FIELD)
    assert comp["status"] == "insufficient_evidence" and comp["cause"] == "unresolved_pair_majority_in_q2"
    assert comp["observed"]["unresolved_share"] == 0.6 and comp["newly_abstained"] is True


def test_composition_excludes_zero_rate_rows_and_counts_them():
    rows = floaters() + [floater(100 + i, rate="0", spread="0") for i in range(5)]
    block = learn(mk_doc(rows))
    comp = pick(block["contracts"], "rate_composition", contracts.COMPOSITION_FIELD)
    assert comp["expectation"]["n"] == 60 and comp["evidence"]["zero_rate_rows"] == 5


# ---------------------------------------------------------------- text_agreement and its patterns

@pytest.mark.parametrize("text, category, spread, cash, pik", [
    ("Acme | SOFR + 750 | 1/1/2029", "base_plus_spread", 7.50, [], []),
    ("Acme | S + 5.50% | 1/1/2029", "base_plus_spread", 5.50, [], []),
    ("Acme Notes | 12.00% | 1/1/2029", "bare_pct", None, [12.0], []),
    ("Carestream (First Lien) | L + 675 | 12.18 % | 9/30/2027", "base_plus_spread", 6.75, [12.18], []),
    ("Acme | TERM SOFR (3M) + 6.25% | 1/1/2030", "base_plus_spread", 6.25, [], []),
    # negatives
    ("S+S Worldwide Inc, First Lien Term Loan", "no_rate_text", None, [], []),
    ("S+S Worldwide Inc | S + 4.75% | 1/1/2029", "base_plus_spread", 4.75, [], []),
    ("Series S+ 2023 Notes", "no_rate_text", None, [], []),
    ("1.5% Club Holdings LLC, Common Units", "no_rate_text", None, [], []),
    ("Acme 7.5% Holdings LLC, Class A Units", "no_rate_text", None, [], []),
    ("Acme Second Lien | 12.00% PIK | 1/1/2029", "pik_pct_only", None, [], [12.0]),
    ("Acme | 10.00% Cash / 2.00% PIK | 1/1/2029", "bare_pct", None, [10.0], [2.0]),
    ("Terrestar (First Lien Term Loan H) | 11% PIK | 2/28/2024", "pik_pct_only", None, [], [11.0]),
    ("CCS Medical Inc (First Lien Term Loan) | 15% Fixed | 4/7/2026", "bare_pct", None, [15.0], []),
])
def test_generic_rate_text_patterns_on_the_owner_session_examples_and_negatives(text, category, spread, cash, pik):
    from scripts.profile_pilot import contracts_observe as co
    out = co.parse_rate_text(text)
    assert out["category"] == category and out["parser"] == "generic"
    assert out["spread"] == spread and out["cash_pcts"] == cash and out["pik_pcts"] == pik


def test_generic_patterns_are_named_constants():
    from scripts.profile_pilot import contracts_observe as co
    for name in ("RE_BASE_PLUS_PCT", "RE_BASE_PLUS_BPS", "RE_PCT", "RE_UNDRAWN", "BASE_TOKENS"):
        assert getattr(co, name)
    assert set(co.BASE_TOKENS) == {"SOFR", "S", "LIBOR", "L", "SONIA", "EURIBOR", "E", "PRIME", "P", "TERM SOFR",
                                   "BSBY", "CDOR"}
    assert co.RE_BASE_PLUS_BPS.search("SOFR + 750") and not co.RE_BASE_PLUS_BPS.search("SOFR + 7.50%")


def test_text_agreement_generic_path_learns_shares_and_breaches_on_a_numeric_divergence():
    block = learn(mk_doc(floaters()))
    text = pick(block["contracts"], "text_agreement", contracts.TEXT_FIELD)
    assert text["learn_status"] == "learned" and text["expectation"]["parser"]["kind"] == "generic"
    shares = text["expectation"]["shares"]
    assert shares["spread_text_matches_numeric"] == dict(share=1.0, n=60)
    assert shares["rate_equals_text_spread"] == dict(share=0.0, n=60)
    moved = mk_doc([floater(i, spread="0.06", ident="Acme %d | First Lien | S + 5.00%% | 1/1/2029" % i)
                    for i in range(60)], date=Q2)
    res = pick(evaluate(block, moved), "text_agreement", contracts.TEXT_FIELD)
    assert res["status"] == "breach" and res["cause"] == "text_share_moved"
    assert res["observed"]["criteria"]["spread_text_matches_numeric"] == "breach"
    assert res["violating_keys"] == sorted("f%d" % i for i in range(60))      # rows whose category flipped


def test_text_agreement_category_flip_keys_only_the_flipped_rows():
    block = learn(mk_doc(floaters()))
    rows = [floater(i, rate="0.05") if i < 20 else floater(i) for i in range(60)]
    res = pick(evaluate(block, mk_doc(rows, date=Q2)), "text_agreement", contracts.TEXT_FIELD)
    assert res["status"] == "breach" and res["observed"]["criteria"]["rate_equals_text_spread"] == "breach"
    assert res["violating_keys"] == sorted("f%d" % i for i in range(20))


def test_text_agreement_grammar_path_uses_the_pinned_authored_grammar():
    block = learn(mk_doc(book()), gram=grammar())
    text = pick(block["contracts"], "text_agreement", contracts.TEXT_FIELD)
    assert text["expectation"]["parser"] == dict(kind="grammar", grammar_sha256="0" * 64, dialect="RATE",
                                                 path="test/grammar.json", provenance="inherited")
    assert text["expectation"]["shares"]["rate_equals_text_pct"] == dict(share=1.0, n=60)
    res = pick(evaluate(block, mk_doc(book(rate="0.12"), date=Q2), gram=grammar()), "text_agreement",
               contracts.TEXT_FIELD)
    assert res["status"] == "breach" and len(res["violating_keys"]) == 60
    with pytest.raises(contracts.ContractError):
        evaluate(block, mk_doc(book(), date=Q2), gram=None)


def test_text_agreement_excludes_undrawn_zero_rate_rows_and_counts_them():
    undrawn = [floater(100 + i, rate="0", spread="0",
                       ident="Acme %d Delayed Draw Term Loan | SOFR + 0.00%% | 1/1/2029" % i) for i in range(8)]
    block = learn(mk_doc(floaters() + undrawn))
    text = pick(block["contracts"], "text_agreement", contracts.TEXT_FIELD)
    assert text["expectation"]["shares"]["rate_equals_text_spread"] == dict(share=0.0, n=60)
    assert text["evidence"]["undrawn_zero_rate_rows"] == 8


def test_text_agreement_abstains_below_the_parse_share_floor():
    bare = [debt(i, ident="Acme %d First Lien Term Loan" % i) for i in range(40)]
    block = learn(mk_doc(bare + floaters(20)))
    text = pick(block["contracts"], "text_agreement", contracts.TEXT_FIELD)
    assert text["learn_status"] == "insufficient_evidence"
    assert text["learn_cause"] == "identifier_rate_text_parse_share_below_min"
    assert text["evidence"]["parse_share"] == round(20 / 60, 6)
    ok = learn(mk_doc(floaters()))
    res = pick(evaluate(ok, mk_doc(bare + floaters(20), date=Q2)), "text_agreement", contracts.TEXT_FIELD)
    assert res["status"] == "insufficient_evidence" and res["cause"] == \
        "identifier_rate_text_parse_share_below_min_in_q2"


def test_inception_block_is_recorded_on_the_learning_quarter_as_evidence():
    nexpoint_like = [floater(i, rate="0.05") for i in range(60)]           # spread-as-rate from inception
    block = learn(mk_doc(nexpoint_like))
    for kind, field in (("rate_composition", contracts.COMPOSITION_FIELD), ("text_agreement", contracts.TEXT_FIELD)):
        inception = pick(block["contracts"], kind, field)["evidence"]["inception"]
        assert inception["report_date"] == Q1 and inception["share_rate_le_spread"] == 1.0
        assert inception["rate_equals_text_spread"]["share"] == 1.0 and inception["implied_base_p50"] == 0.0
        assert "evidence, not a contract status" in inception["note"]


# ---------------------------------------------------------------- newly_abstained (a flag, not a status)

def test_newly_abstained_flags_learned_contracts_that_abstain_and_summarise_counts_them():
    block = learn(mk_doc(book() + floaters()))
    results = evaluate(block, mk_doc([], date=Q2))
    learned = {c["contract_id"] for c in block["contracts"] if c["learn_status"] == "learned"}
    for r in results:
        assert r["newly_abstained"] is (r["contract_id"] in learned and r["status"] == "insufficient_evidence")
    m2 = contracts.summarise_m2(results, denominator=len(results))
    assert set(m2["counts"]) == set(contracts.STATUSES)
    newly = sum(r["newly_abstained"] for r in results)
    assert newly > 0 and m2["newly_abstained"]["count"] == newly
    assert m2["newly_abstained"]["share"] == round(newly / len(results), 6)
    assert "newly_abstained" in m2["strict_6_3"]


def test_prior_pair_marks_a_carried_abstention_as_newly_only_after_a_decided_status():
    prior = [dict(contract_id="a", status="holds"), dict(contract_id="b", status="insufficient_evidence"),
             dict(contract_id="c", status="breach")]
    now = [dict(contract_id="a", status="insufficient_evidence", newly_abstained=False),
           dict(contract_id="b", status="insufficient_evidence", newly_abstained=False),
           dict(contract_id="c", status="breach", newly_abstained=False),
           dict(contract_id="d", status="insufficient_evidence", newly_abstained=True)]
    out = contracts.mark_prior_abstentions(now, prior)
    assert [r["newly_abstained"] for r in out] == [True, False, False, True]


def test_v2_subset_check_compares_v2_contracts_and_results_without_the_flag():
    from scripts.profile_pilot import contracts_run
    q1, q2 = mk_doc(book() + floaters()), mk_doc(book() + floaters(), date=Q2)
    b2, b3 = learn(q1, tol=v2_tol()), learn(q1)
    r2 = json.loads(json.dumps(strip_flag(evaluate(b2, q2, tol=v2_tol()))))
    r3 = evaluate(b3, q2)
    check = contracts_run.v2_subset_check({CIK: b3}, {CIK: r3}, v2_blocks={CIK: b2}, v2_results={CIK: r2})
    assert check["identical"] is True and check["by_cik"][CIK] == dict(contracts=True, results=True, v2_contracts=57,
                                                                       semantic_contracts=2)
    bad = copy.deepcopy(r2)
    bad[0]["status"] = "breach"
    check = contracts_run.v2_subset_check({CIK: b3}, {CIK: r3}, v2_blocks={CIK: b2}, v2_results={CIK: bad})
    assert check["identical"] is False and check["by_cik"][CIK]["results"] is False
    assert check["differences"][CIK]
