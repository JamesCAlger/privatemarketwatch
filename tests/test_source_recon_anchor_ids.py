"""Tests for anchor-based published ids in source reconciliation.

Internal SQL ordinals are unchanged; these tests cover the anchor columns
minted in the coerce helpers and the published-id swap in reconcile.
"""

import pandas as pd

from pipeline.source_reconciliation import _coerce_source_df


def _source_frame(rows):
    base = {
        "cik": "0001418076", "entity_name": "Test BDC",
        "accession_number": "0001418076-26-000001", "form_type": "10-Q",
        "filing_date": "2026-05-10", "report_date": "2026-03-31",
        "period": "2026-03-31", "context_id": "ctx_1",
        "investment_identifier": "Acme Corp - First Lien",
        "industry": "", "investment_type": "", "affiliation": "",
        "dimensions_raw": "", "concept_names": "",
        "maturity_date": "", "fair_value": "1000000",
    }
    return pd.DataFrame([{**base, **r} for r in rows])


class TestSourceAnchorId:
    def test_anchor_is_src_accession_context(self):
        out = _coerce_source_df(
            _source_frame([{"context_id": "ctx_42"}]),
            enable_bdc_xbrl_wrappers=False)
        assert out.iloc[0]["source_anchor_id"] == (
            "src:0001418076-26-000001:ctx_42")
        # internal ordinal untouched
        assert list(out["source_row_id"]) == [0]

    def test_duplicate_context_gets_ordinal_suffix(self):
        out = _coerce_source_df(
            _source_frame([{"context_id": "ctx_9"},
                           {"context_id": "ctx_9"},
                           {"context_id": "ctx_9"}]),
            enable_bdc_xbrl_wrappers=False)
        assert list(out["source_anchor_id"]) == [
            "src:0001418076-26-000001:ctx_9",
            "src:0001418076-26-000001:ctx_9#2",
            "src:0001418076-26-000001:ctx_9#3",
        ]

    def test_missing_anchor_part_falls_back_to_ordinal(self):
        out = _coerce_source_df(
            _source_frame([{"context_id": ""},
                           {"accession_number": "", "context_id": "ctx_1"}]),
            enable_bdc_xbrl_wrappers=False)
        assert list(out["source_anchor_id"]) == ["src-ord:0", "src-ord:1"]

    def test_anchor_unique_across_frame(self):
        out = _coerce_source_df(
            _source_frame([{"context_id": "ctx_1"},
                           {"context_id": "ctx_2"},
                           {"context_id": "ctx_1"}]),
            enable_bdc_xbrl_wrappers=False)
        assert out["source_anchor_id"].nunique() == 3
