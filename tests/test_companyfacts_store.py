"""Companyfacts snapshot store and pins (tmp-confined, no network)."""
from __future__ import annotations

import json
import logging
import os
import stat

import pytest

from pipeline import companyfacts_store as store
from pipeline import config

CIK = "0000000123"


def _facts(val=100, end="2026-03-31", extra=None, cik=123):
    rows = [{"end": end, "val": val, "form": "10-Q", "fy": 2026, "fp": "Q1", "accn": "a1"}]
    doc = {"cik": cik, "entityName": "Test BDC",
           "facts": {"us-gaap": {"Assets": {"units": {"USD": rows}}}}}
    if extra:
        doc["facts"]["us-gaap"].update(extra)
    return doc


def _bytes(doc):
    return json.dumps(doc).encode("utf-8")


@pytest.fixture
def env(tmp_path, monkeypatch):
    legacy = tmp_path / "companyfacts_cache"
    legacy.mkdir()
    snaps = tmp_path / "companyfacts_snapshots"
    published = tmp_path / "reference" / "companyfacts_pins" / "published.json"
    monkeypatch.setattr(config, "COMPANYFACTS_CACHE_DIR", legacy)
    monkeypatch.setattr(config, "COMPANYFACTS_SNAPSHOT_DIR", snaps)
    monkeypatch.setattr(config, "COMPANYFACTS_PUBLISHED_PIN_FILE", published)
    monkeypatch.setattr(config, "COMPANYFACTS_PIN_FILE", published)
    monkeypatch.setattr(store, "_LEGACY_DEFAULT", legacy.resolve())
    monkeypatch.setattr(store, "_warned_legacy", False)
    monkeypatch.delenv(store.PIN_ENV, raising=False)
    store._pin_cache.clear()
    return dict(legacy=legacy, snaps=snaps, published=published, tmp=tmp_path)


def test_content_addressing_stores_identical_bytes_once(env):
    row1, created1 = store.add_snapshot(CIK, _bytes(_facts()), source="live_cache_import",
                                        retrieved_at="2026-05-01T00:00:00Z")
    row2, created2 = store.add_snapshot(CIK, _bytes(_facts()), source="api_download",
                                        retrieved_at="2026-11-01T00:00:00Z")
    assert created1 and not created2
    assert row2 == row1
    assert len(store.read_manifest()) == 1
    assert len(list((env["snaps"] / CIK).glob("*.json"))) == 1
    assert row1["path"].startswith(CIK + "/20260501T000000Z_" + row1["sha256"][:12])
    assert row1["max_fact_end"] == "2026-03-31" and row1["fact_count"] == 1
    # a different version is a second snapshot; the file is read-only
    row3, created3 = store.add_snapshot(CIK, _bytes(_facts(200)), source="api_download",
                                        retrieved_at="2026-11-01T00:00:00Z")
    assert created3 and row3["sha256"] != row1["sha256"]
    assert len(store.snapshots_for(CIK)) == 2
    assert not os.stat(env["snaps"] / row3["path"]).st_mode & stat.S_IWRITE


def test_snapshot_rejects_content_of_another_cik(env):
    with pytest.raises(store.CompanyfactsStoreError):
        store.add_snapshot(CIK, _bytes(_facts(cik=999)), source="api_download")


def test_pin_resolution_and_missing_cik_is_none(env):
    row, _ = store.add_snapshot(CIK, _bytes(_facts()), source="live_cache_import")
    # a legacy file with other content must be ignored once a pin exists
    (env["legacy"] / (CIK + ".json")).write_text(json.dumps(_facts(999)), encoding="utf-8")
    (env["legacy"] / "0000000456.json").write_text(json.dumps(_facts(cik=456)), encoding="utf-8")
    store.write_pin(env["published"], {CIK: row["path"]}, promoted_by="test", allow_published=True)
    assert store.companyfacts_path(CIK) == env["snaps"] / row["path"]
    assert store.companyfacts_path(123) == env["snaps"] / row["path"]
    assert store.load_companyfacts(CIK)["facts"]["us-gaap"]["Assets"]["units"]["USD"][0]["val"] == 100
    assert store.companyfacts_path("0000000456") is None          # not pinned -> None, no fallback
    assert store.load_companyfacts("0000000456") == {}
    # default legacy dir passed explicitly still resolves through the pin
    assert store.companyfacts_path(CIK, env["legacy"]) == env["snaps"] / row["path"]


def test_explicit_other_directory_reads_directly(env, tmp_path):
    row, _ = store.add_snapshot(CIK, _bytes(_facts()), source="live_cache_import")
    store.write_pin(env["published"], {CIK: row["path"]}, promoted_by="test", allow_published=True)
    other = tmp_path / "fixture_dir"
    other.mkdir()
    (other / (CIK + ".json")).write_text("{}", encoding="utf-8")
    assert store.companyfacts_path(CIK, other) == other / (CIK + ".json")
    assert store.companyfacts_path("0000000777", other) is None


def test_env_pin_override(env, monkeypatch):
    a, _ = store.add_snapshot(CIK, _bytes(_facts(1)), source="live_cache_import",
                              retrieved_at="2026-01-01T00:00:00Z")
    b, _ = store.add_snapshot(CIK, _bytes(_facts(2)), source="api_download",
                              retrieved_at="2026-08-01T00:00:00Z")
    store.write_pin(env["published"], {CIK: a["path"]}, promoted_by="test", allow_published=True)
    candidate = env["tmp"] / "candidate.json"
    store.write_candidate_pin(candidate, {CIK: b["path"]}, promoted_by="test")
    assert store.companyfacts_path(CIK) == env["snaps"] / a["path"]
    monkeypatch.setenv(store.PIN_ENV, str(candidate))
    assert store.companyfacts_path(CIK) == env["snaps"] / b["path"]
    assert store.pin_digest() == store.sha256_file(candidate)
    assert store.pin_digest() != store.sha256_file(env["published"])
    # an env pin that does not exist is an error, never a silent fallback
    monkeypatch.setenv(store.PIN_ENV, str(env["tmp"] / "missing.json"))
    with pytest.raises(store.CompanyfactsStoreError):
        store.companyfacts_path(CIK)


def test_legacy_fallback_only_without_pin_file(env, caplog):
    (env["legacy"] / (CIK + ".json")).write_text(json.dumps(_facts(7)), encoding="utf-8")
    with caplog.at_level(logging.WARNING, logger="pipeline.companyfacts_store"):
        assert store.companyfacts_path(CIK) == env["legacy"] / (CIK + ".json")
        assert store.companyfacts_path("0000000456") is None
    assert sum("legacy directory" in r.getMessage() for r in caplog.records) == 1   # once per process
    assert store.pin_digest() is None
    # once a pin file exists the legacy file is no longer read
    row, _ = store.add_snapshot("0000000456", _bytes(_facts(cik=456)), source="api_download")
    store.write_pin(env["published"], {"0000000456": row["path"]}, promoted_by="test", allow_published=True)
    assert store.companyfacts_path(CIK) is None


def test_missing_pinned_snapshot_raises(env):
    row, _ = store.add_snapshot(CIK, _bytes(_facts()), source="live_cache_import")
    store.write_pin(env["published"], {CIK: row["path"]}, promoted_by="test", allow_published=True)
    path = env["snaps"] / row["path"]
    os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
    path.unlink()
    with pytest.raises(store.CompanyfactsStoreError):
        store.companyfacts_path(CIK)


def test_published_pin_write_guard(env):
    row, _ = store.add_snapshot(CIK, _bytes(_facts()), source="live_cache_import")
    with pytest.raises(store.CompanyfactsStoreError):
        store.write_pin(env["published"], {CIK: row["path"]}, promoted_by="test")
    with pytest.raises(store.CompanyfactsStoreError):
        store.write_candidate_pin(env["published"], {CIK: row["path"]}, promoted_by="test")
    assert not env["published"].exists()
    # a pin may not point outside its CIK folder or at a missing snapshot
    with pytest.raises(store.CompanyfactsStoreError):
        store.write_pin(env["tmp"] / "c.json", {"0000000456": row["path"]}, promoted_by="test")
    with pytest.raises(store.CompanyfactsStoreError):
        store.write_pin(env["tmp"] / "c.json", {CIK: CIK + "/nope.json"}, promoted_by="test")
    store.write_pin(env["published"], {CIK: row["path"]}, promoted_by="owner", note="n",
                    allow_published=True)
    doc = json.loads(env["published"].read_text(encoding="utf-8"))
    assert doc["promoted_by"] == "owner" and doc["note"] == "n" and doc["promoted_at"].endswith("Z")


def test_cli_pin_refuses_published_without_flags(env):
    from scripts import companyfacts_snapshots as cli
    row, _ = store.add_snapshot(CIK, _bytes(_facts()), source="live_cache_import")
    assert cli.main(["pin", "--file", str(env["published"]), "--cik", CIK, "--latest"]) == 2
    assert cli.main(["pin", "--published", "--cik", CIK, "--latest"]) == 2
    assert not env["published"].exists()
    assert cli.main(["pin", "--published", "--yes", "--cik", CIK, "--latest", "--note", "promote"]) == 0
    assert json.loads(env["published"].read_text(encoding="utf-8"))["pins"] == {CIK: row["path"]}


def test_diff_detects_restated_added_removed(env):
    old = _facts(100, extra={"Liabilities": {"units": {"USD": [
        {"end": "2025-12-31", "val": 5, "form": "10-K", "fy": 2025, "fp": "FY"}]}}})
    new = _facts(110, extra={"Cash": {"units": {"USD": [
        {"end": "2026-03-31", "val": 9, "form": "10-Q", "fy": 2026, "fp": "Q1"}]}}})
    result = store.diff_facts(old, new)
    assert result["summary"]["restated"] == 1
    assert result["restated"][0]["concept"] == "Assets"
    assert result["restated"][0]["values_a"] == [100] and result["restated"][0]["values_b"] == [110]
    assert result["summary"]["added"] == 1 and result["added"][0]["concept"] == "Cash"
    assert result["summary"]["removed"] == 1 and result["removed"][0]["concept"] == "Liabilities"
    assert store.diff_facts(old, old)["summary"]["restated"] == 0


def test_verify_catches_tampered_snapshot(env):
    row, _ = store.add_snapshot(CIK, _bytes(_facts()), source="live_cache_import")
    store.write_pin(env["published"], {CIK: row["path"]}, promoted_by="test", allow_published=True)
    assert store.verify() == []
    path = env["snaps"] / row["path"]
    os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
    path.write_bytes(_bytes(_facts(666)))
    problems = store.verify()
    assert len(problems) == 1 and "sha256 differs" in problems[0]


def test_cli_import_pins_live_versions_byte_identical(env, monkeypatch):
    from scripts import companyfacts_snapshots as cli
    downloads = env["tmp"] / "quarter_downloads"
    (downloads / "before").mkdir(parents=True)
    monkeypatch.setattr(cli, "QUARTER_DOWNLOADS", downloads)
    (downloads / "before" / (CIK + ".json")).write_bytes(_bytes(_facts(1, end="2025-12-31")))
    (downloads / (CIK + ".json")).write_bytes(_bytes(_facts(2)))
    (env["legacy"] / (CIK + ".json")).write_bytes(_bytes(_facts(2)))           # live = Q2 download
    (env["legacy"] / "0000000456.json").write_bytes(_bytes(_facts(3, cik=456)))
    assert cli.main(["import"]) == 0
    rows = store.read_manifest()
    assert sorted(r["source"] for r in rows) == ["live_cache_import", "quarter_backup_import",
                                                 "quarter_download_import"]
    pins = store.load_pin(env["published"])["pins"]
    for cik in (CIK, "0000000456"):
        assert store.sha256_file(env["snaps"] / pins[cik]) == store.sha256_file(env["legacy"] / (cik + ".json"))
    assert cli.main(["import"]) == 0                       # idempotent: nothing new, same pin
    assert len(store.read_manifest()) == 3
    assert cli.main(["verify", "--all", "--against-legacy"]) == 0


def test_extract_reader_uses_pin_not_legacy_file(env):
    from pipeline.extract_companyfacts import _load_companyfacts_cached
    row, _ = store.add_snapshot(CIK, _bytes(_facts(100)), source="live_cache_import")
    store.write_pin(env["published"], {CIK: row["path"]}, promoted_by="test", allow_published=True)
    (env["legacy"] / (CIK + ".json")).write_text(json.dumps(_facts(999)), encoding="utf-8")
    facts = _load_companyfacts_cached("123", config.COMPANYFACTS_CACHE_DIR)
    assert facts["facts"]["us-gaap"]["Assets"]["units"]["USD"][0]["val"] == 100
