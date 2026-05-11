# Constrained FAIL Verification Agent Plan

## Summary

Use a Codex terminal agent to verify open validation `FAIL` issues, but only inside a deterministic, evidence-backed review loop. The agent should not fix pipeline code, rewrite generated CSVs, weaken validators, or change thresholds in this loop.

The purpose is to decide whether each material `FAIL` is a real data error, a valid exception, a validator false positive, or unresolved due to insufficient evidence. The success metric is verdict accuracy and evidence quality, not reducing the number of `FAIL` rows.

## Recommended Approach

Use three components together:

1. A deterministic CLI harness that builds queues, evidence bundles, and validates verdict files.
2. A Codex terminal agent that reviews one bounded bundle at a time and writes a structured verdict.
3. A small Codex skill that instructs the agent how to review FAILs, what is allowed, what is forbidden, and how to handle uncertainty.

The harness is the control mechanism. The skill is instruction and consistency support. Do not rely on the skill alone for safety.

## Repository Layout

Keep the protocol source of truth in version-controlled repository paths. Keep generated evidence, verdicts, and summaries under `data/output/fail_verification/`.

```text
docs/fail_verification/
  instructions.md
  playbooks.md
  README.md

schemas/fail_verification/
  evidence_bundle.schema.json
  verdict.schema.json
  sample_manifest.schema.json
  examples/
    confirmed_data_error.x09.json
    confirmed_valid_exception.x06.json
    validator_false_positive.c402.json
    insufficient_evidence.gav01.json
    invalid_missing_evidence_refs.json

scripts/fail_verification/
  build_sample_manifest.py
  build_evidence_bundle.py
  validate_verdict.py
  summarize_verdicts.py

data/output/fail_verification/
  sample_manifest.csv
  bundles/
  verdicts/
  summaries/
```

The Codex skill, if added later, should be a thin repeatability layer over the repo-tracked instructions and playbooks. It must not be the only copy of the protocol.

## V1 Workflow

1. Build a queue from `data/output/row_validation_issues.csv`, restricted to `status=OPEN` and `severity=FAIL`.
2. Group issues by `rule_id`, `cik`, `report_date`, and materiality.
3. Prioritize current FAIL families in this order:
   - `X09`: pct of net assets greater than 100.
   - `C402`: bad debt maturity date parse.
   - `X06`: principal amount more than 10x fair value.
   - `C101`: missing fair value on indexable row.
   - `GAV01`: extreme GAV reconciliation miss.
4. Generate one immutable evidence bundle per verification group.
5. Let a Codex terminal agent claim one bundle.
6. Agent reads the bundle and allowed source artifacts only.
7. Agent writes exactly one verdict JSON to `data/output/fail_verification/verdicts/{verification_id}.json`.
8. Harness validates the verdict schema, evidence references, bundle fingerprint, and no-mutation guardrails.
9. Summaries aggregate confirmed error rate, false-positive rate, insufficient-evidence rate, and affected fair value.

## Codex Instance Output Contract

Each Codex instance receives exactly one evidence bundle and writes exactly one verdict JSON. If a bundle contains more than one rule, the bundle must define whether the `verification_id` is a group verdict or whether the harness should split it into single-rule bundles before assignment. V1 should prefer one rule per bundle.

The verdict JSON is the only authoritative output from the Codex instance. Completion messages, terminal logs, or conversational notes are not part of the verified record unless copied into the verdict JSON.

The verdict file path must be:

```text
data/output/fail_verification/verdicts/{verification_id}.json
```

The Codex instance may not create sidecar notes, temporary scripts, patched CSVs, or remediation files during the verification run. Any remediation idea belongs in `recommended_next_action` as a future action.

## Statistical Sampling

Verifying all 16,966 open FAILs is unnecessary. Use stratified random sampling to produce statistically valid verdict distributions per rule, then use those distributions to decide which rules warrant exhaustive review or threshold adjustment.

### FAIL Volume

| Rule | Population | Description |
|------|--------:|-------------|
| C101 | 8,004 | Missing fair_value on indexable row |
| X06 | 7,041 | Principal amount > 10x fair_value |
| GAV01 | 1,857 | GAV reconciliation ratio extreme (<0.3 or >5.0) |
| X09 | 58 | pct_of_net_assets > 100% |
| C402 | 6 | Maturity date year before 1900 on debt |
| **Total** | **16,966** | |

### Sample Size Formula

Use proportion estimation with finite population correction:

    n = (Z^2 * p * (1-p)) / E^2
    n_adj = n / (1 + (n - 1) / N)

Where:

- `Z` = 1.96 (95% confidence level)
- `p` = 0.5 (maximum variance; no prior on true error rate)
- `E` = margin of error
- `N` = rule population size

### Sampling Tiers

| Rule | Population | Strategy | Sample Size | Rationale |
|------|--------:|----------|--------:|-----------|
| C402 | 6 | Exhaustive | 6 | Population too small to sample |
| X09 | 58 | Exhaustive | 58 | Population small enough for full review |
| GAV01 | 1,857 | E = 0.10 | 91 | CIK-quarter level; each verdict covers many rows |
| X06 | 7,041 | E = 0.10 | 95 | 10% margin acceptable for first-pass triage |
| C101 | 8,004 | E = 0.10 | 95 | 10% margin acceptable for first-pass triage |
| **Total** | **16,966** | | **345** | |

If a rule's confirmed-error rate exceeds 30% after the first pass, tighten to E = 0.05 (~4x the sample) for that rule in a second pass.

### Sampling Units

Use the correct sampling unit for each rule:

- `C101`, `X06`, `X09`, and `C402`: one issue row, anchored to the corresponding holdings row and source record.
- `GAV01`: one CIK-quarter reconciliation issue, anchored to `holdings_gav_reconciliation.csv`; the row-level FAILs for that CIK-quarter are context, not the sampled unit.

### Stratification

Simple random sampling within each rule risks CIK concentration. A single BDC with many positions could dominate the sample and produce a verdict distribution that does not generalize.

Stratify by CIK within each rule:

1. For each rule, count issues per CIK.
2. If the rule sample size is smaller than the distinct CIK count, select CIK strata with probability proportional to issue count, then sample one issue from each selected CIK.
3. If the rule sample size is at least the distinct CIK count, assign one issue to each CIK first, then allocate remaining samples proportionally to issue count.
4. Within each selected CIK stratum, select rows randomly.

For `GAV01`, stratify by CIK and sample CIK-quarter rows within the selected CIK strata. Do not treat GAV stratification as implicit; a single CIK can contribute many quarters.

### Harness Sampling Procedure

1. Load `row_validation_issues.csv` filtered to `status=OPEN AND severity=FAIL`.
2. For rules with population <= 100 (X09, C402), add all rows to the queue.
3. For rules with population > 100 (C101, X06, GAV01), compute stratified sample using the CIK-proportional method above.
4. Tag each queued row with `sample_stratum` (the CIK) and `sample_weight` (`N_h / n_h` after stratum allocation) so verdict summaries can produce weighted estimates of rule-wide error rates.
5. Persist the sample selection as `data/output/fail_verification/sample_manifest.csv` with columns: `verification_id`, `rule_id`, `sampling_unit`, `cik`, `report_date`, `row_key`, `source`, `accession_number`, `source_record_id`, `issuer_name`, `position_id`, `sample_stratum`, `sample_weight`, `random_seed`, `source_file`, and `source_file_sha256`.
6. Use a fixed random seed (recorded in the manifest) for reproducibility.

`row_key` is not sufficient as a durable identity because it is derived from row order during validation. The manifest and bundle must materialize enough source identity to survive rebuilds and to prove which row was reviewed.

### Interpreting Results

- **Weighted error rate** = sum(sample_weight * is_confirmed_error) / sum(sample_weight), per rule.
- **95% confidence interval** = bootstrap by CIK for row-level rules or by CIK-quarter for `GAV01`, or use a stratified standard error on the weighted estimate. Wilson intervals are acceptable only for unweighted simple random samples.
- If the lower bound of the CI exceeds 0.10 (10% confirmed errors), the rule has a systemic data problem and warrants pipeline-level remediation.
- If the upper bound of the CI is below 0.05 (5% confirmed errors), the rule is predominantly false positives and should be considered for threshold adjustment (as deferred work).
- Rules in between warrant a second sampling pass at E = 0.05.

## Verdict Schema

Each verdict must use one of:

- `CONFIRMED_DATA_ERROR`
- `CONFIRMED_VALID_EXCEPTION`
- `VALIDATOR_FALSE_POSITIVE`
- `INSUFFICIENT_EVIDENCE`

Verdict semantics:

- `CONFIRMED_DATA_ERROR`: the validation condition is real and the reviewed data is unsafe for the affected downstream use.
- `CONFIRMED_VALID_EXCEPTION`: the validation condition is real, but the underlying data is valid or explainable and should be handled as an accepted residual or disclosure candidate.
- `VALIDATOR_FALSE_POSITIVE`: the validator logic is wrong or too broad for this case; the current data should not have been marked as a FAIL.
- `INSUFFICIENT_EVIDENCE`: the bundle does not support a defensible conclusion.

Do not use `VALIDATOR_FALSE_POSITIVE` merely because the root cause is upstream extraction or classification. If the validator correctly detected unsafe output caused by an upstream defect, use `CONFIRMED_DATA_ERROR` and set `validator_assessment.validator_correct` to `true`.

Required verdict fields:

- `schema_version`
- `verification_id`
- `bundle_id`
- `bundle_sha256`
- `created_at`
- `rule_id`
- `cik`
- `report_date`
- `row_key`
- `verdict`
- `confidence`: `low`, `medium`, or `high`
- `mechanism`
- `validator_assessment`
- `determination_rationale`
- `evidence_refs`
- `recommended_next_action`
- `agent_notes`
- `anti_sycophancy_check`

`validator_assessment` must include:

- `rule_condition_true`: boolean
- `validator_correct`: boolean
- `material_risk_real`: boolean
- `root_cause`: controlled string such as `SOURCE_MISSING_VALUE`, `EXTRACTION_GAP`, `CLASSIFICATION_ERROR`, `DIMENSION_PATH_DUPLICATION`, `SCALE_MISMATCH`, `SOURCE_COMPARISON_ERROR`, `VALID_SOURCE_EXCEPTION`, or `UNKNOWN`

`determination_rationale` must include:

- `why_this_verdict`
- `why_not_alternative`
- `residual_uncertainty`

`evidence_refs` must be an array of objects, not bare strings. Each object must include:

- `evidence_id`
- `supports`

`recommended_next_action` must be structured. At minimum it must include:

- `action_type`: one of `PIPELINE_REMEDIATION_REVIEW`, `ACCEPT_RESIDUAL_REVIEW`, `VALIDATOR_REVIEW`, `MANUAL_SOURCE_REVIEW`, or `NO_ACTION`
- `summary`

The `anti_sycophancy_check` must state the strongest alternative explanation and why it was rejected or left unresolved. This is required because the agent should not simply confirm the user's or prior validator's preferred interpretation.

### Example Requirements

Schema examples should live under `schemas/fail_verification/examples/`.

Include:

- One valid example for each verdict type.
- At least one valid example for `C101`, `X06`, `X09`, and `GAV01`.
- Invalid examples that the harness must reject, including missing evidence references, unsupported enums, mismatched bundle hash, direct mutation recommendations, and high confidence with unsupported rationale.

Examples calibrate agent judgment, but the JSON Schema and `validate_verdict.py` are the enforcement mechanism.

## Evidence Bundle Requirements

Each evidence bundle should include stable evidence IDs that the verdict can cite.

Each bundle must include:

- `bundle_id`
- `schema_version`
- `created_at`
- `source_artifacts`, with file paths and SHA256 hashes
- `sample_manifest_row`
- `evidence_items`, keyed by stable `evidence_id`

For row-level rules:

- The issue row from `row_validation_issues.csv`.
- The joined row from `private_markets_holdings.csv` using `row_key` plus stable row identity fields.
- Stable identity fields: source, CIK, report date, accession number, source-specific ID, issuer name, `position_id` when present, full materialized holdings row, source file path, and source file SHA256.
- Nearby rows for the same `cik`, `report_date`, and issuer where relevant.
- Source-specific raw fields such as BDC raw identifier/dimensions or N-PORT holding metadata.

For `GAV01`:

- The matching row from `holdings_gav_reconciliation.csv`.
- Holdings fair value totals and comparison value/source.
- Related row-level FAILs for the same CIK/date.
- Coverage metrics where available.

For BDC source rows:

- `accession_number`, raw investment identifier, dimensions, extracted numeric values, and cached filing path when available.

For N-PORT source rows:

- N-PORT holding ID, series metadata, source asset/issuer fields, principal, cost, and fair value.

The harness must reject verdicts that cite evidence IDs not present in the bundle.

## Strict Validation Responsibilities

`schemas/fail_verification/verdict.schema.json` enforces structure:

- Required fields.
- Enum values.
- Field types.
- Minimum string lengths.
- No unsupported extra properties.
- Allowed `root_cause` and `recommended_next_action.action_type` values.

`scripts/fail_verification/validate_verdict.py` enforces runtime facts:

- Verdict JSON parses and satisfies the schema.
- `verification_id` exists in `sample_manifest.csv`.
- `bundle_id` exists and `bundle_sha256` matches the actual bundle file.
- `rule_id`, `cik`, `report_date`, and row identity fields match the sample manifest and bundle.
- Every `evidence_refs[].evidence_id` exists in the bundle.
- The verdict does not recommend direct mutation of pipeline code, generated holdings CSVs, validation CSVs, frontend data, docs, or schemas.
- `high` confidence verdicts cite enough relevant evidence to support the claim.
- `INSUFFICIENT_EVIDENCE` verdicts identify which required evidence is missing or ambiguous.

The validator should fail closed. If a verdict cannot be tied to the exact bundle and manifest row, reject it.

## Rule-Specific Playbooks

Each playbook defines the review procedure for one FAIL family. The agent must follow the playbook for the relevant `rule_id` when reviewing an evidence bundle. If a bundle spans multiple rules, apply each playbook independently.

### Playbook: C101 -- Missing fair_value on indexable row

**Trigger condition:** `fair_value IS NULL AND index_classification NOT IN ('', 'UNCLASSIFIED')`

**Evidence to gather:**

1. The `private_markets_holdings.csv` row via `row_key`.
2. The raw source row: `bdc_holdings.csv` (match on `cik`, `accession_number`, `investment_identifier`) or `nport_holdings.csv` (match on holding ID).
3. Up to 5 nearby rows from the same CIK and `report_date` to check whether FV is systematically missing.
4. `fund_financials.csv` for the CIK to confirm the fund was active in that period.

**Decision tree:**

| Finding | Verdict | Confidence | Recommended Action |
|---------|---------|------------|-------------------|
| Row is an aggregate header (issuer_name matches patterns like "Total Investments" or "Subtotal") | `CONFIRMED_DATA_ERROR` | high | Add pattern to aggregate filter |
| Row has `shares_held` but no FV (equity stub with zero or missing valuation) | `CONFIRMED_VALID_EXCEPTION` | medium | Mark as zero-FV equity; exclude from index weight but retain in constituent count |
| Raw source row also has no FV (confirmed missing at source) | `CONFIRMED_DATA_ERROR` | high | Exclude from index; no pipeline fix possible without SEC amendment |
| Raw source row has FV but unified row does not (parsing/extraction gap) | `CONFIRMED_DATA_ERROR` | high | Flag for extraction fix; cite accession_number and field name |
| `index_classification` is incorrect and caused an indexable row to be unsafe | `CONFIRMED_DATA_ERROR` | medium | Recommend reclassification review for this issuer pattern |
| Cannot locate raw source row | `INSUFFICIENT_EVIDENCE` | low | Note missing source path; may indicate a filing gap |

**Common pitfalls:**

- Do not assume FV is missing because the position is worthless. BDCs report zero-FV positions explicitly; a truly null FV usually means the field was not extracted.
- N-PORT positions always have FV (it is a required field). A C101 on an N-PORT row likely indicates a join or extraction defect.
- Check `dimensions_raw` for BDC rows: if it contains "Total" or "Subtotal" in a dimension member name, this is almost certainly an aggregate header leak.

### Playbook: X06 -- Principal amount > 10x fair_value

**Trigger condition:** `fair_value > 0 AND principal_amount > 10 * fair_value`

**Evidence to gather:**

1. The `private_markets_holdings.csv` row via `row_key`. Record the exact ratio: `principal_amount / fair_value`.
2. The raw `bdc_holdings.csv` row (match on `cik`, `accession_number`, `investment_identifier`). Check `principal_amount`, `fair_value`, and `cost` as reported.
3. Up to 10 other rows from the same CIK and `report_date`. Compute their principal/FV ratios to detect a systematic scale mismatch.
4. `fund_financials.csv` for the CIK: check `total_assets` and `total_investments` to see if fund-level aggregates are consistent with position-level units.
5. The `interest_rate` and `basis_spread` fields on the flagged row (a position with a normal coupon and 100:1 principal/FV ratio is almost certainly a scale error, not distress).

**Decision tree:**

| Finding | Verdict | Confidence | Recommended Action |
|---------|---------|------------|-------------------|
| Other positions from the same CIK/filing show the same ~10-1000x ratio consistently | `CONFIRMED_DATA_ERROR` | high | Likely thousands-vs-dollars scale mismatch for this filer; flag CIK for unit normalization |
| Ratio is 10-20x and interest_rate is 0 or missing (deeply distressed or equity-like position) | `CONFIRMED_VALID_EXCEPTION` | medium | Position may be near default; principal exceeds recovery value |
| Ratio is 10-20x and position is a revolving credit facility or unfunded commitment | `CONFIRMED_VALID_EXCEPTION` | medium | Principal = total commitment, FV = drawn amount; document the instrument type |
| Principal and FV come from different XBRL contexts (different `period` dates) | `CONFIRMED_DATA_ERROR` | high | Context mismatch in extraction; cite the two period values |
| Raw source row shows the same values (no extraction defect) and no pattern across CIK | `INSUFFICIENT_EVIDENCE` | low | May be a one-off filer data entry error; no remediation available |
| Only 1-2 positions from the CIK are flagged and others look normal | `CONFIRMED_DATA_ERROR` | medium | Likely a per-position extraction or tagging error |

**Common pitfalls:**

- BDC XBRL does not enforce unit consistency. Some filers report principal in thousands and FV in dollars (or vice versa). Always check multiple positions from the same filing before concluding it is a single-position error.
- Do not confuse `cost` with `principal_amount`. Cost is the acquisition price; principal is the par/face value. A high principal/FV ratio does not imply a high cost/FV ratio.
- Revolving credit facilities legitimately have principal (commitment) much larger than FV (drawn and marked). Check `investment_identifier` or `bdc_investment_identifier` for keywords like "Revolver", "Revolving", "Delayed Draw", "Unfunded".

### Playbook: X09 -- pct_of_net_assets > 100%

**Trigger condition:** `pct_of_net_assets > 100.0`

**Evidence to gather:**

1. The `private_markets_holdings.csv` row via `row_key`. Record the exact `pct_of_net_assets` value.
2. All rows from the same CIK and `report_date` in `private_markets_holdings.csv`. Sum their `pct_of_net_assets` to get the CIK-quarter total.
3. `holdings_pct_sum.csv` for the same CIK/report_date (if available).
4. `fund_financials.csv` for the CIK: check `net_assets` and `leverage_ratio`. A near-zero or negative `net_assets` denominator explains extreme percentages.
5. `dimensions_raw` from the raw `bdc_holdings.csv` row: look for multiple dimension paths (e.g., both an affiliation axis and an investment-type axis tagging the same position).
6. Check whether current validation artifacts show the CIK has repeated dimension-path rows with matching FV. If a curated multi-dimension reference file is added later, the harness may use it, but it must not depend on conversational or assistant-specific notes.

**Decision tree:**

| Finding | Verdict | Confidence | Recommended Action |
|---------|---------|------------|-------------------|
| Position appears under 2+ dimension paths with matching FV and inflates holdings, FV, or GAV | `CONFIRMED_DATA_ERROR` | high | Dimension-path duplication; residual survived dedup due to different parsed issuer_name |
| CIK-quarter pct_sum is 200-400% due to duplicated dimension paths | `CONFIRMED_DATA_ERROR` | high | Systemic CIK-level duplication; document for cross-path entity matching (deferred work) |
| `net_assets` from fund_financials is negative or < $1M for that report_date | `CONFIRMED_VALID_EXCEPTION` | high | Near-zero denominator; pct_of_net_assets is mathematically correct but misleading |
| Position is from a leveraged fund with leverage_ratio > 1.5 AND pct is 100-150% | `CONFIRMED_VALID_EXCEPTION` | medium | Leveraged exposure; position size legitimately exceeds equity |
| No duplication detected AND net_assets is normal AND leverage is low | `CONFIRMED_DATA_ERROR` | medium | Likely a reporting or extraction error in the pct_of_net_assets field |

**Common pitfalls:**

- Do not assume all >100% values are errors. BDCs are leveraged vehicles; a position that is 105% of net assets is unusual but not impossible for a concentrated, leveraged fund.
- Always check the CIK-quarter total pct_sum before concluding on an individual position. If the total is ~200%, the issue is systemic duplication, not a single-position problem.
- The affiliation-axis dedup (V7) already resolves many of these. If the position survived dedup, it is likely because different dimension paths produce different `issuer_name` values. Document both names in the verdict and treat polluted holdings as a data error, not an accepted exception.

### Playbook: C402 -- Maturity date year before 1900 on debt

**Trigger condition:** `YEAR(maturity_date) < 1900 AND (asset_category IN ('LOAN', 'DEBT') OR asset_class = 'PRIVATE_CREDIT')`

**Evidence to gather:**

1. The `private_markets_holdings.csv` row via `row_key`. Record the exact `maturity_date` value.
2. The raw source row (`bdc_holdings.csv` or `nport_holdings.csv`). Check the raw `maturity_date` field before any parsing.
3. Up to 5 other positions from the same CIK and `report_date` that have valid maturity dates, to confirm parsing works for other positions.
4. If the raw date looks like a 2-digit year (e.g., "25", "0025"), note the likely intended year.
5. If the raw date is a sentinel (e.g., "0001-01-01", "1899-12-31"), check whether other positions from the same filer use the same sentinel.

**Decision tree:**

| Finding | Verdict | Confidence | Recommended Action |
|---------|---------|------------|-------------------|
| Raw maturity_date is a 2-digit year that was parsed as a year < 100 (e.g., "25" became "0025-XX-XX") | `CONFIRMED_DATA_ERROR` | high | Date parsing bug; recommend adding century expansion logic for this pattern |
| Raw maturity_date is a sentinel value like "0001-01-01" and other positions from the same filer use it consistently | `CONFIRMED_VALID_EXCEPTION` | medium | Filer convention for "no maturity" or "perpetual"; recommend mapping to the 9999-12-31 sentinel |
| Raw maturity_date is a valid post-1900 date but was corrupted during extraction | `CONFIRMED_DATA_ERROR` | high | Extraction defect; cite the raw vs. parsed values |
| Cannot find the raw source row to compare | `INSUFFICIENT_EVIDENCE` | low | Note the missing source linkage |
| The position's `asset_category` or `asset_class` is wrong and the current output is unsafe | `CONFIRMED_DATA_ERROR` | medium | Classification error caused the rule to fire on a non-debt position; recommend classification review |
| The validator applied the debt maturity rule to a row whose output classification is already non-debt | `VALIDATOR_FALSE_POSITIVE` | medium | Validator rule is too broad for this case |

**Common pitfalls:**

- With only 6 rows, each verdict is worth documenting thoroughly. These are likely all the same root cause (one or two filers with a parsing pattern). Check whether they share a CIK.
- Do not assume a pre-1900 date means the maturity_date column is generally broken. The validator already confirms that the vast majority of debt maturity dates parse correctly; this rule fires on rare edge cases.
- If all 6 rows come from the same CIK, the verdict can be written once with a batch justification, but the harness should still produce 6 individual verdict JSON files.

### Playbook: GAV01 -- GAV reconciliation ratio extreme

**Trigger condition:** `gav_ratio_adjusted < 0.3 OR > 5.0` where available, otherwise `gav_ratio < 0.3 OR > 5.0` (CIK-quarter level). The comparison value may be `investments_at_fair_value`, `total_assets_companyfacts`, or `total_assets_nport`.

**Evidence to gather:**

1. The `holdings_gav_reconciliation.csv` row for the CIK and `report_date`. Record `gav_ratio`, `gav_ratio_adjusted`, `comparison_value`, `comparison_source`, `sum_holdings_fv`, and position count.
2. `fund_financials.csv` for the CIK: check `total_assets`, `investments_at_fair_value`, `net_assets`, and `source` (companyfacts, nport, ncsr). Confirm which value was used as the comparison and whether it is reliable.
3. Count of row-level FAILs (C101, X06) for the same CIK and `report_date` in `row_validation_issues.csv`. A high count of C101 (missing FV) explains a low GAV ratio.
4. `holdings_count_stability.csv` for the CIK: check whether the position count for this quarter is an outlier versus adjacent quarters.
5. `bdc_filings_index.csv`: confirm the filing exists and was successfully parsed. Check `form_type` (10-K vs. 10-Q) and whether adjacent quarters have filings.

**Decision tree:**

| Finding | Verdict | Confidence | Recommended Action |
|---------|---------|------------|-------------------|
| Ratio < 0.3 AND C101 count for the same CIK/date is > 50% of position count | `CONFIRMED_DATA_ERROR` | high | GAV miss is caused by systematic missing FV; root cause is extraction gap |
| Ratio < 0.3 AND comparison_source is unreliable (e.g., stale companyfacts, wrong fiscal period) | `VALIDATOR_FALSE_POSITIVE` | medium | Comparison value is wrong; flag this comparison_source as unreliable for this CIK |
| Ratio > 5.0 AND duplicated dimension paths inflate `sum_holdings_fv` | `CONFIRMED_DATA_ERROR` | high | Duplication inflates sum_holdings_fv; document the duplication factor |
| Ratio > 5.0 AND X06 count for the same CIK/date is > 20% of position count | `CONFIRMED_DATA_ERROR` | high | Scale mismatch inflating FV aggregation |
| Ratio < 0.3 AND the fund is in wind-down (position count < 10, total_assets declining across quarters) | `CONFIRMED_VALID_EXCEPTION` | medium | Residual portfolio in liquidation; few positions remain |
| Ratio is extreme but the comparison_value is from a subsidiary structure (parent vs. consolidated) | `CONFIRMED_VALID_EXCEPTION` | medium | Entity mismatch between holdings source and financials source |
| No clear explanation from available evidence | `INSUFFICIENT_EVIDENCE` | low | Escalate for manual review of the SEC filing |

**Common pitfalls:**

- GAV01 is a CIK-quarter-level rule, not a row-level rule. The verdict applies to the entire CIK/date combination, not to individual positions. The evidence bundle should include aggregate statistics, not individual row details (though row-level FAIL counts are relevant context).
- Always check `comparison_source`. If it says "companyfacts" for an N-PORT fund, the value is likely empty or stale (interval/tender fund companyfacts are usually empty). This is a false positive caused by a bad comparison, not a holdings problem.
- A GAV ratio of exactly 0.0 usually means extracted holdings FV is zero or near zero against a nonzero comparison value. Treat this as likely extraction or coverage failure unless evidence shows the comparison value is stale, wrong-period, or wrong-entity.
- Do not conflate GAV01 with pct_of_net_assets sum checks. GAV01 compares absolute FV against total_assets; pct checks compare the sum of percentages. They can disagree when net_assets differs from total_assets (i.e., when leverage is present).

## Guardrails

- The agent may write only verdict artifacts under `data/output/fail_verification/`.
- The agent may not edit pipeline source, generated holdings CSVs, validation CSVs, frontend data, or docs during a verification run.
- The agent may not change validation thresholds or recommend suppressing a rule without evidence.
- If evidence is missing or ambiguous, the correct verdict is `INSUFFICIENT_EVIDENCE`.
- Unsupported claims cap confidence at `low`.
- Any recommended remediation must be phrased as a future action, not performed during verification.
- High-impact verdicts should receive human review before remediation planning.
- The harness must record pre-run and post-run file hashes or use an equivalent diff check to reject any mutation outside `data/output/fail_verification/verdicts/`.
- All `high` confidence remediation-driving verdicts require human review before any pipeline, validator, threshold, or accepted-residual change is planned from them.

## Skill Role

A Codex skill is useful for repeatability, but it should not be treated as enforcement.

The skill should define:

- Allowed actions.
- Forbidden actions.
- The verdict taxonomy.
- The anti-sycophancy requirement.
- Rule-specific review playbooks (see the Rule-Specific Playbooks section above).
- Evidence standards.
- Escalation behavior when the source record is missing or ambiguous.

The CLI harness should still enforce schema validity, evidence references, allowed output paths, and non-mutation of source artifacts.

## Acceptance Criteria

- Queue generation is deterministic and includes only open FAIL issues.
- Evidence bundles can be generated for all five current FAIL families.
- Verdict JSON files validate against a strict schema.
- Invalid verdicts are rejected if they cite missing evidence IDs, use unsupported enums, or recommend direct mutation.
- Invalid verdicts are rejected if their bundle hash, rule identity, row identity, or manifest row does not match.
- Summary output reports verdict counts and affected fair value by rule.
- The workflow can be run by a Codex terminal agent without modifying pipeline code or generated source datasets.

## Deferred Work

- Applying accepted residuals back into validation tiers.
- Auto-remediation of extraction defects.
- Per-CIK correction files.
- Rule threshold changes.
- Frontend display of verification verdicts.

These should be planned only after enough verdicts establish which FAILs are true data errors versus validator false positives.
