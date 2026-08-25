# Provenance Step-1 Passthroughs Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the scoping doc's "cheap passthroughs" as one schema batch: merged-context audit carry-through (`src_context_count`, `src_conflict_fields`), pipeline transform recording (`src_transforms` events for the rate/pct rescale heuristic, PIK boundary fix, cost proxy, shares pow-10 fix), Class-C pathway enums (`cost_source`, `shares_held_source`), and HTML-bridge coordinate refs (`src_field_overrides`) — populated by a single `--unified` rebuild, no re-extraction.

**Architecture:** Six new `UNIFIED_COLUMNS` entries added in one commit (avoiding repeated ~45-min rebuild+gate cycles). Staging Phase C emits the dedup carry-throughs and the transform-event string (event CASEs colocated with the value CASEs, kept in sync by boundary tests rather than codegen); the Phase C PIK-boundary CTE and the unified `with_cost`/`with_shares_fix` CTEs append their events; the bridge overlay writes coordinate refs. All values land on rebuild from existing data — the extractor and bdc_holdings.csv are untouched.

**Tech Stack:** Python 3.x, pandas, DuckDB, pytest. No new dependencies.

**Spec:** `docs/provenance_columns_scoping.md` sections 1.1, 2.3, 2.4 (items 1, 4, 5) and section 6 step 1. Decisions from the 2026-08-22 owner conversation:
- One batch, one rebuild, one gate pass.
- `src_transforms` is a flat `;`-joined ordered list of `field:code` events — the step-1 precursor that folds into `src_facts` when the extractor migration adds instance-raw values. NOT JSON yet: without raw values a JSON payload has nothing else to carry, and a flat tag list is directly SQL-filterable.
- Event vocabulary (versioned in schemas.md): `rate_x100`, `rate_div100`, `neg_null` (on `interest_rate`/`basis_spread`/`pik_rate`), `rate_x100`/`rate_div100` on `pct_of_net_assets`, `pik_boundary_div100`, `cost_proxy_fv`, `pow10_shares`.
- `cost_source`/`shares_held_source`: `''` (as-extracted) | `'derived_proxy'` (Class-C fill fired) — extends the existing 4-field `*_source` enum pattern.
- `src_field_overrides`: `;`-joined `field=bridge:<html_sha256[:8]>:t<table_index>:r<row_index>`.
- OUT of scope (recorded): identifier-text parse-rule ids (grammar layer), extractor-side `src_facts` raw values (needs re-extraction — separate plan), `corrected_fields` (pre-dirty apply-layer files), the re-verifier.
- Measurement by-product: `src_transforms` makes the `<=0.50 / >=50` threshold heuristic's fire-rate measurable against the rate-convention gold set for the first time.

## Global Constraints

(from AGENTS.md)
- ASCII-only logs; no inline `python -`; no `.apply()`/`.iterrows()` on large frames (the bridge overlay's existing small `iterrows` over matched bridge rows is the one sanctioned exception — bridge entries are dozens, not thousands).
- Pytest write-guard active; rebuilds outside pytest.
- **Dirty-worktree rule:** stage only named files; never `git add -A`/`-u`.
- **Sequencing:** the operator phase (Task 5) must NOT start until the source-reconciliation anchor migration (SRC-5) gates are closed — one data migration through the gates at a time. Note: the Task-5 unified rebuild changes holdings hashes, so the next reconciliation run will mark CIKs dirty and re-run; that is now safe (published reconciliation ids are order-independent anchors) but expect the runtime.
- Commit style: short subject + 2-4 bullets.

## File Structure

| File | Change | Task |
|---|---|---|
| `pipeline/unified_holdings.py` | 6 new `UNIFIED_COLUMNS` entries; `with_cost`/`with_shares_fix` event recording | 1, 3 |
| `pipeline/staging_bdc.py` | `_optional_cols` + Phase C emissions; transform-event expression; PIK-boundary CTE append | 1, 2 |
| `pipeline/staging_nport.py` | `''` emissions for all 6 | 1 |
| `pipeline/bdc_xbrl_html_bridge.py` | overlay writes `src_field_overrides` refs | 4 |
| `tests/test_unified_holdings.py` | passthrough + event tests | 1, 2, 3 |
| `tests/test_bdc_xbrl_html_bridge_fields.py` | override-ref assertions | 4 |
| `docs/reference/schemas.md`, `docs/agent_changelog.md` | event vocabulary + entry | 5 |

---

### Task 1: Schema batch — 6 columns through staging (dedup carry-throughs live, rest empty)

**Files:**
- Modify: `pipeline/unified_holdings.py` (`UNIFIED_COLUMNS`, after `"src_context_id",`)
- Modify: `pipeline/staging_bdc.py` (`_optional_cols` ~:410; Phase C SELECT after the `src_context_id` line ~:2588)
- Modify: `pipeline/staging_nport.py` (after `'' AS src_context_id,` ~:299)
- Test: `tests/test_unified_holdings.py` (append to `TestPrepareBdc` next to `test_src_context_id_passes_through_bdc_staging`)

**Interfaces:**
- Consumes: `dedupe_context_count`/`dedupe_conflict_fields` already present in bdc_holdings.csv (written by `_deduplicate_bdc_holdings` since the dedup audit shipped).
- Produces: `UNIFIED_COLUMNS` order (insert after `"src_context_id"`): `"src_context_count", "src_conflict_fields", "src_transforms", "src_field_overrides", "cost_source", "shares_held_source"`. Tasks 2-4 populate `src_transforms`/`src_field_overrides`/the two enums; this task leaves them `''`.

- [ ] **Step 1: Write the failing tests**

Append to `TestPrepareBdc` in `tests/test_unified_holdings.py`:

```python
    def test_dedup_audit_columns_pass_through(self):
        df = self._make_bdc_df([
            {"investment_identifier": "Acme Corp - Term Loan", "cik": "123",
             "fair_value": 1000000, "dedupe_context_count": "3",
             "dedupe_conflict_fields": "cost"},
        ])
        result = _prepare_bdc(df)
        assert list(result["src_context_count"]) == ["3"]
        assert list(result["src_conflict_fields"]) == ["cost"]

    def test_dedup_audit_columns_default_empty(self):
        df = self._make_bdc_df([
            {"investment_identifier": "Acme Corp - Term Loan", "cik": "123",
             "fair_value": 1000000},
        ])
        result = _prepare_bdc(df)
        assert list(result["src_context_count"]) == [""]
        assert list(result["src_conflict_fields"]) == [""]
        # the batch's other columns exist and default empty at this stage
        for col in ("src_field_overrides", "cost_source", "shares_held_source"):
            assert list(result[col]) == [""]
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_unified_holdings.py -k dedup_audit_columns -v`
Expected: FAIL — `KeyError: 'src_context_count'`.

- [ ] **Step 3: Implement (four edits)**

3a. `unified_holdings.py` — in `UNIFIED_COLUMNS`, after `"src_context_id",` insert:

```python
    "src_context_count",
    "src_conflict_fields",
    "src_transforms",
    "src_field_overrides",
    "cost_source",
    "shares_held_source",
```

3b. `staging_bdc.py` `_optional_cols` — append `"dedupe_context_count", "dedupe_conflict_fields",` (keeps pre-audit bdc_holdings CSVs readable).

3c. `staging_bdc.py` Phase C SELECT — after `COALESCE(CAST(src_context_id AS VARCHAR), '') AS src_context_id,` add:

```sql
            COALESCE(CAST(dedupe_context_count AS VARCHAR), '') AS src_context_count,
            COALESCE(CAST(dedupe_conflict_fields AS VARCHAR), '') AS src_conflict_fields,
            '' AS src_transforms,
            '' AS src_field_overrides,
            '' AS cost_source,
            '' AS shares_held_source,
```

(`src_transforms` becomes a real expression in Task 2 — emitting `''` first keeps this task shippable alone.)

3d. `staging_nport.py` — after `'' AS src_context_id,` add:

```sql
            '' AS src_context_count,
            '' AS src_conflict_fields,
            '' AS src_transforms,
            '' AS src_field_overrides,
            '' AS cost_source,
            '' AS shares_held_source,
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_unified_holdings.py -k "dedup_audit_columns or src_context_id" -v`
Expected: PASS. Then `python -m pytest tests/test_row_id.py tests/test_source_recon_anchor_ids.py -q` (schema neighbors) — PASS.

- [ ] **Step 5: Commit**

```bash
git add pipeline/unified_holdings.py pipeline/staging_bdc.py pipeline/staging_nport.py tests/test_unified_holdings.py
git commit -m "provenance step 1: six-column schema batch through staging

- src_context_count/src_conflict_fields carry the dedup audit into unified
- src_transforms/src_field_overrides/cost_source/shares_held_source added
  empty; populated by the transform-recording and bridge tasks
- one schema change -> one rebuild for the whole step-1 batch"
```

---

### Task 2: Transform events in staging Phase C (rescale branches + PIK boundary)

**Files:**
- Modify: `pipeline/staging_bdc.py` (Phase C: replace `'' AS src_transforms,` with the event expression; extend the `unified_pik_fixed` CTE ~:2659-2667)
- Test: `tests/test_unified_holdings.py`

**Interfaces:**
- Consumes: the `_ir`/`_bs`/`_pik`/`_pct` staging intermediates whose value CASEs live at ~:2442-2513; the `unified_pik_fixed` CTE.
- Produces: `src_transforms` populated with `;`-joined events in field order `interest_rate, basis_spread, pik_rate, pct_of_net_assets` plus appended `pik_rate:pik_boundary_div100`. Sync contract: an event fires IFF the corresponding value branch fired — enforced by the boundary tests below.

- [ ] **Step 1: Write the failing boundary-sync tests**

Append to `TestPrepareBdc`:

```python
    def test_src_transforms_records_rate_rescale_branches(self):
        df = self._make_bdc_df([
            # <=0.50 -> x100 branch
            {"investment_identifier": "A Corp - TL", "cik": "123",
             "fair_value": 1, "interest_rate": 0.105},
            # >=50 -> /100 branch
            {"investment_identifier": "B Corp - TL", "cik": "123",
             "fair_value": 1, "interest_rate": 62.5},
            # identity: no event
            {"investment_identifier": "C Corp - TL", "cik": "123",
             "fair_value": 1, "interest_rate": 10.5},
            # negative -> nulled
            {"investment_identifier": "D Corp - TL", "cik": "123",
             "fair_value": 1, "interest_rate": -1.0},
        ])
        result = _prepare_bdc(df).set_index("issuer_name")
        assert result.loc["A Corp", "interest_rate"] == 10.5
        assert "interest_rate:rate_x100" in result.loc["A Corp", "src_transforms"]
        assert result.loc["B Corp", "interest_rate"] == 0.625
        assert "interest_rate:rate_div100" in result.loc["B Corp", "src_transforms"]
        assert "interest_rate" not in result.loc["C Corp", "src_transforms"]
        assert pd.isna(result.loc["D Corp", "interest_rate"])
        assert "interest_rate:neg_null" in result.loc["D Corp", "src_transforms"]

    def test_src_transforms_records_pct_branches_with_pct_thresholds(self):
        # pct uses > 50 (strict), rates use >= 50 -- events must match values
        df = self._make_bdc_df([
            {"investment_identifier": "E Corp - TL", "cik": "123",
             "fair_value": 1, "pct_of_net_assets": 0.004},
            {"investment_identifier": "F Corp - TL", "cik": "123",
             "fair_value": 1, "pct_of_net_assets": 50.0},  # boundary: NO event
        ])
        result = _prepare_bdc(df).set_index("issuer_name")
        assert "pct_of_net_assets:rate_x100" in result.loc["E Corp", "src_transforms"]
        assert "pct_of_net_assets" not in result.loc["F Corp", "src_transforms"]

    def test_src_transforms_records_pik_boundary_fix(self):
        # CTE 12a: pik 20-50 exceeding interest_rate was bps -> /100 + event
        df = self._make_bdc_df([
            {"investment_identifier": "G Corp - TL", "cik": "123",
             "fair_value": 1, "interest_rate": 10.0, "pik_rate": 25.0},
        ])
        result = _prepare_bdc(df)
        assert result.iloc[0]["pik_rate"] == 0.25
        assert "pik_rate:pik_boundary_div100" in result.iloc[0]["src_transforms"]
```

NOTE: raw fixture rates are DECIMAL-scale inputs; check what `_ir` sees (the `*100` harmonization may occur before these CASEs — if `interest_rate: 0.105` arrives at the CASE as something else, adjust fixture inputs so each branch demonstrably fires, asserting on the published value to prove which branch ran).

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_unified_holdings.py -k src_transforms -v`
Expected: FAIL — `src_transforms` is `''`.

- [ ] **Step 3: Implement**

3a. Replace `'' AS src_transforms,` in the Phase C SELECT with (colocated with the value CASEs; branch conditions copied verbatim — pct uses `> 50`, rates use `>= 50`):

```sql
            concat_ws(';',
                CASE WHEN _ir IS NOT NULL AND _ir < 0 THEN 'interest_rate:neg_null'
                     WHEN _ir IS NOT NULL AND _ir <= 0.50 THEN 'interest_rate:rate_x100'
                     WHEN _ir IS NOT NULL AND _ir >= 50 THEN 'interest_rate:rate_div100'
                     ELSE NULL END,
                CASE WHEN _bs IS NOT NULL AND _bs < 0 THEN 'basis_spread:neg_null'
                     WHEN _bs IS NOT NULL AND _bs <= 0.50 THEN 'basis_spread:rate_x100'
                     WHEN _bs IS NOT NULL AND _bs >= 50 THEN 'basis_spread:rate_div100'
                     ELSE NULL END,
                CASE WHEN _pik IS NOT NULL AND _pik < 0 THEN 'pik_rate:neg_null'
                     WHEN _pik IS NOT NULL AND _pik <= 0.50 THEN 'pik_rate:rate_x100'
                     WHEN _pik IS NOT NULL AND _pik >= 50 THEN 'pik_rate:rate_div100'
                     ELSE NULL END,
                CASE WHEN _pct IS NOT NULL AND _pct <= 0.50 THEN 'pct_of_net_assets:rate_x100'
                     WHEN _pct IS NOT NULL AND _pct > 50 THEN 'pct_of_net_assets:rate_div100'
                     ELSE NULL END
            ) AS src_transforms,
```

3b. Extend `unified_pik_fixed` (CTE 12a) to append its event — the CTE condition duplicated for value and event:

```sql
    unified_pik_fixed AS (
        SELECT * EXCLUDE (pik_rate, src_transforms),
            CASE WHEN pik_rate >= 20
                  AND interest_rate IS NOT NULL
                  AND pik_rate > interest_rate
                 THEN pik_rate / 100
                 ELSE pik_rate END AS pik_rate,
            CASE WHEN pik_rate >= 20
                  AND interest_rate IS NOT NULL
                  AND pik_rate > interest_rate
                 THEN concat_ws(';', NULLIF(src_transforms, ''),
                                'pik_rate:pik_boundary_div100')
                 ELSE src_transforms END AS src_transforms
        FROM unified
    ),
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_unified_holdings.py -k src_transforms -v` then the whole `TestPrepareBdc` class.
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add pipeline/staging_bdc.py tests/test_unified_holdings.py
git commit -m "provenance step 1: record rescale-branch events in src_transforms

- which rate_x100/rate_div100/neg_null branch fired per field, plus the
  CTE-12a pik boundary /100 -- first measurable dataset for the threshold
  heuristic's error rate (scoping doc 2.3)
- event CASEs colocated with value CASEs; boundary tests enforce sync"
```

---

### Task 3: Class-C events in unified CTEs (`cost_proxy_fv`, `pow10_shares`)

**Files:**
- Modify: `pipeline/unified_holdings.py` (`with_cost` ~:1038-1063, `with_shares_fix` ~:1068-1100)
- Test: `tests/test_unified_holdings.py` (extend the existing cost-proxy and shares-normalization test groups — copy their fixture style)

**Interfaces:**
- Consumes: `cost_source`/`shares_held_source`/`src_transforms` columns (present from staging, Task 1).
- Produces: when the cost proxy fills a NULL/0 cost: `cost_source='derived_proxy'` + `cost:cost_proxy_fv` appended to `src_transforms`. When the shares pow-10 fix fires (`_is_outlier`): `shares_held_source='derived_proxy'` + `shares_held:pow10_shares` appended.

- [ ] **Step 1: Write the failing tests**

Locate the existing cost-proxy tests (`rg "cost_proxy|with_cost" tests/test_unified_holdings.py`) and shares tests (`rg "shares_fix|power.of.10|pow10" tests/test_unified_holdings.py`); add alongside, reusing their fixtures:

```python
    def test_cost_proxy_fill_records_derived_proxy(self):
        # reuse the nearest existing cost-proxy fixture: a position with
        # cost=0 in q1 and fair_value present -> proxy fill fires
        ...  # build via the same helper the neighboring test uses
        assert row["cost_source"] == "derived_proxy"
        assert "cost:cost_proxy_fv" in row["src_transforms"]

    def test_unproxied_cost_keeps_empty_source(self):
        ...  # position with real cost
        assert row["cost_source"] == ""
        assert "cost:" not in row["src_transforms"]

    def test_shares_pow10_fix_records_derived_proxy(self):
        ...  # reuse the existing 400 vs 400000 shares fixture
        assert fixed_row["shares_held_source"] == "derived_proxy"
        assert "shares_held:pow10_shares" in fixed_row["src_transforms"]
```

(The `...` bodies are fixture reuse, not design gaps: copy the arrange/act code of the adjacent passing test verbatim and add these assertions — the neighboring tests already construct exactly the firing/non-firing scenarios.)

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_unified_holdings.py -k "derived_proxy or pow10" -v`
Expected: FAIL — sources are `''`.

- [ ] **Step 3: Implement**

3a. `with_cost`: restructure so the fired-condition is computable once — inner subquery materializes original and proxy, outer publishes value + flags:

```sql
    with_cost AS (
        SELECT * EXCLUDE (cost, cost_source, src_transforms, _cost_orig, _cost_proxy),
            COALESCE(_cost_orig, _cost_proxy) AS cost,
            CASE WHEN _cost_orig IS NULL AND _cost_proxy IS NOT NULL
                 THEN 'derived_proxy' ELSE cost_source END AS cost_source,
            CASE WHEN _cost_orig IS NULL AND _cost_proxy IS NOT NULL
                 THEN concat_ws(';', NULLIF(src_transforms, ''), 'cost:cost_proxy_fv')
                 ELSE src_transforms END AS src_transforms
        FROM (
            SELECT *,
                NULLIF(TRY_CAST(cost AS DOUBLE), 0) AS _cost_orig,
                FIRST_VALUE(
                    NULLIF(TRY_CAST(fair_value AS DOUBLE), 0)
                    IGNORE NULLS
                ) OVER (
                    -- window copied VERBATIM from the current with_cost CTE
                    PARTITION BY cik, issuer_name,
                        regexp_replace(
                            lower(trim(COALESCE(CAST(instrument_description AS VARCHAR), ''))),
                            '[^a-z0-9]+', ' ', 'g'
                        ),
                        COALESCE(NULLIF(CAST(cusip AS VARCHAR), ''), '')
                    ORDER BY
                        report_date,
                        fair_value,
                        COALESCE(CAST(accession_number AS VARCHAR), ''),
                        COALESCE(CAST(bdc_investment_identifier AS VARCHAR), ''),
                        COALESCE(CAST(nport_holding_id AS VARCHAR), ''),
                        COALESCE(CAST(shares_held AS VARCHAR), '')
                    ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING
                ) AS _cost_proxy
            FROM classified
        )
    ),
```

3b. `with_shares_fix`: the outer SELECT already has `_is_outlier` in scope from its inner subquery. Extend the outer EXCLUDE to also cover `shares_held_source, src_transforms` and add:

```sql
            CASE WHEN _is_outlier THEN 'derived_proxy'
                 ELSE shares_held_source END AS shares_held_source,
            CASE WHEN _is_outlier
                 THEN concat_ws(';', NULLIF(src_transforms, ''), 'shares_held:pow10_shares')
                 ELSE src_transforms END AS src_transforms
```

(Keep the existing shares_held CASE byte-identical; mirror however the CTE currently drops its `_sh_val`/`_is_outlier` helpers downstream.)

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_unified_holdings.py -k "derived_proxy or pow10 or cost_proxy or shares" -v`
Expected: new tests PASS, existing cost/shares tests still PASS (values unchanged — only flags added).

- [ ] **Step 5: Commit**

```bash
git add pipeline/unified_holdings.py tests/test_unified_holdings.py
git commit -m "provenance step 1: Class-C derivation events in unified CTEs

- cost proxy fill and shares pow-10 fix flip cost_source/shares_held_source
  to derived_proxy and append events to src_transforms
- values byte-identical; derived rows are now excludable from any
  verified-FV numerator (scoping doc accounting rule)"
```

---

### Task 4: Bridge overlay coordinate refs in `src_field_overrides`

**Files:**
- Modify: `pipeline/bdc_xbrl_html_bridge.py:513-575` (`apply_html_section_bridge_field_overlays`)
- Test: `tests/test_bdc_xbrl_html_bridge_fields.py`

**Interfaces:**
- Consumes: bridge rows carry `html_sha256`, `table_index`, `row_index` (BRIDGE_TABLE_COLUMNS :40-43); overlay already stamps `*_source='html_section_bridge'`.
- Produces: for each overlaid field, `src_field_overrides` gains `field=bridge:<sha8>:t<T>:r<R>` (`;`-joined across fields).

- [ ] **Step 1: Write the failing test**

Extend the existing overlay test in `tests/test_bdc_xbrl_html_bridge_fields.py` (the one at ~:89 that overlays via `tmp_path` bridge_dir; its bridge fixture must include `html_sha256`/`table_index`/`row_index` values — extend the fixture JSON if it omits them):

```python
def test_overlay_records_src_field_override_ref(tmp_path):
    # arrange identical to test at :89 (copy), with bridge record carrying
    # html_sha256="a1b2c3d4e5f6...", table_index=2, row_index=15
    out = apply_html_section_bridge_field_overlays(
        df, identifier_col="bdc_investment_identifier", bridge_dir=tmp_path)
    ref = out.iloc[0]["src_field_overrides"]
    assert "maturity_date=bridge:a1b2c3d4:t2:r15" in ref
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_bdc_xbrl_html_bridge_fields.py -v`
Expected: new test FAILS (`src_field_overrides` missing or empty); existing tests PASS.

- [ ] **Step 3: Implement**

In `apply_html_section_bridge_field_overlays`:

3a. After the defensive column loop (:537-540) add `"src_field_overrides"` to the ensured columns.

3b. Add `"html_sha256", "table_index", "row_index"` to the `bridges[[...]]` merge column list (:552-555).

3c. Add a helper inside the function and call it in both overlay branches:

```python
    def _append_override(idx: Any, field: str, row: Any) -> None:
        sha8 = _norm_text(row.get("html_sha256"))[:8]
        ref = (f"{field}=bridge:{sha8}"
               f":t{int(row.get('table_index', -1))}"
               f":r{int(row.get('row_index', -1))}")
        prev = str(result.at[idx, "src_field_overrides"] or "").strip()
        result.at[idx, "src_field_overrides"] = f"{prev};{ref}" if prev else ref
```

In the maturity branch (after `result.at[idx, "maturity_date_source"] = ...`): `_append_override(idx, "maturity_date", row)`. In the reference-rate branch: `_append_override(idx, "reference_rate_type", row)`.

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_bdc_xbrl_html_bridge_fields.py -q`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add pipeline/bdc_xbrl_html_bridge.py tests/test_bdc_xbrl_html_bridge_fields.py
git commit -m "provenance step 1: bridge overlay records coordinate refs

- src_field_overrides gains field=bridge:<sha8>:t<T>:r<R> per overlaid
  field, closing the scoping doc 1.1 gap (bridge-sourced values were
  indistinguishable from XBRL-sourced ones on the published row)"
```

---

### Task 5: Operator phase — rebuild, gates, docs (AFTER SRC-5 closes)

Precondition: SRC-5 (source-reconciliation anchor migration) gates are closed and its changelog entry written. Do not interleave.

- [ ] **Step 1: Snapshot + rebuild**

```powershell
Get-Process | Where-Object { $_.ProcessName -match 'python|pytest' } | Select-Object Id, ProcessName
New-Item -ItemType Directory -Force data\snapshots\pre_prov_step1_20260822 | Out-Null
Copy-Item data\output\private_markets_holdings.csv data\snapshots\pre_prov_step1_20260822\
python scripts\rebuild_outputs.py --unified
```

- [ ] **Step 2: GATE — values identical, only new columns + expected flags**

Adapt `scratch/2026-08-22_anchor_rowid/unified_drift_gate.py` (point OLD at `data/snapshots/pre_prov_step1_20260822/`): identical row count, total FV, per-classification, per-cik-quarter. Additionally verify `cost` and `shares_held` sums are IDENTICAL (the CTE restructures must not move values) and `row_id` values unchanged for `src_anchor`-basis rows (anchors don't depend on the new columns).

- [ ] **Step 3: Coverage stats (record in changelog)**

DuckDB over the parquet companion: counts of rows with each `src_transforms` event code, `cost_source`/`shares_held_source='derived_proxy'` counts (compare to known baselines: shares fix historically ~1,902 rows), `src_context_count > 1` count, `src_field_overrides != ''` count.

- [ ] **Step 4: Full suite + backstop**

```powershell
python -m pytest --durations=50 --durations-min=0.5 -q
python scripts\diff_outputs.py --semantic
```

Expected: green; semantic deltas remain the documented pre-existing set.

- [ ] **Step 5: Docs + commit**

- `docs/reference/schemas.md`: document the six columns and the `src_transforms` event vocabulary as v1 (upgrade path: folds into `src_facts` at the extractor migration).
- `docs/agent_changelog.md`: entry with gate results, coverage stats, test counts.

```bash
git add docs/reference/schemas.md docs/agent_changelog.md docs/superpowers/plans/2026-08-22-provenance-step1-passthroughs.md
git commit -m "docs: provenance step-1 passthrough record

- six columns documented with src_transforms event vocabulary v1
- rebuild gate results and coverage stats in changelog"
```

---

## Self-Review Notes

- Spec coverage: scoping 2.4 #4 (context count + conflict fields) → Task 1; 2.3 transform table rows that fire pipeline-side (`rate_x100/rate_div100`, pik boundary, `cost_proxy_fv`, `pow10_shares`) → Tasks 2-3; 2.4 #5 (`src_field_overrides`) → Task 4; 2.4 #1 partially (enum extension for the two Class-C fields; full per-field enum extension deferred to the extractor migration); section 6 step 1 complete.
- Deliberate deviations from the scoping doc, with reasons: flat `src_transforms` instead of `src_facts` JSON (no raw values to carry yet; avoids committing a JSON schema before the extractor fields exist); `decimals_rescale` and identifier-text parse-rule recording deferred (extractor/grammar side).
- Known risks encoded: event/value CASE sync enforced by boundary tests (incl. the pct `>50` vs rate `>=50` asymmetry); `with_cost` restructure guarded by a cost-sum identity gate in Task 5; sequencing barrier against SRC-5.
- Type consistency: all six columns str; event grammar `field:code`; override grammar `field=bridge:<sha8>:t<T>:r<R>` — consistent across Tasks 2-5 and the schemas.md vocabulary.
