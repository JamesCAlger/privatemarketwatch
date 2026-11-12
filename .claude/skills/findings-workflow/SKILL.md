---
name: findings-workflow
description: Use when asked to process, clear, work through or sign off outstanding ledger items or findings, to say what is outstanding or what needs review or a fix, to record a ruling, verdict, fix or check-repair request, to run or read a batch build, or to take a new quarter into the funds. Replaces v05-fund-clearing and quarter-pass-operator.
---

# Findings workflow (one status, one store, one batch)

You are the ORCHESTRATOR. Production is the only build of record. A finding's status comes from
one place and changes in one way.

| Thing | Where | Rule |
|---|---|---|
| What is outstanding | `python scripts/status.py` -> `docs/investigations/findings_status.md` | Quote counts only from it, with its batch id |
| Decisions | `data/decisions/` through `python scripts/decide.py append <file> --actor <who>` | Append-only; never edit a line; supersede |
| The ledger | `data/output/batches/<batch_id>/findings_ledger.csv`, current = `batches/latest.json` | Only `scripts/run_batch.py` writes one |
| Fund sandboxes | `scratch/fund_sandbox/<label>` | Scratch for testing a fix. No status, nothing quotable |

## First check: is there a batch?

If `data/output/batches/latest.json` does not exist, no production batch has run under this
workflow and `scripts/status.py` will stop with "no batch yet". Do not improvise: say so, and use
the `v05-fund-clearing` skill (status from `scripts/v05_evidence/outstanding_status.py`) until the
owner has had the first batch run. Decisions can still be recorded with `scripts/decide.py`.

## The six statuses (`pipeline/finding_status.py`)

| Status | Who acts | What they do |
|---|---|---|
| Needs agent review | fund agent | read the filing, record a `verdict` (conclusion + evidence) |
| Needs data fix | fund agent | fix the cause at fund level, test in a sandbox, record a `fix_record` |
| Needs check repair | orchestrator, after the owner approves | repair the check in a worktree, measure, record a `fix_record` |
| Needs owner ruling | owner | rule; the orchestrator records the `owner_ruling` in the owner's words |
| Fix awaiting build | nobody until the next batch | - |
| Closed | - | - |

The detailed lifecycle states stay in the ledger's `state` column. Do not quote them as status.

## Hard rules (a violation stops the run)

1. Nothing but a batch changes whether a finding is fixed. A sandbox that looks clean proves the
   fix is worth queuing, nothing more.
2. One batch at a time, on the owner's go each time. No fund build, pytest or code edit in the
   checkout while it runs. Never start one yourself.
3. Never edit the ledger, a check, a rule, a threshold, the gate or the scope to change a status.
4. Only the owner (or a delegate the owner named in the session, recorded as `delegate:<date>`)
   records an `owner_ruling`. Agents record `verdict`, `check_repair_request`, `owner_request`,
   `fix_record`. `decide.py` enforces this; do not write the files by hand.
5. A disposition is accepted only by a check in `data/reference/accepted_disposition_reasons.json`
   or by the owner, and only in classes `as_filed`, `not_applicable`, `informational` with a filing
   quote per fund-quarter and the rows it covers. A misfiring check is repaired, not dispositioned.
6. A real-error verdict is retired only on evidence that its cited rows equal the filed values
   (`pipeline/verdict_retirements.py`), by a deterministic check or the owner.
7. No push, publish, download, write to `frontend/public/data/`, edit of `AGENTS.md`, `git stash`.
8. One fund agent at a time; one Python job at a time; no ad-hoc inline Python.
9. Closed is not "data correct". Say so in every report.

## The cycle

1. **Read status.** `python scripts/status.py --owner-queue`. Note the batch id and build time.
2. **Hand out work by fund**, largest first (`python scripts/v05_evidence/cohort_by_size.py`): one
   subagent per fund, across all its quarters. Its packet is that fund's rows of
   `docs/investigations/findings_status.csv` with status "needs_agent_review" or "needs_data_fix".
   Its brief is `.claude/skills/v05-fund-clearing/fund-agent-brief.md` and
   `investigation-review.md`, with these changes:
   - conclusions are recorded with `decide.py` as `verdict` entries, not only in the report;
   - a fix is tested in a scratch sandbox (`bash scripts/v05_evidence/build_fund.sh <label> <cik>`)
     and then recorded as a `fix_record` whose `expects` lists the finding ids and funds it should
     change and whose `tested_in` names the sandbox;
   - a carried review stays valid unless the finding's flagged rows changed.
3. **Review before a fix is queued** (unchanged from the fund loop):
   - mechanical gate on the agent's output: `python scripts/v05_evidence/fund_gate.py check ...`;
   - an independent reviewer subagent over every finding the fund agent touched; its outcome goes
     on the `verdict` entry (`review_outcome`, `reviewed_by`) by a superseding entry;
   - a 20-row page sample (`scripts/v05_evidence/field_sample.py`), read by a third subagent.
   A fix that fails any of these gets no `fix_record`. An unsupported conclusion leaves the
   finding at "needs agent review".
4. **Batch, on the owner's go.**
   `python scripts/run_batch.py --batch-id <id> --quarters <sign-off quarters>` (detached; about six
   hours; ~14 GB free for the unified stage; `--dry-run` prints the stages). Read
   `batches/<id>/compare.csv` and `batch.json`:

   | Outcome | Meaning | Next |
   |---|---|---|
   | fixed | the fix named it and it closed | nothing |
   | fixed_pending_retirement | check silent, real-error verdict stands | retire on evidence or leave outstanding |
   | failed_fix | the fix named it and it still fires | back to the fund agent |
   | unexplained_silence | reviewed, no fix named it, it stopped firing | find out why before anyone calls it fixed |
   | closed_other | disposition, retirement, or a never-reviewed finding that stopped firing | read a sample |
   | new_finding / reopened | - | agent review |
   | outside_expected_funds = True | a fund no fix named moved | regression until explained |

   Also read `batches/<id>/holdings_diff.csv` (the `holdings` entry of `batch.json` summarises it):
   every fund whose published rows changed against the previous batch, the fields that changed, and
   whether a recorded fix named the fund. A fund that moved with `named_by_fix` False is a
   regression until explained, even when no finding moved: no rule sees a lost lien or a changed
   rate. A shared-code change that should move many funds says so in its `fix_record`
   (`expects.ciks: ["*"]`).

   Then step 1 again. A failed batch writes no ledger and leaves the previous one current.

## Recording decisions

Write the entry as JSON (fields in `pipeline/decision_store.py`), then:
`python scripts/decide.py append entry.json --actor agent:<id>` (or `owner`, `delegate:<date>`).
Filing quotes are checked against the cached page; a quote not on the page is refused.
`python scripts/decide.py show --cik <cik>` lists what stands.

Accepted dispositions, verdict retirements and disposition proposals still live in their own
validated stores (`data/overrides/finding_dispositions/`, `verdict_retirements/`,
`finding_dispositions_proposed/`) and are read through the decision store. Write them as before.

## Sign-off

A quarter is signed off from the same batch: `batches/<id>/acceptance_<quarter>.json`. The rule
is unchanged (AGENTS.md, Quarter Acceptance Contract): zero outstanding for the v0.5 funds at the
quarter, plus the FV-share bars.

## Known limits (say them when they matter)

- A reviewed finding with no reviewer verdict file that stops firing leaves the ledger; the batch
  comparison flags it `unexplained_silence` but the gate does not hold it outstanding.
- Tie-out columns compare with the filer's tags and filed totals. Page rules cover four fields.
- Requests migrated from old fund reports name no finding ids, so they do not set a status; the
  findings they concern show by their proposal class or the agent's conclusion.
- The old skills remain until the first production batch has run; do not mix the two procedures
  inside one run.

## Red flags: stop and report

- You are about to quote a count from a sandbox, a remembered number or an old status file.
- "The sandbox is clean, so it is fixed."
- You are about to read a filing or edit a wrapper yourself: that is the fund agent's work.
- A batch is running and you want to edit code or run pytest in the same checkout.
- A check went quiet and nobody recorded a fix.
