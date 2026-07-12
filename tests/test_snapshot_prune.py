"""Tests for pre-run snapshot retention (pipeline.main._prune_pre_run_snapshots)."""

import logging

import pytest

from pipeline.main import _PRE_RUN_SNAPSHOTS_KEEP, _prune_pre_run_snapshots

logger = logging.getLogger(__name__)


def _make_snapshot(root, name):
    d = root / name
    d.mkdir()
    (d / "unified_holdings.csv").write_text("cik,fv\n1,100\n")
    return d


def test_prune_keeps_newest_n(tmp_path):
    names = [f"pre_run_2026-06-{day:02d}_000000" for day in range(1, 6)]
    for name in names:
        _make_snapshot(tmp_path, name)

    _prune_pre_run_snapshots(tmp_path, logger, keep=3)

    remaining = sorted(p.name for p in tmp_path.iterdir())
    assert remaining == names[-3:]


def test_prune_ignores_named_snapshots(tmp_path):
    _make_snapshot(tmp_path, "baseline")
    _make_snapshot(tmp_path, "pre_2026_05_27_refresh")
    for day in range(1, 6):
        _make_snapshot(tmp_path, f"pre_run_2026-06-{day:02d}_000000")

    _prune_pre_run_snapshots(tmp_path, logger, keep=1)

    remaining = sorted(p.name for p in tmp_path.iterdir())
    assert remaining == [
        "baseline",
        "pre_2026_05_27_refresh",
        "pre_run_2026-06-05_000000",
    ]


def test_prune_noop_when_at_or_under_cap(tmp_path):
    for day in range(1, 3):
        _make_snapshot(tmp_path, f"pre_run_2026-06-{day:02d}_000000")

    _prune_pre_run_snapshots(tmp_path, logger, keep=3)

    assert len(list(tmp_path.iterdir())) == 2


def test_prune_ignores_files_matching_pattern(tmp_path):
    (tmp_path / "pre_run_2026-06-01_000000").write_text("not a dir")
    for day in range(2, 7):
        _make_snapshot(tmp_path, f"pre_run_2026-06-{day:02d}_000000")

    _prune_pre_run_snapshots(tmp_path, logger, keep=2)

    assert (tmp_path / "pre_run_2026-06-01_000000").is_file()
    dirs = sorted(p.name for p in tmp_path.iterdir() if p.is_dir())
    assert dirs == ["pre_run_2026-06-05_000000", "pre_run_2026-06-06_000000"]


def test_default_keep_is_three():
    assert _PRE_RUN_SNAPSHOTS_KEEP == 3
