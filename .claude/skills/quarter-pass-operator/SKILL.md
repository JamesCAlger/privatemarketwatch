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

## Preflight (machine-checked since 2026-08-21)

The pass's FIRST STAGE is the machine-checked readiness gate -- probe it
standalone before committing to a pass:

```powershell
python -m scripts.run_quarter_pass --pass-id <id> --quarter <q> --until preflight
# or directly: python -m scripts.pass_preflight --quarter <q> [--strict]
```

It hard-fails on: uncovered fix classes in the actionable pool (the 121/143
lesson), anchor assessability below min (prints the lagging CIKs + the exact
`refresh_companyfacts` remedy), live-rule noop/drift, codex processes running.
It warns on: stale staged leaves/proposals, a non-empty re-adjudication
worklist, other python processes. Exit 1 = enumerated readiness list in
`preflight.log`. The two things the machine CANNOT see -- still check by hand:

```powershell
codex login status                      # must print a logged-in identity
Get-PSDrive C | Select-Object Free      # want > 50GB free (worker scratch)
git status --short                      # note concurrent-session activity; do
                                        # NOT commit files you did not create
python -m pipeline.cohort_guard --worklist <the batch worklist>
```

If anchor assessability fails, the ONLY networked step (operator-run, never
called by the pass): `python -m scripts.refresh_companyfacts --quarter <q>
--ciks <lagging list>` (archives stale cache files to `_archive/`, re-fetches
through the 10 req/s EdgarClient, reports which CIKs still lag SEC).

Also check `data/output/quarter_pass/<pass_id>/state.json` for a resumable
prior pass before starting a new one (`--list`, `--from`, `--force`).

## Phase map

```
battery:   python scripts/run_quarter_pass.py --pass-id <id> --quarter <q>
           runs preflight -> pin_inputs -> rebuild -> oracle -> nonaccrual ->
           validate -> shadow -> queue -> ledger -> acceptance -> select,
           then STOPS for dispatch. Acceptance exit 1 (FAIL) /
           2 (NOT_ASSESSABLE) are recorded outcomes, not stage failures.
dispatch:  fleets below, driven from candidates.csv + any human-approved
           seed lists (triage identifier-shaped defects to Agent A,
           row-shaped to B2). Dispatch manifests are wave-stamped
           (manifest.NNN.json per wave; manifest.json = latest pointer).
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

B1 `discover` builds bundles for every selected engine: generic engines via
`pipeline.review_bundles`, and `source_recon` rows via the richer
`pipeline.bdc_cik_review` generator (routed automatically since 2026-08-29;
before that, a source_recon-only discover wrote a worklist with dead
bundle_paths and wiped the shared bundle manifest). Before `dispatch_preflight`,
spot-check that the worklist's `bundle_path`s exist -- a worklist row without
its bundle file means the build step failed, not that the packet is resolved.

## Investigation-loop escalation semantics (live since 2026-09-02)

The B2-investigator/chain loop (`scripts/agent_investigate/run_investigation.py`)
is escalation-aware. Two statuses change operator behavior:

- **`prep` returns `status: blocked_no_bundle`** -- no cached filing bundle for
  the target. This is SKIP-AND-QUEUE, not a dispatch error: record the packet
  on the bundle-build queue and move to the next one. Do not retry, do not
  count it toward the lane's failure rate. `--allow-missing-bundle` overrides
  only with the human's explicit say-so (a bundle-less worker can only refuse).
- **Loop stops with reason `worker escalated ... honest stop`** -- once a
  worker files an escalation, the loop terminates at the next decision point
  (iteration >= 2) instead of burning the remaining iterations. This is a
  TERMINAL OUTCOME, same standing as a gate refusal (hard rule 2): never
  re-dispatch iterations to "finish" the packet. The escalation is the
  deliverable; it gets routed at close-out (After the fleet, escalations step).

Why this exists: pre-fix, workers refused honestly early then fabricated
gate-passing corrections under iteration pressure (1905824 duplicate row_add,
2008748 subtotals-as-positions -- both operator-vetoed), and 1743415 burned
all 5 iterations on an unanchorable target.

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
5. `blocked_no_bundle` prep statuses and escalation-stops are outcomes, not
   mechanical failures -- excluded from retry rounds and failure-rate counts.

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
   Promotion refuses to overwrite a LIVE leaf without `--allow-overwrite`
   (status `refused_overwrite` in the promote records) -- a sanctioned
   re-author means the operator pulled the old leaf to a
   `_pulled_<reason>_<date>/` dir (with a README naming rule_id + reason)
   first, or passes the flag deliberately.
2. **Fleet acceptance (B2 lanes):**
   `python -m scripts.fleet_acceptance --batch-id <id>` -- evaluates the
   pre-declared criteria (validity >= 95%, selector noops = 0, equivalence/
   off-scope fails = 0, no post-promotion discoveries, no new failure classes,
   defect-signature rate <= 10%) and writes
   `data/output/agent_b2/fleet_acceptance_<id>.json`. ADVISORY while the
   thresholds file's `enforce.*` flags are off: read the artifact, record the
   verdict in the batch dir. A FAIL means stop, diagnose, re-fleet -- never
   widen a bar (hard rule 3 applies to these thresholds too).
3. **Mandatory post-promotion audit (before the post battery):**
   `python -m scripts.agent_b2.replay_gate --corrections-dir
   data/overrides/agent_b2_corrections --stats-only --out
   data/output/agent_b2/replay_live_stats_<id>.json` -- the live-store
   magnitude sweep that caught the 5 FV-invariant corrupting corrections.
   Every out-of-band leg needs evidence, a pull, or a watchlist entry.
4. **Re-adjudication worklist:** if
   `data/output/agent_b2/readjudication_worklist.csv` is non-empty
   (wrong-diagnosis gate refusals), dispatch a B1 re-adjudication batch from
   it (NEW batch id) before any further B2 fleet on those findings. Never
   delete or edit B1 verdict files.
5. **Route accumulated escalations (before the post battery):**
   `python -m scripts.agent_investigate.run_investigation escalations` --
   scans `data/output/agent_investigate/<cik>/escalations/`, dedupes per
   (target_quarter, category), writes
   `data/output/agent_investigate/routing/escalation_routing.csv` with routes
   anchor_lane / extraction_review / human_review. anchor_lane rows seed the
   next anchor-fleet worklist; extraction_review rows are extraction-defect
   candidates for a B2/staging plan; human_review rows go into the close-out
   report verbatim. Routing reads escalation files, never consumes them --
   do not delete them after routing.
6. Run the post battery (`--from rebuild_post`); read `pass_summary.json`.
7. Check `agent_fix_application_audit.csv` for noop/drift flags on newly
   promoted rules.
8. Append a dated entry to `docs/agent_changelog.md` (counts, residuals,
   anything fixed in dispatch tooling). Commit ONLY files this session
   created or changed -- concurrent sessions share this worktree.
9. Sweep worker scratch: `.\scripts\cleanup_worker_scratch.ps1`.
10. Report: promoted counts per lane, fleet-acceptance verdicts, residual
    classes with mechanisms, acceptance delta, and the queue state left for
    the next pass.

## Quarter sign-off + re-attestation (owner decision 2026-08-30)

The codebase deliberately evolves; a semantics change can retroactively flip a
signed-off quarter's acceptance (observed: retain-and-flag regressed 1633336's
signed Q4-2025 until the is_subsidiary false-positive fix). We freeze the
ATTESTATION, not the code:

- AT SIGN-OFF (after the human accepts a quarter's PASS):
    python -m scripts.reattest_quarters attest --quarter <q>         --source data/output/quarter_pass/<pass_id>/acceptance_post.json
    git tag signoff-<q> <signoff-commit>
- AFTER any validation-semantics change, AND in the preflight window of every
  new pass:
    python -m scripts.reattest_quarters check
  Exit 1 = a signed-off quarter REGRESSED under current code. That is a
  stop-and-report event: append the ledger row's attribution to the changelog
  and surface it to the human BEFORE dispatching the pass. Never re-attest
  over a regression without the human's explicit sign-off; improvements
  (FAIL->PASS flips) are recorded but need no escalation.
- Ledger: data/output/acceptance_reattestation_ledger.csv (append-only).
  Stored attestations: data/reference/acceptance_attestations/<q>.json.

## Reference docs

- `docs/reference/codex_worker_dispatch.md` -- the four sandbox traps, fleet
  patterns.
- `docs/adjudication_architecture/B_and_C_validation_agents.md` -- lane specs.
- Changelog entries 2026-07-22/23 -- the convention-fleet maiden-run failure
  catalog this skill's health table is built from.
