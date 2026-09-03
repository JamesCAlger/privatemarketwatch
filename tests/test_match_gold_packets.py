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
