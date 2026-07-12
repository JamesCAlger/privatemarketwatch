"""Tests for the verdict-leaf schema + grounding invariant (pipeline.verdict_leaf)."""

from __future__ import annotations

import json

from pipeline import verdict_leaf


def _real(**over):
    base = {
        "review_id": "RVQ_BLK_abc123",
        "verdict": "real_error",
        "mechanism": "subtotal_leak",
        "localized": True,
        "anchor_used": "companyfacts_fv",
        "confidence": 0.9,
        "escalate": False,
        "culprit_citations": [{"table_index": 1, "row_index": 2, "quoted_text": "X", "ties_to_residual": True}],
        "rationale": "grounded",
    }
    base.update(over)
    return base


def test_valid_real_error_with_citation():
    rep = verdict_leaf.validate_verdict(_real())
    assert rep.ok, rep.errors


def test_real_error_without_grounding_is_error():
    rep = verdict_leaf.validate_verdict(_real(culprit_citations=[], anchor_used=""))
    assert not rep.ok
    assert any("real_error requires" in e for e in rep.errors)


def test_real_error_anchor_disagreement_is_grounding():
    rep = verdict_leaf.validate_verdict(
        _real(culprit_citations=[], observed_value=211749, anchor_value=192754)
    )
    assert rep.ok, rep.errors


def test_real_error_anchor_equal_is_not_grounding():
    rep = verdict_leaf.validate_verdict(
        _real(culprit_citations=[], observed_value=100, anchor_value=100)
    )
    assert not rep.ok


def test_citation_with_only_coordinates_is_valid():
    rep = verdict_leaf.validate_verdict(
        _real(culprit_citations=[{"table_index": 3, "row_index": 4}])
    )
    assert rep.ok, rep.errors


def test_empty_citation_object_is_not_grounding():
    rep = verdict_leaf.validate_verdict(_real(culprit_citations=[{}], anchor_used=""))
    assert not rep.ok


def test_real_error_empty_mechanism_is_error():
    rep = verdict_leaf.validate_verdict(_real(mechanism=""))
    assert not rep.ok
    assert any("mechanism" in e for e in rep.errors)


def test_gold_pik_cash_leg_mechanism_is_known_real_error():
    # PIK all-in convention: cash leg stored as interest_rate -> real_error, grounded by a
    # source citation. The gold mechanism name carries a "false_alarm_" prefix but the
    # VERDICT is real_error; the mechanism must be in-vocabulary (no warning).
    rep = verdict_leaf.validate_verdict(_real(mechanism="false_alarm_cash_leg"))
    assert rep.ok, rep.errors
    assert not any("not in known vocabulary" in w for w in rep.warnings)


def test_c113_range_false_alarm_mechanism_is_known():
    rep = verdict_leaf.validate_verdict({
        "review_id": "RVQ_REV_z", "verdict": "false_alarm", "confidence": 0.9,
        "mechanism": "false_alarm_rule_range", "rationale": "CLO coupon legitimately >25%"})
    assert rep.ok, rep.errors
    assert not any("not in known vocabulary" in w for w in rep.warnings)


def test_unknown_mechanism_is_warning_not_error():
    # observed trial mechanism outside the spec enum must pass (warn only).
    rep = verdict_leaf.validate_verdict(_real(mechanism="cash_equivalent_leak"))
    assert rep.ok, rep.errors
    rep2 = verdict_leaf.validate_verdict(_real(mechanism="totally_new_thing"))
    assert rep2.ok
    assert any("not in known vocabulary" in w for w in rep2.warnings)


def test_findings_multi_defect_ok():
    # TorcSill-style: one row, two defects (PIK-in-interest + duplicate).
    rep = verdict_leaf.validate_verdict(_real(findings=[
        {"mechanism": "genuine_value_defect", "detail": "all-PIK stored into interest_rate",
         "fix_class": "all_pik_normalization", "citation": {"table_index": 5, "row_index": 12}},
        {"mechanism": "dimension_double_count", "detail": "rows 12 and 13 duplicate",
         "fix_class": "dedup", "citation": {"table_index": 5, "row_index": 13}},
    ]))
    assert rep.ok, rep.errors


def test_findings_citation_grounds_real_error():
    # No culprit_citations and no anchor disagreement, but a finding citation grounds it.
    rep = verdict_leaf.validate_verdict(_real(culprit_citations=[], anchor_used="", findings=[
        {"mechanism": "rate_scale", "detail": "source 5%, stored 50", "fix_class": "rate_rescale",
         "citation": {"quoted_text": "5.00 %"}},
    ]))
    assert rep.ok, rep.errors


def test_findings_must_be_list():
    rep = verdict_leaf.validate_verdict(_real(findings={"not": "a list"}))
    assert not rep.ok


def test_findings_unknown_fix_class_warns_not_errors():
    rep = verdict_leaf.validate_verdict(_real(findings=[
        {"mechanism": "subtotal_leak", "detail": "x", "fix_class": "made_up_class",
         "citation": {"table_index": 1, "row_index": 1}}]))
    assert rep.ok, rep.errors
    assert any("fix_class not in known vocabulary" in w for w in rep.warnings)


def test_false_alarm_minimal_ok():
    rep = verdict_leaf.validate_verdict({
        "review_id": "RVQ_REV_x", "verdict": "false_alarm", "confidence": 0.8,
        "rationale": "check is wrong",
    })
    assert rep.ok, rep.errors


def _amb(**over):
    base = {"review_id": "RVQ_REV_a", "verdict": "ambiguous", "confidence": 0.3,
            "ambiguity_basis": "source_checked", "rationale": "looked, unclear"}
    base.update(over)
    return base


def test_ambiguous_requires_basis():
    bad = _amb()
    del bad["ambiguity_basis"]
    rep = verdict_leaf.validate_verdict(bad)
    assert not rep.ok
    assert any("ambiguity_basis" in e for e in rep.errors)


def test_ambiguous_bad_basis_value_is_error():
    rep = verdict_leaf.validate_verdict(_amb(ambiguity_basis="dunno"))
    assert not rep.ok


def test_ambiguous_source_checked_ok():
    assert verdict_leaf.validate_verdict(_amb(ambiguity_basis="source_checked")).ok


def test_ambiguous_source_unavailable_ok_with_escalate():
    rep = verdict_leaf.validate_verdict(_amb(ambiguity_basis="source_unavailable", escalate=True))
    assert rep.ok, rep.errors


def test_ambiguous_source_unavailable_without_escalate_warns():
    rep = verdict_leaf.validate_verdict(_amb(ambiguity_basis="source_unavailable", escalate=False))
    assert rep.ok  # warning, not error
    assert any("escalate" in w for w in rep.warnings)


def test_decided_verdict_cannot_claim_source_unavailable():
    # A real_error/false_alarm that says it had no source is contradictory -> hard error.
    rep = verdict_leaf.validate_verdict(_real(ambiguity_basis="source_unavailable"))
    assert not rep.ok
    assert any("source_unavailable" in e for e in rep.errors)
    rep2 = verdict_leaf.validate_verdict({
        "review_id": "RVQ_REV_y", "verdict": "false_alarm", "confidence": 0.6,
        "ambiguity_basis": "source_unavailable", "rationale": "r"})
    assert not rep2.ok


def test_decided_verdict_ignores_source_checked_basis():
    # A stray source_checked on a decided verdict is harmless (ignored, not rejected).
    assert verdict_leaf.validate_verdict(_real(ambiguity_basis="source_checked")).ok


def test_bad_verdict_value():
    rep = verdict_leaf.validate_verdict(_real(verdict="not_a_verdict"))
    assert not rep.ok


def test_confidence_out_of_range_and_missing():
    assert not verdict_leaf.validate_verdict(_real(confidence=1.5)).ok
    bad = _real()
    del bad["confidence"]
    assert not verdict_leaf.validate_verdict(bad).ok


def test_escalate_must_be_bool():
    assert not verdict_leaf.validate_verdict(_real(escalate="yes")).ok


def test_non_object_is_error():
    assert not verdict_leaf.validate_verdict([1, 2, 3]).ok


def test_validate_dir_missing_and_invalid(tmp_path):
    (tmp_path / "RVQ_a.json").write_text(json.dumps(_real(review_id="RVQ_a")), encoding="utf-8")
    (tmp_path / "RVQ_b.json").write_text(json.dumps(_real(review_id="RVQ_b", verdict="bad")), encoding="utf-8")
    summary = verdict_leaf.validate_dir(tmp_path, expected_review_ids={"RVQ_a", "RVQ_b", "RVQ_c"})
    assert not summary["ok"]
    assert summary["n_files"] == 2
    assert summary["n_valid"] == 1
    assert any("missing verdict for review_id: RVQ_c" in c for c in summary["cross_errors"])


def test_validate_dir_restrict_to_expected_ignores_other_batches(tmp_path):
    # Shared verdicts dir: a sibling batch's verdict must NOT be flagged "not in worklist".
    (tmp_path / "RVQ_mine.json").write_text(json.dumps(_real(review_id="RVQ_mine")), encoding="utf-8")
    (tmp_path / "RVQ_other.json").write_text(json.dumps(_real(review_id="RVQ_other")), encoding="utf-8")
    # Default (strict): the sibling verdict is an error.
    strict = verdict_leaf.validate_dir(tmp_path, expected_review_ids={"RVQ_mine"})
    assert not strict["ok"]
    # Restricted: only my batch's verdict is validated; sibling ignored.
    scoped = verdict_leaf.validate_dir(tmp_path, expected_review_ids={"RVQ_mine"},
                                       restrict_to_expected=True)
    assert scoped["ok"], scoped["cross_errors"]
    assert scoped["n_files"] == 1
    # Missing expected still caught even when restricted.
    miss = verdict_leaf.validate_dir(tmp_path, expected_review_ids={"RVQ_mine", "RVQ_gone"},
                                     restrict_to_expected=True)
    assert any("missing verdict for review_id: RVQ_gone" in c for c in miss["cross_errors"])


def test_validate_dir_all_valid(tmp_path):
    (tmp_path / "RVQ_a.json").write_text(json.dumps(_real(review_id="RVQ_a")), encoding="utf-8")
    summary = verdict_leaf.validate_dir(tmp_path, expected_review_ids={"RVQ_a"})
    assert summary["ok"], summary["cross_errors"]


def test_wilson_basic():
    p, lo, hi = verdict_leaf.wilson(1, 4)
    assert 0.0 <= lo <= p <= hi <= 1.0
    nan_p, nlo, nhi = verdict_leaf.wilson(0, 0)
    assert nan_p != nan_p  # nan
    assert (nlo, nhi) == (0.0, 1.0)
