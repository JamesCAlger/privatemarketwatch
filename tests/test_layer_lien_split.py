"""Tests for the layered lien-split logic + reconciliation gate."""
from pipeline.export.index_exports import _layer_lien_split

_ID = lambda x: x  # identity pct -> assert on raw FV


def test_reconciling_subtotals_used_remainder_to_unknown():
    pp = [("A", "Unknown", 100.0)]          # per-position all blank
    sub = [("A", "First Lien", 90.0)]        # subtotals cover 90 of 100
    out = _layer_lien_split(pp, sub, _ID)
    assert out["firstLien"] == 90.0
    assert out["unknown"] == 10.0            # uncovered remainder is honest Unknown
    assert out["subtotalFilers"] == 1


def test_negative_subtotal_falls_back_to_position():
    # AB Private Credit case: a garbage negative subtotal must NOT be used
    pp = [("B", "First Lien", 50.0)]
    sub = [("B", "First Lien", -2.0)]
    out = _layer_lien_split(pp, sub, _ID)
    assert out["firstLien"] == 50.0
    assert out["subtotalFilers"] == 0


def test_overcounting_subtotal_falls_back_to_position():
    pp = [("D", "First Lien", 100.0)]
    sub = [("D", "First Lien", 200.0)]       # > 105% of DL FV -> reject
    out = _layer_lien_split(pp, sub, _ID)
    assert out["firstLien"] == 100.0
    assert out["subtotalFilers"] == 0


def test_low_coverage_subtotal_falls_back_to_position():
    pp = [("E", "First Lien", 100.0)]
    sub = [("E", "First Lien", 30.0)]        # < 50% coverage -> use per-position
    out = _layer_lien_split(pp, sub, _ID)
    assert out["firstLien"] == 100.0
    assert out["subtotalFilers"] == 0


def test_position_only_filer():
    pp = [("C", "First Lien", 20.0), ("C", "Unknown", 10.0)]
    out = _layer_lien_split(pp, [], _ID)
    assert out["firstLien"] == 20.0 and out["unknown"] == 10.0


def test_mixed_cohort_blends_both_sources():
    pp = [("HIER", "Unknown", 100.0),        # hierarchical filer, blank per-position
          ("EMB", "First Lien", 40.0), ("EMB", "Second Lien", 10.0)]  # embedded-lien filer
    sub = [("HIER", "First Lien", 95.0)]     # reconciles (95% coverage)
    out = _layer_lien_split(pp, sub, _ID)
    assert out["firstLien"] == 95.0 + 40.0
    assert out["secondLien"] == 10.0
    assert out["unknown"] == 5.0             # HIER's uncovered 5
    assert out["subtotalFilers"] == 1
