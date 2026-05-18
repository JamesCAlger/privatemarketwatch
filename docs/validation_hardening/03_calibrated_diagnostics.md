# Plan 3: Calibrated Diagnostics

## Purpose

Add statistical and temporal diagnostics only after deterministic validation and observability are stable. These checks should begin as report-only diagnostics. They must be calibrated against historical data before any promotion to WARN or FAIL.

The purpose is to find suspicious changes, not to prove data is wrong.

## Included Work

### 1. Diagnostic Candidate Set

Start with a small subset instead of adding all proposed DIST and MONO rules.

Initial candidates:

| Candidate | Source idea | Initial status | Rationale |
|-----------|-------------|----------------|-----------|
| DIST01 | QoQ median fair value drift per CIK | Report-only | May reveal scale or extraction changes. |
| DIST02 | QoQ distinct issuer count change per CIK | Report-only | Overlaps with T01 but may be useful as a separate issuer-level signal. |
| DIST04 | Top-10 concentration shift | Report-only | Can surface subtotal leaks or missing long-tail positions. |
| DIST05 | New-name ratio per CIK-quarter | Report-only | Can surface matching/entity-resolution failures or true turnover. |
| MONO03 | Disappears then reappears after a gap | Report-only | Can reveal position matching chain breaks. |
| MONO05 | Classification flip for same position | Report-only | Useful if keyed on stable `position_id`; overlaps with T04 and should be compared. |

Do not implement `DIST03` kurtosis sign flip unless a concrete historical failure proves it is useful. It is likely hard to interpret.

Do not implement `MONO01` fixed-rate rate change until `position_matches.csv` reliably carries the fields needed to distinguish fixed coupons and compare rate fields.

Do not implement broad `MONO02` cost-change thresholds without adjusting for paydowns, add-ons, amendments, restructurings, and source changes.

### 2. Calibration Harness

Before adding candidates to the main registry, run each candidate across historical cached outputs.

Create a temporary or test-only calibration script if needed, but promote reusable behavior into `pipeline/validation_rules/diagnostics.py`.

For each candidate, record:

```
candidate_id,quarters_tested,hit_count,affected_fair_value,
top_ciks,top_examples,false_positive_notes,recommended_action
```

Recommended actions:

- `drop`
- `keep_report_only`
- `add_as_unpromoted_rule`
- `refine_and_retest`
- `promote_to_warn`

No candidate can be promoted directly to FAIL in this plan.

### 3. Rule Implementation Criteria

A diagnostic may enter `RULE_REGISTRY` only if it has:

- A clear analyst action when it fires.
- A low-cost evidence hint.
- A false-positive explanation from calibration.
- A threshold justified by historical behavior, not intuition.
- A test with both trigger and non-trigger examples.

Prefer existing categories if the diagnostic naturally fits:

- Distribution and CIK-quarter drift rules can remain `T` if they are temporal.
- Matching-chain diagnostics can remain `M`.
- Use a new `DIST` category only if there are enough distribution-specific rules to justify it.

### 4. Promotion Policy

Initial state:

- All diagnostics are unpromoted.
- Status should be WARN only under the existing report-only registry semantics, not an export blocker.

Promotion to promoted WARN requires:

- At least one historical production issue found by the diagnostic.
- False-positive rate low enough for routine triage.
- Documented residual risk.
- Review in `docs/validation_hardening/interpretation_guide.md`.

Promotion to promoted FAIL is out of scope.

### 5. No Incremental Validation

Do not add incremental validation here.

Reason: diagnostic results are sensitive to rule SQL, thresholds, upstream transformations, and matching behavior. Carrying forward old findings can create stale confidence. Reconsider only if full validation runtime becomes a measured bottleneck.

## Explicitly Deferred

- Incremental validation.
- Promoted FAIL diagnostics.
- LLM or agent-authored automatic corrections.
- Frontend display changes.

## Verification

Run:

```
pytest tests/test_validation_rules.py
python -m pipeline.main --validate-all
```

For each diagnostic candidate, inspect:

- Total hit count.
- Hit count by quarter.
- Top affected CIKs.
- Top affected FV.
- At least five highest-priority findings.
- At least one non-trigger fixture.

## Success Criteria

- Diagnostics produce useful triage signals without becoming hard gates.
- Overlapping rules are deduplicated or clearly differentiated.
- No new rule is promoted without calibration evidence.
- The plan improves anomaly discovery without weakening the deterministic data-quality contract.
