# Eight-hour build and test plan

Date: 2026-10-03. Status: planned; this document does not start execution.

## Objective and end state

Build a tested shadow implementation that establishes whether Jev can safely
reduce weak-rule investigation work and free B1 capacity for additional rules.
Deliver repaired C107/X08 bundles, explicit routing receipts and a bounded
evaluation. Production clearance remains disabled throughout this session.

The key question is how many flags can be safely cleared after accounting for
bundle failures and audit work, not how many Jev requests succeed. Compare Jev
with deterministic checks alone so we can identify its additional contribution.

This is a feasibility session, not certification of a production error rate.
Use the [evidence contract](01_routing_and_bundles.md) and
[validation plan](02_implementation_and_validation.md) as the governing design.

## Schedule

Times are elapsed from session start. Tests for a failure begin with its fix;
the dedicated test block completes cross-cutting regression coverage.

| Window | Focus and reason | Concrete output / checkpoint |
|---|---|---|
| 00:00-02:30 | Establish the frozen baseline and fix bundle correctness. Incorrect ready packets are more dangerous than explicit rejection. | TCW unit conflicts, Ares identity contradictions and Onex period selection reproduced; each either correctly resolved with evidence or explicitly blocked. |
| 02:30-03:30 | Complete focused regression tests, including valid counterexamples and changed structures. Avoid fitting only the observed failures. | Test results and a development-case before/after table separating readiness from independently valid evidence. |
| 03:30-04:30 | Implement minimal shadow routing and receipts. Make every route explainable and every flag accounted for. | Bounded runner, stable snapshot keys, explicit reasons, complete member accounting; no production queue suppression. |
| 04:30-06:00 | Run the frozen blind evaluation. Measure behaviour on evidence not used to build the solution. | Three-policy comparison, source-reviewed outcomes, raw requests/responses and uncertainty/coverage report. |
| 06:00-07:00 | Conditionally probe one additional weak-rule family. Test the wider-screening opportunity. | Small evidence contract and development probe, or use the hour to resolve core failures. No eligibility promotion. |
| 07:00-08:00 | Complete verification, analyse outcomes and preserve evidence. Make the next decision reproducible. | Durable run artifacts, documented checks/limitations, changelog and a recommendation by rule/layout. |

## 1. Baseline and bundle repair

Use the first 15 minutes of the opening block to inspect current changes and the
latest changelog, record existing test/rebuild processes, and freeze versions,
input hashes and the development manifest. Preserve unrelated worktree changes.
Reserve the holdout identities before detailed source inspection or new fixes.

Extend `pipeline/jev_bundles.py` and its existing CLI rather than create a second
builder. Implement in this order:

1. TCW: detect displayed-unit versus inline-scale contradictions. Resolve only
   with independent corroboration; never normalise solely to match output.
2. Ares: compare visible instrument/share class with output and XBRL dimensions.
   Matching amounts or context IDs cannot override conflicting identity.
3. Onex: attach explicit reporting-period evidence to each candidate, including
   comparative and continuation schedules.
4. If time remains, address reusable header, split numeric-cell and note patterns.
   Retain missing currency or unresolved source context as explicit failures.

Record mechanisms and maintenance effort. Prefer general layout handling and
small evidenced configuration to whole per-filer builders. Preserve original
cells, source coordinates, candidate siblings and normalisation decisions.

Checkpoint: all known unsafe-ready examples are corrected or blocked. If not,
continue repairs and shrink later work; do not expand the rule set.

## 2. Focused verification

Add regression fixtures for the observed failures and valid counterexamples:
legitimate negative costs, genuinely low FV, consistent inline scales, distinct
share classes and current/comparative schedules. Exercise later-period or altered
layout fixtures without claiming synthetic fixtures establish real-filer coverage.

Run targeted `tests/test_jev_bundles.py` tests, then that file. Routing tests follow
the implementation in the next block. Record exact commands and results. Apply
the repository's post-test semantic-diff requirement; report existing differences
separately from this work. If scope or runtime prevents a required check, record
it as incomplete, never as passing. Check for existing long jobs before starting
one. No full-suite run is scheduled for this narrow experimental change; a later
merge or broader shared-contract change requires the repository's wider checks.

## 3. Minimal shadow routing

Add the proposed `pipeline/jev_screening.py` and bounded
`scripts/run_jev_screening.py`, using existing transport patterns where suitable.
Accept an explicit manifest and emit decisions beside the evaluation artifacts.
Do not integrate production queue filtering in this session.

Apply the routing precedence from the evidence contract: high-error/strong rules,
unsupported or conflicting bundles, provider failures, suspected errors,
ambiguity and low confidence all remain B1 work. Only verified high-confidence
false alarms become candidate clearances. Start decision confidence at 0.75;
freeze a separate trial source threshold before holdout calls. These are
experimental cutoffs, not calibrated probabilities.

Test threshold boundaries, contradictory evidence despite high confidence,
missing/malformed responses, stale input hashes, repeat runs and partial grouped
review coverage. Every selected member must have exactly one current route;
unprocessed work stays pending. Retain attempt history and model observations
separately from final source-reviewed outcomes.

## 4. Bounded blind evaluation

Use cached BDC filings only. The programme remains capped at 16 distinct funds,
including the nine consumed development filers. Confirm this remains below the
canonical v1 cohort. For this session use:

- At most four untouched holdout funds, two periods per fund where available and
  40 natural holdout flags; missing strata remain explicit.
- At most 100 Jev calls across the entire session, including development probes,
  reversed-option checks, retries and the optional new-rule probe. Reserve calls
  before each arm; do not spend the entire allowance on repeats.
- Existing consumed filers for any new-rule development probe; never reuse a
  scored holdout as untouched after a repair.

Freeze the model, prompt, builder, thresholds, sample selection and scoring rules
before holdout calls. Select funds without tuning to their detailed source rows.
Create source-reviewed references before revealing Jev decisions, retaining
ambiguous and unscorable outcomes. B1 references require independent access to
cached source evidence; historical labels alone are not ground truth.

Use the existing supported B1 workflow where available, following its dispatch
instructions. If fresh blind B1 review cannot be completed within the session,
report that arm as incomplete. Do not substitute reused historical verdicts and
claim a fresh blind comparison or measured time saving.

Compare the existing B1 policy, deterministic evidence checks alone, and those
same checks plus Jev/B1 routing on the same frozen flags. Audit every candidate
clearance in this small evaluation. Manually repaired bundles form a separate
diagnostic arm and never count as automatic coverage.

Report selected/blocked/valid/called/cleared/escalated counts, unsafe clearances,
error capture, confidence distributions, distinct error mechanisms and effort.
Separate actual B1 time from estimated avoided work; report missing timings.
Do not claim fixed-budget incremental discovery from a routing simulation alone.

## 5. Conditional additional weak rule

Proceed only when core regression checks and routing accounting pass and the
evaluation has no unresolved unsafe-clearance mechanism in the mode being reused.
Otherwise spend this hour on repairs or additional source review.

Rank candidate weak rules using available flag volume, source accessibility,
audited error yield and likely B1 burden. Unknown true-error rates remain unknown;
do not infer them from selected examples. Choose one family with a small evidence
contract and test at most six natural development flags from already consumed
funds, within the shared API allowance.

Deliver an evidence specification, a small working probe if feasible, and a
source-reviewed account of any additional defects. This exploratory probe cannot
enable clearance or replace the new family's later calibration and holdout.

## 6. Handoff and decision

Reserve the final hour even if implementation runs late. Drop the additional-rule
probe first, then reduce evaluation size with explicit denominator changes; do
not relax evidence checks or conceal incomplete work to meet the schedule.

Preserve a run manifest, versions/hashes, bundle audit, request/response records,
routing receipts, reference labels and metrics under a durable evaluation path
such as `data/pilot/jev_screening/<run_id>/`. Keep disposable logs in session
scratch and never persist credentials. Record API usage, failures and cost basis.

The final report should answer:

- Which bundle mechanisms are fixed, blocked or still unsupported?
- How much safe automatic coverage is observed on development versus holdout?
- What does Jev add beyond deterministic checks, and at what maintenance cost?
- How much B1 work remains, including audits, and what savings are only estimates?
- Does the evidence support further shadow testing, a narrower scope, or dropping
  Jev for particular rules? What additional evidence is needed next?

Append the agent changelog and, when experiments produce new findings, update the
investigation record and its index. List checks run and not run. No SEC downloads,
holdings corrections, production clearance, gate changes or baseline refresh are
part of this eight-hour plan.
