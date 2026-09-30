"""Task B2-2a: the all-quarter inventory, the stageb2- run-id prefix and the Stage B cross-check."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.profile_pilot import census_run, census_validate, cohort, lineage, manifest, verify
from scripts.profile_pilot.manifest import StageInvalidated
from tests.test_profile_pilot_m2_seed import TmpRunPaths
from tests.test_profile_pilot_paths import fake_paths, index_row, put_instance


def _paths(tmp_path, run_id="sp1-freeze-test"):
    # test_profile_pilot_all_quarters.py has no `_paths` helper of its own; this reuses the
    # TmpRunPaths fixture test_profile_pilot_m2_seed.py exports. PilotPaths construction does
    # not validate its fields (only resolve_paths does), so a bare tmp_path stands in for every
    # root -- fine here since freeze_inventory_content's callers under test monkeypatch
    # cohort.all_quarter_inventory and never touch the filesystem through `paths`.
    return TmpRunPaths(main_repo_root=tmp_path, code_root=tmp_path, data_root=tmp_path,
                       run_id=run_id, tmp_run_root=tmp_path / "run")


STELLUS, ARES, NEXPOINT = "0001901037", "0001287750", "0001588272"


def _stellus_rows():
    return [
        index_row("1901037", "0001104659-22-060380", "10-Q", "2022-05-13", "2022-03-31", status="not_found"),
        index_row("1901037", "0001558370-22-012334", "10-Q", "2022-08-12", "2022-06-30"),
        index_row("1901037", "0001558370-22-016375", "10-Q", "2022-11-04", "2022-09-30"),
        index_row("1901037", "0001558370-23-002790", "10-K", "2023-03-10", "2022-12-31"),
        index_row("1901037", "0001558370-23-009440", "10-Q", "2023-05-12", "2023-03-31"),
        index_row("1901037", "0001104659-26-059217", "10-Q", "2026-05-12", "2026-03-31"),
        index_row("1901037", "0001104659-26-099999", "10-Q", "2026-08-12", "2026-06-30"),
    ]


def _ares_rows():
    return [
        index_row("1287750", "0001287750-22-000052", "10-Q", "2022-10-25", "2022-09-30"),
        index_row("1287750", "0001287750-23-000010", "10-K", "2023-02-07", "2022-12-31"),
        index_row("1287750", "0001628280-23-010219", "10-K/A", "2023-04-01", "2022-12-31"),
        index_row("1287750", "0001287750-23-000021", "10-Q", "2023-04-25", "2023-03-31"),
    ]


def _fake(tmp_path, run_id="stageb2-test"):
    rows = _stellus_rows() + _ares_rows()
    paths = fake_paths(tmp_path, index_rows=rows, run_id=run_id)
    for row in rows:
        if row["xbrl_download_status"] == "cached":
            put_instance(paths.main_repo_root, row["cik"], row["accession_number"],
                         text="<xbrl>" + row["accession_number"] + "</xbrl>")
    put_instance(paths.main_repo_root, "1901037", "0009999999-24-000001", text="<xbrl>orphan</xbrl>")
    return paths


def _rows(content, cik):
    return [(r["quarter"], r["role"], r["status"], r.get("reason")) for r in content["fund_quarters"]
            if r["cik"] == cik]


# ---------------------------------------------------------------- all-quarter enumerator

def test_all_quarter_inventory_one_row_per_cached_fund_quarter_with_cohort_roles(tmp_path):
    paths = _fake(tmp_path)
    content = cohort.all_quarter_inventory(paths)
    assert _rows(content, STELLUS) == [
        ("2022-06-30", "all:2022-06-30", "selected", None),
        ("2022-09-30", "q1", "selected", None),
        ("2022-12-31", "q2", "selected", None),
        ("2023-03-31", "all:2023-03-31", "selected", None),
        ("2026-03-31", "verified_era", "selected", None),
    ]
    stellus = [r for r in content["fund_quarters"] if r["cik"] == STELLUS]
    assert [r["form_type"] for r in stellus] == ["10-Q", "10-Q", "10-K", "10-Q", "10-Q"]
    assert all(r["source_sha256"] and r["source_bytes"] for r in stellus)


def test_amended_quarters_are_excluded_with_the_scan_reason_and_keep_their_role(tmp_path):
    paths = _fake(tmp_path)
    content = cohort.all_quarter_inventory(paths)
    assert _rows(content, ARES) == [
        ("2022-09-30", "q1", "selected", None),
        ("2022-12-31", "q2", "unavailable", "selection_requires_amendment_scan"),
        ("2023-03-31", "all:2023-03-31", "selected", None),
        ("2026-03-31", "verified_era", "unavailable", "no_indexed_filing"),
    ]
    amended = next(r for r in content["fund_quarters"] if r["cik"] == ARES and r["quarter"] == "2022-12-31")
    assert sorted(c["form_type"] for c in amended["candidates"]) == ["10-K", "10-K/A"]


def test_every_cohort_role_stays_identifiable_and_cik_role_is_unique(tmp_path):
    paths = _fake(tmp_path)
    content = cohort.all_quarter_inventory(paths)
    keys = [(r["cik"], r["role"]) for r in content["fund_quarters"]]
    assert len(keys) == len(set(keys))
    cohort_keys = {(r["cik"], r["role"]) for r in cohort.fund_quarters(include_verified_era=True)}
    assert cohort_keys <= set(keys)
    # a CIK with no cached instance contributes only its cohort quarters (unavailable)
    assert _rows(content, NEXPOINT) == [
        ("2023-09-30", "q1", "unavailable", "no_indexed_filing"),
        ("2023-12-31", "q2", "unavailable", "no_indexed_filing"),
        ("2026-03-31", "verified_era", "unavailable", "no_indexed_filing"),
    ]
    assert all(r["role"] in ("q1", "q2", "verified_era") or r["role"] == "all:" + r["quarter"]
               for r in content["fund_quarters"])


def test_window_runs_from_the_earliest_cached_quarter_through_the_verified_era(tmp_path):
    paths = _fake(tmp_path)
    content = cohort.all_quarter_inventory(paths)
    quarters = [r["quarter"] for r in content["fund_quarters"] if r["cik"] == STELLUS]
    assert "2022-03-31" not in quarters and "2026-06-30" not in quarters
    window = content["window"][STELLUS]
    assert window["first"] == "2022-06-30" and window["last"] == cohort.VERIFIED_ERA_QUARTER
    assert window["indexed_quarters_before_window"] == ["2022-03-31"]
    assert window["indexed_quarters_after_window"] == ["2026-06-30"]
    assert content["window"][NEXPOINT]["first"] is None


def test_cached_instances_outside_the_index_are_recorded_not_dropped(tmp_path):
    paths = _fake(tmp_path)
    content = cohort.all_quarter_inventory(paths)
    orphans = content["cache_reconciliation"][STELLUS]["unindexed_cached_files"]
    assert [Path(p).name for p in orphans] == ["000999999924000001.xml"]
    assert content["cache_reconciliation"][ARES]["unindexed_cached_files"] == []


def test_all_quarter_inventory_is_sorted_and_deterministic(tmp_path):
    paths = _fake(tmp_path)
    first, second = cohort.all_quarter_inventory(paths), cohort.all_quarter_inventory(paths)
    assert manifest.digest(first) == manifest.digest(second)
    keys = [(r["cik"], r["quarter"]) for r in first["fund_quarters"]]
    assert keys == sorted(keys)
    assert first["quarters_mode"] == "all"
    assert first["counts"] == {"selected": 7, "unavailable": 20}  # 6 CIKs x 3 cohort rows + 2 Ares


def test_all_mode_shares_the_cohort_policy_and_index_records(tmp_path):
    paths = _fake(tmp_path)
    everything, primary = cohort.all_quarter_inventory(paths), cohort.primary_quarter_inventory(paths)
    assert everything["selection_policy"] == primary["selection_policy"]
    assert everything["filings_index"] == primary["filings_index"]
    by_role = {(r["cik"], r["role"]): r for r in everything["fund_quarters"]}
    for row in primary["fund_quarters"]:
        assert by_role[(row["cik"], row["role"])] == row


def test_scanner_without_a_held_lease_is_refused_in_all_mode(tmp_path):
    from scripts.profile_pilot.protection import LeaseRefused
    paths = _fake(tmp_path)
    with pytest.raises(LeaseRefused):
        cohort.all_quarter_inventory(paths, scanner=lambda *a: None, lease=None)


# ---------------------------------------------------------------- cohort mode is unchanged

def _normalised(value, main: str):
    if isinstance(value, dict):
        return {k: _normalised(v, main) for k, v in value.items()}
    if isinstance(value, list):
        return [_normalised(v, main) for v in value]
    if isinstance(value, str):
        return value.replace(main, "<main>").replace("\\", "/")
    return value


# Digest of the normalised cohort-mode inventory over _fake(), captured with the
# pre-B2-2a code (commit 509540e) before any change to cohort.py.
COHORT_MODE_PIN = "f17946a7994370f58c66d0b9fec8765251b1c3478d40a1caacfe2a02d8c75e21"


def test_cohort_mode_output_is_pinned_to_the_pre_change_digest(tmp_path):
    paths = _fake(tmp_path)
    content = cohort.primary_quarter_inventory(paths)
    got = manifest.digest(_normalised(content, str(paths.main_repo_root)))
    assert got == COHORT_MODE_PIN, got
    assert "quarters_mode" not in content and "window" not in content


# ---------------------------------------------------------------- freeze --quarters

def test_freeze_content_selects_the_inventory_by_quarters_mode(tmp_path):
    paths = _fake(tmp_path)
    assert verify.freeze_inventory_content(paths, "cohort") == cohort.primary_quarter_inventory(paths)
    assert verify.freeze_inventory_content(paths, "all") == cohort.all_quarter_inventory(paths)
    with pytest.raises(ValueError):
        verify.freeze_inventory_content(paths, "some")


def test_freeze_cli_defaults_to_cohort_and_accepts_all(monkeypatch):
    seen = []
    monkeypatch.setattr(verify, "cmd_freeze", lambda args: seen.append(args.quarters) or 0)
    base = ["freeze", "--data-root", "D", "--run-id", "stageb2-x"]
    assert verify.main(base) == 0 and verify.main(base + ["--quarters", "all"]) == 0
    assert seen == ["cohort", "all"]
    with pytest.raises(SystemExit):
        verify.main(base + ["--quarters", "some"])


# ---------------------------------------------------------------- run-id prefix

@pytest.mark.parametrize("module", [census_run, census_validate])
def test_stage_runners_accept_stageb2_and_still_refuse_other_prefixes(module, tmp_path, monkeypatch, capsys):
    from scripts.profile_pilot import protection
    paths = _fake(tmp_path)

    def discovery(*a, **k):
        raise RuntimeError("sentinel past the prefix check")

    monkeypatch.setattr(protection, "process_conflicts", discovery)
    common = ["run", "--main-root", str(paths.main_repo_root), "--data-root", str(paths.data_root)]
    assert module.main(common + ["--run-id", "stagea-x"]) == 4
    assert "must start with" in capsys.readouterr().out
    for run_id in ("stageb-x", "stageb2-census-x"):
        assert module.main(common + ["--run-id", run_id]) == 4
        assert "sentinel past the prefix check" in capsys.readouterr().out


# ---------------------------------------------------------------- lineage over all: roles

def _listing(paths, rows):
    from scripts.profile_pilot.paths import write_once_json
    for row in rows:
        target = paths.run_root / row["census_relative"]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("{}", encoding="ascii")
        row["census_sha256"] = manifest.sha256_file(target)
    write_once_json(paths, lineage.AUTHORITATIVE_RELATIVE, dict(fund_quarters=rows))


def test_lineage_reads_all_roles_and_keeps_cik_role_unique(tmp_path):
    paths = _fake(tmp_path, run_id="stageb2-census-a")
    rows = [dict(cik=STELLUS, role=role, report_date=date, validation_verdict="pass",
                 census_relative="census/" + STELLUS + "/" + date + ".json")
            for role, date in (("q1", "2022-09-30"), ("all:2023-03-31", "2023-03-31"))]
    _listing(paths, rows)
    got = lineage.load_authoritative_census(paths, "stageb2-census-a", roles=("q1", "all:2023-03-31"),
                                            ciks=(STELLUS,))
    assert sorted(got["rows"]) == [(STELLUS, "all:2023-03-31"), (STELLUS, "q1")]
    other = lineage.sibling_root(paths, "stageb2-census-b")
    dup = [dict(r, census_relative=r["census_relative"]) for r in rows]
    dup[1] = dict(dup[1], role="q1")
    _listing(other, dup)
    with pytest.raises(StageInvalidated):
        lineage.load_authoritative_census(paths, "stageb2-census-b", roles=("q1",), ciks=(STELLUS,))


# ---------------------------------------------------------------- Stage B cross-check

def _census_doc(positions, *, fingerprint="f" * 64, code_sha="a", wrapper_path="w1", elapsed=1.0):
    result = dict(document=dict(cik=STELLUS, report_date="2022-09-30"),
                  collection=dict(state="complete", elapsed_seconds=elapsed),
                  dependencies=[dict(label="wrapper", path=wrapper_path, sha256="s")],
                  summary=dict(position_observations=positions, position_observations_current=positions),
                  measurement=dict(wall_seconds=elapsed),
                  cache_identity=dict(fingerprint=fingerprint))
    identity = dict(fingerprint=fingerprint, collector_version="c",
                    dependencies=dict(code=[dict(label="code/x.py", path="x", sha256=code_sha)],
                                      wrapper=dict(label="wrapper/x", path=wrapper_path, sha256="s")))
    return dict(identity=identity, complete=True, result=result)


def _row(fingerprint="f" * 64, versions=("c", "v", "d")):
    return dict(cik=STELLUS, role="q1", report_date="2022-09-30", fingerprint=fingerprint,
                collector_version=versions[0], census_version=versions[1], detector_version=versions[2])


def test_crosscheck_counts_identity_matches_and_separates_content_equality():
    from scripts.profile_pilot import census_crosscheck as cc
    same = cc.compare_pair(_row(), _census_doc(5), _row(), _census_doc(5, elapsed=9.0))
    assert same["match"] is True and same["content_equal"] is True
    moved = cc.compare_pair(_row(), _census_doc(5), _row("e" * 64),
                            _census_doc(5, fingerprint="e" * 64, code_sha="b", wrapper_path="w2"))
    assert moved["match"] is False and moved["fingerprint_equal"] is False
    assert moved["content_equal"] is True and moved["positions_equal"] is True
    assert moved["dependency_differences"] == dict(sha256=["code/x.py"], path_only=["wrapper/x"])
    fewer = cc.compare_pair(_row(), _census_doc(5), _row(), _census_doc(4))
    assert fewer["match"] is False and fewer["positions_equal"] is False and fewer["content_equal"] is False
    bumped = cc.compare_pair(_row(), _census_doc(5), _row(versions=("c", "v2", "d")), _census_doc(5))
    assert bumped["versions_equal"] is False and bumped["match"] is False


def test_crosscheck_reports_a_missing_new_row_as_a_finding():
    from scripts.profile_pilot import census_crosscheck as cc
    got = cc.compare_pair(_row(), _census_doc(5), None, None)
    assert got["match"] is False and got["status"] == "missing_in_new_root"


def _census_root(paths, run_id, docs, excluded, inventory):
    from scripts.profile_pilot.paths import write_once_json
    root = lineage.sibling_root(paths, run_id)
    rows = []
    for (role, date), doc in docs.items():
        relative = "census/" + STELLUS + "/" + date + ".json"
        write_once_json(root, relative, doc)
        rows.append(dict(_row(doc["identity"]["fingerprint"]), role=role, report_date=date,
                         census_relative=relative, validation_verdict="pass",
                         census_sha256=manifest.sha256_file(root.run_root / relative)))
    write_once_json(root, lineage.AUTHORITATIVE_RELATIVE, dict(fund_quarters=rows))
    write_once_json(root, lineage.EXCLUDED_RELATIVE, dict(fund_quarters=excluded))
    manifest.freeze_inventory(root, "primary_quarter_inventory", inventory)
    return root


def test_crosscheck_run_compares_every_reference_row_and_pins_the_cohort_inventory(tmp_path):
    from scripts.profile_pilot import census_crosscheck as cc
    paths = _fake(tmp_path, run_id="stageb2-census-new")
    primary = cohort.primary_quarter_inventory(paths)
    everything = cohort.all_quarter_inventory(paths)
    gone = [dict(cik=ARES, role="q2", reason="unavailable", detail="selection_requires_amendment_scan")]
    _census_root(paths, "stageb-ref", {("q1", "2022-09-30"): _census_doc(5), ("q2", "2022-12-31"): _census_doc(7)},
                 gone, primary)
    new = _census_root(paths, "stageb2-census-new",
                       {("q1", "2022-09-30"): _census_doc(5, elapsed=3.0),
                        ("all:2023-03-31", "2023-03-31"): _census_doc(9)},
                       gone + [dict(cik=STELLUS, role="all:2022-06-30", reason="validation_failed")], everything)
    body = cc.run(new, reference_run_id="stageb-ref")
    assert body["compared"] == 2 and body["tally"]["match"] == 1
    assert [p["status"] for p in body["pairs"]] == ["compared", "missing_in_new_root"]
    assert body["cohort_exclusions"]["equal"] is True
    regression = body["cohort_inventory_regression"]
    assert regression["identical"] is True and regression["new_root_cohort_rows_equal_reference"] is True


# ---------------------------------------------------------------- amendment-scan wiring (SP1 Task 1)

def test_freeze_all_with_scan_passes_the_default_scanner_under_a_held_lease(tmp_path, monkeypatch):
    from scripts.profile_pilot import verify as verify_mod, cohort as cohort_mod
    seen = {}

    def fake_inventory(paths, *, scanner=None, lease=None):
        seen["scanner"] = scanner
        seen["lease"] = lease
        return dict(fund_quarters=[])

    class Lease:
        held = True
        lock_path = tmp_path / "heavy.lock"

    monkeypatch.setattr(cohort_mod, "all_quarter_inventory", fake_inventory)
    paths = _paths(tmp_path)
    verify_mod.freeze_inventory_content(paths, "all", scan_amendments=True, lease=Lease())
    from scripts import run_context_census
    assert seen["scanner"] is run_context_census.scan_instance
    assert seen["lease"].held is True


def test_freeze_all_without_scan_keeps_scanner_none(tmp_path, monkeypatch):
    from scripts.profile_pilot import verify as verify_mod, cohort as cohort_mod
    seen = {}
    monkeypatch.setattr(cohort_mod, "all_quarter_inventory",
                        lambda paths, *, scanner=None, lease=None: seen.update(scanner=scanner) or dict(fund_quarters=[]))
    verify_mod.freeze_inventory_content(_paths(tmp_path), "all")
    assert seen["scanner"] is None


def test_scan_flag_with_cohort_quarters_is_refused(tmp_path):
    from scripts.profile_pilot import verify as verify_mod
    with pytest.raises(ValueError, match="scan-amendments"):
        verify_mod.freeze_inventory_content(_paths(tmp_path), "cohort", scan_amendments=True)


def test_cmd_freeze_refuses_cohort_plus_scan_before_taking_the_lease(monkeypatch):
    # Fix round 1 (review finding): cmd_freeze must validate --quarters/--scan-amendments
    # BEFORE protection.shared_heavy_lease is ever entered, so a bad combination never
    # acquires the real shared lease or leaves a stray pseudo-candidate under the main
    # checkout. Fail the test if the lease factory is reached at all.
    from scripts.profile_pilot import protection, verify as verify_mod

    def fail_if_called(*args, **kwargs):
        raise AssertionError("shared_heavy_lease must not be entered when validation fails")

    monkeypatch.setattr(protection, "shared_heavy_lease", fail_if_called)
    args = SimpleNamespace(quarters="cohort", scan_amendments=True)
    with pytest.raises(ValueError, match="scan-amendments"):
        verify_mod.cmd_freeze(args)
