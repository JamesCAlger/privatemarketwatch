"""Task B2-2b: back-test M2 against recorded history (rolling and anchored pairs).

Synthetic census documents come from the Task 8 helpers (mk_doc / debt / mk_profile). The
scoring tests run on hand-built pairs, results and positives. The one `needs_cache` test
runs the CLI on NexPoint (0001588272, the smallest census files) against the real
all-quarter census root through PROFILE_PILOT_DATA_ROOT, with the run root redirected into
tmp_path (the real data directory is only read).
"""
from __future__ import annotations

import json
import os
import re

import pytest

from scripts.profile_pilot import contracts, contracts_income, m2_backtest as bt
from scripts.profile_pilot.census import POSITION_FIELDS, POSITION_RATE
from tests.test_profile_pilot_contracts import (
    CIK, Q1, chdir, debt, holdings, income, learn, mk_doc, mk_profile, tolerances, two_quarters)
from tests.test_profile_pilot_m2_seed import TmpRunPaths

NO_VOTE = dict(status="insufficient_evidence", vote=None, cause="s2_evidence_limit_below_min_quarters",
               report_date=Q1)


# ---------------------------------------------------------------- pairing

def _classes(dates, zero=()):
    return {d: ("pre_tagging" if d in zero else "populated") for d in dates}


def test_rolling_pairs_are_consecutive_and_flag_gaps_from_exclusions_and_the_calendar():
    dates = ["2023-03-31", "2023-06-30", "2023-12-31", "2024-03-31", "2024-09-30"]
    pairs = bt.build_pairs("0000000001", dates, q1_date="2023-06-30",
                           excluded={"2023-09-30": "unavailable"}, classes=_classes(dates))
    rolling = [p for p in pairs if p["mode"] == "rolling"]
    assert [(p["learn_date"], p["eval_date"]) for p in rolling] == [
        ("2023-03-31", "2023-06-30"), ("2023-06-30", "2023-12-31"), ("2023-12-31", "2024-03-31"),
        ("2024-03-31", "2024-09-30")]
    assert [p["gapped"] for p in rolling] == [False, True, False, True]
    assert rolling[1]["gap_reasons"] == ["excluded:2023-09-30:unavailable"]
    assert rolling[3]["gap_reasons"] == ["calendar_gap:6_months"]
    assert all(p["status"] == "evaluated" for p in rolling)
    assert len({p["pair_id"] for p in pairs}) == len(pairs)


def test_anchored_pairs_learn_the_stage_b_q1_and_evaluate_every_later_quarter():
    dates = ["2023-03-31", "2023-06-30", "2023-09-30", "2023-12-31"]
    pairs = bt.build_pairs("0000000001", dates, q1_date="2023-06-30", excluded={}, classes=_classes(dates))
    anchored = [p for p in pairs if p["mode"] == "anchored"]
    assert [(p["learn_date"], p["eval_date"]) for p in anchored] == [
        ("2023-06-30", "2023-09-30"), ("2023-06-30", "2023-12-31")]
    assert [p["gapped"] for p in anchored] == [False, False]


def test_pre_tagging_pairs_are_not_scored_but_zero_quarters_with_tagging_are():
    dates = ["2022-06-30", "2022-09-30", "2022-12-31", "2023-03-31"]
    classes = {"2022-06-30": "pre_tagging", "2022-09-30": "populated", "2022-12-31": "recogniser_format",
               "2023-03-31": "unverified_tagging"}
    pairs = bt.build_pairs("0000000001", dates, q1_date="2022-09-30", excluded={}, classes=classes)
    rolling = {(p["learn_date"], p["eval_date"]): p for p in pairs if p["mode"] == "rolling"}
    assert rolling[("2022-06-30", "2022-09-30")]["status"] == "pre_tagging"
    assert rolling[("2022-09-30", "2022-12-31")]["status"] == "evaluated"
    assert rolling[("2022-12-31", "2023-03-31")]["status"] == "evaluated"
    assert rolling[("2022-12-31", "2023-03-31")]["labels"] == ["learn:recogniser_format", "eval:unverified_tagging"]


def _census(n_positions, facts):
    contexts = [dict(id="d", dimensions=[["us-gaap:InvestmentTypeAxis", "x:LoanMember"]], typed_dimensions=[]),
                dict(id="u", dimensions=[], typed_dimensions=[])]
    return dict(summary=dict(position_observations_current=n_positions), contexts=contexts, facts=facts)


def test_quarter_classification_keys_on_recognised_positions_and_position_like_facts():
    pos_like = [dict(i=i, field="fair_value", context_id="d") for i in range(150)]
    other_dim = [dict(i=i, field=None, context_id="d") for i in range(158)]
    cover = [dict(i=i, field="document_type", context_id="u") for i in range(30)]
    assert bt.classify_quarter(_census(3, cover))["class"] == "populated"
    got = bt.classify_quarter(_census(0, pos_like))
    assert got["class"] == "recogniser_format" and got["position_like_facts"] == 150
    assert bt.classify_quarter(_census(0, cover))["class"] == "pre_tagging"
    assert bt.classify_quarter(_census(0, other_dim))["class"] == "unverified_tagging"
    undimensioned = [dict(i=i, field="fair_value", context_id="u") for i in range(150)]
    assert bt.classify_quarter(_census(0, undimensioned))["class"] == "unverified_tagging"
    assert "position_like" in bt.QUARTER_CLASS_RULE


# ---------------------------------------------------------------- positives table

def test_every_typed_positive_names_a_source_and_known_kinds():
    assert bt.TYPED_POSITIVES
    ids = set()
    for row in bt.TYPED_POSITIVES:
        assert row["positive_id"] not in ids
        ids.add(row["positive_id"])
        assert isinstance(row["source"], str) and len(row["source"]) > 10
        assert re.fullmatch(r"\d{10}", row["cik"]) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", row["date"])
        assert row["targets"] and set(row["targets"]) <= set(bt.KNOWN_KINDS)
        assert row["polarity"] == "positive" and row["check"]["type"] in bt.CHECK_TYPES
    d07 = [r for r in bt.TYPED_POSITIVES if r["category"] == "oracle_D07"]
    assert sorted((r["cik"], r["date"]) for r in d07) == [
        ("0001588272", "2024-03-31"), ("0001588272", "2024-06-30"), ("0001588272", "2024-09-30"),
        ("0001950803", "2024-12-31"), ("0001950803", "2025-12-31")]
    assert all(r["targets"] == {"value_range": ["interest_rate"]} for r in d07)
    assert [r["cik"] for r in bt.INCEPTION_ONLY] == ["0001588272"] and bt.INCEPTION_ONLY[0]["source"]


def test_fingerprint_positives_are_computed_per_consecutive_selected_accession():
    rows = [dict(cik="1950803", accession="000119312524258463", n_bare="761", n_cash="0", n_pik="18",
                 n_floor="755", n_ext_rate_facts="0"),
            dict(cik="1950803", accession="000119312525067163", n_bare="892", n_cash="899", n_pik="19",
                 n_floor="892", n_ext_rate_facts="0"),
            dict(cik="1950803", accession="000119312525119892", n_bare="1487", n_cash="1495", n_pik="35",
                 n_floor="1487", n_ext_rate_facts="0"),
            dict(cik="1950803", accession="000119312526128890", n_bare="0", n_cash="1892", n_pik="55",
                 n_floor="1891", n_ext_rate_facts="2")]
    selected = [("0001950803", "2024-09-30", "0001193125-24-258463"), ("0001950803", "2024-12-31", "0001193125-25-067163"),
                ("0001950803", "2025-03-31", "0001193125-25-119892"), ("0001950803", "2025-12-31", "0001193125-26-128890")]
    out = bt.fingerprint_positives(rows, selected)
    got = sorted((p["date"], tuple(p["targets"]["source_concept_set"])) for p in out["positives"])
    assert got == sorted([("2024-12-31", ("interest_rate",)), ("2025-12-31", ("interest_rate",)),
                          ("2025-12-31", tuple(sorted(POSITION_RATE)))])
    assert all(p["category"] == "rate_tag_fingerprint" and "rate_tag_fingerprint_by_accession.csv" in p["source"]
               for p in out["positives"])
    assert out["unmapped_selected"] == []
    out = bt.fingerprint_positives(rows[:1], selected[:2])
    assert out["positives"] == [] and out["unmapped_selected"] == [("0001950803", "2024-12-31", "0001193125-25-067163")]


def test_findings_ledger_rows_map_to_kinds_and_false_alarms_are_negative_evidence():
    rows = [dict(review_id="R1", state="real_error_unremediated", cik="0001588272", rule_name="dl_rate_fill",
                 report_date="2024-03-31"),
            dict(review_id="R2", state="adjudicated_false_alarm", cik="0001715933", rule_name="fmt_basis_spread",
                 report_date="2025-09-30"),
            dict(review_id="R3", state="remediation_staged", cik="0001588272", rule_name="fmt_pik_rate",
                 report_date="2025-12-31")]
    out = bt.ledger_positives(rows)
    by = {p["positive_id"]: p for p in out}
    assert by["ledger:R1"]["targets"] == {"fill_rate": ["interest_rate"]} and by["ledger:R1"]["polarity"] == "positive"
    assert by["ledger:R2"]["polarity"] == "recorded_negative"
    assert by["ledger:R2"]["targets"] == {"format_grammar": ["investment_identifier"], "value_range": ["basis_spread"]}
    assert by["ledger:R3"]["targets"]["value_range"] == ["pik_rate"]
    assert all("findings_ledger_post.csv" in p["source"] for p in out)


def test_recogniser_format_quarters_become_positives_scored_in_both_directions():
    out = bt.recogniser_positives({("0001588272", "2023-06-30"): dict(**{"class": "recogniser_format"},
                                                                       position_like_facts=307),
                                   ("0001588272", "2023-09-30"): {"class": "populated"}})
    assert len(out) == len(POSITION_FIELDS)   # one positive per field ("on every field")
    for p in out:
        assert p["category"] == "recogniser_format" and p["attach"] == "eval_and_learn"
        assert p["source"].startswith("B2-2a review I1") and p["date"] == "2023-06-30"
        assert sorted(p["targets"]) == ["fill_rate", "source_concept_set"]
        assert p["targets"]["fill_rate"] == p["targets"]["source_concept_set"]
    assert sorted(p["targets"]["fill_rate"][0] for p in out) == sorted(POSITION_FIELDS)


# ---------------------------------------------------------------- scoring

def _pair(pid, learn, ev, mode="rolling", status="evaluated", cik="C"):
    return dict(pair_id=pid, cik=cik, mode=mode, learn_date=learn, eval_date=ev, status=status, gapped=False)


def _res(kind, field, status, keys=()):
    return dict(kind=kind, field=field, partition_id="whole_filing", status=status, cause=None,
                violating_keys=list(keys), n_violating=len(keys))


def _pos(pid, date, targets, category="override", polarity="positive", attach="eval", cik="C"):
    return dict(positive_id=pid, cik=cik, date=date, targets=targets, category=category, polarity=polarity,
                attach=attach, source="test")


def test_scoring_detected_abstained_missed_not_covered_and_field_mismatch():
    pairs = [_pair("p1", "2024-03-31", "2024-06-30"), _pair("p2", "2024-06-30", "2024-09-30")]
    results = {
        "p1": [_res("source_concept_set", "interest_rate", "breach", ["a", "b"]),
               _res("value_range", "interest_rate", "insufficient_evidence"),
               _res("fill_rate", "pik_rate", "holds"),
               _res("fill_rate", "interest_rate", "breach", ["c"])],
        "p2": [_res("source_concept_set", "interest_rate", "holds"),
               _res("value_range", "interest_rate", "holds"),
               _res("fill_rate", "pik_rate", "breach", ["x", "y", "z"]),
               _res("fill_rate", "interest_rate", "holds")]}
    positives = [_pos("A", "2024-06-30", {"source_concept_set": ["interest_rate"], "value_range": ["interest_rate"]}),
                 _pos("B", "2024-06-30", {"scale": ["fair_value"]}),
                 _pos("C", "2024-09-30", {"source_concept_set": ["interest_rate"]}),
                 _pos("D", "2024-06-30", {"fill_rate": ["pik_rate"]})]
    s = bt.score(pairs, results, positives, mode="rolling")
    units = {(u["positive_id"], u["kind"]): u for u in s["positive_units"]}
    assert units[("A", "source_concept_set")]["outcome"] == "detected"
    assert units[("A", "value_range")]["outcome"] == "abstained"
    assert units[("B", "scale")]["outcome"] == "not_covered"
    assert units[("C", "source_concept_set")]["outcome"] == "missed"
    assert units[("C", "source_concept_set")]["field_mismatch"] == [dict(kind="fill_rate", field="pik_rate")]
    assert units[("D", "fill_rate")]["outcome"] == "missed"
    assert units[("D", "fill_rate")]["field_mismatch"] == [dict(kind="fill_rate", field="interest_rate")]
    k = s["by_kind"]["source_concept_set"]["positives"]
    assert (k["detected"], k["abstained"], k["missed"], k["field_mismatch"]) == (1, 0, 1, 1)
    assert k["recall"] == 0.5
    negatives = s["by_kind"]["fill_rate"]["negatives"]
    assert (negatives["n"], negatives["breach"], negatives["holds"]) == (3, 2, 1)
    [top] = [u for u in s["unadjudicated"] if u["pair_id"] == "p2"]
    assert (top["kind"], top["field"], top["n_violating"]) == ("fill_rate", "pik_rate", 3)
    assert s["by_kind"]["scale"]["positives"]["not_covered"] == 1


def test_rolling_attachment_spans_gapped_windows_and_learning_side_positives():
    pairs = [_pair("g", "2023-12-31", "2024-06-30"), _pair("n", "2024-06-30", "2024-09-30")]
    results = {"g": [_res("fill_rate", "interest_rate", "holds")],
               "n": [_res("fill_rate", "interest_rate", "insufficient_evidence")]}
    positives = [_pos("X", "2024-03-31", {"fill_rate": ["interest_rate"]}),
                 _pos("Z", "2024-06-30", {"fill_rate": ["interest_rate"]}, category="recogniser_format",
                      attach="eval_and_learn")]
    s = bt.score(pairs, results, positives, mode="rolling")
    got = sorted((u["positive_id"], u["pair_id"], u["outcome"]) for u in s["positive_units"])
    assert got == [("X", "g", "missed"), ("Z", "g", "missed"), ("Z", "n", "abstained")]
    s = bt.score(pairs, results, positives, mode="rolling", exclude_categories=("recogniser_format",))
    assert sorted((u["positive_id"], u["pair_id"]) for u in s["positive_units"]) == [("X", "g")]
    assert s["by_kind"]["fill_rate"]["negatives"]["n"] == 1
    assert s["by_kind"]["fill_rate"]["negatives"]["insufficient_evidence"] == 1


def test_anchored_attachment_is_exact_and_later_results_are_carried_not_negative():
    pairs = [_pair("a1", "2023-09-30", "2023-12-31", mode="anchored"),
             _pair("a2", "2023-09-30", "2024-03-31", mode="anchored")]
    results = {"a1": [_res("source_concept_set", "interest_rate", "breach", ["k"])],
               "a2": [_res("source_concept_set", "interest_rate", "breach", ["k"])]}
    positives = [_pos("P", "2023-12-31", {"source_concept_set": ["interest_rate"]})]
    s = bt.score(pairs, results, positives, mode="anchored")
    assert [(u["pair_id"], u["outcome"]) for u in s["positive_units"]] == [("a1", "detected")]
    assert s["by_kind"]["source_concept_set"]["carried"] == 1
    assert s["by_kind"]["source_concept_set"]["negatives"]["n"] == 0 and s["unadjudicated"] == []


def test_recorded_false_alarms_are_counted_apart_and_unscorable_positives_are_listed():
    pairs = [_pair("p", "2025-06-30", "2025-09-30"), _pair("q", "2022-06-30", "2022-09-30", status="pre_tagging")]
    results = {"p": [_res("value_range", "basis_spread", "breach", ["k"])]}
    positives = [_pos("F", "2025-09-30", {"value_range": ["basis_spread"]}, category="findings_ledger",
                      polarity="recorded_negative"),
                 _pos("L", "2021-12-31", {"fill_rate": ["interest_rate"]}),
                 _pos("Q", "2022-09-30", {"fill_rate": ["interest_rate"]})]
    s = bt.score(pairs, results, positives, mode="rolling")
    neg = s["by_kind"]["value_range"]["negatives"]
    assert neg["n"] == 1 and neg["recorded_negative"] == 1 and neg["recorded_negative_breach"] == 1
    assert s["unadjudicated"] == []
    assert [u["recorded_false_alarm"] for u in s["adjudicated_false_alarm_breaches"]] == [["F"]]
    assert sorted((u["positive_id"], u["reason"]) for u in s["unscorable"]) == [
        ("L", "no_evaluated_pair_covers_the_date"), ("Q", "only_pre_tagging_pairs_cover_the_date")]


# ---------------------------------------------------------------- learning and evaluation

def test_zero_position_learning_quarter_keeps_the_full_denominator_as_insufficient():
    empty = mk_doc([], date="2023-03-31")
    block = bt.learn_block(CIK, empty, tolerances=tolerances(), grammar=None, yield_ev=NO_VOTE,
                           recorded_at="2026-09-29T00:00:00Z", derive=mk_profile)
    assert len(block["contracts"]) == 57
    assert all(c["learn_status"] == "insufficient_evidence" for c in block["contracts"])
    causes = {c["learn_cause"] for c in block["contracts"] if c["kind"] != "fund_income_yield"}
    assert causes == {bt.ZERO_LEARN_CAUSE}
    q2 = mk_doc([debt(i) for i in range(60)], date="2023-06-30")
    out = contracts.evaluate_contracts(block, tolerances(), q2_doc=q2, q2_listing=dict(status="available"),
                                       grammar=None, yield_q2=NO_VOTE)
    assert len(out) == 57 and {r["status"] for r in out} == {"insufficient_evidence"}


def test_learn_block_with_positions_is_learn_contracts_with_the_derived_profile():
    doc = mk_doc([debt(i) for i in range(60)])
    block = bt.learn_block(CIK, doc, tolerances=tolerances(), grammar=None, yield_ev=NO_VOTE,
                           recorded_at="2026-09-29T00:00:00Z", derive=mk_profile)
    ref = learn(doc, yield_q1=NO_VOTE)
    strip = lambda b: [(c["contract_id"], c["learn_status"], c["learn_cause"], c["expectation"]) for c in b["contracts"]]
    assert strip(block) == strip(ref) and len(block["contracts"]) == 57


def test_slim_view_yields_the_same_income_evidence_as_the_full_census(tmp_path):
    rows = [("10.0", "2.0", "1000000")] * 5 + [("10.0", "", "1000000")] * 5
    h, inc, docs = two_quarters(rows, "275000.0")
    slims = {q: bt.slim_view(d) for q, d in docs.items()}
    with chdir(tmp_path):
        full = contracts_income.income_evidence(h, inc, cik=CIK, report_date=Q1, census_doc=docs[Q1],
                                                window=sorted(docs), window_docs=docs, cwd=lambda: chdir(tmp_path))
        slim = contracts_income.income_evidence(h, inc, cik=CIK, report_date=Q1, census_doc=slims[Q1],
                                                window=sorted(docs), window_docs=slims, cwd=lambda: chdir(tmp_path))
    assert full == slim and full["status"] == "vote"
    assert len(json.dumps(slims[Q1])) < len(json.dumps(docs[Q1]))


def test_income_window_uses_the_prior_quarter_only_when_consecutive_and_ungapped():
    assert bt.income_window("2023-06-30", prev="2023-03-31", gapped=False, min_quarters=2) == ["2023-03-31", "2023-06-30"]
    assert bt.income_window("2023-06-30", prev="2023-03-31", gapped=True, min_quarters=2) == ["2023-06-30"]
    assert bt.income_window("2023-06-30", prev=None, gapped=False, min_quarters=2) == ["2023-06-30"]


def test_the_measured_bound_is_learn_plus_evaluate_per_pair():
    assert bt.pair_timing(dict(learn_seconds=30.0), dict(evaluate_seconds=29.0), peak=100)["within_bound"] is True
    t = bt.pair_timing(dict(learn_seconds=31.0), dict(evaluate_seconds=29.5), peak=100)
    assert t["measured_seconds"] == 60.5 and t["within_bound"] is False
    assert bt.pair_timing(dict(learn_seconds=1.0), dict(evaluate_seconds=1.0), peak=3 * 2 ** 30)["within_bound"] is False


# ---------------------------------------------------------------- report

def test_recall_md_carries_the_negatives_caveat_and_is_ascii():
    pairs = [_pair("p1", "2024-03-31", "2024-06-30")]
    results = {"p1": [_res("fill_rate", "interest_rate", "breach", ["k"])]}
    scoring = bt.score_all(pairs, dict(as_evaluated=results, strict=results), [], modes=("rolling",))
    text = bt.render_recall(run_id="stageb2-backtest-test", scoring=scoring, context=dict(
        profile_mode="derived_in_memory", pairs=pairs, yields={}, timing={}, positives=[], inception_only=[],
        unscorable={}, reproduction={}, classes={}))
    assert bt.NEGATIVES_CAVEAT in text
    assert "without recogniser_format" in text
    text.encode("ascii")


# ---------------------------------------------------------------- real data through the CLI

@pytest.mark.needs_cache
def test_real_nexpoint_backtest_through_the_cli(tmp_path, monkeypatch):
    data_root = os.environ.get("PROFILE_PILOT_DATA_ROOT")
    main_root = os.environ.get("PROFILE_PILOT_MAIN_ROOT")
    if not (data_root and main_root):
        pytest.skip("PROFILE_PILOT_DATA_ROOT not set (run through the pilot launcher)")
    real_resolve = bt.resolve_paths

    def redirected(**kw):
        real = real_resolve(**kw)
        return TmpRunPaths(main_repo_root=real.main_repo_root, code_root=real.code_root,
                           data_root=real.data_root, run_id=real.run_id, tmp_run_root=tmp_path / "run")

    monkeypatch.setattr(bt, "resolve_paths", redirected)
    code = bt.main(["run", "--main-root", main_root, "--data-root", data_root,
                    "--census-run-id", "stageb2-census-20260929t094408z",
                    "--contracts-run-id", "stageb-contracts-20260929t053506z",
                    "--cik", "0001588272", "--run-id", "stageb2-backtest-test",
                    "--scratch-dir", str(tmp_path / "scratch")])
    assert code == 0
    root = tmp_path / "run"
    pairs = json.loads((root / "results" / "pairs.json").read_text(encoding="ascii"))["pairs"]
    rolling = [p for p in pairs if p["mode"] == "rolling"]
    assert len(rolling) == 12
    gapped = [p for p in rolling if p["gapped"]]
    assert [(p["learn_date"], p["eval_date"]) for p in gapped] == [("2025-09-30", "2026-03-31")]
    assert all(p["timing"]["within_bound"] for p in pairs if p["status"] == "evaluated")
    classes = json.loads((root / "results" / "pairs.json").read_text(encoding="ascii"))["quarter_classes"]
    assert classes["0001588272/2022-12-31"]["class"] == "recogniser_format"
    assert classes["0001588272/2023-06-30"]["class"] == "recogniser_format"
    built = json.loads((root / "manifest.json").read_text(encoding="ascii"))
    assert built["tolerances"]["content_sha256"] == bt.TOLERANCES_V2_SHA256
    assert all(r["source"] for r in built["positives"]["rows"])
    scoring = json.loads((root / "results" / "scoring.json").read_text(encoding="ascii"))
    assert set(scoring["scoring"]) >= {"rolling", "anchored"}
    text = (root / "results" / "recall.md").read_text(encoding="ascii")
    assert bt.NEGATIVES_CAVEAT in text
    assert list((tmp_path / "scratch").glob("backtest_recall_*.md"))
    assert list((tmp_path / "scratch").glob("backtest_unadjudicated_*.csv"))
