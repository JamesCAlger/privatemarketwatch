import json
import pandas as pd
import pytest

from scripts.match_gold import score_gold as sg


def _mk_batch(tmp_path, verdict_docs):
    (tmp_path / "packets_meta").mkdir(parents=True)
    (tmp_path / "verdicts").mkdir()
    wl_rows = []
    for pid, meta, verdict in verdict_docs:
        (tmp_path / "packets_meta" / f"{pid}.json").write_text(
            json.dumps(meta), encoding="utf-8")
        if verdict is not None:
            (tmp_path / "verdicts" / f"{pid}.json").write_text(
                json.dumps(verdict), encoding="utf-8-sig")  # BOM like real workers
        wl_rows.append({"packet_id": pid, "packet_type": meta["packet_type"],
                        "stratum": meta["stratum"], "cik": "0000000001",
                        "n_rows": 2, "n_edges": len(meta.get("edges", [])),
                        "prompt_path": "", "packet_path": "",
                        "verdict_path": f"verdicts/{pid}.json",
                        "has_cached_filing": True})
    pd.DataFrame(wl_rows).to_csv(tmp_path / "worklist.csv", index=False)


def test_wilson_interval_bounds():
    lo, hi = sg.wilson_interval(9, 10)
    assert 0.55 < lo < 0.9 < hi <= 1.0
    assert sg.wilson_interval(0, 0) == (0.0, 1.0)


def test_score_batch_per_tier_precision(tmp_path):
    meta1 = {"packet_id": "MGP-1", "packet_type": "chain", "stratum": "tier_random",
             "edges": [{"edge_index": 0, "match_method": "B2_exact_name"}]}
    v1 = {"packet_id": "MGP-1", "packet_type": "chain", "verdict": "CONFIRMED",
          "confidence": 0.95, "rationale": "same loan",
          "edge_verdicts": [{"edge_index": 0, "verdict": "CONFIRMED", "evidence": []}],
          "proposed_links": [], "escalate": False}
    meta2 = {"packet_id": "MGP-2", "packet_type": "chain", "stratum": "tier_random",
             "edges": [{"edge_index": 0, "match_method": "B2_exact_name"}]}
    v2 = {"packet_id": "MGP-2", "packet_type": "chain", "verdict": "WRONG_MERGE",
          "confidence": 0.8, "rationale": "different tranches",
          "edge_verdicts": [{"edge_index": 0, "verdict": "WRONG",
                             "evidence": [{"quoted_text": "Second Lien"}]}],
          "proposed_links": [], "escalate": False}
    _mk_batch(tmp_path, [("MGP-1", meta1, v1), ("MGP-2", meta2, v2)])
    stats = sg.score_batch(tmp_path)
    assert stats["n_verdicts"] == 2 and stats["n_invalid"] == 0
    prec = pd.read_csv(tmp_path / "precision_by_tier.csv")
    b2 = prec[prec["tier"] == "B2_exact_name"].iloc[0]
    assert b2["n_confirmed"] == 1 and b2["n_wrong"] == 1
    assert b2["precision"] == pytest.approx(0.5)


def test_score_batch_flags_invalid_and_missing(tmp_path):
    meta = {"packet_id": "MGP-3", "packet_type": "chain", "stratum": "tier_random",
            "edges": [{"edge_index": 0, "match_method": "D_fuzzy"}]}
    bad = {"packet_id": "MGP-3", "packet_type": "chain", "verdict": "WRONG_MERGE",
           "confidence": 0.9, "rationale": "x",
           "edge_verdicts": [{"edge_index": 0, "verdict": "WRONG", "evidence": []}],
           "proposed_links": [], "escalate": False}   # WRONG without citation
    meta4 = {"packet_id": "MGP-4", "packet_type": "chain", "stratum": "tier_random",
             "edges": [{"edge_index": 0, "match_method": "D_fuzzy"}]}
    _mk_batch(tmp_path, [("MGP-3", meta, bad), ("MGP-4", meta4, None)])
    stats = sg.score_batch(tmp_path)
    assert stats["n_invalid"] == 1 and stats["n_missing"] == 1
    gold = pd.read_csv(tmp_path / "gold_set.csv")
    assert not gold[gold["packet_id"] == "MGP-3"]["valid"].iloc[0]


def test_audit_slice_nonempty_per_stratum(tmp_path):
    docs = []
    for i in range(20):
        pid = f"MGP-a{i}"
        meta = {"packet_id": pid, "packet_type": "chain", "stratum": "tier_random",
                "edges": [{"edge_index": 0, "match_method": "A_within_filing"}]}
        v = {"packet_id": pid, "packet_type": "chain", "verdict": "CONFIRMED",
             "confidence": 0.9, "rationale": "ok",
             "edge_verdicts": [{"edge_index": 0, "verdict": "CONFIRMED",
                                "evidence": []}],
             "proposed_links": [], "escalate": False}
        docs.append((pid, meta, v))
    _mk_batch(tmp_path, docs)
    sg.score_batch(tmp_path)
    audit = pd.read_csv(tmp_path / "audit_slice.csv")
    assert len(audit) >= 1
