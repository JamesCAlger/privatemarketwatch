"""Candidate gate inputs reuse live rules without fabricating approval evidence."""
import csv
from pathlib import Path

import pytest

from pipeline import legacy_acceptance_inputs as inputs
from pipeline.investigation_state import rules_fingerprint, stale_investigations
from pipeline.programme.core import ContractError, atomic_json, read_json, sha

Q = "2026-03-31"
CIK = "0000000123"
RESIDUAL = "diagnostics/source_reconciliation_residual_classification.csv"
SOURCE_ONLY = "diagnostics/source_reconciliation_source_only_detail.csv"


def write_csv(path, columns, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


@pytest.fixture
def holdings(tmp_path):
    path = tmp_path / "holdings.csv"
    write_csv(path, ["cik", "report_date", "fair_value"],
              [dict(cik=CIK, report_date=Q, fair_value=100_000_000)])
    return path


def source_result(tmp_path, holdings, *, blocking=True):
    directory = tmp_path / "source"
    common = dict(cik=CIK, report_date=Q, mechanism="missing_position", confidence="high")
    write_csv(directory / RESIDUAL,
        [*common, "blocking_issue", "affected_source_fair_value", "affected_output_fair_value"],
        [dict(common, blocking_issue=blocking,
              affected_source_fair_value=1_000_000, affected_output_fair_value=2_000_000)])
    write_csv(directory / SOURCE_ONLY, [*common, "is_blocking", "source_fair_value"],
        [dict(common, is_blocking=blocking, source_fair_value=1_500_000)])
    atomic_json(directory / "summary.json", dict(holdings_sha256=sha(holdings)))
    atomic_json(directory / "complete.json", {
        name: sha(directory / name) for name in ("summary.json", RESIDUAL, SOURCE_ONLY)})
    return directory


def staged_rule(source, cik="123", quarter=Q):
    path = source / cik / "rules" / "rule.json"
    atomic_json(path, dict(scope=dict(quarters=[quarter]), mechanism="test fixture"))
    return path


def test_source_queue_preserves_existing_max_of_two_views(tmp_path, holdings):
    source = source_result(tmp_path, holdings)
    hashes = {str(p): sha(p) for p in source.rglob("*") if p.is_file()}
    result = inputs.collect_source_queue(holdings, source, tmp_path / "queue")
    with Path(result["queue_path"]).open(newline="", encoding="utf-8-sig") as stream:
        rows = list(csv.DictReader(stream))
    assert result["blocker"] == 1
    assert rows[0]["cik"] == CIK
    assert rows[0]["fv_at_risk_m"] == "2.000000"  # max(2m, 1.5m), not 3.5m
    assert rows[0]["fund_quarter_fv_m"] == "100.000000"
    assert rows[0]["confidence"] == "source_blocking_high"
    assert result["holdings_sha256"] == sha(holdings)
    assert all(sha(Path(path)) == value for path, value in hashes.items())
    seal = read_json(tmp_path / "queue/complete.json")
    assert all(sha(tmp_path / "queue" / name) == value for name, value in seal.items())


def test_documented_nonblockers_produce_measured_empty_queue(tmp_path, holdings):
    source = source_result(tmp_path, holdings, blocking=False)
    result = inputs.collect_source_queue(holdings, source, tmp_path / "queue")
    assert result["items"] == result["blocker"] == 0
    assert Path(result["queue_path"]).is_file()


@pytest.mark.parametrize("changed", ["holdings", RESIDUAL, SOURCE_ONLY, "summary.json"])
def test_queue_rejects_changed_candidate_or_source(tmp_path, holdings, changed):
    source = source_result(tmp_path, holdings)
    path = holdings if changed == "holdings" else source / changed
    with path.open("a", encoding="utf-8") as stream:
        stream.write("\n")
    with pytest.raises(ContractError, match="different holdings|absent or changed"):
        inputs.collect_source_queue(holdings, source, tmp_path / "queue")
    assert not (tmp_path / "queue").exists()


def test_queue_does_not_seal_when_source_changes_during_collection(tmp_path, holdings, monkeypatch):
    from pipeline import review_queue
    source = source_result(tmp_path, holdings)
    original = review_queue.build_review_queue
    def change_source(**kwargs):
        result = original(**kwargs)
        with (source / RESIDUAL).open("a", encoding="utf-8") as stream:
            stream.write("\n")
        return result
    monkeypatch.setattr(review_queue, "build_review_queue", change_source)
    with pytest.raises(ContractError, match="absent or changed"):
        inputs.collect_source_queue(holdings, source, tmp_path / "queue")
    assert not (tmp_path / "queue/complete.json").exists()


def test_snapshot_preserves_stale_rules_and_scopes(tmp_path, holdings):
    source = tmp_path / "investigations"
    rule = staged_rule(source)
    staged_rule(source, "456")  # Outside candidate cohort.
    before = sha(rule)
    result = inputs.snapshot_investigations(source, tmp_path / "capture", holdings, {CIK})
    manifest = tmp_path / "capture/investigation_inputs.json"
    store = inputs.verify_investigations(manifest, holdings, {CIK})
    assert store is not None
    stale = stale_investigations(store, Q, ciks={CIK})
    assert len(stale) == 1
    assert stale[0]["reason"] == "never applied; never gated for quarter"
    assert stale_investigations(store, "2025-12-31", ciks={CIK}) == []
    assert result["inventory"]["cik_directories"] == ["123"]
    assert not (store / "456").exists()
    assert not (store / "123/apply_audit.json").exists()
    assert sha(rule) == before


def test_snapshot_preserves_matching_apply_and_gate_fingerprints(tmp_path, holdings):
    source = tmp_path / "investigations"
    rule = staged_rule(source)
    fp = rules_fingerprint(rule.parent)
    atomic_json(source / "123/apply_audit.json", dict(rules_fingerprint=fp))
    atomic_json(source / f"123/gate.{Q}.json", dict(rules_fingerprint=fp, verdict="FAIL"))
    inputs.snapshot_investigations(source, tmp_path / "capture", holdings, {CIK})
    store = inputs.verify_investigations(tmp_path / "capture/investigation_inputs.json", holdings, {CIK})
    assert stale_investigations(store, Q, ciks={CIK}) == []
    assert read_json(store / f"123/gate.{Q}.json")["verdict"] == "FAIL"


@pytest.mark.parametrize("present", [False, True])
def test_missing_store_is_distinct_from_present_empty_store(tmp_path, holdings, present):
    source = tmp_path / "investigations"
    if present:
        source.mkdir()
    result = inputs.snapshot_investigations(source, tmp_path / "capture", holdings, {CIK})
    store = inputs.verify_investigations(tmp_path / "capture/investigation_inputs.json", holdings, {CIK})
    assert result["inventory"]["present"] is present
    assert (store is not None) is present


@pytest.mark.parametrize("changed", ["rule", "added_gate", "removed_cik", "holdings", "cohort", "directory"])
def test_snapshot_rejects_changed_inputs(tmp_path, holdings, changed):
    source = tmp_path / "investigations"
    staged_rule(source)
    inputs.snapshot_investigations(source, tmp_path / "capture", holdings, {CIK})
    manifest = tmp_path / "capture/investigation_inputs.json"
    store = tmp_path / "capture/store"
    if changed == "rule":
        (store / "123/rules/rule.json").write_text("{}", encoding="utf-8")
    elif changed == "added_gate":
        atomic_json(store / f"123/gate.{Q}.json", dict(rules_fingerprint="invented"))
    elif changed == "removed_cik":
        (store / "123").rename(store / "124")
    elif changed == "holdings":
        with holdings.open("a", encoding="utf-8") as stream:
            stream.write("\n")
    else:
        result = read_json(manifest)
        result[changed] = [] if changed == "cohort" else str(source.resolve())
        atomic_json(manifest, result)
    with pytest.raises(ContractError):
        inputs.verify_investigations(manifest, holdings, {CIK})


def test_duplicate_normalized_cik_is_rejected(tmp_path, holdings):
    source = tmp_path / "investigations"
    staged_rule(source, "123")
    staged_rule(source, CIK)
    with pytest.raises(ContractError, match="repeats a normalized CIK"):
        inputs.snapshot_investigations(source, tmp_path / "capture", holdings, {CIK})


def gate_evidence(tmp_path, holdings, paths):
    from pipeline.quarter_evidence import Evidence
    manifest = tmp_path / "evidence.json"
    atomic_json(manifest, dict(holdings_sha256=sha(holdings), files={
        "legacy_" + name: dict(path=str(path.resolve()), sha256=sha(path), holdings_sha256=sha(holdings))
        for name, path in paths.items()}))
    return Evidence(manifest, holdings)


@pytest.mark.parametrize("name", ["ledger", "queue", "audit"])
def test_bound_evidence_must_be_the_file_actually_measured(tmp_path, holdings, name):
    path = tmp_path / "recorded.csv"
    path.write_text("test fixture\n", encoding="utf-8")
    evidence = gate_evidence(tmp_path, holdings, {name: path})
    assert inputs.bound_legacy_inputs(evidence, holdings, {CIK}, {name: path}) == {name}
    with pytest.raises(ContractError, match="differs from its evidence record"):
        inputs.bound_legacy_inputs(evidence, holdings, {CIK}, {name: tmp_path / "uncollected.csv"})


@pytest.mark.parametrize("present", [True, False])
def test_investigation_receipt_binds_only_the_verified_store(tmp_path, holdings, present):
    source = tmp_path / "investigations"
    if present:
        staged_rule(source)
    inputs.snapshot_investigations(source, tmp_path / "capture", holdings, {CIK})
    evidence = gate_evidence(tmp_path, holdings,
        {"investigate": tmp_path / "capture/investigation_inputs.json"})
    actual = {"investigate": tmp_path / "capture/store"}
    expected = {"investigate"} if present else set()
    assert inputs.bound_legacy_inputs(evidence, holdings, {CIK}, actual) == expected
    with pytest.raises(ContractError, match="differs from its evidence snapshot"):
        inputs.bound_legacy_inputs(evidence, holdings, {CIK}, {"investigate": source})


def test_no_binding_is_not_claimed_as_measured(tmp_path, holdings):
    evidence = gate_evidence(tmp_path, holdings, {})
    assert inputs.bound_legacy_inputs(evidence, holdings, {CIK}, {}) == set()
