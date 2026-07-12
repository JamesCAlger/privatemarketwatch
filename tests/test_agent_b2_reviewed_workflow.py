"""Tests for the reviewed B1 -> B2 target bridge."""

from __future__ import annotations

import csv

import pytest

from scripts.agent_b2 import reviewed_workflow as rw


QUEUE_COLUMNS = [
    "priority_rank", "review_id", "lane", "anchor", "engine", "rule_name", "tier",
    "enforcement", "cik", "report_date", "period", "period_kind", "unit_label", "status",
    "mechanism", "confidence", "src_confidence", "surface", "n_units", "metric_name",
    "metric", "fv_at_risk_m",
]


def _write_csv(path, rows, cols):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for row in rows:
            w.writerow({c: row.get(c, "") for c in cols})


def test_select_review_rows_maps_cik_quarter_to_conservation_b1_id(tmp_path):
    queue = tmp_path / "review_queue.csv"
    _write_csv(queue, [
        {"priority_rank": "2", "review_id": "RVQ_other", "lane": "blocker",
         "engine": "identity", "rule_name": "pct_identity", "cik": "0001743415",
         "report_date": "2023-12-31"},
        {"priority_rank": "1", "review_id": "RVQ_fv", "lane": "blocker",
         "engine": "conservation", "rule_name": "fv_conservation", "cik": "0001743415",
         "report_date": "2023-12-31"},
    ], QUEUE_COLUMNS)
    targets = tmp_path / "targets.csv"
    _write_csv(targets, [{"cik": "1743415", "target_quarter": "2023-12-31"}],
               ["cik", "target_quarter"])

    rows = rw.select_review_rows(targets_path=targets, queue_path=queue)

    assert [r["review_id"] for r in rows] == ["RVQ_fv"]


def test_select_review_rows_errors_when_target_has_no_b1_queue_row(tmp_path):
    queue = tmp_path / "review_queue.csv"
    _write_csv(queue, [
        {"priority_rank": "1", "review_id": "RVQ_fv", "lane": "blocker",
         "engine": "conservation", "rule_name": "fv_conservation", "cik": "0001743415",
         "report_date": "2024-12-31"},
    ], QUEUE_COLUMNS)
    targets = tmp_path / "targets.csv"
    _write_csv(targets, [{"cik": "1743415", "target_quarter": "2023-12-31"}],
               ["cik", "target_quarter"])

    with pytest.raises(rw.ReviewedWorkflowError, match="no B1 review queue row matched"):
        rw.select_review_rows(targets_path=targets, queue_path=queue)


def test_build_b1_batch_uses_selected_review_ids(tmp_path, monkeypatch):
    queue = tmp_path / "review_queue.csv"
    _write_csv(queue, [
        {"priority_rank": "1", "review_id": "RVQ_fv", "lane": "blocker",
         "engine": "conservation", "rule_name": "fv_conservation", "cik": "0001743415",
         "report_date": "2023-12-31"},
    ], QUEUE_COLUMNS)
    targets = tmp_path / "targets.csv"
    _write_csv(targets, [{"review_id": "RVQ_fv"}], ["review_id"])
    seen = {}

    def fake_discover(batch_id, *, base_dir, queue_path, review_ids):
        seen["batch_id"] = batch_id
        seen["base_dir"] = base_dir
        seen["queue_path"] = queue_path
        seen["review_ids"] = review_ids
        (base_dir / "batch" / batch_id).mkdir(parents=True)
        return {"worklist": str(base_dir / "batch" / batch_id / "worklist.csv")}

    monkeypatch.setattr(rw.run_review, "discover", fake_discover)

    result = rw.build_b1_batch(
        "B1X", targets_path=targets, queue_path=queue, base_dir=tmp_path / "agent_b"
    )

    assert seen["review_ids"] == {"RVQ_fv"}
    assert result["n_review_ids"] == 1
    assert (tmp_path / "agent_b" / "batch" / "B1X" / "selected_review_ids.csv").exists()
