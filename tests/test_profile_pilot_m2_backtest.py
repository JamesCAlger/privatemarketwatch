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
    scored = [p for p in out["positives"] if p["polarity"] == "positive"]
    got = sorted((p["date"], tuple(p["targets"]["source_concept_set"])) for p in scored)
    assert got == [("2024-12-31", ("interest_rate",)), ("2025-12-31", ("interest_rate",))]
    # extension-namespace rate facts are not position concepts (review I2a): recorded, never scored
    [ext] = [p for p in out["positives"] if p["polarity"] != "positive"]
    assert ext["polarity"] == "not_a_position_event" and ext["date"] == "2025-12-31" and ext["reason"]
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
    # no v2 kind tests identifier text against the XBRL value (review I2b): covered by text_agreement (B2-3)
    [agent] = bt.ledger_positives([dict(review_id="R4", state="real_error_unremediated", cik="0001860424",
                                        rule_name="agentA_spread_vs_xbrl", report_date="2025-12-31")])
    assert agent["polarity"] == "positive" and "text_agreement" in agent["not_covered_kinds"]["value_range"]
    assert by["ledger:R1"].get("not_covered_reason") is None


def test_bcred_comparative_period_spread_row_is_a_coverage_gap_not_a_scale_positive():
    [row] = [r for r in bt.TYPED_POSITIVES if r["positive_id"] == "semantic:0001803498:basis_spread_scale"]
    assert row["category"] == "comparative_period_coverage_gap" and row["expect"] == "not_covered"
    assert "comparative facts" in row["not_covered_reason"] and "current positions" in row["not_covered_reason"]


def test_a_not_covered_row_scores_not_covered_and_leaves_its_results_as_negatives():
    pairs = [_pair("p", "2025-09-30", "2025-12-31")]
    results = {"p": [_res("format_grammar", "investment_identifier", "breach", ["k"]),
                     _res("value_range", "basis_spread", "holds")]}
    row = dict(_pos("G", "2025-12-31", {"format_grammar": ["investment_identifier"], "value_range": ["basis_spread"]}),
               not_covered_reason="no v2 kind")
    s = bt.score(pairs, results, [row], mode="rolling")
    assert sorted((u["kind"], u["outcome"]) for u in s["positive_units"]) == [
        ("format_grammar", "not_covered"), ("value_range", "not_covered")]
    assert s["by_kind"]["format_grammar"]["negatives"]["breach"] == 1 and len(s["unadjudicated"]) == 1
    assert s["by_kind"]["format_grammar"]["negatives"]["breach_rate_of_decided"] == 1.0


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
    assert len(block["contracts"]) == 59
    assert all(c["learn_status"] == "insufficient_evidence" for c in block["contracts"])
    causes = {c["learn_cause"] for c in block["contracts"] if c["kind"] != "fund_income_yield"}
    assert causes == {bt.ZERO_LEARN_CAUSE}
    q2 = mk_doc([debt(i) for i in range(60)], date="2023-06-30")
    out = contracts.evaluate_contracts(block, tolerances(), q2_doc=q2, q2_listing=dict(status="available"),
                                       grammar=None, yield_q2=NO_VOTE)
    assert len(out) == 59 and {r["status"] for r in out} == {"insufficient_evidence"}
    assert not any(r["newly_abstained"] for r in out)          # never learned: a carried abstention


def test_learn_block_with_positions_is_learn_contracts_with_the_derived_profile():
    doc = mk_doc([debt(i) for i in range(60)])
    block = bt.learn_block(CIK, doc, tolerances=tolerances(), grammar=None, yield_ev=NO_VOTE,
                           recorded_at="2026-09-29T00:00:00Z", derive=mk_profile)
    ref = learn(doc, yield_q1=NO_VOTE)
    strip = lambda b: [(c["contract_id"], c["learn_status"], c["learn_cause"], c["expectation"]) for c in b["contracts"]]
    assert strip(block) == strip(ref) and len(block["contracts"]) == 59


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


# ================================================================ Task B2-3: semantic kinds in the back-test

from scripts.profile_pilot import m2_seed  # noqa: E402

COMP, TEXT = contracts.COMPOSITION_FIELD, contracts.TEXT_FIELD


def test_zero_position_learning_quarter_under_v3_keeps_the_semantic_contracts_in_the_denominator():
    empty = mk_doc([], date="2023-03-31")
    block = bt.learn_block(CIK, empty, tolerances=tolerances(), grammar=None, yield_ev=NO_VOTE,
                           recorded_at="2026-09-29T00:00:00Z", derive=mk_profile)
    assert len(block["contracts"]) == 59
    assert [c["kind"] for c in block["contracts"][-2:]] == ["rate_composition", "text_agreement"]
    assert {c["learn_cause"] for c in block["contracts"][-2:]} == {bt.ZERO_LEARN_CAUSE}
    v2 = bt.learn_block(CIK, empty, tolerances=contracts.tolerance_content_v2(), grammar=None, yield_ev=NO_VOTE,
                        recorded_at="2026-09-29T00:00:00Z", derive=mk_profile)
    assert len(v2["contracts"]) == 57 and v2["contracts"] == block["contracts"][:57]


def test_agenta_rows_are_covered_by_text_agreement_and_not_by_the_v2_kinds():
    [agent] = bt.ledger_positives([dict(review_id="R4", state="real_error_unremediated", cik="0001860424",
                                        rule_name="agentA_spread_vs_xbrl", report_date="2025-12-31")])
    assert agent["targets"]["text_agreement"] == [TEXT] and agent["expect"] == "covered"
    assert set(agent["not_covered_kinds"]) == {"format_grammar", "value_range"}
    pairs = [_pair("p", "2025-09-30", "2025-12-31", cik="0001860424")]
    results = {"p": [_res("format_grammar", "investment_identifier", "breach", ["k"]),
                     _res("value_range", "basis_spread", "holds"), _res("text_agreement", TEXT, "breach", ["k"])]}
    s = bt.score(pairs, results, [agent], mode="rolling")
    got = sorted((u["kind"], u["outcome"]) for u in s["positive_units"])
    assert got == [("format_grammar", "not_covered"), ("text_agreement", "detected"), ("value_range", "not_covered")]
    assert s["by_kind"]["format_grammar"]["negatives"]["breach"] == 1


def test_scoring_splits_abstentions_into_newly_and_carried():
    pairs = [_pair("p1", "2024-03-31", "2024-06-30"), _pair("p2", "2024-06-30", "2024-09-30")]
    results = {"p1": [dict(_res("fill_rate", "interest_rate", "insufficient_evidence"), newly_abstained=True),
                      dict(_res("scale", "interest_rate", "insufficient_evidence"), newly_abstained=True)],
               "p2": [dict(_res("fill_rate", "interest_rate", "insufficient_evidence"), newly_abstained=False),
                      dict(_res("scale", "interest_rate", "insufficient_evidence"), newly_abstained=False)]}
    positives = [_pos("Z", "2024-06-30", {"fill_rate": ["interest_rate"]}, category="recogniser_format",
                      attach="eval_and_learn")]
    s = bt.score(pairs, results, positives, mode="rolling")
    pos = s["by_kind"]["fill_rate"]["positives"]
    assert (pos["abstained"], pos["abstained_newly"], pos["abstained_carried"]) == (2, 1, 1)
    neg = s["by_kind"]["scale"]["negatives"]
    assert (neg["insufficient_evidence"], neg["insufficient_newly"]) == (2, 1)


def _grid_res(cid, kind, status, criteria=None, keys=()):
    return [cid, kind, status, None, criteria, list(keys)]


def test_semantic_negatives_count_criterion_breaches_per_candidate_band_and_skip_targeted_results():
    grid = [dict(name="c:s5_f10", family="composition", share_pp=5, fixed_share_pp=10, text_share_pp=10),
            dict(name="c:s10_f10", family="composition", share_pp=10, fixed_share_pp=10, text_share_pp=10),
            dict(name="t:10", family="text", share_pp=10, fixed_share_pp=10, text_share_pp=10)]
    pairs = [_pair("p", "2024-03-31", "2024-06-30"), _pair("q", "2024-06-30", "2024-09-30", cik="D")]
    grid_results = {
        "p": {"c:s5_f10": [_grid_res("C:rc", "rate_composition", "breach", dict(share="breach", fixed="holds"), ["a"])],
              "c:s10_f10": [_grid_res("C:rc", "rate_composition", "holds", dict(share="holds", fixed="holds"))],
              "t:10": [_grid_res("C:ta", "text_agreement", "breach", None, ["b"])]},
        "q": {"c:s5_f10": [_grid_res("D:rc", "rate_composition", "insufficient_evidence")],
              "c:s10_f10": [_grid_res("D:rc", "rate_composition", "insufficient_evidence")],
              "t:10": [_grid_res("D:ta", "text_agreement", "breach", None, ["z"])]}}
    tiers = {"p": "standard", "q": "low_history"}
    positives = [_pos("T", "2024-09-30", {"text_agreement": [TEXT]}, cik="D")]
    out = bt.semantic_negatives(pairs, grid_results, positives, grid=grid, tiers=tiers)
    share5 = out["share_pp"]["5"]
    assert (share5["all"]["n"], share5["all"]["breach"], share5["all"]["insufficient_evidence"]) == (2, 1, 1)
    assert share5["standard"]["breach_rate_upper_bound"] == 1.0 and share5["low_history"]["breach"] == 0
    assert out["share_pp"]["10"]["all"]["breach"] == 0
    text = out["text_share_pp"]["10"]["all"]
    assert (text["n"], text["breach"]) == (1, 1)                      # D's text result is a targeted positive
    assert [u["pair_id"] for u in out["text_share_pp"]["10"]["unadjudicated"]] == ["p"]
    assert out["text_share_pp"]["10"]["positives"] == dict(units=1, detected=1, abstained=0, missed=0)


def test_choose_band_takes_the_smallest_value_meeting_both_criteria_or_marks_it_uncalibrated():
    curve = [dict(value=5, detection=0.05, neg_rate=0.20), dict(value=10, detection=0.10, neg_rate=0.08),
             dict(value=15, detection=0.20, neg_rate=0.05), dict(value=20, detection=0.5, neg_rate=0.01)]
    out = bt.choose_band(curve)
    assert out["chosen"] == 10 and out["status"] == "calibrated" and "in-sample" in out["label"]
    none = bt.choose_band([dict(value=5, detection=0.05, neg_rate=0.2), dict(value=10, detection=None, neg_rate=0.0),
                           dict(value=15, detection=0.5, neg_rate=0.0)])
    assert none["chosen"] is None and none["status"] == "uncalibrated" and len(none["curve"]) == 3
    assert bt.choose_band([dict(value=5, detection=0.3, neg_rate=0.10)])["chosen"] == 5


def test_median_shift_negatives_and_positives_per_candidate():
    pairs = [_pair("p", "2024-03-31", "2024-06-30")]
    ms = {"p": {"C:vr:interest_rate": {"x0.1_y0.05": "breach", "x0.25_y0.1": "holds"},
                "C:vr:basis_spread": {"x0.1_y0.05": "holds", "x0.25_y0.1": "holds"}}}
    fields = {"C:vr:interest_rate": "interest_rate", "C:vr:basis_spread": "basis_spread"}
    positives = [_pos("D07", "2024-06-30", {"value_range": ["interest_rate"]}, category="oracle_D07")]
    out = bt.median_shift_scores(pairs, ms, positives, fields=fields)
    assert out["x0.1_y0.05"]["negatives"] == dict(n=1, breach=0, insufficient_evidence=0, breach_rate_upper_bound=0.0)
    assert out["x0.1_y0.05"]["positives"] == dict(units=1, detected=1, abstained=0, missed=0)
    assert out["x0.25_y0.1"]["positives"]["missed"] == 1


def _seed_body(comp_det=lambda s, i: 0.1):
    cell = lambda det: dict(median=dict(all=det, standard=det, low_history=None),
                            detected=dict(all=1, standard=1, low_history=0), applicable=dict(all=1, standard=1,
                                                                                             low_history=0))
    curves = {"share_pp": {str(v): {"spread_for_coupon": cell(v / 100.0), "bps_spread_scale": cell(None)}
                           for v in m2_seed.CANDIDATES["share_pp"]},
              "fixed_share_pp": {str(v): {"spread_for_coupon": cell(None)}
                                 for v in m2_seed.CANDIDATES["fixed_share_pp"]},
              "text_share_pp": {str(v): {"text_numeric_divergence": cell(0.05)}
                                for v in m2_seed.CANDIDATES["text_share_pp"]},
              "composition_status": {"c:s%s_f%s" % (s, f): {"spread_for_coupon": cell(comp_det(s, f))}
                                     for s in m2_seed.CANDIDATES["share_pp"]
                                     for f in m2_seed.CANDIDATES["fixed_share_pp"]}}
    ms = {"range_shift_0.6": {name: dict(median=dict(all=0.1)) for name in ["v2_band"] + [
        m2_seed.ms_name(x, y) for x in m2_seed.MEDIAN_SHIFT["x"] for y in m2_seed.MEDIAN_SHIFT["y"]]}}
    return dict(label=m2_seed.IN_SAMPLE, curves=curves, median_shift=ms)


def _negatives(comp_rate, text_rate=lambda t: 0.2):
    def cell(rate, std=None):
        std = rate if std is None else std
        return dict(all=dict(n=100, breach=int(rate * 100), insufficient_evidence=0, breach_rate_upper_bound=rate),
                    standard=dict(n=80, breach=int(std * 80), insufficient_evidence=0, breach_rate_upper_bound=std),
                    low_history=dict(n=20, breach=0, insufficient_evidence=0, breach_rate_upper_bound=0.0),
                    unadjudicated=[], positives=dict(units=0, detected=0, abstained=0, missed=0))
    out = {"share_pp": {str(v): cell(0.02) for v in m2_seed.CANDIDATES["share_pp"]},
           "fixed_share_pp": {str(v): cell(0.01) for v in m2_seed.CANDIDATES["fixed_share_pp"]},
           "text_share_pp": {str(v): cell(text_rate(v)) for v in m2_seed.CANDIDATES["text_share_pp"]}}
    out["composition_status"] = {"c:s%s_f%s" % (s, f): cell(comp_rate(s, f), std=0.5)
                                 for s in m2_seed.CANDIDATES["share_pp"] for f in m2_seed.CANDIDATES["fixed_share_pp"]}
    return out


def _ms():
    return {m2_seed.ms_name(x, y): dict(negatives=dict(n=10, breach=1, insufficient_evidence=0,
                                                       breach_rate_upper_bound=0.1),
                                        positives=dict(units=1, detected=1, abstained=0, missed=0))
            for x in m2_seed.MEDIAN_SHIFT["x"] for y in m2_seed.MEDIAN_SHIFT["y"]}


SCORING = {"rolling": {"as_evaluated": {"all": {"by_kind": {"value_range": {"negatives": dict(
    breach_rate_upper_bound=0.061)}}}}}}


def test_calibration_binds_to_the_contract_status_on_the_joint_grid_with_one_pooled_basis():
    # criteria alone would pass at s5; the CONTRACT (either criterion) only passes from s15_f20 on
    comp = lambda s, f: 0.05 if (s, f) in ((15, 20), (15, 25), (20, 10), (25, 5)) else 0.12
    cal = bt.assemble_calibration(_seed_body(), _negatives(comp, text_rate=lambda t: 0.08), _ms(), SCORING,
                                  seed_run_id="stageb2-seed-v3-x")
    assert cal["tier_basis"] == "pooled"
    joint = cal["bands"]["rate_composition"]
    assert joint["status"] == "calibrated" and joint["chosen"] == dict(share_pp=15, fixed_share_pp=20)
    assert [r["value"] for r in joint["curve"]][:3] == ["s5_f5", "s5_f10", "s5_f15"] and len(joint["curve"]) == 25
    row = next(r for r in joint["curve"] if r["value"] == "s15_f20")
    assert row["neg_rate"] == 0.05 and row["per_criterion"] == dict(share=0.02, fixed=0.01)
    assert cal["bands"]["text_share_pp"]["chosen"] == 5 and cal["bands"]["text_share_pp"]["detection_tier"] == "all"
    assert set(cal["criteria"]) == {"share_pp", "fixed_share_pp"}
    block = cal["tolerances_block"]
    assert block["tier_basis"] == "pooled" and block["bands"]["rate_composition"]["chosen"] == dict(
        share_pp=15, fixed_share_pp=20)
    assert block["bands"]["rate_composition"]["curve"][0]["negatives_breach_rate_per_criterion"] == dict(
        share=0.02, fixed=0.01)
    assert block["bands"]["rate_composition"]["curve"][0]["share_pp"] == 5
    json.dumps(block).encode("ascii")


def test_calibration_marks_the_contract_uncalibrated_when_no_joint_point_meets_the_rule():
    cal = bt.assemble_calibration(_seed_body(comp_det=lambda s, i: 0.5), _negatives(lambda s, i: 0.05), _ms(), SCORING,
                                  seed_run_id="x")
    assert cal["bands"]["rate_composition"]["status"] == "uncalibrated"
    assert cal["bands"]["rate_composition"]["chosen"] is None and len(cal["bands"]["rate_composition"]["curve"]) == 25
    assert cal["bands"]["text_share_pp"]["status"] == "uncalibrated"             # every negatives rate 20%
    sem = dict(run_id="r", negatives=dict(rolling=_negatives(lambda s, i: 0.05)),
               newly_abstained=dict(totals=dict(newly=1, carried=2), recogniser_format_units=dict(newly=1, carried=0),
                                    x100_magnitude_causes=dict(newly=0, carried=0), by_kind={}),
               inception={"C": {"2023-03-31": [dict(kind="rate_composition", learn_status="learned", learn_cause=None,
                                                    inception=dict(share_rate_le_spread=0.0))]}})
    text = bt.render_semantic(sem, cal)
    assert m2_seed.IN_SAMPLE in text and "NOT adopted" in text and "uncalibrated" in text
    text.encode("ascii")


def test_newly_abstained_summary_splits_by_kind_recogniser_units_and_x100_causes():
    pairs = [_pair("p", "2024-03-31", "2024-06-30"), _pair("a", "2023-03-31", "2024-06-30", mode="anchored")]
    results = {"p": [dict(_res("scale", "interest_rate", "insufficient_evidence"), newly_abstained=True,
                          cause="magnitude_regime_changed_under_same_declared_unit"),
                     dict(_res("fill_rate", "interest_rate", "insufficient_evidence"), newly_abstained=False),
                     dict(_res("fill_rate", "pik_rate", "holds"), newly_abstained=False)],
               "a": [dict(_res("scale", "interest_rate", "insufficient_evidence"), newly_abstained=True)]}
    scoring = {"rolling": {"as_evaluated": {"all": {"positive_units": [
        dict(category="recogniser_format", outcome="abstained", abstained="newly"),
        dict(category="recogniser_format", outcome="abstained", abstained="carried"),
        dict(category="override", outcome="abstained", abstained="newly")]}}}}
    out = bt.newly_abstained_summary(pairs, results, scoring)
    assert out["totals"] == dict(newly=1, carried=1)
    assert out["by_kind"] == {"fill_rate": dict(newly=0, carried=1), "scale": dict(newly=1, carried=0)}
    assert out["x100_magnitude_causes"] == dict(newly=1, carried=0)
    assert out["recogniser_format_units"] == dict(newly=1, carried=1)


@pytest.mark.needs_cache
def test_real_nexpoint_semantic_backtest_through_the_cli(tmp_path, monkeypatch):
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
                    "--cik", "0001588272", "--run-id", "stageb2-backtest-v3-test", "--semantic",
                    "--tolerances-version", "3",
                    "--scratch-dir", str(tmp_path / "scratch")])
    assert code == 0
    root = tmp_path / "run"
    sem = json.loads((root / "results" / "semantic.json").read_text(encoding="ascii"))
    assert sem["label"] == m2_seed.IN_SAMPLE and set(sem["negatives"]["rolling"]) >= {"share_pp", "text_share_pp"}
    assert "0001588272" in sem["inception"] and sem["newly_abstained"]["totals"]["newly"] > 0
    pairs = json.loads((root / "results" / "pairs.json").read_text(encoding="ascii"))["pairs"]
    assert all(p["timing"]["within_bound"] for p in pairs if p["status"] == "evaluated")
    results = json.loads((root / "results" / "backtest_results.json").read_text(encoding="ascii"))["results"]
    assert all(len(v) == 59 for v in results.values())
    (root / "results" / "backtest_semantic.md").read_text(encoding="ascii")


def test_the_bcred_fixed_coupon_pairs_are_adjudicated_positives_with_their_source():
    rows = [r for r in bt.TYPED_POSITIVES if r["category"] == "fixed_coupon_in_spread"]
    assert sorted((r["cik"], r["date"]) for r in rows) == [("0001803498", "2022-12-31"), ("0001803498", "2023-03-31")]
    for r in rows:
        assert r["targets"] == {"rate_composition": [contracts.COMPOSITION_FIELD]} and r["expect"] == "covered"
        assert "B2-3 review round 0: census verification, 151 current-period rows, two separate facts, 141 new " \
               "fixed-rate bonds" in r["source"] and "R39" in r["source"]
        assert r["check"]["type"] == "doc_line"
    pairs = [_pair("b", "2022-09-30", "2022-12-31", cik="0001803498")]
    results = {"b": [_res("rate_composition", contracts.COMPOSITION_FIELD, "breach", ["k"])]}
    s = bt.score(pairs, results, rows, mode="rolling")
    assert [u["outcome"] for u in s["positive_units"]] == ["detected"]
    assert s["by_kind"]["rate_composition"]["negatives"]["n"] == 0


# ---------------------------------------------------------------- pre-registered independent_totals ledger map

def test_totals_and_identity_rules_map_to_independent_totals_fields():
    from scripts.profile_pilot import m2_backtest as bt
    assert bt.LEDGER_RULES["fv_conservation"] == {"independent_totals": ["fair_value"]}
    assert bt.LEDGER_RULES["cost_conservation"] == {"independent_totals": ["fair_value"]}
    assert bt.LEDGER_RULES["A04"] == {"independent_totals": ["fair_value"]}
    assert bt.LEDGER_RULES["E01"] == {"independent_totals": ["fair_value"]}
    assert bt.LEDGER_RULES["A07"] == {"independent_totals": ["pct_of_net_assets"]}
    assert bt.LEDGER_RULES["pct_of_net_assets_identity"] == {"independent_totals": ["pct_of_net_assets"]}
    assert bt.LEDGER_MAP_VERSION == "sp1-2026-09-30"
    # the five v2/v3 rules are untouched
    assert bt.LEDGER_RULES["dl_rate_fill"] == {"fill_rate": ["interest_rate"]}


def test_ledger_exclusions_list_every_unscored_row_with_a_reason():
    from scripts.profile_pilot import m2_backtest as bt
    rows = [
        dict(review_id="r1", state="open", verdict_status="MISSING", cik="0001287750", rule_name="A07", report_date="2026-03-31"),
        dict(review_id="r2", state="needs_human", verdict_status="verdict_ESCALATE", cik="0001287750", rule_name="fv_conservation", report_date="2025-12-31"),
        dict(review_id="r3", state="real_error_unremediated", verdict_status="verdict_real_error", cik="0001287750", rule_name="A07", report_date="2026-03-31"),
        dict(review_id="r4", state="real_error_unremediated", verdict_status="verdict_real_error", cik="0001287750", rule_name="nonaccrual_x", report_date="2026-03-31"),
        dict(review_id="r5", state="real_error_unremediated", verdict_status="verdict_real_error", cik="0009999999", rule_name="A07", report_date="2026-03-31"),
    ]
    out = bt.ledger_exclusions(rows, ciks={"0001287750"}, dates={"2025-12-31", "2026-03-31"})
    by_id = {o["review_id"]: o["reason"] for o in out}
    assert by_id == {"r1": "state_not_adjudicated:open", "r2": "state_not_adjudicated:needs_human",
                     "r4": "rule_not_mapped:nonaccrual_x"}
    # r3 is scored (not excluded); r5 is outside the cohort and not listed


# ---------------------------------------------------------------- Task 4 (sp1): independent_totals wiring

def test_tolerances_version_defaults_to_4_under_semantic_and_2_otherwise():
    assert bt.resolve_tolerances_version(None, semantic=True) == 4
    assert bt.resolve_tolerances_version(None, semantic=False) == 2
    assert bt.resolve_tolerances_version(3, semantic=True) == 3
    with pytest.raises(bt.StageInvalidated):
        bt.resolve_tolerances_version(2, semantic=True)
    with pytest.raises(bt.StageInvalidated):
        bt.resolve_tolerances_version(5, semantic=False)


def test_learning_tolerances_derive_v3_and_v4_in_memory_from_the_frozen_v2():
    v2 = contracts.tolerance_content_v2()
    assert bt.learning_tolerances(v2, 2) is v2
    v3 = bt.learning_tolerances(v2, 3)
    v4 = bt.learning_tolerances(v2, 4)
    assert v3["version"] == contracts.TOLERANCES_VERSION and v3["v2_verbatim"] == v2
    assert v4 == contracts.tolerance_content_v4(v3)


def test_zero_position_learning_quarter_under_v4_adds_the_two_totals_contracts():
    empty = mk_doc([], date="2023-03-31")
    v4 = bt.learning_tolerances(contracts.tolerance_content_v2(), 4)
    block = bt.learn_block(CIK, empty, tolerances=v4, grammar=None, yield_ev=NO_VOTE,
                           recorded_at="2026-09-29T00:00:00Z", derive=mk_profile, financials=None)
    assert len(block["contracts"]) == 61
    assert [(c["kind"], c["field"]) for c in block["contracts"][-2:]] == [
        ("independent_totals", bt.TOTALS_FIELD), ("independent_totals", bt.PCT_FIELD)]
    assert all(c["learn_status"] == "insufficient_evidence" for c in block["contracts"])
    v3 = bt.learn_block(CIK, empty, tolerances=bt.learning_tolerances(contracts.tolerance_content_v2(), 3),
                        grammar=None, yield_ev=NO_VOTE, recorded_at="2026-09-29T00:00:00Z", derive=mk_profile)
    assert len(v3["contracts"]) == 59


def test_trim_keeps_status_basis_only_where_the_result_carries_it():
    base = dict(contract_id="x", kind="scale", field="interest_rate", partition_id="whole_filing", status="holds",
                cause=None, violating_keys=[], expected=None, observed=None, identifier_format_unresolved=False,
                q2=dict(form_type="10-Q"))
    assert "status_basis" not in bt._trim(base)
    assert bt._trim(dict(base, kind="independent_totals", status_basis="provisional"))["status_basis"] == "provisional"


# ---------------------------------------------------------------- Task 6b (sp1): contracts roots frozen under v4

def test_backtest_pins_a_v4_root_and_refuses_a_mismatched_inventory(tmp_path):
    from tests.test_profile_pilot_m2_seed import _v4, contracts_root
    tol, tol_rec, _, _ = m2_seed.pin_frozen_tolerances(contracts_root(tmp_path / "a", _v4()))
    assert tol_rec["version"] == 4
    with pytest.raises(bt.StageInvalidated, match="frozen against other tolerances"):
        m2_seed.pin_frozen_tolerances(contracts_root(tmp_path / "b", _v4(),
                                                     inventory_tol_sha=bt.TOLERANCES_V2_SHA256))


def test_learning_tolerances_under_a_v4_root_equal_the_pinned_v4():
    from tests.test_profile_pilot_m2_seed import _v4
    pinned = _v4()
    assert bt.learning_tolerances(pinned, 4) == pinned
    v2 = pinned["v3_verbatim"]["v2_verbatim"]
    assert bt.learning_tolerances(pinned, 2) is v2
    assert bt.learning_tolerances(pinned, 3)["v2_verbatim"] == v2
    drifted = _v4()
    drifted["bands"]["standard"]["independent_totals"]["fv_residual_pct"] = 6.0
    with pytest.raises(bt.StageInvalidated, match="in-memory v4"):
        bt.learning_tolerances(drifted, 4)
