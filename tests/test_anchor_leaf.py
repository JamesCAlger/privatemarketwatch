"""Tests for the anchor-adjudicator deterministic core: anchor_leaf schema + the balance-sheet
closure check (verify_grand_total) + the cheap incomplete-anchor pre-screen. Pure, no dispatch."""
from pipeline.anchor_leaf import validate_anchor_leaf
from pipeline.anchor_validation import (
    HIGH, MEDIUM, NONE, incomplete_anchor_screen, verify_grand_total,
)


def _leaf(**kw):
    base = {"cik": "1715933", "target_quarter": "2025-06-30", "grand_total": 1_094_088_266.0,
            "method": "sum_of_schedules",
            "components": [
                {"label": "non-affiliated", "value": 691_956_192.0, "source": "companyfacts IOAFV"},
                {"label": "affiliated", "value": 402_132_074.0, "source": "SOI affiliated total row"}],
            "companyfacts_fv": 691_956_192.0,
            "evidence": [{"source": "filing", "quote": "Total Investments 1,094,088"}],
            "rationale": "tag captures only non-affiliated", "confidence": 0.9}
    base.update(kw)
    return base


# -- anchor_leaf schema + internal consistency -------------------------------------------

def test_valid_anchor_leaf():
    assert validate_anchor_leaf(_leaf()) == []


def test_anchor_leaf_required_and_enums():
    assert any("method must be one of" in e for e in validate_anchor_leaf(_leaf(method="guess")))
    assert any("grand_total must be" in e for e in validate_anchor_leaf(_leaf(grand_total=-1)))
    assert any("confidence must be" in e for e in validate_anchor_leaf(_leaf(confidence=2)))
    assert any("components must be" in e for e in validate_anchor_leaf(_leaf(components=[])))


def test_anchor_leaf_component_must_cite_source():
    bad = [{"label": "x", "value": 100.0}]   # missing source
    assert any("missing source" in e for e in validate_anchor_leaf(_leaf(components=bad)))


def test_anchor_leaf_filing_total_assets_requires_source():
    # (b) filing-sourced total_assets must cite the balance-sheet line
    assert any("total_assets_source" in e for e in validate_anchor_leaf(_leaf(total_assets=2e9)))
    assert validate_anchor_leaf(_leaf(total_assets=2e9, total_assets_source="BS Total assets line")) == []


def test_sum_of_schedules_must_reconcile():
    # components must sum to grand_total for sum_of_schedules
    bad = _leaf(grand_total=2_000_000_000.0)   # components still sum to ~1.094B
    assert any("must reconcile" in e for e in validate_anchor_leaf(bad))
    # single_tag does not require summation
    ok = _leaf(method="single_tag", grand_total=691_956_192.0,
               components=[{"label": "tag", "value": 691_956_192.0, "source": "IOAFV"}])
    assert validate_anchor_leaf(ok) == []


# -- verify_grand_total: balance-sheet closure (the un-gameable check) --------------------

def test_grand_total_closes_high_with_cash():
    # 1715933: grand 1.094B, total_assets 1.098B, cash ~4M -> other ~0 -> HIGH
    r = verify_grand_total(1_094_088_266, total_assets=1_098_107_000,
                           companyfacts_fv=691_956_192, cash=4_000_000)
    assert r.tier == HIGH and r.ok


def test_grand_total_rejected_when_exceeds_total_assets():
    r = verify_grand_total(1_200_000_000, total_assets=1_098_107_000, companyfacts_fv=691_956_192)
    assert r.tier == NONE and not r.ok and any("exceeds total_assets" in x for x in r.reasons)


def test_grand_total_rejected_below_companyfacts_floor():
    r = verify_grand_total(500_000_000, total_assets=1_098_107_000, companyfacts_fv=691_956_192)
    assert r.tier == NONE and any("below the companyfacts tag" in x for x in r.reasons)


def test_subtotal_masquerading_as_grand_total_not_accepted():
    # the WRONG anchor: companyfacts subtotal 692M proposed as grand total -> 63% invested -> reject
    r = verify_grand_total(691_956_192, total_assets=1_098_107_000, companyfacts_fv=691_956_192)
    assert r.tier == NONE and any("still looks like a subtotal" in x for x in r.reasons)


def test_grand_total_medium_without_cash():
    # plausible invested fraction (~85%) but no cash to confirm -> MEDIUM
    r = verify_grand_total(935_000_000, total_assets=1_098_107_000, companyfacts_fv=691_956_192)
    assert r.tier == MEDIUM


def test_cash_folded_into_tag_falls_back_to_invested_fraction():
    # grand_total (1.05B) <= assets, but grand_total + cash (1.25B) > assets -> the cash is already
    # folded into the FV tag (2022625-style filer). Ignore cash and tier on the invested fraction
    # (95.6% -> HIGH/MEDIUM) instead of falsely rejecting. (A grand_total that ALONE exceeds assets
    # is still NONE -- see test_grand_total_rejected_when_exceeds_total_assets.)
    r = verify_grand_total(1_050_000_000, total_assets=1_098_107_000,
                           companyfacts_fv=691_956_192, cash=200_000_000)
    assert r.tier in (HIGH, MEDIUM)


# -- incomplete-anchor pre-screen (cheap trigger) ----------------------------------------

def test_screen_flags_incomplete_anchor():
    flagged, reason = incomplete_anchor_screen(691_956_192, 1_098_107_000)   # 63%
    assert flagged and "incomplete subtotal" in reason


def test_screen_passes_normal_anchor():
    flagged, _ = incomplete_anchor_screen(950_000_000, 1_098_107_000)        # 87%
    assert not flagged


def test_screen_cash_aware_clears_cash_heavy_quarter():
    # 1792509: 87% invested, but the 13% is $47M cash + $12M other -> non-cash remainder ~2.6% -> ok
    flagged, reason = incomplete_anchor_screen(402_819_000, 462_155_000, 47_218_000)
    assert not flagged and "closes with cash" in reason


def test_screen_cash_aware_still_flags_real_subtotal():
    # a genuine excluded schedule: 60% invested with little cash -> big non-cash remainder -> flag
    flagged, _ = incomplete_anchor_screen(600_000_000, 1_000_000_000, 20_000_000)
    assert flagged


def test_closure_high_with_companyfacts_cash():
    # feeding companyfacts cash makes 1792509 close tightly as the grand total -> HIGH (not MEDIUM)
    r = verify_grand_total(402_819_000, total_assets=462_155_000,
                           companyfacts_fv=402_819_000, cash=47_218_000)
    assert r.tier == HIGH
