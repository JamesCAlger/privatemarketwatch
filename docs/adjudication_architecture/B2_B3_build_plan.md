# Agent B2 (Remediator) + B3 (held-out gate) build plan

Status: plan only. Builds on the LIVE-validated B1 adjudicator (96% vs the 24-label gold,
env stable, schema gate scoped). Companion specs: `B_build_plan_codex_fleet.md` (B1
plumbing, sections 3.6/3.7 sketch B2/B3), `B_and_C_validation_agents.md` (architecture),
`A_identifier_enrichment_agent.md` + `A2_sandbox_task_contract.md` (the harness reused).

Runtime decision (inherit B1): B2 workers run on the **external Codex worker fleet**, reusing
the same sandbox harness. B3 is **pure deterministic Python** (no LLM) -- it is the check the
agent cannot game.

## 0. The shape, and why it is the same skeleton as A and B1

A and B1 both realize: `deterministic builds a bounded item -> blinded LLM worker emits
structured JSON to an append-only dir -> deterministic check the worker cannot game ->
promotion`. B2/B3 is the SAME skeleton, one level downstream:

```
B1 real_error verdicts (grouped by CIK x mechanism-stage)
  -> B2 worker PROPOSES a constrained correction (template instance, audited JSON -- NEVER code)
     to corrections/<cik>/<mechanism>.json
  -> validate_correction (schema) + apply to a TRIAL wrapper via rebuild_unified_cik_trial.py
  -> B3 held-out gate: re-run the FULL ledger on ALL the CIK's quarters; joint promote predicates
  -> B4 promotion (human or materiality-tiered auto), regenerate ledger, re-triage, descend
```

B2's worker output is gated by **schema + the B3 deterministic re-run**, exactly as A's
grammar proposals are gated by `validate_proposal` + `identifier_held_out`. The genuine new
content is (a) the constrained correction templates, (b) B3's joint predicates, and (c) the
**mechanism-precedence ordering** below -- structural fixes must precede the rules that
depend on them.

## 1. Mechanism precedence -- the rule-ordering constraint (READ FIRST)

Some corrections change the INPUTS to other rules, so they MUST be applied (and the trial
ledger regenerated) before the dependent rules are re-judged or gated. Judging a conservation
overshoot before removing a duplicate that caused it mis-attributes the residual and gates
against contaminated inputs. The `fix_class` on each B1 finding carries the stage:

- **Stage 1 -- population / structure** (change WHICH rows exist): `dedup`,
  `subtotal_filter`, `comparative_period_filter`, `missing_position_add`.
- **Stage 2 -- per-row value / scale / mapping** (change row VALUES): `rate_rescale`,
  `all_pik_normalization`, `column_remap`, `unit_rescale`, `classification_fix`.
- **Stage 3 -- aggregate / identity RE-CHECKS** (consume the above): `fv_conservation`,
  `pct_of_net_assets`, `pik_le_interest_rate`, C113. These are not separate "fixes" -- a
  Stage-3 flag's resolution IS its upstream mechanism; you apply that mechanism, regenerate,
  and confirm the flag clears.

Loop invariant: **apply a stage's corrections for a CIK -> regenerate the trial ledger ->
RE-TRIAGE -> only then advance to the dependent stage.** Re-triage is mandatory because a
flag that fired pre-dedup may vanish post-dedup (the dup WAS the defect) -- you must not
remediate a phantom, and you must not gate a Stage-3 flag on a pre-Stage-1 ledger.

This is orthogonal to materiality: the §4.3 tier loop chooses WHICH CIK/flag to target
(Tier 0 = conservation, biggest FV); precedence dictates the ORDER of mechanism application
WITHIN that target. A Tier-0 conservation flag can only be FINALIZED for a CIK once that
CIK's Stage-1 structural fixes are applied and the ledger regenerated.

## 2. Reuse seams: generalize vs fork vs reuse-as-is

| Component | Disposition | Reason |
|---|---|---|
| `scripts/run_codex_worker.ps1` | reuse as-is | task-agnostic worker runner |
| `scripts/setup_codex_worker_harness.ps1` | reuse | now parameterized (`-WriteDirs`/`-ReadDirs`/`-EnvInherit`/`-AllowUserSite`); B2 write-grant = the corrections dir |
| `scripts/dispatch_agent_b_workers.ps1` | clone -> `dispatch_agent_b2_workers.ps1` | same proven loop; only the python entry points differ (preflight/validate/finalize). (Shared core still deferred.) |
| `scripts/agent_b/dispatch_preflight.py` | fork -> `scripts/agent_b2/dispatch_preflight.py` | manifest keyed by `(cik, mechanism)` packet, not `review_id`; prompt = remediation contract; write-grant = `corrections/<cik>/` |
| `scripts/agent_b/review_lock.py` | reuse as-is | lock on `(cik, mechanism)` packet key |
| `pipeline/verdict_leaf.py` (real_error + findings) | reuse as INPUT | B2 worklist = real_error verdicts grouped by CIK x stage; `findings[].fix_class` selects the template |
| `pipeline/identifier_held_out.py` | clone structure -> `pipeline/agent_b_held_out.py` | the joint-gate pattern; B3 predicates differ (conservation residual, net flags, FV-at-risk, D01/D02 bands, held-out quarters) |
| `scripts/rebuild_unified_cik_trial.py` | reuse as-is | the per-CIK cached trial rebuild (`--match`); B2 applies corrections through it, B3 re-runs the ledger on its output |
| shadow ledger engines + `pipeline/review_queue.py` | reuse | re-triage = regenerate the gate results + queue on the trial-corrected holdings |
| `scripts/review_agent/evidence_cli.py` | reuse as-is | the B2 worker's only raw-source window, scoped to the packet's bundles |
| `scripts/gold/*` | reuse | measure B2 fix-acceptance precision once a human slice of remediations lands |

## 3. Directory layout (mirror A/B1 under `data/output/agent_b2/`)

```
data/output/agent_b2/
  batch/<batch_id>/
    worklist.csv            # (cik, mechanism, stage, n_findings, source_review_ids)
    manifest.json           # preflight output, keyed by (cik, mechanism) packet
    prompts/<cik>__<mechanism>.md
    logs/<...>.{stdout.jsonl,stderr.txt,validate.txt}
    held_out/<cik>.json     # B3 gate result per CIK
  corrections/<cik>/<mechanism>.json   # B2 worker output (the sandbox write-grant dir)
  trial/<cik>/...                      # rebuild_unified_cik_trial.py output (cached-only)
```

Corrections are audited per-CIK config (Layer 2 of the agentic-data-quality design):
schema + mechanism + evidence + confidence + audit trail. NEVER production CSV/JSON.

## 4. New / changed files, in build order

### 4.1 Correction-leaf schema + template registry
`pipeline/correction_leaf.py` (new, pure -- the B2 analog of `verdict_leaf.py`): the schema a
B2 worker must emit, one per `(cik, mechanism)` packet. Required: `cik`, `mechanism`,
`fix_class`, `stage` (derived from fix_class), `template` (the constrained instance --
e.g. dedup keys, subtotal patterns, the cash/pik split mapping, the rescale factor),
`source_review_ids[]`, `evidence_citations[]`, `confidence`, `rationale`. Hard invariants:
`fix_class` in `KNOWN_FIX_CLASSES`; `template` shape matches the registered template for that
fix_class; >=1 evidence citation; NO free-form code, NO file paths, NO SQL. Plus a
`TEMPLATE_REGISTRY` mapping `fix_class -> (param schema, apply-fn name in the trial wrapper)`.

### 4.2 B2 preflight + manifest + worker prompt
`scripts/agent_b2/dispatch_preflight.py` (fork of B1's): reads the B2 worklist (real_error
verdicts grouped by `(cik, mechanism)`, one packet per row), validates each source verdict +
its findings, B0-short-circuits packets whose findings lack a `fix_class` to human, acquires a
per-packet lock, writes `manifest.json` + per-packet blinded prompts. Prompt = the remediation
contract (4.3); absolute paths + explicit interpreter (inherit B1's env fixes).

New doc: `docs/adjudication_architecture/B2_remediation_contract.md`. Hard rules: propose ONE
template instance for ONE `(cik, mechanism)`; re-ground every finding against source via
evidence_cli (do NOT trust the B1 hint blindly); emit the correction leaf to the one allowed
path; NO code, NO production writes, NO rebuilds/network. Self-validate with the correction
validator.

### 4.3 Trial apply + re-triage driver
`scripts/agent_b2/run_remediation.py` (the B1 `run_review` analog) with modes:
- `discover <batch_id>` -- group current real_error verdicts by `(cik, mechanism)`, tag each
  with its `stage`, write the stage-ordered worklist.
- `apply <batch_id> --cik <cik> --stage <N>` -- bind each validated correction to its template
  via `rebuild_unified_cik_trial.py`, producing trial-corrected holdings for that CIK.
- `retriage <cik>` -- regenerate the gate results + review queue on the trial holdings (the
  precedence loop's mandatory step between stages).
- `finalize <batch_id>` -- collect correction leaves, validate, route to B3.

### 4.4 B3 held-out gate
`pipeline/agent_b_held_out.py` (clone `identifier_held_out.py` structure). Re-run the FULL
deterministic ledger on ALL quarters of the CIK from the trial-corrected holdings; promote a
correction only if JOINTLY:
- the target flag(s) cleared;
- net flags across the CIK non-increasing (no new flags elsewhere);
- FV-at-risk non-increasing AND (for conservation) the residual moved toward the anchor;
- D01/D02 count/FV bands hold;
- held-out quarters (>=2, all other quarters of the CIK) not regressed.
Fail -> reject + escalate. Two mandatory false-positive guards (4.6): a delete-to-balance
"fix" must be REJECTED, and a single-quarter-overfit must be caught by the held-out quarters.

### 4.5 B4 promotion + tier loop
`scripts/agent_b2/run_remediation.py promote`: human, or auto under materiality tiers
(P0 $25M/1%, P1 $5M/0.25%) with B3 green. Then the serialized §4.3 loop: pick highest
unfinalized tier -> for each firing CIK, run the precedence loop (Stage 1 -> regenerate ->
retriage -> Stage 2 -> ... -> Stage 3 gate) -> promote -> regenerate the production-candidate
ledger deterministically -> re-triage residual -> advance. Tier 0 (FV conservation) first.

## 5. Milestones (each independently testable, cached-only)

1. **M-B2.0 -- schema + registry.** 4.1. Unit tests: template shape validation, fix_class
   gating, stage derivation, citation requirement. No LLM.
2. **M-B2.1 -- one mechanism family end to end.** 4.2 + 4.3(`discover`,`apply`) for Stage-1
   `dedup`/`subtotal_filter` on Tier-0 conservation CIKs (the cleanest mechanism, biggest FV).
   Dispatch real Codex workers; corrections land in the trial wrapper only.
3. **M-B3.1 -- the gate.** 4.4 on the M-B2.1 trial CIKs. Confirm clears + the two
   false-positive guards reject.
4. **M-B2/B3.2 -- the precedence loop on one CIK.** Stage 1 -> regenerate -> retriage ->
   Stage 2/3, proving a conservation flag resolves only after its upstream dedup is applied.
5. **M-B4 -- promotion + tier loop.** 4.5; promote Tier 0, regenerate, descend.

## 6. Test plan (proportional, per AGENTS.md)

- 4.1: `tests/test_correction_leaf.py` -- template/fix_class/stage/citation invariants;
  reject free-form code / path / SQL fields.
- 4.2: `tests/test_agent_b2_preflight.py` -- packet manifest shape, no-fix_class
  short-circuit, lock acquire/release. Mirror B1.
- 4.3: `tests/test_agent_b2_run_remediation.py` -- stage ordering (Stage-2 packet refused
  until Stage-1 applied+regenerated for the CIK); retriage drops a phantom flag.
- 4.4: `tests/test_agent_b_held_out.py` -- **delete-to-balance must REJECT**; held-out catches
  a **single-quarter overfit**; a genuine subtotal removal PROMOTES.
- Contract: conftest write-guard still blocks production; corrections/trial land only under
  `agent_b2/` and the trial dirs.

## 7. Risks / invariants to hold

- **B2 never writes code or production data.** It proposes a template INSTANCE (audited JSON);
  the trial wrapper applies it; B3 gates it. The B1 `findings` hint is advisory -- B2
  re-grounds against source.
- **Precedence is load-bearing.** Never gate a Stage-3 flag on a pre-Stage-1 ledger; always
  regenerate + re-triage between stages. This is the single most likely source of a wrong
  "fix" that balances the target while corrupting inputs.
- **B3 is the un-gameable check** -- a deterministic full-ledger re-run on held-out quarters
  the agent never saw. Keep its predicates joint (clearing the target is necessary, not
  sufficient).
- **PIK all-in coupling** (from the interest-rate-cashpay-convention memory): the
  `all_pik_normalization` template, if it re-derives `interest_rate = cash+pik`, MUST drop the
  `+ pik_rate_pct` add in `index_returns.py:~241` atomically, or PIK income double-counts. Gate
  this on an income/returns regression check, not just the flag clearing.
- **Per-CIK by default** (Decision 1); a global rule only on >=3-5 unrelated CIKs + full
  regression.
- **Cached-only, append-only, ASCII logs, no rebuild/network in the worker** -- inherited from
  the A/B1 sandbox.
