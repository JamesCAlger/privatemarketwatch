import csv
import json
from pathlib import Path

import pytest

from pipeline import position_match_review as review


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
    source: str = "bdc",
    quarter: str = "2025q2",
    cik: str = "1",
    report_date: str = "2025-06-30",
    issuer_name: str = "Borrower A, First Lien",
    index_classification: str = "DIRECT_LENDING",
    residual_bucket: str = "same_issuer_existed_unmatched",
    fair_value: str = "100",
) -> dict[str, str]:
    return {
        "source": source,
        "quarter": quarter,
        "cik": cik,
        "entity_name": "BDC A",
        "report_date": report_date,
        "issuer_name": issuer_name,
        "position_id": "POS-1",
        "index_classification": index_classification,
        "fair_value": fair_value,
        "cusip": "123456789",
        "bdc_investment_identifier": issuer_name,
        "instrument_description": "First Lien",
        "residual_bucket": residual_bucket,
    }


def _valid_verdict(review_id: str) -> dict[str, object]:
    return {
        "review_id": review_id,
        "source": "bdc",
        "cik": "0000000001",
        "quarter": "2025q2",
        "index_classification": "DIRECT_LENDING",
        "verdict": "RULE_PROPOSED",
        "confidence": "HIGH",
        "primary_justification": "Candidate identity evidence shows stable tranche text and matching source identifiers.",
        "evidence_refs": ["worklist_row", "match_residual_rows", "prior_candidate_holdings"],
        "changed_files": ["overrides/position_matching_rules.json", "tests/test_position_matching.py"],
        "rule_scope": "BDC CIK 0000000001 DIRECT_LENDING adjacent quarters only.",
        "rule_type": "tranche_key",
        "rule_summary": "Use normalized BDC identifier plus tranche text.",
        "deterministic_conditions": "Require same CIK/source/class, adjacent quarter span, matching normalized identifier, one-to-one assignment.",
        "positive_examples": [{"evidence_ref": "match_residual_rows", "reason": "same identifier"}],
        "false_positive_examples": [{"evidence_ref": "prior_candidate_holdings", "reason": "same borrower but different rate"}],
        "guardrails": "Enforce one-to-one matching, adjacent-quarter span, maturity/rate/coupon/principal and FV guards.",
        "expected_coverage_effect": "Expected short-span FV coverage improvement for this CIK only after deterministic dry run.",
        "false_match_risk": "Same borrower with a different tranche remains possible and is rejected by rate/maturity/principal guards.",
        "tests_validation_plan": "pytest tests/test_position_matching.py; python scripts/rebuild_outputs.py --returns; python scripts/rebuild_outputs.py --validate-rules",
        "requires_human_merge": True,
        "missing_evidence": "",
        "residual_risk": "Residual ambiguity remains for rows without rate or maturity.",
        "reviewer_notes": "Rule proposal only; production edges remain deterministic.",
    }


def test_build_worklist_prioritizes_interior_high_fv_clusters_and_stable_ids(tmp_path):
    residuals = tmp_path / "position_match_residuals.csv"
    coverage = tmp_path / "position_match_coverage.csv"
    unmatched = tmp_path / "position_match_unmatched_summary.csv"
    holdings = tmp_path / "private_markets_holdings.csv"
    matches = tmp_path / "position_matches.csv"
    edges = tmp_path / "position_id_edges.csv"
    out = tmp_path / "position_match_review"

    _write_csv(
        residuals,
        [
            _residual(cik="1", fair_value="100"),
            _residual(cik="1", fair_value="25"),
            _residual(cik="2", issuer_name="Borrower B", fair_value="500", residual_bucket="likely_new_or_exit"),
        ],
    )
    _write_csv(
        coverage,
        [
            {
                "source": "bdc",
                "quarter": "2025q2",
                "cik": "0000000001",
                "index_classification": "DIRECT_LENDING",
                "any_span_row_match_rate": "0.6",
                "short_span_row_match_rate": "0.4",
                "any_span_fv_match_rate": "0.7",
                "short_span_fv_match_rate": "0.3",
            }
        ],
    )
    _write_csv(unmatched, [{"source": "bdc", "quarter": "2025q2", "cik": "0000000001", "index_classification": "DIRECT_LENDING", "unmatched_rows": "2", "unmatched_fv": "125"}])
    _write_csv(
        holdings,
        [
            {"source": "bdc", "cik": "1", "report_date": "2025-03-31", "index_classification": "DIRECT_LENDING", "issuer_name": "Borrower A, First Lien", "fair_value": "90"},
            {"source": "bdc", "cik": "1", "report_date": "2025-06-30", "index_classification": "DIRECT_LENDING", "issuer_name": "Borrower A, First Lien", "fair_value": "100"},
            {"source": "bdc", "cik": "1", "report_date": "2025-09-30", "index_classification": "DIRECT_LENDING", "issuer_name": "Borrower A, First Lien", "fair_value": "110"},
            {"source": "bdc", "cik": "2", "report_date": "2025-06-30", "index_classification": "DIRECT_LENDING", "issuer_name": "Borrower B", "fair_value": "500"},
        ],
    )
    _write_csv(matches, [{"source": "bdc", "cik": "1", "index_classification": "DIRECT_LENDING", "end_report_date": "2025-06-30"}])
    _write_csv(edges, [{"source": "bdc", "cik": "1", "end_report_date": "2025-06-30"}])

    stats = review.build_worklist(
        residuals_path=residuals,
        coverage_path=coverage,
        unmatched_summary_path=unmatched,
        holdings_path=holdings,
        matches_path=matches,
        edges_path=edges,
        output_dir=out,
        top_n=10,
        batch_size=1,
    )

    rows = _read_csv(out / "worklist.csv")
    assert stats["worklist_count"] == 2
    assert rows[0]["cik"] == "0000000001"
    assert rows[0]["unmatched_rows"] == "2"
    assert rows[0]["unmatched_fv"] == "125.000000"
    assert rows[0]["is_interior_cluster"] == "True"
    assert rows[0]["short_span_priority"] == "True"
    assert rows[0]["nearby_accepted_match_rows"] == "1"
    assert rows[0]["existing_edge_rows"] == "1"
    first_ids = [row["review_id"] for row in rows]

    review.build_worklist(
        residuals_path=residuals,
        coverage_path=coverage,
        unmatched_summary_path=unmatched,
        holdings_path=holdings,
        matches_path=matches,
        edges_path=edges,
        output_dir=out,
        top_n=10,
        batch_size=1,
    )
    assert [row["review_id"] for row in _read_csv(out / "worklist.csv")] == first_ids
    assert (out / "batches" / "batch_001.csv").exists()


def test_build_bundle_includes_position_matching_evidence(tmp_path, monkeypatch):
    output = tmp_path / "output"
    review_dir = output / "position_match_review"
    paths = {
        "POSITION_MATCH_RESIDUALS_FILE": output / "position_match_residuals.csv",
        "POSITION_MATCH_UNMATCHED_SUMMARY_FILE": output / "position_match_unmatched_summary.csv",
        "POSITION_MATCH_COVERAGE_FILE": output / "position_match_coverage.csv",
        "UNIFIED_HOLDINGS_FILE": output / "private_markets_holdings.csv",
        "POSITION_MATCHES_FILE": output / "position_matches.csv",
        "POSITION_ID_EDGES_FILE": output / "position_id_edges.csv",
        "BDC_HOLDINGS_FILE": output / "bdc_holdings.csv",
        "NPORT_HOLDINGS_FILE": output / "nport_holdings.csv",
    }
    for name, path in paths.items():
        monkeypatch.setattr(review.config, name, path)
    monkeypatch.setattr(review.config, "OUTPUT_DIR", output)

    _write_csv(paths["POSITION_MATCH_RESIDUALS_FILE"], [_residual(cik="1")])
    _write_csv(paths["POSITION_MATCH_UNMATCHED_SUMMARY_FILE"], [{"source": "bdc", "quarter": "2025q2", "cik": "1", "index_classification": "DIRECT_LENDING", "unmatched_rows": "1", "unmatched_fv": "100"}])
    _write_csv(paths["POSITION_MATCH_COVERAGE_FILE"], [{"source": "bdc", "quarter": "2025q2", "cik": "1", "index_classification": "DIRECT_LENDING", "short_span_fv_match_rate": "0.2"}])
    _write_csv(
        paths["UNIFIED_HOLDINGS_FILE"],
        [
            {"source": "bdc", "cik": "1", "report_date": "2025-03-31", "quarter": "2025q1", "index_classification": "DIRECT_LENDING", "issuer_name": "Borrower A, First Lien", "bdc_investment_identifier": "Borrower A, First Lien", "fair_value": "90"},
            {"source": "bdc", "cik": "1", "report_date": "2025-06-30", "quarter": "2025q2", "index_classification": "DIRECT_LENDING", "issuer_name": "Borrower A, First Lien", "bdc_investment_identifier": "Borrower A, First Lien", "fair_value": "100"},
        ],
    )
    _write_csv(paths["POSITION_MATCHES_FILE"], [{"source": "bdc", "cik": "1", "index_classification": "DIRECT_LENDING", "end_report_date": "2025-06-30"}])
    _write_csv(paths["POSITION_ID_EDGES_FILE"], [{"source": "bdc", "cik": "1", "end_report_date": "2025-06-30"}])
    _write_csv(paths["BDC_HOLDINGS_FILE"], [{"cik": "1", "report_date": "2025-06-30", "issuer_name": "Borrower A, First Lien"}])
    _write_csv(paths["NPORT_HOLDINGS_FILE"], [{"cik": "9", "report_date": "2025-06-30"}])

    review.build_worklist(
        residuals_path=paths["POSITION_MATCH_RESIDUALS_FILE"],
        coverage_path=paths["POSITION_MATCH_COVERAGE_FILE"],
        unmatched_summary_path=paths["POSITION_MATCH_UNMATCHED_SUMMARY_FILE"],
        holdings_path=paths["UNIFIED_HOLDINGS_FILE"],
        matches_path=paths["POSITION_MATCHES_FILE"],
        edges_path=paths["POSITION_ID_EDGES_FILE"],
        output_dir=review_dir,
    )
    manifest = review.build_bundles(output_dir=review_dir, overwrite=True)

    bundle = json.loads((review_dir / "bundles" / f"{manifest[0]['review_id']}.json").read_text(encoding="utf-8"))
    evidence_ids = [item["evidence_id"] for item in bundle["evidence_items"]]
    assert "match_residual_rows" in evidence_ids
    assert "prior_candidate_holdings" in evidence_ids
    assert "raw_bdc_source_rows" in evidence_ids
    assert "html_artifact" in evidence_ids
    assert len(evidence_ids) == len(set(evidence_ids))
    assert bundle["evidence_items"][3]["data"][0]["report_date"] == "2025-03-31"
    assert bundle["artifact_hashes"]
    html_item = next(item for item in bundle["evidence_items"] if item["evidence_id"] == "html_artifact")
    assert html_item["data"]["status"] == "missing_accession"


def test_build_bundle_skips_html_evidence_for_nport(tmp_path, monkeypatch):
    output = tmp_path / "output"
    review_dir = output / "position_match_review"
    paths = {
        "POSITION_MATCH_RESIDUALS_FILE": output / "position_match_residuals.csv",
        "POSITION_MATCH_UNMATCHED_SUMMARY_FILE": output / "position_match_unmatched_summary.csv",
        "POSITION_MATCH_COVERAGE_FILE": output / "position_match_coverage.csv",
        "UNIFIED_HOLDINGS_FILE": output / "private_markets_holdings.csv",
        "POSITION_MATCHES_FILE": output / "position_matches.csv",
        "POSITION_ID_EDGES_FILE": output / "position_id_edges.csv",
        "BDC_HOLDINGS_FILE": output / "bdc_holdings.csv",
        "NPORT_HOLDINGS_FILE": output / "nport_holdings.csv",
    }
    for name, path in paths.items():
        monkeypatch.setattr(review.config, name, path)
    monkeypatch.setattr(review.config, "OUTPUT_DIR", output)

    _write_csv(paths["POSITION_MATCH_RESIDUALS_FILE"], [_residual(source="nport", cik="9")])
    _write_csv(paths["POSITION_MATCH_UNMATCHED_SUMMARY_FILE"], [{"source": "nport", "quarter": "2025q2", "cik": "9", "index_classification": "DIRECT_LENDING"}])
    _write_csv(paths["POSITION_MATCH_COVERAGE_FILE"], [{"source": "nport", "quarter": "2025q2", "cik": "9", "index_classification": "DIRECT_LENDING"}])
    _write_csv(paths["UNIFIED_HOLDINGS_FILE"], [{"source": "nport", "cik": "9", "report_date": "2025-06-30", "quarter": "2025q2", "index_classification": "DIRECT_LENDING", "issuer_name": "Borrower A, First Lien"}])
    _write_csv(paths["POSITION_MATCHES_FILE"], [{"source": "nport", "cik": "9", "index_classification": "DIRECT_LENDING", "end_report_date": "2025-06-30"}])
    _write_csv(paths["POSITION_ID_EDGES_FILE"], [{"source": "nport", "cik": "9", "end_report_date": "2025-06-30"}])
    _write_csv(paths["BDC_HOLDINGS_FILE"], [{"cik": "1", "report_date": "2025-06-30"}])
    _write_csv(paths["NPORT_HOLDINGS_FILE"], [{"cik": "9", "report_date": "2025-06-30", "issuer_name": "Borrower A, First Lien"}])

    review.build_worklist(
        residuals_path=paths["POSITION_MATCH_RESIDUALS_FILE"],
        coverage_path=paths["POSITION_MATCH_COVERAGE_FILE"],
        unmatched_summary_path=paths["POSITION_MATCH_UNMATCHED_SUMMARY_FILE"],
        holdings_path=paths["UNIFIED_HOLDINGS_FILE"],
        matches_path=paths["POSITION_MATCHES_FILE"],
        edges_path=paths["POSITION_ID_EDGES_FILE"],
        output_dir=review_dir,
    )
    manifest = review.build_bundles(output_dir=review_dir, overwrite=True)
    bundle = json.loads((review_dir / "bundles" / f"{manifest[0]['review_id']}.json").read_text(encoding="utf-8"))

    evidence_ids = [item["evidence_id"] for item in bundle["evidence_items"]]
    assert "raw_nport_source_rows" in evidence_ids
    assert "html_artifact" not in evidence_ids


def test_validate_verdict_rejects_unsafe_rule_proposals(tmp_path):
    output = tmp_path / "review"
    (output / "bundles").mkdir(parents=True)
    (output / "verdicts").mkdir(parents=True)
    review_id = "POSMATCH_BDC_0000000001_2025q2_DIRECT_LENDING_BUCKET_abc"
    bundle = {
        "review_id": review_id,
        "source": "bdc",
        "cik": "0000000001",
        "quarter": "2025q2",
        "index_classification": "DIRECT_LENDING",
        "evidence_items": [{"evidence_id": "worklist_row"}],
    }
    (output / "bundles" / f"{review_id}.json").write_text(json.dumps(bundle), encoding="utf-8")
    verdict = _valid_verdict(review_id)
    verdict.update(
        {
            "primary_justification": "Coverage would improve",
            "evidence_refs": ["unknown"],
            "changed_files": ["data/output/position_matches.csv"],
            "false_positive_examples": [],
            "guardrails": "Use borrower name only.",
            "requires_human_merge": False,
        }
    )
    verdict_path = output / "verdicts" / f"{review_id}.json"
    verdict_path.write_text(json.dumps(verdict), encoding="utf-8")

    errors = review.validate_verdict_file(verdict_path, output)

    assert any("unknown evidence_ref" in error for error in errors)
    assert any("coverage" in error.lower() for error in errors)
    assert any("protected generated-output" in error for error in errors)
    assert any("requires requires_human_merge=true" in error for error in errors)
    assert any("requires false_positive_examples" in error for error in errors)
    assert any("one_to_one guardrails" in error for error in errors)


def test_validate_accepts_rule_and_summary_writes_dry_run_evaluation(tmp_path):
    output = tmp_path / "review"
    (output / "bundles").mkdir(parents=True)
    (output / "verdicts").mkdir(parents=True)
    review_id = "POSMATCH_BDC_0000000001_2025q2_DIRECT_LENDING_BUCKET_abc"
    _write_csv(
        output / "worklist.csv",
        [
            {
                "review_id": review_id,
                "source": "bdc",
                "cik": "0000000001",
                "quarter": "2025q2",
                "index_classification": "DIRECT_LENDING",
                "residual_bucket": "same_issuer_existed_unmatched",
                "unmatched_rows": "1",
                "unmatched_fv": "100",
                "coverage_short_span_fv_rate": "0.2",
                "coverage_any_span_fv_rate": "0.4",
            }
        ],
    )
    (output / "bundles" / f"{review_id}.json").write_text(
        json.dumps(
            {
                "review_id": review_id,
                "source": "bdc",
                "cik": "0000000001",
                "quarter": "2025q2",
                "index_classification": "DIRECT_LENDING",
                "evidence_items": [
                    {"evidence_id": "worklist_row"},
                    {"evidence_id": "match_residual_rows"},
                    {"evidence_id": "prior_candidate_holdings"},
                ],
            }
        ),
        encoding="utf-8",
    )
    (output / "verdicts" / f"{review_id}.json").write_text(json.dumps(_valid_verdict(review_id)), encoding="utf-8")

    assert review.validate_all_verdicts(output) == []
    summary = review.summarize_verdicts(output)

    assert summary["counts"] == {"RULE_PROPOSED": 1}
    rows = _read_csv(output / "summary.csv")
    assert rows[0]["rule_type"] == "tranche_key"
    eval_rows = _read_csv(output / "dry_run_evaluation.csv")
    assert eval_rows[0]["proposed_candidate_edges"] == "1"
    assert eval_rows[0]["rejected_ambiguous_candidates"] == "1"
    assert (output / "summary.md").exists()


def test_validate_accepts_insufficient_evidence_with_missing_evidence(tmp_path):
    output = tmp_path / "review"
    (output / "bundles").mkdir(parents=True)
    (output / "verdicts").mkdir(parents=True)
    review_id = "POSMATCH_BDC_0000000001_2025q2_DIRECT_LENDING_BUCKET_abc"
    (output / "worklist.csv").write_text(
        "review_id,source,cik,quarter,index_classification,residual_bucket,unmatched_fv\n"
        f"{review_id},bdc,0000000001,2025q2,DIRECT_LENDING,same_issuer_existed_unmatched,100\n",
        encoding="utf-8",
    )
    (output / "bundles" / f"{review_id}.json").write_text(
        json.dumps({"review_id": review_id, "source": "bdc", "cik": "0000000001", "quarter": "2025q2", "index_classification": "DIRECT_LENDING", "evidence_items": [{"evidence_id": "worklist_row"}]}),
        encoding="utf-8",
    )
    verdict = {
        "review_id": review_id,
        "source": "bdc",
        "cik": "0000000001",
        "quarter": "2025q2",
        "index_classification": "DIRECT_LENDING",
        "verdict": "INSUFFICIENT_EVIDENCE",
        "confidence": "LOW",
        "primary_justification": "Identity evidence is ambiguous across tranches.",
        "evidence_refs": ["worklist_row"],
        "changed_files": [],
        "rule_scope": "",
        "rule_type": "",
        "rule_summary": "",
        "deterministic_conditions": "",
        "positive_examples": [],
        "false_positive_examples": [],
        "guardrails": "",
        "expected_coverage_effect": "",
        "false_match_risk": "",
        "tests_validation_plan": "",
        "requires_human_merge": False,
        "missing_evidence": "Need raw schedule detail showing tranche-level identifiers.",
        "residual_risk": "Do not force a borrower-level rule.",
        "reviewer_notes": "Escalate after bounded review.",
    }
    (output / "verdicts" / f"{review_id}.json").write_text(json.dumps(verdict), encoding="utf-8")

    assert review.validate_all_verdicts(output) == []


def test_validate_rejects_free_text_html_refs_without_coordinates(tmp_path):
    output = tmp_path / "review"
    (output / "bundles").mkdir(parents=True)
    (output / "verdicts").mkdir(parents=True)
    review_id = "POSMATCH_BDC_0000000001_2025q2_DIRECT_LENDING_BUCKET_abc"
    (output / "bundles" / f"{review_id}.json").write_text(
        json.dumps(
            {
                "review_id": review_id,
                "source": "bdc",
                "cik": "0000000001",
                "quarter": "2025q2",
                "index_classification": "DIRECT_LENDING",
                "evidence_items": [{"evidence_id": "html_table_grid_excerpt"}],
            }
        ),
        encoding="utf-8",
    )
    verdict = _valid_verdict(review_id)
    verdict["evidence_refs"] = ["html_table_grid_excerpt"]
    verdict["positive_examples"] = [{"evidence_ref": "html_table_grid_excerpt", "reason": "free-text hit only"}]
    verdict_path = output / "verdicts" / f"{review_id}.json"
    verdict_path.write_text(json.dumps(verdict), encoding="utf-8")

    errors = review.validate_verdict_file(verdict_path, output)

    assert any("requires table_index,row_index,cell_indices" in error for error in errors)
    assert any("positive_examples[0] HTML citation requires" in error for error in errors)


def test_validate_accepts_html_coordinates_for_unclassifiable_missing_evidence(tmp_path):
    output = tmp_path / "review"
    (output / "bundles").mkdir(parents=True)
    (output / "verdicts").mkdir(parents=True)
    review_id = "POSMATCH_BDC_0000000001_2025q2_DIRECT_LENDING_BUCKET_abc"
    _write_csv(output / "worklist.csv", [{"review_id": review_id, "source": "bdc", "cik": "0000000001", "quarter": "2025q2", "index_classification": "DIRECT_LENDING", "residual_bucket": "bucket", "unmatched_fv": "100"}])
    (output / "bundles" / f"{review_id}.json").write_text(
        json.dumps(
            {
                "review_id": review_id,
                "source": "bdc",
                "cik": "0000000001",
                "quarter": "2025q2",
                "index_classification": "DIRECT_LENDING",
                "evidence_items": [{"evidence_id": "html_row_classification_candidates"}],
            }
        ),
        encoding="utf-8",
    )
    verdict = {
        "review_id": review_id,
        "source": "bdc",
        "cik": "0000000001",
        "quarter": "2025q2",
        "index_classification": "DIRECT_LENDING",
        "verdict": "INSUFFICIENT_EVIDENCE",
        "confidence": "LOW",
        "primary_justification": "HTML row is unclassifiable from cached coordinates.",
        "evidence_refs": ["html_row_classification_candidates"],
        "html_citations": [{"evidence_ref": "html_row_classification_candidates", "table_index": 0, "row_index": 2, "cell_indices": [0], "reason": "UNCLASSIFIABLE row lacks source identifiers."}],
        "changed_files": [],
        "rule_scope": "",
        "rule_type": "",
        "rule_summary": "",
        "deterministic_conditions": "",
        "positive_examples": [],
        "false_positive_examples": [],
        "guardrails": "",
        "expected_coverage_effect": "",
        "false_match_risk": "",
        "tests_validation_plan": "",
        "requires_human_merge": False,
        "missing_evidence": "Need clearer source filing coordinates or audited template selection.",
        "residual_risk": "No deterministic merge should be proposed.",
        "reviewer_notes": "Coordinates support abstention.",
    }
    (output / "verdicts" / f"{review_id}.json").write_text(json.dumps(verdict), encoding="utf-8")

    assert review.validate_all_verdicts(output) == []
