# Wrapper Oracle Agent Review And Drift Design

## Status

This document is the finalized architecture for the BDC XBRL wrapper oracle
extensions. Some sections are already implemented and some remain phased
implementation work, but the open design choices are settled in the decisions
section below.

The additions are designed for the wrapper workflow around per-CIK JSON files in
`data/overrides/bdc_xbrl_wrappers/`. They should help agents determine whether a
wrapper is doing its job without making the agent the owner of production truth.

## Purpose

The wrapper oracle should answer a narrower question than the full production
validation suite:

> Did this CIK wrapper correctly transform cached BDC XBRL source facts into
> production-quality position-level holdings?

The full production validation suite answers a broader question:

> Is the unified dataset fit for analytics, frontend display, and index
> construction?

Those questions overlap, but they should not collapse into one system. The
wrapper oracle should own wrapper-specific evidence: source rows, wrapper
classification, staging behavior, field extraction quality, trial-output deltas,
and promotion readiness. Whole-pipeline checks such as fund strategy validation,
entity resolution, GAV reconciliation, and frontend data quality should remain
independent. When their outputs are useful to wrapper work, the oracle should
surface them as scoped review packets rather than silently adopting their pass or
fail status.

## Design Principles

1. Validation rules create evidence, not truth.
2. LLM review adjudicates noisy candidate issues, but deterministic code still
   implements fixes.
3. Row-level and cluster-level verdicts must include mechanism, evidence,
   confidence, and residual risk.
4. False positives should be preserved with scoped exceptions or calibrated
   diagnostics, not suppressed globally.
5. Wrapper fixes should be CIK-scoped unless evidence supports a global rule.
6. Promotion should block on unresolved material risk, deterministic regressions,
   or adjudicated true wrapper errors, not on every noisy rule firing.
7. Agents must not hand-edit production outputs or frontend JSON.

## Current Limitation

The current oracle is strong at source reconciliation and wrapper-gate
mechanics, but `remaining_blocking_rows=0` does not prove that production
columns are clean.

The transcript review from the wrapper sessions showed this clearly:

| CIK | Evidence | Oracle gap |
| --- | --- | --- |
| `0001860424` Onex Falcon Direct Lending BDC Fund | Source blockers cleared, but malformed Apryse identifiers still entered trial output as index-facing `DIRECT_LENDING` rows until the agent added a custom output check. | Source reconciliation can pass while malformed parsed rows remain in production columns. |
| `0001860424` Onex | The agent found 57 rows with hierarchy text leaking into `issuer_name`, then 9 remaining malformed issuer rows after a first parser fix. | The oracle did not directly report parsed-field contamination. |
| `0001988280` Manulife Private Credit Fund | `instrument_description` carried hierarchy text such as `Senior loans ..., Chemicals ...`; the agent changed archetype keywords to clear content-signature failures. | The oracle signaled unclassified content, but did not directly say the field role looked wrong. |
| `0002052153` Apollo Origination II (UL) Capital Trust | `unclassified_fv_rate_exceeded` led the agent to repeated high-FV `Co-investment` rows and a narrow fund-family fix. | This was a useful cluster signal, but the agent had to inspect examples manually. |

The agents behaved reasonably: they inspected artifacts, added focused tests,
avoided broad global rules, used trial rebuilds, and reported residual warnings.
The issue is that the oracle forced them to invent temporary profilers and
custom checks for common wrapper-quality questions.

## Proposed Additions

There are two primary additions:

1. Production validation issue packets inside the wrapper oracle.
2. CIK-scoped column distribution drift checks.

The transcript review also supports several secondary oracle checks, described
later in this document.

## Addition 1: Production Validation Issue Packets

Selected production validation outputs should be made visible inside the wrapper
trial loop. These should not become direct hard fails by default. They should
become deterministic candidate issues for LLM or human adjudication.

### Goal

Give the agent enough evidence to decide:

- did the wrapper miss a real source position?
- did it leak a subtotal/category row?
- did it parse issuer or instrument fields incorrectly?
- did it alter a numeric field incorrectly?
- did it drop a fair-value-bearing source row that needs exact evidence?
- is a rule firing a real wrapper defect, a false positive, a source issue, or a
  downstream validation issue?

### Candidate Issue Sources

The oracle should generate candidate issue packets from these inputs:

| Source | Examples |
| --- | --- |
| Source reconciliation | source-only rows, pipeline-only rows, value mismatches, duplicate dimension candidates, comparative-period rows. |
| Column validation | missing or malformed issuer, invalid numeric/date/rate fields, fixed/floating contradictions, maturity before report date. |
| Position purity diagnostics | subtotal candidates, duplicate dimension candidates, comparative-period candidates. |
| Classification validation | family vs asset category disagreements, exposure-type disagreements, fund/direct/liquid mismatches. |
| Trial-vs-production summary | rows added, rows removed, classification changes, parsed-field changes, FV changes. |
| Wrapper oracle diagnostics | unclassified rate/FV, exclusion risk, low continuity, concept drift, rate/cost outliers. |

### Candidate Issue Severity

Candidate issue severity should describe risk, not final truth:

| Severity | Meaning |
| --- | --- |
| `info` | Useful context; not review-blocking. |
| `warn` | Needs review if material or repeated. |
| `review` | Requires adjudication before promotion if material. |
| `block_candidate` | Likely serious, but still needs owner/verdict when false positives are known. |
| `hard_fail` | Structural failure where adjudication is not useful. |

### True Hard Fails

These should remain hard fails because they are not judgment calls:

- invalid wrapper JSON;
- schema validation failure;
- wrapper cannot load;
- trial rebuild crashes;
- oracle cannot produce required artifacts;
- malformed agent verdict output;
- missing source lineage keys required for reconciliation;
- non-deterministic or broad output edits;
- accepted correction without mechanism or evidence.

### Noisy Rule Handling

Rules with known false positives should be downgraded from automatic promotion
blockers to candidate issues. Promotion should then depend on adjudication:

```text
rule fires
  -> deterministic candidate issue
  -> LLM/human verdict
  -> deterministic wrapper fix, scoped exception, or escalation
  -> promotion decision based on unresolved material risk
```

This preserves high recall without forcing broad rules to be precise enough for
automatic rejection.

## LLM Verdict Schema

Each LLM-authored verdict should be structured and machine-validated.

Recommended JSONL shape:

```json
{
  "issue_id": "WRAP-0001860424-2025-06-30-000001",
  "rule_id": "PARSED_FIELD_CONTAMINATION",
  "severity": "review",
  "likely_owner": "wrapper",
  "cik": "0001860424",
  "entity_name": "Onex Falcon Direct Lending BDC Fund",
  "report_date": "2025-06-30",
  "accession_number": "0000950170-25-105519",
  "source_row_id": "2667",
  "bdc_investment_identifier": "raw source identifier here",
  "production_column": "issuer_name",
  "source_value": "raw source value here",
  "output_value": "parsed output value here",
  "wrapper_disposition": "debt_position_leaf",
  "verdict": "true_wrapper_error",
  "mechanism": "issuer parser failed to stop at the observed instrument term",
  "recommended_action": "add CIK-scoped instrument boundary and regression test",
  "confidence": 0.92,
  "evidence": "row contains rate and maturity terms after issuer_name; similar rows parse correctly after boundary update",
  "residual_risk": "other unseen instrument terms may still leak until drift checks are added"
}
```

### Required Verdict Values

| Verdict | Meaning | Expected action |
| --- | --- | --- |
| `true_wrapper_error` | The wrapper or wrapper-specific staging produced wrong output. | Add or modify deterministic wrapper/staging rule and tests. |
| `false_positive` | The rule fired but the row/output is acceptable. | Add scoped exception or calibrate the rule; do not change output. |
| `inconclusive` | Evidence is insufficient. | Escalate or leave as review-required. |
| `not_wrapper_owned` | Issue belongs to global classifier, enrichment, source data, or production validation. | Route to the correct backlog; do not change wrapper unless needed. |
| `real_filing_change` | Drift reflects a real disclosure/presentation change. | Update baseline/context if output remains valid. |
| `source_format_change_normalized_ok` | Raw source format changed, but normalized output remains correct. | Record as accepted drift; no wrapper change. |

### Required Owner Values

| Owner | Description |
| --- | --- |
| `wrapper` | CIK wrapper dispatch, parsing, staging, or exclusion logic. |
| `global_staging` | Shared staging behavior outside the wrapper. |
| `classification` | Global asset/exposure/index classification. |
| `source_data` | Cached XBRL/source filing issue or source corruption. |
| `enrichment` | Entity resolution, GICS, canonical name, lien, or downstream enrichment. |
| `validation_rule` | Rule is too broad or needs calibration. |
| `unknown` | Needs human review. |

### Verdict Validation Rules

Agent verdicts should be rejected if:

- `confidence` is missing or outside `[0, 1]`;
- `verdict` is not one of the allowed values;
- `mechanism` is blank for `true_wrapper_error`;
- `evidence` is blank for any verdict except `inconclusive`;
- `recommended_action` asks to hand-edit production output;
- a `false_positive` verdict has no scoped reason;
- a `true_wrapper_error` verdict has no deterministic repair path.

## Promotion Semantics With Verdicts

Promotion should not depend only on raw rule status. It should depend on the
combination of deterministic oracle state, candidate issue materiality, and
adjudicated verdicts.

### Promotion Statuses

| Status | Meaning |
| --- | --- |
| `promote` | No deterministic regressions, no unresolved material true errors, and accepted review issues are documented. |
| `review_required` | Candidate issues remain unresolved or inconclusive, but no deterministic blocker has worsened. |
| `reject` | Blocking rows/FV regress, structural failure occurs, or material true wrapper errors remain unfixed. |

### Suggested Promotion Logic

```text
if structural failure:
    reject
elif blocking rows or blocking FV increased vs baseline:
    reject
elif high-confidence true_wrapper_error remains unfixed:
    reject
elif material inconclusive issues remain:
    review_required
elif false positives are accepted with scoped evidence:
    promote
else:
    promote
```

Materiality should be configurable by row count, fair value, and affected
quarters. Fair-value materiality should generally dominate row-count materiality.

## Addition 2: CIK-Scoped Column Distribution Drift

Wrappers often fail when a filer changes presentation style. A single row may
not look obviously wrong, but the column distribution changes materially. The
oracle should track distribution drift per CIK, report date, and column.

### Separate Raw And Normalized Drift

The oracle should track two layers separately:

| Layer | Question |
| --- | --- |
| Raw source distribution | Did the filer/source format change? |
| Normalized output distribution | Did the production column output change? |

This distinction prevents false alarms. A raw format change may be harmless if
normalization still produces correct production fields.

### Target Columns

Initial high-value columns:

| Column | Why it matters |
| --- | --- |
| `issuer_name` | Bad parsing can make entity resolution and position identity unreliable. |
| `instrument_description` | Hierarchy/category text can masquerade as instrument text. |
| `position_key` | Volatile keys break cross-quarter matching and returns. |
| `interest_rate` | Rate scale and format errors affect yield analytics. |
| `basis_spread` | Spread parsing can be confused with all-in coupon. |
| `reference_rate_type` | SOFR/LIBOR/base-rate parsing can shift with disclosure format. |
| `coupon_type` | Fixed/floating misclassification affects rate sanity checks. |
| `pik_rate` | PIK terms proxy can be confused with current PIK status. |
| `maturity_date` | Date parsing affects credit term analytics and matching. |
| `fair_value` | Scale errors or duplicate rows affect index weights. |
| `cost` | Cost/FV checks catch scale and source-field mixups. |
| `principal_amount` | Commitment vs drawn principal can create false positives and true scale issues. |
| `index_classification` | Family drift can move rows into or out of index categories. |
| `asset_class` | Downstream analytics rely on stable asset class. |
| `exposure_type` | DIRECT/FUND/LIQUID drift changes index eligibility. |

### Format Buckets

For each target field, define deterministic format buckets.

Examples for `interest_rate` raw/source strings:

| Bucket | Examples |
| --- | --- |
| `numeric_percent` | `8.50%`, `10.02%` |
| `percent_string` | `Interest Rate 10.02%` |
| `reference_plus_spread` | `SOFR + 6.25%`, `L + 5.75%` |
| `floor_plus_spread` | `SOFR + 6.25% Floor 1.00%` |
| `cash_pik_split` | `8.00% cash / 2.00% PIK` |
| `range` | `8.00%-10.00%` |
| `footnote_text` | rate with footnote markers or explanatory text |
| `blank` | empty/null |
| `unrecognized` | non-empty value outside known buckets |

Examples for `issuer_name` and `instrument_description`:

| Bucket | Examples |
| --- | --- |
| `clean_entity_like` | `Jackson Paper Manufacturing Company` |
| `contains_affiliation_prefix` | starts with `Non-controlled/Non-affiliated investments` |
| `contains_family_prefix` | starts with `Debt Investments`, `Equity`, `Senior loans` |
| `contains_rate_terms` | includes `SOFR`, `Interest Rate`, `Reference Rate` |
| `contains_date_terms` | includes `Maturity Date`, `Acquisition Date` |
| `contains_pct_hierarchy` | includes category percentages such as `Senior loans 195.1%` |
| `empty` | blank/null |
| `too_short` | very short nonblank output |
| `too_long` | suspiciously long output |

Examples for `position_key`:

| Bucket | Examples |
| --- | --- |
| `stable_clean` | normalized issuer plus stable instrument terms |
| `contains_rate_token` | includes numeric coupon/spread tokens |
| `contains_date_token` | includes maturity/acquisition dates |
| `contains_pct_token` | includes hierarchy percentages |
| `contains_affiliation_token` | includes controlled/non-affiliated text |
| `placeholder_like` | generic key such as `term loan`, `class units`, or very short token set |
| `duplicate_within_quarter` | same key repeated within CIK/source/report date |

### Drift Metrics

For each CIK, report date, and target column, compute:

| Metric | Use |
| --- | --- |
| `row_count` | Denominator for drift interpretation. |
| `fair_value_abs_sum` | Value-weighted materiality. |
| `fill_rate` | Sudden nulls indicate extraction failure. |
| `parse_success_rate` | Numeric/date parser health. |
| `format_bucket_distribution` | Categorical format drift. |
| `new_bucket_share` | New unexpected source presentation. |
| `dominant_bucket` | Main observed format. |
| `dominant_bucket_share` | Concentration in one format. |
| `median` | Numeric center. |
| `p25`, `p75`, `p95` | Numeric distribution. |
| `fair_value_weighted_median` | Value-material numeric center. |
| `zero_share` | Detects default/fill behavior. |
| `outlier_share` | Scale or parsing error signal. |

### Drift Tests

Recommended tests:

| Drift type | Suggested metric |
| --- | --- |
| Categorical format drift | Jensen-Shannon divergence or population stability index. |
| New bucket drift | Current-quarter share of buckets absent from lookback baseline. |
| Fill regression | Current fill rate vs lookback median or minimum acceptable level. |
| Numeric center shift | Robust median/MAD or IQR movement. |
| Tail shift | p95 or p99 ratio vs lookback. |
| Value-weighted shift | fair-value-weighted median ratio or bucket distribution. |

Avoid ordinary standard deviation as the primary signal for rates and spreads.
Rate populations are often not normally distributed, and small positions can
distort unweighted metrics.

### Baseline Windows

Use a configurable baseline:

| Baseline | Use |
| --- | --- |
| Prior quarter | Sensitive to sudden changes. |
| Prior 4 quarters | Good default for seasonal or slowly changing filers. |
| All prior quarters | Useful for sparse histories. |
| Sibling CIK baseline | Useful for related vehicles using the same presentation style. |

Default recommendation: prior 4 quarters when available, otherwise all prior
quarters. Add sibling-CIK comparison as a separate diagnostic, not as the primary
gate.

### Drift Packet Shape

Example deterministic cluster packet:

```json
{
  "packet_id": "DRIFT-0001234567-2026-03-31-interest_rate",
  "cik": "0001234567",
  "report_date": "2026-03-31",
  "column": "interest_rate",
  "layer": "raw_source",
  "baseline_window": "prior_4_quarters",
  "metric": "format_bucket_distribution",
  "status": "review",
  "fair_value_abs_sum": 850000000.0,
  "baseline_distribution": {
    "numeric_percent": 0.80,
    "percent_string": 0.20
  },
  "current_distribution": {
    "numeric_percent": 0.30,
    "percent_string": 0.50,
    "reference_plus_spread": 0.20
  },
  "new_bucket_share": 0.20,
  "representative_rows_path": "column_drift_examples.csv",
  "suggested_review_question": "Did the filer change rate disclosure, and does normalized output still distinguish all-in coupon from spread?"
}
```

### Cluster First, Rows Second

Distribution drift should trigger cluster-level review first. Row-level review
should expand only when the cluster verdict is wrapper-owned or inconclusive.

```text
detect CIK-column-quarter drift
  -> summarize old/new distributions
  -> attach representative rows
  -> LLM gives cluster verdict
  -> expand to row-level issues only if needed
```

This prevents hundreds of repetitive row verdicts when one mechanism explains
the drift.

## Additional Oracle Checks Supported By Transcript Evidence

### 1. Parsed-Field Contamination

The oracle should flag when parsed production columns still contain hierarchy,
rate, date, or source-path text.

Target columns:

- `issuer_name`
- `instrument_description`
- `canonical_name`
- `position_key`

Candidate signals:

- affiliation tokens in parsed fields;
- category/family prefixes in parsed fields;
- `Interest Rate`, `Reference Rate`, `SOFR`, `LIBOR`, `Floor`;
- `Maturity Date`, `Acquisition Date`, `Initial Acquisition Date`;
- percentage hierarchy tokens such as `Senior loans 195.1%`;
- strings longer than a CIK-specific or global length threshold;
- repeated hierarchy separators such as pipes or duplicated category paths.

Suggested rule IDs:

- `PF01_ISSUER_HIERARCHY_CONTAMINATION`
- `PF02_INSTRUMENT_HIERARCHY_CONTAMINATION`
- `PF03_ISSUER_RATE_OR_DATE_CONTAMINATION`
- `PF04_POSITION_KEY_VOLATILE_TOKEN`

Transcript basis: Onex required custom checks to find malformed issuer fields
after source blockers were already clear.

### 2. Position-Key Hygiene

The oracle should directly inspect `position_key`, not only downstream match
rates.

Flag position keys containing:

- interest rates;
- basis spreads;
- PIK rates;
- reference-rate tokens;
- maturity dates;
- acquisition dates;
- category percentages;
- affiliation labels;
- raw source prefixes.

Also flag:

- duplicate keys within CIK/source/report date;
- keys shorter than minimum quality threshold;
- keys with only generic debt/equity terms;
- sharp QoQ change in key format distribution.

Transcript basis: Onex and Manulife both needed wrapper changes because volatile
tokens polluted position identity.

### 3. Source-Corrupted Identifier Detection

The oracle should identify identifiers that appear to contain concatenated or
corrupted source paths.

Candidate signals:

- repeated affiliation blocks in one identifier;
- malformed prefix variants such as duplicated or truncated `Non-controlled`;
- hierarchy text immediately appended after a maturity/acquisition date;
- multiple issuer/instrument sequences in one identifier;
- abrupt transition from date token into another affiliation/category token;
- unusually long identifier compared with CIK history;
- two source rows with same issuer/rate/maturity where one has corrupted
  appended hierarchy.

Suggested rule IDs:

- `SC01_REPEATED_AFFILIATION_BLOCK`
- `SC02_DATE_THEN_HIERARCHY_CONCATENATION`
- `SC03_MALFORMED_PREFIX`
- `SC04_MULTI_POSITION_IDENTIFIER`

Transcript basis: Onex Apryse rows used a malformed `Non-cNon-controlled...`
prefix and appended hierarchy text after the maturity date.

### 4. FV-Bearing Exclusion Audit

Excluding FV-bearing rows is dangerous. The oracle should require explicit
mechanism evidence before accepting the exclusion of a row that looks like a
position.

Flag excluded rows when they have:

- positive or material fair value;
- position evidence such as maturity, rate, principal, investment type, term
  loan, revolver, delayed draw, equity class, or preferred units;
- no exact audited override;
- no arithmetic tie-out to child rows;
- no wrapper reason explaining aggregate/non-private classification.

Expected actions:

| Verdict | Action |
| --- | --- |
| true aggregate | Add scoped aggregate classification or exact override. |
| source corrupted | Add accession/report-date/source-row scoped exclusion with evidence. |
| real position | Fix wrapper to include it. |
| inconclusive | Keep as review-required. |

Transcript basis: Onex initially attempted wrapper-level exclusion, then moved
to exact audited aggregate-row overrides for malformed Apryse source rows.

### 5. Row-Delta Attribution

Trial-vs-production deltas should be explained by mechanism.

New artifact: `row_delta_attribution.csv`.

Suggested columns:

- `cik`
- `report_date`
- `delta_type`
- `row_count`
- `fair_value_abs_sum`
- `sample_identifier`
- `likely_mechanism`
- `owner`
- `review_status`

Suggested `delta_type` values:

- `added_position_leaf`
- `removed_aggregate`
- `removed_non_private`
- `removed_source_corrupted`
- `changed_wrapper_family`
- `changed_index_classification`
- `changed_issuer_name`
- `changed_instrument_description`
- `changed_position_key`
- `changed_numeric_value`
- `unknown`

Transcript basis: Manulife removed 22 current rows, and the agent manually
verified that the removals were subtotal/cash-management rows.

### 6. Wrapper/Staging Disagreement Packets

Current summaries may show counts such as wrapper-only aggregate rows or
hierarchy parse disagreements. The agent needs examples and affected columns.

New artifact: `wrapper_staging_disagreement_packets.csv`.

For each disagreement cluster, include:

- disagreement type;
- row count;
- fair value;
- affected quarters;
- representative identifiers;
- wrapper disposition;
- staging disposition;
- affected output columns;
- suggested owner.

Transcript basis: Final summaries included non-blocking disagreement counts, but
those counts alone do not tell a reviewer whether they are acceptable.

### 7. Content-Signature Field-Role Mismatch

The content-signature engine should flag when it is classifying a row using a
field that appears to hold hierarchy text rather than instrument text.

Signals:

- `instrument_description` starts with a portfolio category;
- `instrument_description` contains multiple hierarchy levels;
- `issuer_name` contains loan terms while `instrument_description` contains
  category text;
- archetype keyword only matches because a broad category keyword was added.

Transcript basis: Manulife used hierarchy-like `instrument_description`, and the
agent resolved content-signature failure by adding `Senior loans` as an
archetype keyword. That may be acceptable, but it should be visible as a
field-role diagnostic.

### 8. High-FV Unclassified Family Clusters

When `unclassified_fv_rate_exceeded` fires, the oracle should emit a cluster
packet with repeated labels and representative rows.

Suggested columns:

- `cluster_label`
- `row_count`
- `quarter_count`
- `fair_value_abs_sum`
- `fair_value_share`
- `source_family_guess`
- `output_classification`
- `sample_identifiers`
- `suggested_wrapper_family`

Transcript basis: Apollo's high-FV unclassified rows were repeated
`Co-investment` rows that needed a CIK-local fund family.

### 9. Comparative-Period Subtotal Separation

Comparative-period subtotal classification issues should be separated from
current-period position failures.

Suggested statuses:

- `current_period_position_issue`
- `current_period_subtotal_issue`
- `comparative_period_position_issue`
- `comparative_period_subtotal_issue`
- `period_unknown`

Transcript basis: Manulife's last failing quarter was a comparative-period
subtotal, not a current-period position blocker.

### 10. Sibling-CIK Parity

For related vehicles, the oracle can compare a candidate CIK against sibling
wrappers and outputs.

Examples:

- Apollo `(L)` vs Apollo `(UL)`;
- related feeder funds;
- parallel share-class vehicles;
- related evergreen/private-credit vehicles managed by the same sponsor.

Compare:

- row counts by quarter;
- family distributions;
- format bucket distributions;
- fill rates;
- classification distributions;
- wrapper sections and staging strategy;
- unclassified FV share;
- position-key hygiene.

This should be diagnostic only unless sibling linkage is explicitly configured.

Transcript basis: Apollo UL used an Apollo sibling wrapper as evidence, but the
agent had to compare formats manually.

### 11. Regex Compatibility Preflight

Wrapper regexes can be valid in Python but invalid or semantically different in
DuckDB SQL. The oracle should preflight regexes according to where they are used.

Classify wrapper regex fields by execution engine:

| Engine | Example fields |
| --- | --- |
| Python regex | dispatch and classifier-only patterns. |
| DuckDB regex | staging SQL extraction and condition fields. |
| Both | any pattern reused across classifier and staging. |

Checks:

- reject unsupported lookaround in DuckDB-bound fields;
- reject backreferences if unsupported by target engine;
- compile Python-bound regexes with Python `re`;
- run small DuckDB `regexp_matches`/`regexp_extract` probes for SQL-bound
  regexes;
- surface exact field path and failing pattern.

Transcript basis: Onex debugging hit a DuckDB regex compatibility concern during
trial rebuild investigation.

## Proposed Oracle Artifacts

### Deterministic Artifacts

| Artifact | Author | Purpose |
| --- | --- | --- |
| `agent_issue_packets.csv` | oracle | Row-level candidate issues from deterministic rules. |
| `agent_issue_packets.jsonl` | oracle | Same issues in stable JSONL form for LLM review. |
| `agent_cluster_packets.csv` | oracle | Cluster-level issues such as drift, unclassified family clusters, and row-delta groups. |
| `column_drift_summary.csv` | oracle | CIK-column-quarter drift metrics. |
| `column_drift_examples.csv` | oracle | Representative rows for drift packets. |
| `row_delta_attribution.csv` | oracle | Trial-vs-production delta attribution. |
| `parsed_field_quality.csv` | oracle | Parsed-column contamination and field-role checks. |
| `wrapper_staging_disagreement_packets.csv` | oracle | Examples behind wrapper/staging disagreement counts. |
| `regex_compatibility_report.csv` | oracle | Regex preflight by wrapper field and execution engine. |

### LLM-Authored Artifacts

| Artifact | Author | Purpose |
| --- | --- | --- |
| `agent_verdicts.jsonl` | LLM/human agent | Structured adjudication of issue packets. |
| `agent_verdict_summary.csv` | deterministic reducer | Counts and materiality by verdict/owner/severity. |
| `accepted_oracle_exceptions.json` | human-approved config | Accepted scoped exceptions, if using exception workflow. |
| `recommended_wrapper_fixes.md` | LLM/human agent | Non-authoritative proposed mechanisms and tests. |

LLM-authored outputs must not directly change production data. They are evidence
for deterministic wrapper fixes, global rule calibration, or scoped exceptions.

## Example Agent Review Flow

```text
1. Agent claims CIK.
2. Agent profiles cached source facts.
3. Agent authors or updates wrapper.
4. Oracle runs schema, coherence, source reconciliation, trial rebuild, matching,
   production-validation packets, parsed-field quality checks, and drift checks.
5. Oracle writes deterministic issue and cluster packets.
6. LLM reviews packets:
     - cluster verdict first for drift and repeated issues;
     - row verdicts only for material affected rows.
7. Agent applies deterministic fixes only when verdict and evidence support them.
8. Agent reruns oracle.
9. Promotion gate reads raw oracle state plus verdict summary.
10. Wrapper is promoted, rejected, or marked review-required.
```

## Example: Onex Corrupted Apryse Rows

Observed pattern:

- malformed prefix similar to `Non-cNon-controlled`;
- identifier appended another hierarchy block after maturity date;
- rows entered trial output as index-facing loans after source blockers cleared;
- direct custom output inspection found the rows;
- final mechanism moved toward exact audited row overrides.

Desired oracle behavior:

1. `SC03_MALFORMED_PREFIX` fires.
2. `SC02_DATE_THEN_HIERARCHY_CONCATENATION` fires.
3. `PF01_ISSUER_HIERARCHY_CONTAMINATION` or `PF02_INSTRUMENT_HIERARCHY_CONTAMINATION` fires if parsed output is contaminated.
4. `FV_BEARING_EXCLUSION_AUDIT` fires if excluded without exact evidence.
5. Oracle creates a cluster packet with both affected quarters.
6. LLM verdict identifies source corruption or true wrapper error.
7. Agent proposes exact accession/report-date/source-row scoped override or
   parser fix.
8. Promotion requires no remaining material unresolved issue.

## Example: Manulife Hierarchy Text In Instrument Description

Observed pattern:

- pipe-separated hierarchy;
- true positions already staged;
- subtotals and category rows were source-only blockers;
- position keys initially contained volatile percentage hierarchy;
- `instrument_description` held category hierarchy text;
- content-signature failure was cleared with archetype tuning.

Desired oracle behavior:

1. `PF02_INSTRUMENT_HIERARCHY_CONTAMINATION` creates parsed-field packet.
2. `PK01_POSITION_KEY_PERCENT_TOKEN` creates position-key packet.
3. Row-delta attribution identifies removed rows as subtotals/non-private rows.
4. Content-signature field-role packet explains that classification is relying on
   hierarchy text.
5. LLM verdict decides whether this is acceptable for the wrapper or should be
   fixed in staging extraction.

## Example: Apollo Co-Investment Family

Observed pattern:

- source blockers cleared, but oracle still failed on high-FV unclassified rows;
- repeated `Co-investment` rows appeared across quarters;
- pipeline output classified them as `FUND`;
- wrapper had no explicit family for them;
- agent added a narrow CIK-local fund family.

Desired oracle behavior:

1. `unclassified_fv_rate_exceeded` fires.
2. Oracle emits `high_fv_unclassified_family_cluster`.
3. Cluster packet shows repeated label, quarters, FV share, and output
   classification.
4. LLM verdict: `true_wrapper_error`, owner `wrapper`, action `add CIK-local fund
   family`.
5. Agent adds deterministic wrapper rule and focused regression test.

## Field-Level Rule Candidates

### `issuer_name`

Candidate checks:

- missing after wrapper leaf classification;
- contains affiliation/category hierarchy;
- contains rate/date terms;
- contains instrument boundary terms that should be in `instrument_description`;
- suspiciously long;
- sharp format-bucket drift;
- high duplicate rate with different instruments;
- large share changed vs production trial baseline.

### `instrument_description`

Candidate checks:

- missing for debt leaf rows where source has instrument terms;
- contains only category hierarchy;
- contains issuer-like legal suffix without instrument terms;
- contains rate/date terms when those should be separate fields;
- sharp drift in clean instrument vs hierarchy-text buckets;
- changed materially vs production trial baseline.

### `position_key`

Candidate checks:

- contains rates, spreads, PIK, dates, percentages, affiliation labels;
- duplicate within CIK/source/report date;
- too short or generic;
- J01/J03 failure cluster points to volatile token family;
- key format distribution drift.

### `interest_rate`

Candidate checks:

- numeric parse failure;
- scale outlier;
- raw rate format drift;
- normalized fill-rate drop;
- all-in coupon confused with spread;
- private credit rows missing rate and spread;
- private equity rows with positive rate.

### `basis_spread`

Candidate checks:

- numeric parse failure;
- spread outlier;
- fixed-rate row with positive spread;
- floating-rate row with missing/zero spread;
- spread distribution shifts sharply;
- source rate format suggests spread but output is blank.

### `pik_rate`

Candidate checks:

- numeric parse failure;
- outlier;
- PIK terms format drift;
- PIK rate exceeds total rate;
- PIK terms confused with strict current PIK status.

Important: `pik_rate` in `private_markets_holdings.csv` is a schedule-rate or
terms proxy. It is not proof that a position is currently paying/accruing PIK.
Strict current PIK evidence belongs in separate PIK status outputs.

### `maturity_date`

Candidate checks:

- parse failure;
- maturity before report date;
- sentinel usage spike;
- date format drift;
- maturity embedded inside issuer/instrument fields;
- maturity token in `position_key`.

### `fair_value`, `cost`, `principal_amount`

Candidate checks:

- source/output mismatch;
- parse failure;
- negative or zero where unexpected;
- cost/FV outlier;
- principal/FV outlier;
- magnitude shift;
- trial-vs-production value change;
- duplicate dimension path candidate.

### Classification Fields

Target fields:

- `index_classification`
- `asset_class`
- `exposure_type`
- `asset_category`
- `issuer_category`
- wrapper family/disposition fields in reconciliation detail.

Candidate checks:

- enum failure;
- family vs asset category disagreement;
- wrapper family missing for high-FV rows;
- classification changed vs production trial baseline;
- classification distribution drift;
- fund/direct/liquid mismatch.

## Final Architecture Decisions

1. Candidate issue materiality is FV-tiered. `P1 review` starts at
   `max($5M, 0.25% of CIK-quarter FV)`. `P0 promotion-material` starts at
   `max($25M, 1.0% of CIK-quarter FV)`. Blocking FV regressions versus baseline
   still reject regardless of threshold.
2. Row-count materiality scales by CIK-quarter size, with FV dominant. Row-only
   `P1 review` starts at `max(5 rows, 2% of CIK-quarter rows)`. Row-only `P0`
   starts at `max(15 rows, 5% of CIK-quarter rows)`. Repeated low-FV issues
   across two or more quarters are at least `P1`.
3. Drift baselines use the rolling prior 4 quarters when available. For short
   histories, use all available prior quarters. With fewer than 2 prior
   quarters, emit only `info/insufficient_baseline`.
4. Durable accepted waivers/adjudications live in central override artifacts,
   not wrapper JSON. Raw per-run verdicts live under the trial output directory.
   True wrapper errors should become deterministic wrapper/config/code fixes,
   not permanent waivers.
5. Sibling-CIK mappings live in explicit separate config under
   `data/overrides/wrapper_cohorts/`. They are not inferred automatically and
   are not stored in wrapper JSON.
6. Wrapper trials do not call full `validate_holdings.py` because it writes
   global artifacts. Reusable validation logic should be exposed as
   side-effect-free one-CIK packet builders and written only to trial-scoped
   oracle artifacts.
7. Wrapper packets use wrapper-namespaced rule IDs such as
   `WRAP.PARSED_FIELD_CONTAMINATION`. Production validation rule IDs may appear
   only as optional `source_rule_id`.
8. `row_delta_attribution.csv` compares trial output against current production
   only. Baseline comparison remains a separate optional promotion artifact.
9. Accepted confidence stays on `[0, 1]`; `0.80` is the minimum accepted
   confidence floor. High-FV or high-impact waivers require `0.90` or explicit
   human acceptance. Calibration over time should track confident-wrong rate,
   abstention rate, and accuracy by verdict type.
10. Human acceptance can waive only scoped soft diagnostics. Structural
    failures, schema/load failures, source-reconciliation regressions, malformed
    verdicts, and adjudicated true wrapper errors are never waived into a pass.

## Implementation Phasing

### Phase 1: Deterministic Packet Emission

Add deterministic packet generation only. No LLM writeback.

Outputs:

- `agent_issue_packets.csv`
- `agent_cluster_packets.csv`
- `parsed_field_quality.csv`
- `row_delta_attribution.csv`
- `column_drift_summary.csv`
- `column_drift_examples.csv`

Acceptance:

- existing oracle pass/fail behavior unchanged;
- packets are written during wrapper trial runs;
- packets include representative examples and materiality.

### Phase 2: LLM Verdict Schema

Add schema validation for `agent_verdicts.jsonl`.

Acceptance:

- invalid verdict files fail closed;
- verdict summary can be produced deterministically;
- no verdict can directly suppress a raw oracle result.

### Phase 3: Review-Aware Promotion Gate

Teach promotion gate to read verdict summaries.

Acceptance:

- true wrapper errors block until fixed;
- false positives can be accepted only with scoped evidence;
- inconclusive material issues produce `review_required`;
- raw oracle outputs remain unchanged.

### Phase 4: Drift Baselines

Add CIK-column drift baselines.

Acceptance:

- prior-quarter and prior-4-quarter baselines work;
- sparse histories degrade gracefully;
- drift emits cluster packets before row packets;
- thresholds are configurable.

### Phase 5: Sibling-CIK And Cross-CIK Diagnostics

Add optional sibling comparison.

Acceptance:

- sibling relationships are explicit config, not inferred blindly;
- diagnostics do not hard-fail promotion by default;
- output includes sibling name/CIK and comparable distributions.

## Testing Strategy

### Unit Tests

Add tests for:

- parsed-field contamination detection;
- position-key volatile token detection;
- source-corrupted identifier detection;
- row-delta attribution categories;
- drift bucket assignment;
- drift metric calculations;
- verdict schema validation;
- regex compatibility preflight.

### Fixture Tests

Use compact synthetic CIK-quarter fixtures for:

- clean stable wrapper output;
- raw format drift normalized correctly;
- raw format drift normalized incorrectly;
- source-corrupted concatenated identifier;
- FV-bearing exclusion with exact override;
- false-positive noisy rule adjudication.

### Regression Tests From Transcript Cases

Add focused cases inspired by:

- Onex malformed Apryse source identifier;
- Onex issuer hierarchy contamination;
- Manulife percentage hierarchy in position keys;
- Manulife comparative-period subtotal;
- Apollo `Co-investment` high-FV unclassified family.

### Non-Goals For Tests

Do not require full production rebuilds for packet unit tests. Use small
DataFrame fixtures or one-CIK trial artifacts where practical.

## Resolved Design Questions

The former open questions are resolved by the final architecture decisions
above. Future changes should amend those decisions explicitly rather than
re-introducing implicit behavior in code.

## Acceptance Criteria For The Overall Extension

The oracle extension is successful when:

- agents no longer need ad hoc temporary profilers for common wrapper-quality
  questions;
- `remaining_blocking_rows=0` is no longer treated as sufficient evidence of
  wrapper quality;
- every material issue has row or cluster examples;
- every candidate issue names affected production columns;
- false positives are captured as scoped verdicts or exceptions;
- true wrapper errors result in deterministic wrapper/staging fixes and tests;
- promotion reports distinguish raw oracle status from review-adjusted status;
- public production data remains derived from deterministic pipeline outputs.

## Non-Goals

These additions should not:

- replace source reconciliation;
- replace production validation;
- allow LLMs to edit output CSVs directly;
- turn broad warning rules into silent suppressions;
- promote wrappers solely because metrics improved;
- require global production rebuilds for every inner-loop wrapper iteration;
- conflate PIK terms with strict current PIK payment/accrual evidence.

## Recommended Initial Build Order

1. Add parsed-field quality packets for `issuer_name`, `instrument_description`,
   and `position_key`.
2. Add row-delta attribution for one-CIK trial output.
3. Add high-FV unclassified cluster packets.
4. Add source-corrupted identifier detection.
5. Add drift summary for `interest_rate`, `basis_spread`, `pik_rate`,
   `maturity_date`, and classification fields.
6. Add LLM verdict schema validation.
7. Integrate verdict summaries into promotion gate as `review_required` inputs.

The first four items are most directly supported by the transcript evidence and
should produce immediate improvements in agent behavior.
