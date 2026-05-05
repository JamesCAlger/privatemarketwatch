"""Tests for pipeline.gics_mapping module.

Covers:
- Label normalization (subtotal prefixes, trailing noise, whitespace)
- Exact GICS name matching
- Alias map resolution
- Fuzzy matching (above/below threshold)
- Aggregate label detection
- Cache load/save round-trip
- LLM batch mapping (mocked)
- End-to-end map_to_gics with mixed cached/uncached labels
- Integration with bdc_sector_breakdown output
"""

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from pipeline.gics_mapping import (
    _AGGREGATE_LABELS,
    _ALIAS_MAP,
    _FUZZY_THRESHOLD,
    _fuzzy_match,
    _gics_lookup_key,
    _load_cache,
    _load_gics_names,
    _normalize_label,
    _parse_llm_text_response,
    _save_cache,
    map_to_gics,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _reset_gics_cache():
    """Reset the module-level GICS names cache between tests."""
    import pipeline.gics_mapping as mod
    mod._gics_names = None
    yield
    mod._gics_names = None


@pytest.fixture
def gics_names():
    """Load the real GICS reference list."""
    return _load_gics_names()


# ---------------------------------------------------------------------------
# Label normalization
# ---------------------------------------------------------------------------

class TestNormalizeLabel:
    def test_strip_total_prefix(self):
        assert _normalize_label("total investments - software") == "software"

    def test_strip_total_space_prefix(self):
        assert _normalize_label("total healthcare") == "healthcare"

    def test_strip_trailing_one(self):
        assert _normalize_label("aerospace one") == "aerospace"

    def test_strip_trailing_digit(self):
        assert _normalize_label("banking1") == "banking"

    def test_strip_trailing_two(self):
        assert _normalize_label("business services two") == "business services"

    def test_strip_trailing_sector(self):
        assert _normalize_label("healthcare sector") == "healthcare"

    def test_strip_trailing_industry(self):
        assert _normalize_label("banking industry") == "banking"

    def test_strip_trailing_punctuation(self):
        assert _normalize_label("automotive sector.") == "automotive"

    def test_collapse_whitespace(self):
        assert _normalize_label("health  care   services") == "health care services"

    def test_lowercase(self):
        assert _normalize_label("Application Software") == "application software"

    def test_combined_cleanup(self):
        """Total prefix + trailing number + sector suffix."""
        assert _normalize_label("total investments - aerospace and defense sector one") == (
            "aerospace and defense"
        )


# ---------------------------------------------------------------------------
# GICS lookup key
# ---------------------------------------------------------------------------

class TestGicsLookupKey:
    def test_lowercase(self):
        assert _gics_lookup_key("Aerospace & Defense") == "aerospace and defense"

    def test_ampersand_to_and(self):
        assert _gics_lookup_key("Oil & Gas Drilling") == "oil and gas drilling"


# ---------------------------------------------------------------------------
# Exact match
# ---------------------------------------------------------------------------

class TestExactMatch:
    def test_exact_gics_name_matches(self, gics_names):
        """A label that exactly matches a GICS name should resolve."""
        result = map_to_gics(["Aerospace & Defense"])
        assert result["Aerospace & Defense"] == "Aerospace & Defense"

    def test_case_insensitive_match(self, gics_names):
        result = map_to_gics(["aerospace & defense"])
        assert result["aerospace & defense"] == "Aerospace & Defense"

    def test_and_vs_ampersand(self, gics_names):
        result = map_to_gics(["aerospace and defense"])
        # Should match via alias (alias map is checked before exact GICS match)
        assert result["aerospace and defense"] == "Aerospace & Defense"


# ---------------------------------------------------------------------------
# Alias map
# ---------------------------------------------------------------------------

class TestAliasMap:
    def test_software_alias(self):
        result = map_to_gics(["software"])
        assert result["software"] == "Application Software"

    def test_healthcare_alias(self):
        result = map_to_gics(["healthcare"])
        assert result["healthcare"] == "Health Care Services"

    def test_insurance_alias(self):
        result = map_to_gics(["insurance"])
        assert result["insurance"] == "Property & Casualty Insurance"

    def test_diversified_financials(self):
        result = map_to_gics(["diversified financials"])
        assert result["diversified financials"] == "Diversified Financial Services"

    def test_itservices(self):
        result = map_to_gics(["itservices"])
        assert result["itservices"] == "IT Consulting & Other Services"

    def test_total_prefix_is_aggregate(self):
        """Labels starting with 'total ' are aggregates -> Other."""
        result = map_to_gics(["total software"])
        assert result["total software"] == "Other"

    def test_trailing_number_then_alias(self):
        result = map_to_gics(["aerospace and defense one"])
        assert result["aerospace and defense one"] == "Aerospace & Defense"

    def test_food_and_beverage(self):
        result = map_to_gics(["food and beverage"])
        assert result["food and beverage"] == "Packaged Foods & Meats"

    def test_professional_services(self):
        result = map_to_gics(["professional services"])
        assert result["professional services"] == "Research & Consulting Services"


# ---------------------------------------------------------------------------
# Fuzzy matching
# ---------------------------------------------------------------------------

class TestFuzzyMatch:
    def test_close_match(self, gics_names):
        """A very close label should fuzzy-match."""
        result = _fuzzy_match("health care equipments", gics_names)
        assert result is not None
        name, score = result
        assert score >= _FUZZY_THRESHOLD
        assert "Health Care" in name

    def test_distant_label_no_match(self, gics_names):
        """A completely unrelated label should NOT fuzzy-match."""
        result = _fuzzy_match("xyzzy foobarbaz", gics_names)
        assert result is None

    def test_threshold_boundary(self, gics_names):
        """Labels at the boundary should be handled correctly."""
        # "Broadline Retail" vs "broadline retail" - should match
        result = _fuzzy_match("broadline retail", gics_names)
        assert result is not None
        assert result[0] == "Broadline Retail"


# ---------------------------------------------------------------------------
# Aggregate label detection
# ---------------------------------------------------------------------------

class TestAggregateLabels:
    def test_all_industries(self):
        result = map_to_gics(["all industries"])
        assert result["all industries"] == "Other"

    def test_total_investments(self):
        result = map_to_gics(["total investments"])
        assert result["total investments"] == "Other"

    def test_aggregate_sectors(self):
        result = map_to_gics(["aggregate sectors"])
        assert result["aggregate sectors"] == "Other"

    def test_assets_in_excess(self):
        result = map_to_gics(["assets in excess of other liabilities"])
        assert result["assets in excess of other liabilities"] == "Other"


# ---------------------------------------------------------------------------
# Cache load/save
# ---------------------------------------------------------------------------

class TestCaching:
    def test_save_and_load_round_trip(self, tmp_path, monkeypatch):
        """Cache saves and loads correctly."""
        cache_file = tmp_path / "test_cache.csv"
        monkeypatch.setattr(
            "pipeline.gics_mapping.GICS_LABEL_CACHE_FILE", cache_file,
        )

        cache = {
            "software": ("Application Software", "alias"),
            "healthcare": ("Health Care Services", "exact"),
        }
        _save_cache(cache)

        loaded = _load_cache()
        assert loaded["software"] == ("Application Software", "alias")
        assert loaded["healthcare"] == ("Health Care Services", "exact")

    def test_load_empty_cache(self, tmp_path, monkeypatch):
        """Non-existent cache file returns empty dict."""
        cache_file = tmp_path / "nonexistent.csv"
        monkeypatch.setattr(
            "pipeline.gics_mapping.GICS_LABEL_CACHE_FILE", cache_file,
        )
        assert _load_cache() == {}

    def test_cached_labels_not_reprocessed(self, tmp_path, monkeypatch):
        """Labels already in cache should not be re-mapped."""
        cache_file = tmp_path / "test_cache.csv"
        monkeypatch.setattr(
            "pipeline.gics_mapping.GICS_LABEL_CACHE_FILE", cache_file,
        )

        # Pre-populate cache
        cache = {"custom label xyz": ("Biotechnology", "llm")}
        _save_cache(cache)

        result = map_to_gics(["custom label xyz"])
        assert result["custom label xyz"] == "Biotechnology"


# ---------------------------------------------------------------------------
# LLM text response parsing
# ---------------------------------------------------------------------------

class TestLLMTextParsing:
    def test_parse_json_array(self):
        gics = ["Aerospace & Defense", "Biotechnology"]
        text = json.dumps([
            {"label": "aero stuff", "gics_sub_industry": "Aerospace & Defense", "confidence": "high"},
            {"label": "bio stuff", "gics_sub_industry": "Biotechnology", "confidence": "medium"},
        ])
        result = _parse_llm_text_response(text, ["aero stuff", "bio stuff"], gics)
        assert result["aero stuff"] == "Aerospace & Defense"
        assert result["bio stuff"] == "Biotechnology"

    def test_parse_with_code_fence(self):
        gics = ["Aerospace & Defense"]
        text = '```json\n[{"label": "aero", "gics_sub_industry": "Aerospace & Defense", "confidence": "high"}]\n```'
        result = _parse_llm_text_response(text, ["aero"], gics)
        assert result["aero"] == "Aerospace & Defense"

    def test_parse_invalid_gics_maps_to_other(self):
        gics = ["Aerospace & Defense"]
        text = json.dumps([
            {"label": "xyz", "gics_sub_industry": "Not A Real GICS", "confidence": "high"},
        ])
        result = _parse_llm_text_response(text, ["xyz"], gics)
        assert result["xyz"] == "Other"

    def test_parse_empty_text(self):
        result = _parse_llm_text_response("", [], [])
        assert result == {}

    def test_parse_wrapper_dict(self):
        gics = ["Biotechnology"]
        text = json.dumps({
            "mappings": [
                {"label": "bio", "gics_sub_industry": "Biotechnology", "confidence": "high"},
            ]
        })
        result = _parse_llm_text_response(text, ["bio"], gics)
        assert result["bio"] == "Biotechnology"


# ---------------------------------------------------------------------------
# LLM integration (mocked)
# ---------------------------------------------------------------------------

class TestLLMMocking:
    def test_llm_not_called_when_all_mapped(self, tmp_path, monkeypatch):
        """If all labels resolve via alias/exact, LLM is never invoked."""
        cache_file = tmp_path / "test_cache.csv"
        monkeypatch.setattr(
            "pipeline.gics_mapping.GICS_LABEL_CACHE_FILE", cache_file,
        )

        with patch("pipeline.gics_mapping._run_llm_mapping") as mock_llm:
            result = map_to_gics(["software", "healthcare", "biotechnology"])
            mock_llm.assert_not_called()

        assert result["software"] == "Application Software"
        assert result["healthcare"] == "Health Care Services"
        assert result["biotechnology"] == "Biotechnology"

    def test_llm_called_for_unmapped(self, tmp_path, monkeypatch):
        """Unmapped labels trigger LLM if OPENAI_API_KEY is set."""
        cache_file = tmp_path / "test_cache.csv"
        monkeypatch.setattr(
            "pipeline.gics_mapping.GICS_LABEL_CACHE_FILE", cache_file,
        )

        def mock_llm(unmapped, gics_names):
            return {label: "Specialized Finance" for label in unmapped}

        with patch("pipeline.gics_mapping._run_llm_mapping", side_effect=mock_llm) as mock:
            result = map_to_gics(["zzz totally unknown label 999"])
            mock.assert_called_once()

        assert result["zzz totally unknown label 999"] == "Specialized Finance"

    def test_no_api_key_returns_other(self, tmp_path, monkeypatch):
        """Without OPENAI_API_KEY, unmapped labels get 'Other'."""
        cache_file = tmp_path / "test_cache.csv"
        monkeypatch.setattr(
            "pipeline.gics_mapping.GICS_LABEL_CACHE_FILE", cache_file,
        )
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)

        # Patch _run_llm_mapping to simulate no-API behavior
        from pipeline.gics_mapping import _run_llm_mapping
        with patch("pipeline.gics_mapping._run_llm_mapping", wraps=_run_llm_mapping):
            result = map_to_gics(["zzz completely unknown xyzzy 999"])

        assert result["zzz completely unknown xyzzy 999"] == "Other"


# ---------------------------------------------------------------------------
# End-to-end map_to_gics
# ---------------------------------------------------------------------------

class TestMapToGics:
    def test_empty_list(self):
        assert map_to_gics([]) == {}

    def test_mixed_labels(self, tmp_path, monkeypatch):
        """Mix of alias, exact, aggregate, and cached labels."""
        cache_file = tmp_path / "test_cache.csv"
        monkeypatch.setattr(
            "pipeline.gics_mapping.GICS_LABEL_CACHE_FILE", cache_file,
        )

        labels = [
            "software",                  # alias
            "Aerospace & Defense",       # exact GICS
            "all industries",            # aggregate
            "biotechnology",             # alias/exact
        ]
        result = map_to_gics(labels)
        assert result["software"] == "Application Software"
        assert result["Aerospace & Defense"] == "Aerospace & Defense"
        assert result["all industries"] == "Other"
        assert result["biotechnology"] == "Biotechnology"

    def test_dedup_labels(self, tmp_path, monkeypatch):
        """Duplicate labels in input produce same result."""
        cache_file = tmp_path / "test_cache.csv"
        monkeypatch.setattr(
            "pipeline.gics_mapping.GICS_LABEL_CACHE_FILE", cache_file,
        )

        result = map_to_gics(["software", "software", "software"])
        assert len(result) == 1
        assert result["software"] == "Application Software"

    def test_cache_persisted(self, tmp_path, monkeypatch):
        """After mapping, cache file is written."""
        cache_file = tmp_path / "test_cache.csv"
        monkeypatch.setattr(
            "pipeline.gics_mapping.GICS_LABEL_CACHE_FILE", cache_file,
        )

        map_to_gics(["software", "healthcare"])
        assert cache_file.exists()

        df = pd.read_csv(cache_file, dtype=str)
        assert len(df) >= 2
        labels_in_cache = set(df["raw_label"])
        assert "software" in labels_in_cache
        assert "healthcare" in labels_in_cache


# ---------------------------------------------------------------------------
# Integration with sector breakdown
# ---------------------------------------------------------------------------

class TestIntegration:
    def test_column_in_sector_columns(self):
        """gics_sub_industry is listed in SECTOR_COLUMNS."""
        from pipeline.bdc_sector_breakdown import SECTOR_COLUMNS
        assert "gics_sub_industry" in SECTOR_COLUMNS

    def test_alias_coverage_high_fv_labels(self):
        """Top FV labels from production data should all have aliases."""
        high_fv_labels = [
            "software", "insurance", "professional services",
            "health care providers services", "financial services",
            "healthcare", "software and services",
            "commercial services supplies", "business services",
            "health care technology",
        ]
        for label in high_fv_labels:
            cleaned = _normalize_label(label)
            assert cleaned in _ALIAS_MAP, (
                f"High-FV label '{label}' (cleaned: '{cleaned}') missing from alias map"
            )

    def test_reference_file_loads(self, gics_names):
        """GICS reference file loads and has expected count."""
        assert len(gics_names) >= 150
        assert "Aerospace & Defense" in gics_names
        assert "Application Software" in gics_names
        assert "Biotechnology" in gics_names
