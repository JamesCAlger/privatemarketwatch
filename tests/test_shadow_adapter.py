"""Tests for scripts/shadow_adapter.py -- provenance re-verifier feed (Task 1).

TDD: these tests were written before the _provenance_select() implementation.
"""
from __future__ import annotations

import duckdb
import pandas as pd


def _prov_rows(rows):
    base = {
        "row_id": "ROW-0000000000000001", "cik": "0001287750",
        "accession_number": "0001287750-26-000001", "report_date": "2025-12-31",
        "src_context_id": "ctx1", "field": "fair_value",
        "reason_code": "verified", "published": 1000000.0,
        "cheap_status": "pass", "full_status": "raw_match",
    }
    return pd.DataFrame([{**base, **r} for r in rows])


def _run_fragment(monkeypatch, tmp_path, prov_df, so_detail_df=None):
    import scripts.shadow_adapter as adp
    prov = tmp_path / "provenance_ledger.csv"
    prov_df.to_csv(prov, index=False)
    monkeypatch.setattr(adp, "PROVENANCE_LEDGER_FILE", prov, raising=False)
    so = tmp_path / "source_only_detail.csv"
    if so_detail_df is None:
        so_detail_df = pd.DataFrame(columns=[
            "cik", "report_date", "accession_number", "source_row_id",
            "mechanism", "is_blocking"])
    so_detail_df.to_csv(so, index=False)
    monkeypatch.setattr(adp, "SOURCE_RECONCILIATION_SOURCE_ONLY_DETAIL_FILE",
                        so, raising=False)
    frag = adp._provenance_select()
    assert frag is not None
    return duckdb.connect().execute(frag).fetchdf()


class TestProvenanceFeed:
    def test_tier_status_mapping(self, monkeypatch, tmp_path):
        df = _prov_rows([
            {"row_id": "ROW-a", "reason_code": "filing_mismatch"},
            {"row_id": "ROW-b", "reason_code": "no_provenance"},
            {"row_id": "ROW-c", "reason_code": "verified"},
        ])
        out = _run_fragment(monkeypatch, tmp_path, df).set_index("rule_name")
        assert out.loc["filing_mismatch", "tier"] == "tight"
        assert out.loc["filing_mismatch", "status"] == "fail"
        assert out.loc["no_provenance", "tier"] == "weak"
        assert out.loc["no_provenance", "status"] == "warn"
        assert out.loc["verified", "tier"] == "weak"
        assert out.loc["verified", "status"] == "pass"
        assert (out["engine"] == "provenance_reverify").all()
        assert (out["enforcement"] == "advisory").all()

    def test_aggregation_and_fv_metric(self, monkeypatch, tmp_path):
        df = _prov_rows([
            {"row_id": "ROW-a", "field": "fair_value",
             "reason_code": "filing_mismatch", "published": 2000000.0},
            {"row_id": "ROW-a", "field": "interest_rate",
             "reason_code": "filing_mismatch", "published": 10.5},
            {"row_id": "ROW-b", "field": "cost",
             "reason_code": "filing_mismatch", "published": 999.0},
        ])
        out = _run_fragment(monkeypatch, tmp_path, df)
        row = out[out["rule_name"] == "filing_mismatch"].iloc[0]
        assert row["n_units"] == 2            # distinct row_ids
        assert row["metric"] == 2.0           # only the fair_value row, $M
        assert row["metric_name"] == "affected_fv_m"

    def test_dedup_excludes_already_queued_and_audits(self, monkeypatch, tmp_path):
        prov = _prov_rows([
            {"row_id": "ROW-a", "src_context_id": "ctxQ",
             "reason_code": "filing_mismatch", "published": 3000000.0},
            {"row_id": "ROW-b", "src_context_id": "ctxF",
             "reason_code": "filing_mismatch", "published": 1000000.0},
        ])
        so = pd.DataFrame([{
            "cik": "0001287750", "report_date": "2025-12-31",
            "accession_number": "0001287750-26-000001",
            "source_row_id": "src:0001287750-26-000001:ctxQ#2",
            "mechanism": "blocking_source_pct_leaf_parser_mismatch",
            "is_blocking": True,
        }])
        out = _run_fragment(monkeypatch, tmp_path, prov, so)
        fm = out[out["rule_name"] == "filing_mismatch"].iloc[0]
        assert fm["n_units"] == 1             # ROW-a excluded (ctxQ queued)
        assert fm["metric"] == 1.0
        audit = out[out["rule_name"] == "provenance_already_queued"].iloc[0]
        assert audit["status"] == "pass" and audit["n_units"] == 1
        assert audit["mechanism"] == "dedup_source_recon"

    def test_informational_codes_not_deduped(self, monkeypatch, tmp_path):
        prov = _prov_rows([
            {"row_id": "ROW-a", "src_context_id": "ctxQ",
             "reason_code": "no_provenance"}])
        so = pd.DataFrame([{
            "cik": "0001287750", "report_date": "2025-12-31",
            "accession_number": "0001287750-26-000001",
            "source_row_id": "src:0001287750-26-000001:ctxQ",
            "mechanism": "m", "is_blocking": True}])
        out = _run_fragment(monkeypatch, tmp_path, prov, so)
        assert out[out["rule_name"] == "no_provenance"].iloc[0]["n_units"] == 1

    def test_absent_file_returns_none(self, monkeypatch, tmp_path):
        import scripts.shadow_adapter as adp
        monkeypatch.setattr(adp, "PROVENANCE_LEDGER_FILE",
                            tmp_path / "missing.csv", raising=False)
        assert adp._provenance_select() is None

    def test_fragment_satisfies_ledger_contract(self, monkeypatch, tmp_path):
        # 13 columns, exact names/order per LEDGER_COLUMNS in the runner
        out = _run_fragment(monkeypatch, tmp_path, _prov_rows([{}]))
        assert list(out.columns) == [
            "engine", "rule_name", "tier", "enforcement", "cik",
            "period_kind", "period", "status", "metric", "metric_name",
            "n_units", "mechanism", "src_confidence"]
