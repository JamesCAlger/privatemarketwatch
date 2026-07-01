"""Tests for #1 (applies_to resolution) and the #2 remediation-quarter feedback."""

from scripts.agent_a.run_quarter import _failing_quarters


class _V:
    def __init__(self, quarters):
        self.quarters = quarters


def _q(quarter, sig_rows, none, comp, inv):
    return {"quarter": quarter, "sig_rows": sig_rows, "none_pct": none,
            "completeness_pct": comp, "invariant_pct": inv}


def test_failing_quarters_flags_completeness_dip():
    v = _V([_q("2024-03-31", 300, 1.0, 99.0, 98.0),
            _q("2024-12-31", 310, 1.0, 84.8, 98.0)])  # the Antares-PC case
    assert _failing_quarters(v) == ["2024-12-31"]


def test_failing_quarters_flags_none_spike_even_with_zero_sig_rows():
    # the MS case: failing quarter has 0 sig-rows (all (none)) -> must STILL be a re-induce target
    v = _V([_q("2023-03-31", 0, 100.0, None, None),
            _q("2024-03-31", 300, 1.0, 99.0, 98.0),
            _q("2024-06-30", 300, 1.5, 99.0, 98.0)])
    assert "2023-03-31" in _failing_quarters(v)


def test_failing_quarters_empty_when_all_clear():
    v = _V([_q("2024-03-31", 300, 1.0, 99.0, 98.0),
            _q("2024-06-30", 310, 1.2, 98.5, 97.0)])
    assert _failing_quarters(v) == []
