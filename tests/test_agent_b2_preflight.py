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
    assert "Shell commands ARE allowed" in prompt
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


def test_preflight_rejects_missing_position_bundle_identity_failure(tmp_path):
    d = _dirs(tmp_path)
    batch = "B2I"
    batch_dir = d["base_dir"] / "batch" / batch
    _seed(d, "RVQ_BLK_identity")
    bundle_path = d["bundles_dir"] / "RVQ_BLK_identity.json"
    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    bundle["integrity_errors"] = ["source row src:0001743415-26-000001:c-9 already present"]
    bundle_path.write_text(json.dumps(bundle), encoding="utf-8")
    _write_worklist(batch_dir, [{"cik": "0001743415", "fix_class": "missing_position_add",
                                 "source_review_ids": "RVQ_BLK_identity"}])
    with pytest.raises(pf.PreflightError, match="identity-integrity"):
        pf.preflight_batch(batch, base_dir=d["base_dir"], verdicts_dir=d["verdicts_dir"],
                           bundles_dir=d["bundles_dir"], corrections_dir=d["corrections_dir"],
                           fix_class="missing_position_add")


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
    # 2026-08-13: a staged leaf awaiting its gate SKIPS the packet (iterative
    # rounds) instead of halting the lane; with no other packet the batch is empty.
    with pytest.raises(pf.PreflightError, match="existing=1"):
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


def test_prompt_grounds_holdings_identifiers_with_match_verification(tmp_path):
    # Round-4: the prompt must carry the EXACT holdings-side identifier strings
    # (from the bundle's holdings_slice) verified against current unified holdings --
    # the fix for the 20 selector-noop gate refusals (workers copied filing-citation
    # text that equality-matches nothing in the holdings frame).
    import pandas as pd
    d = _dirs(tmp_path)
    batch = "B2G"
    batch_dir = d["base_dir"] / "batch" / batch
    d["verdicts_dir"].mkdir(parents=True, exist_ok=True)
    (d["verdicts_dir"] / "RVQ_BLK_gr.json").write_text(
        json.dumps(_verdict("RVQ_BLK_gr")), encoding="utf-8")
    d["bundles_dir"].mkdir(parents=True, exist_ok=True)
    (d["bundles_dir"] / "RVQ_BLK_gr.json").write_text(json.dumps({
        "review_id": "RVQ_BLK_gr", "cik": "0001743415",
        "evidence_items": [
            {"evidence_id": "flag", "data": {"cik": "0001743415"}},
            {"evidence_id": "holdings_slice", "data": [
                {"issuer_name": "Astra Acquisition Corp.",
                 "bdc_investment_identifier": "Astra | Second-lien loan",
                 "fair_value": 1.0},
                {"issuer_name": "Ghost Issuer That Left The Frame",
                 "bdc_investment_identifier": "", "fair_value": 2.0},
            ]},
        ]}), encoding="utf-8")
    holdings = tmp_path / "holdings.parquet"
    pd.DataFrame([
        {"cik": "0001743415", "issuer_name": "Astra Acquisition Corp.",
         "bdc_investment_identifier": "Astra | Second-lien loan",
         "report_date": "2024-12-31"},
        {"cik": "0001743415", "issuer_name": "Other Co",
         "bdc_investment_identifier": "", "report_date": "2024-12-31"},
    ]).to_parquet(holdings)
    _write_worklist(batch_dir, [{"cik": "0001743415", "fix_class": "subtotal_filter",
                                 "mechanism": "subtotal_leak", "quarters": "2024-12-31",
                                 "source_review_ids": "RVQ_BLK_gr"}])
    pf.preflight_batch(batch, base_dir=d["base_dir"], verdicts_dir=d["verdicts_dir"],
                       bundles_dir=d["bundles_dir"], corrections_dir=d["corrections_dir"],
                       fix_class="subtotal_filter", holdings_path=holdings)
    prompt = (batch_dir / "prompts" / "0001743415__subtotal_filter.md").read_text()
    assert "Holdings-side selector identifiers" in prompt
    assert '"Astra Acquisition Corp."' in prompt
    assert "matches 1 current holdings row(s)" in prompt
    assert "Ghost Issuer That Left The Frame" in prompt
    assert "NO MATCH in current holdings -- do NOT use as a selector" in prompt
    manifest = json.loads((batch_dir / "manifest.json").read_text())
    assert manifest["rows"][0]["n_grounded_identifiers"] == 2


def test_prompt_grounding_unverified_without_holdings_file(tmp_path):
    d = _dirs(tmp_path)
    batch = "B2GU"
    batch_dir = d["base_dir"] / "batch" / batch
    d["verdicts_dir"].mkdir(parents=True, exist_ok=True)
    (d["verdicts_dir"] / "RVQ_BLK_gu.json").write_text(
        json.dumps(_verdict("RVQ_BLK_gu")), encoding="utf-8")
    d["bundles_dir"].mkdir(parents=True, exist_ok=True)
    (d["bundles_dir"] / "RVQ_BLK_gu.json").write_text(json.dumps({
        "review_id": "RVQ_BLK_gu", "cik": "0001743415",
        "evidence_items": [{"evidence_id": "holdings_slice",
                            "data": [{"issuer_name": "Astra Acquisition Corp."}]}],
        }), encoding="utf-8")
    _write_worklist(batch_dir, [{"cik": "0001743415", "fix_class": "subtotal_filter",
                                 "source_review_ids": "RVQ_BLK_gu"}])
    pf.preflight_batch(batch, base_dir=d["base_dir"], verdicts_dir=d["verdicts_dir"],
                       bundles_dir=d["bundles_dir"], corrections_dir=d["corrections_dir"],
                       fix_class="subtotal_filter",
                       holdings_path=tmp_path / "no_such_holdings.parquet")
    prompt = (batch_dir / "prompts" / "0001743415__subtotal_filter.md").read_text()
    assert "UNVERIFIED: holdings file unavailable at preflight" in prompt


def test_prompt_grounding_absent_notes_care(tmp_path):
    # Bundles without holdings rows: the section still appears with the caution line
    # (the worker must know selector no-ops are gate refusals).
    d = _dirs(tmp_path)
    batch = "B2GN"
    batch_dir = d["base_dir"] / "batch" / batch
    _seed(d, "RVQ_BLK_gn")
    _write_worklist(batch_dir, [{"cik": "0001743415", "fix_class": "subtotal_filter",
                                 "source_review_ids": "RVQ_BLK_gn"}])
    pf.preflight_batch(batch, base_dir=d["base_dir"], verdicts_dir=d["verdicts_dir"],
                       bundles_dir=d["bundles_dir"], corrections_dir=d["corrections_dir"],
                       fix_class="subtotal_filter", holdings_path=None)
    prompt = (batch_dir / "prompts" / "0001743415__subtotal_filter.md").read_text()
    assert "Holdings-side selector identifiers" in prompt
    assert "no holdings-side identifier rows in the source bundles" in prompt


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


def test_manifest_wave_stamping(tmp_path):
    # Each dispatch wave writes a durable manifest.NNN.json; manifest.json is a
    # latest-wave pointer. The old overwrite behavior lost every prior wave
    # (q4b2exp recorded 2 rows where 126 were dispatched).
    d = _dirs(tmp_path)
    batch = "B2W"
    batch_dir = d["base_dir"] / "batch" / batch
    _seed(d, "RVQ_BLK_aaa")
    _seed(d, "RVQ_BLK_bbb", cik="0001999988")
    _write_worklist(batch_dir, [{"cik": "0001743415", "fix_class": "subtotal_filter",
                                 "source_review_ids": "RVQ_BLK_aaa"}])
    res1 = pf.preflight_batch(batch, base_dir=d["base_dir"], verdicts_dir=d["verdicts_dir"],
                              bundles_dir=d["bundles_dir"], corrections_dir=d["corrections_dir"])
    assert res1["wave"] == 1
    assert res1["manifest_path"].endswith("manifest.001.json")
    # second wave: different packet (first cik now has a staged leaf and would be skipped)
    _write_worklist(batch_dir, [{"cik": "0001999988", "fix_class": "subtotal_filter",
                                 "source_review_ids": "RVQ_BLK_bbb"}])
    res2 = pf.preflight_batch(batch, base_dir=d["base_dir"], verdicts_dir=d["verdicts_dir"],
                              bundles_dir=d["bundles_dir"], corrections_dir=d["corrections_dir"])
    assert res2["wave"] == 2
    m1 = json.loads((batch_dir / "manifest.001.json").read_text())
    m2 = json.loads((batch_dir / "manifest.002.json").read_text())
    latest = json.loads((batch_dir / "manifest.json").read_text())
    assert m1["rows"][0]["cik"] == "0001743415" and m1["wave"] == 1
    assert m2["rows"][0]["cik"] == "0001999988" and m2["wave"] == 2
    assert latest == m2                      # pointer duplicates the last wave
    assert res2["manifest_latest"].endswith("manifest.json")


def test_preflight_stages_per_cik_holdings_csv(tmp_path):
    # Analyst mode: each packet stages a per-CIK, ALL-quarters holdings CSV under the
    # batch staging dir so the worker can compare filing values against extracted
    # values (the 0001838126 canary lesson: a unit_rescale factor authored with no
    # numeric basis because the packet withheld the extracted numbers).
    import pandas as pd
    from pathlib import Path
    d = _dirs(tmp_path)
    batch = "B2AS"
    batch_dir = d["base_dir"] / "batch" / batch
    _seed(d, "RVQ_BLK_stg")
    holdings = tmp_path / "holdings.parquet"
    pd.DataFrame([
        {"cik": "0001743415", "issuer_name": "Astra Acquisition Corp.",
         "bdc_investment_identifier": "Astra | Second-lien loan",
         "report_date": "2024-12-31", "fair_value": 100.0, "row_id": "ROW-aaa"},
        {"cik": "0001743415", "issuer_name": "Astra Acquisition Corp.",
         "bdc_investment_identifier": "Astra | Second-lien loan",
         "report_date": "2024-09-30", "fair_value": 90.0, "row_id": "ROW-bbb"},
        {"cik": "0009999999", "issuer_name": "Other Fund Position",
         "bdc_investment_identifier": "", "report_date": "2024-12-31",
         "fair_value": 5.0, "row_id": "ROW-ccc"},
    ]).to_parquet(holdings)
    _write_worklist(batch_dir, [{"cik": "0001743415", "fix_class": "subtotal_filter",
                                 "quarters": "2024-12-31",
                                 "source_review_ids": "RVQ_BLK_stg"}])
    pf.preflight_batch(batch, base_dir=d["base_dir"], verdicts_dir=d["verdicts_dir"],
                       bundles_dir=d["bundles_dir"], corrections_dir=d["corrections_dir"],
                       fix_class="subtotal_filter", holdings_path=holdings)
    manifest = json.loads((batch_dir / "manifest.json").read_text())
    staged = manifest["rows"][0]["holdings_csv_path"]
    assert staged
    assert (batch_dir / "staging") in Path(staged).parents
    df = pd.read_csv(staged)
    assert set(df["cik"].astype(str).str.zfill(10)) == {"0001743415"}
    assert len(df) == 2                     # ALL quarters for the cik; other ciks excluded
    assert "row_id" in df.columns and "fair_value" in df.columns
    prompt = (batch_dir / "prompts" / "0001743415__subtotal_filter.md").read_text()
    assert staged in prompt


def test_preflight_stages_holdings_csv_once_per_cik(tmp_path):
    # Two packets for the same CIK share one staged CSV (no duplicate work or files).
    import pandas as pd
    d = _dirs(tmp_path)
    batch = "B2A1"
    batch_dir = d["base_dir"] / "batch" / batch
    _seed(d, "RVQ_BLK_s1")
    _seed(d, "RVQ_BLK_s2")
    holdings = tmp_path / "holdings.parquet"
    pd.DataFrame([{"cik": "0001743415", "issuer_name": "Astra Acquisition Corp.",
                   "bdc_investment_identifier": "", "report_date": "2024-12-31",
                   "fair_value": 1.0, "row_id": "ROW-aaa"}]).to_parquet(holdings)
    _write_worklist(batch_dir, [
        {"cik": "0001743415", "fix_class": "subtotal_filter", "source_review_ids": "RVQ_BLK_s1"},
        {"cik": "0001743415", "fix_class": "dedup", "source_review_ids": "RVQ_BLK_s2"},
    ])
    pf.preflight_batch(batch, base_dir=d["base_dir"], verdicts_dir=d["verdicts_dir"],
                       bundles_dir=d["bundles_dir"], corrections_dir=d["corrections_dir"],
                       holdings_path=holdings)
    manifest = json.loads((batch_dir / "manifest.json").read_text())
    paths = {r["holdings_csv_path"] for r in manifest["rows"]}
    assert len(paths) == 1
    staged_files = list((batch_dir / "staging").glob("*.csv"))
    assert len(staged_files) == 1


def test_analyst_prompt_enables_shell_and_regrounding(tmp_path):
    # Analyst mode: the no-shell block is gone; the prompt carries the evidence-CLI
    # roam commands, requires citation resolution + filing-vs-extracted comparison,
    # and says plainly when the holdings CSV could not be staged.
    d = _dirs(tmp_path)
    batch = "B2AP"
    batch_dir = d["base_dir"] / "batch" / batch
    _seed(d, "RVQ_BLK_ap")
    _write_worklist(batch_dir, [{"cik": "0001743415", "fix_class": "subtotal_filter",
                                 "source_review_ids": "RVQ_BLK_ap"}])
    pf.preflight_batch(batch, base_dir=d["base_dir"], verdicts_dir=d["verdicts_dir"],
                       bundles_dir=d["bundles_dir"], corrections_dir=d["corrections_dir"],
                       fix_class="subtotal_filter", holdings_path=None)
    prompt = (batch_dir / "prompts" / "0001743415__subtotal_filter.md").read_text()
    assert "Do not call shell commands" not in prompt
    assert "do NOT use shell" not in prompt
    assert "Shell commands ARE allowed" in prompt
    assert "evidence_cli.py" in prompt
    assert "--bundle" in prompt
    assert "grid --table" in prompt
    assert "roam --query" in prompt
    assert "filing shows X, extracted shows Y" in prompt
    assert "FILE EDIT tool ONLY" in prompt      # BOM lesson: shell-written leaves fail intake
    assert "holdings CSV unavailable at preflight" in prompt
    # tmp bundles carry no accession and no filings index exists here
    assert "no cached filing resolved" in prompt


def test_prompt_embeds_promoted_example_leaf(tmp_path):
    # q4b2r4an trace lesson: workers spent 3-6 shell calls hunting the repo for a
    # worked leaf example despite the embedded contract. Embed one PROMOTED leaf of
    # the same fix_class (shape precedent, another CIK's values) in the prompt.
    d = _dirs(tmp_path)
    batch = "B2EX"
    batch_dir = d["base_dir"] / "batch" / batch
    _seed(d, "RVQ_BLK_ex")
    promoted = tmp_path / "promoted"
    (promoted / "0009990001").mkdir(parents=True)
    (promoted / "0009990001" / "subtotal_filter.json").write_text(json.dumps({
        "cik": "0009990001", "fix_class": "subtotal_filter",
        "template": {"patterns": ["total senior secured example"], "match_mode": "exact"},
        "confidence": 0.9, "rationale": "promoted example rationale"}), encoding="utf-8")
    _write_worklist(batch_dir, [{"cik": "0001743415", "fix_class": "subtotal_filter",
                                 "source_review_ids": "RVQ_BLK_ex"}])
    pf.preflight_batch(batch, base_dir=d["base_dir"], verdicts_dir=d["verdicts_dir"],
                       bundles_dir=d["bundles_dir"], corrections_dir=d["corrections_dir"],
                       fix_class="subtotal_filter", holdings_path=None,
                       promoted_dir=promoted)
    prompt = (batch_dir / "prompts" / "0001743415__subtotal_filter.md").read_text()
    assert "Worked example" in prompt
    assert "match its SHAPE, not its values" in prompt
    assert "total senior secured example" in prompt


def test_prompt_example_absent_notes_no_promoted_leaf(tmp_path):
    d = _dirs(tmp_path)
    batch = "B2EN"
    batch_dir = d["base_dir"] / "batch" / batch
    _seed(d, "RVQ_BLK_en")
    _write_worklist(batch_dir, [{"cik": "0001743415", "fix_class": "subtotal_filter",
                                 "source_review_ids": "RVQ_BLK_en"}])
    pf.preflight_batch(batch, base_dir=d["base_dir"], verdicts_dir=d["verdicts_dir"],
                       bundles_dir=d["bundles_dir"], corrections_dir=d["corrections_dir"],
                       fix_class="subtotal_filter", holdings_path=None,
                       promoted_dir=tmp_path / "no_such_promoted")
    prompt = (batch_dir / "prompts" / "0001743415__subtotal_filter.md").read_text()
    assert "no promoted leaf of this fix_class" in prompt


def test_release_manifest_accepts_wave_path(tmp_path, monkeypatch):
    d = _dirs(tmp_path)
    batch = "B2R"
    batch_dir = d["base_dir"] / "batch" / batch
    _seed(d, "RVQ_BLK_aaa")
    _write_worklist(batch_dir, [{"cik": "0001743415", "fix_class": "subtotal_filter",
                                 "source_review_ids": "RVQ_BLK_aaa"}])
    res = pf.preflight_batch(batch, base_dir=d["base_dir"], verdicts_dir=d["verdicts_dir"],
                             bundles_dir=d["bundles_dir"], corrections_dir=d["corrections_dir"])
    released = []
    monkeypatch.setattr(pf.review_lock, "release", lambda k: released.append(k))
    pf.release_manifest(res["manifest_path"])
    assert released == ["B2__0001743415__subtotal_filter"]


# --- escalation leaf (2026-08-21) -------------------------------------------------


def test_prompt_offers_escalation_path(tmp_path):
    # The forced-authoring rule is gone: a worker whose binding fix_class cannot
    # express the verified defect writes <fix_class>.escalation.json instead of a
    # plausible-looking no-op (the 0001838126 factor-1.0 lesson).
    d = _dirs(tmp_path)
    batch = "B2ESC"
    batch_dir = d["base_dir"] / "batch" / batch
    _seed(d, "RVQ_BLK_esc")
    _write_worklist(batch_dir, [{"cik": "0001743415", "fix_class": "subtotal_filter",
                                 "source_review_ids": "RVQ_BLK_esc"}])
    pf.preflight_batch(batch, base_dir=d["base_dir"], verdicts_dir=d["verdicts_dir"],
                       bundles_dir=d["bundles_dir"], corrections_dir=d["corrections_dir"],
                       fix_class="subtotal_filter", holdings_path=None)
    prompt = (batch_dir / "prompts" / "0001743415__subtotal_filter.md").read_text()
    assert "subtotal_filter.escalation.json" in prompt
    assert "never both" in prompt
    assert "write the narrowest valid correction" not in prompt


def test_preflight_skips_escalated_packets(tmp_path):
    d = _dirs(tmp_path)
    batch = "B2ES"
    batch_dir = d["base_dir"] / "batch" / batch
    _seed(d, "RVQ_BLK_e1")
    _seed(d, "RVQ_BLK_e2", cik="0001999988")
    _write_worklist(batch_dir, [
        {"cik": "0001743415", "fix_class": "subtotal_filter", "source_review_ids": "RVQ_BLK_e1"},
        {"cik": "0001999988", "fix_class": "subtotal_filter", "source_review_ids": "RVQ_BLK_e2"},
    ])
    esc_dir = d["corrections_dir"] / "0001999988"
    esc_dir.mkdir(parents=True)
    (esc_dir / "subtotal_filter.escalation.json").write_text("{}", encoding="utf-8")
    res = pf.preflight_batch(batch, base_dir=d["base_dir"], verdicts_dir=d["verdicts_dir"],
                             bundles_dir=d["bundles_dir"], corrections_dir=d["corrections_dir"],
                             fix_class="subtotal_filter")
    assert res["n_dispatch"] == 1
    assert res["n_skipped_escalated"] == 1
    manifest = json.loads((batch_dir / "manifest.json").read_text())
    assert manifest["skipped_escalated"][0]["cik"] == "0001999988"
    assert "template-authoring" in manifest["skipped_escalated"][0]["reason"]


def test_validator_cli_accepts_escalation_sibling(tmp_path, capsys):
    from scripts.agent_b2 import validate_corrections as vc
    d = tmp_path / "0001838126"
    d.mkdir()
    (d / "unit_rescale.escalation.json").write_text(json.dumps({
        "cik": "0001838126", "mechanism": "unit_scale", "fix_class": "unit_rescale",
        "diagnosis": "Filing NAV-per-share 25.22 vs extracted fund-financials 1000.0; "
                     "defect is outside the holdings template's reach.",
        "suggested_fix_class": "fund_financials_value_fix",
        "evidence_citations": [{"table_index": 54, "row_index": 6,
                                "quoted_text": "Net asset value per share"}],
        "confidence": 0.8}), encoding="utf-8")
    rc = vc.main(["--correction", str(d / "unit_rescale.json"),
                  "--expected-cik", "0001838126",
                  "--expected-fix-class", "unit_rescale"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "ESCALATED" in out
