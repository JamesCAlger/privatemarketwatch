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
