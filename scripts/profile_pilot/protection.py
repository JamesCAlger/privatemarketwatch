"""Protection of the REAL main outputs and the shared programme heavy-job lease.

Module import is stdlib-only so the pytest plugin can install the write guard before
collection imports any pipeline code. The lease adapter imports the programme
runner lazily.
"""
from __future__ import annotations

import builtins
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
import importlib
import io
import json
import os
from pathlib import Path
import sys
import threading
import time
import traceback

WRITE_MODE_CHARS = frozenset("wax+")
# Measured 2026-09-28 (verify measure-inventory): a full walk of the main data/output
# tree is 237,529 files in 9.96 s warm (a cold `find` took 46 s), inside the 60 s
# budget, so every protected root is walked in full. "depth1" (every file AND
# directory entry directly under the root) remains the documented fallback if the
# tree outgrows the budget; the Python-write guard covers every depth either way.
MAIN_OUTPUT_MODE = "full"
HEAVY_ESTIMATE_SECONDS = 60
HEAVY_ESTIMATE_BYTES = 2 * 2 ** 30
PIPELINE_CIK_LIMIT = 8


class PreservationError(RuntimeError):
    """A protected artifact changed, or the protected roots could not be inspected."""


class LeaseRefused(RuntimeError):
    """The shared programme lease could not be inspected or acquired."""


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------- Python-write guard

def is_under(path, roots) -> bool:
    resolved = Path(path).resolve(strict=False)
    return any(resolved == root or resolved.is_relative_to(root) for root in roots)


def install_open_guard(roots):
    """Chain a guard over builtins.open and io.open; return an uninstall callable."""
    roots = tuple(Path(r).resolve(strict=False) for r in roots)
    previous_builtin, previous_io = builtins.open, io.open

    def check(file, mode):
        if isinstance(file, (str, bytes, os.PathLike)) and any(c in mode for c in WRITE_MODE_CHARS):
            if is_under(os.fsdecode(file), roots):
                raise AssertionError("profile pilot blocked a write to a protected path: "
                                     + str(Path(os.fsdecode(file)).resolve(strict=False))
                                     + " (mode=" + repr(mode) + ")")

    def guarded_builtin(file, mode="r", *args, **kwargs):
        check(file, mode)
        return previous_builtin(file, mode, *args, **kwargs)

    def guarded_io(file, mode="r", *args, **kwargs):
        check(file, mode)
        return previous_io(file, mode, *args, **kwargs)

    guarded_builtin.profile_pilot_roots = roots
    builtins.open = guarded_builtin
    io.open = guarded_io

    def uninstall():
        if builtins.open is guarded_builtin:
            builtins.open = previous_builtin
        if io.open is guarded_io:
            io.open = previous_io

    return uninstall


# ---------------------------------------------------------------- native-IO inventory

@dataclass(frozen=True)
class RootSpec:
    path: Path
    mode: str  # "full" or "depth1"


def root_specs(paths=None, *, roots=None, main_repo_root=None) -> list[RootSpec]:
    """Inventory boundary per protected root; main (and data-root) output uses MAIN_OUTPUT_MODE.

    With `paths`, the read-only roots (worktree data/overrides) are inventoried in full
    beside the protected roots, so a change there fails preservation like any other."""
    if paths is not None:
        roots = tuple(paths.protected_roots) + tuple(r for r in paths.read_only_roots
                                                     if r not in paths.protected_roots)
        shallow = {(paths.main_repo_root / "data" / "output").resolve(strict=False),
                   paths.output_root.resolve(strict=False)}
    else:
        shallow = {(Path(main_repo_root) / "data" / "output").resolve(strict=False)} if main_repo_root else set()
    return [RootSpec(Path(r), MAIN_OUTPUT_MODE if Path(r) in shallow else "full") for r in roots]


def guarded_roots(paths) -> tuple:
    """Roots the Python-write guard blocks: protected roots plus read-only roots."""
    return tuple(paths.protected_roots) + tuple(r for r in paths.read_only_roots if r not in paths.protected_roots)


def inventory(specs) -> dict:
    """(mtime_ns, size) per entry; any listing or stat failure is recorded, never skipped."""
    started = time.perf_counter()
    files: dict[str, list[int]] = {}
    errors: list[str] = []

    def record(entry_path: str, entry) -> None:
        try:
            info = entry.stat(follow_symlinks=False)
        except OSError as exc:
            errors.append("stat " + entry_path + ": " + type(exc).__name__)
            return
        files[entry_path] = [info.st_mtime_ns, info.st_size]

    for spec in specs:
        root = Path(spec.path)
        if not root.exists():
            continue
        pending = [str(root)]
        while pending:
            directory = pending.pop()
            try:
                with os.scandir(directory) as entries:
                    listing = list(entries)
            except OSError as exc:
                errors.append("list " + directory + ": " + type(exc).__name__)
                continue
            for entry in listing:
                try:
                    is_dir = entry.is_dir(follow_symlinks=False)
                except OSError as exc:
                    errors.append("type " + entry.path + ": " + type(exc).__name__)
                    continue
                if spec.mode == "depth1":
                    record(entry.path, entry)
                elif is_dir:
                    pending.append(entry.path)
                else:
                    record(entry.path, entry)
    return dict(taken_utc=_now(), seconds=round(time.perf_counter() - started, 3),
                file_count=len(files), files=files, errors=sorted(errors),
                specs=[dict(path=str(s.path), mode=s.mode) for s in specs])


def compare(before: dict, after: dict) -> dict:
    old, new = before["files"], after["files"]
    created = sorted(set(new) - set(old))
    deleted = sorted(set(old) - set(new))
    changed = sorted(p for p in set(old) & set(new) if old[p] != new[p])
    ok = not (created or deleted or changed or before["errors"] or after["errors"])
    return dict(ok=ok, created=created, deleted=deleted, changed=changed,
                errors_before=before["errors"], errors_after=after["errors"])


def summarize(before: dict, after: dict, comparison: dict) -> dict:
    def brief(listing):
        return {k: listing[k] for k in ("taken_utc", "seconds", "file_count", "specs")}
    return dict(verdict="PASS" if comparison["ok"] else "FAIL", before=brief(before),
                after=brief(after), comparison=comparison)


@contextmanager
def protected_session(paths, *, receipt: str):
    """Ordinary-execution equivalent of the pytest plugin: guard, inventory, compare.

    The after-inventory and receipt are written even when the body fails; a
    preservation failure outranks (and chains) the body's own exception.
    """
    from scripts.profile_pilot.paths import write_json
    specs = root_specs(paths)
    before = inventory(specs)
    uninstall = install_open_guard(guarded_roots(paths))
    state: dict = {}
    body_error = None
    try:
        yield state
    except BaseException as exc:
        body_error = exc
        raise
    finally:
        uninstall()
        after = inventory(specs)
        comparison = compare(before, after)
        state.update(summarize(before, after, comparison))
        state["protected_roots"] = [str(r) for r in paths.protected_roots]
        state["read_only_roots"] = [str(r) for r in paths.read_only_roots]
        state["body_error"] = (None if body_error is None else
                               type(body_error).__name__ + ": " + str(body_error))
        write_json(paths, receipt, state)
        if not comparison["ok"]:
            raise PreservationError("protected artifacts changed or uninspectable: created="
                                    + str(len(comparison["created"])) + " changed="
                                    + str(len(comparison["changed"])) + " deleted="
                                    + str(len(comparison["deleted"])) + " errors="
                                    + str(len(comparison["errors_after"]))
                                    + " (see " + receipt + ")")


# ---------------------------------------------------------------- heavy classification (R3)

def _check_workload_types(*, ciks, instance_count, full_cache_scan, pipeline_cik_count,
                          est_seconds, est_bytes) -> None:
    """Fail closed on mistyped workloads: a str ciks would be iterated per character (the
    Ares/BCRED check never fires) and a None/bool count is silently falsy."""
    import numbers
    problems = []
    if not (isinstance(ciks, (list, tuple))
            and all(isinstance(c, str) and c for c in ciks)):
        problems.append("ciks must be a list/tuple of non-empty str, got " + repr(ciks)[:80])
    for name, value in (("instance_count", instance_count), ("pipeline_cik_count", pipeline_cik_count)):
        if isinstance(value, bool) or not isinstance(value, numbers.Integral) or value < 0:
            problems.append(name + " must be a non-negative int, got " + repr(value))
    if not isinstance(full_cache_scan, bool):
        problems.append("full_cache_scan must be bool, got " + repr(full_cache_scan))
    for name, value in (("est_seconds", est_seconds), ("est_bytes", est_bytes)):
        if isinstance(value, bool) or not isinstance(value, numbers.Real) or value != value or value < 0:
            problems.append(name + " must be a non-negative number, got " + repr(value))
    if problems:
        raise ValueError("invalid workload: " + "; ".join(problems))


def requires_lease(*, ciks=(), instance_count=0, full_cache_scan=False, pipeline_cik_count=0,
                   est_seconds=0, est_bytes=0) -> bool:
    """Ruling R3 (amended by R9): True when an operation must hold the shared lease.

    Heavy: parsing any Ares/BCRED instance, parsing more than one instance per call,
    a full raw-cache scan, a staging/unified run over more than the eight pilot CIKs,
    or a parse/staging/census operation estimated above 60 s or 2 GiB.
    Light by enumeration (the estimate does NOT apply): DuckDB reads of pinned
    holdings/index slices for the eight CIKs and file hashing, including the
    freeze command (measured 62.5 s).
    Exempt (R9): the launcher's pytest run and the read-only semantic backstop. They
    are guarded instead by the launcher's process check, which refuses when any
    pytest/rebuild/bootstrap process exists or discovery fails.
    """
    from scripts.profile_pilot.cohort import LARGE_INSTANCE_CIKS
    _check_workload_types(ciks=ciks, instance_count=instance_count, full_cache_scan=full_cache_scan,
                          pipeline_cik_count=pipeline_cik_count, est_seconds=est_seconds,
                          est_bytes=est_bytes)
    if instance_count and any(c in LARGE_INSTANCE_CIKS for c in ciks):
        return True
    return (instance_count > 1 or full_cache_scan or pipeline_cik_count > PIPELINE_CIK_LIMIT
            or est_seconds > HEAVY_ESTIMATE_SECONDS or est_bytes > HEAVY_ESTIMATE_BYTES)


# ---------------------------------------------------------------- shared programme lease

@dataclass(frozen=True)
class LeaseInfo:
    candidate: Path
    lock_path: Path
    acquired_utc: str


_PROCESS_LEASE = threading.Lock()


def assert_lease_held(lease) -> None:
    """Refuse unless `lease` is a live handle: its lock file names this process and candidate."""
    if not isinstance(lease, LeaseInfo):
        raise LeaseRefused("heavy work requires a held shared lease handle; none was given")
    try:
        held = json.loads(Path(lease.lock_path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise LeaseRefused("shared lease is not held: " + type(exc).__name__) from exc
    if held.get("controller_pid") != os.getpid() or held.get("candidate") != str(lease.candidate):
        raise LeaseRefused("shared lease lock does not belong to this process and candidate")


def _normalised(path: Path) -> bytes:
    with open(path, "rb") as stream:
        return stream.read().replace(b"\r\n", b"\n")


def _remove_candidate(candidate: Path) -> None:
    names = sorted(p.name for p in candidate.iterdir())
    if names != ["pilot.json"]:
        raise PreservationError("pseudo-candidate holds unexpected entries; left for inspection: "
                                + str(candidate) + " " + repr(names[:10]))
    (candidate / "pilot.json").unlink()
    candidate.rmdir()


@contextmanager
def shared_heavy_lease(paths, *, head: str):
    """Hold `pipeline.programme.runner.heavy_lock` bound to the MAIN checkout.

    runner.ROOT resolves from the imported module's own file (the worktree here), so
    it is rebound to main_repo_root for the whole lease and restored afterwards. The
    pseudo-candidate holds only pilot.json; it is removed on clean release or refusal
    and left in place when the held work fails.
    """
    if not _PROCESS_LEASE.acquire(blocking=False):
        raise LeaseRefused("the pilot lease is already held in this process")
    try:
        runner = importlib.import_module("pipeline.programme.runner")
        from pipeline.programme.core import ContractError
        main_runner = paths.main_repo_root / "pipeline" / "programme" / "runner.py"
        try:
            # Checkouts differ in line endings (main LF, worktree CRLF; same git blob),
            # so compare content with CRLF normalised, not raw bytes.
            same_protocol = (_normalised(main_runner) == _normalised(Path(runner.__file__)))
        except OSError as exc:
            raise LeaseRefused("cannot inspect the main lease protocol: " + str(exc)) from exc
        if not same_protocol:
            raise LeaseRefused("main pipeline/programme/runner.py differs from the imported "
                               "lease protocol; refusing to bind")
        original_root = runner.ROOT
        runner.ROOT = paths.main_repo_root
        try:
            try:
                candidate = runner.candidate_path(paths.candidate_name)
            except ContractError as exc:
                raise LeaseRefused("pseudo-candidate path rejected: " + str(exc)) from exc
            if candidate.exists():
                raise LeaseRefused("pseudo-candidate already exists (prior failure?); inspect "
                                   + str(candidate))
            candidate.mkdir(parents=True)
            with open(candidate / "pilot.json", "x", encoding="ascii") as stream:
                json.dump(dict(run_id=paths.run_id, pilot_root=str(paths.run_root),
                               git_head=head, pid=os.getpid(), created_utc=_now()),
                          stream, indent=2, sort_keys=True)
            lock = runner.heavy_lock(candidate)
            try:
                lock.__enter__()
            except BaseException as exc:
                _remove_candidate(candidate)
                if isinstance(exc, ContractError):
                    raise LeaseRefused(str(exc)) from exc
                if isinstance(exc, Exception):
                    raise LeaseRefused("lease inspection failed: " + type(exc).__name__ + ": "
                                       + str(exc)) from exc
                raise
            info = LeaseInfo(candidate=candidate,
                             lock_path=paths.main_repo_root / "data" / "programme" / "heavy.lock",
                             acquired_utc=_now())
            try:
                yield info
            except BaseException:
                lock.__exit__(*sys.exc_info())
                raise
            lock.__exit__(None, None, None)
            _remove_candidate(candidate)
        finally:
            runner.ROOT = original_root
    finally:
        _PROCESS_LEASE.release()


def process_conflicts() -> list[dict]:
    """Other python processes that heavy_lock would treat as heavy jobs (launcher check)."""
    import psutil
    found = []
    for process in psutil.process_iter(["pid", "name", "cmdline"]):
        if process.info["pid"] == os.getpid():
            continue
        command = " ".join(process.info.get("cmdline") or [])
        if str(process.info["name"]).lower().startswith("python") and any(
                word in command for word in ("pytest", "rebuild_outputs.py",
                                             "pipeline.programme.bootstrap")):
            found.append(dict(pid=process.info["pid"], command=command[:300]))
    return found


def format_exception(exc: BaseException) -> str:
    return "".join(traceback.format_exception_only(type(exc), exc)).strip()
