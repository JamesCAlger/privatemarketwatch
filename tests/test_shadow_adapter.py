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


def _run_fragment(monkeypatch, tmp_path, prov_df, det_df=None):
    import scripts.shadow_adapter as adp
    prov = tmp_path / "provenance_ledger.csv"
    prov_df.to_csv(prov, index=False)
    monkeypatch.setattr(adp, "PROVENANCE_LEDGER_FILE", prov, raising=False)
    det = tmp_path / "source_reconciliation_detail.csv"
    if det_df is None:
        det_df = pd.DataFrame(columns=[
            "cik", "report_date", "output_row_id", "blocking_issue"])
    det_df.to_csv(det, index=False)
    monkeypatch.setattr(adp, "SOURCE_RECONCILIATION_DETAIL_FILE",
                        det, raising=False)
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
        assert (out["period_kind"] == "report_date").all()

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
            {"row_id": "ROW-a", "reason_code": "filing_mismatch", "published": 3000000.0},
            {"row_id": "ROW-b", "reason_code": "filing_mismatch", "published": 1000000.0},
        ])
        # Detail file: ROW-a has a blocking output_row_id match; ROW-b does not.
        det = pd.DataFrame([{
            "cik": "0001287750", "report_date": "2025-12-31",
            "output_row_id": "ROW-a",
            "blocking_issue": "1",
        }])
        out = _run_fragment(monkeypatch, tmp_path, prov, det)
        fm = out[out["rule_name"] == "filing_mismatch"].iloc[0]
        assert fm["n_units"] == 1             # ROW-a excluded (output_row_id in blocking detail)
        assert fm["metric"] == 1.0
        audit = out[out["rule_name"] == "provenance_already_queued"].iloc[0]
        assert audit["status"] == "pass" and audit["n_units"] == 1
        assert audit["mechanism"] == "dedup_source_recon"

    def test_informational_codes_not_deduped(self, monkeypatch, tmp_path):
        prov = _prov_rows([
            {"row_id": "ROW-a", "reason_code": "no_provenance"}])
        # Detail file has a blocking row matching ROW-a -- but no_provenance is
        # informational (weak/warn), so dedup must not apply.
        det = pd.DataFrame([{
            "cik": "0001287750", "report_date": "2025-12-31",
            "output_row_id": "ROW-a",
            "blocking_issue": "1"}])
        out = _run_fragment(monkeypatch, tmp_path, prov, det)
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

    def test_unknown_reason_code_routes_to_weak_warn(self, monkeypatch, tmp_path):
        # 'amended' is a spec-reserved code that is not in PROV_TIGHT_FAIL,
        # PROV_WEAK_WARN, or PROV_WEAK_PASS.  Unknown codes must land
        # tier=weak, status=warn (safe default, not pass).
        df = _prov_rows([{"row_id": "ROW-x", "reason_code": "amended"}])
        out = _run_fragment(monkeypatch, tmp_path, df).set_index("rule_name")
        assert out.loc["amended", "tier"] == "weak"
        assert out.loc["amended", "status"] == "warn"

    def test_pct_sense_check_is_warn_lane_not_tight(self):
        """Canary re-lane 2026-08-25: pct_sense_check must be weak/warn and must
        NOT join the tight-fail (blocker) set -- PROV_TIGHT_FAIL is frozen by the
        ledger_error_verdict parity test."""
        import scripts.shadow_adapter as adp
        assert "pct_sense_check" in adp.PROV_WEAK_WARN
        assert "pct_sense_check" not in adp.PROV_TIGHT_FAIL
        assert "filing_mismatch" in adp.PROV_TIGHT_FAIL  # monetary mismatches stay blockers


class TestSourceReconFeed:
    """_source_recon_select FV semantics (ranking-input bug, 2026-09-04)."""

    def _run(self, monkeypatch, tmp_path, res_df, so_df=None):
        import scripts.shadow_adapter as adp
        res = tmp_path / "source_reconciliation_residual_classification.csv"
        res_df.to_csv(res, index=False)
        monkeypatch.setattr(
            adp, "SOURCE_RECONCILIATION_RESIDUAL_CLASSIFICATION_FILE", res,
            raising=False)
        so = tmp_path / "source_reconciliation_source_only_detail.csv"
        if so_df is None:
            so_df = pd.DataFrame(columns=[
                "cik", "report_date", "mechanism", "is_blocking",
                "confidence", "source_fair_value"])
        so_df.to_csv(so, index=False)
        monkeypatch.setattr(
            adp, "SOURCE_RECONCILIATION_SOURCE_ONLY_DETAIL_FILE", so,
            raising=False)
        frag = adp._source_recon_select()
        assert frag is not None
        return duckdb.connect().execute(frag).fetchdf()

    def _res_row(self, **kw):
        base = {
            "cik": "0001930087", "report_date": "2026-03-31",
            "mechanism": "blocking_pipeline_only_position",
            "blocking_issue": True, "confidence": "high",
            "affected_source_fair_value": 0.0,
            "affected_output_fair_value": 0.0,
        }
        return {**base, **kw}

    def test_pipeline_only_packet_ranks_by_output_fv(self, monkeypatch, tmp_path):
        # extra_in_pipeline packets have NO source fact: source FV is 0 by
        # definition and the money sits in affected_output_fair_value (Golub
        # Maverick rows, 98.395M). The ledger metric must not read 0.
        res = pd.DataFrame([self._res_row(
            affected_output_fair_value=98_395_000.0)])
        out = self._run(monkeypatch, tmp_path, res)
        row = out[out["rule_name"] == "blocking_pipeline_only_position"].iloc[0]
        assert row["metric"] == 98.4          # $M, rounded 2dp

    def test_missing_from_pipeline_packet_keeps_source_fv(self, monkeypatch, tmp_path):
        res = pd.DataFrame([self._res_row(
            mechanism="blocking_source_position_like_parser_mismatch",
            affected_source_fair_value=527_833_000.0)])
        out = self._run(monkeypatch, tmp_path, res)
        row = out[out["rule_name"] ==
                  "blocking_source_position_like_parser_mismatch"].iloc[0]
        assert row["metric"] == 527.83

    def test_mixed_packet_takes_greater_side(self, monkeypatch, tmp_path):
        res = pd.DataFrame([self._res_row(
            mechanism="blocking_fair_value_disagreement",
            affected_source_fair_value=10_620_000.0,
            affected_output_fair_value=4_000_000.0)])
        out = self._run(monkeypatch, tmp_path, res)
        row = out[out["rule_name"] == "blocking_fair_value_disagreement"].iloc[0]
        assert row["metric"] == 10.62

    def test_non_blocking_rows_excluded(self, monkeypatch, tmp_path):
        res = pd.DataFrame([self._res_row(
            blocking_issue=False, affected_output_fair_value=1_000_000.0)])
        out = self._run(monkeypatch, tmp_path, res)
        assert out.empty
