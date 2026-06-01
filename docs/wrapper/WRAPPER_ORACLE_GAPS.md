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

**Status: IMPLEMENTED (2026-06-01)**

The wrappers reason over identifier strings. But XBRL failures often come from changes in concepts, axes, members, or dimension paths.

**Implemented (`_detect_concept_drift` in oracle harness):**

- Collects the set of unique `concept_names` values per CIK-quarter from reconciliation detail
- Compares adjacent quarters chronologically using churn rate: `|symmetric_difference| / |union|`
- Flags `"yes"` only when churn rate >= 30% (`_CONCEPT_DRIFT_CHURN_THRESHOLD = 0.30`), `"no"` otherwise
- Normal BDC portfolio turnover (adding/removing a few positions) changes a small fraction of concepts and does not trigger the flag; structural taxonomy changes (new axes, reorganized dimensions) affect many concepts and do trigger it
- Only populated for the second quarter onward (first quarter has no prior reference)

**New oracle summary column:** `concept_drift_flag` ("yes"/"no"/"").

**Oracle integration:** When `concept_drift_flag == "yes"`, oracle adds reason `concept_drift_detected` and sets `oracle_status = "fail"`. This is a review reason in the promotion gate (not a hard reject).

**Scope limitations (not yet implemented):**
- Does not track axes or members separately from concept names
- Does not track dimension path shapes
- Does not detect duplicate facts from new dimension paths

**Tests added:** `test_oracle_flags_concept_drift`, `test_oracle_no_concept_drift_when_stable`, `test_oracle_no_concept_drift_when_churn_below_threshold`.

---

## Gap 4: Scale Handling Not Anchored

**Status: IMPLEMENTED (2026-06-01)**

Current scale handling is partly inferred through staging/reconciliation behavior. The oracle now explicitly validates rate scale and cost/FV relative sanity.

**Implemented checks:**

### `_check_rate_outliers(holdings_df, wrapper, report_date)`

Counts holdings rows with `interest_rate` outside the wrapper's `rate_sanity` bounds (`min_pct`, `max_pct`). Only fires when the wrapper definition includes a `rate_sanity` invariant. Oracle reason: `rate_outliers_detected`.

### `_check_cost_fv_outliers(holdings_df, report_date)`

Counts holdings rows where `abs(cost / fair_value)` exceeds 100x or falls below 0.01x. These extreme ratios indicate likely scale mismatches or parsing errors. Oracle reason: `cost_fv_ratio_outliers`.

**New oracle summary columns:** `rate_outlier_count`, `cost_fv_ratio_outlier_count`.

**Configuration:** `RateSanity.min_pct` and `RateSanity.max_pct` in wrapper definition JSON (`invariants.rate_sanity`). Default bounds: 1%-25%.

**Scope limitations (not yet implemented):**
- XBRL decimals or unit metadata validation
- Fund-level `investments_at_fair_value` as independent dollar-scale anchor (partially covered by FV reconciliation in Gap 2)

**Tests added:** `test_oracle_flags_rate_outliers`, `test_oracle_flags_cost_fv_ratio_outliers`, `test_oracle_no_rate_outliers_when_within_bounds`.

---

## Gap 5: unparsed_remainder Is Mostly Aspirational

**Status: IMPLEMENTED (2026-06-01)**

The wrapper schema has `wrapper_unparsed_remainder`, and the oracle checks whether it is non-empty. The oracle now also computes a per-quarter rate and detects QoQ spikes.

**Implemented:**

- `unparsed_remainder_rate` -- fraction of wrapper-processed rows that have non-empty `unparsed_remainder`, computed as `unparsed_rows / wrapper_total_rows`
- QoQ spike detection: when `unparsed_remainder_rate` jumps > 10pp vs prior quarter, oracle adds reason `unparsed_remainder_spike`. Threshold: `_UNPARSED_REMAINDER_QOQ_SPIKE_THRESHOLD = 0.10`.

**New oracle summary column:** `unparsed_remainder_rate`.

**Oracle integration:** The `unparsed_remainder_rows` reason (existing) fires when any rows have unparsed remainder. The `unparsed_remainder_spike` reason (new) fires on QoQ rate jumps exceeding the threshold. Both are review reasons in the promotion gate.

**Scope limitations:**
- Does not attempt to parse identifiers into fields or localize drift
- Rate is a blunt measure -- premature to gate on until more CIKs have full-parser wrappers

**Tests added:** `test_oracle_flags_unparsed_remainder_spike`.

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
- `unparsed_remainder_rows`, `unparsed_remainder_spike`
- `exclusion_risk_detected`, `low_position_continuity`
- `rate_outliers_detected`, `cost_fv_ratio_outliers`
- `concept_drift_detected`

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

**Status: IMPLEMENTED (2026-06-01)**

Excluding rows is dangerous because false positives directly delete data. Aggregate and non-private-market classifications are useful, but need stronger checks.

**Implemented (`_check_exclusion_risk` in oracle harness):**

Scans rows with `aggregate` or `non_private_market` wrapper disposition for position-evidence keywords that suggest the row might be a real position rather than a subtotal or non-private-market instrument.

**Position-evidence keywords checked** (`_EXCLUSION_POSITION_EVIDENCE_TOKENS`):
`type of investment`, `investment type`, `maturity date`, `interest rate`, `reference rate`, `current coupon`, `first lien`, `1st lien`, `second lien`, `term loan`, `revolving credit facility`, `delayed draw`.

When any excluded row's identifier matches these keywords:
- `exclusion_risk_count` -- number of risky excluded rows
- `exclusion_risk_fv` -- sum of |fair_value| across risky excluded rows
- Oracle reason: `exclusion_risk_detected`

**New oracle summary columns:** `exclusion_risk_count`, `exclusion_risk_fv`.

**Oracle integration:** Review reason in promotion gate (not hard reject). The check is intentionally conservative: it flags exclusions that contain any position-evidence language, even if the row is probably a legitimate aggregate.

**Scope limitations (not yet implemented):**
- Arithmetic tie-out of aggregate rows to child rows
- FV-weighted gating for excluded rows (flag when excluded FV > X% of total)
- Sampling-based exclusion validation in tests

**Tests added:** `test_oracle_flags_exclusion_risk_when_position_evidence_found`, `test_oracle_no_exclusion_risk_for_clean_exclusions`.

---

## Gap 8: Limited Cross-Quarter Position Continuity

**Status: IMPLEMENTED (2026-06-01)**

Current QoQ checks include count bands and some stability checks, but do not track actual position continuity. BDC portfolios evolve but do not usually churn randomly quarter to quarter.

**Implemented (`_compute_position_continuity` in oracle harness):**

- Filters to leaf position rows (`source_wrapper_disposition` ending in `_position_leaf`)
- Collects the set of non-empty `source_wrapper_position_key` values per quarter
- Compares adjacent quarters chronologically
- Computes `continuation_rate = |continuing_keys| / |prior_keys|`
- Only populated for the second quarter onward

**New oracle summary column:** `position_continuation_rate` (0.0-1.0, or "" for first quarter).

**Oracle integration:** When `position_continuation_rate < 0.50` (50%), oracle adds reason `low_position_continuity` and sets `oracle_status = "fail"`. Threshold: `_POSITION_CONTINUITY_MIN_RATE = 0.50`. This is a review reason in the promotion gate (not hard reject).

**Scope limitations (not yet implemented):**
- Changed fair values on continuing positions
- Fuzzy position matching (this is a separate pipeline concern)
- New/exited position detail in oracle summary

**Tests added:** `test_oracle_flags_low_position_continuity`, `test_oracle_no_continuity_flag_when_rate_high`.

---

## Implementation Summary

All 8 gaps are implemented. Total: **42 tests** across the oracle test file.

| Gap | Status | Oracle Columns Added | Oracle Reasons Added | Tests |
|---|---|---|---|---|
| #1 Coverage gates | IMPLEMENTED | 4 | 3 | 4 |
| #2 FV-weighted coverage | IMPLEMENTED | 0 (in content sig engine) | 1 | 4 |
| #3 Concept drift | IMPLEMENTED | 1 | 1 | 2 |
| #4 Scale validation | IMPLEMENTED | 2 | 2 | 3 |
| #5 unparsed_remainder | IMPLEMENTED | 1 | 1 | 1 |
| #6 Promotion gate | IMPLEMENTED | 0 (separate columns) | 0 | 14 |
| #7 Exclusion risk | IMPLEMENTED | 2 | 1 | 2 |
| #8 Position continuity | IMPLEMENTED | 1 | 1 | 2 |

**Remaining scope not yet implemented (documented per gap):**
- Gap 3: Axis/member tracking, dimension path shapes, duplicate fact detection
- Gap 4: XBRL decimals/unit metadata, fund-level FV as independent dollar-scale anchor
- Gap 5: Full identifier field parsing, drift localization
- Gap 6: Cross-CIK regression check, position-level semantics preservation
- Gap 7: Arithmetic tie-out of aggregates, FV-weighted exclusion gating
- Gap 8: FV changes on continuing positions, fuzzy position matching
