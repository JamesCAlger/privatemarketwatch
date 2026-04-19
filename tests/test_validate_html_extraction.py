"""Tests for pipeline.validate_html_extraction module."""

import math
from unittest.mock import patch, MagicMock

import pandas as pd
import pytest

from pipeline.validate_html_extraction import (
    _extract_xbrl_company_name,
    _maturity_match,
    _normalize_name,
    _safe_float,
    compare_filing,
    match_positions,
)


# ---------------------------------------------------------------------------
# _normalize_name
# ---------------------------------------------------------------------------

class TestNormalizeName:
    def test_basic(self):
        assert _normalize_name("Acme Corp") == "acme corp"

    def test_whitespace_collapse(self):
        assert _normalize_name("  Acme   Corp  ") == "acme corp"

    def test_trailing_comma(self):
        assert _normalize_name("Acme Corp,") == "acme corp"

    def test_trailing_semicolon(self):
        assert _normalize_name("Acme Corp;") == "acme corp"

    def test_empty(self):
        assert _normalize_name("") == ""

    def test_none(self):
        assert _normalize_name(None) == ""

    def test_not_string(self):
        assert _normalize_name(123) == ""

    def test_preserves_internal_punctuation(self):
        assert _normalize_name("S&P Global, Inc.") == "s&p global, inc."


# ---------------------------------------------------------------------------
# _extract_xbrl_company_name
# ---------------------------------------------------------------------------

class TestExtractXbrlCompanyName:
    def test_pipe_affiliation_format(self):
        """'Company | Instrument | Affiliation' -> Company."""
        result = _extract_xbrl_company_name(
            "Acme Corp | Senior Secured Loan | Non-Controlled/Non-Affiliated"
        )
        assert result == "Acme Corp"

    def test_pipe_two_segment(self):
        """'Company | Instrument' -> Company."""
        result = _extract_xbrl_company_name("Acme Corp | First Lien Term Loan")
        assert result == "Acme Corp"

    def test_pipe_three_segment_no_affil(self):
        """'Company | Industry | Instrument' -> Company (first segment)."""
        result = _extract_xbrl_company_name(
            "Acme Corp | Technology | First Lien Term Loan"
        )
        assert result == "Acme Corp"

    def test_dash_format(self):
        """'Company - Instrument' -> Company."""
        result = _extract_xbrl_company_name(
            "Acme Corp - Senior Secured First Lien"
        )
        assert result == "Acme Corp"

    def test_plain_name(self):
        """Plain name without separators."""
        result = _extract_xbrl_company_name("Acme Corp LLC")
        assert result == "Acme Corp LLC"

    def test_empty(self):
        assert _extract_xbrl_company_name("") == ""

    def test_none(self):
        assert _extract_xbrl_company_name(None) == ""


# ---------------------------------------------------------------------------
# _safe_float
# ---------------------------------------------------------------------------

class TestSafeFloat:
    def test_valid_number(self):
        assert _safe_float(42.5) == 42.5

    def test_string_number(self):
        assert _safe_float("123.45") == 123.45

    def test_none(self):
        assert _safe_float(None) is None

    def test_nan(self):
        assert _safe_float(float("nan")) is None

    def test_invalid_string(self):
        assert _safe_float("not_a_number") is None

    def test_zero(self):
        assert _safe_float(0) == 0.0


# ---------------------------------------------------------------------------
# _maturity_match
# ---------------------------------------------------------------------------

class TestMaturityMatch:
    def test_exact_match(self):
        assert _maturity_match("2025-06-15", "2025-06-15") is True

    def test_same_month(self):
        assert _maturity_match("2025-06-15", "2025-06-30") is True

    def test_different_month(self):
        assert _maturity_match("2025-06-15", "2025-08-15") is False

    def test_empty_strings(self):
        assert _maturity_match("", "") is True  # both empty = exact match

    def test_one_month_apart(self):
        assert _maturity_match("2025-06-30", "2025-07-01") is True


# ---------------------------------------------------------------------------
# match_positions
# ---------------------------------------------------------------------------

class TestMatchPositions:
    def test_exact_matches(self):
        html = [
            {"investment_identifier": "Acme Corp", "fair_value": 1000},
            {"investment_identifier": "Beta Inc", "fair_value": 2000},
        ]
        xbrl = [
            {"investment_identifier": "Acme Corp | First Lien | Non-Controlled/Non-Affiliated", "fair_value": 1000},
            {"investment_identifier": "Beta Inc | Second Lien | Non-Controlled/Non-Affiliated", "fair_value": 2000},
        ]
        matched, h_un, x_un = match_positions(html, xbrl)
        assert len(matched) == 2
        assert len(h_un) == 0
        assert len(x_un) == 0

    def test_fuzzy_matches(self):
        html = [
            {"investment_identifier": "Acme Corporation", "fair_value": 1000},
        ]
        xbrl = [
            {"investment_identifier": "Acme Corp | Loan | Non-Controlled/Non-Affiliated", "fair_value": 1000},
        ]
        matched, h_un, x_un = match_positions(html, xbrl)
        assert len(matched) == 1
        assert matched[0]["name_score"] > 50

    def test_unmatched_positions(self):
        html = [
            {"investment_identifier": "Acme Corp", "fair_value": 1000},
            {"investment_identifier": "Gamma LLC", "fair_value": 3000},
        ]
        xbrl = [
            {"investment_identifier": "Acme Corp | Loan | Non-Controlled/Non-Affiliated", "fair_value": 1000},
            {"investment_identifier": "Delta Holdings | Loan | Non-Controlled/Non-Affiliated", "fair_value": 4000},
        ]
        matched, h_un, x_un = match_positions(html, xbrl)
        assert len(matched) >= 1  # At least Acme matches
        # Both sides should have at most 1 unmatched
        assert len(h_un) <= 1
        assert len(x_un) <= 1

    def test_empty_html(self):
        matched, h_un, x_un = match_positions(
            [],
            [{"investment_identifier": "Acme", "fair_value": 100}],
        )
        assert len(matched) == 0
        assert len(h_un) == 0
        assert len(x_un) == 1

    def test_empty_xbrl(self):
        matched, h_un, x_un = match_positions(
            [{"investment_identifier": "Acme", "fair_value": 100}],
            [],
        )
        assert len(matched) == 0
        assert len(h_un) == 1
        assert len(x_un) == 0

    def test_both_empty(self):
        matched, h_un, x_un = match_positions([], [])
        assert len(matched) == 0
        assert len(h_un) == 0
        assert len(x_un) == 0

    def test_fv_proximity_helps_matching(self):
        """When names are similar, FV proximity should help select correct match."""
        html = [
            {"investment_identifier": "Acme Corp TL", "fair_value": 1000},
        ]
        xbrl = [
            {"investment_identifier": "Acme Corp | First Lien | Affil", "fair_value": 5000},
            {"investment_identifier": "Acme Corp | Second Lien | Affil", "fair_value": 1000},
        ]
        matched, _, _ = match_positions(html, xbrl)
        assert len(matched) == 1
        # Should match to the one with closer FV (1000 vs 1000)
        x_fv = _safe_float(matched[0]["xbrl"]["fair_value"])
        assert x_fv == 1000.0

    def test_one_to_one_enforcement(self):
        """Each position should be matched at most once."""
        html = [
            {"investment_identifier": "Acme Corp", "fair_value": 1000},
            {"investment_identifier": "Acme Corp", "fair_value": 2000},
        ]
        xbrl = [
            {"investment_identifier": "Acme Corp | Loan", "fair_value": 1000},
        ]
        matched, h_un, x_un = match_positions(html, xbrl)
        assert len(matched) == 1
        assert len(h_un) == 1
        assert len(x_un) == 0

    def test_fv_delta_pct_calculated(self):
        html = [{"investment_identifier": "Acme", "fair_value": 1050}]
        xbrl = [{"investment_identifier": "Acme | Loan", "fair_value": 1000}]
        matched, _, _ = match_positions(html, xbrl)
        assert len(matched) == 1
        assert matched[0]["fv_delta_pct"] == pytest.approx(0.05, abs=0.01)


# ---------------------------------------------------------------------------
# compare_filing
# ---------------------------------------------------------------------------

class TestCompareFiling:
    """Test compare_filing with mocked HTML extraction."""

    def _make_xbrl_df(self, positions: list[dict], accession: str, report_date: str) -> pd.DataFrame:
        """Build a minimal XBRL DataFrame for testing."""
        records = []
        for p in positions:
            records.append({
                "cik": "1287750",
                "accession_number": accession,
                "period": report_date,
                "report_date": report_date,
                "investment_identifier": p.get("investment_identifier", ""),
                "fair_value": p.get("fair_value"),
                "interest_rate": p.get("interest_rate"),
                "maturity_date": p.get("maturity_date", ""),
                "principal_amount": p.get("principal_amount"),
            })
        return pd.DataFrame(records)

    @patch("pipeline.html_template.extract_filing_with_template")
    def test_basic_comparison(self, mock_extract, tmp_path):
        """Test basic filing comparison with perfect matches."""
        # Set up HTML cache
        cik = "1287750"
        acc = "0001287750-24-000001"
        acc_nodashes = acc.replace("-", "")
        html_dir = tmp_path / cik
        html_dir.mkdir()
        html_file = html_dir / f"{acc_nodashes}.html"
        html_file.write_text("<html>test</html>" * 100)  # > 1KB

        # Mock extraction returns matching positions
        html_rows = [
            {
                "investment_identifier": "Acme Corp",
                "fair_value": 1000000,
                "interest_rate": 10.5,
                "maturity_date": "2025-06-15",
                "principal_amount": 1000000,
            },
        ]
        mock_extract.return_value = (html_rows, {"variant_id": "v1", "drift_detected": False})

        xbrl_df = self._make_xbrl_df(
            [
                {
                    "investment_identifier": "Acme Corp | First Lien | Non-Controlled/Non-Affiliated",
                    "fair_value": 1000000,
                    "interest_rate": 0.105,  # decimal
                    "maturity_date": "2025-06-15",
                    "principal_amount": 1000000,
                },
            ],
            accession=acc,
            report_date="2024-12-31",
        )

        filing_meta = {
            "cik": cik,
            "accession_number": acc,
            "filing_date": "2025-02-28",
            "report_date": "2024-12-31",
        }

        with patch("pipeline.validate_html_extraction.BDC_HTML_CACHE_DIR", tmp_path):
            result = compare_filing(cik, acc, filing_meta, {}, xbrl_df)

        assert result is not None
        assert result["xbrl_count"] == 1
        assert result["matched_count"] == 1
        assert result["recall"] == 1.0
        assert result["fv_accuracy"] == 1.0

    @patch("pipeline.html_template.extract_filing_with_template")
    def test_no_html_file(self, mock_extract, tmp_path):
        """Returns None when HTML file doesn't exist."""
        with patch("pipeline.validate_html_extraction.BDC_HTML_CACHE_DIR", tmp_path):
            result = compare_filing(
                "1287750", "0001-00-000001",
                {"filing_date": "", "report_date": ""},
                {},
                pd.DataFrame(),
            )
        assert result is None

    @patch("pipeline.html_template.extract_filing_with_template")
    def test_rate_conversion(self, mock_extract, tmp_path):
        """XBRL decimal rates should be converted to percentage for comparison."""
        cik = "1287750"
        acc = "0001287750-24-000002"
        acc_nodashes = acc.replace("-", "")
        html_dir = tmp_path / cik
        html_dir.mkdir()
        (html_dir / f"{acc_nodashes}.html").write_text("<html>x</html>" * 100)

        # HTML rate: 10.5% (percentage)
        # XBRL rate: 0.105 (decimal) -> should convert to 10.5%
        html_rows = [
            {"investment_identifier": "TestCo", "fair_value": 100, "interest_rate": 10.5},
        ]
        mock_extract.return_value = (html_rows, {"variant_id": "v1", "drift_detected": False})

        xbrl_df = self._make_xbrl_df(
            [{"investment_identifier": "TestCo | Loan", "fair_value": 100, "interest_rate": 0.105}],
            accession=acc,
            report_date="2024-12-31",
        )

        filing_meta = {"cik": cik, "accession_number": acc, "filing_date": "", "report_date": "2024-12-31"}

        with patch("pipeline.validate_html_extraction.BDC_HTML_CACHE_DIR", tmp_path):
            result = compare_filing(cik, acc, filing_meta, {}, xbrl_df)

        assert result is not None
        assert result["rate_accuracy"] == 1.0

    @patch("pipeline.html_template.extract_filing_with_template")
    def test_dollar_unit_detection(self, mock_extract, tmp_path):
        """FV ratio of ~1000 should flag dollar unit issue."""
        cik = "1287750"
        acc = "0001287750-24-000003"
        acc_nodashes = acc.replace("-", "")
        html_dir = tmp_path / cik
        html_dir.mkdir()
        (html_dir / f"{acc_nodashes}.html").write_text("<html>x</html>" * 100)

        # HTML FV in thousands (1000), XBRL in units (1000000)
        html_rows = [
            {"investment_identifier": "TestCo", "fair_value": 1000},
        ]
        mock_extract.return_value = (html_rows, {"variant_id": "v1", "drift_detected": False})

        xbrl_df = self._make_xbrl_df(
            [{"investment_identifier": "TestCo | Loan", "fair_value": 1000000}],
            accession=acc,
            report_date="2024-12-31",
        )

        filing_meta = {"cik": cik, "accession_number": acc, "filing_date": "", "report_date": "2024-12-31"}

        with patch("pipeline.validate_html_extraction.BDC_HTML_CACHE_DIR", tmp_path):
            result = compare_filing(cik, acc, filing_meta, {}, xbrl_df)

        assert result is not None
        assert result["dollar_unit_ok"] is False
        assert result["agg_fv_ratio"] is not None
        assert result["agg_fv_ratio"] < 0.01  # ~0.001

    @patch("pipeline.html_template.extract_filing_with_template")
    def test_empty_extraction(self, mock_extract, tmp_path):
        """Empty HTML extraction returns zero metrics."""
        cik = "1287750"
        acc = "0001287750-24-000004"
        acc_nodashes = acc.replace("-", "")
        html_dir = tmp_path / cik
        html_dir.mkdir()
        (html_dir / f"{acc_nodashes}.html").write_text("<html>x</html>" * 100)

        mock_extract.return_value = ([], {"variant_id": "v1", "drift_detected": False})

        with patch("pipeline.validate_html_extraction.BDC_HTML_CACHE_DIR", tmp_path):
            result = compare_filing(
                cik, acc,
                {"cik": cik, "accession_number": acc, "filing_date": "", "report_date": "2024-12-31"},
                {},
                pd.DataFrame(columns=["accession_number", "period", "report_date"]),
            )

        assert result is not None
        assert result["html_count"] == 0
        assert result["matched_count"] == 0
        assert result["recall"] == 0.0
