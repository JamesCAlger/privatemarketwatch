"""Tests for the operator companyfacts refresh script (tmp-confined, no network).

Since 2026-11-10 a refresh stores a new immutable snapshot and never moves the
published pin; it no longer archives or rewrites the legacy cache file."""

from __future__ import annotations

import json

import pytest

from pipeline import companyfacts_store as store
from pipeline import config
from scripts import refresh_companyfacts as rc


def _facts(end, cik):
    return {"cik": cik, "facts": {"us-gaap": {"Assets": {"units": {"USD": [
        {"end": end, "val": 1}]}}}}}


@pytest.fixture
def env(tmp_path, monkeypatch):
    legacy = tmp_path / "companyfacts_cache"
    legacy.mkdir()
    published = tmp_path / "pins" / "published.json"
    monkeypatch.setattr(config, "COMPANYFACTS_CACHE_DIR", legacy)
    monkeypatch.setattr(config, "COMPANYFACTS_SNAPSHOT_DIR", tmp_path / "snapshots")
    monkeypatch.setattr(config, "COMPANYFACTS_PUBLISHED_PIN_FILE", published)
    monkeypatch.setattr(config, "COMPANYFACTS_PIN_FILE", published)
    monkeypatch.setattr(store, "_LEGACY_DEFAULT", legacy.resolve())
    monkeypatch.delenv(store.PIN_ENV, raising=False)
    store._pin_cache.clear()
    row, _ = store.add_snapshot("1", json.dumps(_facts("2025-12-31", 1)).encode(), source="live_cache_import",
                                retrieved_at="2026-01-01T00:00:00Z")
    store.write_pin(published, {"1": row["path"]}, promoted_by="test", allow_published=True)
    return dict(published=published, legacy=legacy, pinned=row["path"], tmp=tmp_path)


def test_fetch_stores_snapshot_and_leaves_published_pin(env):
    before = env["published"].read_bytes()
    fetched = []

    def fake_fetch(cik10, client):
        fetched.append(cik10)
        return _facts("2026-03-31", int(cik10))

    results = rc.refresh(["1", "2"], "2026-03-31", client=object(), fetch=fake_fetch)
    by_cik = {r["cik"]: r for r in results}
    assert fetched == ["0000000001", "0000000002"]
    assert all(r["quarter_covered"] for r in results)
    assert by_cik["0000000001"]["pinned_quarter_covered"] is False     # pinned version lags
    assert by_cik["0000000002"]["pinned_quarter_covered"] is None      # never pinned
    assert all(r["new_snapshot"] and r["snapshot"] for r in results)
    assert env["published"].read_bytes() == before                     # pin not moved
    assert store.companyfacts_path("1") == store.snapshot_root() / env["pinned"]
    assert store.companyfacts_path("2") is None
    assert not list(env["legacy"].iterdir())                           # legacy cache untouched


def test_candidate_pin_repins_only_fetched_ciks(env):
    candidate = env["tmp"] / "candidate.json"
    results = rc.refresh(["1"], "2026-03-31", client=object(), candidate_pin=candidate,
                         fetch=lambda cik10, client: _facts("2026-03-31", 1))
    pins = json.loads(candidate.read_text(encoding="utf-8"))["pins"]
    assert pins == {"0000000001": results[0]["snapshot"]}
    assert results[0]["snapshot"] != env["pinned"]
    with pytest.raises(store.CompanyfactsStoreError):                # never the published pin
        rc.refresh(["1"], "2026-03-31", client=object(), candidate_pin=env["published"],
                   fetch=lambda cik10, client: _facts("2026-06-30", 1))


def test_quarter_not_covered_reported(env):
    results = rc.refresh(["3"], "2026-03-31", client=object(),
                         fetch=lambda cik10, client: _facts("2025-12-31", 3))
    assert results[0]["fetched"] is True
    assert results[0]["quarter_covered"] is False       # SEC lag stays visible


def test_dry_run_fetches_and_writes_nothing(env):
    def boom(cik10, client):  # pragma: no cover - must not be called
        raise AssertionError("fetch called in dry-run")

    n = len(store.read_manifest())
    results = rc.refresh(["1"], "2026-03-31", dry_run=True, fetch=boom)
    assert results[0]["dry_run"] is True
    assert len(store.read_manifest()) == n
