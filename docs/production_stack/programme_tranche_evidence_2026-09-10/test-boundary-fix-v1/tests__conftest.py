"""Pytest safeguards for production output artifacts."""

from __future__ import annotations

import builtins
import io
import os
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parent.parent
PROTECTED_OUTPUT_ROOTS = (
    (PROJECT_ROOT / "data" / "output").resolve(strict=False),
    (PROJECT_ROOT / "frontend" / "public" / "data").resolve(strict=False),
)
_WRITE_MODE_CHARS = frozenset("wax+")

_ORIGINAL_BUILTINS_OPEN = builtins.open
_ORIGINAL_IO_OPEN = io.open


def _is_protected_path(path: Path) -> bool:
    resolved = path.resolve(strict=False)
    return any(resolved == root or resolved.is_relative_to(root) for root in PROTECTED_OUTPUT_ROOTS)


def _should_block_open(file: Any, mode: str) -> tuple[bool, Path | None]:
    if not isinstance(file, (str, bytes, os.PathLike)):
        return False, None
    if not any(char in mode for char in _WRITE_MODE_CHARS):
        return False, None

    path = Path(file)
    if _is_protected_path(path):
        return True, path.resolve(strict=False)
    return False, None


def _guarded_open(file: Any, mode: str = "r", *args: Any, **kwargs: Any) -> Any:
    block, protected_path = _should_block_open(file, mode)
    if block:
        raise AssertionError(f"pytest attempted to write protected output path: {protected_path} (mode={mode!r})")
    return _ORIGINAL_BUILTINS_OPEN(file, mode, *args, **kwargs)


def _guarded_io_open(file: Any, mode: str = "r", *args: Any, **kwargs: Any) -> Any:
    block, protected_path = _should_block_open(file, mode)
    if block:
        raise AssertionError(f"pytest attempted to write protected output path: {protected_path} (mode={mode!r})")
    return _ORIGINAL_IO_OPEN(file, mode, *args, **kwargs)


builtins.open = _guarded_open
io.open = _guarded_io_open


import pytest


# Tests never call the real OpenAI API (clients are mocked), but some construct
# a client, which raises at init when no key is set. Local runs get the real key
# from .env; cacheless environments (CI, fresh clones) get this dummy.
os.environ.setdefault("OPENAI_API_KEY", "ci-dummy-key-tests-mock-all-calls")

_CACHE_PRESENT = (PROJECT_ROOT / "data" / "raw").is_dir()


def pytest_collection_modifyitems(config, items):
    """Skip needs_cache tests when the local data cache is absent.

    CI runners and fresh clones have only tracked files, so data/raw does not
    exist there. CI additionally deselects via -m "not needs_cache"; this hook
    is the fallback so a bare `pytest` on a cacheless checkout skips instead
    of erroring.
    """
    if _CACHE_PRESENT:
        return
    skip_marker = pytest.mark.skip(reason="local data/ cache not available (needs_cache)")
    for item in items:
        if item.get_closest_marker("needs_cache"):
            item.add_marker(skip_marker)


@pytest.fixture(autouse=True)
def _isolate_gics_label_cache(monkeypatch, tmp_path):
    """Point the GICS label cache at a per-test path.

    gics_mapping reads/creates data/output/gics_label_cache.csv via a
    module-level binding; on a cacheless checkout the create hits the
    production-write guard. Tests that patch the path themselves simply
    re-patch over this. No test depends on real cache contents (verified via
    cacheless worktree run 2026-09-02).
    """
    monkeypatch.setattr("pipeline.gics_mapping.GICS_LABEL_CACHE_FILE",
                        tmp_path / "gics_label_cache.csv", raising=True)


# ---------------------------------------------------------------------------
# Native-IO write backstop.
#
# The open() guard above cannot see writes made through native (C++) IO —
# DuckDB COPY TO and pyarrow bypass builtins.open entirely. Since the phase-1
# Parquet companions introduced DuckDB writers into the pipeline, this
# session-level check is the enforcement backstop: snapshot (mtime_ns, size)
# for every file under the protected roots at session start, re-walk at
# session end, and fail the run loudly on any created/changed/deleted path.
# ---------------------------------------------------------------------------

_FS_MANIFEST: dict[str, tuple[int, int]] = {}


def _walk_protected() -> dict[str, tuple[int, int]]:
    manifest: dict[str, tuple[int, int]] = {}
    for root in PROTECTED_OUTPUT_ROOTS:
        if not root.is_dir():
            continue
        for dirpath, _dirnames, filenames in os.walk(root):
            for fn in filenames:
                p = Path(dirpath) / fn
                try:
                    st = p.stat()
                except OSError:
                    # ACL-denied leftovers (e.g. sandboxed scratch); the open()
                    # guard still covers them, and unreadable-both-walks means
                    # unchanged-for-our-purposes.
                    continue
                manifest[str(p)] = (st.st_mtime_ns, st.st_size)
    return manifest


def pytest_sessionstart(session):
    _FS_MANIFEST.update(_walk_protected())


def pytest_sessionfinish(session, exitstatus):
    after = _walk_protected()
    created = sorted(set(after) - set(_FS_MANIFEST))
    deleted = sorted(set(_FS_MANIFEST) - set(after))
    changed = sorted(
        p for p in set(after) & set(_FS_MANIFEST) if after[p] != _FS_MANIFEST[p]
    )
    if created or deleted or changed:
        tr = session.config.pluginmanager.get_plugin("terminalreporter")
        lines = ["PRODUCTION OUTPUT MODIFIED DURING PYTEST (native-IO backstop):"]
        for label, paths in (("created", created), ("deleted", deleted), ("changed", changed)):
            for p in paths[:20]:
                lines.append(f"  {label}: {p}")
            if len(paths) > 20:
                lines.append(f"  ... and {len(paths) - 20} more {label}")
        message = "\n".join(lines)
        if tr is not None:
            tr.write_sep("=", "protected-output backstop FAILED", red=True)
            tr.write_line(message)
        session.exitstatus = 3


@pytest.fixture(autouse=True)
def _isolate_promoted_agent_stores(request, monkeypatch, tmp_path):
    """Point the promoted agent-fix stores (gap 1) at empty per-test dirs.

    build_unified_holdings consumes data/overrides/agent_investigate_rules and
    data/overrides/agent_b2_corrections by default; without this, promoted
    production fixes would silently apply inside fixtures that use real CIKs.
    Tests that exercise the loaders pass an explicit directory, which bypasses
    the config lookup. Opt out with @pytest.mark.use_real_promoted_stores.
    """
    if request.node.get_closest_marker("use_real_promoted_stores"):
        yield
        return
    from pipeline import config as _config
    monkeypatch.setattr(_config, "AGENT_INVESTIGATE_RULES_DIR",
                        tmp_path / "_promoted_agent_rules", raising=True)
    monkeypatch.setattr(_config, "AGENT_B2_CORRECTIONS_DIR",
                        tmp_path / "_promoted_b2_corrections", raising=True)
    monkeypatch.setattr(_config, "AGENT_ANCHOR_OVERRIDES_DIR",
                        tmp_path / "_promoted_anchor_overrides", raising=True)
    yield
