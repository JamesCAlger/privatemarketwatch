# Agent B build plan — external Codex worker fleet (reusing Agent A's harness)

Status: plan only. Runtime decision (owner, 2026-06-23): **B1 runs on the external
Codex worker fleet**, generalized from Agent A's dispatcher, not the in-session skill
path. This document is file-by-file; it does not change pipeline behavior yet.

Companion specs: `B_and_C_validation_agents.md` (architecture), `A_identifier_enrichment_agent.md`
+ `A2_sandbox_task_contract.md` (the harness being reused).

## M1 build record (2026-06-23) -- what shipped + corrections

M1 (fleet plumbing) is built and unit-tested (cached-only, no Codex run here). Two
corrections to the original plan, discovered by reading source:

1. **Lineage.** The verdict-LEAF lineage is `pipeline/review_queue.py` +
   `pipeline/review_bundles.py` + `scripts/review_agent/` (RVQ_BLK_*/RVQ_REV_* ids,
   `review-bundle.v1`, verdicts under `data/output/review_queue/verdicts/`). The older
   `pipeline/bdc_cik_review.py` is a DIFFERENT (patch-proposal) lineage; its
   `cli_validate_verdicts` validates that schema, NOT the leaf. The plan's reuse table
   wrongly named it the leaf validator.
2. **The leaf validator did not exist** -- the 45 trial verdicts passed on agent
   discipline alone. Built it: `pipeline/verdict_leaf.py` (pure schema + grounding
   invariant) + `scripts/review_agent/validate_leaf_verdicts.py` (CLI). Verified against
   all 45 trial verdicts: 45/45 valid, 0 errors (warnings only, on extended
   mechanism/anchor vocabulary -- soft-warn by design).

Shipped in M1:
- `pipeline/verdict_leaf.py` -- leaf schema, grounding invariant, Wilson; pure.
- `scripts/review_agent/validate_leaf_verdicts.py` -- validator CLI (worker self-check
  + batch check).
- `scripts/agent_b/{__init__,review_lock,dispatch_preflight,run_review}.py` -- the B
  spine: per-review_id lock, preflight (manifest + blinded prompts + B0 short-circuit),
  discover/finalize driver.
- `scripts/setup_codex_worker_harness.ps1` -- generalized with `-WriteDirs` (A behavior
  unchanged when omitted).
- `scripts/dispatch_agent_b_workers.ps1` -- B fleet dispatcher.
- `docs/adjudication_architecture/B1_adjudication_contract.md` -- worker contract.
- `tests/test_verdict_leaf.py`, `tests/test_agent_b_preflight.py` -- 24 tests, green.

Deviation from 3.2: the shared dispatch core was NOT extracted and A's dispatcher was
NOT touched. Refactoring the only working external dispatcher with no way to smoke-test
Codex here is the wrong M1 risk. The B dispatcher duplicates A's proven loop on purpose;
extracting the shared core stays deferred until an operator can run both A and B.

Not yet done (needs an operator outside a Codex session): the live fleet smoke run
re-adjudicating the 45-bundle trial through Codex workers and confirming verdicts match.

## 0. What we are reusing and why it fits

Agent A and Agent B share one skeleton:

```
deterministic builds a bounded item  ->  blinded LLM worker emits structured JSON
   to an append-only dir  ->  deterministic check the worker cannot game  ->  promotion
```

A realizes this as: `sample_variant` -> Codex worker writes `proposals/<CIK>.{anchors,grammar}.json`
-> `validate_proposal` (schema) + `identifier_held_out` (numeric gate) -> `run_quarter gate`.

B realizes the SAME mechanics for B2/B3/B4. The single genuine divergence is **B1**:
"is this flag a real error?" has no numeric oracle, so B1's worker output (a verdict
leaf) is gated by **schema validation only**, and its *correctness* is measured
statistically through the gold apparatus (`scripts/gold/`, Rogan-Gladen), NOT by a
pass/fail re-run. Do not invent a deterministic B1 gate — it would just re-encode the
agent's own judgment. The deterministic re-run gate (B3) belongs to B2's *fixes*, not
to B1's *verdicts*.

## 1. Reuse seams: generalize vs fork vs reuse-as-is

| Component | Disposition | Reason |
|---|---|---|
| `scripts/run_codex_worker.ps1` | **reuse as-is** | already task-agnostic: takes `-PromptPath`, sets `CODEX_HOME`, runs `codex exec --ephemeral --json`. No A-specifics. |
| `scripts/setup_codex_worker_harness.ps1` | **generalize** | hard-codes the anchors/grammars/proposals dirs + write grant. Parameterize the read-required dirs and the write-grant dir(s). |
| `scripts/dispatch_agent_a_workers.ps1` | **generalize -> shared core** | body is ~95% task-agnostic; only 3 python entry points are A-specific (preflight, validate, finalize+gate). Extract a parameterized core; keep thin A/B wrappers. |
| `scripts/agent_a/dispatch_preflight.py` | **fork to `scripts/agent_b/dispatch_preflight.py`** | manifest is keyed `(cik, signature, quarter)` + A bundle schema + A prompt. B keys on `review_id` + B bundle schema + B prompt. Structurally identical, semantically different — fork is cleaner than overloading. |
| `scripts/agent_a/cik_lock.py` | **reuse as-is** | claim/reservation by id; B locks on `review_id` (or `(cik, rule)`), same primitive. |
| `pipeline/review_bundles.py` (B0) | **reuse as-is** | already builds `review_bundles/{review_id}.json` for 16 engines. |
| `scripts/bdc_cik_review/build_worklist.py` | **reuse / extend** | A's `run_quarter discover` analog already exists. Feeds the B worklist. |
| `pipeline/bdc_cik_review.py:cli_validate_verdicts` | **reuse as-is** | the verdict-leaf schema validator = B's `validate_proposal` analog. |
| `scripts/review_agent/evidence_cli.py` | **reuse as-is** | the worker's only raw-source window (overview/tables/grid/roam/totals), cache-only, fails closed. |
| `pipeline/identifier_held_out.py` | **clone its structure for B3** | the joint-gate pattern; B3's predicates differ (conservation residual, net-flags, FV-at-risk, D01/D02 bands, held-out quarters). |
| `scripts/gold/*` | **reuse as-is** | B1 calibration + the section-9 measurement (PPS/HT, `estimate_gold`, `per_rule_metrics`, Rogan-Gladen). |

## 2. Directory layout (mirror A under `data/output/agent_b/`)

```
data/output/agent_b/
  batch/<batch_id>/
    worklist.csv                # sampled review_ids for this batch (from build_worklist)
    manifest.json               # dispatch_preflight output (rows keyed by review_id)
    prompts/<review_id>.md       # per-worker prompt (B adjudication contract)
    logs/<review_id>.{stdout.jsonl,stderr.txt,validate.txt}
    wrappers/ worker_home/ worker_runroot/   # per-worker sandbox (as in A)
data/output/review_queue/
  review_bundles/<review_id>.json   # B0 bundles (already produced by review_bundles.py)
  verdicts/<review_id>.json         # B1 worker output (the sandbox write-grant dir)
```

Bundles stay under `review_queue/` (the existing pilot location); only the dispatch
batch scaffolding is new under `agent_b/`. The sandbox grants **write only to
`review_queue/verdicts/`**, repo-root read otherwise.

## 3. New / changed files, in build order

### 3.1 Generalize the sandbox setup
`scripts/setup_codex_worker_harness.ps1` — add params `-ReadDirs string[]`,
`-WriteDirs string[]` (defaults preserve A's anchors/grammars read + proposals write).
Emit the `[permissions.*.filesystem]` block from the params instead of the hard-coded
A dirs. Keep `network.enabled = false`, `approval_policy = "never"`, web_search disabled.

### 3.2 Extract the shared dispatch core
`scripts/dispatch_codex_workers.ps1` (new) — the proven A loop (queue, MaxParallel,
timeout, `Start-Process -PassThru` + `.Handle` capture fix, process-tree kill,
auth-copy, finally-release) parameterized by:
`-PreflightModule`, `-ValidateCmd` (per-row), `-FinalizeCmd`, `-GateCmd`, `-WriteDirs`.
Then reduce `dispatch_agent_a_workers.ps1` to a thin wrapper calling the core with A's
modules (regression-guard: A's existing behavior must stay byte-identical), and add
`scripts/dispatch_agent_b_workers.ps1` calling it with B's modules. NOTE: touching A's
dispatcher requires A's dispatch path to be re-smoke-tested before merge.

### 3.3 B preflight + manifest
`scripts/agent_b/dispatch_preflight.py` (fork of A's) — reads
`agent_b/batch/<batch_id>/worklist.csv` (columns: `review_id, engine, rule_name, cik,
report_date, bundle_path, lane`), validates each `review_bundles/<review_id>.json`
(must have `flag`, `source_artifact_rows`, `holdings_slice`, `coordinates`,
`evidence_completeness`), short-circuits `evidence_completeness in {ledger_only,
artifact_missing}` to an auto `ambiguous`/coverage verdict WITHOUT dispatching a worker
(B0 rule, fail-closed), acquires `cik_lock` per review_id, writes `manifest.json` +
per-row `prompts/<review_id>.md`. Reuse A's `_CIK_RE`, lock, stale-output checks.

### 3.4 B worker prompt (the adjudication contract)
Authored inside 3.3 (A's `_worker_prompt` analog). Hard rules, mirroring A2:
- no nested Codex, no tests/rebuilds/network/SEC/git/repo scans;
- allowed reads: `B1_adjudication_contract.md`, the exact bundle, evidence_cli **only**
  against that bundle;
- allowed write: `review_queue/verdicts/<review_id>.json` only;
- emit the verdict leaf (section 2 of the architecture spec); **invariant: `real_error`
  requires >=1 culprit_citation OR explicit anchor-disagreement proof, else forced
  `ambiguous`**; skeptic default; B0.5 class routing instructions (Class 1 confirm cell;
  Class 2 decide field; Class 3 anchor-triangulate first, then §4.2 row-classification
  via the disposition ledger — never haystack search);
- final step: run `python -m scripts.bdc_cik_review.validate_verdicts --review-id <id>`
  and fix-and-rerun within budget if it fails.

New doc: `docs/adjudication_architecture/B1_adjudication_contract.md` (the B analog of
`A2_sandbox_task_contract.md`).

### 3.5 B finalize + gate driver
`scripts/agent_b/run_review.py` (A's `run_quarter` analog) with modes:
- `discover <batch_id>` — sample the flagged population per §9.4 (per-rule sized,
  stratified by `(engine, rule_name, lane)`), build bundles via `review_bundles.py`,
  write `worklist.csv`. For the §9 measurement pass this is "census/heavy-sample all
  rules"; for the §4.3 remediation loop it is "all firing CIKs for the current tier".
- `finalize <batch_id>` — collect verdicts, run `cli_validate_verdicts` over the batch,
  aggregate via `scripts/bdc_cik_review/summarize_verdicts.py`, route:
  `false_alarm -> rule-scoping queue`, `ambiguous -> human`, `real_error -> B2 queue`.
- `gate <batch_id>` — for B1 this is schema+routing only (no numeric gate). The numeric
  gate lives in B3 (3.7) and runs on B2 fixes, not here.

### 3.6 B2 Remediator
`pipeline/agent_b_remediate.py` (new) — consumes `real_error` verdicts grouped by
`mechanism`, binds each to a constrained template (audited JSON, never free-form code):
per-CIK by Decision 1; mechanism->template->regression-watch per the architecture
spec's table. Writes proposed rules into a **trial** wrapper
`scripts/rebuild_unified_cik_trial.py` (new, cached-only) — never production.

### 3.7 B3 deterministic re-run gate
`pipeline/agent_b_held_out.py` (clone `identifier_held_out.py` structure). Re-run the
FULL ledger on ALL quarters of the CIK from the trial-corrected holdings; promote only
if jointly: target flag cleared; net flags non-increasing; FV-at-risk non-increasing AND
residual moved toward anchor; D01/D02 count/FV bands hold; held-out quarters (>=2, all
other quarters of the CIK) not regressed. Fail -> reject + escalate. This is the check B
cannot satisfy by editing its own output.

### 3.8 B4 promotion + §4.3 tier loop
`scripts/agent_b/run_review.py promote` — human promotes, or auto under materiality
tiers (P0 $25M/1%, P1 $5M/0.25%) with B3 green. Then the serialized loop (§4.3b): pick
highest unfinalized tier -> adjudicate+remediate+gate all firing CIKs -> regenerate the
ledger deterministically (cached rebuild, no LLM) -> re-triage residual -> advance.
Tier 0 (FV conservation) finalizes first.

## 4. Sequencing (each milestone independently testable, cached-only)

1. **M1 — fleet plumbing.** 3.1 + 3.2 + 3.3 + 3.4 + 3.5(`discover`,`finalize`).
   Re-run the existing 45-bundle trial through the fleet instead of in-session; verdicts
   must match the trial's verdicts within adjudication noise. Proves the harness reuse.
2. **M2 — §9 measurement pass.** `discover` over the full registry (sample-sized),
   dispatch, `finalize`, then `scripts/gold/per_rule_metrics.py` + `estimate_gold.py` ->
   per-rule precision table that replaces the heuristic `confidence` column.
3. **M3 — B2/B3.** 3.6 + 3.7 on Tier-0 conservation real_errors only (the BCRED-class
   and subtotal-leak cases), trial wrapper + re-run gate, no production writes.
4. **M4 — B4 + tier loop.** 3.8; promote Tier 0, regenerate, descend.

## 5. Test plan (proportional, per AGENTS.md)

- 3.1/3.2/3.4: PowerShell smoke — sandbox config emits correct grants; A dispatcher
  regression smoke (A behavior unchanged).
- 3.3: `tests/test_agent_b_preflight.py` — manifest shape, evidence_completeness
  short-circuit, lock acquire/release, stale-verdict refusal. Mirror A's preflight tests.
- 3.5: `tests/test_agent_b_run_review.py` — discover sampling sizes to target CI width;
  finalize routing (false_alarm/ambiguous/real_error).
- 3.6/3.7: `tests/test_agent_b_remediate.py`, `tests/test_agent_b_held_out.py` — include
  a delete-to-balance false-positive test (B3 must reject) and a single-quarter-overfit
  test (held-out must catch).
- Contract: confirm the conftest write-guard still blocks production writes; verdicts and
  trial wrappers land only under `agent_b/` / `review_queue/verdicts/` / trial dirs.

## 6. Risks / invariants to hold

- **No fake B1 gate.** B1 = schema + routing; correctness is the gold slice. (§9.3
  circularity: agent labels measure "what the agent decided" until the human slice lands.)
- **No-haystack.** Worker prompt must carry coordinates + evidence_cli access, never a
  holdings dump. evidence_cli "roam" is targeted query/paged grid — keep it that way.
- **Per-CIK by default** (Decision 1); global only on >=3-5 unrelated CIKs + full
  regression.
- **Touching A's dispatcher** (3.2) is the one place this plan risks regressing a
  working system; gate that change behind an A smoke run.
- **Cached-only, append-only, ASCII logs, no rebuild/network in the worker** — inherited
  from A's sandbox; the generalized setup must not loosen the write grant beyond
  `review_queue/verdicts/`.
