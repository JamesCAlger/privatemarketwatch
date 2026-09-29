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
    tol = tolerances()
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
                         format_grammar=1, fund_income_yield=1)
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
        expected = 2 * len(POSITION_FIELDS) + len(contracts.SCALE_FIELDS) + len(contracts.RANGE_FIELDS) + 2
        assert len(results) == len(block["contracts"]) == expected == 57, cik
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
