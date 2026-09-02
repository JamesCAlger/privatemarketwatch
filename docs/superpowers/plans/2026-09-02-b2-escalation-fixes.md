# B2 Escalation-Driven Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the seven system defects surfaced by the q1p3 B2 escalation analysis: gate exactness, snapshot circularity, escalation lifecycle (stop + dedup + routing), prep evidence floor, per-CIK conservation scope, and the growth-aware anchor plausibility band.

**Architecture:** All changes are deterministic harness/gate code in `pipeline/` and `scripts/agent_investigate/` -- no LLM behavior changes except prompt text. Per-CIK scope lands as audited JSON overrides (Layer 2), never global keyword logic. The anchor-band change (Task 8) alters a validation gate and is BLOCKED on an explicit owner decision.

**Tech Stack:** Python 3.13, pandas, DuckDB, pytest. Windows/PowerShell; ASCII-only log strings.

**Spec:** `docs/investigations/agent_fleet_behavior.md` (section "2026-09-02 - Escalation deep-dive") -- the 7 root causes, with per-CIK evidence, live in that file. Read it before starting.

## Global Constraints

- TDD for every task: failing test first, watch it fail, minimal code, watch it pass, commit.
- Never write to `data/output/` or `frontend/public/data/` from tests (conftest guard enforces this).
- ASCII only in all log/reason strings (Windows cp1252).
- Commit messages: short subject + 2-4 bullet body + `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.
- After Tasks 1, 2, and 8 (gate/validation semantics): run `python scripts/reattest_quarters.py check` -- a Q4-2025 regression is stop-and-report.
- After all tasks: run `python scripts/diff_outputs.py --semantic` (must show no NEW unexplained artifact drift beyond the known in-flight q1p3 state).
- Do NOT dispatch worker fleets from this plan (admin shell only, separate operator action).
- Out of scope (companion work, separate plans/actions): the staging extraction fix for dropped cash/short-term schedule rows; the dbt migration; reauthoring rules 1841514/1913724/1869453 (operator workflow through the gate machinery).

---

### Task 1: Relative undershoot tolerance in the over-deletion gate

The gate's `no_over_deletion` check fails any trial value below the anchor (`anchor_undershoot_tol` defaults 0.0), while the engine's own reconcile band is 0.5-1.0%. Three escalations (1487918 -$1K, 2052153 -$1K/-$2K, 2037804 variant) document valid corrections rejected at -0.0002%. The fix adds a FRACTIONAL tolerance tied to the same `threshold_pct` the gate already uses for flagging, so a quarter inside the flagging band can never fail as delete-to-balance. The 1838126 catch (-$29.6M on a ~$1.6B anchor = 1.85%) must keep failing.

**Files:**
- Modify: `pipeline/agent_b_held_out.py` (gate_correction signature ~line 57-70; no_over_deletion loop ~lines 126-143)
- Modify: `pipeline/agent_rule.py` (gate_rules ~line 455, the `gate_correction(...)` call)
- Test: `tests/test_agent_b_held_out.py`

**Interfaces:**
- Produces: `gate_correction(..., anchor_undershoot_tol: float = 0.0, anchor_undershoot_tol_frac: float = 0.0)` -- per-quarter effective tolerance is `max(anchor_undershoot_tol, anchor_undershoot_tol_frac * abs(anchor))`.
- `gate_rules` passes `anchor_undershoot_tol_frac=threshold_pct / 100.0` (threshold_pct default 1.0 -> frac 0.01).

- [ ] **Step 1: Write the failing tests** (append to `tests/test_agent_b_held_out.py`, matching its existing snapshot-dict fixture style):

```python
def _snap(value_sum, anchor, flagged=False):
    return {"flags": ["fv_conservation"] if flagged else [],
            "conservation": {"value_sum": value_sum, "anchor_value": anchor},
            "fv_at_risk": abs(value_sum - anchor) if flagged else 0.0}


def test_over_deletion_tolerates_sub_band_undershoot():
    """A valid dedup landing $1K below a $409M anchor (-0.0002%) is not
    delete-to-balance (q1p3 escalations 1487918/2052153)."""
    baseline = {"2024-12-31": _snap(421_554_000.0, 409_665_000.0, flagged=True)}
    trial = {"2024-12-31": _snap(409_664_000.0, 409_665_000.0)}
    res = gate_correction(cik="1487918", target_quarter="2024-12-31",
                          target_flags={"fv_conservation"},
                          baseline=baseline, trial=trial, min_held_out=0,
                          anchor_undershoot_tol_frac=0.01)
    assert res.checks["no_over_deletion"] is True


def test_over_deletion_still_fails_above_band():
    """The 1838126 catch (-$29.63M on a ~$1.6B anchor = 1.85%) must keep failing."""
    baseline = {"2026-03-31": _snap(1_641_000_000.0, 1_611_219_000.0, flagged=True)}
    trial = {"2026-03-31": _snap(1_581_589_000.0, 1_611_219_000.0)}
    res = gate_correction(cik="1838126", target_quarter="2026-03-31",
                          target_flags={"fv_conservation"},
                          baseline=baseline, trial=trial, min_held_out=0,
                          anchor_undershoot_tol_frac=0.01)
    assert res.checks["no_over_deletion"] is False
```

Note: check the top of the test file for how `gate_correction` is imported; if a similar `_snap` helper already exists, reuse it instead of adding a duplicate.

- [ ] **Step 2: Run to verify both fail** -- `python -m pytest tests/test_agent_b_held_out.py -q -k "over_deletion_tolerates or still_fails_above"`. Expected: first test FAILS (check is False today); second may already pass -- that is the regression guard, keep it.

- [ ] **Step 3: Implement.** In `gate_correction`, add the parameter and change the loop:

```python
    anchor_undershoot_tol: float = 0.0,
    anchor_undershoot_tol_frac: float = 0.0,
```

```python
            # Tolerance mirrors the flagging band: a quarter INSIDE the band is not
            # flagged at all, so an undershoot inside it cannot be delete-to-balance
            # (q1p3: -$1K on a $409M anchor failed at tol=0.0 and taught workers to
            # author balancing plugs).
            tol_q = max(anchor_undershoot_tol, anchor_undershoot_tol_frac * abs(a))
            if trial_delta < -tol_q and trial_delta < base_delta - tol_q:
                overdel[q] = round(trial_delta, 2)
```

In `pipeline/agent_rule.py` `gate_rules`, add to the `gate_correction(...)` call: `anchor_undershoot_tol_frac=threshold_pct / 100.0`.

- [ ] **Step 4: Run the full gate test files** -- `python -m pytest tests/test_agent_b_held_out.py tests/test_agent_rule.py -q`. Expected: all pass.

- [ ] **Step 5: Reattest + commit**

```powershell
python scripts/reattest_quarters.py check
git add pipeline/agent_b_held_out.py pipeline/agent_rule.py tests/test_agent_b_held_out.py
git commit -m @'
gate: band-relative undershoot tolerance in no_over_deletion

- anchor_undershoot_tol_frac (gate_rules passes threshold_pct/100) so an
  undershoot inside the flagging band is not delete-to-balance.
- q1p3 escalations 1487918/2052153: valid dedups at -0.0002% were rejected
  at tol=0.0; the 1838126 -1.85% catch keeps failing (regression test).

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
'@
```

---

### Task 2: Clear single-failure gate result for unvalidated target anchors

When the target quarter's anchor tier is NONE, `build_snapshots` skips the quarter (no anchor -> no snapshot) and `gate_correction` emits a confusing cascade ("target quarter absent from trial snapshots") on top of `anchor_validated` (1930679's snapshot circularity). Fix: in `gate_rules`, when `anchor_candidates` is supplied and the target verdict is missing/NONE, short-circuit to a GateResult that fails ONLY `anchor_validated` with the tier reason plus an explicit note that snapshot checks were skipped.

**Files:**
- Modify: `pipeline/agent_rule.py` (`gate_rules`, ~lines 443-471; the anchor_verdicts block runs BEFORE `build_snapshots` after this change)
- Test: `tests/test_agent_rule.py`

**Interfaces:**
- Produces: unchanged signature; on NONE-tier target the returned `GateResult` has `checks == {"anchor_validated": False}` and `reasons` containing both the tier reason and `"snapshot checks skipped: target anchor unvalidated"`. Verdict remains FAIL.

- [ ] **Step 1: Write the failing test** (append to `tests/test_agent_rule.py`, reusing its holdings-frame fixture style):

```python
def test_gate_rules_none_tier_target_fails_only_anchor_validated():
    """1930679 circularity: a NONE-tier target must produce ONE actionable
    failure, not a cascade of absent-snapshot failures."""
    import pandas as pd
    df = pd.DataFrame({
        "cik": ["1930679"] * 2, "report_date": ["2025-12-31"] * 2,
        "fair_value": [1_000_000.0, 2_000_000.0], "asset_category": ["LOAN", "LOAN"],
    })
    res = gate_rules(df, df.copy(), cik="1930679", target_quarter="2025-12-31",
                     anchor_candidates={"2025-12-31": {}})   # no candidates -> tier NONE
    assert res.verdict == "FAIL"
    assert res.checks == {"anchor_validated": False}
    assert any("snapshot checks skipped" in r for r in res.reasons)
    assert not any("absent from trial snapshots" in r for r in res.reasons)
```

- [ ] **Step 2: Verify it fails** -- `python -m pytest tests/test_agent_rule.py -q -k none_tier_target`. Expected: FAIL (today `checks` contains target_cleared/no_new_flags/etc.).

- [ ] **Step 3: Implement.** In `gate_rules`, move the anchor-verdict classification to the top and short-circuit:

```python
    anchor_verdicts = {}
    if anchor_candidates is not None:
        from pipeline.anchor_validation import DEFAULT_AGREE_TOL, classify_many
        tol_a = anchor_agree_tol if anchor_agree_tol is not None else DEFAULT_AGREE_TOL
        anchor_verdicts = classify_many(anchor_candidates, agree_tol=tol_a)
        tv = anchor_verdicts.get(str(target_quarter))
        if tv is None or tv.tier == "NONE":
            # Snapshot circularity guard (1930679): with no validated target anchor the
            # target quarter never enters snapshots, and every snapshot check then fails
            # for the same upstream cause. Emit the ONE actionable failure instead.
            res = GateResult(cik=str(cik), target_quarter=str(target_quarter))
            why = tv.reason if tv else "no anchor candidates for the target quarter"
            res._fail("anchor_validated", f"target anchor not validated ({why})")
            res.reasons.append("snapshot checks skipped: target anchor unvalidated")
            return res
        anchors = {q: v.consensus for q, v in anchor_verdicts.items() if v.consensus is not None}
```

Then delete the now-duplicated NONE-tier branch further down (keep the MEDIUM advisory `reasons.append`). Check how `GateResult`/`_fail` set `verdict` (top of `agent_b_held_out.py`) -- if verdict is computed at return, mirror that here.

- [ ] **Step 4: Run** `python -m pytest tests/test_agent_rule.py tests/test_agent_b_held_out.py tests/test_investigation_orchestration.py -q`. Expected: all pass (the PASS_NOOP tests exercise adjacent paths).

- [ ] **Step 5: Reattest + commit** (same reattest command and message format as Task 1; subject: `gate: single anchor_validated failure for NONE-tier targets`).

---

### Task 3: Loop stops on escalation instead of iterating to max

Workers who escalate get re-prompted up to 5 times and re-author the same escalation (18 of 41 files are re-statements; 1916608 x4, 1950976 x4). An escalation is a designed terminal outcome -- the loop should stop on it.

**Files:**
- Modify: `scripts/agent_investigate/run_investigation.py` (`loop_decision` ~line 70; `status` ~line 381 passes the new arg)
- Test: `tests/test_investigation_orchestration.py`

**Interfaces:**
- Produces: `loop_decision(residual_pct, iteration, *, gate_verdict=None, n_escalations=0, max_iter=MAX_ITER, tol_pct=STOP_TOL_PCT)`. New rule: if `n_escalations > 0` and `iteration >= 2` and the decision would otherwise be "iterate", return `{"stop": True, "success": False, "reason": "worker escalated (n=<N>); honest stop -- escalation is the outcome"}`. `status()` passes `n_escalations=m["n_escalations"]`.

- [ ] **Step 1: Failing tests:**

```python
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
```

- [ ] **Step 2: Verify RED** -- `python -m pytest tests/test_investigation_orchestration.py -q -k escalation`. Expected: TypeError (no `n_escalations` param) / assertion failures.

- [ ] **Step 3: Implement** in `loop_decision`: add `n_escalations: int = 0` to the signature; insert the check before each `return {"stop": False, ...}` branch (both the within-tol-but-gate-failed branch and the residual-exceeds branch):

```python
        if n_escalations > 0 and iteration >= 2:
            return {"stop": True, "success": False,
                    "reason": f"worker escalated (n={n_escalations}); honest stop -- "
                              "escalation is the outcome, do not re-iterate"}
```

In `status()`: `m["decision"] = loop_decision(m["residual_pct"], iteration, gate_verdict=m["gate_verdict"], n_escalations=m["n_escalations"])`.

- [ ] **Step 4: Run** `python -m pytest tests/test_investigation_orchestration.py -q`. Expected: all pass.

- [ ] **Step 5: Commit** (subject: `investigation loop: stop on escalation after iteration 1`).

---

### Task 4: Escalation dedup + idempotency instruction in the prompt

Re-statements collapse cleanly on `(target_quarter, category)` for every observed cluster. Dedupe at consumption (keep the newest file per key, surface both counts) and tell re-prompted workers what escalations already exist.

**Files:**
- Modify: `pipeline/agent_rule.py` (new `dedupe_escalations` next to `load_escalations` ~line 547)
- Modify: `scripts/agent_investigate/run_investigation.py` (`_measure` ~line 368: report distinct count; `prep`/`_prompt`/`_feedback_block`: list existing escalations with a do-not-reauthor instruction)
- Test: `tests/test_agent_rule.py`, `tests/test_investigation_orchestration.py`

**Interfaces:**
- Produces: `dedupe_escalations(escs: list[dict]) -> list[dict]` -- keeps the LAST item per `(str(e.get("target_quarter")), str(e.get("category")))` in input order (load_escalations sorts by filename; later filename wins). `_measure` output gains `"n_escalation_files"` (raw) while `"n_escalations"` becomes the DISTINCT count (this is what Task 3's loop stop consumes).

- [ ] **Step 1: Failing tests:**

```python
# tests/test_agent_rule.py
def test_dedupe_escalations_collapses_same_quarter_category():
    escs = [
        {"target_quarter": "2026-03-31", "category": "vocab", "summary": "v1"},
        {"target_quarter": "2026-03-31", "category": "vocab", "summary": "v2 restated"},
        {"target_quarter": "2026-03-31", "category": "anchor", "summary": "a1"},
        {"target_quarter": "2025-12-31", "category": "vocab", "summary": "other quarter"},
    ]
    out = dedupe_escalations(escs)
    assert len(out) == 3
    assert {e["summary"] for e in out} == {"v2 restated", "a1", "other quarter"}
```

```python
# tests/test_investigation_orchestration.py
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
    ri.prep("999", "2026-03-31", iteration=2, allow_missing_bundle=True)
    prompt = (tmp_path / "999" / "prompt.md").read_text(encoding="utf-8")
    assert "missing cash row" in prompt
    assert "do not re-author" in prompt.lower()
```

(The `allow_missing_bundle` kwarg arrives in Task 6; if executing tasks in order, write the call without it here and add it in Task 6.)

- [ ] **Step 2: Verify RED** (`-k "dedupe_escalations or lists_existing"`).

- [ ] **Step 3: Implement.** In `agent_rule.py`:

```python
def dedupe_escalations(escs: list[dict]) -> list[dict]:
    """Collapse iteration re-statements: keep the LAST escalation per
    (target_quarter, category). q1p3: 18 of 41 files were same-finding
    re-authors across loop iterations."""
    by_key: dict[tuple, dict] = {}
    for e in escs:
        by_key[(str(e.get("target_quarter") or ""), str(e.get("category") or ""))] = e
    return list(by_key.values())
```

In `run_investigation._measure`: `raw = load_escalations(out / "escalations")`, `escalations = dedupe_escalations(raw)`, report `"n_escalations": len(escalations), "n_escalation_files": len(raw)`. In `prep`, before writing the prompt, load + dedupe existing escalations and pass them into `_prompt`; add a prompt block:

```python
    esc_lines = "\n".join(
        f"  - [{e.get('category')}] {e.get('summary')}" for e in existing_escalations) or "  (none)"
```

with the instruction text: `"Existing escalations for this target (do not re-author these; write a NEW escalation file ONLY for a materially different finding):"` followed by `esc_lines`.

- [ ] **Step 4: Run** `python -m pytest tests/test_agent_rule.py tests/test_investigation_orchestration.py -q`.

- [ ] **Step 5: Commit** (subject: `escalations: dedupe by (quarter, category) + idempotency prompt`).

---

### Task 5: Machine routing of escalations by category

Escalations carry `category` (anchor/vocab/other) but nothing consumes it -- solvable anchor cases dead-end in the human pile while the anchor-adjudicator lane sits proven (1772704). Add an `escalations` CLI mode that scans, dedupes, and routes.

**Files:**
- Modify: `scripts/agent_investigate/run_investigation.py` (new `route_escalations()` + CLI subcommand `escalations`)
- Test: `tests/test_investigation_orchestration.py`

**Interfaces:**
- Produces: `route_escalations(base_dir=BASE, out_dir=None) -> dict`. Scans `<base_dir>/<cik>/escalations/*.json`, dedupes per CIK via `dedupe_escalations`, routes `category=="anchor" -> "anchor_lane"`, `category=="vocab" -> "extraction_review"` (q1p3: every vocab escalation was an extraction-layer defect), else `-> "human_review"`. Writes `<out_dir>/escalation_routing.csv` with columns `cik,target_quarter,category,route,summary,confidence,escalation_path,n_duplicate_files`; default `out_dir = base_dir / "routing"`. Returns `{"n_files", "n_distinct", "by_route": {...}, "csv": path}`.

- [ ] **Step 1: Failing test:**

```python
def test_route_escalations_by_category(tmp_path):
    def _esc(cik, name, category, quarter="2026-03-31"):
        d = tmp_path / cik / "escalations"
        d.mkdir(parents=True, exist_ok=True)
        d.joinpath(name).write_text(json.dumps(
            {"cik": cik, "target_quarter": quarter, "category": category,
             "summary": f"{category} finding", "confidence": 0.9}), encoding="utf-8")
    _esc("111", "a.json", "anchor")
    _esc("222", "v1.json", "vocab")
    _esc("222", "v2_restated.json", "vocab")     # duplicate -> collapsed
    _esc("333", "o.json", "other")
    res = ri.route_escalations(base_dir=tmp_path, out_dir=tmp_path / "routing")
    assert res["n_files"] == 4 and res["n_distinct"] == 3
    assert res["by_route"] == {"anchor_lane": 1, "extraction_review": 1, "human_review": 1}
    rows = list(csv.DictReader(open(tmp_path / "routing" / "escalation_routing.csv",
                                    encoding="utf-8")))
    routes = {r["cik"]: r["route"] for r in rows}
    assert routes == {"111": "anchor_lane", "222": "extraction_review", "333": "human_review"}
    assert rows[[r["cik"] for r in rows].index("222")]["n_duplicate_files"] == "2"
```

- [ ] **Step 2: Verify RED** (`-k route_escalations`). Expected: AttributeError.

- [ ] **Step 3: Implement** `route_escalations` in `run_investigation.py` (skip dirs named `batch`, `_qcache`, `routing`; per CIK: `raw = load_escalations(...)`, `distinct = dedupe_escalations(raw)`, count duplicates per (quarter, category) key from raw). Route map: `{"anchor": "anchor_lane", "vocab": "extraction_review"}` with `"human_review"` default. Wire the CLI: subparser `escalations` with optional `--out-dir`; print the summary JSON.

- [ ] **Step 4: Run** the test file; then a live read-only smoke: `python -m scripts.agent_investigate.run_investigation escalations` and confirm the printed by_route counts match the deep-dive (roughly 10 anchor / 22 vocab / 9 other BEFORE dedup; ~4-5 / ~8 / ~5 after). Writing `data/output/agent_investigate/routing/` is an agent-workspace write and is fine outside pytest.

- [ ] **Step 5: Commit** (subject: `escalations: category routing CLI (anchor lane / extraction review / human)`).

---

### Task 6: Prep refuses to dispatch without a filing bundle

1975736 and 1902649 burned full investigations without a filing bundle and could only refuse. Make bundle presence a prep precondition with an explicit override.

**Files:**
- Modify: `scripts/agent_investigate/run_investigation.py` (`prep` ~line 402; CLI `prep` gains `--allow-missing-bundle`)
- Test: `tests/test_investigation_orchestration.py`

**Interfaces:**
- Produces: `prep(cik, target_quarter, iteration=1, allow_missing_bundle=False)`. When `_find_bundle` returns None and not allowed: return `{"cik", "target_quarter", "status": "blocked_no_bundle", "reason": "no cached filing bundle; queue bundle build before dispatch (q1p3: bundle-less investigations can only refuse)"}` and write NO prompt/manifest. With the flag, current behavior (empty `bundle_path`).

- [ ] **Step 1: Failing tests:**

```python
def test_prep_blocks_without_bundle(tmp_path, monkeypatch):
    monkeypatch.setattr(ri, "BASE", tmp_path)
    monkeypatch.setattr(ri, "_load_holdings", lambda cik: pd.DataFrame(
        {"cik": ["999"], "report_date": ["2026-03-31"], "fair_value": [1.0]}))
    monkeypatch.setattr(ri, "_candidates_with_outlier_filter", lambda cik: ({}, {}))
    monkeypatch.setattr(ri, "_find_bundle", lambda cik, q: None)
    res = ri.prep("999", "2026-03-31")
    assert res["status"] == "blocked_no_bundle"
    assert not (tmp_path / "999" / "prompt.md").exists()


def test_prep_allow_missing_bundle_overrides(tmp_path, monkeypatch):
    # same monkeypatching as above
    monkeypatch.setattr(ri, "BASE", tmp_path)
    monkeypatch.setattr(ri, "_load_holdings", lambda cik: pd.DataFrame(
        {"cik": ["999"], "report_date": ["2026-03-31"], "fair_value": [1.0]}))
    monkeypatch.setattr(ri, "_candidates_with_outlier_filter", lambda cik: ({}, {}))
    monkeypatch.setattr(ri, "_find_bundle", lambda cik, q: None)
    res = ri.prep("999", "2026-03-31", allow_missing_bundle=True)
    assert (tmp_path / "999" / "prompt.md").exists()
    assert res.get("bundle") == ""
```

- [ ] **Step 2: Verify RED** (`-k "blocks_without_bundle or allow_missing_bundle"`).

- [ ] **Step 3: Implement.** In `prep`, after `bundle = _find_bundle(...)`:

```python
    if bundle is None and not allow_missing_bundle:
        return {"cik": _norm(cik), "target_quarter": target_quarter,
                "status": "blocked_no_bundle",
                "reason": "no cached filing bundle; queue bundle build before dispatch "
                          "(bundle-less investigations can only refuse)"}
```

Move the `_dq_describe` pre-warm and dir creation AFTER this check so a blocked prep leaves no side effects. CLI: `p.add_argument("--allow-missing-bundle", action="store_true")` on the prep subparser, threaded through.

- [ ] **Step 4: Run** `python -m pytest tests/test_investigation_orchestration.py -q`.

- [ ] **Step 5: Commit** (subject: `prep: block dispatch when no filing bundle is cached`). Also note in the commit body that the operator chain must treat `blocked_no_bundle` as skip-and-queue (skill update is operator-side, out of code scope).

---

### Task 7: Per-CIK conservation-scope override (1905824)

The conservation sum globally excludes `asset_category == 'CASH'`, but 1905824's printed Total Investments INCLUDES its FHLB discount notes (classified CASH here), producing a structural -$38.8M residual. Fix with an audited per-CIK override consumed by BOTH sum implementations -- `agent_rule.value_sum_by_quarter` (gate/trial frame) and `scripts/shadow_conservation_engine.py` (production flags, `<> 'CASH'` filter at ~line 236). Changing only one would recreate the trial-vs-production divergence that made q1p3 rules inert. Do NOT reclassify the rows themselves: asset_category feeds analytics; the defect is conservation scope, not classification.

**Files:**
- Create: `pipeline/conservation_scope.py`
- Create: `data/overrides/conservation_scope/1905824.json` (evidence from escalation files `data/output/agent_investigate/1905824/escalations/*.json`)
- Modify: `pipeline/config.py` (add `CONSERVATION_SCOPE_DIR = OVERRIDES_DIR / "conservation_scope"` -- check the existing overrides-path constant name and follow it)
- Modify: `pipeline/agent_rule.py` (`value_sum_by_quarter` ~line 395)
- Modify: `scripts/shadow_conservation_engine.py` (the `<> 'CASH'` filter ~line 236)
- Test: `tests/test_conservation_scope.py` (new), plus one test each in `tests/test_agent_rule.py` and the shadow engine's test file (locate with `rg -l shadow_conservation tests/`)

**Interfaces:**
- Produces: `conservation_scope.included_categories_for(cik) -> frozenset[str]` -- the asset_category values NORMALLY excluded that this CIK's anchor scope includes (empty set when no override). Override schema:

```json
{
  "cik": "1905824",
  "include_asset_categories": ["CASH"],
  "scope_quarters": ["all"],
  "evidence": [
    {"source": "filing", "quote": "Table 13: Total U.S. Government Agencies | 38,771 | 38,767 | 22.77%; Total Short-Term Investments | 47,530 | 47,526 | 27.91%; Total Investments | 210,328 | 203,856 | 119.73%"},
    {"source": "query", "quote": "13 CASH rows totaling 38,767,000; conservation remainder after recover_dropped_march_positions is exactly -38,767,000"}
  ],
  "rationale": "Filer's printed Total Investments includes FHLB discount notes that this pipeline classifies CASH; the conservation-eligible set must mirror the anchor's scope.",
  "confidence": 0.99
}
```

- [ ] **Step 1: Failing tests:**

```python
# tests/test_conservation_scope.py
import json
from pipeline import conservation_scope


def test_included_categories_reads_override(tmp_path, monkeypatch):
    d = tmp_path / "conservation_scope"
    d.mkdir()
    d.joinpath("1905824.json").write_text(json.dumps(
        {"cik": "1905824", "include_asset_categories": ["CASH"],
         "scope_quarters": ["all"], "evidence": [{"source": "filing", "quote": "x"}],
         "rationale": "r", "confidence": 0.99}), encoding="utf-8")
    monkeypatch.setattr(conservation_scope, "SCOPE_DIR", d)
    assert conservation_scope.included_categories_for("1905824") == frozenset({"CASH"})
    assert conservation_scope.included_categories_for("0001905824") == frozenset({"CASH"})
    assert conservation_scope.included_categories_for("999") == frozenset()


def test_malformed_override_is_ignored(tmp_path, monkeypatch):
    d = tmp_path / "conservation_scope"
    d.mkdir()
    d.joinpath("111.json").write_text("{not json", encoding="utf-8")
    monkeypatch.setattr(conservation_scope, "SCOPE_DIR", d)
    assert conservation_scope.included_categories_for("111") == frozenset()
```

```python
# tests/test_agent_rule.py
def test_value_sum_respects_conservation_scope(monkeypatch):
    import pandas as pd
    from pipeline import conservation_scope
    df = pd.DataFrame({
        "cik": ["1905824"] * 2, "report_date": ["2026-03-31"] * 2,
        "fair_value": [156_078_000.0, 38_767_000.0],
        "asset_category": ["LOAN", "CASH"],
    })
    assert value_sum_by_quarter(df)["2026-03-31"] == 156_078_000.0   # default: CASH out
    monkeypatch.setattr(conservation_scope, "included_categories_for",
                        lambda cik: frozenset({"CASH"}))
    assert value_sum_by_quarter(df, cik="1905824")["2026-03-31"] == 194_845_000.0
```

- [ ] **Step 2: Verify RED** -- module doesn't exist; `value_sum_by_quarter` has no `cik` param.

- [ ] **Step 3: Implement.** `pipeline/conservation_scope.py`:

```python
"""Per-CIK conservation-scope overrides (Layer 2, audited JSON).

The conservation sum excludes asset_category CASH globally, but some filers'
printed Total Investments INCLUDE cash-like instruments (1905824 FHLB discount
notes). The eligible set must mirror what the filer's anchor includes; that is
scope config, not a classification change. Consumed by BOTH sum
implementations (agent_rule.value_sum_by_quarter and the shadow conservation
engine) so trial and production frames cannot diverge.
"""
from __future__ import annotations

import json
import logging

from pipeline import config

logger = logging.getLogger(__name__)
SCOPE_DIR = config.CONSERVATION_SCOPE_DIR


def _norm(cik) -> str:
    return str(cik).lstrip("0")


def included_categories_for(cik) -> frozenset[str]:
    """asset_category values this CIK's anchor scope INCLUDES despite the
    global conservation exclusion. Empty set when no valid override exists."""
    if not SCOPE_DIR.exists():
        return frozenset()
    target = _norm(cik)
    for p in sorted(SCOPE_DIR.glob("*.json")):
        if _norm(p.stem) != target:
            continue
        try:
            obj = json.loads(p.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("conservation_scope override unreadable, ignored: %s (%s)", p, exc)
            return frozenset()
        cats = obj.get("include_asset_categories")
        if not (isinstance(cats, list) and cats and obj.get("evidence")):
            logger.warning("conservation_scope override invalid, ignored: %s", p)
            return frozenset()
        return frozenset(str(c).upper() for c in cats)
    return frozenset()
```

`agent_rule.value_sum_by_quarter(df, cik=None)`: when `cik` is given, `excluded = CONSERVATION_EXCLUDED_CATEGORIES - conservation_scope.included_categories_for(cik)`, else the global set. Update `build_snapshots`/`gate_rules`/`_measure` call sites to pass their `cik`. Shadow engine: the query is built per-run over all CIKs -- add a SQL carve-out generated from the override dir:

```python
    from pipeline.conservation_scope import SCOPE_DIR, included_categories_for
    carve = []
    for p in sorted(SCOPE_DIR.glob("*.json")) if SCOPE_DIR.exists() else []:
        cats = included_categories_for(p.stem)
        if cats:
            in_list = ",".join("'" + c.replace("'", "''") + "'" for c in sorted(cats))
            carve.append(
                "(LPAD(REGEXP_REPLACE(CAST(cik AS VARCHAR), '[^0-9]', '', 'g'), 10, '0')"
                f" = '{p.stem.zfill(10)}' AND upper(COALESCE(CAST(asset_category AS VARCHAR), ''))"
                f" IN ({in_list}))")
    cash_filter = "upper(COALESCE(CAST(asset_category AS VARCHAR), '')) <> 'CASH'"
    if carve:
        cash_filter = f"({cash_filter} OR {' OR '.join(carve)})"
```

and substitute `cash_filter` for the literal `<> 'CASH'` line. Follow the engine's existing style for how `sub_filter` is interpolated. Add a shadow-engine test with a two-CIK frame proving the carve-out is CIK-scoped (999...'s CASH stays excluded).

- [ ] **Step 4: Create the 1905824 override** (JSON above) and run all touched test files. Expected: green. Do NOT run a production rebuild here -- the override takes effect at the next pass battery; note that in the commit.

- [ ] **Step 5: Commit** (subject: `conservation: per-CIK scope overrides (1905824 FHLB in-anchor cash)`; body notes the dual-consumer requirement and that effect lands at next rebuild + battery).

---

### Task 8: Growth-aware anchor plausibility band -- OWNER DECISION REQUIRED FIRST

**STOP: do not implement until the owner approves.** This changes a validation gate. Present exactly this proposal: flag a quarter only when BOTH (a) the lifetime-median ratio is outside `[1/fold, fold]` (existing 0.33x-3x) AND (b) the quarter is discontinuous with its previous usable quarter (QoQ ratio outside `[1/qoq_fold, qoq_fold]`, proposed `qoq_fold = 2.0`). Evidence: 5 of 5 observed band rejections (1918712 $21.3B, 2031750 $3.5B, 1902649 $2.35B, 1954360 $0.88B, 1495584 declining fund) are false positives where holdings match companyfacts exactly; the check's true-positive class (sporadic one-quarter mis-extraction) remains caught because a sporadic outlier is discontinuous by definition. First usable quarter has no QoQ -> median rule alone decides (unchanged behavior).

**Files:**
- Modify: `pipeline/anchor_validation.py` (`flag_anchor_outliers`, lines 152-179; `DEFAULT_QOQ_FOLD = 2.0` next to `DEFAULT_OUTLIER_FOLD` at line 71)
- Test: `tests/test_anchor_validation.py` (locate with `rg -l flag_anchor_outliers tests/`; if the tests live elsewhere, add there)

**Interfaces:**
- Produces: `flag_anchor_outliers(series, *, fold=DEFAULT_OUTLIER_FOLD, min_history=MIN_OUTLIER_HISTORY, qoq_fold=DEFAULT_QOQ_FOLD)`. `OutlierFlag` unchanged; unflagged-because-continuous quarters get `reason` mentioning QoQ continuity (so escalation-free logs still explain the decision). Consumers (`run_investigation._candidates_with_outlier_filter`, any others found via `rg flag_anchor_outliers`) need no signature change.

- [ ] **Step 0: Obtain owner approval** for (a) the AND-composition, (b) `qoq_fold = 2.0`. Record the decision in `docs/agent_changelog.md`. If declined, delete this task and leave the band as-is.

- [ ] **Step 1: Failing tests** (real q1p3 series, thousands omitted):

```python
def test_ramp_up_fund_not_flagged():
    """1954360: 3.1x lifetime median but QoQ-continuous -- the q1p3 FP class."""
    series = {"2025-03-31": 308_031_000, "2025-06-30": 487_664_000,
              "2025-09-30": 614_062_000, "2025-12-31": 879_592_000,
              "2026-03-31": 877_060_000}
    flags = flag_anchor_outliers(series)
    assert not flags["2026-03-31"].flagged
    assert "continu" in flags["2026-03-31"].reason


def test_declining_fund_not_flagged():
    """1495584: 0.21x median but a smooth decline."""
    series = {"2024-12-31": 1_060_474, "2025-06-30": 723_147,
              "2025-09-30": 256_934, "2025-12-31": 225_436, "2026-03-31": 146_430}
    flags = flag_anchor_outliers(series)
    assert not flags["2025-12-31"].flagged


def test_sporadic_misextraction_still_flagged():
    """The true-positive class: one quarter collapses against BOTH median and neighbor."""
    series = {"2025-03-31": 1_000_000, "2025-06-30": 1_050_000,
              "2025-09-30": 90_000, "2025-12-31": 1_100_000}
    flags = flag_anchor_outliers(series)
    assert flags["2025-09-30"].flagged


def test_first_quarter_median_rule_unchanged():
    """No previous quarter -> QoQ cannot rescue; median rule alone decides."""
    series = {"2025-03-31": 10_000_000, "2025-06-30": 1_000_000, "2025-09-30": 1_050_000}
    flags = flag_anchor_outliers(series)
    assert flags["2025-03-31"].flagged
```

- [ ] **Step 2: Verify RED** -- the first two FAIL today (median-only flags them).

- [ ] **Step 3: Implement:**

```python
DEFAULT_QOQ_FOLD = 2.0      # growth-aware: a quarter continuous with its neighbor is not an outlier
```

```python
def flag_anchor_outliers(series, *, fold: float = DEFAULT_OUTLIER_FOLD,
                         min_history: int = MIN_OUTLIER_HISTORY,
                         qoq_fold: float = DEFAULT_QOQ_FOLD) -> dict[str, OutlierFlag]:
    usable = {str(q): float(v) for q, v in (series or {}).items() if _is_pos(v)}
    out: dict[str, OutlierFlag] = {q: OutlierFlag() for q in usable}
    if len(usable) < min_history:
        return out
    med = statistics.median(usable.values())
    if med <= 0:
        return out
    ordered = sorted(usable)
    for i, q in enumerate(ordered):
        v = usable[q]
        ratio = v / med
        if not (ratio > fold or ratio < 1.0 / fold):
            continue
        # Growth-aware rescue (owner-approved 2026-09-xx): a ramping or shrinking
        # fund drifts far from its LIFETIME median while staying continuous with
        # its neighbor; a sporadic mis-extraction is discontinuous by definition.
        # q1p3: 5/5 median-only rejections were exact-match false positives.
        prev = usable[ordered[i - 1]] if i > 0 else None
        if prev is not None and prev > 0:
            qoq = v / prev
            if 1.0 / qoq_fold <= qoq <= qoq_fold:
                out[q] = OutlierFlag(
                    flagged=False, ratio=round(ratio, 3),
                    reason=(f"companyfacts total {v:.0f} is {ratio:.2g}x the CIK median but "
                            f"QoQ-continuous ({qoq:.2g}x prior quarter) -- growth regime, "
                            f"not flagged"))
                continue
        out[q] = OutlierFlag(
            flagged=True, ratio=round(ratio, 3),
            reason=(f"companyfacts total {v:.0f} is {ratio:.2g}x the CIK median {med:.0f} "
                    f"(outside {1/fold:.2g}x-{fold:.2g}x) and discontinuous QoQ -- likely a "
                    f"mis-extracted anchor; escalate, do not reconcile to it"))
    return out
```

- [ ] **Step 4: Run** the anchor-validation test file plus `tests/test_investigation_orchestration.py` and `tests/test_agent_rule.py`. Then `python scripts/reattest_quarters.py check` (band affects which anchors validate -- a Q4 flip is stop-and-report).

- [ ] **Step 5: Commit** (subject: `anchor band: QoQ-continuity rescue for growth/decline regimes (owner-approved)`; body cites the 5 FP CIKs and the preserved sporadic-TP behavior).

---

### Task 9: Close-out -- changelog, full verification, semantic diff

- [ ] **Step 1:** Run the full touched-suite set: `python -m pytest tests/test_agent_b_held_out.py tests/test_agent_rule.py tests/test_investigation_orchestration.py tests/test_conservation_scope.py -q` plus the shadow-engine and anchor-validation test files. All green.
- [ ] **Step 2:** `python scripts/diff_outputs.py --semantic` -- no NEW unexplained drift (the in-flight q1p3 deltas are known).
- [ ] **Step 3:** `python scripts/reattest_quarters.py check` -- PASS -> PASS.
- [ ] **Step 4:** Append a dated entry to `docs/agent_changelog.md`: what changed per task, test counts, the owner decision on Task 8, and the note that the 1905824 override + band change take production effect at the next pass battery. Commit (subject: `changelog: b2 escalation-driven fixes`).
- [ ] **Step 5:** Operator follow-ups to queue (not code): update the quarter-pass-operator skill for `blocked_no_bundle` handling and the `escalations` routing step; re-dispatch the 15 env-poisoned B1 verdicts; the staging cash/short-term extraction fix gets its own plan.

---

## Self-Review Notes

- Spec coverage: root causes 2 (band) -> Task 8; 3 (anchor routing + circularity) -> Tasks 5 + 2; 4 (loop) -> already shipped (PASS_NOOP), duplicates handled by Task 3; 5 (tolerance) -> Task 1; 6 (evidence floor) -> Task 6 (lineage columns deferred to the staging plan); 7 (eligibility scope) -> Task 7; root cause 1 (extraction) is explicitly out of scope (own plan). Escalation hygiene -> Tasks 3-5.
- Known unknowns an executor must resolve in place (flagged inline): exact import lines / fixture helpers in the two gate test files, the `GateResult` verdict mechanics for Task 2, the shadow engine's filter interpolation style for Task 7, and the anchor-validation test file location for Task 8.
- Type consistency: `dedupe_escalations` (Task 4) is the same callable consumed in Tasks 3 (via `n_escalations` count in `_measure`) and 5; `value_sum_by_quarter(df, cik=None)` (Task 7) call sites include `_measure` and `gate`, which Tasks 2-3 also touch -- execute in numbered order to avoid merge friction in `run_investigation.py`.
