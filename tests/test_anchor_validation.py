"""Tests for pipeline.anchor_validation -- the independence-aware anchor checks that decide whether
the conservation loop may reconcile to an anchor at all. Pure, no data, no LLM."""
from pipeline.anchor_validation import (
    HIGH, MEDIUM, NONE, classify_anchors, classify_many, flag_anchor_outliers,
)


# -- classify_anchors: agreement test among STRONG anchors only --------------------------

def test_two_strong_anchors_agree_is_high():
    v = classify_anchors({"companyfacts_fv": 1000.0, "printed_schedule_total": 1003.0})
    assert v.tier == HIGH and v.may_reconcile
    assert 1000.0 <= v.consensus <= 1003.0          # mean of the agreeing strong anchors
    assert v.max_disagreement is not None and v.max_disagreement < 0.01


def test_two_strong_anchors_disagree_is_none():
    v = classify_anchors({"companyfacts_fv": 1000.0, "printed_schedule_total": 1400.0})
    assert v.tier == NONE and not v.may_reconcile and v.consensus is None
    assert "DISAGREE" in v.reason


def test_single_strong_anchor_is_medium():
    v = classify_anchors({"companyfacts_fv": 1000.0})
    assert v.tier == MEDIUM and v.may_reconcile and v.consensus == 1000.0
    assert "single independent anchor" in v.reason


def test_extraction_resum_is_ignored_not_a_partner():
    # schedule_total is a re-sum of the same extraction. Its disagreement with companyfacts_fv is
    # the DEFECT we fix -- it must NOT flip the anchor to NONE. companyfacts_fv alone -> MEDIUM.
    v = classify_anchors({"companyfacts_fv": 1000.0, "schedule_total": 3500.0})
    assert v.tier == MEDIUM and v.consensus == 1000.0


def test_resum_only_is_none():
    # only an extraction re-sum present -> reconciling to it is circular -> NONE
    assert classify_anchors({"schedule_total": 1000.0}).tier == NONE
    assert classify_anchors({"value_sum": 1000.0}).tier == NONE
    assert classify_anchors({"extract_total_fv": 1376.0}).tier == NONE


def test_empty_candidates_is_none():
    assert classify_anchors({}).tier == NONE
    assert classify_anchors(None).tier == NONE


def test_unknown_name_is_ignored():
    # an unrecognised name cannot fake a strong anchor; with no real strong anchor -> NONE
    assert classify_anchors({"some_made_up_total": 1000.0}).tier == NONE
    # alongside a real strong anchor it is simply ignored -> MEDIUM on the real one
    v = classify_anchors({"companyfacts_fv": 1000.0, "some_made_up_total": 9999.0})
    assert v.tier == MEDIUM and v.consensus == 1000.0


def test_nonpositive_and_missing_dropped():
    v = classify_anchors({"companyfacts_fv": 1000.0, "printed_schedule_total": None,
                          "companyfacts_concept": 0.0})
    assert v.tier == MEDIUM and v.consensus == 1000.0


def test_classify_many_keys_by_quarter():
    out = classify_many({"2025-12-31": {"companyfacts_fv": 1000.0, "printed_schedule_total": 1001.0},
                         "2025-09-30": {"schedule_total": 500.0}})
    assert out["2025-12-31"].tier == HIGH
    assert out["2025-09-30"].tier == NONE


# -- flag_anchor_outliers: cross-quarter plausibility (the 1743415 catch, today) ---------

def test_outlier_flags_pathological_low_quarter():
    # SPORADIC mis-extraction: one quarter wildly below the CIK's own level (a $14M reading among
    # ~$400M quarters). NOTE this is the detectable case; a SYSTEMATICALLY wrong tag (1743415, every
    # quarter consistently ~$14-28M) is self-consistent and is NOT caught here -- see test below.
    series = {"2025-03-31": 406e6, "2025-06-30": 410e6, "2025-09-30": 395e6,
              "2025-12-31": 13.96e6}
    flags = flag_anchor_outliers(series)
    assert flags["2025-12-31"].flagged and "mis-extracted" in flags["2025-12-31"].reason
    assert not flags["2025-03-31"].flagged


def test_outlier_ignores_normal_qoq_drift():
    # portfolios grow/shrink; a <3x band must not fire on ordinary drift
    series = {"a": 100e6, "b": 120e6, "c": 140e6, "d": 160e6}
    flags = flag_anchor_outliers(series)
    assert not any(f.flagged for f in flags.values())


def test_outlier_needs_minimum_history():
    flags = flag_anchor_outliers({"a": 100e6, "b": 1e6})   # only 2 points -> no basis to judge
    assert not any(f.flagged for f in flags.values())


def test_systematically_wrong_anchor_is_not_an_outlier():
    # 1743415: the companyfacts FV tag is consistently ~$14-28M every quarter (broken tag), while
    # the true portfolio is ~$180-514M. The series is SELF-CONSISTENT, so the cross-quarter check
    # cannot flag it -- only a 2nd independent anchor (printed total) would. Pin this boundary.
    series = {"2023-12-31": 13.96e6, "2024-09-30": 28.7e6, "2024-12-31": 26.7e6, "2025-03-31": 25.0e6}
    flags = flag_anchor_outliers(series)
    assert not any(f.flagged for f in flags.values())


# -- growth-aware QoQ rescue (owner-approved 2026-09-02) ------------------------------------

def test_ramp_up_fund_not_flagged():
    """1954360: 3.1x lifetime median but QoQ-continuous -- the q1p3 FP class.
    Full companyfacts series required so median (~282M) makes 2026-03-31 (~877M) a 3.1x outlier.
    """
    series = {"2023-09-30": 49_589_000, "2023-12-31": 114_294_000,
              "2024-03-31": 164_431_000, "2024-06-30": 228_717_000,
              "2024-09-30": 258_282_000, "2024-12-31": 282_161_000,
              "2025-03-31": 308_031_000, "2025-06-30": 487_664_000,
              "2025-09-30": 614_062_000, "2025-12-31": 879_592_000,
              "2026-03-31": 877_060_000}
    flags = flag_anchor_outliers(series)
    assert not flags["2026-03-31"].flagged
    assert "continu" in flags["2026-03-31"].reason


def test_declining_fund_not_flagged():
    """1495584: full 11-quarter series from fund_financials.csv (investments_at_fair_value).
    Median = 1,060,474.  2025-12-31 ratio = 225,436 / 1,060,474 = 0.213x (outside [1/3, 3]).
    QoQ vs 2025-09-30 = 225,436 / 256,934 = 0.877x (within [0.5, 2.0]) -> rescued, not flagged.
    Under OLD median-only code 2025-12-31 would be flagged (0.213x < 1/3) -- discriminating.
    Note: 2025-09-30 ratio=0.242x AND QoQ=256,934/723,147=0.355x (discontinuous) -> still flagged.
    """
    series = {
        "2022-12-31": 40_121_924, "2023-12-31": 8_733_779,
        "2024-03-31":  4_695_742, "2024-06-30": 5_676_686,
        "2024-09-30":  1_431_160, "2024-12-31": 1_060_474,
        "2025-03-31":    698_169, "2025-06-30":   723_147,
        "2025-09-30":    256_934, "2025-12-31":   225_436,
        "2026-03-31":    146_430,
    }
    flags = flag_anchor_outliers(series)
    assert not flags["2025-12-31"].flagged
    assert "continu" in flags["2025-12-31"].reason


def test_sporadic_misextraction_still_flagged():
    """The true-positive class: one quarter collapses against BOTH median and neighbor."""
    series = {"2025-03-31": 1_000_000, "2025-06-30": 1_050_000,
              "2025-09-30": 90_000, "2025-12-31": 1_100_000}
    flags = flag_anchor_outliers(series)
    assert flags["2025-09-30"].flagged


def test_first_quarter_median_rule_unchanged():
    """No previous quarter -> QoQ cannot rescue; median rule alone decides."""
    series = {"2025-03-31": 10_000_000, "2025-06-30": 1_000_000, "2025-09-30": 1_050_000}
    flags = flag_anchor_outliers(series)
    assert flags["2025-03-31"].flagged
