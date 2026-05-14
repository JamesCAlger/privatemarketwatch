# Data Accuracy Contract And Column Validation Plan

## Summary

Create an implementation plan for a data accuracy contract, source-specific validators, column-level validations, and quality metrics. Do not include agent-authored correction loops in the first implementation slice; design the outputs so agents can consume them later.

Primary goal: make data accuracy measurable for `private_markets_holdings.csv` and public frontend outputs before doing broad production refactoring.

## Key Changes

- Create `docs/data_accuracy_contract.md` defining dataset grain, source scope, exclusions, validation tiers, severity levels, tolerances, and public disclosure rules.
- Add a reusable validation layer for `private_markets_holdings.csv` with shared issue output, shared metric output, and separate source-specific rule groups for BDC, N-PORT, and HTML-derived rows.
- Emit durable artifacts:
  - `data/output/column_quality_metrics.csv`
  - `data/output/row_validation_issues.csv`
  - `data/output/data_quality_metrics.csv`
  - optional later: `data/output/source_reconciliation_metrics.csv`
- Extend frontend data quality export so `frontend/public/data/data_quality.json` includes validation tiers, issue counts, and column-quality summaries.
- Keep existing GAV, classification, coverage, pct sum, count stability, and income-yield checks; wrap their outputs into the new issue schema rather than replacing them.

## Data Profiling Results (693,774 rows)

Profiling was run on all columns consumed by downstream modules (`index_returns.py`, `position_matching.py`, `export_frontend.py`, `fee_uplift.py`). Key findings that inform validation rules:

### Rate scale: whole-number percentages, not decimals

All rate columns are stored as whole-number percentages (9.80 = 9.80%, not 980%). Validation ranges must use this scale.

| Column | Median | P5 | P95 | Max | Null % |
|---|---|---|---|---|---|
| `interest_rate` | 9.80 | 0.03 | 12.99 | 50.0 | 34.1% |
| `basis_spread` | 5.50 | 3.09 | 7.94 | 50.0 | 50.1% |
| `pik_rate` | 4.05 | 0.25 | 14.88 | 50.0 | 94.3% |

### Fair value: 6% zero, 5.7% negative

- 8,045 nulls (1.2%) - cannot compute returns if included in index calculations.
- 41,856 zeros (6.0%) - unfunded commitments, written-off positions, or at reporting threshold.
- 39,639 negatives (5.7%) - short positions, derivative marks, unfunded commitment liabilities. Min: -$105M.
- 134 values > $1B (0.02%) - plausible for largest BDC tranches but worth WARN review.

### Principal amount: one extreme outlier

- 144,203 nulls (20.8%) - expected for equity positions.
- Max of $269.8B - almost certainly a 1000x scale error. A single tranche at $269B exceeds entire BDC industry AUM. Will corrupt any aggregation.
- 11 negatives - negligible.

### Pct of net assets: mixed scale, dimension-path artifacts

- 219,924 nulls (31.7%) - mostly N-PORT rows.
- Scale is percentage-points: median 0.087 means 0.087% of net assets. Values > 100.0 are outliers.
- Max of 2,428.69 - multi-dimension-path BDC duplication artifact.
- 8,740 negatives (1.3%) - short positions or unfunded commitments.

### Cost: 8% negative, never exactly zero

- 55,967 negatives (8.1%) - more common than negative FV. Short positions and premium/discount amortization.
- Zero count of 0 - cost is either known or null, never imputed to zero.

### Shares held: 87% null (expected)

- Null for debt positions (78.8% of dataset). Only relevant for equity.
- 2 negatives - data errors.

### Classification columns: clean

All four classification columns (`index_classification`, `asset_category`, `exposure_type`, `asset_class`) are 100% populated with valid enum values. `coupon_type` is 25% null (expected for non-coupon instruments); three valid values (`Floating` 58.9%, `Fixed` 8.6%, `Variable` 7.5%).

### Coupon-type cross-checks: no contradictions

- Fixed with basis_spread > 0: 0 rows.
- Floating with missing/zero basis_spread: 0 rows.

### Identity columns

- `issuer_name`: 100% populated, 157K distinct, 6 values < 3 chars.
- `cusip`: 24% populated (N-PORT only), all exactly 9 characters.
- `entity_id`: 88.1% populated, 27,766 distinct entities.
- `gics_sub_industry`: 100% null - never populated. Exclude from validation; document as future data source.
- `bdc_investment_identifier`: 68.2% populated - exactly matches BDC source share.

### Maturity date: data quality issues

- 41.3% populated (286K rows).
- Min of 0225-06-28 - year-parsing error (likely 2025).
- Max of 9999-12-31 - sentinel for perpetual instruments.
- 69 values before 2020 - matured positions still reported.
- 1,349 values after 2050 - 30-year maturities or sentinels.

### Cross-column findings

| Check | Count | % | Interpretation |
|---|---|---|---|
| PRIVATE_EQUITY with interest_rate > 0 | 1,908 | 0.28% | Likely convertible notes or misclassified debt |
| PRIVATE_CREDIT with no rate data | 35,367 | 5.10% | Equity-like credit or data gaps; affects income return |
| FUND with maturity_date | 456 | 0.07% | Unusual but low count |
| FV/cost > 5x | 19,258 | 2.78% | Equity appreciation or data issues |
| FV/cost < 0.1x | 16,560 | 2.39% | Severely distressed or written down |

## Column Contracts

Validation rules for the columns consumed by index returns, position matching, and frontend export. Severity is contextual: a value can be safe for display but unsafe for index returns.

### Tier 0: Identity and lineage keys

These are not INFO-only fields. They are required for grouping, validation adapters, frontend exports, and auditability.

| Column | Type | Required When | Valid Range | FAIL | WARN | Notes |
|---|---|---|---|---|---|---|
| `source` | enum | always | `bdc`, `nport`, `html` if present | null; unknown value | - | Drives source-specific validation. |
| `cik` | str | always | normalized CIK digits | null; empty; non-numeric after normalization | non-10-digit display form if normalization succeeds | Store or compare in a normalized form. |
| `report_date` | date | always | 2019-01-01 to current date | null; unparseable | future date | Central CIK-quarter key. |
| `accession_number` | str | filing-derived rows when available | non-empty | null for BDC XBRL/HTML rows with filing context | null for N-PORT rows if source lacks accession | Needed for source traceability. |
| `filing_date` | date | filing-derived rows when available | parseable date | unparseable when present | null | Less critical than report_date. |
| `entity_name` | str | always | non-empty | null; empty | unusually long or generic | Used in public display and diagnostics. |

### Tier 1: Index return inputs (corruption risk if wrong)

| Column | Type | Required When | Valid Range | FAIL | WARN | Cross-column |
|---|---|---|---|---|---|---|
| `fair_value` | float | row enters index returns or public FV aggregation | numeric | null for indexable row; unparseable; extreme source-confirmed scale error | negative; zero; > $3B | Null outside indexable scope is WARN/INFO depending evidence. |
| `cost` | float | cost-return or FV/cost analytics | numeric | unparseable when present | null when `fair_value` > 0; negative | FV/cost > 10x or < 0.05x. |
| `principal_amount` | float | debt analytics and rate/yield checks | numeric | > 10x `fair_value` when `fair_value` > 0; unparseable when present | null for PRIVATE_CREDIT; negative | Scale errors can corrupt income/return analytics. |
| `interest_rate` | float | credit income analytics | 0-50 (percentage scale) | unparseable when present | > 25; < 0; null for PRIVATE_CREDIT unless `basis_spread` present | > 0 with PRIVATE_EQUITY is WARN. |
| `basis_spread` | float | floating-rate credit analytics | 0-50 (percentage scale) | unparseable when present | > 15; missing/zero for Floating unless all-in rate exists | > 0 with Fixed is FAIL. |
| `pik_rate` | float | PIK analytics | 0-50 (percentage scale) | unparseable when present | > 20; < 0 | - |
| `shares_held` | float | equity analytics | numeric | negative | zero; null for equity positions | Expected null for debt. |

### Tier 2: Position matching inputs (match quality risk if wrong)

| Column | Type | Required When | Valid Range | FAIL | WARN | Notes |
|---|---|---|---|---|---|---|
| `issuer_name` | str | always | len >= 3 | null; empty; confirmed aggregate/header | len < 3; len > 300; suspected aggregate/header | Confirmed aggregate leakage is FAIL; heuristic suspicion is WARN. |
| `instrument_description` | str | when available | - | - | null for BDC debt/equity rows if raw identifier implies instrument exists | Display and classification support. |
| `cusip` | str | when present | len = 9 | len != 9 when present | - | 24% populated, all clean currently. |
| `isin` | str | when present | len = 12 | len != 12 when present | - | Track only where present. |
| `entity_id` | str | after entity-resolution step | expected canonical ID format | - | null; invalid format when present | Fill rate is quality signal, not correctness proof. |
| `bdc_investment_identifier` | str | `source=bdc` | non-empty | null for BDC rows | - | Raw source identifier must be preserved. |

### Tier 3: Classification / routing (index assignment risk if wrong)

| Column | Type | Required When | Valid Range | FAIL | WARN | Notes |
|---|---|---|---|---|---|---|
| `index_classification` | enum | always | 11 known values | null; unknown value | UNCLASSIFIED (track rate; target < 5%) | Currently 3.8% UNCLASSIFIED. |
| `asset_category` | enum | always | known values from unified holdings | null; unknown value | - | 100% populated. |
| `issuer_category` | enum | always | known values from unified holdings | null; unknown value | known residual disagreement | Must map explicit residuals separately. |
| `exposure_type` | enum | always | DIRECT, FUND, LIQUID | null; unknown value | - | 100% populated. |
| `asset_class` | enum | always | known values from unified holdings | null; unknown value | OTHER (track rate; target < 5%) | Currently 3.8% OTHER. |
| `coupon_type` | enum | credit rows when source supports it | Fixed, Floating, Variable | unknown value | null for PRIVATE_CREDIT | 25% null overall. |

### Tier 4: Frontend display (user-visible data quality)

| Column | Type | Required When | Valid Range | FAIL | WARN | INFO |
|---|---|---|---|---|---|---|
| `maturity_date` | date | debt display and maturity analytics | parseable date or known sentinel | year < 1900 | before `report_date`; after 2050 and not sentinel | `9999-12-31` perpetual/no-maturity sentinel. |
| `pct_of_net_assets` | float | BDC pct/NAV analytics | -100 to 100 percentage-points | > 100.0 unless accepted residual | negative; zero | Mostly null for N-PORT rows. |
| `reference_rate_type` | str | floating-rate display when available | - | - | missing when Floating and no all-in rate evidence | INFO if source omits. |
| `gics_sub_industry` | str | not used in this slice | - | - | - | 100% null; exclude from validation and document as future column. |

### Columns tracked as INFO-only fill/provenance

These fields are useful for audit or future work but should not create FAIL/WARN issues in this slice unless a source-specific rule above references them: `bdc_dimensions_raw`, `nport_asset_cat`, `nport_issuer_type`, `nport_holding_id`, `nport_series_name`, `nport_series_id`, `position_id`.

## Severity Model

Severity should not be column-global. It must reflect downstream use, materiality, and evidence.

Each issue should carry four fields:

| Field | Allowed Values | Purpose |
|---|---|---|
| `severity` | `FAIL`, `WARN`, `INFO` | How unsafe the issue is if true. |
| `evidence_strength` | `STRONG`, `MODERATE`, `WEAK` | How certain the validator is that this is a real issue. |
| `status` | `OPEN`, `ACCEPTED_RESIDUAL`, `FALSE_POSITIVE`, `RESOLVED` | Review lifecycle. |
| `action` | `BLOCK_VERIFIED`, `EXCLUDE_FROM_INDEX`, `REVIEW`, `DISCLOSE`, `TRACK_ONLY` | Intended downstream handling. |

### Severity definitions

`FAIL` means the affected row, CIK-quarter, or dataset is materially unsafe for the relevant downstream use. Open FAIL issues block `VERIFIED` and assign the CIK-quarter to `UNDER_REVIEW`. Examples: invalid source enum, missing CIK, unparseable report_date, unknown classification enum, null fair_value on a row entering returns, confirmed aggregate/subtotal leakage, extreme principal/FV scale error, pct_of_net_assets > 100, extreme GAV miss, or strong source reconciliation mismatch.

`WARN` means the issue is plausible, material enough to review, or relevant to public caveats, but not proven corrupt. Examples: suspected aggregate rows, zero/negative fair_value, high rate values, PRIVATE_CREDIT with no rate data, PRIVATE_EQUITY with an interest rate, moderate GAV miss, unstable position count, maturity before report_date, or missing entity_id.

`INFO` means expected gaps, documented exclusions, provenance facts, or low-risk limitations. Examples: BDC rows without CUSIP, N-PORT-only fields null for BDC rows, consumer-lending CIKs excluded by policy, `9999-12-31` maturity sentinel, and `gics_sub_industry` not populated in this slice.

### Evidence strength definitions

`STRONG` means the issue is grounded in independent source data or deterministic contradiction. Examples: source reconciliation mismatch, invalid enum, non-parseable required date, confirmed aggregate row with no matching source position.

`MODERATE` means the issue follows from cross-field or cross-quarter consistency but can have legitimate exceptions. Examples: GAV outside 0.8-1.2, PRIVATE_EQUITY with rate, maturity before report_date.

`WEAK` means the issue is heuristic or plausibility-only. Examples: keyword aggregate suspicion, unusual text length, high but possible position size.

### Contextual severity examples

| Condition | Severity | Evidence | Action |
|---|---|---|---|
| `fair_value` null on row entering index returns | FAIL | STRONG | EXCLUDE_FROM_INDEX |
| `fair_value` null on documented non-indexable artifact | INFO | MODERATE | TRACK_ONLY |
| suspected aggregate from keyword audit | WARN | WEAK | REVIEW |
| confirmed aggregate/subtotal in holdings | FAIL | STRONG | BLOCK_VERIFIED |
| `9999-12-31` maturity | INFO | STRONG | DISCLOSE |
| `0225-06-28` maturity | FAIL | STRONG | REVIEW |
| Floating coupon with missing spread but all-in `interest_rate` present | WARN | MODERATE | REVIEW |
| Floating coupon with missing spread and no all-in rate | WARN | MODERATE | REVIEW |

## Cross-Column Semantic Rules

These rules detect logical inconsistencies between columns. Each rule has a stable ID for tracking.

| Rule ID | Condition | Severity | Evidence | Rationale |
|---|---|---|---|---|
| X01 | `asset_class=PRIVATE_EQUITY` AND `interest_rate > 0` | WARN | MODERATE | Equity should not usually have interest; likely convertible notes or misclassification. 1,908 current rows. |
| X02 | `asset_class=PRIVATE_CREDIT` AND `interest_rate IS NULL` AND `basis_spread IS NULL` | WARN | MODERATE | Credit without any rate data; affects income return computation. 35,367 current rows (5.1%). |
| X03 | `exposure_type=FUND` AND `maturity_date IS NOT NULL` | INFO | WEAK | Fund positions with maturity are unusual but low count. 456 current rows. |
| X04 | `coupon_type=Fixed` AND `basis_spread > 0` | FAIL | STRONG | Contradictory if coupon_type is reliable: fixed-rate loans should not have floating spread. 0 current rows. |
| X05 | `coupon_type=Floating` AND (`basis_spread IS NULL` OR `basis_spread = 0`) | WARN | MODERATE | Floating-rate rows often should have a spread, but all-in rate or source omission can explain gaps. 0 current rows. |
| X06 | `principal_amount > 10 * fair_value` AND `fair_value > 0` | FAIL | MODERATE | Likely scale error, e.g. $269B outlier. |
| X07 | `fair_value > 0` AND `cost > 0` AND `fair_value / cost > 10` | WARN | WEAK | FV exceeds 10x cost; extreme appreciation or data error. |
| X08 | `fair_value > 0` AND `cost > 0` AND `fair_value / cost < 0.05` | WARN | WEAK | FV below 5% of cost; severely distressed or data error. |
| X09 | `pct_of_net_assets > 100.0` | FAIL | MODERATE | Usually dimension-path duplication or denominator artifact. |
| X10 | `maturity_date < report_date` | WARN | MODERATE | Position matured but still held; stale or legacy reporting. |

## Integration With Existing Validators

### Adapter pattern (wrap, don't rewrite)

Each existing validation function in `validate_holdings.py` keeps its current logic. A thin adapter reads its output CSV and emits issues in the new `(rule_id, severity, evidence_strength, status, action, ...)` schema:

| Existing Function | Adapter Rule IDs | Severity Mapping |
|---|---|---|
| `check_gav_reconciliation()` | GAV01 (ratio < 0.3 or > 5.0), GAV02 (ratio outside 0.8-1.2) | GAV01 = FAIL/STRONG/BLOCK_VERIFIED, GAV02 = WARN/MODERATE/REVIEW |
| `check_pct_of_net_assets_sum()` | PCT01 (sum > 200%), PCT02 (sum < 50%) | PCT01 = WARN/MODERATE/REVIEW, PCT02 = WARN/MODERATE/REVIEW |
| `check_position_count_stability()` | CNT01 (> 2.5x or < 0.4x jump), CNT02 (count/FV divergence) | WARN/MODERATE/REVIEW |
| `check_income_yield_consistency()` | YLD01 (yield ratio < 0.5 or > 2.5) | WARN/MODERATE/REVIEW |
| `validate_classification()` | CLS01-CLS10 mapped from existing E/A/I rules | hard contradictions = FAIL; known residuals or weak source-field disagreements = WARN; documented exceptions = INFO |
| `audit_aggregate_leaks()` | AGG01 suspected aggregate, AGG02 confirmed aggregate | AGG01 = WARN/WEAK/REVIEW, AGG02 = FAIL/STRONG/BLOCK_VERIFIED |
| `check_coverage()` | COV01 (missing CIK), COV02 (single-period) | INFO/MODERATE/DISCLOSE |
| `check_cross_source_overlap()` | DUP01 (cross-source duplicate) | WARN/MODERATE/REVIEW |

The CIK-quarter tier computation reads the unified issues table (new column rules + adapter-emitted rules) rather than joining 11 separate CSVs.

### Classification adapter severity

The current classification validation output does not have a severity model. The adapter must explicitly map each rule:

- FAIL: impossible or contract-breaking combinations that directly affect index assignment and have no documented residual.
- WARN: disagreements against filer-provided source fields, ambiguous source fields, or known residual categories that need monitoring.
- INFO: documented exceptions such as money market fund positions classified as LIQUID/CASH despite issuer_category=FUND.

### Why wrap instead of rewrite

The existing checks have unit tests and produce useful results. What they lack is a common output format, not an obvious correctness failure. Rewriting introduces regression risk for no accuracy gain.

## CIK-Quarter Quality Summary

Combine all issues (column rules + adapted existing checks) into a single tier per (CIK, quarter):

| Tier | Criteria |
|---|---|
| `VERIFIED` | No open FAIL; no open WARN from STRONG or MODERATE rules; source-specific strong checks pass where available. |
| `VALIDATED_WITH_WARNINGS` | No open FAIL, but one or more WARN issues remain. |
| `UNDER_REVIEW` | Any open FAIL issue, or a material unresolved source reconciliation failure. |
| `PRELIMINARY` | Data exists but strong checks have not run, e.g. new CIK with no GAV comparison value. |
| `STALE` | Not used in this slice. Reserved for future scheduled refresh logic. |

Accepted residuals do not block `VERIFIED` if the issue has `status=ACCEPTED_RESIDUAL`, evidence is documented, and the action is `DISCLOSE` or `TRACK_ONLY`.

## Downstream Gating (Intent Only - Not Implemented This Slice)

The contract should document how downstream consumers will eventually respect validation tiers, even if enforcement is deferred:

- `index_returns.py`: positions with open FAIL issues that affect FV, principal, rate, or classification should be excluded from return computation.
- `position_matching.py`: positions with open FAIL identity issues should be excluded from matching.
- `export_frontend.py`: fund pages for CIK-quarters with `UNDER_REVIEW` tier should display a data quality warning.

This slice produces the tiers and issues. Enforcement is a separate implementation step after the first round of issues has been triaged.

## Implementation Details

- Add a validation contract module `pipeline/column_validation.py` with:
  - canonical severity values: `FAIL`, `WARN`, `INFO`
  - canonical evidence values: `STRONG`, `MODERATE`, `WEAK`
  - canonical status values: `OPEN`, `ACCEPTED_RESIDUAL`, `FALSE_POSITIVE`, `RESOLVED`
  - canonical action values: `BLOCK_VERIFIED`, `EXCLUDE_FROM_INDEX`, `REVIEW`, `DISCLOSE`, `TRACK_ONLY`
  - canonical tiers: `VERIFIED`, `VALIDATED_WITH_WARNINGS`, `PRELIMINARY`, `UNDER_REVIEW`
  - rule IDs for every validation rule (column rules C01-C##, cross-column rules X01-X10, adapter rules GAV01, PCT01, etc.)
  - common issue schema: `dataset, source, cik, report_date, row_key, column, rule_id, severity, evidence_strength, status, action, value, message, evidence`
  - common metric schema: `dataset, source, cik, quarter, column, fill_rate, parse_rate, valid_rate, fail_count, warn_count`

- Implement column contracts per the tables above. All rules use DuckDB SQL (no pandas `.apply()` or `.iterrows()` on the 693K-row dataset).

- Use separate validation approaches under the shared framework:
  - BDC rules: aggregate/header leakage, duplicate dimension-path suspects, required raw identifier preservation, numeric parse checks, rate range checks (percentage scale), pct-of-net-assets sanity.
  - N-PORT rules: SEC enum validity, identifier format checks (CUSIP/ISIN length), source-specific field consistency, consumer-lending exclusion checks, asset category versus classification consistency.
  - HTML-template rows, if present: template-derived rows should be flagged as weaker unless template validation and GAV reconciliation pass.

- Implement adapters for existing `validate_holdings.py` functions per the integration table above.

- Compute CIK-quarter quality summary from the unified issues table.

- Update `pipeline.export_frontend._export_data_quality()` and frontend TypeScript types to expose:
  - validation tier counts
  - issue counts by severity
  - issue counts by evidence strength
  - top failing columns
  - column fill/parse/valid rates
  - existing GAV and reconciliation histograms

## Test Plan

- Add unit tests for the validation contract:
  - valid rows produce no `FAIL`
  - invalid enum values produce `FAIL`
  - non-parseable required numerics produce `FAIL`
  - missing optional fields produce `WARN` or `INFO`, not `FAIL`
  - source-specific fields are only required for the relevant source
  - rate values at percentage scale (e.g. 9.80) are accepted; would-be decimal values (e.g. 0.098) are not falsely flagged

- Add contextual severity tests:
  - null `fair_value` on an indexable row produces `FAIL`
  - null `fair_value` on a documented non-indexable row does not produce `FAIL`
  - suspected aggregate produces `WARN`
  - confirmed aggregate produces `FAIL`
  - `9999-12-31` maturity produces `INFO`
  - malformed year like `0225-06-28` produces `FAIL`

- Add column-rule tests:
  - `principal_amount` = 100x `fair_value` triggers X06 FAIL
  - `interest_rate` = 30 triggers WARN; = 9.8 passes
  - `pct_of_net_assets` = 200 triggers X09 FAIL
  - `asset_class=PRIVATE_CREDIT` with null interest_rate and null basis_spread triggers X02 WARN

- Add cross-column tests:
  - PRIVATE_EQUITY row with interest_rate = 8.5 triggers X01 WARN
  - PRIVATE_CREDIT row with interest_rate = 7.0 does not trigger X01
  - Fixed coupon_type with basis_spread = 3.0 triggers X04 FAIL
  - Floating coupon_type with basis_spread = null triggers X05 WARN

- Add BDC-specific tests:
  - subtotal/header issuer names are flagged
  - real company names containing risky words are not falsely flagged
  - duplicate same-CIK/report-date/FV/name rows are flagged as duplicate suspects
  - malformed rates and maturity dates are reported with correct severity

- Add N-PORT-specific tests:
  - valid SEC asset/issuer codes pass
  - unknown codes warn or fail according to contract
  - excluded consumer-lending CIKs are reported as documented exclusions, not silent data loss
  - classification contradictions are counted

- Add adapter tests:
  - GAV ratio of 0.2 produces GAV01 FAIL
  - GAV ratio of 0.75 produces GAV02 WARN
  - GAV ratio of 1.0 produces no issue
  - pct sum of 250% produces PCT01 WARN
  - suspected aggregate leak produces AGG01 WARN
  - confirmed aggregate leak produces AGG02 FAIL

- Add integration tests:
  - validator emits all three CSV artifacts with stable columns
  - `validate_holdings()` includes the new reports without breaking existing outputs
  - frontend `data_quality.json` type shape matches `frontend/src/lib/types.ts`
  - `npm run build` passes after frontend type changes

## Scope Exclusions (Deferred To Later Slices)

### Agent correction loops

This slice produces issues and metrics. Automated remediation (e.g., agents that fix scale errors or reclassify positions) is a future slice that consumes these outputs.

### Position matching validation

Validating `position_id` chain quality (match accuracy, orphan detection, cross-quarter continuity) is important but depends on a different data artifact (`position_matches.csv`). Defer to a dedicated position-matching validation plan.

### Entity resolution validation

`entity_id` coverage is 88% overall but lower for N-PORT. Validating entity resolution quality (false merges, missed matches) requires its own test harness. Track fill rate as INFO in this slice; defer quality validation.

### Temporal / cross-quarter consistency

Detecting anomalies like FV jumping 10x between quarters, rate changes from 5% to 50%, or positions disappearing and reappearing with drastically different FV requires joining across quarters via `position_id`. This is valuable but architecturally distinct from single-quarter column validation. Defer.

### Trend tracking

Not relevant for this slice. The dataset covers a fixed historical window (Q4 2022 to current). Trend tracking becomes relevant when the pipeline runs on a schedule and regressions need detection.

### Scale/unit detection for unified holdings

The HTML template validator has unit detection (Gate 2), but unified holdings has no check for whether BDC XBRL values arrived at the wrong power-of-ten. The `principal_amount` $269B outlier is evidence this happens. Adding systematic unit detection (comparing position-level FV against CIK-level total assets) is deferred but flagged as high-value follow-up.

## Assumptions And Defaults

- First implementation slice is contract plus validators, not agent correction infrastructure.
- `private_markets_holdings.csv` is the first dataset covered; later plans can extend the same framework to `fund_financials.csv`, `position_returns.csv`, and frontend JSON.
- Column-level validation is not treated as proof of accuracy. Stronger source reconciliation, especially BDC XBRL row reconciliation, remains the next major verifier after this slice.
- Existing generated frontend JSON should not be hand-edited; all public quality data should flow through the export pipeline.
- NULL semantics are context-dependent: a column marked "Required When [condition]" should be non-null when the condition holds. NULL outside that condition is valid (not applicable), not a data gap.
