# Current implementation and evidence

Updated 2026-10-04. Execution remains active until the owner stops it in chat.
Production code, data, queues and gates are untouched. All new implementation is
in `.claude/worktrees/jev-screening-pilot`; nothing below authorizes deployment.

## Measured position

- **67 core development flags, 11 funds, 26 filings.** A separate later-period
  offline arm adds two flags and one filing in an existing fund; both are blocked.
  That makes 69 selected numeric cases, with the core denominator unchanged.
  The cumulative reservation is
  16 BDCs, below v1. No untouched holdout remains.
- **39 evidence-ready; 36 also fit the token proxy cap; 34 are eligible under the
  default C107/X08 policy.** These are prerequisites, not clearance counts.
- **100/100 API calls used**, covering 42 unique natural flags plus separate
  repeats, presentation variants and synthetic controls. No further calls are
  being made. Inference estimate: about $0.0664, excluding investigation costs.
- **Zero independently audited clearances; zero B1 work suppressed.** All 39
  ready cases also satisfy the raw-preserving deterministic comparator. Jev's
  incremental benefit for these numeric rules remains unproved.

The local source-review labels are development references, not independently
audited gold. All called natural references were false alarms; four known natural
errors were blocked before submission. High label agreement therefore does not
estimate missed-error risk.

## What exists

| Component | State and practical limit |
|---|---|
| C107/X08/C104 bundle builder | Working isolated prototype with source, period, identity, units, notes and dependency checks. C104 is an explicit development probe. |
| Router and bounded runner | Shadow only; incomplete evidence, errors, ambiguity and failed checks retain B1. Independent audit is required even for high-confidence false alarms. |
| Source-first review forms | 67 unfinished inputs, version 56. They contain no model answers; preparation does not constitute review. |
| Deterministic comparator | Useful numeric baseline; source agreement does not certify identity, inclusion or complete recall. |
| Disclosure-role/search helpers | Optional and unintegrated. Source issuer columns supply queries for 23 flags; 11 gain navigation rows. Other positions and periods remain distinct. |
| Continuation-header diagnostic | One geometrically plausible CMG case; no inherited headers or readiness promotion. Scope and notes remain unresolved. |
| Proxy lineage, parent inventory, explanations, compaction | Separate bounded tools. They do not authorize proxy adjudication, production queue linkage or deployment. |

## Findings that matter before integration

1. **Parent queue identity is unreliable in the inspected slice.** Timestamp-form
   dates cause blank localization and repeated review IDs across quarters. The
   mechanism is reproduced; no migration or fix was applied.
2. **FV conservation can miss lost fields.** A separate TCW investigation finds
   a rollforward survivor replacing detailed term-loan cost with a proxy, a
   difference of $8,260,552. Three-row/FV audit totals still agree. This was found
   by source investigation, not Jev, and is outside the frozen 67 cases.
3. **More context is not automatically a better bundle.** Full supplementary
   rows add 22.2% to aggregate token proxies and make one more request oversized.
   Compact locators omit evidence needed for adjudication.
4. **B1 answers need their own audit.** Historical groups can be partial, cite
   another period or concern a different holdings snapshot. Recorded historical
   token usage is not a measurement of current avoided work.

## Current records

All artifact names below are relative to
`data/pilot/jev_screening/20261003_shadow/`.

| Purpose | Current record |
|---|---|
| Frozen builder replay | `dependency_bound_v4_55/` |
| Unfinished source-first review | `blind_review_inputs_56/` |
| Readiness funnel | `screening_funnel_aea23f322777be85.json` |
| Complete call accounting | `observation_ledger_5b394e009a35cdb6.json` |
| Deterministic baseline | `current_anchor_profile_e437cc9529e39b9a.json` |
| Supplementary navigation | `disclosure_search_profile_da03743e49495fec.json` |
| Payload comparison | `disclosure_appendix_size_53f8f1a298625f47.json` |
| Header continuation | `header_continuation_probe_972590ca4ffead8e.json` |
| Additional two-case period transfer | `later_period_c104_57/` |
| Later-period missing-note diagnosis | `missing_note_inspection_3cdc76304ddd12df.json` |

The next validation milestone is an independently reviewed, snapshot-bound
comparison of deterministic checks alone against those checks plus Jev on the
same workload, including natural errors and complete parent membership. A 0.75
cutoff remains a trial setting. Current evidence supports further isolated
evaluation, not production suppression.

See the [assessment](06_interim_assessment.md), [remaining bundle work](11_remaining_bundle_work.md)
and [run log](05_run_log.md) for mechanisms, tests and limitations.
