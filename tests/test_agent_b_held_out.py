"""Tests for the B3 held-out promotion gate (pure over quarter snapshots)."""

from __future__ import annotations

from pipeline.agent_b_held_out import gate_correction


def _cons(value_sum, anchor):
    return {"value_sum": value_sum, "anchor_value": anchor}


# A conservation overshoot in 2024-12-31 (the target): value_sum 337 vs anchor 316.
# Two clean held-out quarters already at anchor.
def _baseline():
    return {
        "2024-12-31": {"flags": ["fv_conservation"], "fv_at_risk": 20.0,
                       "conservation": _cons(337.0, 316.0)},
        "2024-09-30": {"flags": [], "fv_at_risk": 0.0, "conservation": _cons(300.0, 300.0)},
        "2024-06-30": {"flags": [], "fv_at_risk": 0.0, "conservation": _cons(280.0, 280.0)},
    }


def test_genuine_subtotal_fix_passes():
    # Removing the leaked subtotal brings target to anchor; held-out quarters unchanged.
    trial = {
        "2024-12-31": {"flags": [], "fv_at_risk": 0.0, "conservation": _cons(316.0, 316.0)},
        "2024-09-30": {"flags": [], "fv_at_risk": 0.0, "conservation": _cons(300.0, 300.0)},
        "2024-06-30": {"flags": [], "fv_at_risk": 0.0, "conservation": _cons(280.0, 280.0)},
    }
    res = gate_correction(cik="x", target_quarter="2024-12-31", target_flags=["fv_conservation"],
                          baseline=_baseline(), trial=trial)
    assert res.verdict == "PASS", res.reasons


def test_target_not_cleared_fails():
    trial = dict(_baseline())  # nothing changed
    res = gate_correction(cik="x", target_quarter="2024-12-31", target_flags=["fv_conservation"],
                          baseline=_baseline(), trial=trial)
    assert res.verdict == "FAIL"
    assert res.checks["target_cleared"] is False


def test_already_reconciled_target_passes():
    # 1743415 shape: the anchor-adjudicator corrected the anchor so the target ALREADY reconciles at
    # baseline (no flag, value_sum == anchor); no holdings fix is needed. residual_improved must not
    # fire (nothing to improve) -- a real no-op still fails because the target flag would persist.
    base = {
        "2024-12-31": {"flags": [], "fv_at_risk": 0.0, "conservation": _cons(420.0, 420.0)},
        "2024-09-30": {"flags": [], "fv_at_risk": 0.0, "conservation": _cons(300.0, 300.0)},
        "2024-06-30": {"flags": [], "fv_at_risk": 0.0, "conservation": _cons(280.0, 280.0)},
    }
    trial = {k: dict(v) for k, v in base.items()}                    # no change needed in target
    res = gate_correction(cik="x", target_quarter="2024-12-31", target_flags=["fv_conservation"],
                          baseline=base, trial=trial)
    assert res.verdict == "PASS", res.reasons
    assert res.checks["residual_improved"] is True


def test_delete_to_balance_broad_rule_rejected():
    # The fix clears the target but the over-broad rule fires elsewhere too -> a held-out
    # quarter gains a NEW undershoot flag.
    trial = {
        "2024-12-31": {"flags": [], "fv_at_risk": 0.0, "conservation": _cons(316.0, 316.0)},
        "2024-09-30": {"flags": ["fv_conservation"], "fv_at_risk": 50.0,
                       "conservation": _cons(250.0, 300.0)},  # over-deleted here
        "2024-06-30": {"flags": [], "fv_at_risk": 0.0, "conservation": _cons(280.0, 280.0)},
    }
    res = gate_correction(cik="x", target_quarter="2024-12-31", target_flags=["fv_conservation"],
                          baseline=_baseline(), trial=trial)
    assert res.verdict == "FAIL"
    assert res.checks["no_new_flags"] is False


def test_delete_below_anchor_in_target_rejected():
    # Delete-to-balance that over-shoots PAST the anchor in the target quarter.
    trial = {
        "2024-12-31": {"flags": [], "fv_at_risk": 0.0, "conservation": _cons(250.0, 316.0)},
        "2024-09-30": {"flags": [], "fv_at_risk": 0.0, "conservation": _cons(300.0, 300.0)},
        "2024-06-30": {"flags": [], "fv_at_risk": 0.0, "conservation": _cons(280.0, 280.0)},
    }
    res = gate_correction(cik="x", target_quarter="2024-12-31", target_flags=["fv_conservation"],
                          baseline=_baseline(), trial=trial)
    assert res.verdict == "FAIL"
    assert res.checks["no_over_deletion"] is False


def test_preexisting_undershoot_not_counted_as_new_over_deletion():
    base = _baseline()
    base["2024-09-30"] = {"flags": ["fv_conservation"], "fv_at_risk": 25.0,
                          "conservation": _cons(275.0, 300.0)}
    trial = {
        "2024-12-31": {"flags": [], "fv_at_risk": 0.0, "conservation": _cons(316.0, 316.0)},
        "2024-09-30": base["2024-09-30"],  # unchanged pre-existing undercount
        "2024-06-30": base["2024-06-30"],
    }
    res = gate_correction(cik="x", target_quarter="2024-12-31", target_flags=["fv_conservation"],
                          baseline=base, trial=trial)
    assert res.checks["no_over_deletion"] is True


def test_worsened_preexisting_undershoot_is_rejected():
    base = _baseline()
    base["2024-09-30"] = {"flags": ["fv_conservation"], "fv_at_risk": 25.0,
                          "conservation": _cons(275.0, 300.0)}
    trial = {
        "2024-12-31": {"flags": [], "fv_at_risk": 0.0, "conservation": _cons(316.0, 316.0)},
        "2024-09-30": {"flags": ["fv_conservation"], "fv_at_risk": 40.0,
                       "conservation": _cons(260.0, 300.0)},
        "2024-06-30": base["2024-06-30"],
    }
    res = gate_correction(cik="x", target_quarter="2024-12-31", target_flags=["fv_conservation"],
                          baseline=base, trial=trial)
    assert res.verdict == "FAIL"
    assert res.checks["no_over_deletion"] is False


def test_single_quarter_overfit_caught():
    # Only the target quarter exists -> no held-out coverage.
    base = {"2024-12-31": _baseline()["2024-12-31"]}
    trial = {"2024-12-31": {"flags": [], "fv_at_risk": 0.0, "conservation": _cons(316.0, 316.0)}}
    res = gate_correction(cik="x", target_quarter="2024-12-31", target_flags=["fv_conservation"],
                          baseline=base, trial=trial)
    assert res.verdict == "FAIL"
    assert res.checks["held_out_coverage"] is False


def test_new_flag_elsewhere_fails():
    trial = {
        "2024-12-31": {"flags": [], "fv_at_risk": 0.0, "conservation": _cons(316.0, 316.0)},
        "2024-09-30": {"flags": ["C113:rowZ"], "fv_at_risk": 5.0, "conservation": _cons(300.0, 300.0)},
        "2024-06-30": {"flags": [], "fv_at_risk": 0.0, "conservation": _cons(280.0, 280.0)},
    }
    res = gate_correction(cik="x", target_quarter="2024-12-31", target_flags=["fv_conservation"],
                          baseline=_baseline(), trial=trial)
    assert res.verdict == "FAIL"
    assert res.checks["no_new_flags"] is False


def test_fv_at_risk_increase_fails():
    trial = {
        "2024-12-31": {"flags": [], "fv_at_risk": 0.0, "conservation": _cons(316.0, 316.0)},
        "2024-09-30": {"flags": [], "fv_at_risk": 999.0, "conservation": _cons(300.0, 300.0)},
        "2024-06-30": {"flags": [], "fv_at_risk": 0.0, "conservation": _cons(280.0, 280.0)},
    }
    res = gate_correction(cik="x", target_quarter="2024-12-31", target_flags=["fv_conservation"],
                          baseline=_baseline(), trial=trial)
    assert res.verdict == "FAIL"
    assert res.checks["fv_at_risk_non_increasing"] is False


def test_band_blowout_fails():
    base = {
        "2024-12-31": {"flags": ["fv_conservation"], "fv_at_risk": 20.0,
                       "conservation": _cons(337.0, 316.0),
                       "bands": {"D01_count": 10, "D01_fv": 5.0, "D02_count": 2, "D02_fv": 1.0}},
        "2024-09-30": {"flags": [], "fv_at_risk": 0.0, "conservation": _cons(300.0, 300.0),
                       "bands": {"D01_count": 10, "D01_fv": 5.0, "D02_count": 2, "D02_fv": 1.0}},
        "2024-06-30": {"flags": [], "fv_at_risk": 0.0, "conservation": _cons(280.0, 280.0),
                       "bands": {"D01_count": 10, "D01_fv": 5.0, "D02_count": 2, "D02_fv": 1.0}},
    }
    trial = {
        "2024-12-31": {"flags": [], "fv_at_risk": 0.0, "conservation": _cons(316.0, 316.0),
                       "bands": {"D01_count": 99, "D01_fv": 5.0, "D02_count": 2, "D02_fv": 1.0}},
        "2024-09-30": base["2024-09-30"],
        "2024-06-30": base["2024-06-30"],
    }
    res = gate_correction(cik="x", target_quarter="2024-12-31", target_flags=["fv_conservation"],
                          baseline=base, trial=trial)
    assert res.verdict == "FAIL"
    assert res.checks["bands_hold"] is False
