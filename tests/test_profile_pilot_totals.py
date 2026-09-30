"""Task 3: independent_totals contract kind as pure functions.

Two whole-filing criteria that cannot abstain on a pure scale flip: the census's
published-basis fair-value sum against the fund's filed investments_at_fair_value,
and the pct-of-net-assets sum. See scripts/profile_pilot/contracts_totals.py.
"""
import copy
import pytest
from tests.test_profile_pilot_contracts import mk_doc, debt, val
from scripts.profile_pilot import contracts_totals as ct

BAND = dict(fv_residual_pct=5.0, pct_sum_min=50, pct_sum_max=250, pct_sum_shift_pp=15, min_positions=5)
FIN = dict(cik="0000000001", report_date="2026-03-31", investments_at_fair_value=80_000_000.0,
           net_assets=60_000_000.0, total_assets=90_000_000.0)


def book(n=80, fv="1000000", pct="1.25"):
    doc = mk_doc([debt(i) for i in range(n)])
    for p in doc["positions"]:
        p["fields"]["fair_value"] = val(fv, unit="USD")
        p["fields"]["pct_of_net_assets"] = val(pct)
    return doc


def test_observe_sums_current_period_positions_and_computes_residual():
    obs = ct.observe_totals(book(), financials=FIN)
    assert obs["n_positions"] == 80 and obs["fv_filled"] == 80
    assert obs["fv_sum"] == 80_000_000 and obs["fv_residual_pct"] == 0
    assert obs["pct_sum"] == 100 and obs["anchor_source"] == "fund_financials.investments_at_fair_value"


def test_observe_without_financials_has_no_anchor():
    obs = ct.observe_totals(book(), financials=None)
    assert obs["fv_anchor"] is None and obs["fv_residual_pct"] is None


def test_learn_then_holds_on_an_unchanged_book():
    q1 = book()
    contracts = ct.learn_totals("0000000001", "standard", BAND, q1, financials_q1=FIN)
    assert [c["field"] for c in contracts] == ["fair_value", "pct_of_net_assets"]
    assert all(c["learn_status"] == "learned" and c["status_basis"] == "provisional" for c in contracts)
    q2 = dict(report_date="2026-03-31", form_type="10-Q", status="selected", detail=None)
    res = [ct.evaluate_totals(c, q2, book(), financials_q2=FIN, band=BAND) for c in contracts]
    assert [r["status"] for r in res] == ["holds", "holds"]


def test_x100_scale_flip_on_fair_value_breaches_fv_and_pct_flip_breaches_pct():
    contracts = ct.learn_totals("0000000001", "standard", BAND, book(), financials_q1=FIN)
    q2 = dict(report_date="2026-03-31", form_type="10-Q", status="selected", detail=None)
    fv_flip = book(fv="100000000")          # x100 on every row
    r = ct.evaluate_totals(contracts[0], q2, fv_flip, financials_q2=FIN, band=BAND)
    assert r["status"] == "breach" and r["cause"] == "fv_residual_outside_band"
    pct_flip = book(pct="125")              # x100 on every row
    r = ct.evaluate_totals(contracts[1], q2, pct_flip, financials_q2=FIN, band=BAND)
    assert r["status"] == "breach" and r["cause"] == "pct_sum_outside_band"


def test_partial_flip_at_twenty_percent_of_rows_is_detected():
    contracts = ct.learn_totals("0000000001", "standard", BAND, book(), financials_q1=FIN)
    q2 = dict(report_date="2026-03-31", form_type="10-Q", status="selected", detail=None)
    doc = book()
    for p in doc["positions"][:16]:      # 20% of 80 rows x100
        p["fields"]["fair_value"] = val("100000000", unit="USD")
    r = ct.evaluate_totals(contracts[0], q2, doc, financials_q2=FIN, band=BAND)
    assert r["status"] == "breach"


def test_missing_anchor_in_q2_abstains_with_cause_no_anchor():
    contracts = ct.learn_totals("0000000001", "standard", BAND, book(), financials_q1=FIN)
    q2 = dict(report_date="2026-03-31", form_type="10-Q", status="selected", detail=None)
    r = ct.evaluate_totals(contracts[0], q2, book(), financials_q2=None, band=BAND)
    assert r["status"] == "insufficient_evidence" and r["cause"] == "no_anchor"


def test_pct_sum_shift_within_band_holds_and_beyond_band_breaches():
    contracts = ct.learn_totals("0000000001", "standard", BAND, book(), financials_q1=FIN)
    q2 = dict(report_date="2026-03-31", form_type="10-Q", status="selected", detail=None)
    assert ct.evaluate_totals(contracts[1], q2, book(pct="1.40"), financials_q2=FIN, band=BAND)["status"] == "holds"   # 112
    r = ct.evaluate_totals(contracts[1], q2, book(pct="1.50"), financials_q2=FIN, band=BAND)                          # 120
    assert r["status"] == "breach" and r["cause"] == "pct_sum_shifted"


def test_too_few_positions_never_learns():
    contracts = ct.learn_totals("0000000001", "standard", BAND, book(n=3), financials_q1=FIN)
    assert all(c["learn_status"] == "insufficient_evidence" for c in contracts)
    assert contracts[0]["learn_cause"] == "too_few_positions"
