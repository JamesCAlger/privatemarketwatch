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

**Status: IMPLEMENTED (2026-06-01)**

The oracle now has a full promotion lifecycle:

```
candidate wrapper -> trial run -> oracle checks + baseline comparison -> promote / reject / review_required
```

**Implemented components:**

### `evaluate_promotion_gate(current_summary, baseline_comparison)`

Compares absolute oracle thresholds from the current oracle summary and relative improvements from the baseline comparison (produced by `build_baseline_comparison`).

**Three verdicts:**
- `"promote"` -- no regressions, oracle passes, blocking metrics improve or hold
- `"reject"` -- blocking rows/FV increased, or hard-reject oracle fail reasons
- `"review_required"` -- coverage regressions, per-quarter blocking regressions, or soft oracle fail reasons

**Hard reject triggers** (`_PROMOTION_REJECT_REASONS`):
- `wrapper_blockers_remaining` -- wrappers created new blockers
- `wrapper_no_archetypes` -- structural issue

**Review triggers** (`_PROMOTION_REVIEW_REASONS`):
- `unclassified_rate_exceeded`, `unclassified_fv_rate_exceeded`
- `unclassified_rate_qoq_jump`, `content_signatures_fail`
- `unparsed_remainder_rows`

**Relative checks (from baseline comparison):**
- Total blocking rows delta > 0 -> reject
- Total blocking FV delta > 0 -> reject
- Per-quarter blocking rows regression -> review
- Cleared rollups increase -> logged as improvement

**Output:** `PromotionVerdict` dataclass with `status`, `blocking_rows_delta`, `blocking_fv_delta`, `reasons`, `improvements`, and `per_quarter` DataFrame.

### `validate_wrapper_definition_structure(wrapper)`

Validates structural correctness of a `WrapperDefinition`:
- At least one archetype defined
- Each archetype has keywords
- No duplicate keywords across archetypes
- Numeric range field signatures have min < max
- Valid constraint values

### `run_promotion_trial(cik, output_dir, fresh_bdc_staging)`

Convenience function that orchestrates the full promotion flow:
1. Runs `run_wrapper_oracle_trial` with `compare_baseline=True`
2. Validates wrapper definition structure
3. Evaluates promotion gate
4. Writes `promotion_comparison.csv` and `promotion_verdict.json`

### CLI: `--promotion-gate`

```
python -m pipeline.bdc_xbrl_wrapper_oracle --cik 0001918712 --promotion-gate
python -m pipeline.bdc_xbrl_wrapper_oracle --all-supported --promotion-gate --fail-on-oracle-fail
```

**Tests added (14):** `test_promotion_gate_promotes_when_blocking_rows_decrease`, `test_promotion_gate_rejects_when_blocking_rows_increase`, `test_promotion_gate_rejects_when_blocking_fv_increases`, `test_promotion_gate_review_when_unclassified_rate_exceeded`, `test_promotion_gate_review_on_per_quarter_regression`, `test_promotion_gate_promotes_without_baseline`, `test_promotion_gate_rejects_on_empty_summary`, `test_promotion_gate_rejects_on_wrapper_blockers`, `test_promotion_gate_per_quarter_columns`, `test_validate_structure_passes_clean_wrapper`, `test_validate_structure_flags_no_archetypes`, `test_validate_structure_flags_keyword_overlap`, `test_validate_structure_flags_invalid_numeric_range`, `test_validate_structure_flags_empty_keywords`.

**Not yet implemented:**
- Cross-CIK regression check (does a wrapper change for CIK A increase blockers in CIK B)
- Position-level semantics preservation (requires comparing position key sets from reconciliation detail)

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
