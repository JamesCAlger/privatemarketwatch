"""Tests for scripts/match_gold/build_packets.py chain packet sampler."""
import pandas as pd

from tests.test_match_quality import _edge, _edges, _holdings, _row
from scripts.match_gold import build_packets as bp


def _chain_fixture():
    holdings = _holdings([
        _row("0000000001", "2025-03-31", "Acme Corp", 100.0, "POS-1", "ROW-a"),
        _row("0000000001", "2025-06-30", "Acme Corp", 101.0, "POS-1", "ROW-b"),
        _row("0000000001", "2025-03-31", "Beta LLC", 50.0, "POS-2", "ROW-c"),
        _row("0000000001", "2025-06-30", "Beta LLC", 900.0, "POS-2", "ROW-d"),
    ])
    edges = _edges([
        _edge("POS-1", "B2_exact_name", 100.0, 101.0),
        _edge("POS-2", "D_fuzzy", 50.0, 900.0),   # fv-jump anomaly
    ])
    return holdings, edges


def test_sample_chains_strata_and_determinism():
    holdings, edges = _chain_fixture()
    s1 = bp.sample_chains(holdings, edges, per_tier=5, n_fv_jump=5,
                          n_interior_singleton=5, n_drift_break=5)
    s2 = bp.sample_chains(holdings, edges, per_tier=5, n_fv_jump=5,
                          n_interior_singleton=5, n_drift_break=5)
    pd.testing.assert_frame_equal(s1, s2)          # deterministic
    assert set(s1["stratum"]) >= {"tier_random", "fv_jump"}
    # POS-2 must appear in the fv_jump stratum
    assert "POS-2" in set(s1[s1["stratum"] == "fv_jump"]["position_id"])


def test_no_duplicate_packet_for_same_pid_and_stratum():
    holdings, edges = _chain_fixture()
    s = bp.sample_chains(holdings, edges, per_tier=5, n_fv_jump=5,
                         n_interior_singleton=5, n_drift_break=5)
    assert not s.duplicated(["stratum", "position_id"]).any()


def test_sample_entities_near_miss_pair():
    holdings = _holdings([
        _row("0000000001", "2025-06-30", "Acme Corp", 10.0, "POS-1", "ROW-a"),
        _row("0000000002", "2025-06-30", "Acme Co", 20.0, "POS-2", "ROW-b"),  # near-miss variant, different fund (JW=0.9556)
        _row("0000000001", "2025-06-30", "Zebra Partners", 10.0, "POS-3", "ROW-c"),
    ])
    s = bp.sample_entities(holdings)
    near = s[s["stratum"] == "cross_fund_near_miss"]
    assert len(near) == 1
    assert near.iloc[0]["ciks"] == "0000000001;0000000002"


def test_sample_entities_merge_verify_cross_fund_cluster():
    holdings = _holdings([
        _row("0000000001", "2025-06-30", "Acme Corp", 10.0, "POS-1", "ROW-a",
             entity_id="ENT-1"),
        _row("0000000002", "2025-06-30", "Acme Corporation", 20.0, "POS-2", "ROW-b",
             entity_id="ENT-1"),
    ])
    s = bp.sample_entities(holdings)
    mv = s[s["stratum"] == "entity_merge_verify"]
    assert list(mv["cluster_key"]) == ["ENT-1"]


def test_sample_entities_deterministic():
    holdings = _holdings([
        _row("0000000001", "2025-06-30", "Acme Corp", 10.0, "POS-1", "ROW-a"),
        _row("0000000002", "2025-06-30", "Acme Co", 20.0, "POS-2", "ROW-b"),
    ])
    pd.testing.assert_frame_equal(bp.sample_entities(holdings),
                                  bp.sample_entities(holdings))
