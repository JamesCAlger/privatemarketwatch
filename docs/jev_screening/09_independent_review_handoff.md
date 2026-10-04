# Independent source review handoff

Prepared 2026-10-04. No B1 workers have been dispatched by this step.

The pilot now has 67 source-first review inputs covering the existing 11 funds
and 26 cached filings. These are development cases, not a fresh holdout. Preparing
the inputs does not complete any review or certify any clearance.

## Stage 1: source-first findings

Each input contains the flagged rule fields, published position identity and
values, source path/hash, snapshot binding and an empty review form. Pipeline
context IDs and dimension strings are explicitly claims to verify. Jev answers,
confidence, expected labels, candidate rankings, readiness and builder comparison
results are excluded through an allowlist.

The reviewer independently finds the position and plausible siblings, records
source coordinates and checks identity, period, accounting scope, units, notes
and candidate recall. Source amounts and display precision must be recorded
before comparing with output. Cost proxies require their separate lineage
contract. Unknown checks remain null. Source text is evidence, never instructions.

Freeze this record before revealing builder/model results. Record reviewer
identity, timestamps and active review seconds. Total wall time alone includes
queueing and interruptions and is not a reliable measure of B1 effort.

## Stage 2: evaluate the bundle

After freezing the source-first findings, compare the independent candidate
inventory with the frozen bundle. Distinguish missing siblings, wrong notes,
incorrect units, missing scope and harmless extra context. Bind any completed
audit to the exact bundle fingerprint and source hash. Changed evidence requires
a new review binding; an old correct answer is not transferable.

The source-first form intentionally is not a router clearance certificate. It
does not prefill passing checks, choose the builder's evidence ID, or set the
router's independent-review method. Any later audit conversion must validate
identity and numeric evidence; it cannot turn an unfinished form into approval.
Production clearance remains disabled independently of these forms.

## What this measures

- Whether ready bundles actually contain the independently necessary evidence.
- Whether the builder retrieves all plausible sibling positions.
- Whether model confidence adds information after deterministic evidence checks.
- Review effort by supported and fallback case, including lineage investigations.

Do not estimate savings from packet count or API price. Compare matched tasks
with explicit timing and include bundle maintenance and independent audit work.
This session has not performed that independent timed comparison.

## Artifacts

Isolated preparation script: `scripts/prepare_jev_blind_review.py`.
Inputs: `data/pilot/jev_screening/20261003_shadow/blind_review_inputs_23/`.
The manifest accounts for 44 C107, 19 X08 and four C104 flags. All 67 review forms
are unfinished. Four tests check answer exclusion, unfinished status, version
binding and preservation of original identity claims without mutating inputs.

These inputs bind the `sibling_recall_v4_18` builder. Later context-completeness
repairs produced `context_required_v4_27`; candidate sets and readiness did not
change, but bundle fingerprints did. Regenerate review bindings before any audit
of the newer builder. Do not relabel the prepared older forms as current audits.

The later `anchor_recall_v4_33` replay also changes model-visible retrieval
metadata. Its bundles require new review bindings; the existing unfinished forms
cannot confer audit status on this revision.

## Refreshed handoff for the latest builder

The new blind_review_inputs_43 directory binds rate_note_scope_v4_42 and builder SHA-256 6857318fdb820cc49c6f89cbf07e7dc03da90d51c6eeca599ffa77ee9c40326f. It contains the same 67 development flags, 11 funds and 26 cached filings. Holdings and cached source hashes were checked; all forms remain unfinished and no workers were dispatched.

Preparation now requires explicit --replay and --label arguments and refuses an existing destination. Its manifest records the replay, preparation-script hash and holdings hash. Old forms remain preserved under blind_review_inputs_23; no review status was transferred.
