# Wrapper Validation (Steps 3-6 + Validation Pitfalls)

This document covers validation, testing, promotion gates, and validation pitfalls.

---

## Step 3: Validate the Wrapper

Validation has four levels: schema, staging oracle, trial unified rebuild, and production promotion gate.

### 3a. Schema validation

```bash
python -m jsonschema -i data/overrides/bdc_xbrl_wrappers/{CIK}.json schemas/bdc_xbrl_wrapper/wrapper_v3.schema.json
```

Also run the static coherence check to catch cross-section misconfigurations early:

```python
import json
from pipeline.bdc_xbrl_wrapper_oracle import validate_wrapper_json_coherence

with open('data/overrides/bdc_xbrl_wrappers/{CIK}.json') as f:
    raw = json.load(f)
issues = validate_wrapper_json_coherence(raw)
if issues:
    for issue in issues:
        print(f'  COHERENCE: {issue}')
else:
    print('Coherence check passed')
```

This only proves the JSON is syntactically valid and internally consistent.

### 3b. Run staging-level oracle

Use this during development to test current staging rules against cached raw BDC holdings for the CIK:

```bash
python -m pipeline.bdc_xbrl_wrapper_oracle --cik {CIK} --compare-baseline --fresh-bdc-staging
```

Check oracle output for:
- `remaining_blocking_rows`
- `remaining_blocking_fair_value`
- `remaining_wrapper_blocking_rows`
- `unclassified_rate` and `unclassified_fv_rate`
- `oracle_status` and `oracle_fail_reasons`

Inspect these artifacts:

- `oracle_summary.csv`
- `remaining_blockers.csv`
- `remaining_blocker_mechanisms.csv`
- `baseline_comparison.csv`

If the run used `--promotion-gate`, also inspect:

- `promotion_comparison.csv`
- `promotion_verdict.json`
- `exception_proposals.json`

`oracle_status` and `oracle_fail_reasons` are the raw deterministic oracle result. `effective_oracle_status`, `waived_oracle_reasons`, and `unwaived_oracle_reasons` are promotion-gate interpretation fields after accepted soft-gate exceptions are applied.

Treat these mechanisms as unresolved unless there is clear evidence and a documented acceptance rationale:

- `wrapper_blockers_remaining`
- `leaf_present_in_raw_missing_from_unified`
- `leaf_output_candidate_unmatched`
- `unclassified_signature`
- `category_rollup_source_child_fv_mismatch`
- material cost/FV or rate outliers

Do not let an agent "override" the oracle by silently changing row classifications. The agent may propose an audited exception only for eligible soft diagnostics, and only as a promotion-gate interpretation. Source reconciliation rows, wrapper classifications, and raw oracle results remain unchanged.

#### Soft-gate exception workflow

When a promotion gate writes `exception_proposals.json`, proposals are inactive templates. They do not apply until an accepted record is added to `data/overrides/bdc_xbrl_oracle_exceptions.json`.

Accepted exception records must match exactly on:

- `cik`
- `report_date`
- `oracle_reason`
- `wrapper_version`

They must also include:

- `status`: `accepted`
- `confidence`: `>= 0.80`
- `reason`
- `evidence`
- `residual_risk`
- `created_by`
- `accepted_by`
- `updated_at`

Only these review-style reasons are waiveable:

- `unclassified_rate_exceeded`
- `unclassified_fv_rate_exceeded`
- `unclassified_rate_qoq_jump`
- `content_signatures_fail`
- `unparsed_remainder_rows`
- `unparsed_remainder_spike`
- `low_position_continuity`
- `rate_outliers_detected`
- `cost_fv_ratio_outliers`
- `concept_drift_detected`
- `fv_magnitude_shift_detected`
- `rate_magnitude_shift_detected`
- `cost_magnitude_shift_detected`
- `spread_magnitude_shift_detected`

These remain non-waiveable:

- source reconciliation blockers
- `wrapper_blockers_remaining`
- `wrapper_no_archetypes`
- blocker row or FV regressions versus baseline
- `remaining_*` blocker mechanisms
- `exclusion_risk_detected`

Use exceptions for "the wrapper is acceptable despite this soft diagnostic" cases, not for fixing extraction. If a parser rule, dispatch pattern, or staging mechanism is wrong, update the wrapper instead of accepting an exception.

### 3c. One-CIK trial unified rebuild (fast inner loop)

Rebuild unified holdings for just the target CIK into a trial directory, then run the oracle against the trial artifact. This takes seconds instead of the 30+ minutes required for a full production rebuild.

```bash
python scripts/rebuild_unified_cik_trial.py --cik {CIK}
```

This reads from the existing production `bdc_holdings.parquet` and `nport_holdings.parquet`, filters to the target CIK, and runs the full unified-holdings pipeline with trial output paths. The wrapper staging logic is applied during the build, so wrapper changes are reflected.

Trial artifacts are written to `data/output/bdc_xbrl_wrapper_trial/{CIK}/unified_trial/` and include:
- `private_markets_holdings.{CIK}.csv` -- one-CIK unified holdings
- `universe_orphan_holdings.{CIK}.csv` -- orphan rows (if any)
- `trial_vs_production_summary.{CIK}.csv` -- row/FV diff vs current production

Then run the oracle against the trial file:

```bash
python -m pipeline.bdc_xbrl_wrapper_oracle --cik {CIK} --compare-baseline \
    --holdings-file data/output/bdc_xbrl_wrapper_trial/{CIK}/unified_trial/private_markets_holdings.{CIK}.csv
```

This tests the unified-level output (classification, cost proxy, pct correction, etc.) without overwriting production data. Use this as the default iteration gate after schema/tests/staging oracle.

`--holdings-file` is mutually exclusive with `--fresh-bdc-staging`.

### 3c-match. Trial position matching (cross-quarter feedback)

Add `--match` to the trial rebuild to run position matching on the trial output and get immediate cross-quarter matching feedback:

```bash
python scripts/rebuild_unified_cik_trial.py --cik {CIK} --match
```

This produces additional artifacts in the trial directory:
- `position_matches.{CIK}.csv` -- matched position pairs for this CIK
- `matching_diagnostic.{CIK}.csv` -- D_fuzzy fallback diagnostics showing which position key tokens differ between begin/end sides

The script logs:
- **Match tier distribution** -- what percentage of matches use each tier (B1b, B2, C, D_fuzzy, etc.)
- **J01 result** -- B1b position key stability rate (target: >= 70%)
- **J03 result** -- fuzzy fallback rate (target: <= 10%)
- **Fuzzy diagnostic preview** -- first 10 D_fuzzy matches with position key diffs

Use this to iterate on `canonical_strip_re` and `prefix_rules`. If J03 shows high fuzzy fallback, the diagnostic CSV shows exactly which tokens in the position key are volatile across quarters (e.g., embedded percentages changing from `"7 32"` to `"7 09"`). Fix those by adding patterns to `canonical_strip_re` to strip the volatile components.

**Position key quality requirements for B1b matching:**
- Keys must be >= 12 characters with >= 3 tokens
- Keys must contain at least one 4+ letter distinctive token (not just generic words like "term loan senior secured")
- Keys must be unique within each CIK/source/report quarter -- repeated keys cannot form B1b edges
- Placeholder keys (`"nc nc"`, `"lass units"`, etc.) are automatically rejected

### 3c-2. Position match quality review (C/D/E pair triage)

After trial matching stabilizes J01/J03, review C/D/E match quality:

```bash
python scripts/rebuild_unified_cik_trial.py --cik {CIK} --match
```

Inspect `match_triage.{CIK}.csv` in the trial directory. Each C/D/E pair
has boolean flag columns indicating potential issues:

- `flag_classification_flip`: begin/end index_classification differ
- `flag_subtype_mismatch`: instrument sub-type differs (term_loan vs revolver)
- `flag_maturity_gap`: maturity dates >365 days apart
- `flag_fv_ratio_extreme`: FV ratio >10x
- `flag_rate_discontinuity`: interest rate differs >5 pct pts

For each flagged pair (work highest FV first):

1. **Determine root cause**: Is this a wrapper issue, a matcher issue, or correct?
2. **Wrapper-fixable**: Update `canonical_strip_re`, `pipe_field_map`, or
   `prefix_rules` in the wrapper JSON, re-run trial, verify the pair now
   matches at a higher tier or the flag resolves.
3. **Override needed**: Write to `data/overrides/position_match_overrides/{CIK}.json`:
   - `reject`: Remove the pair (position becomes unmatched)
   - `force_pair`: Replace the end-side assignment
4. **Correct-despite-flag**: No action needed; the heuristic is a false positive.
5. Re-run `--match` to verify fixes took effect.

### 3d. Production promotion gate (full rebuild)

Before labeling a wrapper `production_clean`, run the full production rebuild and oracle:

```bash
python scripts/rebuild_outputs.py --unified
python -m pipeline.bdc_xbrl_wrapper_oracle --cik {CIK} --promotion-gate
python scripts/diff_outputs.py --semantic
```

Target result:

- raw `oracle_status`: `pass` for all relevant quarters, or raw failures limited to accepted waiveable soft reasons
- `effective_oracle_status`: `pass` for all relevant quarters
- `waived_oracle_reasons`: populated only for accepted soft-gate exceptions with documented evidence
- `unwaived_oracle_reasons`: empty for all relevant quarters
- `remaining_blocking_rows`: `0`, or explicitly accepted residuals
- no increase in blocking rows or blocking FV versus baseline
- documented improvements in `promotion_comparison.csv` and `baseline_comparison.csv` if the wrapper was intended to clear blockers
- `diff_outputs.py --semantic` shows expected deltas only

If this fails, the wrapper is partial. Summarize affected quarters, mechanisms, row counts, FV exposure, waived/unwaived reasons, and whether blockers decreased versus baseline. Do not promote it as production-clean.

`diff_outputs.py --semantic` is only meaningful after canonical production artifacts are rebuilt -- do not run it against trial artifacts.

### 3e. Run staging extraction check

```python
# Check field extraction quality after staging
import duckdb, pandas as pd
from pipeline.staging_bdc import _prepare_bdc
from pipeline.config import BDC_HOLDINGS_PARQUET_FILE

path = str(BDC_HOLDINGS_PARQUET_FILE).replace("\\", "/")
con = duckdb.connect()
df = con.execute(f"""
    SELECT * FROM read_parquet('{path}')
    WHERE LPAD(REGEXP_REPLACE(CAST(cik AS VARCHAR), '[^0-9]', '', 'g'), 10, '0') = '{CIK}'
""").fetchdf()
con.close()

result = _prepare_bdc(df)
for col in ['issuer_name', 'instrument_description', 'bdc_investment_country',
            'extracted_industry', 'reference_rate_type']:
    filled = (result[col] != '').sum() if col in result.columns else 0
    print(f'{col}: {filled}/{len(result)} ({100*filled/len(result):.1f}%)')
```

If `identifier_parser` or `staging` config was added, confirm the target CIK appears in the loader output. A dispatch-only wrapper will not show up as a staging config.

### 3f. Run tests

```bash
pytest tests/test_bdc_xbrl_wrapper.py -v
pytest tests/test_unified_cik_trial.py -v
pytest tests/test_position_matching.py -v
pytest tests/test_oracle_checks.py -k "J01 or J03 or J04 or DiagnoseFuzzy" -v
pytest tests/test_unified_holdings.py -k "not slow" --tb=short -q
```

---

## Step 4: Write Tests

Add tests to `tests/test_bdc_xbrl_wrapper.py` for:
- `classify_identifier()` returns correct dispositions for sample identifiers
- Leaf positions get `{family}_position_leaf` disposition
- Aggregate/subtotal rows get `aggregate` or `{family}_category_rollup`
- Non-private markers catch cash/money-market rows

If `identifier_parser` or `staging` config was added, add extraction tests to `tests/test_unified_holdings.py`:
- Correct `issuer_name`, `instrument_description` for representative identifiers
- Correct `bdc_investment_country`, `extracted_industry` if applicable
- Non-CIK regression: verify other CIKs are unaffected

---

## Step 5: HTML vs XBRL Evidence

Do not conflate cached source availability with validation:

- Cached HTML and `.grids.json` files prove the filing is available locally, not that extraction is valid.
- HTML template validation only applies when the template actually selects tables for those accessions.
- For XBRL-era BDC wrappers, default validation source is cached XBRL source facts reconciled to final `private_markets_holdings.csv`.
- Do not claim HTML validation for XBRL wrapper behavior unless HTML extraction actually covers the same periods and accessions.

For pre-XBRL periods, use the HTML template workflow separately and report its validation status independently from the XBRL wrapper oracle.

---

## Step 6: Partial Wrapper Verdict

If the oracle does not pass, write a concise verdict before stopping or promoting:

- CIK and entity name
- source basis used: cached XBRL source facts, fresh BDC staging, final unified holdings, HTML template validation, or a combination
- relevant quarter range
- source row count, output row count, remaining blocking rows, and remaining blocking FV
- top residual mechanisms and sample identifiers
- baseline comparison: blockers reduced, unchanged, or increased
- explicit status: `production_clean`, `partial_wrapper`, `review_required_with_accepted_soft_exceptions`, or `blocked_no_safe_mechanism`
- any accepted soft-gate exceptions: reason, confidence, evidence, and residual risk

A partial wrapper can still be useful as a diagnostic, but it must not be described as complete.

---

## Validation Pitfalls

### Pitfall 5: Optimize for data quality, not oracle metrics

**Anti-pattern:** Adding broad archetype keywords (e.g. `"Debt "` with trailing space) to suppress `unclassified_fv_rate` without investigating what the oracle is actually signaling. This masks real bugs.

**Correct approach:** When a metric fails, investigate the ROWS driving the failure before changing the wrapper. Check:
1. Are the failing rows actually in the output? (blocker check)
2. Do they have correct `issuer_name` and `instrument_description`? (extraction check)
3. Are they real positions or misclassified aggregates? (classification check)
4. Did the trial introduce identity changes (different `bdc_investment_identifier`) vs just new/lost rows? (regression check)

### Pitfall 6: Always compare trial vs production at the row level before trusting summary metrics

**Anti-pattern:** Running the trial, seeing "+88 new rows" in the summary, and assuming all 88 are genuine rescues.

**Correct approach:** Compare `bdc_investment_identifier` values between trial and production:

```python
trial_keys = set(zip(trial['report_date'], trial['bdc_investment_identifier']))
prod_keys = set(zip(prod['report_date'], prod['bdc_investment_identifier']))
new_keys = trial_keys - prod_keys
lost_keys = prod_keys - trial_keys
```

If `lost_keys` is large (especially close to the size of `new_keys`), most rows changed identity rather than being genuinely new. This signals an identifier corruption bug, not a wrapper improvement.

### Pitfall 7: Stale trial output

**Symptom:** Oracle or comparison results don't match expectations. Metrics look wrong despite code being correct.

**Cause:** Trial output files persist across runs. If a rebuild fails or runs against old module code, the output file isn't updated but still exists. Subsequent reads of the file return stale data.

**Prevention:** After every trial rebuild, check the file modification timestamp before reading results. If running diagnostics interactively, verify that `_prepare_bdc()` output matches expectations before trusting `build_unified_holdings()` output.
