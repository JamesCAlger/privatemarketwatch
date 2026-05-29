# Agent Changelog

Append-only log of agent-completed work. The human owner consolidates significant entries into AGENTS.md periodically.

Format: `### YYYY-MM-DD — Brief title`, then bullet points describing what changed, which files, and any new contracts or updated counts.

---

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
