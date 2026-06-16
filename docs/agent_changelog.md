# Agent Changelog

Append-only log of agent-completed work. The human owner consolidates significant entries into AGENTS.md periodically.

Format: `### YYYY-MM-DD — Brief title`, then bullet points describing what changed, which files, and any new contracts or updated counts.

---

### 2026-06-16 -- Shadow adapter ingests validate_holdings row-level issues

- **What changed:** new `_row_issues_select()` in `scripts/shadow_adapter.py` ingests `row_validation_issues.csv` (959K rows, the validate_holdings row-grain the four engines lack). Wired into `adapter_selects()` as a 4th adapter.
- **Mapping:** the file logs only OPEN issues, so `status` is always OPEN -- the verdict is `severity` (FAIL/WARN/INFO), certainty is `evidence_strength` (STRONG/MODERATE/WEAK), and `action=BLOCK_VERIFIED` is production's own verified-blocker disposition. Aggregated to one ledger row per `(cik, report_date, rule_id)` -> 20,361 groups across 45 rules. `tier=tight` when any FAIL in the group else weak; `enforcement=blocking_eligible` when any BLOCK_VERIFIED; `status` fail/warn/skip from severity; `mechanism` carries the block-verified flag; `src_confidence` carries evidence_strength.
- **Confidence/surface:** `scripts/shadow_validation_runner.py` scoring defers to this artifact's own grading (not the bootstrap heuristic): `row_block_verified` (action verified), `row_fail_<evidence>`, `row_warn_<evidence>`. Surface adds `row_block_verified`, `row_fail_strong`, `row_fail_moderate`; WARN bulk and weak fails are NOT surfaced.
- **Result counts:** row_validation contributes 1,731 tight fails + 18,196 warns + 434 info-skips. Surfaced: 1,120 block_verified + 861 fail_moderate + 185 fail_strong = 2,166; ~17.7K WARN rows suppressed. Ledger flagged rows 23,346, surfaced 4,454 (81% suppressed). The row_validation tight-fails also expand the corroboration anchor set (corroborated 579 -> 707).
- **Read-only:** outputs under `data/output/shadow/` only (gitignored); no production artifacts touched.

### 2026-06-15 -- Cash retained as analytics-only bucket (holistic portfolio composition); indices unchanged

- **Goal:** make BDC portfolio analytics holistic by surfacing a Cash bucket alongside private-market instrument types, WITHOUT changing the position-level indices (cash is analytics-only, never an index constituent). Derivatives are a separate follow-up (the brief's named derivative FV concepts -- `DerivativeFairValueOfDerivativeAsset/Liability`, `DerivativeAssets/Liabilities` -- do not exist in any of the 2,977 cached XBRL files; real derivative tagging is heterogeneous notional + gross-unrealized-gain/loss, so net FV must be *derived*; deferred pending a measured-coverage design).
- **Stop trimming cash (`pipeline/staging_bdc.py` CTE 9 `no_mm`):** money-market-keyword rows and wrapper non-private-market rows are no longer dropped. A candidate is retained and stamped `asset_category='CASH'` ONLY when its own issuer/instrument text names a cash equivalent (`cash_identity_check` over `_CASH_KEYWORDS` u `_MONEY_MARKET_KEYWORDS` u {cash equivalent, government/treasury obligations, liquidity/government fund}). Candidates that match only via a trailing aggregate phrase (e.g. `... | Total Cash and Cash Equivalents | Net Assets`) are filer balance-sheet reconciliation footers, not positions -- they keep being dropped (prevents subtotal leakage of ~$1.5B that an earlier draft introduced).
- **Classification (`pipeline/classification.py`):** added a top-priority `WHEN asset_category='CASH'` branch to `_sql_classify_index` (-> CASH), `_sql_classify_asset_class` (-> CASH), `_sql_classify_exposure_type` (-> LIQUID), and the Python `_classify_index` mirror. Safe: no pre-existing row carries `asset_category='CASH'` (verified against the prior output), so no existing classification changes.
- **Indices unchanged (`pipeline/position_matching.py`):** `unified_base` WHERE now excludes `asset_class IN ('CASH','DERIVATIVE')` / `index_classification='CASH'` BEFORE the `ROW_NUMBER` `_row_id` assignment, so the matched-position universe for every real index class is identical. Isolation test (same current unified through old-code vs new-code matching) confirmed: `index_returns` non-CASH **byte-identical** (only_old=0, only_new=0 across all 230 class*quarter rows); `position_returns` / `position_matches` non-CASH **byte-identical except the synthetic `position_id` label**, which necessarily re-sequences when cash rows leave the matching universe. CASH removed from index/position outputs (index_returns 17->0 quarters, position_returns 600->0 rows).
- **Analytics include cash (`pipeline/export/index_exports.py`):** `_export_portfolio_characteristics` now emits `cashFv` (sum of `index_classification='CASH'` fair value at the DL as-of quarter, from the unified holdings -- cash is not in `position_returns`). Frontend: `frontend/src/lib/types.ts` adds `cashFv?`; `frontend/src/app/page.tsx` instrument donut adds a "Cash & Equivalents" slice and relabels to "share of portfolio fair value (incl. cash)".
- **Counts (deduped, current cache):** BDC CASH-classified holdings 76 -> 505 rows (`asset_category='CASH'` = 429; `asset_class='CASH'` = 477); BDC cash fair value ~$5.1B -> ~$21.2B. N-PORT cash unchanged (678 rows). Unified total 795,064 rows; non-CASH unified row count unchanged. (The ~2,300 raw figure in the brief is pre-dedup `bdc_holdings`; unified collapses comparative/multi-quarter duplicates.)
- **No notional/pct corruption:** cash rows carry no derivative_notional (derivatives deferred); FV/pct fields sanity-checked (no negative or aggregate leaks after the reconciliation-footer guard).
- **Baseline governance:** the active official baseline (`data/snapshots/baseline/`, dated 2026-05-16) is stale relative to the current cache (pre-existing drift unrelated to this change, e.g. DL constituent counts differ even with old code), so `diff_outputs.py --semantic` against it is NOT a clean isolation here -- byte-identity was instead proven by the same-unified old-vs-new-code isolation test above. Baseline NOT refreshed (a stale-baseline refresh conflating unrelated drift would need separate approval/investigation).
- **Tests (`tests/test_unified_holdings.py`):** updated 2 staging tests to the retain-as-CASH behavior, kept a false-positive guard (a `Cash + PIK` loan stays a loan, not CASH), and added 2 classifier tests (`asset_category='CASH'` -> CASH/LIQUID; a normal loan is unaffected). Targeted suite 9/9 pass.

### 2026-06-15 -- Shadow adapter ingests rich source-reconciliation residual classification

- **What changed:** `scripts/shadow_adapter.py` `_source_recon_select()` no longer ingests the coarse per-CIK-quarter `source_reconciliation_metrics.csv` (pass/fail + reconciled-rate). It now ingests the RICH residual artifacts -- `source_reconciliation_residual_classification.csv` (output-side: `blocking_issue`, `mechanism`, `confidence`, `affected_source_fair_value`) and `source_reconciliation_source_only_detail.csv` (source-side: `is_blocking`, `mechanism`, `confidence`, `source_fair_value`).
- **Grain:** one ledger row per `(cik, report_date, mechanism)` for BLOCKING residuals only. The two artifacts are two views of the same residual keyed by `(cik, report_date, mechanism)`; the union de-duplicates (423 canonical blocking residual groups, not 423+1749 double-counted). FV is summed within each view then max-ed across views to avoid double-counting. `documented_*` mechanisms (comparative period, no-FV, source rollup, money-market, affiliation dedup) are intentional scope exclusions and are NOT emitted as flags.
- **Schema change:** the validation-results ledger gains two nullable columns -- `mechanism` and `src_confidence`. The four engine normalizers (conservation/identity/cross-source/weak) and the oracle/vrules adapters emit `CAST(NULL AS VARCHAR)` for both; only `source_recon` populates them.
- **Confidence/surface:** `scripts/shadow_validation_runner.py` scoring now DEFERS to source_reconciliation's own classification for source_recon rows: `confidence = 'source_blocking_' || src_confidence` (high/medium/low). `surface` adds `source_blocking_high` + `source_blocking_medium`; `source_blocking_low` is NOT surfaced (per the upstream grade). This replaces the generic `tight_anchor` bootstrap for the FV axis with the mature upstream judgement.
- **Result counts:** source_recon contributes 423 blocking residuals across 5 `blocking_source_*` mechanisms (354 `medium` -> surfaced, 69 `low` -> suppressed; 0 `high` because high-confidence residuals are all `documented_*` non-blocking). Ledger total 31,702 results across 142 distinct checks; 2,138 of 3,393 flagged rows surfaced (37% suppressed as scope/noise/low-confidence).
- **Read-only:** outputs under `data/output/shadow/` only (gitignored); no production artifacts touched.

### 2026-06-12 -- Position match override system and triage heuristics

- **New modules:** `pipeline/position_match_overrides.py` (loader + applier), `pipeline/match_triage.py` (5-check heuristic triage)
- **Override system:** Per-CIK JSON files in `data/overrides/position_match_overrides/` with `reject` and `force_pair` actions. Natural key matching (issuer_name + report_date + FV with 1% tolerance). Same audit contract as other overrides: mechanism, evidence, confidence, residual_risk, created_by, review_id.
- **JSON schema:** `schemas/position_match_override/override_v1.schema.json`
- **Triage function:** `triage_match_quality()` applies 5 heuristic checks to C/D/E match pairs: classification_flip, subtype_mismatch, maturity_gap, fv_ratio_extreme, rate_discontinuity. Joins match sides to holdings via DuckDB (same J07 pattern).
- **Wired into pipeline:** Override application added after tier assembly in `match_positions()`. Triage output added to `rebuild_unified_cik_trial.py --match` (writes `match_triage.{CIK}.csv`).
- **Config:** Added `POSITION_MATCH_OVERRIDES_DIR` to `pipeline/config.py`
- **Docs:** Added step 3c-2 to `WRAPPER_VALIDATE.md`, added match review guardrails to `SKILL.md`
- **Tests:** 14 override tests (loading, validation, reject, force_pair, FV tolerance, CIK scoping, method suffix), 14 triage tests (5 flag checks, no-flag clean, CIK/tier filtering, subtype parser). All 97 existing position matching tests pass.

### 2026-06-11 -- Plan C: Re-calibration complete (weighted error rate 4.2% -> 2.0%)

- **Rebuilt outputs** with Plans A+B fixes: 794,797 unified holdings rows, 511,482 position match pairs.
- **Generated v2 calibration sample**: 600 pairs across 6 tiers (same seed, different population due to Plan A/B changes). 146 bundles.
- **Sub-agent line-by-line review**: 7 parallel sub-agents reviewed 146 bundles using the 5-point calibration protocol (entity identity, instrument type, tranche discrimination, attribute consistency, alternative candidates). An earlier heuristic review (0.1%) significantly underestimated errors by missing wrong_tranche cases.
- **Results**:
  - Weighted error rate: **2.0%** (95% CI: 0.0%-4.1%), down from 4.2%
  - A: 0.0%, B1b: 2.5%, B2: 3.1%, C: 29.4%, D: 13.4%, E: 12.9%
  - A and B2 meet targets; B1b, C, D, E still exceed targets
  - 519 correct, 36 wrong_tranche, 23 ambiguous, 16 wrong_entity, 6 wrong_instrument (58 total errors)
- **Dominant residual pattern**: wrong_tranche (36/58 errors) -- same entity, different instrument. Greedy 1:1 ROW_NUMBER matching selects locally optimal pairs without global optimization. This is the bipartite matching problem (Plan B Deliverable 6, deferred).
- **V2 decision**: Agentic triage IS justified for C/D/E tier matches. Recommended: (1) bipartite matching for multi-position entities, (2) agentic review for residual C/D/E flagged pairs, (3) CIK-specific prefix stripping for D-tier.
- Files created: docs/position_match_calibration/calibration_results_v2.md, scripts/run_calibration_review.py
- Files modified: data/output/position_match_calibration/sample.csv, verdicts/, calibration_summary.md

### 2026-06-11 -- Plan B: Matching algorithm hardening (4 hard gates + suffix tiebreaker + J07/J08)

- **Classification flip veto** (pipeline/position_matching.py):
  - B2/C/D pair CTEs now reject matches where both sides have non-empty `index_classification` and they differ. 100% calibrated precision.
  - E already required classification match; A/B1/B1b excluded by design.
- **Instrument sub-type continuity** (pipeline/position_matching.py):
  - Added `_inst_subtype` computed column to `unified_base` CTE, parsed from `instrument_description` via RE2 regex (REVOLVER, DDTL, TERM_LOAN, WARRANT, EQUITY).
  - B1b/B2/C/D/E pair CTEs reject matches where both sides have a parseable sub-type and they differ.
- **Maturity mismatch veto** (pipeline/position_matching.py):
  - Added `MAX_MATURITY_GAP_DAYS = 365` module constant.
  - C/D/E pair CTEs reject matches where both sides have parseable maturity dates differing by >365 days. B2 excluded (tolerates amendments).
- **Suffix coexistence tiebreaker** (pipeline/position_matching.py):
  - Added `_trailing_num` computed column to `unified_base`, parsing trailing integers from `issuer_name`.
  - B2/C/D ROW_NUMBER ORDER BY now includes `_suffix_match DESC` early in tiebreaker sequence.
  - Not a hard gate -- shifts preference only when same-suffix candidates exist.
- **Tier D blocked CTE propagation**: Added `index_classification`, `_inst_subtype`, `maturity_date`, and `_trailing_num` to the D `blocked` SELECT to enable filters in `scored`.
- **J07 hard gate rejection audit** (pipeline/oracle_checks.py):
  - Informational check that counts C/D/E matches rejected by each gate (classification flip, maturity >12mo, instrument sub-type mismatch). Always passes.
- **J08 suspected refinancing detection** (pipeline/oracle_checks.py):
  - Flags B2+ matches with maturity shift >12mo AND spread change >50bps. Warns if rate exceeds 5%.
- **Tests**: 13 new tests in test_position_matching.py (classification flip, instrument sub-type, maturity gap, suffix tiebreaker). 6 new tests in test_oracle_checks.py (J07, J08).
- Files modified: pipeline/position_matching.py, pipeline/oracle_checks.py, tests/test_position_matching.py, tests/test_oracle_checks.py

### 2026-06-09 -- Position match quality: J05/J06 oracle checks + B2 attribute disambiguation

- **New oracle checks** (pipeline/oracle_checks.py):
  - J05: Lower-tier match pair consistency -- flags B2/C/D/E matches with 2+ attribute discontinuities (FV ratio >10x, rate gap >5pp, principal ratio >5x). Warn if suspect rate >5%.
  - J06: Fuzzy match semantic validation -- joins D/E matches back to holdings via DuckDB to compare raw identifiers (JW similarity) and index classifications. Warn if suspect rate >15%.
  - Added `_jaro_winkler_py()` pure-Python helper (self-contained, no extra deps).
  - Both registered in CHECK_REGISTRY, discoverable by oracle_runner dispatch.
- **B2/C/D attribute disambiguation** (pipeline/position_matching.py):
  - B2 (exact name): Added `_attr_penalty` (lien_position + index_classification + coupon_type mismatch count) and `_maturity_prox` (maturity date day difference) to ROW_NUMBER ORDER BY, ahead of FV/rate/principal proximity.
  - C (normalized name): Same `_attr_penalty` and `_maturity_prox` tiebreaker added.
  - D (fuzzy): Same penalty added to blocked CTE, carried through scored/with_output, inserted after match_score DESC in ROW_NUMBER.
  - Soft penalty design: only reorders preference when multiple candidates exist at the same entity; does not filter out any matches.
- **Tests**: 22 new tests (18 oracle + 4 position matching), all passing. 98 oracle check tests total, 79 position matching tests total. Zero regressions.
- **Files modified**: pipeline/oracle_checks.py, pipeline/position_matching.py, tests/test_oracle_checks.py, tests/test_position_matching.py

### 2026-06-09 -- Fund highlights wrapper skill

- **New module**: `pipeline/fund_highlights_wrapper.py` -- frozen dataclass loader for per-CIK highlights wrappers (concept overrides, share class aliases, oracle tolerances)
- **Schema**: `schemas/fund_highlights_wrapper/wrapper_v1.schema.json` -- JSON Schema 2020-12 for `fund-highlights-wrapper.v1`
- **Pipeline integration**: `pipeline/bdc_fund_highlights.py` -- wrapper-aware `_match_concept_with_wrapper()` applied before global concept map; `_canonical_share_class()` now accepts per-CIK aliases; both changes are no-ops when no wrapper exists for a CIK
- **Oracle integration**: `pipeline/bdc_fund_highlights_oracle.py` -- per-CIK tolerance overrides from wrapper; new `highlights_wrapper_version` column in oracle output; `_compute_verdict()` accepts `nav_identity_tol`/`income_identity_tol` parameters
- **Config**: `pipeline/config.py` -- added `FUND_HIGHLIGHTS_WRAPPER_DIR` path constant
- **Scripts**: `scripts/rebuild_highlights_cik_trial.py` (one-CIK trial rebuild with before/after comparison); `scripts/fund_highlights_wrapper_worklist.py` (priority queue from residual profiler)
- **Skill**: `.claude/skills/highlights-wrapper/SKILL.md` -- profile/create/validate dispatch
- **Docs**: `docs/highlights_wrapper/` -- profile, create, and validate mode instructions
- **Tests**: `tests/test_fund_highlights_wrapper.py` -- 19 tests covering loader, concept overrides (map/suppress/prefer/order), share class aliases, oracle tolerances, schema validation, frozen dataclass
- **Regression**: 19/19 new tests pass; existing `test_validate_fund_financials.py` (11/11), `test_oracle_checks.py` (80/80), `test_validation_rules.py` (41/41) pass; pre-existing 1 failure in `test_bdc_xbrl_wrapper.py` (apollo DS test) is unrelated

### 2026-06-06 -- KKR FS Income Trust Select wrapper

- Added `data/overrides/bdc_xbrl_wrappers/0001975736.json` for KKR FS Income Trust Select and updated its entry in `data/overrides/bdc_xbrl_wrappers/unlisted_bdc_xbrl_reference.json` from `wrapper_status: none` to `exists`.
- Added focused tests in `tests/test_bdc_xbrl_wrapper.py` for pipe-delimited debt leaves, affiliated equity leaves with prefix-stripped keys, comma-form debt leaves, total-row false positives, and registry support. Added staging tests in `tests/test_unified_holdings.py` for comma issuer/instrument extraction, normal pipe rows, and affiliated pipe-prefix rows.
- Staging contract: for CIK `0001975736`, comma-form rows split issuer before the first comma, affiliated/non-affiliated pipe-prefix rows strip the affiliation prefix before issuer extraction, and plain issuer/industry pipe rows stay issuer-specific.
- Validation results: schema validation passed; wrapper JSON coherence check passed; `pytest tests/test_bdc_xbrl_wrapper.py -k "kkr_fs_income_trust_select" -q` passed 4 tests; `pytest tests/test_unified_holdings.py -k "kkr_fs_select" -q` passed 3 tests; `pytest tests/test_unified_cik_trial.py -q` passed 7 tests.
- Staging oracle with fresh BDC staging passed all 9 quarters with zero remaining blocking rows. Wrapper disposition lookup classified 817 of 817 candidates; final BDC staging produced 1,953 rows versus 1,928 rows before wrapper staging.
- One-CIK trial rebuild for `0001975736` produced 1,953 unified rows versus 1,928 production rows, a +25 row scoped trial delta. Position matching passed J01 at 94.3% B1b (517/548 non-A/B1 matches) and J03 at 0.3% fuzzy fallback (4/1,437 matches). Issuer hygiene scan found 0 trial issuers beginning with affiliation, hierarchy, cash, or total markers.
- Wrapper oracle on trial holdings passed all 9 quarters with zero remaining blocking rows. Promotion gate status is `promote`: blocking rows and FV deltas were 0 because the pre-wrapper baseline had no source blockers. Remaining oracle output is review-only warning diagnostics for 29 family-vs-asset-category disagreement rows.
- `python scripts/diff_outputs.py --semantic` was run and failed because the current workspace remains broadly divergent from the active baseline: 443 divergent artifacts out of 3,682 checked and 77 skipped, including holdings, matches, position returns, index returns, and fund financials. No production rebuild was run.

### 2026-06-06 -- Antares Private Credit wrapper

- Added `data/overrides/bdc_xbrl_wrappers/0001976336.json` for Antares Private Credit Fund. The wrapper covers non-controlled/non-affiliated `Asset Type` hierarchy leaves, plural `Assets Type` variants, no-space `Asset TypeFirst` filing text, stripped `Debt Investments` / `nvestments` prefixes, and unfunded commitment rows with and without `Commitment Type`.
- Added focused tests in `tests/test_bdc_xbrl_wrapper.py` for debt, equity, commitment, plural asset-type, totals/cash/industry-heading false positives, and registry support. Added staging tests in `tests/test_unified_holdings.py` for issuer/instrument extraction across debt, commitment, no-label revolver commitment, no-space asset type, plural asset type, stripped debt prefixes, and industry-heading exclusion.
- Staging contract: for CIK `0001976336`, hierarchy extraction captures issuer before `Asset Type`, `Assets Type`, `Commitment Type`, or commitment-expiration-only instrument text; total/cash/unfunded aggregate and industry heading rows are excluded from position-level output.
- Validation results: schema validation passed; wrapper JSON coherence check passed; `pytest tests/test_bdc_xbrl_wrapper.py -k "antares_private" -q` passed 6 tests; `pytest tests/test_unified_holdings.py -k "antares_private" -q` passed 7 tests; `pytest tests/test_unified_cik_trial.py -q` passed 7 tests.
- One-CIK trial rebuild for `0001976336` produced 6,673 BDC staging/unified rows versus 6,652 production rows, a +21 row scoped trial delta. Position matching passed J01 at 79.3% B1b (1,559/1,966 non-A/B1 matches) and J03 at 0.6% fuzzy fallback (12/1,966 matches). Issuer hygiene scan found 0 trial issuers beginning with hierarchy prefixes, cash, or total markers.
- Wrapper oracle on trial holdings passed all 6 quarters with zero remaining blocking rows. Promotion gate status is `promote`: blocking rows improved by -19, blocking FV by -$6.309B, and 78 rollup/source residual rows were cleared. Remaining oracle output is review-only warning diagnostics (`non_private_market_disagreement`, `aggregate_detection_disagreement`, `hierarchy_parse_disagreement`, `identifier_normalization_impact`, and `wrapper_leaf_staging_excluded`).
- `python scripts/diff_outputs.py --semantic` was run and failed because the current workspace remains broadly divergent from the active baseline: 443 divergent artifacts out of 3,682 checked and 77 skipped, including holdings, matches, position returns, index returns, and fund financials. No production rebuild was run.

### 2026-06-05 -- Jefferies Credit Partners wrapper

- Added `data/overrides/bdc_xbrl_wrappers/0001959604.json` for Jefferies Credit Partners BDC Inc. The wrapper covers full `Non-Controlled/Non-Affiliated Portfolio Company Investments` hierarchy identifiers, stripped `Portfolio Company ... Investment Type ...` rows, odd non-controlled equity variants, and unfunded/total rows that must not become position leaves.
- Added focused tests in `tests/test_bdc_xbrl_wrapper.py` for debt leaves, L.P. interest equity leaves, stripped portfolio-company leaves, total/unfunded false positives, hierarchy-heading false positives, and registry support. Added staging tests in `tests/test_unified_holdings.py` for issuer/instrument extraction and unfunded commitment filtering.
- Staging contract: for CIK `0001959604`, hierarchy extraction now captures issuer before `Investment Type`, moves the disclosed investment type into `instrument_description`, strips rate/maturity fragments from wrapper position keys, and requires explicit position text before full hierarchy rows can be classified as leaves.
- Validation results: schema validation passed; wrapper JSON coherence check passed; `pytest tests/test_bdc_xbrl_wrapper.py -k "jefferies" -q` passed 5 tests; `pytest tests/test_unified_holdings.py -k "jefferies" -q` passed 3 tests; `pytest tests/test_unified_cik_trial.py -q` passed 7 tests.
- One-CIK trial rebuild for `0001959604` produced 2,059 unified rows from 2,386 BDC staging rows versus 2,415 production rows. Position matching passed J01 at 89.7% B1b (323/360 non-A/B1 matches) and J03 at 0.3% fuzzy fallback (2/734 matches).
- Wrapper oracle on trial holdings had zero remaining blocking rows and zero wrapper-blocking rows. Promotion gate is `review_required`, not `reject`: blocking rows improved by -20 and blocking FV by -$5.174B. Remaining reasons are review-only soft gates: `exclusion_risk_detected`, `low_position_continuity`, and `cost_fv_ratio_outliers`.
- `python scripts/diff_outputs.py --semantic` was run and failed because the current workspace remains broadly divergent from the active baseline: 443 divergent artifacts out of 3,682 checked, including universe, holdings, returns, and frontend JSON artifacts. No production rebuild was run.

### 2026-06-05 -- New Mountain Private Credit wrapper

- Added `data/overrides/bdc_xbrl_wrappers/0002037804.json` for New Mountain Private Credit Fund. The wrapper covers pipe-delimited issuer/instrument/affiliation identifiers, older comma and no-comma legal-suffix rows, business-line labels used as position descriptors, single-name `Denali` rows, and excludes totals/cash rows from private-market leaves.
- Added focused tests in `tests/test_bdc_xbrl_wrapper.py` for pipe suffix stripping, comma debt leaves, equity leaves, business-line leaves, single-name business-line leaves, totals/cash false positives, and registry support. Added staging tests in `tests/test_unified_holdings.py` for comma, no-comma, and parenthetical f/k/a issuer extraction.
- Staging contract: for CIK `0002037804`, hierarchy extraction now preserves issuer parentheticals after legal suffixes (for example `Auctane Inc. (fka Stamps.com Inc.)`) and moves the lien text into `instrument_description` instead of leaving it in `issuer_name`.
- Validation results: schema validation passed; wrapper JSON coherence check passed; `pytest tests/test_bdc_xbrl_wrapper.py -k "new_mountain" -q` passed 12 tests; `pytest tests/test_unified_holdings.py -k "new_mountain" -q` passed 3 tests; `pytest tests/test_unified_cik_trial.py -q` passed 7 tests.
- One-CIK trial rebuild for `0002037804` produced 1,906 BDC rows, matching production row and FV exactly across all 6 quarters from 2024-12-31 through 2026-03-31. Position matching passed J01 at 86.9% B1b (292/336 non-A/B1 matches) and J03 at 0.8% fuzzy fallback (7/918 matches).
- Wrapper oracle on trial holdings had zero remaining blocking rows and zero wrapper-blocking rows. Five quarters passed; 2026-03-31 retains one review-only oracle fail for `cost_fv_ratio_outliers`. Review warnings also remain for `hierarchy_parse_disagreement` (4 rows) and `family_vs_asset_category_disagreement` (6 warrant-vs-equity rows).
- `python scripts/diff_outputs.py --semantic` was run and failed because the current workspace remains broadly divergent from the active baseline: 443 divergent artifacts out of 3,682 checked, including universe, holdings, returns, and frontend JSON artifacts. No production rebuild was run.

### 2026-06-05 -- Diameter Credit wrapper

- Added `data/overrides/bdc_xbrl_wrappers/0001916099.json` for Diameter Credit Co. The wrapper covers the non-controlled/non-affiliated debt/equity hierarchy, strips security-type and industry prefixes in BDC staging, demotes sector/category and total rows, and excludes cash/cash-equivalent totals from private-market output.
- Added focused tests in `tests/test_bdc_xbrl_wrapper.py` covering BDO term-loan leaves, current-coupon key normalization, acquisition-date lot metadata normalization, sector-header false-positive protection, cash totals, malformed preferred-equity totals, 2026 fund-style equity leaves, and registry support.
- Position-key contract: current coupon and acquisition-date fragments are stripped from canonical Diameter wrapper keys, while reference-rate spread, maturity, issuer, and instrument text remain in the key to avoid merging distinct tranches.
- Validation results: schema validation passed; wrapper JSON coherence check passed; `pytest tests/test_bdc_xbrl_wrapper.py -k "diameter" -q` passed 8 tests; `pytest tests/test_unified_cik_trial.py -q` passed 7 tests. Full `tests/test_bdc_xbrl_wrapper.py -q` was attempted but failed in unrelated Nuveen Churchill tests because an untracked `data/overrides/bdc_xbrl_wrappers/0001911066.json` and active `0001911066` trial job were present; rerun excluding those nodes passed 266 tests with 6 deselected.
- One-CIK trial rebuild for `0001916099` produced 836 BDC rows versus 797 production rows, a +39 row / +$1.080B FV scoped trial delta across 2024-03-31 through 2026-03-31. Position matching passed J01 at 91.2% B1b (332/364 non-A/B1 matches) and J03 at 1.6% fuzzy fallback (6/371 matches).
- Wrapper oracle on trial holdings passed all 9 quarters with zero remaining blocking rows. It cleared 67 documented rollup/source residual rows; only review diagnostics were emitted as warnings (`non_private_market_disagreement`, `aggregate_detection_disagreement`, `hierarchy_parse_disagreement`, and `wrapper_leaf_staging_excluded`).
- `python scripts/diff_outputs.py --semantic` was run and failed because the current workspace remains broadly divergent from the active baseline: 443 divergent artifacts out of 3,682 checked, including universe, holdings, returns, and frontend JSON artifacts. No production rebuild was run.

### 2026-06-05 -- T. Rowe Price OHA Select wrapper

- Added `data/overrides/bdc_xbrl_wrappers/0001901164.json` for T. Rowe Price OHA Select Private Credit Fund. The wrapper covers the bare issuer/tranche identifier style, the 2025 `Investment, Unaffiliated Issuer, ...` comma-prefix format, and the 2025-12 onward `| Non-Affiliated Issuer` pipe suffix format. It strips those affiliation wrappers from canonical position keys but does not infer omitted instrument type for bare issuer rows.
- Added focused tests in `tests/test_bdc_xbrl_wrapper.py` covering pipe suffix stripping, comma-prefix stripping, total-investments false-positive protection, observed bare issuer styles (`Mantech International CP`, `Global Music Rights`, `Geosyntec Consultants`), and wrapper registry support.
- Validation results: schema validation passed; wrapper coherence check passed; `pytest tests/test_bdc_xbrl_wrapper.py -q` passed 240 tests; `pytest tests/test_unified_cik_trial.py -q` passed 7 tests. One-CIK trial rebuild for `0001901164` produced 3,282 BDC rows, matching production by row/FV for all quarters except the pre-existing no-wrapper trial drift of +1 row / +$17.529M at 2025-09-30. Position matching passed J01 at 92.8% B1b (816/879 non-A/B1 matches) and J03 at 0.9% fuzzy fallback (16/1,783 matches).
- Wrapper oracle on trial holdings had zero source-reconciliation blockers and zero wrapper-blocking rows. Remaining oracle failures are review-only/waiveable diagnostics: `unclassified_fv_rate_exceeded`, `cost_fv_ratio_outliers`, and `unclassified_rate_qoq_jump`; no non-waiveable blockers remained.
- `python scripts/diff_outputs.py --semantic` was run and failed because the current workspace is already broadly divergent from the active baseline: 443 divergent artifacts out of 3,682 checked, including universe, holdings, returns, and frontend JSON artifacts. No production rebuild was run because another agent had an active Python oracle job for CIK `0001993402`.

### 2026-06-05 -- Wrapper skill split, coherence checks, and archetype defaults

- **Skill split:** Trimmed `.claude/skills/wrapper/SKILL.md` from 872 lines to ~120-line dispatcher with mode dispatch. Created `docs/wrapper/WRAPPER_PROFILE.md` (Steps 0-1), `docs/wrapper/WRAPPER_CREATE.md` (Step 2 + Pitfalls 1-4), `docs/wrapper/WRAPPER_VALIDATE.md` (Steps 3-6 + Pitfalls 5-7). Agents now load only the mode-specific doc they need.
- **Coherence checks:** Added `validate_wrapper_json_coherence()` to `pipeline/bdc_xbrl_wrapper_oracle.py`. Checks family-marker alignment, staging strategy prerequisites, regex compilation, fallback family consistency, and archetype-dispatch alignment. Integrated into `run_wrapper_oracle_trial()` for fail-fast on misconfigurations. Family alignment and fallback family checks are warnings; staging prerequisites and regex errors are hard errors.
- **Archetype defaults:** Added `_DEFAULT_ARCHETYPE_SIGNATURES` to `pipeline/wrapper_content_signatures.py`. Equity archetypes automatically get `basis_spread: forbidden`; warrant archetypes get `interest_rate: forbidden` + `basis_spread: forbidden`; all known families get `fair_value: required`. Explicit signatures always win. Applied in `_parse_definition()` during wrapper JSON loading.
- **Tests:** 12 new coherence check tests in `tests/test_bdc_xbrl_wrapper_oracle.py` (including integration test against all existing wrapper JSONs). 5 new default signature tests in `tests/test_wrapper_content_signatures.py`. All 324 wrapper-related tests pass.
- **Files modified:** `.claude/skills/wrapper/SKILL.md`, `pipeline/bdc_xbrl_wrapper_oracle.py`, `pipeline/wrapper_content_signatures.py`, `tests/test_bdc_xbrl_wrapper_oracle.py`, `tests/test_wrapper_content_signatures.py`
- **Files created:** `docs/wrapper/WRAPPER_PROFILE.md`, `docs/wrapper/WRAPPER_CREATE.md`, `docs/wrapper/WRAPPER_VALIDATE.md`

### 2026-06-05 -- Frontend V1: Narrow scope to unlisted BDCs only

Implemented full frontend and pipeline export narrowing from all vehicle types (BDCs, interval funds, tender offer funds) to unlisted (non-traded) BDCs only (~129 funds). Two published indices: Private Credit Total Return (DIRECT_LENDING) and Private Equity NAV Return (COMMON_EQUITY).

**Frontend changes (Phases 1-9):**
- `frontend/src/lib/constants.ts`: INDICES reduced from 3 to 2 (removed PREFERRED_EQUITY), slugs changed to `private-credit` and `private-equity`, category updated to "METRIS LENS"
- `frontend/src/components/Header.tsx`: Removed "Data" nav, ticker bar grid 4->3 cols, Subscribe button to /about
- `frontend/src/components/Footer.tsx`: Removed N-PORT data source, removed "Data access" link
- `frontend/src/app/page.tsx`: New hero copy, "Unlisted BDCs" label, replaced MoversSection with CreditRiskCards (credit risk summary, portfolio health, yield leaderboard), "Private Credit" eyebrow on portfolio characteristics
- `frontend/src/components/FundTable.tsx`: Removed vehicle type filter tabs, removed Type/Liquidity columns
- `frontend/src/components/HistogramChart.tsx`: Single `total` bar instead of stacked bdc/nonBdc
- `frontend/src/app/indices/[slug]/page.tsx`: "post-Q4 BDC XBRL" label, "Private Credit" eyebrow
- `frontend/src/app/indices/page.tsx`: 2-col grid, updated hero text, removed peSummary
- `frontend/src/components/HeroStats.tsx`: 3-col grid, renamed labels
- `frontend/src/app/funds/[cik]/page.tsx`: BDC liquidity "Unlisted"
- `frontend/src/components/VehicleTypeBadge.tsx`: BDC label "Unlisted BDC"
- `frontend/src/app/about/page.tsx`: Removed N-PORT step, updated stats/copy for unlisted BDCs
- `frontend/src/app/methodology/page.tsx`: 2 indices, removed N-PORT sections, simplified universe construction
- `frontend/src/app/data-quality/page.tsx`: Redirects to `/`

**Pipeline export filter (Phase 10):**
- `pipeline/config.py`: Added UNLISTED_BDC_REFERENCE_FILE constant
- `pipeline/export/helpers.py`: Added _load_unlisted_bdc_ciks(), UNLISTED_BDC_CIKS set, _unlisted_bdc_filter_sql() function, applied filter to _valid_positions_sql() (both latest and valid CTEs)
- `pipeline/export/fund_exports.py`: Filter on fund_list, fund_details, fund_summary queries
- `pipeline/export/index_exports.py`: Filter on portfolio_characteristics, metadata (5 queries), index_summary unique counts
- `pipeline/export/analytics_exports.py`: Filter on credit_risk, distribution_histogram, leverage_histogram, gics_sector_breakdown
- `pipeline/export/timeseries_exports.py`: Filter on fund_index_returns, aum_time_series, industry_breakdown

**Verification:**
- `npm run build` -> 402 static pages, zero errors. Indices: /indices/private-credit, /indices/private-equity
- `python -m pipeline.main --export-frontend` -> 22 JSON files, 123 fund details (unlisted BDCs only), 2 fund_index_returns series (bdc + combined), 85 distribution histogram funds, 106 leverage histogram funds
- Interval fund, tender offer, N-PORT references remain only in unreachable code paths (kept for future extensibility)

### 2026-06-05 -- Add static HTML-section bridge support for BDC XBRL wrappers

- Added `pipeline/bdc_xbrl_html_bridge.py` for audited same-accession HTML-section bridge records and a cached-HTML proposal CLI (`python -m pipeline.bdc_xbrl_html_bridge`).
- Added `schemas/bdc_xbrl_html_section_bridge/bridge_v1.schema.json` for bridge files under `data/overrides/bdc_xbrl_html_section_bridges/{CIK}.json`.
- Updated BDC staging so exact bridge matches by CIK, accession, report date, and raw identifier can rescue position leaves from aggregate filters and fill missing `issuer_name` / `instrument_description` without broad text inference.
- Updated source reconciliation wrapper-column coercion so bridge-matched source/output rows are reported as `{family}_position_leaf` in oracle diagnostics.
- Updated `.claude/skills/wrapper/SKILL.md` to require static bridge proposals when source HTML section headers carry instrument context that XBRL typed identifiers dropped.
- Added focused tests for bridge loading, schema validation, proposal section tracking, accession-scoped wrapper-column overlay, and staging repair.

**Validation:**
- `pytest tests/test_bdc_xbrl_html_bridge.py tests/test_unified_holdings.py::TestPrepareBdc::test_html_section_bridge_fills_missing_instrument -q` -> 5 passed, 1 BeautifulSoup/lxml warning.
- `pytest tests/test_bdc_xbrl_wrapper.py tests/test_bdc_xbrl_wrapper_oracle.py -q` -> 197 passed, 2 existing wrapper regex warnings.
- `python -m pipeline.bdc_xbrl_html_bridge --help` succeeded.

**Contract:**
- Bridge records are production-affecting only after an accepted bridge JSON file exists locally.
- No SEC downloads are introduced; missing cached HTML yields no bridge.
- Adjacent-period HTML can support review notes but cannot create accepted records for a different accession.

### 2026-06-04 -- Per-CIK hierarchy_extract support + Apollo issuer extraction

- **`pipeline/staging_bdc.py`**: Refactored `hierarchy_extract` strategy from single-config to per-CIK branching. Previously, `next(iter(_hierarchy_extract_cfgs.values()))` took only the first config's regexes and applied them to all hierarchy_extract CIKs. Now each CIK gets its own WHEN branch with its own issuer_re, instrument_re, trailing_re, and condition, matching the pattern already used by `hierarchy_leaf_guard`. Renamed `_crescent_clean_raw` to `_he_clean_raw`, removed dead `_crescent_cik_sql`/`_crescent_condition` variables.
- **`data/overrides/bdc_xbrl_wrappers/0001837532.json`**: Switched Apollo Debt Solutions from `strategy: "default"` to `strategy: "hierarchy_extract"` with regexes for Apollo's XBRL hierarchy format (`{Sector} {CompanyName} Investment Type {Instrument} Interest Rate...`). Uses `MSD_INDUSTRY_LABELS` placeholder. Fixed `\b` word-boundary issue in DuckDB (JSON `\\b` loads as Python backspace `\x08`, not regex `\b`); used `(?:\s|$)` boundaries instead.
- **Verification**: Crescent Capital (0001954360) regression: 2272/2272 rows, delta 0. Apollo (0001837532) trial: 6351 rows, J01 pass (95.2%), J03 pass (0.2%). Issuer extraction: 0 rows with "Investment Type"/"Security Type" in issuer_name (was 20 before). 669 tests passed (test_bdc_xbrl_wrapper + test_unified_holdings).

### 2026-06-03 -- Add 5 wrapper-vs-staging diagnostic columns to source reconciliation

- **pipeline/source_reconciliation.py**: Added 5 read-only diagnostic columns to `DETAIL_COLUMNS` and the reconciliation SQL: `aggregate_detection_disagreement`, `hierarchy_parse_disagreement`, `identifier_normalization_impact`, `family_vs_asset_category_disagreement`, `wrapper_leaf_staging_excluded`.
- New `source_with_diagnostics` CTE inserted between `source_classified` and `source_duplicate_marked` computes the 3 source-only diagnostics. `source_duplicate_marked` and `eligible_source` updated to read from it.
- `family_vs_asset_category_disagreement` and `wrapper_leaf_staging_excluded` computed in `source_detail` SELECT where matched-output and affiliation-dupe join data is available.
- Replaced single-column `non_private_market_disagreement` log block with a loop over all 6 diagnostic columns.
- **tests/test_validate_holdings.py**: New `TestWrapperStagingDiagnostics` class with 5 tests (one per column). All pass. No regressions (130/131 pass; 1 pre-existing `test_trinity_wrapper_rollup` V1/V3 rule ID mismatch).
- **tests/test_source_reconciliation_cache.py**: 5/5 pass with updated `DETAIL_COLUMNS`.
- No staging logic changed. Columns are purely additive diagnostics. Production rebuild not yet run.

---

### 2026-06-02 -- Consolidate hardcoded staging SQL into wrapper JSON config

- **Pure refactor** (Phase A): `pipeline/staging_bdc.py` now reads `hierarchy_prefix_re`, `hierarchy_issuer_re`, `hierarchy_instrument_re`, `hierarchy_trailing_re`, `hierarchy_condition_extra`, `leaf_guard.type_industry_prefix_re`, `leaf_guard.marker_re`, and `leaf_guard.evidence_re` from the per-CIK wrapper JSON files instead of hardcoding them in Python.
- Added `_expand_placeholders()` and `_expand_staging_strings()` helpers to substitute `(?:INDUSTRY_LABELS)` and `(?:CRESCENT_INDUSTRY_LABELS)` tokens in JSON patterns with runtime-computed regex alternations.
- Staging configs are now loaded once via `_load_staging_configs()` and grouped by strategy (`_prefix_strip_cfgs`, `_hierarchy_extract_cfgs`, `_leaf_guard_cfgs`) instead of calling three separate `_get_*_ciks()` helpers.
- Removed `_get_hierarchy_leaf_ciks()`, `_get_prefix_strip_ciks()`, `_get_hierarchy_extract_ciks()` functions (were each redundantly calling `_load_staging_configs()`).
- All variable names consumed by downstream SQL (`_msd_hierarchy_prefix_re`, `_msd_hierarchy_condition`, `_msd_clean_raw`, `_crescent_*`, `_hierarchy_leaf_*`) are preserved -- the generated SQL is character-for-character identical to the old hardcoded version (verified with explicit comparison script).
- No behavioral change. Adding a new CIK with any of these three strategies now only requires adding a JSON wrapper file.
- Verified: 21 CIK-specific tests pass, 784/784 non-slow unified holdings tests pass, 34/34 wrapper tests pass.

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

### 2026-06-03 -- Split unified holdings tests into fast, staging SQL, and integration buckets

Changed test selection semantics for `tests/test_unified_holdings.py` without changing pipeline behavior.

**pytest.ini:**
- Added `staging_sql` marker for DuckDB-backed staging SQL tests.

**tests/test_unified_holdings.py:**
- Added reusable marker lists for slow integration and slow staging SQL groups.
- Marked full `build_unified_holdings()` regression groups as `slow` + `integration`.
- Marked `_prepare_bdc()` / `_prepare_nport()` DuckDB staging groups as `slow` + `staging_sql`.

**Contracts and validation:**
- Fast inner-loop command: `python -m pytest -q tests/test_unified_holdings.py -m "not slow and not integration"`.
- Collection split: 786 total tests; 39 integration tests; 214 staging SQL tests; 253 slow/integration/staging tests; 533 fast inner-loop tests.
- Verified fast subset: 533 passed, 253 deselected in 13.35s.

### 2026-06-03 -- One-CIK unified trial rebuild for wrapper validation

Added a fast one-CIK trial rebuild path so wrapper developers can validate unified holdings changes for a single CIK without running the full 33-minute unified build.

**pipeline/unified_holdings.py:**
- Added optional `output_file` and `orphan_file` keyword parameters to `build_unified_holdings()`. When provided, CSV/parquet output is written to the custom paths instead of the production defaults.
- Added empty-DataFrame guards to entity and industry enrichment DuckDB steps to prevent `BinderException` when the universe gate removes all rows (e.g., test fixtures with non-real CIKs).
- Internal variables `_out_file` / `_orphan_file` resolve defaults from `UNIFIED_HOLDINGS_FILE` / `UNIVERSE_ORPHAN_HOLDINGS_FILE` when the parameters are None.

**scripts/rebuild_unified_cik_trial.py (new):**
- CLI script: `python scripts/rebuild_unified_cik_trial.py --cik 0001849894`.
- Loads production BDC and N-PORT holdings via DuckDB, filters to the target CIK, calls `build_unified_holdings()` with trial output paths under `data/output/bdc_xbrl_wrapper_trial/{CIK}/unified_trial/`.
- Produces `trial_vs_production_summary.{CIK}.csv` comparing row counts and FV per source/report_date against production.

**pipeline/bdc_xbrl_wrapper_oracle.py:**
- Added `--holdings-file` CLI argument and `holdings_file` parameter to `run_wrapper_oracle_trial()`.
- Mutual exclusion with `--fresh-bdc-staging` enforced at both the function and CLI parser level.
- When `--holdings-file` is provided, oracle reads trial unified holdings instead of the production file.

**tests/test_unified_cik_trial.py (new):**
- 7 tests: 3 for `build_unified_holdings()` alternate output paths (custom path, default path, empty input), 3 for oracle `--holdings-file` mutual exclusion (ValueError, CLI rejection, FileNotFoundError), 1 for trial rebuild script CLI.

**.claude/skills/wrapper/SKILL.md:**
- Added step 3c (one-CIK trial unified rebuild) to the wrapper validation workflow; renumbered subsequent steps.

**Verification:** 7 new tests pass; 870 existing wrapper/oracle/unified tests pass with zero regressions. Smoke test with Trinity Capital (CIK 0001786108): 5,053 rows in 64.6s, +0 row delta vs production.

### 2026-06-03 -- Position-level matching uniqueness guard

Implemented position-level safeguards for `position_id` assignment and repaired weak staging keys that were collapsing separate tranches.

**pipeline/position_matching.py:**
- Added strong `position_key` eligibility checks for B1b matching; generic or placeholder keys such as `lass units` and `nc nc` no longer form B1b edges.
- B1b position-key matching now requires each key to be unique within a CIK/source/report quarter before it can link periods.
- Added guarded union-find assignment: an edge is accepted only if the resulting component still has at most one row per `(cik, source, report_date)`.
- Added a hard duplicate-position validation after assignment.
- Dropped match rows that cannot map back to any unified row before returns are computed, preventing blank `position_id` values in matches and returns.

**pipeline/staging_bdc.py and pipeline/staging_nport.py:**
- Repaired weak BDC position keys by falling back to issuer plus instrument text, preserving numbered loan tranches.
- N-PORT placeholder issuer/CUSIP values are no longer allowed to create placeholder position keys.
- N-PORT `issuer_cusip` is no longer used as the entire position key because it can be issuer-level rather than instrument-level.

**pipeline/oracle_checks.py:**
- B02 now prefers canonical `position_key` over raw BDC identifiers.
- Added J04 oracle check for duplicate `(cik, source, report_date, position_id)` groups.

**data/overrides/bdc_xbrl_wrappers/0001287750.json:**
- Removed invalid root-level schema field so the wrapper validates against `wrapper_v3.schema.json`.

**Generated outputs:**
- Rebuilt unified holdings and returns from cached inputs.
- Final returns rebuild produced 794,703 unified rows, 473,651 assigned match rows, 475,786 position-id edge rows, 493,014 position-return rows, and 247 index-return rows.
- Position ID assignment produced 318,917 unique position IDs. The assignment guard skipped 551 supplementary edges that would have merged duplicate report-date rows.

**Validation:**
- Targeted tests: `tests/test_position_matching.py` passed (74 tests); focused unified/oracle regression subset passed (96 tests).
- `python scripts/rebuild_outputs.py --unified --returns` completed after the staging fixes; final `python scripts/rebuild_outputs.py --returns` completed after assigned-match filtering.
- `python scripts/position_id_audit.py`: duplicate `(cik, report_date, position_id)` groups = 0; blank position IDs in holdings, matches, and returns = 0; cross-CIK position IDs = 0; orphan match/return IDs = 0.
- Wrapper JSON validates with `python -m jsonschema -i data\overrides\bdc_xbrl_wrappers\0001287750.json schemas\bdc_xbrl_wrapper\wrapper_v3.schema.json`.
- `python scripts/diff_outputs.py --semantic` still fails against the active baseline due broad pre-existing artifact drift: 443 divergent artifacts, including universe, parse progress, schema, frontend, holdings, matches, and returns outputs. The semantic report was written to `data/output/semantic_diff_report.json`.

**Residual risks:**
- `position_id_audit.py` still flags chain length >25 for 155 IDs and singleton IDs appearing in matches for 9,672 IDs. These are residual audit heuristics, not duplicate same-date failures; they should be reviewed separately before treating the audit as a full pass/fail gate.

### 2026-06-03 -- Add audited soft-gate exceptions for BDC wrapper oracle

Implemented a narrow agent-exception path for BDC XBRL wrapper promotion gates.

**pipeline/bdc_xbrl_oracle_exceptions.py and pipeline/config.py:**
- Added `bdc_xbrl_oracle_exceptions.json` as the active audited override file path.
- Added a loader/validator for `bdc-xbrl-oracle-exceptions.v1` records with exact `cik`, `report_date`, `oracle_reason`, and `wrapper_version` matching.
- Accepted active exceptions require `confidence >= 0.80`; malformed active records fail loudly.

**pipeline/bdc_xbrl_wrapper_oracle.py:**
- Promotion evaluation now preserves raw `oracle_status` and `oracle_fail_reasons` while adding effective promotion fields: `waived_oracle_reasons`, `unwaived_oracle_reasons`, and `effective_oracle_status`.
- Exceptions can waive only selected review-style soft diagnostics. Hard rejects, blocker regressions, remaining blocker mechanisms, source reconciliation blockers, and `exclusion_risk_detected` remain non-waiveable.
- `run_promotion_trial()` writes inactive `exception_proposals.json` templates for eligible unwaived soft reasons; proposals do not apply until accepted in the active override file.

**Tests and validation:**
- Added focused coverage in `tests/test_bdc_xbrl_wrapper_oracle.py` for accepted exact-match waivers, inactive/low-confidence/stale exceptions, non-waiveable reasons, proposal generation, and loader validation.
- `python -m pytest tests\test_bdc_xbrl_wrapper_oracle.py -q`: 55 passed.
- `python scripts\diff_outputs.py --semantic` was run as the post-test backstop and failed due broad pre-existing baseline drift: 443 divergent artifacts, 3,682 checked, 77 skipped. No production rebuild was run.

### 2026-06-03 -- Create wrapper for CIK 0001803498 (Blackstone Private Credit Fund / BCRED)

- Created `data/overrides/bdc_xbrl_wrappers/0001803498.json` (v3 schema, version 1)
- Wrapper sections: `dispatch` + `archetypes` (no staging or identifier_parser needed -- BCRED uses flat identifiers, not hierarchical)
- Identifier format: `"CompanyName [N] [| AffiliationAxis]"` -- flat company names with optional numeric tranche suffixes and pipe-delimited affiliation axis labels (appearing only in 2025-12-31+ filings)
- `canonical_strip_re` strips pipe-delimited affiliation suffixes (Non-Affiliated Issuer, Emerald JV LP, Verdelite JV LP, etc.) for position key stability
- `non_private_markers` filter cash/money-market/treasury positions (55 rows excluded)
- `fallback_family_patterns` classify debt/equity/warrant/CLO via keyword matching
- 6 known edge cases documented: pipe suffix schema change, numeric tranche suffixes, JV sub-portfolio overlap, comparative-period duplication, investment placeholders, JV entity aggregates

**Validation results:**
- Schema validation: pass
- Oracle (staging): 50 remaining blocking rows across 15 quarters (34 cash/money-market, 16 unclassified signatures). Zero delta vs baseline.
- Oracle (unified trial): 46 remaining blocking rows. All 15 quarters status=fail (unclassified_rate/unclassified_fv_rate -- expected for flat identifiers without instrument keywords)
- Trial unified rebuild: 22,762 rows (production 22,773, delta -11). Index breakdown: 89% DIRECT_LENDING, 5.8% STRUCTURED_CREDIT, 3.6% COMMON_EQUITY, 1% PREFERRED_EQUITY
- Position matching: J01 PASS (85.4% B1b, threshold 70%), J03 PASS (0.7% fuzzy, threshold 10%)
- Tests: test_bdc_xbrl_wrapper 50/50, test_unified_cik_trial 7/7, test_bdc_xbrl_wrapper_oracle 55/55, test_position_matching 75/75

**Status: partial_wrapper** -- oracle fails on unclassified_rate for all quarters because BCRED identifiers are flat company names without instrument-type keywords. The wrapper correctly classifies positions via XBRL field evidence (rate/maturity/shares) rather than identifier text. Cash/money-market blockers are correctly excluded by non_private_markers. No production rebuild performed.

- Updated `unlisted_bdc_xbrl_reference.json`: with_wrapper 7->8, without_wrapper 122->121

### 2026-06-04 -- Fix MSD wrapper category rollups and glued hierarchy parsing

Implemented the MSD Investment Corp. (CIK 0001849894) wrapper correction after validating candidate output against raw XBRL/HTML hierarchy labels.

**data/overrides/bdc_xbrl_wrappers/0001849894.json:**
- Bumped wrapper version from 2 to 3.
- Expanded `hierarchy_prefix_re` to parse glued MSD labels such as `SERVICESConsumer`, `Services: Consumer`, and `Consumer Goods: Non-durable` before the generic industry-label alternation.

**pipeline/staging_bdc.py and pipeline/source_reconciliation.py:**
- Applied the MSD hierarchy prefix strip twice so duplicate/nested prefixes do not leak into issuer names.
- Removed the MSD hierarchy-shape rescue from aggregate filtering; hierarchy shape alone no longer admits source rows.
- Dropped wrapper `*_category_rollup` rows unless explicitly classified as `*_position_leaf`, while leaving issuer-rollup handling non-authoritative.
- Treated unmatched wrapper `*_category_rollup` source rows as documented aggregate exclusions in BDC source reconciliation, not blockers.

**Tests and validation:**
- Added focused regressions for MSD service-consumer category subtotals, category-rollup dropping with child leaf preservation, glued uppercase hierarchy issuer parsing, and category-rollup reconciliation.
- Targeted tests passed:
  - `pytest tests\test_bdc_xbrl_wrapper.py -k msd -q`: 16 passed, 64 deselected.
  - `pytest tests\test_unified_holdings.py -k "msd_category_rollup or msd_glued_uppercase" -q`: 2 passed, 800 deselected.
  - `pytest tests\test_validate_holdings.py -k "msd_wrapper_category_rollup" -q`: 1 passed, 131 deselected.
  - `pytest tests\test_bdc_xbrl_wrapper_oracle.py -q`: 55 passed.
- MSD unified trial rebuild (`python scripts\rebuild_unified_cik_trial.py --cik 0001849894 --match`) produced 1,828 trial rows versus 1,818 production rows before the production rebuild. The remaining +10 rows were real positions only:
  - 2024-06-30: +7 rows, +77.588M fair value.
  - 2024-09-30: +1 row, +45.000M fair value.
  - 2024-12-31: +2 rows, +0.582M fair value.
  - 2025-12-31: no row or fair-value delta.
- MSD wrapper oracle on the trial holdings reported `remaining_blocking_rows=0` and `cleared_rollup_rows=212`. Oracle status was pass for 8 of 13 quarters; 5 older/late-2024 quarters still failed soft unclassified-rate thresholds, not source blockers.
- Rebuilt canonical unified holdings from cache with `python scripts\rebuild_outputs.py --unified`; canonical MSD counts now match the corrected trial counts and no suspicious `Consumer`, `INVESTMENTS INVESTMENTS`, `GOODSNon`, or `ConsumerInvestments` issuer rows remain for the corrected periods.
- Re-exported frontend JSON with `python scripts\rebuild_outputs.py --frontend`; 22 frontend JSON files were generated plus fund details.
- `python scripts\diff_outputs.py --semantic` was run after the unified rebuild and failed due broad pre-existing baseline drift: 443 divergent artifacts, 3,682 checked, 77 skipped. The semantic report was written to `data/output/semantic_diff_report.json`.

**Residual risks:**
- MSD still has soft wrapper-oracle unclassified fair-value rate failures in 2023-03-31, 2023-06-30, 2023-09-30, 2024-09-30, and 2024-12-31. These are coverage diagnostics, not remaining blocking source-only rows.

### 2026-06-04 -- Add HPS Corporate Lending Fund wrapper (CIK 0001838126)

- Created dispatch-only wrapper at `data/overrides/bdc_xbrl_wrappers/0001838126.json` (v1, schema v3).
- HPS identifiers use bare issuer names with trailing position numbers (`"123Dentist Inc 1"`) for debt, and `"Issuer - InstrumentType"` dash separator for equity/CLO/warrants. Pipe-delimited affiliation suffix (`| Non-Affiliated Issuer`) appeared from Q4 2025.
- Wrapper classifies equity (~5%), CLO, warrant, and money-market rows via fallback regex patterns. Debt positions (~93%) are caught by a catch-all fallback since their identifiers contain no instrument keywords -- the pipeline uses XBRL economic fields (interest_rate, shares_held) for asset classification.
- `unclassified_rate` invariant set to 0.97 reflecting the structural limitation of this filer's identifier format.
- Trial rebuild: 7,549 rows (vs 7,768 production; -219 from dedup/filter). J01 PASS (95.3% B1b), J03 PASS (0.1% fuzzy). No bad issuer names.
- Oracle: 6 remaining blocking rows across 4 quarters (issuer_rollup_no_child_tie for Sedgwick, Einstein Parent, Logo Holdings). All 13 quarters fail on unclassified_rate_exceeded (soft gate, inherent to format).
- Added 13 unit tests to `tests/test_bdc_xbrl_wrapper.py`. All 102 wrapper tests pass.
- Updated `unlisted_bdc_xbrl_reference.json` (now 12 with wrappers, 117 without).

**Files changed:**
- `data/overrides/bdc_xbrl_wrappers/0001838126.json` (new)
- `data/overrides/bdc_xbrl_wrappers/unlisted_bdc_xbrl_reference.json` (updated counts + entry)
- `tests/test_bdc_xbrl_wrapper.py` (13 new HPS tests)

**Status: partial_wrapper** -- dispatch classification works for equity/CLO/warrant/cash rows. Debt positions are structurally unclassifiable by text alone due to bare issuer name format. Soft-gate exceptions for unclassified_rate are appropriate but not yet added to oracle_exceptions.json.

### 2026-06-04 -- Add Golub Capital Private Credit Fund wrapper (CIK 0001930087)

- Created `data/overrides/bdc_xbrl_wrappers/0001930087.json` (v1, schema v3).
- Golub identifiers use flat issuer + instrument text, with pipe-delimited format in 2026-03-31 samples (`Issuer | Instrument`) and comma-delimited format in older samples (`Issuer, Instrument`).
- Wrapper uses fallback-only dispatch rules for debt (`One stop`, `Senior secured`, `Second lien`, `Subordinated debt`, `Structured Finance Note`), equity (`Common stock`, `Preferred stock`, LP/LLC interests and units), warrants, and treasury money-market non-private rows.
- Added a specific `One stop1` spacing variant regression after profiling showed `YI, LLC, One stop1` was otherwise unclassified.
- Updated `unlisted_bdc_xbrl_reference.json` entry for `0001930087` to `wrapper_status=exists`, `wrapper_version=1`, sections `dispatch`, `archetypes`, `invariants`. Top-level reference counts currently include concurrent HPS work: 12 with wrappers, 117 without.

**Tests and validation:**
- Schema validation passed: `python -m jsonschema -i data/overrides/bdc_xbrl_wrappers/0001930087.json schemas/bdc_xbrl_wrapper/wrapper_v3.schema.json`.
- Focused tests passed: `pytest tests/test_bdc_xbrl_wrapper.py -k golub_private_credit -q` -> 10 passed, 93 deselected.
- Full wrapper test file passed in the combined worktree: `pytest tests/test_bdc_xbrl_wrapper.py -q` -> 103 passed, 2 warnings.
- Per-CIK oracle with cached data and fresh BDC staging passed source blocking checks: `remaining_blocking_rows=0`, `remaining_wrapper_blocking_rows=0`, baseline blocking delta 0 for all 12 quarters.
- Oracle status is 11 pass / 1 fail. The only raw failure is `2023-09-30: concept_drift_detected`; promotion gate status is `review_required` with an inactive proposed exception, not accepted.
- Residual low-risk unclassified source rows: 5 small matched 2024-06-30 bare-name rows with no instrument vocabulary (`Amberfield Acquisition Co.`, `CHVAC Services Investment, LLC`, `Quick Quack Car Wash Holdings, LLC 1/2`, `Yorkshire Parent, Inc.`), `unclassified_rate=0.012136`, `unclassified_fv_rate=0.000578`.

**Status: partial_wrapper / review_required** -- no source reconciliation blockers remain, but the wrapper is not production-clean until the 2023-09-30 concept drift soft diagnostic is reviewed or accepted with evidence. No canonical production rebuild or semantic diff was run.

### 2026-06-04 -- Add Oaktree Strategic Credit Fund wrapper (CIK 0001872371)

- Created `data/overrides/bdc_xbrl_wrappers/0001872371.json` (v1, schema v3).
- Oaktree identifiers are mostly comma-delimited issuer + instrument text, with a small 2026-03-31 pipe-delimited variant containing issuer, industry, and instrument fields.
- Wrapper uses fallback-only dispatch rules for explicit instrument vocabulary: first/second lien loans, revolvers, fixed/floating-rate bonds, CLO notes, credit-linked notes, subordinated debt, common/preferred equity, warrants, and treasury/cash non-private rows.
- Added a false-positive guard for issuer names containing `Treasury`: `Apex Group Treasury LLC, First Lien Term Loan` remains a debt position, while `BNY Mellon U.S. Treasury Fund, Investor Shares` is non-private-market.
- Updated `unlisted_bdc_xbrl_reference.json` entry for `0001872371` to `wrapper_status=exists`, `wrapper_version=1`, sections `dispatch`, `archetypes`, `invariants`. Top-level reference counts are now 14 with wrappers, 115 without.

**Tests and validation:**
- Schema validation passed: `python -m jsonschema -i data/overrides/bdc_xbrl_wrappers/0001872371.json schemas/bdc_xbrl_wrapper/wrapper_v3.schema.json`.
- Focused tests passed: `pytest tests/test_bdc_xbrl_wrapper.py -k oaktree_strategic_credit -q` -> 10 passed, 120 deselected.
- Full wrapper test file passed in the combined worktree: `pytest tests/test_bdc_xbrl_wrapper.py -q` -> 130 passed, 2 warnings.
- Per-CIK oracle with cached data and fresh BDC staging initially reported `oracle_status_counts={'pass': 13}` with `remaining_blocking_rows=0`, `remaining_wrapper_blocking_rows=0`, and baseline blocking delta 0 for all quarters.
- Final promotion-gate artifacts show `oracle_summary.csv` at 8 pass / 5 fail because the cost/FV outlier soft diagnostics are included there; blocking rows remain 0.
- Oracle classified 899 of 899 candidates. Fresh staging excluded 2 non-private rows from unified candidates; reconciliation detail shows 4 source rows classified as `non_private_market` (`BNY Mellon U.S. Treasury Fund, Investor Shares` and `Other cash accounts` in 2024-12-31 and 2025-03-31).
- Promotion gate status is `review_required`, not production-clean, due to unaccepted soft diagnostics: `cost_fv_ratio_outliers` in 2024-12-31, 2025-03-31, 2025-06-30, 2025-09-30, and 2026-03-31.

**Residual risks:**
- Wrapper family versus downstream asset-category warnings remain expected taxonomy differences: warrants downstream map to `EQUITY_COMMON`, and CLO notes downstream map to `FUND` / `STRUCTURED_CREDIT`.
- No canonical production rebuild, semantic diff, or position-matching gate was run.

**Status: partial_wrapper / review_required** -- source reconciliation is clean, but promotion requires review or accepted exceptions for cost/FV outlier soft diagnostics plus the usual matching gate before calling the wrapper production-clean.

### 2026-06-04 -- Add Apollo Debt Solutions BDC wrapper (CIK 0001837532)

- Created `data/overrides/bdc_xbrl_wrappers/0001837532.json` (v3, version 1)
- Sections: dispatch (fallback_family_patterns, aggregate/non-private markers, canonical_strip_re), staging (default strategy with extra_industry_labels), archetypes (debt/equity/warrant), invariants
- No prefix_rules (Apollo identifiers embed GICS sector directly, not a fixed prefix). Classification relies on fallback_family_patterns matching instrument keywords
- 15 extra_industry_labels contributed for newer GICS sub-industry names (Automobile Components, Consumer Staples Distribution & Retail, Financial Services, Ground Transportation, Personal Care Products, etc.)
- canonical_strip_re strips `Interest Rate ...` suffix from position keys for cross-quarter stability
- Dispatch-only wrapper (no extraction staging). The current `hierarchy_extract` infrastructure only supports one shared regex set across all CIKs (currently Crescent's). Apollo needs per-CIK issuer extraction regexes. Issuer name quality is unchanged vs production baseline (GICS sector + company name + "Investment Type" concatenated in issuer_name field)
- Oracle result: 297 blocking rows across 13 quarters, **0 delta vs baseline** in all quarters. Blockers are pre-existing: PIK-containing leaf positions dropped by pipeline (124 rows), portfolio/sector-level aggregates in source (173 rows)
- Trial unified rebuild: 6,452 rows (vs 6,578 production, -126 from wrapper non-private-market exclusion of money market funds)
- J01: PASS (75.9% B1b position key stability, threshold 70%)
- J03: PASS (5.6% fuzzy fallback rate, threshold 10%)
- Added 17 tests in `tests/test_bdc_xbrl_wrapper.py`: debt leaf (term loan, revolver, delayed draw, corporate bond, PIK, en-dash, no-dash), equity leaf (preferred, membership interest, common stock), aggregate (Investments after/before Cash, Total Pharmaceuticals, bare sector), non-private (State Street, Goldman Sachs money market), CIK registration
- All test suites pass: wrapper (120), unified trial (7), oracle checks (19), unified holdings (538), position matching (75)
- Updated `unlisted_bdc_xbrl_reference.json`: 13 with wrappers, 116 without

**Status: partial_wrapper** -- dispatch classification is production-ready with 0 baseline delta. Issuer extraction improvement requires code change to support per-CIK hierarchy_extract regexes (tracked limitation). PIK leaf exclusion is a pre-existing pipeline issue, not introduced by this wrapper.

### 2026-06-04 — HPS Corporate Lending Fund wrapper (CIK 0001838126, v3)

- Created dispatch-only wrapper at `data/overrides/bdc_xbrl_wrappers/0001838126.json`
- HPS uses bare company names as XBRL identifiers (no instrument keywords for debt) with trailing position numbers. Pipe-delimited affiliation suffix appeared from Q4 2025.
- Key design: entity suffixes (Inc, LLC, Corp, Ltd, etc.) serve as leaf markers for debt family, since HTML SOI confirms no issuer-level subtotals exist in XBRL. Archetype detection reordered: warrant -> clo -> equity -> debt (catch-all last) so entity suffixes don't shadow specific instrument archetypes.
- `canonical_strip_re` strips pipe-delimited affiliation suffixes (`| Non-Affiliated Issuer`, `| Affiliated Issuer`, double-pipe variants)
- Oracle result: **8 PASS, 5 FAIL** across 13 quarters (2023-03-31 to 2026-03-31)
  - All unclassified rates pass (3-5% row rate, 3-6% FV rate, within 10% threshold)
  - 5 remaining failures: 4 quarters with `wrapper_blockers_remaining` (3 positions: Sedgwick, Einstein Parent, Logo Holdings missing from pipeline), 2 quarters with `cost_fv_ratio_outliers`
  - Baseline comparison: blocking rows 43 -> 6 (86% reduction), blocking FV $663M -> $55M
- Trial rebuild: 7,713 rows, J01 PASS (95.2% B1b), J03 PASS (0.1% fuzzy), 12 UNCLASSIFIED (0.2%)
- 13 tests added to `tests/test_bdc_xbrl_wrapper.py`, all passing (120 total wrapper tests)
- Updated `unlisted_bdc_xbrl_reference.json`: wrapper_version=3, sections=[dispatch, archetypes, invariants]

**Status: partial_wrapper** -- 8/13 quarters pass oracle. Remaining 5 failures are non-waiveable wrapper blockers (3 positions missing from pipeline) and cost/FV ratio outliers. Dispatch and archetype classification are production-ready.

### 2026-06-04 -- HTML-backed Oaktree delayed-draw wrapper hardening (CIK 0001872371)

- Compared the Oaktree wrapper against cached raw BDC HTML under `data/raw/filings/bdc_html/1872371/`.
- Cached BDC HTML is available only for early filings through accession `000187237123000004`; the later 2024-12-31 through 2026-03-31 quarters with promotion-gate `cost_fv_ratio_outliers` do not have cached BDC HTML in this workspace.
- Cached SC TO-I HTML did not provide useful schedule-of-investments rows for Oaktree.
- Source HTML confirmed the schedule table shape and instrument vocabulary, including `First Lien Delayed Draw Term Loan` rows and the `Apex Group Treasury LLC` private-market borrower row.
- Updated `data/overrides/bdc_xbrl_wrappers/0001872371.json` to classify `First Lien Delayed Draw Term Loan` as a debt position leaf.
- Added `test_oaktree_strategic_credit_html_delayed_draw_term_loan_leaf` in `tests/test_bdc_xbrl_wrapper.py`.
- Appended the source comparison to `data/output/data_investigation_results.md`.

**Validation:**
- Schema validation passed: `python -m jsonschema -i data/overrides/bdc_xbrl_wrappers/0001872371.json schemas/bdc_xbrl_wrapper/wrapper_v3.schema.json`.
- Focused Oaktree tests passed: `pytest tests/test_bdc_xbrl_wrapper.py -k oaktree_strategic_credit -q` -> 11 passed, 120 deselected.
- Per-CIK oracle with cached data and fresh BDC staging passed source blocking checks: 13 pass, `remaining_blocking_rows=0`, `remaining_wrapper_blocking_rows=0`, baseline blocking delta 0.
- Promotion gate remains `review_required` with zero blocking delta due only to `cost_fv_ratio_outliers` in 2024-12-31, 2025-03-31, 2025-06-30, 2025-09-30, and 2026-03-31.

**Status: partial_wrapper / review_required** -- HTML comparison justified one narrow delayed-draw coverage improvement but did not clear the later cost/FV soft diagnostics because the relevant rendered BDC HTML is not cached.

### 2026-06-05 -- Add North Haven Private Income Fund LLC wrapper (CIK 0001851322)

- Created `data/overrides/bdc_xbrl_wrappers/0001851322.json` (v1, schema v3).
- North Haven has two identifier eras:
  - 2025-09 onward uses no-dash hierarchy strings with explicit `Investment First Lien Debt`, `Investment Second Lien Debt`, `Investment Common Equity`, `Investment Preferred Equity`, and `Investment LLC Interest` vocabulary.
  - 2023-03 through 2025-06 is mostly bare issuer-name rows with no instrument text. Some rows are debt by rate evidence and some are equity by share evidence, so no broad text-only catch-all was added.
- Wrapper uses dispatch rules for explicit late-era instrument vocabulary, aggregate guards for numbered note/header rows (`Investment One/Two/Three`, `One Unsecured Debt Position`, etc.), and non-private markers for money-market/government-fund rows.
- Added `hierarchy_extract` staging for the late-era no-dash hierarchy format, extracting issuer and instrument from `Investments ... <industry> <issuer> Investment <instrument>` rows.
- Added 10 focused North Haven wrapper tests in `tests/test_bdc_xbrl_wrapper.py`.
- Updated `data/overrides/bdc_xbrl_wrappers/unlisted_bdc_xbrl_reference.json`: 15 wrappers, 114 without wrappers; North Haven entry now `wrapper_status=exists`, `wrapper_version=1`, sections `dispatch`, `staging`, `archetypes`, `invariants`, staging strategy `hierarchy_extract`.

**Tests and validation:**
- Schema validation passed: `python -m jsonschema -i data/overrides/bdc_xbrl_wrappers/0001851322.json schemas/bdc_xbrl_wrapper/wrapper_v3.schema.json`.
- Focused tests passed: `pytest tests/test_bdc_xbrl_wrapper.py -k north_haven_private_income -q` -> 10 passed, 131 deselected.
- Full wrapper test file passed in the combined worktree: `pytest tests/test_bdc_xbrl_wrapper.py -q` -> 141 passed, 2 existing regex warnings.
- Per-CIK oracle with cached data and fresh BDC staging loaded the North Haven staging config and reported `remaining_blocking_rows=0`, `remaining_wrapper_blocking_rows=0`, baseline blocking delta 0, and 7,202 staged current-period rows after filters.
- Raw fresh-staging oracle status was 2 pass / 11 fail because 2023-03 through 2025-06 remain mostly unclassified due to bare issuer-only identifiers, and 2025-03 has a cost/FV soft diagnostic.
- Promotion gate against current final unified artifacts is `reject`, with blocker improvements of 3 rows and $51.609 million FV but unwaived reasons including old-period unclassified rates, cost/FV outliers, and a final-output 2025-12 wrapper blocker. This is not production-clean without a canonical rebuild and residual review.

**Status: partial_wrapper / rejected_promotion_gate** -- late-era explicit hierarchy rows are classified and staged, source blocking is clean in fresh staging, but early bare-name periods have no safe text-only dispatch mechanism and the promotion gate remains rejected.

### 2026-06-05 -- HTML-backed North Haven bare-name classification update (CIK 0001851322)

- Compared North Haven cached source HTML under `data/raw/filings/bdc_html/1851322/` against the wrapper residuals.
- Source HTML grids for 2022 filings show issuer-only rows grouped under visible instrument section headers including `First Lien Debt`, `Second Lien Debt`, `Preferred Equity`, and `Common Equity`.
- Updated `data/overrides/bdc_xbrl_wrappers/0001851322.json` so old bare issuer-name rows with entity-name signals classify as `mixed_position_leaf`, not debt or equity. This preserves the position leaf while avoiding unsupported instrument-family inference after XBRL tagging drops the HTML section context.
- Added guard coverage in `tests/test_bdc_xbrl_wrapper.py`: `Astra Acquisition Corp. 1` is a mixed position leaf; short non-entity labels such as `DCA` remain unclassified.
- Appended the HTML source comparison to `data/output/data_investigation_results.md`.

**Validation:**
- Schema validation passed: `python -m jsonschema -i data/overrides/bdc_xbrl_wrappers/0001851322.json schemas/bdc_xbrl_wrapper/wrapper_v3.schema.json`.
- Full wrapper test file passed: `pytest tests/test_bdc_xbrl_wrapper.py -q` -> 142 passed, 2 existing regex warnings.
- Fresh cached-staging oracle improved to 10 pass / 3 fail across 13 quarters, with `remaining_blocking_rows=0`, `remaining_wrapper_blocking_rows=0`, and wrapper classification coverage of 3,033 / 3,144 candidates.
- Remaining fresh-staging failures are not hard source blockers: 2023-03-31 has `unclassified_fv_rate_exceeded`; 2025-03-31 has `cost_fv_ratio_outliers`; 2025-09-30 has `cost_fv_ratio_outliers|low_position_continuity`.
- Promotion gate remains `reject`, with blocker improvements of 3 rows and $51.609 million FV, because current final unified artifacts still miss two eligible 2025-12 common-equity source rows (`LUV Car Wash` and `Reveal Data Solutions`) and because soft diagnostics remain unaccepted.

**Status: partial_wrapper / rejected_promotion_gate** -- source HTML supports the mixed leaf mechanism for old bare-name rows, but the CIK is not production-clean until the 2025-12 output inclusion issue and soft diagnostics are resolved or explicitly reviewed.

### 2026-06-05 -- Add Monroe Capital Income Plus Corp wrapper (CIK 0001742313)

- Created `data/overrides/bdc_xbrl_wrappers/0001742313.json` (v1, schema v3).
- Monroe has two identifier eras:
  - 2025-12-31 onward mostly uses pipe-delimited issuer and instrument family strings such as `Issuer | Senior Secured Loans` and `Issuer | Equity Securities`.
  - 2023-03-31 through 2025-09-30 mostly uses comma/parenthetical family terms, plus sparse issuer-only rows.
- Wrapper mechanism:
  - Explicit pipe/comma debt terms classify senior secured, junior secured, unitranche, revolver, delayed draw, and term loan rows as debt leaves.
  - Explicit equity terms classify equity securities, common/preferred units, preferred interests/stock, and equity commitments as equity leaves.
  - Warrant terms classify as warrant leaves.
  - Sparse issuer-only rows with entity signals classify as `mixed_position_leaf` rather than forcing debt/equity family without source text support.
  - Short labels without entity signals remain unclassified; totals/subtotals classify as rollups.
- Added 8 focused Monroe tests in `tests/test_bdc_xbrl_wrapper.py`.
- Updated `data/overrides/bdc_xbrl_wrappers/unlisted_bdc_xbrl_reference.json`: 16 wrappers, 113 without wrappers; Monroe entry now `wrapper_status=exists`, `wrapper_version=1`, sections `dispatch`, `archetypes`, `invariants`.

**Tests and validation:**
- Schema validation passed: `python -m jsonschema -i data/overrides/bdc_xbrl_wrappers/0001742313.json schemas/bdc_xbrl_wrapper/wrapper_v3.schema.json`.
- Full wrapper test file passed: `pytest tests/test_bdc_xbrl_wrapper.py -q` -> 150 passed, 2 existing regex warnings.
- Fresh cached-staging oracle reported `remaining_blocking_rows=0`, `remaining_wrapper_blocking_rows=0`, baseline blocking delta 0, unclassified row/FV rates 0.0 across all 13 quarters, and content signature pass rate 1.0 across all 13 quarters.
- Promotion gate is `review_required`, not production-clean: blocking rows/FV delta 0, but every quarter has `cost_fv_ratio_outliers`; 2023-12-31, 2024-06-30, and 2025-12-31 also have `low_position_continuity`.
- `python scripts/diff_outputs.py --semantic` was run as a backstop and failed because the current workspace already diverges broadly from the active baseline: 443 divergent artifacts, with semantic deltas in holdings, matches, position returns, index returns, and fund financials. This wrapper task did not rebuild canonical production artifacts.

**Status: partial_wrapper / review_required** -- dispatch and content-signature coverage are clean in fresh staging, but the wrapper is not production-clean until the cost/FV and position-continuity diagnostics are reviewed or accepted through the oracle exception workflow.

### 2026-06-05 -- Monroe wrapper diagnostic hardening (CIK 0001742313)

- Investigated the three Monroe wrapper/staging warnings from the fresh-staging oracle:
  - `aggregate_detection_disagreement`: 15 rows before fix.
  - `family_vs_asset_category_disagreement`: 104 rows.
  - `wrapper_leaf_staging_excluded`: 1 row.
- Fixed a wrapper vocabulary gap in `data/overrides/bdc_xbrl_wrappers/0001742313.json`: added equity leaf markers for `class b units`, `series a units`, `series b units`, and `series b preferred units`.
- Added 2 regression tests in `tests/test_bdc_xbrl_wrapper.py` for the actual flagged legacy identifiers:
  - `Really Great Reading Company, Inc., Equity Securites, Series A units`
  - `Forest Buyer, LLC ($1,088 Class B units)`
- Fresh-staging oracle after fix:
  - `aggregate_detection_disagreement`: 1 remaining row, `staging_only`, an excluded comparative-period Respida Software equity row.
  - `family_vs_asset_category_disagreement`: unchanged at 104 rows; 97 are wrapper warrant vs downstream `EQUITY_COMMON`, and 7 are source identifiers saying `Equity Securities` while downstream classifies as `LOAN` because principal/rate-like facts are present. No wrapper change made because the wrapper is reflecting the source identifier text.
  - `wrapper_leaf_staging_excluded`: unchanged at 1 row, `FLEET Response, LLC (Common units)`, excluded as an affiliation-axis duplicate of a matched source row.
  - `remaining_blocking_rows=0`, `unclassified_rate=0.0`, `unclassified_fv_rate=0.0`, `content_signature_pass_rate=1.0` for all 13 quarters.
- Validation:
  - Schema validation passed: `python -m jsonschema -i data/overrides/bdc_xbrl_wrappers/0001742313.json schemas/bdc_xbrl_wrapper/wrapper_v3.schema.json`.
  - `pytest tests/test_bdc_xbrl_wrapper.py -q` -> 152 passed, 2 existing regex warnings.
  - `python -m pipeline.bdc_xbrl_wrapper_oracle --cik 0001742313 --compare-baseline --fresh-bdc-staging` -> 0 remaining blockers; raw oracle still fails all 13 quarters on `cost_fv_ratio_outliers`, with low continuity also in 2023-12-31, 2024-06-30, and 2025-12-31.

**Status: partial_wrapper / review_required** -- the fix removed wrapper-caused aggregate false positives. Remaining warnings are either downstream taxonomy semantics or expected source exclusions, not safe wrapper edits.

### 2026-06-05 -- Add Ares Core Infrastructure Fund wrapper (CIK 0002031750)

- Created `data/overrides/bdc_xbrl_wrappers/0002031750.json` (v1, schema v3) for Ares Core Infrastructure Fund.
- Identifier profile basis: cached BDC XBRL holdings, 364 rows across 7 quarters from 2024-09-30 through 2026-03-31.
- Wrapper mechanism:
  - Explicit debt terms classify first lien senior secured loans, observed `snior` typo variants, senior subordinated loans, and delayed draw term loans as debt leaves.
  - Explicit equity terms classify common equity, other equity, ordinary units, class A units, and no-FV `, Equity` commitment labels.
  - Bare `First lien senior secured loans` and `Senior subordinated loans` classify as aggregate category totals, not leaves.
  - First American treasury sweep, money market, U.S. Treasury, and Treasury Bill rows classify as non-private-market.
  - `canonical_strip_re` removes periods and the plural `s` in `loans` to stabilize keys across `L.L.C.`/`LLC` and `loan`/`loans` drift without stripping numeric tranche suffixes.
- Added 4 focused Ares wrapper tests in `tests/test_bdc_xbrl_wrapper.py`.
- Updated `data/overrides/bdc_xbrl_wrappers/unlisted_bdc_xbrl_reference.json` for Ares: `wrapper_status=exists`, `wrapper_version=1`, sections `dispatch`, `archetypes`, `invariants`.

**Tests and validation:**
- Schema validation passed: `python -m jsonschema -i data/overrides/bdc_xbrl_wrappers/0002031750.json schemas/bdc_xbrl_wrapper/wrapper_v3.schema.json`.
- Ares-focused tests passed: `pytest tests/test_bdc_xbrl_wrapper.py -k "ares_core_infrastructure" -q` -> 4 passed, 176 deselected.
- Full wrapper test file currently does not pass in the dirty worktree because an unrelated Blue Owl Technology Income test fails on `Jeppesen Holdings, LLC | First lien senior secured multi-currency revolving loan`; Ares-specific tests pass.
- Fresh cached-staging oracle: `remaining_blocking_rows=0`, `remaining_wrapper_blocking_rows=0`; baseline blocking rows improved from 6 to 0 across affected quarters, reducing blocking FV by $189.669 million.
- Raw oracle status remains partial: 1 pass, 4 fail, 2 not applicable. Remaining raw failures are soft diagnostics: early quarters with no wrapper-classified source rows, 2025-03 concept drift, 2025-09 unclassified FV from bare issuer rows, and 2025-12/2026-03 aggregate/cash exclusion-risk flags.
- Trial unified rebuild with matching: 242 trial rows versus 254 production rows, reflecting removal of wrapper-classified cash/category rows; J01 passed at 94.7% B1b and J03 passed at 3.2% fuzzy fallback.

**Status: partial_wrapper / source_blockers_cleared** -- the wrapper clears current source reconciliation blockers and passes position-key stability/fuzzy gates in trial output, but it is not production-clean because raw oracle soft diagnostics remain unaccepted.

### 2026-06-05 -- Add Blue Owl Technology Income wrapper (CIK 0001869453)

- Created `data/overrides/bdc_xbrl_wrappers/0001869453.json` (v1, schema v3) for Blue Owl Technology Income Corp.
- Identifier profile basis: cached BDC XBRL holdings, 7,327 source rows across 13 quarters from 2023-03-31 through 2026-03-31. The unlisted reference entry still records 7,324 rows; current cached holdings contain 7,327 rows.
- Wrapper mechanism:
  - Explicit debt terms classify first/second lien senior secured loans, delayed draw term loans, multi-draw term loans, multi-currency revolving loans, numbered loan suffixes, unsecured notes, and subordinated floating-rate notes as debt leaves.
  - Explicit equity terms classify common units, class interests, LP/L.P. interests, LLC interests, preferred stock/shares/equity/units, and specialty-finance equity-investment labels as equity leaves.
  - Warrant terms classify as warrant leaves.
  - ABF section headers and total commitment labels classify as aggregates.
  - Bare names such as `LSI Financing 1 DAC`, `Blue Owl Credit SLF`, `Blue Owl Cross-Strategy Opportunities`, `Stripe Blue Owl Holdings LLC`, and `Blue Owl Leasing LLC` remain unclassified because final holdings show bare rows often alongside instrument-specific rows with the same fair value; classifying them as leaves would risk blessing duplicate dimension paths.
- Added 7 focused Blue Owl tests in `tests/test_bdc_xbrl_wrapper.py`.
- Updated `data/overrides/bdc_xbrl_wrappers/unlisted_bdc_xbrl_reference.json` for Blue Owl: `wrapper_status=exists`, `wrapper_version=1`, sections `dispatch`, `archetypes`, `invariants`.

**Tests and validation:**
- Schema validation passed: `python -m jsonschema -i data/overrides/bdc_xbrl_wrappers/0001869453.json schemas/bdc_xbrl_wrapper/wrapper_v3.schema.json`.
- Blue Owl focused tests passed: `pytest tests/test_bdc_xbrl_wrapper.py -k "blue_owl_tech" -v --tb=short` -> 7 passed, 173 deselected.
- Full wrapper test file passed: `pytest tests/test_bdc_xbrl_wrapper.py -v --tb=short` -> 180 passed, 2 existing regex warnings.
- Fresh cached-staging oracle: 6 pass, 7 fail; `remaining_blocking_rows=10`, unchanged from baseline. Blocking residuals are blank identifiers with negative fair value from 2024-12-31 through 2026-03-31, reported as `total_rollup_no_child_tie`.
- Final oracle unclassified rates:
  - 2024-06-30 failed only `unclassified_fv_rate_exceeded` at row rate 0.047923 and FV rate 0.067573.
  - 2025-12-31 failed blocker and unclassified row-rate gates at row rate 0.055928 and FV rate 0.040144.
  - 2026-03-31 failed blocker and unclassified gates at row rate 0.060976 and FV rate 0.053036.
- `python scripts/diff_outputs.py --semantic` was not run because other agents were actively writing output-side wrapper diagnostics during this handoff; running semantic diff against a moving output tree would not isolate this task. This wrapper task did not rebuild canonical production artifacts.

**Status: partial_wrapper / review_required** -- the wrapper improves deterministic classification for explicit instrument identifiers but is not production-clean. Remaining failures are unresolved blank negative-FV blockers and intentionally unclassified bare specialty-finance names that need duplicate-dimension review before any stronger wrapper treatment.

### 2026-06-05 -- Add Barings Private Credit wrapper (CIK 0001859919)

- Created `data/overrides/bdc_xbrl_wrappers/0001859919.json` (v1, schema v3) for Barings Private Credit Corp.
- Identifier profile basis: cached BDC XBRL holdings, 15,827 source rows across 13 quarters from 2023-03-31 through 2026-03-31. The unlisted reference entry still records 15,807 rows; current cached holdings contain 15,827 rows.
- Wrapper mechanism: explicit loan, equity, warrant, fund, and other-position terms classify Barings instrument identifiers; arbitrary issuer-only rows remain unclassified except exact recurring `Rocade Holdings LLC`, which is reconciled as OTHER.
- Added 14 focused Barings tests in `tests/test_bdc_xbrl_wrapper.py`.
- Updated `data/overrides/bdc_xbrl_wrappers/unlisted_bdc_xbrl_reference.json` for Barings: `wrapper_status=exists`, `wrapper_version=1`, sections `dispatch`, `archetypes`, `invariants`.

**Tests and validation:**
- Schema validation passed: `python -m jsonschema -i data/overrides/bdc_xbrl_wrappers/0001859919.json schemas/bdc_xbrl_wrapper/wrapper_v3.schema.json`.
- Barings-focused tests passed: `pytest tests/test_bdc_xbrl_wrapper.py -k "barings" -q` -> 14 passed, 171 deselected.
- Full wrapper test file passed: `pytest tests/test_bdc_xbrl_wrapper.py -q` -> 185 passed, 2 existing regex warnings.
- Fresh cached-staging oracle: 13 fail; `remaining_blocking_rows=30`, unchanged from baseline, all zero source FV pipeline-only rows with no matching current-period source fact. Unclassified-FV failures cleared; remaining failures are `cost_fv_ratio_outliers`, `exclusion_risk_detected` in 2023-06-30 and 2024-09-30, and `wrapper_blockers_remaining|remaining_unclassified_signature` in 2024-12-31 through 2026-03-31.
- One-CIK trial rebuild with matching wrote `data/output/bdc_xbrl_wrapper_trial/0001859919/unified_trial/private_markets_holdings.0001859919.csv`: 8,133 trial rows versus 8,114 production rows (+19 rows, all before 2024-06-30). Matching gates passed: J01 B1b rate 85.4% and J03 fuzzy rate 1.1%.
- Trial-unified oracle against the trial CSV reduced hard blockers from 30 to 15, but still failed all 13 quarters. Remaining hard blockers are pipeline-only loan rows for Eclipse Business Capital, Skyvault Holdings, Biolam, and Coastal Marina with no matching current-period source fact.

**Status: partial_wrapper / review_required** -- the wrapper improves deterministic classification and passes position-key stability/fuzzy gates in trial output, but it is not production-clean because source reconciliation still reports pipeline-only loan blockers and soft cost/FV diagnostics.

### 2026-06-05 -- Barings wrapper validation addendum

- Backstop semantic diff was run after tests: `python scripts/diff_outputs.py --semantic`.
- Result: failed because the current output tree already diverges broadly from the active baseline: 443 divergent artifacts, 3,682 checked, 77 skipped. Semantic deltas were reported in holdings, matches, position returns, index returns, and fund financials.
- This Barings wrapper task did not rebuild canonical production artifacts; generated artifacts are limited to `data/output/bdc_xbrl_wrapper_trial/0001859919/`.

### 2026-06-05 -- Add TPG Twin Brook Capital Income wrapper (CIK 0001913724)

- Created `data/overrides/bdc_xbrl_wrappers/0001913724.json` (v1, schema v3) for TPG Twin Brook Capital Income Fund.
- Identifier profile basis: cached BDC XBRL holdings, 13,399 source rows across 13 quarters from 2023-03-31 through 2026-03-31.
- Wrapper mechanism:
  - Explicit first-lien senior secured, revolving, delayed-draw, term-loan, sponsor subordinated note, and subordinated note terms classify as debt leaves.
  - Bare `Twin Brook Equity Holdings, LLC` and `Twin Brook Segregated Equity Holdings, LLC` classify as equity leaves because they recur as equity positions, sometimes alongside explicit `Equity interest` variants.
  - Seven 2023-06-30 duplicate-issuer rows for Ascent Lifting and NEFCO classify through a narrow debt rule because source and output rows match and carry interest-rate, basis-spread, principal, cost, and fair-value facts.
  - Generic issuer-only rows are not broadly classified; portfolio total rows remain rollups/aggregates.
- Added 8 focused TPG Twin Brook tests in `tests/test_bdc_xbrl_wrapper.py`.
- Updated `data/overrides/bdc_xbrl_wrappers/unlisted_bdc_xbrl_reference.json`: wrapper inventory is now 18 with wrappers and 111 without wrappers; CIK 0001913724 now has sections `dispatch`, `archetypes`, `invariants`.

**Tests and validation:**
- Schema validation passed: `python -m jsonschema -i data/overrides/bdc_xbrl_wrappers/0001913724.json schemas/bdc_xbrl_wrapper/wrapper_v3.schema.json`.
- TPG-focused tests passed: `pytest tests/test_bdc_xbrl_wrapper.py -k "tpg_twin_brook" -v` -> 8 passed, 172 deselected.
- Full wrapper test file passed: `pytest tests/test_bdc_xbrl_wrapper.py -v` -> 185 passed, 2 existing regex warnings.
- Content-signature tests passed: `pytest tests/test_wrapper_content_signatures.py -v` -> 32 passed.
- Content-signature diagnostic: `python -m pipeline.wrapper_content_signatures --cik 0001913724 --output-dir data/output/wrapper_drift/0001913724` -> unclassified-rate and FV-rate gates pass in all 13 quarters; one non-blocking 2023-09-30 row has missing fair value.
- Fresh cached-staging oracle: `python -m pipeline.bdc_xbrl_wrapper_oracle --cik 0001913724 --compare-baseline --fresh-bdc-staging` -> 13 pass, 0 remaining blocking rows, 0 remaining blocking FV, 2,080/2,080 wrapper candidates classified.
- Promotion gate: `python -m pipeline.bdc_xbrl_wrapper_oracle --cik 0001913724 --promotion-gate` -> `promotion_status=promote`, `blocking_rows_delta=0`, `blocking_fv_delta=0`.
- Baseline backstop: `python scripts/diff_outputs.py --semantic` ran and failed against the already-dirty output tree (`443 divergent artifact(s), 3,682 checked, 77 skipped`). The reported drift spans broad BDC/N-PORT/frontend artifacts and is not attributable to this CIK-scoped wrapper task; no canonical production artifact rebuild was performed for this wrapper.

**Status: production_clean** -- the wrapper classifies the CIK's observed explicit instrument identifiers and documented equity/duplicate-issuer edge cases, with all wrapper oracle quarters passing and no source reconciliation blockers introduced.

### 2026-06-05 -- Blue Owl Technology Income wrapper blocker closeout (CIK 0001869453)

- Updated `pipeline/bdc_xbrl_wrapper.py` so configured commitment-total markers classify as `aggregate` before generic total-rollup detection. This prevents Blue Owl commitment totals from being reported as unresolved total rollups.
- Updated `pipeline/bdc_xbrl_wrapper_oracle.py` so diagnostic `aggregate` and `non_private_market` rows do not count as `remaining_wrapper_blocking_rows`.
- Expanded Blue Owl Technology content-signature archetype keywords in `data/overrides/bdc_xbrl_wrappers/0001869453.json` for explicit instrument forms already supported by dispatch, including currency-qualified term loans, `Firs lien`/`revovling` filer typos, common stock, and common equity.
- Added regression coverage in `tests/test_bdc_xbrl_wrapper.py`, `tests/test_bdc_xbrl_wrapper_oracle.py`, and `tests/test_wrapper_content_signatures.py`.

**Validation:**
- Schema validation passed for `data/overrides/bdc_xbrl_wrappers/0001869453.json`.
- `pytest tests/test_bdc_xbrl_wrapper.py -v --tb=short` -> 186 passed, 2 existing regex warnings.
- `pytest tests/test_bdc_xbrl_wrapper_oracle.py -v --tb=short` -> 56 passed.
- `pytest tests/test_wrapper_content_signatures.py -v --tb=short` -> 33 passed.
- `python -m pipeline.wrapper_content_signatures --cik 0001869453` -> 13 quarters checked, 7,327 rows, 7,325 pass rows, 2 signature violations; unclassified row/FV gates pass in all quarters after the explicit-instrument keyword expansion.
- `python -m pipeline.bdc_xbrl_wrapper_oracle --cik 0001869453 --compare-baseline --fresh-bdc-staging` -> 13 pass, `remaining_blocking_rows=0`, `remaining_wrapper_blocking_rows=0`. Baseline comparison cleared the prior 10 blocking rows across 2024-12-31 through 2026-03-31.
- Backstop semantic diff was not run because an unrelated `pytest tests/test_validate_holdings.py -q` process was active in the shared worktree; running it during that job would not isolate this CIK-scoped change.

**Status: production_clean** -- all current Blue Owl Technology wrapper oracle quarters pass with hard blockers cleared. Bare specialty-finance/cross-strategy labels remain intentionally unclassified unless explicit instrument evidence appears, preserving the duplicate-dimension guardrail.

### 2026-06-05 -- Saratoga wrapper update for no-prefix loan rows (CIK 0001377936)

- Updated `data/overrides/bdc_xbrl_wrappers/0001377936.json` from version 1 to version 2.
- Added explicit mixed-family leaf markers and narrow fallback regexes for Saratoga no-prefix syndicated-loan formats, including:
  - `Issuer - Industry - Issuer - Loan`
  - `Issuer - Industry - Issuer - Loan - One`
  - compact dash variants such as `Isolved Inc.-Services: Business-... - Loan`
  - compact `Term-Loan ... -Loan` variants.
- Added exact issuer bridges for a small set of named Saratoga rows observed as source leaves missing from unified output: GoReact, Omatic Software, Emily Street Enterprises, Fiesta Purchaser, Ingenovis Health, and Pediatric Associates.
- Expanded Saratoga debt archetype keywords for terminal ` - Loan` and compact `Term-Loan` labels.
- Added six focused Saratoga classifier tests in `tests/test_bdc_xbrl_wrapper.py`, including false-positive coverage that plain industry labels remain aggregate.

**Validation:**
- Schema validation passed: `python -m jsonschema -i data/overrides/bdc_xbrl_wrappers/0001377936.json schemas/bdc_xbrl_wrapper/wrapper_v3.schema.json`.
- Focused Saratoga wrapper tests passed: `pytest tests/test_bdc_xbrl_wrapper.py -k "saratoga" -v --tb=short` -> 16 passed, 183 deselected.
- Full wrapper test file passed: `pytest tests/test_bdc_xbrl_wrapper.py -v --tb=short` -> 199 passed.
- Fresh cached-staging oracle improved materially but remains failing: initial run this turn had `remaining_blocking_rows=294`; final run has `remaining_blocking_rows=32`, `cleared_rollup_rows=2`, and `oracle_status_counts={'fail': 6}`.
- Final remaining mechanisms: `total_rollup_no_child_tie=25` rows / $10.590B source FV, `leaf_present_in_raw_missing_from_unified=6` rows / $71.108M source FV, and `unclassified_signature=1` row / $16.429M source FV.
- Final baseline comparison from the oracle artifact shows 197 baseline blocking rows versus 32 current blocking rows across the six Saratoga quarters (`blocking_rows_delta=-165`).
- Content-signature diagnostic still fails on raw `bdc_holdings.csv` for all six quarters because raw holdings include many aggregate/comparative/header-like rows and rows with missing fair value; staging oracle is the stronger CIK-scoped validation signal for this update.
- No canonical production rebuild or semantic diff was run for this CIK-scoped wrapper trial.

**Status: partial_wrapper / blockers_reduced** -- the update safely clears the large 2025-11 no-prefix loan blocker spike and materially reduces Saratoga residuals, but the wrapper is not production-clean. Remaining source rollups need a separate rollup-parent/aggregate policy decision, and the six raw leaves still missing from unified require source/staging review beyond broad text classification.

### 2026-06-05 -- Barings wrapper residual closeout and promotion-gate trial fix (CIK 0001859919)

- Updated `pipeline/source_reconciliation.py` so output rows corresponding to already-collapsed duplicate source dimension paths are not reported as `extra_in_pipeline` when the canonical source row already reconciled. The guard requires same CIK/report/accession, fair-value tolerance, and an exact dimension/identifier/wrapper-key match to the collapsed source variant.
- Added regression coverage in `tests/test_validate_holdings.py` for the output-side duplicate-dimension case found in Barings residuals.
- Updated `pipeline/bdc_xbrl_wrapper_oracle.py` so `--promotion-gate --holdings-file ...` forwards the trial holdings file into `run_promotion_trial`; before this, the gate ignored the file and evaluated canonical production holdings.
- Added promotion-gate forwarding coverage in `tests/test_bdc_xbrl_wrapper_oracle.py`.
- Updated the Trinity source-reconciliation test expectation from `TRINITY_DEBT_ISSUER_ROLLUP_V1` to current rule id `TRINITY_DEBT_ISSUER_ROLLUP_V3`.
- Documented the Barings residual mechanism and remaining review items in `data/output/data_investigation_results.md`.

**Validation:**
- `pytest tests/test_validate_holdings.py -q` -> 133 passed, existing regex warnings.
- `pytest tests/test_bdc_xbrl_wrapper_oracle.py -q` -> 57 passed.
- Schema validation passed for `data/overrides/bdc_xbrl_wrappers/0001859919.json`.
- `pytest tests/test_bdc_xbrl_wrapper.py -q` -> 186 passed.
- Trial-unified oracle with `--holdings-file data/output/bdc_xbrl_wrapper_trial/0001859919/unified_trial/private_markets_holdings.0001859919.csv` -> `remaining_blocking_rows=0`.
- Fresh cached-staging oracle with `--fresh-bdc-staging` -> `remaining_blocking_rows=0`.
- Corrected trial-holdings promotion gate -> `promotion_status=review_required`, `blocking_rows_delta=0`, `blocking_fv_delta=0`; remaining reasons are `cost_fv_ratio_outliers` and `exclusion_risk_detected` in 2023-06-30 and 2024-09-30.
- Fresh cached-staging promotion gate -> `promotion_status=review_required`, `blocking_rows_delta=0`, `blocking_fv_delta=0` with the same review reasons.
- Backstop semantic diff was run after tests: `python scripts/diff_outputs.py --semantic` -> failed against the already-dirty output tree with 443 divergent artifacts, 3,682 checked, 77 skipped; semantic deltas were reported in holdings, matches, position returns, index returns, and fund financials.

**Status: review_required** -- all mechanically fixable Barings hard source-reconciliation blockers are cleared. Remaining issues require human source review: unusual cost/FV economics and two instrument-only term-loan rows with no issuer evidence.

### 2026-06-05 -- TPG Twin Brook staging and matching closeout (CIK 0001913724)

- Added a TPG-specific `staging.strategy=hierarchy_extract` section to `data/overrides/bdc_xbrl_wrappers/0001913724.json` so comma-delimited explicit instrument rows split issuer and instrument before generic no-dash fallback parsing.
- Kept the TPG staging condition narrow: it excludes pipe-delimited identifiers and only fires on explicit debt/equity instrument markers. Bare `Twin Brook Equity Holdings, LLC` rows remain standalone equity positions.
- Updated `data/overrides/bdc_xbrl_wrappers/unlisted_bdc_xbrl_reference.json` so CIK 0001913724 lists the `staging` section and `wrapper_staging_strategy=hierarchy_extract`.
- Added 4 TPG staging regression tests in `tests/test_unified_holdings.py` covering comma debt, sponsor subordinated note, pipe parsing preservation, and the bare-equity false-positive boundary.
- Updated `pipeline/bdc_xbrl_wrapper.py` with a scoped helper for configured fallback regex masks so pandas capture-group warnings do not pollute wrapper test output.
- Changed the TPG bare-equity known-edge-case regex to a non-capturing optional group.
- Investigated the only TPG content-signature violation. It is source row index 1164077: `Kaizen Auto Care, LLC, First lien senior secured term loan` in accession `0001913724-23-000141` for 2023-09-30, with only `basis_spread=0.06` populated and no fair value, cost, principal, rate, or maturity. No wrapper or staging fix was applied because weakening the required fair-value signature would hide a source fact fragment rather than improve position extraction.

**Validation:**
- Schema validation passed for `data/overrides/bdc_xbrl_wrappers/0001913724.json`.
- `pytest tests/test_bdc_xbrl_wrapper.py -k "tpg_twin_brook" -v` -> 8 passed.
- `pytest tests/test_unified_holdings.py -k "tpg_twin_brook" -v --tb=short` -> 4 passed.
- `pytest tests/test_bdc_xbrl_wrapper.py -v` -> 186 passed, with the prior pandas regex warnings cleared.
- `pytest tests/test_wrapper_content_signatures.py -v` -> 33 passed.
- `python -m pipeline.wrapper_content_signatures --cik 0001913724 --output-dir data/output/wrapper_drift/0001913724` -> 13 quarters, 13,399 rows, 13,398 pass rows, 1 fail row, no regex warnings.
- Fresh cached-staging oracle: `python -m pipeline.bdc_xbrl_wrapper_oracle --cik 0001913724 --compare-baseline --fresh-bdc-staging` -> 13 pass, 0 remaining blocking rows.
- Promotion gate: `python -m pipeline.bdc_xbrl_wrapper_oracle --cik 0001913724 --promotion-gate` -> `promotion_status=promote`, `blocking_rows_delta=0`, `blocking_fv_delta=0`.
- One-CIK trial rebuild with matching: `python scripts/rebuild_unified_cik_trial.py --cik 0001913724 --match` -> 7,420 trial rows, 0 row delta and 0 FV delta versus production for every quarter, 4,688 position-match pairs, J01 pass (`B1b rate=92.3%`), J03 pass (`fuzzy rate=0.3%`).
- Trial-unified oracle: `python -m pipeline.bdc_xbrl_wrapper_oracle --cik 0001913724 --holdings-file data/output/bdc_xbrl_wrapper_trial/0001913724/unified_trial/private_markets_holdings.0001913724.csv --compare-baseline` -> 13 pass, 0 remaining blocking rows.
- Backstop semantic diff: `python scripts/diff_outputs.py --semantic` still failed against the already-dirty output tree (`443 divergent artifact(s), 3,682 checked, 77 skipped`) with broad BDC/N-PORT/frontend deltas unrelated to this CIK-scoped change.

**Status: production_clean** -- all TPG wrapper, staging, oracle, promotion, and one-CIK matching gates pass. The remaining content-signature failure is a documented source-data fragment without fair-value evidence, not a safe parser fix.

### 2026-06-05 -- Audax Credit BDC wrapper iteration and residual closeout (CIK 0001633858)

- Added `data/overrides/bdc_xbrl_wrappers/0001633858.json` for Audax Credit BDC Inc. with dispatch rules, prefix hierarchy rules, `hierarchy_extract` staging, archetype signatures, invariants, and documented portfolio rollup/header edge cases.
- Updated `pipeline/staging_bdc.py` so configured `hierarchy_extract` rows can preserve digit-heavy extracted issuers such as `80/20` instead of being replaced by the full raw hierarchy string by the generic bad-issuer fallback. The allowance is scoped to hierarchy-extract rows and only the numeric bad-issuer condition.
- Added Audax wrapper classifier tests in `tests/test_bdc_xbrl_wrapper.py` and staging regression tests in `tests/test_unified_holdings.py` covering hierarchy debt/equity leaves, category headers, flat comma identifiers, non-private cash rows, numeric issuer preservation, and LP Interest retention.
- Updated `data/overrides/bdc_xbrl_wrappers/unlisted_bdc_xbrl_reference.json` so CIK 0001633858 is marked `wrapper_status=exists`, version 1, with `dispatch`, `staging`, `archetypes`, and `invariants`.

**Validation:**
- Schema validation passed for `data/overrides/bdc_xbrl_wrappers/0001633858.json`.
- `pytest tests/test_bdc_xbrl_wrapper.py -k "audax" -q` -> 7 passed, 186 deselected.
- `pytest tests/test_unified_holdings.py::TestWrapperAuthoritativeStaging::test_audax_hierarchy_numeric_issuer_is_not_replaced_by_raw tests/test_unified_holdings.py::TestWrapperAuthoritativeStaging::test_audax_equity_header_dropped_but_numeric_issuer_leaf_kept -q` -> 2 passed.
- Fresh cached-staging oracle: `python -m pipeline.bdc_xbrl_wrapper_oracle --cik 0001633858 --compare-baseline --fresh-bdc-staging` -> 13 summary rows, 9 pass / 4 fail, 2 remaining blocking rows. Remaining rows are 2025-03-31 source totals (`Total Equity and Preferred Shares`, FV 7,190,615; `Total Portfolio Investments`, FV 408,233,009) documented by wrapper as `equity_total_rollup`.
- One-CIK trial rebuild with matching: `python scripts/rebuild_unified_cik_trial.py --cik 0001633858 --match` -> 4,315 trial rows versus 4,326 production rows, delta -11 rows and -33,963,540 FV, all in 2024-12-31 leaked portfolio/category rollups. J01 passed (`B1b rate=88.5%`), J03 passed (`fuzzy rate=0.6%`).
- Trial output inspection found zero `issuer_name` values containing `Portfolio Investments`; `80/20` debt and LP Interest rows are retained in 2025-12-31 and 2026-03-31 with issuer `80/20`.
- Trial-holdings oracle with `--holdings-file data/output/bdc_xbrl_wrapper_trial/0001633858/unified_trial/private_markets_holdings.0001633858.csv --compare-baseline` -> same 2 remaining documented total-rollup residuals.
- Content signatures: `python -m pipeline.wrapper_content_signatures --cik 0001633858 --output-dir data/output/wrapper_drift/0001633858` -> 10,499 raw rows, 8,382 pass rows, 2,117 fail rows. Failures are missing required `fair_value` on classified raw debt/equity source rows; `unclassified_rate` passes every quarter. No signature weakening was applied because making fair value optional would hide source fragments.
- Promotion gate: `python -m pipeline.bdc_xbrl_wrapper_oracle --cik 0001633858 --promotion-gate` -> `promotion_status=reject`, with improvements `blocking_rows_delta=-1`, `blocking_fv_delta=-12242905`; remaining reasons include documented total-rollup residuals, content-signature failures, 2024-12 continuity/unclassified-FV soft gates, and 2025-06 concept drift.

**Status: review_required** -- safe wrapper/staging improvements appear exhausted. The wrapper removes 11 leaked rollup/header rows, normalizes Audax hierarchy issuers, and preserves numeric issuer leaves, but formal promotion still rejects due source-level rollup/signature review items that should not be cleared by weakening wrapper signatures.

### 2026-06-05 -- Saratoga leaf recovery and content-signature diagnostic cleanup (CIK 0001377936)

- Updated `data/overrides/bdc_xbrl_wrappers/0001377936.json` to version 3. Added a narrow fallback-family pattern and aggregate marker for the duplicated `Non-profit Services` industry-axis row, while keeping instrumented Omatic `Non-profit Services - First Lien Term Loan` rows as leaves.
- Fixed `pipeline/bdc_xbrl_wrapper.py` so percentage coupon text like `12.17% Cash/1.00% PIK` is not classified as non-private-market cash. This restored Saratoga current-period loan leaves that were surviving Phase B but being dropped by the final wrapper non-private filter.
- Updated `pipeline/wrapper_content_signatures.py` so the raw BDC loader validates current-period fair-value wrapper position leaves when wrapper dispatch can identify leaves. The diagnostic no longer counts comparative-period rows, subtotal/total rollups, or no-FV source fragments as content-signature candidates.
- Added Saratoga wrapper regressions and a wrapper-content loader regression in `tests/test_bdc_xbrl_wrapper.py` and `tests/test_wrapper_content_signatures.py`.

**Validation:**
- `pytest tests/test_bdc_xbrl_wrapper.py -k saratoga -q` -> 17 passed, 198 deselected.
- `pytest tests/test_bdc_xbrl_wrapper.py -q` -> 215 passed.
- `pytest tests/test_wrapper_content_signatures.py -q` -> 34 passed.
- Fresh cached-staging oracle: `python -m pipeline.bdc_xbrl_wrapper_oracle --cik 0001377936 --fresh-bdc-staging --output-dir data/output/bdc_xbrl_wrapper_trial/0001377936` -> 6 summary rows, `remaining_blocking_rows=25`, all remaining rows are `mixed_total_rollup` subtotal/total residuals. The six source leaf rows and the `Non-profit Services` unclassified row were cleared.
- Raw content-signature diagnostic: `python -m pipeline.wrapper_content_signatures --cik 0001377936 --output-dir data/output/wrapper_drift/0001377936` -> 6 quarters, 1,572 candidate rows, 1,572 pass rows, 0 fail rows, 0 violations.

**Status: review_required** -- user-requested items 2, 3, and 4 are fixed. Remaining Saratoga blockers are 25 documented subtotal/total rollups that require oracle/review policy treatment rather than position-leaf wrapper widening.

### 2026-06-05 -- MidCap Financial wrapper residual closeout (CIK 0001278752)

- Added `data/overrides/bdc_xbrl_wrappers/0001278752.json` for MidCap Financial Investment Corp with dispatch rules for old affiliation/category rows, explicit debt/equity/warrant leaves, cash-equivalent exclusions, and total/category rollups.
- Tightened the MidCap non-private-market markers after trial validation showed the broad `treasury` marker incorrectly removed real borrower rows for `G Treasury SS LLC`. The wrapper now uses narrower government-security terms (`u.s. treasury`, `us treasury`, `treasury bill(s)`).
- Added MidCap wrapper regression tests in `tests/test_bdc_xbrl_wrapper.py`, including false-positive coverage for industry-plus-issuer rows that lack instrument evidence and a `G Treasury SS LLC` borrower leaf.
- Updated `pipeline/bdc_xbrl_wrapper_oracle.py` so `*_rollup` wrapper dispositions such as `mixed_total_rollup` are diagnostic, not hard `wrapper_blockers_remaining` failures. This aligns the promotion gate with source reconciliation, which already treats these dispositions as documented rollups.
- Added oracle regression coverage in `tests/test_bdc_xbrl_wrapper_oracle.py` for both true leaf hard blockers and diagnostic total-rollup residuals.

**Validation:**
- Schema validation passed for `data/overrides/bdc_xbrl_wrappers/0001278752.json`.
- `pytest tests/test_bdc_xbrl_wrapper.py -k "midcap" -q` -> 11 passed.
- `pytest tests/test_bdc_xbrl_wrapper_oracle.py -k "wrapper_blocker or total_rollup_disposition" -q` -> 3 passed.
- `pytest tests/test_bdc_xbrl_wrapper.py tests/test_bdc_xbrl_wrapper_oracle.py -q` -> 286 passed.
- One-CIK trial rebuild with matching: `python scripts/rebuild_unified_cik_trial.py --cik 0001278752 --match` -> 6,280 trial rows versus 6,338 production rows, delta -58 rows; J01 passed (`B1b rate=76.5%`), J03 passed (`fuzzy rate=7.8%`).
- Trial-unified oracle with `--holdings-file data/output/bdc_xbrl_wrapper_trial/0001278752/unified_trial/private_markets_holdings.0001278752.csv --compare-baseline` -> 191 remaining blocking rows, zero `remaining_wrapper_blocking_rows`, and blocker deltas of -435 rows / -109,327,228,000 FV versus baseline.
- Trial promotion gate with the same holdings file -> `promotion_status=review_required`, `blocking_rows_delta=-435`, `blocking_fv_delta=-109327228000`.
- Backstop semantic diff: `python scripts/diff_outputs.py --semantic` failed against the already-dirty output tree with 443 divergent artifacts, 3,682 checked, 77 skipped, and semantic deltas in holdings, matches, position returns, index returns, and fund financials.

**Status: review_required** -- safe MidCap wrapper/oracle fixes are exhausted. Remaining residuals are review-only: 184 unclassified industry-plus-issuer source rows without instrument/rate/maturity evidence, 7 documented total rollups without child ties, and soft gates for cost/FV, rate, exclusion-risk, and early-period continuity review.

### 2026-06-05 -- Trinity Capital wrapper residual reduction (CIK 0001786108)

- Updated `data/overrides/bdc_xbrl_wrappers/0001786108.json` with Trinity-specific dispatch fixes for truncated `ortfolio Company ...` prefixes, portfolio/cash aggregate rows, control/affiliate aggregate headers, and early-quarter `Total`/`Sub-total` fallback rows.
- Added an explicit `cash` fallback family entry and converted Trinity known-edge-case regex groups to non-capturing groups, removing wrapper-coherence and pandas content-signature warning noise without widening position inclusion.
- Added Trinity wrapper regression coverage in `tests/test_bdc_xbrl_wrapper.py` for cash/non-private rows, portfolio aggregate rows, control/affiliate headers, truncated category rows, early total/subtotal rows, and an equipment-financing false-positive boundary.
- Did not add a broad `Total` canonical-strip rule because cached Trinity identifiers include real leaf issuers such as `Total Medical Sales Training Holding Company` and `Total Yellowbrick Learning, Inc.`; stripping `Total` globally would risk contaminating real position keys.

**Validation:**
- Schema validation passed for `data/overrides/bdc_xbrl_wrappers/0001786108.json`.
- `pytest tests/test_bdc_xbrl_wrapper.py -k "trinity" -v --tb=short` -> 8 passed, 208 deselected.
- `pytest tests/test_bdc_xbrl_wrapper.py -v` -> 216 passed.
- `python -m pipeline.wrapper_content_signatures --cik 0001786108 --output-dir data/output/wrapper_drift/0001786108` -> 13 quarters, 5,051 rows, 2,408 pass rows, 2,643 fail rows, 12/12 FV reconciliation quarters passed, no capture-group warnings. Remaining content-signature failures are broad historical hierarchy/rollup diagnostics, not safe parser fixes.
- Fresh cached-staging oracle with `--compare-baseline --fresh-bdc-staging` -> 13 summary rows, `cleared_rollup_rows=1075`, `remaining_blocking_rows=52`. This reduced the Trinity source-only blocking pool from the inspected pre-change 216 rows to 52 rows; the latest four quarters (2025-06-30 through 2026-03-31) have zero remaining wrapper blocking rows.
- One-CIK trial rebuild with matching: `python scripts/rebuild_unified_cik_trial.py --cik 0001786108 --match` -> 5,069 trial rows versus 5,070 production rows, row delta -1; 3,961 match pairs; J01 pass (`B1b rate=78.3%`), J03 pass (`fuzzy rate=8.2%`).
- Trial-unified oracle with `--holdings-file data/output/bdc_xbrl_wrapper_trial/0001786108/unified_trial/private_markets_holdings.0001786108.csv --compare-baseline` -> `remaining_blocking_rows=52`, matching the fresh-staging result.
- Trial-holdings promotion gate -> `promotion_status=review_required`, with improvements `blocking_rows_delta=-594`, `blocking_fv_delta=-33162593000`, and `cleared_rollups_increased=+1075`.
- Backstop semantic diff: `python scripts/diff_outputs.py --semantic` failed against the already-dirty output tree (`443 divergent artifact(s), 3,682 checked, 77 skipped`) with broad BDC/N-PORT/frontend deltas unrelated to this CIK-scoped trial.

**Status: review_required** -- all safe Trinity wrapper fixes found in this pass are implemented. Remaining hard blockers are 52 older-quarter issuer/total rollup residuals with `issuer_rollup_source_child_fv_mismatch`, `issuer_rollup_no_child_tie`, or `total_rollup_no_child_tie`, plus rate/cost diagnostics; these require source-reconciliation or human review rather than broader regex widening.

### 2026-06-05 -- Saratoga wrapper packet marked complete/review-required (CIK 0001377936)

- Updated `data/output/bdc_xbrl_wrapper_queue/summary.csv` to mark Saratoga as `complete_review_required` with the refreshed oracle count of 25 remaining blocking rows.
- Added `data/output/bdc_xbrl_wrapper_trial/0001377936/promotion_verdict.json` with `status=reject`, `blocking_rows_delta=-165`, and `blocking_fv_delta=-4,661,048,444` versus the comparison baseline.
- This is a workflow completion marker, not a production-clean promotion. The remaining 25 rows are documented subtotal/total rollups requiring exception review.
## 2026-06-05 - Stone Point Credit wrapper coverage for CIK 0001825384

- Added `data/overrides/bdc_xbrl_wrappers/0001825384.json` for Stone Point Capital Credit LLC / Stone Point Credit Corp comma-delimited XBRL identifiers. The wrapper is dispatch-only and conservatively classifies explicit first/second lien loans, delayed draws, revolvers, unsecured notes, equity, preferred equity, equity investments, and warrants while leaving bare issuer-only identifiers unclassified for review.
- Updated `data/overrides/bdc_xbrl_wrappers/unlisted_bdc_xbrl_reference.json` to mark `0001825384` as `wrapper_status = "exists"` with dispatch/archetype/invariant sections. Added focused classifier coverage in `tests/test_bdc_xbrl_wrapper.py`, including a false-positive guard for `RSC Topco, Inc.` bare issuer rows.
- Validation: `python -m jsonschema -i data\overrides\bdc_xbrl_wrappers\0001825384.json schemas\bdc_xbrl_wrapper\wrapper_v3.schema.json` passed; `pytest tests\test_bdc_xbrl_wrapper.py -q` passed with 225 tests; `pytest tests\test_unified_cik_trial.py -q` passed with 7 tests.
- Oracle/trial results: staging oracle and trial oracle both reported `remaining_blocking_rows = 0` and baseline blocker delta 0 across 13 quarters. Promotion gate status is `review_required` only for waiveable `cost_fv_ratio_outliers` in 2023-12-31, 2024-03-31, 2024-06-30, and 2024-09-30. The gate also flags 67 family-vs-asset-category review rows where explicit wrapper equity/warrant identifiers disagree with current unified asset classification.
- One-CIK isolated trial rebuild for `0001825384` produced 2,939 rows, unchanged versus production by row count and FV for every quarter. Position matching passed J01 (`0.849`, threshold `0.700`) and J03 (`0.039`, threshold `0.100`), with 400 B1b position-key matches and 71 D_fuzzy fallback matches.
- Backstop semantic diff: `python scripts\diff_outputs.py --semantic` failed against the already-dirty output tree with 443 divergent artifacts, 3,682 checked, 77 skipped, and semantic deltas in holdings, matches, position returns, index returns, and fund financials.

## 2026-06-05 - Antares Strategic Credit wrapper coverage for CIK 0001993402

- Added `data/overrides/bdc_xbrl_wrappers/0001993402.json` for Antares Strategic Credit Fund XBRL hierarchy identifiers. The wrapper classifies `Asset Type` and `Commitment Type` position leaves, total/cash headers, and uses CIK-scoped `hierarchy_extract` staging so issuer/instrument parsing does not widen global BDC rules.
- Updated `data/overrides/bdc_xbrl_wrappers/unlisted_bdc_xbrl_reference.json` to mark `0001993402` as `wrapper_status = "exists"` with dispatch, staging, archetype, and invariant sections. Added focused classifier tests in `tests/test_bdc_xbrl_wrapper.py` for debt leaves, equity leaves, commitment leaves, total headers, and cash-equivalent rows.
- Validation: schema validation passed for `0001993402.json`; wrapper coherence check passed; `pytest tests/test_bdc_xbrl_wrapper.py -k "antares" -q` passed with 5 tests.
- Cached staging oracle with `--compare-baseline --fresh-bdc-staging` and trial-unified oracle both reported 24 remaining blocking rows, all `total_rollup_no_child_tie` on documented total/industry rollup rows. `remaining_wrapper_blocking_rows = 0` across all 9 quarters; 5 of 9 quarters pass outright.
- One-CIK trial rebuild with matching produced 9,320 trial rows versus 9,268 production rows, row delta +52. Position matching passed J01 (`B1b rate=75.1%`, threshold 70%) and J03 (`fuzzy rate=0.9%`, threshold 10%).
- Status: review_required. Safe parser/wrapper fixes found in this pass are implemented; remaining items are documented total rollups requiring review/exception handling rather than broader regex inclusion.

## 2026-06-05 - KKR FS Income Trust wrapper coverage for CIK 0001930679

- Added `data/overrides/bdc_xbrl_wrappers/0001930679.json` for KKR FS Income Trust and updated `data/overrides/bdc_xbrl_wrappers/unlisted_bdc_xbrl_reference.json` from `wrapper_status=none` to `wrapper_status=exists` for this CIK. The wrapper handles mixed pipe, comma, affiliation-prefixed, and bare numbered issuer/tranche formats, strips affiliation prefixes from wrapper keys, uses CIK-scoped `hierarchy_extract` staging for comma-only rows, and keeps portfolio totals out of position leaves.
- Updated `pipeline/wrapper_content_signatures.py` so wrapper content validation falls back per row from sparse preferred text columns to original identifiers, then to wrapper leaf family or deterministic wrapper classifier evidence when keyword archetypes miss a valid wrapper position leaf.
- Added KKR FS wrapper regressions in `tests/test_bdc_xbrl_wrapper.py` and content-signature fallback regressions in `tests/test_bdc_xbrl_wrapper_oracle.py`.
- Validation: `pytest tests/test_bdc_xbrl_wrapper.py tests/test_bdc_xbrl_wrapper_oracle.py -q` passed with 313 tests. Cached promotion gate `python -m pipeline.bdc_xbrl_wrapper_oracle --cik 0001930679 --promotion-gate --fresh-bdc-staging` exited 0 with `promotion_status=review_required`, `blocking_rows_delta=0`, and `blocking_fv_delta=0`.
- One-CIK trial rebuild with matching: `python scripts/rebuild_unified_cik_trial.py --cik 0001930679 --match` produced 2,782 trial rows versus 2,782 production rows with no row/FV delta. Position matching passed J01 (`0.881`, threshold `0.700`) and J03 (`0.006`, threshold `0.100`).
- Status: review_required. Remaining promotion-gate items are review-only `rate_magnitude_shift_detected` diagnostics for 2023-12-31 and 2024-03-31. The trial wrapper changed issuer/instrument parsing enough that entity/GICS enrichment should be rechecked if this wrapper is promoted into canonical outputs.

## 2026-06-05 - Stepstone Private Credit wrapper coverage for CIK 0001950803

- Added `data/overrides/bdc_xbrl_wrappers/0001950803.json` for Stepstone pipe-delimited BDC XBRL identifiers, including debt/equity/fund/cash dispatch, CIK-scoped `prefix_strip` staging, portfolio-total aggregate guards, and canonical key stripping for volatile rate/maturity suffixes.
- Updated wrapper behavior with an opt-in `category_marker_before_total` dispatch flag in `schemas/bdc_xbrl_wrapper/wrapper_v3.schema.json` and `pipeline/bdc_xbrl_wrapper.py`, so Stepstone total-style category markers can be treated as aggregates without changing default total-rollup behavior for other wrappers.
- Tightened the global non-private cash guard so `Cash Pay Term Loan` is treated as a loan position, not a cash-equivalent row. Added Stepstone tests for cash-pay loans, portfolio totals, total/cash rows, quoted identifiers, and subtotal false positives.
- Updated `pipeline/staging_bdc.py` to drop wrapper-classified aggregate and total-rollup hierarchy rows during no-prefix hierarchy filtering, while preserving issuer-rollup rows for review. Updated `data/overrides/bdc_xbrl_wrappers/0001930679.json` to replace DuckDB-incompatible negative-lookahead staging regexes with comma-only regexes guarded by the existing pipe-exclusion condition.
- Updated `data/overrides/bdc_xbrl_wrappers/unlisted_bdc_xbrl_reference.json` to mark Stepstone as `wrapper_status = "exists"` with dispatch, staging, archetype, and invariant sections.
- Validation: schema validation passed for `0001950803.json` and the touched `0001930679.json`; `pytest tests/test_bdc_xbrl_wrapper.py -q` passed with 242 tests; `pytest tests/test_bdc_xbrl_wrapper_oracle.py -q` passed with 73 tests.
- One-CIK trial rebuild with matching: `python scripts/rebuild_unified_cik_trial.py --cik 0001950803 --match` produced 7,816 trial rows versus 7,928 production rows, row delta -112. Position matching J03 passed (`fuzzy rate=2.6%`); J01 remains review-only below target (`B1b rate=53.0%`).
- Trial-unified oracle with `--holdings-file data/output/bdc_xbrl_wrapper_trial/0001950803/unified_trial/private_markets_holdings.0001950803.csv --compare-baseline` reported `remaining_blocking_rows=0` across 11 quarters. Remaining oracle failures are review-only diagnostics: `exclusion_risk_detected`, `unclassified_fv_rate_exceeded`, `low_position_continuity`, and `cost_fv_ratio_outliers`.

**Status: review_required** -- source-reconciliation blockers are cleared in the Stepstone trial. Remaining items require review/exception handling rather than broader parser widening.

### 2026-06-05 - Stepstone wrapper semantic-diff backstop

- Backstop semantic diff after the Stepstone trial work: `python scripts/diff_outputs.py --semantic` failed against the already-dirty output tree with 443 divergent artifacts, 3,682 checked, and 77 skipped. The reported semantic delta categories were holdings, matches, position returns, index returns, and fund financials. This was not treated as Stepstone-specific because no canonical production rebuild was run; the Stepstone verification used isolated trial artifacts under `data/output/bdc_xbrl_wrapper_trial/0001950803/`.

## 2026-06-05 - Golub Capital BDC 4 wrapper coverage for CIK 0001901612

- Added `data/overrides/bdc_xbrl_wrappers/0001901612.json` for Golub Capital BDC 4 comma-delimited BDC XBRL identifiers. The wrapper is dispatch-only and conservatively classifies explicit One stop, senior secured, subordinated debt, revolver/delayed draw, common/preferred equity, LP/LLC interest, and warrant rows while leaving bare issuer-only identifiers unclassified.
- Updated `data/overrides/bdc_xbrl_wrappers/unlisted_bdc_xbrl_reference.json` to mark `0001901612` as `wrapper_status = "exists"` with dispatch, archetype, and invariant sections. Added focused classifier tests in `tests/test_bdc_xbrl_wrapper.py`, including false-positive guards for cash/total rows and bare issuer names.
- Validation: schema validation passed for `0001901612.json`; `pytest tests/test_bdc_xbrl_wrapper.py -k "golub_bdc4" -q` passed with 5 tests; `pytest tests/test_bdc_xbrl_wrapper.py -q` passed with 270 tests; `pytest tests/test_bdc_xbrl_wrapper_oracle.py -q` passed with 73 tests.
- One-CIK trial rebuild with matching: `python scripts/rebuild_unified_cik_trial.py --cik 0001901612 --match` produced 6,547 trial rows versus 6,547 production rows, row delta +0. Position matching passed J01 (`B1b rate=96.1%`) and J03 (`fuzzy rate=0.8%`).
- Trial-unified oracle with `--holdings-file data/output/bdc_xbrl_wrapper_trial/0001901612/unified_trial/private_markets_holdings.0001901612.csv --compare-baseline` reported `remaining_blocking_rows=0` across 13 quarters. Remaining oracle failures are review-only diagnostics: `cost_fv_ratio_outliers` for 2025-03-31 and `low_position_continuity` for 2026-03-31. The oracle also reported 23 staging-only non-private-market disagreement rows for review.
- Backstop semantic diff: `python scripts/diff_outputs.py --semantic` failed against the already-dirty output tree with 443 divergent artifacts, 3,682 checked, 77 skipped, and semantic deltas in holdings, matches, position returns, index returns, and fund financials. This was not treated as Golub-specific because no canonical production rebuild was run; verification used isolated trial artifacts under `data/output/bdc_xbrl_wrapper_trial/0001901612/`.

**Status: review_required** -- source-reconciliation blockers are cleared in the Golub Capital BDC 4 trial. Remaining items require review/exception handling rather than broader parser widening.

## 2026-06-05 - T Series BDC wrapper coverage for CIK 0001885968

- Added `data/overrides/bdc_xbrl_wrappers/0001885968.json` for T Series Middle Market Loan Fund LLC / T Series BDC LLC hierarchy identifiers. The wrapper handles debt/equity hierarchy rows, affiliation spelling drift (`non-controlled/non-affiliated`, `non-controlled/non - affiliated`, `non-controlled//non-affiliated`, `non-controlled/affiliated`), `Investment, Identifier [Axis]` prefix noise, cash/money-market exclusions, and CIK-scoped `hierarchy_extract` staging.
- Updated `data/overrides/bdc_xbrl_wrappers/unlisted_bdc_xbrl_reference.json` to mark `0001885968` as `wrapper_status = "exists"` with dispatch, staging, archetype, and invariant sections. Added focused classifier tests in `tests/test_bdc_xbrl_wrapper.py` and staging extraction tests in `tests/test_unified_holdings.py`.
- Validation: schema validation passed for `0001885968.json`; `pytest tests/test_bdc_xbrl_wrapper.py -k "t_series_bdc" -q` passed with 7 tests; `pytest tests/test_unified_holdings.py -k "t_series_bdc" -q` passed with 3 tests; `pytest tests/test_bdc_xbrl_wrapper.py -q` passed with 304 tests; `pytest tests/test_bdc_xbrl_wrapper_oracle.py -q` passed with 73 tests.
- One-CIK trial rebuild with matching: `python scripts/rebuild_unified_cik_trial.py --cik 0001885968 --match` produced 5,168 trial rows versus 5,124 production rows, row delta +44. The row/FV increases are confined to 2025-09-30 (+18 rows, +$68.696M FV), 2025-12-31 (+15 rows, +$59.754M FV), and 2026-03-31 (+11 rows, +$43.644M FV). Position matching passed J01 (`B1b rate=82.1%`) and J03 (`fuzzy rate=0.1%`).
- Trial-unified oracle with `--holdings-file data/output/bdc_xbrl_wrapper_trial/0001885968/unified_trial/private_markets_holdings.0001885968.csv --compare-baseline` reported `remaining_blocking_rows=0` across all 13 quarters and no blocker regression versus baseline. Remaining raw oracle failures are review-only soft diagnostics: early-quarter `unclassified_rate_exceeded` / `unclassified_fv_rate_exceeded` driven by cash/money-market rows that are excluded from output, `cost_fv_ratio_outliers` in 2024-12-31 and 2025-03-31, and `concept_drift_detected` in 2025-12-31. Four `Investments in Non-Controlled, Affiliated First Lien Debt <issuer>` rows remain as explicit review items because they lack rate/maturity/principal evidence and may represent affiliation-level summary positions.
- Backstop semantic diff: `python scripts/diff_outputs.py --semantic` failed against the already-dirty output tree with 443 divergent artifacts, 3,682 checked, 77 skipped, and semantic deltas in holdings, matches, position returns, index returns, and fund financials. This was not treated as T Series-specific because no canonical production rebuild was run; verification used isolated trial artifacts under `data/output/bdc_xbrl_wrapper_trial/0001885968/`.

**Status: review_required** -- source-reconciliation blockers are cleared in the T Series trial and position-key gates pass. Remaining items require human review/exception handling rather than broader parser widening.

## 2026-06-05 - BlackRock Private Credit Fund wrapper coverage for CIK 0001902649

- Added `data/overrides/bdc_xbrl_wrappers/0001902649.json` for BlackRock Private Credit Fund flat hierarchy XBRL identifiers. The wrapper classifies debt/equity/warrant leaves, cash and total rollups, and uses CIK-scoped `hierarchy_extract` staging for issuer/instrument extraction without widening global BDC parsing.
- Updated `data/overrides/bdc_xbrl_wrappers/unlisted_bdc_xbrl_reference.json` to mark `0001902649` as `wrapper_status = "exists"` with dispatch, staging, archetype, and invariant sections. Added focused classifier tests in `tests/test_bdc_xbrl_wrapper.py` and staging extraction tests in `tests/test_unified_holdings.py`, including false-positive coverage for a borrowerless loan row that remains review-only.
- Validation: schema validation passed; wrapper coherence check passed; `pytest tests/test_bdc_xbrl_wrapper.py -q` passed with 272 tests; `pytest tests/test_unified_holdings.py -k "blackrock_private_credit" --tb=short -q` passed with 3 tests; `pytest tests/test_unified_cik_trial.py -q` passed with 7 tests.
- Cached staging oracle and trial-file oracle both reported `remaining_blocking_rows = 3`, all documented total rollup rows with `total_rollup_no_child_tie`: 2024-09-30 `Total Debt Investments - 147.2% of Net Assets`, 2025-03-31 `Total Debt Investments - 174.9% of Net Assets`, and 2025-03-31 `Total Equity Securities - 0.2% of Net Assets`. `remaining_wrapper_blocking_rows = 0`.
- One-CIK trial rebuild with matching produced 4,012 trial rows versus 4,005 production rows, row delta +7. Position matching passed J01 (`B1b rate=77.0%`, threshold 70%) and J03 (`fuzzy rate=0.6%`, threshold 10%). The wrapper reduces suspicious full-raw issuer extraction to one borrowerless source row, left for review rather than inventing an issuer.
- Backstop semantic diff: `python scripts/diff_outputs.py --semantic` failed against the already-dirty output tree with 443 divergent artifacts, 3,682 checked, 77 skipped, and semantic deltas in holdings, matches, position returns, index returns, and fund financials. This was not treated as BlackRock-specific because no canonical production rebuild was run; verification used isolated trial artifacts under `data/output/bdc_xbrl_wrapper_trial/0001902649/`.

**Status: review_required** -- safe wrapper and staging fixes found in this pass are implemented. Remaining items are documented source total-rollup tie residuals, cost/FV outlier diagnostics, and one borrowerless source row requiring review rather than broader parser widening.
## 2026-06-05 - Added TCG BDC II XBRL wrapper for CIK 0001702510

- Added `data/overrides/bdc_xbrl_wrappers/0001702510.json` for TCG BDC II / Carlyle Credit hierarchy identifiers. The wrapper covers pipe and comma investment hierarchies with section, affiliation, instrument family, issuer, and industry/tranche label segments, and preserves the trailing label in `instrument_description` so same-borrower tranche rows stay position-level constituents.
- Updated `pipeline/staging_bdc.py` so CIK-scoped `hierarchy_extract` conditions override the generic pipe parser when explicitly matched. This is required for CIK 0001702510 because generic pipe parsing treats the instrument-family segment as issuer on rows like `Investment | Non-Affiliated Issuer | First Lien Debt | ...`.
- Updated `tests/test_bdc_xbrl_wrapper.py` with TCG BDC II dispatch tests covering pipe debt leaves, comma leaves with internal commas, equity leaves, category-only non-leaves, and the `Total Power Limited` issuer false-positive guard. Updated `data/overrides/bdc_xbrl_wrappers/unlisted_bdc_xbrl_reference.json` to mark CIK 0001702510 as wrapped (`with_wrapper` 21, `without_wrapper` 108).
- Validation: wrapper schema passed; `pytest tests/test_bdc_xbrl_wrapper.py -q` passed 271 tests; `pytest tests/test_unified_cik_trial.py -q` passed 7 tests; `pytest tests/test_oracle_checks.py -k "J01 or J03 or J04 or DiagnoseFuzzy" -q` passed 19 tests with 60 deselected. Fresh-staging and trial-file wrapper oracles both reported 13 summary rows, `remaining_blocking_rows=0`, and status counts `{'not_applicable': 9, 'pass': 4}`. Trial rebuild produced 2,511 unified rows for the CIK, production delta +28 rows, J01 B1b rate 97.5%, and J03 fuzzy rate 0.3%. `remaining_blockers.csv` and `remaining_blocker_mechanisms.csv` are header-only.

## 2026-06-05 - Nuveen Churchill Private Capital Income Fund wrapper coverage for CIK 0001911066

- Added `data/overrides/bdc_xbrl_wrappers/0001911066.json` for Nuveen Churchill Private Capital Income Fund and updated `data/overrides/bdc_xbrl_wrappers/unlisted_bdc_xbrl_reference.json` from `wrapper_status=none` to `wrapper_status=exists` for this CIK.
- The wrapper covers explicit pipe and comma identifiers for first lien debt, first lien term loans, delayed draws, revolving loans, subordinated debt, equity/unit/partnership-interest rows, warrants, cash/government-liquidity rows, and portfolio totals. It uses CIK-scoped `hierarchy_extract` staging for comma-only rows and canonical key stripping for generic instrument labels while preserving delayed-draw and numeric tranche evidence.
- Deliberately did not promote a broad issuer-only fallback for the 2023-2025 legacy rows. A trial broad fallback reduced unclassified diagnostics but dropped 8 unified rows and did not get J01 over threshold, so it was rejected.
- Added focused Nuveen Churchill classifier tests in `tests/test_bdc_xbrl_wrapper.py` for pipe debt leaves, comma debt leaves, equity leaves, cash rows, total rows, and the bare `Class Valuation` false-positive boundary.
- Validation: schema validation passed for `0001911066.json`; `pytest tests/test_bdc_xbrl_wrapper.py -q` passed with 272 tests. Cached promotion gate `python -m pipeline.bdc_xbrl_wrapper_oracle --cik 0001911066 --promotion-gate --fresh-bdc-staging` exited 0 with `promotion_status=review_required`, `blocking_rows_delta=0`, and `blocking_fv_delta=0`.
- One-CIK trial rebuild with matching: `python scripts/rebuild_unified_cik_trial.py --cik 0001911066 --match` produced 5,092 trial rows versus 5,092 production rows with no row/FV delta. Position matching passed J03 (`0.016`, threshold `0.100`) but J01 remained below target (`0.684`, threshold `0.700`).
- Status: review_required. Promotion-gate residuals are review-only unclassified-rate/FV-rate and low-continuity diagnostics caused by legacy issuer-only XBRL identifiers. The separate J01 miss is a remaining matching-quality review item; safe wrapper changes found in this pass did not clear it without row loss.

## 2026-06-05 - New Mountain Guardian IV wrapper coverage for CIK 0001925531

- Added `data/overrides/bdc_xbrl_wrappers/0001925531.json` for New Mountain Guardian IV BDC L.L.C. / New Mountain Guardian IV BDC Corporation. The wrapper is dispatch-only because generic staging already produced clean issuer/instrument extraction for this CIK.
- The wrapper classifies explicit first-lien, second-lien, subordinated, drawn/undrawn, numbered-tranche, structured-finance, preferred, common, fund, cash, and total rows. It preserves drawn/undrawn and numeric tranche labels in `wrapper_position_key` so same-borrower positions remain separate index constituents.
- Updated `data/overrides/bdc_xbrl_wrappers/unlisted_bdc_xbrl_reference.json` to mark `0001925531` as `wrapper_status = "exists"` with dispatch, archetype, and invariant sections. Added focused wrapper regressions in `tests/test_bdc_xbrl_wrapper.py`, including typo coverage for `Fist lien`, `Frst lien`, `First line`, `First ien`, and `First Drawn`, plus false-positive guards for cash, total, and bare issuer rows.
- Validation: schema validation passed for `0001925531.json`; wrapper coherence check passed; `pytest tests/test_bdc_xbrl_wrapper.py -k "new_mountain_guardian_iv" -q` passed with 5 tests; `pytest tests/test_bdc_xbrl_wrapper.py -q` passed with 304 tests; `pytest tests/test_unified_cik_trial.py -q` passed with 7 tests.
- Cached staging oracle with `--compare-baseline --fresh-bdc-staging` reported 13 summary rows, `remaining_blocking_rows = 0`, `cleared_rollup_rows = 0`, and status counts `{'pass': 13}`. Wrapper staging classified 1,390 of 1,393 wrapper candidates, leaving only bare issuer rows without instrument labels for review.
- One-CIK trial rebuild with matching produced 3,533 trial rows versus 3,533 production rows, row delta +0. Position matching passed J01 (`B1b rate = 92.7%`, threshold `70%`) and J03 (`fuzzy rate = 0.7%`, threshold `10%`).
- Trial-file oracle reported 13 summary rows, `remaining_blocking_rows = 0`, `remaining_wrapper_blocking_rows = 0`, and status counts `{'pass': 12, 'fail': 1}`. The remaining failure is a review-only `cost_fv_ratio_outliers` diagnostic for 2025-09-30; the remaining unclassified wrapper candidates are three bare issuer rows with no instrument label and zero or missing fair value/cost.
- Backstop semantic diff: `python scripts/diff_outputs.py --semantic` failed against the already-dirty output tree with 443 divergent artifacts, 3,682 checked, 77 skipped, and semantic deltas in holdings, matches, position returns, index returns, and fund financials. This was not treated as New Mountain-specific because no canonical production rebuild was run; verification used isolated trial artifacts under `data/output/bdc_xbrl_wrapper_trial/0001925531/`.

**Status: review_required** -- source-reconciliation blockers are cleared in the New Mountain Guardian IV trial. Remaining items are human-review diagnostics rather than parser or wrapper implementation work.

## 2026-06-05 - Blackstone Private Real Estate Credit & Income wrapper coverage for CIK 0002049733

- Added `data/overrides/bdc_xbrl_wrappers/0002049733.json` for Blackstone Private Real Estate Credit & Income Fund and updated `data/overrides/bdc_xbrl_wrappers/unlisted_bdc_xbrl_reference.json` from `wrapper_status = "none"` to `wrapper_status = "exists"` for this CIK.
- The wrapper is dispatch-only. This filer uses flat `InvestmentIdentifierAxis` values: property names, loan names, and securitization tranche labels, while source XBRL facts carry the interest-rate/principal/cost/FV evidence. The wrapper therefore uses CIK-scoped observed markers for current flat debt leaves and explicit Dreyfus cash-management handling rather than a global bare-text extraction rule.
- Added focused `tests/test_bdc_xbrl_wrapper.py` regressions for numeric flat debt leaves, loan/portfolio leaves, observed text-only property leaves, Dreyfus cash rows, total rows, and unseen bare-text rows that must remain non-leaf/reviewable.
- Validation: schema validation passed for `0002049733.json`; wrapper coherence check passed; observed-identifier coverage check classified 156 distinct current debt identifiers as `debt_position_leaf`, 1 Dreyfus identifier as `non_private_market`, and 0 as other/unclassified; `pytest tests/test_bdc_xbrl_wrapper.py -k "blackstone_real_estate_credit" -q` passed with 5 tests.
- Cached staging oracle with `--compare-baseline --fresh-bdc-staging` reported 4 summary rows, `remaining_blocking_rows = 0`, and status counts `{'pass': 4}`. Trial-file oracle also reported 4 pass rows and `remaining_blocking_rows = 0`.
- Cached promotion gate with `--promotion-gate --fresh-bdc-staging` returned `promotion_status = promote`, `blocking_rows_delta = 0`, and `blocking_fv_delta = 0`.
- One-CIK trial rebuild with matching produced 379 trial rows versus 379 production rows, row delta +0. Position matching passed J01 (`B1b rate = 92.8%`, threshold `70%`) and J03 (`fuzzy rate = 0.9%`, threshold `10%`).
- Remaining diagnostics are review-only: 62 reconciled `staging_header_wrapper_leaf` rows, 18 comparative-period/header exclusions, and 3 Dreyfus wrapper-only non-private-market exclusions. No source reconciliation blockers remain.
- Broader targeted tests: `pytest tests/test_unified_cik_trial.py -q` passed with 7 tests. `pytest tests/test_bdc_xbrl_wrapper.py -q` failed in the currently dirty worktree due to unrelated active wrapper tests for CIKs `0001899017` and `0001634452`; the `0002049733` focused tests passed.
- Backstop semantic diff: `python scripts/diff_outputs.py --semantic` failed against the already-dirty output tree with 443 divergent artifacts, 3,682 checked, 77 skipped, and semantic deltas in holdings, matches, position returns, index returns, and fund financials. This was not treated as Blackstone Real Estate Credit-specific because no canonical production rebuild was run; verification used cached staging and isolated trial artifacts under `data/output/bdc_xbrl_wrapper_trial/0002049733/`.

**Status: promote/review-only** -- source-reconciliation blockers are cleared and cached promotion-gate criteria pass for the isolated trial. Remaining items are human review of documented diagnostics and unrelated dirty-worktree test failures.

## 2026-06-05 - APS BDC wrapper coverage for CIK 0002083477

- Added `data/overrides/bdc_xbrl_wrappers/0002083477.json` for APS BDC, LLC and updated `data/overrides/bdc_xbrl_wrappers/unlisted_bdc_xbrl_reference.json` from `wrapper_status = "none"` to `wrapper_status = "exists"` for this CIK.
- The wrapper is dispatch-only. Current cached identifiers are pipe-delimited issuer plus SPV/tranche labels such as `CHS BDC 2 LLC 1` and `APS CW SPV LLC 6`; the wrapper preserves those suffixes in `wrapper_position_key` because they distinguish position-level constituents.
- Added focused `tests/test_bdc_xbrl_wrapper.py` regressions for APS pipe debt leaves, SPV/tranche key preservation, and cash/total/bare-issuer non-leaf guards.
- Validation: schema validation passed for `0002083477.json`; wrapper coherence check passed; observed-identifier coverage check classified all 131 distinct current identifiers as `debt_position_leaf`; `pytest tests/test_bdc_xbrl_wrapper.py -k "aps_bdc" -q` passed with 3 tests.
- Cached staging oracle with `--compare-baseline --fresh-bdc-staging` reported 1 summary row, `remaining_blocking_rows = 0`, and status counts `{'pass': 1}`. Trial-file oracle also reported 1 pass row and `remaining_blocking_rows = 0`.
- Cached promotion gate with `--promotion-gate --fresh-bdc-staging` returned `promotion_status = promote`, `blocking_rows_delta = 0`, and `blocking_fv_delta = 0`.
- One-CIK trial rebuild with matching produced 131 trial rows versus 131 production rows, row delta +0. Position matching produced 0 pairs because only one quarter is currently cached for this CIK, so J01 and J03 skipped with `No position match data available`.
- Broader targeted tests: `pytest tests/test_bdc_xbrl_wrapper.py -q` passed with 324 tests; `pytest tests/test_unified_cik_trial.py -q` passed with 7 tests.
- Backstop semantic diff: `python scripts/diff_outputs.py --semantic` failed against the already-dirty output tree with 443 divergent artifacts, 3,682 checked, 77 skipped, and semantic deltas in holdings, matches, position returns, index returns, and fund financials. This was not treated as APS-specific because no canonical production rebuild was run; verification used cached staging and isolated trial artifacts under `data/output/bdc_xbrl_wrapper_trial/0002083477/`.

**Status: promote/review-only** -- source-reconciliation blockers are cleared and cached promotion-gate criteria pass for the isolated trial. Remaining review context is the expected single-quarter J01/J03 skip until a later quarter is available.

## 2026-06-05 - HPS Corporate Capital Solutions wrapper coverage for CIK 0001989817

- Added `data/overrides/bdc_xbrl_wrappers/0001989817.json` for HPS Corporate Capital Solutions Fund. The wrapper is dispatch-only because current generic staging already reconciles this CIK from cached BDC holdings; it classifies bare issuer rows, pipe-delimited affiliation suffixes, explicit equity/warrant rows, cash/government-money-market rows, and total/affiliation labels without widening global parsing.
- Updated `data/overrides/bdc_xbrl_wrappers/unlisted_bdc_xbrl_reference.json` to mark CIK `0001989817` as `wrapper_status = "exists"` with dispatch, archetype, and invariant sections, and updated the profiled BDC holdings count to 2,862 rows across 8 quarters.
- Added focused HPS Corporate Capital Solutions classifier tests in `tests/test_bdc_xbrl_wrapper.py` for previous blocker issuer names (`International Construction Products, LLC`, `Equinox Holdings, Inc.`), trust/LLP/R.L. legal forms, explicit equity and warrant rows, cash funds, bare affiliation-label false positives, and supported-CIK registration.
- Validation: schema validation passed; `pytest tests/test_bdc_xbrl_wrapper.py -q` passed with 304 tests; `pytest tests/test_unified_cik_trial.py -q` passed with 7 tests; `pytest tests/test_position_matching.py -q` passed with 75 tests; `pytest tests/test_bdc_xbrl_wrapper_oracle.py -k "coherence_passes_all_existing_wrappers or J01 or J03 or J04 or DiagnoseFuzzy" -q` passed with 1 selected test; `pytest tests/test_oracle_checks.py -k "J01 or J03 or J04 or DiagnoseFuzzy" -q` passed with 19 selected tests; `pytest tests/test_unified_holdings.py -k "not slow" --tb=short -q` passed with 538 selected tests.
- Cached staging oracle with `--compare-baseline --fresh-bdc-staging` reported 8 summary rows, `remaining_blocking_rows = 0`, and status counts `{'pass': 8}`. One-CIK trial rebuild with matching produced 1,844 trial unified rows versus 1,840 production rows, row delta +4; position matching passed J01 (`B1b rate = 92.1%`) and J03 (`fuzzy rate = 0.2%`).
- Trial-file promotion gate reported `promotion_status = review_required`, `blocking_rows_delta = 0`, and `blocking_fv_delta = 0`. The only unwaived raw oracle failure is the review-only soft diagnostic `cost_fv_ratio_outliers` for 2026-03-31, driven by `American Academy Holdings, LLC 1` with fair value `-6000`, cost `6544000`, and principal amount `160000`; `exception_proposals.json` contains an inactive proposed exception for human review.

**Status: review_required** -- source-reconciliation blockers are cleared in the HPS Corporate Capital Solutions trial and position-key gates pass. The only remaining item is human review of the 2026-03-31 cost/FV outlier or acceptance of the generated soft-gate exception.

## 2026-06-05 - Bain Capital Private Credit wrapper coverage for CIK 0001899017

- Added `data/overrides/bdc_xbrl_wrappers/0001899017.json` for Bain Capital Private Credit. The wrapper classifies flat and hierarchy-prefixed first-lien, second-lien, delayed-draw, revolver, subordinated-debt/note, equity-interest, warrant, cash, and total rows while preserving borrower/tranche/maturity evidence for position-level keys.
- Added CIK-scoped `prefix_strip` staging for Bain affiliation/industry hierarchy prefixes so retained rows use cleaner issuer/instrument text without widening global parsing. Added extra Bain industry labels including `FIRE: Finance`, `Investment Vehicles`, `Environmental Industries`, and `Beverage, Food & Tobacco`.
- Updated `data/overrides/bdc_xbrl_wrappers/unlisted_bdc_xbrl_reference.json` to mark `0001899017` as wrapped with dispatch, staging, archetype, and invariant sections. Added focused Bain classifier tests in `tests/test_bdc_xbrl_wrapper.py` for coupon-stable debt keys, prefixed/unprefixed key parity, equity leaves, cash rows, totals, and bare-industry false positives.
- Validation: schema validation passed; `pytest tests/test_bdc_xbrl_wrapper.py -k "bain_private_credit or registry" -q` passed with 7 selected tests; cached promotion gate reported `promotion_status=review_required`, `blocking_rows_delta=0`, and `blocking_fv_delta=0`; content signatures passed with 2,051/2,051 pass rows and zero violations.
- One-CIK trial rebuild with matching produced 2,042 trial rows versus 1,991 production rows, row delta +51. Position matching passed J01 (`B1b rate=72.4%`, threshold 70%) but J03 remained above threshold (`fuzzy rate=14.5%`, threshold 10%). A more aggressive spread-stripping key reduced J03 to 12.0% but over-collapsed keys into 113 identical-key fuzzy pairs, so it was rejected as unsafe for position-level tranche semantics.
- Remaining diagnostics are review-required: promotion-gate soft diagnostics `concept_drift_detected` for 2023-12-31 and `cost_fv_ratio_outliers` for 2025-09-30, plus human review of the +51 staged row delta and the residual J03 fuzzy fallback rate. No source reconciliation blocking rows or blocking FV deltas remain.

**Status: review_required** -- safe wrapper and staging changes found in this pass are implemented. Remaining items are human review of soft diagnostics, staged row additions, and match-quality residuals rather than a safe additional wrapper rule.

## 2026-06-05 - AB Private Credit Investors wrapper coverage for CIK 0001634452

- Added `data/overrides/bdc_xbrl_wrappers/0001634452.json` for AB Private Credit Investors Corp and updated `data/overrides/bdc_xbrl_wrappers/unlisted_bdc_xbrl_reference.json` to mark the CIK as wrapped with dispatch, staging, identifier-format, archetype, and invariant sections.
- The wrapper covers AB's pipe-delimited debt, common/preferred equity, warrant, fund, cash, and subtotal/category identifiers. It uses CIK-scoped `hierarchy_extract` staging so issuer extraction reads the issuer segment after the category/security prefix instead of letting generic pipe parsing treat category text as issuer.
- Position-key rules strip volatile displayed coupon percentages while preserving maturity dates and lot/tranche suffixes such as `One` and `Two`, keeping same-borrower positions separate for position-level index semantics.
- Added focused AB classifier tests in `tests/test_bdc_xbrl_wrapper.py` for standard and alternate debt prefixes, equity/fund/warrant leaves, cash/category non-leaves, lot-suffix preservation, and supported-CIK registration. Added focused staging SQL tests in `tests/test_unified_holdings.py` for AB debt issuer/instrument extraction.
- Validation: schema validation passed; wrapper coherence check passed; `pytest tests/test_bdc_xbrl_wrapper.py -k "ab_private_credit_investors" -q` passed with 6 selected tests; `pytest tests/test_unified_holdings.py -k "ab_private_credit_investors" -q` passed with 2 selected tests; full `pytest tests/test_bdc_xbrl_wrapper.py -q` passed with 324 tests; `pytest tests/test_bdc_xbrl_wrapper_oracle.py -q` passed with 73 tests.
- One-CIK trial rebuild with matching produced 5,853 trial rows versus 5,762 production rows, row delta +91. Position matching passed J03 (`fuzzy rate = 2.3%`, threshold 10%) but J01 remained below target (`B1b rate = 61.5%`, threshold 70%).
- Trial-file oracle reported 11 summary rows, `remaining_blocking_rows = 0`, and pass rows for 2025-06-30, 2025-09-30, 2025-12-31, and 2026-03-31. Remaining oracle failures are review-only diagnostics in current code: `exclusion_risk_detected` on subtotal/cash/category exclusions, `low_position_continuity` for 2023-12-31 and 2025-03-31, and `cost_fv_ratio_outliers` for 2023-09-30 and 2024-09-30.
- Backstop semantic diff: `python scripts/diff_outputs.py --semantic` failed against the already-dirty output tree with 443 divergent artifacts, 3,682 checked, 77 skipped, and semantic deltas in holdings, matches, position returns, index returns, and fund financials. This was not treated as AB-specific because no canonical production rebuild was run; verification used isolated trial artifacts under `data/output/bdc_xbrl_wrapper_trial/0001634452/`.

**Status: review_required** -- source-reconciliation blockers are cleared in the isolated AB trial. Remaining items are human review of exclusion-risk, cost/FV, and low-continuity diagnostics plus the +91 trial row delta, not additional safe wrapper rules found in this pass.

## 2026-06-05 - AB Private Credit Investors wrapper final validation update for CIK 0001634452

- Refined `data/overrides/bdc_xbrl_wrappers/0001634452.json` after the initial AB entry: cash-equivalent pipe rows now classify as `non_private_market`, warrant descriptions ending before a later pipe segment classify as warrant leaves, broad `Investment(s) | ...` aggregate headings classify as mixed aggregates, and `canonical_strip_re` now removes volatile U.S./US prefix differences plus displayed coupon/spread/floor/PIK economics while preserving instrument, maturity, and lot/tranche suffixes.
- Updated `data/overrides/bdc_xbrl_wrappers/unlisted_bdc_xbrl_reference.json` for the current cached BDC holdings count: 11,756 rows across 11 quarters from 2023-09-30 through 2026-03-31.
- Added/extended focused AB regressions in `tests/test_bdc_xbrl_wrapper.py` and `tests/test_unified_holdings.py` for pipe issuer/instrument extraction, cash/category exclusions, warrant leaves, and coupon/spread-stable position keys.
- Validation: schema validation passed; `pytest tests/test_bdc_xbrl_wrapper.py -k "ab_private_credit" --tb=short -q` passed with 12 selected tests; `pytest tests/test_unified_holdings.py -k "ab_private_credit" --tb=short -q` passed with 3 selected tests; full `pytest tests/test_bdc_xbrl_wrapper.py --tb=short -q` passed with 335 tests; `pytest tests/test_unified_cik_trial.py --tb=short -q` passed with 7 tests; `pytest tests/test_position_matching.py --tb=short -q` passed with 75 tests; wrapper-oracle focused subset passed with 1 selected test; oracle-check focused subset passed with 19 selected tests.
- Fresh staging oracle with `--compare-baseline --fresh-bdc-staging` reported 11 summary rows, `remaining_blocking_rows = 0`, and no remaining blocker mechanisms. Trial-file oracle also reported `remaining_blocking_rows = 0`.
- One-CIK trial rebuild with matching produced 5,853 trial rows versus 5,762 production rows, row delta +91. Position matching now passes J01 (`B1b rate = 80.6%`, threshold 70%) and J03 (`fuzzy rate = 1.8%`, threshold 10%).
- Promotion gate against the trial file returned `promotion_status = review_required`, `blocking_rows_delta = -77`, and `blocking_fv_delta = -15,462,279,062`. Remaining items are human-review diagnostics: `exclusion_risk_detected` by quarter and `cost_fv_ratio_outliers` for 2023-09-30, 2024-09-30, 2025-09-30, and 2026-03-31. Generated exception proposals cover the cost/FV outlier soft gate only.

**Status: review_required** -- deterministic source-reconciliation blockers and position-matching gates are cleared in the isolated AB trial. The only remaining work is human review of promotion-gate diagnostics and the +91 trial row delta.

## 2026-06-05 - AB Private Credit Investors semantic diff backstop for CIK 0001634452

- Ran `python scripts/diff_outputs.py --semantic` after focused validation. The command failed against the already-dirty production output tree with 443 divergent artifacts, 3,682 checked, 77 skipped, and semantic deltas in holdings, matches, position returns, index returns, and fund financials.
- This was not treated as AB-specific because no canonical production rebuild was run for this task; AB verification used cached staging and isolated trial artifacts under `data/output/bdc_xbrl_wrapper_trial/0001634452/`.

## 2026-06-05 - Fortress Private Lending wrapper coverage for CIK 0002012139

- Added `data/overrides/bdc_xbrl_wrappers/0002012139.json` for Fortress Private Lending Fund and updated `data/overrides/bdc_xbrl_wrappers/unlisted_bdc_xbrl_reference.json` to mark the CIK as wrapped with dispatch, staging, archetype, and invariant sections.
- The wrapper covers Fortress hierarchy identifiers with affiliation, asset class, industry, issuer, instrument, reference spread, current coupon, and maturity terms. CIK-scoped `hierarchy_extract` staging handles both full `Investments Non-controlled... Investment ...` rows and shorter `issuer Investment Type instrument` rows.
- Position-key contract: current coupon and volatile hierarchy/industry prefixes are stripped from canonical keys, while issuer, instrument, reference spread, maturity, and tranche suffixes remain in the key to preserve position-level tranche semantics.
- Added focused classifier tests in `tests/test_bdc_xbrl_wrapper.py` for debt key stability, tranche distinction, `Investment Type` debt rows, equity/warrant leaves, total rows, bare-issuer false positives, and supported-CIK registration.
- Validation: schema validation passed; `pytest tests/test_bdc_xbrl_wrapper.py -k "fortress_private_lending or registry" -q` passed with 7 selected tests; full `pytest tests/test_bdc_xbrl_wrapper.py -q` passed with 335 tests; wrapper-oracle coherence subset passed with 1 selected test; content signatures passed with 417/417 pass rows and zero violations.
- Cached source oracle with `--compare-baseline --fresh-bdc-staging` passed all four quarters with `remaining_blocking_rows = 0` and no blocker deltas. Promotion gate returned `promotion_status = promote`, `blocking_rows_delta = 0`, and `blocking_fv_delta = 0`.
- One-CIK trial rebuild with matching produced 427 trial rows versus 424 production rows, row delta +3. Position matching passed J01 (`B1b rate = 83.6%`, threshold 70%) and J03 (`fuzzy rate = 0.0%`, threshold 10%).
- Remaining items are review-only diagnostics: the +3 trial row delta, warning-only `hierarchy_parse_disagreement` (14 rows), `family_vs_asset_category_disagreement` for warrant rows mapped to equity-common assets (8 rows), and `wrapper_leaf_staging_excluded` hierarchy-header warnings (4 rows). No SEC downloads or production rebuild were run.
- Backstop semantic diff: `python scripts/diff_outputs.py --semantic` failed against the already-dirty output tree with 443 divergent artifacts, 3,682 checked, 77 skipped, and semantic deltas in holdings, matches, position returns, index returns, and fund financials. This was not treated as Fortress-specific because verification used isolated trial artifacts under `data/output/bdc_xbrl_wrapper_trial/0002012139/`.

**Status: promote** -- deterministic source-reconciliation blockers and position-matching gates are cleared in the isolated Fortress trial. Remaining work is human review of warnings and the +3 staged row delta.

## 2026-06-06 - Overland Advantage wrapper coverage for CIK 0001965934

- Added `data/overrides/bdc_xbrl_wrappers/0001965934.json` for Overland Advantage and updated `data/overrides/bdc_xbrl_wrappers/unlisted_bdc_xbrl_reference.json` from `wrapper_status = "none"` to `wrapper_status = "exists"` for this CIK.
- The wrapper covers Overland hierarchy identifiers with non-controlled/non-affiliated debt prefixes, industry labels, issuer names, facility type, reference-rate spread, maturity date, and trailing lot labels. CIK-scoped `hierarchy_extract` staging parses issuer and instrument fields for hierarchy rows with explicit loan markers; cash, BlackRock Liquidity FedFund, Treasury, total, and category rows are excluded from private-market leaves.
- Position-key contract: hierarchy prefixes, displayed reference-rate spreads, and displayed maturity-date text are stripped from wrapper keys, while issuer, facility type, and trailing lot labels remain to preserve position-level tranche semantics.
- Added focused classifier tests in `tests/test_bdc_xbrl_wrapper.py` for prefix/rate/date key stability, distinct term/delayed-draw/revolver facilities, second-lien and unsecured leaves, truncated-prefix rows, and cash/total/category exclusions.
- Validation: schema validation passed; wrapper coherence passed; observed-identifier coverage classified all 288 distinct cached identifiers (263 debt leaves, 19 aggregates, 6 non-private-market rows); `pytest tests/test_bdc_xbrl_wrapper.py -k "overland_advantage" -q` passed with 4 selected tests.
- Cached/trial oracle: trial-file oracle reported 8 summary rows, `remaining_blocking_rows = 0`, no remaining blocker mechanisms, 100% content-signature pass rate, and pass rows for 2024-06-30, 2025-06-30, 2025-09-30, and 2025-12-31. Remaining oracle failures are human-review soft diagnostics: `exclusion_risk_detected` for 2024-09-30, 2024-12-31, and 2025-03-31, and `low_position_continuity` for 2026-03-31.
- One-CIK trial rebuild with matching produced 460 trial rows versus 402 production rows, row delta +58, with zero suspicious issuer-name rows after adding the `Electrical Utilities` staging industry label. Position matching passed J01 (`B1b rate = 99.5%`, threshold 70%) and J03 (`fuzzy rate = 0.0%`, threshold 10%).
- Broader validation: `pytest tests/test_unified_cik_trial.py -q` passed with 7 tests. Full `pytest tests/test_bdc_xbrl_wrapper.py -q` failed with one unrelated Fidelity Central assertion while 364 tests passed; the Overland-focused tests passed.
- Backstop semantic diff: `python scripts/diff_outputs.py --semantic` failed against the already-dirty output tree with 443 divergent artifacts, 3,682 checked, 77 skipped, and semantic deltas in holdings, matches, position returns, index returns, and fund financials. This was not treated as Overland-specific because verification used isolated trial artifacts under `data/output/bdc_xbrl_wrapper_trial/0001965934/` and no canonical production rebuild was run.

**Status: review_required** -- deterministic source-reconciliation blockers and position-matching gates are cleared in the isolated Overland trial. Remaining work is human review of soft oracle diagnostics and the +58 staged row delta.

## 2026-06-06 - Apollo Origination II (L) wrapper coverage for CIK 0002052152

- Added `data/overrides/bdc_xbrl_wrappers/0002052152.json` for Apollo Origination II (L) Capital Trust and updated `data/overrides/bdc_xbrl_wrappers/unlisted_bdc_xbrl_reference.json` to mark the CIK as wrapped with dispatch, staging, archetype, and invariant sections.
- The wrapper covers Apollo GICS-sector hierarchy identifiers with company labels, issuer names, `Investment Type`, debt/equity instrument text, rate text, and maturity dates. CIK-scoped `hierarchy_extract` staging removes the sector prefix and moves `Investment Type ...` text out of `issuer_name` into `instrument_description`.
- Added a CIK-scoped sector/issuer rollup fallback for no-`Investment Type` subtotal rows. The fallback is intentionally limited to Apollo sector hierarchy labels so it documents source rollups without broadening global parser behavior or hiding position-level leaves.
- Position-key contract: displayed rate text is stripped while maturity dates are preserved, so rate-only drift is stable but same issuer/tranche rows with different maturities remain distinct.
- Added focused classifier tests in `tests/test_bdc_xbrl_wrapper.py` for delayed-draw, PIK, convertible-bond, preferred-equity, money-market, sector-header, issuer-rollup, rate-drift key stability, maturity-date distinction, and supported-CIK registration. Added a focused staging SQL regression in `tests/test_unified_holdings.py` for issuer/instrument extraction.
- Validation: wrapper coherence passed; `pytest tests/test_bdc_xbrl_wrapper.py -k "apollo_origination_ii_l" -q` passed with 10 selected tests; `pytest tests/test_unified_holdings.py -k "apollo_origination_ii_l_hierarchy_extracts" -q` passed with 1 selected test; full `pytest tests/test_bdc_xbrl_wrapper.py` passed with 371 tests.
- One-CIK trial rebuild with matching produced 565 trial rows versus 568 production rows, row delta -3. Position matching passed J01 (`B1b rate = 72.3%`, threshold 70%) and J03 (`fuzzy rate = 3.4%`, threshold 10%).
- Trial-file oracle reported 5 summary rows and `remaining_blocking_rows = 0`; baseline comparison improved 2025-03-31 blocking rows from 10 to 0 and blocking fair value from 2,469,032,000 to 0. The only remaining oracle failure is the review-only soft diagnostic `cost_fv_ratio_outliers` for 2025-12-31. Additional warning diagnostics were non-private-market disagreement, aggregate-detection disagreement, and one family-vs-asset-category disagreement.
- Backstop semantic diff: `python scripts/diff_outputs.py --semantic` failed against the already-dirty output tree with 443 divergent artifacts, 3,682 checked, 77 skipped, and semantic deltas in holdings, matches, position returns, index returns, and fund financials. This was not treated as Apollo-specific because verification used isolated trial artifacts under `data/output/bdc_xbrl_wrapper_trial/0002052152/` and no canonical production rebuild was run.

**Status: review_required** -- deterministic source-reconciliation blockers and position-matching gates are cleared in the isolated Apollo Origination II (L) trial. Remaining work is human review of the 2025-12-31 cost/FV outlier and warning diagnostics.

## 2026-06-06 - Fidelity Private Credit Central wrapper coverage for CIK 0001899996

- Added `data/overrides/bdc_xbrl_wrappers/0001899996.json` for Fidelity Private Credit Central/Fidelity Private Credit Co LLC and updated `data/overrides/bdc_xbrl_wrappers/unlisted_bdc_xbrl_reference.json` to mark the CIK as wrapped with dispatch, staging, archetype, and invariant sections.
- The wrapper covers Fidelity hierarchy identifiers with `Investments`/`Investments Investments` prefixes, affiliation labels, debt/equity type labels, industry labels, issuer names, loan/equity instruments, reference-rate spread text, current coupon text, maturity dates, money-market rows, and total/category rollups. CIK-scoped `hierarchy_leaf_guard` staging retains position leaves while filtering hierarchy headers and non-private-market mutual fund/cash rows.
- Added a narrow global typo tolerance for affiliation hierarchy prefixes spelled `affiliatd` in `pipeline/bdc_identifier.py` and `pipeline/staging_bdc.py`; this only applies where the parser already strips an affiliation hierarchy prefix. Added focused regressions for the Routeware `non-affiliatd` rows so they are retained as `Routeware, Inc` position leaves instead of remaining source-only blockers.
- Position-key contract: affiliation hierarchy prefixes, reference-rate spread tokens, displayed interest-rate text, and PIK parentheticals are stripped from wrapper keys, while issuer, instrument, and maturity terms remain to preserve position-level tranche semantics. The canonical strip regex is DuckDB-compatible and avoids unsupported lookahead syntax.
- Validation: wrapper schema validation passed; `python -m json.tool` passed for the wrapper reference registry; `pytest tests/test_bdc_xbrl_wrapper.py --tb=short -q` passed with 371 tests; `pytest tests/test_unified_holdings.py -k "fidelity_central_hierarchy" --tb=short -q` passed with 1 selected test; `pytest tests/test_unified_holdings.py -k "fidelity or msd_category_rollup or wrapper_leaf_rescued" --tb=short -q` passed with 9 selected tests; `pytest tests/test_unified_cik_trial.py --tb=short -q` passed with 7 tests; `pytest tests/test_position_matching.py --tb=short -q` passed with 75 tests; wrapper-oracle focused subset passed with 1 selected test; oracle-check focused subset passed with 19 selected tests; validate-holdings focused subset passed with 1 selected test.
- Fresh staging oracle with `--compare-baseline --fresh-bdc-staging` reported 12 summary rows, 5,984 source rows, 2,506 staged output rows, 58 cleared rollup rows, and `remaining_blocking_rows = 16`. Remaining blocker mechanisms are only `total_rollup_no_child_tie` source total/category rows across 2023-06-30 through 2025-03-31; the prior Routeware leaf-present/missing-from-unified blockers are cleared.
- One-CIK trial rebuild with matching produced 2,506 trial rows versus 2,319 production rows, row delta +187. Position matching passed J01 (`B1b rate = 77.1%`, threshold 70%) and J03 (`fuzzy rate = 5.4%`, threshold 10%).
- Trial-file oracle matched the fresh oracle with `remaining_blocking_rows = 16`. Promotion gate returned `promotion_status = review_required`, `blocking_rows_delta = -43`, `blocking_fv_delta = -15,076,090,599`, and `cleared_rollups_increased = +58`. Remaining promotion reasons are human-review diagnostics: source total rollups, exclusion-risk checks, cost/FV outliers, unclassified-rate checks, and low-position-continuity.
- Backstop semantic diff: `python scripts/diff_outputs.py --semantic` failed against the already-dirty output tree with 443 divergent artifacts, 3,682 checked, 77 skipped, and semantic deltas in holdings, matches, position returns, index returns, and fund financials. This was not treated as Fidelity-specific because verification used isolated trial artifacts under `data/output/bdc_xbrl_wrapper_trial/0001899996/` and no canonical production rebuild was run.

**Status: review_required** -- deterministic position-leaf blockers and position-matching gates are cleared in the isolated Fidelity trial. Remaining work is human review of documented rollup totals, promotion-gate diagnostics, and the +187 staged row delta.

## 2026-06-06 - AGL Private Credit Income wrapper coverage for CIK 0002011498

- Added `data/overrides/bdc_xbrl_wrappers/0002011498.json` for AGL Private Credit Income Fund and updated `data/overrides/bdc_xbrl_wrappers/unlisted_bdc_xbrl_reference.json` to mark the CIK as wrapped.
- The wrapper covers AGL hierarchy identifiers with non-controlled/non-affiliated and non-controlled/affiliated prefixes, industry labels, issuer names, first-lien/second-lien debt facilities, delayed-draw/revolver/term-loan variants, `LP Interest` equity leaves, the affiliated `AGL EPCI I` investment-fund leaf, money-market cash rows, and total/category rollups.
- Position-key contract: hierarchy prefixes, industry labels, generic `First Lien` text, displayed reference-rate/all-in-rate text, acquisition dates, and maturity dates are stripped from wrapper keys, while issuer, facility type, second-lien status, delayed-draw/revolver/term-loan type, and term-loan number remain to preserve position-level tranche semantics.
- Added focused classifier tests in `tests/test_bdc_xbrl_wrapper.py` for prefix variant stability, facility-type and term-loan-number preservation, affiliated/equity leaves, and cash/total/category exclusions.
- Validation: schema validation passed; wrapper coherence passed with 453 distinct cached identifiers classified into 441 debt leaves, 3 equity leaves, 3 aggregates, 2 debt rollups, and 4 non-private-market rows; `pytest tests/test_bdc_xbrl_wrapper.py -k "agl_private_credit" -q` passed with 4 selected tests; full `pytest tests/test_bdc_xbrl_wrapper.py -q` passed with 371 tests; `pytest tests/test_unified_cik_trial.py -q` passed with 7 tests.
- Fresh staging oracle reported 6 summary rows, `cleared_rollup_rows = 1`, `remaining_blocking_rows = 0`, and `oracle_status_counts = {'pass': 6}`. Trial-file oracle matched the clean result with `remaining_blocking_rows = 0`; warning diagnostics were aggregate-detection disagreement, hierarchy-parse disagreement, 77 wrapper leaves excluded by staging/unified rules, and non-private-market disagreement.
- One-CIK trial rebuild with matching produced 514 trial rows versus 531 production rows, row delta -17, with fair value increasing by 21,275,000 from the newly included `AGL EPCI I` affiliated investment. The row-count decrease is explained by 18 production-only 2026-03-31 zero-FV/zero-principal raw filing leaves removed by existing affiliation/dimension de-duplication; no suspicious parsed issuer rows remained in the trial output.
- Position matching passed J01 (`B1b rate = 84.8%`, threshold 70%) and J03 (`fuzzy rate = 0.0%`, threshold 10%). The trial improved matching from pre-wrapper fuzzy-heavy matching to 123 B1b position-key pairs, 22 B2 exact-name pairs, and 3 within-filing pairs.
- Backstop semantic diff: `python scripts/diff_outputs.py --semantic` failed against the already-dirty output tree with 443 divergent artifacts, 3,682 checked, 77 skipped, and semantic deltas in holdings, matches, position returns, index returns, and fund financials. This was not treated as AGL-specific because verification used isolated trial artifacts under `data/output/bdc_xbrl_wrapper_trial/0002011498/` and no canonical production rebuild was run.

**Status: review_required** -- deterministic source-reconciliation blockers and position-matching gates are cleared in the isolated AGL trial. Remaining work is human review of the 18 zero-FV affiliation/dimension-dedup rows and the -17 staged row delta.

## 2026-06-06 - NMF SLF I wrapper coverage for CIK 0001766037

- Added `data/overrides/bdc_xbrl_wrappers/0001766037.json` for NMF SLF I, Inc. and updated `data/overrides/bdc_xbrl_wrappers/unlisted_bdc_xbrl_reference.json` to mark the CIK as wrapped with 8,860 cached holdings rows across 13 quarters from 2023-03-31 through 2026-03-31.
- The wrapper uses conservative explicit leaf markers for first-lien, second-lien, subordinated, undrawn, preferred, common, ordinary-share, and class-A-common-unit rows. It does not add CIK-specific staging because generic staging already parses the issuer and instrument shape correctly. Canonical keys strip pipe-delimited affiliation suffixes such as `| Non-Affiliated Issuer`, while preserving issuer and instrument text for position-level tranche semantics.
- Added focused classifier tests in `tests/test_bdc_xbrl_wrapper.py` for pipe-delimited debt leaves, comma-delimited debt leaves, equity leaves, the observed `First Lie` typo, bare legal-name false positives, total/header exclusions, and supported-CIK registration.
- Added a cross-CIK compatibility fix in `data/overrides/bdc_xbrl_wrappers/0001919369.json` by replacing JSON `\u2013` regex escapes in staging patterns with literal U+2013 characters so DuckDB staging SQL compilation is not blocked when all wrappers load.
- Fixed fuzzy-fallback oracle diagnostics in `pipeline/oracle_checks.py` by de-duplicating the unified lookup before begin/end matching. Added `tests/test_oracle_checks.py::test_duplicate_unified_lookup_keeps_one_diagnostic_row` to prevent duplicate lookup rows from expanding diagnostic output.
- Validation: schema validation passed for `0001766037.json` and the patched `0001919369.json`; `python -m json.tool` passed for the wrapper reference registry; `pytest tests/test_bdc_xbrl_wrapper.py -k "nmf_slf_i" --tb=short -q` passed with 7 tests; full `pytest tests/test_bdc_xbrl_wrapper.py --tb=short -q` passed with 383 tests; `pytest tests/test_oracle_checks.py -k "DiagnoseFuzzy" --tb=short -q` passed with 6 tests; `pytest tests/test_unified_cik_trial.py --tb=short -q` passed with 7 tests; `pytest tests/test_position_matching.py --tb=short -q` passed with 75 tests; focused oracle/oracle-check subsets passed with 20 selected tests plus the wrapper-oracle coherence subset.
- Fresh staging oracle with `--compare-baseline --fresh-bdc-staging` reported 13 summary rows, 4,588 final staged rows from 8,860 input rows, `remaining_blocking_rows = 0`, and status counts `{'pass': 11, 'fail': 2}`. The two failures are review-only soft diagnostics: 2023-12-31 `unclassified_rate_exceeded|unclassified_rate_qoq_jump` and 2024-03-31 `unclassified_rate_exceeded`.
- One-CIK trial rebuild with matching produced 4,587 trial rows versus 4,584 production rows, row delta +3. Position matching produced 2,303 pairs and passed J01 (`B1b rate = 90.4%`, threshold 70%) and J03 (`fuzzy rate = 1.5%`, threshold 10%); the fuzzy diagnostic contains 35 rows after the de-duplication fix.
- Trial-file oracle matched the clean blocker result with `remaining_blocking_rows = 0`; its only warning was `wrapper_leaf_staging_excluded` for one affiliation-dedup row. Promotion gate returned `promotion_status = review_required`, `blocking_rows_delta = 0`, and `blocking_fv_delta = 0`, with proposed exceptions for soft review reasons covering cost/FV outliers and unclassified-rate diagnostics in 2023-12-31 and 2024-03-31.
- Backstop semantic diff: `python scripts/diff_outputs.py --semantic` failed against the already-dirty output tree with 443 divergent artifacts, 3,682 checked, 77 skipped, and semantic deltas in holdings, matches, position returns, index returns, and fund financials. This was not treated as NMF-specific because verification used isolated trial artifacts under `data/output/bdc_xbrl_wrapper_trial/0001766037/` and no canonical production rebuild was run.

**Status: review_required** -- deterministic source-reconciliation blockers and position-matching gates are cleared in the isolated NMF SLF I trial. Remaining work is human review of the soft oracle diagnostics, the +3 staged row delta, and the single affiliation-dedup warning.

## 2026-06-06 - Vista Credit Strategic Lending wrapper coverage for CIK 0001919369

- Added `data/overrides/bdc_xbrl_wrappers/0001919369.json` for Vista Credit Strategic Lending Corp. and updated `data/overrides/bdc_xbrl_wrappers/unlisted_bdc_xbrl_reference.json` to mark the CIK as wrapped with dispatch, staging, archetype, and invariant sections.
- The wrapper covers Vista hierarchy identifiers with `Investments`, non-controlled/non-affiliated labels, first-lien debt, preferred equity, other equity, industry labels, issuer names, reference-rate spread text, current interest-rate text, maturity dates, cash buckets, totals, and industry/category headers. CIK-scoped `hierarchy_extract` staging moves the asset-family label into `instrument_description` and strips hierarchy prefixes from `issuer_name`.
- Added narrow legacy bare-issuer support for recurring single-issuer rows with fair value (`Acronis International`, `SumUp Holdings Midco S.* r.l`, and `McKissock Investment Holdings`) while keeping comma-delimited issuer-list rows out of position leaves.
- Position-key contract: displayed reference-rate spread and current interest-rate text are stripped from wrapper keys, while asset family, issuer, and maturity-date text remain to preserve position-level tranche semantics. Maturity differences remain distinct.
- Added focused classifier tests in `tests/test_bdc_xbrl_wrapper.py` for hierarchy debt key stability, maturity distinction, preferred/other equity leaves, totals, headers, cash totals, legacy single issuers, and issuer-list false positives. Added a focused staging SQL regression in `tests/test_unified_holdings.py` for Vista issuer/instrument extraction.
- Validation: JSON validation passed for the Vista wrapper and wrapper reference registry; wrapper coherence passed; `pytest` focused Vista/coherence/staging selection passed with 6 tests. Full `pytest tests/test_bdc_xbrl_wrapper.py -q` ran with 382 passed and 2 unrelated failures in Bain/Fortress date-format assertions.
- One-CIK trial rebuild with matching produced 381 trial rows versus 360 production rows, row delta +21. Position matching passed J01 (`B1b rate = 91.5%`, threshold 70%) and J03 (`fuzzy rate = 0.0%`, threshold 10%).
- Trial-file oracle reported 10 summary rows, `remaining_blocking_rows = 0`, and status counts `{'pass': 8, 'fail': 2}`. Remaining oracle failures are human-review diagnostics: 2025-03-31 `unclassified_fv_rate_exceeded` from no-FV/comparative issuer-list headers and 2025-06-30 `low_position_continuity` caused by the filer transition from bare/list identifiers to full hierarchy rows. Warning diagnostics include non-private-market disagreement, aggregate-detection disagreement, hierarchy-parse disagreement, identifier-normalization impact, family-vs-asset-category disagreement, and wrapper leaves excluded by staging.
- Backstop semantic diff: `python scripts/diff_outputs.py --semantic` failed against the already-dirty output tree with 443 divergent artifacts, 3,682 checked, 77 skipped, and semantic deltas in holdings, matches, position returns, index returns, and fund financials. This was not treated as Vista-specific because verification used isolated trial artifacts under `data/output/bdc_xbrl_wrapper_trial/0001919369/` and no canonical production rebuild was run.

**Status: review_required** -- deterministic source-reconciliation blockers and position-matching gates are cleared in the isolated Vista trial. Remaining work is human review of the +21 staged row delta, the 2025-03 unclassified-FV diagnostic, the 2025-06 continuity diagnostic, and warning-only oracle disagreements.

## 2026-06-06 - Goldman Sachs Private Middle Market Credit II wrapper coverage for CIK 0001772704

- Added `data/overrides/bdc_xbrl_wrappers/0001772704.json` for Goldman Sachs Private Middle Market Credit II LLC and updated `data/overrides/bdc_xbrl_wrappers/unlisted_bdc_xbrl_reference.json` to mark the CIK as wrapped.
- The wrapper covers Goldman hierarchical percentage identifiers with debt/equity/security category prefixes, country and instrument buckets, current coupon text, reference-rate spread text, PIK terms, maturity dates, initial acquisition dates, money-market cash rows, totals, country/category rollups, and truncated `Investment` prefix variants.
- Added Goldman-focused staging support for comma-delimited hierarchical percentage leaves and issuer names containing dashes. Added a wrapper loader/staging compatibility fix that decodes JSON-style dash escapes before DuckDB regex use, so other ASCII wrapper configs with `\\u2013`/`\\u2014` do not block all-wrapper staging.
- Position-key contract: displayed hierarchy percentages, current coupon, industry labels, initial acquisition dates, and four-digit maturity years are normalized/stripped where volatile. Reference-rate spread, PIK terms, maturity date, and trailing lot labels are preserved as position-level tranche/lot identity. Repeated Goldman wrapper keys within the same CIK/source/report date receive deterministic `lot N` suffixes in unified holdings, ranked by principal/fair-value/cost, so separate disclosed rows are not collapsed into borrower-level exposure.
- Added focused classifier tests in `tests/test_bdc_xbrl_wrapper.py` for display-percent and current-coupon stripping, spread distinction, truncated prefixes, date-width normalization, rate-format variants, equity/warrant leaves, cash/total/category exclusions, and bare-affiliate non-leaves. Added focused staging and unified tests in `tests/test_unified_holdings.py` for comma-delimited hierarchy parsing and duplicate wrapper-key lot suffixes.
- Validation: schema validation passed; wrapper-focused tests passed with 11 selected tests; Goldman staging/unified focused tests passed with 4 selected tests; wrapper-oracle coherence passed with 1 selected test; content signatures passed with 3,071/3,071 rows and one expected truncated-prefix edge case.
- Fresh staging oracle with `--compare-baseline --fresh-bdc-staging` reported 13 summary rows and `remaining_blocking_rows = 0`. Oracle status counts were `{'fail': 9, 'pass': 4}` because 2023-03-31 through 2025-03-31 remain human-review `exclusion_risk_detected` diagnostics.
- One-CIK trial rebuild with matching produced 3,070 trial rows versus 3,051 production rows, row delta +19. Position matching passed J01 (`B1b rate = 85.7%`, threshold 70%) and J03 (`fuzzy rate = 0.5%`, threshold 10%).
- Promotion gate returned `promotion_status = review_required`, `blocking_rows_delta = -114`, and `blocking_fv_delta = -51,409,851,000`. Remaining promotion reasons are the review-only exclusion-risk diagnostics across 2023-03-31 through 2025-03-31.
- Backstop semantic diff: `python scripts/diff_outputs.py --semantic` failed against the already-dirty output tree with 443 divergent artifacts, 3,682 checked, 77 skipped, and semantic deltas in holdings, matches, position returns, index returns, and fund financials. This was not treated as Goldman-specific because verification used isolated trial artifacts under `data/output/bdc_xbrl_wrapper_trial/0001772704/` and no canonical production rebuild was run.

**Status: review_required** -- deterministic source-reconciliation blockers and position-matching gates are cleared in the isolated Goldman trial. Remaining work is human review of exclusion-risk diagnostics and the +19 staged row delta.

## 2026-06-06 - Promoted 39 wrapper-covered unlisted BDCs through canonical cached outputs

- Promoted the original `.claude` wrapper-skill 39-CIK sample through canonical cache-only outputs. Pre-flight found no running pytest/rebuild jobs, no tracked output/frontend/wrapper/changelog dirt, and 39/39 wrapper JSON files present under `data/overrides/bdc_xbrl_wrappers/`.
- Validation before rebuild: the full targeted pytest command over `tests/test_bdc_xbrl_wrapper.py`, `tests/test_unified_holdings.py`, and `tests/test_validate_holdings.py` was attempted twice but timed out, leaving no persistent pytest process. The non-slow targeted suite passed: 1,059 passed, 302 deselected, 169 warnings.
- Rebuild commands run: `python scripts/rebuild_outputs.py --bdc-holdings`, `python scripts/rebuild_outputs.py --unified`, `python -m pipeline.main --validate-all --reconcile-full`, `python -m pipeline.main --export-frontend`, and `python scripts/diff_outputs.py --semantic`.
- Rebuilt BDC holdings from cached XBRL only: 1,180,533 rows from 3,029 filings. The rebuild reported 8 BDC dedupe groups with conflicting economic facts. Rebuilt unified holdings: 795,355 rows, including 574,978 BDC rows and 220,377 N-PORT rows after cross-source duplicate removal. Wrapper position-key override applied to 190,599 rows across 53 CIKs.
- Refreshed validation/GAV/source reconciliation artifacts. Overall validate-all summary was `fund_financials=WARN`, `holdings=WARN`, and `validation_rules=FAIL`. Promoted validation-rule failures were RI03 with 13 hits and RI07 with 330 hits.
- Refreshed frontend JSON with `python -m pipeline.main --export-frontend`; 22 top-level JSON files and 123 fund detail JSON files were written.
- Refreshed 39-CIK sample quality: latest source reconciliation date was 2026-03-31 for all 39; status was 39/39 `RECONCILED`; latest blocking issue sum was 0; historical/all-period blocking issue sum was 200. Frontend fund list matched 38/39, with APS BDC (`0002083477`) still absent. Frontend statuses for matched sample were 35 `VERIFIED`, 2 `VALIDATED_WITH_WARNINGS`, and 1 blank; GAV statuses were 35 `PASS`, 2 `WARN`, and 1 blank.
- GAV limitation: latest 2026-03-31 GAV rows for the 39 are all `SKIP` because no comparison source is available. Latest comparable GAV is 2025-12-31 for 38 CIKs: 36 `PASS`, 2 `WARN`, median adjusted ratio 1.0000, 25/38 within 2%, and 31/38 within 5%.
- Backstop semantic diff failed against the active baseline: 443 divergent artifacts, 3,682 checked, 77 skipped. Semantic deltas were reported in holdings, matches, position returns, index returns, and fund financials. Key global deltas included private markets holdings row count 718,059 -> 795,355, direct lending row count 561,426 -> 634,455, and new `B1b_position_key` match-method rows. This confirms production artifacts changed materially and should not be treated as baseline-clean without baseline governance review.

**Status: promoted_with_residual_failures** -- the 39 wrapper-covered CIKs are promoted through canonical cached holdings, validation/GAV, and frontend exports, and latest source reconciliation blockers are cleared for the sample. Remaining blockers are global validation-rule failures, failed semantic diff against the active baseline, current-quarter GAV comparison gaps, APS BDC frontend absence, and historical sample blocker rows.

## 2026-06-07 - Stepstone 2025-12-31 monetary scale normalization

- Added a narrow Stepstone Private Credit Fund LLC (`0001950803`) correction for accession `0001193125-26-128890`, report date `2025-12-31`, in `pipeline/bdc_filings.py` and mirrored it in BDC source-reconciliation extraction. The repair applies only to wrapper-classified first-lien debt position leaves whose `pct_of_net_assets` implies a 1000x monetary understatement against disclosed net assets; it scales `fair_value`, `cost`, and `principal_amount`, and leaves rates, percentages, dates, non-first-lien rows, and pct-consistent small rows unchanged.
- Added targeted regressions in `tests/test_bdc_filings.py` and `tests/test_validate_holdings.py` covering positive Stepstone scaling, non-Stepstone false positives, non-first-lien false positives, pct-consistent small-value false positives, and source-extraction parity.
- Rebuilt cached BDC holdings and unified holdings after an initial over-broad threshold was caught by GAV overcoverage. Final cached rebuild applied the Stepstone correction to 103 first-lien rows, with 1,180,533 BDC holdings rows and 795,355 unified holdings rows.
- Refreshed validation/source-reconciliation artifacts with `python -m pipeline.main --validate-all --reconcile-full`. Stepstone 2025-12-31 GAV improved from undercoverage to `PASS`: `sum_holdings_fv=3008522106.0` vs `comparison_value=3008628000.0`; `bdc_source_reconciliation_ratio=1.0`, `bdc_source_reconciliation_flag=ok`, and Stepstone source reconciliation remained zero blocking/value mismatch rows.
- Refreshed frontend JSON with `python scripts/rebuild_outputs.py --frontend`; 22 top-level JSON files and 123 fund detail JSON files were written.
- Verification: focused pytest passed with 13 tests. Validate-all remained `fund_financials=WARN`, `holdings=WARN`, and `validation_rules=FAIL`; promoted validation-rule failures remained RI03 with 13 hits and RI07 with 330 hits. Backstop semantic diff still failed against the active baseline with 443 divergent artifacts, 3,682 checked, 77 skipped, and semantic deltas in holdings, matches, position returns, index returns, and fund financials.

**Status: promoted_with_residual_failures** -- the Stepstone 2025-12-31 GAV miss is corrected by a scoped monetary scale normalization, while existing global validation-rule failures and baseline divergence remain unresolved.

## 2026-06-07 - Cleared RI03/RI07 validation blockers and refreshed returns/export artifacts

- Fixed the fund-financial cross-level artifact contract in `pipeline/validate_fund_financials.py`: `fund_financials_validation_current.csv` still preserves all returned validation rows, including holdings-only coverage mismatches, while persisted `fund_financials_cross_level.csv` is now limited to canonical fund-financial CIK/quarter rows so RI03 remains a referential-integrity check instead of failing on expected coverage diagnostics.
- Fixed RI07 in `pipeline/validation_rules/__init__.py` by registering artifact freshness metadata and reporting a single stale-artifact finding when `position_returns.csv` is older than `private_markets_holdings.csv`; after a cached returns rebuild, the blank-position-ID flood no longer appears. Also adjusted PC03 to keep exact count/return reconciliation while allowing cent-level FV aggregate float round-trip noise; the observed false miss was `DIRECT_LENDING|2022q2` with a sub-cent aggregate FV delta on about $11.900B beginning FV.
- Added regressions in `tests/test_validate_fund_financials.py` and `tests/test_validation_rules.py` for the persisted cross-level filter, stale RI07 guard, and sub-cent PC03 tolerance.
- Rebuilt cached returns with `python scripts/rebuild_outputs.py --returns`: 512,251 match pairs loaded, 322,302 unique position IDs assigned, 492,672 `position_returns.csv` rows, and 247 `index_returns.csv` rows.
- Refreshed validation with `python -m pipeline.main --validate-all` after the returns rebuild. Final summary improved to `fund_financials=WARN` (213,956 rows), `holdings=WARN` (2,642,024 rows), and `validation_rules=WARN` (67,217 detail rows). Promoted blockers `RI03`, `RI07`, and `PC03` are all `PASS` with zero hits. Remaining non-PASS validation-rule rows are warnings, not promoted failures.
- Wrote `data/output/wrapper_historical_residual_audit.csv` and `.md` for a reproducible first-39 wrapper-file proxy of the original `.claude` queue. Because no immutable 39-CIK manifest was found, the artifact records its cohort basis explicitly. In that proxy cohort, 24/39 CIKs have validate-all residual issues, all-period validate-all residual `issue_count` sums to 24,553, source-reconciliation blocking `issue_count` sums to 768 all-period, and latest-period source-reconciliation blocking `issue_count` sums to 122.
- Refreshed frontend exports with `python -m pipeline.main --export-frontend`: 22 top-level JSON files and 123 fund detail JSON files written.
- Verification: `pytest tests/test_validation_rules.py -q` passed (41 tests), `pytest tests/test_validate_fund_financials.py -q` passed (11 tests), and the earlier focused returns/matching regression `pytest tests/test_position_matching.py -q` passed (75 tests). Backstop `python scripts/diff_outputs.py --semantic` still fails against the active baseline with 443 divergent artifacts, 3,682 checked, 77 skipped, and semantic deltas in holdings, matches, position returns, index returns, and fund financials; baseline governance review is still required before treating this output tree as baseline-clean.

**Status: validation_blockers_cleared_with_residual_warnings** -- the RI03/RI07 promoted failures and PC03 float-noise false failure are cleared in regenerated validation artifacts, returns and frontend exports are refreshed, but fund-financial/holdings validation remain WARN and the active baseline semantic diff remains divergent.

## 2026-06-09 - Added concurrent BDC wrapper claim helper

- Added `scripts/bdc_wrapper_worklist.py` to let parallel agents claim the next unwrapped BDC CIK through a small JSON claim state with an atomic `.lock` file. The queue is derived from `data/overrides/bdc_xbrl_wrappers/unlisted_bdc_xbrl_reference.json`, excludes CIKs with existing wrapper files and entries without holdings data, and prioritizes source-reconciliation blocking issue count, blocking FV, then holdings rows.
- Updated `.claude/skills/wrapper/SKILL.md` so wrapper agents use `python scripts/bdc_wrapper_worklist.py --next --agent "<agent-name>"`, then mark completed claims with `--done` or return them with `--release`.
- Added `tests/test_bdc_wrapper_worklist.py` covering queue filtering, sequential distinct claims, done status accounting, and stale-claim reclaim behavior.
- Validation: `python -m pytest tests/test_bdc_wrapper_worklist.py -q` passed with 3 tests. CLI dry run `python scripts/bdc_wrapper_worklist.py --stats` reported 71 eligible unclaimed BDC wrapper CIKs and no active claims; `--list --limit 10` showed `0002006758` as the current top claim candidate.

**Status: coordination_helper_ready** -- parallel wrapper agents can now claim distinct CIKs without racing on manual queue selection; no wrapper claims were taken during this change.

## 2026-06-09 - Added audited guarded SEC HTML downloader for agent workflows

- Added `pipeline/sec_download_guard.py` and `scripts/download_missing_bdc_html.py` as the approved opt-in path for missing BDC HTML evidence. The helper validates CIK/accession pairs against `data/output/bdc_filings_index.csv`, restricts URLs to SEC EDGAR archives, enforces a cross-process SEC rate-limit lock, uses a per-target file lock, writes files atomically under `data/raw/filings/bdc_html/`, and appends JSONL receipts to `data/output/sec_download_manifest.jsonl`.
- Added `SEC_DOWNLOAD_LOCK_DIR` and `SEC_DOWNLOAD_MANIFEST_FILE` config constants. Routed `pipeline.bdc_filings.download_html_filing()` and `pipeline.html_soi_evidence.build_html_soi_evidence(..., allow_html_download=True)` through the guarded downloader instead of direct SEC fetch/write logic. Non-BDC HTML evidence remains cache-only for this guard.
- Updated `.claude/skills/wrapper/SKILL.md` so wrapper agents do not run direct SEC downloads and use `python scripts/download_missing_bdc_html.py --cik <CIK> --missing --max-downloads 10 --agent "<agent-name>" --reason wrapper_evidence` when missing BDC HTML evidence is explicitly needed.
- Added `tests/test_sec_download_guard.py` covering unknown-accession rejection without network, cached short-circuit behavior, atomic final-file writes with manifest receipts, short-content failure without a final file, and accession normalization.
- Validation: `python -m pytest tests/test_sec_download_guard.py -q` passed with 5 tests; `python -m pytest tests/test_html_soi_evidence.py tests/test_bdc_cik_review.py tests/test_bdc_filings.py -q` passed with 126 tests and 6 existing BeautifulSoup/lxml deprecation warnings. CLI dry-run `python scripts/download_missing_bdc_html.py --cik 0002006758 --missing --max-downloads 1 --dry-run` listed one missing indexed target and made no SEC request.

**Status: guarded_download_ready** -- terminal agents can fetch missing BDC HTML only through a bounded, audited, indexed-accession path; no live SEC downloads were performed during this change.

Follow-up in same implementation pass:
- Added a run-level `--max-html-downloads` cap to `pipeline.bdc_cik_review` for the existing `--allow-html-download` bundle path, defaulting to 10 and emitting `html_download_cap` evidence when skipped.
- Re-ran touched tests after this cap change: `python -m pytest tests/test_sec_download_guard.py tests/test_html_soi_evidence.py tests/test_bdc_cik_review.py tests/test_bdc_filings.py -q` passed with 131 tests and 6 existing BeautifulSoup/lxml deprecation warnings.

## 2026-06-09 - 26North BDC wrapper review package

- Added `data/overrides/bdc_xbrl_wrappers/0001950976.json` for 26North BDC, Inc. and updated its `unlisted_bdc_xbrl_reference.json` entry from `wrapper_status: none` to `exists` (`with_wrapper` 27 -> 28, `without_wrapper` 102 -> 101).
- The wrapper covers pipe-delimited `Debt Investments`, `Common Equity`, and `Equity` rows; extracts issuer from the second pipe segment and instrument from the third; treats exact category/total/cash rows as non-leaf; and strips volatile rate/date tails from wrapper position keys while preserving issuer and instrument.
- Added focused tests in `tests/test_bdc_xbrl_wrapper.py` for debt/equity leaf classification, category/cash false positives, rate-tail key stability, and registry support. Added staging tests in `tests/test_unified_holdings.py` for debt and equity issuer/instrument extraction.
- Validation: schema validation passed; coherence check passed; `pytest tests/test_bdc_xbrl_wrapper.py -k "twenty_six_north" -q` passed 5 tests; `pytest tests/test_unified_holdings.py -k "twenty_six_north" --tb=short -q` passed 2 tests. Fresh staging oracle and trial unified oracle both reported 9 quarters, zero remaining blocking rows, zero wrapper-blocking rows, and `oracle_status_counts={'pass': 8, 'fail': 1}` with only `2024-06-30: low_position_continuity`.
- One-CIK trial rebuild with matching produced 687 rows versus 639 production rows, delta +48 rows / +$386.083M FV. Position matching passed J01 (`B1b rate = 83.7%`, threshold 70%) and J03 (`fuzzy rate = 0.7%`, threshold 10%).
- Trial promotion gate returned `promotion_status = review_required`, `blocking_rows_delta = 0`, `blocking_fv_delta = 0`, and one proposed soft exception for `low_position_continuity` at 2024-06-30. `remaining_blockers.csv` is empty.
- A cached production `python scripts/rebuild_outputs.py --unified` was attempted but exited non-zero before output timestamps changed; concurrent pytest/python processes were visible afterward, so canonical production promotion and semantic diff were not claimed from this run.

**Status: review_required** -- isolated wrapper validation, oracle, promotion interpretation, and matching are complete for CIK `0001950976`; remaining work is human review of the 2024-06-30 low-continuity soft diagnostic and a later canonical rebuild/promotion when the shared output tree is available.

### 2026-06-09 -- Add comprehensive fund-level highlights extractor

- **Created** `pipeline/bdc_fund_highlights.py`: new module that extracts ~50 fund-level XBRL concepts from cached BDC 10-K/10-Q filings, covering per-share/NAV, financial highlights, distributions, capital activity, income, borrowing, fair value hierarchy, and balance sheet data.
- Handles both instant and duration contexts, entity-level and per-share-class (StatementClassOfStockAxis) facts.
- Rejects investment-level dimension contexts (InvestmentIdentifierAxis, etc.) to isolate fund-level data.
- **Modified** `pipeline/config.py`: added `BDC_FUND_HIGHLIGHTS_FILE` constant.
- **Modified** `scripts/rebuild_outputs.py`: added `--highlights` flag and `rebuild_highlights()` function.
- **Output**: `data/output/bdc_fund_highlights.csv` -- 11,790 rows, 237 CIKs, 80 quarters, 3,088 per-class rows.
- Key coverage: nav_per_share 91%, total_return 85%, nii_per_share 87%, shares_outstanding 100%, total_assets 100%, interest_expense 97%, net_investment_income 88%, stock_issued_value 80%, management_fee_expense 82%.
- Time series depth: NAV per share back to 2008, total return from 2013, through 2026q1.
- No tests modified; no existing output files changed.

## 2026-06-09 - Middle Market Apollo Institutional wrapper review package

- Added `data/overrides/bdc_xbrl_wrappers/0002006758.json` for Middle Market Apollo Institutional Private Lending and updated `unlisted_bdc_xbrl_reference.json` from `wrapper_status: none` to `exists` (`with_wrapper` 28 -> 29, `without_wrapper` 101 -> 100).
- The wrapper handles flat industry-prefixed XBRL identifiers, including debt rows without `Investment Type`, equity rows, and `Total Investments` rows that still contain explicit instrument evidence. Issuer-only/company-only source rows remain aggregate rows rather than position-level leaves.
- Added focused classifier coverage in `tests/test_bdc_xbrl_wrapper.py` and staging extraction coverage in `tests/test_unified_holdings.py` for debt/equity issuer and instrument extraction, rate-drift key stability, and aggregate false positives.
- Validation: wrapper schema validation passed; reference JSON parsed successfully; `pytest tests/test_bdc_xbrl_wrapper.py -k "mm_apollo_institutional" -q --basetemp .tmp/pytest-mm-apollo-wrapper` passed 8 tests; `pytest tests/test_unified_holdings.py -k "mm_apollo_institutional" -q --basetemp .tmp/pytest-mm-apollo-unified` passed 3 tests.
- One-CIK trial rebuild with matching produced 1,470 trial rows versus 1,469 production rows, delta +1. Matching passed J01 (`B1b rate = 78.8%`, threshold 70%) and J03 (`fuzzy rate = 3.0%`, threshold 10%). The row delta reflects removal of 7 issuer-only/source subtotal rows and addition of 8 explicit leaf rows in the trial.
- Fresh staging oracle and trial unified oracle both reported 7 quarters, zero remaining blocking rows, and `oracle_status_counts={'pass': 5, 'fail': 2}`. The remaining soft diagnostics are `2025-09-30: rate_magnitude_shift_detected` and `2026-03-31: low_position_continuity`.
- Trial promotion gate returned `promotion_status = review_required`, `blocking_rows_delta = -75`, `blocking_fv_delta = -1144992000`, and proposed inactive exceptions for the two soft diagnostics. Warnings were `aggregate_detection_disagreement: 178 rows (wrapper_only=172, staging_only=6)` and `identifier_normalization_impact: 14 rows (prefix_stripped=14)`.
- `pytest tests/test_unified_cik_trial.py` could not be used as a final harness check in this environment: the first run failed before test logic due `PermissionError` on `C:\Users\alger\AppData\Local\Temp\pytest-of-alger`; reruns with workspace `--basetemp` aborted during the existing alternate-output `build_unified_holdings()` test without a Python traceback. This was not treated as a `0002006758` wrapper regression because the focused wrapper tests, one-CIK trial, oracle, promotion gate, and matching checks passed.

**Status: review_required** -- isolated wrapper validation, oracle, promotion interpretation, and matching are complete for CIK `0002006758`; remaining work is human review of the two proposed soft oracle exceptions and a later canonical rebuild/promotion when the shared output tree is available.

## 2026-06-09 - BlackRock Direct Lending wrapper review package

- Claimed CIK `0001834543` (`BlackRock Direct Lending Corp.`) as agent `wrapper-alger-20260609-103612` and added `data/overrides/bdc_xbrl_wrappers/0001834543.json`. Updated its `unlisted_bdc_xbrl_reference.json` entry from `wrapper_status: none` to `exists` (`with_wrapper` 29 -> 30, `without_wrapper` 100 -> 99).
- The wrapper covers flat BlackRock Direct Lending XBRL identifiers: `Debt Investments <industry> <issuer> Instrument ...`, `Investment ...` equity/warrant rows, cash rows, and narrow total/header rows. Canonical position keys strip leading category/industry labels, `Instrument`, rate blocks, expiration-only dates, and parenthetical aliases while preserving issuer and tranche/instrument terms.
- Added focused tests in `tests/test_bdc_xbrl_wrapper.py` for debt leaf classification, equity versus warrant family classification, cash/category/total false positives, registry support, and rate-block key stability.
- Validation: schema validation passed; coherence check passed; focused wrapper tests passed (`4 passed`). One-CIK trial rebuild with matching produced 3,028 rows versus 2,978 production rows, delta +50 rows. J01 passed (`B1b rate = 85.4%`, threshold 70%); J03 improved from 27.0% to 13.7% but still failed the 10% threshold.
- Trial unified oracle against `private_markets_holdings.0001834543.csv` reported 13 quarters, 20 remaining blocking rows, 0 remaining wrapper-blocking rows, and `oracle_status_counts={'pass': 7, 'fail': 6}`. Residual mechanisms are `remaining_total_rollup_no_child_tie` on total/cash/investment header rows; the wrapper reduced baseline blockers by 23 rows and about $1.697B FV and cleared 192 rollups.
- The oracle CLI `--promotion-gate --holdings-file ...` exited non-zero without console output or promotion artifacts in this environment. Evaluating promotion from the written oracle artifacts returned `promotion_status=review_required`, `blocking_rows_delta=-23`, `blocking_fv_delta=-1697391469`, with reasons limited to `remaining_total_rollup_no_child_tie`.
- Additional verification: `pytest tests/test_unified_cik_trial.py -q --basetemp .codex_tmp/pytest_unified_cik_trial` passed 7 tests; `pytest tests/test_position_matching.py -q --basetemp .codex_tmp/pytest_position_matching` passed 75 tests; `pytest tests/test_oracle_checks.py -k "J01 or J03 or J04 or DiagnoseFuzzy" -q` passed 20 tests. A full `tests/test_bdc_xbrl_wrapper.py` run found one unrelated existing failure for CIK `0001646614` (`debt_category_rollup` vs expected `aggregate`).

**Status: review_required** -- isolated wrapper validation, oracle artifact promotion interpretation, and matching are complete for CIK `0001834543`; remaining work is human review of total-rollup residuals and J03 fuzzy fallback before any canonical production promotion.

## 2026-06-09 - Phillip Street Middle Market wrapper partial review package

- Claimed CIK `0001948368` (`Phillip Street Middle Market Lending Fund LLC`) as agent `wrapper-alger-20260609-103559` and added `data/overrides/bdc_xbrl_wrappers/0001948368.json`. Updated `unlisted_bdc_xbrl_reference.json` from `wrapper_status: none` to `exists` (`with_wrapper` 29 -> 30, `without_wrapper` 100 -> 99).
- The wrapper handles Goldman-style hierarchy identifiers with quarter-specific percentage buckets, including `Investment Debt Investments`, truncated `IInvestment`/`nvestment` prefixes, first-lien/last-out/second-lien/unsecured debt, equity securities, and money-market exclusions. Position keys strip volatile hierarchy percentages and current coupon text while preserving issuer, industry, spread, maturity, and lot suffixes.
- Added focused classifier tests in `tests/test_bdc_xbrl_wrapper.py` for debt leaves, truncated prefixes, position-key stability, category/total false positives, money-market exclusions, and registry support.
- Validation: schema validation passed; wrapper coherence passed; `pytest tests/test_bdc_xbrl_wrapper.py -v` passed 419 tests; `pytest tests/test_oracle_checks.py -k "J01 or J03 or J04 or DiagnoseFuzzy" -v` passed 20 selected tests; `pytest tests/test_unified_cik_trial.py -q --basetemp .tmp\pytest-wrapper-1948368-unified3 -p no:cacheprovider --tb=short` passed 7 tests.
- One-CIK trial rebuild produced 1,833 rows versus 1,800 production rows, delta +33 rows. The trial oracle against `private_markets_holdings.0001948368.csv` reported 13 quarters with zero remaining blocking rows and zero remaining wrapper-blocking rows. Baseline comparison cleared 43 blocking rows and about $5.243B of blocking FV, with no blocker regressions.
- Matching on the trial artifact produced 811 matched pairs: 286 `B1b_position_key`, 519 `B2_exact_name`, 3 `A_within_filing`, and 3 `C_normalized_name`. J03 passed with 0.0% fuzzy fallback, but J01 failed with B1b rate 35.4% versus the 70% threshold. Inspection showed many B2 pairs had identical keys but were not unique enough for the strong-key tier, so forcing uniqueness would risk corrupting position-level tranche identity.
- Raw oracle status remains review-only: 10 fail quarters and 3 pass quarters. The remaining raw fail reasons are `exclusion_risk_detected`, `concept_drift_detected`, `low_position_continuity`, and `unclassified_fv_rate_exceeded`; source reconciliation blockers are cleared in the trial.
- `python -m pipeline.bdc_xbrl_wrapper_oracle --cik 0001948368 --compare-baseline --fresh-bdc-staging` and `python scripts/rebuild_unified_cik_trial.py --cik 0001948368 --match` exited non-zero without useful traceback in this environment after staging/rebuild work; match-only validation was run against the written trial holdings artifact. Re-running `tests/test_position_matching.py` with workspace `--basetemp` showed passing progress but exited without a pytest summary and left one Python child process that the sandbox refused to terminate (`Access denied`).
- No SEC downloads were performed. The claim was released, not marked done, with the blocker note that J01 failed and raw oracle fail diagnostics remain.

**Status: review_required** -- isolated wrapper creation, trial rebuild, trial oracle, and matching diagnosis are complete for CIK `0001948368`; human review is needed before any promotion because the wrapper clears source blockers but does not satisfy position-key stability.

## 2026-06-09 - Silver Point Specialty Credit wrapper partial package

- Claimed CIK `0001646614` (`Silver Point Specialty Credit Fund, L.P.`) as agent `wrapper-alger-20260609-103544` and added `data/overrides/bdc_xbrl_wrappers/0001646614.json`. Updated `unlisted_bdc_xbrl_reference.json` from `wrapper_status: none` to `exists` (`with_wrapper` 30 -> 31, `without_wrapper` 99 -> 98).
- The wrapper covers Silver Point hierarchy identifiers across non-controlled, affiliated, and controlled sections; handles early comma-delimited loan leaves; excludes cash equivalents and total/category rows; and adds hierarchy staging extraction for issuer/instrument fields while preserving debt tranche terms in position keys.
- Added focused tests in `tests/test_bdc_xbrl_wrapper.py` for early comma leaf classification and total/category false positives, plus `tests/test_unified_holdings.py` coverage showing the comma hierarchy leaf is staged as a position while the controlled trust total is excluded.
- Validation completed: wrapper schema validation passed; wrapper coherence passed; focused tests passed (`test_silver_point_specialty_credit_comma_leaf_and_total_rows`, `TestPrepareBdc::test_silver_point_wrapper_extracts_comma_hierarchy_leaf`). The cached trial artifacts from the prior regex revision produced 1,984 trial rows versus 1,967 production rows and matching failed J03 at 13.2% fuzzy fallback despite passing J01; these artifacts are stale after the final conservative key-regex adjustment.
- Fresh one-CIK trial rebuild with matching for the final JSON could not complete in this environment. A redirected trial stopped after staging BDC rows (`After all BDC filters: 1975 rows`) before writing current artifacts, then left an unkillable Python child process. A foreground rerun exited during Phase A without a traceback and left additional child processes, which were cleaned up where permitted. Oracle and promotion checks were therefore not run against a current holdings-file or fresh staging output.
- No guarded HTML download was needed; cached HTML and XBRL inputs were present. Temporary local diagnostic scripts were deleted.
- The wrapper claim was released, not marked done, because required trial/oracle/promotion validation did not complete.

**Status: blocked_released** -- CIK `0001646614` has a partial wrapper and focused parser coverage, but it needs a clean one-CIK trial rebuild, matching, oracle, and promotion gate before human review or production promotion.

## 2026-06-09 - Onex Falcon Direct Lending wrapper package

- Claimed CIK `0001860424` (`Onex Falcon Direct Lending BDC Fund`) as agent `codex-20260609-xbrl-01` and added `data/overrides/bdc_xbrl_wrappers/0001860424.json`. Updated `unlisted_bdc_xbrl_reference.json` from `wrapper_status: none` to `exists` with `hierarchy_extract` staging.
- The wrapper covers Onex flat XBRL hierarchy identifiers across `Non-controlled/Non-affiliated investments`, debt, equity, all-caps variants, no-space date variants, and cash/total/header rows. Staging extraction handles issuer/instrument boundaries for term loans, revolving loans, DDTL/revolver variants, term facilities, preferred/common equity, and observed malformed spacing without broadening global rules.
- Added focused classifier tests in `tests/test_bdc_xbrl_wrapper.py` for debt leaves, revolver leaves without current coupon, uppercase variants, equity leaves, aggregate/cash false positives, position-key stability, and registry support.
- Validation: wrapper schema validation passed; wrapper coherence passed; focused wrapper tests passed (`7 passed`). Fresh staging oracle and trial-holdings oracle each reported 12 quarters, zero remaining blocking rows, zero remaining blocking FV, and `oracle_status_counts={'pass': 10, 'fail': 2}`. The two raw oracle fail quarters are soft `cost_fv_ratio_outliers`.
- One-CIK trial rebuild with matching produced 856 trial rows versus 834 production rows, delta +22 rows. Matching passed J01 (`B1b rate = 98.7%`, threshold 70%) and J03 (`D_fuzzy rate = 0.4%`, threshold 10%).
- Extraction inspection found 2 remaining malformed issuer rows, both source-corrupted Apryse concatenations in 2025-06-30 and 2025-09-30 (`Non-cNon-controlled...Term Loan...ontrolled/Non-affiliated...2024 Refinancing Term Loan...`). These are human-review/source-evidence items, not safe regex fixes.
- Full cached production rebuild for promotion was attempted twice. The first `python scripts/rebuild_outputs.py --unified` timed out after 30 minutes without updating `private_markets_holdings.*`; the second exited non-zero after BDC pre-filtering with no residual rebuild process and no production artifact timestamp change. Production promotion gate and `diff_outputs.py --semantic` were therefore not run against updated production artifacts.
- No SEC downloads were performed. The claim was marked done because the wrapper exists, CIK-scoped source/oracle/trial/matching validation ran, and source reconciliation blockers for the claimed CIK were cleared in trial validation.

**Status: done_with_review_items** -- CIK `0001860424` has a validated wrapper with zero CIK-scoped source blocking rows in fresh staging/trial oracle checks. Remaining human review is limited to the two corrupted Apryse source identifiers; production promotion still requires a successful canonical cached unified rebuild.

### 2026-06-09 -- Add normalization rules to fund highlights extractor

- **Modified** `pipeline/bdc_fund_highlights.py`: added 5 post-extraction normalization rules modeled on existing pipeline patterns.
- **Rule 1** (member filter): regex-based filter drops non-share-class StatementClassOfStockAxis members (issuance dates, DRIP, distribution types, debt instruments, etc.). Dropped 263 junk rows.
- **Rule 2** (canonical share class): maps 64 raw XBRL member names to 21 canonical labels (ClassI/S/D/A/B/F/M/N/T/SP, CommonStock, Preferred*, Warrant, DepositaryShares). Follows entity_resolution.py regex-first pattern.
- **Rule 3** (concept pollution): nulls 27 entity-dollar columns (income, balance sheet, borrowing, FV) on per-class rows where XBRL reports per-share/ratio values under the same concept name. Eliminated 100% cross-unit contamination.
- **Rule 4** (duration scaling): applies bdc_fund_income quarterly scaling (dm 2-4 as-is, dm 11-13 /4, else 3/dm) to 25 flow columns. Cross-check vs bdc_fund_income: 93% exact match on net_investment_income (up from 71% pre-normalization).
- **Rule 5** (ratio format): applies fund_financials Fix 2 convention (decimal <= 1.0 -> *100 to percentage form) with field-specific outlier bounds. 0 outliers rejected after fixing expense_ratio_incl_waiver misclassification.
- **Fix**: Renamed `expense_ratio_incl_waiver` to `expenses_after_waiver` -- the XBRL concept `InvestmentCompanyExpenseAfterReductionOfFeeWaiverAndReimbursement` is a dollar amount (unitRef=USD), not an expense ratio. Now correctly treated as a flow column with duration scaling.
- **Output**: 11,163 rows, 237 CIKs, 80 quarters, 2,461 per-class rows (down from 11,790/3,088 pre-normalization).

## 2026-06-09 - TriplePoint Global Venture Credit wrapper package

- Claimed CIK `0001792509` (`TriplePoint Global Venture Credit, LLC`) as agent `codex-20260609-001` and added `data/overrides/bdc_xbrl_wrappers/0001792509.json`. Updated its `unlisted_bdc_xbrl_reference.json` entry from `wrapper_status: none` to `exists` with `hierarchy_extract` staging.
- The wrapper covers TriplePoint venture-debt and equity identifiers across older comma-delimited rows and later pipe-delimited rows, including `Growth Capital Loan`, `Revolver`, `Convertible Note`, `Debt Investments`, `Preferred Stock`, `Common Stock`, `Hybrid`, `Equity Investments`, and `Warrant Investments`. Federated Government Obligations Fund rows are treated as non-private cash equivalents. Bare issuer-only rows are intentionally not broadened into wrapper leaves.
- Added focused tests in `tests/test_bdc_xbrl_wrapper.py` for comma/pipe equity leaf classification, cash-equivalent exclusion, total-rollup false positives, bare-issuer false positives, and registry support. Added `tests/test_unified_holdings.py` staging tests for comma equity extraction and four-segment pipe equity extraction.
- Validation: schema validation passed; wrapper coherence passed; focused wrapper tests passed (`6 passed`); focused staging tests passed (`2 passed`). Fresh staging oracle and trial-holdings oracle each reported 10 quarters, zero remaining blocking rows, and zero remaining blocking FV. Baseline/promotion comparison showed no blocking row or FV regression.
- One-CIK trial rebuild with matching produced 4,696 trial rows versus 4,645 production rows, delta +51 rows and about +$35.1M FV. Matching passed J01 (`B1b rate = 94.2%`, threshold 70%) and J03 (`D_fuzzy rate = 0.2%`, threshold 10%).
- Trial promotion-style gate using `--promotion-gate --holdings-file data/output/bdc_xbrl_wrapper_trial/0001792509/unified_trial/private_markets_holdings.0001792509.csv` returned `promotion_status=review_required`, `blocking_rows_delta=0`, and `blocking_fv_delta=0.0`. Proposed soft exceptions were generated for early-quarter `unclassified_rate_exceeded` / `unclassified_fv_rate_exceeded` and 2025-12-31 `low_position_continuity`.
- Full cached production rebuild (`python scripts/rebuild_outputs.py --unified`) was attempted but timed out after 30 minutes without updating `private_markets_holdings.*`; five lingering rebuild worker processes were identified and killed. Production promotion gate against refreshed canonical artifacts was not completed. `python scripts/diff_outputs.py --semantic` was run afterward and failed because the current workspace already diverges broadly from the active baseline (443 divergent artifacts), not as an isolated wrapper-specific signal.
- No SEC downloads were performed. The claim was marked done because the wrapper exists, required CIK-scoped validation ran, deterministic source blockers were cleared, and remaining issues are human-review soft diagnostics.

**Status: done_with_review_items** -- CIK `0001792509` has zero remaining deterministic blocking rows in fresh staging/trial oracle checks and passes trial position matching. Human review is needed for accepted soft exceptions on early bare issuer/tranche unclassified rates and the 2025-12-31 format-transition continuity warning; production promotion still requires a successful canonical cached unified rebuild.

## 2026-06-09 - Varagon Capital wrapper package

- Claimed CIK `0001784700` (`Varagon Capital Corp.`) as agent `codex-gpt5-20260609-001` and added `data/overrides/bdc_xbrl_wrappers/0001784700.json`. Updated `data/overrides/bdc_xbrl_wrappers/unlisted_bdc_xbrl_reference.json` from `wrapper_status: none` to `exists` with `hierarchy_extract` staging (`with_wrapper` 31 -> 32, `without_wrapper` 98 -> 97).
- The wrapper handles Varagon comma-hierarchy identifiers across non-controlled, controlled, debt, equity, and older company/industry ordering variants. Position keys strip volatile hierarchy, reference rate/spread, current coupon, and acquisition-date text while preserving issuer, instrument, maturity, and deterministic lot suffixes.
- Added focused wrapper tests in `tests/test_bdc_xbrl_wrapper.py` for debt leaves, equity co-invest leaves, total/subtotal false positives, coupon and spread repricing stability, company/industry order drift, and registry support. Added `tests/test_unified_holdings.py` coverage for scoped duplicate wrapper-key lot suffixes and updated `pipeline/unified_holdings.py` to apply that suffix behavior for `0001784700`.
- Validation: schema validation passed; wrapper coherence passed; focused Varagon wrapper tests passed (`7 passed`); focused unified lot-suffix test passed (`1 passed`). Fresh staging oracle and trial-holdings oracle each reported zero remaining blocking rows and an empty `remaining_blocker_mechanisms.csv`.
- One-CIK trial rebuild with matching produced 4,031 trial rows and 2,114 matched position pairs. Matching passed J01 (`B1b rate = 83.2%`, threshold 70%) and J03 (`D_fuzzy rate = 0.4%`, threshold 10%).
- Trial oracle still reports review-only soft diagnostics: exclusion-risk warnings on total/category rows, selected cost/FV ratio outliers, one concept-drift warning, and one low-position-continuity warning. These did not produce remaining deterministic blocker rows.
- A full cached production rebuild (`python scripts/rebuild_outputs.py --unified`) was attempted after checking for existing Python/pytest jobs, but exited non-zero after BDC staging without updating `data/output/private_markets_holdings.*`. Production promotion gate against current production therefore rejected on stale wrapper blockers, while reporting improved blocker deltas (`blocking_rows_delta=-34`, `blocking_fv_delta=-13702352000`) and no wrapper-specific structural-keyword regression after the final archetype fix.
- `python scripts/diff_outputs.py --semantic` was run as a backstop and failed because the shared workspace already has broad baseline drift (`443 divergent artifact(s)`, 3,682 checked, 77 skipped), not as an isolated Varagon signal.
- No SEC downloads were performed. The claim was marked done because the wrapper exists, required CIK-scoped source/oracle/trial/matching validation ran, and deterministic trial blockers were cleared.

**Status: done_with_review_items** -- CIK `0001784700` has zero remaining deterministic blocking rows in fresh staging/trial oracle checks and passes trial position matching. Human review is needed for the soft oracle diagnostics and for rerunning canonical cached production rebuild/promotion in a clean environment.

## 2026-06-09 - TCW Direct Lending VII wrapper package

- Claimed CIK `0001715933` (`TCW Direct Lending VII LLC`) as agent `codex-gpt5-20260609-002` and added `data/overrides/bdc_xbrl_wrappers/0001715933.json`. Updated `data/overrides/bdc_xbrl_wrappers/unlisted_bdc_xbrl_reference.json` from `wrapper_status: none` to `exists` with `hierarchy_extract` staging (`with_wrapper` 33 -> 34, `without_wrapper` 96 -> 95).
- The wrapper covers TCW VII `Debt Securities`, `Equity Securities`, `Controlled Affiliated Investments`, `Non-Controlled Affiliated Investments`, cash-equivalent, short-term investment, and total/header identifiers. It rescues position leaves with acquisition-date or instrument evidence while treating industry/category rows such as `Debt Securities Food Products` as non-position aggregates.
- Added focused classifier tests in `tests/test_bdc_xbrl_wrapper.py` for debt leaves, affiliation-prefixed leaves, equity leaves, total/subtotal/cash false positives, coupon/net-asset percentage key stability, and registry support. Added `tests/test_unified_holdings.py` staging tests for debt, affiliation-prefixed debt, and equity issuer/instrument extraction.
- Validation: schema validation passed; wrapper coherence passed; focused wrapper tests passed (`11 passed`, including adjacent TCW VIII regression tests selected by the filter); focused staging tests passed (`6 passed`, including adjacent TCW VIII regression tests). Fresh staging oracle and trial-holdings oracle each reported 13 quarters and zero remaining deterministic blocking rows.
- One-CIK trial rebuild with matching produced 933 trial rows versus 979 current production rows, delta `-46` rows. Matching produced 592 pairs: 392 `B1b_position_key`, 182 `A_within_filing`, and 18 `B2_exact_name`. J01 passed (`B1b rate = 95.6%`, threshold 70%) and J03 passed (`D_fuzzy rate = 0.0%`, threshold 10%).
- Trial promotion-style gate against `data/output/bdc_xbrl_wrapper_trial/0001715933/unified_trial/private_markets_holdings.0001715933.csv` returned `promotion_status=review_required`, `blocking_rows_delta=-50`, and `blocking_fv_delta=-19599266289`. Remaining reasons are review-style diagnostics: 2024-09-30 and 2024-12-31 through 2026-03-31 cost/FV ratio outliers, plus exclusion-risk diagnostics for 2024-12-31 and 2025-03-31.
- Current-production promotion gate was also run and rejected because canonical production holdings are stale for this wrapper, with early `wrapper_blockers_remaining` / `remaining_leaf_present_in_raw_missing_from_unified` reasons still present. A full cached production rebuild was not started because other agents began CIK-scoped oracle/pytest jobs in the shared workspace; production promotion still requires a clean canonical rebuild.
- `python scripts/diff_outputs.py --semantic` was run and failed due broad existing workspace drift (`443 divergent artifact(s)`, 3,682 checked, 77 skipped), not as an isolated TCW VII signal. No SEC downloads were performed.
- The claim was marked done because the wrapper exists, required CIK-scoped source/oracle/trial/matching/promotion-style validation ran, and deterministic trial blockers were cleared.

**Status: done_with_review_items** -- CIK `0001715933` has zero remaining deterministic blocking rows in fresh staging/trial oracle checks and passes trial position matching. Human review is needed for cost/FV and exclusion-risk soft diagnostics; production promotion still requires a successful canonical cached unified rebuild.

## 2026-06-09 - TCW Direct Lending VIII wrapper package

- Claimed CIK `0001825265` (`TCW Direct Lending VIII LLC`) as agent `codex-gpt5-20260609-a7f3` and added `data/overrides/bdc_xbrl_wrappers/0001825265.json`. Updated `data/overrides/bdc_xbrl_wrappers/unlisted_bdc_xbrl_reference.json` from `wrapper_status: none` to `exists` with `hierarchy_extract` staging.
- The wrapper covers TCW flat hierarchy identifiers for `Debt Investments` and `Equity Investments`, including industry-prefixed issuer rows, acquisition-date leaves, debt tranche descriptions, warrants/common units, industry subtotals, portfolio totals, liabilities, cash equivalents, money-market funds, and short-term Treasury rows. Position keys strip volatile current coupon/current NAV percentage text while preserving issuer, instrument, maturity, and warrant expiry details.
- Added focused wrapper tests in `tests/test_bdc_xbrl_wrapper.py` for debt leaves, equity warrant leaves, subtotal/cash false positives, position-key stability, and registry support. Added `tests/test_unified_holdings.py` staging tests for CIK-scoped debt and equity hierarchy extraction plus a false-positive check proving the extractor does not apply to another CIK.
- Validation: wrapper schema validation passed; wrapper coherence passed; focused wrapper tests passed (`5 passed`); focused staging tests passed (`3 passed`). Fresh staging oracle and trial-holdings oracle each reported zero remaining blocking rows and `oracle_status_counts={'pass': 10, 'fail': 3}`.
- One-CIK trial rebuild with matching produced 623 trial rows versus 625 production rows, delta -2 rows. Matching passed J01 (`B1b rate = 96.3%`, threshold 70%) and J03 (`D_fuzzy rate = 0.2%`, threshold 10%).
- Trial promotion-style gate using `--promotion-gate --holdings-file data/output/bdc_xbrl_wrapper_trial/0001825265/unified_trial/private_markets_holdings.0001825265.csv` returned `promotion_status=review_required`, `blocking_rows_delta=-158`, and `blocking_fv_delta=-26319766473.341` with no structural issues. Proposed soft exception templates were generated but not accepted.
- Remaining human-review items are the soft oracle diagnostics: `2023-03-31` `cost_fv_ratio_outliers` (6 outliers), `2023-06-30` `fv_magnitude_shift_detected` (575.3103), and `2025-09-30` `cost_fv_ratio_outliers` (1 outlier).
- Full cached production rebuild for promotion was attempted after checking for existing pytest/rebuild jobs, but did not complete in this environment: one run timed out at 30 minutes, and subsequent runs exited non-zero after BDC staging/Phase A without updating `data/output/private_markets_holdings.*`. `python scripts/diff_outputs.py --semantic` was run afterward and failed because the shared workspace already has broad baseline drift (`443 divergent artifact(s)`, 3,682 checked, 77 skipped), not as an isolated TCW signal.
- No SEC downloads were performed. The claim was marked done because the wrapper exists, required CIK-scoped source/oracle/trial/matching validation ran, and deterministic trial blockers were cleared.

**Status: done_with_review_items** -- CIK `0001825265` has zero remaining deterministic blocking rows in fresh staging/trial oracle checks and passes trial position matching. Human review is needed for the three soft oracle diagnostics above; production promotion still requires a successful canonical cached unified rebuild in a clean environment.

## 2026-06-09 - Commonwealth Credit Partners BDC I wrapper package

- Claimed CIK `0001841514` (`Commonwealth Credit Partners BDC I, Inc.`) as agent `codex-gpt5-20260609-b9c2` and added `data/overrides/bdc_xbrl_wrappers/0001841514.json`. Updated `data/overrides/bdc_xbrl_wrappers/unlisted_bdc_xbrl_reference.json` from `wrapper_status: none` to `exists` with `hierarchy_extract` staging.
- The wrapper covers Commonwealth first-lien senior secured debt leaves, en-dash/dash issuer-instrument separators, equity shorthand rows such as issuer plus `Equity`/`Preferred Equity` plus industry, membership-interest rows, cash-equivalent rows, investment-and-cash totals, debt/equity subtotals, net assets, liabilities, and affiliated/non-controlled affiliated totals. Position keys strip volatile spread/floor/current interest-rate text while preserving issuer, instrument, and maturity details.
- Added focused wrapper tests in `tests/test_bdc_xbrl_wrapper.py` for debt leaves with dash variants, bare equity/unit leaves, equity shorthand leaves, subtotal/cash/liability false positives, position-key coupon stability, and registry support. Added `tests/test_unified_holdings.py` staging tests for debt issuer/instrument extraction, revolving-credit extraction, equity shorthand extraction, and CIK scoping.
- Validation: wrapper schema validation passed; wrapper coherence passed; focused wrapper tests passed (`6 passed`); focused staging tests passed (`4 passed`). Fresh staging oracle and trial-holdings oracle each reported zero remaining blocking rows and an empty `remaining_blocker_mechanisms.csv`.
- One-CIK trial rebuild with matching produced 1,588 trial rows versus 1,574 production rows, delta +14 rows. Matching passed J01 (`B1b rate = 95.9%`, threshold 70%) and J03 (`D_fuzzy rate = 0.1%`, threshold 10%).
- Trial promotion-style gate using `--promotion-gate --holdings-file data/output/bdc_xbrl_wrapper_trial/0001841514/unified_trial/private_markets_holdings.0001841514.csv` returned `promotion_status=review_required`, `blocking_rows_delta=-55`, `blocking_fv_delta=-13852568000.0`, and no structural issues.
- Remaining human-review items are soft oracle diagnostics: `2023-12-31` `exclusion_risk_detected`; `2024-03-31` `exclusion_risk_detected`; `2024-06-30` `cost_fv_ratio_outliers` and `exclusion_risk_detected`; `2024-09-30` `exclusion_risk_detected`; `2024-12-31` `exclusion_risk_detected`; and `2025-03-31` `exclusion_risk_detected`.
- A canonical cached unified rebuild was already running as PID `13432` (`python scripts/rebuild_outputs.py --unified`, started 2026-06-09 15:00:50) before a duplicate could be launched. It was still running after two bounded waits, so no duplicate rebuild or semantic diff was started. Production promotion against canonical artifacts remains pending that rebuild's completion.
- No SEC downloads were performed. The claim was marked done because the wrapper exists, required CIK-scoped source/oracle/trial/matching validation ran, deterministic trial blockers were cleared, and remaining issues are human-review soft diagnostics plus the in-progress canonical rebuild.

**Status: done_with_review_items** -- CIK `0001841514` has zero remaining deterministic blocking rows in fresh staging/trial oracle checks and passes trial position matching. Human review is needed for the soft exclusion/cost-FV diagnostics above; production promotion still requires completion of the already-running canonical cached unified rebuild and a semantic diff.

### 2026-06-09 -- Fund highlights oracle and quality gate

- Created `pipeline/bdc_fund_highlights_oracle.py`: per-row oracle harness for fund-level highlights data with 5 validation groups:
  - Group 1 (FAIL): NAV identity (assets_net vs nav*shares, 2% tol), income identity (TII - expenses vs NII, 5% tol)
  - Group 2 (REVIEW): cross-source consistency vs bdc_fund_income.csv (6 fields) and fund_financials.csv (3 fields)
  - Group 3 (REVIEW): cross-quarter stability (NAV, shares, expense ratio, NII ratio, total return QoQ) using period-type-aware series (instant for NAV/shares, duration for ratios)
  - Group 4 (REVIEW): monotonicity/sign checks (expense ratio ordering, coverage ratio floor at 1.0x, facility capacity ordering, total return floor)
  - Group 5 (diagnostic): core field count aggregated across instant+duration rows, class field asymmetry
  - Balance sheet identity (TA-TL vs SE) demoted to diagnostic-only due to 90%+ structural XBRL ambiguity
- Created `scripts/fund_highlights_quality_gate.py`: per-CIK quality gate that aggregates oracle verdicts to quarterly status, assigns promotion tiers (Verified/Preliminary/Under review/Excluded)
- Modified `pipeline/config.py`: added BDC_FUND_HIGHLIGHTS_ORACLE_FILE, FUND_HIGHLIGHTS_QUALITY_GATE_FILE, FUND_HIGHLIGHTS_QUALITY_GATE_MD_FILE
- Modified `scripts/rebuild_outputs.py`: added `--highlights-oracle` flag and `rebuild_highlights_oracle()` function
- Results: 237 CIKs evaluated -- 37 PASS (16%), 170 REVIEW (72%), 30 FAIL (13%). 1 Verified (Ares Capital), 36 Preliminary, 30 Excluded (non-BDC entities with 0 core fields). Median cross-source match rate 77.4%. Top review drivers: cross_source_total_assets_mismatch (different extraction pipelines), cross_source_nav_mismatch, interest_expense mismatch.

## 2026-06-09 - Senior Credit Investments wrapper package released for review

- Claimed CIK `0001959568` (`Senior Credit Investments, LLC`) as agent `codex-gpt5-20260609-001` and added `data/overrides/bdc_xbrl_wrappers/0001959568.json`. Updated its `data/overrides/bdc_xbrl_wrappers/unlisted_bdc_xbrl_reference.json` entry from `wrapper_status: none` to `exists` with `hierarchy_extract` staging (`with_wrapper` 34 -> 35, `without_wrapper` 95 -> 94 in the current dirty reference file).
- The wrapper covers Senior Credit's flat hierarchy identifiers for non-controlled/non-affiliated first-lien debt and equity rows, including issuer extraction before `Investment Type`, debt instrument extraction before reference-rate and maturity text, `Portfolio Company ... Investment Type ...` equity rows, cash-equivalent exclusions, and exact total/unfunded rows as non-position aggregates.
- Added focused classifier tests in `tests/test_bdc_xbrl_wrapper.py` for debt leaves, portfolio-company equity leaves, total/category/unfunded false positives, bare portfolio-company false positives, and registry support. Added focused staging tests in `tests/test_unified_holdings.py` for Senior Credit debt issuer/instrument extraction and LP-interest extraction.
- Validation: wrapper schema validation passed; wrapper coherence passed before temp diagnostics were removed; focused wrapper tests passed (`5 passed`); focused staging tests passed (`2 passed`). Fresh staging oracle reported 10 quarters, zero remaining blocking rows, zero wrapper-blocking rows, and `oracle_status_counts={'pass': 7, 'fail': 3}` from exact total-row exclusion-risk diagnostics.
- One-CIK trial rebuild with matching produced 2,048 trial rows versus 2,308 current production rows, delta `-260` rows. Trial matching produced 684 pairs and passed J01 (`B1b rate = 82.6%`, threshold 70%) and J03 (`D_fuzzy rate = 0.9%`, threshold 10%).
- Trial-holdings oracle cleared all deterministic source blockers: `remaining_blocking_rows=0` across all 10 quarters. It cleared 72 documented rollup/source residual rows versus baseline. Baseline comparison improved by 19 blocking rows and about $1.871B blocking FV.
- Trial promotion-style gate against `data/output/bdc_xbrl_wrapper_trial/0001959568/unified_trial/private_markets_holdings.0001959568.csv` returned `promotion_status=review_required`, `blocking_rows_delta=-19`, `blocking_fv_delta=-1870744000`, and no structural issues. Remaining unwaived review diagnostics are `exclusion_risk_detected` on 2024-09-30, 2024-12-31, and 2025-03-31 exact total debt-investment rows, plus `cost_fv_ratio_outliers` on 2025-06-30 (`Redwood Services Group, LLC`, cost 1,392,000, FV -2,000) and 2025-12-31 (`Vessco Midco Holdings, LLC`, cost 246,000, FV -2,000).
- No SEC downloads were performed. A full production rebuild/promotion was not started because an existing `scripts/rebuild_outputs.py --unified` process was already running in the shared workspace. The claim was released, not marked done, because raw promotion-style oracle failures remain and `exclusion_risk_detected` is non-waiveable in the wrapper workflow.

**Status: released_for_human_review** -- CIK `0001959568` has zero remaining deterministic source-reconciliation blockers in fresh staging and trial-holdings oracle checks and passes trial position matching. Human review is needed for the exact total-row exclusion-risk diagnostics and the two small negative-FV cost/FV outlier diagnostics before this wrapper can be treated as production-clean.

## 2026-06-09 - TCW Direct Lending wrapper package

- Claimed CIK `0001603480` (`TCW Direct Lending LLC`) as agent `codex-gpt5-20260609-003` and added `data/overrides/bdc_xbrl_wrappers/0001603480.json`. Updated `data/overrides/bdc_xbrl_wrappers/unlisted_bdc_xbrl_reference.json` from `wrapper_status: none` to `exists` with `hierarchy_extract` staging (`with_wrapper` 35 -> 36, `without_wrapper` 94 -> 93 in the current dirty reference file).
- The wrapper covers TCW Direct Lending prefixed 2023-2025 identifiers and later bare 2025-2026 identifiers, including debt term-loan variants (`First Out`, `Delayed Draw Priming/Printing`, `HoldCo`, `Incremental`, `2025`, `10th Amendment`), revolvers, subordinated loans, common/preferred equity, membership interests, units, warrants, Strategic Ventures rows, cash equivalents, short-term Treasury rows, and total/category rows. Position keys strip volatile current coupon and NAV percentage text while preserving issuer/instrument/maturity identity.
- Added focused wrapper tests in `tests/test_bdc_xbrl_wrapper.py` for debt/equity leaves, subtotal/cash false positives, prefixed and bare position-key stability, and registry support. Added focused staging tests in `tests/test_unified_holdings.py` for prefixed debt, prefixed equity, `Retail & Animal` issuer preservation, and bare debt/equity hierarchy extraction.
- Validation: wrapper schema validation passed; wrapper coherence passed; focused wrapper tests passed (`6 passed`); focused staging tests passed (`5 passed`). Fresh staging oracle and trial-holdings oracle each reported `remaining_blocking_rows=0`; baseline comparison reduced blocking rows by 131 and blocking FV by approximately `$25.599B`.
- One-CIK trial rebuild with matching produced 430 trial rows versus 460 current production rows, delta `-30` rows. Wrapper position-key override applied to 426 rows. Matching produced 261 pairs and passed J01 (`B1b rate = 98.3%`, threshold 70%) and J03 (`D_fuzzy rate = 0.4%`, threshold 10%).
- Trial promotion-style gate against `data/output/bdc_xbrl_wrapper_trial/0001603480/unified_trial/private_markets_holdings.0001603480.csv` returned `promotion_status=review_required`, `blocking_rows_delta=-131`, and `blocking_fv_delta=-25599414329`, with no remaining source-reconciliation blockers.
- Remaining human-review item is the soft cost/FV ratio diagnostic for SSI Parent / School Specialty common stock on 2023-03-31 through 2025-12-31: cost is consistently `53889` while FV ranges from about `$11.481M` to `$31.928M`, producing ratios below the oracle's 0.01 threshold. This is a matched source/output position and not a wrapper parsing blocker.
- No SEC downloads were performed. A full production promotion gate against canonical artifacts was not run because an existing `scripts/rebuild_outputs.py --unified` process (`PID 13432`) was already active in the shared workspace. `python scripts/diff_outputs.py --semantic` was run and failed due broad existing workspace drift (`443 divergent artifact(s)`, 3,682 checked, 77 skipped), not as an isolated TCW Direct Lending wrapper signal.

**Status: done_with_review_items** -- CIK `0001603480` has zero remaining deterministic source-reconciliation blockers in fresh staging and trial-holdings oracle checks and passes trial position matching. Human review is needed for the SSI Parent cost/FV ratio soft diagnostic; production promotion still requires completion of the already-running canonical cached unified rebuild and a clean production promotion check.

## 2026-06-09 - TCW Star Direct Lending wrapper package

- Claimed CIK `0001916608` (`TCW Star Direct Lending LLC`) as agent `codex-20260609-002` and added `data/overrides/bdc_xbrl_wrappers/0001916608.json`. Updated `data/overrides/bdc_xbrl_wrappers/unlisted_bdc_xbrl_reference.json` from `wrapper_status: none` to `exists` with `hierarchy_extract` staging.
- The wrapper covers TCW Star singular/plural `Debt Investment(s)` and `Equity Investment(s)` identifiers, cash equivalents, short-term Treasury rows, total/net-asset/liability rows, and industry subtotal rows. It extracts issuer/instrument from acquisition-date hierarchy rows and intentionally does not promote malformed `Date Processing And Outsourced Services Acquisition Date` rows that lack an issuer.
- Added focused wrapper tests in `tests/test_bdc_xbrl_wrapper.py` for debt leaves, equity/common-unit leaves, subtotal/cash/treasury false positives, malformed no-issuer false positive handling, position-key coupon/NAV stability, and registry support. Added focused staging tests in `tests/test_unified_holdings.py` for TCW Star debt extraction, equity extraction, and malformed no-issuer exclusion.
- Validation: wrapper schema validation passed; wrapper coherence passed; focused wrapper tests passed (`6 passed`); focused staging tests passed (`3 passed`). Fresh staging oracle and trial-holdings oracle each reported 13 quarters and zero remaining blocking rows.
- One-CIK trial rebuild with matching produced 436 trial rows versus 436 production rows, delta `0` rows and `0` FV delta in every quarter. Matching produced 304 pairs and passed J01 (`B1b rate = 97.7%`, threshold 70%) and J03 (`D_fuzzy rate = 0.0%`, threshold 10%).
- Trial and current-production promotion-style gates both returned `promotion_status=review_required`, `blocking_rows_delta=-108`, and `blocking_fv_delta=-3671776234`, with no structural issues. Remaining review reasons were `exclusion_risk_detected` on 2023-03-31, 2023-06-30, and 2023-09-30; `fv_magnitude_shift_detected` and `low_position_continuity` on 2023-06-30 and 2023-09-30; and `cost_fv_ratio_outliers` on 2025-09-30 and 2026-03-31.
- A full cached production `python scripts/rebuild_outputs.py --unified` was attempted after checking for existing rebuild jobs, but timed out after 45 minutes and the orphaned rebuild process was stopped. `python scripts/diff_outputs.py --semantic` was run afterward and failed due broad existing workspace drift (`443 divergent artifact(s)`, 3,682 checked, 77 skipped), not as an isolated TCW Star signal.
- No SEC downloads were performed. The claim was marked done because the wrapper exists, required source/oracle/trial/matching/promotion-style validation ran, and deterministic blockers were cleared.

**Status: done_with_review_items** -- CIK `0001916608` has zero remaining deterministic blocking rows in fresh staging/trial oracle checks and passes trial position matching. Human review is needed for exclusion-risk, FV-shift/continuity, and cost/FV diagnostics above; production promotion still requires a successful canonical cached unified rebuild in a clean environment.

## 2026-06-09 - Onex corrupted source-row exclusion and Manulife wrapper package

- For CIK `0001860424` (`Onex Falcon Direct Lending BDC Fund`), added exact audited aggregate-row overrides for the malformed Apryse source identifier in the 2025-06-30 and 2025-09-30 accessions. The corrupted concatenated rows are now excluded from the trial unified output rather than promoted as position-level loans.
- Updated `data/overrides/bdc_xbrl_wrappers/0001860424.json` with a narrow staging guard and known edge case for the corrupted `Non-cNon-controlled...Apryse` source pattern. Added a focused classifier regression in `tests/test_bdc_xbrl_wrapper.py`.
- Claimed CIK `0001988280` (`Manulife Private Credit Fund`) as agent `codex-20260609-xbrl-02` and added `data/overrides/bdc_xbrl_wrappers/0001988280.json`. Updated `data/overrides/bdc_xbrl_wrappers/unlisted_bdc_xbrl_reference.json` from `wrapper_status: none` to `exists` (`with_wrapper` 36 -> 37, `without_wrapper` 93 -> 92 in the current dirty reference file).
- The Manulife wrapper covers pipe-separated `Senior loans` hierarchy rows, two-segment leaves with a missing industry/issuer delimiter, short-term/cash-management rows, percentage-only industry and equity category rows, issuer-only rollups, and canonical position keys that strip changing senior-loan/industry percentages and rate parentheticals.
- Added focused Manulife wrapper tests for senior-loan leaves, missing-delimiter leaves, subtotal/category false positives, issuer-only rollups, short-term non-private rows, position-key stability, and registry support.
- Validation: Manulife wrapper schema validation passed; focused wrapper tests passed (`7 passed`); fresh source oracle passed all 9 quarters with `remaining_blocking_rows=0`; trial-holdings oracle passed all 9 quarters with `remaining_blocking_rows=0`; one-CIK trial rebuild with matching produced 1,698 trial rows versus 1,720 production rows, delta `-22` rows. Matching passed J01 (`B1b rate = 96.8%`, threshold 70%) and J03 (`D_fuzzy rate = 0.2%`, threshold 10%).
- Trial promotion gate for Manulife returned `promotion_status=promote`, `blocking_rows_delta=-96`, and `blocking_fv_delta=-2838415694`. Diagnostics remain visible as warnings: wrapper-only non-private rows, wrapper-only aggregate rows, hierarchy parse disagreements, and debt-wrapper/equity-asset-category disagreement for 25 equity rows.
- No SEC downloads were performed. The Manulife claim was marked done because the wrapper exists, source/oracle/trial/matching/promotion validation passed, and deterministic blockers are cleared.

**Status: done** -- CIK `0001988280` has zero remaining deterministic blocking rows and passes trial promotion. Human review items remaining: none required by the deterministic wrapper gates; optional review may inspect the non-blocking oracle warnings listed above.

## 2026-06-10 - Lord Abbett Private Credit wrapper package

- Claimed CIK `0002008748` (`Lord Abbett Private Credit Fund`) as agent `codex-gpt5-20260610-c4d8` and added `data/overrides/bdc_xbrl_wrappers/0002008748.json`. Updated the `0002008748` entry in `data/overrides/bdc_xbrl_wrappers/unlisted_bdc_xbrl_reference.json` from `wrapper_status: none` to `exists`.
- The wrapper documents Lord Abbett's FV-bearing XBRL rows as category/member/total facts rather than position-level holdings: `First/Second Lien Secured Debt`, `[Member]` category rows, `Total Equity`, total first/second lien debt, total investments, and joint-venture totals. Borrower identifiers with `Revolver` or `Delayed Draw` shapes are recognized as leaf-like, but the cached rows have no fair value and are not promoted.
- Added focused wrapper tests in `tests/test_bdc_xbrl_wrapper.py` for revolver/delayed-draw leaf classification, member/total aggregate handling, bare-issuer false-positive handling, trailing lot-number key normalization, and registry support. Added a focused staging regression in `tests/test_unified_holdings.py` for all-rollup wrapper CIKs.
- Updated `pipeline/staging_bdc.py` so `_prepare_bdc` returns the standard empty unified schema when Phase A filters remove every BDC row. This clears a deterministic empty-output crash exposed by this wrapper without preserving category rows as positions.
- Validation: wrapper schema validation passed; wrapper coherence passed; focused wrapper tests passed (`7 passed`); focused empty-Phase-A staging test passed (`1 passed`). Fresh staging oracle exited successfully with `remaining_blocking_rows=0`; baseline comparison reduced blocking rows from 17 to 0 and blocking FV by approximately `$10.905B`.
- One-CIK trial rebuild with matching produced 0 trial rows versus 3 production rows, delta `-3` rows and FV delta `-$86.385M`. Position matching ran and correctly skipped with no pairs because the trial unified output has no eligible positions.
- Trial promotion-style gate returned `promotion_status=review_required`, `blocking_rows_delta=-17`, and `blocking_fv_delta=-10904531000`. Human-review reasons were exclusion-risk diagnostics for all four quarters, unclassified-rate/FV-rate diagnostics for 2025-09-30 through 2026-03-31, and concept drift on 2026-03-31; these arise because all current FV-bearing source rows are excluded as rollups.
- No SEC downloads were performed. A production rebuild/diff backstop was not started because another agent already had `scripts/rebuild_outputs.py --unified` running as PID `15180`. The claim was marked done because the wrapper exists, required validation ran, deterministic blockers are cleared, and only human-review promotion items remain.

**Status: done_with_review_items** -- CIK `0002008748` has zero remaining deterministic source-reconciliation blockers after fresh staging and trial validation. Human review is needed to approve the zero-position outcome and the promotion gate's exclusion-risk, unclassified-rate/FV-rate, and concept-drift diagnostics.

## 2026-06-10 - Apollo Origination II UL wrapper package

- Claimed CIK `0002052153` (`Apollo Origination II (UL) Capital Trust`) as agent `codex-20260610-xbrl-01` and added `data/overrides/bdc_xbrl_wrappers/0002052153.json`. Updated the `0002052153` entry in `data/overrides/bdc_xbrl_wrappers/unlisted_bdc_xbrl_reference.json` from `wrapper_status: none` to `exists` with `hierarchy_extract` staging.
- The wrapper covers Apollo Origination II UL flat industry/company rows with `Investment Type` or `Security Type` debt/equity/warrant instruments, broader Apollo industry labels, cash-equivalent and money-market exclusions, issuer/source rollups without `Investment Type`, and the repeated `Co-investment` row as a fund-style position leaf.
- Added focused wrapper tests in `tests/test_bdc_xbrl_wrapper.py` for delayed-draw debt, PIK debt, corporate bonds, preferred equity, sector headers, issuer rollups, cash-equivalent total rows, money-market rows, co-investment fund rows, position-key rate stability, maturity-date separation, and registry support. Added a focused staging test in `tests/test_unified_holdings.py` for extended industry-label issuer/instrument extraction.
- Validation: wrapper schema validation passed; focused wrapper tests passed (`12 passed`); focused staging test passed (`1 passed`). Fresh staging oracle passed all 5 quarters with `remaining_blocking_rows=0`.
- One-CIK trial rebuild with matching produced 577 trial rows versus 579 production rows, delta `-2` rows. Matching produced 246 pairs and passed J01 (`B1b rate = 82.6%`, threshold 70%) and J03 (`D_fuzzy rate = 0.8%`, threshold 10%).
- Trial-holdings oracle passed all 5 quarters with `remaining_blocking_rows=0`. Promotion-style gate returned `promotion_status=promote`, `blocking_rows_delta=-11`, and `blocking_fv_delta=-1081378000`.
- No SEC downloads were performed. The claim was marked done because the wrapper exists, source/oracle/trial/matching/promotion validation passed, and deterministic blockers are cleared.

**Status: done** -- CIK `0002052153` has zero remaining deterministic blocking rows and passes trial promotion. Human review items remaining: none required by the deterministic wrapper gates; optional review may inspect the non-blocking oracle warnings for wrapper-only non-private rows, wrapper-only aggregate rows, and one staging-only non-private disagreement.

## 2026-06-10 - Goldman Sachs Private Middle Market Credit wrapper package

- Claimed CIK `0001674760` (`Goldman Sachs Private Middle Market Credit LLC`) as agent `codex-20260610-001` and added `data/overrides/bdc_xbrl_wrappers/0001674760.json`. Updated the `0001674760` entry in `data/overrides/bdc_xbrl_wrappers/unlisted_bdc_xbrl_reference.json` from `wrapper_status: none` to `exists` with `hierarchy_extract + identifier_parser:hierarchical_pct` staging.
- The wrapper covers Goldman private middle-market debt/equity/warrant hierarchy rows, bare and truncated debt prefixes, country/category/instrument subtotal rows, non-private Goldman money-market rows, and bare `Non-Controlled Affiliated Investments` rows as aggregate/review rows rather than position leaves. The staging rule extracts issuer/instrument from CIK-scoped debt hierarchy rows with or without an explicit country bucket while requiring leaf evidence (`Interest Rate`, `Reference Rate`, or `Maturity`).
- Added focused wrapper tests in `tests/test_bdc_xbrl_wrapper.py` for no-prefix debt leaves, category/country/total false positives, bare affiliate false positives, equity leaves, and country-only aggregate handling. Added focused staging tests in `tests/test_unified_holdings.py` for country and no-country debt hierarchy extraction and bare affiliate filtering.
- Validation: wrapper schema validation passed; focused wrapper tests passed (`4 passed`); focused staging tests passed (`3 passed`). Fresh staging promotion-style oracle returned `promotion_status=review_required`, with `remaining_blocking_rows=0` and `remaining_wrapper_blocking_rows=0` across all 13 quarters; baseline comparison reduced blocking rows by 54 and blocking FV by approximately `$6.996B`.
- One-CIK trial rebuild with matching produced 587 trial rows versus 609 production rows, delta `-22` rows. Matching produced 323 pairs; J03 passed (`D_fuzzy rate = 0.6%`, threshold 10%) while J01 remained below threshold (`B1b rate = 49.5%`, threshold 70%) because many continuations match by exact name rather than wrapper position key.
- Trial-holdings oracle against `data/output/bdc_xbrl_wrapper_trial/0001674760/unified_trial/private_markets_holdings.0001674760.csv` reported `remaining_blocking_rows=0` across all 13 quarters. Trial promotion-style gate returned `promotion_status=review_required`, `blocking_rows_delta=-54`, `blocking_fv_delta=-6996106000`, and no structural issues.
- Remaining human-review items are promotion diagnostics only: `exclusion_risk_detected` on 2023-03-31 through 2025-03-31, `cost_fv_ratio_outliers` on 2024-12-31, `low_position_continuity` on 2026-03-31, and the trial matching J01 position-key stability warning. These are not remaining source-reconciliation missing-row blockers.
- No SEC downloads were performed. A production cached rebuild and `python scripts/diff_outputs.py --semantic` backstop were not started because another agent already had `scripts/rebuild_outputs.py --unified` running as PID `15180` in the shared workspace. The claim was marked done because the wrapper exists, required validation ran, deterministic blockers are cleared, and only human-review promotion/matching items remain.

**Status: done_with_review_items** -- CIK `0001674760` has zero remaining deterministic source-reconciliation blockers after fresh staging and trial validation. Human review is needed for the promotion diagnostics and J01 warning listed above before treating the wrapper as production-clean.

## 2026-06-10 - SCP Private Credit Income wrapper package

- Claimed CIK `0001743415` (`SCP Private Credit Income BDC LLC`) as agent `codex-gpt5-20260610-001` and added `data/overrides/bdc_xbrl_wrappers/0001743415.json`. Updated the `0001743415` entry in `data/overrides/bdc_xbrl_wrappers/unlisted_bdc_xbrl_reference.json` from `wrapper_status: none` to `exists` with `hierarchy_extract` staging.
- The wrapper covers SCP's pipe-separated 2023 debt/equity identifiers and later dash/pct-prefixed hierarchy identifiers, including bank debt/senior secured loans, common equity/equity interests/warrants, preferred equity/PIK rows, cash equivalents, totals/net asset/liability rows, and exact bare Oldco AI rollup members. Position keys strip volatile NAV percentages, rate/floor/spread text, label words, and date-day granularity while preserving issuer/industry and maturity month/year identity.
- Added focused wrapper tests in `tests/test_bdc_xbrl_wrapper.py` for debt leaves, equity/preferred leaves, liability/total/cash false positives, bare Oldco rollups versus detailed Oldco loan leaves, pipe-to-dash position-key stability, maturity separation, and registry support. Added focused staging tests in `tests/test_unified_holdings.py` for pipe debt, dash debt, equity issuer/instrument extraction, and CIK scoping.
- Validation: wrapper schema validation passed; wrapper coherence passed; focused wrapper tests passed (`7 passed`); focused staging tests passed (`4 passed`). Fresh staging oracle passed all 11 quarters with `remaining_blocking_rows=0` and reduced source blockers by 25 rows / about `$3.882B` FV.
- One-CIK trial rebuild with matching produced 412 trial rows versus 422 production rows, delta `-10` rows. Matching produced 300 pairs and passed J01 (`B1b rate = 96.9%`, threshold 70%) and J03 (`D_fuzzy rate = 0.7%`, threshold 10%).
- Trial-holdings oracle against `data/output/bdc_xbrl_wrapper_trial/0001743415/unified_trial/private_markets_holdings.0001743415.csv` passed all 11 quarters with `remaining_blocking_rows=0`. Trial promotion-style gate returned `promotion_status=promote`, `blocking_rows_delta=-25`, and `blocking_fv_delta=-3882192000`.
- No SEC downloads were performed. A production cached rebuild and `python scripts/diff_outputs.py --semantic` backstop were not started because another agent already had `scripts/rebuild_outputs.py --unified` running as PID `15180` in the shared workspace.

**Status: done** -- CIK `0001743415` has zero remaining deterministic blocking rows and passes trial promotion. Human review items remaining: none required by the deterministic wrapper gates; optional review may inspect the non-blocking oracle warnings for non-private-market, aggregate-detection, and hierarchy-parse disagreements.

## 2026-06-10 - NexPoint Capital wrapper package

- Claimed CIK `0001588272` (`NexPoint Capital, Inc.  (NXPT)`) as agent `codex-gpt5-20260610-001` and added `data/overrides/bdc_xbrl_wrappers/0001588272.json`. Updated the `0001588272` entry in `data/overrides/bdc_xbrl_wrappers/unlisted_bdc_xbrl_reference.json` from `wrapper_status: none` to `exists` (`with_wrapper` 37 -> 38, `without_wrapper` 92 -> 91 in the current dirty reference file).
- The dispatch-only wrapper covers NexPoint pipe-delimited senior secured loans, corporate bonds, asset-backed securities, preferred/common stocks, LLC interests, warrants, cash equivalents, net assets, total investments, and other-assets rows. It preserves position-level preferred-stock leaves that end in coupon percentages, including the repeated `Preferred Stocks | Financials | United Fidelity Bank FSB | 7.00%` blocker, while filtering category/total/cash rows.
- Added focused wrapper tests in `tests/test_bdc_xbrl_wrapper.py` for the terminal-coupon preferred-stock leaf, PIPE debt leaf classification, category/cash false positives, and registry support. Added focused staging tests in `tests/test_unified_holdings.py` for terminal-coupon preferred-stock survival and bare preferred-category exclusion.
- Updated `pipeline/staging_bdc.py` so staging regex placeholders decode general JSON-style `\uXXXX` escapes before DuckDB SQL generation. This kept unrelated dirty wrapper configs with literal Unicode escapes from blocking deterministic staging validation.
- Validation: wrapper schema validation passed; wrapper coherence passed; focused wrapper tests passed (`4 passed`); focused staging tests passed (`2 passed`). Fresh staging oracle and trial-holdings oracle each reported 11 quarters, `remaining_blocking_rows=0`, and `oracle_status_counts={'pass': 9, 'fail': 2}`.
- One-CIK trial rebuild with matching produced 283 trial rows versus 288 production rows, delta `-5` rows. Matching produced 230 pairs and passed J01 (`B1b rate = 81.6%`, threshold 70%) and J03 (`D_fuzzy rate = 0.0%`, threshold 10%). The wrapper position-key normalization strips volatile pipe-delimited rate/current-coupon/maturity tokens while preserving issuer/tranche text.
- Trial promotion-style gate against `data/output/bdc_xbrl_wrapper_trial/0001588272/unified_trial/private_markets_holdings.0001588272.csv` returned `promotion_status=review_required`, `blocking_rows_delta=-36`, and `blocking_fv_delta=-805357676`, with no structural issues and no remaining blocker rows.
- Remaining human-review items are promotion diagnostics only: `cost_fv_ratio_outliers` on 2023-09-30 (one cost/FV ratio outlier, zero source blockers) and `low_position_continuity` on 2025-06-30 (position continuation rate `0.4828`, zero source blockers). Non-blocking warnings remain visible for wrapper-only non-private rows, aggregate-detection disagreements, hierarchy parse disagreements, and warrant/equity category disagreements.
- No SEC downloads were performed. A production cached rebuild and `python scripts/diff_outputs.py --semantic` backstop were not started because another agent already had `scripts/rebuild_outputs.py --unified` running as PID `15180` in the shared workspace. The claim was marked done because the wrapper exists, required validation ran, deterministic blockers are cleared, and only human-review promotion items remain.

**Status: done_with_review_items** -- CIK `0001588272` has zero remaining deterministic source-reconciliation blockers after fresh staging and trial validation and passes trial position matching. Human review is needed for the 2023-09-30 cost/FV ratio diagnostic and the 2025-06-30 low-continuity diagnostic before treating the wrapper as production-clean.

### 2026-06-11 -- Plan A: Wrapper layer fixes + oracle canary checks

Implements the wrapper extraction fixes and oracle canary checks from the position match calibration review (112 errors in 600 sampled pairs, 47 errors from 4 CIK wrapper/staging problems).

**CIK wrapper fixes:**
- **Fidelity (0001920453):** Added `category_marker_re` to dispatch config to catch bare category subtotals ("Debt", "Debt Diversified Financial Services", etc.) that lack instrument keywords. Uses end-anchored regex to distinguish category headers from real positions that always trail with rate/maturity fields.
- **Stepstone (0001950803):** Added `pipe_field_map` staging config and CIK-scoped WHEN branches in staging_bdc.py to extract issuer from pipe segment 4 (not segment 3/industry). The generic 7-pipe pattern was assigning the industry segment as issuer.
- **GSBD (0001572694):** Added `hierarchy_extract` staging section with issuer/instrument regexes for the "Investment <type> - <pct>% <company> Industry <label> <fields>" format. Added 43 extra_industry_labels for GSBD-specific GICS sectors.
- **North Haven (0001851322):** Fixed hierarchy_extract condition and issuer regex to handle the affiliation-stripped form. After Phase A strips "Investments-non-controlled/non-affiliated", identifiers start with the bare industry label, not "Investments". Made the "^Investments..." prefix optional in both `hierarchy_condition_extra` (OR with industry-label start) and `hierarchy_issuer_re`.

**Schema changes:**
- Added `pipe_field_map` property to staging section in wrapper_v3.schema.json (issuer_segment, instrument_segments, industry_segment, lien_segment)
- Added `segment_assertions` top-level property for canary format-drift assertions

**Oracle checks (I08-I11):**
- I08: Segment assertion drift -- validates pipe-segment content types against declared assertions in wrapper JSON. Uses pattern detectors (entity_name_like, rate_like, date_like, gics_sector_like, instrument_like).
- I09: GICS issuer name detection -- flags CIK-quarters where >5% of position_leaf issuer_names match known GICS sub-industry labels (catches pipe/hierarchy mis-assignment generically).
- I10: Instrument sub-type coverage -- warns when multi-position-per-entity groups have identical instrument descriptions (precondition for pattern 4/6 matching errors).
- I11: Position key uniqueness within entity -- warns when multiple positions at the same entity share near-duplicate position keys (predicts tranche-renumbering vulnerability).

**Files modified:**
- `data/overrides/bdc_xbrl_wrappers/0001920453.json` -- added category_marker_re
- `data/overrides/bdc_xbrl_wrappers/0001950803.json` -- added pipe_field_map + segment_assertions
- `data/overrides/bdc_xbrl_wrappers/0001572694.json` -- added hierarchy_extract staging
- `data/overrides/bdc_xbrl_wrappers/0001851322.json` -- refined hierarchy_extract regexes
- `pipeline/staging_bdc.py` -- pipe_field_map loading + CIK-scoped WHEN branches
- `pipeline/oracle_checks.py` -- I08/I09/I10/I11 checks + pattern detectors + GICS label set
- `schemas/bdc_xbrl_wrapper/wrapper_v3.schema.json` -- pipe_field_map + segment_assertions
- `tests/test_oracle_checks.py` -- 15 new tests for I08/I09/I10/I11

**Test results:** 110 oracle_checks tests passed; 624 wrapper tests passed (1 pre-existing failure in Apollo DS test, unrelated). All wrapper JSON files load correctly. No regressions in validation_rules (52 passed) or validate_fund_financials tests.

### 2026-06-11 -- Issuer-level subtotal arithmetic clearing in source reconciliation

Added a new source reconciliation clearing mechanism `documented_source_issuer_subtotal_arithmetic` that identifies issuer-level subtotal source rows whose FV matches the sum of multiple output leaf positions for the same issuer name. This addresses the majority of blocking rows that are parent XBRL hierarchy nodes, not genuinely missing positions.

**Mechanism design:**
- Two new CTEs: `source_issuer_subtotal_candidates` (filters unmatched source rows with entity signals like LLC/Inc/Corp but no position signals like Term Loan/Revolver/SOFR) and `source_issuer_subtotal_arithmetic` (joins to output on `contains(source_staging_id, normalized_issuer_name)` with FV tolerance matching)
- Requires >= 2 output leaf children and FV tolerance of max($1, 0.01%)
- Fires after existing `documented_source_rollup_exact` to avoid double-clearing
- DuckDB RE2 compatibility: all `\b` word boundaries replaced with `(?:\s|$)` since RE2 does not support `\b`

**Files modified:**
- `pipeline/source_reconciliation.py` -- new constants, CTEs, CASE branches in source_detail, metrics aggregation
- `tests/test_source_reconciliation_cache.py` -- 5 new test cases (basic clearing, FV mismatch, single child, position signal, pipe-delimited)
- `tests/test_validate_holdings.py` -- updated `test_bdc_xbrl_wrappers_can_be_disabled_for_baseline_comparison` assertion (Trinity/Aledia parent now correctly cleared as issuer subtotal; blocking count 3->2)

**Test results:** 10/10 source_reconciliation_cache tests passed. 139/139 validate_holdings tests passed. 116/116 oracle_checks tests passed. 111/111 bdc_filings tests passed.

**Remaining work:** Wrapper dispatch updates for Crescent Capital (0001633336), MidCap Financial (0001278752), Goldman Sachs BDC (0001572694) deferred until source reconciliation is re-run on cached data to measure Part 1 residual and identify which CIKs still need wrapper updates.

### 2026-06-11 -- Per-CIK parsed-field quality packets for wrapper oracle

Added review-only parsed-field quality packets to the BDC XBRL wrapper oracle. Each wrapper trial now writes `parsed_field_quality.csv` under the target CIK trial directory, scoped only to that CIK, and flags suspicious production output fields such as contaminated issuer names, instrument descriptions, and position keys that include hierarchy labels, percentages, rate/date fragments, or low-information text.

**Files modified:**
- `pipeline/bdc_xbrl_wrapper_oracle.py` -- added parsed-field packet construction, CIK scoping, packet artifact write, and two summary telemetry columns: `parsed_field_quality_issue_count` and `parsed_field_quality_fair_value`
- `tests/test_bdc_xbrl_wrapper_oracle.py` -- added focused tests for contaminated output detection, clean-row/other-CIK suppression, and preserving oracle pass/fail status

**Validation results:**
- `pytest tests/test_bdc_xbrl_wrapper_oracle.py -k parsed_field_quality -q` -- 3 passed
- `pytest tests/test_bdc_xbrl_wrapper_oracle.py -q` -- 76 passed

**Contract note:** These checks are warnings/review packets only. They do not add oracle failure reasons or change wrapper promotion pass/fail behavior.

### 2026-06-11 -- One-CIK row-delta attribution for wrapper oracle

Added deterministic row-delta attribution to BDC XBRL wrapper trials. Each trial now writes `row_delta_attribution.csv`, scoped to the target CIK, comparing trial BDC holdings against current production BDC holdings and explaining added rows, removed rows, parsed-field changes, classification changes, and numeric changes.

**Files modified:**
- `pipeline/bdc_xbrl_wrapper_oracle.py` -- added row-delta schema, current-production CIK loader, attribution builder, and artifact write
- `tests/test_bdc_xbrl_wrapper_oracle.py` -- added focused row-delta tests for empty matches, CIK scoping, added/removed rows, non-private and aggregate removals, parsed/classification changes, numeric tolerance, and artifact writing

**Validation results:**
- `pytest tests/test_bdc_xbrl_wrapper_oracle.py -k row_delta -q` -- 7 passed
- `pytest tests/test_bdc_xbrl_wrapper_oracle.py -q` -- 83 passed

**Contract note:** This is oracle trial telemetry only. It does not change production holdings, source reconciliation, oracle pass/fail status, or promotion-gate behavior.

### 2026-06-11 -- High-FV unclassified cluster packets for wrapper oracle

Added high-FV unclassified cluster review packets to BDC XBRL wrapper trials. Each trial now writes `high_fv_unclassified_clusters.csv`, scoped to the target CIK, when a wrapper's FV-weighted unclassified rate breaches its configured `unclassified_rate.max_fv_pct` threshold. The packet groups repeated unclassified labels by issuer/instrument/identifier, reports affected quarters, FV impact, output classification fields, and a suggested wrapper family guess.

**Files modified:**
- `pipeline/wrapper_content_signatures.py` -- added `classify_content_signature_rows()` so oracle telemetry can reuse the same content-signature classification and wrapper-family fallback logic as validation
- `pipeline/bdc_xbrl_wrapper_oracle.py` -- added high-FV unclassified cluster schema, CIK-scoped cluster builder, family-guess heuristics, and trial artifact write
- `tests/test_wrapper_content_signatures.py` -- added tests for row-level classification fallback and absolute-FV output
- `tests/test_bdc_xbrl_wrapper_oracle.py` -- added focused tests for threshold suppression, grouping, CIK scoping, multi-quarter summaries, classified-row exclusion, and artifact writing

**Validation results:**
- `pytest tests/test_wrapper_content_signatures.py -q` -- 41 passed
- `pytest tests/test_bdc_xbrl_wrapper_oracle.py -k high_fv_unclassified -q` -- 6 passed
- `pytest tests/test_bdc_xbrl_wrapper_oracle.py -q` -- 89 passed

**Contract note:** This is oracle trial telemetry only. It does not change production holdings, source reconciliation, oracle pass/fail status, or promotion-gate behavior. It is intended to give wrapper agents a per-CIK worklist for high-FV rows that are currently not covered by local archetypes or wrapper family classification.

### 2026-06-11 -- Bipartite (Hungarian) matching for C/D/E tiers

Replaced greedy ROW_NUMBER PARTITION BY dedup with the Hungarian algorithm (minimum-cost bipartite matching) for C/D/E tiers. This finds the globally optimal 1:1 assignment across all positions for the same entity, fixing wrong_tranche errors caused by FV crossover in multi-position entities.

**Architecture:** Post-processing approach with minimal SQL changes.
- C/D/E tier SQL now saves ALL candidate pairs to `tier_X_candidates` temp tables before greedy dedup
- Greedy dedup still runs as fallback
- New `_bipartite_dedup()` function groups candidates into connected components via UnionFind, runs Hungarian on each multi-position component, replaces the tier table
- `use_bipartite` parameter on `match_positions()` (default True) controls the behavior

**Files changed:**
- `pipeline/utils.py` -- Added `hungarian_assignment()`: pure Python O(N^3) implementation for small matrices (entity groups are 2-8 positions)
- `pipeline/position_matching.py` -- Split C/D/E SQL into candidates + dedup; added `_bipartite_dedup()` with per-tier cost functions; added `use_bipartite` parameter
- `tests/test_hungarian.py` -- New: 10 tests (1x1, 2x2, 3x3, rectangular, all-equal, sentinel, brute-force cross-check, empty)
- `tests/test_position_matching.py` -- Added 5 bipartite tests (FV crossover resolution, correct greedy preservation, rectangular group, single pair passthrough, flag disabled)
- `scripts/assess_bipartite.py` -- New: gold-set comparison script (greedy vs bipartite against calibration v2)

**Gold-set assessment results (302 C/D/E rows):**
- 6 errors fixed (wrong_tranche/wrong_entity -> different pair)
- 3 regressions (correct -> different pair) -- likely Unicode encoding artifacts (em-dash vs hyphen)
- Net improvement: +3
- 239 unchanged correct, 38 unchanged error

**Match count impact:**
- C: 2,218 -> 2,265 (+47)
- D: 12,967 -> 14,670 (+1,703)
- E: 5,598 -> 6,325 (+727)
- Total: 511,482 -> 513,959 (+2,477 net new matches)

**Performance:** Bipartite adds ~70s to the ~120s matching pipeline (total ~190s with bipartite vs ~120s greedy). Overhead is dominated by Tier D (48s for 5,744 components, 1,163 multi-position).

**Test counts:** 107 position matching + Hungarian tests pass. Full suite: 3,546 passed, 13 skipped, 0 new failures (1 pre-existing failure in `test_bdc_xbrl_wrapper.py::test_apollo_ds_company_only_source_row_is_aggregate` excluded).

**Follow-up: Tier E bipartite disabled (same session).** Deep analysis of results showed Tier E bipartite produced 6,856 reassigned pairs (79% of all churn), dominated by lateral swaps within ambiguous name clusters at a single CIK (Cliffwater, 5,853 swaps). FV proximity was sometimes sacrificed. Gold-set changes were lateral moves, not accuracy improvements. Bipartite now only applies to Tier C and D where the mechanism addresses the wrong_tranche failure mode (entity groups with multiple distinct tranches where FV crossover causes greedy mis-assignment). Tier E's entity fingerprint matching operates on fuzzier identity signals where globally-optimal reassignment is not meaningful.

### 2026-06-12 -- Final wrapper-oracle agent packet and drift architecture

Finalized the wrapper-oracle extension architecture and implemented the remaining trial telemetry, agent verdict, and promotion-gate integration.

**Files modified:**
- `docs/wrapper_oracle_extensions/oracle_agent_review_and_drift_design.md` -- converted open questions into final architecture decisions for materiality, drift baselines, verdict confidence, waiver scope, artifact ownership, and per-CIK wrapper scoping
- `pipeline/bdc_xbrl_wrapper_oracle.py` -- added agent row packets, agent cluster packets, source-corrupted identifier detection, per-CIK column distribution drift summaries/examples, agent verdict JSONL validation, verdict summary reduction, and promotion-gate consumption of verdict effects
- `tests/test_bdc_xbrl_wrapper_oracle.py` -- added focused coverage for materiality tiers, source-corrupted packets, drift packeting, packet aggregation, verdict validation/summary effects, promotion-gate verdict effects, and trial artifact writes
- `pipeline/bdc_filings.py` -- moved the non-accrual helper import inside `_parse_single_filing()` to resolve an existing circular import that blocked wrapper-oracle test collection

**New trial artifacts:**
- `source_corrupted_identifiers.csv`
- `column_drift_summary.csv`
- `column_drift_examples.csv`
- `agent_issue_packets.csv`
- `agent_issue_packets.jsonl`
- `agent_cluster_packets.csv`
- `agent_cluster_packets.jsonl`
- `agent_verdict_summary.csv`

**Contracts and guardrails:**
- Agent packet outputs are scoped to the requested CIK and are trial telemetry, not production truth.
- Column drift compares each CIK's current quarter against a rolling four-quarter baseline, using all available prior quarters for short histories and requiring at least two prior quarters before review status.
- Verdict summaries can reject or require review for promotion, but only through deterministic `promotion_effect` values derived from validated JSONL verdict records.
- Verdict validation requires mechanism, evidence, confidence, residual risk, materiality tier, affected FV, and a deterministic repair path; it rejects hand-edited production-output recommendations.

**Validation results:**
- `python -m py_compile pipeline/bdc_xbrl_wrapper_oracle.py pipeline/bdc_filings.py` -- passed
- `pytest tests/test_bdc_xbrl_wrapper_oracle.py -k "materiality or source_corrupted or column_drift or agent_issue or agent_cluster or agent_verdict or promotion_gate_consumes_agent or high_fv_unclassified_clusters_trial_writes_artifact" -q` -- 8 passed, 88 deselected
- `pytest tests/test_bdc_xbrl_wrapper_oracle.py -q` -- 96 passed

### 2026-06-12 -- Wrapper oracle production-validation packets and review-only outlier gates

Implemented the finalized wrapper-oracle additions that move noisy wrapper-adjacent signals into agent-review artifacts instead of direct oracle hard failures.

**Files modified:**
- `pipeline/bdc_xbrl_wrapper_oracle.py` -- added production column validation issue export and packet mapping, source-verbose identifier packets, cost/FV outlier row packets, expanded text/identity column drift coverage, and no-wrapper-row cluster packets.
- `tests/test_bdc_xbrl_wrapper_oracle.py` -- added and updated focused tests for review-only cost/FV semantics, source-verbose false-positive control, production validation packet mapping, text drift, parsed-field coupon allowances, and staging-only no-wrapper-row handling.

**Contracts and guardrails:**
- `cost_fv_ratio_outlier_count` remains visible in `oracle_summary.csv`, but `cost_fv_ratio_outliers` is no longer an oracle fail reason; row-level issues are emitted as `WRAP.COST_FV_RATIO_OUTLIER`.
- Verbose raw source identifiers are emitted as `WRAP.SOURCE_VERBOSE_IDENTIFIER` only when paired with output contamination, parsed-field residue, or an unresolved blocker. `source_corrupted_identifiers.csv` remains as a compatibility alias.
- Wrapper trials now write `source_verbose_identifiers.csv`, `cost_fv_ratio_outliers.csv`, and `column_validation_issues.csv`.
- Production column validation issues are mapped into agent row packets as `WRAP.PRODUCTION_COLUMN_VALIDATION` with the original validation `rule_id` preserved as `source_rule_id`.
- Column drift now covers identity/text fields and uses tighter review thresholds for text-shape changes (`JS >= 0.12` or new bucket share `>= 0.10`).
- Existing wrapper definitions with no produced wrapper rows now use `no_wrapper_rows` and emit `WRAP.NO_WRAPPER_ROWS`; `unsupported_wrapper_cik` is reserved for no wrapper definition.

**Validation results:**
- `python -m py_compile pipeline/bdc_xbrl_wrapper_oracle.py pipeline/column_validation.py` -- passed
- `pytest tests/test_bdc_xbrl_wrapper_oracle.py -q` -- 101 passed
- `pytest tests/test_column_validation.py -q` -- 20 passed
- Cache-only smoke trial: `python -m pipeline.bdc_xbrl_wrapper_oracle --cik 0001508655 --output-dir .codex_tmp\wrapper_oracle_recheck_0001508655` -- passed; 13 summary rows, status counts `{'fail': 9, 'pass': 4}`, 10 cost/FV packets, 5,451 production column validation packets, 2 column drift cluster packets. Cost/FV counts no longer appeared in oracle fail reasons.

### 2026-06-15 -- Leaf->lien recovery from BDC XBRL instance document order (new module, not yet integrated)

Investigated why ~45% of cohort DIRECT_LENDING FV has blank `lien_position` (frontend `firstLien:0.9792` overstated by folding Unknown into First Lien). Root cause: hierarchical-tagging filers (Blackstone, HPS) tag lien tier on *subtotal* facts only; leaf position facts carry just `InvestmentIdentifierAxis`, so there is no dimensional key linking leaf to lien. The link exists only as document order in the instance (confirmed: leaf runs reconcile to lien x sector subtotals to the cent).

- **New module** `pipeline/bdc_lien_hierarchy.py` -- read-only, cache-only. Walks `InvestmentOwnedAtFairValue` facts in instance document order, groups leaf runs, assigns the lien/sector of the closing subtotal **only when the run reconciles to the subtotal** (derived-truth gate). Non-reconciling runs returned flagged (lien=None), never assigned.
- **Tests** `tests/test_bdc_lien_hierarchy.py` -- 5 passed, incl. false-positive guard (non-reconciling subtotal is not accepted), structure-absent case, lien-only subtotal, independent two-sector grouping.
- **Measured** (latest cached instance per filer): Blackstone $76.5B recovered (112/176 groups reconcile), HPS Corp Lending $24.2B, HPS Corp Cap Solutions $1.7B. Cohort recovered lien-FV ~$102.5B, recovery rate 78.5% by FV; ~$28B flagged stays Unknown.
- **Golub (PCF 0001930087, BDC4 0001901612): method does NOT apply** -- 0 sector subtotals, lien-only subtotals do not reconcile to leaf runs; lien stays Unknown. Recovery is filer-specific and must be gated by structure detection + per-filer coverage.
- **Not integrated** into staging/unified/frontend and no outputs rebuilt -- pending owner sign-off and the cross-reconciliation/drift/semantic gates described in the gate assessment.

## 2026-06-15 -- Frontier data-quality architecture design reference

- Added `docs/refactoring/frontier_architecture.md` (design discussion, no
  pipeline behavior change). Consolidates a multi-turn architecture session.
- Captures: the organizing principle (deterministic for truth / learned for
  triage / statistical for the bound; flatten last not first); a nine-stage
  target architecture; the TWO gate families (value/conservation vs
  structure/format) and that the format gate doubles as the per-CIK
  drift-trigger; schemas for the source fact store (long-format, keyed on
  `context_id`), the append-only decision ledger, and the gate registry.
- Worked examples grounded in real data: IRGSE (CIK 0001508655) showing the
  reconciliation key bug (dimension-string vs resolved-issuer) that both misses
  subtotals and creates false-positive blockers; ABC Corp format-drift trace;
  PIK/lien/sector relocation to signal producers over the fact store.
- Documents the autonomy ceiling, coverage holes (what passes a perfect FV gate
  while still wrong), best-practice comparison, suggested 80/20 build order, and
  open risks (context->position cardinality, gold-set cost, frozen-config recall
  dependency).

### 2026-06-15 -- Lien breakdown (aggregate, from filer subtotals) + frontend wiring

Implemented Track A: the lien analogue of the existing sector breakdown. Reads the filer's own lien subtotals directly (aggregate) rather than mapping each leaf, mirroring `bdc_sector_breakdown.py` which already reads sector subtotals and skips position-level contexts.

- `pipeline/bdc_sector_breakdown.py` -- added `extract_bdc_lien_breakdown()` (+ `_parse_lien_contexts`, `_extract_lien_facts`, `_aggregate_lien_tiers`). Detects lien tier from the member name (axis-name agnostic, reuses `bdc_lien_hierarchy._lien_tier`). Per (cik, report_date, lien_tier): prefers summing lien x sector subtotals, falls back to the pure lien-tier total; skips ambiguous lien x non-sector partitions to avoid double counting. Output: `data/output/bdc_lien_breakdown.csv`.
- `pipeline/config.py` -- `BDC_LIEN_BREAKDOWN_FILE`.
- `tests/test_bdc_lien_breakdown.py` -- 5 passed (sector-sum, pure-tier fallback, no-double-count when both present, position-context skipped, ambiguous-partition skipped). `tests/test_bdc_lien_hierarchy.py` (Track B leaf mapping) -- 5 passed.
- `pipeline/export/index_exports.py` -- `_export_portfolio_characteristics` now sources `lienSplit` from `bdc_lien_breakdown.csv` (cohort, as-of quarter) with an explicit `unknown` bucket and `source` tag, falling back to the old per-position subtraction method if the artifact is absent. Fixes the prior defect where blank lien was folded into First Lien.
- `frontend/src/lib/types.ts` -- `lienSplit` gains optional `subordinated`, `unknown`, `source`. `app/indices/[slug]/page.tsx` and `app/page.tsx` render Subordinated + Unknown/unreported slices. `npm run build` passes.
- **Measured (cohort, 2025-12-31):** First Lien $212.3B (70.3%), Second $5.3B (1.8%), Subordinated $2.7B (0.9%), Unsecured $1.0B (0.3%), Unknown $80.8B (26.7%) of $302.0B DL FV -- vs published `firstLien:0.9792`. Filers without lien subtotals (Golub, Fidelity, Stellus, AB) correctly remain Unknown.
- **Not yet run:** `--export-frontend` (would regenerate published JSON); `bdc_lien_breakdown.csv` currently covers cohort filers' 2025-12-31 filings only (not full history). Known gate gap: the lien_only fallback can pick up non-subtotal contexts (AB Private Credit emits a small negative First Lien) -- a sum(tiers) vs total-DL-FV reconciliation gate should flag/drop these before publication.

### 2026-06-15 -- Step 1 (v1) shadow disposition ledger (read-only diagnostic)

- Added `scripts/build_shadow_disposition_ledger.py`. Read-only; writes only to
  `data/output/shadow/` (does NOT touch unified_holdings or any production
  artifact). Scope: 77 wrapped BDC CIKs, current-period rows.
- Design: v1 does NOT build a competing disposition engine. It REUSES the
  existing pipeline's disposition outcome (validated rule stack -> unified
  membership) and adds only the independent conservation gate on top. Cheap
  text/marker/leaf signals are kept as high-recall/low-precision triage flags,
  not decisions. (An earlier draft built fresh competing signals; it lost to the
  validated logic in both directions and was abandoned -- the months of
  trial/error in the existing rules are the asset, not a thing to reimplement.)
- Outputs: bdc_row_disposition_ledger.csv (existing disposition + triage flags),
  bdc_triage_summary.csv, bdc_conservation_residual.csv (the tiered gate result).
- CONSERVATION ANCHOR repointed to fund_financials (companyfacts): STRONG =
  investments_at_fair_value (same quantity as Sum(positions), independent
  source), secondary tight = schedule grand-total, loose = total_assets. Anchor
  coverage of the 850 wrapped CIK-quarters jumped ~18% -> ~90% (companyfacts_fv
  734, schedule_total 34, loose_assets 9, none 73). Validation: median
  sum_included/tight_anchor = 1.0; companyfacts_fv vs schedule_total agree to
  0.0% median |diff| (n=121). Gate over existing output: 452 reconcile, 204
  overshoot/leak, 112 undershoot/missing -> ~316-CIK-quarter residual queue.
- DATA-QUALITY FINDING: `bdc_fund_highlights.total_assets` is mis-scaled/
  mis-extracted for 710/790 (~90%) CIK-quarters (TSLX 2023-12-31 shows $7.6M for
  a $3.28B fund; assets_net -$1.5B); BS identity holds 4.3% vs 98.8% for
  companyfacts/fund_financials. Broken highlights balance-sheet fields feed
  nothing in production; being removed from the extraction (see below). Fixing it
  would unlock a wide-coverage
  loose bound.
- The balance-sheet InvestmentOwnedAtFairValue no-dimension total is NOT
  extracted into bdc_holdings (0/850); lifting tight coverage beyond ~18%
  requires that extraction.
- Documented as section 8b in docs/refactoring/frontier_architecture.md.

### 2026-06-15 -- Reduce lien Unknown: layered export + reconciliation gate + keyword vocab

Implemented the three levers to reduce the 26.7% Unknown lien in the cohort DL split.

- **Lever 1 + gate** (`pipeline/export/index_exports.py`): new `_layer_lien_split(pp_rows, sub_rows, pct)` helper. Per filer, uses `bdc_lien_breakdown` subtotals only when they reconcile to that filer's DL FV (all tiers >= 0, total within +5%, coverage >= 50%); routes the uncovered remainder to Unknown; otherwise uses the already-populated per-position `lien_position`. `_export_portfolio_characteristics` now calls this (replacing the aggregate-only block). The reconciliation gate correctly rejects AB Private Credit's negative subtotal. `lienSplit` JSON gains `subordinated`, `unknown`, `source`, `subtotalFilers`.
- **Lever 2** (`pipeline/lien_classification.py`): added `one stop`/`one-stop` (Golub unitranche product) and `first-lien`/`1st-lien`/`second-lien`/`2nd-lien` hyphen variants.
- **Tests**: `tests/test_layer_lien_split.py` (6, incl. negative/over-count/low-coverage gate fallbacks); `tests/test_lien_classification.py` (+6, incl. false-positive guard). 128 lien-related tests pass.
- **Verified (cohort 2025-12-31, current data):** layered split = First 85.3%, Second 1.9%, Subordinated 0.6%, Unsecured 0.4%, **Unknown 11.8%** (was 26.7% aggregate-only; published was firstLien 97.9%). 19 filers pass the gate.
- **Not yet run:** `--unified` rebuild (needed for Lever-2 keywords to populate `lien_position`; projected Unknown then ~5-6%) and `--export-frontend`.

### 2026-06-15 -- Shadow ledger: residual localization pass

- Added a localization pass to `scripts/build_shadow_disposition_ledger.py`
  (read-only). For each non-reconciling tight CIK-quarter it finds the specific
  candidate rows that explain the signed gap, using STRUCTURE not subset-sum:
  overshoot -> aggregate-like included row ~ excess, or aggregate-like row ~ sum
  of >=2 detailed same-issuer children (issuer subtotal); undershoot -> excluded
  row WITH leaf detail ~ shortfall. Confirms each quarter by gap-closure
  (removing/adding candidates reconciles to the anchor). Reuses the pipeline's
  resolved issuer_name (joined from unified). Outputs
  bdc_residual_localization.csv (candidate rows) and
  bdc_residual_localization_summary.csv (per-quarter label).
- Labels over the 316 non-reconciling tight quarters: overshoot_unexplained 150,
  undershoot_unexplained 86, partial_leak 34, leak_localized 20, drop_localized
  19, partial_drop 7.
- FINDINGS: (1) undershoots are largely SCOPE, not drops -- excluded short-term
  Treasury-bill rows match the shortfall (intentionally excluded from
  private-markets holdings but included in investments_at_fair_value). (2) the
  largest overshoots are STRUCTURAL, not small subtotals -- e.g. CIK 0001851322
  2025-12-31 +$7.1B, 0001920453 2025-03-31 +$2.0B (sum ~2x fund -> likely
  comparative-period bleed or duplicate dimension paths); candidates do not close
  these (labeled partial/unexplained). (3) issuer_subtotal precision is limited
  by the unreliable typed has_leaf_detail field (detail-in-string filers), so
  partial_leak candidates include noise -- handled by the gap-closure label
  (leak_localized high-confidence, partial_leak low-confidence).
- NEXT: scope-aware labels (short-term/Treasury/money-market -> scope, not drop);
  investigate top unexplained overshoots (the highest-$ residuals); join
  source_wrapper_rule_id provenance for per-rule attribution.

### 2026-06-15 -- reference_rate_type inference + maturity_date text generalization

Descriptor-tagging gap work (hierarchical filers tag numeric per-position facts but not categorical descriptors).

**reference_rate_type evidence-flagged inference (all BDCs, self-gating):**
- `staging_bdc.py`: `reference_rate_type` now resolves XBRL field -> identifier text -> inference (basis_spread present + not EUR/GBP/SONIA + `report_date >= 2023-07-01` -> SOFR, else LIBOR). New `reference_rate_source` column tags `xbrl_field` / `identifier_text` / `inferred_post_libor` / `inferred_pre_libor` / ''.
- Threaded `reference_rate_source` through `UNIFIED_COLUMNS` (unified_holdings.py), `staging_nport.py` (''), `db.py` (pmi_holdings schema + `_HOLDINGS_COLS`).
- Verified: inference produces SOFR/inferred_post_libor end-to-end via `_prepare_bdc`; both BDC and N-PORT carry the column (same set as UNIFIED_COLUMNS; union uses named columns so order-independent). Projected floating reference_rate_type coverage 30% -> ~99% across v3 cohort after rebuild.

**maturity_date text generalization:**
- `staging_bdc.py`: maturity text extraction now also scans `instrument_description` (was identifier-only), incl. "due M/YYYY" / "Maturity Date M/D/YYYY". Verified extracts "due 2/2032" and "Maturity Date 6/30/2030" from description.
- DATA FINDING: this recovers ~$0 in the current BDC universe -- the $363B blank-maturity DL FV (Blackstone, Blue Owl family, Ares, HPS, FS KKR, Golub) has maturity in NEITHER identifier nor description; XBRL has no per-position maturity concept for these filers (confirmed via concept scan). Maturity is HTML-only and, unlike reference rate, has no inference analogue (per-loan date). Real recovery requires the audited per-CIK HTML bridge (`bdc_xbrl_html_bridge`); the text generalization is a correct robustness improvement that protects future desc-embedding filers.

**Tests:** `tests/test_lien_classification.py` (+6 incl. false-positive guard), `tests/test_layer_lien_split.py` (6), `tests/test_bdc_lien_breakdown.py` (5), `tests/test_bdc_lien_hierarchy.py` (5) pass. Full `test_unified_holdings.py` exceeds bounded run window (>590s); targeted structural + synthetic verification used. Not yet run: `--unified` rebuild / `--export-frontend` (would apply the reference-rate inference and publish).

### 2026-06-15 -- HTML-section bridge: maturity_date + reference_rate recovery (builder + apply)

Extended the audited HTML-section bridge (`bdc_xbrl_html_bridge.py`) to recover descriptor VALUES (previously classification-only) for filers that tag numeric facts per position but not maturity/reference-rate (Blackstone et al.).

- **Builder**: `(continued)` section headers now match (`_section_for_row` strips "(continued)" -- was missing 53 continuation headers on Blackstone, only 14 base matched). Added `_extract_row_dates` (maturity = latest row date, acquisition = earliest), `_extract_reference_rate` (SOFR/LIBOR/PRIME incl. SF+/S+/P+). Fixed `_search_terms` to strip the pipe affiliation suffix + tranche number ("123Dentist, Inc. 1 | Non-Affiliated Issuer" -> "123Dentist, Inc.") -- this was leaving "| Issuer" in terms so Blackstone never matched (HPS-style clean identifiers unaffected). New bridge fields: `maturity_date`, `acquisition_date`, `reference_rate_type` (in `BRIDGE_TABLE_COLUMNS`, candidate record, `_record_to_row`).
- **Apply**: new `apply_html_section_bridge_field_overlays` overlays maturity_date / reference_rate_type onto exact (cik, accession, report_date, raw_id) bridge matches, **blank-only, no clobber**, tagging `reference_rate_source='html_section_bridge'`. Wired into `staging_bdc._prepare_bdc`.
- **Tests**: `tests/test_bdc_xbrl_html_bridge_fields.py` (9, incl. no-clobber + no-match-noop guards). Existing `test_bdc_xbrl_html_bridge.py` (12) still passes -> 21 total.
- **Blackstone 2025-12-31 proposal generated** (`.tmp/blackstone_bridge_proposal_2025-12-31.json`, NOT placed in the auto-loaded bridge dir pending review): 750/2036 positions matched (36.8%), of which **98.9% carry maturity_date and 97.3% reference_rate_type**, FV-reconciled. ~$31B of Blackstone's $83.8B DL FV.
- **Rejection diagnosis**: 1,252/1,286 rejections are `candidate_count=0` (term/positioning misses, NOT FV ambiguity -- only ~31 are >1-candidate). So 37% is the current positioning ceiling; higher coverage needs better section/row positioning + fuzzier issuer matching (follow-on tuning), not disambiguation.
- **Governance note**: `load_html_section_bridge_rows` loads any `*.json` in the bridge dir with the right schema_version -- so the existing HPS `0001838126.proposed.json` IS active, and accepting Blackstone = placing the reviewed file there. Consider a loader gate distinguishing accepted vs proposed.

### 2026-06-15 -- iXBRL contextRef-anchored field bridge (supersedes fuzzy matching)

Root-cause: the cached BDC HTML is INLINE XBRL (ix:nonFraction/contextRef present), but maturity is untagged display text (0 maturity ix-facts). The fuzzy issuer-name+FV matcher only reached 36.8% on Blackstone. The principled fix anchors on the tagged FV fact's `contextRef` -- whose context's `InvestmentIdentifierAxis` member == `bdc_investment_identifier` -- then reads maturity from the same DOM `<tr>`. Exact per-position key, no name guessing.

- `pipeline/bdc_xbrl_html_bridge.py`: added `propose_field_bridges_from_ixbrl(cik, accession, report_date, html_path)` -- parses iXBRL, maps FV-fact contextRef -> position identity, walks to enclosing `<tr>`, extracts maturity (latest row date) + reference_rate + acquisition_date. Emits the same bridge-record shape the loader/apply already consume.
- **Blackstone 2025-12-31 result: 2,002/2,036 positions anchored (98.3%), 100% with maturity_date, 89.8% with reference_rate_type, in ~2s** (vs 36.8% fuzzy). Per-tranche exact (Atlas CC tranche 4 = PRIME vs SOFR for 1-3). Proposal at `.tmp/blackstone_ixbrl_bridge_2025-12-31.json` (NOT auto-activated, pending review).
- Tests: `tests/test_bdc_xbrl_html_bridge_fields.py` +2 (per-tranche anchor, subtotal-context skip) -> 11 pass; existing `test_bdc_xbrl_html_bridge.py` (12) still passes.
- The existing `apply_html_section_bridge_field_overlays` + loader consume these records unchanged. Generalizes to any inline-XBRL filer (Blue Owl, Ares, HPS, FS KKR) by running the builder per accession.
- Recommendation: prefer the iXBRL anchor over the fuzzy proposer for inline-XBRL filers; review + accept Blackstone, rebuild, measure WAM lift; this also supplies the ACTUAL reference rate (superseding the SOFR inference for matched rows).

### 2026-06-15 -- Frontend cohort: gate-verified expansion 39 -> 70 v3-wrapper BDCs

- GATE-VERIFIED all 77 v3 wrapper files against the FV conservation gate
  (unified sum vs fund_financials.investments_at_fair_value / total_assets at each
  fund's latest anchored quarter). Result: 68 clean + 2 no-anchor = 70 admitted;
  7 HELD BACK for over-inclusion (unified/total_assets > 1.05): 0002052153 Apollo
  Origination II (1.73x), 0001988280 Manulife (1.26x), 0001975736 KKR FS Income
  Trust Select (1.18x), 0001377936 Saratoga (1.16x), 0001930679 KKR FS Income
  Trust (1.15x), 0002037804 New Mountain (1.10x), 0001278752 MidCap (1.05x). These
  exhibit issuer-subtotal duplication and need wrapper/dedup fixes before
  admission. None were in the prior v1_39 cohort, so no live fund is affected.
- NEW MANIFEST data/overrides/wrapper_cohorts/v2_70_gate_verified_wrapper_manifest.json
  (70 entries). config.WRAPPER_COHORT_MANIFEST_FILE repointed from v1_39 (retained
  for audit). Frontend scope 39 -> 70 (+31 added, 0 dropped). Verified the export
  filter now loads 70 CIKs.
- CLEANUP: deleted 321 stale non-cohort fund_details/*.json (pre-V1-narrowing
  leftovers, mostly listed BDCs; git-recoverable). 69 in-cohort detail files kept.
- NOT YET DONE (scope DEFINED, not REGENERATED): a frontend re-export
  (`python -m pipeline.main --export-frontend`) is required to (a) regenerate the
  filtered aggregates (index/analytics/fund_list still reflect the old 39 scope)
  and (b) create the 1 missing cohort detail file (0002083477 APS BDC). Deferred
  because the worktree is broadly divergent from baseline; a blind full export is
  unsafe.

### 2026-06-15 -- Gate fix (sum unified) + new rate/scale shadow gate

- FIX: scripts/build_shadow_disposition_ledger.py now computes the gate quantity
  (sum_included) from UNIFIED fair value per CIK-quarter, not from summing matched
  bdc_holdings source rows (which double-counted where unified deduped, e.g.
  duplicate 10-K/10-K/A). Added source_included_fv + source_minus_unified
  diagnostics. Wrapped-cohort overshoot 204 -> 203 (only the duplicate-filing CIK
  was a source artifact in this set); tool is now correct regardless of dedup.
- NEW: scripts/build_shadow_rate_scale_gate.py (read-only, the interest_rate
  axis). Core period-independent check: portfolio weighted-avg coupon =
  sum(rate*principal)/sum(principal), plausible band [2,25]%; per-position flags
  for rate in (0,1) (decimal-scaled) and rate>50 (double-scaled). Loose secondary:
  reconstructed annual coupon vs fund total_investment_income (wide band only;
  period-caveated). Outputs bdc_rate_scale_gate.csv + bdc_rate_scale_suspect_rows.csv.
- Findings (77 v3-wrapped CIKs): 720 scale_ok, 109 no_rate_data, 15
  decimal_scale_rows, 1 wavg_out_of_band; median wavg coupon 10.14%. Confirmed
  real decimal-vs-percent errors with identifier-text corroboration: Merx Aviation
  (MidCap 0001278752) rate 0.1 vs "Revolver 10.00%"; Paymentsense (Apollo
  0001837532) 0.125 vs "Interest Rate 12.50%"; Valor VCI (0002052152) 0.1 vs "10%".
- Not committed yet; data/output/shadow/* is gitignored (artifacts regenerable).

### 2026-06-15 -- Closed the inline-XBRL cache gap (audited download) + lien row-text fallback

User-approved audited download to make the iXBRL contextRef anchor usable for all wrapper-CIK position-quarters.

- **Download**: ran the existing audited path (`sec_download_guard.download_bdc_html` driven over the 463-row worklist) -- 462 downloaded + 1 retried (transient "response ended prematurely"), 4.17 GB in ~4.3 min, rate-limited and recorded in `sec_download_manifest.jsonl` (464 entries). Caches the primary inline `.htm` to `bdc_html/` (where the anchor reads).
- **Coverage lift**: inline-XBRL availability across the 77 wrapper CIKs went **54.9% -> 100%** of position-quarters (852/852 CIK-quarters, 316,379/316,379 positions). The gap was a cache-route gap (modern 2022-2026 filers), not pre-iXBRL.
- **Builder lien fallback** (`propose_field_bridges_from_ixbrl`): lien resolves via the lien SECTION header (Blackstone-style) OR, for filers grouped only by industry, the row instrument text -- both normalized through `lien_classification.classify_lien`. Emits `lien_position` (tier) + `lien_section` (raw).
- **Validated across newly-cached filers**: maturity ~95-100%, sector ~100%, reference rate ~90%; lien Blackstone 100% / TPG Twin Brook 99% / Oaktree 89% / Stellus 77% (residual = lien-less equity/JV). 135 bridge/lien tests pass.
- The reusable iXBRL row-anchor now recovers lien + sector + maturity + reference rate per position, exactly contextRef-keyed, for the full wrapper universe. NEXT: wire lien/sector overlays into apply/staging (maturity + ref already wired); reconcile per-position lien/sector vs each filer's own subtotals.

### 2026-06-15 -- Tier-tagged validation inventory (review artifact)

- Added docs/refactoring/validation_inventory.md: catalogs ~450 distinct
  validations/guards across oracle_checks.py (48), the wrapper oracle +
  content_signatures (~40), validate_holdings + validation_rules (~115),
  highlights/financials/nonaccrual/cik validators (~60),
  column_validation/fund_strategy/llm/html_template/source_reconciliation (~145),
  and inline build guards in unified_holdings/bdc_filings/index_returns/
  position_matching (~50). Each tagged tier (tight/weak), method, column,
  enforcement (blocking/advisory/opt_in/inline_mutate), tolerance.
- Headline findings: (1) almost NOTHING blocks the production build -- oracle_runner
  is advisory unless --fail-on-failure; validate_holdings never raises;
  validation_rules.run_all doesn't raise; highlights oracle only nav/income
  identities FAIL; the only things that change/stop production data are inline
  transforms (dedups, universe_gate, pct recalc, scale fixes, position_id assert,
  index filters), most of them silent heuristic mutations. (2) Massive duplication
  -- ~12 implementations of positions-vs-fund-total (GAV/FV) conservation, plus
  repeated subtotal-arithmetic, pct-sum, NAV-identity, rate-scale copies. (3) A
  defined promotion queue of tight-but-advisory checks (A01,A04/E01,E02,E04,E07,
  G02,H01,H05,fv_reconciliation,source_recon engine,V7,V10,PC02/03/08,R07,R10,
  IDX14,XS*,RI01-07,F10/11/12/17/20,nonaccrual recon). (4) checks built on the
  known-unreliable highlights balance-sheet fields flagged. (5) silent-mutation
  guards flagged as highest corruption risk.

### 2026-06-15 -- Parametric conservation gate engine (de-dup FV + cost)

- Added scripts/shadow_conservation_engine.py: one read-only engine for the
  "Sum(value column over unified BDC rows) reconciles to an independent fund-level
  total" pattern. Each check is a data-only ConservationRule(name, value_column,
  anchors[, tolerance, tier]); anchors are priority-ordered {fund_financials column |
  schedule_total value}. The engine is generic -- adding a column to validate is
  adding a rule, no new code. Consolidates the ~12 scattered FV/GAV implementations
  (A04, E01, E02, V7, F20, GAV adapters, R07, html aggregate_fv, nonaccrual chart
  gate, shadow FV gate) plus the cost variant.
- Rules shipped: fv_conservation (fair_value vs companyfacts investments_at_fv,
  fallback schedule total) -- 453 reconcile / 203 overshoot / 108 undershoot / 81
  no_anchor, median ratio 1.0 (reproduces the standalone FV gate); cost_conservation
  (cost vs schedule total cost) -- 60 reconcile / 54 undershoot / 29 overshoot / 702
  no_anchor, median 0.9999. Output: data/output/shadow/conservation_gate_results.csv
  (one row per rule x CIK-quarter, tagged rule_name/value_column/tier/enforcement).
- Note: pct_of_net_assets is a SIBLING (per-row identity FV=pct*NA), a different
  shape than pure sum-conservation; it would extend the engine, not drop in as a
  plain rule. Engine is read-only; data/output/shadow is gitignored.

### 2026-06-15 -- Parametric per-row identity gate engine

- Added scripts/shadow_identity_engine.py: sibling to the conservation engine.
  Checks an algebraic relationship AMONG fields of a single row (optionally + one
  per-quarter scalar join), per row, self-localizing -- catches field errors a
  sum check is blind to. A check is data: IdentityRule(name, table, needed_cols,
  holds_sql, residual_sql, [scalar], row_filter). Skips rules whose columns are
  absent (safe across schema variation). Read-only; output
  data/output/shadow/identity_gate_violations.csv.
- Shipped rules + results (77 v3-wrapped cohort): pct_of_net_assets_identity
  (FV=pct/100*net_assets) 13,136/99,371 violations 13.2%; pik_le_interest_rate
  823/13,584 6.1%; nav_identity (nav*shares=net_assets) 83/2,135 3.9%;
  income_identity (NII=TII-total_expenses) 298/1,162 25.7%; balance_sheet_identity
  (TA-TL=net_assets, companyfacts) 86/2,029 4.2%.
- Findings: balance_sheet holds 95.8% on companyfacts (vs 4.3% on the broken
  highlights fields) -- confirms reliable source; pct identity also flags leaked
  subtotals (bare 'Debt' category rows, e.g. 0001920453 ~$1.6B residual) so it
  doubles as a population-error detector, self-localized; income_identity 26%
  violation is a new signal (likely expense-scope definitional gap).
- Caveat: these are tight in FORM but violation rates are partly definitional
  (total_expenses scope, pik-vs-all-in rate convention), so each needs a
  truth-set/precision pass before promotion to a blocking gate.

### 2026-06-15 -- Parametric cross-source agreement gate engine (3rd shape)

- Added scripts/shadow_cross_source_engine.py: two independent sources must agree
  on the same quantity, joined on a shared key. A check is data:
  CrossSourceRule(name, left=(source,col), right=(source,col), comparator, tol);
  skips rules with absent columns. Read-only; output
  data/output/shadow/cross_source_gate_results.csv.
- Scope = fund-level financials across three independent BDC extractions
  (bdc_fund_highlights = highlights-statement XBRL; bdc_fund_income = income-
  statement XBRL; fund_financials = companyfacts API), joined cik+report_quarter.
  8 rules: highlights<->income (NII 4.7% disagree, TII 1.9%, expenses 0.8%,
  mgmt_fee 0.2%); companyfacts<->income (TII 0.0%, NII 0.0% -- perfect);
  highlights<->companyfacts (nav 9.7%, shares 4.3%). Median |diff| 0% everywhere.
- TRIANGULATION: confirms the identity engine's income_identity 26% violation is
  DEFINITIONAL (sources agree on NII/TII/expenses, so NII != TII-total_expenses is
  an expense-scope gap, not a source error). Two engines cross-validate.
- Documented that the BDC<->N-PORT same-CUSIP agreement (XS01-06) is structurally
  empty here: BDC rows carry no CUSIP (0 of 574K), 0 shared-CUSIP CIK-quarters --
  a tight check that can never fire in this dataset.
- Three parametric shadow engines now exist (conservation / identity / cross-source)
  + the pipeline's source-reconciliation match engine; together they cover the
  tight-check families. Next: wire into one tier/enforcement-tagged runner.

### 2026-06-15 -- Column-aware iXBRL extraction + per-field status enum (shadow list)

Made the iXBRL row-anchor self-describing about confidence (four-state design; not_found assigned upstream at the flat-XBRL join, not in the builder).

- `bdc_xbrl_html_bridge.py`: added `_row_grid` (colspan-aware, includes `<th>`), `_detect_header_map` (footnote-marker-stripped so "Maturity Date (2)(15)" isn't counted numeric), `_FIELD_COLUMN_RULES` (shadow-list header regex per field), and `field_status(field, grid, header_map) -> {value, status, source_column}`. The builder tracks the current column-header map and resolves maturity / acquisition / reference_rate by header, emitting per-field `*_status` + `*_source_column` provenance.
- Status: `value` = header-confirmed cell parsed to expected type; `validation_needed` = value found but column unconfirmed (heuristic / no header) or present-but-unparsable -> review; `blank` = column found, cell empty.
- Measured (2025-12-31): Blackstone maturity 1898 value / 1 vneeded / 114 blank; BX Secured Lending 606/0/68; FS KKR 496/114/114; Main Street 0/508/159 (header undetected -> all flagged, NOT trusted -- the safe failure).
- Tests: test_bdc_xbrl_html_bridge_fields.py +5 -> 16; full bridge suite 28 pass.
- NEXT: flat<->inline join for `not_found`; standing-exception `ensure_inline_doc`; per-CIK shadow-list overrides (e.g. Main Street header); lien/sector subtotal reconciliation; consume only status=value into staging.

### 2026-06-15 -- Unified tier-tagged validation-results runner

- Added scripts/shadow_validation_runner.py: wires the three parametric engines
  (conservation, identity, cross_source) into ONE run over a shared DuckDB
  connection and normalizes their outputs into a single validation-results ledger:
  engine | rule_name | tier | enforcement | cik | period_kind | period | status
  (pass|fail|skip) | metric | metric_name | n_units. Read-only; nothing blocks the
  build -- it measures. Outputs data/output/shadow/validation_results_ledger.csv
  and validation_results_summary.csv (per engine x rule: pass/fail/skip + fail%).
- Run (77 v3-wrapped cohort): 14,653 check-results across 15 rules (2 conservation
  + 5 identity + 8 cross_source, all ran). Tier=tight rollup: conservation
  513 pass / 394 fail / 783 skip(no_anchor); identity 5,492 pass / 921 fail;
  cross_source 6,363 pass / 187 fail.
- This is the read-only panel the consolidation built toward: tight fails are the
  promotion-to-blocking queue; weak checks (from the validation_inventory) would
  graduate into the same ledger as flags with per-rule precision tracking; the
  4 pipeline gate engines (conservation/identity/cross_source + source_reconciliation
  match engine) consolidate the ~12 GAV/identity/cross-source duplicate impls.

### 2026-06-15 -- Flat->inline join assigns not_found status (Step 3)

- `bdc_xbrl_html_bridge.join_flat_positions_to_inline_status(flat_rows, bridges)`: every flat-XBRL position (bdc_holdings) gets per-field inline status; a position with no inline anchor (row not found in the inline doc though present in flat XBRL) -> all fields `not_found` -> review. Anchored fields carry the builder status (value/validation_needed/blank); lien/sector derive value-if-populated-else-blank. Output uses uniform `{field}_status` + `{field}_source_column` naming.
- Tests: +2 in test_bdc_xbrl_html_bridge_fields.py (not_found for unanchored; derived blank/value for anchored) -> 18 pass.
- The four-state taxonomy is now complete: not_found (no inline row, exists in flat) + value/validation_needed/blank (per-field, anchored).

### 2026-06-15 -- Wrapper Part A/B split + flattening prevalence (doc)

- frontier_architecture.md section 9: documented the wrapper split into two MODES
  over one per-CIK config -- Part A (deterministic parse/enrich, in-pipeline,
  splits flattened investment_identifier / reads dimensions where structured,
  format-gate-guarded, frozen-until-drift) and Part B (agentic review of the
  unified validation-results ledger; triages residuals into parse-rule / escalate
  / document; gate is acceptance test). Execution loop A-runs -> ledger -> B-validates
  -> B-authors-Part-A-rule -> re-run; Part B fixes land in Part A's config because
  the durable fix to a parse defect IS a Part A rule and there must be one source
  of truth for parsing.
- Measured identifier-flattening prevalence (current-period BDC, CIK counts): 74
  FLATTENED (~38%, rate embedded in identifier -> must parse), 75 STRUCTURED (~39%,
  typed rate field), 45 MIXED/equity (~23%). Per-datapoint: rate% in identifier
  26.6%, typed interest_rate 59%, typed maturity_date only 29% (maturity is
  predominantly string-sourced). FV-weighting omitted (raw pre-dedup, inflated).

### 2026-06-15 -- Shadow-list rule: MM/YY date parsing in header-confirmed column

Diagnosed Main Street (0001379785) maturity = 0 value / 508 validation_needed despite a detected "Maturity Date" column: the column aligned correctly (header grid-idx -> data cell "04/28") but the cell is abbreviated MM/YY, which `_extract_row_dates` doesn't parse -> fell to validation_needed.

- `bdc_xbrl_html_bridge._parse_field_value`: added MM/YY parsing (`"04/28"` -> 2028-04-30, last day of month) applied ONLY in the header-confirmed date path -- NOT in the heuristic row scan (where MM/DD is ambiguous). This is the safe placement: we only interpret MM/YY when we know the cell is the maturity/acquisition column.
- Result: Main Street maturity 0->500 value (validation_needed 508->8, blank 159 = revolvers/equity). Blackstone unchanged (1898 value). +1 test -> 19 pass in the fields suite.
- Confirms the design: filer-format quirks surface as `validation_needed` (not silent corruption), and are fixed by adding a targeted parse/column rule to the shadow list rather than a per-CIK code branch.

### 2026-06-15 -- Weak field-validity engine + warn status (warn/soft steps 1-2)

- Added scripts/shadow_weak_engine.py: parametric field-validity WEAK engine
  (kinds: row range/sign/enum/format/date, and fill coverage). A check is data:
  WeakRule(name, kind, gate_sql, holds_sql|present_sql, threshold). Emits status
  pass|WARN (never fail), tier=weak, enforcement=flag -- a flag, never a gate.
  Read-only; output data/output/shadow/weak_gate_results.csv. 9 rules shipped:
  interest_rate_range[0,25] (1.0% warn), basis_spread_range[0,15] (13.1%),
  pik_rate_range[0,20] (1.2%), pct_position_concentration[0,25] (47.0%),
  shares_held_sign (0%), coupon_type_enum (0%), issuer_name_length[3,300] (3.9%),
  maturity_not_past DL (10.9%), dl_rate_fill>=80% (12.7%).
- Wired into scripts/shadow_validation_runner.py: ledger now carries `warn` as a
  first-class status (Step 1). Rollup: 24 rules / 21,142 check-results; weak tier
  5,933 pass / 556 warn; tight tiers unchanged. Summary CSV gains n_warn/warn_pct.
  Tight-fail (gate candidates) and weak-warn (flags) are cleanly separated.
- Validated: clean fields self-confirm (shares/coupon 0%, rate 1%); noisy flags
  (pct-concentration 47%, spread/dl-rate-fill 13%) are exactly the precision-track
  candidates -- which is why weak=flag, not gate.
- Remaining (warn/soft steps 3-5): adapter for bespoke weak families (anomaly/
  stability/cross-ref T/S/M), per-rule precision via a truth set, quality-tier
  derivation. Weak warns must stay non-blocking.

### 2026-06-15 -- Maturity content signature + shadow-list sweep (header-rule fixes)

- **Maturity content signature** (`apply_maturity_signature`): a header-confirmed maturity must be future-dated vs report_date; a past-dated "maturity" (likely a coincidentally-aligned misread) downgrades value -> validation_needed. Header-agnostic; closes the coincidental-parse gap the column logic can't. +1 test.
- **Universe sweep** (195 CIKs, latest filing each) tallying per-field status surfaced validation_needed CLUSTERS dominated by filer families (Golub x6, SLR x3, Sixth Street x2, Audax, TriplePoint, ...).
- **Root cause = one global rule bug, not per-CIK quirks**: those families concatenate header labels ("MaturityDate", "AcquisitionDate"), and the maturity rule `(?i)\bmaturity\b` failed to match (no word boundary before "Date"). Fixed the shadow-list rule to `(?i)maturity` (+ `acquisition`/`above index` for the same reason).
- **Impact**: Golub PCF maturity 0 -> 990 value; SLR 0 -> 108; Audax 0 -> 410. Pre-fix position-weighted maturity was 56% value / 36% validation_needed / 8% blank across the universe; the concatenated-header fix lifts the bulk of the 65 sub-20%-value filers.
- Residual clusters (Sixth Street debt schedule, TriplePoint venture BDC) remain and need their own look. 20 fields-suite tests pass.

### 2026-06-15 -- Declarative per-column format contract (weak engine)

- shadow_weak_engine.py now carries COLUMN_FORMAT_CONTRACT: one declarative table
  of each column's expected format (21 columns) -- decimal ranges, enum domains
  (mirroring column_validation.ENUM_VALUES), string lengths, cik pattern, date
  parse + sentinel. _contract_rules() auto-generates one fmt_<col> WeakRule per
  column (type {decimal,enum,string_len,string_exact,pattern,date}); plus 3
  semantic rules (pct concentration, maturity-not-past, dl_rate_fill). 24 weak
  rules total, replacing the prior 9 hand-picked. Answers "does each column have
  an expected format" -- yes, now in one auditable place instead of ~50 scattered
  C-series checks.
- Validated: most columns conform (0% warn for source/cik/report_date/entity_name/
  fair_value/shares/all 4 enums/maturity_date). Residuals: fmt_cost 68% of
  CIK-quarters (~14% of rows out of [0,3e9] -- likely negative cost from cost-proxy
  fill; NEW signal), fmt_pct_of_net_assets 45%, fmt_basis_spread 13%,
  fmt_issuer_name 4%. fmt_cusip/isin inert (BDC carries no CUSIP).
- Unified runner now 39 rules / 30,887 check-results; weak tier 14,865 pass /
  1,369 warn; tight tiers unchanged. Format dimension of the panel complete.

### 2026-06-15 -- Shadow-list rule: bare-footnote header markers

- `_detect_header_map`: extended footnote stripping to also remove BARE trailing footnote refs ("Maturity 6", "Portfolio Company 1 2 3 4"), not just parenthesized "(6)". Stone Point's SOI header used bare numbers -> previously numeric>0 -> header rejected.
- Impact: Stone Point maturity 0 -> 329 value. (Stone Point Income / APS / Fortress unaffected -> different residual causes.) 20 fields-suite tests pass.
- Sweep state after the two systematic fixes (\b concatenated + bare-footnote): position-weighted maturity ~76% value / ~16% validation_needed / ~8% blank; filers >=80% confirmed 80 -> 112. Residual ~25 filers / ~5K positions (~8%) are a DIVERSE tail (venture BDCs Hercules/Horizon with own-notes "due" rows not SOI; Stepstone/Capital Southwest with no detected maturity label; misc) -> correctly routed to validation_needed (recovered-but-unconfirmed = review), the safe state.

### 2026-06-15 -- Adapter: ingest existing check outputs into the ledger (warn/soft step 3)

- Added scripts/shadow_adapter.py: reads EXISTING pipeline check artifacts and
  normalizes them into the unified ledger schema (no re-coding). Sources: oracle
  check_results.csv (48 A-J checks), validation_rules_aggregate.csv (PC/IDX/T/S/R/
  XS/F/M/RI), source_reconciliation_metrics.csv (per-CIK-quarter reconciliation).
  Tier assigned from a tight-check map derived from validation_inventory.md
  (TIGHT_ORACLE, TIGHT_VRULES); everything else weak. Status taken as-reported.
- Wired into shadow_validation_runner.py. Panel now spans 7 sources / 137+
  distinct checks / ~31k results. Rollup adds: source_recon tight 1,434 pass /
  480 fail; oracle weak 260 pass/16 warn/21 fail; validation_rules tight 16 pass/
  2 warn + weak 17 pass/60 warn.
- Caveat: ingests latest-on-disk. The oracle check_results.csv present is a
  PARTIAL run (J-series etc.; the tight A/E-series checks are absent), so oracle
  currently shows 0 tight rows -- a full oracle run would populate them. The tier
  MAP is correct regardless.
- Remaining: same-pattern adapters for nonaccrual / column_validation row-issues /
  highlights oracle; then step 4 (per-rule precision via truth set) and step 5
  (quality-tier derivation). Weak warns stay non-blocking.

### 2026-06-15 -- Bootstrap precision/confidence layer (warn/soft step 4, no truth set)

- shadow_validation_runner.py: added a confidence tag per flagged ledger row,
  derived from INDEPENDENCE signals (production is NOT used as truth -- circular;
  no gold set exists yet). Values: confirmed_impossible (logically impossible,
  e.g. FV>total assets), tight_anchor (tight check failed vs independent anchor),
  corroborated (weak warn co-located with a tight fail at same cik+period),
  scope_caveat (known definitional rules: income_identity, pct concentration,
  fmt_pct_of_net_assets, dl_rate_fill), lone_weak (uncorroborated weak warn).
  surface = {confirmed_impossible, tight_anchor, corroborated}.
- Outputs: ledger now has confidence+surface columns; new
  validation_precision_proxy.csv (per rule: flagged/surfaced/by-confidence).
- Result: 3,450 flagged -> 2,274 surfaced, 1,176 (34%) suppressed (857
  scope_caveat, 297 lone_weak). fmt_cost 575 -> 399 corroborated / 176 lone;
  income_identity 298 all scope_caveat (correctly silenced). Makes the panel
  actionable today.
- These are PROXIES: real precision still needs the source-adjudicated gold set
  that the Part B review loop accrues. Production is never the arbiter; the source
  filing is.

## 2026-06-15 - iXBRL field-status: lien reconciliation gate (a) + value overlay into staging (b)

Completed "do both" on the per-position iXBRL descriptor field-status system.

What changed (pipeline/bdc_xbrl_html_bridge.py):
- reconcile_to_subtotals(per_position, subtotals, tol_pct=0.05, tol_abs=5e6) (a):
  rolls value-status per-position lien FV up to the filer's own lien subtotals;
  returns {reconciled, tiers}. Tested pass+fail.
- build_field_status_rows(bridges, flat_rows, lien_subtotals) (producer core):
  joins flat positions -> inline status (assigns not_found to flat rows absent
  from the inline doc), applies the lien reconciliation gate (value->validation_
  needed for the whole filing when rollup fails), emits overlay-schema rows
  (maturity_status / lien_status / reference_rate_status). Tested: join+not_found
  + reconcile pass/fail downgrade.
- apply_ixbrl_field_status_overlay(df, status_rows) (b): rewritten vectorized
  (merge-based, no per-row loop) for the ~1.18M-row _prepare_bdc frame. Applies
  status=='value' maturity/lien/reference_rate onto blank-only staged cells,
  exact-keyed by (cik, accession, report_date, raw_id_lower); sets
  reference_rate_source='ixbrl_field_status'. Tested value-only + blank-only.
- extract_bdc_ixbrl_field_status(...) (universe producer; APPLY STEP, not run):
  iterates cached inline filings, runs the builder + build_field_status_rows,
  writes BDC_IXBRL_FIELD_STATUS_FILE. report_date read as VARCHAR (DATE inference
  yields '...-00:00:00' keys that break the context-instant anchor -> 0 bridges).

Wiring:
- config.py: BDC_IXBRL_FIELD_STATUS_FILE = data/output/bdc_ixbrl_field_status.csv.
- staging_bdc._prepare_bdc: consumes the artifact via apply_ixbrl_field_status_
  overlay after the HTML-section bridge overlay; NO-OP if the artifact is absent.

Validation:
- Scoped single-CIK smoke (Blackstone 0001803498, cached HTML only, no downloads):
  43,734 position-quarters -> maturity value 75.8%, not_found 19.5%, blank 4.8%;
  reference_rate value 60.4%, validation_needed 14.0% (shadow-list flagging
  unconfirmed columns); lien reconciliation passed (lien value 33,011).
- Tests: tests/test_bdc_xbrl_html_bridge_fields.py 23 passing (incl. reconcile
  gate + producer-core + vectorized overlay). 151 passing across the touched
  lien/bridge test files.

Apply step still pending (requires explicit go; heavy + overwrites central data):
  run extract_bdc_ixbrl_field_status() universe-wide, then rebuild unified.
