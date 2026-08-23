"""Tests for pipeline.provenance_reverify -- deterministic two-tier
re-verification of provenance-annotated unified holdings rows."""
import json

import pandas as pd
import pytest

from pipeline.provenance_reverify import cheap_tier


def _row(**kw):
    base = {
        "row_id": "ROW-0000000000000001", "source": "bdc", "cik": "0001287750",
        "accession_number": "0001287750-26-000001", "report_date": "2025-12-31",
        "src_context_id": "ctx1", "src_facts": "", "src_transforms": "",
        "src_conflict_fields": "", "src_filled_fields": "",
        "corrected_fields": "",
        "fair_value": 1000000.0, "cost": None, "principal_amount": None,
        "shares_held": None, "pct_of_net_assets": None,
        "interest_rate": None, "basis_spread": None, "pik_rate": None,
        "interest_rate_source": "", "basis_spread_source": "",
        "pik_rate_source": "", "pct_of_net_assets_source": "",
        "fair_value_source": "xbrl_field", "cost_source": "",
        "shares_held_source": "", "principal_amount_source": "",
    }
    return {**base, **kw}


class TestCheapTier:
    def test_rate_x100_pass_and_fail(self):
        df = pd.DataFrame([
            _row(row_id="ROW-a", interest_rate=10.5,
                 interest_rate_source="xbrl_field",
                 src_facts=json.dumps({"interest_rate": {"r": 0.105}}),
                 src_transforms="interest_rate:rate_x100"),
            _row(row_id="ROW-b", interest_rate=99.0,
                 interest_rate_source="xbrl_field",
                 src_facts=json.dumps({"interest_rate": {"r": 0.105}}),
                 src_transforms="interest_rate:rate_x100"),
        ])
        out = cheap_tier(holdings_df=df)
        ir = out[out["field"] == "interest_rate"].set_index("row_id")
        assert ir.loc["ROW-a", "cheap_status"] == "pass"
        assert ir.loc["ROW-a", "expected"] == pytest.approx(10.5)
        assert ir.loc["ROW-b", "cheap_status"] == "fail"

    def test_decimals_event_on_monetary_field(self):
        df = pd.DataFrame([_row(
            row_id="ROW-c", fair_value=500000.0,
            src_facts=json.dumps({"fair_value":
                {"c": "investmentownedatfairvalue", "r": 500000000,
                 "x": ["decimals_rescale:10^-3"]}}))])
        out = cheap_tier(holdings_df=df)
        fv = out[(out["field"] == "fair_value")].iloc[0]
        assert fv["cheap_status"] == "pass"
        assert fv["expected"] == pytest.approx(500000.0)

    def test_untransformed_monetary_is_trivial_pass(self):
        out = cheap_tier(holdings_df=pd.DataFrame([_row()]))
        fv = out[out["field"] == "fair_value"].iloc[0]
        assert fv["cheap_status"] == "pass_trivial"

    def test_short_circuit_statuses(self):
        df = pd.DataFrame([
            _row(row_id="ROW-t", interest_rate=10.0,
                 interest_rate_source="identifier_text"),
            _row(row_id="ROW-d", cost=1000.0, cost_source="derived_proxy"),
            _row(row_id="ROW-k", fair_value=5.0,
                 corrected_fields="fair_value"),
            _row(row_id="ROW-f", cost=99.0, src_filled_fields="cost"),
            _row(row_id="ROW-m", fair_value=7.0,
                 src_conflict_fields="fair_value"),
            _row(row_id="ROW-n", src_context_id=""),
        ])
        out = cheap_tier(holdings_df=df).set_index(["row_id", "field"])
        assert out.loc[("ROW-t", "interest_rate"), "cheap_status"] == "text_pathway"
        assert out.loc[("ROW-d", "cost"), "cheap_status"] == "derived"
        assert out.loc[("ROW-k", "fair_value"), "cheap_status"] == "corrected"
        assert out.loc[("ROW-f", "cost"), "cheap_status"] == "filled_field"
        assert out.loc[("ROW-m", "fair_value"), "cheap_status"] == "merged_conflict"
        assert out.loc[("ROW-n", "fair_value"), "cheap_status"] == "no_provenance"

    def test_neg_null_event(self):
        df = pd.DataFrame([_row(
            row_id="ROW-e", interest_rate=None,
            src_facts=json.dumps({"interest_rate": {"r": -1.0}}),
            src_transforms="interest_rate:neg_null")])
        out = cheap_tier(holdings_df=df)
        ir = out[out["field"] == "interest_rate"].iloc[0]
        assert ir["cheap_status"] == "pass"

    def test_event_without_raw_fails_loudly(self):
        df = pd.DataFrame([_row(
            row_id="ROW-g", interest_rate=10.5,
            interest_rate_source="xbrl_field",
            src_transforms="interest_rate:rate_x100", src_facts="")])
        out = cheap_tier(holdings_df=df)
        ir = out[out["field"] == "interest_rate"].iloc[0]
        assert ir["cheap_status"] == "missing_raw_with_transform"

    def test_src_facts_column_in_output(self):
        """Task 8 NOTE: src_facts must be included in output columns."""
        out = cheap_tier(holdings_df=pd.DataFrame([_row()]))
        assert "src_facts" in out.columns
