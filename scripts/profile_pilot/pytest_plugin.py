"""Pytest protection plugin for the pilot. Load with `-p scripts.profile_pilot.pytest_plugin`.

tests/conftest.py protects only the importing checkout's data/output and
frontend/public/data; in the pilot worktree both are empty. This plugin:

* installs a write guard for the REAL main roots (taken from environment variables
  set by the launcher) at import time, i.e. before collection imports pipeline code;
* extends the shared conftest guard (its `_is_protected_path`) with the same roots,
  leaving conftest's own PROTECTED_OUTPUT_ROOTS untouched;
* inventories the protected roots at session start and again at session finish,
  which runs even when tests fail, and fails the session (exit 3) on any change or
  inspection error. The receipt goes to PROFILE_PILOT_RECEIPT.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from scripts.profile_pilot import protection
from scripts.profile_pilot.paths import PathError, resolve_paths

ENV_MAIN = "PROFILE_PILOT_MAIN_ROOT"
ENV_DATA = "PROFILE_PILOT_DATA_ROOT"
ENV_CODE = "PROFILE_PILOT_CODE_ROOT"
ENV_RECEIPT = "PROFILE_PILOT_RECEIPT"
CODE_ROOT = Path(__file__).resolve().parents[2]


def _resolve():
    main, data = os.environ.get(ENV_MAIN), os.environ.get(ENV_DATA)
    if not main or not data:
        return None, ENV_MAIN + " and " + ENV_DATA + " must be set (use the pilot launcher)"
    try:
        paths = resolve_paths(main_repo_root=main, data_root=data,
                              code_root=os.environ.get(ENV_CODE) or CODE_ROOT, run_id="plugin")
    except PathError as exc:
        return None, "invalid pilot roots: " + str(exc)
    return paths, None


_PATHS, _PROBLEM = _resolve()
_STATE: dict = dict(guard_installed_at_import=False, conftest_guard_extended=False)
if _PATHS is not None:
    protection.install_open_guard(_PATHS.protected_roots)
    _STATE["guard_installed_at_import"] = True


def pytest_configure(config):
    if _PATHS is None:
        raise pytest.UsageError("profile pilot plugin: " + str(_PROBLEM))
    receipt = os.environ.get(ENV_RECEIPT)
    if not receipt:
        raise pytest.UsageError("profile pilot plugin: " + ENV_RECEIPT + " must be set")
    if protection.is_under(receipt, _PATHS.protected_roots):
        raise pytest.UsageError("profile pilot plugin: receipt path is inside a protected root")


def _extend_conftest_guard(config) -> bool:
    roots = _PATHS.protected_roots
    extended = False
    for plugin in config.pluginmanager.get_plugins():
        original = getattr(plugin, "_is_protected_path", None)
        if not hasattr(plugin, "PROTECTED_OUTPUT_ROOTS") or original is None:
            continue
        if getattr(original, "profile_pilot_extended", False):
            extended = True
            continue

        def combined(path, _original=original):
            return _original(path) or protection.is_under(path, roots)

        combined.profile_pilot_extended = True
        plugin._is_protected_path = combined
        _STATE["conftest_roots_unchanged"] = [str(r) for r in plugin.PROTECTED_OUTPUT_ROOTS]
        extended = True
    return extended


@pytest.hookimpl(tryfirst=True)
def pytest_sessionstart(session):
    _STATE["conftest_guard_extended"] = _extend_conftest_guard(session.config)
    _STATE["specs"] = protection.root_specs(_PATHS)
    _STATE["before"] = protection.inventory(_STATE["specs"])


@pytest.hookimpl(trylast=True)
def pytest_sessionfinish(session, exitstatus):
    before = _STATE.get("before")
    if before is None:  # session start never ran; nothing trustworthy to compare
        after = protection.inventory(protection.root_specs(_PATHS))
        comparison = dict(ok=False, created=[], deleted=[], changed=[],
                          errors_before=["no session-start inventory"], errors_after=after["errors"])
        body = protection.summarize(after, after, comparison)
    else:
        after = protection.inventory(_STATE["specs"])
        comparison = protection.compare(before, after)
        body = protection.summarize(before, after, comparison)
    body.update(protected_roots=[str(r) for r in _PATHS.protected_roots],
                guard_installed_at_import=_STATE["guard_installed_at_import"],
                conftest_guard_extended=_STATE["conftest_guard_extended"],
                conftest_roots_unchanged=_STATE.get("conftest_roots_unchanged"),
                test_exitstatus=int(exitstatus))
    receipt = Path(os.environ[ENV_RECEIPT])
    receipt.parent.mkdir(parents=True, exist_ok=True)
    with open(receipt, "w", encoding="ascii") as stream:
        json.dump(body, stream, indent=2, sort_keys=True)
    if not comparison["ok"]:
        reporter = session.config.pluginmanager.get_plugin("terminalreporter")
        if reporter is not None:
            reporter.write_sep("=", "profile pilot protection FAILED", red=True)
            for label in ("created", "changed", "deleted", "errors_before", "errors_after"):
                for item in comparison[label][:20]:
                    reporter.write_line("  " + label + ": " + item)
        session.exitstatus = 3
