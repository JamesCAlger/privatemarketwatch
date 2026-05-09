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
    _is_aggregate,
    _load_cache,
    _load_gics_hierarchy,
    _load_gics_names,
    _normalize_label,
    _parse_llm_text_response,
    _save_cache,
    _try_remap_stale,
    get_industry_group,
    map_to_gics,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _reset_gics_cache():
    """Reset the module-level GICS names and hierarchy caches between tests."""
    import pipeline.gics_mapping as mod
    mod._gics_names = None
    mod._gics_hierarchy = None
    yield
    mod._gics_names = None
    mod._gics_hierarchy = None


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


# ---------------------------------------------------------------------------
# GICS hierarchy
# ---------------------------------------------------------------------------

class TestGicsHierarchy:
    def test_hierarchy_loads(self):
        """Hierarchy file loads and has expected entries."""
        hierarchy = _load_gics_hierarchy()
        assert len(hierarchy) >= 150
        assert "Application Software" in hierarchy
        assert "Aerospace & Defense" in hierarchy

    def test_hierarchy_structure(self):
        """Each entry has sector, industry_group, and industry."""
        hierarchy = _load_gics_hierarchy()
        for sub_ind, entry in hierarchy.items():
            assert "sector" in entry, f"Missing sector for {sub_ind}"
            assert "industry_group" in entry, f"Missing industry_group for {sub_ind}"
            assert "industry" in entry, f"Missing industry for {sub_ind}"

    def test_software_hierarchy(self):
        hierarchy = _load_gics_hierarchy()
        entry = hierarchy["Application Software"]
        assert entry["sector"] == "Information Technology"
        assert entry["industry_group"] == "Software & Services"
        assert entry["industry"] == "Software"

    def test_aerospace_hierarchy(self):
        hierarchy = _load_gics_hierarchy()
        entry = hierarchy["Aerospace & Defense"]
        assert entry["sector"] == "Industrials"
        assert entry["industry_group"] == "Capital Goods"

    def test_health_care_services_hierarchy(self):
        hierarchy = _load_gics_hierarchy()
        entry = hierarchy["Health Care Services"]
        assert entry["sector"] == "Health Care"
        assert entry["industry_group"] == "Health Care Equipment & Services"

    def test_get_industry_group_known(self):
        assert get_industry_group("Application Software") == "Software & Services"
        assert get_industry_group("Aerospace & Defense") == "Capital Goods"
        assert get_industry_group("Broadline Retail") == "Consumer Discretionary Distribution & Retail"

    def test_get_industry_group_unknown(self):
        """Unknown sub-industry returns itself."""
        assert get_industry_group("Not A Real Sub-Industry") == "Not A Real Sub-Industry"

    def test_get_industry_group_other(self):
        """'Other' is not in hierarchy, returns itself."""
        assert get_industry_group("Other") == "Other"

    def test_all_gics_names_in_hierarchy(self):
        """Every sub-industry from the reference list is in the hierarchy."""
        gics_names = _load_gics_names()
        hierarchy = _load_gics_hierarchy()
        for name in gics_names:
            assert name in hierarchy, f"GICS sub-industry '{name}' missing from hierarchy"

    def test_unique_industry_groups(self):
        """Hierarchy should produce ~24 unique industry groups."""
        hierarchy = _load_gics_hierarchy()
        groups = set(entry["industry_group"] for entry in hierarchy.values())
        assert 20 <= len(groups) <= 30, f"Expected ~24 industry groups, got {len(groups)}"


# ---------------------------------------------------------------------------
# Expanded aggregate label detection
# ---------------------------------------------------------------------------

class TestExpandedAggregates:
    def test_common_stock_is_aggregate(self):
        result = map_to_gics(["common stock"])
        assert result["common stock"] == "Other"

    def test_preferred_stock_is_aggregate(self):
        result = map_to_gics(["preferred stock"])
        assert result["preferred stock"] == "Other"

    def test_warrants_is_aggregate(self):
        result = map_to_gics(["warrants"])
        assert result["warrants"] == "Other"

    def test_senior_secured_loans_is_aggregate(self):
        result = map_to_gics(["senior secured loans"])
        assert result["senior secured loans"] == "Other"

    def test_collateralized_loan_obligation_is_aggregate(self):
        result = map_to_gics(["collateralized loan obligation"])
        assert result["collateralized loan obligation"] == "Other"

    def test_geographic_labels_are_aggregate(self):
        for label in ["northeast", "midwest", "southeast", "west", "germany", "united kingdom"]:
            result = map_to_gics([label])
            assert result[label] == "Other", f"'{label}' should be aggregate"

    def test_vague_labels_are_aggregate(self):
        for label in ["service", "services", "business", "other", "product"]:
            result = map_to_gics([label])
            assert result[label] == "Other", f"'{label}' should be aggregate"

    def test_money_market_fund_is_aggregate(self):
        result = map_to_gics(["money market fund"])
        assert result["money market fund"] == "Other"

    def test_class_prefix_is_aggregate(self):
        result = map_to_gics(["class a common stock"])
        assert result["class a common stock"] == "Other"

    def test_net_assets_is_aggregate(self):
        result = map_to_gics(["net assets"])
        assert result["net assets"] == "Other"

    def test_forward_contract_is_aggregate(self):
        result = map_to_gics(["forward contract"])
        assert result["forward contract"] == "Other"


# ---------------------------------------------------------------------------
# Regex-based aggregate detection
# ---------------------------------------------------------------------------

class TestRegexAggregates:
    def test_llc_label_is_aggregate(self):
        assert _is_aggregate("acme holdings llc", "acme holdings llc")

    def test_inc_label_is_aggregate(self):
        assert _is_aggregate("acme inc.", "acme inc.")

    def test_lp_label_is_aggregate(self):
        assert _is_aggregate("acme fund l.p.", "acme fund l.p.")

    def test_percent_label_is_aggregate(self):
        assert _is_aggregate("5 percent notes", "5 percent notes")

    def test_treasury_bill_is_aggregate(self):
        assert _is_aggregate("treasury bill", "treasury bill")

    def test_government_securities_is_aggregate(self):
        assert _is_aggregate("government securities", "government securities")

    def test_fidelity_is_aggregate(self):
        assert _is_aggregate("fidelity money market", "fidelity money market")

    def test_real_industry_is_not_aggregate(self):
        assert not _is_aggregate("software", "software")
        assert not _is_aggregate("healthcare", "healthcare")
        assert not _is_aggregate("aerospace", "aerospace")


# ---------------------------------------------------------------------------
# Expanded alias map
# ---------------------------------------------------------------------------

class TestExpandedAliases:
    def test_retailing_and_distribution(self):
        result = map_to_gics(["retailing and distribution"])
        assert result["retailing and distribution"] == "Broadline Retail"

    def test_consumer_goods_non_durable(self):
        result = map_to_gics(["consumer goods non durable"])
        assert result["consumer goods non durable"] == "Packaged Foods & Meats"

    def test_consumer_goods_durable(self):
        result = map_to_gics(["consumer goods durable"])
        assert result["consumer goods durable"] == "Home Furnishings"

    def test_media_diversified_and_production(self):
        result = map_to_gics(["media diversified and production"])
        assert result["media diversified and production"] == "Movies & Entertainment"

    def test_cannabis(self):
        result = map_to_gics(["cannabis"])
        assert result["cannabis"] == "Agricultural Products & Services"

    def test_insurance_sectors(self):
        result = map_to_gics(["insurance sectors"])
        assert result["insurance sectors"] == "Property & Casualty Insurance"

    def test_green_technology(self):
        result = map_to_gics(["green technology"])
        assert result["green technology"] == "Renewable Electricity"

    def test_artificial_intelligence(self):
        result = map_to_gics(["artificial intelligence"])
        assert result["artificial intelligence"] == "Application Software"

    def test_ecommerce(self):
        result = map_to_gics(["ecommerce"])
        assert result["ecommerce"] == "Broadline Retail"

    def test_wholesale(self):
        result = map_to_gics(["wholesale"])
        assert result["wholesale"] == "Distributors"

    def test_franchising(self):
        result = map_to_gics(["franchising"])
        assert result["franchising"] == "Restaurants"

    def test_infrastructure(self):
        result = map_to_gics(["infrastructure"])
        assert result["infrastructure"] == "Construction & Engineering"

    def test_food_and_staples(self):
        result = map_to_gics(["food and staples"])
        assert result["food and staples"] == "Packaged Foods & Meats"


# ---------------------------------------------------------------------------
# Cache invalidation for stale LLM entries
# ---------------------------------------------------------------------------

class TestCacheInvalidation:
    def test_stale_llm_other_remapped_to_alias(self, tmp_path, monkeypatch):
        """A stale LLM 'Other' entry that now has an alias gets remapped."""
        cache_file = tmp_path / "test_cache.csv"
        monkeypatch.setattr(
            "pipeline.gics_mapping.GICS_LABEL_CACHE_FILE", cache_file,
        )

        # Pre-populate cache with stale LLM "Other" for a label we now have an alias for
        cache = {"retailing and distribution": ("Other", "llm")}
        _save_cache(cache)

        result = map_to_gics(["retailing and distribution"])
        assert result["retailing and distribution"] == "Broadline Retail"

        # Verify cache was updated
        loaded = _load_cache()
        assert loaded["retailing and distribution"][0] == "Broadline Retail"
        assert loaded["retailing and distribution"][1] == "alias"

    def test_stale_llm_other_aggregate_stays_other(self, tmp_path, monkeypatch):
        """A stale LLM 'Other' for an aggregate label stays 'Other' (source updated)."""
        cache_file = tmp_path / "test_cache.csv"
        monkeypatch.setattr(
            "pipeline.gics_mapping.GICS_LABEL_CACHE_FILE", cache_file,
        )

        cache = {"common stock": ("Other", "llm")}
        _save_cache(cache)

        result = map_to_gics(["common stock"])
        assert result["common stock"] == "Other"

        loaded = _load_cache()
        assert loaded["common stock"][1] == "aggregate"

    def test_non_stale_llm_entry_preserved(self, tmp_path, monkeypatch):
        """A cached LLM entry with a real GICS mapping is not invalidated."""
        cache_file = tmp_path / "test_cache.csv"
        monkeypatch.setattr(
            "pipeline.gics_mapping.GICS_LABEL_CACHE_FILE", cache_file,
        )

        cache = {"some custom label": ("Biotechnology", "llm")}
        _save_cache(cache)

        result = map_to_gics(["some custom label"])
        assert result["some custom label"] == "Biotechnology"

    def test_try_remap_stale_returns_none_for_unknown(self):
        """_try_remap_stale returns None if no better mapping found."""
        gics_names = _load_gics_names()
        gics_exact = {n.strip().lower().replace("&", "and"): n for n in gics_names}
        result = _try_remap_stale("zzz unknown xyzzy 999", gics_exact, gics_names)
        assert result is None
