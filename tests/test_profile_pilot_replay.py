import csv, io
from scripts.profile_pilot import replay_report as rr

LEDGER_HEADER = ("review_id,state,in_queue,population_origin,verdict_status,verdict_detail,has_fix_route,cik,"
                 "rule_name,report_date,lane,engine,fv_at_risk_m,fund_quarter_fv_m")


def _pair(cik, learn, ev, gapped=False):
    return dict(pair_id="rolling:" + cik + ":" + learn + ":" + ev, cik=cik, mode="rolling", learn_date=learn,
                eval_date=ev, gapped=gapped, gap_reasons=[], status="evaluated", labels=[])


def test_select_q4_q1_pair_per_cik_and_flag_gapped_ones():
    pairs = [_pair("A", "2025-12-31", "2026-03-31"), _pair("A", "2025-09-30", "2025-12-31"),
             _pair("B", "2025-09-30", "2026-03-31", gapped=True)]
    chosen = rr.select_pairs(pairs, eval_date="2026-03-31")
    assert chosen["A"]["learn_date"] == "2025-12-31" and chosen["A"]["gapped"] is False
    assert chosen["B"]["gapped"] is True


def test_structural_floor_passes_at_recall_90_and_fp_2_and_fails_below():
    assert rr.floor_verdict("fill_rate", dict(pos_units=10, detected=9, abstained=0, missed=1, neg_n=100,
                                              adjudicated_false_alarm_breaches=1, unadjudicated_breaches=1)) == "PASS"
    assert rr.floor_verdict("fill_rate", dict(pos_units=10, detected=8, abstained=1, missed=1, neg_n=100,
                                              adjudicated_false_alarm_breaches=0, unadjudicated_breaches=0)) == "FAIL"
    assert rr.floor_verdict("fill_rate", dict(pos_units=0, detected=0, abstained=0, missed=0, neg_n=5,
                                              adjudicated_false_alarm_breaches=0, unadjudicated_breaches=0)) == "NO_POSITIVES"
    assert rr.floor_verdict("value_range", dict(pos_units=3, detected=0, abstained=0, missed=3, neg_n=5,
                                                adjudicated_false_alarm_breaches=0, unadjudicated_breaches=0)) == "NOT_CLAIMED"


def test_totals_floor_uses_the_seed_sensitivity():
    ok = _seeded({c: _frow() for c in "ABCDE"})[rr.TOTALS_KIND]
    assert rr.totals_verdict(ok) == "PASS"
    four = _seeded(dict({c: _frow() for c in "ABCD"}, E=_frow(smallest=None, reason="not_detected_at_1.0")))
    assert rr.totals_verdict(four[rr.TOTALS_KIND]) == "FAIL"
    assert rr.totals_verdict(_seeded({c: _frow(smallest=0.3) for c in "ABCDE"})[rr.TOTALS_KIND]) == "FAIL"


def test_drift_queue_has_the_ledger_header_and_ranks_by_fv_at_risk():
    results = {"rolling:A:2025-12-31:2026-03-31": [
        dict(contract_id="A:fill_rate:interest_rate:whole_filing", kind="fill_rate", field="interest_rate",
             partition_id="whole_filing", status="breach", cause="fill_dropped", n_violating=2,
             violating_keys=["c1", "c2"], newly_abstained=False),
        dict(contract_id="A:scale:pik_rate:whole_filing", kind="scale", field="pik_rate", partition_id="whole_filing",
             status="insufficient_evidence", cause="unresolved_unit", n_violating=0, violating_keys=[], newly_abstained=True),
        dict(contract_id="A:scale:interest_rate:whole_filing", kind="scale", field="interest_rate",
             partition_id="whole_filing", status="holds", cause=None, n_violating=0, violating_keys=[], newly_abstained=False)]}
    fv = {("A", "2026-03-31"): dict(total=80_000_000.0, by_key={"c1": 5_000_000.0, "c2": 1_000_000.0})}
    text = rr.drift_queue_csv(results, pairs={"A": _pair("A", "2025-12-31", "2026-03-31")}, fv_by_quarter=fv)
    rows = list(csv.DictReader(io.StringIO(text)))
    assert text.splitlines()[0].startswith(LEDGER_HEADER)
    assert [r["rule_name"] for r in rows] == ["drift:fill_rate", "drift:scale"]
    assert rows[0]["fv_at_risk_m"] == "6.0" and rows[0]["fund_quarter_fv_m"] == "80.0"
    assert rows[0]["state"] == "open" and rows[0]["lane"] == "drift" and rows[0]["engine"] == "profile_contracts"
    assert rows[1]["cause"] == "unresolved_unit"


def test_totals_rows_carry_a_real_fv_at_risk_and_rank_by_it():
    pid = "rolling:A:2025-12-31:2026-03-31"
    results = {pid: [
        dict(contract_id="A:fill_rate:interest_rate:whole_filing", kind="fill_rate", field="interest_rate",
             partition_id="whole_filing", status="breach", cause="fill_dropped", n_violating=2,
             violating_keys=["c1", "c2"], newly_abstained=False),
        dict(contract_id="A:independent_totals:fair_value:whole_filing", kind="independent_totals",
             field="fair_value", partition_id="whole_filing", status="breach", cause="fv_residual_outside_band",
             n_violating=0, violating_keys=[], newly_abstained=False,
             observed=dict(fv_sum=88_600_000_000.0, fv_anchor=80_900_000_000.0), expected=dict()),
        dict(contract_id="A:independent_totals:pct_of_net_assets:whole_filing", kind="independent_totals",
             field="pct_of_net_assets", partition_id="whole_filing", status="breach", cause="pct_sum_shifted",
             n_violating=0, violating_keys=[], newly_abstained=False,
             observed=dict(pct_sum=120.0), expected=dict(pct_sum_q1=100.0))]}
    fv = {("A", "2026-03-31"): dict(total=80_000_000.0, by_key={"c1": 5_000_000.0, "c2": 1_000_000.0})}
    text = rr.drift_queue_csv(results, pairs={"A": _pair("A", "2025-12-31", "2026-03-31")}, fv_by_quarter=fv)
    rows = list(csv.DictReader(io.StringIO(text)))
    assert text.splitlines()[0].startswith(LEDGER_HEADER)
    assert [(r["field"], r["fv_at_risk_m"]) for r in rows] == [
        ("fair_value", "7700.0"), ("pct_of_net_assets", "16.0"), ("interest_rate", "6.0")]


def test_totals_fv_at_risk_is_zero_when_an_input_is_missing():
    fv = dict(total=80_000_000.0, by_key={})
    base = dict(kind="independent_totals", status="breach")
    assert rr.fv_at_risk(dict(base, field="fair_value", observed=dict(fv_sum=1.0, fv_anchor=None)), keys=[], fv=fv) == 0.0
    assert rr.fv_at_risk(dict(base, field="pct_of_net_assets", observed=dict(pct_sum=120.0), expected=None),
                         keys=[], fv=fv) == 0.0


# ---------------------------------------------------------------- totals floor (controller ruling 2026-10-01)

def _seeded(per_cik_fv: dict, per_cik_pct: dict | None = None) -> dict:
    def variant(field, per):
        return dict(field=field, median_smallest_detected=None, detected_ciks=0, applicable_ciks=0, per_cik=per)
    return {rr.TOTALS_KIND: dict(floor_variant=rr.TOTALS_VARIANT, note=rr.TOTALS_SEED_NOTE, variants={
        rr.TOTALS_VARIANT: variant("fair_value", per_cik_fv),
        "pct_scale_flip": variant("pct_of_net_assets", per_cik_pct or {})})}


def _frow(anchored=True, applicable=True, smallest=0.05, reason="measured"):
    return dict(anchored=anchored, applicable=applicable, smallest_detected=smallest, reason=reason)


def test_totals_floor_denominator_is_every_anchored_filer():
    one_of_two = _seeded({"A": _frow(), "B": _frow(applicable=False, smallest=None,
                                                   reason="baseline_out_of_band:fv_residual_outside_band")})
    assert rr.totals_verdict(one_of_two[rr.TOTALS_KIND]) == "FAIL"
    m = rr.totals_measured(one_of_two[rr.TOTALS_KIND])
    assert m["detected_over_anchored"] == "1/2" and m["not_detected"] == {
        "B": "baseline_out_of_band:fv_residual_outside_band"}
    # an unanchored filer is outside the denominator
    ok = _seeded({"A": _frow(), "C": _frow(anchored=False, applicable=False, smallest=None, reason="no_anchor")})
    assert rr.totals_verdict(ok[rr.TOTALS_KIND]) == "PASS"
    # detected, but only above the 0.20 floor
    late = _seeded({"A": _frow(smallest=0.3)})
    assert rr.totals_verdict(late[rr.TOTALS_KIND]) == "FAIL"


def test_totals_floor_with_no_anchored_filer_is_no_anchors_not_pass():
    none = _seeded({"A": _frow(anchored=False, applicable=False, smallest=None, reason="no_anchor")})
    assert rr.totals_verdict(none[rr.TOTALS_KIND]) == "NO_ANCHORS"
    per_kind = {rr.TOTALS_KIND: dict(recall=None, false_alarm_rate=None, pos_units=0, neg_n=0)}
    assert rr.floors(per_kind, none)[rr.TOTALS_KIND]["verdict"] == "NO_ANCHORS"
    assert rr.floors(per_kind, {})[rr.TOTALS_KIND]["verdict"] == "FAIL"


def test_seeded_cells_carry_per_filer_reasons_for_both_variants():
    def cik_cell(applicable, smallest, reason=None):
        return dict(applicable=applicable, smallest_detected=smallest, reason=reason)
    held_not = "contract does not hold in the null control"
    sens = dict(cells={
        rr.TOTALS_VARIANT: {rr.TOTALS_KIND: dict(median_smallest_detected=0.05, detected_ciks=1, applicable_ciks=1,
                                                 per_cik={"A": cik_cell(True, 0.05),
                                                          "B": cik_cell(False, None, held_not)})},
        "pct_scale_flip": {rr.TOTALS_KIND: dict(median_smallest_detected=None, detected_ciks=0, applicable_ciks=0,
                                                per_cik={"A": cik_cell(False, None, "0 eligible rows (of 0 filled): "
                                                                                    "nothing was perturbed"),
                                                         "B": cik_cell(False, None, held_not)})}},
        null_control={"B": [dict(cause="fv_residual_outside_band",
                                 contract_id="B:independent_totals:fair_value:whole_filing"),
                            dict(cause="pct_sum_outside_band",
                                 contract_id="B:independent_totals:pct_of_net_assets:whole_filing")]})
    seeded = rr.seeded_cells(sens, financials_loaded={"A": True, "B": True, "C": False})
    fv = seeded[rr.TOTALS_KIND]["variants"][rr.TOTALS_VARIANT]["per_cik"]
    pct = seeded[rr.TOTALS_KIND]["variants"]["pct_scale_flip"]["per_cik"]
    assert fv["A"] == dict(anchored=True, applicable=True, smallest_detected=0.05, reason="measured")
    assert fv["B"]["reason"] == "baseline_out_of_band:fv_residual_outside_band"
    assert fv["C"]["reason"] == "no_anchor"
    assert pct["A"]["reason"].startswith("not_applicable:0 eligible rows")
    assert pct["B"]["reason"] == "baseline_out_of_band:pct_sum_outside_band"
    assert rr.totals_verdict(seeded[rr.TOTALS_KIND]) == "FAIL"
    body = dict(run_id="sp1-replay-test", sample_label=rr.SAMPLE_LABEL, pair_rule=rr.PAIR_RULE,
                negatives_caveat="caveat", ciks={}, per_kind={}, floors={}, seeded=seeded, exclusions=[],
                exclusion_buckets={"excluded_state:open": 2})
    text = rr.render_md(body, [])
    assert "detected 1/2 anchored filers" in text and "x0.01 is not seeded" in text
    assert "| B | fair_value_scale_flip | True | False | - | baseline_out_of_band:fv_residual_outside_band |" in text
    assert "| B | pct_scale_flip | True | False | - | baseline_out_of_band:pct_sum_outside_band |" in text
    assert "| C | fair_value_scale_flip | False | False | - | no_anchor |" in text
    assert "| excluded_state:open | 2 |" in text
    text.encode("ascii")


def test_exclusion_buckets_use_the_backtest_excluded_states():
    rows = [dict(state="open", reason="state_not_adjudicated:open"),
            dict(state="brand_new", reason="state_not_adjudicated:brand_new"),
            dict(state="adjudicated_confirmed", reason="rule_not_mapped:X99")]
    assert rr.exclusion_buckets(rows) == {"excluded_state:open": 1, "rule_not_mapped": 1,
                                          "unexpected_state:brand_new": 1}


def test_run_refuses_a_seed_whose_lineage_differs_from_the_backtest(tmp_path):
    import json
    import pytest
    from scripts.profile_pilot import lineage, m2_backtest
    from scripts.profile_pilot.manifest import StageInvalidated
    from tests.test_profile_pilot_paths import fake_paths
    paths = fake_paths(tmp_path, run_id="sp1-replay-test")
    broot = lineage.sibling_root(paths, "stageb2-backtest-test").run_root
    sroot = lineage.sibling_root(paths, "stageb2-seed-test").run_root
    for root, rels in ((broot, ("results/pairs.json", "results/backtest_results.json", "results/positives.json",
                                "results/scoring.json")),
                       (sroot, ("results/sensitivity.json", "results/run_summary.json"))):
        for rel in rels:
            (root / rel).parent.mkdir(parents=True, exist_ok=True)
            (root / rel).write_text("{}", encoding="ascii")

    def lineage_of(contracts, census):
        return json.dumps(dict(contracts_source=dict(run_id=contracts), census_source=dict(run_id=census)))
    (broot / "manifest.json").write_text(lineage_of("stageb-contracts-a", "stageb2-census-a"), encoding="ascii")
    (sroot / "manifest.json").write_text(lineage_of("stageb-contracts-b", "stageb2-census-a"), encoding="ascii")
    ledger = paths.data_root / m2_backtest.LEDGER_CSV
    ledger.parent.mkdir(parents=True, exist_ok=True)
    ledger.write_text("review_id\n", encoding="ascii")
    with pytest.raises(StageInvalidated, match="contracts_source.run_id"):
        rr.run(paths, backtest_run_id="stageb2-backtest-test", seed_run_id="stageb2-seed-test")
    (sroot / "manifest.json").write_text(lineage_of("stageb-contracts-a", "stageb2-census-b"), encoding="ascii")
    with pytest.raises(StageInvalidated, match="census_source.run_id"):
        rr.run(paths, backtest_run_id="stageb2-backtest-test", seed_run_id="stageb2-seed-test")


def test_per_filer_totals_table_shows_removed_by_rule_when_the_seed_summary_carries_it():
    sens = dict(cells={rr.TOTALS_VARIANT: {rr.TOTALS_KIND: dict(
        median_smallest_detected=0.05, detected_ciks=1, applicable_ciks=1,
        per_cik={"A": dict(applicable=True, smallest_detected=0.05, reason=None)})}}, null_control={})
    removed = {"A": {"R3_label_or_heading": dict(n=1, fv=600.0), "R4_generic_cash_bucket": dict(n=1, fv=10.0),
                     "R6_reporting_entity_lookthrough": dict(n=2, fv=110.0), "R1_own_period_instant": dict(n=0, fv=0.0)}}
    seeded = rr.seeded_cells(sens, financials_loaded={"A": True}, removed_by_rule=removed)
    row = seeded[rr.TOTALS_KIND]["variants"][rr.TOTALS_VARIANT]["per_cik"]["A"]
    assert row["removed_by_rule"] == "R3_label_or_heading:1/600; R4_generic_cash_bucket:1/10; " \
                                     "R6_reporting_entity_lookthrough:2/110"
    body = dict(run_id="sp3-replay-test", sample_label=rr.SAMPLE_LABEL, pair_rule=rr.PAIR_RULE,
                negatives_caveat="caveat", ciks={}, per_kind={}, floors={}, seeded=seeded, exclusions=[],
                exclusion_buckets={})
    text = rr.render_md(body, [])
    assert "| cik | variant | anchored | applicable | smallest detected | reason | removed by rule |" in text
    assert "| A | fair_value_scale_flip | True | True | 0.05 | measured | R3_label_or_heading:1/600;" in text
    text.encode("ascii")
    plain = rr.render_md(dict(body, seeded=rr.seeded_cells(sens, financials_loaded={"A": True})), [])
    assert "removed by rule" not in plain


def test_fv_of_doc_totals_on_the_published_basis():
    from tests.test_profile_pilot_totals import bcred_doc, BCRED
    fv = rr.fv_of_doc(bcred_doc(), cik=BCRED)
    assert fv["total"] == 600.0 and fv["by_key"]["e1"] == 50.0
