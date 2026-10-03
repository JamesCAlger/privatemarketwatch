"""Filer-profile pilot: the shared programme lease adapter, exercised against a fake main root.

`heavy_lock` refuses whenever another python process with `pytest` in its command
line is alive. In-process tests therefore control psutil discovery; the real psutil
path is exercised by a child process, which must see its pytest parent and refuse.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from pathlib import Path

import psutil
import pytest

import pipeline.programme.runner as runner
from scripts.profile_pilot import manifest, protection, verify
from scripts.profile_pilot.protection import LeaseRefused, shared_heavy_lease
from tests.test_profile_pilot_manifest import ARES_PARSE
from tests.test_profile_pilot_paths import CODE_ROOT, fake_paths


class FakeProcess:
    def __init__(self, pid, name, cmdline):
        self.pid = pid
        self.info = dict(pid=pid, name=name, cmdline=cmdline)


@pytest.fixture
def quiet_discovery(monkeypatch):
    """Discovery sees only this process; everything else is real psutil."""
    monkeypatch.setattr(psutil, "process_iter", lambda attrs=None: iter(
        [FakeProcess(os.getpid(), "python.exe", ["python", "-m", "pytest"])]))


def _lock(paths):
    return paths.main_repo_root / "data" / "programme" / "heavy.lock"


def _candidate(paths):
    return paths.main_repo_root / "data" / "programme" / "candidates" / paths.candidate_name


def test_lease_binds_main_root_and_writes_only_pilot_json(tmp_path, quiet_discovery):
    paths = fake_paths(tmp_path)
    original_root = runner.ROOT
    with shared_heavy_lease(paths, head="abc123") as lease:
        assert runner.ROOT == paths.main_repo_root
        assert lease.lock_path == _lock(paths)
        assert lease.candidate == _candidate(paths)
        held = json.loads(_lock(paths).read_text())
        assert held["controller_pid"] == os.getpid()
        assert Path(held["candidate"]) == _candidate(paths)
        assert sorted(p.name for p in _candidate(paths).iterdir()) == ["pilot.json"]
        pilot = json.loads((_candidate(paths) / "pilot.json").read_text())
        assert pilot["run_id"] == "stagea-test" and pilot["git_head"] == "abc123"
        assert pilot["pilot_root"] == str(paths.run_root)
    assert runner.ROOT == original_root
    assert not _lock(paths).exists()
    assert not _candidate(paths).exists()
    assert not (CODE_ROOT / "data" / "programme" / "heavy.lock").exists()
    assert not (_candidate(paths).parent / "attempts").exists()


def test_occupied_lease_is_refused_and_leaves_the_holder_alone(tmp_path, quiet_discovery):
    paths = fake_paths(tmp_path)
    original_root = runner.ROOT
    holder = psutil.Process(os.getppid())
    _lock(paths).write_text(json.dumps(dict(
        controller_pid=holder.pid, controller_created=holder.create_time(),
        candidate=str(_candidate(paths).parent / "v13-build"))))
    before = _lock(paths).read_text()
    with pytest.raises(LeaseRefused, match="owns the heavy-job lock"):
        with shared_heavy_lease(paths, head="h"):
            pytest.fail("must not run")
    assert _lock(paths).read_text() == before
    assert not _candidate(paths).exists()
    assert runner.ROOT == original_root


def test_concurrent_acquisition_in_one_process_is_refused(tmp_path, quiet_discovery):
    paths = fake_paths(tmp_path)
    other = fake_paths(tmp_path / "second", run_id="stagea-other")
    outcome = {}

    def contender():
        try:
            with shared_heavy_lease(other, head="h"):
                outcome["acquired"] = True
        except LeaseRefused as exc:
            outcome["refused"] = str(exc)

    with shared_heavy_lease(paths, head="h"):
        thread = threading.Thread(target=contender)
        thread.start()
        thread.join(30)
    assert "refused" in outcome and "acquired" not in outcome
    assert not _lock(other).exists()


def test_existing_pseudo_candidate_is_refused_and_kept_for_inspection(tmp_path, quiet_discovery):
    paths = fake_paths(tmp_path)
    _candidate(paths).mkdir(parents=True)
    (_candidate(paths) / "pilot.json").write_text("{}")
    with pytest.raises(LeaseRefused, match="already exists"):
        with shared_heavy_lease(paths, head="h"):
            pytest.fail("must not run")
    assert (_candidate(paths) / "pilot.json").is_file()
    assert not _lock(paths).exists()


def test_discovery_error_is_a_refusal_not_an_empty_process_list(tmp_path, monkeypatch):
    paths = fake_paths(tmp_path)

    def broken(attrs=None):
        raise psutil.AccessDenied(pid=4)

    monkeypatch.setattr(psutil, "process_iter", broken)
    with pytest.raises(LeaseRefused, match="inspection failed"):
        with shared_heavy_lease(paths, head="h"):
            pytest.fail("must not run")
    assert not _lock(paths).exists() and not _candidate(paths).exists()


def test_other_heavy_process_is_a_refusal(tmp_path, monkeypatch):
    paths = fake_paths(tmp_path)
    monkeypatch.setattr(psutil, "process_iter", lambda attrs=None: iter([
        FakeProcess(os.getpid(), "python.exe", ["python"]),
        FakeProcess(999999, "python.exe", ["python", "scripts/rebuild_outputs.py"])]))
    with pytest.raises(LeaseRefused, match="Another heavy job"):
        with shared_heavy_lease(paths, head="h"):
            pytest.fail("must not run")


def test_exception_releases_lock_and_keeps_candidate(tmp_path, quiet_discovery):
    paths = fake_paths(tmp_path)
    original_root = runner.ROOT
    with pytest.raises(RuntimeError, match="stage blew up"):
        with shared_heavy_lease(paths, head="h"):
            raise RuntimeError("stage blew up")
    assert not _lock(paths).exists()
    assert sorted(p.name for p in _candidate(paths).iterdir()) == ["pilot.json"]
    assert runner.ROOT == original_root


def test_stale_lock_protections_are_retained(tmp_path, quiet_discovery):
    paths = fake_paths(tmp_path)
    prior = _candidate(paths).parent / "old-candidate"
    telemetry = prior / "attempts" / "a1" / "telemetry"
    telemetry.mkdir(parents=True)
    (telemetry / "worker.json").write_text(json.dumps(dict(pid=os.getpid())))
    _lock(paths).write_text(json.dumps(dict(controller_pid=2 ** 22 + 7, controller_created=1.0,
                                            candidate=str(prior))))
    with pytest.raises(LeaseRefused, match="Interrupted worker"):
        with shared_heavy_lease(paths, head="h"):
            pytest.fail("must not run")
    (telemetry / "worker.json").write_text(json.dumps(dict(pid=2 ** 22 + 9)))
    with shared_heavy_lease(paths, head="h"):
        pass
    assert list(_lock(paths).parent.glob("heavy.stale-*.json"))


def test_real_psutil_refuses_inside_a_pytest_process_tree(tmp_path):
    paths = fake_paths(tmp_path)
    env = dict(os.environ, PROFILE_PILOT_PROBE_MAIN_ROOT=str(paths.main_repo_root),
               PROFILE_PILOT_PROBE_DATA_ROOT=str(paths.data_root))
    done = subprocess.run([sys.executable, "-m", "scripts.profile_pilot.verify", "lease-probe"],
                          cwd=CODE_ROOT, env=env, capture_output=True, text=True, timeout=120)
    result = json.loads(done.stdout.strip().splitlines()[-1])
    assert done.returncode == verify.EXIT_LEASE_REFUSED, done.stderr
    assert result["status"] == "refused"
    assert "Another heavy job is active" in result["reason"]
    assert not _lock(paths).exists() and not _candidate(paths).exists()


# ---------------------------------------------------------------- heavy classification (R3)

def test_heavy_classification_follows_ruling_r3():
    assert protection.requires_lease(ciks=["0001287750"], instance_count=1)
    assert protection.requires_lease(ciks=["0001803498"], instance_count=1)
    assert not protection.requires_lease(ciks=["0001901037"], instance_count=1)
    assert protection.requires_lease(ciks=["0001901037"], instance_count=2)
    assert protection.requires_lease(full_cache_scan=True)
    assert protection.requires_lease(pipeline_cik_count=9)
    assert protection.requires_lease(est_seconds=61)
    assert protection.requires_lease(est_bytes=5 * 2 ** 30)
    assert not protection.requires_lease(est_bytes=3 * 2 ** 30)
    assert not protection.requires_lease(ciks=[], instance_count=0)


# ---------------------------------------------------------------- stage through a cache miss

def test_cache_miss_that_is_heavy_takes_the_real_lease(tmp_path, quiet_discovery):
    paths = fake_paths(tmp_path)
    source = paths.main_repo_root / "data" / "output" / "existing.csv"
    identity = manifest.cache_identity("census", {"xml": [manifest.file_record(source, "xml")]},
                                       collector_version="c1")
    seen = []

    def compute():
        seen.append(_lock(paths).is_file())
        return {"rows": 1}

    lease = lambda: shared_heavy_lease(paths, head="h")  # noqa: E731
    first = manifest.run_cached_stage(paths, "census/a.json", identity, compute,
                                      workload=ARES_PARSE, lease=lease)
    assert first["cache"] == "miss" and first["requires_lease"] is True and seen == [True]
    second = manifest.run_cached_stage(paths, "census/a.json", identity, compute,
                                       workload=ARES_PARSE, lease=lease)
    assert second["cache"] == "hit" and seen == [True]
    assert not _lock(paths).exists()


def test_cache_miss_is_blocked_when_the_lease_is_refused(tmp_path, monkeypatch):
    paths = fake_paths(tmp_path)
    monkeypatch.setattr(psutil, "process_iter", lambda attrs=None: iter([
        FakeProcess(424242, "python.exe", ["python", "-m", "pytest", "tests"])]))
    identity = manifest.cache_identity("census", {}, collector_version="c1")
    with pytest.raises(LeaseRefused):
        manifest.run_cached_stage(paths, "census/b.json", identity, lambda: {"x": 1},
                                  workload=ARES_PARSE,
                                  lease=lambda: shared_heavy_lease(paths, head="h"))
    assert not (paths.run_root / "census" / "b.json").exists()


# ---------------------------------------------------------------- real coordination-path check

def test_lease_check_command_records_the_held_lock_and_cleans_up(tmp_path, quiet_discovery):
    paths = fake_paths(tmp_path)
    code = verify.main(["lease-check", "--main-root", str(paths.main_repo_root), "--data-root",
                        str(paths.data_root), "--run-id", "stagea-test"])
    assert code == 0
    receipt = json.loads(next((paths.run_root / "verification").glob("*_lease_check.json")).read_text())
    assert receipt["status"] == "acquired"
    assert receipt["candidate"] == str(_candidate(paths))
    assert receipt["candidate_entries"] == ["pilot.json"]
    assert receipt["heavy_lock_contents"]["controller_pid"] == os.getpid()
    assert Path(receipt["heavy_lock_contents"]["candidate"]) == _candidate(paths)
    assert receipt["released_utc"] and receipt["lock_present_after"] is False
    assert receipt["pilot_candidates_after"] == []
    assert not _lock(paths).exists() and not _candidate(paths).exists()


def test_lease_check_records_a_refusal_verbatim(tmp_path, monkeypatch):
    paths = fake_paths(tmp_path)
    monkeypatch.setattr(psutil, "process_iter", lambda attrs=None: iter([
        FakeProcess(424242, "python.exe", ["python", "-m", "pytest", "tests"])]))
    code = verify.main(["lease-check", "--main-root", str(paths.main_repo_root), "--data-root",
                        str(paths.data_root), "--run-id", "stagea-test"])
    assert code == verify.EXIT_LEASE_REFUSED
    receipt = json.loads(next((paths.run_root / "verification").glob("*_lease_check.json")).read_text())
    assert receipt["status"] == "refused" and "Another heavy job" in receipt["reason"]


def test_protocol_check_ignores_line_endings_but_not_content(tmp_path, quiet_discovery):
    paths = fake_paths(tmp_path)
    main_runner = paths.main_repo_root / "pipeline" / "programme" / "runner.py"
    text = (CODE_ROOT / "pipeline" / "programme" / "runner.py").read_bytes().replace(b"\r\n", b"\n")
    main_runner.write_bytes(text.replace(b"\n", b"\r\n"))  # opposite line endings: same protocol
    with shared_heavy_lease(paths, head="h"):
        pass
    main_runner.write_bytes(text + b"\n# drift\n")
    with pytest.raises(LeaseRefused, match="differs"):
        with shared_heavy_lease(paths, head="h"):
            pytest.fail("must not run")
    assert not _candidate(paths).exists()
