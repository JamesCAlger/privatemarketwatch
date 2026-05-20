import json
from pathlib import Path

import jsonschema
import pandas as pd
import pytest

from pipeline.bdc_cik_validator import (
    build_cik_validation_packet,
    gav_condition,
    gav_gate_role,
    validation_matrix_cell,
)


def _gav_row(**overrides):
    row = {
        "cik": "0000000100",
        "report_date": "2025-03-31",
        "comparison_source": "investments_at_fair_value",
        "comparison_value": "1000",
        "comparison_confidence": "STRONG",
        "denominator_scope": "investment_fair_value",
        "flag": "ok",
        "reconciliation_status": "PASS",
        "gav_ratio": "1.0",
        "gav_ratio_adjusted": "1.0",
        "gav_evidence_scope": "indexable_fv_reconciled",
    }
    row.update(overrides)
    return row


def test_gav_gate_roles_follow_denominator_strength():
    assert gav_gate_role(_gav_row()) == "strong_gate"
    assert gav_gate_role(_gav_row(
        comparison_source="total_assets_companyfacts",
        comparison_confidence="MODERATE",
        denominator_scope="full_fund_assets_proxy",
    )) == "moderate_gate"
    assert gav_gate_role(_gav_row(
        comparison_source="total_assets_nport",
        comparison_confidence="WEAK",
    )) == "context_only"
    assert gav_gate_role(_gav_row(
        gav_evidence_scope="non_indexable_denominator",
    )) == "context_only"


@pytest.mark.parametrize(
    ("source_blockers", "gav_cond", "expected"),
    [
        (True, "under_coverage", "source_blockers_gav_undercoverage"),
        (True, "ok", "source_blockers_gav_ok"),
        (False, "over_coverage", "source_ok_gav_overcoverage"),
        (False, "missing_or_weak", "source_ok_gav_context_only"),
    ],
)
def test_validation_matrix_cells(source_blockers, gav_cond, expected):
    assert validation_matrix_cell(source_blockers, gav_cond) == expected


def test_packet_includes_source_blockers_and_gav_undercoverage():
    packet = build_cik_validation_packet(
        "100",
        ["2025-03-31"],
        holdings_df=pd.DataFrame([{
            "cik": "100",
            "report_date": "2025-03-31",
            "fair_value": "100",
            "issuer_name": "Issuer A",
        }]),
        source_residual_df=pd.DataFrame([{
            "cik": "0000000100",
            "report_date": "2025-03-31",
            "blocking_issue": True,
            "mechanism": "blocking_source_only_position",
            "issue_count": "1",
        }]),
        gav_df=pd.DataFrame([_gav_row(
            flag="under_coverage",
            reconciliation_status="WARN",
            gav_ratio="0.2",
            gav_ratio_adjusted="0.2",
        )]),
    )

    assert packet["source_reconciliation"]["blocker_count"] == 1
    assert packet["gav_reconciliation"]["rows"][0]["gate_role"] == "strong_gate"
    assert packet["validation_matrix"][0]["matrix_cell"] == (
        "source_blockers_gav_undercoverage"
    )


def test_packet_distinguishes_source_blockers_with_acceptable_gav():
    packet = build_cik_validation_packet(
        "100",
        ["2025-03-31"],
        source_only_df=pd.DataFrame([{
            "cik": "100",
            "report_date": "2025-03-31",
            "is_blocking": "true",
            "mechanism": "blocking_source_short_plain_unresolved",
        }]),
        gav_df=pd.DataFrame([_gav_row()]),
    )

    assert packet["source_reconciliation"]["blocker_count"] == 1
    assert packet["validation_matrix"][0]["matrix_cell"] == "source_blockers_gav_ok"


def test_packet_surfaces_overcoverage_and_aggregate_leak_context():
    packet = build_cik_validation_packet(
        "100",
        ["2025-03-31"],
        gav_df=pd.DataFrame([_gav_row(
            flag="over_coverage",
            reconciliation_status="WARN",
            gav_ratio="1.8",
            gav_ratio_adjusted="1.8",
        )]),
        purity_df=pd.DataFrame([{
            "cik": "100",
            "report_date": "2025-03-31",
            "subtotal_candidate_rows": "2",
            "duplicate_dimension_candidate_rows": "3",
        }]),
    )

    assert packet["validation_matrix"][0]["matrix_cell"] == "source_ok_gav_overcoverage"
    assert packet["position_quality_context"]["aggregate_leak_context"] == {
        "subtotal_candidate_rows": 2,
        "duplicate_dimension_candidate_rows": 3,
    }


def test_packet_treats_weak_or_missing_gav_as_context_only():
    weak = _gav_row(
        comparison_source="total_assets_nport",
        comparison_confidence="WEAK",
        flag="under_coverage",
        reconciliation_status="WARN",
    )

    assert gav_condition(weak) == "weak_context"
    packet = build_cik_validation_packet("100", ["2025-03-31"], gav_df=pd.DataFrame([weak]))

    assert packet["gav_reconciliation"]["rows"][0]["gate_role"] == "context_only"
    assert packet["validation_matrix"][0]["matrix_cell"] == "source_ok_gav_context_only"


def test_draft_correction_schema_requires_source_and_gav_sections():
    schema = json.loads(Path(
        "schemas/bdc_cik_validator/draft_correction.schema.json"
    ).read_text(encoding="utf-8"))
    valid = {
        "schema_version": "bdc-cik-draft-correction.v1",
        "cik": "0000000100",
        "report_dates": ["2025-03-31"],
        "correction_type": "subtotal_pattern",
        "mechanism": "category header without position-level entity evidence",
        "evidence": [{
            "evidence_id": "source_reconciliation",
            "claim": "Row has no source position identity.",
            "supports": "Source reconciliation classifies it as pipeline-only.",
        }],
        "source_reconciliation_effect": {
            "expected_effect": "improves",
            "row_level_evidence_refs": ["source_reconciliation"],
            "worsens_row_level_reconciliation": False,
        },
        "gav_reconciliation_effect": {
            "expected_effect": "improves",
            "gate_role": "strong_gate",
            "denominator_strength": "investments_at_fair_value",
            "expected_adjusted_ratio_direction": "toward_range",
            "is_primary_justification": False,
            "source_gav_conflict_classification": "none",
            "residual_if_source_and_gav_disagree": "No disagreement expected.",
        },
        "acceptance_checks": {
            "not_accepted_on_gav_improvement_alone": True,
            "row_level_source_evidence_required": True,
            "strong_gav_residual_explained_when_claiming_completeness": True,
            "weak_denominator_not_hard_gate": True,
        },
        "confidence": "high",
        "residual_risk": "Future filings may use the same wording for a real entity.",
    }
    jsonschema.Draft202012Validator(schema).validate(valid)

    invalid = dict(valid)
    invalid.pop("gav_reconciliation_effect")
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.Draft202012Validator(schema).validate(invalid)


def test_draft_schema_rejects_gav_improvement_as_primary_justification():
    schema = json.loads(Path(
        "schemas/bdc_cik_validator/draft_correction.schema.json"
    ).read_text(encoding="utf-8"))
    invalid = {
        "schema_version": "bdc-cik-draft-correction.v1",
        "cik": "0000000100",
        "report_dates": ["2025-03-31"],
        "correction_type": "row_correction",
        "mechanism": "source row identity supported by cached source facts",
        "evidence": [{
            "evidence_id": "source_reconciliation",
            "claim": "Source supports the row.",
            "supports": "Cached facts include the identifier.",
        }],
        "source_reconciliation_effect": {
            "expected_effect": "improves",
            "row_level_evidence_refs": ["source_reconciliation"],
            "worsens_row_level_reconciliation": False,
        },
        "gav_reconciliation_effect": {
            "expected_effect": "improves",
            "gate_role": "strong_gate",
            "denominator_strength": "investments_at_fair_value",
            "expected_adjusted_ratio_direction": "toward_range",
            "is_primary_justification": True,
            "source_gav_conflict_classification": "none",
            "residual_if_source_and_gav_disagree": "No disagreement expected.",
        },
        "acceptance_checks": {
            "not_accepted_on_gav_improvement_alone": False,
            "row_level_source_evidence_required": True,
            "strong_gav_residual_explained_when_claiming_completeness": True,
            "weak_denominator_not_hard_gate": True,
        },
        "confidence": "medium",
        "residual_risk": "Residual risk is intentionally minimal here.",
    }

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.Draft202012Validator(schema).validate(invalid)
