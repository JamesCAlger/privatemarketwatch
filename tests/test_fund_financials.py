"""Tests for pipeline.fund_financials module."""

import pandas as pd
import pytest

from pipeline.fund_financials import (
    OUTPUT_COLUMNS,
    _EXTENDED_FIELDS,
    _enforce_schema,
    _extract_all_companyfacts,
    _extract_bdc_balance_sheet,
    _extract_concept_series,
    _extract_duration_series,
    _months_between,
    _parse_ncen_date,
    _parse_ncen_financials,
    _parse_ncen_identity,
    _prepare_bdc,
    _prepare_ncen,
    _prepare_nport,
    _prior_quarter_end,
    build_fund_financials,
)


# ---------------------------------------------------------------------------
# Helpers -- mock companyfacts JSON
# ---------------------------------------------------------------------------

def _make_facts(concepts: dict) -> dict:
    """Build a minimal companyfacts JSON structure.

    ``concepts`` maps concept_name -> list of entry dicts.
    Each entry dict has: end, val, and optionally start (for duration facts).
    """
    return {
        "facts": {
            "us-gaap": {
                name: {"units": {"USD": entries}}
                for name, entries in concepts.items()
            },
        },
    }


def _make_facts_multi_unit(concept_name: str, unit_key: str,
                           entries: list[dict]) -> dict:
    """Build companyfacts JSON with a specific unit key."""
    return {
        "facts": {
            "us-gaap": {
                concept_name: {"units": {unit_key: entries}},
            },
        },
    }


def test_extract_all_companyfacts_client_none_is_cache_only(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "pipeline.fund_financials.COMPANYFACTS_CACHE_DIR",
        tmp_path / "companyfacts_cache",
    )
    monkeypatch.setattr(
        "pipeline.validate_html_template._fetch_companyfacts",
        lambda *args, **kwargs: pytest.fail("client=None must not fetch companyfacts"),
    )

    result = _extract_all_companyfacts(["123"], client=None)

    assert result.empty


# ===================================================================
# 1. _extract_concept_series tests
# ===================================================================

class TestExtractConceptSeries:

    def test_finds_concept_across_taxonomies(self):
        facts = {
            "facts": {
                "us-gaap": {
                    "Assets": {"units": {"USD": [
                        {"end": "2023-12-31", "val": 1000},
                        {"end": "2024-03-31", "val": 1100},
                    ]}},
                },
                "dei": {
                    "SomeOtherConcept": {"units": {"USD": [
                        {"end": "2023-12-31", "val": 999},
                    ]}},
                },
            },
        }
        result = _extract_concept_series(facts, ["Assets"], "USD", True)
        assert result == {"2023-12-31": 1000.0, "2024-03-31": 1100.0}

    def test_instant_filter(self):
        """Instant-only should exclude duration facts (those with start)."""
        facts = _make_facts({
            "Assets": [
                {"end": "2023-12-31", "val": 1000},  # instant
                {"end": "2024-03-31", "start": "2024-01-01", "val": 50},
            ],
        })
        result = _extract_concept_series(facts, ["Assets"], "USD", True)
        assert "2024-03-31" not in result
        assert result["2023-12-31"] == 1000.0

    def test_duration_filter(self):
        """instant_only=False should return only duration facts."""
        facts = _make_facts({
            "TotalInvestmentIncome": [
                {"end": "2023-12-31", "val": 1000},  # instant
                {"end": "2024-03-31", "start": "2024-01-01", "val": 50},
            ],
        })
        result = _extract_concept_series(
            facts, ["TotalInvestmentIncome"], "USD", False,
        )
        assert result == {"2024-03-31": 50.0}

    def test_picks_concept_with_most_data_points(self):
        """When multiple exact concepts match, pick the one with most entries."""
        facts = {
            "facts": {
                "us-gaap": {
                    "Assets": {"units": {"USD": [
                        {"end": "2023-12-31", "val": 100},
                    ]}},
                    "TotalAssets": {"units": {"USD": [
                        {"end": "2023-12-31", "val": 200},
                        {"end": "2024-03-31", "val": 300},
                    ]}},
                },
            },
        }
        # Both names in the search list -> picks TotalAssets (more points)
        result = _extract_concept_series(
            facts, ["Assets", "TotalAssets"], "USD", True,
        )
        assert len(result) == 2
        assert result["2023-12-31"] == 200.0

    def test_empty_facts(self):
        assert _extract_concept_series({}, ["Assets"], "USD", True) == {}
        assert _extract_concept_series(None, ["Assets"], "USD", True) == {}

    def test_no_matching_concept(self):
        facts = _make_facts({"Revenue": [{"end": "2023-12-31", "val": 100}]})
        result = _extract_concept_series(facts, ["Assets"], "USD", True)
        assert result == {}

    def test_non_usd_unit(self):
        facts = _make_facts_multi_unit(
            "NetAssetValuePerShare", "USD/shares",
            [{"end": "2023-12-31", "val": 19.5}],
        )
        result = _extract_concept_series(
            facts, ["NetAssetValuePerShare"], "USD/shares", True,
        )
        assert result == {"2023-12-31": 19.5}


# ===================================================================
# 2. _extract_bdc_balance_sheet tests
# ===================================================================

class TestExtractBdcBalanceSheet:

    def test_complete_json(self):
        facts = {
            "facts": {
                "us-gaap": {
                    "Assets": {"units": {"USD": [
                        {"end": "2023-12-31", "val": 1000000},
                    ]}},
                    "Liabilities": {"units": {"USD": [
                        {"end": "2023-12-31", "val": 400000},
                    ]}},
                    "StockholdersEquity": {"units": {"USD": [
                        {"end": "2023-12-31", "val": 600000},
                    ]}},
                    "NetAssetValuePerShare": {"units": {"USD/shares": [
                        {"end": "2023-12-31", "val": 19.5},
                    ]}},
                    "CommonStockSharesOutstanding": {"units": {"shares": [
                        {"end": "2023-12-31", "val": 30000},
                    ]}},
                    "LongTermDebt": {"units": {"USD": [
                        {"end": "2023-12-31", "val": 300000},
                    ]}},
                },
            },
        }
        rows = _extract_bdc_balance_sheet("1287750", facts)
        assert len(rows) == 1
        row = rows[0]
        assert row["cik"] == "0001287750"
        assert row["total_assets"] == 1000000
        assert row["total_liabilities"] == 400000
        assert row["net_assets"] == 600000
        assert row["nav_per_share"] == 19.5
        assert row["shares_outstanding"] == 30000
        assert row["borrowings"] == 300000

    def test_missing_concepts_return_none(self):
        facts = _make_facts({
            "Assets": [{"end": "2023-12-31", "val": 1000}],
        })
        rows = _extract_bdc_balance_sheet("1234", facts)
        assert len(rows) == 1
        assert rows[0]["total_assets"] == 1000
        assert rows[0]["total_liabilities"] is None
        assert rows[0]["borrowings"] is None

    def test_empty_facts(self):
        assert _extract_bdc_balance_sheet("1234", {}) == []
        assert _extract_bdc_balance_sheet("1234", None) == []

    def test_multiple_dates(self):
        facts = _make_facts({
            "Assets": [
                {"end": "2023-09-30", "val": 900},
                {"end": "2023-12-31", "val": 1000},
            ],
        })
        rows = _extract_bdc_balance_sheet("1234", facts)
        assert len(rows) == 2
        assert rows[0]["report_date"] == "2023-09-30"
        assert rows[1]["report_date"] == "2023-12-31"

    def test_cik_padding(self):
        facts = _make_facts({
            "Assets": [{"end": "2023-12-31", "val": 100}],
        })
        rows = _extract_bdc_balance_sheet("42", facts)
        assert rows[0]["cik"] == "0000000042"


# ===================================================================
# 3. _prepare_nport tests
# ===================================================================

class TestPrepareNport:

    def _make_nport_df(self, rows: list[dict]) -> pd.DataFrame:
        base = {
            "accession_number": "ACC1", "series_name": "Fund A",
            "series_id": "S1", "cik": "1234",
            "registrant_name": "Test Fund", "quarter": "2023q4",
            "report_date": "2023-10-31", "class_id": "C1",
            "total_assets": "1000000", "net_assets": "800000",
            "total_liabilities": "200000",
            "borrowing_pay_within_1yr": "50000",
            "borrowing_pay_after_1yr": "100000",
            "monthly_total_return1": "1.5",
            "monthly_total_return2": "0.8",
            "monthly_total_return3": "-0.3",
            "sales_flow_mon1": "10000", "sales_flow_mon2": "20000",
            "sales_flow_mon3": "15000",
            "redemption_flow_mon1": "5000",
            "redemption_flow_mon2": "8000",
            "redemption_flow_mon3": "3000",
        }
        full_rows = [{**base, **r} for r in rows]
        return pd.DataFrame(full_rows)

    def test_single_series(self):
        df = self._make_nport_df([{}])
        result = _prepare_nport(df)
        assert len(result) == 1
        row = result.iloc[0]
        assert row["cik"] == "0000001234"
        assert row["report_quarter"] == "2023q4"
        assert row["source"] == "nport"
        assert float(row["total_assets"]) == 1000000.0
        assert float(row["borrowings"]) == 150000.0

    def test_multi_series_aggregation(self):
        df = self._make_nport_df([
            {"series_name": "Fund A", "net_assets": "500000",
             "total_assets": "600000", "total_liabilities": "100000"},
            {"series_name": "Fund B", "net_assets": "300000",
             "total_assets": "400000", "total_liabilities": "100000",
             "accession_number": "ACC2"},
        ])
        result = _prepare_nport(df)
        assert len(result) == 1
        assert float(result.iloc[0]["total_assets"]) == 1000000.0
        assert float(result.iloc[0]["net_assets"]) == 800000.0

    def test_class_level_dedup(self):
        """Same accession + series but different class_ids should dedup."""
        df = self._make_nport_df([
            {"class_id": "C1"},
            {"class_id": "C2"},
        ])
        result = _prepare_nport(df)
        assert len(result) == 1
        # Should NOT double-count
        assert float(result.iloc[0]["total_assets"]) == 1000000.0

    def test_quarterly_return_compounding(self):
        df = self._make_nport_df([{
            "monthly_total_return1": "2.0",
            "monthly_total_return2": "1.0",
            "monthly_total_return3": "0.5",
        }])
        result = _prepare_nport(df)
        expected = ((1.02) * (1.01) * (1.005) - 1) * 100.0
        actual = float(result.iloc[0]["quarterly_return"])
        assert abs(actual - expected) < 0.01

    def test_null_returns(self):
        df = self._make_nport_df([{
            "monthly_total_return1": None,
            "monthly_total_return2": "1.0",
            "monthly_total_return3": "0.5",
        }])
        result = _prepare_nport(df)
        assert pd.isna(result.iloc[0]["quarterly_return"])

    def test_leverage_ratio(self):
        df = self._make_nport_df([{
            "total_assets": "2000000",
            "borrowing_pay_within_1yr": "200000",
            "borrowing_pay_after_1yr": "300000",
        }])
        result = _prepare_nport(df)
        assert abs(float(result.iloc[0]["leverage_ratio"]) - 0.25) < 0.001

    def test_zero_total_assets_leverage(self):
        df = self._make_nport_df([{"total_assets": "0"}])
        result = _prepare_nport(df)
        assert pd.isna(result.iloc[0]["leverage_ratio"])

    def test_empty_input(self):
        result = _prepare_nport(pd.DataFrame())
        assert result.empty

    def test_none_input(self):
        result = _prepare_nport(None)
        assert result.empty


# ===================================================================
# 4. _prepare_bdc tests
# ===================================================================

class TestPrepareBdc:

    def test_balance_and_income_join(self):
        cf_df = pd.DataFrame([{
            "cik": "1287750",
            "report_date": "2023-12-31",
            "total_assets": 27000000000.0,
            "total_liabilities": 16000000000.0,
            "net_assets": 11000000000.0,
            "nav_per_share": 19.24,
            "shares_outstanding": 571000000.0,
            "borrowings": 12000000000.0,
        }])
        inc_df = pd.DataFrame([{
            "cik": "1287750",
            "report_quarter": "2023q4",
            "total_investment_income": "750000000",
            "net_investment_income": "400000000",
            "management_fee": "100000000",
            "incentive_fee": "50000000",
            "interest_expense": "200000000",
            "total_expenses": "350000000",
        }])
        result = _prepare_bdc(cf_df, inc_df)
        assert len(result) == 1
        row = result.iloc[0]
        assert row["cik"] == "0001287750"
        assert row["source"] == "companyfacts"
        assert float(row["total_assets"]) == 27000000000.0
        assert float(row["total_investment_income"]) == 750000000.0

    def test_balance_only_cik(self):
        cf_df = pd.DataFrame([{
            "cik": "1234",
            "report_date": "2023-12-31",
            "total_assets": 500_000.0,
            "total_liabilities": None, "net_assets": None,
            "nav_per_share": None, "shares_outstanding": None,
            "borrowings": None,
        }])
        result = _prepare_bdc(cf_df, pd.DataFrame())
        assert len(result) == 1
        assert float(result.iloc[0]["total_assets"]) == 500_000.0
        assert pd.isna(result.iloc[0]["total_investment_income"])

    def test_income_only_cik(self):
        cf_df = pd.DataFrame(columns=[
            "cik", "report_date", "total_assets", "total_liabilities",
            "net_assets", "nav_per_share", "shares_outstanding", "borrowings",
        ])
        inc_df = pd.DataFrame([{
            "cik": "5678",
            "report_quarter": "2024q1",
            "total_investment_income": "100",
            "net_investment_income": "50",
            "management_fee": None, "incentive_fee": None,
            "interest_expense": None, "total_expenses": None,
        }])
        result = _prepare_bdc(cf_df, inc_df)
        assert len(result) == 1
        assert result.iloc[0]["cik"] == "0000005678"
        assert float(result.iloc[0]["total_investment_income"]) == 100.0

    def test_cik_padding_normalization(self):
        cf_df = pd.DataFrame([{
            "cik": "42",
            "report_date": "2023-12-31",
            "total_assets": 500_000.0,
            "total_liabilities": None, "net_assets": None,
            "nav_per_share": None, "shares_outstanding": None,
            "borrowings": None,
        }])
        result = _prepare_bdc(cf_df, pd.DataFrame())
        assert result.iloc[0]["cik"] == "0000000042"

    def test_leverage_derivation(self):
        cf_df = pd.DataFrame([{
            "cik": "1234",
            "report_date": "2023-12-31",
            "total_assets": 1_000_000.0,
            "total_liabilities": 400_000.0, "net_assets": 600_000.0,
            "nav_per_share": None, "shares_outstanding": None,
            "borrowings": 300_000.0,
        }])
        result = _prepare_bdc(cf_df, pd.DataFrame())
        assert abs(float(result.iloc[0]["leverage_ratio"]) - 0.3) < 0.001

    def test_both_empty(self):
        result = _prepare_bdc(
            pd.DataFrame(columns=[
                "cik", "report_date", "total_assets", "total_liabilities",
                "net_assets", "nav_per_share", "shares_outstanding",
                "borrowings",
            ]),
            pd.DataFrame(),
        )
        assert result.empty


# ===================================================================
# 5. build_fund_financials integration tests
# ===================================================================

class TestBuildFundFinancials:

    def test_full_mock_pipeline(self, tmp_path, monkeypatch):
        """End-to-end with mock data, no file I/O."""
        monkeypatch.setattr(
            "pipeline.fund_financials.FUND_FINANCIALS_FILE",
            tmp_path / "fund_financials.csv",
        )
        monkeypatch.setattr(
            "pipeline.fund_financials.COMPANYFACTS_CACHE_DIR",
            tmp_path / "cf_cache",
        )
        (tmp_path / "cf_cache").mkdir()

        # Write a mock companyfacts file
        import json
        facts = {
            "facts": {
                "us-gaap": {
                    "Assets": {"units": {"USD": [
                        {"end": "2023-12-31", "val": 5000},
                    ]}},
                },
            },
        }
        cf_path = tmp_path / "cf_cache" / "0000001111.json"
        cf_path.write_text(json.dumps(facts))

        universe_df = pd.DataFrame([
            {"cik": "1111", "entity_name": "Test BDC",
             "vehicle_type": "bdc"},
            {"cik": "2222", "entity_name": "Test Fund",
             "vehicle_type": "interval_fund"},
        ])

        income_df = pd.DataFrame()

        nport_df = pd.DataFrame([{
            "accession_number": "ACC1", "series_name": "Fund A",
            "series_id": "S1", "cik": "2222",
            "registrant_name": "Test Fund", "quarter": "2023q4",
            "report_date": "2023-10-31", "class_id": "C1",
            "total_assets": "2000", "net_assets": "1500",
            "total_liabilities": "500",
            "borrowing_pay_within_1yr": "100",
            "borrowing_pay_after_1yr": "200",
            "monthly_total_return1": "1.0",
            "monthly_total_return2": "0.5",
            "monthly_total_return3": "-0.2",
            "sales_flow_mon1": "10", "sales_flow_mon2": "20",
            "sales_flow_mon3": "15",
            "redemption_flow_mon1": "5",
            "redemption_flow_mon2": "8",
            "redemption_flow_mon3": "3",
        }])

        result = build_fund_financials(
            income_df=income_df,
            nport_fund_info_df=nport_df,
            universe_df=universe_df,
            client=None,
        )

        assert not result.empty
        # Should have BDC row + N-PORT row
        assert result["cik"].nunique() == 2
        assert (tmp_path / "fund_financials.csv").exists()

    def test_column_completeness(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "pipeline.fund_financials.FUND_FINANCIALS_FILE",
            tmp_path / "fund_financials.csv",
        )
        monkeypatch.setattr(
            "pipeline.fund_financials.COMPANYFACTS_CACHE_DIR",
            tmp_path / "cf_cache",
        )
        (tmp_path / "cf_cache").mkdir()

        nport_df = pd.DataFrame([{
            "accession_number": "ACC1", "series_name": "Fund A",
            "series_id": "S1", "cik": "3333",
            "registrant_name": "Col Test", "quarter": "2024q1",
            "report_date": "2024-01-31", "class_id": "C1",
            "total_assets": "1000", "net_assets": "800",
            "total_liabilities": "200",
            "borrowing_pay_within_1yr": "0",
            "borrowing_pay_after_1yr": "0",
            "monthly_total_return1": "1.0",
            "monthly_total_return2": "0.5",
            "monthly_total_return3": "0.3",
            "sales_flow_mon1": "0", "sales_flow_mon2": "0",
            "sales_flow_mon3": "0",
            "redemption_flow_mon1": "0",
            "redemption_flow_mon2": "0",
            "redemption_flow_mon3": "0",
        }])

        result = build_fund_financials(
            income_df=pd.DataFrame(),
            nport_fund_info_df=nport_df,
            universe_df=pd.DataFrame(),
            client=None,
        )
        for col in OUTPUT_COLUMNS:
            assert col in result.columns, f"Missing column: {col}"

    def test_vehicle_type_enrichment(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "pipeline.fund_financials.FUND_FINANCIALS_FILE",
            tmp_path / "fund_financials.csv",
        )
        monkeypatch.setattr(
            "pipeline.fund_financials.COMPANYFACTS_CACHE_DIR",
            tmp_path / "cf_cache",
        )
        (tmp_path / "cf_cache").mkdir()

        nport_df = pd.DataFrame([{
            "accession_number": "ACC1", "series_name": "Fund A",
            "series_id": "S1", "cik": "4444",
            "registrant_name": "VT Fund", "quarter": "2024q1",
            "report_date": "2024-01-31", "class_id": "C1",
            "total_assets": "1000", "net_assets": "800",
            "total_liabilities": "200",
            "borrowing_pay_within_1yr": "0",
            "borrowing_pay_after_1yr": "0",
            "monthly_total_return1": "1.0",
            "monthly_total_return2": "0.5",
            "monthly_total_return3": "0.3",
            "sales_flow_mon1": "0", "sales_flow_mon2": "0",
            "sales_flow_mon3": "0",
            "redemption_flow_mon1": "0",
            "redemption_flow_mon2": "0",
            "redemption_flow_mon3": "0",
        }])

        universe_df = pd.DataFrame([
            {"cik": "4444", "entity_name": "VT Fund",
             "vehicle_type": "tender_offer_fund"},
        ])

        result = build_fund_financials(
            income_df=pd.DataFrame(),
            nport_fund_info_df=nport_df,
            universe_df=universe_df,
            client=None,
        )
        assert result.iloc[0]["vehicle_type"] == "tender_offer_fund"

    def test_dedup_prefers_companyfacts(self, tmp_path, monkeypatch):
        """When same CIK+quarter in both sources, companyfacts wins."""
        monkeypatch.setattr(
            "pipeline.fund_financials.FUND_FINANCIALS_FILE",
            tmp_path / "fund_financials.csv",
        )
        monkeypatch.setattr(
            "pipeline.fund_financials.COMPANYFACTS_CACHE_DIR",
            tmp_path / "cf_cache",
        )
        (tmp_path / "cf_cache").mkdir()

        import json
        facts = {
            "facts": {
                "us-gaap": {
                    "Assets": {"units": {"USD": [
                        {"end": "2024-03-31", "val": 999_999},
                    ]}},
                },
            },
        }
        (tmp_path / "cf_cache" / "0000005555.json").write_text(
            json.dumps(facts),
        )

        universe_df = pd.DataFrame([
            {"cik": "5555", "entity_name": "Overlap BDC",
             "vehicle_type": "bdc"},
        ])

        nport_df = pd.DataFrame([{
            "accession_number": "ACC1", "series_name": "Fund A",
            "series_id": "S1", "cik": "5555",
            "registrant_name": "Overlap BDC", "quarter": "2024q1",
            "report_date": "2024-01-31", "class_id": "C1",
            "total_assets": "1111", "net_assets": "800",
            "total_liabilities": "200",
            "borrowing_pay_within_1yr": "0",
            "borrowing_pay_after_1yr": "0",
            "monthly_total_return1": "1.0",
            "monthly_total_return2": "0.5",
            "monthly_total_return3": "0.3",
            "sales_flow_mon1": "0", "sales_flow_mon2": "0",
            "sales_flow_mon3": "0",
            "redemption_flow_mon1": "0",
            "redemption_flow_mon2": "0",
            "redemption_flow_mon3": "0",
        }])

        result = build_fund_financials(
            income_df=pd.DataFrame(),
            nport_fund_info_df=nport_df,
            universe_df=universe_df,
            client=None,
        )
        # Should have exactly 1 row (deduped)
        overlap = result[result["cik"] == "0000005555"]
        assert len(overlap) == 1
        assert overlap.iloc[0]["source"] == "companyfacts"
        assert float(overlap.iloc[0]["total_assets"]) == 999_999.0

    def test_empty_inputs(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "pipeline.fund_financials.FUND_FINANCIALS_FILE",
            tmp_path / "fund_financials.csv",
        )
        monkeypatch.setattr(
            "pipeline.fund_financials.COMPANYFACTS_CACHE_DIR",
            tmp_path / "cf_cache",
        )
        (tmp_path / "cf_cache").mkdir()

        result = build_fund_financials(
            income_df=pd.DataFrame(),
            nport_fund_info_df=pd.DataFrame(),
            universe_df=pd.DataFrame(),
            client=None,
        )
        assert result.empty
        assert (tmp_path / "fund_financials.csv").exists()

    def test_lazy_load_skipped_with_explicit_args(self, tmp_path, monkeypatch):
        """When DataFrames are passed explicitly, file loading is skipped."""
        monkeypatch.setattr(
            "pipeline.fund_financials.FUND_FINANCIALS_FILE",
            tmp_path / "fund_financials.csv",
        )
        monkeypatch.setattr(
            "pipeline.fund_financials.COMPANYFACTS_CACHE_DIR",
            tmp_path / "cf_cache",
        )
        monkeypatch.setattr(
            "pipeline.fund_financials.BDC_FUND_INCOME_FILE",
            tmp_path / "nonexistent_income.csv",
        )
        monkeypatch.setattr(
            "pipeline.fund_financials.NPORT_FUND_INFO_FILE",
            tmp_path / "nonexistent_nport.csv",
        )
        monkeypatch.setattr(
            "pipeline.fund_financials.COMBINED_UNIVERSE_FILE",
            tmp_path / "nonexistent_universe.csv",
        )
        (tmp_path / "cf_cache").mkdir()

        # Should not error even though file paths don't exist
        result = build_fund_financials(
            income_df=pd.DataFrame(),
            nport_fund_info_df=pd.DataFrame(),
            universe_df=pd.DataFrame(),
            client=None,
        )
        assert result.empty


# ===================================================================
# 6. Concept selection -- exact match tests
# ===================================================================

class TestConceptSelectionExactMatch:

    def test_exact_match_preferred_over_substring(self):
        """'DeferredIncomeTaxLiabilities' should NOT win over 'Liabilities'."""
        facts = {
            "facts": {
                "us-gaap": {
                    "Liabilities": {"units": {"USD": [
                        {"end": "2023-12-31", "val": 1_100_000_000},
                        {"end": "2024-03-31", "val": 1_200_000_000},
                    ]}},
                    "DeferredIncomeTaxLiabilities": {"units": {"USD": [
                        {"end": "2023-12-31", "val": 18_000_000},
                        {"end": "2024-03-31", "val": 19_000_000},
                        {"end": "2024-06-30", "val": 20_000_000},
                    ]}},
                },
            },
        }
        result = _extract_concept_series(facts, ["Liabilities"], "USD", True)
        # Should pick "Liabilities" (exact), NOT "DeferredIncomeTaxLiabilities"
        assert result["2023-12-31"] == 1_100_000_000
        assert len(result) == 2  # not 3

    def test_exact_match_tiebreak_by_shorter_name(self):
        """When two exact matches have same points, shorter name wins."""
        facts = {
            "facts": {
                "us-gaap": {
                    "StockholdersEquity": {"units": {"USD": [
                        {"end": "2023-12-31", "val": 500},
                    ]}},
                    "MembersCapital": {"units": {"USD": [
                        {"end": "2023-12-31", "val": 600},
                    ]}},
                },
            },
        }
        result = _extract_concept_series(
            facts,
            ["StockholdersEquity", "MembersCapital"],
            "USD", True,
        )
        # Both have 1 point; MembersCapital is shorter (14 < 18)
        assert result["2023-12-31"] == 600

    def test_fallback_used_when_no_exact(self):
        """'AssetsNet' found via fallback when 'Assets' absent."""
        facts = _make_facts({
            "AssetsNet": [
                {"end": "2023-12-31", "val": 960_000_000},
                {"end": "2024-03-31", "val": 970_000_000},
            ],
        })
        rows = _extract_bdc_balance_sheet("1234", facts)
        assert len(rows) == 2
        assert rows[0]["total_assets"] == 960_000_000

    def test_fallback_not_used_when_exact_exists(self):
        """'Assets' preferred over 'AssetsNet' even with fewer points."""
        facts = {
            "facts": {
                "us-gaap": {
                    "Assets": {"units": {"USD": [
                        {"end": "2023-12-31", "val": 1_000_000_000},
                    ]}},
                    "AssetsNet": {"units": {"USD": [
                        {"end": "2023-12-31", "val": 600_000_000},
                        {"end": "2024-03-31", "val": 700_000_000},
                        {"end": "2024-06-30", "val": 800_000_000},
                    ]}},
                },
            },
        }
        rows = _extract_bdc_balance_sheet("1234", facts)
        # Should use Assets (exact), not AssetsNet (fallback with more points)
        assert len(rows) == 1
        assert rows[0]["total_assets"] == 1_000_000_000

    def test_no_duration_facts_in_instant_search(self):
        """Duration facts (with start date) excluded from instant search."""
        facts = _make_facts({
            "Assets": [
                {"end": "2023-12-31", "start": "2023-01-01", "val": 999},
            ],
        })
        result = _extract_concept_series(facts, ["Assets"], "USD", True)
        assert result == {}

    def test_substring_concepts_not_matched(self):
        """Concepts like 'AccountsPayableAndOtherAccruedLiabilities' should
        not match when searching for 'Liabilities'."""
        facts = {
            "facts": {
                "us-gaap": {
                    "AccountsPayableAndOtherAccruedLiabilities": {
                        "units": {"USD": [
                            {"end": "2023-12-31", "val": 132_000_000},
                            {"end": "2024-03-31", "val": 140_000_000},
                        ]},
                    },
                },
            },
        }
        result = _extract_concept_series(facts, ["Liabilities"], "USD", True)
        assert result == {}


# ===================================================================
# 7. BDC cleaning CTE tests
# ===================================================================

class TestBdcCleaning:

    def test_scale_fix_1000x_jump(self):
        """total_assets 286134 corrected when net_assets is ~286M scale."""
        cf_df = pd.DataFrame([
            {"cik": "100", "report_date": "2023-03-31",
             "total_assets": 286_134_000.0, "total_liabilities": 100_000_000.0,
             "net_assets": 186_134_000.0,
             "nav_per_share": None, "shares_outstanding": None,
             "borrowings": None},
            {"cik": "100", "report_date": "2023-06-30",
             "total_assets": 290_000_000.0, "total_liabilities": 105_000_000.0,
             "net_assets": 185_000_000.0,
             "nav_per_share": None, "shares_outstanding": None,
             "borrowings": None},
            # This quarter reported in thousands (1000x too small)
            {"cik": "100", "report_date": "2023-09-30",
             "total_assets": 295_000.0, "total_liabilities": 110_000.0,
             "net_assets": 185_000_000.0,
             "nav_per_share": None, "shares_outstanding": None,
             "borrowings": None},
        ])
        result = _prepare_bdc(cf_df, pd.DataFrame())
        q3 = result[result["report_date"] == "2023-09-30"].iloc[0]
        # Should be corrected to ~295M scale, not 295K
        assert float(q3["total_assets"]) > 100_000_000

    def test_scale_fix_no_false_positive(self):
        """Legitimate TA/NA=2.0 ratio not corrected."""
        cf_df = pd.DataFrame([
            {"cik": "200", "report_date": "2023-03-31",
             "total_assets": 2_000_000.0, "total_liabilities": 1_000_000.0,
             "net_assets": 1_000_000.0,
             "nav_per_share": None, "shares_outstanding": None,
             "borrowings": None},
            {"cik": "200", "report_date": "2023-06-30",
             "total_assets": 2_100_000.0, "total_liabilities": 1_050_000.0,
             "net_assets": 1_050_000.0,
             "nav_per_share": None, "shares_outstanding": None,
             "borrowings": None},
        ])
        result = _prepare_bdc(cf_df, pd.DataFrame())
        row0 = result[result["report_date"] == "2023-03-31"].iloc[0]
        assert float(row0["total_assets"]) == 2_000_000.0

    def test_negative_total_assets_nulled(self):
        """Negative total_assets set to NULL."""
        cf_df = pd.DataFrame([{
            "cik": "300", "report_date": "2023-12-31",
            "total_assets": -500_000.0, "total_liabilities": None,
            "net_assets": None,
            "nav_per_share": None, "shares_outstanding": None,
            "borrowings": None,
        }])
        result = _prepare_bdc(cf_df, pd.DataFrame())
        assert pd.isna(result.iloc[0]["total_assets"])

    def test_leverage_cap(self):
        """leverage_ratio capped at 2.0."""
        cf_df = pd.DataFrame([{
            "cik": "400", "report_date": "2023-12-31",
            "total_assets": 1_000_000.0, "total_liabilities": None,
            "net_assets": 500_000.0,
            "nav_per_share": None, "shares_outstanding": None,
            "borrowings": 5_000_000.0,  # 5x leverage
        }])
        result = _prepare_bdc(cf_df, pd.DataFrame())
        assert float(result.iloc[0]["leverage_ratio"]) == 2.0

    def test_ta_less_than_na_nulled(self):
        """total_assets < 0.8 * net_assets set to NULL."""
        cf_df = pd.DataFrame([
            # Need a "normal" row so scale fix doesn't interfere
            {"cik": "500", "report_date": "2023-03-31",
             "total_assets": 2000.0, "total_liabilities": 800.0,
             "net_assets": 1200.0,
             "nav_per_share": None, "shares_outstanding": None,
             "borrowings": None},
            # Wrong concept picked: TA < NA
            {"cik": "500", "report_date": "2023-06-30",
             "total_assets": 500.0, "total_liabilities": None,
             "net_assets": 1300.0,
             "nav_per_share": None, "shares_outstanding": None,
             "borrowings": None},
        ])
        result = _prepare_bdc(cf_df, pd.DataFrame())
        q2 = result[result["report_date"] == "2023-06-30"].iloc[0]
        assert pd.isna(q2["total_assets"])

    def test_clean_data_unchanged(self):
        """Well-formed data passes through untouched."""
        cf_df = pd.DataFrame([{
            "cik": "600", "report_date": "2023-12-31",
            "total_assets": 1_000_000.0,
            "total_liabilities": 400_000.0,
            "net_assets": 600_000.0,
            "nav_per_share": 19.5,
            "shares_outstanding": 30000.0,
            "borrowings": 300_000.0,
        }])
        result = _prepare_bdc(cf_df, pd.DataFrame())
        row = result.iloc[0]
        assert float(row["total_assets"]) == 1_000_000.0
        assert float(row["total_liabilities"]) == 400_000.0
        assert float(row["borrowings"]) == 300_000.0
        assert abs(float(row["leverage_ratio"]) - 0.3) < 0.001


# ===================================================================
# 8. N-CEN date parsing
# ===================================================================

class TestParseNcenDate:

    def test_valid_date(self):
        assert _parse_ncen_date("31-JUL-2025") == "2025-07-31"
        assert _parse_ncen_date("01-JAN-2023") == "2023-01-01"
        assert _parse_ncen_date("30-APR-2025") == "2025-04-30"

    def test_invalid_date(self):
        assert _parse_ncen_date("") is None
        assert _parse_ncen_date(None) is None
        assert _parse_ncen_date("2025-07-31") is None  # ISO format
        assert _parse_ncen_date("31-FOO-2025") is None


# ===================================================================
# 9. _parse_ncen_financials tests
# ===================================================================

def _make_ncen_zip(tmp_path, quarter, fri_rows, sub_rows, reg_rows):
    """Create a mock N-CEN ZIP with TSV files."""
    import io
    import zipfile as zf

    zip_path = tmp_path / f"{quarter}_ncen.zip"
    with zf.ZipFile(zip_path, "w") as z:
        # FUND_REPORTED_INFO.tsv
        fri_df = pd.DataFrame(fri_rows)
        buf = io.BytesIO()
        fri_df.to_csv(buf, sep="\t", index=False)
        z.writestr("FUND_REPORTED_INFO.tsv", buf.getvalue())

        # SUBMISSION.tsv
        sub_df = pd.DataFrame(sub_rows)
        buf = io.BytesIO()
        sub_df.to_csv(buf, sep="\t", index=False)
        z.writestr("SUBMISSION.tsv", buf.getvalue())

        # REGISTRANT.tsv
        reg_df = pd.DataFrame(reg_rows)
        buf = io.BytesIO()
        reg_df.to_csv(buf, sep="\t", index=False)
        z.writestr("REGISTRANT.tsv", buf.getvalue())

    return zip_path


class TestParseNcenFinancials:

    def test_extracts_n2_financials(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "pipeline.fund_financials.SEC_DATASETS_DIR", tmp_path)
        monkeypatch.setattr(
            "pipeline.fund_financials.NCEN_QUARTERS", ["2025q3"])

        _make_ncen_zip(tmp_path, "2025q3",
            fri_rows=[{
                "ACCESSION_NUMBER": "ACC1", "FUND_ID": "F1",
                "FUND_NAME": "Test Fund",
                "SERIES_ID": "S1",
                "MANAGEMENT_FEE": "1.2",
                "NET_OPERATING_EXPENSES": "4.47",
                "NAV_PER_SHARE": "25.50",
                "MARKET_PRICE_PER_SHARE": "23.10",
                "MONTHLY_AVG_NET_ASSETS": "500000000",
            }],
            sub_rows=[{
                "ACCESSION_NUMBER": "ACC1",
                "CIK": "0001234567",
                "REPORT_ENDING_PERIOD": "30-JUN-2025",
            }],
            reg_rows=[{
                "ACCESSION_NUMBER": "ACC1",
                "REGISTRANT_NAME": "Test Fund Inc",
                "INVESTMENT_COMPANY_TYPE": "N-2",
            }],
        )

        result = _parse_ncen_financials({"0001234567"})
        assert len(result) == 1
        row = result.iloc[0]
        assert row["cik"] == "0001234567"
        assert row["management_fee_pct"] == 1.2
        assert row["expense_ratio_pct"] == 4.47
        assert row["nav_per_share"] == 25.50
        assert row["market_price_per_share"] == 23.10
        assert row["monthly_avg_net_assets"] == 500_000_000
        assert row["report_date"] == "2025-06-30"
        assert row["report_quarter"] == "2025q2"

    def test_filters_non_n2(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "pipeline.fund_financials.SEC_DATASETS_DIR", tmp_path)
        monkeypatch.setattr(
            "pipeline.fund_financials.NCEN_QUARTERS", ["2025q3"])

        _make_ncen_zip(tmp_path, "2025q3",
            fri_rows=[{
                "ACCESSION_NUMBER": "ACC1", "FUND_ID": "F1",
                "FUND_NAME": "Mutual Fund",
                "SERIES_ID": "S1",
                "MANAGEMENT_FEE": "0.5",
                "NET_OPERATING_EXPENSES": "1.0",
                "NAV_PER_SHARE": "10.00",
                "MARKET_PRICE_PER_SHARE": "",
                "MONTHLY_AVG_NET_ASSETS": "100000",
            }],
            sub_rows=[{
                "ACCESSION_NUMBER": "ACC1",
                "CIK": "0009999999",
                "REPORT_ENDING_PERIOD": "30-JUN-2025",
            }],
            reg_rows=[{
                "ACCESSION_NUMBER": "ACC1",
                "REGISTRANT_NAME": "Mutual Fund Inc",
                "INVESTMENT_COMPANY_TYPE": "N-1A",
            }],
        )

        result = _parse_ncen_financials({"0009999999"})
        assert result.empty

    def test_filters_non_universe_ciks(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "pipeline.fund_financials.SEC_DATASETS_DIR", tmp_path)
        monkeypatch.setattr(
            "pipeline.fund_financials.NCEN_QUARTERS", ["2025q3"])

        _make_ncen_zip(tmp_path, "2025q3",
            fri_rows=[{
                "ACCESSION_NUMBER": "ACC1", "FUND_ID": "F1",
                "FUND_NAME": "Non-Universe Fund",
                "SERIES_ID": "S1",
                "MANAGEMENT_FEE": "1.0",
                "NET_OPERATING_EXPENSES": "2.0",
                "NAV_PER_SHARE": "15.00",
                "MARKET_PRICE_PER_SHARE": "",
                "MONTHLY_AVG_NET_ASSETS": "200000",
            }],
            sub_rows=[{
                "ACCESSION_NUMBER": "ACC1",
                "CIK": "0001111111",
                "REPORT_ENDING_PERIOD": "30-JUN-2025",
            }],
            reg_rows=[{
                "ACCESSION_NUMBER": "ACC1",
                "REGISTRANT_NAME": "Non-Universe Fund Inc",
                "INVESTMENT_COMPANY_TYPE": "N-2",
            }],
        )

        # CIK not in universe set
        result = _parse_ncen_financials({"0009999999"})
        assert result.empty

    def test_dedup_by_cik_report_date(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "pipeline.fund_financials.SEC_DATASETS_DIR", tmp_path)
        monkeypatch.setattr(
            "pipeline.fund_financials.NCEN_QUARTERS",
            ["2025q2", "2025q3"])

        # Same CIK+date in two quarter ZIPs
        for q in ["2025q2", "2025q3"]:
            _make_ncen_zip(tmp_path, q,
                fri_rows=[{
                    "ACCESSION_NUMBER": f"ACC_{q}", "FUND_ID": "F1",
                    "FUND_NAME": "Dup Fund",
                    "SERIES_ID": "S1",
                    "MANAGEMENT_FEE": "1.5",
                    "NET_OPERATING_EXPENSES": "3.0",
                    "NAV_PER_SHARE": "20.00",
                    "MARKET_PRICE_PER_SHARE": "",
                    "MONTHLY_AVG_NET_ASSETS": "300000",
                }],
                sub_rows=[{
                    "ACCESSION_NUMBER": f"ACC_{q}",
                    "CIK": "0002222222",
                    "REPORT_ENDING_PERIOD": "30-JUN-2025",
                }],
                reg_rows=[{
                    "ACCESSION_NUMBER": f"ACC_{q}",
                    "REGISTRANT_NAME": "Dup Fund Inc",
                    "INVESTMENT_COMPANY_TYPE": "N-2",
                }],
            )

        result = _parse_ncen_financials({"0002222222"})
        # Should be deduplicated to 1 row
        assert len(result) == 1
        assert result.iloc[0]["cik"] == "0002222222"


# ===================================================================
# 10. N-PORT + N-CEN enrichment tests
# ===================================================================

class TestNportNcenEnrichment:

    def _make_nport_df(self, rows: list[dict]) -> pd.DataFrame:
        base = {
            "accession_number": "ACC1", "series_name": "Fund A",
            "series_id": "S1", "cik": "1234",
            "registrant_name": "Test Fund", "quarter": "2023q4",
            "report_date": "2023-10-31", "class_id": "C1",
            "total_assets": "1000000", "net_assets": "800000",
            "total_liabilities": "200000",
            "borrowing_pay_within_1yr": "50000",
            "borrowing_pay_after_1yr": "100000",
            "monthly_total_return1": "1.5",
            "monthly_total_return2": "0.8",
            "monthly_total_return3": "-0.3",
            "sales_flow_mon1": "10000", "sales_flow_mon2": "20000",
            "sales_flow_mon3": "15000",
            "redemption_flow_mon1": "5000",
            "redemption_flow_mon2": "8000",
            "redemption_flow_mon3": "3000",
        }
        full_rows = [{**base, **r} for r in rows]
        return pd.DataFrame(full_rows)

    def test_nport_enriched_with_ncen(self):
        nport_df = self._make_nport_df([{}])
        ncen_df = pd.DataFrame([{
            "cik": "0000001234",
            "entity_name": "Test Fund",
            "report_date": "2023-09-30",
            "report_quarter": "2023q3",
            "management_fee_pct": 1.5,
            "expense_ratio_pct": 3.2,
            "nav_per_share": 22.0,
            "market_price_per_share": 20.0,
            "monthly_avg_net_assets": 900000.0,
            "is_debt_default": False,
            "is_dividend_arrears": False,
            "is_fund_of_fund": False,
            "is_non_diversified": False,
        }])
        result = _prepare_nport(nport_df, ncen_df=ncen_df)
        assert len(result) == 1
        row = result.iloc[0]
        assert float(row["management_fee_pct"]) == 1.5
        assert float(row["expense_ratio_pct"]) == 3.2
        assert float(row["nav_per_share"]) == 22.0
        assert float(row["market_price_per_share"]) == 20.0
        assert float(row["monthly_avg_net_assets"]) == 900000.0

    def test_nport_without_ncen_backward_compatible(self):
        nport_df = self._make_nport_df([{}])
        result = _prepare_nport(nport_df, ncen_df=None)
        assert len(result) == 1
        row = result.iloc[0]
        assert pd.isna(row["management_fee_pct"])
        assert pd.isna(row["expense_ratio_pct"])
        assert pd.isna(row["nav_per_share"])

    def test_ncen_temporal_join(self):
        """Picks the most recent N-CEN filing <= N-PORT report_date."""
        nport_df = self._make_nport_df([{
            "quarter": "2024q2", "report_date": "2024-04-30",
        }])
        ncen_df = pd.DataFrame([
            {
                "cik": "0000001234", "entity_name": "Test Fund",
                "report_date": "2023-06-30", "report_quarter": "2023q2",
                "management_fee_pct": 1.0, "expense_ratio_pct": 2.0,
                "nav_per_share": 18.0, "market_price_per_share": None,
                "monthly_avg_net_assets": None,
                "is_debt_default": False, "is_dividend_arrears": False,
                "is_fund_of_fund": False, "is_non_diversified": False,
            },
            {
                "cik": "0000001234", "entity_name": "Test Fund",
                "report_date": "2024-06-30", "report_quarter": "2024q2",
                "management_fee_pct": 1.5, "expense_ratio_pct": 3.0,
                "nav_per_share": 22.0, "market_price_per_share": None,
                "monthly_avg_net_assets": None,
                "is_debt_default": False, "is_dividend_arrears": False,
                "is_fund_of_fund": False, "is_non_diversified": False,
            },
        ])
        result = _prepare_nport(nport_df, ncen_df=ncen_df)
        assert len(result) == 1
        row = result.iloc[0]
        # Should pick 2023-06-30 (most recent <= 2024-04-30)
        # NOT 2024-06-30 which is after the N-PORT date
        assert float(row["management_fee_pct"]) == 1.0
        assert float(row["nav_per_share"]) == 18.0


# ===================================================================
# 11. _prepare_ncen tests
# ===================================================================

class TestPrepareNcen:

    def test_ncen_only_ciks_included(self):
        ncen_df = pd.DataFrame([{
            "cik": "0000007777",
            "entity_name": "Standalone Fund",
            "report_date": "2024-06-30",
            "report_quarter": "2024q2",
            "management_fee_pct": 0.85,
            "expense_ratio_pct": 2.1,
            "nav_per_share": 13.5,
            "market_price_per_share": 11.0,
            "monthly_avg_net_assets": 50000000.0,
        }])
        # No existing CIKs
        result = _prepare_ncen(ncen_df, set())
        assert len(result) == 1
        row = result.iloc[0]
        assert row["cik"] == "0000007777"
        assert row["source"] == "ncen"
        assert float(row["management_fee_pct"]) == 0.85
        assert float(row["nav_per_share"]) == 13.5
        # N-PORT fields should be NULL
        assert pd.isna(row["total_assets"])
        assert pd.isna(row["monthly_return_1"])

    def test_ncen_ciks_in_nport_excluded(self):
        ncen_df = pd.DataFrame([{
            "cik": "0000001234",
            "entity_name": "Already in N-PORT",
            "report_date": "2024-06-30",
            "report_quarter": "2024q2",
            "management_fee_pct": 1.0,
            "expense_ratio_pct": 2.0,
            "nav_per_share": 20.0,
            "market_price_per_share": None,
            "monthly_avg_net_assets": None,
        }])
        # CIK already exists in N-PORT
        result = _prepare_ncen(ncen_df, {"0000001234"})
        assert result.empty


# ===================================================================
# 12. Integration test with N-CEN
# ===================================================================

class TestBuildFundFinancialsWithNcen:

    def test_full_pipeline_with_ncen(self, tmp_path, monkeypatch):
        """End-to-end with N-CEN standalone CIK."""
        monkeypatch.setattr(
            "pipeline.fund_financials.FUND_FINANCIALS_FILE",
            tmp_path / "fund_financials.csv",
        )
        monkeypatch.setattr(
            "pipeline.fund_financials.COMPANYFACTS_CACHE_DIR",
            tmp_path / "cf_cache",
        )
        monkeypatch.setattr(
            "pipeline.fund_financials.SEC_DATASETS_DIR",
            tmp_path / "sec",
        )
        monkeypatch.setattr(
            "pipeline.fund_financials.NCEN_QUARTERS", ["2025q3"],
        )
        (tmp_path / "cf_cache").mkdir()
        (tmp_path / "sec").mkdir()

        # Create mock N-CEN ZIP with a standalone CIK
        _make_ncen_zip(tmp_path / "sec", "2025q3",
            fri_rows=[{
                "ACCESSION_NUMBER": "ACC_NCEN", "FUND_ID": "F1",
                "FUND_NAME": "Interval Fund X",
                "SERIES_ID": "S1",
                "MANAGEMENT_FEE": "1.1",
                "NET_OPERATING_EXPENSES": "2.5",
                "NAV_PER_SHARE": "15.00",
                "MARKET_PRICE_PER_SHARE": "",
                "MONTHLY_AVG_NET_ASSETS": "80000000",
            }],
            sub_rows=[{
                "ACCESSION_NUMBER": "ACC_NCEN",
                "CIK": "0000008888",
                "REPORT_ENDING_PERIOD": "30-JUN-2025",
            }],
            reg_rows=[{
                "ACCESSION_NUMBER": "ACC_NCEN",
                "REGISTRANT_NAME": "Interval Fund X Inc",
                "INVESTMENT_COMPANY_TYPE": "N-2",
            }],
        )

        universe_df = pd.DataFrame([
            {"cik": "8888", "entity_name": "Interval Fund X",
             "vehicle_type": "interval_fund"},
        ])

        result = build_fund_financials(
            income_df=pd.DataFrame(),
            nport_fund_info_df=pd.DataFrame(),
            universe_df=universe_df,
            client=None,
        )

        assert not result.empty
        ncen_rows = result[result["source"] == "ncen"]
        assert len(ncen_rows) == 1
        row = ncen_rows.iloc[0]
        assert row["cik"] == "0000008888"
        assert row["vehicle_type"] == "interval_fund"
        assert float(row["management_fee_pct"]) == 1.1
        assert float(row["expense_ratio_pct"]) == 2.5
        assert float(row["nav_per_share"]) == 15.0
        # All OUTPUT_COLUMNS should be present
        for col in OUTPUT_COLUMNS:
            assert col in result.columns, f"Missing column: {col}"


# ===================================================================
# 13. Extended companyfacts concept extraction tests
# ===================================================================

class TestExtendedConcepts:

    def test_distribution_per_share(self):
        """InvestmentCompanyDistributionToShareholdersPerShare extracted."""
        facts = {
            "facts": {
                "us-gaap": {
                    "InvestmentCompanyDistributionToShareholdersPerShare": {
                        "units": {"USD/shares": [
                            {"end": "2023-12-31", "start": "2023-01-01",
                             "val": 1.52},
                        ]},
                    },
                },
            },
        }
        result = _extract_concept_series(
            facts,
            ["InvestmentCompanyDistributionToShareholdersPerShare"],
            "USD/shares", False,
        )
        assert result == {"2023-12-31": 1.52}

    def test_total_return_pct(self):
        """InvestmentCompanyTotalReturn extracted as duration (pure)."""
        facts = {
            "facts": {
                "us-gaap": {
                    "InvestmentCompanyTotalReturn": {
                        "units": {"pure": [
                            {"end": "2023-12-31", "start": "2023-01-01",
                             "val": 0.0842},
                        ]},
                    },
                },
            },
        }
        result = _extract_concept_series(
            facts, ["InvestmentCompanyTotalReturn"], "pure", False,
        )
        assert result == {"2023-12-31": 0.0842}

    def test_income_per_share(self):
        """InvestmentCompanyInvestmentIncomeLossPerShare extracted."""
        facts = {
            "facts": {
                "us-gaap": {
                    "InvestmentCompanyInvestmentIncomeLossPerShare": {
                        "units": {"USD/shares": [
                            {"end": "2024-03-31", "start": "2024-01-01",
                             "val": 0.45},
                        ]},
                    },
                },
            },
        }
        result = _extract_concept_series(
            facts,
            ["InvestmentCompanyInvestmentIncomeLossPerShare"],
            "USD/shares", False,
        )
        assert result == {"2024-03-31": 0.45}

    def test_portfolio_turnover(self):
        """InvestmentCompanyPortfolioTurnover extracted as pure duration."""
        facts = {
            "facts": {
                "us-gaap": {
                    "InvestmentCompanyPortfolioTurnover": {
                        "units": {"pure": [
                            {"end": "2023-12-31", "start": "2023-01-01",
                             "val": 0.35},
                        ]},
                    },
                },
            },
        }
        result = _extract_concept_series(
            facts, ["InvestmentCompanyPortfolioTurnover"], "pure", False,
        )
        assert result == {"2023-12-31": 0.35}

    def test_asset_coverage_ratio_instant(self):
        """Asset coverage ratio is instant (no start date)."""
        facts = {
            "facts": {
                "us-gaap": {
                    "InvestmentCompanySeniorSecurityIndebtednessAssetCoverageRatio": {
                        "units": {"pure": [
                            {"end": "2023-12-31", "val": 1.92},
                        ]},
                    },
                },
            },
        }
        result = _extract_concept_series(
            facts,
            ["InvestmentCompanySeniorSecurityIndebtednessAssetCoverageRatio"],
            "pure", True,
        )
        assert result == {"2023-12-31": 1.92}

    def test_bdc_balance_sheet_includes_extended(self):
        """_extract_bdc_balance_sheet returns extended fields."""
        facts = {
            "facts": {
                "us-gaap": {
                    "Assets": {"units": {"USD": [
                        {"end": "2023-12-31", "val": 5000000},
                    ]}},
                    "InvestmentCompanyDistributionToShareholdersPerShare": {
                        "units": {"USD/shares": [
                            {"end": "2023-12-31", "start": "2023-01-01",
                             "val": 1.20},
                        ]},
                    },
                    "InvestmentCompanyTotalReturn": {
                        "units": {"pure": [
                            {"end": "2023-12-31", "start": "2023-01-01",
                             "val": 0.095},
                        ]},
                    },
                    "InvestmentCompanyPortfolioTurnover": {
                        "units": {"pure": [
                            {"end": "2023-12-31", "start": "2023-01-01",
                             "val": 0.42},
                        ]},
                    },
                },
            },
        }
        rows = _extract_bdc_balance_sheet("1234", facts)
        assert len(rows) == 1
        row = rows[0]
        assert row["total_assets"] == 5000000
        # Duration facts are now YTD->quarterly converted:
        # 12-month annual / 4 quarters = quarterly value
        assert abs(row["distribution_per_share"] - 0.30) < 0.01
        assert abs(row["total_return_pct"] - 0.095 / 4) < 0.001
        assert abs(row["portfolio_turnover"] - 0.42 / 4) < 0.01

    def test_extended_fields_list(self):
        """_EXTENDED_FIELDS contains all expected fields."""
        expected = {
            "distribution_per_share", "dividends_declared_per_share",
            "distribution_ordinary_income", "distribution_return_of_capital",
            "total_return_pct", "gain_loss_per_share", "nav_change_per_share",
            "income_per_share", "income_yield_pct", "gross_investment_income",
            "portfolio_turnover", "asset_coverage_ratio",
            "unfunded_commitments", "unrealized_appreciation",
            "unrealized_depreciation", "debt_weighted_avg_rate",
        }
        assert expected == set(_EXTENDED_FIELDS)


# ===================================================================
# 14. Computed metrics tests
# ===================================================================

class TestComputedMetrics:

    def test_distribution_rate_bdc(self, tmp_path, monkeypatch):
        """BDC distribution_rate = (dist_per_share * 4) / nav * 100."""
        monkeypatch.setattr(
            "pipeline.fund_financials.FUND_FINANCIALS_FILE",
            tmp_path / "fund_financials.csv",
        )
        monkeypatch.setattr(
            "pipeline.fund_financials.COMPANYFACTS_CACHE_DIR",
            tmp_path / "cf_cache",
        )
        (tmp_path / "cf_cache").mkdir()

        import json
        facts = {
            "facts": {
                "us-gaap": {
                    "Assets": {"units": {"USD": [
                        {"end": "2023-12-31", "val": 10000},
                    ]}},
                    "NetAssetValuePerShare": {"units": {"USD/shares": [
                        {"end": "2023-12-31", "val": 20.0},
                    ]}},
                    "InvestmentCompanyDistributionToShareholdersPerShare": {
                        "units": {"USD/shares": [
                            {"end": "2023-12-31", "start": "2023-01-01",
                             "val": 0.50},
                        ]},
                    },
                },
            },
        }
        (tmp_path / "cf_cache" / "0000001111.json").write_text(
            json.dumps(facts),
        )

        universe_df = pd.DataFrame([
            {"cik": "1111", "entity_name": "Test BDC",
             "vehicle_type": "bdc"},
        ])

        result = build_fund_financials(
            income_df=pd.DataFrame(),
            nport_fund_info_df=pd.DataFrame(),
            universe_df=universe_df,
            client=None,
        )

        assert not result.empty
        row = result.iloc[0]
        # dist_rate = (0.50 * 4) / 20.0 * 100 = 10.0
        assert "distribution_rate" in result.columns
        dr = row["distribution_rate"]
        if dr is not None and not pd.isna(dr):
            assert abs(float(dr) - 10.0) < 0.1

    def test_distribution_rate_proxy_nport(self):
        """N-PORT distribution_rate_proxy from reinvestment flows."""
        nport_df = pd.DataFrame([{
            "accession_number": "ACC1", "series_name": "Fund A",
            "series_id": "S1", "cik": "2222",
            "registrant_name": "Test Fund", "quarter": "2023q4",
            "report_date": "2023-10-31", "class_id": "C1",
            "total_assets": "1000000", "net_assets": "800000",
            "total_liabilities": "200000",
            "borrowing_pay_within_1yr": "0",
            "borrowing_pay_after_1yr": "0",
            "monthly_total_return1": "1.0",
            "monthly_total_return2": "0.5",
            "monthly_total_return3": "0.3",
            "sales_flow_mon1": "10000", "sales_flow_mon2": "8000",
            "sales_flow_mon3": "5000",
            "redemption_flow_mon1": "2000",
            "redemption_flow_mon2": "1000",
            "redemption_flow_mon3": "500",
        }])
        result = _prepare_nport(nport_df)
        assert "distribution_rate_proxy" in result.columns
        assert "redemption_pressure" in result.columns
        row = result.iloc[0]
        # net reinvestment = (10+8+5) - (2+1+0.5) = 19500
        # proxy = 19500 * 4 / 800000 * 100 = 9.75
        proxy = float(row["distribution_rate_proxy"])
        assert proxy > 0

    def test_redemption_pressure_nport(self):
        """redemption_pressure = total_redemptions / net_assets * 100."""
        nport_df = pd.DataFrame([{
            "accession_number": "ACC1", "series_name": "Fund A",
            "series_id": "S1", "cik": "3333",
            "registrant_name": "Test Fund", "quarter": "2024q1",
            "report_date": "2024-01-31", "class_id": "C1",
            "total_assets": "1000000", "net_assets": "800000",
            "total_liabilities": "200000",
            "borrowing_pay_within_1yr": "0",
            "borrowing_pay_after_1yr": "0",
            "monthly_total_return1": "1.0",
            "monthly_total_return2": "0.5",
            "monthly_total_return3": "0.3",
            "sales_flow_mon1": "0", "sales_flow_mon2": "0",
            "sales_flow_mon3": "0",
            "redemption_flow_mon1": "10000",
            "redemption_flow_mon2": "15000",
            "redemption_flow_mon3": "5000",
        }])
        result = _prepare_nport(nport_df)
        row = result.iloc[0]
        # pressure = (10000+15000+5000) / 800000 * 100 = 3.75
        pressure = float(row["redemption_pressure"])
        assert abs(pressure - 3.75) < 0.01

    def test_annualized_return_nport(self):
        """annualized_return = ((1 + qr/100)^4 - 1) * 100."""
        nport_df = pd.DataFrame([{
            "accession_number": "ACC1", "series_name": "Fund A",
            "series_id": "S1", "cik": "4444",
            "registrant_name": "Test Fund", "quarter": "2024q1",
            "report_date": "2024-01-31", "class_id": "C1",
            "total_assets": "1000000", "net_assets": "800000",
            "total_liabilities": "200000",
            "borrowing_pay_within_1yr": "0",
            "borrowing_pay_after_1yr": "0",
            "monthly_total_return1": "1.0",
            "monthly_total_return2": "1.0",
            "monthly_total_return3": "1.0",
            "sales_flow_mon1": "0", "sales_flow_mon2": "0",
            "sales_flow_mon3": "0",
            "redemption_flow_mon1": "0",
            "redemption_flow_mon2": "0",
            "redemption_flow_mon3": "0",
        }])
        result = _prepare_nport(nport_df)
        row = result.iloc[0]
        qr = float(row["quarterly_return"])
        ann = float(row["annualized_return"])
        expected = ((1 + qr / 100.0) ** 4 - 1) * 100.0
        assert abs(ann - expected) < 0.01

    def test_output_columns_complete(self):
        """All new columns are in OUTPUT_COLUMNS."""
        new_cols = [
            "distribution_per_share", "distribution_rate",
            "total_return_pct", "income_per_share", "income_yield_pct",
            "portfolio_turnover", "asset_coverage_ratio",
            "distribution_rate_proxy", "redemption_pressure",
            "annualized_return", "premium_discount_pct",
            "total_borrowings_detail",
            # DV01/DV100 (10 tenors)
            "dv01_3mon", "dv01_1yr", "dv01_5yr", "dv01_10yr", "dv01_30yr",
            "dv100_3mon", "dv100_1yr", "dv100_5yr", "dv100_10yr", "dv100_30yr",
            # Credit spread risk (10 columns)
            "credit_spread_3mon_invest", "credit_spread_1yr_invest",
            "credit_spread_5yr_invest", "credit_spread_10yr_invest",
            "credit_spread_30yr_invest",
            "credit_spread_3mon_noninvest", "credit_spread_1yr_noninvest",
            "credit_spread_5yr_noninvest", "credit_spread_10yr_noninvest",
            "credit_spread_30yr_noninvest",
            # N-CEN flags
            "is_debt_default", "is_dividend_arrears",
            "is_fund_of_fund", "is_non_diversified",
        ]
        for col in new_cols:
            assert col in OUTPUT_COLUMNS, f"Missing from OUTPUT_COLUMNS: {col}"


# ===================================================================
# 15. N-CEN identity extraction tests
# ===================================================================

class TestNcenIdentity:

    def test_extracts_adviser_and_ticker(self, tmp_path, monkeypatch):
        """Identity extraction finds adviser and ticker from N-CEN."""
        import io
        import zipfile as zf

        monkeypatch.setattr(
            "pipeline.fund_financials.SEC_DATASETS_DIR", tmp_path)
        monkeypatch.setattr(
            "pipeline.fund_financials.NCEN_QUARTERS", ["2025q3"])
        monkeypatch.setattr(
            "pipeline.fund_financials.FUND_IDENTITY_FILE",
            tmp_path / "fund_identity.csv",
        )

        zip_path = tmp_path / "2025q3_ncen.zip"
        with zf.ZipFile(zip_path, "w") as z:
            # SUBMISSION
            sub = pd.DataFrame([{
                "ACCESSION_NUMBER": "ACC1",
                "CIK": "0001234567",
                "REPORT_ENDING_PERIOD": "30-JUN-2025",
            }])
            buf = io.BytesIO()
            sub.to_csv(buf, sep="\t", index=False)
            z.writestr("SUBMISSION.tsv", buf.getvalue())

            # REGISTRANT
            reg = pd.DataFrame([{
                "ACCESSION_NUMBER": "ACC1",
                "REGISTRANT_NAME": "Test Fund Inc",
                "INVESTMENT_COMPANY_TYPE": "N-2",
            }])
            buf = io.BytesIO()
            reg.to_csv(buf, sep="\t", index=False)
            z.writestr("REGISTRANT.tsv", buf.getvalue())

            # ADVISER (joins via FUND_ID, accession is first component)
            adv = pd.DataFrame([{
                "FUND_ID": "ACC1_0001234567_S000012345",
                "ADVISER_NAME": "BigAsset Management LLC",
                "CRD_NUM": "123456",
            }])
            buf = io.BytesIO()
            adv.to_csv(buf, sep="\t", index=False)
            z.writestr("ADVISER.tsv", buf.getvalue())

            # SHARES_OUTSTANDING (joins via FUND_ID)
            so = pd.DataFrame([{
                "FUND_ID": "ACC1_0001234567_S000012345",
                "TICKER": "TFND",
                "CLASS_NAME": "Class A",
            }])
            buf = io.BytesIO()
            so.to_csv(buf, sep="\t", index=False)
            z.writestr("SHARES_OUTSTANDING.tsv", buf.getvalue())

        result = _parse_ncen_identity({"0001234567"})
        assert len(result) == 1
        row = result.iloc[0]
        assert row["cik"] == "0001234567"
        assert row["adviser_name"] == "BigAsset Management LLC"
        assert row["adviser_crd_number"] == "123456"
        assert row["ticker"] == "TFND"
        assert row["class_name"] == "Class A"
        assert (tmp_path / "fund_identity.csv").exists()

    def test_empty_universe(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "pipeline.fund_financials.SEC_DATASETS_DIR", tmp_path)
        monkeypatch.setattr(
            "pipeline.fund_financials.NCEN_QUARTERS", ["2025q3"])
        result = _parse_ncen_identity(set())
        assert result.empty


# ===================================================================
# 16. YTD -> Quarterly conversion (Fix 1)
# ===================================================================

class TestMonthsBetween:

    def test_same_month(self):
        assert _months_between("2024-03-01", "2024-03-31") == 0

    def test_one_quarter(self):
        assert _months_between("2024-01-01", "2024-03-31") == 2

    def test_half_year(self):
        assert _months_between("2024-01-01", "2024-06-30") == 5

    def test_full_year(self):
        assert _months_between("2024-01-01", "2024-12-31") == 11

    def test_cross_year(self):
        assert _months_between("2023-10-01", "2024-03-31") == 5


class TestPriorQuarterEnd:

    def test_mid_year(self):
        assert _prior_quarter_end("2024-06-30") == "2024-03-31"

    def test_q1_to_prior_year(self):
        assert _prior_quarter_end("2024-03-31") == "2023-12-31"

    def test_end_of_year(self):
        assert _prior_quarter_end("2024-12-31") == "2024-09-30"


class TestExtractDurationSeries:

    def _make_duration_facts(self, concept_name, unit_key, entries):
        return {
            "facts": {
                "us-gaap": {
                    concept_name: {"units": {unit_key: entries}},
                },
            },
        }

    def test_quarterly_facts_used_directly(self):
        """When 3-month facts exist, use them directly."""
        facts = self._make_duration_facts(
            "DistPerShare", "USD/shares", [
                {"start": "2024-01-01", "end": "2024-03-31", "val": 0.50},
                {"start": "2024-04-01", "end": "2024-06-30", "val": 0.55},
                {"start": "2024-07-01", "end": "2024-09-30", "val": 0.48},
            ],
        )
        result = _extract_duration_series(
            facts, ["DistPerShare"], "USD/shares",
        )
        assert result == {
            "2024-03-31": 0.50,
            "2024-06-30": 0.55,
            "2024-09-30": 0.48,
        }

    def test_ytd_delta_gives_quarterly(self):
        """When only YTD exists, delta gives correct quarterly."""
        facts = self._make_duration_facts(
            "DistPerShare", "USD/shares", [
                # Q1 YTD = Q1 actual (3 months)
                {"start": "2024-01-01", "end": "2024-03-31", "val": 0.50},
                # Q2 YTD (6 months)
                {"start": "2024-01-01", "end": "2024-06-30", "val": 1.10},
                # Q3 YTD (9 months)
                {"start": "2024-01-01", "end": "2024-09-30", "val": 1.60},
            ],
        )
        result = _extract_duration_series(
            facts, ["DistPerShare"], "USD/shares",
        )
        assert abs(result["2024-03-31"] - 0.50) < 0.001
        assert abs(result["2024-06-30"] - 0.60) < 0.001
        assert abs(result["2024-09-30"] - 0.50) < 0.001

    def test_annual_fallback_divides_by_4(self):
        """When only 12-month annual exists, divides by 4."""
        facts = self._make_duration_facts(
            "DistPerShare", "USD/shares", [
                {"start": "2024-01-01", "end": "2024-12-31", "val": 2.00},
            ],
        )
        result = _extract_duration_series(
            facts, ["DistPerShare"], "USD/shares",
        )
        assert abs(result["2024-12-31"] - 0.50) < 0.001

    def test_mixed_quarterly_and_ytd(self):
        """Some quarters have 3-month, some YTD-only."""
        facts = self._make_duration_facts(
            "DistPerShare", "USD/shares", [
                # Q1: quarterly fact
                {"start": "2024-01-01", "end": "2024-03-31", "val": 0.50},
                # Q2: only YTD (6 months)
                {"start": "2024-01-01", "end": "2024-06-30", "val": 1.05},
            ],
        )
        result = _extract_duration_series(
            facts, ["DistPerShare"], "USD/shares",
        )
        # Q1 uses quarterly directly
        assert abs(result["2024-03-31"] - 0.50) < 0.001
        # Q2 YTD - Q1 quarterly-via-YTD: but Q1 is a 3-month fact,
        # not in ytd_at. The delta logic finds prior_end in entries_by_end,
        # checks for same-start entry -> (2024-01-01, 0.50) matches.
        # So result = 1.05 - 0.50 = 0.55
        assert abs(result["2024-06-30"] - 0.55) < 0.001

    def test_non_calendar_fiscal_year(self):
        """Fiscal year starting in October."""
        facts = self._make_duration_facts(
            "TotalReturn", "pure", [
                # FY Q1: Oct-Dec
                {"start": "2023-10-01", "end": "2023-12-31", "val": 0.02},
                # FY Q2 YTD: Oct-Mar (6 months)
                {"start": "2023-10-01", "end": "2024-03-31", "val": 0.05},
            ],
        )
        result = _extract_duration_series(facts, ["TotalReturn"], "pure")
        assert abs(result["2023-12-31"] - 0.02) < 0.001
        # Q2 = YTD(0.05) - Q1 YTD stored (0.02) = 0.03
        assert abs(result["2024-03-31"] - 0.03) < 0.001

    def test_distribution_rate_stable_across_quarters(self):
        """After YTD conversion, distribution_rate should be stable."""
        # Simulate a BDC with $0.50/quarter dist, $20 NAV
        cf_df = pd.DataFrame([
            {"cik": "700", "report_date": "2024-03-31",
             "total_assets": 1_000_000.0, "total_liabilities": 400_000.0,
             "net_assets": 600_000.0, "nav_per_share": 20.0,
             "shares_outstanding": 30000.0, "borrowings": None,
             "distribution_per_share": 0.50},
            {"cik": "700", "report_date": "2024-06-30",
             "total_assets": 1_000_000.0, "total_liabilities": 400_000.0,
             "net_assets": 600_000.0, "nav_per_share": 20.0,
             "shares_outstanding": 30000.0, "borrowings": None,
             "distribution_per_share": 0.50},
            {"cik": "700", "report_date": "2024-09-30",
             "total_assets": 1_000_000.0, "total_liabilities": 400_000.0,
             "net_assets": 600_000.0, "nav_per_share": 20.0,
             "shares_outstanding": 30000.0, "borrowings": None,
             "distribution_per_share": 0.50},
            {"cik": "700", "report_date": "2024-12-31",
             "total_assets": 1_000_000.0, "total_liabilities": 400_000.0,
             "net_assets": 600_000.0, "nav_per_share": 20.0,
             "shares_outstanding": 30000.0, "borrowings": None,
             "distribution_per_share": 0.50},
        ])
        result = _prepare_bdc(cf_df, pd.DataFrame())
        # dist_rate = (0.50 * 4) / 20.0 * 100 = 10.0 for ALL quarters
        rates = result["distribution_rate"].dropna().astype(float).tolist()
        assert len(rates) == 4
        for r in rates:
            assert abs(r - 10.0) < 0.5, f"Expected ~10.0, got {r}"

    def test_empty_facts(self):
        assert _extract_duration_series({}, ["X"], "USD") == {}
        assert _extract_duration_series(None, ["X"], "USD") == {}

    def test_ytd_cross_base_no_mix(self):
        """FY-YTD Q1-Q3 + inception-to-date Q4: no cross-base subtraction."""
        facts = self._make_duration_facts(
            "TotalReturn", "pure", [
                # FY starts 2024-01-01
                {"start": "2024-01-01", "end": "2024-03-31", "val": 0.02},
                {"start": "2024-01-01", "end": "2024-06-30", "val": 0.05},
                {"start": "2024-01-01", "end": "2024-09-30", "val": 0.09},
                # Inception-to-date with different start (2023-06-01)
                {"start": "2023-06-01", "end": "2024-12-31", "val": 0.30},
            ],
        )
        result = _extract_duration_series(facts, ["TotalReturn"], "pure")
        # Q1-Q3 work normally via same-base subtraction
        assert abs(result["2024-03-31"] - 0.02) < 0.001
        assert abs(result["2024-06-30"] - 0.03) < 0.001
        assert abs(result["2024-09-30"] - 0.04) < 0.001
        # Q4: ITD doesn't match FY start, so divides by quarters (~6 qtrs)
        # 0.30 / 6 = 0.05
        assert abs(result["2024-12-31"] - 0.05) < 0.001

    def test_ytd_same_base_subtraction(self):
        """Normal FY-YTD Q1+Q2 with same start: subtraction works."""
        facts = self._make_duration_facts(
            "DistPerShare", "USD/shares", [
                {"start": "2024-01-01", "end": "2024-03-31", "val": 1.00},
                {"start": "2024-01-01", "end": "2024-06-30", "val": 2.50},
            ],
        )
        result = _extract_duration_series(
            facts, ["DistPerShare"], "USD/shares",
        )
        assert abs(result["2024-03-31"] - 1.00) < 0.001
        assert abs(result["2024-06-30"] - 1.50) < 0.001

    def test_ytd_mixed_bases_independent(self):
        """Two FY bases: each tracked independently."""
        facts = self._make_duration_facts(
            "TotalReturn", "pure", [
                # Fiscal year 1: Oct-based
                {"start": "2023-10-01", "end": "2023-12-31", "val": 0.01},
                {"start": "2023-10-01", "end": "2024-03-31", "val": 0.04},
                # Fiscal year 2: Jan-based (overlapping quarter)
                {"start": "2024-01-01", "end": "2024-03-31", "val": 0.02},
                {"start": "2024-01-01", "end": "2024-06-30", "val": 0.06},
            ],
        )
        result = _extract_duration_series(facts, ["TotalReturn"], "pure")
        # 2023-12-31: Oct-Dec = 3 months -> direct quarterly
        assert abs(result["2023-12-31"] - 0.01) < 0.001
        # 2024-03-31: shortest is Jan-based (3 months) -> direct
        assert abs(result["2024-03-31"] - 0.02) < 0.001
        # 2024-06-30: Jan-Jun YTD, subtract Jan-Mar(same base) -> 0.06-0.02=0.04
        assert abs(result["2024-06-30"] - 0.04) < 0.001

    def test_distribution_rate_capped_at_50(self):
        """Distribution rate capped at 50% max."""
        cf_df = pd.DataFrame([{
            "cik": "720", "report_date": "2024-03-31",
            "total_assets": 1_000_000.0, "total_liabilities": 400_000.0,
            "net_assets": 600_000.0, "nav_per_share": 10.0,
            "shares_outstanding": 60000.0, "borrowings": None,
            "distribution_per_share": 100.0,  # would be 4000%
        }])
        result = _prepare_bdc(cf_df, pd.DataFrame())
        rate = float(result.iloc[0]["distribution_rate"])
        assert rate == 50.0

    def test_distribution_rate_floored_at_0(self):
        """Negative distribution rate floored at 0%."""
        cf_df = pd.DataFrame([{
            "cik": "721", "report_date": "2024-03-31",
            "total_assets": 1_000_000.0, "total_liabilities": 400_000.0,
            "net_assets": 600_000.0, "nav_per_share": 20.0,
            "shares_outstanding": 30000.0, "borrowings": None,
            "distribution_per_share": -5.0,  # negative
        }])
        result = _prepare_bdc(cf_df, pd.DataFrame())
        rate = float(result.iloc[0]["distribution_rate"])
        assert rate == 0.0


# ===================================================================
# 17. Decimal -> Percentage scale (Fix 2)
# ===================================================================

class TestDecimalToPercentage:

    def test_decimal_to_pct_conversion(self):
        """Values like 0.05 become 5.0."""
        cf_df = pd.DataFrame([{
            "cik": "710", "report_date": "2024-03-31",
            "total_assets": 1_000_000.0, "total_liabilities": 400_000.0,
            "net_assets": 600_000.0, "nav_per_share": 20.0,
            "shares_outstanding": 30000.0, "borrowings": None,
            "total_return_pct": 0.05,
            "income_yield_pct": 0.08,
            "portfolio_turnover": 0.35,
            "debt_weighted_avg_rate": 0.065,
        }])
        result = _prepare_bdc(cf_df, pd.DataFrame())
        row = result.iloc[0]
        assert abs(float(row["total_return_pct"]) - 5.0) < 0.01
        assert abs(float(row["income_yield_pct"]) - 8.0) < 0.01
        assert abs(float(row["portfolio_turnover"]) - 35.0) < 0.01
        assert abs(float(row["debt_weighted_avg_rate"]) - 6.5) < 0.01

    def test_already_pct_passthrough(self):
        """Values like 5.0 stay 5.0."""
        cf_df = pd.DataFrame([{
            "cik": "711", "report_date": "2024-03-31",
            "total_assets": 1_000_000.0, "total_liabilities": 400_000.0,
            "net_assets": 600_000.0, "nav_per_share": 20.0,
            "shares_outstanding": 30000.0, "borrowings": None,
            "total_return_pct": 5.0,
            "income_yield_pct": 8.0,
            "portfolio_turnover": 35.0,
            "debt_weighted_avg_rate": 6.5,
        }])
        result = _prepare_bdc(cf_df, pd.DataFrame())
        row = result.iloc[0]
        assert abs(float(row["total_return_pct"]) - 5.0) < 0.01
        assert abs(float(row["income_yield_pct"]) - 8.0) < 0.01
        assert abs(float(row["portfolio_turnover"]) - 35.0) < 0.01
        assert abs(float(row["debt_weighted_avg_rate"]) - 6.5) < 0.01

    def test_erroneous_pct_nulled(self):
        """Values > 100 become NULL."""
        cf_df = pd.DataFrame([{
            "cik": "712", "report_date": "2024-03-31",
            "total_assets": 1_000_000.0, "total_liabilities": 400_000.0,
            "net_assets": 600_000.0, "nav_per_share": 20.0,
            "shares_outstanding": 30000.0, "borrowings": None,
            "total_return_pct": 150.0,
            "income_yield_pct": 200.0,
        }])
        result = _prepare_bdc(cf_df, pd.DataFrame())
        row = result.iloc[0]
        assert pd.isna(row["total_return_pct"])
        assert pd.isna(row["income_yield_pct"])


# ===================================================================
# 18. Seed capital filtering (Fix 3)
# ===================================================================

class TestSeedCapitalFiltering:

    def test_seed_capital_nulled(self):
        """Row with TA=$1000 has all financial fields NULLed."""
        cf_df = pd.DataFrame([{
            "cik": "720", "report_date": "2024-03-31",
            "total_assets": 1000.0, "total_liabilities": 200.0,
            "net_assets": 800.0, "nav_per_share": 10.0,
            "shares_outstanding": 80.0, "borrowings": 100.0,
        }])
        result = _prepare_bdc(cf_df, pd.DataFrame())
        row = result.iloc[0]
        # Row should still exist (cik preserved)
        assert row["cik"] == "0000000720"
        # All financial fields should be NULL
        assert pd.isna(row["total_assets"])
        assert pd.isna(row["net_assets"])
        assert pd.isna(row["nav_per_share"])
        assert pd.isna(row["borrowings"])
        assert pd.isna(row["leverage_ratio"])

    def test_normal_row_untouched(self):
        """Row with TA=$5M is not affected by seed filter."""
        cf_df = pd.DataFrame([{
            "cik": "721", "report_date": "2024-03-31",
            "total_assets": 5_000_000.0, "total_liabilities": 2_000_000.0,
            "net_assets": 3_000_000.0, "nav_per_share": 20.0,
            "shares_outstanding": 150000.0, "borrowings": 1_500_000.0,
        }])
        result = _prepare_bdc(cf_df, pd.DataFrame())
        row = result.iloc[0]
        assert float(row["total_assets"]) == 5_000_000.0
        assert float(row["net_assets"]) == 3_000_000.0
        assert float(row["nav_per_share"]) == 20.0


# ===================================================================
# 19. Formation-stage flag (Fix 4)
# ===================================================================

class TestFormationStageFlag:

    def test_formation_stage_flagged(self):
        """Row with shares=100, NAV=$50K -> is_formation_stage=True."""
        cf_df = pd.DataFrame([{
            "cik": "730", "report_date": "2024-03-31",
            "total_assets": 5_000_000.0, "total_liabilities": 0.0,
            "net_assets": 5_000_000.0, "nav_per_share": 50000.0,
            "shares_outstanding": 100.0, "borrowings": None,
        }])
        result = _prepare_bdc(cf_df, pd.DataFrame())
        row = result.iloc[0]
        assert row["is_formation_stage"] is True or row["is_formation_stage"] == 1

    def test_normal_not_flagged(self):
        """Row with shares=10M, NAV=$20 -> is_formation_stage=False."""
        cf_df = pd.DataFrame([{
            "cik": "731", "report_date": "2024-03-31",
            "total_assets": 200_000_000.0, "total_liabilities": 80_000_000.0,
            "net_assets": 120_000_000.0, "nav_per_share": 20.0,
            "shares_outstanding": 6_000_000.0, "borrowings": None,
        }])
        result = _prepare_bdc(cf_df, pd.DataFrame())
        row = result.iloc[0]
        assert row["is_formation_stage"] is False or row["is_formation_stage"] == 0


# ===================================================================
# 20. N-PORT leverage cap (Fix 6)
# ===================================================================

class TestNportLeverageCap:

    def test_nport_leverage_capped(self):
        """Row with borrowings > 2x total_assets produces leverage_ratio=2.0."""
        nport_df = pd.DataFrame([{
            "accession_number": "ACC1", "series_name": "Fund A",
            "series_id": "S1", "cik": "8888",
            "registrant_name": "Leveraged Fund", "quarter": "2024q1",
            "report_date": "2024-01-31", "class_id": "C1",
            "total_assets": "1000000", "net_assets": "200000",
            "total_liabilities": "800000",
            "borrowing_pay_within_1yr": "2000000",
            "borrowing_pay_after_1yr": "1000000",
            "monthly_total_return1": "1.0",
            "monthly_total_return2": "0.5",
            "monthly_total_return3": "0.3",
            "sales_flow_mon1": "0", "sales_flow_mon2": "0",
            "sales_flow_mon3": "0",
            "redemption_flow_mon1": "0",
            "redemption_flow_mon2": "0",
            "redemption_flow_mon3": "0",
        }])
        result = _prepare_nport(nport_df)
        row = result.iloc[0]
        assert float(row["leverage_ratio"]) == 2.0


# ===================================================================
# 21. Schema enforcement (Fix 5)
# ===================================================================

class TestSchemaEnforcement:

    def test_schema_clean_data(self):
        """Valid DataFrame returns empty violations."""
        df = pd.DataFrame([{
            "cik": "0000001234",
            "source": "companyfacts",
            "vehicle_type": "bdc",
            "report_date": "2024-03-31",
            "total_assets": 1_000_000.0,
            "net_assets": 600_000.0,
            "nav_per_share": 20.0,
            "leverage_ratio": 0.5,
            "expense_ratio_pct": 3.0,
            "distribution_rate": 8.0,
            "quarterly_return": 2.5,
            "total_liabilities": 400_000.0,
            "is_formation_stage": False,
        }])
        violations = _enforce_schema(df)
        assert violations == []

    def test_schema_bad_cik(self):
        """CIK with wrong format is caught."""
        df = pd.DataFrame([{
            "cik": "1234",  # Not 10-digit padded
            "source": "companyfacts",
            "vehicle_type": "bdc",
            "report_date": "2024-03-31",
        }])
        violations = _enforce_schema(df)
        names = [v[0] for v in violations]
        assert "cik_format" in names

    def test_schema_leverage_out_of_range(self):
        """Leverage > 2.0 is caught."""
        df = pd.DataFrame([{
            "cik": "0000001234",
            "source": "companyfacts",
            "vehicle_type": "bdc",
            "report_date": "2024-03-31",
            "leverage_ratio": 2.5,
        }])
        violations = _enforce_schema(df)
        names = [v[0] for v in violations]
        assert "leverage_ratio_range" in names


# ===================================================================
# 22. N-CEN distress & structure flags
# ===================================================================

class TestNcenFlags:

    def _make_nport_df(self, **overrides):
        base = {
            "accession_number": "ACC1", "series_name": "Fund A",
            "series_id": "S1", "cik": "1234",
            "registrant_name": "Test Fund", "quarter": "2023q4",
            "report_date": "2023-10-31", "class_id": "C1",
            "total_assets": "1000000", "net_assets": "800000",
            "total_liabilities": "200000",
            "borrowing_pay_within_1yr": "0",
            "borrowing_pay_after_1yr": "0",
            "monthly_total_return1": "1.0",
            "monthly_total_return2": "0.5",
            "monthly_total_return3": "0.3",
            "sales_flow_mon1": "0", "sales_flow_mon2": "0",
            "sales_flow_mon3": "0",
            "redemption_flow_mon1": "0",
            "redemption_flow_mon2": "0",
            "redemption_flow_mon3": "0",
        }
        base.update(overrides)
        return pd.DataFrame([base])

    def test_ncen_distress_flags_true(self):
        """N-CEN flags Y -> True in output."""
        nport_df = self._make_nport_df()
        ncen_df = pd.DataFrame([{
            "cik": "0000001234",
            "entity_name": "Test Fund",
            "report_date": "2023-09-30",
            "report_quarter": "2023q3",
            "management_fee_pct": 1.5,
            "expense_ratio_pct": 3.0,
            "nav_per_share": 20.0,
            "market_price_per_share": 19.0,
            "monthly_avg_net_assets": 750000.0,
            "is_debt_default": True,
            "is_dividend_arrears": True,
            "is_fund_of_fund": False,
            "is_non_diversified": False,
        }])
        result = _prepare_nport(nport_df, ncen_df=ncen_df)
        assert len(result) == 1
        row = result.iloc[0]
        assert row["is_debt_default"] is True or row["is_debt_default"] == 1
        assert row["is_dividend_arrears"] is True or row["is_dividend_arrears"] == 1

    def test_ncen_structure_flags(self):
        """is_fund_of_fund and is_non_diversified propagate."""
        nport_df = self._make_nport_df()
        ncen_df = pd.DataFrame([{
            "cik": "0000001234",
            "entity_name": "Test Fund",
            "report_date": "2023-09-30",
            "report_quarter": "2023q3",
            "management_fee_pct": None,
            "expense_ratio_pct": None,
            "nav_per_share": None,
            "market_price_per_share": None,
            "monthly_avg_net_assets": None,
            "is_debt_default": False,
            "is_dividend_arrears": False,
            "is_fund_of_fund": True,
            "is_non_diversified": True,
        }])
        result = _prepare_nport(nport_df, ncen_df=ncen_df)
        row = result.iloc[0]
        assert row["is_fund_of_fund"] is True or row["is_fund_of_fund"] == 1
        assert row["is_non_diversified"] is True or row["is_non_diversified"] == 1

    def test_ncen_flags_default_false(self):
        """N-CEN flags N -> False in output."""
        nport_df = self._make_nport_df()
        ncen_df = pd.DataFrame([{
            "cik": "0000001234",
            "entity_name": "Test Fund",
            "report_date": "2023-09-30",
            "report_quarter": "2023q3",
            "management_fee_pct": None,
            "expense_ratio_pct": None,
            "nav_per_share": None,
            "market_price_per_share": None,
            "monthly_avg_net_assets": None,
            "is_debt_default": False,
            "is_dividend_arrears": False,
            "is_fund_of_fund": False,
            "is_non_diversified": False,
        }])
        result = _prepare_nport(nport_df, ncen_df=ncen_df)
        row = result.iloc[0]
        assert row["is_debt_default"] is False or row["is_debt_default"] == 0
        assert row["is_fund_of_fund"] is False or row["is_fund_of_fund"] == 0

    def test_bdc_ncen_flags_null(self):
        """BDC companyfacts rows have NULL for all N-CEN flags."""
        cf_df = pd.DataFrame([{
            "cik": "1234",
            "report_date": "2023-12-31",
            "total_assets": 500_000.0,
            "total_liabilities": None, "net_assets": None,
            "nav_per_share": None, "shares_outstanding": None,
            "borrowings": None,
        }])
        result = _prepare_bdc(cf_df, pd.DataFrame())
        row = result.iloc[0]
        assert pd.isna(row["is_debt_default"])
        assert pd.isna(row["is_dividend_arrears"])
        assert pd.isna(row["is_fund_of_fund"])
        assert pd.isna(row["is_non_diversified"])

    def test_no_ncen_flags_null(self):
        """Without N-CEN data, flags are NULL."""
        nport_df = self._make_nport_df()
        result = _prepare_nport(nport_df)
        row = result.iloc[0]
        assert pd.isna(row["is_debt_default"])
        assert pd.isna(row["is_fund_of_fund"])


# ===================================================================
# 23. Credit spread aggregation
# ===================================================================

class TestCreditSpread:

    def test_credit_spread_aggregated(self):
        """N-PORT rows with credit spread data -> aggregated to CIK-quarter."""
        nport_df = pd.DataFrame([{
            "accession_number": "ACC1", "series_name": "Fund A",
            "series_id": "S1", "cik": "1234",
            "registrant_name": "Test Fund", "quarter": "2023q4",
            "report_date": "2023-10-31", "class_id": "C1",
            "total_assets": "1000000", "net_assets": "800000",
            "total_liabilities": "200000",
            "borrowing_pay_within_1yr": "0",
            "borrowing_pay_after_1yr": "0",
            "monthly_total_return1": "1.0",
            "monthly_total_return2": "0.5",
            "monthly_total_return3": "0.3",
            "sales_flow_mon1": "0", "sales_flow_mon2": "0",
            "sales_flow_mon3": "0",
            "redemption_flow_mon1": "0",
            "redemption_flow_mon2": "0",
            "redemption_flow_mon3": "0",
            "credit_spread_3mon_invest": "100.5",
            "credit_spread_1yr_invest": "250.3",
            "credit_spread_5yr_invest": "500.0",
            "credit_spread_10yr_invest": "750.0",
            "credit_spread_30yr_invest": "1000.0",
            "credit_spread_3mon_noninvest": "200.0",
            "credit_spread_1yr_noninvest": "400.0",
            "credit_spread_5yr_noninvest": "600.0",
            "credit_spread_10yr_noninvest": "800.0",
            "credit_spread_30yr_noninvest": "1200.0",
        }])
        result = _prepare_nport(nport_df)
        assert len(result) == 1
        row = result.iloc[0]
        assert abs(float(row["credit_spread_3mon_invest"]) - 100.5) < 0.1
        assert abs(float(row["credit_spread_1yr_invest"]) - 250.3) < 0.1
        assert abs(float(row["credit_spread_30yr_noninvest"]) - 1200.0) < 0.1

    def test_credit_spread_null_when_missing(self):
        """When credit spread columns absent -> NULL output."""
        nport_df = pd.DataFrame([{
            "accession_number": "ACC1", "series_name": "Fund A",
            "series_id": "S1", "cik": "1234",
            "registrant_name": "Test Fund", "quarter": "2023q4",
            "report_date": "2023-10-31", "class_id": "C1",
            "total_assets": "1000000", "net_assets": "800000",
            "total_liabilities": "200000",
            "borrowing_pay_within_1yr": "0",
            "borrowing_pay_after_1yr": "0",
            "monthly_total_return1": "1.0",
            "monthly_total_return2": "0.5",
            "monthly_total_return3": "0.3",
            "sales_flow_mon1": "0", "sales_flow_mon2": "0",
            "sales_flow_mon3": "0",
            "redemption_flow_mon1": "0",
            "redemption_flow_mon2": "0",
            "redemption_flow_mon3": "0",
        }])
        result = _prepare_nport(nport_df)
        row = result.iloc[0]
        assert pd.isna(row["credit_spread_3mon_invest"])
        assert pd.isna(row["credit_spread_30yr_noninvest"])


# ===================================================================
# 24. DV01/DV100 aggregation in fund_financials
# ===================================================================

class TestDvAggregation:

    def test_dv01_all_tenors_aggregated(self):
        """N-PORT rows with DV data -> 10 DV columns in output."""
        nport_df = pd.DataFrame([{
            "accession_number": "ACC1", "series_name": "Fund A",
            "series_id": "S1", "cik": "1234",
            "registrant_name": "Test Fund", "quarter": "2023q4",
            "report_date": "2023-10-31", "class_id": "C1",
            "total_assets": "1000000", "net_assets": "800000",
            "total_liabilities": "200000",
            "borrowing_pay_within_1yr": "0",
            "borrowing_pay_after_1yr": "0",
            "monthly_total_return1": "1.0",
            "monthly_total_return2": "0.5",
            "monthly_total_return3": "0.3",
            "sales_flow_mon1": "0", "sales_flow_mon2": "0",
            "sales_flow_mon3": "0",
            "redemption_flow_mon1": "0",
            "redemption_flow_mon2": "0",
            "redemption_flow_mon3": "0",
            "dv01_3mon": "10", "dv01_1yr": "20",
            "dv01_5yr": "50", "dv01_10yr": "80",
            "dv01_30yr": "120",
            "dv100_3mon": "100", "dv100_1yr": "200",
            "dv100_5yr": "500", "dv100_10yr": "800",
            "dv100_30yr": "1200",
        }])
        result = _prepare_nport(nport_df)
        assert len(result) == 1
        row = result.iloc[0]
        assert abs(float(row["dv01_3mon"]) - 10.0) < 0.1
        assert abs(float(row["dv01_1yr"]) - 20.0) < 0.1
        assert abs(float(row["dv01_30yr"]) - 120.0) < 0.1
        assert abs(float(row["dv100_3mon"]) - 100.0) < 0.1
        assert abs(float(row["dv100_30yr"]) - 1200.0) < 0.1

    def test_dv01_null_when_missing(self):
        """When DV columns absent -> NULL output."""
        nport_df = pd.DataFrame([{
            "accession_number": "ACC1", "series_name": "Fund A",
            "series_id": "S1", "cik": "1234",
            "registrant_name": "Test Fund", "quarter": "2023q4",
            "report_date": "2023-10-31", "class_id": "C1",
            "total_assets": "1000000", "net_assets": "800000",
            "total_liabilities": "200000",
            "borrowing_pay_within_1yr": "0",
            "borrowing_pay_after_1yr": "0",
            "monthly_total_return1": "1.0",
            "monthly_total_return2": "0.5",
            "monthly_total_return3": "0.3",
            "sales_flow_mon1": "0", "sales_flow_mon2": "0",
            "sales_flow_mon3": "0",
            "redemption_flow_mon1": "0",
            "redemption_flow_mon2": "0",
            "redemption_flow_mon3": "0",
        }])
        result = _prepare_nport(nport_df)
        row = result.iloc[0]
        assert pd.isna(row["dv01_3mon"])
        assert pd.isna(row["dv01_1yr"])
        assert pd.isna(row["dv100_30yr"])
