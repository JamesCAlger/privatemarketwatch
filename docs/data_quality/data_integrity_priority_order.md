# Data Integrity Priority Order

This document summarizes the recommended priority order for data integrity work in the private markets index pipeline. The ordering follows the validation approach used elsewhere in the project: anchor correctness to independent source evidence first, then expose uncertainty clearly in public outputs, and only then use agent-assisted correction loops on bounded residuals.

## 1. Full Source Reconciliation By CIK-Quarter

Build or strengthen deterministic reconciliation between pipeline holdings and cached source filing facts for each CIK-quarter.

Focus areas:

- Match source XBRL facts to `private_markets_holdings.csv` rows.
- Identify missing source positions, extra pipeline rows, and numeric mismatches.
- Preserve accession, report date, period, and dimension-path lineage.
- Treat this as the strongest validation layer because it compares output to data the pipeline did not generate.

This should be the first priority because it answers the core integrity questions: are all real source positions present, are false rows excluded, and do key numeric fields match the filing?

## 2. GAV / Fund-Level Reconciliation

Keep fund-level reconciliation beside source reconciliation, not after cleanup work. It provides an independent aggregate anchor even when row-level data looks plausible.

Focus areas:

- Compare holdings fair value to reported investments at fair value where available.
- Fall back carefully to total assets only when the denominator scope is clear.
- Track reconciliation by CIK-quarter and source type.
- Distinguish true undercoverage from intentionally non-indexable holdings.

GAV reconciliation is especially valuable because it catches material silent errors in aggregate exposure, including subtotal leakage, duplicate dimension paths, and missing extraction coverage.

## 3. Position Purity: Subtotals, Duplicate Dimensions, Comparative Periods

Use reconciliation failures to drive cleanup of position-level purity issues.

Focus areas:

- Prevent subtotal, category-header, and aggregate rows from entering position-level holdings.
- Detect duplicate facts caused by multiple XBRL dimension paths.
- Preserve legitimate comparative-period facts instead of deleting them as duplicates.
- Confirm `period`, `report_date`, accession, and dimension path before removing rows.

Do not solve this by endlessly expanding global keyword filters. New filters or dedup rules should be tied to a demonstrated mechanism and checked for false positives across other CIKs.

## 4. Classification And Fund-Strategy Validation

Validate classification using independent fund-level signals, not only holdings-level keywords.

Focus areas:

- Cross-check fund strategy against holdings mix.
- Reconcile strategy labels to N-CEN, prospectus language, or other source evidence.
- Validate asset-class, exposure-type, and index-classification consistency.
- Review classification overrides that affect material portfolio weight.

This catches errors where the holdings are internally consistent but assigned to the wrong public bucket, such as a real estate strategy being classified as private equity.

## 5. Coverage, Freshness, Exclusions, And Public Quality Tiers

Make public uncertainty explicit before expanding frontend claims.

Focus areas:

- Track filing freshness and stale CIKs.
- Separate intentional exclusions from extraction failures.
- Report source coverage, missing quarters, and known limitations.
- Export quality tiers such as verified, preliminary, under review, and stale.

This layer does not make the data correct by itself, but it prevents public charts and fund pages from implying precision that validation does not support.

## 6. Entity Resolution And Position Matching

Improve entity and position identity after the underlying holdings and classifications are validated.

Focus areas:

- Increase entity ID coverage, especially for N-PORT.
- Reduce false merges and name-normalization collisions.
- Preserve position-level semantics when building borrower-level exposure analytics.
- Validate position matching used for return construction and company pages.

Entity resolution is important for exposure views, but it should not override the index's position-level grain.

## 7. Rate / Yield Sanity

Validate rates and yield analytics as a focused integrity layer for credit analytics and income returns.

Focus areas:

- Detect rate scale ambiguity across decimal, percentage, and basis-point inputs.
- Check floating-rate spread, reference-rate, coupon-type, and all-in-rate consistency.
- Compare coupon-derived income to fund-level income where available.
- Treat weak internal checks as flags unless corroborated by independent evidence.

Rate/yield validation is important, but most checks are weaker than source and GAV reconciliation because they often depend on inferred economics rather than direct source matching.

## 8. Audited Per-CIK Corrections And Agent Loops

Use per-CIK corrections and agents only after the validation gates are strong enough to constrain the work.

Focus areas:

- Store filer-specific corrections in audited configuration, not growing global rule lists.
- Require mechanism, source evidence, confidence, before/after metrics, and residual risk.
- Assign agents only to validation residuals with bounded CIK-quarter scope.
- Keep validation independent from the correction author.

Agents should be subroutines inside the deterministic pipeline. They should not become autonomous owners of truth or satisfy weak metrics by suppressing ambiguity.

## Operating Principle

The correct sequence is not "clean code first" or "frontend polish first." The correct sequence is to make data wrongness measurable, tie fixes to source evidence, and expose remaining uncertainty clearly. Refactoring should follow the validation contract, not precede it.
