# 01 Decisions: scope, financial policy and owner rulings

Consolidated 2026-09-12 from the September 9-11 programme documents. This is the only place financial policy and product scope are defined. The other four documents derive from it: [data contract](02_data_contract.md), [pipeline design](03_pipeline_design.md), [acceptance](04_acceptance.md), [plan](05_plan.md). Superseded documents were deleted; git history retains them. Evidence bundles under `programme_*_evidence_*/` and `current_state_evidence_2026-09-09.json` are unchanged.

## 1. Product scope

**Bounded resumption, 2026-09-15.** The owner authorized one agent for a 12-hour refactor closeout, starting with V10/V11 tracking and retaining the completed data repairs. It ends with an isolated, verified integration candidate and an honest report. Numerical threshold calibration is deferred until later operational agent work supplies feedback; it is not a prerequisite for refactor completion. No remediation fleets, dbt migration, production adoption, publication or baseline refresh are authorized by this run.

**Register/cash implementation, 2026-09-15.** The approved v3 population is 804 eligible and 106 excluded obligations (98 lifecycle, 8 no-primary-reporting), with 25 eligible zero-output cases. E3 must audit both exclusion classes using their respective evidence requirements; a reporting exclusion does not claim the fund was not investing. For Golub Private Credit Q2-2023, a complete primary-quarter inventory with no positions or unresolved contexts and a positive cash-equivalent balance permits `eligible_no_position_facts`. Its wording is "No portfolio positions disclosed; cash and money-market holdings only." That wording requires cash-only source evidence and must not be applied to every aggregate-only exception. The updates here supersede the older population counts below; numerical gate values remain unchanged.

- Public v1 is position-level holdings and portfolio analytics for the 70-CIK wrapper cohort in `data/overrides/wrapper_cohorts/v2_70_gate_verified_wrapper_manifest.json`.
- Required history is Q1-2023 through Q1-2026 (13 quarters, 910 fund-quarter obligations before eligibility). Q4-2022 opening is optional. Q2-2026 is a lower-priority forward test after Q1-2026 is reproducible.
- Grain is one retained observation per disclosed position or lot per fund per date. Tranches, equity, warrants, facilities and disclosed lots stay separate. Borrower rollups are analytics, never the base table.
- No public indices, no interval or tender-offer funds, no corporate-group concentration product, no ownership-adjusted look-through analytics.
- The current run ends with a verified refactored architecture and an isolated integration candidate with an honest quality report. Production data acceptance, publication, baseline refresh and adoption are later steps.

## 2. Financial and product decisions D01-D13

All thirteen were resolved by the owner on 2026-09-09. Validation obligations for each live in [acceptance](04_acceptance.md).

| ID | Decision | Counterexample that must keep working |
|---|---|---|
| D01 | Missing or ambiguous rates stay blank. No peer-median, implied-benchmark or model rate fills in public holdings or analytics. Income with missing inputs is unavailable, not zero. | 11.49% cash + 2% PIK = 13.49% all-in; a disclosed 13.49% all-in stays 13.49%. |
| D02 | Reported cost wins, including zero. First observed FV of the same established position is an approved, labelled proxy when reported cost is absent. Principal is not a cost substitute. | Two tranches of one borrower cannot donate cost to each other; a zero-FV donor stays zero. |
| D03 | USD unless the source says otherwise. Explicit USD and assumed USD are distinguishable. Known non-USD with no FX stays unresolved; it never reverts to USD. | German borrower with a disclosed USD loan; `U_USD` token resolves to USD without conversion. |
| D04 | Keep the existing `% Portfolio` display. Reported %NAV and calculated FV/NAV are separate fields. | FV 10, portfolio 200, NAV 100 gives 5% portfolio and 10% NAV; leveraged funds can exceed 100% NAV. |
| D05 | Latest-best history with versioned releases. No as-known-at-cutoff product. | An amendment creates a new source-linked revision; the earlier release stays reproducible. |
| D06 | Month/year maturity uses month-end with precision `month`. Exact dates win. Year-only stays partial. Missing stays missing. | `June 2029` gives 2029-06-30 with month precision; a calculated day cannot create a false exact-day match veto. |
| D07 | Resolve the disclosed borrower conservatively. Store group relationships as dated edges, never by merging borrower IDs. | Same name, unrelated borrowers; parent and subsidiary with separate instruments. |
| D08 | Retain cash, JV, subsidiary and underlying records with explicit accounting scope. Public headline is the canonical holdings sum, not a consolidated or look-through total. | Parent 100 plus underlying 200 is not 300 of exposure; ownership is never inferred from a ratio. |
| D09 | GICS sector is the required level. Sub-industry is optional. Unknown stays visible and counts in coverage. | Sector can exist without sub-industry; a sector never invents a child. |
| D10 | Citations use inline-XBRL fact IDs and existing bridge anchors. PDF is deferrable. | A repeated number in a different row is a failed citation, not a near miss. |
| D11 | XBRL-focused history with measured gaps. No additional recovery campaign. Separate confirmed position, aggregate and unresolved contexts. A completely assessed eligible quarter with no confirmed or unresolved position candidates and a positive investment total is a named exception; confirmed positions with no output are extraction failures. | NexPoint Q1-2023 has 39 confirmed position contexts and zero output under the old extractor: extraction failure. A supported aggregate-only instance can be an exception; unresolved contexts cannot. |
| D12 | Define and baseline, then approve numerical gates. Working targets are amendable through the process in section 4. | A passing result is not a reason to change a target. |
| D13 | Preserve agent propose, verify, promote roles. Fix integration and control gaps. No broader workflow redesign. | A worker cannot promote its own output or edit a threshold. |

## 3. Owner rulings after D01-D13

**Refactor completion precedes operational remediation (2026-09-14).** The owner clarified: "this is a refactor run, not a production run" and "the enrichment and B1/B2 can run after the refactor is complete". Implement and verify the architecture through which existing data, wrappers, corrections and enrichment decisions run. Complete the specified collectors, admission/promotion integration, financial contracts, identity, finalization and public access mechanisms. Use isolated cached integration builds, regression tests, repeatability/recovery checks and all-quarter evaluations to verify that implementation. Do not run B1/B2 remediation fleets, anchor-adjudication campaigns or new LLM enrichment to make the current dataset clear publication thresholds during this run.

Refactor completion requires working collectors and controls, accurate PASS/FAIL/UNASSESSABLE results, explained intentional migration changes and no unexplained refactor regressions. Missing collectors, broken evidence wiring, incorrect calculations and failed software contracts remain implementation defects. Genuine missing source evidence, unresolved legacy approval records, pending numerical-floor adoption and below-target enrichment are recorded operational residuals; they do not require a remediation campaign before the refactor can finish. Existing numerical data/delivery gates remain in force for a later production release. No threshold is relaxed and a refactor handoff is not publication approval. Already recorded source-backed changes and prior trial evidence remain preserved.

**Automated verification, no human-labelled gold set (2026-09-10).** Independent evidence is required; human authorship of each reference is not. Existing human labels (source-field tail labels, mg3/mg4/mg5 match gold) are development regression assets with their exposure recorded. No automated result is ever marked `human_confirmed`.

**No HTML reader (2026-09-12).** The spec must not add a second document-reading path, a row enumerator over HTML tables, or template-driven HTML recovery. Reason: parsing HTML to re-check facts already extracted from inline XBRL is a brittle check of extracted data, and the repo has exactly one HTML table parser, so a "second path" would share its defects. Consequences:

- Verification evidence is limited to XBRL contexts, companyfacts fund-level totals, cross-quarter continuity, provenance replay and published-basis invariants. See [acceptance section 2](04_acceptance.md).
- The collector assigns each candidate context exactly one source-backed role: confirmed position (`P`), aggregate (`A`) or unresolved (`U`). Extractor recognition is a separate compatibility flag; supported NexPoint positions remain confirmed even though the extractor misses their explicit `dei:LegalEntityAxis` pattern. For an eligible zero-output quarter, a complete assessment with `P=0`, `U=0` and a positive investment total permits `eligible_no_position_facts`, including aggregate-only instances. `P>0` is an extraction failure; `P=0, U>0` remains unresolved; mixed cases retain both the confirmed failure and unresolved exposure. Missing or incomplete source assessment cannot establish an exception. The collector must pass the NexPoint and aggregate/ambiguous controls in [acceptance section 2](04_acceptance.md) before classifying the 33 eligible zero-output fund-quarters in `programme_pilot_evidence_2026-09-09/obligations_v3.csv` (33 in v2; 25 in v3). Exceptions remain visible in coverage and the review pack; classes are unknown until E1 runs.
- Citation highlighting uses inline fact IDs and the existing HTML-section bridge anchors already produced by extraction. It does not parse HTML at verification time.

**Reference-dependent metrics are monitored, not gating (2026-09-12).** Entity precision and recall, position precision and recall, complete-chain rate and sector accuracy keep their working targets but are scored from exposed regression sets and consistency checks and cannot block a release. See [acceptance section 5](04_acceptance.md).

**Historical coverage is measured against each quarter's eligible population (2026-09-12).** The live `fund_coverage >= 60` floor cannot be met in 2023, when 48 to 59 funds were eligible. It is replaced through the amendment process by a share of eligible funds per quarter, with the denominator taken from `obligations_v3.csv` (v2 until 2026-09-15) only after experiment E3 has audited the 98 exclusions. Confirmed position contexts or a positive investment total contradict an exclusion; unresolved contexts or incomplete source assessment prevent its certification. Aggregate contexts alone do not establish position activity. See [acceptance section 4](04_acceptance.md).

**Field accuracy carries an assessability floor (2026-09-12).** Accuracy is reported only when the assessed share of disclosed values meets a per-field floor set after measurement; below it the field is unassessable. Assessing less cannot raise the score.

**Working numerical targets are amendable (2026-09-10).** The owner's words: "these are good metrics, but should be amendable as they are put in contact with the messy nature of the data." Current values are in `pipeline/programme/contracts/working-v1.json` and reproduced in [acceptance section 6](04_acceptance.md).

**Sector coverage is an enrichment problem (2026-09-10).** Roughly 73% of Q1-2026 cohort FV carries a sector. Of the remaining $103B, about $99B sits on direct-credit rows that already have an entity ID. The fix is classification of existing entities under an explicit budget, not a schema change.

**Joint-borrower identity is precision over recall (2026-09-17).** A source-disclosed co-borrower list ("A, B and C") is its own entity key and never fuzzy-merges with a single member or with another co-borrower list. This removed 10 of 14 entity false merges in the mg3 gold set at the cost of two disagreements retained as open gold packets: IRI Holdings -> Circana rename (MGP-5625e98fbdb8, same instrument by units and cost) and Truck-Lite single vs co-borrower cluster with a "Clarity"/"Clarience" typo variant (MGP-3fb3d33c5cb2). Recovery of these is later operational work (position-level exact shares+cost continuation; typo-tolerant merge between two joint keys sharing the first legal member), not a refactor gate.

## 4. Amendment process for numerical targets

**Execution amendment (2026-09-12).** The owner instructed: "remove the gb and minute cap entirely" and "keep implementing until all evaluations and tests are complete". Active programme experiments, builds and verification no longer impose fixed memory-GB or elapsed-time termination limits. Measured resource usage remains telemetry. Routine implementation/test failures are diagnosed and retried without a fresh approval request for each attempt; package checkpoints remain reviewable while work continues. This supersedes the earlier retry-count and one-package session stops. Source-evidence requirements, data protection, one heavy job, no downloads, genuine semantic-regression stops, and owner authority over publication, baseline refresh and accepted financial risk remain.

1. Record the source case or measurement limitation that motivates the change. Say whether it is a pipeline defect, a reference error, an applicability issue or an unsuitable requirement.
2. State the revised definition, population, tolerance or target and the quality trade-off. Keep the old version.
3. Evaluate old and new on the same candidate where possible. Show affected rows, FV, unresolved exposure and verdict changes.
4. Record the adopted version, reason and scope. Routine evaluator corrections proceed inside authorized work; material changes to accepted risk, scope or exact requirements return to the owner with that evidence.
5. Each candidate evaluation is pinned to one contract version. An amendment creates a new evaluation; it never rewrites an earlier one.

## 5. Who decides what

| Decision kind | Authority |
|---|---|
| Financial meaning, product scope, acceptable publication risk | Owner, through this document |
| Implementation decomposition, table layout, SQL structure, directory names | Lead engineer or lead agent, within this document |
| Filer-specific interpretation | Versioned per-CIK configuration with source evidence |
| Corrections | Existing propose, deterministic verify, promote route; correction authors cannot edit references or thresholds |
| Expected outputs and thresholds | Versioned acceptance assets in `data/reference/`, editable only outside a remediation run |
| Release, baseline refresh, publication | Owner |

## 6. Explicitly not required

- A second HTML or document parser of any kind.
- Runtime content hashing of the Python environment before each stage.
- A Windows low-integrity token sandbox for deterministic builds. Path redirection plus the protected-output inventory is the required control.
- Exact decimal aggregation from persisted CSV tokens. The measured public-total mismatches were population and overlay defects, not floating-point ones.
- A parallel programme evaluator. The live quarter gate is extended instead.
- A human reviewer appointment or manual labelling queue.
- dbt migration before the writer graph is fixed. Arelle adoption. R2 backup as a programme deliverable.

**Continuous execution amendment, 2026-09-16.** The owner instructed "run continuously without a time limit". This supersedes the September15 twelve-hour cutoff. Continue routine implementation diagnosis, repair and required verification without further routine-retry approval. One heavy job, preserved source evidence, protected production data and the refactor/operations boundary remain. Production adoption, publication, baseline refresh, numeric threshold adoption, dbt and remediation/enrichment campaigns are not authorized by this amendment.
