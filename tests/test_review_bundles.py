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


# ---------------------------------------------------------------------------
# provenance_reverify evidence slice
# ---------------------------------------------------------------------------

PROV_COLS = [
    "row_id", "cik", "report_date", "reason_code", "field",
    "declared_raw", "instance_raw", "published",
    "cheap_status", "full_status", "expected", "src_context_id",
]


def _prov_row(**kw) -> dict[str, str]:
    base = {c: "" for c in PROV_COLS}
    base.update({k: str(v) for k, v in kw.items()})
    return base


def test_provenance_reverify_matching_rows_attached(tmp_path, monkeypatch):
    """3 matching + 2 non-matching rows in ledger -> bundle carries exactly 3."""
    ledger = tmp_path / "provenance_ledger.csv"
    _write_csv(ledger, PROV_COLS, [
        # 3 matching rows
        _prov_row(row_id="r1", cik="0001287750", report_date="2026-03-31",
                  reason_code="filing_mismatch", field="fair_value",
                  declared_raw="1000", instance_raw="1001", published="1000"),
        _prov_row(row_id="r2", cik="0001287750", report_date="2026-03-31",
                  reason_code="filing_mismatch", field="interest_rate",
                  declared_raw="0.08", instance_raw="0.09", published="0.08"),
        _prov_row(row_id="r3", cik="0001287750", report_date="2026-03-31",
                  reason_code="filing_mismatch", field="cost",
                  declared_raw="900", instance_raw="950", published="900"),
        # 2 non-matching rows (wrong reason_code and wrong cik)
        _prov_row(row_id="r4", cik="0001287750", report_date="2026-03-31",
                  reason_code="other_rule", field="fair_value",
                  declared_raw="500", instance_raw="500", published="500"),
        _prov_row(row_id="r5", cik="0009999999", report_date="2026-03-31",
                  reason_code="filing_mismatch", field="fair_value",
                  declared_raw="200", instance_raw="200", published="200"),
    ])
    monkeypatch.setattr(review_bundles.config, "PROVENANCE_LEDGER_FILE", ledger)
    _write_queue(tmp_path / "review_queue.csv", [
        _q(review_id="PROV_001", lane="review", engine="provenance_reverify",
           rule_name="filing_mismatch", cik="0001287750",
           report_date="2026-03-31", period="2026-03-31"),
    ])
    result, out, manifest = _run(tmp_path)
    assert result["bundles"] == 1
    b = _load_bundle(out, "PROV_001")
    assert b["evidence_completeness"] == "source_artifact"
    src = next(e for e in b["evidence_items"] if e["evidence_id"] == "source_artifact_rows")
    assert len(src["data"]) == 3
    row_ids = {row["row_id"] for row in src["data"]}
    assert row_ids == {"r1", "r2", "r3"}
    # required columns must be present (includes adjudication split cols added 2026-08-24)
    for row in src["data"]:
        for col in ("row_id", "field", "declared_raw", "instance_raw", "published",
                    "cheap_status", "full_status", "expected", "src_context_id"):
            assert col in row, f"missing column {col}"
    assert manifest[0]["evidence_completeness"] == "source_artifact"


def test_provenance_reverify_non_matching_engine_no_slice(tmp_path, monkeypatch):
    """An item with a different engine does not pick up the provenance ledger rows."""
    ledger = tmp_path / "provenance_ledger.csv"
    _write_csv(ledger, PROV_COLS, [
        _prov_row(row_id="r1", cik="0001287750", report_date="2026-03-31",
                  reason_code="filing_mismatch", field="fair_value",
                  declared_raw="1000", instance_raw="1001", published="1000"),
    ])
    monkeypatch.setattr(review_bundles.config, "PROVENANCE_LEDGER_FILE", ledger)
    art = tmp_path / "rowval.csv"
    _write_csv(art, ["cik", "report_date", "rule_id"], [
        {"cik": "0001287750", "report_date": "2026-03-31", "rule_id": "filing_mismatch"},
    ])
    _point_spec_at(monkeypatch, "row_validation", art)
    _write_queue(tmp_path / "review_queue.csv", [
        _q(review_id="RV_001", lane="review", engine="row_validation",
           rule_name="filing_mismatch", cik="0001287750",
           report_date="2026-03-31", period="2026-03-31"),
    ])
    result, out, _ = _run(tmp_path)
    b = _load_bundle(out, "RV_001")
    src = next(e for e in b["evidence_items"] if e["evidence_id"] == "source_artifact_rows")
    # Should have 1 row from row_validation, NOT the provenance ledger row
    assert src["data"][0].get("rule_id") == "filing_mismatch"
    # no row_id from the provenance ledger (prov ledger has field col, rowval does not)
    assert "field" not in src["data"][0]


def test_provenance_sql_qualify_and_cap(tmp_path, monkeypatch):
    """SQL-level cap: QUALIFY clause present + exactly cap rows attach when cap+5 rows exist."""
    cap = 3
    n_rows = cap + 5  # 8 matching rows
    ledger = tmp_path / "provenance_ledger.csv"
    rows = [
        _prov_row(
            row_id=f"r{i}", cik="0001287750", report_date="2026-03-31",
            reason_code="filing_mismatch", field="fair_value",
            declared_raw=str(i * 100), instance_raw=str(i * 100 + 1), published=str(i * 100),
        )
        for i in range(n_rows)
    ]
    _write_csv(ledger, PROV_COLS, rows)
    monkeypatch.setattr(review_bundles.config, "PROVENANCE_LEDGER_FILE", ledger)

    # Verify the SQL string itself contains QUALIFY (SQL-level cap, not Python-level).
    targets = {("0001287750", "2026-03-31", "filing_mismatch")}
    sql, _ = review_bundles._build_provenance_sql(targets, cap)
    assert "QUALIFY" in sql.upper(), "SQL must contain QUALIFY for SQL-level per-target row cap"
    assert sql.count("?") >= 1, "SQL must use ? placeholders (no f-string value interpolation)"

    # Verify the end-to-end bundle path also returns exactly cap rows (not cap+5).
    _write_queue(tmp_path / "review_queue.csv", [
        _q(review_id="PROV_CAP", lane="review", engine="provenance_reverify",
           rule_name="filing_mismatch", cik="0001287750",
           report_date="2026-03-31", period="2026-03-31"),
    ])
    out = tmp_path / "out"
    review_bundles.build_review_bundles(
        queue_path=tmp_path / "review_queue.csv", output_dir=out,
        attach_holdings=False, max_rows=cap,
    )
    b = json.loads((out / "review_bundles" / "PROV_CAP.json").read_text(encoding="utf-8"))
    src = next(e for e in b["evidence_items"] if e["evidence_id"] == "source_artifact_rows")
    assert len(src["data"]) == cap, f"Expected exactly {cap} rows (SQL-level cap), got {len(src['data'])}"
