# source_row_id Anchor Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the positional `source_row_id` / `output_row_id` ordinals published in source-reconciliation artifacts with stable, self-describing anchors (`src:{accession}:{context_id}` on the source side; the unified `row_id` on the output side), so grounding citations survive staging reorders and re-extractions.

**Architecture:** Zero-blast-radius swap: the positional ordinals stay untouched INSIDE the ~1,700-line reconciliation SQL (every join, duplicate-rank, and tie-break keeps its exact semantics). `_coerce_source_df` / `_coerce_output_df` mint anchor columns alongside the ordinals; a single post-SQL publish step in `reconcile_bdc_source_to_holdings` maps the detail frame's published id columns from ordinal to anchor after metrics are computed. All downstream artifacts (legacy CSVs, per-CIK parquets, source-only detail, worker evidence, gate grounding frames) inherit through that one chokepoint.

**Tech Stack:** Python 3.x, pandas, DuckDB, pytest. No new dependencies.

**Spec:** Continuation of `docs/superpowers/plans/2026-08-22-anchor-row-id.md` (anchor row_id migration, shipped 2026-08-22) and `docs/provenance_columns_scoping.md`. Decisions from the 2026-08-22 owner conversation, restated in full:
- Published `source_row_id` = `src:{accession_number}:{context_id}` (raw values, `:`-joined, `src:` prefix). If `(accession, context_id)` duplicates exist within one coerced frame, rows after the first get `#2`, `#3`, ... suffixes in original frame order (warn when this fires). Rows missing either part get `src-ord:{ordinal}` (fallback, warn).
- Published `output_row_id` = the unified holdings `row_id` (`ROW-<16hex>`) when the holdings frame carries a nonempty `row_id`; else the stringified ordinal (status quo, keeps test fixtures working).
- Internal SQL semantics unchanged: ordinals still drive joins/ranking; only the PUBLISHED detail columns change.
- Investigator-rule `staging:...` source_row_id dialect (agent_investigate_rules) is OUT of scope — separately minted, self-describing already.
- No leaf restamp needed: verified 2026-08-22 that ZERO live B2 correction leaves cite a reconciliation source_row_id.
- The `run_remediation.py` grounding gate already matches strings — no gate change; grounding frames built from regenerated detail artifacts carry anchors automatically.

## Global Constraints

(from AGENTS.md)
- No network calls; ASCII-only logs; no inline `python -` diagnostics (named scratch scripts only).
- No pandas `.apply()`/`.iterrows()` on large frames — mint anchors vectorized.
- Pytest write-guard blocks `data/output/` writes; artifact regeneration happens outside pytest.
- **Dirty-worktree rule:** stage ONLY the files each task names; never `git add -A`/`-u`. Pre-dirty files from other sessions (`scripts/agent_b2/*`, `pipeline/agent_promoted.py`, etc.) must not be swept into commits. `scripts/agent_b2/dispatch_preflight.py` is PRE-DIRTY: Task 4 edits it but does NOT commit it.
- Blocker accounting (AGENTS.md) reads the residual artifacts this change regenerates — the operator phase must prove counts are unchanged.
- Commit style: short subject + 2-4 bullets.

## File Structure

| File | Change | Task |
|---|---|---|
| `pipeline/source_reconciliation.py` | `_coerce_source_df` mints `source_anchor_id`; `_coerce_output_df` mints `output_anchor_id`; `_publish_anchor_row_ids` swap in `reconcile_bdc_source_to_holdings` | 1, 2, 3 |
| `tests/test_source_recon_anchor_ids.py` | new focused test file | 1, 2, 3 |
| `scripts/agent_b2/dispatch_preflight.py` | prompt line documents `src:` format (EDIT, DO NOT COMMIT — pre-dirty) | 4 |
| `docs/reference/schemas.md` | document the published id formats | 4 |
| `docs/agent_changelog.md` | dated entry (after operator phase) | 5 |
| `scratch/2026-08-22_anchor_rowid/recon_parity_gate.py` | disposable pre/post parity gate | 5 |

---

### Task 1: `_coerce_source_df` mints `source_anchor_id`

**Files:**
- Modify: `pipeline/source_reconciliation.py:1386-1408` (`_coerce_source_df`, after the `source_row_id = range(len(df))` line at :1400)
- Test: `tests/test_source_recon_anchor_ids.py` (new)

**Interfaces:**
- Consumes: the coerced source frame (has `accession_number`, `context_id`, `source_row_id` columns; `context_id` populated from the source-facts cache).
- Produces: `source_anchor_id` (str column): `src:{accession}:{context_id}`, `#k` suffix on within-frame duplicates (k>=2, original order), `src-ord:{ordinal}` when accession or context is empty. Task 3 consumes `source["source_row_id"]` + `source["source_anchor_id"]` as the ordinal→anchor mapping.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_source_recon_anchor_ids.py`:

```python
"""Tests for anchor-based published ids in source reconciliation.

Internal SQL ordinals are unchanged; these tests cover the anchor columns
minted in the coerce helpers and the published-id swap in reconcile.
"""

import pandas as pd

from pipeline.source_reconciliation import _coerce_source_df


def _source_frame(rows):
    base = {
        "cik": "0001418076", "entity_name": "Test BDC",
        "accession_number": "0001418076-26-000001", "form_type": "10-Q",
        "filing_date": "2026-05-10", "report_date": "2026-03-31",
        "period": "2026-03-31", "context_id": "ctx_1",
        "investment_identifier": "Acme Corp - First Lien",
        "industry": "", "investment_type": "", "affiliation": "",
        "dimensions_raw": "", "concept_names": "",
        "maturity_date": "", "fair_value": "1000000",
    }
    return pd.DataFrame([{**base, **r} for r in rows])


class TestSourceAnchorId:
    def test_anchor_is_src_accession_context(self):
        out = _coerce_source_df(
            _source_frame([{"context_id": "ctx_42"}]),
            enable_bdc_xbrl_wrappers=False)
        assert out.iloc[0]["source_anchor_id"] == (
            "src:0001418076-26-000001:ctx_42")
        # internal ordinal untouched
        assert list(out["source_row_id"]) == [0]

    def test_duplicate_context_gets_ordinal_suffix(self):
        out = _coerce_source_df(
            _source_frame([{"context_id": "ctx_9"},
                           {"context_id": "ctx_9"},
                           {"context_id": "ctx_9"}]),
            enable_bdc_xbrl_wrappers=False)
        assert list(out["source_anchor_id"]) == [
            "src:0001418076-26-000001:ctx_9",
            "src:0001418076-26-000001:ctx_9#2",
            "src:0001418076-26-000001:ctx_9#3",
        ]

    def test_missing_anchor_part_falls_back_to_ordinal(self):
        out = _coerce_source_df(
            _source_frame([{"context_id": ""},
                           {"accession_number": "", "context_id": "ctx_1"}]),
            enable_bdc_xbrl_wrappers=False)
        assert list(out["source_anchor_id"]) == ["src-ord:0", "src-ord:1"]

    def test_anchor_unique_across_frame(self):
        out = _coerce_source_df(
            _source_frame([{"context_id": "ctx_1"},
                           {"context_id": "ctx_2"},
                           {"context_id": "ctx_1"}]),
            enable_bdc_xbrl_wrappers=False)
        assert out["source_anchor_id"].nunique() == 3
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_source_recon_anchor_ids.py -v`
Expected: FAIL — `KeyError: 'source_anchor_id'`.

- [ ] **Step 3: Implement**

In `pipeline/source_reconciliation.py::_coerce_source_df`, directly after `df["source_row_id"] = range(len(df))` (:1400), insert:

```python
    # Published grounding anchor (2026-08-22): stable across frame reorders
    # and re-extraction, unlike the positional ordinal above (which remains
    # the INTERNAL join/rank key inside the reconciliation SQL).
    _acc = df["accession_number"].fillna("").astype(str).str.strip()
    _ctx = df["context_id"].fillna("").astype(str).str.strip()
    _anchor = "src:" + _acc + ":" + _ctx
    _dup_rank = _anchor.groupby(_anchor).cumcount()
    if (_dup_rank > 0).any():
        logger.warning(
            "source anchor: %d duplicate (accession, context_id) row(s) "
            "suffixed #k", int((_dup_rank > 0).sum()))
    _anchor = _anchor.where(
        _dup_rank == 0, _anchor + "#" + (_dup_rank + 1).astype(str))
    _has_parts = _acc.ne("") & _ctx.ne("")
    if (~_has_parts).any():
        logger.warning(
            "source anchor: %d row(s) missing accession/context, using "
            "ordinal fallback", int((~_has_parts).sum()))
    df["source_anchor_id"] = _anchor.where(
        _has_parts, "src-ord:" + df["source_row_id"].astype(str))
```

NOTE: `logger` already exists module-level. `Series.groupby(self).cumcount()` is vectorized (no `.apply`).

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_source_recon_anchor_ids.py -v`
Expected: 4 PASS.

- [ ] **Step 5: Commit**

```bash
git add pipeline/source_reconciliation.py tests/test_source_recon_anchor_ids.py
git commit -m "source_reconciliation: mint src:accession:context anchor on source frame

- source_anchor_id = src:{accession}:{context_id}, #k suffix on duplicate
  contexts, src-ord:{n} fallback when either part is missing (both warned)
- internal positional source_row_id untouched (SQL joins/ranking unchanged)"
```

---

### Task 2: `_coerce_output_df` mints `output_anchor_id`

**Files:**
- Modify: `pipeline/source_reconciliation.py:1411-1434` (`_coerce_output_df`, after `output_row_id = range(len(df))` at :1426)
- Test: `tests/test_source_recon_anchor_ids.py` (append)

**Interfaces:**
- Consumes: holdings frame (BDC rows; published unified frames carry `row_id`, test fixtures often do not).
- Produces: `output_anchor_id` (str column): the row's `row_id` when a nonempty `row_id` exists, else the stringified ordinal. Task 3 consumes `output["output_row_id"]` + `output["output_anchor_id"]` as the mapping.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_source_recon_anchor_ids.py`:

```python
from pipeline.source_reconciliation import _coerce_output_df


def _holdings_frame(rows):
    base = {
        "source": "bdc", "cik": "0001418076", "entity_name": "Test BDC",
        "report_date": "2026-03-31", "period": "2026-03-31",
        "accession_number": "0001418076-26-000001", "filing_date": "2026-05-10",
        "bdc_form_type": "10-Q",
        "bdc_investment_identifier": "Acme Corp - First Lien",
        "bdc_dimensions_raw": "", "issuer_name": "Acme Corp",
        "instrument_description": "", "index_classification": "DIRECT_LENDING",
        "asset_category": "", "issuer_category": "", "maturity_date": "",
        "fair_value": "1000000", "cost": "", "principal_amount": "",
        "shares_held": "", "interest_rate": "", "basis_spread": "",
        "pik_rate": "",
    }
    return pd.DataFrame([{**base, **r} for r in rows])


class TestOutputAnchorId:
    def test_uses_unified_row_id_when_present(self):
        out = _coerce_output_df(
            _holdings_frame([{"row_id": "ROW-0123456789abcdef"}]),
            enable_bdc_xbrl_wrappers=False)
        assert out.iloc[0]["output_anchor_id"] == "ROW-0123456789abcdef"
        assert list(out["output_row_id"]) == [0]

    def test_falls_back_to_ordinal_without_row_id(self):
        out = _coerce_output_df(
            _holdings_frame([{}, {}]), enable_bdc_xbrl_wrappers=False)
        assert list(out["output_anchor_id"]) == ["0", "1"]

    def test_empty_row_id_value_falls_back(self):
        out = _coerce_output_df(
            _holdings_frame([{"row_id": ""}]), enable_bdc_xbrl_wrappers=False)
        assert out.iloc[0]["output_anchor_id"] == "0"
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_source_recon_anchor_ids.py::TestOutputAnchorId -v`
Expected: FAIL — `KeyError: 'output_anchor_id'`.

- [ ] **Step 3: Implement**

In `_coerce_output_df`, directly after `df["output_row_id"] = range(len(df))` (:1426), insert:

```python
    # Published anchor: the unified row_id (itself anchor-derived since
    # 2026-08-22) when present; ordinal string otherwise (test fixtures,
    # pre-row_id frames). Internal ordinal above remains the SQL key.
    if "row_id" in df.columns:
        _rid = df["row_id"].fillna("").astype(str).str.strip()
    else:
        _rid = pd.Series("", index=df.index, dtype=str)
    df["output_anchor_id"] = _rid.where(
        _rid.ne(""), df["output_row_id"].astype(str))
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_source_recon_anchor_ids.py -v`
Expected: 7 PASS.

- [ ] **Step 5: Commit**

```bash
git add pipeline/source_reconciliation.py tests/test_source_recon_anchor_ids.py
git commit -m "source_reconciliation: mint output_anchor_id from unified row_id

- published output id becomes the anchor-based unified row_id when the
  holdings frame carries one; ordinal string fallback preserves fixtures
- internal positional output_row_id untouched"
```

---

### Task 3: Publish anchors in the detail frame

**Files:**
- Modify: `pipeline/source_reconciliation.py:3341-3363` (between `metrics = build_source_reconciliation_metrics(detail)` and the return), plus a new module-level helper
- Test: `tests/test_source_recon_anchor_ids.py` (append)

**Interfaces:**
- Consumes: `source["source_row_id"]`/`source["source_anchor_id"]` (Task 1), `output["output_row_id"]`/`output["output_anchor_id"]` (Task 2), the `detail` frame (source_row_id/output_row_id are VARCHAR ordinals or `''`).
- Produces: returned detail frame's `source_row_id`/`output_row_id` columns carry anchors. All artifact writers (`_assemble_legacy_reconciliation_outputs`, per-CIK parquets, `build_source_only_blocker_detail`) inherit — no changes there.

- [ ] **Step 1: Write the failing end-to-end tests**

Append to `tests/test_source_recon_anchor_ids.py`:

```python
from pipeline.source_reconciliation import reconcile_bdc_source_to_holdings


class TestPublishedDetailIds:
    def test_source_only_row_publishes_src_anchor(self):
        source = _source_frame([{"context_id": "ctx_lonely",
                                 "report_date": "2026-03-31"}])
        detail, _metrics = reconcile_bdc_source_to_holdings(
            source, _holdings_frame([]).iloc[0:0],
            enable_bdc_xbrl_wrappers=False,
            audited_value_rescales=pd.DataFrame(
                columns=["cik", "field", "factor"]))
        src_rows = detail[detail["source_row_id"].astype(str).ne("")]
        assert len(src_rows) >= 1
        assert set(src_rows["source_row_id"]) == {
            "src:0001418076-26-000001:ctx_lonely"}

    def test_output_extra_row_publishes_unified_row_id(self):
        holdings = _holdings_frame([{"row_id": "ROW-feedfeedfeedfeed",
                                     "report_date": "2026-03-31"}])
        detail, _metrics = reconcile_bdc_source_to_holdings(
            _source_frame([]).iloc[0:0], holdings,
            enable_bdc_xbrl_wrappers=False,
            audited_value_rescales=pd.DataFrame(
                columns=["cik", "field", "factor"]))
        out_rows = detail[detail["output_row_id"].astype(str).ne("")]
        assert len(out_rows) >= 1
        assert set(out_rows["output_row_id"]) == {"ROW-feedfeedfeedfeed"}
```

NOTE for implementer: if `reconcile_bdc_source_to_holdings` short-circuits on one-sided-empty inputs differently than expected, seed the other side with one non-matching row (different report_date) instead of an empty slice — the assertion targets only the non-empty-id rows either way.

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_source_recon_anchor_ids.py::TestPublishedDetailIds -v`
Expected: FAIL — published ids are stringified ordinals ("0"), not anchors.

- [ ] **Step 3: Implement the publish helper + call**

Add module-level helper near `_coerce_output_df`:

```python
def _publish_anchor_row_ids(
    detail: pd.DataFrame, source: pd.DataFrame, output: pd.DataFrame,
) -> pd.DataFrame:
    """Swap the detail frame's published ordinal ids for stable anchors.

    Internal SQL joins/ranking ran on the ordinals; this is the single
    publish chokepoint. Unmapped/empty values pass through unchanged.
    """
    src_map = dict(zip(source["source_row_id"].astype(str),
                       source["source_anchor_id"].astype(str)))
    out_map = dict(zip(output["output_row_id"].astype(str),
                       output["output_anchor_id"].astype(str)))
    sid = detail["source_row_id"].fillna("").astype(str)
    oid = detail["output_row_id"].fillna("").astype(str)
    detail["source_row_id"] = sid.map(src_map).fillna(sid)
    detail["output_row_id"] = oid.map(out_map).fillna(oid)
    return detail
```

In `reconcile_bdc_source_to_holdings`, after `metrics = build_source_reconciliation_metrics(detail)` (:3341) and before `con.close()`, insert:

```python
    detail = _publish_anchor_row_ids(detail, source, output)
```

(After metrics so any id-distinctness counting inside metrics keeps its exact pre-change inputs; the anchor mapping is bijective anyway, but this makes it provably inert.)

- [ ] **Step 4: Run the focused file, then the two heavy affected suites**

Run: `python -m pytest tests/test_source_recon_anchor_ids.py -v`
Expected: 9 PASS.
Run: `python -m pytest tests/test_source_reconciliation_cache.py -q` (background if slow)
Expected: PASS — its assertions filter on non-empty ids, not ordinal values. If any test pins a literal ordinal id, update the assertion to the anchor format and note it in the commit body.
Run: `python -m pytest tests/test_validate_holdings.py -q` (background; large)
Expected: PASS for the same reason.

- [ ] **Step 5: Commit**

```bash
git add pipeline/source_reconciliation.py tests/test_source_recon_anchor_ids.py
git commit -m "source_reconciliation: publish anchor ids in detail artifacts

- single post-SQL swap maps ordinal source_row_id/output_row_id to
  src:{accession}:{context} anchors / unified row_id at the publish
  chokepoint; every downstream artifact and grounding frame inherits
- internal SQL ordinals and metrics inputs bit-identical to before"
```

---

### Task 4: Worker prompt + schema docs

**Files:**
- Modify: `scripts/agent_b2/dispatch_preflight.py:354-358` (PRE-DIRTY — edit, do NOT commit)
- Modify: `docs/reference/schemas.md` (Row Identity section)
- Test: `tests/test_agent_b2_preflight.py` (run, no edits expected)

**Interfaces:**
- Consumes: the `src:` format string from Task 1.
- Produces: worker-facing prompt text and operator docs describing the format.

- [ ] **Step 1: Update the preflight prompt line**

At `dispatch_preflight.py:354-358`, extend the positions guidance (keep existing sentences, add the format note):

```python
    if "positions" in tpl.allowed:
        lines.append("- Each template.positions[] entry REQUIRES issuer_name, fair_value "
                     "(number), report_date, source_row_id (the staging/source row id "
                     "being recovered -- copy it from the evidence; NEVER invent one; "
                     "current format src:{accession}:{context_id}), "
                     "and bdc_dimensions_raw. The gate re-verifies source_row_id and "
                     "fair_value against raw staging; a fabricated position cannot pass.")
```

- [ ] **Step 2: Run the preflight tests**

Run: `python -m pytest tests/test_agent_b2_preflight.py -q`
Expected: PASS (prompt-text tests, if any, may pin the old sentence — update the pinned string in the test if so, and note the test file is also pre-dirty: edit but do not commit).

- [ ] **Step 3: Document in schemas.md**

Append to the "Row Identity" section of `docs/reference/schemas.md`:

```markdown
- Source-reconciliation published ids (2026-08-22): detail artifacts carry
  `source_row_id` = `src:{accession_number}:{context_id}` (stable grounding
  anchor; `#k` suffix on within-frame duplicate contexts, `src-ord:{n}`
  fallback when a part is missing) and `output_row_id` = the unified
  `row_id` when available. The positional ordinals remain internal to the
  reconciliation SQL only. Correction-leaf `positions[].source_row_id`
  citations copy the published anchor verbatim; the value gate re-verifies
  by string equality + fair_value tolerance against a grounding frame that
  is now independently re-derivable from the source-facts cache.
```

- [ ] **Step 4: Commit (docs only)**

```bash
git add docs/reference/schemas.md
git commit -m "docs: source reconciliation published anchor id formats

- schemas.md documents src:{accession}:{context_id} grounding anchors and
  unified row_id as the published output-side id"
```

---

### Task 5: Operator phase — regenerate artifacts, parity gates, changelog

No new pipeline code. STOP and report on any gate failure.

- [ ] **Step 1: Pre-flight + snapshot**

```powershell
Get-Process | Where-Object { $_.ProcessName -match 'python|pytest' } | Select-Object Id, ProcessName, StartTime
New-Item -ItemType Directory -Force data\snapshots\pre_srcanchor_20260822 | Out-Null
Copy-Item data\output\source_reconciliation_detail.csv data\snapshots\pre_srcanchor_20260822\ -ErrorAction SilentlyContinue
Copy-Item data\output\source_reconciliation_metrics.csv data\snapshots\pre_srcanchor_20260822\ -ErrorAction SilentlyContinue
Copy-Item data\output\source_reconciliation_residual_classification.csv data\snapshots\pre_srcanchor_20260822\ -ErrorAction SilentlyContinue
Copy-Item data\output\source_reconciliation_source_only_detail.csv data\snapshots\pre_srcanchor_20260822\ -ErrorAction SilentlyContinue
```

- [ ] **Step 2: Regenerate reconciliation artifacts**

The reconciliation code change flips `compute_reconciliation_logic_hash()`, so the cached runner marks every CIK dirty and re-runs fully — expected and desired. Trigger via the existing validate path (background; expect a long run):

```powershell
python -m pipeline.main --unified --validate
```

(If a lighter entrypoint invoking `run_bdc_source_reconciliation_cached(force=...)` exists in scripts/, prefer it; check `rg "run_bdc_source_reconciliation_cached" scripts/` first.)

- [ ] **Step 3: GATE — count parity (blocker accounting must not move)**

Write and run `scratch/2026-08-22_anchor_rowid/recon_parity_gate.py`:

```python
"""Pre/post parity for the source_row_id anchor migration (disposable).

Ids changed format; NOTHING else may move: detail row counts per
(cik, report_date, status), metrics rows, residual-classification counts,
source-only blocker counts.
"""

import sys

import duckdb

OLD_DIR = "data/snapshots/pre_srcanchor_20260822"
NEW_DIR = "data/output"
con = duckdb.connect()
fail = False

for name, keys in [
    ("source_reconciliation_detail.csv", "cik, report_date, status"),
    ("source_reconciliation_residual_classification.csv", "cik, report_date, residual_class"),
    ("source_reconciliation_source_only_detail.csv", "cik, report_date, mechanism, is_blocking"),
    ("source_reconciliation_metrics.csv", "cik, report_date, reconciliation_status"),
]:
    rows = con.execute(f"""
        SELECT COALESCE(o.k, n.k) AS k, o.n AS old_n, n.n AS new_n
        FROM (SELECT concat_ws('|', {keys}) AS k, COUNT(*) AS n
              FROM read_csv_auto('{OLD_DIR}/{name}', header=true, all_varchar=true) GROUP BY 1) o
        FULL OUTER JOIN (SELECT concat_ws('|', {keys}) AS k, COUNT(*) AS n
              FROM read_csv_auto('{NEW_DIR}/{name}', header=true, all_varchar=true) GROUP BY 1) n
          ON o.k = n.k
        WHERE COALESCE(o.n, -1) != COALESCE(n.n, -1)
        LIMIT 25
    """).fetchall()
    print(f"{name}: {len(rows)} group-count mismatches")
    for r in rows:
        print("  ", r)
    if rows:
        fail = True

fmt = con.execute(f"""
    SELECT
      SUM(CASE WHEN source_row_id LIKE 'src:%' THEN 1 ELSE 0 END) AS anchored,
      SUM(CASE WHEN source_row_id LIKE 'src-ord:%' THEN 1 ELSE 0 END) AS fallback,
      SUM(CASE WHEN source_row_id != '' AND source_row_id NOT LIKE 'src%' THEN 1 ELSE 0 END) AS unexpected,
      COUNT(DISTINCT source_row_id) - COUNT(DISTINCT CASE WHEN source_row_id = '' THEN NULL ELSE source_row_id END) AS _ignore
    FROM read_csv_auto('{NEW_DIR}/source_reconciliation_detail.csv', header=true, all_varchar=true)
    WHERE source_row_id != ''
""").fetchone()
print(f"id formats: anchored={fmt[0]}, fallback={fmt[1]}, unexpected={fmt[2]}")
if fmt[2]:
    fail = True

print("RESULT:", "FAIL" if fail else "PASS")
sys.exit(1 if fail else 0)
```

Expected: all group counts identical; `unexpected=0`; `fallback` near zero. Any count mismatch = STOP (a logic change leaked past the publish chokepoint).

- [ ] **Step 4: Full test suite before handoff**

Check for competing pytest processes first, then:

```powershell
python -m pytest --durations=50 --durations-min=0.5 -q
```

Expected: green (record counts). Backstop: `python scripts/diff_outputs.py --semantic` — reconciliation artifacts are not in the semantic set, so expect the same pre-existing-only deltas documented on 2026-08-22.

- [ ] **Step 5: Changelog + commit docs**

Append a dated entry to `docs/agent_changelog.md`: what changed, the parity-gate results (group counts identical, id format tallies), test counts, the pre-dirty `dispatch_preflight.py` edit left uncommitted, snapshot location (`data/snapshots/pre_srcanchor_20260822/`).

```bash
git add docs/agent_changelog.md
git commit -m "docs: source_row_id anchor migration changelog

- parity gate results, id format tallies, test counts recorded"
```

---

## Self-Review Notes

- Spec coverage: anchor format + dup suffix + fallback (Task 1), output-side row_id adoption (Task 2), single publish chokepoint with metrics-inert placement (Task 3), worker prompt + docs (Task 4), regeneration + blocker-count-invariance gates (Task 5). Out of scope confirmed: `staging:` rule dialect, gate code (already string-matching), leaf restamp (zero citations).
- Judgment calls encoded: swap AFTER metrics computation; internal ordinals never touched; `output_anchor_id` fallback keeps every existing test fixture green.
- Type consistency: `_publish_anchor_row_ids(detail, source, output) -> pd.DataFrame`; coerce helpers produce `source_anchor_id`/`output_anchor_id` str columns consumed by exactly that helper.
