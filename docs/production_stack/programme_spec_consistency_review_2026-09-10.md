# Programme specification consistency review

Initial review: 10 September 2026. Updated 11 September: the identified specification gaps now have concrete design responses in measurement-register sections 12-15. The completion draft is ready for final review; implementation and financial verification remain incomplete.

The owner accepted [section 12](programme_measurement_register.md#12-first-draft-automated-position-and-field-verification) as-is and requested completion. [Section 13](programme_measurement_register.md#13-identity-enrichment-and-evidence-verification) adds identity, chain, sector and derivation evidence; [section 14](programme_measurement_register.md#14-complete-requirement-to-check-contract) supplies the result contract and all 28 criterion mappings; [section 15](programme_measurement_register.md#15-worker-rule-and-interface-compatibility) maps 15 route families to coupled producer/consumer changes and counterexamples. New sections remain completion proposals for final review, not inferred owner approval or executed verification.

The owner challenged the mandatory human-reference review and the reliability of the specification. That challenge is justified by an identifiable process failure: an engineering recommendation became a supposed owner-level prerequisite without being traced to an accepted decision. The subsequent proposal for a smaller human sample changed the workload but retained the same unsupported prerequisite.

The earlier readiness declaration was withdrawn on 10 September. The completion status above is based on the explicit responses below and does not retroactively validate that earlier claim. Accepted product decisions remain in force; this review does not restart implementation.

## What was checked

Compared the D01-D13 decision map and accepted outcome requirements with the target contract, relevant data-model and processing sections, current reference/measurement governance and implementation status. Traced the agent claims into the B1/B2 contracts, B2/B3 build plan, current source-cell verifier and programme evaluator. Reviewed the existing conflict/rule-authority findings to distinguish already-recorded defects from newly identified gaps.

The 11 September follow-up inspected entity/continuation packet generation and scorers, GICS mapping/validation, Agent A/B1/B2 contracts, anchor/convention/investigation routes, the programme catalog/evaluator/schemas, accepted outcome matrix and existing architecture/rule traces. It found specific source-shortlist, undecidable-score, taxonomy-versus-business and scoped-observation gaps reflected below. Every criterion now names its population, check, missing proof and owner.

This is a targeted document-and-code inspection, not an exhaustive runtime instance audit or certification that every implementation is correct. Historical HTML briefings and frozen evidence remain dated; the status page/register are the current entry points. No tests, rebuilds, reference adjudication or financial measurements ran. Link/fence checks establish document integrity only.

## CR-01: Unsupported mandatory human review

**Finding:** the status page and task-entry documents made a reference-reviewer appointment a prerequisite. The owner's intended B1/B2 workflow and latest explicit instruction require automated source verification without a mandatory human-labelled gold set. Independent evidence does not imply human labelling.

**Evidence:** [D13 and the accepted decisions](programme_decision_sheet.md), [B1 adjudication](../adjudication_architecture/B1_adjudication_contract.md), [B2 remediation](../adjudication_architecture/B2_remediation_contract.md), and [B2/B3's deterministic gate design](../adjudication_architecture/B2_B3_build_plan.md). Historical agent documents do include human escalation and gold-calibration references; they needed a compatibility decision, not an assumption that a new human benchmark was required.

**Disposition:** corrected the active status, measurement, reference, target, processing and execution guidance. The [automated reference protocol](programme_spec_status.md#automated-reference-verification-no-human-label-prerequisite) supersedes the previous human-review recommendation. Existing labels retain their provenance; no automated labels become `human_confirmed`.

**Remaining:** implement claim-specific automated admission and its versioned schema/evaluator integration. No owner appointment is required.

## CR-02: Independence needs a concrete evidence mechanism

**Finding:** names such as "independent reviewer", "B3" and "source-verified" do not by themselves establish a reference's correctness. B1 diagnoses flagged cases; a flag queue misses unflagged errors and absent output. B1's blinding to the pipeline's diagnosis does not prove a benchmark was prepared without candidate exposure. The existing [source-cell verifier](../../pipeline/source_anchor_verify.py) explicitly reuses the evidence CLI's parser. Replaying the same parse can preserve the same mistake. Matching aggregate totals can hide offsetting omissions and additions.

**Disposition:** the revised protocol requires source-selected audits, complete-schedule evidence for omission claims, explicit parser/model dependencies, separate correction/reference/gate write authority and retained disagreement. Automated agreement is reported as agreement. Accuracy claims state their reference basis; sampling bounds do not eliminate systematic reference error. GICS inference remains inference.

**11 September design response:** sections 12-13 specify AV/ID/PC/EN predicates, positive/negative and unresolved outcomes, source-selected frames and permitted claims. Section 14 specifies reference fields/admission for all reference-dependent claims, including lifecycle, anchors and citations missing from the current `REFERENCE_REQUIRED` set. Source interpretation remains a stated evidence dependency; model agreement is never promoted into a correctness metric. Schema/admission and independently generated reference populations remain implementation proof, not an undefined reviewer appointment.

## CR-03: Existing worker contracts need explicit target compatibility

**Finding:** the target correctly preserves roles, but "reuse the existing route" must not imply that every current instruction already matches the accepted target. B1 still sends source-checked ambiguity to a human. The B2 contract's historical SPV guidance includes dropping parent/underlying rows, while D08 and the live retain-and-flag contract require retained records with separate accounting populations. These are specific migration boundaries.

**Evidence:** [B1](../adjudication_architecture/B1_adjudication_contract.md), [B2](../adjudication_architecture/B2_remediation_contract.md), [D08/D13](programme_decision_sheet.md) and the [existing F01-F12 resolution](programme_conflict_resolution.md). The earlier rule assessment already documented production/verifier ordering and admission defects; these are not twelve newly discovered owner decisions.

**Disposition:** active processing guidance explicitly requires compatibility updates before using the programme's automated route. Preserve the established proposal, deterministic verification and promotion responsibilities. Unresolved routine data cases receive bounded investigation and an unresolved outcome rather than a mandatory human-labelling task. Financial-policy changes and release approval remain owner decisions.

**11 September design response:** CP-01 through CP-15 in section 15 identify retained roles, incompatible behavior, producer/validator/executor/scorer changes, counterexamples and implementation owners. This includes the investigation route's human-review fallback, source-only continuation endpoints, GICS subject/level admission, final-writer boundaries and Agent A's lane-specific dispatch contract. Each runtime instance must receive that compatibility record; an unclassified enabled writer blocks implementation completion. Existing prompts/corrections/permissions remain unchanged until their coupled implementation packet lands.

## CR-04: Quarter-level acceptance is not implemented

**Finding:** [outcome acceptance section 2](programme_acceptance_draft.md#2-how-acceptance-works) requires results for each required quarter as well as overall. In [evaluate_metric](../../pipeline/programme/measurement.py), any observation with a non-null `quarter` is returned as UNASSESSABLE; only the overall programme scope is admitted. The schema/framework therefore cannot currently supply the required per-quarter acceptance route. An overall score is insufficient evidence that each quarter passes.

**Disposition:** recorded in the measurement register and implementation obligations. This is an implementation defect against an existing requirement, not a new owner policy choice. All earlier unmeasured results remain unmeasured; no existing pass is invented or rescored.

**11 September design response:** section 14 defines the expected-observation manifest, candidate/claim/field/quarter/fund/population/weighting identity, trustworthy measurement evidence, N/A/zero handling and non-pass aggregation. All 28 criteria map to existing metric IDs and missing implementation proofs. Current dictionary-by-metric and `quarter: null` restrictions must migrate together with observation/reference/result schemas; merely admitting a non-null quarter would still lose field/fund results. Mixed-pass, missing-quarter, zero-population and historical-regression cases are required implementation proof.

## Document-level alignment found

The following accepted decisions remain represented in the target design. This finding concerns the documented requirements, not whether the current pipeline implements them:

- **D01-D04:** missing rates remain unavailable; all-in migration includes consumers; first-observed-FV is a labelled missing-cost proxy with reported zero preserved; USD default is distinguished from source evidence; reported NAV percentages and portfolio weights remain distinct. See [target field families](programme_target_contract.md#2-field-family-contract) and [cost donor rules](programme_data_model.md#first-observed-fv-cost-proxy).
- **D05-D08:** latest-best history, source-aware maturity precision, distinct borrower and position identity, retained subsidiary records and separate accounting populations. See the [decision map](programme_decision_sheet.md#2-review-map), [identity model](programme_data_model.md#5-entity-and-position-relations) and [accounting model](programme_data_model.md#6-accounting-scope-and-reconciliation). CR-03 identifies the worker compatibility gap rather than a change to these decisions.
- **D09-D11:** sector required, deeper GICS optional; inferred evidence separate; HTML/iXBRL citation priority with PDF deferrable; XBRL-focused history with measured gaps. See [enrichment](programme_data_model.md#inferred-gics-sector), [citation model](programme_data_model.md#8-metrics-populations-and-click-through) and the decision map.
- **D12-D13:** numerical working targets use the accepted amendment process; agent proposal/verification/promotion roles remain. See [measurement amendments](programme_measurement_register.md#11-owner-review-and-amendable-working-targets-2026-09-10) and [processing roles](programme_processing_architecture.md#6-agent-and-enrichment-work). CR-01 through CR-04 qualify the governance and executable coverage.
- **Product boundary:** position-level 70-BDC holdings and analytics, Q1-2023 through Q1-2026, no public indices or non-BDC expansion, exact public sums from the same retained holdings. These remain stated requirements. Readiness for owner approval and actual publication remain separate.

## Completion assessment and limits

CR-01's unsupported human prerequisite is removed from the active design. CR-02/03/04 now have concrete specification responses and declared implementation obligations. D01-D13 and numerical working targets are preserved; section 12's owner acceptance is recorded without extending it to the new text. The resulting specification can guide bounded implementation and is ready for final review.

This assessment does not prove all runtime rules are compatible, enough independent source evidence exists to meet the targets, or a practical sample/budget has been demonstrated. Those named proofs belong to the implementation packages. General product interaction budgets beyond the accepted citation ceiling remain a measured delivery parameter. Any newly discovered material policy conflict follows the existing amendment process. No passing product, new reference admission, final numerical calibration or new execution window is claimed.

Owner comment: [Comments on these findings or their priority.]
