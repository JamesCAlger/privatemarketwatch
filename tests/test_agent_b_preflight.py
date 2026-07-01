"""Tests for Agent B1 dispatch preflight + run_review finalize (tmp-confined I/O)."""

from __future__ import annotations

import csv
import json

import pytest

from pipeline import verdict_leaf
from scripts.agent_b import dispatch_preflight as pf
from scripts.agent_b import run_review


def _bundle(rid, *, completeness="source_artifact", engine="conservation", rule="fv_conservation"):
    return {
        "schema_version": "review-bundle.v1",
        "review_id": rid,
        "lane": "blocker",
        "anchor": "companyfacts_fv",
        "engine": engine,
        "rule_name": rule,
        "mechanism": "",
        "cik": "0001849894",
        "report_date": "2025-03-31",
        "period": "2025-03-31",
        "unit_label": "0001849894",
        "evidence_completeness": completeness,
        "has_raw_source": True,
        "evidence_items": [{"evidence_id": "flag", "description": "x", "data": {}}],
    }


def _write_bundle(bundles_dir, rid, **kw):
    bundles_dir.mkdir(parents=True, exist_ok=True)
    (bundles_dir / f"{rid}.json").write_text(json.dumps(_bundle(rid, **kw)), encoding="utf-8")


def _write_worklist(batch_dir, rows):
    batch_dir.mkdir(parents=True, exist_ok=True)
    cols = ["review_id", "engine", "lane", "cik", "report_date", "rule_name", "class_hint", "bundle_path"]
    with open(batch_dir / "worklist.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in rows:
            w.writerow({c: r.get(c, "") for c in cols})


def _dirs(tmp_path):
    return {
        "base_dir": tmp_path / "agent_b",
        "bundles_dir": tmp_path / "bundles",
        "verdicts_dir": tmp_path / "verdicts",
    }


def test_preflight_happy_path(tmp_path):
    d = _dirs(tmp_path)
    batch = "B1"
    batch_dir = d["base_dir"] / "batch" / batch
    for rid in ("RVQ_BLK_aaa", "RVQ_BLK_bbb"):
        _write_bundle(d["bundles_dir"], rid)
    _write_worklist(batch_dir, [
        {"review_id": "RVQ_BLK_aaa", "engine": "conservation", "rule_name": "fv_conservation"},
        {"review_id": "RVQ_BLK_bbb", "engine": "conservation", "rule_name": "fv_conservation"},
    ])

    res = pf.preflight_batch(batch, base_dir=d["base_dir"], bundles_dir=d["bundles_dir"],
                             verdicts_dir=d["verdicts_dir"])
    assert res["n_dispatch"] == 2
    assert res["n_auto_resolved"] == 0
    manifest = json.loads((batch_dir / "manifest.json").read_text())
    assert {r["review_id"] for r in manifest["rows"]} == {"RVQ_BLK_aaa", "RVQ_BLK_bbb"}
    for rid in ("RVQ_BLK_aaa", "RVQ_BLK_bbb"):
        prompt = (batch_dir / "prompts" / f"{rid}.md").read_text()
        assert rid in prompt
        assert "B1_adjudication_contract.md" in prompt
        assert "evidence_cli.py" in prompt
        # env-fix: prompt names the exact interpreter (absolute) + the ambiguity basis
        assert pf.WORKER_PYTHON in prompt
        assert "ambiguity_basis" in prompt
        assert "source_unavailable" in prompt
        # blinded: the prompt must not leak a verdict answer
        assert "real_error" in prompt  # only as an allowed output value, fine
    # the manifest records the interpreter + the import roots the dispatcher must grant
    # the sandbox read on (so the worker can import pandas et al.)
    assert manifest["worker_python"] == pf.WORKER_PYTHON
    assert isinstance(manifest["worker_read_dirs"], list) and manifest["worker_read_dirs"]
    assert "user_site_enabled" in manifest


def test_preflight_short_circuit_writes_auto_verdict(tmp_path):
    d = _dirs(tmp_path)
    batch = "B2"
    batch_dir = d["base_dir"] / "batch" / batch
    _write_bundle(d["bundles_dir"], "RVQ_BLK_ok")
    _write_bundle(d["bundles_dir"], "RVQ_BLK_no", completeness="ledger_only")
    _write_worklist(batch_dir, [
        {"review_id": "RVQ_BLK_ok"},
        {"review_id": "RVQ_BLK_no"},
    ])
    res = pf.preflight_batch(batch, base_dir=d["base_dir"], bundles_dir=d["bundles_dir"],
                             verdicts_dir=d["verdicts_dir"])
    assert res["n_dispatch"] == 1
    assert res["n_auto_resolved"] == 1
    auto = json.loads((d["verdicts_dir"] / "RVQ_BLK_no.json").read_text())
    assert auto["verdict"] == "ambiguous"
    assert auto["ambiguity_basis"] == "source_unavailable"
    assert auto["auto"] is True
    assert auto["evidence_completeness"] == "ledger_only"
    # the auto verdict must itself pass the leaf screen
    assert verdict_leaf.validate_verdict(auto).ok


def test_preflight_rejects_review_id_mismatch(tmp_path):
    d = _dirs(tmp_path)
    batch = "B3"
    batch_dir = d["base_dir"] / "batch" / batch
    # bundle file named for one rid but carrying another internally
    (d["bundles_dir"]).mkdir(parents=True, exist_ok=True)
    (d["bundles_dir"] / "RVQ_BLK_x.json").write_text(json.dumps(_bundle("RVQ_BLK_other")), encoding="utf-8")
    _write_worklist(batch_dir, [{"review_id": "RVQ_BLK_x"}])
    with pytest.raises(pf.PreflightError):
        pf.preflight_batch(batch, base_dir=d["base_dir"], bundles_dir=d["bundles_dir"],
                           verdicts_dir=d["verdicts_dir"])


def test_preflight_rejects_missing_bundle(tmp_path):
    d = _dirs(tmp_path)
    batch = "B4"
    batch_dir = d["base_dir"] / "batch" / batch
    _write_worklist(batch_dir, [{"review_id": "RVQ_BLK_ghost"}])
    with pytest.raises(pf.PreflightError):
        pf.preflight_batch(batch, base_dir=d["base_dir"], bundles_dir=d["bundles_dir"],
                           verdicts_dir=d["verdicts_dir"])


def test_preflight_rejects_bad_schema_version(tmp_path):
    d = _dirs(tmp_path)
    batch = "B5"
    batch_dir = d["base_dir"] / "batch" / batch
    (d["bundles_dir"]).mkdir(parents=True, exist_ok=True)
    b = _bundle("RVQ_BLK_v")
    b["schema_version"] = "review-bundle.v999"
    (d["bundles_dir"] / "RVQ_BLK_v.json").write_text(json.dumps(b), encoding="utf-8")
    _write_worklist(batch_dir, [{"review_id": "RVQ_BLK_v"}])
    with pytest.raises(pf.PreflightError):
        pf.preflight_batch(batch, base_dir=d["base_dir"], bundles_dir=d["bundles_dir"],
                           verdicts_dir=d["verdicts_dir"])


def test_preflight_rejects_existing_verdict(tmp_path):
    d = _dirs(tmp_path)
    batch = "B6"
    batch_dir = d["base_dir"] / "batch" / batch
    _write_bundle(d["bundles_dir"], "RVQ_BLK_dup")
    _write_worklist(batch_dir, [{"review_id": "RVQ_BLK_dup"}])
    d["verdicts_dir"].mkdir(parents=True, exist_ok=True)
    (d["verdicts_dir"] / "RVQ_BLK_dup.json").write_text(json.dumps({"review_id": "RVQ_BLK_dup"}), encoding="utf-8")
    with pytest.raises(pf.PreflightError):
        pf.preflight_batch(batch, base_dir=d["base_dir"], bundles_dir=d["bundles_dir"],
                           verdicts_dir=d["verdicts_dir"])


def test_finalize_routes_and_summarizes(tmp_path):
    d = _dirs(tmp_path)
    batch = "F1"
    batch_dir = d["base_dir"] / "batch" / batch
    batch_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "batch_id": batch,
        "verdicts_dir": str(d["verdicts_dir"]),
        "rows": [
            {"review_id": "RVQ_BLK_aaa", "rule_name": "fv_conservation"},
            {"review_id": "RVQ_BLK_bbb", "rule_name": "fv_conservation"},
            {"review_id": "RVQ_REV_ccc", "rule_name": "C113"},
            {"review_id": "RVQ_REV_ddd", "rule_name": "C113"},
        ],
        "auto_resolved": [{"review_id": "RVQ_BLK_zzz"}],
    }
    (batch_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    d["verdicts_dir"].mkdir(parents=True, exist_ok=True)
    verds = {
        "RVQ_BLK_aaa": {"review_id": "RVQ_BLK_aaa", "verdict": "real_error", "mechanism": "subtotal_leak",
                        "confidence": 0.9, "culprit_citations": [{"quoted_text": "x"}], "rationale": "r"},
        "RVQ_BLK_bbb": {"review_id": "RVQ_BLK_bbb", "verdict": "false_alarm", "confidence": 0.7, "rationale": "r"},
        # genuine ambiguous (read the source) -> human
        "RVQ_REV_ccc": {"review_id": "RVQ_REV_ccc", "verdict": "ambiguous", "confidence": 0.3,
                        "ambiguity_basis": "source_checked", "rationale": "r"},
        # fail-closed ambiguous (could not read source) -> coverage_no_source, NOT human
        "RVQ_REV_ddd": {"review_id": "RVQ_REV_ddd", "verdict": "ambiguous", "confidence": 0.1,
                        "ambiguity_basis": "source_unavailable", "escalate": True, "rationale": "cli failed"},
        "RVQ_BLK_zzz": {"review_id": "RVQ_BLK_zzz", "verdict": "ambiguous", "confidence": 0.0,
                        "ambiguity_basis": "source_unavailable",
                        "escalate": True, "auto": True, "rationale": "auto"},
    }
    for rid, v in verds.items():
        (d["verdicts_dir"] / f"{rid}.json").write_text(json.dumps(v), encoding="utf-8")

    res = run_review.finalize(batch, base_dir=d["base_dir"], verdicts_dir=d["verdicts_dir"],
                              release_locks=False)
    assert res["schema_ok"], res["cross_errors"]
    assert res["n_dispatched"] == 4
    assert res["n_auto"] == 1

    routes = {r["review_id"]: r["route"] for r in csv.DictReader(open(batch_dir / "routing.csv"))}
    assert routes["RVQ_BLK_aaa"] == "b2_remediator_queue"
    assert routes["RVQ_BLK_bbb"] == "rule_scoping_queue"
    assert routes["RVQ_REV_ccc"] == "human"
    assert routes["RVQ_REV_ddd"] == "coverage_no_source"
    assert routes["RVQ_BLK_zzz"] == "coverage"

    cons = next(r for r in res["per_rule"] if r["rule_name"] == "fv_conservation")
    assert cons["real_error"] == 1 and cons["false_alarm"] == 1 and cons["n_decided"] == 2
    # C113: one genuine ambiguous, one fail-closed -> tallied separately, never conflated
    c113 = next(r for r in res["per_rule"] if r["rule_name"] == "C113")
    assert c113["ambiguous"] == 1 and c113["no_source"] == 1 and c113["n_decided"] == 0


def test_finalize_parity_compare(tmp_path):
    d = _dirs(tmp_path)
    batch = "P1"
    batch_dir = d["base_dir"] / "batch" / batch
    batch_dir.mkdir(parents=True, exist_ok=True)
    (batch_dir / "manifest.json").write_text(json.dumps({
        "batch_id": batch, "verdicts_dir": str(d["verdicts_dir"]),
        "rows": [{"review_id": "RVQ_BLK_aaa", "rule_name": "fv_conservation"},
                 {"review_id": "RVQ_BLK_bbb", "rule_name": "fv_conservation"}],
        "auto_resolved": [],
    }), encoding="utf-8")
    d["verdicts_dir"].mkdir(parents=True, exist_ok=True)
    baseline = tmp_path / "baseline"
    baseline.mkdir()
    # fleet
    (d["verdicts_dir"] / "RVQ_BLK_aaa.json").write_text(json.dumps(
        {"review_id": "RVQ_BLK_aaa", "verdict": "real_error", "mechanism": "subtotal_leak",
         "confidence": 0.9, "culprit_citations": [{"quoted_text": "x"}], "rationale": "r"}), encoding="utf-8")
    (d["verdicts_dir"] / "RVQ_BLK_bbb.json").write_text(json.dumps(
        {"review_id": "RVQ_BLK_bbb", "verdict": "false_alarm", "confidence": 0.7, "rationale": "r"}), encoding="utf-8")
    # baseline: aaa agrees, bbb disagrees
    (baseline / "RVQ_BLK_aaa.json").write_text(json.dumps({"review_id": "RVQ_BLK_aaa", "verdict": "real_error"}), encoding="utf-8")
    (baseline / "RVQ_BLK_bbb.json").write_text(json.dumps({"review_id": "RVQ_BLK_bbb", "verdict": "ambiguous"}), encoding="utf-8")

    res = run_review.finalize(batch, base_dir=d["base_dir"], verdicts_dir=d["verdicts_dir"],
                              release_locks=False, compare_baseline=baseline)
    assert res["parity"]["n_compared"] == 2
    assert res["parity"]["n_agree"] == 1
    assert res["parity"]["agreement"] == 0.5
    parity = {r["review_id"]: r["match"] for r in csv.DictReader(open(batch_dir / "parity.csv"))}
    assert parity["RVQ_BLK_aaa"] == "True"
    assert parity["RVQ_BLK_bbb"] == "False"


def test_review_lock_roundtrip(tmp_path, monkeypatch):
    from scripts.agent_b import review_lock
    monkeypatch.setattr(review_lock, "LOCK_DIR", tmp_path / "locks")
    assert review_lock.acquire("RVQ_BLK_lock", now=1000.0) is True
    assert review_lock.is_locked("RVQ_BLK_lock", now=1000.0) is True
    assert review_lock.acquire("RVQ_BLK_lock", now=1000.0) is False  # held
    # stale -> reclaimable
    assert review_lock.is_locked("RVQ_BLK_lock", now=1000.0 + 4000) is False
    review_lock.release("RVQ_BLK_lock")
    assert review_lock.is_locked("RVQ_BLK_lock", now=1000.0) is False
