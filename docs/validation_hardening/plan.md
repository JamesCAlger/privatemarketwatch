# Validation Hardening Plan

## Context

The pipeline has 80+ validation rules across 6 modules (validation_rules, validate_fund_financials, validate_holdings, column_validation, validate_html_template, validate_nonaccruals) producing 22 output CSVs. Rules have IDs, severity levels (FAIL/WARN/INFO), evidence strength (STRONG/MODERATE/WEAK), and DuckDB SQL implementations. The infrastructure works but has gaps in temporal monitoring, cross-output integrity, rule lifecycle management, and documentation.

This plan covers 11 changes across 3 categories: new rules (4), infrastructure amendments (4), and operational improvements (3).

---

## Deliverables

### A. New Rules

**A1. Distribution-based anomaly detection** (new rules: DIST01-DIST05)

Add to `pipeline/validation_rules/__init__.py` as new category `DIST`:
- DIST01: QoQ z-score drift on `fair_value` median per CIK (flag >2 sigma shift)
- DIST02: QoQ distinct `issuer_name` count per CIK (flag >2x or <0.5x change)
- DIST03: FV distribution skewness per CIK-quarter (flag kurtosis sign flip vs. prior quarter)
- DIST04: Concentration shift (top-10 position share changes >15pp QoQ)
- DIST05: New-name ratio per CIK-quarter (flag >60% new issuer names vs. prior quarter)

All implemented as DuckDB SQL using window functions (LAG, STDDEV, PERCENTILE_CONT). Default severity: WARN. No promoted rules initially.

Files: `pipeline/validation_rules/__init__.py`
Tests: `tests/test_validation_rules.py` (add `_base_holding()` fixtures with multi-quarter data)

**A2. Referential integrity across outputs** (new rules: RI01-RI06)

Add to `pipeline/validation_rules/__init__.py` as new category `RI`:
- RI01: Every CIK in `private_markets_holdings.csv` exists in `combined_universe.csv`
- RI02: Every CIK in `position_matches.csv` has rows in holdings
- RI03: Every CIK-quarter in `fund_financials_cross_level.csv` exists in `fund_financials.csv`
- RI04: `index_returns.csv` quarter range is subset of holdings quarter range
- RI05: Every CIK in `fee_uplift.csv` exists in holdings
- RI06: Every CIK in `bdc_fund_income.csv` exists in `bdc_holdings.csv`

Implemented as LEFT JOIN ... WHERE right.key IS NULL anti-join pattern. Severity: FAIL (these indicate pipeline ordering bugs or partial rebuilds).

Files: `pipeline/validation_rules/__init__.py`
Tests: `tests/test_validation_rules.py` (add fixtures with orphan rows)

**A3. Monotonicity / impossible transition checks** (new rules: MONO01-MONO05)

Add to `pipeline/validation_rules/__init__.py` as new category `MONO`:
- MONO01: Fixed-rate `interest_rate` changes >50bps between matched positions (use `position_matches.csv`)
- MONO02: `cost` changes >10% between matched positions (amortized cost should be near-stable)
- MONO03: Position disappears then reappears 2+ quarters later with similar FV (matching failure signal)
- MONO04: `net_assets` swings >50% QoQ without corresponding FV change (scale error signal)
- MONO05: `index_classification` flip for same position across quarters (already partially covered by staging_bdc stabilization, this catches residuals)

Files: `pipeline/validation_rules/__init__.py`
Tests: `tests/test_validation_rules.py`

**A4. Known-bad regression fixtures** (testing practice)

Create `tests/fixtures/known_bad/` directory with real-world records that previously caused production issues, each as a minimal CSV + expected output JSON:
- Goldman Sachs 4-level affiliation hierarchy artifact
- Multi-dimension-path BDC duplicate (e.g., Owl Rock)
- L.P. suffix SPV misclassification (pre-co-keyword fix)
- Aggregate header leak (e.g., "Total Investments in Non-Controlled...")
- NUSS issuer_type misclassification (pre-name-gating fix)

Add `tests/test_known_bad_regressions.py` that loads each fixture, runs the relevant transform, and asserts the expected corrected output.

Files: `tests/fixtures/known_bad/*.csv`, `tests/fixtures/known_bad/*.json`, `tests/test_known_bad_regressions.py`

### B. Infrastructure Amendments

**B1. Explicit null policies per column**

Add a `COLUMN_CONTRACTS` dict to `pipeline/column_validation.py`:
```
Column              | Nullability  | Condition
--------------------|--------------|---------------------------
fair_value          | REQUIRED     | always
cost                | CONDITIONAL  | required if source=BDC
interest_rate       | CONDITIONAL  | required if asset_category=LOAN
cusip               | EXPECTED_47  | expected ~47% fill for N-PORT
pct_of_net_assets   | CONDITIONAL  | required unless pct_corrected=True
```

Change `validate_column_contracts()` to compare actual fill rates against declared expectations. A column at 60% fill when expected REQUIRED is a FAIL; at 60% when expected ~47% is PASS.

Files: `pipeline/column_validation.py`
Tests: `tests/test_validate_holdings.py` (extend column contract tests)

**B2. Rule dependency DAG**

Add `depends_on: tuple[str, ...] = ()` field to `ValidationRule` dataclass. Wire into `run_all()`:
1. Build adjacency list from `depends_on` references
2. Topological sort to determine execution order
3. If a dependency rule has status FAIL, set dependent rule to SKIP with `skipped_reason = "dependency {rule_id} failed"`
4. Log skip count per run

Existing ad-hoc SKIP logic in F20-F28 (cross-level checks) migrates to this mechanism.

Files: `pipeline/validation_rules/__init__.py`
Tests: `tests/test_validation_rules.py` (add DAG cycle detection test, skip propagation test)

**B3. Rule trend analysis**

Add `pipeline/validation_rules/trend.py`:
- `compute_trends(history_df, current_aggregate_df) -> trend_df`
- For each rule: QoQ delta in hit_count, hit_rate, affected_fair_value
- Flag rules where hit_count increased >50% vs. prior run
- Flag rules with 4+ consecutive quarters in FAIL/WARN (chronic issues)
- Output: `validation_rules_trend.csv` with columns: rule_id, prior_hit_count, current_hit_count, delta_pct, consecutive_fail_quarters, trend_flag (REGRESSION | CHRONIC | IMPROVING | STABLE)

Wire into `run_all()` as a post-step that reads `validation_rules_history.csv`.

Files: `pipeline/validation_rules/trend.py`, `pipeline/validation_rules/__init__.py`
Tests: `tests/test_validation_rules.py` (add trend computation tests)
Output: `data/output/validation_rules_trend.csv`

**B4. Downstream impact annotations**

Add two fields to `ValidationRule` dataclass:
- `affects: tuple[str, ...] = ()` -- downstream outputs affected (e.g., `("index_returns", "frontend_fund_detail")`)
- `materiality_weight: str = "equal"` -- `"fv_weighted"` or `"equal"`. FV-weighted rules report affected_fair_value as % of total AUM in aggregate output.

Add `affected_outputs` and `materiality_pct` columns to `AGGREGATE_COLUMNS`. No behavioral change to rule execution -- this is metadata for triage prioritization.

Files: `pipeline/validation_rules/__init__.py`
Tests: `tests/test_validation_rules.py` (verify new columns in aggregate output)

### C. Operational Improvements

**C1. Unified validation entry point**

Add `--validate-all` flag to `pipeline/main.py` that runs in sequence:
1. `validate_fund_financials()` (F-series checks)
2. `validate_holdings()` (10 validators + column contracts)
3. `run_all()` (RULE_REGISTRY: PC/IDX/T/S/R/XS/F/M + new DIST/RI/MONO categories)
4. `compute_trends()` (trend analysis post-step)

Print a single summary table at the end:

```
Module                  | FAIL | WARN | SKIP | PASS
------------------------|------|------|------|-----
Fund Financials (F)     |    2 |   14 |    3 |   15
Holdings Validators     |    0 |    4 |    0 |    6
Rule Registry (83+)     |    1 |   12 |    5 |   65
Trend Flags             |    - |    2 |    - |   81
```

Also add `--validate-all` to `scripts/rebuild_outputs.py`.

Files: `pipeline/main.py`, `scripts/rebuild_outputs.py`

**C2. Efficiency: incremental validation**

Add `--incremental` flag that pairs with `--validate-all` or `--validate-rules`:
1. Read `validation_rules_history.csv` to get last run timestamp
2. Read `private_markets_holdings.csv` and identify CIK-quarters with `report_date` after last validation
3. For rules at `cik_quarter` or finer granularity: filter input tables to changed CIK-quarters only
4. For `global` or `index_quarter` granularity rules: always run (these are cheap aggregate checks)
5. Carry forward prior results for unchanged CIK-quarters

Also wire dependency-aware skipping (B2) into execution -- this is the primary efficiency gain since it avoids running downstream rules on known-bad data.

Files: `pipeline/validation_rules/__init__.py`

**C3. Documentation**

Create two documents in `docs/validation_hardening/`:

**`rule_catalog.md`** (machine-readable reference):
- Table with one row per rule across all modules: ID, category, severity, evidence, depends_on, affects, description, output file
- Generated from code via `python -m pipeline.validation_rules --catalog` (add CLI subcommand)
- Sections grouped by module: Fund Financials (F1-F34), Holdings (10 validators), Rule Registry (PC/IDX/T/S/R/XS/DIST/RI/MONO), Column Contracts

**`interpretation_guide.md`** (human/agent triage guide):
- Severity x Evidence matrix: what each combination means and what action to take
- Validation tier definitions (VERIFIED / VALIDATED_WITH_WARNINGS / UNDER_REVIEW)
- Triage workflow: "15 rules fired on the same CIK-quarter -- now what?"
- Trend flags: what REGRESSION vs. CHRONIC vs. IMPROVING means
- Rule lifecycle: how rules get promoted (WARN -> FAIL), what `promoted` means
- Known residuals: documented acceptable findings that should not trigger investigation (e.g., the 231 E2 disagreements)

Files: `docs/validation_hardening/rule_catalog.md`, `docs/validation_hardening/interpretation_guide.md`

---

## Execution Order

Group by dependency (not by section letter):

| Step | Item | Depends on |
|------|------|------------|
| 1 | B2: Rule dependency DAG | -- |
| 2 | B4: Downstream impact annotations | -- |
| 3 | B1: Explicit null policies | -- |
| 4 | A1: Distribution rules (DIST) | B2 (uses depends_on field) |
| 5 | A2: Referential integrity rules (RI) | B2 |
| 6 | A3: Monotonicity rules (MONO) | B2 |
| 7 | B3: Rule trend analysis | -- |
| 8 | C1: Unified entry point (--validate-all) | B3, all new rules |
| 9 | C2: Incremental validation | C1, B2 |
| 10 | A4: Known-bad regression fixtures | -- (independent) |
| 11 | C3: Documentation | all above (describes final state) |

Steps 1-3 can run in parallel. Steps 4-6 can run in parallel after step 1. Step 10 is independent of everything else.

---

## Verification

After all steps:
1. `pytest tests/` -- all existing + new tests pass
2. `python scripts/rebuild_outputs.py` -- rebuild outputs from cache
3. `python scripts/diff_outputs.py --semantic` -- confirm no semantic delta on existing outputs (new CSVs are additive only)
4. `python -m pipeline.main --validate-all` -- full validation runs end-to-end, summary table prints
5. `python -m pipeline.main --validate-all --incremental` -- incremental mode runs, carries forward prior results
6. `python -m pipeline.validation_rules --catalog` -- generates rule_catalog.md from live code
7. Verify `validation_rules_trend.csv` is produced and contains STABLE/REGRESSION flags
8. Verify dependency-aware skipping: introduce a synthetic FAIL on a parent rule, confirm child rules show SKIP

---

## Out of Scope

- Agent-based rule verification (deferred to V3 calibration per existing plan)
- LLM-assisted triage of ambiguous findings
- Frontend display of validation status (tracked in NEXT_STEPS.md)
- Changes to existing rule thresholds or severity levels
- Promotion of any existing WARN rules to FAIL
