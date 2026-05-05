"""Tests for pipeline.validate_html_template module."""

import json
import math
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from pipeline.validate_html_template import (
    _auto_detect_unit,
    _check_position_count_stability,
    _compute_carry_rates,
    _find_investment_fv_series,
    _find_subtotal_fv,
    _median,
    _normalize_name,
    _print_cik_report,
    _safe_float,
    _self_referential_check,
    validate_cik,
)


# ---------------------------------------------------------------------------
# TestAutoDetectUnit
# ---------------------------------------------------------------------------

class TestAutoDetectUnit:
    def test_exact_match(self):
        """html_sum == xbrl_agg -> ratio 1.0, multiplier 1."""
        adj, mult, raw = _auto_detect_unit(1_000_000, 1_000_000)
        assert mult == 1.0
        assert abs(adj - 1.0) < 0.01
        assert abs(raw - 1.0) < 0.01

    def test_1000x_mismatch(self):
        """HTML in thousands, companyfacts in actual USD."""
        # html_sum = 5000 (thousands), xbrl = 5,000,000 (USD)
        adj, mult, raw = _auto_detect_unit(5_000, 5_000_000)
        assert mult == 1e3
        assert abs(adj - 1.0) < 0.01
        assert abs(raw - 0.001) < 0.0001

    def test_1M_mismatch(self):
        """HTML in millions, companyfacts in actual USD."""
        adj, mult, raw = _auto_detect_unit(5.0, 5_000_000)
        assert mult == 1e6
        assert abs(adj - 1.0) < 0.01

    def test_comparative_period_inflation(self):
        """html_sum ~1.3x xbrl due to comparative periods -> ratio ~1.3."""
        adj, mult, raw = _auto_detect_unit(6_500_000, 5_000_000)
        assert mult == 1.0
        assert abs(adj - 1.3) < 0.01

    def test_zero_html_sum(self):
        adj, mult, raw = _auto_detect_unit(0, 5_000_000)
        assert adj == 0.0
        assert mult == 1.0

    def test_zero_xbrl_agg(self):
        adj, mult, raw = _auto_detect_unit(5_000_000, 0)
        assert adj == 0.0
        assert mult == 1.0


# ---------------------------------------------------------------------------
# TestFindInvestmentFvSeries
# ---------------------------------------------------------------------------

class TestFindInvestmentFvSeries:
    def test_standard_concept(self):
        """Finds us-gaap InvestmentsAtFairValue."""
        facts = {
            "facts": {
                "us-gaap": {
                    "InvestmentsAtFairValue": {
                        "units": {
                            "USD": [
                                {"end": "2023-12-31", "val": 5000000000},
                                {"end": "2023-06-30", "val": 4800000000},
                            ]
                        }
                    }
                }
            }
        }
        result = _find_investment_fv_series(facts)
        assert len(result) == 2
        assert result["2023-12-31"] == 5_000_000_000
        assert result["2023-06-30"] == 4_800_000_000

    def test_picks_most_data_points(self):
        """When multiple concepts match, picks the one with most entries."""
        facts = {
            "facts": {
                "us-gaap": {
                    "InvestmentsAtFairValue": {
                        "units": {
                            "USD": [
                                {"end": "2023-12-31", "val": 5000000000},
                            ]
                        }
                    },
                    "InvestmentOwnedAtFairValue": {
                        "units": {
                            "USD": [
                                {"end": "2023-12-31", "val": 4000000000},
                                {"end": "2023-06-30", "val": 3800000000},
                                {"end": "2022-12-31", "val": 3500000000},
                            ]
                        }
                    },
                }
            }
        }
        result = _find_investment_fv_series(facts)
        assert len(result) == 3
        # Should pick InvestmentOwnedAtFairValue (3 entries vs 1)
        assert result["2023-12-31"] == 4_000_000_000

    def test_no_matching_concept(self):
        """Returns empty dict when no FV concept found."""
        facts = {
            "facts": {
                "us-gaap": {
                    "Revenue": {
                        "units": {"USD": [{"start": "2023-01-01", "end": "2023-12-31", "val": 100}]}
                    }
                }
            }
        }
        result = _find_investment_fv_series(facts)
        assert result == {}

    def test_filters_out_duration_facts(self):
        """Facts with both start and end (duration) are excluded."""
        facts = {
            "facts": {
                "us-gaap": {
                    "InvestmentsAtFairValue": {
                        "units": {
                            "USD": [
                                # Duration fact (has start) -- should be excluded
                                {"start": "2023-01-01", "end": "2023-12-31", "val": 100},
                                # Instant fact -- should be included
                                {"end": "2023-12-31", "val": 5000000000},
                            ]
                        }
                    }
                }
            }
        }
        result = _find_investment_fv_series(facts)
        assert len(result) == 1
        assert result["2023-12-31"] == 5_000_000_000

    def test_empty_facts(self):
        assert _find_investment_fv_series({}) == {}

    def test_none_facts(self):
        assert _find_investment_fv_series(None) == {}


# ---------------------------------------------------------------------------
# TestComputeCarryRates
# ---------------------------------------------------------------------------

class TestComputeCarryRates:
    def test_normal_carry(self):
        """~80% carry rate between two quarters."""
        positions = {
            "2023-06-30": ["Acme Corp", "Beta Inc", "Charlie LLC", "Delta Co", "Echo Ltd"],
            "2023-09-30": ["Acme Corp", "Beta Inc", "Charlie LLC", "Delta Co", "Foxtrot Inc"],
        }
        result = _compute_carry_rates(positions)
        assert len(result) == 1
        r = result[0]
        assert r["begin_date"] == "2023-06-30"
        assert r["end_date"] == "2023-09-30"
        assert r["begin_count"] == 5
        assert r["end_count"] == 5
        assert r["carried"] == 4
        assert r["carry_rate"] == 0.8
        assert r["new_rate"] == 0.2

    def test_zero_carry(self):
        """Completely different names = 0% carry."""
        positions = {
            "2023-06-30": ["Acme Corp", "Beta Inc"],
            "2023-09-30": ["Charlie LLC", "Delta Co"],
        }
        result = _compute_carry_rates(positions)
        assert len(result) == 1
        assert result[0]["carry_rate"] == 0.0
        assert result[0]["new_rate"] == 1.0

    def test_single_quarter(self):
        """Only one quarter -> no pairs."""
        positions = {
            "2023-06-30": ["Acme Corp"],
        }
        result = _compute_carry_rates(positions)
        assert result == []

    def test_name_normalization(self):
        """Carry rate handles case/spacing differences."""
        positions = {
            "2023-06-30": ["Acme Corp", "Beta Inc"],
            "2023-09-30": ["ACME CORP", "  Beta  Inc  "],
        }
        result = _compute_carry_rates(positions)
        assert result[0]["carry_rate"] == 1.0

    def test_three_quarters(self):
        """Three consecutive quarters produce two pairs."""
        positions = {
            "2023-03-31": ["A", "B", "C"],
            "2023-06-30": ["A", "B", "D"],
            "2023-09-30": ["A", "D", "E"],
        }
        result = _compute_carry_rates(positions)
        assert len(result) == 2
        # Q1->Q2: A,B carry (2/3)
        assert result[0]["carry_rate"] == pytest.approx(2 / 3, abs=0.001)
        # Q2->Q3: A,D carry (2/3)
        assert result[1]["carry_rate"] == pytest.approx(2 / 3, abs=0.001)

    def test_empty_names_filtered(self):
        """Empty/None names are excluded from counts."""
        positions = {
            "2023-06-30": ["Acme Corp", "", None, "Beta Inc"],
            "2023-09-30": ["Acme Corp", "Beta Inc"],
        }
        result = _compute_carry_rates(positions)
        assert result[0]["begin_count"] == 2  # empty/None excluded
        assert result[0]["carry_rate"] == 1.0


# ---------------------------------------------------------------------------
# TestNormalizeName
# ---------------------------------------------------------------------------

class TestNormalizeName:
    def test_basic(self):
        assert _normalize_name("Acme Corp") == "acme corp"

    def test_whitespace(self):
        assert _normalize_name("  Acme   Corp  ") == "acme corp"

    def test_trailing_punct(self):
        assert _normalize_name("Acme Corp,") == "acme corp"
        assert _normalize_name("Acme Corp;") == "acme corp"
        assert _normalize_name("Acme Corp.") == "acme corp"

    def test_empty(self):
        assert _normalize_name("") == ""
        assert _normalize_name(None) == ""


# ---------------------------------------------------------------------------
# TestMedian
# ---------------------------------------------------------------------------

class TestMedian:
    def test_odd(self):
        assert _median([1, 2, 3]) == 2

    def test_even(self):
        assert _median([1, 2, 3, 4]) == 2.5

    def test_single(self):
        assert _median([42]) == 42

    def test_empty(self):
        assert _median([]) == 0.0

    def test_unsorted(self):
        assert _median([3, 1, 2]) == 2


# ---------------------------------------------------------------------------
# TestSafeFloat
# ---------------------------------------------------------------------------

class TestSafeFloat:
    def test_float(self):
        assert _safe_float(3.14) == 3.14

    def test_string(self):
        assert _safe_float("3.14") == 3.14

    def test_none(self):
        assert _safe_float(None) is None

    def test_nan(self):
        assert _safe_float(float("nan")) is None

    def test_invalid(self):
        assert _safe_float("abc") is None


# ---------------------------------------------------------------------------
# TestValidateCik (integration-style with mocks)
# ---------------------------------------------------------------------------

class TestValidateCik:
    @patch("pipeline.html_extract.load_template")
    @patch("pipeline.validate_html_template._fetch_companyfacts")
    @patch("pipeline.html_extract.extract_filing")
    def test_basic_pass(
        self,
        mock_extract,
        mock_cf,
        mock_template,
        tmp_path,
    ):
        """Mock all dependencies and verify PASS result."""
        import pipeline.validate_html_template as mod

        # Setup template
        mock_template.return_value = {
            "entity_name": "Test BDC",
            "schema_version": "2.0",
        }

        # Setup filings index
        idx_path = tmp_path / "bdc_filings_index.csv"
        pd.DataFrame([
            {
                "cik": "1234567",
                "accession_number": "0001-23-456789",
                "form_type": "10-K",
                "filing_date": "2023-03-15",
                "report_date": "2023-12-31",
                "primary_document": "doc.htm",
                "xbrl_download_status": "success",
            },
        ]).to_csv(idx_path, index=False)

        # Setup HTML cache
        html_dir = tmp_path / "html"
        html_dir.mkdir()
        cik_dir = html_dir / "1234567"
        cik_dir.mkdir()
        html_file = cik_dir / "000123456789.html"
        html_file.write_text("<html>test</html>" * 100)  # > 1024 bytes

        # Setup companyfacts
        mock_cf.return_value = {
            "facts": {
                "us-gaap": {
                    "InvestmentsAtFairValue": {
                        "units": {
                            "USD": [
                                {"end": "2023-12-31", "val": 1000000},
                            ]
                        }
                    }
                }
            }
        }

        # Setup extraction result
        mock_extract.return_value = (
            [
                {"fair_value": 500000, "investment_identifier": "Acme Corp"},
                {"fair_value": 500000, "investment_identifier": "Beta Inc"},
            ],
            {"variant_id": "era1", "drift_detected": False},
        )

        # Patch module-level paths
        orig_idx = mod.BDC_FILINGS_INDEX_FILE
        orig_html = mod.BDC_HTML_CACHE_DIR
        try:
            mod.BDC_FILINGS_INDEX_FILE = idx_path
            mod.BDC_HTML_CACHE_DIR = html_dir
            result = validate_cik("1234567")
        finally:
            mod.BDC_FILINGS_INDEX_FILE = orig_idx
            mod.BDC_HTML_CACHE_DIR = orig_html

        assert result["cik"] == "1234567"
        assert result["entity_name"] == "Test BDC"
        assert len(result["filings"]) == 1

        filing = result["filings"][0]
        assert filing["html_count"] == 2
        assert filing["html_fv_sum"] == 1000000
        assert filing["agg_status"] == "PASS"

    @patch("pipeline.html_extract.load_template")
    def test_no_template(self, mock_template):
        """Missing template returns error."""
        mock_template.return_value = None
        result = validate_cik("9999999")
        assert result["error"] == "no_template"
        assert result["filings"] == []

    @patch("pipeline.html_extract.load_template")
    def test_no_filings_index(self, mock_template, tmp_path):
        """Missing filings index returns error."""
        import pipeline.validate_html_template as mod

        mock_template.return_value = {"entity_name": "Test"}
        fake_path = tmp_path / "nonexistent.csv"

        orig_idx = mod.BDC_FILINGS_INDEX_FILE
        try:
            mod.BDC_FILINGS_INDEX_FILE = fake_path
            result = validate_cik("1234567")
        finally:
            mod.BDC_FILINGS_INDEX_FILE = orig_idx

        assert result["error"] == "no_filings_index"


# ---------------------------------------------------------------------------
# TestPrintCikReport (enhanced output)
# ---------------------------------------------------------------------------

class TestPrintCikReport:
    def _make_summary(self, **overrides):
        """Build a standard summary dict."""
        summary = {
            "filings_with_html": 3,
            "filings_total": 3,
            "agg_validated": 2,
            "agg_pass": 2,
            "agg_fail": 0,
            "median_adj_ratio": 1.05,
            "unit_mismatch_detected": False,
            "agg_overall": "PASS",
            "self_ref_validated": 0,
            "self_ref_pass": 0,
            "self_ref_fail": 0,
            "self_ref_no_subtotal": 3,
            "median_self_ref_ratio": None,
            "self_ref_overall": "NO_DATA",
            "carry_pairs": 2,
            "carry_pass": 1,
            "carry_fail": 1,
            "median_carry": 0.65,
            "min_carry": 0.30,
            "carry_overall": "FAIL",
            "low_carry_pairs": 1,
            "count_instability": 0,
        }
        summary.update(overrides)
        return summary

    def test_shows_low_carry_details(self, capsys):
        """Report includes per-filing details for low carry transitions."""
        result = {
            "cik": "123",
            "entity_name": "Test BDC",
            "overall": "FAIL",
            "summary": self._make_summary(),
            "filings": [],
            "carry_rates": [
                {
                    "begin_date": "2023-06-30",
                    "end_date": "2023-09-30",
                    "begin_count": 10,
                    "end_count": 10,
                    "carried": 3,
                    "carry_rate": 0.30,
                    "new_rate": 0.70,
                },
                {
                    "begin_date": "2023-09-30",
                    "end_date": "2023-12-31",
                    "begin_count": 10,
                    "end_count": 10,
                    "carried": 9,
                    "carry_rate": 0.90,
                    "new_rate": 0.10,
                },
            ],
            "count_stability": [],
        }
        _print_cik_report(result)
        out = capsys.readouterr().out
        assert "Pairs below 50%: 1" in out
        assert "2023-06-30 -> 2023-09-30" in out
        assert "30% carry" in out
        # High carry pair should not be listed
        assert "2023-09-30 -> 2023-12-31" not in out

    def test_shows_self_ref_section(self, capsys):
        """Report shows self-referential subtotal check section."""
        result = {
            "cik": "456",
            "entity_name": "Test BDC 2",
            "overall": "PASS",
            "summary": self._make_summary(
                self_ref_validated=2,
                self_ref_pass=2,
                self_ref_fail=0,
                self_ref_no_subtotal=1,
                median_self_ref_ratio=1.02,
                self_ref_overall="PASS",
                carry_overall="PASS",
                carry_pass=2,
                carry_fail=0,
            ),
            "filings": [],
            "carry_rates": [],
            "count_stability": [],
        }
        _print_cik_report(result)
        out = capsys.readouterr().out
        assert "Self-Referential Subtotal Check" in out
        assert "Filings with subtotals: 2" in out
        assert "Median ratio: 1.0200" in out

    def test_shows_count_stability(self, capsys):
        """Report shows position count stability section (gate)."""
        result = {
            "cik": "789",
            "entity_name": "Test BDC 3",
            "overall": "FAIL",
            "summary": self._make_summary(
                count_instability=1,
                carry_overall="PASS",
                carry_pass=2,
                carry_fail=0,
            ),
            "filings": [],
            "carry_rates": [],
            "count_stability": [
                {
                    "begin_date": "2023-06-30",
                    "end_date": "2023-09-30",
                    "begin_count": 100,
                    "end_count": 40,
                    "pct_change": 0.60,
                    "status": "WARN",
                },
            ],
        }
        _print_cik_report(result)
        out = capsys.readouterr().out
        assert "Position Count Stability" in out
        assert "QoQ jumps > 50%: 1" in out
        assert "100 -> 40" in out


# ---------------------------------------------------------------------------
# TestSelfReferentialCheck
# ---------------------------------------------------------------------------

class TestSelfReferentialCheck:
    def test_pass_when_ratio_near_one(self):
        """Position FV sum close to subtotal -> PASS."""
        holdings = [
            {"issuer_name": "Acme Corp", "fair_value": 100, "is_subtotal": False},
            {"issuer_name": "Beta Inc", "fair_value": 200, "is_subtotal": False},
            {"issuer_name": "Total Investments at Fair Value", "fair_value": 300,
             "is_subtotal": True},
        ]
        result = _self_referential_check(holdings)
        assert result["status"] == "PASS"
        assert abs(result["ratio"] - 1.0) < 0.01

    def test_fail_when_positions_missing(self):
        """Position FV sum significantly lower than subtotal -> FAIL."""
        holdings = [
            {"issuer_name": "Acme Corp", "fair_value": 100, "is_subtotal": False},
            {"issuer_name": "Total Investments", "fair_value": 500,
             "is_subtotal": True},
        ]
        result = _self_referential_check(holdings)
        assert result["status"] == "FAIL"
        assert result["ratio"] < 0.85

    def test_no_subtotal(self):
        """No subtotal rows -> NO_SUBTOTAL status."""
        holdings = [
            {"issuer_name": "Acme Corp", "fair_value": 100, "is_subtotal": False},
            {"issuer_name": "Beta Inc", "fair_value": 200, "is_subtotal": False},
        ]
        result = _self_referential_check(holdings)
        assert result["status"] == "NO_SUBTOTAL"

    def test_subtotal_pattern_matching(self):
        """Various subtotal name patterns are recognized."""
        assert _find_subtotal_fv([
            {"issuer_name": "Total Investments at Fair Value", "fair_value": 1000},
        ]) == 1000
        assert _find_subtotal_fv([
            {"issuer_name": "TOTAL PORTFOLIO", "fair_value": 500},
        ]) == 500
        assert _find_subtotal_fv([
            {"issuer_name": "Grand Total", "fair_value": 750},
        ]) == 750
        # Not a subtotal
        assert _find_subtotal_fv([
            {"issuer_name": "Acme Corp", "fair_value": 100},
        ]) is None

    def test_picks_largest_subtotal(self):
        """When multiple subtotals exist, picks the largest FV."""
        holdings = [
            {"issuer_name": "Total Investments - First Lien", "fair_value": 200},
            {"issuer_name": "Total Investments at Fair Value", "fair_value": 500},
        ]
        assert _find_subtotal_fv(holdings) == 500

    def test_members_capital_excluded(self):
        """MEMBERS' CAPITAL rows are excluded from position FV sum."""
        holdings = [
            {"issuer_name": "Acme Corp", "fair_value": 100, "is_subtotal": False},
            {"issuer_name": "MEMBERS' CAPITAL", "fair_value": 500,
             "is_subtotal": True},
            {"issuer_name": "Total Investments", "fair_value": 100,
             "is_subtotal": True},
        ]
        result = _self_referential_check(holdings)
        assert result["status"] == "PASS"
        assert result["position_fv_sum"] == 100

    def test_stockholders_equity_excluded(self):
        """Stockholders' Equity rows are excluded from position FV sum."""
        holdings = [
            {"issuer_name": "Acme Corp", "fair_value": 200, "is_subtotal": False},
            {"issuer_name": "Stockholders\u2019 Equity", "fair_value": 800,
             "is_subtotal": True},
            {"issuer_name": "Total Investments", "fair_value": 200,
             "is_subtotal": True},
        ]
        result = _self_referential_check(holdings)
        assert result["status"] == "PASS"
        assert result["position_fv_sum"] == 200

    def test_total_liabilities_and_excluded(self):
        """'Total liabilities and members capital' rows are excluded."""
        from pipeline.validate_html_template import _SUBTOTAL_RE
        assert _SUBTOTAL_RE.search("Total liabilities and members' capital")
        assert _SUBTOTAL_RE.search("TOTAL LIABILITIES AND STOCKHOLDERS' EQUITY")

    def test_net_asset_value_excluded(self):
        """Net asset value rows are excluded from position FV sum."""
        from pipeline.validate_html_template import _SUBTOTAL_RE
        assert _SUBTOTAL_RE.search("Net Asset Value")
        assert _SUBTOTAL_RE.search("NET ASSET VALUE PER UNIT")

    def test_excludes_subtotals_from_position_sum(self):
        """Subtotal rows are excluded from the position FV sum."""
        holdings = [
            {"issuer_name": "Acme Corp", "fair_value": 100, "is_subtotal": False},
            {"issuer_name": "Total First Lien", "fair_value": 100,
             "is_subtotal": True},  # Not matched by _SUBTOTAL_RE
            {"issuer_name": "Total Investments", "fair_value": 100,
             "is_subtotal": True},  # Matched by _SUBTOTAL_RE
        ]
        result = _self_referential_check(holdings)
        # Position sum should be 100 (just Acme), subtotal is 100
        assert result["status"] == "PASS"
        assert result["position_fv_sum"] == 100


# ---------------------------------------------------------------------------
# TestPositionCountStability
# ---------------------------------------------------------------------------

class TestPositionCountStability:
    def test_stable_counts(self):
        """Small changes pass."""
        counts = {"2023-06-30": 100, "2023-09-30": 110, "2023-12-31": 105}
        results = _check_position_count_stability(counts)
        assert all(r["status"] == "OK" for r in results)

    def test_large_drop_warns(self):
        """Large count drop triggers WARN."""
        counts = {"2023-06-30": 100, "2023-09-30": 40}
        results = _check_position_count_stability(counts)
        assert len(results) == 1
        assert results[0]["status"] == "WARN"
        assert results[0]["pct_change"] == 0.6

    def test_large_increase_warns(self):
        """Large count increase also triggers WARN."""
        counts = {"2023-06-30": 50, "2023-09-30": 150}
        results = _check_position_count_stability(counts)
        assert len(results) == 1
        assert results[0]["status"] == "WARN"

    def test_single_date_returns_empty(self):
        """Single date -> no transitions to check."""
        counts = {"2023-06-30": 100}
        results = _check_position_count_stability(counts)
        assert results == []

    def test_zero_count_skipped(self):
        """Zero count in begin date is skipped (avoid div by zero)."""
        counts = {"2023-06-30": 0, "2023-09-30": 100}
        results = _check_position_count_stability(counts)
        assert results == []
