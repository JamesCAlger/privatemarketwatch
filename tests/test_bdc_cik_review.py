import csv
import json
from pathlib import Path

import pytest

from pipeline import bdc_cik_review as review


def _write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = sorted({key for row in rows for key in row})
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _residual(
    *,
    cik: str,
    report_date: str,
    mechanism: str,
    blocking: str = "True",
    fv: str = "100",
    issue_count: str = "1",
) -> dict[str, str]:
    return {
        "classification_id": f"{cik}-{report_date}-{mechanism}",
        "cik": cik,
        "entity_name": "BDC A",
        "report_date": report_date,
        "residual_class": "row_identity",
        "status": "missing_from_pipeline",
        "calibrated_status": "blocking_missing_from_pipeline",
        "match_tier": "",
        "blocking_issue": blocking,
        "mechanism": mechanism,
        "confidence": "medium",
        "recommended_action": "Fix parser.",
        "issue_count": issue_count,
        "affected_source_fair_value": fv,
        "affected_output_fair_value": "0",
        "sample_identifiers": "Issuer A",
        "sample_accessions": "0001",
        "reason": "source evidence",
    }


def test_build_worklist_includes_only_blockers_sorts_and_stabilizes_ids(tmp_path):
    residual = tmp_path / "source_reconciliation_residual_classification.csv"
    metrics = tmp_path / "source_reconciliation_metrics.csv"
    source_only = tmp_path / "source_reconciliation_source_only_detail.csv"
    gav = tmp_path / "holdings_gav_reconciliation.csv"
    holdings = tmp_path / "private_markets_holdings.csv"
    out = tmp_path / "bdc_cik_review"
    _write_csv(
        residual,
        [
            _residual(cik="1", report_date="2025-03-31", mechanism="m1", fv="50", issue_count="2"),
            _residual(cik="1", report_date="2025-03-31", mechanism="m1", fv="25", issue_count="3"),
            _residual(cik="2", report_date="2025-06-30", mechanism="m2", fv="200"),
            _residual(cik="3", report_date="2025-09-30", mechanism="m3", blocking="False", fv="999"),
        ],
    )
    _write_csv(
        metrics,
        [
            {"cik": "0000000001", "report_date": "2025-03-31", "source_rows": "10", "output_rows": "8", "matched_rows": "5", "reconciliation_status": "BLOCKED"},
            {"cik": "0000000002", "report_date": "2025-06-30", "source_rows": "12", "output_rows": "11", "matched_rows": "10", "reconciliation_status": "BLOCKED"},
        ],
    )
    _write_csv(source_only, [{"cik": "1", "report_date": "2025-03-31", "mechanism": "m1", "is_blocking": "True", "source_fair_value": "7"}])
    _write_csv(gav, [{"cik": "1", "report_date": "2025-03-31", "comparison_source": "investments_at_fair_value", "comparison_confidence": "STRONG", "comparison_value": "75", "flag": "ok", "reconciliation_status": "PASS"}])
    _write_csv(holdings, [{"cik": "1", "report_date": "2025-03-31", "fair_value": "70"}])

    stats = review.build_worklist(
        residual_path=residual,
        metrics_path=metrics,
        source_only_path=source_only,
        gav_path=gav,
        holdings_path=holdings,
        output_dir=out,
        top_n=10,
        batch_size=1,
    )

    rows = _read_csv(out / "worklist.csv")
    assert stats["worklist_count"] == 2
    assert [row["mechanism"] for row in rows] == ["m1", "m2"]
    assert rows[0]["cik"] == "0000000001"
    assert rows[0]["blocking_issue_count"] == "2"
    assert rows[0]["issue_count"] == "5"
    assert rows[0]["source_only_blocker_rows"] == "1"
    assert rows[0]["gav_gate_role"] == "strong_gate"
    assert rows[0]["holdings_row_count"] == "1"
    first_ids = [row["review_id"] for row in rows]

    review.build_worklist(
        residual_path=residual,
        metrics_path=metrics,
        source_only_path=source_only,
        gav_path=gav,
        holdings_path=holdings,
        output_dir=out,
        top_n=10,
        batch_size=1,
    )
    assert [row["review_id"] for row in _read_csv(out / "worklist.csv")] == first_ids
    assert (out / "batches" / "batch_001.csv").exists()


def test_build_bundle_includes_packet_artifacts_and_stable_evidence_ids(tmp_path, monkeypatch):
    output = tmp_path / "output"
    review_dir = output / "bdc_cik_review"
    paths = {
        "SOURCE_RECONCILIATION_RESIDUAL_CLASSIFICATION_FILE": output / "source_reconciliation_residual_classification.csv",
        "SOURCE_RECONCILIATION_METRICS_FILE": output / "source_reconciliation_metrics.csv",
        "SOURCE_RECONCILIATION_SOURCE_ONLY_DETAIL_FILE": output / "source_reconciliation_source_only_detail.csv",
        "SOURCE_RECONCILIATION_DETAIL_FILE": output / "source_reconciliation_detail.csv",
    }
    for name, path in paths.items():
        monkeypatch.setattr(review.config, name, path)
    monkeypatch.setattr(review.config, "OUTPUT_DIR", output)

    work = _residual(cik="1", report_date="2025-03-31", mechanism="m1", fv="100")
    _write_csv(paths["SOURCE_RECONCILIATION_RESIDUAL_CLASSIFICATION_FILE"], [work])
    _write_csv(paths["SOURCE_RECONCILIATION_METRICS_FILE"], [{"cik": "1", "report_date": "2025-03-31"}])
    _write_csv(paths["SOURCE_RECONCILIATION_SOURCE_ONLY_DETAIL_FILE"], [{"cik": "1", "report_date": "2025-03-31", "mechanism": "m1", "is_blocking": "True", "source_fair_value": "100"}])
    _write_csv(paths["SOURCE_RECONCILIATION_DETAIL_FILE"], [{"cik": "1", "report_date": "2025-03-31", "blocking_issue": "True", "source_fair_value": "100"}])
    _write_csv(output / "holdings_gav_reconciliation.csv", [{"cik": "1", "report_date": "2025-03-31", "comparison_source": "investments_at_fair_value", "comparison_confidence": "STRONG", "comparison_value": "100"}])
    _write_csv(output / "holdings_pct_sum.csv", [{"cik": "1", "report_date": "2025-03-31", "pct_sum": "100"}])
    _write_csv(output / "position_purity_metrics.csv", [{"cik": "1", "report_date": "2025-03-31", "subtotal_candidate_rows": "0"}])
    _write_csv(output / "private_markets_holdings.csv", [{"cik": "1", "report_date": "2025-03-31", "fair_value": "100"}])

    review.build_worklist(
        residual_path=paths["SOURCE_RECONCILIATION_RESIDUAL_CLASSIFICATION_FILE"],
        metrics_path=paths["SOURCE_RECONCILIATION_METRICS_FILE"],
        source_only_path=paths["SOURCE_RECONCILIATION_SOURCE_ONLY_DETAIL_FILE"],
        gav_path=output / "holdings_gav_reconciliation.csv",
        holdings_path=output / "private_markets_holdings.csv",
        output_dir=review_dir,
    )
    manifest = review.build_bundles(output_dir=review_dir, overwrite=True)

    bundle = json.loads((review_dir / "bundles" / f"{manifest[0]['review_id']}.json").read_text(encoding="utf-8"))
    evidence_ids = [item["evidence_id"] for item in bundle["evidence_items"]]
    assert "cik_validation_packet" in evidence_ids
    assert "html_artifact" in evidence_ids
    assert len(evidence_ids) == len(set(evidence_ids))
    assert bundle["evidence_items"][1]["data"]["source_reconciliation"]["blocker_count"] == 2
    assert bundle["artifact_hashes"]
    html_item = next(item for item in bundle["evidence_items"] if item["evidence_id"] == "html_artifact")
    assert html_item["data"]["status"] == "missing_cached_html"


def test_validate_verdict_rejects_missing_bundle_unknown_evidence_gav_primary_and_protected_edits(tmp_path):
    output = tmp_path / "review"
    (output / "bundles").mkdir(parents=True)
    (output / "verdicts").mkdir(parents=True)
    review_id = "BDCSRC_0000000001_2025-03-31_M1_abc"
    bundle = {
        "review_id": review_id,
        "cik": "0000000001",
        "report_date": "2025-03-31",
        "evidence_items": [{"evidence_id": "worklist_row"}],
    }
    (output / "bundles" / f"{review_id}.json").write_text(json.dumps(bundle), encoding="utf-8")
    verdict = {
        "review_id": review_id,
        "cik": "0000000001",
        "report_date": "2025-03-31",
        "verdict": "PATCH_PROPOSED",
        "confidence": "HIGH",
        "primary_justification": "GAV ratio would improve",
        "evidence_refs": ["unknown"],
        "changed_files": ["data/output/private_markets_holdings.csv"],
        "patch_summary": "",
        "source_reconciliation_effect": "",
        "gav_effect": "",
        "tests_validation_plan": "",
        "requires_human_merge": False,
        "missing_evidence": "",
        "residual_risk": "risk",
        "reviewer_notes": "notes",
    }
    verdict_path = output / "verdicts" / f"{review_id}.json"
    verdict_path.write_text(json.dumps(verdict), encoding="utf-8")

    errors = review.validate_verdict_file(verdict_path, output)

    assert any("unknown evidence_ref" in error for error in errors)
    assert any("GAV improvement" in error for error in errors)
    assert any("protected generated-output" in error for error in errors)
    assert any("requires requires_human_merge=true" in error for error in errors)

    missing = dict(verdict, review_id="missing", primary_justification="Source evidence", evidence_refs=[])
    missing_path = output / "verdicts" / "missing.json"
    missing_path.write_text(json.dumps(missing), encoding="utf-8")
    assert any("Missing bundle" in error for error in review.validate_verdict_file(missing_path, output))


def test_validate_accepts_insufficient_evidence_and_summary_counts(tmp_path):
    output = tmp_path / "review"
    (output / "bundles").mkdir(parents=True)
    (output / "verdicts").mkdir(parents=True)
    review_id = "BDCSRC_0000000001_2025-03-31_M1_abc"
    _write_csv(
        output / "worklist.csv",
        [{"review_id": review_id, "cik": "0000000001", "report_date": "2025-03-31", "mechanism": "m1", "affected_source_fair_value": "100"}],
    )
    (output / "bundles" / f"{review_id}.json").write_text(
        json.dumps({"review_id": review_id, "cik": "0000000001", "report_date": "2025-03-31", "evidence_items": [{"evidence_id": "worklist_row"}]}),
        encoding="utf-8",
    )
    verdict = {
        "review_id": review_id,
        "cik": "0000000001",
        "report_date": "2025-03-31",
        "verdict": "INSUFFICIENT_EVIDENCE",
        "confidence": "LOW",
        "primary_justification": "Source evidence is ambiguous",
        "evidence_refs": ["worklist_row"],
        "changed_files": [],
        "patch_summary": "",
        "source_reconciliation_effect": "",
        "gav_effect": "",
        "tests_validation_plan": "",
        "requires_human_merge": False,
        "missing_evidence": "Need source filing detail beyond the cached residual row.",
        "residual_risk": "Cannot identify a bounded parser mechanism.",
        "reviewer_notes": "Escalating instead of forcing a patch.",
    }
    (output / "verdicts" / f"{review_id}.json").write_text(json.dumps(verdict), encoding="utf-8")

    assert review.validate_all_verdicts(output) == []
    summary = review.summarize_verdicts(output)
    assert summary["counts"] == {"INSUFFICIENT_EVIDENCE": 1}
    rows = _read_csv(output / "summary.csv")
    assert rows[0]["missing_evidence"].startswith("Need source filing")
    assert (output / "summary.md").exists()


def test_validate_rejects_html_refs_without_coordinates_and_accepts_missing_artifact(tmp_path):
    output = tmp_path / "review"
    (output / "bundles").mkdir(parents=True)
    (output / "verdicts").mkdir(parents=True)
    review_id = "BDCSRC_0000000001_2025-03-31_M1_abc"
    (output / "worklist.csv").write_text(
        "review_id,cik,report_date,mechanism,affected_source_fair_value\n"
        f"{review_id},0000000001,2025-03-31,m1,100\n",
        encoding="utf-8",
    )
    (output / "bundles" / f"{review_id}.json").write_text(
        json.dumps({"review_id": review_id, "cik": "0000000001", "report_date": "2025-03-31", "evidence_items": [{"evidence_id": "html_table_grid_excerpt"}, {"evidence_id": "html_artifact"}]}),
        encoding="utf-8",
    )
    verdict = {
        "review_id": review_id,
        "cik": "0000000001",
        "report_date": "2025-03-31",
        "verdict": "INSUFFICIENT_EVIDENCE",
        "confidence": "LOW",
        "primary_justification": "HTML evidence is unresolved.",
        "evidence_refs": ["html_table_grid_excerpt"],
        "changed_files": [],
        "patch_summary": "",
        "source_reconciliation_effect": "",
        "gav_effect": "",
        "tests_validation_plan": "",
        "requires_human_merge": False,
        "missing_evidence": "Need table coordinates rather than free-text HTML search hits.",
        "residual_risk": "No parser patch should be merged.",
        "reviewer_notes": "Reject free-text-only HTML citation.",
    }
    verdict_path = output / "verdicts" / f"{review_id}.json"
    verdict_path.write_text(json.dumps(verdict), encoding="utf-8")

    errors = review.validate_verdict_file(verdict_path, output)
    assert any("requires table_index,row_index,cell_indices" in error for error in errors)

    verdict["evidence_refs"] = ["html_artifact"]
    verdict_path.write_text(json.dumps(verdict), encoding="utf-8")
    assert review.validate_all_verdicts(output) == []


def test_validate_reconciliation_diagnosis_requires_coordinate_html_evidence(tmp_path):
    output = tmp_path / "review"
    (output / "bundles").mkdir(parents=True)
    (output / "verdicts").mkdir(parents=True)
    review_id = "BDCSRC_0000000001_2025-03-31_M1_abc"
    (output / "worklist.csv").write_text(
        "review_id,cik,report_date,mechanism,affected_source_fair_value\n"
        f"{review_id},0000000001,2025-03-31,m1,100\n",
        encoding="utf-8",
    )
    (output / "bundles" / f"{review_id}.json").write_text(
        json.dumps(
            {
                "review_id": review_id,
                "cik": "0000000001",
                "report_date": "2025-03-31",
                "evidence_items": [
                    {"evidence_id": "worklist_row"},
                    {"evidence_id": "html_source_row_coordinate_candidates"},
                ],
            }
        ),
        encoding="utf-8",
    )
    verdict = {
        "review_id": review_id,
        "cik": "0000000001",
        "report_date": "2025-03-31",
        "verdict": "PATCH_PROPOSED",
        "confidence": "HIGH",
        "primary_justification": "Source reconciliation row is visible in HTML.",
        "reconciliation_diagnosis": "REAL_POSITION_MISSING_FROM_UNIFIED",
        "evidence_refs": ["worklist_row", "html_source_row_coordinate_candidates"],
        "changed_files": ["pipeline/source_reconciliation.py"],
        "patch_summary": "Use source evidence to fix parser path.",
        "source_reconciliation_effect": "Expected to reduce the source-only blocker.",
        "gav_effect": "Context only.",
        "tests_validation_plan": "pytest tests/test_validate_holdings.py",
        "requires_human_merge": True,
        "missing_evidence": "",
        "residual_risk": "Scope must remain CIK/date bounded.",
        "reviewer_notes": "Coordinate citation required.",
    }
    verdict_path = output / "verdicts" / f"{review_id}.json"
    verdict_path.write_text(json.dumps(verdict), encoding="utf-8")

    errors = review.validate_verdict_file(verdict_path, output)
    assert any("requires table_index,row_index,cell_indices" in error for error in errors)

    verdict["html_citations"] = [
        {
            "evidence_ref": "html_source_row_coordinate_candidates",
            "table_index": 1,
            "row_index": 2,
            "cell_indices": [0, 1],
            "row_classification": "AGGREGATE_HEADER",
            "reason": "Aggregate row.",
        }
    ]
    verdict_path.write_text(json.dumps(verdict), encoding="utf-8")
    errors = review.validate_verdict_file(verdict_path, output)
    assert any("cannot support REAL_POSITION_MISSING_FROM_UNIFIED" in error for error in errors)

    verdict["html_citations"][0]["row_classification"] = "POSITION_ROW"
    verdict["html_citations"][0]["reason"] = "Visible source row is a position row."
    verdict_path.write_text(json.dumps(verdict), encoding="utf-8")
    assert review.validate_all_verdicts(output) == []


def test_summary_includes_reconciliation_diagnosis_counts(tmp_path):
    output = tmp_path / "review"
    (output / "bundles").mkdir(parents=True)
    (output / "verdicts").mkdir(parents=True)
    review_id = "BDCSRC_0000000001_2025-03-31_M1_abc"
    _write_csv(
        output / "worklist.csv",
        [{"review_id": review_id, "cik": "0000000001", "report_date": "2025-03-31", "mechanism": "m1", "affected_source_fair_value": "100"}],
    )
    (output / "bundles" / f"{review_id}.json").write_text(
        json.dumps({"review_id": review_id, "cik": "0000000001", "report_date": "2025-03-31", "evidence_items": [{"evidence_id": "worklist_row"}]}),
        encoding="utf-8",
    )
    verdict = {
        "review_id": review_id,
        "cik": "0000000001",
        "report_date": "2025-03-31",
        "verdict": "INSUFFICIENT_EVIDENCE",
        "confidence": "LOW",
        "primary_justification": "Source evidence is ambiguous.",
        "reconciliation_diagnosis": "INSUFFICIENT_EVIDENCE",
        "evidence_refs": ["worklist_row"],
        "changed_files": [],
        "patch_summary": "",
        "source_reconciliation_effect": "",
        "gav_effect": "",
        "tests_validation_plan": "",
        "requires_human_merge": False,
        "missing_evidence": "Need coordinate-level source filing evidence.",
        "residual_risk": "No bounded mechanism.",
        "reviewer_notes": "Do not force a patch.",
    }
    (output / "verdicts" / f"{review_id}.json").write_text(json.dumps(verdict), encoding="utf-8")

    summary = review.summarize_verdicts(output)
    assert summary["diagnosis_counts"] == {"INSUFFICIENT_EVIDENCE": 1}
    rows = _read_csv(output / "summary.csv")
    assert rows[0]["reconciliation_diagnosis"] == "INSUFFICIENT_EVIDENCE"
    assert "INSUFFICIENT_EVIDENCE: 1 reviews" in (output / "summary.md").read_text(encoding="utf-8")


def test_raw_source_rows_by_pair_projects_dedups_current_period(tmp_path):
    detail = tmp_path / "detail.csv"
    _write_csv(detail, [
        # current-period row -> included
        {"cik": "1287750", "report_date": "2025-03-31", "period": "2025-03-31",
         "raw_investment_identifier": "Acme Corp Term Loan", "source_fair_value": "1000",
         "output_fair_value": "1000", "status": "matched"},
        # exact duplicate (same identifier + source FV) -> deduped away
        {"cik": "1287750", "report_date": "2025-03-31", "period": "2025-03-31",
         "raw_investment_identifier": "Acme Corp Term Loan", "source_fair_value": "1000",
         "output_fair_value": "1000", "status": "matched"},
        # FV-distinct sibling (same identifier, different FV) -> kept as distinct
        {"cik": "1287750", "report_date": "2025-03-31", "period": "2025-03-31",
         "raw_investment_identifier": "Acme Corp Term Loan", "source_fair_value": "2000",
         "output_fair_value": "", "status": "missing_from_pipeline"},
        # comparative period (period != report_date) -> excluded
        {"cik": "1287750", "report_date": "2025-03-31", "period": "2024-12-31",
         "raw_investment_identifier": "Acme Corp Term Loan", "source_fair_value": "999",
         "output_fair_value": "999", "status": "matched"},
        # different pair (not requested) -> excluded
        {"cik": "9999999", "report_date": "2025-03-31", "period": "2025-03-31",
         "raw_investment_identifier": "Other", "source_fair_value": "5",
         "output_fair_value": "5", "status": "matched"},
    ])
    pairs = {(review.normalize_cik("1287750"), review.normalize_text("2025-03-31"))}
    out = review._raw_source_rows_by_pair(detail, pairs)
    key = (review.normalize_cik("1287750"), review.normalize_text("2025-03-31"))
    rows = out[key]
    # dedup exact dup + drop comparative + drop other pair; keep FV-distinct sibling
    assert len(rows) == 2
    assert sorted(r["source_fair_value"] for r in rows) == ["1000", "2000"]
    # projection to exactly the four fields, incl output FV + match status
    assert set(rows[0].keys()) == {
        "raw_investment_identifier", "source_fair_value", "output_fair_value", "match_status"}
    miss = [r for r in rows if r["match_status"] == "missing_from_pipeline"][0]
    assert miss["output_fair_value"] == ""
    # only the requested pair is present
    assert set(out) == {key}
