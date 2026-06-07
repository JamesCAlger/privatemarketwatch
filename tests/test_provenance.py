"""Tests for pipeline.provenance -- opt-in provenance diagnostic artifacts.

All tests use tmp_path for output to avoid the conftest.py monkeypatch guard
on data/output/.
"""

import json
from pathlib import Path

import pandas as pd
import pytest

from pipeline.bdc_xbrl_wrapper import WRAPPER_COLUMNS


# -------------------------------------------------------------------------
# Fixtures
# -------------------------------------------------------------------------

def _make_unified_df(rows: list[dict]) -> pd.DataFrame:
    """Minimal unified holdings DataFrame for provenance tests."""
    base = {
        "source": "bdc",
        "cik": "0001418076",
        "entity_name": "Test BDC",
        "accession_number": "0001418076-24-000001",
        "filing_date": "2024-03-15",
        "report_date": "2024-12-31",
        "issuer_name": "Acme Corp",
        "bdc_investment_identifier": "Investment Debt Investments Acme Corp Senior Secured First Lien Term Loan Type of Investment Senior Secured First Lien Term Loan",
        "bdc_dimensions_raw": "investmentidentifieraxis=Acme Corp",
        "position_key": "acme corp senior secured",
        "position_id": "POS-00000001",
    }
    result_rows = []
    for row in rows:
        merged = {**base, **row}
        result_rows.append(merged)
    return pd.DataFrame(result_rows)


# -------------------------------------------------------------------------
# Holdings wrapper provenance tests
# -------------------------------------------------------------------------


class TestHoldingsWrapperProvenance:
    def test_columns_present(self, tmp_path: Path):
        """All WRAPPER_COLUMNS plus join key columns are present."""
        from pipeline.provenance import build_holdings_wrapper_provenance

        df = _make_unified_df([{}])
        result = build_holdings_wrapper_provenance(
            unified_df=df,
            output_path=tmp_path / "wrapper_prov.csv",
        )
        expected_cols = {"cik", "report_date", "bdc_investment_identifier"} | set(
            WRAPPER_COLUMNS
        )
        assert expected_cols == set(result.columns)

    def test_bdc_only(self, tmp_path: Path):
        """Mixed-source df produces only BDC rows in output."""
        from pipeline.provenance import build_holdings_wrapper_provenance

        df = _make_unified_df([
            {"source": "bdc", "bdc_investment_identifier": "Investment Debt Investments Test"},
            {"source": "nport", "bdc_investment_identifier": ""},
            {"source": "nport", "bdc_investment_identifier": None},
        ])
        # Ensure nport rows have a non-null source
        result = build_holdings_wrapper_provenance(
            unified_df=df,
            output_path=tmp_path / "wrapper_prov.csv",
        )
        assert len(result) == 1
        assert result.iloc[0]["cik"] == "0001418076"

    def test_empty_input(self, tmp_path: Path):
        """No crash on empty DataFrame."""
        from pipeline.provenance import build_holdings_wrapper_provenance

        df = pd.DataFrame(columns=["source", "cik", "bdc_investment_identifier", "report_date"])
        result = build_holdings_wrapper_provenance(
            unified_df=df,
            output_path=tmp_path / "wrapper_prov.csv",
        )
        assert len(result) == 0
        assert "wrapper_rule_id" in result.columns


# -------------------------------------------------------------------------
# XBRL concept map tests
# -------------------------------------------------------------------------


class TestXbrlConceptMap:
    def test_all_columns_present(self, tmp_path: Path):
        """Every unique output column in CONCEPT_MAP is a key in the map."""
        from pipeline.bdc_filings import CONCEPT_MAP
        from pipeline.provenance import build_xbrl_concept_map

        result = build_xbrl_concept_map(output_path=tmp_path / "concept_map.json")
        expected_cols = {col for _, col in CONCEPT_MAP}
        assert expected_cols == set(result.keys())

    def test_priority_order(self, tmp_path: Path):
        """First concept for fair_value is investmentownedatfairvalue."""
        from pipeline.provenance import build_xbrl_concept_map

        result = build_xbrl_concept_map(output_path=tmp_path / "concept_map.json")
        assert result["fair_value"][0] == "investmentownedatfairvalue"

    def test_valid_json_roundtrip(self, tmp_path: Path):
        """Write/read roundtrip produces identical dict."""
        from pipeline.provenance import build_xbrl_concept_map

        out_path = tmp_path / "concept_map.json"
        original = build_xbrl_concept_map(output_path=out_path)
        with open(out_path, encoding="utf-8") as fh:
            loaded = json.load(fh)
        assert original == loaded


# -------------------------------------------------------------------------
# Position provenance index tests
# -------------------------------------------------------------------------


class TestPositionProvenanceIndex:
    def test_join_carries_accession(self, tmp_path: Path):
        """position_id join carries accession_number through."""
        from pipeline.provenance import build_position_provenance_index

        unified_df = _make_unified_df([{
            "position_id": "POS-00000001",
            "cik": "0001418076",
            "report_date": "2024-12-31",
            "accession_number": "0001418076-24-000099",
            "bdc_investment_identifier": "Test Ident",
            "source": "bdc",
        }])

        pos_returns_df = pd.DataFrame([{
            "position_id": "POS-00000001",
            "cik": "0001418076",
            "entity_name": "Test BDC",
            "end_quarter": "2024q4",
            "issuer_name": "Acme Corp",
            "index_classification": "direct_lending",
            "asset_category": "debt",
            "begin_fair_value": "1000000",
            "end_fair_value": "1010000",
        }])

        wrapper_df = pd.DataFrame([{
            "cik": "0001418076",
            "report_date": "2024-12-31",
            "bdc_investment_identifier": "Test Ident",
            "wrapper_rule_id": "SLR_DEBT_LEAF_V1",
            "wrapper_disposition": "debt_position_leaf",
            "wrapper_family": "debt",
            "wrapper_signature_status": "pass",
            "wrapper_version": "1",
            **{col: "" for col in WRAPPER_COLUMNS if col not in {
                "wrapper_rule_id", "wrapper_disposition", "wrapper_family",
                "wrapper_signature_status", "wrapper_version",
            }},
        }])

        result = build_position_provenance_index(
            position_returns_df=pos_returns_df,
            unified_df=unified_df,
            wrapper_provenance_df=wrapper_df,
            output_path=tmp_path / "pos_prov.csv",
        )

        assert len(result) == 1
        row = result.iloc[0]
        assert row["accession_number"] == "0001418076-24-000099"
        assert row["wrapper_rule_id"] == "SLR_DEBT_LEAF_V1"
        assert row["filing_path"] == "data/raw/filings/bdc_xbrl/0001418076/000141807624000099/"

    def test_null_wrapper_for_nport(self, tmp_path: Path):
        """Non-BDC (nport) rows get null/empty wrapper columns."""
        from pipeline.provenance import build_position_provenance_index

        unified_df = pd.DataFrame([{
            "source": "nport",
            "cik": "0009999999",
            "entity_name": "Nport Fund",
            "accession_number": "0009999999-24-000001",
            "report_date": "2024-12-31",
            "issuer_name": "Some Corp",
            "bdc_investment_identifier": "",
            "bdc_dimensions_raw": "",
            "position_key": "some corp",
            "position_id": "POS-00000002",
        }])

        pos_returns_df = pd.DataFrame([{
            "position_id": "POS-00000002",
            "cik": "0009999999",
            "entity_name": "Nport Fund",
            "end_quarter": "2024q4",
            "issuer_name": "Some Corp",
            "index_classification": "direct_lending",
            "asset_category": "debt",
        }])

        # Empty wrapper provenance (no BDC rows to classify)
        wrapper_df = pd.DataFrame(
            columns=["cik", "report_date", "bdc_investment_identifier"] + list(WRAPPER_COLUMNS)
        )

        result = build_position_provenance_index(
            position_returns_df=pos_returns_df,
            unified_df=unified_df,
            wrapper_provenance_df=wrapper_df,
            output_path=tmp_path / "pos_prov.csv",
        )

        assert len(result) == 1
        row = result.iloc[0]
        assert row["position_id"] == "POS-00000002"
        # Wrapper columns should be null/empty for nport
        assert pd.isna(row["wrapper_rule_id"]) or row["wrapper_rule_id"] == ""
