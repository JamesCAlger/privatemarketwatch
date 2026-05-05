"""Tests for pipeline.bdc_sector_breakdown module.

Covers:
- Context parsing (industry contexts kept, position contexts skipped, instant vs duration)
- Member name normalization (CamelCase, prefix strip, Member suffix)
- Fact extraction (FV, cost, pct_of_net_assets mapped correctly)
- Multi-dimensional contexts (industry + investment_type)
- Empty/missing files handled gracefully
- Dedup (most-populated row wins)
"""

import io
import tempfile
from pathlib import Path

import pandas as pd
import pytest
from lxml import etree

from pipeline.bdc_sector_breakdown import (
    SECTOR_COLUMNS,
    _extract_sector_facts,
    _local_name,
    _match_sector_concept,
    _parse_sector_contexts,
    _strip_member_suffix,
    _camel_to_words,
    extract_bdc_sector_breakdown,
    normalize_member_name,
)


# ---------------------------------------------------------------------------
# Helper: minimal XBRL XML builder
# ---------------------------------------------------------------------------

def _build_xbrl(contexts_xml: str, facts_xml: str) -> etree._ElementTree:
    """Build a minimal XBRL document for testing."""
    xml = f"""<?xml version="1.0" encoding="utf-8"?>
    <xbrli:xbrl
        xmlns:xbrli="http://www.xbrl.org/2003/instance"
        xmlns:xbrldi="http://xbrl.org/2006/xbrldi"
        xmlns:us-gaap="http://fasb.org/us-gaap/2024"
        xmlns:us-gaap-supplement="http://fasb.org/us-gaap-supplement/2024"
        xmlns:glad="http://gladstone.com/20241231"
        xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
        {contexts_xml}
        {facts_xml}
    </xbrli:xbrl>
    """
    return etree.parse(io.BytesIO(xml.encode("utf-8")))


def _industry_ctx(
    ctx_id: str,
    instant: str,
    industry_member: str,
    *,
    investment_type: str = "",
    with_position_axis: bool = False,
) -> str:
    """Build an instant context with industry dimension."""
    dims = f"""
        <xbrldi:explicitMember dimension="us-gaap:EquitySecuritiesByIndustryAxis">
            {industry_member}
        </xbrldi:explicitMember>
    """
    if investment_type:
        dims += f"""
        <xbrldi:explicitMember dimension="us-gaap:InvestmentTypeAxis">
            {investment_type}
        </xbrldi:explicitMember>
        """
    if with_position_axis:
        dims += """
        <xbrldi:typedMember dimension="us-gaap:InvestmentIdentifierAxis">
            <us-gaap:InvestmentIdentifier>SomePosition</us-gaap:InvestmentIdentifier>
        </xbrldi:typedMember>
        """
    return f"""
    <xbrli:context id="{ctx_id}">
        <xbrli:entity>
            <xbrli:identifier scheme="http://www.sec.gov/CIK">0001234567</xbrli:identifier>
            <xbrli:segment>
                {dims}
            </xbrli:segment>
        </xbrli:entity>
        <xbrli:period>
            <xbrli:instant>{instant}</xbrli:instant>
        </xbrli:period>
    </xbrli:context>
    """


def _duration_industry_ctx(
    ctx_id: str,
    start: str,
    end: str,
    industry_member: str,
) -> str:
    """Build a duration context with industry dimension."""
    return f"""
    <xbrli:context id="{ctx_id}">
        <xbrli:entity>
            <xbrli:identifier scheme="http://www.sec.gov/CIK">0001234567</xbrli:identifier>
            <xbrli:segment>
                <xbrldi:explicitMember dimension="us-gaap:EquitySecuritiesByIndustryAxis">
                    {industry_member}
                </xbrldi:explicitMember>
            </xbrli:segment>
        </xbrli:entity>
        <xbrli:period>
            <xbrli:startDate>{start}</xbrli:startDate>
            <xbrli:endDate>{end}</xbrli:endDate>
        </xbrli:period>
    </xbrli:context>
    """


def _plain_instant_ctx(ctx_id: str, instant: str) -> str:
    """Build an instant context with NO dimensions."""
    return f"""
    <xbrli:context id="{ctx_id}">
        <xbrli:entity>
            <xbrli:identifier scheme="http://www.sec.gov/CIK">0001234567</xbrli:identifier>
        </xbrli:entity>
        <xbrli:period>
            <xbrli:instant>{instant}</xbrli:instant>
        </xbrli:period>
    </xbrli:context>
    """


def _fact(concept: str, ctx_ref: str, value: str) -> str:
    """Build a fact element XML snippet."""
    return f'<us-gaap:{concept} contextRef="{ctx_ref}">{value}</us-gaap:{concept}>'


# ---------------------------------------------------------------------------
# Member name normalization tests
# ---------------------------------------------------------------------------

class TestMemberNameNormalization:
    def test_strip_member_suffix(self):
        assert _strip_member_suffix("HealthcareMember") == "Healthcare"

    def test_strip_sector_suffix(self):
        assert _strip_member_suffix("HealthcareSector") == "Healthcare"

    def test_no_suffix(self):
        assert _strip_member_suffix("Software") == "Software"

    def test_camel_to_words_simple(self):
        assert _camel_to_words("Healthcare") == "healthcare"

    def test_camel_to_words_multi(self):
        assert _camel_to_words("HealthcareEducationAndChildcare") == (
            "healthcare education and childcare"
        )

    def test_camel_to_words_with_abbreviation(self):
        assert _camel_to_words("OilAndGasIndustry") == "oil and gas industry"

    def test_normalize_full_member(self):
        assert normalize_member_name("glad:AerospaceAndDefenseMember") == (
            "aerospace and defense"
        )

    def test_normalize_us_gaap_prefix(self):
        assert normalize_member_name(
            "us-gaap:HealthcareSectorMember"
        ) == "healthcare"

    def test_normalize_no_prefix(self):
        assert normalize_member_name("SoftwareAndServicesMember") == (
            "software and services"
        )

    def test_normalize_sector_and_member(self):
        """SectorMember suffix still handled (just Member stripped)."""
        result = normalize_member_name("arcc:InsuranceSectorMember")
        assert result == "insurance"


# ---------------------------------------------------------------------------
# Context parsing tests
# ---------------------------------------------------------------------------

class TestContextParsing:
    def test_industry_instant_context_parsed(self):
        """Industry-dimensioned instant context is extracted."""
        ctx_xml = _industry_ctx(
            "i1", "2024-12-31", "glad:HealthcareMember",
        )
        tree = _build_xbrl(ctx_xml, "")
        contexts = _parse_sector_contexts(tree)
        assert "i1" in contexts
        assert contexts["i1"]["instant_date"] == "2024-12-31"
        assert "Healthcare" in contexts["i1"]["industry_member"]

    def test_position_axis_excluded(self):
        """Context with InvestmentIdentifierAxis is skipped."""
        ctx_xml = _industry_ctx(
            "i_pos", "2024-12-31", "glad:HealthcareMember",
            with_position_axis=True,
        )
        tree = _build_xbrl(ctx_xml, "")
        contexts = _parse_sector_contexts(tree)
        assert "i_pos" not in contexts

    def test_no_industry_axis_excluded(self):
        """Context without industry dimension is skipped."""
        ctx_xml = _plain_instant_ctx("i_plain", "2024-12-31")
        tree = _build_xbrl(ctx_xml, "")
        contexts = _parse_sector_contexts(tree)
        assert "i_plain" not in contexts

    def test_investment_type_captured(self):
        """Investment type axis is captured when present."""
        ctx_xml = _industry_ctx(
            "i_typed", "2024-12-31",
            "glad:HealthcareMember",
            investment_type="glad:DebtSecuritiesFirstLienMember",
        )
        tree = _build_xbrl(ctx_xml, "")
        contexts = _parse_sector_contexts(tree)
        assert "i_typed" in contexts
        assert "FirstLien" in contexts["i_typed"]["investment_type_member"]

    def test_duration_context_allowed(self):
        """Duration context with industry axis is also captured (concentration risk)."""
        ctx_xml = _duration_industry_ctx(
            "d1", "2024-01-01", "2024-12-31",
            "glad:HealthcareMember",
        )
        tree = _build_xbrl(ctx_xml, "")
        contexts = _parse_sector_contexts(tree)
        assert "d1" in contexts
        assert contexts["d1"]["instant_date"] == "2024-12-31"

    def test_multiple_contexts(self):
        """Multiple industry contexts from different sectors are all parsed."""
        ctx_xml = (
            _industry_ctx("i_h", "2024-12-31", "glad:HealthcareMember")
            + _industry_ctx("i_t", "2024-12-31", "glad:TelecomMember")
            + _plain_instant_ctx("i_plain", "2024-12-31")
        )
        tree = _build_xbrl(ctx_xml, "")
        contexts = _parse_sector_contexts(tree)
        assert len(contexts) == 2
        assert "i_h" in contexts
        assert "i_t" in contexts


# ---------------------------------------------------------------------------
# Fact extraction tests
# ---------------------------------------------------------------------------

class TestFactExtraction:
    def test_fair_value_extracted(self):
        """InvestmentOwnedAtFairValue is extracted."""
        ctx_xml = _industry_ctx("i1", "2024-12-31", "glad:HealthcareMember")
        facts_xml = _fact("InvestmentOwnedAtFairValue", "i1", "72699000")
        tree = _build_xbrl(ctx_xml, facts_xml)
        contexts = _parse_sector_contexts(tree)
        facts = _extract_sector_facts(tree, contexts)
        assert len(facts) == 1
        assert facts[0]["fair_value"] == 72699000.0

    def test_cost_extracted(self):
        """InvestmentOwnedAtCost is extracted."""
        ctx_xml = _industry_ctx("i1", "2024-12-31", "glad:HealthcareMember")
        facts_xml = _fact("InvestmentOwnedAtCost", "i1", "80000000")
        tree = _build_xbrl(ctx_xml, facts_xml)
        contexts = _parse_sector_contexts(tree)
        facts = _extract_sector_facts(tree, contexts)
        assert facts[0]["cost"] == 80000000.0

    def test_pct_of_net_assets_extracted(self):
        """InvestmentOwnedPercentOfNetAssets is extracted."""
        ctx_xml = _industry_ctx("i1", "2024-12-31", "glad:HealthcareMember")
        facts_xml = _fact(
            "InvestmentOwnedPercentOfNetAssets", "i1", "0.223",
        )
        tree = _build_xbrl(ctx_xml, facts_xml)
        contexts = _parse_sector_contexts(tree)
        facts = _extract_sector_facts(tree, contexts)
        assert abs(facts[0]["pct_of_net_assets"] - 0.223) < 0.001

    def test_concentration_risk_maps_to_pct(self):
        """ConcentrationRiskPercentage1 maps to pct_of_net_assets."""
        ctx_xml = _duration_industry_ctx(
            "d1", "2024-01-01", "2024-12-31", "arcc:SoftwareMember",
        )
        facts_xml = _fact("ConcentrationRiskPercentage1", "d1", "0.219")
        tree = _build_xbrl(ctx_xml, facts_xml)
        contexts = _parse_sector_contexts(tree)
        facts = _extract_sector_facts(tree, contexts)
        assert len(facts) == 1
        assert abs(facts[0]["pct_of_net_assets"] - 0.219) < 0.001

    def test_multiple_facts_same_context(self):
        """Multiple concepts in one context produce one record."""
        ctx_xml = _industry_ctx("i1", "2024-12-31", "glad:HealthcareMember")
        facts_xml = (
            _fact("InvestmentOwnedAtFairValue", "i1", "72699000")
            + _fact("InvestmentOwnedAtCost", "i1", "80000000")
            + _fact("InvestmentOwnedPercentOfNetAssets", "i1", "0.223")
        )
        tree = _build_xbrl(ctx_xml, facts_xml)
        contexts = _parse_sector_contexts(tree)
        facts = _extract_sector_facts(tree, contexts)
        assert len(facts) == 1
        assert facts[0]["fair_value"] == 72699000.0
        assert facts[0]["cost"] == 80000000.0
        assert abs(facts[0]["pct_of_net_assets"] - 0.223) < 0.001

    def test_multiple_sectors_produce_multiple_records(self):
        """Different sectors produce separate records."""
        ctx_xml = (
            _industry_ctx("i_h", "2024-12-31", "glad:HealthcareMember")
            + _industry_ctx("i_t", "2024-12-31", "glad:TelecomMember")
        )
        facts_xml = (
            _fact("InvestmentOwnedAtFairValue", "i_h", "72699000")
            + _fact("InvestmentOwnedAtFairValue", "i_t", "30000000")
        )
        tree = _build_xbrl(ctx_xml, facts_xml)
        contexts = _parse_sector_contexts(tree)
        facts = _extract_sector_facts(tree, contexts)
        assert len(facts) == 2

    def test_nil_elements_skipped(self):
        """Elements with xsi:nil='true' are skipped."""
        ctx_xml = _industry_ctx("i1", "2024-12-31", "glad:HealthcareMember")
        facts_xml = (
            '<us-gaap:InvestmentOwnedAtFairValue contextRef="i1" '
            'xsi:nil="true"/>'
        )
        tree = _build_xbrl(ctx_xml, facts_xml)
        contexts = _parse_sector_contexts(tree)
        facts = _extract_sector_facts(tree, contexts)
        assert len(facts) == 0

    def test_empty_contexts_returns_empty(self):
        """No matching contexts yields empty facts."""
        ctx_xml = _plain_instant_ctx("i1", "2024-12-31")
        facts_xml = _fact("InvestmentOwnedAtFairValue", "i1", "72699000")
        tree = _build_xbrl(ctx_xml, facts_xml)
        contexts = _parse_sector_contexts(tree)
        facts = _extract_sector_facts(tree, contexts)
        assert len(facts) == 0

    def test_unrelated_concept_ignored(self):
        """Concepts not in the map are ignored."""
        ctx_xml = _industry_ctx("i1", "2024-12-31", "glad:HealthcareMember")
        facts_xml = _fact("SomeUnrelatedConcept", "i1", "12345")
        tree = _build_xbrl(ctx_xml, facts_xml)
        contexts = _parse_sector_contexts(tree)
        facts = _extract_sector_facts(tree, contexts)
        assert len(facts) == 0


# ---------------------------------------------------------------------------
# Concept matching tests
# ---------------------------------------------------------------------------

class TestConceptMatching:
    def test_fair_value_concept(self):
        assert _match_sector_concept("investmentownedatfairvalue") == "fair_value"

    def test_cost_concept(self):
        assert _match_sector_concept("investmentownedatcost") == "cost"

    def test_pct_concept(self):
        assert (
            _match_sector_concept("investmentownedpercentofnetassets")
            == "pct_of_net_assets"
        )

    def test_concentration_risk_concept(self):
        assert (
            _match_sector_concept("concentrationriskpercentage1")
            == "pct_of_net_assets"
        )

    def test_unrelated_concept(self):
        assert _match_sector_concept("netinvestmentincome") is None


# ---------------------------------------------------------------------------
# Integration: extract_bdc_sector_breakdown with temp file
# ---------------------------------------------------------------------------

class TestExtractIntegration:
    def test_empty_filings_index(self):
        """Empty filings index -> empty result."""
        filings = pd.DataFrame(columns=[
            "cik", "entity_name", "form_type", "accession_number",
            "filing_date", "report_date", "xbrl_download_status",
            "xbrl_local_path",
        ])
        result = extract_bdc_sector_breakdown(filings_index=filings)
        assert len(result) == 0
        assert list(result.columns) == SECTOR_COLUMNS

    def test_single_filing_integration(self):
        """End-to-end extraction from a synthetic XBRL fixture."""
        ctx_xml = (
            _industry_ctx("i_h", "2024-12-31", "glad:HealthcareEducationAndChildcareMember")
            + _industry_ctx("i_t", "2024-12-31", "glad:TelecommunicationsMember")
        )
        facts_xml = (
            _fact("InvestmentOwnedAtFairValue", "i_h", "72699000")
            + _fact("InvestmentOwnedAtCost", "i_h", "80000000")
            + _fact("InvestmentOwnedPercentOfNetAssets", "i_h", "0.223")
            + _fact("InvestmentOwnedAtFairValue", "i_t", "30000000")
            + _fact("InvestmentOwnedPercentOfNetAssets", "i_t", "0.092")
        )
        tree = _build_xbrl(ctx_xml, facts_xml)

        with tempfile.NamedTemporaryFile(
            suffix=".xml", delete=False, mode="wb",
        ) as f:
            tree.write(f, xml_declaration=True, encoding="utf-8")
            xml_path = f.name

        try:
            filings = pd.DataFrame([{
                "cik": "1143513",
                "entity_name": "Gladstone Capital Corp",
                "form_type": "10-K",
                "accession_number": "0001143513-25-000001",
                "filing_date": "2025-02-15",
                "report_date": "2024-12-31",
                "xbrl_download_status": "cached",
                "xbrl_local_path": xml_path,
            }])

            result = extract_bdc_sector_breakdown(filings_index=filings)
            assert len(result) == 2

            hc = result[
                result["industry_sector"].str.contains("healthcare")
            ]
            assert len(hc) == 1
            assert float(hc.iloc[0]["fair_value"]) == 72699000.0
            assert float(hc.iloc[0]["cost"]) == 80000000.0
            assert abs(float(hc.iloc[0]["pct_of_net_assets"]) - 0.223) < 0.001

            tc = result[
                result["industry_sector"].str.contains("telecom")
            ]
            assert len(tc) == 1
            assert float(tc.iloc[0]["fair_value"]) == 30000000.0
        finally:
            Path(xml_path).unlink(missing_ok=True)

    def test_investment_type_preserved(self):
        """Investment type dimension is preserved in output."""
        ctx_xml = _industry_ctx(
            "i1", "2024-12-31",
            "glad:HealthcareMember",
            investment_type="glad:DebtSecuritiesSecuredFirstLienDebtMember",
        )
        facts_xml = _fact("InvestmentOwnedAtFairValue", "i1", "50000000")
        tree = _build_xbrl(ctx_xml, facts_xml)

        with tempfile.NamedTemporaryFile(
            suffix=".xml", delete=False, mode="wb",
        ) as f:
            tree.write(f, xml_declaration=True, encoding="utf-8")
            xml_path = f.name

        try:
            filings = pd.DataFrame([{
                "cik": "1143513",
                "entity_name": "Gladstone Capital Corp",
                "form_type": "10-K",
                "accession_number": "0001143513-25-000001",
                "filing_date": "2025-02-15",
                "report_date": "2024-12-31",
                "xbrl_download_status": "cached",
                "xbrl_local_path": xml_path,
            }])

            result = extract_bdc_sector_breakdown(filings_index=filings)
            assert len(result) == 1
            assert "first lien" in result.iloc[0]["investment_type"].lower()
        finally:
            Path(xml_path).unlink(missing_ok=True)

    def test_position_contexts_excluded(self):
        """Contexts with InvestmentIdentifierAxis are not extracted."""
        ctx_xml = _industry_ctx(
            "i_pos", "2024-12-31",
            "glad:HealthcareMember",
            with_position_axis=True,
        )
        facts_xml = _fact("InvestmentOwnedAtFairValue", "i_pos", "99999")
        tree = _build_xbrl(ctx_xml, facts_xml)

        with tempfile.NamedTemporaryFile(
            suffix=".xml", delete=False, mode="wb",
        ) as f:
            tree.write(f, xml_declaration=True, encoding="utf-8")
            xml_path = f.name

        try:
            filings = pd.DataFrame([{
                "cik": "1143513",
                "entity_name": "Gladstone Capital Corp",
                "form_type": "10-K",
                "accession_number": "0001143513-25-000001",
                "filing_date": "2025-02-15",
                "report_date": "2024-12-31",
                "xbrl_download_status": "cached",
                "xbrl_local_path": xml_path,
            }])

            result = extract_bdc_sector_breakdown(filings_index=filings)
            assert len(result) == 0
        finally:
            Path(xml_path).unlink(missing_ok=True)

    def test_corrupted_file_handled(self):
        """Non-XML file does not crash, produces empty result."""
        with tempfile.NamedTemporaryFile(
            suffix=".xml", delete=False, mode="w",
        ) as f:
            f.write("this is not xml")
            bad_path = f.name

        try:
            filings = pd.DataFrame([{
                "cik": "999",
                "entity_name": "Bad Corp",
                "form_type": "10-K",
                "accession_number": "000",
                "filing_date": "2024-01-01",
                "report_date": "2024-12-31",
                "xbrl_download_status": "cached",
                "xbrl_local_path": bad_path,
            }])

            result = extract_bdc_sector_breakdown(filings_index=filings)
            assert len(result) == 0
        finally:
            Path(bad_path).unlink(missing_ok=True)
