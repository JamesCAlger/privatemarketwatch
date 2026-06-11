"""Tests for the v1 wrapper cohort quality gate."""

from __future__ import annotations

import json

import pandas as pd

from scripts.wrapper_v1_quality_gate import build_gate, load_manifest


def _manifest(path, ciks):
    path.write_text(
        json.dumps({
            "schema_version": "wrapper-cohort-manifest.v1",
            "cohort_id": "test_cohort",
            "cohort_basis": "unit_test",
            "entries": [
                {"rank": idx + 1, "cik": cik, "wrapper_file": f"{cik}.json"}
                for idx, cik in enumerate(ciks)
            ],
        }),
        encoding="utf-8",
    )


def test_manifest_requires_exact_39_unique_ciks(tmp_path):
    manifest = tmp_path / "manifest.json"
    _manifest(manifest, [str(i).zfill(10) for i in range(38)])

    try:
        load_manifest(manifest)
    except ValueError as exc:
        assert "Expected 39" in str(exc)
    else:
        raise AssertionError("manifest with 38 entries should fail")

    duplicate_ciks = [str(i).zfill(10) for i in range(38)] + ["0000000001"]
    _manifest(manifest, duplicate_ciks)
    try:
        load_manifest(manifest)
    except ValueError as exc:
        assert "Duplicate CIKs" in str(exc)
    else:
        raise AssertionError("manifest with duplicate CIKs should fail")


def test_gate_fails_only_current_production_blockers(tmp_path):
    ciks = [str(i).zfill(10) for i in range(1, 40)]
    manifest = tmp_path / "manifest.json"
    _manifest(manifest, ciks)

    source_residuals = tmp_path / "source_reconciliation_residual_classification.csv"
    pd.DataFrame([
        {
            "cik": ciks[0],
            "report_date": "2025-03-31",
            "blocking_issue": "True",
            "issue_count": "5",
            "affected_source_fair_value": "100",
        },
        {
            "cik": ciks[1],
            "report_date": "2024-12-31",
            "blocking_issue": "True",
            "issue_count": "7",
            "affected_source_fair_value": "100",
        },
    ]).to_csv(source_residuals, index=False)

    validate_residuals = tmp_path / "validate_all_residual_summary.csv"
    pd.DataFrame([
        {"cik": ciks[2], "issue_count": "20", "fail_count": "0"},
    ]).to_csv(validate_residuals, index=False)

    rules = tmp_path / "validation_rules_aggregate.csv"
    pd.DataFrame([
        {"rule_id": "RI03", "promoted": "True", "status": "PASS"},
    ]).to_csv(rules, index=False)

    gav = tmp_path / "holdings_gav_reconciliation.csv"
    pd.DataFrame([
        {
            "cik": cik,
            "report_date": "2026-03-31",
            "flag": "no_comparison",
            "reconciliation_status": "SKIP",
            "gav_ratio_adjusted": "",
        }
        for cik in ciks
    ]).to_csv(gav, index=False)

    frontend = tmp_path / "fund_list.json"
    frontend.write_text(
        json.dumps([
            {"cik": cik, "validationTier": "VERIFIED", "gavStatus": "PASS"}
            for cik in ciks
        ]),
        encoding="utf-8",
    )

    gate = build_gate(
        manifest_path=manifest,
        source_residual_path=source_residuals,
        validate_residual_path=validate_residuals,
        validation_rules_path=rules,
        gav_path=gav,
        frontend_fund_list_path=frontend,
    )
    by_cik = gate.set_index("cik")

    assert by_cik.loc[ciks[0], "status"] == "FAIL"
    assert by_cik.loc[ciks[0], "latest_source_blocking_issue_count"] == 5
    assert by_cik.loc[ciks[1], "status"] == "FAIL"
    assert by_cik.loc[ciks[2], "status"] == "PASS"
    assert by_cik.loc[ciks[2], "validation_residual_issue_count"] == 20


def test_gate_fails_promoted_rule_failure_and_frontend_gav_warn(tmp_path):
    ciks = [str(i).zfill(10) for i in range(1, 40)]
    manifest = tmp_path / "manifest.json"
    _manifest(manifest, ciks)

    empty_source = tmp_path / "source_reconciliation_residual_classification.csv"
    pd.DataFrame(columns=["cik", "report_date", "blocking_issue", "issue_count"]).to_csv(empty_source, index=False)
    empty_residuals = tmp_path / "validate_all_residual_summary.csv"
    pd.DataFrame(columns=["cik", "issue_count", "fail_count"]).to_csv(empty_residuals, index=False)
    rules = tmp_path / "validation_rules_aggregate.csv"
    pd.DataFrame([{"rule_id": "RI07", "promoted": "True", "status": "FAIL"}]).to_csv(rules, index=False)
    gav = tmp_path / "holdings_gav_reconciliation.csv"
    pd.DataFrame(columns=["cik", "report_date", "flag", "reconciliation_status", "gav_ratio_adjusted"]).to_csv(gav, index=False)
    frontend = tmp_path / "fund_list.json"
    frontend.write_text(
        json.dumps([
            {
                "cik": cik,
                "validationTier": "VERIFIED",
                "gavStatus": "WARN" if idx == 0 else "PASS",
            }
            for idx, cik in enumerate(ciks)
        ]),
        encoding="utf-8",
    )

    gate = build_gate(
        manifest_path=manifest,
        source_residual_path=empty_source,
        validate_residual_path=empty_residuals,
        validation_rules_path=rules,
        gav_path=gav,
        frontend_fund_list_path=frontend,
    )

    assert set(gate["status"]) == {"FAIL"}
    first = gate.set_index("cik").loc[ciks[0]]
    assert "promoted_validation_rule_failures" in first["blocking_reasons"]
    assert "frontend_gav_not_pass_or_skip" in first["blocking_reasons"]
