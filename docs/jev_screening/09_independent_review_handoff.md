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

## Refreshed handoff for builder 42 (historical)

The new blind_review_inputs_43 directory binds rate_note_scope_v4_42 and builder SHA-256 6857318fdb820cc49c6f89cbf07e7dc03da90d51c6eeca599ffa77ee9c40326f. It contains the same 67 development flags, 11 funds and 26 cached filings. Holdings and cached source hashes were checked; all forms remain unfinished and no workers were dispatched.

Preparation now requires explicit --replay and --label arguments and refuses an existing destination. Its manifest records the replay, preparation-script hash and holdings hash. Old forms remain preserved under blind_review_inputs_23; no review status was transferred.

## Validating a completed source-first form

The isolated pipeline/jev_review_findings.py validates completed copies against their immutable prepared envelope. It accepts explicit unresolved outcomes without filling missing checks. A false-alarm record requires all six checks, one selected candidate with no unresolved siblings, source-bound citations, all disputed amounts, USD currency and arithmetic agreement at recorded display precision. Contradictory amounts can be recorded as a real-error finding.

The reviewer adds source_first_attestation: true inside review_form, identifying their own declaration that source findings preceded exposure to builder/model results. This is an attestation, not mechanically verified independence. Citations are objects containing source_sha256, coordinates and supports. Candidate entries contain coordinates, treatment (selected/excluded/unresolved) and reason. Source values contain amount, display_unit and currency. All timestamps require timezones; active_seconds must be positive and no greater than elapsed review time.

The bounded scripts/freeze_jev_review_findings.py checks the prepared manifest/input hashes, current holdings and original cached source before writing a new content-addressed source-first findings record. It refuses overwrites. The result explicitly marks independence_verified and bundle_audit_completed false, has no router audit method/evidence ID, and cannot itself act as a clearance certificate. A later separately validated bundle comparison remains necessary.

Twenty focused tests pass for the findings validator, including unresolved outcomes, source and envelope changes, timing, incomplete checks, invalid monetary values, unresolved siblings and contradictory amounts. The CLI help path was exercised. No completed real-case form was submitted or frozen; independent reviews remain zero.

Five additional CLI integration tests pass using temporary synthetic fixtures: unresolved-record sealing, changed source, changed holdings, changed prepared input and overwrite refusal. They do not count as real completed reviews.

## Current source-first handoff

`blind_review_inputs_53` binds replay `explicit_visibility_v4_52`, builder SHA-256
`50a963afa56516ffc4c59606a27b292b861da55da6bb40cf95b432e9b243aeb1`.
It contains the same 67 flags, 11 funds and 26 cached source files. Preparation
rechecked source/holdings hashes. All forms are unfinished; independent reviews
and clearance certificates remain zero. Older forms and integrity reports remain
historical records and do not bind the changed requests.

The offline verify_jev_review_bindings.py check matches all 67 current packet fingerprints to the current blind_review_inputs_53 bindings, verifies prepared-file hashes, checks the holdings snapshot, and rehashes all 26 original cached sources. All match. Prepared manifest SHA-256: 6d08af436a942eecab17d62e0f988810688fad1ade337728c89a5e1de438f578. Earlier integrity reports remain historical. This verifies content integrity against saved records, not independent evidence completeness; completed reviews remain zero.

## Coordinate consistency in completed review records

The findings validator now rejects duplicate candidate coordinates, including conflicting selected/excluded treatments of the same location. For a false-alarm finding, source_coordinates must match the selected inventory candidate, and at least one citation must name that location. Case and whitespace differences are normalized; distinct free-text coordinate schemes are not guessed equivalent. Additional note/scope citations remain allowed.

Twenty-six findings tests plus five freeze-CLI integration tests pass (31 total). No real completed form has been submitted. This closes internal record contradictions; it does not verify coordinates against source bytes or establish independent source truth. Prepared forms 53 and the current builder are unchanged.

## 2026-10-04: dependency-bound replay refresh

Current unfinished forms are blind_review_inputs_56, bound to dependency_bound_v4_55 and builder 1aa2a991b20957c2c7db4843be929c241230fa0f8f0041aae886a8a627b30570. The 67 forms cover the same 11 funds and 26 cached filings. Manifest SHA-256: 5db563b7b2d0e3d297aa486562ff91a6059712449ccf71a754d84ff5f2df505a. Review binding check 5e65701c442729f4 verifies packet/input/source hashes. All reviews remain unfinished; historical forms 53 are preserved and are not current certificates. Direct parser dependencies are now recorded; see the run log for the exact scope and limitations.
