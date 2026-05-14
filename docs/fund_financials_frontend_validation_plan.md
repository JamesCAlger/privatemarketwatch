# Fund-Level Data Validation Plan

## Summary

The goal is to validate the 33 columns from `fund_financials.csv` that flow through `export_frontend.py` to the frontend, plus the cross-level reconciliation between fund-level data and position-level data in `private_markets_holdings.csv`. Validation targets the source data itself, not just the export representation -- if `fund_financials.csv` is wrong, everything downstream is wrong.

The approach extends the current unified holdings validation architecture to fund-level data: deterministic checks produce focused validation artifacts, row/check-level issues carry severity and evidence strength, frontend quality tiers are derived from those artifacts, and agent playbooks are reserved for unresolved residuals and filer-specific mechanisms.

## Relationship to Unified Holdings Validation Architecture

Fund-level validation should reuse the unified holdings validation model, not create a disconnected quality system. The current holdings stack already combines reconciliation outputs, coverage reports, row-level issues, column-quality metrics, quality-tier summaries, and frontend data-quality exports. Fund-level validation should add fund-financial-specific checks to that pattern.

The direct parallels are:

| Fund-level need | Unified holdings analogue | Implementation direction |
|---|---|---|
| Source-to-output reconciliation | GAV reconciliation, coverage, pct sum, count stability | Add fund-level reconciliation artifacts and extend cross-level checks where holdings are the comparison source |
| Row/check-level issue reporting | `row_validation_issues.csv` | Reuse or deliberately extend the issue schema with fund-level check codes |
| Severity and confidence | `severity` and `evidence_strength` in column validation | Derive quality tiers from issue counts and evidence strength, not from hand-assigned labels |
| Frontend quality disclosure | `data_quality_metrics.csv`, `column_quality_metrics.csv`, frontend data-quality export | Add per-fund and per-metric quality metadata without replacing existing aggregate quality exports |
| Agent review loop | constrained residual investigation and documented findings | Use agents to investigate failures and document evidence, then codify deterministic checks |

Fund-level data adds idiosyncrasies that holdings validation does not cover: balance-sheet identities, NAV/share-class effects, consolidated vs unconsolidated reporting, annualized versus period return scale, YTD-to-quarterly deltas, period selection, and source mixing across companyfacts, N-PORT, N-CEN, and N-CSR.

## Scope: 33 Exported Columns

### Identity and timing (6 columns)

| Column | Export target | Notes |
|---|---|---|
| `cik` | fund_list, fund_details | Primary key |
| `entity_name` | fund_list (as `name`) | Display name |
| `vehicle_type` | fund_list (`vehicleType`) | BDC, interval_fund, tender_offer_fund |
| `source` | fund_details series | companyfacts, nport, ncen |
| `report_quarter` | fund_details series (`quarter`) | Period label |
| `report_date` | fund_details series (`reportDate`) | Period end date |

### Balance sheet (6 columns)

| Column | Export target | Notes |
|---|---|---|
| `total_assets` | fund_list, fund_details, fund_summary, AUM time series | Primary size metric |
| `net_assets` | fund_details series | Used in leverage, pct calculations |
| `total_liabilities` | fund_details series | Balance sheet identity component |
| `nav_per_share` | fund_list, fund_details | Per-share NAV |
| `shares_outstanding` | fund_details series | NAV identity component |
| `borrowings` | fund_details series | Leverage numerator |

### Income (2 columns)

| Column | Export target | Notes |
|---|---|---|
| `total_investment_income` | fund_details series | Gross income |
| `net_investment_income` | fund_details series | After expenses |

### Ratios and rates (6 columns)

| Column | Export target | Notes |
|---|---|---|
| `leverage_ratio` | fund_list, fund_details, fund_summary | borrowings / total_assets, capped 2.0 |
| `management_fee_pct` | fund_details series | Fee rate |
| `expense_ratio_pct` | fund_list, fund_details, fund_summary | Total expense rate |
| `distribution_rate` | fund_list, fund_details | Yield metric |
| `distribution_rate_proxy` | fund_details series | Reinvestment-based proxy |
| `redemption_pressure` | fund_list, fund_details | Binary cap signal from N-PORT |

### Returns (6 columns)

| Column | Export target | Notes |
|---|---|---|
| `quarterly_return` | fund_list, fund_details, fund_index_returns | Product of 3 monthly returns |
| `total_return_pct` | fund_list, fund_details | NAV-based total return |
| `income_yield_pct` | fund_list, fund_details | Income return component |
| `annualized_return` | fund_details series | Annualized quarterly return |
| `monthly_return_1/2/3` | fund_details series | N-PORT monthly returns |
| `gross_return_pct` | fund_details series (computed) | total_return_pct + fee add-back |

### Distribution (2 columns)

| Column | Export target | Notes |
|---|---|---|
| `distribution_per_share` | fund_details, fund_index_returns | Per-share distribution |
| `income_per_share` | fund_details series | Per-share NII |

### Portfolio and risk (4 columns)

| Column | Export target | Notes |
|---|---|---|
| `portfolio_turnover` | fund_details series | Turnover rate |
| `asset_coverage_ratio` | fund_details series | BDC regulatory ratio |
| `unfunded_commitments` | fund_details series | Undrawn commitments |
| `premium_discount_pct` | fund_list, fund_details | Market price vs NAV |

### Not in fund_financials (2 columns, separate sources)

| Column | Source | Notes |
|---|---|---|
| `adviser_name` | fund_identity.csv | Adviser name |
| `ticker` | fund_identity.csv | Trading symbol |

## Validation Maturity Lifecycle

### Phase 1: Discovery (agent playbooks)

Run the checks below across all CIK-quarters. Deterministic outputs should be written as focused artifacts, following the unified holdings pattern: reconciliation reports, coverage reports, row/check-level issues, column-quality metrics, and quality summaries. Agent investigation starts from those artifacts, documents mechanisms in `data/output/data_investigation_results.md`, and proposes tolerances or filer-specific overrides.

This is where the work happens. Most checks have a known correct answer (balance sheet identity, rate scale bounds), but the failure modes are filer-specific and need investigation to catalogue: consolidated vs unconsolidated reporting, YTD-to-quarterly delta artifacts, share class mixing, comparative period contamination.

### Phase 2: Codification

Convert findings into a `validate_fund_financials()` function (preferably in `pipeline/validate_fund_financials.py`). Each check gets a code (F1, F2, ...), threshold, check status, severity, evidence strength, and source provenance. The validator should produce both focused report DataFrames and a unified issue DataFrame compatible with the existing row/column quality model.

### Phase 3: Steady state

Checks run as part of the rebuild/export pipeline. New filings are validated automatically. Agent playbooks are only invoked for new failure patterns that the deterministic checks do not cover. `export_frontend.py` consumes validation artifacts and derived quality summaries to populate fund-level and metric-level quality fields in frontend JSON.

## Validation Surfaces

The validation design has three surfaces. They should share status/severity conventions but should not be collapsed into one artifact.

1. **Fund financial source validation:** checks `fund_financials.csv` fields for accounting identities, period selection, rate/return scale, entity identity, and stale/missing data.
2. **Cross-level reconciliation:** compares `fund_financials.csv` against `private_markets_holdings.csv`, after holdings validation has run, to catch extraction gaps, aggregate leakage, denominator errors, and pipeline coverage gaps.
3. **Frontend-derived export validation:** checks values computed inside `export_frontend.py`, including finite JSON values, exposure splits, top holdings, FV hierarchy, and computed `gross_return_pct`.

## Status, Severity, and Evidence

Fund-level check outputs should keep explicit check status while also using the existing validation vocabulary:

- `status`: `PASS`, `FAIL`, `SKIP`, or `KNOWN_RESIDUAL`.
- `severity`: `FAIL`, `WARN`, or `INFO`.
- `evidence_strength`: `STRONG`, `MODERATE`, or `WEAK`.

`status` describes the result of a specific check. `severity` describes whether the issue should block, warn, or disclose. `evidence_strength` describes how directly the check proves a data problem. Quality tiers are derived from severity/evidence counts, unresolved failures, and staleness, not assigned manually per check.

## Validation Rules

### Tier 1: Hard gates (block export or mark as rejected)

These checks have unambiguous correct answers. Failure means the data is wrong, not borderline.

| Code | Rule | Check | Action |
|---|---|---|---|
| F1 | No NaN/Infinity in export | All 27 numeric columns are finite or null | Block row from export |
| F2 | No future report dates | `report_date <= today` | Block row |
| F3 | Asset split sums to 100% | Fund exposure percentages: `debt + equity + fund + structured + cash + other ~= 1.0` | Block exposure export for CIK |
| F4 | Lien split bounded | `firstLien + secondLien + unsecured <= 1.0` when debt coverage reported | Block exposure export for CIK |
| F5 | Rate type bounded | `floating + fixed <= 1.0` when debt rate coverage reported | Block exposure export for CIK |
| F6 | Maturity bucket sum | Sum of maturity bucket percentages = 1.0 when WAM-covered FV exists | Block exposure export for CIK |
| F7 | Top holdings bounded | Sum of top holding `pctOfPortfolio` <= 1.0 | Block top holdings for CIK |
| F8 | FV hierarchy sums to 100% | `level1 + level2 + level3` within 95-105% where coverage reported | Block FV hierarchy for CIK |

### Tier 2: Reconciliation checks (flag with quality tier)

These checks have known identities but tolerate filer-specific variance. Failure means investigate, then either fix source logic or document as known residual.

#### Self-consistency (fund_financials internal)

| Code | Rule | Formula | Tolerance | Notes |
|---|---|---|---|---|
| F10 | Balance sheet identity | `total_assets - total_liabilities = net_assets` | 1% of total_assets | Skip when any field missing |
| F11 | NAV identity | `nav_per_share * shares_outstanding = net_assets` | 2% of net_assets | Multiple share classes may cause divergence |
| F12 | Leverage consistency | `borrowings / total_assets = uncapped leverage_ratio` before export cap | 5pp | Capped exported leverage cannot prove source consistency by itself |
| F13 | Expense ratio components | `management_fee_pct <= expense_ratio_pct` | Flag if mgmt_fee > expense_ratio | Management fee is a subset of total expenses |
| F14 | Return composition | `total_return_pct` directionally consistent with income and NAV movement | 10pp | Weak proxy; do not treat as proof without source evidence |
| F15 | Gross vs net return | `gross_return_pct >= total_return_pct` | Flag if net > gross | Gross includes fee add-back |
| F16 | Distribution vs income | `distribution_rate <= income_yield_pct * 1.5` | Flag if distribution consistently exceeds income | Business sustainability flag, not necessarily a data error |
| F17 | Quarterly return vs monthly | `quarterly_return ~= (1+m1)*(1+m2)*(1+m3) - 1` | 0.1pp | Verifies the product formula |
| F18 | Asset coverage ratio | BDCs: `asset_coverage_ratio >= 1.5` (regulatory minimum) | Flag if below | Regulatory/business flag, not a data correctness gate |

#### Cross-level reconciliation (fund_financials vs unified_holdings)

| Code | Rule | Formula | Tolerance | Notes |
|---|---|---|---|---|
| F20 | Holdings FV vs investments at FV | `SUM(holdings.fair_value) / fund_financials.investments_at_fair_value` | 0.8-1.2x | Already in `check_gav_reconciliation()`; extend |
| F21 | Holdings FV vs net_assets | `SUM(holdings.fair_value) / fund_financials.net_assets` | 0.5-2.5x (BDCs leverage) | BDCs typically >1.0; interval funds ~1.0 |
| F22 | pct_of_net_assets sum | `SUM(pct_of_net_assets)` | 50-400% | <50% = incomplete extraction; >400% = duplication |
| F23 | pct vs computed pct | `SUM(fv) / net_assets * 100` vs `SUM(pct_of_net_assets)` | 10% relative | Catches filer-reported % inconsistent with FV/NAV |
| F24 | Position count stability | `COUNT(positions)_q / COUNT(positions)_{q-1}` | 0.5-2.0x | Sudden drop = extraction failure; spike = aggregate leak |
| F25 | Holdings FV stability | `SUM(fv)_q / SUM(fv)_{q-1}` vs `total_assets_q / total_assets_{q-1}` | Directional agreement within 30pp | Catches mismatched growth signals |
| F26 | Leverage from two views | `borrowings / total_assets` vs `(SUM(fv) - net_assets) / SUM(fv)` | 20pp | Rough check; non-investment assets create noise |
| F27 | WAC vs income yield | Holdings-level WAC vs `income_yield_pct` | WAC > income_yield (fees reduce yield) | Flag if income_yield > WAC by >200bps |
| F28 | Coverage completeness | CIKs with fund_financials row but no holdings, and vice versa | Flag mismatches | Catches pipeline gaps |

### Tier 3: Anomaly detection (informational, not blocking)

These checks flag unusual values for investigation. They do not block export or change quality tiers unless investigation confirms a data error.

| Code | Rule | Check | Notes |
|---|---|---|---|
| F30 | NAV per share range | `0.01 < nav_per_share < 1000` | Most BDCs trade $5-$30; interval funds $10-$50 |
| F31 | Quarterly return range | `-50% < quarterly_return < +50%` | Extreme but possible in distress/recovery |
| F32 | Expense ratio range | `0 < expense_ratio_pct < 20%` | Most funds 1-5%; outliers need investigation |
| F33 | Distribution rate range | `0 < distribution_rate < 30%` | Most funds 5-15% |
| F34 | Leverage ratio range | `0 <= leverage_ratio <= 2.0` | Already capped in fund_financials |
| F35 | Total assets quarter change | Flag >50% change without corresponding holdings FV change | Structural shift or data error |
| F36 | NAV per share quarter change | Flag >30% change quarter-over-quarter | Reverse split, special distribution, or data error |
| F37 | Quarter gap detection | Flag CIKs missing expected quarters (e.g., Q1, Q3 but no Q2) | Missing filing or extraction failure |
| F38 | Stale data detection | Flag CIKs whose latest report_date is >2 quarters behind universe | Fund may have liquidated, merged, or filing is delayed |
| F39 | Vehicle type consistency | `vehicle_type` in fund_financials matches combined_universe | Catches merge/reclassification |
| F40 | Entity name consistency | Flag where fund_financials entity_name diverges significantly from holdings entity_name | Name changes, mergers |
| F41 | PIK exposure range | `0 <= pik_pct <= 100%` for fund exposure | |
| F42 | Income per share vs distribution | `income_per_share >= distribution_per_share` over trailing year | Sustained underearn flags sustainability risk |

## Playbooks

### What a playbook is

A playbook is a structured investigation workflow for validation failures that have multiple possible root causes. It is not a single check or assertion -- it is a sequence of diagnostic steps that an agent or developer follows to trace a failure back to its source data, identify the mechanism, and decide on a resolution.

Each playbook has a standard structure:

1. **Trigger:** Which check codes activate this playbook and what a failure looks like (e.g., "F10 FAIL: total_assets - total_liabilities differs from net_assets by >1%").
2. **Scope:** The unit of investigation -- always a single (CIK, quarter) pair. Never investigate globally before understanding the fund-period-level mechanism.
3. **Inputs:** The source artifacts to load (cached XBRL, companyfacts JSON, N-PORT TSV rows, N-CSR HTML, fund_financials.csv rows, unified holdings rows for that CIK-quarter).
4. **Investigation steps:** An ordered sequence of diagnostic checks, each producing a finding (confirmed, ruled out, or inconclusive). Steps are ordered from most common root cause to least common.
5. **Output:** A structured record per (CIK, quarter, check_code) containing:
   - `status`: PASS, FAIL, SKIP (missing data), KNOWN_RESIDUAL (investigated, accepted).
   - `value`: the computed metric (e.g., the variance amount).
   - `expected`: the expected value or range.
   - `mechanism`: the root cause identified (e.g., "consolidated vs unconsolidated", "share class mismatch"), or null if unresolved.
   - `source_fields`: which source artifacts were consulted.
   - `note`: free-text explanation for FAIL or KNOWN_RESIDUAL cases.
6. **Resolution:** One of:
   - **Fix source logic:** the pipeline code is wrong, fix it in `fund_financials.py` or `unified_holdings.py`.
   - **Add filer-specific override:** the filer's data has a known quirk, document it and add a correction with evidence.
   - **Accept as known residual:** the divergence is real but not a data error (e.g., multi-class NAV), mark as KNOWN_RESIDUAL with explanation.
   - **Escalate:** the mechanism is unclear, flag for manual review.

During Phase 1 (Discovery), playbooks are run by an agent that investigates each failure and documents findings. During Phase 3 (Steady State), the investigation steps that proved diagnostic are codified into deterministic checks, and only genuinely new failure patterns re-trigger the full playbook.

### Playbook inventory

Not every rule needs a playbook. Playbooks exist for investigation workflows where failure has multiple possible root causes that must be traced through source data. The 39 rules map to 5 playbooks:

| Playbook | Rules covered | Why it needs investigation |
|---|---|---|
| Balance Sheet Reconciliation | F10, F11, F12 | Consolidated vs unconsolidated, share classes, YTD deltas |
| Period Selection | Upstream of F10-F18 | Comparative-period contamination, dimension-path duplicates |
| Rate Scale Validation | F30-F34, feeds F14-F17 | Decimal vs percent ambiguity, annualized vs period, source units |
| Cross-Level Reconciliation | F20-F28 | Extraction gaps, aggregate leaks, dedup failures, scale mismatches |
| Residual Review | Any rule | Catch-all for failures that don't fit the above |

Rules that do **not** need playbooks:

- **F1-F8** (hard gates): Pure assertions. If NaN appears in a numeric column or a split doesn't sum, the producing code is wrong -- fix it directly.
- **F13, F15, F16, F18** (simple comparisons): If management_fee exceeds expense_ratio, look at the source value. No multi-step investigation.
- **F35-F42** (anomaly flags): Range checks and consistency flags produce a list of CIK-quarters to review. Investigation is ad hoc, not structured enough for a playbook.

### 1. Balance Sheet Reconciliation (F10, F11, F12)

Use cached filing facts to compare reported assets, liabilities, net assets, NAV per share, shares outstanding, borrowings, and leverage ratio for each fund-period.

Expected output per (CIK, quarter):

- Reconciliation status: PASS, FAIL, SKIP (missing fields).
- Absolute and percentage variance.
- Source fields used and their provenance (companyfacts concept, N-PORT field, N-CSR table).
- Filing accession and report period.
- Explanation for missing or unresolved fields.

Investigation steps for FAIL cases:

1. **Consolidated vs unconsolidated.** Check whether the filer reports consolidated financials that include subsidiary assets/liabilities not reflected in the fund-level balance sheet. Common for BDCs with SBIC subsidiaries.
2. **Multiple share classes.** NAV identity (F11) may fail when `nav_per_share` is for a single class but `shares_outstanding` aggregates all classes. Check companyfacts for class-level dimensions.
3. **YTD-to-quarterly delta artifacts.** The pipeline converts YTD cumulative XBRL concepts to quarterly via delta logic. Check whether a negative or doubled quarterly value is an artifact of the conversion (e.g., amended filing restating YTD).
4. **Comparative-period contamination.** Check whether `total_assets` or `net_assets` was pulled from a comparative-period context rather than the current-period context.
5. **Leverage computation (F12).** Check whether `borrowings` includes only credit facility draws or also includes notes payable, securitizations, or preferred stock. Compare `borrowings / total_assets` to the reported `leverage_ratio`.

Tolerance: 1% of total_assets for F10, 2% of net_assets for F11, 5pp for F12. These may be revised during discovery.

### 2. Period Selection (upstream of F10-F18)

Not tied to a single rule. This is a root-cause playbook that affects any fund_financials value. The question is: for each CIK-quarter, are we selecting the right filing facts?

Investigation steps:

1. **period and report_date alignment.** Verify that the `period` (XBRL context instant date) matches the `report_date` (period of report). Flag cases where they diverge by >30 days.
2. **Accession consistency.** Check whether all facts for a CIK-quarter come from the same filing accession. Mixed accessions indicate a merge across filings (e.g., 10-K and 10-Q both covering the same quarter).
3. **Duplicate concept values across dimension paths.** Some filers report per-share data under multiple share class axes. Check whether the pipeline selects the correct aggregate or class-level value.
4. **Current period versus prior period.** Comparative-period facts (prior year's balance sheet reported in this year's filing) must not overwrite current-period values. Check the `startDate`/`endDate`/`instant` of each XBRL context.

Investigate when multiple plausible current-period values exist and no deterministic source priority resolves them.

### 3. Rate Scale Validation (F30-F34, feeds F14-F17)

Validate percentage, rate, yield, and return fields against expected ranges and source units.

Investigation steps:

1. **Decimal versus percent scale.** Check the raw companyfacts, N-PORT, or N-CSR value together with the concept, unit, source table label, and existing pipeline transformation. XBRL `decimals` describes precision/rounding; it is not sufficient by itself to infer percent-versus-decimal semantics.
2. **Annualized versus period return.** Check whether `total_return_pct` and `income_yield_pct` are quarterly or annualized. N-CSR Financial Highlights typically report annualized; N-PORT monthly returns are per-period. Verify labeling.
3. **Impossible or extreme values.** For flagged values (F30-F34), pull the raw source fact and trace through the pipeline transformation to identify where the scale went wrong.
4. **Consistency with income, NAV, and period length.** Cross-check: `income_yield_pct ~= net_investment_income / net_assets * (12 / period_months)`. If they diverge, one is wrong.

Range checks start as Tier 3 flags. When investigation reveals a systematic scale error, it becomes a Tier 2 check with corrective logic in `fund_financials.py`.

### 4. Cross-Level Reconciliation (F20-F28)

Compare fund-level data against position-level aggregates from unified holdings. This is the dual-view validation: top-down (fund_financials from filing facts) versus bottom-up (holdings from schedule-of-investments extraction).

Prerequisites: unified holdings validation artifacts must be current and reviewed. Cross-level checks are only meaningful if the holdings data has no unresolved strong-evidence `FAIL` issues for the same CIK-period.

Investigation steps for each (CIK, report_date) where both datasets exist:

1. **Compute holdings aggregates.** `SUM(fair_value)`, `SUM(pct_of_net_assets)`, `COUNT(*)`, FV-weighted average `interest_rate` (WAC), position count.
2. **Compare FV to fund-level (F20, F21).** If `SUM(holdings.fv)` is <80% of `investments_at_fair_value`, check for: missing extraction tables, positions excluded by aggregate filtering, cross-source dedup removing valid positions. If >120%, check for: aggregate rows that leaked through filtering, affiliation-axis duplicates, multi-dimension-path duplicates.
3. **Compare pct_of_net_assets (F22, F23).** If `SUM(pct)` is <50%, holdings extraction is incomplete. If >400%, duplication (likely affiliation-axis or multi-dimension-path). If `SUM(fv)/net_assets*100` diverges from `SUM(pct)` by >10%, either the filer-reported percentages are inconsistent with FV/NAV, or `net_assets` in fund_financials is wrong (check F10).
4. **Check temporal stability (F24, F25).** If position count drops >50% quarter-over-quarter but `total_assets` is stable, the extraction for that quarter likely failed partially. If `SUM(fv)` grows >30pp faster than `total_assets`, check for new positions that are actually aggregate rows.
5. **Compare leverage (F26).** Compute implied leverage from holdings as `(SUM(fv) - net_assets) / SUM(fv)`. Compare to `borrowings / total_assets`. Divergence >20pp may indicate: non-investment assets (cash, receivables) inflating total_assets but not in holdings; or `borrowings` missing some debt instruments.
6. **Compare WAC to income yield (F27).** Holdings-level WAC should exceed `income_yield_pct` because fees reduce net income. If `income_yield_pct` exceeds WAC by >200bps, check for: WAC computed on insufficient coverage (<50% of debt FV has rate data), or `income_yield_pct` includes non-interest income (e.g., fee income, dividend income from equity positions).
7. **Check coverage (F28).** Flag CIKs with fund_financials but no holdings (may be pre-XBRL BDCs, or interval/tender funds with N-PORT but no unified holdings match). Flag CIKs with holdings but no fund_financials (pipeline gap in fund_financials extraction).

Existing implementation: `check_gav_reconciliation()` in `validate_holdings.py` covers F20. Extend with F21-F28 in the same function or create parallel functions in the new validation module.

Output: focused reconciliation artifacts plus issue rows. Each issue row should include `(cik, report_quarter, report_date, check_code, status, severity, evidence_strength, value, expected, mechanism, source_artifacts, note)`.

### 5. Residual Review (any rule)

Catch-all playbook for failures that don't fit the structured playbooks above, or for Tier 3 anomaly flags that need ad hoc investigation.

When validation fails, investigate at the fund-period scope before adding global logic.

Document:

- Question investigated.
- Source facts or cached files used.
- Commands or queries used.
- Mechanism found or hypotheses rejected.
- Before and after validation metric.
- Residual uncertainty.

Durable findings should be saved to `data/output/data_investigation_results.md`.

## Iteration Workflow and Regression Detection

### Why snapshots, not full automation

The fund-level validation loop (run checks, investigate FAILs, fix, re-run) should start with bounded manual/agent investigation rather than full autonomous loop infrastructure. The expected failure modes are narrower than unified holdings -- accounting identities, scale errors, period selection -- but convergence speed should be measured from the validation artifacts rather than assumed. The source CSVs do not need snapshotting if `fund_financials.csv` is rebuilt deterministically from cached filings and git history provides rollback.

What is worth doing: snapshot the **validation output** (not the data) so that every code change produces a clear before/after diff.

### Artifacts

| File | Purpose | When created |
|---|---|---|
| `data/output/fund_financials_validation_baseline.csv` | Frozen issue/check output before an investigation cycle | Start of each cycle |
| `data/output/fund_financials_validation_current.csv` | Latest issue/check output after code changes | After each re-run |
| `data/output/fund_financials_validation_accepted.csv` | Promoted baseline after unresolved issues stabilize | End of cycle, when residuals are accepted |
| `data/output/fund_financials_quality_metrics.csv` | Per-CIK quality tier summary derived from severity/evidence counts | Every validation run |

The baseline/current/accepted files share the same issue schema: `(validation_run_id, cik, report_quarter, report_date, check_code, status, severity, evidence_strength, value, expected, mechanism, source_artifacts, note)`.

### Workflow

**Step 1: Establish baseline.**

Run all checks across all CIK-quarters. Save issue/check output as `fund_financials_validation_baseline.csv`. Record `FAIL`, `WARN`, `INFO`, strong-evidence issue count, and unresolved issue count by check code.

**Step 2: Investigate and fix.**

Agent investigates the top FAIL clusters by volume using the appropriate playbook. Proposes code changes (to `fund_financials.py`, `unified_holdings.py`, or `export_frontend.py`). Human reviews and approves each fix.

**Step 3: Re-run and diff.**

Rebuild `fund_financials.csv` if source logic changed. Re-run all checks, save as `fund_financials_validation_current.csv`. Diff against baseline:

```sql
-- Improvements: FAIL -> PASS
SELECT b.cik, b.report_quarter, b.check_code, b.status AS before, c.status AS after
FROM baseline b
JOIN current c USING (cik, report_quarter, check_code)
WHERE b.status = 'FAIL' AND c.status = 'PASS';

-- Regressions: PASS -> FAIL
SELECT b.cik, b.report_quarter, b.check_code, b.status AS before, c.status AS after
FROM baseline b
JOIN current c USING (cik, report_quarter, check_code)
WHERE b.status = 'PASS' AND c.status = 'FAIL';
```

**Step 4: Review regressions.**

If regressions exist, investigate whether they are genuine (the fix exposed a latent issue) or harmful (the fix broke something). Accept, fix further, or revert the change.

**Step 5: Promote baseline.**

When unresolved strong-evidence issues stabilize and remaining failures are accepted as known residuals (marked `KNOWN_RESIDUAL` with mechanism, source artifacts, and note), copy current to `fund_financials_validation_accepted.csv`. This becomes the steady-state regression reference. Future pipeline changes diff against this file.

### Interdependency awareness

Fund-level checks are interdependent. Fixing one check can change the results of others:

- **F10 (balance sheet identity) affects F23 (pct vs computed pct).** If `net_assets` is wrong and gets corrected, the computed `SUM(fv) / net_assets * 100` changes, which may flip F23 from PASS to FAIL or vice versa.
- **F10/F11 affect V7 (pct_of_net_assets correction).** The V7 correction in `unified_holdings.py` uses `net_assets` from `fund_financials.csv`. If F10 reveals that `net_assets` was wrong, the V7 correction was using a bad denominator. Fixing F10 may require re-running `--unified` to recalculate corrected percentages.
- **Period selection fixes affect all Tier 2 checks.** If a comparative-period fact was contaminating `total_assets`, fixing the period selection changes F10, F12, F20, F21, F25, and F26 simultaneously.

The diff will surface these cascading effects. When reviewing regressions in Step 4, check whether the regression is downstream of a fix applied in the same iteration -- if so, it's expected and should be investigated as a secondary effect, not treated as an independent regression.

## Frontend Export Contract

`export_frontend.py` should export fund-level financials together with validation metadata derived from the fund-level quality artifacts. The frontend should use that metadata to surface data status without replacing the existing aggregate data-quality dashboard.

Per-fund validation fields in `fund_details/{cik}.json`:

- `validationStatus`: overall quality tier for the CIK (`verified`, `validated_with_warnings`, `under_review`, `stale`).
- `metricValidation`: optional map from metric group to quality tier, so a fund can have verified balance-sheet data but return data still under review.
- `validationChecks`: array of `{ code, status, severity, evidenceStrength, note }` for failed/flagged checks.
- `lastValidated`: timestamp of last validation run.

Quality tier assignment:

- `verified`: no unresolved `FAIL` or `WARN` issues for the relevant fund/metric group.
- `validated_with_warnings`: no unresolved `FAIL` issues, but one or more `WARN` or `KNOWN_RESIDUAL` issues remain.
- `under_review`: unresolved `FAIL` issues or failures under active investigation.
- `stale`: latest report_date is >2 quarters behind universe.

The frontend should avoid showing precise derived metrics (gross_return_pct, income_yield_pct) without an associated quality tier.

## Relationship to Existing Validation

### What already exists

| Component | Location | Relevance |
|---|---|---|
| `check_gav_reconciliation()` | `validate_holdings.py` | Implements F20. Extend with F21-F28 or keep as bridge. |
| `check_coverage()` | `validate_holdings.py` | Overlaps with F28 (coverage completeness). |
| `check_cross_source_overlap()` | `validate_holdings.py` | Validates BDC/N-PORT exclusivity. |
| `run_column_quality_validation()` | `column_validation.py` | Provides severity/evidence issue schema and validation-tier summaries to reuse or extend. |
| Frontend data-quality export | `export_frontend.py` | Already consumes validation artifacts for aggregate quality disclosures. |
| V7 pct_of_net_assets correction | `unified_holdings.py` | Uses `net_assets` from fund_financials; depends on F10/F11 being correct. |
| `leverage_ratio` cap at 2.0 | `fund_financials.py` | Upstream guard; F12 validates the computation. |
| YTD-to-quarterly delta logic | `fund_financials.py` | Source of potential errors; period selection playbook investigates. |

### What this plan adds

- Self-consistency checks on fund_financials itself (F10-F18): balance sheet identity, return composition, expense components.
- Extended cross-level checks (F21-F28): beyond GAV reconciliation to include pct_of_net_assets, position stability, leverage from two views, WAC vs income yield.
- Export-level hard gates (F1-F8): NaN/Infinity, split-sum violations, top-holdings bounds.
- Anomaly detection (F30-F42): range checks, temporal stability, entity consistency.
- Fund-level quality tier framework that extends, rather than replaces, the existing validation artifact and frontend quality export model.

### Namespace separation

Fund-level checks use the F-prefix (F1, F10, F20, F30). Holdings-level checks retain their existing validation namespaces and artifacts, including V-series aggregate checks and C/X-series row/column issue codes. Cross-level checks (F20-F28) bridge both; they live in the fund-level namespace because they validate fund-level data using holdings as the reference.

## Test Plan

### Tier 1 (hard gates)

- F1: test with NaN, Infinity, -Infinity, null, valid float in each numeric column.
- F3-F6: test with splits that sum correctly, splits that exceed total, splits with nulls.
- F7: test with top holdings summing to less than, equal to, and exceeding total FV.
- F8: test with FV hierarchy summing to 100%, 90%, 110%, and with missing levels.

### Tier 2 (reconciliation)

- F10: test with matching identity, 0.5% variance (PASS), 2% variance (FAIL), one field missing (SKIP), all missing (SKIP).
- F11: test with single share class (PASS), multi-class divergence (known residual), shares missing (SKIP).
- F17: test with consistent monthly/quarterly returns, and with rounding-induced mismatch.
- F20: test with ratio at 1.0, 0.85, 1.15, 0.5, 2.0.
- F22: test with pct_sum at 100%, 180% (leveraged BDC, PASS), 450% (FAIL), 30% (FAIL).
- F24: test with stable count, 50% drop (FAIL), 2x increase (FAIL).

### Tier 3 (anomaly detection)

- F30-F34: test with values inside, at boundary, and outside expected ranges.
- F35-F36: test with normal quarter-over-quarter change, extreme change, and missing prior quarter.
- F37: test with consecutive quarters, gap, and single quarter.

### Cross-level

- F23: test where filer-reported pct_of_net_assets agrees with computed, disagrees by 15%, and where net_assets is missing.
- F27: test where WAC exceeds income_yield (normal), WAC below income_yield by 100bps (flag), and WAC missing.
- F28: test CIK with both sources, CIK with only fund_financials, CIK with only holdings.

### Regression

- Add regression tests for any filer-specific correction before promoting it into production behavior.
- For implementation changes, run targeted pytest files first, then run the relevant rebuild/export command before treating generated frontend data as production.

## Assumptions

- `fund_financials.csv` is the primary validation target. The frontend is one consumer; other downstream artifacts (index returns, fund exposure) also depend on correctness.
- `private_markets_holdings.csv` provides the cross-level reference. Current unified holdings validation artifacts are a prerequisite -- cross-level checks are only meaningful if holdings data has no unresolved strong-evidence issues for the same CIK-period.
- The investigative phase (Phase 1) uses agent playbooks with the same workflow as unified holdings: flag anomalies, investigate source facts, document findings, codify into deterministic checks.
- The steady-state phase (Phase 3) runs checks deterministically as part of the pipeline. Agent playbooks are only invoked for new failure patterns.
- Cached filings are the default data source. No new SEC or third-party downloads are required for validation.
- Some metrics will remain `validated_with_warnings` or `under_review` because source filings may be incomplete, ambiguous, or inconsistent. That should be surfaced via quality tiers rather than forced into a `verified` state.
- The 33-column scope covers the current planned frontend-relevant subset from `fund_financials.csv`. If `export_frontend.py` adds or removes fund-level fields, this scope must be reconciled against the actual export and each field assigned to a validation surface and tier.
