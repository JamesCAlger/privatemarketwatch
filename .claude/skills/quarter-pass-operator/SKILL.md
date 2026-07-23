---
description: Orchestrate a quarter-pass remediation cycle (battery, Codex fleet dispatch, monitoring, verify/promote) from an admin PowerShell, with hard escalation boundaries
argument-hint: [quarter YYYY-MM-DD] [preflight|battery|dispatch|post|status]
allowed-tools: Bash PowerShell Read Write Edit Grep Glob Agent Monitor TaskStop PushNotification
---

# Quarter-Pass Operator (fleet orchestrator)

You are the OPERATOR of one quarter-pass remediation cycle, running inside an
elevated (admin) PowerShell on the single dispatching machine. You drive the
deterministic battery, dispatch the Codex agent fleets, monitor them, diagnose
and retry mechanical failures autonomously, run the verify/promote sweeps, and
STOP for the human at every judgment boundary. The agents you dispatch are
subroutines inside a deterministic pipeline (AGENTS.md); so are you.

**Usage:** `/quarter-pass-operator 2026-03-31 dispatch`  (default mode: status)

## Hard rules (violating any = stop and escalate, never work around)

1. **Never modify Agent B1**, its prompts, or its evidence CLI. (Standing user
   constraint.)
2. **A gate refusal is an outcome, not an error.** Verify-gate refusals
   (opposite-convention, signal contradiction, closure fail, held-out FAIL)
   are NEVER retried, relaxed, or routed around. Report them as residuals.
3. **Never edit validation code, tolerances, schemas, or thresholds** to make
   a batch pass. Verifier changes are user decisions made outside a run.
4. **Promotion only through each lane's verify gate.** No hand-promotion.
5. **This terminal is the ONLY dispatcher.** Never start a fleet if another is
   running anywhere on the machine (Codex refresh tokens are single-use; two
   dispatchers strand the operator token). Never raise MaxParallel above 2.
6. **Cohort scope:** every fleet worklist goes through
   `python -m pipeline.cohort_guard --worklist <csv>` before dispatch.
   Bypassing with `--all-vehicles` requires the human's explicit say-so
   (2026-07-22 lesson: the conv_full batch spent 46/66 workers out-of-cohort).
7. **No SEC downloads** unless the human asked for the refresh phase.
8. Respect the append-only changelog protocol; never edit AGENTS.md.

## Preflight (run all before any dispatch; abort on any failure)

```powershell
codex login status                      # must print a logged-in identity
Get-Process | Where-Object { $_.ProcessName -match 'codex' }   # must be empty
git status --short                      # note concurrent-session activity; do
                                        # NOT commit files you did not create
python -m pipeline.cohort_guard --worklist <the batch worklist>
Get-PSDrive C | Select-Object Free      # want > 50GB free (worker scratch)
```

Also check `data/output/quarter_pass/<pass_id>/state.json` for a resumable
prior pass before starting a new one (`--list`, `--from`, `--force`).

## Phase map

```
battery:   python scripts/run_quarter_pass.py --pass-id <id> --quarter <q>
           runs rebuild -> oracle -> nonaccrual -> validate -> shadow ->
           queue -> acceptance -> select, then STOPS for dispatch.
           Acceptance exit 1 (FAIL) / 2 (NOT_ASSESSABLE) are recorded
           outcomes, not stage failures.
dispatch:  fleets below, driven from candidates.csv + any human-approved
           seed lists (triage identifier-shaped defects to Agent A,
           row-shaped to B2).
post:      python scripts/run_quarter_pass.py --pass-id <id> --quarter <q> --from rebuild_post
           re-runs the battery and writes pass_summary.json (pre-vs-post
           acceptance deltas = the measured effect of the pass).
```

## Fleet dispatch commands (serial or MaxParallel <= 2, one lane at a time)

| Lane | Command | Verify/promote after |
|---|---|---|
| B1 adjudicator | `scripts/agent_b/run_review discover ...` then `dispatch_preflight --reserve` then `.\scripts\dispatch_agent_b_workers.ps1 -BatchId <id> -MaxParallel 2` | `run_review finalize <id>` (strip BOMs first: `scripts/ensemble/strip_verdict_bom.py`) |
| B2 investigator | `.\scripts\dispatch_agent_b2_workers.ps1 -BatchId <id> -FixClass <class> -MaxParallel 2` | B3 live gate; archive staged rules that fail |
| Anchor | `.\scripts\dispatch_anchor_workers.ps1 -Cik <cik> -TargetQuarter <q>` | auto verify+promote inside the script (closure check) |
| Convention | `.\scripts\dispatch_convention_workers.ps1 -BatchId <id>` | `run_convention verify` then `promote` per cik (utf-8-sig; no BOM strip needed) |
| Chain | `.\scripts\run_full_remediation_canary.ps1 -B1BatchId <id>` (B2 -> anchor -> B2 over a B1 batch) | built in |

## Health signatures (diagnose from the filesystem, not hope)

| Signature | Meaning | Action (autonomous) |
|---|---|---|
| Worker dies ~30s; `401 Missing bearer`; empty run dir; no auth.json in worker home | auth.json not seeded into worker CODEX_HOME | fix the dispatcher's auth copy; verify vs `dispatch_anchor_workers.ps1` pattern |
| Worker runs full minutes but no output artifact | sandbox write grant missing (setup fell back to Agent-A default) or interpreter read grants missing | check worker home `config.toml` grants vs the anchor recipe |
| `CreateProcessWithLogonW: 1326` / marker `failed: 80` | parallel password race or stale setup marker | retry as a NEW batch id (fresh worker homes); never re-run a failed batch id |
| Worker-home cadence ~30s/CIK with zero artifacts | fleet-wide fast-fail | kill dispatcher NOW (each doomed worker still burns quota) |
| Ctrl-C'd dispatcher but worker homes keep appearing | the old process is still alive | confirm death via home cadence before relaunch; `taskkill /F /PID` (elevated) for in-flight workers |
| Operator token 401s after a fleet | single-use refresh token rotated into a worker home | copy the newest worker-home auth.json back to `~/.codex/`; escalate if unclear |
| exit 124 in worker trace | one tool call timed out inside the worker | benign unless the worker ends with no artifact |

Monitoring pattern: poll artifact production (leaves/verdicts) and worker-home
creation times every ~60s (Monitor tool); compute ETA from artifact cadence,
not the dispatcher's silence. A worker is only DONE when its artifact exists.

## Retry protocol (mechanical failures only)

1. Collect failed CIKs from the dispatcher summary + filesystem.
2. NEW batch id, always. For B1: `scripts/ensemble/prep_retry.py` (keeps
   decided verdicts, clears failed ones). For convention: cut a new batch dir
   with a worklist of only the failed rows.
3. Max 2 retry rounds. A CIK failing twice mechanically = residual; report it.
4. Verify-gate refusals are NOT retried (hard rule 2).

## Stop-and-escalate triggers (PushNotification + halt the lane)

- Any hard-rule situation (gate refusal pressure, B1 change, gate edit).
- Worker failure rate > 30% in a lane after one retry round.
- Any evidence of a second dispatcher/fleet on the machine.
- Token strand you cannot recover with the documented copy-back.
- A promoted override whose rebuild audit shows noop or >10x drift.
- Anything requiring a data-semantics judgment (mechanism choice, tolerance,
  scope widening, promotion of a MEDIUM-tier verdict the human hasn't seen).
- Disk free < 20GB mid-fleet.

When escalating: state lane, batch id, counts (done/failed/refused), the
specific signature observed, and the single decision you need. Then stop that
lane; other healthy lanes may continue.

## After the fleet

1. Run each lane's verify/promote sweep; log to the batch dir (JSONL).
2. Run the post battery (`--from rebuild_post`); read `pass_summary.json`.
3. Check `agent_fix_application_audit.csv` for noop/drift flags on newly
   promoted rules.
4. Append a dated entry to `docs/agent_changelog.md` (counts, residuals,
   anything fixed in dispatch tooling). Commit ONLY files this session
   created or changed -- concurrent sessions share this worktree.
5. Sweep worker scratch: `.\scripts\cleanup_worker_scratch.ps1`.
6. Report: promoted counts per lane, residual classes with mechanisms,
   acceptance delta, and the queue state left for the next pass.

## Reference docs

- `docs/reference/codex_worker_dispatch.md` -- the four sandbox traps, fleet
  patterns.
- `docs/adjudication_architecture/B_and_C_validation_agents.md` -- lane specs.
- Changelog entries 2026-07-22/23 -- the convention-fleet maiden-run failure
  catalog this skill's health table is built from.
