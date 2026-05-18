import csv
import json
from pathlib import Path

import pandas as pd

from pipeline.validation_rules import diagnostics as dc


def _write_csv(path: Path, rows: list[dict[str, str]]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = sorted({key for row in rows for key in row})
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    return path


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _holding(**overrides) -> dict[str, str]:
    row = {
        "cik": "0000000100",
        "quarter": "2024q1",
        "report_date": "2024-03-31",
        "issuer_name": "Issuer",
        "position_id": "P0",
        "instrument_description": "Term loan",
        "source": "bdc",
        "fair_value": "100",
        "index_classification": "DIRECT_LENDING",
    }
    row.update({key: str(value) for key, value in overrides.items()})
    return row


def _calibration_fixture(tmp_path: Path) -> dict[str, Path]:
    rows = []

    # DIST01: same-source adjacent quarter with median and total FV both up 1000x.
    for i in range(10):
        rows.append(_holding(
            cik="0000000101",
            quarter="2024q1",
            report_date="2024-03-31",
            issuer_name=f"Scale {i}",
            position_id=f"SCALE{i}",
            fair_value="100",
        ))
        rows.append(_holding(
            cik="0000000101",
            quarter="2024q2",
            report_date="2024-06-30",
            issuer_name=f"Scale {i}",
            position_id=f"SCALE{i}",
            fair_value="100000",
        ))

    # DIST02: issuer count doubles while row count and total FV stay stable.
    for i in range(20):
        rows.append(_holding(
            cik="0000000102",
            quarter="2024q1",
            report_date="2024-03-31",
            issuer_name=f"Residual {i % 10}",
            position_id=f"RESOLD{i}",
            fair_value="100",
        ))
        rows.append(_holding(
            cik="0000000102",
            quarter="2024q2",
            report_date="2024-06-30",
            issuer_name=f"Residual {i}",
            position_id=f"RESCUR{i}",
            fair_value="100",
        ))

    # DIST05: all issuer strings churn while position IDs remain stable.
    for i in range(10):
        rows.append(_holding(
            cik="0000000103",
            quarter="2024q1",
            report_date="2024-03-31",
            issuer_name=f"Legal Name {i}",
            position_id=f"STABLE{i}",
            fair_value="100",
        ))
        rows.append(_holding(
            cik="0000000103",
            quarter="2024q2",
            report_date="2024-06-30",
            issuer_name=f"Renamed Legal Name {i}",
            position_id=f"STABLE{i}",
            fair_value="100",
        ))

    # DIST04: concentration shift remains covered by the broad harness test.
    for i in range(20):
        rows.append(_holding(
            cik="0000000104",
            quarter="2024q1",
            report_date="2024-03-31",
            issuer_name=f"Concentration {i}",
            position_id=f"CONOLD{i}",
            fair_value="100",
        ))
        rows.append(_holding(
            cik="0000000104",
            quarter="2024q2",
            report_date="2024-06-30",
            issuer_name=f"Concentration {i}",
            position_id=f"CONCUR{i}",
            fair_value="2000" if i == 0 else "1",
        ))

    # MONO03: same position appears in q1 and q3 with another q2 observation for the CIK.
    rows.append(_holding(
        cik="0000000105",
        quarter="2024q1",
        report_date="2024-03-31",
        issuer_name="Gap Corp",
        position_id="GAP",
        fair_value="1000",
    ))
    rows.append(_holding(
        cik="0000000105",
        quarter="2024q2",
        report_date="2024-06-30",
        issuer_name="Other Corp",
        position_id="OTHER",
        fair_value="100",
    ))
    rows.append(_holding(
        cik="0000000105",
        quarter="2024q3",
        report_date="2024-09-30",
        issuer_name="Gap Corp",
        position_id="GAP",
        fair_value="1100",
    ))

    # MONO05: stable private identity flips classification across adjacent periods.
    rows.append(_holding(
        cik="0000000106",
        quarter="2024q1",
        report_date="2024-03-31",
        issuer_name="Flip Corp",
        position_id="FLIP",
        fair_value="500",
        index_classification="DIRECT_LENDING",
    ))
    rows.append(_holding(
        cik="0000000106",
        quarter="2024q2",
        report_date="2024-06-30",
        issuer_name="Flip Corp",
        position_id="FLIP",
        fair_value="500",
        index_classification="COMMON_EQUITY",
    ))
    holdings = _write_csv(tmp_path / "private_markets_holdings.csv", rows)
    _write_csv(tmp_path / "validation_rules_detail.csv", [{
        "finding_key": "abc",
        "rule_id": "T04",
        "category": "T",
        "severity": "WARN",
        "granularity_key": "0000000100|2024q2",
        "cik": "0000000100",
        "quarter": "2024q2",
        "report_date": "2024-06-30",
        "issuer_name": "Flip Corp",
        "position_id": "FLIP",
        "affected_fair_value": "500",
        "detail": "overlap fixture",
        "evidence_hint": "test",
        "source_file": "private_markets_holdings.csv",
    }])
    _write_csv(tmp_path / "position_matches.csv", [{"cik": "0000000100", "position_id": "FLIP"}])
    _write_csv(tmp_path / "position_returns.csv", [{"cik": "0000000100", "position_id": "FLIP"}])
    _write_csv(tmp_path / "index_returns.csv", [{"quarter": "2024q2", "constituent_count": "1"}])
    return {"holdings": holdings}


def _run_candidate(tmp_path: Path, candidate_id: str, rows: list[dict[str, str]]) -> pd.DataFrame:
    holdings = _write_csv(tmp_path / "private_markets_holdings.csv", rows)
    outputs = dc.run_calibration(
        [candidate_id],
        output_dir=tmp_path,
        table_paths={"holdings": holdings},
        calibration_run_id="run-a",
    )
    return pd.read_csv(outputs["findings"])


def test_run_calibration_writes_findings_grid_and_summary(tmp_path):
    paths = _calibration_fixture(tmp_path)

    outputs = dc.run_calibration(
        candidate_ids=["DIST01", "DIST02", "DIST04", "DIST05", "MONO03", "MONO05"],
        output_dir=tmp_path,
        table_paths=paths,
        calibration_run_id="run-a",
    )

    assert set(outputs) == {"findings", "summary", "threshold_grid"}
    findings = pd.read_csv(outputs["findings"])
    grid = pd.read_csv(outputs["threshold_grid"])
    summary = pd.read_csv(outputs["summary"])

    assert set(["DIST01", "DIST02", "DIST04", "DIST05", "MONO03", "MONO05"]).issubset(set(findings["candidate_id"]))
    assert list(summary.columns) == dc.SUMMARY_COLUMNS
    assert set(grid["candidate_id"]) == {"DIST01", "DIST02", "DIST04", "DIST05", "MONO03", "MONO05"}
    assert set(summary["recommended_action"]) == {"needs_agent_review"}


def test_dist01_keeps_scale_consistent_fv_break_and_rejects_noise(tmp_path):
    rows = []
    for i in range(10):
        rows.append(_holding(cik="0000000201", quarter="2024q1", report_date="2024-03-31", issuer_name=f"Scale {i}", position_id=f"S{i}", fair_value="100"))
        rows.append(_holding(cik="0000000201", quarter="2024q2", report_date="2024-06-30", issuer_name=f"Scale {i}", position_id=f"S{i}", fair_value="100000"))
        rows.append(_holding(cik="0000000202", quarter="2024q1", report_date="2024-03-31", issuer_name=f"Negative {i}", position_id=f"N{i}", fair_value="-100"))
        rows.append(_holding(cik="0000000202", quarter="2024q2", report_date="2024-06-30", issuer_name=f"Negative {i}", position_id=f"N{i}", fair_value="-100000"))
        rows.append(_holding(cik="0000000203", quarter="2024q1", report_date="2024-03-31", issuer_name=f"Comp {i}", position_id=f"C{i}", fair_value="100"))
        rows.append(_holding(cik="0000000203", quarter="2024q2", report_date="2024-06-30", issuer_name=f"Comp {i}", position_id=f"C{i}", fair_value="991" if i == 0 else "1"))

    findings = _run_candidate(tmp_path, "DIST01", rows)

    assert set(findings["cik"].astype(str).str.zfill(10)) == {"0000000201"}
    assert findings["metric_value"].max() == 3.0


def test_dist02_keeps_residual_issuer_count_shock_and_rejects_coverage_shock(tmp_path):
    rows = []
    for i in range(20):
        rows.append(_holding(cik="0000000301", quarter="2024q1", report_date="2024-03-31", issuer_name=f"Stable Rows {i % 10}", position_id=f"SR{i}", fair_value="100"))
        rows.append(_holding(cik="0000000301", quarter="2024q2", report_date="2024-06-30", issuer_name=f"Stable Rows {i}", position_id=f"SR{i}", fair_value="100"))
        if i < 10:
            rows.append(_holding(cik="0000000302", quarter="2024q1", report_date="2024-03-31", issuer_name=f"Coverage {i}", position_id=f"CO{i}", fair_value="100"))
        rows.append(_holding(cik="0000000302", quarter="2024q2", report_date="2024-06-30", issuer_name=f"Coverage {i}", position_id=f"CN{i}", fair_value="100"))

    findings = _run_candidate(tmp_path, "DIST02", rows)

    assert set(findings["cik"].astype(str).str.zfill(10)) == {"0000000301"}
    assert findings["metric_value"].max() == 1.0


def test_dist05_keeps_issuer_string_churn_and_rejects_true_new_positions(tmp_path):
    rows = []
    for i in range(10):
        rows.append(_holding(cik="0000000401", quarter="2024q1", report_date="2024-03-31", issuer_name=f"Old Name {i}", position_id=f"KEEP{i}", fair_value="100"))
        rows.append(_holding(cik="0000000401", quarter="2024q2", report_date="2024-06-30", issuer_name=f"New Name {i}", position_id=f"KEEP{i}", fair_value="100"))
        rows.append(_holding(cik="0000000402", quarter="2024q1", report_date="2024-03-31", issuer_name=f"Turnover Old {i}", position_id=f"OLD{i}", fair_value="100"))
        rows.append(_holding(cik="0000000402", quarter="2024q2", report_date="2024-06-30", issuer_name=f"Turnover New {i}", position_id=f"NEW{i}", fair_value="100"))

    findings = _run_candidate(tmp_path, "DIST05", rows)

    assert set(findings["cik"].astype(str).str.zfill(10)) == {"0000000401"}
    assert findings["affected_fair_value"].max() == 1000
    assert findings["metric_value"].max() == 1.0


def test_mono05_keeps_stable_private_flip_and_rejects_unstable_identity(tmp_path):
    rows = [
        _holding(cik="0000000501", quarter="2024q1", report_date="2024-03-31", issuer_name="Flip Corp", position_id="GOOD", instrument_description="First lien term loan", fair_value="100", index_classification="DIRECT_LENDING"),
        _holding(cik="0000000501", quarter="2024q2", report_date="2024-06-30", issuer_name="Flip Corp", position_id="GOOD", instrument_description="First lien term loan", fair_value="120", index_classification="COMMON_EQUITY"),
        _holding(cik="0000000502", quarter="2024q1", report_date="2024-03-31", issuer_name="Unclassified Corp", position_id="UNCLASS", fair_value="100", index_classification="UNCLASSIFIED"),
        _holding(cik="0000000502", quarter="2024q2", report_date="2024-06-30", issuer_name="Unclassified Corp", position_id="UNCLASS", fair_value="100", index_classification="DIRECT_LENDING"),
        _holding(cik="0000000503", quarter="2024q1", report_date="2024-03-31", issuer_name="Cash Corp", position_id="CASHFLIP", fair_value="100", index_classification="CASH"),
        _holding(cik="0000000503", quarter="2024q2", report_date="2024-06-30", issuer_name="Cash Corp", position_id="CASHFLIP", fair_value="100", index_classification="DIRECT_LENDING"),
        _holding(cik="0000000504", quarter="2024q1", report_date="2024-03-31", issuer_name="Instrument Corp", position_id="INST", instrument_description="Term loan", fair_value="100", index_classification="DIRECT_LENDING"),
        _holding(cik="0000000504", quarter="2024q2", report_date="2024-06-30", issuer_name="Instrument Corp", position_id="INST", instrument_description="Preferred shares", fair_value="100", index_classification="PREFERRED_EQUITY"),
        _holding(cik="0000000505", quarter="2024q1", report_date="2024-03-31", issuer_name="Multi Corp", position_id="MULTI", fair_value="50", index_classification="DIRECT_LENDING"),
        _holding(cik="0000000505", quarter="2024q1", report_date="2024-03-31", issuer_name="Multi Corp", position_id="MULTI", fair_value="50", index_classification="DIRECT_LENDING"),
        _holding(cik="0000000505", quarter="2024q2", report_date="2024-06-30", issuer_name="Multi Corp", position_id="MULTI", fair_value="100", index_classification="COMMON_EQUITY"),
    ]

    findings = _run_candidate(tmp_path, "MONO05", rows)

    assert set(findings["cik"].astype(str).str.zfill(10)) == {"0000000501"}
    assert set(findings["position_id"]) == {"GOOD"}


def test_calibration_ids_are_stable_across_run_ids(tmp_path):
    paths = _calibration_fixture(tmp_path)

    first = dc.run_calibration(["DIST01"], output_dir=tmp_path, table_paths=paths, calibration_run_id="run-a")
    first_ids = set(pd.read_csv(first["threshold_grid"])["calibration_id"])
    second = dc.run_calibration(["DIST01"], output_dir=tmp_path, table_paths=paths, calibration_run_id="run-b")
    second_ids = set(pd.read_csv(second["threshold_grid"])["calibration_id"])

    assert first_ids == second_ids


def test_build_review_bundle_and_validate_review(tmp_path):
    paths = _calibration_fixture(tmp_path)
    dc.run_calibration(["DIST01"], output_dir=tmp_path, table_paths=paths, calibration_run_id="run-a")

    bundle_path = dc.build_review_bundle("DIST01", output_dir=tmp_path, top_n=3)
    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))

    assert bundle["candidate_id"] == "DIST01"
    assert len(bundle["top_findings"]) <= 3
    assert bundle["input_file_hashes"]["private_markets_holdings.csv"]["status"] == "present"

    review = {
        "schema_version": "1.0",
        "candidate_id": "DIST01",
        "calibration_id": bundle["calibration_id"],
        "verdict": "useful_signal",
        "confidence": "medium",
        "mechanism_assessment": "The examples show a fair value distribution shift that needs source review.",
        "false_positive_assessment": "Some hits may be true portfolio growth rather than extraction defects.",
        "threshold_assessment": "The tested threshold is plausible but should remain report-only.",
        "examples_reviewed": [item["granularity_key"] for item in bundle["top_findings"][:1]],
        "evidence_refs": [{"evidence_id": "top_findings", "supports": "Shows the selected diagnostic examples."}],
        "recommended_action": "keep_report_only",
        "rationale": "The signal is useful for triage but not enough for a production warning.",
        "residual_risk": "The bundle does not include raw filing source rows.",
        "anti_sycophancy_check": "No promotion is recommended without stronger evidence.",
    }
    review_path = tmp_path / "diagnostic_calibration" / "reviews" / f"{bundle['calibration_id']}.json"
    review_path.parent.mkdir(parents=True, exist_ok=True)
    review_path.write_text(json.dumps(review), encoding="utf-8")

    assert dc.validate_review(review_path, output_dir=tmp_path) == []
    assert dc.summarize_reviews(output_dir=tmp_path).exists()
    summary = _read_csv(tmp_path / "diagnostic_calibration" / "review_summary.csv")
    assert summary[0]["recommended_action"] == "keep_report_only"


def test_validate_review_rejects_promote_to_fail_and_unsupported_evidence(tmp_path):
    paths = _calibration_fixture(tmp_path)
    dc.run_calibration(["DIST01"], output_dir=tmp_path, table_paths=paths, calibration_run_id="run-a")
    bundle_path = dc.build_review_bundle("DIST01", output_dir=tmp_path, top_n=1)
    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    review = {
        "schema_version": "1.0",
        "candidate_id": "DIST01",
        "calibration_id": bundle["calibration_id"],
        "verdict": "useful_signal",
        "confidence": "high",
        "mechanism_assessment": "This review tries to over-promote a weak diagnostic.",
        "false_positive_assessment": "False positives were not adequately tested.",
        "threshold_assessment": "The threshold is not justified by evidence.",
        "examples_reviewed": ["missing"],
        "evidence_refs": [{"evidence_id": "missing", "supports": "Missing evidence."}],
        "recommended_action": "promote_to_warn",
        "rationale": "promote_to_fail should never be allowed by this workflow.",
        "residual_risk": "The review lacks source-backed production evidence.",
        "anti_sycophancy_check": "This should fail validation.",
    }
    review_path = tmp_path / "diagnostic_calibration" / "reviews" / f"{bundle['calibration_id']}.json"
    review_path.parent.mkdir(parents=True, exist_ok=True)
    review_path.write_text(json.dumps(review), encoding="utf-8")

    errors = dc.validate_review(review_path, output_dir=tmp_path)

    assert any("unknown evidence_id" in error for error in errors)
    assert any("forbidden" in error for error in errors)
    assert any("promote_to_warn requires" in error for error in errors)
