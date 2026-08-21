"""Tests for the fleet-acceptance evaluator (tmp-confined I/O)."""

from __future__ import annotations

import json

from scripts import fleet_acceptance as fa


def _thresholds():
    return {
        "version": 1,
        "calibration": "provisional",
        "enforce": {"promote_requires_pass": False, "resume_requires_audit": False},
        "known_archive_reason_tokens": ["gate_fail", "schema_invalid", "magnitude_pull"],
        "checks": [
            {"id": "authoring_validity", "metric": "batch.authoring_validity_pct",
             "op": ">=", "value": 95.0},
            {"id": "selector_noop_refusals", "metric": "derived.selector_noop_refusals",
             "op": "==", "value": 0},
            {"id": "replay_offscope_failures", "metric": "derived.replay_offscope_failures",
             "op": "==", "value": 0},
            {"id": "post_promotion_discoveries", "metric": "derived.post_promotion_pull_dirs",
             "op": "==", "value": 0},
            {"id": "post_promotion_audit", "metric": "derived.post_promotion_audit_present",
             "op": "==", "value": 1},
            {"id": "new_failure_classes", "metric": "derived.unknown_archive_dirs",
             "op": "==", "value": 0},
            {"id": "defect_signature_rate", "metric": "derived.defect_signature_refusal_pct",
             "op": "<=", "value": 10.0},
        ],
    }


def _seed_batch(tmp_path, batch_id, *, gate_entries, n_validate_ok=19, n_validate_bad=1):
    batch_dir = tmp_path / "batch" / batch_id
    logs = batch_dir / "logs"
    logs.mkdir(parents=True)
    for i in range(n_validate_ok):
        (logs / f"p{i}.validate.txt").write_text("OK valid correction", encoding="utf-8")
    for i in range(n_validate_bad):
        (logs / f"bad{i}.validate.txt").write_text("INVALID: bad fields", encoding="utf-8")
    gate = "\n".join(json.dumps(e) for e in gate_entries)
    (batch_dir / "apply_gate_v3_log.jsonl").write_text(gate, encoding="utf-8")
    return batch_dir


def _entry(verdict="PASS", checks=None, reasons=None):
    return {"cik": "1", "verdict": verdict,
            "checks": checks or {"replay_ok": True, "replay_equivalence": True,
                                 "off_scope_invariance": True, "magnitude_plausible": True},
            "reasons": reasons or []}


def test_pass_artifact_with_all_checks(tmp_path):
    batch = "bfleet"
    _seed_batch(tmp_path, batch, gate_entries=[_entry() for _ in range(10)])
    (tmp_path / "archive" / f"{batch}_gate_fail").mkdir(parents=True)
    audit_dir = tmp_path / "audit"
    audit_dir.mkdir()
    (audit_dir / f"replay_live_stats_{batch}.json").write_text("[]", encoding="utf-8")

    metrics = fa.build_metrics(batch, batch_root=tmp_path / "batch",
                               archive_root=tmp_path / "archive", audit_dir=audit_dir,
                               known_tokens=_thresholds()["known_archive_reason_tokens"])
    result = fa.evaluate(batch, metrics, _thresholds())
    assert result["verdict"] == "PASS"
    assert len(result["checks"]) == 7
    assert all(c["pass"] for c in result["checks"])
    out = fa.write_acceptance(result, tmp_path / f"fleet_acceptance_{batch}.json")
    assert json.loads(out.read_text(encoding="utf-8"))["batch_id"] == batch


def test_fail_lists_failing_ids(tmp_path):
    batch = "bfail"
    entries = [_entry() for _ in range(8)]
    entries.append(_entry("FAIL", reasons=["applier no-op on trial base rows"]))
    entries.append(_entry("FAIL", checks={"replay_equivalence": False},
                          reasons=["trial != composed replay"]))
    _seed_batch(tmp_path, batch, gate_entries=entries, n_validate_ok=10, n_validate_bad=10)
    metrics = fa.build_metrics(batch, batch_root=tmp_path / "batch",
                               archive_root=tmp_path / "archive",
                               audit_dir=tmp_path / "audit", known_tokens=[])
    result = fa.evaluate(batch, metrics, _thresholds())
    assert result["verdict"] == "FAIL"
    failing = {c["id"] for c in result["checks"] if not c["pass"]}
    assert "authoring_validity" in failing          # 50% validity
    assert "selector_noop_refusals" in failing      # the no-op stale refusal
    assert "replay_offscope_failures" in failing    # the equivalence check fail
    assert "post_promotion_audit" in failing        # artifact absent


def test_not_assessable_when_nothing_gated(tmp_path):
    batch = "bempty"
    (tmp_path / "batch" / batch).mkdir(parents=True)
    metrics = fa.build_metrics(batch, batch_root=tmp_path / "batch",
                               archive_root=tmp_path / "archive",
                               audit_dir=tmp_path / "audit", known_tokens=[])
    result = fa.evaluate(batch, metrics, _thresholds())
    assert result["verdict"] == "NOT_ASSESSABLE"


def test_unknown_archive_dir_flags_new_failure_class(tmp_path):
    batch = "bnovel"
    _seed_batch(tmp_path, batch, gate_entries=[_entry()])
    (tmp_path / "archive" / f"{batch}_gate_fail").mkdir(parents=True)
    (tmp_path / "archive" / f"{batch}_novel_weirdness").mkdir()
    metrics = fa.build_metrics(batch, batch_root=tmp_path / "batch",
                               archive_root=tmp_path / "archive",
                               audit_dir=tmp_path / "audit",
                               known_tokens=_thresholds()["known_archive_reason_tokens"])
    assert metrics["derived"]["unknown_archive_dirs"] == 1
    assert "novel_weirdness" in metrics["derived"]["unknown_archive_dir_names"]
    # pull/revert dirs count as post-promotion discoveries
    (tmp_path / "archive" / f"{batch}_magnitude_pull").mkdir()
    metrics2 = fa.build_metrics(batch, batch_root=tmp_path / "batch",
                                archive_root=tmp_path / "archive",
                                audit_dir=tmp_path / "audit",
                                known_tokens=_thresholds()["known_archive_reason_tokens"])
    assert metrics2["derived"]["post_promotion_pull_dirs"] == 1


def test_defect_signature_pct_math(tmp_path):
    batch = "bpct"
    entries = [_entry() for _ in range(8)]
    entries += [_entry("FAIL", checks={"magnitude_plausible": False},
                       reasons=["rate signature already plausible"]) for _ in range(2)]
    _seed_batch(tmp_path, batch, gate_entries=entries, n_validate_ok=10, n_validate_bad=0)
    metrics = fa.build_metrics(batch, batch_root=tmp_path / "batch",
                               archive_root=tmp_path / "archive",
                               audit_dir=tmp_path / "audit", known_tokens=[])
    assert metrics["derived"]["gated_entries"] == 10
    assert metrics["derived"]["defect_signature_refusal_pct"] == 20.0
    result = fa.evaluate(batch, metrics, _thresholds())
    assert not [c for c in result["checks"]
                if c["id"] == "defect_signature_rate"][0]["pass"]
