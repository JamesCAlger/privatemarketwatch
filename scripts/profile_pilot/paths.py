"""Explicit, validated pilot roots and confinement of every pilot write to the run root.

Nothing here defaults to the importing checkout. The worktree has no data/raw or
data/output, so a silent fallback would read an empty or different dataset.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import stat
import subprocess

RUN_ID_PATTERN = re.compile(r"[a-z0-9][a-z0-9_-]{0,79}")
CANDIDATE_PREFIX = "pilot-filer-profile-"
PILOT_SUBDIR = ("pilot", "filer_profile")
_REPARSE = 0x400


class PathError(ValueError):
    """A pilot path is missing, invalid, aliased or outside the run root."""


def default_run_id(now: datetime | None = None) -> str:
    stamp = (now or datetime.now(timezone.utc)).strftime("%Y%m%dt%H%M%Sz")
    return "stagea-" + stamp


def validate_run_id(run_id) -> str:
    # runner.candidate_path admits only [a-z0-9-_]; the pseudo-candidate embeds the run id.
    if not isinstance(run_id, str) or not RUN_ID_PATTERN.fullmatch(run_id):
        raise PathError("run_id must match [a-z0-9][a-z0-9_-]{0,79}: " + repr(run_id))
    return run_id


def _is_alias(path: Path) -> bool:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return False
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, "st_file_attributes", 0) & _REPARSE)


def _explicit_dir(value, label: str) -> Path:
    if value is None or value == "":
        raise PathError(label + " must be supplied explicitly")
    path = Path(value).absolute()
    if _is_alias(path):
        raise PathError(label + " is a symlink or junction: " + str(path))
    try:
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise PathError(label + " does not exist: " + str(path)) from exc
    if not resolved.is_dir():
        raise PathError(label + " is not a directory: " + str(resolved))
    return resolved


def _require(root: Path, label: str, *relative: str) -> None:
    for item in relative:
        if not (root / item).exists():
            raise PathError(label + " is missing " + item + ": " + str(root))


@dataclass(frozen=True)
class PilotPaths:
    main_repo_root: Path
    code_root: Path
    data_root: Path
    run_id: str

    @property
    def run_root(self) -> Path:
        return self.data_root.joinpath(*PILOT_SUBDIR, self.run_id)

    @property
    def candidate_name(self) -> str:
        return CANDIDATE_PREFIX + self.run_id

    @property
    def output_root(self) -> Path:
        return self.data_root / "output"

    @property
    def cache_root(self) -> Path:
        return self.data_root / "raw" / "filings" / "bdc_xbrl"

    @property
    def protected_roots(self) -> tuple[Path, ...]:
        """Real main roots first, then the data root's output, then worktree equivalents."""
        roots = [self.main_repo_root / "data" / "output",
                 self.main_repo_root / "frontend" / "public" / "data",
                 self.output_root,
                 self.code_root / "data" / "output",
                 self.code_root / "frontend" / "public" / "data"]
        unique = []
        for root in roots:
            root = root.resolve(strict=False)
            if root not in unique:
                unique.append(root)
        return tuple(unique)

    @property
    def read_only_roots(self) -> tuple[Path, ...]:
        """Production inputs the pilot must never change: the code root's data/overrides
        (wrappers, grammars, anchors, corrections). Inventoried before/after like the
        protected roots; any change fails preservation."""
        return (self.code_root.joinpath("data", "overrides").resolve(strict=False),)


def resolve_paths(*, main_repo_root, data_root, code_root, run_id) -> PilotPaths:
    main = _explicit_dir(main_repo_root, "main_repo_root")
    _require(main, "main_repo_root", "pipeline", "data")
    data = _explicit_dir(data_root, "data_root")
    _require(data, "data_root", "raw", "output", "output/bdc_filings_index.csv")
    code = _explicit_dir(code_root, "code_root")
    _require(code, "code_root", "pipeline", "scripts/profile_pilot/__init__.py")
    return PilotPaths(main_repo_root=main, code_root=code, data_root=data,
                      run_id=validate_run_id(run_id))


def discover_main_root(code_root) -> Path:
    """Convenience only: the shared git common dir's parent, validated like any other root."""
    code = _explicit_dir(code_root, "code_root")
    done = subprocess.run(["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
                          cwd=code, capture_output=True, text=True, timeout=60)
    if done.returncode != 0:
        raise PathError("git common dir discovery failed: " + done.stderr.strip())
    main = _explicit_dir(Path(done.stdout.strip()).parent, "main_repo_root")
    _require(main, "main_repo_root", "pipeline", "data")
    return main


def confined(paths: PilotPaths, relative: str) -> Path:
    """Resolve `relative` under the run root; reject escapes, junctions and symlinks."""
    from pipeline.programme.core import ContractError, contained
    try:
        return contained(paths.run_root, relative, existing=False)
    except ContractError as exc:
        raise PathError(str(exc)) from exc


def _prepare(paths: PilotPaths, relative: str) -> Path:
    target = confined(paths, relative)
    target.parent.mkdir(parents=True, exist_ok=True)
    return confined(paths, relative)  # re-check after creating parents


def _dump(value) -> str:
    return json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True, allow_nan=False) + "\n"


def write_json(paths: PilotPaths, relative: str, value) -> Path:
    target = _prepare(paths, relative)
    pending = target.with_name(target.name + ".pending-" + str(os.getpid()))
    with open(pending, "x", encoding="ascii", newline="\n") as stream:
        stream.write(_dump(value))
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(pending, target)
    return target


TMP_SUBDIR = "tmp"


def pilot_temp_dir(paths: PilotPaths) -> Path:
    """<run_root>/tmp, created and re-confined: the only place pilot spill files may land."""
    return _prepare(paths, TMP_SUBDIR + "/.keep").parent


def pilot_duckdb(paths: PilotPaths, *, threads: int = 2, memory_limit: str | None = "2GB"):
    """The one DuckDB factory for pilot code: spill (temp_directory) stays under the run root.

    An in-memory DuckDB connection otherwise spills to ./.tmp in the current working
    directory, which is outside the run root.
    """
    import duckdb
    config = {"threads": threads, "temp_directory": str(pilot_temp_dir(paths))}
    if memory_limit is not None:
        config["memory_limit"] = memory_limit
    return duckdb.connect(config=config)


@contextmanager
def pilot_cwd(paths: PilotPaths):
    """Run a block (e.g. production staging that opens its own DuckDB) with cwd = run root.

    Production code is not edited; its default ./.tmp spill then lands under the run
    root. The previous cwd is restored in `finally`.
    """
    _prepare(paths, TMP_SUBDIR + "/.keep")
    previous = os.getcwd()
    os.chdir(paths.run_root)
    try:
        yield paths.run_root
    finally:
        os.chdir(previous)


def write_once_json(paths: PilotPaths, relative: str, value) -> Path:
    target = _prepare(paths, relative)
    try:
        with open(target, "x", encoding="ascii", newline="\n") as stream:
            stream.write(_dump(value))
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError as exc:
        raise PathError("refusing to overwrite frozen file: " + str(target)) from exc
    return target
