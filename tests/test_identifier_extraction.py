"""Tests for pipeline.identifier_extraction module.

Covers:
- Candidate identification from unified holdings
- Cache resumability (skip already-processed identifiers)
- Batch prompt construction
- API response parsing (all 4 format families)
- Enrichment via DuckDB LEFT JOIN (COALESCE logic)
- Aggregate detection
- Empty input / N-PORT pass-through
- Full extract_identifiers orchestration with mocked API
"""

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from pipeline.identifier_extraction import (
    BATCH_SIZE,
    _apply_enrichment,
    _build_batch_prompt,
    _get_candidates,
    _load_cache,
    _LOOKUP_COLUMNS,
    _parse_batch_results,
    extract_identifiers,
)
from pipeline.unified_holdings import UNIFIED_COLUMNS


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_unified_row(**overrides):
    """Create a single unified holdings row with defaults."""
    row = {col: "" for col in UNIFIED_COLUMNS}
    row.update({
        "source": "bdc",
        "cik": "1234567890",
        "entity_name": "Test BDC",
        "report_date": "2025-03-31",
        "fair_value": "1000000",
        "asset_category": "LOAN",
        "issuer_category": "CORPORATE",
        "index_classification": "DIRECT_LENDING",
    })
    row.update(overrides)
    return row


def _make_unified_df(rows):
    """Create a unified holdings DataFrame from a list of row dicts."""
    return pd.DataFrame(rows)


def _make_lookup_row(**overrides):
    """Create a single lookup cache row."""
    row = {col: "" for col in _LOOKUP_COLUMNS}
    row.update({
        "extraction_timestamp": "2025-01-01T00:00:00+00:00",
    })
    row.update(overrides)
    return row


# ---------------------------------------------------------------------------
# _get_candidates
# ---------------------------------------------------------------------------

class TestGetCandidates:
    def test_finds_unparsed_identifiers(self):
        """BDC rows where issuer_name == bdc_investment_identifier are candidates."""
        raw_id = "Senior Secured Loans | First Lien | Acme Corp | Technology"
        df = _make_unified_df([
            _make_unified_row(
                issuer_name=raw_id,
                bdc_investment_identifier=raw_id,
            ),
        ])
        result = _get_candidates(df)
        assert len(result) == 1
        assert result.iloc[0] == raw_id

    def test_skips_parsed_identifiers(self):
        """BDC rows where issuer_name != bdc_investment_identifier are NOT candidates."""
        df = _make_unified_df([
            _make_unified_row(
                issuer_name="Acme Corp",
                bdc_investment_identifier="Acme Corp - First Lien Term Loan",
            ),
        ])
        result = _get_candidates(df)
        assert len(result) == 0

    def test_skips_nport_rows(self):
        """N-PORT rows are never candidates."""
        df = _make_unified_df([
            _make_unified_row(
                source="nport",
                issuer_name="Some Name",
                bdc_investment_identifier="",
            ),
        ])
        result = _get_candidates(df)
        assert len(result) == 0

    def test_deduplicates(self):
        """Same identifier appearing multiple times is returned once."""
        raw_id = "Acme Corp Inc First Lien"
        df = _make_unified_df([
            _make_unified_row(
                issuer_name=raw_id,
                bdc_investment_identifier=raw_id,
                report_date="2025-03-31",
            ),
            _make_unified_row(
                issuer_name=raw_id,
                bdc_investment_identifier=raw_id,
                report_date="2025-06-30",
            ),
        ])
        result = _get_candidates(df)
        assert len(result) == 1

    def test_empty_identifier_skipped(self):
        """Empty bdc_investment_identifier is not a candidate."""
        df = _make_unified_df([
            _make_unified_row(
                issuer_name="",
                bdc_investment_identifier="",
            ),
        ])
        result = _get_candidates(df)
        assert len(result) == 0


# ---------------------------------------------------------------------------
# _build_batch_prompt
# ---------------------------------------------------------------------------

class TestBuildBatchPrompt:
    def test_numbered_list(self):
        ids = ["Acme Corp - First Lien", "Beta LLC - Revolver"]
        prompt = _build_batch_prompt(ids)
        assert "1. Acme Corp - First Lien" in prompt
        assert "2. Beta LLC - Revolver" in prompt
        assert "JSON" in prompt

    def test_batch_size_limit(self):
        ids = [f"Company {i}" for i in range(BATCH_SIZE)]
        prompt = _build_batch_prompt(ids)
        assert f"{BATCH_SIZE}. Company {BATCH_SIZE - 1}" in prompt


# ---------------------------------------------------------------------------
# _parse_batch_results
# ---------------------------------------------------------------------------

class TestParseBatchResults:
    def test_pipe_format(self):
        """Pipe-delimited identifier correctly decomposed."""
        identifiers = ["Senior Secured Loans | First Lien | Acme Corp | Technology"]
        results = [{
            "id": 1,
            "company_name": "Acme Corp",
            "instrument_description": "Senior Secured First Lien Loan",
            "industry": "Technology",
            "reference_rate": None,
            "basis_spread_pct": None,
            "maturity_date": None,
            "is_aggregate": False,
        }]
        rows = _parse_batch_results(identifiers, results)
        assert len(rows) == 1
        assert rows[0]["extracted_company_name"] == "Acme Corp"
        assert rows[0]["extracted_industry"] == "Technology"
        assert rows[0]["extracted_is_aggregate"] == "False"

    def test_comma_format(self):
        """Structured comma format handled."""
        identifiers = [
            "Non-Control/Non-Affiliate, Senior Secured Loan, First Lien, "
            "Beta Holdings LLC, Healthcare"
        ]
        results = [{
            "id": 1,
            "company_name": "Beta Holdings LLC",
            "instrument_description": "Senior Secured First Lien Loan",
            "industry": "Healthcare",
            "reference_rate": "SOFR",
            "basis_spread_pct": 5.25,
            "maturity_date": "2028-12-15",
            "is_aggregate": False,
        }]
        rows = _parse_batch_results(identifiers, results)
        assert rows[0]["extracted_company_name"] == "Beta Holdings LLC"
        assert rows[0]["extracted_reference_rate"] == "SOFR"
        assert rows[0]["extracted_basis_spread"] == "5.25"
        assert rows[0]["extracted_maturity_date"] == "2028-12-15"

    def test_unstructured_format(self):
        """Unstructured concatenated format parsed."""
        identifiers = [
            "Gamma Inc First Lien Senior Secured Term Loan SOFR + 4.50% 06/30/2027"
        ]
        results = [{
            "id": 1,
            "company_name": "Gamma Inc",
            "instrument_description": "First Lien Senior Secured Term Loan",
            "industry": None,
            "reference_rate": "SOFR",
            "basis_spread_pct": 4.50,
            "maturity_date": "2027-06-30",
            "is_aggregate": False,
        }]
        rows = _parse_batch_results(identifiers, results)
        assert rows[0]["extracted_company_name"] == "Gamma Inc"
        assert rows[0]["extracted_industry"] == ""  # None -> ""

    def test_short_clean_format(self):
        """Short/clean format works."""
        identifiers = ["Delta Corp, Inc. - First Lien Term Loan"]
        results = [{
            "id": 1,
            "company_name": "Delta Corp, Inc.",
            "instrument_description": "First Lien Term Loan",
            "industry": None,
            "reference_rate": None,
            "basis_spread_pct": None,
            "maturity_date": None,
            "is_aggregate": False,
        }]
        rows = _parse_batch_results(identifiers, results)
        assert rows[0]["extracted_company_name"] == "Delta Corp, Inc."
        assert rows[0]["extracted_instrument_description"] == "First Lien Term Loan"

    def test_aggregate_detection(self):
        """Subtotal rows flagged as is_aggregate=True."""
        identifiers = ["Total Senior Secured First Lien"]
        results = [{
            "id": 1,
            "company_name": "",
            "instrument_description": "",
            "industry": None,
            "reference_rate": None,
            "basis_spread_pct": None,
            "maturity_date": None,
            "is_aggregate": True,
        }]
        rows = _parse_batch_results(identifiers, results)
        assert rows[0]["extracted_is_aggregate"] == "True"

    def test_missing_result(self):
        """Missing API result for an identifier produces empty fields."""
        identifiers = ["Company A", "Company B"]
        results = [{
            "id": 1,
            "company_name": "Company A",
            "instrument_description": "Term Loan",
            "industry": None,
            "reference_rate": None,
            "basis_spread_pct": None,
            "maturity_date": None,
            "is_aggregate": False,
        }]
        # id=2 is missing from results
        rows = _parse_batch_results(identifiers, results)
        assert len(rows) == 2
        assert rows[0]["extracted_company_name"] == "Company A"
        assert rows[1]["extracted_company_name"] == ""  # missing


# ---------------------------------------------------------------------------
# _apply_enrichment
# ---------------------------------------------------------------------------

class TestApplyEnrichment:
    def test_issuer_name_overwritten_when_parser_failed(self):
        """issuer_name updated only when it equals the raw identifier."""
        raw_id = "Unstructured Acme Corp First Lien"
        df = _make_unified_df([
            _make_unified_row(
                issuer_name=raw_id,
                bdc_investment_identifier=raw_id,
            ),
        ])
        lookup = pd.DataFrame([_make_lookup_row(
            bdc_investment_identifier=raw_id,
            extracted_company_name="Acme Corp",
        )])
        result = _apply_enrichment(df, lookup)
        assert result.iloc[0]["issuer_name"] == "Acme Corp"

    def test_issuer_name_preserved_when_parser_succeeded(self):
        """issuer_name NOT overwritten when parser already extracted a name."""
        df = _make_unified_df([
            _make_unified_row(
                issuer_name="Acme Corp",
                bdc_investment_identifier="Acme Corp - First Lien Term Loan",
            ),
        ])
        lookup = pd.DataFrame([_make_lookup_row(
            bdc_investment_identifier="Acme Corp - First Lien Term Loan",
            extracted_company_name="ACME Corporation",
        )])
        result = _apply_enrichment(df, lookup)
        assert result.iloc[0]["issuer_name"] == "Acme Corp"

    def test_existing_nonempty_values_preserved(self):
        """COALESCE preserves existing non-empty values."""
        raw_id = "Test Corp"
        df = _make_unified_df([
            _make_unified_row(
                issuer_name=raw_id,
                bdc_investment_identifier=raw_id,
                reference_rate_type="SOFR",
                maturity_date="2028-01-15",
                basis_spread="5.25",
            ),
        ])
        lookup = pd.DataFrame([_make_lookup_row(
            bdc_investment_identifier=raw_id,
            extracted_company_name="Test Corp Inc",
            extracted_reference_rate="PRIME",
            extracted_maturity_date="2029-06-30",
            extracted_basis_spread="3.75",
        )])
        result = _apply_enrichment(df, lookup)
        # issuer_name overwritten (parser failed)
        assert result.iloc[0]["issuer_name"] == "Test Corp Inc"
        # These should be PRESERVED (existing non-empty values)
        assert result.iloc[0]["reference_rate_type"] == "SOFR"
        assert result.iloc[0]["maturity_date"] == "2028-01-15"

    def test_empty_values_filled(self):
        """Empty fields filled from extraction."""
        raw_id = "Bare Name Corp"
        df = _make_unified_df([
            _make_unified_row(
                issuer_name=raw_id,
                bdc_investment_identifier=raw_id,
                instrument_description="",
                reference_rate_type="",
                maturity_date="",
            ),
        ])
        lookup = pd.DataFrame([_make_lookup_row(
            bdc_investment_identifier=raw_id,
            extracted_company_name="Bare Name Corp",
            extracted_instrument_description="First Lien Term Loan",
            extracted_reference_rate="SOFR",
            extracted_maturity_date="2027-12-31",
        )])
        result = _apply_enrichment(df, lookup)
        assert result.iloc[0]["instrument_description"] == "First Lien Term Loan"
        assert result.iloc[0]["reference_rate_type"] == "SOFR"
        assert result.iloc[0]["maturity_date"] == "2027-12-31"

    def test_nport_rows_untouched(self):
        """N-PORT rows pass through without modification."""
        df = _make_unified_df([
            _make_unified_row(
                source="nport",
                issuer_name="Nport Issuer",
                bdc_investment_identifier="",
            ),
        ])
        lookup = pd.DataFrame([_make_lookup_row(
            bdc_investment_identifier="",
            extracted_company_name="Should Not Apply",
        )])
        result = _apply_enrichment(df, lookup)
        assert result.iloc[0]["issuer_name"] == "Nport Issuer"

    def test_extracted_industry_populated(self):
        """extracted_industry column populated for BDC rows."""
        raw_id = "Tech Corp Loan"
        df = _make_unified_df([
            _make_unified_row(
                issuer_name=raw_id,
                bdc_investment_identifier=raw_id,
                extracted_industry="",
            ),
        ])
        lookup = pd.DataFrame([_make_lookup_row(
            bdc_investment_identifier=raw_id,
            extracted_industry="Technology",
        )])
        result = _apply_enrichment(df, lookup)
        assert result.iloc[0]["extracted_industry"] == "Technology"

    def test_empty_lookup(self):
        """Empty lookup returns DataFrame unchanged."""
        df = _make_unified_df([
            _make_unified_row(issuer_name="Acme Corp"),
        ])
        empty_lookup = pd.DataFrame(columns=_LOOKUP_COLUMNS)
        result = _apply_enrichment(df, empty_lookup)
        assert len(result) == len(df)
        assert result.iloc[0]["issuer_name"] == "Acme Corp"


# ---------------------------------------------------------------------------
# Cache resumability
# ---------------------------------------------------------------------------

class TestCacheResumability:
    def test_skip_cached_identifiers(self, tmp_path):
        """Second call skips already-cached identifiers."""
        raw_id_a = "CompanyA First Lien"
        raw_id_b = "CompanyB Revolver"

        df = _make_unified_df([
            _make_unified_row(
                issuer_name=raw_id_a,
                bdc_investment_identifier=raw_id_a,
            ),
            _make_unified_row(
                issuer_name=raw_id_b,
                bdc_investment_identifier=raw_id_b,
            ),
        ])

        # Pre-populate cache with only CompanyA
        cache_df = pd.DataFrame([_make_lookup_row(
            bdc_investment_identifier=raw_id_a,
            extracted_company_name="CompanyA",
        )])
        cache_file = tmp_path / "identifier_extraction_lookup.csv"
        cache_df.to_csv(cache_file, index=False)

        # Mock the API to track calls
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = json.dumps({
            "results": [{
                "id": 1,
                "company_name": "CompanyB",
                "instrument_description": "Revolver",
                "industry": None,
                "reference_rate": None,
                "basis_spread_pct": None,
                "maturity_date": None,
                "is_aggregate": False,
            }]
        })

        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_response

        with patch(
            "pipeline.identifier_extraction.IDENTIFIER_EXTRACTION_LOOKUP_FILE",
            cache_file,
        ), patch(
            "pipeline.identifier_extraction.OpenAI",
            return_value=mock_client,
        ):
            result = extract_identifiers(unified_df=df)

        # API should have been called with only CompanyB (1 call)
        mock_client.chat.completions.create.assert_called_once()
        call_args = mock_client.chat.completions.create.call_args
        user_msg = call_args[1]["messages"][1]["content"]
        assert raw_id_b in user_msg
        assert raw_id_a not in user_msg


# ---------------------------------------------------------------------------
# Full orchestration (mocked API)
# ---------------------------------------------------------------------------

class TestExtractIdentifiers:
    def test_empty_input(self):
        """No BDC rows = no API calls, returns unchanged DataFrame."""
        df = _make_unified_df([
            _make_unified_row(
                source="nport",
                issuer_name="N-PORT Corp",
                bdc_investment_identifier="",
            ),
        ])
        # Should not raise, should not call API
        result = extract_identifiers(unified_df=df)
        assert len(result) == 1
        assert result.iloc[0]["issuer_name"] == "N-PORT Corp"

    def test_all_parsed(self):
        """All BDC identifiers already parsed = no candidates."""
        df = _make_unified_df([
            _make_unified_row(
                issuer_name="Acme Corp",
                bdc_investment_identifier="Acme Corp - First Lien",
            ),
        ])
        result = extract_identifiers(unified_df=df)
        assert len(result) == 1
        assert result.iloc[0]["issuer_name"] == "Acme Corp"

    def test_full_flow_with_mock(self, tmp_path):
        """Full extract -> enrich flow with mocked OpenAI API."""
        raw_id = "Unstructured Acme Corp Inc First Lien Senior Secured"
        df = _make_unified_df([
            _make_unified_row(
                issuer_name=raw_id,
                bdc_investment_identifier=raw_id,
                instrument_description="",
                reference_rate_type="",
                extracted_industry="",
            ),
        ])

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = json.dumps({
            "results": [{
                "id": 1,
                "company_name": "Acme Corp Inc",
                "instrument_description": "First Lien Senior Secured Term Loan",
                "industry": "Technology",
                "reference_rate": "SOFR",
                "basis_spread_pct": 5.25,
                "maturity_date": None,
                "is_aggregate": False,
            }]
        })

        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_response

        cache_file = tmp_path / "identifier_extraction_lookup.csv"

        with patch(
            "pipeline.identifier_extraction.IDENTIFIER_EXTRACTION_LOOKUP_FILE",
            cache_file,
        ), patch(
            "pipeline.identifier_extraction.OpenAI",
            return_value=mock_client,
        ):
            result = extract_identifiers(unified_df=df)

        assert len(result) == 1
        assert result.iloc[0]["issuer_name"] == "Acme Corp Inc"
        assert result.iloc[0]["instrument_description"] == (
            "First Lien Senior Secured Term Loan"
        )
        assert result.iloc[0]["extracted_industry"] == "Technology"
        assert result.iloc[0]["reference_rate_type"] == "SOFR"

        # Verify cache was written
        assert cache_file.exists()
        cache = pd.read_csv(cache_file, dtype=str)
        assert len(cache) == 1
        assert cache.iloc[0]["extracted_company_name"] == "Acme Corp Inc"
