# Wrapper Oracle Gaps

Identified gaps in the BDC XBRL wrapper oracle validation system, with implementation tracking.

**Source files:**
- `pipeline/bdc_xbrl_wrapper_oracle.py` -- oracle harness
- `pipeline/wrapper_content_signatures.py` -- content signature engine
- `tests/test_bdc_xbrl_wrapper_oracle.py` -- test coverage

---

## Gap 1: Coverage Gates Are Incomplete

**Status: IMPLEMENTED (2026-06-01)**

Content-signature validation treats unclassified rows as non-failures. That is reasonable for a diagnostic pass, but unsafe as a promotion gate. Previously, the oracle only surfaced `pass_rate` and `violation_count`, not `unclassified_rate_status`.

**Implemented gates (oracle fails when):**

1. Too many rows match no archetype -- `unclassified_rate` exceeds configured `max_pct` threshold. Oracle reason: `unclassified_rate_exceeded`.
2. Too much fair value sits in unclassified rows -- see Gap 2. Oracle reason: `unclassified_fv_rate_exceeded`.
3. A quarter's unclassified rate jumps > 5pp vs prior quarter. Oracle reason: `unclassified_rate_qoq_jump`. Threshold: `_UNCLASSIFIED_RATE_QOQ_JUMP_THRESHOLD = 0.05`.
4. Wrapper JSON exists but archetypes tuple is empty. Oracle reason: `wrapper_no_archetypes`.

**New oracle summary columns:** `unclassified_rate`, `unclassified_rate_status`, `unclassified_fv_rate`, `unclassified_fv_rate_status`.

**Tests added:** `test_oracle_fails_when_unclassified_rate_exceeded`, `test_oracle_fails_on_qoq_unclassified_rate_jump`, `test_oracle_no_qoq_jump_when_rate_stable`, `test_oracle_fails_when_wrapper_has_no_archetypes`.

---

## Gap 2: No Fair-Value Coverage By Unclassified Rows

**Status: IMPLEMENTED (2026-06-01)**

Row count is not enough. A wrapper could classify 990 small rows and miss 10 large loans, and row coverage would look strong while value coverage is bad.

**Implemented per CIK-quarter (in `validate_content_signatures`):**

- `total_fv` -- sum of |fair_value| for all rows (absolute values to handle negative FV)
- `classified_fv` -- sum of |fair_value| for archetype-classified rows
- `unclassified_fv` -- sum of |fair_value| for unclassified rows
- `unclassified_fv_rate` -- unclassified_fv / total_fv
- `unclassified_fv_rate_status` -- pass/fail against `max_fv_pct` threshold (default 5%)

**Configuration:** `UnclassifiedRate.max_fv_pct` in wrapper definition JSON (`invariants.unclassified_rate.max_fv_pct`). Default 0.05 (5%).

**Oracle integration:** When `unclassified_fv_rate_status == "fail"`, oracle adds reason `unclassified_fv_rate_exceeded` and sets `oracle_status = "fail"`.

**Tests added:** `test_validate_content_signatures_includes_fv_columns`, `test_validate_content_signatures_fv_pass_when_below_threshold`, `test_validate_content_signatures_uses_absolute_fv`, `test_oracle_fails_when_unclassified_fv_rate_exceeded`.

---

## Gap 3: No Concept/Dimension Drift Inventory

**Status: NOT YET IMPLEMENTED**

The wrappers reason over identifier strings. But XBRL failures often come from changes in concepts, axes, members, or dimension paths.

**Required per-CIK inventory:**

- XBRL concepts used for FV, cost, principal, shares, rates
- Axes and members used in holdings contexts
- Dimension path shapes
- New or missing concepts quarter over quarter
- Duplicate facts from new dimension paths

A filer can keep similar identifier text while changing the tagging structure. Reconciliation may still partially work, but duplicate paths, comparative-period paths, or alternate concepts can create silent overcounting or missing rows.

**Priority:** Tier 2 -- useful but expensive to implement. Start narrow: track the set of (concept, axis, member) tuples producing holdings rows per CIK-quarter, flag when the set changes.

---

## Gap 4: Scale Handling Not Anchored

**Status: NOT YET IMPLEMENTED**

Current scale handling is partly inferred through staging/reconciliation behavior. The oracle should explicitly validate scale using independent anchors:

- XBRL decimals or unit metadata where available
- Fund-level `investments_at_fair_value` as FV anchor
- Position FV sum vs fund FV
- Cost/FV relative sanity
- Rate fields separately from dollar fields

Dollar scale and rate scale need different treatment. A rate of 850 may mean 8.50%, 850 bps, or bad parsing. A fair value of 25,000 may mean 25 thousand or 25 million depending on filer scale. The oracle should prefer reconciliation against tagged fund totals over magnitude priors.

---

## Gap 5: unparsed_remainder Is Mostly Aspirational

**Status: NOT YET IMPLEMENTED**

The wrapper schema has `wrapper_unparsed_remainder`, and the oracle checks whether it is non-empty. But most current wrappers are identifier classifiers, not full parsers.

**Required parsing discipline:**

- Split identifier into expected fields
- Map known fields into issuer, instrument, rate, maturity, etc.
- Store any leftover text in `unparsed_remainder`
- Fail or warn if remainder spikes
- Localize drift to the first field where parsing diverged

**Priority:** Premature to gate on until at least 5-10 CIKs have full-parser wrappers. Content-signature field checks (numeric_range, regex, enum) serve as a partial substitute in the meantime.

---

## Gap 6: No Promotion Gate

**Status: NOT YET IMPLEMENTED**

The oracle produces diagnostics but has no hard lifecycle:

```
candidate wrapper -> trial run -> oracle checks -> promote or reject
```

**Required promotion contract (wrapper delta accepted only if):**

- Reduces or explains target residuals
- Does not increase blocking rows elsewhere
- Does not increase unmatched FV
- Does not worsen aggregate leakage
- Does not worsen unclassified row/FV coverage
- Passes content signatures and reconciliation
- Preserves position-level semantics

The gate should compare before/after artifacts, not just look at the final state. Otherwise a bad wrapper can appear to improve one metric by moving the problem into a less visible bucket.

Additionally, the promotion gate should validate that the wrapper definition itself is structurally valid (non-overlapping archetypes, consistent field signatures, valid FV reconciliation config).

---

## Gap 7: Weak False-Positive Protection For Exclusions

**Status: NOT YET IMPLEMENTED**

Excluding rows is dangerous because false positives directly delete data. Aggregate and non-private-market classifications are useful, but need stronger checks.

**Risky false-positive examples:**

- "Cash + PIK" in a loan coupon mistaken for cash
- Category text that also contains a real issuer
- A one-line position with no obvious maturity but real FV
- Fund interests or CLOs misread as non-private-market funds

**Required evidence for exclusions:**

- Aggregate rows should tie arithmetically to child rows where possible
- Non-private-market rows should match narrow vocab and not contain position evidence
- Excluded rows with large FV should be reviewed or separately gated
- Rows classified as aggregate/non-private should be sampled in tests and residual reports

The standard should be stricter for exclusions than for labels. A bad label is noisy; a bad exclusion causes data loss.

---

## Gap 8: Limited Cross-Quarter Position Continuity

**Status: NOT YET IMPLEMENTED**

Current QoQ checks include count bands and some stability checks, but do not track actual position continuity. BDC portfolios evolve but do not usually churn randomly quarter to quarter.

**Required position key comparison across adjacent quarters:**

- Continuing positions (key present in both quarters)
- New positions (key present only in current quarter)
- Exited positions (key present only in prior quarter)
- Changed fair values on continuing positions
- Continuation rate (% of prior positions still present)

**Gate:** Flag CIK-quarters where continuation rate drops below threshold (e.g., < 50%) as potential wrapper regressions. Start with exact-key continuity as a diagnostic signal. Do not build fuzzy position matching into the oracle -- that is a separate pipeline concern.

---

## Implementation Priority

| Priority | Gap | Rationale |
|---|---|---|
| 1 | #2 FV-weighted coverage | Highest impact, straightforward |
| 2 | #1 Coverage gates | Natural companion to #2, uses same data |
| 3 | #6 Promotion gate | Architectural prerequisite for safe iteration |
| 4 | #7 Exclusion false-positive protection | Directly prevents data loss |
| 5 | #4 Scale validation | Important but partially covered by FV reconciliation |
| 6 | #8 Position continuity | Useful diagnostic, start simple |
| 7 | #3 Concept drift | Valuable but expensive, start narrow |
| 8 | #5 unparsed_remainder | Premature until wrapper coverage is broader |
