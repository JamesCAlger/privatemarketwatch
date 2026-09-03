"""Tests for pipeline/match_quality.py deterministic metrics."""
import pandas as pd
import pytest

from pipeline import match_quality as mq

HOLDING_COLS = [
    "source", "cik", "report_date", "issuer_name", "fair_value",
    "position_id", "row_id", "index_classification", "interest_rate",
    "maturity_date", "entity_id",
]


def _holdings(rows: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(rows)
    for c in HOLDING_COLS:
        if c not in df.columns:
            df[c] = None
    return df[HOLDING_COLS]


def _row(cik, date, issuer, fv, pid, rid, **kw):
    base = {
        "source": "bdc", "cik": cik, "report_date": date, "issuer_name": issuer,
        "fair_value": fv, "position_id": pid, "row_id": rid,
        "index_classification": "DIRECT_LENDING",
    }
    base.update(kw)
    return base


EDGE_COLS = ["edge_type", "position_id", "cik", "source", "begin_report_date",
             "begin_quarter", "begin_issuer_name", "begin_fair_value",
             "end_report_date", "end_quarter", "end_issuer_name",
             "end_fair_value", "match_method", "match_key", "match_score",
             "span_months"]


def _edges(rows: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(rows)
    for c in EDGE_COLS:
        if c not in df.columns:
            df[c] = None
    return df[EDGE_COLS]


def _edge(pid, method, bfv, efv, cik="0000000001"):
    return {"edge_type": "match_pair", "position_id": pid, "cik": cik,
            "source": "bdc", "begin_fair_value": bfv, "end_fair_value": efv,
            "match_method": method, "begin_report_date": "2025-03-31",
            "end_report_date": "2025-06-30"}


class TestChainContinuity:
    def test_continued_and_dropped_rows(self):
        # CIK A: q1 has 2 rows; one continues into q2 (same position_id), one does not.
        df = _holdings([
            _row("0000000001", "2025-03-31", "Acme Corp", 100.0, "POS-1", "ROW-a"),
            _row("0000000001", "2025-03-31", "Beta LLC", 50.0, "POS-2", "ROW-b"),
            _row("0000000001", "2025-06-30", "Acme Corp", 101.0, "POS-1", "ROW-c"),
        ])
        out = mq.chain_continuity(df)
        all_row = out[(out["scope_type"] == "ALL")].iloc[0]
        # q2 rows are terminal (no later quarter) -> only the 2 q1 rows are eligible
        assert all_row["denominator"] == 2
        assert all_row["numerator"] == 1
        assert all_row["value"] == pytest.approx(0.5)

    def test_zero_fv_rows_excluded(self):
        df = _holdings([
            _row("0000000001", "2025-03-31", "Acme Corp", 0.0, "POS-1", "ROW-a"),
            _row("0000000001", "2025-06-30", "Acme Corp", 10.0, "POS-1", "ROW-b"),
        ])
        out = mq.chain_continuity(df)
        assert out[(out["scope_type"] == "ALL")].iloc[0]["denominator"] == 0

    def test_nport_rows_excluded(self):
        df = _holdings([
            _row("0000000001", "2025-03-31", "Acme Corp", 10.0, "POS-1", "ROW-a",
                 source="nport"),
            _row("0000000001", "2025-06-30", "Acme Corp", 10.0, "POS-1", "ROW-b",
                 source="nport"),
        ])
        out = mq.chain_continuity(df)
        assert out[(out["scope_type"] == "ALL")].iloc[0]["denominator"] == 0


class TestSingletonDecomposition:
    def test_classes(self):
        df = _holdings([
            # interior suspicious singleton: has quarters before and after, positive FV
            _row("0000000001", "2025-03-31", "Acme Corp", 10.0, "POS-1", "ROW-a"),
            _row("0000000001", "2025-06-30", "Lone Star", 20.0, "POS-9", "ROW-b"),
            _row("0000000001", "2025-09-30", "Acme Corp", 11.0, "POS-1", "ROW-c"),
            # terminal-quarter singleton
            _row("0000000001", "2025-09-30", "Newco Inc", 5.0, "POS-8", "ROW-d"),
            # zero-FV singleton
            _row("0000000001", "2025-06-30", "Zero Co", 0.0, "POS-7", "ROW-e"),
            # negative-FV singleton
            _row("0000000001", "2025-06-30", "Neg Co", -3.0, "POS-6", "ROW-f"),
        ])
        out = mq.singleton_decomposition(df)
        by_scope = out.set_index("scope")
        assert by_scope.loc["interior_suspicious", "numerator"] == 1
        assert by_scope.loc["terminal_quarter", "numerator"] == 1
        assert by_scope.loc["zero_or_null_fv", "numerator"] == 1
        assert by_scope.loc["negative_fv", "numerator"] == 1
        # denominator = total singletons everywhere
        assert (out["denominator"] == 4).all()


class TestEdgeAnomalies:
    def test_fv_jump_flagged_per_tier(self):
        edges = _edges([
            _edge("POS-1", "B2_exact_name", 100.0, 110.0),   # normal
            _edge("POS-2", "B2_exact_name", 100.0, 900.0),   # 9x jump -> anomaly
            _edge("POS-3", "D_fuzzy", 50.0, 55.0),           # normal
        ])
        out = mq.edge_anomalies(edges)
        b2 = out[out["scope"] == "B2_exact_name"].iloc[0]
        assert b2["numerator"] == 1 and b2["denominator"] == 2
        d = out[out["scope"] == "D_fuzzy"].iloc[0]
        assert d["numerator"] == 0 and d["denominator"] == 1


class TestDriftBreakCandidates:
    def test_detects_rename_pair(self):
        df = _holdings([
            # chain POS-1 stops at q1 under name "Acme Corp" ...
            _row("0000000001", "2025-03-31", "Acme Corp", 100.0, "POS-1", "ROW-a",
                 interest_rate=10.0, maturity_date="2029-01-15"),
            # ... and a brand-new chain starts q2 as "Acme Holdings" with same terms
            _row("0000000001", "2025-06-30", "Acme Holdings", 102.0, "POS-2", "ROW-b",
                 interest_rate=10.0, maturity_date="2029-01-15"),
            # unrelated stable chain so q2 is not terminal-only noise
            _row("0000000001", "2025-03-31", "Beta LLC", 50.0, "POS-3", "ROW-c"),
            _row("0000000001", "2025-06-30", "Beta LLC", 51.0, "POS-3", "ROW-d"),
        ])
        cands = mq.drift_break_candidates(df)
        assert len(cands) == 1
        assert cands.iloc[0]["dropped_row_id"] == "ROW-a"
        assert cands.iloc[0]["start_row_id"] == "ROW-b"

    def test_different_terms_not_candidate(self):
        df = _holdings([
            _row("0000000001", "2025-03-31", "Acme Corp", 100.0, "POS-1", "ROW-a",
                 interest_rate=10.0, maturity_date="2029-01-15"),
            _row("0000000001", "2025-06-30", "Gamma Inc", 300.0, "POS-2", "ROW-b",
                 interest_rate=6.0, maturity_date="2027-06-01"),
        ])
        assert len(mq.drift_break_candidates(df)) == 0

    def test_fanout_bounded_to_best_fv_ratio(self):
        """Dropped row with TWO qualifying starts must yield exactly 1 candidate pair
        (the one with FV ratio closest to 1.0)."""
        df = _holdings([
            # chain POS-1 stops at q1 under name "Acme Corp" at FV 100
            _row("0000000001", "2025-03-31", "Acme Corp", 100.0, "POS-1", "ROW-a",
                 interest_rate=10.0, maturity_date="2029-01-15"),
            # q2: two starts with same CIK, classification, maturity, interest_rate
            # Start 1: "Acme Holdings" at FV 98 (ratio 0.98, BEST match to 1.0)
            _row("0000000001", "2025-06-30", "Acme Holdings", 98.0, "POS-2", "ROW-b",
                 interest_rate=10.0, maturity_date="2029-01-15"),
            # Start 2: "Acme Inc" at FV 120 (ratio 1.20, worse match)
            _row("0000000001", "2025-06-30", "Acme Inc", 120.0, "POS-3", "ROW-c",
                 interest_rate=10.0, maturity_date="2029-01-15"),
            # unrelated stable chain so q2 is not terminal-only noise
            _row("0000000001", "2025-03-31", "Beta LLC", 50.0, "POS-4", "ROW-d"),
            _row("0000000001", "2025-06-30", "Beta LLC", 51.0, "POS-4", "ROW-e"),
        ])
        cands = mq.drift_break_candidates(df)
        assert len(cands) == 1, f"Expected 1 candidate, got {len(cands)}"
        assert cands.iloc[0]["dropped_row_id"] == "ROW-a"
        assert cands.iloc[0]["start_row_id"] == "ROW-b", \
            "Should pick ROW-b (FV 98, ratio 0.98 closest to 1.0)"
        assert cands.iloc[0]["fv_ratio"] == pytest.approx(0.98)


class TestEntityStats:
    def test_coverage_and_cross_fund(self):
        df = _holdings([
            _row("0000000001", "2025-03-31", "Acme Corp", 10.0, "POS-1", "ROW-a",
                 entity_id="ENT-1"),
            _row("0000000002", "2025-03-31", "Acme Corporation", 20.0, "POS-2", "ROW-b",
                 entity_id="ENT-1"),
            _row("0000000002", "2025-03-31", "Solo Co", 20.0, "POS-3", "ROW-c"),
        ])
        out = mq.entity_stats(df)
        cov = out[out["metric"] == "entity_coverage_rate"].iloc[0]
        assert cov["numerator"] == 2 and cov["denominator"] == 3
        xf = out[out["metric"] == "entity_cross_fund_count"].iloc[0]
        assert xf["numerator"] == 1
