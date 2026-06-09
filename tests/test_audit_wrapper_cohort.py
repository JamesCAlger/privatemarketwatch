"""Tests for the wrapper V1 cohort audit script."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from scripts.audit_wrapper_cohort import (
    _setup_duckdb,
    audit_classification_dist,
    audit_corrections,
    audit_fv_coverage,
    audit_pct_of_net_assets,
    audit_position_counts,
    audit_provenance_completeness,
    audit_source_reconciliation,
    audit_wrapper_spec_complexity,
    audit_wrapper_vs_global,
    build_audit_detail,
    build_audit_quarterly,
    compute_risk_score,
    run_audit,
)
from scripts.wrapper_v1_quality_gate import CohortEntry


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

COHORT_SIZE = 39


def _cik(n: int) -> str:
    return str(n).zfill(10)


def _make_manifest(path: Path, ciks: list[str]) -> Path:
    manifest = path / "manifest.json"
    manifest.write_text(
        json.dumps({
            "schema_version": "wrapper-cohort-manifest.v1",
            "cohort_id": "test_audit",
            "cohort_basis": "unit_test",
            "entries": [
                {"rank": i + 1, "cik": cik, "wrapper_file": f"{cik}.json"}
                for i, cik in enumerate(ciks)
            ],
        }),
        encoding="utf-8",
    )
    return manifest


def _make_holdings_csv(path: Path, rows: list[dict]) -> Path:
    f = path / "private_markets_holdings.csv"
    pd.DataFrame(rows).to_csv(f, index=False)
    return f


def _make_fund_financials_csv(path: Path, rows: list[dict]) -> Path:
    f = path / "fund_financials.csv"
    pd.DataFrame(rows).to_csv(f, index=False)
    return f


def _make_source_recon_metrics_csv(path: Path, rows: list[dict]) -> Path:
    f = path / "source_reconciliation_metrics.csv"
    pd.DataFrame(rows).to_csv(f, index=False)
    return f


def _make_source_recon_residual_csv(path: Path, rows: list[dict]) -> Path:
    f = path / "source_reconciliation_residual_classification.csv"
    pd.DataFrame(rows).to_csv(f, index=False)
    return f


def _make_wrapper_json(wrapper_dir: Path, cik: str, **overrides) -> Path:
    spec = {
        "schema_version": "bdc-xbrl-wrapper.v3",
        "cik": cik,
        "entity_name": f"Test Entity {cik}",
        "version": 1,
        "source": "bdc_xbrl",
        "dispatch": {
            "rule_prefix": "TEST",
            "prefix_rules": {},
            "leaf_markers_by_family": {},
            "aggregate_markers": [],
        },
        "archetypes": {"debt": {}, "equity": {}},
        "invariants": {"fv_reconciliation": {}},
    }
    spec.update(overrides)
    wrapper_dir.mkdir(parents=True, exist_ok=True)
    f = wrapper_dir / f"{cik}.json"
    f.write_text(json.dumps(spec), encoding="utf-8")
    return f


def _standard_ciks() -> list[str]:
    return [_cik(i) for i in range(1, COHORT_SIZE + 1)]


def _standard_entries(ciks: list[str] | None = None) -> list[CohortEntry]:
    if ciks is None:
        ciks = _standard_ciks()
    return [
        CohortEntry(rank=i + 1, cik=cik, wrapper_file=f"{cik}.json")
        for i, cik in enumerate(ciks)
    ]


# ---------------------------------------------------------------------------
# Test: source reconciliation
# ---------------------------------------------------------------------------

class TestSourceReconciliation:
    def test_calibrated_rate_and_residual_blocking(self, tmp_path):
        """Audit uses calibrated rate and residual-based blocking counts."""
        ciks = _standard_ciks()
        cik1, cik2 = ciks[0], ciks[1]

        # Metrics has raw and calibrated rates, plus metrics-level blocking
        recon = _make_source_recon_metrics_csv(tmp_path, [
            {
                "cik": cik1, "entity_name": "Fund A",
                "report_date": "2025-03-31",
                "reconciled_source_row_rate": "0.70",
                "calibrated_reconciled_source_row_rate": "0.98",
                "blocking_issue_count": "10",
                "diagnostic_issue_count": "1",
            },
            {
                "cik": cik1, "entity_name": "Fund A",
                "report_date": "2024-12-31",
                "reconciled_source_row_rate": "0.60",
                "calibrated_reconciled_source_row_rate": "0.92",
                "blocking_issue_count": "15",
                "diagnostic_issue_count": "3",
            },
            {
                "cik": cik2, "entity_name": "Fund B",
                "report_date": "2025-03-31",
                "reconciled_source_row_rate": "0.80",
                "calibrated_reconciled_source_row_rate": "1.0",
                "blocking_issue_count": "5",
                "diagnostic_issue_count": "0",
            },
        ])

        # Residual has actual blocking issues (much fewer than metrics)
        residual = _make_source_recon_residual_csv(tmp_path, [
            {
                "cik": cik1, "entity_name": "Fund A",
                "report_date": "2025-03-31",
                "blocking_issue": "True",
                "mechanism": "blocking_source_position_like_parser_mismatch",
                "issue_count": "2",
            },
            {
                "cik": cik1, "entity_name": "Fund A",
                "report_date": "2025-03-31",
                "blocking_issue": "False",
                "mechanism": "documented_source_total_header",
                "issue_count": "8",
            },
        ])

        con = _setup_duckdb(
            ciks,
            holdings_path=tmp_path / "nonexistent.csv",
            fund_financials_path=tmp_path / "nonexistent.csv",
            source_recon_metrics_path=recon,
            source_recon_residual_path=residual,
        )
        per_cik, per_q = audit_source_reconciliation(con)
        con.close()

        assert len(per_cik) == 2
        row1 = per_cik[per_cik["cik"] == cik1].iloc[0]
        assert row1["recon_quarter_count"] == 2
        # avg_reconciled_rate uses calibrated: (0.98 + 0.92) / 2 = 0.95
        assert abs(row1["avg_reconciled_rate"] - 0.95) < 0.01
        # avg_raw_reconciled_rate: (0.70 + 0.60) / 2 = 0.65
        assert abs(row1["avg_raw_reconciled_rate"] - 0.65) < 0.01
        # total_blocking_issues from residual: only 2 (the True row)
        assert row1["total_blocking_issues"] == 2
        # total_blocking_issues_metrics: 10 + 15 = 25
        assert row1["total_blocking_issues_metrics"] == 25

        row2 = per_cik[per_cik["cik"] == cik2].iloc[0]
        # No residual blocking rows for cik2
        assert row2["total_blocking_issues"] == 0
        # But metrics says 5
        assert row2["total_blocking_issues_metrics"] == 5

        assert len(per_q) == 3

    def test_falls_back_to_raw_rate(self, tmp_path):
        """When calibrated rate column is missing, falls back to raw."""
        ciks = _standard_ciks()
        cik1 = ciks[0]
        recon = _make_source_recon_metrics_csv(tmp_path, [
            {
                "cik": cik1, "entity_name": "Fund A",
                "report_date": "2025-03-31",
                "reconciled_source_row_rate": "0.85",
                "blocking_issue_count": "3",
                "diagnostic_issue_count": "1",
            },
        ])

        con = _setup_duckdb(
            ciks,
            holdings_path=tmp_path / "x.csv",
            fund_financials_path=tmp_path / "x.csv",
            source_recon_metrics_path=recon,
            source_recon_residual_path=tmp_path / "x.csv",
        )
        per_cik, _ = audit_source_reconciliation(con)
        con.close()

        row = per_cik[per_cik["cik"] == cik1].iloc[0]
        # Without calibrated column, uses raw rate
        assert abs(row["avg_reconciled_rate"] - 0.85) < 0.01

    def test_missing_file(self, tmp_path):
        ciks = _standard_ciks()
        con = _setup_duckdb(
            ciks,
            holdings_path=tmp_path / "x.csv",
            fund_financials_path=tmp_path / "x.csv",
            source_recon_metrics_path=tmp_path / "x.csv",
            source_recon_residual_path=tmp_path / "x.csv",
        )
        per_cik, per_q = audit_source_reconciliation(con)
        con.close()
        assert per_cik.empty
        assert per_q.empty


# ---------------------------------------------------------------------------
# Test: FV coverage
# ---------------------------------------------------------------------------

class TestFVCoverage:
    def test_ratio_calculation(self, tmp_path):
        ciks = _standard_ciks()
        cik1 = ciks[0]
        holdings = _make_holdings_csv(tmp_path, [
            {"cik": cik1, "report_date": "2025-03-31", "fair_value": "1000000",
             "entity_name": "A", "index_classification": "DL", "asset_class": "PC"},
            {"cik": cik1, "report_date": "2025-03-31", "fair_value": "500000",
             "entity_name": "A", "index_classification": "DL", "asset_class": "PC"},
        ])
        financials = _make_fund_financials_csv(tmp_path, [
            {"cik": cik1, "report_date": "2025-03-31", "total_assets": "2000000"},
        ])

        con = _setup_duckdb(
            ciks,
            holdings_path=holdings,
            fund_financials_path=financials,
            source_recon_metrics_path=tmp_path / "x.csv",
            source_recon_residual_path=tmp_path / "x.csv",
        )
        result = audit_fv_coverage(con)
        con.close()

        assert len(result) == 1
        row = result.iloc[0]
        assert row["holdings_fv_sum"] == 1500000
        assert row["total_assets"] == 2000000
        assert abs(row["fv_coverage_ratio"] - 0.75) < 0.01

    def test_missing_holdings(self, tmp_path):
        ciks = _standard_ciks()
        con = _setup_duckdb(
            ciks,
            holdings_path=tmp_path / "x.csv",
            fund_financials_path=tmp_path / "x.csv",
            source_recon_metrics_path=tmp_path / "x.csv",
            source_recon_residual_path=tmp_path / "x.csv",
        )
        result = audit_fv_coverage(con)
        con.close()
        assert result.empty


# ---------------------------------------------------------------------------
# Test: position counts & volatility
# ---------------------------------------------------------------------------

class TestPositionCounts:
    def test_volatility_detection(self, tmp_path):
        ciks = _standard_ciks()
        cik1 = ciks[0]
        # Q1: 100 positions, Q2: 300 positions (3x -> volatile)
        rows = (
            [{"cik": cik1, "report_date": "2025-03-31", "entity_name": "A"}]
            * 100
            + [{"cik": cik1, "report_date": "2025-06-30", "entity_name": "A"}]
            * 300
        )
        holdings = _make_holdings_csv(tmp_path, rows)

        con = _setup_duckdb(
            ciks,
            holdings_path=holdings,
            fund_financials_path=tmp_path / "x.csv",
            source_recon_metrics_path=tmp_path / "x.csv",
            source_recon_residual_path=tmp_path / "x.csv",
        )
        per_cik, per_q = audit_position_counts(con)
        con.close()

        assert len(per_cik) == 1
        assert per_cik.iloc[0]["volatile_quarters"] >= 1

        q2 = per_q[(per_q["cik"] == cik1) & (per_q["report_date"] == "2025-06-30")]
        assert q2.iloc[0]["volatile"] is True or q2.iloc[0]["volatile"] == 1

    def test_stable_counts(self, tmp_path):
        ciks = _standard_ciks()
        cik1 = ciks[0]
        rows = (
            [{"cik": cik1, "report_date": "2025-03-31", "entity_name": "A"}]
            * 100
            + [{"cik": cik1, "report_date": "2025-06-30", "entity_name": "A"}]
            * 110
        )
        holdings = _make_holdings_csv(tmp_path, rows)

        con = _setup_duckdb(
            ciks,
            holdings_path=holdings,
            fund_financials_path=tmp_path / "x.csv",
            source_recon_metrics_path=tmp_path / "x.csv",
            source_recon_residual_path=tmp_path / "x.csv",
        )
        per_cik, _ = audit_position_counts(con)
        con.close()

        assert per_cik.iloc[0]["volatile_quarters"] == 0


# ---------------------------------------------------------------------------
# Test: classification distribution
# ---------------------------------------------------------------------------

class TestClassificationDist:
    def test_unclassified_pct(self, tmp_path):
        ciks = _standard_ciks()
        cik1 = ciks[0]
        rows = [
            {"cik": cik1, "report_date": "2025-03-31",
             "index_classification": "DIRECT_LENDING",
             "entity_name": "A", "asset_class": "PC"},
        ] * 8 + [
            {"cik": cik1, "report_date": "2025-03-31",
             "index_classification": "",
             "entity_name": "A", "asset_class": "PC"},
        ] * 2
        holdings = _make_holdings_csv(tmp_path, rows)

        con = _setup_duckdb(
            ciks,
            holdings_path=holdings,
            fund_financials_path=tmp_path / "x.csv",
            source_recon_metrics_path=tmp_path / "x.csv",
            source_recon_residual_path=tmp_path / "x.csv",
        )
        result = audit_classification_dist(con)
        con.close()

        row = result[result["cik"] == cik1].iloc[0]
        assert row["total_positions"] == 10
        assert row["unclassified_count"] == 2
        assert abs(row["unclassified_pct"] - 0.2) < 0.01


# ---------------------------------------------------------------------------
# Test: wrapper vs global agreement (fallback proxy)
# ---------------------------------------------------------------------------

class TestWrapperVsGlobal:
    def test_disagreement_detection(self, tmp_path):
        ciks = _standard_ciks()
        cik1 = ciks[0]
        rows = [
            # Loan classified as EQUITY -> disagreement
            {"cik": cik1, "report_date": "2025-03-31",
             "asset_category": "LOAN", "asset_class": "PRIVATE_EQUITY",
             "entity_name": "A", "index_classification": "DL"},
            # Loan classified as PRIVATE_CREDIT -> agreement
            {"cik": cik1, "report_date": "2025-03-31",
             "asset_category": "LOAN", "asset_class": "PRIVATE_CREDIT",
             "entity_name": "A", "index_classification": "DL"},
        ]
        holdings = _make_holdings_csv(tmp_path, rows)

        con = _setup_duckdb(
            ciks,
            holdings_path=holdings,
            fund_financials_path=tmp_path / "x.csv",
            source_recon_metrics_path=tmp_path / "x.csv",
            source_recon_residual_path=tmp_path / "x.csv",
        )
        result = audit_wrapper_vs_global(con)
        con.close()

        row = result[result["cik"] == cik1].iloc[0]
        assert row["disagreement_count"] == 1
        assert abs(row["disagreement_pct"] - 0.5) < 0.01

    def test_no_asset_category(self, tmp_path):
        ciks = _standard_ciks()
        rows = [
            {"cik": ciks[0], "report_date": "2025-03-31",
             "asset_class": "PRIVATE_CREDIT",
             "entity_name": "A", "index_classification": "DL"},
        ]
        holdings = _make_holdings_csv(tmp_path, rows)

        con = _setup_duckdb(
            ciks,
            holdings_path=holdings,
            fund_financials_path=tmp_path / "x.csv",
            source_recon_metrics_path=tmp_path / "x.csv",
            source_recon_residual_path=tmp_path / "x.csv",
        )
        result = audit_wrapper_vs_global(con)
        con.close()

        # No asset_category column -> should return empty-ish result
        assert result.empty or result["total_classified"].sum() == 0


# ---------------------------------------------------------------------------
# Test: corrections
# ---------------------------------------------------------------------------

class TestCorrections:
    def test_counts(self, tmp_path):
        ciks = _standard_ciks()
        cik1, cik2 = ciks[0], ciks[1]

        row_corr = tmp_path / "row_corrections.csv"
        pd.DataFrame([
            {"cik": cik1, "field": "fair_value", "value": "100"},
            {"cik": cik1, "field": "fair_value", "value": "200"},
            {"cik": cik2, "field": "fair_value", "value": "300"},
        ]).to_csv(row_corr, index=False)

        strat_corr = tmp_path / "fund_strategy_correction_candidates.csv"
        pd.DataFrame([
            {"cik": cik1, "correction_status": "APPLY"},
            {"cik": cik1, "correction_status": "SKIP"},
        ]).to_csv(strat_corr, index=False)

        result = audit_corrections(
            ciks,
            row_corrections_path=row_corr,
            strategy_corrections_path=strat_corr,
        )

        r1 = result[result["cik"] == cik1].iloc[0]
        assert r1["row_correction_count"] == 2
        assert r1["strategy_correction_count"] == 1  # only APPLY

        r2 = result[result["cik"] == cik2].iloc[0]
        assert r2["row_correction_count"] == 1
        assert r2["strategy_correction_count"] == 0

    def test_missing_files(self, tmp_path):
        ciks = _standard_ciks()
        result = audit_corrections(
            ciks,
            row_corrections_path=tmp_path / "x.csv",
            strategy_corrections_path=tmp_path / "x.csv",
        )
        assert len(result) == COHORT_SIZE
        assert result["row_correction_count"].sum() == 0


# ---------------------------------------------------------------------------
# Test: provenance (graceful degradation)
# ---------------------------------------------------------------------------

class TestProvenance:
    def test_missing_provenance_file(self, tmp_path):
        ciks = _standard_ciks()
        con = _setup_duckdb(
            ciks,
            holdings_path=tmp_path / "x.csv",
            fund_financials_path=tmp_path / "x.csv",
            source_recon_metrics_path=tmp_path / "x.csv",
            source_recon_residual_path=tmp_path / "x.csv",
        )
        result = audit_provenance_completeness(
            con, provenance_path=tmp_path / "nonexistent.csv"
        )
        con.close()

        assert len(result) == COHORT_SIZE
        assert (result["provenance_status"] == "not_available").all()
        assert (result["full_chain_pct"] == 0.0).all()


# ---------------------------------------------------------------------------
# Test: pct_of_net_assets
# ---------------------------------------------------------------------------

class TestPctOfNetAssets:
    def test_flags(self, tmp_path):
        ciks = _standard_ciks()
        cik1 = ciks[0]
        rows = [
            {"cik": cik1, "report_date": "2025-03-31",
             "pct_of_net_assets": "60", "entity_name": "A"},
            {"cik": cik1, "report_date": "2025-03-31",
             "pct_of_net_assets": "70", "entity_name": "A"},
        ]
        holdings = _make_holdings_csv(tmp_path, rows)

        con = _setup_duckdb(
            ciks,
            holdings_path=holdings,
            fund_financials_path=tmp_path / "x.csv",
            source_recon_metrics_path=tmp_path / "x.csv",
            source_recon_residual_path=tmp_path / "x.csv",
        )
        result = audit_pct_of_net_assets(con)
        con.close()

        row = result[result["cik"] == cik1].iloc[0]
        assert row["pct_sum"] == 130
        assert row["pct_flag"] == "HIGH"


# ---------------------------------------------------------------------------
# Test: wrapper spec complexity
# ---------------------------------------------------------------------------

class TestWrapperSpecComplexity:
    def test_parses_spec(self, tmp_path):
        wrapper_dir = tmp_path / "wrappers"
        cik1 = _cik(1)
        _make_wrapper_json(wrapper_dir, cik1, version=2, dispatch={
            "rule_prefix": "TEST",
            "prefix_rules": {"r1": {}, "r2": {}, "r3": {}},
            "leaf_markers_by_family": {"debt": [], "equity": []},
            "aggregate_markers": ["Total", "Subtotal"],
        })

        entries = [CohortEntry(rank=1, cik=cik1, wrapper_file=f"{cik1}.json")]
        result = audit_wrapper_spec_complexity(entries, wrapper_dir=wrapper_dir)

        row = result.iloc[0]
        assert bool(row["wrapper_exists"]) is True
        assert row["wrapper_version"] == 2
        assert row["prefix_rule_count"] == 3
        assert row["leaf_marker_family_count"] == 2
        assert row["aggregate_marker_count"] == 2

    def test_missing_wrapper(self, tmp_path):
        wrapper_dir = tmp_path / "wrappers"
        wrapper_dir.mkdir()
        cik1 = _cik(1)
        entries = [CohortEntry(rank=1, cik=cik1, wrapper_file=f"{cik1}.json")]
        result = audit_wrapper_spec_complexity(entries, wrapper_dir=wrapper_dir)

        assert bool(result.iloc[0]["wrapper_exists"]) is False


# ---------------------------------------------------------------------------
# Test: risk scoring
# ---------------------------------------------------------------------------

class TestRiskScoring:
    def test_zero_risk(self):
        df = pd.DataFrame([{
            "avg_reconciled_rate": 1.0,
            "total_blocking_issues": 0,
            "unclassified_pct": 0.0,
            "fv_coverage_ratio": 1.0,
            "volatile_quarters": 0,
            "total_quarters": 4,
            "disagreement_pct": 0.0,
            "full_chain_pct": 100.0,
        }])
        scores = compute_risk_score(df)
        assert scores.iloc[0] == 0.0

    def test_max_risk(self):
        df = pd.DataFrame([{
            "avg_reconciled_rate": 0.0,
            "total_blocking_issues": 100,
            "unclassified_pct": 1.0,
            "fv_coverage_ratio": 0.0,
            "volatile_quarters": 4,
            "total_quarters": 4,
            "disagreement_pct": 1.0,
            "full_chain_pct": 0.0,
        }])
        scores = compute_risk_score(df)
        assert scores.iloc[0] == 100.0

    def test_partial_risk(self):
        df = pd.DataFrame([{
            "avg_reconciled_rate": 0.8,
            "total_blocking_issues": 10,
            "unclassified_pct": 0.1,
            "fv_coverage_ratio": 0.9,
            "volatile_quarters": 1,
            "total_quarters": 8,
            "disagreement_pct": 0.05,
            "full_chain_pct": 50.0,
        }])
        scores = compute_risk_score(df)
        assert 0 < scores.iloc[0] < 50

    def test_missing_columns(self):
        """Risk score should not crash when columns are absent."""
        df = pd.DataFrame([{"cik": "0000000001"}])
        scores = compute_risk_score(df)
        assert scores.iloc[0] == 0.0


# ---------------------------------------------------------------------------
# Test: build_audit_detail assembly
# ---------------------------------------------------------------------------

class TestBuildAuditDetail:
    def test_merges_all_dimensions(self):
        ciks = [_cik(1), _cik(2)]
        entries = _standard_entries(ciks + [_cik(i) for i in range(3, COHORT_SIZE + 1)])

        recon_cik = pd.DataFrame([
            {"cik": _cik(1), "recon_quarter_count": 4,
             "avg_reconciled_rate": 0.95, "avg_raw_reconciled_rate": 0.80,
             "total_blocking_issues": 2, "total_blocking_issues_metrics": 10,
             "total_diagnostic_issues": 1},
        ])
        fv_cov = pd.DataFrame([
            {"cik": _cik(1), "latest_holdings_quarter": "2025-03-31",
             "holdings_fv_sum": 1e9, "total_assets": 1.2e9,
             "fv_coverage_ratio": 0.833},
        ])
        pos_cik = pd.DataFrame([
            {"cik": _cik(1), "total_quarters": 4,
             "avg_position_count": 100, "volatile_quarters": 0},
        ])
        class_dist = pd.DataFrame([
            {"cik": _cik(1), "total_positions": 400,
             "unclassified_count": 10, "unclassified_pct": 0.025,
             "classification_breakdown": "DL=390; UNCLASSIFIED=10"},
        ])
        wrapper_global = pd.DataFrame([
            {"cik": _cik(1), "total_classified": 400,
             "disagreement_count": 5, "disagreement_pct": 0.0125},
        ])
        corrections = pd.DataFrame([
            {"cik": cik, "row_correction_count": 0,
             "strategy_correction_count": 0}
            for cik in [_cik(i) for i in range(1, COHORT_SIZE + 1)]
        ])
        provenance = pd.DataFrame([
            {"cik": cik, "provenance_status": "not_available",
             "full_chain_pct": 0.0, "total_provenance_rows": 0}
            for cik in [_cik(i) for i in range(1, COHORT_SIZE + 1)]
        ])
        wrapper_complexity = pd.DataFrame([
            {"cik": cik, "wrapper_exists": True, "wrapper_version": 1,
             "prefix_rule_count": 2, "leaf_marker_family_count": 3,
             "aggregate_marker_count": 4, "archetype_count": 2,
             "has_staging": False, "has_edge_cases": False,
             "invariant_count": 3, "schema_version": "bdc-xbrl-wrapper.v3"}
            for cik in [_cik(i) for i in range(1, COHORT_SIZE + 1)]
        ])
        gate_df = pd.DataFrame([
            {"cik": cik, "status": "PASS", "blocking_reasons": ""}
            for cik in [_cik(i) for i in range(1, COHORT_SIZE + 1)]
        ])

        detail = build_audit_detail(
            entries, recon_cik, fv_cov, pos_cik, class_dist,
            wrapper_global, corrections, provenance, wrapper_complexity,
            gate_df,
        )

        assert len(detail) == COHORT_SIZE
        assert "risk_score" in detail.columns
        assert "risk_rank" in detail.columns
        assert "gate_status" in detail.columns

        # CIK 1 should have merged data
        r1 = detail[detail["cik"] == _cik(1)].iloc[0]
        assert r1["recon_quarter_count"] == 4
        assert abs(r1["fv_coverage_ratio"] - 0.833) < 0.01


# ---------------------------------------------------------------------------
# Test: build_audit_quarterly assembly
# ---------------------------------------------------------------------------

class TestBuildAuditQuarterly:
    def test_merges_timeseries(self):
        recon_q = pd.DataFrame([
            {"cik": _cik(1), "report_date": "2025-03-31",
             "calibrated_reconciled_rate": 0.95,
             "raw_reconciled_rate": 0.80,
             "residual_blocking_issues": 2, "metrics_blocking_issues": 5,
             "diagnostic_issue_count": 1},
        ])
        pos_q = pd.DataFrame([
            {"cik": _cik(1), "report_date": "2025-03-31",
             "position_count": 100, "qoq_ratio": None, "volatile": False},
        ])
        pct_q = pd.DataFrame([
            {"cik": _cik(1), "report_date": "2025-03-31",
             "pct_sum": 98.5, "pct_flag": "OK"},
        ])

        quarterly = build_audit_quarterly(recon_q, pos_q, pct_q)
        assert len(quarterly) == 1
        row = quarterly.iloc[0]
        assert row["position_count"] == 100
        assert row["pct_sum"] == 98.5


# ---------------------------------------------------------------------------
# Test: end-to-end with synthetic data
# ---------------------------------------------------------------------------

class TestEndToEnd:
    def test_run_audit_synthetic(self, tmp_path):
        ciks = _standard_ciks()
        manifest = _make_manifest(tmp_path, ciks)

        # Create wrapper dir with one wrapper
        wrapper_dir = tmp_path / "wrappers"
        _make_wrapper_json(wrapper_dir, ciks[0])

        # Holdings with two CIKs
        holdings = _make_holdings_csv(tmp_path, [
            {"cik": ciks[0], "report_date": "2025-03-31",
             "fair_value": "1000000", "entity_name": "Fund A",
             "index_classification": "DIRECT_LENDING",
             "asset_class": "PRIVATE_CREDIT",
             "asset_category": "LOAN",
             "pct_of_net_assets": "50"},
            {"cik": ciks[0], "report_date": "2025-03-31",
             "fair_value": "500000", "entity_name": "Fund A",
             "index_classification": "",
             "asset_class": "PRIVATE_CREDIT",
             "asset_category": "LOAN",
             "pct_of_net_assets": "25"},
            {"cik": ciks[1], "report_date": "2025-03-31",
             "fair_value": "2000000", "entity_name": "Fund B",
             "index_classification": "OPPORTUNISTIC_CREDIT",
             "asset_class": "PRIVATE_CREDIT",
             "asset_category": "LOAN",
             "pct_of_net_assets": "90"},
        ])

        financials = _make_fund_financials_csv(tmp_path, [
            {"cik": ciks[0], "report_date": "2025-03-31",
             "total_assets": "2000000"},
            {"cik": ciks[1], "report_date": "2025-03-31",
             "total_assets": "2500000"},
        ])

        recon = _make_source_recon_metrics_csv(tmp_path, [
            {"cik": ciks[0], "report_date": "2025-03-31",
             "reconciled_source_row_rate": "0.7",
             "calibrated_reconciled_source_row_rate": "0.95",
             "blocking_issue_count": "10", "diagnostic_issue_count": "1"},
        ])

        # Residual: only 3 of the 10 metrics-level blockers are real
        residual = _make_source_recon_residual_csv(tmp_path, [
            {"cik": ciks[0], "report_date": "2025-03-31",
             "blocking_issue": "True",
             "mechanism": "blocking_source_position_like_parser_mismatch",
             "issue_count": "3"},
            {"cik": ciks[0], "report_date": "2025-03-31",
             "blocking_issue": "False",
             "mechanism": "documented_source_total_header",
             "issue_count": "7"},
        ])

        # Empty corrections
        row_corr = tmp_path / "row_corrections.csv"
        pd.DataFrame(columns=["cik", "field", "value"]).to_csv(
            row_corr, index=False
        )
        strat_corr = tmp_path / "fund_strategy_correction_candidates.csv"
        pd.DataFrame(
            columns=["cik", "correction_status"]
        ).to_csv(strat_corr, index=False)

        # Gate CSV
        gate = tmp_path / "quality_gate.csv"
        pd.DataFrame([
            {"cik": cik, "status": "PASS", "blocking_reasons": ""}
            for cik in ciks
        ]).to_csv(gate, index=False)

        detail_out = tmp_path / "detail.csv"
        quarterly_out = tmp_path / "quarterly.csv"
        report_out = tmp_path / "report.md"

        detail, quarterly = run_audit(
            manifest_path=manifest,
            wrapper_dir=wrapper_dir,
            holdings_path=holdings,
            fund_financials_path=financials,
            source_recon_metrics_path=recon,
            source_recon_residual_path=residual,
            row_corrections_path=row_corr,
            strategy_corrections_path=strat_corr,
            provenance_path=tmp_path / "nonexistent_prov.csv",
            quality_gate_path=gate,
            detail_out=detail_out,
            quarterly_out=quarterly_out,
            report_out=report_out,
        )

        # Artifacts written
        assert detail_out.exists()
        assert quarterly_out.exists()
        assert report_out.exists()

        # Detail has all CIKs
        assert len(detail) == COHORT_SIZE

        # Risk scores computed
        assert "risk_score" in detail.columns
        assert detail["risk_score"].notna().all()

        # CIK with blocking issues should rank higher risk
        r0 = detail[detail["cik"] == ciks[0]].iloc[0]
        # Residual blocking: only the 3 True rows, not the 10 from metrics
        assert r0["total_blocking_issues"] == 3
        assert r0["total_blocking_issues_metrics"] == 10
        # Calibrated rate used, not raw
        assert abs(r0["avg_reconciled_rate"] - 0.95) < 0.01

        # Report is valid markdown
        report_text = report_out.read_text(encoding="utf-8")
        assert "# Wrapper V1 Cohort Audit Report" in report_text
        assert "## Risk Rankings" in report_text
        assert "## Per-CIK Detail" in report_text
