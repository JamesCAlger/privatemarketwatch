import csv
import json

import pytest

import scripts.agent_a.cik_lock as lk
import scripts.agent_a.dispatch_preflight as dp


def _write_worklist(base, quarter, rows):
    qdir = base / "agent_a" / "quarter" / quarter
    bundles = qdir / "bundles"
    bundles.mkdir(parents=True, exist_ok=True)
    fields = ["cik", "entity_name", "quarter", "reason", "regime", "n_rows",
              "none_pct", "dominant_signature", "has_existing_grammar", "bundle_path"]
    path = qdir / "worklist.csv"
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    return qdir, bundles


def _write_remediation_worklist(base, quarter, rows):
    qdir = base / "agent_a" / "quarter" / quarter
    bundles = qdir / "bundles"
    bundles.mkdir(parents=True, exist_ok=True)
    fields = ["cik", "entity_name", "verdict", "remediate_quarter", "reason", "bundle_path"]
    path = qdir / "remediation_worklist.csv"
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    return qdir, bundles


def _bundle(path, cik, quarter, regime="flattened"):
    path.write_text(json.dumps({
        "cik": cik,
        "engine": "agentA",
        "report_date": quarter,
        "entity_name": "Test Fund",
        "n_rows": 10,
        "regime": regime,
        "top_variants": [{"signature": "RATE", "samples": []}],
        "evidence_items": [{"evidence_id": "source_accessions", "data": []}],
    }), encoding="utf-8")


def _row(cik, quarter, bundle_path):
    return {
        "cik": cik, "entity_name": "Test Fund", "quarter": quarter,
        "reason": "uninduced", "regime": "flattened", "n_rows": "10",
        "none_pct": "0.0", "dominant_signature": "RATE",
        "has_existing_grammar": "False", "bundle_path": str(bundle_path),
    }


def test_preflight_writes_manifest_and_prompts(tmp_path, monkeypatch):
    quarter = "2025-12-31"
    monkeypatch.setattr(dp.config, "OUTPUT_DIR", tmp_path / "output")
    monkeypatch.setattr(dp.config, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(lk, "LOCK_DIR", tmp_path / "locks")
    qdir, bundles = _write_worklist(dp.config.OUTPUT_DIR, quarter, [])
    bpath = bundles / f"0001_{quarter}.json"
    _bundle(bpath, "0001", quarter)
    _write_worklist(dp.config.OUTPUT_DIR, quarter, [_row("0001", quarter, bpath)])

    result = dp.preflight_quarter(quarter, batch_id="batch", reserve=True)

    manifest = json.loads((qdir / "dispatch" / "batch" / "manifest.json").read_text(encoding="utf-8"))
    assert result["n_rows"] == 1
    assert manifest["rows"][0]["cik"] == "0001"
    assert (qdir / "dispatch" / "batch" / "prompts" / "0001.md").exists()
    assert lk.is_locked("0001")


def test_preflight_rejects_stale_proposal(tmp_path, monkeypatch):
    quarter = "2025-12-31"
    monkeypatch.setattr(dp.config, "OUTPUT_DIR", tmp_path / "output")
    monkeypatch.setattr(dp.config, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(lk, "LOCK_DIR", tmp_path / "locks")
    _, bundles = _write_worklist(dp.config.OUTPUT_DIR, quarter, [])
    bpath = bundles / f"0001_{quarter}.json"
    _bundle(bpath, "0001", quarter)
    _write_worklist(dp.config.OUTPUT_DIR, quarter, [_row("0001", quarter, bpath)])
    proposals = dp.config.OUTPUT_DIR / "agent_a" / "proposals"
    proposals.mkdir(parents=True)
    (proposals / "0001.anchors.json").write_text("{}", encoding="utf-8")

    with pytest.raises(dp.PreflightError, match="stale proposal"):
        dp.preflight_quarter(quarter, batch_id="batch")


def test_preflight_releases_prior_claims_on_acquire_failure(tmp_path, monkeypatch):
    quarter = "2025-12-31"
    monkeypatch.setattr(dp.config, "OUTPUT_DIR", tmp_path / "output")
    monkeypatch.setattr(dp.config, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(lk, "LOCK_DIR", tmp_path / "locks")
    _, bundles = _write_worklist(dp.config.OUTPUT_DIR, quarter, [])
    rows = []
    for cik in ("0001", "0002"):
        bpath = bundles / f"{cik}_{quarter}.json"
        _bundle(bpath, cik, quarter)
        rows.append(_row(cik, quarter, bpath))
    _write_worklist(dp.config.OUTPUT_DIR, quarter, rows)

    acquired = []
    released = []

    def fake_acquire(cik, owner=""):
        acquired.append(cik)
        return cik != "0002"

    monkeypatch.setattr(dp.cik_lock, "acquire", fake_acquire)
    monkeypatch.setattr(dp.cik_lock, "release", released.append)

    with pytest.raises(dp.PreflightError, match="failed to acquire"):
        dp.preflight_quarter(quarter, batch_id="batch", reserve=True)
    assert acquired == ["0001", "0002"]
    assert released == ["0001"]


def test_preflight_remediation_uses_failure_era_bundle(tmp_path, monkeypatch):
    quarter = "2025-12-31"
    remediate_quarter = "2023-12-31"
    monkeypatch.setattr(dp.config, "OUTPUT_DIR", tmp_path / "output")
    monkeypatch.setattr(dp.config, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(lk, "LOCK_DIR", tmp_path / "locks")
    qdir, bundles = _write_remediation_worklist(dp.config.OUTPUT_DIR, quarter, [])
    bpath = bundles / f"0001_{remediate_quarter}.json"
    _bundle(bpath, "0001", remediate_quarter)
    _write_remediation_worklist(dp.config.OUTPUT_DIR, quarter, [{
        "cik": "0001",
        "entity_name": "Test Fund",
        "verdict": "FAIL",
        "remediate_quarter": remediate_quarter,
        "reason": "held-out fail",
        "bundle_path": str(bpath),
    }])

    result = dp.preflight_quarter(quarter, batch_id="batch", remediation=True)

    manifest = json.loads((qdir / "dispatch" / "batch" / "manifest.json").read_text(encoding="utf-8"))
    row = manifest["rows"][0]
    assert result["n_rows"] == 1
    assert row["cik"] == "0001"
    assert row["quarter"] == quarter
    assert row["bundle_report_date"] == remediate_quarter
    assert row["bundle_path"] == str(bpath.resolve())
