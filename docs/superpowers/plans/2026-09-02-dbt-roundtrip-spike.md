# dbt Round-Trip Spike Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Decide Phase 2 go/no-go of the production stack plan by replaying a live transform-layer defect class (duplicate XBRL dimension paths) through a minimal dbt-duckdb port and testing whether a model-boundary test failure round-trips into a B1-style blocker packet with better mechanism localization than the incumbent residual classifier.

**Architecture:** A harness script stages real BDC rows via the production code path (`staging_bdc._prepare_bdc`), extracts a 3-CIK slice plus deterministic ground truth (rows the production `bdc_dim_ranked` CTE drops). A 2-model dbt project (`stg_bdc_holdings` -> `bdc_dim_deduped`) reads that slice; a singular dbt test with `store_failures` fires at the staging boundary on the duplicate groups. A converter turns the stored-failure rows into a packet; a comparison script proves the packet's group set exactly equals ground truth and contrasts its localization against `source_reconciliation_source_only_detail.csv`.

**Tech Stack:** dbt-duckdb (new install), DuckDB (existing), Python 3, pytest.

**Spec:** `docs/production_stack/production_data_stack_plan.md` — Phase 2 "SPIKE SUCCESS CRITERION" bullet. Kill criteria (any one = keep Python SQL):
1. Stored-failure rows cannot carry provenance keys (`source_row_id` = `src:{accession}:{src_context_id}`).
2. The packet is not strictly better localized than the residual classifier's treatment of the same rows.
3. Porting the one CTE cluster costs more than ~1 day of framework friction.

## Global Constraints

- **No SEC/EDGAR network calls.** The ONLY permitted network operation is `pip install dbt-duckdb` (Task 1).
- **No writes to `data/output/` or `frontend/public/data/`.** All spike artifacts go under `spikes/dbt_roundtrip/artifacts/` (git-ignored). Those two production dirs are read-only inputs.
- **ASCII-only** in all print/log output (Windows cp1252).
- **DuckDB SQL for anything >10K rows.** No pandas `.apply()`/`.iterrows()`.
- **Do not modify any file under `pipeline/`.** The spike imports production modules read-only.
- **Time-box:** if a single task exceeds ~4 hours of framework friction (not data debugging), STOP, record the friction in `spikes/dbt_roundtrip/NOTES.md`, and jump to Task 6 — friction is itself a spike result (kill criterion 3).
- **Ergonomics log:** append a timestamped line to `spikes/dbt_roundtrip/NOTES.md` at the start and end of every task (`[2026-09-02 14:05] Task 3 start`). This is the kill-criterion-3 evidence; do not skip it.
- Shell is PowerShell 5.1: no `&&` chaining; use `;` or separate commands. Run all `dbt` commands from `spikes/dbt_roundtrip/` with `$env:DBT_PROFILES_DIR = "."`.

## File Structure

```
spikes/dbt_roundtrip/            # git-TRACKED spike root (delete whole dir if no-go)
  .gitignore                     # ignores artifacts/, target/, logs/, dbt_packages/
  README.md                      # what this spike is, how to rerun, link to spec
  NOTES.md                       # ergonomics/friction log (kill criterion 3 evidence)
  extract_staged.py              # harness: stage + slice + ground truth  (Task 2)
  dbt_project.yml                # dbt project                            (Task 3)
  profiles.yml                   # duckdb profile -> artifacts/spike.duckdb
  models/sources.yml             # external_location parquet source
  models/stg_bdc_holdings.sql    # staging model + normalized key columns
  models/bdc_dim_deduped.sql     # ported production dedup CTE
  models/schema.yml              # test on dedup output
  tests/duplicate_dimension_paths.sql  # singular boundary test (store_failures)
  failures_to_packet.py          # stored failures -> packet JSON         (Task 4)
  test_failures_to_packet.py     # pytest for the converter               (Task 4)
  compare_and_verdict.py         # equality + incumbent comparison + hash (Task 5)
  artifacts/                     # git-ignored: parquet, duckdb, csv, json outputs
docs/production_stack/dbt_spike_report.md   # decision report             (Task 6)
```

Production references (read-only):
- `pipeline/unified_holdings.py:998-1066` — `no_sub_dupes` + `bdc_dim_ranked`/`no_dim_dupes` CTEs being ported (the defect class: risk-register item "Duplicate facts from multiple XBRL dimension paths").
- `pipeline/staging_bdc.py:381` — `_prepare_bdc(bdc_df=None, bdc_file=None, raw_exclusions=None, raw_exclusion_audits=None) -> pd.DataFrame`.
- `pipeline/unified_holdings.py:826-843` — the production call pattern the harness mirrors (promoted corrections loaded via `agent_promoted`).
- `data/output/source_reconciliation_source_only_detail.csv` (19 cols incl. `source_row_id`, `mechanism`) and `source_reconciliation_residual_classification.csv` (18 cols) — incumbent vocabulary; mechanism taxonomy in `pipeline/source_reconciliation.py:193-302` (includes `documented_duplicate_dimension_path`).
- `data/output/bdc_holdings.parquet` (115MB, exists) — staging input.

---

### Task 1: Scaffold + dbt install

**Files:**
- Create: `spikes/dbt_roundtrip/.gitignore`, `spikes/dbt_roundtrip/README.md`, `spikes/dbt_roundtrip/NOTES.md`

**Interfaces:**
- Produces: the `spikes/dbt_roundtrip/` dir all later tasks write into; a working `dbt` CLI on PATH.

- [ ] **Step 1: Create the spike directory and .gitignore**

`spikes/dbt_roundtrip/.gitignore`:
```
artifacts/
target/
logs/
dbt_packages/
*.duckdb
*.duckdb.wal
```

`spikes/dbt_roundtrip/README.md`:
```markdown
# dbt Round-Trip Spike (Phase 2 go/no-go)

Replays the duplicate-dimension-path defect class through a 2-model
dbt-duckdb port of the `bdc_dim_ranked` CTE cluster
(`pipeline/unified_holdings.py:1029-1066`) and tests whether a boundary
test failure converts into a B1-style packet.

Spec + kill criteria: docs/production_stack/production_data_stack_plan.md (Phase 2).
Decision report: docs/production_stack/dbt_spike_report.md.

Rerun order:
1. python spikes/dbt_roundtrip/extract_staged.py
2. cd spikes/dbt_roundtrip; $env:DBT_PROFILES_DIR = "."; dbt run; dbt test --store-failures
3. python spikes/dbt_roundtrip/failures_to_packet.py
4. python spikes/dbt_roundtrip/compare_and_verdict.py

All artifacts land in spikes/dbt_roundtrip/artifacts/ (git-ignored).
Never writes to data/output/ or frontend/public/data/.
```

`spikes/dbt_roundtrip/NOTES.md`:
```markdown
# Spike ergonomics log (kill-criterion-3 evidence)

Append one line at start/end of each task: [YYYY-MM-DD HH:MM] Task N start|end - note.
Record every framework workaround (dbt quirk, config fight, docs gap) as its own line.
```

- [ ] **Step 2: Install dbt-duckdb**

Run: `pip install dbt-duckdb`
(Only permitted network call in this plan. dbt-core comes as a dependency.)

- [ ] **Step 3: Verify install**

Run: `dbt --version`
Expected: prints dbt-core and duckdb plugin versions without error. Record versions in NOTES.md.

- [ ] **Step 4: Commit**

```powershell
git add spikes/dbt_roundtrip/.gitignore spikes/dbt_roundtrip/README.md spikes/dbt_roundtrip/NOTES.md
git commit -m "spike(dbt): scaffold dbt round-trip spike dir"
```

---

### Task 2: Ground-truth extractor

**Files:**
- Create: `spikes/dbt_roundtrip/extract_staged.py`

**Interfaces:**
- Consumes: `staging_bdc._prepare_bdc(bdc_file=..., raw_exclusions=..., raw_exclusion_audits=...)`, `agent_promoted.load_promoted_corrections()` / `agent_promoted.raw_staging_exclusions()`, `data/output/bdc_holdings.parquet`.
- Produces (in `artifacts/`): `cik_selection.csv` (cols: cik, dup_rows, dup_fv); `staged_predim.parquet` (full staged schema for top-3 CIKs, post-sub-dedup — the exact input `bdc_dim_ranked` sees); `ground_truth_dropped.parquet` (rows production drops, `_dim_rank > 1`, plus `source_row_id`, `key_sig`); `ground_truth_groups.csv` (cols: `key_sig`, `group_size`). The `key_sig` string format is the cross-task join key: `concat_ws('|', cik, accession_number, CAST(report_date AS VARCHAR), norm_issuer, norm_instrument, fv/principal/shares as BIGINT strings)`.

- [ ] **Step 1: Write the extractor**

`spikes/dbt_roundtrip/extract_staged.py`:
```python
"""Spike harness: stage BDC rows via the production path, pick the 3 CIKs
with the most duplicate-dimension-path rows, and extract deterministic
ground truth (the rows production's bdc_dim_ranked CTE drops).

Read-only w.r.t. data/output/; writes only under spikes/dbt_roundtrip/artifacts/.
Exit code 2 if no duplicate groups exist (replay impossible for this class).
"""
import sys
import time
from pathlib import Path

import duckdb

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from pipeline import agent_promoted, staging_bdc  # noqa: E402
from pipeline.config import BDC_HOLDINGS_FILE, BDC_HOLDINGS_PARQUET_FILE  # noqa: E402

ART = Path(__file__).resolve().parent / "artifacts"

NORM = ("regexp_replace(lower(trim(COALESCE(CAST({c} AS VARCHAR), ''))), "
        "'[^a-z0-9]+', ' ', 'g')")

# Production dedup key: pipeline/unified_holdings.py bdc_dim_ranked (lines 1033-1047)
KEY_EXPRS = [
    "cik",
    "accession_number",
    "report_date",
    NORM.format(c="issuer_name"),
    NORM.format(c="instrument_description"),
    "ROUND(COALESCE(TRY_CAST(fair_value AS DOUBLE), 0), 0)",
    "ROUND(COALESCE(TRY_CAST(principal_amount AS DOUBLE), 0), 0)",
    "ROUND(COALESCE(TRY_CAST(shares_held AS DOUBLE), 0), 0)",
]
DIM_KEY = ", ".join(KEY_EXPRS)

# Production tiebreak order: pipeline/unified_holdings.py lines 1048-1053
DIM_ORDER = """
    LENGTH(COALESCE(CAST(issuer_name AS VARCHAR), '')),
    COALESCE(CAST(issuer_name AS VARCHAR), ''),
    COALESCE(CAST(bdc_investment_identifier AS VARCHAR), ''),
    COALESCE(CAST(accession_number AS VARCHAR), ''),
    COALESCE(CAST(src_context_id AS VARCHAR), '')
"""

KEY_SIG = (
    "concat_ws('|', cik, accession_number, CAST(report_date AS VARCHAR), "
    + NORM.format(c="issuer_name") + ", "
    + NORM.format(c="instrument_description") + ", "
    "CAST(CAST(ROUND(COALESCE(TRY_CAST(fair_value AS DOUBLE), 0), 0) AS BIGINT) AS VARCHAR), "
    "CAST(CAST(ROUND(COALESCE(TRY_CAST(principal_amount AS DOUBLE), 0), 0) AS BIGINT) AS VARCHAR), "
    "CAST(CAST(ROUND(COALESCE(TRY_CAST(shares_held AS DOUBLE), 0), 0) AS BIGINT) AS VARCHAR))"
)


def main() -> int:
    ART.mkdir(exist_ok=True)
    t0 = time.time()
    print("[1/5] Staging BDC rows via production path (staging_bdc._prepare_bdc) ...")
    raw_excl = agent_promoted.raw_staging_exclusions(
        agent_promoted.load_promoted_corrections())
    bdc_file = (BDC_HOLDINGS_PARQUET_FILE
                if BDC_HOLDINGS_PARQUET_FILE.exists() else BDC_HOLDINGS_FILE)
    bdc = staging_bdc._prepare_bdc(
        bdc_file=bdc_file, raw_exclusions=raw_excl, raw_exclusion_audits=[])
    print(f"      staged rows: {len(bdc)} in {time.time() - t0:.0f}s")

    con = duckdb.connect()
    con.register("bdc_part", bdc)
    sources = [r[0] for r in con.execute(
        "SELECT DISTINCT source FROM bdc_part").fetchall()]
    assert sources == ["bdc"], f"expected bdc-only staged frame, got {sources}"

    print("[2/5] Ranking CIKs by duplicate-dimension rows ...")
    con.execute(f"""
        COPY (
            SELECT cik, COUNT(*) AS dup_rows,
                   SUM(TRY_CAST(fair_value AS DOUBLE)) AS dup_fv
            FROM (SELECT *, COUNT(*) OVER (PARTITION BY {DIM_KEY}) AS _n
                  FROM bdc_part) t
            WHERE _n > 1
            GROUP BY cik ORDER BY dup_rows DESC, cik LIMIT 20
        ) TO '{(ART / "cik_selection.csv").as_posix()}' (HEADER)
    """)
    top = [r[0] for r in con.execute(
        f"SELECT cik FROM read_csv_auto('{(ART / 'cik_selection.csv').as_posix()}') "
        "ORDER BY dup_rows DESC, cik LIMIT 3").fetchall()]
    if not top:
        print("NO duplicate-dimension groups anywhere in staged data.")
        print("Replay impossible for this defect class; see plan Task 2 contingency.")
        return 2
    print(f"      top CIKs: {top}")
    cik_list = ", ".join(f"'{c}'" for c in top)

    print("[3/5] Applying subsidiary dedup (no_sub_dupes) to the CIK slice ...")
    # Verbatim port of pipeline/unified_holdings.py:998-1028; on a bdc-only
    # slice the upstream cross-source CTEs (deduped/no_dupes) are identity
    # because _source_count is always 1.
    n_i = NORM.format(c="nd2.issuer_name")
    n_i0 = NORM.format(c="nd.issuer_name")
    n_d = NORM.format(c="nd2.instrument_description")
    n_d0 = NORM.format(c="nd.instrument_description")
    con.execute(f"""
        CREATE TEMP TABLE bdc_top AS
        SELECT * FROM bdc_part WHERE cik IN ({cik_list});
        CREATE TEMP TABLE staged_predim AS
        SELECT * FROM bdc_top nd
        WHERE COALESCE(TRY_CAST(is_subsidiary AS INT), 0) = 0
           OR NOT EXISTS (
               SELECT 1 FROM bdc_top nd2
               WHERE nd2.cik = nd.cik
                 AND nd2.accession_number = nd.accession_number
                 AND nd2.report_date = nd.report_date
                 AND {n_i} = {n_i0}
                 AND {n_d} = {n_d0}
                 AND ROUND(COALESCE(TRY_CAST(nd2.fair_value AS DOUBLE), 0), 0)
                     = ROUND(COALESCE(TRY_CAST(nd.fair_value AS DOUBLE), 0), 0)
                 AND ROUND(COALESCE(TRY_CAST(nd2.principal_amount AS DOUBLE), 0), 0)
                     = ROUND(COALESCE(TRY_CAST(nd.principal_amount AS DOUBLE), 0), 0)
                 AND ROUND(COALESCE(TRY_CAST(nd2.shares_held AS DOUBLE), 0), 0)
                     = ROUND(COALESCE(TRY_CAST(nd.shares_held AS DOUBLE), 0), 0)
                 AND COALESCE(TRY_CAST(nd2.is_subsidiary AS INT), 0) = 0
           );
    """)
    con.execute(f"""
        COPY staged_predim TO '{(ART / "staged_predim.parquet").as_posix()}'
        (FORMAT PARQUET)
    """)

    print("[4/5] Computing ground truth (production _dim_rank > 1) ...")
    con.execute(f"""
        CREATE TEMP TABLE ranked AS
        SELECT *,
            'src:' || accession_number || ':' || COALESCE(src_context_id, '')
                AS source_row_id,
            {KEY_SIG} AS key_sig,
            ROW_NUMBER() OVER (
                PARTITION BY {DIM_KEY} ORDER BY {DIM_ORDER}
            ) AS _dim_rank
        FROM staged_predim;
        COPY (SELECT * FROM ranked WHERE _dim_rank > 1)
            TO '{(ART / "ground_truth_dropped.parquet").as_posix()}' (FORMAT PARQUET);
        COPY (SELECT key_sig, COUNT(*) AS group_size FROM ranked
              GROUP BY key_sig HAVING COUNT(*) > 1 ORDER BY key_sig)
            TO '{(ART / "ground_truth_groups.csv").as_posix()}' (HEADER);
    """)

    print("[5/5] Summary")
    n_slice, n_drop, n_grp = (
        con.execute("SELECT COUNT(*) FROM staged_predim").fetchone()[0],
        con.execute("SELECT COUNT(*) FROM ranked WHERE _dim_rank > 1").fetchone()[0],
        con.execute("SELECT COUNT(*) FROM (SELECT key_sig FROM ranked "
                    "GROUP BY key_sig HAVING COUNT(*) > 1)").fetchone()[0],
    )
    print(f"      slice rows: {n_slice}, dup groups: {n_grp}, dropped rows: {n_drop}")
    if n_drop == 0:
        print("Top CIKs have no dup rows after sub-dedup; see Task 2 contingency.")
        return 2
    null_ctx = con.execute(
        "SELECT COUNT(*) FROM ranked WHERE _dim_rank > 1 "
        "AND COALESCE(src_context_id, '') = ''").fetchone()[0]
    print(f"      dropped rows with empty src_context_id: {null_ctx} "
          "(these weaken kill criterion 1 if > 0)")
    print(f"done in {time.time() - t0:.0f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Run the extractor**

Run: `python spikes/dbt_roundtrip/extract_staged.py`
Expected: exit 0; prints staged row count (~600-700K), top-3 CIKs, nonzero dup groups and dropped rows; four files appear under `spikes/dbt_roundtrip/artifacts/`. Runtime a few minutes.

**Contingency (exit 2):** if no dup groups exist, the dimension-path defect class has been fully drained upstream and cannot be replayed. Record this in NOTES.md, then swap the defect class to subsidiary-duplicate rows: rerun ranking with `is_subsidiary`-flagged duplicate pairs (the `no_sub_dupes` NOT EXISTS predicate inverted) as the dup marker, and carry that key through Tasks 3-5 identically. If THAT is also empty, skip to Task 6 and report "no live transform-layer defect available to replay; spike inconclusive on criterion 2, decide on criteria 1+3 only."

- [ ] **Step 3: Sanity-check ground truth composition**

Run: `python -c "import duckdb; con=duckdb.connect(); print(con.execute(\"SELECT cik, report_date, COUNT(*) FROM 'spikes/dbt_roundtrip/artifacts/ground_truth_dropped.parquet' GROUP BY 1,2 ORDER BY 3 DESC LIMIT 10\").fetchall())"`
Expected: a handful of CIK-quarters with plausible counts (units to hundreds). Note the top CIK-quarter in NOTES.md — Task 5 compares the incumbent's view of exactly these.

- [ ] **Step 4: Commit**

```powershell
git add spikes/dbt_roundtrip/extract_staged.py
git commit -m "spike(dbt): ground-truth extractor for dimension-dup replay"
```

---

### Task 3: dbt project — models + boundary test + store-failures run

**Files:**
- Create: `spikes/dbt_roundtrip/dbt_project.yml`, `profiles.yml`, `models/sources.yml`, `models/stg_bdc_holdings.sql`, `models/bdc_dim_deduped.sql`, `tests/duplicate_dimension_paths.sql`, `tests/dedup_output_unique.sql`

**Interfaces:**
- Consumes: `artifacts/staged_predim.parquet` (Task 2).
- Produces: `artifacts/spike.duckdb` containing models `main.stg_bdc_holdings`, `main.bdc_dim_deduped`, and stored-failure table `main_dbt_test__audit.duplicate_dimension_paths` whose columns include `source_row_id`, `key_sig`, `group_size`, `cik`, `accession_number`, `report_date`, `fair_value`.

- [ ] **Step 1: Write the dbt project files**

`spikes/dbt_roundtrip/dbt_project.yml`:
```yaml
name: dbt_roundtrip
version: "0.1.0"
profile: dbt_roundtrip
model-paths: ["models"]
test-paths: ["tests"]
```

`spikes/dbt_roundtrip/profiles.yml`:
```yaml
dbt_roundtrip:
  target: spike
  outputs:
    spike:
      type: duckdb
      path: artifacts/spike.duckdb
      threads: 1
```

`spikes/dbt_roundtrip/models/sources.yml`:
```yaml
version: 2
sources:
  - name: spike
    schema: main
    tables:
      - name: staged_predim
        meta:
          external_location: "artifacts/staged_predim.parquet"
```

`spikes/dbt_roundtrip/models/stg_bdc_holdings.sql` (adds the normalized key + provenance columns; key expressions are verbatim from `bdc_dim_ranked`):
```sql
select
    *,
    'src:' || accession_number || ':' || coalesce(src_context_id, '') as source_row_id,
    regexp_replace(lower(trim(coalesce(cast(issuer_name as varchar), ''))),
                   '[^a-z0-9]+', ' ', 'g') as norm_issuer,
    regexp_replace(lower(trim(coalesce(cast(instrument_description as varchar), ''))),
                   '[^a-z0-9]+', ' ', 'g') as norm_instrument,
    round(coalesce(try_cast(fair_value as double), 0), 0) as fv_key,
    round(coalesce(try_cast(principal_amount as double), 0), 0) as principal_key,
    round(coalesce(try_cast(shares_held as double), 0), 0) as shares_key
from {{ source('spike', 'staged_predim') }}
```

`spikes/dbt_roundtrip/tests/duplicate_dimension_paths.sql` (the boundary test — a singular test returning every member row of every duplicate group; note it needs NO knowledge of the fix's tiebreak ordering):
```sql
{{ config(store_failures = true) }}
with grouped as (
    select *,
        count(*) over (
            partition by cik, accession_number, report_date,
                norm_issuer, norm_instrument, fv_key, principal_key, shares_key
        ) as group_size,
        concat_ws('|', cik, accession_number, cast(report_date as varchar),
                  norm_issuer, norm_instrument,
                  cast(cast(fv_key as bigint) as varchar),
                  cast(cast(principal_key as bigint) as varchar),
                  cast(cast(shares_key as bigint) as varchar)) as key_sig
    from {{ ref('stg_bdc_holdings') }}
)
select cik, entity_name, accession_number, report_date, source_row_id,
       issuer_name, instrument_description, fair_value,
       key_sig, group_size
from grouped
where group_size > 1
```

`spikes/dbt_roundtrip/models/bdc_dim_deduped.sql` (the ported production CTE, `pipeline/unified_holdings.py:1033-1066`, minus the N-PORT branch which is out of slice):
```sql
with ranked as (
    select *,
        row_number() over (
            partition by cik, accession_number, report_date,
                norm_issuer, norm_instrument, fv_key, principal_key, shares_key
            order by
                length(coalesce(cast(issuer_name as varchar), '')),
                coalesce(cast(issuer_name as varchar), ''),
                coalesce(cast(bdc_investment_identifier as varchar), ''),
                coalesce(cast(accession_number as varchar), ''),
                coalesce(cast(src_context_id as varchar), '')
        ) as _dim_rank
    from {{ ref('stg_bdc_holdings') }}
)
select * exclude (_dim_rank)
from ranked
where _dim_rank = 1
```

`spikes/dbt_roundtrip/tests/dedup_output_unique.sql` (second singular test — proves the fix model resolves the defect the boundary test found; no `models/schema.yml` is needed):
```sql
{{ config(store_failures = true) }}
select cik, accession_number, report_date, source_row_id
from (
    select *,
        count(*) over (
            partition by cik, accession_number, report_date,
                norm_issuer, norm_instrument, fv_key, principal_key, shares_key
        ) as group_size
    from {{ ref('bdc_dim_deduped') }}
)
where group_size > 1
```
(`models/schema.yml` is then not needed; do not create it.)

- [ ] **Step 2: Build the models**

```powershell
cd spikes/dbt_roundtrip
$env:DBT_PROFILES_DIR = "."
dbt run
```
Expected: 2 models built OK (`stg_bdc_holdings`, `bdc_dim_deduped`). Record any friction (source config fights, path issues) in NOTES.md.

- [ ] **Step 3: Run the tests with stored failures**

Run (still in `spikes/dbt_roundtrip`): `dbt test --store-failures`
Expected: `duplicate_dimension_paths` FAILS with N failing rows (N = total member rows of dup groups; this is EXPECTED RED — the replay firing at the boundary). `dedup_output_unique` PASSES (the ported CTE resolves it). Exit code nonzero is expected.

- [ ] **Step 4: Verify stored-failure rows carry provenance (kill criterion 1 check)**

Run: `python -c "import duckdb; con=duckdb.connect('spikes/dbt_roundtrip/artifacts/spike.duckdb', read_only=True); t=con.execute(\"select table_schema, table_name from information_schema.tables where table_name like '%duplicate_dimension_paths%'\").fetchone(); print(t); print(con.execute(f'select source_row_id, key_sig, group_size from \"{t[0]}\".\"{t[1]}\" limit 5').fetchall())"`
Expected: a schema like `main_dbt_test__audit`, and 5 rows each with a populated `src:{accession}:{context}` id. If `source_row_id` values are missing/empty here, kill criterion 1 has FIRED — record in NOTES.md and proceed straight to Task 6.

- [ ] **Step 5: Commit**

```powershell
git add spikes/dbt_roundtrip/dbt_project.yml spikes/dbt_roundtrip/profiles.yml spikes/dbt_roundtrip/models spikes/dbt_roundtrip/tests
git commit -m "spike(dbt): 2-model port + boundary test with stored failures"
```

---

### Task 4: Failures-to-packet converter (TDD)

**Files:**
- Create: `spikes/dbt_roundtrip/failures_to_packet.py`
- Test: `spikes/dbt_roundtrip/test_failures_to_packet.py`

**Interfaces:**
- Consumes: `artifacts/spike.duckdb` stored-failure table (Task 3 schema: `cik, entity_name, accession_number, report_date, source_row_id, issuer_name, instrument_description, fair_value, key_sig, group_size`).
- Produces: `build_packets(db_path: Path) -> list[dict]` and `artifacts/packet.json`. Each packet dict has keys: `schema_version` ("dbt-spike-packet.v0"), `mechanism` ("boundary_duplicate_dimension_path"), `boundary_model` ("stg_bdc_holdings"), `downstream_fix_model` ("bdc_dim_deduped"), `cik`, `entity_name`, `accession_number`, `report_date` (str), `key_sig`, `group_size` (int), `source_row_ids` (sorted list), `fair_values` (list, same order as source_row_ids), `is_blocking` (True), `recommended_action` ("dimension_path_dedup"). Task 5 joins packets to ground truth on `key_sig`.

- [ ] **Step 1: Write the failing test**

`spikes/dbt_roundtrip/test_failures_to_packet.py`:
```python
"""Converter tests. Fixture fakes the dbt stored-failure table; never
touches the real spike.duckdb or data/output/."""
from pathlib import Path

import duckdb
import pytest

import failures_to_packet as f2p

ROWS = [
    # (cik, entity, accession, report_date, source_row_id, issuer, instr, fv, key_sig, group_size)
    ("0000000001", "Fund A", "acc-1", "2025-12-31", "src:acc-1:ctxA", "Acme", "TL", 100.0, "k1", 3),
    ("0000000001", "Fund A", "acc-1", "2025-12-31", "src:acc-1:ctxB", "ACME", "TL", 100.0, "k1", 3),
    ("0000000001", "Fund A", "acc-1", "2025-12-31", "src:acc-1:ctxC", "Acme.", "TL", 100.0, "k1", 3),
    ("0000000002", "Fund B", "acc-2", "2025-09-30", "src:acc-2:ctxZ", "Beta", "EQ", 50.0, "k2", 2),
    ("0000000002", "Fund B", "acc-2", "2025-09-30", "src:acc-2:ctxY", "Beta", "EQ", 50.0, "k2", 2),
]


@pytest.fixture
def fake_db(tmp_path: Path) -> Path:
    db = tmp_path / "fake.duckdb"
    con = duckdb.connect(str(db))
    con.execute("CREATE SCHEMA main_dbt_test__audit")
    con.execute("""
        CREATE TABLE main_dbt_test__audit.duplicate_dimension_paths (
            cik VARCHAR, entity_name VARCHAR, accession_number VARCHAR,
            report_date VARCHAR, source_row_id VARCHAR, issuer_name VARCHAR,
            instrument_description VARCHAR, fair_value DOUBLE,
            key_sig VARCHAR, group_size BIGINT)
    """)
    con.executemany(
        "INSERT INTO main_dbt_test__audit.duplicate_dimension_paths VALUES "
        "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", ROWS)
    con.close()
    return db


def test_one_packet_per_group(fake_db):
    packets = f2p.build_packets(fake_db)
    assert len(packets) == 2


def test_packet_contents_and_provenance(fake_db):
    packets = {p["key_sig"]: p for p in f2p.build_packets(fake_db)}
    p = packets["k1"]
    assert p["schema_version"] == "dbt-spike-packet.v0"
    assert p["mechanism"] == "boundary_duplicate_dimension_path"
    assert p["boundary_model"] == "stg_bdc_holdings"
    assert p["downstream_fix_model"] == "bdc_dim_deduped"
    assert p["cik"] == "0000000001"
    assert p["report_date"] == "2025-12-31"
    assert p["group_size"] == 3
    assert p["source_row_ids"] == ["src:acc-1:ctxA", "src:acc-1:ctxB", "src:acc-1:ctxC"]
    assert len(p["fair_values"]) == 3
    assert p["is_blocking"] is True


def test_deterministic_order(fake_db):
    a = f2p.build_packets(fake_db)
    b = f2p.build_packets(fake_db)
    assert a == b
    assert [p["key_sig"] for p in a] == sorted(p["key_sig"] for p in a)


def test_missing_table_raises(tmp_path):
    db = tmp_path / "empty.duckdb"
    duckdb.connect(str(db)).close()
    with pytest.raises(f2p.NoFailuresTable):
        f2p.build_packets(db)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest spikes/dbt_roundtrip/test_failures_to_packet.py -v`
Expected: FAIL / collection error with `ModuleNotFoundError: failures_to_packet`.

- [ ] **Step 3: Write the converter**

`spikes/dbt_roundtrip/failures_to_packet.py`:
```python
"""Convert dbt stored-failure rows into B1-style blocker packets.

The point of the spike: prove that a model-boundary test failure carries
enough provenance to become an adjudicable packet mechanically. Output
vocabulary deliberately mirrors source_only_detail.csv fields
(source_row_id, mechanism, is_blocking, recommended_action) plus the two
fields the incumbent CANNOT provide: boundary_model / downstream_fix_model.
"""
import json
import sys
from pathlib import Path

import duckdb

ART = Path(__file__).resolve().parent / "artifacts"
TABLE_LIKE = "%duplicate_dimension_paths%"


class NoFailuresTable(RuntimeError):
    pass


def build_packets(db_path: Path) -> list[dict]:
    con = duckdb.connect(str(db_path), read_only=True)
    try:
        hit = con.execute(
            "SELECT table_schema, table_name FROM information_schema.tables "
            "WHERE table_name LIKE ? AND table_schema LIKE '%dbt_test__audit%'",
            [TABLE_LIKE]).fetchone()
        if hit is None:
            raise NoFailuresTable(
                f"no stored-failure table matching {TABLE_LIKE}; "
                "run: dbt test --store-failures")
        rows = con.execute(
            f'SELECT * FROM "{hit[0]}"."{hit[1]}" '
            "ORDER BY key_sig, source_row_id").fetchall()
        cols = [d[0] for d in con.description]
    finally:
        con.close()
    groups: dict[str, list[dict]] = {}
    for row in rows:
        rec = dict(zip(cols, row))
        groups.setdefault(rec["key_sig"], []).append(rec)
    packets = []
    for key_sig in sorted(groups):
        members = groups[key_sig]
        first = members[0]
        packets.append({
            "schema_version": "dbt-spike-packet.v0",
            "mechanism": "boundary_duplicate_dimension_path",
            "boundary_model": "stg_bdc_holdings",
            "downstream_fix_model": "bdc_dim_deduped",
            "cik": first["cik"],
            "entity_name": first["entity_name"],
            "accession_number": first["accession_number"],
            "report_date": str(first["report_date"]),
            "key_sig": key_sig,
            "group_size": len(members),
            "source_row_ids": [m["source_row_id"] for m in members],
            "fair_values": [m["fair_value"] for m in members],
            "is_blocking": True,
            "recommended_action": "dimension_path_dedup",
        })
    return packets


def main() -> int:
    packets = build_packets(ART / "spike.duckdb")
    out = ART / "packet.json"
    out.write_text(json.dumps(packets, indent=2, default=str),
                   encoding="utf-8")
    print(f"wrote {len(packets)} packets to {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest spikes/dbt_roundtrip/test_failures_to_packet.py -v`
Expected: 4 passed.

- [ ] **Step 5: Run against the real spike database**

Run: `python spikes/dbt_roundtrip/failures_to_packet.py`
Expected: `wrote N packets` where N equals the dup-group count printed by Task 2's extractor. Spot-check: `artifacts/packet.json` first packet has real `src:{accession}:{context}` ids.

- [ ] **Step 6: Commit**

```powershell
git add spikes/dbt_roundtrip/failures_to_packet.py spikes/dbt_roundtrip/test_failures_to_packet.py
git commit -m "spike(dbt): stored-failures -> B1-style packet converter (TDD)"
```

---

### Task 5: Equality proof, incumbent comparison, determinism

**Files:**
- Create: `spikes/dbt_roundtrip/compare_and_verdict.py`

**Interfaces:**
- Consumes: `artifacts/packet.json`, `artifacts/ground_truth_groups.csv`, `artifacts/ground_truth_dropped.parquet`, `artifacts/spike.duckdb`, `data/output/source_reconciliation_source_only_detail.csv`, `data/output/source_reconciliation_residual_classification.csv` (read-only).
- Produces: `artifacts/verdict.json` with keys `groups_match` (bool), `packet_groups` (int), `ground_truth_groups` (int), `dropped_row_identity_match` (bool), `incumbent_rows` (list of dicts), `dedup_output_hash` (str). Console PASS/FAIL summary.

- [ ] **Step 1: Write the comparison script**

`spikes/dbt_roundtrip/compare_and_verdict.py`:
```python
"""Decisive spike checks.

1. Group equality: packet key_sig set == ground-truth key_sig set
   (kill criterion 2 gate: the boundary test found exactly what
   production drops -- no more, no less).
2. Dropped-row identity: ground-truth dropped source_row_ids are a
   subset of packet source_row_ids, and counts reconcile as
   sum(group_size - 1) == dropped rows.
3. Incumbent view: what mechanism/localization does the residual
   classifier hold for the spike CIKs today (read-only query).
4. Determinism hash of bdc_dim_deduped (run twice via --hash-only to
   compare across two dbt builds).
"""
import json
import sys
from pathlib import Path

import duckdb

HERE = Path(__file__).resolve().parent
ART = HERE / "artifacts"
REPO = HERE.parents[1]
DETAIL = REPO / "data/output/source_reconciliation_source_only_detail.csv"
RESID = REPO / "data/output/source_reconciliation_residual_classification.csv"


def dedup_hash() -> str:
    con = duckdb.connect(str(ART / "spike.duckdb"), read_only=True)
    try:
        return con.execute(
            "SELECT md5(string_agg(source_row_id, ',' ORDER BY source_row_id)) "
            "FROM main.bdc_dim_deduped").fetchone()[0]
    finally:
        con.close()


def main() -> int:
    if "--hash-only" in sys.argv:
        print(f"dedup_output_hash: {dedup_hash()}")
        return 0

    packets = json.loads((ART / "packet.json").read_text(encoding="utf-8"))
    pkt_sigs = {p["key_sig"] for p in packets}
    pkt_row_ids = {rid for p in packets for rid in p["source_row_ids"]}
    ciks = sorted({p["cik"] for p in packets})

    con = duckdb.connect()
    gt_sigs = {r[0] for r in con.execute(
        f"SELECT key_sig FROM read_csv_auto('{(ART / 'ground_truth_groups.csv').as_posix()}')"
    ).fetchall()}
    gt_dropped = {r[0] for r in con.execute(
        f"SELECT source_row_id FROM '{(ART / 'ground_truth_dropped.parquet').as_posix()}'"
    ).fetchall()}

    groups_match = pkt_sigs == gt_sigs
    dropped_subset = gt_dropped <= pkt_row_ids
    counts_ok = sum(p["group_size"] - 1 for p in packets) == len(gt_dropped)

    cik_list = ", ".join(f"'{c}'" for c in ciks)
    incumbent = [dict(zip([d[0] for d in con.description], row))
                 for row in con.execute(f"""
        SELECT mechanism, disposition, is_blocking, COUNT(*) AS n
        FROM read_csv_auto('{DETAIL.as_posix()}')
        WHERE cik IN ({cik_list}) GROUP BY 1, 2, 3 ORDER BY n DESC
    """).fetchall()] if DETAIL.exists() else []
    resid = [dict(zip([d[0] for d in con.description], row))
             for row in con.execute(f"""
        SELECT mechanism, residual_class, status, COUNT(*) AS n
        FROM read_csv_auto('{RESID.as_posix()}')
        WHERE cik IN ({cik_list}) GROUP BY 1, 2, 3 ORDER BY n DESC
    """).fetchall()] if RESID.exists() else []

    verdict = {
        "groups_match": groups_match,
        "packet_groups": len(pkt_sigs),
        "ground_truth_groups": len(gt_sigs),
        "dropped_row_identity_match": dropped_subset and counts_ok,
        "spike_ciks": ciks,
        "incumbent_rows": incumbent,
        "incumbent_residual_rows": resid,
        "dedup_output_hash": dedup_hash(),
    }
    (ART / "verdict.json").write_text(
        json.dumps(verdict, indent=2, default=str), encoding="utf-8")
    print(f"groups_match: {groups_match} "
          f"(packet {len(pkt_sigs)} vs ground truth {len(gt_sigs)})")
    print(f"dropped_row_identity_match: {dropped_subset and counts_ok}")
    print(f"incumbent mechanisms for spike CIKs: "
          f"{[r['mechanism'] for r in incumbent][:8]}")
    print(f"dedup_output_hash: {verdict['dedup_output_hash']}")
    print("wrote artifacts/verdict.json")
    return 0 if (groups_match and dropped_subset and counts_ok) else 1


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Run the comparison**

Run: `python spikes/dbt_roundtrip/compare_and_verdict.py`
Expected: `groups_match: True`, `dropped_row_identity_match: True`, exit 0. If False: diagnose before proceeding — likely a key-expression divergence between the dbt SQL and `extract_staged.py` (both must stay verbatim to `bdc_dim_ranked`); use superpowers:systematic-debugging, fix, rerun `dbt run; dbt test --store-failures`, reconvert, recompare. A genuine, non-reconcilable mismatch is itself a spike finding (record it).

- [ ] **Step 3: Determinism check (twin dbt build)**

```powershell
cd spikes/dbt_roundtrip
$env:DBT_PROFILES_DIR = "."
python compare_and_verdict.py --hash-only
dbt run
python compare_and_verdict.py --hash-only
```
Expected: the two printed hashes are IDENTICAL. Record both in NOTES.md. A mismatch means the ported ORDER BY chain is not stable under dbt materialization — a serious finding against migration; record it prominently.

- [ ] **Step 4: Read the incumbent comparison**

Open `artifacts/verdict.json`; for the spike CIKs, note what the incumbent artifacts say about duplicate-dimension rows (expect `documented_duplicate_dimension_path` or nothing, with no boundary/model attribution and no fix linkage). Write 3-5 sentences in NOTES.md answering: "For these exact rows, is `boundary_model` + `downstream_fix_model` + per-group `source_row_ids` strictly more actionable than the incumbent's mechanism label?" This is the kill-criterion-2 evidence.

- [ ] **Step 5: Commit**

```powershell
git add spikes/dbt_roundtrip/compare_and_verdict.py
git commit -m "spike(dbt): equality proof + incumbent comparison + twin-build hash"
```

---

### Task 6: Decision report + changelog

**Files:**
- Create: `docs/production_stack/dbt_spike_report.md`
- Modify: `docs/agent_changelog.md` (append entry at top, after the header `---`)

**Interfaces:**
- Consumes: `artifacts/verdict.json`, `NOTES.md` (ergonomics log), all prior task outcomes.

- [ ] **Step 1: Write the report**

`docs/production_stack/dbt_spike_report.md` — fill every `<...>` from actual artifacts; no placeholders may survive:
```markdown
# dbt Round-Trip Spike Report

Date: <run date>
Spec: production_data_stack_plan.md, Phase 2 spike criterion.
Code: spikes/dbt_roundtrip/ (branch <branch>, commits <first>..<last>)

## Verdict: <GO for phase 2 | NO-GO - keep Python SQL | INCONCLUSIVE>

| Kill criterion | Result | Evidence |
|---|---|---|
| 1. Stored failures carry provenance keys | <PASS/FAIL> | <N> failure rows, <M> with populated source_row_id (artifacts/verdict.json) |
| 2. Packet strictly better localized than incumbent | <PASS/FAIL> | packet: boundary_model+fix_model+<G> groups vs incumbent: <mechanisms found> |
| 3. Port friction under ~1 day | <PASS/FAIL> | NOTES.md log: <hours> total, <k> workarounds |

## Replay facts
- Defect class: duplicate XBRL dimension paths (risk-register item).
- Spike CIKs: <list>. Dup groups: <G>. Dropped rows: <D>.
- groups_match: <bool>; dropped_row_identity_match: <bool>.
- Twin-build hash: <equal/UNEQUAL> (<hash>).

## Ergonomics findings
<bullets from NOTES.md: what dbt made easy, what it fought, what a full
build_unified_holdings port (~15 CTEs) would cost by extrapolation>

## Caveats
- Single defect class, 3 CIKs, BDC-only slice; N-PORT branch and the
  cross-source dedup CTEs were not ported.
- source_row_id here lacks the incumbent's _{periodSuffix}; join on
  accession+context prefix when comparing to source_only_detail.csv.
- Framework choice (dbt vs SQLMesh) is NOT decided by this spike; if
  verdict is GO on criteria but ergonomics were poor, run the same replay
  on SQLMesh before committing (plan section 7).

## Recommendation
<2-4 sentences: proceed to phase 2 as planned / keep Python SQL and close
phase 2 / run SQLMesh variant first. State residual risk.>
```

- [ ] **Step 2: Append the changelog entry**

Append to `docs/agent_changelog.md` directly under the header `---` (newest-first convention):
```markdown
## <date> - dbt round-trip spike executed (phase 2 go/no-go)

- Spike code: spikes/dbt_roundtrip/ (2 dbt models, boundary test with store_failures, packet converter + equality proof). Report: docs/production_stack/dbt_spike_report.md.
- Verdict: <verdict>. Kill criteria: 1 <P/F>, 2 <P/F>, 3 <P/F>.
- Replayed duplicate-dimension-path class on CIKs <list>: <G> groups, <D> dropped rows; packet/ground-truth match: <bool>; twin-build hash <equal/unequal>.
- No production outputs touched (all artifacts under spikes/dbt_roundtrip/artifacts/, git-ignored). New dependency installed: dbt-duckdb (spike-only; not added to requirements.txt).
- Tests: 4 converter tests (pytest spikes/dbt_roundtrip/test_failures_to_packet.py). Full suite NOT run (spike touches no pipeline code).

---
```

- [ ] **Step 3: Verify no production drift**

Run: `python scripts/diff_outputs.py --semantic`
Expected: zero deltas (the spike never writes to `data/output/`). If deltas appear, something violated the constraint — investigate before committing.

- [ ] **Step 4: Commit**

```powershell
git add docs/production_stack/dbt_spike_report.md docs/agent_changelog.md
git commit -m "docs: dbt round-trip spike report + verdict"
```

---

## Self-Review Notes

- Spec coverage: the Phase 2 spike criterion's three demands — failure materializes as queryable rows (Task 3 step 4), rows convert to a B1-bundlable packet (Task 4), localization strictly better than the residual classifier (Task 5 step 4) — plus the "keep Python SQL is a valid outcome" clause (Task 6 verdict options) are each mapped to a task. Ergonomics/kill-criterion 3 is covered by the NOTES.md log mandated in Global Constraints.
- The dbt/extractor key SQL is verbatim from `bdc_dim_ranked` in both places; the equality proof (Task 5) is the guard against transcription drift between them.
- Deliberately out of scope (recorded in report caveats): SQLMesh comparison, seed-fit for correction stores, N-PORT branch, full CTE-chain port.
