# Programme specification: current status

11 September 2026. **Specification completion draft ready for final review.** The owner accepted the roster/field procedure in measurement-register section 12 as-is and asked to continue finalising the specification. Sections 13-15 now supply the remaining identity/enrichment evidence rules, all-criterion evaluator coverage and worker/interface compatibility definitions. Their additions have not yet received separate owner sign-off. D01-D13 and the amendable working numerical targets remain unchanged. The [consistency review](programme_spec_consistency_review_2026-09-10.md) records how the identified design gaps were addressed and what still requires implementation proof.

This page reconciles the documents and records the owner's direction to use automated source verification without a mandatory human-labelled gold set. It changes no financial policy, numerical target or execution authorization. Dated measurements, failed attempts and earlier approval records retain their original meaning.

## Current review and handoff

| Area | Specification status | Implementation status |
|---|---|---|
| Roster, field values and comparable totals | [Section 12](programme_measurement_register.md#12-first-draft-automated-position-and-field-verification) accepted by owner, including its seven assumptions. | Independent complete-schedule admission/scoped measurement not implemented. |
| Identity, continuity, GICS and evidence | [Section 13](programme_measurement_register.md#13-identity-enrichment-and-evidence-verification) defines positive/negative/unresolved evidence and counterexamples. | Production durable identities, source-based recall/full chains, independent sector references and evidence delivery remain incomplete. |
| Acceptance coverage | [Section 14](programme_measurement_register.md#14-complete-requirement-to-check-contract) maps all 28 outcomes, including fields, weights, quarters, fund floors, missingness and zero/N/A cases. | Versioned observation/reference schemas, trusted collectors and complete expected-result aggregation required. |
| Rules, workers and interfaces | [Section 15](programme_measurement_register.md#15-worker-rule-and-interface-compatibility) maps 15 route families and F01-F12 to coupled changes and proofs. | Runtime instance inventory/adapters, migration/replay and final writer enforcement required. |

The next engineering work is bounded runtime readiness and the reference/evaluator integration defined in PREP-02/03 and WP-11, coordinated with WP-02/03/05/07. Preserve the current handoff's failed/stopped verification evidence. This specification task starts no new implementation window, workers, source calls, deployment or reference promotion.

Remaining execution parameters are fixture/source hashes, schema serialization, statistically sufficient sample sizes, resource limits and the concrete product workload/budgets. They must be fixed before their associated runs or product acceptance. They are not invitations to change financial meaning or silently relax targets. Reference uncertainty remains an admissible non-pass outcome.

## Resume after shutdown: agreed starting point, 10 September

Historical handoff, superseded for task entry by the 11 September review table above. The owner asked to save this position and prepare for shutdown; no implementation run was active or newly authorized by that handoff.

**Already defined at design level:** target schema and data model, processing/physical architecture, product scope, financial conventions, working numerical targets and the implementation plan. Do not restart those decisions or interpret this note as final acceptance of the whole specification.

**Three specification gaps were recorded at shutdown; sections 12-15 now define their design responses:**

1. **Automated verification rules:** for amounts, position completeness, entity links, position continuity and GICS, specify sufficient evidence, the checks that establish it, and treatment of conflicting or missing evidence. Reuse B1/B2/B3 and include errors outside the flagged-error queue. No mandatory human-labelled gold set or human reviewer appointment.
2. **Compatibility with existing behavior:** finish the mapping of rules, worker instructions and interfaces that stay, change or retire. Identify producer/consumer changes that must land together, including subsidiary retention, ambiguity routing and atomic rate/income migration. Reuse the existing conflict assessments.
3. **Requirement-to-check coverage:** connect every requirement to its check, evidence and pass/fail treatment; identify existing, incomplete and absent checks. Preserve per-quarter/per-fund requirements. The overall-only evaluator is an implementation gap, not permission to weaken quarterly acceptance.

The agreed sequence started with "did we capture the right positions?" and "did we capture their values correctly?", then identity, enrichment and downstream analytics. That definition work is now in the existing measurement register. Roster completeness/purity remains separate from field accuracy.

Building dbt models, migrating identities, completing real FX integration, repairing the evaluator and running full validation remain subsequent implementation/proof work. They do not all have to finish before the spec can be finalized. Document/link checks do not establish source correctness or product acceptance.

At handoff, no pipeline/test/rebuild Python or DuckDB processes were found in the process inspection. The existing Codex CLI Node process was left running. No task-owned background jobs were launched. Files are saved in the existing worktree; no commit, operating-system shutdown, reference promotion or new execution window was performed.

## Three different completion states

- **Specification ready for approval:** the required behaviour, design, acceptance definitions and implementation responsibilities are specified. A known implementation gap does not make the design undecided.
- **Implementation package complete:** that package's promised code, measurements and verification are delivered. A package can preserve a known financial failure where its contract explicitly permits that result. The first eight-hour package is incomplete.
- **Product ready for approval:** the exact candidate and delivery pass all mandatory requirements, or carry only exceptions expressly permitted by the agreed contract. Unmeasured mandatory metrics are not passes. Publication is a separate action.

## Automated reference verification: no human-label prerequisite

Owner direction, 10 September: the B1/B2 approach is intended to avoid a human-labelled gold set. The previous recommendation to appoint a human reference reviewer, including a bounded manual sample, is superseded. Independent evidence is required; human authorship or approval of each reference is not. There is no remaining mandatory reviewer appointment.

The target is an automated evidence-admission protocol, operated separately from correction authors. It must substantiate each claim from pinned sources and deterministic checks. A different agent name, a second model agreeing, or a signed JSON file alone does not establish correctness. Existing human-labelled assets remain optional regression evidence with their actual provenance and development exposure; they are not a prerequisite for future acceptance.

### Existing B1/B2/B3 foundation and its limits

The [B1 contract](../adjudication_architecture/B1_adjudication_contract.md) requires raw-source grounding and separates real errors, false alarms and ambiguity. B1 is blinded to the pipeline's diagnosis. The [B2 contract](../adjudication_architecture/B2_remediation_contract.md) requires a bounded correction, re-grounded in source. [B3's gate](../../pipeline/agent_b_held_out.py) evaluates supported deterministic checks across target and held-out quarters. B2 cannot declare its own correction passed.

These mechanisms already support automated investigation and verification. They are not a complete population-accuracy evaluator: B1 starts from flagged items, blinding to a diagnosis is not a fresh source-only benchmark, and matching fund totals can hide offsetting missing and duplicate positions. The current [source-cell verifier](../../pipeline/source_anchor_verify.py) also shares the evidence CLI's HTML parser. Its replay and witness checks are useful, but do not independently eliminate that parser's errors.

Older B1 instructions route source-checked ambiguity to a human. For the target programme, replace routine human routing with bounded automated investigation and a retained unresolved outcome. Live worker contracts and promotion controls must be adapted and verified in their implementation package; this specification does not change their current execution permissions.

### Required automated workflow

1. **Build source references separately.** Freeze original filing identities and source-only packets before candidate comparison. Recover complete schedules, footnotes, units, periods and accounting scope; retain section boundaries and totals so omissions are detectable. Use structured facts and an independently implemented document-reading path where available. Record shared-parser/model dependencies and disagreements; neither a raw tag nor a printed total is automatically correct.
2. **Investigate and propose.** B1 diagnoses discrepancies from source; B2 proposes scoped corrections with mechanism, citations and counterexamples. Corrections, references and gate definitions have separate write authority. If source evidence challenges a reference, request a separately verified, versioned amendment; the correction author cannot edit the reference to pass.
3. **Verify automatically.** Re-resolve citations and check the claimed row, field, units, date and accounting scope. Reconcile both individual positions and totals; test legitimate rows that a correction must preserve, other quarters and signed-quarter regressions. An independent source-grounded challenge can test semantic assumptions; deterministic checks decide only the assertions they actually cover.
4. **Measure outside the error queue.** Run inexpensive checks over the full population and source-selected automated audits of apparently passing and missing-output schedules. For sampled population estimates, predeclare selection probabilities, strata, independent clusters and appropriate confidence bounds. Keep targeted investigations separate. Complete schedules measure omissions; distinct entity decisions and position chains measure identity. Repeated rows are not independent observations.
5. **Admit evidence or retain uncertainty.** A versioned verification controller admits only evidence satisfying that claim's requirements. Missing sources, conflicting interpretations and failed checks trigger bounded further investigation, then an explicit unresolved record. Unresolved cases remain in assessability and exposure reporting. Apply the existing acceptance floors; if mandatory evidence remains insufficient, the candidate cannot pass. This does not create a mandatory human-labelling queue.

Before execution, the work packet must instantiate sections 12-15 with source/sample scope, admission predicates, access boundaries, independent checks, sample-size/cluster calculations where needed, time/compute limits and retry/stopping rules. Source references and verification results are reusable by content identity; changed sources, rules or reference decisions invalidate affected results. Owner involvement concerns financial policy, material changes to accepted risk and release approval, rather than routine reference labelling.

### What the measurements may claim

Reported values can be checked against source cells with meaning and units verified. Derived values can be checked against their inputs and formula. Default and proxy values retain those evidence categories rather than masquerading as reported facts.

Entity resolution, position continuity and inferred GICS require evidence about identity or business activity, including competing interpretations. They may be automatically adjudicated, but a checked citation or model consensus alone does not prove the conclusion. Inferred GICS remains inferred even when independently challenged. Report source-supported decisions, unresolved exposure and automated agreement separately. Do not rename agreement or consistency as the existing 99.5% identity accuracy or 95% sector accuracy target.

Sampling bounds address sampling uncertainty, not a shared systematic error in reference generation. Accuracy claims must state their reference basis and its limitations. Where available evidence cannot support a mandatory accuracy claim, retain UNASSESSABLE while improving automated verification. Any proposed change to the metric's meaning follows the existing versioned amendment process; targets are not silently weakened to make a human-free workflow pass.

### Implementation gap, not an owner appointment

The current [working contract](../../pipeline/programme/contracts/working-v1.json) still has `reference_review_authority: null`. The [evaluator](../../pipeline/programme/measurement.py) checks a named reviewer, distinct author, source/payload hashes and an attestation; it does not require that actor to be human. It also does not yet enforce the automated admission protocol above. Merely inserting an agent name would satisfy an identity field without supplying the missing assurance.

PREP-02/PREP-03 and the WP-11 evaluator contribution must implement a versioned automated authority and claim-specific evidence checks, with rejection cases for unsupported conclusions, shared-parser-only evidence, reference tampering and development exposure presented as held-out evidence. References must retain separate evidence basis, verification status, admissible claim and unresolved reasons; no automated work is marked `human_confirmed`. Existing schemas/working targets and sealed reference proposals stay unchanged until that implementation is tested and versioned. No reference is promoted by this document.

Owner comment: [Comments on automated reference verification.]

## Ambiguities resolved in this closeout

**Status and authority.** Older paragraphs called the programme "preparing", requested an already-run pilot, or said no programme execution had occurred. Preparation and the first implementation attempt did occur; the implementation package is incomplete and the product unaccepted. The earlier readiness claim was withdrawn on 10 September. The 11 September final-review draft instead rests on the explicit gap-to-definition mapping above; it does not retroactively certify the earlier claim or establish production correctness. Historical observations remain dated evidence.

**Work-package names.** Master WP-02 means "one rule plan, field contract and final writer". The first tranche reused WP-02 for reference/measurement work. That tranche delivered parts of PREP-02/PREP-03 and the WP-11 evaluation framework, alongside WP-01. It did not deliver the master WP-02 rule-authority consolidation. Master package IDs remain unchanged; the tranche now uses T1 labels and an explicit crosswalk.

**Numerical requirements.** Older register rows still describe sector coverage, chain completeness, citation coverage and assessability floors as awaiting proposals. The subsequent numerical proposal and 10 September owner response supply the current working targets, recorded in `working-v1`. Earlier placeholders do not reopen those choices or grant additional tolerances. Future material changes need the already-agreed amendment process. Baseline measurements and final calibration are implementation work.

**Persistent-ID allocation.** The physical design described allocation from a source anchor, whereas the later units/identity contract uses an immutable creation decision with identity kind and scope. Use the later decision-based convention. Source anchors support that decision; they are not recomputed into the identity whenever chain membership changes. The migration must pin serialization and namespace fixtures before admitting IDs. The preparation allocator remains a prototype, and production IDs remain unchanged.

**Stage status spelling.** Processing and physical documents used different spellings for the same states. The target stage contract uses execution `pending/running/complete/failed/interrupted` and quality `not_evaluated/pass/fail/unassessable`. Metric verdicts such as `UNMEASURED` and `UNASSESSABLE` are a separate result vocabulary. This is document alignment, not a rewrite of existing run records or a completed runtime migration.

**What remains under SPEC-FX/ID/RULES/REF/VIEW/GATE.** These identifiers now track implementation proofs and reference completion. The FX provider/date/fallback convention, identity convention and citation priority are already specified. Source-specific uncertainty must still be investigated; an ambiguous source is not permission to invent a value.

## What is already decided

The target remains the 70-BDC cohort, Q1-2023 through Q1-2026, position-level holdings and permitted analytics, with latest-best historical data and reproducible releases. There is no public index or non-BDC expansion in this programme.

The existing decisions cover first-observed-FV as a labeled missing-cost proxy, USD default absent contrary evidence, source-aware maturity precision, borrower/entity versus position identity, sector-level GICS with separate inferred evidence, and HTML/iXBRL citation priority. PDF highlighting is deferrable. A future history extension or material change of financial meaning requires an explicit scope/version decision.

## Where each definition lives

- [Decision sheet](programme_decision_sheet.md): accepted financial/product policies D01-D13.
- [Target contract](programme_target_contract.md) and [units/FX/identity contract](programme_units_fx_identity_contract.md): field meaning, currency/date conventions and allocation policy. The later specific convention controls an older contradictory design example.
- [Data model](programme_data_model.md), [processing architecture](programme_processing_architecture.md) and [physical design](programme_physical_architecture.md): grains, relationships, stages, storage and checkpoints.
- [Measurement register](programme_measurement_register.md): populations, formulas, assessability and result requirements. Its latest owner-review section controls earlier numerical approval wording; the automated reference protocol above controls reviewer requirements.
- [Working numerical contract](../../pipeline/programme/contracts/working-v1.json) and [owner-review response](programme_review_response_2026-09-10.md): current working numbers and amendment rules. The live quarter gate is separate.
- [Implementation plan](programme_implementation_plan.md): stable WP-01 through WP-11 definitions and dependencies.
- [First-tranche handoff](programme_tranche_handoff_2026-09-10.md) and [subsequent investigation](programme_verification_investigation_2026-09-10.md): executed work and verification limits. These are not evidence that the target architecture is deployed.

## Next work

Review the new sections 13-15 against the accepted section 12, then use the stable implementation packages and compatibility records to execute the design. No new product/financial policy decision was identified in this scoped completion review. In the execution sequence, finish bounded runtime readiness, implement the necessary reference/evaluator controls, then measure the candidate where dependencies validate and implement substantive migration packages. The regex-validator repair, full-suite native protection and verification, recovery drill, real FX integration, automated reference admission, scoped evaluation, dbt migration and production source navigation remain unfinished. They do not reopen D01-D13.

This closeout ran document/link and consistency checks only. It did not start another test suite, build, reference promotion, download or implementation tranche. The owner's original saved comments remain unchanged.
