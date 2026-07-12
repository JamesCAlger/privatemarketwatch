import csv
import json

import scripts.agent_a.run_quarter as rq


def _write_worklist(output_dir, quarter, cik="0001"):
    qdir = output_dir / "agent_a" / "quarter" / quarter
    qdir.mkdir(parents=True)
    path = qdir / "worklist.csv"
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["cik", "entity_name", "quarter", "dominant_signature"])
        w.writeheader()
        w.writerow({"cik": cik, "entity_name": "Test Fund", "quarter": quarter,
                    "dominant_signature": "RATE"})
    return qdir


def _write_manifest(path, ciks):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"rows": [{"cik": cik} for cik in ciks]}), encoding="utf-8")


def test_finalize_staged_uses_proposals_not_production_overrides(tmp_path, monkeypatch):
    quarter = "2025-12-31"
    monkeypatch.setattr(rq.config, "OUTPUT_DIR", tmp_path / "output")
    monkeypatch.setattr(rq.config, "DATA_DIR", tmp_path / "data")
    _write_worklist(rq.config.OUTPUT_DIR, quarter)
    proposals = rq.config.OUTPUT_DIR / "agent_a" / "proposals"
    proposals.mkdir(parents=True)
    (proposals / "0001.anchors.json").write_text(
        json.dumps({"anchors": [{"label": "RATE", "regex": "[0-9]+%"}]}),
        encoding="utf-8")
    (proposals / "0001.grammar.json").write_text(
        json.dumps({"applies_to": {"signature": "OLD"}, "extractors": [], "required_fields": []}),
        encoding="utf-8")
    calls = []

    def fake_resolve(cik, parquet=None, write=True, grammar_path=None, anchor_path=None):
        calls.append((cik, grammar_path, anchor_path))
        spec = json.loads(grammar_path.read_text(encoding="utf-8"))
        spec["applies_to"]["signature"] = "RATE"
        grammar_path.write_text(json.dumps(spec), encoding="utf-8")
        return "OLD", "RATE", 12

    monkeypatch.setattr(rq, "resolve_applies_to", fake_resolve)

    rq.finalize(quarter, staged=True)

    assert calls[0][1] == proposals / "0001.grammar.json"
    assert calls[0][2] == proposals / "0001.anchors.json"
    assert not (rq.config.DATA_DIR / "overrides" / "identifier_rate_grammars" / "0001.json").exists()


def test_gate_staged_reports_missing_proposal_without_production_write(tmp_path, monkeypatch):
    quarter = "2025-12-31"
    monkeypatch.setattr(rq.config, "OUTPUT_DIR", tmp_path / "output")
    monkeypatch.setattr(rq.config, "DATA_DIR", tmp_path / "data")
    qdir = _write_worklist(rq.config.OUTPUT_DIR, quarter)

    results = rq.gate(quarter, staged=True)

    assert results[0]["verdict"] == "NO_PROPOSAL"
    assert (qdir / "staged_gate_results.csv").exists()
    assert not (rq.config.DATA_DIR / "overrides").exists()


def test_gate_staged_manifest_limits_rows_and_lock_release(tmp_path, monkeypatch):
    quarter = "2025-12-31"
    monkeypatch.setattr(rq.config, "OUTPUT_DIR", tmp_path / "output")
    monkeypatch.setattr(rq.config, "DATA_DIR", tmp_path / "data")
    qdir = rq.config.OUTPUT_DIR / "agent_a" / "quarter" / quarter
    qdir.mkdir(parents=True)
    with open(qdir / "worklist.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["cik", "entity_name", "quarter", "dominant_signature"])
        w.writeheader()
        w.writerow({"cik": "0001", "entity_name": "Included", "quarter": quarter,
                    "dominant_signature": "RATE"})
        w.writerow({"cik": "0002", "entity_name": "Excluded", "quarter": quarter,
                    "dominant_signature": "RATE"})
    manifest = qdir / "dispatch" / "batch" / "manifest.json"
    _write_manifest(manifest, ["0001"])
    released = []
    monkeypatch.setattr(rq.cik_lock, "release", released.append)

    results = rq.gate(quarter, staged=True, manifest_path=str(manifest))

    assert [r["cik"] for r in results] == ["0001"]
    assert released == ["0001"]


def test_gate_staged_reports_not_applicable_rate_grammar(tmp_path, monkeypatch):
    quarter = "2025-12-31"
    monkeypatch.setattr(rq.config, "OUTPUT_DIR", tmp_path / "output")
    monkeypatch.setattr(rq.config, "DATA_DIR", tmp_path / "data")
    qdir = _write_worklist(rq.config.OUTPUT_DIR, quarter)
    proposals = rq.config.OUTPUT_DIR / "agent_a" / "proposals"
    proposals.mkdir(parents=True)
    (proposals / "0001.anchors.json").write_text(
        json.dumps({"anchors": [{"label": "SECDEBT", "regex": "secured debt"}]}),
        encoding="utf-8")
    (proposals / "0001.grammar.json").write_text(
        json.dumps({
            "status": "NOT_APPLICABLE_RATE_GRAMMAR",
            "confidence": "medium",
            "applies_to": {"regime": "flattened", "signature": "SECDEBT"},
            "extractors": [],
            "required_fields": [],
            "available_identifier_datapoints": ["issuer", "instrument_type"],
            "unsupported_identifier_datapoints": ["interest_rate"],
            "not_applicable_reason": "identifiers carry issuer and type only",
        }),
        encoding="utf-8")

    results = rq.gate(quarter, staged=True)

    assert results[0]["verdict"] == "NOT_APPLICABLE_RATE_GRAMMAR"
    assert results[0]["reason"] == "identifiers carry issuer and type only"


def test_emit_remediation_uses_staged_anchors_for_staged_gate(tmp_path, monkeypatch):
    quarter = "2025-12-31"
    monkeypatch.setattr(rq.config, "OUTPUT_DIR", tmp_path / "output")
    monkeypatch.setattr(rq.config, "DATA_DIR", tmp_path / "data")
    proposals = rq.config.OUTPUT_DIR / "agent_a" / "proposals"
    proposals.mkdir(parents=True)
    (proposals / "0001.anchors.json").write_text(
        json.dumps({"anchors": [{"label": "CUSTOM", "regex": "custom marker"}]}),
        encoding="utf-8")
    captured = []

    def fake_build_bundle(*args, **kwargs):
        captured.append((args, kwargs))
        return {"n_rows": 1}

    monkeypatch.setattr(rq, "build_bundle", fake_build_bundle)
    n = rq._emit_remediation(quarter, [{
        "cik": "0001",
        "entity_name": "Test Fund",
        "verdict": "FAIL",
        "remediate_quarters": "2023-03-31",
        "reason": "none-share spike",
    }], staged=True)

    assert n == 1
    assert captured[0][0] == ("0001",)
    assert captured[0][1]["report_date"] == "2023-03-31"
    assert captured[0][1]["shape_stratified"] is True
    anchors = captured[0][1]["anchors"]
    assert anchors is not None
    assert anchors[0][0] == "CUSTOM"


def test_emit_remediation_uses_default_anchors_for_non_staged_gate(tmp_path, monkeypatch):
    quarter = "2025-12-31"
    monkeypatch.setattr(rq.config, "OUTPUT_DIR", tmp_path / "output")
    captured = []

    def fake_build_bundle(*args, **kwargs):
        captured.append((args, kwargs))
        return {"n_rows": 1}

    monkeypatch.setattr(rq, "build_bundle", fake_build_bundle)
    rq._emit_remediation(quarter, [{
        "cik": "0001",
        "entity_name": "Test Fund",
        "verdict": "FAIL",
        "remediate_quarters": "2023-03-31",
        "reason": "none-share spike",
    }], staged=False)

    assert captured[0][1]["anchors"] is None


def test_emit_remediation_queues_no_proposal_for_retry(tmp_path, monkeypatch):
    quarter = "2025-12-31"
    monkeypatch.setattr(rq.config, "OUTPUT_DIR", tmp_path / "output")
    captured = []

    def fake_build_bundle(*args, **kwargs):
        captured.append((args, kwargs))
        return {"n_rows": 1, "cik": args[0], "report_date": kwargs["report_date"]}

    monkeypatch.setattr(rq, "build_bundle", fake_build_bundle)
    n = rq._emit_remediation(quarter, [{
        "cik": "0001",
        "entity_name": "Test Fund",
        "verdict": "NO_PROPOSAL",
        "reason": "worker did not produce both staged proposal files",
    }], staged=True)

    rem_path = rq.config.OUTPUT_DIR / "agent_a" / "quarter" / quarter / "remediation_worklist.csv"
    rows = list(csv.DictReader(open(rem_path, newline="", encoding="utf-8")))
    assert n == 1
    assert rows[0]["cik"] == "0001"
    assert rows[0]["verdict"] == "NO_PROPOSAL"
    assert captured[0][1]["report_date"] == quarter
