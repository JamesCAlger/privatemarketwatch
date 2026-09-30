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
    ok = dict(median_smallest_detected=0.05, detected_ciks=5, applicable_ciks=5)
    assert rr.totals_verdict(ok) == "PASS"
    assert rr.totals_verdict(dict(ok, detected_ciks=4)) == "FAIL"
    assert rr.totals_verdict(dict(ok, median_smallest_detected=0.3)) == "FAIL"


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
