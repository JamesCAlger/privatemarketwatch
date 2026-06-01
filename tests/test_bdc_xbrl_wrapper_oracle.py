from unittest import mock

import pandas as pd

from pipeline.bdc_xbrl_wrapper_oracle import (
    _UNCLASSIFIED_RATE_QOQ_JUMP_THRESHOLD,
    build_residual_wrapper_queue,
    build_wrapper_oracle_outputs,
    build_wrapper_profile_for_cik,
    run_wrapper_queue,
)
from pipeline.source_reconciliation import DETAIL_COLUMNS
from pipeline.wrapper_content_signatures import (
    Archetype,
    FieldSignature,
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
    }])

    summary, cleared, remaining, mechanisms = build_wrapper_oracle_outputs(detail)

    assert cleared.empty
    assert len(remaining) == 1
    assert mechanisms.iloc[0]["mechanism"] == "issuer_rollup_no_child_tie"
    assert summary.iloc[0]["oracle_status"] == "fail"
    assert "wrapper_blockers_remaining" in summary.iloc[0]["oracle_fail_reasons"]


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

    _summary, _cleared, _remaining, mechanisms = build_wrapper_oracle_outputs(detail)

    assert set(mechanisms["mechanism"]) == {"aggregate", "cash_or_money_market"}


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
