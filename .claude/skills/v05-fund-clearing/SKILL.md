---
name: v05-fund-clearing
description: Use when asked to process, clear, work through or sign off outstanding ledger items or findings (one fund, the v0.5 funds or the whole v1 cohort), to re-run or refresh the ledger to see what remains, to run the fund-by-fund clearing loop over several funds unattended, to take a new quarter into funds already cleared, or to fold cleared sandboxes back into production
metadata:
  argument-hint: <cik> [<cik> ...] | next <n>
allowed-tools: Bash PowerShell Read Write Edit Grep Glob Agent SendMessage Monitor TaskStop
---

# v0.5 fund clearing (orchestrator)

You are the ORCHESTRATOR. One subagent owns one fund end to end (read, fix, build, propose). You
do not read filings or fix data yourself. You hand over the fund, run the mechanical gate on what
comes back, send failures back to the same agent, record the result, and move to the next fund.

**The unit of work is the fund, across all its quarters.** Causes sit at fund level (a wrapper
setting, a column, a member format); work pinned to one quarter does not carry forward.

## Hard rules (a violation stops the run; never work around one)

1. **One fund agent at a time, and nothing else writing in this working tree.** Builds, shared
   files and shared code are not safe in parallel. If `git log` or `git status` shows another
   session's work appearing during a run, stop and report.
2. **The gate decides.** `scripts/v05_evidence/fund_gate.py check` PASS, INCOMPLETE, INVESTIGATION_INCOMPLETE, FAIL or
   NEEDS_ORCHESTRATOR. Never
   edit the gate, a rule, a threshold, a check or the reasons list to change a verdict.
3. **Nobody in the loop accepts a new reason.** A disposition is accepted only by a check listed
   in `data/reference/accepted_disposition_reasons.json` (through `make_batch_dispositions.py`)
   or by the owner. Everything else is a proposal and stays outstanding.
4. Never: push, publish, download, build more than the funds in hand, write `data/output/` or
   `frontend/public/data/`, edit `AGENTS.md`, `git stash`.
5. Commit locally after each fund that passes (owner instruction 2026-10-13: unattended runs
   allowed). Stage only the files the gate lists as changed, plus the fund's report.
6. A zero is not "data correct". Say so in every report.

## Step 0 of every run: what is outstanding (owner 2026-11-10)

"Process outstanding ledger items" starts here, never from a remembered count.

1. `python scripts/v05_evidence/outstanding_status.py --refresh [--skip <labels a build is using>]`
   (ledger stage only, about 10 s per sandbox, ~10 min for the cohort). Read
   `docs/investigations/v05_readings/outstanding_status.md`. Quote counts only from it, with its
   timestamp. It says what a refresh does NOT cover: rules added and extraction fixes since a
   sandbox's build need a fund build (`build_fund.sh`); production is a different build (column
   "Production", from the latest quarter-pass ledger).
2. "Sandbox used" differs from "Accepted sandbox": registry drift. `BEFORE` stays the accepted
   sandbox; note the newer build in the decision-log entry.
3. Scope of agent review (owner 2026-11-10): only findings in category `unreviewed` or
   `investigated`, plus finding ids a rebuild newly produces. Reviewed findings (proposal, verdict,
   review_supported, narrative) carry their earlier investigation forward unchanged with
   `"carried_from": "<file>"`; one whose flagged rows differ from the carried `affected_rows` is
   back in scope. Fixing errors earlier reviews confirmed stays in scope. Put this paragraph in
   every fund-agent and reviewer prompt.
4. The registry (`accepted_sandboxes.json`) is the record of each fund's current state. Update it
   whenever a fund is accepted (step 9), and also when a regression rebuild or a merge produces a
   newer gated build of an accepted fund. A fund-loop branch merged without registering its
   sandbox is drift (Apollo `apx5`, Sixth Street `ssq0`, 2026-11-10).

Outstanding is the gate's definition (`pipeline.quarter_acceptance.RESOLVED_FINDING_STATES`):
`verdict_retired` is closed, `real_error_check_silent` is open.

## Per fund

```dot
digraph fund {
  snapshot -> dispatch -> gate;
  gate -> page_sample [label="PASS / INCOMPLETE"];
  gate -> send_back [label="INVESTIGATION_INCOMPLETE: finish evidence/review"];
  page_sample -> independent_review [label="sample complete; report final"];
  independent_review -> final_gate;
  final_gate -> record [label="PASS / investigated INCOMPLETE"];
  final_gate -> send_back [label="investigation incomplete or FAIL"];
  page_sample -> send_back [label="published errors, round < 3"];
  gate -> send_back [label="FAIL, round < 3"];
  send_back -> gate;
  gate -> park [label="FAIL, round 3"];
  record -> regression [label="shared code changed"];
  regression -> commit [label="no undeclared change"];
  regression -> park [label="other funds moved"];
  record -> commit [label="no shared code"];
}
```

1. **Preflight.** No Python process running; `git status` read; last accepted sandbox for the
   fund found (`python scripts/v05_evidence/fund_ledger_latest.py <cik>`) and used as `BEFORE`.
   `ADD_QUARTER` is `2026-06-30` only for funds whose filings for it are on disk
   (`data/raw/filings/quarter_downloads/2026-06-30.csv`).
2. **Snapshot.** `python scripts/v05_evidence/fund_gate.py snapshot --out scratch/fund_runs/<cik>.snapshot.json`
3. **Dispatch** one general-purpose subagent. Its prompt is the whole of `fund-agent-brief.md`
   in this folder plus: `CIK`, `LABEL_PREFIX`, `BEFORE`, `ADD_QUARTER`,
   `REPORT = docs/investigations/v05_readings/reports/<cik10>.json`. Give it nothing else: no
   hypothesis about what is wrong. Include the investigation contract in
   `investigation-review.md`; give the investigator its actual agent identity.
4. **Gate** when it returns:
   `python scripts/v05_evidence/fund_gate.py check --label <label from report> --cik <cik> --report <REPORT> --before <BEFORE> --snapshot <snapshot> --review <independent-review.json>`
   Before final acceptance, dispatch a separate investigator-reviewer while the fund agent is idle,
   using `investigation-review.md`. It reviews EVERY outstanding finding and observation, not a
   sample. The random page sample remains a separate check. The initial mechanical check may run
   without a review; it cannot grant acceptance. After the page sample or any report/ledger edit,
   obtain a fresh review bound to the final report and ledger.
   **INVESTIGATION_INCOMPLETE (exit 4):** send missing coverage and rejected conclusions back to
   the same fund agent. Do not register the sandbox as accepted or start the next fund. A build cap
   limits repairs, not reading. If cached evidence cannot complete the investigation, save the exact
   unchecked rows, evidence needed and next action; report the blocked investigation to the owner.
   Do not run `park` merely because investigation is incomplete; preserve the resumable work.
5. **FAIL:** send the gate's printed failures, verbatim, to the same agent (SendMessage, so it
   keeps its context). At most three gate rounds. Then
   `fund_gate.py park --snapshot <snapshot> --cik <cik>` and record the fund as parked with the
   last verdict. If `park` prints STOP, stop the whole run and report.
6. **NEEDS_ORCHESTRATOR:** the agent asks for a change it may not make (a check, the re-verifier,
   a rule). Read its evidence. A change to how a published value is VERIFIED (the re-verifier
   reading a new event) you make yourself, with a test, then re-snapshot, have the agent rebuild
   and gate again. A change to what counts as a FINDING or as ACCEPTED is the owner's: record
   the request and leave the finding outstanding. Continue independent investigation on this fund;
   do not interpret this as permission to accept it or advance while NEEDS_ORCHESTRATOR persists.
   Keep unanswered requests active. When a request is implemented, rejected or explicitly deferred
   by the owner, preserve it with the response, authority and evidence in `request_resolution_history`,
   remove it from active `orchestrator_requests`, and obtain a fresh independent review and gate.
   The resolution history is part of the hashed report and the reviewer must examine it. Never
   remove a request just to change the verdict. List all requests and responses in the end-of-run report.
7. **PASS or INCOMPLETE with shared code changed** (the report says so, or the gate lists it):
   run the changed modules' tests now. If the change altered an EXISTING wrapper setting, find
   the other funds that use it (search `data/overrides/bdc_xbrl_wrappers/` for the key), rebuild
   them and run `regression_check.py`; a fund that MOVED without an explanation in the report
   parks this fund. A NEW setting is on for one fund: nothing else is rebuilt until the end of
   the run.
7b. **Page sample** (after mechanical checks pass, even if independent review is pending; the net for what no rule looks at). The ledger rules and
   the gate miss whole fields: the 2026-10-14 sample found issuer names wrong on 75 pct of one
   fund's rows with every finding cleared. With `S = docs/investigations/v05_readings/samples/<cik10>`:
   `python scripts/v05_evidence/field_sample.py --dir <S> draw --per-fund 20 --label <label> --cik <cik>`,
   then `... --dir <S> cards --batch 20`. Dispatch ONE reader subagent, never the fund agent (it
   would be marking its own work), while the fund agent is idle. Its prompt: read
   `docs/investigations/v05_field_sample/reader_brief.md`, label `<S>/cards/batch_01.md`, write
   `<S>/labels/batch_01.json`, run `field_sample.py --dir <S> check` on it. Then
   `field_sample.py --dir <S> score` and read the "Published errors" table in `<S>/results.md`.
   - None: go on.
   - Any published error with cause `tag` or `pipeline`: send the table, verbatim, to the fund
     agent (SendMessage). It fixes the cause at fund level or lists it as an observation with a
     reason it is left, rebuilds, and the fund is gated again. This counts as a gate round.
   - The same field wrong on two or more cards is a fund-level cause: fixed, or the fund is
     recorded INCOMPLETE with it named.
   Record the sample (cards, published errors, fields) in the decision-log entry. Twenty cards
   can miss a problem on under about 15 pct of rows; say so, never "the sample was clean, so the
   data is correct".
8. **Observations:** `python scripts/v05_evidence/observations.py add <REPORT>` (the gate has
   verified their printed lines). An observation whose cause is `shared` goes in the end-of-run
   report by name.
9. **Record:** set the fund's entry in `docs/investigations/v05_readings/accepted_sandboxes.json`
   to the sandbox that passed; append one entry to `docs/investigations/v05_decision_log.md` (next D-number: what
   was fixed, what is proposed, what is parked, gate verdict, sandbox label) and one line to the
   run table in `docs/investigations/v05_reading_backlog.md`. Commit.
10. Next fund.

**INCOMPLETE** means the build is clean and investigation independently supported, but some findings
remain unfixed without a disposition proposal. It can be recorded with explicit mechanisms and next
actions. **INVESTIGATION_INCOMPLETE** means coverage, evidence or independent review is missing;
it cannot use this acceptance route. Never classify an unfinished read as an owner decision.

Every observation needs a detection decision: propose a detector, reference an existing detector or
proposal, or explain why reliable detection is not feasible. Collect these in the end-of-run report.
Every verifier request must distinguish a verification bug from an acceptance-standard change and
carry evidence plus a next action. Repair verification bugs with independent source evidence and tests;
new detection/acceptance rules still require the owner's decision. Never verify a derived value against itself.

## Order and scope

Largest first by 2026-03-31 published fair value: `python scripts/v05_evidence/cohort_by_size.py`.
`next <n>` means the next n funds in that order whose last gate verdict is not PASS.
A new quarter for a cleared fund is the same loop with `ADD_QUARTER`: record the first, untouched
reading (findings cleared by carry-forward against findings newly open) before any fix.

## End of run

1. **Regression, only if shared code changed during the run.** Rebuild the funds accepted before
   the run in sandboxes of at most ten (`build_fund.sh`, with `--add-quarter` where they have it)
   and run `python scripts/v05_evidence/regression_check.py <label>`. A fund that MOVED: find the
   commit that did it (one commit per fund), report it, and do not call the run clean.
2. **Observations.** `python scripts/v05_evidence/observations.py show --open`. One seen on several
   funds is a candidate rule; one caused by shared code reaches funds nobody has read. Report
   both kinds; propose rules, do not add them.
3. **Owner decision ledger.** `python scripts/v05_evidence/owner_queue.py build`. The owner rules
   per reason: `owner_queue.py rule <reason key> accept|reject|more --words "<their words>"`.
   Only that command turns a proposal into an accepted disposition.

4. **Fold back into production (owner's go each time; about 6 hours, ~14 GB free).** Launch
   detached: `Start-Process powershell -ArgumentList '-File','scripts\v05_evidence\foldback_chain.ps1','-Tag','<tag>','-Quarters','2026-06-30,2026-03-31' -WindowStyle Hidden`.
   No fund build, pytest or edit in this checkout while it runs. It re-extracts the cohort, rebuilds
   the chain, runs the quarter passes, then `sandbox_parity.py --prod-ledger ...`: production rows
   and FV against each registered sandbox, and finding ids outstanding in production but not in the
   sandbox ledger (`NEW_OUTSTANDING_IN_PRODUCTION`, `ledger_diff.csv`). Equal counts are not enough;
   read every new id before calling it a regression (production computes entity ids and industry
   labels on all funds). A quarter a sandbox lacks is unchecked, not passing. Ends with
   `outstanding_status.py`. Never publish or push from it.

One report to the owner:

| Fund | Verdict | Findings | Outstanding | With a proposal | Quarters tying | Fixed | Parked |
|---|---|---|---|---|---|---|---|

Then: proposals grouped BY REASON across funds, one question per reason, unrelated one-offs kept
apart; errors the agents saw that no rule flagged; shared-code changes and what the regression
build showed; what was not run. Lead with what failed.

## Quick reference

| Need | Command |
|---|---|
| What is outstanding (start here) | `python scripts/v05_evidence/outstanding_status.py --refresh` -> `docs/investigations/v05_readings/outstanding_status.md` |
| Fold back into production | `scripts/v05_evidence/foldback_chain.ps1 -Tag <t> -Quarters <q,...>` (detached, owner's go) |
| Production vs sandboxes | `python scripts/v05_evidence/sandbox_parity.py --quarters <q ...> --prod-ledger <ledger.csv>` |
| Fund order | `python scripts/v05_evidence/cohort_by_size.py` |
| Latest ledger of a fund | `python scripts/v05_evidence/fund_ledger_latest.py <cik> --rules` |
| Build | `bash scripts/v05_evidence/build_fund.sh <label> [--add-quarter D] <cik>` |
| Reasons accepted by check | `data/reference/accepted_disposition_reasons.json` |
| Gate | `python scripts/v05_evidence/fund_gate.py check ...` (verdict in `scratch/fund_sandbox/<label>/gate_<cik>.json`) |
| Field comparison | `python scripts/v05_evidence/holdings_field_diff.py <new> <old>` |
| Have accepted funds moved | `python scripts/v05_evidence/regression_check.py <label>` |
| What agents saw that no rule reported | `python scripts/v05_evidence/observations.py add <report> | show [--open]` |
| Page sample of one fund | `python scripts/v05_evidence/field_sample.py --dir <S> draw --label <l> --cik <c> | cards | check <labels> | score` |
| Owner decisions | `python scripts/v05_evidence/owner_queue.py build | show [key] | rule ...` |
| Take a failed fund out | `python scripts/v05_evidence/fund_gate.py park --snapshot <file> --cik <cik>` |

## Red flags: stop and report

- You are about to read a filing or edit a wrapper yourself: that is the fund agent's work.
- "The gate is too strict here": report the case to the owner; do not loosen it.
- A fund "passes" with a total exception or a proposal you would not want to defend to the owner.
- Two builds or two fund agents at once.
- A count quoted without rebuilding: another session may have committed since. Check `git log`.
