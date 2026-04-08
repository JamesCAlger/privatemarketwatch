"""Tests for pipeline.bdc_fund_income module.

Covers:
- Context parsing (duration vs instant, dimensioned vs entity-level)
- Fact extraction (concept matching, numeric parsing)
- Quarterly derivation (scaling by duration)
- Dedup (prefer shortest duration, then 10-K)
- Integration (end-to-end from XBRL fixture)
"""

import io
import tempfile
from pathlib import Path

import pandas as pd
import pytest
from lxml import etree

from pipeline.bdc_fund_income import (
    FUND_INCOME_CONCEPT_MAP,
    INCOME_COLUMNS,
    _derive_quarterly_income,
    _extract_fund_income_facts,
    _local_name,
    _match_income_concept,
    _parse_income_contexts,
    extract_bdc_fund_income,
)


# ---------------------------------------------------------------------------
# Helper: minimal XBRL XML builder
# ---------------------------------------------------------------------------

def _build_xbrl(contexts_xml: str, facts_xml: str) -> etree._ElementTree:
    """Build a minimal XBRL document for testing."""
    xml = f"""<?xml version="1.0" encoding="utf-8"?>
    <xbrli:xbrl
        xmlns:xbrli="http://www.xbrl.org/2003/instance"
        xmlns:cef="http://xbrl.sec.gov/cef/2024"
        xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
        {contexts_xml}
        {facts_xml}
    </xbrli:xbrl>
    """
    return etree.parse(io.BytesIO(xml.encode("utf-8")))


def _duration_ctx(ctx_id: str, start: str, end: str,
                  with_dimension: bool = False) -> str:
    """Build a duration context XML snippet."""
    dim_xml = ""
    if with_dimension:
        dim_xml = """
        <xbrli:entity>
            <xbrli:identifier scheme="http://www.sec.gov/CIK">0001234567</xbrli:identifier>
            <xbrli:segment>
                <xbrli:explicitMember dimension="us-gaap:StatementScenarioAxis">
                    us-gaap:ScenarioMember
                </xbrli:explicitMember>
            </xbrli:segment>
        </xbrli:entity>
        """
    else:
        dim_xml = """
        <xbrli:entity>
            <xbrli:identifier scheme="http://www.sec.gov/CIK">0001234567</xbrli:identifier>
        </xbrli:entity>
        """
    return f"""
    <xbrli:context id="{ctx_id}">
        {dim_xml}
        <xbrli:period>
            <xbrli:startDate>{start}</xbrli:startDate>
            <xbrli:endDate>{end}</xbrli:endDate>
        </xbrli:period>
    </xbrli:context>
    """


def _instant_ctx(ctx_id: str, instant_date: str) -> str:
    """Build an instant context XML snippet."""
    return f"""
    <xbrli:context id="{ctx_id}">
        <xbrli:entity>
            <xbrli:identifier scheme="http://www.sec.gov/CIK">0001234567</xbrli:identifier>
        </xbrli:entity>
        <xbrli:period>
            <xbrli:instant>{instant_date}</xbrli:instant>
        </xbrli:period>
    </xbrli:context>
    """


def _fact(concept: str, ctx_ref: str, value: str) -> str:
    """Build a fact element XML snippet."""
    return f'<cef:{concept} contextRef="{ctx_ref}">{value}</cef:{concept}>'


# ---------------------------------------------------------------------------
# Context parsing tests
# ---------------------------------------------------------------------------

class TestContextParsing:
    def test_entity_level_duration_context(self):
        """Entity-level duration context is parsed correctly."""
        ctx_xml = _duration_ctx("d_q1", "2024-01-01", "2024-03-31")
        tree = _build_xbrl(ctx_xml, "")
        contexts = _parse_income_contexts(tree)
        assert "d_q1" in contexts
        assert contexts["d_q1"]["start_date"] == "2024-01-01"
        assert contexts["d_q1"]["end_date"] == "2024-03-31"
        assert contexts["d_q1"]["duration_months"] == 3
        assert contexts["d_q1"]["has_dimensions"] is False

    def test_dimensioned_context_flagged(self):
        """Context with dimensions has has_dimensions=True."""
        ctx_xml = _duration_ctx("d_dim", "2024-01-01", "2024-03-31",
                                with_dimension=True)
        tree = _build_xbrl(ctx_xml, "")
        contexts = _parse_income_contexts(tree)
        assert "d_dim" in contexts
        assert contexts["d_dim"]["has_dimensions"] is True

    def test_instant_context_ignored(self):
        """Instant contexts are not included (income is a flow concept)."""
        ctx_xml = _instant_ctx("i1", "2024-03-31")
        tree = _build_xbrl(ctx_xml, "")
        contexts = _parse_income_contexts(tree)
        assert "i1" not in contexts

    def test_annual_duration(self):
        """Annual context has ~12 month duration."""
        ctx_xml = _duration_ctx("d_annual", "2024-01-01", "2024-12-31")
        tree = _build_xbrl(ctx_xml, "")
        contexts = _parse_income_contexts(tree)
        assert contexts["d_annual"]["duration_months"] == 12

    def test_ytd_6month(self):
        """6-month YTD context."""
        ctx_xml = _duration_ctx("d_ytd6", "2024-01-01", "2024-06-30")
        tree = _build_xbrl(ctx_xml, "")
        contexts = _parse_income_contexts(tree)
        assert contexts["d_ytd6"]["duration_months"] == 6

    def test_multiple_contexts(self):
        """Multiple contexts are all parsed."""
        ctx_xml = (
            _duration_ctx("q1", "2024-01-01", "2024-03-31")
            + _duration_ctx("q2", "2024-04-01", "2024-06-30")
            + _instant_ctx("i1", "2024-03-31")
        )
        tree = _build_xbrl(ctx_xml, "")
        contexts = _parse_income_contexts(tree)
        assert len(contexts) == 2
        assert "q1" in contexts and "q2" in contexts


# ---------------------------------------------------------------------------
# Fact extraction tests
# ---------------------------------------------------------------------------

class TestFactExtraction:
    def test_gross_investment_income(self):
        """Total investment income concept extracted."""
        ctx_xml = _duration_ctx("d1", "2024-01-01", "2024-03-31")
        facts_xml = _fact("GrossInvestmentIncomeOperating", "d1", "50000000")
        tree = _build_xbrl(ctx_xml, facts_xml)
        contexts = _parse_income_contexts(tree)
        facts = _extract_fund_income_facts(tree, contexts)
        assert len(facts) == 1
        assert facts[0]["total_investment_income"] == 50000000.0

    def test_net_investment_income(self):
        """Net investment income concept extracted."""
        ctx_xml = _duration_ctx("d1", "2024-01-01", "2024-03-31")
        facts_xml = _fact("NetInvestmentIncome", "d1", "30000000")
        tree = _build_xbrl(ctx_xml, facts_xml)
        contexts = _parse_income_contexts(tree)
        facts = _extract_fund_income_facts(tree, contexts)
        assert len(facts) == 1
        assert facts[0]["net_investment_income"] == 30000000.0

    def test_alt_net_income_concept(self):
        """investmentincomenet also maps to net_investment_income."""
        ctx_xml = _duration_ctx("d1", "2024-01-01", "2024-03-31")
        facts_xml = _fact("InvestmentIncomeNet", "d1", "25000000")
        tree = _build_xbrl(ctx_xml, facts_xml)
        contexts = _parse_income_contexts(tree)
        facts = _extract_fund_income_facts(tree, contexts)
        assert len(facts) == 1
        assert facts[0]["net_investment_income"] == 25000000.0

    def test_interest_income(self):
        """Interest income concept."""
        ctx_xml = _duration_ctx("d1", "2024-01-01", "2024-03-31")
        facts_xml = _fact("InvestmentIncomeInterest", "d1", "40000000")
        tree = _build_xbrl(ctx_xml, facts_xml)
        contexts = _parse_income_contexts(tree)
        facts = _extract_fund_income_facts(tree, contexts)
        assert facts[0]["interest_income"] == 40000000.0

    def test_multiple_periods(self):
        """Facts from multiple periods produce separate records."""
        ctx_xml = (
            _duration_ctx("q1", "2024-01-01", "2024-03-31")
            + _duration_ctx("q2", "2024-04-01", "2024-06-30")
        )
        facts_xml = (
            _fact("GrossInvestmentIncomeOperating", "q1", "50000000")
            + _fact("GrossInvestmentIncomeOperating", "q2", "55000000")
        )
        tree = _build_xbrl(ctx_xml, facts_xml)
        contexts = _parse_income_contexts(tree)
        facts = _extract_fund_income_facts(tree, contexts)
        assert len(facts) == 2

    def test_dimensioned_context_excluded(self):
        """Facts in dimensioned contexts are excluded."""
        ctx_xml = (
            _duration_ctx("d_entity", "2024-01-01", "2024-03-31")
            + _duration_ctx("d_dim", "2024-01-01", "2024-03-31",
                          with_dimension=True)
        )
        facts_xml = (
            _fact("GrossInvestmentIncomeOperating", "d_entity", "50000000")
            + _fact("GrossInvestmentIncomeOperating", "d_dim", "99999999")
        )
        tree = _build_xbrl(ctx_xml, facts_xml)
        contexts = _parse_income_contexts(tree)
        facts = _extract_fund_income_facts(tree, contexts)
        assert len(facts) == 1
        assert facts[0]["total_investment_income"] == 50000000.0

    def test_nil_elements_skipped(self):
        """Elements with xsi:nil='true' are skipped."""
        ctx_xml = _duration_ctx("d1", "2024-01-01", "2024-03-31")
        facts_xml = (
            '<cef:GrossInvestmentIncomeOperating contextRef="d1" '
            'xsi:nil="true"/>'
        )
        tree = _build_xbrl(ctx_xml, facts_xml)
        contexts = _parse_income_contexts(tree)
        facts = _extract_fund_income_facts(tree, contexts)
        assert len(facts) == 0


# ---------------------------------------------------------------------------
# Quarterly derivation tests
# ---------------------------------------------------------------------------

class TestQuarterlyDerivation:
    def test_direct_quarterly(self):
        """3-month duration used as-is (scale=1)."""
        raw = [{"start_date": "2024-01-01", "end_date": "2024-03-31",
                "duration_months": 3,
                "total_investment_income": 50000000.0}]
        meta = {"cik": "123", "entity_name": "Test BDC",
                "form_type": "10-Q", "accession_number": "000-00-000001"}
        result = _derive_quarterly_income(raw, meta)
        assert len(result) == 1
        assert result[0]["total_investment_income"] == 50000000.0
        assert result[0]["report_quarter"] == "2024q1"

    def test_annual_divided_by_4(self):
        """12-month duration divided by 4."""
        raw = [{"start_date": "2024-01-01", "end_date": "2024-12-31",
                "duration_months": 12,
                "total_investment_income": 200000000.0}]
        meta = {"cik": "123", "entity_name": "Test BDC",
                "form_type": "10-K", "accession_number": "000-00-000002"}
        result = _derive_quarterly_income(raw, meta)
        assert len(result) == 1
        # 12 months is in 11-13 range -> scale = 1/4
        expected = 200000000.0 / 4.0
        assert abs(result[0]["total_investment_income"] - expected) < 1
        assert result[0]["report_quarter"] == "2024q4"

    def test_semiannual_scaled(self):
        """6-month duration: scale = 3/6 = 0.5."""
        raw = [{"start_date": "2024-01-01", "end_date": "2024-06-30",
                "duration_months": 6,
                "total_investment_income": 100000000.0}]
        meta = {"cik": "123", "entity_name": "Test BDC",
                "form_type": "10-Q", "accession_number": "000-00-000003"}
        result = _derive_quarterly_income(raw, meta)
        expected = 100000000.0 * 3.0 / 6.0
        assert abs(result[0]["total_investment_income"] - expected) < 1

    def test_zero_duration_skipped(self):
        """Zero or negative duration is skipped."""
        raw = [{"start_date": "2024-03-31", "end_date": "2024-03-31",
                "duration_months": 0,
                "total_investment_income": 50000000.0}]
        meta = {"cik": "123"}
        result = _derive_quarterly_income(raw, meta)
        assert len(result) == 0

    def test_multiple_income_cols_scaled(self):
        """All income columns are scaled together."""
        raw = [{"start_date": "2024-01-01", "end_date": "2024-03-31",
                "duration_months": 3,
                "total_investment_income": 50000000.0,
                "interest_income": 40000000.0,
                "fee_income": 5000000.0,
                "net_investment_income": 30000000.0}]
        meta = {"cik": "123"}
        result = _derive_quarterly_income(raw, meta)
        assert result[0]["interest_income"] == 40000000.0
        assert result[0]["fee_income"] == 5000000.0
        assert result[0]["net_investment_income"] == 30000000.0


# ---------------------------------------------------------------------------
# Concept matching tests
# ---------------------------------------------------------------------------

class TestConceptMatching:
    def test_gross_income_concept(self):
        assert _match_income_concept("grossinvestmentincomeoperating") == "total_investment_income"

    def test_fee_income_concept(self):
        assert _match_income_concept("feeincome") == "fee_income"

    def test_management_fee_concept(self):
        assert _match_income_concept("managementfeeexpense") == "management_fee"

    def test_unrelated_concept(self):
        assert _match_income_concept("investmentsatfairvalue") is None

    def test_interest_expense_borrowings(self):
        """More specific interestexpenseborrowings matches before interestexpense."""
        assert _match_income_concept("interestexpenseborrowings") == "interest_expense"


# ---------------------------------------------------------------------------
# Integration: extract_bdc_fund_income with temp file
# ---------------------------------------------------------------------------

class TestExtractIntegration:
    def test_empty_filings_index(self):
        """Empty filings index -> empty result."""
        filings = pd.DataFrame(columns=[
            "cik", "entity_name", "form_type", "accession_number",
            "filing_date", "report_date", "xbrl_download_status",
            "xbrl_local_path",
        ])
        result = extract_bdc_fund_income(filings_index=filings)
        assert len(result) == 0
        assert list(result.columns) == INCOME_COLUMNS

    def test_single_filing_integration(self):
        """End-to-end extraction from a real XBRL fixture."""
        # Build a minimal XBRL file
        ctx_xml = _duration_ctx("d1", "2024-01-01", "2024-03-31")
        facts_xml = (
            _fact("GrossInvestmentIncomeOperating", "d1", "50000000")
            + _fact("InvestmentIncomeInterest", "d1", "40000000")
            + _fact("FeeIncome", "d1", "5000000")
            + _fact("NetInvestmentIncome", "d1", "30000000")
        )
        tree = _build_xbrl(ctx_xml, facts_xml)

        with tempfile.NamedTemporaryFile(suffix=".xml", delete=False,
                                          mode="wb") as f:
            tree.write(f, xml_declaration=True, encoding="utf-8")
            xml_path = f.name

        try:
            filings = pd.DataFrame([{
                "cik": "123456",
                "entity_name": "Test BDC Corp",
                "form_type": "10-Q",
                "accession_number": "0001234567-24-000001",
                "filing_date": "2024-05-15",
                "report_date": "2024-03-31",
                "xbrl_download_status": "cached",
                "xbrl_local_path": xml_path,
            }])

            result = extract_bdc_fund_income(filings_index=filings)
            assert len(result) == 1
            row = result.iloc[0]
            assert row["cik"] == "123456"
            assert row["report_quarter"] == "2024q1"
            assert float(row["total_investment_income"]) == 50000000.0
            assert float(row["interest_income"]) == 40000000.0
            assert float(row["fee_income"]) == 5000000.0
            assert float(row["net_investment_income"]) == 30000000.0
        finally:
            Path(xml_path).unlink(missing_ok=True)

    def test_dedup_prefers_shortest_duration(self):
        """When multiple periods cover same quarter, shortest duration wins."""
        # Build XBRL with quarterly and annual periods, same end_date
        ctx_xml = (
            _duration_ctx("q4", "2024-10-01", "2024-12-31")
            + _duration_ctx("annual", "2024-01-01", "2024-12-31")
        )
        facts_xml = (
            _fact("GrossInvestmentIncomeOperating", "q4", "15000000")
            + _fact("GrossInvestmentIncomeOperating", "annual", "52000000")
        )
        tree = _build_xbrl(ctx_xml, facts_xml)

        with tempfile.NamedTemporaryFile(suffix=".xml", delete=False,
                                          mode="wb") as f:
            tree.write(f, xml_declaration=True, encoding="utf-8")
            xml_path = f.name

        try:
            filings = pd.DataFrame([{
                "cik": "123456",
                "entity_name": "Test BDC",
                "form_type": "10-K",
                "accession_number": "0001234567-25-000001",
                "filing_date": "2025-03-15",
                "report_date": "2024-12-31",
                "xbrl_download_status": "cached",
                "xbrl_local_path": xml_path,
            }])

            result = extract_bdc_fund_income(filings_index=filings)
            # Both map to 2024q4; shortest duration (3 months) wins
            q4_rows = result[result["report_quarter"] == "2024q4"]
            assert len(q4_rows) == 1
            # The quarterly record (15M) is used directly (scale=1)
            assert float(q4_rows.iloc[0]["total_investment_income"]) == 15000000.0
        finally:
            Path(xml_path).unlink(missing_ok=True)
