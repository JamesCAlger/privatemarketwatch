"""Filer-profile pilot: protection of the REAL main outputs, proven against a fake main root.

The worktree's own data/output and frontend/public/data are empty here, which is
exactly the loophole the plugin closes: the shared conftest guard only covers the
importing checkout.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import duckdb
import pytest

from scripts.profile_pilot import protection, verify
from scripts.profile_pilot.protection import PreservationError
from tests.test_profile_pilot_paths import CODE_ROOT, fake_paths

PROBE_ENV = "PROFILE_PILOT_INNER_PROBE"


def _worktree_output_files():
    root = CODE_ROOT / "data" / "output"
    return [p for p in root.rglob("*") if p.is_file()] if root.is_dir() else []


def test_worktree_data_output_holds_no_files():
    # Precondition for the loophole this module closes: the conftest guard's
    # data/output root is the worktree's, which holds nothing. (The worktree's
    # frontend/public/data is a tracked copy, not the main site data.)
    assert _worktree_output_files() == []


def test_open_guard_blocks_python_writes_to_fake_main_roots(tmp_path):
    paths = fake_paths(tmp_path)
    target = paths.main_repo_root / "data" / "output" / "existing.csv"
    uninstall = protection.install_open_guard(paths.protected_roots)
    try:
        with pytest.raises(AssertionError, match="protected"):
            open(target, "a", encoding="utf-8")
        with pytest.raises(AssertionError):
            (paths.main_repo_root / "frontend" / "public" / "data" / "new.json").write_text("{}")
        with pytest.raises(AssertionError):
            (CODE_ROOT / "data" / "output" / "never.csv").write_text("x")
        assert target.read_text(encoding="utf-8") == "a,b\n1,2\n"  # reads still allowed
        allowed = paths.run_root / "ok.json"
        allowed.parent.mkdir(parents=True)
        allowed.write_text("{}", encoding="ascii")
    finally:
        uninstall()
    assert target.read_text(encoding="utf-8") == "a,b\n1,2\n"
    assert not (CODE_ROOT / "data" / "output" / "never.csv").exists()


def test_protected_session_detects_native_duckdb_copy(tmp_path):
    paths = fake_paths(tmp_path)
    native = paths.main_repo_root / "data" / "output" / "native.csv"
    with pytest.raises(PreservationError, match="created"):
        with protection.protected_session(paths, receipt="verification/session.json"):
            con = duckdb.connect()
            try:
                con.execute(f"COPY (SELECT 1 AS a) TO '{native.as_posix()}' (HEADER)")
            finally:
                con.close()
    receipt = json.loads((paths.run_root / "verification" / "session.json").read_text())
    assert receipt["verdict"] == "FAIL"
    assert str(native) in receipt["comparison"]["created"]
    assert str(paths.main_repo_root / "data" / "output") in receipt["protected_roots"]


def test_protected_session_snapshots_after_body_failure(tmp_path):
    paths = fake_paths(tmp_path)
    existing = paths.main_repo_root / "frontend" / "public" / "data" / "site.json"
    with pytest.raises(PreservationError) as raised:
        with protection.protected_session(paths, receipt="verification/failed.json"):
            con = duckdb.connect()
            try:
                con.execute(f"COPY (SELECT 2 AS b) TO '{existing.as_posix()}' (FORMAT csv, HEADER)")
            finally:
                con.close()
            raise ValueError("stage failed")
    assert isinstance(raised.value.__context__, ValueError)
    receipt = json.loads((paths.run_root / "verification" / "failed.json").read_text())
    assert str(existing) in receipt["comparison"]["changed"]
    assert receipt["body_error"].startswith("ValueError")


def test_protected_session_passes_when_untouched(tmp_path):
    paths = fake_paths(tmp_path)
    with protection.protected_session(paths, receipt="verification/clean.json") as session:
        (paths.run_root / "inputs").mkdir(parents=True, exist_ok=True)
        (paths.run_root / "inputs" / "frame.json").write_text("{}", encoding="ascii")
    receipt = json.loads((paths.run_root / "verification" / "clean.json").read_text())
    assert receipt["verdict"] == "PASS" and session["verdict"] == "PASS"
    assert receipt["before"]["file_count"] >= 2


def _fake_code_root(tmp_path):
    code = tmp_path / "code"
    (code / "pipeline").mkdir(parents=True)
    (code / "scripts" / "profile_pilot").mkdir(parents=True)
    (code / "scripts" / "profile_pilot" / "__init__.py").write_text("", encoding="ascii")
    wrappers = code / "data" / "overrides" / "bdc_xbrl_wrappers"
    wrappers.mkdir(parents=True)
    (wrappers / "0000000001.json").write_text("{}", encoding="ascii")
    return code


@pytest.mark.parametrize("change", ["python", "native", "delete"])
def test_a_change_under_data_overrides_fails_preservation(tmp_path, change):
    # Minor B: the code root's data/overrides is a read-only root (inventoried before/after).
    from scripts.profile_pilot.paths import resolve_paths
    main = fake_paths(tmp_path).main_repo_root
    paths = resolve_paths(main_repo_root=main, data_root=main / "data", code_root=_fake_code_root(tmp_path),
                          run_id="stageb-test")
    wrapper = paths.code_root / "data" / "overrides" / "bdc_xbrl_wrappers" / "0000000001.json"
    assert paths.read_only_roots == ((paths.code_root / "data" / "overrides").resolve(),)
    specs = {str(s.path): s.mode for s in protection.root_specs(paths)}
    assert specs[str(paths.read_only_roots[0])] == "full"
    with pytest.raises(PreservationError):
        with protection.protected_session(paths, receipt="verification/overrides.json"):
            if change == "python":
                with pytest.raises(AssertionError, match="protected"):
                    wrapper.write_text("{\"x\": 1}", encoding="ascii")
                os.utime(wrapper, ns=(1, 1))  # a change the Python guard cannot see
            elif change == "native":
                con = duckdb.connect()
                target = wrapper.parent / "native.json"
                con.execute("COPY (SELECT 1 AS a) TO '" + target.as_posix() + "' (FORMAT csv)")
                con.close()
            else:
                wrapper.unlink()
    receipt = json.loads((paths.run_root / "verification" / "overrides.json").read_text())
    assert receipt["verdict"] == "FAIL"
    assert str(paths.read_only_roots[0]) in receipt["read_only_roots"]


def test_inventory_inspection_failure_fails_preservation(tmp_path, monkeypatch):
    paths = fake_paths(tmp_path)
    specs = protection.root_specs(paths)
    before = protection.inventory(specs)
    real_scandir = os.scandir

    def broken(path):
        if Path(path) == paths.main_repo_root / "frontend" / "public" / "data":
            raise PermissionError("denied")
        return real_scandir(path)

    monkeypatch.setattr(protection.os, "scandir", broken)
    after = protection.inventory(specs)
    comparison = protection.compare(before, after)
    assert comparison["ok"] is False
    assert comparison["errors_after"]


def test_main_output_inventory_boundary_is_explicit(tmp_path):
    paths = fake_paths(tmp_path)
    deep = paths.main_repo_root / "data" / "output" / "quarter_pass" / "p1"
    deep.mkdir(parents=True)
    (deep / "state.json").write_text("{}", encoding="ascii")
    specs = {str(s.path): s.mode for s in protection.root_specs(paths)}
    assert specs[str(paths.main_repo_root / "data" / "output")] == protection.MAIN_OUTPUT_MODE
    assert specs[str(paths.main_repo_root / "frontend" / "public" / "data")] == "full"
    listing = protection.inventory(protection.root_specs(paths))
    if protection.MAIN_OUTPUT_MODE == "full":
        assert str(deep / "state.json") in listing["files"]
    shallow = protection.inventory([protection.RootSpec(paths.main_repo_root / "data" / "output",
                                                        "depth1")])
    assert str(deep / "state.json") not in shallow["files"]
    assert str(paths.main_repo_root / "data" / "output" / "quarter_pass") in shallow["files"]


# ---------------------------------------------------------------- pytest plugin, end to end

def _run_inner(tmp_path, paths, node, *, extra_env=None, with_env=True):
    receipt = tmp_path / "inner_receipt.json"
    env = {k: v for k, v in os.environ.items() if not k.startswith("PROFILE_PILOT_")}
    if with_env:
        env.update(verify.plugin_env(paths, receipt))
    env[PROBE_ENV] = "1"
    env.update(extra_env or {})
    command = [sys.executable, "-m", "pytest", "-p", "scripts.profile_pilot.pytest_plugin",
               "-q", "-p", "no:cacheprovider", f"tests/test_profile_pilot_protection.py::{node}"]
    done = subprocess.run(command, cwd=CODE_ROOT, env=env, capture_output=True, text=True,
                          timeout=300)
    return done, receipt


def test_plugin_blocks_python_write_and_catches_native_write_in_a_real_session(tmp_path):
    paths = fake_paths(tmp_path)
    done, receipt_path = _run_inner(tmp_path, paths, "test_inner_probe_writes_fake_main",
                                    extra_env={"PROFILE_PILOT_PROBE_MODE": "fail"})
    assert done.returncode == 3, done.stdout + done.stderr
    receipt = json.loads(receipt_path.read_text())
    native = str(paths.main_repo_root / "data" / "output" / "probe_native.csv")
    assert receipt["verdict"] == "FAIL"
    assert native in receipt["comparison"]["created"]
    assert receipt["conftest_guard_extended"] is True
    assert receipt["test_exitstatus"] == 1  # the probe failed on purpose; snapshot still ran
    assert not (paths.main_repo_root / "data" / "output" / "probe_python.csv").exists()


def test_plugin_passes_a_clean_session(tmp_path):
    paths = fake_paths(tmp_path)
    done, receipt_path = _run_inner(tmp_path, paths, "test_inner_probe_reads_only")
    assert done.returncode == 0, done.stdout + done.stderr
    receipt = json.loads(receipt_path.read_text())
    assert receipt["verdict"] == "PASS"
    assert str(paths.main_repo_root / "data" / "output") in receipt["protected_roots"]
    assert str(CODE_ROOT / "data" / "output") in receipt["protected_roots"]


def test_plugin_refuses_to_run_without_roots(tmp_path):
    paths = fake_paths(tmp_path)
    done, _ = _run_inner(tmp_path, paths, "test_inner_probe_reads_only", with_env=False)
    assert done.returncode != 0
    assert "PROFILE_PILOT_MAIN_ROOT" in done.stdout + done.stderr


@pytest.mark.skipif(os.environ.get(PROBE_ENV) != "1", reason="inner probe for the plugin tests")
def test_inner_probe_writes_fake_main():
    main = Path(os.environ["PROFILE_PILOT_MAIN_ROOT"])
    output = main / "data" / "output"
    # The shared conftest guard now also covers the fake main root.
    conftest = sys.modules.get("tests.conftest") or sys.modules.get("conftest")
    assert conftest is not None and conftest._is_protected_path(output / "x.csv")
    with pytest.raises(AssertionError):
        (output / "probe_python.csv").write_text("x")
    con = duckdb.connect()
    try:
        con.execute(f"COPY (SELECT 1 AS a) TO '{(output / 'probe_native.csv').as_posix()}' (HEADER)")
    finally:
        con.close()
    if os.environ.get("PROFILE_PILOT_PROBE_MODE") == "fail":
        pytest.fail("deliberate failure after a native write")


@pytest.mark.skipif(os.environ.get(PROBE_ENV) != "1", reason="inner probe for the plugin tests")
def test_inner_probe_reads_only():
    main = Path(os.environ["PROFILE_PILOT_MAIN_ROOT"])
    assert (main / "data" / "output" / "existing.csv").read_text(encoding="utf-8")


# ---------------------------------------------------------------- semantic-diff backstop

FAKE_DIFF = '''from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
SEMANTIC_REPORT_FILE = ROOT / "data" / "output" / "semantic_diff_report.json"
def diff(compare_sql=True, semantic=False):
    if semantic:
        SEMANTIC_REPORT_FILE.write_text("{}", encoding="utf-8")
        print("Semantic diff report: " + SEMANTIC_REPORT_FILE.relative_to(ROOT).as_posix())
    marker = ROOT / "data" / "output" / "diverged.txt"
    if marker.exists():
        print("Diff failed: 1 divergent artifact(s), 3 checked, 0 skipped")
        print("- data/output/a.csv: differs from baseline")
        return 1
    print("Diff clean: 3 checked, 0 explicitly skipped")
    return 0
'''


def _fake_diff_script(paths):
    script = paths.main_repo_root / "scripts" / "diff_outputs.py"
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text(FAKE_DIFF, encoding="utf-8")


def test_backstop_runs_in_main_root_and_keeps_report_out_of_outputs(tmp_path):
    paths = fake_paths(tmp_path)
    _fake_diff_script(paths)
    before = protection.inventory(protection.root_specs(paths))
    result = verify.run_backstop(paths, "verification/inv1", label="post")
    after = protection.inventory(protection.root_specs(paths))
    assert protection.compare(before, after)["ok"]
    assert result["exit_code"] == 0 and result["inspection_ok"] is True
    assert result["cwd"] == str(paths.main_repo_root)
    assert "--semantic" in result["command"]
    # tmp paths contain "pytest"; they must not reach the process command line,
    # or heavy_lock elsewhere would read the backstop as a heavy job.
    assert not any("pytest" in part for part in result["command"])
    assert result["baseline_differences"] == []
    assert not (paths.main_repo_root / "data" / "output" / "semantic_diff_report.json").exists()
    assert Path(result["report_path"]).is_relative_to(paths.run_root)
    for name in ("stdout", "stderr"):
        assert Path(result[name + "_path"]).is_file()


def test_backstop_separates_preexisting_baseline_differences(tmp_path):
    paths = fake_paths(tmp_path)
    _fake_diff_script(paths)
    (paths.main_repo_root / "data" / "output" / "diverged.txt").write_text("x")
    pre = verify.run_backstop(paths, "verification/inv2", label="pre")
    post = verify.run_backstop(paths, "verification/inv2", label="post")
    verdict = verify.backstop_verdict(pre, post)
    assert post["exit_code"] == 1 and post["inspection_ok"] is True
    assert verdict["preexisting_baseline_differences"] == ["data/output/a.csv"]
    assert verdict["new_differences"] == [] and verdict["ok"] is True


def test_backstop_crash_is_failed_inspection(tmp_path):
    paths = fake_paths(tmp_path)
    script = paths.main_repo_root / "scripts" / "diff_outputs.py"
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text("raise SystemExit('boom')\n", encoding="utf-8")
    post = verify.run_backstop(paths, "verification/inv3", label="post")
    assert post["inspection_ok"] is False
    assert verify.backstop_verdict(None, post)["ok"] is False


def _launch_with_discovery(tmp_path, monkeypatch, discovery):
    paths = fake_paths(tmp_path)
    monkeypatch.setattr(protection, "process_conflicts", discovery)

    def no_subprocess(*args, **kwargs):
        raise AssertionError("launcher started a subprocess despite refusing")

    monkeypatch.setattr(verify.subprocess, "run", no_subprocess)
    code = verify.main(["test", "--main-root", str(paths.main_repo_root), "--data-root",
                        str(paths.data_root), "--run-id", "stagea-test",
                        "tests/test_profile_pilot_paths.py"])
    refusals = list((paths.run_root / "verification").rglob("refused.json"))
    return code, refusals


def test_launcher_refuses_when_another_heavy_process_exists(tmp_path, monkeypatch):
    code, refusals = _launch_with_discovery(
        tmp_path, monkeypatch,
        lambda: [dict(pid=4242, command="python scripts/rebuild_outputs.py")])
    assert code == verify.EXIT_REFUSED
    assert len(refusals) == 1 and "other heavy jobs" in refusals[0].read_text()


def test_launcher_refuses_when_process_discovery_fails(tmp_path, monkeypatch):
    import psutil

    def broken():
        raise psutil.AccessDenied(pid=4)

    code, refusals = _launch_with_discovery(tmp_path, monkeypatch, broken)
    assert code == verify.EXIT_REFUSED
    assert len(refusals) == 1 and "process discovery failed" in refusals[0].read_text()


def test_launcher_documents_the_r9_lease_exemption():
    doc = verify.__doc__
    assert "R9" in doc and "process check" in doc and "pytest" in doc
    assert "R9" in protection.requires_lease.__doc__


def test_launcher_refuses_non_pilot_test_targets(tmp_path):
    with pytest.raises(SystemExit):
        verify.validate_test_targets(["tests/test_unified_holdings.py"])
    with pytest.raises(SystemExit):
        verify.validate_test_targets([])
    assert verify.validate_test_targets(["tests/test_profile_pilot_paths.py"]) == [
        "tests/test_profile_pilot_paths.py"]
