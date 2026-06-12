import json
from unittest import mock

import pandas as pd
import pytest

from pipeline.bdc_xbrl_wrapper_oracle import (
    AGENT_CLUSTER_PACKET_COLUMNS,
    AGENT_ISSUE_PACKET_COLUMNS,
    AGENT_VERDICT_SUMMARY_COLUMNS,
    BASELINE_COMPARISON_COLUMNS,
    COLUMN_DRIFT_EXAMPLE_COLUMNS,
    COLUMN_DRIFT_SUMMARY_COLUMNS,
    HIGH_FV_UNCLASSIFIED_CLUSTER_COLUMNS,
    ORACLE_SUMMARY_COLUMNS,
    PARSED_FIELD_QUALITY_COLUMNS,
    PROMOTION_GATE_COLUMNS,
    ROW_DELTA_ATTRIBUTION_COLUMNS,
    _UNCLASSIFIED_RATE_QOQ_JUMP_THRESHOLD,
    _append_parsed_field_quality_summary,
    _build_agent_cluster_packets,
    _build_agent_issue_packets,
    _build_cost_fv_outlier_packets,
    _build_column_drift_packets,
    _build_parsed_field_quality_packets,
    _build_high_fv_unclassified_clusters,
    _build_row_delta_attribution,
    _build_source_corrupted_identifier_packets,
    _build_source_verbose_identifier_packets,
    _materiality_metrics,
    build_agent_verdict_summary,
    build_exception_proposals,
    build_residual_wrapper_queue,
    build_wrapper_oracle_outputs,
    build_wrapper_profile_for_cik,
    run_wrapper_oracle_trial,
    evaluate_promotion_gate,
    run_promotion_trial,
    run_wrapper_queue,
    validate_agent_verdict_records,
    validate_wrapper_definition_structure,
    validate_wrapper_json_coherence,
)
from pipeline.bdc_xbrl_oracle_exceptions import (
    ORACLE_EXCEPTION_SCHEMA_VERSION,
    load_bdc_xbrl_oracle_exceptions,
)
from pipeline.source_reconciliation import DETAIL_COLUMNS
from pipeline.wrapper_content_signatures import (
    Archetype,
    FieldSignature,
    RateSanity,
    UnclassifiedRate,
    WrapperDefinition,
    validate_content_signatures,
)


def _detail(rows):
    defaults = {
        "status": "matched",
        "match_tier": "",
        "issue_severity": "",
        "residual_class": "reconciled",
        "blocking_issue": False,
        "calibrated_status": "reconciled",
        "calibration_reason": "",
        "cik": "0001786108",
        "entity_name": "Trinity Capital Inc.",
        "report_date": "2024-12-31",
        "period": "2024-12-31",
        "accession_number": "0001786108-25-000001",
        "form_type": "10-K",
        "filing_date": "2025-03-01",
        "context_id": "ctx",
        "source_row_id": "1",
        "output_row_id": "",
        "raw_investment_identifier": "Portfolio Company Debt Securities- Europe Industrials Aledia, Inc.",
        "normalized_investment_identifier": "portfolio company debt securities europe industrials aledia inc",
        "dimensions_raw": "",
        "concept_names": "InvestmentOwnedAtFairValue",
        "source_wrapper_disposition": "rollup_candidate",
        "source_wrapper_rule_id": "TRINITY_DEBT_ISSUER_ROLLUP_V1",
        "source_wrapper_family": "debt",
        "source_wrapper_parent_key": "portfolio company debt securities europe industrials aledia inc",
        "source_wrapper_position_key": "",
        "source_wrapper_structured_leaf_key": "",
        "source_wrapper_investment_date_key": "",
        "source_wrapper_maturity_date_key": "",
        "source_wrapper_rate_key": "",
        "source_wrapper_signature_status": "pass",
        "source_wrapper_unparsed_remainder": "",
        "output_wrapper_disposition": "",
        "output_wrapper_rule_id": "",
        "output_wrapper_family": "",
        "output_wrapper_parent_key": "",
        "output_wrapper_position_key": "",
        "output_wrapper_structured_leaf_key": "",
        "output_wrapper_investment_date_key": "",
        "output_wrapper_maturity_date_key": "",
        "output_wrapper_rate_key": "",
        "output_wrapper_signature_status": "",
        "output_wrapper_unparsed_remainder": "",
        "source_fair_value": 3000000,
        "output_fair_value": "",
        "source_cost": "",
        "output_cost": "",
        "source_principal_amount": "",
        "output_principal_amount": "",
        "source_shares_held": "",
        "output_shares_held": "",
        "source_interest_rate": "",
        "output_interest_rate": "",
        "source_basis_spread": "",
        "output_basis_spread": "",
        "source_pik_rate": "",
        "output_pik_rate": "",
        "mismatched_fields": "",
        "issuer_name": "",
        "instrument_description": "",
        "index_classification": "",
        "asset_category": "",
        "issuer_category": "",
        "evidence": "",
    }
    merged_rows = []
    for row in rows:
        merged = {**defaults, **row}
        if merged.get("source_wrapper_disposition") == "rollup_candidate":
            merged["source_wrapper_disposition"] = "debt_issuer_rollup"
        merged_rows.append({col: merged.get(col, "") for col in DETAIL_COLUMNS})
    return pd.DataFrame(merged_rows)


def test_oracle_passes_cleared_wrapper_rollup():
    detail = _detail([{
        "status": "documented_source_rollup_exact",
        "residual_class": "documented_exclusion",
        "calibrated_status": "documented_source_rollup_exact",
        "evidence": "documented source rollup exact; child_output_count=2; child_output_fair_value=3000000.0",
    }])

    summary, cleared, remaining, mechanisms = build_wrapper_oracle_outputs(detail)

    assert len(cleared) == 1
    assert remaining.empty
    assert mechanisms.empty
    assert summary.iloc[0]["oracle_status"] == "pass"
    assert summary.iloc[0]["cleared_rollup_rows"] == 1


def test_oracle_fails_when_wrapper_blocker_remains():
    detail = _detail([{
        "status": "missing_from_pipeline",
        "blocking_issue": True,
        "residual_class": "row_identity",
        "calibrated_status": "blocking_missing_from_pipeline",
        "source_wrapper_disposition": "debt_position_leaf",
        "source_wrapper_rule_id": "TRINITY_DEBT_LEAF_V1",
        "source_wrapper_position_key": "portfolio company debt securities europe industrials aledia inc",
    }])

    summary, cleared, remaining, mechanisms = build_wrapper_oracle_outputs(detail)

    assert cleared.empty
    assert len(remaining) == 1
    assert mechanisms.iloc[0]["mechanism"] == "leaf_no_output_candidate"
    assert summary.iloc[0]["oracle_status"] == "fail"
    assert "wrapper_blockers_remaining" in summary.iloc[0]["oracle_fail_reasons"]


def test_oracle_treats_total_rollup_disposition_as_diagnostic():
    detail = _detail([{
        "status": "missing_from_pipeline",
        "blocking_issue": True,
        "residual_class": "row_identity",
        "calibrated_status": "blocking_missing_from_pipeline",
        "source_wrapper_disposition": "mixed_total_rollup",
        "source_wrapper_rule_id": "MIDCAP_FINANCIAL_MIXED_TOTAL_ROLLUP_V1",
        "source_wrapper_family": "mixed",
        "source_wrapper_parent_key": "total healthcare pharmaceuticals",
        "source_wrapper_position_key": "total healthcare pharmaceuticals",
        "raw_investment_identifier": "Total Healthcare & Pharmaceuticals",
        "normalized_investment_identifier": "total healthcare pharmaceuticals",
    }])

    summary, _cleared, remaining, mechanisms = build_wrapper_oracle_outputs(detail)

    assert len(remaining) == 1
    assert mechanisms.iloc[0]["mechanism"] == "total_rollup_no_child_tie"
    assert summary.iloc[0]["oracle_status"] == "fail"
    assert "remaining_total_rollup_no_child_tie" in summary.iloc[0]["oracle_fail_reasons"]
    assert "wrapper_blockers_remaining" not in summary.iloc[0]["oracle_fail_reasons"]


def test_oracle_fails_unclassified_trinity_prefix_row():
    detail = _detail([{
        "status": "missing_from_pipeline",
        "blocking_issue": True,
        "source_wrapper_disposition": "",
        "source_wrapper_rule_id": "",
        "source_wrapper_parent_key": "",
        "source_wrapper_signature_status": "",
    }])

    summary, _cleared, _remaining, mechanisms = build_wrapper_oracle_outputs(detail)

    assert summary.iloc[0]["oracle_status"] == "fail"
    assert "unclassified_prefix_rows" in summary.iloc[0]["oracle_fail_reasons"]
    assert mechanisms.iloc[0]["mechanism"] == "unclassified_signature"


def test_oracle_flags_leaf_present_in_raw_missing_from_unified():
    position_key = (
        "portfolio company debt securities europe industrials aledia inc "
        "type of investment equipment financing"
    )
    detail = _detail([{
        "status": "missing_from_pipeline",
        "blocking_issue": True,
        "source_wrapper_disposition": "debt_position_leaf",
        "source_wrapper_rule_id": "TRINITY_DEBT_LEAF_V1",
        "source_wrapper_position_key": position_key,
    }])
    raw_keys = {("0001786108", "2024-12-31", "0001786108-25-000001", position_key)}

    summary, _cleared, _remaining, mechanisms = build_wrapper_oracle_outputs(
        detail,
        raw_bdc_position_keys=raw_keys,
        unified_position_keys=set(),
    )

    assert summary.iloc[0]["oracle_status"] == "fail"
    assert mechanisms.iloc[0]["mechanism"] == "leaf_present_in_raw_missing_from_unified"
    assert mechanisms.iloc[0]["raw_bdc_present_count"] == 1
    assert mechanisms.iloc[0]["unified_present_count"] == 0


def test_oracle_classifies_aggregate_and_non_private_rows_as_diagnostic():
    detail = _detail([
        {
            "status": "missing_from_pipeline",
            "blocking_issue": True,
            "source_wrapper_disposition": "aggregate",
            "source_wrapper_rule_id": "TRINITY_DEBT_AGGREGATE_V1",
            "raw_investment_identifier": "Portfolio Company Debt Securities- Sub-total: Education Technology",
        },
        {
            "status": "missing_from_pipeline",
            "blocking_issue": True,
            "source_wrapper_disposition": "non_private_market",
            "source_wrapper_rule_id": "TRINITY_DEBT_NON_PRIVATE_MARKET_V1",
            "raw_investment_identifier": "Portfolio Company Debt Securities- Cash and money market funds",
        },
    ])

    summary, _cleared, _remaining, mechanisms = build_wrapper_oracle_outputs(detail)

    assert set(mechanisms["mechanism"]) == {"aggregate", "cash_or_money_market"}
    assert summary.iloc[0]["remaining_wrapper_blocking_rows"] == 0
    assert summary.iloc[0]["oracle_status"] == "pass"


def test_oracle_splits_rollup_child_sum_mismatch_from_no_child_tie():
    detail = _detail([
        {
            "cik": "0001377936",
            "entity_name": "Saratoga Investment Corp.",
            "report_date": "2025-02-28",
            "accession_number": "0001213900-25-040617",
            "status": "missing_from_pipeline",
            "blocking_issue": True,
            "source_wrapper_disposition": "mixed_category_rollup",
            "source_wrapper_rule_id": "SARATOGA_MIXED_CATEGORY_ROLLUP_V1",
            "source_wrapper_family": "mixed",
            "source_wrapper_parent_key": "direct selling software",
            "source_row_id": "parent",
            "raw_investment_identifier": "Non-control/Non-affiliate investments - 229.3% - Direct Selling Software",
            "source_fair_value": 24063677,
        },
        {
            "cik": "0001377936",
            "entity_name": "Saratoga Investment Corp.",
            "report_date": "2025-02-28",
            "accession_number": "0001213900-25-040617",
            "status": "matched",
            "blocking_issue": False,
            "source_wrapper_disposition": "mixed_position_leaf",
            "source_wrapper_family": "mixed",
            "source_wrapper_parent_key": "exigo llc direct selling software first lien",
            "source_row_id": "child-a",
            "raw_investment_identifier": "Exigo, LLC - Direct Selling Software - First Lien",
            "source_fair_value": 23352713,
        },
        {
            "cik": "0001377936",
            "entity_name": "Saratoga Investment Corp.",
            "report_date": "2025-02-28",
            "accession_number": "0001213900-25-040617",
            "status": "matched",
            "blocking_issue": False,
            "source_wrapper_disposition": "mixed_position_leaf",
            "source_wrapper_family": "mixed",
            "source_wrapper_parent_key": "exigo llc direct selling software revolver",
            "source_row_id": "child-b",
            "raw_investment_identifier": "Exigo, LLC - Direct Selling Software - Revolver",
            "source_fair_value": -18500,
        },
    ])

    _summary, _cleared, _remaining, mechanisms = build_wrapper_oracle_outputs(
        detail,
        cik="0001377936",
    )

    row = mechanisms.iloc[0]
    assert row["mechanism"] == "category_rollup_source_child_fv_mismatch"
    assert row["candidate_source_child_count"] == 2
    assert row["candidate_source_child_fair_value"] == 23334213


def test_residual_queue_ranks_blocking_ciks_by_rows_then_fair_value():
    clusters = pd.DataFrame([
        {
            "cik": "1786108",
            "entity_name": "Trinity Capital Inc.",
            "mechanism": "blocking_source_position_like_parser_mismatch",
            "is_blocking": "true",
            "row_count": "5",
            "source_fair_value": "100",
            "sample_identifiers": "Portfolio Company Debt Securities- A",
        },
        {
            "cik": "0000000002",
            "entity_name": "Example BDC",
            "mechanism": "blocking_source_pct_leaf_parser_mismatch",
            "is_blocking": "true",
            "row_count": "7",
            "source_fair_value": "50",
            "sample_identifiers": "Total investments",
        },
        {
            "cik": "0000000003",
            "entity_name": "Non Blocking BDC",
            "mechanism": "documented",
            "is_blocking": "false",
            "row_count": "99",
            "source_fair_value": "999",
            "sample_identifiers": "Ignored",
        },
    ])

    queue = build_residual_wrapper_queue(clusters, top=10)

    assert queue["cik"].tolist() == ["0000000002", "0001786108"]
    assert queue.iloc[1]["supported_wrapper"] == True
    assert "blocking_source_position_like_parser_mismatch:5" in queue.iloc[1]["mechanisms"]


def test_wrapper_profile_classifies_candidate_actions():
    clusters = pd.DataFrame([
        {
            "cik": "0000000002",
            "entity_name": "Example BDC",
            "report_date": "2025-12-31",
            "is_blocking": "true",
            "row_count": "2",
            "source_fair_value": "10",
            "sample_identifiers": "Portfolio Company Cash and Cash Equivalents",
        },
        {
            "cik": "0000000002",
            "entity_name": "Example BDC",
            "report_date": "2025-12-31",
            "is_blocking": "true",
            "row_count": "3",
            "source_fair_value": "20",
            "sample_identifiers": "Investment Debt - Acme LLC Type of Investment Secured Loan",
        },
        {
            "cik": "0000000002",
            "entity_name": "Example BDC",
            "report_date": "2025-12-31",
            "is_blocking": "true",
            "row_count": "4",
            "source_fair_value": "30",
            "sample_identifiers": "10.2% - Software - Common Stock",
        },
    ])

    profile, candidates = build_wrapper_profile_for_cik(clusters, "2")

    assert set(profile["recommended_action"]) == {
        "likely_non_private_market",
        "add_per_cik_wrapper",
        "needs_html_evidence",
    }
    assert set(candidates["candidate_disposition"]) == {
        "non_private_market",
        "position_leaf",
        "pct_prefix_signature",
    }


def test_run_wrapper_queue_writes_profiles_without_promoting_unsupported_specs(tmp_path):
    clusters = pd.DataFrame([
        {
            "cik": "0000000002",
            "entity_name": "Example BDC",
            "report_date": "2025-12-31",
            "mechanism": "blocking_source_position_like_parser_mismatch",
            "is_blocking": "true",
            "row_count": "3",
            "source_fair_value": "20",
            "sample_identifiers": "Investment Debt - Acme LLC Type of Investment Secured Loan",
        },
    ])
    clusters_file = tmp_path / "clusters.csv"
    clusters.to_csv(clusters_file, index=False)

    queue, summary = run_wrapper_queue(
        residual_clusters_file=clusters_file,
        output_dir=tmp_path / "queue",
        top=10,
    )

    assert queue.iloc[0]["supported_wrapper"] == False
    assert summary.iloc[0]["status"] == "profiled"
    assert (tmp_path / "queue" / "0000000002" / "profile.csv").exists()
    assert (tmp_path / "queue" / "0000000002" / "candidate_rules.csv").exists()


def test_profiler_normalizes_affiliation_prefix_without_promoting_non_artifact():
    clusters = pd.DataFrame([{
        "cik": "0001784700",
        "entity_name": "Varagon Capital Corp",
        "report_date": "2025-03-31",
        "is_blocking": "true",
        "row_count": "5",
        "source_fair_value": "100",
        "sample_identifiers": (
            "Non-Controlled/Non-Affiliated Investments - "
            "Debt Investments Software Example Borrower Term Loan Maturity Date 12/31/2030"
        ),
    }])

    profile, candidates = build_wrapper_profile_for_cik(clusters, "0001784700")

    assert not profile.iloc[0]["detected_prefix"].lower().startswith("non")
    assert "Debt Investments" in profile.iloc[0]["detected_prefix"]
    assert candidates.iloc[0]["recommended_action"] == "add_per_cik_wrapper"


# ---------------------------------------------------------------------------
# Coverage gate tests (Gap #1 and #2)
# ---------------------------------------------------------------------------


def _make_wrapper(
    *,
    max_pct: float = 0.05,
    max_fv_pct: float = 0.05,
    keywords: tuple[str, ...] = ("term loan",),
    archetypes: tuple | None = None,
) -> WrapperDefinition:
    """Build a minimal WrapperDefinition for testing."""
    if archetypes is None:
        archetypes = (
            Archetype(
                name="debt",
                description="Debt instruments",
                keywords=keywords,
                keyword_mode="any",
                field_signatures=(),
            ),
        )
    return WrapperDefinition(
        cik="0001786108",
        entity_name="Test BDC",
        version=1,
        archetypes=archetypes,
        unclassified_rate=UnclassifiedRate(max_pct=max_pct, max_fv_pct=max_fv_pct),
    )


def test_validate_content_signatures_includes_fv_columns():
    """validate_content_signatures should compute FV-weighted coverage metrics."""
    wrapper = _make_wrapper()
    holdings = pd.DataFrame({
        "investment_identifier": [
            "Acme Corp Term Loan",       # matches "term loan" -> classified
            "Beta Inc Term Loan",        # matches -> classified
            "Gamma LLC Equity",          # no match -> unclassified
        ],
        "fair_value": [1000000, 500000, 2000000],
        "report_date": ["2024-12-31", "2024-12-31", "2024-12-31"],
    })

    summary, violations = validate_content_signatures(wrapper, holdings)

    assert len(summary) == 1
    row = summary.iloc[0]
    assert row["total_rows"] == 3
    assert row["classified_rows"] == 2
    assert row["unclassified_rows"] == 1
    # FV columns
    assert row["total_fv"] == 3500000.0
    assert row["classified_fv"] == 1500000.0
    assert row["unclassified_fv"] == 2000000.0
    # FV rate: 2M / 3.5M ~= 0.571
    assert row["unclassified_fv_rate"] > 0.5
    assert row["unclassified_fv_rate_status"] == "fail"  # exceeds 5% threshold
    # Row rate: 1/3 ~= 0.333
    assert row["unclassified_rate_status"] == "fail"  # exceeds 5%


def test_validate_content_signatures_falls_back_when_preferred_text_is_blank():
    wrapper = _make_wrapper(keywords=("advanced dermatology",))
    holdings = pd.DataFrame({
        "instrument_description": ["", "Unmatched text"],
        "bdc_investment_identifier": [
            "Advanced Dermatology & Cosmetic Surgery",
            "Other issuer",
        ],
        "fair_value": [1000000, 100],
        "report_date": ["2025-03-31", "2025-03-31"],
    })

    summary, _ = validate_content_signatures(wrapper, holdings)

    row = summary.iloc[0]
    assert row["classified_rows"] == 1
    assert row["unclassified_rows"] == 1
    assert row["classified_fv"] == 1000000.0


def test_validate_content_signatures_uses_wrapper_leaf_family_when_keywords_miss():
    wrapper = _make_wrapper(keywords=("term loan",))
    holdings = pd.DataFrame({
        "instrument_description": [""],
        "bdc_investment_identifier": ["Apex Service Partners LLC 3"],
        "wrapper_family": ["debt"],
        "wrapper_disposition": ["debt_position_leaf"],
        "fair_value": [56000000],
        "report_date": ["2025-03-31"],
    })

    summary, _ = validate_content_signatures(wrapper, holdings)

    row = summary.iloc[0]
    assert row["classified_rows"] == 1
    assert row["unclassified_rows"] == 0
    assert row["unclassified_fv_rate_status"] == "pass"


def test_validate_content_signatures_uses_wrapper_classifier_when_columns_absent():
    wrapper = _make_wrapper(keywords=("term loan",))
    holdings = pd.DataFrame({
        "bdc_investment_identifier": [
            "Portfolio Company Debt Securities- Europe Industrials Aledia, Inc."
            "Type of Investment Equipment Financing Investment Date March 31, 2022 "
            "Maturity Date April 1, 2025 Interest Rate Fixed interest rate 9.0%"
        ],
        "fair_value": [1000000],
        "report_date": ["2024-12-31"],
    })

    summary, _ = validate_content_signatures(wrapper, holdings)

    row = summary.iloc[0]
    assert row["classified_rows"] == 1
    assert row["unclassified_rows"] == 0


def test_validate_content_signatures_fv_pass_when_below_threshold():
    """FV rate should pass when unclassified FV is below the threshold."""
    wrapper = _make_wrapper(max_fv_pct=0.10)  # 10% threshold
    holdings = pd.DataFrame({
        "investment_identifier": [
            "Acme Corp Term Loan",
            "Beta Inc Term Loan",
            "Gamma LLC Equity",   # unclassified but small FV
        ],
        "fair_value": [5000000, 4000000, 100000],  # 100K / 9.1M ~= 1.1%
        "report_date": ["2024-12-31", "2024-12-31", "2024-12-31"],
    })

    summary, _ = validate_content_signatures(wrapper, holdings)

    row = summary.iloc[0]
    assert row["unclassified_fv_rate"] < 0.10
    assert row["unclassified_fv_rate_status"] == "pass"


def test_validate_content_signatures_uses_absolute_fv():
    """FV coverage should use absolute values to handle negative FV positions."""
    wrapper = _make_wrapper()
    holdings = pd.DataFrame({
        "investment_identifier": [
            "Acme Corp Term Loan",
            "Gamma LLC Equity",     # unclassified, negative FV
        ],
        "fair_value": [1000000, -500000],
        "report_date": ["2024-12-31", "2024-12-31"],
    })

    summary, _ = validate_content_signatures(wrapper, holdings)

    row = summary.iloc[0]
    assert row["total_fv"] == 1500000.0  # abs(1M) + abs(-500K)
    assert row["unclassified_fv"] == 500000.0  # abs(-500K)


def test_oracle_fails_when_unclassified_rate_exceeded():
    """Oracle should fail when content signature unclassified_rate_status is 'fail'."""
    detail = _detail([{
        "status": "documented_source_rollup_exact",
        "residual_class": "documented_exclusion",
        "calibrated_status": "documented_source_rollup_exact",
    }])

    def mock_cs(cik, holdings_df):
        return {"2024-12-31": {
            "pass_rate": 1.0,
            "violation_count": 0,
            "unclassified_rate": 0.15,
            "unclassified_rate_status": "fail",
            "unclassified_fv_rate": 0.01,
            "unclassified_fv_rate_status": "pass",
        }}

    with mock.patch(
        "pipeline.bdc_xbrl_wrapper_oracle._check_content_signatures",
        side_effect=mock_cs,
    ), mock.patch(
        "pipeline.bdc_xbrl_wrapper_oracle.load_wrapper_definition",
        return_value=None,
    ):
        summary, _, _, _ = build_wrapper_oracle_outputs(detail)

    assert summary.iloc[0]["oracle_status"] == "fail"
    assert "unclassified_rate_exceeded" in summary.iloc[0]["oracle_fail_reasons"]


def test_oracle_fails_when_unclassified_fv_rate_exceeded():
    """Oracle should fail when FV-weighted unclassified rate exceeds threshold."""
    detail = _detail([{
        "status": "documented_source_rollup_exact",
        "residual_class": "documented_exclusion",
        "calibrated_status": "documented_source_rollup_exact",
    }])

    def mock_cs(cik, holdings_df):
        return {"2024-12-31": {
            "pass_rate": 1.0,
            "violation_count": 0,
            "unclassified_rate": 0.02,
            "unclassified_rate_status": "pass",
            "unclassified_fv_rate": 0.35,
            "unclassified_fv_rate_status": "fail",
        }}

    with mock.patch(
        "pipeline.bdc_xbrl_wrapper_oracle._check_content_signatures",
        side_effect=mock_cs,
    ), mock.patch(
        "pipeline.bdc_xbrl_wrapper_oracle.load_wrapper_definition",
        return_value=None,
    ):
        summary, _, _, _ = build_wrapper_oracle_outputs(detail)

    assert summary.iloc[0]["oracle_status"] == "fail"
    assert "unclassified_fv_rate_exceeded" in summary.iloc[0]["oracle_fail_reasons"]
    # Row rate is fine, should NOT also fail on row rate
    assert "unclassified_rate_exceeded" not in summary.iloc[0]["oracle_fail_reasons"]


def test_oracle_fails_on_qoq_unclassified_rate_jump():
    """Oracle should fail when unclassified rate jumps > 5pp between quarters."""
    q1_detail = _detail([{
        "status": "documented_source_rollup_exact",
        "residual_class": "documented_exclusion",
        "calibrated_status": "documented_source_rollup_exact",
        "report_date": "2024-09-30",
    }])
    q2_detail = _detail([{
        "status": "documented_source_rollup_exact",
        "residual_class": "documented_exclusion",
        "calibrated_status": "documented_source_rollup_exact",
        "report_date": "2024-12-31",
    }])
    detail = pd.concat([q1_detail, q2_detail], ignore_index=True)

    def mock_cs(cik, holdings_df):
        return {
            "2024-09-30": {
                "pass_rate": 1.0,
                "violation_count": 0,
                "unclassified_rate": 0.02,
                "unclassified_rate_status": "pass",
                "unclassified_fv_rate": 0.01,
                "unclassified_fv_rate_status": "pass",
            },
            "2024-12-31": {
                "pass_rate": 1.0,
                "violation_count": 0,
                "unclassified_rate": 0.10,  # jumped from 0.02 to 0.10 = 8pp > 5pp
                "unclassified_rate_status": "fail",
                "unclassified_fv_rate": 0.01,
                "unclassified_fv_rate_status": "pass",
            },
        }

    with mock.patch(
        "pipeline.bdc_xbrl_wrapper_oracle._check_content_signatures",
        side_effect=mock_cs,
    ), mock.patch(
        "pipeline.bdc_xbrl_wrapper_oracle.load_wrapper_definition",
        return_value=None,
    ):
        summary, _, _, _ = build_wrapper_oracle_outputs(detail)

    q2_row = summary[summary["report_date"] == "2024-12-31"].iloc[0]
    assert q2_row["oracle_status"] == "fail"
    assert "unclassified_rate_qoq_jump" in q2_row["oracle_fail_reasons"]

    # Q1 should not be flagged for QoQ jump
    q1_row = summary[summary["report_date"] == "2024-09-30"].iloc[0]
    assert "unclassified_rate_qoq_jump" not in str(q1_row["oracle_fail_reasons"])


def test_oracle_no_qoq_jump_when_rate_stable():
    """No QoQ jump flag when unclassified rate is stable between quarters."""
    q1_detail = _detail([{
        "status": "documented_source_rollup_exact",
        "residual_class": "documented_exclusion",
        "calibrated_status": "documented_source_rollup_exact",
        "report_date": "2024-09-30",
    }])
    q2_detail = _detail([{
        "status": "documented_source_rollup_exact",
        "residual_class": "documented_exclusion",
        "calibrated_status": "documented_source_rollup_exact",
        "report_date": "2024-12-31",
    }])
    detail = pd.concat([q1_detail, q2_detail], ignore_index=True)

    def mock_cs(cik, holdings_df):
        return {
            "2024-09-30": {
                "pass_rate": 1.0,
                "violation_count": 0,
                "unclassified_rate": 0.03,
                "unclassified_rate_status": "pass",
                "unclassified_fv_rate": 0.01,
                "unclassified_fv_rate_status": "pass",
            },
            "2024-12-31": {
                "pass_rate": 1.0,
                "violation_count": 0,
                "unclassified_rate": 0.04,  # only 1pp increase, under 5pp threshold
                "unclassified_rate_status": "pass",
                "unclassified_fv_rate": 0.01,
                "unclassified_fv_rate_status": "pass",
            },
        }

    with mock.patch(
        "pipeline.bdc_xbrl_wrapper_oracle._check_content_signatures",
        side_effect=mock_cs,
    ), mock.patch(
        "pipeline.bdc_xbrl_wrapper_oracle.load_wrapper_definition",
        return_value=None,
    ):
        summary, _, _, _ = build_wrapper_oracle_outputs(detail)

    for _, row in summary.iterrows():
        assert "unclassified_rate_qoq_jump" not in str(row["oracle_fail_reasons"])


def test_oracle_fails_when_wrapper_has_no_archetypes():
    """Oracle should fail when wrapper definition exists but has no archetypes."""
    detail = _detail([{
        "status": "documented_source_rollup_exact",
        "residual_class": "documented_exclusion",
        "calibrated_status": "documented_source_rollup_exact",
    }])

    empty_wrapper = _make_wrapper(archetypes=())

    with mock.patch(
        "pipeline.bdc_xbrl_wrapper_oracle._check_content_signatures",
        return_value={},
    ), mock.patch(
        "pipeline.bdc_xbrl_wrapper_oracle.load_wrapper_definition",
        return_value=empty_wrapper,
    ):
        summary, _, _, _ = build_wrapper_oracle_outputs(detail)

    assert summary.iloc[0]["oracle_status"] == "fail"
    assert "wrapper_no_archetypes" in summary.iloc[0]["oracle_fail_reasons"]


# ---------------------------------------------------------------------------
# Promotion gate tests (Gap #6)
# ---------------------------------------------------------------------------


def _oracle_summary(rows):
    """Build oracle summary DataFrame from row overrides."""
    defaults = {
        "cik": "0001786108",
        "entity_name": "Trinity Capital Inc.",
        "report_date": "2024-12-31",
        "wrapper_source_rows": 10,
        "wrapper_output_rows": 10,
        "wrapper_rollup_candidates": 2,
        "wrapper_leaf_outputs": 8,
        "wrapper_leaf_source_rows": 8,
        "cleared_rollup_rows": 2,
        "cleared_rollup_fair_value": 1000000,
        "remaining_blocking_rows": 0,
        "remaining_blocking_fair_value": 0,
        "remaining_wrapper_blocking_rows": 0,
        "signature_fail_rows": 0,
        "unclassified_prefix_rows": 0,
        "unparsed_remainder_rows": 0,
        "content_signature_pass_rate": 1.0,
        "content_signature_violations": 0,
        "unclassified_rate": 0.02,
        "unclassified_rate_status": "pass",
        "unclassified_fv_rate": 0.01,
        "unclassified_fv_rate_status": "pass",
        "fv_reconciliation_status": "pass",
        "fv_reconciliation_pct_diff": 0.003,
        "exclusion_risk_count": 0,
        "exclusion_risk_fv": 0,
        "position_continuation_rate": "",
        "rate_outlier_count": 0,
        "cost_fv_ratio_outlier_count": 0,
        "fv_magnitude_shift": "",
        "rate_magnitude_shift": "",
        "concept_drift_flag": "",
        "unparsed_remainder_rate": "",
        "oracle_status": "pass",
        "oracle_fail_reasons": "",
    }
    merged = []
    for row in rows:
        m = {**defaults, **row}
        merged.append({col: m.get(col, "") for col in ORACLE_SUMMARY_COLUMNS})
    return pd.DataFrame(merged)


def _baseline_comp(rows):
    """Build baseline comparison DataFrame from row overrides."""
    defaults = {
        "cik": "0001786108",
        "report_date": "2024-12-31",
        "current_blocking_rows": 0,
        "baseline_blocking_rows": 5,
        "blocking_rows_delta": -5,
        "current_documented_source_rollup_exact_rows": 3,
        "baseline_documented_source_rollup_exact_rows": 0,
        "documented_rollup_delta": 3,
        "current_blocking_fair_value": 0,
        "baseline_blocking_fair_value": 500000,
        "blocking_fair_value_delta": -500000,
        "current_cleared_rollup_fair_value": 300000,
        "baseline_cleared_rollup_fair_value": 0,
        "cleared_rollup_fair_value_delta": 300000,
    }
    merged = []
    for row in rows:
        m = {**defaults, **row}
        merged.append({col: m.get(col, 0) for col in BASELINE_COMPARISON_COLUMNS})
    return pd.DataFrame(merged)


def _oracle_exception_rows(rows):
    defaults = {
        "schema_version": ORACLE_EXCEPTION_SCHEMA_VERSION,
        "cik": "0001786108",
        "report_date": "2024-12-31",
        "oracle_reason": "unclassified_rate_exceeded",
        "wrapper_version": "1",
        "status": "accepted",
        "confidence": 0.9,
        "reason": "Reviewed CIK-specific filing behavior.",
        "evidence": "Trial reconciliation and source detail reviewed.",
        "residual_risk": "Low residual diagnostic risk.",
        "created_by": "agent",
        "accepted_by": "operator",
        "updated_at": "2026-06-03",
    }
    return pd.DataFrame([{**defaults, **row} for row in rows])


def test_promotion_gate_promotes_when_blocking_rows_decrease():
    """Promotion gate should promote when blocking rows decrease and oracle passes."""
    summary = _oracle_summary([{}])
    baseline = _baseline_comp([{
        "blocking_rows_delta": -5,
        "blocking_fair_value_delta": -500000,
        "documented_rollup_delta": 3,
    }])

    verdict = evaluate_promotion_gate(summary, baseline)

    assert verdict.status == "promote"
    assert verdict.blocking_rows_delta == -5
    assert verdict.blocking_fv_delta == -500000
    assert any("blocking_rows_reduced" in imp for imp in verdict.improvements)
    assert any("blocking_fv_reduced" in imp for imp in verdict.improvements)
    assert any("cleared_rollups_increased" in imp for imp in verdict.improvements)
    assert len(verdict.reasons) == 0


def test_promotion_gate_rejects_when_blocking_rows_increase():
    """Promotion gate should reject when total blocking rows increase."""
    summary = _oracle_summary([{
        "remaining_blocking_rows": 10,
        "oracle_status": "fail",
        "oracle_fail_reasons": "wrapper_blockers_remaining",
    }])
    baseline = _baseline_comp([{
        "blocking_rows_delta": 5,
        "blocking_fair_value_delta": 0,
    }])

    verdict = evaluate_promotion_gate(summary, baseline)

    assert verdict.status == "reject"
    assert verdict.blocking_rows_delta == 5
    assert any("blocking_rows_increased" in r for r in verdict.reasons)


def test_promotion_gate_rejects_when_blocking_fv_increases():
    """Promotion gate should reject when blocking FV increases."""
    summary = _oracle_summary([{
        "oracle_status": "fail",
        "oracle_fail_reasons": "wrapper_blockers_remaining",
    }])
    baseline = _baseline_comp([{
        "blocking_rows_delta": 0,
        "blocking_fair_value_delta": 100000,
    }])

    verdict = evaluate_promotion_gate(summary, baseline)

    assert verdict.status == "reject"
    assert any("blocking_fv_increased" in r for r in verdict.reasons)


def test_promotion_gate_review_when_unclassified_rate_exceeded():
    """Promotion gate should require review when oracle fails on coverage."""
    summary = _oracle_summary([{
        "oracle_status": "fail",
        "oracle_fail_reasons": "unclassified_rate_exceeded",
    }])
    baseline = _baseline_comp([{
        "blocking_rows_delta": -3,
        "blocking_fair_value_delta": -100000,
    }])

    verdict = evaluate_promotion_gate(summary, baseline)

    assert verdict.status == "review_required"
    assert any("unclassified_rate_exceeded" in r for r in verdict.reasons)
    # Still has improvements from blocking reduction
    assert any("blocking_rows_reduced" in imp for imp in verdict.improvements)


def test_promotion_gate_review_on_per_quarter_regression():
    """Promotion gate should flag per-quarter blocking regressions."""
    summary = _oracle_summary([
        {"report_date": "2024-09-30", "oracle_status": "pass"},
        {"report_date": "2024-12-31", "oracle_status": "pass"},
    ])
    baseline = _baseline_comp([
        {"report_date": "2024-09-30", "blocking_rows_delta": -10},
        {"report_date": "2024-12-31", "blocking_rows_delta": 2},  # regression
    ])

    verdict = evaluate_promotion_gate(summary, baseline)

    # Total delta is -8, so no total-level reject, but per-quarter regression
    assert verdict.status == "review_required"
    assert verdict.blocking_rows_delta == -8
    assert any("blocking_rows_regressed" in r for r in verdict.reasons)
    # Per-quarter comparison should show the regression
    q2 = verdict.per_quarter[verdict.per_quarter["report_date"] == "2024-12-31"].iloc[0]
    assert q2["quarter_verdict"] == "reject"
    assert "blocking_rows_regressed" in q2["quarter_reasons"]


def test_promotion_gate_promotes_without_baseline():
    """Promotion gate should promote on clean oracle even without baseline."""
    summary = _oracle_summary([{}])

    verdict = evaluate_promotion_gate(summary, baseline_comparison=None)

    assert verdict.status == "promote"
    assert verdict.blocking_rows_delta == 0
    assert verdict.blocking_fv_delta == 0.0
    assert len(verdict.reasons) == 0


def test_promotion_trial_forwards_holdings_file(tmp_path):
    """Promotion trial should evaluate the same trial holdings as the oracle."""
    summary = _oracle_summary([{}])
    holdings_file = tmp_path / "trial_holdings.csv"

    with (
        mock.patch(
            "pipeline.bdc_xbrl_wrapper_oracle.run_wrapper_oracle_trial",
            return_value=(pd.DataFrame(), summary, pd.DataFrame(), pd.DataFrame(), pd.DataFrame()),
        ) as run_trial,
        mock.patch("pipeline.bdc_xbrl_wrapper_oracle.load_wrapper_definition", return_value=mock.Mock(version=1)),
        mock.patch("pipeline.bdc_xbrl_wrapper_oracle.validate_wrapper_definition_structure", return_value=[]),
        mock.patch("pipeline.bdc_xbrl_wrapper_oracle.load_bdc_xbrl_oracle_exceptions", return_value=pd.DataFrame()),
    ):
        verdict = run_promotion_trial(
            cik="0001859919",
            output_dir=tmp_path / "promotion",
            holdings_file=holdings_file,
        )

    assert verdict.status == "promote"
    assert run_trial.call_args.kwargs["holdings_file"] == holdings_file


def test_promotion_gate_rejects_on_empty_summary():
    """Promotion gate should reject when oracle summary is empty."""
    verdict = evaluate_promotion_gate(pd.DataFrame(), None)

    assert verdict.status == "reject"
    assert "no_oracle_data" in verdict.reasons


def test_promotion_gate_rejects_on_wrapper_blockers():
    """Promotion gate should hard-reject on wrapper_blockers_remaining."""
    summary = _oracle_summary([{
        "oracle_status": "fail",
        "oracle_fail_reasons": "wrapper_blockers_remaining",
    }])

    verdict = evaluate_promotion_gate(summary, baseline_comparison=None)

    assert verdict.status == "reject"
    assert any("wrapper_blockers_remaining" in r for r in verdict.reasons)


def test_promotion_gate_per_quarter_columns():
    """Promotion gate per_quarter should have all expected columns."""
    summary = _oracle_summary([{}])
    baseline = _baseline_comp([{}])

    verdict = evaluate_promotion_gate(summary, baseline)

    assert list(verdict.per_quarter.columns) == PROMOTION_GATE_COLUMNS
    assert len(verdict.per_quarter) == 1


def test_promotion_gate_accepted_exception_waives_soft_reason():
    """Accepted exact-match exceptions waive eligible soft promotion reasons."""
    summary = _oracle_summary([{
        "oracle_status": "fail",
        "oracle_fail_reasons": "unclassified_rate_exceeded",
    }])
    baseline = _baseline_comp([{
        "blocking_rows_delta": -3,
        "blocking_fair_value_delta": -100000,
    }])
    exceptions = _oracle_exception_rows([{}])

    verdict = evaluate_promotion_gate(
        summary,
        baseline,
        oracle_exceptions=exceptions,
        wrapper_version_by_cik={"0001786108": 1},
    )

    assert verdict.status == "promote"
    assert verdict.reasons == []
    quarter = verdict.per_quarter.iloc[0]
    assert quarter["current_oracle_status"] == "fail"
    assert quarter["effective_oracle_status"] == "pass"
    assert quarter["waived_oracle_reasons"] == "unclassified_rate_exceeded"
    assert quarter["unwaived_oracle_reasons"] == ""


def test_promotion_gate_exception_does_not_waive_hard_or_false_exclusion_reason():
    """Exceptions cannot waive hard rejects or non-waiveable exclusion risk."""
    hard_summary = _oracle_summary([{
        "oracle_status": "fail",
        "oracle_fail_reasons": "wrapper_blockers_remaining",
    }])
    false_exclusion_summary = _oracle_summary([{
        "oracle_status": "fail",
        "oracle_fail_reasons": "exclusion_risk_detected",
    }])
    exceptions = _oracle_exception_rows([
        {"oracle_reason": "wrapper_blockers_remaining"},
        {"oracle_reason": "exclusion_risk_detected"},
    ])

    hard_verdict = evaluate_promotion_gate(
        hard_summary,
        None,
        oracle_exceptions=exceptions,
        wrapper_version_by_cik={"0001786108": 1},
    )
    false_exclusion_verdict = evaluate_promotion_gate(
        false_exclusion_summary,
        None,
        oracle_exceptions=exceptions,
        wrapper_version_by_cik={"0001786108": 1},
    )

    assert hard_verdict.status == "reject"
    assert any("wrapper_blockers_remaining" in r for r in hard_verdict.reasons)
    assert hard_verdict.per_quarter.iloc[0]["unwaived_oracle_reasons"] == "wrapper_blockers_remaining"
    assert false_exclusion_verdict.status == "review_required"
    assert any("exclusion_risk_detected" in r for r in false_exclusion_verdict.reasons)
    assert false_exclusion_verdict.per_quarter.iloc[0]["unwaived_oracle_reasons"] == "exclusion_risk_detected"


def test_promotion_gate_exception_requires_exact_match_and_active_confidence():
    """Inactive, low-confidence, or stale-version exceptions do not waive."""
    summary = _oracle_summary([{
        "oracle_status": "fail",
        "oracle_fail_reasons": "unclassified_rate_exceeded",
    }])
    baseline = _baseline_comp([{}])
    exceptions = _oracle_exception_rows([
        {"status": "proposed", "confidence": 1.0},
        {"status": "accepted", "confidence": 0.79},
        {"status": "accepted", "confidence": 0.95, "wrapper_version": "2"},
    ])

    verdict = evaluate_promotion_gate(
        summary,
        baseline,
        oracle_exceptions=exceptions,
        wrapper_version_by_cik={"0001786108": 1},
    )

    assert verdict.status == "review_required"
    assert verdict.per_quarter.iloc[0]["waived_oracle_reasons"] == ""
    assert verdict.per_quarter.iloc[0]["unwaived_oracle_reasons"] == "unclassified_rate_exceeded"


def test_build_exception_proposals_only_outputs_unwaived_eligible_reasons():
    """Proposal templates include only eligible unwaived soft reasons."""
    summary = _oracle_summary([{
        "oracle_status": "fail",
        "oracle_fail_reasons": (
            "unclassified_rate_exceeded|wrapper_blockers_remaining|"
            "exclusion_risk_detected|concept_drift_detected"
        ),
    }])
    exceptions = _oracle_exception_rows([{
        "oracle_reason": "unclassified_rate_exceeded",
    }])

    proposals = build_exception_proposals(
        summary,
        wrapper_version_by_cik={"0001786108": 1},
        oracle_exceptions=exceptions,
    )

    assert [p["oracle_reason"] for p in proposals] == ["concept_drift_detected"]
    assert proposals[0]["status"] == "proposed"
    assert proposals[0]["confidence"] == ""


def test_load_bdc_xbrl_oracle_exceptions_validates_active_file(tmp_path):
    """Active exception files normalize CIKs and reject malformed records."""
    valid_path = tmp_path / "exceptions.json"
    valid_record = _oracle_exception_rows([{}]).iloc[0].to_dict()
    valid_path.write_text(
        json.dumps({
            "schema_version": ORACLE_EXCEPTION_SCHEMA_VERSION,
            "exceptions": [valid_record],
        }),
        encoding="utf-8",
    )

    loaded = load_bdc_xbrl_oracle_exceptions(valid_path)

    assert loaded.iloc[0]["cik"] == "0001786108"
    assert loaded.iloc[0]["confidence"] == 0.9

    invalid_path = tmp_path / "invalid.json"
    invalid_record = dict(valid_record)
    invalid_record["confidence"] = 0.5
    invalid_path.write_text(
        json.dumps({"exceptions": [invalid_record]}),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="confidence >= 0.80"):
        load_bdc_xbrl_oracle_exceptions(invalid_path)


# ---------------------------------------------------------------------------
# Wrapper definition structural validation tests
# ---------------------------------------------------------------------------


def test_validate_structure_passes_clean_wrapper():
    """Valid wrapper definition should produce no issues."""
    wrapper = _make_wrapper()
    issues = validate_wrapper_definition_structure(wrapper)
    assert issues == []


def test_validate_structure_flags_no_archetypes():
    """Wrapper with no archetypes should be flagged."""
    wrapper = _make_wrapper(archetypes=())
    issues = validate_wrapper_definition_structure(wrapper)
    assert "no_archetypes_defined" in issues


def test_validate_structure_flags_keyword_overlap():
    """Overlapping keywords across archetypes should be flagged."""
    archetypes = (
        Archetype(
            name="debt_a",
            description="First debt type",
            keywords=("term loan",),
            keyword_mode="any",
            field_signatures=(),
        ),
        Archetype(
            name="debt_b",
            description="Second debt type",
            keywords=("term loan", "revolver"),  # "term loan" overlaps
            keyword_mode="any",
            field_signatures=(),
        ),
    )
    wrapper = _make_wrapper(archetypes=archetypes)
    issues = validate_wrapper_definition_structure(wrapper)
    assert any("term loan" in i and "debt_a" in i and "debt_b" in i for i in issues)


def test_validate_structure_flags_invalid_numeric_range():
    """Numeric range with min > max should be flagged."""
    archetypes = (
        Archetype(
            name="bad_range",
            description="Bad numeric range",
            keywords=("test",),
            keyword_mode="any",
            field_signatures=(
                FieldSignature(
                    field_name="fair_value",
                    sig_type="numeric_range",
                    constraint="required",
                    min_val=100.0,
                    max_val=10.0,  # min > max
                ),
            ),
        ),
    )
    wrapper = _make_wrapper(archetypes=archetypes)
    issues = validate_wrapper_definition_structure(wrapper)
    assert any("min" in i and "max" in i for i in issues)


def test_validate_structure_flags_empty_keywords():
    """Archetype with no keywords should be flagged."""
    archetypes = (
        Archetype(
            name="no_keywords",
            description="Missing keywords",
            keywords=(),
            keyword_mode="any",
            field_signatures=(),
        ),
    )
    wrapper = _make_wrapper(archetypes=archetypes)
    issues = validate_wrapper_definition_structure(wrapper)
    assert any("no keywords" in i for i in issues)


# ---------------------------------------------------------------------------
# Gap #7: Exclusion false-positive risk tests
# ---------------------------------------------------------------------------


def test_oracle_flags_exclusion_risk_when_position_evidence_found():
    """Oracle should flag excluded rows containing position-evidence keywords."""
    detail = _detail([
        {
            "status": "documented_source_rollup_exact",
            "residual_class": "documented_exclusion",
            "calibrated_status": "documented_source_rollup_exact",
            "source_wrapper_disposition": "aggregate",
            "raw_investment_identifier": "Total Term Loan Investments - Category A",
            "source_fair_value": 5000000,
        },
    ])

    with mock.patch(
        "pipeline.bdc_xbrl_wrapper_oracle._check_content_signatures",
        return_value={},
    ), mock.patch(
        "pipeline.bdc_xbrl_wrapper_oracle.load_wrapper_definition",
        return_value=None,
    ):
        summary, _, _, _ = build_wrapper_oracle_outputs(detail)

    assert summary.iloc[0]["exclusion_risk_count"] == 1
    assert summary.iloc[0]["exclusion_risk_fv"] > 0
    assert "exclusion_risk_detected" in summary.iloc[0]["oracle_fail_reasons"]


def test_oracle_no_exclusion_risk_for_clean_exclusions():
    """Oracle should not flag exclusions without position-evidence keywords."""
    detail = _detail([
        {
            "status": "documented_source_rollup_exact",
            "residual_class": "documented_exclusion",
            "calibrated_status": "documented_source_rollup_exact",
            "source_wrapper_disposition": "non_private_market",
            "raw_investment_identifier": "U.S. Treasury Bills",
        },
    ])

    with mock.patch(
        "pipeline.bdc_xbrl_wrapper_oracle._check_content_signatures",
        return_value={},
    ), mock.patch(
        "pipeline.bdc_xbrl_wrapper_oracle.load_wrapper_definition",
        return_value=None,
    ):
        summary, _, _, _ = build_wrapper_oracle_outputs(detail)

    assert summary.iloc[0]["exclusion_risk_count"] == 0
    assert "exclusion_risk_detected" not in str(summary.iloc[0]["oracle_fail_reasons"])


# ---------------------------------------------------------------------------
# Gap #8: Position continuity tests
# ---------------------------------------------------------------------------


def test_oracle_flags_low_position_continuity():
    """Oracle should flag quarters with < 50% position key continuation."""
    # Q1 has positions A, B, C; Q2 has position D only -> 0% continuation
    q1_rows = [
        {
            "report_date": "2024-09-30",
            "source_wrapper_disposition": "debt_position_leaf",
            "source_wrapper_position_key": f"position_{k}",
            "status": "matched",
        }
        for k in ["a", "b", "c"]
    ]
    q2_rows = [
        {
            "report_date": "2024-12-31",
            "source_wrapper_disposition": "debt_position_leaf",
            "source_wrapper_position_key": "position_d",
            "status": "matched",
        },
    ]
    detail = _detail(q1_rows + q2_rows)

    with mock.patch(
        "pipeline.bdc_xbrl_wrapper_oracle._check_content_signatures",
        return_value={},
    ), mock.patch(
        "pipeline.bdc_xbrl_wrapper_oracle.load_wrapper_definition",
        return_value=None,
    ):
        summary, _, _, _ = build_wrapper_oracle_outputs(detail)

    q2_row = summary[summary["report_date"] == "2024-12-31"].iloc[0]
    assert float(q2_row["position_continuation_rate"]) < 0.50
    assert "low_position_continuity" in str(q2_row["oracle_fail_reasons"])


def test_oracle_no_continuity_flag_when_rate_high():
    """Oracle should not flag when position continuation is >= 50%."""
    # Q1 has positions A, B; Q2 has A, B, C -> 100% continuation
    q1_rows = [
        {
            "report_date": "2024-09-30",
            "source_wrapper_disposition": "debt_position_leaf",
            "source_wrapper_position_key": f"position_{k}",
            "status": "matched",
        }
        for k in ["a", "b"]
    ]
    q2_rows = [
        {
            "report_date": "2024-12-31",
            "source_wrapper_disposition": "debt_position_leaf",
            "source_wrapper_position_key": f"position_{k}",
            "status": "matched",
        }
        for k in ["a", "b", "c"]
    ]
    detail = _detail(q1_rows + q2_rows)

    with mock.patch(
        "pipeline.bdc_xbrl_wrapper_oracle._check_content_signatures",
        return_value={},
    ), mock.patch(
        "pipeline.bdc_xbrl_wrapper_oracle.load_wrapper_definition",
        return_value=None,
    ):
        summary, _, _, _ = build_wrapper_oracle_outputs(detail)

    q2_row = summary[summary["report_date"] == "2024-12-31"].iloc[0]
    assert float(q2_row["position_continuation_rate"]) >= 0.50
    assert "low_position_continuity" not in str(q2_row["oracle_fail_reasons"])


# ---------------------------------------------------------------------------
# Gap #4: Rate and scale outlier tests
# ---------------------------------------------------------------------------


def test_oracle_flags_rate_outliers():
    """Oracle should flag rows with interest rates outside rate_sanity bounds."""
    detail = _detail([{
        "status": "documented_source_rollup_exact",
        "residual_class": "documented_exclusion",
        "calibrated_status": "documented_source_rollup_exact",
    }])

    holdings = pd.DataFrame({
        "cik": ["0001786108"] * 3,
        "report_date": ["2024-12-31"] * 3,
        "interest_rate": ["0.08", "0.50", "0.10"],  # 50% is outside 1%-25%
        "fair_value": ["1000000", "500000", "2000000"],
    })

    wrapper = WrapperDefinition(
        cik="0001786108",
        entity_name="Test BDC",
        version=1,
        archetypes=_make_wrapper().archetypes,
        rate_sanity=RateSanity(min_pct=0.01, max_pct=0.25),
        unclassified_rate=_make_wrapper().unclassified_rate,
    )

    with mock.patch(
        "pipeline.bdc_xbrl_wrapper_oracle._check_content_signatures",
        return_value={},
    ), mock.patch(
        "pipeline.bdc_xbrl_wrapper_oracle.load_wrapper_definition",
        return_value=wrapper,
    ):
        summary, _, _, _ = build_wrapper_oracle_outputs(
            detail, holdings_df=holdings,
        )

    assert summary.iloc[0]["rate_outlier_count"] == 1
    assert "rate_outliers_detected" in summary.iloc[0]["oracle_fail_reasons"]


def test_oracle_counts_cost_fv_ratio_outliers_without_failing():
    """Oracle should count extreme cost/FV ratios without making them hard fails."""
    detail = _detail([{
        "status": "documented_source_rollup_exact",
        "residual_class": "documented_exclusion",
        "calibrated_status": "documented_source_rollup_exact",
    }])

    holdings = pd.DataFrame({
        "cik": ["0001786108"] * 3,
        "report_date": ["2024-12-31"] * 3,
        "cost": ["1000000", "100", "2000000"],
        "fair_value": ["1000000", "100000", "2000000"],  # row 2: ratio=0.001
    })

    with mock.patch(
        "pipeline.bdc_xbrl_wrapper_oracle._check_content_signatures",
        return_value={},
    ), mock.patch(
        "pipeline.bdc_xbrl_wrapper_oracle.load_wrapper_definition",
        return_value=None,
    ):
        summary, _, _, _ = build_wrapper_oracle_outputs(
            detail, holdings_df=holdings,
        )

    assert summary.iloc[0]["cost_fv_ratio_outlier_count"] == 1
    assert "cost_fv_ratio_outliers" not in summary.iloc[0]["oracle_fail_reasons"]

    packets = _build_cost_fv_outlier_packets(holdings, cik="0001786108")
    assert list(packets.columns) == AGENT_ISSUE_PACKET_COLUMNS
    assert len(packets) == 1
    assert packets.iloc[0]["rule_id"] == "WRAP.COST_FV_RATIO_OUTLIER"
    assert packets.iloc[0]["likely_owner"] == "validation_rule"


def test_oracle_cost_fv_skips_nominal_fv_positions():
    """Positions with |FV| <= $1,000 are nominal-value (unfunded commitments,
    warrants at minimal mark) and should not trigger cost/FV outlier flags."""
    detail = _detail([{
        "status": "documented_source_rollup_exact",
        "residual_class": "documented_exclusion",
        "calibrated_status": "documented_source_rollup_exact",
    }])

    holdings = pd.DataFrame({
        "cik": ["0001786108"] * 3,
        "report_date": ["2024-12-31"] * 3,
        # Nominal FV positions: |FV| <= 1000 with real cost
        "cost": ["-125000", "600000", "1000000"],
        "fair_value": ["-1000", "1000", "1000000"],
    })

    with mock.patch(
        "pipeline.bdc_xbrl_wrapper_oracle._check_content_signatures",
        return_value={},
    ), mock.patch(
        "pipeline.bdc_xbrl_wrapper_oracle.load_wrapper_definition",
        return_value=None,
    ):
        summary, _, _, _ = build_wrapper_oracle_outputs(
            detail, holdings_df=holdings,
        )

    assert summary.iloc[0]["cost_fv_ratio_outlier_count"] == 0
    assert "cost_fv_ratio_outliers" not in str(
        summary.iloc[0].get("oracle_fail_reasons", "")
    )


def test_oracle_uses_no_wrapper_rows_for_existing_definition_without_prefix_rows():
    detail = _detail([{
        "status": "matched",
        "raw_investment_identifier": "Jackson Paper Manufacturing Company Initial Term Loan",
        "source_wrapper_disposition": "",
        "output_wrapper_disposition": "",
        "source_wrapper_signature_status": "",
    }])

    with mock.patch(
        "pipeline.bdc_xbrl_wrapper_oracle._check_content_signatures",
        return_value={},
    ), mock.patch(
        "pipeline.bdc_xbrl_wrapper_oracle.load_wrapper_definition",
        return_value=_make_wrapper(),
    ):
        summary, _, _, _ = build_wrapper_oracle_outputs(detail)

    reasons = summary.iloc[0]["oracle_fail_reasons"]
    assert "no_wrapper_rows" in reasons
    assert "unsupported_wrapper_cik" not in reasons


def test_oracle_no_rate_outliers_when_within_bounds():
    """Oracle should not flag rates within rate_sanity bounds."""
    detail = _detail([{
        "status": "documented_source_rollup_exact",
        "residual_class": "documented_exclusion",
        "calibrated_status": "documented_source_rollup_exact",
    }])

    holdings = pd.DataFrame({
        "cik": ["0001786108"] * 2,
        "report_date": ["2024-12-31"] * 2,
        "interest_rate": ["0.08", "0.12"],  # both within 1%-25%
        "fair_value": ["1000000", "2000000"],
    })

    wrapper = WrapperDefinition(
        cik="0001786108",
        entity_name="Test BDC",
        version=1,
        archetypes=_make_wrapper().archetypes,
        rate_sanity=RateSanity(min_pct=0.01, max_pct=0.25),
        unclassified_rate=_make_wrapper().unclassified_rate,
    )

    with mock.patch(
        "pipeline.bdc_xbrl_wrapper_oracle._check_content_signatures",
        return_value={},
    ), mock.patch(
        "pipeline.bdc_xbrl_wrapper_oracle.load_wrapper_definition",
        return_value=wrapper,
    ):
        summary, _, _, _ = build_wrapper_oracle_outputs(
            detail, holdings_df=holdings,
        )

    assert summary.iloc[0]["rate_outlier_count"] == 0
    assert "rate_outliers_detected" not in str(summary.iloc[0]["oracle_fail_reasons"])


# ---------------------------------------------------------------------------
# Gap #3: Concept drift tests
# ---------------------------------------------------------------------------


def test_oracle_flags_concept_drift():
    """Oracle should flag when XBRL concepts change between quarters."""
    q1_detail = _detail([{
        "report_date": "2024-09-30",
        "concept_names": "InvestmentOwnedAtFairValue",
        "status": "matched",
    }])
    q2_detail = _detail([{
        "report_date": "2024-12-31",
        "concept_names": "InvestmentOwnedAtCost",
        "status": "matched",
    }])
    detail = pd.concat([q1_detail, q2_detail], ignore_index=True)

    with mock.patch(
        "pipeline.bdc_xbrl_wrapper_oracle._check_content_signatures",
        return_value={},
    ), mock.patch(
        "pipeline.bdc_xbrl_wrapper_oracle.load_wrapper_definition",
        return_value=None,
    ):
        summary, _, _, _ = build_wrapper_oracle_outputs(detail)

    q2_row = summary[summary["report_date"] == "2024-12-31"].iloc[0]
    assert q2_row["concept_drift_flag"] == "yes"
    assert "concept_drift_detected" in str(q2_row["oracle_fail_reasons"])


def test_oracle_no_concept_drift_when_stable():
    """Oracle should not flag when XBRL concepts are stable across quarters."""
    q1_detail = _detail([{
        "report_date": "2024-09-30",
        "concept_names": "InvestmentOwnedAtFairValue",
        "status": "matched",
    }])
    q2_detail = _detail([{
        "report_date": "2024-12-31",
        "concept_names": "InvestmentOwnedAtFairValue",
        "status": "matched",
    }])
    detail = pd.concat([q1_detail, q2_detail], ignore_index=True)

    with mock.patch(
        "pipeline.bdc_xbrl_wrapper_oracle._check_content_signatures",
        return_value={},
    ), mock.patch(
        "pipeline.bdc_xbrl_wrapper_oracle.load_wrapper_definition",
        return_value=None,
    ):
        summary, _, _, _ = build_wrapper_oracle_outputs(detail)

    q2_row = summary[summary["report_date"] == "2024-12-31"].iloc[0]
    assert q2_row["concept_drift_flag"] == "no"
    assert "concept_drift_detected" not in str(q2_row["oracle_fail_reasons"])


def test_oracle_no_concept_drift_when_churn_below_threshold():
    """Oracle should not flag when only a small fraction of concepts change.

    Normal BDC portfolio turnover adds/removes a few concepts per quarter.
    With 10 shared concepts and 1 new concept, churn = 1/11 ~ 9%, well below
    the 30% threshold.
    """
    shared = [f"Concept{i}" for i in range(10)]
    q1_rows = [{"report_date": "2024-09-30", "concept_names": c, "status": "matched"}
               for c in shared]
    q2_rows = [{"report_date": "2024-12-31", "concept_names": c, "status": "matched"}
               for c in shared + ["NewConceptQ2"]]
    detail = pd.concat([_detail(q1_rows), _detail(q2_rows)], ignore_index=True)

    with mock.patch(
        "pipeline.bdc_xbrl_wrapper_oracle._check_content_signatures",
        return_value={},
    ), mock.patch(
        "pipeline.bdc_xbrl_wrapper_oracle.load_wrapper_definition",
        return_value=None,
    ):
        summary, _, _, _ = build_wrapper_oracle_outputs(detail)

    q2_row = summary[summary["report_date"] == "2024-12-31"].iloc[0]
    assert q2_row["concept_drift_flag"] == "no"
    assert "concept_drift_detected" not in str(q2_row["oracle_fail_reasons"])


def test_oracle_no_concept_drift_when_pipe_delimited_combos_change():
    """Concept drift should split pipe-delimited concept_names into individual
    concepts before comparing.  Different rows may report different
    *combinations* of the same underlying concepts (e.g. one row has
    ``FV|Cost`` and another has ``FV|Cost|Maturity``).  This is normal
    portfolio composition change, not a structural taxonomy change."""
    q1_detail = _detail([
        {"report_date": "2024-09-30",
         "concept_names": "FairValue|Cost", "status": "matched"},
        {"report_date": "2024-09-30",
         "concept_names": "FairValue|Cost|Rate", "status": "matched"},
    ])
    # Q2: same individual concepts, different combo set
    q2_detail = _detail([
        {"report_date": "2024-12-31",
         "concept_names": "FairValue|Cost|Rate|Maturity", "status": "matched"},
    ])
    detail = pd.concat([q1_detail, q2_detail], ignore_index=True)

    with mock.patch(
        "pipeline.bdc_xbrl_wrapper_oracle._check_content_signatures",
        return_value={},
    ), mock.patch(
        "pipeline.bdc_xbrl_wrapper_oracle.load_wrapper_definition",
        return_value=None,
    ):
        summary, _, _, _ = build_wrapper_oracle_outputs(detail)

    q2_row = summary[summary["report_date"] == "2024-12-31"].iloc[0]
    # Individual concepts: {FairValue, Cost, Rate} vs {FairValue, Cost, Rate, Maturity}
    # churn = 1/4 = 25%, below the 30% threshold
    assert q2_row["concept_drift_flag"] == "no"
    assert "concept_drift_detected" not in str(q2_row["oracle_fail_reasons"])


# ---------------------------------------------------------------------------
# Gap #5: Unparsed remainder spike test
# ---------------------------------------------------------------------------


def test_oracle_flags_unparsed_remainder_spike():
    """Oracle should flag when unparsed_remainder_rate spikes > 10pp QoQ."""
    q1_detail = _detail([{
        "report_date": "2024-09-30",
        "source_wrapper_unparsed_remainder": "",
    }])
    q2_detail = _detail([{
        "report_date": "2024-12-31",
        "source_wrapper_unparsed_remainder": "leftover text",
    }])
    detail = pd.concat([q1_detail, q2_detail], ignore_index=True)

    with mock.patch(
        "pipeline.bdc_xbrl_wrapper_oracle._check_content_signatures",
        return_value={},
    ), mock.patch(
        "pipeline.bdc_xbrl_wrapper_oracle.load_wrapper_definition",
        return_value=None,
    ):
        summary, _, _, _ = build_wrapper_oracle_outputs(detail)

    q2_row = summary[summary["report_date"] == "2024-12-31"].iloc[0]
    assert "unparsed_remainder_spike" in str(q2_row["oracle_fail_reasons"])


# ---------------------------------------------------------------------------
# Gap #4 extension: Per-field magnitude shift tests
# ---------------------------------------------------------------------------


def test_magnitude_shift_detects_fv_scale_change():
    """Oracle should flag when FV medians shift by >= 10x between quarters."""
    # Q1: FV values around 1,000; Q2: FV values around 1,000,000 (1000x shift)
    q1_rows = [
        {"report_date": "2024-09-30", "source_fair_value": v, "status": "matched"}
        for v in [1000, 1100, 900, 1050, 950]
    ]
    q2_rows = [
        {"report_date": "2024-12-31", "source_fair_value": v, "status": "matched"}
        for v in [1000000, 1100000, 900000, 1050000, 950000]
    ]
    detail = _detail(q1_rows + q2_rows)

    with mock.patch(
        "pipeline.bdc_xbrl_wrapper_oracle._check_content_signatures",
        return_value={},
    ), mock.patch(
        "pipeline.bdc_xbrl_wrapper_oracle.load_wrapper_definition",
        return_value=None,
    ):
        summary, _, _, _ = build_wrapper_oracle_outputs(detail)

    q2_row = summary[summary["report_date"] == "2024-12-31"].iloc[0]
    assert q2_row["fv_magnitude_shift"] != ""
    assert float(q2_row["fv_magnitude_shift"]) >= 10.0
    assert "fv_magnitude_shift_detected" in str(q2_row["oracle_fail_reasons"])


def test_magnitude_shift_detects_rate_scale_change():
    """Oracle should flag when rate medians shift by >= 10x (decimal -> percentage)."""
    # Q1: rates as decimals ~0.08; Q2: rates as percentages ~8.0 (100x shift)
    q1_rows = [
        {"report_date": "2024-09-30", "source_interest_rate": v, "status": "matched"}
        for v in [0.08, 0.09, 0.07, 0.085, 0.075]
    ]
    q2_rows = [
        {"report_date": "2024-12-31", "source_interest_rate": v, "status": "matched"}
        for v in [8.0, 9.0, 7.0, 8.5, 7.5]
    ]
    detail = _detail(q1_rows + q2_rows)

    with mock.patch(
        "pipeline.bdc_xbrl_wrapper_oracle._check_content_signatures",
        return_value={},
    ), mock.patch(
        "pipeline.bdc_xbrl_wrapper_oracle.load_wrapper_definition",
        return_value=None,
    ):
        summary, _, _, _ = build_wrapper_oracle_outputs(detail)

    q2_row = summary[summary["report_date"] == "2024-12-31"].iloc[0]
    assert q2_row["rate_magnitude_shift"] != ""
    assert float(q2_row["rate_magnitude_shift"]) >= 10.0
    assert "rate_magnitude_shift_detected" in str(q2_row["oracle_fail_reasons"])


def test_magnitude_shift_no_flag_when_stable():
    """No magnitude shift flag when values change by only 2x (normal variation)."""
    q1_rows = [
        {"report_date": "2024-09-30", "source_fair_value": v, "status": "matched"}
        for v in [1000000, 1100000, 900000, 1050000, 950000]
    ]
    q2_rows = [
        {"report_date": "2024-12-31", "source_fair_value": v, "status": "matched"}
        for v in [2000000, 2200000, 1800000, 2100000, 1900000]  # ~2x, not 10x
    ]
    detail = _detail(q1_rows + q2_rows)

    with mock.patch(
        "pipeline.bdc_xbrl_wrapper_oracle._check_content_signatures",
        return_value={},
    ), mock.patch(
        "pipeline.bdc_xbrl_wrapper_oracle.load_wrapper_definition",
        return_value=None,
    ):
        summary, _, _, _ = build_wrapper_oracle_outputs(detail)

    q2_row = summary[summary["report_date"] == "2024-12-31"].iloc[0]
    assert q2_row["fv_magnitude_shift"] == ""
    assert "fv_magnitude_shift_detected" not in str(q2_row["oracle_fail_reasons"])


def test_magnitude_shift_no_flag_when_sparse():
    """No magnitude shift flag when fewer than 5 values per quarter."""
    # Only 3 values per quarter -- below _MAGNITUDE_SHIFT_MIN_VALUES threshold
    q1_rows = [
        {"report_date": "2024-09-30", "source_fair_value": v, "status": "matched"}
        for v in [1000, 1100, 900]
    ]
    q2_rows = [
        {"report_date": "2024-12-31", "source_fair_value": v, "status": "matched"}
        for v in [1000000, 1100000, 900000]  # 1000x shift, but sparse
    ]
    detail = _detail(q1_rows + q2_rows)

    with mock.patch(
        "pipeline.bdc_xbrl_wrapper_oracle._check_content_signatures",
        return_value={},
    ), mock.patch(
        "pipeline.bdc_xbrl_wrapper_oracle.load_wrapper_definition",
        return_value=None,
    ):
        summary, _, _, _ = build_wrapper_oracle_outputs(detail)

    q2_row = summary[summary["report_date"] == "2024-12-31"].iloc[0]
    assert q2_row["fv_magnitude_shift"] == ""
    assert "fv_magnitude_shift_detected" not in str(q2_row["oracle_fail_reasons"])


def test_magnitude_shift_handles_negative_fv():
    """Negative FV values should use abs() and not cause false positives."""
    q1_rows = [
        {"report_date": "2024-09-30", "source_fair_value": v, "status": "matched"}
        for v in [1000000, -1100000, 900000, -1050000, 950000]
    ]
    q2_rows = [
        {"report_date": "2024-12-31", "source_fair_value": v, "status": "matched"}
        for v in [-1200000, 1300000, -1000000, 1150000, -1050000]
    ]
    detail = _detail(q1_rows + q2_rows)

    with mock.patch(
        "pipeline.bdc_xbrl_wrapper_oracle._check_content_signatures",
        return_value={},
    ), mock.patch(
        "pipeline.bdc_xbrl_wrapper_oracle.load_wrapper_definition",
        return_value=None,
    ):
        summary, _, _, _ = build_wrapper_oracle_outputs(detail)

    q2_row = summary[summary["report_date"] == "2024-12-31"].iloc[0]
    assert q2_row["fv_magnitude_shift"] == ""
    assert "fv_magnitude_shift_detected" not in str(q2_row["oracle_fail_reasons"])


def test_magnitude_shift_no_flag_single_quarter():
    """No magnitude shift flag when only one quarter of data exists."""
    q1_rows = [
        {"report_date": "2024-12-31", "source_fair_value": v, "status": "matched"}
        for v in [1000, 1100, 900, 1050, 950]
    ]
    detail = _detail(q1_rows)

    with mock.patch(
        "pipeline.bdc_xbrl_wrapper_oracle._check_content_signatures",
        return_value={},
    ), mock.patch(
        "pipeline.bdc_xbrl_wrapper_oracle.load_wrapper_definition",
        return_value=None,
    ):
        summary, _, _, _ = build_wrapper_oracle_outputs(detail)

    assert summary.iloc[0]["fv_magnitude_shift"] == ""
    assert "fv_magnitude_shift_detected" not in str(summary.iloc[0]["oracle_fail_reasons"])


# ---------------------------------------------------------------------------
# Row-delta attribution packets
# ---------------------------------------------------------------------------


def _holding(**overrides):
    row = {
        "cik": "0001786108",
        "entity_name": "Trinity Capital Inc.",
        "source": "bdc",
        "report_date": "2024-12-31",
        "accession_number": "0001786108-25-000001",
        "bdc_investment_identifier": "Jackson Paper Initial Term Loan",
        "issuer_name": "Jackson Paper Manufacturing Company",
        "instrument_description": "Initial Term Loan",
        "position_key": "jackson paper initial term loan",
        "fair_value": "1000",
        "cost": "950",
        "principal_amount": "1000",
        "interest_rate": "10.0",
        "basis_spread": "5.0",
        "pik_rate": "",
        "index_classification": "DIRECT_LENDING",
        "asset_class": "PRIVATE_CREDIT",
        "exposure_type": "DIRECT",
        "asset_category": "LOAN",
        "issuer_category": "CORPORATE",
    }
    row.update(overrides)
    return row


def test_materiality_metrics_uses_fv_row_and_repeated_quarter_tiers():
    p0_fv = _materiality_metrics(
        affected_fair_value=30_000_000,
        total_fair_value=1_000_000_000,
        affected_rows=1,
        total_rows=100,
    )
    p1_fv = _materiality_metrics(
        affected_fair_value=6_000_000,
        total_fair_value=1_000_000_000,
        affected_rows=1,
        total_rows=100,
    )
    p1_rows = _materiality_metrics(
        affected_fair_value=0,
        total_fair_value=1_000_000_000,
        affected_rows=5,
        total_rows=100,
    )
    p0_rows = _materiality_metrics(
        affected_fair_value=0,
        total_fair_value=1_000_000_000,
        affected_rows=15,
        total_rows=100,
    )
    repeated = _materiality_metrics(
        affected_fair_value=1,
        total_fair_value=1_000_000_000,
        affected_rows=1,
        total_rows=100,
        quarter_count=2,
    )

    assert p0_fv["materiality_tier"] == "P0"
    assert p1_fv["materiality_tier"] == "P1"
    assert p1_rows["materiality_tier"] == "P1"
    assert p0_rows["materiality_tier"] == "P0"
    assert repeated["materiality_tier"] == "P1"


def test_row_delta_attribution_empty_when_trial_matches_production():
    holdings = pd.DataFrame([_holding()])

    deltas = _build_row_delta_attribution(holdings, holdings, cik="1786108")

    assert deltas.empty
    assert list(deltas.columns) == ROW_DELTA_ATTRIBUTION_COLUMNS


def test_row_delta_attribution_scopes_to_target_cik():
    trial = pd.DataFrame([_holding()])
    production = pd.DataFrame([
        _holding(),
        _holding(
            cik="0000000001",
            bdc_investment_identifier="Other Loan",
            issuer_name="Other Issuer",
            position_key="other loan",
        ),
    ])

    deltas = _build_row_delta_attribution(trial, production, cik="0001786108")

    assert deltas.empty


def test_row_delta_attribution_flags_added_and_removed_position_rows():
    production = pd.DataFrame([_holding()])
    trial = pd.DataFrame([
        _holding(
            bdc_investment_identifier="New Borrower Term Loan",
            issuer_name="New Borrower LLC",
            position_key="new borrower term loan",
            fair_value="2000",
        )
    ])

    deltas = _build_row_delta_attribution(trial, production, cik="0001786108")

    by_type = set(deltas["delta_type"])
    assert "added_position_leaf" in by_type
    assert "removed_position_leaf" in by_type
    assert set(deltas["review_status"]) == {"review"}


def test_row_delta_attribution_classifies_removed_non_private_and_aggregate_rows():
    production = pd.DataFrame([
        _holding(
            bdc_investment_identifier="Goldman Sachs Liquidity Fund",
            issuer_name="Goldman Sachs Liquidity Fund",
            position_key="goldman sachs liquidity fund",
            exposure_type="LIQUID",
            index_classification="CASH",
        ),
        _holding(
            bdc_investment_identifier="Total Debt Investments",
            issuer_name="Total Debt Investments",
            instrument_description="",
            position_key="total debt investments",
        ),
    ])
    trial = pd.DataFrame(columns=production.columns)

    deltas = _build_row_delta_attribution(trial, production, cik="0001786108")

    assert set(deltas["delta_type"]) == {"removed_non_private", "removed_aggregate"}
    assert set(deltas["review_status"]) == {"info"}


def test_row_delta_attribution_reports_parsed_and_classification_changes():
    production = pd.DataFrame([_holding()])
    trial = pd.DataFrame([
        _holding(
            issuer_name="Jackson Paper Manufacturing Co.",
            instrument_description="First Lien Initial Term Loan",
            position_key="jackson paper first lien initial term loan",
            index_classification="UNCLASSIFIED",
        )
    ])

    deltas = _build_row_delta_attribution(trial, production, cik="0001786108")

    assert {
        "changed_issuer_name",
        "changed_instrument_description",
        "changed_position_key",
        "changed_index_classification",
    }.issubset(set(deltas["delta_type"]))
    classification = deltas[deltas["delta_type"] == "changed_index_classification"].iloc[0]
    assert "index_classification" in classification["changed_columns"]


def test_row_delta_attribution_numeric_tolerance():
    production = pd.DataFrame([_holding(fair_value="1000.00", interest_rate="10.0")])
    tiny_change = pd.DataFrame([_holding(fair_value="1000.05", interest_rate="10.0")])
    material_change = pd.DataFrame([_holding(fair_value="1000.05", interest_rate="10.5")])

    tiny_deltas = _build_row_delta_attribution(tiny_change, production, cik="0001786108")
    material_deltas = _build_row_delta_attribution(material_change, production, cik="0001786108")

    assert tiny_deltas.empty
    numeric = material_deltas[material_deltas["delta_type"] == "changed_numeric_value"].iloc[0]
    assert numeric["changed_columns"] == "interest_rate"


def test_row_delta_attribution_trial_writes_artifact(tmp_path):
    trial_file = tmp_path / "trial_holdings.csv"
    pd.DataFrame([
        _holding(
            cik="0000000002",
            bdc_investment_identifier="New Trial Loan",
            issuer_name="New Trial Borrower LLC",
            position_key="new trial borrower term loan",
        )
    ]).to_csv(trial_file, index=False)
    production = pd.DataFrame([
        _holding(
            cik="0000000002",
            bdc_investment_identifier="Old Production Loan",
            issuer_name="Old Production Borrower LLC",
            position_key="old production borrower term loan",
        )
    ])

    empty_detail = pd.DataFrame(columns=DETAIL_COLUMNS)
    empty_summary = pd.DataFrame(columns=ORACLE_SUMMARY_COLUMNS)
    with mock.patch(
        "pipeline.bdc_xbrl_wrapper_oracle._load_cached_source_facts_for_cik",
        return_value=pd.DataFrame(),
    ), mock.patch(
        "pipeline.bdc_xbrl_wrapper_oracle._load_current_production_bdc_holdings_for_cik",
        return_value=production,
    ), mock.patch(
        "pipeline.bdc_xbrl_wrapper_oracle.BDC_HOLDINGS_FILE",
        tmp_path / "missing_bdc_holdings.csv",
    ), mock.patch(
        "pipeline.bdc_xbrl_wrapper_oracle._wrapper_position_keys",
        return_value=set(),
    ), mock.patch(
        "pipeline.bdc_xbrl_wrapper_oracle.reconcile_bdc_source_to_holdings",
        return_value=(empty_detail, {}),
    ), mock.patch(
        "pipeline.bdc_xbrl_wrapper_oracle.build_wrapper_oracle_outputs",
        return_value=(
            empty_summary,
            pd.DataFrame(columns=DETAIL_COLUMNS),
            pd.DataFrame(columns=DETAIL_COLUMNS),
            pd.DataFrame(),
        ),
    ):
        run_wrapper_oracle_trial(
            cik="0000000002",
            holdings_file=trial_file,
            output_dir=tmp_path,
        )

    written = pd.read_csv(tmp_path / "row_delta_attribution.csv")
    assert list(written.columns) == ROW_DELTA_ATTRIBUTION_COLUMNS
    assert set(written["delta_type"]) == {"added_position_leaf", "removed_position_leaf"}


# ---------------------------------------------------------------------------
# High-FV unclassified cluster packets
# ---------------------------------------------------------------------------


def test_high_fv_unclassified_clusters_empty_without_threshold():
    wrapper = WrapperDefinition(
        cik="0001786108",
        entity_name="Test BDC",
        version=1,
        archetypes=(
            Archetype(
                name="debt",
                description="Debt instruments",
                keywords=("term loan",),
                keyword_mode="any",
                field_signatures=(),
            ),
        ),
    )
    holdings = pd.DataFrame([
        _holding(
            bdc_investment_identifier="Apollo Co-Investment Program",
            issuer_name="Apollo Co-Investment Program",
            instrument_description="",
            fair_value="1000",
        )
    ])

    clusters = _build_high_fv_unclassified_clusters(holdings, wrapper, cik="0001786108")

    assert clusters.empty
    assert list(clusters.columns) == HIGH_FV_UNCLASSIFIED_CLUSTER_COLUMNS


def test_high_fv_unclassified_clusters_empty_below_threshold():
    wrapper = _make_wrapper(max_fv_pct=0.50)
    holdings = pd.DataFrame([
        _holding(
            bdc_investment_identifier="Acme Corp Term Loan",
            issuer_name="Acme Corp",
            instrument_description="Term Loan",
            fair_value="900",
        ),
        _holding(
            bdc_investment_identifier="Apollo Co-Investment Program",
            issuer_name="Apollo Co-Investment Program",
            instrument_description="",
            fair_value="100",
        ),
    ])

    clusters = _build_high_fv_unclassified_clusters(holdings, wrapper, cik="0001786108")

    assert clusters.empty
    assert list(clusters.columns) == HIGH_FV_UNCLASSIFIED_CLUSTER_COLUMNS


def test_high_fv_unclassified_clusters_groups_repeated_high_fv_labels():
    wrapper = _make_wrapper(max_fv_pct=0.10)
    holdings = pd.DataFrame([
        _holding(
            bdc_investment_identifier="Acme Corp Term Loan",
            issuer_name="Acme Corp",
            instrument_description="Term Loan",
            fair_value="100",
        ),
        _holding(
            bdc_investment_identifier="Apollo Co-Investment Program LP Interest A",
            issuer_name="Apollo Co-Investment Program",
            instrument_description="LP Interest",
            position_key="apollo co investment program lp interest a",
            fair_value="600",
            index_classification="PRIVATE_CREDIT_FUND",
            asset_category="FUND",
            exposure_type="FUND",
        ),
        _holding(
            bdc_investment_identifier="Apollo Co-Investment Program LP Interest B",
            issuer_name="Apollo Co-Investment Program",
            instrument_description="LP Interest",
            position_key="apollo co investment program lp interest b",
            fair_value="300",
            index_classification="PRIVATE_CREDIT_FUND",
            asset_category="FUND",
            exposure_type="FUND",
        ),
    ])

    clusters = _build_high_fv_unclassified_clusters(holdings, wrapper, cik="0001786108")

    assert list(clusters.columns) == HIGH_FV_UNCLASSIFIED_CLUSTER_COLUMNS
    assert len(clusters) == 1
    row = clusters.iloc[0]
    assert row["cluster_label"] == "Apollo Co-Investment Program"
    assert row["affected_report_dates"] == "2024-12-31"
    assert row["quarter_count"] == 1
    assert row["row_count"] == 2
    assert row["fair_value_abs_sum"] == 900.0
    assert row["fair_value_share"] == 0.9
    assert row["max_quarter_fair_value_share"] == 0.9
    assert row["source_family_guess"] == "fund"
    assert row["suggested_wrapper_family"] == "fund"
    assert row["output_asset_category"] == "FUND"
    assert row["owner"] == "wrapper"
    assert row["review_status"] == "review"


def test_high_fv_unclassified_clusters_excludes_classified_and_wrapper_family_rows():
    wrapper = _make_wrapper(max_fv_pct=0.10)
    holdings = pd.DataFrame([
        _holding(
            bdc_investment_identifier="Acme Corp Term Loan",
            issuer_name="Acme Corp",
            instrument_description="Term Loan",
            fair_value="100",
        ),
        _holding(
            bdc_investment_identifier="Apex Service Partners LLC 3",
            issuer_name="Apex Service Partners LLC",
            instrument_description="",
            position_key="apex service partners llc 3",
            wrapper_family="debt",
            wrapper_disposition="debt_position_leaf",
            fair_value="900",
        ),
    ])

    clusters = _build_high_fv_unclassified_clusters(holdings, wrapper, cik="0001786108")

    assert clusters.empty
    assert list(clusters.columns) == HIGH_FV_UNCLASSIFIED_CLUSTER_COLUMNS


def test_high_fv_unclassified_clusters_scope_and_multi_quarter_summary():
    wrapper = _make_wrapper(max_fv_pct=0.10)
    holdings = pd.DataFrame([
        _holding(
            report_date="2024-09-30",
            bdc_investment_identifier="Acme Corp Term Loan",
            issuer_name="Acme Corp",
            instrument_description="Term Loan",
            fair_value="100",
        ),
        _holding(
            report_date="2024-09-30",
            bdc_investment_identifier="Apollo Co-Investment Program LP Interest",
            issuer_name="Apollo Co-Investment Program",
            instrument_description="LP Interest",
            position_key="apollo co investment program lp interest q3",
            fair_value="400",
        ),
        _holding(
            report_date="2024-12-31",
            bdc_investment_identifier="Acme Corp Term Loan",
            issuer_name="Acme Corp",
            instrument_description="Term Loan",
            fair_value="100",
        ),
        _holding(
            report_date="2024-12-31",
            bdc_investment_identifier="Apollo Co-Investment Program LP Interest",
            issuer_name="Apollo Co-Investment Program",
            instrument_description="LP Interest",
            position_key="apollo co investment program lp interest q4",
            fair_value="600",
        ),
        _holding(
            cik="0000000001",
            report_date="2024-12-31",
            bdc_investment_identifier="Other Co-Investment Program",
            issuer_name="Other Co-Investment Program",
            instrument_description="LP Interest",
            position_key="other co investment program",
            fair_value="100000",
        ),
    ])

    clusters = _build_high_fv_unclassified_clusters(holdings, wrapper, cik="0001786108")

    assert len(clusters) == 1
    row = clusters.iloc[0]
    assert row["cluster_label"] == "Apollo Co-Investment Program"
    assert row["quarter_count"] == 2
    assert row["affected_report_dates"] == "2024-09-30|2024-12-31"
    assert row["fair_value_abs_sum"] == 1000.0
    assert row["max_quarter_fair_value_share"] == pytest.approx(0.857143)


def test_high_fv_unclassified_clusters_trial_writes_artifact(tmp_path):
    wrapper = WrapperDefinition(
        cik="0000000002",
        entity_name="Test BDC",
        version=1,
        archetypes=(
            Archetype(
                name="debt",
                description="Debt instruments",
                keywords=("term loan",),
                keyword_mode="any",
                field_signatures=(),
            ),
        ),
        unclassified_rate=UnclassifiedRate(max_pct=0.10, max_fv_pct=0.10),
    )
    trial_file = tmp_path / "trial_holdings.csv"
    pd.DataFrame([
        _holding(
            cik="0000000002",
            bdc_investment_identifier="Acme Corp Term Loan",
            issuer_name="Acme Corp",
            instrument_description="Term Loan",
            position_key="acme corp term loan",
            fair_value="100",
        ),
        _holding(
            cik="0000000002",
            bdc_investment_identifier="Apollo Co-Investment Program LP Interest",
            issuer_name="Apollo Co-Investment Program",
            instrument_description="LP Interest",
            position_key="apollo co investment program lp interest",
            fair_value="900",
            index_classification="PRIVATE_CREDIT_FUND",
            asset_category="FUND",
            exposure_type="FUND",
        ),
    ]).to_csv(trial_file, index=False)

    empty_detail = pd.DataFrame(columns=DETAIL_COLUMNS)
    empty_summary = pd.DataFrame(columns=ORACLE_SUMMARY_COLUMNS)
    with mock.patch(
        "pipeline.bdc_xbrl_wrapper_oracle._load_cached_source_facts_for_cik",
        return_value=pd.DataFrame(),
    ), mock.patch(
        "pipeline.bdc_xbrl_wrapper_oracle._load_current_production_bdc_holdings_for_cik",
        return_value=pd.DataFrame(),
    ), mock.patch(
        "pipeline.bdc_xbrl_wrapper_oracle.BDC_HOLDINGS_FILE",
        tmp_path / "missing_bdc_holdings.csv",
    ), mock.patch(
        "pipeline.bdc_xbrl_wrapper_oracle._wrapper_position_keys",
        return_value=set(),
    ), mock.patch(
        "pipeline.bdc_xbrl_wrapper_oracle.reconcile_bdc_source_to_holdings",
        return_value=(empty_detail, {}),
    ), mock.patch(
        "pipeline.bdc_xbrl_wrapper_oracle.build_wrapper_oracle_outputs",
        return_value=(
            empty_summary,
            pd.DataFrame(columns=DETAIL_COLUMNS),
            pd.DataFrame(columns=DETAIL_COLUMNS),
            pd.DataFrame(),
        ),
    ), mock.patch(
        "pipeline.bdc_xbrl_wrapper_oracle.load_wrapper_definition",
        return_value=wrapper,
    ):
        run_wrapper_oracle_trial(
            cik="0000000002",
            holdings_file=trial_file,
            output_dir=tmp_path,
        )

    written = pd.read_csv(tmp_path / "high_fv_unclassified_clusters.csv")
    assert list(written.columns) == HIGH_FV_UNCLASSIFIED_CLUSTER_COLUMNS
    assert len(written) == 1
    assert written.iloc[0]["cluster_label"] == "Apollo Co-Investment Program"
    assert written.iloc[0]["source_family_guess"] == "fund"

    agent_clusters = pd.read_csv(tmp_path / "agent_cluster_packets.csv")
    agent_issues = pd.read_csv(tmp_path / "agent_issue_packets.csv")
    drift_summary = pd.read_csv(tmp_path / "column_drift_summary.csv")
    verdict_summary = pd.read_csv(tmp_path / "agent_verdict_summary.csv")
    assert list(agent_clusters.columns) == AGENT_CLUSTER_PACKET_COLUMNS
    assert "WRAP.HIGH_FV_UNCLASSIFIED_CLUSTER" in set(agent_clusters["rule_id"])
    assert list(agent_issues.columns) == AGENT_ISSUE_PACKET_COLUMNS
    assert list(drift_summary.columns) == COLUMN_DRIFT_SUMMARY_COLUMNS
    assert list(verdict_summary.columns) == AGENT_VERDICT_SUMMARY_COLUMNS
    assert (tmp_path / "agent_cluster_packets.jsonl").exists()
    assert (tmp_path / "agent_issue_packets.jsonl").exists()


# ---------------------------------------------------------------------------
# Agent review packets and drift diagnostics
# ---------------------------------------------------------------------------


def test_source_verbose_identifier_packets_flag_when_output_is_contaminated():
    detail = _detail([{
        "source_row_id": "src-1",
        "raw_investment_identifier": (
            "Debt Investments Type of Investment First Lien Term Loan "
            "Investment Date 01/01/2024 Maturity Date 12/31/2028 "
            "Interest Rate SOFR + 6.00%"
        ),
        "source_fair_value": 6_000_000,
        "issuer_name": "Debt Investments Type of Investment First Lien Term Loan",
    }])
    holdings = pd.DataFrame([
        _holding(fair_value="994000000"),
        _holding(
            bdc_investment_identifier="Corrupted Source Row",
            position_key="corrupted source row",
            fair_value="6000000",
        ),
    ])

    packets = _build_source_verbose_identifier_packets(detail, holdings, cik="1786108")

    assert list(packets.columns) == AGENT_ISSUE_PACKET_COLUMNS
    assert len(packets) == 1
    row = packets.iloc[0]
    assert row["rule_id"] == "WRAP.SOURCE_VERBOSE_IDENTIFIER"
    assert row["source_rule_id"] == "WRAP.SOURCE_CORRUPTED_IDENTIFIER"
    assert row["likely_owner"] == "wrapper"
    assert row["materiality_tier"] == "P1"
    assert row["review_status"] == "review"


def test_source_verbose_identifier_packets_ignore_clean_output_false_positive():
    detail = _detail([{
        "source_row_id": "src-1",
        "raw_investment_identifier": (
            "Debt Investments Type of Investment First Lien Term Loan "
            "Investment Date 01/01/2024 Maturity Date 12/31/2028 "
            "Interest Rate SOFR + 6.00%"
        ),
        "source_fair_value": 6_000_000,
        "issuer_name": "Jackson Paper Manufacturing Company",
        "instrument_description": "First Lien Term Loan",
        "status": "matched",
        "calibrated_status": "matched",
    }])
    holdings = pd.DataFrame([_holding(fair_value="6000000")])

    packets = _build_source_verbose_identifier_packets(detail, holdings, cik="1786108")

    assert packets.empty
    assert list(packets.columns) == AGENT_ISSUE_PACKET_COLUMNS


def test_column_drift_packets_use_short_history_and_emit_examples():
    holdings = pd.DataFrame([
        _holding(report_date="2024-03-31", interest_rate="10.00", fair_value="100"),
        _holding(report_date="2024-06-30", interest_rate="11.00", fair_value="100"),
        _holding(
            report_date="2024-09-30",
            interest_rate="SOFR + 6.00%",
            fair_value="100",
            bdc_investment_identifier="Jackson Paper SOFR Loan",
        ),
    ])

    summary, examples = _build_column_drift_packets(holdings, cik="1786108")

    assert list(summary.columns) == COLUMN_DRIFT_SUMMARY_COLUMNS
    assert list(examples.columns) == COLUMN_DRIFT_EXAMPLE_COLUMNS
    interest_rate_q3 = summary[
        summary["column"].eq("interest_rate")
        & summary["report_date"].eq("2024-09-30")
    ].iloc[0]
    assert interest_rate_q3["baseline_quarter_count"] == 2
    assert interest_rate_q3["status"] == "review"
    assert interest_rate_q3["current_dominant_bucket"] == "rate_text"
    assert interest_rate_q3["baseline_dominant_bucket"] == "numeric_pct"
    assert "rate_text" in interest_rate_q3["bucket_distribution"]
    assert not examples.empty
    assert "interest_rate" in set(examples["column"])


def test_column_drift_packets_flag_identity_text_shape_shift():
    holdings = pd.DataFrame([
        _holding(report_date="2024-03-31", issuer_name="Jackson Paper Manufacturing Company"),
        _holding(report_date="2024-06-30", issuer_name="Acme Software Inc."),
        _holding(
            report_date="2024-09-30",
            issuer_name="Debt Investments Type of Investment First Lien Term Loan Interest Rate SOFR + 6.00%",
            bdc_investment_identifier="verbose-label-residue",
            fair_value="100",
        ),
    ])

    summary, examples = _build_column_drift_packets(holdings, cik="1786108")

    issuer_q3 = summary[
        summary["column"].eq("issuer_name")
        & summary["report_date"].eq("2024-09-30")
    ].iloc[0]
    assert issuer_q3["status"] == "review"
    assert issuer_q3["current_dominant_bucket"] == "field_label_text"
    assert "issuer_name" in set(examples["column"])


def test_agent_issue_packets_merge_parsed_source_verbose_cost_and_column_validation_artifacts():
    detail = _detail([{
        "source_row_id": "src-1",
        "output_row_id": "out-1",
        "issuer_name": "Apryse Software Corp Interest Rate 9.05% Maturity Date 6/26/2032",
        "output_fair_value": 6_000_000,
        "raw_investment_identifier": (
            "Debt Investments Type of Investment First Lien Term Loan "
            "Maturity Date 6/26/2032 Interest Rate 9.05%"
        ),
    }])
    holdings = pd.DataFrame([
        _holding(fair_value="994000000"),
        _holding(
            bdc_investment_identifier="Apryse Software Corp Term Loan",
            issuer_name="Apryse Software Corp",
            position_key="apryse software corp term loan",
            fair_value="6000000",
        ),
    ])
    parsed = _build_parsed_field_quality_packets(detail, holdings, cik="1786108")
    source_verbose = _build_source_verbose_identifier_packets(
        detail,
        holdings,
        parsed_field_quality=parsed,
        cik="1786108",
    )
    cost_outliers = _build_cost_fv_outlier_packets(pd.DataFrame([
        _holding(
            bdc_investment_identifier="Tiny Mark Loan",
            cost="100",
            fair_value="100000",
        )
    ]), cik="1786108")
    column_issues = pd.DataFrame([{
        "dataset": "private_markets_holdings",
        "source": "bdc",
        "cik": "0001786108",
        "report_date": "2024-12-31",
        "row_key": "0",
        "column": "interest_rate",
        "rule_id": "C201",
        "severity": "FAIL",
        "evidence_strength": "STRONG",
        "status": "OPEN",
        "action": "REVIEW",
        "value": "SOFR plus too much text",
        "message": "interest_rate must be parseable",
        "evidence": "parse failed",
    }])

    packets = _build_agent_issue_packets(
        parsed_field_quality=parsed,
        source_verbose_identifiers=source_verbose,
        cost_fv_outliers=cost_outliers,
        column_validation_issues=column_issues,
        holdings_df=holdings,
        cik="1786108",
    )

    assert list(packets.columns) == AGENT_ISSUE_PACKET_COLUMNS
    assert {
        "WRAP.PARSED_FIELD_CONTAMINATION",
        "WRAP.SOURCE_VERBOSE_IDENTIFIER",
        "WRAP.COST_FV_RATIO_OUTLIER",
        "WRAP.PRODUCTION_COLUMN_VALIDATION",
    }.issubset(set(packets["rule_id"]))
    validation = packets[packets["rule_id"].eq("WRAP.PRODUCTION_COLUMN_VALIDATION")].iloc[0]
    assert validation["source_rule_id"] == "C201"
    assert validation["likely_owner"] == "wrapper"
    assert set(packets["packet_type"]) == {"row"}
    assert packets["issue_id"].is_unique


def test_agent_cluster_packets_merge_delta_high_fv_and_drift_artifacts():
    production = pd.DataFrame([_holding()])
    trial = pd.DataFrame([
        _holding(
            bdc_investment_identifier="New Borrower Term Loan",
            issuer_name="New Borrower LLC",
            position_key="new borrower term loan",
            fair_value="5000000",
        )
    ])
    row_delta = _build_row_delta_attribution(trial, production, cik="1786108")
    high_fv = pd.DataFrame([{
        "cik": "0001786108",
        "entity_name": "Trinity Capital Inc.",
        "cluster_label": "Apollo Co-Investment Program",
        "affected_report_dates": "2024-12-31",
        "quarter_count": 1,
        "row_count": 2,
        "fair_value_abs_sum": 10_000_000,
        "fair_value_share": 0.25,
        "max_quarter_fair_value_share": 0.25,
        "source_family_guess": "fund",
        "suggested_wrapper_family": "fund",
        "output_index_classification": "PRIVATE_CREDIT_FUND",
        "output_asset_category": "FUND",
        "output_exposure_type": "FUND",
        "sample_identifiers": "Apollo Co-Investment Program LP Interest",
        "sample_issuer_names": "Apollo Co-Investment Program",
        "sample_instrument_descriptions": "LP Interest",
        "suggested_review_question": "Should this cluster be wrapper-covered?",
        "owner": "wrapper",
        "review_status": "review",
    }], columns=HIGH_FV_UNCLASSIFIED_CLUSTER_COLUMNS)
    drift = pd.DataFrame([{
        "cik": "0001786108",
        "entity_name": "Trinity Capital Inc.",
        "report_date": "2024-12-31",
        "column": "interest_rate",
        "baseline_quarter_count": 2,
        "row_count": 1,
        "fair_value_abs_sum": 5_000_000,
        "js_divergence": 0.5,
        "new_bucket_share": 1.0,
        "current_dominant_bucket": "rate_text",
        "baseline_dominant_bucket": "numeric_pct",
        "status": "review",
        "severity": "review",
        "materiality_tier": "P1",
        "bucket_distribution": "rate_text:1.000000",
        "baseline_bucket_distribution": "numeric_pct:1.000000",
    }], columns=COLUMN_DRIFT_SUMMARY_COLUMNS)
    holdings = pd.DataFrame([
        _holding(fair_value="5000000"),
        _holding(
            bdc_investment_identifier="Apollo Co-Investment Program LP Interest",
            position_key="apollo co investment program lp interest",
            fair_value="10000000",
        ),
    ])

    packets = _build_agent_cluster_packets(
        row_delta_attribution=row_delta,
        high_fv_unclassified_clusters=high_fv,
        column_drift_summary=drift,
        holdings_df=holdings,
        cik="1786108",
    )

    assert list(packets.columns) == AGENT_CLUSTER_PACKET_COLUMNS
    assert {
        "WRAP.ROW_DELTA_ATTRIBUTION",
        "WRAP.HIGH_FV_UNCLASSIFIED_CLUSTER",
        "WRAP.COLUMN_DISTRIBUTION_DRIFT",
    }.issubset(set(packets["rule_id"]))
    assert set(packets["packet_type"]) == {"cluster"}
    assert packets["issue_id"].is_unique


def test_agent_cluster_packets_include_no_wrapper_rows_summary():
    oracle_summary = pd.DataFrame([{
        "cik": "0001786108",
        "entity_name": "Trinity Capital Inc.",
        "report_date": "2024-12-31",
        "oracle_fail_reasons": "no_wrapper_rows",
    }], columns=ORACLE_SUMMARY_COLUMNS)
    holdings = pd.DataFrame([_holding(fair_value="5000000")])

    packets = _build_agent_cluster_packets(
        row_delta_attribution=pd.DataFrame(columns=ROW_DELTA_ATTRIBUTION_COLUMNS),
        high_fv_unclassified_clusters=pd.DataFrame(columns=HIGH_FV_UNCLASSIFIED_CLUSTER_COLUMNS),
        column_drift_summary=pd.DataFrame(columns=COLUMN_DRIFT_SUMMARY_COLUMNS),
        oracle_summary=oracle_summary,
        holdings_df=holdings,
        cik="1786108",
    )

    assert list(packets.columns) == AGENT_CLUSTER_PACKET_COLUMNS
    assert len(packets) == 1
    assert packets.iloc[0]["rule_id"] == "WRAP.NO_WRAPPER_ROWS"
    assert packets.iloc[0]["representative_rows_path"] == "oracle_summary.csv"


def test_agent_verdict_validation_and_summary_promotion_effects():
    valid = [{
        "issue_id": "WRAP|0001786108|2024-12-31|WRAP.ROW_DELTA_ATTRIBUTION|1",
        "rule_id": "WRAP.ROW_DELTA_ATTRIBUTION",
        "severity": "review",
        "materiality_tier": "P1",
        "likely_owner": "wrapper",
        "cik": "0001786108",
        "report_date": "2024-12-31",
        "verdict": "true_wrapper_error",
        "mechanism": "wrapper failed to split source leaf",
        "recommended_action": "Add CIK-local wrapper leaf pattern with source evidence.",
        "confidence": 0.92,
        "affected_fair_value": 10_000_000,
        "evidence": "Source row and trial row reviewed.",
        "residual_risk": "Low after targeted regression test.",
    }]
    invalid = [{
        **valid[0],
        "issue_id": "bad-confidence",
        "confidence": 1.5,
    }]
    unsafe_action = [{
        **valid[0],
        "issue_id": "unsafe-action",
        "recommended_action": "Hand-edit production output CSV.",
    }]

    assert validate_agent_verdict_records(valid) == []
    assert any("confidence" in error for error in validate_agent_verdict_records(invalid))
    assert any("hand-edited" in error for error in validate_agent_verdict_records(unsafe_action))

    summary = build_agent_verdict_summary(valid)
    assert list(summary.columns) == AGENT_VERDICT_SUMMARY_COLUMNS
    assert summary.iloc[0]["promotion_effect"] == "reject"
    assert summary.iloc[0]["issue_count"] == 1


def test_promotion_gate_consumes_agent_verdict_summary():
    summary = _oracle_summary([{}])
    reject_verdicts = pd.DataFrame([{
        "verdict": "true_wrapper_error",
        "likely_owner": "wrapper",
        "materiality_tier": "P1",
        "issue_count": 1,
        "affected_fair_value": 10_000_000,
        "max_confidence": 0.92,
        "promotion_effect": "reject",
    }], columns=AGENT_VERDICT_SUMMARY_COLUMNS)
    review_verdicts = pd.DataFrame([{
        "verdict": "inconclusive",
        "likely_owner": "unknown",
        "materiality_tier": "P1",
        "issue_count": 1,
        "affected_fair_value": 10_000_000,
        "max_confidence": 0.70,
        "promotion_effect": "review",
    }], columns=AGENT_VERDICT_SUMMARY_COLUMNS)

    reject = evaluate_promotion_gate(summary, verdict_summary=reject_verdicts)
    review = evaluate_promotion_gate(summary, verdict_summary=review_verdicts)

    assert reject.status == "reject"
    assert any("agent_verdict_reject" in reason for reason in reject.reasons)
    assert review.status == "review_required"
    assert any("agent_verdict_review" in reason for reason in review.reasons)


# ---------------------------------------------------------------------------
# Parsed-field quality review packets
# ---------------------------------------------------------------------------


def test_parsed_field_quality_flags_contaminated_output_columns():
    detail = _detail([{
        "status": "matched",
        "source_row_id": "src-1",
        "output_row_id": "out-1",
        "issuer_name": (
            "Non-controlled/Non-affiliated Investments Debt Investments "
            "Apryse Software Corp Interest Rate 9.05% Maturity Date 6/26/2032"
        ),
        "instrument_description": "Senior loans 195.1% | Chemicals 12.0%",
        "output_wrapper_disposition": "debt_position_leaf",
        "output_wrapper_position_key": (
            "Apryse Software Corp Term Loan Interest Rate 9.05% Maturity Date 6/26/2032"
        ),
        "output_fair_value": 1234567,
    }])

    packets = _build_parsed_field_quality_packets(detail, pd.DataFrame(), cik="1786108")

    assert list(packets.columns) == PARSED_FIELD_QUALITY_COLUMNS
    assert set(packets["column"]) == {
        "issuer_name",
        "instrument_description",
        "position_key",
    }
    assert "hierarchy_or_metric_contamination" in set(packets["issue_type"])
    assert "rate_or_date_contamination" in set(packets["issue_type"])
    assert set(packets["severity"]) == {"warn"}
    assert packets["fair_value"].astype(float).max() == 1234567


def test_parsed_field_quality_ignores_clean_rows_and_scopes_to_cik():
    detail = _detail([{
        "cik": "0001786108",
        "issuer_name": "Jackson Paper Manufacturing Company",
        "instrument_description": "Initial Term Loan",
        "output_wrapper_position_key": "jackson paper initial term loan",
        "output_wrapper_disposition": "debt_position_leaf",
    }])
    holdings = pd.DataFrame([
        {
            "cik": "0001786108",
            "entity_name": "Trinity Capital Inc.",
            "report_date": "2024-12-31",
            "accession_number": "0001786108-25-000001",
            "bdc_investment_identifier": "Jackson Paper Initial Term Loan",
            "position_key": "jackson paper initial term loan",
            "fair_value": "100",
        },
        {
            "cik": "0000000001",
            "entity_name": "Other BDC",
            "report_date": "2024-12-31",
            "accession_number": "0000000001-25-000001",
            "bdc_investment_identifier": "Other Loan",
            "position_key": "Other Loan Interest Rate 12.00% Maturity Date 1/1/2030",
            "fair_value": "200",
        },
    ])

    packets = _build_parsed_field_quality_packets(detail, holdings, cik="0001786108")

    assert packets.empty
    assert list(packets.columns) == PARSED_FIELD_QUALITY_COLUMNS


def test_parsed_field_quality_allows_coupon_bearing_instrument_descriptions():
    detail = _detail([{
        "cik": "0001786108",
        "issuer_name": "Mental Healthcare Services",
        "instrument_description": (
            "Delayed Draw Term Loan (3M USD TERM SOFR+8.40%), "
            "12.86% Cash, 8/5/2027"
        ),
        "output_wrapper_position_key": "mental healthcare services delayed draw term loan",
        "output_wrapper_disposition": "debt_position_leaf",
        "output_fair_value": 1000,
    }])

    packets = _build_parsed_field_quality_packets(detail, pd.DataFrame(), cik="0001786108")

    assert packets.empty
    assert list(packets.columns) == PARSED_FIELD_QUALITY_COLUMNS


def test_parsed_field_quality_summarizes_without_changing_oracle_status():
    detail = _detail([{
        "status": "documented_source_rollup_exact",
        "residual_class": "documented_exclusion",
        "calibrated_status": "documented_source_rollup_exact",
        "issuer_name": "Non-controlled Investments Apryse Software Corp 9.05%",
        "output_fair_value": 500,
    }])

    with mock.patch(
        "pipeline.bdc_xbrl_wrapper_oracle._check_content_signatures",
        return_value={},
    ), mock.patch(
        "pipeline.bdc_xbrl_wrapper_oracle.load_wrapper_definition",
        return_value=None,
    ):
        summary, _, _, _ = build_wrapper_oracle_outputs(detail)

    status_before = summary.iloc[0]["oracle_status"]
    reasons_before = summary.iloc[0]["oracle_fail_reasons"]
    packets = _build_parsed_field_quality_packets(detail, pd.DataFrame(), cik="0001786108")
    updated = _append_parsed_field_quality_summary(summary, packets)

    assert status_before == "pass"
    assert updated.iloc[0]["oracle_status"] == status_before
    assert updated.iloc[0]["oracle_fail_reasons"] == reasons_before
    assert updated.iloc[0]["parsed_field_quality_issue_count"] > 0
    assert updated.iloc[0]["parsed_field_quality_fair_value"] == 500


# ---------------------------------------------------------------------------
# Wrapper JSON coherence checks
# ---------------------------------------------------------------------------


def test_coherence_passes_for_valid_wrapper():
    """A well-formed wrapper JSON has no coherence issues."""
    raw = {
        "schema_version": "bdc-xbrl-wrapper.v3",
        "cik": "0001786108",
        "entity_name": "Trinity Capital Inc.",
        "version": 1,
        "dispatch": {
            "rule_prefix": "TRINITY",
            "prefix_rules": {"Debt Investments": "debt", "Equity": "equity"},
            "leaf_markers_by_family": {
                "debt": ["interest rate", "maturity"],
                "equity": ["common stock"],
            },
            "aggregate_markers": ["total investments"],
        },
        "archetypes": {
            "debt": {
                "description": "Debt",
                "detection_rules": {"keywords": ["Term Loan"], "keyword_mode": "any"},
            },
            "equity": {
                "description": "Equity",
                "detection_rules": {"keywords": ["Common stock"], "keyword_mode": "any"},
            },
        },
    }
    assert validate_wrapper_json_coherence(raw) == []


def test_coherence_catches_missing_leaf_markers_family():
    """Family in prefix_rules without leaf_markers_by_family entry is flagged as warning."""
    raw = {
        "dispatch": {
            "prefix_rules": {"Debt": "debt", "Mixed": "mixed"},
            "leaf_markers_by_family": {"debt": ["maturity"]},
        },
    }
    issues = validate_wrapper_json_coherence(raw)
    assert any("mixed" in i and "leaf_markers_by_family" in i for i in issues)
    # Should be a warning, not a hard error
    mixed_issues = [i for i in issues if "mixed" in i]
    assert all(i.startswith("warning:") for i in mixed_issues)


def test_coherence_catches_prefix_strip_missing_regex():
    """prefix_strip strategy without hierarchy_prefix_re is flagged."""
    raw = {
        "staging": {"strategy": "prefix_strip"},
    }
    issues = validate_wrapper_json_coherence(raw)
    assert any("hierarchy_prefix_re" in i for i in issues)


def test_coherence_catches_hierarchy_extract_missing_fields():
    """hierarchy_extract without both regexes is flagged."""
    raw = {
        "staging": {
            "strategy": "hierarchy_extract",
            "hierarchy_issuer_re": ".*",
        },
    }
    issues = validate_wrapper_json_coherence(raw)
    assert any("hierarchy_instrument_re" in i for i in issues)
    assert not any("hierarchy_issuer_re" in i for i in issues)


def test_coherence_catches_leaf_guard_missing_fields():
    """hierarchy_leaf_guard without marker_re/evidence_re is flagged."""
    raw = {
        "staging": {
            "strategy": "hierarchy_leaf_guard",
            "leaf_guard": {"marker_re": "term loan"},
        },
    }
    issues = validate_wrapper_json_coherence(raw)
    assert any("evidence_re" in i for i in issues)
    assert not any("marker_re" in i for i in issues)


def test_coherence_catches_issuer_bridge_empty():
    """issuer_bridge strategy with empty bridges is flagged."""
    raw = {
        "staging": {"strategy": "issuer_bridge", "issuer_bridges": []},
    }
    issues = validate_wrapper_json_coherence(raw)
    assert any("issuer_bridges" in i for i in issues)


def test_coherence_catches_bad_regex():
    """Invalid regex patterns are flagged."""
    raw = {
        "dispatch": {"canonical_strip_re": "[invalid("},
    }
    issues = validate_wrapper_json_coherence(raw)
    assert any("canonical_strip_re" in i and "valid regex" in i for i in issues)


def test_coherence_catches_bad_fallback_regex():
    """Invalid regex in fallback_family_patterns is flagged."""
    raw = {
        "dispatch": {
            "fallback_family_patterns": [{"regex": "[bad(", "family": "debt"}],
        },
    }
    issues = validate_wrapper_json_coherence(raw)
    assert any("fallback_family_patterns[0]" in i for i in issues)


def test_coherence_catches_fallback_family_missing_leaf_markers():
    """Fallback family with no leaf markers is flagged as warning."""
    raw = {
        "dispatch": {
            "leaf_markers_by_family": {"debt": ["maturity"]},
            "fallback_family_patterns": [{"regex": "equity", "family": "equity"}],
        },
    }
    issues = validate_wrapper_json_coherence(raw)
    assert any("fallback_family_patterns[0]" in i and "equity" in i for i in issues)
    fallback_issues = [i for i in issues if "fallback_family_patterns" in i]
    assert all(i.startswith("warning:") for i in fallback_issues)


def test_coherence_warns_disconnected_archetypes():
    """Archetype names with no dispatch family overlap triggers warning."""
    raw = {
        "dispatch": {
            "prefix_rules": {"Debt": "debt"},
        },
        "archetypes": {
            "first_lien": {"description": "1L", "detection_rules": {"keywords": ["1L"]}},
            "second_lien": {"description": "2L", "detection_rules": {"keywords": ["2L"]}},
        },
    }
    issues = validate_wrapper_json_coherence(raw)
    assert any("disconnected" in i and i.startswith("warning:") for i in issues)


def test_coherence_no_warning_when_archetypes_overlap_dispatch():
    """No warning when archetype names overlap with dispatch families."""
    raw = {
        "dispatch": {
            "prefix_rules": {"Debt": "debt", "Equity": "equity"},
        },
        "archetypes": {
            "debt": {"description": "Debt", "detection_rules": {"keywords": ["Loan"]}},
            "warrant": {"description": "Warrant", "detection_rules": {"keywords": ["Warrant"]}},
        },
    }
    issues = validate_wrapper_json_coherence(raw)
    assert not any("disconnected" in i for i in issues)


def test_coherence_passes_all_existing_wrappers():
    """All committed wrapper JSONs should pass coherence with zero hard errors.

    Warnings (prefixed with 'warning:') are allowed.
    """
    import glob
    wrapper_files = glob.glob(
        "data/overrides/bdc_xbrl_wrappers/*.json"
    )
    for path in wrapper_files:
        if "reference" in path:
            continue
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
        if raw.get("schema_version") not in (
            "bdc-xbrl-wrapper.v2",
            "bdc-xbrl-wrapper.v3",
        ):
            continue
        issues = validate_wrapper_json_coherence(raw)
        errors = [i for i in issues if not i.startswith("warning:")]
        assert errors == [], f"{path}: {errors}"
