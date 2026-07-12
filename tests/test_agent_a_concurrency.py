"""Tests for per-CIK serialization (cik_lock) and the proposal self-screen helpers."""

import scripts.agent_a.cik_lock as lk


def test_lock_is_mutually_exclusive(tmp_path, monkeypatch):
    monkeypatch.setattr(lk, "LOCK_DIR", tmp_path)
    assert lk.acquire("0001", owner="a", now=1000.0) is True
    # second concurrent acquirer on the SAME cik must fail (serial per CIK)
    assert lk.acquire("0001", owner="b", now=1000.0) is False
    # a DIFFERENT cik is free (parallel across CIKs)
    assert lk.acquire("0002", owner="c", now=1000.0) is True


def test_lock_release_allows_reacquire(tmp_path, monkeypatch):
    monkeypatch.setattr(lk, "LOCK_DIR", tmp_path)
    assert lk.acquire("0001", now=1000.0) is True
    lk.release("0001")
    assert lk.acquire("0001", now=1000.0) is True   # remediation pass can claim after release


def test_stale_lock_is_reclaimable(tmp_path, monkeypatch):
    monkeypatch.setattr(lk, "LOCK_DIR", tmp_path)
    assert lk.acquire("0001", now=1000.0) is True
    # a crashed run leaves the lock; after ttl it is reclaimable
    assert lk.acquire("0001", ttl_s=3600, now=1000.0 + 5000) is True
    # but not before ttl
    assert lk.acquire("0001", ttl_s=3600, now=1000.0 + 100) is False


def test_held_ciks_lists_live_locks(tmp_path, monkeypatch):
    monkeypatch.setattr(lk, "LOCK_DIR", tmp_path)
    lk.acquire("0001", now=1.0)
    lk.acquire("0002", now=1.0)
    assert lk.held_ciks() == ["0001", "0002"]


# --- self-screen: the over-require trap is caught deterministically ---
def test_screen_catches_over_required_optional_field(tmp_path, monkeypatch):
    import json
    from scripts.agent_a import validate_proposal as vp

    # point proposal lookup at tmp dirs
    monkeypatch.setattr(vp.config, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(vp.config, "DATA_DIR", tmp_path)
    (tmp_path / "agent_a" / "proposals").mkdir(parents=True)
    (tmp_path / "agent_a" / "proposals" / "X.anchors.json").write_text(
        json.dumps({"cik": "X", "anchors": [{"label": "SECDEBT", "regex": "secured debt"}]}),
        encoding="utf-8")
    (tmp_path / "agent_a" / "proposals" / "X.grammar.json").write_text(
        json.dumps({"extractors": [{"field": "basis_spread", "regex": "([0-9.]+)%", "group": 1, "type": "pct"}],
                    "required_fields": ["basis_spread", "pik_rate"],   # <- pik_rate is the trap
                    "applies_to": {"regime": "flattened", "signature": "SECDEBT"}}),
        encoding="utf-8")
    bundle = tmp_path / "b.json"
    bundle.write_text(json.dumps({"top_variants": [], "none_examples": []}), encoding="utf-8")
    fails, warns, metrics = vp.screen("X", str(bundle))
    assert any("OPTIONAL field" in f for f in fails)


def test_screen_accepts_supported_not_applicable_rate_grammar(tmp_path, monkeypatch):
    import json
    from scripts.agent_a import validate_proposal as vp

    monkeypatch.setattr(vp.config, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(vp.config, "DATA_DIR", tmp_path)
    (tmp_path / "agent_a" / "proposals").mkdir(parents=True)
    (tmp_path / "agent_a" / "proposals" / "X.anchors.json").write_text(
        json.dumps({"cik": "X", "anchors": [{"label": "SECDEBT", "regex": "secured debt"}]}),
        encoding="utf-8")
    (tmp_path / "agent_a" / "proposals" / "X.grammar.json").write_text(
        json.dumps({
            "status": "NOT_APPLICABLE_RATE_GRAMMAR",
            "extractors": [],
            "required_fields": [],
            "applies_to": {"regime": "flattened", "signature": "SECDEBT"},
            "available_identifier_datapoints": ["issuer", "instrument_type"],
            "unsupported_identifier_datapoints": ["interest_rate", "maturity_date"],
            "not_applicable_reason": "identifiers contain issuer and type only",
        }),
        encoding="utf-8")
    bundle = tmp_path / "b.json"
    bundle.write_text(json.dumps({
        "top_variants": [{"signature": "SECDEBT", "samples": [
            {"identifier": "Acme LLC | Secured Debt 1"},
            {"identifier": "Beta Inc. | Secured Debt"},
        ]}],
        "none_examples": [],
    }), encoding="utf-8")

    fails, warns, metrics = vp.screen("X", str(bundle))

    assert fails == []
    assert metrics["status"] == "NOT_APPLICABLE_RATE_GRAMMAR"
    assert metrics["identifier_rate_evidence_pct"] == 0.0


def test_screen_rejects_not_applicable_when_identifier_has_rates(tmp_path, monkeypatch):
    import json
    from scripts.agent_a import validate_proposal as vp

    monkeypatch.setattr(vp.config, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(vp.config, "DATA_DIR", tmp_path)
    (tmp_path / "agent_a" / "proposals").mkdir(parents=True)
    (tmp_path / "agent_a" / "proposals" / "X.anchors.json").write_text(
        json.dumps({"cik": "X", "anchors": [{"label": "SECDEBT", "regex": "secured debt"}]}),
        encoding="utf-8")
    (tmp_path / "agent_a" / "proposals" / "X.grammar.json").write_text(
        json.dumps({
            "status": "NOT_APPLICABLE_RATE_GRAMMAR",
            "extractors": [],
            "required_fields": [],
            "applies_to": {"regime": "flattened", "signature": "SECDEBT"},
            "available_identifier_datapoints": ["issuer", "instrument_type"],
            "unsupported_identifier_datapoints": ["interest_rate"],
            "not_applicable_reason": "claimed no embedded rates",
        }),
        encoding="utf-8")
    bundle = tmp_path / "b.json"
    bundle.write_text(json.dumps({
        "top_variants": [{"signature": "SECDEBT", "samples": [
            {"identifier": "Acme LLC secured debt SOFR + 5.50% 12/31/2028"},
            {"identifier": "Beta Inc. secured debt 12.00%"},
        ]}],
        "none_examples": [],
    }), encoding="utf-8")

    fails, warns, metrics = vp.screen("X", str(bundle))

    assert any("NOT_APPLICABLE contradicted" in f for f in fails)
