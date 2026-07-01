"""Tests for the B2 wrapper-patch applier (subtotal_filter) + the trial overlay reload."""

from __future__ import annotations

import json

import pytest

from pipeline import agent_b2_wrapper_patch as wp
from pipeline import bdc_xbrl_wrapper as bw


def _dispatch_wrapper(cik, markers):
    return {
        "schema_version": "bdc-xbrl-wrapper.v3",
        "cik": cik,
        "version": 1,
        "dispatch": {"rule_prefix": "TST", "aggregate_markers": list(markers)},
    }


def _write_src(tmp_path, cik, markers):
    src_dir = tmp_path / "src"
    src_dir.mkdir(exist_ok=True)
    (src_dir / f"{cik}.json").write_text(json.dumps(_dispatch_wrapper(cik, markers)), encoding="utf-8")
    return src_dir


def test_subtotal_filter_merges_patterns(tmp_path):
    cik = "0001633858"
    src_dir = _write_src(tmp_path, cik, ["total investments"])
    out_dir = tmp_path / "trial"
    audit = wp.apply_subtotal_filter(
        cik, {"patterns": ["Total Portfolio Rollup", "TOTAL INVESTMENTS"]},
        out_wrapper_dir=out_dir, source_wrapper_dir=src_dir,
        provenance={"source_review_ids": ["RVQ_BLK_x"], "confidence": 0.9})
    assert audit["status"] == "ok"
    # new marker added (lowercased); the existing one not duplicated
    assert "total portfolio rollup" in audit["patterns_added"]
    assert "total investments" not in audit["patterns_added"]  # already present (case-insensitive)
    out = json.loads((out_dir / f"{cik}.json").read_text())
    markers = out["dispatch"]["aggregate_markers"]
    assert "total investments" in markers and "total portfolio rollup" in markers
    # provenance recorded
    assert out["b2_provenance"][0]["source_review_ids"] == ["RVQ_BLK_x"]
    # production source untouched
    src = json.loads((src_dir / f"{cik}.json").read_text())
    assert "total portfolio rollup" not in src["dispatch"]["aggregate_markers"]


def test_subtotal_filter_missing_wrapper_fails_safe(tmp_path):
    audit = wp.apply_subtotal_filter("0009999999", {"patterns": ["x"]},
                                     out_wrapper_dir=tmp_path / "trial",
                                     source_wrapper_dir=tmp_path / "src")
    assert audit["status"] == "error"
    assert not (tmp_path / "trial" / "0009999999.json").exists()


def test_subtotal_filter_non_dispatch_wrapper_fails_safe(tmp_path):
    cik = "0001234567"
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    # staging-style wrapper (no dispatch) -> subtotal_filter does not apply
    (src_dir / f"{cik}.json").write_text(json.dumps(
        {"schema_version": "bdc-xbrl-wrapper.v3", "cik": cik, "staging": {"strategy": "x"}}),
        encoding="utf-8")
    audit = wp.apply_subtotal_filter(cik, {"patterns": ["total"]},
                                     out_wrapper_dir=tmp_path / "trial", source_wrapper_dir=src_dir)
    assert audit["status"] == "error"
    assert "dispatch" in audit["message"]


def test_reload_overlay_takes_effect_then_restores(tmp_path):
    cik = "0001633858"
    # only run if this CIK has a production dispatch wrapper (so restore is meaningful)
    prod = bw.get_wrapper_spec(cik)
    trial_dir = tmp_path / "trial"
    trial_dir.mkdir()
    (trial_dir / f"{cik}.json").write_text(json.dumps(
        _dispatch_wrapper(cik, ["total investments", "zzz_trial_marker"])), encoding="utf-8")
    try:
        bw.reload_wrapper_specs(override_dir=trial_dir)
        spec = bw.get_wrapper_spec(cik)
        assert spec is not None
        assert "zzz_trial_marker" in spec.aggregate_markers
        # a different production CIK still loads (overlay didn't wipe production)
        assert len(bw.WRAPPER_SPECS) > 1
    finally:
        bw.reload_wrapper_specs()  # restore production
    restored = bw.get_wrapper_spec(cik)
    if restored is not None:
        assert "zzz_trial_marker" not in restored.aggregate_markers
