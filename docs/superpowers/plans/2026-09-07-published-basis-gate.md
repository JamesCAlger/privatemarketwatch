# Published-Basis Gate Implementation Plan (Plan 2 of 2)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every fair-value gate sum exactly the rows the public headline sums, make anchors declare what they include, add the over-inclusion and unfinished-investigation gates (thresholds v3), re-test quarter-scoped rules on new quarters, and prove on Q1 2026 that the gate now sees the $4.09B.

**Architecture:** One shared numerator (`pipeline/published_basis.py`) replaces four private copies and the GAV ex-subsidiary numerator. The conservation engine's anchor list gains a basis per anchor and a deterministic "companyfacts + tagged cash equivalents" candidate; anchor leaves gain a required `basis`. The acceptance contract reads two new metrics from artifacts agents cannot edit. Rollout is rebuild -> battery -> acceptance on Q1 and Q4 with the expected Q1 FAIL recorded, not remediated.

**Tech Stack:** Python 3.11, DuckDB SQL for the engine and GAV, pandas on per-CIK frames only, pytest. Cache-only rebuilds via `scripts/rebuild_outputs.py`.

**Spec:** `docs/superpowers/specs/2026-09-07-published-basis-conservation-gate-design.md` (sections 1, 2, 3, 4c, 4d, 5, 6). Plan 1 (`2026-09-07-gate-mechanics-fixes.md`) must be complete first: Task 9 here depends on `investigations.n_stale` and Task 10 on the `rows_skipped_duplicate` / drift plumbing.

## Global Constraints

- ASCII only in logs, docstrings, comments (Windows cp1252).
- No `.apply()` / `.iterrows()` on large frames. The engine and GAV stay in DuckDB SQL; pandas only on one CIK's rows or on summary frames.
- No network. Rebuilds use cached inputs only (`scripts/rebuild_outputs.py --financials`, `--unified`).
- Tests never write to `data/output/` or `frontend/public/data/` (conftest guard).
- Numerator definition, verbatim from the spec and used in every implementation: `published_fv(cik, quarter) = SUM(fair_value)` over all unified rows with that 10-digit `cik` and `report_date`, no category, dimension, or subsidiary filter.
- Anchor `basis` enum: `published_rows`, `investments_ex_cash`. Nothing else validates.
- Band stays `config.FV_CONSERVATION_BAND_PCT = 0.5`.
- Commit message format: subject + 2-4 bullets + the two attribution lines
  `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>` and
  `Claude-Session: https://claude.ai/code/session_012y9HXDTAq1SHqB5GKmjmc1`.
- Do not run the full pytest suite until Task 12; before it, check for other pytest/rebuild processes (`Get-Process python`).
- Do not refresh `data/snapshots/baseline/`. Do not edit `AGENTS.md`.

**Deviations from the spec, decided here (report them in the changelog):**
1. Anchor priority is `verified_override(published_rows)` > `verified_override(investments_ex_cash)` > `companyfacts_fv_plus_cash` > `companyfacts_fv` > `schedule_total`. The spec listed the ex-cash override below plain companyfacts; an override exists precisely because companyfacts was partial, so it must outrank it.
2. The ledger does not gain a new column. The 13-column ledger contract is asserted on every engine fragment; instead the conservation fragment writes `anchor_used || ':' || anchor_basis` into the existing, previously NULL `mechanism` column. Acceptance splits it on `:`.

---

### Task 1: `pipeline/published_basis.py` — one numerator, two implementations, one parity test

**Files:**
- Create: `pipeline/published_basis.py`
- Test: `tests/test_published_basis.py` (new)

**Interfaces:**
- Produces: `published_fv_sum_sql(table_expr: str, where: str = "TRUE") -> str` returning a SELECT with columns `cik` (10-digit VARCHAR), `report_date` (VARCHAR, first 10 chars), `value_sum` (DOUBLE), `n_rows` (BIGINT), grouped by cik/report_date, restricted to `where`.
- Produces: `published_fv_by_quarter(df: pd.DataFrame) -> dict[str, float]` for a single-CIK frame; keys are `report_date` strings (first 10 chars).
- Produces: `published_fv_mask(df: pd.DataFrame) -> pd.Series` (all-True boolean mask of the frame's index; exists so callers that need a mask, such as `agent_b2_diagnose._gate_rows`, have one named place).
- Consumed by: Tasks 2, 3, 7.

- [ ] **Step 1: Write the failing test**

Create `tests/test_published_basis.py`:

```python
"""The published basis: one numerator for the headline and every FV gate (spec section 1)."""
import duckdb
import pandas as pd

from pipeline.published_basis import (
    published_fv_by_quarter, published_fv_mask, published_fv_sum_sql,
)


def _frame():
    # cash, subsidiary, added (no accession), unpadded cik, NULL dims, comparative period:
    # ALL of them count. Only a NULL fair_value contributes nothing.
    return pd.DataFrame([
        {"cik": "0001899017", "report_date": "2026-03-31", "fair_value": 1815.0,
         "bdc_dimensions_raw": "x=y", "asset_category": "LOAN", "is_subsidiary": 0},
        {"cik": "0001899017", "report_date": "2026-03-31", "fair_value": 406.5,
         "bdc_dimensions_raw": "nonconsolidatedsubsidiaryaxis=SLP", "asset_category": "LOAN",
         "is_subsidiary": 1},
        {"cik": "0001899017", "report_date": "2026-03-31", "fair_value": 20.0,
         "bdc_dimensions_raw": "cashandcashequivalentsaxis=MMF", "asset_category": "CASH",
         "is_subsidiary": None},
        {"cik": "1899017", "report_date": "2026-03-31", "fair_value": 5.0,
         "bdc_dimensions_raw": None, "asset_category": "LOAN", "is_subsidiary": 0},
        {"cik": "0001899017", "report_date": "2026-03-31 00:00:00", "fair_value": None,
         "bdc_dimensions_raw": "x=y", "asset_category": "LOAN", "is_subsidiary": 0},
        {"cik": "0001899017", "report_date": "2025-12-31", "fair_value": 1630.1,
         "bdc_dimensions_raw": "x=y", "asset_category": "LOAN", "is_subsidiary": 0},
    ])


def test_sql_and_pandas_agree_and_include_everything():
    df = _frame()
    con = duckdb.connect()
    con.register("u", df)
    rows = con.execute(published_fv_sum_sql("u")).fetchall()
    got = {(c, d): (v, n) for c, d, v, n in rows}
    assert got == {("0001899017", "2026-03-31"): (2246.5, 5),
                   ("0001899017", "2025-12-31"): (1630.1, 1)}
    assert published_fv_by_quarter(df) == {"2026-03-31": 2246.5, "2025-12-31": 1630.1}


def test_sql_where_and_timestamp_report_date():
    df = _frame()
    con = duckdb.connect()
    con.register("u", df)
    rows = con.execute(published_fv_sum_sql("u", "report_date LIKE '2025%'")).fetchall()
    assert rows == [("0001899017", "2025-12-31", 1630.1, 1)]


def test_mask_is_all_true_and_empty_frames():
    df = _frame()
    assert published_fv_mask(df).all() and len(published_fv_mask(df)) == len(df)
    assert published_fv_by_quarter(pd.DataFrame()) == {}
    assert published_fv_by_quarter(pd.DataFrame({"cik": []})) == {}
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/test_published_basis.py -v`
Expected: ImportError (module missing).

- [ ] **Step 3: Implement**

Create `pipeline/published_basis.py`:

```python
"""The published basis: the ONE row set the public headline and every FV gate sum.

Spec (docs/superpowers/specs/2026-09-07-published-basis-conservation-gate-design.md, s.1):

    published_fv(cik, quarter) = SUM(fair_value) over all unified rows with that 10-digit cik
    and report_date, with no category, dimension, or subsidiary filter.

Until 2026-09-07 four gate implementations each excluded CASH and is_subsidiary=1 rows (with
per-CIK carve-outs) while the headline excluded nothing; the rows that inflated the headline
were exactly the rows the gates dropped, so nine of twelve Q1-2026 defect funds reconciled to
0.000% against a headline that was $4.09B too high. This module is the single definition;
callers must not add filters. ASCII-only.
"""
from __future__ import annotations

import pandas as pd

# report_date may be VARCHAR, DATE, or TIMESTAMP ('2025-12-31 00:00:00' from typed parquet).
REPORT_DATE_KEY_SQL = "substr(CAST(report_date AS VARCHAR), 1, 10)"
CIK10_SQL = "lpad(regexp_replace(CAST(cik AS VARCHAR), '[^0-9]', '', 'g'), 10, '0')"


def published_fv_sum_sql(table_expr: str, where: str = "TRUE") -> str:
    """SELECT cik, report_date, value_sum, n_rows FROM <table_expr> WHERE <where> GROUP BY 1,2.
    n_rows counts rows with a numeric fair_value (NULL fair_value contributes nothing)."""
    return f"""
        SELECT {CIK10_SQL} AS cik,
               {REPORT_DATE_KEY_SQL} AS report_date,
               sum(TRY_CAST(fair_value AS DOUBLE)) AS value_sum,
               count(TRY_CAST(fair_value AS DOUBLE)) AS n_rows
        FROM {table_expr}
        WHERE ({where})
        GROUP BY 1, 2
    """


def published_fv_mask(df: pd.DataFrame) -> pd.Series:
    """Rows that count: all of them. Exists so mask-taking callers have one named source."""
    return pd.Series(True, index=df.index)


def published_fv_by_quarter(df: pd.DataFrame) -> dict[str, float]:
    """{report_date (10 chars) -> sum(fair_value)} for one CIK's frame; no filters."""
    if df is None or len(df) == 0 or "report_date" not in df.columns:
        return {}
    fv = pd.to_numeric(df.get("fair_value"), errors="coerce").fillna(0.0)
    key = df["report_date"].astype(str).str.slice(0, 10)
    return {str(k): float(v) for k, v in fv.groupby(key).sum().items()}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `pytest tests/test_published_basis.py -v`
Expected: 3 PASS.

- [ ] **Step 5: Commit**

```bash
git add pipeline/published_basis.py tests/test_published_basis.py
git commit -m "feat: published_basis -- the one FV numerator for headline and gates

- published_fv_sum_sql (DuckDB) and published_fv_by_quarter (pandas) with a parity test
- no category/dimension/subsidiary filter by definition (spec s.1)

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_012y9HXDTAq1SHqB5GKmjmc1"
```

---

### Task 2: Switch the three pandas numerators to the published basis; retire `conservation_scope`

**Files:**
- Modify: `pipeline/agent_rule.py` (`value_sum_by_quarter`, delete `CONSERVATION_EXCLUDED_CATEGORIES`)
- Modify: `pipeline/agent_b2_diagnose.py` (`_gate_rows`)
- Modify: `scripts/agent_b2/run_remediation.py` (`build_conservation_snapshots`)
- Modify: `pipeline/config.py` (delete `CONSERVATION_SCOPE_DIR`)
- Delete: `pipeline/conservation_scope.py`, `tests/test_conservation_scope.py`
- Move: `data/overrides/conservation_scope/*.json` -> `data/overrides/_retired/conservation_scope/` + `README.md`
- Test: `tests/test_agent_rule.py`, `tests/test_agent_b2_diagnose.py`, `tests/test_agent_b2_run_remediation.py`, `tests/test_agent_promoted.py`

**Interfaces:**
- `value_sum_by_quarter(df, cik=None)` keeps its signature (`cik` is now ignored; kept so callers do not change) and returns `published_fv_by_quarter(df)`.
- `agent_b2_diagnose._gate_rows(df)` returns `published_fv_mask(df)`.
- `run_remediation.build_conservation_snapshots` sums via `published_fv_by_quarter`.

- [ ] **Step 1: Rewrite the tests (failing first)**

In `tests/test_agent_rule.py`: delete `test_value_sum_excludes_cash_but_keeps_rows`, `test_value_sum_excludes_subsidiary_rows_but_keeps_them`, `test_value_sum_respects_conservation_scope`, `test_value_sum_quarter_scoped_carveout_leaves_other_quarters`, and `test_value_sum_honors_gate_filter` (line ~482). Add:

```python
def test_value_sum_is_the_published_basis():
    """Spec 2026-09-07 s.1: the gate sums exactly what the headline sums. CASH rows,
    is_subsidiary=1 rows, and NULL-dimension rows all count. Bain Q4-25 needed the
    subsidiary rows (0.970 -> 1.002); Q1-26 they were surplus (1.224) -- the gate decides."""
    df = pd.DataFrame([
        {**_h("1", "q", 1815.0), "is_subsidiary": 0, "asset_category": "LOAN"},
        {**_h("1", "q", 406.5), "is_subsidiary": 1, "asset_category": "LOAN"},
        {**_h("1", "q", 20.0), "is_subsidiary": None, "asset_category": "CASH"},
        {**_h("1", "q", 5.0, dims=None), "asset_category": "LOAN"},
    ])
    assert value_sum_by_quarter(df)["q"] == 2246.5
    assert value_sum_by_quarter(df, cik="1")["q"] == 2246.5     # cik arg is inert
    assert len(df) == 4
```

In `tests/test_agent_b2_diagnose.py`: replace `test_value_sum_honors_gate_filter` and `test_value_sum_excludes_subsidiary_rows` with:

```python
def test_value_sum_is_published_basis():
    df = _uframe([_u(100.0, "A"), _u(50.0, "B", dims=None), _u(40.0, "SubLayer")])
    df["is_subsidiary"] = [0, 0, 1]
    assert value_sum(df) == 190.0
```

In `tests/test_agent_b2_run_remediation.py`: replace `test_conservation_snapshot_excludes_subsidiary_rows` with:

```python
def test_conservation_snapshot_is_published_basis():
    df = _holdings([
        {"report_date": "2024-12-31", "fair_value": 1815.0, "is_subsidiary": 0},
        {"report_date": "2024-12-31", "fair_value": 406.0, "is_subsidiary": 1},
    ])
    snaps = rr.build_conservation_snapshots(df, {"2024-12-31": 1815.0})
    assert snaps["2024-12-31"]["conservation"]["value_sum"] == 2221.0
    assert snaps["2024-12-31"]["flags"] == ["fv_conservation"]
    snaps2 = rr.build_conservation_snapshots(df, {"2024-12-31": 2221.0})
    assert snaps2["2024-12-31"]["flags"] == []
```

In `tests/test_agent_promoted.py`: delete `test_engine_conservation_scope_carveout_is_cik_scoped` (its subject no longer exists). Leave `test_engine_conservation_sum_excludes_subsidiary_rows` for Task 3 to rewrite.

- [ ] **Step 2: Run to verify the new tests fail**

Run: `pytest tests/test_agent_rule.py::test_value_sum_is_the_published_basis tests/test_agent_b2_diagnose.py::test_value_sum_is_published_basis tests/test_agent_b2_run_remediation.py::test_conservation_snapshot_is_published_basis -v`
Expected: 3 FAIL on the summed value.

- [ ] **Step 3: Implement**

`pipeline/agent_rule.py`: delete the `CONSERVATION_EXCLUDED_CATEGORIES` constant and its comment. Replace `value_sum_by_quarter` with:

```python
def value_sum_by_quarter(df: pd.DataFrame, cik=None) -> dict[str, float]:
    """Conservation value_sum per report_date on the PUBLISHED basis (spec 2026-09-07 s.1):
    every row counts -- CASH, is_subsidiary=1, NULL-dimension rows included -- because the
    public headline counts them. ``cik`` is accepted for call-site compatibility and ignored
    (per-CIK numerator carve-outs were retired with pipeline.conservation_scope)."""
    from pipeline.published_basis import published_fv_by_quarter
    return published_fv_by_quarter(df)
```

`pipeline/agent_b2_diagnose.py`: replace `_gate_rows` with:

```python
def _gate_rows(df: pd.DataFrame) -> pd.Series:
    """Rows the conservation value_sum includes: ALL of them (published basis, spec
    2026-09-07 s.1). GATE_FILTER is retained as a column name for callers that report on
    dimension presence, but it no longer filters the sum."""
    from pipeline.published_basis import published_fv_mask
    return published_fv_mask(df)
```

`scripts/agent_b2/run_remediation.py`, in `build_conservation_snapshots`, delete the `is_subsidiary` block and replace the two `fv = ...` / `sums = ...` lines with:

```python
    from pipeline.published_basis import published_fv_by_quarter
    sums = published_fv_by_quarter(holdings_df)
    for q, vsum in sums.items():
```

`pipeline/config.py`: delete the `CONSERVATION_SCOPE_DIR = ...` line.

Delete `pipeline/conservation_scope.py` and `tests/test_conservation_scope.py`. Then:

```bash
mkdir -p data/overrides/_retired/conservation_scope
git mv data/overrides/conservation_scope/1772704.json data/overrides/conservation_scope/1899996.json data/overrides/conservation_scope/1905824.json data/overrides/conservation_scope/1916608.json data/overrides/conservation_scope/1950976.json data/overrides/_retired/conservation_scope/
```

Create `data/overrides/_retired/conservation_scope/README.md`:

```markdown
# Retired 2026-09-07: conservation-scope carve-outs

These five per-CIK files widened the conservation NUMERATOR to include CASH rows for filers
whose anchor included cash equivalents. Retired by the published-basis gate
(docs/superpowers/specs/2026-09-07-published-basis-conservation-gate-design.md): the numerator
now always equals the published row set, and what an anchor includes is declared on the anchor
leaf (`basis`) instead. Their evidence (exact cash-equivalent amounts per filer) remains useful
for the anchor lane and is why the files are kept. Nothing reads this directory.
```

Grep for leftovers and fix any: `rg -n "conservation_scope|CONSERVATION_SCOPE_DIR|CONSERVATION_EXCLUDED_CATEGORIES|build_cash_filter" pipeline scripts tests` -- after this task the only hits must be inside `scripts/shadow_conservation_engine.py` (`build_cash_filter`, removed in Task 3) and `scripts/shadow_validation_runner.py` if it references it (Task 3).

- [ ] **Step 4: Run the tests**

Run: `pytest tests/test_agent_rule.py tests/test_agent_b2_diagnose.py tests/test_agent_b2_run_remediation.py -q`
Expected: all pass. `tests/test_agent_promoted.py` will fail on the engine test until Task 3; that is expected.

- [ ] **Step 5: Commit**

```bash
git add -A pipeline/agent_rule.py pipeline/agent_b2_diagnose.py scripts/agent_b2/run_remediation.py pipeline/config.py pipeline/conservation_scope.py tests/test_conservation_scope.py data/overrides/conservation_scope data/overrides/_retired tests/test_agent_rule.py tests/test_agent_b2_diagnose.py tests/test_agent_b2_run_remediation.py tests/test_agent_promoted.py
git commit -m "feat: gate numerators on the published basis; retire conservation_scope

- value_sum_by_quarter, _gate_rows, build_conservation_snapshots sum every row (no CASH / is_subsidiary / dims filter)
- pipeline.conservation_scope + 5 carve-out files retired to data/overrides/_retired (evidence kept)
- tests rewritten to pin inclusion (Bain Q4/Q1 rationale in docstring)

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_012y9HXDTAq1SHqB5GKmjmc1"
```

---

### Task 3: Conservation engine on the published basis; anchors carry a basis; ledger records it

**Files:**
- Modify: `scripts/shadow_conservation_engine.py` (`Anchor`, `RULES`, `ensure_anchor_overrides`, `_anchor_table_sql`, `run_rule`, delete `build_cash_filter`, `main`)
- Modify: `pipeline/agent_promoted.py` (`load_anchor_overrides` returns `basis`, skips leaves without)
- Modify: `scripts/shadow_validation_runner.py` (`_CONS` fragment; drop `cash_filter` plumbing)
- Test: `tests/test_agent_promoted.py`

**Interfaces:**
- `Anchor(kind, label, column, basis="")` -- `basis` is `published_rows` / `investments_ex_cash`; for `verified_override` it selects which leaves the anchor reads.
- New anchor kind `fund_financials_plus_cash` (label `companyfacts_fv_plus_cash`, basis `published_rows`): `investments_at_fair_value + cash_equivalents_at_fair_value` from `fund_financials.csv`, joined to `_cash_rows` (cik-quarters that hold at least one `asset_category='CASH'` row in unified). The `cash_equivalents_at_fair_value` column is added in Task 6; until then the SQL returns no rows (column absent -> the anchor SELECT must guard with a column probe, see below).
- `result_<rule>` gains `anchor_basis` VARCHAR.
- `load_anchor_overrides()` -> `[{cik, report_date, anchor_value, basis}]`; leaves without a valid `basis` are skipped with a WARN.
- Ledger `mechanism` for conservation rows = `anchor_used || ':' || anchor_basis` (e.g. `verified_override:published_rows`, `companyfacts_fv:investments_ex_cash`, `none:`).

- [ ] **Step 1: Rewrite/add the engine tests (failing first)**

In `tests/test_agent_promoted.py`:

Replace `test_load_anchor_overrides_reads_and_pads` with:

```python
def test_load_anchor_overrides_reads_pads_and_requires_basis(tmp_path):
    _write_json(tmp_path / "1715933" / "2025-06-30.json",
                {"cik": "1715933", "target_quarter": "2025-06-30",
                 "grand_total": 1093518278.0, "method": "total_row", "basis": "published_rows"})
    _write_json(tmp_path / "1715933" / "2025-09-30.json",
                {"cik": "1715933", "target_quarter": "2025-09-30",
                 "grand_total": 5.0, "method": "total_row"})              # no basis -> skipped
    _write_json(tmp_path / "1715933" / "2025-12-31.json",
                {"cik": "1715933", "target_quarter": "2025-12-31",
                 "grand_total": 6.0, "method": "total_row", "basis": "grand"})  # bad enum -> skipped
    out = ap.load_anchor_overrides(tmp_path)
    assert out == [{"cik": "0001715933", "report_date": "2025-06-30",
                    "anchor_value": 1093518278.0, "basis": "published_rows"}]
```

In `test_load_anchor_overrides_skips_malformed`, add `"basis": "investments_ex_cash"` to the `333` leaf so it still loads.

Replace `test_fv_conservation_verified_override_is_top_priority` with:

```python
def test_fv_conservation_anchor_priority_and_bases():
    import scripts.shadow_conservation_engine as sce
    fv = next(r for r in sce.RULES if r.name == "fv_conservation")
    assert [(a.kind, a.basis) for a in fv.anchors] == [
        ("verified_override", "published_rows"),
        ("verified_override", "investments_ex_cash"),
        ("fund_financials_plus_cash", "published_rows"),
        ("fund_financials", "investments_ex_cash"),
        ("schedule_total", "investments_ex_cash"),
    ]
```

In `test_engine_prefers_verified_override`: add `"basis": "published_rows"` to the written leaf; change the rule to
`anchors=(sce.Anchor("verified_override", "verified_override", "grand_total", basis="published_rows"), sce.Anchor("schedule_total", "schedule_total", "fair_value", basis="investments_ex_cash"))`; extend the result assertion to include `anchor_basis`:

```python
    rows = {r[0]: r for r in con.execute(
        "SELECT cik, anchor_value, anchor_used, status, anchor_basis FROM result_fv_test").fetchall()}
    assert rows["0001715933"][1:] == (1000.0, "verified_override", "reconciles", "published_rows")
    assert rows["0000000456"][1:] == (500.0, "schedule_total", "reconciles", "investments_ex_cash")
```

Replace `test_engine_conservation_sum_excludes_subsidiary_rows` with:

```python
def test_engine_conservation_sum_is_published_basis(monkeypatch):
    """Spec 2026-09-07 s.1: the engine sums every row (CASH, is_subsidiary=1, NULL dims).
    Parent 600+400, subsidiary layer 400, cash 20 -> 1420 vs a 1000 schedule total = overshoot.
    That overshoot is the gate DOING ITS JOB (Bain Q1-26); Bain Q4-25 reconciles the same way."""
    import scripts.shadow_conservation_engine as sce

    con = duckdb.connect()
    con.execute("CREATE TABLE wrapped(cik VARCHAR)")
    con.execute("INSERT INTO wrapped VALUES ('0001899017')")
    con.execute("""
        CREATE TABLE unified_tbl AS SELECT * FROM (VALUES
            ('0001899017', '2026-03-31', 600.0, 'x=y', 'LOAN', 0),
            ('0001899017', '2026-03-31', 400.0, 'x=y', 'LOAN', 0),
            ('0001899017', '2026-03-31', 400.0, 'nonconsolidatedsubsidiaryaxis=SLP', 'LOAN', 1),
            ('0001899017', '2026-03-31', 20.0, NULL, 'CASH', NULL)
        ) AS t(cik, report_date, fair_value, bdc_dimensions_raw, asset_category, is_subsidiary)
    """)
    con.execute("""
        CREATE TABLE bdc_tbl AS SELECT * FROM (VALUES
            ('0001899017', '2026-03-31', '2026-03-31', 'Total Investments', 1000.0)
        ) AS t(cik, report_date, period, investment_identifier, fair_value)
    """)
    monkeypatch.setattr(sce, "_unified", lambda: "unified_tbl")
    monkeypatch.setattr(sce, "_bdc", lambda: "bdc_tbl")
    rule = sce.ConservationRule(
        name="fv_pub_test", value_column="fair_value",
        anchors=(sce.Anchor("schedule_total", "schedule_total", "fair_value",
                            basis="investments_ex_cash"),))
    sce.run_rule(con, rule)
    row = con.execute("SELECT value_sum, n_rows, anchor_value, status FROM result_fv_pub_test").fetchone()
    assert row == (1420.0, 4, 1000.0, "overshoot"), row


def test_engine_companyfacts_plus_cash_only_where_cash_rows_exist(monkeypatch, tmp_path):
    """Deterministic published-rows anchor: investments_at_fair_value + tagged cash equivalents,
    used ONLY for cik-quarters that hold a CASH row. Fund A (has cash) anchors at 1000+20;
    fund B (no cash rows) falls through to plain companyfacts."""
    import scripts.shadow_conservation_engine as sce
    ff = tmp_path / "fund_financials.csv"
    ff.write_text(
        "cik,report_date,source,investments_at_fair_value,cash_equivalents_at_fair_value\n"
        "0000000001,2026-03-31,companyfacts,1000,20\n"
        "0000000002,2026-03-31,companyfacts,500,7\n", encoding="utf-8")
    monkeypatch.setattr(sce, "FUND_FINANCIALS_FILE", ff)
    con = duckdb.connect()
    con.execute("CREATE TABLE wrapped(cik VARCHAR)")
    con.executemany("INSERT INTO wrapped VALUES (?)", [("0000000001",), ("0000000002",)])
    con.execute("""
        CREATE TABLE unified_tbl AS SELECT * FROM (VALUES
            ('0000000001', '2026-03-31', 1000.0, 'x=y', 'LOAN'),
            ('0000000001', '2026-03-31', 20.0, 'cashandcashequivalentsaxis=MMF', 'CASH'),
            ('0000000002', '2026-03-31', 500.0, 'x=y', 'LOAN')
        ) AS t(cik, report_date, fair_value, bdc_dimensions_raw, asset_category)
    """)
    monkeypatch.setattr(sce, "_unified", lambda: "unified_tbl")
    rule = sce.ConservationRule(
        name="fv_cash_test", value_column="fair_value",
        anchors=(sce.Anchor("fund_financials_plus_cash", "companyfacts_fv_plus_cash",
                            "investments_at_fair_value", basis="published_rows"),
                 sce.Anchor("fund_financials", "companyfacts_fv", "investments_at_fair_value",
                            basis="investments_ex_cash")))
    sce.run_rule(con, rule)
    rows = {r[0]: r[1:] for r in con.execute(
        "SELECT cik, anchor_value, anchor_used, anchor_basis, status FROM result_fv_cash_test").fetchall()}
    assert rows["0000000001"] == (1020.0, "companyfacts_fv_plus_cash", "published_rows", "reconciles")
    assert rows["0000000002"] == (500.0, "companyfacts_fv", "investments_ex_cash", "reconciles")


def test_engine_companyfacts_plus_cash_skipped_when_column_absent(monkeypatch, tmp_path):
    import scripts.shadow_conservation_engine as sce
    ff = tmp_path / "fund_financials.csv"
    ff.write_text("cik,report_date,source,investments_at_fair_value\n"
                  "0000000001,2026-03-31,companyfacts,1000\n", encoding="utf-8")
    monkeypatch.setattr(sce, "FUND_FINANCIALS_FILE", ff)
    con = duckdb.connect()
    con.execute("CREATE TABLE wrapped(cik VARCHAR)")
    con.execute("INSERT INTO wrapped VALUES ('0000000001')")
    con.execute("""CREATE TABLE unified_tbl AS SELECT * FROM (VALUES
        ('0000000001', '2026-03-31', 1000.0, 'x=y', 'LOAN'),
        ('0000000001', '2026-03-31', 20.0, 'c=MMF', 'CASH')
        ) AS t(cik, report_date, fair_value, bdc_dimensions_raw, asset_category)""")
    monkeypatch.setattr(sce, "_unified", lambda: "unified_tbl")
    rule = sce.ConservationRule(
        name="fv_nocol", value_column="fair_value",
        anchors=(sce.Anchor("fund_financials_plus_cash", "companyfacts_fv_plus_cash",
                            "investments_at_fair_value", basis="published_rows"),
                 sce.Anchor("fund_financials", "companyfacts_fv", "investments_at_fair_value",
                            basis="investments_ex_cash")))
    sce.run_rule(con, rule)
    row = con.execute("SELECT anchor_used, anchor_basis, status FROM result_fv_nocol").fetchone()
    assert row == ("companyfacts_fv", "investments_ex_cash", "overshoot")
```

- [ ] **Step 2: Run to verify failures**

Run: `pytest tests/test_agent_promoted.py -q -k "anchor or engine"`
Expected: the new/rewritten tests fail (`Anchor` has no `basis`, `anchor_basis` column missing, loader returns no `basis`).

- [ ] **Step 3: Implement the engine**

`scripts/shadow_conservation_engine.py`:

Replace the `Anchor` dataclass:

```python
@dataclass(frozen=True)
class Anchor:
    """Where to get the independent fund-level total for one CIK-quarter."""
    kind: str            # 'verified_override' | 'fund_financials' | 'fund_financials_plus_cash'
                         # | 'schedule_total' | 'companyfacts_concept'
    label: str           # tier label recorded in output (e.g. 'companyfacts_fv')
    column: str          # fund_financials column, OR the value column for a schedule total row
    # What the anchor INCLUDES (spec 2026-09-07 s.2): 'published_rows' = everything the schedule
    # lists incl. cash equivalents and look-through rows (directly comparable to the published
    # numerator); 'investments_ex_cash' = the balance-sheet investments line. For
    # verified_override this selects which leaves the anchor reads.
    basis: str = ""
```

Replace the `fv_conservation` rule's `anchors` tuple:

```python
        anchors=(
            # Priority (spec s.2, plan deviation 1): a verified override exists precisely because
            # companyfacts was partial, so BOTH override bases outrank companyfacts. The
            # published_rows override is directly comparable to the published numerator; an
            # ex-cash override on a cash-holding fund flags an overshoot equal to its cash rows,
            # which is the honest signal that the anchor lane must upgrade its basis.
            Anchor("verified_override", "verified_override", "grand_total", basis="published_rows"),
            Anchor("verified_override", "verified_override_ex_cash", "grand_total",
                   basis="investments_ex_cash"),
            # Deterministic published-rows candidate: companyfacts FV + the filer's tagged cash
            # equivalents (fund_financials.cash_equivalents_at_fair_value), only for cik-quarters
            # that hold a CASH row in unified.
            Anchor("fund_financials_plus_cash", "companyfacts_fv_plus_cash",
                   "investments_at_fair_value", basis="published_rows"),
            Anchor("fund_financials", "companyfacts_fv", "investments_at_fair_value",
                   basis="investments_ex_cash"),
            Anchor("schedule_total", "schedule_total", "fair_value", basis="investments_ex_cash"),
        ),
```

For the `cost_conservation` rule, add `basis="investments_ex_cash"` to each of its three anchors (cost anchors are ex-cash by construction; the label is informational there).

Replace `ensure_anchor_overrides`:

```python
def ensure_anchor_overrides(con: duckdb.DuckDBPyConnection) -> int:
    """TEMP TABLE _anchor_override(cik, report_date, anchor_value, basis) from the promoted
    Anchor-Adjudicator leaves that declare a basis (leaves without one are ignored upstream)."""
    from pipeline.agent_promoted import load_anchor_overrides
    rows = [(o["cik"], o["report_date"], o["anchor_value"], o["basis"])
            for o in load_anchor_overrides()]
    con.execute("CREATE OR REPLACE TEMP TABLE _anchor_override("
                "cik VARCHAR, report_date VARCHAR, anchor_value DOUBLE, basis VARCHAR)")
    if rows:
        con.executemany("INSERT INTO _anchor_override VALUES (?, ?, ?, ?)", rows)
    return len(rows)
```

In `_anchor_table_sql`, replace the `verified_override` branch and add the plus-cash branch:

```python
    if anchor.kind == "verified_override":
        b = anchor.basis.replace("'", "''")
        return f"SELECT cik, report_date, anchor_value FROM _anchor_override WHERE basis = '{b}'"
    if anchor.kind == "fund_financials_plus_cash":
        # Column probe: fund_financials.cash_equivalents_at_fair_value lands with Task 6; an
        # older CSV simply yields no rows for this anchor (falls through to the next).
        cols = {r[0].lower() for r in duckdb.connect().execute(
            f"DESCRIBE SELECT * FROM read_csv_auto('{FUND_FINANCIALS_FILE.as_posix()}', sample_size=-1) LIMIT 0"
        ).fetchall()}
        if "cash_equivalents_at_fair_value" not in cols:
            return "SELECT CAST(NULL AS VARCHAR) AS cik, CAST(NULL AS VARCHAR) AS report_date, CAST(NULL AS DOUBLE) AS anchor_value WHERE false"
        return f"""
            SELECT f.cik, f.report_date, f.ifv + f.cash AS anchor_value
            FROM (
                SELECT CAST(cik AS VARCHAR) AS cik, CAST(report_date AS VARCHAR) AS report_date,
                       max(TRY_CAST({anchor.column} AS DOUBLE)) AS ifv,
                       max(TRY_CAST(cash_equivalents_at_fair_value AS DOUBLE)) AS cash
                FROM read_csv_auto('{FUND_FINANCIALS_FILE.as_posix()}', sample_size=-1)
                WHERE source='companyfacts'
                GROUP BY 1, 2
            ) f
            JOIN _cash_rows c USING (cik, report_date)
            WHERE f.ifv IS NOT NULL AND f.cash IS NOT NULL
        """
```

Delete `build_cash_filter` entirely. Replace `run_rule` with:

```python
def run_rule(con: duckdb.DuckDBPyConnection, rule: ConservationRule) -> None:
    """Run one conservation rule into result_<rule>: the PUBLISHED-basis sum of value_column
    over every unified row of each wrapped CIK-quarter (spec 2026-09-07 s.1 -- no cash,
    subsidiary, or dimension filter; what the headline sums is what the gate sums) against
    the first available anchor in priority order."""
    from pipeline.published_basis import published_fv_sum_sql
    con.execute(
        f"CREATE OR REPLACE TEMP TABLE _sum_{rule.name} AS "
        + published_fv_sum_sql(_unified(),
                               f"lpad(regexp_replace(CAST(cik AS VARCHAR), '[^0-9]', '', 'g'), 10, '0') "
                               f"IN (SELECT cik FROM wrapped)")
        .replace("TRY_CAST(fair_value AS DOUBLE)", f"TRY_CAST({rule.value_column} AS DOUBLE)")
    )
    # cik-quarters holding at least one CASH row (gates the companyfacts_fv_plus_cash anchor)
    con.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE _cash_rows AS
        SELECT DISTINCT lpad(regexp_replace(CAST(cik AS VARCHAR), '[^0-9]', '', 'g'), 10, '0') AS cik,
               substr(CAST(report_date AS VARCHAR), 1, 10) AS report_date
        FROM {_unified()}
        WHERE upper(COALESCE(CAST(asset_category AS VARCHAR), '')) = 'CASH'
        """
    )
    anchor_ctes, coalesce_val, coalesce_label, coalesce_basis = [], [], [], []
    for i, a in enumerate(rule.anchors):
        con.execute(f"CREATE OR REPLACE TEMP TABLE _a{i}_{rule.name} AS {_anchor_table_sql(a)}")
        anchor_ctes.append(f"LEFT JOIN _a{i}_{rule.name} a{i} USING (cik, report_date)")
        coalesce_val.append(f"a{i}.anchor_value")
        coalesce_label.append(f"WHEN a{i}.anchor_value IS NOT NULL THEN '{a.label}'")
        coalesce_basis.append(f"WHEN a{i}.anchor_value IS NOT NULL THEN '{a.basis}'")
    val_expr = "COALESCE(" + ", ".join(coalesce_val) + ")"
    label_expr = "CASE " + " ".join(coalesce_label) + " ELSE 'none' END"
    basis_expr = "CASE " + " ".join(coalesce_basis) + " ELSE '' END"
    tol = rule.tolerance_pct
    con.execute(
        f"""
        CREATE OR REPLACE TABLE result_{rule.name} AS
        SELECT
            '{rule.name}' AS rule_name,
            '{rule.value_column}' AS value_column,
            '{rule.tier}' AS tier,
            '{rule.enforcement}' AS enforcement,
            s.cik, s.report_date, s.n_rows,
            s.value_sum,
            {val_expr} AS anchor_value,
            {label_expr} AS anchor_used,
            {basis_expr} AS anchor_basis,
            CASE WHEN {val_expr} IS NOT NULL AND {val_expr} <> 0
                 THEN round(100.0*(s.value_sum - {val_expr})/{val_expr}, 3) END AS residual_pct,
            CASE
                WHEN {val_expr} IS NULL THEN 'no_anchor'
                WHEN abs(s.value_sum - {val_expr}) <= {tol}*abs({val_expr}) THEN 'reconciles'
                WHEN s.value_sum > {val_expr} THEN 'overshoot'
                ELSE 'undershoot'
            END AS status
        FROM _sum_{rule.name} s
        {' '.join(anchor_ctes)}
        """
    )
```

The `.replace(...)` on the value column is deliberate: `published_fv_sum_sql` is written for `fair_value`; `cost_conservation` reuses it for `cost`. Keep the `count(...)` also on the value column (the replace covers both occurrences).

In `main()`, delete `cash_filter = build_cash_filter()` and call `run_rule(con, rule)`.

`scripts/shadow_validation_runner.py`: the engine call already passes no `cash_filter` (`cons.run_rule(con, r)`), so only `_CONS` changes:

```python
_CONS = """
SELECT 'conservation' AS engine, rule_name, tier, enforcement, cik,
       'report_date' AS period_kind, report_date AS period,
       CASE status WHEN 'reconciles' THEN 'pass'
                   WHEN 'no_anchor'  THEN 'skip' ELSE 'fail' END AS status,
       residual_pct AS metric, 'residual_pct' AS metric_name, 1 AS n_units,
       anchor_used || ':' || COALESCE(anchor_basis, '') AS mechanism,
       CAST(NULL AS VARCHAR) AS src_confidence
FROM result_{name}
"""
```

Also grep the runner for `build_cash_filter`; if present, delete that call.

`pipeline/agent_promoted.py::load_anchor_overrides`: after `total = leaf.get("grand_total")`, add:

```python
        basis = str(leaf.get("basis") or "").strip()
        if basis not in ("published_rows", "investments_ex_cash"):
            logger.warning("anchor override has no valid basis (spec 2026-09-07 s.2), skipped: %s", p)
            continue
```
and append `"basis": basis` to the emitted dict. Update the docstring to list `basis`.

- [ ] **Step 4: Run the tests**

Run: `pytest tests/test_agent_promoted.py tests/test_shadow_adapter.py -q`
Expected: all pass. If `test_engine_prefers_verified_override` fails because the fixture's `unified_tbl` lacks `asset_category`, it has it (5 columns) -- check the `_cash_rows` SQL runs against the stand-in table name via `_unified()`.

- [ ] **Step 5: Commit**

```bash
git add scripts/shadow_conservation_engine.py scripts/shadow_validation_runner.py pipeline/agent_promoted.py tests/test_agent_promoted.py
git commit -m "feat: conservation engine sums the published basis; anchors declare basis

- run_rule uses published_fv_sum_sql (no cash/subsidiary/dims filter); build_cash_filter removed
- Anchor.basis; verified_override split by basis; new companyfacts_fv_plus_cash anchor gated on CASH rows
- result gains anchor_basis; ledger mechanism = anchor_used:anchor_basis; leaves without basis skipped

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_012y9HXDTAq1SHqB5GKmjmc1"
```

---

### Task 4: Anchor leaf schema `basis`; investigation driver and anchor lane honour it

**Files:**
- Modify: `pipeline/anchor_leaf.py`
- Modify: `pipeline/anchor_validation.py` (`STRONG_ANCHORS`)
- Modify: `scripts/agent_investigate/run_investigation.py` (`load_anchor_overrides`, `load_anchor_candidates`, `_prompt` anchor note)
- Modify: `scripts/agent_anchor/run_anchor.py` (`_prompt` output block)
- Test: `tests/test_anchor_leaf.py`, `tests/test_investigation_orchestration.py`

**Interfaces:**
- `anchor_leaf.BASES = frozenset({"published_rows", "investments_ex_cash"})`; `REQUIRED` gains `"basis"`; `validate_anchor_leaf` rejects a missing/invalid basis and rejects a `published_rows` leaf whose `grand_total` is within 0.5% of its own `companyfacts_fv` (mislabelled), and an `investments_ex_cash` leaf whose grand_total exceeds `companyfacts_fv` by more than 0.5% when `companyfacts_fv` is present (mislabelled).
- `run_investigation.load_anchor_overrides(cik) -> dict[str, tuple[float, str]]` (quarter -> (grand_total, basis)).
- `run_investigation.load_anchor_candidates(cik)` candidate names: `printed_schedule_total` (published_rows override), `verified_investments_ex_cash` (ex-cash override), `companyfacts_fv_plus_cash` (replaces `companyfacts_fv` when the fund holds CASH rows in that quarter and the cash column is present), `companyfacts_fv`.
- `anchor_validation.STRONG_ANCHORS` gains `verified_investments_ex_cash` and `companyfacts_fv_plus_cash`.

- [ ] **Step 1: Write the failing tests**

In `tests/test_anchor_leaf.py`, add `"basis": "published_rows"` to `_leaf()`'s base dict, then append:

```python
def test_anchor_leaf_requires_valid_basis():
    errs = validate_anchor_leaf({k: v for k, v in _leaf().items() if k != "basis"})
    assert any("basis" in e for e in errs)
    assert any("basis must be one of" in e for e in validate_anchor_leaf(_leaf(basis="grand")))
    assert validate_anchor_leaf(_leaf(basis="investments_ex_cash",
                                      grand_total=691_956_192.0)) == []


def test_anchor_leaf_basis_consistent_with_companyfacts():
    # published_rows but equal to the companyfacts tag -> mislabelled
    errs = validate_anchor_leaf(_leaf(basis="published_rows", grand_total=691_956_192.0))
    assert any("mislabelled" in e for e in errs)
    # investments_ex_cash but far above the tag -> mislabelled
    errs = validate_anchor_leaf(_leaf(basis="investments_ex_cash"))   # grand_total 1.094B vs 692M
    assert any("mislabelled" in e for e in errs)
    # no companyfacts_fv on the leaf -> no consistency check possible
    leaf = _leaf(basis="published_rows"); leaf.pop("companyfacts_fv")
    assert validate_anchor_leaf(leaf) == []
```

Append to `tests/test_investigation_orchestration.py`:

```python
def test_anchor_candidates_use_basis(tmp_path, monkeypatch):
    q = "2026-03-31"
    ff = tmp_path / "fund_financials.csv"
    ff.write_text("cik,report_date,source,investments_at_fair_value,cash_equivalents_at_fair_value\n"
                  "0000000888,2026-03-31,companyfacts,1000,20\n"
                  "0000000889,2026-03-31,companyfacts,500,7\n"
                  "0000000890,2026-03-31,companyfacts,300,\n", encoding="utf-8")
    monkeypatch.setattr(pipeline_config, "FUND_FINANCIALS_FILE", ff)
    ov = tmp_path / "agent_anchor"
    monkeypatch.setattr(ri, "ANCHOR_OVERRIDES", ov)
    frames = {
        "888": pd.DataFrame([{"cik": "888", "report_date": q, "fair_value": 1000.0, "asset_category": "LOAN"},
                             {"cik": "888", "report_date": q, "fair_value": 20.0, "asset_category": "CASH"}]),
        "889": pd.DataFrame([{"cik": "889", "report_date": q, "fair_value": 500.0, "asset_category": "LOAN"}]),
        "890": pd.DataFrame([{"cik": "890", "report_date": q, "fair_value": 300.0, "asset_category": "LOAN"},
                             {"cik": "890", "report_date": q, "fair_value": 9.0, "asset_category": "CASH"}]),
    }
    monkeypatch.setattr(ri, "_load_holdings", lambda c: frames[str(c).lstrip("0")])
    # 888: cash rows + cash column -> plus_cash replaces companyfacts_fv
    assert ri.load_anchor_candidates("888")[q] == {"companyfacts_fv_plus_cash": 1020.0}
    # 889: no cash rows -> plain companyfacts_fv
    assert ri.load_anchor_candidates("889")[q] == {"companyfacts_fv": 500.0}
    # 890: cash rows but the cash concept is untagged -> plain companyfacts_fv (honest overshoot later)
    assert ri.load_anchor_candidates("890")[q] == {"companyfacts_fv": 300.0}
    # override with published_rows basis that disagrees with companyfacts -> replaces it
    (ov / "889").mkdir(parents=True)
    (ov / "889" / f"{q}.json").write_text(json.dumps({
        "cik": "889", "target_quarter": q, "grand_total": 540.0, "method": "total_row",
        "basis": "published_rows", "companyfacts_fv": 500.0,
        "components": [{"label": "Total investments and cash equivalents", "value": 540.0, "source": "SOI"}],
        "evidence": [{"source": "filing", "quote": "x"}], "confidence": 0.9}), encoding="utf-8")
    assert ri.load_anchor_candidates("889")[q] == {"printed_schedule_total": 540.0}
    # override with ex-cash basis agreeing with companyfacts -> both kept (HIGH)
    (ov / "889" / f"{q}.json").write_text(json.dumps({
        "cik": "889", "target_quarter": q, "grand_total": 501.0, "method": "total_row",
        "basis": "investments_ex_cash", "companyfacts_fv": 500.0,
        "components": [{"label": "Total investments", "value": 501.0, "source": "SOI"}],
        "evidence": [{"source": "filing", "quote": "x"}], "confidence": 0.9}), encoding="utf-8")
    assert ri.load_anchor_candidates("889")[q] == {"companyfacts_fv": 500.0,
                                                    "verified_investments_ex_cash": 501.0}
    # a leaf without basis is ignored
    (ov / "889" / f"{q}.json").write_text(json.dumps({
        "cik": "889", "target_quarter": q, "grand_total": 999.0, "method": "total_row",
        "components": [{"label": "x", "value": 999.0, "source": "s"}],
        "evidence": [{"source": "filing", "quote": "x"}], "confidence": 0.9}), encoding="utf-8")
    assert ri.load_anchor_candidates("889")[q] == {"companyfacts_fv": 500.0}
```

- [ ] **Step 2: Run to verify failures**

Run: `pytest tests/test_anchor_leaf.py tests/test_investigation_orchestration.py -q -k "basis"`
Expected: FAIL (no basis validation; candidate names not produced).

- [ ] **Step 3: Implement**

`pipeline/anchor_leaf.py`:

```python
REQUIRED = ("cik", "target_quarter", "grand_total", "method", "components", "evidence",
            "confidence", "basis")
METHODS = frozenset({"single_tag", "total_row", "sum_of_schedules"})
# What the grand total INCLUDES (spec 2026-09-07 s.2). published_rows = everything the schedule
# lists incl. cash equivalents / short-term investments / look-through rows -> comparable to the
# published numerator directly. investments_ex_cash = the balance-sheet investments line.
BASES = frozenset({"published_rows", "investments_ex_cash"})
_BASIS_TOL = 0.005   # basis-vs-companyfacts consistency: 0.5% (the conservation band)
```

In `validate_anchor_leaf`, after the `method` check:

```python
    basis = str(obj.get("basis") or "")
    if basis not in BASES:
        errs.append(f"basis must be one of {sorted(BASES)}, got {obj.get('basis')!r}")
    cf = obj.get("companyfacts_fv")
    if basis in BASES and _is_pos_num(obj.get("grand_total")) and _is_pos_num(cf):
        g, c = float(obj["grand_total"]), float(cf)
        close = abs(g - c) <= _BASIS_TOL * c
        if basis == "published_rows" and close:
            errs.append("basis mislabelled: published_rows but grand_total equals the companyfacts "
                        "investments tag within 0.5% -- declare investments_ex_cash or cite the "
                        "cash/short-term components")
        if basis == "investments_ex_cash" and g > c * (1 + _BASIS_TOL):
            errs.append("basis mislabelled: investments_ex_cash but grand_total exceeds the "
                        "companyfacts investments tag by more than 0.5% -- declare published_rows")
```

Update the module docstring's leaf example to include `"basis": "published_rows"` and a one-line explanation.

`pipeline/anchor_validation.py`: add `"verified_investments_ex_cash", "companyfacts_fv_plus_cash"` to `STRONG_ANCHORS`.

`scripts/agent_investigate/run_investigation.py`:

```python
def load_anchor_overrides(cik: str) -> dict[str, tuple[float, str]]:
    """{report_date -> (verified grand_total, basis)} from data/overrides/agent_anchor/<cik>/*.json.
    Leaves that fail validate_anchor_leaf (incl. a missing basis) are ignored."""
    d = ANCHOR_OVERRIDES / _norm(cik)
    out: dict[str, tuple[float, str]] = {}
    for p in (sorted(d.glob("*.json")) if d.exists() else []):
        leaf = load_anchor_leaf(p)
        if leaf and validate_anchor_leaf(leaf) == []:
            q = str(leaf.get("target_quarter") or "").strip()
            try:
                if q:
                    out[q] = (float(leaf["grand_total"]), str(leaf["basis"]))
            except (TypeError, ValueError, KeyError):
                pass
    return out
```

Replace the body of `load_anchor_candidates` after the docstring with:

```python
    c = _norm(cik)
    out: dict[str, dict[str, float]] = {}
    cash_col: dict[str, float] = {}
    ff = config.FUND_FINANCIALS_FILE
    if Path(ff).exists():
        con = duckdb.connect()
        try:
            cols = {r[0].lower() for r in con.execute(
                f"DESCRIBE SELECT * FROM read_csv_auto('{Path(ff).as_posix()}', sample_size=-1) LIMIT 0"
            ).fetchall()}
            cash_sel = ("max(TRY_CAST(cash_equivalents_at_fair_value AS DOUBLE))"
                        if "cash_equivalents_at_fair_value" in cols else "CAST(NULL AS DOUBLE)")
            rows = con.execute(
                f"SELECT CAST(report_date AS VARCHAR), max(TRY_CAST(investments_at_fair_value AS DOUBLE)), "
                f"{cash_sel} FROM read_csv_auto('{Path(ff).as_posix()}', sample_size=-1) "
                f"WHERE source='companyfacts' AND ltrim(CAST(cik AS VARCHAR),'0')='{c}' "
                f"AND investments_at_fair_value IS NOT NULL GROUP BY 1").fetchall()
        finally:
            con.close()
        for rd, v, cash in rows:
            if v is not None:
                out.setdefault(str(rd), {})["companyfacts_fv"] = float(v)
                if cash is not None:
                    cash_col[str(rd)] = float(cash)
    # Published-rows deterministic candidate (spec s.2 anchor 2): where the fund HOLDS a CASH row
    # in that quarter and the filer tagged cash equivalents, companyfacts_fv + cash REPLACES
    # companyfacts_fv (keeping both would make two strong anchors disagree by the cash amount).
    if cash_col:
        h = _load_holdings(cik)
        if h is not None and len(h) and "asset_category" in h.columns:
            cash_q = set(h.loc[h["asset_category"].astype(str).str.upper() == "CASH",
                               "report_date"].astype(str).str.slice(0, 10))
            for rd in cash_q:
                if rd in cash_col and "companyfacts_fv" in out.get(rd, {}):
                    out[rd]["companyfacts_fv_plus_cash"] = out[rd].pop("companyfacts_fv") + cash_col[rd]
    # Verified overrides (anchor-adjudicator), by basis:
    #  - published_rows -> 'printed_schedule_total'; disagreeing companyfacts (partial tag) dropped.
    #  - investments_ex_cash -> 'verified_investments_ex_cash'; agreeing companyfacts kept (HIGH),
    #    disagreeing companyfacts dropped (the override exists because the tag was partial).
    for rd, (gt, basis) in load_anchor_overrides(cik).items():
        name = "printed_schedule_total" if basis == "published_rows" else "verified_investments_ex_cash"
        slot = out.setdefault(rd, {})
        slot[name] = gt
        for cf_name in ("companyfacts_fv", "companyfacts_fv_plus_cash"):
            cf = slot.get(cf_name)
            if cf is not None and abs(cf - gt) > 0.01 * max(abs(cf), abs(gt)):
                slot.pop(cf_name, None)
    return out
```

In `_prompt`, replace `anchor_note` with:

```python
    anchor_note = (f"\nThis anchor is the VALIDATED figure the gate reconciles to (tier {anchor_tier}). "
                   f"The gate sums EVERY published row (cash equivalents and look-through rows "
                   f"included). If the anchor's basis is investments_ex_cash and this fund holds "
                   f"cash-equivalent rows, an overshoot equal to those rows means the ANCHOR needs a "
                   f"published_rows adjudication -- escalate category=anchor, do NOT delete the cash "
                   f"rows. If the anchor is a published_rows grand total, reconcile value_sum to it "
                   f"and do NOT delete real rows to reach a smaller figure. ({anchor_reason})\n"
                   if anchor_tier else "")
```

`scripts/agent_anchor/run_anchor.py` `_prompt`: in the JSON output block add the line
`"basis":"published_rows|investments_ex_cash",` after `"method":...`, and add this paragraph before `## Output`:

```
## Declare the BASIS of your grand total (required)
- `published_rows`: the total of EVERYTHING the schedule of investments lists, INCLUDING cash
  equivalents, money-market / short-term investments, and look-through rows. Use this when the
  filer prints a "Total investments and cash equivalents" style row, or when you sum schedules
  that include those sections. This is the basis the gate compares to directly.
- `investments_ex_cash`: the balance-sheet "investments at fair value" line (what companyfacts
  InvestmentOwnedAtFairValue usually tags). Cite it only when the cash-equivalent section is
  presented OUTSIDE the total you report.
A published_rows total must differ from the companyfacts tag; an investments_ex_cash total must
not exceed it by more than 0.5%. The leaf is rejected otherwise.
```

- [ ] **Step 4: Run the tests**

Run: `pytest tests/test_anchor_leaf.py tests/test_anchor_adjudicator.py tests/test_anchor_validation.py tests/test_investigation_orchestration.py -q`
Expected: all pass. `test_anchor_adjudicator.py` may construct leaves without `basis`; add `"basis": "published_rows"` (or `investments_ex_cash` where the grand total equals companyfacts) to those fixtures.

- [ ] **Step 5: Commit**

```bash
git add pipeline/anchor_leaf.py pipeline/anchor_validation.py scripts/agent_investigate/run_investigation.py scripts/agent_anchor/run_anchor.py tests/test_anchor_leaf.py tests/test_anchor_adjudicator.py tests/test_investigation_orchestration.py
git commit -m "feat: anchor leaves declare basis; driver candidates by basis

- anchor_leaf: basis required (published_rows | investments_ex_cash) + mislabel check vs companyfacts_fv
- load_anchor_candidates: companyfacts_fv_plus_cash replaces companyfacts_fv where CASH rows exist; overrides named by basis
- worker + anchor-lane prompts state the basis and the escalate-not-delete rule

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_012y9HXDTAq1SHqB5GKmjmc1"
```

---

### Task 5: Backfill `basis` on the 67 existing anchor leaves

**Files:**
- Create: `scripts/backfill_anchor_basis.py`
- Test: `tests/test_backfill_anchor_basis.py` (new)

**Interfaces:**
- `classify_leaf(leaf: dict) -> str` returns `published_rows`, `investments_ex_cash`, or `""` (unresolved).
- `backfill(overrides_dir: Path, out_csv: Path, *, write: bool) -> dict` with counts `{"published_rows", "investments_ex_cash", "unresolved", "already_set", "invalid"}`; writes basis into each resolvable leaf (in place, `utf-8`, 2-space indent) when `write=True`, and always writes the unresolved list to `out_csv` (columns `cik,target_quarter,grand_total,companyfacts_fv,method,reason`).
- CLI: `python scripts/backfill_anchor_basis.py [--dry-run]`; default out CSV `data/output/agent_anchor/basis_backfill_unresolved.csv`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_backfill_anchor_basis.py`:

```python
import csv
import json

from scripts.backfill_anchor_basis import backfill, classify_leaf


def _leaf(gt, cf, labels=("Total Investments",), method="total_row", basis=None):
    d = {"cik": "1", "target_quarter": "2026-03-31", "grand_total": gt, "method": method,
         "components": [{"label": l, "value": gt, "source": "s"} for l in labels],
         "companyfacts_fv": cf, "evidence": [{"source": "filing", "quote": "x"}],
         "rationale": "r", "confidence": 0.9}
    if basis:
        d["basis"] = basis
    return d


def test_classify_leaf():
    assert classify_leaf(_leaf(1000.0, 1001.0)) == "investments_ex_cash"
    assert classify_leaf(_leaf(1093.5, 692.0, labels=("Total Debt & Equity Investments",
                                                        "Total Cash Equivalents",
                                                        "Total Short-term Investments"),
                               method="sum_of_schedules")) == "published_rows"
    assert classify_leaf(_leaf(1093.5, 692.0, labels=("Total Investments",))) == ""      # wider, no cash label
    assert classify_leaf(_leaf(1093.5, None)) == ""                                      # no companyfacts
    assert classify_leaf(_leaf(500.0, 692.0)) == ""                                      # below the tag


def test_backfill_writes_and_reports(tmp_path):
    ov = tmp_path / "agent_anchor"
    for i, leaf in enumerate([
        _leaf(1000.0, 1001.0),
        _leaf(1093.5, 692.0, labels=("Total Investments", "Total Money Market Funds")),
        _leaf(1093.5, 692.0),
        _leaf(1.0, 1.0, basis="published_rows"),
    ]):
        p = ov / str(i) / "2026-03-31.json"
        p.parent.mkdir(parents=True)
        leaf["cik"] = str(i)
        p.write_text(json.dumps(leaf), encoding="utf-8")
    (ov / "9").mkdir(); (ov / "9" / "x.json").write_text("{bad", encoding="utf-8")
    out_csv = tmp_path / "unresolved.csv"
    counts = backfill(ov, out_csv, write=True)
    assert counts == {"published_rows": 1, "investments_ex_cash": 1, "unresolved": 1,
                      "already_set": 1, "invalid": 1}
    assert json.loads((ov / "0" / "2026-03-31.json").read_text(encoding="utf-8"))["basis"] == "investments_ex_cash"
    assert json.loads((ov / "1" / "2026-03-31.json").read_text(encoding="utf-8"))["basis"] == "published_rows"
    assert "basis" not in json.loads((ov / "2" / "2026-03-31.json").read_text(encoding="utf-8"))
    rows = list(csv.DictReader(out_csv.open(encoding="utf-8")))
    assert [r["cik"] for r in rows] == ["0000000002"]
    # dry run changes nothing
    (ov / "0" / "2026-03-31.json").write_text(json.dumps(_leaf(1000.0, 1001.0)), encoding="utf-8")
    backfill(ov, out_csv, write=False)
    assert "basis" not in json.loads((ov / "0" / "2026-03-31.json").read_text(encoding="utf-8"))
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/test_backfill_anchor_basis.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement `scripts/backfill_anchor_basis.py`**

```python
"""One-shot, idempotent backfill of `basis` on existing anchor leaves (spec 2026-09-07 s.2).

Deterministic rules, using only the leaf's own numbers:
  investments_ex_cash : grand_total within 0.5% of the leaf's companyfacts_fv
  published_rows      : grand_total > companyfacts_fv * 1.005 AND at least one component label
                        mentions cash / money market / short-term / treasury / sweep
  unresolved          : anything else (no companyfacts_fv, wider with no cash label, below the tag)
                        -> listed for the anchor lane; leaf left untouched (the gate ignores it).

    python scripts/backfill_anchor_basis.py [--dry-run] [--overrides-dir DIR] [--out CSV]
ASCII-only.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pipeline import config                                   # noqa: E402
from pipeline.anchor_leaf import BASES, validate_anchor_leaf   # noqa: E402

_TOL = 0.005
_CASH_LABEL = re.compile(r"cash|money market|short-?term|treasur|sweep", re.I)
OUT_COLUMNS = ["cik", "target_quarter", "grand_total", "companyfacts_fv", "method", "reason"]


def _num(x):
    return float(x) if isinstance(x, (int, float)) and not isinstance(x, bool) else None


def classify_leaf(leaf: dict) -> str:
    gt, cf = _num(leaf.get("grand_total")), _num(leaf.get("companyfacts_fv"))
    if gt is None or cf is None or cf <= 0:
        return ""
    if abs(gt - cf) <= _TOL * cf:
        return "investments_ex_cash"
    labels = " ".join(str(c.get("label") or "") for c in (leaf.get("components") or [])
                      if isinstance(c, dict))
    if gt > cf * (1 + _TOL) and _CASH_LABEL.search(labels):
        return "published_rows"
    return ""


def _reason(leaf: dict) -> str:
    gt, cf = _num(leaf.get("grand_total")), _num(leaf.get("companyfacts_fv"))
    if gt is None or cf is None or cf <= 0:
        return "no companyfacts_fv on leaf"
    if gt < cf * (1 - _TOL):
        return "grand_total below companyfacts tag"
    return "grand_total wider than companyfacts tag but no cash-like component label"


def backfill(overrides_dir: Path, out_csv: Path, *, write: bool) -> dict:
    counts = {"published_rows": 0, "investments_ex_cash": 0, "unresolved": 0,
              "already_set": 0, "invalid": 0}
    unresolved: list[dict] = []
    for p in sorted(Path(overrides_dir).glob("*/*.json")):
        try:
            leaf = json.loads(p.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            counts["invalid"] += 1
            continue
        if not isinstance(leaf, dict):
            counts["invalid"] += 1
            continue
        if str(leaf.get("basis") or "") in BASES:
            counts["already_set"] += 1
            continue
        basis = classify_leaf(leaf)
        if basis:
            candidate = {**leaf, "basis": basis}
            errs = [e for e in validate_anchor_leaf(candidate) if "mislabelled" in e]
            if errs:
                basis = ""
        if not basis:
            counts["unresolved"] += 1
            unresolved.append({"cik": str(leaf.get("cik") or p.parent.name).zfill(10),
                               "target_quarter": leaf.get("target_quarter") or p.stem,
                               "grand_total": leaf.get("grand_total"),
                               "companyfacts_fv": leaf.get("companyfacts_fv"),
                               "method": leaf.get("method"), "reason": _reason(leaf)})
            continue
        counts[basis] += 1
        if write:
            leaf["basis"] = basis
            p.write_text(json.dumps(leaf, indent=2), encoding="utf-8")
    out_csv = Path(out_csv)
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    with out_csv.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=OUT_COLUMNS)
        w.writeheader()
        w.writerows(unresolved)
    return counts


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Backfill anchor-leaf basis (spec 2026-09-07 s.2).")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--overrides-dir", type=Path, default=config.AGENT_ANCHOR_OVERRIDES_DIR)
    ap.add_argument("--out", type=Path,
                    default=config.OUTPUT_DIR / "agent_anchor" / "basis_backfill_unresolved.csv")
    a = ap.parse_args(argv)
    counts = backfill(a.overrides_dir, a.out, write=not a.dry_run)
    print(json.dumps({"dry_run": a.dry_run, "counts": counts, "unresolved_csv": str(a.out)}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run the test**

Run: `pytest tests/test_backfill_anchor_basis.py -v`
Expected: 2 PASS.

- [ ] **Step 5: Dry-run against the real store and record the counts**

Run: `python scripts/backfill_anchor_basis.py --dry-run`
Expected: JSON with counts over 67 leaves; note the numbers for the changelog (Task 12). Do NOT write yet -- the live backfill is part of the rollout (Task 12 Step 1) so the rebuild sees a single consistent state.

- [ ] **Step 6: Commit**

```bash
git add scripts/backfill_anchor_basis.py tests/test_backfill_anchor_basis.py
git commit -m "feat: backfill script for anchor-leaf basis

- deterministic classify_leaf from the leaf's own grand_total / companyfacts_fv / component labels
- unresolved leaves listed for the anchor lane; dry-run by default in this commit (live run in rollout)

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_012y9HXDTAq1SHqB5GKmjmc1"
```

---

### Task 6: `fund_financials.cash_equivalents_at_fair_value` from cached companyfacts

**Files:**
- Modify: `pipeline/extract_companyfacts.py` (`_PORTFOLIO_CONCEPTS`)
- Modify: `pipeline/fund_financials.py` (`OUTPUT_COLUMNS`)
- Test: `tests/test_fund_financials.py` (pinned `_EXTENDED_FIELDS` set, around line 1835)

**Interfaces:**
- New fund_financials column `cash_equivalents_at_fair_value` (USD, instant), companyfacts rows only. Concepts: exact `CashEquivalentsAtCarryingValue`, `MoneyMarketFundsAtCarryingValue`; no fallback (the balance-sheet `CashAndCashEquivalentsAtCarryingValue` includes bank cash and would overstate).

- [ ] **Step 1: Update the pinned test (failing first)**

In `tests/test_fund_financials.py` around line 1844, add `"cash_equivalents_at_fair_value",` to the `expected` set next to `"investments_at_cost",`.

Run: `pytest tests/test_fund_financials.py -q -k "EXTENDED_FIELDS or extended_fields"`
Expected: FAIL (set mismatch).

- [ ] **Step 2: Implement**

In `pipeline/extract_companyfacts.py` `_PORTFOLIO_CONCEPTS`, after the `investments_at_cost` entry:

```python
    # Fund-level cash equivalents the filer tags separately from investments (money-market
    # sweeps, T-bills held for cash management). With investments_at_fair_value this forms the
    # deterministic PUBLISHED-ROWS anchor (spec 2026-09-07 s.2). No fallback on purpose:
    # CashAndCashEquivalentsAtCarryingValue includes bank cash and would overstate.
    "cash_equivalents_at_fair_value": {
        "exact": ["CashEquivalentsAtCarryingValue", "MoneyMarketFundsAtCarryingValue"],
        "fallback": [],
        "unit": "USD", "instant": True,
    },
```

In `pipeline/fund_financials.py` `OUTPUT_COLUMNS`, after `"investments_at_cost",` add `"cash_equivalents_at_fair_value",`.

- [ ] **Step 3: Run the tests**

Run: `pytest tests/test_fund_financials.py tests/test_validate_fund_financials.py -q`
Expected: all pass.

- [ ] **Step 4: Rebuild fund_financials from cache and check coverage (read-only query)**

```
python scripts/rebuild_outputs.py --financials
```
Then:
```
duckdb -c "SELECT count(*) n, count(cash_equivalents_at_fair_value) n_cash, count(investments_at_fair_value) n_ifv FROM read_csv_auto('data/output/fund_financials.csv', sample_size=-1) WHERE source='companyfacts' AND report_date >= '2025-12-31'"
```
(If the `duckdb` CLI is not on PATH, use `python -c "import duckdb; print(duckdb.sql(\"...\"))"` with the same SQL.) Record `n_cash` vs `n_ifv` for the changelog. Expected: n_cash well below n_ifv (most filers do not tag it); that is fine -- the anchor is used only where present.

- [ ] **Step 5: Commit**

```bash
git add pipeline/extract_companyfacts.py pipeline/fund_financials.py tests/test_fund_financials.py
git commit -m "feat: fund_financials.cash_equivalents_at_fair_value from cached companyfacts

- concepts CashEquivalentsAtCarryingValue / MoneyMarketFundsAtCarryingValue, no bank-cash fallback
- feeds the companyfacts_fv_plus_cash published-rows anchor; rebuilt cache-only

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_012y9HXDTAq1SHqB5GKmjmc1"
```

---

### Task 7: GAV on the published basis + STRONG-anchor bands

**Files:**
- Modify: `pipeline/validate_holdings.py` (`check_gav_reconciliation` SQL around lines 1330-1350; status bands around lines 1431-1448)
- Test: `tests/test_validate_holdings.py`

**Interfaces:**
- `gav_ratio_adjusted` = `sum_holdings_fv / comparison_value` always; `sum_holdings_fv_ex_sub` and `has_subsidiary_positions` columns kept (informational).
- BDC status on `comparison_confidence == "STRONG"`: WARN outside [0.98, 1.02], FAIL outside [0.95, 1.05]. MODERATE/WEAK unchanged (WARN outside [0.8, 1.2], FAIL outside [0.3, 5.0]).

- [ ] **Step 1: Rewrite/add tests (failing first)**

In `tests/test_validate_holdings.py`, replace `test_ex_sub_ratio_excludes_subsidiary` (line ~4279) with:

```python
    def test_adjusted_ratio_is_published_basis(self):
        """Spec 2026-09-07 s.1: GAV sums every row, subsidiary rows included. The ex_sub
        column stays informational. 8M vs 5M anchor -> 1.6 on BOTH ratios -> FAIL on a
        STRONG anchor."""
        holdings = _make_unified_df([
            {"cik": "100", "entity_name": "BDC A", "report_date": "2024-03-31",
             "fair_value": "5000000", "source": "bdc", "is_subsidiary": "0"},
            {"cik": "100", "entity_name": "BDC A", "report_date": "2024-03-31",
             "fair_value": "3000000", "source": "bdc", "is_subsidiary": "1"},
        ])
        ff = pd.DataFrame([{"cik": "100", "report_date": "2024-03-31",
                            "investments_at_fair_value": "5000000", "total_assets": "6000000"}])
        result = check_gav_reconciliation(holdings, fund_financials_df=ff)
        assert abs(float(result.iloc[0]["gav_ratio"]) - 1.6) < 0.01
        assert abs(float(result.iloc[0]["gav_ratio_adjusted"]) - 1.6) < 0.01
        assert float(result.iloc[0]["sum_holdings_fv_ex_sub"]) == 5000000.0
        assert int(result.iloc[0]["has_subsidiary_positions"]) == 1
        assert result.iloc[0]["reconciliation_status"] == "FAIL"

    def test_strong_anchor_bands_warn_2pct_fail_5pct(self):
        def _run(fv, ifv=None, ta="10000000"):
            holdings = _make_unified_df([
                {"cik": "100", "entity_name": "BDC A", "report_date": "2024-03-31",
                 "fair_value": fv, "source": "bdc", "is_subsidiary": "0"}])
            ffrow = {"cik": "100", "report_date": "2024-03-31", "total_assets": ta}
            if ifv is not None:
                ffrow["investments_at_fair_value"] = ifv
            res = check_gav_reconciliation(holdings, fund_financials_df=pd.DataFrame([ffrow]))
            return res.iloc[0]["comparison_confidence"], res.iloc[0]["reconciliation_status"]
        assert _run("1010000", ifv="1000000") == ("STRONG", "PASS")     # 1.01
        assert _run("1030000", ifv="1000000") == ("STRONG", "WARN")     # 1.03
        assert _run("1060000", ifv="1000000") == ("STRONG", "FAIL")     # 1.06
        assert _run("940000", ifv="1000000") == ("STRONG", "FAIL")      # 0.94
        conf, status = _run("1060000", ta="1000000")                     # total_assets only
        assert conf == "MODERATE" and status == "PASS"                   # 1.06 within 0.8-1.2
```

`test_no_subsidiary_passthrough` stays as is (it holds under the new numerator).

- [ ] **Step 2: Run to verify failures**

Run: `pytest tests/test_validate_holdings.py -q -k "published_basis or strong_anchor_bands or passthrough"`
Expected: the two new tests FAIL.

- [ ] **Step 3: Implement**

In the SQL of `check_gav_reconciliation`:
- `gav_ratio_adjusted`: replace the two-branch CASE with
  `CASE WHEN comparison_value > 0 THEN ROUND(sum_holdings_fv / comparison_value, 4) END AS gav_ratio_adjusted,`
- In the `flag` CASE (the `over_coverage` / `under_coverage` branches) and in the `gav_evidence_scope` CASE (`source_fv_present_not_indexable` branch), replace every
  `(CASE WHEN has_subsidiary_positions = 1 THEN sum_holdings_fv_ex_sub ELSE sum_holdings_fv END)` with `sum_holdings_fv`.
- In the pandas block, replace
  ```python
  numerator = pd.to_numeric(result.get("sum_holdings_fv_ex_sub"), errors="coerce")
  if "has_subsidiary_positions" in result.columns: ... numerator = numerator.where(has_sub, ...)
  ```
  with
  ```python
  # Published basis (spec 2026-09-07 s.1): every row counts; ex_sub is informational only.
  numerator = pd.to_numeric(result.get("sum_holdings_fv"), errors="coerce")
  ```
- After the existing BDC WARN assignment (`(ratio < 0.8) | (ratio > 1.2)`), add:

```python
        # STRONG anchor (companyfacts investments_at_fair_value): the published-basis numerator
        # should match a filer-tagged total tightly. WARN > 2%, FAIL > 5% (spec s.3).
        strong = comparison_source == "investments_at_fair_value"
        status[(holdings_source == "bdc") & strong & status.eq("PASS")
               & ((ratio < 0.98) | (ratio > 1.02))] = "WARN"
        status[(holdings_source == "bdc") & strong & ((ratio < 0.95) | (ratio > 1.05))] = "FAIL"
```

Update the log lines that mention "0.8-1.2x" only if they break; they are informational.

- [ ] **Step 4: Run the tests**

Run: `pytest tests/test_validate_holdings.py -q`
Expected: all pass. Any other test asserting a BDC status of PASS/WARN at a ratio between 1.02 and 1.2 on a STRONG anchor must be updated to the new band (state the change in the commit body).

- [ ] **Step 5: Commit**

```bash
git add pipeline/validate_holdings.py tests/test_validate_holdings.py
git commit -m "feat: GAV on the published basis with tight STRONG-anchor bands

- gav_ratio_adjusted and flags use sum_holdings_fv for every fund; ex_sub column kept informational
- STRONG anchors: WARN outside 0.98-1.02, FAIL outside 0.95-1.05; MODERATE/WEAK unchanged

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_012y9HXDTAq1SHqB5GKmjmc1"
```

---

### Task 8: Surface `fv_conservation` fails as `fv_conservation_fail`

**Files:**
- Modify: `scripts/shadow_validation_runner.py` (surface CASE and allow-list around lines 244-275; header comment around line 76)
- Test: `tests/test_shadow_adapter.py` (if it pins surface labels; otherwise none)

- [ ] **Step 1: Implement**

In the `surface` allow-list tuple add `'fv_conservation_fail'`. Replace the `cons_superseded` branch:

```sql
                    -- fv_conservation on the PUBLISHED basis (2026-09-07): the numerator now
                    -- equals the headline, so a fail is a headline defect. Surfaced (advisory
                    -- lane). The 2026-06-16 "~80% false positive" assessment was made on the
                    -- excluding basis and is re-measured in the rollout.
                    WHEN l.engine='conservation' AND l.rule_name='fv_conservation' AND l.status='fail'
                         THEN 'fv_conservation_fail'
                    WHEN l.engine='conservation' AND l.status='fail' THEN 'cons_superseded'
```

Update the header comment block: replace the `cons_superseded` description with
`#   fv_conservation_fail : published-basis FV conservation fail (numerator == headline) -> surfaced`
and keep `cons_superseded` described as "any other conservation fail (none expected)".

- [ ] **Step 2: Run the runner's tests**

Run: `pytest tests/test_shadow_adapter.py tests/test_shadow_identity_rules.py -q`
Expected: pass. If a test enumerates the surface allow-list, add the new label to it.

- [ ] **Step 3: Commit**

```bash
git add scripts/shadow_validation_runner.py tests/test_shadow_adapter.py
git commit -m "feat: surface published-basis fv_conservation fails

- fv_conservation_fail replaces cons_superseded for the FV rule (numerator == headline now)
- advisory lane; FP rate re-measured in rollout before any lane change

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_012y9HXDTAq1SHqB5GKmjmc1"
```

---

### Task 9: Acceptance: over-inclusion metric, anchor basis per fund, thresholds v3

**Files:**
- Modify: `pipeline/quarter_acceptance.py`
- Modify: `data/reference/quarter_acceptance_thresholds.json`
- Test: `tests/test_quarter_acceptance.py`

**Interfaces:**
- Ledger conservation rows carry `mechanism = "<anchor_used>:<anchor_basis>"`; acceptance parses `anchor_basis = mechanism.split(":")[-1]`.
- `metrics["conservation"]["over_inclusion_fv_m"]`, `["over_inclusion_fv_share_pct"]`; per fund `over_inclusion_fv_m` (string, 6 dp like `fund_fv_m`) and `anchor_basis`. `FUNDS_COLUMNS` gains both, after `conservation_residual_pct`.
- Per-fund over-inclusion: for `status == "fail"` and `residual > 0`: `fund_fv_m - fund_fv_m / (1 + residual/100)`; else 0.
- Thresholds v3 adds `over_inclusion_fv_share` (`<= 0.5`) and `unfinished_investigations` (`investigations.n_stale <= 0`).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_quarter_acceptance.py`:

```python
def test_over_inclusion_metric_and_anchor_basis(tmp_path):
    """Bain Q1-26 shape: fund FV 2221.6M at +22.4% residual -> 406.5M over-included.
    An undershoot contributes 0. Share is against cohort FV."""
    ciks = ["0000000001", "0000000002", "0000000003"]
    kw = _setup(tmp_path, ciks=ciks,
                holdings_rows=[("0000000001", Q, 2_221_600_000.0),
                               ("0000000002", Q, 1_000_000_000.0),
                               ("0000000003", Q, 778_400_000.0)],
                ledger_rows=[
                    {**_cons_row("0000000001", "fail", "22.4"), "mechanism": "verified_override:published_rows"},
                    {**_cons_row("0000000002", "fail", "-3.0"), "mechanism": "companyfacts_fv:investments_ex_cash"},
                    {**_cons_row("0000000003", "pass", "0.1"), "mechanism": "companyfacts_fv_plus_cash:published_rows"},
                ])
    res = qa.compute_acceptance(target_quarter=Q, **kw)
    m = res["metrics"]["conservation"]
    assert abs(m["over_inclusion_fv_m"] - 406.5) < 0.2
    assert abs(m["over_inclusion_fv_share_pct"] - 100 * 406.5 / 4000.0) < 0.01
    funds = {f["cik"]: f for f in res["_funds"]}
    assert abs(float(funds["0000000001"]["over_inclusion_fv_m"]) - 406.5) < 0.2
    assert float(funds["0000000002"]["over_inclusion_fv_m"]) == 0.0
    assert funds["0000000001"]["anchor_basis"] == "published_rows"
    assert funds["0000000002"]["anchor_basis"] == "investments_ex_cash"
    assert funds["0000000003"]["anchor_basis"] == "published_rows"


def test_over_inclusion_gate_from_thresholds(tmp_path):
    ciks = ["0000000001", "0000000002"]
    checks = [{"id": "over_inclusion_fv_share", "metric": "conservation.over_inclusion_fv_share_pct",
               "op": "<=", "value": 0.5}]
    kw = _setup(tmp_path, ciks=ciks,
                holdings_rows=[("0000000001", Q, 1_010_000_000.0), ("0000000002", Q, 990_000_000.0)],
                ledger_rows=[_cons_row("0000000001", "fail", "1.01"), _cons_row("0000000002", "pass")])
    kw["thresholds_path"] = _thresholds(tmp_path / "t3.json", checks=checks)
    res = qa.compute_acceptance(target_quarter=Q, **kw)
    # over-inclusion = 1010 - 1010/1.0101 = 10.1M of 2000M = 0.505% -> FAIL at 0.5
    assert res["checks"][0]["pass"] is False and res["verdict"] == "FAIL"
    kw["thresholds_path"] = _thresholds(tmp_path / "t4.json", checks=[{**checks[0], "value": 0.51}])
    assert qa.compute_acceptance(target_quarter=Q, **kw)["verdict"] == "PASS"


def test_thresholds_v3_file_has_nine_checks():
    from pipeline import config
    t = json.loads(config.QUARTER_ACCEPTANCE_THRESHOLDS_FILE.read_text(encoding="utf-8-sig"))
    ids = [c["id"] for c in t["checks"]]
    assert t["version"] == 3
    assert ids == ["fund_coverage", "reconcile_rate", "flagged_fv_share", "source_blocking_fv_share",
                   "verified_fv_share", "promoted_rule_drift", "promoted_rule_health",
                   "over_inclusion_fv_share", "unfinished_investigations"]
    by_id = {c["id"]: c for c in t["checks"]}
    assert by_id["over_inclusion_fv_share"] == {
        "id": "over_inclusion_fv_share", "metric": "conservation.over_inclusion_fv_share_pct",
        "op": "<=", "value": 0.5, "note": by_id["over_inclusion_fv_share"]["note"]}
    assert by_id["unfinished_investigations"]["metric"] == "investigations.n_stale"
    assert by_id["unfinished_investigations"]["op"] == "<=" and by_id["unfinished_investigations"]["value"] == 0
```

- [ ] **Step 2: Run to verify failures**

Run: `pytest tests/test_quarter_acceptance.py -q -k "over_inclusion or v3"`
Expected: 3 FAIL.

- [ ] **Step 3: Implement**

`pipeline/quarter_acceptance.py`:

`FUNDS_COLUMNS` -> insert `"over_inclusion_fv_m", "anchor_basis",` after `"conservation_residual_pct",`.

In the ledger loop, store the mechanism too. Change the `cons_status` type to `dict[str, tuple[str, float | None, str]]` and the assignment to:

```python
                    cons_status[cik] = (
                        str(row.get("status") or ""),
                        _f(metric) if metric not in (None, "") else None,
                        str(row.get("mechanism") or "").split(":")[-1],
                    )
```
Update the three comprehensions that unpack `(s, _)` to `(s, _, _)` / `(s, _r, _b)` accordingly, and the `flagged_fv_m` one to `for c, (s, _, _) in cons_status.items()`.

After `flagged_fv_m = ...` add:

```python
    # Over-inclusion (spec 2026-09-07 s.3): FV above the anchor across failed funds. With the
    # published-basis numerator, value_sum == fund FV, so over = fv - fv / (1 + r/100).
    def _over(c: str) -> float:
        s, r, _ = cons_status.get(c, ("", None, ""))
        fv = fv_in_quarter.get(c, 0.0)
        if s == "fail" and r is not None and r > 0 and fv > 0:
            return fv - fv / (1.0 + r / 100.0)
        return 0.0
    over_by_fund = {c: _over(c) for c in cons_status}
    over_inclusion_fv_m = sum(over_by_fund.values())
```

In the per-fund loop change `status, residual = cons_status.get(cik, ("", None))` to
`status, residual, basis = cons_status.get(cik, ("", None, ""))` and add to the fund dict after `conservation_residual_pct`:

```python
                "over_inclusion_fv_m": f"{over_by_fund.get(cik, 0.0):.6f}",
                "anchor_basis": basis,
```

In `metrics["conservation"]` add:

```python
            "over_inclusion_fv_m": round(over_inclusion_fv_m, 3),
            "over_inclusion_fv_share_pct": _share(over_inclusion_fv_m),
```

Replace `data/reference/quarter_acceptance_thresholds.json` with version 3: keep the v2 `calibration_note` text verbatim and append this sentence to it: `" v3 (2026-09-07, provisional): numerator moved to the PUBLISHED basis (spec docs/superpowers/specs/2026-09-07-published-basis-conservation-gate-design.md); two checks added -- over_inclusion_fv_share <= 0.5 and unfinished_investigations <= 0. Q1 2026 re-run under v3 is EXPECTED to fail both FV-share checks; that result is the proof the gate sees the $4.09B over-inclusion, not a regression. Calibrate to v4 on Q2 2026 actuals."`. Set `"version": 3`, `"calibration": "provisional"`, keep `assessability` and the seven existing checks unchanged, and append:

```json
    {
      "id": "over_inclusion_fv_share",
      "metric": "conservation.over_inclusion_fv_share_pct",
      "op": "<=",
      "value": 0.5,
      "note": "FV above the anchor across conservation-failed cohort funds, pct of cohort FV (published basis)"
    },
    {
      "id": "unfinished_investigations",
      "metric": "investigations.n_stale",
      "op": "<=",
      "value": 0,
      "note": "cohort CIKs whose staged rules are newer than their last apply/gate for the quarter"
    }
```

- [ ] **Step 4: Run the tests**

Run: `pytest tests/test_quarter_acceptance.py tests/test_fleet_acceptance.py -q`
Expected: all pass. Any test in `test_fleet_acceptance.py` or elsewhere that pins `version == 2` or seven checks must be updated to v3 / nine.

- [ ] **Step 5: Commit**

```bash
git add pipeline/quarter_acceptance.py data/reference/quarter_acceptance_thresholds.json tests/test_quarter_acceptance.py tests/test_fleet_acceptance.py
git commit -m "feat: acceptance over-inclusion metric + anchor basis; thresholds v3

- conservation.over_inclusion_fv_m/share from ledger residuals on the published basis; per-fund columns
- thresholds v3 (provisional): over_inclusion_fv_share <= 0.5, unfinished_investigations <= 0
- Q1 2026 is expected to FAIL under v3 (recorded in calibration_note)

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_012y9HXDTAq1SHqB5GKmjmc1"
```

---

### Task 10: Quarter-scope carry-over re-test on promoted rules

**Files:**
- Modify: `pipeline/agent_rule.py` (new `match_rows_outside_scope`; `validate_rule` accepts `carryover_reviewed`)
- Modify: `pipeline/agent_promoted.py` (`apply_promoted_rules` drift classification)
- Test: `tests/test_agent_rule.py`, `tests/test_agent_promoted.py`, `tests/test_quarter_acceptance.py`

**Interfaces:**
- `agent_rule.match_rows_outside_scope(work, predicate_sql, scope) -> list[tuple[rid, fv, report_date]]`; empty for `scope.quarters == ["all"]` or no predicate.
- Rule JSON optional key `carryover_reviewed: {"<YYYY-MM-DD>": {"verdict": "not_applicable", "evidence": [ {...}, ... ]}}`; `validate_rule` rejects any other shape.
- Audit `drift` value `scope_carryover`; message `scope_carryover: predicate matches N rows / FV X outside scope in {quarter: {rows, fv}}`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_agent_rule.py`:

```python
from pipeline.agent_rule import match_rows_outside_scope


def test_match_rows_outside_scope():
    df = pd.DataFrame([
        _h("1", "2025-12-31", 10.0, dims="x|legalentityaxis=FooCloMember"),
        _h("1", "2026-03-31", 20.0, dims="x|legalentityaxis=FooCloMember"),
        _h("1", "2026-03-31", 30.0),
    ])
    df["_rid"] = range(len(df))
    out = match_rows_outside_scope(df, _CLO, {"quarters": ["2025-12-31"]})
    assert [(r[1], r[2]) for r in out] == [(20.0, "2026-03-31")]
    assert match_rows_outside_scope(df, _CLO, {"quarters": ["all"]}) == []
    assert match_rows_outside_scope(df, None, {"quarters": ["2025-12-31"]}) == []


def test_carryover_reviewed_shape_validated():
    ok = _rule(scope={"quarters": ["2025-12-31"]},
               carryover_reviewed={"2026-03-31": {"verdict": "not_applicable",
                                                  "evidence": [{"source": "filing", "quote": "no CLO in Q1"}]}})
    assert validate_rule(ok) == []
    bad = _rule(carryover_reviewed={"2026-03-31": {"verdict": "fine"}})
    assert any("carryover_reviewed" in e for e in validate_rule(bad))
    bad2 = _rule(carryover_reviewed={"q1": {"verdict": "not_applicable", "evidence": [{"source": "x", "quote": "y"}]}})
    assert any("carryover_reviewed" in e for e in validate_rule(bad2))
```

Append to `tests/test_agent_promoted.py`:

```python
def _q_rows(cik="0000000123"):
    return pd.DataFrame([
        {"cik": cik, "source": "bdc", "report_date": "2025-12-31", "issuer_name": "Dup Row",
         "entity_name": "Fund A", "fair_value": 100.0, "bdc_dimensions_raw": "x=y"},
        {"cik": cik, "source": "bdc", "report_date": "2026-03-31", "issuer_name": "Dup Row",
         "entity_name": "Fund A", "fair_value": 355.9, "bdc_dimensions_raw": "x=y"},
        {"cik": cik, "source": "bdc", "report_date": "2026-03-31", "issuer_name": "Keep",
         "entity_name": "Fund A", "fair_value": 1.0, "bdc_dimensions_raw": "x=y"},
    ])


def test_apply_promoted_rules_scope_carryover_flagged():
    """TCW VII Q1-26 shape: a Q4-scoped exclusion whose predicate still matches Q1 rows."""
    rule = _valid_rule(predicate="issuer_name = 'Dup Row'", scope={"quarters": ["2025-12-31"]},
                       measured_impact={"2025-12-31": {"rows": 1, "fv": 100.0}})
    out, audits = ap.apply_promoted_rules(_q_rows(), {"0000000123": [rule]})
    assert len(out) == 2                                  # only the in-scope row removed
    assert audits[0]["drift"] == "scope_carryover"
    assert "2026-03-31" in audits[0]["message"] and "355.9" in audits[0]["message"]


def test_apply_promoted_rules_scope_carryover_excused_by_review():
    rule = _valid_rule(predicate="issuer_name = 'Dup Row'", scope={"quarters": ["2025-12-31"]},
                       measured_impact={"2025-12-31": {"rows": 1, "fv": 100.0}},
                       carryover_reviewed={"2026-03-31": {"verdict": "not_applicable",
                                                          "evidence": [{"source": "filing", "quote": "Q1 rows are distinct lots"}]}})
    _, audits = ap.apply_promoted_rules(_q_rows(), {"0000000123": [rule]})
    assert audits[0]["drift"] == ""


def test_apply_promoted_rules_all_scope_and_row_add_exempt_from_carryover():
    rule_all = _valid_rule(predicate="issuer_name = 'Dup Row'",
                           measured_impact={"2025-12-31": {"rows": 2, "fv": 455.9}})
    _, audits = ap.apply_promoted_rules(_q_rows(), {"0000000123": [rule_all]})
    assert audits[0]["drift"] == ""
    add = _valid_rule(rule_type="row_add", action="add", predicate=None, rule_id="add1",
                      scope={"quarters": ["2025-12-31"]},
                      positions=[{"report_date": "2025-12-31", "issuer_name": "New",
                                  "fair_value": 5.0, "bdc_dimensions_raw": "a=b",
                                  "source_row_id": "s"}])
    del add["predicate_sql"]
    _, audits = ap.apply_promoted_rules(_q_rows(), {"0000000123": [add]})
    assert audits[0]["drift"] == ""
```

Append to `tests/test_quarter_acceptance.py`:

```python
def test_scope_carryover_counts_as_drift(tmp_path):
    kw = _setup(tmp_path, ledger_rows=[_cons_row(c, "pass") for c in
                                       ("0000000001", "0000000002", "0000000003")],
                audit_rows=[{"layer": "unified_agent_rules", "cik": "0000000001", "rule_id": "r",
                             "rule_type": "row_exclusion", "status": "ok", "rows_changed": 1,
                             "drift": "scope_carryover", "message": "m"}])
    res = qa.compute_acceptance(target_quarter=Q, **kw)
    assert res["metrics"]["promoted_rules"]["n_drift"] == 1
    assert res["checks"][2]["pass"] is False
```

- [ ] **Step 2: Run to verify failures**

Run: `pytest tests/test_agent_rule.py tests/test_agent_promoted.py tests/test_quarter_acceptance.py -q -k "carryover or outside_scope"`
Expected: ImportError / assertion failures; the acceptance test may already pass (drift counting is generic) -- that is fine.

- [ ] **Step 3: Implement**

`pipeline/agent_rule.py`, after `_match_rows`:

```python
def match_rows_outside_scope(work: pd.DataFrame, predicate_sql, scope) -> list:
    """Rows matching the predicate in quarters NOT in scope.quarters (carry-over re-test,
    spec 2026-09-07 s.4d). Empty for 'all' scope or no predicate. Same row tuple as _match_rows."""
    qs = (scope or {}).get("quarters") or ["all"]
    if "all" in qs or not (predicate_sql and str(predicate_sql).strip()):
        return []
    conn = duckdb.connect()
    conn.register("h", work)
    q = (f"SELECT _rid, TRY_CAST(fair_value AS DOUBLE) AS fv, {_REPORT_DATE_KEY} AS rd "
         f"FROM h WHERE ({predicate_sql}) AND NOT ({_scope_sql(scope)})")
    try:
        return conn.execute(q).fetchall()
    finally:
        conn.close()
```

In `validate_rule`, before `return errs`:

```python
    cr = obj.get("carryover_reviewed")
    if cr is not None:
        if not isinstance(cr, dict):
            errs.append("carryover_reviewed must be an object {quarter: {verdict, evidence}}")
        else:
            for q, v in cr.items():
                if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(q)):
                    errs.append(f"carryover_reviewed key {q!r} must be an ISO report_date")
                if (not isinstance(v, dict) or v.get("verdict") != "not_applicable"
                        or not isinstance(v.get("evidence"), list) or not v.get("evidence")):
                    errs.append(f"carryover_reviewed[{q!r}] must be "
                                "{'verdict': 'not_applicable', 'evidence': [non-empty]}")
```

`pipeline/agent_promoted.py`, in `apply_promoted_rules`, inside the `for r, a in zip(rules, rule_audits):` loop after the superseded block and before `audits.append(...)`:

```python
            # Carry-over re-test (spec 2026-09-07 s.4d): a quarter-scoped predicate rule that
            # still matches rows OUTSIDE its scope is a rule that expired silently (TCW VII:
            # a Q3/Q4-25 dedup matched 27 Q1-26 rows / $355.9M and did nothing). Flag as drift
            # so promoted_rule_drift forces a decision: extend scope + re-gate, or excuse the
            # quarter with carryover_reviewed evidence. row_add has no predicate; 'all' is exempt.
            if (not drift and a.get("status") == "ok"
                    and str(r.get("rule_type")) in ("row_exclusion", "dedup", "value_rescale",
                                                     "value_expression")):
                from pipeline.agent_rule import _per_quarter, match_rows_outside_scope
                probe = sub.reset_index(drop=True).copy()
                probe["_rid"] = range(len(probe))
                pq = _per_quarter(match_rows_outside_scope(probe, r.get("predicate_sql"),
                                                           r.get("scope")))
                reviewed = set(str(k) for k in (r.get("carryover_reviewed") or {}))
                pq = {q: v for q, v in pq.items() if q not in reviewed}
                if pq:
                    drift = "scope_carryover"
                    n = sum(v["rows"] for v in pq.values())
                    fv_out = round(sum(v["fv"] for v in pq.values()), 2)
                    message = (f"scope_carryover: predicate matches {n} rows / FV {fv_out} outside "
                               f"scope in {pq}") + (f"; {message}" if message else "")
```

(`sub` is the pre-apply CIK slice built earlier in the loop; it still exists at this point. The `logger.warning` below the append already prints any non-empty drift.)

- [ ] **Step 4: Run the tests**

Run: `pytest tests/test_agent_rule.py tests/test_agent_promoted.py tests/test_quarter_acceptance.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add pipeline/agent_rule.py pipeline/agent_promoted.py tests/test_agent_rule.py tests/test_agent_promoted.py tests/test_quarter_acceptance.py
git commit -m "feat: re-test quarter-scoped rules outside their scope (scope_carryover drift)

- match_rows_outside_scope + carryover_reviewed excusal (validated shape)
- apply_promoted_rules flags drift=scope_carryover with matched quarters/rows/FV; row_add and 'all' exempt
- fails promoted_rule_drift so a dead rule forces a decision (TCW VII Q1 shape)

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_012y9HXDTAq1SHqB5GKmjmc1"
```

---

### Task 11: Quarter-pass runbook reads the new checks (no code change if already generic)

**Files:**
- Verify only: `scripts/run_quarter_pass.py`, `scripts/pass_preflight.py`, `scripts/reattest_quarters.py`

- [ ] **Step 1: Confirm the acceptance stage needs no change**

`run_quarter_pass._stages` invokes `python -m pipeline.quarter_acceptance --quarter Q` and copies the JSON; the v3 checks flow through. Confirm with:

```
python -m pipeline.quarter_acceptance --quarter 2026-03-31 --out "%TEMP%\qa_probe.json" --funds-out "%TEMP%\qa_probe_funds.csv"
```
(PowerShell: `$env:TEMP`.) Expected: exit code 1 (FAIL) or 2, and the JSON lists nine checks including `over_inclusion_fv_share` and `unfinished_investigations`. This runs on the CURRENT ledger (pre-rebuild), so the over-inclusion number is still on the old basis; the point is only that the plumbing works.

- [ ] **Step 2: Check preflight and reattest do not pin the check count**

Run: `rg -n "version|checks\)|len\(.*checks" scripts/pass_preflight.py scripts/reattest_quarters.py`
If either asserts `version == 2` or seven checks, change it to read the count from the thresholds file and commit with subject `fix: preflight/reattest read thresholds v3`.

---

### Task 12: Rollout -- backfill, rebuild, battery, acceptance on Q1 and Q4, FP re-measure, diff, changelog, full suite

**Files:**
- Modify: `data/overrides/agent_anchor/**/*.json` (backfill writes `basis`)
- Create: `scratch/2026-09-07_published_basis/` (session scratch; git-ignored except README)
- Modify: `docs/investigations/` topic file for conservation (create `docs/investigations/conservation_basis.md` if no fitting topic exists; register it in `scripts/split_investigations.py` TOPICS and reindex)
- Modify: `docs/agent_changelog.md` (append)

Preconditions: Plan 1 complete; Tasks 1-11 committed; no other pytest or rebuild process running (`Get-Process python | Format-Table Id,StartTime,CPU`).

- [ ] **Step 1: Live backfill of anchor basis**

```
python scripts/backfill_anchor_basis.py
python -m pytest tests/test_anchor_leaf.py -q
git add data/overrides/agent_anchor data/output/agent_anchor/basis_backfill_unresolved.csv
git commit -m "data: backfill basis on anchor leaves (spec 2026-09-07 s.2)

- <published_rows N> published_rows, <ex N> investments_ex_cash, <U> unresolved (listed for the anchor lane)
- unresolved leaves are ignored by every gate until re-adjudicated

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_012y9HXDTAq1SHqB5GKmjmc1"
```
Fill in the three counts from the script's JSON output. If `data/output/agent_anchor/` is git-ignored, drop it from the `git add`.

- [ ] **Step 2: Rebuild from cache**

```
python scripts/rebuild_outputs.py --financials
python scripts/rebuild_outputs.py --unified
```
Expected: unified rebuild completes (~60 s to a few minutes); the promoted-rule audit is written. Then, read-only:

```
duckdb -c "SELECT drift, count(*) n FROM read_csv_auto('data/output/agent_fix_application_audit.csv') GROUP BY 1"
```
Expected: a non-zero `scope_carryover` count; record the rule ids with `SELECT cik, rule_id, message FROM ... WHERE drift='scope_carryover'`. The TCW VII (0001715933) dedup rule must be among them with 27 rows (acceptance criterion 4 of the spec).

- [ ] **Step 3: Battery + acceptance on Q1 2026 through the runbook**

```
python scripts/run_quarter_pass.py --pass-id v3basis_20260907 --quarter 2026-03-31 --until acceptance
```
This runs preflight, rebuild (again, idempotent), oracle, nonaccrual, validate, provenance, shadow, queue, ledger, acceptance. Expected acceptance verdict: FAIL, with `over_inclusion_fv_share` above 0.5 and `flagged_fv_share` above 10. Copy the verdict block and the per-fund over-inclusion top 10 from `data/output/quarter_acceptance_funds.csv` (sort by `over_inclusion_fv_m` desc) into the changelog. Bain (0001899017), HPS (0001838126), TCW VII (0001715933), TCW DL (0001603480), Silver Capital (0001674760), Fidelity PCF (0001920453), GS PCC (0001920145) must appear (spec acceptance criterion 2). If any is missing, do not tune anything: record which and why (e.g. anchor now `companyfacts_fv_plus_cash` reconciles it) and continue.

Also confirm spec acceptance criterion 1 (read-only):

```
duckdb -c "WITH s AS (SELECT lpad(CAST(cik AS VARCHAR),10,'0') cik, substr(CAST(report_date AS VARCHAR),1,10) rd, sum(TRY_CAST(fair_value AS DOUBLE)) fv FROM read_parquet('data/output/private_markets_holdings.parquet') GROUP BY 1,2) SELECT count(*) n_mismatch FROM read_csv_auto('data/output/shadow/conservation_gate_results.csv') c JOIN s ON s.cik = lpad(CAST(c.cik AS VARCHAR),10,'0') AND s.rd = CAST(c.report_date AS VARCHAR) WHERE c.rule_name='fv_conservation' AND abs(c.value_sum - s.fv) > 1"
```
Expected: `n_mismatch = 0`.

Confirm spec acceptance criterion 6 (every cik is 10 digits after the rebuild; the Plan 1 padding fix applies to the promoted TCW Star row_add):

```
duckdb -c "SELECT count(*) n_bad FROM read_parquet('data/output/private_markets_holdings.parquet') WHERE NOT regexp_matches(CAST(cik AS VARCHAR), '^[0-9]{10}$')"
```
Expected: `n_bad = 0`. The `validate` stage's log must show no `CIK FORMAT` error line.

- [ ] **Step 4: Re-attest Q4 2025**

```
python scripts/reattest_quarters.py --help
```
Run it for `2025-12-31` per its usage (it appends to `data/output/acceptance_reattestation_ledger.csv`). Expected: a verdict as measured. Record the seven-to-nine check actuals. Bain Q4 must show `conservation_status = pass` (parent + subsidiary = 1.002 within band). Funds whose anchors include the subsidiary layer (1633336, 1930087) are expected to reconcile again; funds whose subsidiary rows duplicate the parent will flag. Report; do not tune.

- [ ] **Step 5: Re-measure the fv_conservation false-positive rate (read-only)**

Create `scratch/2026-09-07_published_basis/fp_remeasure.py`:

```python
"""Read-only: every cohort fv_conservation FAIL for 2025-12-31 and 2026-03-31 with the row
classes that explain the residual. Output: fp_remeasure.csv next to this script. ~10 s."""
import json
from pathlib import Path
import duckdb

ROOT = Path(__file__).resolve().parents[2]
m = json.load(open(ROOT / "data/overrides/wrapper_cohorts/v2_70_gate_verified_wrapper_manifest.json"))
ciks = [str(e["cik"] if isinstance(e, dict) else e).zfill(10) for e in m["entries"]]
con = duckdb.connect()
con.execute("CREATE TABLE cohort AS SELECT * FROM (VALUES " + ",".join(f"('{c}')" for c in ciks) + ") t(cik)")
P = f"read_parquet('{(ROOT / 'data/output/private_markets_holdings.parquet').as_posix()}')"
C = f"read_csv_auto('{(ROOT / 'data/output/shadow/conservation_gate_results.csv').as_posix()}')"
con.execute(f"""
COPY (
  WITH h AS (
    SELECT lpad(CAST(cik AS VARCHAR),10,'0') cik, substr(CAST(report_date AS VARCHAR),1,10) rd,
           ROUND(SUM(CASE WHEN upper(COALESCE(asset_category,''))='CASH' THEN fair_value END)/1e6,1) cash_mm,
           ROUND(SUM(CASE WHEN COALESCE(is_subsidiary,0)=1 THEN fair_value END)/1e6,1) sub_mm,
           ROUND(SUM(CASE WHEN corrected_fields LIKE '%_row:added%' THEN fair_value END)/1e6,1) added_mm
    FROM {P} WHERE report_date IN ('2025-12-31','2026-03-31') GROUP BY 1,2)
  SELECT lpad(CAST(c.cik AS VARCHAR),10,'0') cik, c.report_date, c.status, c.residual_pct,
         ROUND(c.value_sum/1e6,1) value_mm, ROUND(c.anchor_value/1e6,1) anchor_mm,
         ROUND((c.value_sum-c.anchor_value)/1e6,1) residual_mm,
         c.anchor_used, c.anchor_basis, h.cash_mm, h.sub_mm, h.added_mm
  FROM {C} c JOIN h ON h.cik = lpad(CAST(c.cik AS VARCHAR),10,'0') AND h.rd = CAST(c.report_date AS VARCHAR)
  WHERE c.rule_name='fv_conservation' AND c.status <> 'reconciles'
    AND lpad(CAST(c.cik AS VARCHAR),10,'0') IN (SELECT cik FROM cohort)
  ORDER BY abs(c.value_sum-c.anchor_value) DESC
) TO '{(Path(__file__).parent / 'fp_remeasure.csv').as_posix()}' (HEADER)
""")
print(con.execute(f"SELECT count(*) FROM read_csv_auto('{(Path(__file__).parent / 'fp_remeasure.csv').as_posix()}')").fetchone())
```

Run: `timeout 120 python scratch/2026-09-07_published_basis/fp_remeasure.py` (PowerShell: run it plainly; it is bounded). Classify each flagged fund-quarter by whether `residual_mm` is explained by `cash_mm`, `sub_mm`, `added_mm`, or an anchor-basis mismatch (`anchor_basis = investments_ex_cash` with `cash_mm > 0`). A flag is a TRUE positive when the residual is a real headline defect or an anchor that needs re-adjudication; it is a FALSE positive only when the published rows and the anchor both look right and still disagree. Write the table and the true/false counts to `docs/investigations/conservation_basis.md` under a dated heading with the question asked and results found; register the topic in `scripts/split_investigations.py` TOPICS if new; run `python scripts/split_investigations.py --reindex`. Decision rule for the surface label: keep `fv_conservation_fail` surfaced unless false positives exceed 50% of flags; if they do, record that and open the question for the owner instead of changing the label in this plan.

- [ ] **Step 6: Semantic diff against the active baseline**

```
python scripts/diff_outputs.py --semantic
```
Expected: deltas in `conservation_gate_results.csv` (value_sum on every cash/subsidiary fund), `validation_results_ledger.csv` (mechanism populated; statuses moved), `holdings_gav_reconciliation.csv` (adjusted ratios, STRONG statuses), `quarter_acceptance*.csv/json`, `fund_financials.csv` (new column), `agent_fix_application_audit.csv` (scope_carryover), and NO delta in `private_markets_holdings` fair values except rows added-then-skipped by the widened duplicate guard (list them; expected: the Q1 cash duplicates at Silver Capital, TCW DL, Fidelity PCF -- $1.32B class from the spec). Any FV delta outside that class is a stop-and-report. Do not refresh the baseline.

- [ ] **Step 7: Full pytest suite (quiet window)**

Check for competing processes, then:
```
python -m pytest -q --durations=50 --durations-min=0.5 2>&1 | tee scratch/2026-09-07_published_basis/full_suite.log
python scripts/diff_outputs.py --semantic
```
Expected: 0 failures; the second diff must show no artifact drift caused by the test run (conftest write guard).

- [ ] **Step 8: Changelog + memory-visible summary**

Append to `docs/agent_changelog.md`:

```markdown
## 2026-09-07 - Published-basis conservation gate SHIPPED (Plan 2); thresholds v3; Q1-2026 re-run FAILS as designed

- Spec docs/superpowers/specs/2026-09-07-published-basis-conservation-gate-design.md; plans
  docs/superpowers/plans/2026-09-07-gate-mechanics-fixes.md (Plan 1) and
  2026-09-07-published-basis-gate.md (Plan 2). Commits <first>..<last>.
- Numerator: `pipeline/published_basis.py` is the ONE definition; shadow engine,
  agent_rule.value_sum_by_quarter, agent_b2_diagnose._gate_rows,
  run_remediation.build_conservation_snapshots and GAV all sum every published row.
  `pipeline/conservation_scope.py` + 5 carve-outs retired (data/overrides/_retired/).
- Anchors: leaf `basis` required (published_rows | investments_ex_cash) with a mislabel check;
  backfill <N pub>/<N ex>/<U unresolved> of 67 leaves; engine priority override(pub) >
  override(ex_cash) > companyfacts_fv_plus_cash (new; fund_financials.cash_equivalents_at_fair_value,
  coverage <n_cash>/<n_ifv> cohort rows since 2025-12-31) > companyfacts_fv > schedule_total.
  Deviation from spec: ex-cash override outranks plain companyfacts (an override exists because
  the tag was partial). Ledger `mechanism` = anchor_used:anchor_basis (no new column; 13-col contract).
- Gates: thresholds v3 (provisional) adds over_inclusion_fv_share <= 0.5 and
  unfinished_investigations <= 0; GAV STRONG bands 2%/5%; fv_conservation fails surface as
  fv_conservation_fail (advisory). Carry-over re-test: <K> promoted rules flagged scope_carryover
  incl. 0001715933 dedup (27 rows / $355.9M).
- Q1-2026 under v3: verdict <FAIL>; over_inclusion_fv_share <x.xx>% (<$B>), flagged_fv_share
  <y.y>%, n_stale <s>. Top over-included: <table of 10>. This is the designed outcome (the gate now
  sees what the 2026-09-07 forensics saw); the v2 sign-off stands as history. Q4-2025 re-attest:
  <verdict + actuals>; Bain reconciles at <ratio>.
- FP re-measure (docs/investigations/conservation_basis.md): <T> true / <F> false of <n> flags ->
  surface label <kept|question opened>.
- diff_outputs --semantic: <summary>; holdings FV deltas limited to the widened dup-guard skips
  (<list>). Baseline NOT refreshed (owner decision pending on the new gate results).
- Full suite: <passed/skipped/failed> in <time>; zero production writes.
- NEXT (Q2 fleet prerequisites now met): anchor lane on the unresolved leaves + the cash funds
  still on an ex-cash anchor; extend-or-excuse the scope_carryover rules; Q2 pass under v3.
```

Fill every `<...>` from the measured outputs. Commit:

```bash
git add docs/agent_changelog.md docs/investigations scripts/split_investigations.py scratch/2026-09-07_published_basis/README.md
git commit -m "docs: published-basis gate rollout results (Q1 re-run FAILS as designed)

- acceptance v3 on 2026-03-31 and re-attest 2025-12-31 recorded as measured
- fv_conservation FP re-measure in docs/investigations/conservation_basis.md
- semantic diff summary; baseline not refreshed

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_012y9HXDTAq1SHqB5GKmjmc1"
```

(Create `scratch/2026-09-07_published_basis/README.md` with one line naming the session and the two scripts, per `scratch/README.md`.)
