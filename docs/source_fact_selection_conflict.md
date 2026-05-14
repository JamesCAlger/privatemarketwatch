# Source Fact Selection Conflict

A source fact selection conflict occurs when a filing contains multiple raw facts
that appear to describe the same economic position, but the unified holdings
pipeline keeps the blank or less informative fact.

This is different from subtotal leakage. Subtotal leakage is an aggregate or
category row surviving as a position. Source fact selection conflict is a
selection/deduplication problem among position-like source facts.

Example: Saratoga Investment Corp. / ETU Holdings, Inc. for `2025-02-28`.

The unified row kept:

- `ETU Holdings, Inc. - Corporate Education Software - Series A Preferred Units`
- fair value: blank
- cost: `3000000.0`
- principal amount: `3000000.0`

The raw BDC evidence also contained a related fact:

- `Affiliate investments - 7.5% - ETU Holdings, Inc. - Corporate Education Software - Series A Preferred Units`
- fair value: `1162040.0`
- cost: `3000000.0`
- principal amount: `3000000.0`

This is not evidence of duplicate preferred-unit positions in unified holdings.
It is evidence that raw source facts can contain competing variants of the same
apparent position, and the unified output may select the blank variant.

This issue can be reviewed alongside subtotal-leakage WARN labels because both
require source-row inspection and normalized identifier comparison. It should
not be fixed only by expanding subtotal filters. The required measurement is:

- missing-FV unified rows with same-filing raw candidates that have nonblank FV;
- whether candidate rows share issuer, security label, cost, principal amount,
  and report/accession identity;
- whether the nonblank candidate is a true position, not a borrower subtotal or
  category aggregate.

Until this category is measured separately, C101 failures may overstate pure
source-missing-value cases and understate extraction/selection errors.
