"""Filer-profile pilot: frozen inputs, inventories, cache identity and verified-era evidence."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.profile_pilot import cohort, manifest
from scripts.profile_pilot.manifest import StageInvalidated
from scripts.profile_pilot.paths import PathError
from tests.test_profile_pilot_paths import CODE_ROOT, fake_paths, index_row, put_instance

LEDGER_HEADER = ("review_id,state,in_queue,population_origin,verdict_status,verdict_detail,"
                 "has_fix_route,cik,rule_name,report_date,lane,engine,fv_at_risk_m,"
                 "fund_quarter_fv_m\n")


# ---------------------------------------------------------------- inventories

def test_freeze_inventory_is_write_once_and_hash_checked(tmp_path):
    paths = fake_paths(tmp_path)
    record = manifest.freeze_inventory(paths, "correction_inventory", {"items": [1, 2]})
    assert record["state"] == "frozen" and len(record["sha256"]) == 64
    assert manifest.load_inventory(paths, "correction_inventory") == {"items": [1, 2]}
    with pytest.raises(PathError, match="overwrite"):
        manifest.freeze_inventory(paths, "correction_inventory", {"items": []})
    target = paths.run_root / "inventories" / "correction_inventory.json"
    body = json.loads(target.read_text())
    body["content"]["items"].append(3)
    target.write_text(json.dumps(body))
    with pytest.raises(StageInvalidated):
        manifest.load_inventory(paths, "correction_inventory")


def test_unknown_inventory_names_are_rejected(tmp_path):
    paths = fake_paths(tmp_path)
    with pytest.raises(ValueError):
        manifest.freeze_inventory(paths, "anything_else", {})


def test_inventory_states_mark_unfrozen_inventories_explicitly(tmp_path):
    paths = fake_paths(tmp_path)
    manifest.freeze_inventory(paths, "wrapper_key_inventory", {"ciks": {}})
    states = manifest.inventory_states(paths)
    assert states["wrapper_key_inventory"]["state"] == "frozen"
    assert states["correction_inventory"] == {"state": "not_yet_frozen"}
    assert states["contract_inventory"] == {"state": "not_yet_frozen"}
    assert states["primary_quarter_inventory"] == {"state": "not_yet_frozen"}


def test_wrapper_key_inventory_lists_nested_keys_once(tmp_path):
    wrappers = tmp_path / "wrappers"
    wrappers.mkdir()
    (wrappers / "0001901037.json").write_text(json.dumps({
        "schema_version": 3, "dispatch": {"rule_prefix": "X", "prefix_rules": [{"a": 1}, {"a": 2, "b": 3}]},
        "known_edge_cases": [{"id": "e1"}]}))
    content = manifest.wrapper_key_inventory(CODE_ROOT, wrapper_dir=wrappers,
                                             ciks=["0001901037", "0000000009"])
    stellus = content["ciks"]["0001901037"]
    assert stellus["status"] == "present"
    assert stellus["keys"] == ["dispatch", "dispatch.prefix_rules", "dispatch.prefix_rules[].a",
                               "dispatch.prefix_rules[].b", "dispatch.rule_prefix",
                               "known_edge_cases", "known_edge_cases[].id", "schema_version"]
    assert len(stellus["sha256"]) == 64
    assert content["ciks"]["0000000009"] == {"status": "missing", "path": str(
        wrappers / "0000000009.json")}


def test_wrapper_key_inventory_reads_the_real_pilot_wrappers():
    content = manifest.wrapper_key_inventory(CODE_ROOT)
    assert set(content["ciks"]) == {m.cik for m in cohort.PILOT_COHORT}
    for entry in content["ciks"].values():
        assert entry["status"] == "present"
        assert "dispatch.rule_prefix" in entry["keys"]
        assert len(entry["git_blob"]) == 40


# ---------------------------------------------------------------- input freezing

def test_verify_inputs_reports_changed_and_missing_paths(tmp_path):
    paths = fake_paths(tmp_path)
    a = paths.main_repo_root / "data" / "output" / "existing.csv"
    b = paths.main_repo_root / "data" / "output" / "other.csv"
    b.write_text("x", encoding="utf-8")
    records = [manifest.file_record(a, "a"), manifest.file_record(b, "b"),
               manifest.file_record(tmp_path / "absent.csv", "absent")]
    assert records[2]["status"] == "missing"
    assert manifest.verify_inputs({"inputs": records})["ok"] is True
    a.write_text("changed", encoding="utf-8")
    b.unlink()
    report = manifest.verify_inputs({"inputs": records})
    assert report["ok"] is False
    assert report["changed"] == [str(a)]
    assert report["missing"] == [str(b)]
    (tmp_path / "absent.csv").write_text("appeared")
    assert str(tmp_path / "absent.csv") in manifest.verify_inputs({"inputs": records})["appeared"]


def test_input_change_during_a_stage_invalidates_it(tmp_path):
    paths = fake_paths(tmp_path)
    source = paths.main_repo_root / "data" / "output" / "existing.csv"
    identity = manifest.cache_identity("census", {"xml": [manifest.file_record(source, "xml")]},
                                       collector_version="c1")

    def compute():
        source.write_text("mutated mid-stage", encoding="utf-8")
        return {"rows": 1}

    with pytest.raises(StageInvalidated, match="existing.csv"):
        manifest.run_cached_stage(paths, "census/x.json", identity, compute, heavy=False)
    assert not (paths.run_root / "census" / "x.json").exists()


def test_changed_input_before_a_stage_invalidates_the_cached_result(tmp_path):
    paths = fake_paths(tmp_path)
    source = paths.main_repo_root / "data" / "output" / "existing.csv"
    identity = manifest.cache_identity("census", {"xml": [manifest.file_record(source, "xml")]},
                                       collector_version="c1")
    manifest.run_cached_stage(paths, "census/y.json", identity, lambda: {"n": 1}, heavy=False)
    source.write_text("new bytes", encoding="utf-8")
    with pytest.raises(StageInvalidated):
        manifest.run_cached_stage(paths, "census/y.json", identity, lambda: {"n": 2}, heavy=False)


def test_collector_version_change_invalidates_the_cache(tmp_path):
    paths = fake_paths(tmp_path)
    calls = []

    def compute():
        calls.append(1)
        return {"n": len(calls)}

    v1 = manifest.cache_identity("census", {}, collector_version="c1")
    v2 = manifest.cache_identity("census", {}, collector_version="c2")
    assert v1["fingerprint"] != v2["fingerprint"]
    assert manifest.run_cached_stage(paths, "census/v1.json", v1, compute, heavy=False)["cache"] == "miss"
    assert manifest.run_cached_stage(paths, "census/v1.json", v1, compute, heavy=False)["cache"] == "hit"
    again = manifest.run_cached_stage(paths, "census/v2.json", v2, compute, heavy=False)
    assert again["cache"] == "miss" and len(calls) == 2
    # Reusing a path with a different identity is not a hit either; it is refused.
    with pytest.raises(StageInvalidated, match="identity"):
        manifest.run_cached_stage(paths, "census/v1.json", v2, compute, heavy=False)


def test_incomplete_prior_result_is_not_reused(tmp_path):
    paths = fake_paths(tmp_path)
    identity = manifest.cache_identity("census", {}, collector_version="c1")
    target = paths.run_root / "census" / "z.json"
    target.parent.mkdir(parents=True)
    target.write_text(json.dumps({"identity": identity, "complete": False, "result": {}}))
    with pytest.raises(StageInvalidated, match="incomplete"):
        manifest.run_cached_stage(paths, "census/z.json", identity, lambda: {"n": 1}, heavy=False)


def test_heavy_classified_stage_without_a_lease_is_refused_not_run(tmp_path):
    from contextlib import contextmanager
    from scripts.profile_pilot import protection
    paths = fake_paths(tmp_path)
    identity = manifest.cache_identity("census", {}, collector_version="c1")
    heavy = protection.requires_lease(ciks=["0001287750"], instance_count=1)  # Ares parse, R3
    assert heavy is True
    ran = []
    with pytest.raises(protection.LeaseRefused):
        manifest.run_cached_stage(paths, "census/h.json", identity, lambda: ran.append(1) or {},
                                  heavy=heavy)

    @contextmanager
    def pretend_lease():  # yields a handle whose lock is not actually held
        yield protection.LeaseInfo(candidate=tmp_path / "c", lock_path=tmp_path / "heavy.lock",
                                   acquired_utc="x")

    with pytest.raises(protection.LeaseRefused):
        manifest.run_cached_stage(paths, "census/h.json", identity, lambda: ran.append(1) or {},
                                  heavy=heavy, lease=pretend_lease)
    assert ran == []
    assert not (paths.run_root / "census" / "h.json").exists()


# ---------------------------------------------------------------- verified-era evidence

def test_missing_historical_wrapper_is_explicit_missing_evidence():
    entry = manifest.historical_wrapper(CODE_ROOT, "0000000009", "eed082b")
    assert entry["status"] == "missing"
    assert entry["commit"] == "eed082b"


def test_verified_era_wrappers_pin_both_versions_where_they_differ():
    bcred = manifest.historical_wrapper(CODE_ROOT, "0001803498", "eed082b")
    head = manifest.historical_wrapper(CODE_ROOT, "0001803498", "HEAD")
    assert bcred["status"] == head["status"] == "present"
    assert bcred["git_blob"] != head["git_blob"]
    stellus_then = manifest.historical_wrapper(CODE_ROOT, "0001901037", "eed082b")
    stellus_now = manifest.historical_wrapper(CODE_ROOT, "0001901037", "HEAD")
    assert stellus_then["git_blob"] == stellus_now["git_blob"]


def test_verified_era_ledger_labels_blocking_ciks(tmp_path):
    ledger = tmp_path / "findings_ledger_post.csv"
    ledger.write_text(LEDGER_HEADER +
                      "r1,open,True,live,MISSING,,False,0001287750,SRC_BDC01,2026-03-31,blocker,row_validation,1.0,\n"
                      "r2,adjudicated_false_alarm,True,live,x,,False,0001901037,X,2026-03-31,blocker,oracle,1.0,\n"
                      "r3,open,True,live,x,,False,0001901037,Y,2026-03-31,review,weak,1.0,\n"
                      "r4,open,True,live,x,,False,0001901037,Z,2025-12-31,blocker,oracle,1.0,\n",
                      encoding="utf-8")
    rows = manifest.verified_era_ledger(ledger, ["0001287750", "0001901037", "0001588272"])
    assert rows["status"] == "present" and len(rows["sha256"]) == 64
    assert rows["ciks"]["0001287750"]["label"] == "verified_era_unreconciled"
    assert rows["ciks"]["0001287750"]["blocking_rows"] == 1
    assert rows["ciks"]["0001901037"]["label"] == "verified_era_reconciled"
    assert rows["ciks"]["0001588272"]["label"] == "verified_era_reconciled"
    assert rows["ciks"]["0001588272"]["rows"] == 0


def test_missing_verified_era_ledger_is_recorded_not_fatal(tmp_path):
    rows = manifest.verified_era_ledger(tmp_path / "absent.csv", ["0001287750"])
    assert rows["status"] == "missing"
    assert rows["ciks"]["0001287750"]["label"] == "verified_era_evidence_missing"


# ---------------------------------------------------------------- the manifest itself

def test_build_manifest_records_head_dirty_digest_and_input_hashes(tmp_path):
    rows = [index_row("1901037", "0001558370-22-016375", "10-Q", "2022-11-04", "2022-09-30")]
    paths = fake_paths(tmp_path, index_rows=rows)
    xml = put_instance(paths.main_repo_root, "1901037", "0001558370-22-016375")
    primary = cohort.primary_quarter_inventory(paths)
    built = manifest.build_manifest(paths, primary_inventory=primary)
    assert len(built["git"]["head"]) == 40
    assert len(built["git"]["dirty_source_digest"]) == 64
    assert built["run_id"] == "stagea-test"
    labels = {r["label"]: r for r in built["inputs"]}
    assert labels["output/bdc_filings_index.csv"]["status"] == "present"
    assert labels["output/bdc_holdings.csv"]["status"] == "missing"
    assert any(r["path"] == str(xml) and r["status"] == "present" for r in built["inputs"])
    assert labels["code/scripts/run_context_census.py"]["git_blob"]
    assert built["inventories"]["contract_inventory"] == {"state": "not_yet_frozen"}
    assert built["verified_era"]["quarter"] == "2026-03-31"
    assert built["verified_era"]["signoff_commit"] == "eed082b"
    assert manifest.verify_inputs(built)["ok"] is True
    json.dumps(built).encode("ascii")


def test_manifest_freezes_source_mappings_and_anchor_basis(tmp_path):
    paths = fake_paths(tmp_path)
    primary = dict(fund_quarters=[])
    built = manifest.build_manifest(paths, primary_inventory=primary)
    mapped = {r["label"]: r for r in built["source_mappings"]}
    assert set(mapped) == {"source_mappings/" + p for p in manifest.SOURCE_MAPPING_FILES}
    assert all(r["status"] == "present" and len(r["git_blob"]) == 40 for r in mapped.values())
    assert set(built["anchor_basis"]) == set(cohort.PILOT_CIKS)
    tcw = {r["label"] for r in built["anchor_basis"]["0001715933"]}
    assert tcw == {"anchor_basis/0001715933/2025-06-30.json", "anchor_basis/0001715933/2026-03-31.json"}
    for records in built["anchor_basis"].values():
        assert records and all(r["status"] in ("present", "missing", "empty") for r in records)


def test_absent_anchor_directory_is_explicit(tmp_path):
    records = manifest._directory_records(tmp_path / "absent", "anchor_basis/0000000009")
    assert records == [dict(label="anchor_basis/0000000009", path=str(tmp_path / "absent"),
                            status="missing")]
