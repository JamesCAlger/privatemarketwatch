# Refactor handoff - 14 September 2026

**Owner decision: pause the open-ended P1-P8 refactor because of model-usage cost.**
Let the existing identity/comparison sequence and already-queued focused tests plus
semantic backstop finish. No subsequent candidate build, investigation or evaluation
is authorized by this wind-down. Resume only for an individually bounded deliverable.

## What is usable

- Candidate code includes tested currency-admission and replay fixes. Unknown or
  unsupported monetary units remain explicit instead of entering USD totals.
  The latest related batch passed **300 tests**; its semantic backstop found
  **no new material drift** against the previously recorded baseline differences.
- V9's full unified stage is sealed: **780,616 holdings, 100 columns**, seven
  CSV/Parquet pairs with zero differences, and **283,620 protected files unchanged**
  under size/mtime checks. Frozen-input and artifact hashes are checked separately.
- V8 demonstrated all five isolated stages and exact history readback. Its browser
  checks passed, but later currency/name/citation repairs require V9 verification.
  V8 evidence cannot establish that the current candidate passes.
- Selective cleanup removed **211.50 GB** from 24 completed workspace/temp
  directories. All **715 retained bundle/proof/log files** passed hash checks.
  Frozen inputs, raw data, saved results and failed-attempt evidence were retained.

These are engineering results. **P1-P8 is not complete; a measured production-quality
improvement has not been demonstrated. No publication or baseline adoption occurred.**

## Existing checks finishing locally

1. V9 identity finalization and comparisons with the original candidate and V8.
2. The already-queued five-file legacy-input collector test batch and semantic backstop.

Their terminal results will be written to
[wind-down results](2026-09-14_wind_down_results.md) by a local observer. Until that
file exists, these checks are pending. The observer starts no tests or pipeline jobs.
If a controller stops without a result, it records that failure rather than restarting.

## Remaining defects or unresolved evidence

- **Matching:** V8 showed reference regressions. V9 comparison results need human/model
  review before any claim that the cached-name repair resolved them. Do not accept
  a lower entity count or a successful build as proof of better matching.
- **Quarterly evaluator wiring:** the existing source-blocker queue and investigation
  snapshots are implemented in a new helper but not connected to the P4 driver.
  The driver still uses placeholder paths for those inputs. The pending patch also
  requires evidence receipts to name the files actually measured.
- **Current integrated verification:** V9 financial/source/field/public evaluations,
  all 13 quarter verdicts and re-attestation, browser/performance, cold twin, recovery
  and final full suite are outstanding. They are required for the original full
  architecture-completion claim, not prerequisites for every smaller future fix.
- **Historical full suite:** 5,295 passed, six failed, 13 skipped, two expected failures.
  The six original failures passed focused repair checks; there is no final full-suite pass.
- **Operational evidence:** legacy correction admission, unresolved source units and
  source/classification coverage retain gaps. Missing evidence must remain explicit;
  do not weaken gates or launch enrichment campaigns to close an architecture checklist.

## Recommended next decision

First review the saved matching comparison summary. Then select **one** defect with
a stated user-visible benefit and acceptance test. The P4 wiring gap is a concrete
candidate: connect actual inputs, run the focused integration controls, and confirm
that missing or mismatched evidence cannot yield a false pass. It does not require
another full candidate build merely to test that interface.

dbt, Arelle, R2 and production remediation/enrichment remain deferred. Additional
storage cleanup, broad performance work and further diagnostic scripts are optional.
Do not resume the entire backlog automatically.

## Evidence and resumption notes

- Candidate: `data/programme/candidates/production-20260914-v9/`.
- Evidence: `scratch/2026-09-12_programme_e0/`; detailed state is in `PROGRESS.md`.
- Cleanup receipt: `completed-workspace-cleanup-v3/result.json` under that evidence root.
- Pending evaluator patch: `p4-legacy-wiring.pending.patch`; not applied.
- Pending integration tests: `test_legacy_acceptance_wiring.pending.py`; not installed/run.
- `inspect_identity_regressions.py` is prepared only; not compiled or run.
- Preserve the dirty worktree and immutable candidates. Read this pause decision before
  following any older continuation scripts or the broader execution plan.
