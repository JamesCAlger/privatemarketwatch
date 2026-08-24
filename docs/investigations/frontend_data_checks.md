<!-- Canonical investigations file (cutover 2026-08-20). Append new entries with a
     dated '## ' heading, the question asked, and the results found; then rebuild
     the index: python scripts/split_investigations.py --reindex -->
# Frontend / public data checks

## 2026-05-17: BDC Credit Stress Chart Validation

### Question

Validate whether the frontend credit stress chart data is mechanically coherent after changing it to BDC-only direct-lending signals:

- `deepDistress`: FV / principal < 80%, with principal sanity bounds.
- `nonAccrual`: matched BDC non-accrual flags.
- `markedBelowCost`: FV / cost < 90%, with cost sanity bounds.
- PIK terms are excluded from stress.
- The frontend renders the three independent signals as a cumulative stacked chart.

### Data Sources

- `frontend/public/data/credit_risk.json`
- `data/output/private_markets_holdings.csv`
- `data/output/fund_financials.csv`
- `data/output/nonaccrual_flags.csv`

### Commands / Queries Used

Used DuckDB against cached local CSVs to reproduce the export logic:

- Filtered holdings to `source = 'bdc'`, `index_classification = 'DIRECT_LENDING'`, positive FV, report dates from 2022-10-01 onward, and excluded configured consumer-lending CIKs.
- Rebuilt the existing GAV filter using `fund_financials.csv`.
- Joined non-accrual flags on `(cik, report_date, bdc_investment_identifier)`.
- Recomputed per-quarter signal counts/FV, unique any-signal rows/FV, and overlapping-signal rows/FV.

### Key Results

Latest generated chart row (`2025q4`) exactly reproduced from source CSVs:

| Metric | Count % | FV % |
|---|---:|---:|
| Deep distress | 6.48% | 2.84% |
| Non-accrual | 3.54% | 2.46% |
| Marked below cost | 5.88% | 4.34% |
| Cumulative stacked height | 15.90% | 9.64% |
| Unique any-signal exposure | 11.17% | 7.25% |
| Multi-signal overlap | 3.66% | 1.99% |

The cumulative stacked chart is therefore mechanically correct as signal incidence, but it is not the percentage of unique stressed positions. Positions with multiple signals contribute to multiple segments.

GAV filter coverage for `2025q4`:

| Scope | Positions | FV |
|---|---:|---:|
| BDC direct lending before GAV filter | 38,687 | $507.0B |
| Kept after GAV filter | 36,601 | $489.9B |
| Kept share | 94.61% | 96.62% |

N-PORT direct-lending rows are excluded from the chart denominator. For `2025q4`, excluded N-PORT direct lending was 15,920 rows and $65.9B FV.

Sanity guards in `2025q4`:

| Check | Raw ratio candidates | Guarded signal rows | Rejected by sanity bounds |
|---|---:|---:|---:|
| FV / principal < 80% | 2,780 | 2,373 | 407 |
| FV / cost < 90% | 2,304 | 2,152 | 152 |

PIK exclusion check for `2025q4`:

- Rows with BDC `pik_rate > 0`: 3,537.
- PIK-term-only rows with no traditional stress signal: 2,588.
- These are not counted in the chart, consistent with the decision that BDC PIK rate reflects terms, not active PIK usage.

Non-accrual matching in `2025q4`:

- Matched rows: 1,294.
- Matched CIKs: 79.
- Matched FV: $12.0B.

### Conclusion

The chart data makes sense mechanically and is internally consistent with the export logic. The main caveat is interpretation: because the frontend now renders independent, non-exclusive signals as a cumulative stack, the bar height should be read as cumulative credit stress signal incidence, not unique stressed exposure.

For `2025q4`, the unique any-signal exposure is materially lower than the stacked height: 11.17% by count and 7.25% by FV versus stacked 15.90% by count and 9.64% by FV. The subtitle and tooltip should continue to use "cumulative signals" wording to avoid overstating unique distressed exposure.

### Residual Uncertainty

- Non-accrual accuracy depends on `nonaccrual_flags.csv` matching identifiers exactly. The validation confirms matched rows, not full non-accrual recall against source filings.
- Markdown metrics are price/cost/par proxies. They identify traditional credit stress signals, but they do not prove credit impairment by themselves.
- The GAV filter removes a small but non-trivial amount of BDC direct-lending exposure; this is intentional, but excluded CIK-quarters should remain auditable when explaining coverage.

### External Benchmark Comparison

Current industry research implies the chart's `nonAccrual` line is high and should be treated as unvalidated until reconciled to fund-reported non-accrual disclosures:

- Octus reported Q4 2025 BDC debt non-accruals of $7.12B at cost and $3.77B at fair value, equal to 1.45% of debt investments at cost and 0.77% at fair value across 171 BDCs.
- KBRA reported Q2 2025 non-accruals for non-perpetual-life BDCs at 2.3% of total investments at cost and 1.0% at fair value.
- Houlihan Lokey / Advantage Data reported Q2 2025 BDC loan non-accruals at 1.2% of total portfolio cost, and describes distress as low/moderate.

Our chart reports non-accrual at 2.46% of FV in Q4 2025, roughly 3x Octus' 0.77% FV benchmark. The total matched non-accrual FV is $12.0B, compared with Octus' reported $3.77B. Many of our largest matched non-accrual rows are marked near cost/par; in Q4 2025, $8.17B of matched non-accrual FV has FV/cost >= 95%. This is a strong sign that `nonaccrual_flags.csv` may be over-inclusive or that footnote-derived flags are matching broader note disclosures rather than only true non-accrual positions.

The markdown series are more directionally comparable with industry mark-based stress screens:

- Houlihan Lokey / Advantage Data's Q2 2025 par buckets show a low single-digit share of BDC loan exposure below 80% of par, excluding outliers and using performing-loan pricing.
- Our `deepDistress` for Q2 2025 is 2.24% by FV and 6.32% by row count. The FV measure is broadly plausible against that benchmark; the row-count measure is not directly comparable to cost/FV-weighted industry reporting.

Recommended follow-up: before publishing the non-accrual line as a benchmark-quality metric, reconcile `nonaccrual_flags.csv` against issuer-level disclosed non-accrual cost/FV totals for a sample of large contributors, especially Prospect Capital, AGL Private Credit Income Fund, HPS Corporate Lending Fund, Blackstone Private Credit Fund, and FS KKR Capital Corp.

## Blackstone Private Credit Fund return chart drop - 2026-05-17

Question: explain why the fund page "Total Return" chart for Blackstone Private Credit Fund (`CIK 0001803498`) falls after 2024q2.

Sources: `frontend/public/data/fund_details/0001803498.json`, `data/output/fund_financials.csv`, `frontend/src/app/funds/[cik]/page.tsx`, `frontend/src/components/FundPerformanceTable.tsx`, and `pipeline/fund_financials.py`.

Commands/queries: inspected fund detail JSON series; queried `fund_financials.csv` for NAV/share, distribution, and return fields; reviewed frontend chart selection logic and BDC return fallback logic.

Conclusion: the visible line is not a total-return series. For BDCs, `pickLineChart()` selects NAV/share when available, then the page rebases the first NAV/share point to 100. BCRED NAV/share rises from `24.5889` at 2022q4 to `25.5717` at 2024q2, then falls to `24.7945` at 2025q4. Rebased to 2022q4, that is approximately `104.00` at 2024q2 and `100.84` at 2025q4, matching the chart drop.

The available BDC `total_return_pct` field is not a reliable substitute for this line as currently computed. For BCRED, distributions per share are null, and `_fill_computed_returns()` can use a Tier 1 formula based on `nav_per_share * shares_outstanding`, which is sensitive to share issuance/capital raises. That produces high returns in quarters with large share growth and lower returns when share growth slows, so it is not a clean per-share total return proxy.

Residual uncertainty: source filings may contain usable per-share distributions or share-class total return facts outside the current companyfacts extraction path. Until reconciled to filing financial highlights or per-share distributions, the frontend should label the current BDC line as NAV/share, not total return, and should avoid presenting computed `total_return_pct` as benchmark-quality BDC total return.

## 2026-05-24 - Frontend Fund and Position Data Source Spot Check

Question: Can the fund-level and position-level numbers shown in the frontend be justified by their source, where source means cached XBRL/companyfacts tags, N-PORT fields, deterministic pipeline inference, or LLM/GICS enrichment?

Scope:
- Checked generated frontend JSON in `frontend/public/data/`.
- Traced representative values back to `data/output/fund_financials.csv`, `private_markets_holdings.csv`, `position_returns.csv`, `holdings_gav_reconciliation.csv`, `source_reconciliation_detail.csv`, `nport_fund_info.csv`, and cached `data/raw/companyfacts_cache/0001803498.json`.
- No SEC or third-party network calls were made.

Findings:
- Frontend aggregate fund summary values recompute exactly from `fund_financials.csv` using the export logic: 385 funds, 208 BDCs, 150 interval funds, 27 tender-offer funds, and total AUM of 830,556,080,736.
- Blackstone Private Credit Fund (`0001803498`) fund-level fields shown in the frontend trace to companyfacts/XBRL-derived `fund_financials.csv`; cached companyfacts contains the 2025-12-31 `us-gaap:Assets` value of 85,992,162,000 from accession `0001803498-26-000014`, matching the frontend total assets value. The latest GAV reconciliation is `PASS` with STRONG comparison source `investments_at_fair_value`, but holdings FV / investments-at-FV is 1.0813, so the pass is within tolerance rather than exact.
- Blackstone position-level frontend values recompute from `private_markets_holdings.csv`: latest holdings total FV is 88,882,467,000 across 2,003 positions; top holding `BCRED Emerald JV LP` has FV 1,678,745,000 and portfolio share 0.0189. However, current `source_reconciliation_detail.csv` contains no rows for CIK `0001803498`, so individual Blackstone position values are not independently evidenced by the current reconciliation artifact even though they are sourced from BDC XBRL-derived holdings.
- Cliffwater Corporate Lending Fund (`0001735964`) fund-level and top-position values trace to N-PORT artifacts. The latest `nport_fund_info.csv` row for accession `0001735964-26-000003` has total assets 56,338,645,518.19, net assets 31,530,117,620.63, monthly returns .56/.85/.68, and borrowings after one year 10,045,088,713.78, matching the frontend fund detail fields after export rounding. Its top holding, `SILVER POINT LOAN NOTE ISSUER LLC /`, has FV 1,436,727,263.42 in `private_markets_holdings.csv`, matching the frontend 1,436,727,263 rounded value.
- FSK (`0001422183`) top direct-lending frontend constituent `Credit Opportunities Partners JV, LLC` has a matched source-reconciliation row for 2025-12-31 showing source FV 1,967,900,000 equals output FV 1,967,900,000 and source cost 2,201,900,000 equals output cost 2,201,900,000. But the CIK-quarter GAV reconciliation is `WARN`: holdings FV 19,267,000,000 versus investments-at-fair-value 13,008,600,000, ratio 1.4811. The position value is individually justified, while the fund-quarter aggregate is not fully reconciled.
- The direct-lending index summary shown for 2025q4 traces to `index_returns.csv` and `position_returns.csv` with the configured `INDEX_DISPLAY_END_QUARTER = "2025q4"`. Note that `index_returns.csv` also contains 2026q1 rows, but the frontend intentionally cuts display at 2025q4.
- GICS sector breakdown values are aggregation outputs over reconciled BDC sector rows, holdings fallback rows, N-PORT rows, and `data/reference/gics_hierarchy.json`. The top sector, Industrials, is 142,216,918,506 total FV with source breakdown 77,241,292,980 BDC reconciled, 49,508,824,900 BDC fallback, and 15,466,800,627 N-PORT. The numeric aggregation is reproducible, but the industry/GICS labels are partly LLM or rule-enriched. `company_gics_cache.csv` includes many `llm` high/medium/low records and some malformed normalized company names such as rate/date strings, so GICS sector values should be presented as enrichment-backed estimates, not filing-native facts.

Conclusion:
- The frontend numbers are generally mechanically justified by current pipeline artifacts.
- Fund-level XBRL/companyfacts and N-PORT fields are the strongest: sampled values tie directly to cached source facts or N-PORT source rows.
- Position-level values are mixed: FSK has row-level source reconciliation evidence; Blackstone top holdings do not have current row-level reconciliation artifacts despite GAV passing at the aggregate tolerance level.
- GICS sector values are numerically reproducible but depend materially on programmatic and LLM enrichment. They should not be displayed with the same confidence as directly filed FV, cost, assets, or N-PORT fields.

Residual uncertainty:
- This was a spot check, not a full audit.
- Current validation tier labels are fund-quarter/GAV oriented and can overstate individual position-level evidence when `source_reconciliation_detail.csv` is absent for a CIK.
- GICS cache quality needs a separate false-positive review because malformed entity strings can still receive confident sector labels.

