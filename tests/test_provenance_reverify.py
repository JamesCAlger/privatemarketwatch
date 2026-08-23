"""Tests for pipeline.provenance_reverify -- deterministic two-tier
re-verification of provenance-annotated unified holdings rows."""
import json

import pandas as pd
import pytest

from pipeline.provenance_reverify import (
    build_ledger,
    cheap_tier,
    classify_reason,
    full_tier,
)


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

    def test_rate_absent_trivial_not_fail(self):
        """Folded item (a): rate field, pathway='', published NULL, no raw,
        no events -> pass_trivial (not fail)."""
        df = pd.DataFrame([_row(
            row_id="ROW-trivial",
            interest_rate=None,
            interest_rate_source="",
            src_facts="",
            src_transforms="",
        )])
        out = cheap_tier(holdings_df=df)
        ir = out[out["field"] == "interest_rate"].iloc[0]
        assert ir["cheap_status"] == "pass_trivial"


_FIXTURE_XML = (
    '<xbrl xmlns:us-gaap="http://fasb.org/us-gaap/2024">'
    '<us-gaap:InvestmentInterestRate contextRef="ctx1">0.105'
    '</us-gaap:InvestmentInterestRate>'
    '<us-gaap:InvestmentOwnedAtFairValue contextRef="ctx1" unitRef="usd">'
    '1000000</us-gaap:InvestmentOwnedAtFairValue>'
    '</xbrl>'
)


def _loader(cik, accession):
    from lxml import etree
    return etree.ElementTree(etree.fromstring(_FIXTURE_XML.encode()))


class TestFullTier:
    def _cheap(self, **kw):
        base = {
            "row_id": "ROW-a", "cik": "0001287750",
            "accession_number": "0001287750-26-000001",
            "report_date": "2025-12-31", "src_context_id": "ctx1",
            "field": "interest_rate", "pathway": "xbrl_field",
            "declared_raw": 0.105,
            "declared_events": "interest_rate:rate_x100",
            "published": 10.5, "expected": 10.5, "cheap_status": "pass",
            "src_facts": json.dumps({"interest_rate": {"r": 0.105}}),
        }
        return pd.DataFrame([{**base, **kw}])

    def test_verified_roundtrip(self):
        out = full_tier(self._cheap(), xml_loader=_loader)
        assert out.iloc[0]["full_status"] == "raw_match"
        assert out.iloc[0]["instance_raw"] == pytest.approx(0.105)

    def test_stale_declared_raw_but_published_consistent(self):
        # declared_raw is stale (0.2) but published 10.5 == instance 0.105*100
        out = full_tier(
            self._cheap(declared_raw=0.2, cheap_status="fail"),
            xml_loader=_loader,
        )
        assert out.iloc[0]["full_status"] == "raw_stale"

    def test_published_no_longer_matches_filing(self):
        out = full_tier(self._cheap(published=99.0), xml_loader=_loader)
        assert out.iloc[0]["full_status"] == "published_mismatch"

    def test_anchor_and_context_and_file_missing(self):
        assert full_tier(
            self._cheap(field="basis_spread", declared_raw=None,
                        declared_events="", published=None,
                        src_facts=""),
            xml_loader=_loader,
        ).iloc[0]["full_status"] == "anchor_missing"

        assert full_tier(
            self._cheap(src_context_id="ctxZZ"),
            xml_loader=_loader,
        ).iloc[0]["full_status"] == "context_missing"

        assert full_tier(
            self._cheap(),
            xml_loader=lambda c, a: None,
        ).iloc[0]["full_status"] == "source_unavailable"

    def test_short_circuits_not_checked(self):
        out = full_tier(
            self._cheap(cheap_status="corrected"),
            xml_loader=_loader,
        )
        assert out.iloc[0]["full_status"] == "not_checked"


class TestClassifyReason:
    @pytest.mark.parametrize("cheap,full,reason", [
        ("pass",                   "raw_match",          "verified"),
        ("pass",                   "raw_stale",          "anchor_stale"),
        ("fail",                   "raw_match",          "transform_drift"),
        ("pass",                   "published_mismatch", "filing_mismatch"),
        ("pass",                   "anchor_missing",     "anchor_missing"),
        ("pass",                   "context_missing",    "provenance_wrong"),
        ("pass",                   "source_unavailable", "source_unavailable"),
        ("corrected",              "not_checked",        "corrected"),
        ("derived",                "not_checked",        "derived"),
        ("text_pathway",           "not_checked",        "text_pathway"),
        ("filled_field",           "not_checked",        "merged_context_excluded"),
        ("merged_conflict",        "not_checked",        "merged_context_excluded"),
        ("no_provenance",          "not_checked",        "no_provenance"),
        ("pass_trivial",           "not_checked",        "unchecked_trivial"),
    ])
    def test_table(self, cheap, full, reason):
        assert classify_reason(cheap, full) == reason


class TestLedger:
    def test_ledger_and_summary_written(self, tmp_path):
        df = pd.DataFrame([
            {"row_id": "ROW-a", "cik": "1", "accession_number": "A",
             "report_date": "2025-12-31", "src_context_id": "c1",
             "field": "fair_value", "pathway": "xbrl_field",
             "declared_raw": None, "declared_events": "",
             "published": 100.0, "expected": None, "instance_raw": 100.0,
             "cheap_status": "pass_trivial", "full_status": "raw_match"},
            {"row_id": "ROW-b", "cik": "1", "accession_number": "A",
             "report_date": "2025-12-31", "src_context_id": "c2",
             "field": "fair_value", "pathway": "",
             "declared_raw": None, "declared_events": "",
             "published": 50.0, "expected": None, "instance_raw": None,
             "cheap_status": "corrected", "full_status": "not_checked"},
        ])
        ledger_path, summary_path = build_ledger(
            df, out_dir=tmp_path, holdings_mtime="2026-08-23T00:00:00")
        ledger = pd.read_csv(ledger_path)
        assert set(["row_id", "field", "reason_code"]) <= set(ledger.columns)
        assert ledger.set_index("row_id").loc["ROW-a", "reason_code"] == "verified"
        assert ledger.set_index("row_id").loc["ROW-b", "reason_code"] == "corrected"
        summary = pd.read_csv(summary_path)
        row = summary.iloc[0]
        assert row["verified_fv"] == 100.0
        assert row["total_fv"] == 150.0
        assert row["verified_fv_share"] == pytest.approx(100.0 / 150.0)

    def test_holdings_mtime_recorded(self, tmp_path):
        """holdings_artifact_mtime column must propagate to every ledger row."""
        df = pd.DataFrame([
            {"row_id": "ROW-x", "cik": "2", "accession_number": "B",
             "report_date": "2025-09-30", "src_context_id": "cx",
             "field": "interest_rate", "pathway": "xbrl_field",
             "declared_raw": 0.1, "declared_events": "interest_rate:rate_x100",
             "published": 10.0, "expected": 10.0, "instance_raw": None,
             "cheap_status": "pass", "full_status": "not_checked"},
        ])
        mtime = "2026-08-23T12:34:56"
        lp, _ = build_ledger(df, out_dir=tmp_path, holdings_mtime=mtime)
        ledger = pd.read_csv(lp)
        assert (ledger["holdings_artifact_mtime"] == mtime).all()

    def test_verified_fv_only_counts_verified_reason(self, tmp_path):
        """derived/corrected FV must NOT appear in verified_fv numerator."""
        df = pd.DataFrame([
            {"row_id": "ROW-v", "cik": "3", "accession_number": "C",
             "report_date": "2025-12-31", "src_context_id": "cv",
             "field": "fair_value", "pathway": "xbrl_field",
             "declared_raw": None, "declared_events": "",
             "published": 200.0, "expected": None, "instance_raw": 200.0,
             "cheap_status": "pass_trivial", "full_status": "raw_match"},
            {"row_id": "ROW-d", "cik": "3", "accession_number": "C",
             "report_date": "2025-12-31", "src_context_id": "cd",
             "field": "fair_value", "pathway": "derived_proxy",
             "declared_raw": None, "declared_events": "",
             "published": 80.0, "expected": None, "instance_raw": None,
             "cheap_status": "derived", "full_status": "not_checked"},
            {"row_id": "ROW-c", "cik": "3", "accession_number": "C",
             "report_date": "2025-12-31", "src_context_id": "cc",
             "field": "fair_value", "pathway": "",
             "declared_raw": None, "declared_events": "",
             "published": 30.0, "expected": None, "instance_raw": None,
             "cheap_status": "corrected", "full_status": "not_checked"},
        ])
        _, sp = build_ledger(df, out_dir=tmp_path)
        summary = pd.read_csv(sp)
        row = summary.iloc[0]
        assert row["verified_fv"] == pytest.approx(200.0)
        assert row["derived_fv"] == pytest.approx(80.0)
        assert row["corrected_fv"] == pytest.approx(30.0)
        assert row["total_fv"] == pytest.approx(310.0)
        assert row["verified_fv_share"] == pytest.approx(200.0 / 310.0)

    def test_reason_code_counts_wide_in_summary(self, tmp_path):
        """Wide reason-code count columns must appear in summary."""
        df = pd.DataFrame([
            {"row_id": "ROW-1", "cik": "4", "accession_number": "D",
             "report_date": "2025-12-31", "src_context_id": "c1",
             "field": "fair_value", "pathway": "xbrl_field",
             "declared_raw": None, "declared_events": "",
             "published": 100.0, "expected": None, "instance_raw": 100.0,
             "cheap_status": "pass_trivial", "full_status": "raw_match"},
            {"row_id": "ROW-2", "cik": "4", "accession_number": "D",
             "report_date": "2025-12-31", "src_context_id": "c2",
             "field": "interest_rate", "pathway": "xbrl_field",
             "declared_raw": None, "declared_events": "",
             "published": 8.0, "expected": None, "instance_raw": None,
             "cheap_status": "no_provenance", "full_status": "not_checked"},
        ])
        _, sp = build_ledger(df, out_dir=tmp_path)
        summary = pd.read_csv(sp)
        cols = set(summary.columns)
        assert "verified" in cols or "no_provenance" in cols

    # ------------------------------------------------------------------
    # Folded-in items from Task 8 review
    # ------------------------------------------------------------------

    def test_full_tier_decimals_rescale_expect_raw_match(self):
        """Folded (a): src_facts carries decimals_rescale:10^-3, published 500000.0,
        XML fact value 500000000 -- full_tier must resolve raw_match (proves
        _extractor_multiplier applied in published recomputation)."""
        xml_src = (
            '<xbrl xmlns:us-gaap="http://fasb.org/us-gaap/2024">'
            '<us-gaap:InvestmentOwnedAtFairValue contextRef="ctx-dec" unitRef="usd">'
            '500000000'
            '</us-gaap:InvestmentOwnedAtFairValue>'
            '</xbrl>'
        )

        def _ldr(cik, accession):
            from lxml import etree
            return etree.ElementTree(etree.fromstring(xml_src.encode()))

        cheap_df = pd.DataFrame([{
            "row_id": "ROW-dec", "cik": "0001287750",
            "accession_number": "0001287750-26-000001",
            "report_date": "2025-12-31", "src_context_id": "ctx-dec",
            "field": "fair_value", "pathway": "xbrl_field",
            "declared_raw": 500000000,
            "declared_events": "",
            "published": 500000.0,
            "expected": 500000.0,
            "cheap_status": "pass",
            "src_facts": json.dumps({
                "fair_value": {
                    "c": "investmentownedatfairvalue",
                    "r": 500000000,
                    "x": ["decimals_rescale:10^-3"],
                }
            }),
        }])
        out = full_tier(cheap_df, xml_loader=_ldr)
        assert out.iloc[0]["full_status"] == "raw_match"

    def test_full_tier_missing_raw_with_transform_becomes_transform_drift(self):
        """Folded (b): cheap_status='missing_raw_with_transform', filing supports
        published value -- full_status should be raw_match, classify_reason
        should return 'transform_drift'."""
        xml_src = (
            '<xbrl xmlns:us-gaap="http://fasb.org/us-gaap/2024">'
            '<us-gaap:InvestmentInterestRate contextRef="ctx-tr">0.105'
            '</us-gaap:InvestmentInterestRate>'
            '</xbrl>'
        )

        def _ldr(cik, accession):
            from lxml import etree
            return etree.ElementTree(etree.fromstring(xml_src.encode()))

        cheap_df = pd.DataFrame([{
            "row_id": "ROW-tr", "cik": "0001287750",
            "accession_number": "0001287750-26-000001",
            "report_date": "2025-12-31", "src_context_id": "ctx-tr",
            "field": "interest_rate", "pathway": "xbrl_field",
            "declared_raw": None,
            "declared_events": "interest_rate:rate_x100",
            "published": 10.5,
            "expected": None,
            "cheap_status": "missing_raw_with_transform",
            "src_facts": "",
        }])
        out = full_tier(cheap_df, xml_loader=_ldr)
        assert out.iloc[0]["full_status"] == "raw_match"
        assert classify_reason("missing_raw_with_transform", "raw_match") == "transform_drift"
