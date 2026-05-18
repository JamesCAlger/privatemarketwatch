# Validation Rules Engine - Implementation Plan

## Context

The current validation layer produces 343K row-level entries dominated by source characterization: known gaps are re-documented every run. The redesign document specifies 83 rules across 8 categories that answer "did anything leak through?" rather than "does the source have known gaps?"

This plan implements the deterministic rule layer first. Agent verification remains a later calibration tool for ambiguous, high-volume rules; it is not part of the first production path.

The objective is:
1. Get usable signal immediately from post-condition and index sanity checks.
2. Add the full SQL rule registry without making all 83 rules production gates on day one.
3. Promote rules only when their semantics are clear and their findings are auditable.
4. Build toward a quarterly loop where deterministic rules find residuals and agents only investigate uncertain cases.

---

## Proposed Approach

Implement the rule engine in two slices instead of trying to make all 83 rules equally production-ready in the first pass.

**V1: runner + high-confidence rules**
- Build the `pipeline/validation_rules/` package, output contract, CLI integration, and tests.
- Implement and ship PC + IDX first, plus a small set of high-value non-PC rules: `T01`, `T02`, `R07`, and `M02`.
- Treat only true guard-leak rules as promoted FAIL gates at first.
- Run against production data and inspect the output shape, hit counts, and runtime.

**V2: remaining SQL rules**
- Add the remaining T/S/R/XS/F/M rules as SQL definitions.
- Default new rules to `promoted=False` and `severity=WARN` unless the failure is mechanically a downstream bug.
- Use hit counts and materiality-ranked detail rows for triage.

**V3: calibration and quarterly loop**
- Extend `fail_verification.py` for ambiguous validation-rule findings.
- Add append-only trend history.
- Feed promoted validation status into frontend quality metadata once the rule set is trusted.

This avoids creating 83 superficial checks that nobody trusts while still preserving the long-term rule catalog.

---

## Step 1: Build the Rule Engine and Ship V1 Rules

### New module structure

```
pipeline/validation_rules/
  __init__.py           # Public API: run_all(), run_category(), RULE_REGISTRY
  _registry.py          # ValidationRule dataclass, registry dict, category enum
  _runner.py            # DuckDB execution engine, table loading, output assembly
  _temporal.py          # T01-T10
  _strategy.py          # S01-S10
  _relational.py        # R01-R15
  _cross_source.py      # XS01-XS06
  _index.py             # IDX01-IDX10
  _postcondition.py     # PC01-PC12
  _freshness.py         # F01-F10
  _matching.py          # M01-M10
```

### Rule definition

Use a frozen dataclass with SQL text plus enough metadata to support triage and later promotion review.

```python
@dataclass(frozen=True)
class ValidationRule:
    rule_id: str
    category: str                     # T/S/R/XS/IDX/PC/F/M
    granularity: str                  # row | cik_quarter | cik | index_quarter | global
    tables_required: tuple[str, ...]
    title: str
    description: str
    sql_template: str                 # DuckDB SQL returning detail rows
    severity: str = "WARN"
    promoted: bool = False
    promotion_basis: str = ""         # e.g. "mechanical_guard", "manual_review", "agent_verified"
    materiality_column: str = ""      # optional column used for detail ranking
```

### Severity defaults

Do not mark all PC rules as automatic FAILs. Split post-condition rules into hard guard leaks and proxy diagnostics.

**Promoted FAIL in V1:**
- `PC02`: any negative-cost position entered `position_returns.csv`
- `PC03`: any below-MIN_FV position entered index returns
- `PC11`: any `NPORT_EXCLUDE_CIKS` row present in final output
- `PC12`: any consumer-lending excluded CIK present in frontend-facing output

**Start as WARN/proxy diagnostics:**
- `PC01`, `PC04`, `PC05`, `PC06`, `PC07`, `PC08`, `PC09`, `PC10`

These can be promoted later, but only after the downstream artifact, denominator, and valid-exception behavior are pinned down. For example, cross-source duplicate candidates and pct-of-net-assets sums can reflect comparison-source gaps or legitimate multi-tranche facts; they should not fail production until false-positive behavior is measured.

`IDX01-IDX10` start as promoted WARN rules. They are small, cheap, and important for public trust, but they are sanity checks rather than source reconciliation.

### Data loading

The runner must load each required CSV once per process/category into DuckDB temp views or temp tables, then run all relevant SQL against those loaded objects. Do not make each rule reparse `private_markets_holdings.csv`.

Use deterministic CSV loading helpers:
- `read_csv(..., header=true, all_varchar=true)` or equivalent explicit options.
- Cast inside SQL with `TRY_CAST`.
- Avoid `read_csv_auto()` for validation inputs; type inference can change across files and silently alter rule behavior.
- If broad raw `nport_holdings.csv` access is needed, isolate it to rules that explicitly require raw-source evidence. Most Step 1 rules should use unified outputs and downstream artifacts.

Table registry:
- `holdings` -> `private_markets_holdings.csv`
- `position_matches` -> `position_matches.csv`
- `position_returns` -> `position_returns.csv`
- `index_returns` -> `index_returns.csv`
- `fund_financials` -> `fund_financials.csv`
- `combined_universe` -> `combined_universe.csv`
- `bdc_holdings` -> `bdc_holdings.csv`
- `nport_holdings` -> `nport_holdings.csv`
- `fee_uplift` -> `fee_uplift.csv`

If a non-critical table is missing, rules requiring it should emit a skipped aggregate row with a clear reason rather than crashing the full run.

### Output files

**`validation_rules_aggregate.csv`**: one row per rule per run.

```
rule_id | category | title | severity | promoted | status | hit_count |
hit_rate | affected_fair_value | run_id | run_timestamp | skipped_reason
```

**`validation_rules_detail.csv`**: row-level or entity-level findings, capped 10K per rule after deterministic ranking.

```
finding_key | rule_id | category | severity | granularity | granularity_key |
cik | quarter | report_date | issuer_name | position_id | source |
affected_fair_value | denominator | hit_rate | priority_rank |
detail | evidence_hint | source_file | run_id
```

Detail rows should be ranked by materiality and recency, not arbitrary file order. The detail cap should never change aggregate hit counts.

**`validation_rules_history.csv`**: append-only trend file added in Step 4.

### CLI integration

Add to `pipeline/main.py`:

```
--validate-rules              Run validation-rules engine
--rules-category T S PC ...   Limit to specific categories
```

`--validate-rules --rules-category PC` should run without requiring a full rebuild, using existing output artifacts.

### What ships in V1

- Rule package and runner.
- PC + IDX rule modules.
- `T01`, `T02`, `R07`, `M02`.
- Config path constants for aggregate, detail, and history outputs.
- CLI integration.
- Tests for runner behavior, output schemas, SQL syntax, and trigger scenarios for V1 rules.

### Deliverable

Run:

```
python -m pipeline.main --validate-rules
python -m pipeline.main --validate-rules --rules-category PC
```

The first command should produce aggregate and detail CSVs. The second should provide a fast answer to "did downstream guards leak?"

---

## Step 2: Add Remaining SQL Rules and Triage

After V1 is stable, add the remaining T/S/R/XS/F/M rule definitions. New rules default to `promoted=False` unless their semantics are mechanically a downstream bug.

Triage actions after running against production data:

| Hit count | Action |
|-----------|--------|
| 0 hits | Defer; keep in registry as inactive signal |
| 1-10 hits | Exhaustive manual review |
| 11-100 hits | Manual review of 10-20 materiality-ranked hits |
| >100 hits | Keep unpromoted unless clearly mechanical; route ambiguous rules to Step 3 |

Promotion criteria without agent verification:
- Hard PC guard leaks can be promoted immediately when the downstream artifact definition is exact.
- IDX rules remain WARN unless a specific check is proven to identify index corruption rather than market movement.
- T/R/F/M rules with fewer than 10 hits can be promoted after all hits are reviewed and documented.
- S rules need independent fund metadata evidence; holdings mix alone is not enough to make a fund strategy verdict.

Promotion decisions should be auditable. Either store `promotion_basis` in rule metadata or add a small promotion manifest with reviewer, date, evidence summary, and known false-positive pattern.

---

## Step 3: Agent Verification for Ambiguous Rules

Use agent verification only for rules with high hit counts where manual review is impractical and the true-positive rate is unclear.

### Connection to `fail_verification.py`

This is an extension, not a simple alias registration. The current verifier is hard-coded around existing holdings and fund-financials rule families, so validation rules need their own manifest and bundle path.

Required changes:
1. Register `validation_rules` as a dataset.
2. Add `_build_rules_sample_manifest()` to read `validation_rules_detail.csv`, stratify by CIK and rule, and preserve `finding_key`.
3. Add `_build_rules_evidence_bundle()` with category-specific context:
   - T rules: current/prior positions, filing index, fund financials, relevant source rows.
   - S rules: fund metadata, full holdings mix, top positions, source identity evidence.
   - R rules: flagged row, matched pair if available, nearby CIK-quarter positions, raw source row.
   - M rules: both sides of the match, identifiers, CUSIP/entity-resolution data, FV history.
4. Reuse the existing verdict schema and verdict validator where possible.
5. Keep the agent verdict workflow unchanged: `CONFIRMED_DATA_ERROR`, `CONFIRMED_VALID_EXCEPTION`, `VALIDATOR_FALSE_POSITIVE`, `INSUFFICIENT_EVIDENCE`.

Decision logic:

| TP rate | Action |
|---------|--------|
| >70% DATA_ERROR | Promote to FAIL |
| >70% combined DATA_ERROR + VALID_EXCEPTION | Promote to WARN |
| 30-70% | Refine SQL or evidence bundle, then re-verify |
| <30% DATA_ERROR | Retire or keep unpromoted |

Expected scope: roughly 10-15 ambiguous, high-volume rules, not all 83.

---

## Step 4: Quarterly Cadence and Frontend Quality Loop

### Trend tracking

Add `validation_rules_history.csv`:

```
rule_id | run_id | run_timestamp | hit_count | affected_fair_value | delta_vs_prior
```

The runner computes `delta_vs_prior` from the prior history row for the same rule. Log a warning if a promoted rule's hit count or affected FV increases materially.

### Integration into rebuild workflow

Add `--validate-rules` to `scripts/rebuild_outputs.py`, running after rebuild steps complete.

Initial behavior:
- Report-only.
- No non-zero exit.
- Promoted FAIL hits are logged as ERROR.
- Frontend export is not blocked.

Later behavior:
- Promoted FAIL/WARN status should flow into frontend quality metadata so public charts can show verified/preliminary/under-review status.
- Blocking frontend export can be considered only after the rule set has passed at least one production triage cycle.

### Outer loop

Quarterly agent-assisted rule proposal remains outside the first implementation.

Agent scans:
1. `validation_rules_aggregate.csv`
2. `validation_rules_detail.csv`
3. new-quarter distribution shifts and novel CIK patterns

It writes proposed additions to:

```
validation_rules_candidates.csv
candidate_id | proposed_sql | rationale | expected_category | proposed_severity
```

A human must approve candidate rules before they enter the registry.

---

## Files to Create or Modify

| File | Action |
|------|--------|
| `pipeline/validation_rules/__init__.py` | Create |
| `pipeline/validation_rules/_registry.py` | Create |
| `pipeline/validation_rules/_runner.py` | Create |
| `pipeline/validation_rules/_temporal.py` | Create |
| `pipeline/validation_rules/_strategy.py` | Create |
| `pipeline/validation_rules/_relational.py` | Create |
| `pipeline/validation_rules/_cross_source.py` | Create |
| `pipeline/validation_rules/_index.py` | Create |
| `pipeline/validation_rules/_postcondition.py` | Create |
| `pipeline/validation_rules/_freshness.py` | Create |
| `pipeline/validation_rules/_matching.py` | Create |
| `tests/test_validation_rules.py` | Create |
| `pipeline/config.py` | Add output path constants |
| `pipeline/main.py` | Add `--validate-rules`, `--rules-category` |
| `scripts/rebuild_outputs.py` | Add optional `--validate-rules` step |

---

## Testing

- Parametrized syntax tests: every registered rule executes against minimal fixture tables without SQL errors.
- Trigger scenario tests: V1 PC/IDX/T01/T02/R07/M02 rules produce expected hit counts on crafted fixtures.
- Zero-hit tests: clean fixture data produces no findings for promoted FAIL rules.
- Missing-table tests: non-critical missing inputs produce skipped aggregate rows, not a broken run.
- Output schema tests: aggregate/detail CSVs contain required columns and deterministic `finding_key` values.
- Integration test: end-to-end small fixture run writes aggregate and detail files.

---

## Verification

After implementation:

1. `pytest tests/test_validation_rules.py`
2. `python -m pipeline.main --validate-rules`
3. `python -m pipeline.main --validate-rules --rules-category PC`
4. Inspect `validation_rules_aggregate.csv` for expected rule count, statuses, hit counts, and skipped reasons.
5. Inspect `validation_rules_detail.csv` for materiality-ranked findings and stable finding keys.
6. Run `pytest tests/` before considering the change integrated.

Because `pytest tests/` can overwrite output CSVs with fixtures in this repo, rebuild production outputs before treating `data/output/` or `frontend/public/data/` as production data.

---

## Runtime Estimates

Current artifact sizes:

| Artifact | Rows | Size |
|----------|------|------|
| `private_markets_holdings.csv` | 718,059 | 387 MB |
| `position_matches.csv` | 513,089 | 205 MB |
| `position_returns.csv` | 521,222 | 177 MB |
| `index_returns.csv` | 210 | 38 KB |
| `fund_financials.csv` | 6,858 | 2.7 MB |
| `nport_holdings.csv` | 7,908,483 | 2.35 GB |

Representative DuckDB scans over the current artifacts run sub-second for unified holdings and downstream return/match checks when only needed columns are scanned. The real runtime depends on whether the runner materializes tables once or reparses CSVs rule-by-rule.

Expected runtime with per-table materialization:

| Category | Rules | Primary tables | Estimated time |
|----------|-------|----------------|----------------|
| PC | 12 | holdings, position_returns, index/front-end artifacts | 2-5s |
| IDX | 10 | index_returns | <1s |
| V1 extra rules | 4 | holdings, fund_financials, position_matches | 2-8s |
| R | 15 | holdings, fund_financials | 5-10s |
| T | 10 | holdings window/grouped views | 5-15s |
| S | 10 | holdings + fund_financials | 5-10s |
| XS | 6 | holdings cross-source subset | 3-8s |
| F | 10 | holdings + combined_universe + filings indexes | 3-8s |
| M | 10 | position_matches | 5-15s |
| Full 83-rule run | 83 | loaded once per table | 10-45s typical; 45-90s conservative |

Rules that broadly scan raw `nport_holdings.csv` can add several seconds by themselves and should be avoided in the normal path unless the rule explicitly requires raw-source evidence.

