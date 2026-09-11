# Programme review: responses and amendments

10 September 2026. Based on the [saved owner comments](programme_review_comments.md), saved at 08:32:34 UTC. The comments are preserved unchanged. This record clarifies the specification; it does not change measured results, production data or live thresholds.

## FX: what was tested on real data?

Two different things were done. Real cached filings were inspected to establish the meaning of monetary fields and expose incorrect currency tags. For example, a printed GBP principal amount was tagged EGP, while other filings reported foreign principal alongside USD cost and fair value. These are actual source cases.

The new conversion function was tested with synthetic exchange rates. Those tests cover conversion direction, same-date cross rates, weekend selection, no future-rate use, zero/negative values, missing or stale rates and ambiguous observations. No historical market-rate dataset was imported, and there was no end-to-end test joining real filing amounts to real historical rates.

“Import and version real FX observations” means save the historical provider quotes with their dates and source identities, then use that fixed snapshot to check independently calculated conversions for real, currency-resolved filing observations. This integration proof remains required before deploying the FX conversion path. A changed provider quote should create a new recorded version so an old result can still be reproduced.

## Sector coverage: an enrichment issue?

Yes, primarily. The measured 72.98% coverage asks whether holdings already in the dataset have a valid GICS sector assignment, weighted by absolute fair value. This belongs to the classification/enrichment workstream, separately from extracting the loan or its amount.

Missing coverage may reflect an absent classification, an identity/cache match failure or an invalid code. It does not automatically require another LLM call. Reuse supported classifications, repair mappings where justified, and infer missing assignments with visible evidence and uncertainty.

Coverage and accuracy remain separate: filling more codes improves availability, but independent reference decisions are needed to establish whether the codes are correct. Holdings missing from the dataset are a separate source-coverage problem and are not measured by this enrichment percentage.

## Metrics: useful starting targets, open to amendment

The owner supports the metrics as working targets and expects them to evolve when confronted with real data. The proposed numbers remain unchanged for now. They are not permanently fixed, and the current data has not been accepted.

The amendment process is:

1. Record the real source case or measurement limitation that motivates a change. Distinguish a pipeline defect, a reference error, an applicability issue and an unsuitable requirement.
2. Describe the revised definition, population, tolerance or target and the quality tradeoff. Preserve the old version.
3. Evaluate old and revised rules on the same candidate where possible. Show affected rows, fair value, unresolved exposure and verdict changes; identify comparisons that cannot be made reliably.
4. Record the adopted version, reason and effective scope. Ordinary evaluator/reference corrections can proceed within authorized work. Material changes to acceptable error, product scope or already accepted exact requirements return to the owner with that evidence.
5. Keep each candidate evaluation pinned to its chosen version. An amendment produces a new evaluation; it does not rewrite earlier results or silently turn missing evidence into a pass.

This permits evidence-backed calibration during implementation. Merely obtaining a passing result is not a sufficient reason to change a requirement. The initial working targets do not replace the existing live quarter gate, authorize production publication or start a new execution tranche.

## Document changes

The [HTML briefing](programme_briefing.html), [closeout](programme_spec_closeout_2026-09-09.md), [units/FX contract](programme_units_fx_identity_contract.md), [measurement register](programme_measurement_register.md), [execution tranche](programme_execution_tranche_2026-09-09.md) and [readiness plan](consolidation_readiness_plan.md) now incorporate these clarifications. The measurements and archived proposal/results under the 9 September evidence bundle remain unchanged. Its document hashes describe the earlier versions, not this subsequent review revision.

The remaining package-level decisions concern starting the execution tranche and reference-review authority. There is no need to ask again whether the numerical recommendations are a useful starting point.
