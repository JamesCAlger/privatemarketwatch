"""Tests for pipeline.html_extract (v3.0 extraction engine)."""

import json
import pytest

from pipeline.html_extract import (
    _convert_date,
    _extract_tables,
    _get_cell,
    _parse_dollar,
    _parse_rate,
    _resolve_headers,
    _strip_footnotes,
    extract_filing,
    load_template,
)


# ---------------------------------------------------------------------------
# _strip_footnotes
# ---------------------------------------------------------------------------

class TestStripFootnotes:
    def test_trailing_paren(self):
        assert _strip_footnotes("value (1)") == "value"

    def test_multiple_parens(self):
        assert _strip_footnotes("value (1)(2)") == "value"

    def test_trailing_stars(self):
        assert _strip_footnotes("value **") == "value"

    def test_no_footnotes(self):
        assert _strip_footnotes("clean value") == "clean value"

    def test_empty(self):
        assert _strip_footnotes("") == ""


# ---------------------------------------------------------------------------
# _parse_dollar
# ---------------------------------------------------------------------------

class TestParseDollar:
    def test_simple(self):
        assert _parse_dollar("1,234") == 1234.0

    def test_dollar_sign(self):
        assert _parse_dollar("$1,234") == 1234.0

    def test_negative_parens(self):
        assert _parse_dollar("(500)") == -500.0

    def test_negative_parens_with_dollar(self):
        assert _parse_dollar("($1,234)") == -1234.0

    def test_none(self):
        assert _parse_dollar(None) is None

    def test_dash(self):
        assert _parse_dollar("-") is None

    def test_empty(self):
        assert _parse_dollar("") is None

    def test_float_passthrough(self):
        assert _parse_dollar(42.5) == 42.5

    def test_int_passthrough(self):
        assert _parse_dollar(100) == 100.0

    def test_null_string(self):
        assert _parse_dollar("null") is None

    def test_foreign_currency(self):
        assert _parse_dollar("1,000 (CAD 76,091)") == 1000.0

    def test_multi_numbers(self):
        # First number extracted from multi-number cells
        assert _parse_dollar("1791278 150000") == 1791278.0

    def test_with_footnote(self):
        assert _parse_dollar("1,234 (1)") == 1234.0


# ---------------------------------------------------------------------------
# _parse_rate
# ---------------------------------------------------------------------------

class TestParseRate:
    def test_percentage(self):
        assert _parse_rate("5.50%") == 5.5

    def test_percentage_with_space(self):
        assert _parse_rate("5.50 %") == 5.5

    def test_decimal_conversion(self):
        assert _parse_rate(0.0525) == 5.25

    def test_none(self):
        assert _parse_rate(None) is None

    def test_dash(self):
        assert _parse_rate("-") is None

    def test_cash_suffix(self):
        # First number extracted from "6.5% Cash"
        assert _parse_rate("6.5% Cash") == 6.5

    def test_pik_suffix(self):
        # First number extracted from "10.0% PIK"
        assert _parse_rate("10.0% PIK") == 10.0

    def test_embedded_ref_spread(self):
        # First number extracted from combined rate+ref+spread text
        assert _parse_rate("10.50% (S+5.25%)") == 10.5


# ---------------------------------------------------------------------------
# _convert_date
# ---------------------------------------------------------------------------

class TestConvertDate:
    def test_mdy(self):
        assert _convert_date("12/31/2024") == "2024-12-31"

    def test_mdy_single_digit(self):
        assert _convert_date("1/5/2024") == "2024-01-05"

    def test_mdy_two_digit_year(self):
        assert _convert_date("6/15/24") == "2024-06-15"

    def test_mdy_two_digit_year_old(self):
        assert _convert_date("6/15/99") == "1999-06-15"

    def test_iso_passthrough(self):
        assert _convert_date("2024-12-31") == "2024-12-31"

    def test_partial_mmyyyy(self):
        assert _convert_date("10/2029") == "2029-10-01"

    def test_month_name_year(self):
        assert _convert_date("January 2017") == "2017-01-01"

    def test_month_day_year(self):
        assert _convert_date("June 30, 2024") == "2024-06-30"

    def test_dash(self):
        assert _convert_date("-") is None

    def test_empty(self):
        assert _convert_date("") is None

    def test_mdy_dash_format(self):
        assert _convert_date("3-15-2024") == "2024-03-15"

    def test_abbrev_month(self):
        assert _convert_date("Mar 2024") == "2024-03-01"


# ---------------------------------------------------------------------------
# _get_cell
# ---------------------------------------------------------------------------

class TestGetCell:
    def test_basic(self):
        row = ["alpha", "beta", "gamma"]
        assert _get_cell(row, 1) == "beta"

    def test_dollar_split(self):
        row = ["name", "$", "1,234", ""]
        assert _get_cell(row, 1) == "1,234"

    def test_empty_lookahead(self):
        row = ["name", "", "value"]
        assert _get_cell(row, 1) == "value"

    def test_out_of_range(self):
        row = ["a", "b"]
        assert _get_cell(row, 5) == ""

    def test_negative_index(self):
        row = ["a", "b"]
        assert _get_cell(row, -1) == ""

    def test_zwsp_stripped(self):
        row = ["\u200bvalue\u200b"]
        assert _get_cell(row, 0) == "value"

    def test_dollar_prefix_stripped(self):
        row = ["$1,234"]
        assert _get_cell(row, 0) == "1,234"

    def test_split_reference_spread(self):
        row = ["SF + ", "5.50 %"]
        assert _get_cell(row, 0) == "SF + 5.50 %"

    def test_split_negative_paren(self):
        row = ["(12,987", ")"]
        assert _get_cell(row, 0) == "(12,987)"


# ---------------------------------------------------------------------------
# _extract_tables
# ---------------------------------------------------------------------------

class TestExtractTables:
    def test_basic_table(self):
        html = """
        <html><body>
        <table>
            <tr><td>A</td><td>B</td></tr>
            <tr><td>1</td><td>2</td></tr>
        </table>
        </body></html>
        """
        tables = _extract_tables(html)
        assert len(tables) == 1
        assert tables[0][0] == ["A", "B"]
        assert tables[0][1] == ["1", "2"]

    def test_colspan(self):
        html = """
        <html><body>
        <table>
            <tr><td colspan="3">Header</td></tr>
            <tr><td>a</td><td>b</td><td>c</td></tr>
        </table>
        </body></html>
        """
        tables = _extract_tables(html)
        assert len(tables[0][0]) == 3
        assert tables[0][0] == ["Header", "", ""]

    def test_zwsp_stripped(self):
        html = """
        <html><body>
        <table>
            <tr><td>\u200bvalue\u200b</td></tr>
        </table>
        </body></html>
        """
        tables = _extract_tables(html)
        assert tables[0][0] == ["value"]

    def test_multiple_tables(self):
        html = """
        <html><body>
        <table><tr><td>T1</td></tr></table>
        <table><tr><td>T2</td></tr></table>
        </body></html>
        """
        tables = _extract_tables(html)
        assert len(tables) == 2


# ---------------------------------------------------------------------------
# load_template
# ---------------------------------------------------------------------------

class TestLoadTemplate:
    def test_v3_loads(self, tmp_path, monkeypatch):
        import pipeline.html_extract as mod
        monkeypatch.setattr(mod, "HTML_TEMPLATE_DIR", tmp_path)

        template = {
            "version": "3.0",
            "cik": "1234",
            "columns": {"fair_value": {"col": 5}},
            "default": {"tables": [0], "header_row": 0},
        }
        (tmp_path / "1234.json").write_text(json.dumps(template))

        result = load_template("0001234")
        assert result is not None
        assert result["version"] == "3.0"

    def test_v2_returns_none(self, tmp_path, monkeypatch):
        import pipeline.html_extract as mod
        monkeypatch.setattr(mod, "HTML_TEMPLATE_DIR", tmp_path)

        template = {"schema_version": "2.0", "entity_name": "Test"}
        (tmp_path / "1234.json").write_text(json.dumps(template))

        result = load_template("1234")
        assert result is None

    def test_missing_returns_none(self, tmp_path, monkeypatch):
        import pipeline.html_extract as mod
        monkeypatch.setattr(mod, "HTML_TEMPLATE_DIR", tmp_path)

        result = load_template("9999")
        assert result is None


# ---------------------------------------------------------------------------
# extract_filing (integration)
# ---------------------------------------------------------------------------

class TestExtractFiling:
    def _make_html(self, rows):
        """Build minimal HTML with one table."""
        lines = ["<html><body><table>"]
        for row in rows:
            cells = "".join(f"<td>{c}</td>" for c in row)
            lines.append(f"<tr>{cells}</tr>")
        lines.append("</table></body></html>")
        return "\n".join(lines)

    def test_basic_extraction(self):
        html = self._make_html([
            ["Company", "FV", "Cost"],
            ["Acme Corp", "1,000", "900"],
            ["Beta Inc", "2,000", "1,800"],
        ])
        template = {
            "version": "3.0",
            "columns": {
                "investment_identifier": {"col": 0},
                "fair_value": {"col": 1},
                "cost": {"col": 2},
            },
            "default": {"tables": [0], "header_row": 0},
            "dollar_unit": 1,
        }
        filing_meta = {
            "cik": "1234",
            "entity_name": "Test",
            "accession_number": "0001-23-456",
            "form_type": "10-K",
            "filing_date": "2024-03-15",
            "report_date": "2023-12-31",
        }

        holdings, stats = extract_filing(html, filing_meta, template)
        assert len(holdings) == 2
        assert holdings[0]["investment_identifier"] == "Acme Corp"
        assert holdings[0]["fair_value"] == "1,000"
        assert holdings[0]["cost"] == "900"
        assert holdings[0]["dollar_unit"] == 1
        assert holdings[1]["investment_identifier"] == "Beta Inc"
        assert stats["rows_extracted"] == 2

    def test_dollar_unit(self):
        html = self._make_html([
            ["Company", "FV"],
            ["Acme", "1,000"],
        ])
        template = {
            "version": "3.0",
            "columns": {
                "investment_identifier": {"col": 0},
                "fair_value": {"col": 1},
            },
            "default": {"tables": [0], "header_row": 0},
            "dollar_unit": 1000,
        }
        meta = {
            "cik": "1", "entity_name": "", "accession_number": "x",
            "form_type": "10-K", "filing_date": "", "report_date": "",
        }

        holdings, _ = extract_filing(html, meta, template)
        assert holdings[0]["fair_value"] == "1,000"
        assert holdings[0]["dollar_unit"] == 1000

    def test_filing_override(self):
        html = self._make_html([
            ["Company", "FV"],
            ["Acme", "500"],
        ])
        template = {
            "version": "3.0",
            "columns": {
                "investment_identifier": {"col": 0},
                "fair_value": {"col": 1},
            },
            "default": {"tables": [0], "header_row": 0},
            "dollar_unit": 1,
            "filings": {
                "special-acc": {
                    "dollar_unit": 1000,
                }
            },
        }
        meta = {
            "cik": "1", "entity_name": "", "accession_number": "special-acc",
            "form_type": "10-K", "filing_date": "", "report_date": "",
        }

        holdings, _ = extract_filing(html, meta, template)
        assert holdings[0]["fair_value"] == "500"
        assert holdings[0]["dollar_unit"] == 1000

    def test_subtotal_detected(self):
        html = self._make_html([
            ["Company", "FV"],
            ["Acme Corp", "1,000"],
            ["Total Investments", "1,000"],
        ])
        template = {
            "version": "3.0",
            "columns": {
                "investment_identifier": {"col": 0},
                "fair_value": {"col": 1},
            },
            "default": {"tables": [0], "header_row": 0},
            "dollar_unit": 1,
        }
        meta = {
            "cik": "1", "entity_name": "", "accession_number": "x",
            "form_type": "10-K", "filing_date": "", "report_date": "",
        }

        holdings, _ = extract_filing(html, meta, template)
        assert len(holdings) == 2
        assert holdings[0]["is_subtotal"] is False
        assert holdings[1]["is_subtotal"] is True

    def test_name_propagation(self):
        # Name propagation: when investment_identifier is empty AND lookahead
        # also finds nothing, the previous row's name carries forward.
        # Use a gap column (col 1 empty) so lookahead from col 0 finds "".
        html = self._make_html([
            ["Company", "", "Type", "FV"],
            ["Acme Corp", "", "First Lien", "1,000"],
            ["", "", "Second Lien", "500"],
        ])
        template = {
            "version": "3.0",
            "columns": {
                "investment_identifier": {"col": 0},
                "investment_type": {"col": 2},
                "fair_value": {"col": 3},
            },
            "default": {"tables": [0], "header_row": 0},
            "dollar_unit": 1,
        }
        meta = {
            "cik": "1", "entity_name": "", "accession_number": "x",
            "form_type": "10-K", "filing_date": "", "report_date": "",
        }

        holdings, _ = extract_filing(html, meta, template)
        assert len(holdings) == 2
        assert holdings[1]["investment_identifier"] == "Acme Corp"

    def test_multiple_tables(self):
        html = """
        <html><body>
        <table>
            <tr><td>Summary</td><td>Total</td></tr>
            <tr><td>All</td><td>999</td></tr>
        </table>
        <table>
            <tr><td>Company</td><td>FV</td></tr>
            <tr><td>Acme</td><td>500</td></tr>
        </table>
        <table>
            <tr><td>Company</td><td>FV</td></tr>
            <tr><td>Beta</td><td>400</td></tr>
        </table>
        </body></html>
        """
        template = {
            "version": "3.0",
            "columns": {
                "investment_identifier": {"col": 0},
                "fair_value": {"col": 1},
            },
            "default": {"tables": [1, 2], "header_row": 0},
            "dollar_unit": 1,
        }
        meta = {
            "cik": "1", "entity_name": "", "accession_number": "x",
            "form_type": "10-K", "filing_date": "", "report_date": "",
        }

        holdings, _ = extract_filing(html, meta, template)
        assert len(holdings) == 2
        names = [h["investment_identifier"] for h in holdings]
        assert "Acme" in names
        assert "Beta" in names

    def test_empty_html(self):
        holdings, stats = extract_filing(
            "<html><body></body></html>",
            {"cik": "1", "entity_name": "", "accession_number": "x",
             "form_type": "10-K", "filing_date": "", "report_date": ""},
            {"version": "3.0", "columns": {}, "default": {"tables": [0], "header_row": 0}},
        )
        assert holdings == []
        assert stats["tables_found"] == 0

    def test_columns_by_width_basic(self):
        """Tables with different widths use different column mappings."""
        # Table 0: 3 columns wide (w=3), FV at col 2
        # Table 1: 5 columns wide (w=5), FV at col 4
        html = """
        <html><body>
        <table>
            <tr><td>Company</td><td>Cost</td><td>FV</td></tr>
            <tr><td>Acme</td><td>900</td><td>1,000</td></tr>
        </table>
        <table>
            <tr><td>Company</td><td>Type</td><td>Rate</td><td>Cost</td><td>FV</td></tr>
            <tr><td>Beta</td><td>Loan</td><td>5%</td><td>800</td><td>2,000</td></tr>
        </table>
        </body></html>
        """
        template = {
            "version": "3.0",
            "columns": {
                "investment_identifier": {"col": 0},
                "fair_value": {"col": 2},
            },
            "columns_by_width": {
                "5": {"fair_value": {"col": 4}},
            },
            "default": {"tables": [0, 1], "header_row": 0},
            "dollar_unit": 1,
        }
        meta = {
            "cik": "1", "entity_name": "", "accession_number": "x",
            "form_type": "10-K", "filing_date": "", "report_date": "",
        }

        holdings, _ = extract_filing(html, meta, template)
        assert len(holdings) == 2
        assert holdings[0]["investment_identifier"] == "Acme"
        assert holdings[0]["fair_value"] == "1,000"  # w=3, default col 2
        assert holdings[1]["investment_identifier"] == "Beta"
        assert holdings[1]["fair_value"] == "2,000"  # w=5, override col 4

    def test_columns_by_width_not_present(self):
        """Without columns_by_width, all tables use default columns."""
        html = """
        <html><body>
        <table>
            <tr><td>Company</td><td>FV</td></tr>
            <tr><td>Acme</td><td>1,000</td></tr>
        </table>
        </body></html>
        """
        template = {
            "version": "3.0",
            "columns": {
                "investment_identifier": {"col": 0},
                "fair_value": {"col": 1},
            },
            "default": {"tables": [0], "header_row": 0},
            "dollar_unit": 1,
        }
        meta = {
            "cik": "1", "entity_name": "", "accession_number": "x",
            "form_type": "10-K", "filing_date": "", "report_date": "",
        }

        holdings, _ = extract_filing(html, meta, template)
        assert len(holdings) == 1
        assert holdings[0]["fair_value"] == "1,000"

    def test_columns_by_width_no_matching_width(self):
        """When table width doesn't match any key, default columns used."""
        html = """
        <html><body>
        <table>
            <tr><td>Company</td><td>FV</td><td>Cost</td></tr>
            <tr><td>Acme</td><td>1,000</td><td>900</td></tr>
        </table>
        </body></html>
        """
        template = {
            "version": "3.0",
            "columns": {
                "investment_identifier": {"col": 0},
                "fair_value": {"col": 1},
            },
            "columns_by_width": {
                "7": {"fair_value": {"col": 6}},
            },
            "default": {"tables": [0], "header_row": 0},
            "dollar_unit": 1,
        }
        meta = {
            "cik": "1", "entity_name": "", "accession_number": "x",
            "form_type": "10-K", "filing_date": "", "report_date": "",
        }

        holdings, _ = extract_filing(html, meta, template)
        assert holdings[0]["fair_value"] == "1,000"  # default col 1

    def test_columns_by_width_filing_override(self):
        """Filing-level columns_by_width overrides template-level."""
        html = """
        <html><body>
        <table>
            <tr><td>Company</td><td>CostA</td><td>FV_tmpl</td><td>FV_filing</td></tr>
            <tr><td>Acme</td><td>900</td><td>1,000</td><td>2,000</td></tr>
        </table>
        </body></html>
        """
        template = {
            "version": "3.0",
            "columns": {
                "investment_identifier": {"col": 0},
                "fair_value": {"col": 1},
            },
            "columns_by_width": {
                "4": {"fair_value": {"col": 2}},
            },
            "default": {"tables": [0], "header_row": 0},
            "dollar_unit": 1,
            "filings": {
                "special": {
                    "columns_by_width": {
                        "4": {"fair_value": {"col": 3}},
                    },
                },
            },
        }
        meta = {
            "cik": "1", "entity_name": "", "accession_number": "special",
            "form_type": "10-K", "filing_date": "", "report_date": "",
        }

        holdings, _ = extract_filing(html, meta, template)
        assert holdings[0]["fair_value"] == "2,000"  # filing override col 3

    def test_columns_by_width_merges_with_base(self):
        """Width override merges with (not replaces) base columns."""
        # Table has 5 cols. Width override only changes fair_value;
        # investment_identifier should still come from base columns.
        html = """
        <html><body>
        <table>
            <tr><td>Company</td><td>A</td><td>B</td><td>C</td><td>FV</td></tr>
            <tr><td>Acme</td><td>x</td><td>y</td><td>z</td><td>3,000</td></tr>
        </table>
        </body></html>
        """
        template = {
            "version": "3.0",
            "columns": {
                "investment_identifier": {"col": 0},
                "fair_value": {"col": 1},
            },
            "columns_by_width": {
                "5": {"fair_value": {"col": 4}},
            },
            "default": {"tables": [0], "header_row": 0},
            "dollar_unit": 1,
        }
        meta = {
            "cik": "1", "entity_name": "", "accession_number": "x",
            "form_type": "10-K", "filing_date": "", "report_date": "",
        }

        holdings, _ = extract_filing(html, meta, template)
        assert holdings[0]["investment_identifier"] == "Acme"  # from base
        assert holdings[0]["fair_value"] == "3,000"  # from width override

    def test_table_periods_basic(self):
        """Tables mapped in table_periods get the specified period date."""
        html = """
        <html><body>
        <table>
            <tr><td>Company</td><td>FV</td></tr>
            <tr><td>Acme</td><td>1,000</td></tr>
        </table>
        <table>
            <tr><td>Company</td><td>FV</td></tr>
            <tr><td>Beta</td><td>2,000</td></tr>
        </table>
        </body></html>
        """
        template = {
            "version": "3.0",
            "columns": {
                "investment_identifier": {"col": 0},
                "fair_value": {"col": 1},
            },
            "default": {"tables": [0, 1], "header_row": 0},
            "dollar_unit": 1,
            "filings": {
                "10k-acc": {
                    "tables": [0, 1],
                    "table_periods": {
                        "2023-12-31": [0],
                        "2022-12-31": [1],
                    },
                },
            },
        }
        meta = {
            "cik": "1", "entity_name": "", "accession_number": "10k-acc",
            "form_type": "10-K", "filing_date": "2024-03-01",
            "report_date": "2023-12-31",
        }

        holdings, _ = extract_filing(html, meta, template)
        assert len(holdings) == 2
        assert holdings[0]["period"] == "2023-12-31"
        assert holdings[0]["report_date"] == "2023-12-31"
        assert holdings[1]["period"] == "2022-12-31"
        assert holdings[1]["report_date"] == "2023-12-31"

    def test_table_periods_not_present(self):
        """Without table_periods, all rows get report_date as period."""
        html = """
        <html><body>
        <table>
            <tr><td>Company</td><td>FV</td></tr>
            <tr><td>Acme</td><td>1,000</td></tr>
        </table>
        </body></html>
        """
        template = {
            "version": "3.0",
            "columns": {
                "investment_identifier": {"col": 0},
                "fair_value": {"col": 1},
            },
            "default": {"tables": [0], "header_row": 0},
            "dollar_unit": 1,
        }
        meta = {
            "cik": "1", "entity_name": "", "accession_number": "x",
            "form_type": "10-K", "filing_date": "", "report_date": "2023-12-31",
        }

        holdings, _ = extract_filing(html, meta, template)
        assert holdings[0]["period"] == "2023-12-31"

    def test_table_periods_unmapped_table_gets_report_date(self):
        """Tables not in any table_periods entry get report_date."""
        html = """
        <html><body>
        <table>
            <tr><td>Company</td><td>FV</td></tr>
            <tr><td>Acme</td><td>1,000</td></tr>
        </table>
        <table>
            <tr><td>Company</td><td>FV</td></tr>
            <tr><td>Beta</td><td>2,000</td></tr>
        </table>
        </body></html>
        """
        template = {
            "version": "3.0",
            "columns": {
                "investment_identifier": {"col": 0},
                "fair_value": {"col": 1},
            },
            "default": {"tables": [0, 1], "header_row": 0},
            "dollar_unit": 1,
            "filings": {
                "acc": {
                    "tables": [0, 1],
                    "table_periods": {
                        "2022-12-31": [1],
                    },
                },
            },
        }
        meta = {
            "cik": "1", "entity_name": "", "accession_number": "acc",
            "form_type": "10-K", "filing_date": "", "report_date": "2023-12-31",
        }

        holdings, _ = extract_filing(html, meta, template)
        assert holdings[0]["period"] == "2023-12-31"  # unmapped -> report_date
        assert holdings[1]["period"] == "2022-12-31"  # mapped

    def test_subtotal_members_capital(self):
        """MEMBERS' CAPITAL rows are marked as subtotals."""
        html = self._make_html([
            ["Company", "FV"],
            ["Acme Corp", "1,000"],
            ["MEMBERS' CAPITAL", "5,000"],
        ])
        template = {
            "version": "3.0",
            "columns": {
                "investment_identifier": {"col": 0},
                "fair_value": {"col": 1},
            },
            "default": {"tables": [0], "header_row": 0},
            "dollar_unit": 1,
        }
        meta = {
            "cik": "1", "entity_name": "", "accession_number": "x",
            "form_type": "10-K", "filing_date": "", "report_date": "",
        }
        holdings, _ = extract_filing(html, meta, template)
        assert len(holdings) == 2
        assert holdings[0]["is_subtotal"] is False
        assert holdings[1]["is_subtotal"] is True

    def test_subtotal_stockholders_equity(self):
        """Stockholders' Equity rows are marked as subtotals."""
        html = self._make_html([
            ["Company", "FV"],
            ["Acme Corp", "1,000"],
            ["Stockholders\u2019 Equity", "10,000"],
        ])
        template = {
            "version": "3.0",
            "columns": {
                "investment_identifier": {"col": 0},
                "fair_value": {"col": 1},
            },
            "default": {"tables": [0], "header_row": 0},
            "dollar_unit": 1,
        }
        meta = {
            "cik": "1", "entity_name": "", "accession_number": "x",
            "form_type": "10-K", "filing_date": "", "report_date": "",
        }
        holdings, _ = extract_filing(html, meta, template)
        assert holdings[1]["is_subtotal"] is True

    def test_subtotal_net_asset_value(self):
        """Net asset value rows are marked as subtotals."""
        html = self._make_html([
            ["Company", "FV"],
            ["Acme Corp", "1,000"],
            ["Net Asset Value Per Unit", "15.50"],
        ])
        template = {
            "version": "3.0",
            "columns": {
                "investment_identifier": {"col": 0},
                "fair_value": {"col": 1},
            },
            "default": {"tables": [0], "header_row": 0},
            "dollar_unit": 1,
        }
        meta = {
            "cik": "1", "entity_name": "", "accession_number": "x",
            "form_type": "10-K", "filing_date": "", "report_date": "",
        }
        holdings, _ = extract_filing(html, meta, template)
        assert holdings[1]["is_subtotal"] is True

    def test_rate_raw_capture(self):
        """Engine captures raw cell text for rate fields; no parsing."""
        html = self._make_html([
            ["Company", "Rate", "FV"],
            ["Acme", "10.50% (S+5.25%)", "1,000"],
        ])
        template = {
            "version": "3.0",
            "columns": {
                "investment_identifier": {"col": 0},
                "interest_rate": {"col": 1},
                "fair_value": {"col": 2},
            },
            "default": {"tables": [0], "header_row": 0},
            "dollar_unit": 1,
        }
        meta = {
            "cik": "1", "entity_name": "", "accession_number": "x",
            "form_type": "10-K", "filing_date": "", "report_date": "",
        }

        holdings, _ = extract_filing(html, meta, template)
        assert holdings[0]["interest_rate"] == "10.50% (S+5.25%)"
        # No text parsing -- ref/spread not derived from rate cell
        assert holdings[0]["reference_rate_type"] == ""
        assert holdings[0]["basis_spread"] == ""


# ---------------------------------------------------------------------------
# _resolve_headers
# ---------------------------------------------------------------------------

class TestResolveHeaders:
    def test_basic(self):
        header = ["", "Company", "Cost", "Fair Value"]
        columns = {"fair_value": {"col": 5, "header": "fair value"}}
        result = _resolve_headers(header, columns)
        assert result == {"fair_value": 3}

    def test_or_pattern(self):
        header = ["Name", "Shares", "FV"]
        columns = {"shares_held": {"col": 9, "header": "shares|units"}}
        result = _resolve_headers(header, columns)
        assert result == {"shares_held": 1}

    def test_case_insensitive(self):
        header = ["Issuer", "FAIR VALUE (3)"]
        columns = {"fair_value": {"col": 0, "header": "fair value"}}
        result = _resolve_headers(header, columns)
        assert result == {"fair_value": 1}

    def test_no_match(self):
        header = ["Company", "Type", "Cost"]
        columns = {"interest_rate": {"col": 3, "header": "interest rate"}}
        result = _resolve_headers(header, columns)
        assert result == {}

    def test_no_header_key(self):
        """Fields without 'header' key are not included in resolved dict."""
        header = ["Company", "Fair Value"]
        columns = {"fair_value": {"col": 1}}
        result = _resolve_headers(header, columns)
        assert result == {}

    def test_non_dict_spec_ignored(self):
        header = ["Company", "Fair Value"]
        columns = {"fair_value": 1}
        result = _resolve_headers(header, columns)
        assert result == {}


# ---------------------------------------------------------------------------
# Header resolution in extract_filing (integration)
# ---------------------------------------------------------------------------

class TestHeaderExtraction:
    def _make_html(self, rows):
        lines = ["<html><body><table>"]
        for row in rows:
            cells = "".join(f"<td>{c}</td>" for c in row)
            lines.append(f"<tr>{cells}</tr>")
        lines.append("</table></body></html>")
        return "\n".join(lines)

    def _meta(self):
        return {
            "cik": "1", "entity_name": "", "accession_number": "x",
            "form_type": "10-K", "filing_date": "", "report_date": "",
        }

    def test_debt_table_rate_extracted(self):
        """When header matches 'interest rate', rate is extracted."""
        html = self._make_html([
            ["Company", "Interest Rate", "Fair Value"],
            ["Acme", "10.5%", "1,000"],
        ])
        template = {
            "version": "3.0",
            "columns": {
                "investment_identifier": {"col": 0},
                "interest_rate": {"col": 1, "header": "interest rate"},
                "fair_value": {"col": 2, "header": "fair value"},
            },
            "default": {"tables": [0], "header_row": 0},
            "dollar_unit": 1,
        }
        holdings, _ = extract_filing(html, self._meta(), template)
        assert len(holdings) == 1
        assert holdings[0]["interest_rate"] == "10.5%"
        assert holdings[0]["fair_value"] == "1,000"

    def test_equity_table_rate_skipped(self):
        """When header says 'Shares' (not 'Interest Rate'), interest_rate is skipped."""
        html = self._make_html([
            ["Company", "Shares", "Fair Value"],
            ["Beta Inc", "5,000", "2,000"],
        ])
        template = {
            "version": "3.0",
            "columns": {
                "investment_identifier": {"col": 0},
                "interest_rate": {"col": 1, "header": "interest rate"},
                "shares_held": {"col": 1, "header": "shares|units"},
                "fair_value": {"col": 2, "header": "fair value"},
            },
            "default": {"tables": [0], "header_row": 0},
            "dollar_unit": 1,
        }
        holdings, _ = extract_filing(html, self._meta(), template)
        assert len(holdings) == 1
        assert holdings[0]["interest_rate"] == ""
        assert holdings[0]["shares_held"] == "5,000"
        assert holdings[0]["fair_value"] == "2,000"

    def test_continuation_carries_forward(self):
        """Second table with no headers inherits resolved mapping from first."""
        html = """
        <html><body>
        <table>
            <tr><td>Company</td><td>Fair Value</td></tr>
            <tr><td>Acme</td><td>1,000</td></tr>
        </table>
        <table>
            <tr><td></td><td></td></tr>
            <tr><td>Beta</td><td>2,000</td></tr>
        </table>
        </body></html>
        """
        template = {
            "version": "3.0",
            "columns": {
                "investment_identifier": {"col": 0},
                "fair_value": {"col": 5, "header": "fair value"},
            },
            "default": {"tables": [0, 1], "header_row": 0},
            "dollar_unit": 1,
        }
        holdings, _ = extract_filing(html, self._meta(), template)
        assert len(holdings) == 2
        # First table: header resolved fair_value to col 1
        assert holdings[0]["fair_value"] == "1,000"
        # Second table: no new headers -> carries forward col 1
        assert holdings[1]["fair_value"] == "2,000"

    def test_no_header_field_uses_positional(self):
        """Fields without 'header' key always use positional col."""
        html = self._make_html([
            ["Company", "Maturity", "Fair Value"],
            ["Acme", "12/31/2025", "1,000"],
        ])
        template = {
            "version": "3.0",
            "columns": {
                "investment_identifier": {"col": 0},
                "maturity_date": {"col": 1},  # no "header" key -> positional
                "fair_value": {"col": 2, "header": "fair value"},
            },
            "default": {"tables": [0], "header_row": 0},
            "dollar_unit": 1,
        }
        holdings, _ = extract_filing(html, self._meta(), template)
        assert len(holdings) == 1
        assert holdings[0]["maturity_date"] == "12/31/2025"
        assert holdings[0]["fair_value"] == "1,000"

    def test_continuation_column_shift_basic(self):
        """Continuation rows shift financial columns left when configured."""
        # Simulates Prospect Capital w=13: company rows have industry at col 1,
        # continuation rows have numeric at col 1 (shifted financial data).
        html = self._make_html([
            # Header row
            ["Company", "Industry", "", "Principal", "", "", "Cost", "", "",
             "FV", "", "", "Pct"],
            # Company row: col 0=name, col 1=industry text, col 3=$, col 6=$, col 9=$
            ["Acme Corp", "Technology", "", "$", "20,000", "", "$", "18,000",
             "", "$", "19,000", "", "5.0%"],
            # Continuation row: col 0=instrument, col 1=numeric (no alpha) ->
            # shift -2: principal at col 1, cost at col 4, FV at col 7
            ["First Lien Loan", "$", "15,000", "", "$", "14,000", "", "$",
             "14,500", "", "3.5%", "", ""],
        ])
        template = {
            "version": "3.0",
            "columns": {
                "investment_identifier": {"col": 0},
                "industry": {"col": 1},
                "principal_amount": {"col": 3},
                "cost": {"col": 6},
                "fair_value": {"col": 9},
                "pct_of_net_assets": {"col": 12},
            },
            "columns_by_width": {
                "13": {
                    "continuation_column_shift": {"shift": -2, "detect_col": 1},
                    "investment_identifier": {"col": 0},
                    "industry": {"col": 1},
                    "principal_amount": {"col": 3},
                    "cost": {"col": 6},
                    "fair_value": {"col": 9},
                    "pct_of_net_assets": {"col": 12},
                },
            },
            "default": {"tables": [0], "header_row": 0},
            "dollar_unit": 1,
        }
        meta = {
            "cik": "1", "entity_name": "", "accession_number": "x",
            "form_type": "10-K", "filing_date": "", "report_date": "",
        }
        holdings, _ = extract_filing(html, meta, template)
        assert len(holdings) == 2
        # Company row: no shift (industry col has alpha text)
        assert holdings[0]["investment_identifier"] == "Acme Corp"
        assert holdings[0]["fair_value"] == "19,000"
        # Continuation row: shifted -2, so FV reads from col 9-2=7
        assert holdings[1]["investment_identifier"] == "First Lien Loan"
        assert holdings[1]["fair_value"] == "14,500"

    def test_continuation_column_shift_no_shift_when_alpha(self):
        """Rows with alphabetic text at detect_col are NOT shifted."""
        html = self._make_html([
            ["Company", "Industry", "", "FV"],
            ["Acme Corp", "Tech", "", "1,000"],
            ["Beta Inc", "Finance", "", "2,000"],
        ])
        template = {
            "version": "3.0",
            "columns": {
                "investment_identifier": {"col": 0},
                "industry": {"col": 1},
                "fair_value": {"col": 3},
            },
            "columns_by_width": {
                "4": {
                    "continuation_column_shift": {"shift": -2, "detect_col": 1},
                    "investment_identifier": {"col": 0},
                    "industry": {"col": 1},
                    "fair_value": {"col": 3},
                },
            },
            "default": {"tables": [0], "header_row": 0},
            "dollar_unit": 1,
        }
        meta = {
            "cik": "1", "entity_name": "", "accession_number": "x",
            "form_type": "10-K", "filing_date": "", "report_date": "",
        }
        holdings, _ = extract_filing(html, meta, template)
        assert len(holdings) == 2
        # Both rows have alpha at detect_col -> no shift
        assert holdings[0]["fair_value"] == "1,000"
        assert holdings[1]["fair_value"] == "2,000"

    def test_continuation_column_shift_empty_name_no_shift(self):
        """Rows with empty identifier are NOT shifted (subtotal/blank rows)."""
        html = self._make_html([
            ["Company", "Industry", "", "FV"],
            ["Acme Corp", "Tech", "", "1,000"],
            # Empty name, numeric at detect_col -> but no shift because name empty
            ["", "500", "", "500"],
        ])
        template = {
            "version": "3.0",
            "columns": {
                "investment_identifier": {"col": 0},
                "industry": {"col": 1},
                "fair_value": {"col": 3},
            },
            "columns_by_width": {
                "4": {
                    "continuation_column_shift": {"shift": -2, "detect_col": 1},
                    "investment_identifier": {"col": 0},
                    "industry": {"col": 1},
                    "fair_value": {"col": 3},
                },
            },
            "default": {"tables": [0], "header_row": 0},
            "dollar_unit": 1,
        }
        meta = {
            "cik": "1", "entity_name": "", "accession_number": "x",
            "form_type": "10-K", "filing_date": "", "report_date": "",
        }
        holdings, _ = extract_filing(html, meta, template)
        # Second row: empty name + FV -> gets name propagated, reads FV at col 3
        assert holdings[1]["fair_value"] == "500"

    def test_continuation_column_shift_template_level(self):
        """continuation_column_shift at template root level works."""
        html = self._make_html([
            ["Company", "Industry", "", "FV"],
            ["Acme Corp", "Tech", "", "1,000"],
            ["First Lien", "500", "", ""],
        ])
        template = {
            "version": "3.0",
            "columns": {
                "investment_identifier": {"col": 0},
                "industry": {"col": 1},
                "fair_value": {"col": 3},
            },
            "continuation_column_shift": {"shift": -2, "detect_col": 1},
            "default": {"tables": [0], "header_row": 0},
            "dollar_unit": 1,
        }
        meta = {
            "cik": "1", "entity_name": "", "accession_number": "x",
            "form_type": "10-K", "filing_date": "", "report_date": "",
        }
        holdings, _ = extract_filing(html, meta, template)
        assert len(holdings) == 2
        # Continuation row "First Lien" has numeric "500" at detect_col 1
        # -> shifted: FV reads from col 3-2=1 -> "500"
        assert holdings[1]["fair_value"] == "500"

    def test_header_resolves_different_col(self):
        """Header resolution overrides the positional col in template."""
        html = self._make_html([
            ["Company", "Cost", "Extra", "Fair Value"],
            ["Acme", "900", "", "1,000"],
        ])
        template = {
            "version": "3.0",
            "columns": {
                "investment_identifier": {"col": 0},
                "fair_value": {"col": 1, "header": "fair value"},
            },
            "default": {"tables": [0], "header_row": 0},
            "dollar_unit": 1,
        }
        holdings, _ = extract_filing(html, self._meta(), template)
        assert len(holdings) == 1
        # Header found "Fair Value" at col 3, overriding template's col 1
        assert holdings[0]["fair_value"] == "1,000"
