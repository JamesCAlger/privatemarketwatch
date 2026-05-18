# Plan 2: Validation Observability And Triage

## Purpose

Make validation results easier to interpret, prioritize, and communicate after deterministic hardening is stable. This plan should not introduce new data mutations or suppress validation failures. It is about visibility, triage, and consistent semantics.

This plan depends on Plan 1 writing current-run validation outputs, minimal append-only validation history, and the rule dependency DAG.

## Included Work

### 1. Status, Severity, And Evidence Normalization

Document and normalize display semantics across the three validation surfaces:

- Fund financials validation.
- Holdings and column validation.
- Rule registry validation.

Decisions:

- Preserve existing output schemas unless a schema change is explicitly needed.
- Normalize in summary/reporting code first.
- Treat `SKIP` and `SKIPPED` as the same display status.
- Keep severity separate from status. A WARN-severity rule can still have status `PASS` if it has no findings.

Add a small helper module only if repeated summary code appears in more than one place.

### 2. Trend Analysis

Add trend computation only after `validation_rules_history.csv` exists.

Create `pipeline/validation_rules/trend.py` with a pure function:

```
compute_trends(history_df: pd.DataFrame, current_aggregate_df: pd.DataFrame) -> pd.DataFrame
```

Output:

```
data/output/validation_rules_trend.csv
```

Columns:

```
rule_id,category,prior_hit_count,current_hit_count,delta_pct,
prior_affected_fair_value,current_affected_fair_value,
affected_fair_value_delta_pct,consecutive_non_pass_runs,trend_flag
```

Trend flags:

| Flag | Meaning |
|------|---------|
| REGRESSION | Current hit count or affected FV increased materially versus the prior run. |
| CHRONIC | Same rule has non-PASS results for at least four consecutive runs. |
| IMPROVING | Current hit count and affected FV are both materially lower than prior run. |
| STABLE | No material change. |
| NEW | No prior comparable history. |

Default materiality:

- Hit count increase greater than 50%.
- Affected FV increase greater than 25%.
- Ignore percentage deltas when the prior value is zero; mark as `NEW` or use absolute values in the detail fields.

Do not make trend flags gates. They are triage signals.

### 3. Downstream Impact Annotations

Add simple metadata to `ValidationRule`:

```
affected_outputs: tuple[str, ...] = ()
```

Do not add `materiality_weight` in this pass. The runner already computes `affected_fair_value`; use that for prioritization.

Recommended affected output labels:

- `private_markets_holdings`
- `position_returns`
- `index_returns`
- `frontend_index`
- `frontend_fund_detail`
- `data_quality_dashboard`

Add `affected_outputs` to `validation_rules_aggregate.csv` as a semicolon-delimited string.

### 4. Interpretation Guide

Create:

```
docs/validation_hardening/interpretation_guide.md
```

Required sections:

- Severity vs. evidence: what combinations mean.
- Status meanings: `PASS`, `WARN`, `FAIL`, `SKIP/SKIPPED`.
- Validation tiers: `VERIFIED`, `VALIDATED_WITH_WARNINGS`, `UNDER_REVIEW`.
- Triage workflow for many findings on the same CIK-quarter.
- Trend flag meanings.
- Rule lifecycle: candidate, report-only, promoted WARN, promoted FAIL, retired.
- Known residuals that should be tracked but not investigated each run.

The guide must be explicit that weak signals are flags, not correctness proof.

### 5. Catalog Expansion

Extend the generated `rule_catalog.md` from Plan 1 to include:

- Affected outputs.
- Whether the rule is promoted.
- Current output artifact.
- Trend status if `validation_rules_trend.csv` exists.
- Module namespace to avoid rule ID collisions.

If including non-registry validators, use a generated or manually curated adapter that reads live constants from code where practical.

## Explicitly Deferred

- Incremental validation.
- Frontend UI changes.
- Any rule threshold or severity changes.
- Agent-based triage.

## Verification

Run:

```
pytest tests/test_validation_rules.py
python -m pipeline.main --validate-all
python -m pipeline.validation_rules --catalog
```

Inspect:

- `data/output/validation_rules_history.csv`
- `data/output/validation_rules_trend.csv`
- `data/output/validation_rules_aggregate.csv`
- `docs/validation_hardening/rule_catalog.md`
- `docs/validation_hardening/interpretation_guide.md`

## Success Criteria

- Operators can tell whether a finding is new, chronic, improving, or stable.
- Validation output can be prioritized by affected output and affected FV.
- Rule identity is unambiguous across modules.
- Documentation explains what to do next without implying false precision.
