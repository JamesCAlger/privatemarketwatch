"""Tests for the verdict-retirement store (pipeline/verdict_retirements.py)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from pipeline import verdict_retirements as vr

RID = "RVQ_REV_0123456789ab"


def _entry(**over):
    e = {"retirement_id": "VR-X", "review_id": RID, "verdict_sha256": "a" * 64,
         "cik": "0000000001", "engine": "oracle", "rule_name": "B01", "report_date": "2025-12-31",
         "reason": "r", "evidence": [{"source": "query", "quote": "q"}], "rerun": "duckdb: SELECT 1",
         "owner_words": "do as recommended", "decided_by": "owner", "decided_on": "2026-11-10"}
    e.update(over)
    return e


def test_validate_accepts_a_complete_entry():
    assert vr.validate(_entry()) == []


@pytest.mark.parametrize("over, needle", [
    ({"decided_by": "agent"}, "only the owner"),
    ({"owner_words": ""}, "owner_words"),
    ({"verdict_sha256": "abc"}, "verdict_sha256"),
    ({"cik": "1"}, "cik"),
    ({"report_date": "2025q4"}, "report_date"),
    ({"evidence": []}, "evidence"),
    ({"evidence": [{"source": "hunch", "quote": "q"}]}, "evidence"),
    ({"review_id": "not-an-id"}, "review_id"),
])
def test_validate_rejects(over, needle):
    assert any(needle in p for p in vr.validate(_entry(**over)))


def test_load_raises_on_invalid_or_duplicate(tmp_path):
    (tmp_path / "a.json").write_text(json.dumps({"retirements": [_entry(decided_by="agent")]}), encoding="utf-8")
    with pytest.raises(ValueError):
        vr.load(tmp_path)
    (tmp_path / "a.json").write_text(json.dumps({"retirements": [_entry(), _entry(retirement_id="VR-Y")]}),
                                     encoding="utf-8")
    with pytest.raises(ValueError, match="Two retirements"):
        vr.load(tmp_path)


def test_match_is_exact_on_hash_and_identity(tmp_path):
    p = tmp_path / (RID + ".json")
    p.write_text(json.dumps({"verdict": "real_error"}), encoding="utf-8")
    store = {RID: _entry(verdict_sha256=vr.verdict_sha256(p))}
    assert vr.match(store, RID, verdict_path=p, cik="1", rule_name="B01", report_date="2025-12-31 00:00:00")
    assert vr.match(store, RID, verdict_path=p) is not None  # identity unknown: the hash decides
    assert vr.match(store, RID, verdict_path=p, rule_name="B02") is None
    assert vr.match(store, RID, verdict_path=tmp_path / "missing.json") is None
    p.write_text(json.dumps({"verdict": "real_error", "x": 1}), encoding="utf-8")
    assert vr.match(store, RID, verdict_path=p) is None


def test_the_recorded_store_loads():
    root = Path(__file__).resolve().parents[1]
    d = root / "data" / "overrides" / "verdict_retirements"
    store = vr.load(d)
    owner = json.loads((d / "owner_2026-11-10.json").read_text(encoding="utf-8"))["retirements"]
    assert len(owner) == 8
    standing = json.loads((d / "standing_rule_2026-11-10.json").read_text(encoding="utf-8"))["retirements"]
    # standing rule D-252: each entry records the deterministic check and the owner's words
    assert standing and all("D-252" in e["owner_words"] and e["rerun"].startswith("python scratch/")
                            for e in standing)
    assert len(store) == len(owner) + len(standing)
    # the two live real errors (Apollo, ssxf B01 2026-03-31) are deliberately not retired
    assert "RVQ_REV_4cdfa40d7a7a" not in store and "RVQ_REV_3049f7519633" not in store
