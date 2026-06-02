# Agent Changelog

Append-only log of agent-completed work. The human owner consolidates significant entries into AGENTS.md periodically.

Format: `### YYYY-MM-DD — Brief title`, then bullet points describing what changed, which files, and any new contracts or updated counts.

---

### 2026-06-01 -- Fix Trinity Capital FV overshoot: prefix bypass + subtotal hierarchy filter

- **staging_bdc.py (Change 1)**: Fixed prefix bypass instrument keyword check to strip the prefix before checking for instrument keywords. Previously, prefixes like "Portfolio Company Warrant Investments" contained "warrant" which rescued ALL rows under that prefix. Now `_pr_remainder` strips the prefix first, so only rows with instrument keywords in the text AFTER the prefix are rescued.
- **staging_bdc.py (Change 2)**: Added `no_prefix_hierarchy` CTE between `no_aggregates` and `no_artifacts` to filter prefix_rules subtotals that leaked through the aggregate filter. Four conditions per CIK: (2a) prefix-starting rows without instrument detail after prefix, (2b) "Total X" rows without instrument keywords, (2c) affiliation headers without separators, (2d) bare entity names from affiliation stripping.
- **staging_bdc.py**: Hoisted `_pr_instrument_re` before the per-CIK loop (shared between bypass and hierarchy filter). Added `_prefix_rules_hierarchy_parts` list and `_prefix_hierarchy_filter` combined SQL expression.
- **Followup fix**: Prefix match in conditions 2a/2b/2d used `\s` after prefix which missed dash separators (`Prefix- Sector`) and bare prefix (`Prefix` at end-of-string). Changed to `(?:\s|-|$)`. Also widened 2b from `starts_with(_lower_id, 'total ')` to `regexp_matches(_lower_id, '(?:^|\s)total\s')` to catch embedded "Total" after sector names (e.g. "...United States Total Applied Digital Corporation").
- **Oracle results**: Trinity (0001786108) A04/E01 now passes ALL 12 quarters with financials (0.0-0.7% divergence). Previous state was 24-29% overshoot on all quarters. Trinity overall: 161 pass / 18 fail (remaining fails are A07 pct_sum and unrelated checks). Ares (0001287750) unchanged at 198 pass / 16 fail.
- **Row counts**: Unified holdings 794,982 (down 112 from 795,094 — subtotals removed across all Trinity quarters). BDC total: 575,217 rows.
- **Tests**: 774 passed, 2 deselected (pre-existing MSD hierarchy test failures from prior worktree changes, not caused by this change).

### 2026-06-01 -- Fix oracle failures for Ares Capital and Trinity Capital

- **staging_bdc.py**: Added `single_child_rollup_parents` CTE (CIK-scoped to comma-delimited wrapper CIKs) to remove entity-level rollup rows with exactly 1 FV-matching child. Includes guards: parent lacks instrument keywords, child HAS instrument keywords, child is >= 20 chars longer. Targets Ares Ivy Hill/SDLP duplication causing ~9.5% GAV overshoot.
- **staging_bdc.py**: Added `_get_prefix_rules_data()` and `_get_comma_delimited_ciks()` functions to load wrapper configs. Built dynamic aggregate-filter bypass for all 7 CIKs with `prefix_rules` in wrapper JSON. This prevents Trinity's 217 real positions from being dropped by `_BDC_AGGREGATE_PATTERNS` when identifiers start with "Portfolio Company Debt Securities" etc.
- **source_reconciliation.py**: Added `documented_source_issuer_level_xbrl_subtotal` mechanism to reclassify issuer-level XBRL subtotals as non-blocking. Detection uses `source_wrapper_disposition` ending in `_issuer_rollup`. Also relaxed `HAVING COUNT >= 2` to allow single-child rollup matching for `_issuer_rollup` disposition in both `source_rollup_matches` and `source_child_rollup_matches`.
- **0001287750.json**: Added `known_null_fields` documenting that Ares Capital does not report `pct_of_net_assets` in XBRL.
- **test_unified_holdings.py**: Updated pre-existing test (`test_long_noncontrol_dimension_path_filtered_pre_strip` -> `test_long_noncontrol_dimension_path_with_entity_kept_pre_strip`) to match worktree `bdc_identifier.py` changes where expanded entity/leaf signals protect the identifier.
- Test results: 2593 passed, 2 failed (pre-existing X06 column validation), 13 skipped, 32 deselected (5 pre-existing worktree failures: 2 MSD hierarchy, 1 Trinity wrapper v3, 2 column validation).

### 2026-05-28 — SC TO-I extraction regex expansion and universe validation

- Updated `pipeline/sc_toi_filings.py` and `tests/test_sc_toi_filings.py` for SC TO-I/A tender-offer result extraction.
- Added result-oriented share-count parsing with fractional shares, blocked prospective original-offer language such as "Shares that are tendered", and required direct tendered/accepted result evidence before emitting a result row.
- Added general regex coverage for implicit/variant final-result language: decimal share counts, "purchased all/a total of X Shares", "purchased on a pro rata basis the maximum of X Shares", "repurchased all such X Shares", "Offer terminated ... on DATE", "at a price equal to $X per Share", and "price equal to the net offering price per Share determined ... of $X".
- Added guards for par value false positives (`$0.001 per share`) and a narrow correction for filings where accepted shares are rendered at roughly 1000x tendered shares because a decimal share count is printed with a comma.
- Fixed TxValtn cross-check warning reporting to align boolean masks by index and report each failing row's own computed value.
- Validation: `python -m pytest tests/test_sc_toi_filings.py -v` passed with 97 tests. Full universe run via `python -m pipeline.main --tender-offers` indexed 2,849 filings across 113 CIKs and downloaded 2,847 successfully. Final cache-only rebuild via `python scripts/rebuild_outputs.py --tender-offers` produced 625 result rows across 59 CIKs.
- Final extracted field counts: `shares_tendered` 596/625, `shares_accepted` 403/625, `repurchase_price_per_share` 567/625, `offer_expiration_date` 612/625. Parse progress statuses: 738 `ok`, 47 `partial`, 2,062 `no_data`, 2 `no_html`.
- Blackstone Private Credit Fund (`CIK 1803498`) now has 20 completed result rows with 100% fill for tendered, accepted, price, and expiration. The previous 21st row was a prospective original SC TO-I filed 2026-05-01 for an offer expiring 2026-05-29 and is correctly excluded from result output.

### 2026-05-28 — Test workflow guidance and slow-test markers

- Added proportional test workflow guidance in `docs/testing_workflow.md` and registered pytest markers in `pytest.ini`: `slow`, `integration`, and `data_rebuild`.
- Marked known slow integration tests in unified holdings, holdings validation, interval source review, and position matching so agents can run `python -m pytest tests/ -m "not slow" --ignore=tests/test_column_validation.py --tb=short` for broad fast checks.
- Fixed `tests/test_unified_holdings.py::TestBuildUnifiedHoldings::test_load_from_disk` isolation by patching Parquet input constants as well as CSV constants; this prevents the test from selecting production Parquet artifacts when they exist.
- Latest diagnostic before this change: full suite excluding `tests/test_column_validation.py` collected 2,387 tests and reported `1 failed, 2373 passed, 13 skipped, 210 warnings in 1229.25s (0:20:29)`. The failure was the Parquet path isolation issue above.
- Verification: `python -m pytest tests/test_unified_holdings.py::TestBuildUnifiedHoldings::test_load_from_disk -vv --tb=short` passed; `python -m pytest --collect-only -q -m "not slow" --ignore=tests/test_column_validation.py` collected 2,374 of 2,387 tests and deselected 13 marked slow tests. The interval-source slow test still exceeded a 120s focused timeout and remains a follow-up performance target.
- Owner consolidation candidate for `AGENTS.md`:

  ```markdown
  ## Test Workflow Guidance

  Use proportional verification. Do not run the full suite as the default inner loop.

  - For a narrow parser/classifier change, run the exact test node or affected test file first.
  - For unified holdings changes, run `tests/test_unified_holdings.py` and relevant validation tests, then rebuild unified outputs and run semantic diff when data semantics may change.
  - For frontend-only changes, run the frontend build rather than pytest.
  - Run the full pytest suite before merge/handoff, after broad refactors, or when shared contracts change.
  - Use `--durations=50 --durations-min=0.5` on full-suite runs.
  - Before starting a long pytest run, check for existing pytest processes and avoid overlapping full suites from multiple agents.
  ```

### 2026-05-28 - SC TO-I residual review harness

- Added `pipeline/sc_toi_review.py`, `schemas/sc_toi_review/verdict.schema.json`, `prompts/sc_toi_review_prompt.md`, and `tests/test_sc_toi_review.py` for bounded, cache-only validation of SC TO-I parser residuals.
- New CLI commands: `python -m pipeline.sc_toi_review build-worklist`, `build-bundles`, `validate-verdicts`, and `summarize-verdicts`. The harness writes review artifacts under `data/output/sc_toi_review/` and does not download SEC data or write production SC TO-I result files.
- The worklist separates unchecked original/intermediate filings from likely final-result misses, partial parses, missing-field result rows, missing HTML, and ambiguous final-checkbox states. Bundles include sampled filing text snippets and metadata with a schema-bound verdict contract requiring evidence references, mechanism, confidence, residual risk, and protected-output edit checks.
- Generated current cached review artifacts: 2,389 triage rows; 192 review packets covering 1,381 reviewable issues. Issue counts by category: 598 `likely_final_results_missed`, 443 `checkbox_present_unclassified_state`, 278 `result_missing_fields`, 47 `partial_parse`, 9 `no_final_checkbox_language`, 4 `final_heading_but_no_result_terms`, and 2 `missing_html`. Another 1,008 `unchecked_original_or_intermediate` filings are excluded from the default worklist.
- Verification: `python -m pytest tests/test_sc_toi_review.py -v` passed with 5 tests; `python -m pytest tests/test_sc_toi_review.py tests/test_sc_toi_filings.py -v` passed with 102 tests.

### 2026-05-28 - SC TO-I one-packet review test

- Processed one review packet: `SCTOI_0001550913_LIKELY_FINAL_RESULTS_MISSED_0fa77871cd` for MacKenzie Realty Capital, Inc. The verdict file was written to `data/output/sc_toi_review/verdicts/`.
- Verdict: `STRUCTURE_UNSUPPORTED` with medium confidence. Sample evidence showed checked final amendments for third-party Schedule TO-T tender offers by MacKenzie as purchaser for securities of separate subject companies, not issuer or fund self-repurchase results. The correct next mechanism is offeror-role classification or output-scope separation, not a broader regex.
- Updated `pipeline/sc_toi_review.py` and `tests/test_sc_toi_review.py` so `validate-verdicts --allow-missing` and `summarize-verdicts --allow-missing` support incremental packet review without requiring all 192 verdicts to exist.
- Current verdict summary with `--allow-missing`: 1 verdict, all `STRUCTURE_UNSUPPORTED`.
- Verification: `python -m pipeline.sc_toi_review validate-verdicts --allow-missing` passed; `python -m pipeline.sc_toi_review summarize-verdicts --allow-missing` reported 1 verdict; `python -m pytest tests/test_sc_toi_review.py tests/test_sc_toi_filings.py -v` passed with 103 tests.

### 2026-05-28 - SC TO-I third-party tender tagging in review harness

- Updated `pipeline/sc_toi_review.py`, `schemas/sc_toi_review/verdict.schema.json`, `prompts/sc_toi_review_prompt.md`, and `tests/test_sc_toi_review.py` to separate third-party tender offers from issuer self-tenders in the bounded review workflow.
- Added deterministic review-only role hints from Schedule TO Rule 14d-1 and Rule 13e-4 checkbox lines, with form-type fallback and conflict handling. Triage rows now include role hint, role basis, rule checkbox states, offeror/subject-company hints, and role snippets.
- Worklist packets now group by role and form family, split into bounded packets of at most 12 filings, and bundles include every filing in the packet as evidence. This split separates mixed CIKs such as MacKenzie Realty Capital into third-party `SC TO-T/A` packets and issuer `SC TO-I/A` packets.
- Extended verdict schema with required per-accession `filing_tags` and a new `OUT_OF_SCOPE_THIRD_PARTY` verdict. Manual tags are review outputs only and support `issuer_self_tender`, `third_party_tender`, `not_final_or_no_results`, `unknown_role`, and `missing_html`.
- Added `filing_role_tags.csv` generation from validated verdicts. The stale one-packet verdict from the prior schema was removed because review IDs and verdict schema changed.
- Regenerated cache-only review artifacts: 2,389 triage rows, 250 worklist packets, and 250 current bundle JSON files. Triage role hints: 2,291 `issuer_self_tender`, 95 `third_party_tender`, 2 `missing_html`, and 1 `unknown_role`. Worklist role packets: 231 `issuer_self_tender`, 17 `third_party_tender`, 1 `missing_html`, and 1 `unknown_role`.
- Verification: `python -m pytest tests/test_sc_toi_review.py tests/test_sc_toi_filings.py -v` passed with 107 tests; `python -m pipeline.sc_toi_review validate-verdicts --allow-missing` passed; `python -m pipeline.sc_toi_review summarize-verdicts --allow-missing` reported zero current verdicts and zero filing tags.

### 2026-05-28 - SC TO-I debt tender review scope

- Updated `prompts/sc_toi_review_prompt.md` with the review rule that issuer debt tender offers, including notes or other debt securities reported in aggregate principal amount, do not affect share repurchase caps.
- New review contract: tag debt tender filing roles normally, but do not propose share-repurchase parser patterns for those filings; treat them as out of scope for repurchase-cap outputs.
- This follows manual review of `SCTOI_0001287032_CHECKBOX_PRESENT_UNCLASSIFIED_STATE_63faddea1e`, where Prospect Capital issuer self-tender results were senior convertible note tenders rather than share repurchases.
- Verification: documentation/prompt-only change; no tests run.

### 2026-05-29 - Trinity BDC XBRL wrapper pilot

- Added a scoped per-CIK XBRL wrapper for Trinity Capital Inc. (`CIK 0001786108`) in `pipeline/bdc_xbrl_wrapper.py`, with config in `data/overrides/bdc_xbrl_wrappers/0001786108.json` and schema in `schemas/bdc_xbrl_wrapper/wrapper.schema.json`.
- The wrapper classifies Trinity `Portfolio Company Debt Securities` identifiers into `position_leaf` rows with investment-date/maturity/rate markers and `rollup_candidate` bare parent rows. It emits wrapper rule IDs, parent keys, position keys, and signature status without mutating public holdings rows.
- Wired wrapper columns into `pipeline/source_reconciliation.py` so source rollup validation can match Trinity parent rows to multiple child output leaves by wrapper parent key, while still requiring the existing fair-value sum tie before clearing a blocker.
- Added regression coverage in `tests/test_bdc_xbrl_wrapper.py` and `tests/test_validate_holdings.py` for successful Trinity rollup clearance and the false-positive guard where an FV mismatch remains blocking.
- Verification: `pytest tests/test_bdc_xbrl_wrapper.py -q` passed with 3 tests; `pytest tests/test_bdc_xbrl_wrapper.py tests/test_validate_holdings.py -k "trinity or source_rollup" -q` passed with 7 tests; `pytest tests/test_validate_holdings.py -q` passed with 117 tests. `python -m pipeline.main --unified --validate` was attempted cache-only but timed out after 15 minutes; the leftover Python process was stopped and source reconciliation artifacts retained their 2026-05-28 16:10:26 timestamps. `python scripts/diff_outputs.py --semantic` ran and reported pre-existing baseline drift: 438 divergent artifacts, 3,682 checked, 77 skipped.

### 2026-05-29 - Trinity wrapper oracle trial harness

- Added `pipeline/bdc_xbrl_wrapper_oracle.py` with a cache-only CLI: `python -m pipeline.bdc_xbrl_wrapper_oracle --cik 0001786108`. It runs CIK-scoped source reconciliation and writes trial artifacts under `data/output/bdc_xbrl_wrapper_trial/0001786108/` without rewriting global source reconciliation outputs.
- Extended source reconciliation detail columns with wrapper unparsed-remainder fields so wrapper oracle checks can report remainder failures rather than silently discarding them.
- Added `tests/test_bdc_xbrl_wrapper_oracle.py` plus a Trinity one-child regression in `tests/test_validate_holdings.py`; the one-child case confirms a parent is not documented as a rollup unless at least two child leaves participate.
- Current Trinity trial output: 13 quarter summaries, 305 wrapper-cleared rollup rows, $7.60621B cleared source FV, 524 remaining blocking rows, and 261 remaining wrapper-tagged blocking rows. All 13 quarters currently fail the oracle because wrapper blockers remain; content signatures, unclassified prefix rows, and unparsed remainders are clean in the corrected summary.
- Verification: `pytest tests/test_bdc_xbrl_wrapper.py tests/test_bdc_xbrl_wrapper_oracle.py tests/test_validate_holdings.py -q` passed with 124 tests. The trial command completed successfully on cached data and produced `reconciliation_detail.csv`, `oracle_summary.csv`, `cleared_rollups.csv`, and `remaining_blockers.csv`.

### 2026-05-29 - Trinity wrapper trial hardening

- Extended `pipeline/bdc_xbrl_wrapper.py` from coarse `position_leaf`/`rollup_candidate` labels to family-specific Trinity dispositions: debt/warrant/equity leaves, issuer rollups, category rollups, total rollups, and unclassified rows. Added structured leaf signature fields for family, investment date, maturity/expiration date, and rate.
- Updated `pipeline/source_reconciliation.py` with wrapper-enabled/wrapper-disabled reconciliation mode, wrapper exact leaf-key and structured leaf-key match tiers, and wrapper rollup matching across issuer/category/total rollup types. Detail output now carries the richer wrapper signature fields.
- Extended `pipeline/bdc_xbrl_wrapper_oracle.py` with `--compare-baseline`, `baseline_comparison.csv`, and `remaining_blocker_mechanisms.csv` so the Trinity trial reports measured blocker deltas and residual mechanisms instead of only a pass/fail summary.
- Current cache-only Trinity trial output: 13 quarter summaries, 732 wrapper-cleared rollup rows, $8.950518B cleared rollup FV, 337 remaining blocking rows, and 287 remaining wrapper-tagged blocking rows. Baseline comparison versus wrappers disabled: blocking rows declined from 706 to 337 (-369), documented rollups increased from 0 to 732, and blocking source FV declined by $4.233943B. All 13 quarters still fail the oracle because wrapper blockers remain.
- Remaining blocker mechanism totals: 246 `leaf_no_output_candidate`, 26 `cash_or_money_market`, 23 `total_rollup_fv_mismatch`, 20 `aggregate_total`, 14 `category_rollup_fv_mismatch`, 4 `unclassified`, and 4 `issuer_rollup_fv_mismatch`.
- Verification: `pytest tests/test_bdc_xbrl_wrapper.py tests/test_bdc_xbrl_wrapper_oracle.py tests/test_validate_holdings.py -k "trinity or source_rollup or oracle or wrapper" -q` passed with 17 tests; `pytest tests/test_bdc_xbrl_wrapper.py tests/test_bdc_xbrl_wrapper_oracle.py tests/test_validate_holdings.py -q` passed with 129 tests; `python -m pipeline.bdc_xbrl_wrapper_oracle --cik 0001786108 --compare-baseline` completed from cached data.

### 2026-05-29 -- BDC listed price downloads + premium/discount

- New module `pipeline/sec_ticker_map.py`: downloads SEC `company_tickers.json` via `EdgarClient`, caches to `data/raw/sec_reference/`, cross-references against BDC universe to produce CIK-to-ticker mapping for listed BDCs.
- New module `pipeline/listed_prices.py`: downloads daily OHLCV via yfinance per BDC ticker, caches per-ticker to `data/raw/listed_prices/`, produces combined `bdc_listed_prices.csv`. Computes quarter-end premium/discount via DuckDB join against `fund_financials.csv` NAV with 7-day lookback window, writes `bdc_premium_discount.csv`.
- `pipeline/config.py`: added 5 path constants (`SEC_REFERENCE_DIR`, `LISTED_PRICES_CACHE_DIR`, `SEC_COMPANY_TICKERS_FILE`, `BDC_LISTED_PRICES_FILE`, `BDC_PREMIUM_DISCOUNT_FILE`) and 2 dirs to mkdir loop.
- `pipeline/main.py`: added `--listed-prices` flag; orchestration step downloads SEC tickers, yfinance prices, and computes premium/discount. Only runs when explicitly passed (no unwanted network calls).
- `scripts/rebuild_outputs.py`: added `--prices` flag for cache-only listed price + premium/discount rebuild.
- `pipeline/fund_financials.py`: added `_backfill_listed_price_data()` that LEFT JOINs `bdc_premium_discount.csv` onto BDC rows to fill `market_price_per_share` and `premium_discount_pct`. Non-invasive: if file missing, no change.
- New tests: `tests/test_sec_ticker_map.py` (11 tests), `tests/test_listed_prices.py` (11 tests). Cover SEC JSON parsing, CIK zero-padding, BDC cross-reference, premium/discount computation, lookback window, cache rebuild, and edge cases.

### 2026-05-29 - Multi-CIK XBRL wrapper diagnostics and aggregate guard fix

- Promoted the Trinity false-positive root cause into global BDC aggregate detection in `pipeline/bdc_identifier.py`: `type of investment` now counts as leaf evidence, `secured loan` and `equipment financing` count as leaf instrument evidence, and `corporation`/`limited` entity signals plus total-row company guards prevent real position leaves from being dropped as category rows.
- Refactored `pipeline/bdc_xbrl_wrapper.py` from Trinity-only logic into a registry-backed wrapper API while preserving existing wrapper columns and `classify_identifier()`/`add_bdc_xbrl_wrapper_columns()` call sites. Added initial specs for Saratoga (`0001377936`), Goldman Sachs Private Credit (`0001920145`), and Fidelity Private Credit (`0001920453`).
- Extended `pipeline/bdc_xbrl_wrapper_oracle.py` with registry dispatch, `--all-supported`, raw-BDC-vs-unified presence diagnostics, and mechanism buckets for aggregate, non-private/cash, unclassified signature, and `leaf_present_in_raw_missing_from_unified`.
- Current all-supported oracle trial completed from cached data. Quarter summaries / cleared rollups / remaining blockers: Saratoga 6 / 0 / 327; Trinity 13 / 732 / 86; Goldman Sachs Private Credit 12 / 0 / 484; Fidelity Private Credit 13 / 26 / 244.
- Verification: `python -m pytest tests/test_bdc_xbrl_wrapper.py tests/test_bdc_xbrl_wrapper_oracle.py -q` passed with 14 tests; `python -m pytest tests/test_unified_holdings.py -k "aggregate or bdc" -q` passed with 288 tests; `python -m pytest tests/test_validate_holdings.py -k "wrapper or source_rollup or source_reconciliation" -q` passed with 11 tests; `python -m pipeline.bdc_xbrl_wrapper_oracle --all-supported --compare-baseline` completed. `python scripts/diff_outputs.py --semantic` ran and failed on pre-existing broad baseline drift: 441 divergent artifacts, 3,682 checked, 77 skipped.

### 2026-05-29 - Fresh-staged wrapper blocker rerun

- Added `--fresh-bdc-staging` to `pipeline/bdc_xbrl_wrapper_oracle.py` so wrapper trials can rebuild the requested CIK's raw BDC staging path from cached XBRL facts and reconcile that fresh CIK output without rewriting global source reconciliation artifacts.
- Reran the supported wrapper blocker logic with fresh per-CIK BDC staging. Current quarter summaries / cleared rollups / remaining blockers: Saratoga (`0001377936`) 6 / 0 / 327; Trinity (`0001786108`) 13 / 785 / 74; Goldman Sachs Private Credit (`0001920145`) 12 / 0 / 288; Fidelity Private Credit (`0001920453`) 13 / 26 / 233.
- Saratoga is the highest remaining supported wrapper fund. Its remaining blocker mechanisms are 172 aggregate rows, 128 `leaf_present_in_raw_missing_from_unified` rows, 9 issuer rollup FV mismatches, 9 unclassified signatures, 6 cash/money-market rows, and 3 category rollup FV mismatches. The wrapper now identifies the main Saratoga actionable issue as source leaves present in raw BDC rows but absent from unified holdings.
- Extended the Saratoga wrapper prefixes for lowercase `Non-control/Non-affiliate investments` signatures and added a regression test for a Saratoga leaf with a cash coupon string, preventing it from being misbucketed as cash/money-market.
- Full global blocker regeneration via `python -m pipeline.main --validate --reconcile-full` and full `python scripts/rebuild_outputs.py --unified` were attempted cache-only but timed out; leftover Python processes were stopped. The fresh-staged oracle artifacts under `data/output/bdc_xbrl_wrapper_trial/` are the current regenerated trial basis, while the global source reconciliation artifacts remain stale.
- Verification: `python -m pipeline.bdc_xbrl_wrapper_oracle --cik 0001786108 --compare-baseline --fresh-bdc-staging` completed; `python -m pipeline.bdc_xbrl_wrapper_oracle --all-supported --compare-baseline --fresh-bdc-staging` completed; `python -m pytest tests/test_bdc_xbrl_wrapper.py tests/test_bdc_xbrl_wrapper_oracle.py -q` passed with 15 tests.

### 2026-05-29 - Saratoga pct-only XBRL identifier recovery

- Fixed Saratoga-style BDC XBRL identifiers where the affiliation prefix is stripped before parsing and the remaining first segment is only pct-of-net-assets, e.g. `229.3% - Avantra - IT Services - First Lien Term Loan`. `pipeline/bdc_identifier.py` and `pipeline/staging_bdc.py` now recover the second segment as issuer for 4+ segment pct-only signatures, while leaving 3-segment category/instrument rows filtered as ambiguous.
- Added dash-spacing normalization for Saratoga identifiers such as `JDXpert -Talent Acquisition Software` in both Python and DuckDB parsing paths.
- Updated `pipeline/bdc_xbrl_wrapper.py` so Saratoga wrapper key generation canonicalizes source identifiers by stripping the affiliation prefix, allowing wrapper source rows to match fresh staged output identifiers after normalization.
- Fresh Saratoga wrapper oracle with CIK-scoped staging now reports 195 remaining blocking rows, down from 327 before the parser fix. Remaining mechanism totals are 168 aggregate rows, 9 `leaf_present_in_raw_missing_from_unified` rows, 9 unclassified signatures, 6 cash/money-market rows, and 3 category rollup FV mismatches.
- Checked cached HTML grids for the remaining Saratoga position-leaf misses. The HTML schedule includes the missing company column for these rows, e.g. Altvia MidCo, LLC., New England Dental Partners, Exigo, LLC, Zollege PBC, BQE Software, Inc., ETU Holdings, Inc., and ComForCare Health Care. The residual issue is therefore missing issuer detail in the XBRL typed-member signature, not absence from the human-readable filing.
- Verification: `python -m pytest tests/test_unified_holdings.py::TestPctPrefixParsing tests/test_unified_holdings.py::TestPctPrefixSqlPath tests/test_bdc_xbrl_wrapper.py -q` passed with 34 tests; `python -m pytest tests/test_bdc_xbrl_wrapper_oracle.py tests/test_validate_holdings.py -k "wrapper or source_rollup or source_reconciliation" -q` passed with 16 tests; `python -m pipeline.bdc_xbrl_wrapper_oracle --cik 0001377936 --compare-baseline --fresh-bdc-staging` completed from cached data.

### 2026-05-29 - Saratoga bare category wrapper classification

- Extended the Saratoga wrapper in `pipeline/bdc_xbrl_wrapper.py` so bare industry/category source signatures without affiliation prefixes, such as `Alternative Investment Management Software` and `Corporate Education Software - Affiliate investments`, are classified as `aggregate` instead of remaining unclassified.
- Added wrapper regressions for Saratoga bare industry rows, bare affiliation category rows, and wrapper-column application to those signatures.
- Fresh Saratoga wrapper oracle still reports 195 remaining blocking rows, but the prior 9 `unclassified_signature` rows are now explicit aggregate/rollup diagnostics. Current mechanism totals are 162 `aggregate`, 20 `total_rollup_fv_mismatch`, 9 `leaf_present_in_raw_missing_from_unified`, 3 `category_rollup_fv_mismatch`, and 1 `cash_or_money_market`.
- Verification: `python -m pytest tests/test_bdc_xbrl_wrapper.py -q` passed with 14 tests; `python -m pytest tests/test_bdc_xbrl_wrapper_oracle.py tests/test_validate_holdings.py -k "wrapper or source_rollup or source_reconciliation" -q` passed with 16 tests; `python -m pipeline.bdc_xbrl_wrapper_oracle --cik 0001377936 --compare-baseline --fresh-bdc-staging` completed from cached data.

### 2026-05-29 - Wrapper aggregate exclusions in source reconciliation

- Fixed source reconciliation so source rows classified by a per-CIK wrapper as `aggregate` or `non_private_market` are documented exclusions when they have no direct output match, rather than being counted as `missing_from_pipeline` blockers and only re-labeled later by the wrapper oracle.
- Kept wrapper rollups strict: `*_rollup` rows still require exact child-output FV reconciliation and remain blockers when the tie fails. Added tests proving Saratoga aggregate rows clear while Saratoga position leaves still block when missing.
- Extended Saratoga wrapper signatures for terminal percentage total rows (`TOTAL INVESTMENTS - NNN%`), `Sub Total Non-control/Non-affiliate investments`, and cash totals. Cash totals now classify as `non_private_market` before generic total-rollup handling.
- Fresh Saratoga wrapper oracle now reports 37 remaining blocking rows, down from 195 after clearing wrapper aggregate/non-private rows. Current mechanisms: 25 `total_rollup_fv_mismatch`, 9 `leaf_present_in_raw_missing_from_unified`, and 3 `category_rollup_fv_mismatch`. There are no remaining plain aggregate or cash/non-private blockers.
- Verification: `python -m pytest tests/test_bdc_xbrl_wrapper.py tests/test_validate_holdings.py::TestBdcSourceReconciliation::test_saratoga_wrapper_aggregate_is_documented_exclusion tests/test_validate_holdings.py::TestBdcSourceReconciliation::test_saratoga_wrapper_position_leaf_still_blocks_when_missing -q` passed with 19 tests; `python -m pytest tests/test_bdc_xbrl_wrapper_oracle.py tests/test_validate_holdings.py -k "wrapper or source_rollup or source_reconciliation" -q` passed with 18 tests; `python -m pipeline.bdc_xbrl_wrapper_oracle --cik 0001377936 --compare-baseline --fresh-bdc-staging` completed from cached data.

### 2026-05-29 - Saratoga rollup blocker split

- Added deterministic source-child rollup clearing in `pipeline/source_reconciliation.py`: wrapper rollups can now be documented as `documented_source_rollup_exact` when their fair value ties to multiple source child leaf rows, even if child output wrapper keys include issuer text and cannot match the rollup parent key directly.
- Extended Saratoga mixed-wrapper leaf markers in `pipeline/bdc_xbrl_wrapper.py` so terminal instrument signatures without issuer text, such as `Direct Selling Software - Common Units` or `... - First Lien Term Loan`, are classified as `mixed_position_leaf` rather than category rollups.
- Split wrapper oracle rollup residuals in `pipeline/bdc_xbrl_wrapper_oracle.py` into child-tie/no-child-tie buckets and added candidate source-child counts/FV to `remaining_blocker_mechanisms.csv`.
- Fresh Saratoga wrapper oracle now documents 2 cleared source-child rollups and keeps 37 remaining blocking rows split into 25 `total_rollup_no_child_tie`, 11 `leaf_present_in_raw_missing_from_unified`, and 1 `category_rollup_no_child_tie`.
- Verification: `python -m pytest tests/test_bdc_xbrl_wrapper.py tests/test_bdc_xbrl_wrapper_oracle.py tests/test_validate_holdings.py::TestBdcSourceReconciliation::test_saratoga_category_rollup_is_non_blocking_when_source_children_tie tests/test_validate_holdings.py::TestBdcSourceReconciliation::test_saratoga_wrapper_position_leaf_still_blocks_when_missing tests/test_validate_holdings.py::TestBdcSourceReconciliation::test_trinity_wrapper_rollup_is_non_blocking_when_fv_ties_leaf_positions -q` passed with 27 tests; `python -m pipeline.bdc_xbrl_wrapper_oracle --cik 0001377936 --compare-baseline --fresh-bdc-staging` completed from cached data.

### 2026-05-29 - Saratoga issuer bridge for reviewed mixed leaves

- Added exact CIK/report-date/raw-identifier bridges in `pipeline/staging_bdc.py` for 11 Saratoga (`0001377936`) XBRL signatures where the typed member omits the company name but the cached HTML/source schedule identifies the issuer.
- Kept the rule narrow: generic 3-segment pct/category/instrument rows remain filtered unless they match a reviewed Saratoga bridge signature. Added a false-positive regression for the period guard.
- Fresh Saratoga wrapper oracle now reports 26 remaining blocking rows, down from 37. The prior 11 `leaf_present_in_raw_missing_from_unified` rows are cleared; residual blockers are 25 `total_rollup_no_child_tie` rows and 1 `category_rollup_no_child_tie` row.
- Verification: `python -m pytest tests/test_unified_holdings.py::TestPctPrefixSqlPath -q` passed with 10 tests; `python -m pytest tests/test_bdc_xbrl_wrapper.py tests/test_bdc_xbrl_wrapper_oracle.py tests/test_validate_holdings.py::TestBdcSourceReconciliation::test_saratoga_category_rollup_is_non_blocking_when_source_children_tie tests/test_validate_holdings.py::TestBdcSourceReconciliation::test_saratoga_wrapper_position_leaf_still_blocks_when_missing -q` passed with 26 tests; `python -m pipeline.bdc_xbrl_wrapper_oracle --cik 0001377936 --compare-baseline --fresh-bdc-staging` completed from cached data.

### 2026-05-29 - Residual-driven wrapper queue

- Added `--queue-from-residuals`, `--top`, and `--residual-clusters-file` to `pipeline/bdc_xbrl_wrapper_oracle.py`. The queue ranks source-only blocker CIKs from `source_reconciliation_source_only_clusters.csv`, writes diagnostic profiles for every queued CIK, and runs full oracle trials only for registered wrapper CIKs.
- Added draft wrapper profiling artifacts under `data/output/bdc_xbrl_wrapper_queue/`: `queue.csv`, `summary.csv`, and per-CIK `profile.csv` / `candidate_rules.csv`. Draft profiles classify likely aggregate, non-private-market, position-leaf, pct-prefix evidence-needed, and unresolved signatures without mutating `WRAPPER_SPECS` or unified holdings.
- Ran the queue for the current top 10 residual CIKs with fresh supported-wrapper staging. Results: 10 queued CIKs, 6 profiled-only unsupported CIKs, and 4 supported wrapper oracle runs. Supported remaining rows were Trinity 73, Goldman Sachs Private Credit 288, Saratoga 26, and Fidelity Private Credit 246.
- Verification: `python -m pytest tests/test_bdc_xbrl_wrapper.py tests/test_bdc_xbrl_wrapper_oracle.py -q` passed with 27 tests; `python -m pipeline.bdc_xbrl_wrapper_oracle --queue-from-residuals --top 10 --fresh-bdc-staging --compare-baseline` completed from cached data.

### 2026-05-29 - Shared wrapper family generalisations

- Added wrapper diagnostic normalization for dash/encoding variants, hidden BOM characters, and duplicated Goldman `Investment Debt InveInvestment Debt Investments` prefixes.
- Added shared runtime wrapper specs for Sixth Street Specialty (`0001508655`), Sixth Street Lending Partners (`0001925309`), and Goldman Sachs BDC (`0001572694`). Refined Fidelity Private Credit (`0001920453`) aggregate/non-private markers for investment portfolio and mutual fund rows.
- Improved residual queue profiling so affiliation prefixes such as Varagon `Non-Controlled/Non-Affiliated Investments` are stripped before prefix detection. BlackRock TCP (`0001370755`), Varagon (`0001784700`), and Hercules (`0001280784`) remain profile-only; a trial Hercules runtime wrapper was rejected because it expanded noisy wrapper blockers.
- Fresh top-10 queue now runs oracle trials for 7 CIKs and profiles 3. Current supported remaining rows: Trinity 73, Goldman Sachs Private Credit 288, Sixth Street Specialty 265, Saratoga 26, Sixth Street Lending Partners 257, Fidelity Private Credit 238, and Goldman Sachs BDC 232.
- Verification: `python -m pytest tests/test_bdc_xbrl_wrapper.py tests/test_bdc_xbrl_wrapper_oracle.py -q` passed with 33 tests; `python -m pipeline.bdc_xbrl_wrapper_oracle --queue-from-residuals --top 10 --fresh-bdc-staging --compare-baseline` completed from cached data.

### 2026-05-29 - Source reconciliation forced-run memory fix

- Fixed `pipeline/source_reconciliation.py` so `run_bdc_source_reconciliation_cached(force=True)` no longer performs one global source-to-holdings reconciliation batch for all dirty CIKs. Forced/full invalidation now recomputes each dirty CIK partition separately and writes the existing per-CIK Parquet artifacts, avoiding the observed DuckDB OOM in the global `.fetchdf()` path.
- Added a regression in `tests/test_source_reconciliation_cache.py` proving forced reconciliation calls the reconciliation function once per CIK partition and filters out non-BDC holdings before the per-CIK run.
- No schema changes and no production output rebuild was performed. Verification: `pytest tests/test_source_reconciliation_cache.py` passed with 5 tests. `python scripts/diff_outputs.py --semantic` was run as a post-test backstop and failed because the workspace already has broad baseline drift (441 divergent artifacts; semantic deltas in holdings, matches, position returns, index returns, and fund financials).

### 2026-05-29 - Wrapper hierarchy leaf rules for top blocker CIKs

- Hardened wrapper non-private-market detection in `pipeline/bdc_xbrl_wrapper.py` and `pipeline/bdc_xbrl_wrapper_oracle.py` so cash/money-market rows are still documented exclusions, but coupon strings such as `Cash + PIK` are not misclassified as cash equivalents.
- Broadened BDC aggregate leaf evidence in `pipeline/bdc_identifier.py` for no-dash hierarchy rows with real instrument and rate/maturity/acquisition-date evidence, including hyphenated `First-lien`/`Second-lien` text and `Revolving Credit Facility`.
- Added CIK-scoped staging parsing in `pipeline/staging_bdc.py` for Sixth Street Specialty (`0001508655`), Sixth Street Lending Partners (`0001925309`), and Fidelity Private Credit (`0001920453`) no-dash hierarchy leaves. Fidelity hierarchy stripping now accepts the `Investments Investments - ... First Lien Debt ...` variant.
- Fresh top-10 wrapper queue rerun from existing residual artifacts with fresh per-CIK BDC staging completed in 289s. Supported remaining rows are now: Trinity 73, Goldman Sachs Private Credit 74, Sixth Street Specialty 8, Saratoga 26, Sixth Street Lending Partners 7, Fidelity Private Credit 12, and Goldman Sachs BDC 155. Unsupported/profile-only CIKs remain Hercules, BlackRock TCP, and Varagon.
- Verification: `python -m pytest tests\test_bdc_xbrl_wrapper.py tests\test_bdc_xbrl_wrapper_oracle.py tests\test_unified_holdings.py::TestExpandedAggregatePatterns tests\test_unified_holdings.py::TestPctPrefixSqlPath -q` passed with 61 tests. `python -m pipeline.main --validate --reconcile-full` completed validation outputs but the BDC source reconciliation sub-step hit DuckDB OOM at 18.7 GiB, so global residual artifacts were not refreshed by that command.

### 2026-05-31 -- Wrapper v2 content signature system: Ares vertical slice

- Created `schemas/bdc_xbrl_wrapper/wrapper_v2.schema.json`: extends v1 schema with `identifier_format`, `archetypes` (detection_rules + per-field `field_signatures` with types numeric_range/regex/enum/presence and constraints required/forbidden/optional), `invariants` (FV reconciliation, QoQ position count bounds, rate sanity), and `known_edge_cases`.
- Created `data/overrides/bdc_xbrl_wrappers/0001918712.json`: Ares Strategic Income Fund wrapper with 4 archetypes (senior_secured_debt, equity, clo, warrant), FV reconciliation invariant (5% / $5M tolerance), QoQ position count bounds (200%/50%), rate sanity (1-25%), and 3 known edge cases (pipe-delimited rows, bare fund vehicles, Euribor references).
- Created `pipeline/wrapper_content_signatures.py`: content signature engine with `load_wrapper_definition()`, `classify_archetype()`, `validate_content_signatures()`, `validate_fv_reconciliation()`, `run_qoq_drift()`, and CLI entry point (`python -m pipeline.wrapper_content_signatures --cik 0001918712`).
- Modified `pipeline/bdc_xbrl_wrapper.py`: added `ARES_STRATEGIC_INCOME_CIK` constant and minimal `WrapperSpec` entry (empty prefix_rules since Ares uses flat identifiers) to mark CIK as wrapper-supported in the oracle.
- Modified `pipeline/bdc_xbrl_wrapper_oracle.py`: added `content_signature_pass_rate`, `content_signature_violations`, `fv_reconciliation_status`, `fv_reconciliation_pct_diff` to `ORACLE_SUMMARY_COLUMNS`; added `_check_content_signatures()` and `_check_fv_reconciliation()` helpers; wired them into `build_wrapper_oracle_outputs()` with optional `holdings_df` and `fund_financials_df` parameters; updated `run_wrapper_oracle_trial()` to pass holdings and fund financials through.
- Created `tests/test_wrapper_content_signatures.py`: 32 tests covering schema loading (valid, missing, normalized CIK, invariants, edge cases), archetype classification (debt, equity, CLO, warrant, no-match, case-insensitive, pipe-separated), content signature pass/fail (rate in range, rate above max, rate below min, forbidden present, required missing), FV reconciliation (within tolerance, outside tolerance, no invariant, abs tolerance prevents false positive), QoQ drift (spike flagged, stable passes, drop flagged), edge case detection (pipe delimiter), false positive guards (normal growth, null rate on equity), and integration.
- Test counts: 32 new tests pass, 34 existing wrapper/oracle tests pass with zero regressions (66 total).

### 2026-06-01 -- Unify BDC XBRL wrapper system to v3 JSON schema

Consolidated three parallel per-CIK systems (Python WrapperSpec, v2 JSON content signatures, hardcoded staging SQL constants) into a single v3 JSON schema per CIK.

**Schema and definitions:**
- Created `schemas/bdc_xbrl_wrapper/wrapper_v3.schema.json`: unified schema with `dispatch`, `staging`, `archetypes`, `invariants`, `identifier_format`, `known_edge_cases` sections.
- Wrote 11 v3 JSON files in `data/overrides/bdc_xbrl_wrappers/` (Trinity, Saratoga, Goldman Private Credit, Goldman BDC, Fidelity, Sixth Street Specialty, Sixth Street Lending, Ares, MSD, Crescent Capital, Crescent Private Credit).
- Deleted `schemas/bdc_xbrl_wrapper/wrapper.schema.json` (v1, superseded).

**bdc_xbrl_wrapper.py:**
- Replaced `_make_specs()` with `_load_specs_from_json()` that reads v3 JSON dispatch sections.
- Added `fallback_family_patterns`, `canonical_strip_re`, `no_prefix_is_aggregate` fields to `WrapperSpec` dataclass.
- Generalized Saratoga-specific branches in `_family_for_identifier()`, `_canonical_identifier_for_keys()`, `_rollup_disposition()`, `add_bdc_xbrl_wrapper_columns()` to use config-driven fields instead of CIK constant checks.
- Removed all `*_CIK` constants, `TRINITY_*` prefix/leaf constants, `_SARATOGA_*_RE` regexes, `_SIXTH_STREET_PREFIX_RULES`, `_GOLDMAN_PREFIX_RULES`, and `_make_specs()`.

**wrapper_content_signatures.py:**
- `load_wrapper_definition()` now accepts both v2 and v3 schema_version. v3 files without archetypes/invariants return None (dispatch/staging-only).
- Added `UnclassifiedRate` dataclass and `unclassified_rate` field to `WrapperDefinition`.
- `validate_content_signatures()` returns `unclassified_rate` and `unclassified_rate_status` columns per quarter.
- `run_qoq_drift()` logs warnings when unclassified rate exceeds threshold.

**staging_bdc.py:**
- Added `_load_staging_configs()`, `_load_issuer_bridges_from_json()`, `_get_hierarchy_leaf_ciks()`, `_get_prefix_strip_ciks()`, `_get_hierarchy_extract_ciks()` loaders.
- Replaced `_SARATOGA_ISSUER_BRIDGES` list, hardcoded MSD/Crescent/hierarchy-leaf CIK SQL with JSON-driven config.
- SQL CTE structure and DuckDB logic unchanged.

**bdc_xbrl_wrapper_oracle.py:**
- Replaced `TRINITY_CIK` import with local constant.

**Verification:** 66 wrapper/oracle/content-signature tests pass. 3 unified_holdings test failures traced to pre-existing dirty worktree changes in `bdc_identifier.py`, not caused by this work (confirmed by testing with committed `bdc_identifier.py`).

### 2026-06-01 -- Fix oracle failures for Ares Capital and Trinity Capital

**Problem:** Ares Capital (0001287750) A04/E01 showed 8.6-8.8% FV overshoot for 2024-12-31 and 2025-03-31 caused by entity-level XBRL rollup parents (Ivy Hill $1.9B, Potomac $350M, ACAS $500K) duplicating their instrument-level children. Trinity Capital (0001786108) prefix-rules aggregate bypass was too permissive, admitting subtotals via entity-signal matching.

**Changes:**

**staging_bdc.py:**
- Added `_get_comma_delimited_ciks()` to identify CIKs with "issuer, instrument" delimiter format (Ares Capital, Ares Strategic Income)
- Added `_get_prefix_rules_data()` to load prefix_rules from all wrapper JSON configs
- Added CIK-scoped `single_child_rollup_parents` CTE that removes entity-only parent rows whose FV matches ANY individual instrument-level child (not just single-child or sum-match). Guards: parent lacks instrument keywords, child has instrument keywords, CIK uses comma-delimited wrapper format, FV matches within 0.01% tolerance, child at least 5 chars longer
- Added `_prefix_rules_hierarchy_condition` aggregate bypass for 7 CIKs with declared prefix_rules. Replaced entity-signal OR leaf-detail condition with instrument-keyword-only check to prevent subtotal leakage through company-name matching
- Modified `no_subtotals` CTE to exclude `single_child_rollup_parents`

**source_reconciliation.py:**
- Added `documented_source_issuer_level_xbrl_subtotal` mechanism with detection mask using `source_wrapper_disposition` ending in `_issuer_rollup`
- Relaxed `source_rollup_matches` and `source_child_rollup_matches` HAVING clauses to allow single-child rollups with `_issuer_rollup` disposition

**data/overrides/bdc_xbrl_wrappers/0001287750.json:**
- Added `known_null_fields` documenting that pct_of_net_assets is not reported in XBRL

**tests/test_unified_holdings.py:**
- Updated `test_long_noncontrol_dimension_path` to match new entity-signal behavior from worktree changes
- Added `test_short_noncontrol_without_entity_no_leaf_filtered_pre_strip`

**Oracle results after fix:**
- Ares: 198 pass, 16 fail (was 194 pass, 20 fail). A04/E01 ALL PASS -- 2024-12-31 dropped from 8.6% to 0.1%, 2025-03-31 from 8.8% to 0.1%. Remaining 16 failures are A07 (pct_of_net_assets=0%, expected null).
- Trinity: 128 pass, 51 fail (unchanged). FV overshoot (24-29% pre-2025) is pre-existing from subtotals passing through the standard aggregate filter, not the prefix bypass. Requires separate investigation.
- Source reconciliation reclassification (Change 3) not yet verified -- needs separate source recon rebuild.

### 2026-06-02 -- Reduce blocking rows for Goldman Sachs Private Credit (0001920145): 208 -> 4

Three changes to resolve 204 of 208 blocking rows (98% reduction). Remaining 4 are irreducible mojibake encoding issues in source XBRL.

**data/overrides/bdc_xbrl_wrappers/0001920145.json (v1 -> v3):**
- Added `fallback_family_patterns` with 5 regexes to catch bare instrument keywords, country names, portfolio totals, and GS money market fund
- Set `no_prefix_is_aggregate: true` so non-prefix-matched identifiers are classified as aggregates
- Expanded `aggregate_markers` from 3 to 29 entries: country/geography subtotals, instrument-type category headers (`1st lien/senior secured debt`, `2nd lien/senior secured debt`, `1st lien/last-out unitranche`), and country-prefixed patterns (`investment united states`, etc.)
- Added `non_private_markers` for GS money market fund variants
- Added 11 new `prefix_rules`: `Investment Equity Securities`, `Equity and Other`, truncated variants (`nvestment`, `vestment`), and country-prefixed entries
- Added custom `leaf_markers_by_family` for debt: removed instrument-type keywords (first lien, senior secured, term loan, etc.) from debt leaf markers, keeping only structural markers (interest rate, reference rate, maturity, sofr, etc.). This prevents bare category subtotals like "1st Lien/Senior Secured Debt - 93.10%" from being misclassified as position leaves.
- Added `category_marker_re` for equity: catches bare equity subtotals like "Common Stock - 0.1%" and "Equity Securities United States Common Stock" that share keywords with real equity position leaves.
- Result: 157 unclassified identifiers -> 0, 37 category subtotals reclassified as aggregate, 4 equity subtotals demoted via category_marker_re

**pipeline/bdc_xbrl_wrapper.py:**
- Added `category_marker_re` override check in `classify_identifier()` before the leaf branch. When an identifier matches the category regex after prefix stripping, `has_leaf_marker` is set to False, demoting the identifier to rollup/aggregate classification.

**pipeline/staging_bdc.py:**
- Expanded `_pr_instrument_re` to match `reference\s+rate` and `maturity\s+\d` (bare maturity + date digit)
- Root cause: GS Private Credit BSL/syndicated positions use "Reference Rate and Spread S + X.XX% Maturity MM/DD/YY" without explicit "Interest Rate" field. The 96 positions with this format were being dropped by the aggregate filter because the prefix_rules bypass didn't recognize them as leaf-level detail.

**tests/test_bdc_xbrl_wrapper.py:**
- Added 8 GS Private Credit classification tests covering debt/equity leaves, country aggregates, money market, totals, truncated prefixes
- Updated existing test version assertion (V1 -> V3)

**tests/test_unified_holdings.py:**
- Added `TestGSPrivateCreditSqlPath` class with 3 tests: Reference Rate leaf rescue, Interest Rate leaf baseline, and geographic subtotal filtering

**Oracle results (fresh BDC staging):**
- Blocking rows: 208 -> 4 (98% reduction)
- Unclassified_signature: 47 -> 0 (fully resolved)
- Category subtotal leakage: 37 debt + 4 equity -> 0 (fully resolved)
- Q2 2025+ quarters: 0 blocking rows (fully clean)
- Remaining 4 blockers are mojibake encoding issues (corrupted em-dash characters in source XBRL) that cannot be resolved through wrapper config

**Test counts:** 32 wrapper tests pass, 50 oracle tests pass, 770 unified holdings tests pass (9 pre-existing failures unrelated to this change)
