"""Tests for pipeline/gics_classification.py."""

import json
from unittest.mock import patch, MagicMock

import pandas as pd
import pytest

from pipeline.gics_classification import (
    _normalize_company_name,
    _classify_by_keyword,
    _classify_from_extracted_industry,
    _get_candidates,
    _get_skip_names,
    _build_batch_prompt,
    _build_web_search_prompt,
    _extract_search_name,
    _parse_batch_results,
    _parse_json_response,
    _load_cache,
    _save_cache,
    _apply_gics_to_holdings,
    _run_llm_classification,
    _SKIP_WEB_SEARCH_RE,
    classify_gics,
)


@pytest.fixture(autouse=True)
def _redirect_gics_outputs(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "pipeline.gics_classification.COMPANY_GICS_CACHE_FILE",
        tmp_path / "company_gics_cache.csv",
    )
    monkeypatch.setattr(
        "pipeline.gics_classification.UNIFIED_HOLDINGS_FILE",
        tmp_path / "private_markets_holdings.csv",
    )


# ---------------------------------------------------------------------------
# TestNormalizeCompanyName
# ---------------------------------------------------------------------------

class TestNormalizeCompanyName:
    def test_basic_lowercase(self):
        assert _normalize_company_name("Acme Corp") == "acme"

    def test_strip_llc(self):
        assert _normalize_company_name("National Vet Associates, LLC") == "national vet associates"

    def test_strip_inc(self):
        assert _normalize_company_name("Summit Software Inc.") == "summit software"

    def test_strip_holdings(self):
        assert _normalize_company_name("Apex Holdings, LLC") == "apex"

    def test_collapse_whitespace(self):
        assert _normalize_company_name("  Foo   Bar  ") == "foo bar"

    def test_strip_trailing_punct(self):
        assert _normalize_company_name("Widget Co.,") == "widget co"

    def test_empty_string(self):
        assert _normalize_company_name("") == ""

    def test_none_like(self):
        # If someone passes something odd, should not crash
        assert _normalize_company_name("LLC") == ""


# ---------------------------------------------------------------------------
# TestClassifyByKeyword
# ---------------------------------------------------------------------------

class TestClassifyByKeyword:
    def test_dental(self):
        assert _classify_by_keyword("acme dental partners") == "Health Care Services"

    def test_software(self):
        assert _classify_by_keyword("summit software solutions") == "Application Software"

    def test_restaurant(self):
        assert _classify_by_keyword("pizza restaurant group") == "Restaurants"

    def test_no_match(self):
        assert _classify_by_keyword("apex capital management") is None

    def test_hotel(self):
        assert _classify_by_keyword("hilton hotel ventures") == "Hotels, Resorts & Cruise Lines"

    def test_cybersecurity(self):
        assert _classify_by_keyword("nexus cybersecurity") == "Systems Software"


# ---------------------------------------------------------------------------
# TestClassifyFromExtractedIndustry
# ---------------------------------------------------------------------------

class TestClassifyFromExtractedIndustry:
    def test_basic_mapping(self):
        df = pd.DataFrame({
            "issuer_name": ["Acme Corp", "Acme Corp", "Beta LLC"],
            "extracted_industry": ["software", "software", "healthcare"],
            "issuer_category": ["CORPORATE", "CORPORATE", "CORPORATE"],
        })
        result = _classify_from_extracted_industry(df)
        assert result.get("acme") == "Application Software"
        assert result.get("beta") == "Health Care Services"

    def test_empty_industry_skipped(self):
        df = pd.DataFrame({
            "issuer_name": ["Foo Inc"],
            "extracted_industry": [""],
            "issuer_category": ["CORPORATE"],
        })
        result = _classify_from_extracted_industry(df)
        assert len(result) == 0

    def test_non_corporate_skipped(self):
        df = pd.DataFrame({
            "issuer_name": ["Fund ABC"],
            "extracted_industry": ["software"],
            "issuer_category": ["FUND"],
        })
        result = _classify_from_extracted_industry(df)
        assert len(result) == 0

    def test_majority_vote(self):
        df = pd.DataFrame({
            "issuer_name": ["Acme Corp"] * 3,
            "extracted_industry": ["software", "healthcare", "software"],
            "issuer_category": ["CORPORATE"] * 3,
        })
        result = _classify_from_extracted_industry(df)
        assert result.get("acme") == "Application Software"

    def test_empty_df(self):
        df = pd.DataFrame(columns=["issuer_name", "extracted_industry", "issuer_category"])
        result = _classify_from_extracted_industry(df)
        assert result == {}


# ---------------------------------------------------------------------------
# TestGetSkipNames
# ---------------------------------------------------------------------------

class TestGetSkipNames:
    def test_fund_skipped(self):
        df = pd.DataFrame({
            "issuer_name": ["BlackRock Total Fund", "Acme Corp"],
            "issuer_category": ["FUND", "CORPORATE"],
            "nport_asset_cat": ["", ""],
        })
        skip = _get_skip_names(df)
        assert "blackrock total fund" in skip
        assert "acme" not in skip

    def test_government_skipped(self):
        df = pd.DataFrame({
            "issuer_name": ["US Treasury", "Acme Corp"],
            "issuer_category": ["GOVERNMENT", "CORPORATE"],
            "nport_asset_cat": ["", ""],
        })
        skip = _get_skip_names(df)
        assert "us treasury" in skip

    def test_stiv_skipped(self):
        df = pd.DataFrame({
            "issuer_name": ["Money Market Fund"],
            "issuer_category": ["CORPORATE"],
            "nport_asset_cat": ["STIV"],
        })
        skip = _get_skip_names(df)
        assert "money market fund" in skip


# ---------------------------------------------------------------------------
# TestGetCandidates
# ---------------------------------------------------------------------------

class TestGetCandidates:
    def test_basic_candidates(self):
        df = pd.DataFrame({
            "issuer_name": ["Acme Corp", "Beta LLC", "Gamma Inc"],
            "issuer_category": ["CORPORATE", "CORPORATE", "CORPORATE"],
        })
        candidates = _get_candidates(df, already_classified=set(), skip_names=set())
        assert "acme" in candidates
        assert "beta" in candidates
        assert "gamma" in candidates

    def test_skip_already_classified(self):
        df = pd.DataFrame({
            "issuer_name": ["Acme Corp", "Beta LLC"],
            "issuer_category": ["CORPORATE", "CORPORATE"],
        })
        candidates = _get_candidates(df, already_classified={"acme"}, skip_names=set())
        assert "acme" not in candidates
        assert "beta" in candidates

    def test_skip_non_corporate(self):
        df = pd.DataFrame({
            "issuer_name": ["Fund ABC", "Acme Corp"],
            "issuer_category": ["FUND", "CORPORATE"],
        })
        candidates = _get_candidates(df, already_classified=set(), skip_names=set())
        assert "fund abc" not in candidates
        assert "acme" in candidates

    def test_skip_opaque_ids(self):
        df = pd.DataFrame({
            "issuer_name": ["9980668.SQ.RVR", "Acme Corp"],
            "issuer_category": ["CORPORATE", "CORPORATE"],
        })
        candidates = _get_candidates(df, already_classified=set(), skip_names=set())
        assert "acme" in candidates
        # Opaque IDs filtered
        assert not any("9980668" in c for c in candidates)

    def test_skip_short_names(self):
        df = pd.DataFrame({
            "issuer_name": ["AB", "Acme Corp"],
            "issuer_category": ["CORPORATE", "CORPORATE"],
        })
        candidates = _get_candidates(df, already_classified=set(), skip_names=set())
        assert "ab" not in candidates


# ---------------------------------------------------------------------------
# TestBuildBatchPrompt
# ---------------------------------------------------------------------------

class TestBuildBatchPrompt:
    def test_numbered_list(self):
        prompt = _build_batch_prompt(
            ["acme dental", "summit software"],
            ["Health Care Services", "Application Software"],
        )
        assert "1. acme dental" in prompt
        assert "2. summit software" in prompt

    def test_gics_list_included(self):
        prompt = _build_batch_prompt(
            ["acme"],
            ["Health Care Services", "Application Software"],
        )
        assert "- Health Care Services" in prompt
        assert "- Application Software" in prompt

    def test_instructions_included(self):
        prompt = _build_batch_prompt(["acme"], ["Health Care Services"])
        assert "GICS sub-industries" in prompt
        assert "Other" in prompt


# ---------------------------------------------------------------------------
# TestParseBatchResults
# ---------------------------------------------------------------------------

class TestParseBatchResults:
    def test_valid_results(self):
        companies = ["acme dental", "summit software"]
        raw = [
            {"id": 1, "gics_sub_industry": "Health Care Services", "confidence": "high"},
            {"id": 2, "gics_sub_industry": "Application Software", "confidence": "medium"},
        ]
        result = _parse_batch_results(companies, raw)
        assert result["acme dental"] == ("Health Care Services", "high")
        assert result["summit software"] == ("Application Software", "medium")

    def test_missing_ids_default_to_other(self):
        companies = ["acme", "beta"]
        raw = [{"id": 1, "gics_sub_industry": "Restaurants", "confidence": "high"}]
        result = _parse_batch_results(companies, raw)
        assert result["acme"] == ("Restaurants", "high")
        assert result["beta"] == ("Other", "low")

    def test_empty_results(self):
        companies = ["acme"]
        result = _parse_batch_results(companies, [])
        assert result["acme"] == ("Other", "low")

    def test_preserves_confidence(self):
        companies = ["acme"]
        raw = [{"id": 1, "gics_sub_industry": "Restaurants", "confidence": "low"}]
        result = _parse_batch_results(companies, raw)
        assert result["acme"][1] == "low"


# ---------------------------------------------------------------------------
# TestParseJsonResponse
# ---------------------------------------------------------------------------

class TestParseJsonResponse:
    def test_valid_json(self):
        gics_set = {"Health Care Services", "Other"}
        text = json.dumps({
            "classifications": [
                {"id": 1, "gics_sub_industry": "Health Care Services", "confidence": "high"}
            ]
        })
        result = _parse_json_response(text, 1, gics_set)
        assert len(result) == 1
        assert result[0]["gics_sub_industry"] == "Health Care Services"

    def test_invalid_gics_becomes_other(self):
        gics_set = {"Health Care Services", "Other"}
        text = json.dumps({
            "classifications": [
                {"id": 1, "gics_sub_industry": "Fake Industry", "confidence": "high"}
            ]
        })
        result = _parse_json_response(text, 1, gics_set)
        assert result[0]["gics_sub_industry"] == "Other"

    def test_invalid_json(self):
        result = _parse_json_response("not json", 1, {"Other"})
        assert result == []

    def test_empty_text(self):
        result = _parse_json_response("", 1, {"Other"})
        assert result == []


# ---------------------------------------------------------------------------
# TestCacheManagement
# ---------------------------------------------------------------------------

class TestCacheManagement:
    def test_save_and_load_roundtrip(self, tmp_path, monkeypatch):
        cache_file = tmp_path / "test_cache.csv"
        monkeypatch.setattr(
            "pipeline.gics_classification.COMPANY_GICS_CACHE_FILE", cache_file
        )
        cache = {
            "acme": ("Health Care Services", "high", "keyword"),
            "beta": ("Application Software", "medium", "llm"),
        }
        _save_cache(cache)
        loaded = _load_cache()
        assert loaded["acme"] == ("Health Care Services", "high", "keyword")
        assert loaded["beta"] == ("Application Software", "medium", "llm")

    def test_load_nonexistent_returns_empty(self, tmp_path, monkeypatch):
        cache_file = tmp_path / "nonexistent.csv"
        monkeypatch.setattr(
            "pipeline.gics_classification.COMPANY_GICS_CACHE_FILE", cache_file
        )
        loaded = _load_cache()
        assert loaded == {}

    def test_incremental_append(self, tmp_path, monkeypatch):
        cache_file = tmp_path / "test_cache.csv"
        monkeypatch.setattr(
            "pipeline.gics_classification.COMPANY_GICS_CACHE_FILE", cache_file
        )
        cache1 = {"acme": ("Health Care Services", "high", "keyword")}
        _save_cache(cache1)

        # Load, add, save again
        loaded = _load_cache()
        loaded["beta"] = ("Restaurants", "medium", "llm")
        _save_cache(loaded)

        final = _load_cache()
        assert "acme" in final
        assert "beta" in final

    def test_dedup_on_save(self, tmp_path, monkeypatch):
        cache_file = tmp_path / "test_cache.csv"
        monkeypatch.setattr(
            "pipeline.gics_classification.COMPANY_GICS_CACHE_FILE", cache_file
        )
        # Same key overwrites
        cache = {
            "acme": ("Restaurants", "high", "llm"),
        }
        _save_cache(cache)
        loaded = _load_cache()
        assert loaded["acme"][0] == "Restaurants"


# ---------------------------------------------------------------------------
# TestLLMMocking
# ---------------------------------------------------------------------------

class TestLLMMocking:
    def test_no_api_key_returns_other(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        result = _run_llm_classification(["acme", "beta"], ["Health Care Services"])
        assert result["acme"] == ("Other", "low")
        assert result["beta"] == ("Other", "low")

    @patch("pipeline.gics_classification._call_openai_batch")
    def test_llm_called_for_new_names(self, mock_call, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")
        mock_call.return_value = [
            {"id": 1, "gics_sub_industry": "Restaurants", "confidence": "high"},
        ]
        # Mock OpenAI client construction
        with patch("pipeline.gics_classification.OpenAI"):
            result = _run_llm_classification(["acme"], ["Restaurants"])
        assert result["acme"] == ("Restaurants", "high")

    @patch("pipeline.gics_classification._call_openai_batch")
    def test_failed_batch_returns_other(self, mock_call, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")
        mock_call.side_effect = Exception("API error")
        with patch("pipeline.gics_classification.OpenAI"):
            result = _run_llm_classification(["acme"], ["Restaurants"])
        assert result["acme"] == ("Other", "low")


# ---------------------------------------------------------------------------
# TestApplyEnrichment
# ---------------------------------------------------------------------------

class TestApplyEnrichment:
    def test_basic_join(self):
        from pipeline.unified_holdings import UNIFIED_COLUMNS

        # Build minimal unified df
        df = pd.DataFrame({col: [""] for col in UNIFIED_COLUMNS})
        df["issuer_name"] = ["Acme Corp"]
        df["issuer_category"] = ["CORPORATE"]

        cache = {"acme": ("Health Care Services", "high", "keyword")}
        result = _apply_gics_to_holdings(df, cache)
        assert result["gics_sub_industry"].iloc[0] == "Health Care Services"

    def test_non_corporate_stays_blank(self):
        from pipeline.unified_holdings import UNIFIED_COLUMNS

        df = pd.DataFrame({col: [""] for col in UNIFIED_COLUMNS})
        df["issuer_name"] = ["BlackRock Fund"]
        df["issuer_category"] = ["FUND"]

        cache = {}  # No entry for this fund
        result = _apply_gics_to_holdings(df, cache)
        assert result["gics_sub_industry"].iloc[0] == ""

    def test_preserves_other_columns(self):
        from pipeline.unified_holdings import UNIFIED_COLUMNS

        df = pd.DataFrame({col: ["test_val"] for col in UNIFIED_COLUMNS})
        df["issuer_name"] = ["Acme Corp"]
        df["gics_sub_industry"] = [""]

        cache = {"acme": ("Restaurants", "high", "llm")}
        result = _apply_gics_to_holdings(df, cache)
        assert result["source"].iloc[0] == "test_val"
        assert result["gics_sub_industry"].iloc[0] == "Restaurants"

    def test_empty_cache_no_change(self):
        from pipeline.unified_holdings import UNIFIED_COLUMNS

        df = pd.DataFrame({col: [""] for col in UNIFIED_COLUMNS})
        df["issuer_name"] = ["Acme Corp"]

        result = _apply_gics_to_holdings(df, {})
        assert result["gics_sub_industry"].iloc[0] == ""


# ---------------------------------------------------------------------------
# TestClassifyGicsE2E
# ---------------------------------------------------------------------------

class TestClassifyGicsE2E:
    @patch("pipeline.gics_classification._run_llm_classification")
    def test_end_to_end_with_mock_llm(self, mock_llm, tmp_path, monkeypatch):
        from pipeline.unified_holdings import UNIFIED_COLUMNS

        # Setup temp cache
        cache_file = tmp_path / "cache.csv"
        monkeypatch.setattr(
            "pipeline.gics_classification.COMPANY_GICS_CACHE_FILE", cache_file
        )
        unified_file = tmp_path / "unified.csv"
        monkeypatch.setattr(
            "pipeline.gics_classification.UNIFIED_HOLDINGS_FILE", unified_file
        )

        # Build minimal DataFrame
        df = pd.DataFrame({col: [""] for col in UNIFIED_COLUMNS})
        df["issuer_name"] = ["Summit Dental Partners, LLC"]
        df["issuer_category"] = ["CORPORATE"]
        df["extracted_industry"] = [""]
        df["nport_asset_cat"] = [""]

        # Mock LLM (shouldn't be called -- keyword should catch "dental")
        mock_llm.return_value = {}

        result = classify_gics(unified_df=df)
        assert "gics_sub_industry" in result.columns
        # "dental" keyword should have classified this
        assert result["gics_sub_industry"].iloc[0] == "Health Care Services"

    @patch("pipeline.gics_classification._run_llm_classification")
    def test_cache_only_mode(self, mock_llm, tmp_path, monkeypatch):
        from pipeline.unified_holdings import UNIFIED_COLUMNS

        cache_file = tmp_path / "cache.csv"
        monkeypatch.setattr(
            "pipeline.gics_classification.COMPANY_GICS_CACHE_FILE", cache_file
        )
        unified_file = tmp_path / "unified.csv"
        monkeypatch.setattr(
            "pipeline.gics_classification.UNIFIED_HOLDINGS_FILE", unified_file
        )

        # Pre-populate cache
        _save_cache({"acme": ("Restaurants", "high", "llm")})
        monkeypatch.setattr(
            "pipeline.gics_classification.COMPANY_GICS_CACHE_FILE", cache_file
        )

        df = pd.DataFrame({col: [""] for col in UNIFIED_COLUMNS})
        df["issuer_name"] = ["Acme Corp"]
        df["issuer_category"] = ["CORPORATE"]
        df["extracted_industry"] = [""]
        df["nport_asset_cat"] = [""]

        result = classify_gics(unified_df=df)
        assert result["gics_sub_industry"].iloc[0] == "Restaurants"
        # LLM should NOT have been called
        mock_llm.assert_not_called()

    @patch("pipeline.gics_classification._run_llm_classification")
    def test_cache_only_mode_leaves_uncached_names_blank(self, mock_llm, tmp_path, monkeypatch):
        from pipeline.unified_holdings import UNIFIED_COLUMNS

        cache_file = tmp_path / "cache.csv"
        monkeypatch.setattr(
            "pipeline.gics_classification.COMPANY_GICS_CACHE_FILE", cache_file
        )
        unified_file = tmp_path / "unified.csv"
        monkeypatch.setattr(
            "pipeline.gics_classification.UNIFIED_HOLDINGS_FILE", unified_file
        )

        _save_cache({"acme": ("Restaurants", "high", "review")})

        df = pd.DataFrame({col: ["", ""] for col in UNIFIED_COLUMNS})
        df["issuer_name"] = ["Acme Corp", "Unknown Dental LLC"]
        df["issuer_category"] = ["CORPORATE", "CORPORATE"]
        df["extracted_industry"] = ["", ""]
        df["nport_asset_cat"] = ["", ""]

        result = classify_gics(unified_df=df, cache_only=True)

        assert result["gics_sub_industry"].tolist() == ["Restaurants", ""]
        mock_llm.assert_not_called()

    @patch("pipeline.gics_classification._run_llm_classification")
    def test_column_in_output(self, mock_llm, tmp_path, monkeypatch):
        from pipeline.unified_holdings import UNIFIED_COLUMNS

        cache_file = tmp_path / "cache.csv"
        monkeypatch.setattr(
            "pipeline.gics_classification.COMPANY_GICS_CACHE_FILE", cache_file
        )
        unified_file = tmp_path / "unified.csv"
        monkeypatch.setattr(
            "pipeline.gics_classification.UNIFIED_HOLDINGS_FILE", unified_file
        )

        df = pd.DataFrame({col: [""] for col in UNIFIED_COLUMNS})
        df["issuer_name"] = ["Unknown Thing"]
        df["issuer_category"] = ["CORPORATE"]
        df["extracted_industry"] = [""]
        df["nport_asset_cat"] = [""]

        mock_llm.return_value = {"unknown thing": ("Restaurants", "medium")}

        result = classify_gics(unified_df=df)
        assert "gics_sub_industry" in result.columns
        assert result["gics_sub_industry"].iloc[0] == "Restaurants"

    @patch("pipeline.gics_classification._run_llm_classification")
    def test_fund_rows_stay_blank(self, mock_llm, tmp_path, monkeypatch):
        from pipeline.unified_holdings import UNIFIED_COLUMNS

        cache_file = tmp_path / "cache.csv"
        monkeypatch.setattr(
            "pipeline.gics_classification.COMPANY_GICS_CACHE_FILE", cache_file
        )
        unified_file = tmp_path / "unified.csv"
        monkeypatch.setattr(
            "pipeline.gics_classification.UNIFIED_HOLDINGS_FILE", unified_file
        )

        df = pd.DataFrame({col: ["", ""] for col in UNIFIED_COLUMNS})
        df["issuer_name"] = ["BlackRock Fund", "Acme Dental Inc"]
        df["issuer_category"] = ["FUND", "CORPORATE"]
        df["extracted_industry"] = ["", ""]
        df["nport_asset_cat"] = ["", ""]

        mock_llm.return_value = {}

        result = classify_gics(unified_df=df)
        # Fund row should be blank
        assert result["gics_sub_industry"].iloc[0] == ""
        # Corporate row with keyword match should be classified
        assert result["gics_sub_industry"].iloc[1] == "Health Care Services"


# ---------------------------------------------------------------------------
# TestExtractSearchName
# ---------------------------------------------------------------------------

class TestExtractSearchName:
    """Tests for _extract_search_name (DBA extraction and suffix stripping)."""

    def test_dba_extraction(self):
        """DBA names should be extracted."""
        name = "Bayshore Intermediate #2, L.P. (dba Boomi), First Lien Senior Secured Loan"
        assert _extract_search_name(name) == "Boomi"

    def test_dba_case_insensitive(self):
        """DBA match should be case-insensitive."""
        name = "Crewline Buyer, Inc. (DBA New Relic)"
        assert _extract_search_name(name) == "New Relic"

    def test_fka_extraction(self):
        """FKA names should also be extracted."""
        name = "Innovation Ventures (fka 5 Hour Energy)"
        assert _extract_search_name(name) == "5 Hour Energy"

    def test_strip_loan_suffix(self):
        """Position descriptions should be stripped."""
        name = "Zendesk, Inc., First Lien Senior Secured Loan"
        assert _extract_search_name(name) == "Zendesk, Inc."

    def test_strip_trailing_number(self):
        """Trailing position numbers should be stripped."""
        name = "Park Place Technologies, LLC 1"
        assert _extract_search_name(name) == "Park Place Technologies, LLC"

    def test_no_suffix_unchanged(self):
        """Names without suffixes pass through."""
        name = "Bazaarvoice"
        assert _extract_search_name(name) == "Bazaarvoice"


# ---------------------------------------------------------------------------
# TestSkipWebSearchFilter
# ---------------------------------------------------------------------------

class TestSkipWebSearchFilter:
    """Tests for _SKIP_WEB_SEARCH_RE (non-classifiable name filter)."""

    def test_skip_investments(self):
        assert _SKIP_WEB_SEARCH_RE.match("Investments")
        assert _SKIP_WEB_SEARCH_RE.match("Debt Investments")

    def test_skip_jv(self):
        assert _SKIP_WEB_SEARCH_RE.match("BCRED Emerald JV")
        assert _SKIP_WEB_SEARCH_RE.match("Credit Opportunities Partners JV, LLC")

    def test_skip_note_issuer(self):
        assert _SKIP_WEB_SEARCH_RE.match("Silver Point Loan Note Issuer LLC /")
        assert _SKIP_WEB_SEARCH_RE.match("Varagon Structured Note Issuer I LLC /")

    def test_skip_coinvest(self):
        assert _SKIP_WEB_SEARCH_RE.match("EQT VIII Co-Investment (D) SCSP")

    def test_skip_non_controlled(self):
        assert _SKIP_WEB_SEARCH_RE.match(
            "Investments in non-controlled, non-affiliated portfolio companies"
        )

    def test_allow_real_companies(self):
        """Real companies should NOT be filtered."""
        assert not _SKIP_WEB_SEARCH_RE.match("Kaseya, Inc.")
        assert not _SKIP_WEB_SEARCH_RE.match("Aventiv Technologies, LLC")
        assert not _SKIP_WEB_SEARCH_RE.match("Snoopy Bidco")
        assert not _SKIP_WEB_SEARCH_RE.match("Bazaarvoice")


# ---------------------------------------------------------------------------
# TestBuildWebSearchPrompt
# ---------------------------------------------------------------------------

class TestBuildWebSearchPrompt:
    """Tests for _build_web_search_prompt."""

    def test_numbered_format(self):
        companies = [
            (1, "Boomi", "DIRECT_LENDING; held by Blue Owl"),
            (2, "New Relic", "DIRECT_LENDING; held by Blue Owl"),
        ]
        gics = ["Application Software", "Health Care Technology"]
        prompt = _build_web_search_prompt(companies, gics)
        assert "1. Boomi" in prompt
        assert "2. New Relic" in prompt
        assert "[context:" in prompt
        assert "EXACTLY 2 entries" in prompt

    def test_gics_list_included(self):
        companies = [(1, "Test Co", "")]
        gics = ["Application Software", "Restaurants"]
        prompt = _build_web_search_prompt(companies, gics)
        assert "- Application Software" in prompt
        assert "- Restaurants" in prompt
