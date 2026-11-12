# Single Findings Workflow Implementation Plan

> **For agentic workers:** execute task by task; steps use checkbox (`- [ ]`) syntax. Work only in
> the worktree `.claude/worktrees/single-findings-workflow` (branch `single-findings-workflow`).
> No Fable subagents (owner 2026-11-12); Sonnet or Opus only.

**Goal:** one status per finding, one place decisions are written, one batch build that produces
the ledger, one status view, one workflow skill.

**Architecture:** a pure status function over (ledger state, decision facts); a git-tracked
append-only decision store with one loader that also exposes the existing validated stores; a
batch runner that wraps the existing stage sequence on production and keeps every ledger; a
read-only status view over the latest batch.

**Tech stack:** Python 3, pytest, DuckDB for large reads, existing `pipeline/` and `scripts/`.

**Spec:** `docs/superpowers/specs/2026-11-12-single-findings-workflow-design.md`

## Global constraints

- AGENTS.md contracts apply: no network, no writes to `data/output/` or `frontend/public/data/`
  from tests, ASCII-only logs, no ad-hoc inline Python, one Python job at a time, no code edits
  or pytest in a checkout while it builds, never `git stash`, do not edit AGENTS.md.
- The gate's definition of outstanding does not change: outstanding = state not in
  `pipeline.quarter_acceptance.RESOLVED_FINDING_STATES`.
- `adjudicated_false_alarm` and `gone_unadjudicated` stay Closed (owner decisions 7, 8).
- Batches run on the owner's go only (decision 9). This plan builds the runner and tests it on
  synthetic and sandbox data; it does not start a production build.
- Decision entries are append-only; a change of mind is a new entry with `supersedes`.

## Design decisions made while planning (deviations from the spec are marked)

1. **Status is a derived column, not two new detailed states (deviation).** The spec adds
   `check_repair_pending` and `fix_queued` as detailed states. Instead `classify_finding` is left
   untouched and the ledger gains a `status` column computed by `finding_status.status_of(state,
   facts)`. Same result for every reader, no change to the gate's inputs, no risk to the ~80
   existing uses of the detailed states.
2. **Existing validated stores stay physically where they are in this plan (deviation).**
   `finding_dispositions/*.json`, `verdict_retirements/*.json` and the proposals folder keep their
   validators and files; `decision_store.load_all()` exposes them as entries through adapters, and
   new writes of those types go through `decision_store` writers that call the existing
   validators. Everything that had no structured, git-tracked home moves into
   `data/decisions/*.jsonl`: fund-agent conclusions and their independent reviews, check-repair
   requests, owner rulings, fix records. Physical consolidation of the three old stores is a
   later, separate change; rewriting them now would touch the gate's inputs and ~50 tests for no
   change in behaviour.
3. **Reviewer verdict files are copied into git.** `data/output/review_queue/verdicts` (3,127
   files, 4.8 MB) is gitignored build output. They are copied byte-for-byte to
   `data/decisions/verdict_files/` (hashes preserved, so retirements still match) and that folder
   is put first in `scripts/check_tier_coverage.VERDICT_DIRS`.
4. **Status mapping** (first match wins):

   | # | Condition | Status |
   |---|---|---|
   | 1 | state in `RESOLVED_FINDING_STATES` | `closed` |
   | 2 | a standing `fix_record` newer than the ledger's build names the finding | `fix_awaiting_build` |
   | 3 | a standing `check_repair_request` names the finding, or a standing proposal for it has class `rule_problem` / `false_alarm` | `needs_check_repair` |
   | 4 | state in `needs_human`, `evidence_backlog` | `needs_owner_ruling` |
   | 5 | a standing proposal for it has class `as_filed` / `not_applicable` / `informational` | `needs_owner_ruling` |
   | 6 | state in the real-error family (`real_error_unremediated`, `remediation_staged`, `remediation_pulled`, `real_error_check_silent`, `b1_route_missing`, `b2_execution_unproven`, `b3_pass_pending_promotion`, `promoted_pending_verification`) | `needs_data_fix` |
   | 7 | supported fund-agent conclusion `confirmed_error` | `needs_data_fix` |
   | 8 | supported fund-agent conclusion `false_alarm` | `needs_check_repair` |
   | 9 | supported fund-agent conclusion `source_ambiguity` | `needs_owner_ruling` |
   | 10 | anything else (`open`, `b1_re_adjudication_required`, `unverified_absence`, unsupported or missing conclusion) | `needs_agent_review` |

   An unknown detailed state raises `ValueError`.
   A proposal stops standing when an `owner_ruling` rejects its reason; a rejected misfire-class
   proposal still counts under row 3 (the finding needs a check repair, not a ruling).

## File structure

| File | Responsibility |
|---|---|
| `pipeline/finding_status.py` (new) | `STATUSES`, `KNOWN_STATES`, `Facts`, `status_of` |
| `pipeline/decision_store.py` (new) | entry schema, `validate`, `append`, `load_native`, `load_all` (native + adapters), `standing`, `facts_by_finding` |
| `scripts/migrate_decision_store.py` (new) | one-off conversion of reports, reviews, owner-queue rulings, requests; copies verdict files |
| `scripts/findings_ledger.py` (modify) | add `status` column from `decision_store` + `finding_status` |
| `scripts/run_batch.py` (new) | batch runner: stages, ledger, comparison, pointer |
| `pipeline/batch_compare.py` (new) | classify per-finding movement between two ledgers |
| `scripts/status.py` (new) | status view and owner-queue view from the latest batch |
| `.claude/skills/findings-workflow/SKILL.md` (new) | the one workflow |
| `tests/test_finding_status.py`, `tests/test_decision_store.py`, `tests/test_batch_compare.py`, `tests/test_status_view.py`, `tests/test_run_batch.py` (new) | tests |

---

## Phase 1: status mapping

### Task 1: `pipeline/finding_status.py`

**Files:** create `pipeline/finding_status.py`, `tests/test_finding_status.py`.

**Interfaces (produces):**
```python
STATUSES = ("needs_agent_review", "needs_data_fix", "needs_check_repair",
            "needs_owner_ruling", "fix_awaiting_build", "closed")
KNOWN_STATES: frozenset[str]          # every state findings_ledger can emit
@dataclass(frozen=True)
class Facts:
    fix_queued: bool = False          # standing fix_record newer than the build
    check_repair: bool = False        # standing check_repair_request
    proposal_class: str = ""          # class of a standing or rejected-misfire proposal, else ""
    conclusion: str = ""              # fund-agent conclusion, "" if none
    conclusion_supported: bool = False
def status_of(state: str, facts: Facts = Facts()) -> str
```

- [ ] Tests first (`tests/test_finding_status.py`): one test per mapping row above; every state
  in `KNOWN_STATES` returns a member of `STATUSES`; unknown state raises; precedence tests
  (closed beats a queued fix; fix beats check repair; check repair beats needs_human; an
  unsupported `false_alarm` conclusion gives `needs_agent_review`); `KNOWN_STATES` contains every
  state literal `scripts.findings_ledger.classify_finding` can return plus
  `finding_dispositions.STATE_BY_CLASS` values, `resolved_upstream` and `verdict_retired`;
  `RESOLVED_FINDING_STATES` is a subset of `KNOWN_STATES`.
- [ ] Run, see them fail (module missing).
- [ ] Implement.
- [ ] Run `python -m pytest tests/test_finding_status.py -q`; all pass.
- [ ] Commit.

## Phase 2: decision store

### Task 2: native store (`pipeline/decision_store.py`)

**Interfaces (produces):**
```python
TYPES = ("verdict", "verdict_retirement", "disposition", "disposition_proposal",
         "owner_ruling", "check_repair_request", "fix_record")
NATIVE_TYPES = ("verdict", "owner_ruling", "check_repair_request", "fix_record")
def default_dir() -> Path                      # config.REPO/data/decisions
def validate(entry: dict) -> list[str]
def append(entry: dict, *, actor: str, directory: Path | None = None,
           page_text=None) -> dict             # assigns decision_id, validates, enforces actor, appends one line
def load_native(directory: Path | None = None) -> list[dict]
def standing(entries: list[dict]) -> list[dict]   # drops superseded entries
```
Entry fields: `decision_id` (`DC-<cik or shared>-<8 hex>`), `type`, `finding_ids` (list),
`cik`, `engine`, `rule_name`, `quarters`, `statement`, `evidence` (list of `{source, accession,
quote}`), `decided_by` (`owner` | `delegate:<id>` | `check:<name>` | `agent:<id>`), `decided_on`,
optional `supersedes`, `rerun`, `rows`, and per type:
`verdict`: `conclusion` in (`confirmed_error`, `false_alarm`, `source_ambiguity`,
`insufficient_evidence`), `reviewed_by`, `review_outcome` in (`supported`, `rejected`, ``);
`owner_ruling`: `ruling` in (`accept`, `reject`, `more`, `approve`, `decline`), `reason_key` or
`request_id`, `words`; `check_repair_request`: `request_id`, `check` (file or rule), `resolution`
in (`open`, `approved`, `implemented`, `declined`); `fix_record`: `expects` (`finding_ids`,
`ciks`), `commit` or `files`, `tested_in` (sandbox label).
Actor rules: `owner_ruling` only by `owner` or `delegate:`; `agent:` may write `verdict`,
`check_repair_request`, `fix_record`. File: `<cik10>.jsonl`, or `_shared.jsonl` when `cik` is
empty. Lines are JSON with sorted keys; file is only ever opened in append mode.

- [ ] Tests: valid entry of each native type appends and round-trips; missing field, bad date,
  bad type, bad conclusion rejected; agent writing an `owner_ruling` raises `PermissionError`;
  filing quote not found by `page_text` rejected; `supersedes` removes the older entry from
  `standing`; ids unique; append never rewrites earlier lines (file prefix unchanged).
- [ ] Implement; run; commit.

### Task 3: adapters and facts

**Interfaces (produces):**
```python
def load_all(directory=None, *, dispositions_dir=None, retirements_dir=None,
             proposals_dir=None) -> list[dict]   # native + adapted entries, each with "origin"
def facts_by_finding(entries, ledger_rows, *, build_time: str) -> dict[str, finding_status.Facts]
```
Adapters: accepted dispositions -> `disposition`; retirements -> `verdict_retirement`; proposal
files -> `disposition_proposal`. `facts_by_finding` matches proposals to ledger rows on
(cik, engine, rule_name, quarter), other entries on `finding_ids`.

- [ ] Tests with temp dirs: adapters expose each store's entries; a proposal whose reason was
  rejected by an `owner_ruling` is not standing unless its class is misfire; a `fix_record` dated
  before `build_time` does not set `fix_queued`; latest supported verdict wins.
- [ ] Implement; run; commit.

### Task 4: migration (`scripts/migrate_decision_store.py`)

Reads (never modifies) `docs/investigations/v05_readings/reports/*.json` (`investigations`,
`orchestrator_requests`, `request_resolution_history`), `reviews/*.json` (`finding_reviews`),
`docs/investigations/v05_owner_queue.csv` (rulings), and copies verdict files. Writes
`data/decisions/*.jsonl` with `decided_by` taken from the source (`agent:<investigator_id>`,
`owner` for owner-queue rows except those whose words begin "Delegated reviewer", which become
`delegate:2026-11-12`), and `migrated_from` naming the source file. Idempotent: refuses to run
into a non-empty `data/decisions/` without `--force-empty-check` passing.

- [ ] Tests on fixture files: counts in = counts out per type; latest review outcome attached to
  the right verdict; delegated rulings marked `delegate:`; second run refused.
- [ ] Implement; run tests; run the migration for real; record counts in the commit message.
- [ ] Parity check (script `scripts/decision_store_parity.py`): for the current
  `outstanding_status.csv`, the old category and the new status agree under this table, every
  exception listed: proposal -> needs_owner_ruling or needs_check_repair; verdict ->
  needs_data_fix or needs_owner_ruling; review_supported -> needs_data_fix / needs_check_repair /
  needs_owner_ruling by conclusion; narrative, unreviewed, investigated -> needs_agent_review.
  Write the result to `docs/investigations/v05_readings/decision_store_parity.md`.

### Task 5: ledger `status` column

- [ ] Test (`tests/test_findings_ledger.py` addition): `build_ledger` rows carry `status`, equal
  to `status_of(state, facts)`; with an empty decision store every row's status matches rows 1,
  4, 6, 10 of the table.
- [ ] Modify `build_ledger` (new kwarg `decisions_dir`, `build_time`), `write_ledger` unchanged
  apart from the extra column. Run `tests/test_findings_ledger.py`, `tests/test_quarter_acceptance.py`.
- [ ] Commit.

## Phase 3: batch build

### Task 6: `pipeline/batch_compare.py`

```python
def compare(prior: list[dict], current: list[dict], fix_records: list[dict]) -> list[dict]
# one row per finding that changed or was expected to: review_id, cik, rule_name, report_date,
# prior_state, state, prior_status, status, outcome
# outcome in: fixed, failed_fix, unexplained_silence, unexpected_movement, new_finding,
#             closed_other, reopened, unchanged_expected
```
- [ ] Tests on synthetic ledgers, one per outcome, plus: a never-reviewed finding that vanishes
  is `closed_other` (decision 8), a reviewed one is `unexplained_silence`.
- [ ] Implement; commit.

### Task 7: `scripts/run_batch.py`

`--batch-id`, `--dry-run`, `--from/--until`, `--output-dir` (default `config.OUTPUT_DIR`, so a
fund sandbox's output dir can be passed for a rehearsal). Stages = `fund_ledger_trial.STAGES`
commands run against the output dir, then ledger (with `status`), compare with the batch named
in `batches/latest.json`, gate per sign-off quarter, write `batches/<id>/` (`findings_ledger.csv`,
`.parquet`, `compare.csv`, `batch.json` with git commit, decision-store hash, stage exit codes),
and only then move `latest.json`. Any stage failure: no ledger, pointer unchanged, exit 1.
Refuses to start if another Python process is running or `batches/<id>` exists.

- [ ] Tests with stage commands stubbed: failure leaves pointer unchanged; success writes all
  files and moves the pointer; existing batch id refused; `--dry-run` writes nothing.
- [ ] Rehearsal on one existing fund sandbox output dir with `--from ledger` (no rebuild).
- [ ] Commit.

## Phase 4: status view

### Task 8: `scripts/status.py`

Reads `batches/latest.json` (or `--batch`), the batch ledger, the decision store; prints and
writes `docs/investigations/findings_status.md` / `.csv`: per fund and per quarter the six
status counts and tie-out columns (published FV vs filed total and difference from the
conservation output, reconcile rate, verified FV share, each read from the batch's own output
files; a missing input prints `n/a`, never a guess); header with batch id, build time, commit,
count of fix records newer than the batch. `--owner-queue` prints `needs_owner_ruling` findings
grouped by proposal `reason_key` / request id.

- [ ] Tests on a temp batch dir: counts by status; stale-fix notice; owner queue lists only
  findings present in the ledger; missing tie-out input shows `n/a`.
- [ ] Implement; commit.

## Phase 5: cutover (prepared here, switched by the owner)

### Task 9: workflow skill and retirement list

- [ ] Write `.claude/skills/findings-workflow/SKILL.md` (read status, hand out by fund, review
  before queuing, batch on the owner's go; fund-clearing safeguards kept).
- [ ] Mark `v05-fund-clearing` and `quarter-pass-operator` SKILL.md with a one-line pointer to the
  new skill; do not delete them until the first production batch has run.
- [ ] Changelog entry; list for the owner: first production batch, sandbox-parity comparison,
  retirement of `accepted_sandboxes.json`, `outstanding_status.py`, `owner_queue.py`, and the
  AGENTS.md pointer (owner's hand).

## Not done by this plan

The first production batch (owner's go); physical consolidation of the disposition, retirement
and proposal stores; conversion of decision-log prose; deletion of the old skills and scripts.
