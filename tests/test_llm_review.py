"""Tests for pipeline.llm_review module.

All tests mock the API call -- no actual LLM invocation in CI.

Covers:
- extract_review_candidates: dedup, review types, occurrence_count
- build_review_batches: batch size, prompt format, domain context
- parse_review_responses: valid JSON, malformed JSON, confidence levels
- apply_llm_classifications: aggregates removed, reclassified, low-confidence
- run_llm_review: dry_run, full run with mocked API, resumability
"""

import json
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from pipeline.llm_review import (
    apply_llm_classifications,
    build_review_batches,
    extract_review_candidates,
    parse_review_responses,
    run_llm_review,
)


def _make_unified_df(rows):
    """Helper to create a minimal unified DataFrame."""
    from pipeline.unified_holdings import UNIFIED_COLUMNS

    data = []
    for row in rows:
        full_row = {c: "" for c in UNIFIED_COLUMNS}
        full_row.update(row)
        data.append(full_row)
    return pd.DataFrame(data)


def _make_candidates(n=5):
    """Helper to create candidate DataFrame."""
    records = []
    for i in range(n):
        records.append({
            "review_id": i,
            "issuer_name": f"Company {i}",
            "instrument_description": "",
            "bdc_investment_identifier": f"Company {i}",
            "source": "bdc",
            "sample_fair_value": str(1_000_000 * (i + 1)),
            "sample_interest_rate": "",
            "sample_basis_spread": "",
            "sample_principal_amount": "",
            "sample_shares_held": "",
            "current_asset_category": "OTHER",
            "current_index_classification": "UNCLASSIFIED",
            "review_type": "unclassified",
            "occurrence_count": 10 + i,
        })
    return pd.DataFrame(records)


# ---------------------------------------------------------------------------
# extract_review_candidates
# ---------------------------------------------------------------------------

class TestExtractReviewCandidates:
    def test_correct_dedup(self):
        df = _make_unified_df([
            {"source": "bdc", "cik": "100", "issuer_name": "Acme",
             "instrument_description": "", "bdc_investment_identifier": "Acme",
             "asset_category": "OTHER", "index_classification": "UNCLASSIFIED",
             "fair_value": "100"},
            # Duplicate of above
            {"source": "bdc", "cik": "100", "issuer_name": "Acme",
             "instrument_description": "", "bdc_investment_identifier": "Acme",
             "asset_category": "OTHER", "index_classification": "UNCLASSIFIED",
             "fair_value": "200"},
            # Different identifier
            {"source": "bdc", "cik": "100", "issuer_name": "Beta",
             "instrument_description": "Term Loan",
             "bdc_investment_identifier": "Beta - Term Loan",
             "asset_category": "OTHER", "index_classification": "UNCLASSIFIED",
             "fair_value": "300"},
        ])
        result = extract_review_candidates(df)
        assert len(result) == 2  # 2 unique tuples

    def test_includes_all_review_types(self):
        df = _make_unified_df([
            # UNCLASSIFIED
            {"source": "bdc", "cik": "100", "issuer_name": "Unknown",
             "bdc_investment_identifier": "Unknown",
             "asset_category": "LOAN", "index_classification": "UNCLASSIFIED"},
            # OTHER asset
            {"source": "bdc", "cik": "100", "issuer_name": "Mystery",
             "bdc_investment_identifier": "Mystery",
             "asset_category": "OTHER", "index_classification": "UNCLASSIFIED"},
        ])
        result = extract_review_candidates(df)
        assert len(result) == 2
        types = set(result["review_type"])
        assert "unclassified" in types or "other_asset" in types

    def test_occurrence_count(self):
        df = _make_unified_df([
            {"source": "bdc", "cik": "100", "issuer_name": "Acme",
             "bdc_investment_identifier": "Acme",
             "asset_category": "OTHER", "index_classification": "UNCLASSIFIED"},
            {"source": "bdc", "cik": "100", "issuer_name": "Acme",
             "bdc_investment_identifier": "Acme",
             "asset_category": "OTHER", "index_classification": "UNCLASSIFIED"},
            {"source": "bdc", "cik": "100", "issuer_name": "Acme",
             "bdc_investment_identifier": "Acme",
             "asset_category": "OTHER", "index_classification": "UNCLASSIFIED"},
        ])
        result = extract_review_candidates(df)
        assert len(result) == 1
        assert result.iloc[0]["occurrence_count"] == 3

    def test_empty_when_all_classified(self):
        df = _make_unified_df([
            {"source": "bdc", "cik": "100", "issuer_name": "Acme",
             "asset_category": "LOAN", "index_classification": "DIRECT_LENDING"},
        ])
        result = extract_review_candidates(df)
        assert len(result) == 0

    def test_includes_aggregate_suspects(self):
        df = _make_unified_df([
            {"source": "bdc", "cik": "100", "issuer_name": "Good Corp",
             "bdc_investment_identifier": "Good Corp - Term Loan",
             "asset_category": "LOAN", "index_classification": "DIRECT_LENDING",
             "fair_value": "1000000"},
        ])
        suspects = pd.DataFrame([{
            "cik": "100", "entity_name": "BDC",
            "issuer_name": "Good Corp",
            "bdc_investment_identifier": "Good Corp - Term Loan",
            "fair_value": "1000000", "reason": "outlier",
        }])
        result = extract_review_candidates(df, aggregate_suspects=suspects)
        assert len(result) == 1
        assert result.iloc[0]["review_type"] == "suspected_aggregate"


# ---------------------------------------------------------------------------
# build_review_batches
# ---------------------------------------------------------------------------

class TestBuildReviewBatches:
    def test_correct_batch_size(self):
        candidates = _make_candidates(120)
        batches = build_review_batches(candidates, batch_size=50)
        assert len(batches) == 3  # 50 + 50 + 20

    def test_single_batch(self):
        candidates = _make_candidates(5)
        batches = build_review_batches(candidates, batch_size=50)
        assert len(batches) == 1

    def test_prompt_format(self):
        candidates = _make_candidates(3)
        batches = build_review_batches(candidates, batch_size=50)
        prompt, review_ids = batches[0]
        assert "Classify the following" in prompt
        assert len(review_ids) == 3

    def test_includes_financial_signals(self):
        candidates = _make_candidates(1)
        candidates.at[0, "sample_interest_rate"] = "8.5"
        batches = build_review_batches(candidates, batch_size=50)
        prompt, _ = batches[0]
        assert "rate=8.5" in prompt

    def test_includes_current_classification(self):
        candidates = _make_candidates(1)
        candidates.at[0, "current_asset_category"] = "LOAN"
        candidates.at[0, "current_index_classification"] = "DIRECT_LENDING"
        batches = build_review_batches(candidates, batch_size=50)
        prompt, _ = batches[0]
        assert "Current: LOAN/DIRECT_LENDING" in prompt

    def test_formats_fair_value_human_readable(self):
        candidates = _make_candidates(1)
        candidates.at[0, "sample_fair_value"] = "50000000"
        batches = build_review_batches(candidates, batch_size=50)
        prompt, _ = batches[0]
        assert "$50.0M" in prompt

    def test_empty_candidates(self):
        candidates = _make_candidates(0)
        batches = build_review_batches(candidates)
        assert len(batches) == 0


# ---------------------------------------------------------------------------
# parse_review_responses
# ---------------------------------------------------------------------------

class TestParseReviewResponses:
    def test_valid_json_parsed(self):
        candidates = _make_candidates(2)
        response = json.dumps([
            {"id": 0, "is_aggregate": False, "asset_class": "LOAN",
             "confidence": "high", "reasoning": "Has loan keywords"},
            {"id": 1, "is_aggregate": True, "asset_class": "UNKNOWN",
             "confidence": "high", "reasoning": "Section header"},
        ])
        result = parse_review_responses(candidates, [response])
        assert len(result) == 2
        assert result.iloc[0]["llm_asset_class"] == "LOAN"
        assert result.iloc[1]["llm_is_aggregate"] == True

    def test_malformed_json_handled(self):
        candidates = _make_candidates(2)
        result = parse_review_responses(candidates, ["this is not json"])
        assert len(result) == 2
        # Should have defaults
        assert result.iloc[0]["llm_asset_class"] == "UNKNOWN"
        assert result.iloc[0]["llm_confidence"] == "low"

    def test_json_in_code_block(self):
        candidates = _make_candidates(1)
        response = '```json\n[{"id": 0, "is_aggregate": false, "asset_class": "EQUITY_COMMON", "confidence": "medium", "reasoning": "Equity"}]\n```'
        result = parse_review_responses(candidates, [response])
        assert result.iloc[0]["llm_asset_class"] == "EQUITY_COMMON"

    def test_confidence_levels_preserved(self):
        candidates = _make_candidates(3)
        response = json.dumps([
            {"id": 0, "is_aggregate": False, "asset_class": "LOAN",
             "confidence": "high", "reasoning": "x"},
            {"id": 1, "is_aggregate": False, "asset_class": "LOAN",
             "confidence": "medium", "reasoning": "y"},
            {"id": 2, "is_aggregate": False, "asset_class": "UNKNOWN",
             "confidence": "low", "reasoning": "z"},
        ])
        result = parse_review_responses(candidates, [response])
        assert result.iloc[0]["llm_confidence"] == "high"
        assert result.iloc[1]["llm_confidence"] == "medium"
        assert result.iloc[2]["llm_confidence"] == "low"

    def test_multiple_responses(self):
        candidates = _make_candidates(4)
        resp1 = json.dumps([
            {"id": 0, "is_aggregate": False, "asset_class": "LOAN",
             "confidence": "high", "reasoning": "a"},
            {"id": 1, "is_aggregate": False, "asset_class": "LOAN",
             "confidence": "high", "reasoning": "b"},
        ])
        resp2 = json.dumps([
            {"id": 2, "is_aggregate": True, "asset_class": "UNKNOWN",
             "confidence": "high", "reasoning": "c"},
            {"id": 3, "is_aggregate": False, "asset_class": "EQUITY_COMMON",
             "confidence": "medium", "reasoning": "d"},
        ])
        result = parse_review_responses(candidates, [resp1, resp2])
        assert result.iloc[0]["llm_asset_class"] == "LOAN"
        assert result.iloc[2]["llm_is_aggregate"] == True
        assert result.iloc[3]["llm_asset_class"] == "EQUITY_COMMON"

    def test_structured_output_list_of_dicts(self):
        """Pre-parsed structured output (list of dicts) is handled directly."""
        candidates = _make_candidates(2)
        # Simulate structured output: list of dicts (not JSON text)
        structured = [
            [
                {"id": 0, "is_aggregate": False, "asset_class": "LOAN",
                 "confidence": "high", "reasoning": "Term loan"},
                {"id": 1, "is_aggregate": True, "asset_class": "UNKNOWN",
                 "confidence": "high", "reasoning": "Subtotal"},
            ]
        ]
        result = parse_review_responses(candidates, structured)
        assert result.iloc[0]["llm_asset_class"] == "LOAN"
        assert result.iloc[0]["llm_is_aggregate"] == False
        assert result.iloc[1]["llm_is_aggregate"] == True

    def test_mixed_structured_and_text(self):
        """Handles a mix of structured and text responses in one batch list."""
        candidates = _make_candidates(3)
        structured_batch = [
            {"id": 0, "is_aggregate": False, "asset_class": "FUND",
             "confidence": "medium", "reasoning": "PE fund"},
        ]
        text_batch = json.dumps([
            {"id": 1, "is_aggregate": False, "asset_class": "EQUITY_COMMON",
             "confidence": "high", "reasoning": "Common stock"},
        ])
        result = parse_review_responses(candidates, [structured_batch, text_batch])
        assert result.iloc[0]["llm_asset_class"] == "FUND"
        assert result.iloc[1]["llm_asset_class"] == "EQUITY_COMMON"
        assert result.iloc[2]["llm_asset_class"] == "UNKNOWN"  # not covered


# ---------------------------------------------------------------------------
# Pydantic schema
# ---------------------------------------------------------------------------

class TestStructuredOutputSchema:
    def test_classification_response_model_exists(self):
        from pipeline.llm_review import ClassificationResponse, Classification
        assert ClassificationResponse is not None
        assert Classification is not None

    def test_schema_validates(self):
        from pipeline.llm_review import ClassificationResponse, Classification
        c = Classification(
            id=0, is_aggregate=False, asset_class="LOAN",
            confidence="high", reasoning="test",
        )
        resp = ClassificationResponse(classifications=[c])
        assert len(resp.classifications) == 1
        assert resp.classifications[0].asset_class == "LOAN"

    def test_schema_rejects_invalid_asset_class(self):
        from pipeline.llm_review import Classification
        with pytest.raises(Exception):
            Classification(
                id=0, is_aggregate=False, asset_class="INVALID",
                confidence="high", reasoning="test",
            )

    def test_model_dump_roundtrip(self):
        from pipeline.llm_review import Classification
        c = Classification(
            id=5, is_aggregate=True, asset_class="FUND",
            confidence="medium", reasoning="PE fund vehicle",
        )
        d = c.model_dump()
        assert d["id"] == 5
        assert d["is_aggregate"] is True
        assert d["asset_class"] == "FUND"


# ---------------------------------------------------------------------------
# apply_llm_classifications
# ---------------------------------------------------------------------------

class TestApplyLlmClassifications:
    def test_aggregates_removed(self):
        df = _make_unified_df([
            {"source": "bdc", "cik": "100", "issuer_name": "Header Row",
             "instrument_description": "", "bdc_investment_identifier": "Header Row",
             "asset_category": "OTHER", "issuer_category": "CORPORATE",
             "index_classification": "UNCLASSIFIED", "fair_value": "0"},
            {"source": "bdc", "cik": "100", "issuer_name": "Real Corp",
             "instrument_description": "Term Loan",
             "bdc_investment_identifier": "Real Corp - Term Loan",
             "asset_category": "LOAN", "issuer_category": "CORPORATE",
             "index_classification": "DIRECT_LENDING", "fair_value": "1000000"},
        ])
        lookup = pd.DataFrame([
            {"review_id": 0, "issuer_name": "Header Row",
             "instrument_description": "", "bdc_investment_identifier": "Header Row",
             "llm_is_aggregate": True, "llm_asset_class": "UNKNOWN",
             "llm_confidence": "high", "llm_reasoning": "Section header",
             "occurrence_count": 1, "review_timestamp": "2024-01-01"},
        ])
        result = apply_llm_classifications(df, lookup)
        assert len(result) == 1
        assert result.iloc[0]["issuer_name"] == "Real Corp"

    def test_reclassified_loan(self):
        df = _make_unified_df([
            {"source": "bdc", "cik": "100", "issuer_name": "Acme Corp",
             "instrument_description": "", "bdc_investment_identifier": "Acme Corp",
             "asset_category": "OTHER", "issuer_category": "CORPORATE",
             "index_classification": "UNCLASSIFIED", "fair_value": "1000000"},
        ])
        lookup = pd.DataFrame([
            {"review_id": 0, "issuer_name": "Acme Corp",
             "instrument_description": "", "bdc_investment_identifier": "Acme Corp",
             "llm_is_aggregate": False, "llm_asset_class": "LOAN",
             "llm_confidence": "high", "llm_reasoning": "Private loan",
             "occurrence_count": 1, "review_timestamp": "2024-01-01"},
        ])
        result = apply_llm_classifications(df, lookup)
        assert result.iloc[0]["asset_category"] == "LOAN"
        assert result.iloc[0]["index_classification"] == "DIRECT_LENDING"
        assert result.iloc[0]["llm_reviewed"] == True

    def test_low_confidence_left_alone(self):
        df = _make_unified_df([
            {"source": "bdc", "cik": "100", "issuer_name": "Ambiguous",
             "instrument_description": "", "bdc_investment_identifier": "Ambiguous",
             "asset_category": "OTHER", "issuer_category": "CORPORATE",
             "index_classification": "UNCLASSIFIED", "fair_value": "500000"},
        ])
        lookup = pd.DataFrame([
            {"review_id": 0, "issuer_name": "Ambiguous",
             "instrument_description": "", "bdc_investment_identifier": "Ambiguous",
             "llm_is_aggregate": False, "llm_asset_class": "LOAN",
             "llm_confidence": "low", "llm_reasoning": "Unclear",
             "occurrence_count": 1, "review_timestamp": "2024-01-01"},
        ])
        result = apply_llm_classifications(df, lookup)
        # Should still be OTHER / UNCLASSIFIED
        assert result.iloc[0]["asset_category"] == "OTHER"
        assert result.iloc[0]["index_classification"] == "UNCLASSIFIED"

    def test_llm_reviewed_flag_set(self):
        df = _make_unified_df([
            {"source": "bdc", "cik": "100", "issuer_name": "X",
             "instrument_description": "", "bdc_investment_identifier": "X",
             "asset_category": "OTHER", "issuer_category": "CORPORATE",
             "index_classification": "UNCLASSIFIED"},
            {"source": "bdc", "cik": "100", "issuer_name": "Y",
             "instrument_description": "", "bdc_investment_identifier": "Y",
             "asset_category": "LOAN", "issuer_category": "CORPORATE",
             "index_classification": "DIRECT_LENDING"},
        ])
        lookup = pd.DataFrame([
            {"review_id": 0, "issuer_name": "X",
             "instrument_description": "", "bdc_investment_identifier": "X",
             "llm_is_aggregate": False, "llm_asset_class": "LOAN",
             "llm_confidence": "high", "llm_reasoning": "loan",
             "occurrence_count": 1, "review_timestamp": "2024-01-01"},
        ])
        result = apply_llm_classifications(df, lookup)
        x_row = result[result["issuer_name"] == "X"].iloc[0]
        y_row = result[result["issuer_name"] == "Y"].iloc[0]
        assert x_row["llm_reviewed"] == True
        assert y_row["llm_reviewed"] == False

    def test_empty_lookup(self):
        df = _make_unified_df([
            {"source": "bdc", "cik": "100", "issuer_name": "X",
             "asset_category": "OTHER", "index_classification": "UNCLASSIFIED"},
        ])
        lookup = pd.DataFrame(columns=[
            "review_id", "issuer_name", "instrument_description",
            "bdc_investment_identifier", "llm_is_aggregate", "llm_asset_class",
            "llm_confidence", "llm_reasoning", "occurrence_count",
            "review_timestamp",
        ])
        result = apply_llm_classifications(df, lookup)
        assert len(result) == 1


# ---------------------------------------------------------------------------
# run_llm_review
# ---------------------------------------------------------------------------

class TestRunLlmReview:
    def test_dry_run_produces_candidates(self, tmp_path):
        df = _make_unified_df([
            {"source": "bdc", "cik": "100", "issuer_name": "Unknown",
             "bdc_investment_identifier": "Unknown",
             "asset_category": "OTHER", "index_classification": "UNCLASSIFIED"},
        ])
        candidates_file = tmp_path / "candidates.csv"
        lookup_file = tmp_path / "lookup.csv"
        unified_file = tmp_path / "unified.csv"

        with patch("pipeline.llm_review.LLM_REVIEW_CANDIDATES_FILE", candidates_file), \
             patch("pipeline.llm_review.LLM_REVIEW_LOOKUP_FILE", lookup_file), \
             patch("pipeline.llm_review.UNIFIED_HOLDINGS_FILE", unified_file):
            result = run_llm_review(unified_df=df, dry_run=True)

        # Candidates file should exist
        assert candidates_file.exists()
        # Lookup file should NOT exist (dry run)
        assert not lookup_file.exists()
        # Original df returned unchanged
        assert len(result) == 1

    def test_full_run_with_mocked_api(self, tmp_path):
        df = _make_unified_df([
            {"source": "bdc", "cik": "100", "issuer_name": "Acme",
             "instrument_description": "", "bdc_investment_identifier": "Acme",
             "asset_category": "OTHER", "issuer_category": "CORPORATE",
             "index_classification": "UNCLASSIFIED", "fair_value": "1000000"},
        ])

        mock_response = json.dumps([
            {"id": 0, "is_aggregate": False, "asset_class": "LOAN",
             "confidence": "high", "reasoning": "Private loan"},
        ])

        candidates_file = tmp_path / "candidates.csv"
        lookup_file = tmp_path / "lookup.csv"
        unified_file = tmp_path / "unified.csv"

        with patch("pipeline.llm_review.LLM_REVIEW_CANDIDATES_FILE", candidates_file), \
             patch("pipeline.llm_review.LLM_REVIEW_LOOKUP_FILE", lookup_file), \
             patch("pipeline.llm_review.UNIFIED_HOLDINGS_FILE", unified_file), \
             patch("pipeline.llm_review._call_llm_api", return_value=[mock_response]):
            result = run_llm_review(unified_df=df, dry_run=False)

        assert lookup_file.exists()
        assert unified_file.exists()
        assert result.iloc[0]["asset_category"] == "LOAN"
        assert result.iloc[0]["index_classification"] == "DIRECT_LENDING"

    def test_full_run_structured_output(self, tmp_path):
        """Structured output (list of dicts) from _call_llm_api works end-to-end."""
        df = _make_unified_df([
            {"source": "bdc", "cik": "100", "issuer_name": "Acme",
             "instrument_description": "", "bdc_investment_identifier": "Acme",
             "asset_category": "OTHER", "issuer_category": "CORPORATE",
             "index_classification": "UNCLASSIFIED", "fair_value": "1000000"},
        ])

        # Structured output: list of dicts (not JSON text)
        structured_response = [
            [{"id": 0, "is_aggregate": False, "asset_class": "LOAN",
              "confidence": "high", "reasoning": "Private loan"}]
        ]

        candidates_file = tmp_path / "candidates.csv"
        lookup_file = tmp_path / "lookup.csv"
        unified_file = tmp_path / "unified.csv"

        with patch("pipeline.llm_review.LLM_REVIEW_CANDIDATES_FILE", candidates_file), \
             patch("pipeline.llm_review.LLM_REVIEW_LOOKUP_FILE", lookup_file), \
             patch("pipeline.llm_review.UNIFIED_HOLDINGS_FILE", unified_file), \
             patch("pipeline.llm_review._call_llm_api", return_value=structured_response):
            result = run_llm_review(unified_df=df, dry_run=False)

        assert result.iloc[0]["asset_category"] == "LOAN"
        assert result.iloc[0]["index_classification"] == "DIRECT_LENDING"

    def test_resumability_existing_lookup(self, tmp_path):
        """Existing lookup table should be reused without API calls."""
        df = _make_unified_df([
            {"source": "bdc", "cik": "100", "issuer_name": "Acme",
             "instrument_description": "", "bdc_investment_identifier": "Acme",
             "asset_category": "OTHER", "issuer_category": "CORPORATE",
             "index_classification": "UNCLASSIFIED", "fair_value": "1000000"},
        ])

        # Pre-populate lookup table
        lookup = pd.DataFrame([{
            "review_id": "0", "issuer_name": "Acme",
            "instrument_description": "", "bdc_investment_identifier": "Acme",
            "llm_is_aggregate": "False", "llm_asset_class": "LOAN",
            "llm_confidence": "high", "llm_reasoning": "loan",
            "occurrence_count": "1", "review_timestamp": "2024-01-01",
        }])

        candidates_file = tmp_path / "candidates.csv"
        lookup_file = tmp_path / "lookup.csv"
        unified_file = tmp_path / "unified.csv"
        lookup.to_csv(lookup_file, index=False)

        mock_api = MagicMock(return_value=[])

        with patch("pipeline.llm_review.LLM_REVIEW_CANDIDATES_FILE", candidates_file), \
             patch("pipeline.llm_review.LLM_REVIEW_LOOKUP_FILE", lookup_file), \
             patch("pipeline.llm_review.UNIFIED_HOLDINGS_FILE", unified_file), \
             patch("pipeline.llm_review._call_llm_api", mock_api):
            result = run_llm_review(unified_df=df, dry_run=False)

        # API should NOT have been called
        mock_api.assert_not_called()
        # But classification should be applied
        assert result.iloc[0]["asset_category"] == "LOAN"
