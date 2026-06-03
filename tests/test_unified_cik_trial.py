"""Tests for one-CIK trial rebuild and oracle --holdings-file support."""

import pytest
import pandas as pd
from pathlib import Path
from unittest.mock import patch

from pipeline.unified_holdings import build_unified_holdings, UNIFIED_COLUMNS


# ---------------------------------------------------------------------------
# Fixtures: minimal BDC and N-PORT DataFrames
# ---------------------------------------------------------------------------

def _make_bdc_df(cik: str = "123"):
    return pd.DataFrame([
        {
            "cik": cik, "entity_name": "Test BDC",
            "accession_number": "0001-23", "form_type": "10-K",
            "filing_date": "2023-06-01", "report_date": "2023-03-31",
            "investment_identifier": "Acme Corp - First Lien Term Loan",
            "fair_value": 1000000.0, "cost": 990000.0,
            "principal_amount": 1000000.0, "interest_rate": 8.5,
            "basis_spread": 3.5, "reference_rate_type": "SOFR",
            "maturity_date": "2028-01-15", "pct_of_net_assets": 0.05,
            "pik_rate": None, "shares_held": None,
            "unrealized_gain_loss": 10000.0, "dimensions_raw": "x=y",
            "investment_type": "", "industry": "", "affiliation": "",
            "period": "2023-03-31",
        },
    ])


def _make_nport_df(cik: str = "456"):
    return pd.DataFrame([
        {
            "accession_number": "0002-45", "holding_id": "H001",
            "issuer_name": "Private Borrower LLC",
            "issuer_lei": "LEI123", "issuer_title": "Senior Secured Loan",
            "issuer_cusip": "ABC123", "currency_value": 2000000.0,
            "percentage": 0.03, "asset_cat": "LON", "issuer_type": "CORP",
            "investment_country": "US", "is_restricted_security": "Y",
            "fair_value_level": 3, "maturity_date": "2027-06-15",
            "coupon_type": "Floating", "annualized_rate": 9.0,
            "identifier_isin": "US_ISIN_1", "identifier_ticker": "",
            "payoff_profile": "Long", "cik": cik,
            "registrant_name": "Test Interval Fund",
            "filing_date": "2023-07-15", "report_date": "2023-06-30",
            "series_name": "Test Series", "series_id": "S001",
            "quarter": "2023q2", "balance": 2000000, "unit": "PA",
            "other_unit_desc": "", "exchange_rate": None,
            "other_asset": "", "other_issuer": "", "sub_type": "",
            "derivative_cat": "", "is_default": "N",
            "other_identifier": "", "currency_code": "USD",
        },
    ])


# ---------------------------------------------------------------------------
# build_unified_holdings alternate output paths
# ---------------------------------------------------------------------------

class TestAlternateOutputPaths:
    pytestmark = [pytest.mark.slow, pytest.mark.integration]

    def test_writes_to_custom_output_file(self, tmp_path):
        """output_file parameter directs CSV and parquet to the custom path."""
        out_csv = tmp_path / "trial" / "holdings.csv"
        out_orphan = tmp_path / "trial" / "orphans.csv"

        result = build_unified_holdings(
            bdc_df=_make_bdc_df(),
            nport_df=_make_nport_df(),
            output_file=out_csv,
            orphan_file=out_orphan,
        )

        assert out_csv.exists(), "Trial CSV was not written"
        assert out_csv.with_suffix(".parquet").exists(), "Trial parquet was not written"
        assert out_orphan.exists(), "Trial orphan file was not written"
        # Fixture CIKs may be removed by universe gate; the key assertion
        # is that files were written to the custom paths, not production.

    def test_default_path_unchanged_when_no_custom(self, tmp_path):
        """When output_file is not passed, the function still uses the default
        constant.  We patch the constant to tmp_path to verify."""
        default_out = tmp_path / "default_output.csv"

        with patch("pipeline.unified_holdings.UNIFIED_HOLDINGS_FILE", default_out):
            result = build_unified_holdings(
                bdc_df=_make_bdc_df(),
                nport_df=_make_nport_df(),
            )

        assert default_out.exists(), "Default path should be used when output_file is None"
        assert len(result) > 0

    def test_empty_input_writes_to_custom_path(self, tmp_path):
        """Even with empty inputs, the function should write to the custom path."""
        out_csv = tmp_path / "empty" / "holdings.csv"
        out_orphan = tmp_path / "empty" / "orphans.csv"

        result = build_unified_holdings(
            bdc_df=pd.DataFrame(),
            nport_df=pd.DataFrame(),
            output_file=out_csv,
            orphan_file=out_orphan,
        )

        assert out_csv.exists()
        assert out_orphan.exists()
        assert len(result) == 0


# ---------------------------------------------------------------------------
# Oracle --holdings-file mutual exclusion
# ---------------------------------------------------------------------------

class TestOracleHoldingsFileMutualExclusion:

    def test_fresh_staging_and_holdings_file_raises(self):
        """--fresh-bdc-staging and --holdings-file are mutually exclusive."""
        from pipeline.bdc_xbrl_wrapper_oracle import run_wrapper_oracle_trial

        with pytest.raises(ValueError, match="mutually exclusive"):
            run_wrapper_oracle_trial(
                cik="0001786108",
                fresh_bdc_staging=True,
                holdings_file=Path("dummy.csv"),
            )

    def test_cli_rejects_both_flags(self):
        """The CLI parser rejects --fresh-bdc-staging with --holdings-file."""
        from pipeline.bdc_xbrl_wrapper_oracle import main

        with pytest.raises(SystemExit):
            main(["--cik", "0001786108", "--fresh-bdc-staging",
                  "--holdings-file", "dummy.csv"])

    def test_holdings_file_not_found_raises(self):
        """--holdings-file with a nonexistent path raises FileNotFoundError."""
        from pipeline.bdc_xbrl_wrapper_oracle import run_wrapper_oracle_trial

        with pytest.raises(FileNotFoundError, match="Holdings file not found"):
            run_wrapper_oracle_trial(
                cik="0001786108",
                holdings_file=Path("nonexistent.csv"),
            )


# ---------------------------------------------------------------------------
# Trial rebuild script CLI
# ---------------------------------------------------------------------------

class TestTrialRebuildScript:

    def test_missing_cik_exits_nonzero(self):
        """Script should fail when --cik is not provided."""
        import scripts.rebuild_unified_cik_trial as script

        with pytest.raises(SystemExit) as exc_info:
            script.main([])
        assert exc_info.value.code != 0
