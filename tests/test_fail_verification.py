import csv
import json
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


def _append_csv(path: Path, rows: list[dict[str, str]]) -> None:
    existing = _read_csv(path) if path.exists() else []
    _write_csv(path, existing + rows)


def _write_single_fund_manifest(output_dir: Path, rule_id: str, cik: str = "0000000005", report_date: str = "2025-03-31") -> dict[str, str]:
    verification_id = f"{rule_id}_{cik}_{report_date}_pytest"
    row = {
        "dataset": "fund_financials",
        "verification_id": verification_id,
        "rule_id": rule_id,
        "sampling_unit": "fund_period",
        "cik": cik,
        "report_date": report_date,
        "row_key": "0",
        "source": "fund_financials",
        "accession_number": "",
        "source_record_id": f"{cik}|{report_date}|{rule_id}",
        "issuer_name": "",
        "position_id": "",
        "sample_stratum": cik,
        "sample_weight": "1",
        "random_seed": "123",
        "source_file": "data/output/fund_financials_validation_current.csv",
        "source_file_sha256": "0" * 64,
        "population": "1",
        "sample_size": "1",
        "stratum_population": "1",
        "stratum_sample_size": "1",
    }
    fv.write_csv_rows(output_dir / "fail_verification" / "sample_manifest.csv", [row], fv.MANIFEST_COLUMNS)
    return row


@pytest.fixture()
def fail_output_dir(monkeypatch, tmp_path):
    out = tmp_path / "_fail_verification_pytest" / "output"
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
        {
            "source": "bdc",
            "cik": "0000000005",
            "report_date": "2025-03-31",
            "accession_number": "acc5",
            "issuer_name": "Issuer H",
            "fair_value": "40000",
            "principal_amount": "50000",
            "pct_of_net_assets": "44.4",
            "bdc_investment_identifier": "Issuer H - Loan",
            "position_id": "p6",
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
        },
        {
            "cik": "0000000005",
            "report_quarter": "2024q4",
            "report_date": "2024-12-31",
            "entity_name": "Fund Five",
            "total_assets": "95000",
            "total_liabilities": "5000",
            "net_assets": "90000",
            "investments_at_fair_value": "80000",
            "leverage_ratio": "1.05",
        },
        {
            "cik": "0000000005",
            "report_quarter": "2025q1",
            "report_date": "2025-03-31",
            "entity_name": "Fund Five",
            "total_assets": "100000",
            "total_liabilities": "15000",
            "net_assets": "90000",
            "investments_at_fair_value": "80000",
            "leverage_ratio": "1.1",
        },
        {
            "cik": "0000000006",
            "report_quarter": "2025q1",
            "report_date": "2025-03-31",
            "entity_name": "Fund Six",
            "total_assets": "100000",
            "total_liabilities": "10000",
            "net_assets": "90000",
            "investments_at_fair_value": "80000",
            "leverage_ratio": "1.1",
        },
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
        },
        {
            "cik": "0000000005",
            "report_date": "2025-03-31",
            "sum_holdings_fv": "40000",
            "comparison_value": "80000",
            "comparison_source": "fund_financials",
            "gav_ratio": "0.5",
            "gav_ratio_adjusted": "0.5",
        }
    ])
    _write_csv(out / "holdings_pct_sum.csv", [
        {"cik": "0000000001", "report_date": "2025-03-31", "pct_sum": "202"},
        {"cik": "0000000005", "report_date": "2025-03-31", "pct_sum": "44.4"},
    ])
    _write_csv(out / "holdings_count_stability.csv", [
        {"cik": "0000000003", "report_date": "2025-09-30", "position_count": "2"},
        {"cik": "0000000005", "report_date": "2025-03-31", "position_count": "1"},
    ])
    _write_csv(out / "bdc_filings_index.csv", [
        {"cik": "0000000003", "report_date": "2025-09-30", "accession_number": "acc3"}
    ])
    _write_csv(out / "fund_financials_validation_current.csv", [
        {
            "dataset": "fund_financials",
            "cik": "5",
            "report_quarter": "2025q1",
            "report_date": "2025-03-31",
            "check_code": "F10",
            "status": "FAIL",
            "severity": "FAIL",
            "evidence_strength": "STRONG",
            "value": "5000",
            "expected": "total_assets - total_liabilities = net_assets within 1%",
            "mechanism": "",
            "source_artifacts": "fund_financials.csv",
            "note": "balance sheet identity mismatch",
        },
        {
            "dataset": "fund_financials",
            "cik": "5",
            "report_quarter": "2025q1",
            "report_date": "2025-03-31",
            "check_code": "F20",
            "status": "FAIL",
            "severity": "FAIL",
            "evidence_strength": "STRONG",
            "value": "0.5",
            "expected": "0.8 <= holdings_fv / investments_at_fair_value <= 1.2",
            "mechanism": "",
            "source_artifacts": "fund_financials.csv;private_markets_holdings.csv",
            "note": "holdings FV under fund investments",
        },
        {
            "dataset": "fund_financials",
            "cik": "6",
            "report_quarter": "2025q1",
            "report_date": "2025-03-31",
            "check_code": "F28",
            "status": "FAIL",
            "severity": "FAIL",
            "evidence_strength": "MODERATE",
            "value": "has_fund=True,has_holdings=False",
            "expected": "fund_financials and holdings coverage agree",
            "mechanism": "",
            "source_artifacts": "fund_financials.csv;private_markets_holdings.csv",
            "note": "fund row with no holdings",
        },
        {
            "dataset": "fund_financials",
            "cik": "5",
            "report_quarter": "2025q1",
            "report_date": "2025-03-31",
            "check_code": "F17",
            "status": "PASS",
        },
    ])
    _write_csv(out / "fund_financials_quality_metrics.csv", [
        {
            "dataset": "fund_financials",
            "cik": "0000000005",
            "report_quarter": "2025q1",
            "report_date": "2025-03-31",
            "validation_tier": "under_review",
            "fail_count": "2",
        }
    ])
    _write_csv(out / "fund_financials_cross_level.csv", [
        {
            "dataset": "fund_financials",
            "cik": "0000000005",
            "report_quarter": "2025q1",
            "report_date": "2025-03-31",
            "check_code": "F20",
            "status": "FAIL",
            "value": "0.5",
        }
    ])
    _write_csv(out / "bdc_fund_income.csv", [
        {"cik": "0000000005", "report_date": "2025-03-31", "total_investment_income": "1000"}
    ])
    _write_csv(out / "nport_fund_info.csv", [
        {"cik": "0000000005", "report_date": "2025-03-31", "net_assets": "90000"}
    ])
    _write_csv(out / "ncsr_financials.csv", [
        {"cik": "0000000005", "report_date": "2025-03-31", "net_assets": "90000"}
    ])
    _write_csv(out / "combined_universe.csv", [
        {"cik": "0000000005", "entity_name": "Fund Five", "vehicle_type": "BDC"}
    ])
    _write_csv(out / "fund_identity.csv", [
        {"cik": "0000000005", "entity_name": "Fund Five", "source": "companyfacts"}
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


def test_build_sample_manifest_filters_and_dedupes_gav(fail_output_dir):
    path = fv.build_sample_manifest(output_dir=fail_output_dir, seed=123)
    rows = _read_csv(path)

    assert [row["rule_id"] for row in rows].count("GAV_BDC01") == 1
    assert {row["rule_id"] for row in rows} == {"C101", "X06", "X09", "C402", "GAV_BDC01"}
    assert "severity" not in rows[0]  # manifest is identity, not issue copy
    assert all(row["cik"].startswith("000000000") for row in rows)
    assert {row["sampling_unit"] for row in rows if row["rule_id"] == "GAV_BDC01"} == {"cik_quarter"}
    assert {row["sampling_unit"] for row in rows if row["rule_id"] != "GAV_BDC01"} == {"issue_row"}
    assert {row["dataset"] for row in rows} == {"private_markets_holdings"}


def test_build_fund_sample_manifest_from_validation_current(fail_output_dir):
    path = fv.build_sample_manifest(output_dir=fail_output_dir, seed=123, dataset="funds")
    rows = _read_csv(path)

    assert {row["dataset"] for row in rows} == {"fund_financials"}
    assert [row["rule_id"] for row in rows] == ["F10", "F20", "F28"]
    assert {row["sampling_unit"] for row in rows} == {"fund_period"}
    assert all(row["source_file"].endswith("fund_financials_validation_current.csv") for row in rows)


def test_build_fund_evidence_bundle_contains_accounting_context(fail_output_dir):
    manifest_path = fv.build_sample_manifest(output_dir=fail_output_dir, seed=123, dataset="funds")
    manifest = _read_csv(manifest_path)
    verification_id = next(row["verification_id"] for row in manifest if row["rule_id"] == "F10")

    bundle_path = fv.build_evidence_bundle(verification_id, output_dir=fail_output_dir)
    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    evidence = {item["evidence_id"]: item["data"] for item in bundle["evidence_items"]}

    assert bundle["dataset"] == "fund_financials"
    assert bundle["sample_manifest_row"]["rule_id"] == "F10"
    assert evidence["validation_rows"][0]["check_code"] == "F10"
    assert evidence["fund_financials_row"][0]["cik"] == "0000000005"
    assert [row["report_date"] for row in evidence["nearby_fund_rows"]] == ["2024-12-31", "2025-03-31"]
    assert evidence["fund_quality_metrics"][0]["validation_tier"] == "under_review"


def test_build_fund_cross_level_bundle_contains_holdings_evidence(fail_output_dir):
    _append_csv(fail_output_dir / "bdc_holdings.csv", [{
        "cik": "0000000005",
        "accession_number": "acc5",
        "report_date": "2025-03-31",
        "investment_identifier": "Issuer H - Loan",
        "fair_value": "40000",
        "dimension_path": "InvestmentIdentifierAxis=IssuerHMember",
    }])
    manifest_path = fv.build_sample_manifest(output_dir=fail_output_dir, seed=123, dataset="funds")
    manifest = _read_csv(manifest_path)
    verification_id = next(row["verification_id"] for row in manifest if row["rule_id"] == "F20")

    bundle_path = fv.build_evidence_bundle(verification_id, output_dir=fail_output_dir)
    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    evidence = {item["evidence_id"]: item["data"] for item in bundle["evidence_items"]}

    assert evidence["holdings_aggregate"]["position_count"] == 1
    assert evidence["holdings_aggregate"]["sum_fair_value"] == 40000.0
    assert evidence["holdings_examples"][0]["issuer_name"] == "Issuer H"
    assert evidence["gav_reconciliation"][0]["gav_ratio"] == "0.5"
    assert evidence["pct_sum"][0]["pct_sum"] == "44.4"
    detail = evidence["f20_gav_reconciliation_detail"]["bdc_schedule_reconciliation"]
    assert detail["row_match_summary"]["matched_key_count"] == 1
    assert detail["unmatched_raw_rows"] == []
    assert detail["unmatched_unified_rows"] == []


def test_build_f28_bundle_shows_missing_holdings_side(fail_output_dir):
    manifest_path = fv.build_sample_manifest(output_dir=fail_output_dir, seed=123, dataset="funds")
    manifest = _read_csv(manifest_path)
    verification_id = next(row["verification_id"] for row in manifest if row["rule_id"] == "F28")

    bundle_path = fv.build_evidence_bundle(verification_id, output_dir=fail_output_dir)
    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    evidence = {item["evidence_id"]: item["data"] for item in bundle["evidence_items"]}

    assert evidence["fund_financials_row"][0]["cik"] == "0000000006"
    assert evidence["holdings_aggregate"]["has_holdings"] is False
    assert evidence["holdings_examples"] == []
    detail = evidence["f28_coverage_completeness_sources"]
    assert detail["fund_info_to_fund_financials_materialization"]["materialization_status"] == "fund_financials_present_without_nport_fund_info"
    assert any(row["artifact"] == "fund_info" for row in detail["same_period_source_coverage_matrix"])


def test_f11_bundle_includes_nav_identity_metric_trace(fail_output_dir):
    _append_csv(fail_output_dir / "fund_financials.csv", [{
        "cik": "0000000007",
        "report_quarter": "2025q1",
        "report_date": "2025-03-31",
        "entity_name": "Fund Seven",
        "net_assets": "1000",
        "nav_per_share": "10",
        "shares_outstanding": "100",
    }])
    _append_csv(fail_output_dir / "ncsr_financials.csv", [{
        "cik": "0000000007",
        "report_date": "2025-03-31",
        "net_assets": "1000",
        "nav_per_share": "10",
        "shares_outstanding": "100",
        "accession_number": "ncsr7",
    }])
    manifest_row = _write_single_fund_manifest(fail_output_dir, "F11", cik="0000000007")

    bundle_path = fv.build_evidence_bundle(manifest_row["verification_id"], output_dir=fail_output_dir)
    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    evidence = {item["evidence_id"]: item["data"] for item in bundle["evidence_items"]}

    trace = evidence["f11_nav_identity_metric_trace"]
    assert trace["computed_value"] == 1000
    assert trace["trace_status"] == "source_backed"
    assert trace["source_candidates"]["nav_per_share"]["ncsr_financials"]["exact_period"][0]["accession"] == "ncsr7"
    assert trace["share_scope_evidence"]["share_class_scope_resolved"] is False
    assert "same share-class scope" in trace["share_scope_evidence"]["residual_ambiguity"]


def test_f27_bundle_reports_missing_income_sources(fail_output_dir):
    _append_csv(fail_output_dir / "fund_financials.csv", [{
        "cik": "0000000008",
        "report_quarter": "2025q1",
        "report_date": "2025-03-31",
        "entity_name": "Fund Eight",
        "income_yield": "0.08",
    }])
    manifest_row = _write_single_fund_manifest(fail_output_dir, "F27", cik="0000000008")

    bundle_path = fv.build_evidence_bundle(manifest_row["verification_id"], output_dir=fail_output_dir)
    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    evidence = {item["evidence_id"]: item["data"] for item in bundle["evidence_items"]}

    trace = evidence["f27_income_yield_metric_trace"]
    assert trace["trace_status"] == "missing_exact_period_sources"
    assert {row["input"] for row in trace["missing_sources"]} >= {"direct_income_yield", "income_components"}
    assert any(row["artifact"] == "fund_financials" and row["source_absent"] is False for row in trace["income_yield_source_availability_matrix"])
    assert any(row["artifact"] == "companyfacts" and row["source_absent"] is True for row in trace["income_yield_source_availability_matrix"])
    assert trace["source_absence_by_artifact"]


def test_f32_bundle_distinguishes_direct_and_input_sources(fail_output_dir):
    _append_csv(fail_output_dir / "fund_financials.csv", [{
        "cik": "0000000009",
        "report_quarter": "2025q1",
        "report_date": "2025-03-31",
        "entity_name": "Fund Nine",
        "expense_ratio": "0.02",
        "total_expenses": "20",
        "average_net_assets": "1000",
    }])
    _append_csv(fail_output_dir / "ncsr_financials.csv", [{
        "cik": "0000000009",
        "report_date": "2025-03-31",
        "expense_ratio": "0.02",
    }])
    manifest_row = _write_single_fund_manifest(fail_output_dir, "F32", cik="0000000009")

    bundle_path = fv.build_evidence_bundle(manifest_row["verification_id"], output_dir=fail_output_dir)
    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    evidence = {item["evidence_id"]: item["data"] for item in bundle["evidence_items"]}

    trace = evidence["f32_expense_ratio_metric_trace"]
    assert trace["computed_value"] == 0.02
    assert trace["source_candidates"]["direct_expense_ratio"]["ncsr_financials"]["exact_period"]
    assert {row["input"] for row in trace["missing_sources"]} >= {"total_expenses", "average_net_assets"}
    assert any(row["artifact"] == "ncsr_financials" and row["source_absent"] is False for row in trace["expense_source_availability_matrix"])
    assert any(row["artifact"] == "bdc_fund_income" for row in trace["expense_source_availability_matrix"])


def test_f33_zero_distribution_requires_direct_source_candidate(fail_output_dir):
    _append_csv(fail_output_dir / "fund_financials.csv", [{
        "cik": "0000000010",
        "report_quarter": "2025q1",
        "report_date": "2025-03-31",
        "entity_name": "Fund Ten",
        "distribution_rate": "0",
        "distribution_per_share": "0",
        "nav_per_share": "10",
    }])
    _append_csv(fail_output_dir / "ncsr_financials.csv", [{
        "cik": "0000000010",
        "report_date": "2025-03-31",
        "distribution_per_share": "0",
        "nav_per_share": "10",
    }])
    manifest_row = _write_single_fund_manifest(fail_output_dir, "F33", cik="0000000010")

    bundle_path = fv.build_evidence_bundle(manifest_row["verification_id"], output_dir=fail_output_dir)
    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    evidence = {item["evidence_id"]: item["data"] for item in bundle["evidence_items"]}

    trace = evidence["f33_distribution_rate_metric_trace"]
    assert trace["computed_value"] == 0
    assert trace["source_candidates"]["distribution_per_share"]["ncsr_financials"]["exact_period"][0]["source_row"]["distribution_per_share"] == "0"
    assert "distribution_per_share" not in {row["input"] for row in trace["missing_sources"]}
    assert trace["exact_period_source_rows"]
    assert any(row["artifact"] == "ncsr_financials" and row["source_absent"] is False for row in trace["distribution_source_availability_matrix"])


def test_f23_bundle_includes_nport_pct_denominator_trace(fail_output_dir):
    _append_csv(fail_output_dir / "fund_financials.csv", [{
        "cik": "0000000011",
        "report_quarter": "2025q1",
        "report_date": "2025-03-31",
        "entity_name": "Fund Eleven",
        "net_assets": "1000",
    }])
    _append_csv(fail_output_dir / "private_markets_holdings.csv", [{
        "source": "nport",
        "cik": "0000000011",
        "report_date": "2025-03-31",
        "issuer_name": "Issuer N",
        "fair_value": "100",
        "pct_of_net_assets": "12",
        "position_id": "n1",
    }])
    _append_csv(fail_output_dir / "nport_holdings.csv", [{
        "cik": "0000000011",
        "report_date": "2025-03-31",
        "issuer_name": "Issuer N",
        "currency_value": "100",
        "percentage": "12",
    }])
    manifest_row = _write_single_fund_manifest(fail_output_dir, "F23", cik="0000000011")

    bundle_path = fv.build_evidence_bundle(manifest_row["verification_id"], output_dir=fail_output_dir)
    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    evidence = {item["evidence_id"]: item for item in bundle["evidence_items"]}

    assert evidence["f23_reported_vs_computed_pct_detail"]["kind"] == "nport_pct_denominator_trace"
    example = evidence["f23_reported_vs_computed_pct_detail"]["data"]["nport_denominator_trace"]["examples"][0]
    assert example["reported_percentage"] == 12
    assert example["computed_pct"] == 10
    assert example["reported_vs_computed_delta"] == 2


def test_f24_bundle_includes_position_transition_mapping(fail_output_dir):
    _append_csv(fail_output_dir / "private_markets_holdings.csv", [
        {
            "source": "bdc",
            "cik": "0000000012",
            "report_date": "2024-12-31",
            "issuer_name": "Dropped",
            "fair_value": "25",
            "position_id": "drop",
            "index_classification": "DIRECT_LENDING",
            "classification_reason": "debt instrument",
        },
        {
            "source": "bdc",
            "cik": "0000000012",
            "report_date": "2025-03-31",
            "issuer_name": "Added",
            "fair_value": "50",
            "position_id": "add",
            "index_classification": "DIRECT_LENDING",
            "classification_reason": "debt instrument",
        },
    ])
    manifest_row = _write_single_fund_manifest(fail_output_dir, "F24", cik="0000000012")

    bundle_path = fv.build_evidence_bundle(manifest_row["verification_id"], output_dir=fail_output_dir)
    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    evidence = {item["evidence_id"]: item for item in bundle["evidence_items"]}

    assert evidence["f24_position_count_stability_detail"]["kind"] == "position_transition_trace"
    mapping = evidence["f24_position_count_stability_detail"]["data"]["position_transition_mapping"]
    assert mapping["added_count"] == 1
    assert mapping["dropped_count"] == 1
    assert mapping["added_examples"][0]["private_market_classification_reason"] == "debt instrument"
    source_transition = evidence["f24_position_count_stability_detail"]["data"]["source_row_transition_evidence"]
    assert source_transition["added_private_market_rows"][0]["transition_interpretation"] == "true_source_change_or_missing_cached_raw_anchor"
    assert source_transition["dates"]["prior"] == "2024-12-31"
    assert source_transition["dates"]["current"] == "2025-03-31"


def test_build_all_fund_overwrite_preserves_holdings_bundles_and_manifest(fail_output_dir):
    fv.build_sample_manifest(output_dir=fail_output_dir, seed=123, dataset="all")
    holding_paths = fv.build_all_evidence_bundles(
        output_dir=fail_output_dir,
        overwrite=True,
        dataset="holdings",
    )
    stale_fund = fail_output_dir / "fail_verification" / "bundles" / "F10_0000009999_2025-03-31_stale.json"
    stale_fund.parent.mkdir(parents=True, exist_ok=True)
    stale_fund.write_text("{}", encoding="utf-8")
    manifest_path = fail_output_dir / "fail_verification" / "bundle_manifest.csv"
    manifest_rows = _read_csv(manifest_path)
    manifest_rows.append({
        "verification_id": stale_fund.stem,
        "bundle_path": fv.display_path(stale_fund),
        "bundle_sha256": "stale",
        "created_at": "2026-05-11T00:00:00+00:00",
    })
    fv.write_csv_rows(manifest_path, manifest_rows, fv.BUNDLE_MANIFEST_COLUMNS)
    guard_path = fail_output_dir / "fail_verification" / "run_guard.json"
    guard_path.write_text("stale", encoding="utf-8")

    fund_paths = fv.build_all_evidence_bundles(
        output_dir=fail_output_dir,
        overwrite=True,
        dataset="funds",
    )

    assert all(path.exists() for path in holding_paths)
    assert all(path.exists() for path in fund_paths)
    assert not stale_fund.exists()
    manifest = _read_csv(manifest_path)
    assert {row["verification_id"] for row in manifest} == {
        *(path.stem for path in holding_paths),
        *(path.stem for path in fund_paths),
    }
    assert json.loads(guard_path.read_text(encoding="utf-8"))["schema_version"] == "1.0"


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
    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    evidence_ids = [item["evidence_id"] for item in bundle["evidence_items"]]
    return {
        "schema_version": "1.0",
        "dataset": manifest_row.get("dataset", "private_markets_holdings"),
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
        "evidence_inventory": [
            {
                "evidence_id": evidence_id,
                "reviewed": True,
                "classification": "DATA_ERROR",
                "assessment": "Reviewed for this verdict and consistent with the sampled failure.",
            }
            for evidence_id in evidence_ids
        ],
        "already_present_evidence_assessment": {
            "required_for_insufficient": False,
            "assessment": [],
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


def test_validate_verdict_requires_complete_evidence_inventory(fail_output_dir):
    manifest_path = fv.build_sample_manifest(output_dir=fail_output_dir, seed=123)
    manifest_row = next(row for row in _read_csv(manifest_path) if row["rule_id"] == "C101")
    bundle_path = fv.build_evidence_bundle(manifest_row["verification_id"], output_dir=fail_output_dir)
    verdict = _valid_verdict(bundle_path, manifest_row)
    verdict["evidence_inventory"] = verdict["evidence_inventory"][:1]
    verdict_path = fail_output_dir / "fail_verification" / "verdicts" / f"{manifest_row['verification_id']}.json"
    verdict_path.parent.mkdir(parents=True, exist_ok=True)
    verdict_path.write_text(json.dumps(verdict), encoding="utf-8")

    errors = fv.validate_verdict(verdict_path, output_dir=fail_output_dir)

    assert any("evidence_inventory must enumerate every bundled evidence id" in error for error in errors)


def test_validate_verdict_rejects_insufficient_without_present_evidence_assessment(fail_output_dir):
    manifest_path = fv.build_sample_manifest(output_dir=fail_output_dir, seed=123)
    manifest_row = next(row for row in _read_csv(manifest_path) if row["rule_id"] == "C101")
    bundle_path = fv.build_evidence_bundle(manifest_row["verification_id"], output_dir=fail_output_dir)
    verdict = _valid_verdict(bundle_path, manifest_row)
    verdict["verdict"] = "INSUFFICIENT_EVIDENCE"
    verdict["confidence"] = "low"
    verdict["validator_assessment"]["root_cause"] = "UNKNOWN"
    verdict["epistemic_assessment"]["confirmed_mechanism"] = {
        "summary": "",
        "support_strength": "NONE",
        "evidence_refs": [],
    }
    verdict["epistemic_assessment"]["evidence_chain"] = []
    verdict["epistemic_assessment"]["missing_evidence"] = [
        "Raw source row needed to prove the mechanism deterministically."
    ]
    verdict["determination_rationale"]["residual_uncertainty"] = (
        "The bundled evidence does not prove whether this is source omission or extraction loss."
    )
    verdict["already_present_evidence_assessment"] = {
        "required_for_insufficient": False,
        "assessment": [],
    }
    verdict_path = fail_output_dir / "fail_verification" / "verdicts" / f"{manifest_row['verification_id']}.json"
    verdict_path.parent.mkdir(parents=True, exist_ok=True)
    verdict_path.write_text(json.dumps(verdict), encoding="utf-8")

    errors = fv.validate_verdict(verdict_path, output_dir=fail_output_dir)

    assert any("must use root_cause BUNDLE_MISSING_LOCAL_EVIDENCE or RULE_OR_MODEL_NOT_DETERMINATIVE" in error for error in errors)
    assert any("must include already_present_evidence_assessment.required_for_insufficient=true" in error for error in errors)
    assert any("must assess already-present evidence ids" in error for error in errors)


def test_validate_verdict_rejects_dataset_mismatch(fail_output_dir):
    manifest_path = fv.build_sample_manifest(output_dir=fail_output_dir, seed=123, dataset="funds")
    manifest_row = next(row for row in _read_csv(manifest_path) if row["rule_id"] == "F10")
    bundle_path = fv.build_evidence_bundle(manifest_row["verification_id"], output_dir=fail_output_dir)
    verdict = _valid_verdict(bundle_path, manifest_row)
    verdict["dataset"] = "private_markets_holdings"
    verdict["epistemic_assessment"]["confirmed_mechanism"]["evidence_refs"] = ["validation_rows", "fund_financials_row"]
    verdict["epistemic_assessment"]["evidence_chain"][0]["evidence_id"] = "validation_rows"
    verdict["epistemic_assessment"]["evidence_chain"][1]["evidence_id"] = "fund_financials_row"
    verdict["epistemic_assessment"]["ruled_out_alternatives"][0]["evidence_id"] = "fund_financials_row"
    verdict["evidence_refs"] = [
        {"evidence_id": "validation_rows", "supports": "Shows the sampled fund validation failure."},
        {"evidence_id": "fund_financials_row", "supports": "Shows the sampled fund output row."},
    ]
    verdict_path = fail_output_dir / "fail_verification" / "verdicts" / f"{manifest_row['verification_id']}.json"
    verdict_path.parent.mkdir(parents=True, exist_ok=True)
    verdict_path.write_text(json.dumps(verdict), encoding="utf-8")

    errors = fv.validate_verdict(verdict_path, output_dir=fail_output_dir)

    assert any("dataset does not match" in error for error in errors)


def test_validate_verdict_rejects_f21_scope_mismatch_ignored(fail_output_dir):
    verification_id = "F21_0000000005_2025-03-31_scope"
    manifest_row = {
        "dataset": "fund_financials",
        "verification_id": verification_id,
        "rule_id": "F21",
        "sampling_unit": "fund_period",
        "cik": "0000000005",
        "report_date": "2025-03-31",
        "row_key": "0",
        "source": "fund_financials",
        "accession_number": "",
        "source_record_id": "0000000005|2025-03-31|2025q1|F21",
        "issuer_name": "",
        "position_id": "",
        "sample_stratum": "0000000005",
        "sample_weight": "1",
        "random_seed": "123",
        "source_file": "data/output/fund_financials_validation_current.csv",
        "source_file_sha256": "0" * 64,
        "population": "1",
        "sample_size": "1",
        "stratum_population": "1",
        "stratum_sample_size": "1",
    }
    fv.write_csv_rows(
        fail_output_dir / "fail_verification" / "sample_manifest.csv",
        [manifest_row],
        fv.MANIFEST_COLUMNS,
    )
    bundle = {
        "schema_version": "1.0",
        "dataset": "fund_financials",
        "bundle_id": verification_id,
        "created_at": "2026-05-11T00:00:00+00:00",
        "source_artifacts": [],
        "sample_manifest_row": manifest_row,
        "evidence_items": [
            {
                "evidence_id": "f21_net_assets_scope_reconciliation",
                "kind": "cross_level_reconciliation_detail",
                "description": "Scope evidence.",
                "data": {
                    "denominator_scope": "full_fund_assets",
                    "holdings_scope": "unified_private_markets_filter",
                    "scope_mismatch_candidate": True,
                },
            }
        ],
    }
    bundle_path = fail_output_dir / "fail_verification" / "bundles" / f"{verification_id}.json"
    bundle_path.parent.mkdir(parents=True, exist_ok=True)
    bundle_path.write_text(json.dumps(bundle), encoding="utf-8")
    verdict = _valid_verdict(bundle_path, manifest_row)
    verdict["mechanism"] = "The ratio is unusual but the mechanism is not discussed here."
    verdict["epistemic_assessment"]["confirmed_mechanism"]["evidence_refs"] = ["f21_net_assets_scope_reconciliation"]
    verdict["epistemic_assessment"]["confirmed_mechanism"]["support_strength"] = "DIRECT_SOURCE_EVIDENCE"
    verdict["epistemic_assessment"]["evidence_chain"] = [
        {
            "claim": "The bundled detail is cited generically.",
            "evidence_id": "f21_net_assets_scope_reconciliation",
            "supports": "The evidence item was reviewed.",
        }
    ]
    verdict["epistemic_assessment"]["ruled_out_alternatives"] = []
    verdict["evidence_refs"] = [
        {
            "evidence_id": "f21_net_assets_scope_reconciliation",
            "supports": "The evidence item was reviewed.",
        }
    ]
    verdict["determination_rationale"] = {
        "why_this_verdict": "The ratio is treated as a data error without addressing the bundled mechanism.",
        "why_not_alternative": "The alternative was not evaluated in this intentionally invalid fixture.",
        "residual_uncertainty": "This fixture should fail validation.",
    }
    verdict_path = fail_output_dir / "fail_verification" / "verdicts" / f"{verification_id}.json"
    verdict_path.parent.mkdir(parents=True, exist_ok=True)
    verdict_path.write_text(json.dumps(verdict), encoding="utf-8")

    errors = fv.validate_verdict(verdict_path, output_dir=fail_output_dir, check_run_guard=False, dataset="funds")

    assert any("F21 verdict must address scoped denominator mismatch" in error for error in errors)


def test_validate_verdict_accepts_fund_verdict(fail_output_dir):
    manifest_path = fv.build_sample_manifest(output_dir=fail_output_dir, seed=123, dataset="funds")
    manifest_row = next(row for row in _read_csv(manifest_path) if row["rule_id"] == "F10")
    bundle_path = fv.build_evidence_bundle(manifest_row["verification_id"], output_dir=fail_output_dir)
    verdict = _valid_verdict(bundle_path, manifest_row)
    verdict["mechanism"] = "Fund accounting identity failure is corroborated by validation and fund rows."
    verdict["validator_assessment"]["root_cause"] = "FUND_ACCOUNTING_RECONCILIATION"
    verdict["epistemic_assessment"]["confirmed_mechanism"]["evidence_refs"] = ["validation_rows", "fund_financials_row"]
    verdict["epistemic_assessment"]["evidence_chain"] = [
        {
            "claim": "The validator identifies the sampled F10 failure.",
            "evidence_id": "validation_rows",
            "supports": "The validation row carries the F10 failure for this fund period.",
        },
        {
            "claim": "The fund row contains the accounting values under review.",
            "evidence_id": "fund_financials_row",
            "supports": "The sampled fund_financials row is present in the bundle.",
        },
    ]
    verdict["epistemic_assessment"]["ruled_out_alternatives"][0]["evidence_id"] = "fund_financials_row"
    verdict["evidence_refs"] = [
        {"evidence_id": "validation_rows", "supports": "Shows the sampled fund validation failure."},
        {"evidence_id": "fund_financials_row", "supports": "Shows the sampled fund output row."},
    ]
    verdict_path = fail_output_dir / "fail_verification" / "verdicts" / f"{manifest_row['verification_id']}.json"
    verdict_path.parent.mkdir(parents=True, exist_ok=True)
    verdict_path.write_text(json.dumps(verdict), encoding="utf-8")

    assert fv.validate_verdict(verdict_path, output_dir=fail_output_dir, dataset="funds") == []


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
            "dataset": "private_markets_holdings",
            "rule_id": "C101",
            "verdict": "CONFIRMED_DATA_ERROR",
            "confidence": "high",
            "count": "1",
            "weighted_count": "1",
            "affected_fair_value": "0.00",
            "affected_fund_assets": "0.00",
            "affected_holdings_fv": "0.00",
        }
    ]
