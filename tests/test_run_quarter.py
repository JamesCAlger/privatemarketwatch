"""Tests for the Agent A quarterly driver's deterministic helpers (Layer 1)."""

import csv

import scripts.agent_a.run_quarter as rq


def _write_report(path, rows):
    cols = ["cik", "entity_name", "n_rows", "regime", "rate_embed_pct", "anchor_present_pct",
            "distinct_signatures", "cover80", "cover90", "cover95", "largest_sig_pct",
            "none_pct", "rate_capture_pct", "top1_sig", "top2_sig"]
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in rows:
            w.writerow({c: r.get(c, "") for c in cols})


def test_flattened_filers_filters_regime(tmp_path, monkeypatch):
    rep = tmp_path / "sig.csv"
    _write_report(rep, [
        {"cik": "1", "entity_name": "Flat Co", "n_rows": 5000, "regime": "flattened",
         "none_pct": 4.0, "top1_sig": "SECDEBT REFRATE RATE MAT"},
        {"cik": "2", "entity_name": "Delim Co", "n_rows": 9000, "regime": "delimited",
         "none_pct": 0.0, "top1_sig": "W , W"},
    ])
    monkeypatch.setattr(rq, "SIGREPORT", rep)
    filers = rq._flattened_filers()
    assert [f["cik"] for f in filers] == ["1"]   # delimited dropped
    assert filers[0]["none_pct"] == 4.0


def test_has_grammar(tmp_path, monkeypatch):
    monkeypatch.setattr(rq, "GRAMMAR_DIR", tmp_path)
    (tmp_path / "0001993402.json").write_text("{}", encoding="utf-8")
    assert rq._has_grammar("0001993402")
    assert not rq._has_grammar("0000000000")


def test_drift_threshold_constant():
    # the documented drift signal: flattened + grammar + none-share >= threshold
    assert rq.NONE_DRIFT_PCT == 10.0


def test_discover_builds_shape_stratified_first_pass_bundles(tmp_path, monkeypatch):
    quarter = "2025-12-31"
    monkeypatch.setattr(rq.config, "OUTPUT_DIR", tmp_path / "output")
    monkeypatch.setattr(rq, "SIGREPORT", tmp_path / "sig.csv")
    monkeypatch.setattr(rq, "GRAMMAR_DIR", tmp_path / "grammars")
    (tmp_path / "grammars").mkdir()
    _write_report(rq.SIGREPORT, [{
        "cik": "0001",
        "entity_name": "Flat Co",
        "n_rows": 500,
        "regime": "flattened",
        "rate_embed_pct": 50.0,
        "none_pct": 20.0,
        "top1_sig": "RATE MAT",
    }])
    calls = []

    def fake_build_bundle(*args, **kwargs):
        calls.append((args, kwargs))
        return {
            "report_dates": [quarter],
            "top_variants": [{"signature": "RATE MAT"}],
            "regime": "flattened",
            "n_rows": 500,
            "none_pct": 20.0,
        }

    monkeypatch.setattr(rq, "build_bundle", fake_build_bundle)
    monkeypatch.setattr(rq.cik_lock, "is_locked", lambda cik: False)

    rows = rq.discover(quarter, min_rows=200)

    assert [r["cik"] for r in rows] == ["0001"]
    assert calls[0][0] == ("0001",)
    assert calls[0][1]["shape_stratified"] is True
