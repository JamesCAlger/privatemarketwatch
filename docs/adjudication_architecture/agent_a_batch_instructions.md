# Agent A Batch Induction Instructions (Codex operator runbook)

Operator runbook for running the quarter-by-quarter Agent A identifier-grammar induction
as a sandboxed Codex batch. Adapted from `docs/fail_verification/codex_batch_instructions.md`
(the existing precedent in this repo). The agent-facing contract is
`docs/adjudication_architecture/A2_sandbox_task_contract.md`.

Three layers:
- **Layer 1 (deterministic, in-repo):** `scripts/agent_a/run_quarter.py` -- builds the
  worklist + bundles (discover) and runs the A3 held-out gate (gate). No LLM.
- **Layer 2 (this runbook):** run the deterministic dispatcher, which launches one
  sandboxed Codex worker per worklist bundle after a whole-batch preflight.
- **Layer 3 (scheduler, external):** whatever fires Layer 1 each quarter (Makefile / CI cron).

## Hard Rules (enforce in the sandbox, not just the prompt)

- Cached local files only. No SEC EDGAR, no external network.
- Do NOT edit pipeline code, schemas, docs, frontend, or generated CSVs.
- Each worker may write ONLY its two staged proposal files:
  - `data/output/agent_a/proposals/<CIK>.anchors.json`
  - `data/output/agent_a/proposals/<CIK>.grammar.json`
- No temp scripts, sidecar notes, or patched data.
- The agent proposes config only. It NEVER writes production holdings fields. Value
  corrections are authored by Agent B from the ledger flags, not by A.
- Plausible sample parses are not success. The deterministic A3 gate (Layer 1 `gate`) decides.

## Setup (Layer 1 -- run from repo root, before launching agents)

```bash
# (refresh the signature report if stale -- it drives discovery)
python -m pipeline.identifier_signature

# build the worklist + one bounded bundle per filer needing induction this quarter
python -m scripts.agent_a.run_quarter discover 2025-12-31
```

Outputs:
- Worklist: `data/output/agent_a/quarter/<quarter>/worklist.csv`
- Bundles:  `data/output/agent_a/quarter/<quarter>/bundles/<CIK>_<quarter>.json`

`reason` in the worklist is `uninduced` (no grammar yet) or `drift_candidate` (grammar
exists but coverage degraded). NOTE: discovery reads the GLOBAL-anchor signature report, so
a filer that already has per-CIK anchors can show a stale `drift_candidate`; the gate is the
authoritative backstop (PASS => actually covered, ignore the stale flag).

## Agent Assignment (Layer 2)

Launch workers from rows in `worklist.csv`, NOT by scanning the bundle directory. The
dispatcher validates all selected rows, refuses stale proposal files, claims all selected
CIKs before launch, and releases those claims after completion:

```bash
powershell -ExecutionPolicy Bypass -File scripts/dispatch_agent_a_workers.ps1 \
  -Quarter 2025-12-31 \
  -MaxParallel 2
```

Dispatcher outputs land under:

```
data/output/agent_a/quarter/<quarter>/dispatch/<batch_id>/
```

The current Windows worker harness still grants repo-root read access as a ceiling for
evidence tooling. Treat this as staged behavioral isolation, not full OS-level read denial.
Writes are limited to staged proposal files.

The agent's only source window is the shared evidence CLI (identical to Agent B):

```bash
python scripts/review_agent/evidence_cli.py --bundle <bundle> tables
python scripts/review_agent/evidence_cli.py --bundle <bundle> grid --table N
python scripts/review_agent/evidence_cli.py --bundle <bundle> roam --query "Asset Type,PIK"
python scripts/review_agent/evidence_cli.py --bundle <bundle> totals
```

## Gate + promote (Layer 1 -- after workers finish)

```bash
python -m scripts.agent_a.run_quarter finalize 2025-12-31 --staged --manifest <dispatch-manifest.json>
python -m scripts.agent_a.run_quarter gate 2025-12-31 --staged --manifest <dispatch-manifest.json>
```

Outputs `data/output/agent_a/quarter/<quarter>/staged_gate_results.csv` with one verdict per filer:
- `PASS`      -- held-out gate green (>=2 quarters, per-quarter completeness >=90% and
                 gating-invariant >=85%, none-share stable). Promotion-eligible.
- `FAIL`      -- a quarter regressed / overfit. Route to human; do NOT promote.
- `NO_CONFIG` -- the agent produced no grammar for that filer (skipped / failed).

A FAIL means the proposed config is unsafe; route to human and do not promote. PASS proposals
can be copied to durable production overrides explicitly:

```bash
python -m scripts.agent_a.run_quarter promote 2025-12-31
```

Promotion copies only PASS staged proposals to `data/overrides/identifier_anchors/` and
`data/overrides/identifier_rate_grammars/`. Review the diff before merge.

## Re-emit ledger flags (feeds Agent B)

After promotion, refresh A's enrichment flags so B sees the new filers:

```bash
python scripts/shadow_agent_a_engine.py
# (flags land in the production ledger on the next shadow_validation_runner run)
```

## Layer 3 -- scheduling (external; pick one)

- **Manual / Makefile:** `make agent-a-quarter Q=2026-03-31` wrapping discover -> (batch) -> gate.
- **CI cron (recommended):** a scheduled GitHub Action runs discover + gate and opens a PR
  with the proposed configs + `gate_results.csv`. Config changes stay human-reviewed.
- **Repo `/schedule`:** a cloud cron agent, if you want it inside Claude Code.

Start manual on one filer, confirm the gate passes, then wrap in CI. Never auto-merge config.
