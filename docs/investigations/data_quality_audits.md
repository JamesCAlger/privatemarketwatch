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

## 2026-09-08 - Unified holdings schema and financial-contract crosswalk

QUESTION: map the existing definitions, actual transformations, validation and
downstream interpretations before proposing a replacement schema or architecture.

RESULT: [Full crosswalk](../reference/unified_holdings_contract_crosswalk.md)
accounts for all 88 saved unified-holdings columns, with BDC-only interpretation,
explicit treatment of 14 N-PORT-only columns, and related PIK, rate-grammar,
provenance and fund-level artifacts. Existing schemas/contracts are substantial;
the finding is distributed definitions and specific alignment gaps, not absence
of architecture.

Twelve bounded findings cover rate conventions, cost proxies, FX assumptions,
percentage denominators, enforcement/enums, point-in-time leakage, maturity
precision, negative evidence, normalized identifiers, population basis,
documentation/verification scope and identifier stability. Findings distinguish
directly inspected code behavior from inferred analytical consequences; no
population-level error rate or new quality score is asserted.

Evidence: working-tree code at HEAD 2e0491a45d1493e7a3ee329aee52ec96bb34986c,
saved CSV header, current definitions and relevant test sources. Worktree was
already dirty; unrelated changes were preserved. Header-to-crosswalk check:
88/88 fields, no omissions, extras or duplicates; all relative document links
resolve. No tests, rebuilds, source downloads, fleet dispatches or production
data writes were run. This is a documentation audit, not a semantic migration
or quarter acceptance decision.

## 2026-09-08 - Schema availability and preferred representations

QUESTION: which of the crosswalk's 12 alignment choices are supported by the
cached source and curated BDC data?

RESULT: [Availability audit](../reference/unified_holdings_contract_crosswalk.md#18-availability-audit-and-preferred-representations)
records bounded profiling for Q4-2025 and Q1-2026 under the active 70-CIK
manifest, plus three cached-XML source checks. Q1 includes 30,067 current
holdings across 69 funds; direct-lending principal exists on 90.1% of rows but
USD principal on only 39.7%. A checked U_USD unit resolves to actual USD;
many similar unit tokens currently produce missing-FX status, and the FX
reference file has no rate rows. Currency resolution is a high-value recovery
candidate, not evidence that the source principal is generally undisclosed.

Reported cost exists on 96.1% of matched Q1 source anchors; retain legitimate
zeros and distinguish proxies. Direct-lending maturity coverage is 95.4%, with
substantial existing iXBRL enrichment. Preserve that pathway while adding
precision/unknown semantics. Rates require source-aware cash versus all-in
meaning. Optional floor tags exist, but a checked bond example demonstrates
that the economic interpretation cannot be assumed from the tag alone.

The older strict-current-PIK artifact is all unknown in these two quarters,
despite a small pool of position-level evidence records; attachment and period
eligibility need investigation before attributing this to disclosure absence.
Current saved position_id is entirely blank for both selected quarters; the
matching workflow exists separately. Do not use these current artifacts as
already-joined, synchronized transition inputs.

Coverage is not accuracy. The report separates extraction from original source,
different artifact vintages, verified examples from screening estimates, and
available fields from supported meanings. Corrected the crosswalk's omitted
HTML/iXBRL maturity/reference-rate provenance pathways. No pipeline or data
changes, SEC calls, tests, rebuilds, exports or semantic output diff. Both
bounded scratch diagnostics exited successfully; findings persisted in docs.

## 2026-09-08 - Current unified holdings accuracy versus verification coverage

QUESTION: how well does the pipeline currently get accurate numbers into unified
holdings, separately from the proposed schema-alignment work?

SCOPE: active 70-CIK manifest, BDC source, Q4-2025 and Q1-2026. Existing artifacts
read on 2026-09-08: unified Parquet 16:49 local; reconciliation 17:13; provenance
ledger 17:25; Q1 acceptance generated 16:31:46 UTC (17:31 local). No new
validation battery was run. PowerShell aggregated small summaries; bounded
`scratch/2026-09-08_schema_availability/profile_accuracy.py` read the larger
Parquet ledgers using DuckDB (two threads, 768MB, no spill, 60-second watchdog).
The diagnostic completed successfully; no remaining diagnostic process.

### Numeric fidelity is substantially stronger than the fund-tier percentage

`pipeline/provenance_reverify.py::full_tier` checks an anchored field against the
cached instance, applies declared scale transforms and compares published
values. `classify_reason` only calls a field verified after full `raw_match`
without an overriding correction/derivation/failure classification. This is
stronger than just having a non-null value, but it is not certification of the
chosen context, interpretation, economic valuation or row population. It also
reuses parsing helpers, so this is not a wholly independent manual gold audit.

| Q1 field | Populated | Verified populated | Share of populated |
|---|---:|---:|---:|
| Fair value | 30,067 | 30,026 | 99.86% |
| Original principal | 24,229 | 24,194 | 99.86% |
| Spread | 23,468 | 23,340 | 99.45% |
| Interest rate | 21,213 | 21,022 | 99.10% |
| PIK rate | 2,262 | 2,221 | 98.19% |
| Cost | 29,334 | 27,873 | 95.02% |
| Shares | 3,386 | 3,325 | 98.20% |
| Percent of NAV | 15,490 | 8,514 | 54.96% |

For fair value the ledger's verified dollars are $380,589,786,729 of
$381,537,030,207 (99.75%). Q4: 28,870/28,938 FV rows (99.77%) and
$373,681,983,944/$374,335,565,067 (99.83%). These are verification-coverage
statistics, NOT estimated end-to-end accuracy. Unverified is not synonymous
with wrong: Q1 cost includes 1,425 derived entries; %NAV includes 6,975
corrected entries; interest rate includes 191 text-pathway entries.

### Getting the right rows and totals remains a material weakness

Latest Q1 `data/output/quarter_acceptance.json`, provisional v3, is FAIL (4/9
checks pass). Exact figures:

- 69/70 funds have holdings; 55/68 anchored funds reconcile (80.882%).
- 13 flagged funds hold $98.113bn, 25.715% of published FV. This is the entire
  size of those funds' holdings, NOT an estimate that $98bn is wrong.
- Positive excess over independent anchors across failed funds is $3.370bn,
  0.883% of published FV. This does not measure omissions, offsetting errors
  or every possible duplication, and is not a total error bound.
- 46 funds are tier `verified`, representing 60.254% of FV; 22 under review,
  one unanchored, one without holdings. Code assigns verified when conservation
  passes and the source-reconciliation review queue has no blockers for the
  fund. It does not require every field to have passed numeric verification.
- Queue source-blocker FV is $989.080m across 11 fund packets, 0.259% of FV;
  this is queue exposure, not a universal missing-holdings percentage.
- 15 promoted-rule drift records also fail the gate; zero unhealthy rules and
  zero stale investigations. Drift count is global, not solely Q1.

Source reconciliation gives an additional, differently scoped view. Q1 metrics
contain 30,029 output-associated records: 27,800 matched, 2,223 secondary-field
diagnostics and six output-only records before final residual classification.
The final cohort residual classification retains 97 source-only blockers
(77 terminal-percentage parser mismatches + 20 other position-like mismatches),
with $981.492m source FV, and one $7.3m output-only blocker. These are unresolved
source/output identities, not 97 independently confirmed absent legal positions.
No Q1 matched-FV disagreement remains in this artifact. Q4 retains 75 source-only
blockers ($830.961m) and one FV disagreement ($3.902m versus $3.918m).

Q1's 2,223 secondary diagnostics agree on FV but disagree on cost/principal/
shares: 1,887 cost-only, 247 principal-only, 44 shares-only, 35 cost+principal,
10 cost+shares. They cannot be dismissed because FV matches, nor assumed all
wrong before reviewing correction/proxy/source-context mechanisms. The source
reconciliation and declared-provenance checks have different matching and
normalization paths; their apparently conflicting results are not interchangeable.
Neither reconciliation's evaluated row count nor its pre-calibration missing
count should be substituted for the current unified denominator.

The all-history, broader-universe source-only header has 9,335 blocking rows of
15,338 reviewed. Those are NOT current-quarter unlisted-cohort counts. The
filtered figures above prevent conflating those populations.

### Assessment and limitations

The pipeline has strong measured fidelity for many source-backed numbers,
especially FV. Its weaker parts are complete/nonduplicated population selection,
economic meaning and derived values. A real subtotal can pass fact replay but
still be an invalid position. A cash coupon can exactly match its source while
still being wrongly treated as all-in. Original principal can verify while USD
principal is missing through unit resolution. Source-reported marks are not
independent estimates of economic value.

Do not describe this as either "60% accurate" or "99.9% accurate." There is no
single measured end-to-end field/position correctness rate in these artifacts.
Use source-backed positions for research with field eligibility and reconciliation
context; do not treat the full unified table as an analysis-ready, uniformly
validated dataset. Historical v2 sign-offs do not override the current v3 FAIL.

No pipeline changes, downloads, tests, rebuilds, exports, output semantic diff,
baseline refresh or re-attestation. Only read-only diagnostics and documentation.


## 2026-09-09 - Historical XBRL coverage for programme scope

Question: Which quarter first has broad extended XBRL holdings coverage among the active 70-BDC wrapper cohort?

Cache-only DuckDB audit using data/overrides/wrapper_cohorts/v2_70_gate_verified_wrapper_manifest.json (70 distinct CIKs). Source artifact vintages UTC: bdc_holdings.csv 2026-09-05 07:33:09; private_markets_holdings.csv 2026-09-08 15:49:07; fund_financials.csv 2026-09-08 14:27:43. Diagnostic and quarterly CSV: scratch/2026-09-09_history_coverage/. Queries aggregate distinct CIKs by calendar quarter, with current-period evidence requiring period=report_date. This measures extracted position presence, not completeness, accuracy, or the first regulatory tagging obligation.

| Quarter | XBRL funds including later comparatives | Current-period XBRL funds | Unified funds |
|---|---:|---:|---:|
| 2021 Q4 | 12 | 0 | 0 |
| 2022 Q1 | 3 | 0 | 0 |
| 2022 Q2 | 2 | 0 | 0 |
| 2022 Q3 | 9 | 3 | 3 |
| 2022 Q4 | 46 | 3 | 3 |
| 2023 Q1 | 39 | 39 | 39 |
| 2023 Q2 | 47 | 46 | 45 |
| 2023 Q3 | 52 | 52 | 52 |
| 2023 Q4 | 58 | 56 | 56 |
| 2024 Q4 | 66 | 65 | 65 |
| 2025 Q2 | 69 | 69 | 68 |
| 2026 Q1 | 70 | 70 | 69 |

Finding: 2022 Q4 is the first broad historical-period presence (46/70); 2023 Q1 is the first broad current-period presence (39/70). Broad describes the observed step-change, not a new approved numerical threshold. The current staging_bdc.py pre-filter removes comparative rows; thus 2022 Q4 has only 3 cohort funds in unified holdings. Adopting 2022 Q4 as required public history would require a separately validated historical reconstruction mechanism, including accession selection, deduplication and disclosure availability dates. Do not simply remove the comparative filter.

Recommendation for owner decision: 2023 Q1 for the continuous core history; optionally 2022 Q4 as a separately accepted opening snapshot. The fixed 70-fund denominator is today's cohort, not the number operating in each historical quarter. Fund financials are not a sufficient operating-fund denominator: 2023 Q1 has 51 funds with financial rows, 40 with positive extracted investment FV, and 5 of those 40 lack current-period XBRL holdings. Historical formation/operation dates and extraction gaps still require assessment. Raw XML availability and field-level tagging breadth were not independently inventoried, so absence in outputs does not prove absence in filings. Cohort labels were not reclassified in this audit.

Validation: bounded diagnostic completed, process exited; no remaining diagnostic Python process. No pytest, full suite, rebuild, output diff, export, baseline refresh, SEC downloads or pipeline changes.

## 2026-09-09: Programme current-state and architecture assessment

Question: What is implemented, what is active, and what prevents a reproducible approval-ready release across the approved historical, identity, enrichment and citation scope?

Read-only assessment traced production entrypoints, extraction/staging/unification, financial facts, distributed rules, entity/GICS enrichment, matching/chains, provenance/shadow validation, quarter passes, worker cleanup and public export paths. Inventoried 500 Python files (123 pipeline, 234 scripts, 143 tests; 4,998 static test functions) and 534 rule/config assets with hashes and loader qualifications. These are inventory counts, not collected tests or certified active rule counts.

Measured Q1-2026 manifest-cohort holdings: 30,067 rows, 69 funds, FV 381,537,030,207. Public portfolioFv and the GICS sector sum remain 382,151,960,774; metadata is separately 381,907,021,055. Source inspection also found scaled/reconciled GICS overlays contrary to the current direct-aggregation contract. Position matches CSV/Parquet have 497,456/536,455 rows; current cohort position IDs are all blank. Saved provisional-v3 quarter gate dated 2026-09-08 16:31:46 UTC fails 5 of 9 checks. Numeric FV provenance raw-matches approximately 99.75% of current cohort FV, which does not establish roster completeness or economic-row correctness.

Important existing capabilities retained in the assessment: promoted correction verification/audits, raw XML provenance, shadow ledgers, matching gold/chain tooling, GICS quality gate/review caches, HTML table/cell citation anchors, typed Parquet and a bounded dbt spike. Remaining gaps include stable entity as well as position IDs, historical eligible-fund denominators, inference lineage, atomic release dependencies, complete holdings/history serving and PDF passage mapping. Worker cleanup removes resumable session state by default; no provider quota-interruption experiment was performed.

Deliverables: [architecture](../reference/current_architecture.md), [dated assessment](../production_stack/current_state_assessment_2026-09-09.md), [tracked evidence](../production_stack/current_state_evidence_2026-09-09.json), and linked source/rule inventories. See those documents for denominators, artifact timestamps, qualifications and recommended acceptance-contract work.

Validation: bounded cached read-only diagnostics completed; documentation links checked. No tests, build, rebuild, export, semantic diff, baseline refresh, reattestation, SEC downloads or enrichment calls. No production behavior/schema/output changes. Existing working-tree changes preserved.

## 2026-09-09: Programme contract conflicts traced and saved-artifact baselines prepared

Question: How do F01-F12 relate to current rule order, existing validation and the accepted owner decisions, and which measurements can be prepared without changing production?

Added [rule/validation resolutions](../production_stack/programme_conflict_resolution.md) for all twelve findings and seven bounded implementation packet boundaries, plus a [dated assessment](../production_stack/programme_contract_assessment_2026-09-09.md) with tracked collector, queries, results, 653 input hashes, 251 correction/anchor/bridge JSON instance records and a 910-slot obligation frame. The instance inventory records loader-path eligibility and scopes, not successful application or complete runtime rule coverage.

Fresh saved-CSV assessment covers 261,613 observations over Q1-2023 through Q1-2026. 779 of 910 cohort-quarter slots contain holdings; 131 lack output, of which 31 have same-report-date filing-index records. Eligibility remains unadjudicated. Ten exact-key Agent A spread-correction matches at CIK 0001633336 retain decimal fractions in a percentage-point field (two in Q1-2026); source-value correctness still needs independent review. Production/verifier B2 order algorithms differ, but zero current cross-stage inversions were found within a CIK. The single .proposed.json HTML bridge remains loader-eligible with 41 records containing required keys; no conclusion about separate approval or current matched rows.

Q1 remains 30,067 rows / 69 funds / signed FV 381,537,030,207; absolute FV is 382,026,825,645. It has 1,425 cost-proxy rows, no output zero costs, 15,041 GICS-filled rows (72.9841% absolute-FV coverage), 860 missing entity IDs and all 30,067 position IDs blank. Thirteen-quarter row IDs/source-context keys have no duplicates among nonempty keys, but 4,555 within-quarter position-key groups have multiple observations (5,459 excess members); this is not permission to deduplicate lots. Unit tokens require source-document resolution; missing_reference_fx is not a count of foreign loans.

Validation: completed bounded DuckDB/config diagnostic with 240-second watchdog, two threads, 1 GB DuckDB memory, no spill, and unchanged pinned-input size/mtime guards. Earlier diagnostic SQL alias errors exited and were corrected; successful output supersedes partial scratch files. Documentation/artifact consistency checked; investigation index rebuilt. No pytest/build, pipeline/correction replay, source benchmark, rebuild/export, semantic diff, baseline change, reattestation, SEC download, enrichment call or agent dispatch. Production files and prior user changes preserved.

## 2026-09-09: Programme historical eligibility and independent reference preparation

**Question:** Which of the 131 missing required-history fund-quarters are actual coverage gaps, and which existing source/identity/enrichment reference assets can support measured programme acceptance?

**Method:** Cache-only bounded DuckDB/HTML/XBRL-text-block inspection using the 70-CIK manifest and the previous 910-slot frame. Read source lifecycle statements and early filings, distinguish investment activity from BDC election, inventory existing gold metadata/exposure, and freeze source-selected calibration clusters. No SEC requests, production rebuilds or gold-label edits. Full methods and limitations: [programme reference assessment](../production_stack/programme_reference_and_eligibility.md); [evidence bundle](../production_stack/programme_reference_evidence_2026-09-09/README.md).

**Results:** 811 slots assessed eligible, 98 before investment activity and one unresolved (Fortress Q1-2025). 779/811 eligible slots contain saved rows, or 96.05% presence; this is not row/FV accuracy. The 131 missing-output slots split into 98 pre-investment, 32 eligible gaps and one unresolved. Positive source investment facts support 23 of those 32 gaps; nine require a roster or evidenced empty/cash-only status. Seven eligible gaps have no primary-period/companyfacts-accession document candidate in the bounded inventory; this does not establish absence throughout the cache. Lifecycle exclusions require independent review before the final gate denominator; cash and other retained disclosures are not erased.

**Mechanisms:** Bain disclosed two Legacy Corporate Lending equity positions at June 2023 totaling $646,250 before a later stated November commencement, so its earlier investment quarters remain eligible. Fidelity's LP-to-LLC continuity and December 2022 portfolio predate BDC election. Lord Abbett has nine eligible quarters missing from holdings, with March 2026 source investments of $1.413006bn. Source Esdec principal at September 2023 is printed in EUR but tagged USD; following quarters agree on EUR, while cost/FV stay USD. Record the conflict and evidence before resolving it; do not turn a tag-only match into a claim of financial accuracy.

**Reference readiness:** Existing source-field gold has 128 latest labels, 127 in programme scope, all tail census. mg3 includes 175 entity packets within its 535-packet batch; mg4 and mg5 add 265 and 100 packets. Prior tuning/promotion exposure prevents an automatic fresh-held-out claim. No independent reviewed sector benchmark was found in the bounded inventory. A 61-cluster calibration pilot, 39 exact source passages and four development case definitions are pinned. Complete independent rosters, primary anchors, sector labels and final hold-out governance remain open; no cohort source-accuracy result or new threshold is claimed.

**Verification:** 2,083 pinned input stats unchanged; canonical holdings hash matches the prior audit; 910 unique slots, quarter/sample counts and exact passages checked. Collector syntax/document links checked and investigation index rebuilt. No tests, application build, production evaluator, benchmark scorer, downloads, rebuild, export, semantic output diff, baseline refresh, reattestation or agent fleet run.

## 2026-09-09: Programme pilot distinguishes candidate errors from reference errors

**Question:** Can the frozen source pilot support numerical programme gates, and which reference/eligibility gaps prevent a trustworthy accuracy claim?

**Method:** Independent cache-only inline/source-row reader, explicit development roster review, DuckDB comparisons to the pinned saved holdings and isolated reuse of the old source-field label scorer. Original sources, gold labels, production outputs and prior dated reference files preserved. Full [pilot report and proposed gates](../production_stack/programme_measurement_pilot_2026-09-09.md), [evidence bundle](../production_stack/programme_pilot_evidence_2026-09-09/README.md).

**Results:** Fortress Q1-2025 is positively evidenced as investment-active. The updated 910-slot assessment has 812 eligible, 98 pre-investment and zero unresolved statuses; 779/812 have saved rows (95.94% presence), with 33 unrepresented slots still requiring portfolio/empty-state dispositions. Source candidates exist for 53 of the 61 pilot packets; a bounded comparative search read 77 XML documents for the other eight. Two complete development rosters were reviewed: Bain Q2-2023's two equity instruments/$646,250 match the saved candidate; Lord Abbett Q3-2024 has 33 disclosed loans/facilities, no saved holdings and a $313.562m primary portfolio anchor. Six untagged FV dashes explain why a tag-only roster is incomplete even when known signed values sum exactly to the source total. No numerical zero was fabricated for those fields.

**Reference failure mechanisms:** The 47,230 tag-copy probes have 26,345 agreeing fields and 30 numeric discrepancies, plus explicit unavailable/conflicting/unmatched states. Agreement is not correctness: Paragon's source prints 3.38% PIK and the candidate stores 3.38pp, but the inline fact incorrectly implies 338pp under fractional-rate interpretation. The historical label comparison has 122 unique joins out of 127, four missing and one ambiguous. Source review found that Aurelia's apparent FV failure uses a EUR label against a USD output; Sentinel's apparent FV/cost failures use a JV delayed-draw reference against the parent's term loan. Both Sentinel schedules are December 2025 and reuse the same numbered identifier, so date/name matching alone cannot fix the reference key. No original labels were edited or silently excluded from the archived diagnostic.

**Implication:** Keep source meaning, accounting basis and currency in benchmark identity; require row/FV/fund coverage separately; never certify a source-only fact extractor as the source roster. The proposed numerical gate is concrete but not calibrated/approved: remaining rosters, independent sector/identity truth, synchronized candidate and browser evidence are still required. No full-population financial accuracy, entity precision, GICS accuracy or citation coverage is claimed.

**Verification:** Eight focused tests passed; successful bounded pilot, hashes and 2,083 prior input stats checked unchanged. Full semantic-backstop byte scan stopped at 240 seconds; five-artifact semantic comparison completed with existing active-baseline differences. Protected-output guard passed. No production data/schema/threshold changes, gold promotion, rebuild/export, full suite/build, source downloads or fleet. Investigation index rebuilt.

## 2026-09-09: Programme preparation closeout and synchronized candidate

**Question:** Can the remaining specification preparation be made concrete with source dispositions, measured rule impact, compatible consumers, execution/recovery proofs and numerical requirements?

**Method:** Frozen 1,372-file copied workspace; cached isolated unified build; derivative identity and PIK builds; full B2 pre/post accounting and reverse-order replay; source-specific literal reviews; all 535 exposed mg3 packets scored against regenerated identities. Original production data, labels, thresholds and baseline preserved. Full [closeout](../production_stack/programme_spec_closeout_2026-09-09.md), [evidence](../production_stack/programme_closeout_evidence_2026-09-09/README.md) and [bounded next tranche](../production_stack/programme_execution_tranche_2026-09-09.md).

**Source findings:** All 61 packets now have explicit dispositions: four complete development rosters, 48 uncertified full rosters, eight primary sources unavailable and one pre-investment. Newly reviewed 26North Dec-2023 has four source positions/$52.566m signed FV; Golub Private Credit Jun-2023 has one named money-market instrument/$650.323m. Both have zero candidate rows. These amounts are from different quarters and must not be pooled into a current-portfolio error rate. Twenty legacy-label proposals identify currency, parent/JV, prior-period/current-cost, exact-source-row and classification-leaf defects; original labels remain unchanged. Document unit resolution found 6,650 foreign-tagged field observations and 7,107 absent/unresolved observations. Printed-source conflicts prevent interpreting every foreign tag as an actual FX requirement.

**Synchronized results:** The 780,425-row unified CSV is byte-identical to the pilot input; CSV/Parquet comparison has zero typed cell differences. All 22 applied B2 leaves replayed without execution errors; net signed FV change $21.298m, sum of absolute fund-quarter changes $78.482m, one observed overlap and zero tracked-field order differences. These are B2-only input-specific results, not certification of all rule families. Fresh matching/entity generation yields 237,957 position IDs, 37,103 entity IDs and no same-period position-ID collision groups. Exposed mg3 regression still finds 22 false position merges, 19 missed continuations, 13 entity false merges and two false splits. Full source-selected chain completeness and unbiased population identity accuracy remain unassessable.

**Execution/navigation:** Unified success took 35.8 minutes after a retained timed-out attempt; identity about 9.5 minutes; PIK about one minute. A real 2.18GB completed-bundle restore passed in 6.52 seconds. Six actual filing highlights, calculation/inference evidence, unavailable/rejected locators, keyboard and mobile checks passed; 36 browser navigations had local p95 3.91 seconds. The inferred sector example is provisional research, not independent GICS gold. Python guards and strict manifests prove a trusted-code preparation boundary, not complete native-IO isolation.

**Implication:** Preparation can close with explicit evidence gaps. The proposed result is `FAIL_WITH_UNASSESSED_ITEMS`; no current-data acceptance is implied. Requirements and a concrete eight-hour WP-01/WP-02 tranche are ready for review. Independent roster/sector/chain references, broader interaction checks and final production runtime remain implementation dependencies.

**Verification:** Twenty-six focused tests, real isolated stages, browser checks and final stage composition passed. Exact PIK correspondence covers all 780,425 parent CSV rows; an initial checker mistook timestamp spelling normalization for drift, with zero typed-date differences. Original 1,117 frozen pipeline/data/control files, 1,605 used match-reference inputs and position-label SHA unchanged. Two large CSVs compressed with verified roundtrips. Full semantic byte scan did not complete within 240 seconds; five-artifact semantic comparison completed with the same pre-existing divergence. No full suite, public frontend build, production rebuild/export, live-gate/reattest, downloads, paid enrichment, gold/threshold promotion or baseline refresh.


## 2026-09-10: Why programme verification failed and ran slowly

**Question:** What caused the stopped full-suite failures, six protected cache writes and excessive runtime, and which repairs can be verified without another candidate build?

**Findings:** The original log has four failure markers; the earlier one-failure handoff was wrong. All four mapped candidates reproduced: three stale expected wrapper versions and one production validator checking DuckDB regexes with Python. The version expectations are repaired; the validator correction remains. All 106 staging expressions from 77 v2/v3 wrappers compile after existing preprocessing. Native DuckDB cache writes escaped Python file-open interception because orchestration fixtures missed the query module's independent cache root and real default sources. Tiny staging fixtures also processed a 296 MB production overlay. Isolating it reduced two profiled cases from about 170 seconds each to 74-81 seconds, while retaining a real file-backed integration test. Remaining parse/dedup cost is substantial and is not fully explained.

**Verification:** Final bounded run: 61 passed, one known validator failure, including all 54 cache/query/orchestration tests and four staging/integration cases. A broader attempt was stopped after 574 passing calls; the 59-case class and full suite are not completed passes. A launcher-zero/worker-failure mismatch and a Windows progress-file replacement failure were retained and addressed in the diagnostic controller. Seven diagnostic attempts ended with no further protected-file metadata changes; 1,117 frozen inputs, 1,605 matching references, original gold and source freezes retain hashes. Existing five-artifact semantic divergence is unchanged under the established numeric rule. The full byte-scan child failed on DLL loading before comparison; it is not a pass.

**Implication:** Correct the regex validator using the runtime dialect and preprocessing, integrate the verified native boundary/durable-result handling into full-suite execution, and measure an adequate runtime allowance. Then verify candidate dependencies before financial measurement and recovery. No production pipeline change or holdings rebuild was needed for these test repairs. The six original empty caches remain because earlier automatic approval review rejected removal. No full-population accuracy or engineering-completion claim.

**Evidence:** [Readable investigation](../production_stack/programme_verification_investigation_2026-09-10.md), [retained results](../production_stack/programme_tranche_evidence_2026-09-10/verification-investigation-v1/result.json), [preservation check](../production_stack/programme_tranche_evidence_2026-09-10/investigation-preservation-v1/result.json). Failed attempts and historical handoffs were preserved, with corrections recorded separately.
