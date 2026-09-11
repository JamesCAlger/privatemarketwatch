# BDC pipeline consolidation: preparation and launch gate

Date: 2026-09-08. Owner-decision status updated 2026-09-09.
Status updated 2026-09-11: [overnight preparation](programme_spec_closeout_2026-09-09.md) and the owner-authorized [first bounded implementation tranche](programme_execution_tranche_2026-09-09.md) have occurred. All three v5 candidate stages completed; verification stopped after protected test-cache writes during a timed-out full suite. The test-isolation correction passed bounded verification; the production regex-validator correction, full-suite verification, integrated measurements and recovery remain open. Use the [handoff](programme_tranche_handoff_2026-09-10.md) for execution evidence. The owner has now accepted roster/field verification section 12; sections 13-15 complete the remaining evidence, compatibility and all-criterion design for final review. See the [consistency assessment](programme_spec_consistency_review_2026-09-10.md). No human reviewer appointment, new execution window or production adoption is introduced. Older preparation checklists and the [numerical review response](programme_review_response_2026-09-10.md) retain their historical meaning.

## 1. Immediate objective

Current reading guide, 11 September: use [programme specification status](programme_spec_status.md) and measurement-register sections 12-15 for the completed verification definitions, final-review status and remaining implementation proofs. The preparation workflow below is retained as the original plan; it is not a request to repeat completed assessments or an assertion that the target product is ready.

Prepare the existing pipeline for one lead agent to deliver a controlled,
testable consolidation programme through bounded worker tasks. The owner should
decide financial meaning and acceptable risk, not coordinate individual workers.

This preparation comes BEFORE the earlier next-agent instruction to start with
currency fixes. Those fixes remain candidate implementation tasks, not abandoned
work. Do not confuse having this plan with having passed the launch gate below.

The problem is overlapping authority, not simply multiple files. Extraction,
holdings, correction and validation schemas legitimately differ. Consolidate who
defines each meaning and who can change each field; do not flatten every schema
and per-CIK configuration into one giant file.

## 2. Existing work to reuse

- [88-column crosswalk and F01-F12](../reference/unified_holdings_contract_crosswalk.md),
  including section 18's availability audit. Descriptive evidence, NOT approved
  new semantics. Do not redo the column inventory without a detected change.
- [Target contract](programme_target_contract.md), [88-field disposition map](../reference/programme_field_disposition.csv)
  and [28-criterion measurement register](programme_measurement_register.md),
  added 2026-09-09 after all owner decisions were resolved. These are the current
  implementation/measurement design; remaining SPEC dependencies are explicit.
- [Programme data model](programme_data_model.md): concrete logical grains, durable
  identity and release keys, source/evidence relations, accounting scopes and
  metric populations. This develops the target contract without changing the
  shared physical schema.
- [Processing architecture](programme_processing_architecture.md): P00-P10 stage
  contracts, tool/field ownership, correction order, matching inputs, checkpoint
  invalidation and separate data/delivery acceptance.
- [Physical design](programme_physical_architecture.md) and [implementation plan](programme_implementation_plan.md):
  artifact/registry layout, checkpoint/adoption protocol, three preparation and
  eleven engineering packages, verification and execution controls. Runtime,
  calibrated gate and resource limits are not certified by these documents.
- [F01-F12 rule/validation resolutions](programme_conflict_resolution.md) and
  [saved-input contract assessment](programme_contract_assessment_2026-09-09.md),
  added later on 2026-09-09. Include concrete writer order, correction-instance
  scopes/dispositions, seven bounded packet boundaries, 910 obligation slots and
  thirteen measured quarter profiles. Full population rule replay and independent
  reference-based accuracy remain outstanding.
- [Rule-authority assessment](programme_rule_authority_assessment_2026-09-09.md):
  77 families, 740 assets, 14 control inputs and ten isolated runtime cases.
  Separates loader eligibility from application and source correctness, with
  demonstrated ordering/admission/audit/wrapper/cache/artifact behavior. Full
  rule-instance certification and source-unit/FX coverage remain open.
- [Reference and eligibility assessment](programme_reference_and_eligibility.md):
  910 source-backed status records (811 eligible, 98 pre-investment, one unresolved),
  existing source/identity benchmark inventory, 61 calibration clusters and
  development source examples. Independent labels and numerical calibration
  remain open; the pilot is not a completed acceptance benchmark.
- [Accuracy investigation](../investigations/data_quality_audits.md): distinguishes
  source-value verification from position completeness, meaning and release gates.
- [Production stack plan](production_data_stack_plan.md),
  [Parquet plan](phase1_parquet_migration_plan.md) and
  [dbt spike](dbt_spike_report.md). Accepted decision D13 permits necessary
  agent integration/control fixes while preserving proposal, verification and
  promotion roles; this supersedes the earlier unchanged-subsystem restriction
  for that bounded scope. A broader workflow redesign is outside the programme.
- [Existing schema reference](../reference/schemas.md),
  [physical schemas](../../pipeline/output_schemas.py),
  [column contracts](../../pipeline/column_validation.py), wrappers, grammars,
  promoted correction stores, provenance and source reconciliation.
- Existing active baseline, source-labelled gold, matching gold, regression tests
  and signed-quarter attestations. Record exactly what each tests; neither a
  snapshot nor a matching benchmark proves every holding field is correct.
- [Enforcement registry](../../data/overrides/enforcement_registry/README.md)
  and [live policy](../../data/overrides/enforcement_registry/governance_policy.md).
  Distinguish active gates from dormant scaffolding and advisory checks.

Current operational instructions remain in AGENTS.md and the latest changelog.
Re-read them at session start. Do not treat historical document status as current
without checking runtime wiring and newer entries.

## 3. Scope and authority

### Fixed boundaries

- Public v1: position-level holdings and permitted analytics for the active
  unlisted-BDC wrapper cohort. No index product or non-BDC scope expansion.
- Preserve shared non-BDC behaviour unless an explicitly approved change needs it.
- Cached sources only. No SEC downloads, baseline refresh, production replacement
  or fleet dispatch as a side effect of preparation.
- Preserve user changes. Record the dirty-worktree state; do not manufacture a
  clean starting point by reverting or deleting work.
- Unknown disclosure is valid. Do not make all fields mandatory or invent data.
- Keep subsidiary rows under the current retain-and-flag contract; do not resume
  paused publication policy changes without owner direction.

### Proposed ownership to formalize before execution

| Kind of decision | Owner / control |
|---|---|
| Financial meaning, scope, acceptable publication risk | Owner-approved financial contract |
| Implementation decomposition and integration | Lead agent under that contract |
| Filer-specific interpretation | Versioned per-CIK configuration with evidence |
| Exceptional correction | Reviewed proposal through the existing promotion route |
| Expected outputs and acceptance thresholds | Versioned acceptance assets; not editable by correction workers |
| Public release and baseline refresh | Existing owner-governed release process |

Workers may propose contract changes but cannot create new authorities or silently
change success criteria. The lead agent must escalate unresolved meaning rather
than settle it through implementation order.

## 4. Preparation work packages

These are planning tasks for the lead agent. Outputs should extend the existing
documents/stores where appropriate, rather than automatically create new systems.

| ID | Deliverable | Dependencies | Acceptance evidence |
|---|---|---|---|
| P0 | Reproducible assessment manifest | None | Code revision and local changes, cohort, input/config identities, artifact timestamps, active baseline and current validation vintages recorded; mismatched vintages identified |
| P1 | Active-rule and authority inventory | P0 | Every production rule-loading path located; active rules indexed with scope, fields changed, execution order, evidence and consumer; unknowns explicit |
| P2 | Financial decision sheet and authoritative-home map | Existing crosswalk + P1 | F01-F12 each mapped to existing decision, proposed resolution or owner question; no competing definition left implicit |
| P3 | Acceptance-test and benchmark map | P1 + P2 | Each proposed change has source-backed expectations, legitimate counterexamples, held-out cases, applicable metrics and untouched-behaviour checks |
| P4 | Ordered implementation packets and migration design | P1-P3 | Each packet has one accountable owner, bounded scope, dependencies, allowed files, expected semantic delta, tests, rollback and escalation conditions |
| P5 | Operational launch review | P0-P4 | Isolation, persistence, fleet limits, integration/release ownership and unresolved owner choices documented; readiness verdict states ready or not ready with reasons |

P1 now has a family-level source register, live-loader counts and ten bounded
runtime observations. A complete instance-level mapping of active rules, units,
selector overlaps and population effects is not certified. Reuse the saved
register; finish population replay after bounded WP-01 isolation is available.
P2 recommendations can be drafted alongside P1; approval is needed only where
meaning or authority is genuinely undecided, not for every engineering detail.

### P1 rule record

For each active rule or rule family, record:

- Stable reference to its current file and loader; version/content identity.
- Global versus per-CIK scope, effective filing/period regime and input conditions.
- Fields read and written, rows added/removed/merged, execution stage and precedence.
- Source evidence, related regression cases and live validation consumers.
- Overlap with other rules; whether the overlap is intended, redundant or conflicting.
- Proposed disposition: retain, relocate, replace, retire or investigate.
- Proposed authoritative home and compatibility obligations.

Inventory extraction wrappers, identifier grammars, HTML/iXBRL enrichment, rate
conventions, manual row corrections, B2/promoted rules, metadata/classification
caches and global special cases. Classify retired/proposed stores separately;
the presence of a JSON file does not establish that production executes it.

### P2 accepted decisions and authoritative-home mapping

The [programme decision sheet](programme_decision_sheet.md) maps all F01-F12
findings to retained contracts, implementation corrections and accepted owner
decisions. All thirteen D01-D13 decisions are resolved as of 2026-09-09, including
the recommended options for previously uncommented items. The crosswalk now has
a target extension, an exhaustive field disposition map and related-record
contracts. Initial field-family authority and delta mapping is complete; P2 still
depends on active-rule precedence and the bounded SPEC-FX/SPEC-ID details before
implementation readiness can be established.

| Decision group | Accepted basis and remaining specification work |
|---|---|
| Rate meaning (F01) | All-in target with separate PIK and no missing-rate inference. Specify representation and an atomic migration with income consumers. |
| Monetary values and denominators (F02-F04) | Preserve reported cost/zero; use first observed FV as a labeled missing-cost proxy. Assume USD unless otherwise stated, with explicit evidence status. Retain portfolio-weight display and separate NAV meanings. Specify donor eligibility and FX source/date. |
| Evidence and optional terms (F07-F09) | Retain month-end for month/year maturity with source precision; preserve unknown stress states and source wording. Prioritize HTML/iXBRL citations; PDF is deferrable. Specify evidence fields and viewer integration. |
| Authority and release population (F05/F10/F11) | Map authoritative schemas and final validation boundaries. Retain records, public sums and separate accounting populations; ownership-adjusted look-through analytics are not required. Define/baseline metrics before final numerical-gate approval; existing live policy remains in force. |
| History and identity (F06/F12) | Latest-best history with versioned releases; no as-known-at-cutoff product. Stable within-filer position and cross-filer borrower/company identities remain required; group concentration is optional. Core history is XBRL-focused with measured gaps and existing recovery paths. Specify lifecycle, revision and join contracts. |
| Engineering scope | dbt migration is accepted; preserve agent proposal/verification/promotion roles and fix required integration, persistence and control gaps under D13. Select concrete authoritative homes and migration boundaries. |

Use the recorded decisions to complete the field and relationship contracts.
The lead agent selects internal SQL structure and directory names within that
scope. Present only newly discovered material policy ambiguities or the final
calibrated numerical gate for owner decision; do not reopen resolved choices.

### P3 acceptance design

The [measurement register](programme_measurement_register.md) now specifies all
28 criteria, formulas/populations, provisional versus exact targets, dated
starting evidence, reusable evaluators and result artifacts. SPEC-REF and
SPEC-GATE cover remaining independent references, executable checks, measured
baselines and numerical calibration. A documented metric is not an executed check.

Keep these separate:

1. Source fidelity: value and transform agree with the cited filing facts/text.
2. Position roster: eligible positions are accounted for without unsupported
   merging, duplication or unexplained exclusion. Some complete schedules must
   be checked, including apparently passing funds, not only flagged rows.
3. Economic meaning: cash/PIK, original/USD principal, reported/proxy cost and
   denominators satisfy the approved definitions.
4. Regression: unaffected CIKs/quarters and consumers retain expected behaviour.
5. Release: the applicable quarter contract and provenance requirements are met.

Reuse current gold and baseline assets, recording uncovered areas. Missing tests
become explicit tasks. Include same-issuer different-facility cases, equivalent
dimension representations, zero-cost positions and legitimate missing disclosures.
Workers cannot edit their own held-out expectations or lower thresholds.

Existing FAILs must stay visible. A structural migration can establish parity
while pre-existing data issues remain; that is not release acceptance. Intentional
corrections require explained deltas, not forced equality to a wrong baseline.

### P4 implementation packet template

Every packet must specify:

- Objective and referenced contract/decision versions.
- Defect mechanism or transformation boundary, CIKs and periods in scope.
- Dependencies and incompatible concurrent work.
- Allowed code/config paths and isolated trial-output location.
- Existing rules to reuse, supersede or retire; no silent parallel authority.
- Source examples, counterexamples and expected before/after effects.
- Required tests, semantic comparisons, affected consumer checks and re-attestation.
- Success, failure and escalation criteria; rollback and completion evidence.

Candidate ordering after preparation: boundary/source-accounting checks, currency
unit resolution, atomic rate semantics, reported/proxy cost, PIK evidence, then
other approved F01-F12 work. Order by demonstrated dependencies and impact, not
by this provisional list. Framework migration is a distinct packet, not mixed
into an unrelated financial correction. Parallelize independent investigations;
serialize overlapping semantics and shared-output integration.

## 5. Long-running execution controls to establish

- One lead integrator and persistent task/decision ledger. At each checkpoint,
  record accepted changes, remaining work, evidence paths and the next safe action.
- Controlled starting tree/input snapshot and isolated trial outputs. Accepted
  production data and baselines remain protected throughout experimentation.
- One owner for shared rebuilds, integration and release. Check for concurrent
  long-running jobs; do not launch duplicate full suites or rebuilds.
- Fleet dispatch only after authorization and the applicable operator skill and
  dispatch documentation are read. Existing ADMIN PowerShell and MaxParallel=2
  fleet constraints remain binding; this document does not launch or bypass them.
- Runtime/cost budget, checkpoint frequency and stop conditions agreed before
  long-running execution. Do not promise one uninterrupted session.
- Escalate ambiguous financial meaning, unavailable evidence, unexplained
  regressions, out-of-scope changes or required new authority. A blocked packet
  does not justify weakening its acceptance test.
- Retirement plan for old paths and adapters; avoid maintaining two competing
  normalization engines indefinitely.

## 6. Launch checklist and current status

- [x] Existing column crosswalk and bounded availability/accuracy evidence located.
- [x] Preparation sequence and next-agent entry point recorded in this document.
- [x] All thirteen owner choices resolved; first target mapping covers all 88 existing fields and required relationships.
- [x] All 28 criteria mapped to measurement definitions, existing check families and explicit evidence gaps.
- [x] P0 assessment identity: 653 input hashes/stats plus HEAD/local status pinned for the bounded saved-artifact assessment; this is not yet an isolated restorable implementation snapshot.
- [x] F01-F12 traced to current writers, validation, consumers and concrete target resolutions; existing incompatible tests identified.
- [ ] P1: complete active-rule/precedence inventory.
- [x] P1 preparation: source-traced authority/asset/control inventory and ten runtime replays recorded; defects incorporated into WP-01/02/03/07. No production repair or full cohort replay claimed.
- [ ] P2: validate initial authoritative-home map against active-rule precedence; finish SPEC-FX/SPEC-ID dependencies.
- [x] P2 design preparation: logical data model drafted with explicit keys, relationships, evidence and release invariants. Persistent-ID migration and runtime enforcement remain unproved.
- [ ] P3: implement/validate missing measurement checks, freeze independent reference coverage and establish baselines for final numerical calibration.
- [x] P3 preparation: historical eligibility assessment and benchmark reuse/exposure inventory recorded; source calibration frame pinned. Fortress ambiguity resolved: 812 eligible, 98 pre-investment; independent review remains open.
- [x] P3 first pilot: isolated source/field/legacy-label comparisons executed, two development rosters reviewed and a numerical gate proposal drafted. This is reference-limited evidence, not a complete acceptance baseline.
- [ ] P4: instantiate the implementation package records with frozen source fixtures, reviewed limits and tested isolated runtime; calibrated acceptance is required for programme remediation.
- [x] P4 design preparation: processing architecture and PA-01 through PA-06 migration sequence drafted, mapped to CR packets.
- [x] P4 physical/package preparation: artifact and registry layout, manifest/checkpoint/adoption mechanics, PREP-01 through PREP-03 and WP-01 through WP-11 drafted. Measurements, runtime proofs and owner-set total execution limits remain outstanding.
- [ ] P5: execution environment, authority and readiness reviewed.

Readiness is NOT yet established. This document creates the preparation backlog;
it does not claim that the financial contract, rule inventory or launch controls
are complete. Preparation ends with a short owner decision pack and a ready/not
ready verdict, not a request to micromanage each worker.

## 7. Next-agent entry instruction

Start with the dated conflict resolution and assessment after reading current
AGENTS.md and the latest changelog. Reuse the saved P0 assessment identity; make
an isolated restorable starting snapshot before implementation. Continue P1 from
the [authority assessment and retained replays](programme_rule_authority_assessment_2026-09-09.md):
finish source-unit/FX needs and rule-instance records, then measure full selector
interactions once WP-01 isolation is available. Complete the independently
adjudicated reference/obligation frame.
For measurement work, continue from the [executed pilot and numerical proposal](programme_measurement_pilot_2026-09-09.md):
complete reference adjudication and primary accounting bases, prepare the
Aurelia/Sentinel label corrections for their governed review, add independent
sector/identity reference coverage, and specify a synchronized isolated candidate.
Use the remaining 59 source packets and explicit blocked metrics to finish D12
calibration. Do not restart the completed eligibility/benchmark inventory or
represent old-label/tag-copy agreement as source accuracy.
Reuse the existing crosswalk, accepted decision sheet, target contract and
measurement register. Logical, processing and [physical architecture](programme_physical_architecture.md)
are now drafted; use the [implementation plan](programme_implementation_plan.md)
to complete PREP-01/02 and prepare bounded WP-01 isolation/evaluator and citation
prototype work before PREP-03 calibration. Instantiate fixtures and measured
runtime budgets before dispatch. Do not begin a broad rewrite, migrate to dbt,
dispatch a fleet, alter financial semantics, replace production outputs or refresh
the baseline merely because this preparation plan exists. Present any newly
discovered material policy ambiguities and the calibrated numerical gate with
evidence-backed recommendations; D01-D13 are already resolved.

## 8. Preparation closeout and current entry point, 2026-09-09

The [closeout pack](programme_spec_closeout_2026-09-09.md) supersedes the next-action instructions in sections 6-7. N01-N09 have delivered their declared preparation outputs: technical conventions, all 61 source-packet dispositions, four complete development rosters, twenty source-label proposals, a frozen/restorable candidate, full B2 population accounting, synchronized identity/PIK consumers, durable-ID and citation proofs, numerical recommendations and a bounded execution offer.

**Ready for owner review; not a production-ready data release.** The proposed gate returns `FAIL_WITH_UNASSESSED_ITEMS`. Forty-eight full source rosters remain uncertified and eight primary sources unavailable. Independent sector accuracy, whole-population identity accuracy and complete source-selected life histories are not established. Explicit dispositions close preparation tasks; they do not close those accuracy obligations.

| Earlier preparation track | Current status |
|---|---|
| P1 rules/units | Authority inventory plus full B2 application/order replay and document-scoped currency investigation delivered. Global/wrapper/Layer-C interaction certification belongs to implementation. |
| P2 authoritative homes | Logical/processing/physical designs and units/FX/identity contract delivered; actual durable-ID migration example tested. Production migration and final runtime enforcement remain. |
| P3 measurements/reference | Synchronized baseline, exposed mg3 regression and numerical evaluator/proposal delivered. Complete independent references and all 28 production evaluators remain. |
| P4 execution preparation | Isolated build/consumer stages, restore and failure proofs, measured resource limits and concrete first tranche delivered. The preparation adapter is not an OS sandbox. |
| P5 launch decision | Numerical recommendations remain amendable working targets. The first bounded tranche stopped incomplete. Section 12 is owner-accepted and sections 13-15 complete the specification for final review. Runtime/measurement/recovery proofs remain open; no new execution window is opened here. |

The current entry point is [specification status](programme_spec_status.md), then the [latest implementation handoff](programme_tranche_handoff_2026-09-10.md). The original eight-hour tranche has ended; its T1 labels do not replace master WP-02. Instantiate the next bounded runtime/reference/evaluator packet using the completed measurement-register sections 12-15 and validate dependencies before reusing candidate stages. Keep financial failures and reference gaps explicit. Broad dbt/schema migration follows its prerequisites; do not restart completed inventories or reinterpret development labels as held-out evidence. This reading guide does not open another execution window.
