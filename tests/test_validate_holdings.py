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
        "ROW_VALIDATION_ISSUES_FILE": "row_validation_issues.csv",
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

        with patch("pipeline.validate_holdings.HOLDINGS_VALIDATION_REPORT_FILE", report_file), \
             patch("pipeline.validate_holdings.HOLDINGS_SPOT_CHECK_FILE", spot_file), \
             patch("pipeline.validate_holdings.HOLDINGS_COVERAGE_FILE", coverage_file), \
             patch("pipeline.validate_holdings.HOLDINGS_CROSS_SOURCE_FILE", cross_source_file), \
             patch("pipeline.validate_holdings.HOLDINGS_TOTAL_ASSETS_FILE", total_assets_file), \
             patch("pipeline.validate_holdings.ROW_VALIDATION_ISSUES_FILE", row_issues_file), \
             patch("pipeline.validate_holdings.COLUMN_QUALITY_METRICS_FILE", column_metrics_file), \
             patch("pipeline.validate_holdings.DATA_QUALITY_METRICS_FILE", quality_metrics_file):
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

        # CSVs should be saved
        assert report_file.exists()
        assert spot_file.exists()
        assert coverage_file.exists()
        assert row_issues_file.exists()
        assert column_metrics_file.exists()
        assert quality_metrics_file.exists()

    def test_returns_empty_dict_when_no_data(self, tmp_path):
        """When unified file doesn't exist and no df provided, returns empty."""
        fake_path = tmp_path / "nonexistent.csv"
        with patch("pipeline.validate_holdings.UNIFIED_HOLDINGS_FILE", fake_path):
            reports = validate_holdings()
        assert reports == {}


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
        assert float(row["bdc_source_reconciliation_ratio"]) == 1.0
        assert int(row["bdc_source_reconciliation_rows"]) == 2

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
        assert result.iloc[0]["denominator_scope"] == "full_fund_assets"
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

    def test_corroboration_overrides_gate_when_holdings_match_inv_fv(self):
        """When inv_fv/total_assets fails the gate but holdings sum corroborates
        inv_fv (ratio 0.3-5.0x), use inv_fv anyway (e.g. NEWT bank/BDC hybrid)."""
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
        result = check_gav_reconciliation(holdings, fund_financials_df=ff)
        assert len(result) == 1
        # Should use inv_fv due to corroboration, not total_assets
        assert result.iloc[0]["comparison_source"] == "investments_at_fair_value"
        ratio = float(result.iloc[0]["gav_ratio"])
        assert abs(ratio - 1.0) < 0.01

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
