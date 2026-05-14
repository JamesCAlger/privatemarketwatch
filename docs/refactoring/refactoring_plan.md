# Refactoring Plan: Structural Decomposition

## Context

The pipeline has 3 monolithic modules that intermingle extraction, conformance, and output logic:

- `unified_holdings.py` (3,720 lines) - classification constants, SQL generators, per-source staging, cross-source conformance, and gold output all in one file
- `fund_financials.py` (2,414 lines) - 4-source extraction + conformance + output in one pass
- `export_frontend.py` (3,514 lines) - 26 export functions re-deriving classification logic that already exists upstream

This plan decomposes the three modules into focused files with clear responsibilities. No semantic changes. No new features. Every phase produces byte-identical output.

### What this plan delivers

File decomposition: splitting three large files (~9,650 lines total) into ~10 smaller files with re-export shims for backward compatibility, verified by byte-identical output comparison. The vocabulary of bronze/silver/gold layers is used as an organizational aid in the module map, but this refactoring does not adopt layered data architecture (strict layer boundaries, DAG runner, schema contracts, lineage tracking). Those are separate architectural decisions for after the structural work is proven safe.

---

## Prerequisites

### Clean starting state

The working tree has uncommitted modifications to all three target files, their tests, 200+ data files, and ~80 `_tmp_*.py` scratch files. Before starting Phase 0:

1. **Commit the current dirty working tree** (or stash experimental changes). The refactoring needs a clean starting SHA so that any phase can be cleanly reverted.
2. **Verify the commit represents production ground truth** -- the snapshot in Phase 0 must correspond to a committed state, not a dirty tree.

### Git strategy

- **One commit per phase.** Each phase gets its own commit with a message like `refactor: phase 1 -- extract classification module`. This gives each phase a revert point and makes review tractable.
- **Snapshot artifacts (`data/snapshots/baseline/`) must NOT be committed to git.** They are ~3.5 GB of CSV data. Add `data/snapshots/` to `.gitignore`. Record only the manifest (file checksums) in version control, either outside the ignored tree (recommended: `docs/refactoring/baseline_manifest.json`) or with an explicit `.gitignore` exception if the manifest remains under `data/snapshots/`.
- **Phase 6 (shim removal) should be a separate commit** from Phases 1-5. It is the only phase that changes import paths in consumer code, and it is the phase most likely to introduce subtle bugs.

---

## Phase 0: Safety Net

**Goal:** Snapshot current outputs and create a diff script so every subsequent phase can be verified.

### Steps

1. **Create `scripts/snapshot_outputs.py`** - copies all byte-identical artifacts to `data/snapshots/baseline/` with checksums (SHA-256 per file)
2. **Create `scripts/diff_outputs.py`** - compares current byte-identical artifacts against `data/snapshots/baseline/`; reports byte-identical or shows first divergent row per file; exits non-zero on any diff
3. **Define an artifact manifest** - explicitly enumerate all refactor-sensitive output artifacts:
   - every file under `data/output/`
   - every JSON file matching `frontend/public/data/*.json`
   - every JSON file matching `frontend/public/data/fund_details/**/*.json`
   - each artifact must be classified as `byte_identical`, `checksum_only`, or `excluded_with_reason`
4. **Record baseline provenance** - write current `git rev-parse HEAD`, `git status --short`, artifact checksums, snapshot timestamp
5. **Run snapshot** - freeze current production outputs before any code changes
6. **Optionally capture generated SQL strings** - if this can be done without refactoring first, dump the SQL fragments produced by the pure SQL generator helpers (for example `_sql_classify_index()`, `_sql_classify_asset_class()`, `_sql_is_bdc_aggregate()`) to `data/snapshots/baseline/generated_sql/`. Do not add invasive instrumentation only for this check. After each phase, compare these generated fragments to catch moved constants or undefined helper names earlier than CSV diffing.
7. **Verify collection before execution** - confirm the test suite can be collected before treating a test run as authoritative
8. **Verify round-trip** - run `python scripts/rebuild_outputs.py`, then `python scripts/diff_outputs.py` to confirm the rebuild itself is deterministic

### Snapshot scope

**Deterministic outputs (include in byte-identical check):**

| Artifact | Rows | Note |
|---|---|---|
| `private_markets_holdings.csv` | 690K | Core unified holdings |
| `bdc_holdings.csv` | 1.04M | Raw XBRL extract |
| `nport_holdings.csv` | 835K | Raw N-PORT extract |
| `position_matches.csv` | 541K | Matching cascade output |
| `position_returns.csv` | - | Per-position returns |
| `index_returns.csv` | 100 | 4 indices x 25 quarters |
| `fund_financials.csv` | - | 177+ CIKs |
| `fee_uplift.csv` | 128 | Per-CIK fee uplift |
| `bdc_sector_breakdown.csv` | - | Per-CIK aggregates |
| All 409 frontend JSON files | - | Static frontend data |

**Non-deterministic or operator artifacts (exclude from byte-identical check unless the manifest says otherwise):**
- GICS classification outputs (GPT API calls)
- LLM review outputs
- Any timestamp-bearing metadata (e.g., `pipeline.log`)
- Ad-hoc validation text files, markdown investigation notes, and scratch outputs in `data/output/`

The manifest is the source of truth for inclusion. "Every file under `data/output/`" means every file must be reviewed and classified, not necessarily byte-diffed.

**Total baseline size:** ~3.5 GB, dominated by the three large CSV files.

### Note on pytest interaction

Tests use `unittest.mock.patch` to redirect config paths to `tmp_path` (pytest temporary directories). They do NOT write to `data/output/` directly. The real risk is subtler: some tests may have side effects on shared caches (e.g., `gics_label_cache.csv`), and any test that fails to mock a path correctly would write to production. The core snapshot-diff workflow is not broken by running `pytest`, but the Phase 0 verification step should confirm this: (1) run `rebuild_outputs.py` to generate baseline, (2) snapshot, (3) run `pytest`, (4) run `rebuild_outputs.py` again, (5) diff against snapshot. If the diff is clean, the rebuild is deterministic and pytest does not corrupt it.

### Files created

- `scripts/snapshot_outputs.py` (~50 lines)
- `scripts/diff_outputs.py` (~80 lines)
- `docs/refactoring/baseline_manifest.json` or an explicitly unignored `data/snapshots/baseline/manifest.json` (checksums + provenance)
- `data/snapshots/baseline/generated_sql/` (optional SQL string dumps, if captured without invasive instrumentation)

### Verification

- `python scripts/diff_outputs.py` exits 0 (all files match baseline)
- `pytest --collect-only tests/` confirms the current collected test suite
- `pytest tests/` passes for the current collected test suite

---

## Phase 1: Extract Classification Module

**Goal:** Move all classification constants, SQL generators, and Python classifiers out of `unified_holdings.py` into a reusable `pipeline/classification.py`. This is the highest-leverage extraction because classification logic is the #1 reason `export_frontend.py` re-derives business logic.

### Risk: SQL generator constant coupling

All SQL generators reference module-level constants directly, not via parameters. The dependency graph:

| SQL Generator | Constants Referenced Directly |
|---|---|
| `_sql_is_bad_issuer_name()` | `_BAD_ISSUER_NAMES_EXACT`, `_BAD_ISSUER_PREFIXES`, `_BAD_ISSUER_ENTITY_SIGNALS` |
| `_sql_classify_bdc_asset()` | `_BDC_FUND_KEYWORDS`, `_BDC_LOAN_KEYWORDS`, `_BDC_EQUITY_KEYWORDS` |
| `_sql_classify_index()` | `_CREDIT_FUND_SIGNALS`, `_PE_FUND_SIGNALS`, `_REAL_ESTATE_KEYWORDS`, `_REAL_ESTATE_FUND_KEYWORDS`, `_STRUCTURED_CREDIT_KEYWORDS`, `_CASH_KEYWORDS`, `_CASH_CORPORATE_GUARD_KEYWORDS`, `_HEDGE_FUND_KEYWORDS` |
| `_sql_classify_exposure_type()` | `_CASH_KEYWORDS`, `_CASH_CORPORATE_GUARD_KEYWORDS` |
| `_sql_classify_asset_class()` | `_CASH_KEYWORDS`, `_CASH_CORPORATE_GUARD_KEYWORDS`, `_REAL_ESTATE_KEYWORDS`, `_REAL_ESTATE_FUND_KEYWORDS`, `_STRUCTURED_CREDIT_KEYWORDS`, `_HEDGE_FUND_KEYWORDS`, `_CREDIT_FUND_SIGNALS`, `_PE_FUND_SIGNALS` |

**Constants MUST move with their SQL generators.** If any constant is missed, the SQL generator will reference an undefined name, producing a `NameError` at runtime (not import time, since the SQL is generated lazily when a pipeline function calls the generator). `_BAD_ISSUER_ENTITY_SIGNALS` is therefore part of Phase 1, because `_sql_is_bad_issuer_name()` moves in Phase 1. The generated SQL string comparison from Phase 0 catches this at the source rather than at the CSV output symptom.

The four base helpers (`_sql_keyword_check`, `_sql_exact_match`, `_sql_starts_with_any`, `_sql_ends_with_any`) have zero internal dependencies. The classification generators only call these base helpers internally -- they do not call each other. This means extraction is safe IF everything moves together as a group.

### What moves to `pipeline/classification.py` (~1,400 lines)

**Constants (from unified_holdings.py lines 253-597):**

- `_INDUSTRY_LABELS`, `_BAD_ISSUER_NAMES_EXACT`, `_BAD_ISSUER_PREFIXES`, `_BAD_ISSUER_ENTITY_SIGNALS`
- `_NPORT_ASSET_MAP`, `_NPORT_ISSUER_MAP`
- `_BDC_FUND_KEYWORDS`, `_BDC_LOAN_KEYWORDS`, `_BDC_EQUITY_KEYWORDS`
- `_MONEY_MARKET_KEYWORDS`, `_CREDIT_FUND_SIGNALS`, `_PE_FUND_SIGNALS`
- `_NPORT_FUND_NAME_KEYWORDS`, `_NPORT_CREDIT_FUND_NAME_KEYWORDS`, `_NPORT_GOVT_NAME_RE`
- `_NPORT_LP_FUND_CO_KEYWORDS`, `_BDC_FUND_VEHICLE_KEYWORDS`, `_BDC_FUND_VEHICLE_POS_GUARD`
- `_COMPANY_MARKERS`, `_COINVEST_KEYWORDS`, `_LP_INTEREST_KEYWORDS`, `_STRICT_COMPANY_MARKERS`, `_NAMED_LP_PATTERNS`
- `_REAL_ESTATE_KEYWORDS`, `_REAL_ESTATE_FUND_KEYWORDS`, `_STRUCTURED_CREDIT_KEYWORDS`
- `_CASH_KEYWORDS`, `_CASH_CORPORATE_GUARD_KEYWORDS`, `_HEDGE_FUND_KEYWORDS`
- `_VINTAGE_FUND_RE`, `_SERIES_RE`, `_FUND_WORD_RE`
- `_PIPE_INSTRUMENT_KEYWORDS`, `_LEGAL_SUFFIX_RE_SQL`

**SQL generators (from unified_holdings.py lines 599-1026):**

- `_sql_keyword_check`, `_sql_exact_match`, `_sql_starts_with_any`, `_sql_ends_with_any`
- `_sql_is_bad_issuer_name`
- `_sql_classify_bdc_asset`, `_sql_classify_index`
- `_sql_is_named_coinvest`
- `_sql_classify_exposure_type`, `_sql_classify_asset_class`
- `_sql_normalize_name`, `_sql_money_market_check`, `_sql_industry_label_in`

**Python classifiers (from unified_holdings.py lines 1352-1657):**

- `_classify_bdc_asset`, `_classify_nport_asset`
- `_classify_bdc_issuer`, `_classify_nport_issuer`
- `_classify_index`
- `_infer_coupon_type`, `_normalize_rate`
- `_is_named_coinvest`

### What stays in `unified_holdings.py`

- `UNIFIED_COLUMNS` (output schema constant)
- BDC aggregate patterns (`_BDC_AGGREGATE_PATTERNS`, `_BDC_AGGREGATE_EXACT`, `_BDC_AGGREGATE_SUFFIXES`) - staging-specific, not classification
- Affiliation patterns (`_AFFILIATION_PREFIX_RE`, `_AFFILIATION_SUFFIX_RE`, `_AFFILIATION_TAGS`) - staging-specific
- `_QTY_PREFIX_RE` - parsing utility
- `_sql_is_bdc_aggregate` - staging-specific SQL
- `_parse_bdc_identifier`, `_is_bdc_aggregate_row`, `_is_bad_issuer_name` - BDC parsing/filtering
- `_reclassify_named_fund_positions` - calls classification functions (now imported)
- `_prepare_bdc`, `_prepare_nport` - staging pipelines (now import classification SQL)
- `_stabilize_classification`, `_correct_pct_of_net_assets` - conformance
- `build_unified_holdings`, `_apply_row_corrections`, `_enforce_schema`, `_log_summary` - gold
- `_CORRECTABLE_FIELDS`, `_CORRECTIONS_REQUIRED_COLS` - gold constants

### Re-export shim in `unified_holdings.py`

**11 symbols** need re-export shims in this phase. These are the classification symbols currently imported by `test_unified_holdings.py` and `pipeline/llm_review.py`:

```python
# Re-exports for backward compatibility -- Phase 1
# Remove in Phase 6 after migrating consumer imports.
from pipeline.classification import (  # noqa: F401
    _classify_bdc_asset,
    _classify_bdc_issuer,
    _classify_index,
    _classify_nport_asset,
    _classify_nport_issuer,
    _infer_coupon_type,
    _INDUSTRY_LABELS,
    _is_named_coinvest,
    _normalize_rate,
    _sql_classify_asset_class,
    _sql_classify_exposure_type,
)
```

Consumers of these shims:

| Symbol | Imported by |
|---|---|
| `_classify_bdc_asset` | `test_unified_holdings.py` |
| `_classify_bdc_issuer` | `test_unified_holdings.py`, `pipeline/llm_review.py` |
| `_classify_index` | `test_unified_holdings.py`, `pipeline/llm_review.py` |
| `_classify_nport_asset` | `test_unified_holdings.py` |
| `_classify_nport_issuer` | `test_unified_holdings.py` |
| `_infer_coupon_type` | `test_unified_holdings.py` |
| `_INDUSTRY_LABELS` | `test_unified_holdings.py` |
| `_is_named_coinvest` | `test_unified_holdings.py` |
| `_normalize_rate` | `test_unified_holdings.py` |
| `_sql_classify_asset_class` | `test_unified_holdings.py` |
| `_sql_classify_exposure_type` | `test_unified_holdings.py` |

### Verification

- If SQL strings were captured in Phase 0, generated SQL strings match the Phase 0 baseline
- `pytest --collect-only tests/` confirms the current collected test suite
- `pytest tests/` passes for the current collected test suite (imports still resolve via re-exports)
- `python scripts/rebuild_outputs.py && python scripts/diff_outputs.py` - byte-identical output

---

## Phase 2: Extract BDC Identifier Parsing

**Goal:** Move BDC identifier parsing and aggregate detection out of `unified_holdings.py` into `pipeline/bdc_identifier.py`.

### Cross-module dependency

`_sql_is_bdc_aggregate()` is the most complex generator, with 10+ embedded constants and 4 base helper calls. Phase 1 moved the 4 base helpers (`_sql_keyword_check`, `_sql_exact_match`, `_sql_starts_with_any`, `_sql_ends_with_any`) to `classification.py`. Phase 2 must import them from there. This creates a new dependency: `bdc_identifier.py` -> `classification.py`. This is architecturally correct but means Phase 2 cannot be done before Phase 1.

### What moves to `pipeline/bdc_identifier.py` (~500 lines)

**Constants:**

- `_BDC_AGGREGATE_PATTERNS`, `_BDC_AGGREGATE_EXACT`, `_BDC_AGGREGATE_SUFFIXES`
- `_AFFILIATION_PREFIX_RE`, `_AFFILIATION_SUFFIX_RE`, `_AFFILIATION_TAGS`
- `_QTY_PREFIX_RE`

**Functions:**

- `_parse_bdc_identifier` (187 lines) - splits investment_identifier into (issuer_name, instrument_description)
- `_is_bdc_aggregate_row` (131 lines) - Python mirror of aggregate detection
- `_is_bad_issuer_name` - Python mirror of bad issuer name detection
- `_sql_is_bdc_aggregate` (96 lines) - SQL generator for aggregate filtering

### Re-export shim

**4 symbols** need re-export shims in this phase:

```python
# Re-exports for backward compatibility -- Phase 2
from pipeline.bdc_identifier import (  # noqa: F401
    _AFFILIATION_TAGS,
    _is_bad_issuer_name,
    _is_bdc_aggregate_row,
    _parse_bdc_identifier,
)
```

| Symbol | Imported by |
|---|---|
| `_AFFILIATION_TAGS` | `test_unified_holdings.py` |
| `_is_bad_issuer_name` | `test_unified_holdings.py` |
| `_is_bdc_aggregate_row` | `test_unified_holdings.py` |
| `_parse_bdc_identifier` | `test_unified_holdings.py` |

### Post-extraction size of `unified_holdings.py`: ~1,820 lines (down from 3,720)

### Verification

- If SQL strings were captured in Phase 0, generated SQL strings match the Phase 0 baseline
- `pytest --collect-only tests/` confirms the current collected test suite
- `pytest tests/` passes
- `python scripts/rebuild_outputs.py && python scripts/diff_outputs.py` - byte-identical

---

## Phase 3: Decompose `unified_holdings.py` Staging Functions

**Goal:** Extract the two per-source staging pipelines into dedicated modules, leaving `unified_holdings.py` as a lean conformance + gold orchestrator.

### Note on structural impact

Moving `_prepare_bdc()` (810 lines) and `_prepare_nport()` (299 lines) to separate files is the largest single code movement. These functions are the main consumers of the SQL generators extracted in Phase 1 -- they will need imports from both `classification.py` and `bdc_identifier.py`. Note that `_prepare_bdc()` is a single massive function, not a set of smaller functions. Moving it to its own file improves navigability across the codebase but does not change the function's internal complexity.

### New: `pipeline/staging_bdc.py` (~850 lines)

**Moves from `unified_holdings.py`:**

- `_prepare_bdc` (804 lines) - the massive DuckDB CTE chain
- `_reclassify_named_fund_positions` (55 lines) - called at end of BDC prep

Both functions now import classification SQL generators from `pipeline/classification.py` and aggregate constants from `pipeline/bdc_identifier.py`.

### New: `pipeline/staging_nport.py` (~350 lines)

**Moves from `unified_holdings.py`:**

- `_prepare_nport` (299 lines) - DuckDB CTE chain for N-PORT

Imports classification functions from `pipeline/classification.py`.

### What remains in `unified_holdings.py` (~620 lines)

This is now the **conformance + gold orchestrator**:

- `UNIFIED_COLUMNS` - output schema
- `_CORRECTABLE_FIELDS`, `_CORRECTIONS_REQUIRED_COLS` - correction constants
- `build_unified_holdings` (354 lines) - orchestrator: calls `staging_bdc._prepare_bdc()`, `staging_nport._prepare_nport()`, does UNION ALL + cross-source dedup + classification computation + cost proxy + shares normalization, then gold steps
- `_stabilize_classification` (84 lines) - QoQ stabilization
- `_correct_pct_of_net_assets` (153 lines) - pct correction using fund_financials
- `_apply_row_corrections` (111 lines) - manual override application
- `_enforce_schema` (116 lines) - 13 validation checks
- `_log_summary` (51 lines) - summary statistics
- Re-export shim block for backward compatibility

### Re-export shim

**3 symbols** need re-export shims in this phase:

```python
# Re-exports for backward compatibility -- Phase 3
from pipeline.staging_bdc import (  # noqa: F401
    _prepare_bdc,
    _reclassify_named_fund_positions,
)
from pipeline.staging_nport import _prepare_nport  # noqa: F401
```

| Symbol | Imported by |
|---|---|
| `_prepare_bdc` | `test_unified_holdings.py` |
| `_prepare_nport` | `test_unified_holdings.py` |
| `_reclassify_named_fund_positions` | `test_unified_holdings.py` |

### Verification

- If SQL strings were captured in Phase 0, generated SQL strings match the Phase 0 baseline
- `pytest --collect-only tests/` confirms the current collected test suite
- `pytest tests/` passes
- `python scripts/rebuild_outputs.py && python scripts/diff_outputs.py` - byte-identical

---

## Phase 4: Decompose `fund_financials.py` (deferrable)

**Goal:** Separate per-source extraction from cross-source conformance.

**Priority note:** This phase has the weakest cost/benefit ratio of the `unified_holdings` phases. `fund_financials.py` has only 3 importers total (test file, main.py, rebuild_outputs.py). The extraction helpers it splits out have no external consumers beyond `test_fund_financials.py`. If bandwidth is constrained, this phase can be deferred or dropped without affecting the rest of the plan. Phases 0-3 deliver 90% of the value.

### New: `pipeline/extract_companyfacts.py` (~400 lines)

**Moves from `fund_financials.py`:**

- All concept constant dicts: `_BALANCE_SHEET_CONCEPTS`, `_DISTRIBUTION_CONCEPTS`, `_PERFORMANCE_CONCEPTS`, `_INCOME_CONCEPTS`, `_PORTFOLIO_CONCEPTS`, `_EXTENDED_FIELDS`
- `_extract_duration_series` (112 lines) - YTD-to-quarterly conversion
- `_extract_concept_series` (60 lines) - best-matching concept extraction
- `_extract_bdc_balance_sheet` (64 lines) - per-CIK extraction
- `_extract_all_companyfacts` (55 lines) - batch extraction across all BDCs

### New: `pipeline/extract_ncen.py` (~250 lines)

**Moves from `fund_financials.py`:**

- `_parse_ncen_date` (13 lines) - date parser
- `_parse_ncen_financials` (214 lines) - fixed-position table extraction from N-CEN ZIP
- `_parse_ncen_identity` (170 lines) - adviser/ticker extraction

### What remains in `fund_financials.py` (~1,100 lines, down from 2,414)

This is the **conformance + gold layer**:

- `OUTPUT_COLUMNS` - schema constant
- `_months_between`, `_prior_quarter_end` - utility helpers (stay; used by conformance logic)
- `_prepare_nport` (486 lines) - N-PORT + N-CEN + N-CSR conformance (stays because it joins 3 sources)
- `_prepare_bdc` (368 lines) - companyfacts + income conformance (stays because it joins 2 sources)
- `_prepare_ncen` (47 lines) - N-CEN standalone rows
- `_enforce_schema` (83 lines) - validation
- `_fill_computed_returns` (88 lines) - NAV waterfall
- `build_fund_financials` (308 lines) - orchestrator (now imports extraction functions)

`_prepare_nport` and `_prepare_bdc` stay in `fund_financials.py` because they perform cross-source conformance (joining multiple extracted sources together).

### Re-export shim

**8 symbols** need re-export shims in this phase:

```python
# Re-exports for backward compatibility -- Phase 4
from pipeline.extract_companyfacts import (  # noqa: F401
    _EXTENDED_FIELDS,
    _extract_all_companyfacts,
    _extract_bdc_balance_sheet,
    _extract_concept_series,
    _extract_duration_series,
)
from pipeline.extract_ncen import (  # noqa: F401
    _parse_ncen_date,
    _parse_ncen_financials,
    _parse_ncen_identity,
)
```

| Symbol | Imported by |
|---|---|
| `_EXTENDED_FIELDS` | `test_fund_financials.py` |
| `_extract_all_companyfacts` | `test_fund_financials.py` |
| `_extract_bdc_balance_sheet` | `test_fund_financials.py` |
| `_extract_concept_series` | `test_fund_financials.py` |
| `_extract_duration_series` | `test_fund_financials.py` |
| `_parse_ncen_date` | `test_fund_financials.py` |
| `_parse_ncen_financials` | `test_fund_financials.py` |
| `_parse_ncen_identity` | `test_fund_financials.py` |

### Patched config constants

`test_fund_financials.py` also patches path/config constants on `pipeline.fund_financials`, including `COMPANYFACTS_CACHE_DIR`, `SEC_DATASETS_DIR`, `NCEN_QUARTERS`, and `FUND_IDENTITY_FILE`. Moving extraction functions to `extract_companyfacts.py` or `extract_ncen.py` can break those tests if the moved functions read constants from the new modules while tests still patch the old module.

Phase 4 must choose one explicit compatibility mechanism:

1. **Preferred for structural parity:** keep thin wrapper functions in `pipeline.fund_financials` for the moved extractors during Phases 4-6. The wrappers pass the currently patched `pipeline.fund_financials` constants into implementation functions in the new modules.
2. **Alternative:** migrate the affected tests in the same Phase 4 commit to patch `pipeline.extract_companyfacts` and `pipeline.extract_ncen` constants directly, then do not claim old patch paths remain compatible.

Do not simply re-export moved functions if those functions close over new-module constants. That preserves import names but changes monkeypatch behavior.

### Verification

- `pytest --collect-only tests/` confirms the current collected test suite
- `pytest tests/test_fund_financials.py` passes for the current collected test suite
- `python scripts/rebuild_outputs.py && python scripts/diff_outputs.py` - byte-identical

---

## Phase 5: Split `export_frontend.py` Into Sub-Modules (deferrable)

**Goal:** Break the 3,514-line export file into domain-focused sub-modules. This is a structural split only. No logic changes, no removal of re-derived classification; that is a semantic change for later.

**Priority note:** This phase has the weakest cost/benefit ratio overall. `export_frontend.py` has **zero test coupling** -- only `export_all()` and `FRONTEND_DATA_DIR` are imported externally. The split creates 4 new files and an `__init__.py` without delivering the classification deduplication that motivates it (that is deferred to a future semantic refactor). If bandwidth is constrained, defer this phase.

**DuckDB connection threading is a non-issue.** The existing code already passes `con: duckdb.DuckDBPyConnection` as a parameter to every export function. Sub-modules just accept the same parameter -- no design change needed.

### New: `pipeline/export/` package

Create `pipeline/export/__init__.py` that re-exports `export_all` for backward compatibility.

### New: `pipeline/export/index_exports.py` (~600 lines)

Index-level JSON exports:

- `_export_index_returns`, `_export_index_summary`
- `_export_top_constituents`, `_export_sector_breakdown`
- `_export_vehicle_contribution`
- `_export_portfolio_characteristics`
- `_export_metadata`

### New: `pipeline/export/fund_exports.py` (~750 lines)

Fund-level JSON exports:

- `_export_fund_list`, `_export_fund_summary`
- `_compute_fund_exposure` (319 lines), `_compute_fund_top_holdings`
- `_export_fund_details`

### New: `pipeline/export/analytics_exports.py` (~900 lines)

Analytics, concentration, and visualization exports:

- `_export_manager_concentration`, `_export_vehicle_concentration`, `_export_investee_concentration`
- `_export_concentration_curve`, `_export_position_concentration`
- `_export_data_quality` (647 lines)
- `_export_credit_risk`, `_export_distribution_histogram`, `_export_leverage_histogram`
- `_compute_brackets`, `_ranked_query`

### New: `pipeline/export/timeseries_exports.py` (~350 lines)

Time-series and sector exports:

- `_export_fund_index_returns`, `_export_aum_time_series`
- `_export_gics_sector_breakdown`, `_export_industry_breakdown`

### Remains in `pipeline/export_frontend.py` (~300 lines, acts as orchestrator)

- `export_all()` - imports and calls all sub-module functions
- Shared helpers: `_write_json`, `_write_bytes_retry`, `_quarter_to_date`, `_prev_quarter`, `_safe_round`, `_build_recon_hist`, `_valid_positions_sql`, `_exclude_consumer_lending_sql`, `_quarter_cutoff_sql`, `_top_n_with_other`
- Module constants: `FRONTEND_DATA_DIR`, `CONSUMER_LENDING_EXCLUDE_CIKS`, `INDEX_ORDER`, `_STD_EDGES`, `_STD_LABELS`

Alternatively, the shared helpers can move to `pipeline/export/helpers.py` and the orchestrator to `pipeline/export/__init__.py`, with `export_frontend.py` becoming a thin re-export wrapper. Either approach works. The key is the domain split.

If helpers move to `pipeline/export/helpers.py`, move shared constants there too when they are used by multiple export modules, especially `FRONTEND_DATA_DIR`. Keep a compatibility shim in `pipeline.export_frontend` for `export_all`, shared helpers, and constants currently imported by tests, scripts, or operators.

### Re-export shim

**0 symbols** need re-export shims. Only `export_all` and `FRONTEND_DATA_DIR` are imported externally (`pipeline/main.py`, `scripts/rebuild_outputs.py`), and both stay in `export_frontend.py`.

### Verification

- Frontend JSON output unchanged: `python scripts/rebuild_outputs.py && python scripts/diff_outputs.py`
- `npm run build` in `frontend/` succeeds (static export still works)

---

## Do Not Mix Semantic Cleanup

The structural split must not change data semantics. Do not bundle any of the following into Phases 1-5:

- Deduplicating or replacing duplicated frontend classification logic with `pipeline.classification` imports
- Editing generated frontend JSON directly
- Changing data-quality rules, filters, exclusions, validation thresholds, or classification keywords
- Adding or removing unified output columns

Those changes may be worthwhile, but they need separate evidence, tests, source reconciliation, and validation review. Byte-identical artifact parity is the acceptance criterion for this refactor.

---

## Phase 6: Compatibility Cleanup

**Goal:** Remove compatibility shims only after every structural phase has proven byte-identical parity.

### Scope

Across all prior phases, **26 re-export shims** were added:

| Phase | Module | Shim count |
|---|---|---|
| Phase 1 | `unified_holdings.py` -> `classification.py` | 11 |
| Phase 2 | `unified_holdings.py` -> `bdc_identifier.py` | 4 |
| Phase 3 | `unified_holdings.py` -> `staging_bdc.py` / `staging_nport.py` | 3 |
| Phase 4 | `fund_financials.py` -> `extract_companyfacts.py` / `extract_ncen.py` | 8 |
| **Total** | | **26** |

Phase 6 migrates these 26 import paths across the following consumer files, then removes the shim blocks:

| Consumer file | Symbols to migrate | New import source(s) |
|---|---|---|
| `test_unified_holdings.py` | 18 | `pipeline.classification` (11), `pipeline.bdc_identifier` (4), `pipeline.staging_bdc` (2), `pipeline.staging_nport` (1) |
| `test_fund_financials.py` | 8 | `pipeline.extract_companyfacts` (5), `pipeline.extract_ncen` (3) |
| `pipeline/llm_review.py` | 2 | `pipeline.classification` (2: `_classify_bdc_issuer`, `_classify_index`) |

Symbols that stay in their original module (no migration needed):

| Symbol | Stays in | Imported by |
|---|---|---|
| `UNIFIED_COLUMNS` | `unified_holdings.py` | 8 files (tests, pipeline modules) |
| `build_unified_holdings` | `unified_holdings.py` | `test_unified_holdings.py`, `main.py`, `rebuild_outputs.py` |
| `_apply_row_corrections` | `unified_holdings.py` | `test_unified_holdings.py` |
| `_CORRECTABLE_FIELDS` | `unified_holdings.py` | `test_unified_holdings.py` |
| `_correct_pct_of_net_assets` | `unified_holdings.py` | `test_unified_holdings.py` |
| `_enforce_schema` | `unified_holdings.py` | `test_unified_holdings.py` |
| `_stabilize_classification` | `unified_holdings.py` | `test_unified_holdings.py` |
| `OUTPUT_COLUMNS` | `fund_financials.py` | `test_fund_financials.py` |
| `build_fund_financials` | `fund_financials.py` | `test_fund_financials.py`, `main.py`, `rebuild_outputs.py` |
| `_enforce_schema` (ff) | `fund_financials.py` | `test_fund_financials.py` |
| `_months_between` | `fund_financials.py` | `test_fund_financials.py` |
| `_prepare_bdc` (ff) | `fund_financials.py` | `test_fund_financials.py` |
| `_prepare_ncen` | `fund_financials.py` | `test_fund_financials.py` |
| `_prepare_nport` (ff) | `fund_financials.py` | `test_fund_financials.py` |
| `_prior_quarter_end` | `fund_financials.py` | `test_fund_financials.py` |
| `export_all` | `export_frontend.py` | `main.py`, `rebuild_outputs.py` |
| `FRONTEND_DATA_DIR` | `export_frontend.py` | `main.py` |

### 6a: Update test imports (remove re-export shims)

Once all phases are verified and artifact parity is proven, update test files to import from the new module locations:

| Test file | Current import source | New import source |
|---|---|---|
| `test_unified_holdings.py` | `pipeline.unified_holdings` | `pipeline.classification`, `pipeline.bdc_identifier`, `pipeline.staging_bdc`, `pipeline.staging_nport` |
| `test_fund_financials.py` | `pipeline.fund_financials` | `pipeline.extract_companyfacts`, `pipeline.extract_ncen` (for extraction tests) |

Then update `pipeline/llm_review.py` to import from `pipeline.classification`.

Then remove the re-export shim blocks from `unified_holdings.py` and `fund_financials.py`.

### 6b: Verify final state

- `pytest --collect-only tests/` confirms the current collected test suite
- `pytest tests/` passes with updated imports
- `python scripts/rebuild_outputs.py && python scripts/diff_outputs.py` - byte-identical
- No re-export shims remain
- Each module has a single clear responsibility

---

## Separate Cleanup Task: Temporary Files

Temporary-file deletion is deliberately not part of the structural refactor. Delete `_tmp_*.py` / `tmp_*.py` / `temp_*.py` and related scratch artifacts only in a separate PR/task after byte-identical parity is proven.

Candidate deletion patterns for that later cleanup: `_tmp_*.py`, `tmp_*.py`, `temp_*.py`, `_tmp_*.txt`, `_tmp_*.b64`, `dataoutputval_*.txt`.

---

## Summary: New Module Map

| Module | Responsibility | Lines |
|---|---|---|
| `pipeline/classification.py` | Classification constants, SQL generators, Python classifiers | ~1,400 |
| `pipeline/bdc_identifier.py` | BDC identifier parsing, aggregate detection, affiliation patterns | ~500 |
| `pipeline/staging_bdc.py` | BDC per-source cleanup, filtering, column mapping | ~850 |
| `pipeline/staging_nport.py` | N-PORT per-source cleanup, filtering, column mapping | ~350 |
| `pipeline/extract_companyfacts.py` | XBRL concept extraction from companyfacts cache | ~400 |
| `pipeline/extract_ncen.py` | N-CEN financial highlights and identity extraction | ~250 |
| `pipeline/unified_holdings.py` | Cross-source conformance, dedup, corrections, schema enforcement | ~620 |
| `pipeline/fund_financials.py` | Multi-source conformance, computed returns, schema enforcement | ~1,100 |
| `pipeline/export/` | 4 sub-modules by domain (index, fund, analytics, timeseries) | ~2,600 |
| `pipeline/export_frontend.py` | Orchestrator + shared helpers | ~300 |

### Line count changes

| File | Before | After | Delta |
|---|---|---|---|
| `unified_holdings.py` | 3,720 | ~620 | -3,100 |
| `fund_financials.py` | 2,414 | ~1,100 | -1,314 |
| `export_frontend.py` | 3,514 | ~300 | -3,214 |
| **New modules** | 0 | ~6,350 | +6,350 |
| **Net new lines** | | | ~0 (pure decomposition) |

---

## Execution Order and Dependencies

```text
Prerequisites (commit dirty working tree)
  |
  v
Phase 0 (safety net + SQL string baseline)
  |
  v
Phase 1 (classification.py)  -- highest leverage, highest risk
  |                              11 re-export shims
  v
Phase 2 (bdc_identifier.py)  -- depends on Phase 1
  |                              4 re-export shims
  v
Phase 3 (staging_bdc.py, staging_nport.py)  -- largest code movement
  |                                            3 re-export shims
  v
Phase 4 (extract_companyfacts.py, extract_ncen.py)  -- deferrable
  |                                                     8 re-export shims
  v
Phase 5 (export/ sub-modules)  -- deferrable, 0 re-export shims
  |
  v
Phase 6 (compatibility cleanup)  -- 26 import path migrations
  |                                  across 3 consumer files
  v
Separate cleanup task (temporary files)
```

Phases 1-3 are sequential because each enables the next. Phases 4 and 5 are independent of each other and could be done in either order; both can be deferred if bandwidth is constrained -- Phases 0-3 deliver 90% of the value (decomposing the 3,720-line `unified_holdings.py`). Temporary-file deletion is intentionally separated from the refactor so cleanup cannot obscure artifact parity review.

---

## What This Plan Does NOT Do

These are **semantic changes** to be done in a separate pass after the structural refactor:

- Add `lien_position` or `rate_type` columns to unified_holdings.csv (would eliminate re-derivation in export_frontend)
- Replace export_frontend's inline CASE WHEN chains with classification.py imports (logic may differ subtly)
- Create a shared DuckDB context manager (nice-to-have, not structural)
- Add CI/CD (GitHub Actions, linting) - separate effort
- Adopt dbt or any new tooling - separate decision
- Adopt layered data architecture (strict layer boundaries, DAG runner, schema contracts, lineage tracking) - this refactoring is a prerequisite for that work, not a substitute for it
