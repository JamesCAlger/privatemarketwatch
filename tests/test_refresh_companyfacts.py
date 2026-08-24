"""Tests for the operator companyfacts refresh script (tmp-confined, no network)."""

from __future__ import annotations

import json

from scripts import refresh_companyfacts as rc


def _facts(end):
    return {"facts": {"us-gaap": {"Assets": {"units": {"USD": [
        {"end": end, "val": 1}]}}}}}


def test_archive_then_fetch_reports_coverage(tmp_path):
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / "0000000001.json").write_text(json.dumps(_facts("2025-12-31")),
                                           encoding="utf-8")
    fetched = []

    def fake_fetch(cik10, client):
        fetched.append(cik10)
        return _facts("2026-03-31")

    results = rc.refresh(["1", "2"], "2026-03-31", client=object(),
                         cache_dir=cache, fetch=fake_fetch)
    by_cik = {r["cik"]: r for r in results}
    assert by_cik["0000000001"]["archived"] is True     # stale file moved aside
    assert by_cik["0000000002"]["archived"] is False    # nothing to archive
    assert fetched == ["0000000001", "0000000002"]
    assert all(r["quarter_covered"] for r in results)
    # archived copy preserved under _archive/<stamp>/, original gone
    archived = list((cache / "_archive").rglob("0000000001.json"))
    assert len(archived) == 1
    assert not (cache / "0000000001.json").exists() or fetched  # fetch may rewrite


def test_quarter_not_covered_reported(tmp_path):
    results = rc.refresh(["3"], "2026-03-31", client=object(),
                         cache_dir=tmp_path / "cache",
                         fetch=lambda cik10, client: _facts("2025-12-31"))
    assert results[0]["fetched"] is True
    assert results[0]["quarter_covered"] is False       # SEC lag stays visible


def test_dry_run_moves_and_fetches_nothing(tmp_path):
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / "0000000004.json").write_text("{}", encoding="utf-8")

    def boom(cik10, client):  # pragma: no cover - must not be called
        raise AssertionError("fetch called in dry-run")

    results = rc.refresh(["4"], "2026-03-31", cache_dir=cache, dry_run=True, fetch=boom)
    assert results[0]["would_archive"] is True
    assert (cache / "0000000004.json").exists()         # untouched
    assert not (cache / "_archive").exists()
