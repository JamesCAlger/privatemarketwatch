<!-- Canonical investigations file (cutover 2026-08-20). Append new entries with a
     dated '## ' heading, the question asked, and the results found; then rebuild
     the index: python scripts/split_investigations.py --reindex -->
# Source reconciliation & blocker chains

## BDC source reconciliation blockers - 2026-05-19

Question: reduce source reconciliation blockers using deterministic source-to-output evidence, without weakening validation or accepting many-to-one numeric aliases as matches.

Sources: cached `bdc_holdings.csv`, cached XBRL files referenced by `bdc_filings_index.csv`, rebuilt `private_markets_holdings.csv`, and generated source reconciliation artifacts in `data/output/`.

Commands and queries used:

- `pytest tests/test_validate_holdings.py::TestBdcSourceReconciliation -q --basetemp .\tmp_pytest -o cache_dir=.\tmp_pytest\.pytest_cache`
- `pytest tests/test_unified_holdings.py::TestPrepareBdc -q --basetemp .\tmp_pytest -o cache_dir=.\tmp_pytest\.pytest_cache`
- `python -m py_compile pipeline\source_reconciliation.py pipeline\staging_bdc.py pipeline\unified_holdings.py`
- `python scripts\rebuild_outputs.py --unified`
- `python -m pipeline.main --validate`
- `python -c "from pipeline.export_frontend import export_all; export_all()"`
- Python artifact summaries over `source_reconciliation_detail.csv` and `source_reconciliation_residual_classification.csv`, grouped by status, mechanism, CIK, and fair value.

Implementation summary: `pipeline/staging_bdc.py` now removes prefix-parent BDC rows only when at least two FV-carrying child rows extend the identifier and exactly sum to the parent within the existing tolerance. One-child prefix cases, including Cambium/Emerald-style rows, are retained as distinct positions unless another deterministic aggregate rule applies. `pipeline/source_reconciliation.py` now separates exact source rollups into `documented_source_rollup_exact`, a non-blocking documented exclusion with child count and child FV evidence, and applies that only to source rows not already matched by stronger identity evidence. Numeric identity remains one-to-one only; ambiguous numeric candidates are classified as already-matched output aliases, multi-output collisions, or multi-source collisions.

Post-validation counts from `2026-05-19 23:24` artifacts:

| Metric | Count |
|---|---:|
| Detail rows | 1,169,728 |
| Blocking rows | 21,486 |
| Matched rows | 458,758 |
| Missing-from-pipeline blockers | 21,049 |
| Extra-in-pipeline blockers | 437 |
| Documented exact source rollups | 6,510 |
| Documented exact rollup source FV | $272.0B |

Top residual blocking mechanisms:

| Mechanism | Rows |
|---|---:|
| `blocking_source_only_position` | 18,738 |
| `blocking_numeric_already_matched_output_alias` | 2,247 |
| `blocking_pipeline_only_position` | 437 |
| `blocking_identifier_parse_artifact` | 64 |

Top residual blocking CIKs:

| CIK | Entity | Blocking rows |
|---|---|---:|
| `0001633336` | Crescent Capital BDC, Inc. | 1,678 |
| `0001278752` | MidCap Financial Investment Corp | 1,174 |
| `0001786108` | Trinity Capital Inc. | 1,016 |
| `0001954360` | Crescent Private Credit Income Corp | 1,006 |
| `0001655050` | Bain Capital Specialty Finance, Inc. | 898 |
| `0001280784` | Hercules Capital, Inc. | 723 |
| `0001849894` | MSD Investment Corp. | 663 |
| `0001920145` | Goldman Sachs Private Credit Corp. | 545 |
| `0001786835` | Star Mountain Lower Middle-Market Capital Corp | 527 |
| `0001370755` | BlackRock TCP Capital Corp. | 481 |

Examples checked:

- Exact documented rollups include Rand Capital 2023-03-31 rows such as `BMP Food Service Supply` with source FV $5.21mm and `child_output_count=2; child_output_fair_value=5210000.0`, plus similar `BMP Swanson`, `DSD`, `Filterworks`, and `ITA Acquisition, LLC` rows.
- Cambium-style parent and `Emerald JV LP` suffix child rows are covered by a staging regression test and both survive when FV evidence does not prove a subtotal.
- A matched parent source row with distinct suffix children is not converted into a documented rollup and does not suppress child output residuals.
- Numeric aliases to already matched outputs remain blocking and are classified as `blocking_numeric_already_matched_output_alias`, not `reconciled_numeric_identity`.

Conclusion: blockers fell from the prior-plan baseline of 31,576 to 21,486. The decrease came through deterministic mechanisms: exact source rollups are now documented non-blocking exclusions, and over-broad prefix subtotal removal has been tightened so real parent positions can survive the unified rebuild. No FV-only or many-to-one numeric candidate was promoted to a reconciled match.

Validation notes: `python -m pipeline.main --validate` completed successfully and wrote source reconciliation artifacts. It still reports broader known validation risks, including 269 GAV over-coverage rows, 1,210 GAV under-coverage rows, and 317 high pct-of-net-assets CIK-quarters. `python -m pipeline.main --export-frontend` was not usable in the sandbox because it attempted SEC network calls and timed out; the cached export function `pipeline.export_frontend.export_all()` completed successfully instead.

Residual uncertainty: `documented_source_rollup_exact` proves arithmetic rollup behavior against current output rows; it does not prove every child classification is correct. The largest remaining blockers are still source-only rows, especially Crescent, MidCap, Trinity, Crescent Private Credit, and Bain. Those need CIK-quarter scoped source review rather than broader global filters. GAV and pct-of-net-assets warnings remain live validation concerns and should not be suppressed as a side effect of this reconciliation improvement.

---

## BDC source-only blocker classification - 2026-05-20

Question: classify remaining BDC source-only blockers so generic `blocking_source_only_position` is not the terminal explanation, while keeping ambiguous or position-like rows blocking.

Sources: cached `source_reconciliation_detail.csv`, cached XBRL-derived BDC source facts, rebuilt `private_markets_holdings.csv`, and generated source-only classification artifacts in `data/output/`. No SEC or third-party network calls were made.

Commands and queries used:

- `pytest tests\test_validate_holdings.py -k "source_only or residual_classification" --basetemp .pytest_tmp`
- `pytest tests\test_unified_holdings.py tests\test_validate_holdings.py -k "source_only or residual_classification or bdc_source_reconciliation" --basetemp .pytest_tmp`
- `python -m py_compile pipeline\source_reconciliation.py pipeline\staging_bdc.py pipeline\unified_holdings.py`
- `python scripts\rebuild_outputs.py --unified`
- `python -m pipeline.main --validate`
- Python summaries over `source_reconciliation_source_only_detail.csv`, `source_reconciliation_source_only_clusters.csv`, and `source_reconciliation_residual_classification.csv`.

Implementation summary: `pipeline/source_reconciliation.py` now builds additive source-only artifacts: row-level detail, grouped clusters, and markdown. The classifier preserves numeric alias mechanisms first, documents high-confidence total/header, cash or money-market, affiliation, category, and country/industry headers as non-position exclusions, and keeps percentage hierarchy, position-like parser mismatch, short plain unresolved, and unclassifiable-after-review rows blocking. `pipeline/validate_holdings.py` writes the three new artifacts during validation. Existing `source_reconciliation_detail.csv` schema is unchanged.

Post-validation counts from `2026-05-20 01:13` artifacts:

| Metric | Count |
|---|---:|
| Source reconciliation detail rows | 1,169,728 |
| Source reconciliation blocking issues | 14,171 |
| Source-only classifier rows | 13,734 |
| Source-only clusters | 2,042 |
| Source-only documented non-position rows | 1,864 |
| Source-only rows still blocking | 11,870 |
| Residual groups with `blocking_source_only_position` | 0 |

Source-only row mechanisms:

| Mechanism | Rows |
|---|---:|
| `blocking_source_pct_hierarchy_parser_mismatch` | 8,514 |
| `blocking_source_position_like_parser_mismatch` | 2,659 |
| `documented_source_category_header` | 1,062 |
| `documented_source_cash_or_money_market_bucket` | 508 |
| `blocking_source_short_plain_unresolved` | 402 |
| `blocking_source_unclassifiable_after_review` | 284 |
| `documented_source_total_header` | 174 |
| `documented_source_country_industry_header` | 79 |
| `documented_source_affiliation_header` | 41 |
| `blocking_numeric_already_matched_output_alias` | 11 |

Top source-only CIK work packets by row count:

| CIK | Entity | Rows |
|---|---|---:|
| `0001633336` | Crescent Capital BDC, Inc. | 1,166 |
| `0001655050` | Bain Capital Specialty Finance, Inc. | 794 |
| `0001954360` | Crescent Private Credit Income Corp | 783 |
| `0001786108` | Trinity Capital Inc. | 671 |
| `0001280784` | Hercules Capital, Inc. | 594 |
| `0001278752` | MidCap Financial Investment Corp | 566 |
| `0001849894` | MSD Investment Corp. | 531 |
| `0001920145` | Goldman Sachs Private Credit Corp. | 423 |
| `0001383414` | PENNANTPARK INVESTMENT CORP | 327 |
| `0001508655` | Sixth Street Specialty Lending, Inc. | 321 |

Examples checked:

- `TOTAL INVESTMENTS - 114.8%` is classified as `documented_source_total_header`, while `Total Safety Holdings LLC` remains `blocking_source_position_like_parser_mismatch`.
- `Goldman Sachs Financial Square Government Institutional Fund` is classified as `documented_source_cash_or_money_market_bucket`.
- Crescent-style country/industry headers such as `Investments Netherlands Debt Investments Financial Services` are classified as `documented_source_country_industry_header`.
- MSD-style hierarchy headers without entity/rate/maturity evidence are classified as `documented_source_category_header`.
- Long Bain/Overland-style rows with company, rate, maturity, and instrument signals remain blocking parser mismatches.

Conclusion: the generic source-only residual bucket has been eliminated from residual classification. Blocker count did not decrease by suppressing ambiguity: parser-mismatch, numeric alias, short unresolved, and unclassifiable-after-review rows remain blocking. The new artifacts make the remaining work CIK-quarter scoped and auditable.

Residual uncertainty: these rules classify source-only residual mechanisms; they do not prove the correct parser repair for every blocking row. `blocking_source_unclassifiable_after_review` is a reviewed stopping point, not correctness evidence. The largest residual work packets remain Crescent, Bain, Trinity, Hercules, MidCap, MSD, and Goldman style hierarchy/parser issues.

## BDC source-only percentage hierarchy split - 2026-05-20

Question: split the mixed `blocking_source_pct_hierarchy_parser_mismatch` bucket into documented terminal-percentage rollups/headers, blocking leaf parser mismatches, and still-blocking ambiguous percentage rows before building CIK-specific parsers.

Sources: cached `source_reconciliation_detail.csv`, regenerated source-only classification artifacts in `data/output/`, and focused tests in `tests/test_validate_holdings.py`. No SEC or third-party network calls were made.

Commands:

- `python -m py_compile pipeline\source_reconciliation.py`
- `pytest tests\test_validate_holdings.py -k "source_only or residual_classification" --basetemp .pytest_tmp`
- `python -m pipeline.main --validate`

Validation note: `python -m pipeline.main --validate` reached and wrote the source reconciliation artifacts, then timed out after 20 minutes during later column-level validation. The source-only summaries below are from the regenerated reconciliation artifacts, but the full validation command did not complete cleanly.

Implementation summary: terminal-percentage source-only rows now require strict no-leaf-signal guards before being documented as non-blocking. Totals such as `TOTAL INVESTMENTS - 134.4%` and `Net Assets-100.0%` map to `documented_source_pct_total_header`. Category, geography, and security-type rollups such as `Debt Investments (184.96%)`, `Investments in Securities (193.86%)`, `Investment United States - 141.4%`, and `Investment 1st Lien/Senior Secured Debt - 136.5%` map to `documented_source_pct_category_rollup`. Rows with issuer, legal suffix, `Investment Type`, rate, reference-rate/spread, maturity, SOFR/LIBOR/EURIBOR, loan/note/bond/equity/warrant, par/principal, or acquisition-date evidence map to `blocking_source_pct_leaf_parser_mismatch`. Terminal-percentage rows that are neither safe rollups nor leaf-evident remain blocking as `blocking_source_pct_ambiguous_after_review`. Numeric aliases still take precedence.

Before/after percentage bucket summary:

| Mechanism | Rows | Source FV |
|---|---:|---:|
| Old `blocking_source_pct_hierarchy_parser_mismatch` | 8,514 | 543,422,924,304 |
| New `blocking_source_pct_leaf_parser_mismatch` | 7,496 | 128,526,611,073 |
| New `documented_source_pct_category_rollup` | 903 | 404,811,625,571 |
| New `documented_source_pct_total_header` | 138 | 116,468,097,164 |
| New `blocking_source_pct_ambiguous_after_review` | 54 | -11,217,617,358 |
| Remaining `blocking_source_pct_hierarchy_parser_mismatch` | 0 | 0 |

Top remaining percentage leaf parser CIKs by row count:

| CIK | Entity | Rows | Source FV |
|---|---|---:|---:|
| `0001633336` | Crescent Capital BDC, Inc. | 1,009 | 3,782,429,000 |
| `0001954360` | Crescent Private Credit Income Corp | 719 | 1,215,689,000 |
| `0001655050` | Bain Capital Specialty Finance, Inc. | 586 | 8,316,702,000 |
| `0001849894` | MSD Investment Corp. | 498 | 13,247,830,000 |
| `0001920145` | Goldman Sachs Private Credit Corp. | 353 | 4,774,657,000 |
| `0001508655` | Sixth Street Specialty Lending, Inc. | 281 | 3,009,339,000 |
| `0001370755` | BlackRock TCP Capital Corp. | 250 | 1,252,371,000 |
| `0001902649` | BlackRock Private Credit Fund | 248 | 16,913,110,000 |
| `0001925309` | Sixth Street Lending Partners | 236 | 14,016,710,000 |
| `0001280784` | Hercules Capital, Inc. | 235 | 4,777,907,000 |

Top remaining ambiguous percentage CIKs by row count:

| CIK | Entity | Rows | Source FV |
|---|---|---:|---:|
| `0001825265` | TCW Direct Lending VIII LLC | 14 | -2,877,322,000 |
| `0001988280` | Manulife Private Credit Fund | 10 | 859,496,200 |
| `0001383414` | PENNANTPARK INVESTMENT CORP | 8 | -6,618,840,000 |
| `0001743415` | SCP Private Credit Income BDC LLC | 5 | -667,307,000 |
| `0001634452` | AB Private Credit Investors Corp | 5 | -1,434,114,000 |

Conclusion: the old mixed percentage hierarchy bucket has been eliminated from regenerated source-only and residual classification artifacts. The parser work queue should now prioritize `blocking_source_pct_leaf_parser_mismatch` by row count, while documented rollup/header FV is visible separately and should not be read as missing-position FV.

Residual uncertainty: this split is a classifier and prioritization improvement, not parser repair. The remaining leaf rows still require CIK-quarter scoped parser work and source reconciliation. The 54 ambiguous terminal-percentage rows remain blocking because they lack deterministic evidence strong enough to clear them as rollups.

## Crescent hierarchy percentage leaf parser repair - 2026-05-20

Question: clear the largest `blocking_source_pct_leaf_parser_mismatch` packet by adding a real parser repair for Crescent-family hierarchy rows at CIKs `0001633336` and `0001954360`, without reclassifying source-only rows as documented rollups.

Sources: cached `bdc_holdings.csv`, regenerated `private_markets_holdings.csv`, regenerated source reconciliation artifacts in `data/output/`, and focused tests in `tests/test_unified_holdings.py` / `tests/test_validate_holdings.py`. No SEC or third-party network calls were made.

Commands:

- `pytest tests\test_unified_holdings.py -k "aggregate or Crescent or maturity" --basetemp .pytest_tmp`
- `pytest tests\test_validate_holdings.py -k "source_only or residual_classification" --basetemp .pytest_tmp`
- `python scripts\rebuild_outputs.py --unified`
- `python -m pipeline.main --validate`

Implementation summary: BDC aggregate detection now has a narrow leaf-detail guard requiring `Investment Type`, loan/equity instrument text, and rate or maturity evidence before category-prefix filters are bypassed. BDC staging now has a CIK-scoped Crescent hierarchy parser for `0001633336` and `0001954360` that extracts issuer after the observed country/security-type/industry hierarchy and extracts instrument after `Investment Type`. Month/year `Maturity/Dissolution Date` text is normalized to month-end. VetStrategy-style trailing tranche labels (`One`, `Two`, etc.) are retained in the instrument key so equal-FV tranches remain distinct positions.

Before/after Crescent-family source-only mechanisms:

| Mechanism | Before Rows | After Rows | After Source FV |
|---|---:|---:|---:|
| `blocking_source_pct_leaf_parser_mismatch` | 1,728 | 23 | 96,069,000 |
| `blocking_source_position_like_parser_mismatch` | 99 | 97 | 129,061,000 |
| `documented_source_country_industry_header` | 76 | 44 | 275,074,000 |
| `documented_source_cash_or_money_market_bucket` | 28 | 28 | 12,938,080,000 |
| `documented_source_category_header` | 18 | 17 | 957,755,000 |

Examples now present in unified holdings:

| CIK | Report Date | Issuer | Instrument | Maturity |
|---|---|---|---|---|
| `0001633336` | 2023-03-31 | Greencross (Vermont Aus Pty Ltd) | Unitranche First Lien Term Loan | 2028-03-31 |
| `0001633336` | 2023-03-31 | Miraclon Corporation | Unitranche First Lien Term Loan | 2026-04-30 |
| `0001633336` | 2023-03-31 | VetStrategy | Unitranche First Lien Delayed Draw Term Loan - Five | 2027-07-31 |
| `0001633336` | 2023-03-31 | VetStrategy | Unitranche First Lien Delayed Draw Term Loan - Four | 2027-07-31 |

Residual examples after repair:

- `Investments United States Debt Investments Health Care Equipment & Services Patriot Acquisition Topco S.A.R.L Investment Type Unsecured Debt Interest Term 1400 PIK Interest Rate 14.00% Maturity/ Dissolution Date 02/2030`
- `Investments United States Debt Investments Health Care Equipment & Services, Centria Subsidiary Holdings, LLC, Investment Type Unitranche First Lien Term Loan, Interest Term S + 525, (100 Floor), Interest Rate 9.05%, Maturity/ Dissolution Date 06/2027`
- `Investments United States Debt Investments Diversified Financials Essential Services Holding Corporation Investment Unitranche First Lien Revolver Interest Term S + 500,75 Floor Interest Rate 9.19% Maturity / Dissolution Date 06/2031`
- `Investments United Kingdom Debt Investments Commercial & Professional Services Nurture Landscapes Investment One Type Unitranche First Lien Delayed Draw Term Loan Interest Term SN + 650 Interest Rate 10.99% Maturity/ Dissolution Date 06/2028`

Validation notes: Crescent pct leaf blockers dropped by 1,705 rows, clearing materially more than the 1,200-row acceptance threshold. A scoped aggregate leak audit for the two Crescent CIKs returned zero suspected aggregate rows. The regenerated source-only markdown now ranks `blocking_source_pct_leaf_parser_mismatch` at 5,559 rows, down from 7,496, and documented terminal-pct rollup/header FV remains separated from blocking leaf-parser FV.

Residual uncertainty: this parser is intentionally strict and limited to the observed Crescent family. The remaining 23 Crescent pct leaf blockers are real parser work, mostly punctuation or label variants such as `Investment` without `Type`, comma-separated hierarchy text, `Maturity / Dissolution Date`, and `Investment One Type`. Those should be handled in a follow-up only after checking false positives against the affected CIK-quarters.

## Aggregate leak suspect spot-check review - 2026-05-21

Question: label the 385-row `aggregate_leak_spot_check_sample.csv` to estimate the aggregate-suspect audit false-positive rate without changing aggregate filtering logic.

Sources: `data/output/aggregate_leak_spot_check_sample.csv`, joined source-reconciliation fields already present in the sample, targeted checks against cached `data/output/bdc_holdings.csv`, and existing helper/test code in `scripts/spot_check_aggregate_leak_suspects.py` and `tests/test_aggregate_leak_spot_check.py`. No SEC EDGAR or third-party network calls were made.

Commands:

- `python` one-off local inspection snippets for sample schema, audit-keyword counts, joined source evidence, and targeted cached BDC exact-FV checks.
- `python` one-off local review writer to create `data/output/aggregate_leak_spot_check_reviewed.csv` and `data/output/aggregate_leak_spot_check_review_summary.md`.

Review result: all 385 sampled rows were labeled. Counts were 375 `false_positive_valid_position`, 7 `non_private_or_cash_scope_issue`, 3 `confirmed_aggregate_leak`, and 0 `ambiguous_needs_filing_context`. The weighted false-positive estimate, counting valid positions and scope issues as false positives and excluding ambiguous rows, was 99.3% with a 95% CI of 98.3% to 100.0%. Because there were no ambiguous rows, the ambiguous sensitivity range was also 99.3% to 99.3%.

Confirmed aggregate leaks:

| CIK | Entity | Report Date | Keyword | Fair Value | Evidence |
|---|---|---|---|---:|---|
| `0001890107` | First Eagle Private Credit Fund | 2025-03-31 | `non-control` | 613,639,000 | Identifier is only non-controlled/non-affiliated First Lien Debt with no issuer; cached BDC exact row has the same generic category string and pct-of-net-assets value. |
| `0001675033` | Great Elm Capital Corp. | 2024-12-31 | `total investments` | 54,053,000 | CLO Formation JV `Total Investments` label is a total/rollup, not a position. |
| `0001278752` | MidCap Financial Investment Corp | 2025-03-31 | `non-control` | 15,876,000 | Generic Electrical Equipment row has no company or instrument; cached BDC rows show matching industry/security rollup contexts. |

Main false-positive patterns:

- Hierarchy or affiliation wording prefixes otherwise position-like identifiers, especially `non-control`, `affiliate investments`, `investment debt investments`, `investment equity securities`, and `net assets`.
- Unsecured-debt and unfunded-commitment wording is embedded in real debt position descriptions.
- Cash, money-market, and JV liquidity rows are not aggregate leaks, but they need separate private-market scope treatment.

Conclusion: the current aggregate-suspect keyword audit is intentionally broad and has a very high false-positive rate on this sample. The next production change should not suppress the audit wholesale; it should narrow keywords using position-evidence exceptions and separately route cash/liquidity scope issues. Confirmed leaks are concentrated in generic category/total rows where there is no portfolio-company issuer/instrument evidence.

Residual uncertainty: the review did not inspect every underlying filing rendering; it used row fields, joined source evidence, and targeted cached BDC rows where needed. Rows labeled valid can still have separate parser, classification, or scope defects, but they are not aggregate leaks under the review definition.
## BDC source-blocker manual review progress - 2026-05-27

Question: continue manual source-blocker review one blocker at a time without using global heuristics or suppressing validation gates.

Sources: `data/output/bdc_cik_review/worklist.csv`, `data/output/bdc_cik_review/bundles/BDCSRC_0001418076_2024-03-31_BLOCKING_SOURCE_PCT_LEAF_PARSER_MISMATCH_40e573cb4c.json`, `data/output/source_reconciliation_source_only_detail.csv`, `data/output/source_reconciliation_detail.csv`, `data/output/bdc_holdings.csv`, `data/output/private_markets_holdings.csv`, and cached accession files under `data/raw/filings/bdc_xbrl/1418076/` and `data/raw/filings/bdc_html/1418076/`. No SEC EDGAR or third-party network calls were made.

Progress log:

| Blocker | CIK | Quarter | Mechanism | Fix or escalation | Validation before/after | Confidence |
|---|---|---|---|---|---|---|
| `BDCSRC_0001418076_2024-03-31_BLOCKING_SOURCE_PCT_LEAF_PARSER_MISMATCH_40e573cb4c` | `0001418076` | `2024-03-31` | Current residual narrowed to source row `177447`: SLR equipment-financing current-period XBRL typed member has FV/cost/principal `1,013,000`, rate range, acquisition date, and maturity range, but omits the borrower name. Visible cached HTML table 15 row 5 supplies the current-period borrower as `AFG Dallas III, LLC` with matching industry, rate, dates, par, cost, and fair value. | Patch proposed; use current-period rendered HTML evidence or an accession-scoped correction for this exact row. Do not infer borrower identity from comparative-period rows. | Before: verdict validation passed; summary showed 25 `PATCH_PROPOSED`. Intermediate escalation was corrected after rendered HTML review. | High for this row; low tolerance for broad implementation. |

Conclusion: this blocker is not safe to fix from XBRL typed-member text alone, but it is source-backed by the current-period rendered HTML schedule. The repair should be narrow: either parse/backfill from the rendered row or add an accession-scoped audited correction for this exact SLR row. It should not become a global rule that treats industry-label pipe rows as borrower positions.
## 2026-05-27 - MSD Investment Corp. Source-Reconciliation Blocker

Question: Why does the current source-only blocker packet
`0001849894 | MSD Investment Corp. | 2025-12-31 |
blocking_source_pct_leaf_parser_mismatch` contain 83 eligible source rows with
no unified output rows?

Sources used:
- `data/output/source_reconciliation_source_only_detail.csv`
- `data/output/source_reconciliation_residual_classification.csv`
- `data/output/source_reconciliation_detail.csv`
- `data/output/bdc_holdings.csv`
- `data/output/private_markets_holdings.csv`
- Cached XBRL instance:
  `data/raw/filings/bdc_xbrl/1849894/000119312526124538.xml`

Commands run:
- Queried the two source-reconciliation residual CSVs for CIK `0001849894`,
  report date `2025-12-31`, and mechanism
  `blocking_source_pct_leaf_parser_mismatch`.
- Inspected cached raw filing directories under
  `data/raw/filings/bdc_xbrl/1849894/` and
  `data/raw/filings/bdc_html/1849894/`.
- Compared the packet rows against `bdc_holdings.csv` and
  `private_markets_holdings.csv`.
- Ran `_prepare_bdc()` against the affected accession subset from
  `bdc_holdings.csv`.
- Ran `pytest tests/test_unified_holdings.py -k "msd_hierarchy"`.
- Attempted `python scripts/rebuild_outputs.py --unified`; the rebuild timed
  out at 10 minutes, then again at 30 minutes.

Decision/mechanism:
The rows are legitimate position-level leaves already present in
`bdc_holdings.csv`, not non-position rollups. MSD embeds a full hierarchy in
one typed-dimension value:
`Investments Investments - non-controlled/non-affiliated <asset type>
<industry> <issuer> ...`. The generic staging parser treated these as
generic `Investments...` issuer names, and the bad-issuer guard removed valid
borrowers without legal suffixes, such as `7Ridge Investments`,
`ALF Finance`, and `Foundation Risk Partners`.

Implemented a CIK-scoped staging parser for MSD (`0001849894`) that strips the
MSD hierarchy prefix, preserves position-level tranche/security text, and does
not widen the global bad-issuer filter. Added a false-positive guard showing
the same generic-looking hierarchy is not admitted for other CIKs.

Before/after blocker count:
Before: the residual artifacts showed 83 blocking source-only rows for this
packet and 118 current unified rows for the affected accession.
After, at staging level: all 83 packet identifiers survive `_prepare_bdc()` for
the affected accession subset, and affected accession staging rows increase
from 118 observed unified rows to 202 staging rows. Full regenerated
source-reconciliation blocker counts are not available from this run because
the cached unified rebuild timed out before a clean validation rebuild
completed.

Confidence: Medium-high for the parser mechanism because the 83 blocker rows
exactly match `bdc_holdings.csv` source identifiers and all 83 survive the
CIK-scoped staging parser after the fix.

Residual risk:
Full output/residual artifacts still need a clean cached rebuild and validation
run to confirm the packet clears end-to-end. The rebuild timeout also means
current generated outputs should not be treated as a clean production rebuild
until rerun successfully.

## 2026-06-17 - JV look-through double-count: BCRED Emerald JV ($6.5B), surfaced via gold-set labeling

Question: while gold-labeling BCRED (CIK 0001803498, 2025-12-31), the harness surfaced Medallia
appearing 3x -- two direct tranches (`Medallia, Inc. 1/2`) plus `Medallia, Inc. | Emerald JV LP`.
Does BCRED double-count its Emerald JV by carrying BOTH the JV interest AND the JV's underlying loans?

Findings (read-only over private_markets_holdings.parquet + iXBRL anchor):
- BCRED unified total: 2,002 rows / **$89.62B**.
- 427 rows carry the `| Emerald JV LP` suffix (the JV's own portfolio) = **$6.51B**, all classified
  `index_classification=DIRECT_LENDING`, `asset_category=LOAN`, and NOT flagged
  (`jv_subsidiary=None`, `is_subsidiary=0`).
- BCRED separately carries the JV interest line `BCRED Emerald JV LP - LP Interest` = **$1.679B**
  (`index_classification=PRIVATE_EQUITY_FUND`) -- this IS BCRED's actual economic stake (its equity).
- Independent anchor: iXBRL no-dimension `InvestmentOwnedAtFairValue` balance-sheet total = **$80.47B**.
- Reconciliation: unified $89.62B vs anchor $80.47B = **+$9.15B overshoot (+11%)**. The Emerald JV
  look-through explains **$6.51B**; a residual **+$2.64B** remains after removing it (separate,
  unexplained -- other JVs / comparative bleed / anchor noise; NOT investigated here).

Mechanism (why it is a double-count, not a real position set):
- The JV's 427 loans ($6.51B gross) are the JV's assets, financed by the JV's senior/intermediate
  notes (from the other partner) + BCRED's equity. BCRED's exposure is the **$1.679B LP interest**,
  not the gross loan book. The $6.51B/$1.679B ratio reflects JV leverage. BCRED's own balance sheet
  ($80.47B) counts only the LP interest -- which is exactly why the unified sum overshoots by ~$6.5B.
- This is the latent leak predicted in the SDLP discussion, here materialized at scale.

Properties (for the fix):
- Look-through rows are **identifiable**: every one carries `| Emerald JV LP` in
  `bdc_investment_identifier`. But they are **unflagged** and **misclassified DIRECT_LENDING**.
- Correct basis = keep the LP interest (matches the balance sheet), **drop the `| ... JV LP`
  look-through rows**. Must drop one or the other, never both.

Severity / next steps (not yet done):
- **Likely systemic.** Prior shadow residual-localization flagged other funds with multi-$B
  overshoots (CIK 0001851322 +$7.1B, 0001920453 +$2.0B) -- candidates for the same JV-look-through
  pattern. A cohort sweep for `| ... JV LP`-style look-through alongside a JV interest line is needed
  to size it.
- This is exactly the overshoot the shadow `fv_conservation` gate measures; BCRED should appear as an
  overshoot/leak there.
- Captured in the gold set at the CIK-quarter level (BCRED 2025-12-31: `true_total_investments_fv`
  = $80.47B, over-inclusion = 427 `| Emerald JV LP` rows / $6.51B). The direct `Medallia, Inc. 1`
  loan was separately CONFIRMED as a correct direct position (gold label, human:james) -- the
  double-count is a population/scope error on OTHER rows, not on the direct loan.
- Firewall: this gold-found error MOTIVATES a deterministic exclusion rule (drop JV look-through when
  the JV interest line is present); that rule's precision is then measured on a FRESH draw, never
  tuned against this finding.

## 2026-07-21 - Do high-FP review rules catch real errors no other rule catches? (unique-catch analysis)

**Question.** Before killing/demoting the high-FP rules surfaced by ens2+recal1
(X08 89% FP, C107 ~91%, C103 ~79% residual, X10 67%, PP01 ~56-62%, X07 54-71%,
C104/C404 already demoted, fmt_basis_spread/fmt_pct regressions), do any of their
REAL-adjudicated flags sit on units no other rule flags -- i.e., would killing
them silently drop real defects from review?

**Method.** New `scripts/ensemble/unique_catch_analysis.py`. All 1,323 decided
flag-level B1 verdicts (ens1+ens2+recal1 frames + 468 survived_exact pass-stamp
carryover, deduped by review_id) joined to era-matched review-queue co-firing
context (pre-wave1 snapshot for ens1/ens2/carryover; current post-wave1 queue for
recal1; fallback to the other era when a unit is absent). Unit = (cik,
report_date). Three coverage tiers per real flag: queue_covered (any other rule
flags the unit), kept_covered (a rule OUTSIDE the whole 11-rule high-FP set flags
it), real_covered (another rule's flag on the unit was itself adjudicated
real_error). Artifacts: `data/output/ensemble/unique_catch/`
(unique_catch_per_rule.csv, unique_catch_detail.csv, unique_catch_summary.md).

**Result: ZERO unique catches.** Every one of the 89 real flags across the 11
high-FP rules (C103 8, C104 3, C107 8, C404 4, PP01 14, X01 3, X07 15, X08 10,
X10 10, fmt_basis_spread 12, fmt_pct_of_net_assets 2) is on a unit also flagged
by at least one rule outside the entire high-FP set. X08 specifically: all 10
reals also have ANOTHER rule independently adjudicated real on the same unit --
killing it loses nothing measured.

**Coverage quality.** 60/89 reals (67%) have another independently-adjudicated
real on the same unit. For the 29 without, the mechanism mix explains the
coverage: 21/29 are `extraction_gap`, and their covering kept rules are
dominated by oracle-engine rules (E07 on 27/29 units; A07/B01/B02/C04), the
engine already measured at ~66% real for exactly that mechanism. The 2 PP01
`subtotal_leak` reals are covered by `agentA_subtotal_candidate` +
`fv_conservation` (same defect family). Residual distinctive mechanisms riding
on weaker coverage: 2 classification_lookthrough + 1 unit_scale +
1 genuine_value_defect (X07), 1 rate_scale (fmt_basis_spread 0001633336),
1 source_format_defect (fmt_pct 0001919369) -- these are covered at unit level
but by rules aimed at DIFFERENT defect families.

**Caveats.** (1) B1 adjudicates flag groups: unit-level coverage does not prove
the covering rule points at the same rows; a killed rule can still lose a
row-level pointer even when the unit stays in review. (2) The cohort queue is
d8plus-skewed (81% of units carry 8+ flags), which mechanically favors coverage;
alone-firing was already ~0 for all rules in ens2 rule_lift. (3) FP rates here
pool pre- and post-calibration eras; recal1-era rates are the decision numbers.

**Implication.** No high-FP rule is load-bearing for unit-level review coverage.
Kill/demote decisions can proceed on FP economics alone. Recommended shape:
demote to TRACK_ONLY (keep firing into artifacts as investigator evidence and
co-fire features, stop consuming B1 adjudications) rather than deleting
predicates -- preserves the row-level pointers caveat (1) worries about, at zero
adjudication cost. X07's classification_lookthrough/unit_scale reals suggest
keeping X07 in the queue lane (54% FP post-calibration is workable) rather than
grouping it with the kills.

## 2026-07-21 (part 2) - Row-level unique-catch analysis: high-FP rules DO catch unique row-level errors

**Question.** Follow-up to the unit-level analysis above, at the user's
direction: for each KNOWN real row-level error (B1-adjudicated real flag of a
high-FP rule), does another kept rule flag the SAME ROW -- not just the same
CIK-quarter?

**Method.** New `scripts/ensemble/row_level_unique_catch.py`.
`row_validation_issues.csv` keys firings by (cik, report_date, row_key, column,
value) where row_key is the positional index of the shared prepared holdings
frame, so same-row co-flagging across rules is exact within a run. Culprit rows
pinpointed by matching the verdict leaf's `observed_value` to the flagged row's
issue `value` at the unit (tol 1.0); where unmatchable, a bound is used (culprit
covered iff ALL of the rule's flagged rows at the unit are covered). Artifacts:
`data/output/ensemble/unique_catch/row_level_{detail,per_rule,summary}*`.

**Result: unit-level redundancy DISAPPEARS at row level.** Of 89 real flags:
14 not row-assessable (fmt_* weak-engine rules have no row-level artifact),
8 no longer firing on the current frame (6 of X08's 10 -- likely already
corrected), 67 assessable. Of those: 31 culprits pinpointed exactly ->
**16 are flagged by NO other kept rule on that row** (C103 3, C104 2, C107 4,
C404 3, X01 1, X07 2, X08 1); 15 are row-covered. 36 bound-only: 15 covered,
21 indeterminate. Spot-verified: row_key 459639 (0001911066@2025-06-30,
fair_value -11000, adjudicated real extraction error) carries exactly one flag
in the whole issues file: C103.

**Coverage quality is worse than it looks.** In ALL 15 pinpointed-and-covered
cases the covering rule (X02, FX01, X05, X06, C201) flags a DIFFERENT column on
the same row -- zero same-column coverage anywhere. Row-level "coverage" is
incidental co-occurrence, not a second detector of the same defect.

**Conservation is NOT a backstop for these.** The 16 definite unique culprits
are small-magnitude value/sign/extraction defects ($1K-$2.2M stored fair_value
errors: note-marker-as-value, sign flips, dash-vs-0). Against fund-level totals
($100M-$90B) all sit far below the 0.5% fv_conservation band -- the conservation
lane cannot see them. These rules are the ONLY detector in the system for
small-row extraction defects.

**Corrected implication (supersedes part 1's "kill on FP economics alone").**
Unit-level coverage only guarantees the unit enters review via some flag; it
does NOT preserve the row-level pointer. Killing these rules silently accepts
small-row extraction errors. Decision frame per rule is now: (a) keep in queue
lane if post-calibration FP is workable (X07 54%); (b) demote to TRACK_ONLY --
keeps firing into artifacts as investigator evidence, stops burning B1
adjudications -- for high-FP rules whose reals are small-magnitude (C404, C104
already there; X10, PP01 candidates); (c) replace with a source-anchored
deterministic gate where designed (C107 printed-cell gate); (d) X08: weakest
case for keeping -- 6/10 reals already corrected, 1 unique catch, 89% FP on
recal1 -- TRACK_ONLY, not deletion. Note the caught defects are real but tiny
(median well under $100K); their product impact is bounded, which is a
prioritization argument, not a correctness one.

## 2026-07-21 (part 3) - Disposition-trace diagnosis of source-only blocking rows: the parser loses NOTHING; drops are aggregate-filter and promoted-rule effects

**Question:** For each of the ~2,200 blocking source-only rows in source reconciliation
(the "parser mismatch" pool: position_like_parser_mismatch, pct_leaf_parser_mismatch,
short_plain_unresolved, unclassifiable_after_review), WHERE does production actually
lose the row: XML parsing, staging filters, unified filters, promoted agent rules, or
the reconciliation matcher itself?

**Method:** New `scripts/diagnose_parser_mismatch.py`. Stage A (DuckDB joins, no XML):
blocking rows from the per-CIK detail parquets (status=missing_from_pipeline,
blocking_issue, scoped to mechanism LIKE 'blocking%' via source_only_detail join =
2,190 rows, matching the residual-classification pool net of pipeline-only/FV-disagreement
groups) joined against (a) raw `bdc_holdings.parquet` on (cik, accession, dimensions_raw)
with identifier+period fallback, (b) unified `private_markets_holdings.csv` BDC rows on
dims and normalized identifier, (c) the global aggregate predicate
(`_sql_is_bdc_aggregate`), (d) CIKs with promoted row-removal rules applied
(`agent_fix_application_audit.csv`, rule_type in row_exclusion/dedup/comparative_period_filter,
rows_changed>0). Stage B (production-code XML replay) reserved for rows absent from raw.

**Results (artifacts: `parser_mismatch_diagnosis.csv` / `.md`):**

| Trace | Rows | CIKs | Source FV |
| --- | ---: | ---: | ---: |
| A_in_unified_recon_match_gap | 2 | 1 | 228,354,000 |
| C_dropped_aggregate_filter | 1,113 | 31 | 9,812,371,635 |
| E1_promoted_rule_exclusion_candidate | 839 | 11 | 21,005,549,300 |
| E2_dropped_raw_to_unified_unattributed | 236 | 32 | 5,088,099,192 |
| G_not_in_raw (parser loss) | **0** | 0 | 0 |

1. **The XML extraction layer loses zero blocking rows.** Every one of the 2,190 rows
   exists in raw bdc_holdings (matched on exact dimensions_raw). "Parser mismatch" is a
   misnomer: these are post-extraction disposition losses. The proposed
   selection-knob/wrapper-vocabulary work for *claiming* facts is NOT needed for this
   pool; no per-CIK axis-include or identifier-rescue capability would change it.
2. **C (1,113 rows):** identifier text matches the global aggregate predicate; the rows
   die at the aggregate filter. 867/877 pct_leaf_parser_mismatch rows are here -- the
   source-only classifier calls them position-like leaves, the aggregate filter calls
   them aggregates. Several C clusters carry negative or implausibly large FV
   (PennantPark -7.7B, Hercules 4.5B across 200 rows), consistent with many being
   GENUINE aggregates the source-only classifier fails to clear. This is a
   classifier-vs-filter boundary dispute: per cluster, either teach the source-only
   classifier to document them (blocking count falls with no data change) or fix a
   per-CIK aggregate marker (rows were real positions).
3. **E1 (839 rows, 11 CIKs, $21.0B source FV):** the row is a wrapper-certified or
   position-like leaf, in raw, NOT aggregate-matched, absent from unified -- and the CIK
   has Wave-1 promoted row-removal rules applied. Counts align with the application
   audit: KKR FS 308 blockers vs 346 promoted exclusions; New Mountain 206 vs 231;
   MidCap 193 vs 162; also Ares (40 rows, $14.8B incl. large short_plain rows), HPS,
   Antares, Fortress. **Candidate causality only (CIK-level attribution):** if confirmed
   row-level, Wave-1 conservation fixes partially deleted rows that the independent
   source reconciliation now flags as missing positions -- the delete-to-balance risk
   showing up as cross-system disagreement. Requires row-level join of each promoted
   rule predicate to these rows before any remediation decision.
4. **E2 (236 rows, 32 CIKs):** in raw, not aggregate, no promoted-rule CIK overlap,
   absent from unified; unattributed. Next attribution layer: staging bad-issuer/numeric
   filters, dedupe collapse where the surviving twin normalizes differently, unified
   tail filters. Top: Goldman Sachs BDC 72, Carlyle 31, Sixth Street 17, Prospect 13.
5. **A (2 rows):** reconciliation matcher gap is negligible -- the matcher is not the
   problem.

**Caveats:** E1 is CIK-level candidate attribution, not row-level proof. The C-bucket
attribution relies on the aggregate predicate regex matching, not an instrumented
staging replay; a few C rows could die at a later stage. blocking_issue in the detail
parquets is broader than the final source-only mechanism (4,223 vs 2,190); the extra
2,033 rows are documented_* rows and were excluded.

**Implication for remediation sequencing:** the extraction-side selection-knob plan is
unnecessary for this pool. Priority order: (1) row-level verification of E1 against the
promoted rule predicates (adjudicates the delete-to-balance question with evidence);
(2) C-bucket cluster review (cheap classifier/marker calibration, no product-data risk
on the classifier side); (3) E2 next-layer attribution.

## 2026-07-21 (part 4) - Row-level verification of Wave-1 promoted exclusions against the E1 blockers

**Question:** Of the 839 E1 rows (blocking source-only rows on CIKs with promoted
row-removal rules; part 3), which rows are actually removed by which rule predicate,
did a same-FV twin survive in unified, and does the SEC's own BDC structured dataset
(soi.tsv) render the row as an investment-axis row?

**Method:** New `scripts/verify_promoted_exclusions.py`. Replays each promoted rule's
`predicate_sql` + quarter scope in DuckDB over the E1 rows' raw bdc_holdings columns
(bdc_dimensions_raw/bdc_investment_identifier aliased; unified-only classification
columns provided as NULL and such rules reported `partial_not_evaluable_on_raw`, they
had 0 candidate rows anyway). Twin check: surviving unified BDC row at same
(cik, report_date) within $1 FV. soi.tsv check: value-based matching (filer-custom
concepts keep filer labels in soi.tsv -- e.g. KKR FV = "Initial fair value of
Investment" -- so rows match on any numeric cell within $1 + identifier-axis
compatibility). Artifacts: `verify_promoted_exclusions.csv` / `.md`.

**Results (839 rows):** 553 explained by 10 rules; 286 unexplained.

Explained highlights (rule / blocking hits / hit FV / soi_confirmed):
- KKR `exclude_exact_par_commitment_rows_2025h2`: 246 / $987M / 223 soi_confirmed.
  71% of the rule's own 346 removals are blocking. Only 1 surviving twin.
- New Mountain `exclude_newcred_lookthrough_rows`: 203 / $703M / 168 soi_confirmed
  (89% of its removals blocking). JV look-through mechanism.
- HPS `1838126_2025q4_bare_axis_leak_exclusion`: 15 / $1.22B / 11 soi_confirmed.
- Fortress `exclude_short_investment_type_axis_rows`: 21 / $228M / 16 soi_confirmed.
- MidCap `1278752_exclude_relationship_axis_duplicates`: 14 / $172M / 10 soi_confirmed.
- Antares `exclude_commitment_fair_value_rows`: 44 / net -$1.4M (zero/negative FV
  commitment rows; benign-looking).

**Attribution corrections vs part 3:** the E1 bucket was CIK-level; row level shows
286 rows / $17.5B are NOT explained by any rule predicate -- dominated by
ARES CAPITAL 40 rows / $14.76B (its only candidate rule matched 0) and MidCap 179
rows / $2.5B (rule explains only 14 of its 193). These move back to the unattributed
pool with the E2 rows; 194 of the 286 are soi_confirmed SOI rows that production
drops for a cause not yet identified. KKR also has 62 unexplained rows ($175M)
beyond its exact-par predicate.

**Twin-check caveat (selection effect):** blocking rows are by construction rows the
reconciliation could not match to ANY output row -- for duplicate-exclusion rules the
blocking subset is precisely the subset without a surviving same-FV twin, so
twin-survives ~= 0 on "duplicate" rules is expected there and does NOT by itself
refute the duplicate rationale. It does mean recon cannot see the claimed surviving
copy at the same FV for those rows (FV differs across paths, or the copy is absent).

**soi.tsv caveat:** soi.tsv derives from the same XBRL instances; `soi_confirmed`
means SEC's independent processing also renders the row as an investment-axis row
with that FV (visible to any consumer of the official dataset). It does NOT settle
funded-vs-commitment semantics; that is Phase 2 (printed SOI / commitments table
adjudication per rule mechanism).

**Phase-2 queue (semantics adjudication, per rule mechanism):** KKR exact-par
($987M; are exact-par rows unfunded commitments as the rule's residual-vs-unfunded
evidence says, or par-priced funded loans?), HPS bare-axis ($1.22B), NM NEWCRED
look-through ($703M; JV double-count question), Fortress ($228M), MidCap
relationship-axis ($172M). Plus a NEW attribution question: what drops the
Ares $14.8B and MidCap $2.5B unexplained rows (they join E2).

## 2026-07-21 (part 5) - Phase-2 semantics adjudication of the five verified promoted-exclusion rules (printed-SOI evidence)

**Question:** For the five rules row-level confirmed in part 4, were the exclusions
semantically RIGHT (rows were not fund positions) or WRONG (real funded positions
deleted)? Adjudicated against the printed schedules in cached filing HTML by five
parallel read-only agents; all verdicts quote the filings.

**Verdicts:**

1. **MidCap `1278752_exclude_relationship_axis_duplicates` -- RULE CORRECT (high).**
   The excluded relationship-axis rows are the 1940-Act affiliated/controlled
   ROLLFORWARD NOTE rows (issuer+instrument-type aggregates, e.g. "Blue Jay Transit
   Inc.,Term Loan" ending FV 22,571 = surviving tranches 20,001 + 2,570 exactly;
   2026-03-31: 22,734 = 13,491 + 1,674 + 7,569). Tranches print once in the main
   schedule; the note rows are duplicates. Safety caveat: safe only while each
   affiliated issuer's tranches also survive via main-schedule tagging.
2. **HPS `1838126_2025q4_bare_axis_leak_exclusion` -- RULE CORRECT (high).** The 15
   excluded rows ($1.22B) are the ULTRA III, LLC joint-venture NOTE portfolio
   (equity-method-investee axis `hps:ULTRAIIIMember`), including 2024 comparatives
   (excluded 242,570 = the JV note's 2024 row). The fund's real exposure is the
   retained "ULTRA III, LLC - LLC Interest" $416.2M line. Recon false alarm.
3. **New Mountain `exclude_newcred_lookthrough_rows` -- RULE CORRECT (high).**
   NEWCRED SLP I is an unconsolidated JV; its portfolio appears only in a note
   table explicitly outside the fund's Total Investments (fund holds a $48M/$68M
   membership interest, which IS retained). Xplor/Zelis never appear in the fund's
   own schedule. Recon false alarm (~$703M).
4. **Fortress `exclude_short_investment_type_axis_rows` -- RULE CORRECT (high).**
   The excluded rows are LOCAL-CURRENCY restatements of non-USD tranches from a
   footnote table ("fair value and amortized cost for non-USD denominated
   investments in local currencies"): excluded Jupiter 31,543 = CAD FMV of the
   surviving $22,981 USD row (0.7286 implied); Albion 23,122 = EUR of $27,173
   (1.1752). The ~$228M flag counts foreign-currency-unit facts as missing USD
   positions. Better guard than the axis string: fact unitRef currency.
5. **KKR `exclude_exact_par_commitment_rows_2025h2` -- MIXED: aggregate-right,
   row-level WRONG mechanism (high confidence on filing facts).** KKR prints
   unfunded commitments as rows INSIDE the schedule (footnote (i)) at commitment
   value, then nets them via contra-lines ("Unfunded Loan Commitments (446,139)" +
   "(102,885)" = 549,024 at FY2025 -- matching the rule evidence to the dollar);
   printed net TOTAL INVESTMENTS 1,608,953 (Q2) matches the post-exclusion sum
   exactly. BUT the FV=cost=principal proxy is the wrong predicate: it deleted
   confirmed FUNDED positions at par (Woolpert 32,480 funded, no (i); VIB
   30,616 funded; PSKW funded each quarter) while MISSING unfunded rows carried
   above cost (Bausch revolver 18,750/18,938; Curia 10,333/10,437). Some excluded
   rows were also comparative-period facts (excluded PSKW 28,242 = the Dec-2024
   comparative). Net totals approximately correct; position-level data and
   cross-quarter chains are damaged in 2025H2 quarters. Correct mechanism: key on
   the (i) unfunded-commitment footnote / commitments-note membership (extraction-
   side marker), not exact-par.

**Cross-cutting implication for source reconciliation:** four of the five cases are
GENERALIZABLE fact classes recon can excuse deterministically, without per-rule
coupling: (a) equity-method-investee / nonconsolidated-subsidiary axis members
(JV look-through; HPS, NM), (b) non-USD unit facts (local-currency restatements;
Fortress), (c) relationship-axis rollforward note rows whose FV equals the sum of
surviving same-issuer tranches (MidCap), (d) in-schedule unfunded-commitment rows
where the filer nets via contra-lines (KKR). These same classes are prime suspects
for the remaining unexplained pools (Ares $14.8B short_plain rows, MidCap $2.5B,
E2). Adding (a)+(b) to the source-fact staging/classifier is cheap and evidence-
backed; (d) additionally needs the (i)-footnote/contra-line capture at extraction.

**Rule actions implied:** keep MidCap/HPS/NM/Fortress rules (optionally re-mechanize
Fortress on unitRef); REPLACE the KKR rule with an unfunded-marker mechanism (B2
re-investigation with sharpened spec) -- the current rule stays aggregate-correct in
the interim but drops real funded par positions (e.g. Woolpert Q3 2025) and pollutes
position continuity.

Method note: adjudication agents worked read-only over cached HTML
(data/raw/filings/bdc_html/<cik>/<accession>.html); one file-labeling correction --
MidCap accession 0000950170-25-106526 is the 2025-06-30 10-Q, not 2025-09-30
(mechanism verified on 2025-06-30 and 2026-03-31 instead).

## 2026-07-22 (part 6) - Two evidence-class excusal mechanisms added to the source-only classifier; blocking pool 2,305 -> 2,065

**Change (production, `pipeline/source_reconciliation.py`):** two new deterministic
documented mechanisms in `build_source_only_blocker_detail`, evidence basis = the
2026-07-21 printed-SOI adjudication (part 5):

1. `documented_jv_lookthrough_axis` (SRCONLY_JV_LOOKTHROUGH_AXIS, high, non-blocking):
   source fact tagged on `investmentcompanynonconsolidatedsubsidiaryaxis` or
   `scheduleofequitymethodinvestmentequitymethodinvesteenameaxis` -- the axis itself
   declares the fact describes an unconsolidated investee vehicle's portfolio, not
   the fund's direct holding.
2. `documented_non_usd_fair_value_unit` (SRCONLY_NON_USD_FV_UNIT, high, non-blocking):
   the row's fair-value unitRef (joined from `bdc_holdings.parquet` on cik/accession/
   dimensions_raw via new `_fair_value_units_for_rows`) names a non-USD ISO code as a
   standalone token AND does not mention USD. Opaque unit ids (u001) and USD aliases
   (UNIT_STANDARD_USD_<hash>) never match; missing parquet/join = no excusal.

Also fixed: the residual classification's documented-mechanism predicate was
`startswith("documented_source_")`, which missed evidence-class names; now
`startswith("documented_")`.

**Verification:** 7 new tests in test_validate_holdings.py (2 positive per class +
4 false-positive guards: JV name in identifier text without the axis stays blocking;
USD-alias unit with code-like hash stays blocking; opaque unit stays blocking;
missing parquet stays blocking). File total 147 pass. New
`scripts/reassemble_source_recon_artifacts.py` re-assembles legacy artifacts from
cached per-CIK parquets (classifier-only changes do not dirty the reconciliation
cache -- the logic hash covers only the matching path).

**Measured effect (artifact re-assembly, no holdings/pipeline change):**
- Source-only blocking rows 2,190 -> 1,950 (-240); residual classification blocking
  rows 2,305 -> 2,065, blocking groups 461 -> 439.
- `documented_jv_lookthrough_axis`: 233 rows / $1.496B across 13 groups -- the
  New Mountain (203) and HPS (15) adjudicated sets plus 36 rows previously
  mis-bucketed in other mechanisms (category_header, issuer subtotal, short_plain,
  unclassifiable). Row conservation checks: 254 rows moved, 233 + 21 arrived.
- `documented_non_usd_fair_value_unit`: 21 rows / $228M across 3 groups -- exactly
  the adjudicated Fortress local-currency set.
- KKR's 246 exact-par rows deliberately REMAIN blocking (its rule needs
  re-mechanization on the (i)-unfunded footnote, part 5), as do the Ares $14.8B /
  MidCap unexplained pools (position_like 866 / short_plain 91 remain).

**Not done here:** classes (c) rollforward-sum and (d) unfunded-contra from part 5
(need arithmetic/extraction support, not just fact-class checks); standing
review_queue.csv still shows old counts until the next battery run.

## 2026-07-22 (part 7) - Attribution of the rule-unexplained E1 drops (Ares $14.8B solved)

**Question:** What drops the 286 blocker rows (part 4) that no promoted-rule
predicate explains -- Ares 40 rows/$14.8B, MidCap 179/$2.5B, KKR 62/$340M,
remnants?

**Method:** New `scripts/attribute_unexplained_drops.py`: extracts the company
name from each identifier (trailing-name format for MidCap "Industry Company";
first-suffixed-segment fallback for KKR "Company, Industry N"), then tests in
priority order: (A) row FV == sum of >=2 surviving unified rows for the same
company at the same (cik, report_date), within max($1k, 0.5%); (A2) same sum
test against a DIFFERENT quarter's surviving rows (rollforward begin/end
balance); (B) a single surviving row with identical FV at another quarter
(stale/comparative duplicate); (C) fv-only-concept rollforward fingerprint;
else (D). Artifacts: `unexplained_drop_attribution.csv` / `.md`.

**Results (286 rows, $17.8B raw FV):**

| Attribution | Rows | FV | Reading |
| --- | ---: | ---: | --- |
| A_issuer_subtotal_sum_match | 169 | $10.00B | issuer-group subtotal rows; tranches survive, sums exact |
| A2_subtotal_sum_match_other_quarter | 27 | $7.45B | rollforward begin/end balances (Ivy Hill mega-rows) |
| B_same_fv_other_quarter | 58 | $0.63B | comparative/stale duplicate facts (54 = KKR) |
| D_unattributed | 36 | $0.32B | residual (MidCap 23/$250M, KKR 8, North Haven 2, Antares 3) |

- **The Ares "missing $14.8B" is NOT missing data.** All 40 rows are issuer-level
  subtotal/rollforward facts (Ivy Hill Asset Management, Centric Brands group,
  etc.) whose underlying tranche rows survive in unified -- the drop is correct;
  only the reconciliation classifier could not clear them. Same class as
  MidCap's printed company-total lines (146 exact sum matches).
- **KKR's 54 B-class rows** match the part-5 finding that KKR filings embed full
  comparative schedules; the facts carry identical FVs to surviving rows of
  other quarters. B-class evidence is weaker than A/A2 (single-value
  coincidence is possible); treat as strong hint, not proof.
- **Residual D = 36 rows / $318M** -- bounded; mostly MidCap subtotal candidates
  whose tranche sets changed between quarters (sum no longer matches) plus the
  North Haven KWOR pair (its rule was not evaluable on raw columns).

**Implied recon-side fix (future):** extend the issuer-subtotal arithmetic
clearing (`documented_source_issuer_subtotal_arithmetic`) to handle (i) these
identifier formats (trailing-company and first-segment extraction), (ii)
adjacent-quarter sums for rollforward balances, and CONSIDER a review-lane (not
auto-clear) label for same-FV-other-quarter comparative aliases. With those,
the blocking pool would fall by up to ~250 further rows. Not implemented in
this pass.

## 2026-07-22 (part 8) - Global JV-axis staging drop REJECTED by evidence; the pipeline already has a retain-and-flag design the conservation engine ignores

**Question:** Should the HPS/NM JV-axis exclusions become a global staging drop
before their rule scopes expire (HPS: 2025-12-31 only; NM: through 2026-03-31)?

**Answer: NO -- and the measurement overturned the premise.** Findings:

1. **Blast radius:** unified currently carries JV-axis rows for ~14 OTHER BDCs
   (New Mountain Finance $1.1-1.6B/qtr through 2026-03-31, Bain Capital
   Specialty Finance $1.2-2.3B/qtr, Oaktree $0.4-0.5B/qtr, Blue Owl Capital
   Corp / Blue Owl Credit Income ~$1-1.7B/qtr through 2024-09-30, FS KKR
   $3.3-3.6B/qtr 2022-23, Monroe, Capital Southwest, Bain PC, AGL...).
2. **The pipeline already has a designed global treatment:** staging_bdc.py
   flags rows whose dims contain "subsidiar"/"nonconsolidatedsubsidiar" as
   `is_subsidiary=1` (11,118 rows / $90.4B across 12 CIKs), and the GAV
   reconciliation excludes them (`sum_holdings_fv_ex_sub`) -- those funds
   reconcile with residual ~0 while RETAINING the look-through rows
   position-level. A global drop would have deleted a curated feature and
   created $0.4-2.3B/qtr artificial undershoots at a dozen filers.
3. **The actual defect is referee inconsistency:** the SHADOW conservation
   engine (fv_conservation -> B1/B2 -> quarter acceptance) does NOT consult
   `is_subsidiary` anywhere; it sums all rows. That is why NM Private Credit
   and HPS overshot their anchors and the B2 loop resolved them by DELETION --
   destroying data the architecture is designed to retain+flag -- while the
   GAV referee reconciles the same funds ex-sub.
4. **Corrections to parts 5-6:** the 233 excused documented_jv_lookthrough_axis
   rows are NM Private Credit 217 + Franklin BSP 15 + FS KKR 1 -- NOT HPS.
   HPS look-through rows carry ONLY `investmentidentifieraxis=<name> <n>` in
   production dims (no equity-method axis reaches the extracted dimension
   string), so neither the recon excusal nor any axis-based global rule covers
   HPS; its handling must stay per-CIK (rule re-scope or wrapper signature).
5. **Applied (small, evidence-backed):** staging is_subsidiary predicate
   extended to `scheduleofequitymethodinvestmentequitymethodinvesteenameaxis`
   (previously unflagged: 16 NewtekOne rows 2022-09-30 / $79M; future filers
   using the axis now covered). Test added (TestSubsidiaryFlag, 6 pass).
   Materializes at the next unified rebuild.

**Decisions this raises (operator-level, not taken unilaterally):**
- (a) Should the shadow conservation engine + quarter acceptance use the
  ex-subsidiary sum (mirroring GAV recon)? This would let future NM quarters
  self-resolve via retain-and-flag with NO per-CIK rules, and would change
  conservation verdicts for JV-running funds (incl. cohort members).
- (b) If (a), the NM rule should be retired (its deletions remove rows the
  design retains) -- which ADDS the SLP look-through rows back into holdings
  as flagged rows, changing holdings artifacts and the public FV sum.
- (c) The v1 public headline FV is a straight sum of holdings (contract says
  "no reconciled overlays"); it therefore currently INCLUDES JV look-through
  rows for cohort funds that tag them (AGL $232M, Bain PC $407M at
  2026-03-31) on top of those funds' own JV-interest lines -- a double count
  in the public number. Whether to exclude is_subsidiary rows from the
  frontend export is a product decision that conflicts with the documented
  "straight GROUP BY" rule and needs an explicit call.
- (d) HPS rule re-scope (its whitelist mechanism is fragile for future
  quarters; a B2 re-investigation with a structural signature is safer).


## 2026-08-25: pct_sense_check "context-to-position pairing defect" -- resolved, no pairing defect exists

**Question:** After the pct_of_net_assets re-lane (blocker 87 -> 7 packets), 75 cik-quarters /
19,180 ledger rows remained in the warn lane as pct_sense_check divergences. The working
hypothesis (canary worker + operator reading of context-id clustering) was a
context-to-position pairing defect: declared pct facts attributed to the wrong published rows.
Is it real?

**Method:** (1) traced the published pct_of_net_assets data flow: staging_bdc.py passes the
declared fact through with scale harmonization (_pct*100), but unified_holdings.py
`_correct_pct_of_net_assets` overwrites the column for multi-entity BDCs (cik-quarter
pct_sum > 200%) with fair_value / consolidated net_assets * 100 from fund_financials.csv.
(2) Numeric test (scratch/2026-08-25_pct_pairing/verify_recompute_hypothesis.py, DuckDB):
join all pct_sense_check ledger rows -> holdings (row_id) -> fund_financials (cik, quarter),
compute |published - fv/net_assets*100|.

**Result:** 19,180 / 19,180 rows reproduce the recompute EXACTLY (max residual 0.0 pp);
all 75 quarters join. Spot check 0001803498 2025-09-30: net_assets $46.7B consolidated;
published 0.257887 = 120,534,000 / 46,739,130,000 * 100.

**Conclusion:** There is NO pairing defect. The divergences are the intentional multi-entity
consolidated-NAV correction. Sub-pattern A (close values) = positions whose filer-declared pct
was against ~the consolidated NAV; sub-pattern B (wildly-off values, high context ids) =
positions declared against small SUB-ENTITY net assets in sub-entity sections of the filing --
declared 1.59% of a feeder's NAV vs 0.0044% of consolidated NAV are both "correct" numbers
with different denominators.

**The real defect:** `_correct_pct_of_net_assets` is provenance-silent. It overwrites the
value but does not stamp `corrected_fields` (nor a transform event or source change), so the
provenance chain still claims an xbrl_field passthrough. Had it stamped corrected_fields, the
re-verifier cheap tier would have routed these rows to reason 'corrected' (weak/pass) and no
flags would ever have fired. Recommended fix (NOT applied in this investigation): stamp
`corrected_fields` += pct_of_net_assets (or a dedicated transform event, e.g.
'pct_of_net_assets:recompute_consolidated_nav') on exactly the corrected rows, leaving the
pct_sense_check lane to carry only genuinely unexplained divergences.
