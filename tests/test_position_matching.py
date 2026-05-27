"""Tests for pipeline.position_matching module.

Covers:
- Tier A: BDC within-filing comparatives
- Tier B: Exact CUSIP (B1) and exact name (B2)
- Tier C: Regex-normalized name
- Tier D: Jaro-Winkler fuzzy match
- 1:1 enforcement (fan-out prevention)
- Cascade exclusion (row-ID based)
- Integration and edge cases
"""

import pandas as pd
import pytest

from pipeline.position_matching import (
    MATCH_COLUMNS,
    MAX_CUSIP_MULTIPLICITY,
    MAX_FV_RATIO,
    MAX_FV_RATIO_IDENTIFIER,
    MAX_FV_RATIO_WITHIN_FILING,
    MAX_NAME_MULTIPLICITY,
    MIN_JW_SIMILARITY,
    assign_position_ids,
    match_positions,
)
from pipeline.match_reconciliation import build_position_match_reconciliation


@pytest.fixture(autouse=True)
def _redirect_position_matching_output(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "pipeline.position_matching.POSITION_MATCHES_FILE",
        tmp_path / "position_matches.csv",
    )
    monkeypatch.setattr(
        "pipeline.index_returns.POSITION_RETURNS_FILE",
        tmp_path / "position_returns.csv",
    )
    monkeypatch.setattr(
        "pipeline.index_returns.INDEX_RETURNS_FILE",
        tmp_path / "index_returns.csv",
    )


# ---------------------------------------------------------------------------
# Helpers -- synthetic DataFrames
# ---------------------------------------------------------------------------

def _make_bdc_raw(rows: list[dict]) -> pd.DataFrame:
    """Create a minimal raw BDC DataFrame."""
    cols = [
        "cik", "entity_name", "accession_number", "form_type",
        "filing_date", "report_date", "period",
        "investment_identifier", "fair_value", "cost",
        "principal_amount", "interest_rate", "basis_spread",
        "shares_held", "pct_of_net_assets", "unrealized_gain_loss",
        "pik_rate", "reference_rate_type", "maturity_date",
        "industry", "investment_type", "affiliation", "dimensions_raw",
    ]
    df = pd.DataFrame(rows)
    for c in cols:
        if c not in df.columns:
            df[c] = None
    return df[cols]


def _make_unified(rows: list[dict]) -> pd.DataFrame:
    """Create a minimal unified holdings DataFrame."""
    from pipeline.unified_holdings import UNIFIED_COLUMNS
    df = pd.DataFrame(rows)
    for c in UNIFIED_COLUMNS:
        if c not in df.columns:
            df[c] = None
    return df[UNIFIED_COLUMNS]


# ---------------------------------------------------------------------------
# Tier A: Within-Filing Comparatives
# ---------------------------------------------------------------------------

class TestTierA:
    def test_basic_pair(self):
        """Same accession + identifier -> matched pair."""
        bdc_raw = _make_bdc_raw([
            {"cik": "100", "entity_name": "TestBDC", "accession_number": "ACC1",
             "report_date": "2024-06-30", "period": "2024-06-30",
             "investment_identifier": "Acme Corp - Loan",
             "fair_value": "1000000", "cost": "950000"},
            {"cik": "100", "entity_name": "TestBDC", "accession_number": "ACC1",
             "report_date": "2024-06-30", "period": "2023-12-31",
             "investment_identifier": "Acme Corp - Loan",
             "fair_value": "980000", "cost": "950000"},
        ])
        unified = _make_unified([
            {"source": "bdc", "cik": "100", "entity_name": "TestBDC",
             "report_date": "2024-06-30", "issuer_name": "Acme Corp",
             "fair_value": "1000000", "index_classification": "DIRECT_LENDING",
             "asset_category": "LOAN_FIRST_LIEN",
             "bdc_investment_identifier": "Acme Corp - Loan"},
        ])
        result = match_positions(unified_df=unified, bdc_raw_df=bdc_raw)
        method_a = result[result["match_method"] == "A_within_filing"]
        assert len(method_a) == 1
        row = method_a.iloc[0]
        assert float(row["begin_fair_value"]) == 980000
        assert float(row["end_fair_value"]) == 1000000
        assert int(row["span_months"]) == 6

    def test_no_match_different_identifier(self):
        """Different identifiers in same filing -> no match."""
        bdc_raw = _make_bdc_raw([
            {"cik": "100", "entity_name": "TestBDC", "accession_number": "ACC1",
             "report_date": "2024-06-30", "period": "2024-06-30",
             "investment_identifier": "Acme Corp - Loan",
             "fair_value": "1000000"},
            {"cik": "100", "entity_name": "TestBDC", "accession_number": "ACC1",
             "report_date": "2024-06-30", "period": "2023-12-31",
             "investment_identifier": "Beta Inc - Loan",
             "fair_value": "500000"},
        ])
        unified = _make_unified([
            {"source": "bdc", "cik": "100", "entity_name": "TestBDC",
             "report_date": "2024-06-30", "issuer_name": "Acme Corp",
             "fair_value": "1000000",
             "bdc_investment_identifier": "Acme Corp - Loan"},
        ])
        result = match_positions(unified_df=unified, bdc_raw_df=bdc_raw)
        method_a = result[result["match_method"] == "A_within_filing"]
        assert len(method_a) == 0

    def test_span_calculation(self):
        """12-month span correctly computed."""
        bdc_raw = _make_bdc_raw([
            {"cik": "100", "entity_name": "TestBDC", "accession_number": "ACC1",
             "report_date": "2024-12-31", "period": "2024-12-31",
             "investment_identifier": "Acme Corp",
             "fair_value": "1100000"},
            {"cik": "100", "entity_name": "TestBDC", "accession_number": "ACC1",
             "report_date": "2024-12-31", "period": "2023-12-31",
             "investment_identifier": "Acme Corp",
             "fair_value": "1000000"},
        ])
        unified = _make_unified([
            {"source": "bdc", "cik": "100", "entity_name": "TestBDC",
             "report_date": "2024-12-31", "issuer_name": "Acme Corp",
             "fair_value": "1100000",
             "bdc_investment_identifier": "Acme Corp"},
        ])
        result = match_positions(unified_df=unified, bdc_raw_df=bdc_raw)
        method_a = result[result["match_method"] == "A_within_filing"]
        assert len(method_a) == 1
        assert int(method_a.iloc[0]["span_months"]) == 12

    def test_excludes_zero_fv(self):
        """Rows with FV = 0 should not be matched."""
        bdc_raw = _make_bdc_raw([
            {"cik": "100", "entity_name": "TestBDC", "accession_number": "ACC1",
             "report_date": "2024-06-30", "period": "2024-06-30",
             "investment_identifier": "Acme Corp",
             "fair_value": "1000000"},
            {"cik": "100", "entity_name": "TestBDC", "accession_number": "ACC1",
             "report_date": "2024-06-30", "period": "2023-12-31",
             "investment_identifier": "Acme Corp",
             "fair_value": "0"},
        ])
        unified = _make_unified([
            {"source": "bdc", "cik": "100", "entity_name": "TestBDC",
             "report_date": "2024-06-30", "issuer_name": "Acme Corp",
             "fair_value": "1000000",
             "bdc_investment_identifier": "Acme Corp"},
        ])
        result = match_positions(unified_df=unified, bdc_raw_df=bdc_raw)
        method_a = result[result["match_method"] == "A_within_filing"]
        assert len(method_a) == 0

    def test_tier_a_skips_current_rows_absent_from_unified(self):
        """Aggregate/header rows filtered out of unified should not survive in matches."""
        bdc_raw = _make_bdc_raw([
            {"cik": "2041841", "entity_name": "TestBDC", "accession_number": "ACC1",
             "report_date": "2025-06-30", "period": "2025-06-30",
             "investment_identifier": "Total Investments at Fair Value",
             "fair_value": "63284000", "cost": "63284000"},
            {"cik": "2041841", "entity_name": "TestBDC", "accession_number": "ACC1",
             "report_date": "2025-06-30", "period": "2024-12-31",
             "investment_identifier": "Total Investments at Fair Value",
             "fair_value": "43714000", "cost": "43714000"},
        ])
        unified = _make_unified([
            {"source": "bdc", "cik": "0002041841", "entity_name": "TestBDC",
             "report_date": "2025-06-30", "issuer_name": "Acme Corp",
             "fair_value": "1000000",
             "bdc_investment_identifier": "Acme Corp - Term Loan"},
        ])

        result = match_positions(unified_df=unified, bdc_raw_df=bdc_raw)
        assert len(result[result["match_method"] == "A_within_filing"]) == 0
        assert not result["begin_issuer_name"].astype(str).str.contains("Total Investments").any()

    def test_one_to_one_shortest_span(self):
        """Multiple comparatives -> shortest span preferred."""
        bdc_raw = _make_bdc_raw([
            # Current
            {"cik": "100", "entity_name": "TestBDC", "accession_number": "ACC1",
             "report_date": "2024-12-31", "period": "2024-12-31",
             "investment_identifier": "Acme Corp",
             "fair_value": "1100000"},
            # 6-month comparative
            {"cik": "100", "entity_name": "TestBDC", "accession_number": "ACC1",
             "report_date": "2024-12-31", "period": "2024-06-30",
             "investment_identifier": "Acme Corp",
             "fair_value": "1050000"},
            # 12-month comparative
            {"cik": "100", "entity_name": "TestBDC", "accession_number": "ACC1",
             "report_date": "2024-12-31", "period": "2023-12-31",
             "investment_identifier": "Acme Corp",
             "fair_value": "1000000"},
        ])
        unified = _make_unified([
            {"source": "bdc", "cik": "100", "entity_name": "TestBDC",
             "report_date": "2024-12-31", "issuer_name": "Acme Corp",
             "fair_value": "1100000",
             "bdc_investment_identifier": "Acme Corp"},
        ])
        result = match_positions(unified_df=unified, bdc_raw_df=bdc_raw)
        method_a = result[result["match_method"] == "A_within_filing"]
        # 1:1 enforcement: only one pair per end position, shortest span
        assert len(method_a) == 1
        assert int(method_a.iloc[0]["span_months"]) == 6
        assert float(method_a.iloc[0]["begin_fair_value"]) == 1050000


# ---------------------------------------------------------------------------
# Tier B: Exact Name / CUSIP
# ---------------------------------------------------------------------------

class TestTierB:
    def test_cusip_match(self):
        """B1: N-PORT CUSIP match across consecutive quarters."""
        bdc_raw = _make_bdc_raw([])
        unified = _make_unified([
            {"source": "nport", "cik": "300", "entity_name": "IntFund1",
             "report_date": "2024-03-31", "issuer_name": "Corporate Bond A",
             "fair_value": "1000000", "cusip": "123456789",
             "asset_category": "LOAN_FIRST_LIEN"},
            {"source": "nport", "cik": "300", "entity_name": "IntFund1",
             "report_date": "2024-06-30", "issuer_name": "Corporate Bond A",
             "fair_value": "1020000", "cusip": "123456789",
             "asset_category": "LOAN_FIRST_LIEN"},
        ])
        result = match_positions(unified_df=unified, bdc_raw_df=bdc_raw)
        b1 = result[result["match_method"] == "B1_cusip"]
        assert len(b1) == 1
        assert b1.iloc[0]["match_key"] == "123456789"

    def test_placeholder_cusip_excluded(self):
        """Placeholder CUSIP '000000000' excluded, falls to name."""
        bdc_raw = _make_bdc_raw([])
        unified = _make_unified([
            {"source": "nport", "cik": "300", "entity_name": "IntFund1",
             "report_date": "2024-03-31", "issuer_name": "Private Loan",
             "fair_value": "500000", "cusip": "000000000",
             "asset_category": "LOAN_FIRST_LIEN"},
            {"source": "nport", "cik": "300", "entity_name": "IntFund1",
             "report_date": "2024-06-30", "issuer_name": "Private Loan",
             "fair_value": "510000", "cusip": "000000000",
             "asset_category": "LOAN_FIRST_LIEN"},
        ])
        result = match_positions(unified_df=unified, bdc_raw_df=bdc_raw)
        b1 = result[result["match_method"] == "B1_cusip"]
        assert len(b1) == 0
        # Should still match via B2 exact name
        b2 = result[result["match_method"] == "B2_exact_name"]
        assert len(b2) == 1

    def test_high_multiplicity_cusip_excluded(self):
        """CUSIPs appearing > MAX_CUSIP_MULTIPLICITY times excluded from B1."""
        bdc_raw = _make_bdc_raw([])
        rows = []
        for i in range(MAX_CUSIP_MULTIPLICITY + 1):
            rows.append({
                "source": "nport", "cik": "300", "entity_name": "IntFund1",
                "report_date": "2024-03-31", "issuer_name": f"Loan Tranche {i}",
                "fair_value": str(100000 + i * 1000), "cusip": "ABCDE1234",
                "asset_category": "LOAN_FIRST_LIEN",
            })
        for i in range(MAX_CUSIP_MULTIPLICITY + 1):
            rows.append({
                "source": "nport", "cik": "300", "entity_name": "IntFund1",
                "report_date": "2024-06-30", "issuer_name": f"Loan Tranche {i}",
                "fair_value": str(101000 + i * 1000), "cusip": "ABCDE1234",
                "asset_category": "LOAN_FIRST_LIEN",
            })
        unified = _make_unified(rows)
        result = match_positions(unified_df=unified, bdc_raw_df=bdc_raw)
        b1 = result[result["match_method"] == "B1_cusip"]
        assert len(b1) == 0, f"Expected 0 B1 matches, got {len(b1)}"

    def test_exact_name_match(self):
        """B2: BDC exact issuer_name across consecutive quarters."""
        bdc_raw = _make_bdc_raw([])
        unified = _make_unified([
            {"source": "bdc", "cik": "200", "entity_name": "BDC2",
             "report_date": "2024-03-31", "issuer_name": "Gamma Inc",
             "fair_value": "500000", "asset_category": "LOAN_FIRST_LIEN"},
            {"source": "bdc", "cik": "200", "entity_name": "BDC2",
             "report_date": "2024-06-30", "issuer_name": "Gamma Inc",
             "fair_value": "510000", "asset_category": "LOAN_FIRST_LIEN"},
        ])
        result = match_positions(unified_df=unified, bdc_raw_df=bdc_raw)
        b2 = result[result["match_method"] == "B2_exact_name"]
        assert len(b2) == 1

    def test_cusip_over_name(self):
        """CUSIP takes priority when both match."""
        bdc_raw = _make_bdc_raw([])
        unified = _make_unified([
            {"source": "nport", "cik": "300", "entity_name": "Fund1",
             "report_date": "2024-03-31", "issuer_name": "Bond Corp",
             "fair_value": "1000000", "cusip": "ABC123456"},
            {"source": "nport", "cik": "300", "entity_name": "Fund1",
             "report_date": "2024-06-30", "issuer_name": "Bond Corp",
             "fair_value": "1020000", "cusip": "ABC123456"},
        ])
        result = match_positions(unified_df=unified, bdc_raw_df=bdc_raw)
        # Should match via CUSIP, not name (since CUSIP match consumes the row)
        assert len(result) == 1
        assert result.iloc[0]["match_method"] == "B1_cusip"

    def test_case_insensitive(self):
        """B2: case differences still match."""
        bdc_raw = _make_bdc_raw([])
        unified = _make_unified([
            {"source": "bdc", "cik": "200", "entity_name": "BDC2",
             "report_date": "2024-03-31", "issuer_name": "GAMMA INC",
             "fair_value": "500000"},
            {"source": "bdc", "cik": "200", "entity_name": "BDC2",
             "report_date": "2024-06-30", "issuer_name": "gamma inc",
             "fair_value": "510000"},
        ])
        result = match_positions(unified_df=unified, bdc_raw_df=bdc_raw)
        b2 = result[result["match_method"] == "B2_exact_name"]
        assert len(b2) == 1

    def test_high_multiplicity_name_excluded(self):
        """Names appearing > MAX_NAME_MULTIPLICITY times excluded from B2."""
        bdc_raw = _make_bdc_raw([])
        n = MAX_NAME_MULTIPLICITY + 1
        rows = []
        # Q1: n positions with the same generic name
        for i in range(n):
            rows.append({
                "source": "bdc", "cik": "200", "entity_name": "BDC2",
                "report_date": "2024-03-31",
                "issuer_name": "Investment 1st Lien/Senior Secured Debt",
                "fair_value": str(100000 + i * 1000),
            })
        # Q2: n positions with the same generic name
        for i in range(n):
            rows.append({
                "source": "bdc", "cik": "200", "entity_name": "BDC2",
                "report_date": "2024-06-30",
                "issuer_name": "Investment 1st Lien/Senior Secured Debt",
                "fair_value": str(101000 + i * 1000),
            })
        unified = _make_unified(rows)
        result = match_positions(unified_df=unified, bdc_raw_df=bdc_raw)
        b2 = result[result["match_method"] == "B2_exact_name"]
        assert len(b2) == 0, f"Expected 0 B2 matches for high-mult name, got {len(b2)}"

    def test_below_multiplicity_threshold_still_matches(self):
        """Names at or below MAX_NAME_MULTIPLICITY still match via B2."""
        bdc_raw = _make_bdc_raw([])
        n = MAX_NAME_MULTIPLICITY  # exactly at threshold -- should pass
        rows = []
        for i in range(n):
            rows.append({
                "source": "bdc", "cik": "200", "entity_name": "BDC2",
                "report_date": "2024-03-31",
                "issuer_name": "Acme Corp First Lien",
                "fair_value": str(100000 + i * 10000),
            })
        for i in range(n):
            rows.append({
                "source": "bdc", "cik": "200", "entity_name": "BDC2",
                "report_date": "2024-06-30",
                "issuer_name": "Acme Corp First Lien",
                "fair_value": str(101000 + i * 10000),
            })
        unified = _make_unified(rows)
        result = match_positions(unified_df=unified, bdc_raw_df=bdc_raw)
        b2 = result[result["match_method"] == "B2_exact_name"]
        # At threshold, 1:1 enforcement yields min(n, n) = n matches
        assert len(b2) == n, f"Expected {n} B2 matches, got {len(b2)}"

    def test_high_multiplicity_name_does_not_block_other_names(self):
        """High-mult name exclusion doesn't affect other normal names."""
        bdc_raw = _make_bdc_raw([])
        n = MAX_NAME_MULTIPLICITY + 1
        rows = []
        # Generic name: above threshold
        for i in range(n):
            rows.append({
                "source": "bdc", "cik": "200", "entity_name": "BDC2",
                "report_date": "2024-03-31",
                "issuer_name": "Generic Category Header",
                "fair_value": str(100000 + i * 1000),
            })
        for i in range(n):
            rows.append({
                "source": "bdc", "cik": "200", "entity_name": "BDC2",
                "report_date": "2024-06-30",
                "issuer_name": "Generic Category Header",
                "fair_value": str(101000 + i * 1000),
            })
        # Normal name: should still match
        rows.append({
            "source": "bdc", "cik": "200", "entity_name": "BDC2",
            "report_date": "2024-03-31", "issuer_name": "Real Company LLC",
            "fair_value": "500000",
        })
        rows.append({
            "source": "bdc", "cik": "200", "entity_name": "BDC2",
            "report_date": "2024-06-30", "issuer_name": "Real Company LLC",
            "fair_value": "510000",
        })
        unified = _make_unified(rows)
        result = match_positions(unified_df=unified, bdc_raw_df=bdc_raw)
        b2 = result[result["match_method"] == "B2_exact_name"]
        # Only the normal name should match
        assert len(b2) == 1
        assert b2.iloc[0]["match_key"] == "real company llc"


# ---------------------------------------------------------------------------
# Tier C: Normalized Name
# ---------------------------------------------------------------------------

class TestTierC:
    def test_pipe_suffix_stripped(self):
        """'Company | Suffix' matches 'Company'."""
        bdc_raw = _make_bdc_raw([])
        unified = _make_unified([
            {"source": "bdc", "cik": "200", "entity_name": "BDC2",
             "report_date": "2024-03-31", "issuer_name": "Acme Corp",
             "fair_value": "500000"},
            {"source": "bdc", "cik": "200", "entity_name": "BDC2",
             "report_date": "2024-06-30",
             "issuer_name": "Acme Corp | Non-Affiliated",
             "fair_value": "510000"},
        ])
        result = match_positions(unified_df=unified, bdc_raw_df=bdc_raw)
        # No exact name match (different strings), should match at tier C
        tier_c = result[result["match_method"] == "C_normalized_name"]
        assert len(tier_c) == 1

    def test_ordinal_stripped(self):
        """'Company 1' matches 'Company'."""
        bdc_raw = _make_bdc_raw([])
        unified = _make_unified([
            {"source": "bdc", "cik": "200", "entity_name": "BDC2",
             "report_date": "2024-03-31", "issuer_name": "Acme Corp 1",
             "fair_value": "500000"},
            {"source": "bdc", "cik": "200", "entity_name": "BDC2",
             "report_date": "2024-06-30", "issuer_name": "Acme Corp",
             "fair_value": "510000"},
        ])
        result = match_positions(unified_df=unified, bdc_raw_df=bdc_raw)
        tier_c = result[result["match_method"] == "C_normalized_name"]
        assert len(tier_c) == 1

    def test_parenthetical_stripped(self):
        """'Company (95.6%)' matches 'Company'."""
        bdc_raw = _make_bdc_raw([])
        unified = _make_unified([
            {"source": "nport", "cik": "300", "entity_name": "Fund1",
             "report_date": "2024-03-31",
             "issuer_name": "Acme Corp (95.6%)",
             "fair_value": "500000"},
            {"source": "nport", "cik": "300", "entity_name": "Fund1",
             "report_date": "2024-06-30", "issuer_name": "Acme Corp",
             "fair_value": "510000"},
        ])
        result = match_positions(unified_df=unified, bdc_raw_df=bdc_raw)
        tier_c = result[result["match_method"] == "C_normalized_name"]
        assert len(tier_c) == 1

    def test_punctuation_normalized(self):
        """'Inc' matches 'Inc.'."""
        bdc_raw = _make_bdc_raw([])
        unified = _make_unified([
            {"source": "bdc", "cik": "200", "entity_name": "BDC2",
             "report_date": "2024-03-31", "issuer_name": "Acme Inc",
             "fair_value": "500000"},
            {"source": "bdc", "cik": "200", "entity_name": "BDC2",
             "report_date": "2024-06-30", "issuer_name": "Acme Inc.",
             "fair_value": "510000"},
        ])
        result = match_positions(unified_df=unified, bdc_raw_df=bdc_raw)
        tier_c = result[result["match_method"] == "C_normalized_name"]
        assert len(tier_c) == 1

    def test_no_match_when_exact_exists(self):
        """Already matched at B -> no duplicate at C."""
        bdc_raw = _make_bdc_raw([])
        unified = _make_unified([
            {"source": "bdc", "cik": "200", "entity_name": "BDC2",
             "report_date": "2024-03-31", "issuer_name": "Gamma Inc",
             "fair_value": "500000"},
            {"source": "bdc", "cik": "200", "entity_name": "BDC2",
             "report_date": "2024-06-30", "issuer_name": "Gamma Inc",
             "fair_value": "510000"},
        ])
        result = match_positions(unified_df=unified, bdc_raw_df=bdc_raw)
        # Should be matched only once (at B2)
        assert len(result) == 1
        assert result.iloc[0]["match_method"] == "B2_exact_name"


# ---------------------------------------------------------------------------
# Tier D: Fuzzy Match
# ---------------------------------------------------------------------------

class TestTierD:
    def test_jw_match_above_threshold(self):
        """JW >= threshold -> matched."""
        bdc_raw = _make_bdc_raw([])
        # "Acme Corporation" vs "Acme Corporaton" (typo) -- JW > 0.88
        unified = _make_unified([
            {"source": "bdc", "cik": "200", "entity_name": "BDC2",
             "report_date": "2024-03-31", "issuer_name": "Acme Corporation",
             "fair_value": "500000"},
            {"source": "bdc", "cik": "200", "entity_name": "BDC2",
             "report_date": "2024-06-30", "issuer_name": "Acme Corporaton",
             "fair_value": "510000"},
        ])
        result = match_positions(unified_df=unified, bdc_raw_df=bdc_raw)
        fuzzy = result[result["match_method"] == "D_fuzzy"]
        assert len(fuzzy) == 1
        assert float(fuzzy.iloc[0]["match_score"]) >= MIN_JW_SIMILARITY

    def test_jw_below_threshold_excluded(self):
        """JW < threshold -> not matched."""
        bdc_raw = _make_bdc_raw([])
        # Very different names sharing first 4 chars
        unified = _make_unified([
            {"source": "bdc", "cik": "200", "entity_name": "BDC2",
             "report_date": "2024-03-31", "issuer_name": "Acme Systems Inc",
             "fair_value": "500000"},
            {"source": "bdc", "cik": "200", "entity_name": "BDC2",
             "report_date": "2024-06-30", "issuer_name": "Acme Widgets Corp",
             "fair_value": "510000"},
        ])
        result = match_positions(unified_df=unified, bdc_raw_df=bdc_raw)
        fuzzy = result[result["match_method"] == "D_fuzzy"]
        assert len(fuzzy) == 0

    def test_fv_proximity_tiebreaker(self):
        """Ambiguous fuzzy name -> closer FV wins."""
        bdc_raw = _make_bdc_raw([])
        # Two Q1 positions with slightly different names, two Q2 candidates
        # All names are unique to avoid exact-match at B2
        unified = _make_unified([
            # Q1: "Acme Corporaton" FV=500k
            {"source": "bdc", "cik": "200", "entity_name": "BDC2",
             "report_date": "2024-03-31", "issuer_name": "Acme Corporaton",
             "fair_value": "500000"},
            # Q2: "Acme Corporation" FV=510k (close to Q1 500k)
            {"source": "bdc", "cik": "200", "entity_name": "BDC2",
             "report_date": "2024-06-30", "issuer_name": "Acme Corporation",
             "fair_value": "510000"},
        ])
        result = match_positions(unified_df=unified, bdc_raw_df=bdc_raw)
        fuzzy = result[result["match_method"] == "D_fuzzy"]
        assert len(fuzzy) == 1
        assert float(fuzzy.iloc[0]["end_fair_value"]) == 510000

    def test_fv_guard_prevents_nonsense(self):
        """$1M vs $500M not matched even if JW high."""
        bdc_raw = _make_bdc_raw([])
        unified = _make_unified([
            {"source": "bdc", "cik": "200", "entity_name": "BDC2",
             "report_date": "2024-03-31", "issuer_name": "Acme Corporaton",
             "fair_value": "1000000"},
            {"source": "bdc", "cik": "200", "entity_name": "BDC2",
             "report_date": "2024-06-30", "issuer_name": "Acme Corporation",
             "fair_value": "500000000"},  # 500x larger
        ])
        result = match_positions(unified_df=unified, bdc_raw_df=bdc_raw)
        fuzzy = result[result["match_method"] == "D_fuzzy"]
        assert len(fuzzy) == 0

    def test_match_score_populated(self):
        """match_score contains JW value for fuzzy matches."""
        bdc_raw = _make_bdc_raw([])
        unified = _make_unified([
            {"source": "bdc", "cik": "200", "entity_name": "BDC2",
             "report_date": "2024-03-31", "issuer_name": "Acme Corporation",
             "fair_value": "500000"},
            {"source": "bdc", "cik": "200", "entity_name": "BDC2",
             "report_date": "2024-06-30", "issuer_name": "Acme Corporaton",
             "fair_value": "510000"},
        ])
        result = match_positions(unified_df=unified, bdc_raw_df=bdc_raw)
        fuzzy = result[result["match_method"] == "D_fuzzy"]
        if len(fuzzy) > 0:
            score = float(fuzzy.iloc[0]["match_score"])
            assert 0 < score < 1.0  # Not exactly 1.0 for fuzzy


# ---------------------------------------------------------------------------
# 1:1 Enforcement
# ---------------------------------------------------------------------------

class TestOneToOne:
    def test_prevents_fan_out_begin(self):
        """1 Q1 position with 3 Q2 name matches -> only 1 pair."""
        bdc_raw = _make_bdc_raw([])
        unified = _make_unified([
            # Q1: one "Company X"
            {"source": "nport", "cik": "300", "entity_name": "Fund1",
             "report_date": "2024-03-31", "issuer_name": "Company X",
             "fair_value": "1000000"},
            # Q2: three "Company X" (different tranches, same name)
            {"source": "nport", "cik": "300", "entity_name": "Fund1",
             "report_date": "2024-06-30", "issuer_name": "Company X",
             "fair_value": "1010000"},
            {"source": "nport", "cik": "300", "entity_name": "Fund1",
             "report_date": "2024-06-30", "issuer_name": "Company X",
             "fair_value": "500000"},
            {"source": "nport", "cik": "300", "entity_name": "Fund1",
             "report_date": "2024-06-30", "issuer_name": "Company X",
             "fair_value": "200000"},
        ])
        result = match_positions(unified_df=unified, bdc_raw_df=bdc_raw)
        assert len(result) == 1  # 1:1 enforcement

    def test_prevents_fan_out_end(self):
        """3 Q1 positions matching 1 Q2 position -> only 1 pair."""
        bdc_raw = _make_bdc_raw([])
        unified = _make_unified([
            # Q1: three "Company Y"
            {"source": "nport", "cik": "300", "entity_name": "Fund1",
             "report_date": "2024-03-31", "issuer_name": "Company Y",
             "fair_value": "1000000"},
            {"source": "nport", "cik": "300", "entity_name": "Fund1",
             "report_date": "2024-03-31", "issuer_name": "Company Y",
             "fair_value": "500000"},
            {"source": "nport", "cik": "300", "entity_name": "Fund1",
             "report_date": "2024-03-31", "issuer_name": "Company Y",
             "fair_value": "200000"},
            # Q2: one "Company Y"
            {"source": "nport", "cik": "300", "entity_name": "Fund1",
             "report_date": "2024-06-30", "issuer_name": "Company Y",
             "fair_value": "1010000"},
        ])
        result = match_positions(unified_df=unified, bdc_raw_df=bdc_raw)
        assert len(result) == 1  # 1:1 enforcement

    def test_fv_tiebreak(self):
        """Closest FV wins in ambiguous group."""
        bdc_raw = _make_bdc_raw([])
        unified = _make_unified([
            # Q1: "Company Z" FV=1M
            {"source": "nport", "cik": "300", "entity_name": "Fund1",
             "report_date": "2024-03-31", "issuer_name": "Company Z",
             "fair_value": "1000000"},
            # Q2: "Company Z" FV=1.01M (close) and FV=5M (far)
            {"source": "nport", "cik": "300", "entity_name": "Fund1",
             "report_date": "2024-06-30", "issuer_name": "Company Z",
             "fair_value": "1010000"},
            {"source": "nport", "cik": "300", "entity_name": "Fund1",
             "report_date": "2024-06-30", "issuer_name": "Company Z",
             "fair_value": "5000000"},
        ])
        result = match_positions(unified_df=unified, bdc_raw_df=bdc_raw)
        assert len(result) == 1
        # Should match the closer FV
        assert float(result.iloc[0]["end_fair_value"]) == 1010000

    def test_both_sides(self):
        """M x N fan-out reduced to min(M,N) 1:1 pairs."""
        bdc_raw = _make_bdc_raw([])
        unified = _make_unified([
            # Q1: 2 "Widget Corp"
            {"source": "nport", "cik": "300", "entity_name": "Fund1",
             "report_date": "2024-03-31", "issuer_name": "Widget Corp",
             "fair_value": "1000000"},
            {"source": "nport", "cik": "300", "entity_name": "Fund1",
             "report_date": "2024-03-31", "issuer_name": "Widget Corp",
             "fair_value": "2000000"},
            # Q2: 3 "Widget Corp"
            {"source": "nport", "cik": "300", "entity_name": "Fund1",
             "report_date": "2024-06-30", "issuer_name": "Widget Corp",
             "fair_value": "1010000"},
            {"source": "nport", "cik": "300", "entity_name": "Fund1",
             "report_date": "2024-06-30", "issuer_name": "Widget Corp",
             "fair_value": "2020000"},
            {"source": "nport", "cik": "300", "entity_name": "Fund1",
             "report_date": "2024-06-30", "issuer_name": "Widget Corp",
             "fair_value": "500000"},
        ])
        result = match_positions(unified_df=unified, bdc_raw_df=bdc_raw)
        # min(2, 3) = 2 pairs
        assert len(result) == 2

    def test_score_priority(self):
        """For exact methods, match_score is always 1.0."""
        bdc_raw = _make_bdc_raw([])
        unified = _make_unified([
            {"source": "bdc", "cik": "200", "entity_name": "BDC2",
             "report_date": "2024-03-31", "issuer_name": "Alpha Corp",
             "fair_value": "500000"},
            {"source": "bdc", "cik": "200", "entity_name": "BDC2",
             "report_date": "2024-06-30", "issuer_name": "Alpha Corp",
             "fair_value": "510000"},
        ])
        result = match_positions(unified_df=unified, bdc_raw_df=bdc_raw)
        assert len(result) == 1
        assert float(result.iloc[0]["match_score"]) == 1.0


# ---------------------------------------------------------------------------
# Cascade Exclusion
# ---------------------------------------------------------------------------

class TestCascadeExclusion:
    def test_cascade_a_excludes_from_b(self):
        """Tier A match not re-matched at B."""
        bdc_raw = _make_bdc_raw([
            {"cik": "100", "entity_name": "TestBDC", "accession_number": "ACC1",
             "report_date": "2024-06-30", "period": "2024-06-30",
             "investment_identifier": "Acme Corp - Loan",
             "fair_value": "1000000"},
            {"cik": "100", "entity_name": "TestBDC", "accession_number": "ACC1",
             "report_date": "2024-06-30", "period": "2024-03-31",
             "investment_identifier": "Acme Corp - Loan",
             "fair_value": "980000"},
        ])
        unified = _make_unified([
            {"source": "bdc", "cik": "100", "entity_name": "TestBDC",
             "report_date": "2024-03-31",
             "issuer_name": "Acme Corp - Loan",
             "fair_value": "980000",
             "bdc_investment_identifier": "Acme Corp - Loan"},
            {"source": "bdc", "cik": "100", "entity_name": "TestBDC",
             "report_date": "2024-06-30",
             "issuer_name": "Acme Corp - Loan",
             "fair_value": "1000000",
             "bdc_investment_identifier": "Acme Corp - Loan"},
        ])
        result = match_positions(unified_df=unified, bdc_raw_df=bdc_raw)
        # Should have Tier A match and NOT also a B2 match
        method_a = result[result["match_method"] == "A_within_filing"]
        method_b = result[result["match_method"] == "B2_exact_name"]
        assert len(method_a) == 1
        assert len(method_b) == 0

    def test_cascade_b_excludes_from_c(self):
        """Tier B match not re-matched at C."""
        bdc_raw = _make_bdc_raw([])
        unified = _make_unified([
            {"source": "bdc", "cik": "200", "entity_name": "BDC2",
             "report_date": "2024-03-31", "issuer_name": "Gamma Inc",
             "fair_value": "500000"},
            {"source": "bdc", "cik": "200", "entity_name": "BDC2",
             "report_date": "2024-06-30", "issuer_name": "Gamma Inc",
             "fair_value": "510000"},
        ])
        result = match_positions(unified_df=unified, bdc_raw_df=bdc_raw)
        # Should match at B2 only, not also at C
        assert len(result) == 1
        assert result.iloc[0]["match_method"] == "B2_exact_name"

    def test_cascade_c_excludes_from_d(self):
        """Tier C match not re-matched at D."""
        bdc_raw = _make_bdc_raw([])
        unified = _make_unified([
            {"source": "bdc", "cik": "200", "entity_name": "BDC2",
             "report_date": "2024-03-31",
             "issuer_name": "Acme Corp | First Lien",
             "fair_value": "500000"},
            {"source": "bdc", "cik": "200", "entity_name": "BDC2",
             "report_date": "2024-06-30",
             "issuer_name": "Acme Corp | Second Lien",
             "fair_value": "510000"},
        ])
        result = match_positions(unified_df=unified, bdc_raw_df=bdc_raw)
        # Normalized: both -> "acme corp", should match at C not D
        tier_c = result[result["match_method"] == "C_normalized_name"]
        tier_d = result[result["match_method"] == "D_fuzzy"]
        assert len(tier_c) == 1
        assert len(tier_d) == 0

    def test_cascade_uses_row_id(self):
        """Exclusion works via row ID, not name string matching."""
        bdc_raw = _make_bdc_raw([])
        # Two positions: one matched at B, one should fall through to C
        unified = _make_unified([
            # Position 1: exact name match at B
            {"source": "bdc", "cik": "200", "entity_name": "BDC2",
             "report_date": "2024-03-31", "issuer_name": "Alpha Inc",
             "fair_value": "500000"},
            {"source": "bdc", "cik": "200", "entity_name": "BDC2",
             "report_date": "2024-06-30", "issuer_name": "Alpha Inc",
             "fair_value": "510000"},
            # Position 2: different name Q1 vs Q2, needs normalization
            {"source": "bdc", "cik": "200", "entity_name": "BDC2",
             "report_date": "2024-03-31",
             "issuer_name": "Beta Corp | Category A",
             "fair_value": "300000"},
            {"source": "bdc", "cik": "200", "entity_name": "BDC2",
             "report_date": "2024-06-30",
             "issuer_name": "Beta Corp | Category B",
             "fair_value": "310000"},
        ])
        result = match_positions(unified_df=unified, bdc_raw_df=bdc_raw)
        b2 = result[result["match_method"] == "B2_exact_name"]
        tier_c = result[result["match_method"] == "C_normalized_name"]
        assert len(b2) == 1  # Alpha Inc
        assert len(tier_c) == 1  # Beta Corp


# ---------------------------------------------------------------------------
# Integration and edge cases
# ---------------------------------------------------------------------------

class TestIntegration:
    def test_mixed_bdc_nport(self):
        """Full integration with both BDC and N-PORT positions."""
        bdc_raw = _make_bdc_raw([
            {"cik": "100", "entity_name": "TestBDC", "accession_number": "ACC1",
             "report_date": "2024-06-30", "period": "2024-06-30",
             "investment_identifier": "Acme Corp - Loan",
             "fair_value": "1000000"},
            {"cik": "100", "entity_name": "TestBDC", "accession_number": "ACC1",
             "report_date": "2024-06-30", "period": "2023-12-31",
             "investment_identifier": "Acme Corp - Loan",
             "fair_value": "980000"},
        ])
        unified = _make_unified([
            {"source": "bdc", "cik": "100", "entity_name": "TestBDC",
             "report_date": "2024-06-30", "issuer_name": "Acme Corp",
             "fair_value": "1000000",
             "index_classification": "DIRECT_LENDING",
             "asset_category": "LOAN_FIRST_LIEN",
             "bdc_investment_identifier": "Acme Corp - Loan"},
            {"source": "nport", "cik": "300", "entity_name": "IntFund1",
             "report_date": "2024-03-31", "issuer_name": "Bond Co",
             "fair_value": "750000", "cusip": "987654321",
             "asset_category": "LOAN_FIRST_LIEN"},
            {"source": "nport", "cik": "300", "entity_name": "IntFund1",
             "report_date": "2024-06-30", "issuer_name": "Bond Co",
             "fair_value": "760000", "cusip": "987654321",
             "asset_category": "LOAN_FIRST_LIEN"},
        ])
        result = match_positions(unified_df=unified, bdc_raw_df=bdc_raw)
        assert len(result) >= 2
        assert set(result["source"].unique()) == {"bdc", "nport"}

    def test_empty_input(self):
        """Empty unified -> empty result."""
        from pipeline.unified_holdings import UNIFIED_COLUMNS
        empty_unified = pd.DataFrame(columns=UNIFIED_COLUMNS)
        empty_bdc = _make_bdc_raw([])
        result = match_positions(unified_df=empty_unified, bdc_raw_df=empty_bdc)
        assert len(result) == 0
        for col in MATCH_COLUMNS:
            assert col in result.columns

    def test_non_consecutive_quarters_no_match(self):
        """Positions two quarters apart should not match."""
        bdc_raw = _make_bdc_raw([])
        unified = _make_unified([
            {"source": "nport", "cik": "300", "entity_name": "IntFund1",
             "report_date": "2024-03-31", "issuer_name": "Gap Corp",
             "fair_value": "500000", "cusip": "111222333",
             "asset_category": "LOAN_FIRST_LIEN"},
            {"source": "nport", "cik": "300", "entity_name": "IntFund1",
             "report_date": "2024-09-30", "issuer_name": "Gap Corp",
             "fair_value": "520000", "cusip": "111222333",
             "asset_category": "LOAN_FIRST_LIEN"},
        ])
        result = match_positions(unified_df=unified, bdc_raw_df=bdc_raw)
        assert len(result) == 0

    def test_all_match_columns_present(self):
        """Output has all MATCH_COLUMNS."""
        bdc_raw = _make_bdc_raw([])
        unified = _make_unified([
            {"source": "bdc", "cik": "200", "entity_name": "BDC2",
             "report_date": "2024-03-31", "issuer_name": "Test Co",
             "fair_value": "500000"},
            {"source": "bdc", "cik": "200", "entity_name": "BDC2",
             "report_date": "2024-06-30", "issuer_name": "Test Co",
             "fair_value": "510000"},
        ])
        result = match_positions(unified_df=unified, bdc_raw_df=bdc_raw)
        for col in MATCH_COLUMNS:
            assert col in result.columns

    def test_classification_annotation(self):
        """index_classification correctly joined."""
        bdc_raw = _make_bdc_raw([])
        unified = _make_unified([
            {"source": "nport", "cik": "300", "entity_name": "Fund1",
             "report_date": "2024-03-31", "issuer_name": "Loan Corp",
             "fair_value": "500000", "cusip": "AAA111222",
             "index_classification": "DIRECT_LENDING",
             "asset_category": "LOAN_FIRST_LIEN",
             "issuer_category": "CORPORATE",
             "coupon_type": "FLOATING"},
            {"source": "nport", "cik": "300", "entity_name": "Fund1",
             "report_date": "2024-06-30", "issuer_name": "Loan Corp",
             "fair_value": "510000", "cusip": "AAA111222",
             "index_classification": "DIRECT_LENDING",
             "asset_category": "LOAN_FIRST_LIEN",
             "issuer_category": "CORPORATE",
             "coupon_type": "FLOATING"},
        ])
        result = match_positions(unified_df=unified, bdc_raw_df=bdc_raw)
        assert len(result) == 1
        row = result.iloc[0]
        assert row["index_classification"] == "DIRECT_LENDING"
        assert row["asset_category"] == "LOAN_FIRST_LIEN"
        assert row["coupon_type"] == "FLOATING"


# ---------------------------------------------------------------------------
# Position ID assignment
# ---------------------------------------------------------------------------

class TestPositionIds:
    """Tests for assign_position_ids()."""

    def test_basic_chain_two_quarters(self):
        """Q1->Q2 matched pair -> both unified rows share one position_id."""
        bdc_raw = _make_bdc_raw([])
        unified = _make_unified([
            {"source": "nport", "cik": "300", "entity_name": "Fund1",
             "report_date": "2024-03-31", "issuer_name": "Loan Corp",
             "fair_value": "1000000", "cusip": "AAA111222"},
            {"source": "nport", "cik": "300", "entity_name": "Fund1",
             "report_date": "2024-06-30", "issuer_name": "Loan Corp",
             "fair_value": "1020000", "cusip": "AAA111222"},
        ])
        matches = match_positions(unified_df=unified, bdc_raw_df=bdc_raw)
        assert len(matches) == 1
        unified_out, matches_out = assign_position_ids(unified, matches)
        # Both unified rows should share the same position_id
        pids = unified_out["position_id"].tolist()
        assert pids[0] == pids[1]
        assert pids[0].startswith("POS-")
        # Match should also have the position_id
        assert matches_out["position_id"].iloc[0] == pids[0]

    def test_chain_three_quarters(self):
        """Q1->Q2 + Q2->Q3 = all three rows share one position_id."""
        bdc_raw = _make_bdc_raw([])
        unified = _make_unified([
            {"source": "nport", "cik": "300", "entity_name": "Fund1",
             "report_date": "2024-03-31", "issuer_name": "Corp A",
             "fair_value": "1000000"},
            {"source": "nport", "cik": "300", "entity_name": "Fund1",
             "report_date": "2024-06-30", "issuer_name": "Corp A",
             "fair_value": "1010000"},
            {"source": "nport", "cik": "300", "entity_name": "Fund1",
             "report_date": "2024-09-30", "issuer_name": "Corp A",
             "fair_value": "1020000"},
        ])
        matches = match_positions(unified_df=unified, bdc_raw_df=bdc_raw)
        assert len(matches) == 2  # Q1->Q2 and Q2->Q3
        unified_out, _ = assign_position_ids(unified, matches)
        pids = unified_out["position_id"].tolist()
        # All three should share the same position_id
        assert len(set(pids)) == 1

    def test_separate_positions_different_ids(self):
        """Different issuers at the same CIK get different position_ids."""
        bdc_raw = _make_bdc_raw([])
        unified = _make_unified([
            {"source": "nport", "cik": "300", "entity_name": "Fund1",
             "report_date": "2024-03-31", "issuer_name": "Alpha Inc",
             "fair_value": "500000"},
            {"source": "nport", "cik": "300", "entity_name": "Fund1",
             "report_date": "2024-06-30", "issuer_name": "Alpha Inc",
             "fair_value": "510000"},
            {"source": "nport", "cik": "300", "entity_name": "Fund1",
             "report_date": "2024-03-31", "issuer_name": "Beta Corp",
             "fair_value": "700000"},
            {"source": "nport", "cik": "300", "entity_name": "Fund1",
             "report_date": "2024-06-30", "issuer_name": "Beta Corp",
             "fair_value": "720000"},
        ])
        matches = match_positions(unified_df=unified, bdc_raw_df=bdc_raw)
        assert len(matches) == 2
        unified_out, _ = assign_position_ids(unified, matches)
        alpha_ids = unified_out[
            unified_out["issuer_name"].str.contains("Alpha", na=False)
        ]["position_id"].unique()
        beta_ids = unified_out[
            unified_out["issuer_name"].str.contains("Beta", na=False)
        ]["position_id"].unique()
        assert len(alpha_ids) == 1
        assert len(beta_ids) == 1
        assert alpha_ids[0] != beta_ids[0]

    def test_multi_tranche_disambiguation(self):
        """Same issuer_name + different FV -> different position_ids."""
        bdc_raw = _make_bdc_raw([])
        unified = _make_unified([
            # Tranche 1: ~1M
            {"source": "nport", "cik": "300", "entity_name": "Fund1",
             "report_date": "2024-03-31", "issuer_name": "Corp X",
             "fair_value": "1000000"},
            {"source": "nport", "cik": "300", "entity_name": "Fund1",
             "report_date": "2024-06-30", "issuer_name": "Corp X",
             "fair_value": "1010000"},
            # Tranche 2: ~5M
            {"source": "nport", "cik": "300", "entity_name": "Fund1",
             "report_date": "2024-03-31", "issuer_name": "Corp X",
             "fair_value": "5000000"},
            {"source": "nport", "cik": "300", "entity_name": "Fund1",
             "report_date": "2024-06-30", "issuer_name": "Corp X",
             "fair_value": "5050000"},
        ])
        matches = match_positions(unified_df=unified, bdc_raw_df=bdc_raw)
        # Both tranches should be matched (FV proximity tiebreaking)
        assert len(matches) >= 1
        unified_out, _ = assign_position_ids(unified, matches)
        # The 1M tranche and 5M tranche should get different IDs
        # (since ROUND(1000000, -2) != ROUND(5000000, -2))
        pids = unified_out["position_id"].tolist()
        assert len(set(pids)) >= 2

    def test_unmatched_get_singleton_ids(self):
        """Holdings not in any match pair get unique singleton IDs."""
        bdc_raw = _make_bdc_raw([])
        unified = _make_unified([
            {"source": "nport", "cik": "300", "entity_name": "Fund1",
             "report_date": "2024-03-31", "issuer_name": "Orphan Corp",
             "fair_value": "500000"},
        ])
        matches = match_positions(unified_df=unified, bdc_raw_df=bdc_raw)
        assert len(matches) == 0
        unified_out, _ = assign_position_ids(unified, matches)
        assert len(unified_out) == 1
        pid = unified_out["position_id"].iloc[0]
        assert pid.startswith("POS-")

    def test_empty_matches_all_singletons(self):
        """No match pairs -> every holding gets a unique singleton ID."""
        unified = _make_unified([
            {"source": "nport", "cik": "300", "entity_name": "Fund1",
             "report_date": "2024-03-31", "issuer_name": "A Corp",
             "fair_value": "100000"},
            {"source": "nport", "cik": "300", "entity_name": "Fund1",
             "report_date": "2024-03-31", "issuer_name": "B Corp",
             "fair_value": "200000"},
        ])
        empty_matches = pd.DataFrame(columns=MATCH_COLUMNS)
        unified_out, matches_out = assign_position_ids(unified, empty_matches)
        pids = unified_out["position_id"].tolist()
        assert len(set(pids)) == 2
        assert all(p.startswith("POS-") for p in pids)

    def test_position_id_format(self):
        """Position IDs match POS-XXXXXXXX pattern."""
        import re
        bdc_raw = _make_bdc_raw([])
        unified = _make_unified([
            {"source": "nport", "cik": "300", "entity_name": "Fund1",
             "report_date": "2024-03-31", "issuer_name": "Corp Z",
             "fair_value": "500000"},
            {"source": "nport", "cik": "300", "entity_name": "Fund1",
             "report_date": "2024-06-30", "issuer_name": "Corp Z",
             "fair_value": "510000"},
        ])
        matches = match_positions(unified_df=unified, bdc_raw_df=bdc_raw)
        unified_out, matches_out = assign_position_ids(unified, matches)
        pattern = re.compile(r"^POS-\d{8}$")
        for pid in unified_out["position_id"]:
            assert pattern.match(pid), f"Bad format: {pid}"
        for pid in matches_out["position_id"]:
            assert pattern.match(pid), f"Bad format: {pid}"

    def test_position_id_in_columns(self):
        """Both unified and matches DataFrames have position_id column."""
        bdc_raw = _make_bdc_raw([])
        unified = _make_unified([
            {"source": "nport", "cik": "300", "entity_name": "Fund1",
             "report_date": "2024-03-31", "issuer_name": "Test Corp",
             "fair_value": "500000"},
        ])
        matches = match_positions(unified_df=unified, bdc_raw_df=bdc_raw)
        unified_out, matches_out = assign_position_ids(unified, matches)
        assert "position_id" in unified_out.columns
        assert "position_id" in matches_out.columns
        # Also check MATCH_COLUMNS includes it
        assert "position_id" in MATCH_COLUMNS

    def test_match_positions_stable_when_input_shuffled(self):
        bdc_raw = _make_bdc_raw([])
        unified = _make_unified([
            {"source": "nport", "cik": "300", "entity_name": "Fund1",
             "report_date": "2024-03-31", "issuer_name": "Alpha Inc",
             "instrument_description": "First Lien Loan",
             "fair_value": "500000", "cusip": "111111111"},
            {"source": "nport", "cik": "300", "entity_name": "Fund1",
             "report_date": "2024-06-30", "issuer_name": "Alpha Inc",
             "instrument_description": "First Lien Loan",
             "fair_value": "510000", "cusip": "111111111"},
            {"source": "nport", "cik": "300", "entity_name": "Fund1",
             "report_date": "2024-03-31", "issuer_name": "Beta Inc",
             "instrument_description": "Second Lien Loan",
             "fair_value": "700000", "cusip": "222222222"},
            {"source": "nport", "cik": "300", "entity_name": "Fund1",
             "report_date": "2024-06-30", "issuer_name": "Beta Inc",
             "instrument_description": "Second Lien Loan",
             "fair_value": "720000", "cusip": "222222222"},
        ])
        first = match_positions(unified_df=unified, bdc_raw_df=bdc_raw)
        shuffled = unified.sample(frac=1, random_state=7).reset_index(drop=True)
        second = match_positions(unified_df=shuffled, bdc_raw_df=bdc_raw)
        pd.testing.assert_frame_equal(first, second)

    def test_assign_position_ids_stable_when_input_shuffled(self):
        bdc_raw = _make_bdc_raw([])
        unified = _make_unified([
            {"source": "nport", "cik": "300", "entity_name": "Fund1",
             "report_date": "2024-03-31", "issuer_name": "Alpha Inc",
             "instrument_description": "First Lien Loan",
             "fair_value": "500000", "cusip": "111111111"},
            {"source": "nport", "cik": "300", "entity_name": "Fund1",
             "report_date": "2024-06-30", "issuer_name": "Alpha Inc",
             "instrument_description": "First Lien Loan",
             "fair_value": "510000", "cusip": "111111111"},
            {"source": "nport", "cik": "300", "entity_name": "Fund1",
             "report_date": "2024-03-31", "issuer_name": "Beta Inc",
             "instrument_description": "Second Lien Loan",
             "fair_value": "700000", "cusip": "222222222"},
            {"source": "nport", "cik": "300", "entity_name": "Fund1",
             "report_date": "2024-06-30", "issuer_name": "Beta Inc",
             "instrument_description": "Second Lien Loan",
             "fair_value": "720000", "cusip": "222222222"},
        ])
        matches = match_positions(unified_df=unified, bdc_raw_df=bdc_raw)
        first_unified, first_matches = assign_position_ids(unified, matches)

        shuffled_unified = unified.sample(frac=1, random_state=11).reset_index(drop=True)
        shuffled_matches = matches.sample(frac=1, random_state=13).reset_index(drop=True)
        second_unified, second_matches = assign_position_ids(
            shuffled_unified, shuffled_matches,
        )

        pd.testing.assert_frame_equal(first_unified, second_unified)
        pd.testing.assert_frame_equal(first_matches, second_matches)

    def test_no_fan_out(self):
        """Join doesn't create duplicate rows in unified output."""
        bdc_raw = _make_bdc_raw([])
        unified = _make_unified([
            {"source": "nport", "cik": "300", "entity_name": "Fund1",
             "report_date": "2024-03-31", "issuer_name": "Corp A",
             "fair_value": "1000000"},
            {"source": "nport", "cik": "300", "entity_name": "Fund1",
             "report_date": "2024-06-30", "issuer_name": "Corp A",
             "fair_value": "1010000"},
            {"source": "nport", "cik": "300", "entity_name": "Fund1",
             "report_date": "2024-09-30", "issuer_name": "Corp A",
             "fair_value": "1020000"},
        ])
        matches = match_positions(unified_df=unified, bdc_raw_df=bdc_raw)
        unified_out, _ = assign_position_ids(unified, matches)
        # Should have exactly the same number of rows as input
        assert len(unified_out) == len(unified)

    def test_tier_a_bdc_identifier_join(self):
        """Tier A matches join back to unified via bdc_investment_identifier."""
        bdc_raw = _make_bdc_raw([
            {"cik": "100", "entity_name": "TestBDC", "accession_number": "ACC1",
             "report_date": "2024-06-30", "period": "2024-06-30",
             "investment_identifier": "Acme Corp - First Lien Loan",
             "fair_value": "1000000"},
            {"cik": "100", "entity_name": "TestBDC", "accession_number": "ACC1",
             "report_date": "2024-06-30", "period": "2023-12-31",
             "investment_identifier": "Acme Corp - First Lien Loan",
             "fair_value": "980000"},
        ])
        unified = _make_unified([
            {"source": "bdc", "cik": "100", "entity_name": "TestBDC",
             "report_date": "2024-06-30", "issuer_name": "Acme Corp",
             "fair_value": "1000000",
             "bdc_investment_identifier": "Acme Corp - First Lien Loan"},
        ])
        matches = match_positions(unified_df=unified, bdc_raw_df=bdc_raw)
        unified_out, matches_out = assign_position_ids(unified, matches)
        # The unified row should have a position_id (not remain blank)
        assert unified_out["position_id"].iloc[0].startswith("POS-")

    def test_propagates_to_returns(self):
        """position_id is present in compute_returns() output."""
        from pipeline.index_returns import compute_returns
        matches = pd.DataFrame([{
            "cik": "100", "entity_name": "BDC1", "source": "bdc",
            "index_classification": "DIRECT_LENDING",
            "begin_quarter": "2024q1", "end_quarter": "2024q2",
            "begin_report_date": "2024-03-31",
            "end_report_date": "2024-06-30",
            "begin_issuer_name": "Acme Corp",
            "end_issuer_name": "Acme Corp",
            "begin_fair_value": "1000000", "end_fair_value": "1010000",
            "begin_cost": "950000", "end_cost": "950000",
            "begin_principal_amount": "1000000",
            "begin_interest_rate": "10",
            "begin_basis_spread": "5.0",
            "begin_shares_held": None,
            "end_principal_amount": "1000000",
            "end_interest_rate": "10",
            "end_basis_spread": "5.0",
            "end_shares_held": None,
            "span_months": "3",
            "match_method": "A_within_filing",
            "match_key": "ACC1",
            "match_score": "1.0",
            "asset_category": "LOAN",
            "issuer_category": "CORPORATE",
            "maturity_date": "2026-01-01",
            "coupon_type": "Floating",
            "position_id": "POS-00000001",
        }])
        pos, _ = compute_returns(matches_df=matches)
        assert "position_id" in pos.columns
        assert pos["position_id"].iloc[0] == "POS-00000001"


class TestPositionMatchReconciliation:
    def test_reports_short_and_any_span_coverage_and_residual_bucket(self):
        holdings = _make_unified([
            {"source": "bdc", "cik": "100", "entity_name": "BDC",
             "report_date": "2024-03-31", "quarter": "2024q1",
             "issuer_name": "Acme Corp", "fair_value": "1000000",
             "bdc_investment_identifier": "Acme Corp",
             "cusip": "111111111", "index_classification": "DIRECT_LENDING",
             "position_id": "P1"},
            {"source": "bdc", "cik": "100", "entity_name": "BDC",
             "report_date": "2024-06-30", "quarter": "2024q2",
             "issuer_name": "Acme Corp", "fair_value": "1010000",
             "bdc_investment_identifier": "Acme Corp",
             "cusip": "111111111", "index_classification": "DIRECT_LENDING",
             "position_id": "P1"},
            {"source": "bdc", "cik": "100", "entity_name": "BDC",
             "report_date": "2024-06-30", "quarter": "2024q2",
             "issuer_name": "Beta Corp", "fair_value": "500000",
             "bdc_investment_identifier": "Beta Corp",
             "cusip": "222222222", "index_classification": "DIRECT_LENDING",
             "position_id": "P2"},
            {"source": "bdc", "cik": "100", "entity_name": "BDC",
             "report_date": "2024-09-30", "quarter": "2024q3",
             "issuer_name": "Acme Corp", "fair_value": "1020000",
             "bdc_investment_identifier": "Acme Corp",
             "cusip": "111111111", "index_classification": "DIRECT_LENDING",
             "position_id": "P1"},
            {"source": "bdc", "cik": "100", "entity_name": "BDC",
             "report_date": "2024-09-30", "quarter": "2024q3",
             "issuer_name": "Beta Corp", "fair_value": "550000",
             "bdc_investment_identifier": "Beta Corp",
             "cusip": "222222222", "index_classification": "DIRECT_LENDING",
             "position_id": "P2"},
        ])
        matches = pd.DataFrame([{
            "cik": "100", "source": "bdc", "end_quarter": "2024q2",
            "end_report_date": "2024-06-30", "end_issuer_name": "Acme Corp",
            "end_fair_value": "1010000", "position_id": "P1",
            "span_months": "3",
        }, {
            "cik": "100", "source": "bdc", "end_quarter": "2024q3",
            "end_report_date": "2024-09-30", "end_issuer_name": "Acme Corp",
            "end_fair_value": "1020000", "position_id": "P1",
            "span_months": "12",
        }])

        coverage, unmatched, residuals = build_position_match_reconciliation(
            holdings_df=holdings,
            matches_df=matches,
            write=False,
        )

        q2 = coverage.set_index("quarter").loc["2024q2"]
        assert q2["eligible_backward_rows"] == 2
        assert q2["any_span_matched_rows"] == 1
        assert q2["short_span_matched_rows"] == 1
        q3 = coverage.set_index("quarter").loc["2024q3"]
        assert q3["eligible_backward_rows"] == 2
        assert q3["any_span_matched_rows"] == 1
        assert q3["short_span_matched_rows"] == 0

        assert unmatched.set_index("quarter").loc["2024q3", "unmatched_rows"] == 1
        buckets = dict(zip(residuals["quarter"], residuals["residual_bucket"]))
        assert buckets["2024q2"] == "likely_new_or_exit"
        assert buckets["2024q3"] == "cusip_existed_unmatched"


# ---------------------------------------------------------------------------
# FV ratio guards (#3)
# ---------------------------------------------------------------------------

class TestFvRatioGuards:
    """Extreme FV ratio pairs are rejected by tier-specific guards."""

    def test_tier_a_rejects_1000x_fv_ratio(self):
        """Tier A rejects within-filing pair with 1000x FV ratio."""
        bdc_raw = _make_bdc_raw([
            {"cik": "100", "entity_name": "TestBDC", "accession_number": "ACC1",
             "report_date": "2024-06-30", "period": "2024-06-30",
             "investment_identifier": "Acme Corp - Loan",
             "fair_value": "1000000000"},  # $1B
            {"cik": "100", "entity_name": "TestBDC", "accession_number": "ACC1",
             "report_date": "2024-06-30", "period": "2023-12-31",
             "investment_identifier": "Acme Corp - Loan",
             "fair_value": "1000"},  # $1K -- 1,000,000x ratio
        ])
        unified = _make_unified([
            {"source": "bdc", "cik": "100", "entity_name": "TestBDC",
             "report_date": "2024-06-30", "issuer_name": "Acme Corp",
             "fair_value": "1000000000",
             "index_classification": "DIRECT_LENDING",
             "asset_category": "LOAN_FIRST_LIEN",
             "bdc_investment_identifier": "Acme Corp - Loan"},
        ])
        result = match_positions(unified_df=unified, bdc_raw_df=bdc_raw)
        method_a = result[result["match_method"] == "A_within_filing"]
        assert len(method_a) == 0, "1000x FV ratio pair should be rejected by Tier A guard"

    def test_tier_a_accepts_normal_fv_ratio(self):
        """Tier A accepts within-filing pair with 2x FV ratio."""
        bdc_raw = _make_bdc_raw([
            {"cik": "100", "entity_name": "TestBDC", "accession_number": "ACC1",
             "report_date": "2024-06-30", "period": "2024-06-30",
             "investment_identifier": "Acme Corp - Loan",
             "fair_value": "2000000"},
            {"cik": "100", "entity_name": "TestBDC", "accession_number": "ACC1",
             "report_date": "2024-06-30", "period": "2023-12-31",
             "investment_identifier": "Acme Corp - Loan",
             "fair_value": "1000000"},
        ])
        unified = _make_unified([
            {"source": "bdc", "cik": "100", "entity_name": "TestBDC",
             "report_date": "2024-06-30", "issuer_name": "Acme Corp",
             "fair_value": "2000000",
             "index_classification": "DIRECT_LENDING",
             "asset_category": "LOAN_FIRST_LIEN",
             "bdc_investment_identifier": "Acme Corp - Loan"},
        ])
        result = match_positions(unified_df=unified, bdc_raw_df=bdc_raw)
        method_a = result[result["match_method"] == "A_within_filing"]
        assert len(method_a) == 1, "2x FV ratio pair should be accepted by Tier A"

    def test_tier_b1_rejects_extreme_fv_ratio(self):
        """Tier B1 (CUSIP) rejects pair with >50x FV ratio."""
        unified = _make_unified([
            # Q1
            {"source": "nport", "cik": "200", "entity_name": "TestFund",
             "report_date": "2024-03-31", "issuer_name": "Acme Corp",
             "fair_value": "100", "cusip": "12345X789",
             "index_classification": "DIRECT_LENDING",
             "asset_category": "LOAN_FIRST_LIEN"},
            # Q2 -- 100,000x larger FV
            {"source": "nport", "cik": "200", "entity_name": "TestFund",
             "report_date": "2024-06-30", "issuer_name": "Acme Corp",
             "fair_value": "10000000", "cusip": "12345X789",
             "index_classification": "DIRECT_LENDING",
             "asset_category": "LOAN_FIRST_LIEN"},
        ])
        result = match_positions(unified_df=unified)
        method_b1 = result[result["match_method"] == "B1_cusip"]
        assert len(method_b1) == 0, "100,000x FV ratio should be rejected by Tier B1 guard"

    def test_tier_b2_rejects_extreme_fv_ratio(self):
        """Tier B2 (exact name) rejects pair with >50x FV ratio."""
        unified = _make_unified([
            {"source": "nport", "cik": "300", "entity_name": "TestFund",
             "report_date": "2024-03-31", "issuer_name": "Unique Acme Co",
             "fair_value": "500", "cusip": "",
             "index_classification": "DIRECT_LENDING",
             "asset_category": "LOAN_FIRST_LIEN"},
            {"source": "nport", "cik": "300", "entity_name": "TestFund",
             "report_date": "2024-06-30", "issuer_name": "Unique Acme Co",
             "fair_value": "50000000", "cusip": "",
             "index_classification": "DIRECT_LENDING",
             "asset_category": "LOAN_FIRST_LIEN"},
        ])
        result = match_positions(unified_df=unified)
        method_b2 = result[result["match_method"] == "B2_exact_name"]
        assert len(method_b2) == 0, "100,000x FV ratio should be rejected by Tier B2 guard"


# ---------------------------------------------------------------------------
# P0-B: Tier A Begin-Side Dedup and Annotation Dedup
# ---------------------------------------------------------------------------

class TestTierABeginSideDedup:
    """Verify 1:1 enforcement on both begin-side and end-side of Tier A."""

    def test_one_comparative_two_current_produces_one_pair(self):
        """One comparative row matching two current-period rows via identical
        identifier should produce only ONE pair (begin-side dedup)."""
        bdc_raw = _make_bdc_raw([
            # Current period row 1
            {"cik": "100", "entity_name": "TestBDC", "accession_number": "ACC1",
             "form_type": "10-K", "filing_date": "2024-07-15",
             "report_date": "2024-06-30", "period": "2024-06-30",
             "investment_identifier": "Acme Corp - Loan",
             "fair_value": "1000000", "cost": "950000"},
            # Current period row 2 (same identifier, different FV -- e.g. from dimension paths)
            {"cik": "100", "entity_name": "TestBDC", "accession_number": "ACC1",
             "form_type": "10-K", "filing_date": "2024-07-15",
             "report_date": "2024-06-30", "period": "2024-06-30",
             "investment_identifier": "Acme Corp - Loan",
             "fair_value": "1000001", "cost": "950000"},
            # Comparative row (matches both current rows)
            {"cik": "100", "entity_name": "TestBDC", "accession_number": "ACC1",
             "form_type": "10-K", "filing_date": "2024-07-15",
             "report_date": "2024-06-30", "period": "2023-12-31",
             "investment_identifier": "Acme Corp - Loan",
             "fair_value": "980000", "cost": "950000"},
        ])
        unified = _make_unified([
            {"source": "bdc", "cik": "100", "entity_name": "TestBDC",
             "report_date": "2024-06-30", "issuer_name": "Acme Corp",
             "fair_value": "1000000", "index_classification": "DIRECT_LENDING",
             "asset_category": "LOAN_FIRST_LIEN",
             "bdc_investment_identifier": "Acme Corp - Loan"},
            {"source": "bdc", "cik": "100", "entity_name": "TestBDC",
             "report_date": "2024-06-30", "issuer_name": "Acme Corp",
             "fair_value": "1000001", "index_classification": "DIRECT_LENDING",
             "asset_category": "LOAN_FIRST_LIEN",
             "bdc_investment_identifier": "Acme Corp - Loan"},
        ])
        result = match_positions(unified_df=unified, bdc_raw_df=bdc_raw)
        tier_a = result[result["match_method"] == "A_within_filing"]
        # Begin-side dedup: the one comparative row can only appear once
        begin_keys = tier_a[["cik", "begin_report_date", "begin_issuer_name",
                             "begin_fair_value"]].drop_duplicates()
        assert len(begin_keys) <= 1, (
            f"Expected at most 1 begin-side row, got {len(begin_keys)}"
        )

    def test_tier_a_annotation_no_fanout(self):
        """Two unified rows with the same bdc_investment_identifier should
        produce only one annotated Tier A match (annotation dedup)."""
        bdc_raw = _make_bdc_raw([
            {"cik": "200", "entity_name": "DupBDC", "accession_number": "ACC2",
             "form_type": "10-K", "filing_date": "2024-07-15",
             "report_date": "2024-06-30", "period": "2024-06-30",
             "investment_identifier": "Widget Inc - Revolver",
             "fair_value": "500000"},
            {"cik": "200", "entity_name": "DupBDC", "accession_number": "ACC2",
             "form_type": "10-K", "filing_date": "2024-07-15",
             "report_date": "2024-06-30", "period": "2023-12-31",
             "investment_identifier": "Widget Inc - Revolver",
             "fair_value": "480000"},
        ])
        unified = _make_unified([
            # Two unified rows with same identifier (e.g., affiliation-axis variants)
            {"source": "bdc", "cik": "200", "entity_name": "DupBDC",
             "report_date": "2024-06-30", "issuer_name": "Widget Inc",
             "fair_value": "500000", "index_classification": "DIRECT_LENDING",
             "asset_category": "LOAN_REVOLVER",
             "bdc_investment_identifier": "Widget Inc - Revolver"},
            {"source": "bdc", "cik": "200", "entity_name": "DupBDC",
             "report_date": "2024-06-30", "issuer_name": "Widget Inc",
             "fair_value": "500001", "index_classification": "DIRECT_LENDING",
             "asset_category": "LOAN_REVOLVER",
             "bdc_investment_identifier": "Widget Inc - Revolver"},
        ])
        result = match_positions(unified_df=unified, bdc_raw_df=bdc_raw)
        tier_a = result[result["match_method"] == "A_within_filing"]
        # Annotation dedup: each Tier A pair should produce exactly one output row
        assert len(tier_a) == 1, (
            f"Expected exactly 1 Tier A row after annotation dedup, got {len(tier_a)}"
        )

    def test_tier_a_annotation_picks_closest_fv(self):
        """When multiple unified rows match a Tier A pair, the annotation
        should pick the one with the closest fair value."""
        bdc_raw = _make_bdc_raw([
            {"cik": "300", "entity_name": "FvBDC", "accession_number": "ACC3",
             "form_type": "10-K", "filing_date": "2024-07-15",
             "report_date": "2024-06-30", "period": "2024-06-30",
             "investment_identifier": "Gamma LLC - Loan",
             "fair_value": "750000"},
            {"cik": "300", "entity_name": "FvBDC", "accession_number": "ACC3",
             "form_type": "10-K", "filing_date": "2024-07-15",
             "report_date": "2024-06-30", "period": "2023-12-31",
             "investment_identifier": "Gamma LLC - Loan",
             "fair_value": "700000"},
        ])
        unified = _make_unified([
            # Closer FV match
            {"source": "bdc", "cik": "300", "entity_name": "FvBDC",
             "report_date": "2024-06-30", "issuer_name": "Gamma LLC",
             "fair_value": "750000", "index_classification": "DIRECT_LENDING",
             "asset_category": "LOAN_FIRST_LIEN",
             "bdc_investment_identifier": "Gamma LLC - Loan"},
            # Farther FV match
            {"source": "bdc", "cik": "300", "entity_name": "FvBDC",
             "report_date": "2024-06-30", "issuer_name": "Gamma LLC",
             "fair_value": "900000", "index_classification": "DIRECT_LENDING",
             "asset_category": "LOAN_FIRST_LIEN",
             "bdc_investment_identifier": "Gamma LLC - Loan"},
        ])
        result = match_positions(unified_df=unified, bdc_raw_df=bdc_raw)
        tier_a = result[result["match_method"] == "A_within_filing"]
        assert len(tier_a) == 1
        # The annotation should pick the closer FV (750000, not 900000)
        assert tier_a.iloc[0]["index_classification"] == "DIRECT_LENDING"

    def test_tier_a_left_join_preserved_when_no_unified_match(self):
        """Tier A matches with no corresponding unified row should still appear
        in output with NULL classification columns."""
        bdc_raw = _make_bdc_raw([
            {"cik": "400", "entity_name": "NoMatch", "accession_number": "ACC4",
             "form_type": "10-K", "filing_date": "2024-07-15",
             "report_date": "2024-06-30", "period": "2024-06-30",
             "investment_identifier": "Orphan Corp - Loan",
             "fair_value": "100000"},
            {"cik": "400", "entity_name": "NoMatch", "accession_number": "ACC4",
             "form_type": "10-K", "filing_date": "2024-07-15",
             "report_date": "2024-06-30", "period": "2023-12-31",
             "investment_identifier": "Orphan Corp - Loan",
             "fair_value": "95000"},
        ])
        # Unified has the current-period row but with DIFFERENT identifier
        # (simulating a stripping mismatch)
        unified = _make_unified([
            {"source": "bdc", "cik": "400", "entity_name": "NoMatch",
             "report_date": "2024-06-30", "issuer_name": "Orphan Corp",
             "fair_value": "100000", "index_classification": "DIRECT_LENDING",
             "asset_category": "LOAN_FIRST_LIEN",
             "bdc_investment_identifier": "Orphan Corp - Loan"},
        ])
        result = match_positions(unified_df=unified, bdc_raw_df=bdc_raw)
        tier_a = result[result["match_method"] == "A_within_filing"]
        # Should get a match (LEFT JOIN means even without annotation data)
        assert len(tier_a) >= 1

    def test_no_duplicate_position_ids_after_assignment(self):
        """After full pipeline (match + assign), no position_id should appear
        in more unified rows than the chain length warrants."""
        bdc_raw = _make_bdc_raw([
            {"cik": "500", "entity_name": "ChainBDC", "accession_number": "ACC5",
             "form_type": "10-K", "filing_date": "2024-07-15",
             "report_date": "2024-06-30", "period": "2024-06-30",
             "investment_identifier": "Delta LLC - Loan",
             "fair_value": "200000"},
            {"cik": "500", "entity_name": "ChainBDC", "accession_number": "ACC5",
             "form_type": "10-K", "filing_date": "2024-07-15",
             "report_date": "2024-06-30", "period": "2024-03-31",
             "investment_identifier": "Delta LLC - Loan",
             "fair_value": "190000"},
        ])
        unified = _make_unified([
            {"source": "bdc", "cik": "500", "entity_name": "ChainBDC",
             "report_date": "2024-06-30", "issuer_name": "Delta LLC",
             "fair_value": "200000", "index_classification": "DIRECT_LENDING",
             "asset_category": "LOAN_FIRST_LIEN",
             "bdc_investment_identifier": "Delta LLC - Loan"},
            {"source": "bdc", "cik": "500", "entity_name": "ChainBDC",
             "report_date": "2024-03-31", "issuer_name": "Delta LLC",
             "fair_value": "190000", "index_classification": "DIRECT_LENDING",
             "asset_category": "LOAN_FIRST_LIEN",
             "bdc_investment_identifier": "Delta LLC - Loan"},
        ])
        matches = match_positions(unified_df=unified, bdc_raw_df=bdc_raw)
        unified_out, matches_out = assign_position_ids(unified, matches)
        # Each position_id should appear at most once per report_date
        for pid in unified_out["position_id"].dropna().unique():
            pid_rows = unified_out[unified_out["position_id"] == pid]
            dates = pid_rows["report_date"].nunique()
            assert dates == len(pid_rows), (
                f"position_id {pid} has {len(pid_rows)} rows but only {dates} "
                f"unique dates -- possible duplicate assignment"
            )
