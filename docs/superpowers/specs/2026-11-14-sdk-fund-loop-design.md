# SDK fund loop: design

Date: 2026-11-14. Status: draft for owner review. Author: Claude (Opus 5.5) with the owner.

## 1. Purpose and scope

Run the existing fund-clearing process (findings-workflow skill, fund-agent brief, independent
review, page sample) as Claude Agent SDK agents driven by a Python state machine, with:

- the same steps, roles and models as the fund loop of D-255 to D-280;
- added safeguards (hooks, worktree per fund, allowed-path checks, main-checkout snapshot);
- loops automated in code (rejection back to the fund agent, resume, budget);
- an orchestrator agent for judgment between stages, limited to a fixed menu;
- a new observation loop: investigate open observations by key across funds and route them to a
  fund agent or a shared-code fix.

Out of scope: OS-level confinement (upgrade path, section 10), merging into the main branch,
batch runs (`run_batch.py` stays on the owner's go), the v0.5 five funds in the first runs.

Owner decisions taken in the design session (2026-11-14):

| Question | Decision |
|---|---|
| How far does the agent go on remediation? | Fix and build in a sandbox, as today |
| Confinement | Hooks + worktree + after-the-fact checks (OS confinement later if needed) |
| Observations | Fund agents close their own; open ones go to a cross-fund investigator by key |
| Automation | Unattended within a budget cap; owner questions asked once at the end |
| Orchestrator | Yes, as an agent choosing from a fixed menu |

Baseline from today's process (decision log D-255 to D-280, 2026-11-11 to 11-14): 1 fund-agent
run per fund for 14 of 18 funds (2 for 4); review rounds median 3 (mean 2.9, range 2-5); sandbox
builds mean 5.3, 10 of 18 runs at the cap of 6; one fund ended with nothing outstanding in the
sandbox, the rest with mechanisms, check repair requests or owner questions.

## 2. Architecture

One driver, `scripts/sdk_loop/run_loop.py`, runs a per-fund state machine. Each role is an SDK
agent with its own system prompt, tools and hooks; no agent loads project settings
(`setting_sources=[]`, so no CLAUDE.md, AGENTS.md, memory or user hooks). Deterministic steps are
plain code between agents, so no agent can satisfy its own check. It extends `scripts/sdk_review/`
(guards, evidence tools, verdict validation) built and measured 2026-11-14.

```
fund queue (largest first, one fund at a time)
  -> fund agent (worktree, sandbox builds, fixes, report, observations)
  -> deterministic checks
  -> orchestrator decision
  -> reviewer (full in round 1, change-only after)
  -> page-sample reader (20 rows)
  -> orchestrator decision
       pass            -> record (decide.py), commit worktree branch, next fund
       reject, round<4 -> return packet to the fund agent, next round
       round 4 / stuck -> park, owner question
after the fund pass:
  open observations by key -> investigator -> investigation review -> orchestrator decision
       not real -> close the observation with evidence
       fund-specific -> task in that fund's next packet
       shared cause -> shared-fix agent -> checks + review + cohort diff -> record or park
end of run: orchestrator drafts owner_questions.md and the run summary
```

| Role | Model | Tools | Writes |
|---|---|---|---|
| Fund agent | Sonnet 5.5 | Read, Grep, Glob, Edit, Write, Bash (hooked), evidence tools | its worktree, its sandboxes, `scratch/fund_runs/<cik>/` |
| Reviewer | Opus 5.5, fresh session per round | read-only + evidence tools | `review.json` in the round folder |
| Page-sample reader | Sonnet 5.5 | read-only + `page_line` | `sample.json` |
| Orchestrator | Opus 5.5 | read-only over the run folder | a decision (structured output) |
| Investigator | Opus 5.5 | read-only + cohort SQL + evidence tools | `investigation.json` |
| Shared-fix agent | Opus 5.5 | as fund agent, shared-code paths allowed | its worktree |

Prompts: the fund agent's prompt is the fund-agent brief and `investigation-review.md`
(`.claude/skills/v05-fund-clearing/`), with the findings-workflow changes (verdicts as decision
entries, fix_record with `expects` and `tested_in`). The reviewer's prompt is the independent
reviewer brief from `investigation-review.md`. The driver passes them as files, so the briefs stay
the single source of truth.

## 3. State, budget and resume

Run folder `scratch/sdk_loop/<run_id>/`:

- `run.json`: settings (funds, quarters, caps, models, git commit at start) and running totals.
- `funds/<cik>/state.json`: stage, round, builds used, sandbox labels, worktree, cost, stop reason.
- `funds/<cik>/round_<n>/`: each agent's output and transcript; nothing is overwritten.
- `observations/<key>/`: investigator and review outputs.
- `ledger.csv`: one line per agent call (role, fund, round, model, tokens, cost, turns, duration,
  exit reason).
- `orchestrator.jsonl`: every orchestrator decision with its reason.
- `owner_questions.md`: questions collected for the end of the run.

Fund stages: `queued -> fund_agent -> checks -> review -> sample -> recorded | returned(round+1) |
parked | failed`. A stage writes its output, then advances the state. A restarted driver resumes
each fund at its recorded stage and never re-runs a finished stage. An agent cut off mid-stage is
restarted in that stage with the files it left and a summary of its previous transcript.

Budget, checked in code before every agent call:

- run cap (first run $40): stop cleanly after the current stage when the remaining budget is below
  the role's expected cost; every fund stays resumable;
- per-agent cap passed as `max_budget_usd`: fund agent $8, reviewer $4, reader $1,
  orchestrator $1, investigator $5 (starting values, revised from the ledger);
- per-fund cap (first run $30): above it the fund is parked with reason "budget";
- expected cost per role is the running mean from the ledger once it has 3 entries.

Preconditions (the driver refuses to start otherwise): no batch, unified rebuild or other fund
build running (the skill's process check); free memory above the fund-build requirement; no
uncommitted changes in the main checkout to files a fund agent may touch.

Failures: an agent that errors twice in one stage marks the fund `failed` with the error; the
driver moves to the next fund.

## 4. Confinement

Worktree per fund attempt: `.claude/worktrees/sdk-<cik last 6>-<run>`, cut from HEAD,
`core.longpaths=true`. `data/raw` is linked read-only; cleanup removes the link before the
worktree. Sandbox builds go to `scratch/fund_sandbox/<label>` as today.

Allowed write paths, set per fund, enforced by the Edit/Write hook and re-checked from the diff:

- `data/overrides/bdc_xbrl_wrappers/<cik>.json` and the fund's highlights wrapper;
- the fund's own lines in `data/overrides/row_corrections*.csv`;
- `data/overrides/agent_investigate_rules/<cik>/`,
  `data/overrides/finding_dispositions_proposed/fund_<cik>.json`, this CIK's entries under
  `data/overrides/verdict_retirements/`;
- the round folder and `scratch/fund_runs/<cik>/`;
- `pipeline/`, `scripts/`, `tests/`, `schemas/` only when the report sets `shared_code: true`.

Bash/PowerShell hook refuses: `python -` and heredoc Python; `python -c` over 200 characters;
`git checkout --`, `reset --hard`, `clean`, `restore`, `stash`, `push`, `merge`, `--no-verify`;
SEC/EDGAR network calls; `run_batch.py`, `rebuild_outputs.py`, `pipeline.main --unified`;
redirects or copies into `data/output/`, `frontend/public/data/`, `data/decisions/`; any build
other than `scripts/v05_evidence/build_fund.sh`. Read is limited to the repository, the run
folder and the CLI's own spilled tool results; credential files are refused.

Hooks read the call before it runs: they stop habits and mistakes, not a determined agent. The
checks in section 5 are the protection.

## 5. Deterministic checks (after each fund-agent round)

Any failure returns the fund with the check output.

1. Worktree diff: every changed or untracked path is allowed; row-correction diffs touch only
   this CIK; `data/decisions/` untouched.
2. Main checkout: `git status` and the mtime/size snapshot of `data/output/`,
   `frontend/public/data/`, `data/decisions/` and `data/overrides/` equal the snapshot taken at the
   start of the round.
3. `python scripts/v05_evidence/fund_gate.py check --label <label> --cik <cik> --report <report>
   --before <before> --snapshot <snapshot>`.
4. Verdict entries: `pipeline.decision_store.validate` and the cached-page quote check
   (`scripts/decide.py page_quote_ok`).
5. Shared code: focused tests, a false-positive test and a real-error-still-fails test pass; the
   report lists the cohort semantic diff.

Recording, after review and sample pass: the driver appends verdicts and the `fix_record` with
`scripts/decide.py append` under the fund agent's actor id, records the reviewer outcome by a
superseding entry (`review_outcome`, `reviewed_by`), and commits the worktree on branch
`sdk-loop/<run>/<cik>`. Nothing is merged automatically; the run summary lists branches to merge
before the next batch.

## 6. Loop 1: rejection

Return packet for round n+1: the reviewer's rejected items quoted (finding id, reason, evidence),
the reader's flagged rows, failed checks with output, orchestrator notes if any, the previous
report and `scratch/fund_runs/<cik>/notes.md`. The fund agent resumes in the same worktree and
sandbox series and answers every returned item: fixed (new build) or contested with new evidence.
Re-reviews are change-only: returned items plus what the diff changed; round-1 approvals carry
forward unless their rows changed.

Stops: pass -> recorded; round 4 fails -> parked, open items to `owner_questions.md`; the same
item rejected twice with the same reason and no new evidence -> parked early.

Limits per round: 6 builds. Rounds per fund: 4.

## 7. Orchestrator

Called after the checks, after review and sample, when an agent stops early, errors or hits a
cap, before an investigation is routed, and at the end of the run. It reads `state.json`, the
latest outputs, the diff summary and the ledger. It returns one decision as structured output:

| Decision | Effect |
|---|---|
| `continue` | proceed as the driver would |
| `return_with_notes` | back to the fund agent with added guidance |
| `dispute_to_reviewer` | send a rejected item back to the reviewer with the counter-evidence, for a ruling |
| `recheck_sample_row` | ask the reviewer to confirm a reader flag suspected to be a misread |
| `park` | stop the fund early, with a reason |
| `ask_owner` | add a question and park the item, not the fund |
| `stop_run` | stop the run (e.g. every fund failing the same check) |

Enforced by the driver: an off-menu decision is rejected and the driver proceeds as `continue`;
the orchestrator cannot accept, close or record anything; it cannot overrule a reviewer, only send
an item back for a ruling; it cannot change checks, thresholds, scope, allowed paths or budgets;
it cannot exceed 4 rounds or 6 builds per round. Expected cost $0.30-0.60 per decision.

## 8. Loop 2: observations

1. Fund agents close their own fund-specific observations inside their run (as today); those are
   part of the fix and reviewed with it.
2. After the fund pass the driver groups open observations (`docs/investigations/v05_observations.csv`
   plus this run's) by `observation_key`, ranked by fund count times fair value.
3. Investigator, one per key, read-only: cohort extent by read-only SQL over the current build;
   page reads at 3 or more funds (all if fewer); `investigation.json` with confirmed or rejected,
   cause (fund-specific, or shared with the code path), affected funds and row counts, quotes.
4. Investigation review by the Opus reviewer before anything acts on it.
5. Routing (orchestrator decision within these options): not real -> close the observation with
   evidence; fund-specific -> a task in that fund's next packet; shared -> shared-fix agent.

Shared-fix agent: own worktree, shared-code paths allowed; focused, false-positive and
real-error-still-fails tests; cohort semantic diff in which every changed fund must be predicted by
the investigation; the same review plus a check that no unpredicted fund moved; `fix_record` with
`expects.ciks` set to the predicted funds (or `"*"` with a reason). An unpredicted fund moving
parks the fix. If the cohort diff needs the unified build (75-90 minutes, memory-bound), the fix is
parked for the next batch instead of built in the loop.

Limits: 3 investigations and 1 shared fix per run at first.

## 9. Testing and first run

Tests without API calls:

- guards: each refused pattern, each allowed ordinary command, a false-positive test per rule;
- allowed paths: a diff touching another fund's row-correction lines fails, this CIK's passes;
- snapshot: a planted write to `data/output/` is caught;
- state machine with stub agents: pass; reject then pass; 4 rejections -> park; same rejection
  twice -> early park; two errors -> failed; budget exhausted -> clean stop; restart resumes at the
  recorded stage without re-running finished stages;
- orchestrator: off-menu decision rejected; `dispute_to_reviewer` cannot close an item; round and
  build limits hold;
- budget: no agent call that would exceed the cap;
- observation routing: each outcome routes correctly; an unpredicted fund moving parks a shared fix.

Dry run: packets, worktrees and prompts for 3 funds, printed, worktrees removed. No API calls.

First paid run: 3 mid-sized funds (15-30 findings, not the v0.5 five), one at a time, run cap $40,
per-fund cap $30, fund loop and orchestrator only (no Loop 2). Measure against the baseline in
section 1: review rounds, builds, findings with an accepted investigation, cost per fund and per
finding, hook refusals, post-hoc check failures, orchestrator decisions and whether each helped.
Read every recorded verdict on the first fund.

Then: run 2 with 5-10 funds if run 1 matches today's quality; Loop 2 starting with the
floor-rate observation (Trinity Capital, 2026-11-14: floating-rate `interest_rate` published as
the printed floor, 89 rows at 2023-12-31), capped at one investigation and no shared fix until its
output has been read.

## 10. Risks and upgrade path

- Less judgment than an orchestrator session: mitigated by the orchestrator agent, the round and
  stuck-loop limits and parking; measured in the first run.
- Hooks are not a security boundary: a script the agent writes can bypass them. The section 5
  checks catch the result. Upgrade if a check ever catches an out-of-bounds write: run the fund
  agent under the Codex sandbox account (`scripts/setup_codex_worker_harness.ps1`), OS-enforced.
- Loop 2 has no track record: its outputs are read in full before they are trusted.
- Passing every check is not data correct; every run summary says so.
- Cost per fund is an estimate ($10-30) until the first run measures it.
- SDK behaviour changes between versions (0.1.48 -> 0.2.182 changed the settings default); the
  driver pins the SDK version and asserts `setting_sources=[]` at start.
