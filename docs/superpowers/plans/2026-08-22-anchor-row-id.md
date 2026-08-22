# Anchor-Based row_id Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Re-derive unified holdings `row_id` from an immutable source anchor (`source|accession_number|src_context_id` for BDC rows, `source|accession_number|nport_holding_id` for N-PORT rows) so the id survives re-extraction, staging reorders, corrections, and parser fixes — while keeping the `ROW-<16hex>` format and every existing consumer contract.

**Architecture:** Three data-flow changes plus one migration tool. (1) The BDC extractor keeps the winning XBRL contextRef through dedup and publishes it as `src_context_id` in bdc_holdings.csv. (2) Staging passes it through to a new `UNIFIED_COLUMNS` entry. (3) `_assign_row_ids` hashes the anchor when present, falls back to the legacy natural key when not, and records which in a new `row_id_basis` column appended alongside `row_id`. (4) A re-stamp script maps legacy ids to anchor ids in the promoted correction store (exactly 1 live leaf carries a row_id today). An operator phase re-extracts all cached filings (`scripts/rebuild_outputs.py --bdc-holdings`, cache-only), rebuilds unified, re-stamps, and gates on drift/uniqueness audits.

**Tech Stack:** Python 3.x, pandas, DuckDB, pytest. No new dependencies.

**Spec:** `docs/provenance_columns_scoping.md` (section 2.4 item 2 defines `src_context_id`); the row_id-replacement decisions were made in the 2026-08-22 owner conversation and are restated in full here:
- Keep the column name `row_id` and format `ROW-` + first 16 hex of md5. Swap only the hash input.
- Anchor = `{source}|{accession_number}|{src_context_id}` (bdc) / `{source}|{accession_number}|{nport_holding_id}` (nport). Lower-cased source, raw accession, raw context/holding id, joined with `|`.
- Rows missing accession or the per-source anchor part fall back to the legacy natural-key hash (`position_id_registry.compute_natural_keys`), recorded as `row_id_basis = 'natural_key'`; anchored rows get `'src_anchor'`.
- `src_context_id` joins `UNIFIED_COLUMNS` (staged column). `row_id_basis` does NOT — it is appended by `_assign_row_ids` together with `row_id` (final frame = `UNIFIED_COLUMNS + ["row_id", "row_id_basis"]`).
- NOT for cross-quarter identity: `position_id` / `position_id_registry` / position matching are untouched.
- Uniqueness of `(accession, src_context_id)` is asserted (warn-loud), not assumed.
- The anchor is an as-filed claim: an amendment (new accession) yields a new id by design.

## Global Constraints

(from AGENTS.md — every task implicitly includes these)

- No network calls; all rebuilds are cache-only (`scripts/rebuild_outputs.py`).
- All log messages ASCII only (Windows cp1252).
- No `python -` / here-string / long `python -c` diagnostics; use named scripts, pytest, DuckDB CLI, rg.
- Pytest write-guard blocks writes to `data/output/` — rebuilds happen outside pytest.
- No pandas `.apply()`/`.iterrows()` on >10K-row data paths.
- Commit style: short subject + 2-4 bullet body.
- **Dirty-worktree rule:** the repo carries other sessions' deliberate uncommitted changes (`pipeline/agent_b2_appliers.py`, `pipeline/agent_promoted.py`, `pipeline/correction_leaf.py`, `pipeline/review_bundles.py`, `pipeline/verdict_leaf.py`, `pipeline/agent_promoted.py`, `scripts/agent_b2/*`, their tests, `docs/agent_changelog.md`). NEVER `git add -A`/`git add -u`. Stage only the exact files each task names. If a task must edit a pre-dirty file (only Task 3 does, two lines in `pipeline/agent_promoted.py`), make the edit but do NOT commit that file; record it in the final report.
- Before any long rebuild or full pytest run, check for competing python/pytest processes.

## File Structure

| File | Change | Task |
|---|---|---|
| `pipeline/bdc_filings.py` | `_deduplicate_bdc_holdings` publishes winner's context as `src_context_id` | 1 |
| `tests/test_bdc_filings.py` | 2 new dedup tests | 1 |
| `pipeline/staging_bdc.py` | `_optional_cols` + Phase C SELECT gain `src_context_id` | 2 |
| `pipeline/staging_nport.py` | emits `'' AS src_context_id` | 2 |
| `pipeline/unified_holdings.py` | `UNIFIED_COLUMNS` + rewritten `_assign_row_ids` | 2, 3 |
| `tests/test_unified_holdings.py` | passthrough test; end-to-end schema assertion | 2, 3 |
| `tests/test_row_id.py` | rewritten for anchor derivation | 3 |
| `pipeline/main.py` | re-assign row ids after `assign_position_ids` (fixes latent row_id-stripping on `--returns`) | 3 |
| `pipeline/agent_promoted.py` | JIT drop covers `row_id_basis` (EDIT, DO NOT COMMIT — pre-dirty) | 3 |
| `scripts/restamp_row_selectors.py` | new migration script | 4 |
| `tests/test_restamp_row_selectors.py` | new | 4 |
| `docs/reference/schemas.md` | document `src_context_id` / `row_id_basis` | 5 |
| `docs/agent_changelog.md` | dated entry | 5 |

---

### Task 1: Extractor keeps the winning context — `src_context_id` in bdc_holdings.csv

**Files:**
- Modify: `pipeline/bdc_filings.py:1149-1152` (dedup tail)
- Test: `tests/test_bdc_filings.py` (append to `TestParseAllFilings`, after `test_dedupe_collapses_exact_duplicate_dimension_path` ~:1717)

**Interfaces:**
- Consumes: `_deduplicate_bdc_holdings(df)` — records already carry `_context_id` (set at :814).
- Produces: bdc_holdings.csv rows carry `src_context_id` (string, `''` when the input row had none, e.g. rows merged in from a legacy CSV). Downstream (Task 2) reads this column by name.

- [x] **Step 1: Write two failing tests**

Append to `TestParseAllFilings` in `tests/test_bdc_filings.py`:

```python
    def test_dedupe_publishes_winner_context_as_src_context_id(self):
        from pipeline.bdc_filings import _deduplicate_bdc_holdings

        raw = pd.DataFrame([
            {
                "accession_number": "acc-001",
                "investment_identifier": "Acme Corp - First Lien",
                "period": "2024-03-31",
                "_context_id": "ctx_sparse",
                "fair_value": "",
                "cost": "",
                "principal_amount": "",
                "interest_rate": "SOFR+500",
            },
            {
                "accession_number": "acc-001",
                "investment_identifier": "Acme Corp - First Lien",
                "period": "2024-03-31",
                "_context_id": "ctx_complete",
                "fair_value": "1000000",
                "cost": "990000",
                "principal_amount": "1000000",
                "interest_rate": "",
            },
        ])

        result = _deduplicate_bdc_holdings(raw)

        assert len(result) == 1
        # internal column still dropped; published anchor is the winner's ctx
        assert "_context_id" not in result.columns
        assert result.iloc[0]["src_context_id"] == "ctx_complete"

    def test_dedupe_fv_split_rows_keep_own_contexts(self):
        from pipeline.bdc_filings import _deduplicate_bdc_holdings

        raw = pd.DataFrame([
            {
                "accession_number": "acc-001",
                "investment_identifier": "Acme Corp - First Lien",
                "period": "2024-03-31",
                "_context_id": "ctx_a",
                "fair_value": "1000000",
                "cost": "990000",
            },
            {
                "accession_number": "acc-001",
                "investment_identifier": "Acme Corp - First Lien",
                "period": "2024-03-31",
                "_context_id": "ctx_b",
                "fair_value": "2000000",
                "cost": "990000",
            },
        ])

        result = _deduplicate_bdc_holdings(raw)

        assert len(result) == 2
        assert set(result["src_context_id"]) == {"ctx_a", "ctx_b"}
        # distinct contexts -> distinct anchors even under axis split
        assert result["src_context_id"].nunique() == 2

    def test_dedupe_without_context_column_yields_empty_src_context_id(self):
        # legacy-CSV merge path: rows may arrive with no _context_id at all
        from pipeline.bdc_filings import _deduplicate_bdc_holdings

        raw = pd.DataFrame([
            {
                "accession_number": "acc-001",
                "investment_identifier": "Acme Corp - First Lien",
                "period": "2024-03-31",
                "fair_value": "1000000",
            },
        ])

        result = _deduplicate_bdc_holdings(raw)
        assert len(result) == 1
        assert result.iloc[0]["src_context_id"] == ""
```

- [x] **Step 2: Run tests to verify they fail**

Run: `python -m pytest "tests/test_bdc_filings.py::TestParseAllFilings" -v`
Expected: the 3 new tests FAIL (`KeyError: 'src_context_id'`); all pre-existing tests PASS.

- [x] **Step 3: Implement**

In `pipeline/bdc_filings.py`, replace the dedup tail (:1149-1152):

```python
    # Publish the winning row's XBRL contextRef as the row's source anchor.
    # accession_number + src_context_id locates the ix:nonFraction facts in
    # the cached filing (primary-of-N when dedupe_context_count > 1).
    if "_context_id" in picked.columns:
        picked["src_context_id"] = (
            picked["_context_id"].fillna("").astype(str)
        )
    else:
        picked["src_context_id"] = ""

    drop_cols = ["_dedupe_row_order", "_dedupe_score", "_fv_split_key"]
    if "_context_id" in picked.columns:
        drop_cols.append("_context_id")
    return picked.drop(columns=drop_cols)
```

- [x] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_bdc_filings.py -v`
Expected: all PASS (whole file, not just the class — dedup is exercised elsewhere too).

- [x] **Step 5: Commit**

```bash
git add pipeline/bdc_filings.py tests/test_bdc_filings.py
git commit -m "bdc_filings: publish winning contextRef as src_context_id

- _deduplicate_bdc_holdings keeps the winner row's XBRL context as a new
  src_context_id column in bdc_holdings.csv (primary-of-N for merged groups)
- '' when input rows carry no _context_id (legacy-CSV merge path)
- Step 1 of the anchor-based row_id migration (see docs/superpowers/plans/)"
```

---

### Task 2: Staging passthrough — `src_context_id` into UNIFIED_COLUMNS

**Files:**
- Modify: `pipeline/staging_bdc.py:410-414` (`_optional_cols`), `:2587` (Phase C SELECT)
- Modify: `pipeline/staging_nport.py:~298` (empty emit)
- Modify: `pipeline/unified_holdings.py:54-111` (`UNIFIED_COLUMNS`)
- Test: `tests/test_unified_holdings.py`

**Interfaces:**
- Consumes: bdc_holdings.csv / bdc_df with optional `src_context_id` (Task 1).
- Produces: `_prepare_bdc` and `_prepare_nport` outputs both contain `src_context_id` (nport: always `''`; bdc: value or `''`). `UNIFIED_COLUMNS` contains `"src_context_id"` immediately after `"bdc_investment_country"`. Task 3 reads `df["src_context_id"]` by name in `_assign_row_ids`.

- [x] **Step 1: Write the failing test**

Add to `tests/test_unified_holdings.py` (near other `_prepare_bdc` staging tests; match the file's existing fixture style — a minimal bdc frame passed to `_prepare_bdc(bdc_df=...)`):

```python
def test_src_context_id_passes_through_bdc_staging():
    from pipeline.staging_bdc import _prepare_bdc

    bdc_df = pd.DataFrame([{
        "cik": "1418076",
        "entity_name": "Test BDC",
        "accession_number": "0001418076-24-000001",
        "form_type": "10-Q",
        "filing_date": "2024-05-10",
        "report_date": "2024-03-31",
        "period": "2024-03-31",
        "investment_identifier": "Acme Corp | First Lien Term Loan",
        "dimensions_raw": "us-gaap:InvestmentIdentifierAxis=AcmeTL1",
        "fair_value": "1000000",
        "cost": "990000",
        "principal_amount": "1000000",
        "src_context_id": "ctx_acme_tl1",
    }])
    result = _prepare_bdc(bdc_df=bdc_df)

    assert "src_context_id" in result.columns
    assert list(result["src_context_id"]) == ["ctx_acme_tl1"]


def test_src_context_id_defaults_empty_when_absent():
    # bdc_holdings.csv built before the migration has no src_context_id column
    from pipeline.staging_bdc import _prepare_bdc

    bdc_df = pd.DataFrame([{
        "cik": "1418076",
        "entity_name": "Test BDC",
        "accession_number": "0001418076-24-000001",
        "form_type": "10-Q",
        "filing_date": "2024-05-10",
        "report_date": "2024-03-31",
        "period": "2024-03-31",
        "investment_identifier": "Acme Corp | First Lien Term Loan",
        "dimensions_raw": "us-gaap:InvestmentIdentifierAxis=AcmeTL1",
        "fair_value": "1000000",
        "cost": "990000",
        "principal_amount": "1000000",
    }])
    result = _prepare_bdc(bdc_df=bdc_df)

    assert "src_context_id" in result.columns
    assert list(result["src_context_id"]) == [""]
```

NOTE for implementer: `_prepare_bdc` may take extra required args (check its signature at `staging_bdc.py:~380`); mirror however the nearest existing staging test calls it. If existing tests route through a helper, use the helper.

- [x] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_unified_holdings.py -k src_context_id -v`
Expected: FAIL (`src_context_id` not in columns).

- [x] **Step 3: Implement (four edits)**

3a. `pipeline/unified_holdings.py` — in `UNIFIED_COLUMNS`, insert after `"bdc_investment_country",`:

```python
    "src_context_id",
```

3b. `pipeline/staging_bdc.py:410-414` — add to `_optional_cols`:

```python
    _optional_cols = (
        "fair_value_unit", "cost_unit", "principal_amount_unit",
        "industry", "investment_type", "affiliation",
        "nonaccrual_footnote", "nonaccrual_dimension",
        "src_context_id",
    )
```

3c. `pipeline/staging_bdc.py:2587` — in the Phase C `unified` CTE SELECT, directly after `COALESCE(_hier_country, '') AS bdc_investment_country,` add:

```sql
            COALESCE(CAST(src_context_id AS VARCHAR), '') AS src_context_id,
```

(The phases between `bdc_raw` and `with_enrichment` are `SELECT *` / `EXCLUDE` chains, so the column arrives without further edits. If a phase boundary materialises an explicit column list and the test still fails, add the column at that boundary — find it with `rg "src_context_id" pipeline/staging_bdc.py` after checking which CTE loses it.)

3d. `pipeline/staging_nport.py:~296` — after `'' AS bdc_investment_country,` (mirror the neighboring `'' AS bdc_*` lines) add:

```sql
            '' AS src_context_id,
```

- [x] **Step 4: Run tests**

Run: `python -m pytest tests/test_unified_holdings.py -x -q`
Expected: the 2 new tests PASS. Some existing tests may fail if they enumerate expected columns by hand — update those fixtures to include `src_context_id` (the `:1330` assertion compares against the constant and self-heals). Also run: `python -m pytest tests/test_staging_nport.py -q` if that file exists (check with `ls tests/ | rg nport`).

- [x] **Step 5: Commit**

```bash
git add pipeline/staging_bdc.py pipeline/staging_nport.py pipeline/unified_holdings.py tests/test_unified_holdings.py
git commit -m "staging: pass src_context_id through to UNIFIED_COLUMNS

- staging_bdc: optional input col + Phase C SELECT passthrough
- staging_nport: emits '' (no XBRL contexts in N-PORT)
- UNIFIED_COLUMNS gains src_context_id after bdc_investment_country;
  empty-frame constructors and reorder points pick it up via the constant"
```

---

### Task 3: Anchor-based `_assign_row_ids` + `row_id_basis` + downstream guards

**Files:**
- Modify: `pipeline/unified_holdings.py:1437-1470` (`_assign_row_ids`)
- Modify: `pipeline/main.py:963-970` (re-assign after position ids)
- Modify: `pipeline/agent_promoted.py:178-181` (JIT drop — EDIT ONLY, DO NOT COMMIT, file is pre-dirty)
- Test: `tests/test_row_id.py` (rewrite), `tests/test_unified_holdings.py` (end-to-end schema assertion ~:2895)

**Interfaces:**
- Consumes: `src_context_id` (Task 2), `nport_holding_id`, `accession_number`, `source`; `compute_natural_keys(df)` from `pipeline.position_id_registry` (unchanged).
- Produces: `_assign_row_ids(df) -> df` with two appended columns: `row_id` (str, `ROW-<16hex>`) and `row_id_basis` (str, `'src_anchor'` | `'natural_key'`). Final unified frame = `UNIFIED_COLUMNS + ["row_id", "row_id_basis"]`. Task 4's script re-derives legacy ids with the same md5 recipe.

- [x] **Step 1: Rewrite `tests/test_row_id.py` (failing tests)**

Replace the whole file with:

```python
"""Tests for the anchor-based row_id (unified_holdings._assign_row_ids).

row_id = 'ROW-' + md5[:16] of the row's source anchor:
    bdc:   source|accession_number|src_context_id
    nport: source|accession_number|nport_holding_id
Rows lacking an anchor part fall back to the legacy natural-key hash.
row_id_basis records which regime produced each id. Anchored ids are
invariant to value corrections (principal/shares) -- the anchor names the
filing fact context, not the published content.
"""

import hashlib
import re

import pandas as pd

from pipeline.unified_holdings import _assign_row_ids

_ROW_ID_RE = re.compile(r"^ROW-[0-9a-f]{16}$")


def _expected(anchor: str) -> str:
    return "ROW-" + hashlib.md5(anchor.encode()).hexdigest()[:16]


def _base_df() -> pd.DataFrame:
    return pd.DataFrame({
        "cik": ["0000000001", "0000000001", "0000000002", "0000000003"],
        "source": ["bdc", "bdc", "nport", "bdc"],
        "report_date": ["2025-12-31"] * 4,
        "accession_number": [
            "0000000001-26-000001",
            "0000000001-26-000001",
            "0000000002-26-000009",
            "",  # no accession -> natural-key fallback
        ],
        "src_context_id": ["ctx_acme", "ctx_beta", "", ""],
        "bdc_investment_identifier": [
            "Acme Corp | First Lien Term Loan | SOFR+5.00%",
            "Beta LLC | Second Lien Term Loan | SOFR+8.50%",
            "",
            "Gamma Co | Equity",
        ],
        "nport_holding_id": ["", "", "HOLDING-123", ""],
        "principal_amount": [1000000.0, 2000000.0, None, None],
        "shares_held": [None, None, 500.0, 100.0],
        "issuer_name": ["Acme Corp", "Beta LLC", "Gamma Fund", "Gamma Co"],
        "fair_value": [990000.0, 1980000.0, 51000.0, 5000.0],
        "cost": [1000000.0, 2000000.0, 50000.0, 5000.0],
        "bdc_dimensions_raw": ["", "", "", ""],
    })


def test_format_uniqueness_and_basis_column():
    out = _assign_row_ids(_base_df())
    assert "row_id" in out.columns and "row_id_basis" in out.columns
    assert out["row_id"].map(lambda v: bool(_ROW_ID_RE.match(v))).all()
    assert out["row_id"].nunique() == len(out)
    assert list(out["row_id_basis"]) == [
        "src_anchor", "src_anchor", "src_anchor", "natural_key"]


def test_bdc_anchor_id_is_md5_of_source_accession_context():
    out = _assign_row_ids(_base_df())
    assert out.loc[0, "row_id"] == _expected(
        "bdc|0000000001-26-000001|ctx_acme")
    assert out.loc[1, "row_id"] == _expected(
        "bdc|0000000001-26-000001|ctx_beta")


def test_nport_anchor_id_uses_holding_id():
    out = _assign_row_ids(_base_df())
    assert out.loc[2, "row_id"] == _expected(
        "nport|0000000002-26-000009|HOLDING-123")


def test_anchored_id_survives_principal_correction():
    # THE point of the migration: a value correction must not rename the row.
    a = _assign_row_ids(_base_df())
    changed = _base_df()
    changed.loc[0, "principal_amount"] = 999999.0
    b = _assign_row_ids(changed)
    assert a.loc[0, "row_id"] == b.loc[0, "row_id"]
    assert b.loc[0, "row_id_basis"] == "src_anchor"


def test_anchored_id_survives_issuer_name_drift():
    a = _assign_row_ids(_base_df())
    drifted = _base_df()
    drifted.loc[0, "issuer_name"] = "ACME Corporation, Inc."
    b = _assign_row_ids(drifted)
    assert a.loc[0, "row_id"] == b.loc[0, "row_id"]


def test_fallback_rows_use_natural_key_and_stay_content_sensitive():
    a = _assign_row_ids(_base_df())
    changed = _base_df()
    changed.loc[3, "shares_held"] = 200.0  # natural-key field on fallback row
    b = _assign_row_ids(changed)
    assert a.loc[3, "row_id_basis"] == "natural_key"
    assert a.loc[3, "row_id"] != b.loc[3, "row_id"]


def test_bdc_row_missing_context_falls_back():
    df = _base_df()
    df.loc[0, "src_context_id"] = ""
    out = _assign_row_ids(df)
    assert out.loc[0, "row_id_basis"] == "natural_key"
    assert _ROW_ID_RE.match(out.loc[0, "row_id"])


def test_missing_anchor_columns_entirely_falls_back():
    # frames built without staging (e.g. some test fixtures) must not crash
    df = _base_df().drop(columns=["src_context_id", "accession_number"])
    out = _assign_row_ids(df)
    assert (out["row_id_basis"] == "natural_key").all()
    assert out["row_id"].nunique() == len(out)


def test_row_order_invariance():
    a = _assign_row_ids(_base_df())
    shuffled = _base_df().sample(frac=1, random_state=7).reset_index(drop=True)
    b = _assign_row_ids(shuffled)
    map_a = dict(zip(a["issuer_name"], a["row_id"]))
    map_b = dict(zip(b["issuer_name"], b["row_id"]))
    assert map_a == map_b


def test_duplicate_anchor_warns_but_assigns(caplog):
    import logging
    df = _base_df()
    twin = df.iloc[[0]].copy()
    both = pd.concat([df, twin], ignore_index=True)  # same ctx twice
    with caplog.at_level(logging.WARNING):
        out = _assign_row_ids(both)
    assert len(out) == 5
    assert "duplicate" in caplog.text.lower()


def test_empty_frame():
    out = _assign_row_ids(pd.DataFrame())
    assert "row_id" in out.columns and "row_id_basis" in out.columns
    assert len(out) == 0
```

- [x] **Step 2: Run to verify failures**

Run: `python -m pytest tests/test_row_id.py -v`
Expected: anchor/basis tests FAIL (no `row_id_basis`, ids don't match anchors); order-invariance and empty-frame may pass incidentally.

- [x] **Step 3: Implement `_assign_row_ids`**

Replace `pipeline/unified_holdings.py:1437-1470` with:

```python
def _assign_row_ids(df: pd.DataFrame) -> pd.DataFrame:
    """Populate ``row_id`` and ``row_id_basis`` (appended, not in UNIFIED_COLUMNS).

    ``row_id`` = ``ROW-`` + first 16 hex chars of md5 over the row's source
    anchor when one exists (``row_id_basis='src_anchor'``):

        bdc:   source|accession_number|src_context_id
        nport: source|accession_number|nport_holding_id

    The anchor names the filing fact context (accessions are immutable), so
    the id survives rebuilds, staging reorders, value corrections, and parser
    fixes. It is an as-filed claim: an amendment (new accession) is a new id.
    Rows missing accession or the per-source anchor part fall back to the
    legacy drift-resistant natural key from
    ``position_id_registry.compute_natural_keys``
    (``row_id_basis='natural_key'``; content-sensitive by design).

    NOT a cross-quarter identity -- ``position_id`` owns that layer.
    """
    if df.empty:
        df["row_id"] = pd.Series(dtype=str)
        df["row_id_basis"] = pd.Series(dtype=str)
        return df
    from pipeline.position_id_registry import compute_natural_keys

    def _col(name: str) -> pd.Series:
        if name in df.columns:
            return df[name].fillna("").astype(str).str.strip()
        return pd.Series("", index=df.index, dtype=str)

    source = _col("source").str.lower()
    accession = _col("accession_number")
    anchor_part = _col("src_context_id").where(
        source.ne("nport"), _col("nport_holding_id"))
    has_anchor = accession.ne("") & anchor_part.ne("")

    keys = (source + "|" + accession + "|" + anchor_part).where(
        has_anchor, compute_natural_keys(df))
    keys = keys.reset_index(drop=True)

    con = duckdb.connect()
    con.register("nk", pd.DataFrame({"i": range(len(keys)), "k": keys}))
    hashed = con.execute(
        "SELECT 'ROW-' || substr(md5(k), 1, 16) AS row_id FROM nk ORDER BY i"
    ).fetchdf()["row_id"]
    df["row_id"] = hashed.values
    df["row_id_basis"] = has_anchor.map(
        {True: "src_anchor", False: "natural_key"}).values
    n_anchor = int(has_anchor.sum())
    n_dup = int(df["row_id"].duplicated().sum())
    if n_dup:
        logger.warning(
            "row_id: %d duplicate id(s) (anchor collision, natural-key "
            "collision, or md5-prefix collision)", n_dup)
    logger.info("row_id: %d assigned (%d src_anchor, %d natural_key)",
                len(df), n_anchor, len(df) - n_anchor)
    return df
```

- [x] **Step 4: Downstream guards (two small edits)**

4a. `pipeline/main.py` — after `assign_position_ids(...)` (:963-966) and before the `to_csv` re-save (:968), insert:

```python
            # assign_position_ids reorders to UNIFIED_COLUMNS, which drops the
            # appended row_id/row_id_basis -- re-derive before the re-save
            # (anchor-based ids are deterministic, so this is a pure re-add).
            from pipeline.unified_holdings import _assign_row_ids
            unified_df = _assign_row_ids(unified_df)
```

4b. `pipeline/agent_promoted.py:181` (pre-dirty file — edit, do not commit) — replace `corrected = corrected.drop(columns=["row_id"])` with:

```python
            corrected = corrected.drop(
                columns=[c for c in ("row_id", "row_id_basis")
                         if c in corrected.columns])
```

- [x] **Step 5: Update the end-to-end schema assertion**

In `tests/test_unified_holdings.py` (~:2895), change:

```python
    assert list(result.columns) == UNIFIED_COLUMNS + ["row_id"]
```
to
```python
    assert list(result.columns) == UNIFIED_COLUMNS + ["row_id", "row_id_basis"]
```
and keep the format/uniqueness assertions. Search the tests directory for other `+ ["row_id"]` occurrences and update the same way: `rg 'row_id"\]' tests/`.

- [x] **Step 6: Run the affected suites**

Run: `python -m pytest tests/test_row_id.py tests/test_unified_holdings.py tests/test_agent_promoted.py -q`
Expected: all PASS. (test_agent_promoted exercises the JIT block; its fixtures build frames with anchor columns absent, which now fall back to natural_key — same ids as before for those fixtures, so no fixture churn expected. If a fixture pins a literal ROW- id computed from the natural key, it still matches.)

- [x] **Step 7: Commit (excluding the pre-dirty file)**

```bash
git add pipeline/unified_holdings.py pipeline/main.py tests/test_row_id.py tests/test_unified_holdings.py
git commit -m "row_id: derive from source anchor, add row_id_basis

- anchor = source|accession|src_context_id (bdc) / |nport_holding_id (nport);
  ROW- format and md5[:16] recipe unchanged, only the hash input moves
- rows without an anchor keep the legacy natural-key hash (basis column
  records which regime produced each id)
- main.py --returns re-save now re-derives row ids (was silently dropping
  the column via the UNIFIED_COLUMNS reorder in assign_position_ids)"
```

(`pipeline/agent_promoted.py` intentionally left uncommitted — pre-dirty with another session's work; noted for the owner.)

---

### Task 4: Re-stamp script for persisted row_selector ids

**Files:**
- Create: `scripts/restamp_row_selectors.py`
- Test: `tests/test_restamp_row_selectors.py`

**Interfaces:**
- Consumes: published unified holdings (CSV or parquet companion) that already carries NEW anchor-based `row_id` + all natural-key input columns; `compute_natural_keys` (unchanged); `config.AGENT_B2_CORRECTIONS_DIR`.
- Produces: CLI `python scripts/restamp_row_selectors.py [--apply] [--holdings PATH] [--corrections-dir PATH]`. Exit 0 = all row_id selectors resolved (or none found); exit 1 = unresolved/ambiguous ids (fail-loud, nothing partially written unless --apply and all resolvable). Dry-run by default.

- [x] **Step 1: Write failing tests**

Create `tests/test_restamp_row_selectors.py`:

```python
"""Tests for scripts/restamp_row_selectors.py (legacy -> anchor row_id migration)."""

import hashlib
import json

import pandas as pd
import pytest

from scripts.restamp_row_selectors import build_id_map, restamp_leaves


def _legacy_id(natural_key: str) -> str:
    return "ROW-" + hashlib.md5(natural_key.encode()).hexdigest()[:16]


def _frame() -> pd.DataFrame:
    # minimal unified slice: natural-key inputs + published NEW row_id
    return pd.DataFrame({
        "cik": ["0001287750", "0001287750"],
        "source": ["bdc", "bdc"],
        "report_date": ["2025-12-31", "2025-12-31"],
        "accession_number": ["0001287750-26-000010"] * 2,
        "src_context_id": ["ctx_1", "ctx_2"],
        "bdc_investment_identifier": ["Acme | TL", "Beta | TL"],
        "nport_holding_id": ["", ""],
        "principal_amount": ["1000000", "2000000"],
        "shares_held": ["", ""],
        "bdc_dimensions_raw": ["", ""],
        "row_id": [
            "ROW-" + hashlib.md5(b"bdc|0001287750-26-000010|ctx_1").hexdigest()[:16],
            "ROW-" + hashlib.md5(b"bdc|0001287750-26-000010|ctx_2").hexdigest()[:16],
        ],
    })


def test_build_id_map_maps_legacy_to_new():
    frame = _frame()
    id_map, ambiguous = build_id_map(frame)
    assert not ambiguous
    assert len(id_map) == 2
    assert set(id_map.values()) == set(frame["row_id"])
    for legacy in id_map:
        assert legacy.startswith("ROW-") and legacy not in set(frame["row_id"])


def test_build_id_map_flags_ambiguous_legacy_ids():
    frame = pd.concat([_frame(), _frame().iloc[[0]]], ignore_index=True)
    # duplicate natural key -> two rows share a legacy id -> ambiguous ONLY if
    # they map to different new ids; force that by changing the twin's context
    frame.loc[2, "src_context_id"] = "ctx_3"
    frame.loc[2, "row_id"] = "ROW-" + hashlib.md5(
        b"bdc|0001287750-26-000010|ctx_3").hexdigest()[:16]
    id_map, ambiguous = build_id_map(frame)
    assert ambiguous  # the shared legacy id must be refused, not guessed


def _write_leaf(dirpath, row_id_value):
    leaf = {
        "cik": "0001287750",
        "fix_class": "all_pik_normalization",
        "template": {"row_selector": {"row_id": row_id_value},
                     "cash_rate": 0.0, "pik_rate": 14.0},
    }
    p = dirpath / "0001287750"
    p.mkdir(parents=True, exist_ok=True)
    f = p / "all_pik_normalization.json"
    f.write_text(json.dumps(leaf, indent=2), encoding="utf-8")
    return f


def test_restamp_rewrites_matching_leaf(tmp_path):
    frame = _frame()
    id_map, _ = build_id_map(frame)
    legacy = next(iter(id_map))
    leaf_file = _write_leaf(tmp_path, legacy)
    changed, unresolved = restamp_leaves(tmp_path, id_map,
                                         current_ids=set(frame["row_id"]),
                                         apply=True)
    assert changed == 1 and not unresolved
    data = json.loads(leaf_file.read_text(encoding="utf-8-sig"))
    assert data["template"]["row_selector"]["row_id"] == id_map[legacy]


def test_restamp_dry_run_writes_nothing(tmp_path):
    frame = _frame()
    id_map, _ = build_id_map(frame)
    legacy = next(iter(id_map))
    leaf_file = _write_leaf(tmp_path, legacy)
    before = leaf_file.read_text(encoding="utf-8")
    changed, unresolved = restamp_leaves(tmp_path, id_map,
                                         current_ids=set(frame["row_id"]),
                                         apply=False)
    assert changed == 1
    assert leaf_file.read_text(encoding="utf-8") == before


def test_restamp_skips_current_ids_and_pulled_dirs(tmp_path):
    frame = _frame()
    id_map, _ = build_id_map(frame)
    current = frame["row_id"].iloc[0]
    _write_leaf(tmp_path, current)  # already new-style: idempotent skip
    pulled = tmp_path / "0009999999" / "_pulled_x_20260101"
    pulled.mkdir(parents=True)
    (pulled / "leaf.json").write_text(
        json.dumps({"template": {"row_selector": {"row_id": "ROW-" + "0" * 16}}}),
        encoding="utf-8")
    changed, unresolved = restamp_leaves(tmp_path, id_map,
                                         current_ids=set(frame["row_id"]),
                                         apply=True)
    assert changed == 0 and not unresolved


def test_restamp_reports_unknown_id(tmp_path):
    frame = _frame()
    id_map, _ = build_id_map(frame)
    _write_leaf(tmp_path, "ROW-" + "f" * 16)  # matches nothing
    changed, unresolved = restamp_leaves(tmp_path, id_map,
                                         current_ids=set(frame["row_id"]),
                                         apply=True)
    assert changed == 0
    assert len(unresolved) == 1


def test_restamp_preserves_bom(tmp_path):
    frame = _frame()
    id_map, _ = build_id_map(frame)
    legacy = next(iter(id_map))
    leaf_file = _write_leaf(tmp_path, legacy)
    raw = leaf_file.read_bytes()
    leaf_file.write_bytes(b"\xef\xbb\xbf" + raw)  # add BOM
    restamp_leaves(tmp_path, id_map, current_ids=set(frame["row_id"]),
                   apply=True)
    assert leaf_file.read_bytes().startswith(b"\xef\xbb\xbf")
```

- [x] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_restamp_row_selectors.py -v`
Expected: FAIL with ImportError (module does not exist).

- [x] **Step 3: Implement the script**

Create `scripts/restamp_row_selectors.py`:

```python
"""One-time migration: restamp correction-leaf row_selector row_id values
from legacy natural-key hashes to anchor-based ids (2026-08-22 row_id swap).

Reads the published unified holdings (which already carries the NEW
anchor-based row_id), recomputes what each row's LEGACY id was (md5 of
compute_natural_keys), and rewrites any leaf whose row_selector cites a
legacy id. Fail-loud: ambiguous legacy ids (one legacy id -> multiple new
ids) and unknown ids are reported and exit non-zero; they are never guessed.

Usage:
    python scripts/restamp_row_selectors.py            # dry run (default)
    python scripts/restamp_row_selectors.py --apply    # rewrite leaf files
"""

import argparse
import hashlib
import json
import logging
import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

logging.basicConfig(level=logging.INFO, format="%(levelname)-8s %(message)s")
logger = logging.getLogger("restamp")

_BOM = b"\xef\xbb\xbf"


def _legacy_hash(key: str) -> str:
    return "ROW-" + hashlib.md5(key.encode()).hexdigest()[:16]


def build_id_map(frame: pd.DataFrame) -> tuple[dict, list]:
    """Map legacy natural-key row_id -> current published row_id.

    Returns (id_map, ambiguous) where ambiguous lists legacy ids that map to
    more than one distinct current id (refused, never guessed).
    """
    from pipeline.position_id_registry import compute_natural_keys

    legacy = compute_natural_keys(frame).map(_legacy_hash)
    current = frame["row_id"].fillna("").astype(str)
    pairs = pd.DataFrame({"legacy": legacy.values, "current": current.values})
    grouped = pairs.groupby("legacy")["current"].nunique()
    ambiguous = sorted(grouped[grouped > 1].index)
    ok = pairs[~pairs["legacy"].isin(ambiguous)].drop_duplicates("legacy")
    id_map = dict(zip(ok["legacy"], ok["current"]))
    # identity mappings are useless noise (legacy == current cannot happen
    # for anchored rows, but natural_key-basis rows map to themselves)
    id_map = {k: v for k, v in id_map.items() if k != v}
    return id_map, ambiguous


def _iter_selectors(leaf: dict):
    sel = ((leaf.get("template") or {}).get("row_selector"))
    if isinstance(sel, dict):
        yield sel
    elif isinstance(sel, list):
        for s in sel:
            if isinstance(s, dict):
                yield s


def restamp_leaves(corrections_dir: Path, id_map: dict,
                   current_ids: set, apply: bool) -> tuple[int, list]:
    """Rewrite legacy row_id selector values. Returns (n_changed, unresolved)."""
    changed = 0
    unresolved: list[tuple[str, str]] = []
    for leaf_path in sorted(Path(corrections_dir).glob("*/*.json")):
        if leaf_path.parent.name.startswith("_"):
            continue
        raw = leaf_path.read_bytes()
        had_bom = raw.startswith(_BOM)
        try:
            leaf = json.loads(raw.decode("utf-8-sig"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            logger.warning("skipping unreadable leaf %s: %s", leaf_path, exc)
            continue
        touched = False
        for sel in _iter_selectors(leaf):
            rid = str(sel.get("row_id") or "").strip()
            if not rid:
                continue
            if rid in current_ids:
                logger.info("current id, no change: %s (%s)",
                            rid, leaf_path.name)
                continue
            if rid in id_map:
                logger.info("restamp %s: %s -> %s",
                            leaf_path.relative_to(corrections_dir),
                            rid, id_map[rid])
                sel["row_id"] = id_map[rid]
                touched = True
            else:
                unresolved.append((str(leaf_path), rid))
        if touched:
            changed += 1
            if apply:
                out = json.dumps(leaf, indent=2, ensure_ascii=False).encode("utf-8")
                leaf_path.write_bytes((_BOM + out) if had_bom else out)
    return changed, unresolved


def main() -> int:
    from pipeline import config

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true",
                    help="Rewrite leaf files (default: dry run)")
    ap.add_argument("--holdings", type=Path, default=None,
                    help="Unified holdings CSV/parquet (default: published)")
    ap.add_argument("--corrections-dir", type=Path,
                    default=config.AGENT_B2_CORRECTIONS_DIR)
    args = ap.parse_args()

    holdings = args.holdings
    if holdings is None:
        pq = config.UNIFIED_HOLDINGS_FILE.with_suffix(".parquet")
        holdings = pq if pq.exists() else config.UNIFIED_HOLDINGS_FILE
    logger.info("loading holdings: %s", holdings)
    if str(holdings).endswith(".parquet"):
        frame = pd.read_parquet(holdings)
    else:
        frame = pd.read_csv(holdings, dtype=str)
    if "row_id" not in frame.columns:
        logger.error("holdings frame has no row_id column -- rebuild first")
        return 1

    id_map, ambiguous = build_id_map(frame)
    logger.info("id map: %d legacy->new entries, %d ambiguous legacy ids",
                len(id_map), len(ambiguous))

    changed, unresolved = restamp_leaves(
        args.corrections_dir, id_map,
        current_ids=set(frame["row_id"].fillna("").astype(str)),
        apply=args.apply)
    mode = "applied" if args.apply else "dry-run"
    logger.info("%s: %d leaf file(s) with restamped selectors", mode, changed)
    for path, rid in unresolved:
        logger.error("UNRESOLVED row_id %s in %s", rid, path)
    return 1 if unresolved else 0


if __name__ == "__main__":
    sys.exit(main())
```

- [x] **Step 4: Run tests**

Run: `python -m pytest tests/test_restamp_row_selectors.py -v`
Expected: all PASS. Check config attribute names first: `rg "AGENT_B2_CORRECTIONS_DIR|UNIFIED_HOLDINGS_FILE" pipeline/config.py` — adjust the two `config.` references if the constants live elsewhere (e.g. AGENT_B2_CORRECTIONS_DIR may be defined in agent_promoted; import from wherever it is defined).

- [x] **Step 5: Commit**

```bash
git add scripts/restamp_row_selectors.py tests/test_restamp_row_selectors.py
git commit -m "restamp_row_selectors: legacy->anchor row_id leaf migration

- maps md5(natural_key) legacy ids to published anchor ids from the
  rebuilt unified frame; ambiguous or unknown ids fail loud, never guessed
- dry-run by default; preserves per-file BOM state; skips _pulled_ dirs"
```

---

### Task 5: Operator phase — rebuild, audit, restamp, verify, document

No new code. This is the gated data migration. Run each gate; STOP and report to the owner on any gate failure. All commands from repo root.

- [x] **Step 1: Pre-flight**

```powershell
Get-Process | Where-Object { $_.ProcessName -match 'python|pytest' } | Select-Object Id, ProcessName, StartTime
```
Expected: no competing rebuild/pytest processes (this session's own excluded).

- [x] **Step 2: Preserve the pre-migration artifacts**

```powershell
New-Item -ItemType Directory -Force data\snapshots\pre_anchor_rowid_20260822
Copy-Item data\output\bdc_holdings.csv data\snapshots\pre_anchor_rowid_20260822\
Copy-Item data\output\private_markets_holdings.csv data\snapshots\pre_anchor_rowid_20260822\
```

- [x] **Step 3: Full cache re-extraction (background; ~2,775 filings, cache-only)**

```powershell
python scripts\rebuild_outputs.py --bdc-holdings
```
Run in background; expect tens of minutes to a few hours. Monitor the log for the `Cached BDC parse progress` lines.

- [x] **Step 4: HARD GATE — extraction drift audit (old vs new bdc_holdings)**

Using the DuckDB CLI (not inline Python), compare the snapshot against the rebuilt file:

```sql
-- row counts per accession
SELECT COALESCE(a.accession_number, b.accession_number) AS acc,
       COUNT(a.rn) AS old_rows, COUNT(b.rn) AS new_rows
FROM (SELECT accession_number, row_number() OVER () AS rn
      FROM read_csv_auto('data/snapshots/pre_anchor_rowid_20260822/bdc_holdings.csv', all_varchar=true)) a
FULL OUTER JOIN (SELECT accession_number, row_number() OVER () AS rn
      FROM read_csv_auto('data/output/bdc_holdings.csv', all_varchar=true)) b
  USING (accession_number)
GROUP BY 1 HAVING COUNT(a.rn) != COUNT(b.rn);
-- FV sums per accession
SELECT COALESCE(o.accession_number, n.accession_number) AS acc, o.fv AS old_fv, n.fv AS new_fv
FROM (SELECT accession_number, SUM(TRY_CAST(fair_value AS DOUBLE)) AS fv
      FROM read_csv_auto('data/snapshots/pre_anchor_rowid_20260822/bdc_holdings.csv', all_varchar=true) GROUP BY 1) o
FULL OUTER JOIN (SELECT accession_number, SUM(TRY_CAST(fair_value AS DOUBLE)) AS fv
      FROM read_csv_auto('data/output/bdc_holdings.csv', all_varchar=true) GROUP BY 1) n
  USING (accession_number)
WHERE COALESCE(o.fv,0) != COALESCE(n.fv,0);
```
Expected: zero rows from both queries (values identical; only the new column differs). **Any drift = STOP**: the extractor has drifted since the last build; per the scoping doc (risk 2), separate that drift from this migration — report to owner, do not proceed.

- [x] **Step 5: GATE — anchor coverage and uniqueness audit**

```sql
SELECT COUNT(*) AS rows,
       SUM(CASE WHEN COALESCE(src_context_id,'') = '' THEN 1 ELSE 0 END) AS no_ctx
FROM read_csv_auto('data/output/bdc_holdings.csv', all_varchar=true);
SELECT accession_number, src_context_id, COUNT(*) AS n
FROM read_csv_auto('data/output/bdc_holdings.csv', all_varchar=true)
WHERE COALESCE(src_context_id,'') != ''
GROUP BY 1, 2 HAVING COUNT(*) > 1 LIMIT 20;
```
Expected: `no_ctx` near zero (rows parsed fresh always carry a context); zero duplicate `(accession, context)` pairs. A handful of duplicates = investigate individually (filer pathology vs FV-split bug) before proceeding; systematic duplicates = STOP.

- [x] **Step 6: Rebuild unified (pass 1) and restamp**

```powershell
python scripts\rebuild_outputs.py --unified
python scripts\restamp_row_selectors.py            # dry run first, inspect output
python scripts\restamp_row_selectors.py --apply
python scripts\rebuild_outputs.py --unified        # pass 2: correction now applies under its new id
```
Expected: dry run resolves the single live row_id leaf (`0001287750/all_pik_normalization.json`), exit 0. Pass-1 rebuild logs a `noop` drift flag for that correction (expected, documented); pass-2 applies it.

- [x] **Step 7: GATE — corrections still apply**

Inspect `data/output/agent_fix_application_audit.csv`: every promoted correction/rule shows the same `rows_changed` as the pre-migration build; specifically `all_pik_normalization` for CIK 0001287750 has `rows_changed > 0` and no `noop` drift on pass 2.

- [x] **Step 8: GATE — semantic diff**

```powershell
python scripts\diff_outputs.py --semantic
```
Expected deltas: new columns (`src_context_id`, `row_id_basis`) and changed `row_id` values ONLY. Zero economic-value deltas. Document the output; baseline refresh is the owner's call per AGENTS.md governance (do not run snapshot_outputs.py).

- [x] **Step 9: Full test suite**

```powershell
python -m pytest --durations=50 --durations-min=0.5
```
Expected: green (record exact counts). Then re-confirm no production drift from the suite: `python scripts/diff_outputs.py --semantic` (backstop per AGENTS.md).

- [x] **Step 10: Documentation**

- `docs/reference/schemas.md`: document `src_context_id` (bdc_holdings.csv + unified; the XBRL contextRef of the winning dedup row; `''` = no anchor) and `row_id`/`row_id_basis` (anchor recipe, fallback, as-filed semantics, appended-not-in-constant).
- `docs/agent_changelog.md`: dated entry — what changed, the drift/uniqueness/correction gate results, new test counts, the pre-dirty `agent_promoted.py` edit left uncommitted, snapshot location.

```bash
git add docs/reference/schemas.md docs/agent_changelog.md docs/superpowers/plans/2026-08-22-anchor-row-id.md
git commit -m "docs: anchor-based row_id migration record

- schemas.md documents src_context_id and row_id/row_id_basis semantics
- changelog entry with migration gate results and test counts"
```

---

## Self-Review Notes

- Spec coverage: anchor recipe, fallback+basis, UNIFIED_COLUMNS placement, uniqueness gate, re-stamp, as-filed caveat, position-layer non-interference — all mapped to tasks 1-5. The scoping doc's broader provenance columns (src_facts etc.) are deliberately OUT of scope here.
- Known judgment calls encoded: `row_id_basis` appended (not staged) to avoid touching both staging SQL paths for a build-time-derived value; `compute_natural_keys` computed on the full frame for fallback determinism; `agent_promoted.py` edited but not committed (pre-dirty worktree rule).
- Type consistency: `_assign_row_ids(df) -> df` with two appended str columns used identically in Tasks 3-5; `build_id_map(frame) -> (dict, list)`; `restamp_leaves(dir, map, current_ids, apply) -> (int, list)` — consistent between Task 4 test and implementation.
