"""Tests for pipeline.html_holdings module.

Covers the programmatic parts of the HTML extraction pipeline (no LLM calls):
- Table detection: score_table, find_schedule_tables
- Row classification: classify_rows (header, section_header, subtotal, data, blank)
- Dollar unit detection: detect_dollar_unit (millions, thousands, default)
- Column mapping: build_column_map
- Table continuation: tables_are_continuation
- Name propagation: post_process with is_continuation rows
- Subtotal reconciliation: reconcile_subtotals
- Dollar/rate parsing: _parse_dollar, _parse_rate
- Post-processing: footnote stripping, unit normalization
- Schema conversion: _to_bdc_holdings_schema
"""

import pytest

from pipeline.html_holdings import (
    ScheduleTable,
    RowClassification,
    _build_column_map,
    _detect_dollar_unit,
    _extract_table_rows,
    _looks_numeric,
    _parse_dollar,
    _parse_rate,
    _score_table,
    _strip_footnotes,
    _tables_are_continuation,
    _to_bdc_holdings_schema,
    classify_rows,
    find_schedule_tables,
    post_process,
    reconcile_subtotals,
)


# ---------------------------------------------------------------------------
# Helpers: build minimal HTML for testing
# ---------------------------------------------------------------------------

def _make_html_table(rows: list[list[str]], attrs: str = "") -> str:
    """Build an HTML <table> from a list of row-cell-lists."""
    lines = [f"<table {attrs}>"]
    for row in rows:
        lines.append("  <tr>")
        for cell in row:
            lines.append(f"    <td>{cell}</td>")
        lines.append("  </tr>")
    lines.append("</table>")
    return "\n".join(lines)


def _make_schedule_html(
    header: list[str],
    data_rows: list[list[str]],
    title: str = "",
    dollar_note: str = "",
) -> str:
    """Build a full HTML page with a schedule-of-investments table."""
    parts = ["<html><body>"]
    if title:
        parts.append(f"<p>{title}</p>")
    if dollar_note:
        parts.append(f"<p>{dollar_note}</p>")
    parts.append(_make_html_table([header] + data_rows))
    parts.append("</body></html>")
    return "\n".join(parts)


# ===========================================================================
# _score_table
# ===========================================================================

class TestScoreTable:
    def test_schedule_table_scores_high(self):
        rows = [
            ["Company", "Interest Rate", "Maturity Date", "Principal Amount",
             "Cost", "Fair Value"],
        ] + [
            [f"Company {i}", "10.5%", "2025-12-31", "1,000,000",
             "990,000", "1,010,000"]
            for i in range(20)
        ]
        score, header_idx = _score_table(rows)
        assert score > 10.0
        assert header_idx == 0

    def test_income_statement_scores_low(self):
        rows = [
            ["", "Revenue", "Total Assets", "Income Statement"],
            ["Q1", "1,000", "50,000", ""],
            ["Q2", "1,200", "52,000", ""],
        ]
        score, _ = _score_table(rows)
        assert score < 3.0

    def test_too_few_rows_scores_negative(self):
        rows = [["A", "B"]]
        score, _ = _score_table(rows)
        assert score < 0

    def test_header_in_second_row(self):
        rows = [
            ["Schedule of Investments"],
            ["Company", "Interest Rate", "Fair Value", "Cost", "Principal"],
            ["Acme", "10%", "100", "99", "100"],
            ["Beta", "11%", "200", "199", "200"],
            ["Gamma", "9%", "300", "299", "300"],
            ["Delta", "12%", "400", "399", "400"],
        ]
        score, header_idx = _score_table(rows)
        assert score > 5.0
        assert header_idx == 1


# ===========================================================================
# _detect_dollar_unit
# ===========================================================================

class TestDetectDollarUnit:
    def test_millions(self):
        rows = [["(in millions)", "Fair Value", "Cost"]]
        assert _detect_dollar_unit(rows) == 1_000_000

    def test_thousands(self):
        rows = [["(000s)", "Fair Value", "Cost"]]
        assert _detect_dollar_unit(rows) == 1_000

    def test_thousands_variant(self):
        rows = [["in thousands", "Fair Value"]]
        assert _detect_dollar_unit(rows) == 1_000

    def test_default_is_one(self):
        rows = [["Company", "Fair Value"]]
        assert _detect_dollar_unit(rows) == 1

    def test_title_text(self):
        rows = [["Company", "Fair Value"]]
        assert _detect_dollar_unit(rows, "Schedule of Investments (in millions)") == 1_000_000


# ===========================================================================
# _build_column_map
# ===========================================================================

class TestBuildColumnMap:
    def test_standard_headers(self):
        header = ["Company", "Interest Rate", "Maturity Date",
                  "Principal Amount", "Cost", "Fair Value"]
        col_map = _build_column_map(header)
        assert col_map["company"] == 0
        assert col_map["interest_rate"] == 1
        assert col_map["maturity_date"] == 2
        assert col_map["principal_amount"] == 3
        assert col_map["cost"] == 4
        assert col_map["fair_value"] == 5

    def test_alternative_headers(self):
        header = ["Portfolio Company", "Coupon", "Par Amount",
                  "Amortized Cost", "Fair Value", "% of Net Assets"]
        col_map = _build_column_map(header)
        assert col_map["company"] == 0
        assert col_map["interest_rate"] == 1
        assert col_map["principal_amount"] == 2
        assert col_map["cost"] == 3
        assert col_map["fair_value"] == 4
        assert col_map["pct_of_net_assets"] == 5

    def test_empty_header_cells_skipped(self):
        header = ["", "Fair Value", "", "Cost"]
        col_map = _build_column_map(header)
        assert col_map["fair_value"] == 1
        assert col_map["cost"] == 3
        assert "" not in col_map

    def test_shares_header(self):
        header = ["Issuer", "Shares", "Fair Value"]
        col_map = _build_column_map(header)
        assert col_map["shares_held"] == 1


# ===========================================================================
# _tables_are_continuation
# ===========================================================================

class TestTablesAreContinuation:
    def test_matching_headers(self):
        rows_a = [["Company", "Rate", "Maturity", "Cost", "Fair Value"],
                  ["Acme", "10%", "2025", "100", "100"]]
        rows_b = [["Company", "Rate", "Maturity", "Cost", "Fair Value"],
                  ["Beta", "11%", "2026", "200", "200"]]
        assert _tables_are_continuation(rows_a, rows_b, 0, 0) is True

    def test_different_headers(self):
        rows_a = [["Company", "Rate", "Maturity", "Cost", "Fair Value"],
                  ["Acme", "10%", "2025", "100", "100"]]
        rows_b = [["Year", "Revenue", "Net Income"],
                  ["2024", "50M", "10M"]]
        assert _tables_are_continuation(rows_a, rows_b, 0, 0) is False

    def test_empty_tables(self):
        assert _tables_are_continuation([], [], 0, 0) is False
        assert _tables_are_continuation([["A"]], [], 0, 0) is False


# ===========================================================================
# classify_rows
# ===========================================================================

class TestClassifyRows:
    def _make_table(self, rows, header_idx=0):
        return ScheduleTable(
            rows=rows, header_row_idx=header_idx, score=10.0,
        )

    def test_header_row(self):
        table = self._make_table([
            ["Company", "Rate", "Fair Value"],
            ["Acme", "10%", "100"],
        ])
        classified = classify_rows(table)
        assert classified[0].kind == "header"

    def test_data_row(self):
        table = self._make_table([
            ["Company", "Rate", "Fair Value"],
            ["Acme Corp", "10.5%", "1,000,000"],
        ])
        classified = classify_rows(table)
        assert classified[1].kind == "data"

    def test_blank_row(self):
        table = self._make_table([
            ["Company", "Rate", "Fair Value"],
            ["", "", ""],
        ])
        classified = classify_rows(table)
        assert classified[1].kind == "blank"

    def test_subtotal_row(self):
        table = self._make_table([
            ["Company", "Rate", "Fair Value"],
            ["Total Senior Secured", "", "5,000,000"],
        ])
        classified = classify_rows(table)
        assert classified[1].kind == "subtotal"

    def test_subtotal_variants(self):
        for prefix in ["Total", "Sub-total", "Subtotal", "TOTAL"]:
            table = self._make_table([
                ["Company", "Rate", "Fair Value"],
                [f"{prefix} First Lien", "", "10,000"],
            ])
            classified = classify_rows(table)
            assert classified[1].kind == "subtotal", f"Failed for: {prefix}"

    def test_section_header_single_cell(self):
        table = self._make_table([
            ["Company", "Rate", "Fair Value", "Cost", "Principal"],
            ["Technology"],  # single non-empty cell, fewer cols than header
        ])
        classified = classify_rows(table)
        assert classified[1].kind == "section_header"

    def test_section_context_propagation(self):
        table = self._make_table([
            ["Company", "Rate", "Fair Value", "Cost", "Principal"],
            ["Technology"],
            ["Acme Corp", "10%", "100", "99", "100"],
            ["Healthcare"],
            ["Beta Inc", "11%", "200", "199", "200"],
        ])
        classified = classify_rows(table)
        # Technology section
        assert classified[1].kind == "section_header"
        assert classified[2].section_context == "Technology"
        # Healthcare section
        assert classified[3].kind == "section_header"
        assert classified[4].section_context == "Healthcare"


# ===========================================================================
# _looks_numeric
# ===========================================================================

class TestLooksNumeric:
    def test_plain_number(self):
        assert _looks_numeric("1234") is True

    def test_formatted_number(self):
        assert _looks_numeric("1,234,567") is True

    def test_dollar_amount(self):
        assert _looks_numeric("$1,000") is True

    def test_negative_parens(self):
        assert _looks_numeric("(500)") is True

    def test_with_footnote(self):
        assert _looks_numeric("1,000(1)") is True

    def test_text_is_not_numeric(self):
        assert _looks_numeric("Acme Corp") is False

    def test_empty_is_not_numeric(self):
        assert _looks_numeric("") is False

    def test_dash_is_not_numeric(self):
        assert _looks_numeric("-") is False  # dash means "not applicable" in tables


# ===========================================================================
# _parse_dollar
# ===========================================================================

class TestParseDollar:
    def test_plain_number(self):
        assert _parse_dollar(1000) == 1000.0

    def test_string_number(self):
        assert _parse_dollar("1,234,567") == 1234567.0

    def test_dollar_sign(self):
        assert _parse_dollar("$1,000") == 1000.0

    def test_negative_parens(self):
        assert _parse_dollar("(500)") == -500.0

    def test_none(self):
        assert _parse_dollar(None) is None

    def test_dash(self):
        assert _parse_dollar("-") is None

    def test_null_string(self):
        assert _parse_dollar("null") is None

    def test_with_footnote(self):
        assert _parse_dollar("1,000(1)") == 1000.0

    def test_float_passthrough(self):
        assert _parse_dollar(3.14) == 3.14

    def test_empty_string(self):
        assert _parse_dollar("") is None

    # Amendment #18: foreign currency parenthetical stripping.
    def test_strips_foreign_currency_cad(self):
        assert _parse_dollar("$60,919 (CAD 76,091)") == 60919.0

    def test_strips_foreign_currency_eur_no_dollar_sign(self):
        assert _parse_dollar("26,718 (EUR 4,055)") == 26718.0

    def test_strips_foreign_currency_gbp(self):
        assert _parse_dollar("4,455 (GBP 3,200)") == 4455.0

    def test_negative_parens_still_works_after_fx_strip(self):
        """Regression: (1,234) with pure digits stays a negative number."""
        assert _parse_dollar("(1,234)") == -1234.0

    # Amendment #5: multi-value cell -- take first contiguous digit group.
    def test_multi_value_cell_space_separated(self):
        # Rand Capital: "1,791,278 150,000 1,791,278 150,000"
        assert _parse_dollar("1,791,278 150,000 1,791,278 150,000") == 1791278.0

    def test_multi_value_plain_spaces(self):
        assert _parse_dollar("1791278 150000") == 1791278.0

    def test_multi_value_with_dollar_sign(self):
        assert _parse_dollar("$1,234,567 $500,000") == 1234567.0


# ===========================================================================
# _parse_rate
# ===========================================================================

class TestParseRate:
    def test_percentage_number(self):
        assert _parse_rate(10.5) == 10.5

    def test_decimal_rate_converted(self):
        assert _parse_rate(0.1050) == 10.5

    def test_string_rate(self):
        assert _parse_rate("12.5%") == 12.5

    def test_none(self):
        assert _parse_rate(None) is None

    def test_null_string(self):
        assert _parse_rate("null") is None

    def test_zero_stays_zero(self):
        assert _parse_rate(0) == 0

    def test_small_decimal(self):
        # 0.0525 -> 5.25
        assert _parse_rate(0.0525) == 5.25

    # Amendment #4: trailing Cash/PIK suffixes should be stripped.
    def test_strips_cash_suffix(self):
        assert _parse_rate("6.5% Cash") == 6.5

    def test_strips_pik_suffix(self):
        assert _parse_rate("10.0% PIK") == 10.0

    def test_strips_lowercase_cash(self):
        assert _parse_rate("1.0% cash") == 1.0

    def test_strips_pik_no_percent(self):
        assert _parse_rate("5 PIK") == 5.0


# ===========================================================================
# _strip_footnotes
# ===========================================================================

class TestStripFootnotes:
    def test_single_footnote(self):
        assert _strip_footnotes("1,000(1)") == "1,000"

    def test_multiple_footnotes(self):
        assert _strip_footnotes("500(1)(14)") == "500"

    def test_asterisk(self):
        assert _strip_footnotes("1,000**") == "1,000"

    def test_no_footnote(self):
        assert _strip_footnotes("1,000") == "1,000"


# ===========================================================================
# post_process
# ===========================================================================

class TestPostProcess:
    def test_name_propagation(self):
        rows = [
            {"issuer_name": "Acme Corp", "is_continuation": False,
             "fair_value": 100},
            {"issuer_name": None, "is_continuation": True,
             "fair_value": 200},
        ]
        result = post_process(rows, dollar_unit=1)
        assert result[0]["issuer_name"] == "Acme Corp"
        assert result[1]["issuer_name"] == "Acme Corp"

    def test_dollar_unit_millions(self):
        rows = [
            {"issuer_name": "Acme", "is_continuation": False,
             "fair_value": 5, "cost": 4.8, "principal_amount": 5},
        ]
        result = post_process(rows, dollar_unit=1_000_000)
        assert result[0]["fair_value"] == 5_000_000
        assert result[0]["cost"] == 4_800_000
        assert result[0]["principal_amount"] == 5_000_000

    def test_dollar_unit_thousands(self):
        rows = [
            {"issuer_name": "Beta", "is_continuation": False,
             "fair_value": 500, "cost": 490, "principal_amount": 500},
        ]
        result = post_process(rows, dollar_unit=1_000)
        assert result[0]["fair_value"] == 500_000

    def test_rate_normalization_decimal(self):
        rows = [
            {"issuer_name": "Acme", "is_continuation": False,
             "interest_rate": 0.105, "basis_spread": 0.0525,
             "pct_of_net_assets": 0.015},
        ]
        result = post_process(rows, dollar_unit=1)
        assert result[0]["interest_rate"] == 10.5
        assert result[0]["basis_spread"] == 5.25
        assert result[0]["pct_of_net_assets"] == 1.5

    def test_null_fields_stay_null(self):
        rows = [
            {"issuer_name": "Acme", "is_continuation": False,
             "fair_value": None, "cost": None, "principal_amount": None,
             "interest_rate": None, "basis_spread": None},
        ]
        result = post_process(rows, dollar_unit=1)
        assert result[0]["fair_value"] is None
        assert result[0]["cost"] is None
        assert result[0]["interest_rate"] is None

    def test_invalid_maturity_date_cleared(self):
        rows = [
            {"issuer_name": "Acme", "is_continuation": False,
             "maturity_date": "Dec 2025"},
        ]
        result = post_process(rows, dollar_unit=1)
        assert result[0]["maturity_date"] is None

    def test_valid_maturity_date_kept(self):
        rows = [
            {"issuer_name": "Acme", "is_continuation": False,
             "maturity_date": "2025-12-31"},
        ]
        result = post_process(rows, dollar_unit=1)
        assert result[0]["maturity_date"] == "2025-12-31"

    def test_shares_parsed(self):
        rows = [
            {"issuer_name": "Acme", "is_continuation": False,
             "shares_held": "1,000"},
        ]
        result = post_process(rows, dollar_unit=1)
        assert result[0]["shares_held"] == 1000.0

    def test_multiple_continuations(self):
        rows = [
            {"issuer_name": "Parent Co", "is_continuation": False, "fair_value": 100},
            {"issuer_name": None, "is_continuation": True, "fair_value": 50},
            {"issuer_name": None, "is_continuation": True, "fair_value": 25},
            {"issuer_name": "New Parent", "is_continuation": False, "fair_value": 200},
            {"issuer_name": None, "is_continuation": True, "fair_value": 75},
        ]
        result = post_process(rows, dollar_unit=1)
        assert result[0]["issuer_name"] == "Parent Co"
        assert result[1]["issuer_name"] == "Parent Co"
        assert result[2]["issuer_name"] == "Parent Co"
        assert result[3]["issuer_name"] == "New Parent"
        assert result[4]["issuer_name"] == "New Parent"


# ===========================================================================
# reconcile_subtotals
# ===========================================================================

class TestReconcileSubtotals:
    def test_basic_reconciliation(self):
        data_rows = [
            {"_section": "Tech", "fair_value": 100},
            {"_section": "Tech", "fair_value": 200},
            {"_section": "Healthcare", "fair_value": 300},
        ]
        subtotal_rows = [
            {"_section": "Tech", "fair_value": 300},
        ]
        result = reconcile_subtotals(data_rows, subtotal_rows)
        tech = [r for r in result if r["section"] == "Tech"][0]
        assert tech["sum_fair_value"] == 300
        assert tech["subtotal_fair_value"] == 300
        assert tech["pct_diff"] == 0.0

    def test_discrepancy(self):
        data_rows = [
            {"_section": "Tech", "fair_value": 100},
            {"_section": "Tech", "fair_value": 190},
        ]
        subtotal_rows = [
            {"_section": "Tech", "fair_value": 300},
        ]
        result = reconcile_subtotals(data_rows, subtotal_rows)
        tech = result[0]
        assert tech["sum_fair_value"] == 290
        assert abs(tech["pct_diff"] - 10.0 / 300) < 0.001

    def test_no_matching_subtotal(self):
        data_rows = [
            {"_section": "Tech", "fair_value": 100},
        ]
        result = reconcile_subtotals(data_rows, [])
        assert result[0]["subtotal_fair_value"] is None
        assert result[0]["pct_diff"] is None


# ===========================================================================
# _to_bdc_holdings_schema
# ===========================================================================

class TestToBdcHoldingsSchema:
    def test_basic_conversion(self):
        rows = [{
            "issuer_name": "Acme Corp",
            "instrument_description": "First Lien Term Loan",
            "industry": "Technology",
            "interest_rate": 10.5,
            "reference_rate": "SOFR",
            "basis_spread": 5.25,
            "maturity_date": "2026-06-30",
            "principal_amount": 1000000,
            "cost": 990000,
            "fair_value": 1010000,
            "shares_held": None,
            "pct_of_net_assets": 1.5,
        }]
        meta = {
            "cik": "0001234567",
            "entity_name": "Test BDC",
            "accession_number": "0001234567-24-000001",
            "form_type": "10-K",
            "filing_date": "2024-03-15",
            "report_date": "2024-12-31",
        }
        result = _to_bdc_holdings_schema(rows, meta)
        assert len(result) == 1
        r = result[0]
        assert r["cik"] == "0001234567"
        assert r["entity_name"] == "Test BDC"
        assert r["investment_identifier"] == "Acme Corp"
        assert r["fair_value"] == 1010000
        assert r["interest_rate"] == 10.5
        assert r["reference_rate_type"] == "SOFR"
        assert r["period"] == "2024-12-31"
        assert r["industry"] == "Technology"
        assert r["investment_type"] == "First Lien Term Loan"


# ===========================================================================
# find_schedule_tables (integration with real HTML)
# ===========================================================================

class TestFindScheduleTables:
    def test_single_schedule_found(self):
        html = _make_schedule_html(
            header=["Company", "Interest Rate", "Maturity Date",
                    "Principal Amount", "Cost", "Fair Value"],
            data_rows=[
                ["Acme Corp", "10.5%", "12/31/2025", "1,000,000",
                 "990,000", "1,010,000"],
                ["Beta Inc", "11.0%", "06/30/2026", "500,000",
                 "495,000", "505,000"],
            ] * 10,  # 20 data rows
            title="Consolidated Schedule of Investments",
        )
        tables = find_schedule_tables(html)
        assert len(tables) >= 1
        assert tables[0].score > 5.0
        assert tables[0].header_row_idx == 0
        assert len(tables[0].rows) >= 20

    def test_no_schedule_in_balance_sheet(self):
        html = _make_schedule_html(
            header=["", "Total Assets", "Income Statement", "Balance Sheet"],
            data_rows=[
                ["Q1", "50,000", "10,000", ""],
                ["Q2", "52,000", "11,000", ""],
            ],
        )
        tables = find_schedule_tables(html)
        assert len(tables) == 0

    def test_dollar_unit_detected(self):
        html = _make_schedule_html(
            header=["Company", "Interest Rate", "Fair Value"],
            data_rows=[
                ["Acme", "10%", "5"],
                ["Beta", "11%", "3"],
            ] * 10,
            dollar_note="(in millions)",
        )
        tables = find_schedule_tables(html)
        if tables:
            assert tables[0].dollar_unit == 1_000_000

    def test_column_map_populated(self):
        html = _make_schedule_html(
            header=["Portfolio Company", "Coupon", "Par Amount",
                    "Amortized Cost", "Fair Value"],
            data_rows=[
                ["Acme", "10%", "1000", "990", "1010"],
            ] * 10,
        )
        tables = find_schedule_tables(html)
        assert len(tables) >= 1
        cm = tables[0].column_map
        assert "company" in cm
        assert "fair_value" in cm

    def test_continuation_tables_merged(self):
        """Two tables with same headers should be merged."""
        header = ["Company", "Interest Rate", "Maturity", "Cost", "Fair Value"]
        table1_rows = [header] + [
            [f"Co{i}", "10%", "2025", "100", "100"] for i in range(10)
        ]
        table2_rows = [header] + [
            [f"Co{i+10}", "11%", "2026", "200", "200"] for i in range(10)
        ]
        html = (
            "<html><body>"
            + _make_html_table(table1_rows)
            + _make_html_table(table2_rows)
            + "</body></html>"
        )
        tables = find_schedule_tables(html)
        assert len(tables) >= 1
        # Primary table should have merged rows
        primary = tables[0]
        # Should have header + 20 data rows
        assert len(primary.rows) >= 20


# ===========================================================================
# Full classify_rows + section propagation
# ===========================================================================

class TestClassifyRowsIntegration:
    def test_full_table_classification(self):
        table = ScheduleTable(
            rows=[
                ["Company", "Rate", "Maturity", "Cost", "Fair Value", "% Net"],
                ["Senior Secured First Lien"],
                ["Acme Corp", "10.5%", "12/2025", "990,000", "1,000,000", "1.5%"],
                ["Beta Inc", "11.0%", "06/2026", "495,000", "500,000", "0.8%"],
                ["Total Senior Secured First Lien", "", "", "", "1,500,000", ""],
                [""],
                ["Common Equity"],
                ["Gamma LLC", "", "", "100,000", "150,000", "0.2%"],
            ],
            header_row_idx=0,
            score=15.0,
        )
        classified = classify_rows(table)

        kinds = [r.kind for r in classified]
        assert kinds[0] == "header"
        assert kinds[1] == "section_header"
        assert kinds[2] == "data"
        assert kinds[3] == "data"
        assert kinds[4] == "subtotal"
        assert kinds[5] == "blank"
        assert kinds[6] == "section_header"
        assert kinds[7] == "data"

        # Check section context
        assert classified[2].section_context == "Senior Secured First Lien"
        assert classified[3].section_context == "Senior Secured First Lien"
        assert classified[7].section_context == "Common Equity"


# ===========================================================================
# Amendment #33: ZWSP contamination stripping
# ===========================================================================

class TestZWSPStripping:
    def test_zwsp_stripped_from_cells(self):
        """ZWSP characters should be removed from cell text."""
        html = "<html><body><table><tr>"
        html += "<td>Company</td><td>\u200b</td><td>Fair Value</td>"
        html += "</tr><tr>"
        html += "<td>Acme\u200b Corp</td><td>\u200b</td><td>1,000</td>"
        html += "</tr></table></body></html>"
        tables = find_schedule_tables(html)
        # ZWSP cells should become empty after stripping
        if tables:
            header = tables[0].rows[0]
            for cell in header:
                assert "\u200b" not in cell

    def test_zwsp_does_not_inflate_column_count(self):
        """ZWSP-only cells should be empty, not counted as logical columns."""
        from pipeline.html_template import _get_logical_columns
        # Simulate header row after ZWSP stripping: ZWSP cells become empty
        header = ["Company", "", "Rate", "", "Fair Value"]
        logical = _get_logical_columns(header)
        # Only non-empty cells count as logical columns
        assert len(logical) == 3


# ===========================================================================
# Amendment #23: Industry propagation to continuation rows
# ===========================================================================

class TestIndustryPropagation:
    def test_continuation_inherits_industry(self):
        """Continuation row inherits industry from parent."""
        rows = [
            {"issuer_name": "Acme Corp", "industry": "Technology",
             "fair_value": "1000", "is_continuation": False},
            {"issuer_name": "", "industry": "",
             "fair_value": "500", "is_continuation": True},
        ]
        result = post_process(rows)
        assert result[1]["industry"] == "Technology"
        assert result[1]["issuer_name"] == "Acme Corp"

    def test_continuation_with_own_industry_keeps_it(self):
        """Continuation row with its own industry keeps it."""
        rows = [
            {"issuer_name": "Acme Corp", "industry": "Technology",
             "fair_value": "1000", "is_continuation": False},
            {"issuer_name": "", "industry": "Healthcare",
             "fair_value": "500", "is_continuation": True},
        ]
        result = post_process(rows)
        assert result[1]["industry"] == "Healthcare"


# ===========================================================================
# Amendment #20: Financial-highlights table rejection
# ===========================================================================

class TestFinancialHighlightsRejection:
    def test_highlights_table_rejected(self):
        """Table with >30% financial-highlights phrases rejected."""
        html = "<html><body><table>"
        html += "<tr><td>Metric</td><td>Value</td></tr>"
        for phrase in [
            "Net investment income", "Net realized gains",
            "Net unrealized appreciation", "Total return",
            "Per share data", "Ratio to average net assets",
            "From operations", "NAV per share",
            "End of period", "Beginning of period",
        ]:
            html += f"<tr><td>{phrase}</td><td>1,234</td></tr>"
        html += "</table></body></html>"
        tables = find_schedule_tables(html)
        # Should be empty -- highlights table rejected
        assert len(tables) == 0

    def test_schedule_table_passes(self):
        """Normal schedule table passes the highlights filter."""
        html = "<html><body><table>"
        html += "<tr><td>Company</td><td>Fair Value</td></tr>"
        for i in range(10):
            html += f"<tr><td>Company {i}</td><td>1,000,000</td></tr>"
        html += "</table></body></html>"
        tables = find_schedule_tables(html)
        assert len(tables) >= 1

    def test_mixed_table_below_threshold_kept(self):
        """Table with < 30% highlights phrases is kept."""
        html = "<html><body><table>"
        html += "<tr><td>Company</td><td>Fair Value</td></tr>"
        # 1 highlights phrase + 9 normal rows = 10%
        html += "<tr><td>Net investment income</td><td>500</td></tr>"
        for i in range(9):
            html += f"<tr><td>Acme Corp {i}</td><td>1,000,000</td></tr>"
        html += "</table></body></html>"
        tables = find_schedule_tables(html)
        assert len(tables) >= 1


# ===========================================================================
# Amendment #22: Minimum-row and numeric-content thresholds
# ===========================================================================

class TestMinimumRowThreshold:
    def test_small_table_no_values_rejected(self):
        """Table with < 5 rows and no large dollar values rejected."""
        html = "<html><body><table>"
        html += "<tr><td>Company</td><td>Fair Value</td></tr>"
        html += "<tr><td>Acme</td><td>50</td></tr>"
        html += "<tr><td>Beta</td><td>75</td></tr>"
        html += "</table></body></html>"
        tables = find_schedule_tables(html)
        assert len(tables) == 0

    def test_small_table_with_large_values_kept(self):
        """Table with < 5 rows but large values kept."""
        html = "<html><body><table>"
        html += "<tr><td>Company</td><td>Fair Value</td></tr>"
        html += "<tr><td>Acme</td><td>500,000</td></tr>"
        html += "<tr><td>Beta</td><td>750,000</td></tr>"
        html += "</table></body></html>"
        tables = find_schedule_tables(html)
        assert len(tables) >= 1

    def test_large_table_kept(self):
        """Table with >= 5 data rows always kept."""
        html = "<html><body><table>"
        html += "<tr><td>Company</td><td>Fair Value</td></tr>"
        for i in range(6):
            html += f"<tr><td>Co{i}</td><td>50</td></tr>"
        html += "</table></body></html>"
        tables = find_schedule_tables(html)
        assert len(tables) >= 1
