# Provenance Gate Predicates Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add two provenance-integrity predicates to the B2 value gate so a correction that would clobber provenance columns or cause unstamped field drift FAILs at promotion time instead of surfacing post-promotion in the provenance ledger.

**Architecture:** A new pure function `check_provenance_integrity(baseline_df, expected_df)` in `scripts/agent_b2/run_remediation.py`, wired into `gate_value_packet` alongside the existing predicates (`replay_equivalence`, `field_sanity`, `magnitude_plausible`, `fv_change_scoped`, `grounding_verified`). It judges the gate's own replay frame (`expected_df = apply_scoped(baseline_df, correction)`), NOT the staged trial frame — promotion re-applies the correction JSON in production, so the applier's own behavior is what ships. Comparison semantics deliberately mirror `mark_corrected_fields` (`pipeline/agent_promoted.py:77`) so the gate's notion of "changed" equals the production stamp's notion.

**Tech Stack:** Python, pandas. No new dependencies.

**Spec:** Inline (this plan is the spec — see Design Decisions below). Motivating context: the provenance re-verifier (`pipeline/provenance_reverify.py`) excuses any (row, field) stamped in `corrected_fields` (first CASE branch, line 157) and runs only as a post-promotion quarter-pass stage — the B2 gate itself never checks provenance today.

## Design Decisions

1. **Two predicates:**
   - `provenance_invariant` — provenance/anchor columns must be byte-identical between baseline and applier output on rows that survive the applier (index intersection; appliers preserve index labels). A provenance column present in baseline but dropped by the applier also fails.
   - `changed_fields_tracked` — every non-provenance column the applier changed must be in `CORRECTED_TRACKED_FIELDS` (`pipeline/agent_promoted.py:52`). A changed untracked column would never be stamped into `corrected_fields` by production, so the provenance re-verifier would later see unexplained drift.
2. **Provenance column list** (from the unified holdings schema, `pipeline/unified_holdings.py:84-98`, plus `row_id`): `row_id, source_row_id, src_context_id, src_context_count, src_facts, src_transforms, src_filled_fields, src_conflict_fields, src_field_overrides, corrected_fields`. `corrected_fields` is included because production stamps it OUTSIDE the applier (`mark_corrected_fields`); an applier writing it directly is a defect. `source_row_id` may be absent from holdings frames — the check only inspects columns present in `baseline_df`, so absence is harmless.
3. **Rows added by the applier are exempt** (new index labels; production stamps them `_row:added`). Only the index intersection is compared.
4. **Frames without provenance columns pass trivially.** Gate frames from production holdings carry the columns; minimal test fixtures don't, and all existing value-gate tests must keep passing unchanged.
5. **Scope: value gate only** (`POST_STAGING_APPLIERS` fix classes). Wrapper-patch (stage-1) corrections change what the parser sees, so source-level provenance legitimately changes with the values — invariance would be wrong there. The conservation gate path is unchanged.
6. **String-normalized comparison** copied from `mark_corrected_fields`: `series.astype("string").str.strip().fillna("")`. Unchanged values in `expected_df` are the same objects as baseline (applier copies the frame and modifies selected cells), so float-repr false positives cannot occur.

## Global Constraints

- ASCII only in all code, comments, and log/reason strings (Windows cp1252 contract in AGENTS.md).
- Do NOT run the full pytest suite; targeted file only (`tests/test_agent_b2_run_remediation.py`). Check for other running pytest processes before starting a run.
- After running tests, run `python scripts/diff_outputs.py --semantic` as the production-artifact backstop.
- Execute in the CURRENT working tree on branch `ensemble-fp-experiment` — `scripts/agent_b2/run_remediation.py` already carries uncommitted work this plan builds on. Do NOT create an isolated worktree, do NOT revert existing uncommitted changes.
- Commit messages: short subject + 2-4 bullet body.
- Append (never edit) `docs/agent_changelog.md` per the Agent Update Protocol.

---

### Task 1: `check_provenance_integrity` pure function

**Files:**
- Modify: `scripts/agent_b2/run_remediation.py` (new section after `_canonical_value_frame`, which ends near line 443, immediately before `gate_value_packet`)
- Test: `tests/test_agent_b2_run_remediation.py` (append a new section after the value-gate tests)

**Interfaces:**
- Consumes: `CORRECTED_TRACKED_FIELDS` from `pipeline.agent_promoted` (existing list of 22 field names).
- Produces: `check_provenance_integrity(baseline_df: pd.DataFrame, expected_df: pd.DataFrame) -> tuple[dict[str, bool], list[str]]` returning `({"provenance_invariant": bool, "changed_fields_tracked": bool}, reasons)`; module constant `_PROVENANCE_COLUMNS: list[str]`. Task 2 relies on both names exactly.

- [ ] **Step 1: Write the failing unit tests**

Append to `tests/test_agent_b2_run_remediation.py` (module already imports `rr`, `pd`, `json`; reuse the existing `_vg_frame` helper defined at line 276):

```python
# --------------------------------------------------------------------------- provenance gate (2026-08-25)


def _vg_frame_prov():
    """_vg_frame plus the provenance/anchor columns the re-verifier consumes."""
    df = _vg_frame()
    df["row_id"] = ["r1", "r2"]
    df["src_context_id"] = ["ctx1", "ctx2"]
    df["src_facts"] = ["interest_rate=0.105", "interest_rate=11.5"]
    df["src_transforms"] = ["", ""]
    df["corrected_fields"] = ["", ""]
    return df


def test_provenance_integrity_clean_tracked_change():
    base = _vg_frame_prov()
    exp = base.copy()
    exp.loc[0, "interest_rate"] = 10.5  # tracked field, provenance untouched
    checks, reasons = rr.check_provenance_integrity(base, exp)
    assert checks == {"provenance_invariant": True, "changed_fields_tracked": True}
    assert reasons == []


def test_provenance_integrity_flags_modified_src_column():
    base = _vg_frame_prov()
    exp = base.copy()
    exp.loc[0, "interest_rate"] = 10.5
    exp["src_facts"] = ""  # applier clobbered the anchor state
    checks, reasons = rr.check_provenance_integrity(base, exp)
    assert checks["provenance_invariant"] is False
    assert any("src_facts" in r for r in reasons)


def test_provenance_integrity_flags_stamped_corrected_fields():
    # Production stamps corrected_fields OUTSIDE the applier; an applier
    # writing it directly is a defect, not a convenience.
    base = _vg_frame_prov()
    exp = base.copy()
    exp.loc[0, "interest_rate"] = 10.5
    exp.loc[0, "corrected_fields"] = "interest_rate"
    checks, _ = rr.check_provenance_integrity(base, exp)
    assert checks["provenance_invariant"] is False


def test_provenance_integrity_flags_dropped_prov_column():
    base = _vg_frame_prov()
    exp = base.copy().drop(columns=["src_context_id"])
    checks, reasons = rr.check_provenance_integrity(base, exp)
    assert checks["provenance_invariant"] is False
    assert any("src_context_id" in r for r in reasons)


def test_provenance_integrity_flags_untracked_changed_column():
    base = _vg_frame_prov()
    base["bdc_form_type"] = ["10-K", "10-K"]  # not in CORRECTED_TRACKED_FIELDS
    exp = base.copy()
    exp.loc[0, "bdc_form_type"] = "10-Q"
    checks, reasons = rr.check_provenance_integrity(base, exp)
    assert checks["changed_fields_tracked"] is False
    assert any("bdc_form_type" in r for r in reasons)


def test_provenance_integrity_ignores_added_rows():
    # missing_position_add appends new index labels; production stamps them
    # '_row:added'. Only surviving rows are compared.
    base = _vg_frame_prov()
    new_row = base.iloc[[0]].copy()
    new_row.index = [99]
    new_row["issuer_name"] = "Gamma Inc"
    new_row["src_facts"] = "fair_value=500"
    exp = pd.concat([base, new_row])
    checks, reasons = rr.check_provenance_integrity(base, exp)
    assert checks == {"provenance_invariant": True, "changed_fields_tracked": True}
    assert reasons == []


def test_provenance_integrity_trivial_without_prov_columns():
    # Minimal fixtures (existing value-gate tests) carry no provenance columns:
    # nothing to check, both predicates pass.
    base = _vg_frame()
    exp = base.copy()
    exp.loc[0, "interest_rate"] = 10.5
    checks, reasons = rr.check_provenance_integrity(base, exp)
    assert checks == {"provenance_invariant": True, "changed_fields_tracked": True}
    assert reasons == []
```

- [ ] **Step 2: Run the new tests to verify they fail**

Run: `python -m pytest "tests/test_agent_b2_run_remediation.py" -k provenance_integrity -v`
Expected: 7 FAIL/ERROR with `AttributeError: module ... has no attribute 'check_provenance_integrity'`

- [ ] **Step 3: Implement the function**

Insert in `scripts/agent_b2/run_remediation.py` immediately after `_canonical_value_frame` (ends near line 443) and before `gate_value_packet`:

```python
# --------------------------------------------------------------------------- provenance gate (2026-08-25)

# Provenance/anchor columns an applier must NEVER write. These carry the
# re-verifier's anchor state (pipeline/provenance_reverify.py) plus the
# corrected_fields stamp, which production applies OUTSIDE the applier
# (pipeline/agent_promoted.py mark_corrected_fields). Any applier diff here is
# a defect, not a correction. source_row_id may be absent from holdings frames
# (recon-side id); only columns present in the baseline are inspected.
_PROVENANCE_COLUMNS = [
    "row_id", "source_row_id", "src_context_id", "src_context_count",
    "src_facts", "src_transforms", "src_filled_fields", "src_conflict_fields",
    "src_field_overrides", "corrected_fields",
]


def _norm_str(s: pd.Series) -> pd.Series:
    """mark_corrected_fields comparison normalization -- the gate's notion of
    'changed' must equal the production stamp's notion."""
    return s.astype("string").str.strip().fillna("")


def check_provenance_integrity(
    baseline_df: pd.DataFrame, expected_df: pd.DataFrame,
) -> tuple[dict[str, bool], list[str]]:
    """Provenance predicates over the gate's own replay frame:

    - provenance_invariant: _PROVENANCE_COLUMNS byte-identical on rows that
      survive the applier (index intersection; appliers preserve labels).
      A provenance column dropped by the applier also fails.
    - changed_fields_tracked: every other changed column is in
      CORRECTED_TRACKED_FIELDS, so the production corrected_fields stamp
      records it and the re-verifier excuses it; a changed untracked column
      would surface post-promotion as unexplained ledger drift.

    Rows added by the applier (new index labels) are exempt -- production
    stamps them '_row:added'. Judged on expected_df (applier(baseline)), not
    the staged trial: promotion re-applies the correction JSON in production,
    so the applier's own behavior is what ships.
    """
    from pipeline.agent_promoted import CORRECTED_TRACKED_FIELDS

    checks = {"provenance_invariant": True, "changed_fields_tracked": True}
    reasons: list[str] = []
    common = baseline_df.index.intersection(expected_df.index)

    prov_bad: list[str] = []
    untracked: list[str] = []
    for col in baseline_df.columns:
        if col not in expected_df.columns:
            if col in _PROVENANCE_COLUMNS:
                prov_bad.append(f"{col} (dropped)")
            continue
        b = _norm_str(baseline_df.loc[common, col])
        e = _norm_str(expected_df.loc[common, col])
        if bool((b != e).any()):
            if col in _PROVENANCE_COLUMNS:
                prov_bad.append(col)
            elif col not in CORRECTED_TRACKED_FIELDS:
                untracked.append(col)

    if prov_bad:
        checks["provenance_invariant"] = False
        reasons.append(f"applier modified provenance column(s): {prov_bad}")
    if untracked:
        checks["changed_fields_tracked"] = False
        reasons.append(
            f"applier changed untracked column(s) {untracked}: the production "
            f"corrected_fields stamp would miss them (unexplained reverifier drift)")
    return checks, reasons
```

- [ ] **Step 4: Run the new tests to verify they pass**

Run: `python -m pytest "tests/test_agent_b2_run_remediation.py" -k provenance_integrity -v`
Expected: 7 PASS

- [ ] **Step 5: Commit**

```bash
git add scripts/agent_b2/run_remediation.py tests/test_agent_b2_run_remediation.py
git commit -m "b2 gate: check_provenance_integrity predicate function

- provenance_invariant: appliers must never write/drop src_*, row_id, corrected_fields
- changed_fields_tracked: every applier-changed column must be in CORRECTED_TRACKED_FIELDS
- comparison semantics mirror mark_corrected_fields (string-normalized, index-aligned)"
```

---

### Task 2: Wire predicates into `gate_value_packet`

**Files:**
- Modify: `scripts/agent_b2/run_remediation.py` (`gate_value_packet`, currently lines 446-567: docstring + one call site)
- Test: `tests/test_agent_b2_run_remediation.py` (append after Task 1's tests)

**Interfaces:**
- Consumes: `check_provenance_integrity(baseline_df, expected_df)` from Task 1 (same module).
- Produces: `gate_value_packet` result `checks` dict gains keys `provenance_invariant` and `changed_fields_tracked`; either being False makes the verdict FAIL (existing `verdict = "PASS" if all(checks.values())` logic — no change needed there).

- [ ] **Step 1: Write the failing gate-level tests**

Append to `tests/test_agent_b2_run_remediation.py` (the gate imports `apply_scoped` at call time via `from pipeline.agent_b2_appliers import ...`, so monkeypatching the module attribute reaches it):

```python
def test_value_gate_passes_with_provenance_columns_intact():
    from pipeline.agent_b2_appliers import apply_rate_rescale
    base = _vg_frame_prov()
    trial, _ = apply_rate_rescale(base, _vg_corr()["template"])
    res = rr.gate_value_packet(cik="0000000100", target_quarter="2025-12-31",
                               baseline_df=base, trial_df=trial, correction=_vg_corr())
    assert res["verdict"] == "PASS", res["reasons"]
    assert res["checks"]["provenance_invariant"] is True
    assert res["checks"]["changed_fields_tracked"] is True


def test_value_gate_fails_when_applier_clobbers_provenance(monkeypatch):
    import pipeline.agent_b2_appliers as appliers
    base = _vg_frame_prov()

    def bad_apply_scoped(df, correction):
        out = df.copy()
        out.loc[out["issuer_name"] == "Alpha Corp", "interest_rate"] = 10.5
        out["src_facts"] = ""  # simulated applier defect
        return out, {"status": "ok", "rows_changed": 1}

    monkeypatch.setattr(appliers, "apply_scoped", bad_apply_scoped)
    trial, _ = bad_apply_scoped(base, None)
    res = rr.gate_value_packet(cik="0000000100", target_quarter="2025-12-31",
                               baseline_df=base, trial_df=trial, correction=_vg_corr())
    assert res["verdict"] == "FAIL"
    assert res["checks"]["provenance_invariant"] is False
    assert any("src_facts" in r for r in res["reasons"])
```

- [ ] **Step 2: Run the new tests to verify they fail**

Run: `python -m pytest "tests/test_agent_b2_run_remediation.py" -k "provenance_columns_intact or clobbers_provenance" -v`
Expected: 2 FAIL with `KeyError: 'provenance_invariant'`

- [ ] **Step 3: Wire the call into `gate_value_packet`**

In `gate_value_packet`, immediately after the magnitude block (after `reasons.extend(mag_reasons)`, currently line 526), insert:

```python
    prov_checks, prov_reasons = check_provenance_integrity(baseline_df, expected_df)
    checks.update(prov_checks)
    reasons.extend(prov_reasons)
```

And add two bullets to the `gate_value_packet` docstring predicate list (after the `magnitude_plausible` bullet):

```
    - provenance_invariant: the applier must not write or drop provenance/anchor
      columns (src_*, row_id, corrected_fields); production stamps corrected_fields
      outside the applier, and the re-verifier's anchor state must survive.
    - changed_fields_tracked: every column the applier changes must be in
      CORRECTED_TRACKED_FIELDS so the production corrected_fields stamp records
      it; an untracked change would surface as unexplained reverifier drift.
```

- [ ] **Step 4: Run the whole value-gate + provenance test set, then the full file**

Run: `python -m pytest "tests/test_agent_b2_run_remediation.py" -v`
Expected: ALL PASS — including every pre-existing value-gate test (their fixtures lack provenance columns, so the new predicates pass trivially per Design Decision 4). Any pre-existing test now failing is a regression: stop and fix before committing.

- [ ] **Step 5: Commit**

```bash
git add scripts/agent_b2/run_remediation.py tests/test_agent_b2_run_remediation.py
git commit -m "b2 gate: wire provenance predicates into gate_value_packet

- provenance_invariant + changed_fields_tracked now FAIL the value gate
- judged on the gate's own replay frame (applier(baseline)), matching what promotion ships
- existing minimal fixtures unaffected (no provenance columns -> trivially pass)"
```

---

### Task 3: Verification backstop + changelog

**Files:**
- Modify: `docs/agent_changelog.md` (append only — never edit existing entries)

**Interfaces:**
- Consumes: completed Tasks 1-2.
- Produces: changelog entry; verified-clean semantic diff.

- [ ] **Step 1: Confirm no other pytest/rebuild processes, then run the targeted file once more**

Run: `Get-Process python -ErrorAction SilentlyContinue | Select-Object Id, StartTime, CPU` then
`python -m pytest "tests/test_agent_b2_run_remediation.py" -q`
Expected: all tests pass, no overlapping suites running.

- [ ] **Step 2: Run the production-artifact backstop**

Run: `python scripts/diff_outputs.py --semantic`
Expected: no artifact drift (the tests write nothing to `data/output/` — the conftest guard blocks it, this confirms).

- [ ] **Step 3: Append the changelog entry**

Append to `docs/agent_changelog.md`:

```markdown
## 2026-08-25: Provenance-integrity predicates in the B2 value gate

- `scripts/agent_b2/run_remediation.py`: new `check_provenance_integrity` +
  `_PROVENANCE_COLUMNS`; `gate_value_packet` gains two predicates:
  `provenance_invariant` (appliers must not write/drop src_*, row_id,
  corrected_fields) and `changed_fields_tracked` (every applier-changed column
  must be in CORRECTED_TRACKED_FIELDS, else the production stamp would miss it
  and the provenance re-verifier would report unexplained drift post-promotion).
- Judged on the gate's replay frame (applier(baseline)); comparison semantics
  mirror `mark_corrected_fields`. Scope: value gate only -- wrapper-patch
  (stage-1) corrections legitimately change source-level provenance.
- Contract: promotion-time detection of provenance clobbering/unstamped drift;
  previously only detectable post-promotion in the quarter-pass ledger.
- Tests: +9 in `tests/test_agent_b2_run_remediation.py` (7 unit, 2 gate-level).
```

- [ ] **Step 4: Commit**

```bash
git add docs/agent_changelog.md
git commit -m "docs: changelog entry for B2 value-gate provenance predicates

- records new gate contract and test counts"
```

---

## Self-Review Notes

- **Spec coverage:** provenance_invariant (Task 1 Steps 1/3, Task 2), changed_fields_tracked (same), added-row exemption (Task 1 test), backward compatibility with provenance-free fixtures (Task 1 test + Task 2 Step 4), scope limited to value gate (no conservation-gate changes anywhere), changelog protocol (Task 3).
- **Deliberately out of scope:** running `provenance_reverify` inside the gate (redundant with these predicates and erodes the independent-validation property); corrections-as-declared-transforms (separate future project, revisit when the `corrected` FV share in the ledger becomes material, ~1% of cohort FV).
- **Type consistency:** `check_provenance_integrity` returns `(dict[str, bool], list[str])` and is consumed with `checks.update(...)` / `reasons.extend(...)` — matches `check_magnitude_plausibility`'s wiring pattern in the same function.
