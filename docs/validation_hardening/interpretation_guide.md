# Validation Interpretation Guide

Validation output is evidence for triage, not proof that the data is correct.

## Severity, Status, And Evidence

Severity describes the potential impact of a rule if it fires. `FAIL` rules protect data contracts that should block publication or require explicit review. `WARN` rules identify plausible defects or weak signals that need triage but may include legitimate filing behavior.

Status describes the current run result. `PASS` means the rule found no current findings. `WARN` means findings exist for a warning rule. `FAIL` means findings exist for a promoted failure rule. `SKIP` and `SKIPPED` are the same display state: the rule did not run because an input was missing, a dependency failed, or execution could not complete. Existing CSV schemas may still store `SKIPPED`.

Evidence strength describes how independently a finding is supported. Source reconciliation, GAV or total-assets reconciliation, and cross-output referential checks are stronger evidence than null-rate checks, generic anomaly scores, or internal-only trend movement.

## Frontend Quality Tiers

`VERIFIED` means current validation found no blocking row-level issues for that slice of data.

`VALIDATED_WITH_WARNINGS` means no promoted failure is present, but warnings or known residuals remain and should be visible to users.

`UNDER_REVIEW` means a promoted failure, unresolved source mismatch, skipped critical dependency, or other material ambiguity remains.

These tiers are publication metadata. They should not be upgraded by suppressing failed checks without evidence and a documented mechanism.

## Triage Order

Investigate promoted `FAIL` rules first, especially referential-integrity and source-reconciliation failures.

Next review `REGRESSION` trend flags, then findings with the largest affected fair value.

After that, look for repeated CIK-quarter clusters across rules because they often indicate one filing-specific mechanism.

Finally, review weak or chronic warnings. Chronic warnings are useful backlog signals, but they should not crowd out new regressions or high-FV failures.

## Trend Limits

Trend improvements are triage aids, not correctness evidence. A lower hit count can come from missing inputs, skipped dependencies, filtering changes, or incomplete extraction. Treat `IMPROVING` as a prompt to verify the mechanism, not as a reason to publish.

`REGRESSION` means hit count increased by more than 50%, affected fair value increased by more than 25%, or a prior zero became positive. `CHRONIC` means a non-pass status has appeared in at least four consecutive runs. `NEW` means no prior comparable run exists. `STABLE` means none of these thresholds fired.

## Known Residuals

Known residuals should be documented without suppressing or reclassifying failures. If a rule is noisy for a specific CIK-quarter, record the source evidence, mechanism, metric impact, confidence, and residual risk before adding any override.

Weak signals such as generic percentage ranges, null-fill rates, or anomaly scores are useful flags. They are not validation gates unless tied to an independent source or a deterministic reconciliation contract.
