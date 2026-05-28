"""Tests for pipeline.validate_holdings module.

Covers:
- spot_check_top_ciks: correct columns, top N, stratified sample
- summarize_classification_by_cik: per-CIK summary, anomaly flagging
- audit_aggregate_leaks: keyword detection, outlier detection, N-PORT skip
- check_cross_source_overlap: zero overlap, overlap detected, duplicate detection
- check_coverage: no_holdings, single_period, ok flags, total assets ratio
- validate_holdings: full orchestrator integration
"""

from unittest.mock import patch

import pandas as pd
import pytest

from pipeline.validate_holdings import (
    audit_aggregate_leaks,
    check_coverage,
    check_cross_source_overlap,
    check_gav_reconciliation,
    check_income_yield_consistency,
    check_pct_of_net_assets_sum,
    check_position_count_stability,
    spot_check_top_ciks,
    summarize_classification_by_cik,
    validate_holdings,
)
from pipeline.position_purity import build_position_purity_diagnostics
from pipeline.source_reconciliation import (
    INTENTIONAL_SOURCE_STATUSES,
    RESIDUAL_CLASSIFICATION_COLUMNS,
    _extract_single_xbrl_source_file,
    build_source_only_blocker_clusters,
    build_source_only_blocker_detail,
    build_source_only_blocker_markdown,
    build_source_reconciliation_residual_classification,
    build_source_reconciliation_residual_classification_markdown,
    build_source_reconciliation_metrics,
    reconcile_bdc_source_to_holdings,
)


@pytest.fixture(autouse=True)
def _redirect_validate_holdings_outputs(monkeypatch, tmp_path):
    output_files = {
        "HOLDINGS_VALIDATION_REPORT_FILE": "holdings_validation_report.csv",
        "HOLDINGS_SPOT_CHECK_FILE": "holdings_spot_check.csv",
        "HOLDINGS_COVERAGE_FILE": "holdings_coverage.csv",
        "HOLDINGS_CROSS_SOURCE_FILE": "holdings_cross_source.csv",
        "HOLDINGS_TOTAL_ASSETS_FILE": "holdings_total_assets.csv",
        "CLASSIFICATION_VALIDATION_FILE": "classification_validation.csv",
        "HOLDINGS_GAV_RECONCILIATION_FILE": "holdings_gav_reconciliation.csv",
        "HOLDINGS_PCT_SUM_FILE": "holdings_pct_sum.csv",
        "HOLDINGS_COUNT_STABILITY_FILE": "holdings_count_stability.csv",
        "HOLDINGS_INCOME_YIELD_FILE": "holdings_income_yield.csv",
        "SOURCE_RECONCILIATION_DETAIL_FILE": "source_reconciliation_detail.csv",
        "SOURCE_RECONCILIATION_METRICS_FILE": "source_reconciliation_metrics.csv",
        "SOURCE_RECONCILIATION_CALIBRATION_REVIEW_FILE": "source_reconciliation_calibration_review.csv",
        "SOURCE_RECONCILIATION_RESIDUAL_CLASSIFICATION_FILE": "source_reconciliation_residual_classification.csv",
        "SOURCE_RECONCILIATION_RESIDUAL_CLASSIFICATION_MD_FILE": "source_reconciliation_residual_classification.md",
        "SOURCE_RECONCILIATION_SOURCE_ONLY_DETAIL_FILE": "source_reconciliation_source_only_detail.csv",
        "SOURCE_RECONCILIATION_SOURCE_ONLY_CLUSTERS_FILE": "source_reconciliation_source_only_clusters.csv",
        "SOURCE_RECONCILIATION_SOURCE_ONLY_CLASSIFICATION_MD_FILE": "source_reconciliation_source_only_classification.md",
        "POSITION_PURITY_DIAGNOSTICS_FILE": "position_purity_diagnostics.csv",
        "POSITION_PURITY_METRICS_FILE": "position_purity_metrics.csv",
        "FUND_STRATEGY_REFERENCE_FILE": "fund_strategy_reference.csv",
        "FUND_STRATEGY_HOLDINGS_MIX_FILE": "fund_strategy_holdings_mix.csv",
        "FUND_STRATEGY_VALIDATION_FILE": "fund_strategy_validation.csv",
        "FUND_STRATEGY_REVIEW_QUEUE_FILE": "fund_strategy_review_queue.csv",
        "FUND_STRATEGY_CORRECTION_CANDIDATES_FILE": "fund_strategy_correction_candidates.csv",
        "ROW_VALIDATION_ISSUES_FILE": "row_validation_issues.csv",
        "VALIDATE_ALL_RESIDUAL_SUMMARY_FILE": "validate_all_residual_summary.csv",
        "COLUMN_QUALITY_METRICS_FILE": "column_quality_metrics.csv",
        "DATA_QUALITY_METRICS_FILE": "data_quality_metrics.csv",
        "FEE_UPLIFT_FILE": "fee_uplift.csv",
    }
    for name, filename in output_files.items():
        monkeypatch.setattr(f"pipeline.validate_holdings.{name}", tmp_path / filename)


def _make_unified_df(rows):
    """Helper to create a minimal unified DataFrame."""
    from pipeline.unified_holdings import UNIFIED_COLUMNS

    data = []
    for row in rows:
        full_row = {c: "" for c in UNIFIED_COLUMNS}
        full_row.update(row)
        data.append(full_row)
    return pd.DataFrame(data)


def _make_basic_holdings(n_bdc=10, n_nport=5):
    """Build a small unified DataFrame with known structure."""
    rows = []
    for i in range(n_bdc):
        rows.append({
            "source": "bdc",
            "cik": str(100 + i % 3),  # 3 CIKs
            "entity_name": f"BDC {100 + i % 3}",
            "issuer_name": f"Company {i}",
            "instrument_description": "First Lien Term Loan",
            "fair_value": str(1_000_000 + i * 100_000),
            "interest_rate": "8.5",
            "basis_spread": "3.5",
            "asset_category": "LOAN",
            "issuer_category": "CORPORATE",
            "index_classification": "DIRECT_LENDING",
            "bdc_investment_identifier": f"Company {i} - First Lien Term Loan",
            "report_date": "2024-03-31" if i < 5 else "2024-06-30",
        })
    for i in range(n_nport):
        rows.append({
            "source": "nport",
            "cik": str(200 + i % 2),  # 2 CIKs
            "entity_name": f"Fund {200 + i % 2}",
            "issuer_name": f"Borrower {i}",
            "instrument_description": "Senior Secured Loan",
            "fair_value": str(500_000 + i * 50_000),
            "nport_asset_cat": "LON",
            "nport_issuer_type": "CORP",
            "asset_category": "LOAN",
            "issuer_category": "CORPORATE",
            "index_classification": "DIRECT_LENDING",
            "report_date": "2024-06-30",
        })
    return _make_unified_df(rows)


def test_column_validation_uses_principal_amount_usd_for_par_ratio():
    from pipeline.column_validation import validate_column_contracts

    df = _make_unified_df([{
        "source": "bdc",
        "cik": "0000000100",
        "entity_name": "Test BDC",
        "issuer_name": "Acme Corp",
        "instrument_description": "First Lien Term Loan",
        "report_date": "2024-03-31",
        "accession_number": "acc",
        "fair_value": "900",
        "principal_amount": "15000",
        "principal_amount_currency": "CAD",
        "principal_amount_usd": "1000",
        "principal_fx_status": "reference_fx",
        "index_classification": "DIRECT_LENDING",
        "exposure_type": "DIRECT",
        "asset_class": "PRIVATE_CREDIT",
        "asset_category": "LOAN",
        "issuer_category": "CORPORATE",
    }])

    issues, _ = validate_column_contracts(df)
    assert "X06" not in set(issues["rule_id"])


def test_column_validation_flags_fx_residuals():
    from pipeline.column_validation import validate_column_contracts

    df = _make_unified_df([
        {
            "source": "bdc",
            "cik": "0000000100",
            "entity_name": "Test BDC",
            "issuer_name": "Acme Corp",
            "instrument_description": "First Lien Term Loan",
            "report_date": "2024-03-31",
            "accession_number": "acc",
            "fair_value": "900",
            "cost": "850",
            "fair_value_currency": "EUR",
            "cost_currency": "CAD",
            "principal_amount": "1000",
            "principal_amount_currency": "EUR",
            "principal_amount_usd": "",
            "principal_fx_status": "missing_reference_fx",
            "index_classification": "DIRECT_LENDING",
            "exposure_type": "DIRECT",
            "asset_class": "PRIVATE_CREDIT",
            "asset_category": "LOAN",
            "issuer_category": "CORPORATE",
        },
        {
            "source": "nport",
            "cik": "0000000200",
            "entity_name": "Test Fund",
            "issuer_name": "Beta Corp",
            "instrument_description": "Term Loan",
            "report_date": "2024-03-31",
            "fair_value": "900",
            "principal_amount": "1000",
            "principal_amount_currency": "CAD",
            "principal_amount_usd": "",
            "principal_fx_status": "invalid_nport_exchange_rate",
            "index_classification": "DIRECT_LENDING",
            "exposure_type": "DIRECT",
            "asset_class": "PRIVATE_CREDIT",
            "asset_category": "LOAN",
            "issuer_category": "CORPORATE",
        },
    ])

    issues, _ = validate_column_contracts(df)
    assert {"FX01", "FX02", "FX03", "FX04"}.issubset(set(issues["rule_id"]))


def _make_bdc_source(rows):
    defaults = {
        "cik": "100",
        "entity_name": "Test BDC",
        "report_date": "2024-03-31",
        "period": "2024-03-31",
        "accession_number": "000100-24-000001",
        "form_type": "10-Q",
        "filing_date": "2024-05-01",
        "context_id": "ctx1",
        "investment_identifier": "Acme Corp - First Lien Term Loan",
        "dimensions_raw": "investmentidentifier=Acme Corp - First Lien Term Loan",
        "concept_names": "InvestmentOwnedAtFairValue",
        "fair_value": "1000000",
        "cost": "990000",
        "principal_amount": "1000000",
        "shares_held": "",
        "interest_rate": "8.5",
        "basis_spread": "3.5",
        "pik_rate": "",
    }
    return pd.DataFrame([{**defaults, **row} for row in rows])


def _make_bdc_output(rows):
    prepared = []
    for row in rows:
        prepared.append({
            "source": "bdc",
            "cik": "0000000100",
            "entity_name": "Test BDC",
            "report_date": "2024-03-31",
            "accession_number": "000100-24-000001",
            "filing_date": "2024-05-01",
            "bdc_form_type": "10-Q",
            "issuer_name": "Acme Corp",
            "instrument_description": "First Lien Term Loan",
            "fair_value": "1000000",
            "cost": "990000",
            "principal_amount": "1000000",
            "shares_held": "",
            "interest_rate": "8.5",
            "basis_spread": "3.5",
            "pik_rate": "",
            "asset_category": "LOAN",
            "issuer_category": "CORPORATE",
            "index_classification": "DIRECT_LENDING",
            "bdc_investment_identifier": "Acme Corp - First Lien Term Loan",
            "bdc_dimensions_raw": "investmentidentifier=Acme Corp - First Lien Term Loan",
            **row,
        })
    return _make_unified_df(prepared)


def _make_source_only_detail(identifiers):
    rows = []
    for idx, identifier in enumerate(identifiers):
        row = {c: "" for c in RESIDUAL_CLASSIFICATION_COLUMNS}
        row.update({
            "status": "missing_from_pipeline",
            "blocking_issue": True,
            "cik": "0000000100",
            "entity_name": "Test BDC",
            "report_date": "2024-03-31",
            "period": "2024-03-31",
            "accession_number": "acc-001",
            "source_row_id": str(idx),
            "raw_investment_identifier": identifier,
            "source_fair_value": "1000000",
            "evidence": "eligible current-period source row has no pipeline output row",
        })
        rows.append(row)
    from pipeline.source_reconciliation import DETAIL_COLUMNS
    return pd.DataFrame([{col: row.get(col, "") for col in DETAIL_COLUMNS} for row in rows])


class TestSourceOnlyBlockerClassification:
    def _classified(self, identifier):
        return build_source_only_blocker_detail(
            _make_source_only_detail([identifier])
        ).iloc[0]

    def test_total_affiliates_documented_nonblocking(self):
        row = self._classified("Total Affiliates")
        assert row["mechanism"] == "documented_source_total_header"
        assert row["is_blocking"] == False

    def test_standalone_united_states_documented_nonblocking(self):
        row = self._classified("United States")
        assert row["mechanism"] == "documented_source_country_industry_header"
        assert row["is_blocking"] == False

    @pytest.mark.parametrize("identifier", [
        "Total Investments - 215.2%",
        "Total Investments - 208.7%",
        "Equipment Financing - 24.1% | Total Equipment Financing",
    ])
    def test_slr_total_rows_documented_nonblocking(self, identifier):
        row = self._classified(identifier)
        assert row["mechanism"] in {
            "documented_source_total_header",
            "documented_source_pct_total_header",
        }
        assert row["is_blocking"] == False

    def test_position_like_rate_row_remains_blocking(self):
        row = self._classified(
            "Equipment Financing - 24.1% | Air Methods Corporation | Airlines | "
            "First Lien Term Loan | SOFR + 6.00% | 12/31/2028"
        )
        assert row["is_blocking"] == True
        assert row["mechanism"] in {
            "blocking_source_pct_leaf_parser_mismatch",
            "blocking_source_position_like_parser_mismatch",
        }


# ---------------------------------------------------------------------------
# BDC source reconciliation
# ---------------------------------------------------------------------------

class TestBdcSourceReconciliation:
    def test_source_extraction_applies_mixed_decimals_normalization(self, tmp_path):
        contexts = []
        facts = []
        for i, value, decimals in [
            (1, "1000000", "-3"),
            (2, "1100000", "-3"),
            (3, "1200000", "-3"),
            (4, "1300000", "-3"),
            (5, "1400000000", "-6"),
        ]:
            contexts.append(f"""
                <xbrli:context id="ctx{i}">
                    <xbrli:entity>
                        <xbrli:identifier scheme="http://www.sec.gov/CIK">100</xbrli:identifier>
                        <xbrli:segment>
                            <xbrldi:typedMember dimension="test:InvestmentIdentifierAxis">
                                <test:InvestmentIdentifierDomain>Company {i} - Term Loan</test:InvestmentIdentifierDomain>
                            </xbrldi:typedMember>
                        </xbrli:segment>
                    </xbrli:entity>
                    <xbrli:period><xbrli:instant>2024-03-31</xbrli:instant></xbrli:period>
                </xbrli:context>
            """)
            facts.append(
                f'<test:InvestmentOwnedAtFairValue contextRef="ctx{i}" '
                f'unitRef="usd" decimals="{decimals}">{value}</test:InvestmentOwnedAtFairValue>'
            )
        xml = (
            '<xbrl xmlns="http://www.xbrl.org/2003/instance" '
            'xmlns:xbrli="http://www.xbrl.org/2003/instance" '
            'xmlns:xbrldi="http://xbrl.org/2006/xbrldi" '
            'xmlns:test="http://example.com/test">'
            + "".join(contexts)
            + "".join(facts)
            + "</xbrl>"
        )
        path = tmp_path / "mixed_decimals.xml"
        path.write_text(xml, encoding="utf-8")

        rows = _extract_single_xbrl_source_file(
            path,
            {
                "cik": "100",
                "entity_name": "Test BDC",
                "accession_number": "acc",
                "form_type": "10-Q",
                "filing_date": "2024-05-01",
                "report_date": "2024-03-31",
            },
        )

        by_identifier = {row["investment_identifier"]: row for row in rows}
        assert by_identifier["Company 5 - Term Loan"]["fair_value"] == 1400000.0

    def test_exact_source_to_output_match(self):
        detail, metrics = reconcile_bdc_source_to_holdings(
            _make_bdc_source([{}]),
            _make_bdc_output([{}]),
        )
        assert set(detail["status"]) == {"matched"}
        assert detail.iloc[0]["match_tier"] == "exact_dimensions_raw"
        assert detail.iloc[0]["blocking_issue"] == False
        assert metrics.iloc[0]["matched_rows"] == 1
        assert metrics.iloc[0]["strong_issue_count"] == 0
        assert metrics.iloc[0]["blocking_issue_count"] == 0

    def test_exact_override_exclude_is_documented_with_output_rows(self, monkeypatch, tmp_path):
        import json
        overrides_path = tmp_path / "bdc_aggregate_row_overrides.json"
        overrides_path.write_text(json.dumps({"overrides": [{
            "cik": "0001287032",
            "report_date": "2024-03-31",
            "accession_number": "0001287032-24-000152",
            "match_text": "InterDent, Inc.",
            "match_mode": "exact",
            "action": "exclude",
            "reason": "test audited parent row",
            "evidence": "unit test",
            "review_id": "test",
            "updated_at": "2026-05-24",
        }]}), encoding="utf-8")
        monkeypatch.setattr(
            "pipeline.bdc_aggregate_overrides.BDC_AGGREGATE_ROW_OVERRIDES_FILE",
            overrides_path,
        )
        source = _make_bdc_source([{
            "cik": "1287032",
            "entity_name": "Prospect Capital Corporation",
            "report_date": "2024-03-31",
            "period": "2024-03-31",
            "accession_number": "0001287032-24-000152",
            "investment_identifier": "InterDent, Inc.",
            "dimensions_raw": "investmentidentifier=InterDent, Inc.",
            "fair_value": "5000000",
        }])
        output = _make_bdc_output([{
            "cik": "0001287032",
            "entity_name": "Prospect Capital Corporation",
            "report_date": "2024-03-31",
            "accession_number": "0001287032-24-000152",
            "issuer_name": "InterDent, Inc.",
            "bdc_investment_identifier": "InterDent, Inc. - First Lien Term Loan",
            "bdc_dimensions_raw": "investmentidentifier=InterDent, Inc. - First Lien Term Loan",
            "fair_value": "1000000",
        }])

        detail, metrics = reconcile_bdc_source_to_holdings(source, output)
        source_row = detail[detail["source_row_id"] != ""].iloc[0]
        assert source_row["status"] == "excluded_aggregate_candidate"
        assert source_row["blocking_issue"] == False
        assert "audited exact override" in source_row["evidence"]

    def test_affiliation_prefix_source_matches_staging_normalized_output(self):
        source = _make_bdc_source([{
            "investment_identifier": (
                "Investments in Non-Controlled, Non-Affiliated Portfolio Companies - "
                "Acme Corp - First Lien Term Loan"
            ),
            "dimensions_raw": "source_dimensions=full_prefix",
        }])
        output = _make_bdc_output([{
            "bdc_investment_identifier": "Acme Corp - First Lien Term Loan",
            "bdc_dimensions_raw": "pipeline_dimensions=stripped",
        }])
        detail, metrics = reconcile_bdc_source_to_holdings(source, output)
        assert set(detail["status"]) == {"matched"}
        assert detail.iloc[0]["match_tier"] == "staging_normalized_identifier"
        assert metrics.iloc[0]["missing_from_pipeline_rows"] == 0
        assert metrics.iloc[0]["extra_in_pipeline_rows"] == 0
        assert metrics.iloc[0]["blocking_issue_count"] == 0

    def test_numeric_identity_matches_transformed_identifiers_one_to_one(self):
        source = _make_bdc_source([{
            "investment_identifier": "Acme Corp 2027 Secured Note Source Label",
            "dimensions_raw": "source_dimensions=opaque_identifier_123",
            "fair_value": "1000000",
            "cost": "990000",
        }])
        output = _make_bdc_output([{
            "bdc_investment_identifier": "Acme Corp / First Lien TL-B Pipeline Label",
            "bdc_dimensions_raw": "pipeline_dimensions=parsed_alias_456",
            "fair_value": "1000000",
            "cost": "990000",
        }])

        detail, metrics = reconcile_bdc_source_to_holdings(source, output)

        assert set(detail["status"]) == {"matched"}
        row = detail.iloc[0]
        assert row["match_tier"] == "reconciled_numeric_identity"
        assert row["blocking_issue"] == False
        assert "numeric identity" in row["evidence"]
        assert metrics.iloc[0]["matched_rows"] == 1
        assert metrics.iloc[0]["blocking_issue_count"] == 0

    def test_numeric_identity_requires_matching_cost(self):
        """Numeric identity tier requires cost match, but fv_only tier can catch it."""
        source = _make_bdc_source([{
            "investment_identifier": "Acme Corp Source Alias",
            "dimensions_raw": "source_dimensions=opaque_identifier_123",
            "fair_value": "1000000",
            "cost": "990000",
        }])
        output = _make_bdc_output([{
            "bdc_investment_identifier": "Acme Corp Pipeline Alias",
            "bdc_dimensions_raw": "pipeline_dimensions=parsed_alias_456",
            "fair_value": "1000000",
            "cost": "980000",
        }])

        detail, metrics = reconcile_bdc_source_to_holdings(source, output)

        # Numeric identity tier still requires cost -- not used here
        assert "reconciled_numeric_identity" not in set(detail["match_tier"])
        # But a lower tier matches on FV + name (strict 1:1)
        source_row = detail[detail["source_row_id"] != ""]
        assert len(source_row) == 1
        assert source_row.iloc[0]["match_tier"] in (
            "reconciled_issuer_name_extraction",
            "reconciled_fv_only_identity",
            "reconciled_partial_name_fv",
        )
        # Cost mismatch surfaces as diagnostic
        assert source_row.iloc[0]["status"] == "diagnostic_field_mismatch"
        assert source_row.iloc[0]["blocking_issue"] == False

    def test_numeric_identity_two_candidate_outputs_remains_blocking(self):
        source = _make_bdc_source([{
            "investment_identifier": "Zephyr Opaque Source 2027",
            "dimensions_raw": "source_dimensions=opaque_identifier_123",
            "fair_value": "1000000",
            "cost": "990000",
        }])
        output = _make_bdc_output([
            {
                "bdc_investment_identifier": "Vortex Pipeline Alias A",
                "bdc_dimensions_raw": "pipeline_dimensions=parsed_alias_a",
                "issuer_name": "Vortex Capital",
                "fair_value": "1000000",
                "cost": "990000",
            },
            {
                "bdc_investment_identifier": "Nebula Pipeline Alias B",
                "bdc_dimensions_raw": "pipeline_dimensions=parsed_alias_b",
                "issuer_name": "Nebula Holdings",
                "fair_value": "1000000",
                "cost": "990000",
            },
        ])

        detail, metrics = reconcile_bdc_source_to_holdings(source, output)
        source_row = detail[detail["status"] == "missing_from_pipeline"].iloc[0]

        assert "reconciled_numeric_identity" not in set(detail["match_tier"])
        assert "blocking numeric identity candidate" in source_row["evidence"]
        # 1 source missing + 2 outputs extra = 3 blocking
        assert metrics.iloc[0]["blocking_issue_count"] == 3

    def test_numeric_identity_two_candidate_sources_remains_blocking(self):
        source = _make_bdc_source([
            {
                "context_id": "ctx_a",
                "investment_identifier": "Zephyr Widgets Inc. Source Opaque A",
                "dimensions_raw": "source_dimensions=opaque_identifier_a",
                "fair_value": "1000000",
                "cost": "990000",
            },
            {
                "context_id": "ctx_b",
                "investment_identifier": "Quasar Dynamics LLC Source Opaque B",
                "dimensions_raw": "source_dimensions=opaque_identifier_b",
                "fair_value": "1000000",
                "cost": "990000",
            },
        ])
        output = _make_bdc_output([{
            "bdc_investment_identifier": "Nebula Holdings Pipeline Alias",
            "bdc_dimensions_raw": "pipeline_dimensions=parsed_alias",
            "issuer_name": "Nebula Holdings",
            "fair_value": "1000000",
            "cost": "990000",
        }])

        detail, metrics = reconcile_bdc_source_to_holdings(source, output)
        source_rows = detail[detail["status"] == "missing_from_pipeline"]

        assert "reconciled_numeric_identity" not in set(detail["match_tier"])
        assert len(source_rows) == 2
        assert all(source_rows["evidence"].str.contains("blocking numeric identity candidate"))
        assert metrics.iloc[0]["blocking_issue_count"] == 3

    def test_numeric_identity_does_not_cross_accession_cik_or_report_date(self):
        source = _make_bdc_source([{
            "investment_identifier": "Acme Corp Source Alias",
            "dimensions_raw": "source_dimensions=opaque_identifier_123",
            "accession_number": "acc-source",
            "fair_value": "1000000",
            "cost": "990000",
        }])
        output = _make_bdc_output([{
            "bdc_investment_identifier": "Acme Corp Pipeline Alias",
            "bdc_dimensions_raw": "pipeline_dimensions=parsed_alias_456",
            "accession_number": "acc-output",
            "fair_value": "1000000",
            "cost": "990000",
        }])

        detail, metrics = reconcile_bdc_source_to_holdings(source, output)

        assert "reconciled_numeric_identity" not in set(detail["match_tier"])
        assert {"missing_from_pipeline", "extra_in_pipeline"} == set(detail["status"])
        assert metrics.iloc[0]["blocking_issue_count"] == 2

    def test_numeric_identity_does_not_relabel_existing_identifier_match(self):
        source = _make_bdc_source([{
            "investment_identifier": "Acme Corp - First Lien Term Loan",
            "dimensions_raw": "source_dimensions=alias",
            "fair_value": "1000000",
            "cost": "990000",
        }])
        output = _make_bdc_output([{
            "bdc_investment_identifier": "Acme Corp - First Lien Term Loan",
            "bdc_dimensions_raw": "pipeline_dimensions=alias",
            "fair_value": "1000000",
            "cost": "990000",
        }])

        detail, _ = reconcile_bdc_source_to_holdings(source, output)

        assert set(detail["status"]) == {"matched"}
        assert detail.iloc[0]["match_tier"] == "exact_identifier"

    def test_ambiguous_numeric_identity_candidates_have_separate_mechanism(self):
        source = _make_bdc_source([{
            "investment_identifier": "Zephyr Opaque Source 2027 First Lien Note",
            "dimensions_raw": "source_dimensions=opaque_identifier_123",
            "fair_value": "1000000",
            "cost": "990000",
        }])
        output = _make_bdc_output([
            {
                "bdc_investment_identifier": "Vortex Capital Pipeline Alias A",
                "bdc_dimensions_raw": "pipeline_dimensions=parsed_alias_a",
                "issuer_name": "Vortex Capital",
                "fair_value": "1000000",
                "cost": "990000",
            },
            {
                "bdc_investment_identifier": "Nebula Holdings Pipeline Alias B",
                "bdc_dimensions_raw": "pipeline_dimensions=parsed_alias_b",
                "issuer_name": "Nebula Holdings",
                "fair_value": "1000000",
                "cost": "990000",
            },
        ])

        detail, _ = reconcile_bdc_source_to_holdings(source, output)
        classified = build_source_reconciliation_residual_classification(detail)

        assert "blocking_numeric_multi_output_collision" in set(classified["mechanism"])
        by_mechanism = dict(zip(classified["mechanism"], classified["issue_count"]))
        assert by_mechanism["blocking_numeric_multi_output_collision"] == 1

    def test_secondary_field_mismatch_is_diagnostic_not_blocking(self):
        source = _make_bdc_source([{
            "investment_identifier": "Capital Southwest Co - Equity",
            "dimensions_raw": "investmentidentifier=Capital Southwest Co - Equity",
            "fair_value": "1000000",
            "principal_amount": "5000000",
        }])
        output = _make_bdc_output([{
            "bdc_investment_identifier": "Capital Southwest Co - Equity",
            "bdc_dimensions_raw": "investmentidentifier=Capital Southwest Co - Equity",
            "issuer_name": "Capital Southwest Co",
            "instrument_description": "Equity",
            "fair_value": "1000000",
            "principal_amount": "",
            "asset_category": "EQUITY_COMMON",
            "issuer_category": "CORPORATE",
            "index_classification": "COMMON_EQUITY",
        }])
        detail, metrics = reconcile_bdc_source_to_holdings(source, output)
        row = detail.iloc[0]
        assert row["status"] == "diagnostic_field_mismatch"
        assert row["calibrated_status"] == "diagnostic_field_mismatch"
        assert row["blocking_issue"] == False
        assert row["issue_severity"] == "WARN"
        assert metrics.iloc[0]["blocking_issue_count"] == 0
        assert metrics.iloc[0]["diagnostic_issue_count"] == 1
        assert metrics.iloc[0]["reconciliation_status"] == "RECONCILED"

    def test_prefixed_and_stripped_source_duplicates_collapse_before_matching(self):
        source = _make_bdc_source([
            {
                "context_id": "ctx_prefixed",
                "investment_identifier": (
                    "Investments in Non-Controlled, Non-Affiliated Portfolio Companies - "
                    "Acme Corp - First Lien Term Loan"
                ),
                "dimensions_raw": "source_dimensions=full_prefix",
            },
            {
                "context_id": "ctx_stripped",
                "investment_identifier": "Acme Corp - First Lien Term Loan",
                "dimensions_raw": "source_dimensions=stripped",
            },
        ])
        output = _make_bdc_output([{
            "bdc_investment_identifier": "Acme Corp - First Lien Term Loan",
            "bdc_dimensions_raw": "pipeline_dimensions=stripped",
        }])

        detail, metrics = reconcile_bdc_source_to_holdings(source, output)
        assert set(detail["status"]) == {"matched", "collapsed_duplicate_dimension_path"}
        assert metrics.iloc[0]["matched_rows"] == 1
        assert metrics.iloc[0]["missing_from_pipeline_rows"] == 0
        assert metrics.iloc[0]["extra_in_pipeline_rows"] == 0
        assert metrics.iloc[0]["blocking_issue_count"] == 0
        duplicate = detail[detail["status"] == "collapsed_duplicate_dimension_path"].iloc[0]
        assert "canonical_source_row_id=" in duplicate["evidence"]

    def test_duplicate_dimension_paths_with_different_cost_are_non_blocking(self):
        source = _make_bdc_source([
            {
                "context_id": "ctx_a",
                "dimensions_raw": "investmentidentifier=Acme Corp - First Lien Term Loan|affiliation=NonControl",
                "cost": "990000",
            },
            {
                "context_id": "ctx_b",
                "dimensions_raw": "investmentidentifier=Acme Corp - First Lien Term Loan|industry=Software",
                "cost": "950000",
            },
        ])

        detail, metrics = reconcile_bdc_source_to_holdings(source, _make_bdc_output([{}]))
        assert set(detail["status"]) == {"matched", "collapsed_duplicate_dimension_path"}
        assert metrics.iloc[0]["collapsed_duplicate_dimension_path_rows"] == 1
        assert metrics.iloc[0]["blocking_issue_count"] == 0

    def test_same_borrower_distinct_tranches_are_not_collapsed(self):
        source = _make_bdc_source([
            {
                "context_id": "ctx_first",
                "investment_identifier": "Acme Corp - First Lien Term Loan",
                "dimensions_raw": "investmentidentifier=Acme Corp - First Lien Term Loan",
                "fair_value": "1000000",
            },
            {
                "context_id": "ctx_second",
                "investment_identifier": "Acme Corp - Second Lien Term Loan",
                "dimensions_raw": "investmentidentifier=Acme Corp - Second Lien Term Loan",
                "fair_value": "1000000",
            },
        ])
        output = _make_bdc_output([
            {
                "bdc_investment_identifier": "Acme Corp - First Lien Term Loan",
                "bdc_dimensions_raw": "investmentidentifier=Acme Corp - First Lien Term Loan",
                "fair_value": "1000000",
            },
            {
                "bdc_investment_identifier": "Acme Corp - Second Lien Term Loan",
                "bdc_dimensions_raw": "investmentidentifier=Acme Corp - Second Lien Term Loan",
                "fair_value": "1000000",
                "issuer_name": "Acme Corp",
                "instrument_description": "Second Lien Term Loan",
            },
        ])

        detail, metrics = reconcile_bdc_source_to_holdings(source, output)
        assert set(detail["status"]) == {"matched"}
        assert metrics.iloc[0]["matched_rows"] == 2
        assert metrics.iloc[0]["collapsed_duplicate_dimension_path_rows"] == 0

    def test_missing_source_row_extra_pipeline_row_and_numeric_mismatch(self):
        source = _make_bdc_source([
            {"investment_identifier": "Missing Co LLC - Term Loan", "context_id": "ctx_missing", "fair_value": "750000"},
            {"investment_identifier": "Mismatch Co - Term Loan", "context_id": "ctx_mismatch", "fair_value": "1000000"},
        ])
        output = _make_bdc_output([
            {"bdc_investment_identifier": "Extra Co - Term Loan", "issuer_name": "Extra Co", "fair_value": "500000"},
            {"bdc_investment_identifier": "Mismatch Co - Term Loan", "issuer_name": "Mismatch Co", "fair_value": "1500000"},
        ])
        detail, metrics = reconcile_bdc_source_to_holdings(source, output)
        statuses = set(detail["status"])
        assert {"missing_from_pipeline", "extra_in_pipeline", "value_mismatch"}.issubset(statuses)
        assert metrics.iloc[0]["missing_from_pipeline_rows"] == 1
        assert metrics.iloc[0]["extra_in_pipeline_rows"] == 1
        assert metrics.iloc[0]["value_mismatch_rows"] == 1
        assert metrics.iloc[0]["strong_issue_count"] == 3
        assert metrics.iloc[0]["blocking_issue_count"] == 3

    def test_comparative_period_and_superseded_amendment_are_documented(self):
        source = _make_bdc_source([
            {"investment_identifier": "Prior Co - Term Loan", "period": "2023-12-31", "context_id": "ctx_prior"},
            {"investment_identifier": "Old Amendment Co - Term Loan", "form_type": "10-Q", "filing_date": "2024-04-15", "accession_number": "old", "context_id": "ctx_old"},
            {"investment_identifier": "Current Amendment Co - Term Loan", "form_type": "10-Q/A", "filing_date": "2024-05-15", "accession_number": "new", "context_id": "ctx_new"},
        ])
        detail, metrics = reconcile_bdc_source_to_holdings(source, _make_bdc_output([]))
        assert "excluded_comparative_period" in set(detail["status"])
        assert "superseded_amendment" in set(detail["status"])
        assert metrics.iloc[0]["excluded_comparative_period_rows"] == 1
        assert metrics.iloc[0]["superseded_amendment_rows"] == 1

    def test_aggregate_candidate_and_no_fair_value_are_documented(self):
        source = _make_bdc_source([
            {"investment_identifier": "Total Investments at Fair Value", "context_id": "ctx_total"},
            {"investment_identifier": "No FV Co - Revolver", "fair_value": "", "context_id": "ctx_no_fv"},
        ])
        detail, metrics = reconcile_bdc_source_to_holdings(source, _make_bdc_output([]))
        assert "excluded_aggregate_candidate" in set(detail["status"])
        assert "excluded_no_fair_value" in set(detail["status"])
        assert metrics.iloc[0]["excluded_aggregate_candidate_rows"] == 1
        assert metrics.iloc[0]["excluded_no_fair_value_rows"] == 1

    def test_source_rollup_is_non_blocking_when_fv_ties_children(self):
        source = _make_bdc_source([{
            "investment_identifier": "Total First Lien Debt",
            "context_id": "ctx_total_first_lien",
            "fair_value": "3000000",
        }])
        output = _make_bdc_output([
            {
                "bdc_investment_identifier": "Acme Corp - First Lien",
                "bdc_dimensions_raw": "investmentidentifier=Acme",
                "issuer_name": "Acme Corp",
                "fair_value": "1000000",
            },
            {
                "bdc_investment_identifier": "Beta Corp - First Lien",
                "bdc_dimensions_raw": "investmentidentifier=Beta",
                "issuer_name": "Beta Corp",
                "fair_value": "2000000",
            },
        ])

        detail, metrics = reconcile_bdc_source_to_holdings(source, output)

        assert set(detail["status"]) == {"documented_source_rollup_exact"}
        row = detail.iloc[0]
        assert row["blocking_issue"] == False
        assert "child_output_count=2" in row["evidence"]
        assert metrics.iloc[0]["blocking_issue_count"] == 0
        assert metrics.iloc[0]["documented_source_rollup_exact_rows"] == 1

    def test_source_rollup_remains_blocking_when_fv_tie_fails(self):
        source = _make_bdc_source([{
            "investment_identifier": "Total First Lien Debt",
            "context_id": "ctx_total_first_lien",
            "fair_value": "4000000",
        }])
        output = _make_bdc_output([
            {
                "bdc_investment_identifier": "Acme Corp - First Lien",
                "bdc_dimensions_raw": "investmentidentifier=Acme",
                "issuer_name": "Acme Corp",
                "fair_value": "1000000",
            },
            {
                "bdc_investment_identifier": "Beta Corp - First Lien",
                "bdc_dimensions_raw": "investmentidentifier=Beta",
                "issuer_name": "Beta Corp",
                "fair_value": "2000000",
            },
        ])

        detail, metrics = reconcile_bdc_source_to_holdings(source, output)

        assert "missing_from_pipeline" in set(detail["status"])
        assert "extra_in_pipeline" in set(detail["status"])
        assert metrics.iloc[0]["blocking_issue_count"] == 3

    def test_source_rollup_does_not_consume_matched_parent_with_distinct_children(self):
        source = _make_bdc_source([{
            "investment_identifier": "Cambium Learning Group, Inc.",
            "dimensions_raw": "investmentidentifier=Cambium Learning Group, Inc.",
            "context_id": "ctx_parent",
            "fair_value": "3000000",
            "cost": "2900000",
        }])
        output = _make_bdc_output([
            {
                "bdc_investment_identifier": "Cambium Learning Group, Inc.",
                "bdc_dimensions_raw": "investmentidentifier=Cambium Learning Group, Inc.",
                "issuer_name": "Cambium Learning Group, Inc.",
                "fair_value": "3000000",
                "cost": "2900000",
            },
            {
                "bdc_investment_identifier": "Cambium Learning Group, Inc., Emerald JV LP",
                "bdc_dimensions_raw": "investmentidentifier=Cambium Emerald",
                "issuer_name": "Cambium Learning Group, Inc., Emerald JV LP",
                "fair_value": "1000000",
                "cost": "1000000",
            },
            {
                "bdc_investment_identifier": "Cambium Learning Group, Inc., Second Lien",
                "bdc_dimensions_raw": "investmentidentifier=Cambium Second Lien",
                "issuer_name": "Cambium Learning Group, Inc.",
                "instrument_description": "Second Lien",
                "fair_value": "2000000",
                "cost": "1900000",
            },
        ])

        detail, metrics = reconcile_bdc_source_to_holdings(source, output)

        assert "documented_source_rollup_exact" not in set(detail["status"])
        assert "matched" in set(detail["status"])
        assert int(metrics.iloc[0]["extra_in_pipeline_rows"]) == 2
        assert int(metrics.iloc[0]["blocking_issue_count"]) == 2

    def test_duplicate_dimension_paths_collapse_to_one_output_row(self):
        source = _make_bdc_source([
            {"context_id": "ctx_a", "dimensions_raw": "investmentidentifier=Acme Corp - First Lien Term Loan|affiliation=NonControl"},
            {"context_id": "ctx_b", "dimensions_raw": "investmentidentifier=Acme Corp - First Lien Term Loan|industry=Software"},
        ])
        detail, metrics = reconcile_bdc_source_to_holdings(source, _make_bdc_output([{}]))
        assert "matched" in set(detail["status"])
        assert "collapsed_duplicate_dimension_path" in set(detail["status"])
        assert metrics.iloc[0]["matched_rows"] == 1
        assert metrics.iloc[0]["collapsed_duplicate_dimension_path_rows"] == 1
        assert metrics.iloc[0]["strong_issue_count"] == 0

    def test_self_referential_subtotal_is_non_blocking(self):
        """Source row whose identifier is a prefix of 2+ child source rows is excluded."""
        # Parent FV deliberately != sum of children to avoid source_rollup matching
        source = _make_bdc_source([
            {
                "context_id": "ctx_parent",
                "investment_identifier": "Equity Investments Consumer Services",
                "fair_value": "5000000",
            },
            {
                "context_id": "ctx_child1",
                "investment_identifier": "Equity Investments Consumer Services Acme Corp Inc. Common Stock",
                "fair_value": "1500000",
            },
            {
                "context_id": "ctx_child2",
                "investment_identifier": "Equity Investments Consumer Services Beta LLC Term Loan",
                "fair_value": "2500000",
            },
        ])
        output = _make_bdc_output([
            {
                "bdc_investment_identifier": "Equity Investments Consumer Services Acme Corp Inc. Common Stock",
                "bdc_dimensions_raw": "investmentidentifier=Equity Investments Consumer Services Acme Corp Inc. Common Stock",
                "issuer_name": "Acme Corp Inc.",
                "fair_value": "1500000",
            },
            {
                "bdc_investment_identifier": "Equity Investments Consumer Services Beta LLC Term Loan",
                "bdc_dimensions_raw": "investmentidentifier=Equity Investments Consumer Services Beta LLC Term Loan",
                "issuer_name": "Beta LLC",
                "fair_value": "2500000",
            },
        ])
        detail, metrics = reconcile_bdc_source_to_holdings(source, output)
        statuses = set(detail["status"])
        assert "excluded_self_referential_subtotal" in statuses
        assert metrics.iloc[0]["blocking_issue_count"] == 0

    def test_hierarchy_header_is_non_blocking(self):
        """Source row starting with known category prefix is excluded as hierarchy header."""
        source = _make_bdc_source([
            {
                "context_id": "ctx_header",
                "investment_identifier": "Equity Investments",
                "fair_value": "5000000",
            },
            {
                "context_id": "ctx_real",
                "investment_identifier": "Acme Corp - First Lien Term Loan",
                "fair_value": "1000000",
            },
        ])
        output = _make_bdc_output([{
            "bdc_investment_identifier": "Acme Corp - First Lien Term Loan",
            "bdc_dimensions_raw": "investmentidentifier=Acme Corp - First Lien Term Loan",
            "fair_value": "1000000",
        }])
        detail, metrics = reconcile_bdc_source_to_holdings(source, output)
        statuses = set(detail["status"])
        # "Equity Investments" is caught by aggregate filter, hierarchy header, or bad issuer
        non_blocking = statuses - {"matched"}
        assert all(s in INTENTIONAL_SOURCE_STATUSES for s in non_blocking), \
            f"Expected non-blocking status for header, got {non_blocking}"
        assert metrics.iloc[0]["blocking_issue_count"] == 0

    def test_money_market_fund_is_non_blocking(self):
        """Source row with money market fund keyword is excluded."""
        source = _make_bdc_source([
            {
                "context_id": "ctx_mm",
                "investment_identifier": "Goldman Sachs Financial Square Government Money Market Fund",
                "fair_value": "10000000",
            },
            {
                "context_id": "ctx_real",
                "investment_identifier": "Acme Corp - First Lien Term Loan",
                "fair_value": "1000000",
            },
        ])
        output = _make_bdc_output([{
            "bdc_investment_identifier": "Acme Corp - First Lien Term Loan",
            "bdc_dimensions_raw": "investmentidentifier=Acme Corp - First Lien Term Loan",
            "fair_value": "1000000",
        }])
        detail, metrics = reconcile_bdc_source_to_holdings(source, output)
        statuses = set(detail["status"])
        assert "excluded_money_market_fund" in statuses
        mm_row = detail[detail["status"] == "excluded_money_market_fund"].iloc[0]
        assert mm_row["blocking_issue"] == False
        assert metrics.iloc[0]["blocking_issue_count"] == 0

    def test_bad_issuer_name_is_non_blocking(self):
        """Source row with generic issuer name is excluded."""
        source = _make_bdc_source([
            {
                "context_id": "ctx_bad",
                "investment_identifier": "Investments",
                "fair_value": "50000000",
            },
            {
                "context_id": "ctx_real",
                "investment_identifier": "Acme Corp - First Lien Term Loan",
                "fair_value": "1000000",
            },
        ])
        output = _make_bdc_output([{
            "bdc_investment_identifier": "Acme Corp - First Lien Term Loan",
            "bdc_dimensions_raw": "investmentidentifier=Acme Corp - First Lien Term Loan",
            "fair_value": "1000000",
        }])
        detail, metrics = reconcile_bdc_source_to_holdings(source, output)
        statuses = set(detail["status"])
        assert "excluded_bad_issuer_name" in statuses
        bad_row = detail[detail["status"] == "excluded_bad_issuer_name"].iloc[0]
        assert bad_row["blocking_issue"] == False
        assert metrics.iloc[0]["blocking_issue_count"] == 0

    def test_affiliation_dedup_is_non_blocking(self):
        """Source row that is an affiliation-axis duplicate of a matched row is excluded."""
        source = _make_bdc_source([
            {
                "context_id": "ctx_matched",
                "investment_identifier": "Acme Corp - First Lien Term Loan",
                "dimensions_raw": "investmentidentifier=Acme Corp - First Lien Term Loan",
                "fair_value": "1000000",
            },
            {
                "context_id": "ctx_affil_dup",
                "investment_identifier": "Non-Controlled Acme Corp - First Lien TL",
                "dimensions_raw": "affiliation=Non-Controlled;investmentidentifier=Acme Corp",
                "fair_value": "1000000",
            },
        ])
        output = _make_bdc_output([{
            "bdc_investment_identifier": "Acme Corp - First Lien Term Loan",
            "bdc_dimensions_raw": "investmentidentifier=Acme Corp - First Lien Term Loan",
            "fair_value": "1000000",
        }])
        detail, metrics = reconcile_bdc_source_to_holdings(source, output)
        statuses = set(detail["status"])
        assert "matched" in statuses
        assert "excluded_affiliation_dedup" in statuses
        assert metrics.iloc[0]["blocking_issue_count"] == 0

    def test_issuer_name_extraction_matches_embedded_company_name(self):
        """Source identifier with pipe-separated company name matches output issuer_name."""
        source = _make_bdc_source([{
            "investment_identifier": "Senior Secured Loans | First Lien | Acme Industries Inc. | Technology",
            "dimensions_raw": "source_dimensions=pipe_format",
            "fair_value": "2000000",
            "cost": "1800000",
        }])
        output = _make_bdc_output([{
            "bdc_investment_identifier": "Acme Industries Inc. - First Lien Term Loan",
            "bdc_dimensions_raw": "pipeline_dimensions=parsed",
            "issuer_name": "Acme Industries Inc.",
            "fair_value": "2000000",
            "cost": "1900000",
        }])
        detail, metrics = reconcile_bdc_source_to_holdings(source, output)
        source_row = detail[detail["source_row_id"] != ""].iloc[0]
        # Numeric identity won't match (different cost), so issuer name extraction fires
        assert source_row["match_tier"] == "reconciled_issuer_name_extraction"
        assert metrics.iloc[0]["blocking_issue_count"] == 0

    def test_fv_only_identity_strict_one_to_one(self):
        """FV-only matching works when exactly 1 source maps to 1 output."""
        source = _make_bdc_source([{
            "investment_identifier": "Completely Opaque Source Label 2027",
            "dimensions_raw": "source_dimensions=opaque",
            "fair_value": "7777777",
            "cost": "7000000",
        }])
        output = _make_bdc_output([{
            "bdc_investment_identifier": "Totally Different Pipeline Label",
            "bdc_dimensions_raw": "pipeline_dimensions=different",
            "issuer_name": "Unrelated Company",
            "fair_value": "7777777",
            "cost": "7500000",
        }])
        detail, metrics = reconcile_bdc_source_to_holdings(source, output)
        source_row = detail[detail["source_row_id"] != ""].iloc[0]
        assert source_row["match_tier"] == "reconciled_fv_only_identity"
        # Cost mismatch is diagnostic, not blocking
        assert source_row["status"] == "diagnostic_field_mismatch"
        assert source_row["blocking_issue"] == False

    def test_fv_only_identity_rejects_ambiguous_matches(self):
        """FV-only matching rejects when multiple candidates exist."""
        source = _make_bdc_source([{
            "investment_identifier": "Opaque Source Label Inc.",
            "dimensions_raw": "source_dimensions=opaque",
            "fair_value": "5555555",
            "cost": "5000000",
        }])
        output = _make_bdc_output([
            {
                "bdc_investment_identifier": "Output A Inc.",
                "bdc_dimensions_raw": "pipeline_dimensions=a",
                "issuer_name": "Output A Inc.",
                "fair_value": "5555555",
                "cost": "5000000",
            },
            {
                "bdc_investment_identifier": "Output B Inc.",
                "bdc_dimensions_raw": "pipeline_dimensions=b",
                "issuer_name": "Output B Inc.",
                "fair_value": "5555555",
                "cost": "5000000",
            },
        ])
        detail, _ = reconcile_bdc_source_to_holdings(source, output)
        assert "reconciled_fv_only_identity" not in set(detail["match_tier"])

    def test_partial_name_fv_matches_shared_tokens(self):
        """Partial name + FV matching works when 2+ significant tokens overlap."""
        source = _make_bdc_source([{
            "investment_identifier": "Meridian Healthcare Solutions LLC - Senior Secured",
            "dimensions_raw": "source_dimensions=long_format",
            "fair_value": "3333333",
            "cost": "3000000",
        }])
        output = _make_bdc_output([{
            "bdc_investment_identifier": "Meridian Healthcare Group - First Lien TL",
            "bdc_dimensions_raw": "pipeline_dimensions=parsed",
            "issuer_name": "Meridian Healthcare Group",
            "fair_value": "3333333",
            "cost": "3100000",
        }])
        detail, metrics = reconcile_bdc_source_to_holdings(source, output)
        source_row = detail[detail["source_row_id"] != ""].iloc[0]
        # Numeric identity won't match (different cost); one of the new tiers fires
        assert source_row["match_tier"] in (
            "reconciled_issuer_name_extraction",
            "reconciled_fv_only_identity",
            "reconciled_partial_name_fv",
        )
        assert metrics.iloc[0]["blocking_issue_count"] == 0

    def test_metrics_aggregate_detail_rows_by_cik_quarter(self):
        detail = pd.DataFrame([
            {"cik": "0000000100", "entity_name": "Test BDC", "report_date": "2024-03-31", "status": "matched", "source_row_id": "1", "output_row_id": "1"},
            {"cik": "0000000100", "entity_name": "Test BDC", "report_date": "2024-03-31", "status": "missing_from_pipeline", "source_row_id": "2", "output_row_id": ""},
            {"cik": "0000000100", "entity_name": "Test BDC", "report_date": "2024-03-31", "status": "excluded_no_fair_value", "source_row_id": "3", "output_row_id": ""},
        ])
        metrics = build_source_reconciliation_metrics(detail)
        assert len(metrics) == 1
        assert metrics.iloc[0]["source_rows"] == 3
        assert metrics.iloc[0]["matched_rows"] == 1
        assert metrics.iloc[0]["missing_from_pipeline_rows"] == 1
        assert metrics.iloc[0]["excluded_no_fair_value_rows"] == 1
        assert metrics.iloc[0]["reconciliation_status"] == "UNDER_REVIEW"

    def test_residual_classification_empty_input_has_stable_schema(self):
        classified = build_source_reconciliation_residual_classification(pd.DataFrame())
        assert list(classified.columns) == RESIDUAL_CLASSIFICATION_COLUMNS
        assert classified.empty

        markdown = build_source_reconciliation_residual_classification_markdown(classified)
        assert "No non-plain source reconciliation residual groups" in markdown

    def test_residual_classification_documents_known_non_blocking_mechanisms(self):
        detail = pd.DataFrame([
            {
                "status": "excluded_comparative_period",
                "residual_class": "documented_exclusion",
                "blocking_issue": False,
                "cik": "0000000100",
                "entity_name": "Test BDC",
                "report_date": "2024-03-31",
                "period": "2023-12-31",
                "raw_investment_identifier": "Prior Co - Term Loan",
                "source_fair_value": "100",
                "accession_number": "acc-1",
            },
            {
                "status": "excluded_no_fair_value",
                "residual_class": "documented_exclusion",
                "blocking_issue": False,
                "cik": "0000000100",
                "entity_name": "Test BDC",
                "report_date": "2024-03-31",
                "raw_investment_identifier": "No FV Co - Term Loan",
                "accession_number": "acc-1",
            },
            {
                "status": "documented_source_rollup_exact",
                "residual_class": "documented_exclusion",
                "blocking_issue": False,
                "cik": "0000000100",
                "entity_name": "Test BDC",
                "report_date": "2024-03-31",
                "raw_investment_identifier": "Total Investments",
                "source_fair_value": "500",
                "accession_number": "acc-1",
            },
            {
                "status": "excluded_aggregate_candidate",
                "residual_class": "documented_exclusion",
                "blocking_issue": False,
                "cik": "0000000100",
                "entity_name": "Test BDC",
                "report_date": "2024-03-31",
                "raw_investment_identifier": "Total Investments",
                "source_fair_value": "500",
                "accession_number": "acc-1",
            },
            {
                "status": "superseded_amendment",
                "residual_class": "documented_exclusion",
                "blocking_issue": False,
                "cik": "0000000100",
                "entity_name": "Test BDC",
                "report_date": "2024-03-31",
                "raw_investment_identifier": "Old Amendment Co",
                "source_fair_value": "200",
                "accession_number": "old",
            },
            {
                "status": "collapsed_duplicate_dimension_path",
                "residual_class": "documented_exclusion",
                "blocking_issue": False,
                "cik": "0000000100",
                "entity_name": "Test BDC",
                "report_date": "2024-03-31",
                "raw_investment_identifier": "Duplicate Co",
                "source_fair_value": "300",
                "accession_number": "acc-1",
            },
        ])

        mechanisms = set(build_source_reconciliation_residual_classification(detail)["mechanism"])
        assert {
            "documented_comparative_period",
            "documented_no_fair_value",
            "documented_aggregate_candidate",
            "documented_source_rollup_exact",
            "documented_superseded_amendment",
            "documented_duplicate_dimension_path",
        } == mechanisms

    def test_residual_classification_covers_diagnostics_and_normalized_matches(self):
        detail = pd.DataFrame([
            {
                "status": "diagnostic_field_mismatch",
                "residual_class": "field_diagnostic",
                "calibrated_status": "diagnostic_field_mismatch",
                "match_tier": "exact_dimensions_raw",
                "blocking_issue": False,
                "cik": "0000000100",
                "entity_name": "Test BDC",
                "report_date": "2024-03-31",
                "raw_investment_identifier": "Diagnostic Co - Equity",
                "source_fair_value": "1000",
                "output_fair_value": "1000",
            },
            {
                "status": "matched",
                "residual_class": "reconciled",
                "calibrated_status": "reconciled",
                "match_tier": "staging_normalized_identifier",
                "blocking_issue": False,
                "cik": "0000000100",
                "entity_name": "Test BDC",
                "report_date": "2024-03-31",
                "raw_investment_identifier": "Investments in Non-Controlled - Acme Co",
                "source_fair_value": "2000",
                "output_fair_value": "2000",
            },
            {
                "status": "matched",
                "residual_class": "reconciled",
                "calibrated_status": "reconciled",
                "match_tier": "exact_dimensions_raw",
                "blocking_issue": False,
                "cik": "0000000100",
                "entity_name": "Test BDC",
                "report_date": "2024-03-31",
                "raw_investment_identifier": "Plain Exact Co",
                "source_fair_value": "3000",
                "output_fair_value": "3000",
            },
        ])

        classified = build_source_reconciliation_residual_classification(detail)
        assert set(classified["mechanism"]) == {
            "diagnostic_secondary_field_mismatch",
            "reconciled_identifier_normalization",
        }
        assert "Plain Exact Co" not in "|".join(classified["sample_identifiers"].fillna(""))

    def test_residual_classification_covers_row_identity_blockers(self):
        detail = pd.DataFrame([
            {
                "status": "missing_from_pipeline",
                "residual_class": "row_identity",
                "blocking_issue": True,
                "cik": "0000000100",
                "entity_name": "Test BDC",
                "report_date": "2024-03-31",
                "raw_investment_identifier": "Acme Co - Term Loan",
                "source_fair_value": "1000",
            },
            {
                "status": "extra_in_pipeline",
                "residual_class": "row_identity",
                "blocking_issue": True,
                "cik": "0000000100",
                "entity_name": "Test BDC",
                "report_date": "2024-03-31",
                "raw_investment_identifier": "Extra Co - Term Loan",
                "output_fair_value": "2000",
            },
            {
                "status": "missing_from_pipeline",
                "residual_class": "row_identity",
                "blocking_issue": True,
                "cik": "0000000100",
                "entity_name": "Test BDC",
                "report_date": "2024-03-31",
                "raw_investment_identifier": "2024-03-31",
                "source_fair_value": "3000",
            },
            {
                "status": "missing_from_pipeline",
                "residual_class": "row_identity",
                "blocking_issue": True,
                "cik": "0000000100",
                "entity_name": "Test BDC",
                "report_date": "2024-03-31",
                "raw_investment_identifier": "Software",
                "source_fair_value": "4000",
            },
        ])

        classified = build_source_reconciliation_residual_classification(detail)
        by_mechanism = dict(zip(classified["mechanism"], classified["issue_count"]))
        assert by_mechanism["blocking_source_position_like_parser_mismatch"] == 1
        assert by_mechanism["blocking_pipeline_only_position"] == 1
        assert by_mechanism["blocking_identifier_parse_artifact"] == 2

    def test_source_only_blocker_detail_classifies_headers_and_false_positives(self):
        detail = pd.DataFrame([
            {
                "status": "missing_from_pipeline",
                "residual_class": "row_identity",
                "blocking_issue": True,
                "cik": "0000000100",
                "entity_name": "Test BDC",
                "report_date": "2024-03-31",
                "period": "2024-03-31",
                "accession_number": "acc-1",
                "source_row_id": "s1",
                "raw_investment_identifier": "TOTAL INVESTMENTS - 114.8%",
                "source_fair_value": "5000",
                "evidence": "eligible current-period source row has no pipeline output row",
            },
            {
                "status": "missing_from_pipeline",
                "residual_class": "row_identity",
                "blocking_issue": True,
                "cik": "0000000100",
                "entity_name": "Test BDC",
                "report_date": "2024-03-31",
                "period": "2024-03-31",
                "accession_number": "acc-1",
                "source_row_id": "s2",
                "raw_investment_identifier": "Goldman Sachs Financial Square Government Institutional Fund",
                "source_fair_value": "100",
                "evidence": "eligible current-period source row has no pipeline output row",
            },
            {
                "status": "missing_from_pipeline",
                "residual_class": "row_identity",
                "blocking_issue": True,
                "cik": "0000000100",
                "entity_name": "Test BDC",
                "report_date": "2024-03-31",
                "period": "2024-03-31",
                "accession_number": "acc-1",
                "source_row_id": "s3",
                "raw_investment_identifier": "Total Safety Holdings LLC",
                "source_fair_value": "1000",
                "evidence": "eligible current-period source row has no pipeline output row",
            },
            {
                "status": "missing_from_pipeline",
                "residual_class": "row_identity",
                "blocking_issue": True,
                "cik": "0000000100",
                "entity_name": "Test BDC",
                "report_date": "2024-03-31",
                "period": "2024-03-31",
                "accession_number": "acc-1",
                "source_row_id": "s4",
                "raw_investment_identifier": "Total Cash and Investments - 218.4%",
                "source_fair_value": "5000",
                "evidence": "eligible current-period source row has no pipeline output row",
            },
            {
                "status": "missing_from_pipeline",
                "residual_class": "row_identity",
                "blocking_issue": True,
                "cik": "0000000100",
                "entity_name": "Test BDC",
                "report_date": "2024-03-31",
                "period": "2024-03-31",
                "accession_number": "acc-1",
                "source_row_id": "s5",
                "raw_investment_identifier": "First Lien - Secured Debt",
                "source_fair_value": "5000",
                "evidence": "eligible current-period source row has no pipeline output row",
            },
            {
                "status": "missing_from_pipeline",
                "residual_class": "row_identity",
                "blocking_issue": True,
                "cik": "0000000100",
                "entity_name": "Test BDC",
                "report_date": "2024-03-31",
                "period": "2024-03-31",
                "accession_number": "acc-1",
                "source_row_id": "s6",
                "raw_investment_identifier": (
                    "Non-Controlled/Non-Affiliated Investments, Insurance, "
                    "First Lien - Secured Debt"
                ),
                "source_fair_value": "5000",
                "evidence": "eligible current-period source row has no pipeline output row",
            },
            {
                "status": "missing_from_pipeline",
                "residual_class": "row_identity",
                "blocking_issue": True,
                "cik": "0000000100",
                "entity_name": "Test BDC",
                "report_date": "2024-03-31",
                "period": "2024-03-31",
                "accession_number": "acc-1",
                "source_row_id": "s7",
                "raw_investment_identifier": (
                    "Senior Secured Notes - Materials - Veritiv Operating Company - "
                    "first lien senior secured notes"
                ),
                "source_fair_value": "5000",
                "evidence": "eligible current-period source row has no pipeline output row",
            },
            {
                "status": "missing_from_pipeline",
                "residual_class": "row_identity",
                "blocking_issue": True,
                "cik": "0001993402",
                "entity_name": "Antares Strategic Credit Fund",
                "report_date": "2025-03-31",
                "period": "2025-03-31",
                "accession_number": "acc-antares",
                "source_row_id": "antares-total-investments",
                "raw_investment_identifier": "Total Investments - non-controlled/non-affiliated",
                "source_fair_value": "2586320000",
                "evidence": "eligible current-period source row has no pipeline output row",
            },
            {
                "status": "missing_from_pipeline",
                "residual_class": "row_identity",
                "blocking_issue": True,
                "cik": "0001993402",
                "entity_name": "Antares Strategic Credit Fund",
                "report_date": "2025-03-31",
                "period": "2025-03-31",
                "accession_number": "acc-antares",
                "source_row_id": "antares-unfunded-commitments",
                "raw_investment_identifier": "Investments-non-controlled/non-affiliated Total Unfunded Commitments",
                "source_fair_value": "-3703000",
                "evidence": "eligible current-period source row has no pipeline output row",
            },
            {
                "status": "missing_from_pipeline",
                "residual_class": "row_identity",
                "blocking_issue": True,
                "cik": "0001899996",
                "entity_name": "Fidelity Private Credit Co LLC",
                "report_date": "2023-09-30",
                "period": "2023-09-30",
                "accession_number": "acc-fidelity",
                "source_row_id": "fidelity-total-investments",
                "raw_investment_identifier": "Investments, Total Investments -- non-controlled/ non-affiliated",
                "source_fair_value": "1289595075",
                "evidence": "eligible current-period source row has no pipeline output row",
            },
        ])

        classified = build_source_only_blocker_detail(detail)
        by_id = dict(zip(classified["raw_investment_identifier"], classified["mechanism"]))
        assert by_id["TOTAL INVESTMENTS - 114.8%"] == "documented_source_pct_total_header"
        assert by_id["Total Cash and Investments - 218.4%"] == "documented_source_pct_total_header"
        assert by_id["First Lien - Secured Debt"] == "documented_source_category_header"
        assert (
            by_id[
                "Non-Controlled/Non-Affiliated Investments, Insurance, "
                "First Lien - Secured Debt"
            ]
            == "documented_source_category_header"
        )
        assert (
            by_id["Goldman Sachs Financial Square Government Institutional Fund"]
            == "documented_source_cash_or_money_market_bucket"
        )
        assert by_id["Total Safety Holdings LLC"] == "blocking_source_position_like_parser_mismatch"
        assert (
            by_id[
                "Senior Secured Notes - Materials - Veritiv Operating Company - "
                "first lien senior secured notes"
            ]
            == "blocking_source_position_like_parser_mismatch"
        )
        assert by_id["Total Investments - non-controlled/non-affiliated"] == "documented_source_total_header"
        assert (
            by_id["Investments-non-controlled/non-affiliated Total Unfunded Commitments"]
            == "documented_source_total_header"
        )
        assert (
            by_id["Investments, Total Investments -- non-controlled/ non-affiliated"]
            == "documented_source_total_header"
        )
        assert bool(
            classified.loc[
                classified["raw_investment_identifier"].eq("Total Safety Holdings LLC"),
                "is_blocking",
            ].iloc[0]
        ) is True

    def test_source_only_blocker_detail_splits_terminal_pct_rollups_from_leaf_rows(self):
        detail = pd.DataFrame([
            {
                "status": "missing_from_pipeline",
                "residual_class": "row_identity",
                "blocking_issue": True,
                "cik": "0000000100",
                "entity_name": "Test BDC",
                "report_date": "2024-03-31",
                "accession_number": "acc-1",
                "source_row_id": "total-pct",
                "raw_investment_identifier": "Net Assets-100.0%",
                "source_fair_value": "1000",
            },
            {
                "status": "missing_from_pipeline",
                "residual_class": "row_identity",
                "blocking_issue": True,
                "cik": "0000000100",
                "entity_name": "Test BDC",
                "report_date": "2024-03-31",
                "accession_number": "acc-1",
                "source_row_id": "category-pct",
                "raw_investment_identifier": "Debt Investments (184.96%)",
                "source_fair_value": "2000",
            },
            {
                "status": "missing_from_pipeline",
                "residual_class": "row_identity",
                "blocking_issue": True,
                "cik": "0000000100",
                "entity_name": "Test BDC",
                "report_date": "2024-03-31",
                "accession_number": "acc-1",
                "source_row_id": "geo-pct",
                "raw_investment_identifier": "Investment United States - 141.4%",
                "source_fair_value": "3000",
            },
            {
                "status": "missing_from_pipeline",
                "residual_class": "row_identity",
                "blocking_issue": True,
                "cik": "0000000100",
                "entity_name": "Test BDC",
                "report_date": "2024-03-31",
                "accession_number": "acc-1",
                "source_row_id": "security-pct",
                "raw_investment_identifier": "Investment 1st Lien/Senior Secured Debt - 136.5%",
                "source_fair_value": "4000",
            },
            {
                "status": "missing_from_pipeline",
                "residual_class": "row_identity",
                "blocking_issue": True,
                "cik": "0000000100",
                "entity_name": "Test BDC",
                "report_date": "2024-03-31",
                "accession_number": "acc-1",
                "source_row_id": "leaf-pct",
                "raw_investment_identifier": "Acme Holdings LLC First Lien Term Loan - 12.0%",
                "source_fair_value": "5000",
            },
            {
                "status": "missing_from_pipeline",
                "residual_class": "row_identity",
                "blocking_issue": True,
                "cik": "0000000100",
                "entity_name": "Test BDC",
                "report_date": "2024-03-31",
                "accession_number": "acc-1",
                "source_row_id": "ambiguous-pct",
                "raw_investment_identifier": "North - 10.0%",
                "source_fair_value": "6000",
            },
            {
                "status": "missing_from_pipeline",
                "residual_class": "row_identity",
                "blocking_issue": True,
                "cik": "0000000100",
                "entity_name": "Test BDC",
                "report_date": "2024-03-31",
                "accession_number": "acc-1",
                "source_row_id": "numeric-alias-pct",
                "raw_investment_identifier": "TOTAL INVESTMENTS - 134.4%",
                "source_fair_value": "7000",
                "evidence": "blocking numeric identity candidate; already_matched_output_count=1",
            },
            {
                "status": "missing_from_pipeline",
                "residual_class": "row_identity",
                "blocking_issue": True,
                "cik": "0001902649",
                "entity_name": "BlackRock Private Credit Fund",
                "report_date": "2024-12-31",
                "accession_number": "acc-blackrock",
                "source_row_id": "blackrock-debt-total",
                "raw_investment_identifier": "Debt Investments - 159.7% of Net Assets",
                "source_fair_value": "1039985833",
            },
            {
                "status": "missing_from_pipeline",
                "residual_class": "row_identity",
                "blocking_issue": True,
                "cik": "0001902649",
                "entity_name": "BlackRock Private Credit Fund",
                "report_date": "2024-12-31",
                "accession_number": "acc-blackrock",
                "source_row_id": "blackrock-cash-investments-total",
                "raw_investment_identifier": "Cash and Investments - 166.1% of Net Assets",
                "source_fair_value": "1081472023",
            },
            {
                "status": "missing_from_pipeline",
                "residual_class": "row_identity",
                "blocking_issue": True,
                "cik": "0001902649",
                "entity_name": "BlackRock Private Credit Fund",
                "report_date": "2024-12-31",
                "accession_number": "acc-blackrock",
                "source_row_id": "blackrock-leaf-with-net-assets",
                "raw_investment_identifier": (
                    "Debt Investments Chemicals Discovery Purchaser Corporation "
                    "Instrument First Lien Term Loan Ref SOFR(Q) Floor 0.50% "
                    "Spread 4.38% Total Coupon 8.95% Maturity 10/4/2029 - "
                    "0.14% of Net Assets"
                ),
                "source_fair_value": "1505450",
            },
        ])

        classified = build_source_only_blocker_detail(detail)
        mechanisms = dict(zip(classified["source_row_id"], classified["mechanism"]))
        assert mechanisms["total-pct"] == "documented_source_pct_total_header"
        assert mechanisms["category-pct"] == "documented_source_pct_category_rollup"
        assert mechanisms["geo-pct"] == "documented_source_pct_category_rollup"
        assert mechanisms["security-pct"] == "documented_source_pct_category_rollup"
        assert mechanisms["leaf-pct"] == "blocking_source_pct_leaf_parser_mismatch"
        assert mechanisms["ambiguous-pct"] == "blocking_source_pct_ambiguous_after_review"
        assert mechanisms["numeric-alias-pct"] == "blocking_numeric_already_matched_output_alias"
        assert mechanisms["blackrock-debt-total"] == "documented_source_pct_category_rollup"
        assert mechanisms["blackrock-cash-investments-total"] == "documented_source_pct_total_header"
        assert mechanisms["blackrock-leaf-with-net-assets"] == "blocking_source_pct_leaf_parser_mismatch"

    def test_source_only_blocker_detail_keeps_pct_leaf_false_positives_blocking(self):
        detail = pd.DataFrame([
            {
                "status": "missing_from_pipeline",
                "residual_class": "row_identity",
                "blocking_issue": True,
                "cik": "0000000100",
                "entity_name": "Test BDC",
                "report_date": "2024-03-31",
                "accession_number": "acc-1",
                "source_row_id": "seybert",
                "raw_investment_identifier": "Seybert's Billiards Corporation - Term Note at 12%",
                "source_fair_value": "1000",
            },
            {
                "status": "missing_from_pipeline",
                "residual_class": "row_identity",
                "blocking_issue": True,
                "cik": "0001655050",
                "entity_name": "Bain Capital Specialty Finance, Inc.",
                "report_date": "2025-09-30",
                "accession_number": "acc-bain",
                "source_row_id": "bain",
                "raw_investment_identifier": (
                    "Aerospace & Defense ATS First Lien Senior Secured Loan "
                    "SOFR Spread 5.75% Interest Rate 10.07% Maturity Date 7/12/2029"
                ),
                "source_fair_value": "2000",
            },
            {
                "status": "missing_from_pipeline",
                "residual_class": "row_identity",
                "blocking_issue": True,
                "cik": "0001954360",
                "entity_name": "Crescent Private Credit Income Corp",
                "report_date": "2025-09-30",
                "accession_number": "acc-crescent",
                "source_row_id": "crescent",
                "raw_investment_identifier": (
                    "Investments Netherlands Debt Investments Commercial Services "
                    "Playgreen Investment Type Unitranche First Lien Term Loan "
                    "Interest Rate 9.60% Maturity/Dissolution Date 04/2031"
                ),
                "source_fair_value": "3000",
            },
            {
                "status": "missing_from_pipeline",
                "residual_class": "row_identity",
                "blocking_issue": True,
                "cik": "0001849894",
                "entity_name": "MSD Investment Corp.",
                "report_date": "2025-09-30",
                "accession_number": "acc-msd",
                "source_row_id": "msd",
                "raw_investment_identifier": (
                    "Investments Investments - non-controlled/non-affiliated First Lien Debt "
                    "7Ridge Investments Reference Rate and Spread S + 8.00% "
                    "Interest Rate 11.67% Maturity Date 7/7/2028"
                ),
                "source_fair_value": "4000",
            },
        ])

        classified = build_source_only_blocker_detail(detail)
        mechanisms = dict(zip(classified["source_row_id"], classified["mechanism"]))
        assert set(mechanisms.values()) == {"blocking_source_pct_leaf_parser_mismatch"}
        assert classified["is_blocking"].all()

    def test_source_only_blocker_detail_classifies_cik_style_parser_residuals(self):
        detail = pd.DataFrame([
            {
                "status": "missing_from_pipeline",
                "residual_class": "row_identity",
                "blocking_issue": True,
                "cik": "0001954360",
                "entity_name": "Crescent Private Credit Income Corp",
                "report_date": "2025-09-30",
                "accession_number": "acc-crescent",
                "source_row_id": "crescent-header",
                "raw_investment_identifier": "Investments Netherlands Debt Investments Financial Services",
                "source_fair_value": "0",
            },
            {
                "status": "missing_from_pipeline",
                "residual_class": "row_identity",
                "blocking_issue": True,
                "cik": "0001959568",
                "entity_name": "Senior Credit Investments, LLC",
                "report_date": "2023-12-31",
                "accession_number": "acc-msd",
                "source_row_id": "msd-header",
                "raw_investment_identifier": "Non-Controlled/Non-Affiliated Portfolio Company Investments First Lien Debt Investments High Tech Industries",
                "source_fair_value": "0",
            },
            {
                "status": "missing_from_pipeline",
                "residual_class": "row_identity",
                "blocking_issue": True,
                "cik": "0001965934",
                "entity_name": "Overland Advantage",
                "report_date": "2025-06-30",
                "accession_number": "acc-long",
                "source_row_id": "long-position",
                "raw_investment_identifier": (
                    "Investments Non-controlled/non-affiliated senior secured debt Debt "
                    "investments Consumer Finance Maxitransfers Blocker Corp Second lien "
                    "senior secured term loan Interest Rate SOFR + 6.75% Maturity Date 6/18/2030"
                ),
                "source_fair_value": "1000",
            },
        ])

        classified = build_source_only_blocker_detail(detail)
        mechanisms = dict(zip(classified["source_row_id"], classified["mechanism"]))
        assert mechanisms["crescent-header"] == "documented_source_country_industry_header"
        assert mechanisms["msd-header"] == "documented_source_category_header"
        assert mechanisms["long-position"] == "blocking_source_pct_leaf_parser_mismatch"

        clusters = build_source_only_blocker_clusters(classified)
        markdown = build_source_only_blocker_markdown(classified, clusters)
        assert "Pct Leaf Parser Queue" in markdown
        assert "Pct Rollup/Header Exclusions" in markdown
        assert "Unclassifiable After Review" in markdown

    def test_source_only_unclassifiable_remains_blocking_with_required_fields(self):
        detail = pd.DataFrame([{
            "status": "missing_from_pipeline",
            "residual_class": "row_identity",
            "blocking_issue": True,
            "cik": "0000000100",
            "entity_name": "Test BDC",
            "report_date": "2024-03-31",
            "accession_number": "acc-1",
            "source_row_id": "s1",
            "raw_investment_identifier": "North",
            "source_fair_value": "1000",
        }])

        classified = build_source_only_blocker_detail(detail)
        row = classified.iloc[0]
        assert row["mechanism"] == "blocking_source_short_plain_unresolved"
        assert bool(row["is_blocking"]) is True
        for col in [
            "evidence_reviewed",
            "hypotheses_tested",
            "why_not_cleared",
            "recommended_action",
        ]:
            assert row[col]

    def test_residual_classification_covers_fair_value_mismatch_mechanisms(self):
        detail = pd.DataFrame([
            {
                "status": "value_mismatch",
                "residual_class": "fair_value",
                "blocking_issue": True,
                "cik": "0000000100",
                "entity_name": "Test BDC",
                "report_date": "2024-03-31",
                "raw_investment_identifier": "Scale Co - Term Loan",
                "source_fair_value": "1000",
                "output_fair_value": "1000000",
            },
            {
                "status": "value_mismatch",
                "residual_class": "fair_value",
                "blocking_issue": True,
                "cik": "0000000100",
                "entity_name": "Test BDC",
                "report_date": "2024-03-31",
                "raw_investment_identifier": "Disagree Co - Term Loan",
                "source_fair_value": "1000",
                "output_fair_value": "1400",
            },
        ])

        classified = build_source_reconciliation_residual_classification(detail)
        assert set(classified["mechanism"]) == {
            "blocking_fair_value_scale_or_unit_candidate",
            "blocking_fair_value_disagreement",
        }
        markdown = build_source_reconciliation_residual_classification_markdown(classified)
        assert "Fair-Value Mismatch Groups" in markdown
        assert "Recommended Next Fixes" in markdown


# ---------------------------------------------------------------------------
# spot_check_top_ciks
# ---------------------------------------------------------------------------

class TestSpotCheckTopCiks:
    def test_correct_columns(self):
        df = _make_basic_holdings()
        result = spot_check_top_ciks(df, top_n=3, sample_per_cik=5)
        assert "cik" in result.columns
        assert "classification_signals" in result.columns
        assert "issuer_name" in result.columns

    def test_samples_top_n(self):
        df = _make_basic_holdings(n_bdc=30)
        result = spot_check_top_ciks(df, top_n=2, sample_per_cik=5)
        assert result["cik"].nunique() <= 2

    def test_respects_sample_limit(self):
        df = _make_basic_holdings(n_bdc=30)
        result = spot_check_top_ciks(df, top_n=1, sample_per_cik=3)
        # Should have at most 3 rows per CIK
        for cik in result["cik"].unique():
            assert len(result[result["cik"] == cik]) <= 3

    def test_includes_unclassified(self):
        rows = _make_basic_holdings(n_bdc=5, n_nport=0)
        # Add an UNCLASSIFIED row for same CIK
        extra = _make_unified_df([{
            "source": "bdc", "cik": "100", "entity_name": "BDC 100",
            "issuer_name": "Mystery Corp", "index_classification": "UNCLASSIFIED",
            "asset_category": "OTHER", "issuer_category": "CORPORATE",
            "fair_value": "100000", "report_date": "2024-03-31",
            "bdc_investment_identifier": "Mystery Corp",
        }])
        df = pd.concat([rows, extra], ignore_index=True)
        result = spot_check_top_ciks(df, top_n=3, sample_per_cik=50)
        # UNCLASSIFIED should appear in sample
        assert "UNCLASSIFIED" in result["index_classification"].values

    def test_signals_populated(self):
        df = _make_basic_holdings(n_bdc=5, n_nport=0)
        result = spot_check_top_ciks(df, top_n=1, sample_per_cik=5)
        # All rows should have signals
        assert all(result["classification_signals"] != "")

    def test_empty_input(self):
        df = _make_unified_df([])
        result = spot_check_top_ciks(df, top_n=5)
        assert len(result) == 0


# ---------------------------------------------------------------------------
# summarize_classification_by_cik
# ---------------------------------------------------------------------------

class TestSummarizeClassificationByCik:
    def test_per_cik_summary_correct(self):
        df = _make_basic_holdings(n_bdc=10, n_nport=0)
        result = summarize_classification_by_cik(df)
        assert len(result) == 3  # 3 unique BDC CIKs
        assert "total_rows" in result.columns
        assert "pct_direct_lending" in result.columns

    def test_anomaly_flagging_high_unclassified(self):
        rows = []
        for i in range(10):
            rows.append({
                "source": "bdc", "cik": "999", "entity_name": "Bad BDC",
                "issuer_name": f"Unknown {i}", "fair_value": "100000",
                "asset_category": "OTHER", "issuer_category": "CORPORATE",
                "index_classification": "UNCLASSIFIED",
                "report_date": "2024-03-31",
            })
        df = _make_unified_df(rows)
        result = summarize_classification_by_cik(df)
        assert len(result) == 1
        assert result.iloc[0]["has_anomalous_mix"] == True

    def test_no_anomaly_for_normal_bdc(self):
        df = _make_basic_holdings(n_bdc=10, n_nport=0)
        result = summarize_classification_by_cik(df)
        # All DIRECT_LENDING, no anomalous
        assert all(~result["has_anomalous_mix"])

    def test_empty_input(self):
        df = _make_unified_df([])
        result = summarize_classification_by_cik(df)
        assert len(result) == 0


# ---------------------------------------------------------------------------
# audit_aggregate_leaks
# ---------------------------------------------------------------------------

class TestAuditAggregateLeaks:
    def test_detects_keyword_match(self):
        df = _make_unified_df([{
            "source": "bdc", "cik": "100", "entity_name": "Test BDC",
            "issuer_name": "Total Senior Secured", "fair_value": "50000000",
            "bdc_investment_identifier": "Total Senior Secured - First Lien",
            "asset_category": "LOAN", "issuer_category": "CORPORATE",
            "index_classification": "DIRECT_LENDING",
        }])
        result = audit_aggregate_leaks(df)
        assert len(result) >= 1
        assert "keyword" in result.iloc[0]["reason"]

    def test_no_outlier_false_positives(self):
        """Large fair_value alone should NOT flag a position as aggregate."""
        rows = []
        # 9 normal rows
        for i in range(9):
            rows.append({
                "source": "bdc", "cik": "100", "entity_name": "Test BDC",
                "issuer_name": f"Company {i}",
                "fair_value": str(1_000_000),
                "bdc_investment_identifier": f"Company {i} - Term Loan",
                "asset_category": "LOAN", "issuer_category": "CORPORATE",
                "index_classification": "DIRECT_LENDING",
            })
        # 1 large position (100x median) -- should NOT be flagged
        rows.append({
            "source": "bdc", "cik": "100", "entity_name": "Test BDC",
            "issuer_name": "Big Loan Corp",
            "fair_value": str(100_000_000),
            "bdc_investment_identifier": "Big Loan Corp - First Lien Term Loan",
            "asset_category": "LOAN", "issuer_category": "CORPORATE",
            "index_classification": "DIRECT_LENDING",
        })
        df = _make_unified_df(rows)
        result = audit_aggregate_leaks(df)
        assert len(result) == 0

    def test_ignores_nport_rows(self):
        df = _make_unified_df([{
            "source": "nport", "cik": "200", "entity_name": "Test Fund",
            "issuer_name": "Total Investments",
            "fair_value": "50000000",
            "bdc_investment_identifier": "",
            "nport_asset_cat": "LON", "nport_issuer_type": "CORP",
            "asset_category": "LOAN", "issuer_category": "CORPORATE",
            "index_classification": "DIRECT_LENDING",
        }])
        result = audit_aggregate_leaks(df)
        assert len(result) == 0

    def test_doesnt_flag_normal_holding(self):
        df = _make_unified_df([{
            "source": "bdc", "cik": "100", "entity_name": "Test BDC",
            "issuer_name": "Acme Corp",
            "fair_value": "1000000",
            "bdc_investment_identifier": "Acme Corp - First Lien Term Loan",
            "asset_category": "LOAN", "issuer_category": "CORPORATE",
            "index_classification": "DIRECT_LENDING",
        }])
        result = audit_aggregate_leaks(df)
        assert len(result) == 0

    def test_empty_bdc(self):
        df = _make_unified_df([])
        result = audit_aggregate_leaks(df)
        assert len(result) == 0
        assert "reason" in result.columns


# ---------------------------------------------------------------------------
# check_cross_source_overlap
# ---------------------------------------------------------------------------

class TestCheckCrossSourceOverlap:
    def test_zero_overlap(self):
        df = _make_basic_holdings(n_bdc=5, n_nport=3)
        overlap_summary, duplicate_holdings = check_cross_source_overlap(df)
        assert len(overlap_summary) == 0
        assert len(duplicate_holdings) == 0

    def test_overlap_detected(self):
        rows = [
            {"source": "bdc", "cik": "100", "entity_name": "Dual Entity",
             "issuer_name": "X Corp", "fair_value": "100", "report_date": "2024-03-31"},
            {"source": "nport", "cik": "100", "entity_name": "Dual Entity",
             "issuer_name": "Y Corp", "fair_value": "200", "report_date": "2024-06-30"},
        ]
        df = _make_unified_df(rows)
        overlap_summary, duplicate_holdings = check_cross_source_overlap(df)
        assert len(overlap_summary) == 1
        assert overlap_summary.iloc[0]["cik"] == "100"
        assert overlap_summary.iloc[0]["bdc_rows"] == 1
        assert overlap_summary.iloc[0]["nport_rows"] == 1

    def test_duplicate_holdings_detected(self):
        """When same issuer appears in both sources for same CIK/period, detect as dupe."""
        rows = [
            {"source": "bdc", "cik": "100", "entity_name": "Dual Entity",
             "issuer_name": "Acme Corp", "fair_value": "1000000",
             "report_date": "2024-03-31"},
            {"source": "nport", "cik": "100", "entity_name": "Dual Entity",
             "issuer_name": "Acme Corp", "fair_value": "1000500",
             "report_date": "2024-03-31"},
        ]
        df = _make_unified_df(rows)
        overlap_summary, duplicate_holdings = check_cross_source_overlap(df)
        assert len(overlap_summary) == 1
        assert len(duplicate_holdings) >= 1
        assert duplicate_holdings.iloc[0]["bdc_issuer"] == "Acme Corp"
        assert duplicate_holdings.iloc[0]["nport_issuer"] == "Acme Corp"

    def test_no_duplicate_different_issuers(self):
        """Different issuers in same CIK/period should not be flagged as dupes."""
        rows = [
            {"source": "bdc", "cik": "100", "entity_name": "Dual Entity",
             "issuer_name": "Alpha Corp", "fair_value": "1000000",
             "report_date": "2024-03-31"},
            {"source": "nport", "cik": "100", "entity_name": "Dual Entity",
             "issuer_name": "Zeta Industries", "fair_value": "2000000",
             "report_date": "2024-03-31"},
        ]
        df = _make_unified_df(rows)
        overlap_summary, duplicate_holdings = check_cross_source_overlap(df)
        assert len(overlap_summary) == 1
        assert len(duplicate_holdings) == 0

    def test_no_duplicate_different_periods(self):
        """Same issuer in different periods should not be flagged."""
        rows = [
            {"source": "bdc", "cik": "100", "entity_name": "Dual Entity",
             "issuer_name": "Acme Corp", "fair_value": "1000000",
             "report_date": "2024-03-31"},
            {"source": "nport", "cik": "100", "entity_name": "Dual Entity",
             "issuer_name": "Acme Corp", "fair_value": "1000000",
             "report_date": "2024-06-30"},
        ]
        df = _make_unified_df(rows)
        overlap_summary, duplicate_holdings = check_cross_source_overlap(df)
        assert len(overlap_summary) == 1
        assert len(duplicate_holdings) == 0

    def test_fuzzy_match_similar_names(self):
        """Similar but not identical issuer names should be matched."""
        rows = [
            {"source": "bdc", "cik": "100", "entity_name": "Dual Entity",
             "issuer_name": "Acme Corporation LLC", "fair_value": "1000000",
             "report_date": "2024-03-31"},
            {"source": "nport", "cik": "100", "entity_name": "Dual Entity",
             "issuer_name": "Acme Corporation, LLC", "fair_value": "1000000",
             "report_date": "2024-03-31"},
        ]
        df = _make_unified_df(rows)
        overlap_summary, duplicate_holdings = check_cross_source_overlap(df)
        assert len(duplicate_holdings) >= 1

    def test_pct_diff_calculated(self):
        """The pct_diff column should show the percentage difference in fair_value."""
        rows = [
            {"source": "bdc", "cik": "100", "entity_name": "Dual Entity",
             "issuer_name": "Acme Corp", "fair_value": "1000000",
             "report_date": "2024-03-31"},
            {"source": "nport", "cik": "100", "entity_name": "Dual Entity",
             "issuer_name": "Acme Corp", "fair_value": "900000",
             "report_date": "2024-03-31"},
        ]
        df = _make_unified_df(rows)
        _, duplicate_holdings = check_cross_source_overlap(df)
        assert len(duplicate_holdings) >= 1
        assert "pct_diff" in duplicate_holdings.columns
        pct = duplicate_holdings.iloc[0]["pct_diff"]
        assert abs(pct - 0.1) < 0.01  # 10% difference


# ---------------------------------------------------------------------------
# check_coverage
# ---------------------------------------------------------------------------

class TestCheckCoverage:
    def _make_universe(self):
        return pd.DataFrame([
            {"cik": "100", "entity_name": "BDC A", "vehicle_type": "bdc"},
            {"cik": "101", "entity_name": "BDC B", "vehicle_type": "bdc"},
            {"cik": "999", "entity_name": "Empty BDC", "vehicle_type": "bdc"},
        ])

    def test_flags_no_holdings(self):
        df = _make_unified_df([{
            "source": "bdc", "cik": "100", "entity_name": "BDC A",
            "fair_value": "1000000", "report_date": "2024-03-31",
        }])
        universe = self._make_universe()
        result = check_coverage(df, universe_df=universe)
        no_hold = result[result["issue"] == "no_holdings"]
        assert len(no_hold) >= 1
        assert "999" in no_hold["cik"].values

    def test_flags_single_period(self):
        df = _make_unified_df([{
            "source": "bdc", "cik": "100", "entity_name": "BDC A",
            "fair_value": "1000000", "report_date": "2024-03-31",
        }])
        universe = self._make_universe()
        result = check_coverage(df, universe_df=universe)
        cik100 = result[result["cik"] == "100"].iloc[0]
        assert cik100["issue"] == "single_period"

    def test_ok_for_multi_period(self):
        rows = [
            {"source": "bdc", "cik": "100", "entity_name": "BDC A",
             "fair_value": "1000000", "report_date": "2024-03-31"},
            {"source": "bdc", "cik": "100", "entity_name": "BDC A",
             "fair_value": "1100000", "report_date": "2024-06-30"},
        ]
        df = _make_unified_df(rows)
        universe = self._make_universe()
        result = check_coverage(df, universe_df=universe)
        cik100 = result[result["cik"] == "100"].iloc[0]
        assert cik100["issue"] == "ok"

    def test_empty_holdings(self):
        df = _make_unified_df([])
        universe = self._make_universe()
        result = check_coverage(df, universe_df=universe)
        assert all(result["issue"] == "no_holdings")

    def test_has_total_assets_columns(self):
        """Coverage report should include total assets and ratio columns."""
        rows = [
            {"source": "bdc", "cik": "100", "entity_name": "BDC A",
             "fair_value": "1000000", "report_date": "2024-03-31"},
            {"source": "bdc", "cik": "100", "entity_name": "BDC A",
             "fair_value": "1100000", "report_date": "2024-06-30"},
        ]
        df = _make_unified_df(rows)
        universe = self._make_universe()
        result = check_coverage(df, universe_df=universe)
        assert "reported_net_assets" in result.columns
        assert "holdings_to_assets_ratio" in result.columns

    def test_total_assets_from_pct(self):
        """BDC total assets should be estimated from pct_of_net_assets."""
        rows = [
            {"source": "bdc", "cik": "100", "entity_name": "BDC A",
             "fair_value": "1000000", "pct_of_net_assets": "10.0",
             "report_date": "2024-03-31"},
            {"source": "bdc", "cik": "100", "entity_name": "BDC A",
             "fair_value": "2000000", "pct_of_net_assets": "20.0",
             "report_date": "2024-03-31"},
        ]
        df = _make_unified_df(rows)
        universe = self._make_universe()
        result = check_coverage(df, universe_df=universe)
        cik100 = result[result["cik"] == "100"].iloc[0]
        # sum(fair_value) = 3M, sum(pct) = 30%, estimated_total = 3M / 0.30 = 10M
        assert cik100["reported_net_assets"] is not None
        net_assets = float(cik100["reported_net_assets"])
        assert abs(net_assets - 10_000_000) < 100

    def test_nport_total_assets_from_fund_info(self):
        """N-PORT total assets should come from nport_fund_info if provided."""
        rows = [
            {"source": "nport", "cik": "200", "entity_name": "Fund A",
             "fair_value": "5000000", "report_date": "2024-06-30"},
        ]
        df = _make_unified_df(rows)
        universe = pd.DataFrame([
            {"cik": "200", "entity_name": "Fund A", "vehicle_type": "interval_fund"},
        ])
        nport_info = pd.DataFrame([
            {"cik": "200", "net_assets": "50000000", "report_date": "2024-06-30"},
        ])
        result = check_coverage(df, universe_df=universe,
                                nport_fund_info_df=nport_info)
        cik200 = result[result["cik"] == "200"].iloc[0]
        assert float(cik200["reported_net_assets"]) == 50_000_000

    def test_no_fund_info_graceful(self):
        """Coverage should work even without nport_fund_info."""
        rows = [
            {"source": "nport", "cik": "200", "entity_name": "Fund A",
             "fair_value": "5000000", "report_date": "2024-06-30"},
            {"source": "nport", "cik": "200", "entity_name": "Fund A",
             "fair_value": "5100000", "report_date": "2024-09-30"},
        ]
        df = _make_unified_df(rows)
        universe = pd.DataFrame([
            {"cik": "200", "entity_name": "Fund A", "vehicle_type": "interval_fund"},
        ])
        result = check_coverage(df, universe_df=universe,
                                nport_fund_info_df=pd.DataFrame())
        assert len(result) == 1
        assert result.iloc[0]["issue"] == "ok"


# ---------------------------------------------------------------------------
# validate_holdings (orchestrator)
# ---------------------------------------------------------------------------

class TestValidateHoldings:
    def test_full_integration(self, tmp_path):
        df = _make_basic_holdings(n_bdc=15, n_nport=5)
        universe = pd.DataFrame([
            {"cik": "100", "entity_name": "BDC 100", "vehicle_type": "bdc"},
            {"cik": "101", "entity_name": "BDC 101", "vehicle_type": "bdc"},
            {"cik": "102", "entity_name": "BDC 102", "vehicle_type": "bdc"},
            {"cik": "200", "entity_name": "Fund 200", "vehicle_type": "interval_fund"},
            {"cik": "201", "entity_name": "Fund 201", "vehicle_type": "interval_fund"},
        ])

        report_file = tmp_path / "report.csv"
        spot_file = tmp_path / "spot.csv"
        coverage_file = tmp_path / "coverage.csv"
        cross_source_file = tmp_path / "cross_source.csv"
        total_assets_file = tmp_path / "total_assets.csv"
        row_issues_file = tmp_path / "row_issues.csv"
        column_metrics_file = tmp_path / "column_metrics.csv"
        quality_metrics_file = tmp_path / "quality_metrics.csv"
        residual_summary_file = tmp_path / "residual_summary.csv"

        with patch("pipeline.validate_holdings.HOLDINGS_VALIDATION_REPORT_FILE", report_file), \
             patch("pipeline.validate_holdings.HOLDINGS_SPOT_CHECK_FILE", spot_file), \
             patch("pipeline.validate_holdings.HOLDINGS_COVERAGE_FILE", coverage_file), \
             patch("pipeline.validate_holdings.HOLDINGS_CROSS_SOURCE_FILE", cross_source_file), \
             patch("pipeline.validate_holdings.HOLDINGS_TOTAL_ASSETS_FILE", total_assets_file), \
             patch("pipeline.validate_holdings.ROW_VALIDATION_ISSUES_FILE", row_issues_file), \
             patch("pipeline.validate_holdings.COLUMN_QUALITY_METRICS_FILE", column_metrics_file), \
             patch("pipeline.validate_holdings.DATA_QUALITY_METRICS_FILE", quality_metrics_file), \
             patch("pipeline.validate_holdings.VALIDATE_ALL_RESIDUAL_SUMMARY_FILE", residual_summary_file), \
             patch("pipeline.source_reconciliation.run_bdc_source_reconciliation_cached",
                   return_value=(pd.DataFrame(), pd.DataFrame(), pd.DataFrame())):
            reports = validate_holdings(unified_df=df, universe_df=universe)

        assert "spot_check" in reports
        assert "cik_summary" in reports
        assert "aggregate_leaks" in reports
        assert "cross_source_overlap" in reports
        assert "duplicate_holdings" in reports
        assert "coverage" in reports
        assert "row_validation_issues" in reports
        assert "column_quality_metrics" in reports
        assert "data_quality_metrics" in reports
        assert "validate_all_residual_summary" in reports
        assert "fund_strategy_reference" in reports
        assert "fund_strategy_holdings_mix" in reports
        assert "fund_strategy_validation" in reports
        assert "fund_strategy_review_queue" in reports
        assert "fund_strategy_correction_candidates" in reports

        # CSVs should be saved
        assert report_file.exists()
        assert spot_file.exists()
        assert coverage_file.exists()
        assert row_issues_file.exists()
        assert column_metrics_file.exists()
        assert quality_metrics_file.exists()
        assert residual_summary_file.exists()

    def test_returns_empty_dict_when_no_data(self, tmp_path):
        """When unified file doesn't exist and no df provided, returns empty."""
        fake_path = tmp_path / "nonexistent.csv"
        with patch("pipeline.validate_holdings.UNIFIED_HOLDINGS_FILE", fake_path):
            reports = validate_holdings()
        assert reports == {}


# ---------------------------------------------------------------------------
# position purity diagnostics
# ---------------------------------------------------------------------------

class TestPositionPurityDiagnostics:
    def test_subtotal_candidate_flags_aggregate_identifier_only(self):
        df = _make_unified_df([
            {
                "source": "bdc",
                "cik": "0000000100",
                "entity_name": "BDC A",
                "report_date": "2024-03-31",
                "accession_number": "000100-24-000001",
                "issuer_name": "Total Senior Secured Loans",
                "bdc_investment_identifier": "Total Senior Secured Loans",
                "fair_value": "1000000",
            },
            {
                "source": "bdc",
                "cik": "0000000100",
                "entity_name": "BDC A",
                "report_date": "2024-03-31",
                "accession_number": "000100-24-000001",
                "issuer_name": "Total Safety Holdings LLC",
                "bdc_investment_identifier": "Total Safety Holdings LLC - First Lien Loan",
                "instrument_description": "First Lien Loan",
                "fair_value": "2000000",
            },
        ])
        diagnostics, metrics = build_position_purity_diagnostics(df, pd.DataFrame())

        subtotal = diagnostics[diagnostics["issue_family"] == "subtotal_candidate"]
        assert len(subtotal) == 1
        assert subtotal.iloc[0]["issuer_name"] == "Total Senior Secured Loans"
        assert len(df) == 2
        assert int(metrics.iloc[0]["subtotal_candidate_rows"]) == 1

    def test_duplicate_dimension_candidate_requires_same_position_and_facts(self):
        df = _make_unified_df([
            {
                "source": "bdc",
                "cik": "0000000100",
                "entity_name": "BDC A",
                "report_date": "2024-03-31",
                "accession_number": "000100-24-000001",
                "issuer_name": "Acme Corp",
                "instrument_description": "First Lien Term Loan",
                "fair_value": "1000000",
                "cost": "990000",
                "principal_amount": "1000000",
                "bdc_investment_identifier": "Acme Corp - First Lien Term Loan",
                "bdc_dimensions_raw": "axis=AcmeMember|type=DebtMember",
            },
            {
                "source": "bdc",
                "cik": "0000000100",
                "entity_name": "BDC A",
                "report_date": "2024-03-31",
                "accession_number": "000100-24-000001",
                "issuer_name": "Acme Corp",
                "instrument_description": "First Lien Term Loan",
                "fair_value": "1000000",
                "cost": "990000",
                "principal_amount": "1000000",
                "bdc_investment_identifier": "Acme Corp - First Lien Term Loan",
                "bdc_dimensions_raw": "axis=AcmeAltMember|type=DebtMember",
            },
            {
                "source": "bdc",
                "cik": "0000000100",
                "entity_name": "BDC A",
                "report_date": "2024-03-31",
                "accession_number": "000100-24-000001",
                "issuer_name": "Acme Corp",
                "instrument_description": "Second Lien Term Loan",
                "fair_value": "1000000",
                "cost": "990000",
                "principal_amount": "1000000",
                "bdc_investment_identifier": "Acme Corp - Second Lien Term Loan",
                "bdc_dimensions_raw": "axis=AcmeSecondLienMember",
            },
            {
                "source": "bdc",
                "cik": "0000000100",
                "entity_name": "BDC A",
                "report_date": "2024-03-31",
                "accession_number": "000100-24-000001",
                "issuer_name": "Acme Corp",
                "instrument_description": "First Lien Term Loan",
                "fair_value": "1100000",
                "cost": "990000",
                "principal_amount": "1000000",
                "bdc_investment_identifier": "Acme Corp - First Lien Term Loan",
                "bdc_dimensions_raw": "axis=AcmeDifferentFvMember",
            },
        ])
        diagnostics, _ = build_position_purity_diagnostics(df, pd.DataFrame())

        dupes = diagnostics[
            diagnostics["issue_family"] == "duplicate_dimension_candidate"
        ]
        assert len(dupes) == 2
        assert set(dupes["instrument_description"]) == {"First Lien Term Loan"}
        assert set(dupes["fair_value"]) == {"1000000"}

    def test_comparative_period_is_separate_from_duplicate_candidates(self):
        holdings = _make_unified_df([
            {
                "source": "bdc",
                "cik": "0000000100",
                "entity_name": "BDC A",
                "report_date": "2024-06-30",
                "accession_number": "000100-24-000002",
                "issuer_name": "Acme Corp",
                "instrument_description": "First Lien Term Loan",
                "fair_value": "1000000",
                "cost": "990000",
                "principal_amount": "1000000",
                "bdc_investment_identifier": "Acme Corp - First Lien Term Loan",
                "bdc_dimensions_raw": "axis=current",
            },
            {
                "source": "bdc",
                "cik": "0000000100",
                "entity_name": "BDC A",
                "report_date": "2024-06-30",
                "accession_number": "000100-24-000002",
                "issuer_name": "Acme Corp",
                "instrument_description": "First Lien Term Loan",
                "fair_value": "1000000",
                "cost": "990000",
                "principal_amount": "1000000",
                "bdc_investment_identifier": "Acme Corp - First Lien Term Loan",
                "bdc_dimensions_raw": "axis=prior",
            },
        ])
        source = _make_bdc_source([
            {
                "report_date": "2024-06-30",
                "period": "2024-06-30",
                "accession_number": "000100-24-000002",
                "investment_identifier": "Acme Corp - First Lien Term Loan",
                "dimensions_raw": "axis=current",
            },
            {
                "report_date": "2024-06-30",
                "period": "2024-03-31",
                "accession_number": "000100-24-000002",
                "investment_identifier": "Acme Corp - First Lien Term Loan",
                "dimensions_raw": "axis=prior",
            },
        ])
        diagnostics, _ = build_position_purity_diagnostics(holdings, source)

        assert len(diagnostics[diagnostics["issue_family"] == "comparative_period"]) == 1
        assert len(diagnostics[
            diagnostics["issue_family"] == "duplicate_dimension_candidate"
        ]) == 0


# ---------------------------------------------------------------------------
# check_gav_reconciliation
# ---------------------------------------------------------------------------

class TestCheckGavReconciliation:
    def test_basic_reconciliation(self):
        """Holdings FV sum matches fund_financials investments_at_fair_value."""
        holdings = _make_unified_df([
            {"cik": "100", "entity_name": "BDC A", "report_date": "2024-03-31",
             "fair_value": "5000000", "source": "bdc"},
            {"cik": "100", "entity_name": "BDC A", "report_date": "2024-03-31",
             "fair_value": "3000000", "source": "bdc"},
        ])
        ff = pd.DataFrame([{
            "cik": "100", "report_date": "2024-03-31",
            "investments_at_fair_value": "8000000",
            "total_assets": "10000000",
        }])
        result = check_gav_reconciliation(holdings, fund_financials_df=ff)
        assert len(result) == 1
        assert result.iloc[0]["comparison_source"] == "investments_at_fair_value"
        assert result.iloc[0]["holdings_source"] == "bdc"
        assert result.iloc[0]["holdings_scope"] == "bdc_schedule"
        assert result.iloc[0]["denominator_scope"] == "investment_fair_value"
        assert result.iloc[0]["gav_rule_id"] == "GAV_BDC01"
        assert result.iloc[0]["reconciliation_status"] == "PASS"
        assert result.iloc[0]["comparison_confidence"] == "STRONG"
        assert result.iloc[0]["blocks_verified"] == False
        ratio = float(result.iloc[0]["gav_ratio"])
        assert abs(ratio - 1.0) < 0.01
        assert result.iloc[0]["flag"] == "ok"

    def test_falls_back_to_total_assets(self):
        """When investments_at_fair_value is missing, uses total_assets."""
        holdings = _make_unified_df([
            {"cik": "100", "entity_name": "BDC A", "report_date": "2024-03-31",
             "fair_value": "5000000", "source": "bdc"},
        ])
        ff = pd.DataFrame([{
            "cik": "100", "report_date": "2024-03-31",
            "investments_at_fair_value": "",
            "total_assets": "10000000",
        }])
        result = check_gav_reconciliation(holdings, fund_financials_df=ff)
        assert len(result) == 1
        assert result.iloc[0]["comparison_source"] == "total_assets_companyfacts"
        assert result.iloc[0]["denominator_scope"] == "full_fund_assets_proxy"
        assert result.iloc[0]["comparison_confidence"] == "MODERATE"
        ratio = float(result.iloc[0]["gav_ratio"])
        assert abs(ratio - 0.5) < 0.01

    def test_flags_over_coverage(self):
        """Holdings FV >> comparison -> over_coverage flag."""
        holdings = _make_unified_df([
            {"cik": "100", "entity_name": "BDC A", "report_date": "2024-03-31",
             "fair_value": "15000000", "source": "bdc"},
        ])
        ff = pd.DataFrame([{
            "cik": "100", "report_date": "2024-03-31",
            "investments_at_fair_value": "10000000",
            "total_assets": "",
        }])
        result = check_gav_reconciliation(holdings, fund_financials_df=ff)
        assert result.iloc[0]["flag"] == "over_coverage"

    def test_flags_under_coverage(self):
        """Holdings FV << comparison -> under_coverage flag."""
        holdings = _make_unified_df([
            {"cik": "100", "entity_name": "BDC A", "report_date": "2024-03-31",
             "fair_value": "1000000", "source": "bdc"},
        ])
        ff = pd.DataFrame([{
            "cik": "100", "report_date": "2024-03-31",
            "investments_at_fair_value": "50000000",
            "total_assets": "",
        }])
        result = check_gav_reconciliation(holdings, fund_financials_df=ff)
        assert result.iloc[0]["flag"] == "under_coverage"

    def test_bdc_source_reconciliation_distinguishes_non_indexable_source_fv(self):
        """Source FV can reconcile even when indexable holdings remain undercovered."""
        holdings = _make_unified_df([
            {"cik": "100", "entity_name": "BDC A", "report_date": "2024-03-31",
             "fair_value": "1000000", "source": "bdc"},
        ])
        ff = pd.DataFrame([{
            "cik": "100", "report_date": "2024-03-31",
            "investments_at_fair_value": "10000000",
            "total_assets": "",
        }])
        bdc_source = pd.DataFrame([
            {
                "cik": "100",
                "report_date": "2024-03-31",
                "period": "2024-03-31",
                "fair_value": "1000000",
                "accession_number": "acc-001",
                "form_type": "10-Q",
                "filing_date": "2024-05-01",
            },
            {
                "cik": "100",
                "report_date": "2024-03-31",
                "period": "2024-03-31",
                "fair_value": "9000000",
                "accession_number": "acc-001",
                "form_type": "10-Q",
                "filing_date": "2024-05-01",
            },
        ])

        result = check_gav_reconciliation(
            holdings,
            fund_financials_df=ff,
            bdc_source_df=bdc_source,
        )

        row = result.iloc[0]
        assert row["flag"] == "under_coverage"
        assert row["bdc_source_reconciliation_flag"] == "ok"
        assert row["gav_evidence_scope"] == "source_fv_present_not_indexable"
        assert float(row["bdc_source_raw_fv"]) == 10000000.0
        assert float(row["bdc_source_aggregate_filtered_fv"]) == 0.0
        assert float(row["bdc_source_non_indexable_filtered_fv"]) == 9000000.0
        assert row["comparison_denominator_source"] == "investments_at_fair_value"
        assert row["comparison_denominator_scope"] == "investment_fair_value"
        assert float(row["bdc_source_reconciliation_ratio"]) == 1.0
        assert int(row["bdc_source_reconciliation_rows"]) == 2

    def test_bdc_source_reconciliation_separates_aggregate_filtered_fv(self):
        holdings = _make_unified_df([
            {"cik": "100", "entity_name": "BDC A", "report_date": "2024-03-31",
             "fair_value": "1000000", "source": "bdc"},
        ])
        ff = pd.DataFrame([{
            "cik": "100", "report_date": "2024-03-31",
            "investments_at_fair_value": "6000000",
            "total_assets": "",
        }])
        bdc_source = pd.DataFrame([
            {
                "cik": "100", "report_date": "2024-03-31", "period": "2024-03-31",
                "investment_identifier": "Acme Corp - First Lien Term Loan",
                "fair_value": "1000000", "accession_number": "acc-001",
                "form_type": "10-Q", "filing_date": "2024-05-01",
            },
            {
                "cik": "100", "report_date": "2024-03-31", "period": "2024-03-31",
                "investment_identifier": "Total Debt Investments, First Lien Debt",
                "fair_value": "5000000", "accession_number": "acc-001",
                "form_type": "10-Q", "filing_date": "2024-05-01",
            },
        ])

        result = check_gav_reconciliation(
            holdings,
            fund_financials_df=ff,
            bdc_source_df=bdc_source,
        )

        row = result.iloc[0]
        assert float(row["bdc_source_raw_fv"]) == 6000000.0
        assert float(row["bdc_source_aggregate_filtered_fv"]) == 5000000.0
        assert float(row["bdc_source_reconciliation_fv"]) == 1000000.0
        assert row["bdc_source_reconciliation_flag"] == "under_coverage"

    def test_nport_non_indexable_denominator_is_not_ordinary_undercoverage(self):
        holdings = _make_unified_df([
            {"cik": "0001547580", "entity_name": "Victory Portfolios II",
             "report_date": "2024-03-31", "fair_value": "1000000", "source": "nport"},
        ])
        nport_fi = pd.DataFrame([{
            "cik": "1547580", "report_date": "2024-03-31",
            "total_assets": "20000000",
        }])

        result = check_gav_reconciliation(
            holdings,
            fund_financials_df=pd.DataFrame(),
            nport_fund_info_df=nport_fi,
        )

        row = result.iloc[0]
        assert row["gav_rule_id"] == "GAV_NPORT01"
        assert row["flag"] == "non_indexable_denominator"
        assert row["gav_evidence_scope"] == "non_indexable_denominator"

    def test_no_comparison_flag(self):
        """When no fund_financials data, flag is no_comparison."""
        holdings = _make_unified_df([
            {"cik": "100", "entity_name": "BDC A", "report_date": "2024-03-31",
             "fair_value": "5000000", "source": "bdc"},
        ])
        result = check_gav_reconciliation(
            holdings, fund_financials_df=pd.DataFrame(),
            nport_fund_info_df=pd.DataFrame(),
        )
        assert len(result) == 1
        assert result.iloc[0]["flag"] == "no_comparison"
        assert result.iloc[0]["reconciliation_status"] == "SKIP"
        assert result.iloc[0]["blocks_verified"] == True

    def test_nport_fallback(self):
        """Falls back to N-PORT total_assets when no fund_financials."""
        holdings = _make_unified_df([
            {"cik": "0000000100", "entity_name": "Fund A",
             "report_date": "2024-03-31",
             "fair_value": "5000000", "source": "nport"},
        ])
        nport_fi = pd.DataFrame([{
            "cik": "100", "report_date": "2024-03-31",
            "total_assets": "6000000",
        }])
        result = check_gav_reconciliation(
            holdings, fund_financials_df=pd.DataFrame(),
            nport_fund_info_df=nport_fi,
        )
        assert len(result) == 1
        assert result.iloc[0]["comparison_source"] == "total_assets_nport"
        assert result.iloc[0]["holdings_source"] == "nport"
        assert result.iloc[0]["holdings_scope"] == "nport_private_markets_filter"
        assert result.iloc[0]["denominator_scope"] == "full_fund_assets_proxy"
        assert result.iloc[0]["gav_rule_id"] == "GAV_NPORT01"

    def test_ex_sub_ratio_excludes_subsidiary(self):
        """Adjusted ratio excludes is_subsidiary=1 positions from numerator."""
        holdings = _make_unified_df([
            # Parent position
            {"cik": "100", "entity_name": "BDC A", "report_date": "2024-03-31",
             "fair_value": "5000000", "source": "bdc", "is_subsidiary": "0"},
            # Subsidiary duplicate
            {"cik": "100", "entity_name": "BDC A", "report_date": "2024-03-31",
             "fair_value": "3000000", "source": "bdc", "is_subsidiary": "1"},
        ])
        ff = pd.DataFrame([{
            "cik": "100", "report_date": "2024-03-31",
            "investments_at_fair_value": "5000000",
            "total_assets": "6000000",
        }])
        result = check_gav_reconciliation(holdings, fund_financials_df=ff)
        assert len(result) == 1
        # Raw ratio = (5M+3M)/5M = 1.6
        raw_ratio = float(result.iloc[0]["gav_ratio"])
        assert abs(raw_ratio - 1.6) < 0.01
        # Adjusted ratio = 5M/5M = 1.0 (excludes subsidiary)
        adj_ratio = float(result.iloc[0]["gav_ratio_adjusted"])
        assert abs(adj_ratio - 1.0) < 0.01
        assert result.iloc[0]["flag"] == "ok"
        assert int(result.iloc[0]["has_subsidiary_positions"]) == 1

    def test_unreliable_inv_fv_falls_back(self):
        """When inv_fv is wildly different from total_assets, use total_assets."""
        holdings = _make_unified_df([
            {"cik": "100", "entity_name": "BDC A", "report_date": "2024-03-31",
             "fair_value": "5000000", "source": "bdc"},
        ])
        ff = pd.DataFrame([{
            "cik": "100", "report_date": "2024-03-31",
            # inv_fv is 66x total_assets (unreliable, like Kayne)
            "investments_at_fair_value": "330000000",
            "total_assets": "5000000",
        }])
        result = check_gav_reconciliation(holdings, fund_financials_df=ff)
        assert len(result) == 1
        # Should fall back to total_assets, not use unreliable inv_fv
        assert result.iloc[0]["comparison_source"] == "total_assets_companyfacts"
        ratio = float(result.iloc[0]["gav_ratio"])
        assert abs(ratio - 1.0) < 0.01

    def test_raw_source_corroboration_overrides_gate_when_source_matches_inv_fv(self):
        """A suspect inv_fv denominator needs raw source FV corroboration."""
        holdings = _make_unified_df([
            {"cik": "100", "entity_name": "BDC A", "report_date": "2024-03-31",
             "fair_value": "26000000", "source": "bdc"},
        ])
        ff = pd.DataFrame([{
            "cik": "100", "report_date": "2024-03-31",
            # inv_fv is only 2% of total_assets (gate fires)
            # but holdings sum matches inv_fv exactly
            "investments_at_fair_value": "26000000",
            "total_assets": "1300000000",
        }])
        bdc_source = pd.DataFrame([{
            "cik": "100",
            "report_date": "2024-03-31",
            "period": "2024-03-31",
            "fair_value": "26000000",
            "accession_number": "acc-001",
            "form_type": "10-Q",
            "filing_date": "2024-05-01",
        }])
        result = check_gav_reconciliation(
            holdings,
            fund_financials_df=ff,
            bdc_source_df=bdc_source,
        )
        assert len(result) == 1
        assert result.iloc[0]["comparison_source"] == "investments_at_fair_value"
        ratio = float(result.iloc[0]["gav_ratio"])
        assert abs(ratio - 1.0) < 0.01

    def test_holdings_only_corroboration_does_not_override_suspect_inv_fv(self):
        holdings = _make_unified_df([
            {"cik": "100", "entity_name": "BDC A", "report_date": "2024-03-31",
             "fair_value": "26000000", "source": "bdc"},
        ])
        ff = pd.DataFrame([{
            "cik": "100", "report_date": "2024-03-31",
            "investments_at_fair_value": "26000000",
            "total_assets": "1300000000",
        }])
        result = check_gav_reconciliation(holdings, fund_financials_df=ff)
        assert result.iloc[0]["comparison_source"] == "total_assets_companyfacts"

    def test_corroboration_does_not_override_when_holdings_disagree(self):
        """When inv_fv/total_assets fails the gate AND holdings sum does NOT
        corroborate inv_fv, fall back to total_assets (e.g. Kayne subset)."""
        holdings = _make_unified_df([
            {"cik": "100", "entity_name": "BDC A", "report_date": "2024-03-31",
             "fair_value": "430000000", "source": "bdc"},
        ])
        ff = pd.DataFrame([{
            "cik": "100", "report_date": "2024-03-31",
            # inv_fv captures only a subset; holdings >> inv_fv
            "investments_at_fair_value": "14000000",
            "total_assets": "466000000",
        }])
        result = check_gav_reconciliation(holdings, fund_financials_df=ff)
        assert len(result) == 1
        # holdings_sum/inv_fv = 430M/14M = 30.7 (outside 0.3-5.0)
        # Should fall back to total_assets
        assert result.iloc[0]["comparison_source"] == "total_assets_companyfacts"
        ratio = float(result.iloc[0]["gav_ratio"])
        assert abs(ratio - 0.923) < 0.01

    def test_adjusted_flag_uses_adjusted_ratio(self):
        """Flag uses adjusted ratio when subsidiary positions exist."""
        holdings = _make_unified_df([
            # Parent: 5M
            {"cik": "100", "entity_name": "BDC A", "report_date": "2024-03-31",
             "fair_value": "5000000", "source": "bdc", "is_subsidiary": "0"},
            # Subsidiary: 8M (makes raw total 13M, over_coverage raw)
            {"cik": "100", "entity_name": "BDC A", "report_date": "2024-03-31",
             "fair_value": "8000000", "source": "bdc", "is_subsidiary": "1"},
        ])
        ff = pd.DataFrame([{
            "cik": "100", "report_date": "2024-03-31",
            "investments_at_fair_value": "5500000",
            "total_assets": "6000000",
        }])
        result = check_gav_reconciliation(holdings, fund_financials_df=ff)
        # Raw ratio = 13M/5.5M = 2.36 -> would be over_coverage
        # Adjusted ratio = 5M/5.5M = 0.91 -> ok
        assert result.iloc[0]["flag"] == "ok"
        adj_ratio = float(result.iloc[0]["gav_ratio_adjusted"])
        assert abs(adj_ratio - 0.909) < 0.01

    def test_no_subsidiary_passthrough(self):
        """When no subsidiary positions, adjusted ratio equals raw ratio."""
        holdings = _make_unified_df([
            {"cik": "100", "entity_name": "BDC A", "report_date": "2024-03-31",
             "fair_value": "5000000", "source": "bdc", "is_subsidiary": "0"},
            {"cik": "100", "entity_name": "BDC A", "report_date": "2024-03-31",
             "fair_value": "3000000", "source": "bdc", "is_subsidiary": "0"},
        ])
        ff = pd.DataFrame([{
            "cik": "100", "report_date": "2024-03-31",
            "investments_at_fair_value": "8000000",
            "total_assets": "10000000",
        }])
        result = check_gav_reconciliation(holdings, fund_financials_df=ff)
        raw_ratio = float(result.iloc[0]["gav_ratio"])
        adj_ratio = float(result.iloc[0]["gav_ratio_adjusted"])
        assert abs(raw_ratio - adj_ratio) < 0.001
        assert int(result.iloc[0]["has_subsidiary_positions"]) == 0


# ---------------------------------------------------------------------------
# check_pct_of_net_assets_sum
# ---------------------------------------------------------------------------

class TestCheckPctOfNetAssetsSum:
    def test_normal_sum(self):
        """10 BDC positions with pct=12% each -> sum=120%, flag=ok."""
        rows = []
        for i in range(10):
            rows.append({
                "source": "bdc", "cik": "100", "entity_name": "BDC A",
                "issuer_name": f"Company {i}",
                "fair_value": "1000000",
                "pct_of_net_assets": "12.0",
                "report_date": "2024-03-31",
            })
        df = _make_unified_df(rows)
        result = check_pct_of_net_assets_sum(df)
        assert len(result) == 1
        assert abs(float(result.iloc[0]["pct_sum"]) - 120.0) < 0.1
        assert result.iloc[0]["flag"] == "ok"

    def test_high_sum_subtotal_leak(self):
        """Positions + subtotal row with pct -> sum >200, flag=high_pct_sum."""
        rows = []
        # 8 normal positions with 15% each = 120%
        for i in range(8):
            rows.append({
                "source": "bdc", "cik": "100", "entity_name": "BDC A",
                "issuer_name": f"Company {i}",
                "fair_value": "1000000",
                "pct_of_net_assets": "15.0",
                "report_date": "2024-03-31",
            })
        # Subtotal row that leaked through with 120%
        rows.append({
            "source": "bdc", "cik": "100", "entity_name": "BDC A",
            "issuer_name": "Total First Lien",
            "fair_value": "8000000",
            "pct_of_net_assets": "120.0",
            "report_date": "2024-03-31",
        })
        df = _make_unified_df(rows)
        result = check_pct_of_net_assets_sum(df)
        assert len(result) == 1
        assert float(result.iloc[0]["pct_sum"]) > 200
        assert result.iloc[0]["flag"] == "high_pct_sum"

    def test_low_sum(self):
        """5 positions with pct=8% each -> sum=40%, flag=low_pct_sum."""
        rows = []
        for i in range(5):
            rows.append({
                "source": "bdc", "cik": "100", "entity_name": "BDC A",
                "issuer_name": f"Company {i}",
                "fair_value": "500000",
                "pct_of_net_assets": "8.0",
                "report_date": "2024-03-31",
            })
        df = _make_unified_df(rows)
        result = check_pct_of_net_assets_sum(df)
        assert len(result) == 1
        assert float(result.iloc[0]["pct_sum"]) < 50
        assert result.iloc[0]["flag"] == "low_pct_sum"

    def test_nport_excluded(self):
        """N-PORT positions are ignored (no pct_of_net_assets typically)."""
        rows = []
        for i in range(10):
            rows.append({
                "source": "nport", "cik": "200", "entity_name": "Fund A",
                "issuer_name": f"Borrower {i}",
                "fair_value": "1000000",
                "pct_of_net_assets": "10.0",
                "report_date": "2024-06-30",
            })
        df = _make_unified_df(rows)
        result = check_pct_of_net_assets_sum(df)
        assert len(result) == 0

    def test_empty_input(self):
        df = _make_unified_df([])
        result = check_pct_of_net_assets_sum(df)
        assert len(result) == 0
        assert "flag" in result.columns


# ---------------------------------------------------------------------------
# check_position_count_stability
# ---------------------------------------------------------------------------

class TestCheckPositionCountStability:
    def test_stable_count(self):
        """Same CIK with 50, 52, 48 positions -> all ok."""
        rows = []
        for report_date, count in [("2024-03-31", 50), ("2024-06-30", 52), ("2024-09-30", 48)]:
            for i in range(count):
                rows.append({
                    "source": "bdc", "cik": "100", "entity_name": "BDC A",
                    "issuer_name": f"Company {i}",
                    "fair_value": "1000000",
                    "report_date": report_date,
                })
        df = _make_unified_df(rows)
        result = check_position_count_stability(df)
        # 2 transitions: Q1->Q2, Q2->Q3
        assert len(result) == 2
        assert all(result["flag"] == "ok")

    def test_unstable_jump(self):
        """50 then 150 positions -> flag=unstable_count."""
        rows = []
        for i in range(50):
            rows.append({
                "source": "bdc", "cik": "100", "entity_name": "BDC A",
                "issuer_name": f"Company {i}",
                "fair_value": "1000000",
                "report_date": "2024-03-31",
            })
        for i in range(150):
            rows.append({
                "source": "bdc", "cik": "100", "entity_name": "BDC A",
                "issuer_name": f"Company {i}",
                "fair_value": "1000000",
                "report_date": "2024-06-30",
            })
        df = _make_unified_df(rows)
        result = check_position_count_stability(df)
        assert len(result) == 1
        assert result.iloc[0]["flag"] == "unstable_count"

    def test_count_fv_divergence(self):
        """Count doubles but FV stable -> flag=count_fv_divergence."""
        rows = []
        # Q1: 50 positions, each $1M -> total $50M
        for i in range(50):
            rows.append({
                "source": "bdc", "cik": "100", "entity_name": "BDC A",
                "issuer_name": f"Company {i}",
                "fair_value": "1000000",
                "report_date": "2024-03-31",
            })
        # Q2: 110 positions, each ~$455K -> total ~$50M (FV stable, count >2x)
        for i in range(110):
            rows.append({
                "source": "bdc", "cik": "100", "entity_name": "BDC A",
                "issuer_name": f"Company {i}",
                "fair_value": "454545",
                "report_date": "2024-06-30",
            })
        df = _make_unified_df(rows)
        result = check_position_count_stability(df)
        assert len(result) == 1
        assert result.iloc[0]["flag"] == "count_fv_divergence"

    def test_single_period(self):
        """CIK with one period only -> no output."""
        rows = []
        for i in range(20):
            rows.append({
                "source": "bdc", "cik": "100", "entity_name": "BDC A",
                "issuer_name": f"Company {i}",
                "fair_value": "1000000",
                "report_date": "2024-03-31",
            })
        df = _make_unified_df(rows)
        result = check_position_count_stability(df)
        assert len(result) == 0

    def test_empty_input(self):
        df = _make_unified_df([])
        result = check_position_count_stability(df)
        assert len(result) == 0
        assert "flag" in result.columns


# ---------------------------------------------------------------------------
# check_income_yield_consistency
# ---------------------------------------------------------------------------

class TestCheckIncomeYieldConsistency:
    def test_normal_yield(self, tmp_path):
        """yield ratio ~1.1 -> ok."""
        fee_csv = tmp_path / "fee_uplift.csv"
        fee_csv.write_text(
            "cik,total_income_yield,median_all_in_coupon\n"
            "100,0.11,0.10\n"
        )
        result = check_income_yield_consistency(fee_uplift_path=fee_csv)
        assert len(result) == 1
        assert result.iloc[0]["flag"] == "ok"
        ratio = float(result.iloc[0]["yield_ratio"])
        assert abs(ratio - 1.1) < 0.01

    def test_high_yield(self, tmp_path):
        """yield ratio 3.0 -> yield_outlier."""
        fee_csv = tmp_path / "fee_uplift.csv"
        fee_csv.write_text(
            "cik,total_income_yield,median_all_in_coupon\n"
            "100,0.30,0.10\n"
        )
        result = check_income_yield_consistency(fee_uplift_path=fee_csv)
        assert len(result) == 1
        assert result.iloc[0]["flag"] == "yield_outlier"

    def test_no_fee_uplift_file(self, tmp_path):
        """File missing -> returns empty DataFrame."""
        fake_path = tmp_path / "nonexistent.csv"
        result = check_income_yield_consistency(fee_uplift_path=fake_path)
        assert len(result) == 0
        assert "flag" in result.columns

    def test_empty_input(self, tmp_path):
        """Empty fee_uplift file -> returns empty DataFrame."""
        fee_csv = tmp_path / "fee_uplift.csv"
        fee_csv.write_text("cik,total_income_yield,median_all_in_coupon\n")
        result = check_income_yield_consistency(fee_uplift_path=fee_csv)
        assert len(result) == 0
