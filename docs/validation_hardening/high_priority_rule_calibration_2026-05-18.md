# High-Priority Rule Calibration - 2026-05-18

## Scope

This audit calibrates the 12 high-priority unpromoted `WARN` rules: `PC05`, `PC06`, `PC07`, `PC09`, `T04`, `T05`, `M08`, `F02`, `F03`, `F08`, `F09`, and `R14`.

No rule registry entries, severities, generated production CSVs, or frontend JSON files were edited. The audit used cached/local validation artifacts written on 2026-05-18:

- `data/output/validation_rules_aggregate.csv`
- `data/output/validation_rules_detail.csv`
- `data/output/validation_rules_trend.csv`
- `data/output/private_markets_holdings.csv`
- `data/output/combined_universe.csv`

## Summary Recommendation

| Rule | Current status | Hits | Hit rate | Affected FV | Trend | Recommendation | Rationale |
| --- | ---: | ---: | ---: | ---: | --- | --- | --- |
| `PC05` | `PASS` | 0 | 0.0000 | 0 | `STABLE` | `keep_report_only` | Useful cross-source duplicate sentinel, but no current examples to support promotion. |
| `PC06` | `WARN` | 591 | n/a | 1,125,037,545 | `CHRONIC` | `refine_and_retest` | High-volume mixed BDC and N-PORT duplicate population; examples are reviewable but current grouping mixes true duplicate risk with zero-FV and repeated instrument rows. |
| `PC07` | `WARN` | 40 | 307.4735 | 108,394,000,269 | `CHRONIC` | `refine_and_retest` | Very high FV and clear pct denominator risk, but known multi-entity BDC residuals and weak denominator semantics prevent promotion as-is. |
| `PC09` | `PASS` | 0 | 0.0000 | 0 | `STABLE` | `keep_report_only` | Position ID coverage sentinel passes; no current failure population to calibrate. |
| `T04` | `WARN` | 16 | 0.3896 | 0 | `CHRONIC` | `refine_and_retest` | Catches real classification changes, but mixes true taxonomy fixes, source changes, and possible misclassifications; detail is CIK-quarter level only. |
| `T05` | `WARN` | 1 | 0.0000 | 0 | `CHRONIC` | `future_promotion_candidate` | Single clean rate-population regression: CIK `0001616037` dropped from 86.1% to 0.0% rate fill on direct-lending rows. Needs source spot check before promotion. |
| `M08` | `WARN` | 37 | n/a | 0 | `CHRONIC` | `refine_and_retest` | Current expected-calendar construction creates likely false gaps for non-standard fiscal dates; useful signal but too calendar-sensitive. |
| `F02` | `WARN` | 373 | n/a | 0 | `CHRONIC` | `refine_and_retest` | Freshness is public-facing and source-reviewable, but current rule over-broadly uses global max holding date and includes duplicate universe rows. |
| `F03` | `WARN` | 81 | 0.1014 | 0 | `CHRONIC` | `refine_and_retest` | Coverage-drop denominator compares each fiscal-date bucket to the all-time max CIK count, creating predictable calendar noise. |
| `F08` | `WARN` | 16 | 0.1541 | 0 | `CHRONIC` | `future_promotion_candidate` | Missing `entity_id` is a concrete output defect affecting concentration/entity views; current hits are concentrated in BDC rows and can be promoted after scoping. |
| `F09` | `PASS` | 0 | 0.0000 | 0 | `STABLE` | `keep_report_only` | Position ID coverage currently passes; keep as report-only sentinel. |
| `R14` | `PASS` | 0 | 0.0000 | 0 | `STABLE` | `keep_report_only` | Rate-scale sentinel is high-value if it fires, but there are no current examples to support promotion. |

The focused overlap check found no current overlap between these 12 rules and promoted validation findings at `cik`/`quarter`/`position_id`, `cik`/`quarter`, or `quarter` granularity. That reduces urgency for promotion but does not prove the warnings are harmless.

## Affected Output Surfaces

All 12 target rules list these affected surfaces in the aggregate artifact:

- `private_markets_holdings`
- `frontend_fund_detail`
- `data_quality_dashboard`

The rules that most directly affect public-facing analytics are:

- `PC06` and `PC07`: position duplication and pct-of-net-assets inflation can distort holdings tables, fund detail, concentration, and portfolio composition.
- `T04`: classification shifts can move exposure between frontend private credit, real estate, equity, and fund buckets.
- `T05` and `R14`: rate extraction failures can affect yield/rate displays and direct-lending return interpretation.
- `F02` and `F03`: stale or missing filing coverage can make public freshness and coverage look better than they are if not surfaced.
- `F08` and `F09`: entity and position ID coverage affects investee concentration, position continuity, and matching.

## Per-Rule Findings

### `PC05` - Cross-Source Duplicate Holding Candidate

Recommendation: `keep_report_only`.

`PC05` passed with zero findings. The rule remains useful because a same-CIK/date/issuer/FV row coming from more than one source is a plausible duplicated-exposure mechanism, especially across BDC and N-PORT feeds. With no current examples, there is no evidence base for promotion.

Source reviewability: high if it fires, because rows can be traced to the underlying source and accession fields in holdings.

Residual risk: a pass only means no exact cross-source duplicate key exists under the current normalization. It does not rule out fuzzy duplicates.

### `PC06` - Within-Source Duplicate Holding Candidate

Recommendation: `refine_and_retest`.

Current findings:

- 591 findings.
- Affected FV: 1.125 billion.
- Source split: 416 BDC findings with 1.038 billion affected FV; 175 N-PORT findings with 87.1 million affected FV.
- 337 findings have positive FV; 254 findings have zero FV.
- Top CIK clusters: `0001535778` with 144 findings, `0001143513` with 59, `0001447247` with 54, `0001512931` with 43, and `0001572694` with 42.

Top examples include repeated `ivy battery note` N-PORT rows for CIKs `0002000182` and `0001990685`, and repeated zero-FV BDC rows for `the mountain corporation` under CIK `0001321741`.

The duplicate mechanism is plausible: same CIK/date/source/issuer/instrument/CUSIP/FV rows can indicate repeated dimensions or subtotal leakage. But the current finding population mixes positive-FV duplicates, zero-FV residuals, N-PORT holdings with empty `position_id`, and BDC XBRL dimension behavior. That is too broad for promotion.

Refinement target:

- Split positive-FV and zero-FV duplicate findings.
- Add accession and dimension-path samples to detail rows when available.
- Separate N-PORT duplicate holding IDs from BDC dimension duplicate candidates.
- Retest false positives where repeated issuer/FV rows are legitimate distinct instruments lacking CUSIP.

### `PC07` - CIK-Quarter Pct-Of-Net-Assets Sum High

Recommendation: `refine_and_retest`.

Current findings:

- 40 findings.
- Affected FV: 108.394 billion.
- Top CIK clusters: `0001786835` with 12 findings, `0001551901` with 11, `0001825248` with 8, `0001655888` with 2, and `0001490927` with 2.
- Highest example: CIK `0001377936` at 2024-11-30 with pct sum 484.5%.
- Several `0001786835`, `0001825248`, and `0001551901` findings carry the current evidence hint: known multi-entity BDC residual pending fund financials population.

The rule is important because pct-of-net-assets inflation maps directly to frontend composition and concentration risk. However, the current threshold catches multiple mechanisms: duplicate dimensions, subtotal leakage, multi-entity BDC denominator issues, and possibly legitimate fund structure effects.

Refinement target:

- Reconcile flagged CIK-quarters against fund financials or total assets before escalation.
- Split known multi-entity BDC residuals from unexplained pct sum failures.
- Add a separate high-confidence candidate when pct sum is high and fair value also exceeds independent GAV or total-assets tolerance.

### `PC09` - Multi-Quarter Holdings Missing Position ID

Recommendation: `keep_report_only`.

`PC09` passed with zero findings. This is a useful broad sentinel for position-matching undercoverage in repeat issuer names, but the current run provides no failing examples.

Residual risk: this pass does not prove position matching is complete. It only means the current missing-position-ID share did not exceed the rule threshold for multi-quarter issuer groups.

### `T04` - Classification Shift

Recommendation: `refine_and_retest`.

Current findings:

- 16 CIK-quarter findings.
- Top CIKs: `0001990685` with 3 findings; `0002000182` with 2; several one-off CIKs.
- Example shifts include `DIRECT_LENDING` to `DIRECT_REAL_ESTATE` for real-estate named N-PORT positions, `UNCLASSIFIED` to `PRIVATE_EQUITY_FUND` for fund holdings, and bidirectional BDC shifts between `COMMON_EQUITY`, `PREFERRED_EQUITY`, and `DIRECT_LENDING`.

Representative examples:

- CIK `0001762562`, 2022-09-30: `100 Friars Boulevard`, `Mosaic at Largo Station`, and `55 Messina Drive` shifted from `DIRECT_LENDING` to `DIRECT_REAL_ESTATE`.
- CIK `0001990685`, 2024-06-30: `Oak Institutional Credit Solutions` shifted from `DIRECT_LENDING` to `PRIVATE_CREDIT_FUND`; other positions shifted to `UNCLASSIFIED`.
- CIK `0001876006`, 2023-09-30: fund holdings shifted from `UNCLASSIFIED` to `PRIVATE_EQUITY_FUND`.
- CIK `0001901606`, 2025-12-31: some BDC positions shifted between equity and direct lending classifications.

This is useful triage, but current detail rows are only CIK-quarter aggregates. The rule needs position-level samples in the emitted detail or an attached drilldown artifact before it can be promoted. The examples also show that some shifts are likely corrections rather than defects.

Refinement target:

- Emit top shifted `position_id` examples with prior/current classification.
- Separate benign taxonomy improvements from unstable classification flips.
- Compare against `MONO05` diagnostic output because that candidate is narrower and keyed on stable private-position identity.

### `T05` - Rate Population Regression

Recommendation: `future_promotion_candidate`.

Current finding:

- CIK `0001616037`, 2025-10-31.
- Direct-lending row count: 61.
- Current rate fill: 0.0%.
- Prior quarter: 2025-07-31 with 72 direct-lending rows and 86.1% rate fill.

This is a concrete extraction-completeness failure mechanism. A drop from high rate population to zero rate population is unlikely to be legitimate for a direct-lending fund unless the source format changed materially or all holdings became unrated in one period.

Before promotion:

- Spot check the 2025-10-31 source filing or cached filing parse for CIK `0001616037`.
- Add prior/current fill values to the detail evidence hint.
- Confirm there is no source-level reason rates were legitimately omitted.

If the source spot check confirms omitted extractable rates, this rule is a good promoted `WARN` candidate because it is low-volume, concrete, and reviewable.

### `M08` - Position ID Chain Break

Recommendation: `refine_and_retest`.

Current findings:

- 37 findings.
- Top clusters: CIK `0001732078` with 34 findings at 2024-07-31; CIK `0001678124` with 3 findings at 2019-11-30.
- All reviewed examples were N-PORT positions.

The examples point to a calendar-construction problem. For CIK `0001732078`, many positions are observed at 2024-06-30, 2024-08-30, and 2024-12-31. The rule flags 2024-07-31 because it builds expected quarters from all holding dates globally, not from a filer-specific reporting cadence. That is a weak denominator for N-PORT and fiscal-date filers.

Refinement target:

- Build expected periods per CIK/source cadence, not from all global holding dates.
- Avoid treating every other filer fiscal date as expected for each position.
- Consider requiring a missing CIK-level filing row before flagging position-level chain breaks.

Until then, this should remain report-only.

### `F02` - Stale Filing

Recommendation: `refine_and_retest`.

Current findings:

- 373 findings.
- Most findings cluster at 2025-12-31 as the latest available quarter for active funds, with older examples going back to 2021-05-31.
- The rule uses `global_max=2026-01-31` from holdings and flags any CIK last data older than the third-most-recent global holding date, excluding `withdrawn` and `inactive` statuses.

Representative early examples:

- CIK `0001400897`, last data 2021-05-31, active interval fund.
- CIK `0001336050`, last data 2022-12-31, active interval fund.
- CIK `0001496254`, last data 2023-06-30, active interval fund.
- CIK `0001261166`, last data 2023-07-31, active tender offer fund.

Freshness is publication-critical, but the current rule is too broad for promotion. It uses a global holdings date rather than a vehicle-specific filing expectation, and the detail output showed duplicate universe rows for at least one CIK (`0001725295`).

Refinement target:

- Deduplicate `combined_universe` before joining.
- Use vehicle/source-specific expected cadence and latest filing metadata.
- Distinguish true stale active filers from fund closures, mergers, no-longer-private-market funds, and missing extraction coverage.

### `F03` - Source Coverage Drop

Recommendation: `refine_and_retest`.

Current findings:

- 81 findings.
- The denominator is the all-time maximum distinct CIK count, 284.
- Examples include date buckets with 1 to 33 CIKs, such as 2022-04-29, 2022-07-29, 2024-08-30, 2026-01-30, and many fiscal month-end dates.

This rule is detecting real date-bucket sparsity, but not necessarily source coverage drop. The current denominator compares every distinct fiscal date to the global maximum CIK count. That predictably flags non-standard month-end or fiscal-date buckets even when no coverage defect exists.

Refinement target:

- Normalize to calendar quarter or source-specific expected reporting dates before computing coverage.
- Split BDC and N-PORT source coverage.
- Compare current expected active CIKs to prior comparable periods, not to the all-time max across all dates.

As written, the rule is useful as a broad coverage smell but should not be promoted.

### `F08` - Entity Resolution Coverage

Recommendation: `future_promotion_candidate`.

Current findings:

- 16 quarter-level findings.
- Worst quarters: 2025-09-30 with 21.64% missing `entity_id`, 2025-12-31 with 21.27%, 2025-02-28 with 18.62%, 2025-06-30 with 17.48%, and 2025-03-31 with 17.19%.
- Reviewed source split shows the current missing entity IDs are concentrated in BDC rows. For the top five quarters, N-PORT had zero missing entity IDs, while BDC missing counts ranged from 73 on 2025-02-28 to 16,597 on 2025-12-31.

Missing `entity_id` is a concrete output defect. It directly weakens investee concentration, issuer continuity, and public fund-detail views. The current rule is more promotion-ready than generic anomaly rules because the finding is factual and measurable.

Before promotion:

- Scope the promoted version to the affected source or emit source-level detail rows.
- Add affected FV for missing-entity rows, not just quarter counts.
- Confirm there are no intended entity-resolution exclusions that should be separated from defects.

### `F09` - Position ID Coverage

Recommendation: `keep_report_only`.

`F09` passed with zero findings. It should stay as a report-only sentinel for broad position matching undercoverage. There is no failing evidence population to justify promotion in this batch.

Residual risk: a pass does not rule out localized chain breaks or mislinked positions. It only means no multi-quarter CIK exceeded the missing-position-ID threshold.

### `R14` - Interest Rate Exceeds 50%

Recommendation: `keep_report_only`.

`R14` passed with zero findings. The rule is a high-value rate-scale sentinel because an interest rate above 50% on positive-FV direct-lending holdings is likely a bps-versus-percent parse error or source data anomaly. With no current examples, it should remain report-only for now.

If it fires in a later run, examples should be independently source-reviewable through `issuer_name`, `position_id`, `source`, `report_date`, and the raw `interest_rate` evidence hint.

## Verification

No validation logic or helper code was changed, so `pytest tests/test_validation_rules.py` was not required.

Verification performed:

- Confirmed all 12 target rules are present in `validation_rules_aggregate.csv`.
- Confirmed detail rows exist for all non-passing target rules: `PC06`, `PC07`, `T04`, `T05`, `M08`, `F02`, `F03`, and `F08`.
- Confirmed clean-pass target rules have no detail rows: `PC05`, `PC09`, `F09`, and `R14`.
- Did not manually edit diagnostic candidate files, production CSVs, or frontend JSON.
