"""pipeline.investigation_state: rules fingerprint + stale-investigation audit."""
import json

from pipeline.investigation_state import rules_fingerprint, stale_investigations


def _rule(path, rule_id="r1"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"rule_id": rule_id, "rule_type": "row_exclusion"}), encoding="utf-8")


def test_fingerprint_empty_and_deterministic(tmp_path):
    assert rules_fingerprint(tmp_path / "missing") == ""
    d = tmp_path / "rules"
    d.mkdir()
    assert rules_fingerprint(d) == ""
    _rule(d / "b.json", "b")
    _rule(d / "a.json", "a")
    f1 = rules_fingerprint(d)
    assert len(f1) == 64
    assert rules_fingerprint(d) == f1
    _rule(d / "a.json", "a-changed")
    assert rules_fingerprint(d) != f1


def _cik_dir(base, cik, *, rules, apply_fp=None, gate_fp=None, gate_verdict="PASS", q="2026-03-31"):
    d = base / cik
    for i in range(rules):
        _rule(d / "rules" / f"r{i}.json", f"r{i}")
    if apply_fp is not None:
        d.mkdir(parents=True, exist_ok=True)
        (d / "apply_audit.json").write_text(json.dumps({"rules_fingerprint": apply_fp}), encoding="utf-8")
    if gate_fp is not None:
        d.mkdir(parents=True, exist_ok=True)
        (d / f"gate.{q}.json").write_text(
            json.dumps({"verdict": gate_verdict, "rules_fingerprint": gate_fp}), encoding="utf-8")
    return d


def test_stale_when_rules_newer_than_apply_or_gate(tmp_path):
    q = "2026-03-31"
    d = _cik_dir(tmp_path, "1838126", rules=2)
    fp = rules_fingerprint(d / "rules")
    # HPS shape: gate FAIL recorded on an earlier rule set, rules rewritten after
    (d / "apply_audit.json").write_text(json.dumps({"rules_fingerprint": "old"}), encoding="utf-8")
    (d / f"gate.{q}.json").write_text(json.dumps({"verdict": "FAIL", "rules_fingerprint": "old"}),
                                      encoding="utf-8")
    out = stale_investigations(tmp_path, q)
    assert [o["cik"] for o in out] == ["0001838126"]
    assert out[0]["rules_fingerprint"] == fp and out[0]["apply_fingerprint"] == "old"
    assert out[0]["gate_verdict"] == "FAIL"
    assert "apply" in out[0]["reason"] and "gate" in out[0]["reason"]


def test_not_stale_when_fingerprints_match(tmp_path):
    q = "2026-03-31"
    d = _cik_dir(tmp_path, "1674760", rules=1)
    fp = rules_fingerprint(d / "rules")
    _cik_dir(tmp_path, "1674760", rules=0, apply_fp=fp, gate_fp=fp)
    assert stale_investigations(tmp_path, q) == []


def test_no_rules_is_never_stale_and_other_quarter_gate_does_not_count(tmp_path):
    _cik_dir(tmp_path, "2083477", rules=0, apply_fp="x")            # clean zero-rule CIK
    d = _cik_dir(tmp_path, "1715933", rules=1)
    fp = rules_fingerprint(d / "rules")
    _cik_dir(tmp_path, "1715933", rules=0, apply_fp=fp, gate_fp=fp, q="2025-12-31")
    out = stale_investigations(tmp_path, "2026-03-31")
    assert [o["cik"] for o in out] == ["0001715933"]
    assert "gate" in out[0]["reason"] and "apply" not in out[0]["reason"]


def test_cik_filter_and_skip_dirs(tmp_path):
    d = _cik_dir(tmp_path, "111", rules=1)
    _cik_dir(tmp_path, "batch", rules=1)          # non-CIK dirs are skipped
    out = stale_investigations(tmp_path, "2026-03-31", ciks={"0000000111"})
    assert [o["cik"] for o in out] == ["0000000111"]
    assert stale_investigations(tmp_path, "2026-03-31", ciks={"0000000222"}) == []
