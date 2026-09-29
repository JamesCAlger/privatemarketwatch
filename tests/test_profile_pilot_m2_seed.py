"""Task B2-1: seeded-drift harness for M2 (sensitivity of the frozen v2 contracts to injected drift).

Synthetic census documents come from the Task 8 helpers (mk_doc / debt). The perturbations
are injected into a Q1 document which is then evaluated as a synthetic Q2 against the
contracts learned from the unperturbed Q1. The one `needs_cache` test runs the CLI on
Stellus (0001901037) against the real authoritative roots through PROFILE_PILOT_DATA_ROOT,
with the run root redirected into tmp_path (the real data directory is only read).
"""
from __future__ import annotations

import copy
from dataclasses import dataclass
import json
import math
import os
from pathlib import Path

import pytest

from scripts.profile_pilot import m2_seed
from scripts.profile_pilot.paths import PilotPaths
from tests.test_profile_pilot_contracts import (
    CIK, UNITS, debt, evaluate, grammar, learn, mk_doc, pick, tolerances, val)

FRACTIONS = (0.05, 0.10, 0.20, 0.30, 0.50, 1.0)


def book(n=60, **kw):
    rows = []
    for i in range(n):
        spec = debt(i, **kw)
        spec["fields"]["basis_spread"] = val("0.05")
        rows.append(spec)
    return rows


def q1(n=60, **kw):
    return mk_doc(book(n, **kw))


def run(doc, kind, fraction, seed=1, **kw):
    return m2_seed.perturb(doc, kind, fraction, seed=seed, **kw)


def status(results, kind, field="interest_rate"):
    hit = pick(results, kind, field)
    return hit["status"], hit["cause"]


ALL_KINDS = ("scale_flip", "scale_flip_declared", "concept_move_namespace", "concept_move_local",
             "spread_for_coupon", "fill_drop", "range_shift", "identifier_format")


def kw_for(kind):
    return dict(delta=0.3) if kind == "range_shift" else {}


# ---------------------------------------------------------------- receipts and determinism

@pytest.mark.parametrize("kind", ALL_KINDS)
@pytest.mark.parametrize("fraction", FRACTIONS)
def test_receipt_touches_exactly_ceil_fraction_of_eligible_rows(kind, fraction):
    doc = q1()
    out, receipt = run(doc, kind, fraction, **kw_for(kind))
    assert receipt["eligible"] == 60
    assert receipt["touched"] == math.ceil(fraction * 60) == len(receipt["rows"])
    assert len({r["context_id"] for r in receipt["rows"]}) == receipt["touched"]
    assert receipt["rule"] and receipt["kind"] == kind and receipt["seed"] == 1
    json.dumps(receipt, allow_nan=False).encode("ascii")


@pytest.mark.parametrize("kind", ALL_KINDS)
def test_same_seed_is_idempotent_and_the_original_is_never_mutated(kind):
    doc = q1()
    before = copy.deepcopy(doc)
    a, ra = run(doc, kind, 0.3, seed=7, **kw_for(kind))
    b, rb = run(doc, kind, 0.3, seed=7, **kw_for(kind))
    cow, rc = run(doc, kind, 0.3, seed=7, deep=False, **kw_for(kind))
    assert a == b == cow and ra == rb == rc
    assert doc == before
    c, rc2 = run(doc, kind, 0.3, seed=8, **kw_for(kind))
    assert {r["context_id"] for r in rc2["rows"]} != {r["context_id"] for r in ra["rows"]}


@pytest.mark.parametrize("kind", ALL_KINDS)
def test_fraction_zero_returns_an_unchanged_copy(kind):
    doc = q1()
    out, receipt = run(doc, kind, 0.0, **kw_for(kind))
    assert out == doc and out is not doc and receipt["touched"] == 0 and receipt["rows"] == []


def test_perturb_refuses_unknown_kind_bad_fraction_and_bad_delta():
    doc = q1(5)
    with pytest.raises(ValueError):
        run(doc, "shuffle", 0.5)
    with pytest.raises(ValueError):
        run(doc, "fill_drop", 1.5)
    with pytest.raises(ValueError):
        run(doc, "range_shift", 0.5)  # delta required
    with pytest.raises(ValueError):
        run(doc, "range_shift", 0.5, delta=0.2)  # only the declared deltas


def test_receipt_records_before_and_after_values_for_value_classes():
    doc = q1(10)
    _, receipt = run(doc, "scale_flip", 1.0)
    assert {(r["before"], r["after"]) for r in receipt["rows"]} == {("0.10", "10")}
    _, receipt = run(doc, "range_shift", 1.0, delta=0.6)
    assert {(r["before"], r["after"]) for r in receipt["rows"]} == {("0.10", "0.16")}
    _, receipt = run(doc, "spread_for_coupon", 1.0)
    assert {(r["before"], r["after"]) for r in receipt["rows"]} == {("0.10", "0.05")}


# ---------------------------------------------------------------- what the frozen contracts see

def test_scale_flip_at_full_fraction_takes_the_scale_abstain_path_and_partial_is_mixed():
    doc = q1()
    block = learn(doc)
    full, _ = run(doc, "scale_flip", 1.0)
    assert status(evaluate(block, full), "scale") == (
        "insufficient_evidence", "magnitude_regime_changed_under_same_declared_unit")
    part, _ = run(doc, "scale_flip", 0.2)
    results = evaluate(block, part)
    assert status(results, "scale") == ("insufficient_evidence", "magnitude_mixed_under_one_declared_unit")
    assert status(results, "value_range") == ("insufficient_evidence", "scale_contract_not_holds")


def test_scale_flip_declared_changes_the_unit_and_breaches_the_scale_contract():
    doc = q1()
    block = learn(doc)
    out, receipt = run(doc, "scale_flip_declared", 0.05)
    assert receipt["added_units"] and all(u in out["units"] for u in receipt["added_units"])
    assert status(evaluate(block, out), "scale") == ("breach", "declared_unit_class_changed")


@pytest.mark.parametrize("fraction", FRACTIONS)
def test_concept_move_namespace_breaches_the_concept_set_at_any_positive_fraction(fraction):
    doc = q1()
    block = learn(doc)
    out, receipt = run(doc, "concept_move_namespace", fraction)
    moved = {r["after"] for r in receipt["rows"]}
    assert len(moved) == 1 and next(iter(moved)).endswith(":InvestmentInterestRate")
    assert next(iter(moved)) != "us-gaap:InvestmentInterestRate"
    assert status(evaluate(block, out), "source_concept_set") == ("breach", "concept_set_changed")


def test_concept_move_local_keeps_the_field_the_real_collector_would_map():
    doc = q1()
    block = learn(doc)
    out, receipt = run(doc, "concept_move_local", 0.1)
    assert {r["after"] for r in receipt["rows"]} == {"us-gaap:InvestmentInterestRatePaidInCash"}
    moved = [p for p in out["positions"] if p["context_id"] in {r["context_id"] for r in receipt["rows"]}]
    assert all(p["fields"]["interest_rate"]["status"] == "reported" for p in moved)
    assert status(evaluate(block, out), "source_concept_set") == ("breach", "concept_set_changed")
    assert status(evaluate(block, out), "fill_rate") == ("holds", None)


def test_spread_for_coupon_is_invisible_to_concept_fill_and_scale_and_range_is_reported_truthfully():
    doc = q1()
    block = learn(doc)
    null = evaluate(block, doc)
    out, _ = run(doc, "spread_for_coupon", 1.0)
    results = evaluate(block, out)
    for kind in ("source_concept_set", "fill_rate", "scale"):
        assert status(results, kind) == status(null, kind) == ("holds", None)  # the blind spot
    # Q1 rates are all 10% (widened +/- 2.5); the spreads are 5%: the range contract sees it.
    assert status(results, "value_range") == ("breach", "quantiles_outside_widened_q1_range")


def test_fill_drop_holds_inside_the_ten_point_band_and_breaches_outside_it():
    doc = q1()
    block = learn(doc)
    small, _ = run(doc, "fill_drop", 0.05)
    assert status(evaluate(block, small), "fill_rate") == ("holds", None)
    large, receipt = run(doc, "fill_drop", 0.20)
    assert status(evaluate(block, large), "fill_rate") == ("breach", "fill_rate_outside_band")
    assert len(large["facts"]) == len(doc["facts"]) - receipt["touched"]
    assert receipt["removed_fact_indices"]


def test_range_shift_small_delta_holds_and_large_delta_breaches():
    doc = q1()
    block = learn(doc)
    small, _ = run(doc, "range_shift", 1.0, delta=0.15)
    assert status(evaluate(block, small), "value_range") == ("holds", None)
    large, _ = run(doc, "range_shift", 1.0, delta=0.6)
    assert status(evaluate(block, large), "value_range") == ("breach", "quantiles_outside_widened_q1_range")


def test_identifier_format_rewrite_is_measured_against_the_pinned_grammar():
    doc = q1()
    gram = grammar()
    block = learn(doc, gram=gram)
    assert pick(evaluate(block, doc, gram=gram), "format_grammar", "investment_identifier")["status"] == "holds"
    out, receipt = run(doc, "identifier_format", 1.0)
    assert all("%" not in r["after"] and r["before"] != r["after"] for r in receipt["rows"])
    hit = pick(evaluate(block, out, gram=gram), "format_grammar", "investment_identifier")
    # The synthetic dialect's RATE anchor needs '%': rewritten rows leave the scope entirely.
    assert (hit["status"], hit["cause"]) == ("breach", "dialect_scope_empty_in_q2")


# ---------------------------------------------------------------- realism guard

@pytest.mark.parametrize("kind", ALL_KINDS)
def test_perturbations_add_no_schema_or_count_errors(kind):
    doc = q1()
    out, receipt = run(doc, kind, 0.5, **kw_for(kind))
    assert m2_seed.realism_errors(doc, out, receipt) == []


def test_realism_guard_catches_an_invalid_perturbation():
    doc = q1()
    out, receipt = run(doc, "fill_drop", 0.5)
    bad = copy.deepcopy(out)
    ctx = receipt["rows"][0]["context_id"]
    target = next(p for p in bad["positions"] if p["context_id"] == ctx)
    target["fields"]["interest_rate"] = dict(status="vanished", provenance="derived", inherited_from=None)
    assert m2_seed.realism_errors(doc, bad, receipt)
    short = copy.deepcopy(out)
    short["positions"] = short["positions"][:-1]
    assert any("positions" in e for e in m2_seed.realism_errors(doc, short, receipt))


# ---------------------------------------------------------------- harness and aggregation

def small_matrix(doc, gram=None):
    block = learn(doc, gram=gram)
    return m2_seed.evaluate_matrix(cik=CIK, block=block, tolerances=tolerances(), q1_doc=doc, grammar=gram,
                                   yield_q2=dict(status="vote", vote="cash_leg", cause=None,
                                                 report_date=doc["document"]["report_date"]),
                                   fractions=(0.0, 0.05, 0.2, 1.0), seeds=(1, 2, 3))


def test_null_control_on_a_synthetic_doc_has_zero_breaches_and_no_status_changes():
    matrix = small_matrix(q1())
    assert matrix["null_control"]["breaches"] == []
    zero = [e for e in matrix["evaluations"] if e["fraction"] == 0.0]
    assert zero and all(e["changed"] == [] and e["touched"] == 0 for e in zero)
    assert all(e["realism_errors"] == [] for e in matrix["evaluations"])
    assert matrix["original_unchanged"] is True


def test_matrix_records_every_contract_status_and_classifies_detection():
    matrix = small_matrix(q1(), gram=grammar())
    n = len(matrix["contract_ids"])
    assert all(len(e["statuses"]) == n for e in matrix["evaluations"])
    fill = [e for e in matrix["evaluations"] if e["variant"] == "fill_drop" and e["fraction"] == 1.0]
    assert fill and all(e["targets"]["fill_rate"]["outcome"] == "detected" for e in fill)
    flip = [e for e in matrix["evaluations"] if e["variant"] == "scale_flip" and e["fraction"] == 1.0]
    assert all(e["targets"]["scale"]["outcome"] == "abstained" for e in flip)
    coupon = [e for e in matrix["evaluations"] if e["variant"] == "spread_for_coupon" and e["fraction"] == 1.0]
    assert all(e["targets"]["scale"]["outcome"] == "missed" for e in coupon)
    variants = {e["variant"] for e in matrix["evaluations"]}
    assert variants == set(m2_seed.VARIANT_NAMES)


def test_outcome_classification():
    assert m2_seed.outcome("holds", "breach") == "detected"
    assert m2_seed.outcome("holds", "insufficient_evidence") == "abstained"
    assert m2_seed.outcome("holds", "holds") == "missed"
    assert m2_seed.outcome("insufficient_evidence", "breach") == "not_applicable"


def test_sensitivity_takes_the_smallest_fraction_detected_by_the_seed_median_and_the_median_over_ciks():
    def ev(cik, fraction, outcomes):
        return [dict(cik=cik, variant="fill_drop", fraction=fraction, seed=s,
                     targets=dict(fill_rate=dict(outcome=o, status=None, cause=None)))
                for s, o in zip((1, 2, 3), outcomes)]
    evaluations = (ev("a", 0.05, ["missed", "detected", "missed"]) + ev("a", 0.2, ["detected"] * 3)
                   + ev("b", 0.05, ["detected", "detected", "missed"]) + ev("b", 0.2, ["detected"] * 3)
                   + ev("c", 0.05, ["missed"] * 3) + ev("c", 0.2, ["missed"] * 3)
                   + ev("d", 0.05, ["not_applicable"] * 3) + ev("d", 0.2, ["not_applicable"] * 3))
    sens = m2_seed.sensitivity(evaluations, variants=("fill_drop",), kinds=("fill_rate",))
    cell = sens["cells"]["fill_drop"]["fill_rate"]
    assert cell["per_cik"]["a"]["smallest_detected"] == 0.2
    assert cell["per_cik"]["b"]["smallest_detected"] == 0.05
    assert cell["per_cik"]["c"]["smallest_detected"] is None
    assert cell["per_cik"]["d"]["applicable"] is False
    assert cell["applicable_ciks"] == 3 and cell["detected_ciks"] == 2
    assert cell["median_smallest_detected"] == 0.2  # median of (0.05, 0.2, never)


# ---------------------------------------------------------------- real data through the CLI

@dataclass(frozen=True)
class TmpRunPaths(PilotPaths):
    tmp_run_root: Path = None

    @property
    def run_root(self) -> Path:
        return self.tmp_run_root


@pytest.mark.needs_cache
def test_real_stellus_seed_matrix_through_the_cli(tmp_path, monkeypatch):
    data_root = os.environ.get("PROFILE_PILOT_DATA_ROOT")
    main_root = os.environ.get("PROFILE_PILOT_MAIN_ROOT")
    if not (data_root and main_root):
        pytest.skip("PROFILE_PILOT_DATA_ROOT not set (run through the pilot launcher)")
    real_resolve = m2_seed.resolve_paths

    def redirected(**kw):
        real = real_resolve(**kw)
        return TmpRunPaths(main_repo_root=real.main_repo_root, code_root=real.code_root,
                           data_root=real.data_root, run_id=real.run_id, tmp_run_root=tmp_path / "run")

    monkeypatch.setattr(m2_seed, "resolve_paths", redirected)
    code = m2_seed.main(["run", "--main-root", main_root, "--data-root", data_root,
                         "--census-run-id", "stageb-20260929t004819z",
                         "--profile-run-id", "stageb-profile-20260929t053308z",
                         "--contracts-run-id", "stageb-contracts-20260929t053506z",
                         "--cik", "0001901037", "--run-id", "stageb2-seed-test",
                         "--scratch-dir", str(tmp_path / "scratch")])
    assert code == 0
    root = tmp_path / "run"
    matrix = json.loads((root / "results" / "seed_matrix.json").read_text(encoding="ascii"))
    cik = matrix["ciks"]["0001901037"]
    assert cik["null_control"]["breaches"] == [] and cik["original_unchanged"] is True
    assert cik["block_source"] == "reused_frozen_learning_block"
    assert len(cik["contract_ids"]) == 57
    assert all(e["realism_errors"] == [] for e in cik["evaluations"])
    assert (root / "results" / "sensitivity.json").is_file() and (root / "results" / "summary.md").is_file()
    built = json.loads((root / "manifest.json").read_text(encoding="ascii"))
    assert built["tolerances"]["content_sha256"] == m2_seed.TOLERANCES_V2_SHA256
    assert list((tmp_path / "scratch").glob("seed_*.md")) and list((tmp_path / "scratch").glob("seed_*.csv"))
    (root / "results" / "summary.md").read_text(encoding="ascii")


def test_realism_self_check_runs_on_seed_one_only_and_is_timed_apart_from_the_measured_work():
    matrix = small_matrix(q1())
    for e in matrix["evaluations"]:
        assert e["realism_checked"] is (e["seed"] == 1)
        if not e["realism_checked"]:
            assert e["realism_errors"] == []
    t = matrix["timing"]
    assert t["measured_seconds"] == round(t["perturb_seconds"] + t["evaluate_seconds"], 3)
    assert "validate_seconds" in t and "R35" in m2_seed.LIMIT_RULE


# ---------------------------------------------------------------- review fix round 1

def test_fraction_zero_is_labelled_null_control_never_missed():
    matrix = small_matrix(q1())
    zero = [e for e in matrix["evaluations"] if e["fraction"] == 0.0]
    assert zero and all(t["outcome"] == "null_control" for e in zero for t in e["targets"].values()
                        if t["baseline_status"] == "holds")
    sens = m2_seed.sensitivity(matrix["evaluations"])
    for row in sens["cells"].values():
        for cell in row.values():
            for c in cell["per_cik"].values():
                assert "missed" not in c["by_fraction"].get("0.0", {})


def test_target_records_keep_the_observed_block_for_mechanism_checks():
    matrix = small_matrix(q1())
    ev = next(e for e in matrix["evaluations"] if e["variant"] == "range_shift_0.6" and e["fraction"] == 1.0)
    rng = ev["targets"]["value_range"]
    assert {"p5", "p95"} <= set(rng["observed"]) and rng["expected"]["widened"]
    fill = next(e for e in matrix["evaluations"] if e["variant"] == "fill_drop" and e["fraction"] == 0.2)
    assert "fill_share" in fill["targets"]["fill_rate"]["observed"]
    concept = next(e for e in matrix["evaluations"] if e["variant"] == "concept_move_local" and e["fraction"] == 0.2)
    assert "concepts" in concept["targets"]["source_concept_set"]["observed"]
    json.dumps(matrix["evaluations"], allow_nan=False).encode("ascii")


def test_zero_eligible_variants_are_not_applicable_in_every_denominator_with_the_reason():
    doc = mk_doc([debt(i) for i in range(60)])  # no basis_spread: spread_for_coupon has 0 eligible rows
    matrix = small_matrix(doc)
    receipt_rows = [e for e in matrix["evaluations"] if e["variant"] == "spread_for_coupon"]
    assert all(e["eligible"] == 0 and e["filled"] == 60 for e in receipt_rows)
    sens = m2_seed.sensitivity(matrix["evaluations"])
    elig = sens["eligibility"]["spread_for_coupon"][CIK]
    assert (elig["eligible"], elig["filled"]) == (0, 60) and "0 eligible" in elig["reason"]
    for kind, cell in sens["cells"]["spread_for_coupon"].items():
        c = cell["per_cik"][CIK]
        assert c["applicable"] is False and "0 eligible" in c["reason"], kind
        assert cell["applicable_ciks"] == 0
    assert sens["cells"]["fill_drop"]["fill_rate"]["applicable_ciks"] == 1
    assert sens["eligibility"]["fill_drop"][CIK]["eligible"] == 60


def test_measured_seconds_is_the_rounded_sum_of_the_recorded_rounded_parts():
    t = m2_seed.finish_timing(dict(perturb_seconds=0.3184999, evaluate_seconds=0.3184999, validate_seconds=1.0))
    assert t["perturb_seconds"] == 0.318 and t["evaluate_seconds"] == 0.318
    assert t["measured_seconds"] == round(t["perturb_seconds"] + t["evaluate_seconds"], 3) == 0.636



# ================================================================ Task B2-3: semantic kinds in the seed harness

from scripts.profile_pilot import contracts  # noqa: E402
from tests.test_profile_pilot_contracts import floater, floaters  # noqa: E402


def fdoc(n=60):
    return mk_doc(floaters(n))


def v3_blocks(doc, gram=None):
    v2 = contracts.tolerance_content_v2()
    return learn(doc, gram=gram, tol=v2), learn(doc, gram=gram), v2


def test_text_numeric_divergence_moves_rate_and_spread_one_point_and_leaves_the_text():
    doc = fdoc()
    out, receipt = run(doc, "text_numeric_divergence", 1.0)
    assert receipt["eligible"] == 60 and receipt["touched"] == 60
    p0, q0 = doc["positions"][0], out["positions"][0]
    assert q0["identity"] == p0["identity"]
    assert q0["fields"]["basis_spread"]["value"] == "0.06" and q0["fields"]["interest_rate"]["value"] == "0.1"
    assert receipt["rows"][0]["delta_pp"] == 1.0


def test_bps_spread_scale_multiplies_the_spread_by_100_under_the_same_unit():
    doc = fdoc()
    out, receipt = run(doc, "bps_spread_scale", 1.0)
    fields = out["positions"][3]["fields"]["basis_spread"]
    assert fields["value"] == "5" and fields["unit_kind"] == doc["positions"][3]["fields"]["basis_spread"]["unit_kind"]
    fact = next(f for f in out["facts"] if f["i"] == fields["fact_indices"][0])
    assert fact["unit_ref"] == "pure" and fact["value"] == "5"


@pytest.mark.parametrize("kind", ("text_numeric_divergence", "bps_spread_scale"))
def test_new_perturbations_are_seeded_copy_on_write_and_schema_clean(kind):
    doc = fdoc()
    before = copy.deepcopy(doc)
    a, ra = run(doc, kind, 0.3, seed=7)
    b, rb = run(doc, kind, 0.3, seed=7, deep=False)
    assert a == b and ra == rb and doc == before and ra["touched"] == math.ceil(0.3 * 60)
    assert m2_seed.realism_errors(doc, a, ra) == []
    zero, rz = run(doc, kind, 0.0)
    assert zero == doc and rz["touched"] == 0


def test_semantic_grid_covers_every_candidate_band_over_the_v2_content_verbatim():
    v2 = contracts.tolerance_content_v2()
    grid = m2_seed.semantic_grid(v2)
    assert len(grid) == 25 + 5 and len({g["name"] for g in grid}) == 30
    comp = [g for g in grid if g["family"] == "composition"]
    assert {(g["share_pp"], g["fixed_share_pp"]) for g in comp} == {(s, f) for s in (5, 10, 15, 20, 25)
                                                                   for f in (5, 10, 15, 20, 25)}
    assert {g["text_share_pp"] for g in grid if g["family"] == "text"} == {5, 10, 15, 20, 25}
    for g in grid:
        for tier in ("standard", "low_history"):
            assert {k: g["tolerances"]["bands"][tier][k] for k in v2["bands"][tier]} == v2["bands"][tier]
    assert m2_seed.CANDIDATES == dict(share_pp=(5, 10, 15, 20, 25), fixed_share_pp=(5, 10, 15, 20, 25),
                                      text_share_pp=(5, 10, 15, 20, 25))


def semantic_matrix(doc, variants=("spread_for_coupon",), fractions=(0.0, 0.05, 0.2, 1.0)):
    b2, b3, v2 = v3_blocks(doc)
    return m2_seed.evaluate_matrix(
        cik=CIK, block=b2, tolerances=v2, q1_doc=doc, grammar=None,
        yield_q2=dict(status="vote", vote="cash_leg", cause=None, report_date=doc["document"]["report_date"]),
        variants=[v for v in m2_seed.SEMANTIC_VARIANTS if v[0] in variants], fractions=fractions, seeds=(1, 2, 3),
        semantic=dict(block=b3, grid=m2_seed.semantic_grid(v2), range_stats=True))


def test_spread_for_coupon_is_seen_by_composition_and_text_and_the_null_control_holds():
    matrix = semantic_matrix(fdoc())
    comp_id = next(c for c in matrix["semantic"]["contracts"] if c["kind"] == "rate_composition")["contract_id"]
    text_id = next(c for c in matrix["semantic"]["contracts"] if c["kind"] == "text_agreement")["contract_id"]
    null = matrix["semantic"]["null_control"]
    assert all(null[name][comp_id][0] == "holds" and null[name][text_id][0] == "holds" for name in null)
    full = [e for e in matrix["evaluations"] if e["fraction"] == 1.0]
    for e in full:
        for name, per in e["semantic"].items():
            if name.startswith("c:"):
                assert per[comp_id][0] == "breach" and per[comp_id][2]["share"] == "breach"
            else:
                assert per[text_id][0] == "breach"
    part = [e for e in matrix["evaluations"] if e["fraction"] == 0.2]
    for e in part:                      # 12 of 60 rows swapped: share moves 20 points
        assert e["semantic"]["c:s15_f10"][comp_id][2]["share"] == "breach"
        assert e["semantic"]["c:s20_f10"][comp_id][2]["share"] == "holds"


def test_semantic_curves_take_the_seed_majority_and_the_median_over_applicable_ciks():
    def ev(cik, fraction, flags, tier="standard"):
        out = []
        for seed, flag in zip((1, 2, 3), flags):
            status = "breach" if flag else "holds"
            out.append(dict(cik=cik, tier=tier, variant="spread_for_coupon", fraction=fraction, seed=seed, semantic={
                "c:s10_f10": {"k": [status, None, dict(share=status, fixed="holds"), 0]}}))
        return out
    evaluations = (ev("a", 0.05, [0, 1, 1]) + ev("a", 0.2, [1, 1, 1]) + ev("b", 0.05, [0, 0, 0])
                   + ev("b", 0.2, [1, 1, 0]) + ev("c", 0.05, [0, 0, 0]) + ev("c", 0.2, [0, 0, 0]))
    meta = {"a": dict(tier="standard", contracts={"k": "rate_composition"}, null={"c:s10_f10": {"k": "holds"}}),
            "b": dict(tier="standard", contracts={"k": "rate_composition"}, null={"c:s10_f10": {"k": "holds"}}),
            "c": dict(tier="low_history", contracts={"k": "rate_composition"}, null={"c:s10_f10": {"k": "holds"}})}
    grid = [dict(name="c:s10_f10", family="composition", share_pp=10, fixed_share_pp=10, text_share_pp=10)]
    curves = m2_seed.semantic_curves(evaluations, grid=grid, meta=meta)
    cell = curves["share_pp"]["10"]["spread_for_coupon"]
    assert cell["per_cik"] == {"a": 0.05, "b": 0.2, "c": None}
    assert cell["median"]["all"] == 0.2 and cell["median"]["standard"] == 0.2
    assert cell["median"]["low_history"] is None and cell["applicable"] == dict(all=3, standard=2, low_history=1)


def test_median_shift_experiment_needs_both_the_median_move_and_the_outside_share():
    learned = dict(p50=10.0, min=5.0, max=15.0, n=100)
    inside = [10.0 + 0.02 * i for i in range(100)]                 # median +10%, nothing outside
    moved = [12.0 + 0.1 * i for i in range(100)]                   # median +71%, many outside
    assert m2_seed.median_shift_verdict(learned, inside, x=0.10, y=0.05) == "holds"
    assert m2_seed.median_shift_verdict(learned, moved, x=0.10, y=0.05) == "breach"
    assert m2_seed.median_shift_verdict(learned, moved, x=0.10, y=0.90) == "holds"
    assert m2_seed.median_shift_verdict(learned, [], x=0.10, y=0.05) == "insufficient_evidence"
    assert m2_seed.MEDIAN_SHIFT == dict(x=(0.10, 0.15, 0.25), y=(0.05, 0.10))


def test_range_samples_route_rows_by_the_frozen_partitions_under_the_learned_scale():
    doc = fdoc()
    b2, _, v2 = v3_blocks(doc)
    samples = m2_seed.range_samples(b2, doc, grammar=None, tolerances=v2)
    rate_id = next(c["contract_id"] for c in b2["contracts"] if c["kind"] == "value_range"
                   and c["field"] == "interest_rate")
    assert len(samples[rate_id]) == 60 and abs(samples[rate_id][0] - 9.0) < 1e-9


def test_relearned_block_must_equal_the_frozen_v2_block_on_the_v2_subset():
    doc = fdoc()
    b2, b3, _ = v3_blocks(doc)
    assert m2_seed.compare_relearned(b2, b3)["equal"] is True
    tampered = copy.deepcopy(b3)
    tampered["contracts"][0]["expectation"] = dict(concepts=["x:y"])
    check = m2_seed.compare_relearned(b2, tampered)
    assert check["equal"] is False and check["differences"]


def test_semantic_meta_curves_and_summary_from_a_real_matrix_shape():
    matrix = semantic_matrix(fdoc(), variants=("spread_for_coupon", "range_shift_0.6"))
    meta, ms_meta = m2_seed.semantic_meta({CIK: matrix})
    assert meta[CIK]["tier"] == "standard" and sorted(meta[CIK]["contracts"].values()) == ["rate_composition",
                                                                                            "text_agreement"]
    curves = m2_seed.semantic_curves(matrix["evaluations"], grid=m2_seed.semantic_grid(
        contracts.tolerance_content_v2()), meta=meta)
    assert curves["share_pp"]["15"]["spread_for_coupon"]["per_cik"][CIK] == 0.2
    assert curves["share_pp"]["25"]["spread_for_coupon"]["per_cik"][CIK] == 1.0
    ms = m2_seed.median_shift_curves(matrix["evaluations"], meta=ms_meta)
    assert set(ms["range_shift_0.6"]) == {m2_seed.ms_name(x, y) for x in (0.10, 0.15, 0.25) for y in (0.05, 0.10)} | {
        "v2_band"}
    text = m2_seed.render_semantic_summary(run_id="stageb2-seed-v3-test", curves=curves, ms_curves=ms, meta=meta,
                                           contracts_by_cik={CIK: matrix["semantic"]["contracts"]})
    assert m2_seed.IN_SAMPLE in text and "NOT in v3" in text
    text.encode("ascii")


@pytest.mark.needs_cache
def test_real_stellus_semantic_seed_through_the_cli(tmp_path, monkeypatch):
    data_root = os.environ.get("PROFILE_PILOT_DATA_ROOT")
    main_root = os.environ.get("PROFILE_PILOT_MAIN_ROOT")
    if not (data_root and main_root):
        pytest.skip("PROFILE_PILOT_DATA_ROOT not set (run through the pilot launcher)")
    real_resolve = m2_seed.resolve_paths

    def redirected(**kw):
        real = real_resolve(**kw)
        return TmpRunPaths(main_repo_root=real.main_repo_root, code_root=real.code_root,
                           data_root=real.data_root, run_id=real.run_id, tmp_run_root=tmp_path / "run")

    monkeypatch.setattr(m2_seed, "resolve_paths", redirected)
    code = m2_seed.main(["run", "--main-root", main_root, "--data-root", data_root,
                         "--census-run-id", "stageb-20260929t004819z",
                         "--profile-run-id", "stageb-profile-20260929t053308z",
                         "--contracts-run-id", "stageb-contracts-20260929t053506z",
                         "--cik", "0001901037", "--run-id", "stageb2-seed-v3-test", "--semantic",
                         "--scratch-dir", str(tmp_path / "scratch")])
    assert code == 0
    root = tmp_path / "run"
    body = json.loads((root / "results" / "semantic_curves.json").read_text(encoding="ascii"))
    assert body["label"] == m2_seed.IN_SAMPLE
    assert body["relearn_checks"]["0001901037"]["equal"] is True
    assert body["relearn_checks"]["0001901037"]["semantic_contracts"] == 2
    assert set(body["curves"]) >= {"share_pp", "fixed_share_pp", "text_share_pp"}
    matrix = json.loads((root / "results" / "seed_matrix.json").read_text(encoding="ascii"))
    assert matrix["ciks"]["0001901037"]["null_control"]["breaches"] == []
    (root / "results" / "semantic_summary.md").read_text(encoding="ascii")


def test_semantic_families_record_the_fixed_coupon_criterion_per_share_band():
    grid = m2_seed.semantic_grid(contracts.tolerance_content_v2())
    families = m2_seed._semantic_families(grid)
    fixed = [(key, point) for family, key, point, kind, criterion in families if family == "fixed_share_pp"]
    assert fixed == [(str(f), "c:s10_f%s" % f) for f in m2_seed.CANDIDATES["fixed_share_pp"]]
    assert {criterion for family, _, _, _, criterion in families if family == "fixed_share_pp"} == {"fixed"}
    assert not [f for f in families if f[0] in ("iqr_widen", "fixed_share")]
