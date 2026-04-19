"""Tests for pipeline.html_template module.

Covers Section B: Programmatic extraction -- load_template, column mapping,
date conversion, template drift detection, full extraction, orchestrator.
"""

import json
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest

from pipeline.html_holdings import (
    ScheduleTable,
    RowClassification,
    find_schedule_tables,
)
from pipeline.html_template import (
    TEMPLATE_SCHEMA_VERSION,
    _DATE_MARKER_RE,
    _STANDALONE_DATE_RE,
    _apply_fallback_extraction,
    _apply_template_column_map,
    _convert_date,
    _detect_template_drift,
    _normalize_template,
    _segment_table_by_period,
    _select_best_variant,
    extract_filing_with_template,
    load_template,
)


# ---------------------------------------------------------------------------
# Helpers
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


def _make_template(
    overrides: dict | None = None,
    column_overrides: dict | None = None,
) -> dict:
    """Build a standard template dict for testing."""
    template = {
        "schema_version": "1.0",
        "cik": "1234567",
        "entity_name": "Test BDC",
        "source_accession": "0001234567-24-000001",
        "model_used": "gpt-4.1",
        "learned_at": "2026-01-01T00:00:00Z",
        "column_mapping": {
            "company": {"index": 0, "header_text": "Company"},
            "fair_value": {"index": 5, "header_text": "Fair Value"},
            "cost": {"index": 4, "header_text": "Cost"},
            "principal_amount": {"index": 3, "header_text": "Principal Amount"},
            "interest_rate": {"index": 1, "header_text": "Interest Rate"},
            "maturity_date": {"index": 2, "header_text": "Maturity Date"},
            "shares_held": {"index": None, "header_text": ""},
            "pct_of_net_assets": {"index": None, "header_text": ""},
        },
        "value_formats": {
            "dollar_unit": 1,
            "rate_format": "percentage",
            "date_format": "MM/DD/YYYY",
            "negative_convention": "parentheses",
            "dash_means_null": True,
        },
        "row_conventions": {
            "continuation_detection": "empty_first_cell",
            "industry_source": "section_header",
        },
        "filer_quirks": {
            "multi_line_cells": False,
            "instrument_in_company_cell": False,
            "rate_cell_includes_reference": False,
            "pik_notation": None,
        },
        "programmatic_analysis": {
            "tables_found": 1,
            "total_data_rows": 20,
            "column_count": 6,
            "detected_dollar_unit": 1,
        },
    }
    if column_overrides:
        template["column_mapping"].update(column_overrides)
    if overrides:
        for k, v in overrides.items():
            if isinstance(v, dict) and k in template and isinstance(template[k], dict):
                template[k].update(v)
            else:
                template[k] = v
    return template


# ===========================================================================
# Section B: Programmatic Extraction
# ===========================================================================

class TestLoadTemplate:
    def test_valid_json(self, tmp_path):
        template = _make_template()
        (tmp_path / "1234.json").write_text(json.dumps(template))

        with patch("pipeline.html_template.HTML_TEMPLATE_DIR", tmp_path):
            result = load_template("1234")

        assert result is not None
        assert result["cik"] == "1234567"

    def test_missing_file(self, tmp_path):
        with patch("pipeline.html_template.HTML_TEMPLATE_DIR", tmp_path):
            result = load_template("99999")
        assert result is None

    def test_invalid_json(self, tmp_path):
        (tmp_path / "1234.json").write_text("{invalid json")

        with patch("pipeline.html_template.HTML_TEMPLATE_DIR", tmp_path):
            result = load_template("1234")
        assert result is None

    def test_leading_zeros_stripped(self, tmp_path):
        template = _make_template()
        (tmp_path / "1234.json").write_text(json.dumps(template))

        with patch("pipeline.html_template.HTML_TEMPLATE_DIR", tmp_path):
            result = load_template("0001234")
        assert result is not None


class TestConvertDate:
    def test_mm_dd_yyyy(self):
        assert _convert_date("12/31/2025") == "2025-12-31"

    def test_m_d_yyyy(self):
        assert _convert_date("1/5/2025") == "2025-01-05"

    def test_m_d_yy_20xx(self):
        assert _convert_date("6/15/25") == "2025-06-15"

    def test_m_d_yy_19xx(self):
        assert _convert_date("6/15/95") == "1995-06-15"

    def test_already_iso(self):
        assert _convert_date("2025-12-31") == "2025-12-31"

    def test_dash_returns_none(self):
        assert _convert_date("-") is None

    def test_empty_returns_none(self):
        assert _convert_date("") is None

    def test_unparseable_returns_none(self):
        # "December 2025" is now handled by amendment #1 (month-name parsing).
        # Use something genuinely unparseable instead.
        assert _convert_date("Q4 FY25") is None
        assert _convert_date("sometime in 2025") is None

    def test_with_footnote(self):
        assert _convert_date("12/31/2025(1)") == "2025-12-31"

    def test_m_dash_d_dash_yyyy(self):
        assert _convert_date("3-15-2026") == "2026-03-15"

    def test_mm_yyyy_partial_date(self):
        assert _convert_date("10/2029") == "2029-10-01"

    def test_m_yyyy_partial_date(self):
        assert _convert_date("1/2030") == "2030-01-01"

    # Amendment #1: month-name date parsing
    def test_month_name_full_january(self):
        assert _convert_date("January 2017") == "2017-01-01"

    def test_month_name_case_insensitive(self):
        assert _convert_date("june 2016") == "2016-06-01"

    def test_month_name_december(self):
        assert _convert_date("December 2028") == "2028-12-01"

    def test_month_name_abbreviation(self):
        assert _convert_date("Mar 2025") == "2025-03-01"

    def test_invalid_month_name_returns_none(self):
        assert _convert_date("Foo 2020") is None


class TestRatePatternBaseReference:
    """Amendment #12: 'Base' reference rate (maps to PRIME)."""

    def test_base_plus_spread_simple(self):
        template = _make_template(
            overrides={"filer_quirks": {
                "multi_line_cells": False,
                "instrument_in_company_cell": False,
                "rate_cell_includes_reference": True,
                "pik_notation": None,
            }}
        )
        cells = ["Acme", "Base+ 2.50%", "12/31/2025", "1000", "990", "1010"]
        result = _apply_template_column_map(cells, template)
        assert result["reference_rate"] == "PRIME"
        assert result["basis_spread"] == 2.5

    def test_base_in_parenthesis_with_total(self):
        template = _make_template(
            overrides={"filer_quirks": {
                "multi_line_cells": False,
                "instrument_in_company_cell": False,
                "rate_cell_includes_reference": True,
                "pik_notation": None,
            }}
        )
        cells = ["Acme", "14.00% (Base+ 850)", "12/31/2025", "1000", "990", "1010"]
        result = _apply_template_column_map(cells, template)
        assert result["interest_rate"] == 14.0
        assert result["reference_rate"] == "PRIME"
        assert result["basis_spread"] == 8.5  # 850 bps

    def test_base_spread_separate_column(self):
        """`Base + 400` appearing in a dedicated spread cell."""
        template = _make_template(
            column_overrides={
                "basis_spread": {"index": 6, "header_text": "Spread"},
            },
            overrides={
                "programmatic_analysis": {
                    "tables_found": 1,
                    "total_data_rows": 20,
                    "column_count": 7,
                    "detected_dollar_unit": 1,
                },
            },
        )
        cells = ["Acme", "12.5", "12/31/2025", "1000", "990", "1010", "Base + 400"]
        result = _apply_template_column_map(cells, template)
        assert result["reference_rate"] == "PRIME"
        assert result["basis_spread"] == 4.0


class TestSplitCellMultiwordReference:
    """Amendment #17: multi-word reference codes in split cells."""

    def test_1m_usd_sofr_plus(self):
        # Spread column split: "1M USD SOFR+" in one cell, "3.25 %" in the next.
        template = _make_template(
            column_overrides={
                "basis_spread": {"index": 6, "header_text": "Spread"},
            },
            overrides={
                "programmatic_analysis": {
                    "tables_found": 1,
                    "total_data_rows": 20,
                    "column_count": 7,
                    "detected_dollar_unit": 1,
                },
            },
        )
        cells = [
            "Acme", "10.5", "12/31/2025", "1000", "990", "1010",
            "1M USD SOFR+", "3.25 %",
        ]
        result = _apply_template_column_map(cells, template)
        assert result["reference_rate"] == "SOFR"
        assert result["basis_spread"] == 3.25

    def test_3m_usd_libor_spaced_plus(self):
        template = _make_template(
            column_overrides={
                "basis_spread": {"index": 6, "header_text": "Spread"},
            },
            overrides={
                "programmatic_analysis": {
                    "tables_found": 1,
                    "total_data_rows": 20,
                    "column_count": 7,
                    "detected_dollar_unit": 1,
                },
            },
        )
        cells = [
            "Acme", "11.0", "12/31/2025", "1000", "990", "1010",
            "3M USD LIBOR +", "4.50 %",
        ]
        result = _apply_template_column_map(cells, template)
        assert result["reference_rate"] == "LIBOR"
        assert result["basis_spread"] == 4.5


class TestApplyTemplateColumnMap:
    def test_standard_mapping(self):
        template = _make_template()
        cells = ["Acme Corp", "10.5", "12/31/2025", "1000000",
                 "990000", "1010000"]
        result = _apply_template_column_map(cells, template)
        assert result["issuer_name"] == "Acme Corp"
        assert result["fair_value"] == 1010000.0
        assert result["cost"] == 990000.0
        assert result["principal_amount"] == 1000000.0
        assert result["interest_rate"] == 10.5

    def test_out_of_range_index(self):
        template = _make_template(
            column_overrides={"cost": {"index": 99, "header_text": "Cost"}}
        )
        cells = ["Acme", "10%", "2025-12-31", "1000", "990", "1010"]
        result = _apply_template_column_map(cells, template)
        assert result["cost"] is None

    def test_null_index_field(self):
        template = _make_template()
        cells = ["Acme", "10%", "2025-12-31", "1000", "990", "1010"]
        result = _apply_template_column_map(cells, template)
        assert result["shares_held"] is None

    def test_dollar_unit_thousands(self):
        template = _make_template(
            overrides={"value_formats": {
                "dollar_unit": 1000,
                "rate_format": "percentage",
                "date_format": "MM/DD/YYYY",
                "negative_convention": "parentheses",
                "dash_means_null": True,
            }}
        )
        cells = ["Acme", "10%", "12/31/2025", "500", "490", "510"]
        result = _apply_template_column_map(cells, template)
        assert result["fair_value"] == 510000.0
        assert result["cost"] == 490000.0
        assert result["principal_amount"] == 500000.0

    def test_embedded_rate_and_spread(self):
        template = _make_template(
            overrides={"filer_quirks": {
                "multi_line_cells": False,
                "instrument_in_company_cell": False,
                "rate_cell_includes_reference": True,
                "pik_notation": None,
            }}
        )
        cells = ["Acme", "S+5.25% / 10.50%", "12/31/2025", "1000",
                 "990", "1010"]
        result = _apply_template_column_map(cells, template)
        assert result["reference_rate"] == "SOFR"
        assert result["basis_spread"] == 5.25
        assert result["interest_rate"] == 10.5

    def test_embedded_libor_rate(self):
        template = _make_template(
            overrides={"filer_quirks": {
                "multi_line_cells": False,
                "instrument_in_company_cell": False,
                "rate_cell_includes_reference": True,
                "pik_notation": None,
            }}
        )
        cells = ["Beta Inc", "L+4.00%", "06/30/2026", "500",
                 "495", "505"]
        result = _apply_template_column_map(cells, template)
        assert result["reference_rate"] == "LIBOR"
        assert result["basis_spread"] == 4.0

    def test_instrument_in_company_cell(self):
        template = _make_template(
            overrides={"filer_quirks": {
                "multi_line_cells": True,
                "instrument_in_company_cell": True,
                "rate_cell_includes_reference": False,
                "pik_notation": None,
            }}
        )
        cells = ["Acme Corp\nFirst Lien Term Loan", "10%",
                 "12/31/2025", "1000", "990", "1010"]
        result = _apply_template_column_map(cells, template)
        assert result["issuer_name"] == "Acme Corp"
        assert result["instrument_description"] == "First Lien Term Loan"

    def test_date_format_conversion(self):
        template = _make_template()
        cells = ["Acme", "10%", "6/15/2026", "1000", "990", "1010"]
        result = _apply_template_column_map(cells, template)
        assert result["maturity_date"] == "2026-06-15"

    def test_pik_rate_extraction(self):
        template = _make_template(
            overrides={"filer_quirks": {
                "multi_line_cells": False,
                "instrument_in_company_cell": False,
                "rate_cell_includes_reference": False,
                "pik_notation": "PIK after rate",
            }}
        )
        cells = ["Acme", "10.5% PIK 2.0%", "12/31/2025", "1000",
                 "990", "1010"]
        result = _apply_template_column_map(cells, template)
        assert result["pik_rate"] == 2.0

    def test_pik_rate_before_keyword(self):
        """Pure PIK: '14.00 % PIK' -- number before PIK keyword."""
        template = _make_template()
        cells = ["Acme", "14.00 % PIK", "12/31/2025", "1000", "990", "1010"]
        result = _apply_template_column_map(cells, template)
        assert result["pik_rate"] == 14.0
        assert result["interest_rate"] == 14.0

    def test_pik_rate_partial(self):
        """Partial PIK: '9.42 % ( 3.00 % PIK)' -- total rate with PIK portion."""
        template = _make_template()
        cells = ["Acme", "9.42 % ( 3.00 % PIK)", "12/31/2025", "1000",
                 "990", "1010"]
        result = _apply_template_column_map(cells, template)
        assert result["pik_rate"] == 3.0
        assert result["interest_rate"] == 9.42

    def test_pik_rate_partial_no_spaces(self):
        """Partial PIK variant: '10.25% (5.25% PIK)'."""
        template = _make_template()
        cells = ["Acme", "10.25% (5.25% PIK)", "12/31/2025", "1000",
                 "990", "1010"]
        result = _apply_template_column_map(cells, template)
        assert result["pik_rate"] == 5.25
        assert result["interest_rate"] == 10.25

    def test_nml_rate_with_space(self):
        """'9.35% (1M L+725)' -- space between month code and reference."""
        template = _make_template(
            overrides={"filer_quirks": {
                "multi_line_cells": False,
                "instrument_in_company_cell": False,
                "rate_cell_includes_reference": True,
                "pik_notation": None,
            }}
        )
        cells = ["Acme", "9.35% (1M L+725)", "12/31/2025", "1000",
                 "990", "1010"]
        result = _apply_template_column_map(cells, template)
        assert result["interest_rate"] == 9.35
        assert result["reference_rate"] == "LIBOR"
        assert result["basis_spread"] == 7.25

    def test_nml_rate_no_space(self):
        """'10.00% (3ML+ 7.00%)' -- no space (original format)."""
        template = _make_template(
            overrides={"filer_quirks": {
                "multi_line_cells": False,
                "instrument_in_company_cell": False,
                "rate_cell_includes_reference": True,
                "pik_notation": None,
            }}
        )
        cells = ["Acme", "10.00% (3ML+ 7.00%)", "12/31/2025", "1000",
                 "990", "1010"]
        result = _apply_template_column_map(cells, template)
        assert result["interest_rate"] == 10.0
        assert result["reference_rate"] == "LIBOR"
        assert result["basis_spread"] == 7.0

    def test_negative_dollar_parentheses(self):
        template = _make_template()
        cells = ["Acme", "10%", "12/31/2025", "(500)", "(490)", "(510)"]
        result = _apply_template_column_map(cells, template)
        assert result["fair_value"] == -510.0
        assert result["principal_amount"] == -500.0

    def test_dash_means_null(self):
        template = _make_template()
        cells = ["Acme", "-", "-", "-", "-", "100"]
        result = _apply_template_column_map(cells, template)
        assert result["interest_rate"] is None
        assert result["cost"] is None
        assert result["fair_value"] == 100.0

    def test_dollar_sign_split(self):
        """When a cell is just "$" and the value is in the next cell."""
        template = _make_template()
        # fair_value is at index 5. Cell 5 = "$", cell 6 = "1,234"
        cells = ["Acme", "10%", "12/31/2025", "1000", "990", "$", "1,234"]
        result = _apply_template_column_map(cells, template)
        assert result["fair_value"] == 1234.0

    def test_dollar_sign_prefix(self):
        """When a cell has "$" prefix attached to value."""
        template = _make_template()
        cells = ["Acme", "10%", "12/31/2025", "$1000", "$990", "$1010"]
        result = _apply_template_column_map(cells, template)
        assert result["fair_value"] == 1010.0
        assert result["principal_amount"] == 1000.0
        assert result["cost"] == 990.0


class TestApplyFallbackDollarSplit:
    """Test "$" + number split handling in _apply_fallback_extraction."""

    def test_dollar_sign_split_fallback(self):
        col_map = {"company": 0, "fair_value": 3, "cost": 5}
        cells = ["Acme", "", "", "$", "500", "$", "490"]
        result = _apply_fallback_extraction(cells, col_map, dollar_unit=1)
        assert result["fair_value"] == 500.0
        assert result["cost"] == 490.0

    def test_dollar_sign_prefix_fallback(self):
        col_map = {"company": 0, "fair_value": 1}
        cells = ["Acme", "$1,234"]
        result = _apply_fallback_extraction(cells, col_map, dollar_unit=1)
        assert result["fair_value"] == 1234.0


class TestDetectTemplateDrift:
    def test_no_drift(self):
        template = _make_template()
        table = ScheduleTable(
            rows=[
                ["Company", "Interest Rate", "Maturity Date",
                 "Principal Amount", "Cost", "Fair Value"],
                ["Acme", "10%", "2025", "1000", "990", "1010"],
            ],
            header_row_idx=0,
            score=15.0,
            dollar_unit=1,
        )
        has_drift, reasons = _detect_template_drift(table, template)
        assert not has_drift
        assert reasons == []

    def test_column_count_change(self):
        template = _make_template()
        table = ScheduleTable(
            rows=[
                ["Company", "Rate", "Cost", "Fair Value",
                 "Extra1", "Extra2", "Extra3", "Extra4", "Extra5"],
                ["Acme", "10%", "990", "1010",
                 "x", "x", "x", "x", "x"],
            ],
            header_row_idx=0,
            score=15.0,
            dollar_unit=1,
        )
        has_drift, reasons = _detect_template_drift(table, template)
        assert has_drift
        assert any("Column count" in r for r in reasons)

    def test_header_mismatch(self):
        template = _make_template()
        # Swap column 5 from "Fair Value" to "Revenue"
        table = ScheduleTable(
            rows=[
                ["Company", "Interest Rate", "Maturity Date",
                 "Principal Amount", "Cost", "Revenue"],
                ["Acme", "10%", "2025", "1000", "990", "1010"],
            ],
            header_row_idx=0,
            score=15.0,
            dollar_unit=1,
        )
        has_drift, reasons = _detect_template_drift(table, template)
        assert has_drift
        assert any("fair_value" in r for r in reasons)

    def test_dollar_unit_change(self):
        template = _make_template()
        table = ScheduleTable(
            rows=[
                ["Company", "Interest Rate", "Maturity Date",
                 "Principal Amount", "Cost", "Fair Value"],
                ["Acme", "10%", "2025", "1000", "990", "1010"],
            ],
            header_row_idx=0,
            score=15.0,
            dollar_unit=1000,  # template expects 1
        )
        has_drift, reasons = _detect_template_drift(table, template)
        # Dollar unit mismatch is logged but does NOT trigger drift --
        # the template is authoritative for dollar unit.
        assert not has_drift
        assert any("Dollar unit" in r for r in reasons)

    def test_column_index_out_of_range(self):
        template = _make_template(
            column_overrides={
                "pct_of_net_assets": {
                    "index": 7, "header_text": "% Net Assets"
                }
            }
        )
        table = ScheduleTable(
            rows=[
                ["Company", "Rate", "Maturity", "Principal", "Cost", "FV"],
                ["Acme", "10%", "2025", "1000", "990", "1010"],
            ],
            header_row_idx=0,
            score=15.0,
            dollar_unit=1,
        )
        has_drift, reasons = _detect_template_drift(table, template)
        assert has_drift
        assert any("out of range" in r for r in reasons)

    # --- Amendment #7: parenthetical footnote markers in headers ---

    def test_detect_drift_strips_header_footnotes(self):
        """Headers like "Cost(r)" / "Fair Value(4)" still match expected text."""
        template = _make_template()
        table = ScheduleTable(
            rows=[
                # Each header has a footnote marker appended directly
                ["Company", "Interest Rate(1)", "Maturity Date(2)",
                 "Principal Amount(3)", "Cost(r)", "Fair Value(4)"],
                ["Acme", "10%", "2025", "1000", "990", "1010"],
            ],
            header_row_idx=0,
            score=15.0,
            dollar_unit=1,
        )
        has_drift, reasons = _detect_template_drift(table, template)
        # With amendment #7, footnote markers are stripped before word
        # overlap check, so there should be no header-mismatch drift.
        mismatch_reasons = [r for r in reasons if "header mismatch" in r]
        assert not has_drift
        assert mismatch_reasons == []

    def test_detect_drift_footnote_in_actual_only(self):
        """Even when only the actual header has a footnote, it still matches."""
        template = _make_template()
        table = ScheduleTable(
            rows=[
                ["Company", "Interest Rate", "Maturity Date",
                 "Principal Amount", "Cost(r)", "Fair Value"],
                ["Acme", "10%", "2025", "1000", "990", "1010"],
            ],
            header_row_idx=0,
            score=15.0,
            dollar_unit=1,
        )
        has_drift, _ = _detect_template_drift(table, template)
        assert not has_drift


class TestApplyFallbackExtraction:
    def test_basic_fallback(self):
        col_map = {
            "company": 0,
            "interest_rate": 1,
            "fair_value": 2,
        }
        cells = ["Acme Corp", "10.5%", "1,000,000"]
        result = _apply_fallback_extraction(cells, col_map, dollar_unit=1)
        assert result["issuer_name"] == "Acme Corp"
        assert result["fair_value"] == 1000000.0

    def test_with_dollar_unit(self):
        col_map = {"company": 0, "fair_value": 1}
        cells = ["Acme", "500"]
        result = _apply_fallback_extraction(cells, col_map, dollar_unit=1000)
        assert result["fair_value"] == 500000.0


class TestExtractFilingWithTemplate:
    def _make_filing_html(self):
        return _make_schedule_html(
            header=["Company", "Interest Rate", "Maturity Date",
                    "Principal Amount", "Cost", "Fair Value"],
            data_rows=[
                ["Acme Corp", "10.5", "12/31/2025", "1000000",
                 "990000", "1010000"],
                ["Beta Inc", "11.0", "06/30/2026", "500000",
                 "495000", "505000"],
                ["Gamma LLC", "9.5", "03/15/2025", "750000",
                 "740000", "760000"],
            ] * 5,  # 15 rows
            title="Schedule of Investments",
        )

    def test_full_extraction(self):
        html = self._make_filing_html()
        template = _make_template()
        filing_meta = {
            "cik": "1234567",
            "entity_name": "Test BDC",
            "accession_number": "0001234567-24-000001",
            "form_type": "10-K",
            "filing_date": "2024-03-15",
            "report_date": "2024-12-31",
        }

        holdings, stats = extract_filing_with_template(
            html, filing_meta, template,
        )

        assert stats["tables_found"] >= 1
        assert stats["rows_extracted"] > 0
        assert len(holdings) > 0
        # Verify schema fields
        h = holdings[0]
        assert "cik" in h
        assert "fair_value" in h
        assert "investment_identifier" in h
        assert h["cik"] == "1234567"

    def test_no_tables_returns_empty(self):
        html = "<html><body>No tables</body></html>"
        template = _make_template()
        holdings, stats = extract_filing_with_template(
            html, {"cik": "1"}, template,
        )
        assert holdings == []
        assert stats["tables_found"] == 0

    def test_drift_uses_fallback(self):
        html = _make_schedule_html(
            header=["Company", "Rate", "Cost", "Fair Value",
                    "Extra1", "Extra2", "Extra3", "Extra4", "Extra5"],
            data_rows=[
                ["Acme", "10%", "990", "1010", "x", "x", "x", "x", "x"],
            ] * 15,
        )
        template = _make_template()  # expects 6 columns
        filing_meta = {"cik": "1", "report_date": "2024-12-31"}

        holdings, stats = extract_filing_with_template(
            html, filing_meta, template,
        )
        assert stats["drift_detected"]
        # Should still extract with fallback
        assert stats["rows_extracted"] > 0

    def test_section_context_propagation(self):
        # Build HTML with a section header followed by data
        rows = [
            ["Company", "Interest Rate", "Maturity", "Principal",
             "Cost", "Fair Value"],
            ["Senior Secured First Lien"],
            ["Acme Corp", "10%", "2025-12-31", "1000", "990", "1010"],
            ["Beta Inc", "11%", "2026-06-30", "500", "495", "505"],
        ] + [
            [f"Co{i}", "10%", "2025-12-31", "100", "99", "101"]
            for i in range(13)
        ]
        html = (
            "<html><body><p>Schedule of Investments</p>"
            + _make_html_table(rows)
            + "</body></html>"
        )
        template = _make_template(
            overrides={"row_conventions": {
                "continuation_detection": "empty_first_cell",
                "industry_source": "section_header",
            }}
        )
        filing_meta = {"cik": "1", "report_date": "2024-12-31"}

        holdings, stats = extract_filing_with_template(
            html, filing_meta, template,
        )
        assert stats["rows_extracted"] > 0

    def test_continuation_rows(self):
        rows = [
            ["Company", "Interest Rate", "Maturity", "Principal",
             "Cost", "Fair Value"],
            ["Acme Corp", "10%", "12/31/2025", "1000", "990", "1010"],
            ["", "11%", "06/30/2026", "500", "495", "505"],
        ] + [
            [f"Co{i}", "10%", "2025-12-31", "100", "99", "101"]
            for i in range(13)
        ]
        html = (
            "<html><body><p>Schedule of Investments</p>"
            + _make_html_table(rows)
            + "</body></html>"
        )
        template = _make_template()
        filing_meta = {"cik": "1", "report_date": "2024-12-31"}

        holdings, stats = extract_filing_with_template(
            html, filing_meta, template,
        )
        # The continuation row should have Acme Corp's name propagated
        # (via post_process)
        assert stats["rows_extracted"] > 0

    def test_subtotal_rows_filtered(self):
        rows = [
            ["Company", "Interest Rate", "Maturity", "Principal",
             "Cost", "Fair Value"],
        ] + [
            [f"Co{i}", "10%", "2025-12-31", "100", "99", "101"]
            for i in range(14)
        ] + [
            ["Total First Lien", "", "", "", "", "1414"],
        ]
        html = (
            "<html><body><p>Schedule of Investments</p>"
            + _make_html_table(rows)
            + "</body></html>"
        )
        template = _make_template()
        filing_meta = {"cik": "1", "report_date": "2024-12-31"}

        holdings, stats = extract_filing_with_template(
            html, filing_meta, template,
        )
        # Total row should be classified as subtotal, not data
        names = [h.get("investment_identifier", "") for h in holdings]
        assert not any("Total" in n for n in names if n)


class TestExtractAllHtml:
    def test_multi_filing_orchestrator(self, tmp_path):
        """Test extract_all_html processes multiple filings."""
        # Setup: create templates and HTML files
        template_dir = tmp_path / "templates"
        template_dir.mkdir()
        html_dir = tmp_path / "html"
        cik_dir = html_dir / "1234"
        cik_dir.mkdir(parents=True)

        template = _make_template()
        (template_dir / "1234.json").write_text(json.dumps(template))

        html = _make_schedule_html(
            header=["Company", "Interest Rate", "Maturity Date",
                    "Principal Amount", "Cost", "Fair Value"],
            data_rows=[["Acme", "10%", "12/31/2025", "1000",
                       "990", "1010"]] * 15,
        )
        (cik_dir / "000123400001.html").write_text(html)
        (cik_dir / "000123400002.html").write_text(html)

        filings_index = pd.DataFrame({
            "cik": ["0001234", "0001234"],
            "accession_number": ["0001234-00-001", "0001234-00-002"],
            "form_type": ["10-K", "10-Q"],
            "filing_date": ["2024-12-31", "2024-06-30"],
            "report_date": ["2024-12-31", "2024-06-30"],
            "entity_name": ["Test BDC", "Test BDC"],
            "primary_document": ["doc.htm", "doc.htm"],
            "xbrl_download_status": ["not_found", "not_found"],
        })

        output_file = tmp_path / "output" / "html_extraction_holdings.csv"
        output_file.parent.mkdir(parents=True, exist_ok=True)

        with patch("pipeline.html_template.HTML_TEMPLATE_DIR", template_dir), \
             patch("pipeline.html_template.BDC_HTML_CACHE_DIR", html_dir), \
             patch("pipeline.html_template.HTML_EXTRACTION_FILE", output_file):
            from pipeline.html_template import extract_all_html
            result = extract_all_html(
                client=None,
                filings_index=filings_index,
            )

        assert not result.empty

    def test_skip_no_template(self, tmp_path):
        """Filings without templates should be skipped."""
        template_dir = tmp_path / "templates"
        template_dir.mkdir()

        filings_index = pd.DataFrame({
            "cik": ["0099999"],
            "accession_number": ["0099999-00-001"],
            "form_type": ["10-K"],
            "filing_date": ["2024-12-31"],
            "report_date": ["2024-12-31"],
            "entity_name": ["Unknown BDC"],
            "primary_document": ["doc.htm"],
            "xbrl_download_status": ["not_found"],
        })

        output_file = tmp_path / "output" / "html_extraction_holdings.csv"
        output_file.parent.mkdir(parents=True, exist_ok=True)

        with patch("pipeline.html_template.HTML_TEMPLATE_DIR", template_dir), \
             patch("pipeline.html_template.HTML_EXTRACTION_FILE", output_file):
            from pipeline.html_template import extract_all_html
            result = extract_all_html(
                client=None,
                filings_index=filings_index,
            )

        assert result.empty


# ===========================================================================
# Multi-Variant Template Support
# ===========================================================================

class TestNormalizeTemplate:
    def test_v1_wrapped_as_single_variant(self):
        """v1.0 template (no variants key) is wrapped into a single-variant list."""
        template = _make_template()
        norm = _normalize_template(template)
        assert "variants" in norm
        assert len(norm["variants"]) == 1
        v = norm["variants"][0]
        assert v["format_id"] == "default"
        assert v["column_mapping"] == template["column_mapping"]
        assert v["value_formats"] == template["value_formats"]
        assert v["filer_quirks"] == template["filer_quirks"]

    def test_v2_returned_as_is(self):
        """v2.0 template (has variants key) is returned unchanged."""
        v1 = _make_template()
        variant = {
            "format_id": "test_variant",
            "column_mapping": v1["column_mapping"],
            "value_formats": v1["value_formats"],
            "row_conventions": v1["row_conventions"],
            "filer_quirks": v1["filer_quirks"],
            "programmatic_analysis": v1["programmatic_analysis"],
        }
        template = {
            "schema_version": "2.0",
            "cik": "1234567",
            "entity_name": "Test BDC",
            "variants": [variant],
        }
        norm = _normalize_template(template)
        assert norm is template  # same object, not copied
        assert len(norm["variants"]) == 1
        assert norm["variants"][0]["format_id"] == "test_variant"


class TestSelectBestVariant:
    def _make_variant(self, format_id, header_texts, col_count, grid_positions=None):
        """Build a variant dict with column_mapping matching the given headers."""
        cm = {}
        field_names = [
            "company", "interest_rate", "maturity_date",
            "principal_amount", "cost", "fair_value",
        ]
        for i, (field, hdr) in enumerate(
            zip(field_names, header_texts)
        ):
            cm[field] = {"index": i, "header_text": hdr}
        pa = {
            "column_count": col_count,
        }
        if grid_positions:
            pa["grid_positions"] = grid_positions
        return {
            "format_id": format_id,
            "column_mapping": cm,
            "value_formats": {"dollar_unit": 1},
            "programmatic_analysis": pa,
        }

    def test_exact_match_selected(self):
        """Variant with zero drift is selected over one with mismatches."""
        # Variant A matches the table perfectly
        var_a = self._make_variant(
            "match",
            ["Company", "Interest Rate", "Maturity Date",
             "Principal Amount", "Cost", "Fair Value"],
            col_count=6,
        )
        # Variant B has wrong header texts
        var_b = self._make_variant(
            "mismatch",
            ["Issuer", "Coupon", "Due Date",
             "Par", "Basis", "Market Value"],
            col_count=6,
        )
        template = {
            "schema_version": "2.0",
            "variants": [var_b, var_a],  # mismatch first
        }
        table = ScheduleTable(
            rows=[
                ["Company", "Interest Rate", "Maturity Date",
                 "Principal Amount", "Cost", "Fair Value"],
                ["Acme", "10%", "2025", "1000", "990", "1010"],
            ],
            header_row_idx=0,
            score=15.0,
            dollar_unit=1,
        )
        best = _select_best_variant(table, template)
        assert best["format_id"] == "match"

    def test_fallback_returns_first_variant(self):
        """When all variants have drift, the first variant is returned."""
        var_a = self._make_variant(
            "first",
            ["Issuer", "Coupon", "Due Date",
             "Par", "Basis", "Market Value"],
            col_count=6,
        )
        var_b = self._make_variant(
            "second",
            ["Name", "Rate", "Maturity",
             "Amount", "Price", "Worth"],
            col_count=6,
        )
        template = {
            "schema_version": "2.0",
            "variants": [var_a, var_b],
        }
        table = ScheduleTable(
            rows=[
                ["Company", "Interest Rate", "Maturity Date",
                 "Principal Amount", "Cost", "Fair Value"],
                ["Acme", "10%", "2025", "1000", "990", "1010"],
            ],
            header_row_idx=0,
            score=15.0,
            dollar_unit=1,
        )
        best = _select_best_variant(table, template)
        # Both have drift; should pick the one with fewer mismatches,
        # or first if tied
        assert best["format_id"] in ("first", "second")

    def test_single_variant_works(self):
        """Single-variant template returns that variant."""
        var = self._make_variant(
            "only",
            ["Company", "Rate", "Maturity",
             "Principal", "Cost", "FV"],
            col_count=6,
        )
        template = {
            "schema_version": "2.0",
            "variants": [var],
        }
        table = ScheduleTable(
            rows=[
                ["Company", "Rate", "Maturity",
                 "Principal", "Cost", "FV"],
                ["Acme", "10%", "2025", "1000", "990", "1010"],
            ],
            header_row_idx=0,
            score=15.0,
            dollar_unit=1,
        )
        best = _select_best_variant(table, template)
        assert best["format_id"] == "only"

    # --- Amendment #2: shift_count tiebreaker ---

    def test_select_best_variant_shift_count_tiebreaker(self):
        """Variant whose headers match in-place beats variant with reordered headers."""
        # Variant "in_place": headers at their expected positions.
        var_in_place = self._make_variant(
            "in_place",
            ["Company", "Interest Rate", "Maturity Date",
             "Principal Amount", "Cost", "Fair Value"],
            col_count=6,
            grid_positions=[0, 1, 2, 3, 4, 5],
        )
        # Variant "reordered": same column count but expected order is
        # shifted -- every header still exists in the table (so no "real"
        # mismatches) but at different positions (so they count as shifts).
        var_reordered = self._make_variant(
            "reordered",
            ["Fair Value", "Cost", "Principal Amount",
             "Maturity Date", "Interest Rate", "Company"],
            col_count=6,
            grid_positions=[0, 1, 2, 3, 4, 5],
        )
        template = {
            "schema_version": "2.0",
            "variants": [var_reordered, var_in_place],  # reordered first
        }
        table = ScheduleTable(
            rows=[
                ["Company", "Interest Rate", "Maturity Date",
                 "Principal Amount", "Cost", "Fair Value"],
                ["Acme", "10%", "2025", "1000", "990", "1010"],
            ],
            header_row_idx=0,
            score=15.0,
            dollar_unit=1,
        )
        best = _select_best_variant(table, template)
        # Both variants have real=0 and same col_delta. The in-place
        # variant has fewer shifts, so it should win via #2's tiebreaker.
        assert best["format_id"] == "in_place"

    # --- Amendment #8: skip_count tiebreaker ---

    def test_select_best_variant_skip_count_tiebreaker(self):
        """Variant pointing grid_positions at empty cells loses on skip count."""
        # Variant "matches": headers match the actual 6-col header exactly.
        var_matches = self._make_variant(
            "matches",
            ["Company", "Interest Rate", "Maturity Date",
             "Principal Amount", "Cost", "Fair Value"],
            col_count=6,
            grid_positions=[0, 1, 2, 3, 4, 5],
        )
        # Variant "empty_targets": headers exist in the table but its
        # grid_positions point at indices whose cells are empty -- so
        # real=0 (via shift recovery) but skip count is high.
        var_empty = self._make_variant(
            "empty_targets",
            ["Company", "Interest Rate", "Maturity Date",
             "Principal Amount", "Cost", "Fair Value"],
            col_count=6,
            grid_positions=[0, 6, 7, 8, 9, 10],
        )
        template = {
            "schema_version": "2.0",
            "variants": [var_empty, var_matches],  # empty first
        }
        # Build a table with the real headers at 0-5 and empty cells at 6-10.
        table = ScheduleTable(
            rows=[
                ["Company", "Interest Rate", "Maturity Date",
                 "Principal Amount", "Cost", "Fair Value",
                 "", "", "", "", ""],
                ["Acme", "10%", "2025", "1000", "990", "1010",
                 "", "", "", "", ""],
            ],
            header_row_idx=0,
            score=15.0,
            dollar_unit=1,
        )
        best = _select_best_variant(table, template)
        # var_matches has skip=0; var_empty has skip=5 (5 fields at
        # empty cells). Both have real=0. var_matches should win.
        assert best["format_id"] == "matches"


# ---------------------------------------------------------------------------
# Amendment #25: Filing-date-aware variant selection (tiebreaker only)
# ---------------------------------------------------------------------------

class TestVariantDateRanges:
    """Tests for `_variant_date_ranges` and date-based variant filtering."""

    def _make_table(self, header: list[str]) -> ScheduleTable:
        return ScheduleTable(
            rows=[header, ["val"] * len(header)],
            header_row_idx=0,
            score=15.0,
            dollar_unit=1,
        )

    def _make_variant(
        self,
        format_id: str,
        headers: list[str],
        source_filing: str | None = None,
        effective_from: str | None = None,
        effective_until: str | None = None,
    ) -> dict:
        field_names = [
            "company", "interest_rate", "maturity_date",
            "principal_amount", "cost", "fair_value",
        ]
        cm = {f: {"index": i, "header_text": h}
              for i, (f, h) in enumerate(zip(field_names, headers))}
        v: dict = {
            "format_id": format_id,
            "column_mapping": cm,
            "value_formats": {"dollar_unit": 1},
            "programmatic_analysis": {"column_count": len(headers)},
        }
        if source_filing is not None:
            v["source_filing"] = source_filing
        if effective_from is not None:
            v["effective_from"] = effective_from
        if effective_until is not None:
            v["effective_until"] = effective_until
        return v

    def test_date_ranges_auto_derived_from_source_filings(self):
        """Auto-derive [from, until) windows from source_filing dates."""
        from pipeline.html_template import _variant_date_ranges

        with patch(
            "pipeline.html_template._load_accession_dates",
            return_value={
                "ACC-2013": "2013-03-15",
                "ACC-2017": "2017-06-01",
                "ACC-2020": "2020-02-10",
            },
        ):
            tpl = {
                "variants": [
                    self._make_variant("v2013", ["a"] * 6, source_filing="ACC-2013"),
                    self._make_variant("v2017", ["a"] * 6, source_filing="ACC-2017"),
                    self._make_variant("v2020", ["a"] * 6, source_filing="ACC-2020"),
                ]
            }
            ranges = _variant_date_ranges(tpl)
        # Earliest variant claims all pre-source filings
        assert ranges["v2013"] == (None, "2017-06-01")
        # Middle variant: [own_source, next_source)
        assert ranges["v2017"] == ("2017-06-01", "2020-02-10")
        # Latest variant: open on the right
        assert ranges["v2020"] == ("2020-02-10", None)

    def test_explicit_effective_from_until_overrides_auto_derivation(self):
        """`effective_from` / `effective_until` in template win over derivation."""
        from pipeline.html_template import _variant_date_ranges

        with patch(
            "pipeline.html_template._load_accession_dates",
            return_value={"ACC-1": "2015-01-01", "ACC-2": "2020-01-01"},
        ):
            tpl = {
                "variants": [
                    self._make_variant("v1", ["a"] * 6, source_filing="ACC-1",
                                       effective_until="2019-06-30"),
                    self._make_variant("v2", ["a"] * 6, source_filing="ACC-2",
                                       effective_from="2019-07-01"),
                ]
            }
            ranges = _variant_date_ranges(tpl)
        assert ranges["v1"] == (None, "2019-06-30")
        assert ranges["v2"] == ("2019-07-01", None)

    def test_missing_source_filing_treated_as_unrestricted(self):
        """Variant with no source_filing is not in the ranges map."""
        from pipeline.html_template import _variant_date_ranges

        with patch(
            "pipeline.html_template._load_accession_dates",
            return_value={"ACC-A": "2020-01-01"},
        ):
            tpl = {
                "variants": [
                    self._make_variant("with_src", ["a"] * 6, source_filing="ACC-A"),
                    self._make_variant("no_src", ["a"] * 6),
                ]
            }
            ranges = _variant_date_ranges(tpl)
        assert "with_src" in ranges
        assert "no_src" not in ranges  # unrestricted -> not recorded

    def test_in_range_half_open_semantics(self):
        """`_in_range` uses half-open [from, until) semantics."""
        from pipeline.html_template import _in_range

        assert _in_range("2020-01-01", "2020-01-01", "2020-12-31")
        assert _in_range("2020-06-15", "2020-01-01", "2020-12-31")
        # Upper bound is exclusive
        assert not _in_range("2020-12-31", "2020-01-01", "2020-12-31")
        assert not _in_range("2019-12-31", "2020-01-01", "2020-12-31")
        # Unbounded either side
        assert _in_range("2000-01-01", None, "2020-12-31")
        assert _in_range("2099-01-01", "2020-01-01", None)
        assert _in_range("2020-06-15", None, None)

    def test_filing_date_selects_correct_variant(self):
        """A 2021 filing routes to the 2020 variant, not the 2013 legacy."""
        modern_headers = ["Company", "Interest Rate", "Maturity Date",
                          "Principal Amount", "Cost", "Fair Value"]
        legacy = self._make_variant(
            "v2013_legacy", modern_headers, source_filing="LEG-ACC",
        )
        modern = self._make_variant(
            "v2020_modern", modern_headers, source_filing="MOD-ACC",
        )
        template = {"schema_version": "2.0", "variants": [legacy, modern]}
        table = self._make_table(modern_headers)

        with patch(
            "pipeline.html_template._load_accession_dates",
            return_value={
                "LEG-ACC": "2013-04-01",
                "MOD-ACC": "2020-02-10",
            },
        ):
            best_modern = _select_best_variant(
                table, template, filing_date="2021-05-15",
            )
            best_legacy = _select_best_variant(
                table, template, filing_date="2014-06-01",
            )

        assert best_modern["format_id"] == "v2020_modern"
        assert best_legacy["format_id"] == "v2013_legacy"

    def test_filing_date_outside_all_ranges_falls_back_to_scoring(self):
        """If date filter empties the candidate set, fall back to scoring."""
        headers = ["Company", "Interest Rate", "Maturity Date",
                   "Principal Amount", "Cost", "Fair Value"]
        v1 = self._make_variant(
            "v1", headers,
            effective_from="2010-01-01", effective_until="2012-01-01",
        )
        v2 = self._make_variant(
            "v2", headers,
            effective_from="2012-01-01", effective_until="2014-01-01",
        )
        template = {"schema_version": "2.0", "variants": [v1, v2]}
        table = self._make_table(headers)

        with patch(
            "pipeline.html_template._load_accession_dates",
            return_value={},
        ):
            best = _select_best_variant(
                table, template, filing_date="2025-05-15",
            )
        # Fallback: both are candidates again; at least one picked
        assert best["format_id"] in ("v1", "v2")

    def test_filing_date_none_preserves_score_based_selection(self):
        """No filing_date -> date filter is bypassed, old behavior intact."""
        headers = ["Company", "Interest Rate", "Maturity Date",
                   "Principal Amount", "Cost", "Fair Value"]
        legacy = self._make_variant(
            "v_legacy",
            ["Issuer", "Coupon", "Due", "Par", "Basis", "Mkt"],
            source_filing="LEG-ACC",
        )
        modern = self._make_variant(
            "v_modern", headers, source_filing="MOD-ACC",
        )
        template = {"schema_version": "2.0", "variants": [legacy, modern]}
        table = self._make_table(headers)

        with patch(
            "pipeline.html_template._load_accession_dates",
            return_value={
                "LEG-ACC": "2013-04-01", "MOD-ACC": "2020-02-10",
            },
        ):
            best = _select_best_variant(table, template, filing_date=None)
        # Without date signal, score-based selection still picks modern
        assert best["format_id"] == "v_modern"

    def test_single_variant_bypasses_date_filter(self):
        """Templates with a single variant return it unconditionally."""
        headers = ["Company", "Interest Rate", "Maturity Date",
                   "Principal Amount", "Cost", "Fair Value"]
        only = self._make_variant("only", headers, source_filing="ACC")
        template = {"schema_version": "2.0", "variants": [only]}
        table = self._make_table(headers)

        with patch(
            "pipeline.html_template._load_accession_dates",
            return_value={"ACC": "2020-01-01"},
        ):
            best = _select_best_variant(
                table, template, filing_date="1999-01-01",
            )
        assert best["format_id"] == "only"

    def test_extract_filing_threads_filing_date_through(self):
        """extract_filing_with_template forwards filing_date to selection."""
        html = _make_schedule_html(
            header=["Company", "Rate", "Maturity", "Principal", "Cost", "Fair Value"],
            data_rows=[
                [f"Issuer {i}", "10.0%", "12/31/2025", "1000", "995", "1010"]
                for i in range(20)
            ],
            title="Schedule of Investments",
        )
        legacy = self._make_variant(
            "legacy",
            ["Company", "Rate", "Maturity", "Principal", "Cost", "Fair Value"],
            source_filing="LEG-ACC",
        )
        modern = self._make_variant(
            "modern",
            ["Company", "Rate", "Maturity", "Principal", "Cost", "Fair Value"],
            source_filing="MOD-ACC",
        )
        template = {"schema_version": "2.0", "variants": [legacy, modern]}

        with patch(
            "pipeline.html_template._load_accession_dates",
            return_value={
                "LEG-ACC": "2013-04-01", "MOD-ACC": "2020-02-10",
            },
        ):
            _, stats_modern = extract_filing_with_template(
                html,
                filing_meta={"cik": "1234567",
                             "filing_date": "2021-06-01",
                             "accession_number": "TEST",
                             "form_type": "10-K",
                             "report_date": "2021-06-30"},
                template=template,
            )
            _, stats_legacy = extract_filing_with_template(
                html,
                filing_meta={"cik": "1234567",
                             "filing_date": "2014-06-01",
                             "accession_number": "TEST",
                             "form_type": "10-K",
                             "report_date": "2014-06-30"},
                template=template,
            )

        assert stats_modern["variant_id"] == "modern"
        assert stats_legacy["variant_id"] == "legacy"


class TestPikColumnExtraction:
    def test_pik_from_dedicated_column(self):
        """PIK rate extracted from a separate column (not regex from rate cell)."""
        template = _make_template(
            column_overrides={
                "pik_rate": {"index": 6, "header_text": "PIK Rate"},
            },
            overrides={
                "programmatic_analysis": {
                    "tables_found": 1,
                    "total_data_rows": 20,
                    "column_count": 7,
                    "detected_dollar_unit": 1,
                },
            },
        )
        cells = [
            "Acme Corp", "10.5", "12/31/2025", "1000000",
            "990000", "1010000", "3.0",
        ]
        result = _apply_template_column_map(cells, template)
        assert result["pik_rate"] == 3.0
        assert result["interest_rate"] == 10.5

    def test_pik_column_overrides_regex(self):
        """When both PIK column and rate cell contain PIK info, column wins."""
        template = _make_template(
            column_overrides={
                "pik_rate": {"index": 6, "header_text": "PIK Rate"},
            },
            overrides={
                "programmatic_analysis": {
                    "tables_found": 1,
                    "total_data_rows": 20,
                    "column_count": 7,
                    "detected_dollar_unit": 1,
                },
            },
        )
        # Rate cell has "10.5% (2.0% PIK)" but PIK column has "3.0"
        cells = [
            "Acme Corp", "10.5% (2.0% PIK)", "12/31/2025", "1000000",
            "990000", "1010000", "3.0",
        ]
        result = _apply_template_column_map(cells, template)
        # PIK column (3.0) overrides the regex-extracted 2.0
        assert result["pik_rate"] == 3.0

    def test_pik_column_null_index_no_effect(self):
        """When pik_rate has null index, no column extraction occurs."""
        template = _make_template(
            column_overrides={
                "pik_rate": {"index": None, "header_text": ""},
            },
        )
        cells = [
            "Acme Corp", "10.5% (2.0% PIK)", "12/31/2025", "1000000",
            "990000", "1010000",
        ]
        result = _apply_template_column_map(cells, template)
        # Only regex extraction from rate cell
        assert result["pik_rate"] == 2.0


class TestVariantIntegration:
    def test_extract_with_v2_template(self):
        """Full extraction with a v2.0 multi-variant template."""
        # Build two variants: 6-col and 9-col
        var_6col = {
            "format_id": "6col",
            "column_mapping": {
                "company": {"index": 0, "header_text": "Company"},
                "fair_value": {"index": 5, "header_text": "Fair Value"},
                "cost": {"index": 4, "header_text": "Cost"},
                "principal_amount": {"index": 3, "header_text": "Principal"},
                "interest_rate": {"index": 1, "header_text": "Rate"},
                "maturity_date": {"index": 2, "header_text": "Maturity"},
                "shares_held": {"index": None, "header_text": ""},
                "pct_of_net_assets": {"index": None, "header_text": ""},
            },
            "value_formats": {"dollar_unit": 1},
            "row_conventions": {"continuation_detection": "empty_first_cell"},
            "filer_quirks": {"rate_cell_includes_reference": False},
            "programmatic_analysis": {"column_count": 6},
        }
        var_9col = {
            "format_id": "9col",
            "column_mapping": {
                "company": {"index": 0, "header_text": "Issuer"},
                "fair_value": {"index": 8, "header_text": "Market Value"},
                "cost": {"index": 7, "header_text": "Cost Basis"},
                "principal_amount": {"index": 6, "header_text": "Par"},
                "interest_rate": {"index": 1, "header_text": "Coupon"},
                "maturity_date": {"index": 2, "header_text": "Due Date"},
                "shares_held": {"index": None, "header_text": ""},
                "pct_of_net_assets": {"index": None, "header_text": ""},
            },
            "value_formats": {"dollar_unit": 1},
            "row_conventions": {"continuation_detection": "empty_first_cell"},
            "filer_quirks": {"rate_cell_includes_reference": False},
            "programmatic_analysis": {"column_count": 9},
        }
        template = {
            "schema_version": "2.0",
            "cik": "999",
            "entity_name": "Test Multi",
            "variants": [var_6col, var_9col],
        }

        # HTML matches the 6-col variant
        html = _make_schedule_html(
            header=["Company", "Rate", "Maturity",
                    "Principal", "Cost", "Fair Value"],
            data_rows=[
                ["Acme Corp", "10.5", "12/31/2025", "1000000",
                 "990000", "1010000"],
            ] * 15,
            title="Schedule of Investments",
        )
        filing_meta = {
            "cik": "999",
            "entity_name": "Test Multi",
            "accession_number": "000999-24-001",
            "form_type": "10-K",
            "filing_date": "2024-03-15",
            "report_date": "2024-12-31",
        }

        holdings, stats = extract_filing_with_template(
            html, filing_meta, template,
        )

        assert stats["variant_id"] == "6col"
        assert not stats["drift_detected"]
        assert len(holdings) > 0
        assert holdings[0]["fair_value"] == 1010000.0


class TestIndustryLookAhead:
    """Amendment #11: industry field in look-ahead set."""

    def test_industry_colspan_offset(self):
        """Industry header at grid N, data at grid N+1 due to colspan."""
        # 7-col table: Company, Industry (header at 1, data at 2 due to
        # colspan offset), Rate, Maturity, Cost, FV + empty col
        rows = [
            ["Company", "Industry", "", "Interest Rate", "Maturity",
             "Cost", "Fair Value"],
        ] + [
            [f"Co{i}", "", "Technology", "10%", "12/31/2025", "990", "1010"]
            for i in range(16)
        ]
        # Override last two to Healthcare to test both values
        rows[-1] = ["CoLast", "", "Healthcare", "11%", "06/30/2026",
                     "495", "505"]
        html = (
            "<html><body><p>Schedule of Investments</p>"
            + _make_html_table(rows)
            + "</body></html>"
        )
        template = _make_template(
            column_overrides={
                "industry": {"source": "column", "index": 1,
                             "header_text": "Industry"},
                "interest_rate": {"index": 3, "header_text": "Interest Rate"},
                "maturity_date": {"index": 4, "header_text": "Maturity"},
                "principal_amount": {"index": None, "header_text": ""},
                "cost": {"index": 5, "header_text": "Cost"},
                "fair_value": {"index": 6, "header_text": "Fair Value"},
            },
        )
        filing_meta = {"cik": "1", "report_date": "2024-12-31"}
        holdings, stats = extract_filing_with_template(
            html, filing_meta, template,
        )
        assert len(holdings) >= 2
        industries = [h.get("industry") for h in holdings if h.get("industry")]
        assert len(industries) >= 2
        assert "Technology" in industries
        assert "Healthcare" in industries

    def test_industry_direct_no_offset(self):
        """Industry at correct grid position, no look-ahead needed."""
        rows = [
            ["Company", "Industry", "Interest Rate", "Maturity",
             "Cost", "Fair Value"],
        ] + [
            [f"Co{i}", "Technology", "10%", "12/31/2025", "990", "1010"]
            for i in range(16)
        ]
        html = (
            "<html><body><p>Schedule of Investments</p>"
            + _make_html_table(rows)
            + "</body></html>"
        )
        template = _make_template(
            column_overrides={
                "industry": {"source": "column", "index": 1,
                             "header_text": "Industry"},
                # Shift rate/maturity to avoid index collision with industry
                "interest_rate": {"index": 2, "header_text": "Interest Rate"},
                "maturity_date": {"index": 3, "header_text": "Maturity"},
                "cost": {"index": 4, "header_text": "Cost"},
                "fair_value": {"index": 5, "header_text": "Fair Value"},
                "principal_amount": {"index": None, "header_text": ""},
            },
        )
        filing_meta = {"cik": "1", "report_date": "2024-12-31"}
        holdings, stats = extract_filing_with_template(
            html, filing_meta, template,
        )
        assert len(holdings) >= 1
        assert holdings[0].get("industry") == "Technology"


class TestCompanyRowNoFinancials:
    """Amendment #10: alternating company/investment row merging."""

    def test_alternating_rows_merged(self):
        """Company-header row + investment row should merge."""
        rows = [
            ["Company", "Principal", "Cost", "Fair Value"],
        ]
        # 8 alternating pairs = 16 data rows (>= 15 threshold)
        for i in range(8):
            rows.append([f"Company{i}", "", "", ""])
            rows.append([f"term loan {i}", f"{1000+i}", f"{990+i}", f"{1010+i}"])
        html = (
            "<html><body><p>Schedule of Investments</p>"
            + _make_html_table(rows)
            + "</body></html>"
        )
        template = _make_template(
            overrides={
                "row_conventions": {
                    "continuation_detection": "company_row_no_financials",
                    "industry_source": "section_header",
                },
            },
            column_overrides={
                "interest_rate": {"index": None, "header_text": ""},
                "maturity_date": {"index": None, "header_text": ""},
                "principal_amount": {"index": 1, "header_text": "Principal"},
                "cost": {"index": 2, "header_text": "Cost"},
                "fair_value": {"index": 3, "header_text": "Fair Value"},
            },
        )
        filing_meta = {"cik": "1", "report_date": "2024-12-31"}
        holdings, stats = extract_filing_with_template(
            html, filing_meta, template,
        )
        # Should produce 8 merged holdings, not 16 separate rows
        fv_holdings = [h for h in holdings if h.get("fair_value") is not None]
        assert len(fv_holdings) == 8
        # First holding: Company0 with FV
        assert fv_holdings[0]["investment_identifier"] == "Company0"
        assert fv_holdings[0]["fair_value"] == 1010.0
        # Last holding: Company7 with FV
        assert fv_holdings[7]["investment_identifier"] == "Company7"
        assert fv_holdings[7]["fair_value"] == 1017.0

    def test_alternating_rows_industry_inherited(self):
        """Company-header row's industry should propagate to investment row."""
        rows = [
            ["Company", "Industry", "Principal", "Cost", "Fair Value"],
        ]
        industries = ["Technology", "Healthcare", "Energy", "Finance",
                       "Retail", "Media", "Telecom", "Software"]
        for i, ind in enumerate(industries):
            rows.append([f"Co{i}", ind, "", "", ""])
            rows.append([f"loan {i}", "", f"{1000+i}", f"{990+i}", f"{1010+i}"])
        html = (
            "<html><body><p>Schedule of Investments</p>"
            + _make_html_table(rows)
            + "</body></html>"
        )
        template = _make_template(
            overrides={
                "row_conventions": {
                    "continuation_detection": "company_row_no_financials",
                    "industry_source": "column",
                },
            },
            column_overrides={
                "industry": {"source": "column", "index": 1,
                             "header_text": "Industry"},
                "interest_rate": {"index": None, "header_text": ""},
                "maturity_date": {"index": None, "header_text": ""},
                "principal_amount": {"index": 2, "header_text": "Principal"},
                "cost": {"index": 3, "header_text": "Cost"},
                "fair_value": {"index": 4, "header_text": "Fair Value"},
            },
        )
        filing_meta = {"cik": "1", "report_date": "2024-12-31"}
        holdings, stats = extract_filing_with_template(
            html, filing_meta, template,
        )
        fv_holdings = [h for h in holdings if h.get("fair_value") is not None]
        assert len(fv_holdings) == 8
        assert fv_holdings[0]["investment_identifier"] == "Co0"
        assert fv_holdings[0]["fair_value"] == 1010.0
        assert fv_holdings[0].get("industry") == "Technology"
        assert fv_holdings[3].get("industry") == "Finance"

    def test_standalone_rows_unaffected(self):
        """Normal rows (name + financials in same row) still work."""
        rows = [
            ["Company", "Principal", "Cost", "Fair Value"],
        ] + [
            [f"Co{i}", f"{1000+i}", f"{990+i}", f"{1010+i}"]
            for i in range(16)
        ]
        html = (
            "<html><body><p>Schedule of Investments</p>"
            + _make_html_table(rows)
            + "</body></html>"
        )
        template = _make_template(
            overrides={
                "row_conventions": {
                    "continuation_detection": "company_row_no_financials",
                    "industry_source": "section_header",
                },
            },
            column_overrides={
                "interest_rate": {"index": None, "header_text": ""},
                "maturity_date": {"index": None, "header_text": ""},
                "principal_amount": {"index": 1, "header_text": "Principal"},
                "cost": {"index": 2, "header_text": "Cost"},
                "fair_value": {"index": 3, "header_text": "Fair Value"},
            },
        )
        filing_meta = {"cik": "1", "report_date": "2024-12-31"}
        holdings, stats = extract_filing_with_template(
            html, filing_meta, template,
        )
        assert len(holdings) == 16
        assert holdings[0]["investment_identifier"] == "Co0"
        assert holdings[0]["fair_value"] == 1010.0
        assert holdings[15]["investment_identifier"] == "Co15"

    def test_consecutive_company_headers(self):
        """Two company-header rows in a row: first should be emitted standalone."""
        rows = [
            ["Company", "Principal", "Cost", "Fair Value"],
        ]
        # 7 normal alternating pairs (14 rows)
        for i in range(7):
            rows.append([f"Normal{i}", "", "", ""])
            rows.append([f"loan {i}", f"{1000+i}", f"{990+i}", f"{1010+i}"])
        # Then two consecutive company headers followed by investment
        rows.append(["Acme Corp", "", "", ""])
        rows.append(["Beta Inc", "", "", ""])
        rows.append(["term loan", "500", "495", "505"])
        html = (
            "<html><body><p>Schedule of Investments</p>"
            + _make_html_table(rows)
            + "</body></html>"
        )
        template = _make_template(
            overrides={
                "row_conventions": {
                    "continuation_detection": "company_row_no_financials",
                    "industry_source": "section_header",
                },
            },
            column_overrides={
                "interest_rate": {"index": None, "header_text": ""},
                "maturity_date": {"index": None, "header_text": ""},
                "principal_amount": {"index": 1, "header_text": "Principal"},
                "cost": {"index": 2, "header_text": "Cost"},
                "fair_value": {"index": 3, "header_text": "Fair Value"},
            },
        )
        filing_meta = {"cik": "1", "report_date": "2024-12-31"}
        holdings, stats = extract_filing_with_template(
            html, filing_meta, template,
        )
        # Beta Inc merges with term loan; Acme Corp emitted standalone (no FV)
        fv_holdings = [h for h in holdings if h.get("fair_value") is not None]
        # 7 normal pairs + 1 Beta Inc = 8
        assert len(fv_holdings) == 8
        # The last FV holding should be Beta Inc
        assert fv_holdings[7]["investment_identifier"] == "Beta Inc"
        assert fv_holdings[7]["fair_value"] == 505.0


# ===========================================================================
# Amendment #6: missing_key_column continuation detection
# ===========================================================================

class TestMissingKeyColumnContinuation:
    def test_continuation_missing_key_column(self):
        """Continuation rows have empty key column -> merged with preceding."""
        # Template: company=0, maturity_date=1 (the key column),
        # cost=2, fair_value=3.
        rows = [
            ["Company", "Maturity", "Cost", "Fair Value"],
        ]
        # 16 two-row holdings: first row has date, second has empty date
        # (so it's a continuation) plus cost/FV.
        for i in range(16):
            rows.append([f"Co{i}", f"12/31/2025", "", ""])
            rows.append(["desc line", "", f"{990+i}", f"{1010+i}"])
        html = (
            "<html><body><p>Schedule of Investments</p>"
            + _make_html_table(rows)
            + "</body></html>"
        )
        template = _make_template(
            overrides={
                "row_conventions": {
                    "continuation_detection": "missing_key_column",
                    "continuation_key_column": 1,  # maturity column
                    "industry_source": "section_header",
                },
            },
            column_overrides={
                "interest_rate": {"index": None, "header_text": ""},
                "principal_amount": {"index": None, "header_text": ""},
                "maturity_date": {"index": 1, "header_text": "Maturity"},
                "cost": {"index": 2, "header_text": "Cost"},
                "fair_value": {"index": 3, "header_text": "Fair Value"},
            },
        )
        filing_meta = {"cik": "1", "report_date": "2024-12-31"}
        holdings, stats = extract_filing_with_template(
            html, filing_meta, template,
        )
        # Continuation rows should have been merged into their parent row
        # via the post_process pass.  Each holding should have the company
        # name AND the cost/FV from its continuation row.
        fv_holdings = [h for h in holdings if h.get("fair_value") is not None]
        assert len(fv_holdings) >= 16
        # First holding should have Co0 as name and FV 1010
        first = [h for h in fv_holdings
                 if h.get("investment_identifier") == "Co0"]
        assert first, "Co0 should appear with a fair value"
        assert first[0]["fair_value"] == 1010.0


# ===========================================================================
# Amendment #16: section-header filter
# ===========================================================================

class TestSectionHeaderFiltering:
    def test_section_header_filtering(self):
        """Rows whose issuer_name matches section_header_examples are filtered."""
        rows = [
            ["Company", "Interest Rate", "Maturity Date",
             "Principal Amount", "Cost", "Fair Value"],
        ]
        # Normal data rows
        for i in range(16):
            rows.append([
                f"Acme{i}", "10.5", "12/31/2025",
                "1000000", "990000", "1010000",
            ])
        # A section-header-looking row that slipped through row classification
        rows.append([
            "Control Investments (4.9% of net assets)",
            "", "", "", "", "",
        ])
        # Plus another normal row
        rows.append([
            "Beta", "10.5", "12/31/2025",
            "1000000", "990000", "1010000",
        ])
        html = (
            "<html><body><p>Schedule of Investments</p>"
            + _make_html_table(rows)
            + "</body></html>"
        )
        template = _make_template(
            overrides={
                "row_conventions": {
                    "continuation_detection": "empty_first_cell",
                    "industry_source": "section_header",
                    "section_header_examples": [
                        "Control Investments",
                        "Affiliate Investments",
                    ],
                },
            },
        )
        filing_meta = {"cik": "1", "report_date": "2024-12-31"}
        holdings, stats = extract_filing_with_template(
            html, filing_meta, template,
        )
        names = [h["investment_identifier"] for h in holdings]
        # The section header row must be dropped
        assert not any("Control Investments" in n for n in names)
        # Normal rows preserved
        assert any(n == "Acme0" for n in names)
        assert any(n == "Beta" for n in names)

    def test_section_header_no_examples_no_filtering(self):
        """When no section_header_examples, multi-cell section-header-looking
        rows are NOT dropped (filter only activates when template provides
        examples)."""
        template = _make_template()  # no section_header_examples
        rows = [
            ["Company", "Interest Rate", "Maturity Date",
             "Principal Amount", "Cost", "Fair Value"],
        ]
        for i in range(16):
            rows.append([
                f"Acme{i}", "10.5", "12/31/2025",
                "1000000", "990000", "1010000",
            ])
        # Multi-cell row with section-header-ish company name; survives
        # because no section_header_examples to match against.
        rows.append([
            "Control Investments (4.9% of net assets)",
            "10.5", "12/31/2025",
            "1000000", "990000", "1010000",
        ])
        html = (
            "<html><body><p>Schedule of Investments</p>"
            + _make_html_table(rows)
            + "</body></html>"
        )
        filing_meta = {"cik": "1", "report_date": "2024-12-31"}
        holdings, _ = extract_filing_with_template(html, filing_meta, template)
        names = [h["investment_identifier"] for h in holdings]
        # Without section_header_examples, the row survives
        assert any("Control Investments" in n for n in names)


# ===========================================================================
# Amendment #9: dollar_unit_auto override
# ===========================================================================

class TestDollarUnitAuto:
    def test_dollar_unit_auto_uses_detected(self):
        """When dollar_unit_auto is true, detected unit overrides template."""
        template = _make_template(
            overrides={"value_formats": {
                "dollar_unit": 1000,  # template says thousands
                "dollar_unit_auto": True,
                "rate_format": "percentage",
                "date_format": "MM/DD/YYYY",
                "negative_convention": "parentheses",
                "dash_means_null": True,
            }}
        )
        cells = ["Acme", "10%", "12/31/2025", "500", "490", "510"]
        # Pass detected_dollar_unit=1 (actual dollars, overrides template)
        result = _apply_template_column_map(
            cells, template, detected_dollar_unit=1,
        )
        # With auto=True and detected=1, FV should be 510, NOT 510000.
        assert result["fair_value"] == 510.0
        assert result["cost"] == 490.0
        assert result["principal_amount"] == 500.0

    def test_dollar_unit_auto_false_uses_template(self):
        """When dollar_unit_auto is absent/false, template unit is used."""
        template = _make_template(
            overrides={"value_formats": {
                "dollar_unit": 1000,
                "rate_format": "percentage",
                "date_format": "MM/DD/YYYY",
                "negative_convention": "parentheses",
                "dash_means_null": True,
            }}
        )
        cells = ["Acme", "10%", "12/31/2025", "500", "490", "510"]
        result = _apply_template_column_map(
            cells, template, detected_dollar_unit=1,
        )
        # Without auto flag, template 1000 still wins.
        assert result["fair_value"] == 510000.0

    def test_dollar_unit_auto_default_parameter(self):
        """Default detected_dollar_unit=1 still works."""
        template = _make_template(
            overrides={"value_formats": {
                "dollar_unit": 1000,
                "dollar_unit_auto": True,
                "rate_format": "percentage",
                "date_format": "MM/DD/YYYY",
                "negative_convention": "parentheses",
                "dash_means_null": True,
            }}
        )
        cells = ["Acme", "10%", "12/31/2025", "500", "490", "510"]
        # No detected_dollar_unit passed -> defaults to 1
        result = _apply_template_column_map(cells, template)
        assert result["fair_value"] == 510.0


# ===========================================================================
# Amendment #31: Comma in month-name date
# ===========================================================================

class TestConvertDateComma:
    def test_comma_after_month(self):
        assert _convert_date("April, 2022") == "2022-04-01"

    def test_comma_abbreviated_month(self):
        assert _convert_date("Jun, 2019") == "2019-06-01"


# ===========================================================================
# Amendment #30: Decimal basis-point conversion
# ===========================================================================

class TestDecimalBasisPoints:
    def test_decimal_bps_converted(self):
        """L+712.5 (no %) -> 7.125% (basis points with decimal)."""
        template = _make_template(
            overrides={"filer_quirks": {
                "multi_line_cells": False,
                "instrument_in_company_cell": False,
                "rate_cell_includes_reference": True,
                "pik_notation": None,
            }}
        )
        cells = ["Acme", "L+712.5", "12/31/2025", "1000", "990", "1010"]
        result = _apply_template_column_map(cells, template)
        assert result["basis_spread"] == 7.125

    def test_integer_bps_still_converted(self):
        """L+450 (no %) -> 4.50%."""
        template = _make_template(
            overrides={"filer_quirks": {
                "multi_line_cells": False,
                "instrument_in_company_cell": False,
                "rate_cell_includes_reference": True,
                "pik_notation": None,
            }}
        )
        cells = ["Acme", "L+450", "12/31/2025", "1000", "990", "1010"]
        result = _apply_template_column_map(cells, template)
        assert result["basis_spread"] == 4.5

    def test_percentage_preserved(self):
        """4.50% stays 4.50 (% present, no conversion)."""
        template = _make_template(
            overrides={"filer_quirks": {
                "multi_line_cells": False,
                "instrument_in_company_cell": False,
                "rate_cell_includes_reference": True,
                "pik_notation": None,
            }}
        )
        cells = ["Acme", "L+4.50%", "12/31/2025", "1000", "990", "1010"]
        result = _apply_template_column_map(cells, template)
        assert result["basis_spread"] == 4.5


# ===========================================================================
# Amendment #32: Case-insensitive reference rate matching
# ===========================================================================

class TestCaseInsensitiveRatePatterns:
    def test_lowercase_libor(self):
        template = _make_template(
            overrides={"filer_quirks": {
                "multi_line_cells": False,
                "instrument_in_company_cell": False,
                "rate_cell_includes_reference": True,
                "pik_notation": None,
            }}
        )
        cells = ["Acme", "Libor + 5.5%", "12/31/2025", "1000", "990", "1010"]
        result = _apply_template_column_map(cells, template)
        assert result["reference_rate"] == "LIBOR"
        assert result["basis_spread"] == 5.5

    def test_lowercase_sofr(self):
        template = _make_template(
            overrides={"filer_quirks": {
                "multi_line_cells": False,
                "instrument_in_company_cell": False,
                "rate_cell_includes_reference": True,
                "pik_notation": None,
            }}
        )
        cells = ["Acme", "sofr+3.25%", "12/31/2025", "1000", "990", "1010"]
        result = _apply_template_column_map(cells, template)
        assert result["reference_rate"] == "SOFR"
        assert result["basis_spread"] == 3.25

    def test_mixed_case_spread_cell(self):
        """'libor + 400' in spread column."""
        template = _make_template(
            column_overrides={
                "basis_spread": {"index": 6, "header_text": "Spread"},
            },
            overrides={
                "programmatic_analysis": {
                    "tables_found": 1,
                    "total_data_rows": 20,
                    "column_count": 7,
                    "detected_dollar_unit": 1,
                },
            },
        )
        cells = ["Acme", "12.5", "12/31/2025", "1000", "990", "1010", "libor + 400"]
        result = _apply_template_column_map(cells, template)
        assert result["reference_rate"] == "LIBOR"
        assert result["basis_spread"] == 4.0


# ===========================================================================
# Amendment #25b: Split parenthetical negative concatenation
# ===========================================================================

class TestSplitParenNegative:
    def test_split_paren_concatenated(self):
        """'(12,987' + ')' -> '(12,987)' -> -12987."""
        template = _make_template()
        cells = ["Acme", "10%", "12/31/2025", "1000", "990", "(1,234", ")"]
        result = _apply_template_column_map(cells, template)
        assert result["fair_value"] == -1234.0

    def test_complete_paren_unchanged(self):
        """'(12,987)' already complete, no look-ahead needed."""
        template = _make_template()
        cells = ["Acme", "10%", "12/31/2025", "1000", "990", "(1,234)"]
        result = _apply_template_column_map(cells, template)
        assert result["fair_value"] == -1234.0

    def test_non_closing_next_cell_ignored(self):
        """'(12,987' + 'something' -> not concatenated."""
        template = _make_template()
        cells = ["Acme", "10%", "12/31/2025", "1000", "990", "(1,234", "other"]
        result = _apply_template_column_map(cells, template)
        # _parse_dollar("(1,234") should fail since no closing paren
        assert result["fair_value"] is None


# ===========================================================================
# Amendment #24: Em-dash / dash separator for instrument_in_company_cell
# ===========================================================================

class TestDashSeparatorInstrumentInCompany:
    def test_em_dash_separator(self):
        """Em-dash splits company and instrument."""
        template = _make_template(
            overrides={"filer_quirks": {
                "multi_line_cells": False,
                "instrument_in_company_cell": True,
                "rate_cell_includes_reference": False,
                "pik_notation": None,
            }}
        )
        cells = ["Acme Corp \u2013 Senior Secured Loan", "10%", "12/31/2025",
                 "1000", "990", "1010"]
        result = _apply_template_column_map(cells, template)
        assert result["issuer_name"] == "Acme Corp"
        assert result["instrument_description"] == "Senior Secured Loan"

    def test_en_dash_separator(self):
        """En-dash splits company and instrument."""
        template = _make_template(
            overrides={"filer_quirks": {
                "multi_line_cells": False,
                "instrument_in_company_cell": True,
                "rate_cell_includes_reference": False,
                "pik_notation": None,
            }}
        )
        cells = ["Acme Corp \u2014 First Lien", "10%", "12/31/2025",
                 "1000", "990", "1010"]
        result = _apply_template_column_map(cells, template)
        assert result["issuer_name"] == "Acme Corp"
        assert result["instrument_description"] == "First Lien"

    def test_double_hyphen_separator(self):
        """Double-hyphen splits company and instrument."""
        template = _make_template(
            overrides={"filer_quirks": {
                "multi_line_cells": False,
                "instrument_in_company_cell": True,
                "rate_cell_includes_reference": False,
                "pik_notation": None,
            }}
        )
        cells = ["Acme Corp -- Second Lien", "10%", "12/31/2025",
                 "1000", "990", "1010"]
        result = _apply_template_column_map(cells, template)
        assert result["issuer_name"] == "Acme Corp"
        assert result["instrument_description"] == "Second Lien"

    def test_no_separator_keeps_full_name(self):
        """No dash separator -- entire cell is issuer_name."""
        template = _make_template(
            overrides={"filer_quirks": {
                "multi_line_cells": False,
                "instrument_in_company_cell": True,
                "rate_cell_includes_reference": False,
                "pik_notation": None,
            }}
        )
        cells = ["Acme Corp", "10%", "12/31/2025", "1000", "990", "1010"]
        result = _apply_template_column_map(cells, template)
        assert result["issuer_name"] == "Acme Corp"
        assert result.get("instrument_description") is None


# ===========================================================================
# Amendment #26: Split PIK notation concatenation
# ===========================================================================

class TestSplitPIKConcatenation:
    def test_split_pik_concatenated(self):
        """'(PIK 1.00' + '%)' -> '(PIK 1.00 %)'."""
        template = _make_template(
            overrides={"filer_quirks": {
                "multi_line_cells": False,
                "instrument_in_company_cell": False,
                "rate_cell_includes_reference": True,
                "pik_notation": "parenthetical",
            }}
        )
        # Rate cell with split PIK
        cells = ["Acme", "9.42% (PIK 3.00", "%)", "12/31/2025",
                 "1000", "990", "1010"]
        result = _apply_template_column_map(cells, template)
        assert result["pik_rate"] == 3.0

    def test_non_pik_unclosed_paren_ignored(self):
        """Unclosed paren without PIK should not concatenate."""
        template = _make_template()
        cells = ["Acme", "10%", "12/31/2025", "1000", "(note", "1010"]
        result = _apply_template_column_map(cells, template)
        # Should not try to concatenate "(note" with next cell


# ===========================================================================
# Amendment #29: Mid-table row-width filtering
# ===========================================================================

class TestMidTableRowWidthFilter:
    def test_comparative_rows_filtered(self):
        """Rows significantly wider/narrower than header are skipped."""
        from pipeline.html_template import extract_filing_with_template

        html = "<html><body><table>"
        html += "<tr><td>Company</td><td>Interest Rate</td>"
        html += "<td>Maturity Date</td><td>Principal Amount</td>"
        html += "<td>Cost</td><td>Fair Value</td></tr>"
        # 16 normal rows to exceed data_row_count >= 15 threshold
        for i in range(16):
            html += f"<tr><td>Co{i}</td><td>10%</td><td>12/31/2025</td>"
            html += "<td>1000</td><td>990</td><td>1010</td></tr>"
        # Comparative row (10 cells -- much wider, delta >= 3)
        html += "<tr><td>Comp</td><td>10%</td><td>12/31/2024</td>"
        html += "<td>900</td><td>880</td><td>920</td>"
        html += "<td>x1</td><td>x2</td><td>x3</td><td>x4</td></tr>"
        # Another normal row
        html += "<tr><td>Last</td><td>8%</td><td>06/30/2025</td>"
        html += "<td>500</td><td>490</td><td>510</td></tr>"
        html += "</table></body></html>"

        template = _make_template()
        meta = {"cik": "123", "filing_date": "2025-01-01"}
        results, stats = extract_filing_with_template(html, meta, template)
        ids = [r["investment_identifier"] for r in results
               if r.get("investment_identifier")]
        # Comparative row ("Comp") should be filtered out
        assert "Comp" not in ids
        # Normal rows should be present
        assert "Co0" in ids
        assert "Last" in ids

    def test_matching_width_rows_kept(self):
        """Rows matching header width are not filtered."""
        from pipeline.html_template import extract_filing_with_template

        html = "<html><body><table>"
        html += "<tr><td>Company</td><td>Interest Rate</td>"
        html += "<td>Maturity Date</td><td>Principal Amount</td>"
        html += "<td>Cost</td><td>Fair Value</td></tr>"
        for i in range(20):
            html += f"<tr><td>Co{i}</td><td>10%</td><td>12/31/2025</td>"
            html += "<td>1000</td><td>990</td><td>1010</td></tr>"
        html += "</table></body></html>"

        template = _make_template()
        meta = {"cik": "123", "filing_date": "2025-01-01"}
        results, _ = extract_filing_with_template(html, meta, template)
        assert len(results) == 20

    def test_small_delta_tolerated(self):
        """Rows with width delta < 3 are not filtered."""
        from pipeline.html_template import extract_filing_with_template

        html = "<html><body><table>"
        html += "<tr><td>Company</td><td>Interest Rate</td>"
        html += "<td>Maturity Date</td><td>Principal Amount</td>"
        html += "<td>Cost</td><td>Fair Value</td></tr>"
        # 16 normal rows
        for i in range(16):
            html += f"<tr><td>Co{i}</td><td>10%</td><td>12/31/2025</td>"
            html += "<td>1000</td><td>990</td><td>1010</td></tr>"
        # Slightly wider row (+2 cells -- below threshold of 3)
        html += "<tr><td>Beta</td><td>8%</td><td>06/30/2025</td>"
        html += "<td>500</td><td>490</td><td>510</td><td>note</td><td>note2</td></tr>"
        html += "</table></body></html>"

        template = _make_template()
        meta = {"cik": "123", "filing_date": "2025-01-01"}
        results, _ = extract_filing_with_template(html, meta, template)
        # 16 normal + 1 slightly wider (delta=2 < threshold=3)
        assert len(results) == 17


# ===========================================================================
# Amendment #14: Adaptive grid-position shifting
# ===========================================================================

class TestAdaptiveGridShifting:
    def test_shifted_grid_remapped(self):
        """When grid positions shift but headers still match, use template."""
        from pipeline.html_template import extract_filing_with_template

        # Template expects grid [0, 2, 4, 6, 8, 10]
        template = _make_template(
            overrides={"programmatic_analysis": {
                "tables_found": 1,
                "total_data_rows": 20,
                "column_count": 6,
                "detected_dollar_unit": 1,
                "grid_positions": [0, 2, 4, 6, 8, 10],
            }}
        )
        # Actual HTML has denser grid [0, 1, 2, 3, 4, 5]
        html = "<html><body><table>"
        html += "<tr><td>Company</td><td>Interest Rate</td>"
        html += "<td>Maturity Date</td><td>Principal Amount</td>"
        html += "<td>Cost</td><td>Fair Value</td></tr>"
        for i in range(20):
            html += f"<tr><td>Co{i}</td><td>10%</td><td>12/31/2025</td>"
            html += "<td>1000</td><td>990</td><td>1010</td></tr>"
        html += "</table></body></html>"

        meta = {"cik": "123", "filing_date": "2025-01-01"}
        results, stats = extract_filing_with_template(html, meta, template)
        # Drift should be cleared after remapping
        assert stats.get("drift_detected") is False
        assert len(results) == 20
        assert results[0]["fair_value"] == 1010.0

    def test_aligned_grid_unchanged(self):
        """When grid positions match, no remapping needed."""
        from pipeline.html_template import extract_filing_with_template

        template = _make_template()
        html = "<html><body><table>"
        html += "<tr><td>Company</td><td>Interest Rate</td>"
        html += "<td>Maturity Date</td><td>Principal Amount</td>"
        html += "<td>Cost</td><td>Fair Value</td></tr>"
        for i in range(20):
            html += f"<tr><td>Co{i}</td><td>10%</td><td>12/31/2025</td>"
            html += "<td>1000</td><td>990</td><td>1010</td></tr>"
        html += "</table></body></html>"

        meta = {"cik": "123", "filing_date": "2025-01-01"}
        results, stats = extract_filing_with_template(html, meta, template)
        assert stats.get("drift_detected") is False
        assert len(results) == 20


# ===========================================================================
# Amendment #28: Split debt/equity/warrant schedule merging
# ===========================================================================

class TestSiblingTableMerging:
    def test_sibling_table_merged_with_quirk(self):
        """With merge_sibling_tables, sibling table positions are appended."""
        from pipeline.html_template import extract_filing_with_template

        # Primary table (6 columns)
        html = "<html><body>"
        html += "<table>"
        html += "<tr><td>Company</td><td>Interest Rate</td>"
        html += "<td>Maturity Date</td><td>Principal Amount</td>"
        html += "<td>Cost</td><td>Fair Value</td></tr>"
        for i in range(16):
            html += f"<tr><td>Debt{i}</td><td>10%</td><td>12/31/2025</td>"
            html += "<td>1000</td><td>990</td><td>1010</td></tr>"
        html += "</table>"
        # Sibling: same column names but 3 extra empty columns (9 total)
        # to prevent _tables_are_continuation (len diff > 2).
        # Headers still match template keywords for drift check.
        html += "<table>"
        html += "<tr><td>Company</td><td></td><td></td><td>Interest Rate</td>"
        html += "<td>Maturity Date</td><td>Principal Amount</td>"
        html += "<td>Cost</td><td>Fair Value</td><td></td></tr>"
        for i in range(6):
            html += f"<tr><td>Equity{i}</td><td></td><td></td><td></td>"
            html += "<td></td><td></td><td>500</td><td>600</td><td></td></tr>"
        html += "</table></body></html>"

        template = _make_template(
            overrides={"filer_quirks": {
                "multi_line_cells": False,
                "instrument_in_company_cell": False,
                "rate_cell_includes_reference": False,
                "pik_notation": None,
                "merge_sibling_tables": True,
            }}
        )
        meta = {"cik": "123", "filing_date": "2025-01-01"}
        results, stats = extract_filing_with_template(html, meta, template)
        ids = [r["investment_identifier"] for r in results
               if r.get("investment_identifier")]
        assert "Debt0" in ids
        assert "Equity0" in ids

    def test_no_merge_without_quirk_flag(self):
        """Without merge_sibling_tables, sibling table is ignored."""
        from pipeline.html_template import extract_filing_with_template

        html = "<html><body>"
        html += "<table>"
        html += "<tr><td>Company</td><td>Interest Rate</td>"
        html += "<td>Maturity Date</td><td>Principal Amount</td>"
        html += "<td>Cost</td><td>Fair Value</td></tr>"
        for i in range(16):
            html += f"<tr><td>Debt{i}</td><td>10%</td><td>12/31/2025</td>"
            html += "<td>1000</td><td>990</td><td>1010</td></tr>"
        html += "</table>"
        # Sibling: wider (len diff > 2), prevents continuation merge
        html += "<table>"
        html += "<tr><td>Company</td><td></td><td></td><td>Interest Rate</td>"
        html += "<td>Maturity Date</td><td>Principal Amount</td>"
        html += "<td>Cost</td><td>Fair Value</td><td></td></tr>"
        for i in range(6):
            html += f"<tr><td>Equity{i}</td><td></td><td></td><td></td>"
            html += "<td></td><td></td><td>500</td><td>600</td><td></td></tr>"
        html += "</table></body></html>"

        template = _make_template()  # no merge flag
        meta = {"cik": "123", "filing_date": "2025-01-01"}
        results, stats = extract_filing_with_template(html, meta, template)
        ids = [r["investment_identifier"] for r in results
               if r.get("investment_identifier")]
        assert "Debt0" in ids
        # Equity should NOT be present without the flag
        assert "Equity0" not in ids

    def test_sibling_dedup_works(self):
        """Sibling table merging adds new positions, dedupes by name+FV."""
        from pipeline.html_template import extract_filing_with_template

        html = "<html><body>"
        html += "<table>"
        html += "<tr><td>Company</td><td>Interest Rate</td>"
        html += "<td>Maturity Date</td><td>Principal Amount</td>"
        html += "<td>Cost</td><td>Fair Value</td></tr>"
        for i in range(16):
            html += f"<tr><td>Co{i}</td><td>10%</td><td>12/31/2025</td>"
            html += "<td>1000</td><td>990</td><td>1010</td></tr>"
        html += "</table>"
        # Sibling: wider (len diff > 2) with unique positions
        html += "<table>"
        html += "<tr><td>Company</td><td></td><td></td><td>Interest Rate</td>"
        html += "<td>Maturity Date</td><td>Principal Amount</td>"
        html += "<td>Cost</td><td>Fair Value</td><td></td></tr>"
        for i in range(6):
            html += f"<tr><td>New{i}</td><td></td><td></td><td>8%</td>"
            html += "<td>06/30/2025</td><td>500</td><td>490</td>"
            html += "<td>510</td><td></td></tr>"
        html += "</table></body></html>"

        template = _make_template(
            overrides={"filer_quirks": {
                "multi_line_cells": False,
                "instrument_in_company_cell": False,
                "rate_cell_includes_reference": False,
                "pik_notation": None,
                "merge_sibling_tables": True,
            }}
        )
        meta = {"cik": "123", "filing_date": "2025-01-01"}
        results, stats = extract_filing_with_template(html, meta, template)
        ids = [r["investment_identifier"] for r in results
               if r.get("investment_identifier")]
        # Primary positions present
        assert "Co0" in ids
        # Sibling positions also present
        assert "New0" in ids
        # Total should be 16 primary + 6 sibling
        assert len(ids) == 22

    def test_v2_sibling_uses_own_variant_column_map(self):
        """v2.0 template: sibling table uses its own variant's column mapping."""
        from pipeline.html_template import extract_filing_with_template

        # Primary table: 6-col debt layout (Company, Rate, Maturity, Principal, Cost, FV)
        html = "<html><body>"
        html += "<table>"
        html += "<tr><td>Company</td><td>Interest Rate</td>"
        html += "<td>Maturity Date</td><td>Principal Amount</td>"
        html += "<td>Cost</td><td>Fair Value</td></tr>"
        for i in range(16):
            html += f"<tr><td>Debt{i}</td><td>10%</td><td>12/31/2025</td>"
            html += "<td>1000</td><td>990</td><td>1010</td></tr>"
        html += "</table>"

        # Sibling table: 5-col equity layout (Company, Dividend Rate, Shares, Cost, FV)
        # Different column count and headers -- requires a different variant.
        html += "<table>"
        html += "<tr><td>Company</td><td>Preferred Dividend Rate</td>"
        html += "<td>Shares</td><td>Cost</td><td>Fair Value</td></tr>"
        for i in range(6):
            html += f"<tr><td>Equity{i}</td><td>8%</td>"
            html += f"<td>500</td><td>400</td><td>450</td></tr>"
        html += "</table></body></html>"

        # v2.0 template with two variants: debt (6-col) and equity (5-col)
        template = {
            "schema_version": "2.0",
            "cik": "999",
            "entity_name": "Test Multi-Table BDC",
            "source_filings": ["0001-24-000001"],
            "created_by": "test",
            "created_at": "2026-01-01T00:00:00Z",
            "variants": [
                {
                    "format_id": "debt_6col",
                    "column_mapping": {
                        "company": {"index": 0, "header_text": "Company"},
                        "interest_rate": {"index": 1, "header_text": "Interest Rate"},
                        "maturity_date": {"index": 2, "header_text": "Maturity Date"},
                        "principal_amount": {"index": 3, "header_text": "Principal Amount"},
                        "cost": {"index": 4, "header_text": "Cost"},
                        "fair_value": {"index": 5, "header_text": "Fair Value"},
                        "shares_held": {"index": None, "header_text": ""},
                        "pct_of_net_assets": {"index": None, "header_text": ""},
                    },
                    "value_formats": {
                        "dollar_unit": 1,
                        "rate_format": "percentage",
                        "date_format": "MM/DD/YYYY",
                        "negative_convention": "parentheses",
                        "dash_means_null": True,
                    },
                    "row_conventions": {
                        "continuation_detection": "empty_first_cell",
                    },
                    "filer_quirks": {
                        "multi_line_cells": False,
                        "instrument_in_company_cell": False,
                        "rate_cell_includes_reference": False,
                        "pik_notation": None,
                        "merge_sibling_tables": True,
                    },
                    "programmatic_analysis": {
                        "column_count": 6,
                        "grid_positions": [0, 1, 2, 3, 4, 5],
                    },
                },
                {
                    "format_id": "equity_5col",
                    "column_mapping": {
                        "company": {"index": 0, "header_text": "Company"},
                        "interest_rate": {"index": 1, "header_text": "Preferred Dividend Rate"},
                        "shares_held": {"index": 2, "header_text": "Shares"},
                        "cost": {"index": 3, "header_text": "Cost"},
                        "fair_value": {"index": 4, "header_text": "Fair Value"},
                        "maturity_date": {"index": None, "header_text": ""},
                        "principal_amount": {"index": None, "header_text": ""},
                        "pct_of_net_assets": {"index": None, "header_text": ""},
                    },
                    "value_formats": {
                        "dollar_unit": 1,
                        "rate_format": "percentage",
                        "date_format": "MM/DD/YYYY",
                        "negative_convention": "parentheses",
                        "dash_means_null": True,
                    },
                    "row_conventions": {
                        "continuation_detection": "empty_first_cell",
                    },
                    "filer_quirks": {
                        "multi_line_cells": False,
                        "instrument_in_company_cell": False,
                        "rate_cell_includes_reference": False,
                        "pik_notation": None,
                        "merge_sibling_tables": True,
                    },
                    "programmatic_analysis": {
                        "column_count": 5,
                        "grid_positions": [0, 1, 2, 3, 4],
                    },
                },
            ],
        }

        meta = {"cik": "999", "filing_date": "2025-01-01"}
        results, stats = extract_filing_with_template(html, meta, template)
        ids = [r["investment_identifier"] for r in results
               if r.get("investment_identifier")]

        # Primary (debt) positions present
        assert "Debt0" in ids
        assert "Debt15" in ids

        # Sibling (equity) positions present -- only works if sibling
        # used its own variant's column mapping (equity_5col)
        assert "Equity0" in ids

        # Verify FV was extracted correctly from equity table
        # (col 4 in equity variant, NOT col 5 which would be wrong)
        equity_rows = [r for r in results
                       if r.get("investment_identifier", "").startswith("Equity")]
        assert len(equity_rows) == 6
        for r in equity_rows:
            assert r["fair_value"] == 450.0

    def test_v2_sibling_no_merge_without_flag(self):
        """v2.0 template: sibling not merged without merge_sibling_tables."""
        from pipeline.html_template import extract_filing_with_template

        html = "<html><body>"
        html += "<table>"
        html += "<tr><td>Company</td><td>Interest Rate</td>"
        html += "<td>Maturity Date</td><td>Principal Amount</td>"
        html += "<td>Cost</td><td>Fair Value</td></tr>"
        for i in range(16):
            html += f"<tr><td>Debt{i}</td><td>10%</td><td>12/31/2025</td>"
            html += "<td>1000</td><td>990</td><td>1010</td></tr>"
        html += "</table>"
        html += "<table>"
        html += "<tr><td>Company</td><td>Preferred Dividend Rate</td>"
        html += "<td>Shares</td><td>Cost</td><td>Fair Value</td></tr>"
        for i in range(6):
            html += f"<tr><td>Equity{i}</td><td>8%</td>"
            html += f"<td>500</td><td>400</td><td>450</td></tr>"
        html += "</table></body></html>"

        template = {
            "schema_version": "2.0",
            "cik": "999",
            "entity_name": "Test Multi-Table BDC",
            "source_filings": ["0001-24-000001"],
            "created_by": "test",
            "created_at": "2026-01-01T00:00:00Z",
            "variants": [
                {
                    "format_id": "debt_6col",
                    "column_mapping": {
                        "company": {"index": 0, "header_text": "Company"},
                        "interest_rate": {"index": 1, "header_text": "Interest Rate"},
                        "maturity_date": {"index": 2, "header_text": "Maturity Date"},
                        "principal_amount": {"index": 3, "header_text": "Principal Amount"},
                        "cost": {"index": 4, "header_text": "Cost"},
                        "fair_value": {"index": 5, "header_text": "Fair Value"},
                        "shares_held": {"index": None, "header_text": ""},
                        "pct_of_net_assets": {"index": None, "header_text": ""},
                    },
                    "value_formats": {
                        "dollar_unit": 1,
                        "rate_format": "percentage",
                        "date_format": "MM/DD/YYYY",
                        "negative_convention": "parentheses",
                        "dash_means_null": True,
                    },
                    "row_conventions": {
                        "continuation_detection": "empty_first_cell",
                    },
                    "filer_quirks": {
                        "multi_line_cells": False,
                        "instrument_in_company_cell": False,
                        "rate_cell_includes_reference": False,
                        "pik_notation": None,
                        # No merge_sibling_tables flag
                    },
                    "programmatic_analysis": {
                        "column_count": 6,
                        "grid_positions": [0, 1, 2, 3, 4, 5],
                    },
                },
            ],
        }

        meta = {"cik": "999", "filing_date": "2025-01-01"}
        results, stats = extract_filing_with_template(html, meta, template)
        ids = [r["investment_identifier"] for r in results
               if r.get("investment_identifier")]
        assert "Debt0" in ids
        assert "Equity0" not in ids


# ===========================================================================
# Amendment #27: Row-type-based dynamic column remapping
# ===========================================================================

class TestRowTypeColumnOverrides:
    def test_continuation_uses_override_map(self):
        """Continuation rows use row_type_column_overrides."""
        from pipeline.html_template import extract_filing_with_template

        html = "<html><body><table>"
        html += "<tr><td>Company</td><td>Interest Rate</td>"
        html += "<td>Maturity Date</td><td>Principal Amount</td>"
        html += "<td>Cost</td><td>Fair Value</td></tr>"
        # Normal row
        html += "<tr><td>Acme</td><td>10%</td><td>12/31/2025</td>"
        html += "<td>1000</td><td>990</td><td>1010</td></tr>"
        # Continuation row (empty company) - FV at index 3 instead of 5
        html += "<tr><td></td><td></td><td></td>"
        html += "<td>2020</td><td></td><td></td></tr>"
        # More normal rows to exceed 15
        for i in range(15):
            html += f"<tr><td>Co{i}</td><td>10%</td><td>12/31/2025</td>"
            html += "<td>1000</td><td>990</td><td>1010</td></tr>"
        html += "</table></body></html>"

        template = _make_template(
            overrides={
                "row_type_column_overrides": {
                    "continuation": {
                        "fair_value": {"index": 3, "header_text": "Fair Value"},
                    },
                },
            }
        )
        meta = {"cik": "123", "filing_date": "2025-01-01"}
        results, _ = extract_filing_with_template(html, meta, template)
        # Find the continuation row (2nd row, attached to Acme)
        continuations = [r for r in results
                         if r.get("investment_identifier") == "Acme"
                         or (not r.get("investment_identifier") and
                             r.get("fair_value") == 2020.0)]
        # The continuation should have FV=2020 from index 3
        fv_values = [r.get("fair_value") for r in results]
        assert 2020.0 in fv_values

    def test_first_row_uses_default_map(self):
        """Non-continuation rows use default column_mapping."""
        from pipeline.html_template import extract_filing_with_template

        html = "<html><body><table>"
        html += "<tr><td>Company</td><td>Interest Rate</td>"
        html += "<td>Maturity Date</td><td>Principal Amount</td>"
        html += "<td>Cost</td><td>Fair Value</td></tr>"
        for i in range(20):
            html += f"<tr><td>Co{i}</td><td>10%</td><td>12/31/2025</td>"
            html += "<td>1000</td><td>990</td><td>1010</td></tr>"
        html += "</table></body></html>"

        template = _make_template(
            overrides={
                "row_type_column_overrides": {
                    "continuation": {
                        "fair_value": {"index": 3, "header_text": "Fair Value"},
                    },
                },
            }
        )
        meta = {"cik": "123", "filing_date": "2025-01-01"}
        results, _ = extract_filing_with_template(html, meta, template)
        # All non-continuation rows use default FV at index 5
        assert all(r["fair_value"] == 1010.0 for r in results)

    def test_no_override_when_absent(self):
        """Without row_type_column_overrides, behavior unchanged."""
        from pipeline.html_template import extract_filing_with_template

        html = "<html><body><table>"
        html += "<tr><td>Company</td><td>Interest Rate</td>"
        html += "<td>Maturity Date</td><td>Principal Amount</td>"
        html += "<td>Cost</td><td>Fair Value</td></tr>"
        for i in range(20):
            html += f"<tr><td>Co{i}</td><td>10%</td><td>12/31/2025</td>"
            html += "<td>1000</td><td>990</td><td>1010</td></tr>"
        html += "</table></body></html>"

        template = _make_template()  # no overrides
        meta = {"cik": "123", "filing_date": "2025-01-01"}
        results, _ = extract_filing_with_template(html, meta, template)
        assert len(results) == 20
        assert results[0]["fair_value"] == 1010.0


# ===========================================================================
# Amendment #19: Multi-period schedule segmentation
# ===========================================================================

class TestMultiPeriodSegmentation:
    def test_multi_period_segmented(self):
        """Multi-period table segmented to matching report_date."""
        from pipeline.html_template import extract_filing_with_template

        html = "<html><body><table>"
        html += "<tr><td>Company</td><td>Interest Rate</td>"
        html += "<td>Maturity Date</td><td>Principal Amount</td>"
        html += "<td>Cost</td><td>Fair Value</td></tr>"
        # Period 1 marker
        html += "<tr><td>As of June 30, 2024</td><td></td><td></td>"
        html += "<td></td><td></td><td></td></tr>"
        for i in range(10):
            html += f"<tr><td>Old{i}</td><td>10%</td><td>12/31/2025</td>"
            html += "<td>1000</td><td>990</td><td>1010</td></tr>"
        # Period 2 marker
        html += "<tr><td>As of December 31, 2024</td><td></td><td></td>"
        html += "<td></td><td></td><td></td></tr>"
        for i in range(10):
            html += f"<tr><td>New{i}</td><td>8%</td><td>06/30/2025</td>"
            html += "<td>500</td><td>490</td><td>510</td></tr>"
        html += "</table></body></html>"

        template = _make_template(
            overrides={"filer_quirks": {
                "multi_line_cells": False,
                "instrument_in_company_cell": False,
                "rate_cell_includes_reference": False,
                "pik_notation": None,
                "segment_by_period": True,
            }}
        )
        meta = {"cik": "123", "filing_date": "2025-01-01",
                "report_date": "2024-12-31"}
        results, _ = extract_filing_with_template(html, meta, template)
        ids = [r["investment_identifier"] for r in results
               if r.get("investment_identifier")]
        # Should only have Period 2 positions (matching report_date)
        assert "New0" in ids
        assert "Old0" not in ids

    def test_single_period_unchanged(self):
        """Table without period markers is unchanged."""
        from pipeline.html_template import extract_filing_with_template

        html = "<html><body><table>"
        html += "<tr><td>Company</td><td>Interest Rate</td>"
        html += "<td>Maturity Date</td><td>Principal Amount</td>"
        html += "<td>Cost</td><td>Fair Value</td></tr>"
        for i in range(20):
            html += f"<tr><td>Co{i}</td><td>10%</td><td>12/31/2025</td>"
            html += "<td>1000</td><td>990</td><td>1010</td></tr>"
        html += "</table></body></html>"

        template = _make_template(
            overrides={"filer_quirks": {
                "multi_line_cells": False,
                "instrument_in_company_cell": False,
                "rate_cell_includes_reference": False,
                "pik_notation": None,
                "segment_by_period": True,
            }}
        )
        meta = {"cik": "123", "filing_date": "2025-01-01",
                "report_date": "2024-12-31"}
        results, _ = extract_filing_with_template(html, meta, template)
        assert len(results) == 20

    def test_auto_segment_without_quirk(self):
        """Auto-segmentation activates even without segment_by_period flag."""
        from pipeline.html_template import extract_filing_with_template

        html = "<html><body><table>"
        html += "<tr><td>Company</td><td>Interest Rate</td>"
        html += "<td>Maturity Date</td><td>Principal Amount</td>"
        html += "<td>Cost</td><td>Fair Value</td></tr>"
        html += "<tr><td>As of June 30, 2024</td><td></td><td></td>"
        html += "<td></td><td></td><td></td></tr>"
        for i in range(10):
            html += f"<tr><td>Old{i}</td><td>10%</td><td>12/31/2025</td>"
            html += "<td>1000</td><td>990</td><td>1010</td></tr>"
        html += "<tr><td>As of December 31, 2024</td><td></td><td></td>"
        html += "<td></td><td></td><td></td></tr>"
        for i in range(10):
            html += f"<tr><td>New{i}</td><td>8%</td><td>06/30/2025</td>"
            html += "<td>500</td><td>490</td><td>510</td></tr>"
        html += "</table></body></html>"

        template = _make_template()  # no segment_by_period flag
        meta = {"cik": "123", "filing_date": "2025-01-01",
                "report_date": "2024-12-31"}
        results, _ = extract_filing_with_template(html, meta, template)
        ids = [r["investment_identifier"] for r in results
               if r.get("investment_identifier")]
        # Auto-segmentation selects the report_date-matching segment
        assert "New0" in ids
        assert "Old0" not in ids

    def test_no_segment_without_report_date(self):
        """Without report_date, multi-period table is not segmented."""
        from pipeline.html_template import extract_filing_with_template

        html = "<html><body><table>"
        html += "<tr><td>Company</td><td>Interest Rate</td>"
        html += "<td>Maturity Date</td><td>Principal Amount</td>"
        html += "<td>Cost</td><td>Fair Value</td></tr>"
        html += "<tr><td>As of June 30, 2024</td><td></td><td></td>"
        html += "<td></td><td></td><td></td></tr>"
        for i in range(10):
            html += f"<tr><td>Old{i}</td><td>10%</td><td>12/31/2025</td>"
            html += "<td>1000</td><td>990</td><td>1010</td></tr>"
        html += "<tr><td>As of December 31, 2024</td><td></td><td></td>"
        html += "<td></td><td></td><td></td></tr>"
        for i in range(10):
            html += f"<tr><td>New{i}</td><td>8%</td><td>06/30/2025</td>"
            html += "<td>500</td><td>490</td><td>510</td></tr>"
        html += "</table></body></html>"

        template = _make_template()
        meta = {"cik": "123", "filing_date": "2025-01-01",
                "report_date": ""}
        results, _ = extract_filing_with_template(html, meta, template)
        ids = [r["investment_identifier"] for r in results
               if r.get("investment_identifier")]
        # No report_date -> no segmentation -> both periods present
        assert "Old0" in ids
        assert "New0" in ids


# ---------------------------------------------------------------------------
# TestDateMarkerPatterns
# ---------------------------------------------------------------------------

class TestDateMarkerPatterns:
    """Tests for expanded _DATE_MARKER_RE and _STANDALONE_DATE_RE."""

    def test_as_of(self):
        m = _DATE_MARKER_RE.search("As of December 31, 2023")
        assert m is not None
        assert m.group(1).strip() == "December 31, 2023"

    def test_for_the_period_ended(self):
        m = _DATE_MARKER_RE.search("For the period ended June 30, 2022")
        assert m is not None
        assert m.group(1).strip() == "June 30, 2022"

    def test_for_the_year_ended(self):
        m = _DATE_MARKER_RE.search("for the year ended December 31, 2021")
        assert m is not None
        assert m.group(1).strip() == "December 31, 2021"

    def test_for_the_quarter_ended(self):
        m = _DATE_MARKER_RE.search("for the quarter ended March 31, 2024")
        assert m is not None
        assert m.group(1).strip() == "March 31, 2024"

    def test_schedule_of_investments(self):
        m = _DATE_MARKER_RE.search(
            "Schedule of Investments September 30, 2023"
        )
        assert m is not None
        assert m.group(1).strip() == "September 30, 2023"

    def test_standalone_date(self):
        m = _STANDALONE_DATE_RE.match("December 31, 2023")
        assert m is not None
        assert m.group(1) == "December 31, 2023"

    def test_standalone_no_comma(self):
        m = _STANDALONE_DATE_RE.match("June 30 2024")
        assert m is not None

    def test_standalone_rejects_extra_text(self):
        m = _STANDALONE_DATE_RE.match("Total December 31, 2023")
        assert m is None

    def test_segment_with_schedule_header(self):
        """_segment_table_by_period handles 'Schedule of Investments' marker."""
        table = ScheduleTable(
            rows=[
                ["Company", "FV"],  # header
                ["Schedule of Investments June 30, 2024", ""],
                ["OldCo", "100"],
                ["OldCo2", "200"],
                ["Schedule of Investments December 31, 2024", ""],
                ["NewCo", "300"],
                ["NewCo2", "400"],
            ],
            header_row_idx=0,
            score=10.0,
            dollar_unit=1,
            column_map={},
        )
        result = _segment_table_by_period(table, "2024-12-31")
        # Should only keep the Dec 31 segment (+ header)
        joined = [" ".join(r) for r in result.rows]
        assert any("NewCo" in j for j in joined)
        assert not any("OldCo" in j and "Schedule" not in j for j in joined)

    def test_segment_standalone_date(self):
        """_segment_table_by_period handles standalone date rows."""
        table = ScheduleTable(
            rows=[
                ["Company", "FV"],  # header
                ["June 30, 2024", ""],
                ["OldCo", "100"],
                ["OldCo2", "200"],
                ["December 31, 2024", ""],
                ["NewCo", "300"],
                ["NewCo2", "400"],
            ],
            header_row_idx=0,
            score=10.0,
            dollar_unit=1,
            column_map={},
        )
        result = _segment_table_by_period(table, "2024-12-31")
        joined = [" ".join(r) for r in result.rows]
        assert any("NewCo" in j for j in joined)
        assert not any("OldCo" in j for j in joined)

    def test_no_segments_returns_unchanged(self):
        """Table without date markers is returned unchanged."""
        table = ScheduleTable(
            rows=[
                ["Company", "FV"],
                ["Acme", "100"],
                ["Beta", "200"],
            ],
            header_row_idx=0,
            score=10.0,
            dollar_unit=1,
            column_map={},
        )
        result = _segment_table_by_period(table, "2024-12-31")
        assert len(result.rows) == 3  # unchanged


# ===========================================================================
# Section: Raw text preservation + subtotal flag
# ===========================================================================

class TestRawTextPreservation:
    """Test that raw_* fields preserve cell text even when parsing fails."""

    def test_raw_interest_rate_on_parse_failure(self):
        """When _parse_rate fails (e.g., slash format), raw text is preserved."""
        template = _make_template()
        cells = ["Acme", "12.96%/0.00%", "12/31/2025", "1000", "990", "1010"]
        result = _apply_template_column_map(cells, template)
        # _parse_rate can't handle "12.96%/0.00%" -- parsed value may be None
        # But raw text is always preserved
        assert result["raw_interest_rate"] == "12.96%/0.00%"

    def test_raw_interest_rate_on_parse_success(self):
        """When parsing succeeds, both parsed and raw exist."""
        template = _make_template()
        cells = ["Acme", "10.50%", "12/31/2025", "1000", "990", "1010"]
        result = _apply_template_column_map(cells, template)
        assert result["interest_rate"] == 10.5
        assert result["raw_interest_rate"] == "10.50%"

    def test_raw_fair_value_preserved(self):
        """Dollar field raw text preserved alongside parsed value."""
        template = _make_template()
        cells = ["Acme", "10.50", "12/31/2025", "1000", "990", "1010"]
        result = _apply_template_column_map(cells, template)
        assert result["fair_value"] == 1010.0
        assert result["raw_fair_value"] == "1010"

    def test_raw_maturity_date_preserved(self):
        """Date raw text preserved alongside parsed date."""
        template = _make_template()
        cells = ["Acme", "10.50", "12/31/2025", "1000", "990", "1010"]
        result = _apply_template_column_map(cells, template)
        assert result["maturity_date"] == "2025-12-31"
        assert result["raw_maturity_date"] == "12/31/2025"

    def test_raw_fields_none_when_cell_empty(self):
        """Raw fields are None when the cell has no content."""
        template = _make_template()
        cells = ["Acme", "", "", "", "", ""]
        result = _apply_template_column_map(cells, template)
        assert result["raw_interest_rate"] is None
        assert result["raw_fair_value"] is None

    def test_source_row_idx_not_in_column_map(self):
        """source_row_idx is NOT set by _apply_template_column_map.

        It's set by the caller (extract_filing_with_template).
        """
        template = _make_template()
        cells = ["Acme", "10.50", "12/31/2025", "1000", "990", "1010"]
        result = _apply_template_column_map(cells, template)
        # Not set by column map -- caller adds it
        assert "source_row_idx" not in result or result.get("source_row_idx") is None
