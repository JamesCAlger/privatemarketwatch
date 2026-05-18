# Plan 3 Readiness - 2026-05-18

## Scope

This note records the safe baseline for beginning Plan 3 diagnostic work. It does not promote diagnostics, change frontend data, or claim that diagnostic hits prove data errors.

## Commands Run

| Command | Outcome |
| --- | --- |
| `git status --short` | Dirty worktree already present; treated prior changes as existing work and did not revert them. |
| `pytest tests/test_validation_rules.py --basetemp=.pytest_tmp` | Passed: 38 tests. Pytest cache warning from `.pytest_cache` permissions. |
| `pytest tests/test_diagnostic_calibration.py --basetemp=.pytest_tmp` | Initial parallel run failed during Windows temp cleanup because `.pytest_tmp` was shared by simultaneous pytest jobs. |
| `pytest tests/test_diagnostic_calibration.py --basetemp=.pytest_diag_tmp` | Passed: 8 tests. Pytest cache warning from `.pytest_cache` permissions. |
| `python -m pipeline.main --validate-all` | Completed successfully in 419.9 seconds. Summary: fund financials WARN, holdings WARN, validation rules WARN. |
| `python -m pipeline.validation_rules --catalog` | Completed; regenerated `docs/validation_hardening/rule_catalog.md`. |
| `python scripts/diagnostic_calibration/run_calibration.py --all` | Completed from cached outputs; wrote diagnostic calibration candidate files. |
| `python scripts/diagnostic_calibration/validate_review.py --all` | Passed for all six review JSON files. |
| `python scripts/diagnostic_calibration/summarize_reviews.py` | Completed; wrote `review_summary.csv`. |

## Validation Baseline

Inspected artifacts:

- `data/output/validation_rules_aggregate.csv`
- `data/output/validation_rules_detail.csv`
- `data/output/validation_rules_history.csv`
- `data/output/validation_rules_trend.csv`
- `docs/validation_hardening/rule_catalog.md`

Current aggregate schema:

```text
rule_id,category,title,severity,promoted,status,hit_count,hit_rate,affected_fair_value,affected_outputs,run_id,run_timestamp,skipped_reason
```

Current aggregate result:

- 94 rules.
- 58 current `WARN` rows.
- 36 current `PASS` rows.
- 10 promoted `FAIL` severity rules are currently `PASS`.
- No current promoted `FAIL` rule is unresolved.

History/trend status:

- `validation_rules_history.csv` exists and now has 846 rows across 9 run IDs.
- Latest history run has 58 `WARN` rows and 36 `PASS` rows.
- `validation_rules_trend.csv` exists and has 94 rows.

## Diagnostic Calibration Baseline

Inspected artifacts:

- `data/output/diagnostic_calibration/candidate_summary.csv`
- `data/output/diagnostic_calibration/candidate_threshold_grid.csv`
- `data/output/diagnostic_calibration/candidate_findings.csv`
- `data/output/diagnostic_calibration/review_summary.csv`

Refreshed calibration run:

- `calibration_run_id`: `6dd7cc1d5ab5`
- Candidate summary rows: 6.
- Threshold grid rows: 16.
- Finding rows: 945.
- Review summary rows: 6.

Candidate review recommendations:

| Candidate | Review verdict | Confidence | Recommended action | Promotion eligible |
| --- | --- | --- | --- | --- |
| `DIST01` | `needs_refinement` | medium | `refine_and_retest` | false |
| `DIST02` | `needs_refinement` | medium | `refine_and_retest` | false |
| `DIST04` | `useful_signal` | medium | `keep_report_only` | false |
| `DIST05` | `needs_refinement` | medium | `refine_and_retest` | false |
| `MONO03` | `useful_signal` | medium | `keep_report_only` | false |
| `MONO05` | `needs_refinement` | medium | `refine_and_retest` | false |

## Safe Starting Position

Plan 3 is ready to begin only as report-only diagnostic work.

- Keep `DIST04` and `MONO03` as report-only candidates.
- Keep `DIST01`, `DIST02`, `DIST05`, and `MONO05` in `refine_and_retest`.
- Do not add promoted WARN diagnostics from this evidence.
- Do not add promoted FAIL diagnostics; that remains out of scope.
- Do not add frontend changes from these diagnostics.

## Residual Blockers Before Promotion

- Current candidate summaries still label machine recommendations as `needs_agent_review`; review summaries provide triage recommendations, not correctness proof.
- `DIST04` and `MONO03` have useful-signal reviews but are not eligible for promotion.
- `DIST01`, `DIST02`, `DIST05`, and `MONO05` require tighter mechanisms and retesting before even unpromoted registry consideration.
- Promotion still requires a historical production issue, low-noise evidence, threshold justification, trigger and non-trigger tests, and documentation in the interpretation guide.
- The shared `.pytest_tmp` failure shows parallel pytest runs should not reuse the same basetemp on Windows.
