# Agentic investigation path -- root-cause + author auditable rules (bypasses the B2 battery)

Status: built + proven end-to-end on cik 1377936 (deterministic spine). The live Codex run is an
operator step.

## The point

A clean agentic path: the agent investigates a conservation FV discrepancy ITSELF (like the
manual Saratoga root-cause), and AUTHORS auditable rule(s). No deterministic battery, no probe
deciders, no template registry, no `MECHANISM_TO_FIX_CLASS` guessing. Deterministic stays only as
(a) the safe read-only tools the agent queries and (b) the un-gameable validator (B3).

```
prep  -> build the agent's prompt + manifest + the cik's conservation residual (the score)
[Codex worker] -> investigate with data_query_cli (extracted data) + evidence_cli (filing)
              -> author rule(s) to data/output/agent_investigate/<cik>/rules/<id>.json
apply -> apply the authored rules to a TRIAL holdings frame (general predicate applier), per-quarter audit
gate  -> B3 conservation re-check (target cleared, no over-deletion, held-out not regressed)
```

## Pieces

- `pipeline/agent_data_query.py` + `scripts/review_agent/data_query_cli.py` -- read-only,
  cik-scoped query over holdings/staging/fund_financials/conservation (the agent's DuckDB).
- `pipeline/agent_rule.py` -- the AUDITABLE rule schema + appliers (common fields: scope,
  evidence, rationale, per-quarter measured_impact, confidence). Four rule_types, one per defect
  class -- pick the type that matches the defect, never delete a real position to mask a value/
  anchor bug:
  - `row_exclusion` (predicate_sql) -- drop over-counted / leaked rows.
  - `dedup` (match_fields + keep, optional predicate) -- collapse true duplicates, one per key.
  - `value_rescale` (predicate_sql + field + factor) -- fix a scale/unit error (e.g. fair_value
    1000x too large -> factor 0.001) WITHOUT deleting the position. `field` limited to a
    value-column allowlist.
  - `row_add` (positions[]) -- recover an UNDER-counted position (FV < anchor). Each position is
    grounded by a mandatory `source_row_id` (the iXBRL/staging row recovered) and carries
    `bdc_dimensions_raw` so it is counted; the agent finds it by querying `staging` for rows
    present there but missing from `holdings`.
  Plus a GENERAL applier per type (per-quarter audit) and the B3 gate wrapper.
- `scripts/agent_investigate/run_investigation.py` -- `prep` / `apply` / `gate`.
- `scripts/dispatch_investigation.ps1` -- one Codex worker: sandbox (read repo, write only the
  rules dir) -> run on the prompt -> apply -> gate. Operator-run, outside a Codex session.

## Why this is the auditable-code-rule form you wanted

A rule is reviewable: `predicate_sql` reads like code, `rationale` says why, `evidence` cites the
filing/queries, `measured_impact` is per-quarter (never a blanket cross-quarter number). It is
version-controllable per-CIK and deterministically replayable. The agent is what AUTHORS it; the
applier executes it; B3 gates it.

## Worked proof (cik 1377936, 2026-02-28)

`prep` -> anchor 1,109,133,812 over 6 quarters. A simulated agent rule (the CLO look-through
exclusion) -> `apply` excluded 1456 rows with a PER-QUARTER audit (246 rows / 376,435,958 in the
target quarter; 272-335 rows in each other quarter). `gate` -> **FAIL (correctly)**:
`no_over_deletion=false` -- dropping the CLO collateral pushes value_sum ~17-20M BELOW the anchor
in EVERY quarter. That is the compound defect surfacing: a systematic ~18M/quarter UNDER-count
(the under-valued controlled equity line) coexists with the CLO over-count. One rule cannot
resolve it; the gate demands the full set. A complete agent solution authors a SECOND rule for the
under-count (which needs an add/value rule_type, the next vocabulary item) -- the harness already
loads and gates multiple rules.

## B2 consolidation -- one substrate, agentic authoring (steps 1-4)

The deterministic template-author B2 (`dispatch_agent_b2_workers` -> fill a `correction_leaf`
template) no-op'd 3/3 at the B3 gate (subtotal_filter = filing-label mismatch; comparative =
the unified frame has no `period` column) and drifted fix_class (emitted subtotal_filter for
classification/rule_scope requests). The remediation engine is now the AGENTIC path; the
deterministic pieces that are load-bearing or shared are KEPT and unified, not deleted.

1. **One applier set** -- `pipeline/agent_rule.py` (`row_exclusion`/`dedup`/`value_rescale`/
   `row_add`) is canonical. The legacy `pipeline/agent_b2_appliers.py` + `agent_b2_wrapper_patch.py`
   are superseded (quarantined, not deleted, pending the agentic track record).
2. **One gate** -- `agent_rule.gate_rules` wraps `agent_b_held_out.gate_correction` and adds the
   `no_over_addition` + `anchor_sanity` guards. That is the single remediation gate.
3. **One driver** -- `scripts/agent_investigate/run_investigation.py` now also has `discover`
   (B1 verdicts -> investigation worklist) and `promote` (gate-PASS rules -> overrides), the two
   orchestration pieces it lacked. The deterministic `run_remediation` author/apply/promote path
   is superseded for authoring.
4. **B1 -> agentic** -- `discover` reads the B1 batch worklist + verdicts and emits a
   `(cik, target_quarter)` target for every `real_error`. B1's mechanism GUESS is intentionally
   NOT used; the agent finds the mechanism by investigating the EXTRACTED data (which is why the
   template-author failed and the agent succeeds, e.g. 1715933 -> 0.0% gate PASS).

End-to-end: `discover <batch> --source-worklist <B1 worklist>` -> per target,
`dispatch_investigation.ps1` (prep/investigate/author/apply/gate loop) -> `promote --cik <cik>
--target-quarter <q>` (copies rules to `data/overrides/agent_investigate_rules/` iff gate PASS).

COORDINATION: the B1-before-B2 work currently wires into the deterministic `run_remediation`; that
wiring should point at `run_investigation discover` instead. Do not delete the deterministic
author/appliers until the agentic loop has a real multi-CIK gate-PASS track record (currently ~2).

## Not done

- The live Codex run (operator: `scripts/dispatch_investigation.ps1 -Cik 1377936 -TargetQuarter 2026-02-28`).
- Deleting the quarantined deterministic author/appliers (after the agentic track record lands).
- A source-pull `row_add` (applier reads values from `staging` by `source_row_id`).
