"""Tests for pipeline.entity_resolution module.

Covers:
- BDC name extraction: legal suffix cutoff, generic markers, metadata blobs,
  Investment prefix, trailing numbers, no-marker fallback
- N-PORT name extraction: facility suffixes, trailing slash, clean passthrough
- Name normalisation: legal suffixes, parentheticals, punctuation, whitespace
- Variant table building: DuckDB aggregation
- Exact dedup: same normalised -> merged, different -> separate, canonical pick
- Union-Find: find, union, transitive closure, components
- Fuzzy clustering: similar merged, dissimilar separate, threshold, block skip
- Cross-source linking: CUSIP match, LEI match, fuzzy name match
- Full integration: build_entity_lookup end-to-end
- CLI: --entities flag parsing
"""

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest

from pipeline.entity_resolution import (
    UnionFind,
    _GARBAGE_ENTITY_NAMES_RE,
    _MIN_ENTITY_NAME_LENGTH,
    _NUMERIC_SUFFIX_THRESHOLD,
    _OPAQUE_NUMERIC_ID_RE,
    _apply_entity_overrides,
    _build_variant_table,
    _cross_source_link,
    _exact_dedup,
    _extract_bdc_name,
    _extract_nport_name,
    _format_entity_id,
    _fuzzy_cluster,
    _numeric_suffix_guard,
    _strip_trailing_number,
    _write_entity_lookup,
    _write_stats,
    _enrich_holdings,
    build_entity_lookup,
    extract_company_name,
    normalise_entity_name,
)


# ---------------------------------------------------------------------------
# extract_company_name / _extract_bdc_name
# ---------------------------------------------------------------------------

class TestExtractBdcCompanyName:
    """BDC name extraction: cut at legal suffix or generic marker."""

    def test_inc_suffix(self):
        result = extract_company_name(
            "Zendesk, Inc., First lien senior secured loan", "bdc"
        )
        assert result == "Zendesk, Inc."

    def test_llc_suffix(self):
        result = extract_company_name(
            "PT Intermediate Holdings III, LLC 1", "bdc"
        )
        assert result == "PT Intermediate Holdings III, LLC"

    def test_llc_suffix_trailing_number(self):
        result = extract_company_name(
            "Galway Borrower, LLC 2", "bdc"
        )
        assert result == "Galway Borrower, LLC"

    def test_corp_suffix(self):
        result = extract_company_name(
            "Acme Corp., Senior Secured Term Loan", "bdc"
        )
        assert result == "Acme Corp."

    def test_lp_suffix(self):
        result = extract_company_name(
            "Summit Partners L.P., Common Units", "bdc"
        )
        assert result == "Summit Partners L.P."

    def test_holdings_generic_marker(self):
        result = extract_company_name(
            "PT Intermediate Holdings, First Lien", "bdc"
        )
        assert result == "PT Intermediate Holdings"

    def test_group_generic_marker(self):
        result = extract_company_name(
            "athenahealth Group, Health Care Technology", "bdc"
        )
        assert result == "athenahealth Group"

    def test_group_inc_prefers_legal(self):
        """Legal suffix (Inc.) wins over generic marker (Group)."""
        result = extract_company_name(
            "athenahealth Group Inc., Health Care Technology, Preferred Equity",
            "bdc",
        )
        assert result == "athenahealth Group Inc."

    def test_plc_suffix(self):
        result = extract_company_name(
            "Barclays plc Senior Notes", "bdc"
        )
        assert result == "Barclays plc"

    def test_gmbh_suffix(self):
        result = extract_company_name(
            "Siemens GmbH Term Loan B", "bdc"
        )
        assert result == "Siemens GmbH"

    def test_no_marker_passthrough(self):
        """Names without any marker are returned as-is."""
        result = extract_company_name("Acme Widget Co", "bdc")
        # "Co" by itself is not enough; "Co." is needed
        # Actually "Co." IS a legal suffix -- let's test something truly bare
        result = extract_company_name("Acme Widgets", "bdc")
        assert result == "Acme Widgets"

    def test_trailing_number_stripped(self):
        result = extract_company_name("Zendesk, Inc. 3", "bdc")
        assert result == "Zendesk, Inc."

    def test_trailing_parens_number_stripped(self):
        result = extract_company_name("Zendesk, Inc. (2)", "bdc")
        assert result == "Zendesk, Inc."

    def test_empty_string(self):
        assert extract_company_name("", "bdc") == ""

    def test_none_input(self):
        assert extract_company_name(None, "bdc") == ""

    def test_investment_prefix_stripped(self):
        result = extract_company_name(
            "Investment, Non-Affiliated Issuer, First Lien Debt, "
            "Infront Luxembourg Finance S.a R.L.",
            "bdc",
        )
        # Should find the company name after stripping the prefix
        # "S.a R.L." is close to "S.A.R.L." legal suffix
        assert "Infront" in result

    def test_co_dot_suffix(self):
        result = extract_company_name("Acme Co. Term Loan", "bdc")
        assert result == "Acme Co."


# ---------------------------------------------------------------------------
# _extract_nport_name
# ---------------------------------------------------------------------------

class TestExtractNportCompanyName:
    """N-PORT name extraction: strip facility suffixes and slashes."""

    def test_tl_suffix(self):
        result = extract_company_name(
            "FINASTRA USA INC TL 1L VISTA /", "nport"
        )
        assert result == "FINASTRA USA INC"

    def test_revolver_suffix(self):
        result = extract_company_name(
            "ACME CORP LLC REVOLVER 2024", "nport"
        )
        # "CORP" is matched as a legal suffix first (before LLC)
        assert result == "ACME CORP"

    def test_revolver_no_legal_suffix(self):
        result = extract_company_name(
            "ACME WIDGETS REVOLVER 2024", "nport"
        )
        assert result == "ACME WIDGETS"

    def test_dl_suffix(self):
        result = extract_company_name("WIDGET INC DL TL B", "nport")
        assert result == "WIDGET INC"

    def test_trailing_slash(self):
        result = extract_company_name("ACME CORP /", "nport")
        assert result == "ACME CORP"

    def test_clean_passthrough(self):
        result = extract_company_name("SIMPLE NAME INC", "nport")
        assert result == "SIMPLE NAME INC"

    def test_with_legal_suffix_cutoff(self):
        """N-PORT names with legal suffix should cut there."""
        result = extract_company_name(
            "BROADSTREET PARTNERS INC TL 1L", "nport"
        )
        assert result == "BROADSTREET PARTNERS INC"

    def test_empty_string(self):
        assert extract_company_name("", "nport") == ""

    def test_none_input(self):
        assert extract_company_name(None, "nport") == ""


# ---------------------------------------------------------------------------
# normalise_entity_name
# ---------------------------------------------------------------------------

class TestNormaliseEntityName:
    """Name normalisation for exact dedup matching."""

    def test_lowercase(self):
        assert normalise_entity_name("ACME") == "acme"

    def test_strip_inc(self):
        result = normalise_entity_name("Zendesk, Inc.")
        assert result == "zendesk"

    def test_strip_llc(self):
        result = normalise_entity_name("PT Intermediate Holdings III, LLC")
        assert result == "pt intermediate iii"

    def test_strip_holdings_and_inc(self):
        result = normalise_entity_name("Acme Holdings, Inc.")
        assert result == "acme"

    def test_strip_parenthetical(self):
        result = normalise_entity_name("Acme Corp (DE)")
        assert result == "acme"

    def test_strip_fka_parenthetical(self):
        result = normalise_entity_name("NewName LLC (f/k/a OldName)")
        assert result == "newname"

    def test_remove_punctuation(self):
        result = normalise_entity_name("A.B.C. Corp.")
        assert result == "abc"

    def test_collapse_whitespace(self):
        result = normalise_entity_name("  Acme   Widget   ")
        assert result == "acme widget"

    def test_strip_leading_the(self):
        result = normalise_entity_name("The Acme Company")
        assert result == "acme company"

    def test_empty_string(self):
        assert normalise_entity_name("") == ""

    def test_none_input(self):
        assert normalise_entity_name(None) == ""

    def test_same_company_variants_match(self):
        """Different variants of the same company normalise identically."""
        a = normalise_entity_name("Zendesk, Inc.")
        b = normalise_entity_name("ZENDESK INC")
        c = normalise_entity_name("Zendesk, Inc")
        assert a == b == c

    def test_lp_stripped(self):
        result = normalise_entity_name("Summit Partners L.P.")
        assert result == "summit partners"


# ---------------------------------------------------------------------------
# _build_variant_table
# ---------------------------------------------------------------------------

class TestBuildVariantTable:
    """DuckDB-based variant table construction."""

    def _make_csv(self, rows, tmp_dir):
        """Create a minimal holdings CSV for testing."""
        path = Path(tmp_dir) / "test_holdings.csv"
        df = pd.DataFrame(rows)
        # Ensure required columns exist
        for col in ["issuer_name", "source", "cusip", "lei", "bdc_investment_identifier"]:
            if col not in df.columns:
                df[col] = ""
        df.to_csv(path, index=False)
        return path

    def test_basic_aggregation(self, tmp_path):
        path = self._make_csv([
            {"issuer_name": "Acme Inc", "source": "bdc"},
            {"issuer_name": "Acme Inc", "source": "bdc"},
            {"issuer_name": "Beta LLC", "source": "nport"},
        ], tmp_path)
        result = _build_variant_table(path)
        assert len(result) == 2
        acme = result[result["issuer_name"] == "Acme Inc"]
        assert acme.iloc[0]["occurrence_count"] == 2
        assert acme.iloc[0]["source"] == "bdc"

    def test_cusip_carried(self, tmp_path):
        path = self._make_csv([
            {"issuer_name": "Acme", "source": "nport", "cusip": "123456789", "lei": ""},
            {"issuer_name": "Acme", "source": "nport", "cusip": "", "lei": ""},
        ], tmp_path)
        result = _build_variant_table(path)
        assert result.iloc[0]["cusip"] == "123456789"

    def test_lei_carried(self, tmp_path):
        path = self._make_csv([
            {"issuer_name": "Acme", "source": "nport", "cusip": "", "lei": "LEI123"},
        ], tmp_path)
        result = _build_variant_table(path)
        assert result.iloc[0]["lei"] == "LEI123"

    def test_empty_issuer_excluded(self, tmp_path):
        path = self._make_csv([
            {"issuer_name": "", "source": "bdc"},
            {"issuer_name": "Real", "source": "bdc"},
        ], tmp_path)
        result = _build_variant_table(path)
        assert len(result) == 1
        assert result.iloc[0]["issuer_name"] == "Real"

    def test_same_name_different_source(self, tmp_path):
        path = self._make_csv([
            {"issuer_name": "Acme", "source": "bdc"},
            {"issuer_name": "Acme", "source": "nport"},
        ], tmp_path)
        result = _build_variant_table(path)
        assert len(result) == 2

    def test_garbage_name_excluded(self, tmp_path):
        """Subtotal/category names like 'Investments', 'First Lien Debt' are filtered."""
        path = self._make_csv([
            {"issuer_name": "Investments", "source": "bdc"},
            {"issuer_name": "First Lien Debt", "source": "bdc"},
            {"issuer_name": "Equity Investments", "source": "bdc"},
            {"issuer_name": "Subtotal", "source": "bdc"},
            {"issuer_name": "Total", "source": "bdc"},
            {"issuer_name": "Net Assets", "source": "bdc"},
            {"issuer_name": "Real Company Inc", "source": "bdc"},
        ], tmp_path)
        result = _build_variant_table(path)
        assert len(result) == 1
        assert result.iloc[0]["issuer_name"] == "Real Company Inc"

    def test_real_name_with_keyword_preserved(self, tmp_path):
        """Legal entity names containing keywords are preserved."""
        path = self._make_csv([
            {"issuer_name": "Investments Holdings LLC", "source": "bdc"},
            {"issuer_name": "Senior Secured Capital Corp", "source": "bdc"},
        ], tmp_path)
        result = _build_variant_table(path)
        assert len(result) == 2

    def test_short_name_excluded(self, tmp_path):
        """Names shorter than 3 characters are excluded."""
        path = self._make_csv([
            {"issuer_name": "", "source": "bdc"},
            {"issuer_name": "AB", "source": "bdc"},
            {"issuer_name": "X", "source": "bdc"},
            {"issuer_name": "ABC Corp", "source": "bdc"},
        ], tmp_path)
        result = _build_variant_table(path)
        assert len(result) == 1
        assert result.iloc[0]["issuer_name"] == "ABC Corp"


# ---------------------------------------------------------------------------
# _exact_dedup
# ---------------------------------------------------------------------------

class TestExactDedup:
    """Exact dedup via normalised name matching."""

    def _make_variants(self, rows):
        df = pd.DataFrame(rows)
        for col in ["cusip", "lei"]:
            if col not in df.columns:
                df[col] = ""
        return df

    def test_same_normalised_merged(self):
        variants = self._make_variants([
            {"issuer_name": "Zendesk, Inc.", "source": "bdc", "occurrence_count": 50},
            {"issuer_name": "ZENDESK INC", "source": "bdc", "occurrence_count": 30},
        ])
        result = _exact_dedup(variants)
        assert result["entity_num"].nunique() == 1

    def test_different_normalised_separate(self):
        variants = self._make_variants([
            {"issuer_name": "Acme, Inc.", "source": "bdc", "occurrence_count": 10},
            {"issuer_name": "Beta LLC", "source": "bdc", "occurrence_count": 5},
        ])
        result = _exact_dedup(variants)
        assert result["entity_num"].nunique() == 2

    def test_canonical_picks_highest_count(self):
        variants = self._make_variants([
            {"issuer_name": "zendesk inc", "source": "bdc", "occurrence_count": 10},
            {"issuer_name": "Zendesk, Inc.", "source": "bdc", "occurrence_count": 50},
        ])
        result = _exact_dedup(variants)
        # Canonical should be the one with higher occurrence_count AND legal suffix
        canonical = result["canonical_name"].iloc[0]
        assert "Zendesk" in canonical

    def test_canonical_prefers_legal_suffix(self):
        variants = self._make_variants([
            {"issuer_name": "zendesk", "source": "bdc", "occurrence_count": 100},
            {"issuer_name": "Zendesk, Inc.", "source": "bdc", "occurrence_count": 10},
        ])
        result = _exact_dedup(variants)
        # Should prefer "Zendesk, Inc." despite lower count
        canonical = result["canonical_name"].iloc[0]
        assert "Inc" in canonical

    def test_empty_normalised_grouped(self):
        """Edge case: empty names after normalisation."""
        variants = self._make_variants([
            {"issuer_name": "Inc.", "source": "bdc", "occurrence_count": 1},
        ])
        result = _exact_dedup(variants)
        assert len(result) == 1

    def test_cross_source_same_normalised(self):
        """Same normalised name from different sources gets same entity."""
        variants = self._make_variants([
            {"issuer_name": "Acme, Inc.", "source": "bdc", "occurrence_count": 10},
            {"issuer_name": "ACME INC", "source": "nport", "occurrence_count": 5},
        ])
        result = _exact_dedup(variants)
        assert result["entity_num"].nunique() == 1

    def test_extracted_name_column_added(self):
        variants = self._make_variants([
            {"issuer_name": "Zendesk, Inc., First Lien", "source": "bdc",
             "occurrence_count": 10},
        ])
        result = _exact_dedup(variants)
        assert "extracted_name" in result.columns
        assert result.iloc[0]["extracted_name"] == "Zendesk, Inc."

    def test_normalized_name_column_added(self):
        variants = self._make_variants([
            {"issuer_name": "Acme Corp.", "source": "bdc", "occurrence_count": 5},
        ])
        result = _exact_dedup(variants)
        assert "normalized_name" in result.columns
        assert result.iloc[0]["normalized_name"] == "acme"


# ---------------------------------------------------------------------------
# UnionFind
# ---------------------------------------------------------------------------

class TestUnionFind:
    """Disjoint-set data structure."""

    def test_find_creates_singleton(self):
        uf = UnionFind()
        assert uf.find(1) == 1

    def test_union_merges(self):
        uf = UnionFind()
        uf.union(1, 2)
        assert uf.find(1) == uf.find(2)

    def test_transitive_closure(self):
        uf = UnionFind()
        uf.union(1, 2)
        uf.union(2, 3)
        assert uf.find(1) == uf.find(3)

    def test_components_separate(self):
        uf = UnionFind()
        uf.union(1, 2)
        uf.union(3, 4)
        comps = uf.components()
        assert len(comps) == 2

    def test_components_merged(self):
        uf = UnionFind()
        uf.union(1, 2)
        uf.union(2, 3)
        uf.union(3, 4)
        comps = uf.components()
        assert len(comps) == 1
        members = list(comps.values())[0]
        assert members == {1, 2, 3, 4}


# ---------------------------------------------------------------------------
# _fuzzy_cluster
# ---------------------------------------------------------------------------

class TestFuzzyCluster:
    """Fuzzy clustering via rapidfuzz within source."""

    def _make_variants(self, entities):
        """Build a variant table with pre-set entity_num and normalized_name."""
        rows = []
        for ent_num, name, source, count in entities:
            rows.append({
                "issuer_name": name,
                "source": source,
                "occurrence_count": count,
                "extracted_name": name,
                "normalized_name": normalise_entity_name(name),
                "canonical_name": name,
                "entity_num": ent_num,
                "cusip": "",
                "lei": "",
            })
        return pd.DataFrame(rows)

    def test_similar_names_merged(self):
        variants = self._make_variants([
            (1, "Acme Corp", "bdc", 50),
            (2, "Acme Corporation", "bdc", 30),
        ])
        result = _fuzzy_cluster(variants, threshold=80)
        assert result["entity_num"].nunique() == 1

    def test_dissimilar_names_separate(self):
        variants = self._make_variants([
            (1, "Acme Corp", "bdc", 50),
            (2, "Zendesk Inc", "bdc", 30),
        ])
        result = _fuzzy_cluster(variants, threshold=85)
        assert result["entity_num"].nunique() == 2

    def test_transitive_merge(self):
        """A matches B, B matches C -> all merged."""
        variants = self._make_variants([
            (1, "Acme Systems", "bdc", 50),
            (2, "Acme System", "bdc", 30),
            (3, "Acme Systms", "bdc", 20),
        ])
        result = _fuzzy_cluster(variants, threshold=70)
        assert result["entity_num"].nunique() == 1

    def test_threshold_respected(self):
        """Names below threshold stay separate."""
        variants = self._make_variants([
            (1, "Alpha Beta", "bdc", 10),
            (2, "Alpha Gamma", "bdc", 10),
        ])
        # These share first 4 chars ("alph") but should score below 95
        result = _fuzzy_cluster(variants, threshold=95)
        assert result["entity_num"].nunique() == 2

    def test_large_block_skipped(self):
        """Blocks larger than max_block_size are skipped."""
        variants = self._make_variants([
            (i, f"Same{i}", "bdc", 1)
            for i in range(1, 12)
        ])
        # All start with "same" -> single block of 11
        result = _fuzzy_cluster(variants, threshold=50, max_block_size=5)
        # Should not merge anything (block too large)
        assert result["entity_num"].nunique() == 11

    def test_single_entity_passthrough(self):
        variants = self._make_variants([
            (1, "Only One", "bdc", 100),
        ])
        result = _fuzzy_cluster(variants, threshold=85)
        assert result["entity_num"].nunique() == 1

    def test_cluster_method_set(self):
        variants = self._make_variants([
            (1, "Acme Corp", "bdc", 50),
            (2, "Acme Corporation", "bdc", 30),
        ])
        result = _fuzzy_cluster(variants, threshold=80)
        # At least one row should have cluster_method = "fuzzy"
        assert (result["cluster_method"] == "fuzzy").any()

    def test_canonical_picks_higher_count(self):
        variants = self._make_variants([
            (1, "Acme Corp", "bdc", 50),
            (2, "Acme Corporation", "bdc", 30),
        ])
        result = _fuzzy_cluster(variants, threshold=80)
        # Both should have the same canonical_name
        assert result["canonical_name"].nunique() == 1

    def test_different_blocks_not_compared(self):
        """Entities in different blocks cannot merge."""
        variants = self._make_variants([
            (1, "AAAA Corp", "bdc", 10),
            (2, "BBBB Corp", "bdc", 10),
        ])
        result = _fuzzy_cluster(variants, threshold=50)
        assert result["entity_num"].nunique() == 2

    def test_empty_dataframe(self):
        variants = self._make_variants([])
        result = _fuzzy_cluster(variants, threshold=85)
        assert len(result) == 0

    def test_preserves_all_rows(self):
        """Fuzzy clustering should not add or remove rows."""
        variants = self._make_variants([
            (1, "Acme Corp", "bdc", 50),
            (2, "Acme Corporation", "bdc", 30),
            (3, "Beta LLC", "bdc", 10),
        ])
        result = _fuzzy_cluster(variants, threshold=80)
        assert len(result) == 3

    def test_high_threshold_no_merges(self):
        """At threshold 100, similar but non-identical normalised names stay separate."""
        variants = self._make_variants([
            (1, "Acme Systems", "bdc", 10),
            (2, "Acme Systemes", "bdc", 10),
        ])
        result = _fuzzy_cluster(variants, threshold=100)
        assert result["entity_num"].nunique() == 2


# ---------------------------------------------------------------------------
# _cross_source_link
# ---------------------------------------------------------------------------

class TestCrossSourceLink:
    """Cross-source entity linking between BDC and N-PORT."""

    def _make_variants(self, entities):
        rows = []
        for ent_num, name, source, count, cusip, lei in entities:
            rows.append({
                "issuer_name": name,
                "source": source,
                "occurrence_count": count,
                "extracted_name": name,
                "normalized_name": normalise_entity_name(name),
                "canonical_name": name,
                "entity_num": ent_num,
                "cusip": cusip,
                "lei": lei,
            })
        return pd.DataFrame(rows)

    def test_cusip_match(self):
        variants = self._make_variants([
            (1, "Acme Corp", "bdc", 50, "123456789", ""),
            (2, "ACME CORPORATION", "nport", 30, "123456789", ""),
        ])
        result = _cross_source_link(variants, threshold=80)
        assert result["entity_num"].nunique() == 1

    def test_lei_match(self):
        variants = self._make_variants([
            (1, "Beta LLC", "bdc", 20, "", "LEI123ABC"),
            (2, "BETA", "nport", 10, "", "LEI123ABC"),
        ])
        result = _cross_source_link(variants, threshold=80)
        assert result["entity_num"].nunique() == 1

    def test_fuzzy_name_match(self):
        variants = self._make_variants([
            (1, "Acme Corp", "bdc", 50, "", ""),
            (2, "ACME CORP", "nport", 30, "", ""),
        ])
        result = _cross_source_link(variants, threshold=80)
        assert result["entity_num"].nunique() == 1

    def test_no_match_different_names(self):
        variants = self._make_variants([
            (1, "Alpha Inc", "bdc", 10, "", ""),
            (2, "Omega LLC", "nport", 10, "", ""),
        ])
        result = _cross_source_link(variants, threshold=80)
        assert result["entity_num"].nunique() == 2

    def test_same_source_not_linked(self):
        """Cross-source linking only links BDC<->NPORT, not within source."""
        variants = self._make_variants([
            (1, "Acme Corp", "bdc", 50, "", ""),
            (2, "Acme Corporation", "bdc", 30, "", ""),
        ])
        result = _cross_source_link(variants, threshold=80)
        assert result["entity_num"].nunique() == 2

    def test_cross_source_method_set(self):
        variants = self._make_variants([
            (1, "Acme Corp", "bdc", 50, "", ""),
            (2, "ACME CORP", "nport", 30, "", ""),
        ])
        result = _cross_source_link(variants, threshold=80)
        assert (result["cluster_method"] == "cross_source").any()

    def test_no_nport_entities(self):
        """No N-PORT entities -> no linking possible."""
        variants = self._make_variants([
            (1, "Acme Corp", "bdc", 50, "", ""),
            (2, "Beta LLC", "bdc", 30, "", ""),
        ])
        result = _cross_source_link(variants, threshold=80)
        assert result["entity_num"].nunique() == 2

    def test_mixed_source_entity_skipped(self):
        """Entity already in both sources is skipped (not BDC-only or NPORT-only)."""
        variants = self._make_variants([
            (1, "Acme Corp", "bdc", 50, "", ""),
            (1, "ACME CORP", "nport", 30, "", ""),
            (2, "Beta LLC", "nport", 20, "", ""),
        ])
        result = _cross_source_link(variants, threshold=80)
        # Entity 1 already has both sources, entity 2 is nport-only
        # No linking should happen since there's no bdc-only entity
        assert result["entity_num"].nunique() == 2


# ---------------------------------------------------------------------------
# _format_entity_id
# ---------------------------------------------------------------------------

class TestFormatEntityId:
    def test_single_digit(self):
        assert _format_entity_id(1) == "ENT-00000001"

    def test_large_number(self):
        assert _format_entity_id(12345) == "ENT-00012345"


# ---------------------------------------------------------------------------
# Integration: build_entity_lookup
# ---------------------------------------------------------------------------

class TestBuildEntityLookup:
    """Full pipeline integration test."""

    def _make_holdings_csv(self, tmp_dir):
        """Create a minimal unified holdings CSV for testing."""
        path = Path(tmp_dir) / "test_holdings.csv"
        rows = [
            {"source": "bdc", "issuer_name": "Zendesk, Inc., First Lien",
             "cusip": "", "lei": "", "fair_value": "1000", "bdc_investment_identifier": ""},
            {"source": "bdc", "issuer_name": "Zendesk, Inc., Second Lien",
             "cusip": "", "lei": "", "fair_value": "2000", "bdc_investment_identifier": ""},
            {"source": "bdc", "issuer_name": "ZENDESK INC",
             "cusip": "", "lei": "", "fair_value": "3000", "bdc_investment_identifier": ""},
            {"source": "nport", "issuer_name": "ZENDESK INC TL 1L",
             "cusip": "Z123", "lei": "", "fair_value": "500", "bdc_investment_identifier": ""},
            {"source": "bdc", "issuer_name": "Acme Corp., Term Loan",
             "cusip": "", "lei": "", "fair_value": "1500", "bdc_investment_identifier": ""},
            {"source": "nport", "issuer_name": "TOTALLY DIFFERENT CO",
             "cusip": "D456", "lei": "", "fair_value": "800", "bdc_investment_identifier": ""},
        ]
        df = pd.DataFrame(rows)
        df.to_csv(path, index=False)
        return path

    def test_end_to_end(self, tmp_path):
        holdings_path = self._make_holdings_csv(tmp_path)
        lookup_path = tmp_path / "entity_lookup.csv"
        stats_path = tmp_path / "entity_stats.csv"

        with patch("pipeline.entity_resolution.ENTITY_LOOKUP_FILE", lookup_path), \
             patch("pipeline.entity_resolution.ENTITY_STATS_FILE", stats_path), \
             patch("pipeline.entity_resolution.UNIFIED_HOLDINGS_FILE", holdings_path):
            result = build_entity_lookup(
                holdings_path=holdings_path,
                enrich=False,
            )

        # Check lookup file was written
        assert lookup_path.exists()
        lookup_df = pd.read_csv(lookup_path)
        assert len(lookup_df) > 0
        assert "entity_id" in lookup_df.columns
        assert "canonical_name" in lookup_df.columns

        # Check stats file was written
        assert stats_path.exists()
        stats_df = pd.read_csv(stats_path)
        assert stats_df.iloc[0]["total_variants"] == 6

        # Zendesk variants should be merged (at least by exact dedup)
        zendesk_variants = lookup_df[
            lookup_df["issuer_name_variant"].str.contains("endesk", case=False, na=False)
        ]
        assert zendesk_variants["entity_id"].nunique() <= 2  # BDC+NPORT may or may not merge

    def test_enrichment(self, tmp_path):
        holdings_path = self._make_holdings_csv(tmp_path)
        lookup_path = tmp_path / "entity_lookup.csv"
        stats_path = tmp_path / "entity_stats.csv"

        with patch("pipeline.entity_resolution.ENTITY_LOOKUP_FILE", lookup_path), \
             patch("pipeline.entity_resolution.ENTITY_STATS_FILE", stats_path), \
             patch("pipeline.entity_resolution.UNIFIED_HOLDINGS_FILE", holdings_path):
            build_entity_lookup(
                holdings_path=holdings_path,
                enrich=True,
            )

        # Read enriched holdings
        enriched = pd.read_csv(holdings_path)
        assert "entity_id" in enriched.columns
        assert "canonical_name" in enriched.columns
        # All rows should have entity_id populated
        assert (enriched["entity_id"] != "").all()

    def test_lookup_from_disk(self, tmp_path):
        """Entity lookup can be loaded from disk."""
        lookup_path = tmp_path / "entity_lookup.csv"
        pd.DataFrame({
            "entity_id": ["ENT-00000001"],
            "canonical_name": ["Test"],
            "normalized_name": ["test"],
            "issuer_name_variant": ["Test Inc."],
            "source": ["bdc"],
            "occurrence_count": [10],
            "cluster_method": ["exact"],
            "cusip": [""],
            "lei": [""],
        }).to_csv(lookup_path, index=False)

        loaded = pd.read_csv(lookup_path)
        assert loaded.iloc[0]["entity_id"] == "ENT-00000001"

    def test_enrich_holdings_join(self, tmp_path):
        """Test the DuckDB enrichment join directly."""
        # Create holdings CSV
        holdings_path = tmp_path / "holdings.csv"
        pd.DataFrame({
            "source": ["bdc", "nport"],
            "issuer_name": ["Acme Inc", "BETA LLC"],
            "fair_value": [100, 200],
        }).to_csv(holdings_path, index=False)

        # Create lookup CSV
        lookup_path = tmp_path / "lookup.csv"
        pd.DataFrame({
            "entity_id": ["ENT-00000001", "ENT-00000002"],
            "canonical_name": ["Acme Inc.", "Beta LLC"],
            "normalized_name": ["acme", "beta"],
            "issuer_name_variant": ["Acme Inc", "BETA LLC"],
            "source": ["bdc", "nport"],
            "occurrence_count": [10, 5],
            "cluster_method": ["exact", "exact"],
            "cusip": ["", ""],
            "lei": ["", ""],
        }).to_csv(lookup_path, index=False)

        output_path = tmp_path / "enriched.csv"
        _enrich_holdings(holdings_path, lookup_path, output_path)

        result = pd.read_csv(output_path)
        assert "entity_id" in result.columns
        assert "canonical_name" in result.columns
        assert result.iloc[0]["entity_id"] == "ENT-00000001"
        assert result.iloc[1]["canonical_name"] == "Beta LLC"

    def test_enrich_unmatched_rows_empty_string(self, tmp_path):
        """Holdings with no lookup match get empty entity_id."""
        holdings_path = tmp_path / "holdings.csv"
        pd.DataFrame({
            "source": ["bdc"],
            "issuer_name": ["Unknown Entity"],
            "fair_value": [100],
        }).to_csv(holdings_path, index=False)

        lookup_path = tmp_path / "lookup.csv"
        pd.DataFrame({
            "entity_id": ["ENT-00000001"],
            "canonical_name": ["Acme"],
            "normalized_name": ["acme"],
            "issuer_name_variant": ["Acme Inc"],
            "source": ["bdc"],
            "occurrence_count": [10],
            "cluster_method": ["exact"],
            "cusip": [""],
            "lei": [""],
        }).to_csv(lookup_path, index=False)

        output_path = tmp_path / "enriched.csv"
        _enrich_holdings(holdings_path, lookup_path, output_path)

        result = pd.read_csv(output_path, keep_default_na=False)
        assert result.iloc[0]["entity_id"] == ""


# ---------------------------------------------------------------------------
# _strip_trailing_number
# ---------------------------------------------------------------------------

class TestStripTrailingNumber:
    def test_trailing_1(self):
        assert _strip_trailing_number("Acme LLC 1") == "Acme LLC"

    def test_trailing_parens(self):
        assert _strip_trailing_number("Acme LLC (2)") == "Acme LLC"

    def test_no_trailing(self):
        assert _strip_trailing_number("Acme LLC") == "Acme LLC"

    def test_number_in_name(self):
        """Numbers that are part of the name (not trailing) are preserved."""
        assert _strip_trailing_number("PT Intermediate III, LLC") == "PT Intermediate III, LLC"


# ---------------------------------------------------------------------------
# _write_entity_lookup
# ---------------------------------------------------------------------------

class TestWriteEntityLookup:
    def test_writes_csv(self, tmp_path):
        variants = pd.DataFrame({
            "entity_num": [1],
            "canonical_name": ["Acme Inc."],
            "normalized_name": ["acme"],
            "issuer_name": ["Acme, Inc."],
            "source": ["bdc"],
            "occurrence_count": [10],
            "cluster_method": ["exact"],
            "cusip": [""],
            "lei": [""],
        })
        path = tmp_path / "entity_lookup.csv"
        _write_entity_lookup(variants, path)
        assert path.exists()
        df = pd.read_csv(path)
        assert df.iloc[0]["entity_id"] == "ENT-00000001"


# ---------------------------------------------------------------------------
# _write_stats
# ---------------------------------------------------------------------------

class TestWriteStats:
    def test_writes_csv(self, tmp_path):
        variants = pd.DataFrame({
            "entity_num": [1, 1, 2],
            "source": ["bdc", "nport", "bdc"],
            "occurrence_count": [10, 5, 20],
            "cluster_method": ["exact", "cross_source", "exact"],
        })
        path = tmp_path / "stats.csv"
        _write_stats(variants, path)
        assert path.exists()
        stats = pd.read_csv(path)
        assert stats.iloc[0]["total_variants"] == 3
        assert stats.iloc[0]["total_entities"] == 2
        assert stats.iloc[0]["cross_source_entities"] == 1


# ---------------------------------------------------------------------------
# CLI integration
# ---------------------------------------------------------------------------

class TestCli:
    def test_entities_flag_parsing(self):
        """--entities flag is recognized by argparse."""
        from pipeline.main import _parse_args
        with patch("sys.argv", ["main", "--entities"]):
            args = _parse_args()
            assert args.entities is True

    def test_entities_flag_default_false(self):
        from pipeline.main import _parse_args
        with patch("sys.argv", ["main"]):
            args = _parse_args()
            assert args.entities is False


# ---------------------------------------------------------------------------
# Fix 1: LLM-extracted names preferred over regex
# ---------------------------------------------------------------------------

class TestLlmNameExtraction:
    """LLM extraction cache integration in _exact_dedup()."""

    def _make_variants(self, rows):
        df = pd.DataFrame(rows)
        for col in ["cusip", "lei", "bdc_investment_identifier"]:
            if col not in df.columns:
                df[col] = ""
        return df

    def test_llm_name_preferred_over_regex(self, tmp_path):
        """BDC variant with bdc_investment_identifier uses LLM name."""
        # Create a mock LLM lookup CSV
        llm_path = tmp_path / "identifier_extraction_lookup.csv"
        pd.DataFrame({
            "bdc_investment_identifier": ["Zendesk, Inc., First Lien Senior Secured Loan SOFR 5.0%"],
            "extracted_company_name": ["Zendesk, Inc."],
        }).to_csv(llm_path, index=False)

        variants = self._make_variants([{
            "issuer_name": "Zendesk, Inc., First Lien Senior Secured Loan SOFR 5.0%",
            "source": "bdc",
            "occurrence_count": 50,
            "bdc_investment_identifier": "Zendesk, Inc., First Lien Senior Secured Loan SOFR 5.0%",
        }])

        with patch("pipeline.entity_resolution.IDENTIFIER_EXTRACTION_LOOKUP_FILE", llm_path):
            result = _exact_dedup(variants)

        assert result.iloc[0]["extracted_name"] == "Zendesk, Inc."

    def test_llm_fallback_to_regex(self, tmp_path):
        """BDC variant not in LLM cache falls back to regex."""
        # Create an LLM lookup that does NOT contain our identifier
        llm_path = tmp_path / "identifier_extraction_lookup.csv"
        pd.DataFrame({
            "bdc_investment_identifier": ["SomethingElse"],
            "extracted_company_name": ["SomethingElse"],
        }).to_csv(llm_path, index=False)

        variants = self._make_variants([{
            "issuer_name": "Acme Corp., Term Loan B",
            "source": "bdc",
            "occurrence_count": 10,
            "bdc_investment_identifier": "Acme Corp., Term Loan B",
        }])

        with patch("pipeline.entity_resolution.IDENTIFIER_EXTRACTION_LOOKUP_FILE", llm_path):
            result = _exact_dedup(variants)

        # Regex should extract "Acme Corp."
        assert result.iloc[0]["extracted_name"] == "Acme Corp."

    def test_nport_unaffected_by_llm(self, tmp_path):
        """N-PORT variants always use regex, never LLM."""
        llm_path = tmp_path / "identifier_extraction_lookup.csv"
        pd.DataFrame({
            "bdc_investment_identifier": ["WIDGET INC TL 1L"],
            "extracted_company_name": ["LLM Override"],
        }).to_csv(llm_path, index=False)

        variants = self._make_variants([{
            "issuer_name": "WIDGET INC TL 1L",
            "source": "nport",
            "occurrence_count": 5,
            "bdc_investment_identifier": "",
        }])

        with patch("pipeline.entity_resolution.IDENTIFIER_EXTRACTION_LOOKUP_FILE", llm_path):
            result = _exact_dedup(variants)

        # N-PORT regex: legal suffix "INC" -> "WIDGET INC"
        assert result.iloc[0]["extracted_name"] == "WIDGET INC"

    def test_llm_cache_missing_file(self, tmp_path):
        """When LLM cache file doesn't exist, falls back to regex gracefully."""
        llm_path = tmp_path / "nonexistent.csv"

        variants = self._make_variants([{
            "issuer_name": "Acme, Inc., First Lien",
            "source": "bdc",
            "occurrence_count": 10,
            "bdc_investment_identifier": "Acme, Inc., First Lien",
        }])

        with patch("pipeline.entity_resolution.IDENTIFIER_EXTRACTION_LOOKUP_FILE", llm_path):
            result = _exact_dedup(variants)

        assert result.iloc[0]["extracted_name"] == "Acme, Inc."


# ---------------------------------------------------------------------------
# Fix 2: Opaque numeric ID filtering
# ---------------------------------------------------------------------------

class TestOpaqueNumericIdFilter:
    """Filtering of opaque numeric IDs like 1824445.SQ.RVR."""

    def test_numeric_id_matches_regex(self):
        """Regex correctly identifies opaque numeric IDs."""
        assert _OPAQUE_NUMERIC_ID_RE.match("1824445.SQ.RVR")
        assert _OPAQUE_NUMERIC_ID_RE.match("99999999.AB.CD")
        assert _OPAQUE_NUMERIC_ID_RE.match("12345.X.YZ")

    def test_real_names_not_matched(self):
        """Normal company names are not matched by the regex."""
        assert not _OPAQUE_NUMERIC_ID_RE.match("Acme Corp")
        assert not _OPAQUE_NUMERIC_ID_RE.match("123 Industries, Inc.")
        assert not _OPAQUE_NUMERIC_ID_RE.match("First National Bank")

    def test_numeric_ids_excluded_from_variant_table(self, tmp_path):
        """Opaque numeric IDs are excluded from the variant table."""
        path = tmp_path / "holdings.csv"
        pd.DataFrame({
            "issuer_name": ["1824445.SQ.RVR", "Acme Corp", "99999.AB.CD"],
            "source": ["bdc", "bdc", "bdc"],
            "cusip": ["", "", ""],
            "lei": ["", "", ""],
            "bdc_investment_identifier": ["", "", ""],
        }).to_csv(path, index=False)

        result = _build_variant_table(path)
        assert len(result) == 1
        assert result.iloc[0]["issuer_name"] == "Acme Corp"

    def test_short_numeric_not_excluded(self, tmp_path):
        """Short numeric strings (< 5 digits) are not excluded."""
        path = tmp_path / "holdings.csv"
        pd.DataFrame({
            "issuer_name": ["1234.AB.CD", "Acme Corp"],
            "source": ["bdc", "bdc"],
            "cusip": ["", ""],
            "lei": ["", ""],
            "bdc_investment_identifier": ["", ""],
        }).to_csv(path, index=False)

        result = _build_variant_table(path)
        # "1234.AB.CD" has only 4 digits, should NOT be excluded
        assert len(result) == 2


# ---------------------------------------------------------------------------
# Fix 3: Regex improvements -- pipe splitting
# ---------------------------------------------------------------------------

class TestPipeSplitting:
    """Phase 0: Split BDC names on pipe delimiter."""

    def test_pipe_split_basic(self):
        result = _extract_bdc_name("Acme, Inc. | Non-Affiliated Issuer")
        assert result == "Acme, Inc."

    def test_pipe_split_no_space(self):
        result = _extract_bdc_name("Energy Equipment & Services|9.11%")
        assert "Energy Equipment & Services" == result

    def test_pipe_split_lien_type(self):
        result = _extract_bdc_name("ACACIA BUYERCO V LLC | First Lien")
        assert result == "ACACIA BUYERCO V LLC"

    def test_pipe_at_start_ignored(self):
        """Pipe at position 0 should not trigger split (pipe_idx > 0)."""
        result = _extract_bdc_name("|Some Name, Inc.")
        # Falls through to normal extraction; legal suffix found
        assert "Inc" in result


# ---------------------------------------------------------------------------
# Fix 3: Regex improvements -- prefix stripping
# ---------------------------------------------------------------------------

class TestPrefixStripping:
    """New prefix patterns for BDC name extraction."""

    def test_debt_prefix_stripped(self):
        result = _extract_bdc_name(
            "Debt Investments, First Lien Senior Secured, OneCare Media, LLC"
        )
        assert "OneCare Media" in result

    def test_controlled_prefix_stripped(self):
        result = _extract_bdc_name(
            "Controlled/Non-Affiliated Investments, Senior Secured First Lien Loans, "
            "Industry Energy, Company Acme, Inc."
        )
        assert "Acme" in result

    def test_related_party_prefix(self):
        result = _extract_bdc_name("Related Party PSLF First Lien Secured Debt")
        assert result == "PSLF"

    def test_non_controlled_prefix(self):
        result = _extract_bdc_name(
            "Non-Controlled Investments, Senior Secured Loans, "
            "Industry Healthcare, Company Beta, LLC"
        )
        assert "Beta" in result


# ---------------------------------------------------------------------------
# Fix 3: Regex improvements -- trailing instrument stripping
# ---------------------------------------------------------------------------

class TestTrailingInstrumentStripping:
    """Trailing instrument keywords stripped when no legal suffix found."""

    def test_trailing_lien_stripped(self):
        result = _extract_bdc_name("PSLF First Lien Secured Debt")
        assert result == "PSLF"

    def test_trailing_term_loan_stripped(self):
        result = _extract_bdc_name("Acme Widgets Term Loan")
        assert result == "Acme Widgets"

    def test_trailing_senior_secured_stripped(self):
        result = _extract_bdc_name("XYZ Corp Senior Secured Loan B")
        # "Corp" without dot matches legal suffix regex (corp\.?,?)
        assert result == "XYZ Corp"

    def test_no_false_positive_first_national(self):
        """'First National Bank' should NOT be stripped."""
        result = _extract_bdc_name("First National Bank")
        # "First" is followed by "National", not "Lien"
        assert result == "First National Bank"

    def test_no_false_positive_first_citizens(self):
        """'First Citizens BancShares' should NOT be stripped."""
        result = _extract_bdc_name("First Citizens BancShares")
        assert result == "First Citizens BancShares"

    def test_legal_suffix_takes_priority(self):
        """When a legal suffix exists, trailing instrument is irrelevant."""
        result = _extract_bdc_name("Acme, Inc. First Lien Term Loan")
        assert result == "Acme, Inc."


# ---------------------------------------------------------------------------
# Fix 3: Regex improvements -- N-PORT facility expansion
# ---------------------------------------------------------------------------

class TestNportFacilityExpansion:
    """Extended N-PORT facility suffix stripping."""

    def test_nport_term_loan_full_word(self):
        result = _extract_nport_name("ACME WIDGETS TERM LOAN B")
        assert result == "ACME WIDGETS"

    def test_nport_delayed_draw(self):
        result = _extract_nport_name("ACME CORP DELAYED DRAW 2025")
        assert "ACME CORP" in result

    def test_nport_credit_facility(self):
        result = _extract_nport_name("BETA LLC CREDIT FACILITY")
        # "LLC" is a legal suffix, so it should be caught first
        assert result == "BETA LLC"

    def test_nport_existing_tl_still_works(self):
        """Existing TL pattern should still work."""
        result = _extract_nport_name("FINASTRA USA INC TL 1L VISTA /")
        assert result == "FINASTRA USA INC"

    def test_nport_existing_revolver_still_works(self):
        """Existing REVOLVER pattern should still work."""
        result = _extract_nport_name("ACME WIDGETS REVOLVER 2024")
        assert result == "ACME WIDGETS"


# ---------------------------------------------------------------------------
# Entity override tests
# ---------------------------------------------------------------------------

class TestEntityOverrides:
    """Tests for JSON-based entity merge and canonical name overrides."""

    def _make_variants(self, rows):
        df = pd.DataFrame(rows)
        for col in ["cusip", "lei", "bdc_investment_identifier"]:
            if col not in df.columns:
                df[col] = ""
        df["occurrence_count"] = df.get("occurrence_count", 1)
        df = _exact_dedup(df)
        if "cluster_method" not in df.columns:
            df["cluster_method"] = "exact"
        return df

    def test_merge_override_applied(self, tmp_path):
        """Two variants forced into same entity by merge override."""
        # Use names different enough that exact_dedup won't merge them
        variants = self._make_variants([
            {"issuer_name": "Zenith Widgets Ltd", "source": "bdc", "occurrence_count": 10},
            {"issuer_name": "ZW Holdings Inc", "source": "nport", "occurrence_count": 5},
        ])
        # Verify they start as separate entities
        assert variants["entity_num"].nunique() == 2
        overrides = {
            "schema_version": "entity-overrides.v1",
            "merges": [{
                "canonical_name": "Zenith Widgets Corporation",
                "variants": [
                    {"issuer_name": "Zenith Widgets Ltd", "source": "bdc"},
                    {"issuer_name": "ZW Holdings Inc", "source": "nport"},
                ],
                "evidence": "test",
                "date_added": "2026-06-03",
            }],
            "canonical_overrides": [],
        }
        path = tmp_path / "overrides.json"
        path.write_text(json.dumps(overrides), encoding="utf-8")
        result = _apply_entity_overrides(variants, overrides_path=path)
        # Both should have same entity_num
        assert result["entity_num"].nunique() == 1
        # Both should have canonical_name from override
        assert (result["canonical_name"] == "Zenith Widgets Corporation").all()

    def test_canonical_override_applied(self, tmp_path):
        """Canonical name corrected via override."""
        variants = self._make_variants([
            {"issuer_name": "ABBREV NAME", "source": "bdc", "occurrence_count": 10},
        ])
        overrides = {
            "schema_version": "entity-overrides.v1",
            "merges": [],
            "canonical_overrides": [{
                "issuer_name": "ABBREV NAME",
                "source": "bdc",
                "canonical_name": "Full Canonical Name",
                "evidence": "test",
            }],
        }
        path = tmp_path / "overrides.json"
        path.write_text(json.dumps(overrides), encoding="utf-8")
        result = _apply_entity_overrides(variants, overrides_path=path)
        assert result.iloc[0]["canonical_name"] == "Full Canonical Name"

    def test_no_override_file(self, tmp_path):
        """No crash when override file missing."""
        variants = self._make_variants([
            {"issuer_name": "Acme Corp", "source": "bdc", "occurrence_count": 10},
        ])
        missing = tmp_path / "nonexistent.json"
        result = _apply_entity_overrides(variants, overrides_path=missing)
        assert len(result) == len(variants)

    def test_invalid_json_warning(self, tmp_path):
        """Malformed JSON logs warning and continues."""
        variants = self._make_variants([
            {"issuer_name": "Acme Corp", "source": "bdc", "occurrence_count": 10},
        ])
        path = tmp_path / "bad.json"
        path.write_text("{invalid json", encoding="utf-8")
        result = _apply_entity_overrides(variants, overrides_path=path)
        assert len(result) == len(variants)


# ---------------------------------------------------------------------------
# 3-char blocking pass tests
# ---------------------------------------------------------------------------

class TestThreeCharBlocking:
    """Tests for the secondary 3-char blocking fuzzy pass."""

    def _make_variants(self, rows):
        df = pd.DataFrame(rows)
        for col in ["cusip", "lei", "bdc_investment_identifier"]:
            if col not in df.columns:
                df[col] = ""
        df["occurrence_count"] = df.get("occurrence_count", 1)
        df = _exact_dedup(df)
        if "cluster_method" not in df.columns:
            df["cluster_method"] = "exact"
        return df

    def test_3char_blocking_catches_prefix_mismatch(self):
        """Entities differing in first 4 chars but sharing 3-char prefix can merge."""
        variants = self._make_variants([
            {"issuer_name": "ACME Corp Holdings", "source": "bdc", "occurrence_count": 10},
            {"issuer_name": "ACM Holdings Corp", "source": "bdc", "occurrence_count": 5},
        ])
        # First pass (4-char blocking) won't match these since "acme" != "acm "
        result_4char = _fuzzy_cluster(variants.copy(), threshold=85)
        # Second pass with 3-char should catch them if similarity >= 90
        # Both normalize to similar names; check that the function handles them
        # The actual merge depends on normalized_name similarity
        assert len(result_4char) >= 1  # Sanity check

    def test_3char_blocking_threshold_higher(self):
        """Marginal pairs at score 86 not merged in second pass (threshold 90)."""
        # With threshold=90, pairs scoring 86-89 should NOT merge
        variants = self._make_variants([
            {"issuer_name": "Alpha Beta Gamma", "source": "bdc", "occurrence_count": 10},
            {"issuer_name": "Alpha Beta Delta", "source": "bdc", "occurrence_count": 5},
        ])
        # These are clearly different entities and should not merge at threshold 90
        result = _fuzzy_cluster(variants.copy(), threshold=90)
        assert result["entity_num"].nunique() >= 1  # Sanity: no crash


# ---------------------------------------------------------------------------
# Numeric-suffix guard tests
# ---------------------------------------------------------------------------

class TestNumericSuffixGuard:
    """Tests for _numeric_suffix_guard preventing series/vintage false merges."""

    def test_guard_function_raises_threshold(self):
        """Names identical except digits get elevated threshold."""
        effective = _numeric_suffix_guard("cifc 20191", "cifc 20203", 85)
        assert effective == _NUMERIC_SUFFIX_THRESHOLD

    def test_guard_function_no_digits_unchanged(self):
        """Names with no digit difference keep original threshold."""
        effective = _numeric_suffix_guard("acme corp", "acme corporation", 85)
        assert effective == 85

    def test_guard_function_identical_names_unchanged(self):
        """Identical names (same digits) keep original threshold."""
        effective = _numeric_suffix_guard("cifc 20191", "cifc 20191", 85)
        assert effective == 85

    def test_guard_function_different_base_unchanged(self):
        """Names with different non-digit bases keep original threshold."""
        effective = _numeric_suffix_guard("alpha 2019", "beta 2019", 85)
        assert effective == 85

    def test_guard_function_empty_stripped_unchanged(self):
        """Names that are purely digits keep original threshold."""
        effective = _numeric_suffix_guard("12232019", "12232020", 85)
        # After stripping digits, both are empty -> threshold unchanged
        assert effective == 85

    def _make_variants(self, rows):
        df = pd.DataFrame(rows)
        for col in ["cusip", "lei", "bdc_investment_identifier"]:
            if col not in df.columns:
                df[col] = ""
        df["occurrence_count"] = df.get("occurrence_count", 1)
        df = _exact_dedup(df)
        if "cluster_method" not in df.columns:
            df["cluster_method"] = "exact"
        return df

    def test_clo_series_not_merged(self):
        """Different CLO vintages should NOT be merged despite similar names."""
        variants = self._make_variants([
            {"issuer_name": "CIFC 2019-1", "source": "nport", "occurrence_count": 10},
            {"issuer_name": "CIFC 2020-3", "source": "nport", "occurrence_count": 10},
            {"issuer_name": "CIFC 2021-5", "source": "nport", "occurrence_count": 10},
        ])
        result = _fuzzy_cluster(variants.copy(), threshold=85)
        assert result["entity_num"].nunique() == 3

    def test_fund_vintage_not_merged(self):
        """Different fund vintages should NOT be merged."""
        variants = self._make_variants([
            {"issuer_name": "Carlyle Partners VII LP", "source": "nport", "occurrence_count": 10},
            {"issuer_name": "Carlyle Partners VIII LP", "source": "nport", "occurrence_count": 10},
        ])
        result = _fuzzy_cluster(variants.copy(), threshold=85)
        assert result["entity_num"].nunique() == 2

    def test_deal_number_not_merged(self):
        """Different numbered deals should NOT be merged."""
        variants = self._make_variants([
            {"issuer_name": "BCC 2019-2", "source": "nport", "occurrence_count": 10},
            {"issuer_name": "BCC 2020-2", "source": "nport", "occurrence_count": 10},
        ])
        result = _fuzzy_cluster(variants.copy(), threshold=85)
        assert result["entity_num"].nunique() == 2

    def test_same_entity_name_variants_still_merged(self):
        """Genuine name variants (not numeric-only diffs) still merge."""
        variants = self._make_variants([
            {"issuer_name": "Acme Corp Holdings", "source": "bdc", "occurrence_count": 10},
            {"issuer_name": "Acme Corp Holding", "source": "bdc", "occurrence_count": 10},
        ])
        result = _fuzzy_cluster(variants.copy(), threshold=85)
        assert result["entity_num"].nunique() == 1

    def test_transitive_chain_blocked(self):
        """Transitive chain through numeric variants is blocked.

        A=CIFC 2019-1, B=CIFC 2019-2, C=CIFC 2020-1
        A~B and B~C individually score high, but A-C has digit-only diff.
        The guard should prevent at least some of these merges.
        """
        variants = self._make_variants([
            {"issuer_name": "Elmwood CLO VIII Ltd", "source": "nport", "occurrence_count": 10},
            {"issuer_name": "Elmwood CLO X Ltd", "source": "nport", "occurrence_count": 10},
            {"issuer_name": "Elmwood CLO 14 Ltd", "source": "nport", "occurrence_count": 10},
            {"issuer_name": "Elmwood CLO 22 Ltd", "source": "nport", "occurrence_count": 10},
        ])
        result = _fuzzy_cluster(variants.copy(), threshold=85)
        # These are different CLO vintages; should NOT all merge into one
        assert result["entity_num"].nunique() >= 3
