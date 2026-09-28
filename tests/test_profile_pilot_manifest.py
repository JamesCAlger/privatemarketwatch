"""Filer-profile pilot: frozen inputs, inventories, cache identity and verified-era evidence."""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from scripts.profile_pilot import cohort, manifest
from scripts.profile_pilot.manifest import StageInvalidated
from scripts.profile_pilot.paths import PathError
from tests.test_profile_pilot_paths import CODE_ROOT, fake_paths, index_row, put_instance

LEDGER_HEADER = ("review_id,state,in_queue,population_origin,verdict_status,verdict_detail,"
                 "has_fix_route,cik,rule_name,report_date,lane,engine,fv_at_risk_m,"
                 "fund_quarter_fv_m\n")
LIGHT = dict(ciks=["0001901037"], instance_count=0, full_cache_scan=False, pipeline_cik_count=0,
             est_seconds=1, est_bytes=0)
ARES_PARSE = dict(LIGHT, ciks=["0001287750"], instance_count=1)


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
        manifest.run_cached_stage(paths, "census/x.json", identity, compute, workload=LIGHT)
    assert not (paths.run_root / "census" / "x.json").exists()


def test_changed_input_before_a_stage_invalidates_the_cached_result(tmp_path):
    paths = fake_paths(tmp_path)
    source = paths.main_repo_root / "data" / "output" / "existing.csv"
    identity = manifest.cache_identity("census", {"xml": [manifest.file_record(source, "xml")]},
                                       collector_version="c1")
    manifest.run_cached_stage(paths, "census/y.json", identity, lambda: {"n": 1}, workload=LIGHT)
    source.write_text("new bytes", encoding="utf-8")
    with pytest.raises(StageInvalidated):
        manifest.run_cached_stage(paths, "census/y.json", identity, lambda: {"n": 2}, workload=LIGHT)


def test_collector_version_change_invalidates_the_cache(tmp_path):
    paths = fake_paths(tmp_path)
    calls = []

    def compute():
        calls.append(1)
        return {"n": len(calls)}

    v1 = manifest.cache_identity("census", {}, collector_version="c1")
    v2 = manifest.cache_identity("census", {}, collector_version="c2")
    assert v1["fingerprint"] != v2["fingerprint"]
    assert manifest.run_cached_stage(paths, "census/v1.json", v1, compute, workload=LIGHT)["cache"] == "miss"
    assert manifest.run_cached_stage(paths, "census/v1.json", v1, compute, workload=LIGHT)["cache"] == "hit"
    again = manifest.run_cached_stage(paths, "census/v2.json", v2, compute, workload=LIGHT)
    assert again["cache"] == "miss" and len(calls) == 2
    # Reusing a path with a different identity is not a hit either; it is refused.
    with pytest.raises(StageInvalidated, match="identity"):
        manifest.run_cached_stage(paths, "census/v1.json", v2, compute, workload=LIGHT)


def test_incomplete_prior_result_is_not_reused(tmp_path):
    paths = fake_paths(tmp_path)
    identity = manifest.cache_identity("census", {}, collector_version="c1")
    target = paths.run_root / "census" / "z.json"
    target.parent.mkdir(parents=True)
    target.write_text(json.dumps({"identity": identity, "complete": False, "result": {}}))
    with pytest.raises(StageInvalidated, match="incomplete"):
        manifest.run_cached_stage(paths, "census/z.json", identity, lambda: {"n": 1}, workload=LIGHT)


def test_heavy_classified_stage_without_a_lease_is_refused_not_run(tmp_path):
    from contextlib import contextmanager
    from scripts.profile_pilot import protection
    paths = fake_paths(tmp_path)
    identity = manifest.cache_identity("census", {}, collector_version="c1")
    assert manifest.classify_workload(ARES_PARSE) is True  # Ares parse, R3
    ran = []
    with pytest.raises(protection.LeaseRefused):
        manifest.run_cached_stage(paths, "census/h.json", identity, lambda: ran.append(1) or {},
                                  workload=ARES_PARSE)

    @contextmanager
    def pretend_lease():  # yields a handle whose lock is not actually held
        yield protection.LeaseInfo(candidate=tmp_path / "c", lock_path=tmp_path / "heavy.lock",
                                   acquired_utc="x")

    with pytest.raises(protection.LeaseRefused):
        manifest.run_cached_stage(paths, "census/h.json", identity, lambda: ran.append(1) or {},
                                  workload=ARES_PARSE, lease=pretend_lease)
    assert ran == []
    assert not (paths.run_root / "census" / "h.json").exists()


@pytest.mark.parametrize("workload", [
    False,  # a bare literal can no longer stand in for the classification
    {},
    {k: v for k, v in LIGHT.items() if k != "instance_count"},  # omitted field would default light
    dict(LIGHT, heavy=False),  # unknown keys are not a classification either
])
def test_run_cached_stage_derives_heaviness_from_a_complete_workload(tmp_path, workload):
    paths = fake_paths(tmp_path)
    identity = manifest.cache_identity("census", {}, collector_version="c1")
    ran = []
    with pytest.raises(ValueError, match="workload"):
        manifest.run_cached_stage(paths, "census/w.json", identity, lambda: ran.append(1) or {},
                                  workload=workload)
    assert ran == [] and not (paths.run_root / "census" / "w.json").exists()


@pytest.mark.parametrize("bad", [
    dict(ARES_PARSE, ciks="0001287750"),  # a str is iterated per character: Ares check never fires
    dict(ARES_PARSE, ciks=[""]),
    dict(ARES_PARSE, ciks=[1287750]),
    dict(ARES_PARSE, instance_count=None),  # None is falsy: would read as "no parse"
    dict(ARES_PARSE, instance_count=True),  # bool is not a count
    dict(LIGHT, pipeline_cik_count=None),
    dict(LIGHT, pipeline_cik_count=False),
    dict(LIGHT, full_cache_scan=1),
    dict(LIGHT, full_cache_scan=None),
    dict(LIGHT, est_seconds=None),
])
def test_mistyped_workload_raises_instead_of_classifying_light(tmp_path, bad):
    from scripts.profile_pilot import protection
    with pytest.raises(ValueError, match="invalid workload"):
        manifest.classify_workload(bad)
    with pytest.raises(ValueError, match="invalid workload"):
        protection.requires_lease(**bad)
    paths = fake_paths(tmp_path)
    identity = manifest.cache_identity("census", {}, collector_version="c1")
    ran = []
    with pytest.raises(ValueError):
        manifest.run_cached_stage(paths, "census/t.json", identity, lambda: ran.append(1) or {},
                                  workload=bad)
    assert ran == []


def test_run_cached_stage_records_the_derived_classification(tmp_path):
    paths = fake_paths(tmp_path)
    identity = manifest.cache_identity("census", {}, collector_version="c1")
    out = manifest.run_cached_stage(paths, "census/c.json", identity, lambda: {"n": 1}, workload=LIGHT)
    assert out["requires_lease"] is False
    body = json.loads((paths.run_root / "census" / "c.json").read_text())
    assert body["requires_lease"] is False and body["workload"]["instance_count"] == 0


def test_nested_dependency_records_are_rehashed(tmp_path):
    paths = fake_paths(tmp_path)
    source = tmp_path / "source.csv"
    source.write_text("v1", encoding="utf-8")
    slice_file = tmp_path / "slice.parquet"
    slice_file.write_text("s1", encoding="utf-8")
    nested = manifest.file_record(slice_file, "slice")
    nested["source"] = manifest.file_record(source, "source")  # nested inside a record
    deps = {"single": manifest.file_record(tmp_path / "absent.csv", "absent"),
            "deep": {"slices": [nested]}}
    identity = manifest.cache_identity("census", deps, collector_version="c1")
    labels = sorted(r["label"] for r in manifest._identity_records(identity))
    assert labels == ["absent", "slice", "source"]
    manifest.run_cached_stage(paths, "census/n.json", identity, lambda: {"n": 1}, workload=LIGHT)
    source.write_text("v2", encoding="utf-8")  # only the nested record's file changes
    with pytest.raises(StageInvalidated, match="source.csv"):
        manifest.run_cached_stage(paths, "census/n.json", identity, lambda: {"n": 2}, workload=LIGHT)
    source.write_text("v1", encoding="utf-8")
    (tmp_path / "absent.csv").write_text("appeared", encoding="utf-8")  # single-dict dependency
    with pytest.raises(StageInvalidated, match="absent.csv"):
        manifest.run_cached_stage(paths, "census/n.json", identity, lambda: {"n": 2}, workload=LIGHT)


# ---------------------------------------------------------------- DuckDB spill confinement

def test_pilot_duckdb_spills_under_the_run_root(tmp_path):
    from scripts.profile_pilot.paths import pilot_duckdb
    paths = fake_paths(tmp_path)
    con = pilot_duckdb(paths)
    try:
        temp = con.execute("SELECT current_setting('temp_directory')").fetchone()[0]
    finally:
        con.close()
    assert Path(temp).resolve() == (paths.run_root / "tmp").resolve()
    assert (paths.run_root / "tmp").is_dir()


def test_pilot_cwd_confines_and_restores_the_working_directory(tmp_path):
    from scripts.profile_pilot.paths import pilot_cwd
    paths = fake_paths(tmp_path)
    original = os.getcwd()
    with pytest.raises(RuntimeError):
        with pilot_cwd(paths):
            assert Path(os.getcwd()).resolve() == paths.run_root.resolve()
            raise RuntimeError("stage failed")
    assert os.getcwd() == original


def test_materialise_slices_is_public_and_shared():
    from scripts.profile_pilot import graduate, verify
    assert callable(manifest.materialise_slices)
    assert not hasattr(verify, "_materialise_slices")
    source = Path(graduate.__file__).read_text(encoding="utf-8")
    assert "manifest.materialise_slices(paths)" in source and "_materialise_slices" not in source


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
    rows = manifest.verified_era_ledger(ledger, ["0001287750", "0001901037", "0001588272"],
                                        paths=fake_paths(tmp_path))
    assert rows["status"] == "present" and len(rows["sha256"]) == 64
    assert rows["ciks"]["0001287750"]["label"] == "verified_era_unreconciled"
    assert rows["ciks"]["0001287750"]["blocking_rows"] == 1
    assert rows["ciks"]["0001901037"]["label"] == "verified_era_reconciled"
    assert rows["ciks"]["0001588272"]["label"] == "verified_era_reconciled"
    assert rows["ciks"]["0001588272"]["rows"] == 0


def test_missing_verified_era_ledger_is_recorded_not_fatal(tmp_path):
    rows = manifest.verified_era_ledger(tmp_path / "absent.csv", ["0001287750"],
                                        paths=fake_paths(tmp_path))
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
