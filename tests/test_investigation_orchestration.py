"""Tests for the agentic driver's orchestration: discover (B1 -> investigation targets) and
promote (gate-PASS rules -> overrides). Steps 3-4 of the B2 consolidation."""
import json

import pandas as pd

import scripts.agent_investigate.run_investigation as ri
from scripts.agent_investigate.run_investigation import _discover_targets, loop_decision, promote


def _b1_fixture(tmp_path):
    verdicts = tmp_path / "verdicts"
    verdicts.mkdir()
    (verdicts / "R1.json").write_text(json.dumps({"verdict": "real_error", "mechanism": "subtotal_leak"}))
    (verdicts / "R2.json").write_text(json.dumps({"verdict": "false_alarm"}))
    (verdicts / "R3.json").write_text(json.dumps({"verdict": "real_error"}))
    wl = tmp_path / "worklist.csv"
    wl.write_text(
        "review_id,cik,report_date,rule_name\n"
        "R1,0001920453,2024-03-31,fv_conservation\n"        # real_error -> target
        "R2,0001920453,2024-06-30,fv_conservation\n"        # false_alarm -> skipped
        "R3,0001715933,2025-12-31,fv_conservation\n"        # real_error -> target
        ",0001603480,2025-06-30,fv_conservation\n"          # no review_id -> skipped
    )
    return wl, verdicts


def test_discover_selects_only_real_errors(tmp_path):
    wl, verdicts = _b1_fixture(tmp_path)
    targets = _discover_targets(wl, verdicts)
    assert set(targets) == {("1920453", "2024-03-31"), ("1715933", "2025-12-31")}
    assert targets[("1920453", "2024-03-31")] == {"R1"}            # false_alarm R2 excluded


def test_discover_dedupes_multiple_verdicts_per_target(tmp_path):
    verdicts = tmp_path / "verdicts"
    verdicts.mkdir()
    for r in ("R1", "R2"):
        (verdicts / f"{r}.json").write_text(json.dumps({"verdict": "real_error"}))
    wl = tmp_path / "worklist.csv"
    wl.write_text("review_id,cik,report_date\nR1,0001920453,2024-03-31\nR2,0001920453,2024-03-31\n")
    targets = _discover_targets(wl, verdicts)
    assert set(targets) == {("1920453", "2024-03-31")}
    assert targets[("1920453", "2024-03-31")] == {"R1", "R2"}      # one target, both review_ids


def test_promote_refuses_without_gate_pass(tmp_path):
    # No corrected holdings for a fake cik -> gate is not PASS -> promote must refuse (no copy).
    res = promote("9999999999", "2025-12-31", overrides_dir=tmp_path)
    assert res["status"] == "refused" and res.get("gate") != "PASS"
    assert not any(tmp_path.iterdir())                             # nothing written to overrides


# --- PASS_NOOP: clean zero-rule investigations (2083477 q1p3 false-FAIL) ----------------
# held_out_coverage hard-failed a first-time filer with ONE anchored quarter, zero rules,
# and residual 0.0 -- there is no correction to overfit, so the predicate's rationale is
# vacuous. A clean no-op must pass; an over-band or unvalidated-anchor no-op must not
# (that is a worker that gave up, not a clean quarter).

def _noop_fixture(tmp_path, monkeypatch, fair_value, anchor):
    monkeypatch.setattr(ri, "BASE", tmp_path)
    df = pd.DataFrame({"cik": ["2083477"], "report_date": ["2026-03-31"],
                       "fair_value": [fair_value]})
    monkeypatch.setattr(ri, "_load_holdings", lambda cik: df)
    monkeypatch.setattr(ri, "_candidates_with_outlier_filter",
                        lambda cik: ({"2026-03-31": {"companyfacts_fv": anchor}}, {}))
    out = tmp_path / "2083477"
    out.mkdir()
    df.to_csv(out / "corrected_holdings.2083477.csv", index=False)


def test_loop_decision_pass_noop_stops_successfully():
    d = loop_decision(0.0, 1, gate_verdict="PASS_NOOP")
    assert d["stop"] is True and d["success"] is True


def test_noop_gate_verdict_requires_band_and_validated_tier():
    assert ri._noop_gate_verdict(0.0, "MEDIUM")["verdict"] == "PASS_NOOP"
    assert ri._noop_gate_verdict(0.0, "HIGH")["verdict"] == "PASS_NOOP"
    assert ri._noop_gate_verdict(5.0, "MEDIUM") is None      # over band -> gave up, not clean
    assert ri._noop_gate_verdict(None, "MEDIUM") is None     # no residual -> undecidable
    assert ri._noop_gate_verdict(0.0, "NONE") is None        # unvalidated anchor -> escalate


def test_gate_passes_clean_zero_rule_investigation(tmp_path, monkeypatch):
    _noop_fixture(tmp_path, monkeypatch, fair_value=1811075043.0, anchor=1811075043.0)
    res = ri.gate("2083477", "2026-03-31")
    assert res["verdict"] == "PASS_NOOP"
    assert res["checks"] == {"noop_reconciled": True}


def test_gate_still_fails_over_band_zero_rule_investigation(tmp_path, monkeypatch):
    _noop_fixture(tmp_path, monkeypatch, fair_value=1600000000.0, anchor=1811075043.0)
    res = ri.gate("2083477", "2026-03-31")
    assert res["verdict"] == "FAIL"


def test_promote_pass_noop_promotes_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(ri, "gate",
                        lambda cik, q: {"verdict": "PASS_NOOP", "reasons": ["clean no-op"]})
    res = promote("2083477", "2026-03-31", overrides_dir=tmp_path)
    assert res["status"] == "no_rules_to_promote" and res["gate"] == "PASS_NOOP"
    assert not any(tmp_path.iterdir())                             # nothing written to overrides


# --- promote audit guard: invalid/noop rules must not reach production ------------------
# q1p3: the Fiesta dedup (position_key not in DEDUP_KEY_FIELDS) was invalid in trial AND
# production, yet promoted -- the conservation gate passes trivially for an FV-neutral
# rule on an already-reconciled quarter, and promote copied every file unconditionally.

def _valid_rule(rule_id, predicate, cik="2083477"):
    return {"cik": cik, "rule_id": rule_id, "rule_type": "row_exclusion", "action": "exclude",
            "predicate_sql": predicate, "scope": {"quarters": ["all"]},
            "evidence": ["filing table 1 row 2"], "rationale": "test rule",
            "confidence": 0.9}


def _promote_fixture(tmp_path, monkeypatch, rules):
    monkeypatch.setattr(ri, "BASE", tmp_path / "base")
    rules_dir = tmp_path / "base" / "2083477" / "rules"
    rules_dir.mkdir(parents=True)
    for r in rules:
        (rules_dir / f"{r['rule_id']}.json").write_text(json.dumps(r), encoding="utf-8")
    monkeypatch.setattr(ri, "gate", lambda cik, q: {"verdict": "PASS"})
    monkeypatch.setattr(ri, "_load_holdings", lambda cik: pd.DataFrame({
        "cik": ["2083477", "2083477"], "report_date": ["2026-03-31", "2026-03-31"],
        "issuer_name": ["Acme Corp", "Total Investments"],
        "fair_value": [100.0, 200.0]}))
    return tmp_path / "overrides"


def test_promote_refuses_invalid_rules(tmp_path, monkeypatch):
    bad = _valid_rule("dedup_bad", "")
    bad.update({"rule_type": "dedup", "action": "dedup",
                "match_fields": ["report_date", "position_key"], "keep": "last"})
    ov = _promote_fixture(tmp_path, monkeypatch, [bad])
    res = promote("2083477", "2026-03-31", overrides_dir=ov)
    assert res["status"] == "refused_invalid_rules"
    assert res["invalid_rules"][0]["rule_id"] == "dedup_bad"
    assert not ov.exists() or not any(ov.iterdir())


def test_promote_refuses_noop_rules(tmp_path, monkeypatch):
    ov = _promote_fixture(tmp_path, monkeypatch,
                          [_valid_rule("exclude_nothing", "issuer_name = 'Nobody At All'")])
    res = promote("2083477", "2026-03-31", overrides_dir=ov)
    assert res["status"] == "refused_noop_rules"
    assert res["noop_rules"] == ["exclude_nothing"]
    assert not ov.exists() or not any(ov.iterdir())


def test_promote_copies_valid_effective_rules(tmp_path, monkeypatch):
    ov = _promote_fixture(tmp_path, monkeypatch,
                          [_valid_rule("exclude_total", "issuer_name = 'Total Investments'")])
    res = promote("2083477", "2026-03-31", overrides_dir=ov)
    assert res["status"] == "promoted" and res["n_rules"] == 1
    assert (ov / "2083477" / "exclude_total.json").exists()


# --- escalation handling: workers who escalate get one post-escalation iteration ---
# Before iter 2, the escalation does not stop the loop; at iter 2+ with escalation,
# the loop stops (honest outcome -- escalation is a terminal decision).


def test_loop_decision_stops_on_escalation_after_iter1():
    d = loop_decision(-1.6, 2, gate_verdict="FAIL", n_escalations=1)
    assert d["stop"] is True and d["success"] is False
    assert "escalat" in d["reason"]


def test_loop_decision_iteration_one_still_iterates_despite_escalation():
    # give the worker one post-escalation iteration to also author expressible rules
    d = loop_decision(-1.6, 1, gate_verdict="FAIL", n_escalations=1)
    assert d["stop"] is False


def test_loop_decision_pass_beats_escalation():
    d = loop_decision(0.0, 2, gate_verdict="PASS", n_escalations=1)
    assert d["stop"] is True and d["success"] is True


# --- escalation dedup + idempotency prompt ------------------------------------------

def test_prep_prompt_lists_existing_escalations(tmp_path, monkeypatch):
    monkeypatch.setattr(ri, "BASE", tmp_path)
    monkeypatch.setattr(ri, "_load_holdings", lambda cik: pd.DataFrame(
        {"cik": ["999"], "report_date": ["2026-03-31"], "fair_value": [1.0]}))
    monkeypatch.setattr(ri, "_candidates_with_outlier_filter", lambda cik: ({}, {}))
    monkeypatch.setattr(ri, "_find_bundle", lambda cik, q: None)
    esc_dir = tmp_path / "999" / "escalations"
    esc_dir.mkdir(parents=True)
    esc_dir.joinpath("prior.json").write_text(json.dumps(
        {"target_quarter": "2026-03-31", "category": "vocab", "kind": "proposed_mechanism",
         "summary": "missing cash row", "evidence": [{"source": "query", "quote": "x"}],
         "why_no_vocab_fits": "w", "suggested_applier": "s", "confidence": 0.9}),
        encoding="utf-8")
    ri.prep("999", "2026-03-31", iteration=2)
    prompt = (tmp_path / "999" / "prompt.md").read_text(encoding="utf-8")
    assert "missing cash row" in prompt
    assert "do not re-author" in prompt.lower()
