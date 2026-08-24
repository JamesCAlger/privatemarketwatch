"""Tests for the B2 cross-batch metrics extractor (tmp-confined I/O)."""

from __future__ import annotations

import json

from scripts import b2_run_metrics as m


def _metric(rows, name):
    hits = [r for r in rows if r["metric"] == name]
    assert len(hits) == 1, f"{name}: {len(hits)} hits"
    return hits[0]


def _manifest(batch_id, rows, *, wave=None, skipped_stale=()):
    d = {
        "batch_id": batch_id,
        "created_at": "2026-08-21T00:00:00+00:00",
        "n_dispatch": len(rows),
        "skipped_no_citations": [],
        "skipped_policy": [],
        "skipped_stale": list(skipped_stale),
        "skipped_existing": [],
        "rows": rows,
    }
    if wave is not None:
        d["wave"] = wave
    return d


def test_aggregates_across_wave_manifests_without_double_count(tmp_path):
    batch_dir = tmp_path / "batch" / "B2W"
    batch_dir.mkdir(parents=True)
    w1 = _manifest("B2W", [{"cik": "1"}, {"cik": "2"}, {"cik": "3"}], wave=1,
                   skipped_stale=[{"cik": "9", "reason": "fixed upstream"}])
    w2 = _manifest("B2W", [{"cik": "4"}, {"cik": "5"}], wave=2)
    (batch_dir / "manifest.001.json").write_text(json.dumps(w1), encoding="utf-8")
    (batch_dir / "manifest.002.json").write_text(json.dumps(w2), encoding="utf-8")
    # latest pointer duplicates wave 2 and must NOT be double-counted
    (batch_dir / "manifest.json").write_text(json.dumps(w2), encoding="utf-8")

    rows = m.rows_for_batch(batch_dir, "B2W")
    assert _metric(rows, "manifest_total_waves")["value"] == 2
    assert _metric(rows, "manifest_total_rows")["value"] == 5
    assert _metric(rows, "manifest_last_wave_rows")["value"] == 2
    assert _metric(rows, "skipped_stale")["value"] == 1
    per_wave = [r for r in rows if r["metric"] == "manifest_wave_rows"]
    assert [r["value"] for r in per_wave] == [3, 2]
    assert per_wave[0]["detail"] == "wave 1"


def test_legacy_single_manifest_still_read(tmp_path):
    batch_dir = tmp_path / "batch" / "OLD"
    batch_dir.mkdir(parents=True)
    legacy = _manifest("OLD", [{"cik": "1"}, {"cik": "2"}, {"cik": "3"}, {"cik": "4"}])
    (batch_dir / "manifest.json").write_text(json.dumps(legacy), encoding="utf-8")

    rows = m.rows_for_batch(batch_dir, "OLD")
    assert _metric(rows, "manifest_total_waves")["value"] == 1
    assert _metric(rows, "manifest_total_rows")["value"] == 4
    assert _metric(rows, "manifest_last_wave_rows")["value"] == 4
    assert "last wave only" in _metric(rows, "manifest_total_rows")["detail"]
    assert not [r for r in rows if r["metric"] == "manifest_wave_rows"]


def test_missing_manifest_flagged(tmp_path):
    batch_dir = tmp_path / "batch" / "EMPTY"
    batch_dir.mkdir(parents=True)
    rows = m.rows_for_batch(batch_dir, "EMPTY")
    assert _metric(rows, "manifest_missing")["value"] == 1
