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
    spot_check_top_ciks,
    summarize_classification_by_cik,
    validate_holdings,
)


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

        with patch("pipeline.validate_holdings.HOLDINGS_VALIDATION_REPORT_FILE", report_file), \
             patch("pipeline.validate_holdings.HOLDINGS_SPOT_CHECK_FILE", spot_file), \
             patch("pipeline.validate_holdings.HOLDINGS_COVERAGE_FILE", coverage_file), \
             patch("pipeline.validate_holdings.HOLDINGS_CROSS_SOURCE_FILE", cross_source_file), \
             patch("pipeline.validate_holdings.HOLDINGS_TOTAL_ASSETS_FILE", total_assets_file):
            reports = validate_holdings(unified_df=df, universe_df=universe)

        assert "spot_check" in reports
        assert "cik_summary" in reports
        assert "aggregate_leaks" in reports
        assert "cross_source_overlap" in reports
        assert "duplicate_holdings" in reports
        assert "coverage" in reports

        # CSVs should be saved
        assert report_file.exists()
        assert spot_file.exists()
        assert coverage_file.exists()

    def test_returns_empty_dict_when_no_data(self, tmp_path):
        """When unified file doesn't exist and no df provided, returns empty."""
        fake_path = tmp_path / "nonexistent.csv"
        with patch("pipeline.validate_holdings.UNIFIED_HOLDINGS_FILE", fake_path):
            reports = validate_holdings()
        assert reports == {}
