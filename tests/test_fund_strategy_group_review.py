import csv
import json
from pathlib import Path

import pytest

from pipeline import fund_strategy_group_review as fsgr


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


def _candidate(
    *,
    cik: str,
    issuer_name: str,
    instrument_description: str = "Term Loan",
    fv: str,
    report_date: str,
    accession_number: str,
    status: str = "REVIEW",
    current: str = "PRIVATE_EQUITY_FUND",
    proposed: str = "PRIVATE_CREDIT_FUND",
) -> dict[str, str]:
    return {
        "correction_status": status,
        "rule_id": "FS03",
        "mechanism": "fund_holding_strategy_alignment",
        "confidence": "LOW",
        "residual_risk": "risk",
        "cik": cik,
        "entity_name": "Fund A",
        "report_date": report_date,
        "source": "bdc",
        "accession_number": accession_number,
        "bdc_investment_identifier": f"{issuer_name} {instrument_description}",
        "nport_holding_id": "",
        "issuer_name": issuer_name,
        "instrument_description": instrument_description,
        "asset_category": "FUND",
        "issuer_category": "FUND",
        "nport_asset_cat": "",
        "nport_issuer_type": "",
        "current_index_classification": current,
        "current_asset_class": "PRIVATE_EQUITY",
        "proposed_index_classification": proposed,
        "proposed_asset_class": "PRIVATE_CREDIT",
        "fund_strategy": "PRIVATE_CREDIT",
        "fund_strategy_source": "VEHICLE_TYPE_BDC",
        "fund_strategy_evidence": "vehicle_type=bdc",
        "row_source_evidence": "fund_row_evidence=issuer_or_asset_category",
        "affected_fair_value": fv,
        "before_metric": "before",
        "after_metric": "after",
    }


def test_build_grouped_worklist_is_deterministic_and_batches(tmp_path):
    input_file = tmp_path / "candidates.csv"
    output_dir = tmp_path / "review"
    rows = [
        _candidate(cik="1", issuer_name="Issuer B", fv="100", report_date="2025-03-31", accession_number="0001-1"),
        _candidate(cik="0000000001", issuer_name="Issuer B", fv="25", report_date="2025-06-30", accession_number="0001-2"),
        _candidate(cik="2", issuer_name="Issuer A", fv="200", report_date="2025-03-31", accession_number="0002-1"),
        _candidate(cik="3", issuer_name="Issuer C", fv="999", report_date="2025-03-31", accession_number="0003-1", status="APPLY"),
        _candidate(cik="4", issuer_name="Issuer D", fv="50", report_date="2025-03-31", accession_number="0004-1"),
    ]
    _write_csv(input_file, rows)

    stats = fsgr.build_grouped_worklist(input_file, output_dir, top_n=3, batch_size=2)

    worklist = _read_csv(output_dir / "grouped_worklist.csv")
    group_rows = _read_csv(output_dir / "group_rows.csv")
    assert stats["selected_group_count"] == 3
    assert stats["selected_row_count"] == 4
    assert [row["issuer_name"] for row in worklist] == ["Issuer A", "Issuer B", "Issuer D"]
    assert [row["affected_fair_value"] for row in worklist] == ["200.000000", "125.000000", "50.000000"]
    assert worklist[1]["row_count"] == "2"
    assert all(row["group_id"] in {group["group_id"] for group in worklist} for row in group_rows)
    assert len(_read_csv(output_dir / "batches" / "batch_001.csv")) == 2
    assert len(_read_csv(output_dir / "batches" / "batch_002.csv")) == 1

    first_ids = [row["group_id"] for row in worklist]
    fsgr.build_grouped_worklist(input_file, output_dir, top_n=3, batch_size=2)
    assert [row["group_id"] for row in _read_csv(output_dir / "grouped_worklist.csv")] == first_ids


def test_validate_verdict_rejects_confirmed_gap_without_evidence(tmp_path):
    output_dir = tmp_path / "review"
    bundle_dir = output_dir / "bundles"
    verdict_dir = output_dir / "verdicts"
    bundle_dir.mkdir(parents=True)
    verdict_dir.mkdir(parents=True)
    (bundle_dir / "G1.json").write_text("{}", encoding="utf-8")
    verdict = {
        "group_id": "G1",
        "verdict": "CONFIRMED_RULE_GAP",
        "confidence": "HIGH",
        "mechanism": "fund_holding_strategy_alignment",
        "evidence_refs": [],
        "recommended_next_action": "GLOBAL_DETERMINISTIC_RULE",
        "residual_risk": "low",
        "reviewer_notes": "source evidence supports the mechanism",
    }
    verdict_file = verdict_dir / "G1.json"
    verdict_file.write_text(json.dumps(verdict), encoding="utf-8")

    errors = fsgr.validate_verdict_file(verdict_file, output_dir)

    assert any("evidence_refs" in error for error in errors)


def test_summarize_verdicts_reconciles_counts_and_fv(tmp_path):
    output_dir = tmp_path / "review"
    (output_dir / "verdicts").mkdir(parents=True)
    (output_dir / "bundles").mkdir(parents=True)
    worklist = [
        {
            "group_id": "G1",
            "affected_fair_value": "100.000000",
            "row_count": "2",
            "rule_id": "FS03",
            "mechanism": "fund_holding_strategy_alignment",
            "fund_strategy": "PRIVATE_CREDIT",
            "current_index_classification": "PRIVATE_EQUITY_FUND",
            "proposed_index_classification": "PRIVATE_CREDIT_FUND",
        },
        {
            "group_id": "G2",
            "affected_fair_value": "50.000000",
            "row_count": "1",
            "rule_id": "FS02",
            "mechanism": "insufficient_row_evidence",
            "fund_strategy": "PRIVATE_CREDIT",
            "current_index_classification": "DIRECT_REAL_ESTATE",
            "proposed_index_classification": "DIRECT_REAL_ESTATE",
        },
    ]
    _write_csv(output_dir / "grouped_worklist.csv", worklist)
    _write_csv(output_dir / "group_rows.csv", [{"group_id": "G1"}, {"group_id": "G2"}])
    for group_id in ["G1", "G2"]:
        (output_dir / "bundles" / f"{group_id}.json").write_text("{}", encoding="utf-8")
    (output_dir / "verdicts" / "G1.json").write_text(
        json.dumps(
            {
                "group_id": "G1",
                "verdict": "CONFIRMED_RULE_GAP",
                "confidence": "HIGH",
                "mechanism": "fund_holding_strategy_alignment",
                "evidence_refs": ["bundle.source_evidence[0].snippets[0]"],
                "recommended_next_action": "PER_CIK_CONFIG",
                "residual_risk": "limited to this CIK pattern",
                "reviewer_notes": "source evidence supports a per-CIK mechanism",
            }
        ),
        encoding="utf-8",
    )
    (output_dir / "verdicts" / "G2.json").write_text(
        json.dumps(
            {
                "group_id": "G2",
                "verdict": "INSUFFICIENT_EVIDENCE",
                "confidence": "LOW",
                "mechanism": "insufficient_row_evidence",
                "evidence_refs": [],
                "recommended_next_action": "MANUAL_REVIEW",
                "residual_risk": "source context missing",
                "reviewer_notes": "bundle fields do not prove row-level classification",
            }
        ),
        encoding="utf-8",
    )

    summary = fsgr.summarize_verdicts(output_dir)
    summary_rows = _read_csv(output_dir / "summary.csv")

    assert summary["counts"] == {"CONFIRMED_RULE_GAP": 1, "INSUFFICIENT_EVIDENCE": 1}
    assert summary["fv_by_verdict"]["CONFIRMED_RULE_GAP"] == pytest.approx(100.0)
    assert summary["unresolved_fv"] == pytest.approx(50.0)
    assert len(summary_rows) == 2
    assert (output_dir / "summary.md").exists()
