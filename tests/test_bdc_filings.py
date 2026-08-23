"""Comprehensive tests for pipeline.bdc_filings module.

Covers:
- Pure functions: _local_name, _match_concept, _parse_fact_value, _collect_filings
- XBRL parsing: _parse_xbrl_contexts, _extract_investment_facts, _parse_single_filing
- Integration: _build_filings_index, _download_xbrl_instances, _parse_all_filings
- Config: new constants and directory creation
- CLI: --holdings flag in main.py
"""

import os
import textwrap
import tempfile
import shutil
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch, PropertyMock

import pandas as pd
import pytest
from lxml import etree

from pipeline.edgar_client import EdgarClient


# ---------------------------------------------------------------------------
# Fixtures & helpers
# ---------------------------------------------------------------------------

# Minimal XBRL document with one investment context and facts
XBRL_MINIMAL = textwrap.dedent("""\
    <?xml version="1.0" encoding="UTF-8"?>
    <xbrl
        xmlns="http://www.xbrl.org/2003/instance"
        xmlns:xbrli="http://www.xbrl.org/2003/instance"
        xmlns:xbrldi="http://xbrl.org/2006/xbrldi"
        xmlns:cik0001418076="http://example.com/cik0001418076"
        xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">

        <!-- Non-investment context (entity-level) -->
        <xbrli:context id="ctx_entity">
            <xbrli:entity><xbrli:identifier scheme="http://www.sec.gov/CIK">0001418076</xbrli:identifier></xbrli:entity>
            <xbrli:period><xbrli:instant>2023-12-31</xbrli:instant></xbrli:period>
        </xbrli:context>

        <!-- Investment context with typed dimension -->
        <xbrli:context id="ctx_inv_001">
            <xbrli:entity>
                <xbrli:identifier scheme="http://www.sec.gov/CIK">0001418076</xbrli:identifier>
                <xbrli:segment>
                    <xbrldi:typedMember dimension="cik0001418076:InvestmentIdentifierAxis">
                        <cik0001418076:InvestmentIdentifierDomain>Acme Corp - First Lien Term Loan</cik0001418076:InvestmentIdentifierDomain>
                    </xbrldi:typedMember>
                    <xbrldi:explicitMember dimension="cik0001418076:IndustryAxis">cik0001418076:SoftwareMember</xbrldi:explicitMember>
                    <xbrldi:explicitMember dimension="cik0001418076:InvestmentTypeAxis">cik0001418076:FirstLienDebtMember</xbrldi:explicitMember>
                    <xbrldi:explicitMember dimension="cik0001418076:IssuerAffiliationAxis">cik0001418076:NonAffiliatedMember</xbrldi:explicitMember>
                </xbrli:segment>
            </xbrli:entity>
            <xbrli:period><xbrli:instant>2023-12-31</xbrli:instant></xbrli:period>
        </xbrli:context>

        <!-- Investment context #2 — different investee -->
        <xbrli:context id="ctx_inv_002">
            <xbrli:entity>
                <xbrli:identifier scheme="http://www.sec.gov/CIK">0001418076</xbrli:identifier>
                <xbrli:segment>
                    <xbrldi:typedMember dimension="cik0001418076:InvestmentIdentifierAxis">
                        <cik0001418076:InvestmentIdentifierDomain>Beta Inc - Senior Secured Note</cik0001418076:InvestmentIdentifierDomain>
                    </xbrldi:typedMember>
                    <xbrldi:explicitMember dimension="cik0001418076:IndustryAxis">cik0001418076:HealthcareMember</xbrldi:explicitMember>
                </xbrli:segment>
            </xbrli:entity>
            <xbrli:period><xbrli:instant>2023-12-31</xbrli:instant></xbrli:period>
        </xbrli:context>

        <!-- Facts for investment 1 -->
        <cik0001418076:InvestmentOwnedAtFairValue contextRef="ctx_inv_001" unitRef="usd" decimals="-3">15000000</cik0001418076:InvestmentOwnedAtFairValue>
        <cik0001418076:InvestmentOwnedAtCost contextRef="ctx_inv_001" unitRef="usd" decimals="-3">14500000</cik0001418076:InvestmentOwnedAtCost>
        <cik0001418076:InvestmentInterestRate contextRef="ctx_inv_001" unitRef="pure" decimals="4">0.0925</cik0001418076:InvestmentInterestRate>
        <cik0001418076:InvestmentBasisSpreadVariableRate contextRef="ctx_inv_001" unitRef="pure" decimals="4">0.0575</cik0001418076:InvestmentBasisSpreadVariableRate>
        <cik0001418076:InvestmentMaturityDate contextRef="ctx_inv_001">2028-06-15</cik0001418076:InvestmentMaturityDate>
        <cik0001418076:InvestmentOwnedBalancePrincipalAmount contextRef="ctx_inv_001" unitRef="usd" decimals="-3">15000000</cik0001418076:InvestmentOwnedBalancePrincipalAmount>
        <cik0001418076:InvestmentOwnedPercentOfNetAssets contextRef="ctx_inv_001" unitRef="pure" decimals="4">0.0023</cik0001418076:InvestmentOwnedPercentOfNetAssets>

        <!-- Facts for investment 2 -->
        <cik0001418076:InvestmentOwnedAtFairValue contextRef="ctx_inv_002" unitRef="usd" decimals="-3">8000000</cik0001418076:InvestmentOwnedAtFairValue>
        <cik0001418076:InvestmentOwnedAtCost contextRef="ctx_inv_002" unitRef="usd" decimals="-3">8200000</cik0001418076:InvestmentOwnedAtCost>
        <cik0001418076:InvestmentOwnedBalanceShares contextRef="ctx_inv_002" unitRef="shares" decimals="0">50000</cik0001418076:InvestmentOwnedBalanceShares>

        <!-- Nil element — should be skipped -->
        <cik0001418076:InvestmentInterestRateFloor contextRef="ctx_inv_001" xsi:nil="true" />

        <!-- Fact on entity context — should be ignored (not investment) -->
        <cik0001418076:InvestmentOwnedAtFairValue contextRef="ctx_entity" unitRef="usd" decimals="-3">999999</cik0001418076:InvestmentOwnedAtFairValue>
    </xbrl>
""")


def test_extract_investment_facts_preserves_xbrl_units():
    """Principal may be non-USD while valuation facts remain USD."""
    from pipeline.bdc_filings import _extract_investment_facts, _parse_xbrl_contexts

    xml = textwrap.dedent("""\
        <xbrl xmlns="http://www.xbrl.org/2003/instance"
              xmlns:xbrli="http://www.xbrl.org/2003/instance"
              xmlns:xbrldi="http://xbrl.org/2006/xbrldi"
              xmlns:test="http://example.com/test">
            <xbrli:context id="ctx_cad">
                <xbrli:entity>
                    <xbrli:identifier scheme="http://www.sec.gov/CIK">100</xbrli:identifier>
                    <xbrli:segment>
                        <xbrldi:typedMember dimension="test:InvestmentIdentifierAxis">
                            <test:InvestmentIdentifierDomain>Acme - Term Loan</test:InvestmentIdentifierDomain>
                        </xbrldi:typedMember>
                    </xbrli:segment>
                </xbrli:entity>
                <xbrli:period><xbrli:instant>2024-03-31</xbrli:instant></xbrli:period>
            </xbrli:context>
            <test:InvestmentOwnedAtFairValue contextRef="ctx_cad" unitRef="usd" decimals="0">750</test:InvestmentOwnedAtFairValue>
            <test:InvestmentOwnedAtCost contextRef="ctx_cad" unitRef="usd" decimals="0">700</test:InvestmentOwnedAtCost>
            <test:InvestmentOwnedBalancePrincipalAmount contextRef="ctx_cad" unitRef="cad" decimals="0">1000</test:InvestmentOwnedBalancePrincipalAmount>
        </xbrl>
    """)
    tree = etree.ElementTree(etree.fromstring(xml.encode("utf-8")))
    facts = _extract_investment_facts(tree, _parse_xbrl_contexts(tree))

    assert len(facts) == 1
    row = facts[0]
    assert row["fair_value_unit"] == "usd"
    assert row["cost_unit"] == "usd"
    assert row["principal_amount_unit"] == "cad"


# XBRL with duration period (startDate/endDate) instead of instant
XBRL_DURATION_PERIOD = textwrap.dedent("""\
    <?xml version="1.0" encoding="UTF-8"?>
    <xbrl
        xmlns="http://www.xbrl.org/2003/instance"
        xmlns:xbrli="http://www.xbrl.org/2003/instance"
        xmlns:xbrldi="http://xbrl.org/2006/xbrldi"
        xmlns:abc="http://example.com/abc">

        <xbrli:context id="ctx_dur_inv">
            <xbrli:entity>
                <xbrli:identifier scheme="http://www.sec.gov/CIK">0001234567</xbrli:identifier>
                <xbrli:segment>
                    <xbrldi:typedMember dimension="abc:InvestmentIdentifierAxis">
                        <abc:InvestmentIdentifierDomain>Duration Corp</abc:InvestmentIdentifierDomain>
                    </xbrldi:typedMember>
                </xbrli:segment>
            </xbrli:entity>
            <xbrli:period>
                <xbrli:startDate>2023-01-01</xbrli:startDate>
                <xbrli:endDate>2023-12-31</xbrli:endDate>
            </xbrli:period>
        </xbrli:context>

        <abc:RealizedGainLossOnInvestments contextRef="ctx_dur_inv" unitRef="usd" decimals="-3">-250000</abc:RealizedGainLossOnInvestments>
    </xbrl>
""")


# XBRL with no investment contexts (entity-only)
XBRL_NO_INVESTMENTS = textwrap.dedent("""\
    <?xml version="1.0" encoding="UTF-8"?>
    <xbrl
        xmlns="http://www.xbrl.org/2003/instance"
        xmlns:xbrli="http://www.xbrl.org/2003/instance">

        <xbrli:context id="ctx_entity_only">
            <xbrli:entity><xbrli:identifier scheme="http://www.sec.gov/CIK">0009999999</xbrli:identifier></xbrli:entity>
            <xbrli:period><xbrli:instant>2023-12-31</xbrli:instant></xbrli:period>
        </xbrli:context>

        <us-gaap:Assets contextRef="ctx_entity_only" unitRef="usd" decimals="-3"
            xmlns:us-gaap="http://fasb.org/us-gaap/2023">5000000000</us-gaap:Assets>
    </xbrl>
""")


# XBRL with alternative dimension naming (InvestmentCompany instead of InvestmentIdentifier)
XBRL_ALT_DIMENSION = textwrap.dedent("""\
    <?xml version="1.0" encoding="UTF-8"?>
    <xbrl
        xmlns="http://www.xbrl.org/2003/instance"
        xmlns:xbrli="http://www.xbrl.org/2003/instance"
        xmlns:xbrldi="http://xbrl.org/2006/xbrldi"
        xmlns:filer="http://example.com/filer">

        <xbrli:context id="ctx_alt">
            <xbrli:entity>
                <xbrli:identifier scheme="http://www.sec.gov/CIK">0005555555</xbrli:identifier>
                <xbrli:segment>
                    <xbrldi:typedMember dimension="filer:InvestmentCompanyAxis">
                        <filer:InvestmentCompanyDomain>AltCo Partners</filer:InvestmentCompanyDomain>
                    </xbrldi:typedMember>
                </xbrli:segment>
            </xbrli:entity>
            <xbrli:period><xbrli:instant>2023-06-30</xbrli:instant></xbrli:period>
        </xbrli:context>

        <filer:InvestmentOwnedFairValue contextRef="ctx_alt" unitRef="usd" decimals="-3">3000000</filer:InvestmentOwnedFairValue>
        <filer:InvestmentOwnedCost contextRef="ctx_alt" unitRef="usd" decimals="-3">2900000</filer:InvestmentOwnedCost>
    </xbrl>
""")


# XBRL with concept name variants (e.g. InvestmentOwnedPercentageOfNetAssets)
XBRL_VARIANT_CONCEPTS = textwrap.dedent("""\
    <?xml version="1.0" encoding="UTF-8"?>
    <xbrl
        xmlns="http://www.xbrl.org/2003/instance"
        xmlns:xbrli="http://www.xbrl.org/2003/instance"
        xmlns:xbrldi="http://xbrl.org/2006/xbrldi"
        xmlns:filer="http://example.com/filer2">

        <xbrli:context id="ctx_var">
            <xbrli:entity>
                <xbrli:identifier scheme="http://www.sec.gov/CIK">0006666666</xbrli:identifier>
                <xbrli:segment>
                    <xbrldi:typedMember dimension="filer:InvestmentIdentifierAxis">
                        <filer:InvestmentIdentifierDomain>Variant Corp</filer:InvestmentIdentifierDomain>
                    </xbrldi:typedMember>
                </xbrli:segment>
            </xbrli:entity>
            <xbrli:period><xbrli:instant>2023-09-30</xbrli:instant></xbrli:period>
        </xbrli:context>

        <filer:InvestmentOwnedPercentageOfNetAssets contextRef="ctx_var" unitRef="pure" decimals="4">0.0150</filer:InvestmentOwnedPercentageOfNetAssets>
        <filer:InvestmentOwnedFaceAmount contextRef="ctx_var" unitRef="usd" decimals="-3">5000000</filer:InvestmentOwnedFaceAmount>
        <filer:InvestmentInterestRatePaidInKind contextRef="ctx_var" unitRef="pure" decimals="4">0.0200</filer:InvestmentInterestRatePaidInKind>
        <filer:InvestmentAcquisitionDate contextRef="ctx_var">2022-03-15</filer:InvestmentAcquisitionDate>
        <filer:InvestmentOwnedUnrealizedAppreciationDepreciation contextRef="ctx_var" unitRef="usd" decimals="-3">-120000</filer:InvestmentOwnedUnrealizedAppreciationDepreciation>
    </xbrl>
""")


@pytest.fixture
def tmp_dir(tmp_path):
    """Provide a temporary directory for test outputs."""
    return tmp_path


def _write_xml(tmp_dir: Path, content: str, name: str = "test.xml") -> Path:
    """Write XML content to a temp file and return its path."""
    p = tmp_dir / name
    p.write_text(content, encoding="utf-8")
    return p


def _parse_tree(xml_string: str) -> etree._ElementTree:
    """Parse an XML string into an lxml ElementTree."""
    return etree.ElementTree(etree.fromstring(xml_string.encode("utf-8")))


# ---------------------------------------------------------------------------
# 1. _local_name
# ---------------------------------------------------------------------------

class TestLocalName:
    def test_namespace_uri(self):
        from pipeline.bdc_filings import _local_name
        assert _local_name("{http://www.xbrl.org/2003/instance}context") == "context"

    def test_colon_prefix(self):
        from pipeline.bdc_filings import _local_name
        assert _local_name("xbrli:context") == "context"

    def test_no_namespace(self):
        from pipeline.bdc_filings import _local_name
        assert _local_name("context") == "context"

    def test_empty_string(self):
        from pipeline.bdc_filings import _local_name
        assert _local_name("") == ""

    def test_deep_namespace_uri(self):
        from pipeline.bdc_filings import _local_name
        assert _local_name("{http://example.com/cik0001418076/2023}InvestmentOwnedAtFairValue") == "InvestmentOwnedAtFairValue"


# ---------------------------------------------------------------------------
# 2. _match_concept
# ---------------------------------------------------------------------------

class TestMatchConcept:
    def test_exact_substring_match(self):
        from pipeline.bdc_filings import _match_concept
        assert _match_concept("investmentownedatfairvalue") == "fair_value"

    def test_extended_name_match(self):
        """Concept names may have filer-specific prefixes/suffixes."""
        from pipeline.bdc_filings import _match_concept
        assert _match_concept("cik0001418076_investmentownedatfairvalue") == "fair_value"

    def test_variant_fair_value(self):
        from pipeline.bdc_filings import _match_concept
        assert _match_concept("investmentownedfairvalue") == "fair_value"

    def test_cost_variants(self):
        from pipeline.bdc_filings import _match_concept
        assert _match_concept("investmentownedatcost") == "cost"
        assert _match_concept("investmentownedcost") == "cost"

    def test_interest_rate(self):
        from pipeline.bdc_filings import _match_concept
        assert _match_concept("investmentinterestrate") == "interest_rate"

    def test_basis_spread_variants(self):
        from pipeline.bdc_filings import _match_concept
        assert _match_concept("investmentbasisspreadvariablerate") == "basis_spread"
        assert _match_concept("investmentbasisspreadofvariablerate") == "basis_spread"

    def test_maturity_date(self):
        from pipeline.bdc_filings import _match_concept
        assert _match_concept("investmentmaturitydate") == "maturity_date"

    def test_shares(self):
        from pipeline.bdc_filings import _match_concept
        assert _match_concept("investmentownedbalanceshares") == "shares_held"

    def test_pct_of_net_assets_variants(self):
        from pipeline.bdc_filings import _match_concept
        assert _match_concept("investmentownedpercentofnetassets") == "pct_of_net_assets"
        assert _match_concept("investmentownedpercentageofnetassets") == "pct_of_net_assets"

    def test_unrealized_gain_loss(self):
        from pipeline.bdc_filings import _match_concept
        assert _match_concept("investmentownedunrealizedappreciationdepreciation") == "unrealized_gain_loss"

    def test_realized_gain_loss_variants(self):
        from pipeline.bdc_filings import _match_concept
        assert _match_concept("realizedgainlossoninvestments") == "realized_gain_loss"
        assert _match_concept("realizedgainlossoninvestment") == "realized_gain_loss"

    def test_pik_rate_variants(self):
        from pipeline.bdc_filings import _match_concept
        assert _match_concept("investmentinterestratepaidinkind") == "pik_rate"
        assert _match_concept("investmentpikrate") == "pik_rate"

    def test_face_amount_variants(self):
        from pipeline.bdc_filings import _match_concept
        assert _match_concept("investmentobtainedfaceamount") == "face_amount"
        assert _match_concept("investmentownedfaceamount") == "face_amount"

    def test_acquisition_date(self):
        from pipeline.bdc_filings import _match_concept
        assert _match_concept("investmentacquisitiondate") == "acquisition_date"

    def test_no_match(self):
        from pipeline.bdc_filings import _match_concept
        assert _match_concept("totalassets") is None
        assert _match_concept("cashandcashequivalents") is None
        assert _match_concept("") is None

    def test_first_match_wins(self):
        """investmentownedatfairvalue should match before investmentownedfairvalue."""
        from pipeline.bdc_filings import _match_concept
        # "investmentownedatfairvalue" contains "investmentownedatfairvalue" (exact)
        # It also contains "investmentownedfairvalue" as a substring
        # First-match-wins means both map to "fair_value" — no conflict
        assert _match_concept("investmentownedatfairvalue") == "fair_value"

    def test_principal_amount_long_variant(self):
        from pipeline.bdc_filings import _match_concept
        assert _match_concept(
            "investmentownedbalancesharesornumberofcontractsorprincipalamount"
        ) == "principal_amount"


# ---------------------------------------------------------------------------
# 3. _parse_fact_value
# ---------------------------------------------------------------------------

class TestParseFactValue:
    def test_numeric_plain(self):
        from pipeline.bdc_filings import _parse_fact_value
        assert _parse_fact_value("fair_value", "15000000") == 15000000.0

    def test_numeric_with_commas(self):
        from pipeline.bdc_filings import _parse_fact_value
        assert _parse_fact_value("cost", "14,500,000") == 14500000.0

    def test_numeric_negative(self):
        from pipeline.bdc_filings import _parse_fact_value
        assert _parse_fact_value("unrealized_gain_loss", "-250000") == -250000.0

    def test_numeric_decimal(self):
        from pipeline.bdc_filings import _parse_fact_value
        assert _parse_fact_value("interest_rate", "0.0925") == 0.0925

    def test_date_column_kept_as_string(self):
        from pipeline.bdc_filings import _parse_fact_value
        assert _parse_fact_value("maturity_date", "2028-06-15") == "2028-06-15"
        assert _parse_fact_value("acquisition_date", "2022-03-15") == "2022-03-15"

    def test_string_column(self):
        from pipeline.bdc_filings import _parse_fact_value
        assert _parse_fact_value("reference_rate_type", "SOFR + 5.75%") == "SOFR + 5.75%"

    def test_non_numeric_fallback(self):
        from pipeline.bdc_filings import _parse_fact_value
        # Non-parseable numeric column falls back to raw string
        result = _parse_fact_value("fair_value", "N/A")
        assert result == "N/A"


# ---------------------------------------------------------------------------
# 4. _collect_filings
# ---------------------------------------------------------------------------

class TestCollectFilings:
    def test_basic_collection(self):
        from pipeline.bdc_filings import _collect_filings
        records = []
        recent = {
            "form": ["10-K", "10-Q", "8-K", "10-K/A"],
            "filingDate": ["2023-12-15", "2023-09-15", "2023-07-01", "2024-01-10"],
            "accessionNumber": ["0001-23-000001", "0001-23-000002", "0001-23-000003", "0001-24-000001"],
            "primaryDocument": ["doc1.htm", "doc2.htm", "doc3.htm", "doc4.htm"],
            "reportDate": ["2023-12-31", "2023-09-30", "2023-06-30", "2023-12-31"],
        }
        _collect_filings(records, "1418076", "Ares Capital", recent, "2013-01-01")
        # 8-K should be excluded
        assert len(records) == 3
        forms = {r["form_type"] for r in records}
        assert forms == {"10-K", "10-Q", "10-K/A"}

    def test_cutoff_date_filter(self):
        from pipeline.bdc_filings import _collect_filings
        records = []
        recent = {
            "form": ["10-K", "10-K"],
            "filingDate": ["2012-03-15", "2014-03-15"],
            "accessionNumber": ["acc1", "acc2"],
            "primaryDocument": ["d1.htm", "d2.htm"],
            "reportDate": ["2012-12-31", "2013-12-31"],
        }
        _collect_filings(records, "123", "Test Corp", recent, "2013-01-01")
        assert len(records) == 1
        assert records[0]["accession_number"] == "acc2"

    def test_empty_recent(self):
        from pipeline.bdc_filings import _collect_filings
        records = []
        _collect_filings(records, "123", "Test", {}, "2013-01-01")
        assert len(records) == 0

    def test_mismatched_array_lengths(self):
        """Handle submissions API returning arrays of different lengths."""
        from pipeline.bdc_filings import _collect_filings
        records = []
        recent = {
            "form": ["10-K", "10-Q"],
            "filingDate": ["2023-12-15", "2023-09-15"],
            "accessionNumber": ["acc1"],  # shorter!
            "primaryDocument": ["d1.htm", "d2.htm"],
            "reportDate": ["2023-12-31"],
        }
        _collect_filings(records, "123", "Test", recent, "2013-01-01")
        # Should still collect both, with empty strings for missing values
        assert len(records) == 2
        assert records[0]["accession_number"] == "acc1"
        assert records[1]["accession_number"] == ""

    def test_amendment_forms_included(self):
        from pipeline.bdc_filings import _collect_filings
        records = []
        recent = {
            "form": ["10-Q/A"],
            "filingDate": ["2023-09-15"],
            "accessionNumber": ["acc-amend"],
            "primaryDocument": ["amend.htm"],
            "reportDate": ["2023-06-30"],
        }
        _collect_filings(records, "123", "Test", recent, "2013-01-01")
        assert len(records) == 1
        assert records[0]["form_type"] == "10-Q/A"


# ---------------------------------------------------------------------------
# 5. _parse_xbrl_contexts
# ---------------------------------------------------------------------------

class TestParseXBRLContexts:
    def test_minimal_xbrl(self):
        from pipeline.bdc_filings import _parse_xbrl_contexts
        tree = _parse_tree(XBRL_MINIMAL)
        contexts = _parse_xbrl_contexts(tree)

        # Should find at least 3 contexts
        assert len(contexts) >= 3

        # Entity context should exist but NOT be an investment
        assert "ctx_entity" in contexts
        assert contexts["ctx_entity"]["is_investment"] is False

        # Investment contexts should be marked
        assert "ctx_inv_001" in contexts
        assert contexts["ctx_inv_001"]["is_investment"] is True
        assert contexts["ctx_inv_001"]["investment_identifier"] == "Acme Corp - First Lien Term Loan"
        assert contexts["ctx_inv_001"]["period"] == "2023-12-31"

        assert "ctx_inv_002" in contexts
        assert contexts["ctx_inv_002"]["is_investment"] is True
        assert contexts["ctx_inv_002"]["investment_identifier"] == "Beta Inc - Senior Secured Note"

    def test_industry_extraction(self):
        from pipeline.bdc_filings import _parse_xbrl_contexts
        tree = _parse_tree(XBRL_MINIMAL)
        contexts = _parse_xbrl_contexts(tree)

        ctx1 = contexts["ctx_inv_001"]
        assert "Software" in ctx1["industry"] or "software" in ctx1["industry"].lower()

        ctx2 = contexts["ctx_inv_002"]
        assert "Healthcare" in ctx2["industry"] or "healthcare" in ctx2["industry"].lower()

    def test_investment_type_extraction(self):
        from pipeline.bdc_filings import _parse_xbrl_contexts
        tree = _parse_tree(XBRL_MINIMAL)
        contexts = _parse_xbrl_contexts(tree)

        ctx1 = contexts["ctx_inv_001"]
        assert "FirstLien" in ctx1["investment_type"] or "Debt" in ctx1["investment_type"]

    def test_affiliation_extraction(self):
        from pipeline.bdc_filings import _parse_xbrl_contexts
        tree = _parse_tree(XBRL_MINIMAL)
        contexts = _parse_xbrl_contexts(tree)

        ctx1 = contexts["ctx_inv_001"]
        assert "NonAffiliated" in ctx1["affiliation"] or "non" in ctx1["affiliation"].lower()

    def test_duration_period(self):
        """endDate should be used for duration periods."""
        from pipeline.bdc_filings import _parse_xbrl_contexts
        tree = _parse_tree(XBRL_DURATION_PERIOD)
        contexts = _parse_xbrl_contexts(tree)

        assert "ctx_dur_inv" in contexts
        assert contexts["ctx_dur_inv"]["period"] == "2023-12-31"
        assert contexts["ctx_dur_inv"]["is_investment"] is True
        assert contexts["ctx_dur_inv"]["investment_identifier"] == "Duration Corp"

    def test_no_investment_contexts(self):
        from pipeline.bdc_filings import _parse_xbrl_contexts
        tree = _parse_tree(XBRL_NO_INVESTMENTS)
        contexts = _parse_xbrl_contexts(tree)

        assert len(contexts) >= 1
        assert all(not c["is_investment"] for c in contexts.values())

    def test_alt_dimension_name(self):
        """InvestmentCompany axis should also be detected."""
        from pipeline.bdc_filings import _parse_xbrl_contexts
        tree = _parse_tree(XBRL_ALT_DIMENSION)
        contexts = _parse_xbrl_contexts(tree)

        assert "ctx_alt" in contexts
        assert contexts["ctx_alt"]["is_investment"] is True
        assert contexts["ctx_alt"]["investment_identifier"] == "AltCo Partners"
        assert contexts["ctx_alt"]["period"] == "2023-06-30"

    def test_dimensions_raw_populated(self):
        from pipeline.bdc_filings import _parse_xbrl_contexts
        tree = _parse_tree(XBRL_MINIMAL)
        contexts = _parse_xbrl_contexts(tree)

        raw = contexts["ctx_inv_001"]["dimensions_raw"]
        assert raw  # non-empty
        assert "investmentidentifier" in raw.lower()

    def test_date_like_investment_identifier_uses_portfolio_company_axis(self):
        from pipeline.bdc_filings import _parse_xbrl_contexts

        xml = textwrap.dedent("""\
            <xbrl
                xmlns="http://www.xbrl.org/2003/instance"
                xmlns:xbrli="http://www.xbrl.org/2003/instance"
                xmlns:xbrldi="http://xbrl.org/2006/xbrldi"
                xmlns:test="http://example.com/test">
                <xbrli:context id="ctx_bad_id">
                    <xbrli:entity>
                        <xbrli:identifier scheme="http://www.sec.gov/CIK">1</xbrli:identifier>
                        <xbrli:segment>
                            <xbrldi:typedMember dimension="test:InvestmentIdentifierAxis">
                                <test:InvestmentIdentifierDomain>01/03/2020</test:InvestmentIdentifierDomain>
                            </xbrldi:typedMember>
                            <xbrldi:explicitMember dimension="test:PortfolioCompaniesAxis">
                                test:FarmersBusinessNetworkIncMember
                            </xbrldi:explicitMember>
                        </xbrli:segment>
                    </xbrli:entity>
                    <xbrli:period><xbrli:instant>2024-03-31</xbrli:instant></xbrli:period>
                </xbrli:context>
            </xbrl>
        """)
        contexts = _parse_xbrl_contexts(_parse_tree(xml))

        assert contexts["ctx_bad_id"]["investment_identifier"] == (
            "FarmersBusinessNetworkIncMember"
        )

    def test_date_like_investment_identifier_kept_without_company_axis(self):
        from pipeline.bdc_filings import _parse_xbrl_contexts

        xml = textwrap.dedent("""\
            <xbrl
                xmlns="http://www.xbrl.org/2003/instance"
                xmlns:xbrli="http://www.xbrl.org/2003/instance"
                xmlns:xbrldi="http://xbrl.org/2006/xbrldi"
                xmlns:test="http://example.com/test">
                <xbrli:context id="ctx_date_only">
                    <xbrli:entity>
                        <xbrli:identifier scheme="http://www.sec.gov/CIK">1</xbrli:identifier>
                        <xbrli:segment>
                            <xbrldi:typedMember dimension="test:InvestmentIdentifierAxis">
                                <test:InvestmentIdentifierDomain>01/03/2020</test:InvestmentIdentifierDomain>
                            </xbrldi:typedMember>
                        </xbrli:segment>
                    </xbrli:entity>
                    <xbrli:period><xbrli:instant>2024-03-31</xbrli:instant></xbrli:period>
                </xbrli:context>
            </xbrl>
        """)
        contexts = _parse_xbrl_contexts(_parse_tree(xml))

        assert contexts["ctx_date_only"]["investment_identifier"] == "01/03/2020"


# ---------------------------------------------------------------------------
# 6. _extract_investment_facts
# ---------------------------------------------------------------------------

class TestExtractInvestmentFacts:
    def test_minimal_extraction(self):
        from pipeline.bdc_filings import _parse_xbrl_contexts, _extract_investment_facts
        tree = _parse_tree(XBRL_MINIMAL)
        contexts = _parse_xbrl_contexts(tree)
        facts = _extract_investment_facts(tree, contexts)

        # Should get 2 investment positions
        assert len(facts) == 2

        # Find Acme Corp record
        acme = [f for f in facts if "Acme" in f.get("investment_identifier", "")]
        assert len(acme) == 1
        acme = acme[0]
        assert acme["fair_value"] == 15000000.0
        assert acme["cost"] == 14500000.0
        assert acme["interest_rate"] == 0.0925
        assert acme["basis_spread"] == 0.0575
        assert acme["maturity_date"] == "2028-06-15"
        assert acme["principal_amount"] == 15000000.0
        assert acme["pct_of_net_assets"] == 0.0023

        # Find Beta Inc record
        beta = [f for f in facts if "Beta" in f.get("investment_identifier", "")]
        assert len(beta) == 1
        beta = beta[0]
        assert beta["fair_value"] == 8000000.0
        assert beta["cost"] == 8200000.0
        assert beta["shares_held"] == 50000.0

    def test_nil_elements_skipped(self):
        from pipeline.bdc_filings import _parse_xbrl_contexts, _extract_investment_facts
        tree = _parse_tree(XBRL_MINIMAL)
        contexts = _parse_xbrl_contexts(tree)
        facts = _extract_investment_facts(tree, contexts)

        acme = [f for f in facts if "Acme" in f.get("investment_identifier", "")][0]
        # interest_rate_floor was xsi:nil="true" — should be None
        assert acme.get("interest_rate_floor") is None

    def test_entity_context_excluded(self):
        """Facts on non-investment contexts must not appear."""
        from pipeline.bdc_filings import _parse_xbrl_contexts, _extract_investment_facts
        tree = _parse_tree(XBRL_MINIMAL)
        contexts = _parse_xbrl_contexts(tree)
        facts = _extract_investment_facts(tree, contexts)

        # The entity-level fair_value of 999999 should NOT appear in any record
        all_fv = [f["fair_value"] for f in facts if f.get("fair_value") is not None]
        assert 999999.0 not in all_fv

    def test_no_investment_contexts_returns_empty(self):
        from pipeline.bdc_filings import _parse_xbrl_contexts, _extract_investment_facts
        tree = _parse_tree(XBRL_NO_INVESTMENTS)
        contexts = _parse_xbrl_contexts(tree)
        facts = _extract_investment_facts(tree, contexts)
        assert facts == []

    def test_duration_period_facts(self):
        from pipeline.bdc_filings import _parse_xbrl_contexts, _extract_investment_facts
        tree = _parse_tree(XBRL_DURATION_PERIOD)
        contexts = _parse_xbrl_contexts(tree)
        facts = _extract_investment_facts(tree, contexts)

        assert len(facts) == 1
        assert facts[0]["realized_gain_loss"] == -250000.0
        assert facts[0]["investment_identifier"] == "Duration Corp"
        assert facts[0]["period"] == "2023-12-31"

    def test_variant_concepts(self):
        from pipeline.bdc_filings import _parse_xbrl_contexts, _extract_investment_facts
        tree = _parse_tree(XBRL_VARIANT_CONCEPTS)
        contexts = _parse_xbrl_contexts(tree)
        facts = _extract_investment_facts(tree, contexts)

        assert len(facts) == 1
        f = facts[0]
        assert f["pct_of_net_assets"] == 0.015
        assert f["face_amount"] == 5000000.0
        assert f["pik_rate"] == 0.02
        assert f["acquisition_date"] == "2022-03-15"
        assert f["unrealized_gain_loss"] == -120000.0

    def test_alt_dimension_facts(self):
        from pipeline.bdc_filings import _parse_xbrl_contexts, _extract_investment_facts
        tree = _parse_tree(XBRL_ALT_DIMENSION)
        contexts = _parse_xbrl_contexts(tree)
        facts = _extract_investment_facts(tree, contexts)

        assert len(facts) == 1
        assert facts[0]["fair_value"] == 3000000.0
        assert facts[0]["cost"] == 2900000.0
        assert facts[0]["investment_identifier"] == "AltCo Partners"

    def test_all_value_columns_present(self):
        """Every output record should have all _VALUE_COLUMNS keys."""
        from pipeline.bdc_filings import _parse_xbrl_contexts, _extract_investment_facts, _VALUE_COLUMNS
        tree = _parse_tree(XBRL_MINIMAL)
        contexts = _parse_xbrl_contexts(tree)
        facts = _extract_investment_facts(tree, contexts)

        for record in facts:
            for col in _VALUE_COLUMNS:
                assert col in record, f"Missing column {col} in record"


# ---------------------------------------------------------------------------
# 6b. Decimals normalization in _extract_investment_facts
# ---------------------------------------------------------------------------

# Filing with mixed decimals: 5 positions at decimals="-3" (correct) and
# 1 position at decimals="-6" (1000x inflated -- filer error).
XBRL_MIXED_DECIMALS = textwrap.dedent("""\
    <?xml version="1.0" encoding="UTF-8"?>
    <xbrl
        xmlns="http://www.xbrl.org/2003/instance"
        xmlns:xbrli="http://www.xbrl.org/2003/instance"
        xmlns:xbrldi="http://xbrl.org/2006/xbrldi"
        xmlns:cik="http://example.com/cik"
        xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">

        <!-- 5 normal positions (decimals="-3") -->
        <xbrli:context id="ctx_a">
            <xbrli:entity>
                <xbrli:identifier scheme="http://www.sec.gov/CIK">0001234567</xbrli:identifier>
                <xbrli:segment>
                    <xbrldi:typedMember dimension="cik:InvestmentIdentifierAxis">
                        <cik:InvestmentIdentifierDomain>Normal Corp A</cik:InvestmentIdentifierDomain>
                    </xbrldi:typedMember>
                </xbrli:segment>
            </xbrli:entity>
            <xbrli:period><xbrli:instant>2023-03-31</xbrli:instant></xbrli:period>
        </xbrli:context>
        <xbrli:context id="ctx_b">
            <xbrli:entity>
                <xbrli:identifier scheme="http://www.sec.gov/CIK">0001234567</xbrli:identifier>
                <xbrli:segment>
                    <xbrldi:typedMember dimension="cik:InvestmentIdentifierAxis">
                        <cik:InvestmentIdentifierDomain>Normal Corp B</cik:InvestmentIdentifierDomain>
                    </xbrldi:typedMember>
                </xbrli:segment>
            </xbrli:entity>
            <xbrli:period><xbrli:instant>2023-03-31</xbrli:instant></xbrli:period>
        </xbrli:context>
        <xbrli:context id="ctx_c">
            <xbrli:entity>
                <xbrli:identifier scheme="http://www.sec.gov/CIK">0001234567</xbrli:identifier>
                <xbrli:segment>
                    <xbrldi:typedMember dimension="cik:InvestmentIdentifierAxis">
                        <cik:InvestmentIdentifierDomain>Normal Corp C</cik:InvestmentIdentifierDomain>
                    </xbrldi:typedMember>
                </xbrli:segment>
            </xbrli:entity>
            <xbrli:period><xbrli:instant>2023-03-31</xbrli:instant></xbrli:period>
        </xbrli:context>
        <xbrli:context id="ctx_d">
            <xbrli:entity>
                <xbrli:identifier scheme="http://www.sec.gov/CIK">0001234567</xbrli:identifier>
                <xbrli:segment>
                    <xbrldi:typedMember dimension="cik:InvestmentIdentifierAxis">
                        <cik:InvestmentIdentifierDomain>Normal Corp D</cik:InvestmentIdentifierDomain>
                    </xbrldi:typedMember>
                </xbrli:segment>
            </xbrli:entity>
            <xbrli:period><xbrli:instant>2023-03-31</xbrli:instant></xbrli:period>
        </xbrli:context>
        <xbrli:context id="ctx_e">
            <xbrli:entity>
                <xbrli:identifier scheme="http://www.sec.gov/CIK">0001234567</xbrli:identifier>
                <xbrli:segment>
                    <xbrldi:typedMember dimension="cik:InvestmentIdentifierAxis">
                        <cik:InvestmentIdentifierDomain>Normal Corp E</cik:InvestmentIdentifierDomain>
                    </xbrldi:typedMember>
                </xbrli:segment>
            </xbrli:entity>
            <xbrli:period><xbrli:instant>2023-03-31</xbrli:instant></xbrli:period>
        </xbrli:context>

        <!-- 1 outlier position (decimals="-6", value 1000x too large) -->
        <xbrli:context id="ctx_outlier">
            <xbrli:entity>
                <xbrli:identifier scheme="http://www.sec.gov/CIK">0001234567</xbrli:identifier>
                <xbrli:segment>
                    <xbrldi:typedMember dimension="cik:InvestmentIdentifierAxis">
                        <cik:InvestmentIdentifierDomain>Outlier Corp</cik:InvestmentIdentifierDomain>
                    </xbrldi:typedMember>
                </xbrli:segment>
            </xbrli:entity>
            <xbrli:period><xbrli:instant>2023-03-31</xbrli:instant></xbrli:period>
        </xbrli:context>

        <!-- Normal facts (decimals="-3") -->
        <cik:InvestmentOwnedAtFairValue contextRef="ctx_a" unitRef="usd" decimals="-3">10000000</cik:InvestmentOwnedAtFairValue>
        <cik:InvestmentOwnedAtCost contextRef="ctx_a" unitRef="usd" decimals="-3">9500000</cik:InvestmentOwnedAtCost>
        <cik:InvestmentOwnedAtFairValue contextRef="ctx_b" unitRef="usd" decimals="-3">20000000</cik:InvestmentOwnedAtFairValue>
        <cik:InvestmentOwnedAtCost contextRef="ctx_b" unitRef="usd" decimals="-3">19000000</cik:InvestmentOwnedAtCost>
        <cik:InvestmentOwnedAtFairValue contextRef="ctx_c" unitRef="usd" decimals="-3">15000000</cik:InvestmentOwnedAtFairValue>
        <cik:InvestmentOwnedAtFairValue contextRef="ctx_d" unitRef="usd" decimals="-3">12000000</cik:InvestmentOwnedAtFairValue>
        <cik:InvestmentOwnedAtFairValue contextRef="ctx_e" unitRef="usd" decimals="-3">8000000</cik:InvestmentOwnedAtFairValue>

        <!-- Outlier facts (decimals="-6", 1000x inflated) -->
        <cik:InvestmentOwnedAtFairValue contextRef="ctx_outlier" unitRef="usd" decimals="-6">25000000000</cik:InvestmentOwnedAtFairValue>
        <cik:InvestmentOwnedAtCost contextRef="ctx_outlier" unitRef="usd" decimals="-6">24000000000</cik:InvestmentOwnedAtCost>

        <!-- Non-monetary fact on outlier (should NOT be corrected) -->
        <cik:InvestmentInterestRate contextRef="ctx_outlier" unitRef="pure" decimals="4">0.085</cik:InvestmentInterestRate>
    </xbrl>
""")

# Filing where ALL facts have the same decimals -- no correction needed.
XBRL_UNIFORM_DECIMALS = textwrap.dedent("""\
    <?xml version="1.0" encoding="UTF-8"?>
    <xbrl
        xmlns="http://www.xbrl.org/2003/instance"
        xmlns:xbrli="http://www.xbrl.org/2003/instance"
        xmlns:xbrldi="http://xbrl.org/2006/xbrldi"
        xmlns:cik="http://example.com/cik">

        <xbrli:context id="ctx_u1">
            <xbrli:entity>
                <xbrli:identifier scheme="http://www.sec.gov/CIK">0001234567</xbrli:identifier>
                <xbrli:segment>
                    <xbrldi:typedMember dimension="cik:InvestmentIdentifierAxis">
                        <cik:InvestmentIdentifierDomain>Uniform A</cik:InvestmentIdentifierDomain>
                    </xbrldi:typedMember>
                </xbrli:segment>
            </xbrli:entity>
            <xbrli:period><xbrli:instant>2023-06-30</xbrli:instant></xbrli:period>
        </xbrli:context>
        <xbrli:context id="ctx_u2">
            <xbrli:entity>
                <xbrli:identifier scheme="http://www.sec.gov/CIK">0001234567</xbrli:identifier>
                <xbrli:segment>
                    <xbrldi:typedMember dimension="cik:InvestmentIdentifierAxis">
                        <cik:InvestmentIdentifierDomain>Uniform B</cik:InvestmentIdentifierDomain>
                    </xbrldi:typedMember>
                </xbrli:segment>
            </xbrli:entity>
            <xbrli:period><xbrli:instant>2023-06-30</xbrli:instant></xbrli:period>
        </xbrli:context>
        <xbrli:context id="ctx_u3">
            <xbrli:entity>
                <xbrli:identifier scheme="http://www.sec.gov/CIK">0001234567</xbrli:identifier>
                <xbrli:segment>
                    <xbrldi:typedMember dimension="cik:InvestmentIdentifierAxis">
                        <cik:InvestmentIdentifierDomain>Uniform C</cik:InvestmentIdentifierDomain>
                    </xbrldi:typedMember>
                </xbrli:segment>
            </xbrli:entity>
            <xbrli:period><xbrli:instant>2023-06-30</xbrli:instant></xbrli:period>
        </xbrli:context>

        <cik:InvestmentOwnedAtFairValue contextRef="ctx_u1" unitRef="usd" decimals="-3">10000000</cik:InvestmentOwnedAtFairValue>
        <cik:InvestmentOwnedAtCost contextRef="ctx_u1" unitRef="usd" decimals="-3">9000000</cik:InvestmentOwnedAtCost>
        <cik:InvestmentOwnedAtFairValue contextRef="ctx_u2" unitRef="usd" decimals="-3">20000000</cik:InvestmentOwnedAtFairValue>
        <cik:InvestmentOwnedAtCost contextRef="ctx_u2" unitRef="usd" decimals="-3">19000000</cik:InvestmentOwnedAtCost>
        <cik:InvestmentOwnedAtFairValue contextRef="ctx_u3" unitRef="usd" decimals="-3">30000000</cik:InvestmentOwnedAtFairValue>
        <cik:InvestmentOwnedAtCost contextRef="ctx_u3" unitRef="usd" decimals="-3">28000000</cik:InvestmentOwnedAtCost>
    </xbrl>
""")


class TestDecimalsNormalization:
    """Tests for mixed-decimals normalization in _extract_investment_facts."""

    def test_outlier_corrected(self):
        """Facts with decimals=-6 amid dominant -3 are scaled down 1000x."""
        from pipeline.bdc_filings import _parse_xbrl_contexts, _extract_investment_facts
        tree = _parse_tree(XBRL_MIXED_DECIMALS)
        contexts = _parse_xbrl_contexts(tree)
        facts = _extract_investment_facts(tree, contexts)

        outlier = [f for f in facts if "Outlier" in f.get("investment_identifier", "")]
        assert len(outlier) == 1
        o = outlier[0]
        # 25000000000 * 10^(-6 - (-3)) = 25000000000 * 10^-3 = 25000000
        assert o["fair_value"] == pytest.approx(25000000.0, rel=1e-6)
        assert o["cost"] == pytest.approx(24000000.0, rel=1e-6)

    def test_normal_positions_unchanged(self):
        """Positions with dominant decimals are not modified."""
        from pipeline.bdc_filings import _parse_xbrl_contexts, _extract_investment_facts
        tree = _parse_tree(XBRL_MIXED_DECIMALS)
        contexts = _parse_xbrl_contexts(tree)
        facts = _extract_investment_facts(tree, contexts)

        normal_a = [f for f in facts if "Normal Corp A" in f.get("investment_identifier", "")]
        assert len(normal_a) == 1
        assert normal_a[0]["fair_value"] == 10000000.0
        assert normal_a[0]["cost"] == 9500000.0

    def test_non_monetary_not_corrected(self):
        """Non-monetary fields (rates, dates) are never scaled."""
        from pipeline.bdc_filings import _parse_xbrl_contexts, _extract_investment_facts
        tree = _parse_tree(XBRL_MIXED_DECIMALS)
        contexts = _parse_xbrl_contexts(tree)
        facts = _extract_investment_facts(tree, contexts)

        outlier = [f for f in facts if "Outlier" in f.get("investment_identifier", "")]
        assert outlier[0]["interest_rate"] == 0.085  # unchanged

    def test_uniform_decimals_no_change(self):
        """When all facts share the same decimals, nothing changes."""
        from pipeline.bdc_filings import _parse_xbrl_contexts, _extract_investment_facts
        tree = _parse_tree(XBRL_UNIFORM_DECIMALS)
        contexts = _parse_xbrl_contexts(tree)
        facts = _extract_investment_facts(tree, contexts)

        assert len(facts) == 3
        fv_values = sorted([f["fair_value"] for f in facts])
        assert fv_values == [10000000.0, 20000000.0, 30000000.0]

    def test_too_few_facts_skips_normalization(self):
        """Fewer than 5 monetary facts -> no normalization applied."""
        from pipeline.bdc_filings import _parse_xbrl_contexts, _extract_investment_facts
        # XBRL_ALT_DIMENSION has just 2 monetary facts (FV + cost) -- below threshold
        tree = _parse_tree(XBRL_ALT_DIMENSION)
        contexts = _parse_xbrl_contexts(tree)
        facts = _extract_investment_facts(tree, contexts)

        assert len(facts) == 1
        assert facts[0]["fair_value"] == 3000000.0  # raw value preserved

    def test_precision_only_difference_not_corrected(self):
        """When decimals differ but values are NOT inflated, skip correction.

        This covers CIK 1521945 (Prospect Floating Rate) where dominant is
        decimals=0 and a few facts have decimals=-3 with normal-range values.
        """
        from pipeline.bdc_filings import _parse_xbrl_contexts, _extract_investment_facts

        # 5 positions at decimals=0, 1 at decimals=-3 with a normal value
        xml = textwrap.dedent("""\
            <?xml version="1.0" encoding="UTF-8"?>
            <xbrl
                xmlns="http://www.xbrl.org/2003/instance"
                xmlns:xbrli="http://www.xbrl.org/2003/instance"
                xmlns:xbrldi="http://xbrl.org/2006/xbrldi"
                xmlns:cik="http://example.com/cik">

                <xbrli:context id="ctx_p1">
                    <xbrli:entity>
                        <xbrli:identifier scheme="http://www.sec.gov/CIK">0001521945</xbrli:identifier>
                        <xbrli:segment>
                            <xbrldi:typedMember dimension="cik:InvestmentIdentifierAxis">
                                <cik:InvestmentIdentifierDomain>Position A</cik:InvestmentIdentifierDomain>
                            </xbrldi:typedMember>
                        </xbrli:segment>
                    </xbrli:entity>
                    <xbrli:period><xbrli:instant>2024-06-30</xbrli:instant></xbrli:period>
                </xbrli:context>
                <xbrli:context id="ctx_p2">
                    <xbrli:entity>
                        <xbrli:identifier scheme="http://www.sec.gov/CIK">0001521945</xbrli:identifier>
                        <xbrli:segment>
                            <xbrldi:typedMember dimension="cik:InvestmentIdentifierAxis">
                                <cik:InvestmentIdentifierDomain>Position B</cik:InvestmentIdentifierDomain>
                            </xbrldi:typedMember>
                        </xbrli:segment>
                    </xbrli:entity>
                    <xbrli:period><xbrli:instant>2024-06-30</xbrli:instant></xbrli:period>
                </xbrli:context>
                <xbrli:context id="ctx_p3">
                    <xbrli:entity>
                        <xbrli:identifier scheme="http://www.sec.gov/CIK">0001521945</xbrli:identifier>
                        <xbrli:segment>
                            <xbrldi:typedMember dimension="cik:InvestmentIdentifierAxis">
                                <cik:InvestmentIdentifierDomain>Position C</cik:InvestmentIdentifierDomain>
                            </xbrldi:typedMember>
                        </xbrli:segment>
                    </xbrli:entity>
                    <xbrli:period><xbrli:instant>2024-06-30</xbrli:instant></xbrli:period>
                </xbrli:context>
                <xbrli:context id="ctx_p4">
                    <xbrli:entity>
                        <xbrli:identifier scheme="http://www.sec.gov/CIK">0001521945</xbrli:identifier>
                        <xbrli:segment>
                            <xbrldi:typedMember dimension="cik:InvestmentIdentifierAxis">
                                <cik:InvestmentIdentifierDomain>Position D</cik:InvestmentIdentifierDomain>
                            </xbrldi:typedMember>
                        </xbrli:segment>
                    </xbrli:entity>
                    <xbrli:period><xbrli:instant>2024-06-30</xbrli:instant></xbrli:period>
                </xbrli:context>
                <xbrli:context id="ctx_p5">
                    <xbrli:entity>
                        <xbrli:identifier scheme="http://www.sec.gov/CIK">0001521945</xbrli:identifier>
                        <xbrli:segment>
                            <xbrldi:typedMember dimension="cik:InvestmentIdentifierAxis">
                                <cik:InvestmentIdentifierDomain>Position E</cik:InvestmentIdentifierDomain>
                            </xbrldi:typedMember>
                        </xbrli:segment>
                    </xbrli:entity>
                    <xbrli:period><xbrli:instant>2024-06-30</xbrli:instant></xbrli:period>
                </xbrli:context>
                <xbrli:context id="ctx_diff">
                    <xbrli:entity>
                        <xbrli:identifier scheme="http://www.sec.gov/CIK">0001521945</xbrli:identifier>
                        <xbrli:segment>
                            <xbrldi:typedMember dimension="cik:InvestmentIdentifierAxis">
                                <cik:InvestmentIdentifierDomain>Position DiffPrec</cik:InvestmentIdentifierDomain>
                            </xbrldi:typedMember>
                        </xbrli:segment>
                    </xbrli:entity>
                    <xbrli:period><xbrli:instant>2024-06-30</xbrli:instant></xbrli:period>
                </xbrli:context>

                <!-- 5 facts at decimals=0 -->
                <cik:InvestmentOwnedAtFairValue contextRef="ctx_p1" unitRef="usd" decimals="0">15000000</cik:InvestmentOwnedAtFairValue>
                <cik:InvestmentOwnedAtFairValue contextRef="ctx_p2" unitRef="usd" decimals="0">20000000</cik:InvestmentOwnedAtFairValue>
                <cik:InvestmentOwnedAtFairValue contextRef="ctx_p3" unitRef="usd" decimals="0">12000000</cik:InvestmentOwnedAtFairValue>
                <cik:InvestmentOwnedAtFairValue contextRef="ctx_p4" unitRef="usd" decimals="0">8000000</cik:InvestmentOwnedAtFairValue>
                <cik:InvestmentOwnedAtFairValue contextRef="ctx_p5" unitRef="usd" decimals="0">25000000</cik:InvestmentOwnedAtFairValue>

                <!-- 1 fact at decimals=-3 with NORMAL value (not inflated) -->
                <cik:InvestmentOwnedAtFairValue contextRef="ctx_diff" unitRef="usd" decimals="-3">18000000</cik:InvestmentOwnedAtFairValue>
            </xbrl>
        """)

        tree = _parse_tree(xml)
        contexts = _parse_xbrl_contexts(tree)
        facts = _extract_investment_facts(tree, contexts)

        diff_pos = [f for f in facts if "DiffPrec" in f.get("investment_identifier", "")]
        assert len(diff_pos) == 1
        # Value should NOT be corrected -- 18M is in-range (not 100x the median)
        assert diff_pos[0]["fair_value"] == 18000000.0


STEPSTONE_FIRST_LIEN_IDENTIFIER = (
    "Non-Controlled, Non-Affiliated Debt Investments | First Lien Senior Secured | "
    "Insurance | Denali Topco LLC Initial Term Loan | SOFR + 5.50% | 7/12/29"
)


def _stepstone_2025q4_record(**overrides):
    record = {
        "cik": "0001950803",
        "entity_name": "Stepstone Private Credit Fund LLC",
        "accession_number": "0001193125-26-128890",
        "report_date": "2025-12-31",
        "period": "2025-12-31",
        "investment_identifier": STEPSTONE_FIRST_LIEN_IDENTIFIER,
        "fair_value": 12541.0,
        "cost": 12541.0,
        "principal_amount": 12541.0,
        "interest_rate": 0.0942,
        "pct_of_net_assets": 0.0067,
    }
    record.update(overrides)
    return record


class TestStepstone2025Q4ScaleCorrection:
    def test_first_lien_leaf_monetary_fields_scaled(self):
        from pipeline.bdc_filings import _apply_stepstone_2025q4_monetary_scale_correction

        records = [_stepstone_2025q4_record()]

        _apply_stepstone_2025q4_monetary_scale_correction(records)

        row = records[0]
        assert row["fair_value"] == 12541000.0
        assert row["cost"] == 12541000.0
        assert row["principal_amount"] == 12541000.0
        assert row["interest_rate"] == 0.0942
        assert row["pct_of_net_assets"] == 0.0067

    def test_non_stepstone_cik_not_scaled(self):
        from pipeline.bdc_filings import _apply_stepstone_2025q4_monetary_scale_correction

        records = [_stepstone_2025q4_record(cik="0000000100")]

        _apply_stepstone_2025q4_monetary_scale_correction(records)

        assert records[0]["fair_value"] == 12541.0

    def test_non_first_lien_stepstone_row_not_scaled(self):
        from pipeline.bdc_filings import _apply_stepstone_2025q4_monetary_scale_correction

        records = [
            _stepstone_2025q4_record(
                investment_identifier=(
                    "Non-Controlled, Non-Affiliated Debt Investments | "
                    "Second Lien Senior Secured | Software | Borrower LLC Term Loan | "
                    "SOFR + 8.00% | 7/12/29"
                )
            )
        ]

        _apply_stepstone_2025q4_monetary_scale_correction(records)

        assert records[0]["fair_value"] == 12541.0

    def test_large_value_in_affected_filing_not_scaled(self):
        from pipeline.bdc_filings import _apply_stepstone_2025q4_monetary_scale_correction

        records = [_stepstone_2025q4_record(fair_value=12541000.0)]

        _apply_stepstone_2025q4_monetary_scale_correction(records)

        assert records[0]["fair_value"] == 12541000.0

    def test_pct_consistent_small_value_not_scaled(self):
        from pipeline.bdc_filings import _apply_stepstone_2025q4_monetary_scale_correction

        records = [
            _stepstone_2025q4_record(
                fair_value=250000.0,
                cost=250000.0,
                principal_amount=250000.0,
                pct_of_net_assets=0.000134,
            )
        ]

        _apply_stepstone_2025q4_monetary_scale_correction(records)

        assert records[0]["fair_value"] == 250000.0
        assert records[0]["cost"] == 250000.0
        assert records[0]["principal_amount"] == 250000.0


# ---------------------------------------------------------------------------
# 7. _parse_single_filing (end-to-end single file)
# ---------------------------------------------------------------------------

class TestParseSingleFiling:
    def test_with_valid_file(self, tmp_dir):
        from pipeline.bdc_filings import _parse_single_filing
        xml_path = _write_xml(tmp_dir, XBRL_MINIMAL)
        meta = {
            "cik": "1418076",
            "entity_name": "Ares Capital Corp",
            "accession_number": "0001-23-000001",
            "form_type": "10-K",
            "filing_date": "2024-02-28",
            "report_date": "2023-12-31",
        }
        results = _parse_single_filing(str(xml_path), meta)

        assert len(results) == 2
        # Verify metadata propagation
        for r in results:
            assert r["cik"] == "1418076"
            assert r["entity_name"] == "Ares Capital Corp"
            assert r["accession_number"] == "0001-23-000001"
            assert r["form_type"] == "10-K"
            assert r["filing_date"] == "2024-02-28"
            assert r["report_date"] == "2023-12-31"

    def test_with_nonexistent_file(self, tmp_dir):
        from pipeline.bdc_filings import _parse_single_filing
        results = _parse_single_filing(str(tmp_dir / "nonexistent.xml"), {})
        assert results == []

    def test_with_invalid_xml(self, tmp_dir):
        from pipeline.bdc_filings import _parse_single_filing
        bad_xml = tmp_dir / "bad.xml"
        bad_xml.write_text("<not<valid>xml", encoding="utf-8")
        results = _parse_single_filing(str(bad_xml), {})
        assert results == []

    def test_with_no_investments(self, tmp_dir):
        from pipeline.bdc_filings import _parse_single_filing
        xml_path = _write_xml(tmp_dir, XBRL_NO_INVESTMENTS)
        results = _parse_single_filing(str(xml_path), {"cik": "999"})
        assert results == []


# ---------------------------------------------------------------------------
# 8. _build_filings_index (mocked client)
# ---------------------------------------------------------------------------

class TestBuildFilingsIndex:
    def _mock_client(self):
        client = MagicMock(spec=EdgarClient)
        client.get_company_submissions.return_value = {
            "name": "Test BDC Corp",
            "filings": {
                "recent": {
                    "form": ["10-K", "10-Q", "8-K"],
                    "filingDate": ["2023-12-15", "2023-09-15", "2023-07-01"],
                    "accessionNumber": ["acc-001", "acc-002", "acc-003"],
                    "primaryDocument": ["d1.htm", "d2.htm", "d3.htm"],
                    "reportDate": ["2023-12-31", "2023-09-30", "2023-06-30"],
                },
                "files": [],
            },
        }
        return client

    @patch("pipeline.bdc_filings.BDC_FILINGS_INDEX_FILE")
    def test_builds_index(self, mock_path, tmp_dir):
        from pipeline.bdc_filings import _build_filings_index

        output_file = tmp_dir / "filings_index.csv"
        mock_path.__class__ = type(output_file)
        # Make it so the cache file doesn't exist
        mock_path.exists.return_value = False

        client = self._mock_client()
        universe = pd.DataFrame({"cik": ["1418076"]})

        with patch("pipeline.bdc_filings.BDC_FILINGS_INDEX_FILE", output_file):
            result = _build_filings_index(client, universe)

        assert len(result) == 2  # 10-K and 10-Q (8-K filtered out)
        assert set(result["form_type"]) == {"10-K", "10-Q"}
        assert output_file.exists()

    @patch("pipeline.bdc_filings.BDC_FILINGS_INDEX_FILE")
    def test_cache_fresh(self, mock_path, tmp_dir):
        from pipeline.bdc_filings import _build_filings_index

        # Create a fresh cache file
        cache_file = tmp_dir / "filings_index.csv"
        pd.DataFrame({
            "cik": ["123"],
            "entity_name": ["Cached Corp"],
            "accession_number": ["cached-acc"],
            "form_type": ["10-K"],
            "filing_date": ["2023-12-15"],
            "report_date": ["2023-12-31"],
            "primary_document": ["d.htm"],
        }).to_csv(cache_file, index=False)

        client = self._mock_client()
        universe = pd.DataFrame({"cik": ["123"]})

        with patch("pipeline.bdc_filings.BDC_FILINGS_INDEX_FILE", cache_file):
            result = _build_filings_index(client, universe)

        # Should load from cache, NOT call the client
        client.get_company_submissions.assert_not_called()
        assert len(result) == 1
        assert result.iloc[0]["entity_name"] == "Cached Corp"

    @patch("pipeline.bdc_filings.BDC_FILINGS_INDEX_FILE")
    def test_pagination(self, mock_path, tmp_dir):
        from pipeline.bdc_filings import _build_filings_index

        output_file = tmp_dir / "filings_index.csv"
        mock_path.exists.return_value = False

        client = MagicMock(spec=EdgarClient)
        client.get_company_submissions.return_value = {
            "name": "Paged BDC",
            "filings": {
                "recent": {
                    "form": ["10-K"],
                    "filingDate": ["2023-12-15"],
                    "accessionNumber": ["acc-recent"],
                    "primaryDocument": ["d.htm"],
                    "reportDate": ["2023-12-31"],
                },
                "files": [{"name": "CIK0000123456-submissions-002.json"}],
            },
        }
        # The paginated file returns additional filings
        client.get_json.return_value = {
            "form": ["10-Q"],
            "filingDate": ["2023-09-15"],
            "accessionNumber": ["acc-page2"],
            "primaryDocument": ["d2.htm"],
            "reportDate": ["2023-09-30"],
        }

        universe = pd.DataFrame({"cik": ["123456"]})

        with patch("pipeline.bdc_filings.BDC_FILINGS_INDEX_FILE", output_file):
            result = _build_filings_index(client, universe)

        assert len(result) == 2
        assert set(result["accession_number"]) == {"acc-recent", "acc-page2"}

    @patch("pipeline.bdc_filings.BDC_FILINGS_INDEX_FILE")
    def test_api_error_handled(self, mock_path, tmp_dir):
        from pipeline.bdc_filings import _build_filings_index

        output_file = tmp_dir / "filings_index.csv"
        mock_path.exists.return_value = False

        client = MagicMock(spec=EdgarClient)
        client.get_company_submissions.side_effect = Exception("API error")

        universe = pd.DataFrame({"cik": ["999"]})

        with patch("pipeline.bdc_filings.BDC_FILINGS_INDEX_FILE", output_file):
            result = _build_filings_index(client, universe)

        assert result.empty

    def test_merge_preserves_other_ciks(self, tmp_dir):
        """When building index for a subset, rows for other CIKs are preserved."""
        from pipeline.bdc_filings import _build_filings_index

        output_file = tmp_dir / "filings_index.csv"

        # Pre-populate with CIK 999 data (simulating a full prior run)
        pd.DataFrame({
            "cik": ["999", "999"],
            "entity_name": ["Existing Corp", "Existing Corp"],
            "accession_number": ["old-acc-1", "old-acc-2"],
            "form_type": ["10-K", "10-Q"],
            "filing_date": ["2023-06-15", "2023-12-15"],
            "report_date": ["2023-06-30", "2023-12-31"],
            "primary_document": ["d.htm", "d2.htm"],
            "xbrl_download_status": ["cached", "not_found"],
            "xbrl_local_path": ["/some/path.xml", ""],
        }).to_csv(output_file, index=False)
        # Make the file appear old so the 24h cache check is bypassed
        import os
        old_time = os.path.getmtime(str(output_file)) - 90_000
        os.utime(str(output_file), (old_time, old_time))

        client = self._mock_client()  # returns data for CIK 1418076
        universe = pd.DataFrame({"cik": ["1418076"]})

        with patch("pipeline.bdc_filings.BDC_FILINGS_INDEX_FILE", output_file):
            result = _build_filings_index(client, universe)

        # Result should have BOTH CIK 999 (preserved) and CIK 1418076 (new)
        ciks = set(result["cik"].astype(str).str.strip())
        assert "999" in ciks, "Existing CIK 999 should be preserved"
        assert "1418076" in ciks, "New CIK 1418076 should be added"

        # CIK 999 rows should retain xbrl_download_status from the old file
        cik999 = result[result["cik"].astype(str).str.strip() == "999"]
        assert len(cik999) == 2
        assert list(cik999["xbrl_download_status"]) == ["cached", "not_found"]

    def test_download_skips_preserved_rows(self, tmp_dir):
        """_download_xbrl_instances skips rows that already have a status."""
        from pipeline.bdc_filings import _download_xbrl_instances

        output_file = tmp_dir / "idx.csv"

        # DataFrame with one pre-existing row (preserved) and one new row
        index = pd.DataFrame({
            "cik": ["999", "1418076"],
            "accession_number": ["old-acc-1", "new-acc-1"],
            "primary_document": ["d.htm", "d2.htm"],
            "form_type": ["10-K", "10-K"],
            "xbrl_download_status": ["not_found", pd.NA],
            "xbrl_local_path": ["", pd.NA],
        })

        # Client should only be called for the NEW row (CIK 1418076)
        client = MagicMock(spec=EdgarClient)
        client.get_safe.return_value = None  # nothing found

        with (
            patch("pipeline.bdc_filings.BDC_FILINGS_INDEX_FILE", output_file),
            patch("pipeline.bdc_filings.BDC_XBRL_CACHE_DIR", tmp_dir / "xbrl"),
        ):
            result = _download_xbrl_instances(client, index)

        # CIK 999 should keep its old "not_found" status
        row999 = result[result["cik"] == "999"].iloc[0]
        assert row999["xbrl_download_status"] == "not_found"

        # Client should have been called for CIK 1418076 only
        # (3 attempts: _htm.xml, .xml, filing index)
        assert client.get_safe.call_count >= 1


# ---------------------------------------------------------------------------
# 9. _download_xbrl_instances (mocked client)
# ---------------------------------------------------------------------------

class TestDownloadXBRLInstances:
    @patch("pipeline.bdc_filings.BDC_FILINGS_INDEX_FILE")
    @patch("pipeline.bdc_filings.BDC_XBRL_CACHE_DIR")
    def test_download_attempt1_success(self, mock_cache_dir, mock_index_file, tmp_dir):
        from pipeline.bdc_filings import _download_xbrl_instances

        mock_cache_dir.__truediv__ = lambda self, x: tmp_dir / x
        mock_index_file.__class__ = type(tmp_dir / "idx.csv")

        index = pd.DataFrame({
            "cik": ["1418076"],
            "accession_number": ["0001-23-000001"],
            "primary_document": ["filing.htm"],
            "form_type": ["10-K"],
        })

        # Mock client: first get_safe (attempt 1 — _htm.xml) succeeds
        client = MagicMock(spec=EdgarClient)
        resp = MagicMock()
        resp.content = b"x" * 2000  # > 1KB
        client.get_safe.return_value = resp

        with (
            patch("pipeline.bdc_filings.BDC_XBRL_CACHE_DIR", tmp_dir),
            patch("pipeline.bdc_filings.BDC_FILINGS_INDEX_FILE", tmp_dir / "idx.csv"),
        ):
            result = _download_xbrl_instances(client, index)

        assert result.iloc[0]["xbrl_download_status"] == "downloaded"
        assert result.iloc[0]["xbrl_local_path"] != ""

    @patch("pipeline.bdc_filings.BDC_FILINGS_INDEX_FILE")
    @patch("pipeline.bdc_filings.BDC_XBRL_CACHE_DIR")
    def test_cache_hit(self, mock_cache_dir, mock_index_file, tmp_dir):
        from pipeline.bdc_filings import _download_xbrl_instances

        # Create a pre-cached file > 1KB
        cik_dir = tmp_dir / "1418076"
        cik_dir.mkdir()
        cached = cik_dir / "000123000001.xml"
        cached.write_bytes(b"<xbrl>" + b"x" * 2000 + b"</xbrl>")

        index = pd.DataFrame({
            "cik": ["1418076"],
            "accession_number": ["0001-23-000001"],
            "primary_document": ["filing.htm"],
            "form_type": ["10-K"],
        })

        client = MagicMock(spec=EdgarClient)

        with (
            patch("pipeline.bdc_filings.BDC_XBRL_CACHE_DIR", tmp_dir),
            patch("pipeline.bdc_filings.BDC_FILINGS_INDEX_FILE", tmp_dir / "idx.csv"),
        ):
            result = _download_xbrl_instances(client, index)

        assert result.iloc[0]["xbrl_download_status"] == "cached"
        # Should NOT have made any HTTP calls
        client.get_safe.assert_not_called()

    @patch("pipeline.bdc_filings.BDC_FILINGS_INDEX_FILE")
    def test_all_attempts_fail(self, mock_index_file, tmp_dir):
        from pipeline.bdc_filings import _download_xbrl_instances

        index = pd.DataFrame({
            "cik": ["1418076"],
            "accession_number": ["0001-23-000001"],
            "primary_document": ["filing.htm"],
            "form_type": ["10-K"],
        })

        client = MagicMock(spec=EdgarClient)
        client.get_safe.return_value = None  # All attempts fail

        with (
            patch("pipeline.bdc_filings.BDC_XBRL_CACHE_DIR", tmp_dir),
            patch("pipeline.bdc_filings.BDC_FILINGS_INDEX_FILE", tmp_dir / "idx.csv"),
        ):
            result = _download_xbrl_instances(client, index)

        assert result.iloc[0]["xbrl_download_status"] == "not_found"
        assert result.iloc[0]["xbrl_local_path"] == ""


# ---------------------------------------------------------------------------
# 10. _parse_all_filings (with temp files)
# ---------------------------------------------------------------------------

class TestParseAllFilings:
    def test_dedupe_prefers_complete_context_and_fills_sparse_values(self):
        from pipeline.bdc_filings import _deduplicate_bdc_holdings

        raw = pd.DataFrame([
            {
                "accession_number": "acc-001",
                "investment_identifier": "Acme Corp - First Lien",
                "period": "2024-03-31",
                "fair_value": "",
                "cost": "",
                "principal_amount": "",
                "interest_rate": "SOFR+500",
            },
            {
                "accession_number": "acc-001",
                "investment_identifier": "Acme Corp - First Lien",
                "period": "2024-03-31",
                "fair_value": "1000000",
                "cost": "990000",
                "principal_amount": "1000000",
                "interest_rate": "",
            },
        ])

        result = _deduplicate_bdc_holdings(raw)

        assert len(result) == 1
        row = result.iloc[0]
        assert row["fair_value"] == "1000000"
        assert row["cost"] == "990000"
        assert row["principal_amount"] == "1000000"
        assert row["interest_rate"] == "SOFR+500"
        assert int(row["dedupe_context_count"]) == 2
        assert row["dedupe_conflict_fields"] == ""

    def test_dedupe_marks_conflicting_economic_facts(self):
        from pipeline.bdc_filings import _deduplicate_bdc_holdings

        raw = pd.DataFrame([
            {
                "accession_number": "acc-001",
                "investment_identifier": "Acme Corp - First Lien",
                "period": "2024-03-31",
                "fair_value": "1000000",
                "cost": "990000",
            },
            {
                "accession_number": "acc-001",
                "investment_identifier": "Acme Corp - First Lien",
                "period": "2024-03-31",
                "fair_value": "2000000",
                "cost": "990000",
            },
        ])

        result = _deduplicate_bdc_holdings(raw)

        # FV conflict triggers axis split -- both positions preserved
        assert len(result) == 2
        assert set(result["fair_value"]) == {"1000000", "2000000"}
        assert result["dedupe_axis_split"].all()
        # Within each sub-group there is no conflict
        assert (result["dedupe_conflict_fields"] == "").all()
        # Original group size is still recorded
        assert (result["dedupe_context_count"].astype(int) == 2).all()

    def test_dedupe_fv_split_collapses_same_fv_subgroup(self):
        """3 rows with 2 distinct FVs: two at $1M collapse, one at $2M kept."""
        from pipeline.bdc_filings import _deduplicate_bdc_holdings

        raw = pd.DataFrame([
            {
                "accession_number": "acc-001",
                "investment_identifier": "Acme Corp - First Lien",
                "period": "2024-03-31",
                "fair_value": "1000000",
                "cost": "990000",
            },
            {
                "accession_number": "acc-001",
                "investment_identifier": "Acme Corp - First Lien",
                "period": "2024-03-31",
                "fair_value": "1000000",
                "cost": "995000",
            },
            {
                "accession_number": "acc-001",
                "investment_identifier": "Acme Corp - First Lien",
                "period": "2024-03-31",
                "fair_value": "2000000",
                "cost": "1900000",
            },
        ])

        result = _deduplicate_bdc_holdings(raw)

        assert len(result) == 2
        assert set(result["fair_value"]) == {"1000000", "2000000"}
        assert result["dedupe_axis_split"].all()

    def test_dedupe_cost_only_conflict_no_split(self):
        """Same FV but different cost: no FV split triggered."""
        from pipeline.bdc_filings import _deduplicate_bdc_holdings

        raw = pd.DataFrame([
            {
                "accession_number": "acc-001",
                "investment_identifier": "Acme Corp - First Lien",
                "period": "2024-03-31",
                "fair_value": "1000000",
                "cost": "990000",
            },
            {
                "accession_number": "acc-001",
                "investment_identifier": "Acme Corp - First Lien",
                "period": "2024-03-31",
                "fair_value": "1000000",
                "cost": "950000",
            },
        ])

        result = _deduplicate_bdc_holdings(raw)

        assert len(result) == 1
        assert not result.iloc[0]["dedupe_axis_split"]

    def test_dedupe_null_fv_in_conflict_group_joins_best_subgroup(self):
        """Null-FV row in a conflict group joins the highest-scoring sub-group."""
        from pipeline.bdc_filings import _deduplicate_bdc_holdings

        raw = pd.DataFrame([
            {
                "accession_number": "acc-001",
                "investment_identifier": "Acme Corp - First Lien",
                "period": "2024-03-31",
                "fair_value": "1000000",
                "cost": "990000",
                "interest_rate": "",
            },
            {
                "accession_number": "acc-001",
                "investment_identifier": "Acme Corp - First Lien",
                "period": "2024-03-31",
                "fair_value": "2000000",
                "cost": "1900000",
                "interest_rate": "",
            },
            {
                "accession_number": "acc-001",
                "investment_identifier": "Acme Corp - First Lien",
                "period": "2024-03-31",
                "fair_value": "",
                "cost": "",
                "interest_rate": "SOFR+500",
            },
        ])

        result = _deduplicate_bdc_holdings(raw)

        # Two sub-groups survive; the null-FV row fills the rate into one
        assert len(result) == 2
        assert set(result["fair_value"]) == {"1000000", "2000000"}
        # The rate should appear on whichever sub-group the null-FV row joined
        rates = result["interest_rate"].tolist()
        assert "SOFR+500" in rates

    def test_dedupe_preserves_distinct_legal_entity_dimensions(self):
        from pipeline.bdc_filings import _deduplicate_bdc_holdings

        raw = pd.DataFrame([
            {
                "accession_number": "acc-001",
                "investment_identifier": "Blackstone Senior Debt Fund",
                "period": "2024-03-31",
                "dimensions_raw": (
                    "investmentidentifier=BlackstoneSeniorDebtFund|"
                    "legalentityaxis=EntityA"
                ),
                "fair_value": "1000000",
            },
            {
                "accession_number": "acc-001",
                "investment_identifier": "Blackstone Senior Debt Fund",
                "period": "2024-03-31",
                "dimensions_raw": (
                    "investmentidentifier=BlackstoneSeniorDebtFund|"
                    "legalentityaxis=EntityB"
                ),
                "fair_value": "2000000",
            },
        ])

        result = _deduplicate_bdc_holdings(raw)

        assert len(result) == 2
        assert set(result["fair_value"]) == {"1000000", "2000000"}

    def test_dedupe_collapses_exact_duplicate_dimension_path(self):
        from pipeline.bdc_filings import _deduplicate_bdc_holdings

        raw = pd.DataFrame([
            {
                "accession_number": "acc-001",
                "investment_identifier": "Acme Corp - First Lien",
                "period": "2024-03-31",
                "dimensions_raw": "investmentidentifier=Acme|legalentityaxis=EntityA",
                "fair_value": "1000000",
            },
            {
                "accession_number": "acc-001",
                "investment_identifier": "Acme Corp - First Lien",
                "period": "2024-03-31",
                "dimensions_raw": "investmentidentifier=Acme|legalentityaxis=EntityA",
                "fair_value": "1000000",
            },
        ])

        result = _deduplicate_bdc_holdings(raw)

        assert len(result) == 1
        assert int(result.iloc[0]["dedupe_context_count"]) == 2

    def test_dedupe_publishes_winner_context_as_src_context_id(self):
        from pipeline.bdc_filings import _deduplicate_bdc_holdings

        raw = pd.DataFrame([
            {
                "accession_number": "acc-001",
                "investment_identifier": "Acme Corp - First Lien",
                "period": "2024-03-31",
                "_context_id": "ctx_sparse",
                "fair_value": "",
                "cost": "",
                "principal_amount": "",
                "interest_rate": "SOFR+500",
            },
            {
                "accession_number": "acc-001",
                "investment_identifier": "Acme Corp - First Lien",
                "period": "2024-03-31",
                "_context_id": "ctx_complete",
                "fair_value": "1000000",
                "cost": "990000",
                "principal_amount": "1000000",
                "interest_rate": "",
            },
        ])

        result = _deduplicate_bdc_holdings(raw)

        assert len(result) == 1
        # internal column still dropped; published anchor is the winner's ctx
        assert "_context_id" not in result.columns
        assert result.iloc[0]["src_context_id"] == "ctx_complete"

    def test_dedupe_fv_split_rows_keep_own_contexts(self):
        from pipeline.bdc_filings import _deduplicate_bdc_holdings

        raw = pd.DataFrame([
            {
                "accession_number": "acc-001",
                "investment_identifier": "Acme Corp - First Lien",
                "period": "2024-03-31",
                "_context_id": "ctx_a",
                "fair_value": "1000000",
                "cost": "990000",
            },
            {
                "accession_number": "acc-001",
                "investment_identifier": "Acme Corp - First Lien",
                "period": "2024-03-31",
                "_context_id": "ctx_b",
                "fair_value": "2000000",
                "cost": "990000",
            },
        ])

        result = _deduplicate_bdc_holdings(raw)

        assert len(result) == 2
        assert set(result["src_context_id"]) == {"ctx_a", "ctx_b"}
        # distinct contexts -> distinct anchors even under axis split
        assert result["src_context_id"].nunique() == 2

    def test_dedupe_without_context_column_yields_empty_src_context_id(self):
        # legacy-CSV merge path: rows may arrive with no _context_id at all
        from pipeline.bdc_filings import _deduplicate_bdc_holdings

        raw = pd.DataFrame([
            {
                "accession_number": "acc-001",
                "investment_identifier": "Acme Corp - First Lien",
                "period": "2024-03-31",
                "fair_value": "1000000",
            },
        ])

        result = _deduplicate_bdc_holdings(raw)
        assert len(result) == 1
        assert result.iloc[0]["src_context_id"] == ""

    @patch("pipeline.bdc_filings.BDC_HOLDINGS_FILE")
    @patch("pipeline.bdc_filings.BDC_PARSE_PROGRESS_FILE")
    def test_parses_and_saves(self, mock_progress, mock_holdings, tmp_dir):
        from pipeline.bdc_filings import _parse_all_filings

        # Write a real XBRL file
        xml_path = _write_xml(tmp_dir, XBRL_MINIMAL, "test_filing.xml")

        holdings_file = tmp_dir / "holdings.csv"
        progress_file = tmp_dir / "progress.csv"

        index = pd.DataFrame({
            "cik": ["1418076"],
            "entity_name": ["Ares Capital"],
            "accession_number": ["acc-001"],
            "form_type": ["10-K"],
            "filing_date": ["2024-02-28"],
            "report_date": ["2023-12-31"],
            "xbrl_download_status": ["downloaded"],
            "xbrl_local_path": [str(xml_path)],
        })

        with (
            patch("pipeline.bdc_filings.BDC_HOLDINGS_FILE", holdings_file),
            patch("pipeline.bdc_filings.BDC_PARSE_PROGRESS_FILE", progress_file),
        ):
            result = _parse_all_filings(index)

        assert len(result) == 2  # 2 investments in XBRL_MINIMAL
        assert holdings_file.exists()
        assert progress_file.exists()

        # Verify progress file
        progress = pd.read_csv(progress_file, dtype=str)
        assert "acc-001" in progress["accession_number"].values
        assert progress.loc[progress["accession_number"] == "acc-001", "status"].iloc[0] == "parsed"

    @patch("pipeline.bdc_filings.BDC_HOLDINGS_FILE")
    @patch("pipeline.bdc_filings.BDC_PARSE_PROGRESS_FILE")
    def test_skips_already_parsed(self, mock_progress, mock_holdings, tmp_dir):
        from pipeline.bdc_filings import _parse_all_filings

        holdings_file = tmp_dir / "holdings.csv"
        progress_file = tmp_dir / "progress.csv"

        # Pre-populate progress file
        pd.DataFrame({
            "accession_number": ["acc-001"],
            "status": ["parsed"],
            "count": ["5"],
        }).to_csv(progress_file, index=False)

        # Pre-populate holdings file
        pd.DataFrame({
            "cik": ["1418076"],
            "investment_identifier": ["Old Holding"],
            "fair_value": ["1000000"],
            "accession_number": ["acc-001"],
        }).to_csv(holdings_file, index=False)

        index = pd.DataFrame({
            "cik": ["1418076"],
            "entity_name": ["Ares Capital"],
            "accession_number": ["acc-001"],
            "form_type": ["10-K"],
            "filing_date": ["2024-02-28"],
            "report_date": ["2023-12-31"],
            "xbrl_download_status": ["downloaded"],
            "xbrl_local_path": [str(tmp_dir / "whatever.xml")],
        })

        with (
            patch("pipeline.bdc_filings.BDC_HOLDINGS_FILE", holdings_file),
            patch("pipeline.bdc_filings.BDC_PARSE_PROGRESS_FILE", progress_file),
        ):
            result = _parse_all_filings(index)

        # Should load existing holdings without re-parsing
        assert len(result) == 1
        assert result.iloc[0]["investment_identifier"] == "Old Holding"

    @patch("pipeline.bdc_filings.BDC_HOLDINGS_FILE")
    @patch("pipeline.bdc_filings.BDC_PARSE_PROGRESS_FILE")
    def test_skips_not_found_filings(self, mock_progress, mock_holdings, tmp_dir):
        from pipeline.bdc_filings import _parse_all_filings

        holdings_file = tmp_dir / "holdings.csv"
        progress_file = tmp_dir / "progress.csv"

        index = pd.DataFrame({
            "cik": ["1418076"],
            "entity_name": ["Test"],
            "accession_number": ["acc-missing"],
            "form_type": ["10-K"],
            "filing_date": ["2024-02-28"],
            "report_date": ["2023-12-31"],
            "xbrl_download_status": ["not_found"],
            "xbrl_local_path": [""],
        })

        with (
            patch("pipeline.bdc_filings.BDC_HOLDINGS_FILE", holdings_file),
            patch("pipeline.bdc_filings.BDC_PARSE_PROGRESS_FILE", progress_file),
        ):
            result = _parse_all_filings(index)

        assert result.empty


# ---------------------------------------------------------------------------
# 11. _find_xbrl_in_filing_index
# ---------------------------------------------------------------------------

class TestFindXBRLInFilingIndex:
    def test_finds_htm_xml(self):
        from pipeline.bdc_filings import _find_xbrl_in_filing_index

        client = MagicMock(spec=EdgarClient)
        resp = MagicMock()
        resp.text = '''
        <html><body>
        <table>
        <tr><td><a href="filing_htm.xml">XBRL INSTANCE</a></td></tr>
        <tr><td><a href="R1.xml">Render</a></td></tr>
        </table>
        </body></html>
        '''
        client.get_safe.return_value = resp

        url = _find_xbrl_in_filing_index(client, "1418076", "000123000001", "0001-23-000001")
        assert url is not None
        assert "filing_htm.xml" in url

    def test_skips_render_files(self):
        from pipeline.bdc_filings import _find_xbrl_in_filing_index

        client = MagicMock(spec=EdgarClient)
        resp = MagicMock()
        resp.text = '''
        <html><body>
        <tr><td><a href="R1.xml">Render 1</a></td></tr>
        <tr><td><a href="R2.xml">Render 2</a></td></tr>
        <tr><td><a href="actual_data.xml">Data</a></td></tr>
        </body></html>
        '''
        client.get_safe.return_value = resp

        url = _find_xbrl_in_filing_index(client, "123", "000456", "0004-56-000000")
        assert url is not None
        assert "actual_data.xml" in url

    def test_skips_cal_lab_def_pre(self):
        from pipeline.bdc_filings import _find_xbrl_in_filing_index

        client = MagicMock(spec=EdgarClient)
        resp = MagicMock()
        resp.text = '''
        <html>
        <a href="filing_cal.xml">Cal</a>
        <a href="filing_lab.xml">Lab</a>
        <a href="filing_def.xml">Def</a>
        <a href="filing_pre.xml">Pre</a>
        <a href="filing_htm.xml">Instance</a>
        </html>
        '''
        client.get_safe.return_value = resp

        url = _find_xbrl_in_filing_index(client, "123", "000456", "0004-56-000000")
        assert url is not None
        assert "filing_htm.xml" in url

    def test_returns_none_on_404(self):
        from pipeline.bdc_filings import _find_xbrl_in_filing_index

        client = MagicMock(spec=EdgarClient)
        client.get_safe.return_value = None

        url = _find_xbrl_in_filing_index(client, "123", "000456", "0004-56-000000")
        assert url is None

    def test_returns_none_no_xml_links(self):
        from pipeline.bdc_filings import _find_xbrl_in_filing_index

        client = MagicMock(spec=EdgarClient)
        resp = MagicMock()
        resp.text = '<html><body><a href="filing.htm">HTML doc</a></body></html>'
        client.get_safe.return_value = resp

        url = _find_xbrl_in_filing_index(client, "123", "000456", "0004-56-000000")
        assert url is None

    def test_absolute_href(self):
        from pipeline.bdc_filings import _find_xbrl_in_filing_index

        client = MagicMock(spec=EdgarClient)
        resp = MagicMock()
        resp.text = '<a href="/Archives/edgar/data/123/000456/instance.xml">Instance</a>'
        client.get_safe.return_value = resp

        url = _find_xbrl_in_filing_index(client, "123", "000456", "0004-56-000000")
        assert url == "https://www.sec.gov/Archives/edgar/data/123/000456/instance.xml"


# ---------------------------------------------------------------------------
# 12. _try_download
# ---------------------------------------------------------------------------

class TestTryDownload:
    def test_success(self, tmp_dir):
        from pipeline.bdc_filings import _try_download

        client = MagicMock(spec=EdgarClient)
        resp = MagicMock()
        resp.content = b"<xbrl>" + b"x" * 2000 + b"</xbrl>"
        client.get_safe.return_value = resp

        dest = tmp_dir / "sub" / "file.xml"
        assert _try_download(client, "http://example.com/file.xml", dest)
        assert dest.exists()
        assert dest.stat().st_size > 1024

    def test_http_error(self, tmp_dir):
        from pipeline.bdc_filings import _try_download

        client = MagicMock(spec=EdgarClient)
        client.get_safe.return_value = None

        dest = tmp_dir / "file.xml"
        assert not _try_download(client, "http://example.com/file.xml", dest)
        assert not dest.exists()

    def test_too_small(self, tmp_dir):
        from pipeline.bdc_filings import _try_download

        client = MagicMock(spec=EdgarClient)
        resp = MagicMock()
        resp.content = b"tiny"  # < 1KB
        client.get_safe.return_value = resp

        dest = tmp_dir / "file.xml"
        assert not _try_download(client, "http://example.com/file.xml", dest)
        assert not dest.exists()


# ---------------------------------------------------------------------------
# 13. Config constants verification
# ---------------------------------------------------------------------------

class TestConfig:
    def test_new_constants_exist(self):
        from pipeline.config import (
            BDC_XBRL_CACHE_DIR,
            BDC_FILINGS_INDEX_FILE,
            BDC_HOLDINGS_FILE,
            BDC_PARSE_PROGRESS_FILE,
            BDC_XBRL_START_YEAR,
            BDC_FILING_FORM_TYPES,
        )
        assert isinstance(BDC_XBRL_CACHE_DIR, Path)
        assert isinstance(BDC_FILINGS_INDEX_FILE, Path)
        assert isinstance(BDC_HOLDINGS_FILE, Path)
        assert isinstance(BDC_PARSE_PROGRESS_FILE, Path)
        assert BDC_XBRL_START_YEAR == 2013
        assert BDC_FILING_FORM_TYPES == {"10-K", "10-K/A", "10-Q", "10-Q/A"}

    def test_cache_dir_path(self):
        from pipeline.config import BDC_XBRL_CACHE_DIR, RAW_DIR
        assert BDC_XBRL_CACHE_DIR == RAW_DIR / "filings" / "bdc_xbrl"

    def test_output_paths(self):
        from pipeline.config import (
            BDC_FILINGS_INDEX_FILE,
            BDC_HOLDINGS_FILE,
            BDC_PARSE_PROGRESS_FILE,
            OUTPUT_DIR,
        )
        assert BDC_FILINGS_INDEX_FILE == OUTPUT_DIR / "bdc_filings_index.csv"
        assert BDC_HOLDINGS_FILE == OUTPUT_DIR / "bdc_holdings.csv"
        assert BDC_PARSE_PROGRESS_FILE == OUTPUT_DIR / "bdc_parse_progress.csv"

    def test_cache_dir_in_auto_creation(self):
        from pipeline.config import BDC_XBRL_CACHE_DIR
        # The directory should exist after importing config
        assert BDC_XBRL_CACHE_DIR.exists()


# ---------------------------------------------------------------------------
# 14. CLI --holdings flag
# ---------------------------------------------------------------------------

class TestCLIHoldingsFlag:
    def test_parse_holdings_flag(self):
        """--holdings should be parsed as a boolean flag."""
        import importlib
        import pipeline.main as main_mod
        importlib.reload(main_mod)

        with patch("sys.argv", ["main", "--holdings"]):
            args = main_mod._parse_args()
        assert args.holdings is True

    def test_default_no_holdings(self):
        import importlib
        import pipeline.main as main_mod
        importlib.reload(main_mod)

        with patch("sys.argv", ["main"]):
            args = main_mod._parse_args()
        assert args.holdings is False

    def test_combined_flags(self):
        import importlib
        import pipeline.main as main_mod
        importlib.reload(main_mod)

        with patch("sys.argv", ["main", "--holdings", "--nport"]):
            args = main_mod._parse_args()
        assert args.holdings is True
        assert args.nport is True


# ---------------------------------------------------------------------------
# 15. extract_bdc_holdings entry point (mocked integration)
# ---------------------------------------------------------------------------

class TestExtractBDCHoldings:
    @patch("pipeline.bdc_filings._parse_all_filings")
    @patch("pipeline.bdc_filings._download_xbrl_instances")
    @patch("pipeline.bdc_filings._build_filings_index")
    def test_orchestration(self, mock_build, mock_download, mock_parse):
        from pipeline.bdc_filings import extract_bdc_holdings

        # Setup mocks
        filings_df = pd.DataFrame({
            "cik": ["123"],
            "accession_number": ["acc-001"],
        })
        mock_build.return_value = filings_df
        mock_download.return_value = filings_df
        mock_parse.return_value = pd.DataFrame({
            "cik": ["123"],
            "investment_identifier": ["Test Corp"],
            "fair_value": [1000000.0],
            "accession_number": ["acc-001"],
        })

        client = MagicMock(spec=EdgarClient)
        universe = pd.DataFrame({"cik": ["123"]})

        result = extract_bdc_holdings(client, universe)

        mock_build.assert_called_once_with(client, universe)
        mock_download.assert_called_once()
        mock_parse.assert_called_once()
        assert len(result) == 1
        assert result.iloc[0]["fair_value"] == 1000000.0

    @patch("pipeline.bdc_filings._build_filings_index")
    def test_empty_filings_index(self, mock_build):
        from pipeline.bdc_filings import extract_bdc_holdings

        mock_build.return_value = pd.DataFrame()

        client = MagicMock(spec=EdgarClient)
        universe = pd.DataFrame({"cik": ["123"]})

        result = extract_bdc_holdings(client, universe)
        assert result.empty

    def test_loads_universe_from_disk(self, tmp_dir):
        from pipeline.bdc_filings import extract_bdc_holdings

        universe_file = tmp_dir / "bdc_universe.csv"
        pd.DataFrame({"cik": ["1418076"]}).to_csv(universe_file, index=False)

        client = MagicMock(spec=EdgarClient)

        with (
            patch("pipeline.bdc_filings.BDC_UNIVERSE_FILE", universe_file),
            patch("pipeline.bdc_filings._build_filings_index") as mock_build,
            patch("pipeline.bdc_filings._download_xbrl_instances") as mock_dl,
            patch("pipeline.bdc_filings._parse_all_filings") as mock_parse,
        ):
            mock_build.return_value = pd.DataFrame({"cik": ["1418076"], "accession_number": ["a"]})
            mock_dl.return_value = mock_build.return_value
            mock_parse.return_value = pd.DataFrame({"cik": ["1418076"], "fair_value": [1.0], "investment_identifier": ["x"], "accession_number": ["a"]})

            result = extract_bdc_holdings(client, bdc_universe=None)

        assert len(result) == 1

    def test_missing_universe_raises(self, tmp_dir):
        from pipeline.bdc_filings import extract_bdc_holdings

        client = MagicMock(spec=EdgarClient)

        with (
            patch("pipeline.bdc_filings.BDC_UNIVERSE_FILE", tmp_dir / "nonexistent.csv"),
            pytest.raises(FileNotFoundError),
        ):
            extract_bdc_holdings(client, bdc_universe=None)


# ---------------------------------------------------------------------------
# 16. Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_cik_leading_zeros_stripped(self):
        """CIK '0001418076' should become '1418076' for URL construction."""
        from pipeline.bdc_filings import _download_xbrl_instances

        index = pd.DataFrame({
            "cik": ["0001418076"],
            "accession_number": ["0001-23-000001"],
            "primary_document": ["filing.htm"],
            "form_type": ["10-K"],
        })

        client = MagicMock(spec=EdgarClient)
        client.get_safe.return_value = None

        with (
            patch("pipeline.bdc_filings.BDC_XBRL_CACHE_DIR", Path(tempfile.mkdtemp())),
            patch("pipeline.bdc_filings.BDC_FILINGS_INDEX_FILE", Path(tempfile.mkdtemp()) / "idx.csv"),
        ):
            _download_xbrl_instances(client, index)

        # Check that get_safe was called with URL containing stripped CIK
        calls = client.get_safe.call_args_list
        assert any("1418076" in str(c) and "0001418076" not in str(c) for c in calls)

    def test_accession_dashes_removed(self):
        """Accession '0001-23-000001' should become '000123000001' for paths."""
        from pipeline.bdc_filings import _download_xbrl_instances

        index = pd.DataFrame({
            "cik": ["1418076"],
            "accession_number": ["0001-23-000001"],
            "primary_document": ["filing.htm"],
            "form_type": ["10-K"],
        })

        client = MagicMock(spec=EdgarClient)
        client.get_safe.return_value = None

        with (
            patch("pipeline.bdc_filings.BDC_XBRL_CACHE_DIR", Path(tempfile.mkdtemp())),
            patch("pipeline.bdc_filings.BDC_FILINGS_INDEX_FILE", Path(tempfile.mkdtemp()) / "idx.csv"),
        ):
            _download_xbrl_instances(client, index)

        calls = client.get_safe.call_args_list
        assert any("000123000001" in str(c) for c in calls)

    def test_concept_map_no_duplicates_in_output_columns(self):
        """Each CONCEPT_MAP pattern should map to a valid column."""
        from pipeline.bdc_filings import CONCEPT_MAP, _VALUE_COLUMNS
        for pattern, col in CONCEPT_MAP:
            assert col in _VALUE_COLUMNS, f"Column '{col}' from pattern '{pattern}' not in _VALUE_COLUMNS"

    def test_value_columns_sorted(self):
        from pipeline.bdc_filings import _VALUE_COLUMNS
        assert _VALUE_COLUMNS == sorted(_VALUE_COLUMNS)


# ---------------------------------------------------------------------------
# Non-accrual extraction in _parse_single_filing
# ---------------------------------------------------------------------------

class TestNonaccrualExtraction:
    """Verify footnote and dimension non-accrual signals are extracted."""

    XBRL_WITH_NONACCRUAL = textwrap.dedent("""\
        <?xml version="1.0" encoding="UTF-8"?>
        <xbrl
            xmlns="http://www.xbrl.org/2003/instance"
            xmlns:xbrli="http://www.xbrl.org/2003/instance"
            xmlns:xbrldi="http://xbrl.org/2006/xbrldi"
            xmlns:link="http://www.xbrl.org/2003/linkbase"
            xmlns:xlink="http://www.w3.org/1999/xlink"
            xmlns:test="http://example.com/test">

            <!-- Investment context 1: has linked non-accrual footnote -->
            <xbrli:context id="ctx_fn">
                <xbrli:entity>
                    <xbrli:identifier scheme="http://www.sec.gov/CIK">100</xbrli:identifier>
                    <xbrli:segment>
                        <xbrldi:typedMember dimension="test:InvestmentIdentifierAxis">
                            <test:InvestmentIdentifierDomain>Acme Corp - Term Loan</test:InvestmentIdentifierDomain>
                        </xbrldi:typedMember>
                    </xbrli:segment>
                </xbrli:entity>
                <xbrli:period><xbrli:instant>2025-12-31</xbrli:instant></xbrli:period>
            </xbrli:context>

            <!-- Investment context 2: has non-accrual dimension member -->
            <xbrli:context id="ctx_dim">
                <xbrli:entity>
                    <xbrli:identifier scheme="http://www.sec.gov/CIK">100</xbrli:identifier>
                    <xbrli:segment>
                        <xbrldi:typedMember dimension="test:InvestmentIdentifierAxis">
                            <test:InvestmentIdentifierDomain>Beta Inc - Senior Note</test:InvestmentIdentifierDomain>
                        </xbrldi:typedMember>
                        <xbrldi:explicitMember dimension="test:InvestmentTypeAxis">test:NonAccrualMember</xbrldi:explicitMember>
                    </xbrli:segment>
                </xbrli:entity>
                <xbrli:period><xbrli:instant>2025-12-31</xbrli:instant></xbrli:period>
            </xbrli:context>

            <!-- Investment context 3: no NA signal -->
            <xbrli:context id="ctx_clean">
                <xbrli:entity>
                    <xbrli:identifier scheme="http://www.sec.gov/CIK">100</xbrli:identifier>
                    <xbrli:segment>
                        <xbrldi:typedMember dimension="test:InvestmentIdentifierAxis">
                            <test:InvestmentIdentifierDomain>Gamma LLC - Revolver</test:InvestmentIdentifierDomain>
                        </xbrldi:typedMember>
                    </xbrli:segment>
                </xbrli:entity>
                <xbrli:period><xbrli:instant>2025-12-31</xbrli:instant></xbrli:period>
            </xbrli:context>

            <!-- Facts -->
            <test:InvestmentOwnedAtFairValue id="fv_fn" contextRef="ctx_fn" unitRef="usd" decimals="0">1000000</test:InvestmentOwnedAtFairValue>
            <test:InvestmentOwnedAtFairValue id="fv_dim" contextRef="ctx_dim" unitRef="usd" decimals="0">2000000</test:InvestmentOwnedAtFairValue>
            <test:InvestmentOwnedAtFairValue id="fv_clean" contextRef="ctx_clean" unitRef="usd" decimals="0">3000000</test:InvestmentOwnedAtFairValue>

            <!-- Footnote link: fv_fn -> non-accrual footnote -->
            <link:footnoteLink>
                <link:loc xlink:type="locator" xlink:href="#fv_fn" xlink:label="fact_fn"/>
                <link:footnote xlink:type="resource" xlink:label="fn_na" xml:lang="en">
                    Loan was placed on non-accrual status as of December 31, 2025.
                </link:footnote>
                <link:footnoteArc xlink:type="arc" xlink:from="fact_fn" xlink:to="fn_na" xlink:arcrole="http://www.xbrl.org/2003/arcrole/fact-footnote"/>
            </link:footnoteLink>
        </xbrl>
    """)

    def test_parse_single_filing_extracts_nonaccrual_signals(self, tmp_path):
        from pipeline.bdc_filings import _parse_single_filing

        xml_file = tmp_path / "test.xml"
        xml_file.write_text(self.XBRL_WITH_NONACCRUAL, encoding="utf-8")

        meta = {
            "cik": "100", "entity_name": "Test", "accession_number": "0001",
            "form_type": "10-K", "filing_date": "2026-01-15",
            "report_date": "2025-12-31",
        }
        records = _parse_single_filing(str(xml_file), meta)

        by_id = {r["investment_identifier"]: r for r in records}

        # Footnote-flagged position
        acme = by_id["Acme Corp - Term Loan"]
        assert acme["nonaccrual_footnote"] is True
        assert acme["nonaccrual_dimension"] is False

        # Dimension-flagged position
        beta = by_id["Beta Inc - Senior Note"]
        assert beta["nonaccrual_footnote"] is False
        assert beta["nonaccrual_dimension"] is True

        # Clean position
        gamma = by_id["Gamma LLC - Revolver"]
        assert gamma["nonaccrual_footnote"] is False
        assert gamma["nonaccrual_dimension"] is False

    def test_dedup_preserves_nonaccrual_or_semantics(self):
        """If any row in a dedup group has True, the surviving row must too."""
        from pipeline.bdc_filings import _deduplicate_bdc_holdings

        df = pd.DataFrame([
            {
                "accession_number": "A", "investment_identifier": "X",
                "period": "2025-12-31", "dimensions_raw": "",
                "fair_value": 100, "nonaccrual_footnote": True,
                "nonaccrual_dimension": False,
            },
            {
                "accession_number": "A", "investment_identifier": "X",
                "period": "2025-12-31", "dimensions_raw": "",
                "fair_value": 100, "nonaccrual_footnote": False,
                "nonaccrual_dimension": False,
            },
        ])
        result = _deduplicate_bdc_holdings(df)
        assert len(result) == 1
        assert bool(result.iloc[0]["nonaccrual_footnote"]) is True


# ---------------------------------------------------------------------------
# interest_rate_concept provenance (rate-convention S0 input)
# ---------------------------------------------------------------------------

XBRL_PAIDINCASH = textwrap.dedent("""\
    <?xml version="1.0" encoding="UTF-8"?>
    <xbrl
        xmlns="http://www.xbrl.org/2003/instance"
        xmlns:xbrli="http://www.xbrl.org/2003/instance"
        xmlns:xbrldi="http://xbrl.org/2006/xbrldi"
        xmlns:f="http://example.com/filer"
        xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
        <xbrli:context id="ctx_a">
            <xbrli:entity>
                <xbrli:identifier scheme="http://www.sec.gov/CIK">0001551901</xbrli:identifier>
                <xbrli:segment>
                    <xbrldi:typedMember dimension="f:InvestmentIdentifierAxis">
                        <f:InvestmentIdentifierDomain>Cash Co Term Loan</f:InvestmentIdentifierDomain>
                    </xbrldi:typedMember>
                </xbrli:segment>
            </xbrli:entity>
            <xbrli:period><xbrli:instant>2025-12-31</xbrli:instant></xbrli:period>
        </xbrli:context>
        <xbrli:context id="ctx_b">
            <xbrli:entity>
                <xbrli:identifier scheme="http://www.sec.gov/CIK">0001551901</xbrli:identifier>
                <xbrli:segment>
                    <xbrldi:typedMember dimension="f:InvestmentIdentifierAxis">
                        <f:InvestmentIdentifierDomain>Bare Co Term Loan</f:InvestmentIdentifierDomain>
                    </xbrldi:typedMember>
                </xbrli:segment>
            </xbrli:entity>
            <xbrli:period><xbrli:instant>2025-12-31</xbrli:instant></xbrli:period>
        </xbrli:context>
        <f:InvestmentInterestRatePaidInCash contextRef="ctx_a" unitRef="pure" decimals="4">0.0800</f:InvestmentInterestRatePaidInCash>
        <f:InvestmentInterestRatePaidInKind contextRef="ctx_a" unitRef="pure" decimals="4">0.0250</f:InvestmentInterestRatePaidInKind>
        <f:InvestmentOwnedAtFairValue contextRef="ctx_a" unitRef="usd" decimals="-3">5000000</f:InvestmentOwnedAtFairValue>
        <f:InvestmentInterestRate contextRef="ctx_b" unitRef="pure" decimals="4">0.1050</f:InvestmentInterestRate>
        <f:InvestmentOwnedAtFairValue contextRef="ctx_b" unitRef="usd" decimals="-3">3000000</f:InvestmentOwnedAtFairValue>
    </xbrl>
""")


class TestInterestRateConceptProvenance:
    def test_paidincash_maps_to_interest_rate_with_provenance(self, tmp_path):
        from pipeline.bdc_filings import _parse_single_filing
        xml = tmp_path / "pc.xml"
        xml.write_text(XBRL_PAIDINCASH, encoding="utf-8")
        meta = {"cik": "1551901", "entity_name": "T", "accession_number": "a",
                "form_type": "10-K", "filing_date": "2026-02-01",
                "report_date": "2025-12-31"}
        records = _parse_single_filing(str(xml), meta)
        by_id = {r["investment_identifier"]: r for r in records}
        cash_row = by_id["Cash Co Term Loan"]
        bare_row = by_id["Bare Co Term Loan"]
        # value behavior unchanged: PaidInCash lands in interest_rate
        assert cash_row["interest_rate"] == pytest.approx(0.08)
        assert cash_row["pik_rate"] == pytest.approx(0.025)
        # provenance records WHICH concept won the column
        assert cash_row["interest_rate_concept"] == "paid_in_cash"
        assert bare_row["interest_rate_concept"] == "bare"

    def test_match_concept_paidincash_explicit(self):
        from pipeline.bdc_filings import _match_concept
        assert _match_concept("investmentinterestratepaidincash") == "interest_rate"

    def test_no_rate_fact_leaves_provenance_empty(self, tmp_path):
        from pipeline.bdc_filings import _parse_single_filing
        xml = tmp_path / "m.xml"
        xml.write_text(XBRL_MINIMAL, encoding="utf-8")
        meta = {"cik": "1418076", "entity_name": "T", "accession_number": "a",
                "form_type": "10-K", "filing_date": "2024-02-01",
                "report_date": "2023-12-31"}
        records = _parse_single_filing(str(xml), meta)
        by_id = {r["investment_identifier"]: r for r in records}
        # Beta Inc has no rate fact at all -> empty provenance
        assert by_id["Beta Inc - Senior Secured Note"]["interest_rate_concept"] == ""
        # Acme has a bare InvestmentInterestRate fact
        assert by_id["Acme Corp - First Lien Term Loan"]["interest_rate_concept"] == "bare"


# ---------------------------------------------------------------------------
# src_facts provenance capture
# ---------------------------------------------------------------------------

import json

from pipeline.bdc_filings import _extract_investment_facts


def _ctx(period="2025-12-31", ident="Acme Corp - Term Loan"):
    return {
        "is_investment": True, "period": period,
        "investment_identifier": ident, "industry": "", "investment_type": "",
        "affiliation": "", "dimensions_raw": f"investmentidentifieraxis={ident}",
    }


def _tree(facts_xml: str):
    return etree.ElementTree(etree.fromstring(
        f'<xbrl xmlns:us-gaap="http://fasb.org/us-gaap/2024">{facts_xml}</xbrl>'
    ))


class TestSrcFactsCapture:
    def test_rate_fields_record_raw_value(self):
        tree = _tree(
            '<us-gaap:InvestmentInterestRate contextRef="c1">0.105'
            '</us-gaap:InvestmentInterestRate>'
            '<us-gaap:InvestmentOwnedAtFairValue contextRef="c1" unitRef="usd" '
            'decimals="-3">1000000</us-gaap:InvestmentOwnedAtFairValue>'
        )
        recs = _extract_investment_facts(tree, {"c1": _ctx()})
        prov = json.loads(recs[0]["src_facts"])
        assert prov["interest_rate"]["r"] == 0.105
        # canonical concept, no transform -> no "c", no "x"
        assert "c" not in prov["interest_rate"]
        # fair_value: canonical concept, no transform -> NO entry at all
        assert "fair_value" not in prov

    def test_noncanonical_concept_recorded(self):
        # SharesOrNumberOfContractsOrPrincipalAmount is the NON-canonical
        # principal_amount concept (canonical = InvestmentOwnedBalancePrincipalAmount)
        tree = _tree(
            '<us-gaap:InvestmentOwnedBalanceSharesOrNumberOfContractsOr'
            'PrincipalAmount contextRef="c1" unitRef="usd" decimals="0">58702'
            '</us-gaap:InvestmentOwnedBalanceSharesOrNumberOfContractsOr'
            'PrincipalAmount>'
        )
        recs = _extract_investment_facts(tree, {"c1": _ctx()})
        prov = json.loads(recs[0]["src_facts"])
        assert prov["principal_amount"]["c"] == (
            "investmentownedbalancesharesornumberofcontractsorprincipalamount")

    def test_decimals_rescale_records_raw_and_event(self):
        # 5+ facts at decimals=-3, one outlier at -6 and >100x the median:
        # normalization multiplies the outlier by 10^-3; src_facts must keep
        # the pre-fix raw and the event.
        base = "".join(
            f'<us-gaap:InvestmentOwnedAtFairValue contextRef="c{i}" '
            f'unitRef="usd" decimals="-3">{1000000 + i}'
            f'</us-gaap:InvestmentOwnedAtFairValue>' for i in range(5))
        outlier = ('<us-gaap:InvestmentOwnedAtFairValue contextRef="c9" '
                   'unitRef="usd" decimals="-6">500000000'
                   '</us-gaap:InvestmentOwnedAtFairValue>')
        contexts = {f"c{i}": _ctx(ident=f"P{i}") for i in range(5)}
        contexts["c9"] = _ctx(ident="Outlier LP")
        recs = _extract_investment_facts(_tree(base + outlier), contexts)
        by_ctx = {r["_context_id"]: r for r in recs}
        assert by_ctx["c9"]["fair_value"] == 500000000 * 10 ** -3
        prov = json.loads(by_ctx["c9"]["src_facts"])
        assert prov["fair_value"]["r"] == 500000000
        assert prov["fair_value"]["x"] == ["decimals_rescale:10^-3"]

    def test_no_facts_means_empty_src_facts(self):
        tree = _tree('<us-gaap:InvestmentOwnedAtFairValue contextRef="c1" '
                     'unitRef="usd">1000</us-gaap:InvestmentOwnedAtFairValue>')
        recs = _extract_investment_facts(tree, {"c1": _ctx()})
        # fair_value canonical + untransformed and no rate facts -> "" not "{}"
        assert recs[0]["src_facts"] == ""
