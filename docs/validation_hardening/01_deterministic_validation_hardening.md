# Plan 1: Deterministic Validation Hardening

## Purpose

Strengthen the validation layer with checks that have clear correctness semantics and low false-positive risk. This plan should ship before statistical diagnostics or incremental validation because it directly reduces silent corruption risk in public outputs.

The goal is not to add many rules. The goal is to make partial rebuilds, orphaned outputs, known historical defects, and source-specific column contract violations visible and testable.

## Included Work

### 1. Referential Integrity Rules

Add a new `RI` category to `pipeline/validation_rules/__init__.py`.

Rules:

| Rule | Severity | Promoted | Check |
|------|----------|----------|-------|
| RI01 | FAIL | true | Every CIK in `private_markets_holdings.csv` exists in `combined_universe.csv`. |
| RI02 | FAIL | true | Every CIK in `position_matches.csv` exists in `private_markets_holdings.csv`. |
| RI03 | FAIL | true | Every CIK-quarter in `fund_financials_cross_level.csv` exists in `fund_financials.csv`. |
| RI04 | FAIL | true | `index_returns.csv` quarter range is within the holdings quarter range. |
| RI05 | FAIL | true | Every CIK in `fee_uplift.csv` exists in `private_markets_holdings.csv`. |
| RI06 | FAIL | true | Every CIK in `bdc_fund_income.csv` exists in `bdc_holdings.csv`. |

Implementation notes:

- Use anti-join SQL patterns.
- Add missing table registrations for `bdc_holdings`, `bdc_fund_income`, and `fund_financials_cross_level`.
- Emit detail rows at the narrowest useful granularity: CIK, CIK-quarter, or index-quarter.
- Keep these rules promoted from day one because they represent pipeline integrity failures, not analyst judgment calls.

### 2. Known-Bad Regression Fixtures

Create `tests/fixtures/known_bad/` with minimal fixture files for prior production failure modes.

Initial fixtures:

- Goldman Sachs four-level affiliation hierarchy artifact.
- Multi-dimension-path BDC duplicate, such as Owl Rock.
- L.P. suffix SPV misclassification that was fixed by co-invest keyword/name gating.
- Aggregate header leak such as `Total Investments in Non-Controlled...`.
- NUSS issuer type misclassification.

Add `tests/test_known_bad_regressions.py`.

Each fixture must include:

- Minimal input CSV.
- Expected output JSON or expected row assertion.
- The specific transform or validator being exercised.
- At least one false-positive guard when the fix involves filtering or keyword logic.

### 3. Source-Aware Column Contracts

Tighten `pipeline/column_validation.py` by making null and fill expectations explicit without weakening current row-level checks.

Important constraints:

- Do not replace existing C-series row checks.
- Do not make `fair_value` required for every row unconditionally; preserve the current indexable-row distinction.
- Do not reference `pct_corrected` unless that field is added to `private_markets_holdings.csv`. Prefer existing source and reconciliation signals.

Minimum contract table:

| Column | Contract |
|--------|----------|
| `fair_value` | Required for indexable rows. |
| `cost` | Required for BDC debt positions where cost is source-reported or expected. |
| `interest_rate` | Expected, not required, for direct lending loans; failures should remain source-aware because filings often omit parsed rates. |
| `cusip` | Expected fill-rate metric for N-PORT and public-security-like rows; not a universal failure. |
| `pct_of_net_assets` | Required where source reports it and used as a reconciliation input; outliers remain row/CIK-quarter issues. |

Output expectations:

- `column_quality_metrics.csv` continues to expose actual fill, parse, and valid rates.
- Any new contract fields must be reflected in tests.
- The frontend-facing data-quality export should not break if new columns are added.

### 4. Append-Only Validation History

The config already defines `VALIDATION_RULES_HISTORY_FILE`, but the current rule runner does not write history.

Add minimal append-only history from `run_all()`:

```
rule_id,category,run_id,run_timestamp,status,hit_count,hit_rate,affected_fair_value
```

Rules:

- Append only after a successful rule-run output is assembled.
- Do not use history to skip or carry forward results.
- Preserve `validation_rules_aggregate.csv` and `validation_rules_detail.csv` as the current-run artifacts.

### 5. Rule Dependency DAG

Add a `depends_on` field to `ValidationRule` and wire dependency-aware execution into `run_all()`.

Dataclass change:

```python
depends_on: tuple[str, ...] = ()  # rule_ids that must pass before this rule runs
```

Runner changes in `run_all()`:

1. Build adjacency list from `depends_on` references across all registered rules.
2. Detect cycles at import time (not runtime). Raise `ValueError` if a cycle exists.
3. Topological sort determines execution order within each `run_all()` invocation.
4. If any dependency rule has status `FAIL`, set the dependent rule to `SKIP` with `skipped_reason = "dependency {rule_id} failed"`.
5. Log total skip count per run.

Initial dependency assignments:

- RI rules: no dependencies (pipeline integrity, should always run).
- F20-F28 cross-level checks: migrate existing ad-hoc SKIP logic to `depends_on` references on F10 (balance sheet identity) and F1-F3 (schema checks).
- PC rules that reference index_returns: depend on RI04 (index quarter range integrity).
- New rules added in Plans 2 and 3 inherit the DAG for free since they run through the same `run_all()` path.

Do not use the DAG for incremental carry-forward. It controls execution ordering and skip propagation only.

Files: `pipeline/validation_rules/__init__.py`
Tests: `tests/test_validation_rules.py` (cycle detection test, skip propagation test, topological ordering test)

### 6. Unified Validation Entry Point

Add `--validate-all` to `pipeline/main.py`.

Execution order:

1. Load `private_markets_holdings.csv` from `data/output/` unless `--unified` already built it in the same run.
2. Run `validate_fund_financials()`.
3. Run `validate_holdings()`.
4. Run `pipeline.validation_rules.run_all()` (uses DAG for execution order and skip propagation).
5. Print one ASCII-safe summary table.

Also add `--validate-all` to `scripts/rebuild_outputs.py`, running after rebuild steps when requested.

Summary table statuses must normalize:

- Fund financials: `PASS`, `FAIL`, `SKIP`.
- Holdings validators: report available fail/warn counts.
- Rule registry: `PASS`, `WARN`, `FAIL`, `SKIPPED`.

Use display labels to normalize `SKIP` and `SKIPPED`; do not change existing file schemas solely for presentation.

### 7. Generated Rule Catalog Basics

Add a lightweight catalog generator for live code.

Command:

```
python -m pipeline.validation_rules --catalog
```

Output:

```
docs/validation_hardening/rule_catalog.md
```

Catalog requirements:

- Include module namespace as part of identity because rule IDs collide across systems, especially F-series checks.
- Include rule ID, category/module, title, severity, promoted, required tables, and output artifact.
- Generated content should be deterministic.

## Explicitly Deferred

- Distribution anomaly rules.
- Broad monotonicity rules.
- Incremental validation and carry-forward results.
- Frontend UI changes.
- Promoting existing non-RI rules.

## Verification

Run:

```
pytest tests/test_validation_rules.py
pytest tests/test_column_validation.py
pytest tests/test_validate_holdings.py
pytest tests/test_validate_fund_financials.py
pytest tests/test_known_bad_regressions.py
python -m pipeline.main --validate-all
python -m pipeline.validation_rules --catalog
```

If full output rebuild is needed after tests:

```
python scripts/rebuild_outputs.py --unified
python -m pipeline.main --export-frontend
```

## Success Criteria

- Referential integrity failures produce promoted FAIL rows.
- Known historical defects have regression coverage.
- Column contracts are source-aware and do not turn expected sparsity into false failures.
- Validation history is written but not used for gating.
- Rule execution respects dependency ordering; downstream rules skip when dependencies fail.
- One command gives an operator a readable validation summary.
- The catalog is generated from code, not hand-maintained.
