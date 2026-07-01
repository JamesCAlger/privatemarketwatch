"""Tests for the generalized per-engine review bundler."""

from __future__ import annotations

import csv
import dataclasses
import json
from pathlib import Path

from pipeline import review_bundles
from pipeline.bdc_cik_review import read_csv_rows

QUEUE_COLS = [
    "priority_rank", "review_id", "lane", "anchor", "engine", "rule_name",
    "tier", "enforcement", "cik", "report_date", "period", "period_kind",
    "unit_label", "status", "mechanism", "confidence", "src_confidence",
    "surface", "n_units", "metric_name", "metric", "fv_at_risk_m",
]


def _q(**kw) -> dict[str, str]:
    base = {c: "" for c in QUEUE_COLS}
    base.update({k: str(v) for k, v in kw.items()})
    return base


def _write_csv(path: Path, header: list[str], rows: list[dict[str, str]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=header, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)


def _write_queue(path: Path, rows: list[dict[str, str]]) -> None:
    _write_csv(path, QUEUE_COLS, rows)


def _point_spec_at(monkeypatch, engine: str, artifact: Path) -> None:
    spec = review_bundles.EVIDENCE_SPECS[engine]
    monkeypatch.setitem(review_bundles.EVIDENCE_SPECS, engine, dataclasses.replace(spec, artifact=artifact))


def _run(tmp_path: Path, **kw):
    out = tmp_path / "out"
    result = review_bundles.build_review_bundles(
        queue_path=tmp_path / "review_queue.csv", output_dir=out, attach_holdings=False, **kw
    )
    manifest = read_csv_rows(out / "review_bundle_manifest.csv") if (out / "review_bundle_manifest.csv").exists() else []
    return result, out, manifest


def _load_bundle(out: Path, review_id: str) -> dict:
    return json.loads((out / "review_bundles" / f"{review_id}.json").read_text(encoding="utf-8"))


def test_row_validation_source_rows_attached(tmp_path, monkeypatch):
    art = tmp_path / "rowval.csv"
    _write_csv(art, ["cik", "report_date", "rule_id", "row_key", "message", "severity"], [
        {"cik": "0001287750", "report_date": "2026-03-31", "rule_id": "R12",
         "row_key": "rk1", "message": "bad rate", "severity": "WARN"},
        {"cik": "0001287750", "report_date": "2026-03-31", "rule_id": "R99",
         "row_key": "other", "message": "different rule", "severity": "WARN"},
    ])
    _point_spec_at(monkeypatch, "row_validation", art)
    _write_queue(tmp_path / "review_queue.csv", [
        _q(review_id="RVQ_REV_aaa", lane="review", engine="row_validation",
           rule_name="R12", cik="0001287750", report_date="2026-03-31", period="2026-03-31"),
    ])
    result, out, manifest = _run(tmp_path)
    assert result["bundles"] == 1
    b = _load_bundle(out, "RVQ_REV_aaa")
    assert b["evidence_completeness"] == "source_artifact"
    src = next(e for e in b["evidence_items"] if e["evidence_id"] == "source_artifact_rows")
    assert len(src["data"]) == 1 and src["data"][0]["rule_id"] == "R12"
    assert manifest[0]["evidence_completeness"] == "source_artifact"


def test_no_matching_rows(tmp_path, monkeypatch):
    art = tmp_path / "rowval.csv"
    _write_csv(art, ["cik", "report_date", "rule_id"], [
        {"cik": "0009999999", "report_date": "2020-01-01", "rule_id": "RZ"},
    ])
    _point_spec_at(monkeypatch, "row_validation", art)
    _write_queue(tmp_path / "review_queue.csv", [
        _q(review_id="x1", lane="review", engine="row_validation", rule_name="R12",
           cik="0001287750", report_date="2026-03-31", period="2026-03-31"),
    ])
    result, out, _ = _run(tmp_path)
    assert _load_bundle(out, "x1")["evidence_completeness"] == "no_matching_rows"


def test_artifact_missing(tmp_path, monkeypatch):
    _point_spec_at(monkeypatch, "row_validation", tmp_path / "does_not_exist.csv")
    _write_queue(tmp_path / "review_queue.csv", [
        _q(review_id="x2", lane="review", engine="row_validation", rule_name="R1",
           cik="0001287750", report_date="2026-03-31", period="2026-03-31"),
    ])
    result, out, _ = _run(tmp_path)
    assert _load_bundle(out, "x2")["evidence_completeness"] == "artifact_missing"


def test_unspecced_engine_is_ledger_only(tmp_path):
    _write_queue(tmp_path / "review_queue.csv", [
        _q(review_id="x3", lane="review", engine="made_up_engine", rule_name="Z",
           cik="0001287750", report_date="2026-03-31", period="2026-03-31"),
    ])
    result, out, _ = _run(tmp_path)
    b = _load_bundle(out, "x3")
    assert b["evidence_completeness"] == "ledger_only"
    assert {e["evidence_id"] for e in b["evidence_items"]} == {"flag"}


def test_source_recon_skipped_by_default(tmp_path):
    _write_queue(tmp_path / "review_queue.csv", [
        _q(review_id="BDCSRC_x", lane="blocker", engine="source_recon", rule_name="m",
           cik="0001287750", report_date="2026-03-31", period="2026-03-31"),
        _q(review_id="keep", lane="review", engine="made_up", rule_name="z",
           cik="0001287750", report_date="2026-03-31", period="2026-03-31"),
    ])
    result, out, _ = _run(tmp_path)
    assert result["bundles"] == 1
    assert (out / "review_bundles" / "keep.json").exists()
    assert not (out / "review_bundles" / "BDCSRC_x.json").exists()


def test_aggregate_header_name_keyed(tmp_path, monkeypatch):
    art = tmp_path / "agg.csv"
    _write_csv(art, ["name_norm", "verdict", "total_fv", "n_positions", "confidence"], [
        {"name_norm": "consumer goods", "verdict": "AGGREGATE_HEADER",
         "total_fv": "1096650000", "n_positions": "20", "confidence": "high"},
    ])
    _point_spec_at(monkeypatch, "aggregate_header", art)
    _write_queue(tmp_path / "review_queue.csv", [
        _q(review_id="agg1", lane="blocker", engine="aggregate_header",
           rule_name="AGGREGATE_HEADER", cik="", report_date="", period="",
           unit_label="consumer goods"),
    ])
    result, out, _ = _run(tmp_path)
    b = _load_bundle(out, "agg1")
    assert b["evidence_completeness"] == "source_artifact"
    src = next(e for e in b["evidence_items"] if e["evidence_id"] == "source_artifact_rows")
    assert src["data"][0]["name_norm"] == "consumer goods"


def test_holdings_slice_attached(tmp_path, monkeypatch):
    art = tmp_path / "rowval.csv"
    _write_csv(art, ["cik", "report_date", "rule_id"], [
        {"cik": "0001287750", "report_date": "2026-03-31", "rule_id": "R12"},
    ])
    _point_spec_at(monkeypatch, "row_validation", art)
    holdings = tmp_path / "holdings.csv"
    _write_csv(holdings, ["cik", "report_date", "issuer_name", "fair_value"], [
        {"cik": "0001287750", "report_date": "2026-03-31", "issuer_name": "Acme", "fair_value": "100"},
    ])
    monkeypatch.setattr(review_bundles, "HOLDINGS_FILE", holdings)
    _write_queue(tmp_path / "review_queue.csv", [
        _q(review_id="h1", lane="review", engine="row_validation", rule_name="R12",
           cik="0001287750", report_date="2026-03-31", period="2026-03-31"),
    ])
    out = tmp_path / "out"
    review_bundles.build_review_bundles(
        queue_path=tmp_path / "review_queue.csv", output_dir=out, attach_holdings=True,
    )
    b = _load_bundle(out, "h1")
    ids = {e["evidence_id"] for e in b["evidence_items"]}
    assert "holdings_slice" in ids
    assert b["has_raw_source"] is True


def test_lane_and_limit_filters(tmp_path):
    _write_queue(tmp_path / "review_queue.csv", [
        _q(review_id="a", lane="blocker", engine="made_up", rule_name="z", cik="0000000001",
           report_date="2024-12-31", period="2024-12-31"),
        _q(review_id="b", lane="review", engine="made_up", rule_name="z", cik="0000000002",
           report_date="2024-12-31", period="2024-12-31"),
        _q(review_id="c", lane="review", engine="made_up", rule_name="z", cik="0000000003",
           report_date="2024-12-31", period="2024-12-31"),
    ])
    result, out, _ = _run(tmp_path, lane="review", limit=1)
    assert result["bundles"] == 1
    assert (out / "review_bundles" / "b.json").exists()
