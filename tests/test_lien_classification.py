"""Tests for pipeline/lien_classification.py."""

import pandas as pd
import pytest

import duckdb

from pipeline.lien_classification import (
    _FIRST_LIEN_KEYWORDS,
    _SECOND_LIEN_KEYWORDS,
    _UNSECURED_KEYWORDS,
    _normalize_instrument_pattern,
    _sql_classify_lien,
    _load_lien_cache,
    _save_lien_cache,
    _apply_lien_cache,
    classify_lien,
)


@pytest.fixture(autouse=True)
def _redirect_lien_outputs(monkeypatch, tmp_path):
    # lien_classification.py imports LIEN_CACHE_FILE lazily from pipeline.config
    # so we only need to patch the config module attribute.
    monkeypatch.setattr(
        "pipeline.config.LIEN_CACHE_FILE",
        tmp_path / "lien_cache.csv",
    )


# ---------------------------------------------------------------------------
# classify_lien (pure Python)
# ---------------------------------------------------------------------------

class TestClassifyLien:
    """Test the pure-Python classify_lien function."""

    # --- Second Lien keywords ---
    def test_second_lien(self):
        assert classify_lien("Acme Corp Second Lien Term Loan", None) == "Second Lien"

    def test_2nd_lien(self):
        assert classify_lien("Acme Corp 2nd Lien Term Loan", None) == "Second Lien"

    def test_junior_lien(self):
        assert classify_lien("Acme Corp Junior Lien", None) == "Second Lien"

    def test_junior_secured(self):
        assert classify_lien("Acme Corp Junior Secured Term Loan", None) == "Second Lien"

    # --- Unsecured keywords ---
    def test_unsecured(self):
        assert classify_lien("Acme Corp Unsecured Note", None) == "Unsecured"

    def test_subordinated(self):
        assert classify_lien("Acme Corp Subordinated Debt", None) == "Unsecured"

    def test_subordinate(self):
        assert classify_lien("Acme Corp Subordinate Loan", None) == "Unsecured"

    def test_mezzanine(self):
        assert classify_lien("Acme Corp Mezzanine Loan", None) == "Unsecured"

    # --- First Lien keywords ---
    def test_first_lien(self):
        assert classify_lien("Acme Corp First Lien Term Loan", None) == "First Lien"

    def test_1st_lien(self):
        assert classify_lien("Acme Corp 1st Lien Term Loan", None) == "First Lien"

    def test_senior_secured(self):
        assert classify_lien("Acme Corp Senior Secured Term Loan", None) == "First Lien"

    def test_unitranche(self):
        assert classify_lien("Acme Corp Unitranche", None) == "First Lien"

    def test_super_senior(self):
        assert classify_lien("Acme Corp Super Senior Loan", None) == "First Lien"

    def test_last_out(self):
        assert classify_lien("Acme Corp Last Out Term Loan", None) == "First Lien"

    def test_first_out(self):
        assert classify_lien("Acme Corp First Out Term Loan", None) == "First Lien"

    def test_senior_lien(self):
        assert classify_lien("Acme Corp Senior Lien Loan", None) == "First Lien"

    # --- Lever 2: hyphenated + product-name variants ---
    def test_first_lien_hyphenated(self):
        # Sixth Street writes "First-lien loan (...)"
        assert classify_lien("First-lien loan", None) == "First Lien"

    def test_second_lien_hyphenated(self):
        assert classify_lien("Second-lien term loan", None) == "Second Lien"

    def test_one_stop_via_identifier(self):
        # Golub tags first-lien/unitranche as "One stop" in the identifier
        assert classify_lien(
            "ABC Legal Holdings, LLC", None,
            bdc_investment_identifier="ABC Legal Holdings, LLC, One stop 1",
        ) == "First Lien"

    def test_one_stop_hyphen(self):
        assert classify_lien("Acme Corp One-Stop Loan", None) == "First Lien"

    def test_one_stop_does_not_override_second_lien(self):
        # priority guard: an explicit second-lien marker still wins
        assert classify_lien("Acme One Stop Second Lien", None) == "Second Lien"

    def test_one_stop_only_for_direct_lending(self):
        # false-positive guard: non-DL positions are never lien-classified
        assert classify_lien(
            "One Stop Shop Holdings", None,
            index_classification="DIRECT_EQUITY",
        ) is None

    # --- Priority order ---
    def test_second_lien_beats_first_lien(self):
        """Second lien checked before first lien."""
        assert classify_lien(
            "Acme Corp Senior Secured Second Lien Term Loan", None
        ) == "Second Lien"

    def test_second_lien_beats_unsecured(self):
        """Second lien checked before unsecured."""
        assert classify_lien(
            "Acme Corp Second Lien Subordinated Note", None
        ) == "Second Lien"

    def test_unsecured_beats_first_lien(self):
        """Unsecured checked before first lien."""
        assert classify_lien(
            "Acme Corp Unsecured Senior Secured Note", None
        ) == "Unsecured"

    # --- Case insensitivity ---
    def test_case_insensitive_upper(self):
        assert classify_lien("ACME CORP FIRST LIEN", None) == "First Lien"

    def test_case_insensitive_mixed(self):
        assert classify_lien("Acme Corp SECOND LIEN", None) == "Second Lien"

    def test_case_insensitive_lower(self):
        assert classify_lien("acme corp mezzanine loan", None) == "Unsecured"

    # --- Combined text (keyword in instrument_description only) ---
    def test_keyword_in_instrument_only(self):
        assert classify_lien("Acme Corp", "First Lien Term Loan") == "First Lien"

    def test_second_lien_in_instrument_only(self):
        assert classify_lien("Acme Corp", "Second Lien Term Loan") == "Second Lien"

    def test_unsecured_in_instrument_only(self):
        assert classify_lien("Acme Corp", "Unsecured Note") == "Unsecured"

    def test_keyword_in_both(self):
        """When both fields have keywords, first match in combined text wins."""
        result = classify_lien(
            "Acme Corp First Lien",
            "Second Lien Term Loan"
        )
        # "second lien" is checked first in priority order, appears in instrument
        assert result == "Second Lien"

    # --- No match ---
    def test_no_keyword(self):
        assert classify_lien("Acme Corp", "Term Loan") is None

    def test_empty_strings(self):
        assert classify_lien("", "") is None

    def test_none_inputs(self):
        assert classify_lien(None, None) is None

    # --- Non-DIRECT_LENDING gate ---
    def test_non_direct_lending_returns_none(self):
        assert classify_lien(
            "Acme Corp First Lien Term Loan", None,
            index_classification="COMMON_EQUITY"
        ) is None

    def test_fund_returns_none(self):
        assert classify_lien(
            "Senior Secured Fund", None,
            index_classification="PRIVATE_CREDIT_FUND"
        ) is None

    def test_unclassified_returns_none(self):
        assert classify_lien(
            "First Lien Acme", None,
            index_classification="UNCLASSIFIED"
        ) is None

    # --- bdc_investment_identifier fallback ---
    def test_bid_first_lien_hierarchy(self):
        """Goldman-style long-form identifier with lien in hierarchy."""
        assert classify_lien(
            "Curriculum Associates, LLC", "Debt Investments",
            bdc_investment_identifier=(
                "Investment Debt Investments - 137.5% United States - 129.7% "
                "1st Lien/Senior Secured Debt - 125.7% Curriculum Associates"
            ),
        ) == "First Lien"

    def test_bid_second_lien_hierarchy(self):
        assert classify_lien(
            "Magenta Buyer LLC", "Debt Investments",
            bdc_investment_identifier=(
                "Non-control Investments Magenta Buyer LLC "
                "Information Technology Services Second Lien Debt"
            ),
        ) == "Second Lien"

    def test_bid_unsecured(self):
        assert classify_lien(
            "Acme Corp", "Debt Investments",
            bdc_investment_identifier="Investment Unsecured Debt Acme Corp",
        ) == "Unsecured"

    def test_bid_no_keywords_returns_none(self):
        assert classify_lien(
            "Guidehouse, Inc.", "",
            bdc_investment_identifier="Guidehouse, Inc.",
        ) is None

    def test_bid_only_source(self):
        """Keywords only in bdc_investment_identifier, nowhere else."""
        assert classify_lien(
            "Acme Corp", "Term Loan",
            bdc_investment_identifier="1st Lien/Senior Secured Debt Acme Corp",
        ) == "First Lien"


# ---------------------------------------------------------------------------
# _sql_classify_lien (DuckDB SQL)
# ---------------------------------------------------------------------------

class TestSqlClassifyLien:
    """Test the SQL CASE WHEN generated by _sql_classify_lien."""

    def _classify_via_sql(self, issuer_name, instrument_desc,
                          bdc_investment_identifier=""):
        """Run the lien SQL against a single row."""
        lien_sql = _sql_classify_lien()
        con = duckdb.connect()
        result = con.execute(f"""
            SELECT {lien_sql} AS lien_position
            FROM (
                SELECT
                    COALESCE(lower(trim('{issuer_name}')), '') || ' ' ||
                    COALESCE(lower(trim('{instrument_desc}')), '') AS _combined_fund_text,
                    '{bdc_investment_identifier}' AS bdc_investment_identifier
            )
        """).fetchone()
        con.close()
        return result[0] if result else None

    def test_first_lien_sql(self):
        assert self._classify_via_sql("Acme Corp First Lien Term Loan", "") == "First Lien"

    def test_second_lien_sql(self):
        assert self._classify_via_sql("Acme Corp Second Lien", "") == "Second Lien"

    def test_unsecured_sql(self):
        assert self._classify_via_sql("Acme Corp Unsecured Note", "") == "Unsecured"

    def test_mezzanine_sql(self):
        assert self._classify_via_sql("", "Mezzanine Loan") == "Unsecured"

    def test_unitranche_sql(self):
        assert self._classify_via_sql("Acme Unitranche", "") == "First Lien"

    def test_no_match_sql(self):
        assert self._classify_via_sql("Acme Corp", "Term Loan") is None

    def test_priority_second_over_first_sql(self):
        result = self._classify_via_sql("Senior Secured Second Lien", "")
        assert result == "Second Lien"

    def test_priority_unsecured_over_first_sql(self):
        result = self._classify_via_sql("Unsecured Senior Secured", "")
        assert result == "Unsecured"

    def test_instrument_desc_keyword_sql(self):
        result = self._classify_via_sql("Acme Corp", "First Lien Term Loan")
        assert result == "First Lien"

    def test_subordinated_sql(self):
        assert self._classify_via_sql("", "Subordinated Note") == "Unsecured"

    def test_2nd_lien_sql(self):
        assert self._classify_via_sql("2nd Lien Term Loan", "") == "Second Lien"

    def test_1st_lien_sql(self):
        assert self._classify_via_sql("1st Lien Term Loan", "") == "First Lien"

    def test_senior_lien_sql(self):
        assert self._classify_via_sql("Senior Lien", "") == "First Lien"

    def test_super_senior_sql(self):
        assert self._classify_via_sql("Super Senior Facility", "") == "First Lien"

    def test_junior_lien_sql(self):
        assert self._classify_via_sql("Junior Lien", "") == "Second Lien"

    def test_junior_secured_sql(self):
        assert self._classify_via_sql("Junior Secured", "") == "Second Lien"

    def test_last_out_sql(self):
        assert self._classify_via_sql("Last Out Term Loan", "") == "First Lien"

    def test_first_out_sql(self):
        assert self._classify_via_sql("First Out Term Loan", "") == "First Lien"

    # --- bdc_investment_identifier fallback ---
    def test_bid_first_lien_hierarchy(self):
        """Goldman-style long-form identifier with lien in hierarchy."""
        result = self._classify_via_sql(
            "Curriculum Associates, LLC", "Debt Investments",
            bdc_investment_identifier=(
                "Investment Debt Investments - 137.5% United States - 129.7% "
                "1st Lien/Senior Secured Debt - 125.7% "
                "Curriculum Associates, LLC Industry Diversified Consumer Services"
            ),
        )
        assert result == "First Lien"

    def test_bid_second_lien_hierarchy(self):
        result = self._classify_via_sql(
            "Magenta Buyer LLC", "Debt Investments",
            bdc_investment_identifier=(
                "Non-control/Non-affiliate Investments Magenta Buyer LLC "
                "Information Technology Services Second Lien Debt"
            ),
        )
        assert result == "Second Lien"

    def test_bid_unsecured_hierarchy(self):
        result = self._classify_via_sql(
            "Acme Corp", "Debt Investments",
            bdc_investment_identifier=(
                "Investment Debt - Unsecured Debt - 5.0% Acme Corp"
            ),
        )
        assert result == "Unsecured"

    def test_bid_no_keywords_still_null(self):
        """Identifier without lien keywords stays NULL."""
        result = self._classify_via_sql(
            "Guidehouse, Inc.", "",
            bdc_investment_identifier="Guidehouse, Inc.",
        )
        assert result is None

    def test_combined_text_takes_priority_over_bid(self):
        """When combined text has second lien but bid has first lien,
        second lien wins (checked first in priority order)."""
        result = self._classify_via_sql(
            "Acme Corp Second Lien", "",
            bdc_investment_identifier="1st Lien/Senior Secured Debt Acme Corp",
        )
        assert result == "Second Lien"


# ---------------------------------------------------------------------------
# SQL with DataFrame (integration test)
# ---------------------------------------------------------------------------

class TestSqlWithDataFrame:
    """Test SQL classification against a real DataFrame via DuckDB."""

    def test_batch_classification(self):
        lien_sql = _sql_classify_lien()
        df = pd.DataFrame({
            "issuer_name": [
                "Acme Corp",
                "Beta Inc",
                "Gamma LLC",
                "Delta Co",
                "Epsilon Ltd",
            ],
            "instrument_description": [
                "First Lien Term Loan",
                "Second Lien Note",
                "Mezzanine Facility",
                "Revolving Credit",
                "Senior Secured Term Loan B",
            ],
            "bdc_investment_identifier": ["", "", "", "", ""],
            "index_classification": [
                "DIRECT_LENDING",
                "DIRECT_LENDING",
                "DIRECT_LENDING",
                "DIRECT_LENDING",
                "DIRECT_LENDING",
            ],
        })

        con = duckdb.connect()
        con.register("holdings", df)
        result = con.execute(f"""
            WITH with_fund_text AS (
                SELECT *,
                    COALESCE(lower(trim(issuer_name)), '') || ' ' ||
                    COALESCE(lower(trim(instrument_description)), '') AS _combined_fund_text
                FROM holdings
            )
            SELECT issuer_name, {lien_sql} AS lien_position
            FROM with_fund_text
        """).fetchdf()
        con.close()

        expected = ["First Lien", "Second Lien", "Unsecured", None, "First Lien"]
        actual = result["lien_position"].tolist()
        assert actual == expected

    def test_batch_classification_via_bid(self):
        """Positions classified via bdc_investment_identifier when combined text has no keywords."""
        lien_sql = _sql_classify_lien()
        df = pd.DataFrame({
            "issuer_name": [
                "Curriculum Associates, LLC",
                "Magenta Buyer LLC",
                "Guidehouse, Inc.",
            ],
            "instrument_description": [
                "Debt Investments",
                "Debt Investments",
                "",
            ],
            "bdc_investment_identifier": [
                "Investment Debt Investments - 137.5% 1st Lien/Senior Secured Debt - 125.7% Curriculum Associates",
                "Non-control Investments Magenta Buyer LLC Second Lien Debt",
                "Guidehouse, Inc.",
            ],
        })

        con = duckdb.connect()
        con.register("holdings", df)
        result = con.execute(f"""
            WITH with_fund_text AS (
                SELECT *,
                    COALESCE(lower(trim(issuer_name)), '') || ' ' ||
                    COALESCE(lower(trim(instrument_description)), '') AS _combined_fund_text
                FROM holdings
            )
            SELECT issuer_name, {lien_sql} AS lien_position
            FROM with_fund_text
        """).fetchdf()
        con.close()

        expected = ["First Lien", "Second Lien", None]
        actual = result["lien_position"].tolist()
        assert actual == expected

    def test_non_direct_lending_excluded_in_final_select(self):
        """The final SELECT gates lien on _index_class = DIRECT_LENDING."""
        lien_sql = _sql_classify_lien()
        df = pd.DataFrame({
            "issuer_name": ["Equity Fund First Lien"],
            "instrument_description": [""],
            "bdc_investment_identifier": [""],
            "index_classification": ["COMMON_EQUITY"],
        })

        con = duckdb.connect()
        con.register("holdings", df)
        # Simulate the final SELECT gate
        result = con.execute(f"""
            WITH with_fund_text AS (
                SELECT *,
                    COALESCE(lower(trim(issuer_name)), '') || ' ' ||
                    COALESCE(lower(trim(instrument_description)), '') AS _combined_fund_text,
                    CAST(index_classification AS VARCHAR) AS _index_class
                FROM holdings
            )
            SELECT CASE WHEN _index_class = 'DIRECT_LENDING'
                        THEN ({lien_sql})
                        ELSE NULL END AS lien_position
            FROM with_fund_text
        """).fetchdf()
        con.close()

        assert result["lien_position"].iloc[0] is None


# ---------------------------------------------------------------------------
# _normalize_instrument_pattern
# ---------------------------------------------------------------------------

class TestNormalizeInstrumentPattern:
    def test_basic(self):
        result = _normalize_instrument_pattern("First Lien Term Loan")
        assert result == "first lien term loan"

    def test_strip_rate_sofr(self):
        result = _normalize_instrument_pattern("Term Loan SOFR + 5.50%")
        assert "5.50" not in result
        assert "sofr" not in result

    def test_strip_rate_libor(self):
        result = _normalize_instrument_pattern("Term Loan LIBOR + 350bps")
        assert "350" not in result

    def test_strip_percentage(self):
        result = _normalize_instrument_pattern("12.5% Senior Secured Note")
        assert "12.5" not in result

    def test_strip_date_slash(self):
        result = _normalize_instrument_pattern("Term Loan due 12/15/2027")
        assert "2027" not in result

    def test_strip_date_iso(self):
        result = _normalize_instrument_pattern("Note 2027-06-30")
        assert "2027" not in result

    def test_strip_date_due(self):
        result = _normalize_instrument_pattern("Note due 2028")
        assert "2028" not in result

    def test_strip_dollar_amount(self):
        result = _normalize_instrument_pattern("$1,500,000 Term Loan")
        assert "1,500" not in result

    def test_collapse_whitespace(self):
        result = _normalize_instrument_pattern("  First   Lien   Term  Loan  ")
        assert result == "first lien term loan"

    def test_empty_string(self):
        assert _normalize_instrument_pattern("") == ""

    def test_none_like(self):
        # Edge case for missing text
        result = _normalize_instrument_pattern("SOFR + 4.25%")
        assert result.strip() == ""

    def test_preserves_lien_keywords(self):
        result = _normalize_instrument_pattern("Second Lien Term Loan B SOFR + 6.00% 12/31/2028")
        assert "second lien" in result
        assert "term loan" in result


# ---------------------------------------------------------------------------
# Cache I/O
# ---------------------------------------------------------------------------

class TestCacheIO:
    def test_load_empty(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "pipeline.config.LIEN_CACHE_FILE",
            tmp_path / "nonexistent.csv",
        )
        cache = _load_lien_cache()
        assert cache == {}

    def test_save_and_load_roundtrip(self, tmp_path, monkeypatch):
        cache_file = tmp_path / "lien_cache.csv"
        monkeypatch.setattr("pipeline.config.LIEN_CACHE_FILE", cache_file)

        cache = {
            "first lien term loan": ("First Lien", "high", "keyword"),
            "second lien note": ("Second Lien", "medium", "agent"),
            "mezzanine facility": ("Unsecured", "low", "cc_skill"),
        }
        _save_lien_cache(cache)

        loaded = _load_lien_cache()
        assert len(loaded) == 3
        assert loaded["first lien term loan"] == ("First Lien", "high", "keyword")
        assert loaded["second lien note"] == ("Second Lien", "medium", "agent")
        assert loaded["mezzanine facility"] == ("Unsecured", "low", "cc_skill")

    def test_invalid_values_filtered(self, tmp_path, monkeypatch):
        cache_file = tmp_path / "lien_cache.csv"
        monkeypatch.setattr("pipeline.config.LIEN_CACHE_FILE", cache_file)
        monkeypatch.setattr("pipeline.config.LIEN_CACHE_FILE", cache_file)

        # Write a cache with an invalid lien value
        df = pd.DataFrame([
            {"pattern_norm": "valid", "lien_position": "First Lien",
             "confidence": "high", "source": "keyword", "timestamp": "2025-01-01"},
            {"pattern_norm": "invalid", "lien_position": "Third Lien",
             "confidence": "high", "source": "keyword", "timestamp": "2025-01-01"},
        ])
        df.to_csv(cache_file, index=False)

        loaded = _load_lien_cache()
        assert len(loaded) == 1
        assert "valid" in loaded
        assert "invalid" not in loaded

    def test_save_creates_sorted(self, tmp_path, monkeypatch):
        cache_file = tmp_path / "lien_cache.csv"
        monkeypatch.setattr("pipeline.config.LIEN_CACHE_FILE", cache_file)
        monkeypatch.setattr("pipeline.config.LIEN_CACHE_FILE", cache_file)

        cache = {
            "zzz pattern": ("First Lien", "high", "keyword"),
            "aaa pattern": ("Second Lien", "medium", "agent"),
        }
        _save_lien_cache(cache)

        df = pd.read_csv(cache_file)
        assert df.iloc[0]["pattern_norm"] == "aaa pattern"
        assert df.iloc[1]["pattern_norm"] == "zzz pattern"


# ---------------------------------------------------------------------------
# _apply_lien_cache
# ---------------------------------------------------------------------------

class TestApplyLienCache:
    def test_fills_null_from_cache(self, tmp_path, monkeypatch):
        cache_file = tmp_path / "lien_cache.csv"
        monkeypatch.setattr("pipeline.config.LIEN_CACHE_FILE", cache_file)
        monkeypatch.setattr("pipeline.config.LIEN_CACHE_FILE", cache_file)

        # Create cache with one entry
        cache = {"acme corp term loan": ("First Lien", "high", "agent")}
        _save_lien_cache(cache)

        # Create holdings with NULL lien_position
        df = pd.DataFrame({
            "issuer_name": ["Acme Corp"],
            "instrument_description": ["Term Loan"],
            "index_classification": ["DIRECT_LENDING"],
            "lien_position": [None],
            "fair_value": [1000000.0],
        })

        result = _apply_lien_cache(df)
        assert result["lien_position"].iloc[0] == "First Lien"

    def test_does_not_overwrite_existing(self, tmp_path, monkeypatch):
        cache_file = tmp_path / "lien_cache.csv"
        monkeypatch.setattr("pipeline.config.LIEN_CACHE_FILE", cache_file)
        monkeypatch.setattr("pipeline.config.LIEN_CACHE_FILE", cache_file)

        # Cache says Second Lien
        cache = {"acme corp term loan": ("Second Lien", "high", "agent")}
        _save_lien_cache(cache)

        # Holdings already have First Lien
        df = pd.DataFrame({
            "issuer_name": ["Acme Corp"],
            "instrument_description": ["Term Loan"],
            "index_classification": ["DIRECT_LENDING"],
            "lien_position": ["First Lien"],
            "fair_value": [1000000.0],
        })

        result = _apply_lien_cache(df)
        assert result["lien_position"].iloc[0] == "First Lien"

    def test_no_cache_file_returns_unchanged(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "pipeline.config.LIEN_CACHE_FILE",
            tmp_path / "nonexistent.csv",
        )

        df = pd.DataFrame({
            "issuer_name": ["Acme Corp"],
            "instrument_description": ["Term Loan"],
            "index_classification": ["DIRECT_LENDING"],
            "lien_position": [None],
            "fair_value": [1000000.0],
        })

        result = _apply_lien_cache(df)
        assert result["lien_position"].iloc[0] is None

    def test_non_direct_lending_not_filled(self, tmp_path, monkeypatch):
        cache_file = tmp_path / "lien_cache.csv"
        monkeypatch.setattr("pipeline.config.LIEN_CACHE_FILE", cache_file)
        monkeypatch.setattr("pipeline.config.LIEN_CACHE_FILE", cache_file)

        cache = {"equity fund": ("First Lien", "high", "agent")}
        _save_lien_cache(cache)

        df = pd.DataFrame({
            "issuer_name": ["Equity Fund"],
            "instrument_description": [""],
            "index_classification": ["COMMON_EQUITY"],
            "lien_position": [None],
            "fair_value": [1000000.0],
        })

        result = _apply_lien_cache(df)
        assert result["lien_position"].iloc[0] is None or result["lien_position"].iloc[0] == ""


# ---------------------------------------------------------------------------
# Keyword coverage checks
# ---------------------------------------------------------------------------

class TestKeywordCoverage:
    """Verify all keyword lists are non-empty and consistent."""

    def test_all_keyword_lists_nonempty(self):
        assert len(_FIRST_LIEN_KEYWORDS) > 0
        assert len(_SECOND_LIEN_KEYWORDS) > 0
        assert len(_UNSECURED_KEYWORDS) > 0

    def test_keywords_lowercase(self):
        for kw in _FIRST_LIEN_KEYWORDS + _SECOND_LIEN_KEYWORDS + _UNSECURED_KEYWORDS:
            assert kw == kw.lower(), f"Keyword should be lowercase: {kw}"

    def test_no_overlap_between_lists(self):
        first = set(_FIRST_LIEN_KEYWORDS)
        second = set(_SECOND_LIEN_KEYWORDS)
        unsecured = set(_UNSECURED_KEYWORDS)
        assert first.isdisjoint(second), f"Overlap: {first & second}"
        assert first.isdisjoint(unsecured), f"Overlap: {first & unsecured}"
        assert second.isdisjoint(unsecured), f"Overlap: {second & unsecured}"

    def test_python_and_sql_agree(self):
        """Python classify_lien and SQL _sql_classify_lien produce same results."""
        # (issuer_name, instrument_desc, bdc_investment_identifier)
        test_cases = [
            ("First Lien Term Loan", "", ""),
            ("Second Lien Note", "", ""),
            ("Mezzanine Facility", "", ""),
            ("Acme Corp", "Senior Secured First Lien", ""),
            ("Plain Term Loan", "No keywords here", ""),
            ("Senior Secured Second Lien", "", ""),
            ("Unitranche", "", ""),
            ("Junior Secured Note", "", ""),
            # bdc_investment_identifier cases
            ("Acme Corp", "Debt Investments",
             "Investment 1st Lien/Senior Secured Debt Acme Corp"),
            ("Beta Inc", "Debt Investments",
             "Non-control Investments Beta Inc Second Lien Debt"),
            ("Gamma LLC", "", "Gamma LLC"),  # no keywords anywhere
        ]

        lien_sql = _sql_classify_lien()
        con = duckdb.connect()

        for issuer, inst, bid in test_cases:
            py_result = classify_lien(
                issuer, inst, bdc_investment_identifier=bid,
            )
            sql_result = con.execute(f"""
                SELECT {lien_sql} AS lien
                FROM (
                    SELECT
                        COALESCE(lower(trim('{issuer}')), '') || ' ' ||
                        COALESCE(lower(trim('{inst}')), '') AS _combined_fund_text,
                        '{bid}' AS bdc_investment_identifier
                )
            """).fetchone()[0]

            assert py_result == sql_result, (
                f"Mismatch for ({issuer!r}, {inst!r}, bid={bid!r}): "
                f"Python={py_result}, SQL={sql_result}"
            )

        con.close()


# ---------------------------------------------------------------------------
# Real-world instrument description patterns
# ---------------------------------------------------------------------------

class TestRealWorldPatterns:
    """Test against patterns commonly seen in BDC filings."""

    def test_senior_secured_first_lien_term_loan(self):
        assert classify_lien(
            "ABC Holdings, LLC | Senior Secured Loans - First Lien | Technology",
            "Senior Secured First Lien Term Loan"
        ) == "First Lien"

    def test_second_lien_delayed_draw(self):
        assert classify_lien(
            "XYZ Corp | Second Lien",
            "Second Lien Delayed Draw Term Loan"
        ) == "Second Lien"

    def test_unsecured_bond(self):
        assert classify_lien(
            "DEF Inc",
            "Unsecured Bond"
        ) == "Unsecured"

    def test_subordinated_note_via_instrument(self):
        assert classify_lien(
            "GHI Corp",
            "Subordinated Note due 2028"
        ) == "Unsecured"

    def test_mezzanine_debt(self):
        assert classify_lien(
            "JKL Holdings",
            "Mezzanine Debt"
        ) == "Unsecured"

    def test_unitranche_term_loan(self):
        assert classify_lien(
            "MNO Partners",
            "Unitranche Term Loan"
        ) == "First Lien"

    def test_super_senior_revolver(self):
        assert classify_lien(
            "PQR Inc",
            "Super Senior Revolving Credit Facility"
        ) == "First Lien"

    def test_last_out_term_loan(self):
        assert classify_lien(
            "STU Corp",
            "Last Out Term Loan"
        ) == "First Lien"

    def test_first_out_tranche(self):
        assert classify_lien(
            "VWX LLC",
            "First Out Tranche"
        ) == "First Lien"

    def test_no_lien_keyword_plain_term_loan(self):
        assert classify_lien("Alpha Corp", "Term Loan") is None

    def test_no_lien_keyword_revolving_credit(self):
        assert classify_lien("Beta Corp", "Revolving Credit Facility") is None

    def test_no_lien_keyword_delayed_draw(self):
        assert classify_lien("Gamma Corp", "Delayed Draw Term Loan") is None

    def test_1st_lien_with_rate(self):
        assert classify_lien(
            "Delta Corp",
            "1st Lien Term Loan SOFR + 5.50%"
        ) == "First Lien"

    def test_bdc_pipe_delimited_identifier(self):
        """BDC investment identifiers often use pipe delimiters."""
        assert classify_lien(
            "Epsilon Holdings | Senior Secured Loans - First Lien | Healthcare",
            None
        ) == "First Lien"

    def test_bdc_second_lien_in_identifier(self):
        assert classify_lien(
            "Zeta Corp | Senior Secured Loans - Second Lien | Software",
            None
        ) == "Second Lien"


# ---------------------------------------------------------------------------
# SQL generation sanity
# ---------------------------------------------------------------------------

class TestSqlGeneration:
    def test_returns_string(self):
        sql = _sql_classify_lien()
        assert isinstance(sql, str)

    def test_contains_case_when(self):
        sql = _sql_classify_lien()
        assert "CASE" in sql
        assert "END" in sql

    def test_all_three_values_present(self):
        sql = _sql_classify_lien()
        assert "'First Lien'" in sql
        assert "'Second Lien'" in sql
        assert "'Unsecured'" in sql

    def test_valid_duckdb_sql(self):
        """The generated SQL should parse and execute in DuckDB."""
        sql = _sql_classify_lien()
        con = duckdb.connect()
        result = con.execute(f"""
            SELECT {sql} AS lien_position
            FROM (SELECT 'first lien term loan' AS _combined_fund_text,
                         '' AS bdc_investment_identifier)
        """).fetchone()
        con.close()
        assert result[0] == "First Lien"
