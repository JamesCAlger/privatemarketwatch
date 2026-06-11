# Plan B: Matching Algorithm Hardening

Status: Not started
Depends on: Nothing (can run in parallel with Plan A)
Blocks: Plan C (re-calibration)

## Motivation

The 2026-06-11 calibration found 58 of 112 errors (52%) caused by the matching algorithm itself, independent of wrapper extraction quality. These errors fall into 5 patterns where the algorithm lacks sufficient gates to prevent incorrect matches.

The calibration also measured the precision of existing heuristic flags, giving us ground truth to promote the best flags from informational to hard rejection:

| Flag | Precision (error rate when true) | Volume (flagged matches) |
|------|----------------------------------|--------------------------|
| flag_classification_flip | 100% | 6 |
| flag_maturity_mismatch | 74.6% | 63 |
| flag_rate_discontinuity | 66.7% | 6 |
| flag_fv_ratio_extreme | 62.5% | 8 |
| flag_principal_ratio_extreme | 52.9% | 17 |

## Deliverables

### 1. Hard gates in `position_matching.py`

**Classification flip veto** (tiers B2/C/D/E):
- If `begin_index_classification != end_index_classification`, reject the match.
- Calibrated precision: 100% (6/6 flagged matches were errors).
- Catches: equity matched to debt, DIRECT_LENDING matched to COMMON_EQUITY, etc. (pattern 4).
- Implementation: add a WHERE clause to the match CTE excluding pairs with different classifications.
- False positive risk: minimal. Legitimate classification changes (e.g., reclassification from "other" to "direct lending") are rare and should re-match via a lower tier with correct classification.

**Maturity mismatch veto** (tiers C/D/E only):
- If both sides have non-null maturity dates and the dates differ by >12 months, reject the match.
- Calibrated precision: 74.6% (47/63 flagged matches were errors).
- Catches: refinancings mis-identified as continuity (pattern 5), wrong tranche selections where maturities differ (patterns 3, 6).
- Implementation: add a WHERE clause to C/D/E match CTEs filtering out maturity gaps >365 days.
- Not applied to A/B1b/B2: higher-confidence tiers can tolerate maturity amendments. For B2, the 25% false positive rate is too high given the tier's volume.
- False positive risk: some legitimate maturity extensions (amendments) in C/D/E will be rejected. These positions will fall to unmatched, which is acceptable -- better to break a match chain than link different instruments.

**Instrument sub-type continuity** (all tiers):
- Parse instrument sub-type from `instrument_description`: Revolver, DDTL (Delayed Draw), Term Loan, Equity, Warrant.
- If both sides have a parseable sub-type and they differ, reject the match.
- Catches: revolver matched to term loan, DDTL matched to revolver (pattern 6), equity matched to debt when classification is ambiguous (pattern 4 residual).
- Implementation: add a UDF or CASE expression that extracts instrument sub-type, then a WHERE clause requiring compatibility.
- Compatibility rules: Revolver <-> Revolver, Term Loan <-> Term Loan, DDTL <-> DDTL, Equity <-> Equity. Unknown/null sub-types are compatible with anything (no rejection).

### 2. Suffix coexistence check (tiers B2/C/D)

When matching a position with a numbered suffix (e.g., "Acme Corp Loan 6"), check whether a position with the same suffix number exists in the end period. If the original suffix still exists in the end period but the matcher selected a different suffix, reject the match.

This addresses pattern 3 (tranche renumbering), the largest single error group at 26 errors.

Implementation approach:
- After the initial match CTE produces candidates, add a validation pass that checks for "suffix coexistence": parse trailing digits from the match key, and if the begin-side suffix number exists verbatim in the end period at the same entity, prefer it over the current match candidate.
- This is a tiebreaker refinement, not a hard reject -- if no same-suffix candidate exists (position was genuinely renumbered), the match stands.

Expected catch rate: ~60% of pattern 3 errors (15-16 of 26).

### 3. Bipartite matching for same-entity multi-tranche groups (tiers B2/C)

When an entity has N positions in the begin period and M positions in the end period, the current algorithm matches them one-at-a-time using FV proximity as tiebreaker. This can produce suboptimal assignments where swapping two matches would reduce total error.

Replace with minimum-cost bipartite matching (Hungarian algorithm or similar) within same-entity groups:
- Group unmatched positions by (CIK, entity_name/entity_id, classification)
- For groups with 2+ positions on both sides, compute pairwise cost matrix (FV distance + rate distance + principal distance)
- Solve assignment problem to minimize total cost
- Only form matches where the best assignment cost is below the tier's FV ratio guard

This addresses pattern 8 (4 errors) and likely catches some pattern 3 residuals.

Implementation note: this is the most complex change. DuckDB does not have a native Hungarian algorithm, so this would require a Python post-processing step on the small subset of multi-tranche groups. Given the low error count (4), this is the lowest priority item in this plan.

### 4. New J-category oracle checks

**J07: Calibrated flag rejection audit**:
- After matching completes, count matches in tiers C/D/E that would have been rejected by the new hard gates (classification flip, maturity mismatch, instrument sub-type).
- Report: total rejected, breakdown by gate, percentage of tier population.
- Status: informational (always pass). Purpose is auditing the rejection rate over time.

**J08: Refinancing detection**:
- Flag matches where maturity shifted >12 months AND spread changed >50bps.
- Report as "suspected refinancings" with detail rows.
- Status: warn if count >N% of B2+ matches.
- These are not auto-rejected (distinguishing refinancing from amendment requires judgment), but surfaced for review.

## Verification

- All existing `tests/test_position_matching.py` tests pass
- Add new test cases:
  - Classification flip: match rejected when classifications differ
  - Maturity mismatch: match rejected in C/D/E when maturity gap >12mo, allowed in A/B
  - Instrument sub-type: revolver not matched to term loan
  - Suffix coexistence: prefer same-suffix candidate when available
- Run `python -m pipeline.oracle_runner --category J` and verify J07/J08 produce output
- Spot-check: manually verify 10 rejected matches are genuine errors and 10 surviving matches are correct

## Files to create/modify

| File | Action |
|------|--------|
| `pipeline/position_matching.py` | Add classification flip veto, maturity mismatch veto, instrument sub-type continuity, suffix coexistence check |
| `pipeline/oracle_checks.py` | Add J07, J08 checks |
| `tests/test_position_matching.py` | New test cases for each gate |
| `tests/test_oracle_checks.py` | Tests for J07, J08 |

## Expected impact

- Eliminates ~43 of the 58 algorithm-side errors
- B2_exact_name error rate: 7.6% -> 3-4%
- C_normalized_name error rate: 30% -> 10-15%
- D_fuzzy error rate (after Plan A wrapper fixes): ~10.6% -> 5-8%
- Bipartite matching (if implemented): additional ~4 errors

## Priority order within this plan

1. Classification flip veto -- simplest change, 100% precision, zero false positive risk
2. Instrument sub-type continuity -- moderate complexity, high precision
3. Maturity mismatch veto (C/D/E) -- simple change, 74.6% precision, some false positives acceptable
4. Suffix coexistence check -- moderate complexity, addresses largest error group
5. J07/J08 oracle checks -- informational, low urgency
6. Bipartite matching -- highest complexity, lowest error count (4), do last or defer to v2
