"""Tests for the anchor-adjudicator driver (verify/promote against real fund_financials) and the
per-cik override wiring back into the fixer's anchor candidates. Output paths -> tmp."""
import json

import pytest

from scripts.agent_anchor import run_anchor
from scripts.agent_investigate import run_investigation


def _write_leaf(path, grand_total, *, method="sum_of_schedules"):
    path.parent.mkdir(parents=True, exist_ok=True)
    comps = [{"label": "non-affiliated", "value": 691_956_192.0, "source": "companyfacts IOAFV"},
             {"label": "affiliated", "value": round(grand_total - 691_956_192.0, 2),
              "source": "SOI affiliated total row"}]
    if method == "single_tag":
        comps = [{"label": "tag", "value": grand_total, "source": "IOAFV"}]
    path.write_text(json.dumps({
        "cik": "1715933", "target_quarter": "2025-06-30", "grand_total": grand_total,
        "method": method, "components": comps, "companyfacts_fv": 691_956_192.0,
        "evidence": [{"source": "filing", "quote": "Total Investments"}],
        "rationale": "grand total", "confidence": 0.9}), encoding="utf-8")


@pytest.mark.needs_cache
def test_verify_accepts_real_grand_total(tmp_path, monkeypatch):
    # real 1715933 2025-06-30: total_assets ~1.098B. A ~1.094B grand total closes -> HIGH.
    monkeypatch.setattr(run_anchor, "BASE", tmp_path / "agent_anchor")
    _write_leaf(run_anchor._leaf_path("1715933", "2025-06-30"), 1_094_088_266.0)
    res = run_anchor.verify("1715933", "2025-06-30")
    assert res["ok"] and res["tier"] == "HIGH", res


def test_verify_uses_filing_total_assets_when_companyfacts_null(tmp_path, monkeypatch):
    # (b) companyfacts total_assets NULL (lagged quarter) -> verify falls back to the leaf's
    # filing-sourced total_assets and caps the tier at MEDIUM. Stub fund_financials rather than
    # rely on a real lagged quarter: companyfacts catches up over time (1377936 2026-02-28 was
    # null when this test was written, then filled, breaking the premise).
    monkeypatch.setattr(run_anchor, "BASE", tmp_path / "agent_anchor")
    monkeypatch.setattr(run_anchor, "fund_financials", lambda cik: {})
    p = run_anchor._leaf_path("1377936", "2026-02-28")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({
        "cik": "1377936", "target_quarter": "2026-02-28", "grand_total": 1000.0, "method": "single_tag",
        "components": [{"label": "Total Investments", "value": 1000.0, "source": "SOI total row"}],
        "total_assets": 1050.0, "total_assets_source": "balance sheet Total assets line",
        "evidence": [{"source": "filing", "quote": "Total Investments 1000"}], "confidence": 0.8}),
        encoding="utf-8")
    res = run_anchor.verify("1377936", "2026-02-28")
    assert res["total_assets_source"] == "filing"
    assert res["tier"] == "MEDIUM" and res["ok"], res


def test_verify_rejects_subtotal(tmp_path, monkeypatch):
    # the WRONG anchor (692M companyfacts subtotal) proposed as grand total -> 63% invested -> reject
    monkeypatch.setattr(run_anchor, "BASE", tmp_path / "agent_anchor")
    _write_leaf(run_anchor._leaf_path("1715933", "2025-06-30"), 691_956_192.0, method="single_tag")
    res = run_anchor.verify("1715933", "2025-06-30")
    assert not res["ok"] and res["tier"] == "NONE"


@pytest.mark.needs_cache
def test_promote_writes_override_only_when_verified(tmp_path, monkeypatch):
    monkeypatch.setattr(run_anchor, "BASE", tmp_path / "agent_anchor")
    monkeypatch.setattr(run_anchor, "ANCHOR_OVERRIDES", tmp_path / "overrides")
    # good -> promoted
    _write_leaf(run_anchor._leaf_path("1715933", "2025-06-30"), 1_094_088_266.0)
    p = run_anchor.promote("1715933", "2025-06-30")
    assert p["status"] == "promoted"
    assert (tmp_path / "overrides" / "1715933" / "2025-06-30.json").exists()
    # bad -> refused, no override written
    _write_leaf(run_anchor._leaf_path("1715933", "2025-09-30"), 691_956_192.0, method="single_tag")
    r = run_anchor.promote("1715933", "2025-09-30")
    assert r["status"] == "refused"
    assert not (tmp_path / "overrides" / "1715933" / "2025-09-30.json").exists()


def test_override_feeds_back_into_anchor_candidates(tmp_path, monkeypatch):
    monkeypatch.setattr(run_investigation, "ANCHOR_OVERRIDES", tmp_path / "ov")
    # a verified grand total that DISAGREES with companyfacts -> companyfacts dropped, override kept
    leaf = tmp_path / "ov" / "1715933" / "2025-06-30.json"
    _write_leaf(leaf, 1_094_088_266.0)
    cand = run_investigation.load_anchor_candidates("1715933")
    q = cand.get("2025-06-30", {})
    assert q.get("printed_schedule_total") == 1_094_088_266.0
    assert "companyfacts_fv" not in q          # the incomplete subtotal was dropped
    from pipeline.anchor_validation import classify_anchors
    assert classify_anchors(q).tier == "MEDIUM"   # single verified strong anchor


@pytest.mark.needs_cache
def test_override_agreeing_with_companyfacts_yields_high(tmp_path, monkeypatch):
    monkeypatch.setattr(run_investigation, "ANCHOR_OVERRIDES", tmp_path / "ov")
    # an override that AGREES with companyfacts (692M) -> keep both -> HIGH (corroborated)
    leaf = tmp_path / "ov" / "1715933" / "2025-06-30.json"
    _write_leaf(leaf, 691_956_192.0, method="single_tag")
    q = run_investigation.load_anchor_candidates("1715933").get("2025-06-30", {})
    from pipeline.anchor_validation import classify_anchors
    assert classify_anchors(q).tier == "HIGH"
