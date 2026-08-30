"""Tests for the quarter re-attestation check (freeze the attestation, not the code).

A signed-off quarter's acceptance verdict is an artifact of (code, data) at
sign-off. Semantics changes may retroactively flip it (2026-08-30 example: the
retain-and-flag conservation change regressed 1633336's signed Q4-2025 quarter
until the is_subsidiary false-positive fix restored it). compare_attestation
diffs a stored attestation against a current re-run so such regressions are
DETECTED and ledgered, not discovered by accident.
"""

from __future__ import annotations

import json

from scripts.reattest_quarters import compare_attestation, ledger_row


def _acc(verdict="PASS", checks=None):
    return {
        "target_quarter": "2025-12-31",
        "thresholds_version": 2,
        "verdict": verdict,
        "checks": checks if checks is not None else [
            {"id": "reconcile_rate", "actual": 92.0, "pass": True},
            {"id": "flagged_fv_share", "actual": 8.0, "pass": True},
        ],
    }


def test_identical_attestations_produce_no_flips():
    d = compare_attestation(_acc(), _acc())
    assert d["verdict_flip"] is None
    assert d["check_flips"] == []
    assert d["regressed"] is False


def test_verdict_regression_detected_with_check_attribution():
    cur = _acc(verdict="FAIL", checks=[
        {"id": "reconcile_rate", "actual": 88.0, "pass": False},
        {"id": "flagged_fv_share", "actual": 8.0, "pass": True},
    ])
    d = compare_attestation(_acc(), cur)
    assert d["verdict_flip"] == ("PASS", "FAIL")
    assert d["regressed"] is True
    assert d["check_flips"] == [
        {"id": "reconcile_rate", "stored": (92.0, True), "current": (88.0, False)}]


def test_improvement_is_a_flip_but_not_a_regression():
    stored = _acc(verdict="FAIL", checks=[
        {"id": "reconcile_rate", "actual": 88.0, "pass": False}])
    cur = _acc(verdict="PASS", checks=[
        {"id": "reconcile_rate", "actual": 92.0, "pass": True}])
    d = compare_attestation(stored, cur)
    assert d["verdict_flip"] == ("FAIL", "PASS")
    assert d["regressed"] is False


def test_ledger_row_shape():
    d = compare_attestation(_acc(), _acc(verdict="FAIL", checks=[
        {"id": "reconcile_rate", "actual": 88.0, "pass": False}]))
    row = ledger_row("2025-12-31", d, note="unit test")
    assert row["quarter"] == "2025-12-31"
    assert row["stored_verdict"] == "PASS" and row["current_verdict"] == "FAIL"
    assert row["regressed"] == 1
    assert "reconcile_rate" in row["check_flips"]
    assert row["note"] == "unit test"
    json.dumps(row)  # must be serializable
