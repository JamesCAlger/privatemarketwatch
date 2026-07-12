"""Tests for pipeline.sofr_reference (SOFR lookup + spread/all-in reconciliation)."""

import pipeline.sofr_reference as sr


def _inject(series):
    sr._CACHE = ([d for d, _ in series], [v for _, v in series])


def test_sofr_for_nearest_prior():
    _inject([("2023-03-31", 4.8), ("2023-06-30", 5.0), ("2023-09-29", 5.3)])
    assert sr.sofr_for("2023-06-30") == 5.0
    assert sr.sofr_for("2023-07-15") == 5.0       # nearest prior obs
    assert sr.sofr_for("2023-01-01") is None      # before series start
    assert sr.sofr_for(None) is None
    sr._CACHE = None


def test_effective_base_floor_binds():
    assert sr.effective_base(4.5, 1.0) == 4.5     # SOFR above floor
    assert sr.effective_base(0.5, 1.0) == 1.0     # floor binds


def test_reconcile_residual():
    # cash 11.13 = SOFR 5.00 + spread 6.00 -> residual 0.13
    assert sr.reconcile_residual(11.13, 6.00, 0.0, 5.00) == 0.13
    assert sr.reconcile_residual(11.13, 6.60, 0.0, 5.00) == round(abs(11.60 - 11.13), 4)
    assert sr.reconcile_residual(None, 6.0, 0.0, 5.0) is None
    assert sr.reconcile_residual(11.13, 6.0, 0.0, None) is None


def test_adjudicate_spread_xbrl_wins():
    # A005: cash 11.13, A=6.60, XBRL=6.00, SOFR 5.00 -> XBRL reconciles
    assert sr.adjudicate_spread(11.13, 6.60, 6.00, 0.0, 5.00) == "xbrl"


def test_adjudicate_spread_agent_wins():
    # cash 11.00 = 5.00 + 6.00; A=6.00 right, XBRL=6.60 wrong
    assert sr.adjudicate_spread(11.00, 6.00, 6.60, 0.0, 5.00) == "agentA"


def test_adjudicate_spread_both_when_close():
    # both within margin of the all-in -> proxy cannot resolve
    assert sr.adjudicate_spread(11.05, 6.00, 6.05, 0.0, 5.00) == "both"


def test_adjudicate_spread_neither_when_implausible():
    # both spreads far from reconciling (cash wildly off) -> neither
    assert sr.adjudicate_spread(20.0, 6.0, 6.5, 0.0, 5.0) == "neither"


def test_adjudicate_undeterminable_missing_allin():
    assert sr.adjudicate_spread(None, 6.0, 6.5, 0.0, 5.0) == "undeterminable"
