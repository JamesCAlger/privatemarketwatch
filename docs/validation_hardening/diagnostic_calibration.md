# Diagnostic Calibration Harness

This harness lets agents evaluate Plan 3 diagnostic candidates before any candidate enters `RULE_REGISTRY`.

It is report-only. It reads cached CSVs under `data/output/` and writes only under `data/output/diagnostic_calibration/`. It must not edit frontend JSON, generated production CSVs, validation rule severity, or `RULE_REGISTRY`.

## Candidates

Initial candidates are:

| Candidate | Meaning |
| --- | --- |
| `DIST01` | QoQ median fair value drift per CIK |
| `DIST02` | QoQ distinct issuer count change per CIK |
| `DIST04` | Top-10 concentration share shift |
| `DIST05` | New-name ratio per CIK-quarter |
| `MONO03` | Position disappears then reappears after a gap |
| `MONO05` | Classification flip for the same `position_id` |

Thresholds are a calibration grid, not policy. The machine-filled `recommended_action` is always `needs_agent_review`.

## Commands

Run all candidates from cached data:

```powershell
python scripts/diagnostic_calibration/run_calibration.py --all
```

Run one candidate:

```powershell
python scripts/diagnostic_calibration/run_calibration.py --candidate DIST01
```

Build a review bundle for the highest-impact threshold row for a candidate:

```powershell
python scripts/diagnostic_calibration/build_review_bundle.py --candidate DIST01 --top-n 20
```

Validate one review:

```powershell
python scripts/diagnostic_calibration/validate_review.py --review data/output/diagnostic_calibration/reviews/<calibration_id>.json
```

Validate all reviews and summarize recommendations:

```powershell
python scripts/diagnostic_calibration/validate_review.py --all
python scripts/diagnostic_calibration/summarize_reviews.py
```

## Output Files

The harness writes:

- `candidate_findings.csv`: normalized threshold-hit rows.
- `candidate_summary.csv`: candidate-level machine summary.
- `candidate_threshold_grid.csv`: per-candidate threshold grid with input hashes and git metadata.
- `review_manifest.csv`: bundle inventory.
- `bundles/<calibration_id>.json`: evidence bundle for agent review.
- `reviews/<calibration_id>.json`: agent-authored review location.
- `review_summary.csv`: aggregated accepted reviews.

## Review Contract

Agents consume one bundle at a time from `bundles/<calibration_id>.json` and write only `reviews/<calibration_id>.json`.

Review JSON must validate against `schemas/diagnostic_calibration/review.schema.json` and include:

- `candidate_id`
- `calibration_id`
- `verdict`
- `confidence`
- `mechanism_assessment`
- `false_positive_assessment`
- `threshold_assessment`
- `examples_reviewed`
- `evidence_refs`
- `recommended_action`
- `rationale`
- `residual_risk`
- `anti_sycophancy_check`

Allowed `recommended_action` values are exactly:

- `drop`
- `keep_report_only`
- `add_as_unpromoted_rule`
- `refine_and_retest`
- `promote_to_warn`

`promote_to_warn` requires at least one reviewed historical production issue and a low-noise explanation. `promote_to_fail` is not allowed.

## Policy

Do not promote a diagnostic without evidence. A plausible anomaly is not a data-quality contract. Promotion requires a clear analyst action, a low-cost evidence hint, false-positive assessment from calibration, threshold justification from historical behavior, and tests with both trigger and non-trigger fixtures.

If the bundle is insufficient, write `insufficient_evidence` or recommend `refine_and_retest`. Escalation is better than converting weak anomaly scores into production validation gates.
