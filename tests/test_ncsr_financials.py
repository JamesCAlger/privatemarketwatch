"""Tests for pipeline.ncsr_financials module."""

import re
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from pipeline.ncsr_financials import (
    _OUTPUT_COLS,
    _FOOTNOTE_RE,
    _PAREN_NEG_RE,
    _ROW_LABEL_PATTERNS,
    _apply_guards,
    _collect_ncsr_filings,
    _dedup_filings,
    _derive_report_quarter,
    _detect_dollar_unit,
    _detect_value_offsets,
    _detect_vertical_layout,
    _extract_table,
    _extract_vertical,
    _find_fh_tables,
    _find_merged_headers,
    _find_period_columns,
    _is_fh_candidate,
    _looks_numeric,
    _match_row_label,
    _parse_financial_highlights,
    _parse_period_label,
    _parse_value,
    _pick_largest_class,
    _read_cell_value,
    _try_split_table_extraction,
    build_ncsr_filings_index,
    download_ncsr_filings,
    extract_ncsr_financials,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_fh_html(
    rows: list[tuple[str, ...]],
    heading: str = "Financial Highlights",
    dollar_unit: str = "",
    extra_before: str = "",
) -> str:
    """Build minimal N-CSR HTML with a Financial Highlights table."""
    trs = []
    for row in rows:
        cells = "".join(f"<td>{c}</td>" for c in row)
        trs.append(f"<tr>{cells}</tr>")
    table_html = "<table>" + "\n".join(trs) + "</table>"
    unit_text = f"<p>{dollar_unit}</p>" if dollar_unit else ""
    return f"""<html><body>
    {unit_text}
    {extra_before}
    <p><b>{heading}</b></p>
    {table_html}
    </body></html>"""


def _write_html(tmp_dir: Path, content: str, filename: str = "test.html") -> str:
    path = tmp_dir / filename
    path.write_text(content, encoding="utf-8")
    return str(path)


# ===================================================================
# 1. Row label matching
# ===================================================================

class TestMatchRowLabel:

    def test_nav_beginning(self):
        assert _match_row_label("Net asset value, beginning of period") == "nav_begin_per_share"

    def test_nav_end(self):
        assert _match_row_label("Net asset value, end of period") == "nav_end_per_share"

    def test_nii(self):
        assert _match_row_label("Net investment income (loss)") == "nii_per_share"

    def test_gain_loss(self):
        assert _match_row_label("Net realized and unrealized gain (loss)") == "gain_loss_per_share"

    def test_change_in_unrealized(self):
        assert _match_row_label("Change in unrealized appreciation") == "gain_loss_per_share"

    def test_dist_from_nii(self):
        assert _match_row_label("Distributions from net investment income") == "distribution_from_nii"

    def test_dividends_from_nii(self):
        assert _match_row_label("Dividends from net investment income") == "distribution_from_nii"

    def test_dist_from_gains(self):
        assert _match_row_label("Distributions from net realized capital gains") == "distribution_from_gains"

    def test_return_of_capital(self):
        assert _match_row_label("Return of capital") == "distribution_return_of_capital"

    def test_total_distributions(self):
        assert _match_row_label("Total distributions") == "distribution_per_share"

    def test_total_dividends(self):
        assert _match_row_label("Total dividends and distributions") == "distribution_per_share"

    def test_total_return(self):
        assert _match_row_label("Total return") == "total_return_pct"

    def test_expense_ratio(self):
        assert _match_row_label("Ratio of expenses to average net assets") == "expense_ratio_pct"

    def test_expense_ratio_alt(self):
        assert _match_row_label("Total expenses to average net assets") == "expense_ratio_pct"

    def test_income_yield(self):
        assert _match_row_label("Ratio of net investment income to average net assets") == "income_yield_pct"

    def test_portfolio_turnover(self):
        assert _match_row_label("Portfolio turnover rate") == "portfolio_turnover"

    def test_net_assets_end(self):
        assert _match_row_label("Net assets, end of period (in thousands)") == "net_assets_end"

    def test_no_match(self):
        assert _match_row_label("Some random text") is None

    def test_empty(self):
        assert _match_row_label("") is None


# ===================================================================
# 2. Value parsing
# ===================================================================

class TestParseValue:

    def test_simple_dollar(self):
        assert _parse_value("$25.00", "nav_begin_per_share", 1.0) == 25.0

    def test_negative_parens(self):
        assert _parse_value("(0.50)", "distribution_from_nii", 1.0) == -0.50

    def test_percentage(self):
        assert _parse_value("5.25%", "total_return_pct", 1.0) == 5.25

    def test_dash_null(self):
        assert _parse_value("-", "nii_per_share", 1.0) is None
        assert _parse_value("--", "nii_per_share", 1.0) is None

    def test_em_dash_null(self):
        assert _parse_value("\u2014", "nii_per_share", 1.0) is None

    def test_na_null(self):
        assert _parse_value("N/A", "nii_per_share", 1.0) is None

    def test_empty_null(self):
        assert _parse_value("", "nii_per_share", 1.0) is None

    def test_footnote_stripped(self):
        assert _parse_value("$25.00(a)", "nav_begin_per_share", 1.0) == 25.0

    def test_footnote_complex(self):
        assert _parse_value("10.50%(a,b)", "total_return_pct", 1.0) == 10.50

    def test_comma_thousands(self):
        assert _parse_value("$1,234,567", "net_assets_end", 1.0) == 1234567.0

    def test_dollar_unit_thousands(self):
        assert _parse_value("$1,234", "net_assets_end", 1000.0) == 1234000.0

    def test_dollar_unit_not_applied_to_pct(self):
        # Percentage fields should not be multiplied by dollar_unit
        assert _parse_value("5.25%", "total_return_pct", 1000.0) == 5.25

    def test_dollar_unit_not_applied_to_per_share(self):
        # Per-share fields should not be multiplied
        assert _parse_value("$25.00", "nav_begin_per_share", 1000.0) == 25.0

    def test_negative_number(self):
        assert _parse_value("-0.25", "nii_per_share", 1.0) == -0.25


# ===================================================================
# 3. Period label parsing
# ===================================================================

class TestParsePeriodLabel:

    def test_year_ended(self):
        result = _parse_period_label("Year Ended December 31, 2024")
        assert result["period_type"] == "annual"
        assert result["end_date"] == "2024-12-31"

    def test_six_months_ended(self):
        result = _parse_period_label("Six Months Ended June 30, 2024")
        assert result["period_type"] == "semi-annual"
        assert result["end_date"] == "2024-06-30"

    def test_twelve_months_ended(self):
        result = _parse_period_label("Twelve Months Ended March 31, 2023")
        assert result["period_type"] == "annual"
        assert result["end_date"] == "2023-03-31"

    def test_no_period_type(self):
        result = _parse_period_label("October 31, 2024")
        assert result["period_type"] == ""
        assert result["end_date"] == "2024-10-31"

    def test_abbreviated_month(self):
        result = _parse_period_label("Year Ended Dec 31, 2024")
        assert result["end_date"] == "2024-12-31"

    def test_empty(self):
        result = _parse_period_label("")
        assert result.get("period_type", "") == ""


# ===================================================================
# 4. Layout detection
# ===================================================================

class TestDetectVerticalLayout:

    def test_vertical(self):
        rows = [
            ["", "Year Ended Dec 31, 2024", "Year Ended Dec 31, 2023"],
            ["Net asset value, beginning of period", "$25.00", "$24.00"],
            ["Net investment income", "$1.00", "$0.90"],
            ["Total return", "5.25%", "4.50%"],
        ]
        assert _detect_vertical_layout(rows) is True

    def test_horizontal(self):
        rows = [
            ["Period", "NAV Begin", "NII", "Total Return"],
            ["Year Ended Dec 31, 2024", "$25.00", "$1.00", "5.25%"],
        ]
        assert _detect_vertical_layout(rows) is False


# ===================================================================
# 5. Period column detection
# ===================================================================

class TestFindPeriodColumns:

    def test_finds_dates(self):
        row = ["", "Year Ended Dec 31, 2024", "Year Ended Dec 31, 2023"]
        cols = _find_period_columns(row)
        assert len(cols) == 2
        assert cols[0][0] == 1
        assert cols[1][0] == 2

    def test_skips_first_column(self):
        row = ["Dec 31, 2024", "Dec 31, 2023"]
        cols = _find_period_columns(row)
        assert len(cols) == 1
        assert cols[0][0] == 1


# ===================================================================
# 6. Table detection
# ===================================================================

class TestFindFHTables:

    def test_finds_fh_heading(self):
        from bs4 import BeautifulSoup
        html = """<html><body>
        <p><b>Financial Highlights</b></p>
        <table><tr><td>test</td></tr></table>
        </body></html>"""
        soup = BeautifulSoup(html, "html.parser")
        tables = _find_fh_tables(soup)
        assert len(tables) == 1

    def test_consolidated_heading(self):
        from bs4 import BeautifulSoup
        html = """<html><body>
        <p><b>Consolidated Financial Highlights</b></p>
        <table><tr><td>test</td></tr></table>
        </body></html>"""
        soup = BeautifulSoup(html, "html.parser")
        tables = _find_fh_tables(soup)
        assert len(tables) == 1

    def test_skips_toc_links(self):
        from bs4 import BeautifulSoup
        html = """<html><body>
        <a href="#fh">Financial Highlights</a>
        <table><tr><td>not this</td></tr></table>
        <p><b>Financial Highlights</b></p>
        <table><tr><td>this one</td></tr></table>
        </body></html>"""
        soup = BeautifulSoup(html, "html.parser")
        tables = _find_fh_tables(soup)
        assert len(tables) == 1
        assert tables[0].get_text(strip=True) == "this one"

    def test_skips_auditor_opinion(self):
        from bs4 import BeautifulSoup
        html = """<html><body>
        <p>Opinion on the Financial Highlights</p>
        <table><tr><td>not this</td></tr></table>
        <p><b>Financial Highlights</b></p>
        <table><tr><td>this one</td></tr></table>
        </body></html>"""
        soup = BeautifulSoup(html, "html.parser")
        tables = _find_fh_tables(soup)
        assert len(tables) == 1
        assert tables[0].get_text(strip=True) == "this one"

    def test_no_fh_table(self):
        from bs4 import BeautifulSoup
        html = """<html><body><p>No highlights here</p></body></html>"""
        soup = BeautifulSoup(html, "html.parser")
        tables = _find_fh_tables(soup)
        assert len(tables) == 0


# ===================================================================
# 7. Dollar unit detection
# ===================================================================

class TestDetectDollarUnit:

    def test_thousands(self):
        assert _detect_dollar_unit("(in thousands)") == 1000.0

    def test_millions(self):
        assert _detect_dollar_unit("Amounts in millions") == 1000000.0

    def test_default(self):
        assert _detect_dollar_unit("Regular text") == 1.0


# ===================================================================
# 8. Vertical extraction from a full HTML file
# ===================================================================

class TestExtractVertical:

    def test_basic_vertical_table(self):
        with tempfile.TemporaryDirectory() as tmp:
            html = _build_fh_html([
                ("", "Year Ended Dec 31, 2024"),
                ("Net asset value, beginning of period", "$25.00"),
                ("Net investment income", "$1.00"),
                ("Net realized and unrealized gain (loss)", "$0.50"),
                ("Distributions from net investment income", "$(0.80)"),
                ("Total distributions", "$(0.80)"),
                ("Net asset value, end of period", "$25.70"),
                ("Total return", "5.25%"),
                ("Ratio of expenses to average net assets", "1.50%"),
                ("Net assets, end of period", "$500,000"),
            ])
            path = _write_html(Path(tmp), html)
            records = _parse_financial_highlights(path)
            assert len(records) == 1
            r = records[0]
            assert r.get("nav_begin_per_share") == 25.0
            assert r.get("nii_per_share") == 1.0
            assert r.get("gain_loss_per_share") == 0.5
            assert r.get("distribution_from_nii") == -0.80
            assert r.get("distribution_per_share") == -0.80
            assert r.get("nav_end_per_share") == 25.70
            assert r.get("total_return_pct") == 5.25
            assert r.get("expense_ratio_pct") == 1.50
            assert r.get("net_assets_end") == 500000.0

    def test_multi_period_columns(self):
        with tempfile.TemporaryDirectory() as tmp:
            html = _build_fh_html([
                ("", "Year Ended Dec 31, 2024", "Year Ended Dec 31, 2023"),
                ("Net asset value, beginning of period", "$25.00", "$24.00"),
                ("Net investment income", "$1.00", "$0.90"),
                ("Net asset value, end of period", "$26.00", "$25.00"),
                ("Total return", "5.25%", "4.50%"),
            ])
            path = _write_html(Path(tmp), html)
            records = _parse_financial_highlights(path)
            assert len(records) == 2


# ===================================================================
# 9. Guard rails
# ===================================================================

class TestApplyGuards:

    def test_nav_out_of_range(self):
        df = pd.DataFrame({
            "nav_begin_per_share": [0.1, 25.0, 6000.0],
            "nav_end_per_share": [25.0, 0.1, 26.0],
        })
        result = _apply_guards(df)
        assert pd.isna(result.loc[0, "nav_begin_per_share"])
        assert result.loc[1, "nav_begin_per_share"] == 25.0
        assert pd.isna(result.loc[2, "nav_begin_per_share"])
        assert pd.isna(result.loc[1, "nav_end_per_share"])

    def test_nii_out_of_range(self):
        df = pd.DataFrame({"nii_per_share": [-600.0, 0.50, 1264550.0]})
        result = _apply_guards(df)
        assert pd.isna(result.loc[0, "nii_per_share"])
        assert result.loc[1, "nii_per_share"] == 0.50
        assert pd.isna(result.loc[2, "nii_per_share"])

    def test_total_return_out_of_range(self):
        df = pd.DataFrame({"total_return_pct": [-70.0, 5.0, 150.0]})
        result = _apply_guards(df)
        assert pd.isna(result.loc[0, "total_return_pct"])
        assert result.loc[1, "total_return_pct"] == 5.0
        assert pd.isna(result.loc[2, "total_return_pct"])

    def test_expense_ratio_out_of_range(self):
        df = pd.DataFrame({"expense_ratio_pct": [-1.0, 2.5, 25.0]})
        result = _apply_guards(df)
        assert pd.isna(result.loc[0, "expense_ratio_pct"])
        assert result.loc[1, "expense_ratio_pct"] == 2.5
        assert pd.isna(result.loc[2, "expense_ratio_pct"])

    def test_portfolio_turnover_out_of_range(self):
        df = pd.DataFrame({"portfolio_turnover": [-5.0, 50.0, 600.0]})
        result = _apply_guards(df)
        assert pd.isna(result.loc[0, "portfolio_turnover"])
        assert result.loc[1, "portfolio_turnover"] == 50.0
        assert pd.isna(result.loc[2, "portfolio_turnover"])

    def test_empty_df(self):
        df = pd.DataFrame()
        result = _apply_guards(df)
        assert result.empty


# ===================================================================
# 10. Filing dedup
# ===================================================================

class TestDedupFilings:

    def test_prefer_ncsr_over_ncsrs(self):
        df = pd.DataFrame({
            "cik": ["0001234567", "0001234567"],
            "form_type": ["N-CSRS", "N-CSR"],
            "report_date": ["2024-06-30", "2024-12-31"],
            "report_quarter": ["2024q2", "2024q4"],
            "nav_begin_per_share": [10.0, 10.0],
        })
        result = _dedup_filings(df)
        assert len(result) == 2  # Different quarters, both kept

    def test_same_date_prefers_ncsr(self):
        df = pd.DataFrame({
            "cik": ["0001234567", "0001234567"],
            "form_type": ["N-CSRS", "N-CSR"],
            "report_date": ["2024-12-31", "2024-12-31"],
            "report_quarter": ["2024q4", "2024q4"],
            "nav_begin_per_share": [10.0, 10.0],
        })
        result = _dedup_filings(df)
        assert len(result) == 1
        assert result.iloc[0]["form_type"] == "N-CSR"

    def test_empty_df(self):
        df = pd.DataFrame(columns=["cik", "form_type", "report_date", "report_quarter"])
        result = _dedup_filings(df)
        assert result.empty


# ===================================================================
# 11. Report quarter derivation
# ===================================================================

class TestDeriveReportQuarter:

    def test_from_period_end_date(self):
        df = pd.DataFrame({
            "period_end_date": ["2024-12-31"],
            "report_date": ["2025-02-15"],
        })
        result = _derive_report_quarter(df)
        assert result.iloc[0]["report_quarter"] == "2024q4"

    def test_from_report_date_fallback(self):
        df = pd.DataFrame({
            "period_end_date": [""],
            "report_date": ["2024-06-30"],
        })
        result = _derive_report_quarter(df)
        assert result.iloc[0]["report_quarter"] == "2024q2"

    def test_empty_df(self):
        df = pd.DataFrame()
        result = _derive_report_quarter(df)
        assert result.empty


# ===================================================================
# 12. Largest class selection
# ===================================================================

class TestPickLargestClass:

    def test_single_record(self):
        records = [{"period_end_date": "2024-12-31", "net_assets_end": 100}]
        result = _pick_largest_class(records)
        assert len(result) == 1

    def test_multi_class_picks_largest(self):
        records = [
            {"period_end_date": "2024-12-31", "net_assets_end": 100, "share_class": "A"},
            {"period_end_date": "2024-12-31", "net_assets_end": 500, "share_class": "I"},
        ]
        result = _pick_largest_class(records)
        assert len(result) == 1
        assert result[0]["share_class"] == "I"

    def test_different_periods_kept(self):
        records = [
            {"period_end_date": "2024-12-31", "net_assets_end": 100},
            {"period_end_date": "2023-12-31", "net_assets_end": 90},
        ]
        result = _pick_largest_class(records)
        assert len(result) == 2

    def test_empty_returns_empty(self):
        assert _pick_largest_class([]) == []


# ===================================================================
# 13. Filing index collection
# ===================================================================

class TestCollectNcsrFilings:

    def test_filters_to_ncsr_forms(self):
        records: list[dict] = []
        recent = {
            "form": ["N-CSR", "10-K", "N-CSRS", "N-PORT"],
            "filingDate": ["2024-03-01", "2024-03-02", "2024-09-01", "2024-06-01"],
            "accessionNumber": ["acc1", "acc2", "acc3", "acc4"],
            "primaryDocument": ["d1.htm", "d2.htm", "d3.htm", "d4.htm"],
            "reportDate": ["2024-12-31", "2024-12-31", "2024-06-30", "2024-03-31"],
        }
        _collect_ncsr_filings(records, "1234567", "Test Fund", recent)
        assert len(records) == 2
        assert records[0]["form_type"] == "N-CSR"
        assert records[1]["form_type"] == "N-CSRS"

    def test_includes_amendments(self):
        records: list[dict] = []
        recent = {
            "form": ["N-CSR/A", "N-CSRS/A"],
            "filingDate": ["2024-03-01", "2024-09-01"],
            "accessionNumber": ["acc1", "acc2"],
            "primaryDocument": ["d1.htm", "d2.htm"],
            "reportDate": ["2024-12-31", "2024-06-30"],
        }
        _collect_ncsr_filings(records, "1234567", "Test Fund", recent)
        assert len(records) == 2


# ===================================================================
# 14. Full extract_ncsr_financials (integration)
# ===================================================================

class TestExtractNcsrFinancials:

    def test_empty_index(self, tmp_path):
        empty_df = pd.DataFrame(columns=[
            "cik", "entity_name", "accession_number", "form_type",
            "filing_date", "report_date", "html_local_path",
        ])
        with patch("pipeline.ncsr_financials.NCSR_FINANCIALS_FILE",
                    tmp_path / "ncsr_financials.csv"):
            result = extract_ncsr_financials(filings_index=empty_df)
        assert result.empty
        for col in _OUTPUT_COLS:
            assert col in result.columns

    def test_with_html_file(self, tmp_path):
        html = _build_fh_html([
            ("", "Year Ended Dec 31, 2024"),
            ("Net asset value, beginning of period", "$25.00"),
            ("Net investment income", "$1.00"),
            ("Net asset value, end of period", "$26.00"),
            ("Total return", "5.25%"),
        ])
        html_path = tmp_path / "test.html"
        html_path.write_text(html, encoding="utf-8")

        index_df = pd.DataFrame([{
            "cik": "0001234567",
            "entity_name": "Test Fund",
            "accession_number": "0001-23-456789",
            "form_type": "N-CSR",
            "filing_date": "2025-02-15",
            "report_date": "2024-12-31",
            "html_local_path": str(html_path),
        }])

        with patch("pipeline.ncsr_financials.NCSR_FINANCIALS_FILE",
                    tmp_path / "ncsr_financials.csv"):
            result = extract_ncsr_financials(filings_index=index_df)

        assert len(result) >= 1
        row = result.iloc[0]
        assert row["cik"] == "0001234567"
        assert float(row["nav_begin_per_share"]) == 25.0
        assert float(row["nii_per_share"]) == 1.0
        assert float(row["nav_end_per_share"]) == 26.0
        assert float(row["total_return_pct"]) == 5.25


# ===================================================================
# 15. Filing index build (mock SEC API)
# ===================================================================

class TestBuildNcsrFilingsIndex:

    def test_builds_index_from_submissions(self, tmp_path):
        mock_client = MagicMock()
        mock_client.get_company_submissions.return_value = {
            "name": "Test Interval Fund",
            "filings": {
                "recent": {
                    "form": ["N-CSR", "N-CSRS", "10-K"],
                    "filingDate": ["2025-03-01", "2024-09-01", "2025-03-15"],
                    "accessionNumber": ["acc1", "acc2", "acc3"],
                    "primaryDocument": ["d1.htm", "d2.htm", "d3.htm"],
                    "reportDate": ["2024-12-31", "2024-06-30", "2024-12-31"],
                },
                "files": [],
            },
        }

        with patch("pipeline.ncsr_financials.NCSR_FILINGS_INDEX_FILE",
                    tmp_path / "ncsr_idx.csv"):
            result = build_ncsr_filings_index(
                mock_client, ["0001234567"],
            )

        assert len(result) == 2  # Only N-CSR and N-CSRS
        assert set(result["form_type"]) == {"N-CSR", "N-CSRS"}


# ===================================================================
# 16. Download (mock)
# ===================================================================

class TestDownloadNcsrFilings:

    def test_empty_index(self):
        mock_client = MagicMock()
        empty = pd.DataFrame(columns=[
            "cik", "entity_name", "accession_number", "form_type",
            "filing_date", "report_date", "primary_document",
        ])
        result = download_ncsr_filings(mock_client, empty)
        assert "html_local_path" in result.columns
        assert "download_status" in result.columns

    def test_already_cached(self, tmp_path):
        mock_client = MagicMock()
        # Create cached file
        cache_dir = tmp_path / "1234567"
        cache_dir.mkdir()
        cached_file = cache_dir / "acc1.html"
        cached_file.write_text("<html>test</html>" * 100, encoding="utf-8")

        index_df = pd.DataFrame([{
            "cik": "1234567",
            "entity_name": "Test",
            "accession_number": "acc-1",
            "form_type": "N-CSR",
            "filing_date": "2025-03-01",
            "report_date": "2024-12-31",
            "primary_document": "d1.htm",
        }])

        with patch("pipeline.ncsr_financials.NCSR_HTML_CACHE_DIR", tmp_path), \
             patch("pipeline.ncsr_financials.NCSR_FILINGS_INDEX_FILE",
                   tmp_path / "ncsr_idx.csv"):
            result = download_ncsr_filings(mock_client, index_df)

        assert result.iloc[0]["download_status"] == "cached"
        mock_client.download_file.assert_not_called()


# ===================================================================
# 17. Dollar unit handling
# ===================================================================

class TestDollarUnitInExtraction:

    def test_net_assets_in_thousands(self):
        with tempfile.TemporaryDirectory() as tmp:
            html = _build_fh_html(
                rows=[
                    ("", "Year Ended Dec 31, 2024"),
                    ("Net asset value, beginning of period", "$25.00"),
                    ("Net assets, end of period", "$500"),
                ],
                dollar_unit="(in thousands)",
            )
            path = _write_html(Path(tmp), html)
            records = _parse_financial_highlights(path)
            assert len(records) == 1
            assert records[0]["net_assets_end"] == 500000.0
            # NAV per share should NOT be multiplied
            assert records[0]["nav_begin_per_share"] == 25.0


# ===================================================================
# 18. Footnote regex
# ===================================================================

class TestFootnoteRegex:

    def test_single_letter(self):
        assert _FOOTNOTE_RE.sub("", "$25.00(a)") == "$25.00"

    def test_number(self):
        assert _FOOTNOTE_RE.sub("", "5.25%(1)") == "5.25%"

    def test_multi(self):
        assert _FOOTNOTE_RE.sub("", "$25.00(a,b)") == "$25.00"

    def test_no_match(self):
        assert _FOOTNOTE_RE.sub("", "$(0.50)") == "$(0.50)"


# ===================================================================
# 19. Parentheses negative regex
# ===================================================================

class TestParenNegRegex:

    def test_negative_value(self):
        m = _PAREN_NEG_RE.match("(0.50)")
        assert m is not None
        assert m.group(1) == "0.50"

    def test_not_negative(self):
        m = _PAREN_NEG_RE.match("0.50")
        assert m is None


# ===================================================================
# 20. N-CSR columns in output schema
# ===================================================================

class TestOutputSchema:

    def test_all_expected_columns(self):
        expected = {
            "cik", "entity_name", "accession_number", "form_type",
            "filing_date", "report_date", "report_quarter", "period_type",
            "share_class",
            "nav_begin_per_share", "nav_end_per_share",
            "nii_per_share", "gain_loss_per_share",
            "distribution_from_nii", "distribution_from_gains",
            "distribution_return_of_capital", "distribution_per_share",
            "total_return_pct", "expense_ratio_pct", "income_yield_pct",
            "portfolio_turnover", "net_assets_end",
        }
        assert set(_OUTPUT_COLS) == expected


# ===================================================================
# 21. Dollar-sign offset detection
# ===================================================================

class TestDetectValueOffsets:

    def test_dollar_sign_offset(self):
        """Values at col+1 from header when '$' takes its own cell."""
        rows = [
            ["", "Year Ended Dec 31, 2024", "", "", "Year Ended Dec 31, 2023", ""],
            ["Net asset value, beginning of period", "$", "25.00", "", "$", "24.00"],
            ["Net investment income", "$", "1.00", "", "$", "0.80"],
        ]
        period_cols = [(1, "Year Ended Dec 31, 2024"), (4, "Year Ended Dec 31, 2023")]
        offsets = _detect_value_offsets(rows, period_cols)
        assert offsets == [1, 1]

    def test_no_offset(self):
        """Values directly in header column."""
        rows = [
            ["", "Year Ended Dec 31, 2024"],
            ["Net asset value, beginning of period", "$25.00"],
            ["Net investment income", "$1.00"],
        ]
        period_cols = [(1, "Year Ended Dec 31, 2024")]
        offsets = _detect_value_offsets(rows, period_cols)
        assert offsets == [0]


# ===================================================================
# 22. Cell value reading with SEC HTML patterns
# ===================================================================

class TestReadCellValue:

    def test_dollar_sign_skip(self):
        row = ["label", "$", "25.00", ""]
        assert _read_cell_value(row, 1) == "25.00"

    def test_empty_cell_skip(self):
        row = ["label", "", "10.50", ""]
        assert _read_cell_value(row, 1) == "10.50"

    def test_split_negative_parens(self):
        row = ["label", "(0.56", ")"]
        assert _read_cell_value(row, 1) == "(0.56)"

    def test_split_paren_percent(self):
        row = ["label", "(1.50", "%)"]
        assert _read_cell_value(row, 1) == "(1.50%)"

    def test_normal_value(self):
        row = ["label", "10.32"]
        assert _read_cell_value(row, 1) == "10.32"

    def test_out_of_bounds(self):
        row = ["label"]
        assert _read_cell_value(row, 5) == ""

    def test_dollar_then_negative(self):
        row = ["label", "$", "(0.38", ")"]
        assert _read_cell_value(row, 1) == "(0.38)"


# ===================================================================
# 23. Looks-numeric helper
# ===================================================================

class TestLooksNumeric:

    def test_positive_number(self):
        assert _looks_numeric("10.32") is True

    def test_negative_parens(self):
        assert _looks_numeric("(0.56)") is True

    def test_with_commas(self):
        assert _looks_numeric("1,234,567") is True

    def test_empty(self):
        assert _looks_numeric("") is False

    def test_text(self):
        assert _looks_numeric("Investment") is False

    def test_dollar_sign(self):
        assert _looks_numeric("$") is False

    def test_dash(self):
        assert _looks_numeric("-") is False  # Single dash is NULL marker, not numeric


# ===================================================================
# 24. Updated row label patterns
# ===================================================================

class TestUpdatedRowLabels:

    def test_nii_matches_loss(self):
        """'Net investment loss' should match nii_per_share."""
        assert _match_row_label("Net investment loss (a)") == "nii_per_share"

    def test_from_net_investment_income(self):
        """'From net investment income' matches distribution_from_nii."""
        assert _match_row_label("From net investment income") == "distribution_from_nii"

    def test_from_net_realized_gain(self):
        """'From net realized gain' matches distribution_from_gains."""
        assert _match_row_label("From net realized gain") == "distribution_from_gains"

    def test_from_net_realized_capital_gains(self):
        assert _match_row_label("From net realized capital gains") == "distribution_from_gains"

    def test_gain_loss_slash(self):
        """'Realized/ Unrealized' with slash matches gain_loss."""
        assert _match_row_label("Net Realized/ Unrealized Gain") == "gain_loss_per_share"

    def test_gain_loss_and(self):
        """Original 'and' pattern still works."""
        assert _match_row_label("Net realized and unrealized gain (loss)") == "gain_loss_per_share"

    def test_income_yield_loss(self):
        """'Net investment loss to average net assets' matches income_yield."""
        assert _match_row_label("Ratio of net investment loss to average net assets") == "income_yield_pct"

    def test_bare_nii_does_not_match_distribution(self):
        """Bare 'Net investment income' matches nii, NOT distribution."""
        assert _match_row_label("Net investment income") == "nii_per_share"


# ===================================================================
# 25. Parse value with footnote markers and unclosed parens
# ===================================================================

class TestParseValueEdgeCases:

    def test_trailing_footnote_number(self):
        """'6.74 5' should parse as 6.74, not 6.745."""
        val = _parse_value("6.74 5", "total_return_pct", 1.0)
        assert val == pytest.approx(6.74)

    def test_trailing_footnote_with_percent(self):
        """'1.17% 6' should parse as 1.17."""
        val = _parse_value("1.17% 6", "expense_ratio_pct", 1.0)
        assert val == pytest.approx(1.17)

    def test_unclosed_paren_negative(self):
        """'(0.56' without closing paren is still negative."""
        val = _parse_value("(0.56", "distribution_from_nii", 1.0)
        assert val == pytest.approx(-0.56)

    def test_closed_paren_negative(self):
        """'(0.56)' with closing paren is negative."""
        val = _parse_value("(0.56)", "distribution_from_nii", 1.0)
        assert val == pytest.approx(-0.56)

    def test_em_dash(self):
        """Em-dash is NULL."""
        assert _parse_value("\u2014", "nav_begin_per_share", 1.0) is None

    def test_en_dash(self):
        """En-dash is NULL."""
        assert _parse_value("\u2013", "nav_begin_per_share", 1.0) is None


# ===================================================================
# 26. Vertical extraction with dollar-sign offset
# ===================================================================

class TestVerticalDollarOffset:

    def test_sec_html_dollar_split(self):
        """Full vertical table with SEC-style '$' split cells."""
        rows = [
            ["", "", "For the Year Ended December 31, 2024", "", "", ""],
            ["Net asset value, beginning of period", "", "$", "10.67", "", ""],
            ["Net investment income", "", "", "0.57", "", ""],
            ["Net realized and unrealized gain (loss)", "", "", "0.12", "", ""],
            ["From net investment income", "", "", "(0.56", ")", ""],
            ["Total distributions", "", "", "(0.56", ")", ""],
            ["Net asset value, end of period", "", "$", "10.80", "", ""],
            ["Total return", "", "", "6.74%", "", ""],
            ["Net assets, end of period (in thousands)", "", "$", "13,886", "", ""],
        ]
        records = _extract_vertical(rows, 1_000.0)
        assert len(records) >= 1
        rec = records[0]
        assert rec["nav_begin_per_share"] == pytest.approx(10.67)
        assert rec["nii_per_share"] == pytest.approx(0.57)
        assert rec["gain_loss_per_share"] == pytest.approx(0.12)
        assert rec["distribution_from_nii"] == pytest.approx(-0.56)
        assert rec["distribution_per_share"] == pytest.approx(-0.56)
        assert rec["nav_end_per_share"] == pytest.approx(10.80)
        assert rec["total_return_pct"] == pytest.approx(6.74)
        assert rec["net_assets_end"] == pytest.approx(13_886_000.0)


# ===================================================================
# 27. Heading false positive filtering
# ===================================================================

class TestHeadingFalsePositives:

    def test_long_paragraph_skipped(self):
        """Long paragraphs mentioning FH should be skipped."""
        long_text = "On February 3, 2020, CCLF SPV LLC was formed. " * 10
        html = f"""<html><body>
        <p>{long_text} Consolidated Financial Highlights are included.</p>
        <table><tr><td>Not a FH table</td></tr></table>
        <p><b>Financial Highlights</b></p>
        <table>
            <tr><td></td><td>Year Ended Dec 31, 2024</td></tr>
            <tr><td>Net asset value, beginning of period</td><td>$25.00</td></tr>
        </table>
        </body></html>"""
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "html.parser")
        tables = _find_fh_tables(soup)
        # Should find only the real FH table, not the one after the paragraph
        assert len(tables) == 1


# ===================================================================
# 28. Merged headers for horizontal layout
# ===================================================================

class TestFindMergedHeaders:

    def test_multi_row_headers(self):
        """Headers spanning multiple rows are merged correctly."""
        rows = [
            ["", "", "", "Investment Operations", ""],
            ["Selected Per Share Data", "Net Asset Value Beginning", "", "Net Investment Income (Loss)", ""],
            ["Class A", "", "", "", ""],
            ["01/01/2024 - 12/31/2024", "$", "10.00", "$", "0.50"],
        ]
        idx, merged = _find_merged_headers(rows)
        # Should merge rows 0-1 into headers and stop before data rows
        assert "Net Asset Value" in merged[1]
        assert "Net Investment Income" in merged[3]

    def test_data_row_stops_merge(self):
        """Rows with mostly numeric data stop header merging."""
        rows = [
            ["Header1", "Header2", "Header3"],
            ["01/01/2024", "$10.00", "5.25%"],
        ]
        idx, merged = _find_merged_headers(rows)
        # Data row should not be included in merged headers
        assert "10.00" not in merged[1]


# ===================================================================
# 11. Split-table extraction
# ===================================================================

class TestSplitTableExtraction:
    """Tests for _try_split_table_extraction (split label + data tables)."""

    def _build_split_table_html(self):
        """Build HTML with separate label and data tables (split layout).

        Mimics SEC filings where FH labels are in a narrow 1-col table
        and values are in a wide table with 3+ periods (9+ columns).
        """
        # Label table: 1-column with FH row labels
        label_rows = [
            "<tr><td></td></tr>",
            "<tr><td>Net asset value, beginning of year</td></tr>",
            "<tr><td>Net investment income</td></tr>",
            "<tr><td>Net realized and unrealized gains</td></tr>",
            "<tr><td>Total from investment operations</td></tr>",
            "<tr><td></td></tr>",
            "<tr><td>Less distributions:</td></tr>",
            "<tr><td>Net investment income</td></tr>",
            "<tr><td>Total distributions</td></tr>",
            "<tr><td></td></tr>",
            "<tr><td>Net asset value, end of year</td></tr>",
            "<tr><td></td></tr>",
            "<tr><td>Total return</td></tr>",
            "<tr><td>Expense ratio to average net assets</td></tr>",
            "<tr><td>Net assets, end of period</td></tr>",
        ]
        label_table = "<table>\n" + "\n".join(label_rows) + "\n</table>"

        # Data table: 9 columns (3 periods x 3 cols each: $ + value + spacer)
        data_rows = [
            "<tr><td colspan='9'>For the years ended December 31,</td></tr>",
            "<tr><td>2024</td><td></td><td></td><td>2023</td><td></td><td></td><td>2022</td><td></td><td></td></tr>",
            "<tr><td>$</td><td>10.50</td><td></td><td>$</td><td>9.80</td><td></td><td>$</td><td>9.00</td><td></td></tr>",
            "<tr><td></td><td>0.42</td><td></td><td></td><td>0.38</td><td></td><td></td><td>0.30</td><td></td></tr>",
            "<tr><td></td><td>0.15</td><td></td><td></td><td>0.72</td><td></td><td></td><td>0.55</td><td></td></tr>",
            "<tr><td></td><td>0.57</td><td></td><td></td><td>1.10</td><td></td><td></td><td>0.85</td><td></td></tr>",
            "<tr><td></td><td></td><td></td><td></td><td></td><td></td><td></td><td></td><td></td></tr>",
            "<tr><td></td><td></td><td></td><td></td><td></td><td></td><td></td><td></td><td></td></tr>",
            "<tr><td></td><td>(0.40)</td><td></td><td></td><td>(0.35)</td><td></td><td></td><td>(0.28)</td><td></td></tr>",
            "<tr><td></td><td>(0.40)</td><td></td><td></td><td>(0.35)</td><td></td><td></td><td>(0.28)</td><td></td></tr>",
            "<tr><td></td><td></td><td></td><td></td><td></td><td></td><td></td><td></td><td></td></tr>",
            "<tr><td>$</td><td>10.67</td><td></td><td>$</td><td>10.50</td><td></td><td>$</td><td>9.80</td><td></td></tr>",
            "<tr><td></td><td></td><td></td><td></td><td></td><td></td><td></td><td></td><td></td></tr>",
            "<tr><td></td><td>5.43</td><td></td><td></td><td>11.22</td><td></td><td></td><td>9.44</td><td></td></tr>",
            "<tr><td></td><td>1.25</td><td></td><td></td><td>1.30</td><td></td><td></td><td>1.35</td><td></td></tr>",
            "<tr><td>$</td><td>500,000</td><td></td><td>$</td><td>450,000</td><td></td><td>$</td><td>400,000</td><td></td></tr>",
        ]
        data_table = "<table>\n" + "\n".join(data_rows) + "\n</table>"

        html = f"""<html><body>
        <p><b>Financial Highlights</b></p>
        {label_table}
        <table><tr><td>(1) footnote</td></tr></table>
        {data_table}
        </body></html>"""
        return html

    def test_split_table_merges_correctly(self, tmp_path):
        """Split label+data tables should merge and extract multiple periods."""
        html = self._build_split_table_html()
        path = tmp_path / "split.html"
        path.write_text(html, encoding="utf-8")
        records = _parse_financial_highlights(str(path))
        assert len(records) == 3  # 2024, 2023, and 2022

    def test_split_table_extracts_nav(self, tmp_path):
        """NAV begin/end should be extracted from merged split tables."""
        html = self._build_split_table_html()
        path = tmp_path / "split.html"
        path.write_text(html, encoding="utf-8")
        records = _parse_financial_highlights(str(path))
        r2024 = next((r for r in records if r.get("period_label") == "2024"), None)
        assert r2024 is not None
        assert r2024["nav_begin_per_share"] == 10.50
        assert r2024["nav_end_per_share"] == 10.67

    def test_split_table_extracts_nii(self, tmp_path):
        """NII should be extracted from merged split tables."""
        html = self._build_split_table_html()
        path = tmp_path / "split.html"
        path.write_text(html, encoding="utf-8")
        records = _parse_financial_highlights(str(path))
        r2024 = next((r for r in records if r.get("period_label") == "2024"), None)
        assert r2024 is not None
        assert r2024["nii_per_share"] == 0.42

    def test_split_table_extracts_distributions(self, tmp_path):
        """Distributions should be negative (parentheses)."""
        html = self._build_split_table_html()
        path = tmp_path / "split.html"
        path.write_text(html, encoding="utf-8")
        records = _parse_financial_highlights(str(path))
        r2024 = next((r for r in records if r.get("period_label") == "2024"), None)
        assert r2024 is not None
        assert r2024["distribution_per_share"] == -0.40

    def test_split_table_not_triggered_for_normal_tables(self, tmp_path):
        """Normal vertical tables should NOT trigger split-table path."""
        rows = [
            ("", "Year Ended Dec 31, 2024", "Year Ended Dec 31, 2023"),
            ("Net asset value, beginning of period", "$10.00", "$9.50"),
            ("Net investment income", "0.40", "0.35"),
            ("Net asset value, end of period", "$10.50", "$9.80"),
            ("Total return", "5.00%", "3.16%"),
            ("Expense ratio to average net assets", "1.25%", "1.30%"),
            ("Net assets, end of period", "$500,000", "$400,000"),
        ]
        html = _build_fh_html(rows)
        path = tmp_path / "normal.html"
        path.write_text(html, encoding="utf-8")
        records = _parse_financial_highlights(str(path))
        # Should extract normally without needing split-table
        assert len(records) == 2
        assert records[0]["nav_begin_per_share"] == 10.00


# ===================================================================
# 12. Bare year period detection
# ===================================================================

class TestBareYearPeriods:
    """Tests for bare year detection in _find_period_columns."""

    def test_bare_year_detected(self):
        """Bare years like '2024' should be detected as period columns."""
        row = ["", "2024", "", "", "2023", "", "", "2022"]
        cols = _find_period_columns(row)
        assert len(cols) >= 3
        labels = [label for _, label in cols]
        assert "2024" in labels
        assert "2023" in labels

    def test_bare_year_skips_col_zero(self):
        """Bare year in col 0 should not be detected (label column)."""
        row = ["2024", "10.00", "0.40"]
        cols = _find_period_columns(row)
        assert len(cols) == 0

    def test_invalid_years_not_detected(self):
        """Years outside 2010-2029 should not be detected."""
        row = ["", "1999", "3000", "2024"]
        cols = _find_period_columns(row)
        assert len(cols) == 1
        assert cols[0][1] == "2024"


# ===================================================================
# 13. Element-level heading fallback
# ===================================================================

class TestElementLevelHeadingFallback:
    """Tests for element-level get_text() fallback in _find_fh_tables."""

    def test_split_text_node_found(self, tmp_path):
        """Heading split across child elements should still be found."""
        # "Financial Highlights" split into two <b> elements within a <div>
        html = """<html><body>
        <div><b>Financial</b> <b>Highlights</b></div>
        <table>
        <tr><td>Net asset value, beginning of period</td><td>$10.00</td></tr>
        <tr><td>Net investment income</td><td>0.40</td></tr>
        <tr><td>Net asset value, end of period</td><td>$10.50</td></tr>
        <tr><td>Total return</td><td>5.00%</td></tr>
        <tr><td>Expense ratio to average net assets</td><td>1.25%</td></tr>
        <tr><td>Net assets, end of period</td><td>$500,000</td></tr>
        </table>
        </body></html>"""
        path = tmp_path / "split_heading.html"
        path.write_text(html, encoding="utf-8")
        records = _parse_financial_highlights(str(path))
        assert len(records) >= 1
        assert records[0]["nav_begin_per_share"] == 10.00

    def test_normal_heading_still_works(self, tmp_path):
        """Normal single-text-node heading should still work."""
        html = """<html><body>
        <p>Financial Highlights</p>
        <table>
        <tr><td>Net asset value, beginning of period</td><td>$10.00</td></tr>
        <tr><td>Net investment income</td><td>0.40</td></tr>
        <tr><td>Net asset value, end of period</td><td>$10.50</td></tr>
        </table>
        </body></html>"""
        path = tmp_path / "normal_heading.html"
        path.write_text(html, encoding="utf-8")
        records = _parse_financial_highlights(str(path))
        assert len(records) >= 1


# ===================================================================
# 14. FH candidate detection
# ===================================================================

class TestIsFhCandidate:
    """Tests for _is_fh_candidate pre-filter."""

    def test_fh_table_is_candidate(self):
        """Table with NAV/NII/distributions/expense/turnover is a candidate."""
        rows = [
            ["", "Year Ended Dec 31, 2024"],
            ["Net asset value, beginning of period", "$25.00"],
            ["Net investment income", "$1.00"],
            ["Net realized and unrealized gain (loss)", "$0.50"],
            ["Distributions from net investment income", "$(0.80)"],
            ["Total distributions", "$(0.80)"],
            ["Net asset value, end of period", "$25.70"],
            ["Total return", "5.25%"],
            ["Ratio of expenses to average net assets", "1.50%"],
            ["Net assets, end of period", "$500,000"],
        ]
        assert _is_fh_candidate(rows) is True

    def test_portfolio_schedule_not_candidate(self):
        """Portfolio schedule (company names, no FH labels) is not a candidate."""
        rows = [
            ["Company", "Industry", "Fair Value"],
            ["Acme Corp", "Technology", "$10,000"],
            ["Beta Inc", "Healthcare", "$8,000"],
            ["Gamma LLC", "Energy", "$12,000"],
            ["Delta Co", "Finance", "$5,000"],
            ["Epsilon Ltd", "Consumer", "$7,000"],
            ["Zeta Partners", "Real Estate", "$9,000"],
        ]
        assert _is_fh_candidate(rows) is False

    def test_statement_of_operations_not_candidate(self):
        """Statement of Operations has NII but only 1-2 FH labels."""
        rows = [
            ["Investment Income:", ""],
            ["Interest income", "$5,000,000"],
            ["Dividend income", "$200,000"],
            ["Total investment income", "$5,200,000"],
            ["Expenses:", ""],
            ["Management fees", "$1,000,000"],
            ["Net investment income", "$3,500,000"],
            ["Realized gain on investments", "$500,000"],
        ]
        assert _is_fh_candidate(rows) is False

    def test_too_short_table(self):
        """Table with fewer than 5 rows is not a candidate."""
        rows = [
            ["Net asset value, beginning of period", "$25.00"],
            ["Net investment income", "$1.00"],
            ["Total return", "5.25%"],
        ]
        assert _is_fh_candidate(rows) is False

    def test_min_labels_parameter(self):
        """Threshold parameter works (min_labels=2 vs default 3)."""
        rows = [
            ["", "2024"],
            ["Net asset value, beginning of period", "$25.00"],
            ["Net investment income", "$1.00"],
            ["Some other row", "value"],
            ["Another row", "value"],
        ]
        assert _is_fh_candidate(rows, min_labels=2) is True
        assert _is_fh_candidate(rows, min_labels=3) is False


# ===================================================================
# 15. Broadened document-wide FH table search
# ===================================================================

class TestBroadenedSearch:
    """Tests for broadened search fallback in _parse_financial_highlights."""

    def test_wrong_table_linked_finds_real_fh(self, tmp_path):
        """FH heading leads to wrong table, real FH table later in doc."""
        html = """<html><body>
        <p><b>Financial Highlights</b></p>
        <!-- Wrong table: portfolio schedule -->
        <table>
            <tr><td>Company</td><td>Fair Value</td></tr>
            <tr><td>Acme Corp</td><td>$10,000</td></tr>
            <tr><td>Beta Inc</td><td>$8,000</td></tr>
        </table>
        <!-- Some intervening content -->
        <p>Notes to Financial Statements</p>
        <table>
            <tr><td>Note 1</td><td>Details</td></tr>
        </table>
        <!-- Real FH table further in the document -->
        <table>
            <tr><td></td><td>Year Ended Dec 31, 2024</td></tr>
            <tr><td>Net asset value, beginning of period</td><td>$25.00</td></tr>
            <tr><td>Net investment income</td><td>$1.00</td></tr>
            <tr><td>Net realized and unrealized gain (loss)</td><td>$0.50</td></tr>
            <tr><td>Distributions from net investment income</td><td>$(0.80)</td></tr>
            <tr><td>Total distributions</td><td>$(0.80)</td></tr>
            <tr><td>Net asset value, end of period</td><td>$25.70</td></tr>
            <tr><td>Total return</td><td>5.25%</td></tr>
            <tr><td>Ratio of expenses to average net assets</td><td>1.50%</td></tr>
            <tr><td>Net assets, end of period</td><td>$500,000</td></tr>
        </table>
        </body></html>"""
        path = tmp_path / "wrong_table.html"
        path.write_text(html, encoding="utf-8")
        records = _parse_financial_highlights(str(path))
        assert len(records) >= 1
        r = records[0]
        assert r["nav_begin_per_share"] == 25.0
        assert r["total_return_pct"] == 5.25

    def test_no_fh_table_returns_empty(self, tmp_path):
        """No FH table in doc at all returns empty list."""
        html = """<html><body>
        <p><b>Financial Highlights</b></p>
        <table>
            <tr><td>Company</td><td>Fair Value</td></tr>
            <tr><td>Acme Corp</td><td>$10,000</td></tr>
        </table>
        <table>
            <tr><td>Note 1</td><td>Details</td></tr>
        </table>
        </body></html>"""
        path = tmp_path / "no_fh.html"
        path.write_text(html, encoding="utf-8")
        records = _parse_financial_highlights(str(path))
        assert records == []

    def test_primary_extraction_not_broadened(self, tmp_path):
        """When primary extraction succeeds, broadened search is NOT triggered."""
        html = """<html><body>
        <p><b>Financial Highlights</b></p>
        <table>
            <tr><td></td><td>Year Ended Dec 31, 2024</td></tr>
            <tr><td>Net asset value, beginning of period</td><td>$25.00</td></tr>
            <tr><td>Net investment income</td><td>$1.00</td></tr>
            <tr><td>Net asset value, end of period</td><td>$26.00</td></tr>
            <tr><td>Total return</td><td>5.25%</td></tr>
        </table>
        <!-- Another FH-like table that should NOT be picked up -->
        <table>
            <tr><td></td><td>Year Ended Dec 31, 2023</td></tr>
            <tr><td>Net asset value, beginning of period</td><td>$99.00</td></tr>
            <tr><td>Net investment income</td><td>$9.00</td></tr>
            <tr><td>Net asset value, end of period</td><td>$99.99</td></tr>
            <tr><td>Total return</td><td>99.99%</td></tr>
        </table>
        </body></html>"""
        path = tmp_path / "primary_ok.html"
        path.write_text(html, encoding="utf-8")
        records = _parse_financial_highlights(str(path))
        # Should have 1 record from primary extraction only
        assert len(records) == 1
        assert records[0]["nav_begin_per_share"] == 25.0
