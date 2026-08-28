"""Q4 closure report tests use fully isolated artifact stores."""

from __future__ import annotations

import csv
import json

from scripts.report_q4_v1_funnel import QUARTER, build_report


def _csv(path, rows):
    fields = ["review_id", "cik", "report_date", "lane", "rule_name", "engine",
              "fv_at_risk_m", "fund_quarter_fv_m"]
    with path.open("w", newline="", encoding="utf-8") as handle:
        w = csv.DictWriter(handle, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def test_report_requires_keyed_no_change_evidence(tmp_path):
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"entries": [{"cik": "1", "entity_name": "Fund"}]}),
                        encoding="utf-8")
    frozen, queue = tmp_path / "frozen.csv", tmp_path / "queue.csv"
    row = {"review_id": "R1", "cik": "0000000001", "report_date": QUARTER,
           "lane": "blocker", "rule_name": "x", "engine": "source_recon",
           "fv_at_risk_m": "1", "fund_quarter_fv_m": "10"}
    _csv(frozen, [row])
    _csv(queue, [row])
    verdicts = tmp_path / "verdicts"
    verdicts.mkdir()
    (verdicts / "R1.json").write_text(json.dumps({"review_id": "R1", "verdict": "real_error",
                                                    "findings": [{"fix_class": "missing_position_add"}]}),
                                      encoding="utf-8")
    batch = tmp_path / "batch"
    (batch / "b" / "dispositions").mkdir(parents=True)
    # A generic JSON with no exact review id cannot close the finding.
    (batch / "b" / "gate.json").write_text(json.dumps({"verdict": "PASS", "batch_id": "b"}),
                                                encoding="utf-8")
    staged, promoted = tmp_path / "staged", tmp_path / "promoted"
    staged.mkdir(); promoted.mkdir()
    lifecycle, report, summary = build_report(
        frozen_ledger_path=frozen, queue_path=queue, manifest_path=manifest,
        verdicts_dirs=(verdicts,), b2_batch_dir=batch, b2_corrections_dir=staged,
        promoted_dir=promoted)
    assert lifecycle[0]["state"] == "real_error_unremediated"
    assert report[0]["actionable_outstanding"] == 1
    assert summary["lifecycle"]["dry"] is False

    (batch / "b" / "dispositions" / "R1.json").write_text(json.dumps({
        "schema_version": 1, "disposition": "no_change_required",
        "reason_code": "baseline_source_identity_present", "source_review_ids": ["R1"],
    }), encoding="utf-8")
    lifecycle, report, _ = build_report(
        frozen_ledger_path=frozen, queue_path=queue, manifest_path=manifest,
        verdicts_dirs=(verdicts,), b2_batch_dir=batch, b2_corrections_dir=staged,
        promoted_dir=promoted)
    assert lifecycle[0]["state"] == "b1_re_adjudication_required"
    assert report[0]["b2_validated_no_change"] == 1
