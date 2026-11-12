# Single findings workflow: design

Date: 2026-11-12. Status: design decisions made by the owner in session; nothing here is built.

## Problem

Agents cannot reliably say what is outstanding, what has been reviewed, what needs a fix, or what
the ledger holds. Measured on 2026-11-12:

- Two builds give two counts: 1,014 outstanding across about 60 fund sandboxes of different ages,
  1,677 in production (quarter pass n1110_q1c).
- A finding's status is computed by joining about eight places: the per-sandbox ledger, verdict
  files (under `data/output/review_queue/verdicts`, not in git), `verdict_retirements`, three
  disposition files, proposed dispositions, fund report JSON (requests, observations), the owner
  queue CSV, the staged / promoted / archived correction stores, and decision-log prose.
- Check results go stale: the status refresh re-runs only the ledger stage. 160 findings were
  listed as outstanding that the current checks no longer raise.
- The owner queue is built from proposals, not from live findings: 24 reasons shown as waiting,
  16 with nothing firing.
- Two workflows (`v05-fund-clearing` per fund on sandboxes, `quarter-pass-operator` per quarter on
  production) with different units of work and different ledgers.

## Owner decisions (2026-11-12)

1. Production is the only build of record. Sandboxes are scratch space with no status.
2. Fixes enter production in batches, one batch at a time. After `--unified` the ledger is
   regenerated and checked for new findings.
3. Six statuses are the only ones quoted; the detailed lifecycle states stay underneath.
4. One workflow: a production batch engine, work handed out by fund, with the fund-clearing
   practices as the default.
5. Decisions live in git; the ledger is derived per build; every build's ledger is kept.
6. The status view carries tie-out columns beside the six statuses.

## Design

### 1. Decision store

`data/decisions/` (git-tracked). One JSON-lines file per fund, `<cik10>.jsonl`, plus
`_shared.jsonl` for entries that are not fund-specific (check repairs, cohort rulings). Append
only. One schema, validated at write time by `pipeline/decision_store.py`:

| Field | Meaning |
|---|---|
| `decision_id` | unique, assigned at write |
| `type` | `verdict`, `verdict_retirement`, `disposition`, `disposition_proposal`, `owner_ruling`, `check_repair_request`, `fix_record` |
| `finding_ids` | the review ids it applies to (may be empty for a shared entry) |
| `cik`, `engine`, `rule_name`, `quarters` | finding identity, as today |
| `statement` | one sentence a reader can check |
| `evidence` | list of `{source, accession, quote, verbatim}`; filing quotes are checked against the cached page at write time |
| `rows` | row ids covered, where the type needs them (D-253 bar) |
| `rerun` | command that reproduces the evidence |
| `decided_by`, `decided_on` | who and when; `owner`, `check:<name>`, `agent:<id>`, or `delegate:<id>` with the owner's instruction quoted |
| `supersedes` | `decision_id` this entry replaces, if any |
| `expects` | `fix_record` only: finding ids and funds the fix should change |

Rules: an entry is never edited or deleted; a change of mind is a new entry with `supersedes`.
Who may write which type is enforced by the writer:

| Type | Agent | Deterministic check | Owner |
|---|---|---|---|
| verdict, fix_record, disposition_proposal, check_repair_request | yes | - | yes |
| disposition (accepted) | no | yes, for reasons in `accepted_disposition_reasons.json` | yes |
| verdict_retirement | no | yes, when every cited row equals its filed value | yes |
| owner_ruling (incl. approval of a check repair or a new rule) | no | no | yes |

The existing validators (`finding_dispositions.validate`, `verdict_retirements.validate`, the
member-quote check) are reused behind the one writer; their stores become read-only inputs to the
migration and are then retired.

### 2. Batch build

`scripts/run_batch.py --batch-id <id>`: the only thing that produces status. It is the existing
stage sequence (`fund_ledger_trial.STAGES`, the pre-dispatch half of `run_quarter_pass`) run once
on production for all quarters:

1. Preflight: no other Python job, free memory, clean decision store, list of `fix_record`
   entries since the last batch.
2. highlights, financials, `--unified`, nonaccrual.
3. Checks: validate (source reconciliation, conservation), oracle, provenance re-verify, shadow
   (page rules), queue.
4. Ledger: `scripts/findings_ledger.py` reading the decision store, written to
   `data/output/batches/<batch_id>/findings_ledger.parquet` (+ CSV), stamped with batch id, git
   commit, and the hash of the decision store.
5. Comparison with the previous batch's ledger (`--compare` exists; extended, below).
6. Gate: `pipeline.quarter_acceptance` per sign-off quarter, reading this ledger.
7. Re-attestation of signed-off quarters. A regression is stop-and-report.

`data/output/batches/<batch_id>/` is never overwritten or deleted by tooling; `latest.json`
names the current batch. If any stage fails, no ledger is written and `latest.json` is unchanged.

Batch comparison, per finding:

| Case | Result |
|---|---|
| `fix_record` expects it, check no longer fires, cited rows equal filed values | Closed |
| `fix_record` expects it, check still fires | Needs data fix, flagged `failed_fix` |
| Reviewed finding stops firing with no `fix_record` or repair claiming it | stays open, flagged `unexplained_silence` |
| A fix changes findings in a fund or rule outside its `expects` | flagged `unexpected_movement` |
| New finding id | Needs agent review |

### 3. Statuses

One function, `pipeline/finding_status.py: status_of(detailed_state, decisions) -> str`, used by
the ledger, the gate, the status view and work selection. An unknown detailed state raises.

| Status | Detailed states (today's names unless marked new) |
|---|---|
| Needs agent review | `open` with no verdict |
| Needs data fix | `real_error_unremediated`, `remediation_staged`, `remediation_pulled`, `real_error_check_silent` |
| Needs check repair | `check_repair_pending` (new): a `check_repair_request` stands, or a false-alarm verdict names the check as its cause, and no batch has yet shown the repaired check silent |
| Needs owner ruling | `needs_human`, `evidence_backlog`, or a `disposition_proposal` that meets the bar and has no accepting check |
| Fix awaiting build | `fix_queued` (new): a `fix_record` newer than the current batch names the finding |
| Closed | `RESOLVED_FINDING_STATES` as defined in `quarter_acceptance.py`, less check-caused false alarms (decision 7) |

Outstanding = not Closed. The gate's definition changes in one respect only: decision 7.

### 4. Status view

`scripts/status.py` (replaces `outstanding_status.py`). Read-only. Prints, for the current batch
only, per fund and per quarter: the six status counts, and from the same build the tie-out
columns: published FV against filed total (ties / difference), source reconcile rate, verified
FV share. Every table carries the batch id and build time. If `fix_record` entries are newer than
the batch, it says how many and that their findings show as "Fix awaiting build". The owner queue
is a second view of the same data: "Needs owner ruling" findings grouped by reason.

### 5. Workflow (one skill, replaces `v05-fund-clearing` and `quarter-pass-operator`)

1. Read status.
2. Hand out work by fund, largest first, one agent per fund across all its quarters. The packet
   is the fund's findings by status. The agent investigates "Needs agent review" (writes a
   verdict, a check-repair request or a proposal) and fixes "Needs data fix" at fund level
   (wrapper, extractor, correction), testing in a scratch sandbox, then writes a `fix_record`.
   A carried review stays valid unless the finding's flagged rows changed.
3. Review before queuing, unchanged from the fund loop: mechanical gate on the agent's output,
   independent reviewer over every finding touched, 20-row page sample. A fix failing any of
   these gets no `fix_record`.
4. Batch, on the owner's go. Its comparison report is the result of the cycle. Back to 1.

Check repairs are built in a worktree, measured against the current batch's ledger, approved by
an `owner_ruling`, and enter the next batch like any fix.

Codex fleets remain available as the worker type for step 2; the unit of work is still the fund.

### 6. Migration

1. Freeze: no new sandbox acceptances; uncommitted work from other sessions committed or dropped.
2. Convert: verdict files, `verdict_retirements`, disposition files, proposals, owner-queue
   rulings, report requests, and the B2 correction stores' review-id links into the decision
   store. Decision-log rulings are converted only where they touch an open finding. Check: status
   computed from the new store on the current production ledger equals status computed the old
   way, finding by finding; the diff must be empty or each difference explained in writing.
3. Add the two new detailed states and `status_of`.
4. First batch. Compare against each registered sandbox ledger once (`sandbox_parity.py`) to find
   fixes that exist only in a sandbox.
5. Retire: `accepted_sandboxes.json`, per-sandbox ledgers as a source, `outstanding_status.py`,
   `owner_queue.py`, the two skills. The AGENTS.md pointer changes only by the owner.

### 7. Testing

- `status_of`: every detailed state maps to exactly one status; unknown state raises.
- Decision store: schema, append-only, supersession, writer permissions, quote-on-page.
- Batch comparison: synthetic ledgers for a fix that worked, a failed fix, unexplained silence,
  unexpected movement, a new finding.
- Migration parity (step 2).
- Gate: existing tests unchanged except for decision 7, which gets its own tests (a check-caused
  false alarm is outstanding; a repaired, silent one closes).

## Further owner decisions (2026-11-12, "go with recommended approaches on all three points")

7. A false-alarm verdict whose cause is the check maps to "Needs check repair", not Closed
   (`adjudicated_false_alarm` is Closed today, against the 2026-11-04 ruling). A false-alarm
   verdict must therefore name its cause: `check` (stays outstanding until the check is repaired
   and a batch shows it silent) or `data_as_filed` (closes only through a disposition). This is
   an acceptance change and will raise the outstanding count. Existing false-alarm verdicts carry
   no cause field; the migration counts them and they are classified before the first batch is
   quoted (deterministically where the verdict's mechanism text allows, otherwise by agent
   review). Until classified they show as "Needs agent review".
8. `gone_unadjudicated` stays Closed (a never-reviewed finding that stops firing) and is listed
   in the batch report. Only reviewed findings stay open under `unexplained_silence`.
9. A batch runs on the owner's go each time, not on a schedule, while the build is unreliable.

## Risks

- Everything waits on the production build. `--unified` has been killed for low memory several
  times on this machine. If a batch cannot complete, nothing closes. Making the build reliable is
  a precondition.
- Feedback is slower: an agent learns whether a fix worked only after the next batch.
- One batch carries many fixes; a regression is not always attributable automatically (`expects`
  narrows it, a scratch sandbox bisects it).
- Migration is where rulings could be lost; the parity check is the control.
- "Closed" and a tie-out that ties still do not prove the data is correct: the first three match
  layers compare with the filer's tags, the page rules cover four fields.

## Not in scope

Per-fund production updates; new detectors (including page checks on more fields); frontend
changes; clearing the current backlog; making `--unified` reliable (separate, prior work).
