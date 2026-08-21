<!-- Canonical investigations file (cutover 2026-08-20). Append new entries with a
     dated '## ' heading, the question asked, and the results found; then rebuild
     the index: python scripts/split_investigations.py --reindex -->
# Data-quality audits & triage

## Fund financials schema flags audit - 2026-05-17

Question: find the root cause of the `fund_financials.csv` schema enforcement flags after adding BDC reported total-return extraction.

Sources: `data/output/fund_financials.csv`, `data/output/bdc_fund_income.csv`, cached BDC XBRL files under `data/raw/filings/bdc_xbrl/`, `pipeline/fund_financials.py`, and regenerated frontend fund-detail JSON.

Commands/queries: ran `python scripts/rebuild_outputs.py --financials`, queried the exact `_enforce_schema()` predicates, traced flagged BDC `InvestmentCompanyTotalReturn` rows back to selected XBRL facts and contexts, regenerated frontend JSON with `python scripts/rebuild_outputs.py --frontend`, and ran `pytest tests/test_fund_financials.py --basetemp .pytest_tmp\fund_financials_audit_full`.

### Root Causes

The original `quarterly_return_range` count was 17 rows. The main root cause was a scale bug in the new BDC XBRL return extractor: some filers report `InvestmentCompanyTotalReturn` in decimal form, such as `0.019` for 1.9%, while other filers report percentage-point values, such as `1.3` for 1.3%. The extractor was multiplying every selected raw fact by 100, so percent-style facts became 100x too large. I fixed this by normalizing raw values with absolute value greater than 1.0 as percentage-point facts before YTD-to-quarter conversion.

After that fix, `quarterly_return_range` dropped from 17 rows to 9 rows. The remaining 9 rows are concentrated in 3 CIKs:

| CIK | Fund | Rows | Mechanism |
|---|---|---:|---|
| `0001495584` | Firsthand Technology Value Fund | 6 | Near-zero NAV/share and severe reported losses/recovery create extreme but source-linked shareholder returns. |
| `0001849089` | Lafayette Square Empire BDC | 2 | Near-zero/negative net assets and unusual reported total-return facts produce non-chart-grade returns. |
| `0001916099` | Diameter Credit Co | 1 | Source fact reports a -56.4% standalone return, outside the schema range. |

The `nav_per_share_range` flag is 11 rows across 7 CIKs. Root causes:

| Mechanism | Rows |
|---|---:|
| Negative net assets used in direct or derived NAV/share | 7 |
| Net assets divided by very small share counts, usually formation-stage/minimal-share rows | 4 |

The `bdc_has_balance_sheet` flag is 673 rows across 162 CIKs. This is mostly not a new return-extraction issue. It comes from the companyfacts/income union emitting BDC rows where non-balance-sheet facts exist but both `total_assets` and `net_assets` are missing. In the top contributing CIKs, many rows have BDC income rows, NAV/share or shares outstanding, or performance facts, but no balance-sheet anchor for that quarter. This is especially common in older and pre-XBRL-ish companyfacts coverage, stale/partial companyfacts concepts, and income-only quarters. There are also some entirely blank metric rows created by sparse companyfacts histories.

### Audit Artifacts

Generated CSV artifacts:

- `data/output/fund_financials_schema_nav_flags_audit.csv`
- `data/output/fund_financials_schema_quarterly_return_flags_audit.csv`
- `data/output/fund_financials_schema_missing_bs_audit.csv`

These contain the flagged CIK-quarter rows, selected source fact metadata where available, and root-cause labels.

### Actions Taken

- Fixed BDC total-return scale normalization in `pipeline/fund_financials.py`.
- Added a regression test for percent-point total-return facts.
- Rebuilt `data/output/fund_financials.csv`.
- Rebuilt frontend JSON exports.
- Confirmed BCRED (`0001803498`) 2025 exported quarterly returns remain `1.9%`, `2.3553%`, `1.8217%`, and `1.6949%`, compounding to approximately `8.0%`.

### Residual Risk

The remaining 9 `quarterly_return_range` rows should not be suppressed globally. They are source-linked but not chart-grade without a quality tier or additional validation. Frontend return charts should either exclude out-of-range `quarterly_return` values or surface an `under review` status when such values would affect the visible series.

The 673 `bdc_has_balance_sheet` rows need a separate materiality audit before any production filter is added. A safe next step is to split them into: income-only rows, NAV/performance-only rows, and all-metric-blank rows, then remove or quarantine only rows that have no usable public metric and no balance-sheet anchor. Do not solve this by weakening the schema check; it is correctly pointing at unanchored BDC fund-period rows.

## Validation warning triage - 2026-05-17

Question: triage current business-rule/data-quality warnings from `validation_rules_aggregate.csv` run `06bd4b03cfce` (`2026-05-17T16:41:13Z`).

Sources: `validation_rules_aggregate.csv`, `validation_rules_detail.csv`, `position_returns.csv`, `private_markets_holdings.csv`, `index_returns.csv`, and `combined_universe.csv`.

Commands/queries: grouped warning rules by hit count and affected fair value; inspected top detail rows for promoted index warnings and high-FV validation families; checked representative rows in `position_returns.csv` and `private_markets_holdings.csv`; inspected matching/universe examples by CIK.

Conclusion: hard promoted FAIL gates pass, but several WARN families are not publication-clean. Highest priority is `IDX09`: 1,153 direct-lending rows have quarter-equivalent income return above 20%, and 820 are exactly capped at 25%. Representative rows show normal coupon rates but principal amounts scaled roughly 10x to 1000x too high, which causes the income-return formula to overstate income and hit the cap. Examples: FS KKR Advania (`0001422183`, `POS-00013091`) has FV $91.4mm and principal $933.6mm; Apollo Debt Solutions Delivery Hero (`0001837532`, `POS-00060623`) has FV $149.0mm and principal $194.8bn. This is likely a principal scale/extraction issue, not a real return signal.

Second priority is universe/fund identity and strategy classification. `S07` flags very large funds with sparse position counts; the largest contributor is `0001547580` Victory Portfolios II / VictoryShares International Free Cash Flow ETF, which appears in the universe as `interval_fund` despite being a public ETF series. `S01` flags real-estate funds with low real-estate classification; examples include KKR Real Estate Select Trust (`0001803958`) and Blackstone Private Real Estate Credit & Income Fund (`0002049733`), whose holdings are currently classified mainly as direct lending/private credit even when the fund identity is real-estate credit.

Third priority is duplicate/subtotal leakage and pct-of-net-assets reconciliation. `PC06` identifies duplicate BDC rows, especially Main Street/related CIKs with repeated member-unit rows. `PC07` flags high pct-of-net-assets sums for BDC CIK-quarters, including Blue Owl (`0001655888`), Franklin BSP Capital (`0001825248`), Stellus (`0001551901`), and Star Mountain (`0001786835`). Some of this can be legitimate leverage/net-assets denominator behavior, but the rule evidence explicitly includes suspected duplicate dimensions/subtotal leakage and should be reconciled before being downgraded.

Lower-priority warnings are high-volume matching and temporal stability rules (`M03`, `M09`, `T03`, `T06`). They dominate hit counts and fair-value impact, but many are broad monitoring rules: new positions and disappearances can be real originations/exits, while duplicate entity IDs can reflect borrower-level entity resolution across multiple tranches. They should be calibrated after the principal-scale, universe, and duplicate-row issues are addressed.

Residual uncertainty: this was artifact triage, not a source-filing reconciliation pass. The top examples are strong enough to justify targeted fixes/tests, but each proposed correction still needs source-backed confirmation and false-positive checks before changing global rules.

## Non-accrual reconciliation - 2025q4

Question: validate the BDC direct-lending non-accrual FV used in `credit_risk.json` for `2025q4`.

Sources: `private_markets_holdings.csv`, `nonaccrual_flags.csv`, `fund_financials.csv`, `bdc_filings_index.csv`, and cached XBRL files.

Conclusion: chart status `VALIDATED`. Flagged FV $3,953,163,914 / total FV $489,871,771,853 = 0.8070%. Reconciled FV $3,953,163,914 (100.0%). Reason: thresholds met.

Artifacts: `C:/Users/alger/Documents/000. Projects/005. evergreen funds platform xbrl/data/output/nonaccrual_reconciliation_2025q4.csv` and `C:/Users/alger/Documents/000. Projects/005. evergreen funds platform xbrl/data/output/nonaccrual_position_evidence_2025q4.csv`.

Residual uncertainty: aggregate non-accrual totals are only accepted when parseable from structured XBRL concepts; otherwise direct position-level evidence is used and unresolved cases remain under review.

---

## Data quality root-cause audit - 2026-05-18

Question: root-cause the current headline validation/audit themes at mechanism level, using cached artifacts only, without applying code, schema, API, or frontend changes.

Sources: `holdings_gav_reconciliation.csv`, `fund_financials.csv`, `fund_financials_validation_current.csv`, `fund_financials_cross_level.csv`, `private_markets_holdings.csv`, `bdc_holdings.csv`, `holdings_pct_sum.csv`, `row_validation_issues.csv`, `validation_rules_detail.csv`, `position_matches.csv`, `position_returns.csv`, `combined_universe.csv`, `holdings_validation_report.csv`, `holdings_coverage.csv`, `data_quality_metrics.csv`, and `company_gics_cache.csv`.

Queries used: DuckDB grouped reconciliation flags by source/scope, pct-of-net-assets flags by CIK-quarter, validation rule details by rule ID and affected FV, position-return outliers by return magnitude and begin FV, match methods by begin FV, fund-financial validation statuses, cross-level financial checks, universe vehicle types, coverage issues, and GICS cache confidence. `row_validation_issues.csv` is malformed around long unescaped issuer strings, so `AGG01/PCT01/PCT02` counts were read with Python `csv.DictReader`.

### Root-Cause Summary

| Issue theme | Linked rule IDs/artifacts | Affected scale | Confirmed root cause | Evidence samples | Confidence | Recommended fix/disposition |
|---|---|---:|---|---|---|---|
| BDC GAV/source reconciliation over-coverage | `holdings_gav_reconciliation.csv`, `PC07`, `F20/F21/F22` | BDC: 182 GAV over-coverage rows with $471.3B holdings FV, plus 560 source-reconciliation over-coverage rows with $1.11T holdings FV | Mixed. Confirmed denominator mismatch and subsidiary/consolidation effects for many large BDCs; duplicate dimension/subtotal leakage remains live for high-ratio clusters | FS KKR CIK `0001422183`: 14 over-coverage quarters, $245.1B holdings vs $200.5B comparison, summed ratio 1.22. Franklin BSP CIK `0001825248`: 8 quarters, $44.5B vs $31.0B, ratio 1.44. PennantPark CIK `0001383414`: $34.1B vs $14.5B, ratio 2.35. Ares CIK `0001287750` has GAV ratio near 1.00 but source-reconciliation ratio around 1.20, indicating the source-row reconciliation metric can see a broader/different XBRL path than the fund-level denominator. | Medium | Do not suppress. Split the BDC reconciliation into fund financial GAV, source schedule FV, indexable FV, and subsidiary-inclusive FV. For high-ratio CIKs, reconcile top XBRL dimension paths before treating leverage as sufficient explanation. |
| BDC GAV under-coverage and missing extraction | `holdings_gav_reconciliation.csv`, prior "BDCs with Holdings but Missing from Unified" finding | BDC: 16 under-coverage rows; Newtek alone has 9 quarters with only $0.51B holdings against $17.70B comparison | Confirmed extraction/normalization defect for several CIKs; confirmed aggregate-filter false positives from prior investigation for newer private BDCs | NewtekOne CIK `0001587987` 2025-12-31: $47.7M holdings vs $2.745B comparison, ratio 0.017, evidence `source_fv_missing_or_under_extracted`. Prior investigation found 17 of 20 BDCs fully removed by aggregate filters and about $8.4B missing FV in 2025-12-31 because long position identifiers contain `non-control`/`non-affiliate` hierarchy text. TriplePoint CIK `0001580345` 2022 rows show `source_fv_present_not_indexable`, meaning source FV exists but does not currently map to indexable rows. | High for mechanism, medium for full magnitude | Fix aggregate/header detection with position-aware guards and add CIK-quarter reconciliation tests. Keep under-covered CIK-quarters out of verified frontend tiers until holdings FV reconciles to source/fund anchors. |
| N-PORT GAV under-coverage and universe contamination | `holdings_gav_reconciliation.csv`, `combined_universe.csv`, `S07` | 1,714 N-PORT under-coverage rows; $135.8B holdings vs $7.65T comparison | Confirmed denominator/universe mismatch, not just incomplete private extraction. Many N-PORT funds are broad public credit, municipal, ETF, or mixed registered funds where total assets are not a private-markets denominator | Victory Portfolios II CIK `0001547580`: 501 under-coverage rows, $0.66B holdings vs $6.656T comparison, and latest periods have only 25-47 holdings rows with near-zero FV despite $12B-$22B comparison values. Other large examples: PIMCO Flexible Credit Income Fund CIK `0001688554`, $83.7B holdings vs $426.5B comparison; PIMCO Flexible Municipal Income Fund CIK `0001723701`, $4.4B vs $131.3B. | High | Tighten universe eligibility and denominator semantics before using N-PORT GAV warnings as data-quality failures. Public ETF/municipal/broad credit vehicles should be excluded from index-facing private-market coverage metrics or assigned a non-indexable tier. |
| Pct-of-net-assets inflation and aggregate leaks | `holdings_pct_sum.csv`, `row_validation_issues.csv` `AGG01/PCT01/PCT02`, `validation_rules_detail.csv` `PC06/PC07`, `bdc_holdings.csv` | `AGG01`: 61,310 row warnings. `PCT01`: 277 high-pct CIK-quarters with $1.015T FV. `PCT02`: 71 low-pct CIK-quarters with $15.8B FV. `PC07`: 40 findings, $108.4B affected FV | Confirmed mix of real leverage/net-assets denominator behavior, subtotal/header leakage, and duplicate XBRL dimensions. Star Mountain samples are visible category/subtotal rows; Franklin/Blue Owl need reconciliation because high sums may include leverage and multi-entity effects | Star Mountain CIK `0001786835` 2025-12-31 pct sum 346.1%; top rows include category labels such as "Construction & Engineering First Lien Senior Secured Term Loan Non-Affiliate Investments" at 19.8% and "Preferred Equity Securities Controlled Investments" at 14.9%, which are not borrower-level positions. Saratoga CIK `0001377936` 2024-11-30 pct sum 484.5%. Franklin BSP CIK `0001825248` has repeated 2024-2025 pct sums around 258%-312%, flagged with evidence "Known multi-entity BDC residual pending fund financials population." | High for Star/category leakage; medium for Franklin/Blue Owl denominator share | Add a false-positive-safe aggregate classifier using identifier length, source dimensions, and presence of borrower/security terms. Add per-CIK audited corrections where a filer reports category subtotals as investment identifiers. Keep pct sums as warnings unless independently reconciled to net assets/GAV. |
| Position matching and return anomalies | `position_matches.csv`, `position_returns.csv`, `validation_rules_detail.csv` `M03/M09/T03/T06/IDX01/IDX03/IDX04/IDX06/IDX08/IDX09/IDX10/IDX11` | `M03`, `M09`, `T03`, `T06` are capped at 10,000 findings each; affected FV is $1.87T, $0.43T, $0.48T, and $0.79T respectively. 9,928 position-return rows have absolute quarterly return above 50%, $79.3B begin FV | Mixed. Confirmed broad monitoring-rule overbreadth, aggregate/header rows in matches, principal-scale errors, and real turnover/origination. Not all large warnings are data defects | `M03` top sample `POS-00003940` is Ares "Ivy Hill Asset Management, L.P., Member interest" repeated across 13-14 quarters with $1.5B-$1.9B FV; this is a persistent related-party fund position, not 13 separate bad matches. Return outliers include Runway CIK `0001653384` "Non-Control/Non-Affiliate Investments" dropping from $11.15B to $1.07B, an aggregate row leak; Cliffwater 2025q1-2025q2 structured note with $650M begin FV and principal amount `1`, a principal-scale issue; and Blackstone/Apollo rows such as "Other Cash and Cash Equivalents" or sector labels, which are non-position labels entering return math. | Medium | Separate accepted turnover from defects by excluding aggregate/header rows before matching, adding principal-scale sanity checks, and calibrating `M03/T03/T06` to position lifecycle behavior. Do not use current return outlier counts as direct correctness failure rates. |
| Fund financial headline failures | `fund_financials.csv`, `fund_financials_validation_current.csv`, `fund_financials_cross_level.csv`, prior fund-financial schema audits | `F1` fails all 6,871 rows across 414 CIKs. Direct scan found 0 actual `inf` rows and 0 actual `NaN` rows in key exported numeric fields. Real warnings: `F28` 2,986 rows, `F26` 1,824, `F21` 1,186, `F22` 1,056, `F20` 336 | Confirmed validator/null-semantics defect for `F1`. Separately confirmed real financial-quality gaps: missing balance-sheet anchors, holdings/financial reconciliation failures, leverage proxy divergence, pct-sum mismatch, and return/rate range flags | `F1` value strings list null/missing fields as "non-finite numeric export value", but DuckDB `isinf/isnan` over total assets, net assets, liabilities, investments at FV, leverage, quarterly return, total return, income yield, and distribution rate found zero actual non-finite values. Prior schema audit found `bdc_has_balance_sheet` affects 673 rows across 162 CIKs because companyfacts/income union emits rows without balance-sheet anchors. Current checks show `F10` 195 hard failures, `F31` 10 quarterly-return range warnings, and `F18` 15 BDC asset-coverage warnings. | High for `F1` defect; medium for individual financial warnings | Fix `F1` to distinguish null from non-finite and add a regression test. Treat missing balance-sheet anchors as coverage tier issues. Keep return/rate outliers under review until reconciled to filing financial highlights or source concepts. |
| Universe, strategy, and classification mismatch | `combined_universe.csv`, `holdings_validation_report.csv`, `validation_rules_detail.csv` `S01/S02/S03/S06/S07`, GICS artifacts | `S06`: 562 findings, $436.0B affected FV. `S07`: 52 findings, $435.9B. `S01`: 142 findings, $49.4B. `S03`: 11 findings, $15.0B. `S02`: 13 findings, $7.0B | Confirmed wrong or too-broad vehicle metadata and taxonomy gaps. Some "unusual" mixes are genuine fund mandates, but public ETF/registered-fund contamination and real-estate credit classification gaps are material | `S07` top contributor is Victory Portfolios II CIK `0001547580`, a large fund with fewer than 50 extracted positions and very low indexable FV, consistent with wrong universe inclusion for a public ETF/registered-fund series. `S06` top contributor Cliffwater CIK `0001735964` has 70%+ DIRECT_LENDING despite interval-fund status; this appears to be expected mandate behavior, not automatically wrong. `S01` examples from prior triage include KKR Real Estate Select Trust CIK `0001803958` and Blackstone Private Real Estate Credit & Income Fund CIK `0002049733`, where real-estate credit is classified as direct lending/private credit because holdings-level rules do not see fund strategy. | High | Add fund-level strategy metadata/overrides grounded in source evidence. Split "registered fund with direct lending mandate" from "public ETF/broad fund contamination". Add real-estate credit taxonomy rules at fund-strategy level, not only holdings keywords. |
| Coverage and enrichment gaps | `holdings_coverage.csv`, `data_quality_metrics.csv`, `company_gics_cache.csv`, `validation_rules_detail.csv` `F01-F08` | Coverage: 186 BDCs, 76 interval funds, and 19 tender-offer funds have no holdings; 19 funds are single-period. `F01-F08`: 717 findings. GICS cache has 155,726 rows, but `private_markets_holdings.csv` currently has 0 populated `gics_sub_industry` rows | Confirmed pipeline/export enrichment gap for GICS, plus stale/no-holdings universe entries and new single-period funds. No-holdings is not always a defect because withdrawn/legacy CIKs and newly discovered funds are present in the universe | Single-period high-FV examples include TCW Steel City Perpetual Levered Fund CIK `0002043133` ($0.34B), Nuveen Churchill Private Credit Fund CIK `0002022625` ($0.29B), Golub Capital Private Income Fund I/S CIKs `0002082559`/`0002082557` ($0.26B/$0.18B duplicated names), and AG Twin Brook BDC CIK `0001666384` ($0.18B). GICS cache confidence is broad, including 41,625 high-confidence LLM rows and 17,123 high-confidence extracted-industry rows, but the unified holdings export does not populate `gics_sub_industry`. | High | Add coverage status tiers: no source, stale, single-period, under review, verified. Reconnect GICS enrichment into unified holdings or stop implying GICS coverage. Deduplicate universe identities where the same CIK appears with multiple names. |

### Material Conclusions

1. The largest immediate data defect is not a frontend issue. It is upstream holdings construction: aggregate/header rows and XBRL dimension-path behavior can both remove valid positions and leak subtotals into position-level outputs. This directly affects GAV reconciliation, pct-of-net-assets sums, and return calculations.

2. `F1` should not be treated as evidence that all fund financial rows are numerically corrupt. It is a validator/null-semantics defect in the current artifact. The real fund-financial risks are missing balance-sheet anchors and cross-level reconciliation failures.

3. N-PORT GAV under-coverage is dominated by universe and denominator semantics. Comparing indexable private holdings to total assets for broad registered funds, municipal funds, public ETFs, or mixed funds creates huge "under-coverage" metrics that are not mechanically comparable to BDC schedule reconciliation.

4. The matching and temporal rules are useful as monitoring screens but are overbroad as correctness claims. Large persistent positions, real origination/exit activity, cash/sector labels, aggregate rows, and principal-scale errors are all present in the same warning families.

5. GICS enrichment is currently disconnected from public unified holdings. The cache exists, but `private_markets_holdings.csv` has zero populated `gics_sub_industry` values, so any frontend or audit claim depending on GICS coverage should be marked unavailable or under review until the export path is fixed.

### Residual Uncertainty

- This audit used cached pipeline artifacts, not direct source-filing proof for each row. The mechanisms are visible in artifacts, but per-CIK fixes still require CIK-quarter reconciliation against source XBRL facts or filings.
- Some high pct-of-net-assets sums may be legitimate leverage/net-assets denominator behavior. They should remain warnings until reconciled, not automatically removed.
- Some no-holdings CIKs are legitimate withdrawn, legacy, or newly discovered vehicles. Coverage status needs universe-level lifecycle evidence before these become extraction failures.
- `M03/M09/T03/T06` counts are capped in `validation_rules_detail.csv`; their affected FV is useful for prioritization but not a complete population estimate.

## Universe gating residuals - 2026-05-18

Question: handle N-PORT/holdings CIKs present in cached holdings but absent from `combined_universe.csv` without silently adding them to the index universe.

Sources: cached `private_markets_holdings.csv`, `nport_holdings.csv`, and `combined_universe.csv`; no EDGAR or third-party calls.

Conclusion: non-universe holdings should be excluded from index-facing unified outputs and written to `universe_orphan_holdings.csv` for review. CIKs `0002040315` and `0002040318` are excluded pending universe verification rather than automatically promoted into the public universe. This is a data-quality control, not evidence that the filings are invalid.

Residual uncertainty: the orphan report proves universe absence, not business ineligibility. Each orphan CIK still needs source-backed universe classification before it is either added to `combined_universe.csv` or permanently excluded.

---

## 2026-06-15 - bdc_fund_highlights balance-sheet fields broadly unreliable

Question: how reliable are the balance-sheet fields in bdc_fund_highlights.csv
(total_assets, total_liabilities, stockholders_equity, assets_net), and why?

Trigger: while testing total_assets as a loose conservation anchor for the
shadow disposition ledger, total_assets was implausible for ~90% of CIK-quarters
(e.g. Sixth Street 0001508655 2023-12-31 showed $7.6M for a $3.28B fund;
assets_net showed -$1.5B).

Method: computed coverage, sign plausibility, and independent-identity
reconciliation over all 11,163 highlights rows.

Results (within 5% for identities):
- Coverage (non-null): total_assets 48.0%, total_liabilities 44.9%,
  stockholders_equity 36.0%, assets_net 14.8%, nav_per_share 46.4%,
  shares_outstanding 35.4%.
- Sign plausibility (BDCs cannot be negative): total_assets >0 only 77.1%,
  stockholders_equity >0 80.3%, total_liabilities >=0 78.3%, assets_net >0 92.7%.
  ~1 in 5 of the substring-bound fields is provably garbage on sign alone.
- Independent reconciliation:
  - NAV identity (assets_net ~ nav_per_share * shares_outstanding): 84.4% pass.
  - Balance-sheet identity (total_assets - total_liabilities ~ equity): 4.3% pass
    (136/3,167) -- the three fields are not mutually consistent.
  - assets_net ~ stockholders_equity: 64.6% pass.

Root cause: pipeline/bdc_fund_highlights.py HIGHLIGHTS_CONCEPT_MAP binds these
fields with BARE SUBSTRING keys -- ("assets","total_assets") line 130,
("liabilities","total_liabilities") line 131, ("stockholdersequity",
"stockholders_equity") line 132, ("assetsnet","assets_net") line 55. "assets"
matches narrower elements (OtherAssets, RestrictedAssets, net-assets flow
concepts), so the catch-all binds the wrong fact. Reliability tracks concept-key
SPECIFICITY: nav_per_share / shares_outstanding use specific concept keys and
are reliable; assets_net (semi-specific) is 84% NAV-consistent; the three
balance-sheet totals (bare substrings) reconcile to the accounting identity only
4.3% of the time.

Known + contained, not missed: bdc_fund_highlights_oracle.py:16-17 documents
that "the 'assets' concept in XBRL often matches narrower elements" and demotes
the balance-sheet-identity check to Group 2 (REVIEW, non-blocking). Downstream
analytics_exports.py guards consumption with sanity filters (dl_fv/total_assets
in 0.7-1.3, total_assets > $1M), so bad rows are silently excluded from the
leverage/size analytics rather than corrected -- no blocking failure, no visible
frontend symptom. New consumers that do not replicate those guards (e.g. the
shadow ledger loose anchor) get garbage.

Recommended fix: replace the bare substring keys for total_assets,
total_liabilities, stockholders_equity (and verify assets_net) with EXACT
concept matching (us-gaap:Assets, us-gaap:Liabilities, us-gaap:StockholdersEquity
or NetAssetValue), then re-measure the balance-sheet identity and promote it from
REVIEW to a blocking gate where the concepts are unambiguous. Surface the count
of funds dropped by the downstream sanity filters rather than dropping silently.

Blast radius (verified 2026-06-15): the broken bdc_fund_highlights balance-sheet
fields are NOT consumed by any production export, the frontend, or any
holdings-validation gate. The only reader of bdc_fund_highlights.csv is
bdc_fund_highlights_oracle.py (review-only Group-2 checks). Production and
validation instead use a SEPARATE extraction: extract_companyfacts.py ->
fund_financials.csv (companyfacts API, exact-concept-keyed). That path feeds the
frontend leverage/AUM analytics (analytics_exports.py reads FUND_FINANCIALS_CSV)
and the GAV reconciliation gate (bdc_cik_validator.py: investments_at_fair_value
= STRONG, total_assets_companyfacts = MODERATE). So the broken highlights fields
are effectively a standalone diagnostic. NOT YET VERIFIED: the reliability of the
companyfacts/fund_financials balance-sheet fields themselves (architecturally
sounder but unmeasured). Systemic risk: two extractions emit identically-named
balance-sheet fields with different reliability -- a lineage/single-source-of-
truth hazard.

Comparison measurement (2026-06-15): the companyfacts/fund_financials.csv
balance-sheet fields ARE reliable, confirming fund_financials as the single
source of truth. Over 6,281 rows: BS identity (total_assets - total_liabilities
~ net_assets) holds 98.8% (vs 4.3% for highlights); total_assets >0 100.0%;
net_assets >0 98.2%; investments_at_fair_value <= total_assets 99.8%. Coverage:
total_assets 77.9%, net_assets 85.1%, total_liabilities 78.0%,
investments_at_fair_value 32.7% (the STRONG GAV anchor is sparse). Decision:
remove the broken balance-sheet FIELDS (total_assets/total_liabilities/
stockholders_equity) from bdc_fund_highlights -- not the artifact, which is the
only source of reliable per-share financial-highlights data -- and use
fund_financials for the balance sheet. Schema change to a production artifact;
requires tests + rebuild + semantic diff.

