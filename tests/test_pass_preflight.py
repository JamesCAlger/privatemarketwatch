"""Tests for the machine-checked quarter-pass readiness gate (tmp-confined I/O)."""

from __future__ import annotations

import json

from scripts import pass_preflight as pp


# ------------------------------------------------------------ applier coverage

def _verdict_dir(tmp_path, rid, *, findings=None, mechanism="subtotal_leak"):
    vdir = tmp_path / "verdicts"
    vdir.mkdir(exist_ok=True)
    v = {"review_id": rid, "verdict": "real_error", "mechanism": mechanism}
    if findings is not None:
        v["findings"] = findings
    (vdir / f"{rid}.json").write_text(json.dumps(v), encoding="utf-8")
    return vdir


def test_applier_coverage_passes_when_all_classes_covered(tmp_path):
    vdir = _verdict_dir(tmp_path, "R1", findings=[{"fix_class": "unit_rescale"}])
    rows = [{"review_id": "R1", "state": "real_error_unremediated"}]
    c = pp.check_applier_coverage(rows, [vdir])
    assert c["pass"] and c["severity"] == "hard"


def test_applier_coverage_fails_listing_uncovered_class(tmp_path):
    # the 121/143 lesson: a fix_class in the pool without a registered applier
    vdir = _verdict_dir(tmp_path, "R2", findings=[{"fix_class": "quantum_fix"}])
    rows = [{"review_id": "R2", "state": "remediation_pulled"}]
    c = pp.check_applier_coverage(rows, [vdir])
    assert not c["pass"]
    assert "quantum_fix" in c["detail"]
    assert c["items"][0]["example_review_ids"] == ["R2"]


def test_applier_coverage_policy_classes_do_not_fail(tmp_path):
    vdir = _verdict_dir(tmp_path, "R3", findings=[{"fix_class": "rule_scope"},
                                                  {"fix_class": "anchor_fix"}])
    rows = [{"review_id": "R3", "state": "real_error_unremediated"}]
    assert pp.check_applier_coverage(rows, [vdir])["pass"]


def test_applier_coverage_mechanism_fallback(tmp_path):
    # verdict without findings[] -> MECHANISM_TO_FIX_CLASS maps subtotal_leak
    vdir = _verdict_dir(tmp_path, "R4", mechanism="subtotal_leak")
    rows = [{"review_id": "R4", "state": "real_error_unremediated"}]
    assert pp.check_applier_coverage(rows, [vdir])["pass"]
    # non-actionable states are ignored entirely
    rows2 = [{"review_id": "R4", "state": "adjudicated_false_alarm"}]
    assert pp.check_applier_coverage(rows2, [vdir])["pass"]


# -------------------------------------------------------- anchor assessability

def _manifest(tmp_path, ciks):
    p = tmp_path / "manifest.json"
    p.write_text(json.dumps({"entries": [{"cik": c, "entity_name": c} for c in ciks]}),
                 encoding="utf-8")
    return p


def _shadow(tmp_path, rows):
    p = tmp_path / "ledger.csv"
    header = "engine,rule_name,cik,period,status\n"
    body = "".join(f"conservation,fv_conservation,{c},{q},{s}\n" for c, q, s in rows)
    p.write_text(header + body, encoding="utf-8")
    return p


def test_assessability_passes_above_min(tmp_path):
    manifest = _manifest(tmp_path, ["0000000001", "0000000002"])
    ledger = _shadow(tmp_path, [("0000000001", "2026-03-31", "pass"),
                                ("0000000002", "2026-03-31", "fail")])
    c = pp.check_anchor_assessability("2026-03-31", shadow_ledger=ledger,
                                      manifest_path=manifest,
                                      cache_dir=tmp_path / "cache", min_pct=50.0)
    assert c["pass"] and "anchored_rate 100.0" in c["detail"]


def test_assessability_fails_listing_lagging_ciks_with_cache_state(tmp_path):
    manifest = _manifest(tmp_path, ["0000000001", "0000000002", "0000000003"])
    ledger = _shadow(tmp_path, [("0000000001", "2026-03-31", "pass"),
                                ("0000000002", "2026-03-31", "skip"),
                                ("0000000003", "2026-03-31", "skip")])
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / "0000000002.json").write_text("{}", encoding="utf-8")
    c = pp.check_anchor_assessability("2026-03-31", shadow_ledger=ledger,
                                      manifest_path=manifest, cache_dir=cache,
                                      min_pct=50.0)
    assert not c["pass"]
    assert "refresh_companyfacts" in c["detail"]        # exact operator remedy
    lagging = {x["cik"]: x for x in c["items"]}
    assert lagging["0000000002"]["companyfacts_cached"] is True
    assert lagging["0000000003"]["companyfacts_cached"] is False


# ----------------------------------------------------------------- rule hygiene

def _audit(tmp_path, rows):
    p = tmp_path / "audit.csv"
    header = "layer,cik,rule_id,rule_type,status,rows_changed,fv_affected,drift\n"
    body = "".join(f"unified,{c},{r},x,{s},1,0,{d}\n" for c, r, s, d in rows)
    p.write_text(header + body, encoding="utf-8")
    return p


def test_rule_hygiene_clean_audit_passes(tmp_path):
    c = pp.check_rule_hygiene(_audit(tmp_path, [("1", "rule_a", "ok", "")]))
    assert c["pass"]


def test_rule_hygiene_fails_on_noop_and_drift(tmp_path):
    c = pp.check_rule_hygiene(_audit(tmp_path, [
        ("1", "rule_a", "ok", ""),
        ("2", "rule_b", "noop", "noop"),
        ("3", "rule_c", "ok", "row_drift")]))
    assert not c["pass"]
    assert {x["rule_id"] for x in c["items"]} == {"rule_b", "rule_c"}
    assert "_pulled_" in c["detail"]                    # retirement convention named


def test_rule_hygiene_missing_audit_fails(tmp_path):
    assert not pp.check_rule_hygiene(tmp_path / "absent.csv")["pass"]


# ----------------------------------------------------------------- stale staged

def test_stale_staged_warns_with_ages(tmp_path):
    staged = tmp_path / "staged" / "0000000001"
    staged.mkdir(parents=True)
    (staged / "unit_rescale.json").write_text("{}", encoding="utf-8")
    inv = tmp_path / "investigate"
    (inv / "123" / "rules").mkdir(parents=True)
    (inv / "123" / "rules" / "r.json").write_text("{}", encoding="utf-8")
    (inv / "_pulled_old" / "rules").mkdir(parents=True)  # skipped by convention
    (inv / "_pulled_old" / "rules" / "z.json").write_text("{}", encoding="utf-8")
    c = pp.check_stale_staged(tmp_path / "staged", inv)
    assert not c["pass"] and c["severity"] == "warn"
    stores = {x["store"] for x in c["items"]}
    assert stores == {"agent_b2/corrections", "agent_investigate"}
    assert len(c["items"]) == 2                          # _pulled_ dir excluded
    assert all("age_days" in x for x in c["items"])


def test_stale_staged_clean_passes(tmp_path):
    assert pp.check_stale_staged(tmp_path / "none", tmp_path / "none2")["pass"]


# ------------------------------------------------------- readjudication + procs

def test_readjudication_warns_on_rows(tmp_path):
    p = tmp_path / "readju.csv"
    p.write_text("cik,fix_class,source_review_ids,batch_id,gated_utc,reason\n"
                 "1,unit_rescale,R1,b,t,r\n", encoding="utf-8")
    c = pp.check_readjudication(p)
    assert not c["pass"] and "1 wrong-diagnosis" in c["detail"]
    assert pp.check_readjudication(tmp_path / "absent.csv")["pass"]


def test_competing_processes_codex_hard_python_warn():
    canned = ('"Image Name","PID","Session Name","Session#","Mem Usage"\n'
              '"codex.exe","111","Console","1","300,000 K"\n'
              '"python.exe","222","Console","1","50,000 K"\n')
    checks = {c["id"]: c for c in pp.check_competing_processes(lambda: canned)}
    assert not checks["codex_processes"]["pass"]
    assert checks["codex_processes"]["severity"] == "hard"
    assert not checks["python_processes"]["pass"]
    assert checks["python_processes"]["severity"] == "warn"
    clean = '"Image Name","PID","Session Name","Session#","Mem Usage"\n'
    checks2 = {c["id"]: c for c in pp.check_competing_processes(lambda: clean)}
    assert checks2["codex_processes"]["pass"] and checks2["python_processes"]["pass"]


# ------------------------------------------------------------------- verdicts

def _c(check_id, severity, ok):
    return {"id": check_id, "severity": severity, "pass": ok, "detail": "", "items": []}


def test_run_preflight_ready_and_not_ready():
    ready = pp.run_preflight("2026-03-31", checks=[_c("a", "hard", True),
                                                   _c("b", "warn", True)])
    assert ready["verdict"] == "READY" and ready["n_hard_fail"] == 0
    hard = pp.run_preflight("2026-03-31", checks=[_c("a", "hard", False)])
    assert hard["verdict"] == "NOT_READY"


def test_strict_promotes_warns():
    checks = [_c("a", "hard", True), _c("b", "warn", False)]
    assert pp.run_preflight("2026-03-31", checks=checks)["verdict"] == "READY"
    assert pp.run_preflight("2026-03-31", strict=True,
                            checks=checks)["verdict"] == "NOT_READY"


def test_cli_writes_artifact_and_exit_code(tmp_path, monkeypatch):
    monkeypatch.setattr(pp, "run_preflight",
                        lambda quarter, strict=False, checks=None: {
                            "schema_version": 1, "generated_utc": "t",
                            "target_quarter": quarter, "strict": strict,
                            "verdict": "NOT_READY", "n_hard_fail": 1, "n_warn": 0,
                            "checks": [_c("a", "hard", False)]})
    out = tmp_path / "preflight.json"
    assert pp.main(["--quarter", "2026-03-31", "--out", str(out)]) == 1
    assert json.loads(out.read_text(encoding="utf-8"))["verdict"] == "NOT_READY"
