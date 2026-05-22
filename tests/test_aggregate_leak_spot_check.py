from __future__ import annotations

import math

import pandas as pd

from scripts.spot_check_aggregate_leak_suspects import (
    RARE_STRATA,
    SAMPLE_COLUMNS,
    allocate_sample,
    build_audit_frame,
    compute_weighted_false_positive_estimate,
    false_positive_rate_by_keyword,
    recurring_false_positive_patterns,
    render_review_summary,
    stratified_sample,
)


def _audit_rows(stratum_sizes: dict[str, int]) -> pd.DataFrame:
    rows = []
    for keyword, size in stratum_sizes.items():
        for idx in range(size):
            rows.append(
                {
                    "sample_row_key": f"{keyword}-{idx:05d}",
                    "sample_seed": 20260520,
                    "audit_keyword": keyword,
                    "audit_reason": f"keyword:{keyword}",
                    "cik": "0000000100",
                    "entity_name": "Test BDC",
                    "report_date": "2024-03-31",
                    "period": "2024-03-31",
                    "accession_number": "000100-24-000001",
                    "filing_date": "2024-05-01",
                    "bdc_form_type": "10-Q",
                    "issuer_name": f"{keyword} {idx}",
                    "instrument_description": "First Lien Term Loan",
                    "bdc_investment_identifier": f"{keyword} {idx} - First Lien",
                    "fair_value": float(1000 + idx),
                    "cost": float(900 + idx),
                    "pct_of_net_assets": "",
                    "shares_held": None,
                    "principal_amount": None,
                    "asset_category": "LOAN",
                    "issuer_category": "CORPORATE",
                    "index_classification": "DIRECT_LENDING",
                    "asset_class": "DEBT",
                    "exposure_type": "POSITION",
                    "interest_rate": 8.5,
                    "basis_spread": 3.5,
                    "reference_rate_type": "SOFR",
                    "coupon_type": "Floating",
                    "pik_rate": None,
                    "maturity_date": "2028-03-31",
                    "bdc_dimensions_raw": "",
                    "source_reconciliation_status": "",
                    "source_match_tier": "",
                    "source_issue_severity": "",
                    "source_residual_class": "",
                    "source_blocking_issue": None,
                    "source_calibrated_status": "",
                    "source_raw_identifier": "",
                    "source_normalized_identifier": "",
                    "source_context_id": "",
                    "source_concept_names": "",
                    "source_fair_value": None,
                    "source_cost": None,
                    "source_evidence": "",
                    "source_mismatched_fields": "",
                }
            )
    return pd.DataFrame(rows)


def test_sample_allocation_matches_planned_385_and_censuses_rare_strata():
    stratum_sizes = {
        "non-control": 29134,
        "investment debt investments": 11768,
        "net assets": 2480,
        "affiliate investments": 1110,
        "investment equity securities": 311,
        "investment unsecured": 4,
        "cash and cash equivalents": 8,
        "unfunded commitments": 9,
        "total investments": 9,
    }

    allocation = allocate_sample(stratum_sizes)

    assert sum(allocation.values()) == 385
    for rare in RARE_STRATA:
        assert allocation[rare] == stratum_sizes[rare]
    assert allocation["non-control"] == 186
    assert allocation["investment debt investments"] == 87
    assert allocation["net assets"] == 34
    assert allocation["affiliate investments"] == 26
    assert allocation["investment equity securities"] == 22


def test_stratified_sample_is_deterministic_unique_and_has_review_columns():
    audit_df = _audit_rows(
        {
            "non-control": 29134,
            "investment debt investments": 11768,
            "net assets": 2480,
            "affiliate investments": 1110,
            "investment equity securities": 311,
            "investment unsecured": 4,
            "cash and cash equivalents": 8,
            "unfunded commitments": 9,
            "total investments": 9,
        }
    )

    first = stratified_sample(audit_df)
    second = stratified_sample(audit_df)

    assert len(first) == 385
    assert not first["sample_row_key"].duplicated().any()
    assert first["sample_row_key"].tolist() == second["sample_row_key"].tolist()
    assert list(first.columns) == SAMPLE_COLUMNS
    assert (first["review_label"] == "").all()
    sample_counts = first.groupby("audit_keyword").size().to_dict()
    assert sample_counts["investment unsecured"] == 4
    assert sample_counts["cash and cash equivalents"] == 8
    assert sample_counts["unfunded commitments"] == 9
    assert sample_counts["total investments"] == 9


def test_weighted_false_positive_estimator_known_fixture():
    review_df = pd.DataFrame(
        [
            {"audit_keyword": "large", "stratum_size": 80, "review_label": "false_positive_valid_position"},
            {"audit_keyword": "large", "stratum_size": 80, "review_label": "confirmed_aggregate_leak"},
            {"audit_keyword": "large", "stratum_size": 80, "review_label": "confirmed_aggregate_leak"},
            {"audit_keyword": "large", "stratum_size": 80, "review_label": "confirmed_aggregate_leak"},
            {"audit_keyword": "small", "stratum_size": 20, "review_label": "false_positive_valid_position"},
            {"audit_keyword": "small", "stratum_size": 20, "review_label": "non_private_or_cash_scope_issue"},
        ]
    )

    result = compute_weighted_false_positive_estimate(review_df)

    assert result["reviewed_rows"] == 6
    assert math.isclose(result["weighted_false_positive_rate"], 0.4)
    assert 0 <= result["ci95_low"] <= result["weighted_false_positive_rate"]
    assert result["weighted_false_positive_rate"] <= result["ci95_high"] <= 1


def test_weighted_false_positive_estimator_excludes_ambiguous_and_reports_sensitivity():
    review_df = pd.DataFrame(
        [
            {"audit_keyword": "large", "stratum_size": 80, "review_label": "false_positive_valid_position"},
            {"audit_keyword": "large", "stratum_size": 80, "review_label": "confirmed_aggregate_leak"},
            {"audit_keyword": "large", "stratum_size": 80, "review_label": "ambiguous_needs_filing_context"},
            {"audit_keyword": "small", "stratum_size": 20, "review_label": "non_private_or_cash_scope_issue"},
            {"audit_keyword": "small", "stratum_size": 20, "review_label": "confirmed_aggregate_leak"},
        ]
    )

    result = compute_weighted_false_positive_estimate(review_df)
    by_keyword = false_positive_rate_by_keyword(review_df)

    assert result["reviewed_rows"] == 5
    assert result["estimate_rows"] == 4
    assert result["ambiguous_rows"] == 1
    assert math.isclose(result["weighted_false_positive_rate"], 0.5)
    assert result["sensitivity_low"] < result["weighted_false_positive_rate"]
    assert result["sensitivity_high"] > result["weighted_false_positive_rate"]
    large = by_keyword[by_keyword["audit_keyword"] == "large"].iloc[0]
    assert large["reviewed_rows"] == 3
    assert large["estimate_rows"] == 2
    assert large["ambiguous_rows"] == 1


def test_review_summary_and_patterns_include_required_sections():
    review_df = pd.DataFrame(
        [
            {
                "audit_keyword": "non-control",
                "stratum_size": 10,
                "review_label": "false_positive_valid_position",
                "issuer_name": "Non-Controlled Investments Example LLC",
                "instrument_description": "First Lien Term Loan",
                "bdc_investment_identifier": "Non-Controlled Investments Example LLC First Lien Term Loan",
                "index_classification": "DIRECT_LENDING",
            },
            {
                "audit_keyword": "cash and cash equivalents",
                "stratum_size": 2,
                "review_label": "non_private_or_cash_scope_issue",
                "issuer_name": "JV Cash and Cash Equivalents",
                "instrument_description": "",
                "bdc_investment_identifier": "JV Cash and Cash Equivalents",
                "index_classification": "CASH",
            },
            {
                "audit_keyword": "total investments",
                "stratum_size": 1,
                "review_label": "confirmed_aggregate_leak",
                "fair_value": 100.0,
                "cik": "0000000100",
                "entity_name": "Test BDC",
                "report_date": "2024-03-31",
            },
        ]
    )

    patterns = recurring_false_positive_patterns(review_df)
    summary = render_review_summary(review_df)

    assert "hierarchy/affiliation wording" in patterns["pattern"].to_string()
    assert "cash, money-market" in patterns["pattern"].to_string()
    assert "Weighted false-positive rate" in summary
    assert "Top CIK-quarter confirmed-leak fair value" in summary


def test_build_audit_frame_uses_validate_holdings_keywords_and_cached_evidence(tmp_path):
    holdings = pd.DataFrame(
        [
            {
                "source": "bdc",
                "cik": "100",
                "entity_name": "Test BDC",
                "accession_number": "000100-24-000001",
                "filing_date": "2024-05-01",
                "report_date": "2024-03-31",
                "issuer_name": "Non-Control Investments",
                "instrument_description": "First Lien Term Loan",
                "fair_value": 1000.0,
                "cost": 900.0,
                "pct_of_net_assets": "",
                "shares_held": None,
                "principal_amount": None,
                "asset_category": "LOAN",
                "issuer_category": "CORPORATE",
                "index_classification": "DIRECT_LENDING",
                "exposure_type": "",
                "asset_class": "",
                "interest_rate": 8.5,
                "basis_spread": 3.5,
                "reference_rate_type": "SOFR",
                "coupon_type": "Floating",
                "pik_rate": None,
                "maturity_date": "",
                "bdc_investment_identifier": "Non-Control Investments - First Lien",
                "bdc_form_type": "10-Q",
                "bdc_dimensions_raw": "dim",
            },
            {
                "source": "nport",
                "cik": "200",
                "entity_name": "Fund",
                "accession_number": "000200-24-000001",
                "filing_date": "2024-05-01",
                "report_date": "2024-03-31",
                "issuer_name": "Total Investments",
                "instrument_description": "",
                "fair_value": 1000.0,
                "cost": 900.0,
                "pct_of_net_assets": "",
                "shares_held": None,
                "principal_amount": None,
                "asset_category": "",
                "issuer_category": "",
                "index_classification": "CASH",
                "exposure_type": "",
                "asset_class": "",
                "interest_rate": None,
                "basis_spread": None,
                "reference_rate_type": "",
                "coupon_type": "",
                "pik_rate": None,
                "maturity_date": "",
                "bdc_investment_identifier": "",
                "bdc_form_type": "",
                "bdc_dimensions_raw": "",
            },
        ]
    )
    recon = pd.DataFrame(
        [
            {
                "status": "matched",
                "match_tier": "exact",
                "issue_severity": "",
                "residual_class": "",
                "blocking_issue": False,
                "calibrated_status": "matched",
                "cik": "0000000100",
                "entity_name": "Test BDC",
                "report_date": "2024-03-31",
                "period": "2024-03-31",
                "accession_number": "000100-24-000001",
                "form_type": "10-Q",
                "filing_date": "2024-05-01",
                "context_id": "ctx1",
                "source_row_id": 1,
                "output_row_id": 1,
                "raw_investment_identifier": "Non-Control Investments - First Lien",
                "normalized_investment_identifier": "Non-Control Investments - First Lien",
                "dimensions_raw": "dim",
                "concept_names": "InvestmentOwnedAtFairValue",
                "source_fair_value": 1000.0,
                "output_fair_value": 1000.0,
                "source_cost": 900.0,
                "output_cost": 900.0,
                "source_principal_amount": None,
                "output_principal_amount": None,
                "source_shares_held": None,
                "output_shares_held": None,
                "source_interest_rate": 8.5,
                "output_interest_rate": 8.5,
                "source_basis_spread": 3.5,
                "output_basis_spread": 3.5,
                "source_pik_rate": None,
                "output_pik_rate": None,
                "mismatched_fields": "",
                "issuer_name": "Non-Control Investments",
                "instrument_description": "First Lien Term Loan",
                "index_classification": "DIRECT_LENDING",
                "asset_category": "LOAN",
                "issuer_category": "CORPORATE",
                "evidence": "exact identifier and FV match",
            }
        ]
    )
    holdings_path = tmp_path / "holdings.csv"
    recon_path = tmp_path / "source_reconciliation_detail.csv"
    holdings.to_csv(holdings_path, index=False)
    recon.to_csv(recon_path, index=False)

    result = build_audit_frame(holdings_path, recon_path)

    assert len(result) == 1
    row = result.iloc[0]
    assert row["audit_keyword"] == "non-control"
    assert row["source_reconciliation_status"] == "matched"
    assert row["source_context_id"] == "ctx1"
