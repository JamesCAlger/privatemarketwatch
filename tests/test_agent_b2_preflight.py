"""Tests for the Agent B2 remediation dispatch preflight (tmp-confined I/O)."""

from __future__ import annotations

import csv
import json

import pytest

from scripts.agent_b2 import dispatch_preflight as pf


def _verdict(rid, *, mechanism="subtotal_leak"):
    return {"review_id": rid, "verdict": "real_error", "mechanism": mechanism, "confidence": 0.9,
            "culprit_citations": [{"table_index": 7, "row_index": 41,
                                   "quoted_text": "Total Senior Unsecured | 42,712 | 40,061 | 18.04%"}],
            "rationale": "leaked subtotal"}


def _write_worklist(batch_dir, rows):
    batch_dir.mkdir(parents=True, exist_ok=True)
    cols = ["cik", "fix_class", "stage", "mechanism", "fix_class_derived", "quarters",
            "rule_names", "n_findings", "source_review_ids"]
    with open(batch_dir / "worklist.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in rows:
            w.writerow({c: r.get(c, "") for c in cols})


def _dirs(tmp_path):
    return {"base_dir": tmp_path / "agent_b2", "verdicts_dir": tmp_path / "verdicts",
            "bundles_dir": tmp_path / "bundles", "corrections_dir": tmp_path / "corrections"}


def _seed(d, rid, *, cik="0001743415"):
    d["verdicts_dir"].mkdir(parents=True, exist_ok=True)
    (d["verdicts_dir"] / f"{rid}.json").write_text(json.dumps(_verdict(rid)), encoding="utf-8")
    d["bundles_dir"].mkdir(parents=True, exist_ok=True)
    (d["bundles_dir"] / f"{rid}.json").write_text(
        json.dumps({"review_id": rid, "cik": cik}), encoding="utf-8"
    )


def test_preflight_builds_packet_manifest_and_prompt(tmp_path):
    d = _dirs(tmp_path)
    batch = "B2T"
    batch_dir = d["base_dir"] / "batch" / batch
    _seed(d, "RVQ_BLK_aaa")
    _write_worklist(batch_dir, [{"cik": "0001743415", "fix_class": "subtotal_filter",
                                 "mechanism": "subtotal_leak", "quarters": "2024-12-31",
                                 "source_review_ids": "RVQ_BLK_aaa"}])
    res = pf.preflight_batch(batch, base_dir=d["base_dir"], verdicts_dir=d["verdicts_dir"],
                             bundles_dir=d["bundles_dir"], corrections_dir=d["corrections_dir"],
                             fix_class="subtotal_filter")
    assert res["n_dispatch"] == 1
    manifest = json.loads((batch_dir / "manifest.json").read_text())
    row = manifest["rows"][0]
    assert row["cik"] == "0001743415" and row["fix_class"] == "subtotal_filter"
    assert row["correction_path"].endswith("0001743415\\subtotal_filter.json") or \
        row["correction_path"].endswith("0001743415/subtotal_filter.json")
    assert (d["corrections_dir"] / "0001743415").is_dir()
    assert manifest["worker_python"] and manifest["worker_read_dirs"]
    prompt = (batch_dir / "prompts" / "0001743415__subtotal_filter.md").read_text()
    # the prompt carries B1's localized citation plus parent-validation instructions.
    assert "Total Senior Unsecured" in prompt
    assert "Do not call shell commands" in prompt
    assert "Write the relative" in prompt
    assert "target quarter(s): 2024-12-31" in prompt
    assert "validate_corrections.py" in prompt
    assert "--expected-fix-class" in prompt
    assert "Evidence citations to copy" in prompt
    assert pf.WORKER_PYTHON in prompt


def test_prompt_contract_excerpt_matches_fix_class(tmp_path):
    # Regression: the contract excerpt was hard-coded to comparative_period_filter,
    # so a subtotal_filter worker authored {"report_date": ...} and failed the
    # validator ("unexpected param(s)"). The excerpt must come from TEMPLATE_REGISTRY
    # for the packet's own fix_class.
    d = _dirs(tmp_path)
    batch = "B2X"
    batch_dir = d["base_dir"] / "batch" / batch
    _seed(d, "RVQ_BLK_aaa")
    _write_worklist(batch_dir, [{"cik": "0001743415", "fix_class": "subtotal_filter",
                                 "mechanism": "subtotal_leak", "quarters": "2024-12-31",
                                 "source_review_ids": "RVQ_BLK_aaa"}])
    pf.preflight_batch(batch, base_dir=d["base_dir"], verdicts_dir=d["verdicts_dir"],
                       bundles_dir=d["bundles_dir"], corrections_dir=d["corrections_dir"],
                       fix_class="subtotal_filter")
    prompt = (batch_dir / "prompts" / "0001743415__subtotal_filter.md").read_text()
    assert "Embedded contract excerpt for subtotal_filter" in prompt
    assert "'patterns'" in prompt
    assert "'match_mode'" in prompt
    assert '{"report_date"' not in prompt
    assert "excerpt for comparative_period_filter" not in prompt


def test_preflight_skips_packets_without_usable_citations(tmp_path):
    # A packet whose source verdicts carry no culprit citations can only produce a
    # correction that validate_corrections rejects (">=1 valid citation"). Preflight
    # must skip it with a recorded reason, not dispatch a doomed worker (q4b2t4b
    # canary lesson: Ares comparative packet burned a worker on a guaranteed reject).
    d = _dirs(tmp_path)
    batch = "B2C"
    batch_dir = d["base_dir"] / "batch" / batch
    _seed(d, "RVQ_BLK_good")
    # second packet: real_error verdict but with NO citations
    d["verdicts_dir"].mkdir(parents=True, exist_ok=True)
    v = _verdict("RVQ_BLK_nocite")
    v["culprit_citations"] = []
    (d["verdicts_dir"] / "RVQ_BLK_nocite.json").write_text(json.dumps(v), encoding="utf-8")
    (d["bundles_dir"] / "RVQ_BLK_nocite.json").write_text(
        json.dumps({"review_id": "RVQ_BLK_nocite", "cik": "0001999988"}), encoding="utf-8")
    _write_worklist(batch_dir, [
        {"cik": "0001743415", "fix_class": "subtotal_filter", "source_review_ids": "RVQ_BLK_good"},
        {"cik": "0001999988", "fix_class": "subtotal_filter", "source_review_ids": "RVQ_BLK_nocite"},
    ])
    res = pf.preflight_batch(batch, base_dir=d["base_dir"], verdicts_dir=d["verdicts_dir"],
                             bundles_dir=d["bundles_dir"], corrections_dir=d["corrections_dir"],
                             fix_class="subtotal_filter")
    assert res["n_dispatch"] == 1
    assert res["n_skipped_no_citations"] == 1
    manifest = json.loads((batch_dir / "manifest.json").read_text())
    assert manifest["skipped_no_citations"][0]["cik"] == "0001999988"
    assert "re-enrichment" in manifest["skipped_no_citations"][0]["reason"]


def test_coordinate_only_citations_survive_into_prompt(tmp_path):
    # validate_corrections accepts quote OR table/row coordinate; the prompt's copyable
    # citations JSON must not drop coordinate-only citations (Ares q4b2t4b lesson).
    d = _dirs(tmp_path)
    batch = "B2K"
    batch_dir = d["base_dir"] / "batch" / batch
    d["verdicts_dir"].mkdir(parents=True, exist_ok=True)
    v = _verdict("RVQ_BLK_coord")
    v["culprit_citations"] = [{"table_index": 190, "row_index": 5}]
    (d["verdicts_dir"] / "RVQ_BLK_coord.json").write_text(json.dumps(v), encoding="utf-8")
    d["bundles_dir"].mkdir(parents=True, exist_ok=True)
    (d["bundles_dir"] / "RVQ_BLK_coord.json").write_text(
        json.dumps({"review_id": "RVQ_BLK_coord", "cik": "0001743415"}), encoding="utf-8")
    _write_worklist(batch_dir, [{"cik": "0001743415", "fix_class": "subtotal_filter",
                                 "source_review_ids": "RVQ_BLK_coord"}])
    res = pf.preflight_batch(batch, base_dir=d["base_dir"], verdicts_dir=d["verdicts_dir"],
                             bundles_dir=d["bundles_dir"], corrections_dir=d["corrections_dir"],
                             fix_class="subtotal_filter")
    assert res["n_dispatch"] == 1 and res["n_skipped_no_citations"] == 0
    prompt = (batch_dir / "prompts" / "0001743415__subtotal_filter.md").read_text()
    assert '"table_index": 190' in prompt
    assert "coordinate-only citation" in prompt


def test_contract_excerpt_covers_all_registered_classes():
    from pipeline.correction_leaf import TEMPLATE_REGISTRY
    for fc, tpl in TEMPLATE_REGISTRY.items():
        text = pf._contract_excerpt(fc)
        assert f"Embedded contract excerpt for {fc}" in text
        for k in tpl.required:
            assert f"'{k}'" in text


def test_preflight_skips_non_actionable_packets(tmp_path):
    d = _dirs(tmp_path)
    batch = "B2N"
    batch_dir = d["base_dir"] / "batch" / batch
    _seed(d, "RVQ_BLK_aaa")
    _write_worklist(batch_dir, [
        {"cik": "0001743415", "fix_class": "subtotal_filter", "source_review_ids": "RVQ_BLK_aaa"},
        {"cik": "0001999999", "fix_class": "", "source_review_ids": "RVQ_BLK_zzz"},  # needs_human
    ])
    res = pf.preflight_batch(batch, base_dir=d["base_dir"], verdicts_dir=d["verdicts_dir"],
                             bundles_dir=d["bundles_dir"], corrections_dir=d["corrections_dir"],
                             fix_class="subtotal_filter")
    assert res["n_dispatch"] == 1  # only the actionable subtotal_filter packet


def test_preflight_rejects_non_real_error_source(tmp_path):
    d = _dirs(tmp_path)
    batch = "B2R"
    batch_dir = d["base_dir"] / "batch" / batch
    d["verdicts_dir"].mkdir(parents=True, exist_ok=True)
    (d["verdicts_dir"] / "RVQ_BLK_fa.json").write_text(
        json.dumps({"review_id": "RVQ_BLK_fa", "verdict": "false_alarm"}), encoding="utf-8")
    _write_worklist(batch_dir, [{"cik": "0001743415", "fix_class": "subtotal_filter",
                                 "source_review_ids": "RVQ_BLK_fa"}])
    with pytest.raises(pf.PreflightError):
        pf.preflight_batch(batch, base_dir=d["base_dir"], verdicts_dir=d["verdicts_dir"],
                           bundles_dir=d["bundles_dir"], corrections_dir=d["corrections_dir"],
                           fix_class="subtotal_filter")


def test_preflight_rejects_source_bundle_cik_mismatch(tmp_path):
    d = _dirs(tmp_path)
    batch = "B2C"
    batch_dir = d["base_dir"] / "batch" / batch
    _seed(d, "RVQ_BLK_aaa", cik="0009999999")
    _write_worklist(batch_dir, [{"cik": "0001743415", "fix_class": "subtotal_filter",
                                 "source_review_ids": "RVQ_BLK_aaa"}])
    with pytest.raises(pf.PreflightError, match="belongs to CIK"):
        pf.preflight_batch(batch, base_dir=d["base_dir"], verdicts_dir=d["verdicts_dir"],
                           bundles_dir=d["bundles_dir"], corrections_dir=d["corrections_dir"],
                           fix_class="subtotal_filter")


def test_preflight_rejects_existing_correction(tmp_path):
    d = _dirs(tmp_path)
    batch = "B2E"
    batch_dir = d["base_dir"] / "batch" / batch
    _seed(d, "RVQ_BLK_aaa")
    _write_worklist(batch_dir, [{"cik": "0001743415", "fix_class": "subtotal_filter",
                                 "source_review_ids": "RVQ_BLK_aaa"}])
    existing = d["corrections_dir"] / "0001743415"
    existing.mkdir(parents=True)
    (existing / "subtotal_filter.json").write_text("{}", encoding="utf-8")
    with pytest.raises(pf.PreflightError):
        pf.preflight_batch(batch, base_dir=d["base_dir"], verdicts_dir=d["verdicts_dir"],
                           bundles_dir=d["bundles_dir"], corrections_dir=d["corrections_dir"],
                           fix_class="subtotal_filter")


def test_preflight_rejects_fix_class_without_trial_applier(tmp_path):
    d = _dirs(tmp_path)
    batch = "B2U"
    batch_dir = d["base_dir"] / "batch" / batch
    # 2026-08-13: classification_fix now HAS an applier; anchor_fix remains the
    # rule-track class with no trial applier.
    _seed(d, "RVQ_BLK_aaa")
    _write_worklist(batch_dir, [{"cik": "0001743415", "fix_class": "anchor_fix",
                                 "source_review_ids": "RVQ_BLK_aaa"}])
    with pytest.raises(pf.PreflightError, match="no implemented trial applier"):
        pf.preflight_batch(batch, base_dir=d["base_dir"], verdicts_dir=d["verdicts_dir"],
                           bundles_dir=d["bundles_dir"], corrections_dir=d["corrections_dir"],
                           fix_class="anchor_fix")


def test_preflight_rejects_ambiguous_comparative_quarters(tmp_path):
    d = _dirs(tmp_path)
    batch = "B2Q"
    batch_dir = d["base_dir"] / "batch" / batch
    _seed(d, "RVQ_BLK_aaa")
    _write_worklist(batch_dir, [{"cik": "0001743415", "fix_class": "comparative_period_filter",
                                 "quarters": "2024-12-31;2025-03-31",
                                 "source_review_ids": "RVQ_BLK_aaa"}])
    with pytest.raises(pf.PreflightError, match="exactly one target quarter"):
        pf.preflight_batch(batch, base_dir=d["base_dir"], verdicts_dir=d["verdicts_dir"],
                           bundles_dir=d["bundles_dir"], corrections_dir=d["corrections_dir"],
                           fix_class="comparative_period_filter")


def test_preflight_skips_policy_fix_class_with_reason(tmp_path):
    # rule_scope asks to change a VALIDATION RULE's scope -- human basket, not a
    # worker dispatch, and not a whole-lane error.
    d = _dirs(tmp_path)
    batch = "B2P"
    batch_dir = d["base_dir"] / "batch" / batch
    _seed(d, "RVQ_BLK_aaa")
    _write_worklist(batch_dir, [
        {"cik": "0001743415", "fix_class": "subtotal_filter", "source_review_ids": "RVQ_BLK_aaa"},
        {"cik": "0001999988", "fix_class": "rule_scope", "source_review_ids": "RVQ_BLK_aaa"},
    ])
    res = pf.preflight_batch(batch, base_dir=d["base_dir"], verdicts_dir=d["verdicts_dir"],
                             bundles_dir=d["bundles_dir"], corrections_dir=d["corrections_dir"])
    assert res["n_dispatch"] == 1
    assert res["n_skipped_policy"] == 1
    manifest = json.loads((batch_dir / "manifest.json").read_text())
    assert manifest["skipped_policy"][0]["fix_class"] == "rule_scope"
    assert "human escalation basket" in manifest["skipped_policy"][0]["reason"]


def test_preflight_skips_stale_targets_against_review_queue(tmp_path):
    # Frame revalidation: a packet whose source finding no longer appears in the
    # current review queue was fixed upstream -- skip, don't dispatch (q4b2t4b lesson).
    d = _dirs(tmp_path)
    batch = "B2S"
    batch_dir = d["base_dir"] / "batch" / batch
    _seed(d, "RVQ_BLK_aaa")
    _seed(d, "RVQ_BLK_bbb", cik="0001743415")
    _write_worklist(batch_dir, [
        {"cik": "0001743415", "fix_class": "subtotal_filter", "source_review_ids": "RVQ_BLK_aaa"},
        {"cik": "0001743415", "fix_class": "dedup", "source_review_ids": "RVQ_BLK_bbb"},
    ])
    queue = tmp_path / "review_queue.csv"
    queue.write_text("review_id,lane\nRVQ_BLK_aaa,blocker\n", encoding="utf-8")
    res = pf.preflight_batch(batch, base_dir=d["base_dir"], verdicts_dir=d["verdicts_dir"],
                             bundles_dir=d["bundles_dir"], corrections_dir=d["corrections_dir"],
                             review_queue_path=queue)
    assert res["n_dispatch"] == 1          # only the still-open finding dispatches
    assert res["n_skipped_stale"] == 1     # RVQ_BLK_bbb no longer fires
    manifest = json.loads((batch_dir / "manifest.json").read_text())
    assert manifest["skipped_stale"][0]["fix_class"] == "dedup"
    assert "fixed upstream" in manifest["skipped_stale"][0]["reason"]
