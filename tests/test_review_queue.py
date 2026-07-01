"""Tests for the ledger-first unified review queue builder."""

from __future__ import annotations

import csv
from pathlib import Path

from pipeline import review_queue
from pipeline.bdc_cik_review import make_review_id, read_csv_rows

LEDGER_HEADER = [
    "engine", "rule_name", "tier", "enforcement", "cik", "period_kind",
    "period", "status", "metric", "metric_name", "n_units", "mechanism",
    "src_confidence", "confidence", "surface",
]


def _row(**kw) -> dict[str, str]:
    base = {k: "" for k in LEDGER_HEADER}
    base.update({k: str(v) for k, v in kw.items()})
    return base


def _write_ledger(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=LEDGER_HEADER)
        w.writeheader()
        for r in rows:
            w.writerow(r)


def _build(tmp_path: Path, rows: list[dict[str, str]], **kw):
    ledger = tmp_path / "ledger.csv"
    _write_ledger(ledger, rows)
    out = tmp_path / "review_queue"
    result = review_queue.build_review_queue(ledger_path=ledger, output_dir=out, **kw)
    items = read_csv_rows(out / "review_queue.csv")
    return result, items


def test_lane_mapping_tight_blocker_weak_review(tmp_path):
    rows = [
        _row(engine="source_recon", rule_name="src", tier="tight", cik="0001287750",
             period_kind="quarter", period="2026-03-31", status="fail",
             metric="100.0", metric_name="affected_fv_m", n_units="5",
             mechanism="blocking_source_short_plain_unresolved"),
        _row(engine="fund_strategy", rule_name="fs", tier="weak", cik="0001287750",
             period_kind="quarter", period="2026-03-31", status="warn",
             metric="20.0", metric_name="affected_pct", n_units="3", mechanism="strategy"),
    ]
    _, items = _build(tmp_path, rows)
    by_engine = {i["engine"]: i for i in items}
    assert by_engine["source_recon"]["lane"] == "blocker"
    assert by_engine["fund_strategy"]["lane"] == "review"


def test_source_recon_review_id_matches_make_review_id(tmp_path):
    rows = [
        _row(engine="source_recon", rule_name="src", tier="tight", cik="0001287750",
             period_kind="quarter", period="2026-03-31", status="fail",
             metric="100.0", metric_name="affected_fv_m", n_units="1",
             mechanism="blocking_source_pct_leaf_parser_mismatch"),
    ]
    _, items = _build(tmp_path, rows)
    expected = make_review_id("0001287750", "2026-03-31", "blocking_source_pct_leaf_parser_mismatch")
    assert items[0]["review_id"] == expected


def test_fv_at_risk_only_for_fv_metrics(tmp_path):
    rows = [
        _row(engine="source_recon", rule_name="src", tier="tight", cik="0000000001",
             period_kind="quarter", period="2024-12-31", status="fail",
             metric="42.5", metric_name="affected_fv_m", n_units="1", mechanism="m"),
        _row(engine="gav_recon", rule_name="gav", tier="tight", cik="0000000002",
             period_kind="quarter", period="2024-12-31", status="fail",
             metric="8.87", metric_name="residual_pct", n_units="1", mechanism="m"),
    ]
    _, items = _build(tmp_path, rows)
    by_engine = {i["engine"]: i for i in items}
    assert by_engine["source_recon"]["fv_at_risk_m"] == "42.500000"
    assert by_engine["gav_recon"]["fv_at_risk_m"] == ""  # residual_pct is not FV


def test_prioritization_blocker_before_review_and_fv_desc(tmp_path):
    rows = [
        _row(engine="fund_strategy", rule_name="fs", tier="weak", cik="0000000009",
             period_kind="quarter", period="2024-12-31", status="warn",
             metric="99.0", metric_name="affected_pct", n_units="50", mechanism="m"),
        _row(engine="source_recon", rule_name="src", tier="tight", cik="0000000001",
             period_kind="quarter", period="2024-12-31", status="fail",
             metric="10.0", metric_name="affected_fv_m", n_units="1", mechanism="m"),
        _row(engine="aggregate_header", rule_name="AGGREGATE_HEADER", tier="tight",
             cik="consumer goods", period_kind="name", period="", status="fail",
             metric="1096.65", metric_name="total_fv_m", n_units="20", mechanism="agg"),
    ]
    _, items = _build(tmp_path, rows)
    # blocker lane (both tight) ranks above the review-lane weak row, and within
    # the blocker lane the larger FV-at-risk ranks first.
    assert [i["engine"] for i in items] == ["aggregate_header", "source_recon", "fund_strategy"]
    assert items[0]["priority_rank"] == "1"
    assert items[-1]["lane"] == "review"


def test_pass_and_skip_excluded(tmp_path):
    rows = [
        _row(engine="gav_recon", rule_name="gav", tier="tight", cik="0000000001",
             period_kind="quarter", period="2024-12-31", status="pass",
             metric="0.1", metric_name="residual_pct", n_units="1", mechanism="m"),
        _row(engine="source_recon", rule_name="src", tier="tight", cik="0000000002",
             period_kind="quarter", period="2024-12-31", status="skip",
             metric="0", metric_name="affected_fv_m", n_units="0", mechanism="m"),
        _row(engine="source_recon", rule_name="src", tier="tight", cik="0000000003",
             period_kind="quarter", period="2024-12-31", status="fail",
             metric="5.0", metric_name="affected_fv_m", n_units="1", mechanism="m"),
    ]
    result, items = _build(tmp_path, rows)
    assert result["items"] == 1
    assert items[0]["cik"] == "0000000003"


def test_name_keyed_row_not_localized(tmp_path):
    rows = [
        _row(engine="aggregate_header", rule_name="AGGREGATE_HEADER", tier="tight",
             cik="consumer goods", period_kind="name", period="", status="fail",
             metric="21.63", metric_name="total_fv_m", n_units="1", mechanism="agg"),
    ]
    _, items = _build(tmp_path, rows)
    assert items[0]["cik"] == ""               # not a CIK
    assert items[0]["report_date"] == ""        # not localizable
    assert items[0]["unit_label"] == "consumer goods"
    assert items[0]["review_id"].startswith("RVQ_BLK_")


def test_anchor_classification(tmp_path):
    rows = [
        _row(engine="source_recon", rule_name="src", tier="tight", cik="0000000001",
             period_kind="quarter", period="2024-12-31", status="fail",
             metric="1", metric_name="affected_fv_m", n_units="1", mechanism="m"),
        _row(engine="identity", rule_name="pct_identity", tier="tight", cik="0000000002",
             period_kind="quarter", period="2024-12-31", status="fail",
             metric="1", metric_name="violation_pct", n_units="1", mechanism="m"),
    ]
    _, items = _build(tmp_path, rows)
    by_engine = {i["engine"]: i for i in items}
    assert by_engine["source_recon"]["anchor"] == "source"
    assert by_engine["identity"]["anchor"] == "internal"


def test_bdc_worklist_projection_only_source_recon(tmp_path):
    rows = [
        _row(engine="source_recon", rule_name="src", tier="tight", cik="0001287750",
             period_kind="quarter", period="2026-03-31", status="fail",
             metric="100.0", metric_name="affected_fv_m", n_units="1",
             mechanism="blocking_source_short_plain_unresolved"),
        _row(engine="identity", rule_name="pct", tier="tight", cik="0000000002",
             period_kind="quarter", period="2024-12-31", status="fail",
             metric="5", metric_name="violation_pct", n_units="1", mechanism="m"),
    ]
    _, items = _build(tmp_path, rows)
    proj = review_queue.bdc_worklist_projection(items=items)
    assert len(proj) == 1
    p = proj[0]
    assert p["cik"] == "0001287750"
    assert p["report_date"] == "2026-03-31"
    assert p["review_id"] == make_review_id(
        "0001287750", "2026-03-31", "blocking_source_short_plain_unresolved"
    )
    # affected_source_fair_value is re-expanded from millions to raw dollars.
    assert abs(float(p["affected_source_fair_value"]) - 100_000_000.0) < 1.0


def test_lane_filter_blocker_only(tmp_path):
    rows = [
        _row(engine="source_recon", rule_name="src", tier="tight", cik="0000000001",
             period_kind="quarter", period="2024-12-31", status="fail",
             metric="1", metric_name="affected_fv_m", n_units="1", mechanism="m"),
        _row(engine="fund_strategy", rule_name="fs", tier="weak", cik="0000000002",
             period_kind="quarter", period="2024-12-31", status="warn",
             metric="1", metric_name="affected_pct", n_units="1", mechanism="m"),
    ]
    result, items = _build(tmp_path, rows, lanes=("blocker",))
    assert result["items"] == 1
    assert items[0]["lane"] == "blocker"
