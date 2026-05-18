# Refactor Phase 6: Compatibility Cleanup (Amended)

## Summary

Remove the compatibility shims left by refactor phases 1-5 after migrating every known consumer to the new module locations. This phase is structural only: no data logic, schema, threshold, output, or frontend behavior changes.

---

## Current State (Pre-Phase 6)

### Re-export shim block in `pipeline/unified_holdings.py` (lines 82-109)

12 symbols re-exported from `pipeline.classification`:

| # | Symbol | Consumed by test/runtime? |
|---|---|---|
| 1 | `_INDUSTRY_LABELS` | `test_unified_holdings.py` |
| 2 | `_classify_bdc_asset` | `test_unified_holdings.py` |
| 3 | `_classify_bdc_issuer` | `test_unified_holdings.py`, `pipeline/llm_review.py` |
| 4 | `_classify_index` | `test_unified_holdings.py`, `pipeline/llm_review.py` |
| 5 | `_classify_nport_asset` | `test_unified_holdings.py` |
| 6 | `_classify_nport_issuer` | `test_unified_holdings.py` |
| 7 | `_infer_coupon_type` | `test_unified_holdings.py` |
| 8 | `_is_named_coinvest` | `test_unified_holdings.py` |
| 9 | `_normalize_rate` | `test_unified_holdings.py` |
| 10 | `_sql_classify_asset_class` | `test_unified_holdings.py` |
| 11 | `_sql_classify_exposure_type` | `test_unified_holdings.py` |
| 12 | `_sql_classify_index` | (no external consumer -- only used internally via `build_unified_holdings` SQL; shim is vestigial) |

4 symbols re-exported from `pipeline.bdc_identifier`:

| # | Symbol | Consumed by |
|---|---|---|
| 13 | `_AFFILIATION_TAGS` | `test_unified_holdings.py` |
| 14 | `_is_bad_issuer_name` | `test_unified_holdings.py` |
| 15 | `_is_bdc_aggregate_row` | `test_unified_holdings.py` |
| 16 | `_parse_bdc_identifier` | `test_unified_holdings.py` |

2 symbols re-exported from `pipeline.staging_bdc`:

| # | Symbol | Consumed by |
|---|---|---|
| 17 | `_prepare_bdc` | `test_unified_holdings.py` |
| 18 | `_reclassify_named_fund_positions` | `test_unified_holdings.py` |

1 symbol re-exported from `pipeline.staging_nport`:

| # | Symbol | Consumed by |
|---|---|---|
| 19 | `_prepare_nport` | `test_unified_holdings.py` |

### Compatibility wrappers in `pipeline/fund_financials.py` (lines 99-706)

Phase 4 used **thin wrappers** (not `# noqa: F401` re-exports). Each wrapper passes config constants from `pipeline.fund_financials`'s module namespace into the extracted module's implementation function. This is the "preferred for structural parity" approach from the refactoring plan.

**Companyfacts wrappers (lines 103-176):**

| Symbol | Wrapper delegates to | Config constants injected |
|---|---|---|
| `_EXTENDED_FIELDS` | `extract_companyfacts._EXTENDED_FIELDS` (alias) | -- |
| `_load_companyfacts_cached` | `extract_companyfacts._load_companyfacts_cached(cik, companyfacts_cache_dir=COMPANYFACTS_CACHE_DIR)` | `COMPANYFACTS_CACHE_DIR` |
| `_extract_duration_series` | `extract_companyfacts._extract_duration_series(facts, concept_names, unit_key)` | -- |
| `_extract_concept_series` | `extract_companyfacts._extract_concept_series(facts, concept_names, unit_key, instant_only)` | -- |
| `_extract_bdc_balance_sheet` | `extract_companyfacts._extract_bdc_balance_sheet(cik, facts)` | -- |
| `_extract_all_companyfacts` | `extract_companyfacts._extract_all_companyfacts(bdc_ciks, client=client, companyfacts_cache_dir=COMPANYFACTS_CACHE_DIR)` | `COMPANYFACTS_CACHE_DIR` |

**N-CEN wrappers (lines 682-706):**

| Symbol | Wrapper delegates to | Config constants injected |
|---|---|---|
| `_NCEN_DATE_MONTHS` | `extract_ncen._NCEN_DATE_MONTHS` (alias) | -- |
| `_parse_ncen_date` | `extract_ncen._parse_ncen_date(raw)` | -- |
| `_parse_ncen_financials` | `extract_ncen._parse_ncen_financials(universe_ciks, sec_datasets_dir=SEC_DATASETS_DIR, ncen_quarters=NCEN_QUARTERS)` | `SEC_DATASETS_DIR`, `NCEN_QUARTERS` |
| `_parse_ncen_identity` | `extract_ncen._parse_ncen_identity(universe_ciks, sec_datasets_dir=SEC_DATASETS_DIR, ncen_quarters=NCEN_QUARTERS, fund_identity_file=FUND_IDENTITY_FILE)` | `SEC_DATASETS_DIR`, `NCEN_QUARTERS`, `FUND_IDENTITY_FILE` |

**Symbols that truly belong in `fund_financials.py` (NOT wrappers, NOT migrating):**

- `_months_between`, `_prior_quarter_end` -- local re-implementations used by conformance logic
- `OUTPUT_COLUMNS`, `build_fund_financials`, `_enforce_schema`, `_prepare_bdc`, `_prepare_nport`, `_prepare_ncen`, `_fill_computed_returns`
- `_EXTENDED_FIELDS` is consumed extensively by `_prepare_bdc` (lines 350, 778, 788, 833, 835, 883, 891, 901, 924) as a local constant reference -- the wrapper alias `_EXTENDED_FIELDS = extract_companyfacts._EXTENDED_FIELDS` is needed by `fund_financials.py` itself, not just tests

### Dynamic import specs in scripts

`scripts/diff_outputs.py` lines 19-24 and `scripts/snapshot_outputs.py` lines 95-99 use `importlib`-style dynamic lookups:

```python
SQL_SPECS = [
    ("classification_index.sql", "pipeline.unified_holdings", "_sql_classify_index"),
    ("classification_exposure_type.sql", "pipeline.unified_holdings", "_sql_classify_exposure_type"),
    ("classification_asset_class.sql", "pipeline.unified_holdings", "_sql_classify_asset_class"),
    ("bdc_aggregate.sql", "pipeline.unified_holdings", "_sql_is_bdc_aggregate"),
]
```

These resolve via `__import__(module_name, fromlist=[func_name])` and `getattr(module, func_name)()`. After shim removal, they must point to canonical module locations.

---

## Implementation Changes

### 6a. Update `tests/test_unified_holdings.py` imports

Replace the single import block (lines 24-50):

```python
# BEFORE
from pipeline.unified_holdings import (
    _AFFILIATION_TAGS,
    _apply_row_corrections,
    _classify_bdc_asset,
    _classify_bdc_issuer,
    _classify_index,
    _classify_nport_asset,
    _classify_nport_issuer,
    _CORRECTABLE_FIELDS,
    _correct_pct_of_net_assets,
    _enforce_schema,
    _infer_coupon_type,
    _INDUSTRY_LABELS,
    _is_bad_issuer_name,
    _is_bdc_aggregate_row,
    _is_named_coinvest,
    _normalize_rate,
    _parse_bdc_identifier,
    _prepare_bdc,
    _prepare_nport,
    _reclassify_named_fund_positions,
    _sql_classify_exposure_type,
    _sql_classify_asset_class,
    _stabilize_classification,
    build_unified_holdings,
    UNIFIED_COLUMNS,
)
```

With split imports by canonical location:

```python
# AFTER
from pipeline.classification import (
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
from pipeline.bdc_identifier import (
    _AFFILIATION_TAGS,
    _is_bad_issuer_name,
    _is_bdc_aggregate_row,
    _parse_bdc_identifier,
)
from pipeline.staging_bdc import (
    _prepare_bdc,
    _reclassify_named_fund_positions,
)
from pipeline.staging_nport import _prepare_nport
from pipeline.unified_holdings import (
    _apply_row_corrections,
    _CORRECTABLE_FIELDS,
    _correct_pct_of_net_assets,
    _enforce_schema,
    _stabilize_classification,
    build_unified_holdings,
    UNIFIED_COLUMNS,
)
```

Also check for the late import at line 2493:
```python
from pipeline.unified_holdings import _prepare_bdc
```
Change to:
```python
from pipeline.staging_bdc import _prepare_bdc
```

### 6b. Update `tests/test_fund_financials.py` imports

Replace the import block (lines 6-23):

```python
# BEFORE
from pipeline.fund_financials import (
    OUTPUT_COLUMNS,
    _EXTENDED_FIELDS,
    _enforce_schema,
    _extract_all_companyfacts,
    _extract_bdc_balance_sheet,
    _extract_concept_series,
    _extract_duration_series,
    _months_between,
    _parse_ncen_date,
    _parse_ncen_financials,
    _parse_ncen_identity,
    _prepare_bdc,
    _prepare_ncen,
    _prepare_nport,
    _prior_quarter_end,
    build_fund_financials,
)
```

With split imports:

```python
# AFTER
from pipeline.extract_companyfacts import (
    _EXTENDED_FIELDS,
    _extract_all_companyfacts,
    _extract_bdc_balance_sheet,
    _extract_concept_series,
    _extract_duration_series,
)
from pipeline.extract_ncen import (
    _parse_ncen_date,
    _parse_ncen_financials,
    _parse_ncen_identity,
)
from pipeline.fund_financials import (
    OUTPUT_COLUMNS,
    _enforce_schema,
    _months_between,
    _prepare_bdc,
    _prepare_ncen,
    _prepare_nport,
    _prior_quarter_end,
    build_fund_financials,
)
```

**Monkeypatch migration** -- the test's `monkeypatch.setattr` targets must change:

| Current patch target | New patch target | Reason |
|---|---|---|
| `"pipeline.fund_financials.COMPANYFACTS_CACHE_DIR"` | `"pipeline.extract_companyfacts.COMPANYFACTS_CACHE_DIR"` | `_extract_all_companyfacts` reads `companyfacts_cache_dir` default from `extract_companyfacts` module |
| `"pipeline.fund_financials.SEC_DATASETS_DIR"` | `"pipeline.extract_ncen.SEC_DATASETS_DIR"` | `_parse_ncen_financials` reads default from `extract_ncen` module |
| `"pipeline.fund_financials.NCEN_QUARTERS"` | `"pipeline.extract_ncen.NCEN_QUARTERS"` | same |
| `"pipeline.fund_financials.FUND_IDENTITY_FILE"` | `"pipeline.extract_ncen.FUND_IDENTITY_FILE"` | `_parse_ncen_identity` reads default from `extract_ncen` module |

**Keep unchanged:**

| Patch target | Why it stays |
|---|---|
| `"pipeline.fund_financials.FUND_FINANCIALS_FILE"` | Tests the orchestrator output path (belongs to `fund_financials.py`) |
| `"pipeline.fund_financials.BDC_FUND_INCOME_FILE"` | Orchestrator output path |
| `"pipeline.fund_financials.FUND_IDENTITY_FILE"` | Only if also used by `build_fund_financials` directly (verify) |

**Verification detail:** The extracted functions use keyword arguments with defaults from their own module namespace:
- `_extract_all_companyfacts(bdc_ciks, client=None, companyfacts_cache_dir=COMPANYFACTS_CACHE_DIR)` -- the default is bound at function definition time from `extract_companyfacts.COMPANYFACTS_CACHE_DIR`
- `_parse_ncen_financials(universe_ciks, sec_datasets_dir=SEC_DATASETS_DIR, ncen_quarters=NCEN_QUARTERS)` -- defaults from `extract_ncen`

Since Python default arguments are evaluated at definition time, monkeypatching the module-level constant after import has **no effect on the default**. The tests must either:
1. Patch the constant **before** the function is imported (not practical with pytest), OR
2. Call the function with explicit keyword arguments instead of relying on defaults

Option 2 is the correct approach. Where tests currently rely on monkeypatched defaults, update them to pass the tmp_path explicitly:

```python
# BEFORE
monkeypatch.setattr("pipeline.fund_financials.COMPANYFACTS_CACHE_DIR", tmp_path / "cf")
result = _extract_all_companyfacts(["123"], client=None)

# AFTER
result = _extract_all_companyfacts(["123"], client=None, companyfacts_cache_dir=tmp_path / "cf")
```

**However** -- re-check whether the wrapper approach in Phase 4 was specifically designed to avoid this problem. The wrappers in `fund_financials.py` read `COMPANYFACTS_CACHE_DIR` at call time (not at definition time) because they explicitly pass `companyfacts_cache_dir=COMPANYFACTS_CACHE_DIR` inside the function body. When tests patched `pipeline.fund_financials.COMPANYFACTS_CACHE_DIR`, the wrapper's body would read the patched value at call time. **This is why the wrapper approach was chosen.**

After removing wrappers and importing directly from `extract_companyfacts`, the tests must pass explicit arguments OR patch `pipeline.extract_companyfacts.COMPANYFACTS_CACHE_DIR` (which works because the extracted functions also read the default at call time via `companyfacts_cache_dir=COMPANYFACTS_CACHE_DIR` as a keyword default -- **wait, no, defaults are bound at definition time**).

**Resolution:** Examine the actual function signatures in the extracted modules:

```python
# extract_companyfacts.py line 16:
def _load_companyfacts_cached(cik: str, companyfacts_cache_dir=COMPANYFACTS_CACHE_DIR) -> dict:

# extract_companyfacts.py _extract_all_companyfacts:
def _extract_all_companyfacts(bdc_ciks, client=None, companyfacts_cache_dir=COMPANYFACTS_CACHE_DIR):

# extract_ncen.py line 37:
def _parse_ncen_financials(universe_ciks, sec_datasets_dir=SEC_DATASETS_DIR, ncen_quarters=NCEN_QUARTERS):
```

These defaults ARE bound at definition time. Monkeypatching `extract_companyfacts.COMPANYFACTS_CACHE_DIR` after the module is imported does NOT change the default. The correct migration is: **pass explicit path arguments in tests**:

```python
result = _extract_all_companyfacts(["123"], client=None, companyfacts_cache_dir=tmp_path / "cf")
ncen_df = _parse_ncen_financials(ciks, sec_datasets_dir=tmp_path / "sec", ncen_quarters=["2024q4"])
```

### 6c. Update `pipeline/llm_review.py`

Line 436 (inside function body, lazy import):

```python
# BEFORE
from pipeline.unified_holdings import _classify_bdc_issuer, _classify_index

# AFTER
from pipeline.classification import _classify_bdc_issuer, _classify_index
```

### 6d. Update `scripts/diff_outputs.py` SQL_SPECS

Lines 19-24:

```python
# BEFORE
SQL_SPECS = [
    ("classification_index.sql", "pipeline.unified_holdings", "_sql_classify_index"),
    ("classification_exposure_type.sql", "pipeline.unified_holdings", "_sql_classify_exposure_type"),
    ("classification_asset_class.sql", "pipeline.unified_holdings", "_sql_classify_asset_class"),
    ("bdc_aggregate.sql", "pipeline.unified_holdings", "_sql_is_bdc_aggregate"),
]

# AFTER
SQL_SPECS = [
    ("classification_index.sql", "pipeline.classification", "_sql_classify_index"),
    ("classification_exposure_type.sql", "pipeline.classification", "_sql_classify_exposure_type"),
    ("classification_asset_class.sql", "pipeline.classification", "_sql_classify_asset_class"),
    ("bdc_aggregate.sql", "pipeline.bdc_identifier", "_sql_is_bdc_aggregate"),
]
```

### 6e. Update `scripts/snapshot_outputs.py` SQL specs

Lines 95-99 (identical structure):

```python
# BEFORE
    specs = [
        ("classification_index.sql", "pipeline.unified_holdings", "_sql_classify_index"),
        ("classification_exposure_type.sql", "pipeline.unified_holdings", "_sql_classify_exposure_type"),
        ("classification_asset_class.sql", "pipeline.unified_holdings", "_sql_classify_asset_class"),
        ("bdc_aggregate.sql", "pipeline.unified_holdings", "_sql_is_bdc_aggregate"),
    ]

# AFTER
    specs = [
        ("classification_index.sql", "pipeline.classification", "_sql_classify_index"),
        ("classification_exposure_type.sql", "pipeline.classification", "_sql_classify_exposure_type"),
        ("classification_asset_class.sql", "pipeline.classification", "_sql_classify_asset_class"),
        ("bdc_aggregate.sql", "pipeline.bdc_identifier", "_sql_is_bdc_aggregate"),
    ]
```

### 6f. Remove shim block from `pipeline/unified_holdings.py`

Delete lines 82-109 entirely (the 19-symbol re-export block). The internal call sites in `unified_holdings.py` (specifically `build_unified_holdings`) already import from the canonical modules via the module-level `from pipeline.staging_bdc import _prepare_bdc` etc. -- **verify this**. If `build_unified_holdings` calls `_prepare_bdc()` relying on the shim import rather than a separate internal import, add an explicit internal import first.

**Verify before deletion:** Grep `unified_holdings.py` for calls to `_prepare_bdc(`, `_prepare_nport(`, `_sql_classify_index(`, etc. to confirm they use the `staging_bdc.` / `classification.` module prefix or have separate non-shim imports.

### 6g. Remove wrapper functions from `pipeline/fund_financials.py`

Delete the following wrapper blocks:

- Lines 99-176: Companyfacts compatibility wrappers (`_load_companyfacts_cached`, `_extract_duration_series`, `_extract_concept_series`, `_extract_bdc_balance_sheet`, `_extract_all_companyfacts`)
- Lines 680-706: N-CEN compatibility wrappers (`_NCEN_DATE_MONTHS`, `_parse_ncen_date`, `_parse_ncen_financials`, `_parse_ncen_identity`)

**Keep the `_EXTENDED_FIELDS` alias** (line 103: `_EXTENDED_FIELDS = extract_companyfacts._EXTENDED_FIELDS`) because it is consumed extensively by `_prepare_bdc` and other internal conformance logic (lines 350, 778, 788, 833, 835, 883, 891, 901, 924). It is not a backward-compat shim -- it is a module-internal constant reference.

**Update internal call sites** in `build_fund_financials()` (around line 1385):

```python
# BEFORE (calls wrapper)
cf_balance_df = _extract_all_companyfacts(bdc_ciks, client)
ncen_raw_df = _parse_ncen_financials(universe_ciks)
_parse_ncen_identity(universe_ciks)

# AFTER (calls extracted module directly, passing config)
cf_balance_df = extract_companyfacts._extract_all_companyfacts(
    bdc_ciks, client=client, companyfacts_cache_dir=COMPANYFACTS_CACHE_DIR
)
ncen_raw_df = extract_ncen._parse_ncen_financials(
    universe_ciks, sec_datasets_dir=SEC_DATASETS_DIR, ncen_quarters=NCEN_QUARTERS
)
extract_ncen._parse_ncen_identity(
    universe_ciks, sec_datasets_dir=SEC_DATASETS_DIR,
    ncen_quarters=NCEN_QUARTERS, fund_identity_file=FUND_IDENTITY_FILE
)
```

---

## Symbols That Stay (No Migration)

| Symbol | Stays in | Reason |
|---|---|---|
| `UNIFIED_COLUMNS` | `unified_holdings.py` | Output schema constant |
| `build_unified_holdings` | `unified_holdings.py` | Orchestrator |
| `_apply_row_corrections` | `unified_holdings.py` | Gold-layer function |
| `_CORRECTABLE_FIELDS` | `unified_holdings.py` | Gold-layer constant |
| `_correct_pct_of_net_assets` | `unified_holdings.py` | Conformance function |
| `_enforce_schema` | `unified_holdings.py` | Validation function |
| `_stabilize_classification` | `unified_holdings.py` | Conformance function |
| `OUTPUT_COLUMNS` | `fund_financials.py` | Output schema constant |
| `build_fund_financials` | `fund_financials.py` | Orchestrator |
| `_enforce_schema` (ff) | `fund_financials.py` | Validation function |
| `_months_between` | `fund_financials.py` | Utility used by conformance logic |
| `_prior_quarter_end` | `fund_financials.py` | Utility used by conformance logic |
| `_prepare_bdc` (ff) | `fund_financials.py` | Cross-source conformance |
| `_prepare_ncen` | `fund_financials.py` | Standalone N-CEN rows |
| `_prepare_nport` (ff) | `fund_financials.py` | Cross-source conformance |
| `_EXTENDED_FIELDS` | `fund_financials.py` (alias) | Used by 9+ internal SQL builders |
| `export_all` | `export_frontend.py` | Orchestrator entry point |
| `FRONTEND_DATA_DIR` | `export_frontend.py` (or `export/helpers.py`) | External consumers |

---

## Test Plan

### Step 1: Verify collection (catch import errors immediately)

```
pytest --collect-only tests/
```

This catches `ImportError` / `ModuleNotFoundError` from any broken import path before running expensive tests.

### Step 2: Targeted tests (fast feedback on migrated files)

```
pytest tests/test_unified_holdings.py tests/test_fund_financials.py tests/test_llm_review.py -x
```

### Step 3: Verify scripts still resolve SQL specs

```
python scripts/diff_outputs.py --help
python scripts/snapshot_outputs.py --help
```

(Both scripts import and call the SQL generators at runtime. `--help` won't execute the SQL path, so also run:)

```
python -c "import sys; sys.path.insert(0,'.'); exec(open('scripts/diff_outputs.py').read().split('def ')[0])"
```

Or simply run the full diff (Step 5) which exercises both.

### Step 4: Full test suite

```
pytest tests/
```

### Step 5: Output parity verification

```
python scripts/rebuild_outputs.py
python scripts/diff_outputs.py
```

Both must exit 0 with byte-identical outputs.

### Step 6: Confirm no shims remain

Search for residual compatibility artifacts:

```
grep -rn "noqa: F401" pipeline/unified_holdings.py pipeline/fund_financials.py
grep -rn "Re-exports" pipeline/unified_holdings.py pipeline/fund_financials.py
grep -rn "compatibility" pipeline/unified_holdings.py pipeline/fund_financials.py
grep -rn "from pipeline.unified_holdings import _classify\|from pipeline.unified_holdings import _parse\|from pipeline.unified_holdings import _is_\|from pipeline.unified_holdings import _prepare\|from pipeline.unified_holdings import _sql" tests/ pipeline/ scripts/
grep -rn "from pipeline.fund_financials import _extract\|from pipeline.fund_financials import _parse_ncen" tests/ pipeline/ scripts/
```

All should return zero matches.

---

## Risk Mitigations

| Risk | Mitigation |
|---|---|
| Default argument binding (monkeypatch ineffective) | Pass explicit keyword args in tests instead of patching module constants |
| `build_unified_holdings` calls shimmed names | Verify internal call sites use module-prefixed calls before shim deletion |
| `_EXTENDED_FIELDS` removal breaks 9+ SQL builders | Keep as module-level alias; it's internal, not a compat shim |
| `_sql_classify_index` only used internally | Remove from shim block but verify `build_unified_holdings` imports it from `classification` directly or calls it via module reference |
| Script SQL_SPECS use `__import__` (fragile) | Update both `diff_outputs.py` and `snapshot_outputs.py` in the same commit |
| Late import in `llm_review.py` | Same mechanics as top-level; just change the module path string |

---

## Execution Order

Within this single Phase 6 commit:

1. Update `tests/test_unified_holdings.py` imports (6a)
2. Update `tests/test_fund_financials.py` imports + monkeypatch targets (6b)
3. Update `pipeline/llm_review.py` import (6c)
4. Update `scripts/diff_outputs.py` SQL_SPECS (6d)
5. Update `scripts/snapshot_outputs.py` SQL specs (6e)
6. Verify `unified_holdings.py` internal call sites use module-prefixed calls
7. Remove shim block from `unified_holdings.py` (6f)
8. Update `fund_financials.py` internal call sites to use `extract_companyfacts.` / `extract_ncen.` directly
9. Remove wrapper functions from `fund_financials.py` (6g)
10. Run test plan (Steps 1-6)

---

## Out of Scope

- No changes to classification logic, thresholds, or keywords
- No changes to output schemas or column sets
- No changes to frontend JSON structure
- No temporary file cleanup (separate task per refactoring plan)
- No `export_frontend.py` changes (Phase 5 had 0 re-export shims)
