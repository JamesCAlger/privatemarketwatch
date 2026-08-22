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


from pipeline.source_reconciliation import _coerce_output_df  # noqa: E402


def _holdings_frame(rows):
    base = {
        "source": "bdc", "cik": "0001418076", "entity_name": "Test BDC",
        "report_date": "2026-03-31", "period": "2026-03-31",
        "accession_number": "0001418076-26-000001", "filing_date": "2026-05-10",
        "bdc_form_type": "10-Q",
        "bdc_investment_identifier": "Acme Corp - First Lien",
        "bdc_dimensions_raw": "", "issuer_name": "Acme Corp",
        "instrument_description": "", "index_classification": "DIRECT_LENDING",
        "asset_category": "", "issuer_category": "", "maturity_date": "",
        "fair_value": "1000000", "cost": "", "principal_amount": "",
        "shares_held": "", "interest_rate": "", "basis_spread": "",
        "pik_rate": "",
    }
    return pd.DataFrame([{**base, **r} for r in rows])


class TestOutputAnchorId:
    def test_uses_unified_row_id_when_present(self):
        out = _coerce_output_df(
            _holdings_frame([{"row_id": "ROW-0123456789abcdef"}]),
            enable_bdc_xbrl_wrappers=False)
        assert out.iloc[0]["output_anchor_id"] == "ROW-0123456789abcdef"
        assert list(out["output_row_id"]) == [0]

    def test_falls_back_to_ordinal_without_row_id(self):
        out = _coerce_output_df(
            _holdings_frame([{}, {}]), enable_bdc_xbrl_wrappers=False)
        assert list(out["output_anchor_id"]) == ["0", "1"]

    def test_empty_row_id_value_falls_back(self):
        out = _coerce_output_df(
            _holdings_frame([{"row_id": ""}]), enable_bdc_xbrl_wrappers=False)
        assert out.iloc[0]["output_anchor_id"] == "0"


from pipeline.source_reconciliation import (  # noqa: E402
    reconcile_bdc_source_to_holdings,
)

_NO_RESCALES = pd.DataFrame(columns=["cik", "field", "factor"])


class TestPublishedDetailIds:
    def test_source_only_row_publishes_src_anchor(self):
        source = _source_frame([{"context_id": "ctx_lonely",
                                 "report_date": "2026-03-31"}])
        detail, _metrics = reconcile_bdc_source_to_holdings(
            source, _holdings_frame([]).iloc[0:0],
            enable_bdc_xbrl_wrappers=False,
            audited_value_rescales=_NO_RESCALES)
        src_rows = detail[detail["source_row_id"].astype(str).ne("")]
        assert len(src_rows) >= 1
        assert set(src_rows["source_row_id"]) == {
            "src:0001418076-26-000001:ctx_lonely"}

    def test_output_extra_row_publishes_unified_row_id(self):
        holdings = _holdings_frame([{"row_id": "ROW-feedfeedfeedfeed",
                                     "report_date": "2026-03-31"}])
        detail, _metrics = reconcile_bdc_source_to_holdings(
            _source_frame([]).iloc[0:0], holdings,
            enable_bdc_xbrl_wrappers=False,
            audited_value_rescales=_NO_RESCALES)
        out_rows = detail[detail["output_row_id"].astype(str).ne("")]
        assert len(out_rows) >= 1
        assert set(out_rows["output_row_id"]) == {"ROW-feedfeedfeedfeed"}
