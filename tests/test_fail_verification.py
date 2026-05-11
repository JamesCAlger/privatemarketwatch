import csv
import json
import shutil
from pathlib import Path

import pytest

from pipeline import fail_verification as fv


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


@pytest.fixture()
def fail_output_dir(monkeypatch):
    base = fv.PROJECT_ROOT / "data" / "output" / "_fail_verification_pytest"
    if base.exists():
        shutil.rmtree(base)
    out = base / "output"
    rows = [
        {
            "dataset": "private_markets_holdings",
            "source": "bdc",
            "cik": "1",
            "report_date": "2025-03-31",
            "row_key": "0",
            "column": "fair_value",
            "rule_id": "C101",
            "severity": "FAIL",
            "evidence_strength": "STRONG",
            "status": "OPEN",
            "action": "EXCLUDE_FROM_INDEX",
            "value": "",
            "message": "fair_value is missing on an indexable row",
            "evidence": "index returns require fair_value",
        },
        {
            "dataset": "private_markets_holdings",
            "source": "bdc",
            "cik": "1",
            "report_date": "2025-03-31",
            "row_key": "1",
            "column": "principal_amount",
            "rule_id": "X06",
            "severity": "FAIL",
            "evidence_strength": "MODERATE",
            "status": "OPEN",
            "action": "REVIEW",
            "value": "20000",
            "message": "principal_amount is more than 10x fair_value",
            "evidence": "likely scale error",
        },
        {
            "dataset": "private_markets_holdings",
            "source": "bdc",
            "cik": "1",
            "report_date": "2025-03-31",
            "row_key": "2",
            "column": "pct_of_net_assets",
            "rule_id": "X09",
            "severity": "FAIL",
            "evidence_strength": "MODERATE",
            "status": "OPEN",
            "action": "BLOCK_VERIFIED",
            "value": "101",
            "message": "pct_of_net_assets exceeds 100 percentage points",
            "evidence": "denominator artifact",
        },
        {
            "dataset": "private_markets_holdings",
            "source": "bdc",
            "cik": "2",
            "report_date": "2025-06-30",
            "row_key": "3",
            "column": "maturity_date",
            "rule_id": "C402",
            "severity": "FAIL",
            "evidence_strength": "STRONG",
            "status": "OPEN",
            "action": "REVIEW",
            "value": "0025-06-30",
            "message": "maturity_date year is before 1900",
            "evidence": "date parsing error",
        },
        {
            "dataset": "private_markets_holdings",
            "source": "bdc",
            "cik": "3",
            "report_date": "2025-09-30",
            "row_key": "",
            "column": "fair_value",
            "rule_id": "GAV_BDC01",
            "severity": "FAIL",
            "evidence_strength": "STRONG",
            "status": "OPEN",
            "action": "BLOCK_VERIFIED",
            "value": "0.1",
            "message": "BDC GAV reconciliation ratio is extreme",
            "evidence": "comparison_source=companyfacts",
        },
        {
            "dataset": "private_markets_holdings",
            "source": "bdc",
            "cik": "3",
            "report_date": "2025-09-30",
            "row_key": "",
            "column": "fair_value",
            "rule_id": "GAV_BDC01",
            "severity": "FAIL",
            "evidence_strength": "STRONG",
            "status": "OPEN",
            "action": "BLOCK_VERIFIED",
            "value": "0.1",
            "message": "duplicate GAV row for same unit",
            "evidence": "comparison_source=companyfacts",
        },
        {
            "dataset": "private_markets_holdings",
            "source": "bdc",
            "cik": "4",
            "report_date": "2025-03-31",
            "row_key": "4",
            "column": "fair_value",
            "rule_id": "C101",
            "severity": "WARN",
            "evidence_strength": "STRONG",
            "status": "OPEN",
            "action": "REVIEW",
            "value": "",
            "message": "not in scope",
            "evidence": "",
        },
        {
            "dataset": "private_markets_holdings",
            "source": "bdc",
            "cik": "3",
            "report_date": "2025-09-30",
            "row_key": "5",
            "column": "fair_value",
            "rule_id": "C101",
            "severity": "FAIL",
            "evidence_strength": "STRONG",
            "status": "OPEN",
            "action": "EXCLUDE_FROM_INDEX",
            "value": "",
            "message": "fair_value is missing on an indexable row",
            "evidence": "row-level fail for GAV context",
        },
    ]
    _write_csv(out / "row_validation_issues.csv", rows)
    _write_csv(out / "private_markets_holdings.csv", [
        {
            "source": "bdc",
            "cik": "0000000001",
            "report_date": "2025-03-31",
            "accession_number": "acc1",
            "issuer_name": "Issuer A",
            "fair_value": "",
            "principal_amount": "",
            "pct_of_net_assets": "",
            "bdc_investment_identifier": "Issuer A - Term Loan",
            "position_id": "p0",
            "index_classification": "DIRECT_LENDING",
        },
        {
            "source": "bdc",
            "cik": "0000000001",
            "report_date": "2025-03-31",
            "accession_number": "acc1",
            "issuer_name": "Issuer B",
            "fair_value": "1000",
            "principal_amount": "20000",
            "pct_of_net_assets": "",
            "bdc_investment_identifier": "Issuer B - Revolver",
            "position_id": "p1",
            "index_classification": "DIRECT_LENDING",
        },
        {
            "source": "bdc",
            "cik": "0000000001",
            "report_date": "2025-03-31",
            "accession_number": "acc1",
            "issuer_name": "Issuer C",
            "fair_value": "1000",
            "principal_amount": "",
            "pct_of_net_assets": "101",
            "bdc_investment_identifier": "Issuer C - Loan",
            "bdc_dimensions_raw": "InvestmentIdentifierAxis=IssuerCMember",
            "position_id": "p2",
            "index_classification": "DIRECT_LENDING",
        },
        {
            "source": "bdc",
            "cik": "0000000002",
            "report_date": "2025-06-30",
            "accession_number": "acc2",
            "issuer_name": "Issuer D",
            "fair_value": "10",
            "principal_amount": "100",
            "pct_of_net_assets": "",
            "maturity_date": "0025-06-30",
            "bdc_investment_identifier": "Issuer D - Loan",
            "position_id": "p3",
            "index_classification": "DIRECT_LENDING",
        },
        {
            "source": "bdc",
            "cik": "0000000001",
            "report_date": "2025-03-31",
            "accession_number": "acc1",
            "issuer_name": "Issuer C",
            "fair_value": "1000",
            "principal_amount": "",
            "pct_of_net_assets": "101",
            "bdc_investment_identifier": "Issuer C - Loan",
            "bdc_dimensions_raw": "InvestmentIdentifierAxis=IssuerCDuplicateMember",
            "position_id": "p4",
            "index_classification": "DIRECT_LENDING",
        },
        {
            "source": "bdc",
            "cik": "0000000003",
            "report_date": "2025-09-30",
            "accession_number": "acc3",
            "issuer_name": "Issuer G",
            "fair_value": "",
            "principal_amount": "",
            "pct_of_net_assets": "",
            "bdc_investment_identifier": "Issuer G - Loan",
            "position_id": "p5",
            "index_classification": "DIRECT_LENDING",
        },
    ])
    _write_csv(out / "bdc_holdings.csv", [
        {
            "cik": "0000000001",
            "accession_number": "acc1",
            "report_date": "2025-03-31",
            "investment_identifier": "Non-control/non-affiliate investments - Issuer A - Term Loan",
            "fair_value": "",
            "principal_amount": "",
            "maturity_date": "",
        },
        {
            "cik": "0000000001",
            "accession_number": "acc1",
            "report_date": "2025-03-31",
            "investment_identifier": "Affiliate investments - Issuer A - Term Loan",
            "fair_value": "0",
            "principal_amount": "",
            "maturity_date": "",
        },
        {
            "cik": "0000000001",
            "accession_number": "acc1",
            "report_date": "2025-03-31",
            "investment_identifier": "Affiliate investments - 7.5% - Issuer A - Term Loan",
            "fair_value": "1",
            "principal_amount": "",
            "maturity_date": "",
        },
        {
            "cik": "0000000001",
            "accession_number": "acc1",
            "report_date": "2025-03-31",
            "investment_identifier": "Issuer B - Revolver",
            "fair_value": "1000",
            "principal_amount": "20000",
            "maturity_date": "",
        }
    ])
    _write_csv(out / "nport_holdings.csv", [{"cik": "0000000009", "report_date": "2025-03-31"}])
    _write_csv(out / "fund_financials.csv", [
        {
            "cik": "0000000001",
            "report_date": "2025-03-31",
            "total_assets": "100000",
            "net_assets": "90000",
            "leverage_ratio": "1.1",
        }
    ])
    _write_csv(out / "holdings_gav_reconciliation.csv", [
        {
            "cik": "0000000003",
            "report_date": "2025-09-30",
            "sum_holdings_fv": "100",
            "comparison_value": "1000",
            "comparison_source": "companyfacts",
            "gav_ratio": "0.1",
            "gav_ratio_adjusted": "0.1",
        }
    ])
    _write_csv(out / "holdings_pct_sum.csv", [
        {"cik": "0000000001", "report_date": "2025-03-31", "pct_sum": "202"}
    ])
    _write_csv(out / "holdings_count_stability.csv", [
        {"cik": "0000000003", "report_date": "2025-09-30", "position_count": "2"}
    ])
    _write_csv(out / "bdc_filings_index.csv", [
        {"cik": "0000000003", "report_date": "2025-09-30", "accession_number": "acc3"}
    ])

    def write_guard(output_dir):
        guard = {
            "schema_version": "1.0",
            "created_at": "2026-05-11T00:00:00+00:00",
            "protected_hashes": {},
            "allowed_write_dir": "data/output/fail_verification/verdicts",
        }
        path = output_dir / "fail_verification" / "run_guard.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(guard), encoding="utf-8")

    monkeypatch.setattr(fv, "_write_run_guard", write_guard)
    yield out
    if base.exists():
        shutil.rmtree(base)


def test_build_sample_manifest_filters_and_dedupes_gav(fail_output_dir):
    path = fv.build_sample_manifest(output_dir=fail_output_dir, seed=123)
    rows = _read_csv(path)

    assert [row["rule_id"] for row in rows].count("GAV_BDC01") == 1
    assert {row["rule_id"] for row in rows} == {"C101", "X06", "X09", "C402", "GAV_BDC01"}
    assert "severity" not in rows[0]  # manifest is identity, not issue copy
    assert all(row["cik"].startswith("000000000") for row in rows)
    assert {row["sampling_unit"] for row in rows if row["rule_id"] == "GAV_BDC01"} == {"cik_quarter"}
    assert {row["sampling_unit"] for row in rows if row["rule_id"] != "GAV_BDC01"} == {"issue_row"}


def test_build_evidence_bundle_contains_rule_specific_evidence(fail_output_dir):
    manifest_path = fv.build_sample_manifest(output_dir=fail_output_dir, seed=123)
    manifest = _read_csv(manifest_path)
    verification_id = next(row["verification_id"] for row in manifest if row["rule_id"] == "X09")

    bundle_path = fv.build_evidence_bundle(verification_id, output_dir=fail_output_dir)
    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    evidence_ids = {item["evidence_id"] for item in bundle["evidence_items"]}

    assert bundle["bundle_id"] == verification_id
    assert "holdings_row" in evidence_ids
    assert "pct_sum" in evidence_ids
    assert "same_issuer_dimension_rows" in evidence_ids
    assert bundle["sample_manifest_row"]["rule_id"] == "X09"

    dimension_rows = next(
        item["data"] for item in bundle["evidence_items"]
        if item["evidence_id"] == "same_issuer_dimension_rows"
    )
    assert len(dimension_rows) == 2


def test_build_evidence_bundle_matches_prefixed_bdc_raw_rows(fail_output_dir):
    manifest_path = fv.build_sample_manifest(output_dir=fail_output_dir, seed=123)
    manifest = _read_csv(manifest_path)
    verification_id = next(
        row["verification_id"] for row in manifest
        if row["rule_id"] == "C101" and row["cik"] == "0000000001"
    )

    bundle_path = fv.build_evidence_bundle(verification_id, output_dir=fail_output_dir)
    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    evidence = {item["evidence_id"]: item["data"] for item in bundle["evidence_items"]}

    assert len(evidence["raw_source_rows"]) == 3
    assert {
        row["investment_identifier"] for row in evidence["raw_source_rows"]
    } == {
        "Non-control/non-affiliate investments - Issuer A - Term Loan",
        "Affiliate investments - Issuer A - Term Loan",
        "Affiliate investments - 7.5% - Issuer A - Term Loan",
    }
    assert evidence["raw_source_match_diagnostics"]["match_method"] == "normalized_identifier_with_related_candidates"
    assert evidence["raw_source_match_diagnostics"]["exact_match_count"] == 0
    assert evidence["raw_source_match_diagnostics"]["normalized_match_count"] == 2
    assert evidence["raw_source_match_diagnostics"]["related_candidate_count"] == 1


def test_build_evidence_bundle_adds_gav_row_level_examples(fail_output_dir):
    manifest_path = fv.build_sample_manifest(output_dir=fail_output_dir, seed=123)
    manifest = _read_csv(manifest_path)
    verification_id = next(row["verification_id"] for row in manifest if row["rule_id"] == "GAV_BDC01")

    bundle_path = fv.build_evidence_bundle(verification_id, output_dir=fail_output_dir)
    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    evidence = {item["evidence_id"]: item["data"] for item in bundle["evidence_items"]}

    assert evidence["related_row_fail_examples"][0]["rule_id"] == "C101"
    assert evidence["gav_holdings_examples"][0]["issuer_name"] == "Issuer G"


def _valid_verdict(bundle_path: Path, manifest_row: dict[str, str]) -> dict:
    bundle_sha = fv.sha256_file(bundle_path)
    return {
        "schema_version": "1.0",
        "verification_id": manifest_row["verification_id"],
        "bundle_id": manifest_row["verification_id"],
        "bundle_sha256": bundle_sha,
        "created_at": "2026-05-11T00:00:00+00:00",
        "rule_id": manifest_row["rule_id"],
        "cik": manifest_row["cik"],
        "report_date": manifest_row["report_date"],
        "row_key": manifest_row["row_key"],
        "verdict": "CONFIRMED_DATA_ERROR",
        "confidence": "high",
        "mechanism": "Raw and unified evidence show an unsafe validation failure.",
        "epistemic_assessment": {
            "confirmed_mechanism": {
                "summary": "The sampled output row is unsafe because the validation issue is corroborated by the holdings row.",
                "support_strength": "DETERMINISTIC_RECONCILIATION",
                "evidence_refs": ["holdings_row", "issue_rows"],
            },
            "evidence_chain": [
                {
                    "claim": "The validation issue identifies the sampled rule failure.",
                    "evidence_id": "issue_rows",
                    "supports": "The issue row carries the C101 failure for this row.",
                },
                {
                    "claim": "The holdings row corroborates the unsafe output.",
                    "evidence_id": "holdings_row",
                    "supports": "The sampled holdings row has the relevant unsafe field state.",
                },
            ],
            "ruled_out_alternatives": [
                {
                    "alternative": "Validator identity mismatch",
                    "evidence_id": "holdings_row",
                    "reason": "The manifest row and holdings row refer to the same sampled row.",
                }
            ],
            "missing_evidence": [],
        },
        "validator_assessment": {
            "rule_condition_true": True,
            "validator_correct": True,
            "material_risk_real": True,
            "root_cause": "EXTRACTION_GAP",
        },
        "determination_rationale": {
            "why_this_verdict": "The evidence supports the validation condition.",
            "why_not_alternative": "A valid exception is not supported by the bundle.",
            "residual_uncertainty": "Limited to the source rows included in this bundle.",
        },
        "evidence_refs": [
            {"evidence_id": "holdings_row", "supports": "Shows the sampled output row."},
            {"evidence_id": "issue_rows", "supports": "Shows the validation rule failure."},
        ],
        "recommended_next_action": {
            "action_type": "PIPELINE_REMEDIATION_REVIEW",
            "summary": "Review the extraction mechanism in a later remediation pass.",
        },
        "agent_notes": "",
        "anti_sycophancy_check": "A source exception was considered but was not supported by the evidence.",
    }


def test_validate_verdict_accepts_matching_verdict(fail_output_dir):
    manifest_path = fv.build_sample_manifest(output_dir=fail_output_dir, seed=123)
    manifest_row = next(row for row in _read_csv(manifest_path) if row["rule_id"] == "C101")
    bundle_path = fv.build_evidence_bundle(manifest_row["verification_id"], output_dir=fail_output_dir)
    verdict = _valid_verdict(bundle_path, manifest_row)
    verdict_path = fail_output_dir / "fail_verification" / "verdicts" / f"{manifest_row['verification_id']}.json"
    verdict_path.parent.mkdir(parents=True, exist_ok=True)
    verdict_path.write_text(json.dumps(verdict), encoding="utf-8")

    assert fv.validate_verdict(verdict_path, output_dir=fail_output_dir) == []


def test_validate_verdict_reuses_run_guard_validation(fail_output_dir, monkeypatch):
    manifest_path = fv.build_sample_manifest(output_dir=fail_output_dir, seed=123)
    manifest_row = next(row for row in _read_csv(manifest_path) if row["rule_id"] == "C101")
    bundle_path = fv.build_evidence_bundle(manifest_row["verification_id"], output_dir=fail_output_dir)
    verdict_path = fail_output_dir / "fail_verification" / "verdicts" / f"{manifest_row['verification_id']}.json"
    verdict_path.parent.mkdir(parents=True, exist_ok=True)
    verdict_path.write_text(json.dumps(_valid_verdict(bundle_path, manifest_row)), encoding="utf-8")

    calls = []

    def validate_once(output_dir):
        calls.append(output_dir)
        return []

    monkeypatch.setattr(fv, "_validate_run_guard", validate_once)
    guard = fv.RunGuardValidator(fail_output_dir)

    assert fv.validate_verdict(verdict_path, output_dir=fail_output_dir, run_guard_validator=guard) == []
    assert fv.validate_verdict(verdict_path, output_dir=fail_output_dir, run_guard_validator=guard) == []
    assert calls == [fail_output_dir]


def test_validate_verdict_rejects_missing_evidence_and_mutation_recommendation(fail_output_dir):
    manifest_path = fv.build_sample_manifest(output_dir=fail_output_dir, seed=123)
    manifest_row = next(row for row in _read_csv(manifest_path) if row["rule_id"] == "C101")
    bundle_path = fv.build_evidence_bundle(manifest_row["verification_id"], output_dir=fail_output_dir)
    verdict = _valid_verdict(bundle_path, manifest_row)
    verdict["evidence_refs"][0]["evidence_id"] = "missing"
    verdict["recommended_next_action"]["summary"] = "Edit pipeline code now"
    verdict_path = fail_output_dir / "fail_verification" / "verdicts" / f"{manifest_row['verification_id']}.json"
    verdict_path.parent.mkdir(parents=True, exist_ok=True)
    verdict_path.write_text(json.dumps(verdict), encoding="utf-8")

    errors = fv.validate_verdict(verdict_path, output_dir=fail_output_dir)

    assert any("unknown evidence_id" in error for error in errors)
    assert any("direct mutation" in error for error in errors)


def test_validate_verdict_rejects_positive_verdict_without_positive_mechanism(fail_output_dir):
    manifest_path = fv.build_sample_manifest(output_dir=fail_output_dir, seed=123)
    manifest_row = next(row for row in _read_csv(manifest_path) if row["rule_id"] == "X06")
    bundle_path = fv.build_evidence_bundle(manifest_row["verification_id"], output_dir=fail_output_dir)
    verdict = _valid_verdict(bundle_path, manifest_row)
    verdict["rule_id"] = "X06"
    verdict["verdict"] = "CONFIRMED_VALID_EXCEPTION"
    verdict["confidence"] = "medium"
    verdict["mechanism"] = "Same-filing context does not prove a broad scale mismatch."
    verdict["validator_assessment"]["material_risk_real"] = False
    verdict["validator_assessment"]["root_cause"] = "VALID_SOURCE_EXCEPTION"
    verdict["epistemic_assessment"] = {
        "confirmed_mechanism": {
            "summary": "No positive exception mechanism was confirmed.",
            "support_strength": "ABSENCE_OF_CONTRARY_EVIDENCE",
            "evidence_refs": ["nearby_holdings"],
        },
        "evidence_chain": [
            {
                "claim": "Nearby rows do not prove a broad filing-level scale mismatch.",
                "evidence_id": "nearby_holdings",
                "supports": "Only some rows have high ratios.",
            }
        ],
        "ruled_out_alternatives": [
            {
                "alternative": "Filing-wide scale mismatch",
                "evidence_id": "nearby_holdings",
                "reason": "The nearby rows are mixed rather than uniformly high-ratio.",
            }
        ],
        "missing_evidence": ["Source narrative or instrument evidence confirming distress, default, revolver, delayed draw, or unfunded commitment treatment."],
    }
    verdict_path = fail_output_dir / "fail_verification" / "verdicts" / f"{manifest_row['verification_id']}.json"
    verdict_path.parent.mkdir(parents=True, exist_ok=True)
    verdict_path.write_text(json.dumps(verdict), encoding="utf-8")

    errors = fv.validate_verdict(verdict_path, output_dir=fail_output_dir)

    assert any("absence of contrary evidence" in error for error in errors)


def test_summarize_verdicts_writes_counts(fail_output_dir):
    manifest_path = fv.build_sample_manifest(output_dir=fail_output_dir, seed=123)
    manifest_row = next(row for row in _read_csv(manifest_path) if row["rule_id"] == "C101")
    bundle_path = fv.build_evidence_bundle(manifest_row["verification_id"], output_dir=fail_output_dir)
    verdict_path = fail_output_dir / "fail_verification" / "verdicts" / f"{manifest_row['verification_id']}.json"
    verdict_path.parent.mkdir(parents=True, exist_ok=True)
    verdict_path.write_text(json.dumps(_valid_verdict(bundle_path, manifest_row)), encoding="utf-8")

    summary_path = fv.summarize_verdicts(output_dir=fail_output_dir)
    rows = _read_csv(summary_path)

    assert rows == [
        {
            "rule_id": "C101",
            "verdict": "CONFIRMED_DATA_ERROR",
            "count": "1",
            "weighted_count": "1",
            "affected_fair_value": "0.00",
        }
    ]
