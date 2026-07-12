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
