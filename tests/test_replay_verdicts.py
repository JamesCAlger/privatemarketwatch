"""Tests for scripts.match_gold.replay_verdicts -- the deterministic replay
harness that explains, per matcher tier, why a gold-set pair was admitted or
vetoed."""
import json

import pandas as pd

from scripts.match_gold import replay_verdicts as rv


def _mk_batch(tmp_path):
    (tmp_path / "packets").mkdir()
    (tmp_path / "packets_meta").mkdir()
    (tmp_path / "verdicts").mkdir()
    # Chain packet: edge 0 WRONG (B2), edge 1 CONFIRMED (SUPP_B2)
    pid = "MGP-chain"
    (tmp_path / "packets" / f"{pid}.json").write_text(json.dumps({
        "packet_id": pid, "packet_type": "chain", "cik": "0000000001",
        "edges": [
            {"edge_index": 0, "begin_row_id": "ROW-a", "end_row_id": "ROW-b"},
            {"edge_index": 1, "begin_row_id": "ROW-b", "end_row_id": "ROW-c"},
        ],
        "rows": [], "candidate_rows": [],
    }), encoding="utf-8")
    (tmp_path / "packets_meta" / f"{pid}.json").write_text(json.dumps({
        "packet_id": pid, "packet_type": "chain", "stratum": "tier_random",
        "edges": [
            {"edge_index": 0, "match_method": "B2_exact_name", "match_score": "1.0"},
            {"edge_index": 1, "match_method": "SUPP_B2_unique_exact_name", "match_score": "1.0"},
        ],
    }), encoding="utf-8")
    (tmp_path / "verdicts" / f"{pid}.json").write_text(json.dumps({
        "packet_id": pid, "packet_type": "chain", "verdict": "MIXED",
        "confidence": 0.99, "rationale": "x",
        "edge_verdicts": [
            {"edge_index": 0, "verdict": "WRONG", "evidence": []},
            {"edge_index": 1, "verdict": "CONFIRMED", "evidence": []},
        ],
        "proposed_links": [], "escalate": False,
    }), encoding="utf-8-sig")
    # Singleton packet: MISSED_LINK with one usable and one null proposed link
    pid2 = "MGP-single"
    (tmp_path / "packets" / f"{pid2}.json").write_text(json.dumps({
        "packet_id": pid2, "packet_type": "chain", "cik": "0000000001",
        "edges": [], "rows": [], "candidate_rows": [],
    }), encoding="utf-8")
    (tmp_path / "packets_meta" / f"{pid2}.json").write_text(json.dumps({
        "packet_id": pid2, "packet_type": "chain",
        "stratum": "interior_singleton", "edges": [],
    }), encoding="utf-8")
    (tmp_path / "verdicts" / f"{pid2}.json").write_text(json.dumps({
        "packet_id": pid2, "packet_type": "chain", "verdict": "MISSED_LINK",
        "confidence": 0.99, "rationale": "x", "edge_verdicts": [],
        "proposed_links": [
            {"row_id_a": "ROW-d", "row_id_b": "ROW-e", "evidence": []},
            {"row_id_a": "null", "row_id_b": None, "evidence": []},
        ],
        "escalate": False,
    }), encoding="utf-8-sig")
    return tmp_path


def test_load_gold_pairs_collects_wrong_confirmed_and_missed(tmp_path):
    batch = _mk_batch(tmp_path)
    pairs, stats = rv.load_gold_pairs(batch)
    kinds = pairs.set_index(["packet_id", "row_a", "row_b"])["kind"].to_dict()
    assert kinds[("MGP-chain", "ROW-a", "ROW-b")] == "WRONG"
    assert kinds[("MGP-chain", "ROW-b", "ROW-c")] == "CONFIRMED"
    assert kinds[("MGP-single", "ROW-d", "ROW-e")] == "MISSED"
    assert len(pairs) == 3
    assert stats["unresolvable_missed"] == 1
    tiers = pairs.set_index(["row_a", "row_b"])["tier"].to_dict()
    assert tiers[("ROW-a", "ROW-b")] == "B2_exact_name"
    assert tiers[("ROW-d", "ROW-e")] == ""


def _row(row_id, report_date, name, fv, **kw):
    base = {
        "row_id": row_id, "cik": "0000000001", "source": "bdc",
        "report_date": report_date, "issuer_name": name, "fair_value": fv,
        "principal_amount": kw.get("pa", fv), "basis_spread": kw.get("bs", 5.0),
        "maturity_date": kw.get("mat", "2029-01-01"),
        "index_classification": kw.get("ic", "DIRECT_LENDING"),
        "instrument_description": kw.get("desc", "First lien term loan"),
        "cusip": kw.get("cusip", ""), "position_key": kw.get("pk", ""),
        "entity_id": kw.get("eid", "ENT-1"), "lien_position": "",
        "coupon_type": "", "asset_class": "PRIVATE_CREDIT",
    }
    return base


def test_replay_reports_fv_ratio_veto_for_exact_name_tier():
    holdings = pd.DataFrame([
        _row("ROW-a", "2024-03-31", "Acme LLC", 100.0),
        _row("ROW-b", "2024-06-30", "Acme LLC", 10000.0),
    ])
    pairs = pd.DataFrame([{"packet_id": "P", "stratum": "s", "kind": "MISSED",
                           "tier": "", "cik": "0000000001",
                           "row_a": "ROW-a", "row_b": "ROW-b", "edge_index": ""}])
    out = rv.replay_pairs(pairs, holdings)
    assert out.loc[0, "t_B2"].startswith("VETO:")
    assert "fv_ratio" in out.loc[0, "t_B2"]


def test_replay_admits_fuzzy_for_legal_suffix_variant():
    holdings = pd.DataFrame([
        _row("ROW-a", "2024-03-31", "Armstrong Bidco Ltd.", 1000.0),
        _row("ROW-b", "2024-06-30", "Armstrong Bidco Limited", 1010.0),
    ])
    pairs = pd.DataFrame([{"packet_id": "P", "stratum": "s", "kind": "MISSED",
                           "tier": "", "cik": "0000000001",
                           "row_a": "ROW-a", "row_b": "ROW-b", "edge_index": ""}])
    out = rv.replay_pairs(pairs, holdings)
    assert out.loc[0, "t_B2"].startswith("VETO:name")
    assert out.loc[0, "t_D"] == "ADMIT"


def test_replay_flags_name_multiplicity_veto():
    rows = [_row("ROW-a", "2024-03-31", "Generic Loan", 100.0)]
    rows += [_row(f"ROW-x{i}", "2024-03-31", "Generic Loan", 100.0 + i)
             for i in range(11)]
    rows += [_row("ROW-b", "2024-06-30", "Generic Loan", 101.0)]
    holdings = pd.DataFrame(rows)
    pairs = pd.DataFrame([{"packet_id": "P", "stratum": "s", "kind": "MISSED",
                           "tier": "", "cik": "0000000001",
                           "row_a": "ROW-a", "row_b": "ROW-b", "edge_index": ""}])
    out = rv.replay_pairs(pairs, holdings)
    assert "multiplicity" in out.loc[0, "t_B2"]


def test_replay_reports_twin_for_wrong_edge():
    holdings = pd.DataFrame([
        _row("ROW-a", "2024-03-31", "Acme LLC", 2_600_000.0, pa=2_600_000.0),
        _row("ROW-b", "2024-06-30", "Acme LLC", 300_000.0, pa=300_000.0),
        _row("ROW-t", "2024-06-30", "Acme LLC", 2_550_000.0, pa=2_550_000.0),
    ])
    pairs = pd.DataFrame([{"packet_id": "P", "stratum": "s", "kind": "WRONG",
                           "tier": "B2_exact_name", "cik": "0000000001",
                           "row_a": "ROW-a", "row_b": "ROW-b", "edge_index": 0}])
    out = rv.replay_pairs(pairs, holdings)
    assert out.loc[0, "twin_row_id"] == "ROW-t"
    assert out.loc[0, "twin_pa_ratio"] < 1.05
